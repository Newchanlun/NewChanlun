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
from pilot1742.external_review import (
    docker_cli as real_docker_cli,
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
        self.pr = {"number": 1810, "state": "open", "draft": False, "auto_merge": None,
                   "user": {"login": "business-owner"},
                   "base": {"repo": {"id": 1150335160}, "ref": "main", "sha": env.base},
                   "head": {"repo": {"id": 1150335160}, "ref": "feature/business", "sha": git(env.source, "rev-parse", "HEAD")}}
        self.repo = {"allow_auto_merge": False}
        self.rows, self.sent = [], []
        self.fault, self.hide, self.after_write = False, False, None
    def get_pr(self, number):
        assert number == 1810
        return copy.deepcopy(self.pr)
    def get_repo(self):
        return copy.deepcopy(self.repo)
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


@pytest.fixture(autouse=True)
def vm_trims(monkeypatch):
    """#1986：测试里不碰真实 Colima。缺省 trim 换成记录器；需要别的行为的用例直接改 lane.vm_trim。"""
    calls = []
    monkeypatch.setattr(module, "trim_vm_disk", lambda root: calls.append(root) or {"state": "trimmed", "fixture": True})
    return calls


def _fake_preflight_pass(_target: ReviewTarget) -> dict:
    checks = []
    for model in module.MODELS:
        route = f"codex:{model}@chatgpt.com" if model.startswith("gpt-6.2-") else (
            "kimi@api.kimi.com" if "kimi" in model else "claude@api.anthropic.com" if "claude" in model else f"{model}@example.test")
        checks.append({"name": f"route:{model}", "class": "route", "ok": True,
                       "detail": {"expected": [route], "actual": [route], "log_found": True, "sealed": True}})
        checks.append({"name": f"seal:{model}", "class": "seal", "ok": True,
                       "detail": {"http_status": 200, "status": "sealed", "ok": True}})
        checks.append({"name": f"roundtrip:{model}", "class": "roundtrip", "ok": True,
                       "detail": {"http_status": 200, "terminal": "response.completed", "status": "completed",
                                  "returned_model": model, "ok": True, "error": None}})
    return {"kind": "review-preflight", "is_review_result": False, "ready": True, "checks": checks,
            "image_id": "sha256:" + "1" * 64}


def _make_fake_session_receipt(state_root: Path):
    def fake(model: str, launch_id: str, _session_id: str, _since: float) -> dict:
        out_sha = ""
        resp_sha = ""
        reqs = 1
        for path in (state_root / "runs").glob(f"*/{model}/launch.json"):
            try:
                if json.loads(path.read_text()).get("launch_id") == launch_id:
                    worker = path.parent
                    final_text = None
                    for line in (worker / "events.jsonl").read_text().splitlines():
                        if not line.strip():
                            continue
                        ev = json.loads(line)
                        if ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                            final_text = ev["item"].get("text")
                    if isinstance(final_text, str):
                        out_sha = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
                    rids = []
                    for line in (worker / "session.jsonl").read_text().splitlines():
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        if row.get("type") == "token_usage_record":
                            rid = (row.get("payload") or {}).get("response_id")
                            if isinstance(rid, str) and rid:
                                rids.append(rid)
                    if rids:
                        rid_shas = [hashlib.sha256(r.encode("utf-8")).hexdigest() for r in rids]
                        resp_sha = rid_shas[-1]
                        reqs = len(rid_shas)
                    else:
                        rid_shas = [resp_sha]
                    break
            except (OSError, ValueError):
                continue
        return {
            "routes": [f"codex:{model}@chatgpt.com"],
            "requests": reqs,
            "sealed": True,
            "response_id_sha256s": rid_shas if rids else [resp_sha] * reqs,
            "last_response_id_sha256": resp_sha,
            "last_output_sha256": out_sha,
        }
    return fake


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
                          launcher=[sys.executable, str(Path(__file__).with_name("external_review_child.py"))],
                          preflight=_fake_preflight_pass,
                          session_receipt=_make_fake_session_receipt(env.home / "review"))


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
    (folder / "session.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": session, "model_provider": "cliproxy-local"}}) + "\n"
        + json.dumps({"type": "turn_context", "payload": {"model": launch["model"]}}) + "\n"
    )
    receipt.update(session_id=session, result=scenario["result"], exit_code=scenario["exit_code"],
                   observed_provider="cliproxy-local", observed_model=launch["model"])
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


def _dead_launch(lane, run):
    launch_id = str(uuid.uuid4())
    worker = lane.state_root / "runs" / run / MODELS[0]
    worker.mkdir(parents=True)
    module._save(worker / "launch.json", {"launch_id": launch_id})
    return launch_id, module.REVIEW_VOLUME_PREFIX + launch_id


def test_reaper_trims_vm_only_after_removing_a_volume(lane, vm_trims):
    """#1986：本轮删掉了卷才 trim，trim 以 checkout_root 为节流根、结果记进 reaper 日志；没删卷不 trim。"""
    dead, name = _dead_launch(lane, "dead-run")
    unknown = str(uuid.uuid4())
    lane.docker = FakeDocker({name: dead, module.REVIEW_VOLUME_PREFIX + unknown: unknown}, {"c1": (dead, name)})
    entries = lane.reap_review_volumes()
    assert vm_trims == [lane.checkout_root]
    assert entries[-1] == {"action": "vm_trim", "state": "trimmed", "fixture": True}
    # 再跑一轮：死卷已删，只剩未登记 launch 的卷（不碰）——没有删卷，不 trim。
    assert not any(e["action"] == "vm_trim" for e in lane.reap_review_volumes())
    # 卷删不掉（in use）也不 trim。
    stuck, stuck_name = _dead_launch(lane, "stuck-run")
    lane.docker = FakeDocker({stuck_name: stuck}, volume_rm_stderr="volume is in use")
    assert not any(e["action"] == "vm_trim" for e in lane.reap_review_volumes())
    assert vm_trims == [lane.checkout_root]
    log = [json.loads(line) for line in (lane.state_root / "volume-reaper.jsonl").read_text().splitlines()]
    assert [e["state"] for e in log if e["action"] == "vm_trim"] == ["trimmed"]


def test_vm_trim_failure_never_blocks_dispatch_or_changes_verdict(lane):
    """trim 抛错只记日志；派发照常、结论不变。"""
    dead, name = _dead_launch(lane, "dead-run")
    lane.docker = FakeDocker({name: dead})
    def broken(root):
        raise TimeoutError("colima hung")
    lane.vm_trim = broken
    assert lane.review_pr(1810)["verdict"] == "PASS"
    log = [json.loads(line) for line in (lane.state_root / "volume-reaper.jsonl").read_text().splitlines()]
    trims = [e for e in log if e["action"] == "vm_trim"]
    assert trims and trims[0]["state"] == "failed" and trims[0]["reason"] == "TimeoutError"
    assert name not in lane.docker.volumes


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


PARTIAL_OR_FILTERED_PATCH_READ = frozenset({
    "show-file", "var-export-quoted-show", "show-HEAD-file",
    "show-file-dot-slash", "show-two-changed-files", "show-file-numbered",
    "dollar-at-end-of-double-quotes", "triple-dot-base", "filter-chain",
})


@pytest.mark.parametrize("claim", ["PASS", "BLOCK"])
def test_conclusion_after_frozen_patch_read_stands(lane, claim):
    outcomes = _verdicts_with_commands(lane, claim, PATCH_READ)
    if claim == "BLOCK":
        assert {case: o.reason for case, o in outcomes.items() if o.verdict != claim} == {}
    else:
        # R35/R37：完整连续补丁读取可放行 PASS；单文件/多文件无界 blob/非 -U0 grep 过滤读取不得单独放行 PASS（允许 BLOCK）
        full_bad = {
            case: o.reason for case, o in outcomes.items()
            if case not in PARTIAL_OR_FILTERED_PATCH_READ and o.verdict != "PASS"
        }
        partial_bad = {
            case: (o.verdict, o.reason) for case, o in outcomes.items()
            if case in PARTIAL_OR_FILTERED_PATCH_READ
            and (o.verdict != "FAILED" or "未完整覆盖全部冻结改动行" not in (o.reason or ""))
        }
        assert full_bad == {} and partial_bad == {}


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
    orig_reverify = lane._reverify_sealed_receipts
    monkeypatch.setattr(lane, "_reverify_sealed_receipts", lambda _t, _f, r: r)
    second = lane.review_pr(1810, 2)
    monkeypatch.setattr(lane, "run_reviewers", real)
    monkeypatch.setattr(lane, "_reverify_sealed_receipts", orig_reverify)
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


@pytest.mark.parametrize("policy,digest", [(None, "1" * 64), ("accept", "2" * 64)])
def test_reuse_records_admission(lane, env, monkeypatch, policy, digest):
    if policy is None:
        monkeypatch.delenv("SANDCASTLE_APPARMOR_ABSENT", raising=False)
    else:
        monkeypatch.setenv("SANDCASTLE_APPARMOR_ABSENT", policy)
    lane.review_pr(1810)
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["reused_from"]["admission"] == {"controller_code_head": git(lane.source, "rev-parse", "HEAD"),
                                                  "image_id": "sha256:" + "1" * 64, "isolation_contract": digest}


@pytest.mark.parametrize("change", ["policy", "legacy-receipt"])
def test_reuse_requires_both_receipts_to_match_isolation_contract(lane, env, monkeypatch, change):
    monkeypatch.setenv("SANDCASTLE_APPARMOR_ABSENT", "accept")
    first = lane.review_pr(1810)
    if change == "policy":
        monkeypatch.delenv("SANDCASTLE_APPARMOR_ABSENT")
    else:
        old = ReviewTarget(**first["target"])
        path = lane.state_root / "runs" / old.key / MODELS[1] / "receipt.json"
        receipt = json.loads(path.read_text())
        del receipt["isolation_contract"]
        path.write_text(json.dumps(receipt))
    _advance_main(lane, env)
    result = lane.review_pr(1810)
    assert result["verdict"] == "PASS"
    assert "reused_from" not in result
    assert [r["model"] for r in result["reviews"]] == list(MODELS)


@pytest.mark.parametrize("digest", [None, "a" * 63, "A" * 64, 10**63])
def test_deployment_admission_rejects_missing_or_invalid_isolation_contract(lane, monkeypatch, digest):
    head = git(lane.source, "rev-parse", "HEAD")
    output = {"controller_code_head": head, "image_id": "sha256:" + "1" * 64}
    if digest is not None:
        output["isolation_contract"] = digest
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps(output)))
    assert lane._deployment_admission(head) is None



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
    from dataclasses import asdict
    lane.review_pr(1810)
    second = lane.target(1810, 2)
    folder = lane.state_root / "runs" / second.key
    (folder / MODELS[0]).mkdir(parents=True)
    (folder / MODELS[0] / "prepare.json").write_text(json.dumps({"run_id": second.run_id}))
    (folder / "outcome.json").write_text(json.dumps({"run_id": second.run_id, "verdict": "FAILED", "state": "error",
        "target": asdict(second), "reviews": [{"model": MODELS[0], "verdict": "FAILED"}]}))
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
                           checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01,
                           preflight=lane.preflight)
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


def test_prompt_asks_for_standalone_diff_that_patch_read_accepts():
    """#1968：kimi 常把 diff 串在 cat/printf/--stat/--check 后面，守卫不认；提示词要求单独执行那条 diff，守卫不改。"""
    required = "git diff --no-ext-diff --no-textconv {merge_base} {head}"
    assert "先单独执行一条命令 " + required in module.PROMPT
    assert "不要接 &&、;、|" in module.PROMPT
    # 按提示词原样写出的那条命令（只替换两个 SHA，不加任何别的段）被现有 patch_read 判为读取
    command = required.format(merge_base=PR2018_MB, head=PR2018_HEAD)
    assert command in module.PROMPT.format(pr=1, base=PR2018_MB, merge_base=PR2018_MB, head=PR2018_HEAD, names="[]")
    patch = FrozenPatch.from_diff(PR2018_HEAD, PR2018_MB, PR2018_MB, PR2018_FROZEN)
    assert reads_candidate_patch(f"/bin/bash -lc '{command}'", PR2018_DIFF, patch)
    # 提示词劝阻的串接写法仍判未读（守卫行为不变）
    for chained in (f"cat SKILL.md && printf '--- DIFF ---' && {command}", f"{command} && git diff --check",
                    f"git diff --stat && {command}"):
        assert not reads_candidate_patch(f"/bin/bash -lc \"{chained}\"", PR2018_DIFF, patch)


# ---------------- Codex 额度耗尽时的临时组合（Kimi + Opus） ----------------

LEGACY_MODELS = ("kimi-k3.1-pro", "claude-opus-5-5")
LEGACY_POLICY = "external-pr-v1-kimi"


def _contract(policy, models):
    return "sha256:" + hashlib.sha256(json.dumps([policy, models, module.PROMPT]).encode()).hexdigest()


def _use_contract(monkeypatch, models, policy):
    monkeypatch.setattr(module, "MODELS", models)
    monkeypatch.setattr(module, "POLICY", policy)
    monkeypatch.setattr(module, "REVIEW_CONTRACT", _contract(policy, models))


def test_distinct_gpt_pair_has_its_own_contract():
    assert MODELS == ("gpt-6.2-sol", "gpt-6.2-astra")
    assert len(set(MODELS)) == len(MODELS) == 2
    assert module.POLICY == "external-pr-v2-gpt62" != LEGACY_POLICY
    assert module.REVIEW_CONTRACT == _contract(module.POLICY, MODELS) != _contract(LEGACY_POLICY, LEGACY_MODELS)


def test_pass_under_legacy_contract_is_not_reused_after_switch(lane, env, monkeypatch):
    current = (module.MODELS, module.POLICY)
    _use_contract(monkeypatch, LEGACY_MODELS, LEGACY_POLICY)
    first = lane.review_pr(1810)
    assert first["verdict"] == "PASS" and [r["model"] for r in first["reviews"]] == list(LEGACY_MODELS)
    _use_contract(monkeypatch, *current)
    with pytest.raises(IdentityError, match="旧合同占用"):
        lane.review_pr(1810, 1)
    assert lane.status(1810)[0]["outcome"] == first
    second = lane.review_pr(1810, 2)
    assert [(r["model"], r["verdict"]) for r in second["reviews"]] == [(m, "PASS") for m in MODELS]
    assert len({r["session_id"] for r in second["reviews"]}) == 2
    assert "reused_from" not in second
    assert second["target"]["policy_version"] == "external-pr-v2-gpt62"
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


@pytest.mark.parametrize("context", ["colima", None, "missing-context"])
def test_docker_context_at_admission_supervisor_and_recovery_boundaries(lane, monkeypatch, tmp_path, context):
    """真实子进程 + PATH 内假 docker：监督、准入、回收必须选同一 daemon，失败不改走默认。"""
    import os

    selected = context or "orbstack"
    if context is None:
        monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    else:
        monkeypatch.setenv("DOCKER_CONTEXT", context)
    for key in ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SECRET_TOKEN"):
        monkeypatch.setenv(key, "fixture-must-not-pass")
    monkeypatch.setenv("SANDCASTLE_MAIN_MODEL", "kimi-k3.1-pro")
    monkeypatch.setenv("SANDCASTLE_CONFIG_FILE", "/tmp/deploy-scheduler-config.json")
    monkeypatch.setenv("CLIPROXY_LOCAL_KEY", "fixture-worker-only")
    monkeypatch.setenv("SANDCASTLE_APPARMOR_ABSENT", "accept")  # #2071：部署的 AppArmor 策略声明要到准入与监督子进程
    trace = tmp_path / "docker-calls.jsonl"
    binary = tmp_path / "bin"
    binary.mkdir()
    docker = binary / "docker"
    docker.write_text(f'''#!{sys.executable}
import json, os, sys
assert os.environ.get("DOCKER_CONTEXT") == {context!r}
assert not any(k in os.environ for k in ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SECRET_TOKEN"))
assert os.environ.get("SANDCASTLE_MAIN_MODEL") == ("kimi-k3.1-pro" if sys.argv[1:] == ["info"] else None)
assert os.environ.get("SANDCASTLE_CONFIG_FILE") == ("/tmp/deploy-scheduler-config.json" if sys.argv[1:] == ["info"] else None)
with open({str(trace)!r}, "a") as f:
    f.write(json.dumps({{"context": os.environ.get("DOCKER_CONTEXT", "orbstack"), "args": sys.argv[1:]}}) + "\\n")
if os.environ.get("DOCKER_CONTEXT") == "missing-context":
    sys.exit(7)
if sys.argv[1:4] == ["ps", "-a", "-q"]:
    print("a" * 64)
''')
    docker.chmod(0o700)
    monkeypatch.setenv("PATH", str(binary) + os.pathsep + os.environ["PATH"])
    # 绕过 conftest 的空 docker 替身，但只能命中上面的假可执行文件。
    lane.docker = real_docker_cli
    worker = tmp_path / "supervisor.py"
    worker.write_text(f'''
import json, os, runpy, subprocess, sys
from pathlib import Path
assert os.environ.get("DOCKER_CONTEXT") == {context!r}
assert not any(k in os.environ for k in ("DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "SECRET_TOKEN"))
assert os.environ.get("SANDCASTLE_MAIN_MODEL") == "kimi-k3.1-pro"
assert os.environ.get("SANDCASTLE_CONFIG_FILE") == "/tmp/deploy-scheduler-config.json"
admission = sys.argv[1:] == ["--admission-only"]
assert os.environ.get("SANDCASTLE_APPARMOR_ABSENT") == "accept"
assert os.environ.get("CLIPROXY_LOCAL_KEY") == (None if admission else "fixture-worker-only")
if not admission:
    launch = json.loads((Path(sys.argv[-1]) / "launch.json").read_text())
    assert launch["model"] in {MODELS!r}
probe = subprocess.run(["docker", "info"], capture_output=True)
if probe.returncode:
    sys.exit(2)
runpy.run_path({lane.launcher[1]!r}, run_name="__main__")
''')
    lane.launcher = [sys.executable, str(worker)]
    controller = git(lane.source, "rev-parse", "HEAD")
    admission = lane._deployment_admission(controller)
    assert (admission is None) == (context == "missing-context")
    result = lane.review_pr(1810)
    assert result["verdict"] == ("FAILED" if context == "missing-context" else "PASS")
    volume = module.REVIEW_VOLUME_PREFIX + str(uuid.uuid4())
    assert lane.remove_review_volume(volume) == (context != "missing-context")
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert {row["context"] for row in rows} == {selected}
    assert sum(row["args"] == ["info"] for row in rows) == 3  # 准入一次、两位监督各一次
    destructive = [row for row in rows if row["args"][0] == "rm" or row["args"][:2] == ["volume", "rm"]]
    assert bool(destructive) == (context != "missing-context")
    if destructive:
        assert [row["args"] for row in destructive] == [["rm", "-f", "a" * 64], ["volume", "rm", volume]]


