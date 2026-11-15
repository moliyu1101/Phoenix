/** Real DOM/focus regressions, with exit animations enabled and native API fixtures. */
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const meta=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),output=path.resolve(process.argv[3]),base=process.argv[4]||'http://127.0.0.1:3012';
const local=!process.argv[5],token=local?'phoenix-local-browser-fixture-token-2026':/^PHOENIX_WEB_TOKEN=(.+)$/m.exec(fs.readFileSync(process.argv[5],'utf8'))?.[1]?.trim();
fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const ctx=await browser.newContext({viewport:{width:1580,height:1000},reducedMotion:'no-preference'});
await ctx.addInitScript(key=>{sessionStorage.setItem('phoenix.workbench.token',key);localStorage.setItem('phoenix.motion','system');},token);
const page=await ctx.newPage(),cdp=await ctx.newCDPSession(page),warnings=[],errors=[],failed=[],checks=[];
await cdp.send('Log.enable');
const targeted=/Blocked aria-hidden|Password field is not contained in a form/i;
cdp.on('Log.entryAdded',({entry})=>{if(targeted.test(entry.text))warnings.push(entry.text);});
page.on('console',m=>{if(targeted.test(m.text()))warnings.push(m.text());});
page.on('pageerror',e=>errors.push(e.message));
page.on('response',r=>{if(r.url().startsWith(base)&&r.status()>=400)failed.push({path:new URL(r.url()).pathname,status:r.status()});});
let saves=0,deletes=0;
page.on('request',r=>{if(r.method()==='POST'&&new URL(r.url()).pathname==='/api/configuration')saves++;if(r.method()==='DELETE')deletes++;});
async function native(url,body){const response=await ctx.request.fetch(base+url,{method:body===undefined?'GET':'POST',headers:{Authorization:'Bearer '+token},...(body===undefined?{}:{data:body})});expect(response.status()).toBe(200);return response.json();}
try{
 await page.goto(base+'/settings');await expect(page.getByLabel('接口密钥',{exact:true})).toBeVisible({timeout:20000});
 expect(await page.getByLabel('接口密钥',{exact:true}).evaluate(el=>el.form!==null&&el.closest('form')===el.form)).toBe(true);
 expect(await page.getByRole('button',{name:'保存配置',exact:true}).evaluate(el=>el.type==='submit'&&el.form?.contains(document.querySelector('input[type=password]')))).toBe(true);
 if(local){
  const profile='ui-regression-'+Date.now().toString(36);await page.getByLabel('新模型配置名称').fill(profile);await page.getByLabel('新模型配置名称').press('Enter');await expect(page.locator('.wset-inspector-head strong')).toHaveText(profile);expect(saves).toBe(0);
  await page.locator('.px-admin-record').filter({hasText:'默认配置'}).click();expect(saves).toBe(0);
  await page.getByLabel('接口密钥',{exact:true}).fill('fixture-only-not-a-provider-credential');await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByRole('status')).toContainText('配置已保存');expect(saves).toBe(1);
  await expect(page.getByLabel('接口密钥',{exact:true})).toHaveValue('');await expect(page.getByLabel('接口密钥',{exact:true})).toHaveAttribute('placeholder','已配置，留空保持不变');
 }else expect(saves).toBe(0);
 await page.screenshot({path:path.join(output,'Phoenix-ui-01-configuration-form.png')});checks.push('API key belongs to the real configuration form; explicit submit preserves blank keys');
 await page.goto(base+'/ctf');await expect(page.getByRole('heading',{name:'开始解题',exact:true})).toBeVisible();await page.getByRole('button',{name:'展开题目侧栏',exact:true}).click();
 const list=await native('/api/workbench/runs');
 const rowFor=id=>{expect(list.find(r=>r.run_id===id)).toBeTruthy();return page.locator(`.thread-item[data-run-id="${id}"]`);};
 const active=rowFor(meta.ui_active_run_id),finished=rowFor(meta.ui_finished_run_id),paused=rowFor(meta.ui_paused_run_id);
 async function open(row){await row.hover();const trigger=row.getByRole('button',{name:'更多操作',exact:true});await trigger.click();const menu=page.locator('.menu:not([inert])').last();await expect(menu).toBeVisible();return {trigger,menu};}
 let m=await open(active);await expect(m.menu.getByRole('button',{name:'暂停后可移除',exact:true})).toBeDisabled();expect(deletes).toBe(0);await page.keyboard.press('Escape');await expect(m.trigger).toBeFocused();
 checks.push('active fixture cannot send an invalid removal request');
 m=await open(finished);await expect(m.menu.getByRole('button',{name:'重命名',exact:true})).toBeFocused();await page.keyboard.press('Escape');await expect(m.trigger).toBeFocused();
 m=await open(finished);await page.getByRole('heading',{name:'开始解题',exact:true}).click();expect(await page.evaluate(()=>!document.activeElement.closest('[inert],[aria-hidden="true"]'))).toBe(true);
 m=await open(finished);const cancelled=page.waitForEvent('dialog');page.once('dialog',d=>d.dismiss());await m.menu.getByRole('button',{name:'从侧栏移除',exact:true}).click();await cancelled;await expect(m.trigger).toBeFocused();expect(deletes).toBe(0);
 checks.push('Escape and cancelled confirmation restore focus; outside clicks leave no focus inside hidden menus');
 for(const row of [finished,paused]){
  m=await open(row);await expect(m.menu.getByRole('button',{name:'从侧栏移除',exact:true})).toBeEnabled();page.once('dialog',d=>d.accept());await m.menu.getByRole('button',{name:'从侧栏移除',exact:true}).click();await expect(row).toHaveCount(0);
 }
 expect(deletes).toBe(2);await native('/api/runs/'+meta.ui_finished_run_id);await native('/api/runs/'+meta.ui_paused_run_id);
 checks.push('finished and paused fixtures can be removed while original run records remain readable');
 // Folder menus use the same focus path, including a focused danger action.
 const folderName='UI menu focus '+Date.now();await native('/api/workbench/folders',{name:folderName});await page.reload();await expect(page.getByRole('heading',{name:'开始解题',exact:true})).toBeVisible();await page.getByRole('button',{name:'展开题目侧栏',exact:true}).click();
 const folder=page.locator('.rail-folder-head').filter({hasText:folderName});await expect(folder).toBeVisible();await folder.getByRole('button',{name:'更多操作',exact:true}).click();
 const folderMenu=page.locator('.menu:not([inert])').last();await folderMenu.getByRole('button',{name:'删除文件夹',exact:true}).focus();await page.keyboard.press('Escape');await expect(folder.getByRole('button',{name:'更多操作',exact:true})).toBeFocused();
 await folder.getByRole('button',{name:'更多操作',exact:true}).click();await page.locator('.menu:not([inert])').last().getByRole('button',{name:'删除文件夹',exact:true}).click();await expect(folder).toHaveCount(0);
 checks.push('folder menu danger-item focus is restored during animated close');
 await page.screenshot({path:path.join(output,'Phoenix-ui-02-sidebar-actions.png')});
 expect(warnings).toEqual([]);expect(errors).toEqual([]);expect(failed).toEqual([]);
 fs.writeFileSync(path.join(output,'ui-warnings-results.json'),JSON.stringify({checks,warnings,errors,failed,base,saves,deletes},null,2));console.log(JSON.stringify({passed:checks.length,warnings,errors,failed},null,2));
}finally{await browser.close();}
