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

lane = _external_review.lane  # 复用真实审查 lane 与 PR 替身


class FakeGitHub:
    """GitHub 端口替身：PR、检查、文件与写操作记录。"""
    def __init__(self, lane, *, required=module.MERGE_CHECKS, review_app=5664795):
        self.lane = lane
        if lane is not None:
            lane.gateway.pr.setdefault("auto_merge", None)  # REST 列表用 null 表示未挂载
        self.required = {name: {"deepagents/review": review_app, "ci-ok": 15368, "DevSkim": 15368}[name] for name in required}
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
        state = {"head": p["head"]["sha"], "base": p["base"]["sha"], "changed_files": 1,
                 "mergeable_state": "clean", "auto_merge": False}
        state.update(self.states.get(number, {}))
        return state

    def checks(self, number, state, bindings, review_runs):
        return {k: v for k, v in self.checks_by_head.get(state["head"], {}).items() if bindings.get(k)}

    def review_status(self, number, state, runs, publisher):
        return self.checks(number, state, {"deepagents/review": publisher[0]}, runs).get("deepagents/review")

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


class Host:
    """进程表与子进程替身。run=True 时 spawn 在进程内同步跑完 review_pr，模拟审查子进程结束。"""
    def __init__(self, lane, *, run=True):
        self.lane, self.run, self.rows, self.spawned, self.next_pid = lane, run, [], [], 4000

    def spawn(self, number, attempt, head, log):
        self.next_pid += 1
        self.spawned.append((number, attempt, head))
        if self.run:
            self.lane.review_pr(number, attempt)
        else:
            self.rows.append((self.next_pid, self.next_pid, "S",
                              " ".join(module.run_review_command(number, attempt, head, "/k")[1:])))
        return self.next_pid


def make(lane, *, run=True, github=None, **kwargs):
    host = Host(lane, run=run)
    github = github or FakeGitHub(lane)
    kwargs.setdefault("publisher", lambda: module.REVIEW_PUBLISHER)
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
    _leave_unpublished_outcome(lane)
    assert acts(sweep.tick()) == ["resume-publish"]
    host.rows.clear()
    assert acts(sweep.tick()) == ["needs-reconcile"]


def _leave_unpublished_outcome(lane):
    lane.review_pr(1810)
    row = lane.status(1810)[0]
    path = lane.state_root / "runs" / ReviewTarget(**row["target"]).key / "outcome.json"
    saved = json.loads(path.read_text())
    saved.pop("publication")
    path.write_text(json.dumps(saved))


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


def test_withdrawal_continues_during_rate_limit_backoff(lane):
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
    assert "check-report" in acts(actions, 1810) and "needs-human-confirm" in acts(actions, 1811)
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
    """F5：子进程绑定决策时的 head；head 已变就不审（不登记、不派模型）。"""
    called = []
    monkeypatch.setattr("pilot1742.external_review.main", lambda argv: called.append(argv) or 0)
    class GitHub:
        def pr(self, number):
            return {"head": "b" * 40}
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "a" * 40, "--private-key", "/k"],
                             GitHub()) == 3
    assert called == []
    assert module.run_review(["--pr", "5", "--attempt", "1", "--expect-head", "b" * 40, "--private-key", "/k"],
                             GitHub()) == 0
    assert called == [["review-pr", "--pr", "5", "--attempt", "1", "--private-key", "/k"]]


