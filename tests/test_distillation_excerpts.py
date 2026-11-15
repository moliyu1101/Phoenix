import json

import pytest

from phoenix.domain import Completion, Distillation


class ExcerptGateway:
    def __init__(self, select):
        self.select = select

    async def complete(self, rid, role, messages, tools=None, *, profile_override=None, worker_id=None, task_id=None):
        prompt = json.loads(messages[-1]['content'])
        choice = prompt['observations'][0]['excerpts'][0]
        value = {'title': 'Preserve structured output', 'category': 'misc', 'kind': 'observation',
                 'applicability': 'When inspecting a structured tool output',
                 'steps': ['Inspect original text and preserve escaped characters'],
                 'citation_ids': [self.select(choice['citation_id'])]}
        return Completion(text=json.dumps({'lessons': [value]}))


async def test_distiller_selects_exact_escaped_original(components, run, task):
    content = json.dumps({'text': 'line one\nline two "quoted" 中文 flag{private}'}, ensure_ascii=False)
    row = components.evidence.record(run['id'], task['id'], 'file_read', {}, content)
    ids = await components.memory.distill(run['id'], ExcerptGateway(lambda key: key))
    assert len(ids) == 1
    sources = components.store.all('SELECT * FROM memory_sources WHERE memory_id=?', (ids[0],))
    quote = json.loads(sources[0]['citations'])[0]
    assert quote == {'evidence_id': row['id'], 'quote': content}
    assert components.memory.describe(ids[0])['state'] == 'draft'
    components.memory.review(ids[0], True)  # Rechecks the unchanged source hash.


async def test_distiller_cannot_invent_or_cross_scope_excerpt(components, run, task):
    components.evidence.record(run['id'], task['id'], 'file_read', {}, 'original immutable text')
    assert await components.memory.distill(run['id'], ExcerptGateway(lambda _: 'ev_other:0:invented')) == []
    assert not components.store.all('SELECT * FROM memories')
    assert 'Unknown immutable excerpt' in components.store.all("SELECT payload FROM events WHERE kind='memory.rejected'")[0]['payload']


async def test_tampering_still_rejected_before_distiller(components, run, task):
    row = components.evidence.record(run['id'], task['id'], 'file_read', {}, 'original immutable text')
    components.store.execute('UPDATE evidence SET content=? WHERE id=?', ('tampered', row['id']))
    with pytest.raises(ValueError, match='integrity'):
        await components.memory.distill(run['id'], ExcerptGateway(lambda key: key))


def test_legacy_exact_quote_schema_remains_supported():
    value = {'title': 'Original citation', 'category': 'misc', 'kind': 'observation',
             'applicability': 'When inspecting original files', 'steps': ['Inspect the original'],
             'citations': [{'evidence_id': 'ev_test', 'quote': 'original'}]}
    assert Distillation.model_validate({'lessons': [value]}).lessons[0].citations[0].quote == 'original'
