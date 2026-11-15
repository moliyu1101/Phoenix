from __future__ import annotations

import asyncio
import os
import shutil

from .config import Settings
from .domain import now, uid
from .store import Store


class DockerSandbox:
    """A disposable per-command container. Never falls back to a host shell."""
    def __init__(self, store: Store, settings: Settings):
        self.store, self.settings = store, settings

    def command(self, name: str, input_dir, work_dir, script: str) -> list[str]:
        return ['docker', 'run', '--name', name, '--init', '--read-only', '--network', 'none',
                '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--pids-limit', '96',
                '--memory', self.settings.sandbox_memory, '--cpus', str(self.settings.sandbox_cpus),
                '--user', f'{os.getuid()}:{os.getgid()}', '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m',
                '--mount', f'type=bind,src={input_dir},dst=/input,readonly',
                '--mount', f'type=bind,src={work_dir},dst=/work', '-w', '/work',
                '-e', 'HOME=/tmp', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                self.settings.sandbox_image, '/bin/sh', '-lc', script]

    async def execute(self, rid: str, tid: str, script: str, timeout: int) -> dict:
        if not shutil.which('docker'):
            raise RuntimeError('Docker is unavailable. Host execution is deliberately not a fallback.')
        if not 1 <= timeout <= 300 or len(script) > 40000:
            raise ValueError('Sandbox limits exceeded')
        challenge_id = self.store.run(rid)['challenge_id']
        inputs = self.store.root / 'inputs' / challenge_id
        work = self.store.root / 'work' / rid / tid
        work.mkdir(parents=True, exist_ok=True)
        name = 'phoenix-' + uid('job')
        xid = uid('exec')
        self.store.execute('INSERT INTO executions VALUES(?,?,?,?,?,?)', (xid, rid, tid, name, 'running', now()))
        args = self.command(name, inputs, work, script)
        process = None
        chunks = bytearray()
        total = 0
        timed_out = False
        try:
            process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.STDOUT)
            async def drain():
                nonlocal total
                while True:
                    block = await process.stdout.read(65536)
                    if not block:
                        break
                    total += len(block)
                    remaining = self.settings.max_output_bytes - len(chunks)
                    if remaining > 0:
                        chunks.extend(block[:remaining])
                await process.wait()
            try:
                await asyncio.wait_for(drain(), timeout)
            except asyncio.TimeoutError:
                timed_out = True
            return {'stdout': chunks.decode('utf-8', 'replace'), 'exit_code': process.returncode,
                    'timed_out': timed_out, 'truncated': total > len(chunks), 'observed_bytes': total,
                    'work_prefix': f'work:{tid}/', 'execution_id': xid}
        finally:
            # Shield cleanup from parent cancellation; a failed cleanup remains visibly uncertain.
            clean = await asyncio.shield(self.remove(name))
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            self.store.execute('UPDATE executions SET state=? WHERE id=?', ('cleaned' if clean else 'uncertain', xid))

    async def remove(self, name: str) -> bool:
        if not name.startswith('phoenix-job_') or not shutil.which('docker'):
            return False
        process = None
        try:
            process = await asyncio.create_subprocess_exec('docker', 'rm', '-f', name,
                                                           stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(process.communicate(), 20)
            return process.returncode == 0 or b'No such container' in output
        except (OSError, asyncio.TimeoutError):
            return False
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    async def reconcile(self, rid: str) -> list[dict]:
        rows = self.store.all("SELECT * FROM executions WHERE run_id=? AND state IN ('running','uncertain')", (rid,))
        result = []
        for row in rows:
            clean = await self.remove(row['container_name'])
            self.store.execute('UPDATE executions SET state=? WHERE id=?', ('cleaned' if clean else 'uncertain', row['id']))
            result.append({'execution_id': row['id'], 'cleaned': clean})
        return result
