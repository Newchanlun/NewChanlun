import copy
import hashlib
import json
import shlex
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import git

from pilot1742 import delivery, patch_read
from pilot1742 import external_review as module
from pilot1742.delivery import EffectPending, RepoGateway, Stale
from pilot1742.external_review import (
    CONTEXT,
    MODELS,
    TOKEN_PERMISSIONS,
    ExternalReview,
    ReviewTarget,
    StatusPublisher,
    load_target,
    validate_review,
)
from pilot1742.github_app import (
    AppIdentity,
    GitHubAppClient,
    IdentityError,
    OutcomeUnknown,
)
from pilot1742.patch_read import WHOLE_PATCH, FrozenPatch, reads_candidate_patch


class Gateway:
    bot = "newchanlun-deepagents-1742[bot]"
    def __init__(self, env):
        self.client = SimpleNamespace(identity=SimpleNamespace(repository_id=1150335160))
        self.pr = {"number": 1810, "state": "open", "draft": False, "user": {"login": "business-owner"},
                   "base": {"repo": {"id": 1150335160}, "ref": "main", "sha": env.base},
                   "head": {"repo": {"id": 1150335160}, "ref": "feature/business", "sha": git(env.source, "rev-parse", "HEAD")}}
        self.rows, self.sent = [], []
        self.fault, self.hide, self.after_write = False, False, None
    def get_pr(self, number):
        assert number == 1810
        return copy.deepcopy(self.pr)
    def statuses(self, sha):
        if self.hide:
            return []
        return copy.deepcopy([r for r in self.rows if r["sha"] == sha])
    def set_status(self, sha, context, state, description):
        self.sent.append(state)
        if self.fault:
            raise OutcomeUnknown("已发送结果不明")
        self.rows.insert(0, {"id": len(self.rows) + 1, "sha": sha, "context": context, "state": state,
                             "description": description, "creator": {"login": self.bot, "type": "Bot"}})
        if self.after_write:
            self.after_write()


@pytest.fixture
def lane(env, monkeypatch):
    for i in range(2):
        (env.source / f"changed-{i}").write_text(str(i))
        git(env.source, "add", ".")
        git(env.source, "commit", "-qm", f"change-{i}")
    monkeypatch.setattr(module, "SOURCE_REPO", env.source)
    gateway = Gateway(env)
    return ExternalReview(gateway, source=env.source, state_root=env.home / "review",
                          checkout_root=env.home / "clones", poll_seconds=0.01,
                          launcher=[sys.executable, str(Path(__file__).with_name("external_review_child.py"))])


def test_business_owner_multi_commit_pr_and_idempotent_resume(lane):
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS"
    assert [r["model"] for r in result["reviews"]] == list(MODELS)
    assert len({r["session_id"] for r in result["reviews"]}) == 2
    assert lane.gateway.sent == ["pending", "success"]
    target = ReviewTarget(**result["target"])
    for model in MODELS:
        folder = lane.state_root / "runs" / target.key / model
        launch = json.loads((folder / "launch.json").read_text())
        assert "changed-0" in launch["prompt"] and "changed-1" in launch["prompt"]
        assert target.merge_base_sha == lane.gateway.pr["base"]["sha"]
        assert not Path(launch["checkout"]).exists()
        assert (folder / "events.jsonl").is_file() and (folder / "session.jsonl").is_file()
    before = sorted(lane.checkout_root.glob("*/*"))
    assert lane.review_pr(1810)["run_id"] == result["run_id"]
    assert sorted(lane.checkout_root.glob("*/*")) == before
    assert lane.gateway.sent == ["pending", "success"]


@pytest.mark.parametrize("draft", [True, False])
def test_draft_and_non_app_author_are_accepted(lane, draft):
    lane.gateway.pr["draft"] = draft
    assert load_target(lane.gateway, 1810)["head_ref"] == "feature/business"


@pytest.mark.parametrize("change", [lambda p: p.update(state="closed"),
    lambda p: p["base"].update(ref="other"), lambda p: p["head"]["repo"].update(id=9),
    lambda p: p["head"].update(sha="missing"), lambda p: p.pop("draft")])
def test_invalid_target_does_not_launch_or_publish(lane, change):
    change(lane.gateway.pr)
    with pytest.raises(IdentityError):
        lane.review_pr(1810)
    assert lane.gateway.sent == []
    assert not lane.checkout_root.exists()


def test_missing_source_objects_fail_before_pending(lane):
    lane.gateway.pr["head"]["sha"] = "f" * 40
    with pytest.raises(IdentityError, match="needs_source_sync"):
        lane.review_pr(1810)
    assert not lane.gateway.sent


def test_complete_block_maps_failure_and_is_not_retried(lane):
    lane.target(1810, 1)
    (lane.state_root / "runs" / "fake-mode").write_text("BLOCK")
    assert lane.review_pr(1810)["verdict"] == "BLOCK"
    assert lane.gateway.sent == ["pending", "failure"]
    assert lane.review_pr(1810)["verdict"] == "BLOCK"
    assert lane.gateway.sent == ["pending", "failure"]


@pytest.mark.parametrize("field", ["base", "head"])
def test_drift_prevents_publish_even_if_done(lane, field):
    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    publisher = StatusPublisher(lane.gateway, target, folder, lane.state_root / "locks")
    publisher.publish("success")
    lane.gateway.pr[field]["sha"] = "e" * 40
    with pytest.raises(Stale):
        publisher.publish("success")
    assert lane.gateway.sent == ["success"]


def test_post_write_drift_is_stale_not_success(lane):
    lane.gateway.after_write = lambda: lane.gateway.pr["head"].update(sha="e" * 40)
    result = lane.review_pr(1810)
    assert result["verdict"] == "STALE"
    assert lane.gateway.sent == ["pending"]


def test_unknown_write_only_reconciles_without_republish(lane):
    target = lane.target(1810, 1)
    lane.gateway.fault = True
    for _ in range(2):
        with pytest.raises(EffectPending):
            lane.review_pr(1810)
    assert lane.gateway.sent == ["pending"]
    lane.reconcile(target.run_id, "已核远端请求确未生效")
    lane.gateway.fault = False
    assert lane.review_pr(1810)["verdict"] == "PASS"
    assert lane.gateway.sent == ["pending", "pending", "success"]


def test_newer_failure_blocks_old_success_and_done(lane):
    lane.review_pr(1810)
    lane.gateway.rows.insert(0, {**lane.gateway.rows[0], "id": 999, "state": "failure"})
    with pytest.raises(EffectPending):
        lane.review_pr(1810)
    assert lane.gateway.sent == ["pending", "success"]


def test_upload_pass_is_not_a_launch_and_missing_supervisor_never_redispatches(lane):
    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    worker = folder / MODELS[0]
    worker.mkdir()
    (worker / "result.json").write_text('{"summary":"VERDICT: PASS"}')
    (worker / "launch.json").write_text(json.dumps({"model": MODELS[0], "launch_id": "test"}))
    for _ in range(2):
        with pytest.raises(EffectPending):
            lane.review_pr(1810)
    assert lane.gateway.sent == ["pending"]
    assert not lane.checkout_root.exists()


@pytest.mark.parametrize("mutation", [lambda r: r.update(status="failed"), lambda r: r.update(status="cancelled"),
    lambda r: r.update(turn_completed=False), lambda r: r.update(exit_code=1),
    lambda r: r.update(model="other"), lambda r: r.update(session_id="wrong"),
    lambda r: r.pop("filesystem"), lambda r: r["filesystem"].update(source_write="ALLOWED"),
    lambda r: r["after"].update(status=" M README"), lambda r: r.update(result={"summary": "VERDICT: PASS"})])
def test_terminal_receipt_requires_supervision_evidence(lane, mutation):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    launch = json.loads((folder / "launch.json").read_text())
    receipt = json.loads((folder / "receipt.json").read_text())
    mutation(receipt)
    assert validate_review(target, launch, receipt, folder, lane.source).verdict == "FAILED"


RECONNECT_CASES = json.loads((Path(__file__).parent / "fixtures" / "codex-reconnect.json").read_text())


@pytest.mark.parametrize("scenario", RECONNECT_CASES["cases"], ids=lambda case: case["name"])
def test_reconnect_protocol_matches_child_supervision(lane, scenario):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    launch = json.loads((folder / "launch.json").read_text())
    receipt = json.loads((folder / "receipt.json").read_text())
    session = RECONNECT_CASES["session_id"]
    events = [{"type": "thread.started", "thread_id": session},
              _command(f"git diff {target.merge_base_sha} {target.head_sha}"), *scenario["events"]]
    (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (folder / "session.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"id": session}}) + "\n")
    receipt.update(session_id=session, result=scenario["result"], exit_code=scenario["exit_code"])
    outcome = validate_review(target, launch, receipt, folder, lane.source)
    assert outcome.verdict == scenario["verdict"], outcome.reason
    assert outcome.session_id == (None if scenario["verdict"] == "FAILED" else session)


def test_symlink_session_cannot_prove_pass(lane, tmp_path):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    session = folder / "session.jsonl"
    other = tmp_path / "uploaded-pass"
    session.rename(other)
    session.symlink_to(other)
    assert validate_review(target, json.loads((folder / "launch.json").read_text()),
                           json.loads((folder / "receipt.json").read_text()), folder, lane.source).verdict == "FAILED"


def test_status_pagination_error_cannot_mean_absent_or_publish(lane):
    lane.gateway.statuses = lambda sha: (_ for _ in ()).throw(IdentityError("分页失败"))
    with pytest.raises(IdentityError):
        lane.review_pr(1810)
    assert not lane.gateway.sent


def test_set_status_retains_old_success_api():
    requests = []
    client = SimpleNamespace(identity=SimpleNamespace(repository="owner/repo"), bot_login="app[bot]",
                             api=lambda method, path, **kw: requests.append((method, path, kw)))
    gateway = RepoGateway(client)
    gateway.create_status("a" * 40, "old", "description")
    gateway.set_status("b" * 40, CONTEXT, "error", "review failed")
    assert [r[2]["json"]["state"] for r in requests] == ["success", "error"]
    assert "target_url" not in requests[1][2]["json"]
    with pytest.raises(ValueError):
        gateway.set_status("b" * 40, CONTEXT, "neutral", "bad")


def test_token_requests_only_external_review_permissions(tmp_path, monkeypatch):
    identity = AppIdentity(5486877, 179444545, 1150335160, "Newchanlun/NewChanlun",
                           "newchanlun-deepagents-1742", tmp_path / "unused.pem")
    captured = []
    import pilot1742.github_app as app
    monkeypatch.setattr(app, "_read_private_key", lambda path: b"fixture")
    monkeypatch.setattr(app.jwt, "encode", lambda *a, **kw: "fixture-jwt")
    def transport(request):
        if request.url.path == "/app":
            value = {"id": identity.app_id, "slug": identity.app_slug}
        elif request.url.path.endswith("/access_tokens"):
            captured.append(json.loads(request.content))
            value = {"token": "fixture", "permissions": TOKEN_PERMISSIONS, "expires_at": "2099-01-01T00:00:00Z"}
        else:
            value = {"id": identity.installation_id, "app_id": identity.app_id, "app_slug": identity.app_slug,
                     "account": {"login": "Newchanlun"}, "repository_selection": "selected",
                     "suspended_at": None, "permissions": app.INSTALLATION_PERMISSIONS}
        return httpx.Response(200, json=value)
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS, transport=httpx.MockTransport(transport)) as client:
        client._ensure_token()
    assert captured == [{"repository_ids": [1150335160], "permissions": {
        "metadata": "read", "contents": "read", "pull_requests": "read", "statuses": "write"}}]


def test_recover_after_spawn_without_second_model_call(lane, monkeypatch):
    original = module._save
    crashed = False
    def save(path, value):
        nonlocal crashed
        if path.name == "process.json" and not crashed:
            crashed = True
            raise KeyboardInterrupt("crash after spawn before process record")
        return original(path, value)
    monkeypatch.setattr(module, "_save", save)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS"
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()) == sorted(MODELS)
    assert lane.gateway.sent == ["pending", "success"]


def test_new_attempt_supersedes_inflight_old_run(lane):
    first = lane.target(1810, 1)
    second = lane.target(1810, 2)
    old = StatusPublisher(lane.gateway, first, lane.state_root / "runs" / first.key, lane.state_root / "locks")
    new = StatusPublisher(lane.gateway, second, lane.state_root / "runs" / second.key, lane.state_root / "locks")
    old.publish("pending")
    new.publish("pending")
    new.publish("failure")
    with pytest.raises(Stale):
        old.publish("success")
    with pytest.raises(Stale):
        old.publish("pending")
    assert lane.gateway.sent == ["pending", "pending", "failure"]


def test_status_transport_pages_are_complete_and_failure_does_not_publish(lane):
    requests = []
    pr = lane.gateway.pr
    identity = AppIdentity(5486877, 179444545, 1150335160, "Newchanlun/NewChanlun",
                           "newchanlun-deepagents-1742", Path("/unused-fixture.pem"))
    def transport(request):
        requests.append(request)
        if request.url.path.endswith("/pulls/1810"):
            return httpx.Response(200, json=pr)
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200, json=[], headers={"Link": '<https://api.github.com/x?page=2>; rel="next"'})
        return httpx.Response(500, json={"error": "fixture"})
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS, transport=httpx.MockTransport(transport)) as client:
        client._token = "fixture"
        client._expires_at = 99999999999
        lane.gateway = RepoGateway(client)
        with pytest.raises(IdentityError):
            lane.review_pr(1810)
    assert len([r for r in requests if r.url.path.endswith("/statuses")]) == 2
    assert all(r.method == "GET" for r in requests)


def test_older_unstarted_target_cannot_supersede_newer_attempt(lane):
    first = lane.target(1810, 1)
    second = lane.target(1810, 2)
    new = StatusPublisher(lane.gateway, second, lane.state_root / "runs" / second.key, lane.state_root / "locks")
    new.publish("pending")
    old = StatusPublisher(lane.gateway, first, lane.state_root / "runs" / first.key, lane.state_root / "locks")
    with pytest.raises(Stale):
        old.publish("pending")
    assert lane.gateway.sent == ["pending"]


def test_publication_rechecks_controller_code(lane):
    target = lane.target(1810, 1)
    publisher = StatusPublisher(lane.gateway, target, lane.state_root / "runs" / target.key, lane.state_root / "locks")
    git(lane.source, "commit", "--allow-empty", "-qm", "controller advanced")
    with pytest.raises(Stale, match="controller"):
        publisher.publish("success")
    assert not lane.gateway.sent


@pytest.mark.parametrize("args", [["--help"], ["review-pr", "--help"], ["status", "--help"]])
def test_cli_help_is_offline(args):
    with pytest.raises(SystemExit) as caught:
        module.main(args)
    assert caught.value.code == 0


@pytest.mark.parametrize("number", ["0", "-1", "abc"])
def test_cli_rejects_invalid_pr_before_auth(number):
    with pytest.raises(SystemExit) as caught:
        module.main(["review-pr", "--pr", number, "--private-key", "/never-read.pem"])
    assert caught.value.code == 2


def test_cli_status_uses_no_auth(lane, monkeypatch, capsys):
    monkeypatch.setattr(module, "ExternalReview", lambda gateway: lane)
    monkeypatch.setattr(module, "GitHubAppClient", lambda *a, **kw: pytest.fail("status must stay offline"))
    assert module.main(["status", "--pr", "1810"]) == 0
    assert json.loads(capsys.readouterr().out) == []


