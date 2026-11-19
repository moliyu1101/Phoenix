import pytest

from phoenix.domain import dump, now, uid


async def test_empty_overview(components):
    view = components.attention.overview()
    assert view['total'] == 0 and view['items'] == []
    assert view['counts'] == {'action': 0, 'review': 0, 'info': 0}
    assert view['effect_health'] == []


async def test_action_items(components, run, task):
    s = components.store
    s.execute('INSERT INTO request_approvals VALUES(?,?,?,?,?,?,?)',
              (uid('ap'), run['id'], task['id'], dump({'method': 'GET', 'url': 'http://target'}), 'pending', now(), now()))
    s.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)',
              (uid('exec'), run['id'], task['id'], 'container', 'uncertain', now()))
    s.state(run['id'], 'interrupted', 'fixture interruption')
    view = components.attention.overview()
    kinds = {i['kind'] for i in view['items']}
    assert {'approval', 'uncertain_execution', 'interrupted_run'} <= kinds
    assert view['counts']['action'] >= 3
    assert all(i['hint'] for i in view['items'])


async def test_awaiting_verification_is_review(components, run):
    components.store.state(run['id'], 'awaiting_verification', 'candidates exist; no acceptance')
    view = components.attention.overview()
    item = next(i for i in view['items'] if i['kind'] == 'awaiting_verification')
    assert item['severity'] == 'review' and item['refs']['run_id'] == run['id']


async def test_dead_letter_effect(components):
    eid = components.effects.enqueue('delivery', 'k', {'run_id': 'run_x', 'entry_id': 'cq_x'})
    components.store.execute("UPDATE effects SET state='dead_letter',last_error='uncertain: lost' WHERE id=?", (eid,))
    view = components.attention.overview()
    item = next(i for i in view['items'] if i['kind'] == 'effect')
    assert item['severity'] == 'action' and item['refs']['effect_id'] == eid
    assert item['refs']['entry_id'] == 'cq_x'
    assert any(h['kind'] == 'delivery' and h['needs_attention'] == 1 for h in view['effect_health'])


def _competition(s, state='failed', submission_state=None):
    cid = uid('comp')
    s.execute('INSERT INTO competitions VALUES(?,?,?,?,?,?,?,?)',
              (cid, 'conn', '', '赛', dump({}), 'paused', now(), now()))
    eid = uid('cq')
    s.execute('INSERT INTO competition_queue(id,competition_id,challenge_key,title,category,state,'
              'submission_state,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
              (eid, cid, '7', '题', 'misc', state, submission_state, now(), now()))
    return cid, eid


async def test_failed_competition_entry(components):
    _, eid = _competition(components.store, state='failed')
    view = components.attention.overview()
    item = next(i for i in view['items'] if i['kind'] == 'competition_entry')
    assert item['severity'] == 'review' and item['refs']['entry_id'] == eid


async def test_unknown_submission(components):
    _, eid = _competition(components.store, state='solved', submission_state='unknown')
    view = components.attention.overview()
    item = next(i for i in view['items'] if i['kind'] == 'submission')
    assert item['severity'] == 'action' and item['refs']['entry_id'] == eid


async def test_sorted_action_first(components, run):
    components.store.state(run['id'], 'awaiting_verification', 'review item')
    eid = components.effects.enqueue('delivery', 'k', {})
    components.store.execute("UPDATE effects SET state='dead_letter' WHERE id=?", (eid,))
    view = components.attention.overview()
    severities = [i['severity'] for i in view['items']]
    assert severities == sorted(severities, key=lambda s: {'action': 0, 'review': 1, 'info': 2}[s])