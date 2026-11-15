from __future__ import annotations

import json
from pathlib import Path

from .domain import SkillSpec
from .evolution import Evolution
from .knowledge import Knowledge


def seed(knowledge: Knowledge, evolution: Evolution):
    path = Path(__file__).with_name('seeds') / 'baseline.json'
    raw = json.loads(path.read_text())
    for item in raw['knowledge']:
        knowledge.ingest(item['title'], item['body'], item['category'], 'phoenix-authored-baseline', trusted=True)
    for item in raw['skills']:
        evolution.install_seed(SkillSpec.model_validate(item))