def test_behind_pr_is_reviewed_without_automatic_branch_update(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    assert acts(sweep.tick()) == ["launch", "check-report"] and len(host.spawned) == 1
    assert github.calls == []


# ---- 合入 ----

def test_no_merge_unless_ci_ok_is_required(lane):
    github = FakeGitHub(lane, required=("deepagents/review",))
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    green(github, lane.gateway.pr["head"]["sha"])
    actions = sweep.tick()
    assert any(a["action"] == "merge-protection-mismatch" for a in actions)
    assert not [c for c in github.calls if c[0] == "merge"]


def test_all_green_cannot_enable_sweep_writes(lane):
    sweep, _, github = make(lane, auto_merge=True)
    green(github, lane.gateway.pr["head"]["sha"])
    report = next(a for a in sweep.tick() if a["action"] == "check-report")
    assert set(report["checks"].values()) == {"success"}
    assert report["scope"] == "diagnostic-only" and github.calls == []


def test_moved_head_is_not_merged(lane):
    github = FakeGitHub(lane)
    github.states[1810] = {"head": "0" * 40}
    green(github, "0" * 40)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    assert acts(sweep.tick()) == ["head-moved"] and github.calls == [("disable", 1810)]


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
    lane.gateway.pr["base"]["sha"] = "e" * 40
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
    assert acts(actions, 1805) == ["error"]   # 状态读不到：失败关闭
    assert ("disable", 1805) in github.calls
    assert "launch" in acts(actions, 1810) and "check-report" in acts(actions, 1810)


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


def test_sweep_carries_no_app_identity_and_uses_shared_repo():
    """F8：sweep 不构造 App 身份（审查身份归 external_review）；仓库名取共享的 workunit.REPO。"""
    from pathlib import Path

    from pilot1742 import workunit
    source = Path(module.__file__).read_text()
    assert "AppIdentity" not in source and "175617978" not in source and "179444545" not in source
    assert module.GhCli().repository == workunit.REPO


@pytest.mark.skipif(not hasattr(_external_review, "_advance_main"), reason="需要 #1913 的补丁沿用与 _advance_main")
def test_main_advance_then_catch_up_costs_no_extra_model_calls(lane, env):
    """组合（独审 test_zz_1939_x_1913）：审过 → main 前进（不重审同 head）→ 操作员追平 → 新 head 按补丁沿用，模型只调用一轮。"""
    github = FakeGitHub(lane)
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    assert "launch" in acts(sweep.tick())
    first = lane.gateway.pr["head"]["sha"]
    green(github, first, **{"ci-ok": "pending"})
    launches = (lane.state_root / "runs" / "launches").read_text()
    _external_review._advance_main(lane, env)            # 模拟操作员追平后 GitHub 报出新 head
    caught_up = lane.gateway.pr["head"]["sha"]
    lane.gateway.pr["head"]["sha"] = first               # update 落地前：PR 仍是旧 head，落后
    github.states[1810] = {"mergeable_state": "behind"}
    actions = sweep.tick()
    assert acts(actions) == ["done", "check-report"] and github.calls == []
    lane.gateway.pr["head"]["sha"] = caught_up
    github.states[1810] = {"mergeable_state": "clean"}
    actions = sweep.tick()
    assert "launch" in acts(actions)
    assert (lane.state_root / "runs" / "launches").read_text() == launches   # 新 head 沿用，不再调用模型
    # 目录名以 base 开头，按名字排序取 [-1] 是随机的；按 head 找追平后的那个 run
    assert next(r for r in lane.status(1810) if r["target"]["head_sha"] == caught_up)["outcome"].get("reused_from")


# ---- 第二轮独审（d0fa06f9）I1/I2 与 Nit ----


BOUND = [{"context": "deepagents/review", "app_id": 5486877}, {"context": "ci-ok", "app_id": 15368}]


@pytest.mark.parametrize(("rules", "trusted"), [
    ({"strict": True, "checks": BOUND}, {"deepagents/review": 5486877, "ci-ok": 15368}),
    ({"strict": False, "checks": BOUND}, {}),
    ({"strict": True, "checks": [BOUND[0], {"context": "ci-ok", "app_id": None}, {"context": "x", "app_id": -1}]},
     {"deepagents/review": 5486877, "ci-ok": None, "x": None}),
])
@pytest.mark.parametrize("enforce_admins", [True, False])
def test_required_checks_preserve_unbound_contexts_under_strict_enforced_protection(monkeypatch, rules, trusted, enforce_admins):
    """I2：strict 关着一个都不算（会拿旧 base 上的结论合入）；enforce_admins 关着也不算（管理员身份可绕过保护）；
    未绑定来源 App 的配置须可见，不得与缺项混淆。"""
    cli = module.GhCli("Newchanlun/NewChanlun")
    protection = {"required_status_checks": rules, "enforce_admins": {"enabled": enforce_admins}}
    calls = []
    monkeypatch.setattr(cli, "_gh", lambda *args: calls.append(args) or json.dumps(protection))
    assert cli.required_checks() == (trusted if enforce_admins else {})
    assert calls == [("api", "repos/Newchanlun/NewChanlun/branches/main/protection")]


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
def test_ci_only_pr_is_not_human_gated(lane, path):
    """只改 CI 或 DevSkim 配置仍不触发人工确认。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    github.files[1810] = [{"filename": path, "status": "modified", "changes": 3}]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = acts(sweep.tick())
    assert "needs-human-confirm" not in actions and "check-report" in actions
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


# ---- 多 PR 夹具 ----

def _more_pulls(lane, github, numbers):
    """同仓的其他 PR，各有自己的 head（f"{号码:040d}"），检查结论互不串。"""
    for number in numbers:
        other = copy.deepcopy(lane.gateway.pr)
        other["number"] = number
        other["head"]["sha"] = f"{number:040d}"
        github.extra_pulls.append(other)


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
    assert all(line.startswith("review-sweep {") for line in lines) and "check-report" in [a["action"] for a in logged]


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
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1].removeprefix("review-sweep "))
    assert line["action"] == "round-skipped" and line["unreadable"] == source
    assert host.spawned == []
    assert github.calls == ([("disable", 1810)] if broken == "rows" else [])
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

    def child(number, attempt, head, log):  # 子进程：review-pr 失败即退出，sweep 只拿到 pid
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


def test_deployed_executor_plist_turns_sweep_and_auto_merge_on():
    """兼容旧部署参数，模板不得为 R29 改写。"""
    import plistlib
    from pathlib import Path
    plist = Path(module.__file__).resolve().parents[2] / "launchd" / "com.newchanlun.deepagents-executor.plist"
    args = plistlib.loads(plist.read_bytes())["ProgramArguments"]
    assert args[args.index("serve"):args.index("serve") + 2] == ["serve", "--loop"]
    assert "--review-sweep" in args and "--review-sweep-auto-merge" in args
    assert args[args.index("--review-sweep-max-running") + 1] == "3"


def test_plist_flags_withdraw_then_dispatch_on_next_clean_round_without_put(lane, monkeypatch, tmp_path, capsys):
    import plistlib
    from pathlib import Path

    from pilot1742 import external_review

    plist = Path(module.__file__).resolve().parents[2] / "launchd" / "com.newchanlun.deepagents-executor.plist"
    arguments = plistlib.loads(plist.read_bytes())["ProgramArguments"]
    flags = [arg for arg in arguments if arg in ("--review-sweep", "--review-sweep-auto-merge")]
    rounds = []
    cli, argv = _fake_serve(monkeypatch, tmp_path, rounds=rounds)
    host = Host(lane, run=False)
    github = FakeGitHub(lane)
    github.states[1810] = {"auto_merge": True}
    green(github, lane.gateway.pr["head"]["sha"])
    wire = []
    api = module.GhCli()
    monkeypatch.setattr(api, "_gh", lambda *args: wire.append(args) or "")
    monkeypatch.setattr(github, "disable_auto_merge", api.disable_auto_merge)
    monkeypatch.setattr(module, "GhCli", lambda: github)
    monkeypatch.setattr(module, "ExternalReview", lambda _: lane)
    monkeypatch.setattr(module, "spawner", lambda key: host.spawn)
    monkeypatch.setattr(module, "STATE_ROOT", lane.state_root)
    monkeypatch.setattr(external_review, "IDENTITY_CONFIG", tmp_path / "absent.json")
    # 保留真实 serve_round 和 Sweep，只隔离宿主进程表及状态目录。
    real_sweep = module.Sweep
    monkeypatch.setattr(module, "Sweep", lambda *args, **kwargs: real_sweep(
        *args, **kwargs, state_root=lane.state_root, rows=lambda: host.rows))
    with pytest.raises(_StopServe):
        cli.main(argv + flags)
    assert lane.gateway.sent == [] and host.spawned == []
    assert "auto-merge-disabled-pre-cutover" in capsys.readouterr().out
    assert wire == [("pr", "merge", "1810", "-R", api.repository, "--disable-auto")]
    github.states[1810] = {"auto_merge": False}
    (lane.state_root / "sweep" / "serve-round.last").unlink()
    with pytest.raises(_StopServe):
        cli.main(argv + flags)
    assert [n for n, _, _ in host.spawned] == [1810]
    assert len(wire) == 1
    assert github.calls == []


def test_legacy_auto_merge_flag_defaults_off(monkeypatch, tmp_path):
    """默认不加只读 CI 诊断；原生撤销不受旧开关控制。"""
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
    github.states[1810]["auto_merge"] = False
    if broken == "pr":
        github.fail[1810] = {"pr"}
    else:
        setattr(github, broken, _raise)
    if broken == "checks":  # 检查在人工确认类判定之后读；读不到时普通 PR 同样失败关闭
        github.files[1810] = [{"filename": "src/x.py", "status": "modified", "changes": 1}]
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    result = next(a for a in sweep.tick() if a.get("pr") == 1810 and a.get("auto_merge_withdrawn"))
    assert result["action"] in ("error", "evidence-insufficient")
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
    assert set(github.calls) == {("disable", n) for n in (1810, 1811, 1812)}


def test_gh_calls_have_a_timeout_and_a_timeout_is_an_unreadable_source(monkeypatch):
    """kimi 高 2：每个 gh 调用带超时；超时转成 SourceUnreadable，写明是哪个接口。"""
    import subprocess
    seen = []
    def run(command, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(module.subprocess, "run", run)
    cli = module.GhCli("Newchanlun/NewChanlun", timeout=7)
    for call in (cli.open_pulls, lambda: cli.pr(5), lambda: cli.checks(5, {"head": HEAD}, BINDINGS, []),
                 cli.required_checks, cli.allow_auto_merge, lambda: cli.pr_files(5),
                 lambda: cli.disable_auto_merge(5)):
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
    assert "check-report" in [a["action"] for a in hook()]


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
    assert [a["pr"] for a in actions if a["action"] == "source-unreadable"] == [1810, 1811]
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
    assert {"pr": 1810, "action": "native-auto-merge-withdrawal", "auto_merge_withdrawn": True}.items() <= next(
        a for a in lines if a.get("pr") == 1810 and a["action"] == "native-auto-merge-withdrawal").items()
    attempted = {1810, 1805} if where in ("required_checks", "checks") else {1810}
    assert set(github.calls) == {("disable", n) for n in attempted}


def test_auto_merge_state_missing_from_pull_list_counts_as_armed(lane):
    github = FakeGitHub(lane)
    del lane.gateway.pr["auto_merge"]
    github.states[1810] = {}
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    github.pr = _hang
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert github.calls == [("disable", 1810)]
    assert caught.value.actions[-1]["action"] == "native-auto-merge-withdrawal"
    assert caught.value.actions[-1]["auto_merge_withdrawn"] is True


def test_withdraw_timeout_stops_the_fail_closed_sweep(lane):
    github = FakeGitHub(lane)
    _armed_sensitive_and_green_neighbour(lane, github)
    lane.gateway.pr["auto_merge"] = None  # 让读取先超时，进入失败关闭撤销分支
    github.required_checks = _hang
    github.disable_auto_merge = _hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    assert [a["action"] for a in caught.value.actions][-2:] == ["fail-closed-withdraw", "fail-closed-aborted"]
    assert caught.value.actions[-2]["auto_merge_withdrawn"] is False


@pytest.mark.parametrize("withdraw_timeout", [False, True])
def test_second_pr_read_timeout_withdraws_even_when_first_read_was_unarmed(lane, monkeypatch, withdraw_timeout):
    sweep, host, github = make(lane, run=False, auto_merge=True)
    lane.gateway.pr["auto_merge"] = None
    original_pr = github.pr
    reads, attempts = [], []

    def pr(number):
        if reads:
            _hang()
        state = original_pr(number)
        assert state["auto_merge"] is False
        reads.append(number)
        return state

    def disable(number):
        attempts.append(number)
        if withdraw_timeout:
            _hang()

    monkeypatch.setattr(github, "pr", pr)
    monkeypatch.setattr(github, "disable_auto_merge", disable)
    with pytest.raises(SourceUnreadable) as caught:
        sweep.tick()
    result = next(a for a in caught.value.actions if a["action"] == "fail-closed-withdraw")
    assert reads == attempts == [1810]
    assert result["auto_merge_withdrawn"] is not withdraw_timeout
    assert host.spawned == [] and github.calls == []


def test_native_auto_merge_is_withdrawn_for_sensitive_pr_even_without_legacy_flag(lane):
    sweep, _, github = make(lane)
    github.files[1810] = [{"filename": ".env"}]
    assert any(a["action"] == "needs-human-confirm" for a in sweep.tick())
    assert github.calls == [("disable", 1810)]


def test_stale_pr_with_native_auto_merge_is_not_reviewed_but_withdrawal_is_logged(lane, capsys):
    sweep, host, github = make(lane)
    lane.gateway.pr.update(updated_at="2026-01-01T00:00:00Z", auto_merge={"merge_method": "merge"})
    module.report(sweep.tick())
    logged = json.loads(capsys.readouterr().out)
    assert logged["action"] == "stale-pr" and logged["auto_merge_withdrawn"] is True
    assert host.spawned == [] and github.calls == [("disable", 1810)]


def test_unconfirmed_native_withdrawal_defers_review_for_that_pr_only(lane, monkeypatch):
    sweep, host, github = make(lane, run=False)
    _same_head_pulls(lane, github, [1811])
    github.states[1810] = {"auto_merge": True}
    monkeypatch.setattr(github, "disable_auto_merge", _raise)
    actions = sweep.tick()
    assert next(a for a in actions if a.get("pr") == 1810)["auto_merge_withdrawn"] is False
    assert launched(actions) == [1811] and [s[0] for s in host.spawned] == [1811]


def test_actions_done_before_a_timeout_are_still_logged(lane, capsys):
    """撤销超时不丢掉先前完成的检查报告。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805])
    green(github, f"{1805:040d}")
    github.files[1810] = [{"filename": "credentials.json"}]
    github.states[1810] = {"auto_merge": True}
    github.disable_auto_merge = _hang
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    assert ServeRound(sweep, clock=Clock())() is None
    lines = [json.loads(line.removeprefix("review-sweep ")) for line in capsys.readouterr().out.splitlines()]
    assert github.calls == []
    assert any(a.get("pr") == 1805 and a["action"] == "check-report" for a in lines)
    assert any(a.get("pr") == 1810 and a.get("auto_merge_withdrawn") is False for a in lines)
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
    assert "复核 head" in result["reason"] and github.calls == [("disable", 1810)]


