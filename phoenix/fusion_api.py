from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field

from .domain import Conflict, Strict, digest, dump, now, uid
from .tools import BrowserAction, HTTPRequest


class SandboxAction(Strict):
    action: Literal['start', 'stop', 'pause', 'resume']


class OperatorCommand(Strict):
    command: str = Field(min_length=1, max_length=40000)
    timeout: int = Field(default=60, ge=1, le=300)


class TerminalInput(Strict):
    data_base64: str = Field(max_length=24000)


class TerminalSize(Strict):
    rows: int = Field(ge=2, le=200)
    cols: int = Field(ge=10, le=500)


class AssetInput(Strict):
    kind: str = Field(max_length=20)
    value: str = Field(min_length=1, max_length=6000)
    parent_id: str | None = None
    tested: bool = False


class InterceptInput(Strict):
    enabled: bool


class ApprovalInput(Strict):
    approved: bool
    request: HTTPRequest | None = None


class PlatformInput(Strict):
    kind: Literal['ctfd', 'gzctf', 'rctf']
    endpoint: str = Field(min_length=1, max_length=1000)
    credential: str = Field(default='', max_length=16000)
    account: str = Field(default='', max_length=300)
    connection_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,100}$')
    label: str = Field(default='', max_length=120)


class PlatformSync(Strict):
    competition_id: str | None = Field(default=None, max_length=300)


class PlatformImport(Strict):
    challenge_key: str = Field(min_length=1, max_length=300)
    targets: list[str] = Field(default_factory=list, max_length=20)
    authorized: bool = True
    flag_prefix: str = Field(default='flag', pattern=r'^[A-Za-z0-9_]{1,32}$')


class PlatformSubmit(Strict):
    candidate_id: str = Field(max_length=100)
    confirm_submit: bool = False


class PlatformInstance(Strict):
    challenge_key: str = Field(min_length=1, max_length=300)
    action: Literal['acquire', 'renew', 'release']


class ScopeConfig(Strict):
    endpoint: str = Field(min_length=1, max_length=1000)
    api_key: str = Field(default='', max_length=16000)


class ScopeSync(Strict):
    dimension: Literal['project', 'task']
    targets: list[str] = Field(min_length=1, max_length=20)
    asset_types: list[Literal['subdomain', 'service', 'app']] = Field(default_factory=lambda: ['subdomain', 'service', 'app'])