@pytest.mark.parametrize("history_count", [1, 4])
def test_snapshot_omits_obsolete_blobs_but_preserves_graph_and_diff(lane, tmp_path, history_count):
    import os
    old = lane.source / "obsolete.bin"
    old_blobs = []
    for i in range(history_count):
        old.write_bytes(os.urandom(2 * 1024 * 1024))
        git(lane.source, "add", ".")
        git(lane.source, "commit", "-qm", f"unrelated old payload {i}")
        old_blobs.append(git(lane.source, "rev-parse", "HEAD:obsolete.bin"))
    old.unlink()
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "remove old payload")
    base = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-qb", "candidate")
    (lane.source / "later").write_text("new PR\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "PR first")
    (lane.source / "later").write_text("whole PR\n")
    git(lane.source, "commit", "-am", "PR second", "-q")
    head = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-q", "main")
    (lane.source / "base-only").write_text("main advanced\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "base advanced")
    lane.gateway.pr["base"]["sha"] = git(lane.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = head
    target = lane.target(1810, 1)
    checkout = tmp_path / "snapshot"
    frozen = module.prepare_review(target, lane.source, checkout)
    assert frozen.changed_files == ("later",)
    assert git(checkout, "status", "--porcelain", "--untracked-files=all") == ""
    assert git(checkout, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert git(checkout, "merge-base", target.base_sha, head) == base
    assert git(checkout, "diff", "--binary", base, head) == git(lane.source, "diff", "--binary", base, head)
    assert git(checkout, "log", "--format=%H", head) == git(lane.source, "log", "--format=%H", head)
    import subprocess
    for old_blob in old_blobs:
        assert subprocess.run(["git", "-C", str(checkout), "cat-file", "-e", old_blob], capture_output=True).returncode != 0
    assert "remote" not in (checkout / ".git/config").read_text()
    assert not (checkout / ".git/objects/info/alternates").exists()
    assert not (checkout / ".git/hooks").exists()
    assert sum(p.stat().st_size for p in (checkout / ".git/objects").rglob("*.pack")) < 128 * 1024


def test_terminal_reclaims_only_checkout_and_retains_evidence(lane):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    for model in MODELS:
        worker = lane.state_root / "runs" / target.key / model
        assert not Path(module._read(worker / "launch.json")["checkout"]).exists()
        for name in ("launch.json", "receipt.json", "events.jsonl", "session.jsonl"):
            assert (worker / name).is_file()
    assert lane.review_pr(1810)["verdict"] == "PASS"
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()) == sorted(MODELS)


@pytest.mark.parametrize("crash_point", ["during-prepare", "after-prepare"])
def test_prepare_interruption_recovers_without_duplicate_dispatch(lane, monkeypatch, crash_point):
    original = module.prepare_review
    crashed = False
    def prepare(target, source, checkout):
        nonlocal crashed
        if not crashed:
            crashed = True
            if crash_point == "during-prepare":
                checkout.mkdir(parents=True)
                (checkout / "partial").write_text("interrupted snapshot")
            else:
                original(target, source, checkout)
            raise KeyboardInterrupt("prepare interrupted")
        return original(target, source, checkout)
    monkeypatch.setattr(module, "prepare_review", prepare)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    assert lane.review_pr(1810)["verdict"] == "PASS"
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()) == sorted(MODELS)


def test_fresh_reviewers_run_concurrently_and_any_failure_fails_the_run(lane):
    lane.target(1810, 1)
    (lane.state_root / "runs" / "fake-mode").write_text("failed")
    result = lane.review_pr(1810)
    assert result["verdict"] == "FAILED"
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()) == sorted(MODELS)
    assert not list(lane.checkout_root.iterdir())


def test_reviewers_overlap_in_time(lane, monkeypatch):
    import threading
    started, both = [], threading.Event()
    real = lane.run_review
    def run_review(target, model, folder):
        started.append(model)
        if len(started) == len(MODELS):
            both.set()
        assert both.wait(30), "第二位 reviewer 没有在第一位结束前启动"
        return real(target, model, folder)
    monkeypatch.setattr(lane, "run_review", run_review)
    assert lane.review_pr(1810)["verdict"] == "PASS"


def test_resume_after_first_failure_stays_serial(lane):
    target = lane.target(1810, 1)
    (lane.state_root / "runs" / target.key / MODELS[0]).mkdir()
    (lane.state_root / "runs" / "fake-mode").write_text("failed")
    assert lane.review_pr(1810)["verdict"] == "FAILED"
    assert (lane.state_root / "runs" / "launches").read_text().splitlines() == [MODELS[0]]


def test_exited_supervisor_before_receipt_is_terminal_not_pending(lane):
    lane.launcher = [sys.executable, "-c", "raise SystemExit(3)"]
    result = lane.review_pr(1810)
    assert result["verdict"] == "FAILED"
    assert lane.gateway.sent == ["pending", "error"]
    assert lane.review_pr(1810)["verdict"] == "FAILED"


def test_stale_publication_preserves_completed_reviews(lane):
    def drift_after_success():
        if lane.gateway.sent[-1] == "success":
            lane.gateway.pr["head"]["sha"] = "e" * 40
    lane.gateway.after_write = drift_after_success
    result = lane.review_pr(1810)
    assert result["verdict"] == "STALE"
    assert [r["verdict"] for r in result["reviews"]] == ["PASS", "PASS"]


def test_low_space_refuses_registration_before_attempt_or_status(lane, monkeypatch):
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    with pytest.raises(IdentityError, match="空间不足：2 份并发快照共需 .*可用 1 bytes；未登记 attempt"):
        lane.review_pr(1810)
    assert not list((lane.state_root / "runs").glob("*/target.json"))
    assert lane.gateway.sent == []
    assert not lane.checkout_root.exists()


def test_admission_counts_every_reviewer_snapshot(lane, monkeypatch):
    data = module.load_target(lane.gateway, 1810)
    merge_base = git(lane.source, "merge-base", data["base_sha"], data["head_sha"])
    probe = module.ReviewTarget(**data, merge_base_sha=merge_base, run_id="probe", attempt=1,
                                policy_version=module.POLICY, controller_code_head="x", registered_at_ns=0)
    _, single = module.snapshot_plan(lane.source, probe)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=single * len(MODELS) - 1))
    with pytest.raises(IdentityError, match=f"共需 {single * len(MODELS)} bytes"):
        lane.review_pr(1810)
    assert lane.gateway.sent == []


def test_cleanup_preserves_live_or_unknown_activity(lane, monkeypatch):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key
    worker = folder / MODELS[0]
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    checkout.mkdir(parents=True)
    (checkout / "retained").write_text("active source")
    monkeypatch.setattr(module, "_ps_rows", lambda: [(8123, 8123, "S", f"unknown-tool {checkout}")])
    assert not lane.cleanup_checkout(target, MODELS[0], folder)
    assert (checkout / "retained").exists()
    monkeypatch.setattr(module, "_ps_rows", lambda: [])
    assert lane.cleanup_checkout(target, MODELS[0], folder)
    assert (worker / "session.jsonl").is_file()


def test_cleanup_preserves_unconfirmed_container(lane):
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key
    worker = folder / MODELS[0]
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    checkout.mkdir(parents=True)
    receipt = module._read(worker / "receipt.json")
    receipt["container_closed"] = False
    module._save(worker / "receipt.json", receipt)
    assert not lane.cleanup_checkout(target, MODELS[0], folder)
    assert checkout.exists()


@pytest.mark.parametrize("removed", [True, False])
def test_cleanup_removes_review_volume_the_supervisor_left(lane, removed):
    """#1986：监督删卷失败（volume_removed=false）时，宿主回收 checkout 时补删本 launch 的卷；删不掉记 retained，checkout 照删。"""
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key
    worker = folder / MODELS[0]
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    checkout.mkdir(parents=True)
    volume = module.REVIEW_VOLUME_PREFIX + module._read(worker / "launch.json")["launch_id"]
    receipt = module._read(worker / "receipt.json")
    module._save(worker / "receipt.json", {**receipt, "volume": volume, "volume_removed": False})
    calls = []
    lane.remove_review_volume = lambda name: calls.append(name) or removed
    assert lane.cleanup_checkout(target, MODELS[0], folder)
    assert calls == [volume] and not checkout.exists()
    assert module._read(worker / "checkout-cleanup.json") == {
        "state": "removed", "checkout": str(checkout), "volume": volume, "volume_state": "removed" if removed else "retained"}
    # 监督已删掉的卷不再删；回执里不属于本 launch 的卷名拒绝，不删别的卷。
    calls.clear()
    module._save(worker / "receipt.json", {**receipt, "volume": volume, "volume_removed": True})
    assert lane.cleanup_checkout(target, MODELS[0], folder) and calls == []
    module._save(worker / "receipt.json", {**receipt, "volume": module.REVIEW_VOLUME_PREFIX + "0" * 36, "volume_removed": False})
    with pytest.raises(IdentityError, match="不属于本次 launch"):
        lane.cleanup_checkout(target, MODELS[0], folder)
    assert calls == []


class FakeDocker:
    """按标签列出的卷与容器；记录每条 docker 命令。rm/volume rm 真的把对象从列表里删掉。"""

    def __init__(self, volumes=(), containers=(), volume_rm_stderr=None):
        self.volumes = dict(volumes)        # name -> launch_id
        self.containers = dict(containers)  # id -> (launch_id, volume or None)
        self.volume_rm_stderr = volume_rm_stderr
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        ok = lambda out="": subprocess.CompletedProcess(args, 0, out, "")
        if args[:2] == ["volume", "ls"]:
            return ok("".join(f"{n}\t{l}\n" for n, l in self.volumes.items()))
        if args[:2] == ["ps", "-a"] and "--format" in args:
            return ok("".join(f"{c}\t{l}\n" for c, (l, _) in self.containers.items()))
        if args[:2] == ["ps", "-a"]:
            volume = args[-1].removeprefix("volume=")
            return ok("".join(f"{c}\n" for c, (_, v) in self.containers.items() if v == volume))
        if args[:2] == ["rm", "-f"]:
            self.containers.pop(args[2], None)
            return ok()
        if args[:2] == ["volume", "rm"]:
            if self.volume_rm_stderr:
                return subprocess.CompletedProcess(args, 1, "", self.volume_rm_stderr)
            if any(v == args[2] for _, v in self.containers.values()):
                return subprocess.CompletedProcess(args, 1, "", "volume is in use")
            return ok() if self.volumes.pop(args[2], None) else subprocess.CompletedProcess(args, 1, "", "no such volume")
        raise AssertionError(args)


def test_remove_review_volume_removes_holders_first_and_only_accepts_review_names(lane):
    with pytest.raises(IdentityError):
        lane.remove_review_volume("f3-controller-data")
    name = module.REVIEW_VOLUME_PREFIX + "a" * 36
    # Sandcastle close 吞掉 rm 错误时残留的审阅容器、没删掉的辅助容器都会占住卷。
    lane.docker = FakeDocker({name: "a" * 36}, {"c1": ("a" * 36, name), "c2": ("x", None)})
    assert lane.remove_review_volume(name)
    assert lane.docker.calls == [["ps", "-a", "-q", "--filter", f"volume={name}"], ["rm", "-f", "c1"], ["volume", "rm", name]]
    assert lane.remove_review_volume(name)  # 已不存在也算删掉
    lane.docker = FakeDocker(volume_rm_stderr="volume is in use")
    assert not lane.remove_review_volume(name)


def test_reaper_removes_dead_launch_volume_and_containers_before_next_dispatch(lane, monkeypatch):
    """#1986 BLOCK：监督被 SIGTERM（Sandcastle 钩子 process.exit，finally 不跑、无回执）或 SIGKILL 打断后，
    合成回执没有 volume 字段、container_closed=false，卷和容器只剩标签。下一次派发前 reaper 必须按标签收掉。"""
    lane.launcher = [sys.executable, "-c", "raise SystemExit(3)"]  # 监督没写回执就退出
    assert lane.review_pr(1810)["verdict"] == "FAILED"
    first = ReviewTarget(**module._read(next((lane.state_root / "runs").glob("*/target.json"))))
    dead = module._read(lane.state_root / "runs" / first.key / MODELS[0] / "launch.json")["launch_id"]
    receipt = module._read(lane.state_root / "runs" / first.key / MODELS[0] / "receipt.json")
    assert "volume" not in receipt and receipt["container_closed"] is False
    # 存活 launch：别的 run 正在跑的监督（进程表里有它的 --output-dir）；未登记的 launch_id 不属于本 state_root。
    live_worker = lane.state_root / "runs" / "live-run" / MODELS[1]
    live_worker.mkdir(parents=True)
    live = str(uuid.uuid4())
    module._save(live_worker / "launch.json", {"launch_id": live})
    unknown = str(uuid.uuid4())
    vol = lambda launch: module.REVIEW_VOLUME_PREFIX + launch
    lane.docker = FakeDocker(
        {vol(dead): dead, vol(live): live, vol(unknown): unknown},
        {"review-dead": (dead, vol(dead)), "helper-dead": (dead, vol(dead)), "review-live": (live, vol(live)),
         "helper-unknown": (unknown, vol(unknown))})
    real_rows = module._ps_rows
    monkeypatch.setattr(module, "_ps_rows", lambda: [*real_rows(), (4242, 4242, "S", f"tsx worker --output-dir {live_worker}")])
    lane.launcher = [sys.executable, str(Path(__file__).with_name("external_review_child.py"))]
    assert lane.review_pr(1810, 2)["verdict"] == "PASS"
    assert vol(dead) not in lane.docker.volumes
    assert "review-dead" not in lane.docker.containers and "helper-dead" not in lane.docker.containers
    assert set(lane.docker.volumes) == {vol(live), vol(unknown)}
    assert set(lane.docker.containers) == {"review-live", "helper-unknown"}
    log = [json.loads(line) for line in (lane.state_root / "volume-reaper.jsonl").read_text().splitlines()]
    reaped = [e for e in log if e["action"] == "reaped"]
    assert reaped and reaped[0]["launch_id"] == dead and reaped[0]["volumes"] == [vol(dead)]
    assert any(e["action"] == "retained" and e["launch_id"] == unknown for e in log)
    assert not any(e.get("launch_id") == live for e in log)
    # 每轮一行计数：删掉的、留下的（未登记 launch）、存活 launch 占着的卷都报数。
    summaries = [e for e in log if e["action"] == "summary"]
    assert summaries[0] == {"at": summaries[0]["at"], "action": "summary", "reaped_volumes": 1, "retained_volumes": 1,
                            "live_volumes": 1}
    # 两位 reviewer 并发派发，各跑一轮 reaper，可能都看见同一个死卷；重复删除无害。
    assert all(s["retained_volumes"] == 1 and s["live_volumes"] == 1 for s in summaries)


def test_reaper_failure_never_blocks_dispatch(lane):
    lane.docker = lambda args: subprocess.CompletedProcess(args, 125, "", "docker unavailable")
    assert lane.review_pr(1810)["verdict"] == "PASS"
    log = [json.loads(line) for line in (lane.state_root / "volume-reaper.jsonl").read_text().splitlines()]
    assert {e["reason"] for e in log} == {"docker_unavailable"}


def test_multiple_attempts_reclaim_each_checkout(lane):
    for attempt in (1, 2, 3):
        assert lane.review_pr(1810, attempt)["verdict"] == "PASS"
        assert not list(lane.checkout_root.iterdir())
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()) == sorted(list(MODELS) * 3)
    assert len(list((lane.state_root / "runs").glob("*/outcome.json"))) == 3


def test_no_intent_never_grants_checkout_deletion(lane):
    target = lane.target(1810, 1)
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    checkout.mkdir(parents=True)
    assert not lane.cleanup_checkout(target, MODELS[0], lane.state_root / "runs" / target.key)
    assert checkout.exists()



