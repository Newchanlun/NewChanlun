"""#1742 正式审查的自动触发、对账与原生 auto-merge 撤销。

常驻入口是 executor serve 的每轮钩子（ServeRound）；本模块的 main 供手动运行。
同仓、非草稿、活动窗内的开放 main PR 按可沿用 PASS、再按 head 提交时间派审。
同一 PR 同时只派一次；已有发布不重复审，被覆盖报 needs-reconcile，不阻挡其他 PR。
中断或发布未完成的同一 attempt 只续跑一次；登记前退出的 attempt 退避 10 分钟。
限流退避只延后新审查与审查续跑，不影响发布续跑、对账与撤销。

#2131 R09 切换前无自动合入、无自动追平。兼容 --review-sweep-auto-merge / --auto-merge，
但只增加只读的三门与改动分类诊断，诊断不授权合入。获准人工合入者按 graph-engineering.md 核验；
切换后合入只走 R09 受控入口，sweep 不持合入凭据。

先撤销仓库所有开放 PR 的已知或未知挂载，再诊断和派审；仓库设置非明确关闭时整轮不派审／续发。
挂载过的 PR 本轮不派审／续发；命中人工确认或读取／核验失败时仍尝试撤销。gh 读超时中止本轮并尝试撤销；
撤销也超时则记录未确认并中止余下操作，下轮重试。
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
from typing import Any, NamedTuple, Protocol
from urllib.parse import quote

from . import external_review
from .external_review import (
    DEFAULT_IDENTITY,
    STATE_ROOT,
    ExternalReview,
    _git,
    git_environment,
)
from .github_app import IdentityError
from .run import _ps_rows
from .workunit import REPO

Rows = list[tuple[int, int, str, str]]
Spawn = Callable[[int, int, str, Path], int]
Sync = Callable[[int, str, str], None]
LAUNCH_BACKOFF_SECONDS = 600
# 限流退避：最近 RATE_LIMIT_RUNS 个已完结的审查 run 都有 reviewer 以 failure_code=rate_limited 失败时，自最后一个完结起
# RATE_LIMIT_BACKOFF_SECONDS 内不派新审查（不派 launch、不续跑 resume-review）；发布续跑、对账、撤 auto-merge 照常。
RATE_LIMIT_RUNS = 2
RATE_LIMIT_BACKOFF_SECONDS = 1800
MIN_LOOP_SECONDS = 180
# 派发先后：head 提交早于这么久的 PR 排在最后（只在没有更新的 PR 等着时才轮到）。
STALE_PUSH = timedelta(hours=48)
MERGE_CHECKS = ("deepagents/review", "ci-ok", "DevSkim")
GATE = frozenset(MERGE_CHECKS)
FILES_CAP = 3000
FETCH_TIMEOUT_SECONDS = 120
REVIEW_APP_ID = 5664795
ACTIONS_APP_ID = 15368
WORKFLOWS = {"ci-ok": ".github/workflows/ci.yml", "DevSkim": ".github/workflows/devskim.yml"}
BASE_CHANGE_EVENTS = frozenset({"base_ref_changed", "automatic_base_change_succeeded", "automatic_base_change_failed"})
REVIEW_STATUS = re.compile(
    r"run=([a-f0-9-]{36}) b=([a-f0-9]{12}) h=([a-f0-9]{12}) (success|pending|failure|error)"
    r"(?: reuse=([a-f0-9-]{36}) p=([a-f0-9]{12}))?"
)
# Commit Status 只露出 bot 账号；用 GET /apps/{slug} 核数值身份。
REVIEW_PUBLISHER = (REVIEW_APP_ID, "newchanlun-review-gate")
GH_TIMEOUT_SECONDS = 60
# 执行器 App：交付时在冻结 head 上自写 deepagents/review=success（作者侧独审，不是正式非作者双审）。
EXECUTOR_APP_ID = DEFAULT_IDENTITY["app_id"]


def configured_publisher(config: Path | None = None) -> tuple[int, str] | None:
    """和正式发布读取同一身份配置；缺席用执行器 App，坏配置不回退。这里只验证元数据，不读取私钥。"""
    try:
        identity = external_review.load_identity(config or external_review.IDENTITY_CONFIG, Path("/unused"))
    except (IdentityError, OSError):
        return None
    return identity.app_id, identity.app_slug

# 人工确认只剩两类：实盘下单或资金、密钥或凭证。出处：用户 2026-11-07、2026-11-08 的裁定，原话留痕在
#   https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631
# CI 与分支保护配置不属于两类；来源及合入规程见 graph-engineering.md。
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
# 没有动作的状态，不写日志。review-backoff 由本轮一行 rate-limit-backoff 汇总，不逐个 PR 记。
QUIET = frozenset({"done", "draft", "stale-pr", "review-backoff"})


class EvidenceInsufficient(RuntimeError):
    """证据不足：清单、检查或必需检查读不全，撤原生 auto-merge，不升级成人工确认。"""


class SourceUnreadable(RuntimeError):
    """输入源读不到，中止本轮余下派审，下轮重试；source 写明读不到的源。"""

    def __init__(self, source: str, error: BaseException):
        super().__init__(f"{source}: {type(error).__name__}: {error}")
        self.source = source
        self.actions: list[dict[str, Any]] = []  # 本轮中止前已经做过的动作，照常写日志
        self.pr_number: int | None = None


def _github_second(stamp: str) -> int:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp):
        raise EvidenceInsufficient("GitHub 检查时刻不是 UTC 秒")
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())


def human_gated(files: list[str]) -> dict[str, list[str]]:
    """命中人工确认两类的文件，按类别列出；空表示不需要人工确认。"""
    hits: dict[str, list[str]] = {}
    for name in files:
        for category, pattern in HUMAN_GATED.items():
            if pattern.search(name):
                hits.setdefault(category, []).append(name)
    return hits


class GitHubPort(Protocol):
    """GitHub 端口（宿主 gh 凭据）。唯一的写操作是撤销原生 auto-merge。"""
    def open_pulls(self) -> list[dict[str, Any]]: ...
    def committed_at(self, head: str) -> str: ...
    def pr(self, number: int) -> dict[str, Any]: ...
    def review_status(self, number: int, state: dict[str, Any], runs: list[dict],
                      publisher: tuple[int, str]) -> str | None: ...
    def checks(self, number: int, state: dict[str, Any], bindings: dict[str, int | None],
               review_runs: list[dict]) -> dict[str, str]: ...
    def required_checks(self) -> dict[str, int | None]: ...
    def allow_auto_merge(self) -> bool: ...
    def pr_files(self, number: int) -> list[dict[str, Any]]: ...
    def disable_auto_merge(self, number: int) -> None: ...


class InspectedPull(NamedTuple):
    pr: dict[str, Any]
    entry: dict[str, Any]
    report: dict[str, Any]
    can_review: bool
    armed: bool
    withdrawal: dict[str, Any]


class GhCli:
    def __init__(self, repository: str = REPO, timeout: float = GH_TIMEOUT_SECONDS):
        self.repository, self.timeout = repository, timeout
        self._bots: dict[tuple[int, str], str | None] = {}
        self._committed: dict[str, str] = {}

    def committed_at(self, head: str) -> str:
        """head 提交的 committer 时间（ISO 8601）。同一 SHA 的提交不可变，按 SHA 缓存，每个新 head 只读一次接口。"""
        if head not in self._committed:
            self._committed[head] = json.loads(self._gh("api", f"repos/{self.repository}/git/commits/{head}"))[
                "committer"]["date"]
        return self._committed[head]

    def _gh(self, *args: str) -> str:
        try:
            return subprocess.run(["gh", *args], capture_output=True, text=True, check=True,
                                  timeout=self.timeout).stdout
        except subprocess.TimeoutExpired as error:  # 挂住的 gh 不能拖住 serve：按源读不到处理，整轮作废
            target = next((a for a in args if a.startswith("repos/")), " ".join(args[:2]))
            raise SourceUnreadable(f"github ({target.split('?')[0]}) timed out after {self.timeout:g}s", error) from None

    def _json_lines(self, *args: str) -> list[Any]:
        return [json.loads(line) for line in self._gh(*args).splitlines() if line.strip()]

    def _inventory(self, path: str, key: str | None = None, *, capped: bool = False) -> list[dict]:
        """保留分页外层，核计数和唯一 ID；Actions 带查询条件时最多返回 1,000 条。"""
        try:
            pages = json.loads(self._gh("api", "--paginate", "--slurp", path))
            if not isinstance(pages, list) or not pages:
                raise ValueError("缺分页响应")
            items: list[dict] = []
            for page in pages:
                part = page if key is None else page[key]
                if not isinstance(part, list):
                    raise ValueError("分页不是列表")
                items.extend(part)
            if key is not None and any(type(p["total_count"]) is not int or p["total_count"] != len(items) for p in pages):
                raise ValueError("计数与分页不符")
            if capped and len(items) >= 1000:
                raise ValueError("触及 Actions 查询上限")
            ids = [item["id"] for item in items]
            if any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("ID 缺失或重复，分页不完整")
            return items
        except SourceUnreadable:
            raise
        except (subprocess.CalledProcessError, KeyError, TypeError, ValueError) as error:
            raise EvidenceInsufficient(f"读不全 GitHub 分页：{path.split('?')[0]}（{type(error).__name__}）") from error

    def open_pulls(self) -> list[dict[str, Any]]:
        pulls = self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls?state=open&per_page=100",
                                 "--jq", ".[] | @json")
        return list({pr["number"]: pr for pr in pulls}.values())  # 翻页期间变化可能重复，按号码去重

    def pr(self, number: int) -> dict[str, Any]:
        data = json.loads(self._gh("api", f"repos/{self.repository}/pulls/{number}"))
        repository_id = data["base"]["repo"]["id"]
        if (data["number"] != number or data["base"]["ref"] != "main" or data["head"]["repo"]["id"] != repository_id
                or data["state"] != "open" or data["draft"] is not False):
            raise EvidenceInsufficient("PR 不再是同仓、开放且非 draft 的 main 目标")
        head, base = data["head"]["sha"], data["base"]["sha"]
        if not all(re.fullmatch(r"[0-9a-f]{40}", sha or "") for sha in (head, base)):
            raise EvidenceInsufficient("PR 缺完整 base/head SHA")
        return {"head": head, "base": base, "head_ref": data["head"]["ref"], "changed_files": data["changed_files"],
                "mergeable_state": data["mergeable_state"], "auto_merge": data.get("auto_merge", True) is not None,
                "repository_id": repository_id, "pr_id": data["id"], "created_at": data["created_at"]}

    def _bot(self, publisher: tuple[int, str]) -> str | None:
        if publisher not in self._bots:
            app_id, slug = publisher
            self._bots[publisher] = (f"{slug}[bot]"
                                     if json.loads(self._gh("api", f"apps/{slug}")).get("id") == app_id else None)
        return self._bots[publisher]

    def review_status(self, number: int, state: dict[str, Any], runs: list[dict],
                      publisher: tuple[int, str]) -> str | None:
        path = f"repos/{self.repository}/commits/{state['head']}/statuses?per_page=100"
        statuses = self._json_lines("api", "--paginate", path, "--jq", ".[] | @json")
        return self._review_check(number, state, statuses, runs, publisher)

    def _review_check(self, number: int, state: dict[str, Any], statuses: list[dict],
                      review_runs: list[dict], publisher: tuple[int, str] = REVIEW_PUBLISHER) -> str | None:
        frozen = {"pr_number": number, "repository_id": state["repository_id"], "head_sha": state["head"]}
        publications = {
            row["outcome"]["publication"]["id"]: row for row in review_runs
            if (row["outcome"] or {}).get("publication") and row["outcome"].get("verdict") != "STALE"
            and all(row["target"].get(k) == v for k, v in frozen.items())
        }
        group = []
        for item in statuses:
            context = item["context"]
            if not context.isascii() or context.lower() != "deepagents/review":
                continue
            created, updated = (_github_second(item.get(key) or "") for key in ("created_at", "updated_at"))
            if type(item.get("id")) is not int or item["id"] <= 0 or created > updated:
                raise EvidenceInsufficient("正式审查状态缺可比顺序")
            group.append((created, item["id"], item))
        if not group:
            return "superseded" if publications else None
        # 先定序再验作者与发布；任何覆盖都不得回退读取上一条正式状态。
        _, status_id, item = max(group, key=lambda row: row[:2])
        row = publications.get(status_id)
        creator = item.get("creator") or {}
        bot = self._bot(publisher) if row is not None else None
        if row is None or not bot or creator.get("login") != bot or creator.get("type") != "Bot":
            return "superseded" if publications else "pending"
        registered, outcome = row["target"], row["outcome"]
        publication = outcome["publication"]
        match = REVIEW_STATUS.fullmatch(item.get("description") or "")
        base = registered.get("base_sha") or ""
        run_id = registered.get("run_id")
        identity = {**frozen, "base_sha": base, "run_id": run_id}
        reused = outcome.get("reused_from") or {}
        if (not match or (match[1], match[2], match[3], match[4]) != (run_id, base[:12], state["head"][:12], item["state"])
                or outcome.get("run_id") != run_id
                or any((outcome.get("target") or {}).get(k) != v for k, v in identity.items())
                or publication.get("state") != item["state"] or publication.get("sha") != state["head"]
                or publication.get("description") != item["description"] or reused.get("run_id") != match[5]
                or (match[5] is not None and (registered.get("patch_id") or "")[7:19] != match[6])):
            return "superseded"
        if item["state"] in ("failure", "error"):
            return "failure"
        if base == state["base"] and item["state"] == "success" and outcome.get("verdict") == "PASS":
            return "success"
        return "pending"  # 同 PR/head 的合法旧 base 发布仍属于该 PR，不能算当前 base 的通过。

    def _target_history(self, number: int, state: dict[str, Any]) -> None:
        """按同仓 head ref 查全部 PR（包括已关闭）；现算的 run.pull_requests 不能证明历史目标。"""
        repo, ref = self.repository, state["head_ref"]
        owner = repo.split("/")[0]
        prefix = f"repos/{repo}"
        pulls = self._inventory(f"{prefix}/pulls?head={owner}:{quote(ref, safe='')}&state=all&per_page=100")
        targets = [pr for pr in pulls if pr["number"] == number]
        if (len(targets) != 1 or targets[0]["id"] != state["pr_id"]
                or targets[0]["state"] != "open" or targets[0]["draft"] is not False
                or (targets[0]["base"]["sha"], targets[0]["head"]["sha"]) != (state["base"], state["head"])):
            raise EvidenceInsufficient("同源 PR 分页缺目标 PR，或其 base/head 已漂移")
        repository_id = state["repository_id"]
        for pr in pulls:
            if (pr["base"]["ref"] != "main" or pr["base"]["repo"]["id"] != repository_id
                    or pr["head"]["repo"]["id"] != repository_id or pr["head"]["ref"] != ref):
                raise EvidenceInsufficient(f"同源 PR #{pr['number']} 未始终指向本仓 main")
            events = self._inventory(f"{prefix}/issues/{pr['number']}/events?per_page=100")
            if any(event["event"] in BASE_CHANGE_EVENTS for event in events):
                raise EvidenceInsufficient(f"同源 PR #{pr['number']} 有改投目标的历史事件")

    def _run_target(self, number: int, state: dict[str, Any], workflow: str, run: dict) -> bool:
        if run["event"] != "pull_request" or run["path"] != workflow:
            return False
        repository_id = state["repository_id"]
        if run["repository"]["id"] != repository_id or run["head_sha"] != state["head"]:
            raise EvidenceInsufficient("GitHub Actions run 的仓库或 head 不符")
        head_repo = run.get("head_repository") or {}
        if ((head_repo.get("id") is not None and head_repo["id"] != repository_id)
                or (run.get("head_branch") is not None and run["head_branch"] != state["head_ref"])):
            return False  # SHA 可跨分支共享；已证无关的 run 不要求其查询时 PR 关联仍在。
        prs = run["pull_requests"]
        if not prs:
            raise EvidenceInsufficient("GitHub Actions run 缺服务端 PR 关联")
        if not any(pr["id"] == state["pr_id"] or pr["number"] == number for pr in prs):
            return False
        pr = prs[0]
        if (len(prs) != 1 or (pr["id"], pr["number"]) != (state["pr_id"], number)
                or pr["base"]["ref"] != "main" or pr["base"]["sha"] != state["base"]
                or pr["head"]["sha"] != state["head"] or pr["head"]["ref"] != state["head_ref"]
                or run["head_branch"] != state["head_ref"] or run["head_repository"]["id"] != repository_id
                or any(pr[end]["repo"]["id"] != repository_id for end in ("base", "head"))):
            raise EvidenceInsufficient("GitHub Actions run 的 PR、目标或 head 不唯一或不符")
        if _github_second(run["created_at"]) < _github_second(state["created_at"]):
            raise EvidenceInsufficient("GitHub Actions run 早于当前 PR")
        return True

    def _actions_check(self, number: int, state: dict[str, Any], name: str) -> str:
        prefix = f"repos/{self.repository}"
        workflow = WORKFLOWS[name]
        runs = self._inventory(
            f"{prefix}/actions/workflows/{workflow.rsplit('/', 1)[-1]}/runs"
            f"?event=pull_request&head_sha={state['head']}&per_page=100", "workflow_runs", capped=True)
        applicable = [run for run in runs if self._run_target(number, state, workflow, run)]
        if not applicable or any(run["status"] != "completed" for run in applicable):
            return "pending"
        # 重跑不生成新 run；较大的 Check Run ID 不能把较早创建的 run 变成最新 run。
        latest = max(applicable, key=lambda run: (_github_second(run["created_at"]), run["id"]))
        run_id = latest["id"]
        run = json.loads(self._gh("api", f"{prefix}/actions/runs/{run_id}"))
        if (not self._run_target(number, state, workflow, run)
                or any(run[k] != latest[k] for k in ("id", "workflow_id", "check_suite_id", "created_at"))):
            raise EvidenceInsufficient("GitHub Actions run 原件与库存不符")
        attempt = run["run_attempt"]
        if type(attempt) is not int or attempt <= 0:
            raise EvidenceInsufficient("GitHub Actions run 缺有效 attempt")
        if run["status"] != "completed" or attempt != latest["run_attempt"]:
            return "pending"
        if run["conclusion"] != "success" or latest["conclusion"] != "success":
            return "failure"
        jobs = self._inventory(f"{prefix}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100", "jobs")
        matches = [job for job in jobs if job["name"] == name]
        if len(matches) != 1:
            raise EvidenceInsufficient(f"{name} 缺唯一的适用作业")
        job = matches[0]
        link = re.fullmatch(rf"https://api\.github\.com/{re.escape(prefix)}/check-runs/([1-9][0-9]*)",
                            job.get("check_run_url") or "", re.IGNORECASE)
        if (link is None or job["run_id"] != run_id or job["run_attempt"] != attempt
                or job["head_sha"] != state["head"]):
            raise EvidenceInsufficient("GitHub Actions job 与选定 run、attempt 或 head 不符")
        check_id = int(link[1])
        check = json.loads(self._gh("api", f"{prefix}/check-runs/{check_id}"))
        if (check["id"] != check_id or check["name"] != name or check["head_sha"] != state["head"]
                or check["check_suite"]["id"] != run["check_suite_id"]
                or (check.get("app") or {}).get("id") != ACTIONS_APP_ID):
            raise EvidenceInsufficient("GitHub Actions job 与绑定 App 的 Check Run 不符")
        if job["status"] != "completed" or check["status"] != "completed":
            return "pending"
        if job["conclusion"] != "success" or check["conclusion"] != "success":
            return "failure"
        return "success"

    def checks(self, number: int, state: dict[str, Any], bindings: dict[str, int | None],
               review_runs: list[dict]) -> dict[str, str]:
        """只读诊断。Actions 的查询时关联不证明触发身份，结果不能用于签发或合入。"""
        result: dict[str, str] = {}
        if bindings.get("deepagents/review") == REVIEW_APP_ID:
            review = self.review_status(number, state, review_runs, REVIEW_PUBLISHER)
            if review is not None:
                result["deepagents/review"] = review
        if result.get("deepagents/review") == "superseded" or state.get("mergeable_state") == "behind":
            return result  # 覆盖先交对账；旧 base 不查 Actions。
        actions = [name for name in WORKFLOWS if bindings.get(name) == ACTIONS_APP_ID]
        if actions:
            self._target_history(number, state)
        for name in actions:
            result[name] = self._actions_check(number, state, name)
        return result

    def required_checks(self) -> dict[str, int | None]:
        """strict 与 enforce_admins 同开时读取必检；未绑 App 的已配置检查保留键，值为 None。"""
        rules = json.loads(self._gh("api", f"repos/{self.repository}/branches/main/protection"))
        checks = rules.get("required_status_checks") or {}
        if checks.get("strict") is not True or (rules.get("enforce_admins") or {}).get("enabled") is not True:
            return {}
        bindings: dict[str, int | None] = {}
        for check in checks.get("checks", []):
            name, app = check["context"], check.get("app_id")
            bound = app if type(app) is int and app > 0 else None
            bindings[name] = bound if bindings.get(name, bound) == bound else None
        for context in checks.get("contexts", []):
            bindings.setdefault(context, None)
        return bindings

    def allow_auto_merge(self) -> bool:
        """仓库设置：是否允许挂 GitHub 原生 auto-merge。只认明确的 false；字段缺失或不是布尔值都按开着算。"""
        value = json.loads(self._gh("api", f"repos/{self.repository}")).get("allow_auto_merge")
        return value is not False

    def pr_files(self, number: int) -> list[dict[str, Any]]:
        return self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls/{number}/files?per_page=100",
                                "--jq", ".[] | {filename, previous_filename, status, changes} | @json")

    def disable_auto_merge(self, number: int) -> None:
        self._gh("pr", "merge", str(number), "-R", self.repository, "--disable-auto")


def run_review_command(number: int, attempt: int, head: str, private_key: Path) -> list[str]:
    return [sys.executable, "-m", "pilot1742.review_sweep", "run-review", "--pr", str(number),
            "--attempt", str(attempt), "--expect-head", head, "--private-key", str(private_key)]


_REVIEWER = re.compile(r"pilot1742\.(review_sweep run-review|external_review review-pr) --pr (\d+) ")


def reviewer_processes(rows: Rows) -> int:
    """活着（非僵尸）的审查进程数：并发上限按进程数算，同一 PR 的多个 attempt/head 各占一个名额（kimi 审 aa117154）。"""
    return sum(1 for _, _, stat, command in rows if not stat.startswith("Z") and _REVIEWER.search(command + " "))


def reviewing(rows: Rows) -> set[int]:
    """正在审查的 PR 号：活着（非僵尸）的 run-review 或 review-pr 进程，含操作员手动起的 review-pr。"""
    return {int(m.group(2)) for _, _, stat, command in rows if not stat.startswith("Z")
            for m in [_REVIEWER.search(command + " ")] if m}


class Sweep:
    def __init__(self, github: GitHubPort, lane: ExternalReview, spawn: Spawn, *,
                 state_root: Path = STATE_ROOT, max_running: int = 2, rows: Callable[[], Rows] = _ps_rows,
                 sync: Sync | None = None, auto_merge: bool = False, max_age: timedelta = timedelta(hours=24),
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 publisher: Callable[[], tuple[int, str] | None] = configured_publisher):
        self.github, self.lane, self.spawn, self.rows, self.sync = github, lane, spawn, rows, sync
        self.publisher = publisher
        self.folder = state_root / "sweep"
        self._sync_failed = False
        self._backoff: dict[str, Any] | None = None
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

    def launch_order(self, pulls: list[dict[str, Any]], busy: set[int], read_failed: set[int]) -> list[dict[str, Any]]:
        """审查派发的先后（并发上限内谁先拿到名额）。只改先后，不改每个 PR 派不派、怎么审。
        1. 当前 head 能沿用同 patch_id/policy/contract 的已发布 PASS 的（ExternalReview.would_reuse，约 1 分钟、不调模型）；
        2. 其余按 head 提交的 committer 时间从新到旧；
        3. head 提交早于 STALE_PUSH（48 小时）或时间读不到的排最后，组内同样从新到旧。
        同组同时间按 PR 号升序。不进活动窗的 PR 本轮跳过，不读接口，排在末尾；已在审的 PR 不探沿用。
        排在后面的不会被饿死：前面的 PR 已完成、在退避或要操作员处理时都不占名额，名额空着就轮到它。"""
        def key(pr: dict[str, Any]) -> tuple[int, float, int]:
            number = pr["number"]
            try:
                if self._eligible(pr):
                    return 3, 0.0, number
                pushed = datetime.fromisoformat(self.github.committed_at(pr["head"]["sha"]).replace("Z", "+00:00"))
                if number not in busy and self.lane.would_reuse({
                        "repository_id": pr["base"]["repo"]["id"], "pr_number": number,
                        "base_repository_id": pr["base"]["repo"]["id"], "base_ref": pr["base"]["ref"],
                        "base_sha": pr["base"]["sha"], "head_repository_id": pr["head"]["repo"]["id"],
                        "head_ref": pr["head"]["ref"], "head_sha": pr["head"]["sha"]}):
                    return 0, -pushed.timestamp(), number
            except SourceUnreadable as error:
                error.pr_number = number
                raise
            except Exception:  # 排序证据失败不决定派不派，但原生 auto-merge 按未知处理。
                read_failed.add(number)
                return 2, 0.0, number
            return (2 if pushed < self.now() - STALE_PUSH else 1), -pushed.timestamp(), number
        return sorted(pulls, key=key)

    def rate_limit_backoff(self) -> dict[str, Any] | None:
        """限流退避是否生效：按 outcome.json 的写入时间取最近 RATE_LIMIT_RUNS 个已完结且真派过模型的 run（有逐位结论、
        不是 STALE；沿用 run 不调模型，不算），都有 reviewer 回执记 failure_code=rate_limited、且最后一个完结不足
        RATE_LIMIT_BACKOFF_SECONDS 时返回日志行，否则 None。读不了的 run 跳过。"""
        found: list[tuple[float, str, bool]] = []
        stamped: list[tuple[float, Path]] = []
        for path in (self.lane.state_root / "runs").glob("*/outcome.json"):
            try:
                stamped.append((path.stat().st_mtime, path))
            except OSError:
                continue
        for mtime, path in sorted(stamped, reverse=True):
            try:
                outcome = json.loads(path.read_text())
                if outcome.get("verdict") not in ("PASS", "BLOCK", "FAILED") or not outcome.get("reviews"):
                    continue
                limited = False
                for receipt in path.parent.glob("*/receipt.json"):
                    try:
                        limited = limited or json.loads(receipt.read_text()).get("failure_code") == "rate_limited"
                    except (OSError, ValueError, AttributeError):
                        continue
            except (OSError, ValueError, AttributeError):
                continue
            found.append((mtime, str(outcome.get("run_id")), limited))
            if len(found) == RATE_LIMIT_RUNS:
                break
        if len(found) < RATE_LIMIT_RUNS or not all(limited for _, _, limited in found):
            return None
        until = found[0][0] + RATE_LIMIT_BACKOFF_SECONDS
        if self.now().timestamp() >= until:
            return None
        return {"action": "rate-limit-backoff", "runs": [run for _, run, _ in found],
                "until": datetime.fromtimestamp(until, timezone.utc).isoformat()}

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

    def decide(self, pr: dict[str, Any], busy: set[int], running: int) -> tuple[str, dict | None]:
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
        if self._backoff is not None:  # 限流退避：不派新审查（含续跑审查），本轮汇总一行日志
            return "review-backoff", None
        if not self._has_commits(base, head):
            if self.sync is None:
                return "needs-source-sync", None
            source = f"git fetch {REPO} main pull/{number}/head"
            if self._sync_failed:  # 一轮里 fetch 失败过就不再试，免得超时逐个累加
                return "source-unreadable", {"unreadable": source, "reason": "本轮 fetch 已失败过，下轮再试"}
            try:
                self.sync(number, base, head)
            except Exception as error:  # 读不到对象：不派审、不算通过，写明读不到哪个源
                self._sync_failed = True
                detail = getattr(error, "stderr", b"") or b""
                detail = detail.decode(errors="replace") if isinstance(detail, bytes) else str(detail)
                return "source-unreadable", {"unreadable": source,
                                             "reason": f"{type(error).__name__}: {detail.strip()[:200] or error}"}
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
        actions: list[dict[str, Any]] = []
        if self.auto_merge:
            actions.append({"action": "auto-merge-disabled-pre-cutover",
                            "reason": "切换前停用自动合入与追平；#2131 R09 冻结、排空、发布互斥及触发时 PR 归属上线后，合入只走统一入口"})
        try:
            all_pulls = sorted(self.open_pulls(), key=lambda pr: pr["number"])
        except Exception as error:
            failure = SourceUnreadable("github open pulls", error)
            failure.actions = actions
            raise failure from error
        remaining = {pr["number"]: pr for pr in all_pulls}
        self._sync_failed = False
        timeout_in_withdrawal = False
        affected: int | None = None
        withdrawals: dict[int, dict[str, Any]] = {}
        inspected: list[InspectedPull] = []

        def withdrawal_reports() -> list[dict[str, Any]]:
            return [{"pr": pr["number"], "head": pr["head"]["sha"], "action": "native-auto-merge-withdrawal",
                     **withdrawals[pr["number"]]} for pr in all_pulls if pr["number"] in withdrawals]

        def withdraw(entry: dict[str, Any], report: dict[str, Any], armed: bool) -> dict[str, Any]:
            nonlocal timeout_in_withdrawal
            try:
                return self._withdraw(entry["pr"], armed)
            except SourceUnreadable as error:
                timeout_in_withdrawal = True
                actions.append({**entry, **report, "auto_merge_withdrawn": False, "withdraw_error": str(error)})
                raise

        try:
            native = self._native_enabled(actions)
            # 先处理全仓挂载（包括 draft、外仓及非 main PR）；缺字段不等于未挂载。
            for pr in sorted(all_pulls, key=lambda pr: "auto_merge" not in pr):
                if pr.get("auto_merge", True) is not None:
                    number = pr["number"]
                    entry = {"pr": number, "head": pr["head"]["sha"]}
                    withdrawals[number] = withdraw(entry, {"action": "native-auto-merge-withdrawal"}, True)

            if native:
                return actions + withdrawal_reports()
            pulls = [pr for pr in all_pulls if pr["base"]["ref"] == "main"]
            remaining = {pr["number"]: pr for pr in pulls}
            try:
                rows = self.rows()
            except Exception as error:
                raise SourceUnreadable("host process table", error) from error
            busy, running = reviewing(rows), reviewer_processes(rows)
            self._backoff = self.rate_limit_backoff()
            held: list[int] = []
            publisher = self.publisher()
            bindings, protection_unreadable = self._diagnostic_bindings(
                actions, publisher) if self.auto_merge else ({}, False)
            read_failed: set[int] = set()
            for pr in self.launch_order(pulls, busy, read_failed):
                number, head = pr["number"], pr["head"]["sha"]
                entry = {"pr": number, "head": head}
                affected = number
                mounted = number in withdrawals
                armed = protection_unreadable or number in read_failed
                try:
                    skip = self._eligible(pr)
                    if skip:
                        report: dict[str, Any] = {"action": skip}
                    else:
                        state = self.github.pr(number)
                        mounted = mounted or state.get("auto_merge") is not False
                        report = self._inspect(pr, state, bindings, publisher)
                        mounted = report.pop("mounted", False) or mounted
                        armed = report.pop("armed") or armed
                except SourceUnreadable:
                    raise
                except Exception as error:
                    armed = True
                    kind = "evidence-insufficient" if isinstance(error, EvidenceInsufficient) else "error"
                    report = {"action": kind, "reason": str(error)}
                can_review = report.pop("can_review", report["action"] in (
                    "check-report", "review-inspected", "needs-human-confirm"))
                armed = mounted or armed
                if number in withdrawals:
                    withdrawal = withdrawals.pop(number)
                else:
                    withdrawal = withdraw(entry, report, armed)
                inspected.append(InspectedPull(pr, entry, report, can_review and not mounted, armed, withdrawal))
                remaining.pop(number)
        except SourceUnreadable as error:
            actions.extend({**entry, **report, **withdrawal} for _, entry, report, _, _, withdrawal in inspected
                           if report["action"] != "review-inspected" or withdrawal)
            actions.extend(withdrawal_reports())
            actions.extend(error.actions)
            if not timeout_in_withdrawal:
                # 初读未挂载不排除超时后的挂载；本轮已成功撤除的无需重复调用。
                self._fail_closed({n: pr for n, pr in remaining.items()
                                   if not withdrawals.get(n, {}).get("auto_merge_withdrawn")},
                                  actions, error.pr_number or affected)
            error.actions = actions
            raise
        actions.extend(withdrawal_reports())  # 非 main PR 只撤销，不进入诊断或派审。
        # 完成所有 PR 的检查及撤销后才派审／续发；撤过挂载的 PR 要等下一轮确认。
        for pr, entry, report, can_review, armed, withdrawal in inspected:
            number = entry["pr"]
            try:
                if can_review and withdrawal.get("auto_merge_withdrawn") is not False:
                    try:
                        action, details = self.decide(pr, busy, running)
                    except SourceUnreadable:
                        raise
                    except Exception as error:
                        action, details = "error", {"reason": f"{type(error).__name__}: {error}"}
                    if action == "review-backoff":
                        held.append(number)
                    running += action in ("launch", "resume-review", "resume-publish")
                    actions.append({**entry, "action": action, **(details or {})})
                    if action in ("error", "source-unreadable") and not armed:
                        withdrawal = withdraw(entry, report, True)
                if report["action"] != "review-inspected" or withdrawal:
                    actions.append({**entry, **report, **withdrawal})
            except SourceUnreadable as error:
                if not timeout_in_withdrawal:
                    self._fail_closed({number: pr}, actions, number)
                error.actions = actions
                raise
        if self._backoff is not None:
            actions.append({**self._backoff, "held": held})
        return actions

    def _native_enabled(self, actions: list[dict[str, Any]]) -> bool:
        try:
            native = self.github.allow_auto_merge() is not False
            reason = "仓库允许原生 auto-merge 或设置未知"
        except SourceUnreadable as error:
            actions.append({"action": "native-auto-merge-enabled", "reason": str(error)})
            raise
        except Exception as error:
            native, reason = True, f"读取仓库设置 allow_auto_merge 失败：{type(error).__name__}: {error}"
        if native:
            actions.append({"action": "native-auto-merge-enabled", "reason": reason})
        return native

    def _diagnostic_bindings(self, actions: list[dict[str, Any]],
                             publisher: tuple[int, str] | None) -> tuple[dict[str, int | None], bool]:
        try:
            bindings, unsafe = self._merge_bindings(publisher)
        except SourceUnreadable:
            raise
        except Exception as error:
            actions.append({"action": "evidence-insufficient", "reason": f"读取 main 必需检查失败：{error}"})
            return {}, True
        if unsafe:
            actions.append({"action": "merge-protection-mismatch", "reason": unsafe})
        return bindings, False

    def _review_binding_unsafe(self, bound: int | None, publisher: tuple[int, str] | None) -> str | None:
        """必需检查 deepagents/review 须绑定审查专用 App（IDENTITY_CONFIG 配的那个），且它不是执行器 App。
        绑定执行器 App 时，其交付自写的 success 就能冒充正式双审。"""
        reviewer = publisher[0] if publisher else None
        if bound == EXECUTOR_APP_ID:
            return f"必需检查 deepagents/review 绑定执行器 App {bound}：执行器交付时自写的 success 会被当成正式审查，不合入"
        if reviewer == EXECUTOR_APP_ID:
            return f"正式审查使用执行器 App {reviewer} 回退身份，只可对账；合入门要求专用审查 App {REVIEW_APP_ID}"
        if bound != REVIEW_APP_ID or bound != reviewer:
            return (f"必需检查 deepagents/review 绑定 App {bound}，与审查身份文件配的审查 App {reviewer} 不符"
                    "（或身份文件缺失、读不了），不合入")
        return None

    def _merge_bindings(self, publisher: tuple[int, str] | None) -> tuple[dict[str, int | None], str | None]:
        required = self.github.required_checks()
        missing = GATE - required.keys()
        unsafe = self._review_binding_unsafe(required.get("deepagents/review"), publisher)
        if unsafe:
            required.pop("deepagents/review", None)
        if missing:
            return required, f"main 须 strict、enforce_admins 且必检齐全；缺 {sorted(missing)}"
        if unsafe is None and any(required[name] != ACTIONS_APP_ID for name in WORKFLOWS):
            unsafe = "ci-ok 与 DevSkim 均须绑定 GitHub Actions App 15368"
        return required, unsafe

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

    def _inspect(self, pr: dict[str, Any], state: dict[str, Any],
                 bindings: dict[str, int | None], publisher: tuple[int, str] | None) -> dict[str, Any]:
        """核当前身份、人工确认类别与正式发布。诊断不产生合入或追平计划。"""
        number, head, base = pr["number"], pr["head"]["sha"], pr["base"]["sha"]
        if state["head"] != head:
            return {"action": "head-moved", "now": state["head"], "armed": True}
        if state["base"] != base:
            return {"action": "base-moved", "armed": True}
        mounted = state.get("auto_merge") is not False
        runs = self.lane.status(number)
        # 对账按实际发布者，独立于保护绑定和文件分类。
        published = any(row["target"].get("head_sha") == head and (row["outcome"] or {}).get("publication")
                        and row["outcome"].get("verdict") != "STALE" for row in runs)
        if published and publisher is None:
            raise EvidenceInsufficient("无法识别正式审查的发布身份")
        try:
            review = self.github.review_status(number, state, runs, publisher) if published and publisher else None
        except SourceUnreadable:
            raise
        except Exception as error:
            raise EvidenceInsufficient(f"读取 {head[:12]} 的正式发布失败：{error}") from error
        reconcile = {"action": "needs-reconcile", "review": "superseded", "queue_head": False, "armed": True,
                     "reason": "正式状态已被取代，须核对后为当前 PR/base/head 重新审查"}
        try:
            files = self.complete_files(number, state)
        except SourceUnreadable as error:
            if review == "superseded":
                error.actions.append({"pr": number, "head": head, **reconcile, "file_evidence_error": str(error)})
            raise
        except Exception as error:
            if review == "superseded":
                return {**reconcile, "file_evidence_error": str(error)}
            return {"action": "evidence-insufficient", "reason": str(error), "armed": True,
                    "can_review": isinstance(error, EvidenceInsufficient)}
        try:
            again = self.github.pr(number)
        except SourceUnreadable:
            raise
        except Exception as error:
            raise EvidenceInsufficient(f"复核 head 失败：{error}") from error
        if again["head"] != head:
            return {"action": "head-moved", "classified": head, "now": again["head"], "armed": True}
        if again["base"] != base:
            return {"action": "base-moved", "armed": True}
        if again["changed_files"] != state["changed_files"]:
            raise EvidenceInsufficient("复核时改动文件数变化")
        mounted = mounted or again.get("auto_merge") is not False
        gated = human_gated(files)
        if review == "superseded":
            return reconcile
        if gated:
            return {"action": "needs-human-confirm", "gated": gated, "armed": True, "mounted": mounted}
        if self.auto_merge:
            try:
                # 已对账的结果只有来自专用 App 且保护绑定正确时才可出现在三门诊断。
                diagnostic = {k: v for k, v in bindings.items() if k != "deepagents/review" or not published}
                checks = self.github.checks(number, again, diagnostic, runs)
                if published and review is not None and "deepagents/review" in bindings:
                    checks["deepagents/review"] = review
            except SourceUnreadable:
                raise
            except Exception as error:
                return {"action": "evidence-insufficient", "reason": f"读取 {head[:12]} 的检查失败：{error}",
                        "armed": True, "can_review": True, "mounted": mounted}
            return {"action": "check-report", "checks": {name: checks.get(name) for name in MERGE_CHECKS},
                    "mergeable_state": again["mergeable_state"], "scope": "diagnostic-only",
                    "armed": mounted, "mounted": mounted}
        return {"action": "review-inspected", "armed": mounted, "mounted": mounted}

    def _withdraw(self, number: int, armed: bool) -> dict[str, Any]:
        if not armed:
            return {}
        try:
            self.github.disable_auto_merge(number)
        except SourceUnreadable:
            raise
        except Exception as error:
            return {"auto_merge_withdrawn": False, "withdraw_error": f"{type(error).__name__}: {error}"}
        return {"auto_merge_withdrawn": True}

    def _fail_closed(self, remaining: dict[int, dict[str, Any]], actions: list[dict[str, Any]],
                     affected: int | None) -> None:
        for number in sorted(remaining, key=lambda n: (
                n != affected, remaining[n].get("auto_merge", True) is None, "auto_merge" not in remaining[n], n)):
            pr = remaining[number]
            entry = {"pr": number, "head": pr["head"]["sha"], "action": "fail-closed-withdraw"}
            try:
                actions.append({**entry, **self._withdraw(number, True)})
            except SourceUnreadable as error:
                actions.append({**entry, "auto_merge_withdrawn": False, "withdraw_error": str(error)})
                actions.append({"action": "fail-closed-aborted", "reason": "撤销也超时，余下的下轮再撤"})
                break


def report(actions: list[dict[str, Any]], prefix: str = "") -> None:
    """每个动作一行 JSON；无动作的状态不写，但同条的撤销结果必须留存。"""
    for action in actions:
        if action.get("action") not in QUIET or "auto_merge_withdrawn" in action:
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
            report([*error.actions, {"action": "round-skipped", "unreadable": error.source, "reason": str(error)}],
                   "review-sweep ")
            return None
        except Exception as error:
            report([{"action": "tick-error", "reason": f"{type(error).__name__}: {error}"}], "review-sweep ")
            return None
        report(actions, "review-sweep ")
        return actions


FETCH_CREDENTIAL = ("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")


def fetch_command(source: Path, url: str, number: int) -> list[str]:
    # 先清空再只挂 gh 自己的凭据助手：与 sweep 其余 GitHub 读写同一份宿主 gh 登录。仓库私有时也能取；
    # 本进程不读、不打印 token（由 gh 直接交给 git），也不引入新的密钥。
    return ["git", "-c", "core.hooksPath=/dev/null", *FETCH_CREDENTIAL, "-C", str(source), "fetch", "--no-tags",
            "--quiet", url, "main", f"pull/{number}/head"]


def fetch_environment() -> dict[str, str]:
    """external_review 的 git 环境（关全局/系统配置、不弹终端提示），外加 gh 找到自己登录状态所需的 HOME 与 GH_CONFIG_DIR。"""
    env = git_environment()
    env.update({k: os.environ[k] for k in ("HOME", "GH_CONFIG_DIR") if k in os.environ})
    return env


def fetcher(source: Path, url: str = f"https://github.com/{REPO}.git") -> Sync:
    """sweep 的 sync：把 main 与 PR head 取进宿主对象库，只写 FETCH_HEAD，不动 HEAD、分支与工作区（controller
    身份不变）。认证走宿主 gh 的凭据助手（见 fetch_command）；失败由 decide 记 source-unreadable。"""
    def sync(number: int, base: str, head: str) -> None:
        subprocess.run(fetch_command(source, url, number), env=fetch_environment(), check=True, capture_output=True,
                       timeout=FETCH_TIMEOUT_SECONDS)
    return sync


def serve_round(private_key: Path, *, auto_merge: bool = False, max_running: int = 1) -> ServeRound:
    """executor serve 用的钩子。max_running 默认 1：HOST 上同时在跑的审查不超过它，操作员手动起的 review-pr 也算
    （reviewing）。同一 PR 有活进程就不再派（decide 的 running）；各审查子进程照常各自过空间与额度准入。
    风险：两道准入都按单个 run 算，不是总量。空间准入只看本 run 的快照，不给同时在跑、还没铺开快照的 run 预留；
    额度准入只统计已结束 run 的回执。上限 N 时最多 N 个 run（每个 2 个模型）同时铺快照、同时耗额度，
    可能集体超占外盘或超出每日上限。调高 N 前先查外盘剩余空间（df -h /Volumes/AgentStorage）。"""
    lane = ExternalReview(None)
    return ServeRound(Sweep(GhCli(), lane, spawner(private_key), max_running=max_running, auto_merge=auto_merge,
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
                        help="旧参数，仅开启只读检查与分类诊断；不合入、不追平")
    args = parser.parse_args(argv)
    if not math.isfinite(args.loop) or not (args.loop == 0 or args.loop >= MIN_LOOP_SECONDS):  # 挡住负数、nan、inf
        parser.error(f"--loop 须为 0 或至少 {MIN_LOOP_SECONDS:g} 秒")
    sweep = Sweep(GhCli(), ExternalReview(None), spawner(args.private_key), max_running=args.max_running,
                  auto_merge=args.auto_merge)
    while True:
        try:
            report(sweep.tick())
        except SourceUnreadable as error:  # 与 ServeRound 一致：本轮已做的动作照常写日志
            report([*error.actions, {"action": "round-skipped", "unreadable": error.source, "reason": str(error)}])
        except Exception:  # 整轮失败（例如列 PR 失败）：记下，下轮重试，不退出
            print(json.dumps({"action": "tick-error", "reason": traceback.format_exc(limit=3)}, ensure_ascii=False),
                  flush=True)
        if args.loop <= 0:
            return 0
        time.sleep(args.loop)


if __name__ == "__main__":
    raise SystemExit(main())
