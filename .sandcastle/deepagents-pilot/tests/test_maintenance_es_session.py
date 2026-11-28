"""显式ES编排的隔离来源；永不构造VerifiedChannel或写native可信表。"""
import os
import queue
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

from pilot1742 import maintenance as m
from pilot1742 import maintenance_es_session as session
from pilot1742.maintenance_es import AuditIdentity, Peer


def audit(pid, version=1):
    return AuditIdentity((501, 501, 20, 501, 20, pid, 99, version))


class FixtureChannel:
    epoch = 'isolated-transport'
    parent = audit(os.getpid())
    config = dict(helper='fixture-helper', socket='unused', collector_requirement='unused',
                  helper_requirement='unused', image='helper')

    def __init__(self):
        self.frames = queue.Queue()
        self.sent = []
        self.seq = 0
        self.resource = None
        self.nonce = None
        self.failure = None

    def event(self, kind, actor, target=None, image=None):
        self.seq += 1
        self.frames.put(dict(type='event', event=dict(epoch=self.epoch, seq=self.seq, version=5,
                         kind=kind, actor=actor.words, target=target.words if target else None, image=image)))

    def read(self):
        frame = self.frames.get(timeout=5)
        if frame is None:
            raise EOFError('fixture closed')
        return frame

    def send(self, message):
        self.sent.append(message)
        if message.startswith('ARM'):
            if self.failure == 'ack':
                raise BrokenPipeError('fixture ACK failure')
            self.event('FORK', audit(200, 2), audit(300))
            self.frames.put(dict(type='started', resource=self.resource, pid=300))
            if self.failure == 'source':
                self.frames.put(None)
                return
            self.event('EXIT', audit(300))
            self.frames.put(dict(type='waited', resource=self.resource, pid=300, code=23))
        elif message.startswith('WAITED'):
            self.event('EXIT', audit(200, 2))

    def close(self):
        self.shutdown()

    def shutdown(self):
        self.frames.put(None)


class FixtureReducer(session.BoundSession):
    def __init__(self, gate, channel):
        super().__init__(gate, channel)
        self.seal_calls = 0

    def prepare_resource(self, resource, nonce):
        super().prepare_resource(resource, nonce)
        self.channel.resource, self.channel.nonce = resource, nonce

    def seal(self, resource):
        self.seal_calls += 1
        # Protocol completion in a fixture does NOT grant Gate resource evidence.
        assert not self.status(resource)['production_accepted']
        return False


@pytest.mark.parametrize('failure', [None, 'ack', 'source', 'seal', 'notification'])
def test_vertical_wait_and_loss_preserve_business_result_without_promoting_fixture(tmp_path, monkeypatch, failure):
    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'work')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    gate.request()  # 已领取任务在关闭之后仍可完整推进；不是新admit。
    channel = FixtureChannel()
    channel.failure = failure
    reducer = FixtureReducer(gate, channel)
    def popen(command):
        assert command[0] == 'fixture-helper'
        channel.event('FORK', audit(os.getpid()), audit(200))
        channel.event('EXEC', audit(200), audit(200, 2), 'helper')
        channel.frames.put(dict(type='register', resource=resource, nonce='nonce', image='helper', peer=audit(200, 2).words))
        return subprocess.Popen([sys.executable, '-c', 'print("isolated-business-output"); raise SystemExit(23)'])
    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=popen))
    if failure == 'seal':
        def failed(_):
            raise sqlite3.OperationalError('fixture persistence failure')
        reducer.seal = failed
    def notify(code):
        assert code == 23
        raise OSError('isolated caller notification failure')
    assert session._run_session(reducer, channel, resource, 'nonce', ['unused'],
                                on_business_wait=notify if failure == 'notification' else None) == 23
    if failure == 'notification':
        assert reducer.seal_calls == 1, 'caller notification failure must not abandon supervision'
    assert len([s for s in channel.sent if s.startswith('ARM')]) == 1
    assert not gate.local_action_idle(job)
    assert not reducer.status(resource)['production_accepted']
    with gate.tx() as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='native_es_sources'").fetchone()


def test_fixture_cannot_construct_trusted_channel_or_reducer(tmp_path):
    with pytest.raises(TypeError):
        session.VerifiedChannel()
    with pytest.raises(ValueError, match='authenticated'):
        session.NativeES(m.Gate(tmp_path), FixtureChannel())


