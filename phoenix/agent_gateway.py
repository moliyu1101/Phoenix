from __future__ import annotations

import asyncio
import hashlib
import json
import secrets

from .domain import dump, uid
from .providers import as_chat_call


class AgentGateway:
    """A run-local UNIX socket. Containers receive short-lived task tokens only."""
    def __init__(self, components):
        self.c = components
        self.servers, self.tokens = {}, {}

    async def bind(self, rid, tid, profile, worker_id=None):
        directory = self.c.store.root / 'bridges' / rid
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'model.sock'
        if rid not in self.servers:
            if path.exists():
                path.unlink()
            self.servers[rid] = await asyncio.start_unix_server(lambda r, w: self.handle(rid, r, w), str(path), limit=1024*1024)
            path.chmod(0o600)
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        self.tokens[key] = {'rid': rid, 'tid': tid, 'profile': profile, 'worker_id': worker_id,
                            'lock': asyncio.Lock(), 'evidence_ids': [], 'finish': None}
        return token

    def revoke(self, token):
        self.tokens.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    def task(self, rid, token):
        task = self.tokens.get(hashlib.sha256(token.encode()).hexdigest())
        if not task or task['rid'] != rid:
            raise PermissionError('Task token is invalid or expired')
        return task

    async def tool(self, rid, token, name, payload):
        task = self.task(rid, token)
        run = self.c.store.run(rid)
        targets = self.c.store.challenge(run['challenge_id'])['targets']
        schemas = self.c.tools.schemas(targets)
        if name == 'schema':
            return {'tools': schemas}
        if name not in {s['function']['name'] for s in schemas}:
            raise ValueError('Tool is not available for this task')
        call_id = str(payload.get('call_id') or uid('tool'))[:150]
        self.c.store.event(rid, 'tool.started', {'tool': name, 'call_id': call_id}, task['tid'])
        result = await self.c.tools.call(rid, task['tid'], name, payload.get('arguments', {}))
        self.c.store.event(rid, 'tool.completed', {'tool': name, 'call_id': call_id,
            'ok': result.get('ok', True), 'evidence_id': result.get('evidence_id')}, task['tid'])
        if result.get('ok') and result.get('origin') in ('tool', 'target', 'sandbox'):
            task['evidence_ids'].append(result['evidence_id'])
        if result.get('finish'):
            task['finish'] = result['finish']
        return result

    async def complete(self, rid, token, payload):
        key = hashlib.sha256(token.encode()).hexdigest()
        task = self.tokens.get(key)
        if not task or task['rid'] != rid:
            raise PermissionError('Task token is invalid or expired')
        messages = payload.get('messages')
        if not isinstance(messages, list) or len(messages) > 500:
            raise ValueError('Invalid agent messages')
        messages = [{**m, 'role': 'system' if m.get('role') == 'developer' else m.get('role')} for m in messages]
        async with task['lock']:
            self.task(rid, token)  # Recheck a token revoked while waiting for this lock.
            role = self.c.store.one('SELECT role FROM tasks WHERE id=? AND run_id=?', (task['tid'], rid))['role']
            response = await self.c.gateway.complete(rid, role, messages, payload.get('tools') or [],
                profile_override=task['profile'], worker_id=task['worker_id'], task_id=task['tid'])
        message = {**response.assistant, 'role': 'assistant', 'content': response.text}
        message.pop('_anthropic_content', None)
        if response.calls:
            message['tool_calls'] = [as_chat_call(call) for call in response.calls]
        return {'id': uid('chatcmpl'), 'object': 'chat.completion', 'created': 0,
                'model': task['profile'].model,
                'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if response.calls else 'stop'}],
                'usage': {'prompt_tokens': response.input_tokens, 'completion_tokens': response.output_tokens,
                          'total_tokens': (response.input_tokens or 0)+(response.output_tokens or 0)}}

    async def handle(self, rid, reader, writer):
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
            lines = header.decode('latin-1').split('\r\n')
            method, path, _ = lines[0].split(' ', 2)
            headers = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            if method != 'POST' or (path not in ('/v1/chat/completions', '/chat/completions') and not path.startswith('/tools/')):
                raise ValueError('Only task model and native tool endpoints are available')
            size = int(headers.get('content-length', '0'))
            if not 1 <= size <= 2*1024*1024:
                raise ValueError('Agent payload exceeds limits')
            payload = json.loads(await reader.readexactly(size))
            token = headers.get('authorization', '').removeprefix('Bearer ')
            is_tool = path.startswith('/tools/')
            result = await self.tool(rid, token, path[7:], payload) if is_tool else await self.complete(rid, token, payload)
            if not is_tool and payload.get('stream'):
                choice = result['choices'][0]
                delta = dict(choice['message'])
                if delta.get('tool_calls'):
                    delta['tool_calls'] = [{'index': i, **call} for i, call in enumerate(delta['tool_calls'])]
                chunk = {**result, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                done = {**result, 'object': 'chat.completion.chunk', 'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice['finish_reason']}]}
                content = ('data: '+dump(chunk)+'\n\ndata: '+dump(done)+'\n\ndata: [DONE]\n\n').encode()
                content_type = 'text/event-stream'
            else:
                content, content_type = dump(result).encode(), 'application/json'
            code = 200
        except PermissionError:
            code, content_type, content = 401, 'application/json', b'{"error":{"message":"Invalid task token"}}'
        except BaseException as exc:
            code, content_type = 502, 'application/json'
            content = dump({'error': {'message': type(exc).__name__+'; see native run journal'}}).encode()
        try:
            writer.write(f'HTTP/1.1 {code} Response\r\nContent-Type: {content_type}\r\nContent-Length: {len(content)}\r\nConnection: close\r\n\r\n'.encode()+content)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def shutdown(self):
        for server in self.servers.values():
            server.close()
            await server.wait_closed()
        self.tokens.clear()
