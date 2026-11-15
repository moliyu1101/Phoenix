from __future__ import annotations

import asyncio
import json
from typing import Protocol

import httpx

from .budget import Ledger, upper_token_estimate
from .config import ModelProfile, Settings
from .domain import BudgetExceeded, Completion, ContextExceeded, ToolCall, now
from .store import Store


class Provider(Protocol):
    async def complete(self, profile: ModelProfile, messages: list[dict], tools: list[dict]) -> Completion: ...


def chat_messages(messages: list[dict]) -> list[dict]:
    result = []
    for message in messages:
        result.append({k: v for k, v in message.items() if not k.startswith('_')})
    return result


def anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system = '\n\n'.join(str(m['content']) for m in messages if m['role'] == 'system')
    result: list[dict] = []
    for m in messages:
        role = m['role']
        if role == 'system':
            continue
        if role == 'tool':
            block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
            if result and result[-1]['role'] == 'user' and isinstance(result[-1]['content'], list):
                result[-1]['content'].append(block)
            else:
                result.append({'role': 'user', 'content': [block]})
        elif role == 'assistant':
            if '_anthropic_content' in m:
                content = m['_anthropic_content']
            else:
                content = []
                if m.get('content'):
                    content.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    content.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'],
                                    'input': json.loads(call['function']['arguments'])})
                if not content:
                    content = [{'type': 'text', 'text': '(no text)'}]
            result.append({'role': 'assistant', 'content': content})
        else:
            content = [{'type': 'text', 'text': m['content']}]
            if result and result[-1]['role'] == 'user':
                result[-1]['content'].extend(content)
            else:
                result.append({'role': 'user', 'content': content})
    return system, result


class HTTPProvider:
    """Direct model transport. No CLI, daemon, or external agent subprocess."""
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.transport = transport

    async def complete(self, profile: ModelProfile, messages: list[dict], tools: list[dict]) -> Completion:
        if not profile.model:
            raise ValueError('Configure the model ID before starting a live run')
        headers = {'Content-Type': 'application/json'}
        if profile.protocol == 'anthropic':
            system, body_messages = anthropic_messages(messages)
            headers.update({'x-api-key': profile.key, 'anthropic-version': '2023-06-01'})
            body = {'model': profile.model, 'system': system, 'messages': body_messages,
                    'max_tokens': profile.output_tokens}
            if tools:
                body['tools'] = [{'name': t['function']['name'], 'description': t['function']['description'],
                                  'input_schema': t['function']['parameters']} for t in tools]
            endpoint = profile.base_url.rstrip('/') + '/messages'
        else:
            if profile.key:
                headers['Authorization'] = 'Bearer ' + profile.key
            body = {'model': profile.model, 'messages': chat_messages(messages),
                    profile.chat_token_parameter: profile.output_tokens}
            if tools:
                body['tools'] = tools
            endpoint = profile.base_url.rstrip('/') + '/chat/completions'
        # No blind retries: a timed-out POST may already have been billed.
        async with httpx.AsyncClient(transport=self.transport, timeout=profile.timeout_seconds,
                                     follow_redirects=False, trust_env=False) as client:
            response = await client.post(endpoint, headers=headers, json=body)
            if response.status_code >= 400:
                # Avoid reflecting API keys or provider debug payloads into transcripts.
                raise RuntimeError(f'Model endpoint returned HTTP {response.status_code}')
            if response.status_code != 200:
                raise RuntimeError(f'Unexpected model response HTTP {response.status_code}')
            data = response.json()
        if profile.protocol == 'anthropic':
            blocks = data.get('content', [])
            text = '\n'.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            calls = [ToolCall(id=b['id'], name=b['name'], arguments=b['input'])
                     for b in blocks if b.get('type') == 'tool_use']
            assistant = {'role': 'assistant', 'content': text, '_anthropic_content': blocks}
            if calls:
                assistant['tool_calls'] = [as_chat_call(c) for c in calls]
            usage = data.get('usage') or {}
            # Cached input is still context; use the total input accounted by the provider.
            inp = usage.get('input_tokens')
            if inp is not None:
                inp += usage.get('cache_creation_input_tokens', 0) + usage.get('cache_read_input_tokens', 0)
            return Completion(text=text, calls=calls, input_tokens=inp, output_tokens=usage.get('output_tokens'),
                              assistant=assistant)
        message = data['choices'][0]['message']
        calls = []
        for call in message.get('tool_calls') or []:
            arguments = json.loads(call['function']['arguments'])
            if not isinstance(arguments, dict):
                raise ValueError('Tool arguments must be a JSON object')
            calls.append(ToolCall(id=call['id'], name=call['function']['name'], arguments=arguments))
        # Preserve provider extensions such as reasoning_content, but not response-only fields.
        assistant = {k: v for k, v in message.items() if k not in ('refusal', 'annotations', 'audio')}
        assistant['role'] = 'assistant'
        usage = data.get('usage') or {}
        return Completion(text=message.get('content') or '', calls=calls,
                          input_tokens=usage.get('prompt_tokens'), output_tokens=usage.get('completion_tokens'),
                          assistant=assistant)


