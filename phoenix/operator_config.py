"""Operator-owned model and roster settings, never a legacy daemon facade."""
import json
import os
import re
from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import Field, StrictBool, StrictStr

from .config import ModelProfile, Settings, WorkerProfile
from .domain import Strict


class ConfigurationInput(Strict):
    profiles: dict[str, ModelProfile] | None = None
    roles: dict[str, str] | None = None
    workers: list[WorkerProfile] | None = Field(default=None, min_length=1, max_length=32)
    secrets: dict[str, str] = Field(default_factory=dict)


def atomic_json(folder, name, value):
    target = folder / name
    temp = folder / (name + '.pending')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, target)


class PresetAccent(Strict):
    kind: Literal['preset']
    id: Literal['azure', 'violet', 'teal', 'ember']


class CustomAccent(Strict):
    kind: Literal['custom']
    hue: float = Field(ge=0, lt=360, allow_inf_nan=False)


class DefaultModel(Strict):
    credentialId: str = Field(min_length=1, max_length=512)
    modelId: str = Field(min_length=1, max_length=512)


class UiValues(Strict):
    language: Literal['zh', 'en'] = 'zh'
    theme: Literal['light', 'dark', 'system'] = 'system'
    accent: PresetAccent | CustomAccent = PresetAccent(kind='preset', id='violet')
    sendKey: Literal['enter', 'mod-enter'] = 'enter'
    runningSend: Literal['queue', 'steer'] = 'queue'
    defaultAccessMode: Literal['', 'supervised', 'auto-accept-edits', 'auto', 'full-access'] = ''
    diffView: Literal['unified', 'split'] = 'unified'
    diffWrap: StrictBool = False
    diffCollapseUnchanged: StrictBool = False
    readingFontScale: Literal['sm', 'md', 'lg'] = 'md'
    readingDensity: Literal['comfortable', 'compact'] = 'comfortable'
    readingContentWidth: Literal['narrow', 'default', 'wide'] = 'default'
    defaultModel: DefaultModel | None = None
    hiddenModels: list[StrictStr] = Field(default_factory=list, max_length=512)


class UiInput(Strict):
    version: int = Field(ge=0, strict=True)
    values: UiValues


def attach_operator_config(app, c):
    @app.get('/api/health')
    async def ui_health():
        return {'ok': True, 'engine': 'native', 'features': {'ui.preferences': 1}}

    def preferences():
        path = c.settings.data_dir / 'ui-preferences.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 0, 'values': {}}

    @app.get('/api/settings/ui')
    async def read_preferences():
        return preferences()

    @app.put('/api/settings/ui')
    async def save_preferences(spec: UiInput):
        current = preferences()
        if current['version'] != spec.version:
            return JSONResponse(current, status_code=409)
        value = {'version': spec.version + 1, 'values': spec.values.model_dump(mode='json', exclude_unset=True)}
        atomic_json(c.settings.data_dir, 'ui-preferences.json', value)
        return value

    @app.post('/api/configuration')
    async def save_configuration(spec: ConfigurationInput):
        # Hot update: active runs freeze their own worker and coordinator profiles
        # at creation (swarm_workers / run_profiles), so shared settings may change
        # at any time. Credential values apply immediately, enabling key rotation.
        merged = c.settings.model_dump()
        for key in ('profiles', 'roles', 'workers'):
            value = getattr(spec, key)
            if value is not None:
                merged[key] = value
        validated = Settings.model_validate(merged)
        if not validated.profiles or len(validated.profiles) > 32:
            raise ValueError('Configure 1..32 model profiles')
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,47}', key) for key in validated.profiles):
            raise ValueError('Profile names must be short identifiers')
        for role in ('planner', 'analyst', 'solver', 'reviewer', 'distiller'):
            validated.profile(role)
        for key, value in spec.secrets.items():
            if not re.fullmatch(r'PHOENIX_[A-Z0-9_]*KEY', key) or key == 'PHOENIX_WEB_TOKEN':
                raise ValueError('Only Phoenix model credential variables may be changed')
            if len(value) > 16000 or '\n' in value or '\r' in value:
                raise ValueError('Invalid model credential')
        folder = c.settings.data_dir
        saved = {key: validated.model_dump(mode='json')[key] for key in ('profiles', 'roles', 'workers')}

        if spec.secrets:
            credentials = folder / 'model-credentials.json'
            values = json.loads(credentials.read_text(encoding='utf-8')) if credentials.exists() else {}
            values.update(spec.secrets)
            atomic_json(folder, 'model-credentials.json', values)
            os.environ.update(spec.secrets)
        atomic_json(folder, 'operator-config.json', saved)
        for key in ('profiles', 'roles', 'workers'):
            setattr(c.settings, key, getattr(validated, key))
        c.store.audit('configuration.updated', {'fields': [k for k in ('profiles', 'roles', 'workers')
            if getattr(spec, k) is not None], 'credential_variables': list(spec.secrets)})
        return c.settings.public()