def test_failed_spawn_has_terminal_receipt_and_reclaims_checkout(lane):
    lane.launcher = ["/nonexistent-fixture-launcher"]
    result = lane.review_pr(1810)
    assert result["verdict"] == "FAILED"
    assert lane.gateway.sent == ["pending", "error"]
    assert not list(lane.checkout_root.iterdir())
    target = ReviewTarget(**result["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    assert module._read(worker / "receipt.json")["failure_reason"] == "SupervisorNotStarted"


def test_space_exhausted_after_prepare_stops_before_model(lane, monkeypatch):
    def disk_usage(path):  # 只有模型启动前对 checkout 本身的复查看到空间耗尽
        return SimpleNamespace(free=1 if Path(path).name in MODELS else 10**12)
    monkeypatch.setattr(module.shutil, "disk_usage", disk_usage)
    result = lane.review_pr(1810)
    assert result["verdict"] == "FAILED"
    assert "模型启动前" in result["reviews"][0]["reason"]
    assert not (lane.state_root / "runs" / "launches").exists()
    assert not list(lane.checkout_root.iterdir())


def _launches(lane):
    path = lane.state_root / "runs" / "launches"
    return len(path.read_text().splitlines()) if path.exists() else 0


def _advance_main(lane, env, *, conflict=False, rewrite=None):
    """main 前进后把 main 合进 PR head，模拟 strict 下的追平。"""
    src, head = lane.source, git(lane.source, "rev-parse", "HEAD")
    git(src, "checkout", "-q", "-b", f"main-{len(lane.gateway.rows)}", str(env.base))
    # 每次前进写不同内容，免得同一秒内两次前进生成同一个提交（head 不变就测不到「新 head」）。
    (src / ("changed-0" if conflict else "unrelated")).write_text("main side\n" if conflict else f"main side {len(lane.gateway.rows)}\n")
    git(src, "add", ".")
    git(src, "commit", "-qm", "main advances")
    base = git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", head)
    if conflict:
        assert subprocess.run(["git", "-C", str(src), "merge", "-q", "--no-edit", base],
                              capture_output=True).returncode != 0
        (src / "changed-0").write_text("0\nmain side\n")
        git(src, "add", ".")
        git(src, "commit", "-qm", "resolve conflict")
    else:
        git(src, "merge", "-q", "--no-edit", base)
    if rewrite is not None:
        (src / "changed-1").write_text(rewrite)
        git(src, "commit", "-qam", "patch changes")
    lane.gateway.pr["base"]["sha"], lane.gateway.pr["head"]["sha"] = base, git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", head)  # 宿主 controller 不随 PR 追平而变，只在部署时变


def test_same_patch_on_new_base_reuses_pass_without_model(lane, env):
    first = lane.review_pr(1810)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["reviews"] == []
    assert result["reused_from"]["run_id"] == first["run_id"]
    assert result["target"]["patch_id"] == first["target"]["patch_id"]
    assert result["target"]["merge_base_sha"] != first["target"]["merge_base_sha"]
    assert _launches(lane) == len(MODELS)
    assert lane.gateway.sent == ["pending", "success", "pending", "success"]
    row = lane.gateway.rows[0]
    assert row["sha"] == lane.gateway.pr["head"]["sha"]
    assert f"reuse={first['run_id']} p={first['target']['patch_id'][7:19]}" in row["description"]
    assert len(row["description"]) <= 140
    assert lane.review_pr(1810)["publication"]["id"] == row["id"]  # 重跑只读回，不重发
    assert lane.gateway.sent == ["pending", "success", "pending", "success"]


def test_success_recovered_by_same_attempt_records_publication_and_is_reusable(lane, env, monkeypatch):
    # #1942 attempt 49285：终态 success 已送达但读回一直看不到，同一 attempt 重跑认回后 outcome 缺 publication，
    # 追平后同补丁没法沿用、整轮重审。
    monkeypatch.setattr(delivery, "READBACK_DELAYS", ())
    gateway = lane.gateway
    gateway.after_write = lambda: setattr(gateway, "hide", gateway.sent[-1] == "success")
    with pytest.raises(EffectPending):
        lane.review_pr(1810)
    gateway.hide, gateway.after_write = False, None
    first = lane.review_pr(1810)
    assert gateway.sent == ["pending", "success"]
    folder = lane.state_root / "runs" / ReviewTarget(**first["target"]).key
    saved = json.loads((folder / "outcome.json").read_text())
    assert saved["publication"]["state"] == "success" and saved["publication"]["id"] == gateway.rows[0]["id"]
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["reused_from"]["run_id"] == first["run_id"] and result["reviews"] == []
    assert _launches(lane) == len(MODELS)


# 只改空白也必须重审：git patch-id 会忽略空白，所以补丁身份不用它。
@pytest.mark.parametrize("change", ["patch", "whitespace", "conflict"])
def test_changed_patch_or_conflict_resolution_is_reviewed_again(lane, env, change):
    first = lane.review_pr(1810)
    _advance_main(lane, env, conflict=change == "conflict",
                  rewrite={"patch": "changed again\n", "whitespace": " 1"}.get(change))
    result = lane.review_pr(1810)
    assert result["target"]["patch_id"] != first["target"]["patch_id"]
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)
    assert _launches(lane) == 2 * len(MODELS)


@pytest.mark.parametrize("first_verdict", ["BLOCK", "FAILED"])
def test_non_pass_conclusion_is_not_reused(lane, env, first_verdict):
    launcher = lane.launcher
    if first_verdict == "BLOCK":
        (lane.state_root / "runs").mkdir(parents=True)
        (lane.state_root / "runs" / "fake-mode").write_text("BLOCK")
    else:
        lane.launcher = ["/nonexistent-fixture-launcher"]
    assert lane.review_pr(1810)["verdict"] == first_verdict
    (lane.state_root / "runs" / "fake-mode").unlink(missing_ok=True)
    lane.launcher = launcher
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and "reused_from" not in result
    assert len(result["reviews"]) == len(MODELS)


@pytest.mark.parametrize("claim", ["PASS", "BLOCK"])
def test_zero_tool_conclusion_is_error_not_verdict(lane, claim):
    """#1968：没跑过任何命令的审查员说 PASS 不能放行，说 BLOCK 也不能否决；两种都只能是 error。"""
    _modes(lane, **{MODELS[0]: f"{claim}:notool", MODELS[1]: "PASS"})
    result = lane.review_pr(1810)
    assert result["verdict"] == "FAILED" and result["state"] == "error"
    assert lane.gateway.sent == ["pending", "error"]
    kimi, opus = result["reviews"]
    assert kimi["verdict"] == "FAILED" and "未读取冻结候选补丁" in kimi["reason"]
    assert opus["verdict"] == "PASS"


# lane 的冻结补丁在审查员日志里的样子（git diff merge-base head 的输出）
LANE_PATCH = "".join(f"diff --git a/changed-{i} b/changed-{i}\nnew file mode 100644\n--- /dev/null\n+++ b/changed-{i}\n"
                     f"@@ -0,0 +1 @@\n+{i}\n\\ No newline at end of file\n" for i in range(2))


def _command(script: str, exit_code: int = 0, output: str | None = LANE_PATCH) -> dict:
    """Codex 记录 command_execution 的真实形状：`/bin/bash -lc <shell 引号包好的脚本>`，输出在 aggregated_output；
    `output=None` 是这个字段没进日志。"""
    item = {"type": "command_execution", "command": f"/bin/bash -lc {shlex.quote(script)}",
            "status": "completed" if exit_code == 0 else "failed", "exit_code": exit_code}
    return {"type": "item.completed", "item": item if output is None else {**item, "aggregated_output": output}}


def _verdicts_with_commands(lane, claim: str, cases: dict) -> dict[str, module.ReviewOutcome]:
    """跑一次 PASS/BLOCK 审查，再把 events.jsonl 依次换成每个用例的命令序列重新判定。"""
    _modes(lane, **{model: claim for model in MODELS})
    target = ReviewTarget(**lane.review_pr(1810)["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    events = [json.loads(line) for line in (folder / "events.jsonl").read_text().splitlines()]
    events = [e for e in events if e.get("item", {}).get("type") != "command_execution"]
    launch, receipt = json.loads((folder / "launch.json").read_text()), json.loads((folder / "receipt.json").read_text())
    outcomes = {}
    for case, commands in cases.items():
        (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in [
            events[0], *(c(target) for c in commands), *events[1:]]) + "\n")
        outcomes[case] = validate_review(target, launch, receipt, folder, lane.source)
    return outcomes


def _diff(flags: str = "", tail: str = "") -> list:
    return [lambda t: _command(f"git diff {flags}{' ' if flags else ''}{t.merge_base_sha} {t.head_sha}{tail}")]


def _meta(t) -> str:
    """`git show --no-patch --format='%H%n%an%n%B' <head>` 的输出；提交说明里恰好有改动行 `+0`、`1`。"""
    return f"{t.head_sha}\nSmoke\nfix: quote the change\n\n+0\n1\n"


FAKE = "f" * 40
NOT_A_PATCH_READ = {
    "echo": [lambda t: _command("echo hi")],
    "ls": [lambda t: _command("ls -la /review")],
    "unrelated-file": [lambda t: _command("cat /review/.agents/skills/code-review/SKILL.md")],
    "git-log": [lambda t: _command(f"git log --oneline {t.merge_base_sha}..{t.head_sha}")],
    "wrong-sha": [lambda t: _command(f"git diff {t.merge_base_sha} {FAKE}")],
    "stat-only": _diff("--stat"),
    "failed-diff": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha}", exit_code=128)],
    "sha-outside-diff": [lambda t: _command(f"git log -1 {t.head_sha}; git diff")],
    "var-wrong-sha": [lambda t: _command(f"H={FAKE}; git diff {t.merge_base_sha} $H")],
    "var-echo-not-diff": [lambda t: _command(f"H={t.head_sha}; echo $H")],
    "var-stat-only": [lambda t: _command(f"B={t.merge_base_sha}; H={t.head_sha}; git diff --stat $B $H")],
    # #1969 kimi BLOCK 与准入独审：命令文本里有 git diff 字样，但不是 git 本身在执行
    "echo-diff-text": [lambda t: _command(f"echo git diff {t.merge_base_sha} {t.head_sha}")],
    "printf-diff-text": [lambda t: _command(f"printf '%s\\n' 'git diff {t.merge_base_sha} {t.head_sha}'")],
    "heredoc-diff-text": [lambda t: _command(f"cat <<EOF\ngit diff {t.merge_base_sha} {t.head_sha}\nEOF")],
    "comment-diff-text": [lambda t: _command(f"ls /review # git diff {t.merge_base_sha} {t.head_sha}")],
    "grep-for-diff-text": [lambda t: _command(f'rg -n "git show {t.head_sha}" /review')],
    "diff-tree-raw": [lambda t: _command(f"git diff-tree {t.merge_base_sha} {t.head_sha}")],
    "nested-shell": [lambda t: _command(f'bash -c "git diff {t.merge_base_sha} {t.head_sha}"')],
    "command-substitution": [lambda t: _command(f"x=$(git diff {t.merge_base_sha} {t.head_sha})")],
    # kimi BLOCK：变量代回必须按 shell 语义
    "var-used-before-assign": [lambda t: _command(f"git diff $H; H={t.head_sha}")],
    "var-reassigned-last-wins": [lambda t: _command(f"H={t.head_sha}; H={FAKE}; git diff {t.merge_base_sha} $H")],
    "var-single-quoted": [lambda t: _command(f"H={t.head_sha}; git diff {t.merge_base_sha} '$H' | cat")],
    "var-subshell": [lambda t: _command(f"(H={t.head_sha}); git diff {t.merge_base_sha} $H")],
    "var-suffix": [lambda t: _command(f"H={t.head_sha}; git diff {t.merge_base_sha} ${{H}}x | cat")],
    "var-prefix-assignment": [lambda t: _command(f"H={t.head_sha} git diff {t.merge_base_sha} $H")],
    # 不输出补丁的形式（git 2.50 实测）
    "empty-range": [lambda t: _command(f"git diff {t.head_sha}..{t.head_sha}")],
    "same-commit": [lambda t: _command(f"git diff {t.head_sha} {t.head_sha}")],
    "head-vs-clean-worktree": [lambda t: _command(f"git diff {t.head_sha}")],
    "show-q": [lambda t: _command(f"git show -q {t.head_sha}")],
    "show-quiet": [lambda t: _command(f"git show --quiet {t.head_sha}")],
    "show-s-format": [lambda t: _command(f"git show -s --format=%H {t.head_sha}")],
    "show-no-patch": [lambda t: _command(f"git show --no-patch {t.head_sha}")],
    "show-patch-then-no-patch": [lambda t: _command(f"git show -p --no-patch {t.head_sha}")],
    "show-name-only": [lambda t: _command(f"git show --name-only -p {t.head_sha}")],
    "show-tree-root": [lambda t: _command(f"git show {t.head_sha}:")],
    **{f"diff{flag}": _diff(flag) for flag in ("--name-only", "--name-status", "--numstat", "--shortstat",
                                               "--summary", "--check", "--quiet", "--exit-code", "--raw", "-s",
                                               "--no-patch", "--output=/tmp/p.diff")},
    "trailing-stat": _diff(tail=" --stat"),
    "trailing-name-only": _diff(tail=" --name-only"),
    "ext-diff": [lambda t: _command(f"GIT_EXTERNAL_DIFF=true git diff {t.merge_base_sha} {t.head_sha}")],
    "unknown-sha-piped": [lambda t: _command(f"git diff {'e' * 40} {t.head_sha} | head")],
    # 输出被吞或退出码被掩盖
    "pipe-true": _diff(tail=" | true"),
    "pipe-colon": _diff(tail=" | :"),
    "pipe-cat-devnull": _diff(tail=" | cat >/dev/null"),
    "pipe-head-0": _diff(tail=" | head -0"),
    "pipe-head-n-0": _diff(tail=" | head -n 0"),
    "pipe-grep-q": _diff(tail=" | grep -q x"),
    "or-true": _diff(tail=" || true"),
    "semicolon-true": _diff(tail="; true"),
    "newline-exit-0": _diff(tail="\nexit 0"),
    "background": _diff(tail=" &"),
    "or-guarded": [lambda t: _command(f"true || git diff {t.merge_base_sha} {t.head_sha}")],
    "stdout-devnull": _diff(tail=" >/dev/null"),
    "stdout-devnull-after-dup": _diff(tail=" 2>&1 >/dev/null"),
    "stdout-closed": _diff(tail=" >&-"),
    "unread-file": _diff(tail=" > /tmp/p.diff"),
    # #1969 正式审查 kimi BLOCK 与 #1971：命令文本像读取，记录的输出里却没有冻结补丁
    "if-false-never-runs": [lambda t: _command(f"if false; then git diff {t.merge_base_sha} {t.head_sha}; fi", output="")],
    "file-then-echo-name": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha} >/tmp/p; echo /tmp/p",
                                               output="/tmp/p\n")],
    "file-then-wc": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha} >/tmp/p; wc -l /tmp/p",
                                        output="      14 /tmp/p\n")],
    "exec-stdout-devnull": [lambda t: _command(f"exec >/dev/null; git diff {t.merge_base_sha} {t.head_sha}", output="")],
    "export-external-diff": [lambda t: _command(
        f"export GIT_EXTERNAL_DIFF=true; git diff {t.merge_base_sha} {t.head_sha}", output="")],
    "ext-diff-from-config": [lambda t: _command(f"git diff --ext-diff {t.merge_base_sha} {t.head_sha}",
                                                output="changed-0 is different\nchanged-1 is different\n")],
    "textconv-replaces-content": [lambda t: _command(
        f"git -c diff.t.textconv='echo X' diff {t.merge_base_sha} {t.head_sha}",
        output="diff --git a/changed-0 b/changed-0\n--- /dev/null\n+++ b/changed-0\n@@ -0,0 +1 @@\n"
               "+X /tmp/git-blob-ksCWK9/changed-0\n")],
    "empty-output-exit-0": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha} -- README", output="")],
    "output-not-logged": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha}", output=None)],
    "show-unchanged-file": [lambda t: _command(f"git show {t.head_sha}:README", output="x\n")],
    # #1969 正式审查（bb8aa92e）opus BLOCK：本 PR 没改的文件里有一行与改动行相同（真实仓库里是
    # `from __future__ import annotations` 这类通用行），读它不等于读了补丁；证据须出自所读的改动文件
    "show-unchanged-file-common-line": [lambda t: _command(f"git show {t.head_sha}:README", output="1\n")],
    "show-unchanged-file-numbered": [lambda t: _command("git show HEAD:README | nl -ba", output="     1\t0\n")],
    "show-changed-and-unchanged-file": [lambda t: _command(
        f"git show {t.head_sha}:changed-0 {t.head_sha}:README", output="x\n1\n")],
    "show-changed-file-other-files-line": [lambda t: _command(f"git show {t.head_sha}:changed-0", output="1\n")],
    "show-commit-unrelated-file": [lambda t: _command(
        f"git show {t.head_sha}", output="diff --git a/README b/README\n--- a/README\n+++ b/README\n@@ -1 +1 @@\n-x\n+0\n")],
    "diff-parent-unrelated-file": [lambda t: _command(
        f"git diff {t.head_sha}~1 {t.head_sha}", output="diff --git a/README b/README\n@@ -1 +1 @@\n+1\n")],
    "diff-parent-lines-before-header": [lambda t: _command(
        f"git diff {t.head_sha}~1 {t.head_sha} | grep -n 0", output="5:+0\n")],
    "show-other-commit-and-head": [lambda t: _command(f"git show {t.merge_base_sha} {t.head_sha}")],
    "show-file-dot-slash-after-C": [lambda t: _command(f"git -C /review/sub show {t.head_sha}:./changed-0", output="0\n")],
    "show-missing-path-masked": [lambda t: _command(
        f"git show {t.head_sha}:nope | head", output=f"fatal: path 'nope' does not exist in '{t.head_sha}'\n")],
    # #1969 正式审查 kimi BLOCK（f566ce6b）：输出是整条命令的合并输出，git 之外的段可以印出冻结补丁的改动行
    "kimi-printf-after-empty-diff": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} -- nope; printf '%s\\n' '+0'", output="+0\n")],
    "echo-before-empty-diff": [lambda t: _command(f"echo +0 && git diff {t.merge_base_sha} {t.head_sha} -- nope",
                                                  output="+0\n")],
    "cat-file-before-diff": [lambda t: _command(f"cat /tmp/fake; git diff {t.merge_base_sha} {t.head_sha} -- nope",
                                                output="+0\n")],
    "second-git-prints-text": [lambda t: _command(
        f"git log -1 --format=+0 {t.head_sha}; git diff {t.merge_base_sha} {t.head_sha} -- nope", output="+0\n")],
    "two-patch-reads": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha}; git show {t.head_sha}:changed-0")],
    "git-then-and-echo": _diff(tail=" -- nope | head && echo +0"),
    "pipe-into-python": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} -- nope | python3 -c 'print(\"+0\")'", output="+0\n")],
    "pipe-into-tee": _diff(tail=" | tee /tmp/p"),
    "pipe-into-less": _diff(tail=" | less -R"),
    "filter-reads-file": _diff(tail=" -- nope | grep . /tmp/fake"),
    "filter-stdin-from-file": _diff(tail=" -- nope | cat </tmp/fake"),
    "filter-here-string": _diff(tail=" -- nope | cat <<< +0"),
    "sed-rewrites-lines": [lambda t: _command(f"git show {t.head_sha}:README | sed -n 's/.*/+0/p'", output="+0\n")],
    "sed-inserts-text": [lambda t: _command(f"git show {t.head_sha}:README | sed -n '1i +0'", output="+0\nx\n")],
    "nl-separator-text": [lambda t: _command(f"git show {t.head_sha}:README | nl -ba -s '\t+0'", output="     1\t+0\n")],
    "grep-label-text": [lambda t: _command(f"git show {t.head_sha}:README | grep -H --label=+0 ''", output="+0:x\n")],
    "filter-by-path": _diff(tail=" | /tmp/cat"),
    "newline-arg-in-error": [lambda t: _command(
        f"git show {t.head_sha}:'x\n+0\n' | cat", output=f"fatal: path 'x\n+0\n' does not exist in '{t.head_sha}'\n")],
    "command-substitution-stderr": [lambda t: _command(
        f"H=$(echo +0 >&2); git diff {t.merge_base_sha} {t.head_sha} -- nope", output="+0\n")],
    "export-external-diff-prints": [lambda t: _command(
        f"export GIT_EXTERNAL_DIFF=/tmp/x.sh; git diff {t.merge_base_sha} {t.head_sha}", output="+0\n")],
    "path-assignment": [lambda t: _command(f"PATH=/tmp; git diff {t.merge_base_sha} {t.head_sha}")],
    "git-by-path": [lambda t: _command(f"/tmp/git diff {t.merge_base_sha} {t.head_sha}")],
    "cd-elsewhere": [lambda t: _command(f"cd /tmp/clone && git diff {t.merge_base_sha}")],
    "export-prints": [lambda t: _command(f"export -p; git diff {t.merge_base_sha} {t.head_sha}")],
    # 原先算读取、现在不算：git 之外还有段（真实日志里有这些形式，见 PR 正文的重放）
    "skill-then-diff": [lambda t: _command(
        f"cat /review/.agents/skills/code-review/SKILL.md && git diff --no-ext-diff --no-textconv {t.merge_base_sha} {t.head_sha}")],
    "stat-then-diff": [lambda t: _command(
        f"git diff --stat {t.merge_base_sha} {t.head_sha} && git diff {t.merge_base_sha} {t.head_sha} -- changed-0")],
    "file-then-read": _diff(tail=" > /tmp/p.diff; wc -l /tmp/p.diff; sed -n 1,200p /tmp/p.diff"),
    "file-read-by-heredoc": [lambda t: _command(
        f"git show {t.head_sha}:changed-0 > /tmp/r.md; python3 - <<'EOF'\nprint(open('/tmp/r.md').read())\nEOF",
        output="0\n")],
    "for-loop-show": [lambda t: _command(f"H={t.head_sha}; for f in changed-0 changed-1; do git show $H:$f | nl -ba; done",
                                         output="     1\t0\n     1\t1\n")],
    "and-then-true": _diff(tail=" && true"),
    # #1969 正式审查（01a6038a）opus BLOCK：`$'…'` 解码出换行、U+2028 被 splitlines 切开，git 报错里的参数成了一行证据
    "ansi-c-quote-newline": [lambda t: _command(
        f"git show {t.head_sha}:$'x\\n+0\\n' | cat", output=f"fatal: path 'x\n+0\n' does not exist in '{t.head_sha}'\n")],
    "locale-quote-path": [lambda t: _command(f'git show {t.head_sha}:$"changed-0"')],
    "u2028-in-single-quotes": [lambda t: _command(
        f"git show {t.head_sha}:'x\u2028+0\u2028' | cat",
        output=f"fatal: path 'x\u2028+0\u2028' does not exist in '{t.head_sha}'\n")],
    "u2029-in-output-only": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} -- nope", output="x\u2029+0\n")],
    # 同一轮 kimi BLOCK：git 自己印出审查员写的文字、外部 diff 被后面的 --ext-diff 重新打开、grep 输出的不是 git 的行
    "show-format-text": [lambda t: _command(f"git show --format='+0' {t.head_sha} -- nope", output="+0\n")],
    "show-pretty-format-text": [lambda t: _command(f"git show --pretty=tformat:+0 {t.head_sha} -- nope", output="+0\n")],
    "show-line-prefix": [lambda t: _command(f"git show --line-prefix=+0 {t.head_sha} -- nope", output="+0\n")],
    "config-format-pretty": [lambda t: _command(f"git -c format.pretty=format:+0 show {t.head_sha} -- nope", output="+0\n")],
    "ext-diff-reenabled": [lambda t: _command(
        f"git -c diff.external='printf +0' diff --no-ext-diff --ext-diff {t.merge_base_sha} {t.head_sha}", output="+0\n")],
    "config-textconv": [lambda t: _command(
        f"git -c diff.lfs.textconv='printf +0' diff {t.merge_base_sha} {t.head_sha}", output="+0\n")],
    "grep-count": [lambda t: _command(f"git diff {t.merge_base_sha} {t.head_sha} -- nope | grep -c . | cat", output="0\n")],
    "grep-only-matching": [lambda t: _command(
        f"git show {t.head_sha}:'x+0' 2>&1 | grep -o '+0'", output="+0\n")],
    # PR #2018 run 45a4c22b：整个 PR 的 diff 之后接只印提交元数据的 git 段可以算，证据只在开头那段 diff 里找
    "diff-empty-then-show-metadata": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} -- nope; git show --no-patch --format='%H%n%an%n%B' {t.head_sha}",
        output=_meta(t))],
    "diff-failed-then-show-metadata": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha}; git show --no-patch --format='%H%n%B' {t.head_sha}",
        output=f"fatal: unable to read {t.head_sha}\n{_meta(t)}{LANE_PATCH}")],
    # #2022 kimi BLOCK：pathspec 让 diff 什么都不印，提交说明写成补丁的样子就成了「开头那段 diff」
    "kimi-pathspec-then-patch-shaped-body": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} -- nope; git show --no-patch --format=%B {t.head_sha}",
        output=LANE_PATCH)],
    # #2022 第二轮 kimi BLOCK：前一段 diff 悄悄失败（全局选项指错仓库、报错被丢），开头就成了 `%B` 的输出
    "kimi-git-dir-stderr-dropped-then-show": [lambda t: _command(
        f"git --git-dir=/nonexistent diff {t.merge_base_sha} {t.head_sha} 2>/dev/null; "
        f"git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    "diff-stderr-dropped-then-show": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} 2>/dev/null; git show -s --format=%B {t.head_sha}",
        output=LANE_PATCH)],
    "diff-elsewhere-then-show": [lambda t: _command(
        f"git -C /tmp diff {t.merge_base_sha} {t.head_sha}; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    "diff-work-tree-then-show": [lambda t: _command(
        f"git --work-tree=/tmp diff {t.merge_base_sha}; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    "diff-stderr-merged-then-show": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} 2>&1; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    # #2022 第三轮 opus BLOCK：只有「左 merge-base、右 head」才是整份补丁；别的形状在复合形式里不算
    **{f"compound-{name}": [lambda t, rev=rev: _command(
        f"git diff {rev(t)}; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)] for name, rev in {
        "reversed": lambda t: f"{t.head_sha} {t.merge_base_sha}",
        "HEAD-triple-dot": lambda t: "HEAD...",
        "at-triple-dot": lambda t: "@...",
        "triple-dot-mb": lambda t: f"...{t.merge_base_sha}",
    }.items()},
    "diff-option-then-show": [lambda t: _command(
        f"git diff -R {t.merge_base_sha} {t.head_sha}; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    "diff-parent-then-show": [lambda t: _command(
        f"git diff {t.head_sha}~1 {t.head_sha}; git show -s --format=%B {t.head_sha}", output=LANE_PATCH)],
    # #2022 opus BLOCK：后一段按黑名单放行时未知选项默认通过；下面这些在整个 PR 的 diff 之后也一律不认
    "opus-log-binary": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha}; git log --format= --binary {t.merge_base_sha}", output=LANE_PATCH)],
    "opus-show-linear-break": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha}; git log -s --format=%H --show-linear-break=+0 {t.head_sha}",
        output=LANE_PATCH)],
    **{f"trailing-{name}": [lambda t, tail=tail: _command(
        f"git diff {t.merge_base_sha} {t.head_sha}; git {tail.format(h=t.head_sha, b=t.merge_base_sha)}",
        output=LANE_PATCH)] for name, tail in {
        "format-literal-text": "show -s --format='diff --git a/changed-0 b/changed-0' {h}",
        "format-hex-char": "show -s --format=%x2b0 {h}",
        "date-format-text": "log -1 -s --format=%ad --date=format:+0 {h}",
        "show-blob": "show --no-patch --format=%H {h}:changed-0",
        "unknown-object": "show --no-patch --format=%H " + "e" * 40,
        "ancestor": "show --no-patch --format=%B {h}~1",
        "range": "log -s --format=%B {b}..{h}",
        "log-patch": "log -p -s --format=%B {h}",
        "show-cc": "show --no-patch --cc --format=%B {h}",
        "stat": "show --stat --format=%B {h}",
        "name-only": "show -s --name-only --format=%B {h}",
        "count": "log -1 -s --format=%B {h}",
        "config": "-c format.pretty=format:+0 show -s --format=%B {h}",
        "no-quiet": "show --format=%B {h}",
        "no-format": "show -s {h}",
        "two-formats": "show -s --format=%H --format=%B {h}",
        "named-pretty": "show -s --pretty=fuller {h}",
        "redirected-in": "log -s --format=%B --stdin </tmp/revs",
        "piped": "show -s --format=%B {h} | head",
        "then-echo": "show -s --format=%B {h}; echo +0",
    }.items()},
    "diff-or-show": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} || git show --no-patch --format=%B {t.head_sha}", output=_meta(t))],
    "piped-diff-then-show": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} | cat; git show --no-patch --format=%B {t.head_sha}",
        output=LANE_PATCH)],
    "show-blob-then-log": [lambda t: _command(
        f"git show {t.head_sha}:changed-0; git log -1 --format=%B {t.head_sha}", output="0\n")],
    "diff-and-log-range-piped": [lambda t: _command(
        f"git diff {t.merge_base_sha} {t.head_sha} && git log --format='%H %s' --date=iso "
        f"{t.merge_base_sha}..{t.head_sha} 2>&1 | head -40", output=LANE_PATCH + _meta(t))],
}
PATCH_READ = {
    "range": [lambda t: _command(f"cd /review && git diff --no-ext-diff --no-textconv {t.merge_base_sha} {t.head_sha} | head")],
    "dotdot": [lambda t: _command(f"git -C /review diff {t.merge_base_sha[:7]}..{t.head_sha[:7]}")],
    "show-file": [lambda t: _command("echo hi", output="hi\n"),
                  lambda t: _command(f"git --no-pager show {t.head_sha[:8]}:changed-0", output="0")],
    "var-assign": [lambda t: _command(f"B={t.merge_base_sha}; H={t.head_sha}; git diff $B $H")],
    "var-export-quoted-show": [lambda t: _command(f'export H={t.head_sha} && git show "$H":changed-1', output="1")],
    "var-braces": [lambda t: _command(f"B={t.merge_base_sha}; H={t.head_sha}; git diff ${{B}} ${{H}}")],
    "var-last-assignment-wins": [lambda t: _command(f"H={FAKE}; H={t.head_sha}; git diff {t.merge_base_sha} $H")],
    # 真实审查日志里的形式（opus、kimi、gpt-6.1-sol，166 位审查员 6512 条命令）
    "merge-base-vs-clean-worktree": [lambda t: _command(f"git diff {t.merge_base_sha}")],
    "merge-base-HEAD": [lambda t: _command(f"git diff {t.merge_base_sha} HEAD")],
    "merge-base-dotdot-HEAD": [lambda t: _command(f"cd /review && B={t.merge_base_sha}; git diff $B..HEAD -- changed-0")],
    "triple-dot": [lambda t: _command(f"git diff {t.merge_base_sha}...{t.head_sha}")],
    "show-HEAD-file": [lambda t: _command("cd /review && git show HEAD:changed-0 | sed -n 1,60p", output="0\n")],
    "show-file-dot-slash": [lambda t: _command("git show HEAD:./changed-1", output="1\n")],
    "show-two-changed-files": [lambda t: _command(f"git show {t.head_sha}:changed-0 {t.head_sha}:changed-1",
                                                  output="0\n1\n")],
    "diff-parent-attributed": [lambda t: _command(f"git diff {t.head_sha}~1 {t.head_sha} | nl -ba")],
    "triple-dot-base": [lambda t: _command(f"git diff {t.base_sha}...{t.head_sha} | grep -n -e 1")],
    "show-file-numbered": [lambda t: _command(f"git show {t.head_sha}:changed-1 | nl -ba | sed -n '1,200p'",
                                              output="     1\t1\n")],
    "show-commit-oneline": [lambda t: _command(f"git show --oneline {t.head_sha}")],
    "show-range": [lambda t: _command(f"git show {t.merge_base_sha}..{t.head_sha}")],
    "git-P": [lambda t: _command(f"git -P diff {t.merge_base_sha} {t.head_sha}")],
    "env-and-global-options": [lambda t: _command(
        f"GIT_PAGER=cat git --no-pager -c core.quotepath=false --git-dir=/review/.git --work-tree /review "
        f"diff {t.merge_base_sha} {t.head_sha}")],
    "stat-then-patch": _diff("--stat -p"),
    "show-named-pretty": [lambda t: _command(f"git show --pretty=fuller {t.head_sha}")],
    "hooks-path-config": [lambda t: _command(
        f"git -c core.hooksPath=/dev/null diff --no-ext-diff --no-textconv {t.merge_base_sha} {t.head_sha}")],
    "dollar-at-end-of-double-quotes": [lambda t: _command(
        f'git show {t.head_sha}:changed-0 | grep -n -B2 "^0$" | grep -v "^--$"', output="1:0\n")],
    "command-in-variable": [lambda t: _command(
        f'cd /review && D="git diff --no-ext-diff --no-textconv {t.merge_base_sha} {t.head_sha}"; $D -- changed-0')],
    "stderr-dropped": _diff(tail=" 2>/dev/null"),
    "stderr-merged-piped": _diff(tail=" 2>&1 | head -200"),
    "filter-chain": [lambda t: _command(
        f"cd /review && B={t.merge_base_sha}; export H={t.head_sha}; git diff --no-ext-diff $B $H 2>&1 "
        "| nl -ba | grep -n -v -e zzz | sed -n '1,400p' | head -n 400 | tail -n +1 | cat -n")],
    # PR #2018 run 45a4c22b opus 的原样命令（之前 13 条同形读取都被判未读，见 PR 正文的重放）
    "diff-then-show-metadata": [lambda t: _command(
        f"cd /review && git diff --no-ext-diff --no-textconv {t.merge_base_sha} {t.head_sha}; "
        f"git show --no-patch --format='%H%n%an%n%B' {t.head_sha}", output=LANE_PATCH + _meta(t))],
    "diff-and-show-short-sha": [lambda t: _command(
        f"git diff --no-color -U5 {t.merge_base_sha} {t.head_sha} && git log -s --pretty=tformat:'%h %an %s' "
        f"{t.head_sha[:8]}", output=LANE_PATCH + _meta(t))],
}


