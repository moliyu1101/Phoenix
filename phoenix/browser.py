from __future__ import annotations

import asyncio
import base64
from urllib.parse import urlsplit, urlunsplit

import httpx


class Browsers:
    """Phoenix browser workflow: Chromium in the offline run sandbox, scoped HTTP via the native tool bus."""
    def __init__(self, components):
        self.c = components
        self.sessions, self.locks = {}, {}
        self.playwright = None

    async def session(self, rid):
        if rid in self.sessions:
            if self.sessions[rid]['browser'].is_connected():
                return self.sessions[rid]
            old = self.sessions.pop(rid)
            old['relay'].close()
            await old['relay'].wait_closed()
        from playwright.async_api import async_playwright
        if self.playwright is None:
            self.playwright = await async_playwright().start()
        name = await self.c.sandboxes.ensure(rid)
        await self.c.sandboxes.docker('exec', '-d', name, 'chromium', '--headless', '--no-sandbox',
            '--disable-gpu', '--disable-dev-shm-usage', '--no-first-run', '--disable-background-networking',
            '--remote-debugging-port=9222', '--remote-allow-origins=*', '--user-data-dir=/tmp/phoenix-chromium', 'about:blank')

        async def tunnel(reader, writer):
            process = await asyncio.create_subprocess_exec('docker', 'exec', '-i', name, 'socat', 'STDIO', 'TCP:127.0.0.1:9222',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            async def copy(src, dst):
                while block := await src.read(65536):
                    dst.write(block)
                    await dst.drain()
            try:
                tasks = [asyncio.create_task(copy(reader, process.stdin)), asyncio.create_task(copy(process.stdout, writer))]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                writer.close()
                if process.returncode is None:
                    process.terminate()
                await process.wait()
        relay = await asyncio.start_server(tunnel, '127.0.0.1', 0)
        port = relay.sockets[0].getsockname()[1]
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for attempt in range(40):
                    try:
                        result = (await client.get(f'http://127.0.0.1:{port}/json/version', timeout=2)).json()
                        break
                    except Exception:
                        if attempt == 39:
                            raise
                        await asyncio.sleep(0.25)
            parsed = urlsplit(result['webSocketDebuggerUrl'])
            endpoint = urlunsplit(('ws', f'127.0.0.1:{port}', parsed.path, '', ''))
            browser = await self.playwright.chromium.connect_over_cdp(endpoint)
            context = await browser.new_context(service_workers='block', accept_downloads=False)
            async def route(request_route):
                request = request_route.request
                try:
                    headers = {k: v for k, v in (await request.all_headers()).items()
                               if k.lower() not in ('host', 'connection', 'content-length', 'accept-encoding')}
                    response = await self.c.investigation.request(rid, None, request.method, request.url,
                        headers, request.post_data or '', source='browser', browser=True)
                    data = base64.b64decode(response['body_base64'])
                    await request_route.fulfill(status=response['status'], body=data,
                        headers={k: v for k, v in response['_transport_headers'].items()
                                 if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding')})
                except Exception:
                    await request_route.abort('blockedbyclient')
            await context.route('**/*', route)
            # No unrecorded browser websocket channel bypasses the scoped HTTP bus.
            await context.route_web_socket('**/*', lambda ws: ws.close())
            page = await context.new_page()
            page.set_default_timeout(15000)
            session = {'browser': browser, 'context': context, 'page': page, 'relay': relay}
            self.sessions[rid] = session
            return session
        except BaseException:
            relay.close()
            await relay.wait_closed()
            raise

    async def action(self, rid, action, url='', selector='', value=''):
        async with self.locks.setdefault(rid, asyncio.Lock()):
            if action == 'navigate':
                self.c.tools.target(rid, url, ('http', 'https'))
            session = await self.session(rid)
            page = session['page']
            page.set_default_timeout(320000 if self.c.investigation.intercept(rid) else 15000)
            if action == 'navigate':
                await page.goto(url, wait_until='domcontentloaded')
            elif action == 'click':
                await page.locator(selector).first.click()
            elif action == 'fill':
                await page.locator(selector).first.fill(value)
            elif action == 'press':
                await page.locator(selector).first.press(value)
            elif action not in ('read', 'screenshot'):
                raise ValueError('Unknown browser action')
            self.c.tools.target(rid, page.url, ('http', 'https'))
            result = {'url': page.url, 'title': await page.title(),
                      'text': (await page.locator('body').inner_text())[:24000],
                      'links': await page.locator('a[href]').evaluate_all('(nodes)=>nodes.slice(0,60).map(a=>({text:a.innerText,url:a.href}))')}
            if action == 'screenshot':
                result['image_base64'] = base64.b64encode(await page.screenshot()).decode()
            return result

    async def shutdown(self):
        for session in self.sessions.values():
            await session['browser'].close()
            session['relay'].close()
            await session['relay'].wait_closed()
        self.sessions.clear()
        if self.playwright:
            await self.playwright.stop()
