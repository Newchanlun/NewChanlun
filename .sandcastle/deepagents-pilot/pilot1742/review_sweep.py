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
派发先后（launch_order，并发上限内谁先拿名额）：能沿用已发布 PASS 的 head 先，其余按 head 提交的 committer 时间从新到旧，
head 提交早于 48 小时的垫底；只改先后，不改派不派。合入、追平与兜底撤销仍按 PR 号。
限流退避：最近 2 个已完结的审查 run 都有 reviewer 以 failure_code=rate_limited 失败时，30 分钟内不派新审查
（launch、resume-review），每轮记一行 rate-limit-backoff；发布续跑、追平、合入与撤原生 auto-merge 照常。
派发的子进程绑定决策时的 head：先核对 PR 仍是这个 head，不是就不审（run-review --expect-head）。
启用合入时，strict 下落后的 PR 先追平、再审新 head（不审一个合入前必然被替换的 head）。
发起前 base、head 提交须已在宿主对象库（EXTERNAL-REVIEW.md：入口和 reviewer 都不 fetch）；缺失时调用 owner 注入的
sync(number, base, head)，未注入报 needs-source-sync。

合入（--auto-merge，用宿主 gh 凭据；本模块不构造 App 身份，审查身份归 external_review）：不预先挂 auto-merge；
依据 #1742 用户常驻授权（https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631）与 #1909 裁定，
因 GitHub REST/GraphQL 合入与追平接口均不支持服务端 `expected_base_ref` 绑定（读后写前若 PR 改指同仓非 main 分支，本机锁无法阻止远端改指），
#2207 正式关闭无人值守循环内自动发起 `PUT /pulls/{n}/merge` 与 `PUT /pulls/{n}/update-branch`，改为每轮核验全部准入条件
（分支保护 strict/enforce_admins/禁止强推删分支、必需检查绑定审查专用 App、仓库 allow_auto_merge=false、精确 head 三项检查全绿、
已发布 PASS 且无在途/待完成重审意图、改动清单不触及人工确认两类）并将结果原子持久化到 `STATE_ROOT/sweep/merge-handoff.json`
（区分普通门禁全绿的 `ready_for_merge`、队首落后需追平的 `behind_queue_head` 与敏感两类 `human_confirm`；日志仍兼容输出
`needs-human-confirm` 与 `behind-waiting`），同时对任意挂着 GitHub 原生 auto-merge 的 PR 无条件撤掉原生 auto-merge（`disable_auto_merge`）。
接手方为获常驻合入授权的主控巡航（`/graph-run` 与主图编排会话）或维护者，先通过 `python -m pilot1742.review_sweep --handoff`
查看交接队列，再通过显式接手入口 `python -m pilot1742.review_sweep handoff-update-branch --pr N --expect-base <base> --expect-head <head>`
与 `python -m pilot1742.review_sweep handoff-merge --pr N --expect-base <base> --expect-head <head>` 执行追平与非敏感 PR 合入；
显式接手入口持同一把本机排他重审锁（`p{N}.inflight.lock` + `p{N}.lock`）直至 GitHub 写操作完成，持锁期间实时复核远端 `base_ref=main`、
精确 `(base, head)` SHA、`mergeable_state`、非敏感文件清单、分支保护与必需检查以及当前合同已发布 PASS（无待完成重审意图）。
两类的出处：用户裁定留痕 https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631
仓库设置 allow_auto_merge 已关（GET /repos/{owner}/{repo} 的 allow_auto_merge=false，2026-11-09 由主控关闭），
GitHub 原生 auto-merge 根本挂不上；sweep 每轮读这个设置：为 true 或读不到时记 native-auto-merge-enabled，并照常对所有挂着原生 auto-merge 的 PR 执行撤回。
该模式在代码里默认关；只给 --review-sweep 时只派审。关掉的方法见 EXECUTOR.md「附带正式审查」。
完整清单：files 接口最多 3000 个且需与 changed_files 相符；否则用本地精确 diff；两者都拿不到报 evidence-insufficient
（下轮重试），不合入，也不升级成人工确认。
触及两类的报 needs-human-confirm，不合入、不追平；这类 PR 上若挂着 GitHub 原生 auto-merge 会撤掉。
证据不全一律按失败关闭（fail closed）：该 PR 的状态、文件清单或检查读不到，main 的必需检查读不到，或处理中出任何异常，
都不合入、不追平，并撤掉它的原生 auto-merge（状态读不到、不知道挂没挂时也撤）——否则一个读失败的敏感 PR
会靠原生 auto-merge 在检查转绿后绕过 HUMAN_GATED。
合入阶段分两段：先把所有 PR 的证据读完、定好动作，再按序执行写（合入、追平、撤 auto-merge）。
每个 gh 调用都有 GH_TIMEOUT_SECONDS 上限；超时按输入源读不到处理（SourceUnreadable），整轮作废、下轮重试，
读阶段最多卡一个超时；之后 fail_closed 撤 auto-merge 时最多再卡一个，补对象的 fetch 另有自己的上限，
所以一轮的耗时有界，不会无限期拖住 executor serve 的派票循环。
检查结论绑定发布来源：必需检查只认 main 分支保护为它绑定的 app_id（status 按该 App 的 bot 账号、check run 按
app.id），DevSkim 不是必需检查，只认 GitHub Actions（GATED_APP_IDS）；同名但出自别的 App 的结论一律不算。
分支保护须 strict 与 enforce_admins 都开、两项必需检查都绑定了 app，否则本轮不合入、不追平。
分类绑定到读到的那个 head SHA：文件清单接口不按 SHA 取，所以读完清单后再读一次 PR，head 未变才算数；开放 PR 列表、
实时状态与复核三者的 head 有任何不一致都报 head-moved，不合入、不追平，并撤掉原生 auto-merge（新 head 没分类过）。
写操作里合入带 sha、追平带 expected_head_sha，由 GitHub 服务端拒绝 head 不符；撤 auto-merge 的接口不收 SHA，
它只会让 PR 更难合入，任何 head 上撤都安全。
补对象的 fetch 失败（网络、超时、无权限）记 source-unreadable 并写明读不到的源，这个 PR 本轮不派审、不算通过，
也不占队首。读阶段超时发生在任何写之前，本轮一个 PR 也不合入、
不追平；随后对每个本轮没能确认不触及两类、又挂着（或不知道挂没挂）原生 auto-merge 的 PR 尽力撤掉（fail_closed），
撤销本身也超时就停下、下轮再撤。写本身超时记 write-unknown，余下的写不做。本轮中止前已做的动作随异常带出，照常写日志。补对象的 fetch 另有 FETCH_TIMEOUT_SECONDS，
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
import fcntl
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .delivery import EffectPending
from .external_review import (
    DEFAULT_IDENTITY,
    IDENTITY_CONFIG,
    MODELS,
    POLICY,
    PREFLIGHT_ADMITTED_FILE,
    PREFLIGHT_RATE_LIMIT_FILE,
    QUOTA_PAUSED_FILE,
    REVIEW_CONTRACT,
    STATE_ROOT,
    ExternalReview,
    _git,
    git_environment,
)
from .run import _ps_rows
from .workunit import REPO

Rows = list[tuple[int, int, str, str]]
Spawn = Callable[[int, int, str, Path, str | None], int]
Sync = Callable[[int, str, str], None]
GATE = frozenset({"deepagents/review", "ci-ok"})
LAUNCH_BACKOFF_SECONDS = 600
# 限流退避：最近 RATE_LIMIT_RUNS 个已完结的审查 run 都有 reviewer 以 failure_code=rate_limited 失败时，自最后一个完结起
# RATE_LIMIT_BACKOFF_SECONDS 内不派新审查（不派 launch、不续跑 resume-review）；发布续跑、合入、撤 auto-merge 照常。
RATE_LIMIT_RUNS = 2
RATE_LIMIT_BACKOFF_SECONDS = 1800
MIN_LOOP_SECONDS = 180
# 派发先后：head 提交早于这么久的 PR 排在最后（只在没有更新的 PR 等着时才轮到）。
STALE_PUSH = timedelta(hours=48)
MERGE_CHECKS = ("deepagents/review", "ci-ok", "DevSkim")
FILES_CAP = 3000
FETCH_TIMEOUT_SECONDS = 120
# 不在分支保护里、但合入前也要看的检查：只认这里登记的来源 App（DevSkim 由 GitHub Actions 跑）。
GATED_APP_IDS = {"DevSkim": 15368}
# 发 commit status 的 App 在接口里只露出 bot 账号，不露 app_id：按已知 slug 求 bot 账号，并用 GET /apps/{slug}
# 现场核对 id；不在表里的 App 发的 status 一律不算（失败关闭）。
APP_SLUGS = {5486877: "newchanlun-deepagents-1742", 5664795: "newchanlun-review-gate", 15368: "github-actions"}
GH_TIMEOUT_SECONDS = 60
MERGE_HANDOFF_FILE = "merge-handoff.json"
MERGE_HANDOFF_SCHEMA = "review-sweep-merge-handoff-v1"
# 交接快照有效期：至多容忍 3 轮 serve 间隔，超过即视为过期并在读取端拒绝。
MERGE_HANDOFF_MAX_AGE_SECONDS = MIN_LOOP_SECONDS * 3
# 执行器 App：交付时在冻结 head 上自写 deepagents/review=success（作者侧独审，不是正式非作者双审）。
EXECUTOR_APP_ID = DEFAULT_IDENTITY["app_id"]


