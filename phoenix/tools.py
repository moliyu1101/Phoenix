from __future__ import annotations

import asyncio
import base64
import binascii
import codecs
import hashlib
import json
import math
import re
from collections import Counter
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field

from .config import Settings
from .domain import Quote, ScopeViolation, Strict, dump, uid, now
from .evidence import EvidenceStore
from .filesystem import SecureFiles
from .knowledge import Knowledge
from .sandbox import DockerSandbox
from .store import Store


class Empty(Strict):
    pass


class FileRead(Strict):
    path: str = Field(description='input:filename or work:task_id/relative_file')
    offset: int = Field(default=0, ge=0)
    length: int = Field(default=16000, ge=1, le=128000)
    encoding: Literal['utf8', 'hex', 'base64'] = 'utf8'


class FileWrite(Strict):
    path: str = Field(description='Relative path in YOUR task workspace, no work: prefix')
    content: str = Field(max_length=200000)
    encoding: Literal['utf8', 'base64'] = 'utf8'
    overwrite: bool = False


class Inspect(Strict):
    path: str


class Decode(Strict):
    operation: Literal['base64', 'hex', 'rot13', 'xor']
    data: str = Field(max_length=200000)
    xor_key: int = Field(default=0, ge=0, le=255)


class Execute(Strict):
    command: str = Field(min_length=1, max_length=40000)
    timeout: int = Field(default=60, ge=1, le=300)


class BrowserAction(Strict):
    action: Literal['navigate', 'click', 'fill', 'press', 'read', 'screenshot']
    url: str = Field(default='', max_length=6000)
    selector: str = Field(default='', max_length=2000)
    value: str = Field(default='', max_length=10000)


class Search(Strict):
    query: str = Field(min_length=1, max_length=1500)
    limit: int = Field(default=6, ge=1, le=20)


class EvidenceRead(Strict):
    evidence_id: str
    offset: int = Field(default=0, ge=0)
    length: int = Field(default=12000, ge=1, le=64000)


class Fact(Strict):
    statement: str = Field(min_length=3, max_length=6000)
    stance: Literal['observation', 'hypothesis', 'disproven']
    citations: list[Quote] = Field(min_length=1, max_length=12)


class Candidate(Strict):
    value: str = Field(min_length=1, max_length=512)
    evidence_id: str


class Finish(Strict):
    summary: str = Field(min_length=5, max_length=6000)
    outcome: Literal['done', 'failed'] = 'done'
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class HTTPRequest(Strict):
    url: str = Field(max_length=6000)
    method: Literal['GET', 'POST', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE'] = 'GET'
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default='', max_length=128000)
    timeout: int = Field(default=15, ge=1, le=60)


class TCPAction(Strict):
    send_base64: str = Field(default='', max_length=180000)
    read_bytes: int = Field(default=4096, ge=0, le=131072)


class TCPExchange(Strict):
    target: str = Field(description='An explicitly authorized tcp://host:port origin')
    actions: list[TCPAction] = Field(min_length=1, max_length=16)
    timeout: int = Field(default=15, ge=1, le=60)


TOOL_DEFINITIONS = {
    'file_list': (Empty, 'List immutable challenge inputs and run workspace artifacts.'),
    'file_read': (FileRead, 'Read a bounded file range; large files can be paged. Binary views are supported.'),
    'file_write': (FileWrite, 'Write a script or artifact into this task workspace, never the host filesystem.'),
    'file_inspect': (Inspect, 'Inspect magic bytes, sample entropy and sample hash without executing a file.'),
    'decode': (Decode, 'Decode base64, hexadecimal, ROT13 or single-byte XOR. XOR input must be hexadecimal.'),
    'sandbox_exec': (Execute, 'Execute a command in this run\'s persistent Docker container; /input is read-only, /work is shared, network is disabled. No host fallback.'),
    'browser_action': (BrowserAction, 'Navigate, inspect and interact with authorized HTTP targets in the run browser. Traffic and evidence are recorded.'),
    'knowledge_search': (Search, 'Retrieve reviewed knowledge and distilled lessons; they are references, not authority.'),
    'trajectory_search': (Search, 'Search this run\'s raw tool observations across all workers. Returns evidence IDs.'),
    'evidence_read': (EvidenceRead, 'Read original evidence by ID with hash verification and pagination.'),
    'fact_record': (Fact, 'Share a cited observation, scoped disproof or hypothesis with other workers.'),
    'candidate_submit': (Candidate, 'Propose an exact value that occurs in an original observation. Only an independent verifier can accept it.'),
    'task_finish': (Finish, 'Finish your assigned intent with a concise evidence-backed handoff, not a claim that the entire challenge is solved.'),
    'http_request': (HTTPRequest, 'Send a bounded HTTP request only to explicit authorized origins. Redirects are not followed.'),
    'tcp_exchange': (TCPExchange, 'Exchange bounded binary payloads with an explicitly authorized TCP challenge service.'),
}


