import base64
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import conftest
import pytest
import v2env
from conftest import FAKE, MODELS
from fake_github import FakeGitHub
from test_boat import FakeBoat, adapter, payload, prepared_engine, stamp
from test_boat_drain import assert_no_collection, stopped_worker
from test_queue import SPEC, authorize, executor
from test_queue import queued as queued
from v2env import TICKET, V2Env

from pilot1742 import boat_execution
from pilot1742 import run as run_module
from pilot1742.agent import build_tools
from pilot1742.approval import SignedApprovals
from pilot1742.boat_execution import BoatExecution, ExecutionUnknown, ForkIntent
from pilot1742.claims import ClaimRefused, ClaimStore
from pilot1742.domain import EffectUnknown, NotStarted
from pilot1742.executor import load_unit, open_v2_run, release_claim
from pilot1742.github_app import AppIdentity
from pilot1742.run import Halted
from pilot1742.workunit import DEDICATED_MARKER


@pytest.fixture(scope="module")
def _v2_seed(tmp_path_factory):
    root = tmp_path_factory.mktemp("boat_prelaunch_seed")
    seed = V2Env(root)
    return seed.source, seed.base, seed.bare, seed.identity.private_key_path


@pytest.fixture(autouse=True)
def _fast_env(monkeypatch, _v2_seed):
    seed_source, seed_base, seed_bare, seed_pem = _v2_seed
    orig_ensure = run_module.PilotRun._ensure_checkout

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
                run_module.require_free_space(path.parent)
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
    monkeypatch.setattr(run_module.PilotRun, "_ensure_checkout", _fast_ensure)


def cleanup_cli(remote):
    def execute(command):
        assert command.startswith('rm -f ') and 'test ! -e ' in command
        remote['key'] = False
        return {}

    def stop(sandbox):
        assert sandbox == 'bx_abc' and not remote['key']
        remote['running'] = False
        return [{'operation': {'id': 'stop_1'}}]

    return FakeBoat(info=lambda: {'state': 'running' if remote['running'] else 'stopped',
                                 'archiveAfter': stamp(1700)},
                    exec=execute, stop=stop)


def test_prepared_cancel_recovers_key_transfer_before_submitting_record(env, monkeypatch):
    remote = {'key': False, 'running': True}
    cli = cleanup_cli(remote)
    run, engine, key, _ = prepared_engine(env, monkeypatch, cli, 'prepared', 'bx_abc')
    store = engine._store

    def fail_submitting(key, binding):
        if binding.submission == 'submitting':
            raise OSError('fixture crash after key transfer')
        return store(key, binding)

    monkeypatch.setattr(engine, '_provision_key', lambda binding: remote.update(key=True))
    monkeypatch.setattr(engine, '_store', fail_submitting)
    with pytest.raises(OSError, match='after key transfer'):
        engine.submit(key)
    assert engine.load(key).submission == 'prepared' and remote['key']
    reopened = BoatExecution(run, cli)
    assert isinstance(reopened.cancel(key), NotStarted)
    assert not remote['key'] and not remote['running']
    assert reopened.load(key).stop_id == 'stop_1'
    calls = list(cli.calls)
    assert isinstance(reopened.cancel(key), NotStarted) and cli.calls == calls
    with pytest.raises(ExecutionUnknown):
        reopened.submit(key)
    assert cli.calls == calls
    run.release()


@pytest.mark.parametrize('submission', ['creating', 'prepared'])
def test_prelaunch_cleanup_unknown_does_not_release_resources(env, submission):
    remote = {'key': True, 'running': True}
    cli = cleanup_cli(remote)

    def fail(command):
        raise ExecutionUnknown('fixture key cleanup failed')

    cli.handlers['exec'] = fail
    run, engine, key, binding = adapter(env, cli, submission)
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
    assert not engine.is_drained(key)
    assert remote['key'] and remote['running'] and engine.load(key) == replace(binding, cancel_requested=True)
    with pytest.raises(ExecutionUnknown):
        engine.submit(key)
    assert isinstance(engine.observe(key), EffectUnknown)
    assert not any(call[0] == 'stop' for call in cli.calls)
    run.release()


