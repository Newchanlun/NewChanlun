import copy
import json
import os
from datetime import datetime, timezone

import pytest
import test_external_review as _external_review
from conftest import git

from pilot1742 import review_sweep as module
from pilot1742.external_review import MODELS, ReviewTarget
from pilot1742.review_sweep import (
    ServeRound,
    SourceUnreadable,
    Sweep,
    human_gated,
    reviewing,
)


@pytest.fixture
def lane(env, monkeypatch):
    """单提交 PR 夹具（rev-list --ancestry-path base..head == [head]，满足服务端精确 base 绑定）；
    需测多提交中间祖先场景的用例在用例内再追加提交。"""
    (env.source / "changed-0").write_text("0")
    (env.source / "changed-1").write_text("1")
    git(env.source, "add", ".")
    git(env.source, "commit", "-qm", "change-0")
    monkeypatch.setattr(_external_review.module, "SOURCE_REPO", env.source)
    gateway = _external_review.Gateway(env)
    return _external_review.ExternalReview(
        gateway, source=env.source, state_root=env.home / "review",
        checkout_root=env.home / "clones", poll_seconds=0.01,
        launcher=[_external_review.sys.executable, str(_external_review.Path(__file__).with_name("external_review_child.py"))],
        preflight=_external_review._fake_preflight_pass,
        session_receipt=_external_review._make_fake_session_receipt(env.home / "review"),
    )


class FakeGitHub:
    """GitHub 端口替身：PR、检查、文件与写操作记录。"""
    def __init__(self, lane, *, required=("deepagents/review", "ci-ok"), review_app=5664795):
        self.lane = lane
        self.required = {name: {"deepagents/review": review_app, "ci-ok": 15368}[name] for name in required}
        self.extra_pulls = []
        self.states, self.checks_by_head, self.files, self.calls, self.fail = {}, {}, {}, [], {}
        self.committed = {}  # head → committer 时间；没登记的 head 都按建替身时刚推送（同一时刻，按号码排）
        self.pushed = datetime.now(timezone.utc).isoformat()

    def open_pulls(self):
        return copy.deepcopy([self.lane.gateway.pr, *self.extra_pulls])

    def committed_at(self, head):
        return self.committed.get(head, self.pushed)

    def _pr(self, number):
        return next(p for p in [self.lane.gateway.pr, *self.extra_pulls] if p["number"] == number)

    def pr(self, number):
        if "pr" in self.fail.get(number, ()):
            raise RuntimeError("HTTP 502")
        p = self._pr(number)
        state = {
            "head": p["head"]["sha"],
            "base": p["base"]["sha"],
            "base_ref": p["base"]["ref"],
            "base_repo_id": (p["base"].get("repo") or {}).get("id"),
            "head_repo_id": (p["head"].get("repo") or {}).get("id"),
            "draft": bool(p.get("draft", False)),
            "changed_files": 1,
            "mergeable_state": "clean",
            "auto_merge": False,
        }
        state.update(self.states.get(number, {}))
        return state

    def checks(self, head, bindings):
        assert bindings.get("DevSkim") == 15368 and all(bindings.get(k) == v for k, v in self.required.items())
        return dict(self.checks_by_head.get(head, {}))

    def required_checks(self):
        return dict(self.required)

    def allow_auto_merge(self):
        return False

    def pr_files(self, number):
        return copy.deepcopy(self.files.get(number, [{"filename": ".sandcastle/x.py", "status": "modified", "changes": 1}]))

    def merge(self, number, head):
        self.calls.append(("merge", number, head))

    def update_branch(self, number, head):
        self.calls.append(("update", number, head))

    def disable_auto_merge(self, number):
        self.calls.append(("disable", number))
        if number in self.states:
            self.states[number]["auto_merge"] = False


class Host:
    """进程表与子进程替身。run=True 时 spawn 在进程内同步跑完 review_pr，模拟审查子进程结束。"""
    def __init__(self, lane, *, run=True):
        self.lane, self.run, self.rows, self.spawned, self.next_pid = lane, run, [], [], 4000

    def spawn(self, number, attempt, head, log, base=None):
        self.next_pid += 1
        self.spawned.append((number, attempt, head))
        if self.run:
            self.lane.review_pr(number, attempt, expect_head=head, expect_base=base)
        else:
            self.rows.append((self.next_pid, self.next_pid, "S",
                              " ".join(module.run_review_command(number, attempt, head, "/k", base)[1:])))
        return self.next_pid


def make(lane, *, run=True, github=None, **kwargs):
    host = Host(lane, run=run)
    github = github or FakeGitHub(lane)
    kwargs.setdefault("review_app", lambda: 5664795)  # HOST 现状：审查专用 App，main 的必需检查也绑它
    sweep = Sweep(github, lane, host.spawn, state_root=lane.state_root, rows=lambda: list(host.rows), **kwargs)
    return sweep, host, github


def acts(actions, pr=1810):
    return [a["action"] for a in actions if a.get("pr") == pr]


def green(github, head, **override):
    github.checks_by_head[head] = {"deepagents/review": "success", "ci-ok": "success", "DevSkim": "success", **override}


# ---- 审查派发 ----

def test_new_head_is_reviewed_without_operator(lane):
    sweep, host, _ = make(lane)
    assert acts(sweep.tick()) == ["launch"]
    assert lane.gateway.sent == ["pending", "success"]
    assert acts(sweep.tick()) == ["done"]
    assert len(host.spawned) == 1


def test_one_live_reviewer_per_pr_regardless_of_head(lane):
    """F5：同一 PR 已有审查进程在跑（不论它审哪个 head）就不再派发，免得重复派发撞 run 锁、误报 needs-operator。"""
    sweep, host, _ = make(lane, run=False)
    assert acts(sweep.tick()) == ["launch"]
    lane.gateway.pr["head"]["sha"] = "f" * 40  # 决策后 head 变了
    assert acts(sweep.tick()) == ["running"]
    assert len(host.spawned) == 1


def test_new_head_after_push_gets_its_own_review(lane):
    sweep, host, _ = make(lane)
    sweep.tick()
    (lane.source / "changed-1").write_text("pushed again\n")
    git(lane.source, "commit", "-qam", "push")
    lane.gateway.pr["head"]["sha"] = git(lane.source, "rev-parse", "HEAD")
    assert acts(sweep.tick()) == ["launch"]
    assert len(host.spawned) == 2


def test_main_advance_does_not_rereview_the_same_head(lane):
    """F4：「已审完」按 head 判定；main 前进不把同一 head 拉回 pending、不重开双审。"""
    sweep, host, _ = make(lane)
    sweep.tick()
    git(lane.source, "checkout", "-q", "-b", "main-next", lane.gateway.pr["base"]["sha"])
    (lane.source / "unrelated").write_text("main moved\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "main moved")
    lane.gateway.pr["base"]["sha"] = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-q", lane.gateway.pr["head"]["sha"])
    assert acts(sweep.tick()) == ["done"]
    assert len(host.spawned) == 1 and lane.gateway.sent == ["pending", "success"]


def test_only_stale_on_head_is_reviewed_again_with_next_attempt(lane):
    sweep, host, _ = make(lane)
    sweep.tick()
    row = lane.status(1810)[0]
    path = lane.state_root / "runs" / ReviewTarget(**row["target"]).key / "outcome.json"
    stale = json.loads(path.read_text())
    stale["verdict"] = "STALE"
    stale.pop("publication")
    path.write_text(json.dumps(stale))
    actions = sweep.tick()
    assert acts(actions) == ["launch"] and actions[0]["attempt"] == 2


def test_interrupted_review_resumes_same_attempt_once_then_needs_operator(lane):
    sweep, host, _ = make(lane, run=False)
    sweep.tick()
    lane.target(1810, 1)              # 子进程已登记 attempt 1……
    host.rows.clear()                 # ……然后中断，没有结论
    assert acts(sweep.tick()) == ["resume-review"]
    host.rows.clear()
    assert acts(sweep.tick()) == ["needs-operator"]
    assert [s[1] for s in host.spawned] == [1, 1]


def test_unpublished_outcome_is_resumed_once_then_needs_reconcile(lane):
    """F6：outcome 已存但终态没发布，不算完成；同一 attempt 续跑一次走受管对账与发布，再不成报 needs-reconcile。"""
    sweep, host, _ = make(lane, run=False)
    lane.review_pr(1810)
    row = lane.status(1810)[0]
    path = lane.state_root / "runs" / ReviewTarget(**row["target"]).key / "outcome.json"
    saved = json.loads(path.read_text())
    saved.pop("publication")
    path.write_text(json.dumps(saved))
    assert acts(sweep.tick()) == ["resume-publish"]
    host.rows.clear()
    assert acts(sweep.tick()) == ["needs-reconcile"]


@pytest.mark.parametrize(("published", "verdict", "expected"), [
    (False, None, "needs-operator"),
    (False, "FAILED", "needs-reconcile"),
    (True, "FAILED", "done"),
])
def test_old_contract_is_never_dispatched_as_a_gpt_resume(lane, monkeypatch, published, verdict, expected):
    from pilot1742 import external_review

    sweep, host, _ = make(lane, run=False)
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        target = lane.target(1810, 1)
    folder = lane.state_root / "runs" / target.key
    if verdict:
        outcome = {"verdict": verdict}
        if published:
            outcome["publication"] = {"status": "error"}
        (folder / "outcome.json").write_text(json.dumps(outcome))
    before = list(lane.status(1810))
    for _ in range(2):
        assert acts(sweep.tick()) == [expected]
    assert not host.spawned
    assert lane.status(1810) == before
    assert external_review.POLICY == "external-pr-v2-gpt62"


def test_old_unpublished_outcome_does_not_shadow_newer_gpt_attempt_recovery(lane, monkeypatch):
    """旧合同 A1 有未发布终态，操作员启动 GPT A2 后中断，sweep 应续跑 A2 而非被 A1 遮蔽。"""
    sweep, host, _ = make(lane, run=False)
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        old_target = lane.target(1810, 1)
    old_folder = lane.state_root / "runs" / old_target.key
    (old_folder / "outcome.json").write_text(json.dumps({"verdict": "FAILED"}))
    # 操作员按新合同启动 A2 并中断（仅有 target.json，无 outcome.json）
    new_target = lane.target(1810, 2)
    assert new_target.registered_at_ns > old_target.registered_at_ns
    assert acts(sweep.tick()) == ["resume-review"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 2)]
    host.rows.clear()
    assert acts(sweep.tick()) == ["needs-operator"]


@pytest.mark.parametrize("new_has_outcome,expected_first,expected_second", [
    (False, "resume-review", "needs-operator"),
    (True, "resume-publish", "needs-reconcile"),
])
def test_old_published_outcome_does_not_shadow_newer_gpt_attempt_recovery(
        lane, monkeypatch, new_has_outcome, expected_first, expected_second):
    """旧合同 A1 已发布终态，操作员启动 GPT A2 后中断（含已发 pending 未完结或有结论未发布），sweep 必须续跑 A2 而非误判 done。"""
    sweep, host, _ = make(lane, run=False)
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        old_target = lane.target(1810, 1)
    old_folder = lane.state_root / "runs" / old_target.key
    (old_folder / "outcome.json").write_text(json.dumps({
        "verdict": "PASS", "publication": {"id": 1, "state": "success"},
    }))
    new_target = lane.target(1810, 2)
    assert new_target.registered_at_ns > old_target.registered_at_ns
    if new_has_outcome:
        new_folder = lane.state_root / "runs" / new_target.key
        (new_folder / "outcome.json").write_text(json.dumps({"verdict": "PASS", "state": "success"}))
    assert acts(sweep.tick()) == [expected_first]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 2)]
    host.rows.clear()
    assert acts(sweep.tick()) == [expected_second]


def test_spawner_normalizes_relative_sandcastle_config_file_before_chdir(tmp_path, monkeypatch):
    """spawner 切到 deepagents-pilot 子目录前，先把相对 SANDCASTLE_CONFIG_FILE 按调用方 cwd 规范成绝对路径。"""
    from pathlib import Path
    caller = tmp_path / "host-cwd"
    caller.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setenv("SANDCASTLE_CONFIG_FILE", "deploy/sched.json")
    expected = os.path.abspath("deploy/sched.json")
    captured = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        captured["cwd"] = kwargs.get("cwd")
        return FakeProc()

    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)
    spawn = module.spawner(tmp_path / "key.pem")
    assert spawn(2207, 1, "a" * 40, tmp_path / "spawn.log") == 4242
    assert captured["env"]["SANDCASTLE_CONFIG_FILE"] == expected
    assert Path(captured["cwd"]).name == "deepagents-pilot"


def test_auto_merge_blocks_old_success_while_newer_gpt_attempt_is_pending(lane, monkeypatch):
    """旧合同 A1 已发布 success、新 GPT A2 登记后在发 pending 前中断，auto-merge 不得凭 A1 绿灯合入。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        old_target = lane.target(1810, 1)
    old_folder = lane.state_root / "runs" / old_target.key
    (old_folder / "outcome.json").write_text(json.dumps({
        "verdict": "PASS", "publication": {"id": 1, "state": "success"},
    }))
    new_target = lane.target(1810, 2)
    assert new_target.registered_at_ns > old_target.registered_at_ns

    # 1. 首轮续跑 A2，绝不凭旧 A1 的 success 合入
    actions = sweep.tick()
    assert acts(actions) == ["resume-review", "waiting"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 2)]
    assert github.calls == []
    assert any(a.get("pending_latest_attempt") is True for a in actions)

    # 2. 次轮 A2 仍未完结（needs-operator），依然绝不合入
    host.rows.clear()
    actions2 = sweep.tick()
    assert acts(actions2) == ["needs-operator", "waiting"]
    assert github.calls == []

    # 3. 直到 A2 完结并发布 PASS 后才不再 waiting，因服务端不支持 expected_base_ref 转人工确认且不发起自动合入
    new_folder = lane.state_root / "runs" / new_target.key
    (new_folder / "outcome.json").write_text(json.dumps({
        "verdict": "PASS", "state": "success", "publication": {"id": 2, "state": "success", "sha": head},
    }))
    actions3 = sweep.tick()
    assert acts(actions3) == ["done", "needs-human-confirm"]
    assert actions3[-1]["gated"] == ["base-ref-not-server-bound"]
    assert github.calls == []


def test_recovery_branch_selects_latest_registered_attempt_even_with_lower_number(lane, monkeypatch):
    """先登记旧合同 A3、再登记新合同 A2（编号更小但 registered_at_ns 更新）均中断时，恢复分支选最新的 A2。"""
    sweep, host, _ = make(lane, run=False)
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        older = lane.target(1810, 3)
    newer = lane.target(1810, 2)
    assert newer.registered_at_ns > older.registered_at_ns
    assert acts(sweep.tick()) == ["resume-review"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 2)]


def test_preflight_rate_limits_feed_global_sweep_backoff_without_occupying_attempt(lane, monkeypatch):
    """预检命中 HTTP 429/rate_limit 时不占 attempt、不发状态，但纳入全局限流退避，拦住后续排队 PR。"""
    import time

    from pilot1742.delivery import EffectPending

    github = FakeGitHub(lane)
    second = copy.deepcopy(lane.gateway.pr)
    second["number"] = 1811
    github.extra_pulls = [second]
    t_now = time.time()
    clock = {"t": t_now + 5}
    sweep, host, _ = make(lane, run=False, github=github, now=lambda: datetime.fromtimestamp(clock["t"], timezone.utc))

    rate_limited_report = {
        "returncode": 2,
        "report": {
            "kind": "review-preflight", "is_review_result": False, "ready": False,
            "checks": [
                {"name": f"roundtrip:{MODELS[0]}", "ok": False,
                 "detail": {"http_status": 429, "error": {"class": "rate_limit"}}},
            ],
        },
    }
    lane.preflight = lambda _t: rate_limited_report
    for _ in range(2):
        with pytest.raises(EffectPending, match="上游限流"):
            lane.review_pr(1810, 1)
    assert lane.status(1810) == [] and lane.gateway.sent == []

    # 连续 2 次预检限流触发全局退避：两张 PR 均 review-backoff，不再派子进程
    actions = sweep.tick()
    assert acts(actions, 1810) == acts(actions, 1811) == ["review-backoff"] and host.spawned == []
    assert any(a.get("action") == "rate-limit-backoff" for a in actions)

    # 后续预检通过后解除退避
    lane.preflight = _external_review._fake_preflight_pass
    target = lane.target(1810, 1)
    assert target.attempt == 1
    clock["t"] = time.time() + 10
    assert sweep.rate_limit_backoff() is None


def test_auto_merge_rechecks_latest_attempt_under_pr_lock_before_merging(lane, monkeypatch):
    """同 head 新登记了 A2 时，即使旧 A1 已有当前合同 PASS，规划也必须报 waiting(pending_latest_attempt=True)；
    即使在规划之后并发登记 A2，因关闭自动发起 PUT /pulls/{n}/merge，也绝不会凭旧 A1 抢跑合入，且 read_merge_handoff 立即过滤。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    real_plan_one = sweep._plan_one
    raced = {"done": False}
    def plan_then_register(*args, **kwargs):
        res = real_plan_one(*args, **kwargs)
        if not raced["done"]:
            raced["done"] = True
            lane.target(1810, 2)  # 模拟规划之后并发登记的新 attempt（未发 pending）
        return res
    monkeypatch.setattr(sweep, "_plan_one", plan_then_register)
    actions = sweep.tick()
    assert github.calls == []
    assert any(a["action"] == "needs-human-confirm" and a.get("gated") == ["base-ref-not-server-bound"] for a in actions)
    # 下一轮（已存在未完结 A2）：直接进入 waiting(pending_latest_attempt=True)
    actions2 = sweep.tick()
    assert github.calls == []
    assert any(a["action"] == "waiting" and a.get("pending_latest_attempt") is True for a in actions2)