def test_frozen_patch_evidence_is_its_distinct_changed_lines():
    diff = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,2 @@\n"
            "-    old_value = compute_old()\n+    new_value = compute_new()\n+}\n")
    patch = FrozenPatch.from_diff("a" * 40, "b" * 40, "", diff)
    assert patch.evidence == {"old_value = compute_old()", "new_value = compute_new()"}
    assert patch.shown_in("+    new_value = compute_new()\n")
    assert patch.shown_in("    12\t    new_value = compute_new()\n")  # git show <head>:f.py | nl -ba
    assert not patch.shown_in("}\n")
    assert not patch.shown_in("diff --git a/f.py b/f.py\n@@ -1,2 +1,2 @@\n+X /tmp/git-blob-ksCWK9/f.py\n")  # textconv
    assert not patch.shown_in("fatal: path 'x\u2028+    new_value = compute_new()\u2028' does not exist\n")
    assert patch.shown_in("+    new_value = compute_new()\r\n")
    binary = FrozenPatch.from_diff("a" * 40, "b" * 40, "", "diff --git a/p.png b/p.png\nBinary files a/p.png and b/p.png differ\n")
    assert binary.shown_in("diff --git a/p.png b/p.png\n") and not binary.shown_in("")


# \u771f\u5b9e\u5f62\u72b6\uff1a\u672c PR \u65b0\u589e\u4e00\u4e2a Python \u6a21\u5757\uff0c\u9996\u884c\u662f\u5230\u5904\u90fd\u6709\u7684 `from __future__ import annotations`
COMMON_LINE_DIFF = (
    "diff --git a/pkg/new_gate.py b/pkg/new_gate.py\nnew file mode 100644\nindex 0000000..1111111\n"
    "--- /dev/null\n+++ b/pkg/new_gate.py\n@@ -0,0 +1,3 @@\n+from __future__ import annotations\n+\n"
    "+def gate_reads_the_patch() -> bool:\n"
    "diff --git a/pkg/old.py b/pkg/old.py\nindex 2222222..3333333 100644\n--- a/pkg/old.py\n+++ b/pkg/old.py\n"
    "@@ -4 +3,0 @@\n-    removed_only_line = 1\n"
    "diff --git \"a/pkg/\\303\\244 x.py\" \"b/pkg/\\303\\244 x.py\"\n--- \"a/pkg/\\303\\244 x.py\"\n"
    "+++ \"b/pkg/\\303\\244 x.py\"\n@@ -1 +1 @@\n-+++ looks like a header\n+++++ also looks like one\n")
UNCHANGED_MODULE = "from __future__ import annotations\n\nfrom pathlib import Path\n\ndef unrelated() -> None:\n"


def test_common_line_in_unchanged_file_is_not_a_patch_read():
    """#1969 \u6b63\u5f0f\u5ba1\u67e5\uff08bb8aa92e\uff09opus BLOCK \u7684\u8d1f\u5bf9\u7167\uff1a`git show <head>:<\u672c PR \u6ca1\u6539\u7684\u6587\u4ef6>` \u7684\u8f93\u51fa\u91cc\u6709\u4e0e\u6539\u52a8\u884c
    \u76f8\u540c\u7684\u901a\u7528\u884c\uff0c\u4e0d\u7b97\u8bfb\u53d6\uff1b\u540c\u4e00\u884c\u51fa\u81ea\u6539\u52a8\u6587\u4ef6\u624d\u7b97\u3002\u65e7 head \u4e0a\u8fd9\u91cc\u7684\u7b2c\u4e00\u6761\u65ad\u8a00\u4e0d\u6210\u7acb\u3002"""
    head, merge_base = "a" * 40, "b" * 40
    patch = FrozenPatch.from_diff(head, merge_base, "", COMMON_LINE_DIFF)
    assert "from __future__ import annotations" in patch.evidence
    assert not reads_candidate_patch(f"/bin/bash -lc 'git show {head}:pkg/approval.py'", UNCHANGED_MODULE, patch)
    assert not reads_candidate_patch("/bin/bash -lc 'git show HEAD:pkg/approval.py | nl -ba'",
                                     "     1\tfrom __future__ import annotations\n", patch)
    assert reads_candidate_patch(f"/bin/bash -lc 'git show {head}:pkg/new_gate.py'", UNCHANGED_MODULE, patch)
    # \u53ea\u5220\u4e86\u884c\u7684\u6587\u4ef6\uff0chead \u4e0a\u7684\u5185\u5bb9\u91cc\u6ca1\u6709\u5b83\u7684\u6539\u52a8
    assert not reads_candidate_patch(f"/bin/bash -lc 'git show {head}:pkg/old.py'",
                                     "    removed_only_line = 1\n", patch)
    # \u52a0\u5f15\u53f7\u7684\u8def\u5f84\u3001\u5185\u5bb9\u5f62\u5982 `+++ ` \u7684\u6539\u52a8\u884c\u90fd\u6309\u6587\u4ef6\u5f52\u5c5e
    assert reads_candidate_patch(f"/bin/bash -lc 'git show {head}:\"pkg/\u00e4 x.py\"'", "++++ also looks like one\n", patch)
    assert patch.files[2].evidence == {"+++ looks like a header", "++++ also looks like one"}
    # diff \u4e24\u7aef\u4e0d\u662f merge-base \u4e0e head \u65f6\uff0c\u8f93\u51fa\u53ef\u80fd\u542b\u672c PR \u6ca1\u6539\u7684\u6587\u4ef6\uff1a\u53ea\u8ba4\u51bb\u7ed3\u6587\u4ef6\u5934\u4e4b\u540e\u7684\u884c
    other = "diff --git a/pkg/approval.py b/pkg/approval.py\n@@ -0,0 +1 @@\n+from __future__ import annotations\n"
    assert not reads_candidate_patch(f"/bin/bash -lc 'git diff {head}~1 {head}'", other, patch)
    mine = "diff --git a/pkg/new_gate.py b/pkg/new_gate.py\n@@ -0,0 +1 @@\n+from __future__ import annotations\n"
    assert reads_candidate_patch(f"/bin/bash -lc 'git diff {head}~1 {head}'", other + mine, patch)
    # merge-base..head \u7684\u8f93\u51fa\u5168\u51fa\u81ea\u51bb\u7ed3\u8865\u4e01\uff08\u4e0a\u4e0b\u6587\u884c\u4e5f\u662f\u6539\u52a8\u6587\u4ef6\u7684\u5185\u5bb9\uff09
    assert reads_candidate_patch(f"/bin/bash -lc 'git diff {merge_base} {head} | grep -n annotations'",
                                 "7:+from __future__ import annotations\n", patch)