def test_missing_managed_configuration_refuses_before_helper_or_fallback(tmp_path, monkeypatch):
    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'no-config')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(session.os, 'setsid', lambda: None)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=lambda *a, **kw: pytest.fail('must not spawn')))
    with pytest.raises((OSError, ValueError)):
        session._supervise(SimpleNamespace(root=tmp_path, resource=resource, es_config=tmp_path / 'absent'), ['unused'])
    with gate.tx() as db:
        assert db.execute('SELECT reason FROM local_resource_not_started').fetchone()[0] == 'baseline_unavailable'
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None
    assert gate.local_action_idle(job)


def test_popen_sync_failure_is_not_a_business_wait(tmp_path, monkeypatch):
    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'spawn-failed')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    channel = FixtureChannel()
    reducer = FixtureReducer(gate, channel)
    def failed(*args, **kwargs):
        raise FileNotFoundError('isolated Popen sync failure')
    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=failed))
    assert session._run_session(reducer, channel, resource, 'nonce', ['unused']) == 127
    assert channel.sent == []
    assert gate.local_action_idle(job)
    with gate.tx() as db:
        assert db.execute('SELECT reason FROM local_resource_not_started').fetchone()[0] == 'exec_failed'
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None


def test_old_prepared_resource_cannot_rebind_after_source_restart(tmp_path, monkeypatch):
    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'old-resource')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    first = FixtureReducer(gate, FixtureChannel())
    from pilot1742.maintenance_epoch import local_epoch
    from pilot1742.maintenance_es import EVENTS, Coverage
    first.source(first.channel.epoch, *local_epoch(), Coverage(5, EVENTS, ()))
    first.prepare_resource(resource, 'nonce')
    second = FixtureReducer(gate, FixtureChannel())
    second.channel.epoch = 'new-source'
    second.source(second.channel.epoch, *local_epoch(), Coverage(5, EVENTS, ()))
    with pytest.raises(ValueError, match='reattached'):
        second.prepare_resource(resource, 'new-nonce')
    assert not gate.local_action_idle(job)


@pytest.mark.parametrize('missing', [None, 'offline', 'wait', 'descendant', 'epoch', 'peer', 'gap', 'external'])
def test_durable_closure_consumption_contract_only(tmp_path, monkeypatch, missing):
    """直接构造隔离数据库的终态输入测试消费判据；不是来源认证或真实ES验收。"""
    import json
    from dataclasses import asdict

    from pilot1742.maintenance_epoch import local_epoch
    from pilot1742.maintenance_es import Action, Source

    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'persisted-closure')
    resource = gate.reserve_local_resource(owner, job)
    host, boot = local_epoch()
    source = Source('persisted', host, boot, False, trust='native')
    # Source EOF after causal closure does not invalidate already persisted terminal evidence.
    action = Action(resource, job, source.epoch, 'nonce', audit(100).key, 'helper', 0,
                    root=audit(200, 2).key, peer=audit(200, 2).key, permit='permit', claimed=True,
                    primary=audit(300).key, code=23, closed_seq=9, parents={audit(300).key: audit(200, 2).key})
    if missing == 'offline':
        source.trust = 'offline'
    elif missing == 'wait':
        action.code = None
    elif missing == 'descendant':
        action.live = [audit(400).key]
    elif missing == 'epoch':
        source.boot = 'old-boot'
    elif missing == 'peer':
        action.peer = audit(200, 3).key
    elif missing == 'gap':
        action.unknown = 'stream_discontinuity'
    with gate.tx() as db:
        db.executescript('''CREATE TABLE native_es_sources(epoch TEXT PRIMARY KEY,data TEXT);
          CREATE TABLE native_es_actions(resource TEXT PRIMARY KEY,job TEXT,nonce TEXT,data TEXT);
          CREATE TABLE native_es_audit(id INTEGER PRIMARY KEY,at TEXT,operation TEXT,data TEXT);''')
        db.execute('INSERT INTO native_es_sources VALUES(?,?)', (source.epoch, json.dumps(asdict(source))))
        db.execute('INSERT INTO native_es_actions VALUES(?,?,?,?)', (resource, job, 'nonce', json.dumps(asdict(action))))
        db.execute('UPDATE local_resources SET host=?,boot=?,pid=?,start=?,sid=? WHERE id=?',
                   (host, boot, 100, 'original-supervisor', 100, resource))
        db.execute('INSERT INTO local_resource_domains VALUES(?,?,?,NULL)',
                   (resource, json.dumps(dict(kind='macos-es-v1', epoch=source.epoch)), action.parent))
        if missing == 'external':
            db.execute('INSERT INTO bindings VALUES(?,?)', (job, json.dumps({'kind': 'fixture-external'})))
    monkeypatch.setattr(gate, '_resources_idle', lambda *a: False)
    generation = gate.request()
    assert session.settle_native_resource(gate, resource) == (missing is None)
    assert session.settle_native_resource(gate, resource) == (missing is None)
    with gate.tx() as db:
        control = db.execute('SELECT * FROM control').fetchone()
        assert control['closed'] and control['generation'] == generation
        assert db.execute('SELECT count(*) FROM native_es_audit').fetchone()[0] == (1 if missing is None else 0)
        assert not db.execute('SELECT * FROM action_returns').fetchall()  # 不补造整个callback的return。


