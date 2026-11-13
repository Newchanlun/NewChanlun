"""真实 SQLite/进程边界，所有目录与工作均为离线替身。"""
import multiprocessing as mp
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pilot1742.maintenance import Closed, Gate, LANES, Owner, identity


def owners(root):
    return [Owner(lane, root) for lane in LANES]


def confirm(items):
    for owner in items:
        assert owner.poll()


def test_close_continues_claimed_work_and_resumes_exact_generation(tmp_path):
    items = owners(tmp_path)
    gate = items[0].gate
    job = items[0].admit('ticket:1742')
    generation = gate.request()
    assert gate.request() == generation
    confirm(items)
    assert items[0].admit('ticket:1742') == job
    with pytest.raises(Closed): items[0].admit('ticket:1743')
    assert gate.status([])['state'] == 'draining'
    items[0].finish(job)
    assert gate.status([])['state'] == 'drained'
    with pytest.raises(ValueError): gate.resume(generation + 1)
    gate.resume(generation)
    with pytest.raises(ValueError): gate.resume(generation)
    assert gate.status([])['state'] == 'open'
    assert gate.request() == generation + 1
    assert gate.status([])['state'] == 'unknown'  # old ack is not current ack


def test_missing_owner_and_old_process_are_unknown(tmp_path):
    items = owners(tmp_path)
    gate = items[0].gate
    gate.request()
    confirm(items[:-1])
    assert gate.status([])['unconfirmed'] == ['review']
    confirm(items[-1:])
    assert gate.status([('decision', 999999, 'old-process')])['state'] == 'unknown'
    assert gate.status([])['state'] == 'unknown'  # 旧进程消失没有补齐身份绑定的结束证明


def _race(root, barrier, pipe, request):
    gate = Gate(Path(root))
    owner = gate.register('decision')
    barrier.wait()
    if request:
        pipe.send(('request', gate.request()))
    else:
        try: pipe.send(('admitted', gate.admit(owner, 'ticket:1')))
        except Closed: pipe.send(('closed', None))
    pipe.close()


def test_atomic_request_admission_race(tmp_path):
    ctx = mp.get_context('spawn')
    for index in range(8):
        root = tmp_path / str(index)
        gate = Gate(root)
        barrier = ctx.Barrier(2)
        pairs = [ctx.Pipe(False) for _ in range(2)]
        children = [ctx.Process(target=_race, args=(str(root), barrier, pairs[n][1], n == 0)) for n in range(2)]
        for child in children: child.start()
        replies = [pair[0].recv() for pair in pairs]
        for child in children:
            child.join(15)
            assert child.exitcode == 0
        report = gate.status([])
        assert report['state'] == 'unknown'  # exiting without stop is never natural evidence
        if replies[1][0] == 'admitted':
            assert len(report['inflight']) == 1
            assert report['inflight'][0]['generation'] == 0
        else:
            assert not report['inflight']
        live = Owner('decision', root)
        with pytest.raises(Closed): live.admit('after-close')


def test_detached_reservation_adopts_after_close_and_never_expires(tmp_path):
    items = owners(tmp_path)
    parent = items[-1]
    job = parent.reserve('pr:10:abcdef:1')
    parent.gate.request()
    confirm(items)
    assert parent.gate.status([])['state'] == 'draining'
    child = Owner('review', tmp_path, reservation=job)
    with pytest.raises(ValueError): Owner('review', tmp_path, reservation=job)
    child.poll()
    parent.stop()
    assert child.gate.status([])['state'] == 'draining'
    child.finish(job)
    child.stop()
    assert child.gate.status([])['state'] == 'drained'


