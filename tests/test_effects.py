import asyncio

import pytest

from phoenix.domain import Conflict
from phoenix.effects import Defer, Effects, Uncertain


@pytest.fixture
def effects(components):
    # A real backoff window (1s) so the "not due yet" assertion cannot race the
    # wall clock between drains; tests force run_after=0 to advance, never wait.
    return Effects(components.store, base_delay=1.0, max_delay=10.0)


async def test_enqueue_coalesces_active_and_resets_terminal(effects):
    first = effects.enqueue('notify', 'k', {'n': 1})
    again = effects.enqueue('notify', 'k', {'n': 2})
    assert first == again
    assert effects.get(first)['payload'] == {'n': 2}
    assert effects.store.one('SELECT COUNT(*) AS n FROM effects')['n'] == 1

    async def ok(payload):
        return {'seen': payload['n']}

    await effects.drain({'notify': ok})
    assert effects.get(first)['state'] == 'completed'
    # A fresh intent after a terminal effect re-arms the same row rather than duplicating it.
    third = effects.enqueue('notify', 'k', {'n': 3})
    assert third == first
    row = effects.get(first)
    assert row['state'] == 'accepted' and row['attempts'] == 0 and row['payload'] == {'n': 3}


async def test_drain_success_and_scope(effects):
    a = effects.enqueue('launch', 'a', {'v': 'a'})
    b = effects.enqueue('launch', 'b', {'v': 'b'})
    other = effects.enqueue('notify', 'c', {'v': 'c'})
    seen = []

    async def handler(payload):
        seen.append(payload['v'])
        return payload['v']

    results = await effects.drain({'launch': handler}, kinds=['launch'], keys=['a'])
    assert [r['key'] for r in results] == ['a'] and seen == ['a']
    assert effects.get(a)['state'] == 'completed'
    assert effects.get(b)['state'] == 'accepted' and effects.get(other)['state'] == 'accepted'


async def test_backoff_then_dead_letter(effects):
    eid = effects.enqueue('relay', 'k', {}, max_attempts=3)
    calls = []

    async def flaky(payload):
        calls.append(1)
        raise RuntimeError('transient')

    first = await effects.drain({'relay': flaky})
    assert first[0]['state'] == 'waiting' and first[0]['attempts'] == 1
    row = effects.get(eid)
    assert row['run_after'] > row['updated'] - 1 and 'transient' in row['last_error']
    # Not due yet: a immediate second drain does nothing.
    assert await effects.drain({'relay': flaky}) == []
    effects.store.execute('UPDATE effects SET run_after=0 WHERE id=?', (eid,))
    second = await effects.drain({'relay': flaky})
    assert second[0]['attempts'] == 2 and second[0]['state'] == 'waiting'
    effects.store.execute('UPDATE effects SET run_after=0 WHERE id=?', (eid,))
    third = await effects.drain({'relay': flaky})
    assert third[0]['state'] == 'dead_letter' and len(calls) == 3
    assert effects.get(eid)['attempts'] == 3


async def test_defer_does_not_consume_attempt(effects):
    eid = effects.enqueue('relay', 'k', {})

    async def later(payload):
        raise Defer(0.02)

    result = await effects.drain({'relay': later})
    assert result[0]['state'] == 'waiting'
    assert effects.get(eid)['attempts'] == 0


async def test_uncertain_dead_letters_immediately(effects):
    eid = effects.enqueue('delivery', 'k', {})
    calls = []

    async def uncertain(payload):
        calls.append(1)
        raise Uncertain('POST sent, receipt lost')

    result = await effects.drain({'delivery': uncertain})
    assert result[0]['state'] == 'dead_letter' and result[0]['uncertain'] is True
    # Fail closed: no automatic retry of an uncertain effect.
    assert await effects.drain({'delivery': uncertain}) == []
    assert len(calls) == 1


async def test_retry_and_drop_operator_controls(effects):
    eid = effects.enqueue('delivery', 'k', {})

    async def uncertain(payload):
        raise Uncertain('lost')

    await effects.drain({'delivery': uncertain})
    assert effects.get(eid)['state'] == 'dead_letter'
    retried = effects.retry(eid)
    assert retried['state'] == 'accepted' and retried['attempts'] == 0
    with pytest.raises(Conflict):
        effects.retry(eid)
    dropped = effects.drop(eid)
    assert dropped['state'] == 'cancelled'
    with pytest.raises(Conflict):
        effects.drop(eid)


async def test_health_and_recover(effects):
    effects.enqueue('launch', 'a')
    dead = effects.enqueue('delivery', 'b')

    async def uncertain(payload):
        raise Uncertain('lost')

    await effects.drain({'delivery': uncertain})
    running = effects.enqueue('relay', 'c')
    effects.store.execute("UPDATE effects SET state='running' WHERE id=?", (running,))
    effects.recover()
    assert effects.get(running)['state'] == 'dead_letter'
    health = {h['kind']: h for h in effects.health()}
    assert health['delivery']['dead_letter'] == 1 and health['delivery']['needs_attention'] == 1
    assert health['launch']['accepted'] == 1
    assert effects.get(dead)['state'] == 'dead_letter'


async def test_effects_loop_drains_and_stops(components, effects):
    components.effects = effects
    components.effect_handlers = {}
    seen = []

    async def handler(payload):
        seen.append(payload['v'])

    components.effect_handlers['notify'] = handler
    effects.enqueue('notify', 'k', {'v': 1})
    stop = asyncio.Event()
    from phoenix.effects import effects_loop
    task = asyncio.create_task(effects_loop(components, stop, interval=0.02))
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 5)
    assert seen == [1]