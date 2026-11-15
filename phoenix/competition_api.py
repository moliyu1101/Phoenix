from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from .competition import CompetitionPolicy
from .domain import Strict


class CompetitionInput(Strict):
    connection_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]{1,100}$')
    title: str = Field(min_length=1, max_length=180)
    external_competition_id: str = Field(default='', max_length=300)
    policy: CompetitionPolicy = Field(default_factory=CompetitionPolicy)


class SchedulerAction(Strict):
    action: Literal['start', 'pause', 'resume']


class PriorityInput(Strict):
    priority: int = Field(ge=0, le=100)


def attach_competition(app, c):
    router = APIRouter(prefix='/api')

    @router.get('/competitions')
    async def competitions():
        return c.competitions.list()

    @router.post('/competitions')
    async def register(spec: CompetitionInput):
        return c.competitions.register(spec.connection_id, spec.title, spec.external_competition_id,
                                       spec.policy.model_dump(mode='json'))

    @router.get('/competitions/{competition_id}')
    async def competition(competition_id: str):
        return c.competitions.describe(competition_id)

    @router.delete('/competitions/{competition_id}')
    async def remove(competition_id: str):
        return c.competitions.remove(competition_id)

    @router.post('/competitions/{competition_id}/sync')
    async def sync(competition_id: str):
        return await c.competitions.sync(competition_id)

    @router.patch('/competitions/{competition_id}/policy')
    async def policy(competition_id: str, spec: CompetitionPolicy):
        return c.competitions.set_policy(competition_id, spec.model_dump(mode='json'))

    @router.post('/competitions/{competition_id}/scheduler')
    async def scheduler(competition_id: str, spec: SchedulerAction):
        return c.competitions.scheduler(competition_id, spec.action)

    @router.post('/competitions/{competition_id}/tick')
    async def tick(competition_id: str):
        return await c.competitions.tick(competition_id)

    @router.get('/competitions/{competition_id}/queue')
    async def queue(competition_id: str):
        return c.competitions.queue(competition_id)

    @router.patch('/competitions/{competition_id}/queue/{entry_id}')
    async def priority(competition_id: str, entry_id: str, spec: PriorityInput):
        return c.competitions.set_priority(competition_id, entry_id, spec.priority)

    @router.post('/competitions/{competition_id}/queue/{entry_id}/admit')
    async def admit(competition_id: str, entry_id: str):
        return await c.competitions.admit(competition_id, entry_id)

    @router.post('/competitions/{competition_id}/queue/{entry_id}/skip')
    async def skip(competition_id: str, entry_id: str):
        return c.competitions.skip(competition_id, entry_id)

    @router.post('/competitions/{competition_id}/queue/{entry_id}/requeue')
    async def requeue(competition_id: str, entry_id: str):
        return c.competitions.requeue(competition_id, entry_id)

    app.include_router(router)