def configured_review_app(config: Path = IDENTITY_CONFIG) -> int | None:
    """审查专用 App 的 app_id（external_review.IDENTITY_CONFIG，非秘密 JSON）。文件不存在时审查沿用执行器 App，
    读不了或字段不对时不知道是谁：都返回 None，合入按不安全处理。"""
    try:
        app_id = json.loads(config.read_text(encoding="utf-8")).get("app_id")
    except (OSError, ValueError, AttributeError):
        return None
    return app_id if type(app_id) is int and app_id > 0 else None

# 人工确认只剩两类：实盘下单或资金、密钥或凭证。出处：用户 2026-11-07、2026-11-08 的裁定，原话留痕在
#   https://github.com/Newchanlun/NewChanlun/issues/1742#issuecomment-6719202631
# CI 与分支保护配置（workflows、actions、DevSkim 门脚本、基线与误报清单）不再交人工确认。已接受的风险：改 CI 的 PR
# 在自己的合并 ref 上运行自己定义的 ci-ok 与 DevSkim，必需检查的 app 绑定挡不住它把这两项改成恒成功或放宽扫描准入，
# 所以对这类 PR 只剩精确 head 上的双模型非作者独审（deepagents/review）。审查提示词（external_review.PROMPT）是通用
# 审阅提示，没有专门要求拦截放宽必需检查或 DevSkim 基线的改动；原来按内容判基线放宽的检测随 CI 类一起删掉，没有替代。
# 这是接受的风险，不是已实现的缓解：要补，须改审查提示词（会改变 REVIEW_CONTRACT，旧结论不能沿用），不在本模块。
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
STUCK_REVIEW = frozenset({
    "needs-operator",
    "needs-reconcile",
    "needs-source-sync",
    "source-unreadable",
    "rereview-pending",
    "base-ref-moved",
    "error",
})
# 没有动作的状态，不写日志。review-backoff 由本轮一行 rate-limit-backoff 汇总，不逐个 PR 记。
QUIET = frozenset({"done", "draft", "stale-pr", "review-backoff"})


class EvidenceInsufficient(RuntimeError):
    """证据不足：清单、检查或必需检查读不全。不合入、不追平、撤掉原生 auto-merge，不升级成人工确认；下轮重试。"""


class SourceUnreadable(RuntimeError):
    """整轮的输入源读不到。本轮不派审、不追平、不合入，下轮重试；source 写明是哪个源。"""

    def __init__(self, source: str, error: BaseException):
        super().__init__(f"{source}: {type(error).__name__}: {error}")
        self.source = source
        self.actions: list[dict[str, Any]] = []  # 本轮中止前已经做过的动作，照常写日志


class HandoffBlocked(RuntimeError):
    """显式交接执行入口（handoff-merge / handoff-update-branch）实时复核未通过或被本机重审锁阻断。"""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


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
    def committed_at(self, head: str) -> str: ...
    def pr(self, number: int) -> dict[str, Any]: ...
    def checks(self, head: str, bindings: dict[str, int]) -> dict[str, str]: ...
    def required_checks(self) -> dict[str, int]: ...
    def allow_auto_merge(self) -> bool: ...
    def pr_files(self, number: int) -> list[dict[str, Any]]: ...
    def disable_auto_merge(self, number: int) -> None: ...


class HandoffGitHubPort(GitHubPort, Protocol):
    """仅显式交接执行入口（handoff-merge / handoff-update-branch）使用的 GitHub 写端口；无人值守 Sweep 不可调用。"""
    def merge(self, number: int, head: str) -> dict[str, Any]: ...
    def update_branch(self, number: int, head: str) -> dict[str, Any]: ...


class GhCli:
    def __init__(self, repository: str = REPO, timeout: float = GH_TIMEOUT_SECONDS):
        self.repository, self.timeout = repository, timeout
        self._bots: dict[int, str | None] = {}
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

    def open_pulls(self) -> list[dict[str, Any]]:
        pulls = self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls?state=open&base=main&per_page=100",
                                 "--jq", ".[] | @json")
        return list({pr["number"]: pr for pr in pulls}.values())  # 翻页期间变化可能重复，按号码去重

    def pr(self, number: int) -> dict[str, Any]:
        data = json.loads(self._gh("api", f"repos/{self.repository}/pulls/{number}"))
        base_repo = data["base"].get("repo") or {}
        head_repo = data["head"].get("repo") or {}
        return {
            "head": data["head"]["sha"],
            "base": data["base"]["sha"],
            "base_ref": data["base"]["ref"],
            "base_repo_id": base_repo.get("id"),
            "head_repo_id": head_repo.get("id"),
            "state": data.get("state", "open"),
            "draft": bool(data.get("draft", False)),
            "changed_files": data["changed_files"],
            "mergeable_state": data["mergeable_state"],
            "auto_merge": data["auto_merge"] is not None,
        }

    def _bot(self, app_id: int) -> str | None:
        """App 发 commit status 时用的 bot 账号；slug 不在表里或 GET /apps/{slug} 的 id 对不上时返回 None。"""
        if app_id not in self._bots:
            slug = APP_SLUGS.get(app_id)
            self._bots[app_id] = (f"{slug}[bot]" if slug is not None
                                  and json.loads(self._gh("api", f"apps/{slug}")).get("id") == app_id else None)
        return self._bots[app_id]

    def checks(self, head: str, bindings: dict[str, int]) -> dict[str, str]:
        """该 head 上每个受绑定检查名的最新结论（success / failure / pending），只认 bindings 给出的来源 App；
        同名但出自别的 App 的 status 或 check run 不算，没有绑定 App 的结论就当没有。"""
        result: dict[str, str] = {}
        statuses = self._json_lines("api", "--paginate", f"repos/{self.repository}/commits/{head}/statuses?per_page=100",
                                    "--jq", ".[] | @json")
        for item in statuses:  # 列表接口新的在前：每个名字只取绑定 App 发的最新一条
            name = item["context"]
            if name in bindings and name not in result and \
                    (item.get("creator") or {}).get("login") == self._bot(bindings[name]):
                result[name] = {"success": "success", "pending": "pending"}.get(item["state"], "failure")
        runs = self._json_lines("api", "--paginate", f"repos/{self.repository}/commits/{head}/check-runs?per_page=100",
                                "--jq", ".check_runs[] | @json")
        for run in sorted(runs, key=lambda r: (r.get("started_at") or "", r["id"])):  # 重跑时后者覆盖前者
            if run["name"] not in bindings or (run.get("app") or {}).get("id") != bindings[run["name"]]:
                continue
            result[run["name"]] = ("pending" if run["status"] != "completed" else
                                   "success" if run["conclusion"] in ("success", "skipped", "neutral") else "failure")
        return result

    def required_checks(self) -> dict[str, int]:
        """main 上可信的必需检查及其绑定的来源 app_id。strict（要求 PR 先与 base 追平）、enforce_admins、
        禁止强推（allow_force_pushes=false）与禁止删分支（allow_deletions=false）任一不满足就一个都不算：
        它们共同保证 GitHub 服务端在合入时只允许 main 单调前进到 head 的祖先。没绑定来源 app 的检查也不算。"""
        rules = json.loads(self._gh("api", f"repos/{self.repository}/branches/main/protection"))
        checks = rules.get("required_status_checks") or {}
        if (checks.get("strict") is not True
                or (rules.get("enforce_admins") or {}).get("enabled") is not True
                or (rules.get("allow_force_pushes") or {}).get("enabled") is not False
                or (rules.get("allow_deletions") or {}).get("enabled") is not False):
            return {}
        return {c["context"]: c["app_id"] for c in checks.get("checks", [])
                if type(c.get("app_id")) is int and c["app_id"] > 0}  # bool 是 int 的子类，排除

    def allow_auto_merge(self) -> bool:
        """仓库设置：是否允许挂 GitHub 原生 auto-merge。只认明确的 false；字段缺失或不是布尔值都按开着算。"""
        value = json.loads(self._gh("api", f"repos/{self.repository}")).get("allow_auto_merge")
        return value is not False

    def pr_files(self, number: int) -> list[dict[str, Any]]:
        return self._json_lines("api", "--paginate", f"repos/{self.repository}/pulls/{number}/files?per_page=100",
                                "--jq", ".[] | {filename, previous_filename, status, changes} | @json")

    def disable_auto_merge(self, number: int) -> None:
        self._gh("pr", "merge", str(number), "-R", self.repository, "--disable-auto")


class HandoffGhCli(GhCli):
    """仅显式交接执行入口（handoff-merge / handoff-update-branch）使用的 GitHub CLI；
    与无人值守 Sweep 所用的 GhCli 物理隔离，保持 GhCli 不暴露 merge / update_branch。"""

    def merge(self, number: int, head: str) -> dict[str, Any]:
        return json.loads(self._gh("api", "-X", "PUT", f"repos/{self.repository}/pulls/{number}/merge",
                                   "-f", f"sha={head}", "-f", "merge_method=merge"))

    def update_branch(self, number: int, head: str) -> dict[str, Any]:
        return json.loads(self._gh("api", "-X", "PUT", f"repos/{self.repository}/pulls/{number}/update-branch",
                                   "-f", f"expected_head_sha={head}"))


def _is_current_contract(target: dict[str, Any]) -> bool:
    """仅认当前审查政策与合同的 run；旧合同（如 v1 Kimi/Opus）记录保留作留痕，不作当前合同的放行凭证。"""
    return target.get("policy_version") == POLICY and target.get("review_contract") == REVIEW_CONTRACT


def _latest_for_head(lane: ExternalReview, number: int, head: str) -> dict[str, Any] | None:
    """生产端、只读读取端与显式接手入口共用的目标选择：在当前 (pr, head) 下按 registered_at_ns 取最新未作废 attempt。"""
    runs = [row for row in lane.status(number) if row["target"].get("head_sha") == head]
    non_stale = [r for r in runs if not r["outcome"] or r["outcome"].get("verdict") != "STALE"]
    return max(non_stale, key=lambda r: r["target"]["registered_at_ns"]) if non_stale else None