def test_ghcli_has_only_auto_merge_withdrawal_write():
    sent = []
    cli = module.GhCli("Newchanlun/NewChanlun")
    cli._gh = lambda *args: sent.append(args) or ""
    assert not hasattr(cli, "merge") and not hasattr(cli, "update_branch")
    cli.disable_auto_merge(5)
    assert sent == [("pr", "merge", "5", "-R", cli.repository, "--disable-auto")]


def test_fetch_failure_is_an_unreadable_source_and_never_reviewed(lane, tmp_path):
    """kimi 阻断 2：fetch 失败（私有仓无认证、网络、超时）写明读不到哪个源，不派审、不算通过。"""
    lane.gateway.pr["head"]["sha"] = "e" * 40
    sweep, host, _ = make(lane, run=False, sync=module.fetcher(lane.source, str(tmp_path / "no-such-repo.git")))
    result = next(a for a in sweep.tick() if a.get("pr") == 1810)
    assert result["action"] == "source-unreadable" and result["unreadable"].endswith("pull/1810/head")
    assert "CalledProcessError" in result["reason"] and host.spawned == []
    assert ("disable", 1810) in sweep.github.calls


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

@pytest.mark.parametrize("setting", ["enabled", "unreadable", "unknown", "timeout"])
@pytest.mark.parametrize("legacy_flag", [False, True])
def test_native_auto_merge_setting_blocks_all_review_work_after_prioritized_withdrawal(
    lane, setting, legacy_flag
):
    _leave_unpublished_outcome(lane)
    github = FakeGitHub(lane)
    _same_head_pulls(lane, github, [1805, 1806, 1811])
    github._pr(1811)["auto_merge"] = {}
    del github._pr(1806)["auto_merge"]
    github._pr(1806)["base"]["ref"] = "another-base"
    github.allow_auto_merge = {"enabled": lambda: True, "unreadable": _raise,
                              "unknown": lambda: None, "timeout": _hang}[setting]
    def unexpected(*args):
        pytest.fail("设置未确认关闭时不得诊断、排序或派审")
    github.required_checks = github.pr = github.committed_at = unexpected
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=legacy_flag)
    sweep.spawn = unexpected
    if setting == "timeout":
        with pytest.raises(SourceUnreadable) as caught:
            sweep.tick()
        actions = caught.value.actions
        assert github.calls == [("disable", n) for n in (1811, 1806, 1805, 1810)]
    else:
        actions = sweep.tick()
        assert github.calls == [("disable", 1811), ("disable", 1806)]
    assert any(a["action"] == "native-auto-merge-enabled" and a["reason"] for a in actions)
    assert not {"launch", "resume-review", "resume-publish"} & {a["action"] for a in actions}
    assert host.spawned == [] and not list(sweep.folder.glob("*.resumes"))


