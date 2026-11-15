from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from .domain import Conflict, NotFound, dump, now, uid

TRANSPORTS = ('stdio', 'streamable-http', 'sse')
_MAX_TEXT = 128000
_MAX_ARGS = 64000

SCHEMA_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS mcp_servers(
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        transport TEXT NOT NULL,
        config TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'unknown',
        tools TEXT NOT NULL DEFAULT '[]',
        error TEXT NOT NULL DEFAULT '',
        last_probe REAL,
        created REAL NOT NULL,
        updated REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS plugins(
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        manifest TEXT NOT NULL DEFAULT '{}',
        source TEXT NOT NULL DEFAULT '',
        diagnostics TEXT NOT NULL DEFAULT '[]',
        enabled INTEGER NOT NULL DEFAULT 0,
        created REAL NOT NULL,
        updated REAL NOT NULL)""",
)


def sdk_available() -> bool:
    return importlib.util.find_spec('mcp') is not None


def _slug(value: str, limit: int) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_-]', '_', str(value)).strip('_')
    return (cleaned or 'x')[:limit]


def _string_map(value: Any, label: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 64:
        raise ValueError(f'{label} must be an object with at most 64 string entries')
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 200:
            raise ValueError(f'{label} keys must be non-empty strings up to 200 characters')
        if not isinstance(item, str) or len(item) > 16000:
            raise ValueError(f'{label} values must be strings up to 16000 characters')
        result[key] = item
    return result


def normalize_config(transport: str, config: dict) -> dict:
    if transport not in TRANSPORTS:
        raise ValueError('Transport must be stdio, streamable-http or sse')
    if not isinstance(config, dict):
        raise ValueError('Config must be an object')
    timeout = config.get('timeout', 15)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise ValueError('Timeout must be an integer between 1 and 120 seconds')
    result: dict[str, Any] = {'timeout': timeout}
    if transport == 'stdio':
        command = config.get('command')
        if not isinstance(command, str) or not command.strip() or len(command) > 2000:
            raise ValueError('A stdio server requires a non-empty command')
        args = config.get('args', [])
        if not isinstance(args, list) or len(args) > 64 or any(not isinstance(a, str) or len(a) > 4000 for a in args):
            raise ValueError('Args must be an array of at most 64 strings')
        cwd = config.get('cwd', '')
        if not isinstance(cwd, str) or len(cwd) > 2000:
            raise ValueError('Cwd must be a string up to 2000 characters')
        result.update(command=command.strip(), args=list(args), cwd=cwd, env=_string_map(config.get('env'), 'Env'))
    else:
        url = config.get('url')
        if not isinstance(url, str) or len(url) > 6000:
            raise ValueError('A remote server requires a url')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Url must be an http(s) endpoint without embedded credentials')
        result.update(url=url, headers=_string_map(config.get('headers'), 'Headers'))
    return result


def public_config(transport: str, config: dict) -> dict:
    view = {k: v for k, v in config.items() if k not in ('env', 'headers')}
    view['env_keys'] = sorted(config.get('env', {}))
    view['header_keys'] = sorted(config.get('headers', {}))
    return view


@asynccontextmanager
async def open_mcp_session(transport: str, config: dict):
    if not sdk_available():
        raise RuntimeError('The mcp SDK is not installed; run pip install mcp')
    from mcp import ClientSession, StdioServerParameters
    if transport == 'stdio':
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=config['command'], args=config.get('args', []),
                                       env=config.get('env') or None, cwd=config.get('cwd') or None)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                yield session
    elif transport == 'streamable-http':
        import httpx2
        from mcp.client.streamable_http import streamable_http_client
        async with httpx2.AsyncClient(headers=config.get('headers') or {}, timeout=config.get('timeout', 15),
                                      trust_env=False, follow_redirects=False) as client:
            async with streamable_http_client(config['url'], http_client=client) as (read, write):
                async with ClientSession(read, write) as session:
                    yield session
    else:
        from mcp.client.sse import sse_client
        async with sse_client(config['url'], headers=config.get('headers') or {},
                              timeout=config.get('timeout', 15)) as (read, write):
            async with ClientSession(read, write) as session:
                yield session


def _normalize_tools(result: Any) -> list[dict]:
    tools = []
    for tool in getattr(result, 'tools', []) or []:
        schema = getattr(tool, 'input_schema', None) or getattr(tool, 'inputSchema', None) or {}
        if not isinstance(schema, dict):
            schema = {}
        schema.setdefault('type', 'object')
        schema.setdefault('properties', {})
        tools.append({'name': str(tool.name), 'description': str(getattr(tool, 'description', '') or '')[:4000],
                      'input_schema': schema})
    return tools


def _normalize_result(result: Any) -> tuple[dict, bool]:
    blocks, text_len, truncated = [], 0, False
    for block in getattr(result, 'content', []) or []:
        text = getattr(block, 'text', None)
        if isinstance(text, str):
            room = _MAX_TEXT - text_len
            if len(text) > room:
                text, truncated = text[:room], True
            text_len += len(text)
            blocks.append({'type': 'text', 'text': text})
        else:
            data = getattr(block, 'data', '') or ''
            blocks.append({'type': str(getattr(block, 'type', 'unknown')),
                           'mime_type': str(getattr(block, 'mimeType', '') or getattr(block, 'mime_type', '') or ''),
                           'bytes': len(data) if isinstance(data, str) else 0})
    structured = getattr(result, 'structured_content', None)
    if structured is None:
        structured = getattr(result, 'structuredContent', None)
    payload: dict[str, Any] = {'content': blocks}
    if isinstance(structured, dict):
        payload['structured_content'] = json.loads(dump(structured))
    is_error = bool(getattr(result, 'is_error', False) or getattr(result, 'isError', False))
    payload['is_error'] = is_error
    return payload, truncated


class Extensions:
    """Native registry for operator-managed MCP servers and agent plugins."""

    def __init__(self, components):
        self.c = components
        self.store = components.store
        self.evidence = components.evidence
        self.session_factory = open_mcp_session
        for statement in SCHEMA_STATEMENTS:
            self.store.execute(statement)

    # -- MCP servers ---------------------------------------------------------

    def _server_row(self, sid: str) -> dict:
        return self.store.one('SELECT * FROM mcp_servers WHERE id=?', (sid,))

    def _server_view(self, row: dict) -> dict:
        config = json.loads(row['config'])
        tools = json.loads(row['tools'])
        return {'id': row['id'], 'name': row['name'], 'transport': row['transport'],
                'enabled': bool(row['enabled']), 'state': row['state'], 'error': row['error'],
                'last_probe': row['last_probe'], 'created': row['created'], 'updated': row['updated'],
                'config': public_config(row['transport'], config), 'tools': tools, 'tool_count': len(tools)}

    def list_servers(self) -> list[dict]:
        return [self._server_view(r) for r in self.store.all('SELECT * FROM mcp_servers ORDER BY created, id')]

    def server(self, sid: str) -> dict:
        return self._server_view(self._server_row(sid))

    def create_server(self, spec: dict) -> dict:
        name = spec.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('Name must be a non-empty string up to 120 characters')
        name = name.strip()
        if self.store.all('SELECT id FROM mcp_servers WHERE name=?', (name,)):
            raise Conflict('An MCP server with this name already exists')
        transport = spec.get('transport', 'stdio')
        config = normalize_config(transport, spec.get('config', {}))
        sid, t = uid('mcp'), now()
        self.store.execute('INSERT INTO mcp_servers(id,name,transport,config,enabled,state,tools,error,last_probe,created,updated) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (sid, name, transport, dump(config), int(bool(spec.get('enabled', False))),
                            'unknown', '[]', '', None, t, t))
        self.store.audit('extensions.mcp_created', {'id': sid, 'name': name, 'transport': transport})
        return self.server(sid)

    def update_server(self, sid: str, spec: dict) -> dict:
        row = self._server_row(sid)
        name = spec.get('name', row['name'])
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('Name must be a non-empty string up to 120 characters')
        name = name.strip()
        if name != row['name'] and self.store.all('SELECT id FROM mcp_servers WHERE name=?', (name,)):
            raise Conflict('An MCP server with this name already exists')
        transport = spec.get('transport', row['transport'])
        current = json.loads(row['config'])
        incoming = spec.get('config')
        if incoming is None:
            config = normalize_config(transport, current)
        else:
            merged = dict(incoming)
            # Omitted secret maps keep their stored values; an explicit empty map clears them.
            for key in ('env', 'headers'):
                if key not in merged and key in current:
                    merged[key] = current[key]
            config = normalize_config(transport, merged)
        enabled = bool(spec.get('enabled', row['enabled']))
        reset = transport != row['transport'] or dump(config) != row['config']
        self.store.execute('UPDATE mcp_servers SET name=?,transport=?,config=?,enabled=?,state=?,tools=?,error=?,updated=? WHERE id=?',
                           (name, transport, dump(config), int(enabled),
                            'unknown' if reset else row['state'], '[]' if reset else row['tools'],
                            '' if reset else row['error'], now(), sid))
        self.store.audit('extensions.mcp_updated', {'id': sid})
        return self.server(sid)

    def set_server_enabled(self, sid: str, enabled: bool) -> dict:
        self._server_row(sid)
        self.store.execute('UPDATE mcp_servers SET enabled=?,updated=? WHERE id=?', (int(bool(enabled)), now(), sid))
        self.store.audit('extensions.mcp_enabled', {'id': sid, 'enabled': bool(enabled)})
        return self.server(sid)

    def delete_server(self, sid: str) -> dict:
        self._server_row(sid)
        self.store.execute('DELETE FROM mcp_servers WHERE id=?', (sid,))
        self.store.audit('extensions.mcp_removed', {'id': sid})
        return {'removed': sid}

    async def probe(self, sid: str) -> dict:
        row = self._server_row(sid)
        config = json.loads(row['config'])
        tools, state, error = [], 'error', ''
        try:
            tools = await asyncio.wait_for(self._list_tools(row['transport'], config), config.get('timeout', 15) + 5)
            state = 'healthy'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f'{type(exc).__name__}: {str(exc)[:400]}'
        self.store.execute('UPDATE mcp_servers SET state=?,tools=?,error=?,last_probe=?,updated=? WHERE id=?',
                           (state, dump(tools), error, now(), now(), sid))
        return self.server(sid)

    async def _list_tools(self, transport: str, config: dict) -> list[dict]:
        async with self.session_factory(transport, config) as session:
            await session.initialize()
            return _normalize_tools(await session.list_tools())

    # -- Plugins -------------------------------------------------------------

    def _plugin_row(self, pid: str) -> dict:
        return self.store.one('SELECT * FROM plugins WHERE id=?', (pid,))

    def _plugin_view(self, row: dict) -> dict:
        return {'id': row['id'], 'name': row['name'], 'manifest': json.loads(row['manifest']),
                'source': row['source'], 'diagnostics': json.loads(row['diagnostics']),
                'enabled': bool(row['enabled']), 'created': row['created'], 'updated': row['updated']}

    def list_plugins(self) -> list[dict]:
        return [self._plugin_view(r) for r in self.store.all('SELECT * FROM plugins ORDER BY created, id')]

    def plugin(self, pid: str) -> dict:
        return self._plugin_view(self._plugin_row(pid))

    def create_plugin(self, spec: dict) -> dict:
        path = spec.get('path')
        diagnostics: list[dict] = []
        if path:
            from .vendor.engine.capability_bindings.agent_plugin import discover_agent_plugin
            package = discover_agent_plugin(path)
            if not package.plugin.ready:
                raise ValueError('The plugin package manifest is invalid: '
                                 + '; '.join(d.message for d in package.diagnostics[:4]))
            manifest = dict(package.manifest)
            name = spec.get('name') or manifest.get('name')
            source = str(package.root)
            diagnostics = [d.as_dict() for d in package.diagnostics]
        else:
            manifest = spec.get('manifest')
            if not isinstance(manifest, dict) or not manifest:
                raise ValueError('Provide a manifest object or a package path')
            if len(dump(manifest)) > 64000:
                raise ValueError('Manifest exceeds the 64 KB limit')
            name = spec.get('name') or manifest.get('name')
            source = ''
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('Plugin name must be a non-empty string up to 120 characters')
        name = name.strip()
        if self.store.all('SELECT id FROM plugins WHERE name=?', (name,)):
            raise Conflict('A plugin with this name already exists')
        pid, t = uid('plugin'), now()
        self.store.execute('INSERT INTO plugins(id,name,manifest,source,diagnostics,enabled,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                           (pid, name, dump(json.loads(dump(manifest))), source, dump(diagnostics),
                            int(bool(spec.get('enabled', False))), t, t))
        self.store.audit('extensions.plugin_created', {'id': pid, 'name': name})
        return self.plugin(pid)

    def set_plugin_enabled(self, pid: str, enabled: bool) -> dict:
        self._plugin_row(pid)
        self.store.execute('UPDATE plugins SET enabled=?,updated=? WHERE id=?', (int(bool(enabled)), now(), pid))
        self.store.audit('extensions.plugin_enabled', {'id': pid, 'enabled': bool(enabled)})
        return self.plugin(pid)

    def delete_plugin(self, pid: str) -> dict:
        self._plugin_row(pid)
        self.store.execute('DELETE FROM plugins WHERE id=?', (pid,))
        self.store.audit('extensions.plugin_removed', {'id': pid})
        return {'removed': pid}

    # -- Agent-facing tool bridge -------------------------------------------

    def _exposed_tools(self) -> dict[str, dict]:
        mapping: dict[str, dict] = {}
        rows = self.store.all("SELECT * FROM mcp_servers WHERE enabled=1 AND state='healthy' ORDER BY created, id")
        for row in rows:
            prefix = 'mcp__' + _slug(row['name'], 20) + '__'
            for tool in json.loads(row['tools']):
                base = (prefix + _slug(tool['name'], 34))[:60]
                name, suffix = base, 2
                while name in mapping:
                    name = f'{base}_{suffix}'[:64]
                    suffix += 1
                mapping[name] = {'server_id': row['id'], 'server_name': row['name'], 'tool': tool['name'],
                                 'description': tool.get('description', ''), 'input_schema': tool.get('input_schema', {})}
        return mapping

    def schemas(self) -> list[dict]:
        return [{'type': 'function', 'function': {
            'name': name, 'description': f"[MCP:{item['server_name']}] {item['description']}".strip()[:1024],
            'parameters': item['input_schema'] or {'type': 'object', 'properties': {}}}}
            for name, item in self._exposed_tools().items()]

    async def call(self, rid: str, tid: str, name: str, arguments: dict) -> dict:
        item = self._exposed_tools().get(name)
        if item is None:
            raise ValueError('Unknown tool')
        return await self.call_tool(item['server_id'], item['tool'], arguments, rid=rid, tid=tid, evidence_tool=name)

    async def call_tool(self, sid: str, name: str, arguments: dict, *, rid: str | None = None,
                        tid: str | None = None, evidence_tool: str | None = None) -> dict:
        row = self._server_row(sid)
        if not row['enabled']:
            raise Conflict('Enable the MCP server before calling its tools')
        if not isinstance(arguments, dict) or len(dump(arguments)) > _MAX_ARGS:
            raise ValueError('Arguments must be an object up to 64 KB')
        known = {t['name'] for t in json.loads(row['tools'])}
        if known and name not in known:
            raise ValueError('The tool was not discovered on this server; probe it first')
        config = json.loads(row['config'])
        truncated = False
        try:
            payload = await asyncio.wait_for(self._call_remote(row['transport'], config, name, arguments),
                                             config.get('timeout', 15) + 5)
            payload, truncated = _normalize_result(payload)
            ok = not payload.get('is_error', False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            payload, ok = {'error': type(exc).__name__, 'message': str(exc)[:1000], 'is_error': True}, False
        if rid is None:
            return {'ok': ok, 'result': payload, 'truncated': truncated}
        self.store.run(rid)
        tool_label = evidence_tool or f"mcp__{_slug(row['name'], 20)}__{_slug(name, 34)}"[:64]
        content = dump(payload)
        record = self.evidence.record(rid, tid, tool_label, arguments, content, 'tool', ok, truncated)
        candidates = self.evidence.scan_flags(record)
        return {'evidence_id': record['id'], 'ok': ok, 'origin': 'tool', 'sha256': record['sha256'],
                'output': content[:14000], 'excerpt': len(content) > 14000,
                'record_truncated': bool(record['truncated']), 'candidate_ids': candidates}

    async def _call_remote(self, transport: str, config: dict, name: str, arguments: dict) -> Any:
        async with self.session_factory(transport, config) as session:
            await session.initialize()
            return await session.call_tool(name, arguments)

    # -- Overview ------------------------------------------------------------

    def overview(self) -> dict:
        servers = self.list_servers()
        plugins = self.list_plugins()
        enabled = [s for s in servers if s['enabled']]
        return {'sdk': 'mcp' if sdk_available() else 'unavailable',
                'mcp_servers': {'total': len(servers), 'enabled': len(enabled),
                                'healthy': sum(1 for s in enabled if s['state'] == 'healthy'),
                                'error': sum(1 for s in servers if s['state'] == 'error')},
                'plugins': {'total': len(plugins), 'enabled': sum(1 for p in plugins if p['enabled'])},
                'tools': len(self._exposed_tools())}