@pytest.mark.parametrize('submission', ['creating', 'prepared'])
def test_prelaunch_cancel_known_vm_does_not_require_uploaded_controller(env, submission):
    remote = {'key': True, 'running': True}
    cli = cleanup_cli(remote)
    run, engine, key, _ = adapter(env, cli, submission)
    assert isinstance(engine.cancel(key), NotStarted)
    assert not remote['key'] and not remote['running']
    assert engine.load(key).stop_id == 'stop_1'
    assert isinstance(engine.observe(key, reconcile=False), NotStarted)
    run.release()


@pytest.mark.parametrize('matches', [0, 1, 2])
def test_cancel_recovers_lost_fork_by_label_without_creating(env, matches):
    remote = {'key': False, 'running': True}
    cli = cleanup_cli(remote)
    run, engine, key, binding = adapter(env, cli, 'creating')
    engine._store(key, replace(binding, sandbox_id=None, create_requested=True,
                               fork_intent=ForkIntent('bx_base', 'same-key', '{}', 0)))
    cli.handlers['list'] = [{'sandboxes': [
        {'id': 'bx_abc', 'name': 'before-rename', 'labels': {'newchanlun.worker': binding.sandbox_name}}
        for _ in range(matches)]}]
    engine.fork_api = SimpleNamespace(fork=lambda _: pytest.fail('cancel created a VM'))
    fact = engine.cancel(key)
    if matches == 1:
        assert isinstance(fact, NotStarted)
        assert not remote['running'] and engine.load(key).sandbox_id == 'bx_abc'
    else:
        assert isinstance(fact, EffectUnknown) and remote['running']
        assert engine.load(key).sandbox_id is None
        assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
        assert not engine.is_drained(key)
    run.release()


def test_prelaunch_stopped_vm_does_not_imply_key_erasure(env):
    run, engine, key, binding = adapter(env, FakeBoat(info={'state': 'stopped'}), 'prepared')
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert engine.load(key) == replace(binding, cancel_requested=True) and not engine.is_drained(key)
    assert [call[0] for call in engine.cli.calls] == ['info']
    run.release()


def test_cancel_before_fork_request_is_not_started(env):
    run, engine, key, binding = adapter(env, FakeBoat(), 'creating')
    engine._store(key, replace(binding, sandbox_id=None))
    assert isinstance(engine.cancel(key), NotStarted)
    assert engine.cli.calls == []
    with pytest.raises(ExecutionUnknown):
        engine.submit(key)
    run.release()


def test_stop_ack_without_stopped_state_keeps_slot_until_reconciled(env):
    remote = {'key': True, 'running': True}
    cli = cleanup_cli(remote)
    cli.handlers['stop'] = [{'operation': {'id': 'stop_pending'}}]
    run, engine, key, _ = adapter(env, cli, 'prepared')
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert not remote['key'] and remote['running']
    assert engine.load(key).key_erased and engine.load(key).stop_id is None
    assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
    assert not engine.is_drained(key)
    remote['running'] = False
    assert isinstance(engine.cancel(key), NotStarted)
    assert sum(call[0] == 'stop' for call in cli.calls) == 1
    assert engine.load(key).stop_id and isinstance(engine.observe(key, reconcile=False), NotStarted)
    run.release()


def test_real_key_delete_failure_cannot_be_hidden_by_printf(env, tmp_path):
    remote = {'key': True, 'running': True}
    cli = cleanup_cli(remote)
    run, engine, key, binding = adapter(env, cli, 'prepared')
    binding = engine._store(key, replace(binding, remote_root=str(tmp_path / 'remote/p1')))
    Path(binding.key_file).mkdir(parents=True)

    def execute(command):
        result = subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True)
        if result.returncode:
            raise ExecutionUnknown('key cleanup command failed')
        remote['key'] = False
        return json.loads(result.stdout)

    cli.handlers['exec'] = execute
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert Path(binding.key_file).is_dir()
    assert not engine.load(key).key_erased and engine.load(key).stop_id is None
    assert not any(call[0] == 'stop' for call in cli.calls)
    run.release()



