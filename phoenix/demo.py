"""Scripted MODEL fixture. Tools and storage are real; this is not a general CTF solver."""
from __future__ import annotations

import base64
import json

from .domain import ChallengeInput, Completion, RunInput, ToolCall, digest, dump, uid
from .filesystem import SecureFiles
from .providers import ModelGateway, as_chat_call
from .runtime import Runtime


class DemonstrationProvider:
    async def complete(self, profile, messages, tools) -> Completion:
        if not tools:
            if 'Extract at most' in messages[0]['content']:
                return self.text({'lessons': []})
            core = next((json.loads(m['content']) for m in messages if m['role'] == 'user'
                         and m['content'].startswith('{') and 'output_schema' in m['content']), {})
            if '复盘撰写器' in messages[0]['content']:
                first = core['observations'][0]['excerpts'][0]['citation_id']
                return self.text({'title': '脚本化演示：Base64 附件解码复盘',
                                  'overview': '本演示使用真实工具读取并 Base64 解码附件，得到候选 Flag 并保留不可变证据。',
                                  'analysis': '附件内容为 Base64 编码字符串，解码后即可还原明文 Flag；考点在于识别编码并保留原始证据。',
                                  'steps': [{'heading': '读取并解码附件',
                                             'detail': '先列出输入文件，读取 payload.txt，再对其内容执行 Base64 解码。',
                                             'citation_ids': [first]}],
                                  'reproduction': {'reproducible': True,
                                                   'notes': '凭引用证据中的原始内容与解码输出即可独立复现。', 'gaps': []},
                                  'conclusion': '解码得到候选 Flag，已由独立校验器确认。',
                                  'citation_ids': [first]})
            if core.get('existing_tasks'):
                return self.text({'rationale': 'The demonstration has no additional directions', 'tasks': [], 'stop': True})
            return self.text({'rationale': 'Scripted fixture: inspect the encoded attachment using real tools',
                              'tasks': [{'key': 'decode-attachment', 'goal': 'Inspect and decode the provided attachment',
                                         'role': 'solver', 'depends_on': [], 'priority': 80}], 'stop': False})
        observations = [m for m in messages if m['role'] == 'tool']
        if not observations:
            return self.call('file_list', {})
        envelope = json.loads(observations[-1]['content'])
        result = json.loads(envelope.get('output', '{}'))
        if 'inputs' in result:
            return self.call('file_read', {'path': 'input:' + result['inputs'][0]['path']})
        if 'content' in result and 'encoding' in result:
            return self.call('decode', {'operation': 'base64', 'data': result['content'].strip()})
        return self.call('task_finish', {'summary': 'The scripted fixture decoded the attachment using real tools',
                                         'evidence_ids': [envelope['evidence_id']], 'outcome': 'done'})

    @staticmethod
    def call(name, args):
        c = ToolCall(id=uid('tc'), name=name, arguments=args)
        return Completion(calls=[c], input_tokens=100, output_tokens=30,
                          assistant={'role': 'assistant', 'content': '', 'tool_calls': [as_chat_call(c)]})

    @staticmethod
    def text(value):
        return Completion(text=dump(value), input_tokens=100, output_tokens=60,
                          assistant={'role': 'assistant', 'content': dump(value)})


async def create_demo(components):
    s = components.store
    challenge = s.create_challenge(ChallengeInput(title='Native pipeline demonstration', category='misc',
        description='SCRIPTED DEMO, NOT A MODEL BENCHMARK. Decode payload.txt and preserve evidence.', authorized=True))
    flag = 'flag{native_tools_real_evidence}'
    fs = SecureFiles(s.root / 'inputs' / challenge['id'])
    fs.write('payload.txt', base64.b64encode(flag.encode()))
    s.execute('INSERT INTO verifiers VALUES(?,?)', (challenge['id'], digest(flag)))
    run = s.create_run(challenge['id'], RunInput(auto_distill=False, max_rounds=2), mode='demo')
    gateway = ModelGateway(s, components.settings, DemonstrationProvider())
    runtime = Runtime(s, components.settings, gateway, components.tools, components.memory, components.knowledge)
    result = await runtime.run(run['id'])
    from .domain import Lesson, Quote
    row = s.one("SELECT * FROM evidence WHERE run_id=? AND tool='decode'", (run['id'],))
    components.memory.propose(run['id'], Lesson(
        title='Decode a base64 attachment with explicit evidence', category='misc', kind='procedure',
        applicability='Use only when the input alphabet and padding are consistent with base64; validate decoded structure.',
        steps=['Read the original attachment without executing it.', 'Decode the candidate encoding using a real tool.',
               'Keep the original output and require an independent verifier for any candidate answer.'],
        pitfalls=['A readable or flag-shaped decoded string alone does not establish correctness.'],
        citations=[Quote(evidence_id=row['id'], quote='"text"')]))
    return result