def test_preflight_pass_does_not_mask_consecutive_formal_rate_limits(lane):
    """预检成功记录绝不能隔断连续两次正式审查 429 触发的 30 分钟全局退避。"""
    import time

    github = FakeGitHub(lane)
    base_t = time.time()
    clock = {"t": base_t + 100}
    sweep, host, _ = make(lane, run=False, github=github, now=lambda: datetime.fromtimestamp(clock["t"], timezone.utc))
    # 历史上有过预检限流日志，随后顺序为：预检成功 -> 正式审阅 429 -> 预检成功 -> 正式审阅 429
    finished_run(lane, "11", base_t + 20, rate_limited=True)
    finished_run(lane, "12", base_t + 60, rate_limited=True)
    (lane.state_root / module.PREFLIGHT_RATE_LIMIT_FILE).write_text(json.dumps({
        "events": [
            {"at": base_t + 1, "id": "pf-0", "rate_limited": True, "models": [MODELS[0]]},
            {"at": base_t + 10, "id": "pf-1", "rate_limited": False, "models": list(MODELS)},
            {"at": base_t + 50, "id": "pf-2", "rate_limited": False, "models": list(MODELS)},
            {"at": base_t + 70, "id": "pf-3", "rate_limited": False, "models": list(MODELS)},
        ],
    }))
    backoff = sweep.rate_limit_backoff()
    assert backoff is not None and backoff["runs"] == ["run-12", "run-11"]
    assert acts(sweep.tick(), 1810) == ["review-backoff"] and host.spawned == []


def test_reuse_fallback_preflight_failure_uses_launch_backoff_not_one_shot_resume(lane, monkeypatch):
    """沿用登记后来源失效且预检失败（未发 pending、未建工蜂目录）：按 launch-backoff 重试，不消耗唯一一次审查续跑。"""
    import dataclasses

    sweep, host, _ = make(lane, run=False)
    target = dataclasses.replace(lane.target(1810, 1), reuse_planned=True)
    folder = lane.state_root / "runs" / target.key
    (folder / "target.json").write_text(json.dumps(dataclasses.asdict(target)))

    # 1. 首轮按 launch 重派同一 attempt（非 resume-review，不写 .resumes）
    assert acts(sweep.tick()) == ["launch"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 1)]
    assert not sweep._resumes(1810, target.head_sha, 1, target.base_sha).exists()

    # 2. 若仍遇预检故障退出，退避期内报 launch-backoff，不卡死在 needs-operator
    host.rows.clear()
    assert acts(sweep.tick()) == ["launch-backoff"]
    assert not sweep._resumes(1810, target.head_sha, 1, target.base_sha).exists()

    # 3. 退避期满后自动重派同一 attempt，而非永久需人工介入
    marker = sweep.folder / f"p1810-{target.head_sha}-{target.base_sha}-a1.launched"
    old = marker.stat().st_mtime - module.LAUNCH_BACKOFF_SECONDS - 5
    os.utime(marker, (old, old))
    assert acts(sweep.tick()) == ["launch"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 1), (1810, 1)]


def test_explicit_reattempt_by_operator_is_left_alone(lane):
    sweep, host, _ = make(lane)
    sweep.tick()
    lane.review_pr(1810, 2)
    assert acts(sweep.tick()) == ["done"]
    assert len(host.spawned) == 1


def test_concurrency_cap_counts_every_live_reviewer(lane):
    github = FakeGitHub(lane)
    second = copy.deepcopy(lane.gateway.pr)
    second["number"] = 1811
    github.extra_pulls = [second]
    sweep, host, _ = make(lane, run=False, github=github, max_running=1)
    actions = sweep.tick()
    assert acts(actions, 1810) == ["launch"] and acts(actions, 1811) == ["queued"]


# ---- 限流退避 ----

T0 = datetime(2026, 11, 9, 4, 30, tzinfo=timezone.utc).timestamp()


def finished_run(lane, name, ended, *, rate_limited=True, verdict=None, reviews=True):
    """另一个 PR 的已完结审查 run（不与 1810 的 status 混淆）：opus 回执按需记 failure_code=rate_limited。"""
    folder = lane.state_root / "runs" / f"r1150335160-p9{name}-x-a1"
    for model in MODELS:
        (folder / model).mkdir(parents=True)
        limited = rate_limited and model == MODELS[-1]
        (folder / model / "receipt.json").write_text(json.dumps(
            {"status": "failed" if limited else "completed", **({"failure_code": "rate_limited"} if limited else {})}))
    verdict = verdict or ("FAILED" if rate_limited else "PASS")
    outcome = folder / "outcome.json"
    outcome.write_text(json.dumps({"run_id": f"run-{name}", "verdict": verdict,
                                   "reviews": [{"model": m} for m in MODELS] if reviews else []}))
    os.utime(outcome, (ended, ended))


def test_two_rate_limited_runs_hold_new_reviews_for_30_minutes_with_one_log_line(lane, capsys):
    github = FakeGitHub(lane)
    second = copy.deepcopy(lane.gateway.pr)
    second["number"] = 1811
    github.extra_pulls = [second]
    clock = {"t": T0}
    sweep, host, _ = make(lane, run=False, github=github, now=lambda: datetime.fromtimestamp(clock["t"], timezone.utc))
    finished_run(lane, "01", T0 - 600)
    finished_run(lane, "02", T0 - 300)
    actions = sweep.tick()
    assert acts(actions, 1810) == acts(actions, 1811) == ["review-backoff"] and host.spawned == []
    module.report(actions, "review-sweep ")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1 and lines[0].startswith('review-sweep {"action": "rate-limit-backoff"')
    logged = json.loads(lines[0].removeprefix("review-sweep "))
    assert logged["runs"] == ["run-02", "run-01"] and logged["held"] == [1810, 1811]
    assert logged["until"] == datetime.fromtimestamp(T0 - 300 + 1800, timezone.utc).isoformat()
    clock["t"] = T0 - 300 + 1799
    assert acts(sweep.tick(), 1810) == ["review-backoff"] and host.spawned == []
    clock["t"] = T0 - 300 + 1800  # 自最后一个限流 run 完结满 30 分钟：解除
    actions = sweep.tick()
    assert acts(actions, 1810) == ["launch"] and not any(a["action"] == "rate-limit-backoff" for a in actions)
    assert [s[0] for s in host.spawned] == [1810, 1811]


@pytest.mark.parametrize("history", ["one-limited", "latest-ok", "only-one-run"])
def test_backoff_needs_the_last_two_completed_runs_both_rate_limited(lane, history):
    sweep, host, _ = make(lane, run=False, now=lambda: datetime.fromtimestamp(T0, timezone.utc))
    if history == "one-limited":
        finished_run(lane, "01", T0 - 600, rate_limited=False)
        finished_run(lane, "02", T0 - 300)
    elif history == "latest-ok":
        finished_run(lane, "01", T0 - 900)
        finished_run(lane, "02", T0 - 600)
        finished_run(lane, "03", T0 - 300, rate_limited=False)
    else:
        finished_run(lane, "01", T0 - 300)
    assert acts(sweep.tick()) == ["launch"]


def test_stale_and_reused_runs_are_not_completed_reviews_for_backoff(lane):
    sweep, host, _ = make(lane, run=False, now=lambda: datetime.fromtimestamp(T0, timezone.utc))
    finished_run(lane, "01", T0 - 900)
    finished_run(lane, "02", T0 - 600)
    finished_run(lane, "03", T0 - 300, rate_limited=False, verdict="STALE")
    finished_run(lane, "04", T0 - 200, rate_limited=False, reviews=False)  # 沿用 PASS：没派模型
    assert acts(sweep.tick()) == ["review-backoff"] and host.spawned == []


def test_merges_and_withdrawals_continue_during_rate_limit_backoff(lane):
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    pass_target = ReviewTarget(**passed["target"])
    pass_outcome = lane.state_root / "runs" / pass_target.key / "outcome.json"
    os.utime(pass_outcome, (T0 - 1200, T0 - 1200))
    (lane.state_root / module.PREFLIGHT_RATE_LIMIT_FILE).unlink(missing_ok=True)
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    gated = copy.deepcopy(lane.gateway.pr)
    gated["number"] = 1811
    github.extra_pulls = [gated]
    github.files[1811] = [{"filename": ".env", "status": "modified", "changes": 1}]
    github.states[1811] = {"auto_merge": True}
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True,
                          now=lambda: datetime.fromtimestamp(T0, timezone.utc))
    green(github, head)
    finished_run(lane, "01", T0 - 600)
    finished_run(lane, "02", T0 - 300)
    actions = sweep.tick()
    assert any(a["action"] == "rate-limit-backoff" for a in actions) and host.spawned == []
    a1810 = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "needs-human-confirm")
    a1811 = next(a for a in actions if a.get("pr") == 1811 and a["action"] == "needs-human-confirm")
    assert a1810["gated"] == ["base-ref-not-server-bound"]
    assert a1811["gated"] == {"secrets-or-credentials": [".env"]}
    assert github.calls == [("disable", 1811)]


@pytest.mark.parametrize("change", ["draft", "foreign", "stale"])
def test_drafts_foreign_and_stale_pulls_are_not_reviewed(lane, change):
    if change == "draft":
        lane.gateway.pr["draft"] = True
    elif change == "foreign":
        lane.gateway.pr["head"]["repo"]["id"] = 1
    else:
        lane.gateway.pr["updated_at"] = "2026-01-01T00:00:00Z"
    sweep, host, _ = make(lane, now=lambda: datetime(2026, 11, 7, tzinfo=timezone.utc))
    assert acts(sweep.tick()) == [{"draft": "draft", "foreign": "foreign-head", "stale": "stale-pr"}[change]]
    assert host.spawned == []


def test_missing_objects_wait_for_owner_sync(lane):
    lane.gateway.pr["head"]["sha"] = "f" * 40
    synced = []
    sweep, host, _ = make(lane)
    assert acts(sweep.tick()) == ["needs-source-sync"]
    sweep.sync = lambda number, base, head: synced.append((number, base, head))
    assert acts(sweep.tick()) == ["needs-source-sync"] and synced and host.spawned == []


def test_reviewer_identity_rejects_other_prs_zombies_and_unrelated_commands():
    command = " ".join(module.run_review_command(5, 1, "a" * 40, "/k")[1:])
    assert reviewing([(42, 42, "S", command)]) == {5}
    assert reviewing([(42, 42, "Z", command)]) == set()
    assert reviewing([(42, 42, "S", command.replace("--pr 5 ", "--pr 50 "))]) == {50}
    assert reviewing([(42, 42, "S", "-m pilot1742.external_review review-pr --pr 7 --attempt 1")]) == {7}
    assert reviewing([(42, 42, "S", "vim notes.txt")]) == set()


def test_run_review_refuses_when_head_moved(monkeypatch):
    """F5 + R32（Astra P2）：子进程绑定决策时的 head、base 与非 draft；任一已变就不审（不登记、不派模型），
    匹配时带 --reject-draft 透传给 external_review 供登记前再次复核。"""
    called = []
    monkeypatch.setattr("pilot1742.external_review.main", lambda argv: called.append(argv) or 0)
    class GitHub:
        def __init__(self, *, draft=False):
            self.draft = draft
        def pr(self, number):
            return {"head": "b" * 40, "base": "c" * 40, "draft": self.draft}
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "a" * 40, "--private-key", "/k"],
                             GitHub()) == 3
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "b" * 40,
                              "--expect-base", "d" * 40, "--private-key", "/k"], GitHub()) == 3
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "b" * 40,
                              "--expect-base", "c" * 40, "--private-key", "/k"], GitHub(draft=True)) == 3
    assert called == []
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "b" * 40,
                              "--expect-base", "c" * 40, "--private-key", "/k"], GitHub()) == 0
    assert called == [["review-pr", "--pr", "5", "--attempt", "1", "--private-key", "/k",
                       "--expect-head", "b" * 40, "--reject-draft", "--expect-base", "c" * 40]]


def test_behind_head_is_caught_up_before_review(lane):
    """F4：启用合入前分类时，落后的 PR 不重审旧 head（behind-awaiting-update），因 update-branch 缺 expected_base_ref 报 behind-waiting 且不自动写 PR 分支。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["behind-awaiting-update", "behind-waiting"] and host.spawned == []
    assert actions[-1]["queue_head"] is True and github.calls == []


# ---- 合入 ----

def test_no_merge_unless_ci_ok_is_required(lane):
    github = FakeGitHub(lane, required=("deepagents/review",))
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    green(github, lane.gateway.pr["head"]["sha"])
    actions = sweep.tick()
    assert any(a["action"] == "auto-merge-unsafe" for a in actions)
    assert not [c for c in github.calls if c[0] == "merge"]


def test_merges_only_exact_head_with_review_ci_ok_and_devskim_green(lane):
    """F1：不预挂 auto-merge；三项未全绿时 waiting；三项全绿、清单可判定且非人工确认两类时，
    因 GitHub 合入接口不支持服务端 expected_base_ref，输出 needs-human-confirm 并撤原生 auto-merge，不自动合入。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    green(github, head, DevSkim="pending")
    assert "waiting" in acts(sweep.tick())
    assert github.calls == []
    green(github, head)
    github.states[1810] = {"auto_merge": True}
    actions = sweep.tick()
    confirm = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "needs-human-confirm")
    assert confirm["gated"] == ["base-ref-not-server-bound"]
    assert github.calls == [("disable", 1810)]


def test_moved_head_is_not_merged(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {"head": "0" * 40}
    green(github, "0" * 40)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    assert "head-moved" in acts(sweep.tick()) and github.calls == []


@pytest.mark.parametrize(("path", "category"), [
    ("rust/src/bin/x_execution_session.rs", "live-trading-or-funds"),   # 用户原例：下单逻辑
    ("rust/src/economic_session/book.rs", "live-trading-or-funds"),     # 账本
    ("trading_system/config/broker_config.py", "live-trading-or-funds"),  # F3：IBKR/Hyperliquid 实盘配置
    ("analysis/buy_28316_warrant.py", "live-trading-or-funds"),         # F3：TWS 7496 下单脚本
    ("trading_system/live/runner.py", "live-trading-or-funds"),
    ("deploy/.env.production", "secrets-or-credentials"),
    ("keys/newchanlun-app.pem", "secrets-or-credentials"),
    ("config/credentials.json", "secrets-or-credentials"),
])
def test_human_gated_pr_is_never_merged_and_armed_auto_merge_is_withdrawn(lane, path, category):
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    github.states[1810] = {"auto_merge": True, "changed_files": 2}
    github.files[1810] = [{"filename": ".sandcastle/a.py", "status": "modified", "changes": 1},
                          {"filename": path, "status": "modified", "changes": 1}]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a["action"] == "needs-human-confirm")
    assert result["gated"] == {category: [path]}
    assert github.calls == [("disable", 1810)]


@pytest.mark.parametrize("path", [
    ".sandcastle/deepagents-pilot/pilot1742/external_review.py", ".sandcastle/codex-child.ts",
    "docs/adr/0061-x.md", ".github/copilot-instructions.md", ".github/PULL_REQUEST_TEMPLATE.md",
    "topological-computation/frontend/src/tokens.ts", "rust/src/diagnostic_fill.rs", "docs/ci_secrets.md",
    "src/newchan/data_ibkr.py", "rust/src/bin/s_structure_session.rs", "analysis/some_research.py"])
def test_ordinary_code_and_docs_are_not_human_gated(path):
    assert human_gated([path]) == {}


def test_truncated_file_list_falls_back_to_exact_local_diff(lane):
    """F2：接口清单达到 3000 上限或与 changed_files 不符时不放行；用本地精确 diff 看到排在后面的人工确认类文件。"""
    (lane.source / "trading_system" / "live").mkdir(parents=True)
    (lane.source / "trading_system" / "live" / "runner.py").write_text("ORDER = 1\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "touch live runner")
    head = git(lane.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = head
    github = FakeGitHub(lane)
    github.states[1810] = {"changed_files": 3001}
    github.files[1810] = [{"filename": f".chanlun/review-results/a/f{i:05d}.json", "status": "removed", "changes": 1}
                          for i in range(3000)]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "needs-human-confirm")
    assert "trading_system/live/runner.py" in result["gated"]["live-trading-or-funds"]
    assert not [c for c in github.calls if c[0] == "merge"]


def test_incomplete_file_list_without_local_objects_is_evidence_insufficient(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {"changed_files": 3001, "base": "e" * 40, "auto_merge": True}
    github.files[1810] = [{"filename": f"x/{i}", "status": "added", "changes": 1} for i in range(3000)]
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a["action"] == "evidence-insufficient")
    assert "文件清单不全" in result["reason"]
    assert github.calls == [("disable", 1810)]  # 不合入；挂着的 auto-merge 撤掉；不升级成人工确认


def test_one_prs_failure_does_not_stop_others(lane):
    """F1：单个 PR 的异常隔离，不中止其他 PR 的处理。"""
    github = FakeGitHub(lane)
    other = copy.deepcopy(lane.gateway.pr)
    other["number"] = 1805
    github.extra_pulls = [other]
    github.fail[1805] = {"pr"}
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions, 1805) == ["error", "evidence-insufficient"]   # 状态读不到：失败关闭
    assert ("disable", 1805) in github.calls
    assert any(a.get("pr") == 1810 and a["action"] == "needs-human-confirm"
               and a.get("gated") == ["base-ref-not-server-bound"] for a in actions)


def test_main_loop_survives_tick_errors(monkeypatch, capsys):
    """F1b：整轮失败只记下，循环不退出。"""
    ticks = []
    class Boom(Sweep):
        def __init__(self, *args, **kwargs):
            pass
        def tick(self):
            ticks.append(1)
            if len(ticks) == 1:
                raise KeyError("files")
            raise SystemExit(0)  # 第二轮到达即说明循环活下来了
    monkeypatch.setattr(module, "Sweep", Boom)
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    with pytest.raises(SystemExit):
        module.main(["--private-key", "/k", "--loop", "180"])
    assert len(ticks) == 2 and "tick-error" in capsys.readouterr().out


