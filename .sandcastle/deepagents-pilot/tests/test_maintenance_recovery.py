"""离线恢复协议与生命周期绑定反例；不读生产账本、不调用模型。"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pilot1742 import maintenance as module
from pilot1742 import maintenance_recovery as evidence
from pilot1742.maintenance import Gate, Owner


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    live = {41001: 'old-start', os.getpid(): 'witness-start'}
    monkeypatch.setattr(module, 'identity', lambda pid: live[pid])
    monkeypatch.setattr(module, 'alive', lambda pid, start: live.get(pid) == start)
    gate = Gate(tmp_path / 'gate')
    owner = gate.register('executor', 41001)
    job = gate.admit(owner, 'ticket:1742')
    gate.bind_executor(owner, job, 't1742-1', tmp_path / 'state', tmp_path / 'source')
    monkeypatch.setattr(evidence, 'bound_idle', lambda binding: True)
    generation = gate.request()
    gate.poll(owner)
    return gate, owner, job, generation, live


def complete(recovery):
    gate, owner, job, generation, live = recovery
    witness = gate.start_bound(job, 't1742-1', gate.root.parent / 'state')
    gate.complete_bound(witness)
    # 模拟父失联、执行子进程正常退出；不是据此产生完成证据。
    live.clear()
    return witness


def test_orphan_completion_reconciles_without_rewriting_history_or_resuming(recovery):
    gate, owner, job, generation, _ = recovery
    witness = complete(recovery)
    assert gate.reconcile(generation, owner)['result'] == 'reconciled'
    with gate.tx() as db:
        assert db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'active'
        assert db.execute('SELECT stopped FROM owners WHERE id=?', (owner,)).fetchone()[0] == 0
        assert db.execute('SELECT witness FROM resolutions WHERE job=?', (job,)).fetchone()[0] == witness
        assert db.execute('SELECT closed FROM control').fetchone()[0] == 1
    assert gate.status([])['inflight'] == []
    assert gate.status([])['state'] == 'unknown'  # 仍须当前活跃四入口确认


def test_missing_completion_and_pid_reuse_cannot_reconcile(recovery):
    gate, owner, job, generation, live = recovery
    gate.start_bound(job, 't1742-1', gate.root.parent / 'state')
    live[41001] = 'reused-start'
    live.pop(os.getpid())
    assert gate.reconcile(generation, owner)['reason'] == 'missing_bound_completion'


def test_unbound_receipt_and_wrong_run_cannot_complete(recovery):
    gate, owner, job, generation, live = recovery
    with pytest.raises(ValueError): gate.start_bound(job, 'different-run', gate.root.parent / 'state')
    (gate.root / 'receipt.json').write_text(json.dumps({'job': job, 'container_closed': True}))
    live.clear()
    assert gate.reconcile(generation, owner)['result'] == 'unknown'


def test_resource_regression_blocks_recorded_completion(recovery, monkeypatch):
    gate, owner, _, generation, _ = recovery
    complete(recovery)
    monkeypatch.setattr(evidence, 'bound_idle', lambda binding: False)
    assert gate.reconcile(generation, owner)['reason'] == 'resources_unsettled'


def test_concurrent_reconcile_is_idempotent_and_old_generation_rejected(recovery):
    gate, owner, _, generation, _ = recovery
    complete(recovery)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: gate.reconcile(generation, owner), range(2)))
    assert all(result['result'] == 'reconciled' for result in results)
    with gate.tx() as db:
        assert db.execute('SELECT count(*) FROM reconciliations').fetchone()[0] == 1
    gate.resume(generation)
    gate.request()
    with pytest.raises(ValueError): gate.reconcile(generation, owner)
    assert gate.status([])['state'] == 'unknown'


def test_generation_change_during_evidence_read_cannot_commit(recovery, monkeypatch):
    gate, owner, _, generation, _ = recovery
    complete(recovery)
    def moved(binding):
        gate.resume(generation)
        gate.request()
        return True
    monkeypatch.setattr(evidence, 'bound_idle', moved)
    with pytest.raises(ValueError): gate.reconcile(generation, owner)
    with gate.tx() as db:
        assert db.execute('SELECT count(*) FROM resolutions').fetchone()[0] == 0


def test_lost_idle_owner_requires_current_census_not_just_disappearance(tmp_path, monkeypatch):
    owner = Owner('decision', tmp_path)
    gate = owner.gate
    generation = gate.request()
    monkeypatch.setattr(module, 'alive', lambda *args: False)
    assert gate.reconcile(generation, owner.id)['reason'] == 'missing_scope_checkpoint'
    monkeypatch.undo()
    owner.poll()  # 原子关闭确认、无任何在途工作
    monkeypatch.setattr(module, 'alive', lambda *args: False)
    assert gate.reconcile(generation, owner.id)['result'] == 'reconciled'
    with pytest.raises(ValueError): owner.admit('new')


def test_unbound_legacy_job_stays_unknown(tmp_path, monkeypatch):
    owner = Owner('executor', tmp_path)
    owner.admit('ticket:1')
    generation = owner.gate.request()
    monkeypatch.setattr(module, 'alive', lambda *args: False)
    assert owner.gate.reconcile(generation, owner.id)['reason'] == 'missing_bound_completion'


def test_new_witness_during_verification_invalidates_snapshot(recovery, monkeypatch):
    gate, owner, job, generation, live = recovery
    complete(recovery)
    def started(binding):
        live[os.getpid()] = 'new-witness'
        gate.start_bound(job, 't1742-1', gate.root.parent / 'state')
        return True
    monkeypatch.setattr(evidence, 'bound_idle', started)
    assert gate.reconcile(generation, owner)['reason'] == 'evidence_changed'


def test_executor_binding_uses_workunit_and_requires_real_run(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pilot1742 import executor
    monkeypatch.setattr(executor, 'load_unit', lambda *args: (SimpleNamespace(run_id='t1742-1', ticket=1743), None))
    binding = dict(state_root=str(tmp_path), source_repo=str(tmp_path), run_id='t1742-1', work='ticket:1742')
    assert not evidence.executor_idle(binding)
    monkeypatch.setattr(executor, 'load_unit', lambda *args: (SimpleNamespace(run_id='t1742-1', ticket=1742), None))
    assert not evidence.executor_idle(binding)


def test_real_orphan_publishes_bound_completion_after_owner_exits(tmp_path):
    import subprocess
    import sys
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    parent = subprocess.run([sys.executable, '-c',
        'from pilot1742.maintenance import Owner; from pathlib import Path; import sys,json; '
        'r=Path(sys.argv[1]); o=Owner("executor",r); j=o.admit("ticket:1742"); '
        'o.gate.bind_executor(o.id,j,"t1742-1",r,r); print(json.dumps([o.id,j]))', str(tmp_path)],
        capture_output=True, text=True, check=True, env=env)
    owner, job = json.loads(parent.stdout)
    gate = Gate(tmp_path)
    generation = gate.request()
    child = subprocess.Popen([sys.executable, '-u', '-c',
        'from pilot1742.maintenance import Gate; from pilot1742 import maintenance_recovery as e; '
        'from pathlib import Path; import sys; r=Path(sys.argv[1]); g=Gate(r); '
        'w=g.start_bound(sys.argv[2],"t1742-1",r); print("started",flush=True); sys.stdin.readline(); '
        'e.bound_idle=lambda b: True; g.complete_bound(w)', str(tmp_path), job],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, start_new_session=True)
    try:
        assert child.stdout.readline().strip() == 'started'
        assert gate.reconcile(generation, owner)['result'] == 'unknown'
        child.communicate('\n', timeout=10)
        assert child.returncode == 0
        # 正常测试资源适配器另有反例锁；此处验证真实进程身份和父退出后写入。
        from unittest.mock import patch
        with patch.object(evidence, 'bound_idle', return_value=True):
            assert gate.reconcile(generation, owner)['result'] == 'reconciled'
    finally:
        if child.poll() is None:
            child.communicate('\n', timeout=10)


def test_recovered_history_does_not_ack_new_generation(recovery):
    gate, owner, job, generation, live = recovery
    complete(recovery)
    assert gate.reconcile(generation, owner)['result'] == 'reconciled'
    live[os.getpid()] = 'new-owner'
    items = [Owner(lane, gate.root) for lane in module.LANES]
    for item in items:
        item.poll()
    assert gate.status([])['state'] == 'drained'
    gate.resume(generation)
    next_generation = gate.request()
    assert gate.status([])['state'] == 'unknown'
    assert gate.reconcile(next_generation, owner)['result'] == 'reconciled'
    assert gate.status([])['state'] == 'unknown'
    live[41001] = 'old-start'
    with pytest.raises(ValueError): gate.admit(owner, 'ticket:2')


def test_executor_entry_preserves_return_and_requires_cleanup(recovery, monkeypatch):
    from pilot1742 import executor
    gate, owner, job, _, _ = recovery
    monkeypatch.setattr(executor, '_main', lambda args: 2)
    monkeypatch.setattr(evidence, 'bound_idle', lambda binding: False)
    argv = ['--state-root', str(gate.root.parent / 'state'), 'run', '--run-id', 't1742-1',
            '--maintenance-root', str(gate.root), '--maintenance-job', job]
    assert executor.main(argv) == 2
    with gate.tx() as db:
        assert db.execute('SELECT completed_at FROM witnesses').fetchone()[0] is None


def test_returned_busy_invocation_can_continue_but_not_reconcile_until_resources_end(recovery, monkeypatch):
    gate, owner, job, generation, live = recovery
    first = gate.start_bound(job, 't1742-1', gate.root.parent / 'state')
    gate.returned(first)  # 正常 busy 返回不伪造资源关闭，也不阻止原任务下一轮
    second = gate.start_bound(job, 't1742-1', gate.root.parent / 'state')
    gate.returned(second)
    live.clear()
    monkeypatch.setattr(evidence, 'bound_idle', lambda binding: False)
    assert gate.reconcile(generation, owner)['reason'] == 'resources_unsettled'
    monkeypatch.setattr(evidence, 'bound_idle', lambda binding: True)
    assert gate.reconcile(generation, owner)['result'] == 'reconciled'


def test_executor_adapter_retains_boat_effect_unknown(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pilot1742 import executor
    from pilot1742.domain import EffectUnknown
    from pilot1742.run import PilotRun
    run_id = 't1742-1'
    monkeypatch.setattr(executor, 'load_unit', lambda *args: (SimpleNamespace(run_id=run_id, ticket=1742), None))
    folder = PilotRun.run_dir(tmp_path, run_id)
    folder.mkdir(parents=True)
    (folder / 'run.json').write_text('{}')
    closed = []
    backend = SimpleNamespace(is_drained=lambda key: bool(closed))
    run = SimpleNamespace(spec=SimpleNamespace(run_id=run_id), execution=backend,
                          _keys=lambda: [__import__('collections').namedtuple('Key', 'name')('bound-key')], _observe=lambda *a, **kw: EffectUnknown('missing termination'))
    monkeypatch.setattr(PilotRun, 'open', lambda *a, **kw: run)
    binding = dict(state_root=str(tmp_path), source_repo=str(tmp_path), run_id=run_id, work='ticket:1742')
    assert not evidence.executor_idle(binding)
    closed.append(True)  # existing backend's bound teardown evidence, not CLI force input
    assert evidence.executor_idle(binding)


def test_graph_return_checkpoint_recovers_but_cannot_be_backfilled_after_death(tmp_path, monkeypatch):
    owner = Owner('wayfinder', tmp_path)
    job = owner.admit('map:1742:dispatch')
    owner.gate.returned_action(owner.id, job)
    generation = owner.gate.request()
    monkeypatch.setattr(module, 'alive', lambda *args: False)
    with pytest.raises(ValueError): owner.gate.returned_action(owner.id, job)
    assert owner.gate.reconcile(generation, owner.id)['result'] == 'reconciled'


def test_sighting_before_registration_is_covered_without_erasing_history(tmp_path):
    gate = Gate(tmp_path)
    pid = os.getpid()
    start = module.identity(pid)
    gate.status([('executor', pid, start)])
    owner = gate.register('executor')
    gate.request()
    gate.poll(owner)
    assert gate.status([])['uncovered'] == []
    with gate.tx() as db:
        assert db.execute('SELECT count(*) FROM sightings').fetchone()[0] == 1


def test_idle_owner_lost_before_request_uses_atomic_census(tmp_path, monkeypatch):
    owner = Owner('decision', tmp_path)
    assert not owner.poll()
    generation = owner.gate.request()
    monkeypatch.setattr(module, 'alive', lambda *args: False)
    assert owner.gate.reconcile(generation, owner.id)['result'] == 'reconciled'
    assert owner.gate.status([])['state'] == 'unknown'


def test_evidence_failure_is_typed_and_does_not_publish_sensitive_exception(recovery, monkeypatch):
    gate, owner, _, generation, _ = recovery
    complete(recovery)
    def failed(binding):
        raise RuntimeError('fixture-sensitive-detail')
    monkeypatch.setattr(evidence, 'bound_idle', failed)
    result = gate.reconcile(generation, owner)
    assert result['reason'] == 'resources_unverified'
    assert 'fixture-sensitive-detail' not in json.dumps(result)
