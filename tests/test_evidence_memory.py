import json

import pytest

from phoenix.domain import ChallengeInput, Lesson, Quote, RunInput, digest
from phoenix.memory import redact


def observation(c,run,task,content='The input has 12 bytes',**kwargs):
    return c.evidence.record(run['id'],task['id'],'file_inspect',{},content,**kwargs)


def lesson(row,kind='observation'):
    return Lesson(title='Inspect input size',category='misc',kind=kind,
                  applicability='When a binary attachment needs initial triage',steps=['Measure the actual input size'],
                  citations=[Quote(evidence_id=row['id'],quote='12 bytes')])


def test_tampered_evidence_rejected(components,run,task):
    row=observation(components,run,task)
    components.store.execute('UPDATE evidence SET content=? WHERE id=?',('changed',row['id']))
    with pytest.raises(ValueError):components.evidence.read(run['id'],row['id'])


def test_evidence_citation_scope(components,run,task):
    row=observation(components,run,task)
    other=components.store.create_run(run['challenge_id'],RunInput())
    with pytest.raises(Exception):components.evidence.validate_quotes(other['id'],[Quote(evidence_id=row['id'],quote='12 bytes')])


def test_wrong_quote_rejected(components,run,task):
    row=observation(components,run,task)
    with pytest.raises(ValueError):components.evidence.validate_quotes(run['id'],[Quote(evidence_id=row['id'],quote='invented fact')])


@pytest.mark.parametrize('origin',['reference','model'])
def test_reflected_flag_is_not_a_candidate(components,run,task,origin):
    row=observation(components,run,task,'flag{fake}',origin=origin)
    assert components.evidence.scan_flags(row)==[]


def test_literal_echo_not_candidate(components,run,task):
    row=components.evidence.record(run['id'],task['id'],'sandbox_exec',{'command':'echo flag{fake}'},'flag{fake}',origin='sandbox')
    assert components.evidence.scan_flags(row)==[]


def test_candidate_not_automatically_accepted(components,run,task):
    row=observation(components,run,task,'flag{candidate}')
    ids=components.evidence.scan_flags(row)
    assert components.store.one('SELECT status FROM candidates WHERE id=?',(ids[0],))['status']=='unverified'


def test_independent_hash_verifier_rejects_decoy(components,run,task):
    components.store.execute('INSERT INTO verifiers VALUES(?,?)',(run['challenge_id'],digest('flag{real}')))
    row=observation(components,run,task,'flag{fake} and flag{real}')
    components.evidence.scan_flags(row)
    result={r['value']:r['status'] for r in components.store.all('SELECT * FROM candidates')}
    assert result=={'flag{fake}':'rejected','flag{real}':'accepted'}


def test_truncation_is_visible(components,run,task):
    from phoenix.evidence import EvidenceStore
    row=EvidenceStore(components.store,10).record(run['id'],task['id'],'test',{},'x'*20)
    assert row['truncated'] and len(row['content'])==10


def test_distillation_requires_success_for_procedure(components,run,task):
    row=observation(components,run,task)
    with pytest.raises(ValueError,match='accepted'):
        components.memory.propose(run['id'],lesson(row,'procedure'))


def test_draft_not_in_retrieval_then_reviewed(components,run,task):
    row=observation(components,run,task)
    mid=components.memory.propose(run['id'],lesson(row))
    assert components.memory.describe(mid)['state']=='draft'
    assert not components.store.all('SELECT * FROM documents WHERE source=?',('distilled:'+mid,))
    components.memory.review(mid,True)
    assert any(r['source']=='distilled:'+mid for r in components.knowledge.search('actual input size',limit=30))
    components.memory.review(mid,False)
    assert not any(r['source']=='distilled:'+mid for r in components.knowledge.search('actual input size',limit=30))


def test_same_episode_deduplicated(components,run,task):
    row=observation(components,run,task)
    a=components.memory.propose(run['id'],lesson(row));b=components.memory.propose(run['id'],lesson(row))
    assert a==b and components.memory.describe(a)['source_count']==1


def test_heldout_cannot_train(components,run,task):
    components.store.execute("UPDATE runs SET mode='benchmark' WHERE id=?",(run['id'],))
    row=observation(components,run,task)
    with pytest.raises(ValueError,match='Held-out'):components.memory.propose(run['id'],lesson(row))


def test_redacts_answer_credentials_targets():
    value=redact('flag{secret} http://example.com/x 192.168.1.2:80 sk-abcdefghijklmnop password=hunter2')
    for secret in ['flag{secret}','example.com','192.168.1.2','abcdefghijklmnop','hunter2']:
        assert secret not in value


def test_episode_is_trace_not_memory_claim(components,run,task):
    eid=components.memory.consolidate_episode(run['id'])
    assert components.store.one('SELECT id FROM episodes')['id']==eid
    assert components.store.one('SELECT COUNT(*) AS n FROM memories')['n']==0


def test_failed_tool_can_support_scoped_negative(components,run,task):
    row=observation(components,run,task,'Failed: input has 12 bytes',ok=False)
    mid=components.memory.propose(run['id'],lesson(row,'negative'))
    assert components.memory.describe(mid)['kind']=='negative'


def test_citations_rechecked_at_activation(components,run,task):
    row=observation(components,run,task);mid=components.memory.propose(run['id'],lesson(row))
    components.store.execute('UPDATE evidence SET content=? WHERE id=?',('tamper',row['id']))
    with pytest.raises(ValueError):components.memory.review(mid,True)