def test_new_attempt_and_reuse_fallback_enforce_preflight_fail_closed(lane, env, monkeypatch):
    """手动与自动入口共用的新 attempt 登记与复用退回路径均执行预检闸；失败不占 attempt、不发 pending。"""
    for key in (module.PREFLIGHT_ENV_CONTAINER, module.PREFLIGHT_ENV_CONTAINER_DIR,
                module.PREFLIGHT_ENV_PROXY_CONTEXT, module.PREFLIGHT_ENV_HOST_DIR):
        monkeypatch.delenv(key, raising=False)
    # 1. 缺可信代理收据配置时默认实路径失败闭合，不写 target.json，不发状态
    unconfigured = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                                  checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01)
    with pytest.raises(EffectPending, match="preflight-blocked"):
        unconfigured.review_pr(1810, 1)
    assert lane.status(1810) == [] and lane.gateway.sent == []

    # 2. 预检返回失败、旧未绑定路由或两路响应模型撞车，均阻断且不占 attempt
    bad_reports = [
        {"returncode": 2, "report": {"kind": "review-preflight", "is_review_result": False, "ready": False,
                                     "checks": [{"name": f"route:{MODELS[0]}", "ok": False}]}},
        {"kind": "review-preflight", "is_review_result": False, "ready": True, "checks": [
            {"name": f"route:{m}", "ok": True, "detail": {"expected": ["codex@chatgpt.com"], "actual": ["codex@chatgpt.com"]}}
            for m in MODELS
        ] + [
            {"name": f"roundtrip:{m}", "ok": True, "detail": {"returned_model": m}} for m in MODELS
        ]},
        {"kind": "review-preflight", "is_review_result": False, "ready": True, "checks": [
            {"name": f"route:{m}", "ok": True, "detail": {"expected": [f"codex:{m}@chatgpt.com"], "actual": [f"codex:{m}@chatgpt.com"], "sealed": True}}
            for m in MODELS
        ] + [
            {"name": f"seal:{m}", "ok": True, "detail": {"status": "sealed", "ok": True}} for m in MODELS
        ] + [
            {"name": f"roundtrip:{m}", "ok": True, "detail": {"returned_model": MODELS[0]}} for m in MODELS
        ]},
        # R32 (Astra P2): 普通连通性自检报告（缺少 seal:<model> 或 route.detail.sealed=true）不得充当正式预检
        {"kind": "review-preflight", "is_review_result": False, "ready": True, "image_id": "sha256:" + "1" * 64, "checks": [
            {"name": f"route:{m}", "ok": True, "detail": {"expected": [f"codex:{m}@chatgpt.com"], "actual": [f"codex:{m}@chatgpt.com"], "log_found": True}}
            for m in MODELS
        ] + [
            {"name": f"roundtrip:{m}", "ok": True, "detail": {"returned_model": m}} for m in MODELS
        ]},
        {"kind": "review-preflight", "is_review_result": False, "ready": True, "image_id": "sha256:" + "1" * 64, "checks": [
            {"name": f"route:{m}", "ok": True, "detail": {"expected": [f"codex:{m}@chatgpt.com"], "actual": [f"codex:{m}@chatgpt.com"], "sealed": False}}
            for m in MODELS
        ] + [
            {"name": f"seal:{m}", "ok": True, "detail": {"status": "sealed", "ok": True}} for m in MODELS
        ] + [
            {"name": f"roundtrip:{m}", "ok": True, "detail": {"returned_model": m}} for m in MODELS
        ]},
    ]
    for bad in bad_reports:
        lane.preflight = lambda _t, payload=bad: payload
        with pytest.raises(EffectPending, match="preflight-blocked"):
            lane.review_pr(1810, 1)
        assert lane.status(1810) == [] and lane.gateway.sent == []

    # 3. 预检参数与端点合同：固定对齐 codex-route.mts 容器代理地址，拒绝 REVIEW_PREFLIGHT_PROXY_URL 分叉，强制传已准入镜像 ID、容器探测与 worker-env
    codex_route_mts = (Path(__file__).resolve().parents[2] / "codex-route.mts").read_text()
    assert f'"{module.FORMAL_PROXY_URL}/v1"' in codex_route_mts
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER, "blackhole-cliproxy")
    monkeypatch.setenv(module.PREFLIGHT_ENV_PROXY_CONTEXT, "orbstack")
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER_DIR, "/tmp/cliproxy-preflight-receipts")
    monkeypatch.setenv("DOCKER_CONTEXT", "orbstack")
    admitted_image = "sha256:" + "a" * 64
    probe_target = unconfigured._frozen(load_target(lane.gateway, 1810), 1)
    cmd = unconfigured._preflight_args(probe_target, image=admitted_image)
    assert "--image" in cmd and cmd[cmd.index("--image") + 1] == admitted_image
    assert "--proxy-url" in cmd and cmd[cmd.index("--proxy-url") + 1] == module.FORMAL_PROXY_URL
    assert "--probe-in-container" in cmd
    assert "--credential-mode" in cmd and cmd[cmd.index("--credential-mode") + 1] == "worker-env"
    assert "--proxy-receipt-container" in cmd and "blackhole-cliproxy" in cmd
    assert "--proxy-docker-context" in cmd and "--review-docker-context" in cmd
    assert "--proxy-container-receipt-dir" in cmd and "/tmp/cliproxy-preflight-receipts" in cmd
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_URL", "http://127.0.0.1:9999")  # DevSkim: ignore DS162092 测试用的本地回环地址
    with pytest.raises(EffectPending, match="REVIEW_PREFLIGHT_PROXY_URL"):
        unconfigured._preflight_args(probe_target, image=admitted_image)
    monkeypatch.delenv("REVIEW_PREFLIGHT_PROXY_URL", raising=False)
    with pytest.raises(EffectPending, match="已准入镜像"):
        unconfigured._preflight_args(probe_target, image="sandcastle:newchanlun")

    # 4. 正常通过后：已有 attempt 续跑与有效 PASS 沿用不重跑预检；沿用退回双审时补跑预检
    calls = []
    lane.preflight = lambda t: (calls.append(t.head_sha), _fake_preflight_pass(t))[1]
    first = lane.review_pr(1810, 1)
    assert first["verdict"] == "PASS" and len(calls) == 1
    assert lane.review_pr(1810, 1)["run_id"] == first["run_id"] and len(calls) == 1
    _advance_main(lane, env)
    reused = lane.review_pr(1810, 1)
    assert reused["reused_from"]["run_id"] == first["run_id"] and len(calls) == 1

    # 沿用登记后在发布前来源失效：退回双审前强制再过预检
    _advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned is True and len(calls) == 1
    lane.preflight = lambda _t: {"returncode": 2, "report": {"kind": "review-preflight", "is_review_result": False,
                                                             "ready": False, "checks": [{"name": f"route:{MODELS[1]}", "ok": False}]}}
    monkeypatch.setattr(lane, "reusable", lambda _t: None)
    sent_before = list(lane.gateway.sent)
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.review_pr(1810, 1)
    assert lane.gateway.sent == sent_before


def test_validate_review_rejects_mismatched_session_model_or_provider(lane):
    """当前 GPT 合同下，session.jsonl 的 provider 或 turn_context.model 不符均判 FAILED。"""
    result = lane.review_pr(1810)
    target = ReviewTarget(**result["target"])
    folder = lane.state_root / "runs" / target.key / MODELS[1]
    launch = json.loads((folder / "launch.json").read_text())
    receipt = json.loads((folder / "receipt.json").read_text())
    session = receipt["session_id"]

    # 1. turn_context.model 实际为另一路模型
    (folder / "session.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": session, "model_provider": "cliproxy-local"}}) + "\n"
        + json.dumps({"type": "turn_context", "payload": {"model": MODELS[0]}}) + "\n"
    )
    assert validate_review(target, launch, receipt, folder, lane.source).verdict == "FAILED"

    # 2. session_meta.model_provider 非 cliproxy-local
    (folder / "session.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": session, "model_provider": "other-provider"}}) + "\n"
        + json.dumps({"type": "turn_context", "payload": {"model": MODELS[1]}}) + "\n"
    )
    assert validate_review(target, launch, receipt, folder, lane.source).verdict == "FAILED"

    # 3. 缺 turn_context
    (folder / "session.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": session, "model_provider": "cliproxy-local"}}) + "\n"
    )
    assert validate_review(target, launch, receipt, folder, lane.source).verdict == "FAILED"


def test_run_preflight_requires_admission_before_probe_and_filters_env(lane, monkeypatch, tmp_path):
    """正式预检先过部署准入取得不可变镜像 ID，再以过滤环境启动预检进程；准入未过时不启动任何探针容器。"""
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER, "blackhole-cliproxy")
    monkeypatch.setenv(module.PREFLIGHT_ENV_PROXY_CONTEXT, "orbstack")
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER_DIR, "/tmp/cliproxy-preflight-receipts")
    monkeypatch.setenv("DOCKER_CONTEXT", "orbstack")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/forbidden.sock")
    monkeypatch.setenv("DOCKER_CONFIG", "/tmp/forbidden-docker")
    monkeypatch.setenv("SECRET_TOKEN", "must-not-leak")
    monkeypatch.setenv("CLIPROXY_LOCAL_KEY", "fixture-worker-key")

    real_lane = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                               checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01)
    seen = []
    real_run = subprocess.run
    def spy_run(cmd, *args, **kwargs):
        if len(cmd) >= 3 and cmd[2] == str(module.PREFLIGHT_SCRIPT):
            seen.append({"cmd": cmd, "env": kwargs.get("env"), "cwd": kwargs.get("cwd")})
            return subprocess.CompletedProcess(cmd, 0, json.dumps(_fake_preflight_pass(None)), "")
        return real_run(cmd, *args, **kwargs)
    monkeypatch.setattr(module.subprocess, "run", spy_run)

    # 1. 部署准入失败时直接拦截，预检脚本不被调用（零容器启动）
    (lane.source / ".git" / "fake-admission").write_text("fail")
    with pytest.raises(EffectPending, match="部署 Docker 准入未通过"):
        real_lane.review_pr(1810, 1)
    assert seen == [] and lane.status(1810) == [] and lane.gateway.sent == []

    # 2. 部署准入通过时只传已准入 sha256 镜像 ID，并过滤掉 DOCKER_HOST/DOCKER_CONFIG/SECRET_TOKEN
    admitted = "sha256:" + "9" * 64
    (lane.source / ".git" / "fake-admission").write_text(admitted)
    target = real_lane.target(1810, 1)
    assert target.attempt == 1 and len(seen) == 1
    cmd = seen[0]["cmd"]
    env = seen[0]["env"]
    assert cmd[cmd.index("--image") + 1] == admitted
    assert cmd[cmd.index("--proxy-url") + 1] == module.FORMAL_PROXY_URL
    assert cmd[cmd.index("--review-seal-url") + 1] == module.FORMAL_SEAL_URL
    assert "--probe-in-container" in cmd
    assert cmd[cmd.index("--credential-mode") + 1] == "worker-env"
    assert env["DOCKER_CONTEXT"] == "orbstack" and env["CLIPROXY_LOCAL_KEY"] == "fixture-worker-key"
    assert not any(k in env for k in ("DOCKER_HOST", "DOCKER_CONFIG", "SECRET_TOKEN"))


def test_relative_sandcastle_config_file_resolves_identically_for_admission_and_supervisor(lane, monkeypatch, tmp_path):
    """相对 SANDCASTLE_CONFIG_FILE 在准入与监督进程收到同一个绝对路径，且两者均以 SOURCE_REPO 为 cwd。"""
    import os
    caller_dir = tmp_path / "caller-cwd"
    caller_dir.mkdir()
    monkeypatch.chdir(caller_dir)
    expected = os.path.abspath("rel/scheduler.json")
    monkeypatch.setenv("SANDCASTLE_CONFIG_FILE", "rel/scheduler.json")
    trace = tmp_path / "cfg-trace.jsonl"
    worker = tmp_path / "worker.py"
    worker.write_text(f"""import json, os, runpy, sys
with open({str(trace)!r}, "a") as f:
    f.write(json.dumps({{"admission": sys.argv[1:] == ["--admission-only"],
                         "cwd": os.getcwd(), "cfg": os.environ.get("SANDCASTLE_CONFIG_FILE")}}) + "\\n")
runpy.run_path({lane.launcher[1]!r}, run_name="__main__")
""")
    lane.launcher = [sys.executable, str(worker)]
    controller = git(lane.source, "rev-parse", "HEAD")
    assert lane._deployment_admission(controller) is not None
    assert lane.review_pr(1810)["verdict"] == "PASS"
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert len(rows) == 3 and sum(r["admission"] for r in rows) == 1
    assert {r["cfg"] for r in rows} == {expected}
    assert {Path(r["cwd"]).resolve() for r in rows} == {lane.source.resolve()}


