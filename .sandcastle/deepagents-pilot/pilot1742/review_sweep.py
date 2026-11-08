"""#1742 正式审查的自动触发与（可选）合入。常驻入口是 executor serve 的每轮钩子（ServeRound，
`serve --review-sweep [--review-sweep-auto-merge]`）；本模块的 main 只供手动单跑。

每轮 tick 列出指向 main 的开放 PR（max_age 内有活动、非草稿、同仓），逐个隔离处理，单个 PR 的异常不影响其他 PR，
主循环遇到异常也不退出。整轮的输入源（GitHub 开放 PR 列表、本机进程表）读不到时抛 SourceUnreadable，写明是哪个源。

审查（按 head 判定，不按 base；main 前进不会把已审完的同一 head 拉回 pending）：
- 这个 PR 已有审查进程在跑：等待（同一 PR 同时只跑一个，与 head 无关，免得重复派发）；
- 本 head 上有已发布终态（非 STALE 且有 publication）：完成；
- 本 head 上有结论但没发布（outcome 已存、publication 缺失）：同一 attempt 续跑一次走受管对账与发布，再不成交操作员；
- 本 head 上有登记、无结论、进程已不在（中断）：同一 attempt 续跑一次，再不成交操作员；
- 其余（没有 run，或本 head 上只有 STALE）：派发下一个 attempt；子进程登记前就退出的同一 attempt 退避 10 分钟再派。
派发的子进程绑定决策时的 head：先核对 PR 仍是这个 head，不是就不审（run-review --expect-head）。
启用合入时，strict 下落后的 PR 先追平、再审新 head（不审一个合入前必然被替换的 head）。
发起前 base、head 提交须已在宿主对象库（EXTERNAL-REVIEW.md：入口和 reviewer 都不 fetch）；缺失时调用 owner 注入的
sync(number, base, head)，未注入报 needs-source-sync。

合入（--auto-merge，用宿主 gh 凭据；本模块不构造 App 身份，审查身份归 external_review）：不预先挂 auto-merge。
只有同时满足下列条件才合入，用 REST PUT /pulls/{n}/merge 并带 sha=<该 head>，由 GitHub 服务端拒绝 head 不符（409）：
- main 的分支保护 strict 开着，且必需检查同时含 deepagents/review 与 ci-ok，两者都绑定了来源 app（没绑定的谁都能发同名 success）；
- 该精确 head 上 deepagents/review、ci-ok、DevSkim 都是 success，且 GitHub 判定可合入（clean/unstable）；
- 该 head 的完整改动清单可判定且不触及人工确认两类（HUMAN_GATED：实盘下单或资金、密钥或凭证）。
两类的出处：用户裁定留痕 https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631
完整清单：files 接口最多 3000 个且需与 changed_files 相符；否则用本地精确 diff；两者都拿不到报 evidence-insufficient
（下轮重试），不合入，也不升级成人工确认。
触及两类的报 needs-human-confirm，不合入、不追平；这类 PR 上若挂着 GitHub 原生 auto-merge 会撤掉。
证据不全一律按失败关闭（fail closed）：该 PR 的状态、文件清单或检查读不到，main 的必需检查读不到，或处理中出任何异常，
都不合入、不追平，并撤掉它的原生 auto-merge（状态读不到、不知道挂没挂时也撤）——否则一个读失败的敏感 PR
会靠原生 auto-merge 在检查转绿后绕过 HUMAN_GATED。
每个 gh 调用都有 GH_TIMEOUT_SECONDS 上限；超时按输入源读不到处理（SourceUnreadable），整轮作废、下轮重试，
所以一轮最多卡一个超时，不会无限期拖住 executor serve 的派票循环。补对象的 fetch 另有 FETCH_TIMEOUT_SECONDS，
一轮里失败一次后其余 PR 不再 fetch。
追平只给队首（CI 节流：同一时刻只让一个 PR 占一整轮 CI）。队首是按 PR 号排第一个仍可能合入的 PR；冲突（dirty）、本 head
已有失败的独审结论、审查卡在要操作员处理的状态（STUCK_REVIEW）、不落后却有合入检查失败、或不落后且三项检查全绿
却仍不可合入（mergeable_state 停在 blocked/unknown 等，例如 main 另有未满足的保护规则）的 PR 不占队首，免得一个卡住的
PR 挡住整列。队首落后、且本地没有它的在途审查（活进程或本轮刚派出）时追平，用 expected_head_sha 绑定 head（服务端 422
拒绝不符）；队首不落后（在等审查或 CI）时，其他落后的 PR 一律不追平。在途与否以本地为准，不看 GitHub 上的 pending：
审查进行中 main 前进时终态判 Stale，GitHub 上会一直停在 pending，以它为准会让追平与重审互等。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .external_review import STATE_ROOT, ExternalReview, _git, git_environment
from .run import _ps_rows
from .workunit import REPO

Rows = list[tuple[int, int, str, str]]
Spawn = Callable[[int, int, str, Path], int]
Sync = Callable[[int, str, str], None]
GATE = frozenset({"deepagents/review", "ci-ok"})
LAUNCH_BACKOFF_SECONDS = 600
MIN_LOOP_SECONDS = 180
MERGE_CHECKS = ("deepagents/review", "ci-ok", "DevSkim")
FILES_CAP = 3000
FETCH_TIMEOUT_SECONDS = 120
GH_TIMEOUT_SECONDS = 60

# 人工确认只剩两类：实盘下单或资金、密钥或凭证。出处：用户 2026-11-07、2026-11-08 的裁定，原话留痕在
#   https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631
# CI 与分支保护配置（workflows、actions、DevSkim 门脚本、基线与误报清单）不再交人工确认。已接受的风险：改 CI 的 PR
# 在自己的合并 ref 上运行自己定义的 ci-ok 与 DevSkim，必需检查的 app 绑定挡不住它把这两项改成恒成功或放宽扫描准入，
# 所以对这类 PR，精确 head 上的双模型非作者独审（deepagents/review）是唯一独立的把关。裁定同时划定边界：代理不得借改
# CI 关闭或放宽必需检查 deepagents/review、ci-ok；独审按这条边界判。
# 两类的边界按仓库实际入口定（2026-11-07 逐个核对用途），不按名字猜；新增同类入口时更新本表。
#   实盘下单或资金：X 执行域、E 经济、B 域、唯一生产 launcher（会话命名约定 x_/e_/b_/production_），E/B 经济事实库
#     （账本 book、allocation、finance……）、trading、funding_record；Python 实盘 runner、执行器与券商/交易所配置
#     （trading_system/config/broker_config.py：IBKR 实盘/纸交易端口、Hyperliquid 主网/测试网）；会连实盘端口下单的脚本
#     （tws_margin_check.py、analysis/buy_28316_warrant.py：TWS 7496 提交 LMT 单）。
#     不含：diagnostic_fill（头注释：不产生正式成交或持仓）、回测、行情抓取、其余 analysis。
#   密钥或凭证：密钥材料与凭证配置文件本身；不含讲到 token 的普通代码或文档。
HUMAN_GATED: dict[str, re.Pattern[str]] = {
    "live-trading-or-funds": re.compile(
        r"^rust/src/bin/(x_|e_|b_|production_)[^/]*session[^/]*\.rs$"
        r"|^rust/src/(economic_session|trading|funding_record)/|^rust/src/funding_record\.rs$"
        r"|^trading_system/(live|execution)/|^trading_system/config/broker_config\.py$|^src/newchan/trading/"
        r"|^tws_margin_check\.py$|^analysis/buy_28316_warrant\.py$"),
    "secrets-or-credentials": re.compile(
        r"\.(pem|key|p12|pfx|p8)$|(^|/)\.env(\.[^/]*)?$|(^|/)\.(envrc|netrc|npmrc|pypirc)$|(^|/)id_(rsa|ed25519|ecdsa|dsa)$"
        r"|(^|/)(secrets?|credentials?)\.(json|ya?ml|toml|ini)$",
        re.IGNORECASE),
}
STUCK_REVIEW = frozenset({"needs-operator", "needs-reconcile", "needs-source-sync", "error"})
QUIET = frozenset({"done", "draft", "stale-pr"})  # 没有动作的状态，不写日志


class EvidenceInsufficient(RuntimeError):
    """证据不足：清单、检查或必需检查读不全。不合入、不追平、撤掉原生 auto-merge，不升级成人工确认；下轮重试。"""


class SourceUnreadable(RuntimeError):
    """整轮的输入源读不到。本轮不派审、不追平、不合入，下轮重试；source 写明是哪个源。"""

    def __init__(self, source: str, error: BaseException):
        super().__init__(f"{source}: {type(error).__name__}: {error}")
        self.source = source


def human_gated(files: list[str]) -> dict[str, list[str]]:
    """命中人工确认两类的文件，按类别列出；空表示不需要人工确认。"""
    hits: dict[str, list[str]] = {}
    for name in files:
        for category, pattern in HUMAN_GATED.items():
            if pattern.search(name):
                hits.setdefault(category, []).append(name)
    return hits


class GitHubPort(Protocol):
    """读写 GitHub 的端口（宿主 gh 凭据）。写操作只在 --auto-merge 时调用。"""
    def open_pulls(self) -> list[dict[str, Any]]: ...
    def pr(self, number: int) -> dict[str, Any]: ...
    def checks(self, head: str) -> dict[str, str]: ...
    def required_checks(self) -> set[str]: ...
    def pr_files(self, number: int) -> list[dict[str, Any]]: ...
    def merge(self, number: int, head: str) -> None: ...
    def update_branch(self, number: int, head: str) -> None: ...
    def disable_auto_merge(self, number: int) -> None: ...


class GhCli:
    def __init__(self, repository: str = REPO, timeout: float = GH_TIMEOUT_SECONDS):
        self.repository, self.timeout = repository, timeout

    def _gh(self, *args: str) -> str:
        try:
            return subprocess.run(["gh", *args], capture_output=True, text=True, check=True,
                                  timeout=self.timeout).stdout
        except subprocess.TimeoutExpired as error:  # 挂住的 gh 不能拖住 serve：按源读不到处理，整轮作废
            target = next((a for a in args if a.startswith("repos/")), " ".join(args[:2]))
            raise SourceUnreadable(f"github ({target.split('?')[0]}) timed out after {self.timeout:g}s", error) from None

    def _json_lines(self, *args: str) -> list[Any]:
        return [json.loads(line) for line in self._gh(*args).splitlines() if line.strip()]

    def open_pulls(self) -> list[dict[str, Any]]:
        pulls = self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls?state=open&base=main&per_page=100",
                                 "--jq", ".[] | @json")
        return list({pr["number"]: pr for pr in pulls}.values())  # 翻页期间变化可能重复，按号码去重

    def pr(self, number: int) -> dict[str, Any]:
        data = json.loads(self._gh("api", f"repos/{self.repository}/pulls/{number}"))
        return {"head": data["head"]["sha"], "base": data["base"]["sha"], "changed_files": data["changed_files"],
                "mergeable_state": data["mergeable_state"], "auto_merge": data["auto_merge"] is not None}

    def checks(self, head: str) -> dict[str, str]:
        """该 head 上每个检查名的最新结论：success / failure / pending。"""
        result: dict[str, str] = {}
        status = json.loads(self._gh("api", f"repos/{self.repository}/commits/{head}/status"))
        for item in status["statuses"]:  # 合并接口已按 context 取最新
            result[item["context"]] = {"success": "success", "pending": "pending"}.get(item["state"], "failure")
        runs = self._json_lines("api", "--paginate", f"repos/{self.repository}/commits/{head}/check-runs?per_page=100",
                                "--jq", ".check_runs[] | @json")
        for run in sorted(runs, key=lambda r: (r.get("started_at") or "", r["id"])):  # 重跑时后者覆盖前者
            result[run["name"]] = ("pending" if run["status"] != "completed" else
                                   "success" if run["conclusion"] in ("success", "skipped", "neutral") else "failure")
        return result

    def required_checks(self) -> set[str]:
        """main 上可信的必需检查。strict（要求 PR 先与 base 追平）关着就一个都不算：审查结论只对 (base, head)
        成立，不追平就会拿旧 base 上的结论合入。没绑定来源 app 的检查，任何有 statuses:write 的人都能发一条同名
        success，也不算。"""
        rules = json.loads(self._gh("api", f"repos/{self.repository}/branches/main/protection/required_status_checks"))
        if rules.get("strict") is not True:
            return set()
        return {c["context"] for c in rules.get("checks", [])
                if type(c.get("app_id")) is int and c["app_id"] > 0}  # bool 是 int 的子类，排除

    def pr_files(self, number: int) -> list[dict[str, Any]]:
        return self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls/{number}/files?per_page=100",
                                "--jq", ".[] | {filename, previous_filename, status, changes} | @json")

    def merge(self, number: int, head: str) -> None:
        # REST 文档：sha 是「PR head 必须与之匹配才允许合入」，不符返回 409。
        self._gh("api", "-X", "PUT", f"repos/{self.repository}/pulls/{number}/merge",
                 "-f", f"sha={head}", "-f", "merge_method=merge")

    def update_branch(self, number: int, head: str) -> None:
        # REST 文档：expected_head_sha 与 PR head 不符返回 422。
        self._gh("api", "-X", "PUT", f"repos/{self.repository}/pulls/{number}/update-branch",
                 "-f", f"expected_head_sha={head}")

    def disable_auto_merge(self, number: int) -> None:
        self._gh("pr", "merge", str(number), "-R", self.repository, "--disable-auto")


def run_review_command(number: int, attempt: int, head: str, private_key: Path) -> list[str]:
    return [sys.executable, "-m", "pilot1742.review_sweep", "run-review", "--pr", str(number),
            "--attempt", str(attempt), "--expect-head", head, "--private-key", str(private_key)]


_REVIEWER = re.compile(r"pilot1742\.(review_sweep run-review|external_review review-pr) --pr (\d+) ")


def reviewing(rows: Rows) -> set[int]:
    """正在审查的 PR 号：活着（非僵尸）的 run-review 或 review-pr 进程，含操作员手动起的 review-pr。"""
    return {int(m.group(2)) for _, _, stat, command in rows if not stat.startswith("Z")
            for m in [_REVIEWER.search(command + " ")] if m}


class Sweep:
    def __init__(self, github: GitHubPort, lane: ExternalReview, spawn: Spawn, *,
                 state_root: Path = STATE_ROOT, max_running: int = 2, rows: Callable[[], Rows] = _ps_rows,
                 sync: Sync | None = None, auto_merge: bool = False, max_age: timedelta = timedelta(hours=24),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.github, self.lane, self.spawn, self.rows, self.sync = github, lane, spawn, rows, sync
        self.folder = state_root / "sweep"
        self._sync_failed = False
        self.max_running, self.auto_merge, self.max_age, self.now = max_running, auto_merge, max_age, now

    def open_pulls(self) -> list[dict[str, Any]]:
        return self.github.open_pulls()

    def _eligible(self, pr: dict[str, Any]) -> str | None:
        if pr.get("draft"):
            return "draft"
        if (pr["head"].get("repo") or {}).get("id") != pr["base"]["repo"]["id"]:
            return "foreign-head"
        updated = pr.get("updated_at")
        if updated is not None and datetime.fromisoformat(updated.replace("Z", "+00:00")) < self.now() - self.max_age:
            return "stale-pr"
        return None

    def _resumes(self, number: int, head: str, attempt: int) -> Path:
        return self.folder / f"p{number}-{head}-a{attempt}.resumes"

    def _has_commits(self, *shas: str) -> bool:
        try:
            for sha in shas:
                _git(self.lane.source, "cat-file", "-e", f"{sha}^{{commit}}")
        except subprocess.CalledProcessError:
            return False
        return True

    def _launch(self, number: int, head: str, attempt: int) -> int:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.spawn(number, attempt, head, self.folder / "logs" / f"p{number}-{head[:12]}-a{attempt}.log")

    def _resume_once(self, number: int, head: str, attempt: int, action: str) -> tuple[str, dict | None]:
        marker = self._resumes(number, head, attempt)
        if marker.exists():
            return ("needs-reconcile" if action == "publish" else "needs-operator"), None
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text(str(time.time()))
        return f"resume-{action}", {"pid": self._launch(number, head, attempt), "attempt": attempt}

    def decide(self, pr: dict[str, Any], busy: set[int], running: int, behind: bool) -> tuple[str, dict | None]:
        number, head, base = pr["number"], pr["head"]["sha"], pr["base"]["sha"]
        if number in busy:
            return "running", None
        runs = [row for row in self.lane.status(number) if row["target"].get("head_sha") == head]
        final = [r for r in runs if r["outcome"] and r["outcome"].get("verdict") != "STALE"]
        if any("publication" in r["outcome"] for r in final):
            return "done", None
        if running >= self.max_running:
            return "queued", None
        if final:  # 有结论没发布：受管对账与发布（同一 attempt，key 要求 base 未变）
            row = max(final, key=lambda r: r["target"]["registered_at_ns"])
            if row["target"].get("base_sha") != base:
                return "needs-reconcile", None
            return self._resume_once(number, head, row["target"]["attempt"], "publish")
        if behind:  # 先追平再审：不审一个合入前必然被替换的 head
            return "behind-awaiting-update", None
        if not self._has_commits(base, head):
            if self.sync is None or self._sync_failed:  # 一轮里 fetch 失败过就不再试，免得超时逐个累加
                return "needs-source-sync", None
            try:
                self.sync(number, base, head)
            except Exception:
                self._sync_failed = True
                raise
            if not self._has_commits(base, head):
                return "needs-source-sync", None
        current = [r for r in runs if r["target"].get("base_sha") == base]
        live = [r for r in current if not r["outcome"]]
        if live:  # 中断：同一 attempt 续跑一次
            return self._resume_once(number, head, max(r["target"]["attempt"] for r in live), "review")
        attempt = max((r["target"]["attempt"] for r in current), default=0) + 1
        # 子进程在登记前就退出（读 PR 失败、App 身份未就绪、controller 不干净）时同一 attempt 会原样再派；
        # 退避一段时间，免得每轮都派一个必死的子进程。
        marker = self.folder / f"p{number}-{head}-{base}-a{attempt}.launched"
        if marker.exists() and time.time() - marker.stat().st_mtime < LAUNCH_BACKOFF_SECONDS:
            return "launch-backoff", None
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text(str(time.time()))
        return "launch", {"pid": self._launch(number, head, attempt), "attempt": attempt}

    def tick(self) -> list[dict[str, Any]]:
        try:
            rows = self.rows()
        except Exception as error:  # 不知道谁在审就不能派审：整轮作废
            raise SourceUnreadable("host process table", error) from error
        busy = reviewing(rows)
        running = len(busy)
        # 追平只看本地真实在途（活进程或本轮刚派出），不信 GitHub 上的 pending：审查进行中 main 前进时终态判 Stale，
        # GitHub 上该 head 会一直停在 pending；若以它为准，decide 等追平、合入等审查，两边互等。中断后残留的
        # 无结论 run 审的是旧 base，追平后自然作废，也不挡追平。
        reviewing_now = set(busy)
        try:
            pulls = sorted(self.open_pulls(), key=lambda pr: pr["number"])
        except Exception as error:
            raise SourceUnreadable("github open pulls", error) from error
        self._sync_failed = False
        actions: list[dict[str, Any]] = []
        states: dict[int, dict[str, Any]] = {}
        unreadable: set[int] = set()
        review_actions: dict[int, str] = {}
        for pr in pulls:
            entry: dict[str, Any] = {"pr": pr["number"], "head": pr["head"]["sha"]}
            try:
                skip = self._eligible(pr)
                if skip:  # 闲置超过活动窗的 PR 整个跳过：不读接口、不追平（不在闲置分支上压合并提交、触发整套 CI）
                    actions.append({**entry, "action": skip})
                    continue
                behind = False
                if self.auto_merge:
                    try:
                        states[pr["number"]] = self.github.pr(pr["number"])
                    except SourceUnreadable:
                        raise
                    except Exception:  # 状态读不到：不派审，合入阶段按失败关闭处理（撤原生 auto-merge）
                        unreadable.add(pr["number"])
                        raise
                    behind = states[pr["number"]]["mergeable_state"] == "behind"
                action, record = self.decide(pr, busy, running, behind)
                started = action in ("launch", "resume-review", "resume-publish")
                running += started
                if started:
                    reviewing_now.add(pr["number"])
                actions.append({**entry, "action": action, **(record or {})})
            except SourceUnreadable:  # gh 超时：整轮作废
                raise
            except Exception as error:  # 单个 PR 隔离：记下，继续处理其他 PR
                action = "error"
                actions.append({**entry, "action": action, "reason": f"{type(error).__name__}: {error}"})
            review_actions[pr["number"]] = action
        if self.auto_merge:
            actions += self.merge_actions(pulls, states, reviewing_now, review_actions, unreadable)
        return actions

    def complete_files(self, number: int, state: dict[str, Any]) -> list[str]:
        """该 head 的完整改动路径（含改名前路径）；读不全时用本地精确 diff，仍不行就证据不足。"""
        try:
            entries = self.github.pr_files(number)
        except SourceUnreadable:
            raise
        except Exception as error:
            raise EvidenceInsufficient(f"读取文件清单失败：{type(error).__name__}: {error}") from None
        names = {e["filename"] for e in entries}
        if len(entries) < FILES_CAP and len(names) == state["changed_files"]:
            return sorted(names | {e["previous_filename"] for e in entries if e.get("previous_filename")})
        try:  # 截断或数目不符：本地精确 diff（--no-renames 同时列出改名两端）
            merge_base = _git(self.lane.source, "merge-base", state["base"], state["head"]).decode().strip()
            raw = _git(self.lane.source, "diff", "--name-only", "-z", "--no-renames", merge_base, state["head"])
        except subprocess.CalledProcessError:
            raise EvidenceInsufficient(f"文件清单不全（接口 {len(entries)} 条，changed_files={state['changed_files']}），"
                                       "本地也缺对象") from None
        return sorted(p for p in raw.decode().split("\0") if p)

    def _merge_one(self, pr: dict[str, Any], state: dict[str, Any], gate_ok: bool, head_free: bool,
                   reviewing_now: bool = False, review_action: str | None = None) -> tuple[dict[str, Any], bool]:
        """返回（动作，是否占队首）。只有 head_free（前面没有 PR 占队首）且本 PR 仍可能合入时才可能追平。"""
        number, head = pr["number"], pr["head"]["sha"]
        if state["head"] != head:
            return {"action": "head-moved"}, False
        gated = human_gated(self.complete_files(number, state))  # 证据不足抛出，由 merge_actions 失败关闭
        if gated:
            if state["auto_merge"]:
                self.github.disable_auto_merge(number)
            return {"action": "needs-human-confirm", "gated": gated}, False
        try:
            checks = self.github.checks(head)
        except SourceUnreadable:
            raise
        except Exception as error:
            raise EvidenceInsufficient(f"读取 {head[:12]} 的检查失败：{type(error).__name__}: {error}") from None
        review = checks.get("deepagents/review")
        behind = state["mergeable_state"] == "behind"
        all_green = all(checks.get(name) == "success" for name in MERGE_CHECKS)
        # 本 head 已发布失败结论（BLOCK/error）时追平只会换来注定被拦的重审；落后时其余检查失败可能是旧 base 造成的，
        # 追平给一次新 CI；不落后时检查失败要作者处理；不落后、三项全绿却不可合入（blocked/unknown 等）的也不占队首。
        candidate = (review != "failure" and state["mergeable_state"] != "dirty" and review_action not in STUCK_REVIEW
                     and (behind or not any(checks.get(name) == "failure" for name in MERGE_CHECKS))
                     and (behind or not all_green or state["mergeable_state"] in ("clean", "unstable")))
        is_head = candidate and head_free
        if behind:
            if is_head and not reviewing_now:  # 本地有在途审查时不追平
                self.github.update_branch(number, head)
                return {"action": "update-branch"}, True
            return {"action": "behind-waiting", "review": review, "reviewing": reviewing_now,
                    "queue_head": is_head}, candidate
        if gate_ok and state["mergeable_state"] in ("clean", "unstable") and all_green:
            self.github.merge(number, head)
            return {"action": "merged"}, candidate
        return {"action": "waiting", "checks": {name: checks.get(name) for name in MERGE_CHECKS},
                "mergeable_state": state["mergeable_state"], "queue_head": is_head,
                **({} if gate_ok else {"gate": "ci-ok 未设为必需检查"})}, candidate

    def _withdraw(self, number: int, armed: bool) -> dict[str, Any]:
        """失败关闭：撤掉原生 auto-merge。armed 为真（挂着或不知道挂没挂）才撤；撤失败如实记下，不影响其他 PR。"""
        if not armed:
            return {}
        try:
            self.github.disable_auto_merge(number)
        except SourceUnreadable:
            raise
        except Exception as error:
            return {"auto_merge_withdrawn": False, "withdraw_error": f"{type(error).__name__}: {error}"}
        return {"auto_merge_withdrawn": True}

    def merge_actions(self, pulls: list[dict[str, Any]], states: dict[int, dict[str, Any]],
                      reviewing_now: set[int] | frozenset[int] = frozenset(),
                      review_actions: dict[int, str] | None = None,
                      unreadable: set[int] | frozenset[int] = frozenset()) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        review_actions = review_actions or {}
        evidence_ok = True
        try:
            gate_ok = GATE <= self.github.required_checks()
        except SourceUnreadable:
            raise
        except Exception as error:  # 不合入、不追平，但照常逐个 PR 判人工确认类并撤原生 auto-merge
            gate_ok = evidence_ok = False
            actions.append({"action": "evidence-insufficient", "reason": f"读取 main 必需检查失败：{error}"})
        if evidence_ok and not gate_ok:
            actions.append({"action": "auto-merge-unsafe",
                            "reason": f"main 须 strict 且必需检查含绑定来源 app 的 {sorted(GATE)}，不合入"})
        head_free = True
        for pr in pulls:  # 与 tick 同序（PR 号升序）：队首是第一个仍可能合入的 PR
            number = pr["number"]
            entry = {"pr": number, "head": pr["head"]["sha"]}
            if number in unreadable:  # 状态读不到，不知道挂没挂原生 auto-merge：照撤
                actions.append({**entry, "action": "evidence-insufficient", "reason": "读取 PR 状态失败",
                                **self._withdraw(number, True)})
                continue
            if number not in states:
                continue
            claimed = False
            try:
                result, claimed = self._merge_one(pr, states[number], gate_ok, head_free and evidence_ok,
                                                  number in reviewing_now, review_actions.get(number))
            except SourceUnreadable:
                raise
            except Exception as error:  # 单个 PR 隔离；不明即不合入，并撤原生 auto-merge（失败关闭）
                kind = "evidence-insufficient" if isinstance(error, EvidenceInsufficient) else "error"
                reason = str(error) if kind == "evidence-insufficient" else f"{type(error).__name__}: {error}"
                result = {"action": kind, "reason": reason,
                          **self._withdraw(number, states[number].get("auto_merge") is not False)}
            head_free = head_free and not claimed
            actions.append({**entry, **result})
        return actions


def report(actions: list[dict[str, Any]], prefix: str = "") -> None:
    """每个动作一行 JSON；没有动作的状态（QUIET）不写。"""
    for action in actions:
        if action.get("action") not in QUIET:
            print(prefix + json.dumps(action, ensure_ascii=False), flush=True)


class ServeRound:
    """executor serve 每轮调用一次的钩子：至多跑一轮 sweep，距上一轮不足 interval 秒就跳过（GitHub 核心限额，
    见 MIN_LOOP_SECONDS）。上一轮的时间记在状态目录的文件上，launchd 重启 serve 也不会加密轮次。每个动作一行日志，
    前缀 `review-sweep `；输入源读不到或整轮出错时记一行写明原因，不抛出，serve 循环照常继续。"""

    def __init__(self, sweep: Sweep, *, interval: float = MIN_LOOP_SECONDS, clock: Callable[[], float] = time.time):
        self.sweep, self.interval, self.clock = sweep, interval, clock
        self.stamp = sweep.folder / "serve-round.last"

    def __call__(self) -> list[dict[str, Any]] | None:
        """返回本轮动作；本轮不到时间或失败返回 None。"""
        try:
            last = float(self.stamp.read_text())
        except (OSError, ValueError):
            last = None
        now = self.clock()
        if last is not None and 0 <= now - last < self.interval:
            return None
        try:
            self.sweep.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.stamp.write_text(repr(now))  # 先记时间：本轮失败也按间隔重试，不每轮重打接口
            actions = self.sweep.tick()
        except SourceUnreadable as error:
            report([{"action": "round-skipped", "unreadable": error.source, "reason": str(error)}], "review-sweep ")
            return None
        except Exception as error:
            report([{"action": "tick-error", "reason": f"{type(error).__name__}: {error}"}], "review-sweep ")
            return None
        report(actions, "review-sweep ")
        return actions


def fetcher(source: Path, url: str = f"https://github.com/{REPO}.git") -> Sync:
    """sweep 的 sync：把 main 与 PR head 取进宿主对象库，只写 FETCH_HEAD，不动 HEAD、分支与工作区（controller
    身份不变）。仓库公开，用 external_review 的无凭据 git 环境。"""
    def sync(number: int, base: str, head: str) -> None:
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(source), "fetch", "--no-tags", "--quiet",
                        url, "main", f"pull/{number}/head"], env=git_environment(), check=True, capture_output=True,
                       timeout=FETCH_TIMEOUT_SECONDS)
    return sync


def serve_round(private_key: Path, *, auto_merge: bool = False) -> ServeRound:
    """executor serve 用的钩子。max_running=1：HOST 上同时只跑一个审查，操作员手动起的 review-pr 也算（reviewing）。"""
    lane = ExternalReview(None)
    return ServeRound(Sweep(GhCli(), lane, spawner(private_key), max_running=1, auto_merge=auto_merge,
                            sync=fetcher(lane.source)))


def spawner(private_key: Path) -> Spawn:
    def spawn(number: int, attempt: int, head: str, log: Path) -> int:
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(log, "ab", opener=lambda p, f: os.open(p, f, 0o600)) as out:
            return subprocess.Popen(run_review_command(number, attempt, head, private_key), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=out, start_new_session=True,
                                    cwd=Path(__file__).resolve().parents[1]).pid
    return spawn


def run_review(argv: list[str], github: GitHubPort | None = None) -> int:
    """子进程入口：先核对 PR 仍是决策时的 head，再交给 external_review review-pr（身份由它负责）。"""
    parser = argparse.ArgumentParser(prog="pilot1742.review_sweep run-review")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--expect-head", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args(argv)
    if (github or GhCli()).pr(args.pr)["head"] != args.expect_head:
        print(json.dumps({"pr": args.pr, "action": "head-moved-not-reviewed", "expected": args.expect_head}))
        return 3
    from . import external_review
    return external_review.main(["review-pr", "--pr", str(args.pr), "--attempt", str(args.attempt),
                                 "--private-key", str(args.private_key)])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run-review"]:
        return run_review(argv[1:])
    parser = argparse.ArgumentParser(prog="pilot1742.review_sweep")
    parser.add_argument("--private-key", required=True, type=Path, help="只原样交给审查子进程")
    parser.add_argument("--max-running", type=int, default=2)
    parser.add_argument("--loop", type=float, default=0,
                        help=f"0 只跑一轮；循环时间隔至少 {MIN_LOOP_SECONDS:g} 秒（每轮每个 PR 约 4 次读接口，受 GitHub 核心限额约束）")
    parser.add_argument("--auto-merge", action="store_true",
                        help="默认关。用宿主 gh 凭据追平队首与合入（须 ci-ok 为必需检查；人工确认两类除外）")
    args = parser.parse_args(argv)
    if not math.isfinite(args.loop) or not (args.loop == 0 or args.loop >= MIN_LOOP_SECONDS):  # 挡住负数、nan、inf
        parser.error(f"--loop 须为 0 或至少 {MIN_LOOP_SECONDS:g} 秒")
    sweep = Sweep(GhCli(), ExternalReview(None), spawner(args.private_key), max_running=args.max_running,
                  auto_merge=args.auto_merge)
    while True:
        try:
            report(sweep.tick())
        except Exception:  # 整轮失败（例如列 PR 失败）：记下，下轮重试，不退出
            print(json.dumps({"action": "tick-error", "reason": traceback.format_exc(limit=3)}, ensure_ascii=False),
                  flush=True)
        if args.loop <= 0:
            return 0
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())
