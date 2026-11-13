"""无 ES client/模型/真实资源的 macos-es-v1 因果轨迹。"""
import json
import os

import pytest

from pilot1742 import maintenance as m
from pilot1742.maintenance_es import (
    EVENTS,
    AuditIdentity,
    Coverage,
    Event,
    OfflineES,
    Peer,
)


def ident(pid, version=1):
    return AuditIdentity((501, 501, 20, 501, 20, pid, 99, version))


class Trace:
    parent = ident(os.getpid())
    before = ident(200)
    helper = ident(200, 2)
    child = ident(300)
    peer = Peer(helper, 'signed-helper-v1')

    def __init__(self, tmp_path):
        self.gate = m.Gate(tmp_path / 'ledger')
        self.owner = self.gate.register('decision', local_actions=True)
        self.es = OfflineES(self.gate)
        self.seq = 40  # 首序号不是0/1。
        host, boot = m.local_epoch()
        self.es.source('source1', host, boot, Coverage(5, EVENTS, ()))
        self.event('EXIT', ident(999))  # 订阅后可信前沿
        self.resource = self.es.prepare('source1', self.owner, 'work', self.parent, self.peer.image, 'nonce1')
        self.calls = 0

    def event(self, kind, actor, target=None, image=None, *, jump=1, epoch='source1', version=5):
        self.seq += jump
        self.es.ingest(Event(epoch, self.seq, version, kind, actor, target, image))

    def exec_helper(self):
        self.event('FORK', self.parent, self.before)
        self.event('EXEC', self.before, self.helper, self.peer.image)

    def register(self):
        self.es.register_peer(self.resource, 'nonce1', self.peer)

    def arm(self):
        self.exec_helper()
        self.register()
        return self.es.arm(self.resource, self.peer)

    def dispatch(self):
        self.calls += 1
        self.event('FORK', self.helper, self.child)
        return self.child

    def launch(self):
        permit = self.arm()
        assert permit
        assert self.es.launch(self.resource, permit, self.peer, self.dispatch)
        return permit

    def close(self, *, wait=True):
        self.event('EXIT', self.child)
        if wait:
            self.es.waited(self.resource, self.peer, self.child, 143)
        self.event('EXIT', self.helper)

    def status(self):
        return self.es.status(self.resource)


@pytest.fixture
def trace(tmp_path):
    return Trace(tmp_path)


def test_exec_without_peer_and_wrong_peer_never_launch(trace):
    trace.exec_helper()
    assert trace.es.arm(trace.resource, trace.peer) is None
    trace.es.register_peer(trace.resource, 'nonce1', Peer(ident(201), trace.peer.image))
    assert trace.es.arm(trace.resource, trace.peer) is None
    assert trace.calls == 0
    assert trace.status()['offline_phase'] == 'REGISTERING'  # 其它helper不等于注册peer；等待精确EXEC。


def test_registration_before_exec_waits_and_ack_replay_dispatches_once(trace):
    trace.register()
    assert trace.es.arm(trace.resource, trace.peer) is None
    trace.exec_helper()
    first = trace.es.arm(trace.resource, trace.peer)
    assert first and trace.es.arm(trace.resource, trace.peer) == first
    assert trace.es.launch(trace.resource, first, trace.peer, trace.dispatch)
    assert not trace.es.launch(trace.resource, first, trace.peer, trace.dispatch)
    assert trace.calls == 1


def test_double_fork_setsid_and_reparent_do_not_release_descendant(trace):
    trace.launch()
    grandchild = ident(400)
    trace.event('FORK', trace.child, grandchild)
    # setsid/reparent不改变audit身份；无需凭ppid/进程组猜归属。
    trace.close()
    assert trace.status()['live'] == [grandchild.key]
    assert not trace.status()['process_closed']
    trace.event('EXIT', grandchild)
    assert trace.status()['resources_closed']


