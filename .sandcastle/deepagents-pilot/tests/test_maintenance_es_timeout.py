"""真实 execFileSync 超时；仅离线 ES 输入和隔离睡眠进程。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pilot1742 import maintenance as m

SCRIPT = r'''
import os, signal, subprocess, sys, threading, time
from pathlib import Path
from types import SimpleNamespace
from pilot1742 import maintenance_es_session as session
from test_maintenance_es_session import FixtureChannel, FixtureReducer, audit
root, resource, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
real_popen = subprocess.Popen
class Channel(FixtureChannel):
    def send(self, message):
        self.sent.append(message)
        if message.startswith('ARM'):
            self.event('FORK', audit(200, 2), audit(300))
            self.event('FORK', audit(300), audit(400))
            self.frames.put(dict(type='started', resource=resource, pid=300))
            self.armed.set()
channel = Channel()
channel.armed = threading.Event()
class Reducer(FixtureReducer):
    def seal(self, resource):
        assert self.status(resource)['process_closed']
        assert self.status(resource)['business_waited']
        (root / 'closed').write_text('offline process closure observed')
        return super().seal(resource)
class Helper:
    def __init__(self):
        self.child = real_popen([sys.executable, '-c', 'raise SystemExit(23)' if mode == 'early' else 'import time; time.sleep(30)'])
        self.descendant = real_popen([sys.executable, '-c',
            'import time; time.sleep(4)'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (root / 'guardian').write_text(str(os.getpid()))
        (root / 'descendant').write_text(str(self.descendant.pid))
        def finish_descendant():
            self.descendant.wait()
            channel.event('EXIT', audit(400))
        threading.Thread(target=finish_descendant, daemon=True).start()
    def wait(self):
        assert channel.armed.wait(2)
        code = self.child.wait()
        (root / 'actual-wait').write_text(str(code))
        channel.event('EXIT', audit(300))
        channel.frames.put(dict(type='waited', resource=resource, pid=300, code=128-code if code < 0 else code))
        channel.event('EXIT', audit(200, 2))
        return code
    def poll(self): return self.child.poll()
    def send_signal(self, value): self.child.send_signal(value)
def popen(command):
    channel.event('FORK', audit(os.getpid()), audit(200))
    channel.event('EXEC', audit(200), audit(200, 2), 'helper')
    channel.frames.put(dict(type='register', resource=resource, nonce=channel.nonce,
                            image='helper', peer=audit(200, 2).words))
    return Helper()
session.subprocess = SimpleNamespace(Popen=popen)
def connect(*args):
    channel.parent = audit(os.getpid())
    return channel
session.VerifiedChannel.connect = connect
session.NativeES = Reducer
raise SystemExit(session.run(SimpleNamespace(root=root, resource=resource, es_config='isolated'), ['unused']))
'''


@pytest.mark.parametrize('mode,kill_signal', [('early', 'SIGTERM'), ('timeout', 'SIGTERM'), ('timeout', 'SIGINT')])
def test_sync_timeout_returns_while_es_guardian_tracks_live_descendant(tmp_path, mode, kill_signal):
    gate = m.Gate(tmp_path)
    owner = gate.register('wayfinder', local_actions=True)
    job = gate.admit(owner, 'map:1:draft_spec')
    resource = gate.reserve_local_resource(owner, job)
    script = tmp_path / 'fixture.py'
    script.write_text(SCRIPT)
    node = r'''
const {execFileSync} = require('node:child_process');
const start=Date.now();
try { execFileSync(process.argv[1], [process.argv[2], process.argv[3], process.argv[4], process.argv[5]],
  {killSignal:process.argv[6], timeout:1500, encoding:'utf8'}); throw Error('expected timeout'); }
catch (e) { console.log(JSON.stringify({code:e.code,elapsed:Date.now()-start,status:e.status})); }
'''
    env = dict(os.environ)
    code_root = os.environ.get('ES_TEST_CODE_ROOT', str(Path(__file__).resolve().parents[1]))
    env['PYTHONPATH'] = os.pathsep.join([code_root, str(Path(__file__).parent.resolve()), env.get('PYTHONPATH', '')])
    result = subprocess.run(['node', '-e', node, sys.executable, str(script), str(tmp_path), resource, mode, kill_signal],
                            env=env, capture_output=True, text=True, timeout=8, check=True)
    report = json.loads(result.stdout)
    actual = 23 if mode == 'early' else -15 if kill_signal == 'SIGTERM' else -2
    assert report.get('code') == (None if mode == 'early' else 'ETIMEDOUT'), report
    assert (tmp_path / 'actual-wait').read_text() == str(actual)
    assert report['status'] == (actual if actual >= 0 else 128 - actual)
    assert report['elapsed'] < 3000, report
    assert not (tmp_path / 'closed').exists(), 'caller timeout must precede descendant closure'
    os.kill(int((tmp_path / 'guardian').read_text()), 0)
    os.kill(int((tmp_path / 'descendant').read_text()), 0)
    gate.action_exited(owner, job, opaque_clear=True)
    gate.finish(owner, job, natural=False)
    assert not gate.local_action_idle(job)
    assert gate.status([])['inflight'][0]['state'] == 'unknown'
    with pytest.raises(ValueError, match='unresolved'):
        gate.admit(gate.register('wayfinder', local_actions=True), 'map:1:draft_spec')
    # Bounded observation only: guardian, not this checker, consumes final ES EXIT.
    import time
    deadline = time.monotonic() + 6
    while not (tmp_path / 'closed').exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (tmp_path / 'closed').exists()
    assert not gate.local_action_idle(job), 'offline source must never sign production closure'
