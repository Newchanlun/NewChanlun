"""Review放行前无fork启动域。只有本模块持有的Popen wait可提交该域终态。"""
from __future__ import annotations

import os
import subprocess
import sys

from .maintenance import Gate, now
from .maintenance_epoch import local_epoch

# -I -S 禁用site/user启动钩子；GO之前不导入项目、不fork、不exec、不接外部资源。
# 两个单向pipe不传秘密。EOF只让尚未放行的bootstrap退出，不杀已接受工作。
BOOTSTRAP = """import os,sys
ready,go=map(int,sys.argv[1:3])
os.write(ready,b'R');os.close(ready)
permit=os.read(go,1);os.close(go)
if permit != b'G': sys.exit(78)
os.execv(sys.argv[3],sys.argv[3:])
"""


class Launch:
    def __init__(self, gate: Gate, parent: str, job: str, command: list[str], **kwargs):
        self.gate, self.parent, self.job = gate, parent, job
        self.bound = False
        self.released = False
        self.settled = False
        ready_r, ready_w = os.pipe()
        go_r, go_w = os.pipe()
        self.go = go_w
        try:
            self.process = subprocess.Popen([sys.executable, '-I', '-S', '-c', BOOTSTRAP,
                                             str(ready_w), str(go_r), *command],
                                            pass_fds=(ready_w, go_r), **kwargs)
        except BaseException:
            os.close(ready_r)
            os.close(go_w)
            raise
        finally:
            os.close(ready_w)
            os.close(go_r)
        self.ready = ready_r
        self.binding = None

    def prepare(self):
        try:
            if os.read(self.ready, 1) != b'R':
                raise OSError('bootstrap unavailable')
            self.gate.prepare_spawn(self.parent, self.job, self.process.pid)
            with self.gate.tx() as db:
                self.binding = dict(db.execute('SELECT * FROM spawn_launches WHERE job=?', (self.job,)).fetchone())
            self.bound = True
        finally:
            os.close(self.ready)
            self.ready = None
            if not self.bound:
                self.close()  # no GO; process naturally returns, no invented evidence

    @property
    def pid(self):
        return self.process.pid

    def release(self):
        self.gate.release_spawn(self.parent, self.job)
        self.released = True
        try:
            if os.write(self.go, b'G') != 1:
                raise OSError('incomplete bootstrap release')
        finally:
            self.close()

    def close(self):
        if self.go is not None:
            os.close(self.go)
            self.go = None

    def reap(self) -> bool:
        code = self.process.poll()  # real waitpid result, never supplied by caller
        if code is None or not self.bound or self.released or self.settled:
            return False
        with self.gate.tx() as db:
            self.gate._owner(db, self.parent)
            row = db.execute('SELECT * FROM spawn_launches WHERE job=?', (self.job,)).fetchone()
            if (row is None or dict(row) != self.binding or row['parent'] != self.parent or row['pid'] != self.pid
                    or row['kind'] != 'review-bootstrap-v1' or row['released_at'] or row['confirmed_at']
                    or (row['host'], row['boot']) != local_epoch()):
                return False
            task = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (self.job, row['owner'])).fetchone()
            if task is None:
                return False
            if any(db.execute(f'SELECT 1 FROM {table} WHERE job=?', (self.job,)).fetchone()
                   for table in ('witnesses', 'bindings', 'local_resources')):
                return False
            # No GO ever written + trusted no-fork bootstrap + actual Popen wait:
            # all possible resources were this process and inherited pipe endpoints.
            self.close()
            db.execute('INSERT INTO spawn_exits VALUES(?,?,?,?,?)', (self.job, self.parent, self.pid, code, now()))
            db.execute('INSERT INTO cancellations VALUES(?,?,?,?)', (self.job, self.parent, 'bootstrap_unreleased', now()))
            db.execute("UPDATE jobs SET state='finished',ended_at=? WHERE id=? AND owner=?", (now(), self.job, row['owner']))
            state = db.execute('SELECT * FROM control').fetchone()
            db.execute('UPDATE owners SET stopped=1,ack=?,ack_at=? WHERE id=?',
                       (state['generation'] if state['closed'] else -1, now(), row['owner']))
        self.settled = True
        return True