def test_long_lived_sibling_and_queued_unrelated_events_do_not_block(trace):
    trace.launch()
    trace.event('FORK', trace.parent, ident(900))
    trace.close()
    closed = trace.status()['closed_seq']
    assert trace.status()['process_closed']
    trace.event('FORK', ident(900), ident(901))
    assert trace.status()['closed_seq'] == closed
    assert trace.status()['resources_closed']
    assert trace.status()['business_code'] == 143  # 业务失败并不等于生命周期未结束。


@pytest.mark.parametrize('stale', [ident(300), ident(300, 9)])
def test_exec_migration_old_or_reused_identity_cannot_exit_new_execution(trace, stale):
    trace.launch()
    target = ident(300, 2)
    trace.event('EXEC', trace.child, target, 'business-image')
    trace.event('EXIT', stale)
    assert target.key in trace.status()['live']
    assert trace.status()['unknown'] == 'execution_identity_conflict'
    assert not trace.status()['process_closed']


@pytest.mark.parametrize('jump', [0, 2, -1])
def test_sequence_failure_precedes_final_exit_branch(trace, jump):
    trace.launch()
    trace.event('EXIT', trace.child)
    trace.es.waited(trace.resource, trace.peer, trace.child, 0)
    trace.event('EXIT', trace.helper, jump=jump)
    assert trace.helper.key in trace.status()['live']
    assert not trace.status()['process_closed']
    assert trace.status()['unknown'] == 'stream_discontinuity'


@pytest.mark.parametrize('reason', ['source_lost', 'configuration_changed', 'internal_drop'])
def test_source_loss_persistent_and_new_epoch_cannot_sign_old_action(trace, reason):
    trace.launch()
    trace.es.lost('source1', reason)
    reopened = OfflineES(trace.gate)
    host, boot = m.local_epoch()
    reopened.source('source2', host, boot, Coverage(5, EVENTS, ()))
    reopened.ingest(Event('source2', 1, 5, 'EXIT', trace.helper))
    assert reopened.status(trace.resource)['unknown'] == reason
    assert not reopened.status(trace.resource)['process_closed']
    with pytest.raises(ValueError, match='epoch cannot'):
        reopened.source('source1', host, boot, Coverage(5, EVENTS, ()))


def test_collector_restart_without_explicit_loss_taints(trace):
    trace.launch()
    reopened = OfflineES(trace.gate)
    assert reopened.status(trace.resource)['unknown'] == 'collector_reopened'
    assert not reopened.status(trace.resource)['resources_closed']


@pytest.mark.parametrize('coverage', [Coverage(4, EVENTS, ()), Coverage(5, ('FORK', 'EXIT'), ()),
                                      Coverage(5, EVENTS, ('default_path_mute',)),
                                      Coverage(5, EVENTS, ('inverted_process_mute',))])
def test_unverified_initial_coverage_never_arms(tmp_path, coverage):
    gate = m.Gate(tmp_path / 'gate')
    owner = gate.register('decision', local_actions=True)
    es = OfflineES(gate)
    host, boot = m.local_epoch()
    es.source('s', host, boot, coverage)
    es.ingest(Event('s', 10, 5, 'EXIT', ident(9)))
    with pytest.raises(ValueError, match='source not ready'):
        es.prepare('s', owner, 'work', ident(os.getpid()), 'helper', 'nonce')
    assert gate.status([])['inflight'] == []


def test_helper_exit_does_not_forge_business_wait(trace):
    trace.launch()
    trace.close(wait=False)
    assert trace.status()['process_closed']
    assert not trace.status()['business_waited']
    assert not trace.status()['resources_closed']


