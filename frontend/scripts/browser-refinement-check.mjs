/** Native workspace, navigation and typography acceptance. Paid controls are not invoked. */
import {chromium,expect as baseExpect} from '@playwright/test';
import fs from 'node:fs';import path from 'node:path';
const expect=baseExpect.configure({timeout:20000});
const meta=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),out=path.resolve(process.argv[3]),base=process.argv[4]||'http://127.0.0.1:3012';
const local=!process.argv[5],token=local?'phoenix-local-browser-fixture-token-2026':/^PHOENIX_WEB_TOKEN=(.+)$/m.exec(fs.readFileSync(process.argv[5],'utf8'))[1].trim();
fs.mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true}),ctx=await browser.newContext({viewport:{width:1580,height:1000}});
await ctx.addInitScript(key=>{sessionStorage.setItem('phoenix.workbench.token',key);localStorage.setItem('phoenix.themePreference','light');localStorage.setItem('phoenix.motion','reduce');},token);
const page=await ctx.newPage(),errors=[],failed=[],checks=[],metrics=[];
page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.url().startsWith(base)&&r.status()>=400)failed.push({path:new URL(r.url()).pathname,status:r.status()});});
const native=async(route)=>{const r=await ctx.request.get(base+route,{headers:{Authorization:'Bearer '+token}});expect(r.ok()).toBe(true);return r.json();};
const go=async(route,title)=>{await page.goto(base+route);await expect(page.getByRole('heading',{name:title,exact:true})).toBeVisible();};
const shot=name=>page.screenshot({path:path.join(out,name+'.png')});
try{
 await go('/settings/appearance','外观');await page.getByRole('radio',{name:'亮色',exact:true}).click();
 for(const [route,title] of [['/knowledge','知识库'],['/memory','记忆蒸馏'],['/evolution','策略进化'],['/swarm','蜂群编队'],['/competition','比赛平台'],['/settings','设置与用量'],['/settings/integrations','外部集成'],['/settings/appearance','外观'],['/settings/shortcuts','快捷键']]){
  await go(route,title);await expect(page.getByRole('navigation',{name:'模式选择',exact:true})).toBeVisible();
  if(route.startsWith('/settings')){const nav=page.getByRole('navigation',{name:'设置导航',exact:true});await expect(nav).toBeVisible();await expect(nav.getByRole('link')).toHaveCount(4);expect(await nav.innerText()).not.toMatch(/知识库|记忆蒸馏|策略进化|比赛平台|蜂群编队/);}
  else await expect(page.getByRole('navigation',{name:'设置导航',exact:true})).toHaveCount(0);
  if(route==='/swarm')await expect(page.getByLabel('智能体执行引擎')).toBeVisible();
  if(route==='/settings')await expect(page.getByLabel('接口密钥',{exact:true})).toBeVisible();
  await shot(route.slice(1).replaceAll('/','-'));
 }
 checks.push('nine routes; primary mode rail retained; secondary settings navigation contains only four settings entries');
 await go('/knowledge','知识库');
 if(local){
  await page.getByRole('button',{name:'导入文档',exact:true}).click();const dialog=page.getByRole('dialog',{name:'导入知识文档'});
  const title='界面验收文档 '+Date.now(),body='界面验收标记：先读取原始证据，再交叉复核。保留来源和完整性摘要。 '+Date.now();
  await dialog.getByLabel('文档标题',{exact:true}).fill(title);await dialog.getByLabel('文档正文',{exact:true}).fill(body);await dialog.getByRole('button',{name:'保存文档',exact:true}).click();await expect(dialog).not.toBeVisible();
  const docs=await native('/api/knowledge');expect(docs.some(x=>x.title===title)).toBe(true);
  await expect(page.getByText(body,{exact:true})).toBeVisible();await shot('knowledge-detail');
  await page.getByRole('button',{name:'审核通过',exact:true}).click();const reviewed=await native('/api/knowledge');expect(reviewed.find(x=>x.title===title).trust).toBe('trusted');
  checks.push('document import, master/detail body and review persisted through native knowledge API');
 }
 await go('/memory','记忆蒸馏');
 const memories=await native('/api/memories');
 if(memories.length){await page.locator('.px-catalog-table tbody tr').first().click();await expect(page.locator('.px-workspace-detail')).toBeVisible();await shot('memory-detail');
  await page.getByRole('button',{name:/^来源证据/}).click();await page.getByRole('button',{name:/原始证据/}).first().click();await expect(page.getByRole('dialog')).toBeVisible();await shot('memory-evidence');await page.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click();
  if(local){await page.getByRole('button',{name:'生成候选策略',exact:true}).click();const dialog=page.getByRole('dialog',{name:'生成候选策略'}),key='ui-review-'+Date.now();await dialog.getByLabel('策略标识').fill(key);await dialog.getByRole('button',{name:'生成候选策略',exact:true}).click();await expect(dialog).not.toBeVisible();const skills=await native('/api/skills');expect(skills.some(x=>x.key===key&&x.state==='candidate')).toBe(true);}
 }
 checks.push('native memory catalog and detail rendering');
 await go('/evolution','策略进化');await page.locator('.px-catalog-table tbody tr').first().click();await expect(page.locator('.px-workspace-detail')).toBeVisible();await shot('evolution-detail');
 checks.push('native strategy catalog, instructions and version detail');
 await go('/settings','设置与用量');await page.getByRole('button',{name:'角色路由',exact:true}).click();await shot('settings-roles');await page.getByRole('button',{name:'调用用量',exact:true}).click();await shot('settings-usage');
 checks.push('model configuration tabs, role routing and native usage');
 // Changing the same preference store used by Appearance verifies cross-route reactive scaling.
 for(const size of [14,15]){
  await page.evaluate(size=>{const key='phoenix.chatPrefs.v1',prev=JSON.parse(localStorage.getItem(key)||'{}');localStorage.setItem(key,JSON.stringify({...prev,uiFontSize:size}));window.dispatchEvent(new StorageEvent('storage',{key}));},size);
  for(const [route,title] of [['/knowledge','知识库'],['/swarm','蜂群编队'],['/settings','设置与用量']]){
   await go(route,title);metrics.push(await page.getByRole('heading',{name:title,exact:true}).evaluate((el,{route,size})=>({route,size,font:getComputedStyle(el).fontSize,family:getComputedStyle(el).fontFamily}),{route,size}));
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
 }
 for(const route of ['/knowledge','/swarm','/settings']){const a=metrics.find(x=>x.route===route&&x.size===14),b=metrics.find(x=>x.route===route&&x.size===15);expect(parseFloat(b.font)/parseFloat(a.font)).toBeCloseTo(15/14,2);expect(a.family).not.toMatch(/Times New Roman/);}
 checks.push('global font family resolves correctly and headings scale proportionally on three routes');
 await page.evaluate(()=>{const key='phoenix.chatPrefs.v1',prev=JSON.parse(localStorage.getItem(key)||'{}');localStorage.setItem(key,JSON.stringify({...prev,uiFontSize:14}));window.dispatchEvent(new StorageEvent('storage',{key}));});
 await go('/settings/appearance','外观');await page.getByRole('radio',{name:'暗色',exact:true}).click();await go('/knowledge','知识库');await expect(page.locator('html')).toHaveAttribute('data-theme','dark');await shot('knowledge-dark');
 await go('/settings/appearance','外观');await page.getByRole('radio',{name:'亮色',exact:true}).click();
 await page.setViewportSize({width:760,height:1000});await go('/knowledge','知识库');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await shot('knowledge-narrow');
 checks.push('dark theme and narrow viewport without document overflow');
 expect(errors).toEqual([]);expect(failed).toEqual([]);
 fs.writeFileSync(path.join(out,'refinement-results.json'),JSON.stringify({ok:true,checks,metrics,errors,failed},null,2));console.log(JSON.stringify({ok:true,checks,metrics}));
}catch(e){await shot('FAILURE');fs.writeFileSync(path.join(out,'refinement-failure.json'),JSON.stringify({error:String(e),checks,metrics,errors,failed},null,2));throw e;}finally{await browser.close();}
