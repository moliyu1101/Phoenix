import asyncio
import base64
import json

import httpx
import pytest

from phoenix.config import ModelProfile
from phoenix.domain import ChallengeInput, RunInput, dump
from phoenix.filesystem import SecureFiles
from phoenix.providers import HTTPProvider, ModelGateway, anthropic_messages
from phoenix.tools import ToolBus


async def test_direct_chat_protocol_and_tool_calls():
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':None,
          'reasoning_content':'provider extension',
          'tool_calls':[{'id':'c1','type':'function','function':{'name':'file_list','arguments':'{}'}}]}}],
          'usage':{'prompt_tokens':100,'completion_tokens':20}})
    p=HTTPProvider(httpx.MockTransport(handler))
    result=await p.complete(ModelProfile(model='test-model'),[{'role':'user','content':'inspect'}],[])
    assert result.calls[0].name=='file_list'
    assert result.assistant['reasoning_content']=='provider extension'
    assert captured[0]['max_completion_tokens']==4096
    assert result.input_tokens==100


async def test_chat_legacy_token_parameter():
    def handler(request):
        data=json.loads(request.content)
        assert 'max_tokens' in data and 'max_completion_tokens' not in data
        return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    await HTTPProvider(httpx.MockTransport(handler)).complete(
        ModelProfile(model='x',chat_token_parameter='max_tokens'),[{'role':'user','content':'x'}],[])


def test_anthropic_groups_parallel_tool_results():
    msgs=[{'role':'system','content':'policy'},
          {'role':'assistant','content':'','tool_calls':[
           {'id':'a','function':{'name':'one','arguments':'{}'}},
           {'id':'b','function':{'name':'two','arguments':'{}'}}]},
          {'role':'tool','tool_call_id':'a','content':'one-result'},
          {'role':'tool','tool_call_id':'b','content':'two-result'}]
    system,result=anthropic_messages(msgs)
    assert system=='policy' and len(result)==2
    assert len(result[1]['content'])==2
    assert result[1]['content'][0]['tool_use_id']=='a'


async def test_anthropic_native_blocks_preserved():
    blocks=[{'type':'thinking','thinking':'provider-signed-content','signature':'signature'},
            {'type':'tool_use','id':'t1','name':'file_list','input':{}}]
    def handler(request):
        assert request.headers['anthropic-version']=='2023-06-01'
        return httpx.Response(200,json={'content':blocks,'usage':{'input_tokens':20,'output_tokens':5}})
    result=await HTTPProvider(httpx.MockTransport(handler)).complete(
        ModelProfile(protocol='anthropic',base_url='https://api.anthropic.com/v1',model='test'),
        [{'role':'system','content':'policy'},{'role':'user','content':'inspect'}],[])
    _,converted=anthropic_messages([result.assistant])
    assert converted[0]['content']==blocks


async def test_provider_error_does_not_echo_secret():
    def handler(request):return httpx.Response(401,text='sk-SECRET_PROVIDER_DEBUG')
    with pytest.raises(RuntimeError) as exc:
        await HTTPProvider(httpx.MockTransport(handler)).complete(ModelProfile(model='x'),[],[])
    assert 'SECRET' not in str(exc.value)


async def test_ambiguous_model_post_not_retried(components,run,task):
    calls=[]
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('simulated ambiguous timeout')
    gateway=ModelGateway(components.store,components.settings,HTTPProvider(httpx.MockTransport(handler)))
    with pytest.raises(httpx.ReadTimeout):
        await gateway.complete(run['id'],'solver',[{'role':'user','content':'x'}])
    assert len(calls)==1
    assert components.store.one('SELECT status FROM model_calls')['status']=='uncertain'
    assert components.store.run(run['id'])['held_tokens']>0


async def test_native_files_and_decode(components,run,task):
    c=components
    result=await c.tools.call(run['id'],task['id'],'file_write',{'path':'test.txt','content':'hello'})
    assert result['ok']
    path=json.loads(result['output'])['path']
    read=await c.tools.call(run['id'],task['id'],'file_read',{'path':path})
    assert json.loads(read['output'])['content']=='hello'
    decode=await c.tools.call(run['id'],task['id'],'decode',{'operation':'base64','data':'aGVsbG8='})
    assert json.loads(decode['output'])['text']=='hello'


@pytest.mark.parametrize('operation,data,key,expected',[
 ('hex','6869',0,'hi'),('rot13','uryyb',0,'hello'),('xor','6968',1,'hi')])