@pytest.mark.parametrize('kind', ['executor', 'review'])
def test_bound_boat_or_docker_still_requires_existing_resource_evidence(trace, tmp_path, kind):
    trace.launch()
    trace.close()
    assert trace.status()['resources_closed']
    binding = {'kind': kind, 'state_root': str(tmp_path / 'missing'), 'run_id': 'unclosed',
               'source_repo': str(tmp_path), 'ticket': 1742, 'target': {'run_id': 'unclosed'}}
    job = trace.status()['job']
    with trace.gate.tx() as db:
        db.execute('INSERT INTO bindings VALUES(?,?)', (job, json.dumps(binding)))
    assert not trace.status()['resources_closed']


def test_offline_completion_cannot_make_production_gate_drained(trace):
    trace.launch()
    trace.close()
    assert trace.status()['resources_closed']
    assert not trace.status()['production_accepted']
    owners = [trace.owner] + [trace.gate.register(lane) for lane in ('wayfinder', 'executor', 'review')]
    trace.gate.request()
    for owner in owners:
        trace.gate.poll(owner)
    assert not trace.gate.action_exited(trace.owner, trace.status()['job'], opaque_clear=True)
    trace.gate.finish(trace.owner, trace.status()['job'], natural=False)
    assert trace.gate.status([])['state'] == 'unknown'
    with trace.gate.tx() as db:
        assert not db.execute('SELECT 1 FROM local_resource_domains').fetchone()


def test_old_job_and_nonce_cannot_be_reused(trace):
    with pytest.raises(ValueError, match='unregistered'):
        trace.es.register_peer('old-resource', 'nonce1', trace.peer)
    with pytest.raises(ValueError, match='nonce already used'):
        trace.es.prepare('source1', trace.owner, 'other', trace.parent, trace.peer.image, 'nonce1')
    trace.gate.request()
    with pytest.raises(m.Closed):
        trace.es.prepare('source1', trace.owner, 'other', trace.parent, trace.peer.image, 'nonce2')
    # 先已准入的原动作不因关闸而不能继续。
    trace.launch()
    assert trace.calls == 1


def test_wrong_parent_image_and_premature_fork_do_not_arm(trace):
    trace.event('FORK', ident(777), trace.before)
    trace.event('EXEC', trace.before, trace.helper, trace.peer.image)
    trace.register()
    assert trace.es.arm(trace.resource, trace.peer) is None
    trace.exec_helper()
    trace.event('FORK', trace.helper, trace.child)
    assert trace.es.arm(trace.resource, trace.peer) is None
    assert trace.calls == 0


def test_wire_has_no_command_env_or_arbitrary_fields():
    wire = {'epoch': 's', 'seq': 2, 'version': 5, 'kind': 'EXIT', 'actor': ident(12).words,
            'target': None, 'image': None}
    assert Event.from_wire(wire).actor == ident(12)
    with pytest.raises(ValueError, match='non-whitelisted'):
        Event.from_wire(dict(wire, env='must-not-be-read'))
    with pytest.raises(ValueError):
        AuditIdentity((12,))


def test_wrong_epoch_or_low_message_version_taints_current_source(trace):
    trace.launch()
    trace.event('EXIT', trace.helper, epoch='other-source')
    assert trace.status()['unknown'] == 'stream_discontinuity'


def test_dispatch_exception_cannot_retry_or_sign_wait(trace):
    permit = trace.arm()
    def failed():
        trace.calls += 1
        raise OSError('offline spawn uncertainty')
    with pytest.raises(OSError):
        trace.es.launch(trace.resource, permit, trace.peer, failed)
    with pytest.raises(ValueError):
        trace.es.launch(trace.resource, permit, trace.peer, trace.dispatch)
    assert trace.calls == 1
    assert trace.status()['unknown'] == 'dispatch_uncertain'


def test_preexec_fork_cannot_smuggle_an_existing_descendant(trace):
    trace.event('FORK', trace.parent, trace.before)
    trace.event('FORK', trace.before, ident(555))
    trace.event('EXEC', trace.before, trace.helper, trace.peer.image)
    trace.register()
    assert trace.es.arm(trace.resource, trace.peer) is None
    assert trace.status()['unknown'] == 'helper_had_preexec_descendants'