# PR #2018 run 45a4c22b a1：opus 的读取被判未读、两个 PASS 整轮记 error。冻结补丁与输出取自真实日志（截短）
PR2018_HEAD, PR2018_MB = "0b07c6b0" * 5, "83c4d9c9" * 5  # 真实 SHA 的前缀；整串 40 位十六进制会被 DevSkim DS173237 当成密钥
PR2018_CHANGED = "  #   rust-test-production-session    生产入口测试 + backtest_bin feature 的库测试（#1875 合并）"
PR2018_FROZEN = (
    "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\nindex 1992713934..cd7c2277d1 100644\n"
    "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -228 +228 @@ jobs:\n"
    "-  #   rust-test-backtest-bin          backtest_bin feature 的库测试\n"
    f"+{PR2018_CHANGED}\n")
PR2018_COMMAND = (f"/bin/bash -lc \"cd /review && git diff --no-ext-diff --no-textconv {PR2018_MB} {PR2018_HEAD}; "
                  f"git show --no-patch --format='%H%n%an%n%B' {PR2018_HEAD}\"")
PR2018_DIFF = (
    "diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml\nindex 1992713..cd7c227 100644\n"
    "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n@@ -226,3 +226,3 @@ jobs:\n"
    "   #   rust-test-s-session-extras (组) s_session 的 TB-02-C、库/集成测试、TestOnly 特性增量、v3 history（矩阵作业\n"
    "   #                                   rust-test-s-session-extra-groups，结论由 ci-ok 直接判定）\n"
    "-  #   rust-test-backtest-bin          backtest_bin feature 的库测试\n"
    f"+{PR2018_CHANGED}\n")
# 提交说明原样引用了改动行：diff 没印出东西时，这一行只出现在 git show 的输出里
PR2018_SHOW = f"{PR2018_HEAD}\nSmoke\nci(#1875): rust-test-backtest-bin 并入 rust-test-production-session\n\n{PR2018_CHANGED}\n"


def test_diff_then_commit_metadata_reads_patch_from_diff_segment_only():
    """`git diff <mb> <head>; git show --no-patch --format=… <head>`：输出是两段按序拼接，证据只认开头那段 diff。"""
    patch = FrozenPatch.from_diff(PR2018_HEAD, PR2018_MB, PR2018_MB, PR2018_FROZEN)
    assert reads_candidate_patch(PR2018_COMMAND, PR2018_DIFF + PR2018_SHOW, patch)
    # 只有第二段跑出了东西（diff 报错或没印内容，`;` 让整条命令照样 exit 0）：提交说明里的改动行不算读到补丁
    assert not reads_candidate_patch(PR2018_COMMAND, PR2018_SHOW, patch)
    assert not reads_candidate_patch(PR2018_COMMAND, f"fatal: bad object {PR2018_HEAD}\n{PR2018_SHOW}", patch)
    only_show = f"/bin/bash -lc \"cd /review && git show --no-patch --format='%H%n%an%n%B' {PR2018_HEAD}\""
    assert not reads_candidate_patch(only_show, PR2018_DIFF + PR2018_SHOW, patch)
    # #2022 kimi BLOCK：带 pathspec 的 diff 可以什么都不印，提交说明里写成补丁样子的文字就会排在开头
    kimi = (f"/bin/bash -lc \"git diff {PR2018_MB} {PR2018_HEAD} -- nope; "
            f"git show --no-patch --format=%B {PR2018_HEAD}\"")
    assert not reads_candidate_patch(kimi, PR2018_DIFF, patch)
    # #2022 opus BLOCK：`--binary` 隐含 `--patch`，`--show-linear-break` 印审查员写的文字；后一段只认白名单
    for tail in (f"git log --format= --binary {PR2018_MB}",
                 f"git log -s --format=%H --show-linear-break=+x {PR2018_HEAD}"):
        command = f"/bin/bash -lc \"git diff {PR2018_MB} {PR2018_HEAD}; {tail}\""
        assert not reads_candidate_patch(command, PR2018_DIFF, patch)
    # #2022 第二轮 kimi BLOCK：diff 指错仓库、报错丢进 /dev/null，开头只剩 `%B`（这里让提交说明长成补丁的样子）
    for leading in (f"git --git-dir=/nonexistent diff {PR2018_MB} {PR2018_HEAD} 2>/dev/null",
                    f"git diff {PR2018_MB} {PR2018_HEAD} 2>/dev/null", f"git -C /tmp diff {PR2018_MB} {PR2018_HEAD}"):
        command = f"/bin/bash -lc \"{leading}; git show -s --format=%B {PR2018_HEAD}\""
        assert not reads_candidate_patch(command, PR2018_DIFF, patch)
    allowed_config = (f"/bin/bash -lc \"git -c core.quotepath=false diff {PR2018_MB} {PR2018_HEAD}; "
                      f"git show -s --format=%B {PR2018_HEAD}\"")
    assert reads_candidate_patch(allowed_config, PR2018_DIFF + PR2018_SHOW, patch)
    # 没有后一段时照旧按整段输出判
    alone = f"/bin/bash -lc 'git diff --no-ext-diff --no-textconv {PR2018_MB} {PR2018_HEAD}'"
    assert reads_candidate_patch(alone, PR2018_DIFF, patch)


@pytest.mark.parametrize("shape", ["reversed", "HEAD...", "@...", "...mb"])
def test_only_merge_base_left_head_right_is_whole_patch(shape):
    """#2022 第三轮 opus BLOCK：反向、`HEAD...`、`@...`、`...<mb>` 不是整份冻结补丁的读取，复合形式里也不算。"""
    rev = {"reversed": f"{PR2018_HEAD} {PR2018_MB}", "HEAD...": "HEAD...", "@...": "@...", "...mb": f"...{PR2018_MB}"}[shape]
    assert patch_read._patch_read(f"/bin/bash -lc 'git diff {rev}'", PR2018_HEAD, PR2018_MB, PR2018_MB) != WHOLE_PATCH
    patch = FrozenPatch.from_diff(PR2018_HEAD, PR2018_MB, PR2018_MB, PR2018_FROZEN)
    command = f"/bin/bash -lc \"git diff {rev}; git show -s --format=%B {PR2018_HEAD}\""
    assert not reads_candidate_patch(command, PR2018_DIFF, patch)


@pytest.mark.parametrize("rev", [f"{PR2018_MB} {PR2018_HEAD}", PR2018_MB, f"{PR2018_MB}..{PR2018_HEAD}",
                                 f"{PR2018_MB}...{PR2018_HEAD}", f"{PR2018_MB[:8]}..HEAD"])
def test_merge_base_left_head_right_is_whole_patch(rev):
    assert patch_read._patch_read(f"/bin/bash -lc 'git diff {rev}'", PR2018_HEAD, PR2018_MB, PR2018_MB) == WHOLE_PATCH
    patch = FrozenPatch.from_diff(PR2018_HEAD, PR2018_MB, PR2018_MB, PR2018_FROZEN)
    command = f"/bin/bash -lc \"git diff {rev}; git show -s --format=%B {PR2018_HEAD}\""
    assert reads_candidate_patch(command, PR2018_DIFF + PR2018_SHOW, patch)


def test_unreadable_frozen_patch_is_failed_not_raised(lane, monkeypatch):
    """#1969 正式审查（bb8aa92e）opus 非阻断项：来源对象库取不出冻结补丁时记 FAILED，不把 git 的异常抛出去。"""
    target = ReviewTarget(**lane.review_pr(1810)["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[0]
    launch, receipt = json.loads((folder / "launch.json").read_text()), json.loads((folder / "receipt.json").read_text())
    assert validate_review(target, launch, receipt, folder, lane.source).verdict == "PASS"
    def missing(*_):
        raise subprocess.CalledProcessError(128, ["git", "diff"])
    monkeypatch.setattr(module, "frozen_patch", missing)
    outcome = validate_review(target, launch, receipt, folder, lane.source)
    assert outcome.verdict == "FAILED" and "取不出冻结候选补丁" in outcome.reason


@pytest.mark.parametrize("claim", ["PASS", "BLOCK"])
def test_conclusion_without_frozen_patch_read_is_failed(lane, claim):
    """#1968/#1969：跑过命令但没有让 git 把冻结候选补丁输出到日志的，PASS、BLOCK 都不采信。"""
    outcomes = _verdicts_with_commands(lane, claim, NOT_A_PATCH_READ)
    assert {case: o.verdict for case, o in outcomes.items()
            if o.verdict != "FAILED" or "未读取冻结候选补丁" not in (o.reason or "")} == {}


@pytest.mark.parametrize("claim", ["PASS", "BLOCK"])
def test_conclusion_after_frozen_patch_read_stands(lane, claim):
    outcomes = _verdicts_with_commands(lane, claim, PATCH_READ)
    assert {case: o.reason for case, o in outcomes.items() if o.verdict != claim} == {}


def test_zero_tool_pass_is_never_reused(lane, env):
    _modes(lane, **{model: "PASS:notool" for model in MODELS})
    assert lane.review_pr(1810)["state"] == "error"
    _clear_modes(lane)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and "reused_from" not in result
    assert _launches(lane) == 2 * len(MODELS)
    assert lane.gateway.sent == ["pending", "error", "pending", "success"]


@pytest.mark.parametrize("field", ["POLICY", "REVIEW_CONTRACT"])
def test_policy_or_contract_change_is_not_reused(lane, env, monkeypatch, field):
    lane.review_pr(1810)
    monkeypatch.setattr(module, field, "changed")
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_new_attempt_on_reused_head_is_reviewed_again(lane, env):
    lane.review_pr(1810)
    _advance_main(lane, env)
    assert "reused_from" in lane.review_pr(1810)
    again = lane.review_pr(1810, 2)
    assert "reused_from" not in again and len(again["reviews"]) == len(MODELS)
    assert _launches(lane) == 2 * len(MODELS)


def test_reuse_needs_no_snapshot_space(lane, env, monkeypatch):
    lane.review_pr(1810)
    _advance_main(lane, env)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    assert "reused_from" in lane.review_pr(1810)


def _second_opinion(lane, env, monkeypatch, verdicts, *, stale=False):
    """同一补丁先双 PASS，再在同一 head 上显式重审得到 verdicts（可选让发布时 head 漂移成 STALE），然后追平 main。"""
    first = lane.review_pr(1810)
    real = lane.run_reviewers
    def scripted(target, folder):
        outcomes = [module.ReviewOutcome(m, v, f"s-{m}" if v != "FAILED" else None, f"VERDICT: {v}")
                    for m, v in zip(MODELS, verdicts, strict=True)]
        if stale:
            _advance_main(lane, env)
        return outcomes
    monkeypatch.setattr(lane, "run_reviewers", scripted)
    second = lane.review_pr(1810, 2)
    monkeypatch.setattr(lane, "run_reviewers", real)
    if not stale:
        _advance_main(lane, env)
    return first, second


def test_reviewer_block_hidden_by_failed_run_still_vetoes_reuse(lane, env, monkeypatch):
    _, second = _second_opinion(lane, env, monkeypatch, ["BLOCK", "FAILED"])
    assert second["verdict"] == "FAILED"
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_reviewer_block_hidden_by_stale_run_still_vetoes_reuse(lane, env, monkeypatch):
    _, second = _second_opinion(lane, env, monkeypatch, ["PASS", "BLOCK"], stale=True)
    assert second["verdict"] == "STALE" and [r["verdict"] for r in second["reviews"]] == ["PASS", "BLOCK"]
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_block_on_legacy_run_without_patch_id_still_vetoes_reuse(lane, env, monkeypatch):
    _, second = _second_opinion(lane, env, monkeypatch, ["BLOCK", "BLOCK"])
    path = lane.state_root / "runs" / ReviewTarget(**second["target"]).key / "target.json"
    legacy = json.loads(path.read_text())
    legacy.pop("patch_id"), legacy.pop("review_contract")
    path.write_text(json.dumps(legacy))
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_interrupted_registration_without_target_json_is_still_admitted(lane, monkeypatch):
    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    (folder / "target.json").unlink()  # _lock 已建目录、target.json 未写时中断
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    with pytest.raises(IdentityError, match="未登记 attempt"):
        lane.review_pr(1810)
    assert not (folder / "target.json").exists() and lane.gateway.sent == []


@pytest.mark.parametrize("change", ["controller", "admission-fails", "image"])
def test_reuse_requires_current_deployment_admission(lane, env, change):
    lane.review_pr(1810)
    _advance_main(lane, env)
    if change == "controller":
        git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")
    else:
        (lane.source / ".git" / "fake-admission").write_text("fail" if change == "admission-fails" else "sha256:" + "2" * 64)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_reuse_records_admission(lane, env):
    lane.review_pr(1810)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["reused_from"]["admission"] == {"controller_code_head": git(lane.source, "rev-parse", "HEAD"),
                                                  "image_id": "sha256:" + "1" * 64}



def _interrupt_before_aggregation(lane, monkeypatch):
    """reviewer 全部写完回执后、汇总写 outcome.json 前控制器中断。"""
    real = lane.run_reviewers
    def interrupted(target, folder):
        real(target, folder)
        raise KeyboardInterrupt
    monkeypatch.setattr(lane, "run_reviewers", interrupted)
    return real


def _modes(lane, **by_model):
    runs = lane.state_root / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for model, mode in by_model.items():
        (runs / f"fake-mode-{model}").write_text(mode)


def _clear_modes(lane):
    for p in (lane.state_root / "runs").glob("fake-mode-*"):
        p.unlink()


def test_seq_sol_interrupted_reattempt_with_unaggregated_block_vetoes_reuse(lane, env, monkeypatch):
    """D5 c24b9537 Sol：同补丁双 PASS 后显式重审得 [FAILED, BLOCK]，汇总前中断；新 head 不得沿用。"""
    lane.review_pr(1810)
    _modes(lane, **{MODELS[0]: "failed", MODELS[1]: "BLOCK"})
    real = _interrupt_before_aggregation(lane, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810, 2)
    monkeypatch.setattr(lane, "run_reviewers", real)
    _clear_modes(lane)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_seq_opus_current_run_with_worker_state_never_reuses(lane, env, monkeypatch):
    """D5 c24b9537 Opus-1：本 run 已有 reviewer BLOCK 回执、未汇总即中断，恢复时不得改走沿用。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    (lane.source / ".git" / "fake-admission").write_text("fail")   # 首轮准入抖动 → 全新双审
    _modes(lane, **{MODELS[0]: "BLOCK"})
    real = _interrupt_before_aggregation(lane, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    monkeypatch.setattr(lane, "run_reviewers", real)
    (lane.source / ".git" / "fake-admission").unlink()             # 准入恢复
    result = lane.review_pr(1810)
    assert "reused_from" not in result and result["verdict"] == "BLOCK"


def test_seq_opus_in_flight_reattempt_of_same_patch_vetoes_reuse(lane, env):
    """D5 c24b9537 Opus-2：同补丁显式重审仍在途（无终态），新 head 不得沿用。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    assert "reused_from" in lane.review_pr(1810)
    in_flight = lane.target(1810, 2)
    (lane.state_root / "runs" / in_flight.key / MODELS[0]).mkdir()
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_block_run_with_unknown_patch_vetoes_reuse(lane, env, monkeypatch):
    """补丁身份算不出的 BLOCK run 按同补丁处理（fail closed）。"""
    _, second = _second_opinion(lane, env, monkeypatch, ["BLOCK", "BLOCK"])
    path = lane.state_root / "runs" / ReviewTarget(**second["target"]).key / "target.json"
    legacy = json.loads(path.read_text())
    legacy.pop("patch_id"), legacy.pop("review_contract")
    legacy["head_sha"] = "e" * 40                                   # 冻结 head 已不在对象库
    path.write_text(json.dumps(legacy))
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_block_only_in_events_of_failed_receipt_vetoes_reuse(lane, env):
    """#1912 run 75aad755 的形状：receipt 停在 transcript 失败、result=None，BLOCK 只在 events 的最终消息里。"""
    first = lane.review_pr(1810)
    second = lane.target(1810, 2)
    worker = lane.state_root / "runs" / second.key / MODELS[1]
    worker.mkdir(parents=True)
    (worker / "receipt.json").write_text(json.dumps({"status": "failed", "phase": "transcript", "result": None}))
    message = "```json\n" + json.dumps({"status": "blocked", "summary": "VERDICT: BLOCK\nx"}) + "\n```"
    (worker / "events.jsonl").write_text(json.dumps({"type": "item.completed",
                                                     "item": {"type": "agent_message", "text": message}}) + "\n")
    (lane.state_root / "runs" / second.key / "outcome.json").write_text(json.dumps(
        {"run_id": second.run_id, "verdict": "FAILED", "state": "error", "target": first["target"], "reviews": []}))
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_planned_reuse_falling_back_to_review_runs_total_space_admission(lane, env, monkeypatch):
    lane.review_pr(1810)
    _advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned
    (lane.source / ".git" / "fake-admission").write_text("fail")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))
    sent = list(lane.gateway.sent)
    with pytest.raises(IdentityError, match="共需"):
        lane.review_pr(1810)
    assert lane.gateway.sent == sent  # 没有为本 run 发 pending


