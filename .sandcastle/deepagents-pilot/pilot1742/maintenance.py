"""#1742 跨 TS/Python 的维护准入账本；事务只覆盖记账，不覆盖工作执行。"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pilot1742.maintenance_epoch import local_epoch

ROOT = Path('/Volumes/AgentStorage/newchanlun-maintenance')
LANES = ('decision', 'wayfinder', 'executor', 'review')


class ExecutorBusy(ValueError):
    """已有活执行见证；保留调用方 Busy75 合同。"""


class Closed(RuntimeError):
    pass


@contextmanager
def evidence_write():
    """仅用于业务结束后的证据提交；失败不改变业务结果，也不授权下一动作。"""
    try:
        yield
    except Exception:
        print('maintenance evidence unavailable', file=sys.stderr, flush=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(pid: int) -> str:
    if type(pid) is not int or pid < 1:
        raise ValueError('invalid pid')
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'stat='], capture_output=True, text=True,
                            env={**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'})
    fields = result.stdout.strip().rsplit(None, 1)
    if result.returncode or len(fields) != 2 or fields[1].startswith('Z'):
        raise ValueError('process unavailable')
    return fields[0]


def alive(pid: int, start: str) -> bool:
    try:
        return identity(pid) == start
    except ValueError:
        return False


def token(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', value) is None:
        raise ValueError('invalid identity')
    return value


class Gate:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root / 'maintenance.sqlite3'
        # 本地受信任 owner 的控制文件；不承载模型、提示词或凭据。
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self.tx() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER,
                    closed INTEGER, requested_at TEXT);
                INSERT OR IGNORE INTO control VALUES (1, 0, 0, NULL);
                CREATE TABLE IF NOT EXISTS owners (id TEXT PRIMARY KEY, lane TEXT, pid INTEGER, start TEXT,
                    registered_at TEXT, ack INTEGER, ack_at TEXT, stopped INTEGER DEFAULT 0, covered INTEGER DEFAULT 1);
                CREATE TABLE IF NOT EXISTS observer_faults (owner TEXT PRIMARY KEY, at TEXT);
                CREATE TABLE IF NOT EXISTS censuses (owner TEXT PRIMARY KEY, generation INTEGER, at TEXT);
                CREATE TABLE IF NOT EXISTS sightings (lane TEXT, pid INTEGER, start TEXT, observed_at TEXT,
                    PRIMARY KEY(lane,pid,start));
                CREATE TABLE IF NOT EXISTS sighting_resolutions (lane TEXT, pid INTEGER, start TEXT,
                    generation INTEGER, owners TEXT, at TEXT, PRIMARY KEY(lane,pid,start));
                CREATE TABLE IF NOT EXISTS lineage (job TEXT, owner TEXT, PRIMARY KEY(job,owner));
                CREATE TABLE IF NOT EXISTS bindings (job TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scopes (owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS local_resources (id TEXT PRIMARY KEY, job TEXT, host TEXT, boot TEXT,
                    pid INTEGER, start TEXT, sid INTEGER, child_pid INTEGER, code INTEGER, waited_at TEXT);
                CREATE TABLE IF NOT EXISTS local_resource_domains (resource TEXT PRIMARY KEY, baseline TEXT,
                    supervisor TEXT, sealed_at TEXT);
                CREATE TABLE IF NOT EXISTS local_resource_not_started (resource TEXT PRIMARY KEY,
                    pid INTEGER, start TEXT, reason TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS local_resource_diagnostics (resource TEXT PRIMARY KEY,
                    reason TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS action_exits (job TEXT PRIMARY KEY, owner TEXT, generation INTEGER,
                    pid INTEGER, start TEXT, opaque_clear INTEGER, at TEXT);
                CREATE TABLE IF NOT EXISTS action_returns (job TEXT PRIMARY KEY, owner TEXT, generation INTEGER,
                    pid INTEGER, start TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS cancellations (job TEXT PRIMARY KEY, owner TEXT, reason TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS local_owners (owner TEXT PRIMARY KEY, host TEXT, boot TEXT);
                CREATE TABLE IF NOT EXISTS local_actions (job TEXT PRIMARY KEY, owner TEXT, host TEXT, boot TEXT);
                CREATE TABLE IF NOT EXISTS epoch_resolutions (job TEXT PRIMARY KEY, host TEXT, old_boot TEXT,
                    new_boot TEXT, generation INTEGER, at TEXT);
                CREATE TABLE IF NOT EXISTS spawn_launches (job TEXT PRIMARY KEY, parent TEXT, owner TEXT,
                    host TEXT, boot TEXT, pid INTEGER, start TEXT, kind TEXT, prepared_at TEXT, released_at TEXT, confirmed_at TEXT);
                CREATE TABLE IF NOT EXISTS spawn_exits (job TEXT PRIMARY KEY, owner TEXT, pid INTEGER, code INTEGER, at TEXT);
                CREATE TABLE IF NOT EXISTS preflight_returns (witness TEXT PRIMARY KEY, at TEXT);
                CREATE TABLE IF NOT EXISTS recoveries (previous TEXT PRIMARY KEY, successor TEXT);
                CREATE TABLE IF NOT EXISTS returns (witness TEXT PRIMARY KEY, at TEXT);
                CREATE TABLE IF NOT EXISTS witnesses (id TEXT PRIMARY KEY, job TEXT, pid INTEGER, start TEXT,
                    started_at TEXT, completed_at TEXT);
                CREATE TABLE IF NOT EXISTS reconciliations (owner TEXT, generation INTEGER, at TEXT,
                    PRIMARY KEY(owner, generation));
                CREATE TABLE IF NOT EXISTS resolutions (job TEXT PRIMARY KEY, witness TEXT, generation INTEGER, at TEXT);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, work TEXT,
                    generation INTEGER, started_at TEXT, ended_at TEXT, state TEXT, transferable INTEGER DEFAULT 0);
                INSERT OR IGNORE INTO lineage SELECT id,owner FROM jobs;
            ''')

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, lane: str, pid: int | None = None, *, local_actions: bool = False) -> str:
        if lane not in LANES:
            raise ValueError('invalid lane')
        if local_actions and lane not in ('decision', 'wayfinder'):
            raise ValueError('only host-local graph actions support boot evidence')
        epoch = local_epoch() if local_actions else None
        pid = os.getpid() if pid is None else pid
        start, owner = identity(pid), uuid.uuid4().hex
        with self.tx() as db:
            db.execute('INSERT INTO owners(id,lane,pid,start,registered_at,ack) VALUES(?,?,?,?,?,?)',
                       (owner, lane, pid, start, now(), -1))
            if epoch is not None:
                db.execute('INSERT INTO local_owners VALUES(?,?,?)', (owner, *epoch))
        return owner

    def _owner(self, db, owner):
        row = db.execute('SELECT * FROM owners WHERE id=?', (token(owner),)).fetchone()
        if (row is None or row['stopped'] or not alive(row['pid'], row['start'])
                or db.execute('SELECT 1 FROM reconciliations WHERE owner=?', (owner,)).fetchone()):
            raise ValueError('owner unavailable')
        epoch = db.execute('SELECT host,boot FROM local_owners WHERE owner=?', (owner,)).fetchone()
        if epoch is not None and tuple(epoch) != local_epoch():
            raise ValueError('local process domain changed')
        return row

    def coverage(self, owner: str, covered: bool) -> None:
        if type(covered) is not bool:
            raise ValueError('invalid coverage')
        with self.tx() as db:
            self._owner(db, owner)
            db.execute('UPDATE owners SET covered=? WHERE id=?', (int(covered), owner))

    def poll(self, owner: str) -> bool:
        self.settle_local_actions(owner)
        with self.tx() as db:
            self._owner(db, owner)
            state = db.execute('SELECT * FROM control').fetchone()
            if state['closed']:
                db.execute('UPDATE owners SET ack=?,ack_at=? WHERE id=?', (state['generation'], now(), owner))
            db.execute('INSERT OR REPLACE INTO censuses VALUES(?,?,?)', (owner, state['generation'], now()))
            db.execute('DELETE FROM observer_faults WHERE owner=?', (owner,))
            return bool(state['closed'])

    def observer_failed(self, owner: str) -> None:
        # 独立于资源coverage：一次poll失败不能抹掉/补签资源清点结论。
        with self.tx() as db:
            if db.execute('SELECT 1 FROM owners WHERE id=?', (token(owner),)).fetchone() is None:
                raise ValueError('unknown observer')
            db.execute('INSERT OR REPLACE INTO observer_faults VALUES(?,?)', (owner, now()))

    def admit(self, owner: str, work: str, *, transferable: bool = False) -> str:
        token(work)
        with self.tx() as db:
            self._owner(db, owner)
            state = db.execute('SELECT * FROM control').fetchone()
            if db.execute('SELECT 1 FROM local_owners WHERE owner=?', (owner,)).fetchone():
                # 重启不会退休旧动作；跨owner/两种图入口共用同一原子work边界。
                if db.execute("SELECT 1 FROM jobs JOIN local_actions ON local_actions.job=jobs.id "
                              "WHERE jobs.work=? AND jobs.state!='finished' "
                              "AND jobs.id NOT IN (SELECT job FROM resolutions)", (work,)).fetchone():
                    if not state['closed']:
                        raise ValueError('previous local action unresolved')
            # 非本机动作保留原同 run 续跑合同；TS 回调须另判新工作。
            prior = db.execute("SELECT * FROM jobs WHERE owner=? AND work=? AND state='active'", (owner, work)).fetchone()
            if prior:
                local_action = db.execute('SELECT 1 FROM local_actions WHERE job=?', (prior['id'],)).fetchone()
                if not local_action:
                    if transferable:
                        raise ValueError('reservation already active')
                    return prior['id']
                # TS work 是新回调，不是原执行的续跑；失败的收尾 RPC 不授予新派发权。
                if not state['closed']:
                    raise ValueError('previous local action unresolved')
            if state['closed']:
                # 拒绝与关闭确认一起提交，不能被异常 rollback 吃掉。
                db.execute('UPDATE owners SET ack=?,ack_at=? WHERE id=?', (state['generation'], now(), owner))
                job = None
            else:
                job = uuid.uuid4().hex
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                           (job, owner, work, state['generation'], now(), None, 'active', int(transferable)))
                db.execute('INSERT INTO lineage VALUES(?,?)', (job, owner))
                epoch = db.execute('SELECT host,boot FROM local_owners WHERE owner=?', (owner,)).fetchone()
                if epoch is not None:
                    db.execute('INSERT INTO local_actions VALUES(?,?,?,?)', (job, owner, *epoch))
        if job is None:
            raise Closed('maintenance closed')
        return job

    def reserve_local_resource(self, owner: str, job: str) -> str:
        resource = uuid.uuid4().hex
        with self.tx() as db:
            self._owner(db, owner)
            row = db.execute("SELECT 1 FROM jobs JOIN local_actions ON local_actions.job=jobs.id WHERE jobs.id=? AND jobs.owner=? AND jobs.state='active' AND NOT EXISTS (SELECT 1 FROM action_exits WHERE action_exits.job=jobs.id)", (token(job), owner)).fetchone()
            if row is None:
                raise ValueError('missing local action')
            db.execute('INSERT INTO local_resources(id,job) VALUES(?,?)', (resource, job))
        return resource

    def bind_local_resource_identity(self, resource: str) -> None:
        """先登记唯一监督器；此时未允许调用 Popen 或声明进程域闭合。"""
        pid = os.getpid()
        host, boot = local_epoch()
        start, sid = identity(pid), os.getsid(0)
        if sid != pid:
            raise ValueError('supervisor must own session')
        with self.tx() as db:
            row = db.execute("SELECT jobs.owner,local_actions.host,local_actions.boot FROM local_resources JOIN jobs ON jobs.id=local_resources.job JOIN local_actions ON local_actions.job=jobs.id WHERE local_resources.id=? AND local_resources.pid IS NULL AND jobs.state='active'", (token(resource),)).fetchone()
            if row is None or (row['host'], row['boot']) != (host, boot):
                raise ValueError('resource binding unavailable')
            self._owner(db, row['owner'])
            db.execute('UPDATE local_resources SET host=?,boot=?,pid=?,start=?,sid=? WHERE id=?',
                       (host, boot, pid, start, sid, resource))

    def bind_local_resource(self, resource: str, *, subreaper: bool = False) -> None:
        from pilot1742.maintenance_processes import stable_snapshot
        self.bind_local_resource_identity(resource)
        pid = os.getpid()
        # 先绑定监督身份，再采集基线；基线失败时尚未执行 Popen，可留下精确未派发证据。
        if subreaper:
            from pilot1742.maintenance_subreaper import bind
            baseline = bind()
            supervisor = baseline['birth']
        else:
            baseline = stable_snapshot()
            supervisor = baseline[pid][0]
        with self.tx() as db:
            if db.execute('SELECT 1 FROM local_resource_not_started WHERE resource=?', (resource,)).fetchone():
                raise ValueError('resource dispatch cancelled')
            db.execute('INSERT INTO local_resource_domains VALUES(?,?,?,NULL)',
                       (resource, json.dumps(baseline), supervisor))

    def local_resource_not_started(self, resource: str, *, exec_failed: bool = False, cancelled: bool = False) -> None:
        """原监督器证明基线失败或 Popen 同步抛 OSError（未 exec 且内部子进程已回收）。"""
        with self.tx() as db:
            row = db.execute('SELECT * FROM local_resources WHERE id=?', (token(resource),)).fetchone()
            if (row is None or row['pid'] != os.getpid() or row['start'] != identity(os.getpid())
                    or (row['host'], row['boot']) != local_epoch() or row['waited_at'] is not None
                    or bool(db.execute('SELECT 1 FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()) != (exec_failed or cancelled)):
                raise ValueError('resource may have dispatched')
            db.execute('INSERT OR IGNORE INTO local_resource_not_started VALUES(?,?,?,?,?)',
                       (resource, row['pid'], row['start'], 'cancelled_before_spawn' if cancelled else 'exec_failed' if exec_failed else 'baseline_unavailable', now()))

    def local_resource_waited(self, resource: str, child_pid: int, code: int) -> None:
        if type(child_pid) is not int or child_pid < 1 or type(code) is not int:
            raise ValueError('invalid native wait')
        with self.tx() as db:
            row = db.execute('SELECT * FROM local_resources WHERE id=?', (token(resource),)).fetchone()
            if (row is None or row['pid'] != os.getpid() or row['start'] != identity(os.getpid())
                    or (row['host'], row['boot']) != local_epoch() or row['waited_at'] is not None
                    or not db.execute('SELECT 1 FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()):
                raise ValueError('wrong resource supervisor')
            db.execute('UPDATE local_resources SET child_pid=?,code=?,waited_at=? WHERE id=?',
                       (child_pid, code, now(), resource))

    def local_action_idle(self, job: str) -> bool:
        from pilot1742.maintenance_local import resources_idle
        with self.tx() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM local_resources WHERE job=?', (job,))]
            for row in rows:
                domain = db.execute('SELECT * FROM local_resource_domains WHERE resource=?', (row['id'],)).fetchone()
                row['domain'] = dict(domain) if domain else None
                row['not_started'] = bool(db.execute('SELECT 1 FROM local_resource_not_started WHERE resource=? AND pid=? AND start=?',
                                                    (row['id'], row['pid'], row['start'])).fetchone())
        # 只消费原native表的既存认证闭包；offline/旧epoch/不完整证据均不能补签。
        for row in rows:
            domain = row['domain']
            if domain and not domain['sealed_at'] and json.loads(domain['baseline']).get('kind') == 'macos-es-v1':
                from pilot1742.maintenance_es_session import settle_native_resource
                if settle_native_resource(self, row['id']):
                    domain['sealed_at'] = now()
                    row['waited_at'] = now()
        return resources_idle(rows)

    def seal_local_resource(self, resource: str) -> None:
        with self.tx() as db:
            row = db.execute('SELECT * FROM local_resources WHERE id=?', (token(resource),)).fetchone()
            if row is None or row['pid'] != os.getpid() or row['start'] != identity(os.getpid()):
                raise ValueError('wrong resource supervisor')
            domain = db.execute('SELECT * FROM local_resource_domains WHERE resource=?', (resource,)).fetchone()
            proof = dict(row, domain=dict(domain) if domain else None)
        from pilot1742.maintenance_local import resources_idle
        diagnostics: list[str] = []
        settled = resources_idle([proof], diagnostics)
        with self.tx() as db:
            if settled:
                db.execute('UPDATE local_resource_domains SET sealed_at=? WHERE resource=?', (now(), resource))
            else:
                db.execute('INSERT OR REPLACE INTO local_resource_diagnostics VALUES(?,?,?)',
                           (resource, diagnostics[0], now()))

    def settle_local_actions(self, owner: str) -> None:
        with self.tx() as db:
            self._owner(db, owner)
            jobs = [r[0] for r in db.execute("SELECT jobs.id FROM jobs JOIN action_exits ON action_exits.job=jobs.id WHERE jobs.owner=? AND jobs.state='unknown' AND action_exits.opaque_clear=1 AND jobs.id NOT IN (SELECT job FROM resolutions)", (owner,))]
        for job in jobs:
            if self.local_action_idle(job):
                with self.tx() as db:
                    self._owner(db, owner)
                    generation = db.execute('SELECT generation FROM control').fetchone()[0]
                    db.execute('INSERT OR IGNORE INTO resolutions VALUES(?,?,?,?)',
                               (job, 'local-session-ended', generation, now()))

    def action_exited(self, owner: str, job: str, *, opaque_clear: bool) -> bool:
        with self.tx() as db:
            row = self._owner(db, owner)
            task = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (token(job), owner)).fetchone()
            if (task is None or row['lane'] not in ('decision', 'wayfinder')
                    or not db.execute('SELECT 1 FROM local_actions WHERE job=? AND owner=?', (job, owner)).fetchone()):
                raise ValueError('missing active local action')
            db.execute('INSERT INTO action_exits VALUES(?,?,?,?,?,?,?)',
                       (job, owner, task['generation'], row['pid'], row['start'], int(opaque_clear), now()))
        settled = opaque_clear and self.local_action_idle(job)
        if settled:
            self.returned_action(owner, job)
        return settled

    def spawn_exited(self, owner: str, job: str, pid: int, code: int) -> bool:
        """旧PID/退出码接口没有资源域证据，不能取消或清除sighting。"""
        return False

    def prepare_spawn(self, parent: str, job: str, pid: int) -> str:
        """仅供受控无fork bootstrap：放行前绑定身份并原子转交原reservation。"""
        start, child = identity(pid), uuid.uuid4().hex
        host, boot = local_epoch()
        with self.tx() as db:
            row = self._owner(db, parent)
            task = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active' AND transferable=1",
                              (token(job), parent)).fetchone()
            if task is None or row['lane'] != 'review':
                raise ValueError('missing review reservation')
            db.execute('INSERT INTO owners(id,lane,pid,start,registered_at,ack) VALUES(?,?,?,?,?,?)',
                       (child, 'review', pid, start, now(), -1))
            db.execute('UPDATE jobs SET owner=?,transferable=0 WHERE id=?', (child, job))
            db.execute('INSERT INTO lineage VALUES(?,?)', (job, child))
            db.execute('INSERT INTO spawn_launches VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL)',
                       (job, parent, child, host, boot, pid, start, 'review-bootstrap-v1', now()))
        return child

    def release_spawn(self, parent: str, job: str) -> None:
        # 先持久消费，再写一次GO；写失败不能把可能已放行的程序降为未启动。
        with self.tx() as db:
            self._owner(db, parent)
            row = db.execute('SELECT * FROM spawn_launches WHERE job=? AND parent=?', (token(job), parent)).fetchone()
            if (row is None or row['released_at'] or (row['host'], row['boot']) != local_epoch()
                    or not alive(row['pid'], row['start'])):
                raise ValueError('spawn identity unavailable or already released')
            db.execute('UPDATE spawn_launches SET released_at=? WHERE job=?', (now(), job))

    def cancel_unstarted(self, owner: str, job: str, reason: str) -> None:
        """只能由尚持有任务的启动方证明未启动；adopt 与撤销竞争同一事务。"""
        if reason not in ('spawn_failed', 'preflight_return'):
            raise ValueError('invalid cancellation')
        with self.tx() as db:
            self._owner(db, owner)
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (token(job), owner)).fetchone()
            if row is None or db.execute('SELECT 1 FROM witnesses WHERE job=?', (job,)).fetchone():
                raise ValueError('work already started')
            if reason == 'preflight_return' and db.execute('SELECT 1 FROM bindings WHERE job=?', (job,)).fetchone():
                raise ValueError('work already bound')
            db.execute('INSERT INTO cancellations VALUES(?,?,?,?)', (job, owner, reason, now()))
            db.execute("UPDATE jobs SET state='finished',ended_at=? WHERE id=?", (now(), job))

    def has_execution(self, ticket: int, state_root: Path) -> bool:
        with self.tx() as db:
            return any(json.loads(r['data']).get('state_root') == str(state_root.resolve())
                       for r in db.execute("SELECT data FROM bindings JOIN jobs ON jobs.id=bindings.job "
                           "WHERE work=? AND state!='finished' AND jobs.id NOT IN (SELECT job FROM resolutions)",
                           (f'ticket:{ticket}',)))

    def admit_executor(self, owner: str, run_id: str, ticket: int, state_root: Path, source_repo: Path, *, manual: bool = False) -> str:
        """按真实 run 原子领取并绑定；未派发的计划票不获得跨关闭许可。"""
        data = json.dumps(dict(kind='executor', run_id=token(run_id), work=f'ticket:{ticket}',
                              state_root=str(state_root.resolve()), source_repo=str(source_repo.resolve())), sort_keys=True)
        with self.tx() as db:
            self._owner(db, owner)
            previous = db.execute("SELECT jobs.* FROM jobs JOIN bindings ON bindings.job=jobs.id "
                "WHERE bindings.data=? AND state!='finished' AND jobs.id NOT IN (SELECT job FROM resolutions)", (data,)).fetchone()
            if previous:
                if previous['owner'] != owner:
                    old = db.execute('SELECT * FROM owners WHERE id=?', (previous['owner'],)).fetchone()
                    if not old['stopped'] and alive(old['pid'], old['start']):
                        if manual:
                            # 手动续跑保留 serve 的任务所有权；start_bound 原子拒绝并行控制器。
                            return previous['id']
                        raise ValueError('executor owner still active')
                    if any(alive(w['pid'], w['start']) for w in db.execute('SELECT * FROM witnesses WHERE job=? AND id NOT IN (SELECT witness FROM returns)', (previous['id'],))):
                        raise ExecutorBusy('executor controller still active')
                    db.execute('UPDATE jobs SET owner=? WHERE id=?', (owner, previous['id']))
                    db.execute('INSERT OR IGNORE INTO lineage VALUES(?,?)', (previous['id'], owner))
                return previous['id']
            state = db.execute('SELECT * FROM control').fetchone()
            if state['closed']:
                raise Closed('maintenance closed')
            job = uuid.uuid4().hex
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,0)',
                       (job, owner, f'ticket:{ticket}', state['generation'], now(), None, 'active'))
            db.execute('INSERT INTO lineage VALUES(?,?)', (job, owner))
            db.execute('INSERT INTO bindings VALUES(?,?)', (job, data))
            return job

    @staticmethod
    def _chain_complete(witnesses, returned, recoveries) -> bool:
        by_id = {w['id']: w for w in witnesses}
        def complete(w, seen):
            if w['id'] in returned:
                return True
            successor = by_id.get(recoveries.get(w['id']))
            return (w['id'] not in seen and not alive(w['pid'], w['start']) and successor is not None
                    and successor['completed_at'] is not None and complete(successor, seen | {w['id']}))
        return bool(witnesses) and all(complete(w, set()) for w in witnesses)

    def settle_bound(self, owner: str, job: str) -> bool:
        """业务失败同样可收尾，但必须有入口返回链和资源终态，退出码不是证明。"""
        with self.tx() as db:
            self._owner(db, owner)
            task = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state!='finished'", (job, owner)).fetchone()
            if task is None:
                return False
            binding = db.execute('SELECT data FROM bindings WHERE job=?', (job,)).fetchone()
            chain = [dict(r) for r in db.execute('SELECT * FROM witnesses WHERE job=?', (job,))]
            returned = {r[0] for r in db.execute('SELECT witness FROM returns')}
            recoveries = dict(db.execute('SELECT previous,successor FROM recoveries'))
            preflight = {r[0] for r in db.execute('SELECT witness FROM preflight_returns')}
        if not binding or not self._chain_complete(chain, returned, recoveries):
            return False
        try:
            if not self._resources_idle(json.loads(binding['data']), chain, preflight):
                return False
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
            return False
        with self.tx() as db:
            self._owner(db, owner)
            if ([dict(r) for r in db.execute('SELECT * FROM witnesses WHERE job=?', (job,))] != chain
                    or dict(db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()) != dict(task)):
                return False
            if task['state'] == 'unknown':
                generation = db.execute('SELECT generation FROM control').fetchone()[0]
                db.execute('INSERT OR IGNORE INTO resolutions VALUES(?,?,?,?)', (job, chain[-1]['id'], generation, now()))
            else:
                db.execute("UPDATE jobs SET state='finished',ended_at=? WHERE id=?", (now(), job))
        return True

    def finish_review(self, owner: str, job: str) -> None:
        with self.tx() as db:
            bound = db.execute('SELECT 1 FROM bindings WHERE job=?', (job,)).fetchone()
        if not bound:
            self.cancel_unstarted(owner, job, 'preflight_return')
        elif not self.settle_bound(owner, job):
            self.finish(owner, job, natural=False)

    def finish(self, owner: str, job: str, *, natural: bool) -> None:
        with self.tx() as db:
            self._owner(db, owner)
            result = db.execute("UPDATE jobs SET state=?,ended_at=? WHERE id=? AND owner=? AND (state='active' OR (state='unknown' AND ?=0))",
                                ('finished' if natural else 'unknown', now(), token(job), owner, int(natural)))
            if result.rowcount != 1:
                raise ValueError('job not active for owner')

    def adopt(self, job: str, lane: str) -> str:
        """子进程继承已领取任务，转交与新 owner 登记同事务，无不计数间隙。"""
        if lane not in LANES:
            raise ValueError('invalid lane')
        pid, start, owner = os.getpid(), identity(os.getpid()), uuid.uuid4().hex
        with self.tx() as db:
            prepared = db.execute('SELECT * FROM spawn_launches WHERE job=?', (token(job),)).fetchone()
            if prepared is not None:
                task = db.execute("SELECT * FROM jobs WHERE id=? AND state='active'", (job,)).fetchone()
                if (task is None or lane != 'review' or task['owner'] != prepared['owner']
                        or prepared['pid'] != pid or prepared['start'] != start
                        or (prepared['host'], prepared['boot']) != local_epoch()
                        or not prepared['released_at'] or prepared['confirmed_at']):
                    raise ValueError('spawn binding mismatch or already adopted')
                db.execute('UPDATE spawn_launches SET confirmed_at=? WHERE job=?', (now(), job))
                return prepared['owner']
            row = db.execute("SELECT * FROM jobs WHERE id=? AND state='active' AND transferable=1", (token(job),)).fetchone()
            if row is None:
                raise ValueError('missing active reservation')
            parent = db.execute('SELECT * FROM owners WHERE id=?', (row['owner'],)).fetchone()
            if parent['lane'] != lane:
                raise ValueError('reservation lane mismatch')
            db.execute('INSERT INTO owners(id,lane,pid,start,registered_at,ack) VALUES(?,?,?,?,?,?)',
                       (owner, lane, pid, start, now(), -1))
            db.execute('UPDATE jobs SET owner=?,transferable=0 WHERE id=?', (owner, job))
            db.execute('INSERT INTO lineage VALUES(?,?)', (job, owner))
        return owner

    def abort_initialization(self, owner: str) -> None:
        """撤销尚未交付的空 owner；保留历史，不声称已清点任何资源域。"""
        with self.tx() as db:
            self._owner(db, owner)
            if any(db.execute(f'SELECT 1 FROM {table} WHERE owner=?', (owner,)).fetchone()
                   for table in ('lineage', 'scopes', 'censuses', 'local_owners')):
                raise ValueError('owner already published or accepted work')
            db.execute('UPDATE owners SET stopped=1,ack=-1,ack_at=? WHERE id=?', (now(), owner))

    def stop(self, owner: str) -> None:
        with self.tx() as db:
            self._owner(db, owner)
            state = db.execute('SELECT * FROM control').fetchone()
            db.execute('UPDATE owners SET stopped=1,ack=?,ack_at=? WHERE id=?',
                       (state['generation'] if state['closed'] else -1, now(), owner))

    def request(self) -> int:
        with self.tx() as db:
            state = db.execute('SELECT * FROM control').fetchone()
            if not state['closed']:
                db.execute('UPDATE control SET closed=1,generation=generation+1,requested_at=?', (now(),))
            return db.execute('SELECT generation FROM control').fetchone()[0]

    def resume(self, generation: int) -> None:
        if type(generation) is not int or generation < 1:
            raise ValueError('invalid generation')
        with self.tx() as db:
            state = db.execute('SELECT * FROM control').fetchone()
            if not state['closed'] or state['generation'] != generation:
                raise ValueError('maintenance generation mismatch')
            db.execute('UPDATE control SET closed=0')

    def bind_executor(self, owner: str, job: str, run_id: str, state_root: Path, source_repo: Path) -> None:
        """派工前写一次绑定；不接受事后给旧任务附加任意回执。"""
        with self.tx() as db:
            self._owner(db, owner)
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (job, owner)).fetchone()
            if row is None:
                raise ValueError('unbound job')
            data = json.dumps(dict(kind='executor', run_id=token(run_id), work=row['work'],
                                   state_root=str(state_root.resolve()), source_repo=str(source_repo.resolve())), sort_keys=True)
            previous = db.execute('SELECT data FROM bindings WHERE job=?', (job,)).fetchone()
            if previous and previous['data'] != data:
                raise ValueError('binding changed')
            db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?)', (job, data))

    def bind_review(self, owner: str, job: str, target: dict, state_root: Path, source_repo: Path) -> None:
        with self.tx() as db:
            self._owner(db, owner)
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (job, owner)).fetchone()
            if row is None:
                raise ValueError('unbound review')
            expected = f"pr:{target['pr_number']}:{target['head_sha']}:{target['attempt']}"
            if row['work'] not in (expected, 'manual-review'):
                raise ValueError('review target mismatch')
            data = json.dumps(dict(kind='review', run_id=token(target['run_id']), target=target,
                                   state_root=str(state_root.resolve()), source_repo=str(source_repo.resolve())), sort_keys=True)
            previous = db.execute('SELECT data FROM bindings WHERE job=?', (job,)).fetchone()
            if previous and previous['data'] != data:
                raise ValueError('binding changed')
            db.execute('INSERT OR IGNORE INTO bindings VALUES(?,?)', (job, data))

    def bind_scope(self, owner: str, state_root: Path, source_repo: Path, *, kind: str = "executor") -> None:
        if kind not in ('executor', 'review'):
            raise ValueError('invalid scope')
        with self.tx() as db:
            self._owner(db, owner)
            data = json.dumps(dict(kind=kind, state_root=str(state_root.resolve()), source_repo=str(source_repo.resolve())), sort_keys=True)
            previous = db.execute('SELECT data FROM scopes WHERE owner=?', (owner,)).fetchone()
            if previous and previous['data'] != data:
                raise ValueError('scope changed')
            db.execute('INSERT OR IGNORE INTO scopes VALUES(?,?)', (owner, data))

    def start_bound(self, job: str, run_id: str, state_root: Path) -> str:
        pid, start, witness = os.getpid(), identity(os.getpid()), uuid.uuid4().hex
        with self.tx() as db:
            row = db.execute('SELECT data FROM bindings WHERE job=?', (token(job),)).fetchone()
            if row is None:
                raise ValueError('missing binding')
            binding = json.loads(row['data'])
            task = db.execute('SELECT * FROM jobs WHERE id=?', (job,)).fetchone()
            if (task['state'] not in ('active', 'unknown') or binding['run_id'] != run_id
                    or binding['state_root'] != str(state_root.resolve())
                    or db.execute('SELECT 1 FROM resolutions WHERE job=?', (job,)).fetchone()
                    or db.execute('SELECT 1 FROM reconciliations WHERE owner=?', (task['owner'],)).fetchone()):
                raise ValueError('invalid executor binding')
            previous = list(db.execute('SELECT * FROM witnesses WHERE job=? AND id NOT IN (SELECT witness FROM returns)', (job,)))
            if previous and (binding['kind'] != 'executor' or any(alive(w['pid'], w['start']) for w in previous)):
                raise ExecutorBusy('previous executor unresolved')
            db.execute('INSERT INTO witnesses VALUES(?,?,?,?,?,NULL)', (witness, job, pid, start, now()))
            for old in previous:
                db.execute('INSERT OR REPLACE INTO recoveries VALUES(?,?)', (old['id'], witness))
        return witness

    def returned_action(self, owner: str, job: str) -> None:
        """TS 同步/await 动作正常返回的窄记录；失联后不能补签。"""
        with self.tx() as db:
            source = self._owner(db, owner)
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=? AND state='active'", (token(job), owner)).fetchone()
            if row is None or source['lane'] not in ('decision', 'wayfinder'):
                raise ValueError('invalid action receipt')
            db.execute('INSERT OR IGNORE INTO action_returns VALUES(?,?,?,?,?,?)',
                       (job, owner, row['generation'], source['pid'], source['start'], now()))

    def returned(self, witness: str) -> None:
        """执行入口已返回，不等于资源已结束；只能由预先登记的同一进程写入。"""
        with self.tx() as db:
            row = db.execute('SELECT * FROM witnesses WHERE id=?', (token(witness),)).fetchone()
            if row is None or row['pid'] != os.getpid() or row['start'] != identity(os.getpid()):
                raise ValueError('wrong witness identity')
            db.execute('INSERT OR IGNORE INTO returns VALUES(?,?)', (witness, now()))

    def returned_preflight(self, witness: str) -> None:
        """执行入口在进入 run 生命周期之前返回；由同一预登记身份写入。"""
        self.returned(witness)
        with self.tx() as db:
            db.execute('INSERT OR IGNORE INTO preflight_returns VALUES(?,?)', (token(witness), now()))

    @staticmethod
    def _resources_idle(binding, chain, preflight) -> bool:
        from pilot1742.maintenance_recovery import bound_idle, executor_preflight_idle
        if chain and all(w['id'] in preflight for w in chain) and binding['kind'] == 'executor':
            return executor_preflight_idle(binding)
        return bound_idle(binding)

    def returned_current(self, job: str) -> None:
        with self.tx() as db:
            ids = [r['id'] for r in db.execute('SELECT id FROM witnesses WHERE job=? AND pid=? AND start=?',
                                               (token(job), os.getpid(), identity(os.getpid())))]
        for witness in ids:
            self.returned(witness)

    def complete_bound(self, witness: str) -> None:
        self.returned(witness)
        from pilot1742.maintenance_recovery import bound_idle
        with self.tx() as db:
            row = db.execute('SELECT * FROM witnesses WHERE id=?', (token(witness),)).fetchone()
            binding = json.loads(db.execute('SELECT data FROM bindings WHERE job=?', (row['job'],)).fetchone()['data'])
        if row['pid'] != os.getpid() or row['start'] != identity(os.getpid()) or not bound_idle(binding):
            raise ValueError('executor not naturally closed')
        with self.tx() as db:
            db.execute('UPDATE witnesses SET completed_at=? WHERE id=? AND completed_at IS NULL', (now(), witness))

    def settle_current_executor(self, witness: str) -> None:
        """手动控制器收尾；可属于仍运行的 serve，但必须是本进程的精确 witness。"""
        self.returned(witness)
        with self.tx() as db:
            row = db.execute('SELECT jobs.id,jobs.owner FROM jobs JOIN witnesses ON jobs.id=witnesses.job '
                             'WHERE witnesses.id=?', (token(witness),)).fetchone()
        if not self.settle_bound(row['owner'], row['id']):
            with self.tx() as db:
                # serve 可并发完成同一任务；不把已完成或已转交的任务改回 unknown。
                db.execute("UPDATE jobs SET state='unknown',ended_at=? WHERE id=? AND owner=? AND state='active'",
                           (now(), row['id'], row['owner']))

    def reconcile(self, generation: int, owner: str) -> dict:
        """只处理精确 owner；读取证据在事务外，提交前重验关闭代次并永久 fence 旧 owner。"""
        from pilot1742.maintenance_recovery import scope_idle
        with self.tx() as db:
            control = db.execute('SELECT * FROM control').fetchone()
            if type(generation) is not int or not control['closed'] or control['generation'] != generation:
                raise ValueError('generation mismatch')
            row = db.execute('SELECT * FROM owners WHERE id=?', (token(owner),)).fetchone()
            if row is None:
                raise ValueError('missing owner')
            prior = db.execute('SELECT generation FROM reconciliations WHERE owner=?', (owner,)).fetchone()
            if prior:
                return {'owner': owner, 'generation': prior['generation'], 'result': 'reconciled'}
            jobs = [dict(r) for r in db.execute('SELECT * FROM jobs WHERE id IN (SELECT job FROM lineage WHERE owner=?)', (owner,))]
            bindings = {r['job']: json.loads(r['data']) for r in db.execute('SELECT * FROM bindings')}
            witnesses = [dict(r) for r in db.execute('SELECT * FROM witnesses')]
            returned = {r['witness'] for r in db.execute('SELECT * FROM returns')}
            recoveries = dict(db.execute('SELECT previous,successor FROM recoveries'))
            preflight = {r[0] for r in db.execute('SELECT witness FROM preflight_returns')}
            actions = {r['job']: dict(r) for r in db.execute('SELECT * FROM action_returns')}
            exits = {r['job']: dict(r) for r in db.execute('SELECT * FROM action_exits')}
            epoch = db.execute('SELECT host,boot FROM local_owners WHERE owner=?', (owner,)).fetchone()
            action_epochs = {r['job']: dict(r) for r in db.execute('SELECT * FROM local_actions WHERE owner=?', (owner,))}
            scope = db.execute('SELECT data FROM scopes WHERE owner=?', (owner,)).fetchone()
            census = db.execute('SELECT 1 FROM censuses WHERE owner=?', (owner,)).fetchone()
        def unknown(reason):
            return {'owner': owner, 'generation': generation, 'result': 'unknown', 'reason': reason}
        current_epoch = local_epoch() if epoch is not None else None
        retired_epoch = (epoch is not None and current_epoch is not None
                         and epoch['host'] == current_epoch[0] and epoch['boot'] != current_epoch[1])
        if not retired_epoch and alive(row['pid'], row['start']):
            return unknown('owner_alive')
        # 任务未登记/旧版本没有绑定，不允许从磁盘补一份任意 receipt 解锁。
        verified = []
        for job in jobs:
            if job['state'] == 'finished':
                continue
            origin = action_epochs.get(job['id'])
            if (retired_epoch and row['lane'] in ('decision', 'wayfinder') and job['id'] not in bindings
                    and origin is not None and origin['host'] == epoch['host'] and origin['boot'] == epoch['boot']):
                verified.append((job['id'], 'local-boot-ended'))
                continue
            exit_record = exits.get(job['id'])
            if (exit_record and exit_record['owner'] == owner and exit_record['generation'] == job['generation']
                    and exit_record['pid'] == row['pid'] and exit_record['start'] == row['start']
                    and exit_record['opaque_clear'] == 1 and self.local_action_idle(job['id'])):
                verified.append((job['id'], 'local-session-ended'))
                continue
            receipt = actions.get(job['id'])
            if (receipt and receipt['owner'] == owner and receipt['generation'] == job['generation']
                    and receipt['pid'] == row['pid'] and receipt['start'] == row['start']):
                verified.append((job['id'], 'action-return'))
                continue
            chain = [w for w in witnesses if w['job'] == job['id']]
            if (not self._chain_complete(chain, returned, recoveries) or any(alive(w['pid'], w['start']) for w in chain)
                    or job['id'] not in bindings):
                return unknown('missing_bound_completion')
            try:
                if not self._resources_idle(bindings[job['id']], chain, preflight):
                    return unknown('resources_unsettled')
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
                return unknown('resources_unverified')
            verified.append((job['id'], chain[-1]['id']))
        if scope:
            try:
                if not scope_idle(json.loads(scope['data'])):
                    return unknown('resources_unsettled')
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError):
                return unknown('resources_unverified')
        elif not row['covered'] or (not jobs and row['ack'] != generation and not census):
            return unknown('missing_scope_checkpoint')
        with self.tx() as db:
            current = db.execute('SELECT * FROM control').fetchone()
            if not current['closed'] or current['generation'] != generation:
                raise ValueError('generation changed')
            if ([dict(r) for r in db.execute('SELECT * FROM jobs WHERE id IN (SELECT job FROM lineage WHERE owner=?)', (owner,))] != jobs
                    or [dict(r) for r in db.execute('SELECT * FROM witnesses')] != witnesses
                    or {r['witness'] for r in db.execute('SELECT * FROM returns')} != returned
                    or dict(db.execute('SELECT previous,successor FROM recoveries')) != recoveries
                    or {r[0] for r in db.execute('SELECT witness FROM preflight_returns')} != preflight):
                return unknown('evidence_changed')
            # 死亡身份不能重新领取；所有正常写入口也检查 fence。历史 job/owner 不改写。
            if current_epoch is not None and local_epoch() != current_epoch:
                return unknown('local_epoch_changed')
            if not retired_epoch and alive(row['pid'], row['start']):
                return unknown('owner_alive')
            for job, witness in verified:
                db.execute('INSERT OR IGNORE INTO resolutions VALUES(?,?,?,?)', (job, witness, generation, now()))
                if witness == 'local-boot-ended':
                    assert current_epoch is not None and epoch is not None
                    db.execute('INSERT OR IGNORE INTO epoch_resolutions VALUES(?,?,?,?,?,?)',
                               (job, epoch['host'], epoch['boot'], current_epoch[1], generation, now()))
            db.execute('INSERT OR IGNORE INTO reconciliations VALUES(?,?,?)', (owner, generation, now()))
        return {'owner': owner, 'generation': generation, 'result': 'reconciled'}

    def reconcile_sighting(self, generation: int, lane: str, pid: int, start: str) -> dict:
        """只消费账本内原始身份绑定及既有严格 reconcile；不接受人工终态。"""
        result = dict(lane=lane, pid=pid, start=start, generation=generation, result='unknown')
        with self.tx() as db:
            control = db.execute('SELECT * FROM control').fetchone()
            if not control['closed'] or control['generation'] != generation:
                raise ValueError('generation mismatch')
            if not db.execute('SELECT 1 FROM sightings WHERE lane=? AND pid=? AND start=?', (lane, pid, start)).fetchone():
                raise ValueError('missing sighting')
            candidates = {r[0] for r in db.execute('SELECT id FROM owners WHERE lane=? AND pid=? AND start=?', (lane, pid, start))}
            candidates.update(r[0] for r in db.execute(
                'SELECT DISTINCT jobs.owner FROM witnesses JOIN jobs ON jobs.id=witnesses.job '
                'JOIN owners ON owners.id=jobs.owner WHERE owners.lane=? AND witnesses.pid=? AND witnesses.start=?',
                (lane, pid, start)))
        if not candidates:
            return dict(result, reason='missing_original_identity_binding')
        for owner in sorted(candidates):
            proof = self.reconcile(generation, owner)
            if proof['result'] != 'reconciled':
                return dict(result, reason=proof['reason'])
        with self.tx() as db:
            control = db.execute('SELECT * FROM control').fetchone()
            if not control['closed'] or control['generation'] != generation:
                raise ValueError('generation changed')
            db.execute('INSERT OR IGNORE INTO sighting_resolutions VALUES(?,?,?,?,?,?)',
                       (lane, pid, start, generation, json.dumps(sorted(candidates)), now()))
        return dict(result, result='reconciled', owners=sorted(candidates))

    def status(self, inventory=None) -> dict:
        # inventory 是生产进程身份清单；测试注入固定清单，不靠时间/TTL。
        processes = process_inventory(self.root) if inventory is None else inventory
        with self.tx() as db:
            state = dict(db.execute('SELECT * FROM control').fetchone())
            owners = [dict(r) for r in db.execute('SELECT * FROM owners ORDER BY registered_at,id')]
            jobs = [dict(r) for r in db.execute("SELECT * FROM jobs WHERE state!='finished' AND id NOT IN (SELECT job FROM resolutions) ORDER BY started_at,id")]
            retired = {r['owner']: r['generation'] for r in db.execute('SELECT * FROM reconciliations')}
            witnesses = [dict(r) for r in db.execute('SELECT * FROM witnesses')]
            for lane, pid, start in processes:
                if not any(r['lane'] == lane and r['pid'] == pid and r['start'] == start for r in owners) and not any(
                        w['pid'] == pid and w['start'] == start for w in witnesses):
                    db.execute('INSERT OR IGNORE INTO sightings VALUES(?,?,?,?)', (lane, pid, start, now()))
            observer_faults = {r[0] for r in db.execute('SELECT owner FROM observer_faults')}
            sightings = [dict(r) for r in db.execute('SELECT * FROM sightings')]
            sighting_resolutions = [dict(r, owners=json.loads(r['owners'])) for r in db.execute('SELECT * FROM sighting_resolutions')]

        missing = []
        for lane in LANES:
            records = [r for r in owners if r['id'] not in retired and r['lane'] == lane and
                       (not r['stopped'] or r['ack'] == state['generation'])]
            confirmed = [r for r in records if r['ack'] == state['generation'] and
                         (r['stopped'] or alive(r['pid'], r['start']))]
            if not confirmed or any(r['id'] in observer_faults or not r['covered'] or r['ack'] != state['generation'] or
                                   (not r['stopped'] and not alive(r['pid'], r['start'])) for r in records):
                missing.append(lane)
        uncovered = [{'lane': r['lane'], 'pid': r['pid'], 'start': r['start'], 'observed_at': r['observed_at'],
                      'reason': 'missing_prelaunch_binding'} for r in sightings
                     if not any(o['lane'] == r['lane'] and o['pid'] == r['pid'] and o['start'] == r['start'] for o in owners)
                     and not any(w['pid'] == r['pid'] and w['start'] == r['start'] for w in witnesses)]
        for job in jobs:
            owner = next(r for r in owners if r['id'] == job['owner'])
            if owner['stopped'] or not alive(owner['pid'], owner['start']):
                job['state'] = 'unknown'
        mode = 'open' if not state['closed'] else ('unknown' if missing or uncovered or any(j['state'] == 'unknown' for j in jobs)
                else 'draining' if jobs else 'drained')
        return {'v': 1, 'generation': state['generation'], 'state': mode, 'requested_at': state['requested_at'],
                'observed_at': now(), 'unconfirmed': missing, 'uncovered': uncovered,
                'owners': [{k: r[k] for k in ('id', 'lane', 'pid', 'registered_at', 'ack', 'ack_at', 'stopped', 'covered')} for r in owners],
                'observer_faults': sorted(observer_faults), 'inflight': jobs, 'sighting_resolutions': sighting_resolutions, 'reconciled': [{'owner': key, 'generation': value} for key, value in retired.items()]}


def process_arguments(pid: int) -> list[str]:
    """读取原生 argv 边界，只返回 argv；不解析或输出环境区。"""
    if sys.platform.startswith('linux'):
        data = Path(f'/proc/{pid}/cmdline').read_bytes()
        if not data or not data.endswith(b'\0') or not data.split(b'\0', 1)[0]:
            raise ValueError('incomplete process argv')
        return [part.decode() for part in data[:-1].split(b'\0')]
    if sys.platform == 'darwin':
        import ctypes
        libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN / KERN_PROCARGS2
        size = ctypes.c_size_t()
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            raise OSError(ctypes.get_errno(), 'argv unavailable')
        if not 4 < size.value <= 8 * 1024 * 1024:
            raise ValueError('invalid argv size')
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            raise OSError(ctypes.get_errno(), 'argv unavailable')
        data = buffer.raw[:size.value]
        argc = int.from_bytes(data[:4], sys.byteorder, signed=True)
        if not 0 < argc < 100000:
            raise ValueError('invalid argc')
        offset = data.index(b'\0', 4) + 1  # executable path followed by padding
        while offset < len(data) and data[offset] == 0:
            offset += 1
        if offset == len(data):
            raise ValueError('missing argv')
        words = []
        for _ in range(argc):
            end = data.index(b'\0', offset)
            words.append(data[offset:end].decode())
            offset = end + 1
        return words
    raise OSError('native argv unavailable')



def python_entry(args: list[str]) -> tuple[str | None, list[str]]:
    """CPython interpreter switches, including clustered flags and attached values.

    An unrecognized switch is not proof that a visible target module is unrelated.
    -c/script/-- terminate interpreter-option parsing; their arguments are not modules.
    """
    original = args
    while args:
        arg, args = args[0], args[1:]
        if arg == '--check-hash-based-pycs':
            args = args[1:]
            continue
        if arg in ('--help', '--version', '--help-env', '--help-xoptions', '--help-all'):
            return None, []
        if not arg.startswith('-') or arg in ('-', '--'):
            return None, []
        flags = arg[1:]
        while flags:
            flag, flags = flags[0], flags[1:]
            if flag in 'bBdEiIOPqRsSuvx':
                continue
            if flag in 'hV?c':
                return None, []
            if flag in 'WXm':
                value = flags or (args.pop(0) if args else '')
                if flag == 'm':
                    return value, args
                break
            # Unknown interpreter syntax: preserve visible relevant module as unknown.
            for i, word in enumerate(original):
                if word == '-m' and i + 1 < len(original):
                    return original[i + 1], original[i + 2:]
            return None, []
    return None, []


def foreign_scope_bound(argv: list[str], lane: str, pid: int, start: str, root: Path) -> bool:
    """A root argument is only a hint; the original live owner is the scope proof.

    Old binaries can ignore new options. Never exclude them from argv alone.
    Only the unambiguous separate option is used as a lookup hint; equals/-- and
    strings consumed as values cannot prove scope. Missing/unreadable proof stays local.
    """
    # Known value-taking options from the four entry parsers; unknown options cannot
    # establish an external scope. The live identity record remains mandatory.
    values = {'--out', '--ticket', '--maps', '--concurrency', '--poll-seconds',
              '--state-root', '--drain-root', '--run-id', '--model-rules', '--workers-log',
              '--private-key', '--review-private-key', '--review-sweep-max-running',
              '--maintenance-job', '--maintenance-reservation', '--maintenance-es-config', '--crash-at', '--pr', '--attempt', '--expect-head',
              '--max-running', '--loop', '--reason', '--task', '--note'}
    switches = {'--live', '--dry-run', '--once', '--explain', '--archaeology-only',
                '--resume', '--recheck-approval', '--review-sweep', '--review-sweep-auto-merge', '--auto-merge'}
    if lane != 'review':
        values.remove('--loop')
        switches.add('--loop')
    entries = {'decision-claimer.mts', 'wayfinder_engine.mts', 'pilot1742.executor',
               'pilot1742.review_sweep', 'pilot1742.external_review'}
    entry = next((i for i, arg in enumerate(argv) if Path(arg).name in entries), None)
    if entry is None:
        return False
    argv = argv[entry + 1:]
    if argv and argv[0] in ('serve', 'run', 'run-review', 'review-pr', 'migrate-stale'):
        argv = argv[1:]
    scope = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == '--':
            return False
        if arg == '--maintenance-root':
            if i + 1 >= len(argv) or argv[i + 1].startswith('-'):
                return False
            scope = argv[i + 1]
            i += 2
        elif arg in values:
            i += 2
        elif arg in switches or ('=' in arg and arg.split('=', 1)[0] in values):
            i += 1
        else:
            return False  # 未核实的参数消费语义不能证明外域。
    if not scope or not Path(scope).is_absolute() or Path(scope).resolve() == root.resolve():
        return False
    path = Path(scope) / 'maintenance.sqlite3'
    try:
        db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            return db.execute('SELECT 1 FROM owners WHERE lane=? AND pid=? AND start=? AND stopped=0',
                              (lane, pid, start)).fetchone() is not None
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error):
        return False


def command_lanes(command: str, root: Path, argv: list[str] | None = None) -> list[str]:
    """只解析解释器实际入口/子命令；不扫描 reason、提示或参数值里的 run。"""
    try:
        words = shlex.split(command)
    except ValueError:
        # ps 不保证保留 argv quoting；无法解析仍按旧保守识别，绝不据此排除。
        words = command.split()
    if argv is not None:
        words = argv
    if not words:
        return []
    executable = Path(words[0]).name
    args = words[1:]
    module = None
    if re.fullmatch(r'(?:python[\d.]*|Python)', executable):
        module, args = python_entry(args)
    elif executable in ('node', 'tsx'):
        while args and args[0].startswith('-'):
            skip = 2 if args[0] in ('--import', '--loader', '--require', '-r', '--tsconfig') else 1
            args = args[skip:]
        if args and re.search(r'(?:tsx/(?:dist/)?cli\.mjs|node_modules/\.bin/tsx)$', args[0]):
            args = args[1:]
        if not args:
            return []
        module, args = Path(args[0]).name, args[1:]
    else:
        return []
    # argv 根参数不证明旧二进制实际消费它；外域排除另核原活 owner。
    if module == 'decision-claimer.mts':
        return ['decision']
    if module == 'wayfinder_engine.mts':
        modes = [a for a in args if a in ('--live', '--dry-run')]
        return ['wayfinder'] if modes and modes[-1] == '--live' and '--spec-ruling' not in args else []
    if module in ('pilot1742.executor', 'pilot1742.review_sweep', 'pilot1742.external_review') and any(a in ('--help', '-h') for a in args):
        return []
    if module == 'pilot1742.executor':
        # executor 全局选项都带单值；第一个位置参数才是子命令。
        i = 0
        while i < len(args) and args[i].startswith('-'):
            if args[i] in ('--state-root', '--drain-root'):
                i += 2
            elif args[i].startswith(('--state-root=', '--drain-root=')):
                i += 1
            else:
                return ['executor']  # 未识别选项不能证明旧入口没有执行（含 argparse 缩写）。
        return ['executor'] if i < len(args) and args[i] in ('serve', 'run') else []
    if module == 'pilot1742.review_sweep':
        return ['review']
    if module == 'pilot1742.external_review':
        return ['review'] if args and args[0] in ('review-pr', 'migrate-stale') else []
    return []


def process_inventory(root: Path = ROOT) -> list[tuple[str, int, str]]:
    output = subprocess.run(['ps', '-axo', 'pid=,ppid=,args='], check=True, capture_output=True, text=True).stdout
    result: list[tuple[str, int, str]] = []
    parents = {}
    wrappers = set()
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid, parent, command = int(parts[0]), int(parts[1]), parts[2]
        parents[pid] = parent
        # 不输出完整命令（可能含提示或秘密）。仅识别真实解释器入口，不匹配 shell 提示文本。
        if not re.match(r'\S*(?:python[\d.]*|Python|node|tsx)\s', command):
            continue
        if re.match(r'\S*node\s+\S*/(?:tsx/(?:dist/)?cli\.mjs|node_modules/\.bin/tsx)(?:\s|$)', command):
            wrappers.add(pid)
        # 作用域排除必须依据内核 argv 边界，不把 reason 字符串里的旗标当成真正选项。
        argv = None
        if '--maintenance-root' in command:
            first_start = identity(pid)
            argv = process_arguments(pid)
            if identity(pid) != first_start:
                raise ValueError('census identity changed')
        lanes = command_lanes(command, root, argv)
        if lanes:
            try:
                start = identity(pid)
            except ValueError:
                continue
            result.extend((lane, pid, start) for lane in lanes
                          if argv is None or not foreign_scope_bound(argv, lane, pid, start, root))
    # 仅消重明确的 tsx CLI 启动壳；普通同 lane 父子进程可能都是独立 scheduler。
    def ancestor(parent, child):
        seen = set()
        while child in parents and child not in seen:
            seen.add(child)
            child = parents[child]
            if child == parent:
                return True
        return False
    return [(lane, pid, start) for lane, pid, start in result
            if not (pid in wrappers and lane in ('decision', 'wayfinder') and any(other_lane == lane and ancestor(pid, other_pid)
                       for other_lane, other_pid, _ in result))]


class Owner:
    def __init__(self, lane: str, root: Path | None = None, reservation: str | None = None):
        self.gate = Gate(ROOT if root is None else root)
        self.id = self.gate.adopt(reservation, lane) if reservation else self.gate.register(lane)

    @contextmanager
    def observing(self):
        """单次执行入口在工作期间确认新代次；不领取或中断已获许可的工作。"""
        self.poll()
        done = threading.Event()
        def observe():
            while not done.wait(0.25):
                try:
                    self.poll()
                except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                    try:
                        self.gate.observer_failed(self.id)
                    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                        pass
                    # 下一周期仍尝试原owner；成功poll只清除控制故障，不改资源coverage。
        watcher = threading.Thread(target=observe, name='maintenance-observer', daemon=True)
        watcher.start()
        try:
            yield
        finally:
            done.set()
            watcher.join()

    def coverage(self, covered: bool) -> None:
        self.gate.coverage(self.id, covered)

    def poll(self) -> bool:
        return self.gate.poll(self.id)

    def admit(self, work: str) -> str:
        return self.gate.admit(self.id, work)

    def reserve(self, work: str) -> str:
        return self.gate.admit(self.id, work, transferable=True)

    def finish(self, job: str, natural: bool = True) -> None:
        self.gate.finish(self.id, job, natural=natural)

    def stop(self) -> None:
        with evidence_write():
            self.gate.stop(self.id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('command', choices=('request', 'status', 'resume', 'register', 'poll', 'admit', 'finish', 'stop', 'reconcile', 'returned-action', 'reserve-resource', 'action-exited'))
    parser.add_argument('--generation', type=int)
    parser.add_argument('--lane', choices=LANES)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--start')
    parser.add_argument('--owner')
    parser.add_argument('--work')
    parser.add_argument('--job')
    parser.add_argument('--natural', action='store_true')
    parser.add_argument('--local-actions', action='store_true')
    args = parser.parse_args(argv)
    try:
        gate = Gate(args.root)
        if args.command == 'reconcile':
            result = (gate.reconcile(args.generation, args.owner) if args.owner else
                      gate.reconcile_sighting(args.generation, args.lane, args.pid, args.start))
        elif args.command == 'register': result = {'owner': gate.register(args.lane, args.pid, local_actions=args.local_actions)}
        elif args.command == 'poll': result = {'closed': gate.poll(args.owner)}
        elif args.command == 'admit': result = {'job': gate.admit(args.owner, args.work)}
        elif args.command == 'reserve-resource': result = {'resource': gate.reserve_local_resource(args.owner, args.job)}
        elif args.command == 'action-exited': result = {'settled': gate.action_exited(args.owner, args.job, opaque_clear=args.natural)}
        elif args.command == 'returned-action': gate.returned_action(args.owner, args.job); result = {'ok': True}
        elif args.command == 'finish': gate.finish(args.owner, args.job, natural=args.natural); result = {'ok': True}
        elif args.command == 'stop': gate.stop(args.owner); result = {'ok': True}
        else:
            if args.command == 'request': gate.request()
            elif args.command == 'resume': gate.resume(args.generation)
            result = gate.status()
        print(json.dumps(result, separators=(',', ':')))
        return 0
    except Closed:
        print('{"error":"closed"}')
        return 75
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, TypeError):
        print('{"error":"maintenance_unavailable"}')
        return 78


if __name__ == '__main__':
    raise SystemExit(main())
