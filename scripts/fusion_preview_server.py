"""Isolated native API with real containers and local external-service fixtures.

No real model credentials are loaded. External-service fixtures are not a claim
of live CTFd/ScopeSentry account acceptance. The browser uses real HTTP traffic.
"""
import asyncio
import base64
import json
import os
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from phoenix.api import create_app
from phoenix.config import ModelProfile, Settings
from phoenix.domain import ChallengeInput, RunInput, Lesson, Quote
from phoenix.service import Components
from phoenix.swarm_demo import create_swarm_demo


async def prepare():
    root=Path(os.environ['PHOENIX_FUSION_DATA']).resolve()
    port=int(os.environ.get('PHOENIX_FUSION_PORT','18860'))
    os.environ['PHOENIX_WEB_TOKEN']='phoenix-local-browser-fixture-token-2026'
    settings=Settings(data_dir=root,port=port,profiles={'default':ModelProfile(model='SCRIPTED-fusion-fixture')})
    c=Components(settings)
    demo=await create_swarm_demo(c)
    # Native evidence-backed records for UI acceptance; no paid model is invoked.
    evidence=c.store.all("SELECT * FROM evidence WHERE run_id=? AND ok=1 AND origin IN ('tool','target','sandbox') ORDER BY created",(demo['id'],))[0]
    lesson=Lesson(title='脚本化验证：先识别附件编码，再交叉复核', category='misc',kind='observation',
        applicability='题目附件存在编码线索时，结合文件特征和工具输出进行独立复核。',
        steps=['读取附件元数据，记录编码与文件类型。','独立解码并回读原始证据，保留可核验的引用。'],
        pitfalls=['仅凭模型总结无法替代原始工具输出。'],
        citations=[Quote(evidence_id=evidence['id'],quote=evidence['content'][:400])])
    memory_id=c.memory.propose(demo['id'],lesson)
    c.memory.review(memory_id,True)
    strategy=c.evolution.from_memory(memory_id,'fixture-evidence-review')
    c.knowledge.ingest('脚本化验证：证据复核工作流','先读取原始工具输出，再确认摘要与引用一致。\n\n保留工具、时间、来源和完整性摘要，避免只记录结论。','misc','isolated-ui-fixture',trusted=False)
    challenge=c.store.create_challenge(ChallengeInput(title='Fusion UI / isolated runtime fixture',
        category='misc',description='Controlled local fixture for sandbox, browser, assets and approvals. No paid model job.',
        targets=[f'http://127.0.0.1:{port}'],authorized=True))
    inputs=root/'inputs'/challenge['id'];inputs.mkdir(parents=True,exist_ok=True)
    (inputs/'fixture.txt').write_text('Phoenix persistent sandbox fixture\n',encoding='utf-8')
    run=c.store.create_run(challenge['id'],RunInput(auto_distill=False),mode='demo')
    c.runtime.swarm.ensure(run['id']);c.store.state(run['id'],'paused','UI-only fixture; no model job launched')
    metadata={'demo_run_id':demo['id'],'paused_run_id':run['id'],'fusion_run_id':run['id'],
        'fixture_target':f'http://127.0.0.1:{port}/fixture',
        'platform_endpoint':f'http://127.0.0.1:{port}/platform',
        'scopesentry_endpoint':f'http://127.0.0.1:{port}/scope/mcp','scripted':True,
        'memory_id':memory_id,'strategy_id':strategy['id']}
    for key,state in [('ui_active','created'),('ui_finished','exhausted'),('ui_paused','paused')]:
        fixture=c.store.create_run(challenge['id'],RunInput(auto_distill=False),mode='demo')
        c.store.state(fixture['id'],state,'UI-only fixture; no model job launched');metadata[key+'_run_id']=fixture['id']
    (root/'preview.json').write_text(json.dumps(metadata),encoding='utf-8')
    app=create_app(settings,c)

    @app.get('/fixture')
    async def fixture():
        return HTMLResponse('''<!doctype html><title>Phoenix browser fixture</title><h1>Native browser fixture</h1>
        <form method="POST" action="/fixture/echo"><label>Name <input name="name" id="name"></label><button id="submit">Send</button></form>
        <a href="/fixture/next">Next page</a><script>document.body.dataset.ready="yes"</script>''')

    @app.post('/fixture/echo')
    async def echo(request:Request):
        value=(await request.body()).decode()
        return HTMLResponse('<title>Browser form received</title><h1>Form received</h1><pre>'+value.replace('<','&lt;')+'</pre>')

    @app.get('/fixture/next')
    async def next_page():
        return HTMLResponse('<title>Second fixture page</title><h1>Second fixture page</h1>')

    @app.get('/platform/api/v1/challenges')
    async def challenges():
        return {'success':True,'data':[{'id':7,'name':'Local platform fixture','category':'misc'}]}

    @app.get('/platform/api/v1/challenges/7')
    async def detail():
        return {'success':True,'data':{'id':7,'name':'Local platform fixture','category':'misc',
            'description':'Local HTTP fixture, not a live competition account.',
            'files':['/platform/files/payload.txt?token=fixture-signature']}}

    @app.get('/platform/api/v1/configs')
    async def configs():
        return {'success':True,'data':[]}

    @app.get('/platform/files/payload.txt')
    async def attachment():
        return HTMLResponse('fixture attachment bytes')

    @app.post('/platform/api/v1/challenges/attempt')
    async def attempt():
        return {'success':True,'data':{'status':'correct','message':'Local fixture accepted'}}

    @app.post('/scope/mcp')
    async def scope(request:Request):
        value=await request.json()
        if value['method']=='initialize':
            return JSONResponse({'jsonrpc':'2.0','id':value['id'],'result':{'protocolVersion':'2025-03-26','capabilities':{'tools':{}},'serverInfo':{'name':'Local ScopeSentry contract fixture','version':'1'}}},headers={'Mcp-Session-Id':'fusion-fixture'})
        if value['method']=='notifications/initialized':
            return JSONResponse({},status_code=202)
        tool=value['params']['name']
        if tool=='list_projects_data':result={'result':{'All':[{'id':'project-1','name':'Local fixture project'}]}}
        elif tool=='list_tasks':result={'list':[{'id':'task-1','name':'Local fixture task'}]}
        else:
            kind=value['params']['arguments']['asset_type']
            result={'list':[{'host':'fixture.test','ip':['192.0.2.1'],'type':'A'}] if kind=='subdomain' else []}
        return {'jsonrpc':'2.0','id':value['id'],'result':{'content':[{'type':'text','text':json.dumps(result)}]}}

    print(json.dumps(metadata),flush=True)
    await uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning')).serve()


if __name__=='__main__':asyncio.run(prepare())