def _confirmed_published_pass(lane: ExternalReview, number: int, head: str, base: str) -> bool:
    """生产端、只读读取端与显式接手入口共用的放行判定：当前合同下 (pr, head) 最新未作废 attempt 绑定到当前精确 base
    且为已发布 PASS 终态，且不存在待完成的重审意图。"""
    if lane.has_pending_rereview_intent(number, head, base):
        return False
    latest = _latest_for_head(lane, number, head)
    if latest is None or not _is_current_contract(latest["target"]) or latest["target"].get("base_sha") != base:
        return False
    outcome = latest["outcome"]
    return bool(outcome and "publication" in outcome and outcome.get("verdict") == "PASS")


def run_review_command(number: int, attempt: int, head: str, private_key: Path, base: str | None = None) -> list[str]:
    cmd = [sys.executable, "-m", "pilot1742.review_sweep", "run-review", "--pr", str(number),
           "--attempt", str(attempt), "--expect-head", head, "--private-key", str(private_key)]
    if base:
        cmd.extend(["--expect-base", base])
    return cmd


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
                 review_app: Callable[[], int | None] = configured_review_app):
        self.github, self.lane, self.spawn, self.rows, self.sync = github, lane, spawn, rows, sync
        self.review_app = review_app
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

    def launch_order(self, pulls: list[dict[str, Any]], busy: set[int]) -> list[dict[str, Any]]:
        """审查派发的先后（并发上限内谁先拿到名额）。只改先后，不改每个 PR 派不派、怎么审。
        1. 当前 head 能沿用同 patch_id/policy/contract 的已发布 PASS 的（ExternalReview.would_reuse，约 1 分钟、不调模型）；
        2. 其余按 head 提交的 committer 时间从新到旧；
        3. head 提交早于 STALE_PUSH（48 小时）或时间读不到的排最后，组内同样从新到旧。
        同组同时间按 PR 号升序。不进活动窗的 PR 本轮跳过，不读接口，排在末尾；已在审的 PR 不探沿用。
        排在后面的不会被饿死：前面的 PR 已完成、在等追平、在退避或要操作员处理时都不占名额，名额空着就轮到它。"""
        def key(pr: dict[str, Any]) -> tuple[int, float, int]:
            number = pr["number"]
            if self._eligible(pr):
                return 3, 0.0, number
            try:
                pushed = datetime.fromisoformat(self.github.committed_at(pr["head"]["sha"]).replace("Z", "+00:00"))
            except SourceUnreadable:  # gh 超时：与其他读接口一样整轮作废
                raise
            except Exception:  # 时间读不到只影响先后：按最旧一组排，照样会轮到
                return 2, 0.0, number
            if number not in busy and self.lane.would_reuse({
                    "repository_id": pr["base"]["repo"]["id"], "pr_number": number,
                    "base_repository_id": pr["base"]["repo"]["id"], "base_ref": pr["base"]["ref"],
                    "base_sha": pr["base"]["sha"], "head_repository_id": pr["head"]["repo"]["id"],
                    "head_ref": pr["head"]["ref"], "head_sha": pr["head"]["sha"]}):
                return 0, -pushed.timestamp(), number
            return (2 if pushed < self.now() - STALE_PUSH else 1), -pushed.timestamp(), number
        return sorted(pulls, key=key)

    def rate_limit_backoff(self) -> dict[str, Any] | None:
        """限流退避是否生效（两条独立判定取更长退避窗口）：
        1. 正式审阅链：最近 RATE_LIMIT_RUNS 个已完结且真派过模型的 run（outcome.json）均命中 failure_code=rate_limited，
           轻量预检成功绝不抵消正式审阅的连续限流；
        2. 预检+审阅合流：合并 preflight-rate-limits.json 与正式审阅记录，最近 RATE_LIMIT_RUNS 条均命中限流时同样触发退避
           （不占 attempt；后续预检通过可解除预检侧限流）。读不了的记录跳过。"""
        formal_events: list[tuple[float, str, bool]] = []
        for path in (self.lane.state_root / "runs").glob("*/outcome.json"):
            try:
                mtime = path.stat().st_mtime
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
            formal_events.append((mtime, str(outcome.get("run_id")), limited))
        preflight_events: list[tuple[float, str, bool]] = []
        preflight_log = self.lane.state_root / PREFLIGHT_RATE_LIMIT_FILE
        if preflight_log.is_file():
            try:
                loaded = json.loads(preflight_log.read_text())
                rows = loaded.get("events") if isinstance(loaded, dict) else None
                if isinstance(rows, list):
                    for row in rows:
                        if (isinstance(row, dict) and isinstance(row.get("at"), int | float)
                                and not isinstance(row.get("at"), bool) and isinstance(row.get("rate_limited"), bool)):
                            preflight_events.append(
                                (float(row["at"]), str(row.get("id") or "preflight"), row["rate_limited"])
                            )
            except (OSError, ValueError, TypeError):
                pass
        now_ts = self.now().timestamp()
        active: list[tuple[float, list[str]]] = []
        for stream in (formal_events, [*formal_events, *preflight_events]):
            found = sorted(stream, key=lambda item: item[0], reverse=True)[:RATE_LIMIT_RUNS]
            if len(found) == RATE_LIMIT_RUNS and all(limited for _, _, limited in found):
                until = found[0][0] + RATE_LIMIT_BACKOFF_SECONDS
                if now_ts < until:
                    active.append((until, [run for _, run, _ in found]))
        if not active:
            return None
        until, runs = max(active, key=lambda item: item[0])
        return {"action": "rate-limit-backoff", "runs": runs,
                "until": datetime.fromtimestamp(until, timezone.utc).isoformat()}

    def _resumes(self, number: int, head: str, attempt: int, base: str | None = None) -> Path:
        if base:
            return self.folder / f"p{number}-{head}-{base}-a{attempt}.resumes"
        return self.folder / f"p{number}-{head}-a{attempt}.resumes"

    def _has_commits(self, *shas: str) -> bool:
        try:
            for sha in shas:
                _git(self.lane.source, "cat-file", "-e", f"{sha}^{{commit}}")
        except subprocess.CalledProcessError:
            return False
        return True

    def _ensure_commits(self, number: int, base: str, head: str) -> tuple[str, dict | None] | None:
        if self._has_commits(base, head):
            return None
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
        return None

    def _launch(self, number: int, head: str, base: str, attempt: int) -> int:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        log = self.folder / "logs" / f"p{number}-{head[:12]}-a{attempt}.log"
        return self.spawn(number, attempt, head, log, base)

    def _resume_once(self, number: int, head: str, base: str, attempt: int, action: str) -> tuple[str, dict | None]:
        marker = self._resumes(number, head, attempt, base)
        if marker.exists():
            return ("needs-reconcile" if action == "publish" else "needs-operator"), None
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text(str(time.time()))
        return f"resume-{action}", {"pid": self._launch(number, head, base, attempt), "attempt": attempt}

    @staticmethod
    def _resumable(row: dict) -> bool:
        target = row["target"]
        return target.get("policy_version") == POLICY and target.get("review_contract") == REVIEW_CONTRACT

    def _run_folder(self, row: dict) -> Path:
        target = row["target"]
        key = (f"r{target['repository_id']}-p{target['pr_number']}-{target['base_sha']}"
               f"-{target['head_sha']}-{target['policy_version']}-a{target['attempt']}")
        return self.lane.state_root / "runs" / key

    def _needs_model_dispatch(self, row: dict | None) -> bool:
        if row is None:
            return True
        folder = self._run_folder(row)
        return any(not (folder / model / "launch.json").exists() for model in MODELS)

    def _pre_dispatch_reuse_fallback(self, row: dict) -> bool:
        """在发 pending 与建工蜂目录前即被拦下（沿用退回尚未过预检，或预检记账后触发 quota-paused）：
        尚未开始审查，按 launch-backoff 重试而不消耗唯一续跑机会。"""
        if row.get("outcome"):
            return False
        folder = self._run_folder(row)
        if (folder / "effects" / "status-pending.json").exists() or any((folder / model).exists() for model in MODELS):
            return False
        if (folder / QUOTA_PAUSED_FILE).exists():
            return True
        return bool(row["target"].get("reuse_planned")) and not (folder / PREFLIGHT_ADMITTED_FILE).exists()

    def _launch_with_backoff(self, number: int, head: str, base: str, attempt: int) -> tuple[str, dict | None]:
        marker = self.folder / f"p{number}-{head}-{base}-a{attempt}.launched"
        if marker.exists() and time.time() - marker.stat().st_mtime < LAUNCH_BACKOFF_SECONDS:
            return "launch-backoff", None
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text(str(time.time()))
        return "launch", {"pid": self._launch(number, head, base, attempt), "attempt": attempt}

    def _is_ancestor(self, ancestor: str, descendant: str) -> bool | None:
        """仅 git 退出码 0 判祖先、退出码 1 判非祖先；缺对象或其它错误返回 None，触发同步而不误判 done。"""
        done = subprocess.run(["git", "-C", str(self.lane.source), "merge-base", "--is-ancestor", ancestor, descendant],
                              capture_output=True)
        if done.returncode == 0:
            return True
        if done.returncode == 1:
            return False
        return None

    @staticmethod
    def _target_branch_valid(pr: dict[str, Any], state: dict[str, Any]) -> bool:
        """确认 PR 实时目标仍指向本仓 main 且 head 仍在本仓；缺字段时不放行。"""
        expected_repo = (pr["base"].get("repo") or {}).get("id")
        return (
            state.get("base_ref") == "main"
            and expected_repo is not None
            and state.get("base_repo_id") == expected_repo
            and state.get("head_repo_id") == expected_repo
        )

    def _latest_for_head(self, number: int, head: str) -> dict[str, Any] | None:
        return _latest_for_head(self.lane, number, head)

    def decide(self, pr: dict[str, Any], busy: set[int], running: int, behind: bool) -> tuple[str, dict | None]:
        number, head, base = pr["number"], pr["head"]["sha"], pr["base"]["sha"]
        if number in busy:
            return "running", None
        runs = [row for row in self.lane.status(number) if row["target"].get("head_sha") == head]
        latest = self._latest_for_head(number, head)
        if (latest is not None and latest["outcome"] and "publication" in latest["outcome"]
                and (_is_current_contract(latest["target"]) or latest["outcome"].get("verdict") != "PASS")):
            # F4：正常 main 前进使 PR 落后（behind 或 base 确非 head 祖先）时不重审旧 head，等追平；
            # 若同一 (base, head) 上存在尚未承接的人工重审意图（例如 A2 预检失败退出），不得把旧 A1 判 done；
            # 若本地缺对象（_is_ancestor 返回 None）须先同步再判定，不可误判 done；
            # 当 main 前进到 head 已包含的提交（clean，不会触发追平）时，须为新 base 派审；
            # 旧合同（如 v1 Kimi/Opus）已发布 PASS 保留历史但不算当前 GPT 双审合同的 done，落入下方派发新 attempt；
            # 旧合同已发布 BLOCK/FAILED 仍保持 done，不自动重审已失败旧 head。
            if latest["target"].get("base_sha") == base:
                if self.lane.has_pending_rereview_intent(number, head, base):
                    return "rereview-pending", None
                return "done", None
            if behind:
                return "done", None
            anc = self._is_ancestor(base, head)
            if anc is False:
                return "done", None
            if anc is None:
                sync_err = self._ensure_commits(number, base, head)
                if sync_err is not None:
                    return sync_err
                anc = self._is_ancestor(base, head)
                if anc is False:
                    return "done", None
                if anc is None:
                    return "needs-source-sync", None
        if running >= self.max_running:
            return "queued", None
        if latest is not None and latest["outcome"] and "publication" not in latest["outcome"]:
            if latest["target"].get("base_sha") == base:
                if not self._resumable(latest):
                    return "needs-reconcile", None
                return self._resume_once(number, head, base, latest["target"]["attempt"], "publish")
            # 旧 base 上尚未发布的 outcome 已被新 base 取代（原记录完整保留）：
            # 绝不回退为 needs-reconcile 堵死追平；落后则允许追平，新 base 为 head 祖先则照常走新 base 派审。
            if behind:
                return "behind-awaiting-update", None
            anc = self._is_ancestor(base, head)
            if anc is False:
                return "behind-awaiting-update", None
            if anc is None:
                sync_err = self._ensure_commits(number, base, head)
                if sync_err is not None:
                    return sync_err
                anc = self._is_ancestor(base, head)
                if anc is False:
                    return "behind-awaiting-update", None
                if anc is None:
                    return "needs-source-sync", None
        if behind:  # 先追平再审：不审一个合入前必然被替换的 head
            return "behind-awaiting-update", None
        if self._backoff is not None:  # 限流退避：不派新审查（含续跑审查），本轮汇总一行日志
            return "review-backoff", None
        sync_err = self._ensure_commits(number, base, head)
        if sync_err is not None:
            return sync_err
        current = [r for r in runs if r["target"].get("base_sha") == base]
        pr_target_data = {
            "repository_id": pr["base"]["repo"]["id"], "pr_number": number,
            "base_repository_id": pr["base"]["repo"]["id"], "base_ref": pr["base"]["ref"],
            "base_sha": base, "head_repository_id": pr["head"]["repo"]["id"],
            "head_ref": pr["head"]["ref"], "head_sha": head,
        }
        if latest is not None and not latest["outcome"] and latest["target"].get("base_sha") == base:  # 最新登记的未完结 attempt
            if not self._resumable(latest):
                return "needs-operator", None
            if (self._needs_model_dispatch(latest)
                    and not (latest["target"].get("reuse_planned")
                             and not (self._run_folder(latest) / PREFLIGHT_ADMITTED_FILE).exists()
                             and self.lane.would_reuse(pr_target_data))):
                try:
                    self.lane.admit_quota()
                except EffectPending as error:
                    return "quota-paused", {"reason": str(error)}
            if self._pre_dispatch_reuse_fallback(latest):  # 尚未发 pending/建工蜂目录：走 launch-backoff，不耗尽唯一续跑机会
                return self._launch_with_backoff(number, head, base, latest["target"]["attempt"])
            return self._resume_once(number, head, base, latest["target"]["attempt"], "review")
        if not self.lane.would_reuse(pr_target_data):
            try:
                self.lane.admit_quota()
            except EffectPending as error:
                return "quota-paused", {"reason": str(error)}
        attempt = max((r["target"]["attempt"] for r in current), default=0) + 1
        # 子进程在登记前就退出（读 PR 失败、App 身份未就绪、controller 不干净）时同一 attempt 会原样再派；
        # 退避一段时间，免得每轮都派一个必死的子进程。
        return self._launch_with_backoff(number, head, base, attempt)

    @contextmanager
    def _tick_lock(self) -> Iterator[None]:
        """同一状态根的巡检排他锁：串行化常驻 serve 与手动单轮 sweep，防止慢轮用旧结论覆写快轮交接快照。"""
        fd = -1
        try:
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_path = self.folder / "sweep.lock"
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or (st.st_mode & 0o077):
                raise OSError(f"sweep.lock 文件类型、属主或权限不合法：{lock_path}")
            fcntl.flock(fd, fcntl.LOCK_EX)
        except Exception as error:
            if fd >= 0:
                os.close(fd)
            raise SourceUnreadable("sweep lock", error) from error
        try:
            yield
        finally:
            os.close(fd)

    def tick(self) -> list[dict[str, Any]]:
        with self._tick_lock():
            return self._tick_locked()

    def _tick_locked(self) -> list[dict[str, Any]]:
        try:
            rows = self.rows()
        except Exception as error:  # 不知道谁在审就不能派审：整轮作废并作废旧交接快照
            if self.auto_merge:
                self._invalidate_merge_handoff("host process table unreadable")
            raise SourceUnreadable("host process table", error) from error
        busy = reviewing(rows)  # 单 PR 去重：已在审的 PR 不再派
        running = reviewer_processes(rows)  # 并发上限：按进程数，不按 PR 数
        # 追平只看本地真实在途（活进程或本轮刚派出），不信 GitHub 上的 pending：审查进行中 main 前进时终态判 Stale，
        # GitHub 上该 head 会一直停在 pending；若以它为准，decide 等追平、合入等审查，两边互等。中断后残留的
        # 无结论 run 审的是旧 base，追平后自然作废，也不挡追平。
        reviewing_now = set(busy)
        try:
            pulls = sorted(self.open_pulls(), key=lambda pr: pr["number"])
        except Exception as error:
            if self.auto_merge:
                self._invalidate_merge_handoff("github open pulls unreadable")
            raise SourceUnreadable("github open pulls", error) from error
        self._sync_failed = False
        self._backoff = self.rate_limit_backoff()
        actions: list[dict[str, Any]] = []
        states: dict[int, dict[str, Any]] = {}
        unreadable: set[int] = set()
        review_actions: dict[int, str] = {}
        withdrawn: set[int] = set()   # 本轮已确认撤掉原生 auto-merge 的 PR
        early_withdraw: dict[int, dict[str, Any]] = {}  # 已在读/派审前即时撤回（或尝试撤回）的结果
        early_logged: set[int] = set()
        drifted: set[int] = set()
        repo_native: tuple[bool, str] | None = None
        pr_errors: dict[int, str] = {}
        try:
            if self.auto_merge:
                # 1. 先读取全部合格 PR 的实时状态；对任何已知挂起或状态不明的 PR（含不合格 PR）立刻撤回原生 auto-merge，
                #    不等后面的 allow_auto_merge / decide / pr_files / checks 全轮读完，最小化 GitHub 抢跑合入窗口。
                for idx, pr in enumerate(pulls):
                    number = pr["number"]
                    entry = {"pr": number, "head": pr["head"]["sha"]}
                    skip = self._eligible(pr)
                    if skip:
                        if pr.get("auto_merge", True) is not None:
                            try:
                                wres = self._withdraw(number, True)
                            except SourceUnreadable as error:
                                for rem in pulls[idx + 1:]:
                                    if not self._eligible(rem):
                                        unreadable.add(rem["number"])
                                actions.append({**entry, "action": "write-unknown", "write": "disable", "reason": str(error)})
                                raise
                            early_withdraw[number] = wres
                            if wres.get("auto_merge_withdrawn"):
                                withdrawn.add(number)
                            actions.append({**entry, "action": "auto-merge-withdraw", "reason": skip, **wres})
                            early_logged.add(number)
                        continue
                    try:
                        states[number] = self.github.pr(number)
                    except SourceUnreadable:  # 实时 PR 状态读取超时：本条及余下尚未读取的合格 PR 均记未知，让 fail_closed 兜底撤原生 auto-merge
                        for rem in pulls[idx:]:
                            if not self._eligible(rem):
                                unreadable.add(rem["number"])
                        raise
                    except Exception as error:  # 单个 PR 隔离：不派审，并立刻尝试撤回原生 auto-merge
                        unreadable.add(number)
                        pr_errors[number] = f"{type(error).__name__}: {error}"
                        try:
                            wres = self._withdraw(number, True)
                        except SourceUnreadable as werr:
                            for rem in pulls[idx + 1:]:
                                if not self._eligible(rem):
                                    unreadable.add(rem["number"])
                            actions.append({**entry, "action": "write-unknown", "write": "disable", "reason": str(werr)})
                            raise
                        early_withdraw[number] = wres
                        if wres.get("auto_merge_withdrawn"):
                            withdrawn.add(number)
                        continue
                    if states[number].get("auto_merge") is not False:
                        try:
                            wres = self._withdraw(number, True)
                        except SourceUnreadable as error:
                            for rem in pulls[idx + 1:]:
                                if not self._eligible(rem):
                                    unreadable.add(rem["number"])
                            actions.append({**entry, "action": "write-unknown", "write": "disable", "reason": str(error)})
                            raise
                        early_withdraw[number] = wres
                        if wres.get("auto_merge_withdrawn"):
                            withdrawn.add(number)
                            states[number]["auto_merge"] = False
                try:
                    native = self.github.allow_auto_merge()
                except SourceUnreadable:
                    raise
                except Exception as error:
                    native, why = True, f"读取仓库设置 allow_auto_merge 失败：{type(error).__name__}: {error}"
                else:
                    why = "仓库设置 allow_auto_merge=true：原生 auto-merge 可在两轮之间被挂上，绕过人工确认两类"
                repo_native = (native, why)
            for pr in self.launch_order(pulls, busy):  # 审查按 launch_order；合入、追平、兜底撤销仍按 PR 号
                entry = {"pr": pr["number"], "head": pr["head"]["sha"]}
                try:
                    skip = self._eligible(pr)
                    if skip:  # 闲置/草稿/跨仓 PR 不派审、不读文件与检查；原生 auto-merge 已在上游即时撤回
                        actions.append({**entry, "action": skip})
                        continue
                    if pr["number"] in pr_errors:
                        action = "error"
                        actions.append({**entry, "action": action, "reason": pr_errors[pr["number"]]})
                        review_actions[pr["number"]] = action
                        continue
                    behind = states[pr["number"]]["mergeable_state"] == "behind" if pr["number"] in states else False
                    if pr["number"] in states and not self._target_branch_valid(pr, states[pr["number"]]):
                        action = "base-ref-moved"
                        actions.append({
                            **entry,
                            "action": action,
                            "expected_base_ref": "main",
                            "now_base_ref": states[pr["number"]].get("base_ref"),
                        })
                        review_actions[pr["number"]] = action
                        continue
                    pr_for_decide = ({**pr, "base": {**pr["base"], "sha": states[pr["number"]]["base"]}}
                                     if pr["number"] in states else pr)
                    if self.auto_merge and repo_native is not None and repo_native[0]:
                        action = "held-native-auto-merge"
                        actions.append({**entry, "action": action, "reason": repo_native[1]})
                        review_actions[pr["number"]] = action
                        continue
                    if self.auto_merge and states[pr["number"]].get("auto_merge") is not False:
                        # 已挂原生 auto-merge 且即时撤回失败：绝不派发审查或沿用（防发布 success 触发合入）。
                        action = "held-auto-merge-withdraw-failed"
                        actions.append({**entry, "action": action})
                        review_actions[pr["number"]] = action
                        continue
                    action, record = self.decide(pr_for_decide, busy, running, behind)
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
                self.merge_actions(pulls, states, reviewing_now, review_actions, unreadable,
                                   out=actions, withdrawn=withdrawn, live_busy=busy,
                                   repo_native=repo_native, drifted=drifted,
                                   early_withdraw=early_withdraw, early_logged=early_logged)
            if self._backoff is not None:
                actions.append({**self._backoff,
                                "held": [n for n, a in review_actions.items() if a == "review-backoff"]})
        except SourceUnreadable as error:
            # 超时（或整轮输入源读不到）：本轮不再合入、不再追平，立即作废旧交接快照；先补记已即时撤回但尚未由
            # merge_actions 落日志的条目，再对尚未确认撤回且挂着（或不知道挂没挂）原生 auto-merge 的 PR 兜底撤回。
            if self.auto_merge:
                self._invalidate_merge_handoff(f"source unreadable: {error.source}")
                for pr in pulls:
                    number = pr["number"]
                    if number in early_withdraw and number not in early_logged:
                        actions.append({"pr": number, "head": pr["head"]["sha"],
                                        "action": "auto-merge-withdraw", **early_withdraw[number]})
                        early_logged.add(number)
                actions += self.fail_closed(pulls, states, withdrawn, unreadable)
            error.actions = actions
            raise
        except Exception as error:
            if self.auto_merge:
                self._invalidate_merge_handoff(f"tick error: {type(error).__name__}")
            raise
        return actions

    def _review_binding_unsafe(self, bound: int) -> str | None:
        """必需检查 deepagents/review 须绑定审查专用 App（IDENTITY_CONFIG 配的那个），且它不是执行器 App。
        绑定执行器 App 时，执行器交付时自写的 success 就能满足必需检查：draft 一标 ready，sweep 可能在同一轮
        刚派出正式审查、还没发 pending 时就合入。"""
        try:
            reviewer = self.review_app()
        except Exception:  # 读不了审查身份：不知道绑定对不对，按不安全处理
            reviewer = None
        if bound == EXECUTOR_APP_ID:
            return f"必需检查 deepagents/review 绑定执行器 App {bound}：执行器交付时自写的 success 会被当成正式审查，不合入"
        if reviewer is None or bound != reviewer:
            return (f"必需检查 deepagents/review 绑定 App {bound}，与审查身份文件配的审查 App {reviewer} 不符"
                    "（或身份文件缺失、读不了），不合入")
        return None

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

    def _review_confirmed_published_pass(self, number: int, head: str, base: str) -> bool:
        """正向确认：当前合同下本 PR、当前 head 的最新未作废 attempt 绑定到当前精确 base 且为已发布 PASS 终态，
        且当前 (pr, base, head) 上不存在待完成的重审意图（防旧合同 PASS 或预检失败重审后凭旧状态放行）。"""
        return _confirmed_published_pass(self.lane, number, head, base)

    def _plan_one(self, pr: dict[str, Any], state: dict[str, Any], gate_ok: bool, head_free: bool,
                  reviewing_now: bool = False, review_action: str | None = None,
                  bindings: dict[str, int] | None = None, live_review: bool = False,
                  withdrawn: set[int] | None = None,
                  early_withdraw: dict[int, dict[str, Any]] | None = None) -> tuple[dict[str, Any], bool, str | None]:
        """只读、不写：返回（动作，是否占队首，要做的写：merge / update / disable / None）。
        只有 head_free（前面没有 PR 占队首）且本 PR 仍可能合入时才可能追平。"""
        number, head = pr["number"], pr["head"]["sha"]
        if not self._target_branch_valid(pr, state):
            return ({"action": "base-ref-moved", "expected_base_ref": "main", "now_base_ref": state.get("base_ref")},
                    False, "disable" if state["auto_merge"] else None)
        if state["head"] != head:  # 列表上的 head 与实时状态不符：新 head 没分类过，挂着的原生 auto-merge 撤掉
            return ({"action": "head-moved", "listed": head, "now": state["head"]}, False,
                    "disable" if state["auto_merge"] else None)
        files = self.complete_files(number, state)  # 证据不足抛出，由 merge_actions 失败关闭
        # 文件清单接口不按 SHA 取：读完后再读一次 PR，head、base SHA 与目标分支仍一致才算这份清单属于它。
        try:
            again = self.github.pr(number)
        except SourceUnreadable:
            # 复核实时 PR 状态超时：此后是否新挂原生 auto-merge 未知，立即作废旧撤回记录并置待撤让 fail_closed 兜底。
            state["auto_merge"] = True
            if withdrawn is not None:
                withdrawn.discard(number)
            if early_withdraw is not None:
                early_withdraw.pop(number, None)
            raise
        except Exception as error:
            # 非超时复核失败（如 HTTP 502 / gh 非零退出）同样无法排除期间新挂原生 auto-merge，作废旧撤回记录并走撤回路径。
            state["auto_merge"] = True
            if withdrawn is not None:
                withdrawn.discard(number)
            if early_withdraw is not None:
                early_withdraw.pop(number, None)
            raise EvidenceInsufficient(f"复核 head 失败：{type(error).__name__}: {error}") from None
        if again.get("auto_merge"):
            # 复核发现本轮早期撤回后又被重新挂起：立即作废旧撤回记录，防止后续任意读取超时时 fail_closed 跳过它。
            if withdrawn is not None:
                withdrawn.discard(number)
            if early_withdraw is not None:
                early_withdraw.pop(number, None)
        armed = bool(state["auto_merge"] or again["auto_merge"])
        if armed:
            state["auto_merge"] = True
        disable_if_armed = "disable" if armed else None
        if not self._target_branch_valid(pr, again):
            return ({"action": "base-ref-moved", "expected_base_ref": "main", "now_base_ref": again.get("base_ref")},
                    False, disable_if_armed)
        if again["head"] != head:
            return ({"action": "head-moved", "classified": head, "now": again["head"]}, False, disable_if_armed)
        if again["base"] != state["base"]:
            return ({"action": "base-moved", "classified_base": state["base"], "now_base": again["base"]}, False,
                    disable_if_armed)
        if again.get("draft") is True:
            return {"action": "draft"}, False, disable_if_armed
        prev_mergeable = state["mergeable_state"]
        mergeable = again["mergeable_state"]
        state["mergeable_state"] = mergeable
        if mergeable != prev_mergeable:
            return ({"action": "waiting", "reason": "mergeable-state-changed", "before": prev_mergeable,
                     "mergeable_state": mergeable, "queue_head": False}, False, disable_if_armed)
        gated = human_gated(files)
        if gated:
            return {"action": "needs-human-confirm", "gated": gated}, False, disable_if_armed
        try:
            checks = self.github.checks(head, bindings or {})
        except SourceUnreadable:
            raise
        except Exception as error:
            raise EvidenceInsufficient(f"读取 {head[:12]} 的检查失败：{type(error).__name__}: {error}") from None
        review = checks.get("deepagents/review")
        behind = mergeable == "behind"
        all_green = all(checks.get(name) == "success" for name in MERGE_CHECKS)
        # 本 head 已发布失败结论（BLOCK/error）时不占队首；不落后时检查失败要作者处理；
        # 不落后、三项全绿却不可合入（blocked/unknown 等）的也不占队首。
        # 无论是否处于 behind / waiting / gate_ok=False，只要 PR 挂着原生 auto-merge 一律独立撤回（disable_if_armed）。
        candidate = (review != "failure" and mergeable != "dirty" and review_action not in STUCK_REVIEW
                     and (behind or not any(checks.get(name) == "failure" for name in MERGE_CHECKS))
                     and (behind or not all_green or mergeable in ("clean", "unstable")))
        is_head = candidate and head_free
        if behind:
            # GitHub update-branch 接口同样无服务端 expected_base_ref，不自动写入 PR 分支，报 behind-waiting 并撤原生 auto-merge。
            return {"action": "behind-waiting", "review": review, "reviewing": reviewing_now,
                    "queue_head": is_head}, candidate, disable_if_armed
        confirmed_pass = self._review_confirmed_published_pass(number, head, state["base"])
        pending_latest = live_review or self.lane.has_inflight_review(number) or not confirmed_pass
        if gate_ok and mergeable in ("clean", "unstable") and all_green and not pending_latest:
            # GitHub REST/GraphQL 合入接口均无服务端 expected_base_ref 前置参数，无法在读后防远端改指非 main 分支；
            # 因此全部门禁就绪的 PR 一律失败闭合转人工确认，并撤掉挂着的原生 auto-merge，不自动发起 PUT /pulls/{n}/merge。
            return ({"action": "needs-human-confirm", "gated": ["base-ref-not-server-bound"],
                     "reason": "GitHub 合入接口不支持服务端 expected_base_ref 绑定，无法原子防远端改指非 main 分支，不自动合入"},
                    False, disable_if_armed)
        return {"action": "waiting", "checks": {name: checks.get(name) for name in MERGE_CHECKS},
                "mergeable_state": mergeable, "queue_head": is_head,
                **({"pending_latest_attempt": True} if pending_latest else {}),
                **({} if gate_ok else {"gate": "ci-ok 未设为必需检查"})}, candidate, disable_if_armed

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

    def fail_closed(self, pulls: list[dict[str, Any]], states: dict[int, dict[str, Any]],
                    withdrawn: set[int], unreadable: set[int] | frozenset[int] = frozenset()) -> list[dict[str, Any]]:
        """本轮中途超时后的兜底：对每个指向 main 且本轮尚未确认撤回、又挂着（或不知道挂没挂）原生 auto-merge 的 PR
        （包含跳过派审的 draft/stale-pr/foreign-head、读状态失败与尚未执行写阶段的普通 waiting/behind PR）尽力撤掉，每个一行日志。
        撤销本身也超时就停下（GitHub 不通，后面的照样会超时），下轮重试。"""
        actions: list[dict[str, Any]] = []
        for pr in pulls:
            number = pr["number"]
            if number in withdrawn:
                continue
            state = states.get(number)
            armed = number in unreadable or (bool(state["auto_merge"]) if state else pr.get("auto_merge", True) is not None)
            if not armed:
                continue
            entry = {"pr": number, "head": pr["head"]["sha"], "action": "fail-closed-withdraw"}
            try:
                actions.append({**entry, **self._withdraw(number, True)})
            except SourceUnreadable as error:
                actions.append({**entry, "auto_merge_withdrawn": False, "withdraw_error": str(error)})
                actions.append({"action": "fail-closed-aborted", "reason": "撤销也超时，余下的下轮再撤"})
                break
        return actions

    def merge_actions(self, pulls: list[dict[str, Any]], states: dict[int, dict[str, Any]],
                      reviewing_now: set[int] | frozenset[int] = frozenset(),
                      review_actions: dict[int, str] | None = None,
                      unreadable: set[int] | frozenset[int] = frozenset(), *,
                      out: list[dict[str, Any]] | None = None,
                      withdrawn: set[int] | None = None,
                      live_busy: set[int] | frozenset[int] = frozenset(),
                      repo_native: tuple[bool, str] | None = None,
                      drifted: set[int] | None = None,
                      early_withdraw: dict[int, dict[str, Any]] | None = None,
                      early_logged: set[int] | None = None) -> list[dict[str, Any]]:
        """两段：先把每个 PR 的证据读完并定好动作（只读），全部读完才按序执行撤原生 auto-merge 写操作。
        读阶段任何超时都在写之前抛出，并由 fail_closed 按已确认撤回集合兜底撤销；动作逐条追加到 out，超时时已做的也不丢。"""
        actions = [] if out is None else out
        withdrawn = set() if withdrawn is None else withdrawn
        review_actions = review_actions or {}
        early_withdraw = early_withdraw or {}
        early_logged = set() if early_logged is None else early_logged
        evidence_ok = True
        required: dict[str, int] = {}
        try:
            required = self.github.required_checks()
            gate_ok = GATE <= set(required)
        except SourceUnreadable:
            raise
        except Exception as error:  # 不合入、不追平，但照常逐个 PR 判人工确认类并撤原生 auto-merge
            gate_ok = evidence_ok = False
            actions.append({"action": "evidence-insufficient", "reason": f"读取 main 必需检查失败：{error}"})
        # 合入看的每项检查都绑定来源 App：必需检查用分支保护的绑定，其余用 GATED_APP_IDS
        bindings: dict[str, int] = {}
        for name in MERGE_CHECKS:
            app = required.get(name, GATED_APP_IDS.get(name))
            if app is not None:
                bindings[name] = app
        if repo_native is not None:
            native, why = repo_native
        else:
            try:
                native = self.github.allow_auto_merge()
            except SourceUnreadable:
                raise
            except Exception as error:
                native, why = True, f"读取仓库设置 allow_auto_merge 失败：{type(error).__name__}: {error}"
            else:
                why = "仓库设置 allow_auto_merge=true：原生 auto-merge 可在两轮之间被挂上，绕过人工确认两类"
        if native:  # 本轮不合入、不追平；撤原生 auto-merge 照常做
            gate_ok = evidence_ok = False
            actions.append({"action": "native-auto-merge-enabled", "reason": why})
        if evidence_ok and not gate_ok:
            actions.append({"action": "auto-merge-unsafe",
                            "reason": f"main 须 strict、enforce_admins 且必需检查含绑定来源 app 的 {sorted(GATE)}，不合入"})
        elif gate_ok:
            unsafe = self._review_binding_unsafe(required["deepagents/review"])
            if unsafe:  # 执行器自写的 success 会满足必需检查，正式审查可能还没跑完就合入：本轮不合入
                gate_ok = False
                actions.append({"action": "auto-merge-unsafe", "reason": unsafe})
        plan: list[tuple[dict[str, Any], dict[str, Any], str | None, bool]] = []
        head_free = True
        for pr in pulls:  # 与 tick 同序（PR 号升序）：队首是第一个仍可能合入的 PR
            number = pr["number"]
            entry = {"pr": number, "head": pr["head"]["sha"]}
            if number in unreadable:  # 状态读不到，不知道挂没挂原生 auto-merge：若前期未成功撤回则再撤
                need_withdraw = "disable" if number not in withdrawn else None
                plan.append((entry, {"action": "evidence-insufficient", "reason": "读取 PR 状态失败"},
                             need_withdraw, number not in withdrawn))
                continue
            if number not in states:
                # 派审资格过滤（draft/stale-pr/foreign-head）独立于原生 auto-merge 撤销：
                # 若在 tick 前期已即时撤回并落日志则跳过；仅当未撤回且列表载荷表明已挂或未知时撤回。
                if number in early_logged:
                    continue
                if pr.get("auto_merge", True) is not None:
                    skip = self._eligible(pr) or "ineligible"
                    plan.append((entry, {"action": "auto-merge-withdraw", "reason": skip}, "disable", True))
                continue
            armed = states[number].get("auto_merge") is not False
            claimed = False
            write: str | None
            try:
                result, claimed, write = self._plan_one(pr, states[number], gate_ok, head_free and evidence_ok,
                                                        number in reviewing_now, review_actions.get(number), bindings,
                                                        live_review=number in live_busy,
                                                        withdrawn=withdrawn, early_withdraw=early_withdraw)
            except SourceUnreadable:
                raise
            except Exception as error:  # 单个 PR 隔离；不明即不合入，并撤原生 auto-merge（失败关闭）
                armed = states[number].get("auto_merge") is not False
                kind = "evidence-insufficient" if isinstance(error, EvidenceInsufficient) else "error"
                reason = str(error) if kind == "evidence-insufficient" else f"{type(error).__name__}: {error}"
                result, write = {"action": kind, "reason": reason}, ("disable" if armed else None)
            else:
                armed = states[number].get("auto_merge") is not False
                if drifted is not None and result.get("action") in ("head-moved", "base-moved", "base-ref-moved"):
                    drifted.add(number)
            head_free = head_free and not claimed
            plan.append((entry, result, write, armed))
        executed: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        for entry, result, write, armed in plan:
            number = entry["pr"]
            try:
                if write == "disable":
                    result = {**result, **self._withdraw(number, True)}
                    if result.get("auto_merge_withdrawn"):
                        withdrawn.add(number)
                elif number in early_withdraw:
                    result = {**result, **early_withdraw[number]}
            except SourceUnreadable as error:  # 写超时：结果不明，本轮余下的写不再做
                actions.append({**entry, "action": "write-unknown", "write": write, "reason": str(error)})
                raise
            except Exception as error:  # 写失败：不明即撤原生 auto-merge
                result = {"action": "error", "reason": f"{type(error).__name__}: {error}"}
                if write != "disable":
                    try:
                        result.update(self._withdraw(number, armed))
                    except SourceUnreadable as timeout:  # 撤销也超时：这一行先记下再整轮作废
                        actions.append({**entry, **result, "auto_merge_withdrawn": False,
                                        "withdraw_error": str(timeout)})
                        raise
            withdraw_confirmed = (
                (not armed or number in withdrawn)
                and result.get("auto_merge_withdrawn") is not False
                and result.get("action") != "error"
            )
            executed.append((entry, result, withdraw_confirmed))
            actions.append({**entry, **result})
            early_logged.add(number)
        self._write_merge_handoff(executed, states, gate_ok)
        return actions

    def _save_merge_handoff_payload(self, payload: dict[str, Any]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.folder / MERGE_HANDOFF_FILE
        tmp = self.folder / f".{MERGE_HANDOFF_FILE}.{os.getpid()}.{time.time_ns()}.tmp"
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, target)

    def _invalidate_merge_handoff(self, reason: str) -> None:
        """失败/超时轮次立即作废旧交接快照（置 gate_ok=False 并清空可操作队列；写失败时删除旧文件），防止读到陈旧结果。"""
        payload = {
            "schema": MERGE_HANDOFF_SCHEMA,
            "updated_at": self.now().isoformat(),
            "base_ref": "main",
            "gate_ok": False,
            "invalidated_reason": reason,
            "behind_queue_head": [],
            "ready_for_merge": [],
            "human_confirm": [],
        }
        try:
            self._save_merge_handoff_payload(payload)
        except OSError:
            try:
                (self.folder / MERGE_HANDOFF_FILE).unlink(missing_ok=True)
            except OSError:
                pass

    def _write_merge_handoff(self, executed: list[tuple[dict[str, Any], dict[str, Any], bool]],
                             states: dict[int, dict[str, Any]], gate_ok: bool) -> None:
        """每轮 --auto-merge 完成撤回后，按实际确认结果原子刷新 sweep/merge-handoff.json（0o600）：
        仅在撤回已确认（未挂或已成功撤回原生 auto-merge）时入队；队首落后 PR 若仍有在途审查（reviewing=True），
        保留队首位置但不交接追平，免得改 head 作废正在运行的审阅。"""
        behind_queue_head: list[dict[str, Any]] = []
        ready_for_merge: list[dict[str, Any]] = []
        human_confirm: list[dict[str, Any]] = []
        for entry, result, withdraw_confirmed in executed:
            number = entry["pr"]
            state = states.get(number) or {}
            base = state.get("base")
            action = result.get("action")
            if (gate_ok and withdraw_confirmed and action == "behind-waiting"
                    and result.get("queue_head") is True and not result.get("reviewing")):
                behind_queue_head.append({"pr": number, "head": entry["head"], "base": base, "base_ref": "main"})
            elif action == "needs-human-confirm":
                gated = result.get("gated")
                if gate_ok and withdraw_confirmed and gated == ["base-ref-not-server-bound"]:
                    ready_for_merge.append({
                        "pr": number, "head": entry["head"], "base": base,
                        "base_ref": "main", "gated": gated,
                    })
                elif isinstance(gated, dict):
                    human_confirm.append({
                        "pr": number, "head": entry["head"], "base": base,
                        "base_ref": "main", "gated": gated,
                    })
        payload = {
            "schema": MERGE_HANDOFF_SCHEMA,
            "updated_at": self.now().isoformat(),
            "base_ref": "main",
            "gate_ok": bool(gate_ok),
            "behind_queue_head": behind_queue_head,
            "ready_for_merge": ready_for_merge,
            "human_confirm": human_confirm,
        }
        self._save_merge_handoff_payload(payload)


