"""d3db 静态发现的隔离反例，模型/资源均不启动。"""
import json
import os
from types import SimpleNamespace

import pytest
from test_maintenance_resources import failed_review as failed_review_fixture

from pilot1742 import executor, maintenance, maintenance_recovery
from pilot1742.external_review import MODELS

failed_review = failed_review_fixture


def test_identity_is_independent_of_terminal_timezone(monkeypatch):
    monkeypatch.setenv('TZ', 'UTC')
    utc = maintenance.identity(os.getpid())
    monkeypatch.setenv('TZ', 'America/Los_Angeles')
    monkeypatch.setenv('LC_ALL', 'zh_CN.UTF-8')
    assert maintenance.identity(os.getpid()) == utc


def test_manual_retryable_exit_preserves_same_run_permit(tmp_path, monkeypatch):
    unit = SimpleNamespace(run_id='same-run', ticket=1742)
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    monkeypatch.setattr(maintenance_recovery, 'bound_idle', lambda _: True)
    def run(argv, *, on_execution):
        on_execution()
        return 75
    monkeypatch.setattr(executor, '_main', run)
    args = ['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id, '--resume']
    assert executor.main(args) == 75
    gate = maintenance.Gate(maintenance.ROOT)
    jobs = gate.status([])['inflight']
    assert len(jobs) == 1
    gate.request()
    assert executor.main(args) == 75
    assert gate.status([])['inflight'][0]['id'] == jobs[0]['id']


def test_removed_prepare_without_launch_has_no_model_resources(failed_review):
    lane, target, worker, _, _ = failed_review
    for path in worker.iterdir():
        path.unlink()
    lane.checkout_root = lane.state_root / "checkouts"
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    (worker / 'prepare.json').write_text(json.dumps({'run_id': target.run_id, 'checkout': str(checkout)}))
    (worker / 'checkout-cleanup.json').write_text(json.dumps({'state': 'removed', 'checkout': str(checkout)}))
    assert lane.maintenance_idle()
    (worker / 'process.json').write_text('{}')
    assert not lane.maintenance_idle()


@pytest.mark.parametrize('lane', ['decision', 'wayfinder'])
def test_local_action_unknown_recovers_only_after_bound_host_boot_ends(tmp_path, monkeypatch, lane):
    epoch = ['host-identity', 'boot-before']
    monkeypatch.setattr(maintenance, 'local_epoch', lambda: tuple(epoch))
    gate = maintenance.Gate(tmp_path)
    owner = gate.register(lane, local_actions=True)
    job = gate.admit(owner, 'action:1')
    gate.finish(owner, job, natural=False)
    generation = gate.request()
    monkeypatch.setattr(maintenance, 'alive', lambda *a: False)
    assert gate.reconcile(generation, owner)['reason'] == 'missing_bound_completion'
    epoch[:] = ['other-host', 'boot-after']
    assert gate.reconcile(generation, owner)['result'] == 'unknown'
    epoch[:] = ['host-identity', 'boot-after']
    assert gate.reconcile(generation, owner)['result'] == 'reconciled'
    with gate.tx() as db:
        assert db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'unknown'
        proof = dict(db.execute('SELECT * FROM epoch_resolutions WHERE job=?', (job,)).fetchone())
        assert proof['old_boot'] == 'boot-before' and proof['new_boot'] == 'boot-after'
        assert not db.execute('SELECT * FROM action_returns').fetchall()
    gate.resume(generation)
    gate.request()
    assert gate.status([])['state'] == 'unknown'  # 资源退休不确认下一代入口。


def test_boot_change_cannot_retrofit_old_unbound_action(tmp_path, monkeypatch):
    gate = maintenance.Gate(tmp_path)
    owner = gate.register('decision')
    job = gate.admit(owner, 'action:1')
    gate.finish(owner, job, natural=False)
    generation = gate.request()
    monkeypatch.setattr(maintenance, 'alive', lambda *a: False)
    monkeypatch.setattr(maintenance, 'local_epoch', lambda: ('host', 'new-boot'))
    assert gate.reconcile(generation, owner)['reason'] == 'missing_bound_completion'


def test_review_reservation_exit_before_adopt_recovers_without_process_disappearance(tmp_path, monkeypatch):
    from pilot1742 import maintenance_spawn
    from pilot1742.review_sweep import spawner
    owner = maintenance.Owner('review', tmp_path)
    children = []
    def withhold(self):
        children.append(self)
        self.close()  # deterministic release rejection: real bootstrap exits, no target exec.
    monkeypatch.setattr(maintenance_spawn.Launch, 'release', withhold)
    spawn = spawner(tmp_path / 'unused', owner)
    pid = spawn(1, 1, 'a'*40, tmp_path / 'log')
    assert children[0].process.wait(timeout=5) == 78
    assert spawn.reap() == [pid]
    assert spawn.reap() == []
    assert owner.gate.status([])['inflight'] == []
    spawn(1, 1, 'a'*40, tmp_path / 'log')  # 原 attempt 可重试。
    children[1].process.wait(timeout=5)
    assert spawn.reap() == [children[1].pid]


def test_review_adopt_wins_over_parent_exit_cleanup(tmp_path):
    parent = maintenance.Owner('review', tmp_path)
    job = parent.reserve('pr:1:head:1')
    child = maintenance.Owner('review', tmp_path, job)
    assert not parent.gate.spawn_exited(parent.id, job, 424242, 1)
    assert child.gate.status([])['inflight'][0]['owner'] == child.id


def test_executor_poll_failure_skips_intake_and_retries(tmp_path, monkeypatch, capsys):
    import sqlite3

    from pilot1742 import queue
    events = []
    def poll():
        events.append('poll')
        if len(events) == 1:
            raise sqlite3.OperationalError('isolated unavailable')
        return False
    owner = SimpleNamespace(coverage=lambda _: None, poll=poll, stop=lambda: events.append('stop'))
    monkeypatch.setattr(maintenance, 'Owner', lambda _: owner)
    monkeypatch.setattr(executor, '_client', lambda _: SimpleNamespace(close=lambda: events.append('close')))
    monkeypatch.setattr(executor, 'RepoGateway', lambda c: c)
    monkeypatch.setattr(queue, 'QueueIntake', lambda *a: SimpleNamespace(once=lambda child: events.append('intake')))
    args = SimpleNamespace(review_sweep=False, once=False, poll_seconds=1, state_root=tmp_path)
    monkeypatch.setattr(executor.time, 'sleep', lambda _: setattr(args, 'once', True))
    assert executor._serve(args, None, SimpleNamespace(load=lambda: None), tmp_path) == 0
    assert events == ['poll', 'poll', 'intake', 'stop', 'close']
    assert 'maintenance unavailable' in capsys.readouterr().err


@pytest.mark.parametrize('damage', ['wrong-path', 'retained-checkout', 'unexpected-file'])
def test_unlaunched_prepare_requires_exact_removed_checkout(failed_review, damage):
    lane, target, worker, _, _ = failed_review
    for path in worker.iterdir():
        path.unlink()
    lane.checkout_root = lane.state_root / 'checkouts'
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    (worker / 'prepare.json').write_text(json.dumps({'run_id': target.run_id, 'checkout': str(checkout)}))
    (worker / 'checkout-cleanup.json').write_text(json.dumps({'state': 'removed', 'checkout': str(checkout)}))
    if damage == 'wrong-path':
        (worker / 'checkout-cleanup.json').write_text(json.dumps({'state': 'removed', 'checkout': 'elsewhere'}))
    elif damage == 'retained-checkout':
        checkout.mkdir(parents=True)
    else:
        (worker / 'unclassified.json').write_text('{}')
    assert not lane.maintenance_idle()


def test_closed_sweep_reaps_unadopted_resume_and_does_not_dispatch(tmp_path, monkeypatch):
    from pilot1742 import maintenance_spawn
    from pilot1742.review_sweep import ServeRound, Sweep, spawner
    owner = maintenance.Owner('review', tmp_path / 'gate')
    children = []
    def withhold(self):
        children.append(self)
        self.close()
    monkeypatch.setattr(maintenance_spawn.Launch, 'release', withhold)
    sweep = object.__new__(Sweep)
    sweep.folder = tmp_path / 'sweep'
    sweep.spawn = spawner(tmp_path / 'unused', owner)
    sweep._launch_markers = {}
    sweep._launch = lambda number, head, attempt: sweep.spawn(number, attempt, head, tmp_path / 'log')
    marker = sweep.folder / 'attempt.resumes'
    sweep._launch_marked(marker, 1, 'a'*40, 1)
    assert children[0].process.wait(timeout=5) == 78
    owner.gate.request()
    sweep.lane = SimpleNamespace(state_root=tmp_path / 'reviews', source=tmp_path,
                                 maintenance_idle=lambda: True)
    sweep.tick = lambda: pytest.fail('closed sweep must not dispatch')
    assert ServeRound(sweep, maintenance=owner)() is None
    assert not marker.exists()
    assert owner.gate.status([])['inflight'] == []
    assert owner.gate.status([])['generation'] == 1


def test_boot_evidence_change_during_reconcile_does_not_commit(tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, 'local_epoch', lambda: ('host', 'before'))
    gate = maintenance.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'action')
    gate.finish(owner, job, natural=False)
    generation = gate.request()
    epochs = iter([('host', 'after'), ('host', 'another')])
    monkeypatch.setattr(maintenance, 'local_epoch', lambda: next(epochs))
    assert gate.reconcile(generation, owner)['reason'] == 'local_epoch_changed'
    with gate.tx() as db:
        assert not db.execute('SELECT * FROM resolutions').fetchall()


def test_executor_loop_does_not_swallow_intake_business_error(tmp_path, monkeypatch):
    from pilot1742 import queue
    events = []
    owner = SimpleNamespace(coverage=lambda _: None, poll=lambda: False, stop=lambda: events.append('stop'))
    monkeypatch.setattr(maintenance, 'Owner', lambda _: owner)
    monkeypatch.setattr(executor, '_client', lambda _: SimpleNamespace(close=lambda: events.append('close')))
    monkeypatch.setattr(executor, 'RepoGateway', lambda c: c)
    failure = ValueError('invalid unit filename')
    def intake(child):
        raise failure
    monkeypatch.setattr(queue, 'QueueIntake', lambda *a: SimpleNamespace(once=intake))
    monkeypatch.setattr(executor.time, 'sleep', lambda _: pytest.fail('business error must not become a silent retry'))
    args = SimpleNamespace(review_sweep=False, once=False, poll_seconds=1, state_root=tmp_path)
    with pytest.raises(ValueError) as result:
        executor._serve(args, None, SimpleNamespace(load=lambda: None), tmp_path)
    assert result.value is failure
    assert events == ['stop', 'close']