@pytest.mark.parametrize("source", ["list", "detail", "unknown-list", "unknown-detail"])
def test_native_auto_merge_residue_is_withdrawn_before_other_launch_and_its_publication_waits(lane, source):
    _leave_unpublished_outcome(lane)
    sweep, host, github = make(lane, run=False)
    _same_head_pulls(lane, github, [1805])  # 排在 1810 前，有足够名额且本可派审
    if source == "list":
        lane.gateway.pr["auto_merge"] = {}
    elif source == "unknown-list":
        del lane.gateway.pr["auto_merge"]
    else:
        github.states[1810] = {"auto_merge": True if source == "detail" else None}
    def spawn(number, *args):
        github.calls.append(("spawn", number))
        return host.spawn(number, *args)
    sweep.spawn = spawn
    assert launched(sweep.tick()) == [1805]
    assert github.calls == [("disable", 1810), ("spawn", 1805)]
    assert not list(sweep.folder.glob("*.resumes"))
    lane.gateway.pr["auto_merge"] = None
    github.states[1810] = {"auto_merge": False}
    assert "resume-publish" in acts(sweep.tick())


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
    assert github.calls == [("disable", 1810)]                     # 超时：整轮作废，失败关闭照撤
    assert caught.value.actions[-1]["action"] == "fail-closed-withdraw"


# ---- 第六轮（1354bc7c，run cfbc868b）：检查结论绑定来源 App；serve 的审查私钥单独给 ----

HEAD, BASE = "a" * 40, "b" * 40
BINDINGS = {"deepagents/review": 5664795, "ci-ok": 15368, "DevSkim": 15368}
REPOSITORY = "Newchanlun/NewChanlun"
REVIEW_BOT = "newchanlun-review-gate[bot]"
RUN_UUID = "83f12ba9-f3c5-49ec-845e-da074743c13e"
STAMP = "2026-11-28T13:03:48Z"
CHECK_STATE = {"head": HEAD, "base": BASE, "head_ref": "decision/feature",
               "repository_id": 1150335160, "pr_id": 5426953656, "created_at": "2026-11-28T13:00:00Z"}


def _pull_original(state, number=1810):
    return {"number": number, "id": state["pr_id"], "state": state.get("state", "open"), "created_at": state["created_at"],
            "draft": state.get("draft", False), "mergeable_state": state.get("mergeable_state", "clean"),
            "changed_files": state.get("changed_files", 1), "auto_merge": {} if state.get("auto_merge") else None,
            "base": {"ref": state.get("base_ref", "main"), "sha": state["base"], "repo": {"id": state["repository_id"]}},
            "head": {"ref": state["head_ref"], "sha": state["head"], "repo": {"id": state["repository_id"]}}}