def read_merge_handoff(state_root: Path = STATE_ROOT, *,
                       max_age_seconds: float = MERGE_HANDOFF_MAX_AGE_SECONDS,
                       now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                       rows: Callable[[], Rows] = _ps_rows) -> dict[str, Any]:
    """只读读取 sweep/merge-handoff.json（非阻塞、拒绝符号链接/FIFO/越权/过期快照），并现场复核
    本机活跃审查进程、在途锁、待承接重审意图及最新非 STALE attempt 是否仍为精确 (base, head) 的已发布 PASS，
    供主控巡航或维护者消费。"""
    path = state_root / "sweep" / MERGE_HANDOFF_FILE
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {
            "schema": MERGE_HANDOFF_SCHEMA,
            "updated_at": None,
            "base_ref": "main",
            "gate_ok": False,
            "behind_queue_head": [],
            "ready_for_merge": [],
            "human_confirm": [],
        }
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or (st.st_mode & 0o077) or st.st_size > 1_048_576:
            raise ValueError(f"merge-handoff 文件类型、属主、权限或大小不合法：{path}")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            data = json.load(handle)
    finally:
        if fd >= 0:
            os.close(fd)
    if not isinstance(data, dict) or data.get("schema") != MERGE_HANDOFF_SCHEMA:
        raise ValueError(f"merge-handoff 格式无效：{path}")
    updated_raw = data.get("updated_at")
    if not isinstance(updated_raw, str) or not updated_raw.strip():
        raise ValueError(f"merge-handoff 缺少有效 updated_at：{path}")
    try:
        updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(f"merge-handoff 时间戳格式无效：{path}") from None
    age = (now() - updated_dt).total_seconds()
    if age > max_age_seconds or age < -60:
        raise ValueError(f"merge-handoff 快照已过期或时钟异常（age={age:.1f}s，上限 {max_age_seconds:.0f}s）：{path}")
    try:
        live_busy = reviewing(rows())
    except Exception as error:
        raise ValueError(f"无法读取宿主活跃审查进程表：{type(error).__name__}") from None
    lane = ExternalReview(None, state_root=state_root)
    if not isinstance(data.get("ready_for_merge"), list) or not isinstance(data.get("behind_queue_head"), list):
        raise ValueError(f"merge-handoff 队列字段格式无效：{path}")
    filtered_ready = []
    for row in data["ready_for_merge"]:
        if not isinstance(row, dict) or type(row.get("pr")) is not int:
            continue
        pr_num, head_sha, base_sha = row["pr"], row.get("head"), row.get("base")
        if not isinstance(head_sha, str) or not isinstance(base_sha, str):
            continue
        if (pr_num in live_busy or lane.has_inflight_review(pr_num)
                or not _confirmed_published_pass(lane, pr_num, head_sha, base_sha)):
            continue
        filtered_ready.append(row)
    data["ready_for_merge"] = filtered_ready
    filtered_behind = []
    for row in data["behind_queue_head"]:
        if not isinstance(row, dict) or type(row.get("pr")) is not int:
            continue
        pr_num = row["pr"]
        if pr_num in live_busy or lane.has_inflight_review(pr_num):
            continue
        filtered_behind.append(row)
    data["behind_queue_head"] = filtered_behind
    return data


