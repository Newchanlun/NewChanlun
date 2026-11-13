"""正式双 BLOCK 的隔离生命周期反例；不使用模型或生产控制根。"""

import pytest

from pilot1742 import maintenance as module
from pilot1742 import maintenance_recovery as evidence
from pilot1742.maintenance import Owner


def test_failed_reservation_can_retry_without_erasing_history(tmp_path):
    owner = Owner('review', tmp_path)
    job = owner.reserve('pr:1:abc:1')
    owner.gate.cancel_unstarted(owner.id, job, 'spawn_failed')
    assert owner.gate.status([])['inflight'] == []
    assert owner.reserve('pr:1:abc:1') != job


def test_cancel_cannot_revoke_adopted_child(tmp_path):
    owner = Owner('review', tmp_path)
    job = owner.reserve('pr:1:abc:1')
    child = Owner('review', tmp_path, job)
    with pytest.raises(ValueError): owner.gate.cancel_unstarted(owner.id, job, 'spawn_failed')
    assert child.gate.status([])['inflight']


def test_same_run_crash_can_resume_but_only_completed_recovery_settles(tmp_path, monkeypatch):
    owner = Owner('executor', tmp_path / 'gate')
    job = owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source')
    first = owner.gate.start_bound(job, 't1-1', tmp_path / 'state')
    with owner.gate.tx() as db:
        db.execute('UPDATE witnesses SET pid=?,start=? WHERE id=?', (999999, 'dead', first))
    owner.gate.request()
    assert owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source') == job
    second = owner.gate.start_bound(job, 't1-1', tmp_path / 'state')
    monkeypatch.setattr(evidence, 'bound_idle', lambda _: False)
    owner.gate.returned(second)
    assert not owner.gate.settle_bound(owner.id, job)
    assert owner.gate.status([])['inflight']
    monkeypatch.setattr(evidence, 'bound_idle', lambda _: True)
    owner.gate.complete_bound(second)
    assert owner.gate.settle_bound(owner.id, job)
    assert not owner.gate.status([])['inflight']
    with owner.gate.tx() as db:
        assert db.execute('SELECT 1 FROM returns WHERE witness=?', (first,)).fetchone() is None


def test_exit_without_witness_is_not_completion(tmp_path):
    owner = Owner('executor', tmp_path / 'gate')
    job = owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source')
    assert not owner.gate.settle_bound(owner.id, job)
    assert owner.gate.status([])['inflight']


def test_census_excludes_readonly_and_dry_entries(monkeypatch):
    commands = ['python -m pilot1742.external_review status --pr 1',
                'python -m pilot1742.external_review reconcile --run-id x --note y',
                'node /tmp/decision-claimer.mts --dry-run',
                'node /tmp/decision-claimer.mts --live --archaeology-only --ticket 1',
                'node /tmp/wayfinder_engine.mts --once --dry-run']
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: type('R', (), {'stdout': '\n'.join(
        f'{100+i} 1 {command}' for i, command in enumerate(commands))})())
    monkeypatch.setattr(module, 'identity', lambda _: 'fixture')
    assert module.process_inventory() == []


def test_new_run_never_rebinds_old_job_or_inherits_closed_permission(tmp_path):
    from pilot1742.maintenance import Closed
    owner = Owner('executor', tmp_path / 'gate')
    first = owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source')
    second = owner.gate.admit_executor(owner.id, 't1-2', 1, tmp_path / 'state', tmp_path / 'source')
    assert first != second
    owner.gate.request()
    with pytest.raises(Closed):
        owner.gate.admit_executor(owner.id, 't1-3', 1, tmp_path / 'state', tmp_path / 'source')
    assert len(owner.gate.status([])['inflight']) == 2  # 不按代次隐藏真实未收尾任务


def test_returned_error_still_needs_bound_resource_completion(tmp_path, monkeypatch):
    owner = Owner('executor', tmp_path / 'gate')
    job = owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source')
    witness = owner.gate.start_bound(job, 't1-1', tmp_path / 'state')
    owner.gate.returned(witness)
    monkeypatch.setattr(evidence, 'bound_idle', lambda _: False)
    assert not owner.gate.settle_bound(owner.id, job)
    monkeypatch.setattr(evidence, 'bound_idle', lambda _: True)
    assert owner.gate.settle_bound(owner.id, job)


def test_manual_review_identity_error_is_proven_unstarted(tmp_path, monkeypatch):
    from pilot1742 import external_review
    monkeypatch.setattr(module, 'ROOT', tmp_path / 'gate')
    assert external_review.main(['review-pr', '--pr', '1', '--private-key', str(tmp_path / 'absent')]) == 2
    assert module.Gate(tmp_path / 'gate').status([])['inflight'] == []


def test_executor_exception_records_return_not_resource_success(tmp_path, monkeypatch):
    from pilot1742 import executor
    owner = Owner('executor', tmp_path / 'gate')
    job = owner.gate.admit_executor(owner.id, 't1-1', 1, tmp_path / 'state', tmp_path / 'source')
    def failed(_, *, on_execution):
        on_execution()
        raise RuntimeError('ordinary controlled failure')
    monkeypatch.setattr(executor, '_main', failed)
    with pytest.raises(RuntimeError):
        executor.main(['--maintenance-job', job, '--maintenance-root', str(owner.gate.root),
                       '--state-root', str(tmp_path / 'state'), '--run-id', 't1-1'])
    with owner.gate.tx() as db:
        assert db.execute('SELECT count(*) FROM returns').fetchone()[0] == 1
        assert db.execute('SELECT completed_at FROM witnesses').fetchone()[0] is None
    assert not owner.gate.settle_bound(owner.id, job)


def test_census_uses_last_mode_flag(monkeypatch):
    commands = ['node /tmp/decision-claimer.mts --dry-run --live',
                'node /tmp/wayfinder_engine.mts --live --dry-run',
                'node /tmp/wayfinder_engine.mts --dry-run --live']
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: type('R', (), {'stdout': '\n'.join(
        f'{100+i} 1 {command}' for i, command in enumerate(commands))})())
    monkeypatch.setattr(module, 'identity', lambda _: 'fixture')
    assert {(lane, pid) for lane, pid, _ in module.process_inventory()} == {('decision', 100), ('wayfinder', 102)}


def test_unknown_requires_evidence_resolution_not_natural_boolean(tmp_path):
    owner = Owner('executor', tmp_path)
    job = owner.admit('ticket:1')
    owner.finish(job, natural=False)
    with pytest.raises(ValueError):
        owner.finish(job, natural=True)
    assert owner.gate.status([])['inflight']
