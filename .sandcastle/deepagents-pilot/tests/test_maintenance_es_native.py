"""假来源仅验证协议与拒绝路径；不创建ES client，不伪造kernel peer证据。"""
import os

import pytest

from pilot1742 import maintenance as m
from pilot1742.maintenance_es import AuditIdentity, OfflineES, Peer
from pilot1742.maintenance_es_native import DevelopmentConsumer


def identity(pid, version=1):
    return AuditIdentity((501, 501, 20, 501, 20, pid, 99, version))


class Protocol:
    def __init__(self, tmp_path):
        self.gate = m.Gate(tmp_path / 'fixture-ledger')
        self.owner = self.gate.register('decision', local_actions=True)
        self.es = OfflineES(self.gate)
        self.sent = []
        self.consumer = DevelopmentConsumer(self.es, self.sent.append)
        self.consumer.accept({'type': 'source', 'epoch': 'fixture-source', 'protocol': 'macos-es-v1'})
        self.seq = 100
        self.event('EXIT', identity(999))
        self.parent, self.before, self.helper, self.primary = identity(os.getpid()), identity(200), identity(200, 2), identity(300)
        self.resource = self.es.prepare('fixture-source', self.owner, 'work', self.parent, 'managed-helper', 'nonce')

    def event(self, kind, actor, target=None, image=None):
        self.seq += 1
        self.consumer.accept({'type': 'event', 'event': dict(epoch='fixture-source', seq=self.seq, version=5,
                             kind=kind, actor=actor.words, target=target.words if target else None, image=image)})

    def register(self):
        self.consumer.accept(dict(type='register', resource=self.resource, nonce='nonce', image='managed-helper', peer=self.helper.words))

    def exec(self, image='managed-helper'):
        self.event('FORK', self.parent, self.before)
        self.event('EXEC', self.before, self.helper, image)

    def result(self, kind, **fields):
        self.consumer.accept(dict(type=kind, resource=self.resource, **fields))


@pytest.mark.parametrize('early', [False, True])
def test_native_protocol_waits_for_exec_and_durable_claim(tmp_path, early):
    p = Protocol(tmp_path)
    if early:
        p.register()
        assert not p.sent
    p.exec()
    if not early:
        p.register()
    assert len(p.sent) == 1 and p.sent[0].startswith(f'ARM {p.resource} nonce ')
    with p.gate.tx() as db:
        _, action = p.es._bound(db, p.resource)
        assert action.claimed
    # IPC START/WAIT can arrive before delayed ES events; PID alone grants no resource evidence.
    p.result('started', pid=300)
    p.result('waited', pid=300, code=143)
    assert not p.es.status(p.resource)['business_waited']
    p.event('FORK', p.helper, p.primary)
    assert p.es.status(p.resource)['business_waited']
    p.event('EXIT', p.primary)
    p.event('EXIT', p.helper)
    status = p.es.status(p.resource)
    assert p.sent[-1] == f'WAITED {p.resource} nonce\n'
    assert status['resources_closed'] and status['business_code'] == 143
    assert not status['production_accepted']


def test_unverified_exec_never_arms(tmp_path):
    p = Protocol(tmp_path)
    p.register()
    p.exec('other-executable')
    assert not p.sent


@pytest.mark.parametrize('failure', ['eof', 'configuration_changed', 'malformed', 'gap'])
def test_native_source_failures_never_arm(tmp_path, failure):
    p = Protocol(tmp_path)
    p.register()
    if failure == 'eof':
        p.consumer.lost()
    elif failure == 'configuration_changed':
        p.consumer.accept(dict(type='lost', epoch='fixture-source', reason=failure))
    elif failure == 'malformed':
        with pytest.raises(ValueError):
            p.consumer.accept({'type': 'register', 'self_reported_pid': 200})
    else:
        p.seq += 1
        p.event('EXIT', identity(999))
    assert not p.sent
    assert not p.es.status(p.resource)['source_ready']
    assert p.es.arm(p.resource, Peer(p.helper, 'managed-helper')) is None


def test_arm_write_failure_cannot_reissue_permit(tmp_path):
    p = Protocol(tmp_path)
    def fail(_):
        raise BrokenPipeError('isolated pipe')
    p.consumer.send = fail
    p.exec()
    with pytest.raises(BrokenPipeError):
        p.register()
    with p.gate.tx() as db:
        _, action = p.es._bound(db, p.resource)
        assert action.claimed
    assert p.es.status(p.resource)['unknown'] == 'source_lost'
    p.consumer.send = p.sent.append
    with pytest.raises(ValueError):
        p.register()
    assert not p.sent


def test_wait_without_original_fork_edge_never_completes(tmp_path):
    p = Protocol(tmp_path)
    p.register(); p.exec()
    p.result('started', pid=300)
    p.result('waited', pid=300, code=0)
    p.event('FORK', identity(800), p.primary)
    p.event('EXIT', p.helper)
    assert not p.es.status(p.resource)['resources_closed']
    assert not p.es.status(p.resource)['business_waited']


def test_native_duplicate_registration_poisoned_not_redispatched(tmp_path):
    p = Protocol(tmp_path)
    p.register(); p.exec()
    with pytest.raises(ValueError, match='duplicate'):
        p.register()
    assert len(p.sent) == 1
    assert not p.es.status(p.resource)['source_ready']


@pytest.mark.parametrize('frame', ['', 'not-json\n', '{}' * 3000])
def test_stream_eof_or_invalid_frame_revokes_before_closing_writer(tmp_path, frame):
    import io

    from pilot1742.maintenance_es_native import consume_stream
    p = Protocol(tmp_path)
    writer = io.StringIO()
    if frame:
        with pytest.raises(ValueError):
            consume_stream(p.consumer, io.StringIO(frame), writer)
    else:
        consume_stream(p.consumer, io.StringIO(frame), writer)
    assert writer.closed and p.consumer.failed
    assert not p.es.status(p.resource)['source_ready']