def test_formal_session_upstream_receipt_enforced_and_fail_closed(lane, monkeypatch, tmp_path):
    """正式双审的 PASS/BLOCK 必须绑定代理侧未污染 cliproxy-review-v1 收据；缺失、污染、换模型或未配置均失败闭合。"""
    import time

    for key in (module.PREFLIGHT_ENV_CONTAINER, module.PREFLIGHT_ENV_CONTAINER_DIR,
                module.PREFLIGHT_ENV_PROXY_CONTEXT, module.PREFLIGHT_ENV_HOST_DIR):
        monkeypatch.delenv(key, raising=False)

    # 1. 未配置代理收据源时默认实路径失败闭合，绝不发布 success
    strict = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                            checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01,
                            preflight=_fake_preflight_pass)
    failed = strict.review_pr(1810, 1)
    assert failed["verdict"] == "FAILED" and lane.gateway.sent == ["pending", "error"]
    assert all("代理侧正式审阅收据" in r["reason"] for r in failed["reviews"])

    # 2. 配置宿主代理收据目录：写入私有权限的 cliproxy-review-v1 收据并经已认证封存替身确认后，正式双审通过
    receipt_root = tmp_path / "proxy-receipts"
    receipt_root.mkdir(mode=0o700)
    receipt_root.chmod(0o700)
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, str(receipt_root))
    monkeypatch.setattr(strict, "seal_receipt", lambda _lid, _sid: True)
    orig_validate = module.validate_review

    def write_proxy_receipt(target, launch, receipt, folder, source, *, route_override=None, tainted=False,
                            session_override=None, stale_output=False, bad_resp_id=False, requests_count=2,
                            drop_response_ids=False):
        outcome = orig_validate(target, launch, receipt, folder, source)
        launch_hdr = f"review-{launch['launch_id']}"
        rec_dir = receipt_root / launch_hdr
        rec_dir.mkdir(mode=0o700, exist_ok=True)
        rec_dir.chmod(0o700)
        now = time.time_ns()
        route = route_override.get(launch["model"], f"codex:{launch['model']}@chatgpt.com") if route_override else f"codex:{launch['model']}@chatgpt.com"
        final_text = None
        for line in (folder / "events.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            if ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                final_text = ev["item"].get("text")
        out_sha = hashlib.sha256(b"earlier-turn-tool-call").hexdigest() if stale_output else hashlib.sha256(
            (final_text or "").encode("utf-8")).hexdigest()
        rid = f"resp_{launch['model']}_final"
        raw_lines = [line for line in (folder / "session.jsonl").read_text().splitlines() if line.strip()]
        tur_indices = [i for i, line in enumerate(raw_lines) if json.loads(line).get("type") == "token_usage_record"]
        if drop_response_ids:
            kept = [line for i, line in enumerate(raw_lines) if i not in tur_indices]
        else:
            kept = list(raw_lines)
            if len(tur_indices) >= 2:
                kept[tur_indices[0]] = json.dumps({"type": "token_usage_record", "payload": {"response_id": f"resp_{launch['model']}_1"}})
                kept[tur_indices[-1]] = json.dumps({"type": "token_usage_record", "payload": {"response_id": rid}})
            else:
                kept = [line for i, line in enumerate(raw_lines) if i not in tur_indices]
                kept.append(json.dumps({"type": "token_usage_record", "payload": {"response_id": f"resp_{launch['model']}_1"}}))
                kept.append(json.dumps({"type": "token_usage_record", "payload": {"response_id": rid}}))
        (folder / "session.jsonl").write_text("\n".join(kept) + "\n")
        resp_sha = hashlib.sha256(b"resp_earlier").hexdigest() if bad_resp_id else hashlib.sha256(rid.encode("utf-8")).hexdigest()
        first_rid_sha = hashlib.sha256(f"resp_{launch['model']}_1".encode("utf-8")).hexdigest()
        rid_list = ([first_rid_sha, *[hashlib.sha256(f"resp_extra_{i}".encode("utf-8")).hexdigest()
                                      for i in range(max(0, requests_count - 2))], resp_sha]
                    if requests_count >= 2 else [resp_sha])
        payload = {
            "schema": "cliproxy-review-v1",
            "launch": launch_hdr,
            "session": session_override or outcome.session_id,
            "started_ns": now - 1_000_000,
            "finished_ns": now,
            "sealed_at_ns": 0 if tainted else now,
            "complete": not tainted,
            "sealed": not tainted,
            "tainted": tainted,
            "requests": requests_count,
            "routes": ["other"] if tainted else [route],
            "response_id_sha256s": [] if tainted else rid_list[:requests_count],
            "last_response_id_sha256": "" if tainted else resp_sha,
            "last_output_sha256": "" if tainted else out_sha,
        }
        rec_file = rec_dir / "receipt.json"
        rec_file.write_text(json.dumps(payload))
        rec_file.chmod(0o600)
        return outcome

    monkeypatch.setattr(module, "validate_review", write_proxy_receipt)
    passed = strict.review_pr(1810, 2)
    assert passed["verdict"] == "PASS" and lane.gateway.sent[-2:] == ["pending", "success"]

    # 3. 代理收据指向另一模型、已污染、仅有首轮陈旧输出摘要、末条 response_id 不符、轮数不足或 session.jsonl 缺 response_id，均判 FAILED
    monkeypatch.setattr(
        module, "validate_review",
        lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, route_override={MODELS[1]: f"codex:{MODELS[0]}@chatgpt.com"}),
    )
    swapped = strict.review_pr(1810, 3)
    assert swapped["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"

    monkeypatch.setattr(module, "validate_review", lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, stale_output=True))
    stale_out = strict.review_pr(1810, 5)
    assert stale_out["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"

    monkeypatch.setattr(module, "validate_review", lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, bad_resp_id=True))
    bad_rid = strict.review_pr(1810, 6)
    assert bad_rid["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"

    monkeypatch.setattr(module, "validate_review", lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, requests_count=1))
    short_reqs = strict.review_pr(1810, 7)
    assert short_reqs["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"

    monkeypatch.setattr(module, "validate_review", lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, drop_response_ids=True))
    missing_rids = strict.review_pr(1810, 8)
    assert missing_rids["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"
    assert all("response_id" in r["reason"] for r in missing_rids["reviews"])

    (lane.state_root / "runs" / "fake-mode").write_text("BLOCK")
    monkeypatch.setattr(module, "validate_review", lambda t, l, r, f, s: write_proxy_receipt(t, l, r, f, s, tainted=True))
    tainted_block = strict.review_pr(1810, 4)
    assert tainted_block["verdict"] == "FAILED" and lane.gateway.sent[-1] == "error"
    (lane.state_root / "runs" / "fake-mode").unlink()
    monkeypatch.setattr(module, "validate_review", orig_validate)

    # 4. recover_stale 同样复验代理侧正式收据：收据被删或污染时拒绝恢复
    stale_target = ReviewTarget(**passed["target"])
    stale_folder = lane.state_root / "runs" / stale_target.key
    saved_stale = {**passed, "verdict": "STALE", "reason": "simulated"}
    saved_stale.pop("publication", None)
    module._save(stale_folder / "outcome.json", saved_stale)
    launch0 = module._read(stale_folder / MODELS[0] / "launch.json")
    (receipt_root / f"review-{launch0['launch_id']}" / "receipt.json").unlink()
    refused = strict.review_pr(1810, 2)
    assert refused["verdict"] == "STALE" and "重验结果与原记录不一致" in refused.get("recovery_refused", "")

    # 5. 相对宿主收据路径在预检与正式收据读取两侧均明确拒绝
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, "relative/receipts")
    with pytest.raises(EffectPending, match="绝对路径"):
        strict._preflight_args(stale_target, image="sha256:" + "1" * 64)
    assert strict._read_session_receipt(MODELS[0], str(uuid.uuid4()), str(uuid.uuid4()), time.time() - 1) is None

    # 6. 容器收据后端：使用过滤后的 Docker 环境执行有界 --review-receipt 读取
    monkeypatch.delenv(module.PREFLIGHT_ENV_HOST_DIR, raising=False)
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER, "blackhole-cliproxy")
    monkeypatch.setenv(module.PREFLIGHT_ENV_PROXY_CONTEXT, "orbstack")
    monkeypatch.setenv(module.PREFLIGHT_ENV_CONTAINER_DIR, "/tmp/cliproxy-preflight-receipts")
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/forbidden.sock")
    monkeypatch.setenv("DOCKER_CONFIG", "/tmp/forbidden-cfg")
    monkeypatch.setenv("CLIPROXY_LOCAL_KEY", "must-not-leak")
    monkeypatch.setenv("DOCKER_CONTEXT", "wrong-ctx")
    lid = str(uuid.uuid4())
    sid = str(uuid.uuid4())
    out_hash = "a" * 64
    rid_hash = "b" * 64
    captured = []
    real_run = subprocess.run

    def spy_container_run(cmd, *args, **kwargs):
        if cmd[:4] == ["docker", "--context", "orbstack", "exec"]:
            captured.append({"cmd": cmd, "env": kwargs.get("env")})
            return subprocess.CompletedProcess(
                cmd, 0,
                json.dumps({"launch": f"review-{lid}", "session": sid, "complete_stable": True, "sealed": True,
                            "routes": [f"codex:{MODELS[0]}@chatgpt.com"], "requests": 3,
                            "response_id_sha256s": ["1" * 64, "2" * 64, rid_hash],
                            "last_response_id_sha256": rid_hash, "last_output_sha256": out_hash}).encode(),
                b"",
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(module.subprocess, "run", spy_container_run)
    got = strict._read_session_receipt(MODELS[0], lid, sid, time.time() - 1)
    assert got == {"routes": [f"codex:{MODELS[0]}@chatgpt.com"], "requests": 3, "sealed": True,
                   "response_id_sha256s": ["1" * 64, "2" * 64, rid_hash],
                   "last_response_id_sha256": rid_hash, "last_output_sha256": out_hash} and len(captured) == 1
    assert "--review-receipt" in captured[0]["cmd"]
    assert not any(k in captured[0]["env"] for k in ("DOCKER_HOST", "DOCKER_CONFIG", "CLIPROXY_LOCAL_KEY", "DOCKER_CONTEXT"))


def test_preflight_admitted_image_id_is_frozen_into_target_launch_and_validated(lane):
    """预检准入取得的不可变镜像 ID 冻结进 target.json 与 launch.json；回执镜像与冻结值不符时判 FAILED。"""
    admitted = "sha256:" + "1" * 64
    lane.preflight = lambda t: {"returncode": 0, "report": _fake_preflight_pass(t), "image_id": admitted}
    result = lane.review_pr(1810, 1)
    assert result["verdict"] == "PASS"
    target = ReviewTarget(**result["target"])
    assert target.admitted_image_id == admitted
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = module._read(worker / "launch.json")
    receipt = module._read(worker / "receipt.json")
    assert launch["image_id"] == admitted
    assert validate_review(target, launch, {**receipt, "image_id": "sha256:" + "2" * 64}, worker, lane.source).verdict == "FAILED"


def test_registered_at_ns_is_strictly_monotonic_under_pr_lock_across_slow_preflight(lane, monkeypatch):
    """两路并发 attempt 即使先冻结的慢预检晚于后冻结的快预检完成，锁内登记的 registered_at_ns 仍按实际登记顺序严格单调递增。"""
    import threading

    entered_slow = threading.Event()
    release_slow = threading.Event()
    calls = {"n": 0}

    def slow_first(t):
        calls["n"] += 1
        if t.attempt == 1:
            entered_slow.set()
            assert release_slow.wait(5)
        return _fake_preflight_pass(t)

    lane.preflight = slow_first
    results = {}

    def register(attempt):
        results[attempt] = lane.target(1810, attempt)

    t1 = threading.Thread(target=register, args=(1,))
    t1.start()
    assert entered_slow.wait(5)
    t2 = threading.Thread(target=register, args=(2,))
    t2.start()
    t2.join(timeout=5)
    assert 2 in results
    release_slow.set()
    t1.join(timeout=5)
    assert 1 in results
    assert results[1].registered_at_ns > results[2].registered_at_ns


def test_reuse_fallback_persists_preflight_admitted_marker_and_skips_re_preflight_on_resume(lane, env, monkeypatch):
    """沿用登记后退回双审时，预检通过即落盘 preflight-admitted.json；若在发 pending 或建工蜂目录前中断，续跑不再重复预检。"""
    first = lane.review_pr(1810, 1)
    assert first["verdict"] == "PASS"
    _advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned is True
    folder = lane.state_root / "runs" / target.key
    monkeypatch.setattr(lane, "reusable", lambda _t: None)

    preflight_calls = []
    lane.preflight = lambda t: (preflight_calls.append(t.run_id), _fake_preflight_pass(t))[1]

    # 第一次：预检通过并写入 preflight-admitted.json，但在发 pending 前模拟中断
    real_publish = StatusPublisher.publish

    def interrupt_before_pending(self, state, *a, **kw):
        if state == "pending" and len(preflight_calls) == 1:
            raise EffectPending("simulated crash before pending")
        return real_publish(self, state, *a, **kw)

    monkeypatch.setattr(StatusPublisher, "publish", interrupt_before_pending)
    with pytest.raises(EffectPending, match="simulated crash before pending"):
        lane.review_pr(1810, 1)
    assert len(preflight_calls) == 1
    assert (folder / module.PREFLIGHT_ADMITTED_FILE).is_file()
    assert not (folder / "effects" / "status-pending.json").exists()

    # 第二次续跑：看到 preflight-admitted.json，不重复跑预检，直接完成双审
    monkeypatch.setattr(StatusPublisher, "publish", real_publish)
    resumed = lane.review_pr(1810, 1)
    assert resumed["verdict"] == "PASS" and len(preflight_calls) == 1


def test_passing_preflight_always_records_non_rate_limited_event(lane):
    """预检通过即使在 preflight-rate-limits.json 尚不存在时也写入 rate_limited=False，防止夹在正式 429 与后续预检 429 之间误判连续限流。"""
    path = lane.state_root / module.PREFLIGHT_RATE_LIMIT_FILE
    assert not path.exists()
    target = lane.target(1810, 1)
    assert target.attempt == 1
    assert path.is_file()
    events = json.loads(path.read_text())["events"]
    assert len(events) == 1 and events[0]["rate_limited"] is False


def test_corrupt_preflight_admitted_marker_on_reuse_fallback_fails_closed(lane, env, monkeypatch):
    """沿用退回双审时，损坏、run_id 失配或缺有效 image_id 的 preflight-admitted.json 必须失败闭合，绝不能当作无镜像约束放行。"""
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    _advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned is True
    folder = lane.state_root / "runs" / target.key
    monkeypatch.setattr(lane, "reusable", lambda _t: None)
    marker = folder / module.PREFLIGHT_ADMITTED_FILE

    for bad_content in (
        "{not-json",
        json.dumps({"run_id": "wrong-run-id", "image_id": "sha256:" + "1" * 64}),
        json.dumps({"run_id": target.run_id, "image_id": ""}),
    ):
        marker.write_text(bad_content)
        with pytest.raises(IdentityError, match="预检准入记录"):
            lane.review_pr(1810, 1)
    assert not any((folder / model).exists() for model in MODELS)


def test_real_codex_0169_redacted_session_contract_and_empty_rid_rejection(lane, tmp_path, monkeypatch):
    """基于已部署 sandcastle:newchanlun 镜像（codex-cli 0.169.0）脱敏真实日志夹具验证代理收据绑定；
    末条 token_usage_record 缺 response_id 时必须判 FAILED，绝不回退到前轮非空 response_id。"""
    import time

    fixture = json.loads((Path(__file__).parent / "fixtures" / "codex-session-receipt-contract.json").read_text())
    result = lane.review_pr(1810, 1)
    target = ReviewTarget(**result["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = module._read(worker / "launch.json")
    receipt = module._read(worker / "receipt.json")
    session_id = fixture["session_id"]
    final_text = json.dumps(fixture["final_result"], ensure_ascii=False)
    diff_cmd = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha}"
    patch = git(lane.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha)
    events = [
        {"type": "thread.started", "thread_id": session_id},
        {"type": "item.completed", "item": {"type": "command_execution", "command": f"/bin/bash -lc '{diff_cmd}'",
                                            "aggregated_output": patch, "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": final_text}},
        {"type": "turn.completed"},
    ]
    def _materialize_records(records: list[dict], *, cmd_override: str | None = None,
                             out_override: str | None = None) -> list[dict]:
        out: list[dict] = []
        for rec in records:
            item = json.loads(json.dumps(rec))
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            if item.get("type") == "response_item" and payload.get("type") == "function_call":
                payload["arguments"] = json.dumps({"cmd": diff_cmd if cmd_override is None else cmd_override})
            elif item.get("type") == "response_item" and payload.get("type") == "function_call_output":
                payload["output"] = (f"Process exited with code 0\nOutput:\n{patch}"
                                     if out_override is None else out_override)
            out.append(item)
        return out

    matched_records = _materialize_records(fixture["session_records"])
    (worker / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n")
    (worker / "session.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in matched_records) + "\n"
    )
    updated_receipt = {**receipt, "session_id": session_id, "result": fixture["final_result"],
                       "observed_provider": fixture["provider"], "observed_model": fixture["model"]}
    receipt_root = tmp_path / "proxy-receipts"
    receipt_root.mkdir(parents=True, mode=0o700)
    receipt_root.chmod(0o700)
    launch_hdr = f"review-{launch['launch_id']}"
    rec_dir = receipt_root / launch_hdr
    rec_dir.mkdir(parents=True, mode=0o700)
    rec_dir.chmod(0o700)
    now = time.time_ns()
    fixture_rid_shas = [hashlib.sha256(r.encode("utf-8")).hexdigest() for r in fixture["response_ids"]]
    rec_file = rec_dir / "receipt.json"
    rec_file.write_text(json.dumps({
        "schema": "cliproxy-review-v1",
        "launch": launch_hdr,
        "session": session_id,
        "started_ns": now - 1_000_000,
        "finished_ns": now,
        "sealed_at_ns": now,
        "complete": True,
        "sealed": True,
        "tainted": False,
        "requests": len(fixture_rid_shas),
        "routes": [f"codex:{fixture['model']}@chatgpt.com"],
        "response_id_sha256s": fixture_rid_shas,
        "last_response_id_sha256": fixture_rid_shas[-1],
        "last_output_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
    }))
    rec_file.chmod(0o600)
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, str(receipt_root))
    strict = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                            checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01,
                            preflight=_fake_preflight_pass)
    outcome = validate_review(target, launch, updated_receipt, worker, lane.source)
    assert outcome.verdict == "PASS"
    # R20（Astra P1）：即使宿主目录收据文件自报 sealed=true，若未获已认证封存端点确认，必须失败闭合拒收
    monkeypatch.setattr(strict, "seal_receipt", lambda _lid, _sid: False)
    assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome).verdict == "FAILED"
    monkeypatch.setattr(strict, "seal_receipt", lambda _lid, _sid: True)
    verified = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
    assert verified.verdict == "PASS"

    # R16：仅工具调用总数相等不够——session.jsonl 命令与 events.jsonl 错配、或输出未含候选补丁/退出码非零，均判 FAILED
    for bad_records in (
        _materialize_records(fixture["session_records"], cmd_override="git diff --no-ext-diff --no-textconv"),
        _materialize_records(fixture["session_records"], out_override="Process exited with code 0\nOutput:\nnot-the-patch"),
        _materialize_records(fixture["session_records"], out_override=f"Process exited with code 1\nOutput:\n{patch}"),
    ):
        (worker / "session.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in bad_records) + "\n")
        assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome).verdict == "FAILED"
    (worker / "session.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in matched_records) + "\n")

    # 中间轮 response_id 被替换（即使总轮数与末条 response_id/终答摘要完全一致），必须判 FAILED
    if len(fixture_rid_shas) >= 2:
        tampered = json.loads((rec_dir / "receipt.json").read_text())
        tampered["response_id_sha256s"] = ["f" * 64, *fixture_rid_shas[1:]]
        (rec_dir / "receipt.json").write_text(json.dumps(tampered))
        mid_rejected = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
        assert mid_rejected.verdict == "FAILED"
        # 允许代理侧多记一次重试轮（session.jsonl 仍为严格有序子序列且末条一致）
        with_retry = json.loads((rec_dir / "receipt.json").read_text())
        with_retry["response_id_sha256s"] = ["e" * 64, *fixture_rid_shas]
        with_retry["requests"] = len(with_retry["response_id_sha256s"])
        (rec_dir / "receipt.json").write_text(json.dumps(with_retry))
        assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome).verdict == "PASS"
        # 恢复原始收据继续后续用例
        with_retry["response_id_sha256s"] = fixture_rid_shas
        with_retry["requests"] = len(fixture_rid_shas)
        (rec_dir / "receipt.json").write_text(json.dumps(with_retry))

    # 未封存收据（sealed=False，即使所有摘要匹配）也必须拒绝，绝不采信
    unsealed_payload = json.loads((rec_dir / "receipt.json").read_text())
    unsealed_payload["sealed"] = False
    (rec_dir / "receipt.json").write_text(json.dumps(unsealed_payload))
    monkeypatch.setattr(strict, "seal_receipt", lambda _lid, _sid: False)
    unsealed = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
    assert unsealed.verdict == "FAILED" and "未封存" in unsealed.reason

    # 恢复已封存收据，再追加一条空 response_id 的末轮 token_usage_record：必须拒绝，绝不能回退采信前一条非空 response_id
    unsealed_payload["sealed"] = True
    (rec_dir / "receipt.json").write_text(json.dumps(unsealed_payload))
    monkeypatch.setattr(strict, "seal_receipt", lambda _lid, _sid: True)
    with open(worker / "session.jsonl", "a") as sf:
        sf.write(json.dumps({"type": "token_usage_record", "payload": {"response_id": ""}}) + "\n")
    rejected = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
    assert rejected.verdict == "FAILED" and "response_id" in rejected.reason

    # R15：工具调用轮整条 token_usage_record 缺失（仅保留终答轮）：即使终答与代理子序列匹配，也必须判 FAILED
    records_missing_tool_tur = [
        r for r in matched_records
        if not (r.get("type") == "token_usage_record"
                and (r.get("payload") or {}).get("response_id") == fixture["response_ids"][0])
    ]
    (worker / "session.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records_missing_tool_tur) + "\n"
    )
    missing_tool_tur = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
    assert missing_tool_tur.verdict == "FAILED" and "闭合" in missing_tool_tur.reason

    # R15：session.jsonl 去掉工具调用 response_item 与其 token_usage_record，仅留终答轮，而 events.jsonl 仍有 command_execution：必须判 FAILED
    records_missing_fc = [
        r for r in records_missing_tool_tur
        if not (r.get("type") == "response_item"
                and (r.get("payload") or {}).get("type") in ("function_call", "function_call_output"))
    ]
    (worker / "session.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records_missing_fc) + "\n"
    )
    missing_fc = strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome)
    assert missing_fc.verdict == "FAILED" and "response_item" in missing_fc.reason


