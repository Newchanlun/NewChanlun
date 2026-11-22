"""#1926 合并队列（merge_group）只读顺序合并树等价与成员 PASS 沿用核验器。

核心不变量（Fail-Closed）：
1. 队列中每一位成员在自己的 head 上都必须具备经完整复验的正式 PASS 证据（直审或单跳 reused_from）；
2. 队列批次 head_sha 对应的树必须与「按队列顺序把各成员依次合入 base_sha」产生的树逐字节一致；
3. 所有 Git 查询与顺序合并重放均在独立临时 bare 仓库中执行（通过 alternates 只读挂接源对象库），
   既不向 source_repo 写入任何对象或引用，也不加载 source_repo 的本地 .git/config；
4. 任一条件不满足、对象缺失、存在冲突、证据损坏或不可核实，一律返回 verdict="ERROR" / status_state="error"。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_external_review_module: Any = importlib.import_module(".external_review", package=__package__ or "pilot1742")
_controller_message_blocks: Callable[[str], bool] = _external_review_module._message_blocks
_unwrap_json_fence: Callable[[str], str] = _external_review_module.unwrap_json_fence
_frozen_patch: Callable[[Path, Any], Any] = _external_review_module.frozen_patch
_ReviewTarget: Any = _external_review_module.ReviewTarget
if (
    not callable(_controller_message_blocks)
    or not callable(_unwrap_json_fence)
    or not callable(_frozen_patch)
    or not callable(_ReviewTarget)
):
    raise ImportError("pilot1742.external_review 必需接口不可调用")

_patch_read_module: Any = importlib.import_module(".patch_read", package=__package__ or "pilot1742")
_reads_candidate_patch: Callable[[str, str, Any], bool] = _patch_read_module.reads_candidate_patch
if not callable(_reads_candidate_patch):
    raise ImportError("pilot1742.patch_read.reads_candidate_patch 不可调用")

MERGE_GROUP_STATUS_CONTEXT = "deepagents/review"
DEFAULT_EXPECTED_MODELS: tuple[str, ...] = ("kimi-k3.1-pro", "claude-opus-5-5")
MAX_STATUS_DESCRIPTION_LEN = 140
MAX_JSON_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_LOG_EVIDENCE_BYTES = 64 * 1024 * 1024

_ALLOWED_QUEUE_ENTRY_STATES: frozenset[str] = frozenset(
    {"QUEUED", "AWAITING_CHECKS", "MERGEABLE", "LOCKED"}
)
_COMMIT_SHA_RE = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
_PATCH_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_CONTAINER_ID_RE = re.compile(r"[a-f0-9]{12,64}")
_SESSION_ID_RE = re.compile(r"[a-zA-Z0-9-]{1,100}")
_OBJECT_FORMAT_RE = re.compile(r"[a-z0-9]+")
_BRANCH_RE = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
_FORBIDDEN_REF_CHARS: frozenset[str] = frozenset("~^:?*[\\")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_MODEL_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_MERGE_GROUP_REF_RE = re.compile(
    r"(?:refs/heads/)?gh-readonly-queue/"
    r"(?P<base_branch>[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)/"
    r"pr-(?P<lead_pr>[1-9][0-9]*)-"
    r"(?P<base_sha>[0-9a-fA-F]{40}|[0-9a-fA-F]{64})"
)
_RUN_DIR_PREFIX_RE = re.compile(r"r(?P<repo>[1-9][0-9]*)-p(?P<pr>[1-9][0-9]*)-.*")
_RECONNECT_ERROR_RE = re.compile(
    r"Reconnecting\.\.\. ([1-9]\d*)/([1-9]\d*) \([^\r\n]+\)",
    re.ASCII,
)

_REASON_DESCRIPTIONS: dict[str, str] = {
    "merge_group_pass_reused": "顺序合并树与成员 PASS 核验通过",
    "missing_object": "缺少所需提交或树对象",
    "not_commit": "目标或成员对象非提交",
    "base_not_ancestor": "base_sha 非 head_sha 祖先",
    "head_tree_id_mismatch": "head_sha 树哈希与载荷声明不符",
    "merge_conflict": "顺序合并存在冲突",
    "merge_failed": "顺序合并重放失败",
    "replay_env_error": "隔离重放环境或 Git 执行故障",
    "overlap_query_failed": "跨成员重叠文件查询失败",
    "tree_mismatch": "顺序合并结果树与队列头不一致",
    "overlapping_files_rejected": "策略拒收跨成员重叠文件",
    "member_missing_pass": "成员缺少有效 PASS 证据",
    "member_migrated_not_allowed": "禁止沿用 migrated 结论",
    "member_blocked": "成员存在 BLOCK 阻断证据",
    "member_unsettled_run": "成员存在未完结审查 run",
    "member_pass_superseded": "成员旧 PASS 已被更晚登记记录取代",
    "member_repository_mismatch": "成员仓库身份不匹配",
    "member_policy_mismatch": "成员审查策略版本不匹配",
    "member_contract_mismatch": "成员审查合同不匹配",
    "member_controller_mismatch": "成员控制器代码版本不匹配",
    "member_image_mismatch": "成员审查镜像与部署策略不匹配",
    "member_merge_base_mismatch": "成员冻结 merge-base 与仓库历史不符",
    "member_patch_id_mismatch": "成员补丁身份与现场重算不符",
    "member_not_published_success": "成员未发布 success 终态",
    "member_publication_invalid": "成员发布记录绑定校验失败",
    "member_outcome_invalid": "成员 outcome 身份绑定校验失败",
    "member_models_mismatch": "成员双审模型集合不匹配",
    "member_launch_invalid": "成员 launch 证据缺失或绑定不符",
    "member_missing_receipt": "成员缺少审查回执",
    "member_receipt_invalid": "成员审查回执绑定或探针校验失败",
    "member_session_invalid": "成员独立 session 证据缺失或不符",
    "member_events_invalid": "成员审查事件流缺失或校验未通过",
    "member_reuse_not_allowed": "策略禁止单跳沿用 PASS",
    "member_chained_reuse_not_allowed": "禁止多跳或自引用沿用 PASS",
    "member_reuse_origin_missing": "找不到单跳沿用的原件审查 run",
    "member_reuse_admission_missing": "单跳沿用缺少部署准入记录",
    "member_reuse_binding_invalid": "单跳沿用来源绑定校验失败",
    "member_status_not_success": "成员远端已发布状态非 success",
    "member_evidence_corrupted": "成员审查证据损坏、越界或权限不安全",
}


class MergeGroupError(ValueError):
    """合并队列输入、边界或模型不变量校验失败。"""


class _EvidenceError(Exception):
    """内部异常：本地审查证据目录、权限、软链、大小或 JSON 内容异常。"""


class _GitQueryError(Exception):
    """内部异常：隔离 bare 仓库初始化、Git 信号中止或环境查询失败。"""


class _OverlapQueryError(Exception):
    """内部异常：合并后重叠文件 diff-tree 非零退出（非信号中止）。"""


def _split_lines_strict(text: str) -> list[str]:
    """仅按 ASCII LF / CRLF / CR 拆分行，避免 Unicode 行分隔符陷阱。"""
    if not text:
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _first_line_strict(text: str) -> str:
    if not text:
        return ""
    return _split_lines_strict(text)[0]


def _message_blocks(text: str) -> bool:
    """直接复用现役 external_review._message_blocks 判定 BLOCK；资源超限异常归因为证据损坏。"""
    try:
        return bool(_controller_message_blocks(text))
    except (RecursionError, MemoryError) as exc:
        raise _EvidenceError(f"消息 BLOCK 判定解码超限：{type(exc).__name__}") from None
    except (ValueError, TypeError):
        return True


def _parse_positive_int(raw: object, *, field: str) -> int:
    if type(raw) is not int or raw <= 0:
        raise MergeGroupError(f"{field} 必须是严格正整数（不接受 bool）：{raw!r}")
    return raw


def _parse_commit_sha(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not _COMMIT_SHA_RE.fullmatch(raw):
        raise MergeGroupError(f"{field} 必须是完整 40 位或 64 位十六进制 Git 提交 SHA：{raw!r}")
    return raw.lower()


def _parse_branch_name(raw: object, *, field: str = "base_branch") -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise MergeGroupError(f"{field} 必须是非空分支名且不含前导或尾随空白：{raw!r}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch.isspace() or ch in _FORBIDDEN_REF_CHARS for ch in raw):
        raise MergeGroupError(f"{field} 含有 Git check-ref-format 禁止的字符：{raw!r}")
    if (
        raw == "@"
        or ".." in raw
        or "@{" in raw
        or "//" in raw
        or raw.startswith("/")
        or raw.endswith("/")
        or raw.endswith(".")
    ):
        raise MergeGroupError(f"{field} 不符合 Git check-ref-format 规则：{raw!r}")
    if not _BRANCH_RE.fullmatch(raw):
        raise MergeGroupError(f"{field} 含有非法字符或路径穿越段：{raw!r}")
    segments = raw.split("/")
    for seg in segments:
        if not seg or seg.startswith(".") or seg.endswith(".lock"):
            raise MergeGroupError(f"{field} 含非法路径段（以 '.' 开头或以 '.lock' 结尾）：{raw!r}")
    return raw


def _parse_repository(raw: object, *, field: str = "repository") -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise MergeGroupError(f"{field} 必须是严格 owner/repo 格式：{raw!r}")
    if ".." in raw or not _REPOSITORY_RE.fullmatch(raw):
        raise MergeGroupError(f"{field} 格式非法或含路径穿越：{raw!r}")
    owner, repo = raw.split("/", 1)
    if owner in (".", "..") or repo in (".", ".."):
        raise MergeGroupError(f"{field} 含有非法路径段：{raw!r}")
    return raw


def _parse_nonempty_token(raw: object, *, field: str) -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise MergeGroupError(f"{field} 必须是非空且无首尾空白的字符串：{raw!r}")
    return raw


@dataclass(frozen=True)
class MergeGroupRef:
    """已解析且通过校验的 GitHub 合并队列只读引用。"""

    base_branch: str
    lead_pr: int
    base_sha: str
    canonical_ref: str

    def __post_init__(self) -> None:
        branch = _parse_branch_name(self.base_branch, field="MergeGroupRef.base_branch")
        lead_pr = _parse_positive_int(self.lead_pr, field="MergeGroupRef.lead_pr")
        base_sha = _parse_commit_sha(self.base_sha, field="MergeGroupRef.base_sha")
        expected_canonical = f"refs/heads/gh-readonly-queue/{branch}/pr-{lead_pr}-{base_sha}"
        if self.canonical_ref != expected_canonical:
            raise MergeGroupError(
                f"MergeGroupRef.canonical_ref 不一致：期望 {expected_canonical!r}，实际 {self.canonical_ref!r}"
            )
        object.__setattr__(self, "base_branch", branch)
        object.__setattr__(self, "base_sha", base_sha)


def parse_merge_group_ref(raw_ref: str, *, expected_base_branch: str = "main") -> MergeGroupRef:
    """解析并严格校验 GitHub 合并队列只读分支名。"""
    expected_branch = _parse_branch_name(expected_base_branch, field="expected_base_branch")
    if not isinstance(raw_ref, str) or not raw_ref or raw_ref != raw_ref.strip():
        raise MergeGroupError(f"head_ref 必须是非空字符串且不含前导或尾随空白：{raw_ref!r}")
    if "\n" in raw_ref or "\r" in raw_ref:
        raise MergeGroupError(f"head_ref 不能包含换行符：{raw_ref!r}")
    match = _MERGE_GROUP_REF_RE.fullmatch(raw_ref)
    if match is None:
        raise MergeGroupError(f"head_ref 不符合合并队列只读分支格式：{raw_ref!r}")
    base_branch = _parse_branch_name(match.group("base_branch"), field="head_ref.base_branch")
    if base_branch != expected_branch:
        raise MergeGroupError(
            f"head_ref 目标分支不匹配：期望 {expected_branch!r}，实际 {base_branch!r}"
        )
    lead_pr = _parse_positive_int(int(match.group("lead_pr")), field="head_ref.lead_pr")
    base_sha = _parse_commit_sha(match.group("base_sha"), field="head_ref.base_sha")
    canonical_ref = f"refs/heads/gh-readonly-queue/{base_branch}/pr-{lead_pr}-{base_sha}"
    return MergeGroupRef(
        base_branch=base_branch,
        lead_pr=lead_pr,
        base_sha=base_sha,
        canonical_ref=canonical_ref,
    )


@dataclass(frozen=True)
class MergeGroupMember:
    """合并队列批次中的单个 PR 成员。"""

    pr_number: int
    head_sha: str

    def __post_init__(self) -> None:
        _parse_positive_int(self.pr_number, field="member.pr_number")
        normalized_sha = _parse_commit_sha(self.head_sha, field="member.head_sha")
        object.__setattr__(self, "head_sha", normalized_sha)


@dataclass(frozen=True)
class MergeGroupTarget:
    """一次合并队列评估的强类型目标输入。"""

    repository_id: int
    repository: str
    base_sha: str
    head_sha: str
    head_ref: str
    members: tuple[MergeGroupMember, ...]
    base_branch: str = "main"
    expected_head_tree_sha: str | None = None

    def __post_init__(self) -> None:
        _parse_positive_int(self.repository_id, field="target.repository_id")
        repo = _parse_repository(self.repository, field="target.repository")
        branch = _parse_branch_name(self.base_branch, field="target.base_branch")
        base_sha = _parse_commit_sha(self.base_sha, field="target.base_sha")
        head_sha = _parse_commit_sha(self.head_sha, field="target.head_sha")
        parsed_ref = parse_merge_group_ref(self.head_ref, expected_base_branch=branch)
        if parsed_ref.base_sha != base_sha:
            raise MergeGroupError(
                f"head_ref 嵌入的 base_sha（{parsed_ref.base_sha}）与 target.base_sha（{base_sha}）不一致"
            )
        if not isinstance(self.members, tuple) or not self.members:
            raise MergeGroupError("target.members 必须是非空 MergeGroupMember 元组")
        seen_prs: set[int] = set()
        for member in self.members:
            if not isinstance(member, MergeGroupMember):
                raise MergeGroupError(f"target.members 含非 MergeGroupMember 元素：{member!r}")
            if member.pr_number in seen_prs:
                raise MergeGroupError(f"target.members 存在重复 PR 号：{member.pr_number}")
            seen_prs.add(member.pr_number)
        if self.members[-1].pr_number != parsed_ref.lead_pr:
            raise MergeGroupError(
                f"队列批次最后一位 PR（#{self.members[-1].pr_number}）与 head_ref 目标 PR（#{parsed_ref.lead_pr}）不一致"
            )
        expected_tree: str | None = None
        if self.expected_head_tree_sha is not None:
            expected_tree = _parse_commit_sha(
                self.expected_head_tree_sha,
                field="target.expected_head_tree_sha",
            )
        object.__setattr__(self, "repository", repo)
        object.__setattr__(self, "base_branch", branch)
        object.__setattr__(self, "base_sha", base_sha)
        object.__setattr__(self, "head_sha", head_sha)
        object.__setattr__(self, "head_ref", parsed_ref.canonical_ref)
        object.__setattr__(self, "expected_head_tree_sha", expected_tree)

    @property
    def parsed_ref(self) -> MergeGroupRef:
        return parse_merge_group_ref(self.head_ref, expected_base_branch=self.base_branch)


def parse_merge_group_event(
    payload: Mapping[str, Any],
    *,
    members: Sequence[MergeGroupMember],
    expected_base_branch: str = "main",
    expected_repository_id: int | None = None,
    expected_repository: str | None = None,
) -> MergeGroupTarget:
    """解析 GitHub merge_group webhook 载荷（仅接受 checks_requested）。"""
    if not isinstance(payload, Mapping):
        raise MergeGroupError("webhook payload 必须是映射对象")
    action = payload.get("action")
    if action != "checks_requested":
        raise MergeGroupError(f"仅接受 action='checks_requested'，收到：{action!r}")

    merge_group = payload.get("merge_group")
    if not isinstance(merge_group, Mapping):
        raise MergeGroupError("webhook 缺少合法的 merge_group 对象")
    repo_obj = payload.get("repository")
    if not isinstance(repo_obj, Mapping):
        raise MergeGroupError("webhook 缺少合法的 repository 对象")

    repo_id = _parse_positive_int(repo_obj.get("id"), field="repository.id")
    repo_name = _parse_repository(repo_obj.get("full_name"), field="repository.full_name")

    if expected_repository_id is not None:
        exp_id = _parse_positive_int(expected_repository_id, field="expected_repository_id")
        if repo_id != exp_id:
            raise MergeGroupError(f"repository.id 不匹配：期望 {exp_id}，实际 {repo_id}")
    if expected_repository is not None:
        exp_repo = _parse_repository(expected_repository, field="expected_repository")
        if repo_name != exp_repo:
            raise MergeGroupError(f"repository.full_name 不匹配：期望 {exp_repo!r}，实际 {repo_name!r}")

    base_branch = _parse_branch_name(expected_base_branch, field="expected_base_branch")
    expected_base_ref = f"refs/heads/{base_branch}"
    base_ref = merge_group.get("base_ref")
    if base_ref != expected_base_ref:
        raise MergeGroupError(f"merge_group.base_ref 不匹配：期望 {expected_base_ref!r}，实际 {base_ref!r}")

    base_sha = _parse_commit_sha(merge_group.get("base_sha"), field="merge_group.base_sha")
    head_sha = _parse_commit_sha(merge_group.get("head_sha"), field="merge_group.head_sha")
    raw_head_ref = merge_group.get("head_ref")
    if not isinstance(raw_head_ref, str):
        raise MergeGroupError("merge_group.head_ref 必须是字符串")
    parsed_ref = parse_merge_group_ref(raw_head_ref, expected_base_branch=base_branch)
    if parsed_ref.base_sha != base_sha:
        raise MergeGroupError("merge_group.head_ref 中的 base_sha 与 merge_group.base_sha 不一致")

    expected_head_tree_sha: str | None = None
    if "head_commit" in merge_group and merge_group["head_commit"] is not None:
        head_commit = merge_group["head_commit"]
        if not isinstance(head_commit, Mapping):
            raise MergeGroupError("merge_group.head_commit 必须是映射对象")
        commit_id = _parse_commit_sha(head_commit.get("id"), field="merge_group.head_commit.id")
        if commit_id != head_sha:
            raise MergeGroupError(
                f"merge_group.head_commit.id（{commit_id}）与 merge_group.head_sha（{head_sha}）不一致"
            )
        if "tree_id" in head_commit and head_commit["tree_id"] is not None:
            expected_head_tree_sha = _parse_commit_sha(
                head_commit["tree_id"],
                field="merge_group.head_commit.tree_id",
            )

    if isinstance(members, (str, bytes)) or not isinstance(members, Sequence) or not members:
        raise MergeGroupError("members 必须是非空 MergeGroupMember 序列")
    member_tuple = tuple(members)

    return MergeGroupTarget(
        repository_id=repo_id,
        repository=repo_name,
        base_branch=base_branch,
        base_sha=base_sha,
        head_sha=head_sha,
        head_ref=parsed_ref.canonical_ref,
        members=member_tuple,
        expected_head_tree_sha=expected_head_tree_sha,
    )


@dataclass(frozen=True)
class _ParsedQueueEntry:
    position: int
    state: str
    base_oid: str
    head_oid: str
    pr_number: int
    pr_head_oid: str
    head_ref_name: str | None
    head_tree_oid: str | None


def _extract_graphql_repository_node(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise MergeGroupError("GraphQL 载荷必须是映射对象")
    if "errors" in payload and payload["errors"]:
        raise MergeGroupError(f"GraphQL 响应包含 errors：{payload['errors']!r}")
    if "data" in payload:
        data = payload["data"]
        if not isinstance(data, Mapping):
            raise MergeGroupError("GraphQL data 字段必须是映射对象")
        repo_node = data.get("repository")
        if not isinstance(repo_node, Mapping):
            raise MergeGroupError("GraphQL data.repository 缺失或不是映射对象")
        return repo_node
    if "mergeQueue" in payload:
        return payload
    raise MergeGroupError("无法识别的 GraphQL 合并队列载荷结构")


def _extract_graphql_repo_identity(
    repo_node: Mapping[str, Any],
    *,
    expected_repository_id: int | None,
    expected_repository: str | None,
) -> tuple[int, str]:
    raw_repo_id: object = None
    if "databaseId" in repo_node and repo_node["databaseId"] is not None:
        raw_repo_id = repo_node["databaseId"]
    elif "id" in repo_node and type(repo_node["id"]) is int:
        raw_repo_id = repo_node["id"]
    elif expected_repository_id is not None:
        raw_repo_id = expected_repository_id
    else:
        raise MergeGroupError("GraphQL repository 缺少 databaseId，且未提供 expected_repository_id")
    repo_id = _parse_positive_int(raw_repo_id, field="repository.databaseId")
    if expected_repository_id is not None:
        exp_id = _parse_positive_int(expected_repository_id, field="expected_repository_id")
        if repo_id != exp_id:
            raise MergeGroupError(f"repository.databaseId 不匹配：期望 {exp_id}，实际 {repo_id}")

    raw_repo_name: object = None
    if "nameWithOwner" in repo_node and repo_node["nameWithOwner"] is not None:
        raw_repo_name = repo_node["nameWithOwner"]
    elif "full_name" in repo_node and repo_node["full_name"] is not None:
        raw_repo_name = repo_node["full_name"]
    elif isinstance(repo_node.get("owner"), Mapping) and isinstance(repo_node.get("name"), str):
        owner_login = repo_node["owner"].get("login")
        if isinstance(owner_login, str):
            raw_repo_name = f"{owner_login}/{repo_node['name']}"
    elif expected_repository is not None:
        raw_repo_name = expected_repository
    else:
        raise MergeGroupError("GraphQL repository 缺少 nameWithOwner，且未提供 expected_repository")
    repo_name = _parse_repository(raw_repo_name, field="repository.nameWithOwner")
    if expected_repository is not None:
        exp_repo = _parse_repository(expected_repository, field="expected_repository")
        if repo_name != exp_repo:
            raise MergeGroupError(f"repository.nameWithOwner 不匹配：期望 {exp_repo!r}，实际 {repo_name!r}")
    return repo_id, repo_name


def _parse_single_queue_entry(raw_entry: Mapping[str, Any], index: int) -> _ParsedQueueEntry:
    position = _parse_positive_int(raw_entry.get("position"), field=f"entries.nodes[{index}].position")
    state = raw_entry.get("state")
    if not isinstance(state, str) or not state:
        raise MergeGroupError(f"entries.nodes[{index}].state 必须是非空字符串：{state!r}")

    base_commit = raw_entry.get("baseCommit")
    if not isinstance(base_commit, Mapping):
        raise MergeGroupError(f"entries.nodes[{index}].baseCommit 必须是映射对象")
    base_oid = _parse_commit_sha(base_commit.get("oid"), field=f"entries.nodes[{index}].baseCommit.oid")

    head_commit = raw_entry.get("headCommit")
    if not isinstance(head_commit, Mapping):
        raise MergeGroupError(f"entries.nodes[{index}].headCommit 必须是映射对象")
    head_oid = _parse_commit_sha(head_commit.get("oid"), field=f"entries.nodes[{index}].headCommit.oid")

    head_tree_oid: str | None = None
    if "tree" in head_commit and head_commit["tree"] is not None:
        tree_obj = head_commit["tree"]
        if not isinstance(tree_obj, Mapping):
            raise MergeGroupError(f"entries.nodes[{index}].headCommit.tree 必须是映射对象")
        head_tree_oid = _parse_commit_sha(
            tree_obj.get("oid"),
            field=f"entries.nodes[{index}].headCommit.tree.oid",
        )

    pr_obj = raw_entry.get("pullRequest")
    if not isinstance(pr_obj, Mapping):
        raise MergeGroupError(f"entries.nodes[{index}].pullRequest 必须是映射对象")
    pr_number = _parse_positive_int(
        pr_obj.get("number"),
        field=f"entries.nodes[{index}].pullRequest.number",
    )
    pr_head_oid = _parse_commit_sha(
        pr_obj.get("headRefOid"),
        field=f"entries.nodes[{index}].pullRequest.headRefOid",
    )

    head_ref_name: str | None = None
    if "headRefName" in raw_entry and raw_entry["headRefName"] is not None:
        raw_ref_name = raw_entry["headRefName"]
        if not isinstance(raw_ref_name, str) or not raw_ref_name:
            raise MergeGroupError(f"entries.nodes[{index}].headRefName 必须是非空字符串")
        head_ref_name = raw_ref_name

    return _ParsedQueueEntry(
        position=position,
        state=state,
        base_oid=base_oid,
        head_oid=head_oid,
        pr_number=pr_number,
        pr_head_oid=pr_head_oid,
        head_ref_name=head_ref_name,
        head_tree_oid=head_tree_oid,
    )


def parse_merge_queue_entries(
    payload: Mapping[str, Any],
    *,
    target_head_sha: str,
    expected_base_branch: str = "main",
    expected_repository_id: int | None = None,
    expected_repository: str | None = None,
) -> MergeGroupTarget:
    """两阶段解析 GitHub GraphQL mergeQueue.entries 响应并提取完整连续前缀。

    阶段 1：最小定位目标条目 T（全量校验映射类型、正整数 position 唯一性，仅在 headCommit 非 None 时匹配 oid）；
    阶段 2：仅对必需前缀 1..T.position 执行严格校验，允许 T 之后尚未生成 commit 的合法队尾条目为 null。
    """
    target_sha = _parse_commit_sha(target_head_sha, field="target_head_sha")
    base_branch = _parse_branch_name(expected_base_branch, field="expected_base_branch")
    repo_node = _extract_graphql_repository_node(payload)
    repo_id, repo_name = _extract_graphql_repo_identity(
        repo_node,
        expected_repository_id=expected_repository_id,
        expected_repository=expected_repository,
    )

    merge_queue = repo_node.get("mergeQueue")
    if not isinstance(merge_queue, Mapping):
        raise MergeGroupError("repository.mergeQueue 缺失或不是映射对象")
    if "branch" in merge_queue and merge_queue["branch"] is not None:
        branch_field = merge_queue["branch"]
        actual_branch = branch_field.get("name") if isinstance(branch_field, Mapping) else branch_field
        if actual_branch != base_branch:
            raise MergeGroupError(
                f"mergeQueue 目标分支不匹配：期望 {base_branch!r}，实际 {actual_branch!r}"
            )

    entries_obj = merge_queue.get("entries")
    if not isinstance(entries_obj, Mapping):
        raise MergeGroupError("mergeQueue.entries 缺失或不是映射对象")

    has_next_page = False
    if "pageInfo" in entries_obj and entries_obj["pageInfo"] is not None:
        page_info = entries_obj["pageInfo"]
        if not isinstance(page_info, Mapping):
            raise MergeGroupError("mergeQueue.entries.pageInfo 必须是映射对象")
        raw_has_next = page_info.get("hasNextPage", False)
        if type(raw_has_next) is not bool:
            raise MergeGroupError("mergeQueue.entries.pageInfo.hasNextPage 必须是布尔值")
        has_next_page = raw_has_next

    nodes = entries_obj.get("nodes")
    if not isinstance(nodes, list):
        raise MergeGroupError("mergeQueue.entries.nodes 必须是列表")
    if not nodes:
        if has_next_page:
            raise MergeGroupError("mergeQueue.entries.nodes 为空且 pageInfo.hasNextPage=true，列表被截断")
        raise MergeGroupError("mergeQueue.entries.nodes 为空，找不到目标队列条目")

    # 阶段 1：全量最小定位
    raw_by_position: dict[int, tuple[int, Mapping[str, Any]]] = {}
    matched_positions: list[int] = []
    for idx, raw_entry in enumerate(nodes):
        if not isinstance(raw_entry, Mapping):
            raise MergeGroupError(f"entries.nodes[{idx}] 必须是映射对象")
        position = _parse_positive_int(raw_entry.get("position"), field=f"entries.nodes[{idx}].position")
        if position in raw_by_position:
            raise MergeGroupError(f"mergeQueue 存在重复 position={position}")
        raw_by_position[position] = (idx, raw_entry)

        head_commit = raw_entry.get("headCommit")
        if head_commit is not None:
            if not isinstance(head_commit, Mapping):
                raise MergeGroupError(f"entries.nodes[{idx}].headCommit 必须是映射对象或 null")
            raw_head_oid = head_commit.get("oid")
            if raw_head_oid is not None:
                head_oid = _parse_commit_sha(raw_head_oid, field=f"entries.nodes[{idx}].headCommit.oid")
                if head_oid == target_sha:
                    matched_positions.append(position)

    if not matched_positions:
        if has_next_page:
            raise MergeGroupError(
                f"未找到 target_head_sha={target_sha} 且 pageInfo.hasNextPage=true，队列列表被截断"
            )
        raise MergeGroupError(f"在 mergeQueue.entries 中未找到 target_head_sha={target_sha}")
    if len(matched_positions) > 1:
        raise MergeGroupError(f"在 mergeQueue.entries 中发现多个重复的 target_head_sha={target_sha}")
    target_position = matched_positions[0]

    # 阶段 2：仅对必需前缀 1..target_position 执行连续性与严格字段校验
    prefix: list[_ParsedQueueEntry] = []
    for pos in range(1, target_position + 1):
        slot = raw_by_position.get(pos)
        if slot is None:
            truncation_hint = "（pageInfo.hasNextPage=true，疑似分页截断）" if has_next_page else ""
            raise MergeGroupError(
                f"合并队列前缀不连续：缺少 position={pos}（目标 position={target_position}）{truncation_hint}"
            )
        idx, raw_entry = slot
        prefix.append(_parse_single_queue_entry(raw_entry, idx))

    target_entry = prefix[-1]
    seen_prs: set[int] = set()
    for entry in prefix:
        if entry.state not in _ALLOWED_QUEUE_ENTRY_STATES:
            raise MergeGroupError(
                f"队列成员 PR #{entry.pr_number}（position={entry.position}）状态非法：{entry.state!r}"
            )
        if entry.base_oid != target_entry.base_oid:
            raise MergeGroupError(
                f"队列成员 PR #{entry.pr_number} 的 baseCommit.oid（{entry.base_oid}）"
                f"与目标 baseCommit.oid（{target_entry.base_oid}）不一致"
            )
        if entry.pr_number in seen_prs:
            raise MergeGroupError(f"队列前缀中存在重复 PR 号：#{entry.pr_number}")
        seen_prs.add(entry.pr_number)
        if entry.head_ref_name is not None:
            parsed_entry_ref = parse_merge_group_ref(
                entry.head_ref_name,
                expected_base_branch=base_branch,
            )
            if parsed_entry_ref.lead_pr != entry.pr_number or parsed_entry_ref.base_sha != entry.base_oid:
                raise MergeGroupError(
                    f"队列成员 PR #{entry.pr_number} 的 headRefName（{entry.head_ref_name!r}）与条目不符"
                )

    if target_entry.head_ref_name is not None:
        canonical_ref = parse_merge_group_ref(
            target_entry.head_ref_name,
            expected_base_branch=base_branch,
        ).canonical_ref
    else:
        canonical_ref = (
            f"refs/heads/gh-readonly-queue/{base_branch}/"
            f"pr-{target_entry.pr_number}-{target_entry.base_oid}"
        )

    members = tuple(MergeGroupMember(entry.pr_number, entry.pr_head_oid) for entry in prefix)
    return MergeGroupTarget(
        repository_id=repo_id,
        repository=repo_name,
        base_branch=base_branch,
        base_sha=target_entry.base_oid,
        head_sha=target_entry.head_oid,
        head_ref=canonical_ref,
        members=members,
        expected_head_tree_sha=target_entry.head_tree_oid,
    )


def _git_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_AUTHOR_NAME="Merge Group Verifier",
        GIT_AUTHOR_EMAIL="merge-group-verifier@invalid.local",
        GIT_AUTHOR_DATE="1700000000 +0000",
        GIT_COMMITTER_NAME="Merge Group Verifier",
        GIT_COMMITTER_EMAIL="merge-group-verifier@invalid.local",
        GIT_COMMITTER_DATE="1700000000 +0000",
    )
    return env


def _run_git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    run_env = dict(env) if env is not None else _git_env()
    completed = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "gc.auto=0",
            "-C",
            str(repo),
            *args,
        ],
        env=run_env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    if completed.returncode < 0:
        raise _GitQueryError(f"git 进程被信号中止（returncode={completed.returncode}）")
    return completed


def _inspect_source_repo(source_repo: Path) -> tuple[Path, str]:
    """仅读取源仓 common objects 目录与对象哈希格式，不执行任何合并或 diff 命令。"""
    env = _git_env()
    common_proc = _run_git(
        source_repo,
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
        env=env,
    )
    if common_proc.returncode != 0:
        raise _GitQueryError(f"无法解析源仓库 git-common-dir：{source_repo}")
    common_dir_raw = _first_line_strict(common_proc.stdout.decode("utf-8", errors="replace")).strip()
    if not common_dir_raw or "\n" in common_dir_raw or "\r" in common_dir_raw:
        raise _GitQueryError(f"源仓库 git-common-dir 非法：{source_repo}")
    objects_dir = Path(common_dir_raw) / "objects"
    if not objects_dir.is_dir():
        raise _GitQueryError(f"源仓库 objects 目录不存在：{objects_dir}")

    fmt_proc = _run_git(source_repo, "rev-parse", "--show-object-format", env=env)
    if fmt_proc.returncode != 0:
        raise _GitQueryError(f"无法解析源仓库 object-format：{source_repo}")
    obj_format = _first_line_strict(fmt_proc.stdout.decode("utf-8", errors="replace")).strip()
    if not _OBJECT_FORMAT_RE.fullmatch(obj_format):
        raise _GitQueryError(f"源仓库 object-format 非法：{obj_format!r}")
    return objects_dir, obj_format


@contextmanager
def _isolated_replay_repo(source_repo: Path) -> Iterator[Path]:
    """在临时目录构造独立空 bare 仓，通过 alternates 只读挂接源对象库，彻底隔离源仓 local .git/config。"""
    source_objects, obj_format = _inspect_source_repo(source_repo)
    alternates: list[str] = [str(source_objects)]
    existing_alternates = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES", "")
    if existing_alternates:
        for entry in existing_alternates.split(os.pathsep):
            if entry and "\n" not in entry and "\r" not in entry and entry not in alternates:
                alternates.append(entry)

    env = _git_env()
    with tempfile.TemporaryDirectory(prefix="merge-group-replay-") as tmp_root:
        replay_repo = Path(tmp_root) / "replay.git"
        replay_repo.mkdir(mode=0o700)
        init_proc = _run_git(
            replay_repo,
            "init",
            "--bare",
            "--quiet",
            "--template=",
            f"--object-format={obj_format}",
            env=env,
        )
        if init_proc.returncode != 0:
            raise _GitQueryError(f"初始化隔离 bare 仓库失败（exit={init_proc.returncode}）")
        alternates_file = replay_repo / "objects" / "info" / "alternates"
        alternates_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        alternates_file.write_text("\n".join(alternates) + "\n", encoding="utf-8")
        yield replay_repo


def _compute_patch_identity_in_repo(replay_repo: Path, merge_base_sha: str, head_sha: str) -> str:
    mb = _parse_commit_sha(merge_base_sha, field="merge_base_sha")
    head = _parse_commit_sha(head_sha, field="head_sha")
    proc = _run_git(
        replay_repo,
        "diff-tree",
        "-r",
        "--raw",
        "-z",
        "--no-renames",
        "--no-abbrev",
        mb,
        head,
        env=_git_env(),
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise MergeGroupError(f"无法计算补丁身份（{mb}..{head}）：{stderr}")
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest()


def compute_patch_identity(source_repo: Path, merge_base_sha: str, head_sha: str) -> str:
    """在隔离 bare 仓中用 git plumbing 重算补丁身份（与 external_review.patch_identity 逐字节一致）。"""
    mb = _parse_commit_sha(merge_base_sha, field="merge_base_sha")
    head = _parse_commit_sha(head_sha, field="head_sha")
    try:
        with _isolated_replay_repo(source_repo) as replay_repo:
            return _compute_patch_identity_in_repo(replay_repo, mb, head)
    except (_GitQueryError, OSError, subprocess.SubprocessError) as exc:
        raise MergeGroupError(f"无法初始化隔离对象库计算补丁身份：{type(exc).__name__}") from None


@dataclass(frozen=True)
class TreeVerificationResult:
    """只读顺序合并树等价核验结果。"""

    matched: bool
    reason_code: str
    detail: str
    base_tree_sha: str | None
    actual_tree_sha: str | None
    expected_tree_sha: str | None
    step_trees: tuple[tuple[int, str], ...]
    overlapping_files: tuple[str, ...]


def _collect_touched_paths(
    replay_repo: Path,
    before_tree_sha: str,
    after_tree_sha: str,
    *,
    env: Mapping[str, str],
) -> set[str]:
    """统计本步合并前后树对象之间实际引入/改动的文件路径；查询失败立即抛错。"""
    diff_proc = _run_git(
        replay_repo,
        "diff-tree",
        "-r",
        "--name-only",
        "-z",
        "--no-renames",
        before_tree_sha,
        after_tree_sha,
        env=env,
    )
    if diff_proc.returncode != 0:
        stderr = diff_proc.stderr.decode("utf-8", errors="replace").strip()
        raise _OverlapQueryError(
            f"重叠文件查询 diff-tree 失败（exit={diff_proc.returncode}）：{stderr}"
        )
    paths: set[str] = set()
    for raw_path in diff_proc.stdout.split(b"\x00"):
        if raw_path:
            paths.add(raw_path.decode("utf-8", errors="surrogateescape"))
    return paths


def _verify_merge_group_tree_in_repo(
    target: MergeGroupTarget,
    *,
    replay_repo: Path,
) -> TreeVerificationResult:
    replay_env = _git_env()

    # 1. 验证 base_sha、head_sha 与全部成员 head_sha 均为真实 commit 对象
    required_commits: list[tuple[str, str]] = [
        ("base_sha", target.base_sha),
        ("head_sha", target.head_sha),
        *((f"PR #{m.pr_number} head_sha", m.head_sha) for m in target.members),
    ]
    checked_shas: set[str] = set()
    for label, sha in required_commits:
        if sha in checked_shas:
            continue
        cat_proc = _run_git(replay_repo, "cat-file", "-t", sha, env=replay_env)
        if cat_proc.returncode != 0:
            return TreeVerificationResult(
                matched=False,
                reason_code="missing_object",
                detail=f"对象库缺少对象 {label}={sha}",
                base_tree_sha=None,
                actual_tree_sha=None,
                expected_tree_sha=None,
                step_trees=(),
                overlapping_files=(),
            )
        obj_type = _first_line_strict(cat_proc.stdout.decode("utf-8", errors="replace")).strip()
        if obj_type != "commit":
            return TreeVerificationResult(
                matched=False,
                reason_code="not_commit",
                detail=f"{label}={sha} 的对象类型为 {obj_type!r}，不是 commit",
                base_tree_sha=None,
                actual_tree_sha=None,
                expected_tree_sha=None,
                step_trees=(),
                overlapping_files=(),
            )
        checked_shas.add(sha)

    # 2. 验证 base_sha 是 head_sha 的祖先
    anc_proc = _run_git(replay_repo, "merge-base", "--is-ancestor", target.base_sha, target.head_sha, env=replay_env)
    if anc_proc.returncode == 1:
        return TreeVerificationResult(
            matched=False,
            reason_code="base_not_ancestor",
            detail=f"base_sha={target.base_sha} 不是 head_sha={target.head_sha} 的祖先提交",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )
    if anc_proc.returncode != 0:
        stderr = anc_proc.stderr.decode("utf-8", errors="replace").strip()
        return TreeVerificationResult(
            matched=False,
            reason_code="merge_failed",
            detail=f"祖先关系检查失败：{stderr}",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )

    # 3. 解析 base_tree_sha 与 actual_tree_sha，并校验可选 expected_head_tree_sha
    base_tree_proc = _run_git(replay_repo, "rev-parse", f"{target.base_sha}^{{tree}}", env=replay_env)
    actual_tree_proc = _run_git(replay_repo, "rev-parse", f"{target.head_sha}^{{tree}}", env=replay_env)
    if base_tree_proc.returncode != 0 or actual_tree_proc.returncode != 0:
        return TreeVerificationResult(
            matched=False,
            reason_code="missing_object",
            detail="无法解析 base_sha 或 head_sha 对应的树对象",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )
    base_tree_sha = _first_line_strict(base_tree_proc.stdout.decode("utf-8", errors="replace")).strip().lower()
    actual_tree_sha = _first_line_strict(actual_tree_proc.stdout.decode("utf-8", errors="replace")).strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(base_tree_sha) or not _COMMIT_SHA_RE.fullmatch(actual_tree_sha):
        return TreeVerificationResult(
            matched=False,
            reason_code="merge_failed",
            detail="解析得到的 tree 对象 ID 格式非法",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )

    if target.expected_head_tree_sha is not None and target.expected_head_tree_sha != actual_tree_sha:
        return TreeVerificationResult(
            matched=False,
            reason_code="head_tree_id_mismatch",
            detail=(
                f"载荷声明的 head tree（{target.expected_head_tree_sha}）"
                f"与仓库实际 head_sha^{{tree}}（{actual_tree_sha}）不一致"
            ),
            base_tree_sha=base_tree_sha,
            actual_tree_sha=actual_tree_sha,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )

    # 4. 在独立 bare 仓中顺序重放合并（零写 source_repo，零读 source_repo/.git/config）
    step_trees: list[tuple[int, str]] = []
    touched_by_path: dict[str, set[int]] = {}

    def _current_overlaps() -> tuple[str, ...]:
        return tuple(sorted(path for path, prs in touched_by_path.items() if len(prs) >= 2))

    current_commit = target.base_sha
    current_tree_sha = base_tree_sha
    for idx, member in enumerate(target.members):
        merge_proc = _run_git(
            replay_repo,
            "merge-tree",
            "--write-tree",
            "--no-messages",
            current_commit,
            member.head_sha,
            env=replay_env,
        )
        if merge_proc.returncode == 1:
            return TreeVerificationResult(
                matched=False,
                reason_code="merge_conflict",
                detail=f"按队列顺序合入 PR #{member.pr_number}（{member.head_sha[:12]}）时发生合并冲突",
                base_tree_sha=base_tree_sha,
                actual_tree_sha=actual_tree_sha,
                expected_tree_sha=None,
                step_trees=tuple(step_trees),
                overlapping_files=_current_overlaps(),
            )
        if merge_proc.returncode != 0:
            stderr = merge_proc.stderr.decode("utf-8", errors="replace").strip()
            return TreeVerificationResult(
                matched=False,
                reason_code="merge_failed",
                detail=f"合入 PR #{member.pr_number} 时 git merge-tree 失败（exit={merge_proc.returncode}）：{stderr}",
                base_tree_sha=base_tree_sha,
                actual_tree_sha=actual_tree_sha,
                expected_tree_sha=None,
                step_trees=tuple(step_trees),
                overlapping_files=_current_overlaps(),
            )

        step_tree_sha = _first_line_strict(
            merge_proc.stdout.decode("utf-8", errors="replace")
        ).strip().lower()
        if not _COMMIT_SHA_RE.fullmatch(step_tree_sha):
            return TreeVerificationResult(
                matched=False,
                reason_code="merge_failed",
                detail=f"合入 PR #{member.pr_number} 返回了非法 tree SHA：{step_tree_sha!r}",
                base_tree_sha=base_tree_sha,
                actual_tree_sha=actual_tree_sha,
                expected_tree_sha=None,
                step_trees=tuple(step_trees),
                overlapping_files=_current_overlaps(),
            )

        # merge-tree 成功后直接对比本步合入前后树差异；任何查询失败均 fail-closed 报 overlap_query_failed
        try:
            touched_paths = _collect_touched_paths(
                replay_repo,
                current_tree_sha,
                step_tree_sha,
                env=replay_env,
            )
        except _OverlapQueryError as exc:
            return TreeVerificationResult(
                matched=False,
                reason_code="overlap_query_failed",
                detail=f"PR #{member.pr_number} 重叠文件统计失败：{exc}",
                base_tree_sha=base_tree_sha,
                actual_tree_sha=actual_tree_sha,
                expected_tree_sha=None,
                step_trees=tuple(step_trees),
                overlapping_files=_current_overlaps(),
            )
        for touched_path in touched_paths:
            touched_by_path.setdefault(touched_path, set()).add(member.pr_number)

        step_trees.append((member.pr_number, step_tree_sha))
        current_tree_sha = step_tree_sha

        if idx + 1 < len(target.members):
            commit_proc = _run_git(
                replay_repo,
                "commit-tree",
                step_tree_sha,
                "-p",
                current_commit,
                "-p",
                member.head_sha,
                "-m",
                "merge-group-step",
                env=replay_env,
            )
            if commit_proc.returncode != 0:
                stderr = commit_proc.stderr.decode("utf-8", errors="replace").strip()
                return TreeVerificationResult(
                    matched=False,
                    reason_code="merge_failed",
                    detail=f"创建临时合并提交失败（PR #{member.pr_number}）：{stderr}",
                    base_tree_sha=base_tree_sha,
                    actual_tree_sha=actual_tree_sha,
                    expected_tree_sha=None,
                    step_trees=tuple(step_trees),
                    overlapping_files=_current_overlaps(),
                )
            next_commit = _first_line_strict(
                commit_proc.stdout.decode("utf-8", errors="replace")
            ).strip().lower()
            if not _COMMIT_SHA_RE.fullmatch(next_commit):
                return TreeVerificationResult(
                    matched=False,
                    reason_code="merge_failed",
                    detail=f"git commit-tree 返回非法提交 SHA：{next_commit!r}",
                    base_tree_sha=base_tree_sha,
                    actual_tree_sha=actual_tree_sha,
                    expected_tree_sha=None,
                    step_trees=tuple(step_trees),
                    overlapping_files=_current_overlaps(),
                )
            current_commit = next_commit

    expected_tree_sha = step_trees[-1][1]
    overlaps = _current_overlaps()
    if expected_tree_sha != actual_tree_sha:
        return TreeVerificationResult(
            matched=False,
            reason_code="tree_mismatch",
            detail=(
                f"顺序合并期望树（{expected_tree_sha}）与队列 head_sha^{{tree}}（{actual_tree_sha}）不一致"
            ),
            base_tree_sha=base_tree_sha,
            actual_tree_sha=actual_tree_sha,
            expected_tree_sha=expected_tree_sha,
            step_trees=tuple(step_trees),
            overlapping_files=overlaps,
        )

    return TreeVerificationResult(
        matched=True,
        reason_code="tree_matched",
        detail=f"顺序合并树与队列 head_sha^{{tree}} 一致（{actual_tree_sha}）",
        base_tree_sha=base_tree_sha,
        actual_tree_sha=actual_tree_sha,
        expected_tree_sha=expected_tree_sha,
        step_trees=tuple(step_trees),
        overlapping_files=overlaps,
    )


def verify_merge_group_tree(
    target: MergeGroupTarget,
    *,
    source_repo: Path,
) -> TreeVerificationResult:
    """在独立临时 bare 仓中顺序重放合并，并比对最终树与 head_sha^{tree} 是否逐字节一致。"""
    if not isinstance(target, MergeGroupTarget):
        raise MergeGroupError("target 必须是 MergeGroupTarget 实例")
    try:
        with _isolated_replay_repo(source_repo) as replay_repo:
            return _verify_merge_group_tree_in_repo(target, replay_repo=replay_repo)
    except (_GitQueryError, OSError, subprocess.SubprocessError) as exc:
        return TreeVerificationResult(
            matched=False,
            reason_code="replay_env_error",
            detail=f"隔离重放环境或 Git 执行故障：{type(exc).__name__}",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )


@dataclass(frozen=True)
class MergeGroupPolicy:
    """合并队列 PASS 沿用策略配置。"""

    policy_version: str
    review_contract: str
    controller_code_head: str
    deployment_image_id: str
    expected_models: tuple[str, ...] = DEFAULT_EXPECTED_MODELS
    allow_single_hop_reused_pass: bool = True
    reject_overlapping_files: bool = False
    check_file_ownership: bool = True

    def __post_init__(self) -> None:
        policy_version = _parse_nonempty_token(self.policy_version, field="policy.policy_version")
        review_contract = _parse_nonempty_token(self.review_contract, field="policy.review_contract")
        controller_head = _parse_commit_sha(self.controller_code_head, field="policy.controller_code_head")
        if not isinstance(self.deployment_image_id, str) or not _IMAGE_ID_RE.fullmatch(self.deployment_image_id):
            raise MergeGroupError(
                f"policy.deployment_image_id 必须匹配 ^sha256:[0-9a-f]{{64}}$：{self.deployment_image_id!r}"
            )
        if not isinstance(self.expected_models, tuple) or len(self.expected_models) < 2:
            raise MergeGroupError("policy.expected_models 必须包含至少 2 个不同模型")
        seen_models: set[str] = set()
        for model in self.expected_models:
            if (
                not isinstance(model, str)
                or not model
                or not _MODEL_NAME_RE.fullmatch(model)
                or model in (".", "..")
                or ".." in model
            ):
                raise MergeGroupError(f"policy.expected_models 含有非法模型名：{model!r}")
            if model in seen_models:
                raise MergeGroupError(f"policy.expected_models 存在重复模型：{model!r}")
            seen_models.add(model)
        for flag_name in (
            "allow_single_hop_reused_pass",
            "reject_overlapping_files",
            "check_file_ownership",
        ):
            if type(getattr(self, flag_name)) is not bool:
                raise MergeGroupError(f"policy.{flag_name} 必须是布尔值")
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "review_contract", review_contract)
        object.__setattr__(self, "controller_code_head", controller_head)


@dataclass(frozen=True)
class MemberPassProof:
    """经完整核验通过的单个成员 PASS 证据。"""

    pr_number: int
    head_sha: str
    source_run_id: str
    member_run_id: str
    patch_id: str
    reused: bool
    reviewer_models: tuple[str, ...]
    image_id: str


@dataclass(frozen=True)
class MemberPassVerification:
    """单个成员 PASS 核验结果。"""

    passed: bool
    pr_number: int
    head_sha: str
    reason_code: str
    detail: str
    proof: MemberPassProof | None = None


def _check_no_ancestor_symlinks(path: Path) -> None:
    """核验路径自身及直至根目录的全部祖先组件不含任何符号链接（对齐 external_review.py:147,174）。"""
    try:
        abs_path = path.absolute()
        for ancestor in (abs_path, *abs_path.parents):
            if ancestor.is_symlink():
                raise _EvidenceError(f"路径或其祖先含符号链接：{path}")
        if path.is_symlink() or abs_path.resolve() != abs_path:
            raise _EvidenceError(f"路径解析经过符号链接：{path}")
    except _EvidenceError:
        raise
    except OSError as exc:
        raise _EvidenceError(f"无法核验路径祖先：{path}（{exc}）") from None


def _check_safe_directory(path: Path, *, check_ownership: bool) -> None:
    _check_no_ancestor_symlinks(path)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise _EvidenceError(f"无法读取目录属性：{path}（{exc}）") from None
    if not stat.S_ISDIR(info.st_mode):
        raise _EvidenceError(f"路径不是常规目录或存在符号链接：{path}")
    if check_ownership and (info.st_uid != os.getuid() or bool(info.st_mode & 0o022)):
        raise _EvidenceError(f"目录属主或权限不安全：{path}")


def _check_safe_path_chain(root: Path, target_path: Path, *, check_ownership: bool) -> None:
    """检查 root 完整祖先无软链，并从 root 到 target_path.parent 逐级检查非符号链接与目录权限/属主。"""
    _check_safe_directory(root, check_ownership=check_ownership)
    _check_no_ancestor_symlinks(target_path.parent)
    try:
        rel = target_path.relative_to(root)
    except ValueError:
        raise _EvidenceError(f"路径越出 state_root：{target_path}") from None
    cursor = root
    for part in rel.parts[:-1]:
        cursor = cursor / part
        _check_safe_directory(cursor, check_ownership=check_ownership)


def _safe_read_bytes(
    root: Path,
    path: Path,
    *,
    check_ownership: bool,
    max_bytes: int,
) -> bytes:
    _check_safe_path_chain(root, path, check_ownership=check_ownership)
    _check_no_ancestor_symlinks(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise _EvidenceError(f"无法安全打开文件（可能为符号链接或不可读）：{path}（{exc}）") from None
    owned_fd: int | None = fd
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _EvidenceError(f"证据文件不是常规文件：{path}")
        if check_ownership and (info.st_uid != os.getuid() or bool(info.st_mode & 0o022)):
            raise _EvidenceError(f"证据文件属主或权限不安全：{path}")
        if info.st_size > max_bytes:
            raise _EvidenceError(f"证据文件超过大小上限（{info.st_size} > {max_bytes}）：{path}")
        stream = os.fdopen(fd, "rb")
        owned_fd = None
        with stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise _EvidenceError(f"证据文件读取字节超过上限（>{max_bytes}）：{path}")
        return data
    except _EvidenceError:
        raise
    except (OSError, MemoryError) as exc:
        raise _EvidenceError(f"读取证据文件失败：{path}（{exc}）") from None
    finally:
        if owned_fd is not None:
            try:
                os.close(owned_fd)
            except OSError:
                pass


def _safe_read_text(
    root: Path,
    path: Path,
    *,
    check_ownership: bool,
    max_bytes: int | None = None,
) -> str:
    limit = MAX_JSON_EVIDENCE_BYTES if max_bytes is None else max_bytes
    raw = _safe_read_bytes(root, path, check_ownership=check_ownership, max_bytes=limit)
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, MemoryError) as exc:
        raise _EvidenceError(f"证据文本 UTF-8 解码失败：{path}（{exc}）") from None


def _safe_read_text_lines(
    root: Path,
    path: Path,
    *,
    check_ownership: bool,
    max_bytes: int | None = None,
) -> list[str]:
    """专用于读取 events.jsonl：保留防软链与字节上限，按 str.splitlines() 分行以对齐 external_review.py:386,681。"""
    limit = MAX_LOG_EVIDENCE_BYTES if max_bytes is None else max_bytes
    text = _safe_read_text(root, path, check_ownership=check_ownership, max_bytes=limit)
    return text.splitlines()


def _safe_read_first_line(
    root: Path,
    path: Path,
    *,
    check_ownership: bool,
    max_file_bytes: int | None = None,
    max_line_bytes: int | None = None,
) -> str:
    file_limit = MAX_LOG_EVIDENCE_BYTES if max_file_bytes is None else max_file_bytes
    line_limit = MAX_JSON_EVIDENCE_BYTES if max_line_bytes is None else max_line_bytes
    _check_safe_path_chain(root, path, check_ownership=check_ownership)
    _check_no_ancestor_symlinks(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise _EvidenceError(f"无法安全打开日志文件（可能为符号链接或不可读）：{path}（{exc}）") from None
    owned_fd: int | None = fd
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _EvidenceError(f"日志文件不是常规文件：{path}")
        if check_ownership and (info.st_uid != os.getuid() or bool(info.st_mode & 0o022)):
            raise _EvidenceError(f"日志文件属主或权限不安全：{path}")
        if info.st_size > file_limit:
            raise _EvidenceError(f"日志文件超过大小上限（{info.st_size} > {file_limit}）：{path}")
        stream = os.fdopen(fd, "rb")
        owned_fd = None
        with stream:
            raw_line = stream.readline(line_limit + 1)
        if len(raw_line) > line_limit:
            raise _EvidenceError(f"日志首行超过大小上限（>{line_limit}）：{path}")
        return raw_line.decode("utf-8").rstrip("\r\n")
    except _EvidenceError:
        raise
    except (OSError, UnicodeDecodeError, MemoryError) as exc:
        raise _EvidenceError(f"读取日志首行失败：{path}（{exc}）") from None
    finally:
        if owned_fd is not None:
            try:
                os.close(owned_fd)
            except OSError:
                pass


def _safe_read_json_dict(
    root: Path,
    path: Path,
    *,
    check_ownership: bool,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    raw_text = _safe_read_text(root, path, check_ownership=check_ownership, max_bytes=max_bytes)
    try:
        parsed = json.loads(raw_text)
    except (ValueError, TypeError, RecursionError, MemoryError) as exc:
        raise _EvidenceError(f"证据 JSON 损坏或解码超限：{path}（{type(exc).__name__}）") from None
    if not isinstance(parsed, dict):
        raise _EvidenceError(f"证据 JSON 顶层不是对象：{path}")
    return parsed


@dataclass(frozen=True)
class _WorkerEvidence:
    model: str
    launch: dict[str, Any] | None
    receipt: dict[str, Any] | None
    session_first_line: str | None
    events_lines: tuple[str, ...] | None


@dataclass(frozen=True)
class _RunRecord:
    folder: Path
    run_id: str
    repository_id: int
    pr_number: int
    base_sha: str
    head_sha: str
    merge_base_sha: str
    registered_at_ns: int
    target: dict[str, Any]
    outcome: dict[str, Any] | None
    workers: dict[str, _WorkerEvidence]


def _load_run_record(
    state_root: Path,
    folder: Path,
    *,
    expected_models: tuple[str, ...],
    check_ownership: bool,
) -> _RunRecord:
    _check_safe_path_chain(state_root, folder, check_ownership=check_ownership)
    _check_safe_directory(folder, check_ownership=check_ownership)

    target_path = folder / "target.json"
    if not os.path.lexists(target_path):
        raise _EvidenceError(f"run 目录缺少 target.json：{folder}")
    target_data = _safe_read_json_dict(state_root, target_path, check_ownership=check_ownership)

    raw_run_id = target_data.get("run_id")
    if not isinstance(raw_run_id, str) or not raw_run_id.strip():
        raise _EvidenceError(f"target.json 缺少合法 run_id：{target_path}")
    try:
        repo_id = _parse_positive_int(target_data.get("repository_id"), field="target.repository_id")
        pr_number = _parse_positive_int(target_data.get("pr_number"), field="target.pr_number")
        base_sha = _parse_commit_sha(target_data.get("base_sha"), field="target.base_sha")
        head_sha = _parse_commit_sha(target_data.get("head_sha"), field="target.head_sha")
        merge_base_sha = _parse_commit_sha(target_data.get("merge_base_sha"), field="target.merge_base_sha")
    except MergeGroupError as exc:
        raise _EvidenceError(f"target.json 字段非法：{exc}") from None

    registered_at_ns = target_data.get("registered_at_ns")
    if type(registered_at_ns) is not int or registered_at_ns < 0:
        raise _EvidenceError(f"target.json registered_at_ns 非法：{target_path}")

    outcome_path = folder / "outcome.json"
    outcome_data: dict[str, Any] | None = None
    if os.path.lexists(outcome_path):
        outcome_data = _safe_read_json_dict(state_root, outcome_path, check_ownership=check_ownership)

    worker_names: set[str] = set()
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise _EvidenceError(f"无法枚举 run 目录：{folder}（{exc}）") from None

    for entry in entries:
        if entry.name == "effects":
            continue
        try:
            entry_info = os.lstat(entry)
        except OSError as exc:
            raise _EvidenceError(f"无法读取 run 条目属性：{entry}（{exc}）") from None
        if stat.S_ISLNK(entry_info.st_mode):
            raise _EvidenceError(f"run 目录内含符号链接：{entry}")
        if stat.S_ISDIR(entry_info.st_mode):
            worker_names.add(entry.name)

    for model in expected_models:
        candidate = folder / model
        if os.path.lexists(candidate):
            worker_names.add(model)

    workers: dict[str, _WorkerEvidence] = {}
    for model in sorted(worker_names):
        worker_dir = folder / model
        _check_safe_directory(worker_dir, check_ownership=check_ownership)
        launch_path = worker_dir / "launch.json"
        launch_data: dict[str, Any] | None = None
        if os.path.lexists(launch_path):
            launch_data = _safe_read_json_dict(state_root, launch_path, check_ownership=check_ownership)
        receipt_path = worker_dir / "receipt.json"
        receipt_data: dict[str, Any] | None = None
        if os.path.lexists(receipt_path):
            receipt_data = _safe_read_json_dict(state_root, receipt_path, check_ownership=check_ownership)
        session_path = worker_dir / "session.jsonl"
        session_first_line: str | None = None
        if os.path.lexists(session_path):
            session_first_line = _safe_read_first_line(
                state_root,
                session_path,
                check_ownership=check_ownership,
            )
        events_path = worker_dir / "events.jsonl"
        events_lines: tuple[str, ...] | None = None
        if os.path.lexists(events_path):
            events_lines = tuple(
                _safe_read_text_lines(
                    state_root,
                    events_path,
                    check_ownership=check_ownership,
                    max_bytes=MAX_LOG_EVIDENCE_BYTES,
                )
            )
        workers[model] = _WorkerEvidence(
            model=model,
            launch=launch_data,
            receipt=receipt_data,
            session_first_line=session_first_line,
            events_lines=events_lines,
        )

    return _RunRecord(
        folder=folder,
        run_id=raw_run_id,
        repository_id=repo_id,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base_sha=merge_base_sha,
        registered_at_ns=registered_at_ns,
        target=target_data,
        outcome=outcome_data,
        workers=workers,
    )


def _scan_pr_runs(
    state_root: Path,
    *,
    repository_id: int,
    pr_number: int,
    expected_models: tuple[str, ...],
    check_ownership: bool,
) -> list[_RunRecord]:
    _check_safe_directory(state_root, check_ownership=check_ownership)
    runs_root = state_root / "runs"
    if not os.path.lexists(runs_root):
        return []
    _check_safe_directory(runs_root, check_ownership=check_ownership)

    try:
        children = sorted(runs_root.iterdir(), key=lambda p: p.name)
    except OSError as exc:
        raise _EvidenceError(f"无法枚举 runs 目录：{runs_root}（{exc}）") from None

    matched_runs: list[_RunRecord] = []
    for child in children:
        prefix_match = _RUN_DIR_PREFIX_RE.fullmatch(child.name)
        if prefix_match is not None:
            dir_repo = int(prefix_match.group("repo"))
            dir_pr = int(prefix_match.group("pr"))
            if dir_pr != pr_number:
                continue
            if dir_repo != repository_id:
                continue
            record = _load_run_record(
                state_root,
                child,
                expected_models=expected_models,
                check_ownership=check_ownership,
            )
            if record.repository_id != repository_id or record.pr_number != pr_number:
                raise _EvidenceError(
                    f"run 目录名归属（r{dir_repo}-p{dir_pr}）与 target.json 身份"
                    f"（r{record.repository_id}-p{record.pr_number}）不一致：{child}"
                )
            matched_runs.append(record)
        else:
            record = _load_run_record(
                state_root,
                child,
                expected_models=expected_models,
                check_ownership=check_ownership,
            )
            if record.repository_id == repository_id and record.pr_number == pr_number:
                matched_runs.append(record)
    return matched_runs


def _run_is_settled(run: _RunRecord) -> bool:
    if run.outcome is None:
        return False
    return not any(worker.launch is not None and worker.receipt is None for worker in run.workers.values())


def _parse_and_validate_events(
    events_lines: Sequence[str],
    *,
    run_id: str,
    model: str,
) -> list[dict[str, Any]]:
    """统一解析并校验 events.jsonl 事件结构（直审事件核验与历史 BLOCK 扫描共用）。"""
    parsed_events: list[dict[str, Any]] = []
    for raw_line in events_lines:
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except (ValueError, TypeError, RecursionError, MemoryError) as exc:
            raise _EvidenceError(
                f"run {run_id} 模型 {model} events.jsonl JSON 损坏或截断（{type(exc).__name__}）"
            ) from None
        if not isinstance(event, dict):
            raise _EvidenceError(
                f"run {run_id} 模型 {model} events.jsonl 事件不是 JSON 对象"
            )
        kind = event.get("type")
        if kind == "item.completed":
            item = event.get("item")
            if not isinstance(item, dict):
                raise _EvidenceError(
                    f"run {run_id} 模型 {model} events.jsonl 中 item.completed 缺少合法 item 对象"
                )
            if item.get("type") == "agent_message" and not isinstance(item.get("text"), str):
                raise _EvidenceError(
                    f"run {run_id} 模型 {model} events.jsonl agent_message.text 不是字符串"
                )
        elif kind == "error":
            raw_msg = event.get("message", "")
            if not isinstance(raw_msg, str):
                raise _EvidenceError(
                    f"run {run_id} 模型 {model} events.jsonl 中 error 事件 message 不是字符串"
                )
        parsed_events.append(event)
    return parsed_events


def _run_has_block(run: _RunRecord) -> bool:
    if run.outcome is not None:
        if run.outcome.get("verdict") == "BLOCK":
            return True
        reviews = run.outcome.get("reviews")
        if reviews is not None:
            if not isinstance(reviews, list):
                raise _EvidenceError(f"run {run.run_id} outcome.reviews 不是列表")
            for review in reviews:
                if not isinstance(review, dict):
                    raise _EvidenceError(f"run {run.run_id} outcome.reviews 含非对象条目")
                if review.get("verdict") == "BLOCK":
                    return True

    for worker in run.workers.values():
        if worker.receipt is not None:
            result = worker.receipt.get("result")
            if isinstance(result, dict):
                if result.get("status") == "blocked":
                    return True
                summary = result.get("summary")
                if isinstance(summary, str):
                    if summary.startswith("VERDICT: BLOCK"):
                        return True
                    try:
                        payload_json = json.dumps(
                            {"status": result.get("status"), "summary": summary},
                            ensure_ascii=False,
                        )
                    except (TypeError, ValueError, RecursionError, MemoryError) as exc:
                        raise _EvidenceError(
                            f"run {run.run_id} 模型 {worker.model} receipt.result 序列化失败（{type(exc).__name__}）"
                        ) from None
                    if _message_blocks(payload_json):
                        return True
        if worker.events_lines is not None:
            parsed_events = _parse_and_validate_events(
                worker.events_lines,
                run_id=run.run_id,
                model=worker.model,
            )
            final_text: str | None = None
            for event in parsed_events:
                if event.get("type") == "item.completed":
                    item = event.get("item")
                    if isinstance(item, dict) and item.get("type") == "agent_message":
                        raw_text = item.get("text")
                        if not isinstance(raw_text, str):
                            raise _EvidenceError(
                                f"run {run.run_id} 模型 {worker.model} events.jsonl agent_message.text 不是字符串"
                            )
                        final_text = raw_text
            if final_text is not None and _message_blocks(final_text):
                return True
    return False


@dataclass(frozen=True)
class _PatchIdentityCheck:
    ok: bool
    patch_id: str | None
    reason_code: str
    detail: str


def _verify_and_compute_patch_id(replay_repo: Path, run: _RunRecord) -> _PatchIdentityCheck:
    """先验证 (base_sha, head_sha) 的真实唯一 merge-base == run.merge_base_sha，再重算 patch_id。"""
    mb_proc = _run_git(
        replay_repo,
        "merge-base",
        "--all",
        run.base_sha,
        run.head_sha,
        env=_git_env(),
    )
    if mb_proc.returncode != 0:
        return _PatchIdentityCheck(
            ok=False,
            patch_id=None,
            reason_code="member_merge_base_mismatch",
            detail=f"run {run.run_id} 无法计算真实 merge-base",
        )
    bases = [
        line.strip().lower()
        for line in _split_lines_strict(mb_proc.stdout.decode("utf-8", errors="replace"))
        if line.strip()
    ]
    if len(bases) != 1 or not _COMMIT_SHA_RE.fullmatch(bases[0]) or bases[0] != run.merge_base_sha:
        return _PatchIdentityCheck(
            ok=False,
            patch_id=None,
            reason_code="member_merge_base_mismatch",
            detail=f"run {run.run_id} 冻结 merge_base_sha 与仓库真实唯一 merge-base 不一致",
        )
    try:
        computed = _compute_patch_identity_in_repo(replay_repo, run.merge_base_sha, run.head_sha)
    except MergeGroupError:
        return _PatchIdentityCheck(
            ok=False,
            patch_id=None,
            reason_code="member_patch_id_mismatch",
            detail=f"run {run.run_id} 无法重算 patch_id",
        )
    return _PatchIdentityCheck(ok=True, patch_id=computed, reason_code="ok", detail="")


def _verify_outcome_target_binding(
    run: _RunRecord,
    outcome: dict[str, Any],
    *,
    policy: MergeGroupPolicy,
    expected_patch_id: str,
) -> tuple[str, str] | None:
    if outcome.get("run_id") != run.run_id:
        return ("member_outcome_invalid", f"run {run.run_id} outcome.run_id 与 target.run_id 不一致")
    outcome_target = outcome.get("target")
    if not isinstance(outcome_target, dict):
        return ("member_outcome_invalid", f"run {run.run_id} outcome.target 缺失或不是对象")
    outcome_reg_ns = outcome_target.get("registered_at_ns")
    if (
        type(outcome_target.get("pr_number")) is not int
        or outcome_target.get("pr_number") != run.pr_number
        or type(outcome_target.get("repository_id")) is not int
        or outcome_target.get("repository_id") != run.repository_id
        or type(outcome_reg_ns) is not int
        or outcome_reg_ns != run.registered_at_ns
    ):
        return (
            "member_outcome_invalid",
            f"run {run.run_id} outcome.target 仓库、PR 编号或 registered_at_ns 不匹配",
        )
    expected_str_fields: dict[str, str] = {
        "run_id": run.run_id,
        "head_sha": run.head_sha,
        "base_sha": run.base_sha,
        "merge_base_sha": run.merge_base_sha,
        "policy_version": policy.policy_version,
        "review_contract": policy.review_contract,
        "controller_code_head": policy.controller_code_head,
        "patch_id": expected_patch_id,
    }
    for key, expected_val in expected_str_fields.items():
        actual_val = outcome_target.get(key)
        target_val = run.target.get(key)
        if key in ("head_sha", "base_sha", "merge_base_sha", "controller_code_head"):
            if (
                not isinstance(actual_val, str)
                or actual_val.lower() != expected_val
                or not isinstance(target_val, str)
                or target_val.lower() != expected_val
            ):
                return (
                    "member_outcome_invalid",
                    f"run {run.run_id} outcome.target.{key} 与 target.json 不一致",
                )
        else:
            if actual_val != expected_val or target_val != expected_val:
                return (
                    "member_outcome_invalid",
                    f"run {run.run_id} outcome.target.{key} 与 target.json 不一致",
                )
    return None


def _verify_publication_binding(
    run: _RunRecord,
    publication: object,
    *,
    patch_id: str,
    reuse_origin_run_id: str | None,
) -> tuple[str, str] | None:
    if not isinstance(publication, dict) or publication.get("state") != "success":
        return ("member_not_published_success", f"run {run.run_id} 未发布 success")
    pub_sha = publication.get("sha")
    if not isinstance(pub_sha, str) or pub_sha.lower() != run.head_sha:
        return ("member_publication_invalid", f"run {run.run_id} publication.sha 与 head_sha 不一致")
    pub_id = publication.get("id")
    valid_id = (type(pub_id) is int and pub_id > 0) or (
        isinstance(pub_id, str) and bool(pub_id.strip())
    )
    if not valid_id:
        return ("member_publication_invalid", f"run {run.run_id} publication.id 缺失或非法")
    pub_desc = publication.get("description")
    if reuse_origin_run_id is None:
        expected_desc = f"run={run.run_id} b={run.base_sha[:12]} h={run.head_sha[:12]} success"
    else:
        expected_desc = (
            f"run={run.run_id} b={run.base_sha[:12]} h={run.head_sha[:12]} success "
            f"reuse={reuse_origin_run_id} p={patch_id[7:19]}"
        )
    if not isinstance(pub_desc, str) or pub_desc != expected_desc:
        return (
            "member_publication_invalid",
            f"run {run.run_id} publication.description 与预期绑定不精确一致",
        )
    return None


def _verify_direct_pass_run(
    run: _RunRecord,
    *,
    repository_id: int,
    policy: MergeGroupPolicy,
    replay_repo: Path,
) -> tuple[str, str] | None:
    """校验单条真实双审 PASS run。成功返回 None，失败返回 (reason_code, detail)。"""
    if run.repository_id != repository_id:
        return ("member_repository_mismatch", f"run {run.run_id} repository_id 不匹配")
    if run.target.get("policy_version") != policy.policy_version:
        return (
            "member_policy_mismatch",
            f"run {run.run_id} policy_version 不匹配：{run.target.get('policy_version')!r}",
        )
    if run.target.get("review_contract") != policy.review_contract:
        return ("member_contract_mismatch", f"run {run.run_id} review_contract 不匹配")
    target_ctrl = run.target.get("controller_code_head")
    if not isinstance(target_ctrl, str) or target_ctrl.lower() != policy.controller_code_head:
        return ("member_controller_mismatch", f"run {run.run_id} controller_code_head 不匹配")

    outcome = run.outcome
    if outcome is None:
        return ("member_unsettled_run", f"run {run.run_id} 缺少 outcome.json")
    if "migrated" in outcome:
        return ("member_migrated_not_allowed", f"run {run.run_id} 为 migrated 结论，禁止沿用")
    if "reused_from" in outcome:
        return ("member_chained_reuse_not_allowed", f"原件 run {run.run_id} 本身含 reused_from，禁止多跳沿用")
    if outcome.get("verdict") != "PASS" or outcome.get("state") != "success":
        return ("member_not_published_success", f"run {run.run_id} verdict/state 非 PASS/success")

    recorded_patch_id = run.target.get("patch_id")
    if not isinstance(recorded_patch_id, str) or not _PATCH_ID_RE.fullmatch(recorded_patch_id):
        return ("member_patch_id_mismatch", f"run {run.run_id} target.patch_id 缺失或格式非法")

    outcome_err = _verify_outcome_target_binding(
        run,
        outcome,
        policy=policy,
        expected_patch_id=recorded_patch_id,
    )
    if outcome_err is not None:
        return outcome_err

    pub_err = _verify_publication_binding(
        run,
        outcome.get("publication"),
        patch_id=recorded_patch_id,
        reuse_origin_run_id=None,
    )
    if pub_err is not None:
        return pub_err

    reviews = outcome.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != len(policy.expected_models):
        return ("member_models_mismatch", f"run {run.run_id} reviews 数量与期望模型不符")
    review_by_model: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            return ("member_models_mismatch", f"run {run.run_id} reviews 含非法条目")
        model = review.get("model")
        verdict = review.get("verdict")
        if not isinstance(model, str) or model in review_by_model or verdict != "PASS":
            return (
                "member_models_mismatch",
                f"run {run.run_id} 模型评审条目非法或非 PASS：{model!r}={verdict!r}",
            )
        review_by_model[model] = review
    if set(review_by_model) != set(policy.expected_models):
        return ("member_models_mismatch", f"run {run.run_id} 未精确覆盖期望双审模型")

    seen_launch_ids: set[str] = set()
    seen_session_ids: set[str] = set()
    frozen_candidate_patch: Any | None = None
    for model in policy.expected_models:
        worker = run.workers.get(model)
        if worker is None or worker.launch is None:
            return ("member_launch_invalid", f"run {run.run_id} 缺少模型 {model} 的 launch.json")
        launch = worker.launch
        launch_id = launch.get("launch_id")
        if (
            not isinstance(launch_id, str)
            or not launch_id
            or launch_id != launch_id.strip()
            or launch_id in seen_launch_ids
        ):
            return ("member_launch_invalid", f"run {run.run_id} 模型 {model} launch_id 缺失、非法或重复")
        if (
            launch.get("run_id") != run.run_id
            or type(launch.get("pr_number")) is not int
            or launch.get("pr_number") != run.pr_number
            or launch.get("model") != model
            or not isinstance(launch.get("head_sha"), str)
            or launch["head_sha"].lower() != run.head_sha
            or not isinstance(launch.get("base_sha"), str)
            or launch["base_sha"].lower() != run.base_sha
            or not isinstance(launch.get("merge_base_sha"), str)
            or launch["merge_base_sha"].lower() != run.merge_base_sha
            or not isinstance(launch.get("controller_code_head"), str)
            or launch["controller_code_head"].lower() != policy.controller_code_head
            or launch.get("mode") != "review"
        ):
            return ("member_launch_invalid", f"run {run.run_id} 模型 {model} launch.json 身份绑定不符")
        seen_launch_ids.add(launch_id)

        if worker.receipt is None:
            return ("member_missing_receipt", f"run {run.run_id} 缺少模型 {model} 的 receipt.json")
        receipt = worker.receipt
        if receipt.get("image_id") != policy.deployment_image_id:
            return (
                "member_image_mismatch",
                f"run {run.run_id} 模型 {model} 镜像 ID 与部署策略不符",
            )
        if (
            receipt.get("run_id") != run.run_id
            or receipt.get("launch_id") != launch_id
            or receipt.get("model") != model
            or not isinstance(receipt.get("head_sha"), str)
            or receipt["head_sha"].lower() != run.head_sha
            or not isinstance(receipt.get("base_sha"), str)
            or receipt["base_sha"].lower() != run.base_sha
            or not isinstance(receipt.get("merge_base_sha"), str)
            or receipt["merge_base_sha"].lower() != run.merge_base_sha
            or not isinstance(receipt.get("controller_code_head"), str)
            or receipt["controller_code_head"].lower() != policy.controller_code_head
            or receipt.get("status") != "completed"
            or receipt.get("mode") != "review"
            or receipt.get("sandbox") != "docker-read-only"
            or type(receipt.get("exit_code")) is not int
            or receipt.get("exit_code") != 0
            or receipt.get("turn_completed") is not True
        ):
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执绑定或状态不符")

        container_id = receipt.get("container_id")
        if not isinstance(container_id, str) or not _CONTAINER_ID_RE.fullmatch(container_id):
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} container_id 非法")

        for phase in ("before", "after"):
            snapshot = receipt.get(phase)
            if (
                not isinstance(snapshot, dict)
                or not isinstance(snapshot.get("head"), str)
                or snapshot["head"].lower() != run.head_sha
                or snapshot.get("status") != ""
                or snapshot.get("branch") != "HEAD"
            ):
                return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} {phase} 快照漂移或缺失")

        fs_probe = receipt.get("filesystem")
        if (
            not isinstance(fs_probe, dict)
            or fs_probe.get("source_write") != "EROFS"
            or fs_probe.get("git_write") != "EROFS"
            or fs_probe.get("host_read") not in ("ENOENT", "EACCES")
            or fs_probe.get("state_write") not in ("ENOENT", "EACCES", "EROFS")
        ):
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 文件隔离探针缺失或未通过")

        result_obj = receipt.get("result")
        if (
            not isinstance(result_obj, dict)
            or set(result_obj) != {"status", "summary", "findings", "validation"}
            or result_obj.get("status") != "completed"
            or not isinstance(result_obj.get("summary"), str)
            or not all(
                isinstance(result_obj.get(k), list)
                and all(isinstance(x, str) for x in result_obj[k])
                for k in ("findings", "validation")
            )
        ):
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执 result 不符合协议")
        summary = result_obj["summary"]
        if _first_line_strict(summary) != "VERDICT: PASS":
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执 summary 首行非 VERDICT: PASS")
        try:
            result_json = json.dumps(result_obj, ensure_ascii=False)
        except (TypeError, ValueError, RecursionError, MemoryError):
            return ("member_evidence_corrupted", f"run {run.run_id} 模型 {model} 回执 result 序列化失败")
        if _message_blocks(result_json):
            return ("member_blocked", f"run {run.run_id} 模型 {model} 回执 result 判定为 BLOCK")

        session_id = receipt.get("session_id")
        if (
            not isinstance(session_id, str)
            or not _SESSION_ID_RE.fullmatch(session_id)
            or session_id in seen_session_ids
        ):
            return ("member_session_invalid", f"run {run.run_id} 模型 {model} session_id 缺失、非法或重复")
        if review_by_model[model].get("session_id") != session_id:
            return ("member_session_invalid", f"run {run.run_id} 模型 {model} outcome.reviews.session_id 不一致")
        seen_session_ids.add(session_id)

        if worker.session_first_line is None:
            return ("member_session_invalid", f"run {run.run_id} 缺少模型 {model} 的 session.jsonl")
        try:
            session_meta = json.loads(worker.session_first_line)
        except (ValueError, TypeError, RecursionError, MemoryError):
            return ("member_evidence_corrupted", f"run {run.run_id} 模型 {model} session.jsonl 首行损坏")
        payload_obj = session_meta.get("payload") if isinstance(session_meta, dict) else None
        if (
            not isinstance(session_meta, dict)
            or session_meta.get("type") != "session_meta"
            or not isinstance(payload_obj, dict)
            or payload_obj.get("id") != session_id
        ):
            return ("member_session_invalid", f"run {run.run_id} 模型 {model} session.jsonl 身份与 receipt 不符")

        if worker.events_lines is None:
            return ("member_events_invalid", f"run {run.run_id} 缺少模型 {model} 的 events.jsonl")
        parsed_events = _parse_and_validate_events(
            worker.events_lines,
            run_id=run.run_id,
            model=model,
        )

        if frozen_candidate_patch is None:
            raw_attempt = run.target.get("attempt")
            attempt_val = raw_attempt if type(raw_attempt) is int and raw_attempt > 0 else 1
            raw_base_ref = run.target.get("base_ref")
            base_ref_val = raw_base_ref if isinstance(raw_base_ref, str) and raw_base_ref else "main"
            raw_head_ref = run.target.get("head_ref")
            head_ref_val = (
                raw_head_ref if isinstance(raw_head_ref, str) and raw_head_ref else f"pr-{run.pr_number}"
            )
            review_target = _ReviewTarget(
                repository_id=run.repository_id,
                pr_number=run.pr_number,
                base_repository_id=run.repository_id,
                base_ref=base_ref_val,
                base_sha=run.base_sha,
                head_repository_id=run.repository_id,
                head_ref=head_ref_val,
                head_sha=run.head_sha,
                merge_base_sha=run.merge_base_sha,
                run_id=run.run_id,
                attempt=attempt_val,
                policy_version=policy.policy_version,
                controller_code_head=policy.controller_code_head,
                registered_at_ns=run.registered_at_ns,
                patch_id=recorded_patch_id,
                review_contract=policy.review_contract,
            )
            try:
                frozen_candidate_patch = _frozen_patch(replay_repo, review_target)
            except subprocess.CalledProcessError as exc:
                if exc.returncode < 0:
                    raise _GitQueryError(
                        f"git 进程被信号中止（returncode={exc.returncode}）"
                    ) from None
                return ("member_patch_id_mismatch", f"run {run.run_id} 无法从隔离对象库提取冻结候选补丁")

        turn_completed = False
        final_text: str | None = None
        patch_reads = 0
        thread_ids: set[object] = set()
        for event in parsed_events:
            kind = event.get("type")
            if kind == "thread.started":
                thread_ids.add(event.get("thread_id"))
            elif kind == "error":
                raw_msg = event.get("message", "")
                if not isinstance(raw_msg, str):
                    raise _EvidenceError(
                        f"run {run.run_id} 模型 {model} events.jsonl 中 error 事件 message 不是字符串"
                    )
                reconnect = _RECONNECT_ERROR_RE.fullmatch(raw_msg)
                if reconnect is None or int(reconnect.group(1)) > int(reconnect.group(2)):
                    return (
                        "member_events_invalid",
                        f"run {run.run_id} 模型 {model} events.jsonl 含非重连 error 事件",
                    )
                turn_completed = False
                final_text = None
            elif kind in ("turn.failed", "turn.cancelled"):
                return (
                    "member_events_invalid",
                    f"run {run.run_id} 模型 {model} events.jsonl 含失败终态 {kind}",
                )
            elif kind == "turn.completed":
                turn_completed = True
            elif kind == "item.completed":
                item = event.get("item")
                if not isinstance(item, dict):
                    raise _EvidenceError(
                        f"run {run.run_id} 模型 {model} events.jsonl 中 item.completed 缺少合法 item 对象"
                    )
                item_type = item.get("type")
                if item_type == "agent_message":
                    raw_text = item.get("text")
                    if not isinstance(raw_text, str):
                        raise _EvidenceError(
                            f"run {run.run_id} 模型 {model} events.jsonl agent_message.text 不是字符串"
                        )
                    final_text = raw_text
                elif item_type == "command_execution":
                    item_status = item.get("status")
                    item_exit = item.get("exit_code")
                    if item_status == "completed" and type(item_exit) is int and item_exit == 0:
                        cmd_raw = item.get("command")
                        agg_raw = item.get("aggregated_output")
                        if _reads_candidate_patch(
                            str(cmd_raw) if cmd_raw is not None else "",
                            str(agg_raw) if agg_raw is not None else "",
                            frozen_candidate_patch,
                        ):
                            patch_reads += 1

        if not turn_completed:
            return ("member_events_invalid", f"run {run.run_id} 模型 {model} events.jsonl 缺少 turn.completed")
        if thread_ids != {session_id}:
            return (
                "member_events_invalid",
                f"run {run.run_id} 模型 {model} events.jsonl thread.started 与 session_id 不符",
            )
        if patch_reads == 0:
            return (
                "member_events_invalid",
                f"run {run.run_id} 模型 {model} events.jsonl 未读取冻结候选补丁",
            )
        if final_text is None:
            return ("member_events_invalid", f"run {run.run_id} 模型 {model} events.jsonl 缺少最终 agent_message")
        if _message_blocks(final_text):
            return ("member_blocked", f"run {run.run_id} 模型 {model} events.jsonl 最终消息判定为 BLOCK")
        try:
            parsed_final = json.loads(_unwrap_json_fence(final_text))
        except (ValueError, TypeError, RecursionError, MemoryError):
            return (
                "member_evidence_corrupted",
                f"run {run.run_id} 模型 {model} events.jsonl 最终消息 JSON 解析失败",
            )
        if parsed_final != result_obj:
            return (
                "member_events_invalid",
                f"run {run.run_id} 模型 {model} events.jsonl 最终消息与 receipt.result 不符",
            )

    patch_check = _verify_and_compute_patch_id(replay_repo, run)
    if not patch_check.ok:
        return (patch_check.reason_code, patch_check.detail)
    if patch_check.patch_id != recorded_patch_id:
        return ("member_patch_id_mismatch", f"run {run.run_id} 现场重算 patch_id 与记录不符")
    return None


def _check_admission_binding(
    admission: object,
    *,
    policy: MergeGroupPolicy,
    run_id: str,
) -> tuple[str, str] | None:
    if not isinstance(admission, dict):
        return ("member_reuse_admission_missing", f"run {run_id} reused_from.admission 缺失或不是对象")
    if admission.get("image_id") != policy.deployment_image_id:
        return ("member_image_mismatch", f"run {run_id} admission.image_id 与策略不符")
    adm_ctrl = admission.get("controller_code_head")
    if not isinstance(adm_ctrl, str) or adm_ctrl.lower() != policy.controller_code_head:
        return ("member_controller_mismatch", f"run {run_id} admission.controller_code_head 与策略不符")
    return None


def _verify_member_pass_in_repo(
    member: MergeGroupMember,
    *,
    repository_id: int,
    replay_repo: Path | None,
    source_repo: Path,
    state_root: Path,
    policy: MergeGroupPolicy,
    published_statuses: Mapping[str, str] | None = None,
) -> MemberPassVerification:
    def fail(code: str, detail: str) -> MemberPassVerification:
        return MemberPassVerification(
            passed=False,
            pr_number=member.pr_number,
            head_sha=member.head_sha,
            reason_code=code,
            detail=detail,
            proof=None,
        )

    try:
        pr_runs = _scan_pr_runs(
            state_root,
            repository_id=repository_id,
            pr_number=member.pr_number,
            expected_models=policy.expected_models,
            check_ownership=policy.check_file_ownership,
        )

        head_runs = [run for run in pr_runs if run.head_sha == member.head_sha]
        if not head_runs:
            return fail(
                "member_missing_pass",
                f"PR #{member.pr_number} 在 head={member.head_sha[:12]} 上没有任何审查记录",
            )

        for run in head_runs:
            if _run_has_block(run):
                return fail("member_blocked", f"PR #{member.pr_number} 在当前 head 存在 BLOCK 证据（run={run.run_id}）")
        for run in head_runs:
            if not _run_is_settled(run):
                return fail(
                    "member_unsettled_run",
                    f"PR #{member.pr_number} 在当前 head 存在未完结 run（run={run.run_id}）",
                )

        # 用 registered_at_ns 做新旧排序与取代判断前，强制核验同 PR 下所有含 outcome.json 的 run 时间戳强绑定
        for run in pr_runs:
            if run.outcome is not None:
                outcome_target = run.outcome.get("target")
                if not isinstance(outcome_target, dict):
                    raise _EvidenceError(f"run {run.run_id} outcome.target 缺失或不是对象")
                outcome_reg_ns = outcome_target.get("registered_at_ns")
                if type(outcome_reg_ns) is not int or outcome_reg_ns != run.registered_at_ns:
                    raise _EvidenceError(
                        f"run {run.run_id} outcome.target.registered_at_ns 与 target.json 不一致"
                    )

        head_runs_sorted = sorted(head_runs, key=lambda r: (r.registered_at_ns, r.run_id), reverse=True)
        latest = head_runs_sorted[0]
        assert latest.outcome is not None

        if latest.outcome.get("verdict") != "PASS":
            had_earlier_pass = any(
                r.outcome is not None and r.outcome.get("verdict") == "PASS"
                for r in head_runs_sorted[1:]
            )
            if had_earlier_pass:
                return fail(
                    "member_pass_superseded",
                    f"PR #{member.pr_number} 当前 head 的旧 PASS 已被更晚登记的 {latest.outcome.get('verdict')!r} 取代",
                )
            return fail(
                "member_missing_pass",
                f"PR #{member.pr_number} 当前 head 最新结论为 {latest.outcome.get('verdict')!r}，非 PASS",
            )

        if "migrated" in latest.outcome:
            return fail(
                "member_migrated_not_allowed",
                f"PR #{member.pr_number} 的 PASS 属于 migrated 迁移结论，禁止沿用",
            )

        recorded_patch_id = latest.target.get("patch_id")
        if not isinstance(recorded_patch_id, str) or not _PATCH_ID_RE.fullmatch(recorded_patch_id):
            return fail("member_patch_id_mismatch", f"PR #{member.pr_number} target.patch_id 缺失或非法")

        def _evaluate_with_replay(active_replay: Path) -> MemberPassVerification:
            assert latest.outcome is not None
            latest_patch_check = _verify_and_compute_patch_id(active_replay, latest)
            if not latest_patch_check.ok:
                return fail(latest_patch_check.reason_code, latest_patch_check.detail)
            if latest_patch_check.patch_id != recorded_patch_id:
                return fail(
                    "member_patch_id_mismatch",
                    f"PR #{member.pr_number} 现场重算 patch_id 与记录不符",
                )

            same_patch_runs: list[_RunRecord] = []
            for run in pr_runs:
                other_recorded = run.target.get("patch_id")
                other_check = _verify_and_compute_patch_id(active_replay, run)
                other_computed = other_check.patch_id if other_check.ok else None
                is_same_patch = (
                    run.head_sha == member.head_sha
                    or other_recorded == recorded_patch_id
                    or other_computed == recorded_patch_id
                    or (not other_recorded and other_computed is None)
                )
                if is_same_patch:
                    same_patch_runs.append(run)

            for run in same_patch_runs:
                if _run_has_block(run):
                    return fail(
                        "member_blocked",
                        f"PR #{member.pr_number} 同补丁历史上存在 BLOCK 证据（run={run.run_id}）",
                    )
            for run in same_patch_runs:
                if not _run_is_settled(run):
                    return fail(
                        "member_unsettled_run",
                        f"PR #{member.pr_number} 同补丁存在未完结 run（run={run.run_id}）",
                    )
            for run in same_patch_runs:
                if (
                    run.registered_at_ns > latest.registered_at_ns
                    and (run.outcome is None or run.outcome.get("verdict") != "PASS")
                ):
                    return fail(
                        "member_pass_superseded",
                        f"PR #{member.pr_number} 同补丁存在更晚登记的非 PASS run（run={run.run_id}）",
                    )

            if "reused_from" not in latest.outcome:
                err = _verify_direct_pass_run(
                    latest,
                    repository_id=repository_id,
                    policy=policy,
                    replay_repo=active_replay,
                )
                if err is not None:
                    return fail(err[0], err[1])
                source_run_id = latest.run_id
                reused = False
            else:
                if not policy.allow_single_hop_reused_pass:
                    return fail(
                        "member_reuse_not_allowed",
                        f"策略禁止沿用单跳 reused_from PASS（PR #{member.pr_number}）",
                    )
                if latest.repository_id != repository_id:
                    return fail("member_repository_mismatch", f"run {latest.run_id} repository_id 不匹配")
                if latest.target.get("policy_version") != policy.policy_version:
                    return fail("member_policy_mismatch", f"run {latest.run_id} policy_version 不匹配")
                if latest.target.get("review_contract") != policy.review_contract:
                    return fail("member_contract_mismatch", f"run {latest.run_id} review_contract 不匹配")
                latest_ctrl = latest.target.get("controller_code_head")
                if not isinstance(latest_ctrl, str) or latest_ctrl.lower() != policy.controller_code_head:
                    return fail("member_controller_mismatch", f"run {latest.run_id} controller_code_head 不匹配")
                if latest.outcome.get("state") != "success":
                    return fail("member_not_published_success", f"run {latest.run_id} state 非 success")

                latest_outcome_err = _verify_outcome_target_binding(
                    latest,
                    latest.outcome,
                    policy=policy,
                    expected_patch_id=recorded_patch_id,
                )
                if latest_outcome_err is not None:
                    return fail(latest_outcome_err[0], latest_outcome_err[1])

                reused_from = latest.outcome.get("reused_from")
                if not isinstance(reused_from, dict):
                    return fail("member_evidence_corrupted", f"run {latest.run_id} reused_from 不是合法对象")

                adm_err = _check_admission_binding(
                    reused_from.get("admission"),
                    policy=policy,
                    run_id=latest.run_id,
                )
                if adm_err is not None:
                    return fail(adm_err[0], adm_err[1])

                origin_run_id = reused_from.get("run_id")
                if not isinstance(origin_run_id, str) or not origin_run_id.strip():
                    return fail("member_reuse_origin_missing", f"run {latest.run_id} reused_from.run_id 缺失")
                if origin_run_id == latest.run_id:
                    return fail("member_chained_reuse_not_allowed", f"run {latest.run_id} reused_from 自引用")

                origin_matches = [run for run in pr_runs if run.run_id == origin_run_id]
                if not origin_matches:
                    return fail("member_reuse_origin_missing", f"找不到同 PR 的原件 run={origin_run_id}")
                if len(origin_matches) > 1:
                    return fail("member_evidence_corrupted", f"存在重复的原件 run_id={origin_run_id}")
                origin = origin_matches[0]

                member_pub_err = _verify_publication_binding(
                    latest,
                    latest.outcome.get("publication"),
                    patch_id=recorded_patch_id,
                    reuse_origin_run_id=origin.run_id,
                )
                if member_pub_err is not None:
                    return fail(member_pub_err[0], member_pub_err[1])

                if _run_has_block(origin):
                    return fail("member_blocked", f"沿用原件 run={origin.run_id} 存在 BLOCK 证据")
                if not _run_is_settled(origin):
                    return fail("member_unsettled_run", f"沿用原件 run={origin.run_id} 未完结")

                origin_err = _verify_direct_pass_run(
                    origin,
                    repository_id=repository_id,
                    policy=policy,
                    replay_repo=active_replay,
                )
                if origin_err is not None:
                    return fail(origin_err[0], origin_err[1])

                origin_recorded_patch_id = origin.target.get("patch_id")
                reused_recorded_patch_id = reused_from.get("patch_id")
                if (
                    origin_recorded_patch_id != recorded_patch_id
                    or reused_recorded_patch_id != recorded_patch_id
                ):
                    return fail(
                        "member_patch_id_mismatch",
                        f"PR #{member.pr_number} 沿用原件与当前成员的 patch_id 不一致",
                    )

                reused_head = reused_from.get("head_sha")
                reused_base = reused_from.get("base_sha")
                reused_mb = reused_from.get("merge_base_sha")
                if (
                    not isinstance(reused_head, str)
                    or reused_head.lower() != origin.head_sha
                    or not isinstance(reused_base, str)
                    or reused_base.lower() != origin.base_sha
                    or not isinstance(reused_mb, str)
                    or reused_mb.lower() != origin.merge_base_sha
                ):
                    return fail(
                        "member_reuse_binding_invalid",
                        f"run {latest.run_id} reused_from 来源 SHA 与原件 run={origin.run_id} 不一致",
                    )

                assert origin.outcome is not None
                origin_pub = origin.outcome.get("publication")
                if not isinstance(origin_pub, dict):
                    return fail(
                        "member_reuse_binding_invalid",
                        f"run {latest.run_id} 原件 run={origin.run_id} 缺少合法 publication",
                    )
                reused_pub = reused_from.get("publication")
                if not isinstance(reused_pub, dict):
                    return fail(
                        "member_reuse_binding_invalid",
                        f"run {latest.run_id} reused_from.publication 缺失或不是对象",
                    )
                reused_pub_id = reused_pub.get("id")
                reused_pub_sha = reused_pub.get("sha")
                reused_pub_state = reused_pub.get("state")
                reused_pub_desc = reused_pub.get("description")
                origin_pub_id = origin_pub.get("id")
                origin_pub_sha = origin_pub.get("sha")
                origin_pub_state = origin_pub.get("state")
                origin_pub_desc = origin_pub.get("description")
                if (
                    type(reused_pub_id) is not type(origin_pub_id)
                    or reused_pub_id != origin_pub_id
                    or not isinstance(reused_pub_sha, str)
                    or not isinstance(origin_pub_sha, str)
                    or reused_pub_sha.lower() != origin_pub_sha.lower()
                    or reused_pub_state != origin_pub_state
                    or reused_pub_desc != origin_pub_desc
                ):
                    return fail(
                        "member_reuse_binding_invalid",
                        f"run {latest.run_id} reused_from.publication 与原件 run={origin.run_id} 不一致",
                    )
                if reused_from.get("reviews") != origin.outcome.get("reviews"):
                    return fail(
                        "member_reuse_binding_invalid",
                        f"run {latest.run_id} reused_from.reviews 与原件 run={origin.run_id} 不一致",
                    )

                for run in same_patch_runs:
                    if (
                        run.registered_at_ns > origin.registered_at_ns
                        and (run.outcome is None or run.outcome.get("verdict") != "PASS")
                    ):
                        return fail(
                            "member_pass_superseded",
                            f"PR #{member.pr_number} 原件 PASS 之后存在非 PASS 重审（run={run.run_id}）",
                        )

                source_run_id = origin.run_id
                reused = True

            if published_statuses is not None:
                observed_state = published_statuses.get(member.head_sha)
                if observed_state != "success":
                    return fail(
                        "member_status_not_success",
                        f"PR #{member.pr_number} head={member.head_sha[:12]} 远端已发布状态为 {observed_state!r}，非 'success'",
                    )

            proof = MemberPassProof(
                pr_number=member.pr_number,
                head_sha=member.head_sha,
                source_run_id=source_run_id,
                member_run_id=latest.run_id,
                patch_id=recorded_patch_id,
                reused=reused,
                reviewer_models=policy.expected_models,
                image_id=policy.deployment_image_id,
            )
            return MemberPassVerification(
                passed=True,
                pr_number=member.pr_number,
                head_sha=member.head_sha,
                reason_code="member_pass_verified",
                detail=f"PR #{member.pr_number} PASS 核验通过（source_run={source_run_id}）",
                proof=proof,
            )

        if replay_repo is not None:
            return _evaluate_with_replay(replay_repo)
        with _isolated_replay_repo(source_repo) as isolated_repo:
            return _evaluate_with_replay(isolated_repo)
    except (_GitQueryError, OSError, subprocess.SubprocessError) as exc:
        return fail("replay_env_error", f"隔离重放环境或 Git 执行故障：{type(exc).__name__}")
    except (
        _EvidenceError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        RecursionError,
        MemoryError,
    ) as exc:
        return fail("member_evidence_corrupted", f"审查证据读取或解析异常：{type(exc).__name__}")


def verify_member_pass(
    member: MergeGroupMember,
    *,
    repository_id: int,
    source_repo: Path,
    state_root: Path,
    policy: MergeGroupPolicy,
    published_statuses: Mapping[str, str] | None = None,
) -> MemberPassVerification:
    """严格核验单个队列成员在当前 head_sha 上的正式 PASS 证据。"""
    if not isinstance(member, MergeGroupMember):
        raise MergeGroupError("member 必须是 MergeGroupMember 实例")
    if not isinstance(policy, MergeGroupPolicy):
        raise MergeGroupError("policy 必须是 MergeGroupPolicy 实例")
    _parse_positive_int(repository_id, field="repository_id")
    try:
        return _verify_member_pass_in_repo(
            member,
            repository_id=repository_id,
            replay_repo=None,
            source_repo=source_repo,
            state_root=state_root,
            policy=policy,
            published_statuses=published_statuses,
        )
    except (_GitQueryError, OSError, subprocess.SubprocessError) as exc:
        return MemberPassVerification(
            passed=False,
            pr_number=member.pr_number,
            head_sha=member.head_sha,
            reason_code="replay_env_error",
            detail=f"隔离重放环境或 Git 执行故障：{type(exc).__name__}",
            proof=None,
        )


def _truncate_description(text: str, *, limit: int = MAX_STATUS_DESCRIPTION_LEN) -> str:
    single_line = " ".join(_split_lines_strict(text)).strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 1] + "…"


def _format_public_status_description(
    *,
    verdict: Literal["PASS", "ERROR"],
    reason_code: str,
    target: MergeGroupTarget,
    member_proofs: Sequence[MemberPassProof],
    failed_members: Sequence[tuple[int, str, str]],
    tree_result: TreeVerificationResult,
) -> str:
    """仅使用白名单原因码模板与已校验公开标识构造远端 GitHub status 描述，绝不拼入本地路径或 Git stderr。"""
    base_short = target.base_sha[:12]
    head_short = target.head_sha[:12]
    if verdict == "PASS":
        pr_list = ",".join(f"#{proof.pr_number}" for proof in member_proofs)
        tree_short = (tree_result.actual_tree_sha or "")[:12]
        return _truncate_description(
            f"合并队列核验通过：沿用 {len(member_proofs)} 个成员 PASS（{pr_list}），树 {tree_short} 一致"
        )

    safe_code = reason_code if reason_code in _REASON_DESCRIPTIONS else "member_evidence_corrupted"
    template = _REASON_DESCRIPTIONS[safe_code]
    if failed_members:
        safe_failed_parts = [
            f"#{pr}:{code if code in _REASON_DESCRIPTIONS else 'member_evidence_corrupted'}"
            for pr, code, _ in failed_members
        ]
        failed_summary = ", ".join(safe_failed_parts)
        if not tree_result.matched:
            tree_code = (
                tree_result.reason_code
                if tree_result.reason_code in _REASON_DESCRIPTIONS
                else "merge_failed"
            )
            raw_desc = (
                f"合并队列拒绝放行：{len(failed_members)} 个成员未通过（{failed_summary}），"
                f"且树核验失败（{tree_code}，b={base_short} h={head_short}）"
            )
        else:
            raw_desc = (
                f"合并队列拒绝放行：{len(failed_members)} 个成员未通过（{failed_summary}，"
                f"b={base_short} h={head_short}）"
            )
        return _truncate_description(raw_desc)

    if not tree_result.matched:
        raw_desc = f"合并队列拒绝放行（{safe_code}）：{template}（b={base_short} h={head_short}）"
        return _truncate_description(raw_desc)

    raw_desc = (
        f"合并队列拒绝放行（{safe_code}）：{template}，"
        f"共 {len(tree_result.overlapping_files)} 个重叠文件（b={base_short} h={head_short}）"
    )
    return _truncate_description(raw_desc)


@dataclass(frozen=True)
class MergeGroupDecision:
    """合并队列最终裁决（只输出 PASS/success 或 ERROR/error）。"""

    verdict: Literal["PASS", "ERROR"]
    status_context: str
    status_state: Literal["success", "error"]
    status_description: str
    reason_code: str
    head_sha: str
    base_sha: str
    head_ref: str
    expected_tree_sha: str | None
    actual_tree_sha: str | None
    overlapping_files: tuple[str, ...]
    member_proofs: tuple[MemberPassProof, ...]
    failed_members: tuple[tuple[int, str, str], ...]
    policy_version: str
    review_contract: str
    controller_code_head: str
    deployment_image_id: str

    def __post_init__(self) -> None:
        if self.verdict == "PASS":
            if self.status_state != "success":
                raise MergeGroupError("PASS 裁决的 status_state 必须为 'success'")
        elif self.verdict == "ERROR":
            if self.status_state != "error":
                raise MergeGroupError("ERROR 裁决的 status_state 必须为 'error'")
        else:
            raise MergeGroupError(f"非法 verdict：{self.verdict!r}")
        if self.status_context != MERGE_GROUP_STATUS_CONTEXT:
            raise MergeGroupError(f"status_context 必须为 {MERGE_GROUP_STATUS_CONTEXT!r}")
        if len(self.status_description) > MAX_STATUS_DESCRIPTION_LEN:
            raise MergeGroupError(
                f"status_description 长度超过 {MAX_STATUS_DESCRIPTION_LEN} 字符：{len(self.status_description)}"
            )

    def to_status_payload(self, target_url: str | None = None) -> dict[str, str]:
        """构造 GitHub Commit Status REST API 请求体。"""
        payload: dict[str, str] = {
            "state": self.status_state,
            "context": self.status_context,
            "description": self.status_description,
        }
        if target_url is not None:
            if not isinstance(target_url, str) or not target_url.strip():
                raise MergeGroupError("target_url 必须是非空字符串")
            payload["target_url"] = target_url
        return payload

    def to_outcome_record(self) -> dict[str, Any]:
        """构造结构化审计回执。"""
        return {
            "kind": "merge_group",
            "verdict": self.verdict,
            "state": self.status_state,
            "status_context": self.status_context,
            "status_description": self.status_description,
            "reason_code": self.reason_code,
            "head_sha": self.head_sha,
            "base_sha": self.base_sha,
            "head_ref": self.head_ref,
            "expected_tree_sha": self.expected_tree_sha,
            "actual_tree_sha": self.actual_tree_sha,
            "overlapping_files": list(self.overlapping_files),
            "reused_members": [
                {
                    "pr_number": proof.pr_number,
                    "head_sha": proof.head_sha,
                    "member_run_id": proof.member_run_id,
                    "source_run_id": proof.source_run_id,
                    "patch_id": proof.patch_id,
                    "reused": proof.reused,
                    "reviewer_models": list(proof.reviewer_models),
                    "image_id": proof.image_id,
                }
                for proof in self.member_proofs
            ],
            "failed_members": [
                {"pr_number": pr, "reason_code": code, "detail": detail}
                for pr, code, detail in self.failed_members
            ],
            "policy_version": self.policy_version,
            "review_contract": self.review_contract,
            "controller_code_head": self.controller_code_head,
            "deployment_image_id": self.deployment_image_id,
        }


def evaluate_merge_group(
    target: MergeGroupTarget,
    *,
    source_repo: Path,
    state_root: Path,
    policy: MergeGroupPolicy,
    published_statuses: Mapping[str, str] | None = None,
) -> MergeGroupDecision:
    """总控评估：逐一核验全部成员 PASS，并执行只读顺序合并树等价核验，fail-closed 输出裁决。"""
    if not isinstance(target, MergeGroupTarget):
        raise MergeGroupError("target 必须是 MergeGroupTarget 实例")
    if not isinstance(policy, MergeGroupPolicy):
        raise MergeGroupError("policy 必须是 MergeGroupPolicy 实例")

    member_proofs: list[MemberPassProof] = []
    failed_members: list[tuple[int, str, str]] = []

    try:
        with _isolated_replay_repo(source_repo) as replay_repo:
            for member in target.members:
                verification = _verify_member_pass_in_repo(
                    member,
                    repository_id=target.repository_id,
                    replay_repo=replay_repo,
                    source_repo=source_repo,
                    state_root=state_root,
                    policy=policy,
                    published_statuses=published_statuses,
                )
                if verification.passed and verification.proof is not None:
                    member_proofs.append(verification.proof)
                else:
                    failed_members.append((member.pr_number, verification.reason_code, verification.detail))
            tree_result = _verify_merge_group_tree_in_repo(target, replay_repo=replay_repo)
    except (_GitQueryError, OSError, subprocess.SubprocessError) as exc:
        tree_result = TreeVerificationResult(
            matched=False,
            reason_code="replay_env_error",
            detail=f"隔离重放环境或 Git 执行故障：{type(exc).__name__}",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )

    if not failed_members and tree_result.matched and not (
        policy.reject_overlapping_files and tree_result.overlapping_files
    ):
        description = _format_public_status_description(
            verdict="PASS",
            reason_code="merge_group_pass_reused",
            target=target,
            member_proofs=member_proofs,
            failed_members=failed_members,
            tree_result=tree_result,
        )
        return MergeGroupDecision(
            verdict="PASS",
            status_context=MERGE_GROUP_STATUS_CONTEXT,
            status_state="success",
            status_description=description,
            reason_code="merge_group_pass_reused",
            head_sha=target.head_sha,
            base_sha=target.base_sha,
            head_ref=target.head_ref,
            expected_tree_sha=tree_result.expected_tree_sha,
            actual_tree_sha=tree_result.actual_tree_sha,
            overlapping_files=tree_result.overlapping_files,
            member_proofs=tuple(member_proofs),
            failed_members=(),
            policy_version=policy.policy_version,
            review_contract=policy.review_contract,
            controller_code_head=policy.controller_code_head,
            deployment_image_id=policy.deployment_image_id,
        )

    if failed_members:
        reason_code = failed_members[0][1]
    elif not tree_result.matched:
        reason_code = tree_result.reason_code
    else:
        reason_code = "overlapping_files_rejected"

    description = _format_public_status_description(
        verdict="ERROR",
        reason_code=reason_code,
        target=target,
        member_proofs=member_proofs,
        failed_members=failed_members,
        tree_result=tree_result,
    )
    return MergeGroupDecision(
        verdict="ERROR",
        status_context=MERGE_GROUP_STATUS_CONTEXT,
        status_state="error",
        status_description=description,
        reason_code=reason_code,
        head_sha=target.head_sha,
        base_sha=target.base_sha,
        head_ref=target.head_ref,
        expected_tree_sha=tree_result.expected_tree_sha,
        actual_tree_sha=tree_result.actual_tree_sha,
        overlapping_files=tree_result.overlapping_files,
        member_proofs=tuple(member_proofs),
        failed_members=tuple(failed_members),
        policy_version=policy.policy_version,
        review_contract=policy.review_contract,
        controller_code_head=policy.controller_code_head,
        deployment_image_id=policy.deployment_image_id,
    )