@pytest.mark.parametrize('trajectory', ['before_register', 'rejected_register', 'delayed_register', 'awaiting_exec'])
@pytest.mark.parametrize('code', [78, -15])
def test_helper_terminal_before_arm_returns_without_source_eof(tmp_path, monkeypatch, trajectory, code):
    """Healthy source must not be required to die to deliver the real wait result."""
    import threading

    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'terminal-helper')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    read_started = threading.Event()
    processed = threading.Event()
    closed = threading.Event()

    class Channel(FixtureChannel):
        timed_out = False
        late_delivered = False

        def read(self):
            read_started.set()
            if trajectory == 'delayed_register' and not self.late_delivered:
                # A frame is in flight until local revocation closes the session.
                assert closed.wait(2), 'helper result waited for source death'
                self.late_delivered = True
                return register
            try:
                frame = self.frames.get(timeout=2)
            except queue.Empty:
                self.timed_out = True
                raise EOFError('test watchdog, not a successful closure') from None
            if frame is None:
                raise EOFError('local close')
            return frame

        def close(self):
            closed.set()
            super().close()

    channel = Channel()
    reducer = FixtureReducer(gate, channel)
    register = dict(type='register', resource=resource, nonce='nonce', image='helper', peer=audit(200, 2).words)
    original_register = reducer.register_peer

    def register_peer(*args):
        try:
            if trajectory == 'rejected_register':
                raise ValueError('isolated registration rejection')
            return original_register(*args)
        finally:
            processed.set()

    monkeypatch.setattr(reducer, 'register_peer', register_peer)

    class Helper:
        def wait(self):
            assert read_started.wait(2)
            if trajectory in ('rejected_register', 'awaiting_exec'):
                assert processed.wait(2)
            return code

        def poll(self):
            return code

    def popen(command):
        if trajectory in ('rejected_register', 'awaiting_exec'):
            channel.frames.put(register)
        return Helper()

    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=popen))
    assert session._run_session(reducer, channel, resource, 'nonce', ['unused']) == (code if code >= 0 else 128 - code)
    assert not channel.timed_out
    assert closed.is_set()
    assert channel.late_delivered == (trajectory == 'delayed_register')
    assert channel.sent == []
    assert reducer.seal_calls == 0
    assert reducer.status(resource)['unknown']
    assert not gate.local_action_idle(job)
    with gate.tx() as db:
        assert not db.execute('SELECT * FROM local_resource_not_started').fetchall()
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None
    # Revoked session cannot authorize a late EXEC/REGISTER or a second dispatch.
    assert reducer.arm(resource, Peer(audit(200, 2), 'helper')) is None


