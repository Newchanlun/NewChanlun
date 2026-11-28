import json
import shutil
from dataclasses import replace
from pathlib import Path

import conftest
import pytest
import v2env
from conftest import FAKE, MODELS, git
from fake_github import FakeGitHub
from test_boat import FakeBoat, config, payload
from test_queue import SPEC, authorize, executor
from test_queue import queued as queued
from v2env import TICKET, V2Env

from pilot1742 import boat_execution, boat_remote
from pilot1742 import run as pilot_run
from pilot1742.approval import SignedApprovals
from pilot1742.boat_execution import (
    BoatBinding,
    BoatExecution,
    ExecutionUnknown,
    parse_execution,
)
from pilot1742.claims import ClaimRefused, ClaimStore
from pilot1742.domain import EffectUnknown, WorkerKey
from pilot1742.executor import load_unit, open_v2_run, release_claim
from pilot1742.github_app import AppIdentity
from pilot1742.workunit import DEDICATED_MARKER


@pytest.fixture(scope="module")
def _v2_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("boat_drain_seed")
    seed = V2Env(root)
    return seed.source, seed.base, seed.bare, seed.identity.private_key_path


@pytest.fixture(autouse=True)
def _fast_env(monkeypatch, _v2_seed):
    seed_source, seed_base, seed_bare, seed_pem = _v2_seed
    orig_ensure = pilot_run.PilotRun._ensure_checkout

    def _fast_env_init(self, tmp: Path):
        self.home = tmp / "home"
        self.source = tmp / "source"
        shutil.copytree(seed_source, self.source)
        self.base = seed_base
        self.home.mkdir()
        self.control({})

    def _fast_v2_init(self, tmp: Path):
        _fast_env_init(self, tmp)
        self.tmp = tmp
        self.bare = tmp / "origin.git"
        shutil.copytree(seed_bare, self.bare)
        pem = tmp / "app.pem"
        shutil.copy2(seed_pem, pem)
        pem.chmod(0o600)
        self.identity = AppIdentity(
            5486877, 179444545, 1150335160, "Newchanlun/NewChanlun", "newchanlun-deepagents-1742", pem
        )
        self.github = FakeGitHub(self.identity, self.bare)
        self.github.add_issue(TICKET, body=f"#1742 首证专用票\n\n{DEDICATED_MARKER}\n")
        self.claims_root = tmp / "claims"
        self.workers_log = tmp / "workers.jsonl"
        self.workers_log.write_text(json.dumps({"ticket": 1715, "branch": "sandcastle/issue-1715"}) + "\n")
        self.approvals = SignedApprovals(
            trust_path=tmp / "unconfigured-trust.json",
            authority_root=tmp / "unconfigured-authority",
        )

    def _fast_ensure(self, role, head):
        path, branch = self.spec.checkout_for(role), self.spec.branch_for(role)
        if not path.exists():
            src = Path(self.source_repo)
            git_dir = src / ".git"
            branch_ref = git_dir / "refs" / "heads" / branch
            head_file = git_dir / "HEAD"
            main_ref = git_dir / "refs" / "heads" / "main"
            index_file = git_dir / "index"
            wt_name = f"{self.spec.run_id}-{role}"
            wt_admin = git_dir / "worktrees" / wt_name
            if (
                git_dir.is_dir()
                and not (git_dir / "packed-refs").exists()
                and not branch_ref.exists()
                and not wt_admin.exists()
                and head_file.is_file()
                and head_file.read_text().strip() == "ref: refs/heads/main"
                and main_ref.is_file()
                and main_ref.read_text().strip() == str(head)
                and index_file.is_file()
            ):
                pilot_run.require_free_space(path.parent)
                path.mkdir(parents=True, exist_ok=True)
                branch_ref.parent.mkdir(parents=True, exist_ok=True)
                branch_ref.write_text(f"{head}\n")
                wt_admin.mkdir(parents=True)
                (wt_admin / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
                (wt_admin / "commondir").write_text("../..\n")
                (wt_admin / "gitdir").write_text(f"{path / '.git'}\n")
                shutil.copy2(index_file, wt_admin / "index")
                for item in src.iterdir():
                    if item.name == ".git":
                        continue
                    dst = path / item.name
                    if item.is_dir() and not item.is_symlink():
                        shutil.copytree(item, dst, symlinks=True)
                    else:
                        shutil.copy2(item, dst, follow_symlinks=False)
                (path / ".git").write_text(f"gitdir: {wt_admin}\n")
                self.trail("checkout_created", role=role, path=str(path), branch=branch)
                return
        return orig_ensure(self, role, head)

    monkeypatch.setattr(conftest.Env, "__init__", _fast_env_init)
    monkeypatch.setattr(v2env.V2Env, "__init__", _fast_v2_init)
    monkeypatch.setattr(pilot_run.PilotRun, "_ensure_checkout", _fast_ensure)


def stopped_worker(run, monkeypatch):
    run.release()
    run.spec = replace(run.spec, execution=parse_execution({
        'backend': 'boat', 'config': config(), 'runtime_head': run.spec.base}))
    (run.dir / 'run.json').write_text(json.dumps(run.spec.to_json()))
    cli = FakeBoat()
    monkeypatch.setattr(boat_execution, 'BoatCLI', lambda: cli)
    run.execution = BoatExecution(run, cli)
    key = WorkerKey(run.spec.run_id, 'author', run.spec.base)
    binding = BoatBinding(run.execution._identity(key), 'vm', 'p1', '/home/user/x/p1',
                          'submitted', sandbox_id='bx_abc', stop_id='stop-original', stop_confirmed=True,
                          key_erased=True)
    run.execution._store(key, binding)
    return run.execution, key, binding, cli


def failure_receipt(binding, exit_code, kind='worker'):
    receipt = {'identity': dict(binding.identity), 'package_id': binding.package_id,
               'state': 'terminal', 'exit_code': exit_code,
               'record': {'status': 'failed', 'process_exit': {'code': exit_code, 'signal': None}},
               'files': [{'path': 'demo/forbidden', 'mode': '100644', 'content': 'bm8='}]}
    if kind == 'supervisor':
        receipt.pop('record')
        receipt.update(state='unknown', reason='管理者取消；未产生成功业务回执')
    return receipt


@pytest.mark.parametrize('entry', ['observe', 'cancel'])
@pytest.mark.parametrize('pending', ['running', 'stopping', 'archiving'])
@pytest.mark.parametrize('final', ['stopped', 'archived'])
def test_submitted_failure_keeps_slot_until_stop_is_confirmed(env, monkeypatch, entry, pending, final):
    run = env.create()
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    binding = replace(binding, stop_id=None, stop_confirmed=False, key_erased=False)
    engine._store(key, binding)
    receipt = failure_receipt(binding, 7)
    engine._path(key, '.remote.json').write_text(json.dumps(receipt))
    states = iter([{'state': 'running'}, {'state': pending}])
    cli.handlers.update(info=lambda: next(states), exec={},
                        stop=[{'operation': {'id': 'stop-pending'}}])
    fact = getattr(engine, entry)(key)
    assert isinstance(fact, EffectUnknown)
    assert engine.load(key).stop_id is None
    assert not engine.is_drained(key)
    assert json.loads(engine._path(key, '.remote.json').read_text()) == receipt
    cli.handlers['info'] = {'state': 'stopping', 'stop': {'id': 'stop-pending'}}
    assert isinstance(getattr(engine, entry)(key), EffectUnknown)
    assert engine.load(key).stop_id is None and not engine.is_drained(key)
    assert sum(call[0] == 'stop' for call in cli.calls) == 1
    cli.handlers['info'] = {'state': final, 'stop': {'id': 'stop-pending'}}
    assert isinstance(getattr(engine, entry)(key), EffectUnknown)
    assert engine.load(key).stop_id == 'stop-pending'
    assert engine.is_drained(key)
    cli.calls.clear()
    assert_no_collection(run, key, cli)


@pytest.mark.parametrize('submission', ['prepared', 'submitted'])
@pytest.mark.parametrize('old_stop', ['stop-request-only', 'stopping'])
def test_legacy_stop_id_requires_explicit_reconciliation(env, monkeypatch, submission, old_stop):
    run = env.create()
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    binding = replace(binding, submission=submission, stop_id=old_stop, key_erased=True)
    engine._store(key, binding)
    path = engine._path(key, '.json')
    raw = json.loads(path.read_text())
    raw.pop('stop_confirmed')
    path.write_text(json.dumps(raw))
    engine._path(key, '.remote.json').write_text(json.dumps(failure_receipt(binding, 7)))
    assert not engine.load(key).stop_confirmed
    assert not engine.is_drained(key) and cli.calls == []
    cli.handlers['info'] = {'state': 'stopping', 'stop': {'id': 'stop-original'}}
    engine.cancel(key)
    assert not engine.is_drained(key)
    assert engine.load(key).stop_id == old_stop
    cli.handlers['info'] = {'state': 'stopped', 'stop': {'id': 'stop-original'}}
    engine.cancel(key)
    assert engine.load(key).stop_confirmed
    assert engine.load(key).stop_id == 'stop-original'
    assert engine.is_drained(key)
    assert all(call[0] == 'info' for call in cli.calls)
    cli.calls.clear()
    assert_no_collection(run, key, cli)


CASES = [
    'worker', 'cancelled', 'supervisor', 'missing_erasure', 'missing_stop', 'missing_receipt', 'identity', 'package',
    'missing_exit', 'exit_mismatch', 'bool_exit', 'process_exit_null', 'process_exit_missing',
    'process_exit_mismatch', 'process_exit_bool', 'completed', 'running', 'unknown', 'bad_binding',
]
DRAINED = {'worker', 'cancelled', 'supervisor'}


def stage_evidence(engine, key, binding, case, exit_code):
    receipt = failure_receipt(binding, exit_code, 'supervisor' if case == 'supervisor' else 'worker')
    if case == 'missing_stop':
        engine._store(key, replace(binding, stop_id=None))
    elif case == 'missing_erasure':
        engine._store(key, replace(binding, key_erased=False))
    elif case == 'identity':
        receipt['identity']['generation'] += 1
    elif case == 'package':
        receipt['package_id'] = 'other'
    elif case == 'missing_exit':
        receipt.pop('exit_code')
    elif case == 'exit_mismatch':
        receipt['exit_code'] = 2 if exit_code == 0 else 0
    elif case == 'bool_exit':
        receipt['exit_code'] = bool(exit_code)
    elif case == 'process_exit_null':
        receipt['record']['process_exit'] = None
    elif case == 'process_exit_missing':
        receipt['record'].pop('process_exit')
    elif case == 'process_exit_mismatch':
        receipt['record']['process_exit']['code'] = 3
    elif case == 'process_exit_bool':
        receipt['record']['process_exit']['code'] = bool(exit_code)
    elif case in ('cancelled', 'completed'):
        receipt['record']['status'] = case
    elif case in ('running', 'unknown'):
        receipt['state'] = case
    elif case == 'bad_binding':
        engine._store(key, replace(binding, identity={**binding.identity, 'generation': 999}))
    if case != 'missing_receipt':
        engine._path(key, '.remote.json').write_text(json.dumps(receipt))
    return receipt


def assert_no_collection(run, key, cli):
    assert not (run._key_dir(key) / 'result.json').exists()
    assert not run.execution._path(key, '.collect.json').exists()
    assert git(run.spec.checkout_for(key.role), 'status', '--porcelain') == ''
    assert cli.calls == []


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('exit_code', [0, 2])
def test_manual_generation_uses_only_stopped_failure_evidence(tmp_path, monkeypatch, case, exit_code):
    v2 = V2Env(tmp_path)
    unit = v2.register()
    run = v2.run(unit)
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    receipt = stage_evidence(engine, key, binding, case, exit_code)
    release_claim(ClaimStore(v2.claims_root), v2.gateway(), TICKET, unit.run_id, 'controller released')
    second_unit = v2.register(f't{TICKET}-2')
    before = v2.writes()
    if case in DRAINED and not (case == 'supervisor' and exit_code == 0):
        with pytest.raises(ExecutionUnknown):
            engine.collect(key, receipt)
        assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
        second = v2.run(second_unit)
        assert second.generation == 2
        second.release()
    else:
        with pytest.raises(ClaimRefused, match='Boat'):
            v2.run(second_unit)
        assert v2.claim_record()['generation'] == 1
        assert v2.writes() == before
    assert_no_collection(run, key, cli)


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('exit_code', [0, 2])
@pytest.mark.parametrize('has_intent', [True, False])
def test_queue_slot_uses_same_stopped_failure_evidence(queued, monkeypatch, case, exit_code, has_intent):
    v2, cutover, intake, signer = queued
    unit = intake.register(TICKET)
    authorize(v2, cutover, unit, signer)
    run = open_v2_run(v2.home, unit, load_unit(v2.home, unit.run_id)[1], executor(v2, cutover, unit),
                      MODELS, launcher=FAKE, source_repo=v2.source)
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    stage_evidence(engine, key, binding, case, exit_code)
    if has_intent:
        (run.dir / 'intents').mkdir(exist_ok=True)
        (run.dir / 'intents' / f'{key.name}.json').write_text('{}')
    release_claim(intake.claims, v2.gateway(), TICKET, unit.run_id, 'controller released')
    v2.github.issues[TICKET]['labels'].remove('deepagents:queue')
    v2.github.add_issue(TICKET + 1, body=f'Part of [SPEC #{SPEC}]', parent=SPEC,
                        labels=('ready-for-agent', 'deepagents:queue'))
    seen = []
    before = v2.writes()
    rows = intake.once(lambda item: seen.append(item.ticket) or 0)
    if case in DRAINED and not (case == 'supervisor' and exit_code == 0):
        assert seen == [TICKET + 1]
    else:
        assert seen == []
        assert rows[TICKET]['phase'] == 'active'
        assert rows[TICKET + 1]['phase'] == 'queued'
    assert v2.writes() == before
    assert_no_collection(run, key, cli)


def test_actual_prelaunch_cancel_receipt_is_drained_but_never_collectible(env, tmp_path, monkeypatch):
    run = env.create()
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    remote = tmp_path / 'remote'
    remote.mkdir()
    request = {'identity': binding.identity, 'package_id': binding.package_id, 'root': str(remote)}
    assert boat_remote.cancel(request, remote / 'request.json')['state'] == 'receipt'
    receipt = json.loads((remote / 'claim/receipt.json').read_text())
    engine._path(key, '.remote.json').write_text(json.dumps(receipt))
    with pytest.raises(ExecutionUnknown):
        engine.collect(key, receipt)
    assert engine.is_drained(key)
    assert_no_collection(run, key, cli)


@pytest.mark.parametrize('status', ['failed', 'cancelled'])
def test_failed_with_zero_exit_drains_without_collecting_incomplete_files(env, monkeypatch, status):
    run = env.create()
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    files = [{'path': 'demo/not-imported', 'mode': '100644', 'content': 'bm8='}]
    receipt = payload(run, engine, key, files, status='?? demo/not-imported\n?? outside-scope.txt')
    receipt['state'] = 'terminal'
    receipt['record'].update(status=status, process_exit={'code': 0, 'signal': None})
    engine._path(key, '.remote.json').write_text(json.dumps(receipt))
    before = engine._path(key, '.remote.json').read_bytes()

    with pytest.raises(ExecutionUnknown, match='业务回执与产物清单不同'):
        engine.collect(key, receipt)
    assert engine.is_drained(key)
    assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
    assert engine._path(key, '.remote.json').read_bytes() == before
    assert engine.load(key) == binding
    assert_no_collection(run, key, cli)