def test_publish_and_resume_reverify_sealed_receipts_and_reject_post_first_taint(lane):
    """首位 reviewer 通过后，若在汇总发布前或未发布结果续发前其代理收据变为污染/未封存，
    _publish_final 与 _resume_publication 均不得凭缓存 PASS 发布 success，必须降级为 FAILED/error。"""
    tainted_first = {"flag": False}
    orig_receipt = lane.session_receipt

    def dynamic_receipt(model, launch_id, session_id, since):
        if model == MODELS[0] and tainted_first["flag"]:
            return None
        return orig_receipt(model, launch_id, session_id, since)

    lane.session_receipt = dynamic_receipt

    # 1. 首次发布前：首位完成时有效，但在汇总写 outcome 后、发布前被污染，最终发布必须降级为 error
    orig_reverify = lane._reverify_sealed_receipts

    def taint_before_publish(target, folder, result):
        tainted_first["flag"] = True
        return orig_reverify(target, folder, result)

    lane._reverify_sealed_receipts = taint_before_publish
    res = lane.review_pr(1810, 1)
    assert res["verdict"] == "FAILED" and res["state"] == "error"
    assert lane.gateway.sent[-1] == "error"

    # 2. 未发布结果续发（_resume_publication）：先写一份未发布的 PASS outcome，再污染首位收据后续跑，绝不发布 success
    tainted_first["flag"] = False
    lane._reverify_sealed_receipts = orig_reverify
    passed = lane.review_pr(1810, 2)
    assert passed["verdict"] == "PASS"
    target2 = ReviewTarget(**passed["target"])
    folder2 = lane.state_root / "runs" / target2.key
    unpublished = {k: v for k, v in passed.items() if k != "publication"}
    module._save(folder2 / "outcome.json", unpublished)
    (folder2 / "effects" / "status-success.json").unlink()
    tainted_first["flag"] = True
    resumed = lane.review_pr(1810, 2)
    assert resumed["verdict"] == "FAILED" and resumed["state"] == "error"
    assert lane.gateway.sent[-1] == "error"


def test_target_exclusive_attempt_lock_prevents_concurrent_duplicate_preflight_and_checks_expected_base(lane):
    """同一 attempt 的并发登记先持排他锁再执行付费预检（第二路立抛 EffectPending 且零重复预检）；
    expect_base / expect_head 失配时在登记与预检前直接抛 TargetDrifted。"""
    import threading

    with pytest.raises(module.TargetDrifted, match="base-moved-not-reviewed"):
        lane.target(1810, 1, expect_head=lane.gateway.pr["head"]["sha"], expect_base="0" * 40)
    with pytest.raises(module.TargetDrifted, match="head-moved-not-reviewed"):
        lane.target(1810, 1, expect_head="0" * 40, expect_base=lane.gateway.pr["base"]["sha"])

    entered = threading.Event()
    release = threading.Event()
    preflight_calls = {"n": 0}

    def slow_preflight(t):
        preflight_calls["n"] += 1
        entered.set()
        assert release.wait(5)
        return _fake_preflight_pass(t)

    lane.preflight = slow_preflight
    out1 = {}
    err2 = {}

    def first():
        out1["target"] = lane.target(1810, 1)

    def second():
        try:
            lane.target(1810, 1)
        except Exception as exc:
            err2["exc"] = exc

    t1 = threading.Thread(target=first)
    t1.start()
    assert entered.wait(5)
    t2 = threading.Thread(target=second)
    t2.start()
    t2.join(timeout=5)
    assert isinstance(err2.get("exc"), EffectPending)
    release.set()
    t1.join(timeout=5)
    assert "target" in out1 and preflight_calls["n"] == 1


def test_host_dir_fifo_receipt_fails_closed_without_hanging(lane, tmp_path, monkeypatch):
    """宿主目录快速路径复用有界读取器：收据路径意外为 FIFO 时立返 FAILED，绝不阻塞等写端。"""
    import os
    import time

    passed = lane.review_pr(1810, 1)
    target = ReviewTarget(**passed["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = module._read(worker / "launch.json")
    receipt = module._read(worker / "receipt.json")
    outcome = validate_review(target, launch, receipt, worker, lane.source)
    assert outcome.verdict == "PASS"

    fifo_root = tmp_path / "fifo-receipts"
    launch_dir = fifo_root / f"review-{launch['launch_id']}"
    launch_dir.mkdir(parents=True, mode=0o700)
    os.mkfifo(launch_dir / "receipt.json", 0o600)
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, str(fifo_root))
    monkeypatch.delenv(module.PREFLIGHT_ENV_CONTAINER, raising=False)
    monkeypatch.delenv("CLIPROXY_LOCAL_KEY", raising=False)
    strict = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                            checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01,
                            preflight=_fake_preflight_pass)
    started = time.monotonic()
    res = strict._verify_session_receipt(target, launch, receipt, worker, outcome)
    assert res.verdict == "FAILED" and time.monotonic() - started < 2.0


def test_slow_preflight_rechecks_live_target_under_pr_lock_and_rereview_intent_blocks_old_pass(lane, env):
    """1. 慢预检期间 base 漂移后，锁内写入 target.json 前复核实时目标直接抛 TargetDrifted，绝不给旧 base 分配更晚 registered_at_ns；
    2. A1 已 PASS 后手动 A2 预检失败退出：不占 attempt，但持久化的重审意图阻塞旧 PASS 自动合入直至 A2 真正登记。"""
    # 1. 慢预检期间 base 移动
    old_base = lane.gateway.pr["base"]["sha"]
    head = lane.gateway.pr["head"]["sha"]
    parent = git(env.source, "rev-parse", f"{head}~1")
    assert parent != old_base

    def move_base_during_preflight(t):
        lane.gateway.pr["base"]["sha"] = parent
        return _fake_preflight_pass(t)

    lane.preflight = move_base_during_preflight
    with pytest.raises(module.TargetDrifted, match="base-moved-not-reviewed"):
        lane.target(1810, 1)
    assert lane.status(1810) == []

    # 2. A1 PASS -> A2 预检失败 -> has_pending_rereview_intent 为 True 且 A2 未写 target.json -> A2 成功后解除意图
    lane.gateway.pr["base"]["sha"] = old_base
    lane.preflight = _fake_preflight_pass
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    assert lane.has_pending_rereview_intent(1810, head, old_base) is False

    lane.preflight = lambda _t: {"returncode": 2, "report": None, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    assert len(lane.status(1810)) == 1
    assert lane.has_pending_rereview_intent(1810, head, old_base) is True

    lane.preflight = _fake_preflight_pass
    t2 = lane.target(1810, 2)
    assert t2.attempt == 2 and lane.has_pending_rereview_intent(1810, head, old_base) is False


def test_pending_rereview_intent_blocks_pass_reuse_on_rebased_same_patch_and_seal_enforces_wall_timeout(
        lane, env, tmp_path, monkeypatch):
    """R15：1. 旧 PASS 存在未承接重审意图时，即使 PR 推进到同 patch_id 新 head 也不得沿用旧 PASS；
    2. _seal_session_receipt 面对慢滴响应在总墙钟期限内强杀子进程并返回 False，绝不拖住 reviewer 线程。"""
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    # 1. A1 PASS -> A2 预检失败留下重审意图（未写 target.json）-> main 前进并追平到同 patch_id 新 head -> 不得沿用 A1 PASS
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    lane.preflight = lambda _t: {"returncode": 2, "report": None, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    _advance_main(lane, env)
    lane.preflight = _fake_preflight_pass
    assert lane.would_reuse(load_target(lane.gateway, 1810)) is False
    rebased_target = lane.target(1810, 1)
    assert rebased_target.reuse_planned is False
    rebased_res = lane.review_pr(1810, 1)
    assert rebased_res["verdict"] == "PASS" and "reused_from" not in rebased_res

    # 2. 慢滴封存服务端（每 0.25s 吐 1 字节，持续远超 0.8s 预算）：_seal_session_receipt 必须在总墙钟上限内强杀并返回 False
    stop_drip = threading.Event()

    class SlowDripSealHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1024")
            self.end_headers()
            try:
                for _ in range(40):
                    if stop_drip.is_set():
                        break
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.25)
            except OSError:
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), SlowDripSealHandler)  # DevSkim: ignore DS162092 测试用的本地回环地址
    srv_url = f"http://127.0.0.1:{srv.server_address[1]}/v1/review-receipts/seal"  # DevSkim: ignore DS162092 测试用的本地回环地址
    t_srv = threading.Thread(target=srv.serve_forever, daemon=True)
    t_srv.start()
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, str(tmp_path))
    monkeypatch.delenv(module.PREFLIGHT_ENV_CONTAINER, raising=False)
    monkeypatch.setenv("CLIPROXY_LOCAL_KEY", "test-seal-key")
    try:
        started = time.monotonic()
        ok = lane._seal_session_receipt(
            "11111111-2222-4333-8444-555555555559",
            "019d0000-0000-7000-8000-000000000559",
            timeout=0.8,
            seal_url=srv_url,
        )
        elapsed = time.monotonic() - started
        assert ok is False and elapsed < 2.0
    finally:
        stop_drip.set()
        srv.shutdown()
        srv.server_close()


