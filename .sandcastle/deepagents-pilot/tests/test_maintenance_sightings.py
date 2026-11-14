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
    ('node /tmp/wayfinder_engine.mts --maintenance-root /isolated --live', ['wayfinder']),
    ('node /tmp/decision-claimer.mts --maintenance-root /isolated --dry-run', ['decision']),
    ('python -m pilot1742.executor run --maintenance-root /isolated', ['executor']),
    ('python -m pilot1742.review_sweep run-review --maintenance-root /isolated', ['review']),
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
    assert m.process_inventory() == [('decision', 123, 'exact-start')]
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
    command = [sys.executable, '-c', 'import sys; print("ready", flush=True); sys.stdin.read()',
               '--out', 'not a flag --maintenance-root /elsewhere', '--maintenance-root', str(tmp_path)]
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        import select
        assert select.select([child.stdout], [], [], 5)[0], "child did not reach ready"
        assert child.stdout.readline() == b'ready\n'
        assert child.poll() is None
        assert m.process_arguments(child.pid) == command
    finally:
        child.communicate(timeout=5)


@pytest.mark.parametrize('options,module,tail,lane', [
    ('-X dev', 'executor', 'serve', 'executor'),
    ('-W ignore', 'review_sweep', '', 'review'),
    ('-uBXdev', 'executor', 'serve', 'executor'),
    ('-Wignore -OO', 'executor', 'run', 'executor'),
    ('--check-hash-based-pycs always', 'executor', 'serve', 'executor'),
    ('--future-option', 'executor', 'serve', 'executor'),
])
def test_interpreter_options_cannot_hide_unbound_work(tmp_path, monkeypatch, options, module, tail, lane):
    gate = m.Gate(tmp_path)
    owners = [gate.register(name) for name in m.LANES]
    gate.request()
    for owner in owners:
        gate.poll(owner)
        gate.coverage(owner, True)
        gate.stop(owner)
    assert gate.status([])['state'] == 'drained'
    command = f'python3 {options} -m pilot1742.{module} {tail}'
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'999999 1 {command}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'legacy-live-start')
    status = gate.status()
    assert status['state'] == 'unknown'
    assert status['uncovered'][0]['lane'] == lane


def test_foreign_scope_needs_original_live_binding(tmp_path, monkeypatch):
    local, foreign = tmp_path / 'local', tmp_path / 'foreign'
    argv = ['node', '/tmp/wayfinder_engine.mts', '--live', '--maintenance-root', str(foreign)]
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'123 1 {" ".join(argv)}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'start')
    monkeypatch.setattr(m, 'process_arguments', lambda _: argv)
    assert m.process_inventory(local) == [('wayfinder', 123, 'start')]
    assert not foreign.exists()  # 清点不得创建另一个账本。
    gate = m.Gate(foreign)
    owner = gate.register('wayfinder', 123)
    assert m.process_inventory(local) == []
    monkeypatch.setattr(m, 'identity', lambda _: 'reused')
    assert m.process_inventory(local) == [('wayfinder', 123, 'reused')]
    monkeypatch.setattr(m, 'identity', lambda _: 'start')
    gate.stop(owner)
    assert m.process_inventory(local) == [('wayfinder', 123, 'start')]


@pytest.mark.parametrize('tail', [
    ['--maintenance-root=/elsewhere'],
    ['--maintenance-root', '/elsewhere'],
    ['--', '--maintenance-root', '/elsewhere'],
])
def test_real_wayfinder_parser_legacy_scope_still_blocks(tmp_path, monkeypatch, tail):
    """执行源码中的真实parseArgs，不调用main；旧无绑定进程不得从参数推定外域。"""
    import json
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    script = """
const fs = require('fs'), vm = require('vm'), ts = require('esbuild');
const source = fs.readFileSync('scripts/wayfinder_engine.mts', 'utf8');
const start = source.indexOf('function parseArgs(');
const end = source.indexOf('const sleep =', start);
const code = ts.transformSync(source.slice(start, end), {loader:'ts', target:'es2022'}).code;
const context = {process:{env:{}}, DEFAULT_POLL_SECONDS:60, ORCHESTRATOR_LOGIN:'fixture',
 resolve:require('path').resolve, resolveSpecDrafter:()=>({})};
vm.createContext(context); vm.runInContext(code, context);
console.log(JSON.stringify(context.parseArgs(JSON.parse(process.argv[1]))));
"""
    argv = ['--live', *tail]
    result = subprocess.run(['node', '-e', script, json.dumps(argv)], cwd=repo,
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed['dryRun'] is False
    if tail[0].startswith('--maintenance-root='):
        assert parsed.get('maintenanceRoot') is None
    else:
        assert parsed['maintenanceRoot'] == '/elsewhere'
    gate = m.Gate(tmp_path)
    owners = [gate.register(lane) for lane in m.LANES]
    gate.request()
    for owner in owners:
        gate.poll(owner)
        gate.coverage(owner, True)
        gate.stop(owner)
    command = ['node', 'scripts/wayfinder_engine.mts', *argv]
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'999999 1 {" ".join(command)}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'legacy')
    monkeypatch.setattr(m, 'process_arguments', lambda _: command)
    assert gate.status()['state'] == 'unknown'


@pytest.mark.parametrize('prefix', [
    ['--out', '--maintenance-root', '/unused'],
    ['--', '--maintenance-root'],
    ['--maintenance-root='],
])
def test_non_option_scope_text_never_excludes_live_binding(tmp_path, monkeypatch, prefix):
    foreign = m.Gate(tmp_path / 'foreign')
    monkeypatch.setattr(m, 'identity', lambda _: 'bound')
    foreign.register('decision', 123)
    argv = ['node', 'decision-claimer.mts', *prefix, str(foreign.root)]
    assert not m.foreign_scope_bound(argv, 'decision', 123, 'bound', tmp_path / 'local')


@pytest.mark.parametrize('options', [
    ['-X', 'dev'], ['-W', 'ignore'], ['-uBXdev'], ['-Wignore', '-OO'],
    ['--check-hash-based-pycs', 'always'],
])
def test_interpreter_options_are_accepted_by_real_python(options):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, *options, '-c', 'print("offline")'],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'offline'
    assert m.python_entry([*options, '-m', 'pilot1742.executor', 'serve']) == ('pilot1742.executor', ['serve'])