def _gh_fake(statuses, checks, *, apps=None, puts=None, state=CHECK_STATE, overrides=None):
    apps = apps if apps is not None else {"newchanlun-review-gate": 5664795}
    overrides = {} if overrides is None else overrides

    def gh(*args):
        path = next(a for a in args if a.startswith(("repos/", "apps/")))
        if path.startswith("apps/"):
            return json.dumps({"id": apps.get(path.removeprefix("apps/"), -1)})
        if "-X" in args and "PUT" in args:
            assert puts is not None
            puts.append(args)
            return "{}"
        if path.endswith("/pulls/1810"):
            return json.dumps(_pull_original(state))
        if "/statuses?" in path:
            return "\n".join(json.dumps(x) for x in statuses)
        verb = path.partition("?")[0]
        if verb in overrides:
            assert "--paginate" in args and "--slurp" in args
            return json.dumps(overrides[verb])
        if "/pulls?" in path:
            assert "--paginate" in args and "--slurp" in args and "state=all" in path and "%2F" in path
            return json.dumps([[_pull_original(state)]])
        if "/events?" in path:
            assert "--paginate" in args and "--slurp" in args
            return "[[]]"
        if "/actions/workflows/" in path:
            assert "--paginate" in args and "--slurp" in args and f"head_sha={state['head']}" in path
            workflow = path.split("/workflows/")[1].partition("/")[0]
            runs = [run for _, run, _ in checks if (run.get("path") or "").endswith(f"/{workflow}")]
            # 每页只放一个 run，防止读取器只看第一页。
            return json.dumps([{"workflow_runs": [run], "total_count": len(runs)} for run in runs]
                              or [{"workflow_runs": [], "total_count": 0}])
        if "/actions/runs/" in path:
            suffix = path.split("/actions/runs/")[1].partition("?")[0]
            run_id, _, rest = suffix.partition("/")
            if rest:
                assert "--paginate" in args and "--slurp" in args
                jobs = [job for _, run, job in checks if str(run["id"]) == run_id]
                return json.dumps([{"jobs": jobs, "total_count": len(jobs)}])
            return json.dumps(next(run for _, run, _ in checks if str(run["id"]) == run_id))
        if "/check-runs/" in path:
            return json.dumps(next(check for check, _, _ in checks if str(check["id"]) == path.rsplit("/", 1)[1]))
        pytest.fail(f"未预期的 gh 请求：{args}")

    return gh


def _review_record(state=CHECK_STATE, number=1810):
    description = f"run={RUN_UUID} b={state['base'][:12]} h={state['head'][:12]} success"
    target = {"run_id": RUN_UUID, "repository_id": state["repository_id"], "pr_number": number,
              "base_sha": state["base"], "head_sha": state["head"]}
    status = {"id": 60106514448, "context": "deepagents/review", "state": "success",
              "description": description, "creator": {"login": REVIEW_BOT, "type": "Bot"},
              "created_at": "2026-11-28T13:03:35Z", "updated_at": "2026-11-28T13:03:38Z"}
    publication = {"id": status["id"], "sha": state["head"], "state": status["state"], "description": description}
    outcome = {"run_id": RUN_UUID, "target": dict(target), "verdict": "PASS", "publication": publication}
    return status, {"target": target, "outcome": outcome}


def _wire_status(monkeypatch, github, cli):
    monkeypatch.setattr(github, "review_status", lambda n, state, runs, publisher: cli.review_status(
        n, {**CHECK_STATE, **state}, runs, publisher))


def _run(name, state=CHECK_STATE, *, check_id=140984998172, conclusion="success", app_id=15368,
         path=None, event="pull_request", number=1810, pr_id=None, run_id=None, attempt=1,
         status="completed", created_at=STAMP):
    run_id = run_id if run_id is not None else check_id + 1000
    head = state["head"]
    check = {"name": name, "status": status, "conclusion": conclusion, "app": {"id": app_id},
             "id": check_id, "head_sha": head, "check_suite": {"id": run_id + 1000}, "completed_at": STAMP}
    pull = _pull_original(state, number)
    if pr_id is not None:
        pull["id"] = pr_id
    run = {"id": run_id, "run_attempt": attempt, "event": event, "path": path or module.WORKFLOWS.get(name),
           "repository": {"id": state["repository_id"]}, "head_repository": pull["head"]["repo"],
           "head_branch": state["head_ref"], "head_sha": head, "check_suite_id": run_id + 1000,
           "workflow_id": 236472671 if name == "ci-ok" else 242058253, "created_at": created_at,
           "status": status, "conclusion": conclusion, "pull_requests": [pull]}
    job = {"id": check_id, "name": name, "head_sha": head, "run_attempt": attempt, "run_id": run_id,
           "status": status, "conclusion": conclusion, "completed_at": STAMP,
           "check_run_url": f"https://api.github.com/repos/{REPOSITORY}/check-runs/{check_id}"}
    return check, run, job


def test_spoofed_same_name_checks_from_other_apps_do_not_count(monkeypatch):
    cli = module.GhCli(REPOSITORY)
    status, record = _review_record()
    spoof = {**status, "context": "DeepAgents/Review", "id": status["id"] + 1,
             "creator": {"login": "someone-else[bot]", "type": "Bot"}}
    checks = [_run("ci-ok", check_id=3)]
    monkeypatch.setattr(cli, "_gh", _gh_fake([status, spoof], checks))
    assert cli.checks(1810, CHECK_STATE, BINDINGS, [record]) == {"deepagents/review": "superseded"}


def test_genuine_checks_from_bound_apps_count_even_with_unrelated_same_name_runs(monkeypatch):
    cli = module.GhCli(REPOSITORY)
    status, record = _review_record()
    checks = [_run("DevSkim", check_id=1), _run("ci-ok", check_id=2),
              _run("ci-ok", check_id=3, event="workflow_dispatch"),
              _run("DevSkim", check_id=4, path=".github/workflows/other.yml"),
              _run("ci-ok", check_id=5, number=1811, pr_id=99)]
    monkeypatch.setattr(cli, "_gh", _gh_fake([status], checks))
    assert cli.checks(1810, CHECK_STATE, BINDINGS, [record]) == {name: "success" for name in BINDINGS}


@pytest.mark.parametrize("foreign_field", ["head_branch", "head_repository", None])
def test_empty_pr_association_only_blocks_runs_that_could_belong_to_this_pr(monkeypatch, foreign_field):
    cli = module.GhCli(REPOSITORY)
    status, record = _review_record()
    old = _run("ci-ok", check_id=90)
    old[1]["pull_requests"] = []  # 已关闭 PR 的关联可为空；当前仍有一条有效 run。
    if foreign_field:
        old[1][foreign_field] = "other-branch" if foreign_field == "head_branch" else {"id": 99}
    checks = [_run("ci-ok", check_id=1), _run("DevSkim", check_id=2), old]
    monkeypatch.setattr(cli, "_gh", _gh_fake([status], checks))
    if foreign_field:
        assert cli.checks(1810, CHECK_STATE, BINDINGS, [record]) == {name: "success" for name in BINDINGS}
    else:
        with pytest.raises(module.EvidenceInsufficient, match="缺服务端 PR 关联"):
            cli.checks(1810, CHECK_STATE, BINDINGS, [record])