def test_behind_pr_with_failed_or_inflight_review_is_not_caught_up(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    github.checks_by_head[lane.gateway.pr["head"]["sha"]] = {"deepagents/review": "failure"}
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    assert "behind-waiting" in acts(sweep.tick()) and github.calls == []


def test_sweep_carries_no_app_identity_and_uses_shared_repo():
    """F8：sweep 不构造 App 身份（审查身份归 external_review）；仓库名取共享的 workunit.REPO。"""
    from pathlib import Path

    from pilot1742 import workunit
    source = Path(module.__file__).read_text()
    assert "AppIdentity" not in source and "175617978" not in source and "179444545" not in source
    assert module.GhCli().repository == workunit.REPO


@pytest.mark.skipif(not hasattr(_external_review, "_advance_main"), reason="需要 #1913 的补丁沿用与 _advance_main")
def test_main_advance_then_catch_up_costs_no_extra_model_calls(lane, env):
    """组合（独审 test_zz_1939_x_1913）：审过 → main 前进（不重审同 head）→ 先追平 → 新 head 按补丁沿用，模型只调用一轮。"""
    github = FakeGitHub(lane)
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    assert "launch" in acts(sweep.tick())
    first = lane.gateway.pr["head"]["sha"]
    green(github, first, **{"ci-ok": "pending"})
    launches = (lane.state_root / "runs" / "launches").read_text()
    _external_review._advance_main(lane, env)            # main 前进且 PR 追平出新 head（模拟 update-branch 落地）
    caught_up = lane.gateway.pr["head"]["sha"]
    lane.gateway.pr["head"]["sha"] = first               # update 落地前：PR 仍是旧 head，落后
    github.states[1810] = {"mergeable_state": "behind"}
    actions = sweep.tick()
    assert acts(actions) == ["done", "behind-waiting"]    # 不重审旧 head；不自动写 PR 分支，等外部追平
    lane.gateway.pr["head"]["sha"] = caught_up
    github.states[1810] = {"mergeable_state": "clean"}
    actions = sweep.tick()
    assert "launch" in acts(actions)
    assert (lane.state_root / "runs" / "launches").read_text() == launches   # 新 head 沿用，不再调用模型
    # 目录名以 base 开头，按名字排序取 [-1] 是随机的；按 head 找追平后的那个 run
    assert next(r for r in lane.status(1810) if r["target"]["head_sha"] == caught_up)["outcome"].get("reused_from")


# ---- 第二轮独审（d0fa06f9）I1/I2 与 Nit ----

def _advance_main_mid_flight(lane):
    git(lane.source, "checkout", "-q", "-b", "main-moved", lane.gateway.pr["base"]["sha"])
    (lane.source / "unrelated-moved").write_text("main moved\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", "main moved")
    lane.gateway.pr["base"]["sha"] = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-q", lane.gateway.pr["head"]["sha"])


def _stale_mid_flight(lane, github, **kwargs):
    """审查进行中 main 前进：终态判 Stale，GitHub 上该 head 停在 pending，strict 下 PR 落后。"""
    sweep, host, _ = make(lane, github=github, **kwargs)
    head = lane.gateway.pr["head"]["sha"]
    lane.gateway.after_write = lambda: lane.gateway.sent == ["pending"] and _advance_main_mid_flight(lane)
    assert "launch" in acts(sweep.tick())
    lane.gateway.after_write = None
    assert lane.gateway.sent == ["pending"] and lane.status(1810)[-1]["outcome"]["verdict"] == "STALE"
    github.checks_by_head[head] = {"deepagents/review": "pending", "ci-ok": "success", "DevSkim": "success"}
    github.states[1810] = {"mergeable_state": "behind"}
    return sweep, host, head


def test_stale_mid_flight_behind_pr_is_caught_up_not_deadlocked(lane):
    """I1：GitHub 上停住的 pending 不再挡队列识别；本地无在途审查时标为队首 behind-waiting 且不自动写 PR 分支。"""
    github = FakeGitHub(lane)
    sweep, host, head = _stale_mid_flight(lane, github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["behind-awaiting-update", "behind-waiting"]
    assert actions[-1]["reviewing"] is False and actions[-1]["queue_head"] is True
    assert github.calls == [] and len(host.spawned) == 1


def test_live_local_reviewer_still_blocks_catch_up(lane):
    """I1 反向：本地确有该 PR 的审查进程在跑时，落后也不追平。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    host.rows.append((4999, 4999, "S", " ".join(module.run_review_command(1810, 1, "a" * 40, "/k")[1:])))
    result = next(a for a in sweep.tick() if a["action"] == "behind-waiting")
    assert result["reviewing"] is True and github.calls == []


BOUND = [{"context": "deepagents/review", "app_id": 5486877}, {"context": "ci-ok", "app_id": 15368}]


@pytest.mark.parametrize(("rules", "trusted"), [
    ({"strict": True, "checks": BOUND}, {"deepagents/review": 5486877, "ci-ok": 15368}),
    ({"strict": False, "checks": BOUND}, {}),
    ({"strict": True, "checks": [BOUND[0], {"context": "ci-ok", "app_id": None}, {"context": "x", "app_id": -1}]},
     {"deepagents/review": 5486877}),
])
@pytest.mark.parametrize("enforce_admins", [True, False])
def test_required_checks_count_only_strict_enforced_and_app_bound(monkeypatch, rules, trusted, enforce_admins):
    """I2：strict 关着、enforce_admins 关着、允许强推或允许删分支都一个都不算；没绑定来源 app 的检查也不算。"""
    cli = module.GhCli("Newchanlun/NewChanlun")
    protection = {
        "required_status_checks": rules,
        "enforce_admins": {"enabled": enforce_admins},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }
    calls = []
    monkeypatch.setattr(cli, "_gh", lambda *args: calls.append(args) or json.dumps(protection))
    assert cli.required_checks() == (trusted if enforce_admins else {})
    assert calls == [("api", "repos/Newchanlun/NewChanlun/branches/main/protection")]
    for bad_key in ("allow_force_pushes", "allow_deletions"):
        bad = {**protection, bad_key: {"enabled": True}}
        monkeypatch.setattr(cli, "_gh", lambda *args, p=bad: json.dumps(p))
        assert cli.required_checks() == {}


def test_child_dying_before_registration_backs_off(lane):
    """Nit 2：子进程登记前就退出，同一 attempt 退避一段时间再派，不每轮派一个必死的子进程。"""
    sweep, host, _ = make(lane, run=False)
    assert acts(sweep.tick()) == ["launch"]
    host.rows.clear()  # 子进程没登记就退出
    assert acts(sweep.tick()) == ["launch-backoff"] and len(host.spawned) == 1
    for marker in (lane.state_root / "sweep").glob("*.launched"):
        old = marker.stat().st_mtime - module.LAUNCH_BACKOFF_SECONDS - 1
        os.utime(marker, (old, old))
    assert acts(sweep.tick()) == ["launch"] and len(host.spawned) == 2


@pytest.mark.parametrize("loop", ["60", "-5", "nan", "inf"])
def test_loop_interval_must_respect_api_rate_limit(loop):
    """r3 Nit 2：每轮每个 PR 约 4 次读接口；循环间隔低于 3 分钟会超过 GitHub 每小时 5000 次的核心限额。
    负数不得被当成单轮，nan 不得混过校验到 sleep 才崩；inf 会让循环永不再跑，同样拒绝。"""
    with pytest.raises(SystemExit):
        module.main(["--private-key", "/k", "--loop", loop])


@pytest.mark.parametrize("path", ["deploy/.envrc", ".netrc", "web/.npmrc", "home/.ssh/id_ed25519", "id_rsa",
                                  "keys/AuthKey_ABC.p8"])
def test_more_credential_files_are_human_gated(path):
    assert human_gated([path]) == {"secrets-or-credentials": [path]}


# ---- 人工确认只剩两类（用户 2026-11-07、11-08 裁定：CI 与分支保护配置不再要人工确认） ----

CI_ONLY = [".github/workflows/ci.yml", ".github/workflows/devskim.yml", ".github/actions/setup/action.yml",
           ".github/scripts/ci_plan.py", ".github/devskim-baseline.json", ".github/devskim-reviewed-1488.json",
           ".github/ci-manifest.txt", "scripts/devskim_sarif_gate.sh", "scripts/devskim_reviewed_false_positives.py"]


@pytest.mark.parametrize("path", CI_ONLY)
def test_ci_only_pr_auto_merges(lane, path):
    """负控：只改 CI 或 DevSkim 配置的 PR 不命中人工确认两类（human_gated 为空），
    最终仅因 GitHub 合入接口缺 expected_base_ref 转人工确认而非命中两类。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    github.files[1810] = [{"filename": path, "status": "modified", "changes": 3}]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "needs-human-confirm")
    assert result["gated"] == ["base-ref-not-server-bound"]
    assert github.calls == []
    assert human_gated([path]) == {}


def test_ci_change_next_to_live_funds_or_credentials_still_blocks(lane):
    """CI 不再拦，但同一 PR 里夹带的另两类照样拦，且只列这两类。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"changed_files": 3, "auto_merge": True}
    github.files[1810] = [{"filename": p, "status": "modified", "changes": 1}
                          for p in (".github/workflows/ci.yml", "rust/src/trading/order.rs", "deploy/.env")]
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a["action"] == "needs-human-confirm")
    assert result["gated"] == {"live-trading-or-funds": ["rust/src/trading/order.rs"],
                               "secrets-or-credentials": ["deploy/.env"]}
    assert github.calls == [("disable", 1810)]


def test_only_two_categories_remain():
    assert set(module.HUMAN_GATED) == {"live-trading-or-funds", "secrets-or-credentials"}


# ---- 只给队首追平（CI 节流） ----

def _more_pulls(lane, github, numbers):
    """同仓的其他 PR，各有自己的 head（f"{号码:040d}"），检查结论互不串。"""
    for number in numbers:
        other = copy.deepcopy(lane.gateway.pr)
        other["number"] = number
        other["head"]["sha"] = f"{number:040d}"
        github.extra_pulls.append(other)


def updates(github):
    return [c for c in github.calls if c[0] == "update"]


def test_only_queue_head_is_caught_up(lane):
    """三个落后的 PR：仅号码最小的标为 queue_head=True（不自动写分支）；队首在等 CI（不落后）时仍占队首。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811, 1812])
    for number in (1810, 1811, 1812):
        github.states[number] = {"mergeable_state": "behind"}
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert github.calls == []
    assert next(a for a in actions if a.get("pr") == 1810 and a["action"] == "behind-waiting")["queue_head"] is True
    assert next(a for a in actions if a.get("pr") == 1811 and a["action"] == "behind-waiting")["queue_head"] is False
    assert next(a for a in actions if a.get("pr") == 1812 and a["action"] == "behind-waiting")["queue_head"] is False
    github.states[1810] = {"mergeable_state": "blocked"}  # 队首已追平，CI 在跑
    actions = sweep.tick()
    assert github.calls == []
    assert next(a for a in actions if a.get("pr") == 1810 and a["action"] == "waiting")["queue_head"] is True
    assert next(a for a in actions if a.get("pr") == 1811 and a["action"] == "behind-waiting")["queue_head"] is False


