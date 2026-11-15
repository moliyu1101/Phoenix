"""Native conversation, durable chronological replay and workspace inspection."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import Field, field_validator

from .domain import Conflict, NotFound, RunInput, Strict, dump, now
from .filesystem import SecureFiles


class OperatorMessage(Strict):
    content: str = Field(min_length=1, max_length=8000)

    @field_validator('content')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Message cannot be blank')
        return value.strip()


def attach_solving(app, c):
    router = APIRouter(prefix='/api/runs/{rid}')

    @app.get('/api/usage')
    async def usage(run_id: str):
        c.store.run(run_id)
        rows = c.store.all('''SELECT m.*,s.worker_id FROM model_calls m
            LEFT JOIN swarm_calls s ON s.call_id=m.id WHERE m.run_id=?''', (run_id,))

        def totals(items):
            token_rows = [r for r in items if r['input_tokens'] is not None and r['output_tokens'] is not None]
            priced = [r for r in items if r['cost_usd'] is not None]
            amount = sum(r['cost_usd'] for r in priced) if priced else None
            return {'records': len(items), 'input_tokens': sum(r['input_tokens'] for r in token_rows) if token_rows else None,
                    'output_tokens': sum(r['output_tokens'] for r in token_rows) if token_rows else None,
                    'total_tokens': sum(r['input_tokens'] + r['output_tokens'] for r in token_rows) if token_rows else None,
                    'token_coverage': 'complete' if len(token_rows) == len(items) else 'partial',
                    'cost': amount, 'estimated_cost': amount, 'reported_cost': None,
                    'unpriced': len(items) - len(priced), 'pricing_coverage': {'custom': len(priced)},
                    'pricing_issues': []}

        groups = {}
        for row in rows:
            actor = row['worker_id'] or ('coordinator' if row['role'] == 'planner' else row['role'])
            groups.setdefault(actor, []).append(row)
        return {'totals': totals(rows), 'groups': {'worker_id': [
            {'name': actor, **totals(items)} for actor, items in groups.items()]}}

    @router.get('/timeline')
    async def timeline(rid: str, after: int = Query(0, ge=0), before: int | None = Query(None, ge=1),
                       limit: int = Query(100, ge=1, le=200)):
        c.store.run(rid)
        # Actor is resolved at the event's sequence, never from a later reassignment.
        rows = c.store.all('''SELECT e.*, (SELECT json_extract(a.payload,'$.worker_id') FROM events a
            WHERE a.run_id=e.run_id AND a.task_id=e.task_id AND a.kind='swarm.assigned'
            AND a.seq<=e.seq ORDER BY a.seq DESC LIMIT 1) AS worker_id
            FROM events e WHERE e.run_id=? AND e.seq>? AND (? IS NULL OR e.seq<?)
            ORDER BY e.seq LIMIT ?''', (rid, after, before, before, limit + 1))
        more = len(rows) > limit
        rows = rows[:limit]
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return {'items': rows, 'has_more': more, 'next_after': rows[-1]['seq'] if rows else after}

    @router.post('/messages', status_code=201)
    async def message(rid: str, spec: OperatorMessage):
        # Persist before acknowledging; the next planner / worker context reads this.
        with c.store.tx() as db:
            run = db.execute('SELECT state FROM runs WHERE id=?', (rid,)).fetchone()
            if run is None:
                c.store.run(rid)
            if run['state'] not in ('created', 'running', 'paused', 'interrupted'):
                raise Conflict('This round has ended; use continue to start a new round')
            db.execute('INSERT INTO events(run_id,kind,payload,created) VALUES(?,?,?,?)',
                       (rid, 'operator.message', dump({'content': spec.content, 'delivery': 'next_context'}), now()))
        return {'recorded': True, 'delivery': 'next_context'}

    @router.post('/continue', status_code=201)
    async def continue_run(rid: str, spec: OperatorMessage):
        source = c.store.run(rid)
        if source['state'] in ('created', 'running', 'distilling', 'paused', 'interrupted'):
            raise Conflict('Pause/resume owns the current round; continue requires a terminal round')
        if source['mode'] != 'live':
            raise Conflict('Scripted fixtures cannot be continued as live model runs')
        config = RunInput.model_validate(source['config'])
        c.runtime.swarm.validate(config, c.store.challenge(source['challenge_id'])['category'], require_models=True)
        if not c.settings.profile('planner').model:
            raise ValueError('Planner model is not configured')
        if config.auto_distill and not c.settings.profile('distiller').model:
            raise ValueError('Distiller model is not configured')
        run = c.store.create_run(source['challenge_id'], config)
        c.store.event(run['id'], 'run.continued', {'source_run_id': rid,
            'summary': source['reason'], 'new_budget': True})
        c.store.event(run['id'], 'operator.message', {'content': spec.content, 'delivery': 'next_context'})
        c.runtime.swarm.ensure(run['id'])
        c.runtime.launch(run['id'])
        return run

    @router.get('/workspace')
    async def workspace(rid: str):
        run = c.store.run(rid)
        return {'inputs': SecureFiles(c.store.root / 'inputs' / run['challenge_id']).list(),
                'artifacts': c.tools.workspace(rid).list()}

    @router.get('/workspace/read')
    async def workspace_read(rid: str, path: str, area: Literal['input', 'work'] = 'work',
                             offset: int = Query(0, ge=0)):
        run = c.store.run(rid)
        fs = (SecureFiles(c.store.root / 'inputs' / run['challenge_id']) if area == 'input'
              else c.tools.workspace(rid))
        try:
            data = fs.read(path, offset, 32001)
        except FileNotFoundError as exc:
            raise NotFound('Workspace file does not exist') from exc
        except OSError as exc:
            raise ValueError('Workspace file cannot be read safely') from exc
        return {'path': path, 'area': area, 'offset': offset,
                'content': data[:32000].decode('utf-8', 'replace'),
                'next_offset': offset + 32000 if len(data) > 32000 else None,
                'note': 'UTF-8 text preview; binary bytes may display replacement characters'}

    app.include_router(router)