def test_diagnostic_rejects_run_created_before_current_pr(transition):
    sweep, state, _, _, checks, puts = transition
    checks[0][1]["created_at"] = "2026-11-28T12:59:59Z"
    result = next(a for a in sweep.tick() if a["action"] == "evidence-insufficient")
    assert "早于当前 PR" in result["reason"] and puts == []


@pytest.mark.parametrize("apps,bound", [({"newchanlun-review-gate": 1}, 5664795), ({}, 424242)])
def test_status_from_unknown_or_mismatched_app_slug_fails_closed(monkeypatch, apps, bound):
    cli = module.GhCli(REPOSITORY)
    status, record = _review_record()
    monkeypatch.setattr(cli, "_gh", _gh_fake([status], [], apps=apps))
    actual = cli.checks(1810, CHECK_STATE, {**BINDINGS, "deepagents/review": bound}, [record])
    assert actual.get("deepagents/review") != "success"


@pytest.fixture
def transition(lane, monkeypatch):
    """真实 sweep 与 GhCli 检查；HTTP、PR 队列及宿主原件用离线夹具。"""
    sweep, _, github = make(lane, run=False, auto_merge=True)
    cli = module.GhCli(REPOSITORY)
    state = {**CHECK_STATE, **github.pr(1810), "head_ref": lane.gateway.pr["head"]["ref"]}
    status, record = _review_record(state)
    checks = [_run("ci-ok", state, check_id=1), _run("DevSkim", state, check_id=2)]
    puts = []
    records = [record]
    monkeypatch.setattr(github, "pr", cli.pr)
    monkeypatch.setattr(github, "checks", cli.checks)
    monkeypatch.setattr(lane, "status", lambda number: records)
    monkeypatch.setattr(cli, "_gh", _gh_fake([status], checks, puts=puts, state=state))
    return sweep, state, status, records, checks, puts


@pytest.mark.parametrize("name", ["ci-ok", "DevSkim"])
@pytest.mark.parametrize("conclusion", ["neutral", "skipped"])
def test_transition_never_merges_non_success_actions_conclusions(transition, name, conclusion):
    sweep, state, _, _, checks, puts = transition
    checks.append(_run(name, state, check_id=5, conclusion=conclusion))
    report = next(a for a in sweep.tick() if a["action"] == "check-report")
    assert report["checks"][name] == "failure" and puts == []


@pytest.mark.parametrize("defect", ["wrong-pr", "wrong-full-base-same-prefix", "wrong-base-prefix",
                                   "wrong-head", "wrong-publication-id", "missing-original"])
def test_transition_requires_the_exact_review_original(transition, defect):
    sweep, state, status, records, _, puts = transition
    record = records[0]
    if defect == "missing-original":
        records.clear()
    elif defect == "wrong-publication-id":
        record["outcome"]["publication"]["id"] += 1
    elif defect == "wrong-base-prefix":
        status["description"] = status["description"].replace(state["base"][:12], "f" * 12)
    else:
        key, value = {
            "wrong-pr": ("pr_number", 1811),
            "wrong-full-base-same-prefix": ("base_sha", state["base"][:12] + ("a" if state["base"][12] != "a" else "f")
                                           + state["base"][13:]),
            "wrong-head": ("head_sha", "f" * 40),
        }[defect]
        record["target"][key] = record["outcome"]["target"][key] = value
    actions = sweep.tick()
    report = actions[-1]
    if defect in ("wrong-base-prefix", "wrong-publication-id"):
        assert report["action"] == "needs-reconcile"
    else:
        assert report["action"] == "check-report" and report["checks"]["deepagents/review"] != "success"
    assert puts == []


@pytest.mark.parametrize("defect", ["workflow_dispatch", "workflow", "pr", "head", "attempt", "unproven-pr", "ambiguous-pr"])
def test_transition_requires_actions_provenance(transition, defect):
    sweep, _, _, _, checks, puts = transition
    check, run, job = checks[0]
    if defect == "workflow_dispatch":
        run["event"] = defect
    elif defect == "workflow":
        run["path"] = ".github/workflows/other.yml"
    elif defect == "pr":
        run["pull_requests"] = [{**run["pull_requests"][0], "id": 99, "number": 1811}]
    elif defect == "head":
        check["head_sha"] = "f" * 40
    elif defect == "attempt":
        run["run_attempt"] = job["run_attempt"] + 1
    elif defect == "unproven-pr":
        run["pull_requests"] = []
    elif defect == "ambiguous-pr":
        run["pull_requests"].append({**run["pull_requests"][0], "id": 99, "number": 1811})
    assert "merged" not in acts(sweep.tick()) and puts == []


@pytest.mark.parametrize("newer_status,expected", [("completed", "failure"), ("in_progress", "pending")])
def test_latest_workflow_run_wins_over_larger_check_id_from_old_rerun(transition, newer_status, expected):
    sweep, state, _, _, checks, puts = transition
    checks[0] = _run("ci-ok", state, check_id=100, run_id=4, attempt=2, created_at="2026-11-28T13:03:40Z")
    checks.append(_run("ci-ok", state, check_id=50, run_id=5, status=newer_status, conclusion="failure"))
    result = next(a for a in sweep.tick() if a["action"] == "check-report")
    assert result["checks"]["ci-ok"] == expected and puts == []


def test_older_in_progress_applicable_run_also_blocks_latest_green(transition):
    sweep, state, _, _, checks, puts = transition
    checks.append(_run("ci-ok", state, check_id=50, run_id=5, status="queued", conclusion=None,
                       created_at="2026-11-28T13:03:40Z"))
    result = next(a for a in sweep.tick() if a["action"] == "check-report")
    assert result["checks"]["ci-ok"] == "pending" and puts == []


@pytest.mark.parametrize("event", sorted(module.BASE_CHANGE_EVENTS))
@pytest.mark.parametrize("retargeted_pr", [1810, 1811])
def test_target_change_on_any_pr_of_same_ref_refuses_actions_evidence(transition, monkeypatch, event, retargeted_pr):
    sweep, state, status, _, checks, puts = transition
    closed = _pull_original({**state, "pr_id": 999, "state": "closed"}, number=1811)
    prefix = f"repos/{REPOSITORY}"
    overrides = {f"{prefix}/pulls": [[_pull_original(state)], [closed]],
                 f"{prefix}/issues/{retargeted_pr}/events": [[{"id": 2, "event": "closed"}], [{"id": 1, "event": event}]]}
    monkeypatch.setattr(sweep.github.checks.__self__, "_gh", _gh_fake(
        [status], checks, state=state, puts=puts, overrides=overrides))
    result = next(a for a in sweep.tick() if a["action"] == "evidence-insufficient")
    assert f"#{retargeted_pr} 有改投" in result["reason"] and puts == []