@pytest.mark.parametrize("state", ["stopping", "archiving"])
def test_prelaunch_stop_transition_keeps_slot_until_terminal(env, state):
    remote = {"key": True, "running": True, "state": "running"}
    cli = cleanup_cli(remote)
    cli.handlers["info"] = lambda: {"state": remote["state"]}

    def stop(sandbox):
        assert sandbox == "bx_abc" and not remote["key"]
        remote["state"] = state
        return [{"operation": {"id": "stop_pending"}}]

    cli.handlers["stop"] = stop
    run, engine, key, _ = adapter(env, cli, "prepared")
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert engine.load(key).key_erased and engine.load(key).stop_id is None
    assert isinstance(engine.observe(key, reconcile=False), EffectUnknown)
    assert not engine.is_drained(key)
    calls = list(cli.calls)
    assert isinstance(engine.cancel(key), EffectUnknown)
    assert cli.calls == calls + [("info",)]
    remote["state"] = "stopped" if state == "stopping" else "archived"
    assert isinstance(engine.cancel(key), NotStarted)
    assert isinstance(engine.observe(key, reconcile=False), NotStarted)
    assert sum(call[0] == "stop" for call in cli.calls) == 1
    run.release()


@pytest.mark.parametrize("has_vm", [True, False])
def test_prelaunch_cancelled_worker_resume_halts_without_redispatch(env, legacy_boat_runtime, has_vm):
    remote = {"key": True, "running": True}
    cli = cleanup_cli(remote)
    run, engine, key, binding = adapter(env, cli, "prepared" if has_vm else "creating")
    if not has_vm:
        engine._store(key, replace(binding, sandbox_id=None))
    assert isinstance(engine.cancel(key), NotStarted)
    calls = list(cli.calls)
    with pytest.raises(Halted, match="取消"):
        run.run_worker("author", "恢复已取消工蜂")
    assert cli.calls == calls
    trail = [json.loads(line) for line in (run.dir / "trail.jsonl").read_text().splitlines()]
    assert trail[-1]["event"] == "halted" and trail[-1]["key"] == key.name
    assert "取消" in trail[-1]["reason"]
    assert isinstance(engine.observe(key, reconcile=False), NotStarted)
    run.release()



@pytest.mark.parametrize("stage", ["creating", "prepared", "lost_fork"])
def test_agent_status_resumes_preparation_through_dispatch_without_new_vm(env, legacy_boat_runtime, monkeypatch, stage):
    cli = FakeBoat(info={"state": "running", "hydrated": True, "archiveAfter": stamp(1700)},
                   detach=[{"commandId": "cmd_resumed", "processId": 7}],
                   stop=[{"operation": {"id": "stop_resumed"}}])
    run, engine, key, _ = prepared_engine(env, monkeypatch, cli,
                                        "prepared" if stage == "prepared" else "creating", "bx_abc")
    binding = engine.load(key)
    if stage == "lost_fork":
        binding = engine._store(key, replace(binding, sandbox_id=None, create_requested=True))
        cli.handlers["list"] = [{"sandboxes": [{"id": "bx_abc", "name": binding.sandbox_name}]}]
    run._prepare_dispatch(key, "原任务", run.facts())
    (run.dir / "run.json").write_text(json.dumps(run.spec.to_json()))
    run.release()

    monkeypatch.setattr(boat_execution, "BoatCLI", lambda: cli)
    resumed = env.reopen()
    engine = resumed.execution
    monkeypatch.setattr(engine, "_build", lambda *_: resumed.dir / "pkg")
    provisioned = []
    monkeypatch.setattr(engine, "_provision_key", lambda b: provisioned.append(b.sandbox_id))
    engine.fork_api = SimpleNamespace(fork=lambda _: pytest.fail("恢复创建了新 VM"))
    files = [{"path": "demo/resumed.txt", "mode": "100644", "content": base64.b64encode(b"done").decode()}]
    receipt = payload(resumed, engine, key, files)
    receipt["record"]["result"]["status"] = "completed"
    cli.handlers["exec"] = lambda command: (
        {"identity": binding.identity, "package_id": binding.package_id, "state": "receipt"}
        if " observe " in command else {})

    def scp(source, target):
        if source.endswith("/claim/receipt.json"):
            Path(target).write_text(json.dumps(receipt))
        return []

    def stop(*args):
        cli.handlers["info"] = {"state": "stopped"}
        return [{"operation": {"id": "stop_resumed"}}]

    cli.handlers["stop"] = stop
    cli.handlers["scp"] = scp
    tools = {tool.name: tool for tool in build_tools(resumed)}
    before = list(cli.calls)
    state = json.loads(tools["run_status"].invoke({}))
    assert state["phase"] == "needs_author"
    assert state["workers"][key.name]["fact"] == "not_started" and cli.calls == before
    monkeypatch.setattr(run_module.time, "sleep", lambda _: None)
    result = json.loads(tools["run_worker"].invoke({"role": "author", "brief": "恢复原任务"}))
    assert result["ok"], result
    assert (Path(resumed.spec.author_checkout) / "demo/resumed.txt").read_text() == "done"
    assert provisioned == ["bx_abc"] and engine.load(key).sandbox_id == "bx_abc"
    assert sum(call[0] == "detach" for call in cli.calls) == 1
    trail = [json.loads(line) for line in (resumed.dir / "trail.jsonl").read_text().splitlines()]
    assert any(row["event"] == "adopt" and row["key"] == key.name for row in trail)
    assert not any(row["event"] == "halted" for row in trail)
    resumed.release()


