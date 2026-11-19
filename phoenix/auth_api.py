"""Session-protocol-2 auth endpoints consumed by the web workbench.

``/api/auth/login`` mints an HttpOnly cookie session; ``/api/auth/me`` reports the
service identity; ``/api/auth/ticket`` mints a one-time ticket for EventSource and
WebSocket links that cannot send an Authorization header. ``/api/settings/access``
reads and rotates the operator password. The legacy Bearer token keeps working for
every route, so programmatic clients and the token login gate are unaffected.
"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from .auth import COOKIE_NAME, PERSISTENCE_WARNING, REMEMBER_TTL, SESSION_TTL
from .domain import Strict


class LoginInput(Strict):
    password: str = Field(min_length=1, max_length=4096)
    remember: bool = True
    client: str = Field(default='web', pattern=r'^(web|desktop)$')


class AccessInput(Strict):
    action: str = Field(pattern=r'^(set|inherit)$')
    current_password: str = Field(default='', max_length=4096)
    new_password: str = Field(default='', max_length=4096)


def attach_auth(app, c) -> None:
    auth = c.auth
    router = APIRouter(prefix='/api')

    @router.post('/auth/login')
    async def login(body: LoginInput, request: Request, response: Response):
        if not auth.verify_password(body.password):
            return JSONResponse({'error': {'code': 'auth.invalid', 'message': '密码不正确。'}}, status_code=401)
        sid, expires = auth.issue_session(body.client, body.remember)
        response.set_cookie(COOKIE_NAME, sid, max_age=REMEMBER_TTL if body.remember else SESSION_TTL,
                            httponly=True, samesite='lax', secure=request.url.scheme == 'https', path='/')
        return {**auth.identity(expires), 'ok': True,
                'session_owner': 'desktop' if body.client == 'desktop' else 'cookie',
                'persistence_warning': PERSISTENCE_WARNING}

    @router.get('/auth/me')
    async def me(request: Request):
        session = auth.session(getattr(request.state, 'auth_session', None))
        return {**auth.identity(session['expires'] if session else None), 'authenticated': True}

    @router.post('/auth/logout')
    async def logout(request: Request, response: Response):
        auth.revoke(request.cookies.get(COOKIE_NAME))
        response.delete_cookie(COOKIE_NAME, path='/')
        return {'ok': True}

    @router.post('/auth/ticket')
    async def ticket():
        return {'ticket': auth.issue_ticket()}

    @router.get('/settings/access')
    async def get_access():
        return auth.access_config()

    @router.put('/settings/access')
    async def put_access(body: AccessInput):
        if not auth.verify_password(body.current_password):
            return JSONResponse({'error': {'code': 'auth.invalid', 'message': '当前密码不正确。'}}, status_code=401)
        if body.action == 'set':
            if len(body.new_password) < 8:
                return JSONResponse({'error': {'code': 'auth.weak', 'message': '新密码至少需要 8 个字符。'}}, status_code=422)
            auth.set_password(body.new_password)
        else:
            auth.clear_override()
        return auth.access_config()

    app.include_router(router)