"""只在 Linux 内核执行新后端；其它平台继续原 census 后端。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pilot1742.maintenance import Gate

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='真实 Linux subreaper')


def test_linux_native_dispatch_never_needs_machine_snapshot(tmp_path):
    gate = Gate(tmp_path / 'gate')
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'kernel-domain')
    resource = gate.reserve_local_resource(owner, job)
    code = '''
import sys
from pilot1742 import maintenance_local, maintenance_processes
def forbidden():
    raise AssertionError('whole machine census must not run')
maintenance_processes.stable_snapshot=forbidden
sys.argv=['local','--root',sys.argv[1],'--resource',sys.argv[2],'--','/bin/true']
raise SystemExit(maintenance_local.main())
'''
    result = subprocess.run([sys.executable, '-c', code, str(gate.root), resource],
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    with gate.tx() as db:
        domain = dict(db.execute('SELECT * FROM local_resource_domains').fetchone())
    assert json.loads(domain['baseline'])['kind'] == 'linux-subreaper-v1'
    assert domain['sealed_at']
    assert gate.action_exited(owner, job, opaque_clear=True)


def test_linux_wrong_birth_and_other_owner_cannot_seal(monkeypatch):
    from pilot1742 import maintenance_subreaper as kernel
    # 保留真正内核检查：其它 PID 和错误出生身份在触及本进程 children 前拒绝。
    assert not kernel.idle(dict(kind=kernel.KIND, pid=os.getpid()+100000, birth='other'))
    assert not kernel.idle(dict(kind=kernel.KIND, pid=os.getpid(), birth='other'))
    monkeypatch.setattr(kernel, 'enabled', lambda: False)
    assert not kernel.idle(dict(kind=kernel.KIND, pid=os.getpid(), birth=kernel.birth()))
