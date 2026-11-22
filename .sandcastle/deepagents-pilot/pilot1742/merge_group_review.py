"""#1926 合并队列（merge_group）只读顺序合并树等价与成员 PASS 沿用核验器。

核心不变量（Fail-Closed）：
1. 队列中每一位成员在自己的 head 上都必须具备经完整复验的正式 PASS 证据（直审或单跳 reused_from）；
2. 队列批次 head_sha 对应的树必须与「按队列顺序把各成员依次合入 base_sha」产生的树逐字节一致；
3. 顺序合并重放全程在临时对象目录执行，绝不向 source_repo 写入任何 git 对象、ref、index 或工作树文件；
4. 任一条件不满足、对象缺失、存在冲突、证据损坏或不可核实，一律返回 verdict="ERROR" / status_state="error"。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MERGE_GROUP_STATUS_CONTEXT = "deepagents/review"
DEFAULT_EXPECTED_MODELS: tuple[str, ...] = ("kimi-k3.1-pro", "claude-opus-5-5")
MAX_STATUS_DESCRIPTION_LEN = 140

_ALLOWED_QUEUE_ENTRY_STATES: frozenset[str] = frozenset(
    {"QUEUED", "AWAITING_CHECKS", "MERGEABLE", "LOCKED"}
)
_COMMIT_SHA_RE = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")
_PATCH_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}")
_BRANCH_RE = re.compile(r"[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*")
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
_MODEL_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
_MERGE_GROUP_REF_RE = re.compile(
    r"(?:refs/heads/)?gh-readonly-queue/"
    r"(?P<base_branch>[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)/"
    r"pr-(?P<lead_pr>[1-9][0-9]*)-"
    r"(?P<base_sha>[0-9a-fA-F]{40}|[0-9a-fA-F]{64})"
)
_RUN_DIR_PREFIX_RE = re.compile(r"r(?P<repo>[1-9][0-9]*)-p(?P<pr>[1-9][0-9]*)-.*")
_JSON_FENCE_RE = re.compile(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
_BLOCK_VERDICT_RE = re.compile(r"VERDICT:\s*BLOCK")


class MergeGroupError(ValueError):
    """合并队列输入、边界或模型不变量校验失败。"""


class _EvidenceError(Exception):
    """内部异常：本地审查证据目录、权限、软链或 JSON 内容异常。"""


def _split_lines_strict(text: str) -> list[str]:
    """仅按 ASCII LF / CRLF / CR 拆分行，避免 Unicode 行分隔符陷阱。"""
    if not text:
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _first_line_strict(text: str) -> str:
    if not text:
        return ""
    return _split_lines_strict(text)[0]


def _unwrap_json_fence(text: str) -> str:
    fenced = _JSON_FENCE_RE.fullmatch(text.strip())
    return fenced.group(1) if fenced else text


def _message_blocks(text: str) -> bool:
    """判定 agent 最终消息是否为 BLOCK（与 external_review._message_blocks 同口径）。"""
    try:
        value = json.loads(_unwrap_json_fence(text))
    except ValueError:
        return _BLOCK_VERDICT_RE.search(text) is not None
    if not isinstance(value, dict):
        return _BLOCK_VERDICT_RE.search(text) is not None
    summary = value.get("summary")
    first_line = _first_line_strict(summary) if isinstance(summary, str) else ""
    return value.get("status") == "blocked" or first_line == "VERDICT: BLOCK"


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
    if ".." in raw or not _BRANCH_RE.fullmatch(raw):
        raise MergeGroupError(f"{field} 含有非法字符或路径穿越段：{raw!r}")
    segments = raw.split("/")
    if any(seg in (".", "..") for seg in segments):
        raise MergeGroupError(f"{field} 不能包含 '.' 或 '..' 路径段：{raw!r}")
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


def _parse_single_queue_entry(raw_entry: object, index: int) -> _ParsedQueueEntry:
    if not isinstance(raw_entry, Mapping):
        raise MergeGroupError(f"entries.nodes[{index}] 必须是映射对象")
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
    """解析 GitHub GraphQL mergeQueue.entries 响应并提取完整连续前缀。"""
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

    parsed_entries: list[_ParsedQueueEntry] = []
    seen_positions: set[int] = set()
    for idx, raw_entry in enumerate(nodes):
        entry = _parse_single_queue_entry(raw_entry, idx)
        if entry.position in seen_positions:
            raise MergeGroupError(f"mergeQueue 存在重复 position={entry.position}")
        seen_positions.add(entry.position)
        parsed_entries.append(entry)

    matches = [entry for entry in parsed_entries if entry.head_oid == target_sha]
    if not matches:
        if has_next_page:
            raise MergeGroupError(
                f"未找到 target_head_sha={target_sha} 且 pageInfo.hasNextPage=true，队列列表被截断"
            )
        raise MergeGroupError(f"在 mergeQueue.entries 中未找到 target_head_sha={target_sha}")
    if len(matches) > 1:
        raise MergeGroupError(f"在 mergeQueue.entries 中发现多个重复的 target_head_sha={target_sha}")
    target_entry = matches[0]

    by_position = {entry.position: entry for entry in parsed_entries}
    prefix: list[_ParsedQueueEntry] = []
    for pos in range(1, target_entry.position + 1):
        entry_at_pos = by_position.get(pos)
        if entry_at_pos is None:
            truncation_hint = "（pageInfo.hasNextPage=true，疑似分页截断）" if has_next_page else ""
            raise MergeGroupError(
                f"合并队列前缀不连续：缺少 position={pos}（目标 position={target_entry.position}）{truncation_hint}"
            )
        prefix.append(entry_at_pos)

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


def _git_env(
    *,
    object_dir: Path | None = None,
    alternate_object_dirs: Sequence[str] = (),
) -> dict[str, str]:
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
    if object_dir is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
    if alternate_object_dirs:
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(alternate_object_dirs)
    return env


def _run_git(
    repo: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    run_env = dict(env) if env is not None else _git_env()
    return subprocess.run(
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


def compute_patch_identity(source_repo: Path, merge_base_sha: str, head_sha: str) -> str:
    """用 git plumbing 重算补丁身份（与 external_review.patch_identity 逐字节一致）。"""
    mb = _parse_commit_sha(merge_base_sha, field="merge_base_sha")
    head = _parse_commit_sha(head_sha, field="head_sha")
    proc = _run_git(
        source_repo,
        "diff-tree",
        "-r",
        "--raw",
        "-z",
        "--no-renames",
        "--no-abbrev",
        mb,
        head,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise MergeGroupError(f"无法计算补丁身份（{mb}..{head}）：{stderr}")
    return "sha256:" + hashlib.sha256(proc.stdout).hexdigest()


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
    source_repo: Path,
    current_commit: str,
    member_head_sha: str,
    *,
    env: Mapping[str, str],
) -> set[str]:
    """统计成员相对 merge-base(current_commit, member_head_sha) 改动的文件路径。"""
    mb_proc = _run_git(source_repo, "merge-base", current_commit, member_head_sha, env=env)
    if mb_proc.returncode != 0:
        return set()
    mb_raw = _first_line_strict(mb_proc.stdout.decode("utf-8", errors="replace")).strip()
    if not _COMMIT_SHA_RE.fullmatch(mb_raw):
        return set()
    diff_proc = _run_git(
        source_repo,
        "diff-tree",
        "-r",
        "--name-only",
        "-z",
        "--no-renames",
        mb_raw.lower(),
        member_head_sha,
        env=env,
    )
    if diff_proc.returncode != 0:
        return set()
    paths: set[str] = set()
    for raw_path in diff_proc.stdout.split(b"\x00"):
        if raw_path:
            paths.add(raw_path.decode("utf-8", errors="surrogateescape"))
    return paths


def _resolve_source_objects_dir(source_repo: Path) -> Path | None:
    proc = _run_git(source_repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if proc.returncode != 0:
        return None
    common_dir_raw = _first_line_strict(proc.stdout.decode("utf-8", errors="replace")).strip()
    if not common_dir_raw:
        return None
    objects_dir = Path(common_dir_raw) / "objects"
    if not objects_dir.is_dir():
        return None
    return objects_dir


def verify_merge_group_tree(
    target: MergeGroupTarget,
    *,
    source_repo: Path,
) -> TreeVerificationResult:
    """在完全只读隔离环境中顺序重放合并，并比对最终树与 head_sha^{tree} 是否逐字节一致。"""
    if not isinstance(target, MergeGroupTarget):
        raise MergeGroupError("target 必须是 MergeGroupTarget 实例")

    source_objects = _resolve_source_objects_dir(source_repo)
    if source_objects is None:
        return TreeVerificationResult(
            matched=False,
            reason_code="merge_failed",
            detail=f"无法解析源仓库 git common objects 目录：{source_repo}",
            base_tree_sha=None,
            actual_tree_sha=None,
            expected_tree_sha=None,
            step_trees=(),
            overlapping_files=(),
        )

    read_env = _git_env()

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
        cat_proc = _run_git(source_repo, "cat-file", "-t", sha, env=read_env)
        if cat_proc.returncode != 0:
            return TreeVerificationResult(
                matched=False,
                reason_code="missing_object",
                detail=f"源仓库缺少对象 {label}={sha}",
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
    anc_proc = _run_git(source_repo, "merge-base", "--is-ancestor", target.base_sha, target.head_sha, env=read_env)
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
    base_tree_proc = _run_git(source_repo, "rev-parse", f"{target.base_sha}^{{tree}}", env=read_env)
    actual_tree_proc = _run_git(source_repo, "rev-parse", f"{target.head_sha}^{{tree}}", env=read_env)
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

    # 4. 在临时对象库中顺序重放合并（严禁写入 source_repo）
    alternates: list[str] = [str(source_objects)]
    existing_alternates = os.environ.get("GIT_ALTERNATE_OBJECT_DIRECTORIES", "")
    if existing_alternates:
        for entry in existing_alternates.split(os.pathsep):
            if entry and entry not in alternates:
                alternates.append(entry)

    step_trees: list[tuple[int, str]] = []
    touched_by_path: dict[str, set[int]] = {}

    def _current_overlaps() -> tuple[str, ...]:
        return tuple(sorted(path for path, prs in touched_by_path.items() if len(prs) >= 2))

    with tempfile.TemporaryDirectory(prefix="merge-group-objects-") as tmp_root:
        tmp_objects = Path(tmp_root) / "objects"
        tmp_objects.mkdir(mode=0o700)
        isolated_env = _git_env(object_dir=tmp_objects, alternate_object_dirs=alternates)
        current_commit = target.base_sha

        for idx, member in enumerate(target.members):
            for touched_path in _collect_touched_paths(
                source_repo,
                current_commit,
                member.head_sha,
                env=isolated_env,
            ):
                touched_by_path.setdefault(touched_path, set()).add(member.pr_number)

            merge_proc = _run_git(
                source_repo,
                "merge-tree",
                "--write-tree",
                "--no-messages",
                current_commit,
                member.head_sha,
                env=isolated_env,
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
            step_trees.append((member.pr_number, step_tree_sha))

            if idx + 1 < len(target.members):
                commit_proc = _run_git(
                    source_repo,
                    "commit-tree",
                    step_tree_sha,
                    "-p",
                    current_commit,
                    "-p",
                    member.head_sha,
                    "-m",
                    "merge-group-step",
                    env=isolated_env,
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


def _check_safe_directory(path: Path, *, check_ownership: bool) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise _EvidenceError(f"无法读取目录属性：{path}（{exc}）") from None
    if not stat.S_ISDIR(info.st_mode):
        raise _EvidenceError(f"路径不是常规目录或存在符号链接：{path}")
    if check_ownership and (info.st_uid != os.getuid() or bool(info.st_mode & 0o022)):
        raise _EvidenceError(f"目录属主或权限不安全：{path}")


def _check_safe_path_chain(root: Path, target_path: Path, *, check_ownership: bool) -> None:
    """从 root 到 target_path.parent 逐级检查非符号链接与目录权限/属主。"""
    _check_safe_directory(root, check_ownership=check_ownership)
    try:
        rel = target_path.relative_to(root)
    except ValueError:
        raise _EvidenceError(f"路径越出 state_root：{target_path}") from None
    cursor = root
    for part in rel.parts[:-1]:
        cursor = cursor / part
        _check_safe_directory(cursor, check_ownership=check_ownership)


def _safe_read_text(root: Path, path: Path, *, check_ownership: bool) -> str:
    _check_safe_path_chain(root, path, check_ownership=check_ownership)
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
        stream = os.fdopen(fd, "r", encoding="utf-8")
        owned_fd = None
        with stream:
            return stream.read()
    except _EvidenceError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise _EvidenceError(f"读取证据文本失败：{path}（{exc}）") from None
    finally:
        if owned_fd is not None:
            try:
                os.close(owned_fd)
            except OSError:
                pass


def _safe_read_json_dict(root: Path, path: Path, *, check_ownership: bool) -> dict[str, Any]:
    raw_text = _safe_read_text(root, path, check_ownership=check_ownership)
    try:
        parsed = json.loads(raw_text)
    except ValueError as exc:
        raise _EvidenceError(f"证据 JSON 损坏：{path}（{exc}）") from None
    if not isinstance(parsed, dict):
        raise _EvidenceError(f"证据 JSON 顶层不是对象：{path}")
    return parsed


@dataclass(frozen=True)
class _WorkerEvidence:
    model: str
    has_launch: bool
    receipt: dict[str, Any] | None
    events_text: str | None


@dataclass(frozen=True)
class _RunRecord:
    folder: Path
    run_id: str
    repository_id: int
    pr_number: int
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
        has_launch = os.path.lexists(launch_path)
        if has_launch:
            _safe_read_json_dict(state_root, launch_path, check_ownership=check_ownership)
        receipt_path = worker_dir / "receipt.json"
        receipt_data: dict[str, Any] | None = None
        if os.path.lexists(receipt_path):
            receipt_data = _safe_read_json_dict(state_root, receipt_path, check_ownership=check_ownership)
        events_path = worker_dir / "events.jsonl"
        events_text: str | None = None
        if os.path.lexists(events_path):
            events_text = _safe_read_text(state_root, events_path, check_ownership=check_ownership)
        workers[model] = _WorkerEvidence(
            model=model,
            has_launch=has_launch,
            receipt=receipt_data,
            events_text=events_text,
        )

    return _RunRecord(
        folder=folder,
        run_id=raw_run_id,
        repository_id=repo_id,
        pr_number=pr_number,
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
            # 非标准命名目录：按 fail-closed 尝试核验；如非目录/软链/损坏直接报错
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
    return not any(worker.has_launch and worker.receipt is None for worker in run.workers.values())


def _run_has_block(run: _RunRecord) -> bool:
    if run.outcome is not None:
        if run.outcome.get("verdict") == "BLOCK":
            return True
        reviews = run.outcome.get("reviews")
        if reviews is not None:
            if not isinstance(reviews, list):
                return True
            for review in reviews:
                if not isinstance(review, dict) or review.get("verdict") == "BLOCK":
                    return True

    for worker in run.workers.values():
        if worker.receipt is not None:
            result = worker.receipt.get("result")
            if isinstance(result, dict):
                if result.get("status") == "blocked":
                    return True
                summary = result.get("summary")
                if isinstance(summary, str) and (
                    _first_line_strict(summary) == "VERDICT: BLOCK"
                    or summary.startswith("VERDICT: BLOCK")
                ):
                    return True
        if worker.events_text is not None:
            final_text: str | None = None
            for line in _split_lines_strict(worker.events_text):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    return True
                if not isinstance(event, dict):
                    return True
                item = event.get("item")
                if (
                    event.get("type") == "item.completed"
                    and isinstance(item, dict)
                    and item.get("type") == "agent_message"
                ):
                    raw_text = item.get("text")
                    if not isinstance(raw_text, str):
                        return True
                    final_text = raw_text
            if final_text is not None and _message_blocks(final_text):
                return True
    return False


def _try_compute_patch_id(source_repo: Path, run: _RunRecord) -> str | None:
    try:
        return compute_patch_identity(source_repo, run.merge_base_sha, run.head_sha)
    except MergeGroupError:
        return None


def _verify_direct_pass_run(
    run: _RunRecord,
    *,
    repository_id: int,
    policy: MergeGroupPolicy,
    source_repo: Path,
) -> tuple[str, str, str] | None:
    """校验单条真实双审 PASS run。成功返回 None，失败返回 (reason_code, detail, '')。"""
    if run.repository_id != repository_id:
        return ("member_repository_mismatch", f"run {run.run_id} repository_id 不匹配", "")
    if run.target.get("policy_version") != policy.policy_version:
        return (
            "member_policy_mismatch",
            f"run {run.run_id} policy_version 不匹配：{run.target.get('policy_version')!r}",
            "",
        )
    if run.target.get("review_contract") != policy.review_contract:
        return ("member_contract_mismatch", f"run {run.run_id} review_contract 不匹配", "")
    if run.target.get("controller_code_head") != policy.controller_code_head:
        return (
            "member_controller_mismatch",
            f"run {run.run_id} controller_code_head 不匹配",
            "",
        )

    outcome = run.outcome
    if outcome is None:
        return ("member_unsettled_run", f"run {run.run_id} 缺少 outcome.json", "")
    if "migrated" in outcome:
        return ("member_migrated_not_allowed", f"run {run.run_id} 为 migrated 结论，禁止沿用", "")
    if "reused_from" in outcome:
        return ("member_chained_reuse_not_allowed", f"原件 run {run.run_id} 本身含 reused_from，禁止多跳沿用", "")
    if outcome.get("verdict") != "PASS" or outcome.get("state") != "success":
        return (
            "member_not_published_success",
            f"run {run.run_id} verdict/state 非 PASS/success",
            "",
        )
    publication = outcome.get("publication")
    if not isinstance(publication, dict) or publication.get("state") != "success":
        return ("member_not_published_success", f"run {run.run_id} 未发布 success", "")

    reviews = outcome.get("reviews")
    if not isinstance(reviews, list) or len(reviews) != len(policy.expected_models):
        return ("member_models_mismatch", f"run {run.run_id} reviews 数量与期望模型不符", "")
    seen_review_models: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            return ("member_models_mismatch", f"run {run.run_id} reviews 含非法条目", "")
        model = review.get("model")
        verdict = review.get("verdict")
        if not isinstance(model, str) or model in seen_review_models or verdict != "PASS":
            return (
                "member_models_mismatch",
                f"run {run.run_id} 模型评审条目非法或非 PASS：{model!r}={verdict!r}",
                "",
            )
        seen_review_models.add(model)
    if seen_review_models != set(policy.expected_models):
        return ("member_models_mismatch", f"run {run.run_id} 未精确覆盖期望双审模型", "")

    for model in policy.expected_models:
        worker = run.workers.get(model)
        if worker is None or worker.receipt is None:
            return ("member_missing_receipt", f"run {run.run_id} 缺少模型 {model} 的 receipt.json", "")
        receipt = worker.receipt
        if receipt.get("status") != "completed" or receipt.get("mode") != "review":
            return (
                "member_receipt_invalid",
                f"run {run.run_id} 模型 {model} 回执 status/mode 不符",
                "",
            )
        if "model" in receipt and receipt.get("model") != model:
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执 model 字段不符", "")
        if "run_id" in receipt and receipt.get("run_id") != run.run_id:
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执 run_id 不符", "")
        if "head_sha" in receipt and str(receipt.get("head_sha", "")).lower() != run.head_sha:
            return ("member_receipt_invalid", f"run {run.run_id} 模型 {model} 回执 head_sha 不符", "")
        if receipt.get("image_id") != policy.deployment_image_id:
            return (
                "member_image_mismatch",
                f"run {run.run_id} 模型 {model} 镜像 ID 与部署策略不符",
                "",
            )

    recorded_patch_id = run.target.get("patch_id")
    if not isinstance(recorded_patch_id, str) or not _PATCH_ID_RE.fullmatch(recorded_patch_id):
        return ("member_patch_id_mismatch", f"run {run.run_id} target.patch_id 缺失或格式非法", "")
    computed_patch_id = _try_compute_patch_id(source_repo, run)
    if computed_patch_id != recorded_patch_id:
        return (
            "member_patch_id_mismatch",
            f"run {run.run_id} 现场重算 patch_id 与记录不符",
            "",
        )
    return None


def _check_admission_binding(
    admission: object,
    *,
    policy: MergeGroupPolicy,
    run_id: str,
) -> tuple[str, str] | None:
    if admission is None:
        return None
    if not isinstance(admission, dict):
        return ("member_image_mismatch", f"run {run_id} admission 不是合法对象")
    if admission.get("image_id") != policy.deployment_image_id:
        return ("member_image_mismatch", f"run {run_id} admission.image_id 与策略不符")
    if (
        "controller_code_head" in admission
        and str(admission.get("controller_code_head", "")).lower() != policy.controller_code_head
    ):
        return ("member_controller_mismatch", f"run {run_id} admission.controller_code_head 与策略不符")
    return None


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
    except _EvidenceError as exc:
        return fail("member_evidence_corrupted", str(exc))

    head_runs = [run for run in pr_runs if run.head_sha == member.head_sha]
    if not head_runs:
        return fail(
            "member_missing_pass",
            f"PR #{member.pr_number} 在 head={member.head_sha[:12]} 上没有任何审查记录",
        )

    # 先检查当前 head_sha 上是否存在 BLOCK 或未完结 run
    for run in head_runs:
        if _run_has_block(run):
            return fail("member_blocked", f"PR #{member.pr_number} 在当前 head 存在 BLOCK 证据（run={run.run_id}）")
    for run in head_runs:
        if not _run_is_settled(run):
            return fail(
                "member_unsettled_run",
                f"PR #{member.pr_number} 在当前 head 存在未完结 run（run={run.run_id}）",
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

    # 校验当前成员的 patch_id 并现场重算
    recorded_patch_id = latest.target.get("patch_id")
    if not isinstance(recorded_patch_id, str) or not _PATCH_ID_RE.fullmatch(recorded_patch_id):
        return fail("member_patch_id_mismatch", f"PR #{member.pr_number} target.patch_id 缺失或非法")
    computed_patch_id = _try_compute_patch_id(source_repo, latest)
    if computed_patch_id != recorded_patch_id:
        return fail(
            "member_patch_id_mismatch",
            f"PR #{member.pr_number} 现场重算 patch_id 与记录不符",
        )

    # 筛出同 PR 中同一 patch_id 的全部历史 run（算不出 patch_id 且未记录的按同补丁保守纳入）
    same_patch_runs: list[_RunRecord] = []
    for run in pr_runs:
        other_recorded = run.target.get("patch_id")
        other_computed = _try_compute_patch_id(source_repo, run)
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

    # 分流：直审 PASS vs 1 跳 reused_from PASS
    if "reused_from" not in latest.outcome:
        err = _verify_direct_pass_run(
            latest,
            repository_id=repository_id,
            policy=policy,
            source_repo=source_repo,
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
        # 先核验成员自身 run 的政策与发布状态
        if latest.repository_id != repository_id:
            return fail("member_repository_mismatch", f"run {latest.run_id} repository_id 不匹配")
        if latest.target.get("policy_version") != policy.policy_version:
            return fail("member_policy_mismatch", f"run {latest.run_id} policy_version 不匹配")
        if latest.target.get("review_contract") != policy.review_contract:
            return fail("member_contract_mismatch", f"run {latest.run_id} review_contract 不匹配")
        if latest.target.get("controller_code_head") != policy.controller_code_head:
            return fail("member_controller_mismatch", f"run {latest.run_id} controller_code_head 不匹配")
        if latest.outcome.get("state") != "success":
            return fail("member_not_published_success", f"run {latest.run_id} state 非 success")
        publication = latest.outcome.get("publication")
        if not isinstance(publication, dict) or publication.get("state") != "success":
            return fail("member_not_published_success", f"run {latest.run_id} 未发布 success")

        reused_from = latest.outcome.get("reused_from")
        if not isinstance(reused_from, dict):
            return fail("member_evidence_corrupted", f"run {latest.run_id} reused_from 不是合法对象")

        # 校验 admission.image_id（支持 outcome.admission 与 outcome.reused_from.admission 两处）
        for adm_candidate in (latest.outcome.get("admission"), reused_from.get("admission")):
            adm_err = _check_admission_binding(adm_candidate, policy=policy, run_id=latest.run_id)
            if adm_err is not None:
                return fail(adm_err[0], adm_err[1])

        origin_run_id = reused_from.get("run_id")
        if not isinstance(origin_run_id, str) or not origin_run_id.strip():
            return fail("member_reuse_origin_missing", f"run {latest.run_id} reused_from.run_id 缺失")
        if origin_run_id == latest.run_id:
            return fail("member_chained_reuse_not_allowed", f"run {latest.run_id} reused_from 自引用")

        origin_matches = [run for run in pr_runs if run.run_id == origin_run_id]
        if not origin_matches:
            return fail(
                "member_reuse_origin_missing",
                f"找不到同 PR 的原件 run={origin_run_id}",
            )
        if len(origin_matches) > 1:
            return fail("member_evidence_corrupted", f"存在重复的原件 run_id={origin_run_id}")
        origin = origin_matches[0]

        if _run_has_block(origin):
            return fail("member_blocked", f"沿用原件 run={origin.run_id} 存在 BLOCK 证据")
        if not _run_is_settled(origin):
            return fail("member_unsettled_run", f"沿用原件 run={origin.run_id} 未完结")

        origin_err = _verify_direct_pass_run(
            origin,
            repository_id=repository_id,
            policy=policy,
            source_repo=source_repo,
        )
        if origin_err is not None:
            return fail(origin_err[0], origin_err[1])

        # 三方 patch_id 一致性校验（当前重算 == 原件重算 == 原件记录 == 当前记录）
        origin_recorded_patch_id = origin.target.get("patch_id")
        origin_computed_patch_id = _try_compute_patch_id(source_repo, origin)
        reused_recorded_patch_id = reused_from.get("patch_id")
        if (
            origin_recorded_patch_id != recorded_patch_id
            or origin_computed_patch_id != recorded_patch_id
            or (reused_recorded_patch_id is not None and reused_recorded_patch_id != recorded_patch_id)
        ):
            return fail(
                "member_patch_id_mismatch",
                f"PR #{member.pr_number} 沿用原件与当前成员的 patch_id 不一致",
            )

        # 原件之后同补丁若有非 PASS 登记，原件已被取代
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

    # 可选外部已绑定 App commit status 核验
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


def _truncate_description(text: str, *, limit: int = MAX_STATUS_DESCRIPTION_LEN) -> str:
    single_line = " ".join(_split_lines_strict(text)).strip()
    if len(single_line) <= limit:
        return single_line
    return single_line[: limit - 1] + "…"


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

    # 1. 不短路核验全部成员 PASS，完整收集失败明细便于排障
    for member in target.members:
        verification = verify_member_pass(
            member,
            repository_id=target.repository_id,
            source_repo=source_repo,
            state_root=state_root,
            policy=policy,
            published_statuses=published_statuses,
        )
        if verification.passed and verification.proof is not None:
            member_proofs.append(verification.proof)
        else:
            failed_members.append((member.pr_number, verification.reason_code, verification.detail))

    # 2. 执行只读零污染顺序合并树等价核验
    tree_result = verify_merge_group_tree(target, source_repo=source_repo)

    # 3. 仅当全部成员 PASS 且树一致且（未因重叠文件策略拒收）时放行
    if not failed_members and tree_result.matched and not (
        policy.reject_overlapping_files and tree_result.overlapping_files
    ):
        pr_list = ",".join(f"#{proof.pr_number}" for proof in member_proofs)
        tree_short = (tree_result.actual_tree_sha or "")[:12]
        description = _truncate_description(
            f"合并队列核验通过：沿用 {len(member_proofs)} 个成员 PASS（{pr_list}），树 {tree_short} 一致"
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
        failed_summary = ", ".join(f"#{pr}:{code}" for pr, code, _ in failed_members)
        if not tree_result.matched:
            raw_desc = (
                f"合并队列拒绝放行：{len(failed_members)} 个成员未通过（{failed_summary}），"
                f"且树核验失败（{tree_result.reason_code}）"
            )
        else:
            raw_desc = f"合并队列拒绝放行：{len(failed_members)} 个成员未通过 PASS 核验（{failed_summary}）"
    elif not tree_result.matched:
        reason_code = tree_result.reason_code
        raw_desc = f"合并队列拒绝放行：顺序合并树核验失败（{tree_result.reason_code}）：{tree_result.detail}"
    else:
        reason_code = "overlapping_files_rejected"
        overlap_preview = ", ".join(tree_result.overlapping_files[:3])
        raw_desc = (
            f"合并队列拒绝放行：检测到 {len(tree_result.overlapping_files)} 个跨成员重叠文件"
            f"（{overlap_preview}）"
        )

    return MergeGroupDecision(
        verdict="ERROR",
        status_context=MERGE_GROUP_STATUS_CONTEXT,
        status_state="error",
        status_description=_truncate_description(raw_desc),
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
