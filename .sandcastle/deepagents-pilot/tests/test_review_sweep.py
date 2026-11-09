import copy
import json
import os
from datetime import datetime, timezone

import pytest
import test_external_review as _external_review
from conftest import git

from pilot1742 import review_sweep as module
from pilot1742.external_review import ReviewTarget
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
    def __init__(self, lane, *, required=("deepagents/review", "ci-ok")):
        self.lane = lane
        self.required = {name: {"deepagents/review": 5486877, "ci-ok": 15368}[name] for name in required}
        self.extra_pulls = []
        self.states, self.checks_by_head, self.files, self.calls, self.fail = {}, {}, {}, [], {}

    def open_pulls(self):
        return copy.deepcopy([self.lane.gateway.pr, *self.extra_pulls])

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


def test_behind_head_is_caught_up_before_review(lane):
    """F4：启用合入时，落后的 PR 先追平、再审新 head，不审一个合入前必然被替换的 head。"""
    github = FakeGitHub(lane)
    github.states[1810] = {"mergeable_state": "behind"}
    sweep, host, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert acts(actions) == ["behind-awaiting-update", "update-branch"] and host.spawned == []
    assert github.calls == [("update", 1810, lane.gateway.pr["head"]["sha"])]


# ---- 合入 ----

def test_no_merge_unless_ci_ok_is_required(lane):
    github = FakeGitHub(lane, required=("deepagents/review",))
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    green(github, lane.gateway.pr["head"]["sha"])
    actions = sweep.tick()
    assert any(a["action"] == "auto-merge-unsafe" for a in actions)
    assert not [c for c in github.calls if c[0] == "merge"]


def test_merges_only_exact_head_with_review_ci_ok_and_devskim_green(lane):
    """F1：不预挂 auto-merge；精确 head 三项全绿、清单可判定且非人工确认类时，带 sha 直接合入。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    green(github, head, DevSkim="pending")
    assert "waiting" in acts(sweep.tick())
    assert github.calls == []
    green(github, head)
    assert "merged" in acts(sweep.tick())
    assert github.calls == [("merge", 1810, head)]


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
    assert "merged" in acts(actions, 1810)


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
    assert acts(actions) == ["done", "update-branch"]    # 不重审旧 head；先追平
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
    """I1：GitHub 上停住的 pending 不再挡追平；本地没有在途审查就追平，追平后的新 head 由下一轮重审。"""
    github = FakeGitHub(lane)
    sweep, host, head = _stale_mid_flight(lane, github, auto_merge=True)
    assert acts(sweep.tick()) == ["behind-awaiting-update", "update-branch"]
    assert github.calls == [("update", 1810, head)] and len(host.spawned) == 1


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
    """I2：strict 关着一个都不算（会拿旧 base 上的结论合入）；enforce_admins 关着也不算（管理员身份可绕过保护）；
    没绑定来源 app 的检查谁都能伪造，不算。"""
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
def test_ci_only_pr_auto_merges(lane, path):
    """负控（在 #1939 的 main 上失败：那里这些路径报 needs-human-confirm）：只改 CI 或 DevSkim 配置的 PR，
    精确 head 双门全绿时和普通代码一样带 sha 合入，不撤 auto-merge，不交人工确认。"""
    github = FakeGitHub(lane)
    head = lane.gateway.pr["head"]["sha"]
    github.files[1810] = [{"filename": path, "status": "modified", "changes": 3}]
    green(github, head)
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = acts(sweep.tick())
    assert "needs-human-confirm" not in actions and "merged" in actions
    assert github.calls == [("merge", 1810, head)]
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
    """三个落后的 PR：只追平号码最小的那个；队首追平后在等 CI（不落后）时，后面的仍不追平。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811, 1812])
    head = lane.gateway.pr["head"]["sha"]
    for number in (1810, 1811, 1812):
        github.states[number] = {"mergeable_state": "behind"}
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert updates(github) == [("update", 1810, head)]
    assert acts(actions, 1811)[-1] == "behind-waiting" and acts(actions, 1812)[-1] == "behind-waiting"
    github.calls.clear()
    github.states[1810] = {"mergeable_state": "blocked"}  # 队首已追平，CI 在跑
    actions = sweep.tick()
    assert updates(github) == []
    assert next(a for a in actions if a.get("pr") == 1810 and a["action"] == "waiting")["queue_head"] is True