def test_helper_exit_racing_arm_failure_never_reissues_permit(tmp_path, monkeypatch):
    import threading

    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'arm-race')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    sending = threading.Event()
    helper_exited = threading.Event()

    class Channel(FixtureChannel):
        def send(self, message):
            self.sent.append(message)
            assert message.startswith('ARM')
            sending.set()
            assert helper_exited.wait(2)
            raise BrokenPipeError('ARM write completion after helper exit')

    channel = Channel()
    reducer = FixtureReducer(gate, channel)

    class Helper:
        def wait(self):
            assert sending.wait(2)
            helper_exited.set()
            return 78

        def poll(self):
            return 78

    def popen(command):
        channel.event('FORK', audit(os.getpid()), audit(200))
        channel.event('EXEC', audit(200), audit(200, 2), 'helper')
        channel.frames.put(dict(type='register', resource=resource, nonce='nonce', image='helper', peer=audit(200, 2).words))
        return Helper()

    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=popen))
    assert session._run_session(reducer, channel, resource, 'nonce', ['unused']) == 78
    assert len(channel.sent) == 1
    with gate.tx() as db:
        _, action = reducer._bound(db, resource)
        assert action.claimed and action.permit
        assert not db.execute('SELECT * FROM local_resource_not_started').fetchall()
    assert reducer.arm(resource, Peer(audit(200, 2), 'helper')) is None
    assert reducer.status(resource)['unknown']
    assert reducer.seal_calls == 0
    assert not gate.local_action_idle(job)

@pytest.mark.parametrize('order', ['wait-first', 'exit-first', 'exit-eof', 'exit-lost', 'exit-no-wait'])
def test_closed_process_and_business_wait_are_independent_channels(tmp_path, monkeypatch, order):
    import threading

    gate = m.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'channel-order')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(m.os, 'getsid', lambda _: os.getpid())
    gate.bind_local_resource_identity(resource)
    armed = threading.Event()
    observed_closed = threading.Event()
    monkeypatch.setattr(session, 'WAIT_EVIDENCE_SECONDS', 0.05, raising=False)

    class Channel(FixtureChannel):
        def send(self, message):
            self.sent.append(message)
            if message.startswith('ARM'):
                self.event('FORK', audit(200, 2), audit(300))
                self.frames.put(dict(type='started', resource=resource, pid=300))
                self.event('EXIT', audit(300))
                if order == 'wait-first':
                    self.frames.put(dict(type='waited', resource=resource, pid=300, code=23))
                self.event('EXIT', audit(200, 2))
                if order != 'wait-first':
                    self.frames.put('delayed-wait')
                armed.set()

        def read(self):
            frame = super().read()
            if frame == 'delayed-wait':
                assert observed_closed.wait(2)
                if order == 'exit-first':
                    return dict(type='waited', resource=resource, pid=300, code=23)
                if order == 'exit-eof':
                    raise EOFError('isolated disconnect')
                if order == 'exit-lost':
                    return dict(type='lost')
                try:
                    return super().read()  # Healthy source, no WAIT; close must unblock it.
                except queue.Empty:
                    self.read_timed_out = True
                    raise
            return frame

    channel = Channel()
    channel.read_timed_out = False
    reducer = FixtureReducer(gate, channel)
    original_status = reducer.status

    def status(resource):
        value = original_status(resource)
        if value['process_closed']:
            observed_closed.set()
        return value

    monkeypatch.setattr(reducer, 'status', status)
    original_seal = reducer.seal

    def seal(resource):
        assert original_status(resource)['business_waited'], 'must not seal before real WAIT'
        return original_seal(resource)

    monkeypatch.setattr(reducer, 'seal', seal)

    class Helper:
        def wait(self):
            assert armed.wait(2)
            return 23

        def poll(self):
            return 23

    def popen(command):
        channel.event('FORK', audit(os.getpid()), audit(200))
        channel.event('EXEC', audit(200), audit(200, 2), 'helper')
        channel.frames.put(dict(type='register', resource=resource, nonce='nonce', image='helper', peer=audit(200, 2).words))
        return Helper()

    monkeypatch.setattr(session, 'subprocess', SimpleNamespace(Popen=popen))
    assert session._run_session(reducer, channel, resource, 'nonce', ['unused']) == 23
    assert not channel.read_timed_out, 'session must bound missing WAIT, not rely on source EOF'
    complete = order in ('wait-first', 'exit-first')
    assert reducer.seal_calls == int(complete)
    assert original_status(resource)['business_waited'] == complete
    assert len([message for message in channel.sent if message.startswith('ARM')]) == 1
    assert not gate.local_action_idle(job)  # Offline evidence never promotes production closure.
    if not complete:
        assert not original_status(resource)['source_ready']
        assert not original_status(resource)['resources_closed']
        with gate.tx() as db:
            assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None
