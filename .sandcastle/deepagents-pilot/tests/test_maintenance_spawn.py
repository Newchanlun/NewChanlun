"""真实隔离bootstrap/wait；不启动review、模型或外部资源。"""
import sqlite3
import subprocess
import sys

import pytest

from pilot1742 import maintenance as m
from pilot1742.maintenance_spawn import Launch


def launch(tmp_path):
    parent = m.Owner('review', tmp_path)
    job = parent.reserve('pr:1:head:1')
    child = Launch(parent.gate, parent.id, job, [sys.executable, '-c', 'raise SystemExit(23)'],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return parent, job, child


def test_prebinding_wait_resolves_original_sighting_and_retains_history(tmp_path):
    parent, job, child = launch(tmp_path)
    try:
        start = m.identity(child.pid)
        assert parent.gate.status([('review', child.pid, start)])['uncovered']
        child.prepare()
        generation = parent.gate.request()
        child.close()  # EOF; bootstrap has never received GO and cannot fork/exec.
        assert child.process.wait(timeout=5) == 78
        assert child.reap()
        assert not child.reap()
        assert not parent.gate.status([])['uncovered']
        proof = parent.gate.reconcile_sighting(generation, 'review', child.pid, start)
        assert proof['result'] == 'reconciled'
        parent.poll()
        for lane in ('decision', 'wayfinder', 'executor'):
            other = parent.gate.register(lane)
            parent.gate.poll(other)
        assert parent.gate.status([])['state'] == 'drained'
        with parent.gate.tx() as db:
            assert db.execute('SELECT count(*) FROM sightings').fetchone()[0] == 1
            assert db.execute('SELECT count(*) FROM spawn_exits').fetchone()[0] == 1
            assert db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'finished'
    finally:
        child.close()
        child.process.wait(timeout=5)


@pytest.mark.parametrize('tamper', ['start', 'boot', 'resources', 'released', 'fake_wait'])
def test_incomplete_or_changed_spawn_proof_cannot_retire(tmp_path, tamper):
    parent, job, child = launch(tmp_path)
    try:
        child.prepare()
        if tamper == 'fake_wait':
            assert not parent.gate.spawn_exited(parent.id, job, child.pid, 78)
            assert not child.reap()  # process is still waiting, fake exit code cannot substitute.
        else:
            with parent.gate.tx() as db:
                if tamper in ('start', 'boot'):
                    db.execute(f'UPDATE spawn_launches SET {tamper}=? WHERE job=?', ('reused', job))
                elif tamper == 'resources':
                    db.execute('INSERT INTO bindings VALUES(?,?)', (job, '{}'))
                else:
                    db.execute('UPDATE spawn_launches SET released_at=? WHERE job=?', (m.now(), job))
            child.close()
            child.process.wait(timeout=5)
            assert not child.reap()
        assert parent.gate.status([])['inflight']
    finally:
        child.close()
        child.process.wait(timeout=5)


def test_real_release_adoption_is_once_and_parent_cannot_cancel(tmp_path):
    parent, job, child = launch(tmp_path)
    try:
        child.prepare()
        # Execute only isolated owner confirmation, never run_review/model.
        # Command fixed at Popen, so this test checks released-but-not-confirmed evidence.
        child.release()
        assert child.process.wait(timeout=5) == 23
        assert not child.reap()
        assert not parent.gate.spawn_exited(parent.id, job, child.pid, 23)
        with pytest.raises(ValueError):
            parent.gate.adopt(job, 'review')  # wrong PID cannot inherit it
        assert parent.gate.status([])['inflight'][0]['state'] == 'unknown'
    finally:
        child.close()
        child.process.wait(timeout=5)


def test_spawn_wait_storage_failure_retries_same_proof_without_relaunch(tmp_path, monkeypatch):
    parent, job, child = launch(tmp_path)
    try:
        child.prepare()
        child.close()
        child.process.wait(timeout=5)
        original = parent.gate.tx
        def fail():
            raise sqlite3.OperationalError('isolated write failure')
        monkeypatch.setattr(parent.gate, 'tx', fail)
        with pytest.raises(sqlite3.OperationalError):
            child.reap()
        assert not child.settled
        monkeypatch.setattr(parent.gate, 'tx', original)
        assert parent.gate.status([])['inflight']
        assert child.reap()
    finally:
        child.close()
        child.process.wait(timeout=5)


def test_old_unbound_spawn_exit_does_not_backfill_sighting(tmp_path):
    gate = m.Gate(tmp_path)
    parent = gate.register('review')
    job = gate.admit(parent, 'pr:old', transferable=True)
    gate.status([('review', 99999999, 'old-start')])
    assert not gate.spawn_exited(parent, job, 99999999, 0)
    generation = gate.request()
    assert gate.reconcile_sighting(generation, 'review', 99999999, 'old-start')['reason'] == 'missing_original_identity_binding'
    assert gate.status([])['uncovered']


def test_local_work_is_fenced_across_scheduler_restart(tmp_path):
    gate = m.Gate(tmp_path)
    scheduler = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdin.read()'], stdin=subprocess.PIPE)
    descendant = subprocess.Popen([sys.executable, '-c', 'import sys;sys.stdin.read()'], stdin=subprocess.PIPE, start_new_session=True)
    try:
        old = gate.register('decision', scheduler.pid, local_actions=True)
        job = gate.admit(old, 'ticket:123')
        gate.reserve_local_resource(old, job)
        scheduler.stdin.close()
        scheduler.wait(timeout=5)
        assert descendant.poll() is None
        replacement = gate.register('decision', local_actions=True)
        with pytest.raises(ValueError, match='previous local action unresolved'):
            gate.admit(replacement, 'ticket:123')
        assert gate.admit(replacement, 'ticket:124')
        gate.request()
        with pytest.raises(m.Closed):
            gate.admit(replacement, 'ticket:123')
        assert descendant.poll() is None
    finally:
        if not scheduler.stdin.closed:
            scheduler.stdin.close()
        descendant.stdin.close()
        scheduler.wait(timeout=5)
        descendant.wait(timeout=5)


def test_released_review_confirms_prebound_owner_once(tmp_path):
    parent = m.Owner('review', tmp_path)
    job = parent.reserve('pr:2:head:1')
    command = [sys.executable, '-c', '''import sys
from pathlib import Path
from pilot1742.maintenance import Owner
owner=Owner('review',Path(sys.argv[1]),sys.argv[2])
try:
    Owner('review',Path(sys.argv[1]),sys.argv[2])
except ValueError:
    pass
else:
    raise AssertionError('duplicate adoption')
owner.finish(sys.argv[2]);owner.stop()
''', str(tmp_path), job]
    child = Launch(parent.gate, parent.id, job, command, start_new_session=True)
    try:
        child.prepare()
        with parent.gate.tx() as db:
            bound_owner = db.execute('SELECT owner FROM spawn_launches WHERE job=?', (job,)).fetchone()[0]
        child.release()
        assert child.process.wait(timeout=5) == 0
        assert not child.reap()  # already adopted/finished; parent never overwrites child evidence
        with parent.gate.tx() as db:
            row = db.execute('SELECT * FROM spawn_launches WHERE job=?', (job,)).fetchone()
            assert row['confirmed_at'] and row['owner'] == bound_owner
            assert not db.execute('SELECT * FROM spawn_exits').fetchall()
    finally:
        child.close()
        child.process.wait(timeout=5)


def test_cross_owner_admission_is_atomic_and_finished_work_can_repeat(tmp_path):
    import concurrent.futures
    import threading

    gate = m.Gate(tmp_path)
    owners = [gate.register('decision', local_actions=True) for _ in range(2)]
    barrier = threading.Barrier(2)
    def enter(owner):
        barrier.wait()
        try:
            return owner, gate.admit(owner, 'ticket:77')
        except ValueError:
            return owner, None
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(enter, owners))
    winners = [(owner, job) for owner, job in results if job]
    assert len(winners) == 1
    owner, job = winners[0]
    assert gate.action_exited(owner, job, opaque_clear=True)
    gate.finish(owner, job, natural=True)
    assert gate.admit(next(o for o in owners if o != owner), 'ticket:77')


def test_adoption_winning_before_prebind_is_not_cancelled(tmp_path):
    parent, job, child = launch(tmp_path)
    try:
        adopter = m.Owner('review', tmp_path, job)
        with pytest.raises(ValueError, match='missing review reservation'):
            child.prepare()
        child.process.wait(timeout=5)
        assert not child.reap()
        assert parent.gate.status([])['inflight'][0]['owner'] == adopter.id
    finally:
        child.close()
        child.process.wait(timeout=5)


def test_prebind_storage_failure_keeps_unknown_without_inventing_wait(tmp_path, monkeypatch):
    parent, job, child = launch(tmp_path)
    try:
        def fail(*args):
            raise sqlite3.OperationalError('prebind unavailable')
        monkeypatch.setattr(parent.gate, 'prepare_spawn', fail)
        with pytest.raises(sqlite3.OperationalError):
            child.prepare()
        assert child.process.wait(timeout=5) == 78
        assert not child.reap()
        with parent.gate.tx() as db:
            assert not db.execute('SELECT * FROM spawn_exits').fetchall()
            assert not db.execute('SELECT * FROM cancellations').fetchall()
        assert parent.gate.status([])['inflight']
    finally:
        child.close()
        child.process.wait(timeout=5)
