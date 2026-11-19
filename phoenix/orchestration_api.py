from __future__ import annotations

from fastapi import APIRouter, Query


def attach_orchestration(app, c):
    router = APIRouter(prefix='/api')

    @router.get('/attention')
    async def attention():
        return c.attention.overview()

    @router.get('/effects')
    async def effects(kind: str | None = None, state: str | None = None, limit: int = Query(200, ge=1, le=500)):
        return {'health': c.effects.health(), 'effects': c.effects.list(kind=kind, state=state, limit=limit)}

    @router.get('/effects/{eid}')
    async def effect(eid: str):
        return c.effects.get(eid)

    @router.post('/effects/{eid}/retry')
    async def retry(eid: str):
        return c.effects.retry(eid)

    @router.post('/effects/{eid}/drop')
    async def drop(eid: str):
        return c.effects.drop(eid)

    app.include_router(router)