def test_ctrl_c_during_concurrent_review_returns_without_waiting_for_receipts(lane, monkeypatch):
    import os
    import signal
    import time as clock
    lane.launcher = [sys.executable, "-c", "import time; time.sleep(120)"]
    calls = []
    real_wait = module.wait
    def interrupted(futures):
        calls.append(1)
        if len(calls) == 1:
            deadline = clock.monotonic() + 30  # 等两位都已派发（有 launch.json），不靠固定 sleep
            while clock.monotonic() < deadline and len(list((lane.state_root / "runs").glob("*/*/launch.json"))) < 2:
                clock.sleep(0.05)
            raise KeyboardInterrupt
        return real_wait(futures)
    monkeypatch.setattr(module, "wait", interrupted)
    started = clock.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            lane.review_pr(1810)
        assert clock.monotonic() - started < 30
        target = ReviewTarget(**json.loads(next((lane.state_root / "runs").glob("*/target.json")).read_text()))
        folder = lane.state_root / "runs" / target.key
        assert all((folder / m / "launch.json").exists() for m in MODELS)  # 已派发，留待收养
        assert not (folder / "outcome.json").exists()
    finally:
        for process in (lane.state_root / "runs").glob("*/*/process.json"):
            os.killpg(json.loads(process.read_text())["pid"], signal.SIGKILL)


def _dispatched_without_receipt(folder, model, run_id):
    worker = folder / model
    worker.mkdir(parents=True, exist_ok=True)
    (worker / "launch.json").write_text(json.dumps({"run_id": run_id, "model": model, "launch_id": "x"}))
    (worker / "process.json").write_text(json.dumps({"pid": 2 ** 22 + 7, "launch_id": "x"}))  # 监督进程已不在


def test_interleave_resume_adopts_dispatched_second_reviewer_after_first_failed(lane, monkeypatch):
    """D5 9842a6d5 Sol：恢复时首位 FAILED、次位已派发未出回执，不得提前聚合；次位须收养到终态再汇总。"""
    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    _modes(lane, **{MODELS[0]: "failed"})
    real = lane.run_review
    def first_only(t, model, f):
        if model == MODELS[1]:
            _dispatched_without_receipt(f, model, t.run_id)
            raise module.EffectPending("模拟：次位已派发，控制器中断")
        return real(t, model, f)
    monkeypatch.setattr(lane, "run_review", first_only)
    with pytest.raises(module.EffectPending):
        lane.review_pr(1810)
    assert not (folder / "outcome.json").exists()
    monkeypatch.setattr(lane, "run_review", real)
    result = lane.review_pr(1810)
    assert [r["model"] for r in result["reviews"]] == list(MODELS)
    assert result["verdict"] == "FAILED" and (folder / MODELS[1] / "receipt.json").exists()


def test_interleave_outcome_with_unfinished_dispatched_reviewer_never_counts_as_settled(lane, env):
    """旧聚合可能在次位仍运行时写出 outcome：这样的 run 不算完结，同补丁新 head 不沿用；次位之后补出 BLOCK 也不沿用。"""
    first = lane.review_pr(1810)
    second = lane.target(1810, 2)
    folder = lane.state_root / "runs" / second.key
    _dispatched_without_receipt(folder, MODELS[1], second.run_id)
    (folder / "outcome.json").write_text(json.dumps({"run_id": second.run_id, "verdict": "FAILED", "state": "error",
        "target": first["target"], "reviews": [{"model": MODELS[0], "verdict": "FAILED"}]}))
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)
    (folder / MODELS[1] / "receipt.json").write_text(json.dumps(
        {"status": "completed", "result": {"status": "blocked", "summary": "VERDICT: BLOCK\n迟到"}}))
    _advance_main(lane, env)
    later = lane.review_pr(1810)
    assert "reused_from" not in later and len(later["reviews"]) == len(MODELS)


def test_prepared_but_never_dispatched_reviewer_does_not_keep_run_unsettled(lane):
    first = lane.review_pr(1810)
    second = lane.target(1810, 2)
    folder = lane.state_root / "runs" / second.key
    (folder / MODELS[0]).mkdir(parents=True)
    (folder / MODELS[0] / "prepare.json").write_text(json.dumps({"run_id": second.run_id}))
    (folder / "outcome.json").write_text(json.dumps({"run_id": second.run_id, "verdict": "FAILED", "state": "error",
        "target": first["target"], "reviews": [{"model": MODELS[0], "verdict": "FAILED"}]}))
    row = next(r for r in lane.status(1810) if r["target"]["run_id"] == second.run_id)
    assert lane._settled(row)  # 未派发的 prepare 不让 run 永远处于未完结
    _dispatched_without_receipt(folder, MODELS[1], second.run_id)
    assert not lane._settled(next(r for r in lane.status(1810) if r["target"]["run_id"] == second.run_id))


@pytest.mark.parametrize("ending", ["FAILED", "STALE"])
def test_superseding_reattempt_without_block_keeps_old_pass_from_reviving(lane, env, monkeypatch, ending):
    """D5 d47722cf Opus：同补丁显式重审以 FAILED/STALE 收场且无 BLOCK，更早的 PASS 不得在追平后复活。"""
    _, second = _second_opinion(lane, env, monkeypatch, ["FAILED", "FAILED"] if ending == "FAILED" else ["PASS", "PASS"],
                                stale=ending == "STALE")
    assert second["verdict"] == ending
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_unreadable_evidence_vetoes_reuse_without_blocking_registration(lane, env):
    """_read 对权限、属主不符抛 IdentityError：按 BLOCK 处理（不沿用），但不能让登记失败。"""
    first = lane.review_pr(1810)
    other = lane.target(1810, 2)
    worker = lane.state_root / "runs" / other.key / MODELS[0]
    worker.mkdir(parents=True)
    (worker / "receipt.json").write_text("{}")
    (worker / "receipt.json").chmod(0o666)  # 组/他人可写：_read 抛 IdentityError
    (lane.state_root / "runs" / other.key / "outcome.json").write_text(json.dumps(
        {"run_id": other.run_id, "verdict": "PASS", "state": "success", "target": first["target"], "reviews": []}))
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_serial_resume_after_interrupt_is_not_stuck_on_stale_stop_flag(lane):
    target = lane.target(1810, 1)
    (lane.state_root / "runs" / target.key / MODELS[0]).mkdir()  # 走串行恢复
    lane._stop.set()                                                # 同一实例上一次被 Ctrl-C
    assert lane.review_pr(1810)["verdict"] == "PASS"


def test_race_superseding_registration_during_reuse_admission_blocks_reuse(lane, env, monkeypatch):
    """D5 f19adb21 Sol P1：H2 读完历史、等部署准入时，另一进程登记同补丁 H1 attempt2 并以 STALE 收场；H2 不得发布沿用。"""
    lane.review_pr(1810)
    h1 = lane.gateway.pr["head"]["sha"]
    _advance_main(lane, env)
    h2 = lane.gateway.pr["head"]["sha"]
    real = lane.reuse_admission
    calls = []
    def racing(target, source):
        calls.append(1)
        if len(calls) == 1:                           # 登记时那次判定不插入；竞态窗口在派发阶段读完历史之后
            return real(target, source)
        lane.gateway.pr["head"]["sha"] = h1           # 另一进程眼中的 PR 仍在 H1
        late = lane.target(1810, 2)
        lane.gateway.pr["head"]["sha"] = h2
        folder = lane.state_root / "runs" / late.key
        (folder / "outcome.json").write_text(json.dumps({"run_id": late.run_id, "verdict": "STALE",
                                                          "target": asdict(late), "reviews": []}))
        (folder / "outcome.json").chmod(0o600)
        return real(target, source)
    monkeypatch.setattr(lane, "reuse_admission", racing)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_pass_message_quoting_block_is_not_block_evidence(lane, env):
    """D5 f19adb21 Sol P2：合法 PASS 在说明里提到 VERDICT: BLOCK，不得被当成 BLOCK 证据。"""
    first = lane.review_pr(1810)
    worker = lane.state_root / "runs" / ReviewTarget(**first["target"]).key / MODELS[0]
    text = json.dumps({"status": "completed", "summary": "VERDICT: PASS\n未发现会导致 VERDICT: BLOCK 的问题",
                       "findings": [], "validation": ["检查过 VERDICT: BLOCK 的触发条件"]})
    (worker / "events.jsonl").write_text(json.dumps({"type": "item.completed",
                                                     "item": {"type": "agent_message", "text": text}}) + "\n")
    _advance_main(lane, env)
    assert lane.review_pr(1810)["reused_from"]["run_id"] == first["run_id"]


@pytest.mark.parametrize("damage", ["json", "mode"])
def test_damaged_history_outcome_vetoes_reuse_but_registration_proceeds(lane, env, damage):
    """D5 f19adb21 Sol P2：status() 读到损坏的历史 outcome 时退回双审，不让登记失败。"""
    first = lane.review_pr(1810)
    outcome = lane.state_root / "runs" / ReviewTarget(**first["target"]).key / "outcome.json"
    if damage == "json":
        outcome.write_text("{broken")
    else:
        outcome.chmod(0o666)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)


def test_registration_waits_for_inflight_reuse_publication(lane, env, monkeypatch):
    """并发合同：沿用从重读历史到发布 success 持有 PR 锁；期间另一实例的同 PR 登记必须等到发布之后。"""
    import threading
    import time as clock
    lane.review_pr(1810)
    h1 = lane.gateway.pr["head"]["sha"]
    _advance_main(lane, env)
    other_gateway = copy.copy(lane.gateway)
    other_gateway.pr = copy.deepcopy(lane.gateway.pr)
    other_gateway.pr["head"]["sha"] = h1
    other = ExternalReview(other_gateway, source=lane.source, state_root=lane.state_root,
                           checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01)
    registered = {}
    def register():
        registered["target"] = other.target(1810, 2)
        registered["at"] = clock.monotonic()
    real = lane._publish_reuse
    def publishing(*args):
        thread = threading.Thread(target=register)
        thread.start()
        clock.sleep(0.5)
        assert "at" not in registered, "持 PR 锁期间另一实例完成了登记"
        result = real(*args)
        registered["published"] = clock.monotonic()
        publishing.thread = thread
        return result
    monkeypatch.setattr(lane, "_publish_reuse", publishing)
    result = lane.review_pr(1810)
    publishing.thread.join(30)
    assert "reused_from" in result and registered["at"] >= registered["published"] - 0.05

def _auth_broken(lane, monkeypatch, broken):
    real = lane.gateway.get_pr
    def get_pr(number):
        if broken["on"]:
            raise IdentityError("GitHub 返回 HTTP 401，未切换凭据来源")
        return real(number)
    monkeypatch.setattr(lane.gateway, "get_pr", get_pr)


def test_auth_failure_before_final_publish_is_pending_not_stale(lane, monkeypatch):
    """#1938 run 63919f86：双 PASS 后发布前预检 401，不得记 STALE；认证恢复后同 attempt 重跑补发，不重跑模型。"""
    broken = {"on": False}
    _auth_broken(lane, monkeypatch, broken)
    real_publish = module.StatusPublisher.publish
    def publish(self, state, *args):
        if state == "success" and not broken.get("done"):
            broken["on"] = broken["done"] = True  # 只在第一次发布 success 前断开认证
        return real_publish(self, state, *args)
    monkeypatch.setattr(module.StatusPublisher, "publish", publish)
    with pytest.raises(EffectPending, match="未判定漂移"):
        lane.review_pr(1810)
    target = ReviewTarget(**json.loads(next((lane.state_root / "runs").glob("*/target.json")).read_text()))
    saved = json.loads((lane.state_root / "runs" / target.key / "outcome.json").read_text())
    assert saved["verdict"] == "PASS" and "publication" not in saved
    broken["on"] = False
    launches = (lane.state_root / "runs" / "launches").read_text()
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["publication"]["state"] == "success"
    assert (lane.state_root / "runs" / "launches").read_text() == launches  # 没有重跑模型
    assert lane.gateway.sent[-1] == "success"


def _legacy_auth_stale(lane):
    """构造旧版本留下的形状：双审完整，发布前 401 被记为 STALE，只发过 pending。"""
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key
    saved = json.loads((folder / "outcome.json").read_text())
    saved.pop("publication")
    saved.update(verdict="STALE", reason="GitHub 返回 HTTP 401，未切换凭据来源")
    (folder / "outcome.json").write_text(json.dumps(saved))
    (folder / "outcome.json").chmod(0o600)
    lane.gateway.rows = [r for r in lane.gateway.rows if r["state"] != "success"]
    (folder / "effects" / "status-success.json").unlink()  # 原件 effects 只有 status-pending
    return folder


def test_legacy_auth_stale_is_recovered_by_same_attempt_without_rerunning_models(lane):
    folder = _legacy_auth_stale(lane)
    launches = (lane.state_root / "runs" / "launches").read_text()
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["publication"]["state"] == "success"
    assert result["recovered_from_stale"]["reason"].startswith("GitHub 返回 HTTP 401")
    history = json.loads((folder / result["recovered_from_stale"]["history"]).read_text())
    assert history["verdict"] == "STALE"  # 原失败记录保留
    assert (lane.state_root / "runs" / "launches").read_text() == launches


def test_legacy_auth_stale_is_not_recovered_after_real_drift(lane):
    _legacy_auth_stale(lane)
    (lane.source / "changed-1").write_text("pushed\n")
    git(lane.source, "commit", "-qam", "push")
    lane.gateway.pr["head"]["sha"] = git(lane.source, "rev-parse", "HEAD")
    sent = list(lane.gateway.sent)
    assert lane.review_pr(1810, 1)["verdict"] in ("STALE", "PASS")  # 新 head 是另一个 run 键
    old = [r for r in lane.status(1810) if r["outcome"] and r["outcome"]["verdict"] == "STALE"]
    assert old and all("recovered_from_stale" not in r["outcome"] for r in old)
    assert sent == lane.gateway.sent[:len(sent)]


def test_legacy_auth_stale_with_tampered_receipt_is_not_recovered(lane):
    folder = _legacy_auth_stale(lane)
    receipt = json.loads((folder / MODELS[0] / "receipt.json").read_text())
    receipt["exit_code"] = 1
    (folder / MODELS[0] / "receipt.json").write_text(json.dumps(receipt))
    (folder / MODELS[0] / "receipt.json").chmod(0o600)
    sent = list(lane.gateway.sent)
    result = lane.review_pr(1810)
    assert result["verdict"] == "STALE" and "recovered_from_stale" not in result
    assert lane.gateway.sent == sent


def test_stale_recovery_is_decided_by_reverification_not_reason_text(lane):
    """恢复与否只看重验：原因文案写成漂移，但 PR、controller、取代关系与回执都仍成立时照常补发；
    真漂移（head 已动）由 test_legacy_auth_stale_is_not_recovered_after_real_drift 覆盖。"""
    folder = _legacy_auth_stale(lane)
    saved = json.loads((folder / "outcome.json").read_text())
    saved["reason"] = "PR base、head 或目标已漂移"
    (folder / "outcome.json").write_text(json.dumps(saved))
    (folder / "outcome.json").chmod(0o600)
    assert lane.review_pr(1810)["verdict"] == "PASS"


def _interrupt_before_reuse_success(lane, env, monkeypatch):
    """沿用路径：pending 已发、outcome 已存（PASS，reused_from），success 发布前被杀。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    real = module.StatusPublisher.publish
    def publish(self, state, *args):
        if state == "success":
            raise KeyboardInterrupt
        return real(self, state, *args)
    monkeypatch.setattr(module.StatusPublisher, "publish", publish)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    monkeypatch.setattr(module.StatusPublisher, "publish", real)
    target = ReviewTarget(**json.loads(next(p for p in (lane.state_root / "runs").glob("*/target.json")
                                              if json.loads(p.read_text())["head_sha"] == lane.gateway.pr["head"]["sha"]).read_text()))
    folder = lane.state_root / "runs" / target.key
    saved = json.loads((folder / "outcome.json").read_text())
    assert "reused_from" in saved and not (folder / "effects" / "status-success.json").exists()
    return folder


def test_resumed_reuse_does_not_publish_after_newer_same_head_attempt(lane, env, monkeypatch):
    """D5 b32b8b86 Sol P1：恢复旧 attempt 不得在同 head 新 attempt 登记后直接发布沿用 success。"""
    _interrupt_before_reuse_success(lane, env, monkeypatch)
    lane.target(1810, 2)                       # 同 head 新 attempt：已登记，尚未发 pending
    sent = list(lane.gateway.sent)
    result = lane.review_pr(1810, 1)
    assert result["verdict"] != "PASS" and "success" not in lane.gateway.sent[len(sent):]


def test_resumed_reuse_does_not_publish_after_admission_lost(lane, env, monkeypatch):
    """同一序列的另一反例：恢复前部署准入失效，不得发布沿用 success。"""
    _interrupt_before_reuse_success(lane, env, monkeypatch)
    (lane.source / ".git" / "fake-admission").write_text("fail")
    sent = list(lane.gateway.sent)
    result = lane.review_pr(1810, 1)
    assert result["verdict"] != "PASS" and "success" not in lane.gateway.sent[len(sent):]


def test_completed_publication_is_only_reconciled_not_regated(lane, env):
    """已完成发布的 run：之后即使有同 head 新 attempt 登记，再调用也只对账，不改写成 STALE。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    first = lane.review_pr(1810)
    assert first["publication"]["state"] == "success"
    lane.target(1810, 2)
    again = lane.review_pr(1810, 1)
    assert again["verdict"] == "PASS" and again["publication"] == first["publication"]