def _no_spawn(_number: int, _attempt: int, _head: str, _log: Path, _base: str | None = None) -> int:
    raise RuntimeError("handoff execution entrypoints must not spawn reviews")


def _handoff_verify_remote(github: HandoffGitHubPort, lane: ExternalReview, number: int, *,
                           expect_base: str, expect_head: str, mode: str,
                           review_app: Callable[[], int | None] = configured_review_app) -> dict[str, Any]:
    """持锁期间实时复核远端门禁与精确 (base_ref=main, base_sha, head_sha, mergeable_state, 非敏感文件清单, 三项检查)。"""
    helper = Sweep(github, lane, _no_spawn, auto_merge=False, review_app=review_app)
    required = github.required_checks()
    if not (GATE <= set(required)):
        raise HandoffBlocked("branch-protection-unsafe",
                             f"main 须 strict、enforce_admins 且必需检查含绑定来源 app 的 {sorted(GATE)}")
    unsafe = helper._review_binding_unsafe(required["deepagents/review"])
    if unsafe:
        raise HandoffBlocked("review-app-binding-unsafe", unsafe)
    if github.allow_auto_merge():
        raise HandoffBlocked("native-auto-merge-enabled", "仓库 allow_auto_merge=true，拒绝执行交接写操作")
    state = github.pr(number)
    if (state.get("state", "open") != "open" or state.get("draft") is True or state.get("base_ref") != "main"
            or state.get("base_repo_id") is None
            or state.get("base_repo_id") != state.get("head_repo_id")):
        raise HandoffBlocked("target-branch-invalid", f"PR #{number} 目标分支、开放/草稿态或跨仓状态不合法")
    if state.get("head") != expect_head:
        raise HandoffBlocked("head-moved", f"PR #{number} 期望 head {expect_head}，远端现为 {state.get('head')}")
    if state.get("base") != expect_base:
        raise HandoffBlocked("base-moved", f"PR #{number} 期望 base {expect_base}，远端现为 {state.get('base')}")
    allowed_states = ("clean", "unstable") if mode == "merge" else ("behind",)
    if state.get("mergeable_state") not in allowed_states:
        raise HandoffBlocked("mergeable-state-invalid",
                             f"PR #{number} 当前 mergeable_state={state.get('mergeable_state')}，不满足 {mode}")
    if state.get("auto_merge") is not False:
        github.disable_auto_merge(number)
        raise HandoffBlocked("native-auto-merge-armed", f"PR #{number} 挂着原生 auto-merge，已撤回，请复核后重试")
    files = helper.complete_files(number, state)
    again = github.pr(number)
    if again.get("auto_merge") is not False:
        github.disable_auto_merge(number)
        raise HandoffBlocked("native-auto-merge-armed", f"PR #{number} 复核期间挂起原生 auto-merge，已撤回")
    if (again.get("state", "open") != "open" or again.get("draft") is True or again.get("base_ref") != "main"
            or again.get("base_repo_id") is None
            or again.get("base_repo_id") != again.get("head_repo_id")
            or again.get("head") != expect_head or again.get("base") != expect_base
            or again.get("mergeable_state") != state.get("mergeable_state")):
        raise HandoffBlocked("pr-drifted", f"PR #{number} 复核期间目标、状态或 base/head 发生漂移")
    gated = human_gated(files)
    if gated:
        raise HandoffBlocked("needs-human-confirm", f"PR #{number} 触及人工确认两类：{sorted(gated)}")
    bindings = {name: app for name in MERGE_CHECKS
                if (app := required.get(name, GATED_APP_IDS.get(name))) is not None}
    checks = github.checks(expect_head, bindings)
    if mode == "merge":
        if not all(checks.get(name) == "success" for name in MERGE_CHECKS):
            raise HandoffBlocked("checks-not-green", f"PR #{number} 三项检查未全绿：{checks}")
    elif checks.get("deepagents/review") == "failure":
        raise HandoffBlocked("review-failed", f"PR #{number} 当前 head 已发布失败独审结论，拒绝追平")
    return {"state": again, "checks": checks}


