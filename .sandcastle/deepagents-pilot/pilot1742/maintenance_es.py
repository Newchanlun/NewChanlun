"""macos-es-v1 离线协议；无 ES/IPC 后端、无生产启用开关。

与 Gate 共用准入与 SQLite。offline 证据绝不写 local_resource_domains/sealed_at，
因此生产 Gate 不接受它。native-es 提供默认禁用的开发适配器；真实 ES/签名正向链尚待验收。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable, Literal

from .maintenance import ROOT, Gate, evidence_write, now, token

KIND = 'macos-es-v1'
EVENTS = ('FORK', 'EXEC', 'EXIT')


@dataclass(frozen=True)
class AuditIdentity:
    # audit_token_t 的全部8个白名单整数，不接受自报PID替代内核peer。
    words: tuple[int, ...]

    def __post_init__(self):
        if type(self.words) is not tuple or len(self.words) != 8 or any(type(x) is not int or not 0 <= x < 2**32 for x in self.words):
            raise ValueError('invalid audit identity')
        if self.words[5] == 0:
            raise ValueError('invalid pid')

    @property
    def key(self) -> str:
        return ':'.join(map(str, self.words))


@dataclass(frozen=True)
class Peer:
    audit: AuditIdentity
    image: str  # 预期受管helper签名身份的适配器别名；离线值不构成签名核验。

    def __post_init__(self):
        if type(self.audit) is not AuditIdentity:
            raise ValueError('invalid peer audit token')
        token(self.image)


@dataclass(frozen=True)
class Event:
    epoch: str
    seq: int
    version: int
    kind: Literal['FORK', 'EXEC', 'EXIT']
    actor: AuditIdentity
    target: AuditIdentity | None = None
    image: str | None = None

    def __post_init__(self):
        token(self.epoch)
        if type(self.actor) is not AuditIdentity or (self.target is not None and type(self.target) is not AuditIdentity):
            raise ValueError('invalid event identity')
        if type(self.seq) is not int or self.seq < 0 or type(self.version) is not int:
            raise ValueError('invalid event frontier')
        if self.kind not in EVENTS or ((self.kind != 'EXIT') != (self.target is not None)):
            raise ValueError('invalid event shape')
        if (self.kind == 'EXEC') != (self.image is not None):
            raise ValueError('invalid executable identity')
        if self.image is not None:
            token(self.image)

    @classmethod
    def from_wire(cls, value: dict) -> Event:
        if set(value) != {'epoch', 'seq', 'version', 'kind', 'actor', 'target', 'image'}:
            raise ValueError('non-whitelisted event fields')
        return cls(value['epoch'], value['seq'], value['version'], value['kind'],
                   AuditIdentity(tuple(value['actor'])),
                   None if value['target'] is None else AuditIdentity(tuple(value['target'])), value['image'])


@dataclass(frozen=True)
class Coverage:
    version: int
    subscriptions: tuple[str, ...]
    uncovered: tuple[str, ...]  # 默认mute、inversion、内部转发覆盖核验的缺口代码。

    def __post_init__(self):
        if type(self.subscriptions) is not tuple or type(self.uncovered) is not tuple:
            raise ValueError('invalid coverage shape')
        reasons = {'default_path_mute', 'process_mute', 'event_mute', 'inverted_process_mute',
                   'internal_forwarding', 'unknown_configuration'}
        if any(x not in EVENTS for x in self.subscriptions) or any(x not in reasons for x in self.uncovered):
            raise ValueError('non-whitelisted coverage fields')

    def ready(self) -> bool:
        return (type(self.version) is int and self.version >= 5 and
                self.subscriptions == EVENTS and not self.uncovered)


@dataclass
class Source:
    epoch: str
    host: str
    boot: str
    ready: bool
    last: int | None = None
    taint: str | None = None
    protocol: Literal['macos-es-v1'] = 'macos-es-v1'
    trust: Literal['offline', 'native'] = 'offline'


@dataclass
class Action:
    resource: str
    job: str
    epoch: str
    nonce: str
    parent: str
    image: str
    frontier: int
    candidates: list[str] = field(default_factory=list)
    dirty_candidates: list[str] = field(default_factory=list)
    startup_execs: dict[str, str | None] = field(default_factory=dict)
    parents: dict[str, str] = field(default_factory=dict)
    root: str | None = None
    peer: str | None = None
    live: list[str] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)
    exited: list[str] = field(default_factory=list)
    permit: str | None = None
    claimed: bool = False
    primary: str | None = None
    code: int | None = None
    closed_seq: int | None = None
    unknown: str | None = None


def taint(source: Source, actions: list[Action], reason: str) -> None:
    source.ready, source.taint = False, reason
    for action in actions:
        if action.epoch == source.epoch and action.closed_seq is None:
            action.unknown = action.unknown or reason


def select_peer(action: Action) -> None:
    """只选注册身份对应的启动EXEC；同parent其它helper仍是独立候选。"""
    if action.root is not None or action.peer not in action.startup_execs:
        return
    reason = action.startup_execs[action.peer]
    if reason:
        action.unknown = reason
        return
    action.root = action.peer
    action.live, action.seen = [action.peer], [action.peer]


def reduce_event(source: Source, actions: list[Action], event: Event) -> None:
    """先检查全局序号/来源，随后才处理包括无关进程在内的事件分支。"""
    if not source.ready:
        return
    if (event.epoch != source.epoch or event.version < 5 or
            (source.last is not None and event.seq != source.last + 1)):
        taint(source, actions, 'stream_discontinuity')
        return
    source.last = event.seq
    old = event.actor.key
    new = event.target.key if event.target else None
    for a in actions:
        if a.epoch != source.epoch or a.unknown or a.closed_seq is not None:
            continue
        if event.seq <= a.frontier:
            a.unknown = 'preexisting_event'
            continue
        if a.root is None:
            if old in a.startup_execs:
                # 注册晚到也不能追认已经退出或派生业务的helper。
                a.startup_execs[old] = a.startup_execs[old] or (
                    'helper_exited_before_arm' if event.kind == 'EXIT' else 'unauthorized_or_duplicate_fork'
                )
            if event.kind == 'FORK' and old == a.parent and new is not None:
                a.candidates.append(new)
            elif event.kind == 'FORK' and old in a.candidates:
                a.dirty_candidates.append(old)
            elif event.kind == 'EXEC' and old in a.candidates:
                a.candidates.remove(old)
                if event.image == a.image and new is not None:
                    reason = None
                    if old in a.dirty_candidates:
                        reason = 'helper_had_preexec_descendants'
                    elif new.split(':')[5] != old.split(':')[5] or new == old:
                        reason = 'execution_identity_conflict'
                    a.startup_execs[new] = reason
            elif event.kind == 'EXIT' and old in a.candidates:
                a.candidates.remove(old)
            select_peer(a)
            continue
        if old not in a.live:
            # 旧exec token不能释放新token；复用同PID的矛盾事件不能被当成无关。
            if old in a.seen or any(x.split(':')[5] == old.split(':')[5] for x in a.live):
                a.unknown = 'execution_identity_conflict'
            continue
        if event.kind == 'FORK' and new is not None:
            if not a.claimed or new in a.seen or any(x.split(':')[5] == new.split(':')[5] for x in a.live):
                a.unknown = 'unauthorized_or_duplicate_fork'
            else:
                a.live.append(new)
                a.seen.append(new)
                a.parents[new] = old
        elif event.kind == 'EXEC' and new is not None:
            if not a.claimed or new in a.seen or new.split(':')[5] != old.split(':')[5]:
                a.unknown = 'execution_identity_conflict'
            else:
                a.live[a.live.index(old)] = new
                a.seen.append(new)
                if old in a.parents:
                    a.parents[new] = a.parents[old]
        elif event.kind == 'EXIT':
            a.live.remove(old)
            a.exited.append(old)
            if not a.live:
                if a.permit is None:
                    a.unknown = 'helper_exited_before_arm'
                else:
                    a.closed_seq = event.seq


class OfflineES:
    """唯一串行collector的离线实现。重开实例代表失去原连接，不能继续旧source。

    Gate只提供现有原子准入及资源占用；不启动子进程、不执行模型、不创建socket。
    launch回调只用于离线轨迹模拟。没有生产fixture信任开关。
    """

    source_table = "es_sources"
    action_table = "es_actions"
    audit_table = "es_audit"

    def __init__(self, gate: Gate):
        if gate.root.resolve() == ROOT.resolve():
            raise ValueError('offline source requires isolated ledger')
        self.gate = gate
        self.current: str | None = None
        self.revoked: dict[str, str] = {}
        self._schema()
        with gate.tx() as db:
            actions = self._actions(db)
            for row in db.execute(f'SELECT data FROM {self.source_table}').fetchall():
                source = Source(**json.loads(row[0]))
                if source.ready:
                    taint(source, actions, 'collector_reopened')
                    self._save(db, source, actions)
            self._log(db, 'offline-open', {'protocol': KIND})

    def _schema(self) -> None:
        with self.gate.tx() as db:
            db.executescript(f'''
                CREATE TABLE IF NOT EXISTS {self.source_table} (epoch TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS {self.action_table} (resource TEXT PRIMARY KEY, job TEXT, nonce TEXT UNIQUE, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS {self.audit_table} (id INTEGER PRIMARY KEY, at TEXT, operation TEXT, data TEXT);
            ''')

    @classmethod
    def _actions(cls, db) -> list[Action]:
        return [Action(**json.loads(r[0])) for r in db.execute(f'SELECT data FROM {cls.action_table}')]

    @classmethod
    def _log(cls, db, operation: str, data: dict) -> None:
        db.execute(f'INSERT INTO {cls.audit_table}(at,operation,data) VALUES(?,?,?)', (now(), operation, json.dumps(data)))

    @classmethod
    def _save(cls, db, source: Source, actions: list[Action]) -> None:
        db.execute(f'INSERT OR REPLACE INTO {cls.source_table} VALUES(?,?)', (source.epoch, json.dumps(asdict(source))))
        for a in actions:
            db.execute(f'INSERT INTO {cls.action_table} VALUES(?,?,?,?) ON CONFLICT(resource) DO UPDATE SET data=excluded.data',
                       (a.resource, a.job, a.nonce, json.dumps(asdict(a))))

    @classmethod
    def _source(cls, db, epoch: str) -> Source:
        row = db.execute(f'SELECT data FROM {cls.source_table} WHERE epoch=?', (token(epoch),)).fetchone()
        if row is None:
            raise ValueError('unknown source epoch')
        return Source(**json.loads(row[0]))

    def source(self, epoch: str, host: str, boot: str, coverage: Coverage) -> None:
        for value in (epoch, host, boot):
            token(value)
        if self.current is not None:
            self.revoked[self.current] = 'source_replaced'
            self.current = None
        with self.gate.tx() as db:
            if db.execute(f'SELECT 1 FROM {self.source_table} WHERE epoch=?', (epoch,)).fetchone():
                raise ValueError('epoch cannot be reused')
            actions = self._actions(db)
            for row in db.execute(f'SELECT data FROM {self.source_table}').fetchall():
                previous = Source(**json.loads(row[0]))
                if previous.ready:
                    taint(previous, actions, 'source_replaced')
                    self._save(db, previous, actions)
            source = Source(epoch, host, boot, coverage.ready(), taint=None if coverage.ready() else 'coverage_unverified')
            self._save(db, source, actions)
            self._log(db, 'offline-subscription', {'source': asdict(source), 'coverage': asdict(coverage)})
        self.current = epoch

    def lost(self, epoch: str, reason: Literal['source_lost', 'configuration_changed', 'internal_drop']) -> None:
        if reason not in ('source_lost', 'configuration_changed', 'internal_drop'):
            raise ValueError('invalid loss reason')
        self.revoked[epoch] = reason
        if self.current == epoch:
            self.current = None
        with self.gate.tx() as db:
            source, actions = self._source(db, epoch), self._actions(db)
            taint(source, actions, reason)
            self._save(db, source, actions)
            self._log(db, reason, {'epoch': epoch})

    def ingest(self, event: Event) -> None:
        if self.current is None:
            raise ValueError('no current source connection')
        epoch = self.current
        try:
            with self.gate.tx() as db:
                source, actions = self._source(db, epoch), self._actions(db)
                reduce_event(source, actions, event)
                self._save(db, source, actions)
                self._log(db, 'offline-event', asdict(event))
        except BaseException:
            # 持久化失败也属于来源丢失；不得在下一条消息前继续发许可。
            self.current = None
            self.revoked[epoch] = 'internal_drop'
            with evidence_write():
                self.lost(epoch, 'internal_drop')
            raise

    def ingest_wire(self, value: dict) -> None:
        try:
            event = Event.from_wire(value)
        except (ValueError, TypeError, KeyError):
            if self.current is not None:
                self.lost(self.current, 'internal_drop')
            raise ValueError('invalid ES wire event') from None
        self.ingest(event)

    def prepare(self, epoch: str, owner: str, work: str, parent: AuditIdentity, image: str, nonce: str) -> str:
        token(image), token(nonce)
        with self.gate.tx() as db:
            source = self._source(db, epoch)
            scheduler = self.gate._owner(db, owner)
            if scheduler['pid'] != parent.words[5]:
                raise ValueError('scheduler peer does not match owner')
            if epoch != self.current or not source.ready or source.last is None:
                raise ValueError('source not ready')
            if db.execute(f'SELECT 1 FROM {self.action_table} WHERE nonce=?', (nonce,)).fetchone():
                raise ValueError('nonce already used')
        # 只有新准入动作可接入；没有attach-old-job接口。中途失败留下未决占用，不派业务。
        job = self.gate.admit(owner, work)
        resource = self.gate.reserve_local_resource(owner, job)
        with self.gate.tx() as db:
            source = self._source(db, epoch)
            action_epoch = db.execute('SELECT host,boot FROM local_actions WHERE job=?', (job,)).fetchone()
            if not source.ready or source.last is None or tuple(action_epoch) != (source.host, source.boot):
                raise ValueError('source changed before registration')
            a = Action(resource, job, epoch, nonce, parent.key, image, source.last)
            self._save(db, source, [a])
            self._log(db, 'prepare', {'resource': resource, 'job': job, 'epoch': epoch})
        return resource

    def _bound(self, db, resource: str) -> tuple[Source, Action]:
        row = db.execute(f'SELECT data FROM {self.action_table} WHERE resource=?', (token(resource),)).fetchone()
        if row is None:
            raise ValueError('unregistered ES resource')
        a = Action(**json.loads(row[0]))
        return self._source(db, a.epoch), a

    def register_peer(self, resource: str, nonce: str, peer: Peer) -> None:
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            if nonce != a.nonce or peer.image != a.image or (a.peer is not None and a.peer != peer.audit.key):
                raise ValueError('wrong registration peer')
            if source.epoch != self.current or not source.ready or a.unknown or a.closed_seq is not None:
                raise ValueError('registration unavailable')
            a.peer = peer.audit.key
            select_peer(a)
            self._save(db, source, [a])
            self._log(db, 'register-peer', {'resource': resource, 'peer': a.peer})

    def arm(self, resource: str, peer: Peer) -> str | None:
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            if (source.epoch != self.current or not source.ready or a.unknown or a.root is None or a.root != a.peer or
                    peer.audit.key != a.peer or peer.image != a.image or a.closed_seq is not None):
                return None
            if a.permit is None:
                a.permit = uuid.uuid4().hex
                self._save(db, source, [a])  # commit之后才返回ACK。
                self._log(db, 'arm', {'resource': resource, 'permit': a.permit})
            return a.permit

    def claim_launch(self, resource: str, permit: str, peer: Peer) -> bool:
        """在发送原生ARM前持久消费；只允许一次，无业务回调。"""
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            if (source.epoch != self.current or not source.ready or a.unknown or a.permit != permit or a.permit is None or
                    a.peer != peer.audit.key or peer.image != a.image or a.closed_seq is not None):
                raise ValueError('launch not permitted')
            if a.claimed:
                return False
            a.claimed = True
            self._save(db, source, [a])
            self._log(db, 'claim-permit', {'resource': resource})
        return True

    def bind_primary(self, resource: str, peer: Peer, primary: AuditIdentity) -> None:
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            if (a.peer != peer.audit.key or peer.image != a.image or not a.claimed or
                    a.parents.get(primary.key) != a.root or a.primary not in (None, primary.key)):
                raise ValueError('unbound primary')
            a.primary = primary.key
            self._save(db, source, [a])

    def launch(self, resource: str, permit: str, peer: Peer, dispatch: Callable[[], AuditIdentity]) -> bool:
        if not self.claim_launch(resource, permit, peer):
            return False
        # ACK重传、同许可并发、commit后crash都不能第二次进入callback。
        try:
            primary = dispatch()
        except BaseException:
            with evidence_write():
                with self.gate.tx() as db:
                    source, a = self._bound(db, resource)
                    a.unknown = a.unknown or 'dispatch_uncertain'
                    self._save(db, source, [a])
            raise
        self.bind_primary(resource, peer, primary)
        return True

    def waited(self, resource: str, peer: Peer, primary: AuditIdentity, code: int) -> None:
        if type(code) is not int:
            raise ValueError('invalid business wait')
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            if (a.peer != peer.audit.key or peer.image != a.image or not a.claimed or
                    a.primary != primary.key or a.parents.get(primary.key) != a.root or a.code is not None):
                raise ValueError('unbound business wait')
            a.code = code
            self._save(db, source, [a])
            self._log(db, 'business-wait', {'resource': resource, 'primary': primary.key, 'code': code})

    def status(self, resource: str) -> dict:
        with self.gate.tx() as db:
            source, a = self._bound(db, resource)
            binding = db.execute('SELECT data FROM bindings WHERE job=?', (a.job,)).fetchone()
        unknown = a.unknown or (self.revoked.get(a.epoch) if a.closed_seq is None else None)
        process_closed = a.closed_seq is not None and unknown is None
        resources_closed = process_closed and a.code is not None
        if resources_closed and binding is not None:
            try:
                resources_closed = self.gate._resources_idle(json.loads(binding[0]), [], set())
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                resources_closed = False
        phase = ('UNKNOWN' if unknown else 'COMPLETE' if resources_closed else
                 'PROCESS_CLOSED' if process_closed else 'RUNNING' if a.claimed else
                 'ARMED' if a.permit else 'REGISTERING')
        return {'protocol': KIND, 'trust': 'offline', 'offline_phase': phase, 'source_epoch': a.epoch, 'resource': resource,
                'job': a.job, 'source_ready': source.ready and self.current == a.epoch, 'action_armed': a.permit is not None,
                'process_closed': process_closed, 'business_waited': a.code is not None,
                'resources_closed': resources_closed, 'live': list(a.live), 'unknown': unknown,
                'closed_seq': a.closed_seq, 'business_code': a.code, 'production_accepted': False}