def test_unrelated_preexec_sibling_children_do_not_pollute_helper(trace):
    sibling = ident(888)
    trace.event('FORK', trace.parent, sibling)
    trace.event('FORK', sibling, ident(889))
    trace.launch()
    trace.close()
    assert trace.status()['resources_closed']


def test_concurrent_ack_claim_enters_callback_once(trace):
    from concurrent.futures import ThreadPoolExecutor
    permit = trace.arm()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: trace.es.launch(trace.resource, permit, trace.peer, trace.dispatch), range(2)))
    assert sorted(results) == [False, True]
    assert trace.calls == 1


def test_malformed_wire_taints_without_storing_extra_fields(trace):
    trace.launch()
    with pytest.raises(ValueError, match='invalid ES wire event'):
        trace.es.ingest_wire({'command': 'forbidden-field'})
    assert trace.status()['unknown'] == 'internal_drop'
    with trace.gate.tx() as db:
        assert all('forbidden-field' not in r[0] for r in db.execute('SELECT data FROM es_audit'))


def test_no_source_replay_and_no_wait_for_wrong_primary(trace):
    trace.launch()
    with pytest.raises(ValueError, match='unbound business wait'):
        trace.es.waited(trace.resource, trace.peer, trace.helper, 0)
    trace.event('EXIT', trace.child, version=4)
    assert trace.status()['unknown'] == 'stream_discontinuity'


def test_wrong_scheduler_peer_cannot_prepare(trace):
    with pytest.raises(ValueError, match='scheduler peer'):
        trace.es.prepare('source1', trace.owner, 'other', ident(1), trace.peer.image, 'nonce2')
    assert len(trace.gate.status([])['inflight']) == 1


def test_wrong_helper_image_never_arms(trace):
    trace.event('FORK', trace.parent, trace.before)
    trace.event('EXEC', trace.before, trace.helper, 'untrusted-image')
    trace.register()
    assert trace.es.arm(trace.resource, trace.peer) is None
    assert trace.calls == 0


def test_event_commit_failure_poisoned_before_any_more_dispatch(trace, monkeypatch):
    import sqlite3
    from contextlib import contextmanager

    permit = trace.arm()
    original = trace.gate.tx
    calls = []
    @contextmanager
    def fail_once():
        calls.append(True)
        if len(calls) == 1:
            raise sqlite3.OperationalError('injected write failure')
        with original() as db:
            yield db
    monkeypatch.setattr(trace.gate, 'tx', fail_once)
    with pytest.raises(sqlite3.OperationalError):
        trace.event('EXIT', ident(900))
    with pytest.raises(ValueError, match='launch not permitted'):
        trace.es.launch(trace.resource, permit, trace.peer, trace.dispatch)
    assert trace.calls == 0
    assert trace.status()['unknown'] == 'internal_drop'
    assert OfflineES(trace.gate).status(trace.resource)['unknown'] == 'internal_drop'


