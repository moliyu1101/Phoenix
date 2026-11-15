from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from .domain import Conflict, now, uid
from .sandbox import DockerSandbox


class RunSandboxes:
    """Phoenix-style per-challenge lifetime, owned by the native Phoenix run."""
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.locks: dict[str, asyncio.Lock] = {}
        self.legacy = DockerSandbox(store, settings)

    def command(self, *args):
        return self.legacy.command(*args)

    async def docker(self, *args, timeout=45):
        if not shutil.which('docker'):
            raise RuntimeError('Docker is unavailable. Host execution is deliberately not a fallback.')
        process = await asyncio.create_subprocess_exec('docker', *map(str, args),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('Docker: ' + stderr.decode('utf-8', 'replace')[:1000])
        return stdout.decode('utf-8', 'replace')

    def rows(self, rid):
        self.store.run(rid)
        return self.store.all('SELECT * FROM run_sandboxes WHERE run_id=?', (rid,))

    async def describe(self, rid):
        rows = self.rows(rid)
        if not rows:
            return {'run_id': rid, 'state': 'absent', 'available': bool(shutil.which('docker'))}
        row = rows[0]
        try:
            state = json.loads(await self.docker('inspect', '--format', '{{json .State}}', row['container_name']))
            row['state'] = state['Status']
        except RuntimeError as exc:
            row.update(state='unavailable', error=str(exc))
        return row

    async def ensure(self, rid):
        async with self.locks.setdefault(rid, asyncio.Lock()):
            run = self.store.run(rid)
            category = self.store.challenge(run['challenge_id'])['category']
            image = self.settings.sandbox_images.get(category)
            if not image:
                raise ValueError('No sandbox image configured for this category')
            inputs = self.store.root / 'inputs' / run['challenge_id']
            inputs.mkdir(parents=True, exist_ok=True)
            work = self.store.root / 'work' / rid
            work.mkdir(parents=True, exist_ok=True)
            bridge = self.store.root / 'bridges' / rid
            bridge.mkdir(parents=True, exist_ok=True)
            rows = self.rows(rid)
            name = rows[0]['container_name'] if rows else 'phoenix-run-' + rid
            try:
                state = (await self.docker('inspect', '--format', '{{.State.Status}}', name)).strip()
            except RuntimeError as exc:
                if 'no such' not in str(exc).lower() and 'not found' not in str(exc).lower():
                    raise
                state = 'absent'
            if state == 'paused':
                raise Conflict('Sandbox is paused; resume it before executing commands')
            if state == 'absent':
                args = ['run', '-d', '--name', name, '--label', 'phoenix.run_id='+rid,
                        '--init', '--read-only', '--network', 'none', '--cap-drop', 'ALL',
                        '--security-opt', 'no-new-privileges', '--pids-limit', '256',
                        '--memory', self.settings.sandbox_memory, '--cpus', str(self.settings.sandbox_cpus),
                        '--user', f'{os.getuid()}:{os.getgid()}',
                        '--tmpfs', '/tmp:rw,nosuid,nodev,size=256m',
                        '--mount', f'type=bind,src={inputs},dst=/input,readonly',
                        '--mount', f'type=bind,src={work},dst=/work', '-w', '/work',
                        '--mount', f'type=bind,src={bridge},dst=/gateway,readonly',
                        '--mount', f'type=bind,src={Path(__file__).parent / "agent_extensions"},dst=/opt/phoenix-extensions,readonly',
                        '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                        '-e', 'XDG_CACHE_HOME=/tmp/cache', '-e', 'XDG_CONFIG_HOME=/tmp/config',
                        image, 'sleep', 'infinity']
                if category in ('pwn', 'reverse'):
                    args[2:2] = ['--cap-add', 'SYS_PTRACE']
                await self.docker(*args)
            elif state != 'running':
                await self.docker('start', name)
            self.store.execute('INSERT INTO run_sandboxes VALUES(?,?,?,?,?,?,?) '
                'ON CONFLICT(run_id) DO UPDATE SET state=excluded.state,updated=excluded.updated',
                (rid, name, category, image, 'running', now(), now()))
            if not rows:
                self.store.event(rid, 'sandbox.created', {'category': category, 'image': image})
            return name

    async def lifecycle(self, rid, action):
        if action == 'start':
            await self.ensure(rid)
        else:
            if self.store.run(rid)['state'] in ('created', 'running', 'distilling'):
                raise Conflict('Pause the run before changing its sandbox lifecycle')
            rows = self.rows(rid)
            if not rows:
                raise Conflict('No sandbox has been created')
            command = {'pause': 'pause', 'resume': 'unpause', 'stop': 'stop'}.get(action)
            if not command:
                raise ValueError('Unknown sandbox lifecycle action')
            await self.docker(command, rows[0]['container_name'])
            self.store.event(rid, 'sandbox.'+action, {})
        return await self.describe(rid)

    async def execute(self, rid, tid, script, timeout):
        if not 1 <= timeout <= 300 or len(script) > 40000:
            raise ValueError('Sandbox limits exceeded')
        name = await self.ensure(rid)
        (self.store.root / 'work' / rid / tid).mkdir(parents=True, exist_ok=True)
        xid = uid('exec')
        self.store.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)', (xid, rid, tid, name, 'running', now()))
        # A uniquely named exec PID lets timeout/cancellation kill just this command,
        # leaving other workers and the persistent container intact.
        pidfile = '/tmp/'+xid+'.pid'
        wrapper = ('import pathlib,subprocess,sys; '
                   'p=subprocess.Popen(["/bin/sh","-lc",sys.argv[1]],start_new_session=True); '
                   'pathlib.Path('+repr(pidfile)+').write_text(str(p.pid)); '
                   'sys.exit(p.wait())')
        process = await asyncio.create_subprocess_exec('docker', 'exec', '-w', '/work/'+tid, name,
            'python', '-c', wrapper, script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        chunks, total, timed_out = bytearray(), 0, False
        async def drain():
            nonlocal total
            while block := await process.stdout.read(65536):
                total += len(block)
                chunks.extend(block[:max(0, self.settings.max_output_bytes-len(chunks))])
            await process.wait()
        try:
            try:
                await asyncio.wait_for(drain(), timeout)
            except asyncio.TimeoutError:
                timed_out = True
            return {'stdout': chunks.decode('utf-8', 'replace'), 'exit_code': process.returncode,
                    'timed_out': timed_out, 'truncated': total > len(chunks), 'observed_bytes': total,
                    'work_prefix': f'work:{tid}/', 'execution_id': xid, 'persistent': True}
        finally:
            if process.returncode is None:
                # PID and descendant cleanup is implemented inside the isolated container.
                await asyncio.shield(self.docker('exec', name, 'python', '-c',
                    'import os,signal,pathlib\np=pathlib.Path('+repr(pidfile)+')\n'
                    'pid=int(p.read_text()) if p.exists() else 0\n'
                    'if pid>1:\n'
                    ' try: os.killpg(pid,signal.SIGKILL)\n'
                    ' except ProcessLookupError: pass'))
                if process.returncode is None:
                    process.kill()
                await process.wait()
            self.store.execute("UPDATE executions SET state='cleaned' WHERE id=?", (xid,))

    async def reconcile(self, rid):
        # Do not remove persistent containers during recovery: the operator can
        # inspect them. Uncertain command records must be explicitly acknowledged.
        rows = self.store.all("SELECT * FROM executions WHERE run_id=? AND state IN ('running','uncertain')", (rid,))
        result = []
        for row in rows:
            if row['container_name'].startswith('phoenix-job_'):
                result.extend(await self.legacy.reconcile(rid))
                continue
            owned = self.rows(rid)
            if not owned or row['container_name'] != owned[0]['container_name']:
                raise Conflict('Execution container ownership does not match this run')
            state = (await self.docker('inspect','--format','{{.State.Status}}',row['container_name'])).strip()
            clean = state in ('exited','dead','created')
            if state == 'running':
                output = await self.docker('exec',row['container_name'],'python','-c',
                    'import os,pathlib,signal\np=pathlib.Path('+repr('/tmp/'+row['id']+'.pid')+')\n'
                    'if p.exists():\n'
                    ' try: os.killpg(int(p.read_text()),signal.SIGKILL)\n'
                    ' except ProcessLookupError: pass\n'
                    ' print("cleaned")\n'
                    'else: print("uncertain")')
                clean = output.strip() == 'cleaned'
            self.store.execute('UPDATE executions SET state=? WHERE id=?',('cleaned' if clean else 'uncertain',row['id']))
            result.append({'execution_id':row['id'],'cleaned':clean,'container_preserved':True})
        return result
