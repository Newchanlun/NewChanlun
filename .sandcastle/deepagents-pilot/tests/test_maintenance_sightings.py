"""来源/作用域误识别与原始身份绑定对账；不采集生产进程。"""
import os
from types import SimpleNamespace

import pytest

from pilot1742 import maintenance as m


@pytest.mark.parametrize('command,expected', [
    ('python -m pilot1742.executor release --reason run', []),
    ('python -m pilot1742.executor register --task serve', []),
    ('python -m pilot1742.executor --state-root /state run --run-id x', ['executor']),
    ('python -m pilot1742.executor serve --review-sweep', ['executor']),
    ('node unrelated.mjs decision-claimer.mts --live', []),
    ('node /tmp/wayfinder_engine.mts --maintenance-root /isolated --live', []),
    ('node /tmp/decision-claimer.mts --maintenance-root /isolated --dry-run', []),
    ('python -m pilot1742.executor run --maintenance-root /isolated', []),
    ('python -m pilot1742.review_sweep run-review --maintenance-root /isolated', []),
])
def test_actual_entry_and_scope(command, expected):
    assert m.command_lanes(command, m.ROOT) == expected


def test_scope_filter_uses_native_argv_not_flattened_value(monkeypatch):
    command = 'node /tmp/decision-claimer.mts --out a --maintenance-root /isolated'
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'123 1 {command}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'exact-start')
    monkeypatch.setattr(m, 'process_arguments', lambda _: ['node', '/tmp/decision-claimer.mts', '--out',
                                                         'a --maintenance-root /isolated'])
    assert m.process_inventory() == [('decision', 123, 'exact-start')]
    monkeypatch.setattr(m, 'process_arguments', lambda _: ['node', '/tmp/decision-claimer.mts',
                                                         '--maintenance-root', '/isolated'])
    assert m.process_inventory() == []
    assert m.process_inventory(m.Path('/isolated')) == [('decision', 123, 'exact-start')]


def test_scope_read_failure_cannot_claim_no_processes(monkeypatch):
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout='123 1 node /tmp/decision-claimer.mts --maintenance-root /isolated'))
    monkeypatch.setattr(m, 'identity', lambda _: 'exact-start')
    def denied(_):
        raise PermissionError('denied')
    monkeypatch.setattr(m, 'process_arguments', denied)
    with pytest.raises(PermissionError):
        m.process_inventory()


def test_sighting_reconcile_requires_original_binding_and_resource_proof(tmp_path, monkeypatch):
    gate = m.Gate(tmp_path)
    pid, start = os.getpid(), m.identity(os.getpid())
    gate.status([('decision', pid, start)])  # 采集发生在登记之前。
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'work')
    generation = gate.request()
    monkeypatch.setattr(m, 'alive', lambda *a: False)
    assert gate.reconcile_sighting(generation, 'decision', pid, start)['reason'] == 'missing_bound_completion'
    monkeypatch.undo()
    gate.action_exited(owner, job, opaque_clear=True)
    gate.finish(owner, job, natural=True)
    gate.poll(owner)
    gate.stop(owner)
    monkeypatch.setattr(m, 'alive', lambda *a: False)
    assert gate.reconcile_sighting(generation, 'decision', pid, start)['result'] == 'reconciled'
    assert gate.reconcile_sighting(generation, 'decision', pid, start)['result'] == 'reconciled'
    with gate.tx() as db:
        assert db.execute('SELECT count(*) FROM sightings').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM sighting_resolutions').fetchone()[0] == 1
    gate.resume(generation)
    gate.request()
    with pytest.raises(ValueError, match='generation'):
        gate.reconcile_sighting(generation, 'decision', pid, start)
    gate.status([('decision', pid, 'reused-start')])
    assert gate.reconcile_sighting(generation + 1, 'decision', pid, 'reused-start')['reason'] == 'missing_original_identity_binding'


def test_unbound_legacy_sighting_survives_disappearance_and_next_generation(tmp_path):
    gate = m.Gate(tmp_path)
    gate.status([('review', 999999, 'unknown-original')])
    generation = gate.request()
    assert gate.reconcile_sighting(generation, 'review', 999999, 'unknown-original')['result'] == 'unknown'
    gate.resume(generation)
    gate.request()
    assert gate.status([])['uncovered'][0]['start'] == 'unknown-original'


def test_native_argv_boundaries_for_own_isolated_child(tmp_path):
    import subprocess
    import sys
    command = [sys.executable, '-c', 'import sys; sys.stdin.read()',
               '--out', 'not a flag --maintenance-root /elsewhere', '--maintenance-root', str(tmp_path)]
    child = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        assert m.process_arguments(child.pid) == command
    finally:
        child.communicate(timeout=5)
