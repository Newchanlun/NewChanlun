"""一次控制读取失败不应永久终止observer；不补签任务终态。"""
import sqlite3
import threading
from types import SimpleNamespace

from pilot1742 import maintenance as m


def test_observer_retries_transient_poll_without_completing_work(tmp_path, monkeypatch):
    owner = m.Owner('decision', tmp_path / 'gate')
    job = owner.admit('ongoing')
    owner.gate.request()
    original = owner.poll
    calls = []
    recovered = threading.Event()
    def poll():
        calls.append(True)
        if len(calls) == 2:
            raise sqlite3.OperationalError('isolated transient')
        result = original()
        if len(calls) >= 3:
            recovered.set()
        return result
    monkeypatch.setattr(owner, 'poll', poll)
    with owner.observing():
        assert recovered.wait(2), 'observer stopped after one transient error'
        status = owner.gate.status([])
        assert 'decision' not in status['unconfirmed']
        assert status['inflight'][0]['id'] == job


def test_census_exit_race_is_transient_refusal_not_permanent_sighting(tmp_path, monkeypatch):
    gate = m.Gate(tmp_path)
    output = '99999 1 node wayfinder_engine.mts --live --maintenance-root /isolated'
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=output))
    monkeypatch.setattr(m, 'identity', lambda _: (_ for _ in ()).throw(ValueError('process unavailable')))
    try:
        gate.status()
    except ValueError:
        pass
    else:
        raise AssertionError('cannot silently claim full census after failed identity read')
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=''))
    assert gate.status()['uncovered'] == []


def test_successful_poll_does_not_restore_failed_resource_coverage(tmp_path):
    owner = m.Owner('executor', tmp_path)
    owner.gate.request()
    owner.coverage(False)
    owner.gate.observer_failed(owner.id)
    owner.poll()
    status = owner.gate.status([])
    assert status['observer_faults'] == []
    assert 'executor' in status['unconfirmed']
    assert status['owners'][0]['covered'] == 0


def test_persisted_observer_failure_is_unknown_until_same_owner_poll(tmp_path):
    owners = [m.Owner(lane, tmp_path) for lane in m.LANES]
    gate = owners[0].gate
    gate.request()
    for owner in owners:
        owner.poll()
    assert gate.status([])['state'] == 'drained'
    gate.observer_failed(owners[0].id)
    assert m.Gate(tmp_path).status([])['state'] == 'unknown'
    owners[0].poll()
    assert gate.status([])['state'] == 'drained'


def test_same_pid_preflight_and_serve_owners_do_not_mask_resource_failure(tmp_path):
    owners = [m.Owner(lane, tmp_path) for lane in m.LANES]
    preflight = m.Owner('executor', tmp_path)
    gate = preflight.gate
    gate.request()
    for owner in [*owners, preflight]:
        owner.poll()
    executor = owners[2]
    executor.coverage(False)
    assert gate.status([])['state'] == 'unknown'
    executor.coverage(True)  # 隔离清点证明已结束，非poll自动补签。
    executor.stop()
    preflight.stop()
    assert gate.status([])['state'] == 'drained'


def test_queue_early_returns_recover_on_next_verified_round(tmp_path):
    import fcntl

    from pilot1742.claims import ClaimStore
    from pilot1742.cutover import CutoverError
    from pilot1742.queue import QueueIntake

    owners = [m.Owner(lane, tmp_path / 'gate') for lane in m.LANES]
    owner = owners[2]
    owner.gate.request()
    for item in owners:
        item.poll()
    state = tmp_path / 'state'
    state.mkdir()
    claims = ClaimStore(tmp_path / 'claims')
    def inactive():
        raise CutoverError('isolated inactive cutover')
    cutover = SimpleNamespace(load=inactive)
    intake = QueueIntake(state, SimpleNamespace(queue=lambda _: []), claims, cutover, tmp_path / 'source', owner)
    def no_dispatch(_):
        raise AssertionError('closed intake must not dispatch')
    assert intake.once(no_dispatch) == {}
    assert owner.gate.status([])['state'] == 'unknown'
    cutover.load = lambda: None
    claims.root.mkdir(parents=True, exist_ok=True)
    with (claims.root / 'serve.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert intake.once(no_dispatch) == {}
        assert owner.gate.status([])['state'] == 'unknown'
    assert intake.once(no_dispatch) == {}
    assert owner.gate.status([])['state'] == 'drained'