@pytest.mark.parametrize("stuck", ["review-failure", "dirty", "ci-failure", "needs-operator"])
def test_stuck_pr_does_not_hold_the_queue_head(lane, stuck):
    """队首卡住（独审已判失败、冲突、不落后却 CI 失败、审查要操作员处理）时，下一个落后的 PR 接替 queue_head=True。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    head = lane.gateway.pr["head"]["sha"]
    github.states[1811] = {"mergeable_state": "behind"}
    github.states[1810] = {"mergeable_state": {"review-failure": "behind", "dirty": "dirty"}.get(stuck, "blocked")}
    if stuck == "review-failure":
        github.checks_by_head[head] = {"deepagents/review": "failure"}
    elif stuck == "ci-failure":
        github.checks_by_head[head] = {"ci-ok": "failure"}
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    if stuck == "needs-operator":
        sweep.decide = lambda pr, *rest: (("needs-operator", None) if pr["number"] == 1810
                                          else ("behind-awaiting-update", None))
    actions = sweep.tick()
    assert github.calls == []
    assert next(a for a in actions if a.get("pr") == 1811 and a["action"] == "behind-waiting")["queue_head"] is True


def test_never_merges_without_both_required_checks_green_on_exact_head(lane):
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    for missing in ({"ci-ok": "pending"}, {"ci-ok": None}, {"deepagents/review": "pending"},
                    {"deepagents/review": None}):
        green(github, head, **missing)
        github.checks_by_head[head] = {k: v for k, v in github.checks_by_head[head].items() if v is not None}
        assert "merged" not in acts(sweep.tick())
    del github.checks_by_head[head]
    green(github, "9" * 40)  # 别的 head 全绿不算
    assert "merged" not in acts(sweep.tick()) and github.calls == []


# ---- executor serve 每轮钩子 ----

class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def _counting(sweep):
    ticks = []
    original = sweep.tick
    def tick():
        ticks.append(1)
        return original()
    sweep.tick = tick
    return ticks


def test_serve_round_runs_one_sweep_per_round_and_logs_one_line_per_action(lane, capsys):
    clock = Clock()
    github = FakeGitHub(lane)
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    ticks = _counting(sweep)
    hook = ServeRound(sweep, clock=clock)
    logged = []
    for _ in range(3):
        actions = hook()
        assert actions is not None
        logged += [a for a in actions if a["action"] not in module.QUIET]
        clock.now += module.MIN_LOOP_SECONDS
    assert len(ticks) == 3
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line.removeprefix("review-sweep ")) for line in lines] == logged
    assert all(line.startswith("review-sweep {") for line in lines) and "needs-human-confirm" in [a["action"] for a in logged]


def test_serve_round_respects_interval_across_restarts(lane):
    """serve 每 60 秒一轮、launchd 还会重启进程：两次 sweep 至少相隔 MIN_LOOP_SECONDS，时间记在磁盘上。"""
    clock = Clock()
    sweep, _, _ = make(lane, run=False)
    ticks = _counting(sweep)
    assert ServeRound(sweep, clock=clock)() is not None
    clock.now += 60
    assert ServeRound(sweep, clock=clock)() is None   # 新进程、同一状态目录：未到间隔，不跑
    clock.now += module.MIN_LOOP_SECONDS
    assert ServeRound(sweep, clock=clock)() is not None
    assert len(ticks) == 2


@pytest.mark.parametrize(("broken", "source"), [("open_pulls", "github open pulls"),
                                                 ("rows", "host process table")])
def test_serve_round_survives_unreadable_source_and_names_it(lane, capsys, broken, source):
    import subprocess
    clock = Clock()
    github = FakeGitHub(lane)
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    healthy = getattr(github if broken == "open_pulls" else sweep, broken)
    def boom():
        raise subprocess.CalledProcessError(1, ["gh", "api"], stderr="HTTP 502")
    setattr(github if broken == "open_pulls" else sweep, broken, boom)
    hook = ServeRound(sweep, clock=clock)
    assert hook() is None                              # 不抛出：serve 循环照常
    line = json.loads(capsys.readouterr().out.strip().removeprefix("review-sweep "))
    assert line["action"] == "round-skipped" and line["unreadable"] == source
    assert host.spawned == [] and github.calls == []   # 读不到就什么都不做
    setattr(github if broken == "open_pulls" else sweep, broken, healthy)
    clock.now += module.MIN_LOOP_SECONDS
    assert hook() is not None and host.spawned        # 源恢复后下一轮照常派审


def test_serve_round_hook_is_single_flight_with_sync(tmp_path):
    """serve 的钩子：代码默认 HOST 同时只跑一个审查（reviewing 也认操作员手动起的 review-pr），并注入补对象的 sync；
    上限由 --review-sweep-max-running 传入。"""
    hook = module.serve_round(tmp_path / "k.pem", auto_merge=True)
    assert hook.sweep.max_running == 1 and hook.sweep.auto_merge is True and hook.sweep.sync is not None
    assert module.serve_round(tmp_path / "k.pem", max_running=3).sweep.max_running == 3
    assert module.serve_round(tmp_path / "k.pem", auto_merge=False).sweep.auto_merge is False


def test_manual_review_pr_on_host_holds_the_single_flight(lane):
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    sweep, host, _ = make(lane, run=False, github=github, max_running=1)
    host.rows.append((7, 7, "S", "python -m pilot1742.external_review review-pr --pr 1999 --attempt 1 --private-key x"))
    actions = sweep.tick()
    assert acts(actions, 1810) == ["queued"] and acts(actions, 1811) == ["queued"] and host.spawned == []


def _same_head_pulls(lane, github, numbers):
    """同仓、同 head 的其他 PR（对象都在本机库里，可直接派审）。"""
    for number in numbers:
        other = copy.deepcopy(lane.gateway.pr)
        other["number"] = number
        github.extra_pulls.append(other)


def test_concurrent_cap_launches_at_most_n_and_never_twice_for_one_pr(lane):
    """max_running=3：一轮最多派 3 个；下一轮在跑的报 running、不重派，其余仍排队，同一 PR 始终至多一个进程。"""
    github = FakeGitHub(lane)
    _same_head_pulls(lane, github, [1811, 1812, 1813, 1814])
    sweep, host, _ = make(lane, run=False, github=github, max_running=3)
    first = sweep.tick()
    assert [a["pr"] for a in first if a["action"] == "launch"] == [1810, 1811, 1812]
    assert [a["pr"] for a in first if a["action"] == "queued"] == [1813, 1814]
    second = sweep.tick()
    assert [a["pr"] for a in second if a["action"] == "running"] == [1810, 1811, 1812]
    assert [a["pr"] for a in second if a["action"] == "queued"] == [1813, 1814]
    assert [number for number, _, _ in host.spawned] == [1810, 1811, 1812]
    host.rows = [row for row in host.rows if " --pr 1811 " not in row[3] + " "]  # 1811 审完退出：让出一个名额
    third = sweep.tick()
    assert acts(third, 1813) == ["launch"] and acts(third, 1814) == ["queued"]
    assert len({number for number, _, _ in host.spawned}) == len(host.spawned) == 4


def test_concurrent_cap_counts_manual_review_pr(lane):
    github = FakeGitHub(lane)
    _same_head_pulls(lane, github, [1811, 1812])
    sweep, host, _ = make(lane, run=False, github=github, max_running=3)
    host.rows.append((7, 7, "S", "python -m pilot1742.external_review review-pr --pr 1999 --attempt 1 --private-key x"))
    actions = sweep.tick()
    assert [a["pr"] for a in actions if a["action"] == "launch"] == [1810, 1811]
    assert acts(actions, 1812) == ["queued"]


def test_concurrent_cap_counts_processes_not_prs(lane):
    """并发上限按审查进程数算（kimi 审 aa117154）：同一 PR 的两个手动 review-pr（不同 attempt）占两个名额。"""
    github = FakeGitHub(lane)
    _same_head_pulls(lane, github, [1811, 1812])
    sweep, host, _ = make(lane, run=False, github=github, max_running=3)
    host.rows.append((7, 7, "S", "python -m pilot1742.external_review review-pr --pr 1999 --attempt 1 --private-key x"))
    host.rows.append((8, 8, "S", "python -m pilot1742.external_review review-pr --pr 1999 --attempt 2 --private-key x"))
    actions = sweep.tick()
    assert [a["pr"] for a in actions if a["action"] == "launch"] == [1810]
    assert acts(actions, 1811) == ["queued"] and acts(actions, 1812) == ["queued"]


# ---- 派发先后：沿用优先、新推送优先、闲置超 48 小时的垫底 ----

def _ago(hours):
    return (datetime.now(timezone.utc) - module.timedelta(hours=hours)).isoformat()


def _pull_pushed(lane, github, number, hours_ago):
    """同仓 PR，head 是本机库里一个独立的新提交（可直接派审），committer 时间记为 hours_ago 小时前。"""
    restore = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-q", "--detach", lane.gateway.pr["head"]["sha"])
    (lane.source / f"pr-{number}").write_text(f"{number}\n")
    git(lane.source, "add", ".")
    git(lane.source, "commit", "-qm", f"pr {number}")
    head = git(lane.source, "rev-parse", "HEAD")
    git(lane.source, "checkout", "-q", restore)  # controller 身份（SOURCE_REPO 的 HEAD）不变
    other = copy.deepcopy(lane.gateway.pr)
    other["number"], other["head"]["sha"] = number, head
    github.extra_pulls.append(other)
    github.committed[head] = _ago(hours_ago)
    return head


def launched(actions):
    return [a["pr"] for a in actions if a["action"] == "launch"]


@pytest.mark.skipif(not hasattr(_external_review, "_advance_main"), reason="需要 #1913 的补丁沿用与 _advance_main")
def test_reuse_eligible_pr_launches_before_fresh_full_review(lane, env):
    """1810 追平后补丁不变、可沿用已发布的 PASS（约 1 分钟）：排在号码更小、推送更新、要完整双审的 1809 前面。"""
    sweep, _, _ = make(lane)
    assert acts(sweep.tick()) == ["launch"]           # 1810 在旧 head 上完整双审、发布 PASS
    reviewed = lane.gateway.pr["head"]["sha"]
    _external_review._advance_main(lane, env)          # main 前进、PR 追平：新 head，补丁不变
    github = FakeGitHub(lane)
    full = copy.deepcopy(lane.gateway.pr)
    full["number"], full["head"]["sha"] = 1809, reviewed  # 1809 从没审过：完整双审
    github.extra_pulls.append(full)
    github.committed = {reviewed: _ago(1), lane.gateway.pr["head"]["sha"]: _ago(10)}
    sweep, host, _ = make(lane, run=False, github=github, max_running=1)
    actions = sweep.tick()
    assert launched(actions) == [1810] and acts(actions, 1809) == ["queued"]
    assert [a["pr"] for a in actions if a.get("pr")] == [1810, 1809]


def test_fresh_pr_launches_before_old_one(lane):
    """号码大但刚推送的 1811 先于号码小、30 小时前推送的 1810。"""
    github = FakeGitHub(lane)
    github.committed[lane.gateway.pr["head"]["sha"]] = _ago(30)
    _pull_pushed(lane, github, 1811, 1)
    sweep, host, _ = make(lane, run=False, github=github, max_running=1)
    actions = sweep.tick()
    assert launched(actions) == [1811] and acts(actions, 1810) == ["queued"]


def test_pr_idle_over_48h_launches_only_when_nothing_else_is_queued(lane):
    """1810 有新评论（updated_at 新、仍在活动窗）但 72 小时没推送：比它旧的 47 小时 PR 也排在它前面；
    前面的审完、不再排队后它照样被派（不饿死）。"""
    github = FakeGitHub(lane)
    lane.gateway.pr["updated_at"] = datetime.now(timezone.utc).isoformat()
    github.committed[lane.gateway.pr["head"]["sha"]] = _ago(72)
    _pull_pushed(lane, github, 1811, 47)
    sweep, host, _ = make(lane, run=False, github=github, max_running=1)
    actions = sweep.tick()
    assert launched(actions) == [1811] and acts(actions, 1810) == ["queued"]
    assert acts(sweep.tick(), 1810) == ["queued"]    # 1811 还在审：1810 继续等
    github.extra_pulls.clear()                       # 1811 审完合入、不再开放
    host.rows.clear()
    assert launched(sweep.tick()) == [1810]


def test_free_slot_goes_to_stale_pr_in_the_same_round(lane):
    """名额够时 48 小时前的 PR 同一轮就派，只是排在后面。"""
    github = FakeGitHub(lane)
    github.committed[lane.gateway.pr["head"]["sha"]] = _ago(72)
    _pull_pushed(lane, github, 1811, 1)
    sweep, _, _ = make(lane, run=False, github=github, max_running=2)
    assert launched(sweep.tick()) == [1811, 1810]


def test_ordering_keeps_concurrency_cap_and_per_pr_dedup(lane):
    """新顺序下并发上限与单 PR 去重照旧：一轮最多派 max_running 个，在审的报 running、不重派，名额让出才轮到下一个。"""
    github = FakeGitHub(lane)
    github.committed[lane.gateway.pr["head"]["sha"]] = _ago(72)
    _pull_pushed(lane, github, 1811, 5)
    _pull_pushed(lane, github, 1812, 1)
    sweep, host, _ = make(lane, run=False, github=github, max_running=2)
    first = sweep.tick()
    assert launched(first) == [1812, 1811] and acts(first, 1810) == ["queued"]
    second = sweep.tick()
    assert launched(second) == [] and acts(second, 1812) == ["running"] and acts(second, 1811) == ["running"]
    assert acts(second, 1810) == ["queued"]
    host.rows = [row for row in host.rows if " --pr 1812 " not in row[3] + " "]
    third = sweep.tick()
    assert launched(third) == [1810] and acts(third, 1811) == ["running"]
    assert sorted(number for number, _, _ in host.spawned) == [1810, 1811, 1812]


def test_unreadable_commit_time_only_moves_pr_to_the_back(lane):
    """head 提交时间读不到（非超时）：不影响派不派，只排到最后一组。"""
    github = FakeGitHub(lane)
    _pull_pushed(lane, github, 1811, 72)
    first = lane.gateway.pr["head"]["sha"]
    real = github.committed_at
    github.committed_at = lambda head: (_ for _ in ()).throw(RuntimeError("HTTP 404")) if head == first else real(head)
    sweep, _, _ = make(lane, run=False, github=github, max_running=2)
    assert launched(sweep.tick()) == [1811, 1810]


def test_commit_time_timeout_voids_the_round(lane):
    github = FakeGitHub(lane)
    github.committed_at = lambda head: (_ for _ in ()).throw(SourceUnreadable("github (git/commits)", TimeoutError()))
    sweep, host, _ = make(lane, run=False, github=github)
    with pytest.raises(SourceUnreadable):
        sweep.tick()
    assert host.spawned == []


def test_space_admission_refusal_holds_with_concurrency(lane, monkeypatch):
    """并发不绕过准入：子进程在登记前被空间准入拒绝时，不登记 attempt、不写状态；下一轮同一 attempt 退避、不重派。"""
    from pilot1742.external_review import IdentityError
    refused = []

    def no_space(target):
        refused.append(target.pr_number)
        raise IdentityError("空间不足：测试")
    monkeypatch.setattr(lane, "admit_space", no_space)
    host = Host(lane)

    def child(number, attempt, head, log, base=None):  # 子进程：review-pr 失败即退出，sweep 只拿到 pid
        host.spawned.append((number, attempt, head))
        with pytest.raises(IdentityError):
            lane.review_pr(number, attempt)
        return 4000 + len(host.spawned)
    sweep = Sweep(FakeGitHub(lane), lane, child, state_root=lane.state_root, rows=lambda: [], max_running=3)
    assert acts(sweep.tick()) == ["launch"]
    assert refused == [1810] and lane.status(1810) == [] and lane.gateway.sent == []
    assert acts(sweep.tick()) == ["launch-backoff"] and len(host.spawned) == 1


def test_fetcher_fills_objects_without_touching_refs(lane, tmp_path):
    """sync 把 main 与 PR head 取进对象库，只写 FETCH_HEAD，不建分支、不动 HEAD。"""
    base, head = lane.gateway.pr["base"]["sha"], lane.gateway.pr["head"]["sha"]
    upstream, fresh = tmp_path / "upstream.git", tmp_path / "host"
    git(tmp_path, "init", "-q", "--bare", str(upstream))
    git(lane.source, "push", "-q", str(upstream), f"{base}:refs/heads/main", f"{head}:refs/pull/1810/head")
    git(tmp_path, "init", "-q", str(fresh))
    module.fetcher(fresh, str(upstream))(1810, base, head)
    for sha in (base, head):
        git(fresh, "cat-file", "-e", f"{sha}^{{commit}}")
    assert git(fresh, "for-each-ref") == ""


class _StopServe(Exception):
    pass


def _fake_serve(monkeypatch, tmp_path, *, rounds):
    from types import SimpleNamespace

    from pilot1742 import executor as cli
    from pilot1742 import queue as queue_module

    class Cutover:
        def __init__(self, *args, **kwargs):
            self.drain_root = tmp_path
        def load(self):
            return None

    class Intake:
        def __init__(self, *args, **kwargs):
            pass
        def once(self, child):
            rounds.append("intake")
            return {}

    client = SimpleNamespace(identity=SimpleNamespace(repository="Newchanlun/NewChanlun"), bot_login="bot[bot]",
                             close=lambda: None)
    monkeypatch.setattr(cli, "CutoverStore", Cutover)
    monkeypatch.setattr(cli, "_client", lambda args: client)
    monkeypatch.setattr(queue_module, "QueueIntake", Intake)
    def sleep(seconds):
        if rounds.count("intake") >= 3:
            raise _StopServe
    monkeypatch.setattr(cli.time, "sleep", sleep)
    for var in (
        "REVIEW_PREFLIGHT_PROXY_URL",
        "REVIEW_PREFLIGHT_PROXY_RECEIPT_CONTAINER",
        "REVIEW_PREFLIGHT_PROXY_DOCKER_CONTEXT",
        "REVIEW_PREFLIGHT_PROXY_CONTAINER_RECEIPT_DIR",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_RECEIPT_DIR", str(tmp_path / "receipts"))
    return cli, ["--state-root", str(tmp_path / "state"), "serve", "--loop", "--private-key", str(tmp_path / "k.pem")]


def test_executor_serve_runs_one_sweep_round_per_serve_round(monkeypatch, tmp_path):
    rounds, built = [], []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round",
                        lambda key, auto_merge, max_running: built.append((key, auto_merge, max_running))
                        or (lambda: rounds.append("sweep")))
    with pytest.raises(_StopServe):
        cli.main(argv + ["--review-sweep", "--review-sweep-auto-merge", "--review-sweep-max-running", "3"])
    assert rounds == ["sweep", "intake"] * 3                      # 每轮一次，排在派票前
    assert built == [(tmp_path / "k.pem", True, 3)]


def test_executor_serve_without_flag_has_no_sweep(monkeypatch, tmp_path, capsys):
    rounds = []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round", lambda *a, **k: pytest.fail("sweep wired without --review-sweep"))
    with pytest.raises(_StopServe):
        cli.main(argv)
    assert rounds == ["intake"] * 3
    assert "ignored-without-review-sweep" not in capsys.readouterr().out
    assert cli.main(argv + ["--review-sweep", "--review-sweep-max-running", "0"]) == 2


@pytest.mark.parametrize("extra", [["--review-sweep-auto-merge"], ["--review-sweep-max-running", "3"],
                                   ["--review-sweep-max-running", "1"],
                                   ["--review-sweep-auto-merge", "--review-sweep-max-running", "3"]])
def test_sweep_flags_without_review_sweep_are_ignored_with_one_warning(monkeypatch, tmp_path, capsys, extra):
    """关审查只删 --review-sweep、其余 sweep 参数留在 plist 里时：serve 照常派票（不以退出码 2 退出，免得 launchd
    反复重启、派票停摆），不接 sweep，记一行警告点名被忽略的参数。"""
    rounds = []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round", lambda *a, **k: pytest.fail("sweep wired without --review-sweep"))
    with pytest.raises(_StopServe):
        cli.main(argv + extra)
    assert rounds == ["intake"] * 3
    warnings = [json.loads(line.split(" ", 1)[1]) for line in capsys.readouterr().out.splitlines()
                if line.startswith("review-sweep ")]
    assert warnings == [{"action": "ignored-without-review-sweep", "flags": [f for f in extra if f.startswith("--")],
                         "reason": "没有 --review-sweep，这些参数不生效"}]


def test_deployed_executor_plist_turns_sweep_on_without_unattended_auto_merge():
    """#2207 依据 #1742/#1909 裁定：因 GitHub 合入/追平接口无服务端 expected_base_ref/expected_base_sha，
    部署模板仅开启 --review-sweep 负责正式双审派发，不再启用 --review-sweep-auto-merge；
    代码里 auto_merge 亦默认关，见 test_auto_merge_is_off_unless_explicitly_enabled；
    模板同时持久化可信代理收据源配置，确保干净 LaunchAgent 启动无需依赖交互 shell。"""
    import plistlib
    from pathlib import Path
    plist = Path(module.__file__).resolve().parents[2] / "launchd" / "com.newchanlun.deepagents-executor.plist"
    data = plistlib.loads(plist.read_bytes())
    args = data["ProgramArguments"]
    assert args[args.index("serve"):args.index("serve") + 2] == ["serve", "--loop"]
    assert "--review-sweep" in args and "--review-sweep-auto-merge" not in args
    assert args[args.index("--review-sweep-max-running") + 1] == "3"
    env = data["EnvironmentVariables"]
    assert _external_review.ExternalReview.validate_preflight_receipt_source(env) is None
    assert env["REVIEW_PREFLIGHT_PROXY_RECEIPT_CONTAINER"] == "blackhole-cliproxy"
    assert env["REVIEW_PREFLIGHT_PROXY_DOCKER_CONTEXT"] == "orbstack"
    assert env["REVIEW_PREFLIGHT_PROXY_CONTAINER_RECEIPT_DIR"] == "/tmp/cliproxy-preflight-receipts"


def test_auto_merge_is_off_unless_explicitly_enabled(monkeypatch, tmp_path):
    """代码里默认关且部署模板不启用：只给 --review-sweep 时 sweep 只派审；显式加 --review-sweep-auto-merge 才附带门禁核验与撤原生 auto-merge。"""
    rounds, built = [], []
    real_serve_round = module.serve_round
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round",
                        lambda key, **kw: built.append(kw) or (lambda: rounds.append("sweep")))
    with pytest.raises(_StopServe):
        cli.main(argv + ["--review-sweep"])
    assert built == [{"auto_merge": False, "max_running": 1}]
    assert real_serve_round(tmp_path / "k.pem").sweep.auto_merge is False
    assert module.Sweep(FakeGitHub(None), None, lambda *a: 0).auto_merge is False


# ---- 第二轮独审（9f0876cf，run dbd3c612）：证据读失败一律失败关闭；gh 调用有超时 ----

def _sensitive_armed(lane, github):
    github.states[1810] = {"auto_merge": True}
    github.files[1810] = [{"filename": "rust/src/trading/order.rs", "status": "modified", "changes": 1}]
    green(github, lane.gateway.pr["head"]["sha"])


def _raise(*args, **kwargs):
    raise RuntimeError("HTTP 502")


@pytest.mark.parametrize("broken", ["pr_files", "checks", "pr"])
def test_evidence_read_failure_withdraws_native_auto_merge(lane, broken):
    """kimi 高 1：读文件清单、检查或 PR 状态失败时，挂着原生 auto-merge 的 PR 不能靠它绕过 HUMAN_GATED：
    不合入、不追平，并撤掉 auto-merge（PR 状态读不到、不知道挂没挂时照撤）。"""
    github = FakeGitHub(lane)
    _sensitive_armed(lane, github)
    if broken == "pr":
        github.fail[1810] = {"pr"}
    else:
        setattr(github, broken, _raise)
    if broken == "checks":  # 检查在人工确认类判定之后读；读不到时普通 PR 同样失败关闭
        github.files[1810] = [{"filename": "src/x.py", "status": "modified", "changes": 1}]
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "evidence-insufficient")
    assert result["auto_merge_withdrawn"] is True
    assert github.calls == [("disable", 1810)]


def test_required_checks_read_failure_still_withdraws_and_never_merges_or_updates(lane):
    """kimi 高 1 后半：main 必需检查读不到时不再直接返回；照常逐个 PR 判人工确认类并撤原生 auto-merge，
    但谁都不合入、不追平。"""
    github = FakeGitHub(lane)
    _sensitive_armed(lane, github)
    _more_pulls(lane, github, [1811, 1812])
    github.states[1811] = {"mergeable_state": "behind"}
    green(github, f"{1812:040d}")
    github.required_checks = _raise
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert any(a["action"] == "evidence-insufficient" and "必需检查" in a["reason"] for a in actions)
    assert github.calls == [("disable", 1810)]


def test_gh_calls_have_a_timeout_and_a_timeout_is_an_unreadable_source(monkeypatch):
    """kimi 高 2：每个 gh 调用带超时；超时转成 SourceUnreadable，写明是哪个接口。"""
    import subprocess
    seen = []
    def run(command, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(module.subprocess, "run", run)
    cli = module.GhCli("Newchanlun/NewChanlun", timeout=7)
    assert not hasattr(cli, "merge") and not hasattr(cli, "update_branch")
    for call in (cli.open_pulls, lambda: cli.pr(5), lambda: cli.checks("a" * 40, BINDINGS), cli.required_checks,
                 lambda: cli.pr_files(5), lambda: cli.disable_auto_merge(5)):
        with pytest.raises(SourceUnreadable) as caught:
            call()
        assert "timed out after 7s" in str(caught.value) and caught.value.source.startswith("github")
    assert seen and all(t == 7 for t in seen)
    assert module.GhCli().timeout == module.GH_TIMEOUT_SECONDS > 0


@pytest.mark.parametrize("where", ["pr", "checks", "required_checks"])
def test_timeout_mid_round_skips_the_round_without_merging(lane, capsys, where):
    """超时发生在本轮中途：整轮作废、记一行写明哪个源，不合入；serve 钩子不抛出，下一轮照常。"""
    clock = Clock()
    github = FakeGitHub(lane)
    green(github, lane.gateway.pr["head"]["sha"])
    def hang(*args, **kwargs):
        raise SourceUnreadable(f"github ({where}) timed out after 60s", TimeoutError())
    healthy = getattr(github, where)
    setattr(github, where, hang)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    hook = ServeRound(sweep, clock=clock)
    assert hook() is None
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1].removeprefix("review-sweep "))
    assert line["action"] == "round-skipped" and where in line["unreadable"]
    assert not [c for c in github.calls if c[0] == "merge"]
    setattr(github, where, healthy)
    clock.now += module.MIN_LOOP_SECONDS
    assert "needs-human-confirm" in [a["action"] for a in hook()]


def test_green_but_unmergeable_pr_does_not_hold_the_queue_head(lane):
    """opus 低：不落后、三项全绿却停在 blocked（main 另有未满足的规则）的 PR 不占队首，下一个落后的照常追平。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    github.states[1810] = {"mergeable_state": "blocked"}
    github.states[1811] = {"mergeable_state": "behind"}
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert github.calls == []
    assert next(a for a in actions if a.get("pr") == 1811 and a["action"] == "behind-waiting")["queue_head"] is True
    assert next(a for a in actions if a.get("pr") == 1810 and a["action"] == "waiting")["queue_head"] is False


