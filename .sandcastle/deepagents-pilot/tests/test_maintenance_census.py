"""定序采集失败，不枚举 HOST；保留未启动与已启动失败的不同合同。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pilot1742 import maintenance_local, maintenance_processes
from pilot1742.maintenance import Gate


@pytest.mark.parametrize('reason', ['proc_pidinfo_size errno=3', 'proc_pidinfo_size errno=13',
                                  'proc_listpids_incomplete errno=0', 'process_read errno=2'])
def test_unavailable_baseline_returns_without_dispatch_or_unknown_reservation(tmp_path, reason):
    gate = Gate(tmp_path / 'gate')
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'no-dispatch')
    resource = gate.reserve_local_resource(owner, job)
    marker = tmp_path / 'must-not-exist'
    code = '''
import sys
from pilot1742 import maintenance_local, maintenance_processes
reason=sys.argv[3]
def fail():
    raise maintenance_processes.UnstableSnapshot(reason)
maintenance_processes.stable_snapshot=fail
root,resource=sys.argv[1:3]
sys.argv=['helper','--root',root,'--resource',resource,'--',sys.executable,'-c',sys.argv[4]]
raise SystemExit(maintenance_local.main())
'''
    result = subprocess.run([sys.executable, '-c', code, str(gate.root), resource, reason,
                             f'from pathlib import Path; Path({str(marker)!r}).touch()'],
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 78 and reason in result.stderr
    assert not marker.exists()
    with gate.tx() as db:
        proof = dict(db.execute('SELECT * FROM local_resource_not_started').fetchone())
        assert proof['resource'] == resource and proof['reason'] == 'baseline_unavailable'
        assert not db.execute('SELECT * FROM local_resource_domains').fetchall()
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None
    assert gate.action_exited(owner, job, opaque_clear=True)
    gate.finish(owner, job, natural=True)
    assert not gate.status([])['inflight']
    with pytest.raises(ValueError):
        gate.local_resource_not_started(resource)  # 不是原监督器，不能补签。


def test_cannot_cancel_after_dispatch_boundary_or_release_missing_return(tmp_path, monkeypatch):
    gate = Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'dispatched')
    resource = gate.reserve_local_resource(owner, job)
    monkeypatch.setattr(os, 'getsid', lambda _: os.getpid())
    monkeypatch.setattr(maintenance_processes, 'stable_snapshot',
                        lambda: {os.getpid(): ['birth', os.getppid()]})
    gate.bind_local_resource(resource)
    with pytest.raises(ValueError, match='may have dispatched'):
        gate.local_resource_not_started(resource)
    assert not gate.local_action_idle(job)
    gate.seal_local_resource(resource)
    with gate.tx() as db:
        assert db.execute('SELECT reason FROM local_resource_diagnostics').fetchone()[0] == 'wait_or_domain_missing'
        assert not db.execute('SELECT * FROM local_resource_not_started').fetchall()


def test_terminal_census_failure_and_unknown_birth_remain_unknown(monkeypatch):
    monkeypatch.setattr(maintenance_local, 'local_epoch', lambda: ('h', 'b'))
    row = dict(host='h', boot='b', pid=10, waited_at='wait',
               domain=dict(sealed_at=None, baseline=json.dumps({10: ['supervisor', 1]})))
    def fail():
        raise maintenance_processes.UnstableSnapshot('process_read errno=2')
    monkeypatch.setattr(maintenance_processes, 'stable_snapshot', fail)
    reasons = []
    assert not maintenance_local.resources_idle([row], reasons)
    assert reasons == ['process_read errno=2']
    monkeypatch.setattr(maintenance_processes, 'stable_snapshot', lambda: {999999: ['escaped', 1]})
    reasons = []
    assert not maintenance_local.resources_idle([row], reasons)
    assert reasons == ['unclassified_process_pids=999999']


def test_retry_diagnostics_preserve_all_failures_without_accepting_partial(monkeypatch):
    attempts = iter([maintenance_processes.UnstableSnapshot('proc_pidinfo_size errno=3'),
                     PermissionError(13, 'untrusted text'), ValueError('untrusted text')])
    def fail():
        raise next(attempts)
    monkeypatch.setattr(maintenance_processes, 'snapshot', fail)
    with pytest.raises(maintenance_processes.UnstableSnapshot) as result:
        maintenance_processes.stable_snapshot()
    assert str(result.value) == ('process census incomplete: proc_pidinfo_size errno=3; '
                                 'process_read errno=13; process_record_invalid')


@pytest.mark.parametrize('number', [3, 13, 0])
def test_native_diagnostics_distinguish_disappearance_permission_and_short_read(monkeypatch, number):
    import ctypes
    class Library:
        def proc_listpids(self, kind, uid, buffer, size):
            if buffer is not None:
                buffer[0] = 123
            return 4
        def proc_pidinfo(self, *args):
            ctypes.set_errno(number)
            return 0 if number else 1
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *a, **kw: Library())
    with pytest.raises(maintenance_processes.UnstableSnapshot) as result:
        maintenance_processes.stable_snapshot()
    assert str(result.value).count(f'proc_pidinfo_size errno={number}') == 3