@pytest.mark.parametrize("stuck", ["review-failure", "dirty", "ci-failure", "needs-operator"])
def test_stuck_pr_does_not_hold_the_queue_head(lane, stuck):
    """队首卡住（独审已判失败、冲突、不落后却 CI 失败、审查要操作员处理）时，下一个落后的 PR 接替队首被追平。"""
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
    sweep.tick()
    assert updates(github) == [("update", 1811, f"{1811:040d}")]


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
    assert all(line.startswith("review-sweep {") for line in lines) and "merged" in [a["action"] for a in logged]


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
    """#1915 合入后 main 的合入不设人工批准，部署模板同时开审查与自动合入；
    代码默认仍关，见 test_auto_merge_is_off_unless_explicitly_enabled。"""
    import plistlib
    from pathlib import Path
    plist = Path(module.__file__).resolve().parents[2] / "launchd" / "com.newchanlun.deepagents-executor.plist"
    args = plistlib.loads(plist.read_bytes())["ProgramArguments"]
    assert args[args.index("serve"):args.index("serve") + 2] == ["serve", "--loop"]
    assert "--review-sweep" in args and "--review-sweep-auto-merge" in args
    assert args[args.index("--review-sweep-max-running") + 1] == "3"


def test_auto_merge_is_off_unless_explicitly_enabled(monkeypatch, tmp_path):
    """代码里默认关：只给 --review-sweep 时 sweep 只派审不合入；合入要显式加 --review-sweep-auto-merge（部署模板已加）。"""
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
    for call in (cli.open_pulls, lambda: cli.pr(5), lambda: cli.checks("a" * 40, BINDINGS), cli.required_checks,
                 lambda: cli.pr_files(5), lambda: cli.merge(5, "a" * 40), lambda: cli.update_branch(5, "a" * 40),
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
    assert "merged" in [a["action"] for a in hook()]


def test_green_but_unmergeable_pr_does_not_hold_the_queue_head(lane):
    """opus 低：不落后、三项全绿却停在 blocked（main 另有未满足的规则）的 PR 不占队首，下一个落后的照常追平。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1811])
    github.states[1810] = {"mergeable_state": "blocked"}
    github.states[1811] = {"mergeable_state": "behind"}
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    assert updates(github) == [("update", 1811, f"{1811:040d}")]
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
    assert {"pr": 1810, "action": "fail-closed-withdraw", "auto_merge_withdrawn": True}.items() <= next(
        a for a in lines if a.get("pr") == 1810 and a["action"] == "fail-closed-withdraw").items()
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
    """opus 中：本轮先合入了一个 PR、后一个写超时，已合入那条照样写日志，写超时那条记 write-unknown。"""
    github = FakeGitHub(lane)
    _more_pulls(lane, github, [1805])
    green(github, f"{1805:040d}")
    green(github, lane.gateway.pr["head"]["sha"])
    merges = []
    def merge(number, head):
        if number == 1810:
            _hang()
        merges.append(number)
    github.merge = merge
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    assert ServeRound(sweep, clock=Clock())() is None
    lines = [json.loads(line.removeprefix("review-sweep ")) for line in capsys.readouterr().out.splitlines()]
    assert merges == [1805]
    assert any(a.get("pr") == 1805 and a["action"] == "merged" for a in lines)
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
    assert "复核 head" in result["reason"] and github.calls == [("disable", 1810)]


def test_writes_carry_the_classified_head():
    """合入带 sha、追平带 expected_head_sha：head 已变时由 GitHub 服务端拒绝。"""
    sent = []
    cli = module.GhCli("Newchanlun/NewChanlun")
    cli._gh = lambda *args: sent.append(args) or ""
    cli.merge(5, "a" * 40)
    cli.update_branch(5, "b" * 40)
    assert f"sha={'a' * 40}" in sent[0] and f"expected_head_sha={'b' * 40}" in sent[1]


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
    green(github, f"{1805:040d}")                                   # 本可合入
    github.states[1811] = {"mergeable_state": "behind"}             # 本可追平
    _sensitive_armed(lane, github)                                  # 1810：须撤 auto-merge
    if setting == "enabled":
        github.allow_auto_merge = lambda: True
    else:
        github.allow_auto_merge = _raise
    sweep, _, _ = make(lane, run=False, github=github, auto_merge=True)
    actions = sweep.tick()
    flagged = next(a for a in actions if a["action"] == "native-auto-merge-enabled")
    assert ("allow_auto_merge=true" in flagged["reason"]) == (setting == "enabled")
    assert github.calls == [("disable", 1810)]                     # 只撤，不合入、不追平


def test_repo_with_native_auto_merge_disabled_merges_normally(lane):
    github = FakeGitHub(lane)
    green(github, lane.gateway.pr["head"]["sha"])
    sweep, _, _ = make(lane, github=github, auto_merge=True)
    actions = sweep.tick()
    assert "native-auto-merge-enabled" not in [a["action"] for a in actions] and "merged" in acts(actions)


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