def as_chat_call(call: ToolCall) -> dict:
    return {'id': call.id, 'type': 'function',
            'function': {'name': call.name, 'arguments': json.dumps(call.arguments)}}


class ModelGateway:
    def __init__(self, store: Store, settings: Settings, provider: Provider | None = None):
        self.store, self.settings = store, settings
        self.provider = provider or HTTPProvider()
        self.ledger = Ledger(store)
        self.live = isinstance(self.provider, HTTPProvider) and self.provider.transport is None

    async def complete(self, rid: str, role: str, messages: list[dict], tools: list[dict] | None = None,
                       *, profile_override: ModelProfile | None = None, worker_id: str | None = None,
                       task_id: str | None = None) -> Completion:
        tools = tools or []
        profile = profile_override or self.settings.profile(role)
        estimate = upper_token_estimate(messages, tools)
        if estimate + profile.output_tokens > profile.context_tokens:
            raise ContextExceeded('Mandatory context exceeds model window; increase context or reduce task size')
        call_id = self.ledger.reserve(rid, role, profile, estimate)
        if worker_id and task_id:
            self.store.execute('INSERT INTO swarm_calls VALUES(?,?,?,?)', (call_id, rid, worker_id, task_id))
        self.store.event(rid, 'model.request', {'call_id': call_id, 'role': role, 'model': profile.model,
                                               'worker_id': worker_id, 'reserved_input_estimate': estimate}, task_id)
        try:
            run = self.store.run(rid)
            remaining = run['config']['budget']['wall_seconds'] - (now() - run['created'])
            if remaining <= 0:
                raise BudgetExceeded('Wall-clock budget exhausted')
            try:
                reply = await asyncio.wait_for(self.provider.complete(profile, messages, tools),
                                               min(remaining, profile.timeout_seconds))
            except asyncio.TimeoutError:
                if remaining <= profile.timeout_seconds:
                    raise BudgetExceeded('Wall-clock budget exhausted during model request') from None
                raise
            self.ledger.settle(call_id, reply.input_tokens, reply.output_tokens)
            self.store.event(rid, 'model.response', {'call_id': call_id, 'role': role,
                                                    'worker_id': worker_id, 'tool_count': len(reply.calls)}, task_id)
            return reply
        except (Exception, asyncio.CancelledError):
            self.ledger.uncertain(call_id)
            raise

    async def complete_detached(self, rid: str, role: str, messages: list[dict],
                                *, profile_override: ModelProfile | None = None) -> Completion:
        # Operator-initiated post-run actions (e.g. writeups) are not bounded by the
        # autonomous run's state/wall-clock budget. Usage is audited, not ledgered,
        # mirroring operator knowledge indexing, so settled run metrics stay intact.
        profile = profile_override or self.settings.profile(role)
        estimate = upper_token_estimate(messages, [])
        if estimate + profile.output_tokens > profile.context_tokens:
            raise ContextExceeded('Mandatory context exceeds model window; increase context or reduce task size')
        reply = await asyncio.wait_for(self.provider.complete(profile, messages, []), profile.timeout_seconds)
        self.store.audit('writeup.model_usage', {'run_id': rid, 'role': role, 'model': profile.model,
                                                 'input_tokens': reply.input_tokens,
                                                 'output_tokens': reply.output_tokens, 'scope': 'operator_writeup'})
        return reply
