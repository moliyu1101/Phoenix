/** Keep real history DOM nodes across polling, typing and journal appends. */
import {chromium, expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const meta = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const output = path.resolve(process.argv[3]);
const base = process.argv[4] || 'http://127.0.0.1:3012';
const local = !process.argv[5];
const token = local ? 'phoenix-local-browser-fixture-token-2026' : /^PHOENIX_WEB_TOKEN=(.+)$/m.exec(fs.readFileSync(process.argv[5], 'utf8'))?.[1]?.trim();
fs.mkdirSync(output, {recursive: true});
const browser = await chromium.launch({channel: 'msedge', headless: true});
const context = await browser.newContext({viewport: {width: 1580, height: 900}, reducedMotion: 'no-preference'});
await context.addInitScript(key => {
  sessionStorage.setItem('phoenix.workbench.token', key);
  localStorage.setItem('phoenix.motion', 'system');
}, token);
const page = await context.newPage(), errors = [], failed = [], checks = [];
page.on('pageerror', e => errors.push(e.message));
page.on('response', r => { if (r.url().startsWith(base) && r.status() >= 400) failed.push({path: new URL(r.url()).pathname, status: r.status()}); });
let polls = 0;
page.on('response', r => { if (new URL(r.url()).pathname.endsWith('/timeline')) polls++; });
async function track() {
  await page.evaluate(() => {
    window.historyProbe?.observer.disconnect();
    const rows = [...document.querySelectorAll('[data-event-seq]')];
    const observer = new MutationObserver(records => {
      for (const record of records) for (const node of record.removedNodes) {
        if (rows.some(row => node === row || node.contains?.(row))) window.historyProbe.removed++;
      }
    });
    window.historyProbe = {rows, observer, removed: 0};
    observer.observe(document.querySelector('.coord-wrap'), {childList: true, subtree: true});
  });
}
async function stability() {
  return page.evaluate(() => ({
    removed: window.historyProbe.removed,
    detached: window.historyProbe.rows.filter(row => !row.isConnected).length,
    retained: window.historyProbe.rows.length,
  }));
}
try {
  await page.goto(`${base}/run/${meta.demo_run_id}`);
  await expect(page.locator('[data-event-seq]').first()).toBeVisible({timeout: 20000});
  await expect(page.locator('.px-original-prompt')).not.toContainText('正在读取题面');
  await page.locator('.px-thread-scroll').evaluate(el => el.scrollTop = 0);
  await track();
  const beforePolls = polls;
  // More than two normal polling cycles, with all original animations enabled.
  await expect.poll(() => polls - beforePolls, {timeout: 18000}).toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(300);
  const polling = await stability();
  fs.writeFileSync(path.join(output, 'conversation-stability.json'), JSON.stringify({polling, errors, failed}, null, 2));
  expect(polling.retained).toBeGreaterThan(3);
  expect(polling.detached).toBe(0);
  expect(polling.removed).toBe(0);
  checks.push('two real polling cycles retain every historical message DOM node');

  await page.getByLabel('向蜂群补充消息').pressSequentially('仅编辑草稿，不发送消息', {delay: 40});
  const typing = await stability();
  expect(typing.detached).toBe(0);
  expect(typing.removed).toBe(0);
  await page.getByLabel('向蜂群补充消息').fill('');
  checks.push('draft typing does not remount or replay historical messages');

  // Browser text selection and reading position should survive a data refresh.
  await page.locator('.px-thread-scroll').evaluate(el => el.scrollTop = 0);
  const selected = await page.locator('[data-event-seq] .body').first().evaluate(el => {
    const range = document.createRange(); range.selectNodeContents(el);
    const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    return selection.toString();
  });
  expect(selected.length).toBeGreaterThan(0);
  const selectionPoll = polls;
  await expect.poll(() => polls, {timeout: 10000}).toBeGreaterThan(selectionPoll);
  await page.waitForTimeout(250);
  expect(await page.evaluate(() => window.getSelection().toString())).toBe(selected);
  expect(await page.locator('.px-thread-scroll').evaluate(el => el.scrollTop)).toBe(0);
  checks.push('history selection and reading position survive an empty journal refresh');
  await page.evaluate(() => window.getSelection().removeAllRanges());
  await page.screenshot({path: path.join(output, 'Phoenix-conversation-stable.png')});

  if (local) {
    await page.goto(`${base}/run/${meta.ui_active_run_id}`);
    await expect(page.locator('[data-event-seq]').first()).toBeVisible();
    await track();
    const clock = await page.locator('.px-solve-status > span').last().innerText();
    await expect.poll(() => page.locator('.px-solve-status > span').last().innerText(), {timeout: 5000}).not.toBe(clock);
    const ticking = await stability();
    expect(ticking.detached).toBe(0);
    expect(ticking.removed).toBe(0);
    checks.push('the active-run clock ticks without remounting historical messages');

    await page.goto(`${base}/run/${meta.paused_run_id}`);
    await expect(page.locator('[data-event-seq]').first()).toBeVisible();
    await track();
    const content = 'UI timeline append regression ' + Date.now();
    const response = await context.request.post(`${base}/api/runs/${meta.paused_run_id}/messages`, {
      headers: {Authorization: 'Bearer ' + token}, data: {content},
    });
    expect(response.ok()).toBe(true);
    await expect(page.locator('[data-event-seq] .body').filter({hasText: content})).toHaveCount(1);
    const appended = await stability();
    expect(appended.detached).toBe(0);
    expect(appended.removed).toBe(0);
    checks.push('native operator event appends once via journal/SSE while old nodes remain mounted');
  }
  expect(errors).toEqual([]);
  expect(failed).toEqual([]);
  fs.writeFileSync(path.join(output, 'conversation-stability.json'), JSON.stringify({checks, polling, errors, failed, base}, null, 2));
  console.log(JSON.stringify({passed: checks.length, polling, errors, failed}, null, 2));
} finally { await browser.close(); }
