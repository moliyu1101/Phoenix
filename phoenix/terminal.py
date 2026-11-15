from __future__ import annotations

import asyncio
import base64
import fcntl
import os
import pty
import struct
import termios

from .domain import Conflict, now, uid


class Terminals:
    """Operator PTYs stay inside the owned sandbox; HTTP polling survives UI navigation."""
    def __init__(self, components):
        self.c, self.store = components, components.store
        self.sessions = {}

    def lookup(self, rid, sid):
        self.store.one('SELECT id FROM terminal_sessions WHERE id=? AND run_id=?', (sid, rid))
        if sid not in self.sessions:
            raise Conflict('Terminal disconnected; open a new terminal in the preserved sandbox')
        return self.sessions[sid]

    async def start(self, rid):
        if self.store.run(rid)['state'] in ('created', 'running', 'distilling'):
            raise Conflict('Pause the run before taking over its terminal')
        if len(self.sessions) >= 8:
            raise Conflict('Close an unused terminal before opening another')
        name = await self.c.sandboxes.ensure(rid)
        sid = uid('terminal')
        master, slave = pty.openpty()
        os.set_blocking(master, False)
        process = await asyncio.create_subprocess_exec('docker', 'exec', '-it', '-e', 'TERM=xterm-256color',
            name, '/bin/bash', '--noprofile', '--norc', stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        self.store.execute('INSERT INTO terminal_sessions VALUES(?,?,?,?)', (sid, rid, 'open', now()))
        self.sessions[sid] = {'master': master, 'process': process, 'run_id': rid}
        loop = asyncio.get_running_loop()
        async def watch():
            await process.wait()
            if sid in self.sessions:
                self.sessions.pop(sid)
                loop.remove_reader(master)
                os.close(master)
                self.store.execute("UPDATE terminal_sessions SET state='closed' WHERE id=?", (sid,))
        asyncio.create_task(watch())
        def read():
            try:
                block = os.read(master, 8192)
                if not block:
                    loop.remove_reader(master)
                    return
                self.store.execute('INSERT INTO terminal_output(session_id,content,created) VALUES(?,?,?)',
                                   (sid, base64.b64encode(block).decode(), now()))
                # Keep a bounded, byte-exact replay window in the private database.
                self.store.execute('DELETE FROM terminal_output WHERE session_id=? AND seq < '
                    '(SELECT COALESCE(MAX(seq),0)-256 FROM terminal_output WHERE session_id=?)', (sid, sid))
            except (OSError, ValueError):
                loop.remove_reader(master)
        loop.add_reader(master, read)
        self.store.event(rid, 'terminal.opened', {'terminal_id': sid, 'actor': 'operator'})
        return {'id': sid, 'state': 'open'}

    def write(self, rid, sid, encoded):
        session = self.lookup(rid, sid)
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 16384:
            raise ValueError('Terminal input is too large')
        os.write(session['master'], data)
        return {'accepted_bytes': len(data)}

    def resize(self, rid, sid, rows, cols):
        session = self.lookup(rid, sid)
        if not 2 <= rows <= 200 or not 10 <= cols <= 500:
            raise ValueError('Terminal dimensions exceed limits')
        fcntl.ioctl(session['master'], termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        return {'rows': rows, 'cols': cols}

    def output(self, rid, sid, after=0):
        row = self.store.one('SELECT * FROM terminal_sessions WHERE id=? AND run_id=?', (sid, rid))
        chunks = self.store.all('SELECT seq,content FROM terminal_output WHERE session_id=? AND seq>? ORDER BY seq LIMIT 100', (sid, after))
        return {'state': row['state'], 'items': chunks, 'next_after': chunks[-1]['seq'] if chunks else after}

    async def close(self, rid, sid):
        self.store.one('SELECT id FROM terminal_sessions WHERE id=? AND run_id=?', (sid, rid))
        if sid not in self.sessions:
            return {'state': 'closed'}
        session = self.sessions.pop(sid)
        asyncio.get_running_loop().remove_reader(session['master'])
        os.close(session['master'])
        if session['process'].returncode is None:
            session['process'].terminate()
        await session['process'].wait()
        self.store.execute("UPDATE terminal_sessions SET state='closed' WHERE id=?", (sid,))
        self.store.event(rid, 'terminal.closed', {'terminal_id': sid})
        return {'state': 'closed'}

    async def shutdown(self):
        for sid, session in list(self.sessions.items()):
            await self.close(session['run_id'], sid)