def attach_fusion(app, c):
    router = APIRouter(prefix='/api')
    from fastapi.responses import JSONResponse
    from .vendor.engine.competition.platforms.base import PlatformTransportError

    @app.exception_handler(PlatformTransportError)
    async def platform_error(request, exc):
        code = exc.status_code if exc.status_code in (401,403,404,409,429) else 502
        return JSONResponse({'error': str(exc), 'category': exc.category.value,
                             'retry_after_seconds': exc.retry_after_seconds}, status_code=code)

    @router.get('/integrations/status')
    async def status():
        import shutil
        return {'sandbox': {'docker_installed': bool(shutil.which('docker')), 'images': c.settings.sandbox_images},
                'platforms': ['ctfd', 'gzctf', 'rctf'], 'scopesentry': c.scopesentry.status(),
                'terminal': 'native-sandbox-pty', 'browser': 'sandbox-chromium-scoped-traffic'}

    @router.get('/integrations/engines')
    async def engines():
        return c.engines.catalog()

    @router.get('/runs/{rid}/engines')
    async def engine_health(rid: str):
        return await c.engines.health(rid)

    @router.get('/runs/{rid}/engine-sessions')
    async def engine_sessions(rid: str):
        c.store.run(rid)
        return c.store.all('SELECT * FROM engine_sessions WHERE run_id=? ORDER BY created', (rid,))

    @router.get('/runs/{rid}/platform-links')
    async def platform_links(rid: str):
        run = c.store.run(rid)
        return c.store.all('SELECT id,connection_id,challenge_key,challenge_id FROM platform_links WHERE challenge_id=?', (run['challenge_id'],))

    @router.get('/runs/{rid}/sandbox')
    async def sandbox(rid: str):
        return await c.sandboxes.describe(rid)

    @router.post('/runs/{rid}/sandbox')
    async def sandbox_action(rid: str, spec: SandboxAction):
        return await c.sandboxes.lifecycle(rid, spec.action)

    @router.post('/runs/{rid}/sandbox/exec')
    async def command(rid: str, spec: OperatorCommand):
        if c.store.run(rid)['state'] in ('created', 'running', 'distilling'):
            raise Conflict('Pause the run before executing an operator command')
        tid = uid('task')
        c.store.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (tid, rid, 'operator-'+tid, 'Operator sandbox command', 'solver', '[]', 0, 'active', digest(tid),
             'operator', now(), None, '', 1))
        try:
            result = await c.sandboxes.execute(rid, tid, spec.command, spec.timeout)
            ok = result['exit_code'] == 0 and not result['timed_out']
            evidence = c.evidence.record(rid, tid, 'sandbox_exec', spec.model_dump(), dump(result), 'sandbox', ok)
            c.evidence.scan_flags(evidence)
            c.store.execute('UPDATE tasks SET state=?,summary=?,ended=? WHERE id=?',
                            ('done' if ok else 'failed', 'Operator command; see '+evidence['id'], now(), tid))
            return {**result, 'evidence_id': evidence['id']}
        except BaseException:
            c.store.execute("UPDATE tasks SET state='failed',ended=?,summary='Operator command failed' WHERE id=?", (now(), tid))
            raise

    @router.post('/runs/{rid}/terminals')
    async def terminal_start(rid: str):
        return await c.terminals.start(rid)

    @router.get('/runs/{rid}/terminals/{sid}')
    async def terminal_output(rid: str, sid: str, after: int = Query(0, ge=0)):
        return c.terminals.output(rid, sid, after)

    @router.post('/runs/{rid}/terminals/{sid}/input')
    async def terminal_input(rid: str, sid: str, spec: TerminalInput):
        return c.terminals.write(rid, sid, spec.data_base64)

    @router.post('/runs/{rid}/terminals/{sid}/resize')
    async def terminal_resize(rid: str, sid: str, spec: TerminalSize):
        return c.terminals.resize(rid, sid, spec.rows, spec.cols)

    @router.delete('/runs/{rid}/terminals/{sid}')
    async def terminal_close(rid: str, sid: str):
        return await c.terminals.close(rid, sid)

    @router.post('/runs/{rid}/browser')
    async def browser_action(rid: str, spec: BrowserAction):
        result = await c.browsers.action(rid, **spec.model_dump())
        evidence = c.evidence.record(rid, None, 'browser_action', spec.model_dump(), dump({k: v for k, v in result.items() if k != 'image_base64'}), 'target')
        c.evidence.scan_flags(evidence)
        return {**result, 'evidence_id': evidence['id']}

    @router.get('/runs/{rid}/assets')
    async def assets(rid: str):
        return c.investigation.inventory(rid)

    @router.post('/runs/{rid}/assets')
    async def asset(rid: str, spec: AssetInput):
        return c.investigation.asset(rid, **spec.model_dump())

    @router.get('/runs/{rid}/traffic')
    async def traffic(rid: str):
        return {'items': c.investigation.traffic(rid), 'intercept': c.investigation.intercept(rid)}

    @router.post('/runs/{rid}/traffic/intercept')
    async def intercept(rid: str, spec: InterceptInput):
        c.store.run(rid)
        c.investigation.configure('intercept:'+rid, spec.enabled)
        return {'enabled': spec.enabled}

    @router.post('/runs/{rid}/traffic/{traffic_id}/replay')
    async def replay(rid: str, traffic_id: str, spec: HTTPRequest):
        c.store.one('SELECT id FROM traffic WHERE id=? AND run_id=?', (traffic_id, rid))
        return await c.investigation.request(rid, None, spec.method, spec.url, spec.headers, spec.body, spec.timeout, 'operator-replay')

    @router.get('/runs/{rid}/approvals')
    async def approvals(rid: str):
        c.store.run(rid)
        rows = c.store.all('SELECT * FROM request_approvals WHERE run_id=? ORDER BY created DESC LIMIT 100', (rid,))
        import json
        return [{**row, 'request': json.loads(row['request'])} for row in rows]

    @router.post('/runs/{rid}/approvals/{aid}')
    async def approval(rid: str, aid: str, spec: ApprovalInput):
        edit = spec.request.model_dump(exclude={'timeout'}) if spec.request else None
        return c.investigation.decide(rid, aid, spec.approved, edit)

    @router.get('/integrations/platforms')
    async def platforms():
        return c.platforms.connections()

    @router.post('/integrations/platforms')
    async def platform_config(spec: PlatformInput):
        return await c.platforms.configure(**spec.model_dump())

    @router.post('/integrations/platforms/{cid}/probe')
    async def platform_probe(cid: str):
        return await c.platforms.probe(cid)

    @router.get('/integrations/platforms/{cid}/challenges')
    async def platform_snapshot(cid: str):
        return c.platforms.snapshot(cid)

    @router.post('/integrations/platforms/{cid}/sync')
    async def platform_sync(cid: str, spec: PlatformSync):
        return await c.platforms.sync(cid, spec.competition_id)

    @router.post('/integrations/platforms/{cid}/import')
    async def platform_import(cid: str, spec: PlatformImport):
        return await c.platforms.import_challenge(cid, spec.challenge_key, spec.targets, spec.authorized, spec.flag_prefix)

    @router.post('/integrations/platforms/{cid}/submit')
    async def platform_submit(cid: str, spec: PlatformSubmit):
        return await c.platforms.submit(cid, spec.candidate_id, spec.confirm_submit)

    @router.post('/integrations/platforms/{cid}/submissions/{sid}/poll')
    async def platform_receipt(cid: str, sid: str):
        return await c.platforms.poll_submission(cid, sid)

    @router.post('/integrations/platforms/{cid}/instance')
    async def platform_instance(cid: str, spec: PlatformInstance):
        return await c.platforms.instance(cid, spec.challenge_key, spec.action)

    @router.get('/integrations/scopesentry')
    async def scopesentry():
        return c.scopesentry.status()

    @router.post('/integrations/scopesentry')
    async def scopesentry_config(spec: ScopeConfig):
        return c.scopesentry.configure(spec.endpoint, spec.api_key)

    @router.get('/integrations/scopesentry/{dimension}')
    async def scopesentry_list(dimension: Literal['projects', 'tasks'], page: int = Query(1, ge=1, le=100), search: str = ''):
        return await c.scopesentry.call('list_projects_data' if dimension == 'projects' else 'list_tasks',
                                       {'pageIndex': page, 'pageSize': 50, 'search': search[:300]})

    @router.post('/runs/{rid}/assets/scopesentry')
    async def scopesentry_sync(rid: str, spec: ScopeSync):
        return await c.scopesentry.sync(rid, **spec.model_dump())

    app.include_router(router)