def test_session_receipt_accepts_write_stdin_continuation_and_parallel_tool_calls(lane, tmp_path, monkeypatch):
    """R17（Sol+Astra P1）：合法的 write_stdin 续读（含切分输出续读补丁）与 multi_tool_use.parallel 并行工具包装
    不得被误判为非法 shell 命令；缺失或伪造补丁读取命令仍判 FAILED。"""
    import time

    result = lane.review_pr(1810, 1)
    target = ReviewTarget(**result["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = module._read(worker / "launch.json")
    receipt = module._read(worker / "receipt.json")
    session_id = "01a204f8-2a11-7720-baca-0bff89db9901"
    diff_cmd = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha}"
    patch = git(lane.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha)
    final_obj = {"status": "completed", "summary": "VERDICT: PASS\n含续读与并行工具调用回归通过。",
                 "findings": [], "validation": ["write_stdin + parallel"]}
    final_text = json.dumps(final_obj, ensure_ascii=False)
    updated_receipt = {**receipt, "session_id": session_id, "result": final_obj,
                       "observed_provider": "cliproxy-local", "observed_model": MODELS[0]}

    receipt_root = tmp_path / "proxy-receipts"
    receipt_root.mkdir(parents=True, mode=0o700)
    receipt_root.chmod(0o700)
    launch_hdr = f"review-{launch['launch_id']}"
    rec_dir = receipt_root / launch_hdr
    rec_dir.mkdir(parents=True, mode=0o700)
    rec_dir.chmod(0o700)
    monkeypatch.setenv(module.PREFLIGHT_ENV_HOST_DIR, str(receipt_root))
    strict = ExternalReview(lane.gateway, source=lane.source, state_root=lane.state_root,
                            checkout_root=lane.checkout_root, launcher=lane.launcher, poll_seconds=0.01,
                            preflight=_fake_preflight_pass, seal_receipt=lambda _lid, _sid: True)

    def _write_proxy(rids: list[str]) -> None:
        now = time.time_ns()
        shas = [hashlib.sha256(r.encode("utf-8")).hexdigest() for r in rids]
        rf = rec_dir / "receipt.json"
        rf.write_text(json.dumps({
            "schema": "cliproxy-review-v1",
            "launch": launch_hdr,
            "session": session_id,
            "started_ns": now - 1_000_000,
            "finished_ns": now,
            "sealed_at_ns": now,
            "complete": True,
            "sealed": True,
            "tainted": False,
            "requests": len(shas),
            "routes": [f"codex:{MODELS[0]}@chatgpt.com"],
            "response_id_sha256s": shas,
            "last_response_id_sha256": shas[-1],
            "last_output_sha256": hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        }))
        rf.chmod(0o600)

    # 1. exec_command 启动 git diff 后由 write_stdin(session_id=42) 续读补丁输出，两轮均由 token_usage_record 闭合
    events_stdin = [
        {"type": "thread.started", "thread_id": session_id},
        {"type": "item.completed", "item": {"type": "command_execution", "command": f"/bin/bash -lc '{diff_cmd}'",
                                            "aggregated_output": patch, "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": final_text}},
        {"type": "turn.completed"},
    ]
    rids_stdin = ["resp_r17_exec_1", "resp_r17_stdin_2", "resp_r17_final_3"]
    sess_stdin = [
        {"type": "session_meta", "payload": {"id": session_id, "model_provider": "cliproxy-local"}},
        {"type": "turn_context", "payload": {"model": MODELS[0]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c1",
                                              "arguments": json.dumps({"cmd": diff_cmd})}},
        {"type": "token_usage_record", "payload": {"response_id": rids_stdin[0]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                                              "output": "Chunk ID: a1\nProcess running with session ID 42\nOutput:\n"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "write_stdin", "call_id": "c2",
                                              "arguments": json.dumps({"session_id": 42, "chars": ""})}},
        {"type": "token_usage_record", "payload": {"response_id": rids_stdin[1]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c2",
                                              "output": f"Process exited with code 0\nOutput:\n{patch}"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": final_text}]}},
        {"type": "token_usage_record", "payload": {"response_id": rids_stdin[2]}},
    ]
    (worker / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events_stdin) + "\n")
    (worker / "session.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sess_stdin) + "\n")
    _write_proxy(rids_stdin)
    outcome = validate_review(target, launch, updated_receipt, worker, lane.source)
    assert outcome.verdict == "PASS"
    assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome).verdict == "PASS"

    # 2. multi_tool_use.parallel 包装两条 exec_command（补丁读取 + git status），同样逐项对齐并通过
    events_par = [
        {"type": "thread.started", "thread_id": session_id},
        {"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/bash -lc 'git status --short'",
                                            "aggregated_output": "", "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": f"/bin/bash -lc '{diff_cmd}'",
                                            "aggregated_output": patch, "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": final_text}},
        {"type": "turn.completed"},
    ]
    rids_par = ["resp_r17_par_1", "resp_r17_par_final_2"]
    sess_par = [
        {"type": "session_meta", "payload": {"id": session_id, "model_provider": "cliproxy-local"}},
        {"type": "turn_context", "payload": {"model": MODELS[0]}},
        {"type": "response_item", "payload": {
            "type": "function_call", "name": "multi_tool_use.parallel", "call_id": "p1",
            "arguments": json.dumps({"tool_uses": [
                {"recipient_name": "functions.exec_command", "parameters": {"cmd": diff_cmd}},
                {"recipient_name": "functions.exec_command", "parameters": {"cmd": "git status --short"}},
            ]}),
        }},
        {"type": "token_usage_record", "payload": {"response_id": rids_par[0]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "p1",
                                              "output": f"Process exited with code 0\nOutput:\n{patch}"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": final_text}]}},
        {"type": "token_usage_record", "payload": {"response_id": rids_par[1]}},
    ]
    (worker / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events_par) + "\n")
    (worker / "session.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sess_par) + "\n")
    _write_proxy(rids_par)
    outcome_par = validate_review(target, launch, updated_receipt, worker, lane.source)
    assert outcome_par.verdict == "PASS"
    assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome_par).verdict == "PASS"

    # 3. R18（Sol P2 + Astra P2）：diff --git 文件头跨 exec_command 与 write_stdin 两个带元数据头输出块无缝重组，
    #    且审查员显式执行 `bash -c 'git status --short'` 时不被剥离两层 shell 包装。
    diff_pos = patch.find("diff --git ")
    assert diff_pos >= 0
    split_at = diff_pos + 7
    part1, part2 = patch[:split_at], patch[split_at:]
    explicit_bash = "bash -c 'git status --short'"
    events_r18 = [
        {"type": "thread.started", "thread_id": session_id},
        {"type": "item.completed", "item": {"type": "command_execution", "command": f"/bin/bash -lc '{diff_cmd}'",
                                            "aggregated_output": patch, "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "command_execution", "command": f'/bin/bash -lc "{explicit_bash}"',
                                            "aggregated_output": "", "status": "completed", "exit_code": 0}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": final_text}},
        {"type": "turn.completed"},
    ]
    rids_r18 = ["resp_r18_exec_1", "resp_r18_stdin_2", "resp_r18_bash_3", "resp_r18_final_4"]
    sess_r18 = [
        {"type": "session_meta", "payload": {"id": session_id, "model_provider": "cliproxy-local"}},
        {"type": "turn_context", "payload": {"model": MODELS[0]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "s1",
                                              "arguments": json.dumps({"cmd": diff_cmd})}},
        {"type": "token_usage_record", "payload": {"response_id": rids_r18[0]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "s1",
                                              "output": f"Chunk ID: c1\nProcess running with session ID 99\nOutput:\n{part1}"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "write_stdin", "call_id": "s2",
                                              "arguments": json.dumps({"session_id": 99, "chars": ""})}},
        {"type": "token_usage_record", "payload": {"response_id": rids_r18[1]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "s2",
                                              "output": f"Chunk ID: c2\nProcess exited with code 0\nOutput:\n{part2}"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "s3",
                                              "arguments": json.dumps({"cmd": explicit_bash})}},
        {"type": "token_usage_record", "payload": {"response_id": rids_r18[2]}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "s3",
                                              "output": "Chunk ID: c3\nProcess exited with code 0\nOutput:\n"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                              "content": [{"type": "output_text", "text": final_text}]}},
        {"type": "token_usage_record", "payload": {"response_id": rids_r18[3]}},
    ]
    (worker / "events.jsonl").write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events_r18) + "\n")
    (worker / "session.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in sess_r18) + "\n")
    _write_proxy(rids_r18)
    outcome_r18 = validate_review(target, launch, updated_receipt, worker, lane.source)
    assert outcome_r18.verdict == "PASS"
    assert strict._verify_session_receipt(target, launch, updated_receipt, worker, outcome_r18).verdict == "PASS"


def test_publish_success_refuses_when_native_auto_merge_enabled_on_repo_or_pr(lane, env):
    """R17（Sol P1）：手动审阅、沿用与补发共用 StatusPublisher.publish("success") 门禁：
    若仓库 allow_auto_merge 未显式为 false 或 PR 挂着原生 auto-merge，一律拒绝写 success（抛 EffectPending）；
    关闭后用同一 attempt 补发即可成功。"""
    # 1. 手动审阅完成时仓库允许原生 auto-merge：拒绝发布 success，只留 pending
    lane.gateway.repo["allow_auto_merge"] = True
    with pytest.raises(EffectPending, match="allow_auto_merge"):
        lane.review_pr(1810, 1)
    assert lane.gateway.sent == ["pending"]

    # 2. 仓库关闭但 PR 仍挂着原生 auto-merge：同 attempt 补发依然拒绝写 success
    lane.gateway.repo["allow_auto_merge"] = False
    lane.gateway.pr["auto_merge"] = {"merge_method": "merge"}
    with pytest.raises(EffectPending, match="原生 auto-merge"):
        lane.review_pr(1810, 1)
    assert lane.gateway.sent == ["pending"]

    # 3. 撤回 PR 原生 auto-merge 后，同一 attempt 补发立即发布 success（零重跑模型）
    lane.gateway.pr["auto_merge"] = None
    first = lane.review_pr(1810, 1)
    assert first["verdict"] == "PASS" and lane.gateway.sent == ["pending", "success"]

    # 4. 沿用路径同样受发布门约束：仓库重开 allow_auto_merge 时拒绝发布沿用 success
    _advance_main(lane, env)
    lane.gateway.repo["allow_auto_merge"] = True
    with pytest.raises(EffectPending, match="allow_auto_merge"):
        lane.review_pr(1810, 1)
    assert lane.gateway.sent[-1] == "pending"
    lane.gateway.repo["allow_auto_merge"] = False
    reused = lane.review_pr(1810, 1)
    assert reused["verdict"] == "PASS" and "reused_from" in reused and lane.gateway.sent[-1] == "success"


def test_stale_rereview_attempt_preserves_intent_and_blocks_pass_reuse_until_settled(lane, env):
    """R17（Astra P1）：A1 PASS -> A2 预检失败留下重审意图 -> A2 登记后变 STALE：
    意图文件必须保留并继续阻断旧 A1 的沿用；直到新非 STALE attempt 真正发布终态才清理意图。"""
    head = lane.gateway.pr["head"]["sha"]
    old_base = lane.gateway.pr["base"]["sha"]
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    lane.preflight = lambda _t: {"returncode": 2, "report": None, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    assert lane.has_pending_rereview_intent(1810, head, old_base) is True

    # A2 登记（尚未终态）：意图文件仍在磁盘，待 A2 变 STALE 后自动恢复阻断
    lane.preflight = _fake_preflight_pass
    t2 = lane.target(1810, 2)
    folder2 = lane.state_root / "runs" / t2.key
    module._save(folder2 / "outcome.json", {"run_id": t2.run_id, "verdict": "STALE", "reason": "controller switched"})
    assert lane.has_pending_rereview_intent(1810, head, old_base) is True

    # 同 patch_id 追平到新 head 时，因重审意图未由非 STALE 终态收口，绝不得沿用 A1 PASS
    _advance_main(lane, env)
    assert lane.would_reuse(load_target(lane.gateway, 1810)) is False
    # 回到原 head 上由 A3 完成并发布非 STALE 终态后，意图被清理
    lane.gateway.pr["base"]["sha"] = old_base
    lane.gateway.pr["head"]["sha"] = head
    a3 = lane.review_pr(1810, 3)
    assert a3["verdict"] == "PASS" and lane.has_pending_rereview_intent(1810, head, old_base) is False


def test_real_github_app_client_and_repo_gateway_publish_success_checks_repo_allow_auto_merge(env, tmp_path, monkeypatch):
    """R18（Astra P0）：真实 GitHubAppClient + httpx.MockTransport + RepoGateway + StatusPublisher.publish('success')
    全链路集成测试：真实路径白名单放行 GET /repos/{owner}/{repo}，allow_auto_merge=True 时拒发，False 时发布 success。"""
    import time
    from datetime import datetime, timedelta, timezone

    import httpx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from pilot1742.delivery import RepoGateway
    from pilot1742.github_app import AppIdentity, GitHubAppClient

    monkeypatch.setattr(module, "SOURCE_REPO", env.source)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = tmp_path / "review-app.pem"
    pem.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    pem.chmod(0o600)
    ident = AppIdentity(
        5664795, 179444545, 1150335160, "Newchanlun/NewChanlun", "newchanlun-review-gate", pem,
        installation_permissions=module.DEFAULT_IDENTITY["installation_permissions"],
    )
    head = git(env.source, "rev-parse", "HEAD")
    repo_state = {"allow_auto_merge": True}
    statuses: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/app":
            return httpx.Response(200, json={"id": ident.app_id, "slug": ident.app_slug})
        if path == f"/app/installations/{ident.installation_id}":
            return httpx.Response(200, json={
                "id": ident.installation_id, "app_id": ident.app_id, "app_slug": ident.app_slug,
                "account": {"login": "Newchanlun"}, "repository_selection": "selected",
                "suspended_at": None, "permissions": dict(ident.installation_permissions),
            })
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={
                "token": "mock-inst-token", "permissions": dict(module.TOKEN_PERMISSIONS),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            })
        if path == f"/repos/{ident.repository}":
            if repo_state.get("mode") == "connect_error":
                raise httpx.ConnectError("network down", request=request)
            if repo_state.get("mode") == "http_502":
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(200, json={
                "id": ident.repository_id, "full_name": ident.repository,
                "allow_auto_merge": repo_state["allow_auto_merge"],
            })
        if path == f"/repos/{ident.repository}/pulls/1810":
            return httpx.Response(200, json={
                "number": 1810, "state": "open", "draft": False, "auto_merge": None,
                "user": {"login": "business-owner"},
                "base": {"repo": {"id": ident.repository_id}, "ref": "main", "sha": env.base},
                "head": {"repo": {"id": ident.repository_id}, "ref": "feature/business", "sha": head},
            })
        if path == f"/repos/{ident.repository}/commits/{head}/statuses":
            return httpx.Response(200, json=statuses)
        if path == f"/repos/{ident.repository}/statuses/{head}" and request.method == "POST":
            body = json.loads(request.content)
            row = {"id": len(statuses) + 1, "sha": head, "context": body["context"], "state": body["state"],
                   "description": body["description"], "creator": {"login": f"{ident.app_slug}[bot]", "type": "Bot"}}
            statuses.insert(0, row)
            return httpx.Response(201, json=row)
        raise AssertionError(f"unexpected {request.method} {path}")

    with GitHubAppClient(ident, permissions=module.TOKEN_PERMISSIONS, transport=httpx.MockTransport(handler)) as client:
        gw = RepoGateway(client)
        target = ReviewTarget(
            **module.load_target(gw, 1810), merge_base_sha=env.base, run_id=str(uuid.uuid4()),
            attempt=1, policy_version=module.POLICY, controller_code_head=module.check_controller(),
            registered_at_ns=time.time_ns(), patch_id=module.patch_identity(env.source, env.base, head),
            review_contract=module.REVIEW_CONTRACT,
        )
        folder = tmp_path / "runs" / target.key
        pub = StatusPublisher(gw, target, folder, tmp_path / "locks")
        pub.publish("pending")
        assert statuses[0]["state"] == "pending"
        with pytest.raises(EffectPending, match="allow_auto_merge"):
            pub.publish("success")
        assert statuses[0]["state"] == "pending"
        for mode in ("connect_error", "http_502"):
            repo_state["mode"] = mode
            with pytest.raises(EffectPending, match="allow_auto_merge"):
                pub.publish("success")
            assert statuses[0]["state"] == "pending"
        repo_state.pop("mode", None)
        repo_state["allow_auto_merge"] = False
        done = pub.publish("success")
        assert done["state"] == "success" and statuses[0]["state"] == "success"


def test_resume_publication_acquires_pr_lock_before_clearing_rereview_intent(lane, monkeypatch):
    """R19（Sol P1 / Astra P1）：_resume_publication 在对账已发出的终态后清理重审意图时必须持有 _pr_lock，
    与 _record_rereview_intent 串行化，防止并发删除新写入的重审意图。"""
    from contextlib import contextmanager

    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    target = ReviewTarget(**passed["target"])
    folder = lane.state_root / "runs" / target.key
    # 模拟重审意图早于本 attempt 登记时刻，且 outcome.json 尚未写回 publication 而 journal 已 done
    intent_path = lane._rereview_intent_path(target.repository_id, target.pr_number, target.base_sha, target.head_sha)
    module._save(intent_path, {
        "repository_id": target.repository_id, "pr_number": target.pr_number,
        "base_sha": target.base_sha, "head_sha": target.head_sha,
        "patch_id": target.patch_id, "attempt": 1,
        "recorded_at_ns": target.registered_at_ns - 1,
    })
    saved = {k: v for k, v in passed.items() if k != "publication"}
    module._save(folder / "outcome.json", saved)

    held = {"active": False, "saw_locked_clear": False}
    orig_lock = lane._pr_lock
    orig_clear = lane._clear_rereview_intent_locked

    @contextmanager
    def tracked_lock(pr_num):
        with orig_lock(pr_num):
            held["active"] = True
            try:
                yield
            finally:
                held["active"] = False

    def tracked_clear(t):
        assert held["active"], "_clear_rereview_intent_locked called without _pr_lock!"
        held["saw_locked_clear"] = True
        return orig_clear(t)

    monkeypatch.setattr(lane, "_pr_lock", tracked_lock)
    monkeypatch.setattr(lane, "_clear_rereview_intent_locked", tracked_clear)

    resumed = lane.review_pr(1810, 1)
    assert resumed["verdict"] == "PASS" and "publication" in resumed
    assert held["saw_locked_clear"] is True
    assert not intent_path.exists()


def test_publish_success_reconciles_existing_remote_status_even_if_allow_auto_merge_changes(lane):
    """R20（Astra P2）：若 GitHub 已接受本 run 的 success、控制器在落本地回执前中断，
    随后仓库 allow_auto_merge 改变或 /repos 接口暂不可读，只读对账仍须成功认回既有远端状态（且不重发新状态），
    而真正发送新的 success 仍受 allow_auto_merge 门禁阻断。"""
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    target = ReviewTarget(**passed["target"])
    folder = lane.state_root / "runs" / target.key
    # 模拟 status-success 已发往远端并生效，但本地 journal 停在 pending 且 outcome 未写 publication
    module._save(folder / "effects" / "status-success.json", {"state": "pending", "what": {"state": "success"}})
    module._save(folder / "outcome.json", {k: v for k, v in passed.items() if k != "publication"})

    lane.gateway.repo["allow_auto_merge"] = True
    lane.gateway.pr["auto_merge"] = {"merge_method": "merge"}
    before_sent = list(lane.gateway.sent)
    reconciled = lane.review_pr(1810, 1)
    assert reconciled["verdict"] == "PASS" and "publication" in reconciled
    assert lane.gateway.sent == before_sent  # 纯只读认回，未重发

    # 再验证 journal 已 done 但 outcome 缺 publication 且 /repos 抛错时，只读对账同样成功
    module._save(folder / "outcome.json", {k: v for k, v in passed.items() if k != "publication"})
    lane.gateway.get_repo = lambda: (_ for _ in ()).throw(IdentityError("HTTP 502"))
    reconciled2 = lane.review_pr(1810, 1)
    assert reconciled2["verdict"] == "PASS" and "publication" in reconciled2
    assert lane.gateway.sent == before_sent


def test_validate_review_rejects_missing_admitted_image_id_on_current_policy(lane):
    """R22（Astra P1）：当前 POLICY 的非沿用 target.json 若缺少预检准入冻结的 admitted_image_id，
    validate_review 必须失败闭合，即使 launch.json 与 receipt.json 带有相同镜像 Id 也不放行。"""
    from dataclasses import replace

    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    target = ReviewTarget(**passed["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = json.loads((worker / "launch.json").read_text())
    receipt = json.loads((worker / "receipt.json").read_text())
    assert launch["image_id"] == receipt["image_id"] and target.admitted_image_id == launch["image_id"]

    missing_target = replace(target, admitted_image_id="")
    outcome = validate_review(missing_target, launch, receipt, worker, lane.source)
    assert outcome.verdict == "FAILED" and "缺少预检准入冻结的镜像 Id" in outcome.reason


def test_validate_review_rejects_whitespace_padded_token_usage_response_id(lane):
    """R27（Astra P2）：session.jsonl 中的 token_usage_record.response_id 带首尾空白时必须失败闭合，
    不经 strip() 归一化冒充与代理精确 response_id 一致。"""
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    target = ReviewTarget(**passed["target"])
    worker = lane.state_root / "runs" / target.key / MODELS[0]
    launch = json.loads((worker / "launch.json").read_text())
    receipt = json.loads((worker / "receipt.json").read_text())
    sess_path = worker / "session.jsonl"
    lines = sess_path.read_text(encoding="utf-8").splitlines()
    patched = []
    mutated = False
    for line in lines:
        item = json.loads(line)
        if item.get("type") == "token_usage_record" and isinstance(item.get("payload"), dict):
            item["payload"]["response_id"] = f" {item['payload']['response_id']} "
            mutated = True
        patched.append(json.dumps(item))
    assert mutated
    sess_path.write_text("\n".join(patched) + "\n", encoding="utf-8")
    outcome = validate_review(target, launch, receipt, worker, lane.source)
    verified = lane._verify_session_receipt(target, launch, receipt, worker, outcome)
    assert verified.verdict == "FAILED" and "首尾空白" in verified.reason


def test_publish_final_blocks_old_pass_when_newer_rereview_intent_exists_without_target(lane):
    """R28（Astra P1）：A1 尚未发布终态时，若 A2 写下重审意图后预检失败退出（无 A2 的 target.json），
    A1 在 _publish_final 的 PR 锁内必须发现更晚的重审意图并转 STALE，绝不能发布旧 success 或清掉该意图。"""
    t1 = lane.target(1810, 1)
    folder1 = lane.state_root / "runs" / t1.key
    # A2 尝试重审：记录重审意图后预检失败，不写 target.json
    lane.preflight = lambda _t: {
        "returncode": 2,
        "image_id": "sha256:" + "1" * 64,
        "report": {"kind": "review-preflight", "is_review_result": False, "ready": False,
                   "checks": [{"name": f"route:{MODELS[0]}", "ok": False}]},
    }
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    assert lane.has_pending_rereview_intent(1810, t1.head_sha, t1.base_sha) is True
    assert len(lane.status(1810)) == 1  # 仅 A1 有 target.json

    # A1 随后推进到发布阶段：必须判 STALE，不得发布 success，也不得清掉 A2 的重审意图
    result = lane.review_pr(1810, 1)
    assert result["verdict"] == "STALE"
    assert not any(s.get("state") == "success" for s in lane.gateway.sent)
    assert lane.has_pending_rereview_intent(1810, t1.head_sha, t1.base_sha) is True
    assert (folder1 / "outcome.json").exists()


def test_rereview_intent_dir_unreadable_fails_closed_and_fsync_failure_blocks_preflight(lane, monkeypatch):
    """R32（Sol P1 + Astra P1）：
    1. rereview-intents 目录不可读（PermissionError）时，has_pending_rereview_intent、_has_newer_rereview_intent
       与 reuse_source 均必须失败闭合，绝不因 Path.glob() 静默返回空而放行旧 PASS；
    2. _save() 必须在新建目录与 os.replace() 后 fsync 父目录；fsync 失败时重审在进入预检前中止。"""
    import os
    from dataclasses import replace

    t1 = lane.target(1810, 1)
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    # 1. fsync 目录调用记录 + 注入失败阻断预检
    synced: list[Path] = []
    orig_fsync = module._fsync_dir

    def fail_on_intent(directory: Path) -> None:
        synced.append(directory)
        if directory.name == "rereview-intents":
            raise OSError("injected dir fsync error")
        orig_fsync(directory)

    preflight_called = []
    lane.preflight = lambda t: (preflight_called.append(t), _fake_preflight_pass(t))[1]
    monkeypatch.setattr(module, "_fsync_dir", fail_on_intent)
    with pytest.raises(OSError, match="injected dir fsync error"):
        lane.target(1810, 2)
    assert preflight_called == []
    assert any(p.name == "rereview-intents" for p in synced)
    assert lane.state_root in synced

    # 2. rereview-intents 目录不可读（0o000）-> 全部查询失败闭合
    monkeypatch.setattr(module, "_fsync_dir", orig_fsync)
    intent_dir = lane.state_root / "rereview-intents"
    intent_dir.mkdir(exist_ok=True, mode=0o700)
    os.chmod(intent_dir, 0o000)
    try:
        assert lane.has_pending_rereview_intent(1810, t1.head_sha, t1.base_sha) is True
        assert lane._has_newer_rereview_intent(t1) is True
        t_new = replace(t1, run_id="00000000-0000-4000-8000-000000000099", attempt=9)
        assert lane.reuse_source(t_new) is None
    finally:
        os.chmod(intent_dir, 0o700)


def test_reject_draft_blocks_auto_dispatch_but_manual_review_allows_draft(lane):
    """R32（Astra P2）：自动派审传 reject_draft=True 时，PR 转回 draft 立即以 TargetDrifted 拒绝且不登记；
    手动 review_pr（默认 reject_draft=False）仍可照常审 draft。"""
    lane.gateway.pr["draft"] = True
    with pytest.raises(module.TargetDrifted, match="draft-not-reviewed"):
        lane.target(1810, 1, reject_draft=True)
    assert lane.status(1810) == [] and lane.gateway.sent == []
    # 手动模式允许 draft
    manual_target = lane.target(1810, 1, reject_draft=False)
    assert manual_target.pr_number == 1810


def test_corrupt_rereview_intent_timestamp_and_unreadable_newer_run_dir_fail_closed(lane):
    """R33（Sol P2 + Astra P1）：
    1. 重审意图 JSON 中 recorded_at_ns 为 false 或 0 时，绝不能因 int() 强转当作更早时间而忽略，必须失败闭合；
    2. A1 已 PASS、A2 随后登记/结束，若 A2 的 run 目录失去遍历权限，status() 抛 PermissionError、
       reuse_source 返回 None、_superseded_on_head 返回 True，绝不静默跳过 A2 重新认可旧 PASS。"""
    import os
    from dataclasses import replace

    t1 = lane.target(1810, 1)
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    # 1. 损坏的 recorded_at_ns（false / 0）必须失败闭合
    intent_path = lane._rereview_intent_path(t1.repository_id, t1.pr_number, t1.base_sha, t1.head_sha)
    for bad_ts in (False, 0, -5, "123"):
        module._save(intent_path, {
            "repository_id": t1.repository_id, "pr_number": t1.pr_number,
            "base_sha": t1.base_sha, "head_sha": t1.head_sha,
            "patch_id": t1.patch_id, "attempt": 2, "recorded_at_ns": bad_ts,
        })
        assert lane.has_pending_rereview_intent(1810, t1.head_sha, t1.base_sha) is True
        assert lane._has_newer_rereview_intent(t1) is True
        t_other = replace(t1, run_id="00000000-0000-4000-8000-000000000088", attempt=8)
        assert lane.reuse_source(t_other) is None
    intent_path.unlink(missing_ok=True)

    # 2. A2 目录失去遍历权限（0o000，且清空重审意图防止被意图路径遮罩）：
    #    status() 抛 PermissionError，reuse_source 拒沿用，_superseded_on_head 失败闭合
    t2 = lane.target(1810, 2)
    intent_path.unlink(missing_ok=True)
    run2 = lane.state_root / "runs" / t2.key
    os.chmod(run2, 0o000)
    try:
        with pytest.raises(PermissionError):
            lane.status(1810)
        assert lane._superseded_on_head(t1) is True
        t_other = replace(t1, run_id="00000000-0000-4000-8000-000000000077", attempt=7)
        assert lane.reuse_source(t_other) is None
    finally:
        os.chmod(run2, 0o700)


def test_reuse_fallback_rechecks_draft_before_publishing_pending(lane, monkeypatch):
    """R33（Sol P2）：自动派审（reject_draft=True）从沿用退回新审时，若 PR 在补做预检期间转回 draft，
    绝不发布 pending 也不派发模型。"""
    t1 = lane.target(1810, 1)
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    lane.gateway.sent.clear()
    # 登记 A2 时模拟规划沿用（reuse_planned=True），随后来源失效触发退回补做预检
    calls = {"reusable": 0}

    def flaky_reusable(target):
        calls["reusable"] += 1
        if calls["reusable"] == 1:
            return ({"run_id": t1.run_id}, {"image_id": "sha256:" + "1" * 64})
        return None

    monkeypatch.setattr(lane, "reusable", flaky_reusable)

    def preflight_turns_draft(t):
        lane.gateway.pr["draft"] = True
        return _fake_preflight_pass(t)

    lane.preflight = preflight_turns_draft
    result = lane.review_pr(1810, 2, reject_draft=True)
    assert result["verdict"] == "STALE"
    assert lane.gateway.sent == []


def test_target_unreadable_prior_run_still_records_rereview_intent(lane):
    """R34（Astra P1）：A1 已发布 PASS 的目录暂时不可遍历（0o000）时，启动 A2 仍须在预检前写下重审意图；
    即使 A2 随后预检失败、A1 恢复权限，has_pending_rereview_intent 仍返回 True，绝不再次认可 A1。
    runs 根目录本身不可遍历时直接抛 PermissionError 拒继续。"""
    import os

    t1 = lane.target(1810, 1)
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    run1 = lane.state_root / "runs" / t1.key
    lane.preflight = lambda t: {"returncode": 2, "report": {"kind": "review-preflight", "is_review_result": False, "ready": False, "checks": []}}

    os.chmod(run1, 0o000)
    try:
        with pytest.raises(EffectPending, match="preflight-blocked"):
            lane.target(1810, 2)
    finally:
        os.chmod(run1, 0o700)
    assert lane.has_pending_rereview_intent(1810, t1.head_sha, t1.base_sha) is True

    runs_root = lane.state_root / "runs"
    os.chmod(runs_root, 0o000)
    try:
        with pytest.raises(PermissionError):
            lane.target(1810, 2)
    finally:
        os.chmod(runs_root, 0o700)


def test_truncated_multifile_diff_rejects_pass_until_all_files_covered_but_allows_block(lane, env):
    """R35（Sol P1）：完整 git diff 输出被截断（仅呈现部分变更文件）时：
    1. 未补读其余文件即返回 PASS，validate_review 与 _verify_session_receipt 均拒认（记 FAILED）；
    2. 独立命令补读剩余文件后覆盖全部冻结变更文件，PASS 通过；
    3. 仅覆盖首文件但给出 BLOCK 时仍允许提前阻断（不强制空读剩余文件）。"""
    import hashlib

    (env.source / "alpha_r35.py").write_text("ALPHA_UNIQUE_R35_LINE = 'alpha_val_12345'\n")
    (env.source / "beta_r35.py").write_text("BETA_UNIQUE_R35_LINE = 'beta_val_67890'\n")
    git(env.source, "add", "alpha_r35.py", "beta_r35.py")
    git(env.source, "commit", "-qm", "add two files r35")
    new_head = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = new_head

    target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    worker = folder / MODELS[0]
    worker.mkdir(parents=True)
    session = "019d0000-0000-7000-8000-00000000r351".replace("r", "a")
    full_diff = git(env.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha)
    before_beta_diff = git(
        env.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha,
        "--", "alpha_r35.py", "changed-0", "changed-1",
    )
    beta_diff = git(env.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha, "--", "beta_r35.py")
    # 截断正好落在 changed-1 的改动行之前（保留 changed-1 文件头但切掉其 `+1` 行，且缺失 beta_r35.py）
    changed1_cut = before_beta_diff.rsplit("\n+", 1)[0]
    trunc_diff = f"Warning: truncated output (original token count: 99999)\n{changed1_cut}\n…88888 chars truncated…\n"

    def write_worker(ev_cmds_out: list[tuple[str, str]], sess_cmds_out: list[tuple[str, str]], verdict: str) -> tuple[dict, dict]:
        out_obj = {
            "status": "blocked" if verdict == "BLOCK" else "completed",
            "summary": f"VERDICT: {verdict}",
            "findings": ["[P1] 发现问题"] if verdict == "BLOCK" else [],
            "validation": ["测试"],
        }
        out_text = json.dumps(out_obj)
        events = [
            {"type": "thread.started", "thread_id": session},
            *[
                {"type": "item.completed", "item": {
                    "type": "command_execution", "command": f"/bin/bash -lc '{c}'",
                    "aggregated_output": o, "status": "completed", "exit_code": 0,
                }}
                for c, o in ev_cmds_out
            ],
            {"type": "item.completed", "item": {"type": "agent_message", "text": out_text}},
            {"type": "turn.completed"},
        ]
        (worker / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
        sess_rows = [
            {"type": "session_meta", "payload": {"id": session, "model_provider": "cliproxy-local"}},
            {"type": "turn_context", "payload": {"model": MODELS[0]}},
        ]
        rid_shas: list[str] = []
        for idx, (c, o) in enumerate(sess_cmds_out, 1):
            cid = f"call_r35_{idx}"
            rid = f"resp_r35_tool_{idx}"
            rid_shas.append(hashlib.sha256(rid.encode()).hexdigest())
            sess_rows.extend([
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "exec_command", "call_id": cid,
                    "arguments": json.dumps({"cmd": c}),
                }},
                {"type": "token_usage_record", "payload": {"response_id": rid}},
                {"type": "response_item", "payload": {
                    "type": "function_call_output", "call_id": cid,
                    "output": f"Process exited with code 0\nOutput:\n{o}",
                }},
            ])
        final_rid = "resp_r35_final"
        rid_shas.append(hashlib.sha256(final_rid.encode()).hexdigest())
        sess_rows.extend([
            {"type": "response_item", "payload": {
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": out_text}],
            }},
            {"type": "token_usage_record", "payload": {"response_id": final_rid}},
        ])
        (worker / "session.jsonl").write_text("\n".join(json.dumps(r) for r in sess_rows) + "\n")
        launch = {
            "run_id": target.run_id, "launch_id": "12345678-1234-4234-8234-1234567890ab",
            "pr_number": 1810, "model": MODELS[0], "head_sha": target.head_sha,
            "base_sha": target.base_sha, "merge_base_sha": target.merge_base_sha,
            "controller_code_head": target.controller_code_head, "mode": "review",
            "prompt": module.review_prompt(target, ("alpha_r35.py", "beta_r35.py")),
            "image_id": "sha256:" + "1" * 64,
        }
        receipt = {
            **launch, "status": "completed", "sandbox": "docker-read-only", "exit_code": 0,
            "container_closed": True, "observed_provider": "cliproxy-local", "observed_model": MODELS[0],
            "isolation_contract": "1" * 64, "container_id": "a" * 64,
            "filesystem": {"source_write": "EROFS", "git_write": "EROFS", "host_read": "ENOENT", "state_write": "ENOENT"},
            "session_id": session, "turn_completed": True, "result": out_obj,
            "before": {"head": target.head_sha, "branch": "HEAD", "status": ""},
            "after": {"head": target.head_sha, "branch": "HEAD", "status": ""},
        }
        module._save(worker / "launch.json", launch)
        module._save(worker / "receipt.json", receipt)
        lane.session_receipt = lambda _m, _l, _s, _since: {
            "launch": f"review-{launch['launch_id']}", "session": session,
            "complete_stable": True, "sealed": True, "routes": [f"codex:{MODELS[0]}@chatgpt.com"],
            "requests": len(rid_shas), "response_id_sha256s": rid_shas,
            "last_response_id_sha256": rid_shas[-1],
            "last_output_sha256": hashlib.sha256(out_text.encode()).hexdigest(),
        }
        return launch, receipt

    cmd_all = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha}"
    cmd_rest = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha} -- changed-1 beta_r35.py"
    rest_diff = git(
        env.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha,
        "--", "changed-1", "beta_r35.py",
    )

    # 1. stdout 未截断但 session.jsonl 截断（仅呈现 alpha_r35.py/changed-0，changed-1 缺失部分行且缺 beta_r35.py）-> PASS 被 _verify_session_receipt 拒绝
    launch, receipt = write_worker([(cmd_all, full_diff)], [(cmd_all, trunc_diff)], "PASS")
    ev_out = module.validate_review(target, launch, receipt, worker, lane.source)
    assert ev_out.verdict == "PASS"
    sess_out = lane._verify_session_receipt(target, launch, receipt, worker, ev_out)
    assert sess_out.verdict == "FAILED" and "未完整呈现全部冻结改动行" in sess_out.reason

    # 2. stdout 本身也截断 -> validate_review 直接拒绝 PASS
    launch, receipt = write_worker([(cmd_all, trunc_diff)], [(cmd_all, trunc_diff)], "PASS")
    assert module.validate_review(target, launch, receipt, worker, lane.source).verdict == "FAILED"

    # 3. 截断后仅补读 beta_r35.py（未补读被截断撤销的 changed-1）仍拒 PASS；补读 changed-1 与 beta_r35.py 后 PASS 通过两道门
    cmd_beta = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha} -- beta_r35.py"
    launch, receipt = write_worker([(cmd_all, trunc_diff), (cmd_beta, beta_diff)],
                                   [(cmd_all, trunc_diff), (cmd_beta, beta_diff)], "PASS")
    assert module.validate_review(target, launch, receipt, worker, lane.source).verdict == "FAILED"

    launch, receipt = write_worker([(cmd_all, trunc_diff), (cmd_rest, rest_diff)],
                                   [(cmd_all, trunc_diff), (cmd_rest, rest_diff)], "PASS")
    ev_ok = module.validate_review(target, launch, receipt, worker, lane.source)
    assert ev_ok.verdict == "PASS"
    assert lane._verify_session_receipt(target, launch, receipt, worker, ev_ok).verdict == "PASS"

    # 4. 仅覆盖 alpha_r35.py 但给出 BLOCK -> 仍允许提前阻断
    launch, receipt = write_worker([(cmd_all, trunc_diff)], [(cmd_all, trunc_diff)], "BLOCK")
    ev_blk = module.validate_review(target, launch, receipt, worker, lane.source)
    assert ev_blk.verdict == "BLOCK"
    assert lane._verify_session_receipt(target, launch, receipt, worker, ev_blk).verdict == "BLOCK"


