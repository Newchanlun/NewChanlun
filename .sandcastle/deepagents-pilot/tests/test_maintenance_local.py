"""822 同 boot 反例：真实 TS work、真实本机无模型子进程，临时账本。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pilot1742.maintenance import Gate, Owner

REPO = Path(__file__).resolve().parents[3]
TSX = REPO / 'node_modules/.bin/tsx'


@pytest.fixture
def process_churn():
    """独立于被测域的持续 fork/wait；测试结束仅停止自己创建的发生器。"""
    code = """
import signal, subprocess, sys, time
running = True
def stop(*_):
    global running
    running = False
signal.signal(signal.SIGTERM, stop)
print('ready', flush=True)
while running:
    subprocess.run(['/bin/sleep', '0.003'], check=True)
"""
    process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == 'ready'
    try:
        yield
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def run_ts(tmp_path, body):
    script = tmp_path / 'probe.mts'
    script.write_text(f'''import {{ MaintenanceOwner, maintenanceCommand }} from {json.dumps(str(REPO / '.sandcastle/maintenance.mts'))};
import {{execFileSync, spawn}} from 'node:child_process';
const root = {json.dumps(str(tmp_path / 'gate'))};
{body}
''')
    result = subprocess.run([str(TSX), str(script)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result


def confirm_all(root):
    owners = [Owner(lane, root) for lane in ('decision', 'wayfinder', 'executor', 'review')]
    gate = owners[0].gate
    generation = gate.request()
    for owner in owners:
        owner.poll()
    assert gate.status([])['unconfirmed'] == []
    return gate, generation


def test_actual_timeout_and_normal_scheduler_restart_drain_same_boot(tmp_path, process_churn):
    result = run_ts(tmp_path, '''
for (const lane of ['decision', 'wayfinder']) {
  const owner = new MaintenanceOwner(lane, root);
  const code = await owner.work('timeout', () => new Promise((resolve, reject) => {
    const cmd = maintenanceCommand('/bin/sh', ['-c', 'printf ready; exec /bin/sleep 30']);
    const child = spawn(cmd.file, cmd.args, {stdio:['ignore','pipe','inherit']});
    child.stdout.once('data', () => setTimeout(() => child.kill('SIGTERM'), 20));
    child.once('error', reject);
    child.once('close', resolve);
  }));
  owner.stop();
  console.log(JSON.stringify({owner:owner.id, code}));
}
''')
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r['code'] for r in rows] == [143, 143], result.stderr
    gate, generation = confirm_all(tmp_path / 'gate')
    for row in rows:
        assert gate.reconcile(generation, row['owner'])['result'] == 'reconciled'
    assert gate.status([])['state'] == 'drained'
    with gate.tx() as db:
        resources = db.execute('SELECT * FROM local_resources').fetchall()
        assert len(resources) == 2 and all(r['code'] == -15 and r['waited_at'] for r in resources)
        assert not db.execute('SELECT * FROM epoch_resolutions').fetchall()


@pytest.mark.parametrize('escape', ['group', 'session'])
def test_primary_wait_with_live_descendant_in_other_group_is_not_drained(tmp_path, escape, process_churn):
    fifo = tmp_path / 'release'
    os.mkfifo(fifo)
    child_code = f"with open({str(fifo)!r}) as f: f.read(1)"
    option = 'process_group=0' if escape == 'group' else 'start_new_session=True'
    parent_code = f"import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',{child_code!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,{option}); print(p.pid)"
    result = run_ts(tmp_path, f'''
const owner = new MaintenanceOwner('decision', root);
const pid = await owner.work('descendant', () => {{
  const cmd = maintenanceCommand('python3', ['-c', {json.dumps(parent_code)}]);
  return Number(execFileSync(cmd.file, cmd.args, {{encoding:'utf8'}}).trim());
}});
owner.stop();
console.log(JSON.stringify({{owner:owner.id,pid}}));
''')
    row = json.loads(result.stdout)
    try:
        gate, generation = confirm_all(tmp_path / 'gate')
        assert os.getpgid(row['pid']) == row['pid']
        assert gate.reconcile(generation, row['owner'])['result'] == 'unknown'
        assert gate.status([])['state'] == 'unknown'
        with gate.tx() as db:
            proof = db.execute('SELECT * FROM local_resources').fetchone()
            assert proof['waited_at'] and proof['code'] == 0
            assert (os.getsid(row['pid']) == proof['sid']) == (escape == 'group')
        with open(fifo, 'w') as release:
            release.write('x')

    finally:
        try:
            os.kill(row['pid'], 15)
        except ProcessLookupError:
            pass


def test_close_or_missing_wait_and_unbound_resource_never_clear_unknown(tmp_path):
    owner = Owner('decision', tmp_path / 'gate')
    try:
        owner.gate.reserve_local_resource(owner.id, owner.admit('legacy'))
    except ValueError:
        pass
    else:
        raise AssertionError('unbound local resource admitted')
    gate = Gate(tmp_path / 'new')
    registered = gate.register('decision', local_actions=True)
    job = gate.admit(registered, 'pending')
    gate.reserve_local_resource(registered, job)
    assert not gate.action_exited(registered, job, opaque_clear=True)
    gate.finish(registered, job, natural=False)
    gate.stop(registered)
    assert gate.status([])['inflight'][0]['state'] == 'unknown'


def test_native_census_requires_wait_and_complete_bound_domain(monkeypatch):
    from pilot1742 import maintenance_local as local
    from pilot1742 import maintenance_processes as native
    monkeypatch.setattr(local, 'local_epoch', lambda: ('host', 'boot'))
    monkeypatch.setattr(local.os, 'getpid', lambda: 90)
    baseline = {1: ['init', 0], 10: ['scheduler', 1], 20: ['supervisor', 10], 30: ['unrelated', 1]}
    proof = dict(pid=20, host='host', boot='boot', waited_at=1,
                 domain=dict(baseline=json.dumps(baseline), sealed_at=None))
    current = {1: ['init', 0], 10: ['scheduler', 1], 30: ['unrelated', 1], 90: ['checker', 10]}
    monkeypatch.setattr(native, 'stable_snapshot', lambda: current)
    assert local.resources_idle([proof])
    current[40] = ['new-unrelated-child', 30]
    assert local.resources_idle([proof])
    current[42] = ['checker-child-not-exempt', 90]
    assert not local.resources_idle([proof])
    del current[42]
    current[41] = ['escaped-descendant', 1]
    assert not local.resources_idle([proof])
    del current[41]
    current[30] = ['reused-pid', 1]
    assert not local.resources_idle([proof])
    current[30] = ['unrelated', 1]
    assert local.resources_idle([proof])
    assert not local.resources_idle([dict(proof, waited_at=None)])
    assert not local.resources_idle([dict(proof, boot='old')])
    def unreadable():
        raise native.UnstableSnapshot('partial')
    monkeypatch.setattr(native, 'stable_snapshot', unreadable)
    assert not local.resources_idle([proof])


def test_live_owner_poll_can_settle_returned_domain_without_rewriting_failure(tmp_path, monkeypatch):
    gate = Gate(tmp_path)
    owner = gate.register('decision', local_actions=True)
    job = gate.admit(owner, 'failed-business')
    idle = [False]
    monkeypatch.setattr(gate, 'local_action_idle', lambda _: idle[0])
    assert not gate.action_exited(owner, job, opaque_clear=True)
    gate.finish(owner, job, natural=False)
    generation = gate.request()
    gate.poll(owner)
    assert gate.status([])['inflight']
    idle[0] = True
    gate.poll(owner)
    gate.poll(owner)
    with gate.tx() as db:
        assert db.execute('SELECT state FROM jobs WHERE id=?', (job,)).fetchone()[0] == 'unknown'
        assert db.execute('SELECT generation FROM resolutions WHERE job=?', (job,)).fetchone()[0] == generation
        assert db.execute('SELECT count(*) FROM resolutions').fetchone()[0] == 1
    assert not gate.status([])['inflight']
    with pytest.raises(ValueError):
        gate.reserve_local_resource(owner, job)


def test_sync_wayfinder_timeout_uses_native_wait_not_close(tmp_path, process_churn):
    result = run_ts(tmp_path, '''
const owner = new MaintenanceOwner('wayfinder', root);
let code;
try {
  await owner.work('sync-timeout', () => {
    const cmd = maintenanceCommand('/bin/sleep', ['30']);
    execFileSync(cmd.file, cmd.args, {timeout:1000});
  });
} catch (e) { code = e.code; }
owner.stop();
console.log(JSON.stringify({owner:owner.id,code}));
''')
    row = json.loads(result.stdout)
    assert row.get('code') == 'ETIMEDOUT', result.stderr
    gate, generation = confirm_all(tmp_path / 'gate')
    assert gate.reconcile(generation, row['owner'])['result'] == 'reconciled'
    assert gate.status([])['state'] == 'drained'


@pytest.mark.parametrize('lane', ['executor', 'review', 'decision'])
def test_action_exit_cannot_substitute_other_protocol_or_old_unbound_job(tmp_path, lane):
    gate = Gate(tmp_path)
    owner = gate.register(lane)
    job = gate.admit(owner, 'unbound')
    with pytest.raises(ValueError, match='local action'):
        gate.action_exited(owner, job, opaque_clear=True)
    with gate.tx() as db:
        assert not db.execute('SELECT * FROM action_exits').fetchall()


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='真实 Linux subreaper 内核合同')
@pytest.mark.parametrize('lose_guardian', [False, True])
def test_linux_guardian_outlives_scheduler_and_only_real_reap_seals(tmp_path, lose_guardian):
    import signal
    import time
    fifo = tmp_path / 'release'
    os.mkfifo(fifo)
    descendant = f"with open({str(fifo)!r}) as f: f.read(1)"
    command = f"import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',{descendant!r}],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True); print(p.pid)"
    result = run_ts(tmp_path, f'''
const owner = new MaintenanceOwner('decision', root);
const pid = await owner.work('orphan', () => {{
  const cmd = maintenanceCommand('python3', ['-c', {json.dumps(command)}]);
  return Number(execFileSync(cmd.file,cmd.args,{{encoding:'utf8'}}).trim());
}});
owner.stop();
console.log(JSON.stringify({{owner:owner.id,pid}}));
''')
    row = json.loads(result.stdout)
    gate, generation = confirm_all(tmp_path / 'gate')
    with gate.tx() as db:
        resource = dict(db.execute('SELECT * FROM local_resources').fetchone())
        domain = dict(db.execute('SELECT * FROM local_resource_domains').fetchone())
    assert json.loads(domain['baseline'])['kind'] == 'linux-subreaper-v1'
    assert resource['waited_at'] and domain['sealed_at'] is None
    assert gate.reconcile(generation, row['owner'])['result'] == 'unknown'
    if lose_guardian:
        os.kill(resource['pid'], signal.SIGKILL)  # 只杀这个临时测试预绑定的 guardian。
    try:
        with open(fifo, 'w') as release:
            release.write('x')
        if not lose_guardian:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with gate.tx() as db:
                    sealed = db.execute('SELECT sealed_at FROM local_resource_domains').fetchone()[0]
                if sealed:
                    break
                time.sleep(.01)
            assert sealed, 'guardian 必须自行等待并持久封闭；不能靠 checker 进程消失推断'
            assert gate.reconcile(generation, row['owner'])['result'] == 'reconciled'
            assert gate.status([])['state'] == 'drained'
        else:
            assert gate.reconcile(generation, row['owner'])['result'] == 'unknown'
            assert gate.status([])['state'] == 'unknown'
            with gate.tx() as db:
                assert db.execute('SELECT sealed_at FROM local_resource_domains').fetchone()[0] is None
    finally:
        try:
            os.kill(row['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass


def test_missing_executable_records_bound_non_dispatch(tmp_path):
    result = run_ts(tmp_path, '''
const owner = new MaintenanceOwner('decision', root);
const code = await owner.work('missing-executable', () => new Promise((resolve, reject) => {
  const cmd = maintenanceCommand('/nonexistent/maintenance-fixture-executable', []);
  const child = spawn(cmd.file, cmd.args, {stdio:['ignore','ignore','pipe']});
  child.once('error', reject);
  child.once('close', resolve);
}));
owner.stop();
console.log(JSON.stringify({code}));
''')
    assert json.loads(result.stdout)['code'] == 127
    gate, _ = confirm_all(tmp_path / 'gate')
    assert gate.status([])['state'] == 'drained'
    with gate.tx() as db:
        assert db.execute('SELECT reason FROM local_resource_not_started').fetchone()[0] == 'exec_failed'
        assert db.execute('SELECT waited_at FROM local_resources').fetchone()[0] is None


@pytest.mark.skipif(sys.platform != 'darwin', reason='native macOS census domain')
def test_macos_unrelated_new_sibling_is_conservative_unknown(tmp_path):
    """真实祖先新增无关分支；记录当前活性边界，不将此 unknown 宣称恢复。"""
    result = run_ts(tmp_path, '''
const owner = new MaintenanceOwner('decision', root);
let unrelated;
try {
  const code = await owner.work('sibling', () => new Promise((resolve, reject) => {
    const cmd = maintenanceCommand('/bin/sh', ['-c', 'printf ready; exec /bin/sleep 30']);
    const child = spawn(cmd.file, cmd.args, {stdio:['ignore','pipe','inherit']});
    child.stdout.once('data', () => {
      unrelated = spawn('/bin/sleep', ['30'], {detached:true, stdio:'ignore'});
      unrelated.once('spawn', () => child.kill('SIGTERM'));
    });
    child.once('error', reject);
    child.once('close', resolve);
  }));
  console.log(JSON.stringify({code, unrelated:unrelated.pid}));
} finally {
  if (unrelated) {
    const exited = new Promise(resolve => unrelated.once('close', resolve));
    unrelated.kill('SIGTERM'); await exited;
  }
  owner.stop();
}
''')
    row = json.loads(result.stdout)
    assert row['code'] == 143, result.stderr
    gate = Gate(tmp_path / 'gate')
    with gate.tx() as db:
        diagnostic = db.execute('SELECT reason FROM local_resource_diagnostics').fetchone()[0]
        assert diagnostic.startswith('unclassified_process_pids='), diagnostic
        assert str(row['unrelated']) in diagnostic.split('=')[1].split(',')
        assert db.execute('SELECT sealed_at FROM local_resource_domains').fetchone()[0] is None
