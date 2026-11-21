"""PR 改动路径风险分档与高风险 Secure Enclave 签批准入（#1930）。

按 #1929 与 2026-11-08 裁定：
- 仅「实盘下单/资金」与「密钥/凭证」两类高风险路径强制人工 Touch ID（CommitTarget）签批且禁止补丁沿用；
- CI 与审查配置路径走深度 AI 审查但不要求人工点头；
- 纯文档类路径（排除 REVIEW.md）走快速审查；其余路径走标准审查；
- 自保路径由代码层硬编码强制纳入高风险集，配置被篡改也不可绕过；边界一律 fail-closed。
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Final

from approval_signing.protocol import CommitTarget, Scope

from pilot1742.approval import SIGN_COMMAND, ApprovalDesk, Approved, SignedApprovals
from pilot1742.domain import parse_sha

SCHEMA_VERSION: Final = "review-risk-tiers/1"
DEFAULT_POLICY_PATH: Final[Path] = Path(__file__).resolve().parents[2] / "review-risk-tiers.json"

MANDATORY_HIGH_RISK_CATEGORY: Final = "secrets_and_credentials"
MANDATORY_HIGH_RISK_PATTERNS: Final[tuple[str, ...]] = (
    ".sandcastle/review-risk-tiers.json",
    ".sandcastle/deepagents-pilot/pilot1742/review_risk.py",
    ".sandcastle/deepagents-pilot/pilot1742/approval.py",
    ".sandcastle/approval-signing/**",
)

_POLICY_FIELDS: Final[frozenset[str]] = frozenset({
    "schema_version",
    "high_risk_categories",
    "deep_ai_only_patterns",
    "low_risk_patterns",
    "low_risk_excludes",
})
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_RENAME_OR_COPY = re.compile(r"^[RC][0-9]*$")
_SINGLE_PATH_STATUS = frozenset({"A", "M", "D", "T", "U", "X", "B"})


class RiskPolicyError(ValueError):
    """风险策略配置损坏、路径非法或 diff 提取失败（fail-closed 边界异常）。"""


class RiskTier(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ReviewDepth(Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class MatchedPath:
    path: str
    category: str
    pattern: str


def normalize_repo_path(raw: str) -> str:
    """校验仓库相对 POSIX 路径，拒绝空路径、绝对路径、路径穿越、反斜杠与 NUL 字节。"""
    if not isinstance(raw, str) or not raw:
        raise RiskPolicyError(f"路径必须为非空字符串：{raw!r}")
    if "\x00" in raw:
        raise RiskPolicyError(f"路径包含非法 NUL 字节：{raw!r}")
    if "\\" in raw:
        raise RiskPolicyError(f"路径必须使用 POSIX 斜杠 '/'：{raw!r}")
    if raw.startswith("/") or _WINDOWS_DRIVE.match(raw):
        raise RiskPolicyError(f"禁止绝对路径或盘符路径：{raw!r}")
    segments = raw.split("/")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise RiskPolicyError(f"路径包含非法段 {seg!r}：{raw!r}")
    return raw


def validate_glob_pattern(pattern: str) -> tuple[str, ...]:
    """校验 POSIX 段级 glob 模式并返回切分后的段元组。"""
    normalized = normalize_repo_path(pattern)
    segments = tuple(normalized.split("/"))
    for seg in segments:
        if "**" in seg and seg != "**":
            raise RiskPolicyError(f"双星号通配符必须独占整个路径段：{pattern!r}")
    return segments


@lru_cache(maxsize=512)
def _compile_segment_regex(pattern_segment: str) -> re.Pattern[str]:
    parts: list[str] = []
    for ch in pattern_segment:
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile(r"\A" + "".join(parts) + r"\Z", re.DOTALL)


def _fold_segments(segments: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(seg.casefold() for seg in segments)


def match_glob(path: str, pattern: str, *, case_sensitive: bool = True) -> bool:
    """按 POSIX 路径段匹配：单段 `*`/`?` 不跨 `/`，`**` 匹配零或多层目录（末尾 `/**` 至少匹配一层）。"""
    path_segs = tuple(normalize_repo_path(path).split("/"))
    pat_segs = validate_glob_pattern(pattern)
    if not case_sensitive:
        path_segs = _fold_segments(path_segs)
        pat_segs = _fold_segments(pat_segs)
    return _match_segments(path_segs, pat_segs)


def _match_segments(path_segs: tuple[str, ...], pat_segs: tuple[str, ...]) -> bool:
    pat_len = len(pat_segs)
    path_len = len(path_segs)
    memo: dict[tuple[int, int], bool] = {}

    def dp(pi: int, si: int) -> bool:
        key = (pi, si)
        if key in memo:
            return memo[key]
        if pi == pat_len:
            ans = si == path_len
        elif pat_segs[pi] == "**":
            if pi == pat_len - 1:
                ans = si < path_len
            else:
                ans = dp(pi + 1, si) or (si < path_len and dp(pi, si + 1))
        elif si == path_len:
            ans = False
        elif _compile_segment_regex(pat_segs[pi]).fullmatch(path_segs[si]) is not None:
            ans = dp(pi + 1, si + 1)
        else:
            ans = False
        memo[key] = ans
        return ans

    return dp(0, 0)


def _merge_mandatory_high_risk(
    raw_categories: Mapping[str, Iterable[str]],
) -> Mapping[str, tuple[str, ...]]:
    merged: dict[str, list[str]] = {}
    for category, patterns in raw_categories.items():
        if not isinstance(category, str) or not category.strip():
            raise RiskPolicyError(f"高风险类别名非法：{category!r}")
        validated: list[str] = []
        for pattern in patterns:
            validate_glob_pattern(pattern)
            if pattern not in validated:
                validated.append(pattern)
        merged[category] = validated

    protected = merged.setdefault(MANDATORY_HIGH_RISK_CATEGORY, [])
    for mandatory in MANDATORY_HIGH_RISK_PATTERNS:
        if mandatory not in protected:
            protected.append(mandatory)

    return MappingProxyType({cat: tuple(pats) for cat, pats in merged.items()})


@dataclass(frozen=True)
class RiskPolicy:
    """不可变风险分级策略；构造时强制注入不可绕过的代码级高风险自保集，并预解析全部 glob 段。"""

    schema_version: str
    high_risk_categories: Mapping[str, tuple[str, ...]]
    deep_ai_only_patterns: tuple[str, ...]
    low_risk_patterns: tuple[str, ...]
    low_risk_excludes: tuple[str, ...]
    _high_risk_segments: tuple[tuple[str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = field(
        init=False, repr=False, compare=False
    )
    _deep_ai_segments: tuple[tuple[str, tuple[str, ...]], ...] = field(
        init=False, repr=False, compare=False
    )
    _low_risk_segments: tuple[tuple[str, ...], ...] = field(
        init=False, repr=False, compare=False
    )
    _low_exclude_segments: tuple[tuple[str, ...], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise RiskPolicyError(
                f"不支持的 schema_version：{self.schema_version!r}，期望 {SCHEMA_VERSION!r}"
            )
        frozen_high = _merge_mandatory_high_risk(self.high_risk_categories)
        deep = tuple(dict.fromkeys(self.deep_ai_only_patterns))
        low = tuple(dict.fromkeys(self.low_risk_patterns))
        excludes = tuple(dict.fromkeys(self.low_risk_excludes))
        high_segments = tuple(
            (
                category,
                tuple((pattern, _fold_segments(validate_glob_pattern(pattern))) for pattern in patterns),
            )
            for category, patterns in frozen_high.items()
        )
        deep_segments = tuple(
            (pattern, _fold_segments(validate_glob_pattern(pattern))) for pattern in deep
        )
        low_segments = tuple(validate_glob_pattern(pattern) for pattern in low)
        exclude_segments = tuple(_fold_segments(validate_glob_pattern(pattern)) for pattern in excludes)
        object.__setattr__(self, "high_risk_categories", frozen_high)
        object.__setattr__(self, "deep_ai_only_patterns", deep)
        object.__setattr__(self, "low_risk_patterns", low)
        object.__setattr__(self, "low_risk_excludes", excludes)
        object.__setattr__(self, "_high_risk_segments", high_segments)
        object.__setattr__(self, "_deep_ai_segments", deep_segments)
        object.__setattr__(self, "_low_risk_segments", low_segments)
        object.__setattr__(self, "_low_exclude_segments", exclude_segments)


@dataclass(frozen=True)
class RiskAssessment:
    tier: RiskTier
    review_depth: ReviewDepth
    requires_human_approval: bool
    allow_patch_reuse: bool
    matched_high_paths: tuple[MatchedPath, ...]
    matched_deep_paths: tuple[MatchedPath, ...]
    all_paths: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.tier is RiskTier.HIGH:
            if not self.requires_human_approval or self.allow_patch_reuse or self.review_depth is not ReviewDepth.DEEP:
                raise RiskPolicyError("HIGH 档必须要求人工签批、深审且禁止补丁沿用")
        elif self.tier is RiskTier.LOW and self.requires_human_approval:
            raise RiskPolicyError("LOW 档不应要求人工签批")


@dataclass(frozen=True)
class DiffRiskAssessment:
    """只读 diff 风险评估结果；仅供展示/检查，不作为准入凭证传入签批入口。"""

    base_sha: str
    head_sha: str
    assessment: RiskAssessment

    def __post_init__(self) -> None:
        try:
            parse_sha(self.base_sha)
            parse_sha(self.head_sha)
        except ValueError as exc:
            raise RiskPolicyError(f"diff SHA 非法：{exc}") from exc


@dataclass(frozen=True)
class HighRiskApprovalResult:
    required: bool
    satisfied: bool
    status: str
    reason: str
    base_sha: str
    head_sha: str
    assessment: RiskAssessment
    request_path: str | None
    sign_command: str | None


def _strict_json_loads(data: bytes) -> object:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        if len({key for key, _ in pairs}) != len(pairs):
            raise RiskPolicyError("策略配置包含重复 JSON 键")
        return dict(pairs)

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    except RiskPolicyError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise RiskPolicyError(f"策略配置不是合法 UTF-8 JSON：{exc}") from exc


def _parse_pattern_list(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RiskPolicyError(f"字段 {field_name} 必须为字符串数组")
    for pattern in value:
        validate_glob_pattern(pattern)
    return tuple(value)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> RiskPolicy:
    """加载并严格校验声明式路径风险分级表，读取或校验失败一律抛 RiskPolicyError。"""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise RiskPolicyError(f"无法读取风险策略文件 {path}：{exc}") from exc

    raw = _strict_json_loads(raw_bytes)
    if not isinstance(raw, dict) or set(raw) != _POLICY_FIELDS:
        raise RiskPolicyError(f"风险策略顶层字段必须恰好为 {sorted(_POLICY_FIELDS)}")

    schema_version = raw["schema_version"]
    if not isinstance(schema_version, str) or schema_version != SCHEMA_VERSION:
        raise RiskPolicyError(f"schema_version 必须为 {SCHEMA_VERSION!r}，实得 {schema_version!r}")

    raw_high = raw["high_risk_categories"]
    if not isinstance(raw_high, dict) or not raw_high:
        raise RiskPolicyError("high_risk_categories 必须为非空对象")

    high_categories: dict[str, tuple[str, ...]] = {}
    for category, patterns in raw_high.items():
        if not isinstance(category, str) or not category.strip():
            raise RiskPolicyError(f"高风险类别名非法：{category!r}")
        parsed_patterns = _parse_pattern_list(patterns, f"high_risk_categories.{category}")
        if not parsed_patterns:
            raise RiskPolicyError(f"高风险类别 {category!r} 不能为空数组")
        high_categories[category] = parsed_patterns

    return RiskPolicy(
        schema_version=schema_version,
        high_risk_categories=high_categories,
        deep_ai_only_patterns=_parse_pattern_list(raw["deep_ai_only_patterns"], "deep_ai_only_patterns"),
        low_risk_patterns=_parse_pattern_list(raw["low_risk_patterns"], "low_risk_patterns"),
        low_risk_excludes=_parse_pattern_list(raw["low_risk_excludes"], "low_risk_excludes"),
    )


def classify_paths(
    paths: Iterable[str],
    policy: RiskPolicy | None = None,
) -> RiskAssessment:
    """对改动路径集执行 fail-closed 风险分档。

    合同：
    - 任意非法路径（空串、`..`、绝对路径、反斜杠、NUL）立即抛 RiskPolicyError；
    - 空路径集（如空提交或基线异常）按 fail-closed 判 HIGH，绝不降级为 LOW；
    - 保护类规则（高风险、深审、低风险排除）大小写不敏感，防止大小写拼写变体绕过降档；
    - 命中任一高风险或代码级自保路径 -> HIGH + DEEP + 人工签批 + 禁止补丁沿用；
    - 未命中高风险但命中仅深审路径 -> NORMAL + DEEP + 免人工签批；
    - 全部路径命中低风险（大小写敏感）且无排除项 -> LOW + QUICK + 免人工签批；
    - 其余 -> NORMAL + STANDARD + 免人工签批。
    """
    active_policy = load_policy() if policy is None else policy
    normalized = tuple(sorted({normalize_repo_path(p) for p in paths}))

    if not normalized:
        return RiskAssessment(
            tier=RiskTier.HIGH,
            review_depth=ReviewDepth.DEEP,
            requires_human_approval=True,
            allow_patch_reuse=False,
            matched_high_paths=(),
            matched_deep_paths=(),
            all_paths=(),
            reason="空路径集：按 fail-closed 规则提升为高风险，禁止降级放行",
        )

    matched_high: list[MatchedPath] = []
    matched_deep: list[MatchedPath] = []
    all_low = True

    for path in normalized:
        path_segs = tuple(path.split("/"))
        folded_path_segs = _fold_segments(path_segs)
        for category, compiled_patterns in active_policy._high_risk_segments:
            for pattern, pat_segs in compiled_patterns:
                if _match_segments(folded_path_segs, pat_segs):
                    matched_high.append(MatchedPath(path=path, category=category, pattern=pattern))
                    break

        for pattern, pat_segs in active_policy._deep_ai_segments:
            if _match_segments(folded_path_segs, pat_segs):
                matched_deep.append(MatchedPath(path=path, category="deep_ai_only", pattern=pattern))
                break

        if all_low:
            is_low = any(
                _match_segments(path_segs, pat_segs)
                for pat_segs in active_policy._low_risk_segments
            )
            is_excluded = any(
                _match_segments(folded_path_segs, pat_segs)
                for pat_segs in active_policy._low_exclude_segments
            )
            if not is_low or is_excluded:
                all_low = False

    if matched_high:
        categories = ", ".join(dict.fromkeys(item.category for item in matched_high))
        return RiskAssessment(
            tier=RiskTier.HIGH,
            review_depth=ReviewDepth.DEEP,
            requires_human_approval=True,
            allow_patch_reuse=False,
            matched_high_paths=tuple(matched_high),
            matched_deep_paths=tuple(matched_deep),
            all_paths=normalized,
            reason=f"命中高风险类别（{categories}），须用户 Secure Enclave 签批且禁止补丁沿用",
        )

    if matched_deep:
        return RiskAssessment(
            tier=RiskTier.NORMAL,
            review_depth=ReviewDepth.DEEP,
            requires_human_approval=False,
            allow_patch_reuse=True,
            matched_high_paths=(),
            matched_deep_paths=tuple(matched_deep),
            all_paths=normalized,
            reason="命中深审配置路径（CI/审查规则），走深度 AI 审查且免人工签批",
        )

    if all_low:
        return RiskAssessment(
            tier=RiskTier.LOW,
            review_depth=ReviewDepth.QUICK,
            requires_human_approval=False,
            allow_patch_reuse=True,
            matched_high_paths=(),
            matched_deep_paths=(),
            all_paths=normalized,
            reason="全部改动均属于低风险文档路径，走快速审查",
        )

    return RiskAssessment(
        tier=RiskTier.NORMAL,
        review_depth=ReviewDepth.STANDARD,
        requires_human_approval=False,
        allow_patch_reuse=True,
        matched_high_paths=(),
        matched_deep_paths=(),
        all_paths=normalized,
        reason="常规代码路径，走标准审查",
    )


def extract_diff_paths(repo_root: Path, base_sha: str, head_sha: str) -> tuple[str, ...]:
    """用 `git diff-tree -r -M -C --find-copies-harder --no-commit-id --name-status -z` 提取变更路径（重命名/复制含旧新路径）。"""
    try:
        base = parse_sha(base_sha)
        head = parse_sha(head_sha)
    except ValueError as exc:
        raise RiskPolicyError(f"diff SHA 非法：{exc}") from exc

    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "diff-tree",
            "-r",
            "-M",
            "-C",
            "--find-copies-harder",
            "--no-commit-id",
            "--name-status",
            "-z",
            str(base),
            str(head),
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RiskPolicyError(f"git diff-tree 失败（rc={proc.returncode}）：{stderr}")

    raw = proc.stdout
    if not raw:
        return ()
    if not raw.endswith(b"\x00"):
        raise RiskPolicyError("git diff-tree -z 输出未以 NUL 结尾")

    tokens = raw[:-1].split(b"\x00")
    extracted: set[str] = set()
    idx = 0
    total = len(tokens)
    while idx < total:
        try:
            status = tokens[idx].decode("ascii")
        except UnicodeDecodeError as exc:
            raise RiskPolicyError("git diff-tree 状态码非 ASCII") from exc
        idx += 1

        path_tokens: tuple[bytes, ...]
        if _RENAME_OR_COPY.fullmatch(status):
            if idx + 1 >= total:
                raise RiskPolicyError(f"git diff-tree 状态 {status!r} 缺少旧/新路径")
            path_tokens = (tokens[idx], tokens[idx + 1])
            idx += 2
        elif status in _SINGLE_PATH_STATUS:
            if idx >= total:
                raise RiskPolicyError(f"git diff-tree 状态 {status!r} 缺少路径")
            path_tokens = (tokens[idx],)
            idx += 1
        else:
            raise RiskPolicyError(f"未知的 git diff-tree 状态码：{status!r}")

        for token in path_tokens:
            try:
                decoded = token.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RiskPolicyError(f"变更路径非合法 UTF-8：{token!r}") from exc
            extracted.add(normalize_repo_path(decoded))

    return tuple(sorted(extracted))


def assess_diff(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    policy: RiskPolicy | None = None,
) -> DiffRiskAssessment:
    """从 git diff 提取变更路径（含重命名/复制旧新路径）并返回只读 diff 风险评估。"""
    try:
        base = parse_sha(base_sha)
        head = parse_sha(head_sha)
    except ValueError as exc:
        raise RiskPolicyError(f"diff SHA 非法：{exc}") from exc
    paths = extract_diff_paths(repo_root, str(base), str(head))
    return DiffRiskAssessment(
        base_sha=str(base),
        head_sha=str(head),
        assessment=classify_paths(paths, policy=policy),
    )


def evaluate_high_risk_approval(
    *,
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    pr_number: int,
    desk_folder: Path,
    approvals: SignedApprovals | None = None,
    generation: int = 1,
    now: datetime | None = None,
) -> HighRiskApprovalResult:
    """在准入边界直接按宿主受信策略重算真实 git diff 风险，并复用 ApprovalDesk 与 CommitTarget 评估签批状态。"""
    if type(pr_number) is not int or pr_number <= 0:
        raise RiskPolicyError(f"pr_number 必须为正整数：{pr_number!r}")
    if type(generation) is not int or generation <= 0:
        raise RiskPolicyError(f"generation 必须为正整数：{generation!r}")

    trusted_policy = load_policy(DEFAULT_POLICY_PATH)
    diff_assessment = assess_diff(repo_root, base_sha, head_sha, policy=trusted_policy)
    assessment = diff_assessment.assessment

    if not assessment.requires_human_approval:
        return HighRiskApprovalResult(
            required=False,
            satisfied=True,
            status="not_required",
            reason=f"风险分档为 {assessment.tier.value}（{assessment.review_depth.value}），免人工签批",
            base_sha=diff_assessment.base_sha,
            head_sha=diff_assessment.head_sha,
            assessment=assessment,
            request_path=None,
            sign_command=None,
        )

    desk = ApprovalDesk(
        folder=desk_folder,
        ticket=pr_number,
        run_id=f"pr-{pr_number}-high-risk",
        approvals=approvals or SignedApprovals(),
    )
    decision = desk.check(
        Scope.CANDIDATE_HEAD,
        generation,
        CommitTarget(diff_assessment.head_sha),
        now=now,
    )
    if isinstance(decision, Approved):
        return HighRiskApprovalResult(
            required=True,
            satisfied=True,
            status="approved",
            reason=decision.reason,
            base_sha=diff_assessment.base_sha,
            head_sha=diff_assessment.head_sha,
            assessment=assessment,
            request_path=decision.request_path,
            sign_command=None,
        )

    return HighRiskApprovalResult(
        required=True,
        satisfied=False,
        status=decision.status,
        reason=decision.reason,
        base_sha=diff_assessment.base_sha,
        head_sha=diff_assessment.head_sha,
        assessment=assessment,
        request_path=decision.request_path,
        sign_command=f"{SIGN_COMMAND} {shlex.quote(decision.request_path)}",
    )
