"""Cookie sessions, one-time stream tickets and the operator access password.

The legacy Bearer ``PHOENIX_WEB_TOKEN`` stays valid for programmatic clients; the
web workbench additionally signs in with a password and holds an HttpOnly cookie.
Sessions and tickets live in process memory only, so a restart signs everyone out
(the login reply carries a ``persistence_warning`` saying exactly that). No secret
is ever returned to the client or written to the event ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from .config import Settings, env_value
from .domain import digest, now

COOKIE_NAME = 'phoenix_session'
SESSION_TTL = 12 * 3600
REMEMBER_TTL = 30 * 24 * 3600
TICKET_TTL = 60
PBKDF2_ITERATIONS = 200_000
PERSISTENCE_WARNING = '会话保存在服务内存中，服务重启后需要重新登录。'


class Auth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.service_id = digest(str(settings.data_dir))[:16]
        self.identity_id = 'operator'
        self._sessions: dict[str, dict] = {}
        self._tickets: dict[str, float] = {}
        self._override_path = settings.data_dir / 'access-config.json'

    # ---- access password -------------------------------------------------
    def _env_password(self) -> str:
        return env_value('PHOENIX_WEB_PASSWORD')

    def _override(self) -> dict | None:
        try:
            value = json.loads(self._override_path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) and value.get('hash') else None

    def has_override(self) -> bool:
        return self._override() is not None

    def environment_configured(self) -> bool:
        return bool(self._env_password())

    def source(self) -> str:
        if self.has_override():
            return 'settings'
        return 'environment' if self.environment_configured() else 'none'

    def auth_required(self) -> bool:
        return True

    def can_disable(self) -> bool:
        return False

    @staticmethod
    def _hash(password: str, salt: bytes) -> str:
        return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF2_ITERATIONS).hex()

    def verify_password(self, submitted: str) -> bool:
        if not submitted:
            return False
        override = self._override()
        if override:
            try:
                salt = bytes.fromhex(override['salt'])
            except (KeyError, ValueError):
                return False
            return hmac.compare_digest(self._hash(submitted, salt), override['hash'])
        env = self._env_password()
        if env:
            return hmac.compare_digest(submitted, env)
        token = self.settings.web_token
        return bool(token) and hmac.compare_digest(submitted, token)

    def set_password(self, new_password: str) -> None:
        salt = secrets.token_bytes(16)
        payload = {'salt': salt.hex(), 'hash': self._hash(new_password, salt), 'iterations': PBKDF2_ITERATIONS}
        self._override_path.parent.mkdir(parents=True, exist_ok=True)
        self._override_path.write_text(json.dumps(payload), 'utf-8')
        try:
            os.chmod(self._override_path, 0o600)
        except OSError:
            pass
        self.revoke_all()

    def clear_override(self) -> None:
        try:
            self._override_path.unlink()
        except OSError:
            pass
        self.revoke_all()

    def access_config(self) -> dict:
        return {'auth_required': self.auth_required(), 'source': self.source(),
                'environment_configured': self.environment_configured(), 'has_override': self.has_override(),
                'session_ttl_seconds': SESSION_TTL, 'can_disable': self.can_disable(),
                'service_id': self.service_id}

    # ---- cookie sessions -------------------------------------------------
    def _prune(self) -> None:
        current = now()
        for sid in [s for s, row in self._sessions.items() if row['expires'] <= current]:
            del self._sessions[sid]
        for ticket in [t for t, exp in self._tickets.items() if exp <= current]:
            del self._tickets[ticket]

    def issue_session(self, client: str, remember: bool) -> tuple[str, int]:
        self._prune()
        sid = secrets.token_urlsafe(32)
        expires = int(now()) + (REMEMBER_TTL if remember else SESSION_TTL)
        self._sessions[sid] = {'expires': expires, 'created': int(now()), 'client': client}
        return sid, expires

    def session(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        self._prune()
        row = self._sessions.get(sid)
        return row if row and row['expires'] > now() else None

    def revoke(self, sid: str | None) -> None:
        if sid:
            self._sessions.pop(sid, None)

    def revoke_all(self) -> None:
        self._sessions.clear()
        self._tickets.clear()

    # ---- one-time stream tickets -----------------------------------------
    def issue_ticket(self) -> str:
        self._prune()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = now() + TICKET_TTL
        return ticket

    def consume_ticket(self, ticket: str | None) -> bool:
        if not ticket:
            return False
        self._prune()
        expires = self._tickets.pop(ticket, None)
        return expires is not None and expires > now()

    # ---- protocol-2 identity ---------------------------------------------
    @staticmethod
    def in_container() -> bool:
        return Path('/.dockerenv').exists() or Path('/run/.containerenv').exists()

    def identity(self, expires_at: int | None = None) -> dict:
        return {'session_protocol': 2, 'service_id': self.service_id, 'identity_id': self.identity_id,
                'auth_required': self.auth_required(), 'in_container': self.in_container(),
                'expires_at': expires_at}