"""Persistent UI metadata for the Phoenix-derived Phoenix workbench.

This module does not dispatch to any legacy agent. Run operations remain owned
by the native Phoenix runtime; renaming a sidebar entry never mutates frozen
challenge inputs or evidence.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
import json
from pydantic import Field

from .domain import Conflict, Strict, now, uid
from .service import Components


class RunDisplayPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    pinned: bool | None = None
    archived: bool | None = None
    folder_id: str | None = None


class FolderInput(Strict):
    name: str = Field(min_length=1, max_length=100)


class ReorderInput(Strict):
    run_ids: list[str] = Field(min_length=1, max_length=1000)
    pinned: bool


def summary(c: Components, row: dict) -> dict:
    state = row['state']
    active = state in ('created', 'running', 'distilling')
    paused = state in ('paused', 'interrupted')
    status = ('running' if active else 'paused' if paused else 'solved'
              if state == 'solved' else 'failed' if state == 'failed' else 'finished')
    return {
        'run_id': row['id'], 'challenge_id': row['challenge_id'], 'mode': 'ctf',
        'name': row.get('display_name') or row['title'], 'category': row['category'],
        'started': True, 'finished': not active and not paused, 'solved': state == 'solved',
        'paused': paused, 'status': status, 'native_state': state, 'execution_mode': row['mode'],
        'pinned': bool(row.get('pinned')), 'archived': bool(row.get('archived')),
        'folder_id': row.get('folder_id'), 'order': row.get('sort_order') or 0,
        'updated': row['updated'], 'updated_at': row['updated'],
    }


def attach_workbench(app, c: Components) -> None:
    router = APIRouter(prefix='/api/workbench')

    @router.get('/runs')
    async def list_runs():
        rows = c.store.all('''SELECT r.*, c.title, c.category, m.name AS display_name,
            m.pinned, m.archived, m.folder_id, m.sort_order
            FROM runs r JOIN challenges c ON c.id=r.challenge_id
            LEFT JOIN workbench_runs m ON m.run_id=r.id
            WHERE COALESCE(m.hidden,0)=0 ORDER BY r.created DESC LIMIT 1000''')
        return [summary(c, row) for row in rows]

    @router.patch('/runs/{rid}')
    async def patch_run(rid: str, spec: RunDisplayPatch):
        c.store.run(rid)
        fields = spec.model_dump(exclude_unset=True)
        if any(fields.get(key) is None for key in ('name', 'pinned', 'archived') if key in fields):
            raise ValueError('Only folder_id may be null')
        if fields.get('folder_id'):
            c.store.one('SELECT id FROM workbench_folders WHERE id=?', (fields['folder_id'],))
        with c.store.tx() as db:
            db.execute('INSERT OR IGNORE INTO workbench_runs(run_id) VALUES(?)', (rid,))
            for key, value in fields.items():
                # Keys originate exclusively from the strict Pydantic schema.
                db.execute(f'UPDATE workbench_runs SET {key}=? WHERE run_id=?', (value, rid))
        c.store.audit('workbench.run.updated', {'run_id': rid, 'fields': fields})
        return {'updated': rid}

    @router.delete('/runs/{rid}')
    async def hide_run(rid: str):
        run = c.store.run(rid)
        if run['state'] in ('created', 'running', 'distilling'):
            raise Conflict('Pause or finish the run before hiding its sidebar entry')
        c.store.execute('''INSERT INTO workbench_runs(run_id,hidden) VALUES(?,1)
            ON CONFLICT(run_id) DO UPDATE SET hidden=1''', (rid,))
        c.store.audit('workbench.run.hidden', {'run_id': rid, 'evidence_preserved': True})
        return {'hidden': rid, 'evidence_preserved': True}

    @router.post('/runs/reorder')
    async def reorder(spec: ReorderInput):
        if len(set(spec.run_ids)) != len(spec.run_ids):
            raise ValueError('Duplicate run IDs')
        for rid in spec.run_ids:
            c.store.run(rid)
        with c.store.tx() as db:
            for index, rid in enumerate(spec.run_ids):
                db.execute('INSERT OR IGNORE INTO workbench_runs(run_id) VALUES(?)', (rid,))
                db.execute('UPDATE workbench_runs SET sort_order=?,pinned=? WHERE run_id=?',
                           (index, spec.pinned, rid))
        return {'reordered': len(spec.run_ids)}

    @router.get('/folders')
    async def folders():
        return c.store.all('SELECT id,name,sort_order AS "order" FROM workbench_folders ORDER BY sort_order,created')

    @router.post('/folders')
    async def add_folder(spec: FolderInput):
        fid = uid('folder')
        count = c.store.one('SELECT COUNT(*) AS n FROM workbench_folders')['n']
        c.store.execute('INSERT INTO workbench_folders VALUES(?,?,?,?)', (fid, spec.name, count, now()))
        return {'id': fid, 'name': spec.name, 'order': count}

    @router.patch('/folders/{fid}')
    async def rename_folder(fid: str, spec: FolderInput):
        c.store.one('SELECT id FROM workbench_folders WHERE id=?', (fid,))
        c.store.execute('UPDATE workbench_folders SET name=? WHERE id=?', (spec.name, fid))
        return {'renamed': fid}

    @router.delete('/folders/{fid}')
    async def delete_folder(fid: str):
        c.store.one('SELECT id FROM workbench_folders WHERE id=?', (fid,))
        with c.store.tx() as db:
            db.execute('UPDATE workbench_runs SET folder_id=NULL WHERE folder_id=?', (fid,))
            db.execute('DELETE FROM workbench_folders WHERE id=?', (fid,))
        return {'deleted': fid, 'runs_preserved': True}

    @router.get('/usage')
    async def usage():
        # Unpriced calls remain unknown; never render them as a genuine zero cost.
        return {'by_role': c.store.all('''SELECT role, COUNT(*) AS calls,
            SUM(COALESCE(input_tokens,0)) AS input_tokens,
            SUM(COALESCE(output_tokens,0)) AS output_tokens,
            SUM(cost_usd) AS priced_cost_usd,
            SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced_calls
            FROM model_calls GROUP BY role'''),
            'by_mode': c.store.all('''SELECT mode,COUNT(*) AS runs,
            SUM(billed_tokens) AS tokens FROM runs GROUP BY mode''')}

    @app.get('/api/agent-runtimes/descriptors')
    async def legacy_visualization_catalog():
        # The graph's optional legacy executor picker is not used by Phoenix.
        return {'schema_version': 1, 'descriptors': [], 'instances': []}

    @app.get('/api/runs/{rid}/graph/export')
    async def graph_export(rid: str, format: str = 'jsonl'):
        c.store.run(rid)
        rows = c.store.all('SELECT * FROM events WHERE run_id=? ORDER BY seq', (rid,))
        if format == 'sqlite':
            raise ValueError('Per-run SQLite export is not implemented; use JSONL or timeline')
        if format not in ('jsonl', 'timeline'):
            raise ValueError('Supported exports: jsonl, timeline')
        text = '\n'.join(json.dumps(row, ensure_ascii=False) if format == 'jsonl' else
                         f"{row['seq']} {row['created']} {row['kind']} {row['payload']}" for row in rows)
        return PlainTextResponse(text, headers={'Content-Disposition': f'attachment; filename="{rid}.{format}"'})

    app.include_router(router)
