"""手动 run 的入口绑定；不加载模型、客户端或真实执行器。"""
import os
from types import SimpleNamespace

from pilot1742 import executor, maintenance


def test_manual_run_has_binding_and_no_permanent_sighting(tmp_path, monkeypatch):
    gate = maintenance.Gate(maintenance.ROOT)
    unit = SimpleNamespace(run_id='manual-run', ticket=1742)
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    from pilot1742 import maintenance_recovery
    monkeypatch.setattr(maintenance_recovery, 'bound_idle', lambda binding: True)
    monkeypatch.setattr(maintenance_recovery, 'executor_idle', lambda binding: True)
    def run(argv, *, on_execution=None):
        if on_execution:
            on_execution()
        state = gate.status([('executor', os.getpid(), maintenance.identity(os.getpid()))])
        assert state['uncovered'] == []
        assert len(state['inflight']) == 1
        return 0
    monkeypatch.setattr(executor, '_main', run)
    assert executor.main(['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id,
                          '--private-key', '/unused', '--resume']) == 0
    assert gate.status([])['uncovered'] == []
    assert gate.status([])['inflight'] == []


def test_manual_run_closed_does_not_execute(tmp_path, monkeypatch):
    gate = maintenance.Gate(maintenance.ROOT)
    generation = gate.request()
    unit = SimpleNamespace(run_id='manual-run', ticket=1742)
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    def run(argv, *, on_execution):
        on_execution()
        raise AssertionError('closed gate executed work')
    monkeypatch.setattr(executor, '_main', run)
    assert executor.main(['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id]) == 75
    assert gate.status([])['generation'] == generation
    assert gate.status([])['inflight'] == []


def test_manual_same_run_can_continue_after_close_but_resources_stay_unknown(tmp_path, monkeypatch):
    from pilot1742 import maintenance_recovery
    gate = maintenance.Gate(maintenance.ROOT)
    unit = SimpleNamespace(run_id='manual-run', ticket=1742)
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    monkeypatch.setattr(maintenance_recovery, 'bound_idle', lambda binding: False)
    jobs = []
    def run(argv, *, on_execution):
        on_execution()
        jobs.append(gate.status([])['inflight'][0]['id'])
        return 2
    monkeypatch.setattr(executor, '_main', run)
    args = ['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id, '--resume']
    assert executor.main(args) == 2
    generation = gate.request()
    assert executor.main(args) == 2
    assert jobs[0] == jobs[1]
    assert gate.status([])['state'] == 'unknown'
    assert gate.status([])['generation'] == generation


def test_manual_read_only_command_never_registers_owner(monkeypatch):
    monkeypatch.setattr(executor, '_main', lambda argv, **kwargs: 0)
    monkeypatch.setattr(maintenance, 'Owner', lambda *a: (_ for _ in ()).throw(AssertionError('unexpected owner')))
    assert executor.main(['status', '--run-id', 'a']) == 0


def test_unbound_history_is_not_erased_by_exit_or_new_generation(tmp_path):
    gate = maintenance.Gate(tmp_path)
    gate.status([('executor', 999999, 'old-start')])
    first = gate.request()
    assert gate.status([])['uncovered']
    gate.resume(first)
    gate.request()
    assert gate.status([])['uncovered'][0]['pid'] == 999999


def test_manual_resume_keeps_live_serve_owner(tmp_path, monkeypatch):
    from pilot1742 import maintenance_recovery
    serve = maintenance.Owner('executor')
    gate = serve.gate
    unit = SimpleNamespace(run_id='manual-run', ticket=1742)
    job = gate.admit_executor(serve.id, unit.run_id, unit.ticket, tmp_path, executor.SOURCE_REPO)
    gate.request()
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    monkeypatch.setattr(maintenance_recovery, 'bound_idle', lambda binding: True)
    def run(argv, *, on_execution):
        on_execution()
        current = gate.status([])['inflight'][0]
        assert current['id'] == job and current['owner'] == serve.id
        return 0
    monkeypatch.setattr(executor, '_main', run)
    assert executor.main(['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id, '--resume']) == 0
    assert gate.status([])['inflight'] == []


def test_manual_cannot_overlap_live_controller(tmp_path):
    import pytest
    serve = maintenance.Owner('executor')
    job = serve.gate.admit_executor(serve.id, 'same-run', 1742, tmp_path, executor.SOURCE_REPO)
    serve.gate.start_bound(job, 'same-run', tmp_path)
    manual = maintenance.Owner('executor')
    assert manual.gate.admit_executor(manual.id, 'same-run', 1742, tmp_path,
                                     executor.SOURCE_REPO, manual=True) == job
    with pytest.raises(ValueError, match='previous executor unresolved'):
        manual.gate.start_bound(job, 'same-run', tmp_path)


def test_manual_preflight_failure_is_registered_without_claiming_work(tmp_path, monkeypatch):
    gate = maintenance.Gate(maintenance.ROOT)
    def run(argv, **kwargs):
        state = gate.status([('executor', os.getpid(), maintenance.identity(os.getpid()))])
        assert state['uncovered'] == []
        assert state['inflight'] == []
        return 2  # 凭据/参数预检失败，没有进入执行回调。
    monkeypatch.setattr(executor, '_main', run)
    assert executor.main(['--state-root', str(tmp_path), 'run', '--run-id', 'a']) == 2
    assert gate.status([])['uncovered'] == []