def test_failed_fetch_is_tried_once_per_round(lane):
    """opus 低：fetch 每次最多 FETCH_TIMEOUT_SECONDS；一轮里失败一次后其余 PR 不再 fetch，超时不逐个累加。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    lane.gateway.pr["head"]["sha"] = "e" * 40
    github.extra_pulls[0]["head"]["sha"] = "d" * 40
    fetches = []
    def sync(number, base, head):
        fetches.append(number)
        raise RuntimeError("fetch timed out")
    sweep, _, _ = make(lane, run=False, github=github, sync=sync)
    actions = sweep.tick()
    assert fetches == [1810]
    assert acts(actions, 1810) == ["source-unreadable"] and acts(actions, 1811) == ["source-unreadable"]
    assert next(a for a in actions if a.get("pr") == 1810)["unreadable"].endswith("main pull/1810/head")
    sweep.tick()
    assert fetches == [1810, 1810]                      # 下一轮重新试


# ---- 第三轮独审（0225a3e6，run 15477252）：超时也要撤原生 auto-merge；中止前的动作照常写日志 ----

def _hang(*args, **kwargs):
    raise SourceUnreadable("github (repos/x) timed out after 60s", TimeoutError())


def _armed_sensitive_and_green_neighbour(lane, github):
    """1810 触及实盘交易且挂着原生 auto-merge（开放 PR 列表里就带着 auto_merge 字段）；1805 是可合入的普通 PR。"""
    lane.gateway.pr["auto_merge"] = {"merge_method": "merge"}
    _sensitive_armed(lane, github)
    _more_pulls(lane, github, [1805])
    github.extra_pulls[0]["auto_merge"] = None
    green(github, f"{1805:040d}")


@pytest.mark.parametrize("where", ["pr", "pr_files", "checks", "required_checks"])
def test_timeout_withdraws_native_auto_merge_and_merges_nothing(lane, capsys, where):
    """kimi 阻断：gh 超时也不能留下原生 auto-merge 的旁路。超时后凡没能确认不触及两类、又挂着（或不知道挂没挂）
    auto-merge 的 PR 都尽力撤掉并记一行；本轮一个 PR 也不合入（读阶段超时发生在任何写之前）。"""
    github = FakeGitHub(lane)
    _armed_sensitive_and_green_neighbour(lane, github)
    if where == "required_checks" or where == "checks":
        setattr(github, where, _hang)
    else:
        original = getattr(github, where)
        setattr(github, where, lambda number, *a: _hang() if number == 1810 else original(number, *a))
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    assert ServeRound(sweep, clock=Clock())() is None
    lines = [json.loads(line.removeprefix("review-sweep ")) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1]["action"] == "round-skipped"
    withdrawn_row = next(
        a for a in lines if a.get("pr") == 1810 and a["action"] in ("auto-merge-withdraw", "fail-closed-withdraw")
    )
    assert withdrawn_row.get("auto_merge_withdrawn") is True
    assert github.calls == [("disable", 1810)]          # 只撤 auto-merge；1805 也没合入


def test_auto_merge_state_missing_from_pull_list_counts_as_armed(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {}
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    github.pr = _hang
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert github.calls == [("disable", 1810)]
    assert caught.value.actions[-1]["action"] == "fail-closed-withdraw"


def test_withdraw_timeout_stops_the_fail_closed_sweep(lane):
    github = FakeGitHub(lane)
    _armed_sensitive_and_green_neighbour(lane, github)
    github.required_checks = _hang
    github.disable_auto_merge = _hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert [a["action"] for a in caught.value.actions][-2:] == ["fail-closed-withdraw", "fail-closed-aborted"]


def test_actions_done_before_a_timeout_are_still_logged(lane, capsys):
    """opus 中：本轮先完成了一个 PR 的撤原生 auto-merge、后一个写超时，已做那条照样写日志，写超时那条记 write-unknown。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805])
    github.states[1805] = {"auto_merge": True}
    github.files[1805] = [{"filename": "src/ordinary.py", "status": "modified", "changes": 1}]
    _sensitive_armed(lane, github)
    disabled = []
    orig_disable = github.disable_auto_merge

    def disable_then_hang(number):
        if number == 1810:
            _hang()
        disabled.append(number)
        orig_disable(number)

    github.disable_auto_merge = disable_then_hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    assert ServeRound(sweep, clock=Clock())() is None
    lines = [json.loads(line.removeprefix("review-sweep ")) for line in capsys.readouterr().out.splitlines()]
    assert disabled == [1805]
    assert any(a.get("pr") == 1805 and a.get("auto_merge_withdrawn") is True for a in lines)
    assert any(a.get("pr") == 1810 and a["action"] == "write-unknown" for a in lines)
    assert lines[-1]["action"] == "round-skipped"


# ---- 第四轮独审（7b477efd，run 52055f21）：分类绑定到读到的 head；fetch 失败明说读不到 ----

def _ordinary_armed(lane, github):
    github.states[1810] = {"auto_merge": True}
    github.files[1810] = [{"filename": "src/x.py", "status": "modified", "changes": 1}]
    green(github, lane.gateway.pr["head"]["sha"])


def test_head_change_mid_round_withdraws_auto_merge_and_never_merges(lane):
    """kimi 阻断：读完文件清单后 head 被推走（清单接口不按 SHA 取，读到的可能已是新 head 的内容，也可能是旧的）。
    分类不再算数：报 head-moved，不合入，撤掉原生 auto-merge，免得没分类过的新 head 靠它合入。"""
    github = FakeGitHub(lane)
    _ordinary_armed(lane, github)
    head, pushed = lane.gateway.pr["head"]["sha"], "c" * 40
    original, reads = github.pr, []
    def pr(number):
        reads.append(number)
        state = original(number)
        if len(reads) > 1:                       # 第二次读（复核）时 head 已变
            state.update(head=pushed)
        return state
    github.pr = pr
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "head-moved")
    assert result["classified"] == head and result["now"] == pushed
    assert result["auto_merge_withdrawn"] is True
    assert github.calls == [("disable", 1810)]


def test_listed_head_differs_from_live_state_withdraws_armed_auto_merge(lane):
    github = FakeGitHub(lane)
    _ordinary_armed(lane, github)
    github.states[1810].update(head="c" * 40)
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "head-moved")
    assert result["now"] == "c" * 40 and github.calls == [("disable", 1810)]


def test_head_recheck_read_failure_fails_closed(lane):
    github = FakeGitHub(lane)
    _ordinary_armed(lane, github)
    original, reads = github.pr, []
    def pr(number):
        reads.append(number)
        if len(reads) > 1:
            raise RuntimeError("HTTP 502")
        return original(number)
    github.pr = pr
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a["action"] == "evidence-insufficient")
    assert "复核 head" in result["reason"] and ("disable", 1810) in github.calls and all(c == ("disable", 1810) for c in github.calls)


def test_writes_carry_the_classified_head():
    """GhCli 不暴露无服务端 expected_base_ref 绑定的 merge 与 update_branch 写分支接口，仅保留收紧性的 disable_auto_merge。"""
    sent = []
    cli = module.GhCli("Newchanlun/NewChanlun")
    cli._gh = lambda *args: sent.append(args) or ""
    assert not hasattr(cli, "merge") and not hasattr(cli, "update_branch")
    cli.disable_auto_merge(5)
    assert sent == [("pr", "merge", "5", "-R", "Newchanlun/NewChanlun", "--disable-auto")]


def test_fetch_failure_is_an_unreadable_source_and_never_reviewed(lane, tmp_path):
    """kimi 阻断 2：fetch 失败（私有仓无认证、网络、超时）写明读不到哪个源，不派审、不算通过。"""
    lane.gateway.pr["head"]["sha"] = "e" * 40
    sweep, host, _ = make(lane, run=False, sync=module.fetcher(lane.source, str(tmp_path / "no-such-repo.git")))
    result = next(a for a in sweep.tick() if a.get("pr") == 1810)
    assert result["action"] == "source-unreadable" and result["unreadable"].endswith("pull/1810/head")
    assert "CalledProcessError" in result["reason"] and host.spawned == []
    assert "source-unreadable" in module.STUCK_REVIEW


def test_fetch_authenticates_with_the_hosts_gh_credential_helper(monkeypatch, tmp_path):
    """kimi 第四轮：私有仓也要取得到。fetch 只挂 gh 自己的凭据助手（先清空其他助手），与 sweep 其余 GitHub 读写
    同一份宿主 gh 登录；保留 120 秒超时；环境只多 HOME/GH_CONFIG_DIR 让 gh 找到登录状态，不带任何 token 变量。"""
    seen = {}
    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GH_TOKEN", "must-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-leak")
    module.fetcher(tmp_path, "https://github.com/Newchanlun/NewChanlun.git")(7, "a" * 40, "b" * 40)
    command = seen["command"]
    helpers = [command[i + 1] for i, part in enumerate(command) if part == "-c" and
               command[i + 1].startswith("credential.helper=")]
    assert helpers == ["credential.helper=", "credential.helper=!gh auth git-credential"]
    assert command[command.index("fetch"):] == ["fetch", "--no-tags", "--quiet",
                                                "https://github.com/Newchanlun/NewChanlun.git", "main", "pull/7/head"]
    assert seen["timeout"] == module.FETCH_TIMEOUT_SECONDS == 120
    assert seen["env"]["HOME"] == str(tmp_path) and seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert not {"GH_TOKEN", "GITHUB_TOKEN"} & set(seen["env"])


# ---- 第五轮（9ab8a495，run ba9fcac2）：原生 auto-merge 在仓库层关掉，sweep 每轮核对 ----

@pytest.mark.parametrize("setting", ["enabled", "unreadable"])
def test_repo_allowing_native_auto_merge_blocks_all_merges_and_updates(lane, setting):
    """有写权限的人能在两轮之间给触及两类的 PR 挂原生 auto-merge，sweep 看不见。所以仓库设置 allow_auto_merge
    必须是 false：为 true 或读不到时本轮谁都不合入、不追平，记 native-auto-merge-enabled；撤 auto-merge 照常做。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805, 1811])
    green(github, f"{1805:040d}", **{"ci-ok": "pending"})            # 普通 PR 挂原生 auto-merge 且 CI pending
    github.states[1805] = {"auto_merge": True}
    github.files[1805] = [{"filename": "src/ordinary.py", "status": "modified", "changes": 1}]
    github.states[1811] = {"mergeable_state": "behind", "auto_merge": True}  # behind 且挂原生 auto-merge
    _sensitive_armed(lane, github)                                  # 1810：须撤 auto-merge
    if setting == "enabled":
        github.allow_auto_merge = lambda: True
    else:
        github.allow_auto_merge = _raise
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    flagged = next(a for a in actions if a["action"] == "native-auto-merge-enabled")
    assert ("allow_auto_merge=true" in flagged["reason"]) == (setting == "enabled")
    # 无论 gate_ok=False、普通 waiting PR、behind PR 还是敏感 PR，凡挂着原生 auto-merge 一律无条件撤回
    assert github.calls == [("disable", 1805), ("disable", 1810), ("disable", 1811)]


def test_repo_with_native_auto_merge_disabled_merges_normally(lane):
    github = FakeGitHub(lane)
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert "native-auto-merge-enabled" not in [a["action"] for a in actions]
    assert any(a["action"] == "needs-human-confirm" and a.get("gated") == ["base-ref-not-server-bound"] for a in actions)
    assert github.calls == []


@pytest.mark.parametrize(("payload", "allowed"), [({"allow_auto_merge": False}, False), ({"allow_auto_merge": True}, True),
                                                  ({}, True), ({"allow_auto_merge": None}, True)])
def test_gh_reads_allow_auto_merge_and_only_trusts_explicit_false(monkeypatch, payload, allowed):
    cli = module.GhCli("Newchanlun/NewChanlun")
    calls = []
    monkeypatch.setattr(cli, "_gh", lambda *args: calls.append(args) or json.dumps(payload))
    assert cli.allow_auto_merge() is allowed and calls == [("api", "repos/Newchanlun/NewChanlun")]


def test_allow_auto_merge_timeout_skips_the_round(lane):
    github = FakeGitHub(lane)
    _sensitive_armed(lane, github)
    github.allow_auto_merge = _hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert github.calls == [("disable", 1810)]                     # 超时：整轮作废，原生 auto-merge 已撤
    assert caught.value.actions[-1]["action"] in ("auto-merge-withdraw", "fail-closed-withdraw")


# ---- 第六轮（1354bc7c，run cfbc868b）：检查结论绑定来源 App；serve 的审查私钥单独给 ----

def _gh_fake(statuses, runs, apps=None):
    apps = apps or {"newchanlun-deepagents-1742": 5486877, "github-actions": 15368}
    def gh(*args):
        path = next(a for a in args if a.startswith(("repos/", "apps/")))
        if path.startswith("apps/"):
            return json.dumps({"id": apps.get(path.removeprefix("apps/"), -1)})
        if "/statuses" in path:
            return "\n".join(json.dumps(x) for x in statuses)
        return "\n".join(json.dumps(x) for x in runs)
    return gh


def _status(context, state, login):
    return {"context": context, "state": state, "creator": {"login": login, "type": "Bot"}}


def _run(name, conclusion, app_id, run_id=1):
    return {"name": name, "status": "completed", "conclusion": conclusion, "app": {"id": app_id},
            "id": run_id, "started_at": f"2026-11-09T00:00:0{run_id}Z"}


BINDINGS = {"deepagents/review": 5486877, "ci-ok": 15368, "DevSkim": 15368}


def test_spoofed_same_name_checks_from_other_apps_do_not_count(monkeypatch):
    """opus 中：同仓 PR 可加一个叫 deepagents/review 或 DevSkim 的 job、或用别的身份发同名 status。
    只认分支保护（DevSkim 为 GATED_APP_IDS）绑定的来源 App，同名伪造的 success 不算。"""
    cli = module.GhCli("Newchanlun/NewChanlun")
    statuses = [_status("deepagents/review", "success", "someone-else[bot]"),   # 最新一条是伪造
                _status("deepagents/review", "failure", "newchanlun-deepagents-1742[bot]")]
    runs = [_run("deepagents/review", "success", 15368, 1),   # Actions 里的同名 job
            _run("DevSkim", "success", 99999, 2),             # 别的 App 跑的 DevSkim
            _run("ci-ok", "success", 15368, 3)]
    monkeypatch.setattr(cli, "_gh", _gh_fake(statuses, runs))
    assert cli.checks("a" * 40, BINDINGS) == {"deepagents/review": "failure", "ci-ok": "success"}


def test_genuine_checks_from_bound_apps_count(monkeypatch):
    cli = module.GhCli("Newchanlun/NewChanlun")
    statuses = [_status("deepagents/review", "success", "newchanlun-deepagents-1742[bot]")]
    runs = [_run("DevSkim", "success", 15368, 1), _run("ci-ok", "success", 15368, 2)]
    monkeypatch.setattr(cli, "_gh", _gh_fake(statuses, runs))
    assert cli.checks("a" * 40, BINDINGS) == {name: "success" for name in BINDINGS}


@pytest.mark.parametrize("apps", [{"newchanlun-deepagents-1742": 1, "github-actions": 15368}, None])
def test_status_from_unknown_or_mismatched_app_slug_fails_closed(monkeypatch, apps):
    """status 只露 bot 账号：bot 由 APP_SLUGS 推出并经 GET /apps/{slug} 核对 id；对不上或不在表里都不算。"""
    cli = module.GhCli("Newchanlun/NewChanlun")
    statuses = [_status("deepagents/review", "success", "newchanlun-deepagents-1742[bot]")]
    monkeypatch.setattr(cli, "_gh", _gh_fake(statuses, [], apps))
    bindings = BINDINGS if apps else {**BINDINGS, "deepagents/review": 424242}
    assert "deepagents/review" not in cli.checks("a" * 40, bindings)


@pytest.mark.parametrize("missing", ["enforce_admins", "strict", "binding"])
def test_protection_mismatch_never_merges(lane, missing):
    """分支保护任一不符（enforce_admins 关、strict 关、必需检查没绑定 app）：失败关闭，不合入、不追平。"""
    github = FakeGitHub(lane, required=() if missing != "binding" else ("deepagents/review",))
    green(github, lane.gateway.pr["head"]["sha"])
    if missing != "binding":
        github.checks = lambda head, bindings: dict(github.checks_by_head.get(head, {}))
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert any(a["action"] == "auto-merge-unsafe" for a in actions) and github.calls == []


# ---- #2015 opus 阻断（247f128b，run 6ac0b428）：必需检查绑定执行器 App 时不合入 ----

@pytest.mark.parametrize("bound, configured", [(5486877, 5486877), (5486877, None), (5664795, None), (5664795, 4242)])
def test_review_binding_not_the_configured_reviewer_app_never_merges(lane, bound, configured):
    """执行器交付时用执行器 App 自写 deepagents/review=success。必需检查绑定执行器 App（缺省身份）时，
    draft 一标 ready，同一轮里 sweep 刚派出正式审查、FakeGitHub 已报三项全绿，也不得合入；
    绑定与审查身份文件配的 App 不符、或身份文件缺失时同样不合入。"""
    github = FakeGitHub(lane, review_app=bound)
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True, review_app=lambda: configured)
    actions = sweep.tick()
    assert acts(actions) == ["launch", "waiting"] and len(host.spawned) == 1   # 本轮刚派出正式审查
    assert [a for a in actions if a["action"] == "auto-merge-unsafe"]
    assert github.calls == []


def test_reviewer_app_binding_merges_when_green(lane):
    """对照：绑定审查专用 App 且与身份文件一致时，不报 auto-merge-unsafe，精确 head 全绿后因缺 expected_base_ref 转人工确认且不自动合入。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert not any(a["action"] == "auto-merge-unsafe" for a in actions)
    assert any(a["action"] == "needs-human-confirm" and a.get("gated") == ["base-ref-not-server-bound"] for a in actions)
    assert github.calls == []