def test_resume_after_planned_reuse_fell_back_is_not_blocked_by_total_admission(lane, env, monkeypatch):
    """D5 b32b8b86 Opus 中：已转双审且有 worker 后，恢复不再按两份快照准入挡收养。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned
    (lane.source / ".git" / "fake-admission").write_text("fail")       # 派发时不能沿用 → 双审
    real = _interrupt_before_aggregation(lane, monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    monkeypatch.setattr(lane, "run_reviewers", real)
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=1))  # 恢复时空间偏紧
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and len(result["reviews"]) == len(MODELS)


def test_wrongly_typed_history_outcome_does_not_block_registration(lane, env):
    """D5 b32b8b86 Opus 低：合法 JSON 但 reviews/publication 类型错误，不沿用，登记照常。"""
    first = lane.review_pr(1810)
    outcome = lane.state_root / "runs" / ReviewTarget(**first["target"]).key / "outcome.json"
    bad = json.loads(outcome.read_text())
    bad["reviews"], bad["publication"] = ["x"], "y"
    outcome.write_text(json.dumps(bad))
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and len(result["reviews"]) == len(MODELS)



def _dirty_executing_checkout(tmp_path):
    repo = tmp_path / "exec-checkout"
    (repo / ".sandcastle").mkdir(parents=True)
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    git(repo, "config", "user.name", "x")
    git(repo, "config", "user.email", "x@example.invalid")
    (repo / ".sandcastle" / "controller.py").write_text("# committed\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "controller B")
    (repo / ".sandcastle" / "controller.py").write_text("# committed\n# uncommitted edit\n")
    return repo


def test_controller_identity_is_the_executing_checkout_not_the_object_source(lane, monkeypatch, tmp_path):
    """D5 外独审 P1：执行代码所在检出不干净时拒绝；对象来源（source）不能替它出具身份。"""
    monkeypatch.setattr(module, "SOURCE_REPO", _dirty_executing_checkout(tmp_path))
    with pytest.raises(IdentityError, match="未提交"):
        lane.review_pr(1810)
    assert lane.gateway.sent == []


def test_cli_has_no_source_override():
    with pytest.raises(SystemExit):
        module.main(["review-pr", "--pr", "1810", "--private-key", "/never-read.pem", "--source", "/x"])


def test_migration_records_both_identities_requires_admission_and_is_never_reused(lane, env):
    """新部署补发旧 controller 下的 STALE：记录原审查与当前发布者两个身份，发布者须过部署准入，不冒充旧 controller。"""
    folder = _legacy_auth_stale(lane)
    review_controller = json.loads((folder / "target.json").read_text())["controller_code_head"]
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")  # 新部署
    publisher = git(lane.source, "rev-parse", "HEAD")
    (lane.source / ".git" / "fake-admission").write_text("fail")
    with pytest.raises(IdentityError, match="部署准入"):
        lane.migrate_stale(1810, 1)
    (lane.source / ".git" / "fake-admission").unlink()
    launches = (lane.state_root / "runs" / "launches").read_text()
    result = lane.migrate_stale(1810, 1)
    assert result["verdict"] == "PASS" and result["publication"]["state"] == "success"
    assert result["migrated"]["review_controller"] == review_controller
    assert result["migrated"]["publisher_controller"] == publisher != review_controller
    assert json.loads((folder / "target.json").read_text())["controller_code_head"] == review_controller
    assert (lane.state_root / "runs" / "launches").read_text() == launches  # 不重跑模型
    _advance_main(lane, env)
    git(lane.source, "checkout", "-q", publisher)
    later = lane.review_pr(1810)
    assert "reused_from" not in later and len(later["reviews"]) == len(MODELS)  # 迁移结论不作沿用来源


def test_reuse_success_delivered_but_journal_pending_is_claimed_not_restaled(lane, env, monkeypatch):
    """D5 外独审 N1：沿用 success 已送达、journal 仍 pending 时中断；恢复时即使准入失效，也先读回认领，不改记 STALE、不重发。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    def crash():
        if lane.gateway.sent[-1:] == ["success"]:
            raise KeyboardInterrupt
    lane.gateway.after_write = crash
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    lane.gateway.after_write = None
    (lane.source / ".git" / "fake-admission").write_text("fail")
    sent = list(lane.gateway.sent)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["publication"]["state"] == "success"
    assert lane.gateway.sent == sent


def test_any_pr_read_failure_at_final_publish_is_pending_not_stale(lane, monkeypatch):
    """D5 外独审 N2：按出处分类——最终发布时读取 PR 失败（如 token 刷新时安装身份不符）不判 STALE；恢复后同 attempt 补发。"""
    broken = {"on": False}
    real_get = lane.gateway.get_pr
    def get_pr(number):
        if broken["on"]:
            raise IdentityError("安装身份不符，字段 permissions")
        return real_get(number)
    monkeypatch.setattr(lane.gateway, "get_pr", get_pr)
    real_publish = module.StatusPublisher.publish
    def publish(self, state, *args):
        if state == "success" and not broken.get("done"):
            broken["on"] = broken["done"] = True
        return real_publish(self, state, *args)
    monkeypatch.setattr(module.StatusPublisher, "publish", publish)
    with pytest.raises(EffectPending, match="未判定漂移"):
        lane.review_pr(1810)
    broken["on"] = False
    launches = (lane.state_root / "runs" / "launches").read_text()
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["publication"]["state"] == "success"
    assert (lane.state_root / "runs" / "launches").read_text() == launches


def test_superseded_old_run_does_not_dispatch_models(lane):
    """D5 外独审 N3：同 head 更晚的 attempt 已登记时，旧 attempt 不发 pending、不派模型。"""
    lane.target(1810, 1)
    lane.target(1810, 2)
    result = lane.review_pr(1810, 1)
    assert result["verdict"] == "STALE" and lane.gateway.sent == []
    assert not (lane.state_root / "runs" / "launches").exists()


def _unknown_success_then_reconciled(lane, attempt=1):
    """终态 success 写入结果不明且读回不见（401 形态），主控按流程 reconcile 为未生效。"""
    real = lane.gateway.set_status
    def set_status(sha, context, state, description):
        if state == "success":
            lane.gateway.sent.append(state)
            raise OutcomeUnknown("已发送结果不明")
        return real(sha, context, state, description)
    lane.gateway.set_status = set_status
    with pytest.raises(EffectPending):
        lane.review_pr(1810, attempt)
    lane.gateway.set_status = real
    head = lane.gateway.pr["head"]["sha"]
    target = next(json.loads(p.read_text()) for p in (lane.state_root / "runs").glob(f"*-a{attempt}/target.json")
                  if json.loads(p.read_text())["head_sha"] == head)
    lane.reconcile(target["run_id"], "主控已核实 GitHub 上没有该 success")
    return list(lane.gateway.sent)


def test_reconciled_reuse_success_regates_admission_before_resend(lane, env):
    """#1913 独审 B1：对账为未生效后恢复，沿用结果必须重做部署准入；准入失效就不发 success。"""
    lane.review_pr(1810)
    _advance_main(lane, env)
    sent = _unknown_success_then_reconciled(lane)
    (lane.source / ".git" / "fake-admission").write_text("fail")
    result = lane.review_pr(1810)
    assert "success" not in lane.gateway.sent[len(sent):] and result["verdict"] == "STALE"


def test_reconciled_success_is_not_resent_after_newer_same_head_attempt(lane):
    """#1913 独审 B1：对账为未生效后，同 head 已登记更晚 attempt，旧 run 不再发 success。"""
    sent = _unknown_success_then_reconciled(lane)
    lane.target(1810, 2)
    result = lane.review_pr(1810, 1)
    assert "success" not in lane.gateway.sent[len(sent):] and result["verdict"] == "STALE"


def test_reconciled_success_passing_the_gate_is_resent(lane):
    """B1 正向：对账为未生效、门仍成立时照常补发。"""
    _unknown_success_then_reconciled(lane)
    result = lane.review_pr(1810)
    assert result["publication"]["state"] == "success"


def test_migration_is_retryable_after_transient_failure_mid_publish(lane, monkeypatch):
    """#1913 独审 N-a：迁移已重验写下结论、发布时读 PR 401；认证恢复后再迁移能补发，不必重跑模型。"""
    folder = _legacy_auth_stale(lane)
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")
    real_get = lane.gateway.get_pr
    calls = {"n": 0}
    def get_pr(number):
        calls["n"] += 1
        if calls["n"] == 3:  # load_target、recover_stale.check_current 之后：publish 内的 check_current
            raise IdentityError("GitHub 返回 HTTP 401")
        return real_get(number)
    monkeypatch.setattr(lane.gateway, "get_pr", get_pr)
    before = list(lane.gateway.sent)
    with pytest.raises(EffectPending):
        lane.migrate_stale(1810, 1)
    monkeypatch.setattr(lane.gateway, "get_pr", real_get)
    assert lane.gateway.sent == before
    launches = (lane.state_root / "runs" / "launches").read_text()
    result = lane.migrate_stale(1810, 1)
    assert result["publication"]["state"] == "success" and result["recovered_from_stale"]["reason"].startswith("GitHub")
    assert (lane.state_root / "runs" / "launches").read_text() == launches
    with pytest.raises(IdentityError, match="只迁移未发布"):
        lane.migrate_stale(1810, 1)  # 已发布的不再迁移
    assert json.loads((folder / "outcome.json").read_text())["publication"]["state"] == "success"


def test_refused_migration_leaves_stale_on_disk(lane):
    """#1913 独审 N-b：迁移被同 head 更晚 attempt 取代时，磁盘 outcome 回到 STALE，不留未发布的 PASS。"""
    folder = _legacy_auth_stale(lane)
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")
    lane.target(1810, 2)
    sent = list(lane.gateway.sent)
    result = lane.migrate_stale(1810, 1)
    assert "migration_refused" in result and lane.gateway.sent == sent
    assert json.loads((folder / "outcome.json").read_text())["verdict"] == "STALE"


def test_migration_refuses_changed_review_contract(lane, monkeypatch):
    """#1913 独审 N-c：合同（policy、模型、提示词）已变的旧结论不迁移，须新审。"""
    _legacy_auth_stale(lane)
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed with new contract")
    monkeypatch.setattr(module, "REVIEW_CONTRACT", "sha256:" + "f" * 64)
    with pytest.raises(IdentityError, match="合同"):
        lane.migrate_stale(1810, 1)


def test_migration_of_contractless_legacy_target_checks_dispatched_prompt(lane, monkeypatch):
    """旧 controller 登记的 target 未记合同：以实际派发给模型的提示词核对，提示词不同就不迁移。"""
    folder = _legacy_auth_stale(lane)
    target = json.loads((folder / "target.json").read_text())
    target["review_contract"] = ""
    (folder / "target.json").write_text(json.dumps(target))
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")
    original = module.PROMPT
    monkeypatch.setattr(module, "PROMPT", original + "\n新增一条审查要求")
    with pytest.raises(IdentityError, match="合同"):
        lane.migrate_stale(1810, 1)
    monkeypatch.setattr(module, "PROMPT", original)
    assert lane.migrate_stale(1810, 1)["publication"]["state"] == "success"


def test_nb_residual_retry_early_return_leaves_disk_pass(lane, monkeypatch):
    """#1944（#1913 独审 N-b' 残余，移植自非作者独审反例）：迁移瞬态失败后重试，`migrate_stale` 把
    `saved` 换成历史里更早的 STALE 记录；如果这次 `recover_stale` 重验又提前返回（这里用回执重验结果
    与原记录不一致模拟早退），磁盘此前仍留着上一轮迁移写下、未发布的 PASS。返回值须与磁盘一致地回到
    STALE，不能一个说 STALE、另一个仍是未发布的 PASS。"""
    folder = _legacy_auth_stale(lane)
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed")
    real_get = lane.gateway.get_pr
    calls = {"n": 0}
    def get_pr(number):
        calls["n"] += 1
        if calls["n"] == 3:
            raise IdentityError("GitHub 返回 HTTP 401")
        return real_get(number)
    monkeypatch.setattr(lane.gateway, "get_pr", get_pr)
    with pytest.raises(EffectPending):
        lane.migrate_stale(1810, 1)
    monkeypatch.setattr(lane.gateway, "get_pr", real_get)
    real_validate = module.validate_review
    def flip(*args, **kwargs):
        o = real_validate(*args, **kwargs)
        return module.ReviewOutcome(o.model, "BLOCK", o.session_id, o.reason) if o.model == module.MODELS[0] else o
    monkeypatch.setattr(module, "validate_review", flip)  # 模拟重验与原记录不一致 → recover_stale 早退
    sent_before = len(lane.gateway.sent)
    result = lane.migrate_stale(1810, 1)
    on_disk = json.loads((folder / "outcome.json").read_text())
    assert result["verdict"] == on_disk["verdict"] == "STALE", (result["verdict"], on_disk["verdict"], "publication" in on_disk)
    assert on_disk["recovery_refused"] == "重验结果与原记录不一致"
    assert "publication" not in on_disk
    assert len(lane.gateway.sent) == sent_before


# ---------------- Codex 额度耗尽时的临时组合（Kimi + Opus） ----------------

LEGACY_MODELS = ("gpt-6.1-sol", "claude-opus-5-5")
LEGACY_POLICY = "external-pr-v1"


def _contract(policy, models):
    return "sha256:" + hashlib.sha256(json.dumps([policy, models, module.PROMPT]).encode()).hexdigest()


def _use_contract(monkeypatch, models, policy):
    monkeypatch.setattr(module, "MODELS", models)
    monkeypatch.setattr(module, "POLICY", policy)
    monkeypatch.setattr(module, "REVIEW_CONTRACT", _contract(policy, models))


def test_fallback_pair_is_two_families_under_its_own_contract():
    assert MODELS == ("kimi-k3.1-pro", "claude-opus-5-5")
    assert len({model.split("-")[0] for model in MODELS}) == len(MODELS) == 2
    assert module.POLICY == "external-pr-v1-kimi" != LEGACY_POLICY
    assert module.REVIEW_CONTRACT == _contract(module.POLICY, MODELS) != _contract(LEGACY_POLICY, LEGACY_MODELS)


def test_pass_under_legacy_contract_is_not_reused_after_switch(lane, env, monkeypatch):
    current = (module.MODELS, module.POLICY)
    _use_contract(monkeypatch, LEGACY_MODELS, LEGACY_POLICY)
    first = lane.review_pr(1810)
    assert first["verdict"] == "PASS" and [r["model"] for r in first["reviews"]] == list(LEGACY_MODELS)
    _use_contract(monkeypatch, *current)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and [r["model"] for r in result["reviews"]] == list(MODELS)
    assert result["target"]["policy_version"] == "external-pr-v1-kimi"
    assert sorted((lane.state_root / "runs" / "launches").read_text().splitlines()[2:]) == sorted(MODELS)


@pytest.mark.parametrize("recorded_contract", [True, False])
def test_legacy_contract_stale_is_not_migrated(lane, monkeypatch, recorded_contract):
    current = (module.MODELS, module.POLICY)
    _use_contract(monkeypatch, LEGACY_MODELS, LEGACY_POLICY)
    folder = _legacy_auth_stale(lane)
    if not recorded_contract:  # 旧 controller 登记的 target 未记合同
        target = json.loads((folder / "target.json").read_text())
        target["review_contract"] = ""
        (folder / "target.json").write_text(json.dumps(target))
    _use_contract(monkeypatch, *current)
    git(lane.source, "commit", "--allow-empty", "-qm", "controller redeployed with fallback pair")
    sent = list(lane.gateway.sent)
    with pytest.raises(IdentityError, match="policy"):
        lane.migrate_stale(1810, 1)
    assert lane.gateway.sent == sent
    assert json.loads((folder / "outcome.json").read_text())["verdict"] == "STALE"


def test_block_left_by_retired_reviewer_still_vetoes_reuse(lane, env, monkeypatch):
    """换组合后，旧 run 里已退役 reviewer 留下的 BLOCK 证据仍算同补丁 BLOCK。"""
    current = (module.MODELS, module.POLICY)
    _use_contract(monkeypatch, LEGACY_MODELS, LEGACY_POLICY)
    _modes(lane, **{LEGACY_MODELS[0]: "BLOCK"})
    legacy = lane.review_pr(1810)
    _clear_modes(lane)
    folder = lane.state_root / "runs" / ReviewTarget(**legacy["target"]).key
    assert (folder / LEGACY_MODELS[0] / "receipt.json").exists()
    (folder / "outcome.json").write_text(json.dumps({**legacy, "verdict": "FAILED", "state": "error", "reviews": []}))
    _use_contract(monkeypatch, *current)
    assert lane.review_pr(1810, 2)["verdict"] == "PASS"
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert "reused_from" not in result and [r["model"] for r in result["reviews"]] == list(MODELS)


# ---- 旁听审查员（ADVISORY_REVIEW_MODELS）：脱离的独立进程，不进结论、状态与合同 ----
ADVISORY = module.ADVISORY_REVIEW_MODELS[0]


def _detached(lane, **config):
    """让 review_pr 派出的旁听进程用本测试的目录与 worker 替身。"""
    config = {"state_root": str(lane.state_root), "checkout_root": str(lane.checkout_root),
              "source": str(lane.source), "launcher": lane.launcher, **config}
    lane.advisory_launcher = [sys.executable, str(Path(__file__).with_name("external_review_advisory.py")),
                              json.dumps(config)]


def _run_folder(lane, result):
    return lane.state_root / "runs" / ReviewTarget(**result["target"]).key


def _wait_advisory(lane, result, seconds=60):
    import time
    path = _run_folder(lane, result) / module.ADVISORY_DIR / "outcome.json"
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists():
            try:
                return json.loads(path.read_text())
            except ValueError:
                pass
        time.sleep(0.05)
    log = path.with_name("advisory.log")
    raise AssertionError("旁听结论未落盘：" + (log.read_text() if log.exists() else "无日志"))


def _kill_advisory(lane, result):
    import os
    import signal
    advisory = _run_folder(lane, result) / module.ADVISORY_DIR
    import time

    def kill(pid):
        for how in (os.killpg, os.kill):
            try:
                how(pid, signal.SIGKILL)
            except OSError:
                pass
    try:  # 先结束旁听进程本身，它就不会再派新 worker
        kill(json.loads((advisory / "spawn.json").read_text())["pid"])
    except (OSError, ValueError, KeyError):
        pass
    time.sleep(0.2)
    pids = set()
    for path in advisory.glob("*/process.json"):
        try:
            pids.add(json.loads(path.read_text())["pid"])
        except (OSError, ValueError, KeyError):
            pass
    # 兜底：命令行里带本测试状态目录的进程（旁听进程的配置 JSON、worker 的 --output-dir）
    pids.update(pid for pid, _, _, command in module._ps_rows() if str(lane.state_root) in command)
    for pid in pids:
        kill(pid)


