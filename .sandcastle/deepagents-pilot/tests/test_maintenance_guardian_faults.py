"""真实 Linux wait/stdio/后代监督；SQLite与身份故障仅注入临时账本。"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pilot1742.maintenance import Gate


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux 内核收养域')
@pytest.mark.parametrize('method', ['local_resource_waited', 'seal_local_resource'])
@pytest.mark.parametrize('error', ['sqlite3.OperationalError', 'ValueError'])
def test_guardian_ledger_failure_keeps_code_stdio_and_descendant_supervision(tmp_path, method, error):
    gate = Gate(tmp_path / 'gate')
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'fault-injection')
    resource = gate.reserve_local_resource(owner, job)
    fifo, finished = tmp_path / 'release', tmp_path / 'supervision-finished'
    os.mkfifo(fifo)
    descendant = f"with open({str(fifo)!r}) as f: f.read(1)"
    child = ("import subprocess,sys; "
             f"subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL,"
             "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); "
             "print('business-out',flush=True); print('business-err',file=sys.stderr,flush=True); sys.exit(23)")
    script = f'''
import sqlite3, sys
from pathlib import Path
from types import SimpleNamespace
from pilot1742.maintenance import Gate
from pilot1742.maintenance_local import linux_guardian
from pilot1742 import maintenance_subreaper
original = maintenance_subreaper.wait_remaining
def wait_remaining():
    original()
    Path({str(finished)!r}).write_text('kernel-wait-complete')
maintenance_subreaper.wait_remaining = wait_remaining
def fail(*args):
    raise {error}('injected')
Gate.{method} = fail
raise SystemExit(linux_guardian(SimpleNamespace(root=Path({str(gate.root)!r}), resource={resource!r}),
                               [sys.executable, '-c', {child!r}]))
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
    try:
        assert result.returncode == 23, result.stderr
        assert result.stdout == 'business-out\n'
        assert 'business-err\n' in result.stderr
        assert not finished.exists()  # 真实后代尚未结束，guardian 不能提前退出。
    finally:
        # 非阻塞写，修前 guardian 失败也不挂住测试；仅释放本测试后代。
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.write(fd, b'x')
        os.close(fd)
    deadline = time.monotonic() + 5
    while not finished.exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert finished.read_text() == 'kernel-wait-complete'
    with gate.tx() as db:
        assert db.execute('SELECT sealed_at FROM local_resource_domains').fetchone()[0] is None
        row = db.execute('SELECT waited_at FROM local_resources').fetchone()
        assert bool(row[0]) == (method == 'seal_local_resource')
    gate.action_exited(owner, job, opaque_clear=True)
    assert gate.status([])['inflight']  # 业务码已返回，但证据写失败没有被改成drained。
