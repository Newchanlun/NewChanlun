"""2fdc：账本故障不改业务退出，未启动证明不覆盖已启动异常。"""
import sqlite3
from types import SimpleNamespace

import pytest

from pilot1742 import executor, maintenance, maintenance_local, review_sweep


@pytest.mark.parametrize('business_code', [23, -15])
@pytest.mark.parametrize('method', ['local_resource_waited', 'seal_local_resource'])
@pytest.mark.parametrize('error', [sqlite3.OperationalError, ValueError])
def test_waited_business_code_survives_ledger_failure(tmp_path, monkeypatch, method, error, business_code):
    calls = []
    class Gate:
        def __init__(self, root):
            pass
        def bind_local_resource(self, *a, **kw):
            pass
        def local_resource_waited(self, *a):
            calls.append('waited')
            if method == 'local_resource_waited':
                raise error('injected')
        def seal_local_resource(self, *a):
            calls.append('seal')
            if method == 'seal_local_resource':
                raise error('injected')
    monkeypatch.setattr(maintenance, 'Gate', Gate)
    monkeypatch.setattr(maintenance_local.os, 'setsid', lambda: None)
    monkeypatch.setattr(maintenance_local.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(maintenance_local.subprocess, 'Popen', lambda *a: SimpleNamespace(pid=123, wait=lambda: business_code))
    expected = business_code if business_code >= 0 else 128 - business_code
    assert maintenance_local.supervise(SimpleNamespace(root=tmp_path, resource='r'), ['unused']) == expected
    assert calls[0] == 'waited'
    if method == 'local_resource_waited':
        assert calls == ['waited']  # 未提交wait，不伪造封闭。


@pytest.mark.parametrize('error', [ValueError, sqlite3.OperationalError, OSError])
@pytest.mark.parametrize('suffix', ['resumes', 'launched'])
def test_reserve_failure_does_not_consume_marker(tmp_path, monkeypatch, error, suffix):
    def reserve(*a):
        raise error('injected')
    owner = SimpleNamespace(reserve=reserve)
    sweep = object.__new__(review_sweep.Sweep)
    sweep.folder = tmp_path
    sweep._launch_markers = {}
    sweep.spawn = review_sweep.spawner(tmp_path / 'unused', owner)
    marker = tmp_path / suffix
    with pytest.raises(review_sweep.NotStarted):
        sweep._launch_marked(marker, 1, 'a' * 40, 1)
    assert not marker.exists()


@pytest.mark.parametrize("real_main", [False, True])
@pytest.mark.parametrize("stopped_owner", [False, True])
def test_manual_overlap_preserves_busy75(tmp_path, monkeypatch, real_main, stopped_owner):
    serve = maintenance.Owner('executor')
    unit = SimpleNamespace(run_id='same-run', ticket=1742)
    job = serve.gate.admit_executor(serve.id, unit.run_id, unit.ticket, tmp_path, executor.SOURCE_REPO)
    witness = serve.gate.start_bound(job, unit.run_id, tmp_path)
    if stopped_owner:
        serve.stop()  # 调度owner结束不等于仍活执行控制器已返回。
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    def run(argv, *, on_execution):
        on_execution()
        pytest.fail('overlap executed')
    if real_main:
        from contextlib import nullcontext

        from pilot1742 import run as run_module
        models = tmp_path / 'models.md'
        models.write_text('')
        monkeypatch.setattr(run_module, 'PSTACK_MODELS', models)
        monkeypatch.setattr(executor, '_client', lambda _: nullcontext(object()))
        monkeypatch.setattr(executor, 'RepoGateway', lambda _: None)
        monkeypatch.setattr(executor, 'TicketExecutor', lambda *a, **kw: None)
        monkeypatch.setattr(executor, 'open_v2_run', lambda *a, **kw: pytest.fail('overlap executed'))
    else:
        monkeypatch.setattr(executor, '_main', run)
    assert executor.main(['--state-root', str(tmp_path), '--drain-root', str(tmp_path / 'drain'),
                          'run', '--run-id', unit.run_id, '--private-key', str(tmp_path / 'unused')]) == 75
    with serve.gate.tx() as db:
        assert db.execute('SELECT count(*) FROM witnesses WHERE job=?', (job,)).fetchone()[0] == 1
        assert db.execute('SELECT 1 FROM returns WHERE witness=?', (witness,)).fetchone() is None


def test_successful_popen_then_bookkeeping_error_keeps_marker(tmp_path, monkeypatch):
    cancellations = []
    owner = SimpleNamespace(id='owner', reserve=lambda *a: 'reservation',
                            gate=SimpleNamespace(root=tmp_path, cancel_unstarted=lambda *a: cancellations.append(a)))
    class Process:
        @property
        def pid(self):
            raise OSError('post-spawn bookkeeping failed')
    monkeypatch.setattr(review_sweep.subprocess, 'Popen', lambda *a, **kw: Process())
    sweep = object.__new__(review_sweep.Sweep)
    sweep.folder = tmp_path
    sweep._launch_markers = {}
    sweep.spawn = review_sweep.spawner(tmp_path / 'unused', owner)
    marker = tmp_path / 'resumes'
    with pytest.raises(OSError):
        sweep._launch_marked(marker, 1, 'a' * 40, 1)
    assert marker.exists()
    assert cancellations == []


def test_signal_during_prelaunch_binding_records_no_dispatch(tmp_path):
    import os
    import subprocess
    import sys

    gate = maintenance.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'signal-before-spawn')
    resource = gate.reserve_local_resource(owner, job)
    script = '''
import os,signal,sys
from types import SimpleNamespace
from pilot1742.maintenance import Gate
from pilot1742.maintenance_local import supervise
from pilot1742.maintenance import now

def bind(self, resource, **kwargs):
    self.bind_local_resource_identity(resource)
    with self.tx() as db:
        db.execute('INSERT INTO local_resource_domains VALUES(?,?,?,NULL)', (resource, '{}', 'fixture'))
    os.kill(os.getpid(), signal.SIGTERM)
Gate.bind_local_resource = bind
raise SystemExit(supervise(SimpleNamespace(root=sys.argv[1],resource=sys.argv[2]),
                          [sys.executable, '-c', 'raise AssertionError("must not spawn")']))
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path), resource],
                            capture_output=True, text=True, timeout=10, env=dict(os.environ))
    assert result.returncode == 143, result.stderr
    with gate.tx() as db:
        assert db.execute('SELECT reason FROM local_resource_not_started').fetchone()[0] == 'cancelled_before_spawn'
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None
    assert gate.local_action_idle(job)


@pytest.mark.parametrize('callback_return_committed', [False, True])
def test_local_wait_alone_cannot_invent_callback_return(tmp_path, monkeypatch, callback_return_committed):
    import os

    from pilot1742.maintenance_epoch import local_epoch
    gate = maintenance.Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'rpc-failed')
    resource = gate.reserve_local_resource(owner, job)
    # Exact local wait/closure fixture. The graph callback may still be doing opaque work.
    with gate.tx() as db:
        db.execute('UPDATE local_resources SET host=?,boot=?,pid=?,start=?,sid=?,child_pid=?,code=?,waited_at=? WHERE id=?',
                   (*local_epoch(), os.getpid(), maintenance.identity(os.getpid()), os.getsid(0), 123, 0, maintenance.now(), resource))
        db.execute('INSERT INTO local_resource_domains VALUES(?,?,?,?)', (resource, '{}', 'fixture', maintenance.now()))
    assert gate.local_action_idle(job)
    with pytest.raises(ValueError, match='unresolved'):
        gate.admit(owner, 'rpc-failed')
    if callback_return_committed:
        # Only the still-live original caller can submit its actual return/opaque state.
        assert gate.action_exited(owner, job, opaque_clear=True)
    gate.stop(owner)
    generation = gate.request()
    monkeypatch.setattr(maintenance, 'alive', lambda *a: False)
    report = gate.reconcile(generation, owner)
    if callback_return_committed:
        assert report['result'] == 'reconciled'
    else:
        assert report['reason'] == 'missing_bound_completion'
        assert report['result'] == 'unknown'
        with gate.tx() as db:
            assert not db.execute('SELECT * FROM action_returns').fetchall()