@pytest.mark.parametrize('early', [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize('reverse_exec', [False, True])
def test_two_actions_bind_only_their_registered_peer(trace, early, reverse_exec):
    second = trace.es.prepare('source1', trace.owner, 'work2', trace.parent, trace.peer.image, 'nonce2')
    peer2 = Peer(ident(201, 2), trace.peer.image)
    entries = [(trace.resource, 'nonce1', trace.peer, trace.before), (second, 'nonce2', peer2, ident(201))]
    for index, (resource, nonce, peer, _) in enumerate(entries):
        if early[index]:
            trace.es.register_peer(resource, nonce, peer)
    for _, _, _, before in entries:
        trace.event('FORK', trace.parent, before)
    for _, _, peer, before in entries[::(-1 if reverse_exec else 1)]:
        trace.event('EXEC', before, peer.audit, peer.image)
    for index, (resource, nonce, peer, _) in enumerate(entries):
        if not early[index]:
            trace.es.register_peer(resource, nonce, peer)
        assert trace.es.arm(resource, peer)
        assert trace.es.status(resource)['live'] == [peer.audit.key]
        assert trace.es.status(resource)['unknown'] is None
    for index, (resource, _, peer, _) in enumerate(entries):
        primary = ident(500 + index)
        def dispatch(peer=peer, primary=primary):
            trace.event('FORK', peer.audit, primary)
            return primary
        assert trace.es.launch(resource, trace.es.arm(resource, peer), peer, dispatch)
        trace.event('EXIT', primary)
        trace.es.waited(resource, peer, primary, 143)
        trace.event('EXIT', peer.audit)
        assert trace.es.status(resource)['resources_closed']


@pytest.mark.parametrize('kind', ['FORK', 'EXIT'])
def test_late_registration_preserves_candidate_prearm_violation(trace, kind):
    trace.exec_helper()
    trace.event(kind, trace.helper, trace.child if kind == 'FORK' else None)
    trace.register()
    assert trace.es.arm(trace.resource, trace.peer) is None
    assert trace.status()['unknown'] is not None


@pytest.mark.parametrize('entry', ['malformed', 'source_lost', 'configuration_changed', 'internal_drop', 'source_replaced'])
def test_every_invalidation_revokes_before_failed_persistence(trace, monkeypatch, entry):
    import sqlite3
    from contextlib import contextmanager

    permit = trace.arm()
    original = trace.gate.tx
    @contextmanager
    def fail():
        raise sqlite3.OperationalError('injected unavailable ledger')
        yield
    monkeypatch.setattr(trace.gate, 'tx', fail)
    with pytest.raises(sqlite3.OperationalError):
        if entry == 'malformed':
            trace.es.ingest_wire({'unexpected': 'field'})
        elif entry == 'source_replaced':
            host, boot = m.local_epoch()
            trace.es.source('replacement', host, boot, Coverage(5, EVENTS, ()))
        else:
            trace.es.lost('source1', entry)
    monkeypatch.setattr(trace.gate, 'tx', original)
    assert trace.es.arm(trace.resource, trace.peer) is None
    with pytest.raises(ValueError, match='launch not permitted'):
        trace.es.launch(trace.resource, permit, trace.peer, trace.dispatch)
    assert trace.calls == 0
    assert not trace.status()['source_ready']
    assert trace.status()['offline_phase'] == 'UNKNOWN'
    # 重开持久化旧ready源的失联；新epoch不复活旧许可或代签动作。
    reopened = OfflineES(trace.gate)
    assert reopened.status(trace.resource)['unknown'] == 'collector_reopened'
    host, boot = m.local_epoch()
    reopened.source('new-source', host, boot, Coverage(5, EVENTS, ()))
    assert reopened.arm(trace.resource, trace.peer) is None
    with pytest.raises(ValueError, match='launch not permitted'):
        reopened.launch(trace.resource, permit, trace.peer, trace.dispatch)
    assert not reopened.status(trace.resource)['resources_closed']


def test_one_action_completes_while_sibling_registration_is_delayed(trace):
    second = trace.es.prepare('source1', trace.owner, 'work2', trace.parent, trace.peer.image, 'nonce2')
    peer2 = Peer(ident(201, 2), trace.peer.image)
    trace.exec_helper()
    trace.event('FORK', trace.parent, ident(201))
    trace.event('EXEC', ident(201), peer2.audit, peer2.image)
    trace.register()
    permit = trace.es.arm(trace.resource, trace.peer)
    assert trace.es.launch(trace.resource, permit, trace.peer, trace.dispatch)
    trace.close()
    trace.es.register_peer(second, 'nonce2', peer2)
    assert trace.es.arm(second, peer2)
    assert trace.es.status(second)['live'] == [peer2.audit.key]
    assert trace.es.status(second)['unknown'] is None