def _launched_models(lane):
    return sorted((lane.state_root / "runs" / "launches").read_text().splitlines())


def _lock_held(path):
    import fcntl
    import os
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def test_advisory_is_off_by_default(lane, monkeypatch):
    monkeypatch.delenv(module.ADVISORY_ENV, raising=False)
    _detached(lane)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and lane.gateway.sent == ["pending", "success"]
    assert _launched_models(lane) == sorted(MODELS)
    assert not (_run_folder(lane, result) / module.ADVISORY_DIR).exists()


def test_advisory_block_with_gating_pass_still_publishes_success(lane, monkeypatch):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    _modes(lane, **{ADVISORY: "BLOCK"})
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["state"] == "success"
    assert lane.gateway.sent == ["pending", "success"]
    advisory = _wait_advisory(lane, result)
    assert [(r["model"], r["verdict"], r["checkout"]) for r in advisory["reviews"]] == [(ADVISORY, "BLOCK", "removed")]
    run = _run_folder(lane, result)
    assert json.loads((run / "outcome.json").read_text()) == result  # 旁听不写 gating 文件
    assert (run / module.ADVISORY_DIR / ADVISORY / "receipt.json").is_file()
    assert _launched_models(lane) == sorted([*MODELS, ADVISORY])
    assert not (lane.checkout_root / result["run_id"]).exists()
    assert lane.gateway.sent == ["pending", "success"]
    assert not lane._reviewer_blocked({"target": result["target"], "outcome": result})
    assert lane._reviewers(run) == list(MODELS)


def test_advisory_block_does_not_veto_reuse(lane, env, monkeypatch):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    _modes(lane, **{ADVISORY: "BLOCK"})
    first = lane.review_pr(1810)
    assert _wait_advisory(lane, first)["reviews"][0]["verdict"] == "BLOCK"
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and result["reused_from"]["run_id"] == first["run_id"]
    assert lane.gateway.sent == ["pending", "success", "pending", "success"]
    assert not (_run_folder(lane, result) / module.ADVISORY_DIR).exists()  # 沿用不派旁听


@pytest.mark.parametrize("mode", ["CRASH", "PASS:notool"])
def test_advisory_failure_is_ignored(lane, monkeypatch, mode):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    _modes(lane, **{ADVISORY: mode})
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS" and lane.gateway.sent == ["pending", "success"]
    assert [(r["model"], r["verdict"]) for r in _wait_advisory(lane, result)["reviews"]] == [(ADVISORY, "FAILED")]


def test_advisory_never_rescues_gating_block(lane, monkeypatch):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    _modes(lane, **{MODELS[0]: "BLOCK", ADVISORY: "PASS"})
    result = lane.review_pr(1810)
    assert result["verdict"] == "BLOCK" and lane.gateway.sent == ["pending", "failure"]
    assert _wait_advisory(lane, result)["reviews"][0]["verdict"] == "PASS"


def test_gating_returns_even_if_advisory_hangs_forever(lane, monkeypatch):
    import time
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)  # 生产上限（50 分钟）：测试期间旁听一直挂着
    _modes(lane, **{ADVISORY: "HANG"})
    started = time.monotonic()
    result = lane.review_pr(1810)
    try:
        assert time.monotonic() - started < 30
        assert result["verdict"] == "PASS" and lane.gateway.sent == ["pending", "success"]
        lock = _run_folder(lane, result) / module.ADVISORY_DIR / ".lock"
        for _ in range(400):
            if lock.exists() and _lock_held(lock):
                break
            time.sleep(0.05)
        assert _lock_held(lock)  # 旁听进程仍在跑、持自己的锁
        assert not _lock_held(_run_folder(lane, result) / "owner.lock")  # gating 的锁已释放
        assert lane.review_pr(1810)["run_id"] == result["run_id"]  # 同键重跑不被旁听挡住
        assert lane.gateway.sent == ["pending", "success"]
    finally:
        _kill_advisory(lane, result)


def test_controller_crash_leaves_advisory_running_and_outcome_lands(lane, monkeypatch):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    spawn = lane._spawn_advisory
    def crash_after_spawn(key):
        spawn(key)
        raise KeyboardInterrupt  # controller 在派出旁听后立刻崩溃
    monkeypatch.setattr(lane, "_spawn_advisory", crash_after_spawn)
    with pytest.raises(KeyboardInterrupt):
        lane.review_pr(1810)
    assert lane.gateway.sent == ["pending", "success"]
    result = lane.status(1810)[0]["outcome"]
    assert _wait_advisory(lane, result)["reviews"][0]["verdict"] == "PASS"


def test_advisory_timeout_snapshot_is_reclaimed_by_reaper_on_next_run(lane, monkeypatch):
    import os
    import signal
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane)
    monkeypatch.setattr(lane, "_spawn_advisory", lambda key: None)  # 本测试在进程内跑旁听，便于计时
    result = lane.review_pr(1810)
    key = ReviewTarget(**result["target"]).key
    _modes(lane, **{ADVISORY: "HANGTERM"})  # 忽略 SIGTERM：取消路径失效
    lane.advisory_timeout, lane.advisory_term_grace = 0.5, 0.5
    advisory = lane.run_advisory(key)
    entry = advisory["reviews"][0]
    assert (entry["verdict"], entry["checkout"]) == ("TIMEOUT", "retained")
    worker = _run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY
    checkout = Path(json.loads((worker / "launch.json").read_text())["checkout"])
    assert checkout.is_dir()
    pid = json.loads((worker / "process.json").read_text())["pid"]
    os.killpg(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    lane.container_state = lambda container: "absent"  # 监督进程死了还不够：容器确认不在了才删
    lane.review_pr(1810, 2)  # 下一次 run 开头的回收
    assert not checkout.exists()
    assert json.loads((worker / "checkout-cleanup.json").read_text())["by"] == "reaper"
    assert lane.gateway.sent[-2:] == ["pending", "success"]


def test_reaper_never_removes_a_checkout_in_use(lane, capfd):
    import subprocess
    result = lane.review_pr(1810)
    folder = _run_folder(lane, result)
    checkout = lane.checkout_root / result["run_id"] / MODELS[0]
    checkout.mkdir(parents=True)
    (checkout / "file").write_text("x" * 1000)
    with module._lock(folder):  # run 锁被持有
        assert lane.reap()["removed"] == 0 and checkout.exists()
    advisory_checkout = lane.checkout_root / result["run_id"] / ADVISORY
    advisory_checkout.mkdir()
    (folder / module.ADVISORY_DIR).mkdir(mode=0o700)
    (folder / module.ADVISORY_DIR / "outcome.json").write_text("{}")
    import fcntl
    import os
    fd = os.open(folder / module.ADVISORY_DIR / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:  # 旁听锁被持有：两份快照都不动
        assert lane.reap()["removed"] == 0 and checkout.exists() and advisory_checkout.exists()
    finally:
        os.close(fd)
    user = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", str(checkout)])
    try:  # 仍有进程在用该快照
        stats = lane.reap()
        assert checkout.exists() and not advisory_checkout.exists() and stats["removed"] == 1
    finally:
        user.kill()
        user.wait()
    stats = lane.reap()
    assert not checkout.exists() and stats == {"removed": 1, "bytes_freed": 1000, "retained_unknown": 0}
    assert not (lane.checkout_root / result["run_id"]).exists()
    assert "external-review reaper" in capfd.readouterr().err


def test_advisory_over_quota_is_skipped_not_failed(lane, monkeypatch):
    monkeypatch.setenv(module.DAILY_INPUT_CAP_ENV, "1000")
    result = lane.review_pr(1810)  # 旁听关闭
    monkeypatch.setattr(lane, "recent_input_tokens", lambda: 1000)
    advisory = lane.run_advisory(ReviewTarget(**result["target"]).key)
    assert advisory["reviews"][0]["verdict"] == "SKIPPED" and "上限 1000" in advisory["reviews"][0]["reason"]
    assert not (_run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY).exists()
    assert lane.gateway.sent == ["pending", "success"]


def test_advisory_receipts_count_toward_daily_cap(lane):
    result = lane.review_pr(1810)
    key = ReviewTarget(**result["target"]).key
    assert lane.run_advisory(key)["reviews"][0]["verdict"] == "PASS"
    assert lane.run_advisory(key)["reviews"][0]["verdict"] == "PASS"  # 已有结论：只读回，不再派发
    assert _launched_models(lane).count(ADVISORY) == 1
    worker = _run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY
    receipt = json.loads((worker / "receipt.json").read_text())
    receipt["usage"] = {"input_tokens": 777, "commands": 1, "reported": True}
    module._save(worker / "receipt.json", receipt)
    assert lane.recent_input_tokens() == 777


def test_advisory_is_outside_review_contract():
    assert not set(module.ADVISORY_REVIEW_MODELS) & set(MODELS)
    assert module.ADVISORY_DIR not in MODELS and module.ADVISORY_DIR != "effects"
    # 合同值与加旁听之前逐字相同：沿用、迁移的合同判断不受旁听影响。
    assert module.REVIEW_CONTRACT == "sha256:f412d17f29e863a2ed4c5fd317fc78c5d1a31608aa8fdf5e2a4151b6164f4383"
    assert module.REVIEW_CONTRACT == "sha256:" + hashlib.sha256(
        json.dumps([module.POLICY, MODELS, module.PROMPT]).encode()).hexdigest()


# ---- 第四轮：空间、prepare 硬墙钟、回收的容器核实与先后 ----


def test_advisory_skipped_when_no_room_for_an_extra_snapshot(lane, monkeypatch):
    result = lane.review_pr(1810)  # 旁听关闭
    target = ReviewTarget(**result["target"])
    single = module.snapshot_plan(lane.source, target)[1]
    monkeypatch.setattr(module.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=single * (len(MODELS) + 1) - 1))
    advisory = lane.run_advisory(target.key)
    assert advisory["reviews"][0]["verdict"] == "SKIPPED" and advisory["reviews"][0]["reason"].startswith("no space")
    assert not (_run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY).exists()
    assert lane.gateway.sent == ["pending", "success"]


def test_gating_admission_leaves_room_for_a_live_advisory_snapshot(lane, monkeypatch):
    import fcntl
    import os
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    single = module.snapshot_plan(lane.source, target)[1]
    worker = _run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY
    worker.mkdir(parents=True, mode=0o700)
    module._save(worker / "prepare.json", {"run_id": target.run_id, "checkout": "x", "required_bytes": 5000})
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(free=single * len(MODELS) + 4999))
    lock = os.open(worker.parent / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)  # 旁听正在 prepare（锁被持有、尚无 launch）
    try:
        with pytest.raises(IdentityError, match="空间不足"):
            lane.admit_space(target)
    finally:
        os.close(lock)
    lane.admit_space(target)  # 旁听不在了：预留随之释放


def test_advisory_hanging_in_prepare_is_bounded_by_watchdog(lane, monkeypatch):
    import os
    import time
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    _detached(lane, timeout=0.5, grace=0.2, margin=0.5, hang_prepare=True)
    started = time.monotonic()
    result = lane.review_pr(1810)
    assert lane.gateway.sent == ["pending", "success"]
    try:
        advisory = _wait_advisory(lane, result, seconds=30)
        assert advisory["watchdog"] and advisory["reviews"][0]["verdict"] == "TIMEOUT"
        assert time.monotonic() - started < 30
        lock = _run_folder(lane, result) / module.ADVISORY_DIR / ".lock"
        for _ in range(200):  # 看门狗结束了旁听进程组，锁随之释放
            if not _lock_held(lock):
                break
            time.sleep(0.05)
        assert not _lock_held(lock)
        pid = json.loads((lock.parent / "spawn.json").read_text())["pid"]
        for _ in range(200):
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("旁听进程未结束")
    finally:
        _kill_advisory(lane, result)


def _leaked(lane, result, *, closed, pid=None):
    """在已完结 run 上造一份遗留 gating 快照：回执 container_closed 按参数，supervisor.json 记容器。"""
    folder = _run_folder(lane, result)
    worker = folder / MODELS[0]
    receipt = json.loads((worker / "receipt.json").read_text())
    receipt["container_closed"] = closed
    module._save(worker / "receipt.json", receipt)
    if pid is not None:
        module._save(worker / "process.json", {"pid": pid, "launch_id": "x"})
    checkout = lane.checkout_root / result["run_id"] / MODELS[0]
    checkout.mkdir(parents=True)
    (checkout / "f").write_text("x" * 100)
    return checkout


@pytest.mark.parametrize("state, kept", [("running", True), ("unknown", True), ("absent", False), ("stopped", False)])
def test_reaper_requires_container_gone_not_just_dead_supervisor(lane, state, kept):
    import subprocess
    result = lane.review_pr(1810)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()  # 监督进程已不在
    checkout = _leaked(lane, result, closed=False, pid=dead.pid)
    seen = []
    lane.container_state = lambda container: seen.append(container) or state
    stats = lane.reap()
    assert seen == ["a" * 64]  # 回执里的容器 id
    assert checkout.exists() is kept
    assert stats["retained_unknown"] == (1 if state == "unknown" else 0)


def test_reaper_trusts_closed_receipt_without_docker(lane):
    result = lane.review_pr(1810)
    checkout = _leaked(lane, result, closed=True)
    lane.container_state = lambda container: pytest.fail("回执已确认关容器，不应再查 docker")
    assert lane.reap()["removed"] == 1 and not checkout.exists()


def test_reaper_runs_before_admission_so_leaks_never_block_their_own_cleanup(lane, monkeypatch):
    result = lane.review_pr(1810)
    checkout = _leaked(lane, result, closed=True)
    # 遗留快照占着空间时总准入不过；回收在准入之前、不持 run 锁运行，所以本次登记照常通过。
    monkeypatch.setattr(module.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=1 if checkout.exists() else 10**15))
    second = lane.review_pr(1810, 2)
    assert not checkout.exists() and second["verdict"] == "PASS"
    assert lane.gateway.sent[-2:] == ["pending", "success"]


def test_reaper_skips_when_another_reaper_holds_the_host_lock(lane):
    import fcntl
    import os
    result = lane.review_pr(1810)
    checkout = _leaked(lane, result, closed=True)
    fd = os.open(lane.state_root / module.REAPER_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert lane.reap()["removed"] == 0 and checkout.exists()
    finally:
        os.close(fd)
    assert lane.reap()["removed"] == 1


# ---- 第五轮（kimi BLOCK）：旁听 Popen 失败、提前返回的 checkout 字段、恢复发布不派旁听 ----


@pytest.mark.parametrize("by", ["cleanup", "reaper"])
def test_advisory_popen_failure_snapshot_is_reclaimed(lane, monkeypatch, by):
    result = lane.review_pr(1810)  # 旁听关闭
    key = ReviewTarget(**result["target"]).key
    lane.launcher = [str(lane.state_root / "no-such-launcher")]  # launch.json 写入后 Popen 失败
    if by == "reaper":  # 本次收尾没删掉（例如删除时出错），留给回收
        monkeypatch.setattr(lane, "cleanup_checkout", lambda *args, **kwargs: False)
    entry = lane.run_advisory(key)["reviews"][0]
    worker = _run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY
    checkout = Path(json.loads((worker / "launch.json").read_text())["checkout"])
    assert entry["verdict"] == "FAILED"
    receipt = json.loads((worker / "receipt.json").read_text())
    assert (receipt["status"], receipt["failure_reason"], receipt["container_closed"]) == (
        "failed", "SupervisorNotStarted", True)
    lane.container_state = lambda container: pytest.fail("worker 从未启动，不应查 docker")
    if by == "cleanup":
        assert entry["checkout"] == "removed" and not checkout.exists()
    else:
        assert entry["checkout"] == "retained" and checkout.is_dir()
        stats = lane.reap()
        assert (stats["removed"], stats["retained_unknown"]) == (1, 0) and not checkout.exists()


@pytest.mark.parametrize("cause", ["quota", "space", "active_prepare"])
def test_advisory_early_returns_carry_checkout_field(lane, monkeypatch, cause):
    import subprocess
    result = lane.review_pr(1810)  # 旁听关闭
    target = ReviewTarget(**result["target"])
    holder = None
    if cause == "quota":
        monkeypatch.setenv(module.DAILY_INPUT_CAP_ENV, "1000")
        monkeypatch.setattr(lane, "recent_input_tokens", lambda: 1000)
    elif cause == "space":
        single = module.snapshot_plan(lane.source, target)[1]
        monkeypatch.setattr(module.shutil, "disk_usage",
                            lambda path: SimpleNamespace(free=single * (len(MODELS) + 1) - 1))
    else:  # 旧 prepare 仍有进程在用快照
        worker = _run_folder(lane, result) / module.ADVISORY_DIR / ADVISORY
        worker.mkdir(parents=True, mode=0o700)
        checkout = lane.checkout_root / target.run_id / ADVISORY
        module._save(worker / "prepare.json", {"run_id": target.run_id, "checkout": str(checkout),
                                               "required_bytes": 1})
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", str(checkout)])
    try:
        entry = lane.run_advisory(target.key)["reviews"][0]
    finally:
        if holder is not None:
            holder.kill()
            holder.wait()
    assert entry["verdict"] == ("FAILED" if cause == "active_prepare" else "SKIPPED")
    assert entry["checkout"] in ("removed", "retained")
    assert set(entry) >= {"model", "verdict", "session_id", "reason", "checkout"}


def test_resumed_publication_does_not_spawn_advisory(lane, monkeypatch):
    monkeypatch.setenv(module.ADVISORY_ENV, "1")
    spawned = []
    monkeypatch.setattr(lane, "_spawn_advisory", spawned.append)
    first = lane.review_pr(1810)
    assert first["verdict"] == "PASS" and spawned == [ReviewTarget(**first["target"]).key]
    again = lane.review_pr(1810)  # outcome 已存在：恢复发布（只对账）
    assert again["run_id"] == first["run_id"] and "publication" in again
    assert len(spawned) == 1