def handoff_merge(github: HandoffGitHubPort, lane: ExternalReview, number: int, *,
                  expect_base: str, expect_head: str,
                  rows: Callable[[], Rows] = _ps_rows,
                  review_app: Callable[[], int | None] = configured_review_app) -> dict[str, Any]:
    """显式交接合入入口：持与 ExternalReview.target 相同的本机排他锁（外层 try_exclude_inflight_review +
    内层 _pr_lock，同锁序无死锁）直至 GitHub merge 写完成，持锁期间实时复核本机活跃进程、重审意图、
    当前合同已发布 PASS 与远端 exact (base_ref=main, base, head, mergeable_state, checks, 非敏感文件清单)。"""
    with lane.try_exclude_inflight_review(number) as excluded:
        if not excluded:
            raise HandoffBlocked("inflight-review-active", f"PR #{number} 正有本机预检/登记在途，拒绝合入")
        with lane._pr_lock(number):
            try:
                live_busy = reviewing(rows())
            except Exception as error:
                raise HandoffBlocked("process-table-unreadable", f"无法读取宿主活跃审查进程表：{type(error).__name__}") from None
            if number in live_busy:
                raise HandoffBlocked("review-running", f"PR #{number} 正有活跃审查进程，拒绝合入")
            if not _confirmed_published_pass(lane, number, expect_head, expect_base):
                raise HandoffBlocked(
                    "review-not-confirmed",
                    f"PR #{number} 缺少当前合同下精确 ({expect_base[:12]}, {expect_head[:12]}) 的已发布 PASS 或存在待完成重审意图",
                )
            _handoff_verify_remote(github, lane, number, expect_base=expect_base, expect_head=expect_head,
                                   mode="merge", review_app=review_app)
            result = github.merge(number, expect_head)
            return {"action": "handoff-merged", "pr": number, "base": expect_base, "head": expect_head, "result": result}


