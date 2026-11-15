from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATEGORIES = ('web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc')
Category = Literal['web', 'crypto', 'pwn', 'reverse', 'forensics', 'misc']


def uid(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:20]}'


def now() -> float:
    return time.time()


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ChallengeInput(Strict):
    title: str = Field(min_length=1, max_length=180)
    category: Category = 'misc'
    description: str = Field(min_length=1, max_length=24000)
    targets: list[str] = Field(default_factory=list, max_length=20)
    # Compatibility field: using Phoenix establishes the operator's authorization.
    authorized: bool = True
    flag_prefix: str = Field(default='flag', pattern=r'^[A-Za-z0-9_]{1,32}$')

    @field_validator('targets')
    @classmethod
    def validate_targets(cls, values: list[str]) -> list[str]:
        result = []
        for value in values:
            p = urlsplit(value)
            if p.scheme not in ('http', 'https', 'tcp') or not p.hostname or p.username or p.password:
                raise ValueError('Targets must be explicit http(s) or tcp origins, without credentials')
            if p.path not in ('', '/') or p.query or p.fragment or '%' in p.netloc:
                raise ValueError('Specify an origin, not a URL path, query or encoded host')
            if p.scheme == 'tcp' and p.port is None:
                raise ValueError('TCP targets require a port')
            if p.port is not None and not 1 <= p.port <= 65535:
                raise ValueError('Invalid target port')
            host = p.hostname.lower()
            if ':' in host:
                host = f'[{host}]'
            default = 443 if p.scheme == 'https' else 80
            port = p.port or default
            origin = f'{p.scheme}://{host}:{port}'
            if origin not in result:
                result.append(origin)
        return result


class BudgetSpec(Strict):
    max_calls: int = Field(default=36, ge=1, le=1000)
    max_tokens: int = Field(default=120000, ge=500, le=10000000)
    max_usd: float | None = Field(default=None, gt=0, le=10000)
    wall_seconds: int = Field(default=1200, ge=10, le=86400)


class RunInput(Strict):
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    concurrency: int = Field(default=4, ge=1, le=16)
    worker_ids: list[str] = Field(default_factory=list, max_length=32)
    max_rounds: int = Field(default=5, ge=1, le=30)
    max_turns: int = Field(default=12, ge=1, le=100)
    auto_distill: bool = True


class TaskSpec(Strict):
    key: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,47}$')
    goal: str = Field(min_length=5, max_length=3000)
    role: Literal['analyst', 'solver', 'reviewer'] = 'solver'
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    priority: int = Field(default=50, ge=0, le=100)


class Plan(Strict):
    rationale: str = Field(max_length=3000)
    tasks: list[TaskSpec] = Field(default_factory=list, max_length=12)
    stop: bool = False


class Quote(Strict):
    evidence_id: str
    quote: str = Field(min_length=3, max_length=3000)


class Lesson(Strict):
    title: str = Field(min_length=3, max_length=180)
    category: Category
    kind: Literal['procedure', 'negative', 'observation']
    applicability: str = Field(min_length=8, max_length=1500)
    steps: list[str] = Field(min_length=1, max_length=12)
    pitfalls: list[str] = Field(default_factory=list, max_length=12)
    citations: list[Quote] = Field(min_length=1, max_length=12)

    @field_validator('steps', 'pitfalls')
    @classmethod
    def bounded_text(cls, items: list[str]) -> list[str]:
        if any(not x.strip() or len(x) > 2000 for x in items):
            raise ValueError('Each procedure entry must be 1..2000 characters')
        return items


class DistilledLesson(Lesson):
    # Distillers select immutable excerpts; only the server fills exact quotes.
    citations: list[Quote] = Field(default_factory=list, max_length=12)
    citation_ids: list[str] = Field(default_factory=list, max_length=12)


class Distillation(Strict):
    lessons: list[DistilledLesson] = Field(default_factory=list, max_length=6)


class WriteupStep(Strict):
    heading: str = Field(min_length=2, max_length=120)
    detail: str = Field(min_length=4, max_length=4000)
    citation_ids: list[str] = Field(default_factory=list, max_length=8)


class Reproduction(Strict):
    reproducible: bool = False
    notes: str = Field(min_length=4, max_length=3000)
    gaps: list[str] = Field(default_factory=list, max_length=10)


class WriteupDoc(Strict):
    # The model selects immutable excerpt IDs; only the server attaches exact quotes.
    title: str = Field(min_length=2, max_length=180)
    overview: str = Field(min_length=4, max_length=3000)
    analysis: str = Field(min_length=4, max_length=6000)
    steps: list[WriteupStep] = Field(min_length=1, max_length=16)
    reproduction: Reproduction
    conclusion: str = Field(min_length=4, max_length=3000)
    citation_ids: list[str] = Field(default_factory=list, max_length=24)


class SkillSpec(Strict):
    key: str = Field(pattern=r'^[a-z][a-z0-9_-]{2,59}$')
    category: Category
    applicability: str = Field(min_length=8, max_length=1500)
    instructions: list[str] = Field(min_length=1, max_length=16)
    stop_conditions: list[str] = Field(default_factory=list, max_length=8)
    memory_ids: list[str] = Field(default_factory=list, max_length=12)

    @field_validator('instructions', 'stop_conditions')
    @classmethod
    def bounded_text(cls, items: list[str]) -> list[str]:
        if any(not x.strip() or len(x) > 2000 for x in items):
            raise ValueError('Skill entries must be 1..2000 characters')
        return items


class ToolCall(Strict):
    id: str
    name: str
    arguments: dict[str, Any]


class Completion(Strict):
    text: str = ''
    calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Provider-specific assistant content must be replayed intact (e.g. signed reasoning blocks).
    assistant: dict[str, Any] = Field(default_factory=dict)


class PhoenixError(Exception):
    pass


class BudgetExceeded(PhoenixError):
    pass


class ContextExceeded(PhoenixError):
    pass


class ScopeViolation(PhoenixError):
    pass


class Conflict(PhoenixError):
    pass


class NotFound(PhoenixError):
    pass


def parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text)
    return json.loads(text)