def test_superseded_on_head_fails_closed_on_missing_target_nonempty_dir_and_bad_timestamp(lane):
    """R35（Astra P1）：发布前 _superseded_on_head 遇到无 target.json 的非空残缺 run 目录（含工蜂/结果文件）
    或同 head 另一记录的 registered_at_ns 为 false/0/缺失时，必须失败闭合返回 True，绝不放行旧 PASS 发布。"""
    t1 = lane.target(1810, 1)
    t2 = lane.target(1810, 2)
    run2 = lane.state_root / "runs" / t2.key
    orig_t2 = json.loads((run2 / "target.json").read_text())

    # 1. A2 的 registered_at_ns 损坏为 false / 0 / 缺失 -> _superseded_on_head 返回 True
    for bad_target in (
        {**orig_t2, "registered_at_ns": False},
        {**orig_t2, "registered_at_ns": 0},
        {k: v for k, v in orig_t2.items() if k != "registered_at_ns"},
    ):
        (run2 / "target.json").write_text(json.dumps(bad_target))
        assert lane._superseded_on_head(t1) is True

    # 2. A2 缺少 target.json 但目录内已有工蜂/结果文件 -> 复用 status() 拒绝，_superseded_on_head 返回 True
    (run2 / "target.json").unlink()
    (run2 / "outcome.json").write_text(json.dumps({"verdict": "FAILED"}))
    assert lane._superseded_on_head(t1) is True