def test_executor_app_status_alone_does_not_satisfy_reviewer_binding(monkeypatch):
    """绑定审查 App 5664795 时，执行器 App 发的 deepagents/review=success 不算（合入看的检查只认绑定来源）。"""
    cli = module.GhCli("Newchanlun/NewChanlun")
    statuses = [_status("deepagents/review", "success", "newchanlun-deepagents-1742[bot]")]
    runs = [_run("DevSkim", "success", 15368, 1), _run("ci-ok", "success", 15368, 2)]
    apps = {"newchanlun-deepagents-1742": 5486877, "newchanlun-review-gate": 5664795, "github-actions": 15368}
    monkeypatch.setattr(cli, "_gh", _gh_fake(statuses, runs, apps))
    assert cli.checks("a" * 40, {**BINDINGS, "deepagents/review": 5664795}) == {"ci-ok": "success", "DevSkim": "success"}


def test_configured_review_app_reads_identity_file(tmp_path):
    config = tmp_path / "app-identity.json"
    assert module.configured_review_app(config) is None                      # 没有身份文件：审查沿用执行器 App
    config.write_text(json.dumps({"app_id": 5664795, "installation_id": 1, "app_slug": "x",
                                  "installation_permissions": {}}))
    assert module.configured_review_app(config) == 5664795
    config.write_text("not json")
    assert module.configured_review_app(config) is None


def test_serve_passes_the_review_key_not_the_executor_key(monkeypatch, tmp_path):
    """kimi 阻断：serve 的 sweep 用 --review-private-key，不把执行器 App 私钥转给 review-pr。"""
    rounds, built = [], []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round", lambda key, **kw: built.append(key) or (lambda: rounds.append("sweep")))
    with pytest.raises(_StopServe):
        cli.main(argv + ["--review-sweep", "--review-private-key", str(tmp_path / "review.pem")])
    assert built == [tmp_path / "review.pem"]


def test_serve_refuses_without_review_key_once_review_app_identity_exists(monkeypatch, tmp_path, capsys):
    """身份文件已指向审查专用 App 而没给 --review-private-key：失败关闭，退出码 2，记一行，sweep 不起。"""
    from pilot1742 import external_review
    identity = tmp_path / "app-identity.json"
    identity.write_text("{}")
    monkeypatch.setattr(external_review, "IDENTITY_CONFIG", identity)
    rounds = []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round", lambda *a, **k: pytest.fail("sweep started without review key"))
    monkeypatch.setattr(cli, "_client", lambda args: pytest.fail("App opened"))
    assert cli.main(argv + ["--review-sweep"]) == 2
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("review-sweep ")]
    assert len(lines) == 1 and json.loads(lines[0].removeprefix("review-sweep "))["action"] == "refused-no-review-key"
    assert rounds == []


def test_serve_without_review_key_falls_back_only_without_review_identity(monkeypatch, tmp_path, capsys):
    from pilot1742 import external_review
    monkeypatch.setattr(external_review, "IDENTITY_CONFIG", tmp_path / "absent.json")
    rounds, built = [], []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.setattr(module, "serve_round", lambda key, **kw: built.append(key) or (lambda: rounds.append("sweep")))
    with pytest.raises(_StopServe):
        cli.main(argv + ["--review-sweep"])
    assert built == [tmp_path / "k.pem"] and "review-key-fallback" in capsys.readouterr().out


def test_plist_gives_the_review_key_its_own_placeholder():
    import plistlib
    from pathlib import Path
    plist = Path(module.__file__).resolve().parents[2] / "launchd" / "com.newchanlun.deepagents-executor.plist"
    args = plistlib.loads(plist.read_bytes())["ProgramArguments"]
    assert args[args.index("--review-private-key") + 1] == "__REVIEW_PRIVATE_KEY_PATH__"
    assert args[args.index("--private-key") + 1] == "__PRIVATE_KEY_PATH__"


def test_manual_loop_logs_actions_taken_before_a_timeout(lane, monkeypatch, capsys):
    """opus 低：手动单跑的 main 循环遇超时也先写本轮已做的动作，再写 round-skipped。"""
    error = SourceUnreadable("github (repos/x) timed out after 60s", TimeoutError())
    error.actions = [{"pr": 1805, "action": "merged"}]
    class Boom(Sweep):
        def __init__(self, *args, **kwargs):
            pass
        def tick(self):
            raise error
    monkeypatch.setattr(module, "Sweep", Boom)
    assert module.main(["--private-key", "/k"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [a["action"] for a in lines] == ["merged", "round-skipped"]


def test_newly_launched_async_review_in_same_tick_blocks_auto_merge_before_target_json(lane):
    """本轮刚异步派出的审查尚未写 target.json 时，即使远端同 SHA 已有绿灯（如跨 PR 旧 status），本轮合入也必须阻塞等待。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["launch", "waiting"]
    waiting = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "waiting")
    assert waiting.get("pending_latest_attempt") is True
    assert len(host.spawned) == 1 and github.calls == []


def test_reuse_fallback_after_preflight_admitted_uses_resume_once_not_launch_backoff(lane, env):
    """沿用登记后一旦写出 preflight-admitted.json，即使尚未发 pending 或建工蜂目录，也不再算预检前退回，改为受管 resume-review。"""
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    _external_review._advance_main(lane, env)
    target = lane.target(1810, 1)
    assert target.reuse_planned is True
    folder = lane.state_root / "runs" / target.key
    (folder / "preflight-admitted.json").write_text(json.dumps({"run_id": target.run_id}))
    sweep, host, _ = make(lane, run=False)
    actions = sweep.tick()
    assert acts(actions) == ["resume-review"] and len(host.spawned) == 1


def test_formal_429_then_passing_preflight_then_preflight_429_does_not_false_backoff(lane):
    """正式 run 命中 rate_limited 后，若中间有一次预检通过，即使此前尚无 preflight-rate-limits.json，后续单次预检 429 也不应误触发 30 分钟退避。"""
    import time

    t0 = time.time() - 20
    run_dir = lane.state_root / "runs" / "r1-p1810-formal-429"
    (run_dir / MODELS[0]).mkdir(parents=True)
    outcome = run_dir / "outcome.json"
    outcome.write_text(json.dumps({"run_id": "formal-429-1", "verdict": "FAILED",
                                   "reviews": [{"model": MODELS[0], "verdict": "FAILED"}]}))
    (run_dir / MODELS[0] / "receipt.json").write_text(json.dumps({"failure_code": "rate_limited"}))
    os.utime(outcome, (t0, t0))

    # 中间一次预检通过（此时 preflight-rate-limits.json 原本不存在）
    target = lane.target(1810, 1)
    # 随后一次预检 429
    lane._record_preflight_rate_limit(target, rate_limited=True, models=[MODELS[0]])

    sweep, _, _ = make(lane, run=False)
    assert sweep.rate_limit_backoff() is None


def test_preflight_failure_next_tick_in_launch_backoff_never_merges_on_cross_pr_green_sha(lane):
    """预检失败不写 target.json、只留 launch-backoff 标记；下一轮无活进程且不重派时，绝不能凭跨 PR 同 SHA 的旧绿灯自动合入。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    lane.preflight = lambda _t: {"returncode": 2, "report": {"kind": "review-preflight", "is_review_result": False,
                                                             "ready": False, "checks": [{"name": f"route:{MODELS[0]}", "ok": False}]}}
    def failing_spawn(number, attempt, h, log, base=None):
        try:
            lane.review_pr(number, attempt)
        except Exception:
            pass
        return 4100

    sweep = Sweep(github, lane, failing_spawn, state_root=lane.state_root, rows=lambda: [],
                  auto_merge=True, review_app=lambda: 5664795)
    # 第一轮：派审后预检失败，无 target.json，且本轮不合入
    first = sweep.tick()
    assert acts(first) == ["launch", "waiting"] and lane.status(1810) == [] and github.calls == []
    # 第二轮：处于 launch-backoff（无活进程、不派工），仍必须拒绝合入
    second = sweep.tick()
    assert acts(second) == ["launch-backoff", "waiting"] and github.calls == []
    waiting = next(a for a in second if a.get("pr") == 1810 and a["action"] == "waiting")
    assert waiting.get("pending_latest_attempt") is True


def test_inflight_preflight_lock_blocks_auto_merge_under_pr_lock(lane):
    """已有 A1 已发布 PASS 后，人工重审 A2 若在 tick 快照之后进入预检（持不占 attempt 的在途锁、尚未写 target.json），合入锁内必须拦截。"""
    import threading

    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    green(github, head)
    entered = threading.Event()
    release = threading.Event()

    def hold_preflight():
        with lane._inflight_review(1810):
            entered.set()
            assert release.wait(5)

    # 在规划前已有 A1 PASS；但在进入合入写阶段前，另一线程进入预检持在途锁
    orig_checks = github.checks
    holder = threading.Thread(target=hold_preflight)

    def checks_then_start_manual_preflight(h, bindings):
        res = orig_checks(h, bindings)
        if not holder.is_alive():
            holder.start()
            assert entered.wait(5)
        return res

    github.checks = checks_then_start_manual_preflight
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    try:
        actions = sweep.tick()
    finally:
        release.set()
        holder.join(timeout=5)
    assert github.calls == []
    waiting = [a for a in actions if a.get("pr") == 1810 and a["action"] == "waiting"]
    assert waiting and waiting[-1].get("pending_latest_attempt") is True


def test_spawn_type_error_propagates_without_retry_and_no_auto_merge_write(lane):
    """1. _launch 统一使用五参数 Spawn 接口，spawn 内部抛出 TypeError 时直接上报为 error，绝不二次重调去掉 base；
    2. 全绿 PR 在 --auto-merge 下也绝不自动发起 PUT /pulls/{n}/merge，改报 needs-human-confirm 并撤原生 auto-merge。"""
    calls = []

    def broken_spawn(number, attempt, head, log, base=None):
        calls.append((number, attempt, head, base))
        raise TypeError("internal callback bug")

    github = FakeGitHub(lane)
    sweep = Sweep(github, lane, broken_spawn, state_root=lane.state_root, rows=lambda: [],
                  auto_merge=False, review_app=lambda: 5664795)
    actions = sweep.tick()
    assert len(calls) == 1 and calls[0][3] == lane.gateway.pr["base"]["sha"]
    assert acts(actions) == ["error"] and "TypeError: internal callback bug" in actions[0]["reason"]

    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    github2 = FakeGitHub(lane)
    _ordinary_armed(lane, github2)
    sweep2, _, _ = make(lane, run=False, github=github2, auto_merge=True)
    actions2 = sweep2.tick()
    confirm = next(a for a in actions2 if a.get("pr") == 1810 and a["action"] == "needs-human-confirm")
    assert confirm["gated"] == ["base-ref-not-server-bound"]
    assert github2.calls == [("disable", 1810)]


def test_dispatch_and_merge_share_exact_base_head_target_and_recheck_live_base(lane, env):
    """1. 文件清单分类后、规划复核时实时 base 漂移：报 base-moved 并撤原生 auto-merge；
    2. 全部门禁就绪但无服务端 expected_base_ref 时转人工确认并撤原生 auto-merge；
    3. main 前进到 head 已包含的提交（clean，无须追平）时，派审不把旧 base 判 done，而是为新 base 派审。"""
    single_head = lane.gateway.pr["head"]["sha"]
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    # 文件清单分类后、规划复核时 base 漂移：报 base-moved 并撤掉原生 auto-merge
    github3 = FakeGitHub(lane)
    _ordinary_armed(lane, github3)
    orig_pr3 = github3.pr
    reads3 = []

    def drift_base_on_plan_recheck(number):
        reads3.append(number)
        st = orig_pr3(number)
        if len(reads3) >= 2:
            st["base"] = "1" * 40
        return st

    github3.pr = drift_base_on_plan_recheck
    sweep3, _, _ = make(lane, run=False, github=github3, auto_merge=True)
    third = sweep3.tick()
    assert any(a.get("pr") == 1810 and a["action"] == "base-moved" for a in third)
    assert github3.calls == [("disable", 1810)]

    # 追加第二笔提交形成 multi-commit PR（old_base -> single_head -> head2）
    (env.source / "changed-2").write_text("2")
    git(env.source, "add", ".")
    git(env.source, "commit", "-qm", "change-1")
    head2 = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = head2
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    # 全绿但 GitHub 合入接口缺服务端 expected_base_ref 绑定：转人工确认并撤原生 auto-merge
    github_mid = FakeGitHub(lane)
    _ordinary_armed(lane, github_mid)
    sweep_mid, _, _ = make(lane, run=False, github=github_mid, auto_merge=True)
    mid_actions = sweep_mid.tick()
    assert any(a.get("pr") == 1810 and a["action"] == "needs-human-confirm" and a.get("gated") == ["base-ref-not-server-bound"]
               for a in mid_actions)
    assert github_mid.calls == [("disable", 1810)]

    # main 前进到 head2 的直系父提交 single_head（已包含在 head2 中，PR 仍为 clean）：不把旧 base 判 done，而是为新 base 派审
    lane.gateway.pr["base"]["sha"] = single_head
    github = FakeGitHub(lane)
    green(github, head2)
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    first = sweep.tick()
    assert acts(first) == ["launch", "waiting"] and github.calls == []
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 1)]


def test_resume_markers_are_isolated_per_base_and_missing_object_triggers_sync(lane, env):
    """1. 不同 base 的同编号 attempt 拥有独立续跑标记；2. 本地缺 base 提交对象时 _is_ancestor 不误判 done，先触发 sync。"""
    (env.source / "changed-2").write_text("2")
    git(env.source, "add", ".")
    git(env.source, "commit", "-qm", "change-1")
    lane.gateway.pr["head"]["sha"] = git(env.source, "rev-parse", "HEAD")
    old_base = lane.gateway.pr["base"]["sha"]
    head = lane.gateway.pr["head"]["sha"]
    parent_of_head = git(env.source, "rev-parse", f"{head}~1")

    # 旧 base 的 A1 登记后中断并消耗一次续跑，随后完成发布
    lane.target(1810, 1)
    sweep, host, _ = make(lane, run=False)
    assert acts(sweep.tick()) == ["resume-review"]
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    # base 改为本地尚未拉取的未知对象：绝不误判 done，必须触发 sync（无 sync 时报 needs-source-sync）
    lane.gateway.pr["base"]["sha"] = "f" * 40
    sync_calls = []
    sweep_sync, _, _ = make(lane, run=False)
    sweep_sync.sync = lambda n, b, h: sync_calls.append((n, b, h))
    assert acts(sweep_sync.tick()) == ["needs-source-sync"]
    assert sync_calls == [(1810, "f" * 40, head)]

    # base 前进到 head 祖先 parent_of_head：新 base 的 A1 中断后必须拥有独立的首次续跑机会
    lane.gateway.pr["base"]["sha"] = parent_of_head
    lane.target(1810, 1)
    host.rows.clear()
    assert acts(sweep.tick()) == ["resume-review"]
    assert sweep._resumes(1810, head, 1, old_base).is_file()
    assert sweep._resumes(1810, head, 1, parent_of_head).is_file()