@pytest.mark.parametrize('args', [
    ['-c', 'print(1)', '-m', 'pilot1742.executor', 'serve'],
    ['unrelated.py', '-m', 'pilot1742.executor', 'serve'],
    ['--', '-m', 'pilot1742.executor', 'serve'],
])
def test_interpreter_stops_before_unrelated_script_arguments(args):
    assert m.python_entry(args) == (None, [])


@pytest.mark.parametrize('data', [b'', b'\0', b'python'])
def test_empty_or_incomplete_proc_argv_cannot_hide_target(tmp_path, monkeypatch, data):
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m.Path, 'read_bytes', lambda _: data)
    monkeypatch.setattr(m, 'identity', lambda _: 'unchanged')
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout='123 1 python -m pilot1742.executor serve --maintenance-root /other'))
    with pytest.raises(ValueError, match='incomplete process argv'):
        m.Gate(tmp_path).status()


def test_proc_argv_preserves_trailing_empty_arguments(monkeypatch):
    monkeypatch.setattr(m.sys, 'platform', 'linux')
    monkeypatch.setattr(m.Path, 'read_bytes', lambda _: b'python\0-c\0pass\0\0')
    assert m.process_arguments(123) == ['python', '-c', 'pass', '']


def test_review_reservation_exact_foreign_binding(tmp_path, monkeypatch):
    import shlex
    local, foreign = m.Gate(tmp_path / 'local'), m.Gate(tmp_path / 'foreign')
    from pilot1742 import review_sweep
    argv = []
    def capture(command, **kwargs):
        argv.extend(command)
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(review_sweep, 'subprocess', SimpleNamespace(Popen=capture, DEVNULL=-3))
    spawn = review_sweep.spawner(tmp_path / 'unused-key',
                                SimpleNamespace(gate=foreign, reserve=lambda _: 'reservation'))
    assert spawn(2063, 1, 'a' * 40, tmp_path / 'isolated-review.log') == 123
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'123 1 {shlex.join(argv)}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'original-start')
    monkeypatch.setattr(m, 'process_arguments', lambda _: argv)
    foreign.register('review', 123)
    assert local.status()['uncovered'] == []
    assert foreign.status()['uncovered'] == []
    monkeypatch.setattr(m, 'identity', lambda _: 'reused-start')
    assert local.status()['uncovered'][0]['lane'] == 'review'


def test_framework_python_executable_is_not_invisible(tmp_path, monkeypatch):
    command = '/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python -m pilot1742.executor serve'
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=f'123 1 {command}'))
    monkeypatch.setattr(m, 'identity', lambda _: 'original-start')
    gate = m.Gate(tmp_path)
    assert gate.status()['uncovered'][0]['lane'] == 'executor'


def test_real_capital_python_argv_entry(tmp_path):
    import subprocess
    import sys
    executable = tmp_path / 'Python.app/Contents/MacOS/Python'
    executable.parent.mkdir(parents=True)
    executable.symlink_to(sys.executable)
    package = tmp_path / 'pilot1742'
    package.mkdir()
    (package / '__init__.py').write_text('')
    (package / 'executor.py').write_text('import sys\nprint("ready", flush=True)\nsys.stdin.read()\n')
    command = [str(executable), '-m', 'pilot1742.executor', 'serve']
    child = subprocess.Popen(command, cwd=tmp_path, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert child.stdout.readline() == b'ready\n'
        argv = m.process_arguments(child.pid)
        assert argv == command
        assert m.command_lanes('', tmp_path, argv) == ['executor']
    finally:
        child.communicate(timeout=5)
