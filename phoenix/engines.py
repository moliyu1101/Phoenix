from __future__ import annotations

import asyncio
import json

from .agent_gateway import AgentGateway
from .domain import Conflict, dump, now, uid
from .vendor.engine.solver.cli_engines.registry import DRIVERS


class Engines:
    """Migrated Phoenix drivers and Phoenix Pi RPC, sharing native ownership and accounting."""
    def __init__(self, components):
        self.c = components
        self.gateway = AgentGateway(components)

    def catalog(self):
        return [{'id': 'api', 'label': 'Phoenix 原生工具循环', 'gateway': True},
                {'id': 'pi-rpc', 'label': 'Pi RPC', 'gateway': True}] + [
                {'id': name, 'label': name, 'gateway': name in ('pi', 'omp'),
                 'requires_account': name not in ('pi', 'omp')} for name in sorted(DRIVERS)]

    async def health(self, rid):
        rows = self.c.sandboxes.rows(rid)
        if not rows:
            return [{**entry, 'installed': entry['id']=='api', 'sandbox_state': 'absent'} for entry in self.catalog()]
        name = rows[0]['container_name']
        result = []
        for entry in self.catalog():
            if entry['id'] == 'api':
                result.append({**entry, 'installed': True})
                continue
            binary = 'pi' if entry['id'] == 'pi-rpc' else entry['id']
            try:
                path = await self.c.sandboxes.docker('exec', name, 'which', binary)
                result.append({**entry, 'installed': True, 'binary': path.strip()})
            except RuntimeError:
                result.append({**entry, 'installed': False})
        return result

    async def solve(self, rid, task, profile):
        engine = task.get('_worker', {}).get('engine', 'api')
        if engine not in DRIVERS and engine != 'pi-rpc':
            raise ValueError('Unknown CLI engine')
        name = await self.c.sandboxes.ensure(rid)
        tid = task['id']
        work = self.c.store.root/'work'/rid/tid
        work.mkdir(parents=True, exist_ok=True)
        home = work/'.home'
        home.mkdir(exist_ok=True)
        model_calls_before = self.c.store.run(rid)['calls']
        token = await self.gateway.bind(rid, tid, profile, task.get('_worker', {}).get('id'))
        # Only a scoped model socket is reachable from the offline container.
        # socat is per-run, and all worker tokens are independently revoked.
        try:
            await self.c.sandboxes.docker('exec', '-d', name, 'socat',
                'TCP-LISTEN:18751,bind=127.0.0.1,reuseaddr,fork', 'UNIX-CONNECT:/gateway/model.sock')
        except RuntimeError:
            pass  # Existing run gateway may already be listening.
        env = ['-e', 'HOME=/work/'+tid+'/.home', '-e', 'XDG_CONFIG_HOME=/work/'+tid+'/.home/.config',
               '-e', 'CTF_MODEL_BASE_URL=http://127.0.0.1:18751/v1', '-e', 'CTF_TASK_TOKEN='+token,
               '-e', 'CTF_MODEL_ID='+profile.model, '-e', 'CTF_MODEL_CONTEXT='+str(profile.context_tokens),
               '-e', 'CTF_MODEL_MAX_TOKENS='+str(profile.output_tokens)]
        prompt = dump({'task': task['goal'], 'context': self.c.runtime.core(rid, task),
            'workspace': '/work/'+tid, 'inputs': '/input',
            'handoff': 'Execute tools, retain reproducible artifacts and write WRITEUP.md. Report concise evidence-backed findings. Do not print secrets.'})
        session_rows = self.c.store.all('SELECT * FROM engine_sessions WHERE run_id=? AND task_id=? AND engine=? ORDER BY created DESC LIMIT 1', (rid, tid, engine))
        saved_session = session_rows[0]['remote_session'] if session_rows else ''
        if engine == 'pi-rpc':
            argv = ['pi', '--mode', 'rpc', '--session-dir', '/work/'+tid+'/.pi-sessions',
                    '--extension', '/opt/phoenix-extensions/phoenix-tools.ts',
                    '--extension', '/home/ctf/.pi/agent/extensions/platform-provider.ts',
                    '--provider', 'ctf-gateway', '--model', profile.model]
            if saved_session:
                argv.extend(['--session', saved_session])
            elif session_rows:
                argv.append('--continue')
            stdin = dump({'id': uid('prompt'), 'type': 'prompt', 'message': prompt})+'\n'
        else:
            driver = DRIVERS[engine]
            if saved_session:
                argv, stdin = driver.build_resume_input(prompt, saved_session, web_access=False, kb_access=False, stream=True)
            else:
                argv, stdin = driver.build_execute_input(prompt, None, web_access=False, kb_access=False, stream=True)
            if engine in ('pi', 'omp'):
                argv = argv[:-1] if argv and argv[-1] == prompt else argv
                argv[1:1] = ['--extension', '/home/ctf/.pi/agent/extensions/platform-provider.ts',
                             '--extension', '/opt/phoenix-extensions/phoenix-tools.ts',
                             '--provider', 'ctf-gateway', '--model', profile.model]
        sid = uid('engine')
        self.c.store.execute('INSERT INTO engine_sessions VALUES(?,?,?,?,?,?,?)',
            (sid, rid, tid, engine, 'running', saved_session, now()))
        self.c.store.event(rid, 'engine.started', {'engine': engine, 'session_id': sid, 'worker_id': task.get('_worker', {}).get('id')}, tid)
        process, output = None, bytearray()
        ended, originals, tool_inputs = False, [], {}
        try:
            supervisor = ('import pathlib,subprocess,sys; '
                'p=subprocess.Popen(sys.argv[1:],start_new_session=True); '
                'pathlib.Path('+repr('/tmp/'+sid+'.pid')+').write_text(str(p.pid)); sys.exit(p.wait())')
            process = await asyncio.create_subprocess_exec('docker', 'exec', '-i', '-w', '/work/'+tid,
                *env, name, 'python', '-c', supervisor, *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                limit=self.c.settings.max_output_bytes+1)
            if stdin:
                process.stdin.write(stdin.encode())
                await process.stdin.drain()
            if engine != 'pi-rpc':
                process.stdin.close()
            while line := await asyncio.wait_for(process.stdout.readline(), 300):
                if len(output)+len(line) > self.c.settings.max_output_bytes:
                    raise ValueError('CLI output exceeded the run capture limit')
                output.extend(line)
                text = line.decode('utf-8', 'replace').strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except ValueError:
                    event = {'type': 'stderr', 'text': text[:2000]}
                self.c.store.event(rid, 'engine.event', {'engine': engine, 'session_id': sid, 'event': event}, tid)
                if event.get('type') == 'tool_execution_start':
                    tool_inputs[event.get('toolCallId')] = event.get('args') or {}
                if event.get('type') == 'tool_execution_end' and event.get('toolName') in ('bash', 'read'):
                    original = self.c.evidence.record(rid, tid, 'cli_'+event['toolName'],
                        tool_inputs.get(event.get('toolCallId'), {}), dump(event.get('result', {})),
                        'sandbox', not event.get('isError', False))
                    if original['ok']:
                        originals.append(original['id'])
                        self.c.evidence.scan_flags(original)
                if engine == 'pi-rpc' and event.get('type') == 'response' and event.get('success') is False:
                    raise RuntimeError('Pi RPC rejected the request')
                if engine == 'pi-rpc' and event.get('type') in ('agent_end', 'agent_settled'):
                    ended = True
                    break
            if engine != 'pi-rpc':
                await process.wait()
                ended = process.returncode == 0
            transcript = output.decode('utf-8', 'replace')
            remote_session, summary = saved_session, transcript[-5000:]
            if engine == 'pi-rpc':
                sessions = list((work/'.pi-sessions').glob('*.jsonl'))
                if sessions:
                    remote_session = '/work/'+tid+'/.pi-sessions/'+max(sessions,key=lambda p:p.stat().st_mtime).name
            if engine != 'pi-rpc':
                parsed = DRIVERS[engine].parse(transcript)
                remote_session, summary = parsed.session or '', parsed.text[-5000:]
            record = self.c.evidence.record(rid, tid, 'cli_agent', {'engine': engine}, transcript,
                                           'model', ended)
            native = self.gateway.task(rid, token)
            originals.extend(native['evidence_ids'])
            finish = native['finish']
            if finish:
                summary = finish['summary']
            supported = bool(originals)
            self.c.store.execute('UPDATE engine_sessions SET state=?,remote_session=? WHERE id=?',
                ('completed' if ended else 'failed', remote_session, sid))
            self.c.store.event(rid, 'worker.message', {'content': summary, 'worker_id': task.get('_worker', {}).get('id'), 'evidence_id': record['id']}, tid)
            return {'state': (finish['outcome'] if finish else 'done') if ended and supported else 'failed',
                    'summary': (summary if supported else 'CLI returned without original tool evidence. '+summary)[-6000:],
                    'evidence_id': record['id'], 'calls': self.c.store.run(rid)['calls']-model_calls_before}
        except BaseException:
            self.c.store.execute("UPDATE engine_sessions SET state='interrupted' WHERE id=?", (sid,))
            raise
        finally:
            self.gateway.revoke(token)
            if process and process.returncode is None:
                if engine == 'pi-rpc':
                    try:
                        process.stdin.write(b'{"type":"abort"}\n')
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                await asyncio.shield(self.c.sandboxes.docker('exec', name, 'python', '-c',
                    'import os,signal,pathlib\np=pathlib.Path('+repr('/tmp/'+sid+'.pid')+')\n'
                    'if p.exists():\n'
                    ' try: os.killpg(int(p.read_text()),signal.SIGKILL)\n'
                    ' except ProcessLookupError: pass'))
                if process.returncode is None:
                    process.terminate()
                await process.wait()

    async def shutdown(self):
        await self.gateway.shutdown()