def test_old_base_unpublished_outcome_unblocks_update_branch_and_merge_commit_is_server_bound(lane, env):
    """1. 旧 base 上尚未发布的 outcome 被新 base 取代后不得卡在 needs-reconcile 堵死追平；
    2. 多提交 PR 经 update-branch 产生追平合入提交 M=merge(multi_commit, new_base) 后，
       rev-list --ancestry-path new_base..M == [M]（无严格中间祖先），满足服务端精确 base 绑定并正常自动合入。"""
    # 给 PR 叠两笔提交，并制造一条旧 base 的未发布 outcome（无 publication）
    (env.source / "changed-2").write_text("2")
    git(env.source, "add", ".")
    git(env.source, "commit", "-qm", "change-1")
    multi_head = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = multi_head
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    old_target = ReviewTarget(**passed["target"])
    old_folder = lane.state_root / "runs" / old_target.key
    unpublished = {k: v for k, v in passed.items() if k != "publication"}
    _external_review.module._save(old_folder / "outcome.json", unpublished)

    # main 前进到独立提交 new_base（PR 变为 behind）：旧 base 未发布 outcome 绝不卡在 needs-reconcile，必须允许追平
    old_base = lane.gateway.pr["base"]["sha"]
    git(env.source, "checkout", "-qb", "main-adv", old_base)
    (env.source / "main-only.txt").write_text("adv")
    git(env.source, "add", ".")
    git(env.source, "commit", "-qm", "main advance")
    new_base = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["base"]["sha"] = new_base

    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["behind-awaiting-update", "behind-waiting"]
    assert actions[-1]["queue_head"] is True and github.calls == []

    # 模拟 update-branch 合并提交 M=merge(multi_head, new_base)：新 base 到 M 无严格中间祖先，审过 PASS 后可正常自动合入
    git(env.source, "checkout", "-q", multi_head)
    git(env.source, "merge", "--no-ff", "-m", "update branch", new_base)
    merged_head = git(env.source, "rev-parse", "HEAD")
    lane.gateway.pr["head"]["sha"] = merged_head
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    github2 = FakeGitHub(lane)
    green(github2, merged_head)
    sweep2, _, _ = make(lane, run=False, github=github2, auto_merge=True)
    actions2 = sweep2.tick()
    assert acts(actions2) == ["done", "needs-human-confirm"]
    assert actions2[-1]["gated"] == ["base-ref-not-server-bound"]
    assert github2.calls == []


def test_retarget_to_non_main_same_sha_is_blocked_and_failed_rereview_blocks_old_pass(lane):
    """1. PR 改指与 main 同 SHA 的非 main 分支时（首次读取与分类复核），一律报 base-ref-moved、不派审、撤原生 auto-merge；
    2. A1 已 PASS 后手动 A2 预检失败退出，持久重审意图阻止下轮 sweep 判 done 或放行就绪，且不占队首。"""
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    head = lane.gateway.pr["head"]["sha"]

    # 1a. 规划分类后改指非 main 分支（同 SHA）
    github1 = FakeGitHub(lane)
    _ordinary_armed(lane, github1)
    orig_pr1 = github1.pr
    reads1 = []

    def retarget_after_files(number):
        reads1.append(number)
        st = orig_pr1(number)
        if len(reads1) >= 2:
            st["base_ref"] = "release"
        return st

    github1.pr = retarget_after_files
    sweep1, _, _ = make(lane, run=False, github=github1, auto_merge=True)
    a1 = sweep1.tick()
    assert any(a.get("pr") == 1810 and a["action"] == "base-ref-moved" for a in a1)
    assert github1.calls == [("disable", 1810)]

    # 1b. 列 PR 后首次读 pr() 即发现已改指非 main 分支：既不派审也撤原生 auto-merge
    github2 = FakeGitHub(lane)
    _ordinary_armed(lane, github2)
    github2.states[1810]["base_ref"] = "release"
    sweep2, host2, _ = make(lane, run=False, github=github2, auto_merge=True)
    a2 = sweep2.tick()
    assert host2.spawned == []
    assert acts(a2) == ["base-ref-moved", "base-ref-moved"]
    assert github2.calls == [("disable", 1810)]

    # 2. 手动 A2 预检失败退出（不写 target.json），下轮 sweep 不得把 A1 判 done，也不得凭旧 PASS 合入
    lane.preflight = lambda _t: {"returncode": 2, "report": None, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(_external_review.EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    github3 = FakeGitHub(lane)
    green(github3, head)
    sweep3, _, _ = make(lane, run=False, github=github3, auto_merge=True)
    a3 = sweep3.tick()
    assert acts(a3) == ["rereview-pending", "waiting"]
    assert a3[-1]["queue_head"] is False
    assert "rereview-pending" in module.STUCK_REVIEW
    assert "base-ref-moved" in module.STUCK_REVIEW
    assert github3.calls == []


def test_timeout_after_planning_waiting_or_behind_still_withdraws_armed_auto_merge(lane):
    """R14：先规划的普通 waiting / behind-waiting PR 挂着原生 auto-merge，若后续 PR 读超时，fail_closed 仍必须撤回它。"""
    for mergeable_state in ("clean", "behind"):
        github = FakeGitHub(lane)
        _more_pulls(lane, github, [1805])
        github.extra_pulls[0]["auto_merge"] = {"merge_method": "merge"}
        github.states[1805] = {"auto_merge": True, "mergeable_state": mergeable_state}
        github.files[1805] = [{"filename": "src/ordinary.py", "status": "modified", "changes": 1}]
        lane.gateway.pr["auto_merge"] = None
        github.states[1810] = {"auto_merge": False}

        orig_files = github.pr_files
        github.pr_files = lambda n, orig=orig_files: _hang() if n == 1810 else orig(n)

        sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
        with pytest.raises(SourceUnreadable) as caught:
            sweep.tick()
        assert github.calls == [("disable", 1805)]
        assert any(a.get("pr") == 1805 and a["action"] in ("auto-merge-withdraw", "fail-closed-withdraw")
                   and a.get("auto_merge_withdrawn") is True for a in caught.value.actions)


@pytest.mark.parametrize("change", ["draft", "foreign", "stale"])
def test_ineligible_prs_withdraw_armed_auto_merge_independently_of_review_dispatch(lane, change):
    """R14：draft/foreign-head/stale-pr 跳过派审但独立撤回已挂原生 auto-merge（正常轮与超时 fail_closed 皆然）；明确无 auto_merge 时零额外调用。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    armed_pr = lane.gateway.pr
    unarmed_pr = github.extra_pulls[0]
    for target_pr in (armed_pr, unarmed_pr):
        if change == "draft":
            target_pr["draft"] = True
        elif change == "foreign":
            target_pr["head"]["repo"]["id"] = 1
        else:
            target_pr["updated_at"] = "2026-01-01T00:00:00Z"
    armed_pr["auto_merge"] = {"merge_method": "merge"}
    unarmed_pr["auto_merge"] = None

    pr_reads = []
    orig_pr = github.pr
    github.pr = lambda n: pr_reads.append(n) or orig_pr(n)

    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True,
                          now=lambda: datetime(2026, 11, 7, tzinfo=timezone.utc))
    actions = sweep.tick()
    assert host.spawned == [] and pr_reads == []
    assert github.calls == [("disable", 1810)]
    withdraw = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "auto-merge-withdraw")
    assert withdraw["auto_merge_withdrawn"] is True

    # 中途超时时 fail_closed 同样对跳过派审且挂着原生 auto-merge 的 PR 撤回，明确 auto_merge=None 的跳过
    github.calls.clear()
    github.required_checks = _hang
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert github.calls == [("disable", 1810)]
    assert any(a.get("pr") == 1810 and a["action"] in ("auto-merge-withdraw", "fail-closed-withdraw")
               and a.get("auto_merge_withdrawn") is True for a in caught.value.actions)


def test_recheck_discovers_auto_merge_then_checks_error_still_withdraws(lane):
    """R15：首次读 pr() 时 auto_merge=False，_plan_one 复核 pr() 发现变为 True，随后 checks() 报非超时 API 错误：
    异常分支必须读取最新 state["auto_merge"] 并执行 disable_auto_merge。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"auto_merge": False}
    orig_pr = github.pr
    reads = []

    def pr_turns_armed_on_recheck(number):
        reads.append(number)
        st = orig_pr(number)
        if len(reads) >= 2:
            st["auto_merge"] = True
        return st

    github.pr = pr_turns_armed_on_recheck
    github.checks = _raise
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    ev = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "evidence-insufficient")
    assert ev.get("auto_merge_withdrawn") is True
    assert github.calls == [("disable", 1810)]


def test_armed_pr_disables_auto_merge_before_dispatch_and_blocks_on_withdraw_failure(lane):
    """R16（Sol P1）：原生 auto-merge 必须先于任何可能发布 success 的审查/沿用派发完成撤回；
    仓库 allow_auto_merge=true 或撤回失败时严禁派发子进程。"""
    order: list[tuple[str, int]] = []
    github = FakeGitHub(lane)
    github.states[1810] = {"auto_merge": True}
    orig_disable = github.disable_auto_merge

    def record_disable(number):
        order.append(("disable", number))
        orig_disable(number)

    github.disable_auto_merge = record_disable
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    orig_spawn = sweep.spawn

    def record_spawn(number, attempt, head, log, base=None):
        order.append(("spawn", number))
        return orig_spawn(number, attempt, head, log, base)

    sweep.spawn = record_spawn
    actions = sweep.tick()
    assert order == [("disable", 1810), ("spawn", 1810)]
    assert any(a.get("pr") == 1810 and a["action"] == "launch" for a in actions)

    # 撤回失败时绝不派发子进程
    github2 = FakeGitHub(lane)
    github2.states[1810] = {"auto_merge": True}
    github2.disable_auto_merge = _raise
    sweep2, host2, _ = make(lane, run=False, github=github2, auto_merge=True)
    actions2 = sweep2.tick()
    assert host2.spawned == []
    assert any(a.get("pr") == 1810 and a["action"] == "held-auto-merge-withdraw-failed" for a in actions2)

    # 仓库 allow_auto_merge=true（或读不到）时绝不派发子进程（即便 PR 当前未挂 auto-merge）
    for unsafe_fn in (lambda: True, _raise):
        github3 = FakeGitHub(lane)
        github3.states[1810] = {"auto_merge": False}
        github3.allow_auto_merge = unsafe_fn
        sweep3, host3, _ = make(lane, run=False, github=github3, auto_merge=True)
        actions3 = sweep3.tick()
        assert host3.spawned == []
        assert any(a.get("pr") == 1810 and a["action"] == "held-native-auto-merge" for a in actions3)


def test_pr_state_timeout_marks_unreadable_so_fail_closed_withdraws_despite_stale_null_snapshot(lane):
    """R16（Astra P1）：open_pulls 快照显示 auto_merge=None，随后实时 pr() 读取或复核超时：
    fail_closed 必须将该 PR 视为状态未知并尝试撤回原生 auto-merge，不按旧快照跳过。"""
    lane.gateway.pr["auto_merge"] = None
    github = FakeGitHub(lane)
    github.pr = _hang
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert host.spawned == []
    assert github.calls == [("disable", 1810)]
    assert any(a.get("pr") == 1810 and a["action"] == "fail-closed-withdraw" for a in caught.value.actions)

    # 首次 pr() 返回 auto_merge=False，但 _plan_one 复核 pr() 超时时同样须加入 unreadable 兜底撤回
    github2 = FakeGitHub(lane)
    github2.states[1810] = {"auto_merge": False}
    orig_pr = github2.pr
    calls = []

    def pr_hang_on_recheck(number):
        calls.append(number)
        if len(calls) >= 2:
            _hang()
        return orig_pr(number)

    github2.pr = pr_hang_on_recheck
    sweep2, _, _ = make(lane, run=False, github=github2, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught2:
        sweep2.tick()
    assert github2.calls == [("disable", 1810)]
    assert any(a.get("pr") == 1810 and a["action"] == "fail-closed-withdraw" for a in caught2.value.actions)


def test_recheck_pr_non_timeout_error_marks_unknown_and_withdraws_auto_merge(lane):
    """R17（Astra P1）：首次 pr() 返回 auto_merge=False，_plan_one 复核 pr() 遇 HTTP 502 等非超时错误：
    必须同样将状态视为未知并执行 disable_auto_merge，不沿用旧 False 跳过撤回。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"auto_merge": False}
    orig_pr = github.pr
    calls = []

    def pr_502_on_recheck(number):
        calls.append(number)
        if len(calls) >= 2:
            raise RuntimeError("gh api HTTP 502 Bad Gateway")
        return orig_pr(number)

    github.pr = pr_502_on_recheck
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    ev = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "evidence-insufficient")
    assert ev.get("auto_merge_withdrawn") is True
    assert github.calls == [("disable", 1810)]


def test_stale_rereview_attempt_keeps_rereview_pending_instead_of_reverting_to_old_pass_done(lane, env):
    """R17（Astra P1）：A1 已发布 PASS -> A2 预检失败写重审意图 -> A2 登记后因控制器切换变 STALE：
    重审意图不得在登记时被删，sweep 必须继续报 rereview-pending，绝不把旧 A1 判 done。"""
    from pilot1742 import external_review as ext
    from pilot1742.delivery import EffectPending

    head = lane.gateway.pr["head"]["sha"]
    base = lane.gateway.pr["base"]["sha"]
    orig_preflight = lane.preflight
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"

    lane.preflight = lambda _t: {"returncode": 2, "report": None, "image_id": "sha256:" + "1" * 64}
    with pytest.raises(EffectPending, match="preflight-blocked"):
        lane.target(1810, 2)
    assert lane.has_pending_rereview_intent(1810, head, base) is True

    lane.preflight = orig_preflight
    t2 = lane.target(1810, 2)
    folder2 = lane.state_root / "runs" / t2.key
    ext._save(folder2 / "outcome.json", {"run_id": t2.run_id, "verdict": "STALE", "reason": "controller switched"})
    assert lane.has_pending_rereview_intent(1810, head, base) is True

    github = FakeGitHub(lane)
    green(github, head)
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["rereview-pending", "waiting"]
    assert actions[-1]["queue_head"] is False


def test_multi_pr_state_timeout_marks_all_remaining_eligible_prs_unreadable_in_fail_closed(lane):
    """R19（Astra P1）：open_pulls 快照中多个合格 PR 均显示 auto_merge=None；1805 实时读回 False，1810 超时后
    1815 尚未读取，fail_closed 必须把 1810 与余下未读的 1815 全部记未知并撤回原生 auto-merge，不误撤已确认 False 的 1805。"""
    lane.gateway.pr["auto_merge"] = None
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805, 1815])
    for extra in github.extra_pulls:
        extra["auto_merge"] = None
    github.states[1805] = {"auto_merge": False}
    orig_pr = github.pr

    def pr_hang_on_1810(number):
        if number == 1810:
            _hang()
        return orig_pr(number)

    github.pr = pr_hang_on_1810
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert host.spawned == []
    assert github.calls == [("disable", 1810), ("disable", 1815)]
    withdrawn_prs = [a["pr"] for a in caught.value.actions if a["action"] == "fail-closed-withdraw"]
    assert withdrawn_prs == [1810, 1815]


def test_armed_pr_withdrawn_immediately_before_classification_and_other_pr_reads(lane):
    """R20（Astra P1）：一旦实时状态发现 PR 挂着原生 auto-merge，必须立即撤回，
    排在 allow_auto_merge、required_checks、pr_files、checks 与派审之前，绝不拖延到整轮规划结束。"""
    events: list[str] = []
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805])
    github.states[1805] = {"auto_merge": True}
    github.states[1810] = {"auto_merge": True}
    orig_disable = github.disable_auto_merge
    orig_allow = github.allow_auto_merge
    orig_req = github.required_checks
    orig_files = github.pr_files
    orig_checks = github.checks

    github.disable_auto_merge = lambda n: (events.append(f"disable:{n}"), orig_disable(n))[1]
    github.allow_auto_merge = lambda: (events.append("allow_auto_merge"), orig_allow())[1]
    github.required_checks = lambda: (events.append("required_checks"), orig_req())[1]
    github.pr_files = lambda n: (events.append(f"pr_files:{n}"), orig_files(n))[1]
    github.checks = lambda sha, *a: (events.append("checks"), orig_checks(sha, *a))[1]

    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True, max_running=2)
    orig_spawn = sweep.spawn
    sweep.spawn = lambda n, *a, **kw: (events.append(f"spawn:{n}"), orig_spawn(n, *a, **kw))[1]

    sweep.tick()
    for pr_num in (1805, 1810):
        assert f"disable:{pr_num}" in events
        idx_disable = events.index(f"disable:{pr_num}")
        for later in ("allow_auto_merge", "required_checks", "pr_files:1805", "pr_files:1810", "checks", "spawn:1810"):
            assert later in events and idx_disable < events.index(later), (events, pr_num, later)


def test_rearmed_auto_merge_invalidates_prior_withdrawn_so_fail_closed_withdraws_again(lane):
    """R21（Sol P1 / Astra P1）：本轮早期成功撤回 1810 后，复核 pr() 发现它被重新挂起原生 auto-merge，
    随后 checks() 超时导致未执行计划写阶段：必须立即作废旧 withdrawn 记录，fail_closed 再次撤回 1810。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"auto_merge": True}
    orig_pr = github.pr
    reads = []

    def pr_rearmed_on_recheck(number):
        reads.append(number)
        st = orig_pr(number)
        if len(reads) >= 2:
            st["auto_merge"] = True
        return st

    github.pr = pr_rearmed_on_recheck
    github.checks = _hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert github.calls == [("disable", 1810), ("disable", 1810)]
    assert any(a.get("pr") == 1810 and a["action"] == "fail-closed-withdraw" and a.get("auto_merge_withdrawn") is True
               for a in caught.value.actions)