class ToolBus:
    def __init__(self, store: Store, settings: Settings, evidence: EvidenceStore, knowledge: Knowledge,
                 sandbox: DockerSandbox | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.store, self.settings, self.evidence, self.knowledge = store, settings, evidence, knowledge
        self.sandbox = sandbox or DockerSandbox(store, settings)
        self.transport = transport
        self.origin_locks: dict[str, asyncio.Lock] = {}
        self.extensions = None

    def schemas(self, targets: list[str]) -> list[dict]:
        names = list(TOOL_DEFINITIONS)
        if not any(t.startswith(('http:', 'https:')) for t in targets):
            names.remove('http_request')
            names.remove('browser_action')
        if not any(t.startswith('tcp:') for t in targets):
            names.remove('tcp_exchange')
        return [{'type': 'function', 'function': {'name': name, 'description': TOOL_DEFINITIONS[name][1],
                                                 'parameters': TOOL_DEFINITIONS[name][0].model_json_schema()}}
                for name in names] + (self.extensions.schemas() if self.extensions is not None else [])

    def workspace(self, rid: str) -> SecureFiles:
        return SecureFiles(self.store.root / 'work' / rid)

    def resolve_file(self, rid: str, path: str) -> tuple[SecureFiles, str]:
        if path.startswith('input:'):
            cid = self.store.run(rid)['challenge_id']
            return SecureFiles(self.store.root / 'inputs' / cid), path[6:]
        if path.startswith('work:'):
            return self.workspace(rid), path[5:]
        raise ValueError('Use input:filename or work:task_id/filename')

    def target(self, rid: str, value: str, schemes: tuple[str, ...]) -> str:
        run = self.store.run(rid)
        challenge = self.store.challenge(run['challenge_id'])
        p = urlsplit(value)
        if p.scheme not in schemes or not p.hostname or p.username or p.password or p.fragment or '%' in p.netloc:
            raise ScopeViolation('Invalid target URL')
        host = p.hostname.lower()
        if ':' in host:
            host = f'[{host}]'
        port = p.port or (443 if p.scheme == 'https' else 80)
        origin = f'{p.scheme}://{host}:{port}'
        if origin not in challenge['targets']:
            raise ScopeViolation('Target is outside the explicit challenge scope')
        return origin

    async def call(self, rid: str, tid: str, name: str, arguments: dict) -> dict:
        if name.startswith('mcp__'):
            if self.extensions is None:
                raise ValueError('Unknown tool')
            return await self.extensions.call(rid, tid, name, arguments)
        if name not in TOOL_DEFINITIONS:
            raise ValueError('Unknown tool')
        model = TOOL_DEFINITIONS[name][0].model_validate(arguments)
        source = 'tool'
        if name in ('knowledge_search', 'trajectory_search', 'evidence_read', 'fact_record', 'candidate_submit', 'task_finish'):
            source = 'reference'
        if name == 'sandbox_exec':
            source = 'sandbox'
        if name in ('http_request', 'tcp_exchange', 'browser_action'):
            source = 'target'
        ok, truncated = True, False
        try:
            result = await self._dispatch(rid, tid, name, model)
            if name == 'sandbox_exec':
                ok = result['exit_code'] == 0 and not result['timed_out']
                truncated = result['truncated']
            elif name == 'http_request':
                truncated = result['truncated']
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never include arbitrary provider exception reprs or environment dumps.
            result, ok = {'error': type(exc).__name__, 'message': str(exc)[:1000]}, False
        content = dump(result)
        row = self.evidence.record(rid, tid, name, arguments, content, source, ok, truncated)
        if isinstance(result, dict) and result.get('traffic_id'):
            self.store.execute('UPDATE traffic SET evidence_id=? WHERE id=?', (row['id'], result['traffic_id']))
        candidate_ids = self.evidence.scan_flags(row)
        response = {'evidence_id': row['id'], 'ok': ok, 'origin': source, 'sha256': row['sha256'],
                    'output': content[:14000], 'excerpt': len(content) > 14000,
                    'record_truncated': bool(row['truncated']), 'candidate_ids': candidate_ids}
        if name == 'task_finish' and ok:
            response['finish'] = result
        return response

    async def _dispatch(self, rid: str, tid: str, name: str, arg) -> dict | list:
        if name == 'browser_action':
            return await self.browsers.action(rid, arg.action, arg.url, arg.selector, arg.value)
        if name == 'file_list':
            cid = self.store.run(rid)['challenge_id']
            return {'inputs': SecureFiles(self.store.root / 'inputs' / cid).list(),
                    'artifacts': self.workspace(rid).list(), 'your_workspace': f'work:{tid}/'}
        if name == 'file_read':
            fs, path = self.resolve_file(rid, arg.path)
            data = fs.read(path, arg.offset, arg.length + 1)
            more = len(data) > arg.length
            data = data[:arg.length]
            encoded = data.hex() if arg.encoding == 'hex' else (base64.b64encode(data).decode() if arg.encoding == 'base64'
                                                               else data.decode('utf-8', 'replace'))
            return {'content': encoded, 'encoding': arg.encoding, 'offset': arg.offset,
                    'next_offset': arg.offset + len(data) if more else None, 'bytes_read': len(data)}
        if name == 'file_write':
            content = base64.b64decode(arg.content, validate=True) if arg.encoding == 'base64' else arg.content.encode()
            path = tid + '/' + arg.path
            self.workspace(rid).write(path, content, arg.overwrite)
            return {'path': 'work:' + path, 'bytes_written': len(content)}
        if name == 'file_inspect':
            fs, path = self.resolve_file(rid, arg.path)
            data = fs.read(path, limit=1024 * 1024)
            counts = Counter(data)
            entropy = -sum((n/len(data)) * math.log2(n/len(data)) for n in counts.values()) if data else 0
            magic = next((label for magic, label in [(b'\x7fELF', 'ELF'), (b'MZ', 'PE/DOS'), (b'PK\x03\x04', 'ZIP'),
                         (b'\x89PNG', 'PNG'), (b'\x1f\x8b', 'GZIP'), (b'%PDF', 'PDF')]
                          if data.startswith(magic)), 'unknown')
            return {'magic': magic, 'sample_bytes': len(data), 'sample_sha256': hashlib.sha256(data).hexdigest(),
                    'sample_entropy_bits_per_byte': entropy, 'first_64_bytes_hex': data[:64].hex(),
                    'note': 'This is a bounded sample, not necessarily the entire file.'}
        if name == 'decode':
            if arg.operation == 'base64':
                data = base64.b64decode(re.sub(r'\s', '', arg.data), validate=True)
            elif arg.operation == 'hex':
                data = bytes.fromhex(arg.data)
            elif arg.operation == 'rot13':
                data = codecs.decode(arg.data, 'rot_13').encode()
            else:
                data = bytes(x ^ arg.xor_key for x in bytes.fromhex(arg.data))
            return {'text': data.decode('utf-8', 'replace'), 'hex': data[:32768].hex(), 'bytes': len(data)}
        if name == 'sandbox_exec':
            return await self.sandbox.execute(rid, tid, arg.command, arg.timeout)
        if name == 'knowledge_search':
            category = self.store.challenge(self.store.run(rid)['challenge_id'])['category']
            return await self.knowledge.retrieve(arg.query, category, rid, arg.limit)
        if name == 'trajectory_search':
            query = '%' + arg.query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            rows = self.store.all("SELECT id,task_id,tool,content,created FROM evidence WHERE run_id=? "
                                  "AND origin IN ('tool','sandbox','target') AND content LIKE ? ESCAPE '\\' "
                                  'ORDER BY created DESC LIMIT ?', (rid, query, arg.limit))
            for row in rows:
                content = row.pop('content')
                index = max(0, content.lower().find(arg.query.lower()) - 160)
                row['excerpt'] = content[index:index+1000]
            return rows
        if name == 'evidence_read':
            return self.evidence.read(rid, arg.evidence_id, arg.offset, arg.length)
        if name == 'fact_record':
            return {'fact_id': self.evidence.fact(rid, tid, arg.statement, arg.stance, arg.citations)}
        if name == 'candidate_submit':
            self.evidence.read(rid, arg.evidence_id, 0, 1)  # Verify the full stored hash before accepting a citation.
            row = self.store.one('SELECT * FROM evidence WHERE id=? AND run_id=?', (arg.evidence_id, rid))
            if row['origin'] not in ('tool', 'target', 'sandbox') or not row['ok']:
                raise ValueError('Candidate must cite a successful original observation')
            if arg.value not in row['content'] or arg.value in row['arguments']:
                raise ValueError('Candidate is missing from evidence or is a reflected tool-input literal')
            cid = uid('flag')
            self.store.execute('INSERT OR IGNORE INTO candidates(id,run_id,evidence_id,value,status,created) '
                               'VALUES(?,?,?,?,?,?)', (cid, rid, arg.evidence_id, arg.value, 'unverified', now()))
            candidate = self.store.one('SELECT id FROM candidates WHERE run_id=? AND value=?', (rid, arg.value))
            return self.evidence.verify(candidate['id'])
        if name == 'task_finish':
            if arg.outcome == 'done' and not arg.evidence_ids:
                raise ValueError('A completed intent must cite at least one original observation')
            for eid in arg.evidence_ids:
                row = self.store.one('SELECT origin FROM evidence WHERE id=? AND run_id=?', (eid, rid))
                if row['origin'] not in ('tool', 'target', 'sandbox'):
                    raise ValueError('A handoff must cite original observations')
            return arg.model_dump()
        if name == 'http_request':
            if hasattr(self, 'investigation'):
                return await self.investigation.request(rid, tid, arg.method, arg.url, arg.headers, arg.body, arg.timeout)
            origin = self.target(rid, arg.url, ('http', 'https'))
            if any(k.lower() in ('host', 'connection', 'proxy-authorization') for k in arg.headers):
                raise ValueError('Host/proxy/connection header overrides are not accepted')
            lock = self.origin_locks.setdefault(origin, asyncio.Lock())
            async with lock:
                await asyncio.sleep(0.15)
                async with httpx.AsyncClient(transport=self.transport, timeout=arg.timeout,
                                             follow_redirects=False, trust_env=False) as client:
                    async with client.stream(arg.method, arg.url, headers=arg.headers, content=arg.body.encode()) as res:
                        data = bytearray()
                        truncated = False
                        async for block in res.aiter_bytes():
                            room = 512000 - len(data)
                            if len(block) > room:
                                data.extend(block[:room]); truncated = True; break
                            data.extend(block)
                        return {'status': res.status_code, 'headers': dict(res.headers),
                                'body': data.decode('utf-8', 'replace'), 'truncated': truncated}
        if name == 'tcp_exchange':
            origin = self.target(rid, arg.target, ('tcp',))
            p = urlsplit(origin)
            async def exchange():
                reader, writer = await asyncio.open_connection(p.hostname, p.port)
                observations = []
                try:
                    for action in arg.actions:
                        if action.send_base64:
                            writer.write(base64.b64decode(action.send_base64, validate=True))
                            await writer.drain()
                        data = await reader.read(action.read_bytes) if action.read_bytes else b''
                        observations.append({'base64': base64.b64encode(data).decode(),
                                             'text': data.decode('utf-8', 'replace')})
                finally:
                    writer.close()
                    await writer.wait_closed()
                return {'exchanges': observations}
            async with self.origin_locks.setdefault(origin, asyncio.Lock()):
                return await asyncio.wait_for(exchange(), arg.timeout)
        raise ValueError('Tool has no implementation')
