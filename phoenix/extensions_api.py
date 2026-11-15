from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import Field

from .domain import Conflict, NotFound, Strict
from .extensions import Extensions


class MCPConfig(Strict):
    command: str | None = Field(default=None, max_length=2000)
    args: list[str] | None = Field(default=None, max_length=64)
    cwd: str | None = Field(default=None, max_length=2000)
    env: dict[str, str] | None = None
    url: str | None = Field(default=None, max_length=6000)
    headers: dict[str, str] | None = None
    timeout: int | None = Field(default=None, ge=1, le=120)


class MCPServerCreate(Strict):
    name: str = Field(min_length=1, max_length=120)
    transport: Literal['stdio', 'streamable-http', 'sse'] = 'stdio'
    config: MCPConfig = Field(default_factory=MCPConfig)
    enabled: bool = False


class MCPServerUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    transport: Literal['stdio', 'streamable-http', 'sse'] | None = None
    config: MCPConfig | None = None
    enabled: bool | None = None


class EnabledInput(Strict):
    enabled: bool


class ToolCallInput(Strict):
    name: str = Field(min_length=1, max_length=300)
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = Field(default=None, max_length=100)
    task_id: str | None = Field(default=None, max_length=100)


class PluginCreate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    manifest: dict[str, Any] | None = None
    path: str | None = Field(default=None, max_length=2000)
    enabled: bool = False


def attach_extensions(app, c):
    ext = getattr(c, 'extensions', None) or Extensions(c)
    c.extensions = ext
    router = APIRouter(prefix='/api/extensions')

    @app.exception_handler(NotFound)
    async def not_found(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=422)

    @router.get('/overview')
    async def overview():
        return ext.overview()

    @router.get('/tools')
    async def tools():
        return {'tools': ext.schemas()}

    @router.get('/mcp-servers')
    async def list_servers():
        return {'servers': ext.list_servers()}

    @router.post('/mcp-servers')
    async def create_server(spec: MCPServerCreate):
        return ext.create_server(spec.model_dump(exclude_none=True))

    @router.get('/mcp-servers/{sid}')
    async def get_server(sid: str):
        return ext.server(sid)

    @router.patch('/mcp-servers/{sid}')
    async def update_server(sid: str, spec: MCPServerUpdate):
        return ext.update_server(sid, spec.model_dump(exclude_none=True))

    @router.delete('/mcp-servers/{sid}')
    async def delete_server(sid: str):
        return ext.delete_server(sid)

    @router.post('/mcp-servers/{sid}/enabled')
    async def enable_server(sid: str, spec: EnabledInput):
        return ext.set_server_enabled(sid, spec.enabled)

    @router.post('/mcp-servers/{sid}/probe')
    async def probe_server(sid: str):
        return await ext.probe(sid)

    @router.post('/mcp-servers/{sid}/call')
    async def call_server_tool(sid: str, spec: ToolCallInput):
        return await ext.call_tool(sid, spec.name, spec.arguments, rid=spec.run_id, tid=spec.task_id)

    @router.get('/plugins')
    async def list_plugins():
        return {'plugins': ext.list_plugins()}

    @router.post('/plugins')
    async def create_plugin(spec: PluginCreate):
        return ext.create_plugin(spec.model_dump(exclude_none=True))

    @router.get('/plugins/{pid}')
    async def get_plugin(pid: str):
        return ext.plugin(pid)

    @router.post('/plugins/{pid}/enabled')
    async def enable_plugin(pid: str, spec: EnabledInput):
        return ext.set_plugin_enabled(pid, spec.enabled)

    @router.delete('/plugins/{pid}')
    async def delete_plugin(pid: str):
        return ext.delete_plugin(pid)

    app.include_router(router)
    return ext