def test_single_file_mid_truncation_and_headerless_shared_line_reject_pass(lane, env):
    """R36/R37（Sol P1/P2 + Astra P1/P2）：
    1. 按精确 `(file_header, sign, line_no, exact_text)` 追踪全部增删行：同文件两处远距 hunk 含完全相同改动行时，
       只读首 hunk 绝不把次 hunk 算作已覆盖；大 hunk 缺失任意一行或中途截断均不能满足全集；
    2. 超大单 hunk（含删除+新增）用 `git diff -U0 -- <file> | nl -ba | sed -n` 按精确 `-U0` 行号分段补读可完整覆盖；
       `sed` 先于 `nl -ba`、双层行号（`nl -ba | grep -n`）、`cat -s`、多段 `sed`、非 `-U0` `grep`、多文件 `git show` 均拒认；
    3. 源码自身合法新增含 `123 chars truncated` 的改动行不再被启发式正则误杀，精确坐标匹配可直接放行 PASS。"""
    from pilot1742.patch_read import covered_candidate_patch_units

    big_lines = [f"LINE_{i:03d} = 'filler_unchanged_line_{i:03d}'" for i in range(1, 130)]
    (env.source / "big_r36.py").write_text("\n".join(big_lines) + "\n")
    git(env.source, "add", "big_r36.py")
    git(env.source, "commit", "-qm", "base big_r36")
    base_sha = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["base"]["sha"] = base_sha

    # 同文件两个远距 hunk 含完全相同的改动行 + 连续多行替换块 + 含 "123 chars truncated" 字面量的合法改动行
    big_lines[2] = "IDENTICAL_LINE_TWO_HUNKS = 'exact_same_text'"
    big_lines[3] = "HUNK1_EXTRA_LINE = 'must_not_be_dropped_by_window'"
    big_lines[4] = "LITERAL_TRUNC_MSG = '123 chars truncated in fixture'"
    big_lines[110] = "IDENTICAL_LINE_TWO_HUNKS = 'exact_same_text'"
    (env.source / "big_r36.py").write_text("\n".join(big_lines) + "\n")
    (env.source / "dup_a_r36.py").write_text("SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n")
    (env.source / "dup_b_r36.py").write_text("SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n")
    git(env.source, "add", "big_r36.py", "dup_a_r36.py", "dup_b_r36.py")
    git(env.source, "commit", "-qm", "two identical hunks, literal truncated text, and shared line")
    head_sha = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = head_sha

    target = lane.target(1810, 1)
    patch = module.frozen_patch(env.source, target)
    big_header = "diff --git a/big_r36.py b/big_r36.py"
    big_file = next(f for f in patch.files if f.header == big_header)
    assert len(big_file.changes) == 8  # 4 deleted + 4 added

    cmd_big = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha} -- big_r36.py"
    full_big = git(env.source, "diff", "--no-ext-diff", "--no-textconv", target.merge_base_sha, target.head_sha, "--", "big_r36.py")

    # 1. 含字面 "123 chars truncated" 的完整单文件 diff 必须 100% 精确覆盖，不得误杀
    assert covered_candidate_patch_units(cmd_big, full_big, patch) == big_file.changes

    # 2. 缺失大 hunk 中任一行（即使同 hunk 前后行都在、且距离远小于 40 行）-> 不满足全集
    dropped_one = full_big.replace("+HUNK1_EXTRA_LINE = 'must_not_be_dropped_by_window'\n", "")
    got_drop = covered_candidate_patch_units(cmd_big, dropped_one, patch)
    assert (big_header, "+", 4, "HUNK1_EXTRA_LINE = 'must_not_be_dropped_by_window'") not in got_drop
    assert not big_file.changes.issubset(got_drop)

    # 3. 仅读 hunk 1（即使 hunk 1 与 hunk 2 的 `+` 文本完全一致）绝不覆盖 hunk 2 的行号 111
    hunk2_hdr_pos = full_big.index("@@ -108,")
    hunk1_only = full_big[:hunk2_hdr_pos]
    got_hunk1 = covered_candidate_patch_units(f"{cmd_big} | head -n 16", hunk1_only, patch)
    assert (big_header, "+", 3, "IDENTICAL_LINE_TWO_HUNKS = 'exact_same_text'") in got_hunk1
    assert (big_header, "+", 111, "IDENTICAL_LINE_TWO_HUNKS = 'exact_same_text'") not in got_hunk1
    assert not big_file.changes.issubset(got_hunk1)

    # 4. 单文件 -U0 + nl -ba + sed -n 在首 hunk 内部切断分段补读（第二段首部不含 @@ 头）仍按精确 -U0 行号覆盖全部删除与新增行
    u0_big = git(env.source, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
                 target.merge_base_sha, target.head_sha, "--", "big_r36.py")
    u0_lines = u0_big.splitlines()
    numbered_u0 = [f"{idx:6d}\t{line}" for idx, line in enumerate(u0_lines, 1)]
    mid = next(idx for idx, line in enumerate(u0_lines) if line.startswith("+HUNK1_EXTRA_LINE"))
    part1 = "\n".join(numbered_u0[:mid]) + "\n"
    part2 = "\n".join(numbered_u0[mid:]) + "\n"
    hunk1_tail_only = "\n".join(numbered_u0[mid:mid + 2]) + "\n"
    cmd_u0_1 = f"git diff --no-ext-diff --no-textconv -U0 {target.merge_base_sha} {target.head_sha} -- big_r36.py | nl -ba | sed -n '1,{mid}p'"
    cmd_u0_2 = f"git diff --no-ext-diff --no-textconv -U0 {target.merge_base_sha} {target.head_sha} -- big_r36.py | nl -ba | sed -n '{mid + 1},999p'"
    cov_u0 = covered_candidate_patch_units(cmd_u0_1, part1, patch) | covered_candidate_patch_units(cmd_u0_2, part2, patch)
    assert cov_u0 == big_file.changes
    assert len(covered_candidate_patch_units(cmd_u0_2, hunk1_tail_only, patch)) == 2

    # 5. 错误管线顺序（sed 先于 nl -ba，无 @@ 头切片）、双层行号（nl -ba | grep -n）、cat -s、多段 sed、非 -U0 grep、多文件 git show 均拒认
    cmd_bad_order = f"git diff --no-ext-diff --no-textconv -U0 {target.merge_base_sha} {target.head_sha} -- big_r36.py | sed -n '{mid + 1},{mid + 2}p' | nl -ba"
    assert covered_candidate_patch_units(cmd_bad_order, hunk1_tail_only, patch) == frozenset()
    cmd_double_num = f"git show {target.head_sha}:dup_a_r36.py | nl -ba | grep -n SHARED"
    assert covered_candidate_patch_units(cmd_double_num, "1:     1\tSHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n", patch) == frozenset()
    cmd_cat_s = f"git show {target.head_sha}:dup_a_r36.py | cat -s"
    assert covered_candidate_patch_units(cmd_cat_s, "SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n", patch) == frozenset()
    cmd_multi_sed = f"{cmd_big} | sed -n '1,5p;10,20p'"
    assert covered_candidate_patch_units(cmd_multi_sed, full_big, patch) == frozenset()
    cmd_grep = f"git diff --no-ext-diff --no-textconv {target.merge_base_sha} {target.head_sha} | grep SHARED_DUPLICATE_LINE_R36"
    assert covered_candidate_patch_units(cmd_grep, "+SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n", patch) == frozenset()
    cmd_multi_blob = f"git show {target.head_sha}:dup_a_r36.py {target.head_sha}:dup_b_r36.py"
    assert covered_candidate_patch_units(cmd_multi_blob, "SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n", patch) == frozenset()

    # 6. 单文件 git show <head>:<file> | nl -ba | sed -n 精确覆盖该新增文件的 + 行
    cmd_show_a = f"git show {target.head_sha}:dup_a_r36.py | nl -ba | sed -n '1,5p'"
    assert covered_candidate_patch_units(
        cmd_show_a, "     1\tSHARED_DUPLICATE_LINE_R36 = 'identical_change_content'\n", patch
    ) == frozenset({("diff --git a/dup_a_r36.py b/dup_a_r36.py", "+", 1, "SHARED_DUPLICATE_LINE_R36 = 'identical_change_content'")})


def test_r36_inconsistent_outcome_reuse_corrupt_ts_and_runs_dir_fsync(lane, env, monkeypatch):
    """R36（Astra P1 #1 + Astra P1 #3 + Astra P2 #4）：
    1. 未发布 outcome.json 若 verdict=FAILED 与 state=success 矛盾且无 journal，续发必须抛 IdentityError，绝不向 GitHub 发布 success；
    2. 跨 head 沿用时若同补丁较晚的 FAILED 历史记录 registered_at_ns 为 false/0/缺失，reuse_source 拒绝沿用改走新双审；
    3. 登记 target.json 前后必须 fsync runs 父目录以确保新 attempt 目录项持久化。"""
    # 3. 登记 target 时 fsync runs 父目录
    synced: list[Path] = []
    orig_fsync = module._fsync_dir
    monkeypatch.setattr(module, "_fsync_dir", lambda d: (synced.append(d), orig_fsync(d))[1])
    t1 = lane.target(1810, 1)
    assert (lane.state_root / "runs") in synced

    # 1. outcome.json 字段矛盾（verdict=FAILED, state=success）绝不能跳过复核发布 success
    folder1 = lane.state_root / "runs" / t1.key
    tampered = {
        "run_id": t1.run_id, "verdict": "FAILED", "state": "success",
        "target": json.loads((folder1 / "target.json").read_text()), "reviews": [],
    }
    module._save(folder1 / "outcome.json", tampered)
    lane.gateway.sent.clear()
    with pytest.raises(IdentityError, match="终态字段不一致"):
        lane.review_pr(1810, 1)
    assert "success" not in lane.gateway.sent

    # 2. 跨 head 沿用：A1 PASS、A2 FAILED 但 A2 的 registered_at_ns 损坏为 false/0/缺失 -> 拒沿用，改走新双审
    reuse_root = lane.state_root / "reuse-ts"
    lane2 = module.ExternalReview(
        lane.gateway, source=lane.source, state_root=reuse_root,
        checkout_root=lane.checkout_root / "reuse-ts", poll_seconds=0.01,
        launcher=lane.launcher, preflight=lane.preflight,
        session_receipt=_make_fake_session_receipt(reuse_root),
    )
    first = lane2.review_pr(1810, 1)
    assert first["verdict"] == "PASS"
    t2 = lane2.target(1810, 2)
    f2 = lane2.state_root / "runs" / t2.key
    orig_t2 = json.loads((f2 / "target.json").read_text())
    module._save(f2 / "outcome.json", {
        "run_id": t2.run_id, "verdict": "FAILED", "state": "error", "target": orig_t2, "reviews": [],
    })
    _advance_main(lane2, env)
    for bad_ts in (False, 0, None):
        bad_t2 = {**orig_t2, "registered_at_ns": bad_ts} if bad_ts is not None else {
            k: v for k, v in orig_t2.items() if k != "registered_at_ns"
        }
        module._save(f2 / "target.json", bad_t2)
        module._save(f2 / "outcome.json", {
            "run_id": t2.run_id, "verdict": "FAILED", "state": "error", "target": bad_t2, "reviews": [],
        })
        assert lane2.would_reuse(module.load_target(lane2.gateway, 1810)) is False


def test_r38_metadata_only_break_chars_nonascii_u0_and_reuse_recovery(lane, env, monkeypatch):
    """R38（Sol P1 #1/#2 + Astra P1 #1/#2/#3 + Astra P2 #4/#5）：
    1. 仅改权限（100644->100755）、纯重命名、二进制等无文本 hunk 变更，只读 `diff --git` 头绝不放行 PASS，
       必须覆盖 `old mode`/`new mode`/`rename from`/`rename to`/`Binary files` 等实际变更元数据；
    2. 含 `_BREAK` 控制字符（如 `\\x0c` / `\\u2028`）的改动行必须保留在必读全集中且无法被匹配，PASS 失败闭合；
    3. 非 ASCII 中文路径被 Git C-quote 转义时，解码旧/新路径后单文件 `-U0 | nl -ba | sed -n` 与 `-c core.quotepath=false`
       均可完整覆盖全部删除与新增行；
    4. 沿用来源必须满足完整 `valid_pass_publication`（正整数 id + state=success + sha=old_head），缺 id 或错 sha 一律拒沿用；
    5. `reuse_planned=True` 在已写 `status-pending.json` 后、写 `outcome.json` 前中断，恢复时若沿用失效，
       只要尚未建工蜂目录必须补做空间/预检并写入 `preflight-admitted.json`，随后正常完成双审 PASS。"""
    import os

    from pilot1742.patch_read import covered_candidate_patch_units

    # 4 & 5. 沿用来源发布凭证校验 + 沿用已发 pending 后中断再失效自动补做预检完成双审（先在原始分支基线上完成）
    reuse_root = lane.state_root / "r38-reuse"
    lane2 = module.ExternalReview(
        lane.gateway, source=lane.source, state_root=reuse_root,
        checkout_root=lane.checkout_root / "r38-reuse", poll_seconds=0.01,
        launcher=lane.launcher, preflight=lane.preflight,
        session_receipt=_make_fake_session_receipt(reuse_root),
    )
    first = lane2.review_pr(1810, 1)
    assert first["verdict"] == "PASS"
    first_head = first["target"]["head_sha"]
    first_folder = reuse_root / "runs" / ReviewTarget(**first["target"]).key
    orig_first_outcome = json.loads((first_folder / "outcome.json").read_text())

    _advance_main(lane2, env)
    # 4. 残缺/伪造 publication（缺 id / id=0 / id=True / sha 不符）一律拒沿用
    for bad_pub in (
        {"state": "success"},
        {"id": 0, "state": "success", "sha": first_head},
        {"id": True, "state": "success", "sha": first_head},
        {"id": 1, "state": "success", "sha": "0" * 40},
    ):
        module._save(first_folder / "outcome.json", {**orig_first_outcome, "publication": bad_pub})
        assert lane2.would_reuse(module.load_target(lane2.gateway, 1810)) is False
    module._save(first_folder / "outcome.json", orig_first_outcome)
    assert lane2.would_reuse(module.load_target(lane2.gateway, 1810)) is True

    # 5. reuse_planned=True 在 _publish_reuse 发出 pending 后、写 outcome 前中断，恢复时旧镜像准入失效 -> 补做预检并完成双审 PASS
    t_next = lane2.target(1810, 1)
    assert t_next.reuse_planned is True and t_next.admitted_image_id == ""
    next_folder = reuse_root / "runs" / t_next.key
    pub = module.StatusPublisher(lane2.gateway, t_next, next_folder, reuse_root / "status-locks")
    pub.publish("pending")
    assert (next_folder / "effects" / "status-pending.json").exists()
    assert not (next_folder / "outcome.json").exists()
    assert not (next_folder / module.PREFLIGHT_ADMITTED_FILE).exists()
    # 使旧镜像准入失效（改为新镜像 id，导致 reuse_admission 返回 None，但新双审预检仍通过）
    (lane2.source / ".git" / "fake-admission").write_text("sha256:" + "2" * 64)
    resumed = lane2.review_pr(1810, 1)
    assert resumed["verdict"] == "PASS" and "reused_from" not in resumed
    assert (next_folder / module.PREFLIGHT_ADMITTED_FILE).exists()
    assert [r["model"] for r in resumed["reviews"]] == list(MODELS)
    (lane2.source / ".git" / "fake-admission").unlink()

    # 1. 元数据变更（纯 chmod + 纯 rename + binary）仅读 diff --git 头不得覆盖必读全集
    (env.source / "chmod_r38.sh").write_text("#!/bin/sh\necho hi\n")
    (env.source / "rename_old_r38.py").write_text("KEEP_CONTENT_R38 = 'unchanged_body_for_pure_rename'\n")
    (env.source / "中文_r38.py").write_text(
        "\n".join(f"CN_LINE_{i:02d} = 'orig_{i:02d}'" for i in range(1, 20)) + "\n"
    )
    git(env.source, "add", "chmod_r38.sh", "rename_old_r38.py", "中文_r38.py")
    git(env.source, "commit", "-qm", "base r38")
    base_sha = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["base"]["sha"] = base_sha

    os.chmod(env.source / "chmod_r38.sh", 0o755)
    git(env.source, "mv", "rename_old_r38.py", "rename_new_r38.py")
    (env.source / "bin_r38.bin").write_bytes(b"\x00\x01\x02\x03binary_r38\x00")
    cn_lines = [f"CN_LINE_{i:02d} = 'orig_{i:02d}'" for i in range(1, 20)]
    cn_lines[2] = "CN_LINE_03 = 'changed_alpha'"
    cn_lines[3] = "CN_LINE_04 = 'changed_beta'"
    cn_lines[4] = "CN_LINE_05 = 'changed_gamma'"
    (env.source / "中文_r38.py").write_text("\n".join(cn_lines) + "\n")
    git(env.source, "add", "chmod_r38.sh", "rename_new_r38.py", "bin_r38.bin", "中文_r38.py")
    git(env.source, "commit", "-qm", "r38 chmod rename binary nonascii")
    head_sha = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = head_sha

    t_meta = lane.target(1810, 1)
    patch_meta = module.frozen_patch(env.source, t_meta)
    cmd_full = f"git diff --no-ext-diff --no-textconv {t_meta.merge_base_sha} {t_meta.head_sha}"

    chmod_f = next(f for f in patch_meta.files if f.git_new_path == "chmod_r38.sh")
    assert (chmod_f.header, "M", 0, "old mode 100644") in chmod_f.changes
    assert (chmod_f.header, "M", 0, "new mode 100755") in chmod_f.changes
    assert covered_candidate_patch_units(cmd_full, f"{chmod_f.header}\n", patch_meta) == frozenset()
    assert not chmod_f.changes.issubset(
        covered_candidate_patch_units(cmd_full, f"{chmod_f.header}\nold mode 100644\n", patch_meta)
    )
    assert chmod_f.changes.issubset(
        covered_candidate_patch_units(cmd_full, f"{chmod_f.header}\nold mode 100644\nnew mode 100755\n", patch_meta)
    )

    ren_f = next(f for f in patch_meta.files if f.git_new_path == "rename_new_r38.py")
    assert (ren_f.header, "M", 0, "rename from rename_old_r38.py") in ren_f.changes
    assert (ren_f.header, "M", 0, "rename to rename_new_r38.py") in ren_f.changes
    assert covered_candidate_patch_units(cmd_full, f"{ren_f.header}\n", patch_meta) == frozenset()

    bin_f = next(f for f in patch_meta.files if f.git_new_path == "bin_r38.bin")
    assert any(u[1] == "BIN" and u[3].startswith("Binary files ") for u in bin_f.changes)
    assert covered_candidate_patch_units(cmd_full, f"{bin_f.header}\n", patch_meta) == frozenset()

    # 3. 中文路径（Git C-quoted）：单文件 -U0 + nl -ba + sed -n（hunk 内切断）与 -c core.quotepath=false 均须完整覆盖
    cn_f = next(f for f in patch_meta.files if f.git_new_path == "中文_r38.py")
    assert cn_f.header.startswith('diff --git "a/') and cn_f.git_old_path == "中文_r38.py"
    u0_cn = git(env.source, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
                t_meta.merge_base_sha, t_meta.head_sha, "--", "中文_r38.py")
    u0_cn_lines = u0_cn.splitlines()
    num_cn = [f"{idx:6d}\t{line}" for idx, line in enumerate(u0_cn_lines, 1)]
    cut = next(idx for idx, line in enumerate(u0_cn_lines) if line.startswith("+CN_LINE_04"))
    cmd_cn_1 = f"git diff --no-ext-diff --no-textconv -U0 {t_meta.merge_base_sha} {t_meta.head_sha} -- 中文_r38.py | nl -ba | sed -n '1,{cut}p'"
    cmd_cn_2 = f"git diff --no-ext-diff --no-textconv -U0 {t_meta.merge_base_sha} {t_meta.head_sha} -- 中文_r38.py | nl -ba | sed -n '{cut + 1},999p'"
    cov_cn_u0 = (
        covered_candidate_patch_units(cmd_cn_1, "\n".join(num_cn[:cut]) + "\n", patch_meta)
        | covered_candidate_patch_units(cmd_cn_2, "\n".join(num_cn[cut:]) + "\n", patch_meta)
    )
    assert cov_cn_u0 == cn_f.changes

    unquoted_diff = git(env.source, "-c", "core.quotepath=false", "diff", "--no-ext-diff", "--no-textconv",
                        t_meta.merge_base_sha, t_meta.head_sha)
    cmd_unquoted = f"git -c core.quotepath=false diff --no-ext-diff --no-textconv {t_meta.merge_base_sha} {t_meta.head_sha}"
    cov_unquoted = covered_candidate_patch_units(cmd_unquoted, unquoted_diff, patch_meta)
    # R40（Sol P1 #2）：文本/权限/重命名全部覆盖，未展开二进制 blob 保留 BIN 必读项不得自动 PASS
    non_bin_units = {u for u in patch_meta.all_change_units if u[1] != "BIN"}
    assert non_bin_units.issubset(cov_unquoted)
    assert not patch_meta.all_change_units.issubset(cov_unquoted)

    # 2. 含 _BREAK 字符（\x0c 换页符）的改动行必须保留在必读全集且永不匹配，阻断 PASS
    (env.source / "formfeed_r38.py").write_text("NORMAL_LINE_R38 = 'ok'\nHAS_FORMFEED = 'a\x0cb'\n")
    git(env.source, "add", "formfeed_r38.py")
    git(env.source, "commit", "-qm", "add formfeed")
    ff_head = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = ff_head
    t_ff = lane.target(1810, 1)
    patch_ff = module.frozen_patch(env.source, t_ff)
    ff_diff = git(env.source, "diff", "--no-ext-diff", "--no-textconv", t_ff.merge_base_sha, t_ff.head_sha)
    cmd_ff = f"git diff --no-ext-diff --no-textconv {t_ff.merge_base_sha} {t_ff.head_sha}"
    assert any("\x0c" in u[3] for u in patch_ff.all_change_units)
    assert not patch_ff.all_change_units.issubset(covered_candidate_patch_units(cmd_ff, ff_diff, patch_ff))