def test_same_ref_closed_pr_targeting_other_base_refuses_actions_evidence(transition, monkeypatch):
    sweep, state, status, _, checks, puts = transition
    other = _pull_original({**state, "pr_id": 999, "state": "closed", "base_ref": "other"}, number=1811)
    monkeypatch.setattr(sweep.github.checks.__self__, "_gh", _gh_fake(
        [status], checks, state=state, puts=puts,
        overrides={f"repos/{REPOSITORY}/pulls": [[_pull_original(state)], [other]]}))
    result = next(a for a in sweep.tick() if a["action"] == "evidence-insufficient")
    assert "#1811 未始终指向本仓 main" in result["reason"] and puts == []


@pytest.mark.parametrize("kind", ["run-count", "event-page", "jobs-count"])
def test_incomplete_github_inventory_fails_closed(transition, monkeypatch, kind):
    sweep, state, status, _, checks, puts = transition
    check, run, job = checks[0]
    prefix = f"repos/{REPOSITORY}"
    overrides = {
        "run-count": {f"{prefix}/actions/workflows/ci.yml/runs": [{"total_count": 2, "workflow_runs": [run]}]},
        "event-page": {f"{prefix}/issues/1810/events": [[{"id": 7, "event": "closed"}], None]},
        "jobs-count": {f"{prefix}/actions/runs/{run['id']}/attempts/1/jobs": [{"total_count": 2, "jobs": [job]}]},
    }
    monkeypatch.setattr(sweep.github.checks.__self__, "_gh", _gh_fake(
        [status], checks, state=state, puts=puts, overrides=overrides[kind]))
    assert acts(sweep.tick())[-1] == "evidence-insufficient" and puts == []


@pytest.mark.parametrize("binding", [None, -1, 999, "missing"])
def test_devskim_must_be_configured_and_bound_in_real_protection_response(transition, monkeypatch, binding):
    sweep, _, _, _, _, puts = transition
    cli = sweep.github.checks.__self__
    checks = [{"context": name, "app_id": app} for name, app in BINDINGS.items() if name != "DevSkim"]
    if binding != "missing":
        checks.append({"context": "DevSkim", "app_id": binding})
    gh = cli._gh
    protection = {"required_status_checks": {"strict": True, "checks": checks}, "enforce_admins": {"enabled": True}}
    monkeypatch.setattr(cli, "_gh", lambda *args: json.dumps(protection) if args[-1].endswith("/main/protection")
                        else gh(*args))
    monkeypatch.setattr(sweep.github, "required_checks", cli.required_checks)
    assert ("DevSkim" in cli.required_checks()) == (binding != "missing")
    assert any(a["action"] == "merge-protection-mismatch" for a in sweep.tick()) and puts == []


def test_closed_pr_shared_head_supersedes_publication_and_frees_queue(lane, monkeypatch):
    lane.review_pr(1810)
    other = {**lane.gateway.pr, "number": 1811}
    get_pr = lane.gateway.get_pr
    monkeypatch.setattr(lane.gateway, "get_pr", lambda n: copy.deepcopy(other) if n == 1811 else get_pr(n))
    lane.review_pr(1811)
    other["state"] = "closed"
    sweep, host, github = make(lane, run=False, auto_merge=True)
    _same_head_pulls(lane, github, [1812])
    github.states[1812] = {"mergeable_state": "behind"}
    cli = module.GhCli(REPOSITORY)
    statuses = [{**row, "creator": {"login": REVIEW_BOT, "type": "Bot"},
                 "created_at": STAMP, "updated_at": STAMP} for row in lane.gateway.rows]
    monkeypatch.setattr(cli, "_gh", _gh_fake(statuses, []))
    _wire_status(monkeypatch, github, cli)
    actions = sweep.tick()
    blocked = next(a for a in actions if a.get("pr") == 1810 and a["action"] == "needs-reconcile")
    assert blocked["review"] == "superseded" and blocked["queue_head"] is False
    assert launched(actions) == [1812] and [s[0] for s in host.spawned] == [1812]
    assert github.calls == [("disable", 1810)]
    pending = {**statuses[0], "state": "pending", "id": statuses[0]["id"] + 1,
               "description": statuses[0]["description"].replace("success", "pending")}
    state = {**CHECK_STATE, **github.pr(1810)}
    assert cli._review_check(1810, state, statuses + [pending], lane.status(1810)) == "superseded"
    lane.review_pr(1810, 2)  # 操作员为本 PR/base/head 重新正式审查；不重用 PR B 的发布。
    current = {**lane.gateway.rows[0], "creator": {"login": REVIEW_BOT, "type": "Bot"},
               "created_at": STAMP, "updated_at": STAMP}
    assert cli._review_check(1810, state, statuses + [current], lane.status(1810)) == "success"


@pytest.mark.parametrize("creator", [
    {"login": "newchanlun-deepagents-1742[bot]", "type": "Bot"},
    {"login": "someone-else", "type": "User"},
])
@pytest.mark.parametrize("legacy_flag", [False, True])
def test_nonofficial_same_name_overwrite_needs_reconcile_and_does_not_block_next_review(
    lane, monkeypatch, creator, legacy_flag
):
    lane.review_pr(1810)
    sweep, host, github = make(lane, run=False, auto_merge=legacy_flag, max_running=1)
    _same_head_pulls(lane, github, [1811])
    real = [{**row, "creator": {"login": REVIEW_BOT, "type": "Bot"}, "created_at": STAMP, "updated_at": STAMP}
            for row in lane.gateway.rows]
    latest = {**real[0], "id": max(row["id"] for row in real) + 1, "creator": creator, "context": "DeepAgents/Review"}
    cli = module.GhCli(REPOSITORY)
    puts = []
    monkeypatch.setattr(cli, "_gh", _gh_fake(real + [latest], [], puts=puts))
    _wire_status(monkeypatch, github, cli)
    actions = sweep.tick()
    assert acts(actions, 1810) == ["needs-reconcile"]
    assert next(a for a in actions if a.get("pr") == 1810)["queue_head"] is False
    assert launched(actions) == [1811] and [s[0] for s in host.spawned] == [1811]
    assert not puts and all(call[0] == "disable" for call in github.calls)


