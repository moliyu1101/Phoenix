from __future__ import annotations

import asyncio
import base64
import hmac
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import Field

from . import __version__
from .auth import COOKIE_NAME
from .config import Settings
from .demo import create_demo
from .domain import ChallengeInput, Conflict, NotFound, PhoenixError, RunInput, SkillSpec, Strict, dump
from .evolution import BenchmarkSuite
from .filesystem import SecureFiles
from .service import Components


class FileUpload(Strict):
    name: str = Field(min_length=1, max_length=500)
    data_base64: str = Field(max_length=45000000)


class VerificationConfig(Strict):
    expected_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class ResumeInput(Strict):
    acknowledge_uncertain: bool = False


class ReceiptInput(Strict):
    accepted: bool
    receipt: str = Field(min_length=8, max_length=4000)


class KnowledgeInput(Strict):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=2000000)
    category: str = 'general'
    source: str = Field(default='operator-import', max_length=1000)
    trusted: bool = False


class ReviewInput(Strict):
    approved: bool


class SkillFromMemory(Strict):
    key: str = Field(pattern=r'^[a-z][a-z0-9_-]{2,59}$')


class EvaluateInput(Strict):
    suite: BenchmarkSuite
    run: RunInput = Field(default_factory=lambda: RunInput(auto_distill=False))
    confirm_model_charges: bool = False


class LearnInput(EvaluateInput):
    auto_promote: bool = False


class PromoteInput(Strict):
    evaluation_id: str


class PaidInput(Strict):
    confirm_paid: bool = False