def test_r39_rereview_attempt_binding_model_reverify_eof_newline_and_space_path(lane, env):
    """R39（Sol P1 #1 + Sol P2 #3 + Astra P1 #1 + Astra P2 #2/#3）：
    1. A2 预检期间 A3 写入重审意图并预检失败后，A2 登记与发布绝不能把 A3 意图判为已承接或误删，且 `_superseded_on_head(A2)` 为 True；
    2. `_reverify_sealed_receipts` 在两目录均放同一模型（Sol+Sol 不同 session）时必须按目录核对模型身份并判 FAILED，绝不发布 success；
    3. 仅删/加末尾换行（`\\ No newline at end of file`）时，截断在无换行标记前的输出不得通过 PASS，完整 diff 与 `-U0 | nl -ba` 须通过；
    4. 含空格中文/ASCII 路径的 `---`/`+++` 末尾 Git 制表符须先剥离再解码，`FrozenFile.path`、`git show` 与 `-U0` 分段补读均匹配。"""
    from pilot1742.patch_read import covered_candidate_patch_units

    # 1. Sol P1 #1（R39/R40）：A1 PASS 后，A2 先登记、随后 A3 写入意图时 A2 被取代且不可清除 A3 意图；
    #    且一旦 A3 意图已落盘，尚未登记的 A2 必须在 PR 锁内被 TargetDrifted 拒绝登记，避免 A2/A3 互相作废。
    first = lane.review_pr(1810, 1)
    assert first["verdict"] == "PASS"
    head1 = first["target"]["head_sha"]
    base1 = first["target"]["base_sha"]

    t2 = lane.target(1810, 2)
    assert t2.attempt == 2
    a3_preview = lane._frozen(module.load_target(lane.gateway, 1810), 3)
    lane._record_rereview_intent(a3_preview)
    assert lane.has_pending_rereview_intent(1810, head1, base1) is True
    assert lane._superseded_on_head(t2) is True
    with lane._pr_lock(1810):
        lane._clear_rereview_intent_locked(t2)
    assert lane.has_pending_rereview_intent(1810, head1, base1) is True
    # 直到 A3 真正登记并清理后，意图才解除
    t3 = lane.target(1810, 3)
    assert lane.has_pending_rereview_intent(1810, head1, base1) is False
    assert lane._superseded_on_head(t3) is False
    with lane._pr_lock(1810):
        lane._clear_rereview_intent_locked(t3)
    assert not lane._rereview_intent_path(t3.repository_id, 1810, base1, head1).exists()

    # 2. Astra P1 #1：_reverify_sealed_receipts 遇 MODELS[1] 目录被替换为 MODELS[0] 另一 session 时必须判 FAILED
    f1 = lane.state_root / "runs" / ReviewTarget(**first["target"]).key
    w1 = f1 / MODELS[1]
    l1_path = w1 / "launch.json"
    orig_l1 = json.loads(l1_path.read_text())
    l1_path.write_text(json.dumps({**orig_l1, "model": MODELS[0]}))
    t1_obj = ReviewTarget(**first["target"])
    reverified = lane._reverify_sealed_receipts(t1_obj, f1, dict(first))
    assert reverified["verdict"] == "FAILED" and reverified["state"] == "error"
    assert any("不符" in (r.get("reason") or "") for r in reverified["reviews"])
    l1_path.write_text(json.dumps(orig_l1))

    # 3 & 4. Astra P2 #2/#3 + Sol P2 #3：仅删末尾换行 + 含空格中文/ASCII 路径（---/+++ 带末尾 \t）
    (env.source / "eof_r39.txt").write_text("same_eof_line\n")
    (env.source / "第一章 形态学_r39.md").write_text("line1_cn_space\nline2_cn_space\n")
    (env.source / "my space_r39.py").write_text("SPACE_A = 1\n")
    git(env.source, "add", "eof_r39.txt", "第一章 形态学_r39.md", "my space_r39.py")
    git(env.source, "commit", "-qm", "base r39")
    b39 = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["base"]["sha"] = b39

    (env.source / "eof_r39.txt").write_text("same_eof_line")  # 唯一改动：删掉末尾换行
    (env.source / "第一章 形态学_r39.md").write_text("line1_cn_space\nline2_cn_space_new\n")
    (env.source / "my space_r39.py").write_text("SPACE_A = 2\n")
    git(env.source, "add", "eof_r39.txt", "第一章 形态学_r39.md", "my space_r39.py")
    git(env.source, "commit", "-qm", "r39 eof newline and space paths")
    h39 = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = h39

    t39 = lane.target(1810, 1)
    p39 = module.frozen_patch(env.source, t39)
    full39 = git(env.source, "diff", "--no-ext-diff", "--no-textconv", t39.merge_base_sha, t39.head_sha)
    cmd39 = f"git diff --no-ext-diff --no-textconv {t39.merge_base_sha} {t39.head_sha}"

    # 3. 删去末尾换行产生 `\+` 必读单元；截断掉 `\ No newline at end of file` 后不得满足全集，完整 diff 与 `-U0 | nl -ba` 均通过
    eof_f = next(f for f in p39.files if f.path == "eof_r39.txt")
    assert any(u[1] == "\\+" and "No newline" in u[3] for u in eof_f.changes)
    eof_diff = git(env.source, "diff", "--no-ext-diff", "--no-textconv", t39.merge_base_sha, t39.head_sha, "--", "eof_r39.txt")
    eof_without_marker = "\n".join(line for line in eof_diff.splitlines() if not line.startswith("\\")) + "\n"
    assert not eof_f.changes.issubset(covered_candidate_patch_units(f"{cmd39} -- eof_r39.txt", eof_without_marker, p39))
    assert eof_f.changes.issubset(covered_candidate_patch_units(f"{cmd39} -- eof_r39.txt", eof_diff, p39))
    u0_eof = git(env.source, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
                 t39.merge_base_sha, t39.head_sha, "--", "eof_r39.txt")
    num_eof = "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(u0_eof.splitlines(), 1)) + "\n"
    assert eof_f.changes.issubset(
        covered_candidate_patch_units(f"{cmd39} -U0 -- eof_r39.txt | nl -ba | sed -n '1,99p'", num_eof, p39)
    )

    # 4. 含空格中文/ASCII 路径：Git 在 ---/+++ 后附带 \t，仍正确解码 path 且 git show 与 -U0 单文件分段补读均通过
    cn_sp = next(f for f in p39.files if f.path == "第一章 形态学_r39.md")
    en_sp = next(f for f in p39.files if f.path == "my space_r39.py")
    assert cn_sp.git_old_path == "第一章 形态学_r39.md" and cn_sp.git_new_path == "第一章 形态学_r39.md"
    assert en_sp.git_old_path == "my space_r39.py" and en_sp.git_new_path == "my space_r39.py"
    assert p39.all_change_units.issubset(covered_candidate_patch_units(cmd39, full39, p39))
    cmd_show_cn = f"git show {t39.head_sha}:'第一章 形态学_r39.md' | nl -ba | sed -n '2,2p'"
    assert covered_candidate_patch_units(cmd_show_cn, "     2\tline2_cn_space_new\n", p39) == frozenset({
        (cn_sp.header, "+", 2, "line2_cn_space_new"),
    })
    u0_cn_sp = git(env.source, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "-U0",
                   t39.merge_base_sha, t39.head_sha, "--", "第一章 形态学_r39.md")
    num_cn_sp = "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(u0_cn_sp.splitlines(), 1)) + "\n"
    assert cn_sp.changes.issubset(
        covered_candidate_patch_units(
            f"git diff --no-ext-diff --no-textconv -U0 {t39.merge_base_sha} {t39.head_sha} -- '第一章 形态学_r39.md' | nl -ba | sed -n '1,99p'",
            num_cn_sp, p39,
        )
    )


def test_r40_concurrent_rereview_no_mutual_stale_target_swap_parallel_output_and_nan_quota(lane, env, monkeypatch):
    """R40（Sol P1 #1/#2 + Astra P1 #1/#2 + Astra P2 #3）：
    1. A3 先落盘后较慢的 A2 不得再登记，抛 TargetDrifted 且不建 A2/target.json，A3 不被作废；
    2. 恢复已有 attempt 时磁盘 target.json 若被换成另一 PR 或篡改 patch_id/head_sha，必须抛 IdentityError 拒绝恢复；
    3. `multi_tool_use.parallel` 多条子命令共用未拆分 `out_body` 时，不得把共享输出同时计入多文件 PASS 覆盖率；
    4. 额度账本含非有限时间戳 `NaN`/`Infinity` 时，开启严格额度校验必须报 `quota-unverifiable`，不得按零用量放行。"""
    import hashlib

    from pilot1742.delivery import EffectPending

    # 1. Sol P1 #1：A1 PASS -> (a) A3 先登记后 A2 尝试登记被 TargetDrifted 拒绝；
    #    (b) A2 先进入慢预检、期间 A3 完成登记，A2 预检返回落盘时仍被 PR 锁内 TargetDrifted 拒绝，A2 不写 target.json 且 A3 不变 STALE
    first = lane.review_pr(1810, 1)
    assert first["verdict"] == "PASS"
    a2_preview = lane._frozen(module.load_target(lane.gateway, 1810), 2)
    a2_dir = lane.state_root / "runs" / a2_preview.key
    orig_admit_preflight = lane.admit_preflight
    t3_box: list[ReviewTarget] = []

    def race_a3_during_a2_preflight(target, **kwargs):
        res = orig_admit_preflight(target, **kwargs)
        if target.attempt == 2 and not t3_box:
            t3_box.append(lane.target(1810, 3))
        return res

    monkeypatch.setattr(lane, "admit_preflight", race_a3_during_a2_preflight)
    with pytest.raises(module.TargetDrifted, match="superseded-by-higher-attempt"):
        lane.target(1810, 2)
    monkeypatch.setattr(lane, "admit_preflight", orig_admit_preflight)
    assert len(t3_box) == 1
    t3 = t3_box[0]
    assert not (a2_dir / "target.json").exists()
    assert lane._superseded_on_head(t3) is False
    # A3 已落盘后再次启动 A2：预检前即在 _record_rereview_intent 被 TargetDrifted 拒绝且不污染意图时间戳
    with pytest.raises(module.TargetDrifted, match="superseded-by-higher-attempt"):
        lane.target(1810, 2)
    assert not (a2_dir / "target.json").exists()
    assert lane._superseded_on_head(t3) is False

    # 2. Astra P1 #1：恢复时磁盘 target.json 被替换为另一 PR 或不同 patch_id，必须拒绝恢复
    t3_path = lane.state_root / "runs" / t3.key / "target.json"
    orig_t3 = json.loads(t3_path.read_text())
    for tampered in (
        {**orig_t3, "pr_number": 9999},
        {**orig_t3, "patch_id": "sha256:" + "0" * 64},
        {**orig_t3, "head_sha": "0" * 40},
    ):
        t3_path.write_text(json.dumps(tampered))
        with pytest.raises(IdentityError):
            lane.target(1810, 3)
    t3_path.write_text(json.dumps(orig_t3))
    assert lane.target(1810, 3).run_id == t3.run_id

    # 3. Astra P1 #2：multi_tool_use.parallel 两子命令共享未拆分 out_body，不得跨文件记入 PASS 覆盖率
    (env.source / "par_a_r40.py").write_text("SHARED_PAR_LINE_R40 = 'identical_parallel_content'\n")
    (env.source / "par_b_r40.py").write_text("SHARED_PAR_LINE_R40 = 'identical_parallel_content'\n")
    git(env.source, "add", "par_a_r40.py", "par_b_r40.py")
    git(env.source, "commit", "-qm", "parallel identical lines r40")
    h40 = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = h40
    t40 = lane.target(1810, 1)
    folder40 = lane.state_root / "runs" / t40.key
    worker40 = folder40 / MODELS[0]
    worker40.mkdir(parents=True)
    session40 = "019d0000-0000-7000-8000-000000000409"
    cmd_a = f"git show {t40.head_sha}:par_a_r40.py | nl -ba | sed -n '1,5p'"
    cmd_b = f"git show {t40.head_sha}:par_b_r40.py | nl -ba | sed -n '1,5p'"
    cmd_full_diff = f"git diff --no-ext-diff --no-textconv {t40.merge_base_sha} {t40.head_sha}"
    full_diff_40 = git(env.source, "diff", "--no-ext-diff", "--no-textconv", t40.merge_base_sha, t40.head_sha)
    out_obj = {"status": "completed", "summary": "VERDICT: PASS", "findings": [], "validation": ["test"]}
    out_text = json.dumps(out_obj)
    # stdout 放完整 diff（让 validate_review 通过），但 session.jsonl 仅用一条 multi_tool_use.parallel 共享输出
    events = [
        {"type": "thread.started", "thread_id": session40},
        {"type": "item.completed", "item": {
            "type": "command_execution", "command": f"/bin/bash -lc {shlex.quote(cmd_a)}",
            "aggregated_output": full_diff_40, "status": "completed", "exit_code": 0,
        }},
        {"type": "item.completed", "item": {
            "type": "command_execution", "command": f"/bin/bash -lc {shlex.quote(cmd_b)}",
            "aggregated_output": full_diff_40, "status": "completed", "exit_code": 0,
        }},
        {"type": "item.completed", "item": {"type": "agent_message", "text": out_text}},
        {"type": "turn.completed"},
    ]
    (worker40 / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    rid1, rid2 = "resp_r40_par_1", "resp_r40_par_2"
    rid_shas = [hashlib.sha256(r.encode()).hexdigest() for r in (rid1, rid2)]
    sess_rows = [
        {"type": "session_meta", "payload": {"id": session40, "model_provider": "cliproxy-local"}},
        {"type": "turn_context", "payload": {"model": MODELS[0]}},
        {"type": "response_item", "payload": {
            "type": "function_call", "name": "multi_tool_use.parallel", "call_id": "call_par_1",
            "arguments": json.dumps({"tool_uses": [
                {"recipient_name": "functions.exec_command", "parameters": {"cmd": cmd_a}},
                {"recipient_name": "functions.exec_command", "parameters": {"cmd": cmd_b}},
            ]}),
        }},
        {"type": "token_usage_record", "payload": {"response_id": rid1}},
        {"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": "call_par_1",
            "output": "Process exited with code 0\nOutput:\n     1\tSHARED_PAR_LINE_R40 = 'identical_parallel_content'\n",
        }},
        {"type": "response_item", "payload": {
            "type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": out_text}],
        }},
        {"type": "token_usage_record", "payload": {"response_id": rid2}},
    ]
    (worker40 / "session.jsonl").write_text("\n".join(json.dumps(r) for r in sess_rows) + "\n")
    launch40 = {
        "run_id": t40.run_id, "launch_id": "12345678-1234-4234-8234-123456789409",
        "pr_number": 1810, "model": MODELS[0], "head_sha": t40.head_sha,
        "base_sha": t40.base_sha, "merge_base_sha": t40.merge_base_sha,
        "controller_code_head": t40.controller_code_head, "mode": "review",
        "prompt": module.review_prompt(t40, ("par_a_r40.py", "par_b_r40.py")),
        "image_id": "sha256:" + "1" * 64,
    }
    receipt40 = {
        **launch40, "status": "completed", "sandbox": "docker-read-only", "exit_code": 0,
        "container_closed": True, "observed_provider": "cliproxy-local", "observed_model": MODELS[0],
        "isolation_contract": "1" * 64, "container_id": "a" * 64,
        "filesystem": {"source_write": "EROFS", "git_write": "EROFS", "host_read": "ENOENT", "state_write": "ENOENT"},
        "session_id": session40, "turn_completed": True, "result": out_obj,
        "before": {"head": t40.head_sha, "branch": "HEAD", "status": ""},
        "after": {"head": t40.head_sha, "branch": "HEAD", "status": ""},
    }
    module._save(worker40 / "launch.json", launch40)
    module._save(worker40 / "receipt.json", receipt40)
    lane.session_receipt = lambda _m, _l, _s, _since: {
        "launch": f"review-{launch40['launch_id']}", "session": session40,
        "complete_stable": True, "sealed": True, "routes": [f"codex:{MODELS[0]}@chatgpt.com"],
        "requests": 2, "response_id_sha256s": rid_shas,
        "last_response_id_sha256": rid_shas[-1],
        "last_output_sha256": hashlib.sha256(out_text.encode()).hexdigest(),
    }
    pass_stub = module.ReviewOutcome(MODELS[0], "PASS", session40, "VERDICT: PASS")
    sess_verdict = lane._verify_session_receipt(t40, launch40, receipt40, worker40, pass_stub)
    assert sess_verdict.verdict == "FAILED" and "未完整呈现全部冻结改动行" in sess_verdict.reason
    # 独立 diff 命令仍按单命令正常通过
    assert cmd_full_diff  # keep lint clean

    # 4. Astra P2 #3：preflight-usage.jsonl 含 NaN / Infinity 时间戳必须触发 quota-unverifiable
    monkeypatch.setenv(module.DAILY_INPUT_CAP_ENV, "1000000")
    usage_path = lane.state_root / module.PREFLIGHT_USAGE_FILE
    for bad_ts in ("NaN", "Infinity", "-Infinity"):
        usage_path.write_text(f'{{"at": {bad_ts}, "tokens": 100}}\n')
        usage_path.chmod(0o600)
        with pytest.raises(EffectPending, match="quota-unverifiable"):
            lane.admit_quota()