@pytest.mark.parametrize("overwrite", [None, "other-pr", "other-app"])
def test_fallback_publication_is_reconciled_but_never_a_merge_gate(lane, monkeypatch, tmp_path, overwrite):
    monkeypatch.setattr(module.external_review, "IDENTITY_CONFIG", tmp_path / "absent.json")
    lane.review_pr(1810)  # 真实 lane：夹具的发布者本来就是执行器 App
    sweep, host, github = make(lane, run=False, auto_merge=True, publisher=module.configured_publisher)
    original = [{**row, "created_at": STAMP, "updated_at": STAMP} for row in lane.gateway.rows]
    if overwrite:
        latest = {**original[0], "id": original[0]["id"] + 1}
        if overwrite == "other-pr":  # 同一个执行器 App、相同 head，但另一 PR 的 run
            latest["description"] = f"run={RUN_UUID} " + latest["description"].split(" ", 1)[1]
        else:
            latest["creator"] = {"login": REVIEW_BOT, "type": "Bot"}
        original.append(latest)
    cli = module.GhCli(REPOSITORY)
    monkeypatch.setattr(cli, "_gh", _gh_fake(original, [], apps={"newchanlun-deepagents-1742": 5486877}))
    _wire_status(monkeypatch, github, cli)
    green(github, lane.gateway.pr["head"]["sha"])
    actions = sweep.tick()
    assert any(a["action"] == "merge-protection-mismatch" for a in actions)
    assert host.spawned == []
    if overwrite:
        assert acts(actions) == ["needs-reconcile"] and github.calls == [("disable", 1810)]
    else:
        assert acts(actions) == ["done", "check-report"] and github.calls == []
        assert next(a for a in actions if a["action"] == "check-report")["checks"]["deepagents/review"] is None


@pytest.mark.parametrize("file_error", [_raise, _hang])
def test_overwritten_publication_still_needs_reconciliation_when_file_inventory_fails(lane, monkeypatch, file_error):
    lane.review_pr(1810)
    sweep, host, github = make(lane, run=False)
    originals = [{**row, "creator": {"login": REVIEW_BOT, "type": "Bot"},
                  "created_at": STAMP, "updated_at": STAMP} for row in lane.gateway.rows]
    overwritten = {**originals[0], "id": originals[0]["id"] + 1, "creator": {"login": "other[bot]", "type": "Bot"}}
    cli = module.GhCli(REPOSITORY)
    monkeypatch.setattr(cli, "_gh", _gh_fake([*originals, overwritten], []))
    _wire_status(monkeypatch, github, cli)
    github.pr_files = file_error
    if file_error is _hang:
        with pytest.raises(SourceUnreadable) as caught:
            sweep.tick()
        actions = caught.value.actions
    else:
        actions = sweep.tick()
    assert "done" not in acts(actions)
    report = next(a for a in actions if a["action"] == "needs-reconcile")
    assert report["review"] == "superseded" and report["file_evidence_error"]
    assert host.spawned == [] and github.calls == [("disable", 1810)]


@pytest.mark.parametrize("missing", ["enforce_admins", "strict", "binding"])
def test_protection_mismatch_never_merges(lane, missing):
    """分支保护任一不符（enforce_admins 关、strict 关、必需检查没绑定 app）：失败关闭，不合入、不追平。"""
    github = FakeGitHub(lane, required=() if missing != "binding" else ("deepagents/review",))
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert any(a["action"] == "merge-protection-mismatch" for a in actions) and github.calls == []


# ---- #2015 opus 阻断（247f128b，run 6ac0b428）：必需检查绑定执行器 App 时不合入 ----

@pytest.mark.parametrize("bound, configured", [(5486877, 5486877), (5486877, None), (5664795, None), (5664795, 4242)])
def test_review_binding_not_the_configured_reviewer_app_never_merges(lane, bound, configured):
    """执行器交付时用执行器 App 自写 deepagents/review=success。必需检查绑定执行器 App（缺省身份）时，
    draft 一标 ready，同一轮里 sweep 刚派出正式审查、FakeGitHub 已报三项全绿，也不得合入；
    绑定与审查身份文件配的 App 不符、或身份文件缺失时同样不合入。"""
    github = FakeGitHub(lane, review_app=bound)
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, host, _ = make(lane, run=False, github=github, auto_merge=True,
                         publisher=lambda: (configured, REVIEW_BOT.removesuffix("[bot]")) if configured else None)
    actions = sweep.tick()
    assert acts(actions) == ["launch", "check-report"] and len(host.spawned) == 1   # 本轮刚派出正式审查
    assert [a for a in actions if a["action"] == "merge-protection-mismatch"]
    assert next(a for a in actions if a["action"] == "check-report")["checks"]["deepagents/review"] is None
    assert github.calls == []


def test_executor_app_status_alone_does_not_satisfy_reviewer_binding(monkeypatch):
    """绑定审查 App 5664795 时，执行器 App 发的 deepagents/review=success 不算（合入看的检查只认绑定来源）。"""
    cli = module.GhCli(REPOSITORY)
    status, record = _review_record()
    status["creator"]["login"] = "newchanlun-deepagents-1742[bot]"
    checks = [_run("DevSkim", check_id=1), _run("ci-ok", check_id=2)]
    monkeypatch.setattr(cli, "_gh", _gh_fake([status], checks))
    assert cli.checks(1810, CHECK_STATE, BINDINGS, [record]) == {"deepagents/review": "superseded"}


def test_configured_publisher_reads_identity_file(tmp_path):
    config = tmp_path / "app-identity.json"
    assert module.configured_publisher(config) == (5486877, "newchanlun-deepagents-1742")
    config.write_text(json.dumps({"app_id": 5664795, "installation_id": 1, "app_slug": "x",
                                  "installation_permissions": {"statuses": "write"}}))
    assert module.configured_publisher(config) == (5664795, "x")
    config.write_text("not json")
    assert module.configured_publisher(config) is None


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
    error.actions = [{"pr": 1805, "action": "check-report"}]
    class Boom(Sweep):
        def __init__(self, *args, **kwargs):
            pass
        def tick(self):
            raise error
    monkeypatch.setattr(module, "Sweep", Boom)
    assert module.main(["--private-key", "/k"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [a["action"] for a in lines] == ["check-report", "round-skipped"]