def create_app(settings: Settings, components: Components | None = None) -> FastAPI:
    c = components or Components(settings)
    lock_file = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal lock_file
        if not settings.web_token or len(settings.web_token) < 24:
            raise RuntimeError('Set PHOENIX_WEB_TOKEN to a random secret of at least 24 characters')
        # The v0.1 server has one control-plane owner. Reject --workers N to avoid false crash recovery.
        import fcntl
        lock_file = (settings.data_dir / 'server.lock').open('a+')
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeError('Another server owns this data directory; run one control-plane process')
        c.store.recover()
        c.effects.recover()
        from .competition import competition_loop
        from .effects import effects_loop
        competition_stop = asyncio.Event()
        competition_task = asyncio.create_task(competition_loop(c, competition_stop))
        effects_task = asyncio.create_task(effects_loop(c, competition_stop))
        yield
        competition_stop.set()
        competition_task.cancel()
        effects_task.cancel()
        await asyncio.gather(competition_task, effects_task, return_exceptions=True)
        for task in list(c.runtime.background.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*c.runtime.background.values(), return_exceptions=True)
        await c.terminals.shutdown()
        await c.browsers.shutdown()
        await c.platforms.shutdown()
        await c.engines.shutdown()
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()

    app = FastAPI(title='Phoenix', version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.components = c
    permitted_origins = {f'http://127.0.0.1:{settings.port}', f'http://localhost:{settings.port}',
                         *settings.allowed_origins}

    @app.middleware('http')
    async def access_control(request: Request, call_next):
        if request.url.path.startswith('/api') or request.url.path == '/openapi.json':
            # login/logout are the session entry/exit and carry no credential yet.
            if request.url.path not in ('/api/auth/login', '/api/auth/logout'):
                supplied = request.headers.get('authorization', '')
                expected = 'Bearer ' + settings.web_token
                bearer_ok = bool(settings.web_token) and hmac.compare_digest(supplied, expected)
                sid = request.cookies.get(COOKIE_NAME)
                session = c.auth.session(sid)
                ticket_ok = c.auth.consume_ticket(request.query_params.get('ticket'))
                if not (bearer_ok or session or ticket_ok):
                    return JSONResponse({'error': 'Authentication required'}, status_code=401)
                request.state.auth_session = sid if session else None
            origin = request.headers.get('origin')
            if origin and origin not in permitted_origins:
                return JSONResponse({'error': 'Origin is not allowed'}, status_code=403)
            length = request.headers.get('content-length', '0')
            if length.isdigit() and int(length) > 48 * 1024 * 1024:
                return JSONResponse({'error': 'Request body too large'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=422)

    @app.exception_handler(PhoenixError)
    async def domain_error(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.get('/health')
    async def health():
        return {'ok': True, 'version': __version__, 'engine': 'native'}

    @app.get('/api/overview')
    async def overview():
        counts = {}
        for table in ('challenges', 'runs', 'evidence', 'documents', 'memories', 'skills'):
            counts[table] = c.store.one(f'SELECT COUNT(*) AS n FROM {table}')['n']
        return {'version': __version__, 'engine': 'native-model-tool-loop', 'counts': counts,
                'runs': c.store.all('SELECT id,challenge_id,state,created,mode,reason,calls,billed_tokens '
                                    'FROM runs ORDER BY created DESC LIMIT 40'),
                'models': settings.public()['profiles'], 'docker_client_present': bool(shutil.which('docker')),
                'embedding_enabled': bool(settings.embedding_model and settings.embedding_base_url)}

    @app.get('/api/settings')
    async def configuration():
        return settings.public()

    @app.get('/api/challenges')
    async def challenges():
        return c.store.all('SELECT * FROM challenges ORDER BY created DESC LIMIT 200')

    @app.post('/api/challenges')
    async def add_challenge(spec: ChallengeInput):
        return c.store.create_challenge(spec)

    @app.get('/api/challenges/{cid}')
    async def challenge(cid: str):
        value = c.store.challenge(cid)
        value['files'] = SecureFiles(c.store.root / 'inputs' / cid).list()
        return value

    @app.post('/api/challenges/{cid}/files')
    async def upload(cid: str, spec: FileUpload):
        challenge = c.store.challenge(cid)
        if challenge['frozen']:
            raise Conflict('Inputs are frozen after a run is created; make a new challenge for changed inputs')
        data = base64.b64decode(spec.data_base64, validate=True)
        fs = SecureFiles(c.store.root / 'inputs' / cid)
        if sum(item['size'] for item in fs.list()) + len(data) > 128 * 1024 * 1024:
            raise ValueError('Total challenge input upload limit is 128 MiB')
        fs.write(spec.name, data)
        return {'name': spec.name, 'bytes': len(data)}

    @app.post('/api/challenges/{cid}/verifier')
    async def verifier(cid: str, spec: VerificationConfig):
        c.store.challenge(cid)
        if c.store.all("SELECT id FROM runs WHERE challenge_id=? AND mode='benchmark'", (cid,)):
            raise Conflict('Benchmark answer keys are immutable after creation')
        c.store.execute('INSERT INTO verifiers VALUES(?,?) ON CONFLICT(challenge_id) DO UPDATE '
                        'SET expected_sha256=excluded.expected_sha256', (cid, spec.expected_sha256))
        c.store.audit('verifier.configured', {'challenge_id': cid})
        return {'configured': True}

    @app.post('/api/challenges/{cid}/runs')
    async def start_run(cid: str, spec: RunInput):
        c.runtime.swarm.validate(spec, c.store.challenge(cid)['category'], require_models=True)
        for role in ('planner', 'distiller'):
            if role == 'distiller' and not spec.auto_distill:
                continue
            if not settings.profile(role).model:
                raise ValueError(f'Model profile for {role} is not configured')
        run = c.store.create_run(cid, spec)
        c.runtime.swarm.ensure(run['id'])
        c.runtime.launch(run['id'])
        return run

    @app.get('/api/runs/{rid}')
    async def run_details(rid: str):
        return {'run': c.store.run(rid), 'tasks': c.store.tasks(rid),
                'candidates': c.store.all('SELECT * FROM candidates WHERE run_id=? ORDER BY created', (rid,)),
                'facts': c.store.all('SELECT * FROM facts WHERE run_id=? ORDER BY created', (rid,)),
                'events': c.store.all('SELECT * FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 80', (rid,)),
                'evidence': c.store.all('SELECT id,task_id,tool,sha256,origin,truncated,ok,created FROM evidence '
                                       'WHERE run_id=? ORDER BY created DESC LIMIT 100', (rid,)),
                'executions': c.store.all('SELECT * FROM executions WHERE run_id=?', (rid,)),
                'evidence_handoffs': c.store.all('''SELECT e.task_id AS target_task_id,
                    src.task_id AS source_task_id, src.id AS evidence_id, e.created
                    FROM evidence e JOIN evidence src ON src.id=json_extract(e.arguments,'$.evidence_id')
                    AND src.run_id=e.run_id WHERE e.run_id=? AND e.tool='evidence_read' AND e.ok=1
                    ORDER BY e.created''', (rid,)),
                'model_calls': c.store.all('''SELECT m.id,m.role,m.status,m.input_tokens,m.output_tokens,
                    m.cost_usd,m.created,m.ended,s.worker_id,s.task_id FROM model_calls m
                    LEFT JOIN swarm_calls s ON s.call_id=m.id WHERE m.run_id=? ORDER BY m.created''', (rid,))}

    @app.get('/api/runs/{rid}/events')
    async def events(rid: str, after: int = 0):
        c.store.run(rid)
        return c.store.all('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 200', (rid, after))

    @app.get('/api/runs/{rid}/stream')
    async def stream(rid: str, request: Request, after: int = 0):
        c.store.run(rid)
        cursor = max(after, int(request.headers.get('last-event-id', '0')))
        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                rows = c.store.all('SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 100', (rid, cursor))
                for row in rows:
                    cursor = row['seq']
                    yield f'id: {cursor}\ndata: {dump(row)}\n\n'
                if not rows:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type='text/event-stream')

    @app.post('/api/runs/{rid}/pause')
    async def pause(rid: str):
        await c.runtime.pause(rid)
        return c.store.run(rid)

    @app.post('/api/runs/{rid}/reconcile')
    async def reconcile(rid: str):
        run = c.store.run(rid)
        if run['state'] in ('running', 'distilling'):
            raise Conflict('Pause the run before reconciling uncertain containers')
        return await c.tools.sandbox.reconcile(rid)

    @app.post('/api/runs/{rid}/resume')
    async def resume(rid: str, spec: ResumeInput):
        c.store.resume(rid, spec.acknowledge_uncertain)
        c.runtime.launch(rid)
        return c.store.run(rid)

    @app.get('/api/runs/{rid}/evidence/{eid}')
    async def evidence(rid: str, eid: str, offset: int = 0, length: int = 12000):
        return c.evidence.read(rid, eid, offset, length)

    @app.post('/api/candidates/{cid}/receipt')
    async def receipt(cid: str, spec: ReceiptInput):
        c.evidence.operator_receipt(cid, spec.accepted, spec.receipt)
        row = c.store.one('SELECT run_id,status FROM candidates WHERE id=?', (cid,))
        rid = row['run_id']
        c.store.event(rid, 'flag.operator_receipt', {'id': cid, 'status': row['status'],
                                                   'verification_source': 'operator-reported'})
        run = c.store.run(rid)
        # Active runs own their lifecycle; only reconcile already settled outcomes here.
        if run['state'] not in ('created', 'running', 'distilling', 'paused', 'interrupted'):
            accepted = c.store.all("SELECT id FROM candidates WHERE run_id=? AND status='accepted'", (rid,))
            if accepted:
                c.store.state(rid, 'solved', 'Operator-reported answer receipt; not an automatic platform check')
            elif run['state'] == 'solved':
                c.store.state(rid, 'awaiting_verification', 'The last accepted candidate was revoked by the operator')
            c.memory.consolidate_episode(rid)
        return {'recorded': True, 'run_state': c.store.run(rid)['state']}


    @app.get('/api/runs/{rid}/writeup')
    async def writeup(rid: str):
        return c.writeup.describe(rid)

    @app.post('/api/runs/{rid}/writeup')
    async def writeup_generate(rid: str, spec: PaidInput):
        run = c.store.run(rid)
        if run['state'] in ('created', 'running', 'distilling'):
            raise Conflict('运行结束后再生成复盘')
        return await c.writeup.generate(rid, c.gateway, spec.confirm_paid)

    @app.get('/api/runs/{rid}/writeup/export')
    async def writeup_export(rid: str):
        record = c.writeup.describe(rid)
        return PlainTextResponse(record['body'], headers={
            'Content-Disposition': f'attachment; filename="{rid}-writeup.md"'})

    @app.get('/api/runs/{rid}/writeup/evidence')
    async def writeup_evidence_export(rid: str):
        return PlainTextResponse(c.writeup.evidence_export(rid), headers={
            'Content-Disposition': f'attachment; filename="{rid}-evidence.md"'})

    @app.get('/api/knowledge')
    async def knowledge_list():
        return c.store.all('SELECT id,title,category,source,sha256,trust,created FROM documents ORDER BY created DESC')

    @app.post('/api/knowledge')
    async def knowledge_add(spec: KnowledgeInput):
        did = c.knowledge.ingest(spec.title, spec.body, spec.category, spec.source, spec.trusted)
        return {'document_id': did}

    @app.get('/api/knowledge/search')
    async def knowledge_search(q: str, category: str | None = None):
        return c.knowledge.search(q, category)

    @app.get('/api/knowledge/{did}')
    async def knowledge_document(did: str):
        return c.store.one('SELECT * FROM documents WHERE id=?', (did,))

    @app.post('/api/knowledge/{did}/review')
    async def knowledge_review(did: str, spec: ReviewInput):
        c.knowledge.trust(did, spec.approved)
        return {'approved': spec.approved}

    @app.post('/api/knowledge/{did}/index')
    async def knowledge_index(did: str, spec: PaidInput):
        return {'indexed_chunks': await c.knowledge.index(did, spec.confirm_paid)}

    @app.get('/api/memories')
    async def memories():
        return [c.memory.describe(row['id']) for row in c.store.all('SELECT id FROM memories ORDER BY created DESC')]

    @app.get('/api/memories/{mid}')
    async def memory(mid: str):
        value = c.memory.describe(mid)
        value['sources'] = c.store.all('SELECT * FROM memory_sources WHERE memory_id=?', (mid,))
        return value

    @app.post('/api/memories/{mid}/review')
    async def memory_review(mid: str, spec: ReviewInput):
        return c.memory.review(mid, spec.approved)

    @app.post('/api/memories/{mid}/strategy')
    async def memory_strategy(mid: str, spec: SkillFromMemory):
        return c.evolution.from_memory(mid, spec.key)

    @app.post('/api/runs/{rid}/distill')
    async def distill(rid: str, spec: PaidInput):
        if not spec.confirm_paid:
            raise ValueError('Distillation calls a configured model; confirm API charges')
        run = c.store.run(rid)
        if run['state'] in ('created', 'running', 'distilling', 'paused', 'interrupted'):
            raise Conflict('Only a terminal run can be manually distilled')
        changed = c.store.execute("UPDATE runs SET state='distilling' WHERE id=? AND state=?", (rid, run['state']))
        if not changed:
            raise Conflict('The run state changed')
        try:
            return {'memory_ids': await c.memory.distill(rid, c.gateway)}
        finally:
            c.store.state(rid, run['state'], run['reason'])
            c.memory.consolidate_episode(rid)

    @app.get('/api/skills')
    async def skills():
        return c.store.all('SELECT * FROM skills ORDER BY key,version DESC')

    @app.post('/api/skills')
    async def skill_propose(spec: SkillSpec):
        return c.evolution.propose(spec)

    @app.get('/api/evaluations')
    async def evaluations():
        return c.store.all('SELECT * FROM evaluations ORDER BY created DESC')

    @app.post('/api/skills/{sid}/evaluate')
    async def evaluate(sid: str, spec: EvaluateInput):
        if not spec.confirm_model_charges:
            raise ValueError('A paired benchmark makes real model calls; explicitly confirm the cost')
        return await c.evaluator.evaluate(sid, spec.suite, spec.run)

    @app.post('/api/skills/{sid}/promote')
    async def promote(sid: str, spec: PromoteInput):
        return c.evolution.promote(sid, spec.evaluation_id)

    @app.post('/api/skills/{sid}/rollback')
    async def rollback(sid: str):
        c.evolution.rollback(sid)
        return {'restored': sid}

    @app.get('/api/learning')
    async def learning_cycles():
        return c.store.all('SELECT * FROM learning_cycles ORDER BY created DESC')

    @app.post('/api/runs/{rid}/learn')
    async def learn(rid: str, spec: LearnInput):
        if not spec.confirm_model_charges:
            raise ValueError('A learning cycle runs a paired model benchmark; confirm the total API cost')
        return await c.learning.execute(rid, spec.suite, spec.run, spec.auto_promote)

    @app.post('/api/demo')
    async def demo():
        return await create_demo(c)

    @app.post('/api/swarm-demo')
    async def swarm_demo():
        from .swarm_demo import create_swarm_demo
        return await create_swarm_demo(c)

    from .swarm import attach_swarm
    attach_swarm(app, c)

    from .workbench import attach_workbench
    attach_workbench(app, c)

    from .solving import attach_solving
    attach_solving(app, c)
    from .operator_config import attach_operator_config
    attach_operator_config(app, c)
    from .fusion_api import attach_fusion
    attach_fusion(app, c)
    from .competition_api import attach_competition
    attach_competition(app, c)
    from .orchestration_api import attach_orchestration
    attach_orchestration(app, c)
    from .auth_api import attach_auth
    attach_auth(app, c)
    from .extensions_api import attach_extensions
    attach_extensions(app, c)

    @app.get('/')
    async def index():
        return HTMLResponse('<!doctype html><html lang="en"><title>Phoenix API</title>'
                            '<h1>Phoenix API</h1><p>The Phoenix-derived workbench runs separately.</p>'
                            '<p>Start both services with <code>bash scripts/start.sh</code> '
                            'and open <a href="http://127.0.0.1:3001">localhost:3001</a>.</p></html>')

    return app