def test_preflight_induced_quota_pause_before_pending_does_not_burn_resume_and_recovers(lane, monkeypatch):
    """R22（Sol P1）：新 attempt 预检成功并记账 2*4096 token 后恰把 24h 额度推到上限，导致 review_pr 在发 pending
    与建工蜂目录前触发 quota-paused：sweep 在额度未回落前不得消耗唯一 .resumes 机会，额度回落后须自动恢复并完成 PASS。"""
    from pilot1742 import external_review as ext
    from pilot1742.delivery import EffectPending

    cap = len(ext.MODELS) * ext.PREFLIGHT_TOKENS_PER_PROBE
    monkeypatch.setenv(ext.DAILY_INPUT_CAP_ENV, str(cap))

    github = FakeGitHub(lane)
    spawned: list[tuple[int, int]] = []

    def child(number, attempt, head, log, base=None):
        spawned.append((number, attempt))
        try:
            lane.review_pr(number, attempt, expect_head=head, expect_base=base)
        except EffectPending:
            pass
        return 5000 + len(spawned)

    sweep = Sweep(github, lane, child, state_root=lane.state_root, rows=lambda: [], max_running=3)
    # 第 1 轮：额度为 0 < cap -> 派发 attempt 1 -> 预检记账 cap -> review_pr 在 pending 前因 quota-paused 退出
    first = sweep.tick()
    assert acts(first) == ["launch"] and len(spawned) == 1
    row = lane.status(1810)[0]
    assert row["outcome"] is None
    folder = lane.state_root / "runs" / ext.ReviewTarget(**row["target"]).key
    assert (folder / ext.QUOTA_PAUSED_FILE).exists()
    assert not (folder / "effects" / "status-pending.json").exists()

    # 第 2、3 轮：额度仍在上限 -> sweep 报 quota-paused，不派必死子进程、不消耗 .resumes，绝不掉进 needs-operator
    for _ in range(2):
        paused = sweep.tick()
        assert acts(paused) == ["quota-paused"]
    assert len(spawned) == 1
    assert not list((lane.state_root / "sweep").glob("*.resumes"))

    # 模拟额度恢复后（如次日或提额），并且清掉 launch-backoff 窗口：sweep 自动续跑完成 PASS，不卡在 needs-operator
    monkeypatch.setenv(ext.DAILY_INPUT_CAP_ENV, str(cap * 100))
    for marker in (lane.state_root / "sweep").glob("*.launched"):
        marker.unlink()
    recovered = sweep.tick()
    assert acts(recovered) == ["launch"] and len(spawned) == 2
    assert lane.status(1810)[0]["outcome"]["verdict"] == "PASS"
    assert not (folder / ext.QUOTA_PAUSED_FILE).exists()
    assert not list((lane.state_root / "sweep").glob("*.resumes"))


def test_legacy_contract_pass_never_enters_done_or_confirmed_pass(lane, monkeypatch):
    """R26/R27（Sol P1）：旧合同（v1 Kimi/Opus）已发布 PASS 保留历史，但既不在 decide 中判 done（改为派发新合同 attempt 2），
    也不通过 _confirmed_published_pass 或在 --auto-merge 审计中输出 base-ref-not-server-bound。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    base = lane.gateway.pr["base"]["sha"]
    github.states[1810] = {"mergeable_state": "clean", "auto_merge": False}
    github.files[1810] = [{"filename": "src/a.py", "status": "modified", "changes": 1}]
    green(github, head)

    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        old_target = lane.target(1810, 1)
    old_folder = lane.state_root / "runs" / old_target.key
    (old_folder / "outcome.json").write_text(json.dumps({
        "verdict": "PASS", "publication": {"id": 1, "state": "success"},
    }))

    assert module._confirmed_published_pass(lane, 1810, head, base) is False
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["launch", "waiting"]
    assert [(s[0], s[1]) for s in host.spawned] == [(1810, 2)]
    assert not any(a.get("gated") == ["base-ref-not-server-bound"] for a in actions)


def test_plan_one_uses_rechecked_mergeable_state_and_withdraws_auto_merge(lane):
    """R26/R27（Astra P1）：_plan_one 第二次读取 PR（pr_files 之后）若 mergeable_state 已变为 blocked，
    绝不能沿用第一次读取的 clean 判就绪，而是报 waiting(mergeable-state-changed) 并撤回挂着的原生 auto-merge。"""
    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    head = lane.gateway.pr["head"]["sha"]
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "clean", "auto_merge": False}
    github.files[1810] = [{"filename": "src/a.py", "status": "modified", "changes": 1}]
    green(github, head)

    calls = 0
    orig_pr = github.pr

    def drifting_pr(number):
        nonlocal calls
        calls += 1
        data = dict(orig_pr(number))
        if calls >= 2:
            data["mergeable_state"] = "blocked"
            data["auto_merge"] = True
        return data

    github.pr = drifting_pr  # type: ignore[method-assign]
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert any(a.get("action") == "waiting" and a.get("reason") == "mergeable-state-changed" for a in actions)
    assert ("disable", 1810) in github.calls
    assert not any(a.get("gated") == ["base-ref-not-server-bound"] for a in actions)


def test_concurrent_sweep_ticks_are_serialized_by_sweep_lock(lane):
    """R26/R31（Astra P1/P2）：同一状态根上的并发 Sweep.tick() 经非阻塞 sweep.lock 互斥：
    已有巡检持锁时另一轮立刻跳过并返回 sweep-busy（绝不阻塞 executor serve 主循环），持锁方退出后恢复正常。"""
    import threading

    assert lane.review_pr(1810, 1)["verdict"] == "PASS"
    head = lane.gateway.pr["head"]["sha"]
    gh1 = FakeGitHub(lane)
    gh1.states[1810] = {"mergeable_state": "clean", "auto_merge": False}
    gh1.files[1810] = [{"filename": "src/a.py", "status": "modified", "changes": 1}]
    green(gh1, head)

    entered = threading.Event()
    release = threading.Event()
    orig_files = gh1.pr_files

    def slow_files(number):
        entered.set()
        assert release.wait(timeout=5)
        return orig_files(number)

    gh1.pr_files = slow_files  # type: ignore[method-assign]
    gh2 = FakeGitHub(lane)
    gh2.states[1810] = {"mergeable_state": "clean", "auto_merge": False}
    gh2.files[1810] = [{"filename": "src/a.py", "status": "modified", "changes": 1}]
    green(gh2, head)

    s1, _, _ = make(lane, run=False, github=gh1, auto_merge=True)
    s2, _, _ = make(lane, run=False, github=gh2, auto_merge=True)
    t1_done: list[str] = []

    def run1():
        s1.tick()
        t1_done.append("t1")

    t1 = threading.Thread(target=run1)
    t1.start()
    assert entered.wait(timeout=5)
    # t1 持锁期间，s2.tick() 必须非阻塞立即返回 sweep-busy，不等待 t1 也不并发写
    busy_actions = s2.tick()
    assert [a["action"] for a in busy_actions] == ["sweep-busy"]
    assert t1_done == []
    release.set()
    t1.join(timeout=10)
    assert t1_done == ["t1"]
    # 锁释放后，下一轮 s2.tick() 恢复正常执行
    after_actions = s2.tick()
    assert "sweep-busy" not in [a["action"] for a in after_actions] and "done" in acts(after_actions)


def test_reviewing_detects_any_flag_order_and_equals_syntax():
    """R27（Sol P2）：活跃审查进程识别须兼容任意参数顺序（如先 --attempt 再 --pr）与 --pr=N，且忽略僵尸进程。"""
    rows = [
        (101, 1, "S", "python -m pilot1742.external_review review-pr --attempt 2 --pr 2207 --private-key /k.pem"),
        (102, 1, "S", "python -m pilot1742.external_review review-pr --attempt=1 --pr=2208 --private-key=/k.pem"),
        (103, 1, "S", "python -m pilot1742.review_sweep run-review --expect-head abc --pr=2209 --attempt 1"),
        (104, 1, "Z", "python -m pilot1742.external_review review-pr --pr 2210"),
        (105, 1, "S", "python -m pilot1742.external_review status --pr 2211"),
    ]
    assert module.reviewing(rows) == {2207, 2208, 2209}
    assert module.reviewer_processes(rows) == 3


def test_verify_pass_binds_pr_contract_base_head_run_id_and_rejects_rereview_or_legacy(lane, monkeypatch, capsys):
    """R28（Sol P1 + Astra P1）：合入前只读核验 verify-pass 必须把远端状态的 run_id 精确对回本 PR、
    当前合同、精确 (base, head) 的最新已发布 PASS，并拦截旧合同、跨 PR run_id、活跃审查、在途锁与待完成重审意图。"""
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    head = lane.gateway.pr["head"]["sha"]
    base = lane.gateway.pr["base"]["sha"]
    run_id = passed["run_id"]

    # 1. 精确匹配 -> 退出码 0
    assert module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id], lane=lane, rows=list,
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["run_id"] == run_id and out["policy_version"] == module.POLICY

    # 2. 跨 PR 同 head 的不同 run_id -> 退出码 2 (run-id-mismatch)
    assert module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", "other-pr-run-id"], lane=lane, rows=list,
    ) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "run-id-mismatch"

    # 3. 活跃审查进程（含 --attempt 在前与 --pr=N）-> 退出码 2 (review-running)
    live_rows = [(777, 1, "S", "python -m pilot1742.external_review review-pr --attempt 2 --pr=1810")]
    assert module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id], lane=lane, rows=lambda: live_rows,
    ) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "review-running"

    # 4. 本机预检在途锁 -> 退出码 2 (inflight-review-active)
    with lane._inflight_review(1810):
        assert module.run_verify_pass(
            ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id], lane=lane, rows=list,
        ) == 2
        assert json.loads(capsys.readouterr().err)["code"] == "inflight-review-active"

    # 5. 待完成重审意图 -> 退出码 2 (rereview-pending)
    lane._record_rereview_intent(ReviewTarget(**passed["target"]))
    assert module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id], lane=lane, rows=list,
    ) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "rereview-pending"

    # 6. 旧合同已发布 PASS -> 退出码 2 (legacy-contract)
    lane2 = _external_review.ExternalReview(
        lane.gateway, source=lane.source, state_root=lane.state_root / "legacy-only",
        checkout_root=lane.checkout_root, poll_seconds=0.01, preflight=lane.preflight,
    )
    with monkeypatch.context() as legacy:
        _external_review._use_contract(legacy, _external_review.LEGACY_MODELS, _external_review.LEGACY_POLICY)
        old_target = lane2.target(1810, 1)
    (lane2.state_root / "runs" / old_target.key / "outcome.json").write_text(json.dumps({
        "run_id": old_target.run_id, "verdict": "PASS", "publication": {"id": 9, "state": "success"},
    }))
    assert module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", old_target.run_id], lane=lane2, rows=list,
    ) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "legacy-contract"


def test_verify_pass_holds_exclusive_pr_locks_during_check_and_rejects_incomplete_publication(lane, capsys):
    """R29/R31（Sol P1 + Astra P1 + Astra P2）：
    1. verify-pass 为纯只读本机核验，在核验瞬间同时排他持有 inflight.lock 与 p<N>.lock，退出即释锁并明示 snapshot-only；
    2. p<N>.lock 被占用或 merge_base != base 时立即拒绝；
    3. 缺少 id/state/sha 或字段不合法的残缺 publication 一律以 not-published-pass 拒绝。"""
    passed = lane.review_pr(1810, 1)
    assert passed["verdict"] == "PASS"
    head = lane.gateway.pr["head"]["sha"]
    base = lane.gateway.pr["base"]["sha"]
    run_id = passed["run_id"]
    folder = lane.state_root / "runs" / ReviewTarget(**passed["target"]).key

    # 1. 核验执行期间（rows() 回调触发时）两把排他锁均已持有，返回后立即释放
    seen: dict[str, object] = {}

    def probe_rows():
        with lane.try_exclude_inflight_review(1810) as excl:
            seen["inflight_free_during_check"] = excl
        with lane.try_pr_lock(1810) as pr_free:
            seen["pr_lock_free_during_check"] = pr_free
        return []

    rc = module.run_verify_pass(
        ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id],
        lane=lane, rows=probe_rows,
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["lock_scope"] == "snapshot-only-unlocked-after-exit"
    assert seen == {"inflight_free_during_check": False, "pr_lock_free_during_check": False}
    with lane.try_exclude_inflight_review(1810) as excl, lane.try_pr_lock(1810) as pr_free:
        assert excl is True and pr_free is True

    # 2. p<N>.lock 被占用时立即拒绝
    with lane._pr_lock(1810):
        assert module.run_verify_pass(
            ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id],
            lane=lane, rows=list,
        ) == 2
        assert json.loads(capsys.readouterr().err)["code"] == "pr-lock-busy"

    # 3. 残缺 publication（空字典 / 缺 sha / 缺 state / id 非正整数 / sha 不符）全部拒放
    orig_outcome = json.loads((folder / "outcome.json").read_text())
    for bad_pub in (
        {},
        {"id": 1},
        {"id": 1, "state": "success"},
        {"id": 1, "sha": head},
        {"id": True, "state": "success", "sha": head},
        {"id": 1, "state": "failure", "sha": head},
        {"id": 1, "state": "success", "sha": "0" * 40},
    ):
        (folder / "outcome.json").write_text(json.dumps({**orig_outcome, "publication": bad_pub}))
        assert module.run_verify_pass(
            ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id],
            lane=lane, rows=list,
        ) == 2
        assert json.loads(capsys.readouterr().err)["code"] == "not-published-pass"
    (folder / "outcome.json").write_text(json.dumps(orig_outcome))

    # 4. R32（Sol P2）：纯只读约束——核验不存在的 PR 不创建任何目录或锁文件，直接返回结构化 no-pr-locks；
    #    rereview-intents 不可读时失败闭合返回 rereview-pending。
    empty_lane = _external_review.ExternalReview(None, state_root=lane.state_root / "brand-new-empty")
    assert module.run_verify_pass(
        ["--pr", "9999", "--base", base, "--head", head, "--run-id", run_id],
        lane=empty_lane, rows=list,
    ) == 2
    assert json.loads(capsys.readouterr().err)["code"] == "no-pr-locks"
    assert not (empty_lane.state_root / "pr-locks").exists()

    intent_dir = lane.state_root / "rereview-intents"
    intent_dir.mkdir(exist_ok=True, mode=0o700)
    os.chmod(intent_dir, 0o000)
    try:
        assert module.run_verify_pass(
            ["--pr", "1810", "--base", base, "--head", head, "--run-id", run_id],
            lane=lane, rows=list,
        ) == 2
        assert json.loads(capsys.readouterr().err)["code"] == "rereview-pending"
    finally:
        os.chmod(intent_dir, 0o700)


def test_behind_pr_is_not_reviewed_when_auto_merge_is_off(lane, env):
    """R30（Astra P2）：默认部署关闭 --auto-merge（不拉 mergeable_state）时，首次出现且 base 非 head 祖先的
    落后 PR 仍须判 behind-awaiting-update，不直接派发注定因追平作废的付费双审。"""
    first_head = lane.gateway.pr["head"]["sha"]
    _external_review._advance_main(lane, env)  # main 前进到新 base
    lane.gateway.pr["head"]["sha"] = first_head  # PR 仍停在旧 head，落后于新 base
    sweep, host, _ = make(lane, run=False, auto_merge=False)
    actions = sweep.tick()
    assert acts(actions) == ["behind-awaiting-update"]
    assert host.spawned == []


def test_serve_refuses_without_valid_proxy_receipt_source(monkeypatch, tmp_path, capsys):
    """R29/R31（Astra P2）：executor serve --review-sweep 启动前与 review_preflight.py 同源校验可信代理收据源：
    缺失、相对容器路径或非法容器名均在启动期退出码 2 拒绝启动。"""
    rounds = []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    monkeypatch.delenv("REVIEW_PREFLIGHT_PROXY_RECEIPT_DIR", raising=False)
    monkeypatch.setattr(module, "serve_round", lambda *a, **k: pytest.fail("sweep started without receipt source"))
    monkeypatch.setattr(cli, "_client", lambda args: pytest.fail("App opened"))
    # 1. 缺失任何收据源
    assert cli.main(argv + ["--review-sweep"]) == 2
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("review-sweep ")]
    assert any(json.loads(line.removeprefix("review-sweep "))["action"] == "refused-no-receipt-source" for line in lines)
    # 2. 容器收据目录非绝对路径（与 review_preflight.py:765 同口径拒绝）
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_RECEIPT_CONTAINER", "blackhole-cliproxy")
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_DOCKER_CONTEXT", "orbstack")
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_CONTAINER_RECEIPT_DIR", "receipts")
    assert cli.main(argv + ["--review-sweep"]) == 2
    lines2 = [line for line in capsys.readouterr().out.splitlines() if line.startswith("review-sweep ")]
    assert any(json.loads(line.removeprefix("review-sweep "))["action"] == "refused-no-receipt-source" for line in lines2)
    # 3. 非法容器名（与 review_preflight.py:767 同口径拒绝）
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_RECEIPT_CONTAINER", "-bad-name")
    monkeypatch.setenv("REVIEW_PREFLIGHT_PROXY_CONTAINER_RECEIPT_DIR", "/tmp/cliproxy-preflight-receipts")
    assert cli.main(argv + ["--review-sweep"]) == 2
    lines3 = [line for line in capsys.readouterr().out.splitlines() if line.startswith("review-sweep ")]
    assert any(json.loads(line.removeprefix("review-sweep "))["action"] == "refused-no-receipt-source" for line in lines3)
    assert rounds == []
