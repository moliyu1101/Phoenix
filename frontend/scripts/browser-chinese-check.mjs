import {chromium,expect as baseExpect} from '@playwright/test';
const expect=baseExpect.configure({timeout:20000});
import fs from 'node:fs';import path from 'node:path';
const meta=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),out=path.resolve(process.argv[3]),base=process.argv[4]||'http://127.0.0.1:3012';
fs.mkdirSync(out,{recursive:true});
const token=process.argv[5]?/^PHOENIX_WEB_TOKEN=(.+)$/m.exec(fs.readFileSync(process.argv[5],'utf8'))[1].trim():'phoenix-local-browser-fixture-token-2026';
const local=!process.argv[5],browser=await chromium.launch({channel:'msedge',headless:true}),ctx=await browser.newContext({locale:'en-US',viewport:{width:1580,height:1000}});
await ctx.addInitScript(token=>{sessionStorage.setItem('phoenix.workbench.token',token);if(!sessionStorage.getItem('phoenix.zh-migration-tested')){localStorage.setItem('phoenix.lang','en');sessionStorage.setItem('phoenix.zh-migration-tested','1');}localStorage.setItem('phoenix.themePreference','light');},token);
const page=await ctx.newPage(),errors=[],failed=[],checks=[];let expectedScopeError=false;
page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().startsWith(base)&&r.status()>=400&&!(expectedScopeError&&r.status()===400&&r.url().endsWith('/browser')))failed.push({path:new URL(r.url()).pathname,status:r.status()});});
const screenshot=name=>page.screenshot({path:path.join(out,name)});
async function panel(group,name){await page.getByRole('button',{name:group,exact:true}).click();await page.getByRole('navigation',{name:'运行时面板'}).getByRole('button',{name:name==='智能体详情'?/^智能体详情/:name,exact:name!=='智能体详情'}).click();}
try{
 await page.goto(base+'/ctf');await expect(page.getByRole('heading',{name:'开始解题',exact:true})).toBeVisible();await expect(page.locator('html')).toHaveAttribute('lang','zh-CN');await expect(page.locator('.suggest-card').first()).toContainText('网站安全');await expect(page.getByRole('checkbox')).toHaveCount(0);await screenshot('Phoenix-zh-01-start.png');checks.push('old English preference migrates to Chinese without restoring an authorization checkbox');
 for(const [route,title] of [['/competition','比赛平台'],['/settings/integrations','外部集成'],['/swarm','蜂群编队'],['/settings','设置与用量'],['/knowledge','知识库'],['/memory','记忆蒸馏'],['/evolution','策略进化'],['/settings/appearance','外观'],['/settings/shortcuts','快捷键']]){
  await page.goto(base+route);await expect(page.getByRole('heading',{name:title,exact:true}).first()).toBeVisible();await expect(page.locator('html')).toHaveAttribute('lang','zh-CN');
  const text=(await page.locator('button,label,th,option,h1,h2,h3').allTextContents()).join('\n');expect(text).not.toMatch(/\b(?:Worker|WORKER|Fact|Step|Goal|Planner|Distiller|MODEL CONNECTION|Benchmark Suite|API Key)\b/);
  if(route==='/settings') {await expect(page.getByLabel('接口密钥',{exact:true})).toBeVisible();await page.getByRole('button',{name:'角色路由',exact:true}).click();await expect(page.getByRole('heading',{name:'角色路由',exact:true})).toBeVisible();await screenshot('Phoenix-zh-02-settings.png');}
  if(route==='/swarm') {await expect(page.getByLabel('智能体执行引擎')).toBeVisible();const options=await page.getByLabel('智能体执行引擎').locator('option').evaluateAll(items=>items.map(e=>({text:e.textContent,value:e.value})));expect(options.find(x=>x.value==='api').text).toBe('原生接口');await screenshot('Phoenix-zh-03-swarm.png');}
  if(route==='/memory'||route==='/knowledge'||route==='/evolution')await screenshot(`Phoenix-zh-${route.slice(1)}.png`);
 }
 checks.push('all nine navigation/settings/library routes expose Chinese controls and labels');
 const rid=local?meta.fusion_run_id:meta.demo_run_id;
 await page.goto(`${base}/run/${rid}`);await expect(page.getByRole('tab',{name:'对话',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:/^事实:/}).first()).toBeVisible();await screenshot('Phoenix-zh-04-conversation.png');
 await page.getByRole('tab',{name:'运行时',exact:true}).click();await expect(page.locator('.rt-console')).toBeVisible();expect(await page.locator('.rt-console').innerText()).not.toMatch(/\b(?:Worker|Token|Planner|Fact)\b/);await screenshot('Phoenix-zh-05-timeline.png');
 await panel('轨迹','智能体详情');await expect(page.locator('.px-native-worker').first()).toBeVisible();const text=await page.locator('.px-runtime-content').innerText();expect(text).not.toMatch(/\b(?:done|failed|calls|tokens|Worker)\b(?!(?:-|_))/);await screenshot('Phoenix-zh-06-workers.png');
 if(local){
  await page.getByRole('button',{name:'添加智能体',exact:true}).click();await page.locator('.px-native-form').getByLabel('名称',{exact:true}).fill('中文界面验证专员');await page.locator('.px-native-form').getByLabel('角色',{exact:true}).selectOption('reviewer');const result=page.waitForResponse(r=>r.url().endsWith(`/api/runs/${rid}/swarm/workers`)&&r.request().method()==='POST');await page.getByRole('button',{name:'加入编队',exact:true}).click();expect((await result).ok()).toBe(true);const native=await ctx.request.get(`${base}/api/runs/${rid}/swarm`,{headers:{Authorization:'Bearer '+token}}),data=await native.json();expect(data.workers.find(w=>w.name==='中文界面验证专员').roles).toEqual(['reviewer']);checks.push('Chinese reviewer label still submits native reviewer identifier');
  await panel('调查','浏览器');expectedScopeError=true;await page.getByLabel('浏览器地址').fill('https://outside.invalid/');const denied=page.waitForResponse(r=>r.url().endsWith('/browser')&&r.status()===400);await page.getByRole('button',{name:'访问',exact:true}).click();await denied;await expect(page.getByRole('region',{name:'题目浏览器'}).getByRole('alert')).toContainText('此地址不在本题的目标范围内');await screenshot('Phoenix-zh-07-error.png');expectedScopeError=false;checks.push('real native scope rejection is displayed in Chinese without changing the target guard');
 }
 await page.getByRole('tab',{name:'协作图',exact:true}).click();await expect(page.locator('.react-flow__node').first()).toBeVisible();await screenshot('Phoenix-zh-08-graph.png');checks.push('conversation, waterfall, worker details and collaboration graph use Chinese labels');
 const manifest=await (await ctx.request.get(base+'/manifest.json')).json();expect(manifest.name).toContain('工作台');expect(manifest.shortcuts.every(x=>/[\u3400-\u9fff]/.test(x.description))).toBe(true);checks.push('installed app metadata and shortcuts are Chinese');
 expect(errors).toEqual([]);expect(failed).toEqual([]);fs.writeFileSync(path.join(out,'chinese-browser-results.json'),JSON.stringify({checks,errors,failed,local,expected_native_400:local},null,2));console.log(JSON.stringify({passed:checks.length,errors,failed},null,2));
}finally{await browser.close();}
