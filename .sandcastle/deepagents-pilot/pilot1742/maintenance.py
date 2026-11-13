"""#1742 跨 TS/Python 的维护准入账本；事务只覆盖记账，不覆盖工作执行。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import uuid

ROOT = Path('/Volumes/AgentStorage/newchanlun-maintenance')
LANES = ('decision', 'wayfinder', 'executor', 'review')


class Closed(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(pid: int) -> str:
    if type(pid) is not int or pid < 1:
        raise ValueError('invalid pid')
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'stat='], capture_output=True, text=True)
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
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, work TEXT,
                    generation INTEGER, started_at TEXT, ended_at TEXT, state TEXT, transferable INTEGER DEFAULT 0);
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

    def register(self, lane: str, pid: int | None = None) -> str:
        if lane not in LANES:
            raise ValueError('invalid lane')
        pid = os.getpid() if pid is None else pid
        start, owner = identity(pid), uuid.uuid4().hex
        with self.tx() as db:
            db.execute('INSERT INTO owners(id,lane,pid,start,registered_at,ack) VALUES(?,?,?,?,?,?)',
                       (owner, lane, pid, start, now(), -1))
        return owner

    def _owner(self, db, owner):
        row = db.execute('SELECT * FROM owners WHERE id=?', (token(owner),)).fetchone()
        if row is None or row['stopped'] or not alive(row['pid'], row['start']):
            raise ValueError('owner unavailable')
        return row

    def coverage(self, owner: str, covered: bool) -> None:
        if type(covered) is not bool:
            raise ValueError('invalid coverage')
        with self.tx() as db:
            self._owner(db, owner)
            db.execute('UPDATE owners SET covered=? WHERE id=?', (int(covered), owner))

    def poll(self, owner: str) -> bool:
        with self.tx() as db:
            self._owner(db, owner)
            state = db.execute('SELECT * FROM control').fetchone()
            if state['closed']:
                db.execute('UPDATE owners SET ack=?,ack_at=? WHERE id=?', (state['generation'], now(), owner))
            return bool(state['closed'])

    def admit(self, owner: str, work: str, *, transferable: bool = False) -> str:
        token(work)
        with self.tx() as db:
            self._owner(db, owner)
            state = db.execute('SELECT * FROM control').fetchone()
            # 同 owner 持有的工作跨轮继续；关闸不改变其后续请求权限。
            prior = db.execute("SELECT * FROM jobs WHERE owner=? AND work=? AND state='active'", (owner, work)).fetchone()
            if prior:
                if transferable:
                    raise ValueError('reservation already active')
                return prior['id']
            if state['closed']:
                # 拒绝与关闭确认一起提交，不能被异常 rollback 吃掉。
                db.execute('UPDATE owners SET ack=?,ack_at=? WHERE id=?', (state['generation'], now(), owner))
                job = None
            else:
                job = uuid.uuid4().hex
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                           (job, owner, work, state['generation'], now(), None, 'active', int(transferable)))
        if job is None:
            raise Closed('maintenance closed')
        return job

    def finish(self, owner: str, job: str, *, natural: bool) -> None:
        with self.tx() as db:
            self._owner(db, owner)
            result = db.execute("UPDATE jobs SET state=?,ended_at=? WHERE id=? AND owner=? AND state='active'",
                                ('finished' if natural else 'unknown', now(), token(job), owner))
            if result.rowcount != 1:
                raise ValueError('job not active for owner')

    def adopt(self, job: str, lane: str) -> str:
        """子进程继承已领取任务，转交与新 owner 登记同事务，无不计数间隙。"""
        if lane not in LANES:
            raise ValueError('invalid lane')
        pid, start, owner = os.getpid(), identity(os.getpid()), uuid.uuid4().hex
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND state='active' AND transferable=1", (token(job),)).fetchone()
            if row is None:
                raise ValueError('missing active reservation')
            parent = db.execute('SELECT * FROM owners WHERE id=?', (row['owner'],)).fetchone()
            if parent['lane'] != lane:
                raise ValueError('reservation lane mismatch')
            db.execute('INSERT INTO owners(id,lane,pid,start,registered_at,ack) VALUES(?,?,?,?,?,?)',
                       (owner, lane, pid, start, now(), -1))
            db.execute('UPDATE jobs SET owner=?,transferable=0 WHERE id=?', (owner, job))
        return owner

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

    def status(self, inventory=None) -> dict:
        # inventory 是生产进程身份清单；测试注入固定清单，不靠时间/TTL。
        processes = process_inventory() if inventory is None else inventory
        with self.tx() as db:
            state = dict(db.execute('SELECT * FROM control').fetchone())
            owners = [dict(r) for r in db.execute('SELECT * FROM owners ORDER BY registered_at,id')]
            jobs = [dict(r) for r in db.execute("SELECT * FROM jobs WHERE state!='finished' ORDER BY started_at,id")]
        missing = []
        for lane in LANES:
            records = [r for r in owners if r['lane'] == lane and
                       (not r['stopped'] or r['ack'] == state['generation'])]
            confirmed = [r for r in records if r['ack'] == state['generation'] and
                         (r['stopped'] or alive(r['pid'], r['start']))]
            if not confirmed or any(not r['covered'] or r['ack'] != state['generation'] or
                                   (not r['stopped'] and not alive(r['pid'], r['start'])) for r in records):
                missing.append(lane)
        uncovered = []
        for lane, pid, start in processes:
            if not any(r['lane'] == lane and r['pid'] == pid and r['start'] == start and not r['stopped'] for r in owners):
                uncovered.append({'lane': lane, 'pid': pid})
        for job in jobs:
            owner = next(r for r in owners if r['id'] == job['owner'])
            if owner['stopped'] or not alive(owner['pid'], owner['start']):
                job['state'] = 'unknown'
        mode = 'open' if not state['closed'] else ('unknown' if missing or uncovered or any(j['state'] == 'unknown' for j in jobs)
                else 'draining' if jobs else 'drained')
        return {'v': 1, 'generation': state['generation'], 'state': mode, 'requested_at': state['requested_at'],
                'observed_at': now(), 'unconfirmed': missing, 'uncovered': uncovered,
                'owners': [{k: r[k] for k in ('id', 'lane', 'pid', 'registered_at', 'ack', 'ack_at', 'stopped', 'covered')} for r in owners],
                'inflight': jobs}


def process_inventory() -> list[tuple[str, int, str]]:
    output = subprocess.run(['ps', '-axo', 'pid=,ppid=,args='], check=True, capture_output=True, text=True).stdout
    result = []
    parents = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        pid, parent, command = int(parts[0]), int(parts[1]), parts[2]
        parents[pid] = parent
        # 不输出完整命令（可能含提示或秘密）。仅识别真实解释器入口，不匹配 shell 提示文本。
        if not re.match(r'\S*(?:python[\d.]*|node|tsx)\s', command):
            continue
        lanes = []
        if re.search(r'(?:^|\s)\S*decision-claimer\.mts(?:\s|$)', command): lanes.append('decision')
        if re.search(r'(?:^|\s)\S*wayfinder_engine\.mts(?:\s|$)', command): lanes.append('wayfinder')
        if re.search(r'-m pilot1742\.executor\b.*\bserve\b', command):
            lanes.append('executor')
            if '--review-sweep' in command: lanes.append('review')
        if re.search(r'-m pilot1742\.(?:review_sweep|external_review)\b', command): lanes.append('review')
        if lanes:
            try:
                start = identity(pid)
            except ValueError:
                continue
            result.extend((lane, pid, start) for lane in lanes)
    # tsx 的 CLI 启动壳与执行脚本可能都带脚本名；以同 lane 最内层解释器作为 owner。
    def ancestor(parent, child):
        seen = set()
        while child in parents and child not in seen:
            seen.add(child)
            child = parents[child]
            if child == parent:
                return True
        return False
    return [(lane, pid, start) for lane, pid, start in result
            if not any(other_lane == lane and ancestor(pid, other_pid)
                       for other_lane, other_pid, _ in result)]


class Owner:
    def __init__(self, lane: str, root: Path | None = None, reservation: str | None = None):
        self.gate = Gate(ROOT if root is None else root)
        self.id = self.gate.adopt(reservation, lane) if reservation else self.gate.register(lane)

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
        self.gate.stop(self.id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('command', choices=('request', 'status', 'resume', 'register', 'poll', 'admit', 'finish', 'stop'))
    parser.add_argument('--generation', type=int)
    parser.add_argument('--lane', choices=LANES)
    parser.add_argument('--pid', type=int)
    parser.add_argument('--owner')
    parser.add_argument('--work')
    parser.add_argument('--job')
    parser.add_argument('--natural', action='store_true')
    args = parser.parse_args(argv)
    try:
        gate = Gate(args.root)
        if args.command == 'register': result = {'owner': gate.register(args.lane, args.pid)}
        elif args.command == 'poll': result = {'closed': gate.poll(args.owner)}
        elif args.command == 'admit': result = {'job': gate.admit(args.owner, args.work)}
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