def test_crash_restart_does_not_erase_unknown_work(tmp_path):
    gate = Gate(tmp_path)
    command = [sys.executable, '-c',
               'from pilot1742.maintenance import Owner; import sys; from pathlib import Path; '
               'o=Owner("review",Path(sys.argv[1])); o.admit("pr:1:a:1")', str(tmp_path)]
    subprocess.run(command, check=True, env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    gate.request()
    new = owners(tmp_path)
    confirm(new)
    report = gate.status([])
    assert report['state'] == 'unknown'
    assert report['inflight'][0]['state'] == 'unknown'
    assert 'review' in report['unconfirmed']


def test_exception_cannot_finish_and_no_legacy_state_changes(tmp_path):
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    state = legacy / 'state.json'
    state.write_text('{"v":1,"mode":"draining","generation":1}')
    before = state.read_bytes()
    items = owners(tmp_path / 'maintenance')
    job = items[0].admit('ticket:1')
    items[0].finish(job, natural=False)
    items[0].gate.request()
    confirm(items)
    assert items[0].gate.status([])['state'] == 'unknown'
    assert state.read_bytes() == before


def test_sqlite_request_never_waits_for_work_lifetime(tmp_path):
    items = owners(tmp_path)
    job = items[0].admit('ticket:1')
    # a second database connection can close while the original work is outstanding
    assert Gate(tmp_path).request() == 1
    assert items[0].admit('ticket:1') == job
    items[0].finish(job)


def test_detached_real_process_receipt(tmp_path):
    items = owners(tmp_path)
    parent = items[-1]
    job = parent.reserve('pr:11:abcdef:1')
    command = [sys.executable, '-u', '-c',
        'from pilot1742.maintenance import Owner; import sys; from pathlib import Path; '
        'o=Owner("review",Path(sys.argv[1]),sys.argv[2]); o.poll(); print("adopted",flush=True); '
        'sys.stdin.readline(); o.finish(sys.argv[2]); o.stop()', str(tmp_path), job]
    parent.gate.request()
    confirm(items)
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                             start_new_session=True,
                             env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    assert child.stdout.readline().strip() == 'adopted'
    assert parent.gate.status([])['state'] == 'draining'
    child.communicate('\n', timeout=10)
    assert child.returncode == 0
    assert parent.gate.status([])['state'] == 'drained'


def test_unverified_old_resources_prevent_drained(tmp_path):
    items = owners(tmp_path)
    gate = items[0].gate
    gate.request()
    confirm(items)
    items[2].coverage(False)
    assert gate.status([])['state'] == 'unknown'
    items[2].coverage(True)
    assert gate.status([])['state'] == 'drained'


def test_process_inventory_reports_old_leaf_not_tsx_wrapper(monkeypatch):
    from pilot1742 import maintenance
    from types import SimpleNamespace
    listing = '\n'.join([
        '11 1 node /tools/tsx/cli.mjs /host/scripts/wayfinder_engine.mts --live',
        '12 11 node --import /tools/tsx/loader.mjs /host/scripts/wayfinder_engine.mts --live',
        '13 1 /venv/bin/python -m pilot1742.executor serve --loop --review-sweep --private-key /private/path',
        '14 1 /bin/bash -c echo pilot1742.executor serve',
        '15 1 /venv/bin/python -m pilot1742.review_sweep run-review --pr 10',
    ])
    monkeypatch.setattr(maintenance.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=listing))
    monkeypatch.setattr(maintenance, 'identity', lambda pid: f'process-{pid}')
    assert maintenance.process_inventory() == [
        ('wayfinder', 12, 'process-12'), ('executor', 13, 'process-13'),
        ('review', 13, 'process-13'), ('review', 15, 'process-15')]


def test_control_cli_errors_never_echo_untrusted_values(tmp_path, capsys):
    from pilot1742.maintenance import main
    assert main(['--root', str(tmp_path), 'poll', '--owner', 'untrusted/value']) == 78
    assert capsys.readouterr().out == '{"error":"maintenance_unavailable"}\n'


def test_inventory_keeps_python_ancestors_and_orphan_executor(monkeypatch):
    from pilot1742 import maintenance
    from types import SimpleNamespace
    listing = "11 1 python -m pilot1742.review_sweep --loop 180\n12 11 python -m pilot1742.review_sweep run-review --pr 1\n13 1 python -m pilot1742.executor --state-root /isolated run --run-id t1-1"
    monkeypatch.setattr(maintenance.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=listing))
    monkeypatch.setattr(maintenance, 'identity', lambda pid: f'process-{pid}')
    assert maintenance.process_inventory() == [('review', 11, 'process-11'), ('review', 12, 'process-12'), ('executor', 13, 'process-13')]
