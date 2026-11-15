import asyncio
import json
import tempfile
from pathlib import Path

import httpx
import pytest

from phoenix.domain import Completion, RunInput, ScopeViolation, dump
from phoenix.filesystem import SecureFiles


def scope(c, run):
    c.store.execute('UPDATE challenges SET targets=? WHERE id=?', (dump(['http://ctf.test:80']), run['challenge_id']))


async def test_recorded_http_drives_assets_and_preserves_evidence(components, run, task):
    c=components;scope(c,run)
    c.tools.transport=httpx.MockTransport(lambda r:httpx.Response(200,text='tool response',headers={'Set-Cookie':'private-session'}))
    result=await c.tools.call(run['id'],task['id'],'http_request',{'url':'http://ctf.test/path'})
    assert result['ok']
    traffic=c.investigation.traffic(run['id'])
    assert len(traffic)==1 and traffic[0]['evidence_id']==result['evidence_id']
    assert traffic[0]['response']['headers']['set-cookie']=='<redacted>'
    first=c.investigation.inventory(run['id']);second=c.investigation.inventory(run['id'])
    assert first['total']==second['total']==3 and first['tested']==3 and len(first['edges'])==2


def test_mark_asset_coverage_retains_source_metadata(components, run):
    c=components
    before=c.investigation.asset(run['id'], 'domain', 'fixture.test', source='scopesentry',
                                metadata={'project_id': 'project-7'})
    after=c.investigation.asset(run['id'], 'domain', 'fixture.test', tested=True)
    assert after['id']==before['id'] and after['source']=='scopesentry'
    assert json.loads(after['metadata'])=={'project_id': 'project-7'}
    assert after['tested']==1


async def test_interception_requires_one_immutable_decision(components, run, task):
    c=components;scope(c,run);requests=[]
    c.tools.transport=httpx.MockTransport(lambda r:(requests.append(r) or httpx.Response(200,text='approved')))
    c.investigation.configure('intercept:'+run['id'], True)
    pending=asyncio.create_task(c.tools.call(run['id'],task['id'],'http_request',{'url':'http://ctf.test/first'}))
    for _ in range(30):
        rows=c.store.all('SELECT * FROM request_approvals')
        if rows:break
        await asyncio.sleep(.01)
    assert rows and not requests
    with pytest.raises(ScopeViolation):
        c.investigation.decide(run['id'],rows[0]['id'],True,{'method':'GET','url':'http://outside.test','headers':{},'body':''})
    c.investigation.decide(run['id'],rows[0]['id'],True,{'method':'GET','url':'http://ctf.test/edited','headers':{},'body':''})
    assert (await pending)['ok'] and len(requests)==1 and requests[0].url.path=='/edited'
    with pytest.raises(Exception):c.investigation.decide(run['id'],rows[0]['id'],True)


async def test_interception_rejection_sends_no_request(components, run, task):
    c=components;scope(c,run);requests=[]
    c.tools.transport=httpx.MockTransport(lambda r:(requests.append(r) or httpx.Response(200)))
    c.investigation.configure('intercept:'+run['id'], True)
    pending=asyncio.create_task(c.tools.call(run['id'],task['id'],'http_request',{'url':'http://ctf.test/'}))
    for _ in range(30):
        rows=c.store.all('SELECT * FROM request_approvals')
        if rows:break
        await asyncio.sleep(.01)
    c.investigation.decide(run['id'],rows[0]['id'],False)
    assert not (await pending)['ok'] and not requests


async def test_real_migrated_ctfd_adapter_import_and_single_submission(components):
    c=components;requests=[]
    def server(request):
        requests.append(request)
        assert request.headers.get('authorization')=='Token platform-test-secret'
        path=request.url.path
        if path=='/api/v1/challenges':return httpx.Response(200,json={'success':True,'data':[{'id':7,'name':'Fixture','category':'misc'}]})
        if path=='/api/v1/challenges/7':return httpx.Response(200,json={'success':True,'data':{'id':7,'name':'Fixture','description':'Analyze the attachment','category':'misc','files':['/files/abc/payload.txt?token=short-lived']}})
        if path=='/files/abc/payload.txt':return httpx.Response(200,content=b'fixture bytes')
        if path=='/api/v1/challenges/attempt':return httpx.Response(200,json={'success':True,'data':{'status':'correct','message':'accepted'}})
        return httpx.Response(404)
    c.platforms.transport=httpx.MockTransport(server)
    result=await c.platforms.configure('ctfd','http://platform.test','platform-test-secret')
    cid=result['id'];assert 'platform-test-secret' not in json.dumps(c.platforms.connections())
    assert (await c.platforms.sync(cid))['synced_challenges']==1
    challenge=await c.platforms.import_challenge(cid,'7',[])
    assert SecureFiles(c.store.root/'inputs'/challenge['id']).read('payload.txt')==b'fixture bytes'
    run=c.store.create_run(challenge['id'],RunInput(auto_distill=False),mode='demo')
    evidence=c.evidence.record(run['id'],None,'file_read',{},'flag{from_fixture}')
    candidate=c.evidence.scan_flags(evidence)[0]
    receipt=await c.platforms.submit(cid,candidate,True)
    assert receipt['state']=='correct'
    await c.platforms.submit(cid,candidate,True)
    assert sum(r.url.path.endswith('/attempt') for r in requests)==1
    assert c.store.one('SELECT status FROM candidates WHERE id=?',(candidate,))['status']=='accepted'
    await c.platforms.shutdown()


