from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv
from pydantic import Field, field_validator, model_validator

from .domain import Strict


def env_value(name: str, default: str = '') -> str:
    """Phoenix variables win, including an explicitly empty value."""
    if name in os.environ:
        return os.environ[name]
    return default


class ModelProfile(Strict):
    protocol: Literal['chat', 'anthropic'] = 'chat'
    base_url: str = 'https://api.openai.com/v1'
    model: str = ''
    api_key_env: str = 'PHOENIX_API_KEY'
    context_tokens: int = Field(default=32768, ge=4096, le=2000000)
    output_tokens: int = Field(default=4096, ge=256, le=64000)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
    timeout_seconds: int = Field(default=120, ge=5, le=900)
    chat_token_parameter: Literal['max_tokens', 'max_completion_tokens'] = 'max_completion_tokens'

    @field_validator('base_url')
    @classmethod
    def url_is_valid(cls, url: str) -> str:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query:
            raise ValueError('Invalid model endpoint')
        return url.rstrip('/')

    @property
    def key(self) -> str:
        return env_value(self.api_key_env)


class WorkerProfile(Strict):
    id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,47}$')
    name: str = Field(min_length=1, max_length=80)
    roles: list[Literal['analyst', 'solver', 'reviewer']] = Field(min_length=1, max_length=3)
    categories: list[Literal['web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc']] = Field(default_factory=list)
    profile: str | None = None
    instructions: str = Field(default='', max_length=3000)
    enabled: bool = True
    engine: str = Field(default='api', pattern=r'^[a-z][a-z0-9-]{0,31}$')


def default_workers() -> list[WorkerProfile]:
    return [
        WorkerProfile(id='scout', name='Recon Analyst', roles=['analyst']),
        WorkerProfile(id='solver-a', name='Solver Alpha', roles=['solver']),
        WorkerProfile(id='solver-b', name='Solver Beta', roles=['solver'],
                      instructions='Prefer complementary experiments to other solvers. Read shared facts first.'),
        WorkerProfile(id='reviewer', name='Independent Reviewer', roles=['reviewer']),
    ]


class Settings(Strict):
    data_dir: Path = Path('data')
    host: str = '127.0.0.1'
    port: int = Field(default=18750, ge=1024, le=65535)
    token_env: str = 'PHOENIX_WEB_TOKEN'
    profiles: dict[str, ModelProfile] = Field(default_factory=lambda: {'default': ModelProfile()})
    roles: dict[str, str] = Field(default_factory=lambda: {
        'planner': 'default', 'analyst': 'default', 'solver': 'default',
        'reviewer': 'default', 'distiller': 'default',
    })
    workers: list[WorkerProfile] = Field(default_factory=default_workers, min_length=1, max_length=32)
    sandbox_image: str = 'phoenix-tools:0.1.0'
    sandbox_memory: str = '1024m'
    sandbox_cpus: float = Field(default=1.0, gt=0, le=8)
    sandbox_images: dict[str, str] = Field(default_factory=lambda: {
        category: f'phoenix-tools-{category}:0.1.0'
        for category in ('web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc')})
    max_output_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=16 * 1024 * 1024)
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_key_env: str = 'PHOENIX_EMBEDDING_KEY'
    embedding_input_usd_per_million: float | None = Field(default=None, ge=0)
    allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def validate_workers(self):
        ids = [worker.id for worker in self.workers]
        if len(set(ids)) != len(ids):
            raise ValueError('Worker IDs must be unique')
        for worker in self.workers:
            if worker.profile and worker.profile not in self.profiles:
                raise ValueError(f'Unknown worker model profile: {worker.profile}')
        return self

    def profile(self, role: str) -> ModelProfile:
        name = self.roles.get(role, 'default')
        if name not in self.profiles:
            raise ValueError(f'Unknown model profile {name!r} for role {role!r}')
        return self.profiles[name]

    @property
    def web_token(self) -> str:
        return env_value(self.token_env)

    def public(self) -> dict:
        value = self.model_dump(mode='json')
        value['profiles'] = {k: {**v.model_dump(), 'key_configured': bool(v.key)}
                             for k, v in self.profiles.items()}
        return value


def load_settings(path: str | Path = 'config.yaml') -> Settings:
    load_dotenv(override=False)
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    raw = raw or {}
    settings = Settings.model_validate(raw)
    settings.data_dir = Path(env_value('PHOENIX_DATA_DIR') or str(settings.data_dir)).resolve()
    default = settings.profiles.get('default')
    if default:
        values = default.model_dump()
        if env_value('PHOENIX_MODEL').strip():
            values['model'] = env_value('PHOENIX_MODEL').strip()
        if env_value('PHOENIX_BASE_URL').strip():
            values['base_url'] = env_value('PHOENIX_BASE_URL').strip().rstrip('/')
        settings.profiles['default'] = ModelProfile.model_validate(values)
    for role in settings.roles:
        settings.profile(role)
    # The native settings UI owns only model/role/roster overrides, never ports or data paths.
    import json
    operator = settings.data_dir / 'operator-config.json'
    if operator.exists():
        saved = json.loads(operator.read_text(encoding='utf-8'))
        merged = settings.model_dump()
        for name in ('profiles', 'roles', 'workers'):
            if name in saved:
                merged[name] = saved[name]
        settings = Settings.model_validate(merged)
        for role in settings.roles:
            settings.profile(role)
    credentials = settings.data_dir / 'model-credentials.json'
    if credentials.exists():
        for name, value in json.loads(credentials.read_text(encoding='utf-8')).items():
            if name.startswith('PHOENIX_') and name.endswith('_KEY'):
                os.environ[name] = value
    return settings