PRELAUNCH_RESOURCES = ["pending_vm", "pending_fork", "cancel_pending", "cleaned", "unallocated"]


def stage_prelaunch_resources(run, monkeypatch, submission, case):
    engine, key, binding, cli = stopped_worker(run, monkeypatch)
    binding = replace(binding, submission=submission, stop_id=None)
    if case in ("pending_fork", "unallocated"):
        binding = replace(binding, sandbox_id=None, create_requested=case == "pending_fork")
    if case in ("cancel_pending", "cleaned"):
        binding = replace(binding, cancel_requested=True)
    if case == "cleaned":
        binding = replace(binding, stop_id="stop_original", stop_confirmed=True, key_erased=True)
    engine._store(key, binding)
    return engine, key, cli


@pytest.mark.parametrize("submission", ["creating", "prepared"])
@pytest.mark.parametrize("case", PRELAUNCH_RESOURCES)
def test_preparation_resources_block_generation_until_drained(tmp_path, monkeypatch, submission, case):
    v2 = V2Env(tmp_path)
    unit = v2.register()
    run = v2.run(unit)
    engine, key, cli = stage_prelaunch_resources(run, monkeypatch, submission, case)
    assert engine.is_drained(key) == (case == "cleaned" or (case == "unallocated" and submission == "creating"))
    release_claim(ClaimStore(v2.claims_root), v2.gateway(), TICKET, unit.run_id, "controller released")
    next_unit = v2.register(f"t{TICKET}-2")
    if case == "cleaned" or (case == "unallocated" and submission == "creating"):
        second = v2.run(next_unit)
        assert second.generation == 2
        second.release()
    else:
        with pytest.raises(ClaimRefused, match="Boat"):
            v2.run(next_unit)
        assert v2.claim_record()["generation"] == 1
    assert_no_collection(run, key, cli)


@pytest.mark.parametrize("submission", ["creating", "prepared"])
@pytest.mark.parametrize("case", PRELAUNCH_RESOURCES)
def test_preparation_resources_keep_queue_slot_until_drained(queued, monkeypatch, submission, case):
    v2, cutover, intake, signer = queued
    unit = intake.register(TICKET)
    authorize(v2, cutover, unit, signer)
    run = open_v2_run(v2.home, unit, load_unit(v2.home, unit.run_id)[1], executor(v2, cutover, unit),
                      MODELS, launcher=FAKE, source_repo=v2.source)
    engine, key, cli = stage_prelaunch_resources(run, monkeypatch, submission, case)
    release_claim(intake.claims, v2.gateway(), TICKET, unit.run_id, "controller released")
    v2.github.issues[TICKET]["labels"].remove("deepagents:queue")
    v2.github.add_issue(TICKET + 1, body=f"Part of [SPEC #{SPEC}]", parent=SPEC,
                        labels=("ready-for-agent", "deepagents:queue"))
    seen = []
    rows = intake.once(lambda item: seen.append(item.ticket) or 0)
    if case == "cleaned" or (case == "unallocated" and submission == "creating"):
        assert seen == [TICKET + 1]
    else:
        assert seen == []
        assert rows[TICKET]["phase"] == "active"
        assert rows[TICKET + 1]["phase"] == "queued"
    assert_no_collection(run, key, cli)