async def test_scope_sentry_native_mcp_session_and_mapping(components, run):
    c=components;calls=[]
    def server(request):
        assert request.headers['x-api-key']=='scope-test-secret'
        value=json.loads(request.content);calls.append(value)
        if value['method']=='initialize':return httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':{'capabilities':{}}},headers={'Mcp-Session-Id':'fixture-session'})
        assert request.headers['mcp-session-id']=='fixture-session'
        if value['method']=='notifications/initialized':return httpx.Response(202)
        assert value['params']['name']=='list_assets'
        result={'list':[{'host':'ctf.test','ip':['192.0.2.1'],'type':'A'}]}
        return httpx.Response(200,json={'result':{'content':[{'type':'text','text':json.dumps(result)}]}})
    c.scopesentry.transport=httpx.MockTransport(server)
    c.scopesentry.configure('http://scopesentry.test/mcp','scope-test-secret')
    result=await c.scopesentry.sync(run['id'],'project',['project-1'],['subdomain'])
    assert result['counts']=={'subdomain':1} and result['scope_unchanged']
    assert c.store.challenge(run['challenge_id'])['targets']==[]
    assets=c.investigation.inventory(run['id'])['items']
    assert {a['kind'] for a in assets}=={'subdomain','ip'}
    assert 'scope-test-secret' not in json.dumps(c.scopesentry.status())


async def test_agent_gateway_scopes_token_and_native_budget(components, run, task):
    c=components
    class Provider:
        async def complete(self,profile,messages,tools):
            assert profile.model=='fixture-model'
            return Completion(text='gateway result',input_tokens=20,output_tokens=4)
    c.gateway.provider=Provider()
    profile=c.settings.profile('solver').model_copy(update={'model':'fixture-model'})
    with tempfile.TemporaryDirectory(prefix='pxgw-') as folder:
        old=c.store.root;c.store.root=Path(folder)
        try:
            token=await c.engines.gateway.bind(run['id'],task['id'],profile)
            with pytest.raises(PermissionError):await c.engines.gateway.complete('other-run',token,{'messages':[]})
            result=await c.engines.gateway.complete(run['id'],token,{'messages':[{'role':'user','content':'hello'}]})
            assert result['choices'][0]['message']['content']=='gateway result'
            assert c.store.run(run['id'])['calls']==1
            c.engines.gateway.revoke(token)
            with pytest.raises(PermissionError):await c.engines.gateway.complete(run['id'],token,{'messages':[]})
        finally:
            await c.engines.shutdown();c.store.root=old


async def test_engine_catalog_does_not_create_sandbox_on_read(components,run):
    health=await components.engines.health(run['id'])
    assert any(e['id']=='pi-rpc' for e in health)
    assert not components.sandboxes.rows(run['id'])


async def test_migrated_attachment_urls_and_cross_origin_credentials():
    from phoenix.vendor.engine.competition.transports.http import RestTransport
    requests=[]
    def server(request):
        requests.append(request)
        return httpx.Response(200,content=b'attachment')
    client=RestTransport('http://platform.test/base',default_headers={'Authorization':'Token private'},transport=httpx.MockTransport(server))
    try:
        assert await client.download('/base/files/a')==b'attachment'
        assert requests[-1].url.path=='/base/files/a'
        assert requests[-1].headers['authorization']=='Token private'
        await client.download('http://cdn.test/a?signature=short-lived')
        assert 'authorization' not in requests[-1].headers and 'cookie' not in requests[-1].headers
    finally:await client.aclose()


async def test_gzctf_async_receipt_updates_native_candidate(components,run,task):
    from phoenix.domain import uid,now
    from phoenix.vendor.engine.platform.contracts.modules import SubmissionResult
    c=components
    evidence=c.evidence.record(run['id'],task['id'],'decode',{},'flag{async_receipt}')
    candidate=c.evidence.scan_flags(evidence)[0]
    c.store.execute('INSERT INTO platform_links VALUES(?,?,?,?,?,?,?)',(uid('link'),'gz-fixture','1/7',run['challenge_id'],'1','{}',now()))
    c.store.execute('INSERT INTO platform_submissions VALUES(?,?,?,?,?,?)',('submission-fixture','gz-fixture',candidate,'pending',dump({'submission_id':'42'}),now()))
    class Adapter:
        async def poll_submission(self,game,challenge,submission):
            assert (game,challenge,submission)==('1','7','42')
            return SubmissionResult(submission_id='42',status='correct')
    c.platforms.adapters['gz-fixture']=Adapter()
    result=await c.platforms.poll_submission('gz-fixture','submission-fixture')
    assert result['state']=='correct'
    assert c.store.one('SELECT status FROM candidates WHERE id=?',(candidate,))['status']=='accepted'
    assert (await c.platforms.poll_submission('gz-fixture','submission-fixture'))['state']=='correct'