def handoff_update_branch(github: HandoffGitHubPort, lane: ExternalReview, number: int, *,
                          expect_base: str, expect_head: str,
                          rows: Callable[[], Rows] = _ps_rows,
                          review_app: Callable[[], int | None] = configured_review_app) -> dict[str, Any]:
    """显式交接追平入口：持同一本机排他重审锁直至 GitHub update-branch 写完成，持锁期间实时复核无活跃审查且
    远端确为指向 main 的 behind PR（精确 base/head、非敏感改动、无失败独审）。"""
    with lane.try_exclude_inflight_review(number) as excluded:
        if not excluded:
            raise HandoffBlocked("inflight-review-active", f"PR #{number} 正有本机预检/登记在途，拒绝追平")
        with lane._pr_lock(number):
            try:
                live_busy = reviewing(rows())
            except Exception as error:
                raise HandoffBlocked("process-table-unreadable", f"无法读取宿主活跃审查进程表：{type(error).__name__}") from None
            if number in live_busy:
                raise HandoffBlocked("review-running", f"PR #{number} 正有活跃审查进程，拒绝追平")
            _handoff_verify_remote(github, lane, number, expect_base=expect_base, expect_head=expect_head,
                                   mode="update", review_app=review_app)
            result = github.update_branch(number, expect_head)
            return {"action": "handoff-updated-branch", "pr": number, "base": expect_base, "head": expect_head, "result": result}


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
    def spawn(number: int, attempt: int, head: str, log: Path, base: str | None = None) -> int:
        log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = dict(os.environ)
        config = env.get("SANDCASTLE_CONFIG_FILE", "").strip()
        if config and not Path(config).is_absolute():
            env["SANDCASTLE_CONFIG_FILE"] = os.path.abspath(config)
        with open(log, "ab", opener=lambda p, f: os.open(p, f, 0o600)) as out:
            return subprocess.Popen(run_review_command(number, attempt, head, private_key, base), stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=out, start_new_session=True, env=env,
                                    cwd=Path(__file__).resolve().parents[1]).pid
    return spawn


