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
    assert str(result.value).count('exit_fence_incomplete' if number == 3 else f'proc_pidinfo_size errno={number}') == 3


def test_exited_read_is_fenced_and_live_escaped_descendant_is_retained():
    scans = iter([{10, 20}, {10, 30}])
    def read(pid):
        if pid == 20:
            raise ProcessLookupError(3, 'gone')
        return [f'{pid}:birth', 1]
    assert maintenance_processes.collect(lambda: next(scans), read) == {
        10: ['10:birth', 1], 30: ['30:birth', 1]}


def test_fence_does_not_require_unchanged_population():
    scans = iter([{10, 20}, {10, 30, 40}])
    def read(pid):
        if pid == 20:
            raise FileNotFoundError(2, 'gone')
        return [f'{pid}:birth', 10]
    assert set(maintenance_processes.collect(lambda: next(scans), read)) == {10, 30, 40}


def test_fence_permission_and_reused_identity_are_not_disappearance():
    def denied(pid):
        raise PermissionError(13, 'private')
    with pytest.raises(PermissionError):
        maintenance_processes.collect(lambda: {10}, denied)
    scans = iter([{10, 20}, {10}])
    births = iter(['old', 'new'])
    def reused(pid):
        if pid == 20:
            raise FileNotFoundError(2, 'gone')
        return [next(births), 1]
    with pytest.raises(maintenance_processes.UnstableSnapshot, match='identity_changed'):
        maintenance_processes.collect(lambda: next(scans), reused)


def test_unresolved_disappearances_have_bounded_fences():
    scans = iter([{20}, {30}, {40}])
    def gone(pid):
        raise FileNotFoundError(2, 'gone')
    with pytest.raises(maintenance_processes.UnstableSnapshot, match='exit_fence_incomplete'):
        maintenance_processes.collect(lambda: next(scans), gone)


def test_mac_exit_fence_uses_new_enumeration_not_just_missing_pid_probe(monkeypatch):
    import ctypes
    class Library:
        round = 0
        def proc_listpids(self, kind, uid, buffer, size):
            if buffer is not None:
                self.round += 1
                buffer[0] = 20 if self.round == 1 else 30
            return 4
        def proc_pidinfo(self, pid, kind, arg, ptr, size):
            if pid == 20:
                ctypes.set_errno(3)
                return 0
            info = ptr._obj
            info.pid, info.uid, info.ppid, info.seconds = pid, os.getuid(), 1, 123
            return size
    library = Library()
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *a, **kw: library)
    assert maintenance_processes.snapshot() == {30: ['30:123:0', 1]}
    assert library.round == 2


def test_linux_enoent_fence_keeps_new_orphan_and_pins_proc_directory(tmp_path, monkeypatch):
    proc = tmp_path / 'proc'
    proc.mkdir()
    (proc / '20').mkdir()
    real_open = os.open
    def opening(path, flags, **kwargs):
        if path == proc / '20':
            (proc / '20').rmdir()
            (proc / '30').mkdir()
            # state + ppid + 17 intervening fields + starttime.
            (proc / '30' / 'stat').write_text('30 (space name) S 1 ' + '0 ' * 17 + '123')
        if path == 'stat':
            assert 'dir_fd' in kwargs
        return real_open(path, flags, **kwargs)
    monkeypatch.setattr(maintenance_processes, 'Path', lambda _: proc)
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(os, 'open', opening)
    assert maintenance_processes.snapshot() == {30: ['30:123', 1]}


def test_newly_observed_zombie_also_requires_descendant_fence():
    scans = iter([{20}, {20, 30}])
    def read(pid):
        return (maintenance_processes.EndedProcess('20:birth') if pid == 20
                else ['30:escaped', 1])
    assert maintenance_processes.collect(lambda: next(scans), read) == {30: ['30:escaped', 1]}


def test_zombie_pid_reuse_does_not_inherit_terminal_evidence():
    reads = iter([maintenance_processes.EndedProcess('old'), ['new', 1]])
    with pytest.raises(maintenance_processes.UnstableSnapshot, match='identity_changed'):
        maintenance_processes.collect(lambda: {20}, lambda _: next(reads))