async def test_native_decode_modes(components,run,task,operation,data,key,expected):
    result=await components.tools.call(run['id'],task['id'],'decode',{'operation':operation,'data':data,'xor_key':key})
    assert json.loads(result['output'])['text']==expected


async def test_http_scope_and_redirect_not_followed(components,run,task):
    c=components;requests=[]
    c.store.execute('UPDATE challenges SET targets=? WHERE id=?',(dump(['http://ctf.test:80']),run['challenge_id']))
    def handler(request):
        requests.append(request)
        return httpx.Response(302,headers={'location':'https://outside.test'},text='redirect')
    c.tools.transport=httpx.MockTransport(handler)
    result=await c.tools.call(run['id'],task['id'],'http_request',{'url':'http://ctf.test/'})
    assert result['ok'] and json.loads(result['output'])['status']==302 and len(requests)==1
    forbidden=await c.tools.call(run['id'],task['id'],'http_request',{'url':'http://outside.test/'})
    assert not forbidden['ok'] and len(requests)==1


async def test_http_host_override_denied(components,run,task):
    components.store.execute('UPDATE challenges SET targets=? WHERE id=?',(dump(['http://ctf.test:80']),run['challenge_id']))
    r=await components.tools.call(run['id'],task['id'],'http_request',{'url':'http://ctf.test/', 'headers':{'Host':'outside.test'}})
    assert not r['ok']


async def test_real_loopback_tcp_exchange(components,run,task):
    async def echo(reader,writer):
        data=await reader.read(10);writer.write(b'result:'+data);await writer.drain();writer.close();await writer.wait_closed()
    server=await asyncio.start_server(echo,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    target=f'tcp://127.0.0.1:{port}'
    components.store.execute('UPDATE challenges SET targets=? WHERE id=?',(dump([target]),run['challenge_id']))
    try:
        result=await components.tools.call(run['id'],task['id'],'tcp_exchange',{
            'target':target,'actions':[{'send_base64':base64.b64encode(b'hello').decode(),'read_bytes':30}]})
        assert result['ok'] and json.loads(result['output'])['exchanges'][0]['text']=='result:hello'
    finally:
        server.close();await server.wait_closed()


async def test_no_host_shell_fallback(components,run,task,monkeypatch):
    monkeypatch.setattr('phoenix.sandbox.shutil.which',lambda _:None)
    r=await components.tools.call(run['id'],task['id'],'sandbox_exec',{'command':'echo must-not-run-on-host'})
    assert not r['ok'] and 'not a fallback' in r['output']


def test_docker_hardening_command(components,tmp_path):
    cmd=components.tools.sandbox.command('phoenix-job_example',tmp_path/'in',tmp_path/'work','file /input/a')
    assert '--read-only' in cmd and '--network' in cmd and cmd[cmd.index('--network')+1]=='none'
    assert '--cap-drop' in cmd and '--privileged' not in cmd
    assert not any('docker.sock' in x or 'PHOENIX_API_KEY' in x for x in cmd)


async def test_tool_argument_validation(components,run,task):
    with pytest.raises(ValueError):
        await components.tools.call(run['id'],task['id'],'file_read',{'path':'input:x','extra_injection':'bad'})


async def test_original_evidence_required_for_handoff(components,run,task):
    result=await components.tools.call(run['id'],task['id'],'task_finish',{'summary':'Trust my unsupported claim','evidence_ids':[]})
    assert not result['ok']


def test_mock_http_transport_never_counts_as_live_model(components):
    from phoenix.providers import HTTPProvider, ModelGateway
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={}))
    gateway = ModelGateway(components.store, components.settings, HTTPProvider(transport))
    assert gateway.live is False
    assert ModelGateway(components.store, components.settings).live is True


async def test_candidate_submission_rejects_corrupted_raw_evidence(components, run, task):
    row = components.evidence.record(run['id'], task['id'], 'decode', {}, 'flag{original}')
    components.store.execute('UPDATE evidence SET content=? WHERE id=?', ('flag{altered}', row['id']))
    result = await components.tools.call(run['id'], task['id'], 'candidate_submit',
                                       {'value': 'flag{altered}', 'evidence_id': row['id']})
    assert not result['ok'] and 'integrity' in result['output'].lower()
    assert not components.store.all('SELECT id FROM candidates')