def run_review(argv: list[str], github: GitHubPort | None = None) -> int:
    """子进程入口：先核对 PR 仍是决策时的 head 与 base，再把期望目标传给 external_review review-pr（登记前再次核验）。"""
    parser = argparse.ArgumentParser(prog="pilot1742.review_sweep run-review")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--expect-head", required=True)
    parser.add_argument("--expect-base", default=None)
    parser.add_argument("--private-key", required=True, type=Path)
    args = parser.parse_args(argv)
    live = (github or GhCli()).pr(args.pr)
    if live["head"] != args.expect_head:
        print(json.dumps({"pr": args.pr, "action": "head-moved-not-reviewed", "expected": args.expect_head}))
        return 3
    if args.expect_base is not None and live["base"] != args.expect_base:
        print(json.dumps({"pr": args.pr, "action": "base-moved-not-reviewed", "expected": args.expect_base,
                          "now": live["base"]}))
        return 3
    from . import external_review
    cmd = ["review-pr", "--pr", str(args.pr), "--attempt", str(args.attempt),
           "--private-key", str(args.private_key), "--expect-head", args.expect_head]
    if args.expect_base is not None:
        cmd.extend(["--expect-base", args.expect_base])
    return external_review.main(cmd)


def run_handoff_command(action: str, argv: list[str], *,
                        github: HandoffGitHubPort | None = None,
                        rows: Callable[[], Rows] = _ps_rows,
                        review_app: Callable[[], int | None] = configured_review_app) -> int:
    parser = argparse.ArgumentParser(prog=f"pilot1742.review_sweep {action}")
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expect-base", required=True)
    parser.add_argument("--expect-head", required=True)
    parser.add_argument("--state-root", type=Path, default=None)
    args = parser.parse_args(argv)
    lane = ExternalReview(None, state_root=args.state_root or STATE_ROOT)
    gh: HandoffGitHubPort = github or HandoffGhCli()
    try:
        fn = handoff_merge if action == "handoff-merge" else handoff_update_branch
        out = fn(gh, lane, args.pr, expect_base=args.expect_base, expect_head=args.expect_head,
                 rows=rows, review_app=review_app)
        print(json.dumps(out, ensure_ascii=False), flush=True)
        return 0
    except HandoffBlocked as error:
        print(json.dumps({"action": "handoff-blocked", "pr": args.pr, "code": error.code, "reason": error.reason},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return 2
    except (SourceUnreadable, EvidenceInsufficient, OSError, ValueError) as error:
        print(json.dumps({"action": "handoff-error", "pr": args.pr, "reason": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False), file=sys.stderr, flush=True)
        return 2


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run-review"]:
        return run_review(argv[1:])
    if argv[:1] in (["handoff-merge"], ["handoff-update-branch"]):
        return run_handoff_command(argv[0], argv[1:])
    parser = argparse.ArgumentParser(prog="pilot1742.review_sweep")
    parser.add_argument("--private-key", type=Path, help="只原样交给审查子进程（--handoff 只读模式不需要）")
    parser.add_argument("--state-root", type=Path, default=None, help="审查状态根（仅用于 --handoff 只读模式，默认 STATE_ROOT）")
    parser.add_argument("--handoff", action="store_true",
                        help="只读输出 sweep/merge-handoff.json 交接队列（供主控巡航或维护者消费追平与合入）")
    parser.add_argument("--max-running", type=int, default=2)
    parser.add_argument("--loop", type=float, default=0,
                        help=f"0 只跑一轮；循环时间隔至少 {MIN_LOOP_SECONDS:g} 秒（每轮每个 PR 约 4 次读接口，受 GitHub 核心限额约束）")
    parser.add_argument("--auto-merge", action="store_true",
                        help="默认关。用宿主 gh 凭据核验门禁、撤原生 auto-merge 并刷新 sweep/merge-handoff.json（不自动发起 merge/update-branch）")
    args = parser.parse_args(argv)
    if args.handoff:
        try:
            print(json.dumps(read_merge_handoff(args.state_root or STATE_ROOT), ensure_ascii=False, indent=2), flush=True)
            return 0
        except (OSError, ValueError) as error:
            print(json.dumps({"action": "handoff-unreadable", "reason": str(error)}, ensure_ascii=False), file=sys.stderr, flush=True)
            return 2
    if args.state_root is not None:
        parser.error("--state-root 仅用于 --handoff 只读模式")
    if args.private_key is None:
        parser.error("--private-key is required unless --handoff is set")
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
