"""代码审查回滚/事故评测集打分与外部审查运行基线统计（#1931）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "review-eval/1"
CaseKind = Literal["bug", "clean"]
FindingSeverity = Literal["blocking", "important", "nit", "pre_existing", "info"]
ReviewVerdict = Literal["PASS", "BLOCK", "FAILED"]
CaseScoreVerdict = Literal["PASS", "BLOCK", "FAILED", "MISSING"]

_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"blocking", "important"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"blocking", "important", "nit", "pre_existing", "info"})
_VALID_VERDICTS: frozenset[str] = frozenset({"PASS", "BLOCK", "FAILED"})
_VALID_SCORE_VERDICTS: frozenset[str] = frozenset({"PASS", "BLOCK", "FAILED", "MISSING"})
_UNDECIDED_SCORE_VERDICTS: frozenset[str] = frozenset({"FAILED", "MISSING"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# 启发式正则：仅用于对历史纯文本 findings 做粗粒度归类，非人工标注真值。
_STYLE_FORMAT_RE = re.compile(
    r"(?:rustfmt|cargo\s+fmt|prettier|eslint|ruff|flake8|black|"
    r"import\s*(?:排序|顺序|分组|order)|"
    r"格式(?:化|问题|对齐)?|缩进|尾随空格|多余空行|拼写错误|typo|"
    r"style\s*(?:only|issue|nit)|formatting|whitespace)",
    re.IGNORECASE,
)
_LEADING_LIST_PREFIX_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
_LEADING_BRACKET_TAG_RE = re.compile(r"^(?:(?:\*\*|__)\s*)?[\[\【]([^\]\】]{1,64})[\]\】](?:\s*(?:\*\*|__))?\s*")
_LEADING_COLON_TAG_RE = re.compile(r"^(?:(?:\*\*|__)\s*)?([^:\n：\[\【\]\】`*]{1,24}?)(?:\s*(?:\*\*|__))?\s*[:：]")
_TAG_SPLIT_RE = re.compile(r"[\s/·,，、\-—:：|]+")
_TAG_NON_BLOCKING_RE = re.compile(
    r"(?:非阻断|不阻断|(?<![A-Za-z0-9])non[- ]?blocking(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])nit(?![A-Za-z0-9])|(?<![A-Za-z0-9])minor(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])low(?![A-Za-z0-9])|(?<![A-Za-z0-9])info(?![A-Za-z0-9])|"
    r"信息|提示|(?<!不是)(?<!并非)(?<!非)建议|(?<!不是)(?<!并非)(?<!非)可选|"
    r"(?<![A-Za-z0-9])p3(?![A-Za-z0-9])|"
    r"已核.*(?:无问题|未发现问题)|核实通过|确认无(?:问题|误)|通过)",
    re.IGNORECASE,
)
_TAG_BLOCKING_RE = re.compile(
    r"(?:阻断|(?<![A-Za-z0-9])block(?:er|ing)?(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])important(?![A-Za-z0-9])|(?<![A-Za-z0-9])critical(?![A-Za-z0-9])|"
    r"(?<![A-Za-z0-9])must[- ]?fix(?![A-Za-z0-9])|严重|重要|"
    r"(?<![A-Za-z0-9])p[01](?![A-Za-z0-9]))",
    re.IGNORECASE,
)
_NON_BLOCKING_NIT_RE = re.compile(
    r"(?:[\[\【]\s*nit\s*[\]\】]|(?<![A-Za-z0-9])nit\s*[:：]|非阻断|不阻断|"
    r"(?<![A-Za-z0-9])non[- ]?blocking(?![A-Za-z0-9])|"
    r"(?<!不是)(?<!并非)(?<!非)建议后续|"
    r"(?<!不是)(?<!并非)(?<!非)(?<!不是建议)(?<!并非建议)(?<!非建议)(?<!不是可选)(?<!并非可选)(?<!非可选)后续跟进|"
    r"(?<!不是)(?<!并非)(?<!非)可选(?:建议|优化)?|"
    r"顺手|(?<![A-Za-z0-9])minor(?![A-Za-z0-9])|仅作记录|低优先级)",
    re.IGNORECASE,
)
_BLOCKING_MARKER_RE = re.compile(
    r"(?:[\[\【]\s*p[012]\s*[\]\】]|(?<![A-Za-z0-9])p[012]\s*[:：]|阻断|必须修复|"
    r"(?<![A-Za-z0-9])blocking(?![A-Za-z0-9])|(?<![A-Za-z0-9])critical(?![A-Za-z0-9])|"
    r"high\s+severity)",
    re.IGNORECASE,
)


class EvalValidationError(ValueError):
    """评测集或输入数据校验失败。"""


class DispositionLabel(str, Enum):
    """人工或流程回填的审查发现去向分类（对照 Anthropic 噪声度量口径）。"""

    FIXED = "fixed"
    FALSE_POSITIVE = "false_positive"
    INTENTIONAL = "intentional"
    NOT_IMPORTANT = "not_important"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class BugLocation:
    """真实事故/回滚案例在 head_sha 中的缺陷位置。"""

    file: str
    line_start: int
    line_end: int
    summary: str
    category: str
    extra_ranges: tuple[tuple[int, int], ...] = ()

    @property
    def all_ranges(self) -> tuple[tuple[int, int], ...]:
        return ((self.line_start, self.line_end), *self.extra_ranges)


@dataclass(frozen=True)
class EvalCase:
    """单条评测案例（bug 案或 clean 案）。"""

    case_id: str
    kind: CaseKind
    title: str
    base_sha: str
    head_sha: str
    fix_sha: str | None = None
    pr_number: int | None = None
    issue_number: int | None = None
    bug_locations: tuple[BugLocation, ...] = ()
    source_note: str = ""


@dataclass(frozen=True)
class PredictedFinding:
    """待评测审查器输出的单条发现。"""

    file: str
    line_start: int | None = None
    line_end: int | None = None
    severity: FindingSeverity = "blocking"
    summary: str = ""

    @property
    def is_blocking(self) -> bool:
        return self.severity in _BLOCKING_SEVERITIES


@dataclass(frozen=True)
class CasePrediction:
    """待评测审查器对单条案例的整体输出。"""

    case_id: str
    verdict: ReviewVerdict
    findings: tuple[PredictedFinding, ...] = ()


@dataclass(frozen=True)
class CaseScoreDetail:
    """单条案例的打分明细。"""

    case_id: str
    kind: CaseKind
    verdict: CaseScoreVerdict
    expected_locations: int
    matched_locations: int
    matched_location_indices: tuple[int, ...]
    blocking_findings: int
    matched_blocking_findings: int
    bug_recalled: bool
    clean_false_positive: bool


@dataclass(frozen=True)
class EvalScore:
    """评测集整体打分结果。"""

    total_cases: int
    evaluated_cases: int
    failed_cases: int
    missing_cases: int
    coverage_rate: float
    bug_cases: int
    clean_cases: int
    decided_clean_cases: int
    recalled_bug_cases: int
    total_bug_locations: int
    matched_bug_locations: int
    clean_false_positive_cases: int
    total_blocking_findings: int
    matched_blocking_findings: int
    bug_case_recall: float
    bug_location_recall: float
    clean_false_positive_rate: float | None
    blocking_precision: float
    f1: float
    line_tolerance: int
    max_finding_span: int
    cases_fingerprint: str
    case_details: tuple[CaseScoreDetail, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreComparison:
    """两次评测打分的增量与逐案变化。"""

    bug_case_recall_delta: float
    bug_location_recall_delta: float
    clean_false_positive_rate_delta: float | None
    blocking_precision_delta: float
    f1_delta: float
    coverage_rate_delta: float
    improved_cases: tuple[str, ...]
    regressed_cases: tuple[str, ...]
    mixed_cases: tuple[str, ...]
    unchanged_cases: tuple[str, ...]
    undecided_cases: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DispositionEntry:
    """单条审查发现的显式去向台账记录。"""

    run_id: str
    pr_number: int
    model: str
    finding_index: int
    disposition: DispositionLabel
    note: str = ""


@dataclass(frozen=True)
class RoundDistribution:
    """每 PR 达到首次 PASS 的轮次分布。"""

    prs_counted: int
    bucket_1: int
    bucket_2: int
    bucket_3: int
    bucket_4_plus: int
    median: float | None
    mean: float | None
    max_rounds: int | None


@dataclass(frozen=True)
class BaselineMetrics:
    """外部正式审查历史运行的基线统计汇总。"""

    runs_dir: str
    total_runs: int
    missing_outcome_runs: int
    reused_runs: int
    fresh_pass_runs: int
    unorderable_runs: int
    corrupted_files: tuple[str, ...]
    verdict_counts: dict[str, int]
    block_rate_all: float
    block_rate_decided_including_reuse: float
    block_rate_fresh_decided: float
    unique_prs: int
    prs_with_pass: int
    prs_without_pass: int
    prs_first_pass_reused: int
    rounds_to_first_pass_all: RoundDistribution
    rounds_to_first_pass_effective: RoundDistribution
    model_verdict_counts: dict[str, dict[str, int]]
    model_pair_agreement: dict[str, dict[str, int]]
    total_receipts: int
    completed_receipts: int
    failed_receipts: int
    total_findings: int
    findings_by_receipt_status: dict[str, int]
    findings_by_model: dict[str, int]
    finding_heuristic_categories: dict[str, int]
    style_or_format_findings: int
    nit_style_or_format_findings: int
    subsequent_head_pass_inferred_fixed: int
    subsequent_head_pass_total_block_findings: int
    subsequent_head_pass_undeterminable_findings: int
    subsequent_head_pass_inferred_rate: float
    disposition_total: int
    disposition_coverage_rate: float
    disposition_counts: dict[str, int]
    disposition_resolved_rates: dict[str, float]

    @property
    def block_rate_decided(self) -> float:
        return self.block_rate_decided_including_reuse

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def _require_nonempty_str(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise EvalValidationError(f"字段 {field} 必须是非空字符串")
    return raw.strip()


def _require_optional_int(raw: Any, field: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EvalValidationError(f"字段 {field} 必须是整数或 null")
    return raw


def _require_int(raw: Any, field: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise EvalValidationError(f"字段 {field} 必须是整数")
    return raw


def _require_sha(raw: Any, field: str) -> str:
    if not isinstance(raw, str) or not _SHA_RE.fullmatch(raw):
        raise EvalValidationError(f"字段 {field} 必须是 40 位小写 Git SHA：{raw!r}")
    return raw


def _merge_line_ranges(ranges: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """将闭区间按升序排序并合并重叠或相邻区间。"""
    if not ranges:
        return ()
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = [ordered[0]]
    for r_start, r_end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if r_start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, r_end))
        else:
            merged.append((r_start, r_end))
    return tuple(merged)


def _validate_bug_location_ranges(all_ranges: Sequence[tuple[int, int]], prefix: str) -> None:
    """校验 BugLocation 的全部区间满足 1 <= start <= end 且严格升序、互不重叠、无重复、无相邻未合并段。"""
    if not all_ranges:
        raise EvalValidationError(f"{prefix} 至少需要一个行号区间")
    prev_end: int | None = None
    for idx, (r_start, r_end) in enumerate(all_ranges):
        if isinstance(r_start, bool) or not isinstance(r_start, int) or isinstance(r_end, bool) or not isinstance(r_end, int):
            raise EvalValidationError(f"{prefix} 行号区间必须是整数：{r_start!r}..{r_end!r}")
        if r_start < 1 or r_end < r_start:
            raise EvalValidationError(f"{prefix} 行号区间非法：{r_start}..{r_end}")
        if prev_end is not None and r_start <= prev_end + 1:
            raise EvalValidationError(
                f"{prefix} 的行号区间必须严格升序且无重叠、无重复、无相邻未合并段："
                f"第 {idx} 段 {r_start}..{r_end} 与前一段末尾 {prev_end} 冲突"
            )
        prev_end = r_end


def _parse_bug_location(raw: Any, prefix: str) -> BugLocation:
    if not isinstance(raw, dict):
        raise EvalValidationError(f"{prefix} 必须是 JSON 对象")
    file_path = _norm_path(_require_nonempty_str(raw.get("file"), f"{prefix}.file"))
    line_start = _require_int(raw.get("line_start"), f"{prefix}.line_start")
    line_end = _require_int(raw.get("line_end"), f"{prefix}.line_end")
    if line_start < 1 or line_end < line_start:
        raise EvalValidationError(f"{prefix} 行号区间非法：{line_start}..{line_end}")
    raw_extra = raw.get("extra_ranges", [])
    if not isinstance(raw_extra, list):
        raise EvalValidationError(f"{prefix}.extra_ranges 必须是数组")
    extra_ranges: list[tuple[int, int]] = []
    for r_idx, rng in enumerate(raw_extra):
        r_prefix = f"{prefix}.extra_ranges[{r_idx}]"
        if not isinstance(rng, list) or len(rng) != 2:
            raise EvalValidationError(f"{r_prefix} 必须是长度为 2 的整数数组")
        r_start = _require_int(rng[0], f"{r_prefix}[0]")
        r_end = _require_int(rng[1], f"{r_prefix}[1]")
        if r_start < 1 or r_end < r_start:
            raise EvalValidationError(f"{r_prefix} 行号区间非法：{r_start}..{r_end}")
        extra_ranges.append((r_start, r_end))
    _validate_bug_location_ranges(((line_start, line_end), *extra_ranges), prefix)
    summary = _require_nonempty_str(raw.get("summary"), f"{prefix}.summary")
    category = _require_nonempty_str(raw.get("category"), f"{prefix}.category")
    return BugLocation(
        file=file_path,
        line_start=line_start,
        line_end=line_end,
        summary=summary,
        category=category,
        extra_ranges=tuple(extra_ranges),
    )


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    """读取并做 schema 级校验，返回评测案例元组。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalValidationError(f"无法解析评测集文件 {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise EvalValidationError("评测集根节点必须是 JSON 对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise EvalValidationError(
            f"schema_version 不匹配：期望 {SCHEMA_VERSION!r}，实际 {payload.get('schema_version')!r}"
        )

    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalValidationError("cases 必须是非空数组")

    parsed: list[EvalCase] = []
    for idx, item in enumerate(raw_cases):
        prefix = f"cases[{idx}]"
        if not isinstance(item, dict):
            raise EvalValidationError(f"{prefix} 必须是 JSON 对象")
        case_id = _require_nonempty_str(item.get("case_id"), f"{prefix}.case_id")
        kind_raw = _require_nonempty_str(item.get("kind"), f"{prefix}.kind")
        if kind_raw not in ("bug", "clean"):
            raise EvalValidationError(f"{prefix}.kind 必须是 'bug' 或 'clean'，实际 {kind_raw!r}")
        kind: CaseKind = "bug" if kind_raw == "bug" else "clean"
        title = _require_nonempty_str(item.get("title"), f"{prefix}.title")
        base_sha = _require_sha(item.get("base_sha"), f"{prefix}.base_sha")
        head_sha = _require_sha(item.get("head_sha"), f"{prefix}.head_sha")
        fix_raw = item.get("fix_sha")
        fix_sha = None if fix_raw is None else _require_sha(fix_raw, f"{prefix}.fix_sha")
        pr_number = _require_optional_int(item.get("pr_number"), f"{prefix}.pr_number")
        issue_number = _require_optional_int(item.get("issue_number"), f"{prefix}.issue_number")
        source_note_raw = item.get("source_note", "")
        if not isinstance(source_note_raw, str):
            raise EvalValidationError(f"{prefix}.source_note 必须是字符串")
        raw_locs = item.get("bug_locations")
        if not isinstance(raw_locs, list):
            raise EvalValidationError(f"{prefix}.bug_locations 必须是数组")
        locs = tuple(
            _parse_bug_location(loc, f"{prefix}.bug_locations[{loc_idx}]")
            for loc_idx, loc in enumerate(raw_locs)
        )
        parsed.append(
            EvalCase(
                case_id=case_id,
                kind=kind,
                title=title,
                base_sha=base_sha,
                head_sha=head_sha,
                fix_sha=fix_sha,
                pr_number=pr_number,
                issue_number=issue_number,
                bug_locations=locs,
                source_note=source_note_raw,
            )
        )

    cases = tuple(parsed)
    validate_cases(cases)
    return cases


def _git_cat_file_exists(repo_root: Path, obj_spec: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", obj_spec],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _git_blob_line_count(repo_root: Path, obj_spec: str) -> int:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-p", obj_spec],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise EvalValidationError(f"无法读取 Git 对象内容：{obj_spec}")
    return len(proc.stdout.splitlines())


def _parse_unified_diff_added_ranges(diff_text: str) -> tuple[tuple[int, int], ...]:
    """逐行扫描 unified diff 正文，仅收集真实 `+` 新增/修改行号并合并为连续闭区间。"""
    added_lines: list[int] = []
    curr_line: int | None = None
    remaining_old = 0
    remaining_new = 0
    for line in diff_text.splitlines():
        match = _DIFF_HUNK_RE.match(line)
        if match:
            remaining_old = int(match.group(2)) if match.group(2) is not None else 1
            curr_line = int(match.group(3))
            remaining_new = int(match.group(4)) if match.group(4) is not None else 1
            continue
        if curr_line is None or (remaining_old == 0 and remaining_new == 0):
            continue
        if line.startswith("\\"):
            continue
        if line.startswith("+") and remaining_new > 0:
            added_lines.append(curr_line)
            curr_line += 1
            remaining_new -= 1
        elif line.startswith(" ") and remaining_old > 0 and remaining_new > 0:
            curr_line += 1
            remaining_old -= 1
            remaining_new -= 1
        elif line.startswith("-") and remaining_old > 0:
            remaining_old -= 1
        else:
            curr_line = None
            remaining_old = 0
            remaining_new = 0
    return _merge_line_ranges([(ln, ln) for ln in added_lines])


def _git_diff_added_ranges(
    repo_root: Path,
    base_sha: str,
    head_sha: str,
    file_path: str,
) -> tuple[tuple[int, int], ...]:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "-c",
            "diff.interHunkContext=0",
            "diff",
            "-U0",
            "--inter-hunk-context=0",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            base_sha,
            head_sha,
            "--",
            file_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise EvalValidationError(f"无法读取 Git diff（{base_sha}..{head_sha} -- {file_path}）：{proc.stderr.strip()}")
    return _parse_unified_diff_added_ranges(proc.stdout)


def compute_cases_fingerprint(cases: Sequence[EvalCase]) -> str:
    """按规范排序后的案例元数据与合并规范化后的缺陷位置计算评测集 sha256 指纹。"""
    canonical = []
    for c in sorted(cases, key=lambda item: item.case_id):
        locs_payload = []
        for loc in c.bug_locations:
            norm_ranges = _merge_line_ranges(loc.all_ranges)
            locs_payload.append(
                {
                    "file": _norm_path(loc.file),
                    "line_start": norm_ranges[0][0],
                    "line_end": norm_ranges[0][1],
                    "extra_ranges": [[r_start, r_end] for r_start, r_end in norm_ranges[1:]],
                }
            )
        canonical.append(
            {
                "case_id": c.case_id,
                "kind": c.kind,
                "base_sha": c.base_sha,
                "head_sha": c.head_sha,
                "bug_locations": locs_payload,
            }
        )
    encoded = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_cases(cases: Sequence[EvalCase], repo_root: Path | None = None) -> None:
    """校验评测集不变式；提供 repo_root 时同时核验 Git 提交、文件行号界限与 diff hunk 逐行覆盖。"""
    if not cases:
        raise EvalValidationError("评测集不能为空")

    seen_ids: set[str] = set()
    line_count_cache: dict[tuple[str, str], int] = {}
    diff_hunk_cache: dict[tuple[str, str, str], tuple[tuple[int, int], ...]] = {}

    for case in cases:
        if not case.case_id.strip():
            raise EvalValidationError("存在空 case_id")
        if case.case_id in seen_ids:
            raise EvalValidationError(f"重复的 case_id：{case.case_id}")
        seen_ids.add(case.case_id)

        if not _SHA_RE.fullmatch(case.base_sha) or not _SHA_RE.fullmatch(case.head_sha):
            raise EvalValidationError(f"{case.case_id} 包含非法 40 位小写 SHA")
        if case.fix_sha is not None and not _SHA_RE.fullmatch(case.fix_sha):
            raise EvalValidationError(f"{case.case_id} 包含非法 40 位小写 fix_sha：{case.fix_sha!r}")
        if case.base_sha == case.head_sha:
            raise EvalValidationError(f"{case.case_id} 的 base_sha 与 head_sha 相同")

        if case.kind == "bug":
            if not case.bug_locations:
                raise EvalValidationError(f"bug 案 {case.case_id} 的 bug_locations 不能为空")
            for loc in case.bug_locations:
                if not _norm_path(loc.file):
                    raise EvalValidationError(f"{case.case_id} 存在空文件路径")
                _validate_bug_location_ranges(loc.all_ranges, f"{case.case_id} 的 {loc.file}")
        elif case.kind == "clean":
            if case.bug_locations:
                raise EvalValidationError(f"clean 案 {case.case_id} 的 bug_locations 必须为空")
        else:
            raise EvalValidationError(f"{case.case_id} 存在未知 kind：{case.kind!r}")

        if repo_root is not None:
            for label, sha in (("base_sha", case.base_sha), ("head_sha", case.head_sha)):
                if not _git_cat_file_exists(repo_root, f"{sha}^{{commit}}"):
                    raise EvalValidationError(f"{case.case_id} 的 {label}={sha} 在仓库中不存在")
            if case.fix_sha is not None and not _git_cat_file_exists(repo_root, f"{case.fix_sha}^{{commit}}"):
                raise EvalValidationError(f"{case.case_id} 的 fix_sha={case.fix_sha} 在仓库中不存在")
            for loc in case.bug_locations:
                norm_file = _norm_path(loc.file)
                obj_spec = f"{case.head_sha}:{norm_file}"
                if not _git_cat_file_exists(repo_root, obj_spec):
                    raise EvalValidationError(
                        f"{case.case_id} 的 bug_location 文件在 {case.head_sha} 中不存在：{norm_file}"
                    )
                cache_key = (case.head_sha, norm_file)
                if cache_key not in line_count_cache:
                    line_count_cache[cache_key] = _git_blob_line_count(repo_root, obj_spec)
                total_lines = line_count_cache[cache_key]
                diff_key = (case.base_sha, case.head_sha, norm_file)
                if diff_key not in diff_hunk_cache:
                    diff_hunk_cache[diff_key] = _merge_line_ranges(
                        _git_diff_added_ranges(repo_root, case.base_sha, case.head_sha, norm_file)
                    )
                merged_added_ranges = diff_hunk_cache[diff_key]
                for r_start, r_end in loc.all_ranges:
                    if r_end > total_lines:
                        raise EvalValidationError(
                            f"{case.case_id} 的 {norm_file} 行号越界：{r_end} > {total_lines}"
                        )
                    if not any(
                        h_start <= r_start and r_end <= h_end for h_start, h_end in merged_added_ranges
                    ):
                        hunks_desc = (
                            ", ".join(f"{h_start}..{h_end}" for h_start, h_end in merged_added_ranges) or "无"
                        )
                        raise EvalValidationError(
                            f"{case.case_id} 的 {norm_file}:{r_start}..{r_end} "
                            f"未完全落在 {case.base_sha[:10]}..{case.head_sha[:10]} 的新增/修改 diff hunk 内"
                            f"（可用 hunk：{hunks_desc}）"
                        )


def load_predictions(path: Path) -> tuple[CasePrediction, ...]:
    """读取待评测审查器的预测 JSON（支持数组或 {"predictions": [...]}）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalValidationError(f"无法解析预测文件 {path}: {exc}") from exc

    raw_items = payload.get("predictions") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise EvalValidationError("预测文件必须是数组或含 predictions 数组的对象")

    predictions: list[CasePrediction] = []
    for idx, item in enumerate(raw_items):
        prefix = f"predictions[{idx}]"
        if not isinstance(item, dict):
            raise EvalValidationError(f"{prefix} 必须是 JSON 对象")
        case_id = _require_nonempty_str(item.get("case_id"), f"{prefix}.case_id")
        verdict_raw = _require_nonempty_str(item.get("verdict"), f"{prefix}.verdict").upper()
        if verdict_raw not in _VALID_VERDICTS:
            raise EvalValidationError(f"{prefix}.verdict 非法：{verdict_raw!r}")
        verdict: ReviewVerdict = "PASS" if verdict_raw == "PASS" else ("BLOCK" if verdict_raw == "BLOCK" else "FAILED")
        raw_findings = item.get("findings", [])
        if not isinstance(raw_findings, list):
            raise EvalValidationError(f"{prefix}.findings 必须是数组")
        findings: list[PredictedFinding] = []
        for f_idx, rf in enumerate(raw_findings):
            f_prefix = f"{prefix}.findings[{f_idx}]"
            if not isinstance(rf, dict):
                raise EvalValidationError(f"{f_prefix} 必须是 JSON 对象")
            file_path = _norm_path(_require_nonempty_str(rf.get("file"), f"{f_prefix}.file"))
            line_start = _require_optional_int(rf.get("line_start"), f"{f_prefix}.line_start")
            line_end = _require_optional_int(rf.get("line_end"), f"{f_prefix}.line_end")
            if line_start is not None and line_start < 1:
                raise EvalValidationError(f"{f_prefix}.line_start 必须 >= 1")
            if line_end is not None:
                if line_start is None:
                    raise EvalValidationError(f"{f_prefix} 指定了 line_end 但缺少 line_start")
                if line_end < line_start:
                    raise EvalValidationError(f"{f_prefix} 行号区间非法：{line_start}..{line_end}")
            sev_raw = str(rf.get("severity", "blocking")).strip().lower()
            if sev_raw not in _VALID_SEVERITIES:
                raise EvalValidationError(f"{f_prefix}.severity 非法：{sev_raw!r}")
            severity: FindingSeverity = (
                "blocking"
                if sev_raw == "blocking"
                else "important"
                if sev_raw == "important"
                else "nit"
                if sev_raw == "nit"
                else "pre_existing"
                if sev_raw == "pre_existing"
                else "info"
            )
            summary = str(rf.get("summary", ""))
            findings.append(
                PredictedFinding(
                    file=file_path,
                    line_start=line_start,
                    line_end=line_end,
                    severity=severity,
                    summary=summary,
                )
            )
        predictions.append(CasePrediction(case_id=case_id, verdict=verdict, findings=tuple(findings)))

    return tuple(predictions)


def _finding_coord_key(finding: PredictedFinding) -> tuple[str, int | None, int | None]:
    norm_file = _norm_path(finding.file)
    if finding.line_start is None:
        return (norm_file, None, None)
    eff_end = finding.line_end if finding.line_end is not None else finding.line_start
    return (norm_file, finding.line_start, eff_end)


def _finding_matches_location(
    loc: BugLocation,
    finding: PredictedFinding,
    *,
    line_tolerance: int,
    max_finding_span: int,
) -> bool:
    if not finding.is_blocking or finding.line_start is None:
        return False
    f_start = finding.line_start
    f_end = finding.line_end if finding.line_end is not None else finding.line_start
    if f_end - f_start + 1 > max_finding_span:
        return False
    if _norm_path(loc.file) != _norm_path(finding.file):
        return False
    return any(
        f_start <= r_end + line_tolerance and f_end >= max(1, r_start - line_tolerance)
        for r_start, r_end in loc.all_ranges
    )


def _match_findings_to_locations(
    locations: Sequence[BugLocation],
    blocking_findings: Sequence[PredictedFinding],
    *,
    line_tolerance: int,
    max_finding_span: int,
) -> tuple[int, ...]:
    """在阻断发现与真实缺陷位置之间求一对一最大二分图匹配，返回命中的 location 索引元组。"""
    adj: list[list[int]] = [
        [
            loc_idx
            for loc_idx, loc in enumerate(locations)
            if _finding_matches_location(
                loc,
                finding,
                line_tolerance=line_tolerance,
                max_finding_span=max_finding_span,
            )
        ]
        for finding in blocking_findings
    ]
    loc_match: dict[int, int] = {}

    def _try_augment(f_idx: int, visited: set[int]) -> bool:
        for loc_idx in adj[f_idx]:
            if loc_idx in visited:
                continue
            visited.add(loc_idx)
            if loc_idx not in loc_match or _try_augment(loc_match[loc_idx], visited):
                loc_match[loc_idx] = f_idx
                return True
        return False

    for f_idx in range(len(blocking_findings)):
        _try_augment(f_idx, set())

    return tuple(sorted(loc_match.keys()))


def score_predictions(
    cases: Sequence[EvalCase],
    predictions: Sequence[CasePrediction],
    *,
    line_tolerance: int = 15,
    max_finding_span: int = 120,
    allow_partial: bool = False,
) -> EvalScore:
    """按位置容差与一对一最大匹配对审查预测结果打分。

    口径：
    - 默认严格要求 predictions 覆盖 cases 的全部 case_id；仅在显式 allow_partial=True 时记为 MISSING 并暴露 coverage_rate。
    - evaluated_cases 仅计实际产生裁定（PASS / BLOCK）的案例数；FAILED 计入 failed_cases、MISSING 计入 missing_cases，两者均计入未裁定覆盖缺口（coverage_rate = evaluated_cases / total_cases）。
    - bug_case_recall：真实 bug 案被判 BLOCK 且至少一条阻断/Important 发现命中真实 bug_location 的比例。
    - bug_location_recall：所有真实 bug_location 中经规范坐标去重后一对一最大匹配命中的比例（闭区间跨度超过 max_finding_span 的宽区间发现不计命中）。
    - clean_false_positive_rate：已实际裁定（PASS / BLOCK）的真实 clean 案中只要 verdict == BLOCK 一律计为误报（FAILED / MISSING 不充当零误报分母）；当已裁定 clean 案数 decided_clean_cases == 0 时返回 None（不可计算）。
    - blocking_precision：所有阻断/Important 发现（含重复副本）中经去重一对一匹配计为真阳性的比例（重复发现惩罚精确率且不领取额外位置召回）。
    - f1：blocking_precision 与 bug_location_recall 的调和平均。
    """
    if line_tolerance < 0:
        raise EvalValidationError(f"line_tolerance 不能为负：{line_tolerance}")
    if max_finding_span < 0:
        raise EvalValidationError(f"max_finding_span 不能为负：{max_finding_span}")
    validate_cases(cases)

    case_ids = {c.case_id for c in cases}
    pred_map: dict[str, CasePrediction] = {}
    for pred in predictions:
        if pred.case_id in pred_map:
            raise EvalValidationError(f"预测中存在重复 case_id：{pred.case_id}")
        if pred.case_id not in case_ids:
            raise EvalValidationError(f"预测中存在未知 case_id：{pred.case_id}")
        if pred.verdict not in _VALID_VERDICTS:
            raise EvalValidationError(f"预测中存在非法 verdict：{pred.verdict!r}")
        pred_map[pred.case_id] = pred

    missing_ids = [c.case_id for c in cases if c.case_id not in pred_map]
    if missing_ids and not allow_partial:
        raise EvalValidationError(
            f"预测缺少案例（默认拒绝缺漏，如需部分评测请显式传 allow_partial=True）：{', '.join(missing_ids)}"
        )

    bug_cases = 0
    clean_cases = 0
    evaluated_cases = 0
    failed_cases = 0
    decided_clean_cases = 0
    missing_cases = 0
    recalled_bug_cases = 0
    total_bug_locations = 0
    matched_bug_locations = 0
    clean_false_positive_cases = 0
    total_blocking_findings = 0
    matched_blocking_findings = 0
    details: list[CaseScoreDetail] = []

    for case in cases:
        case_pred = pred_map.get(case.case_id)
        if case_pred is None:
            missing_cases += 1
            if case.kind == "bug":
                bug_cases += 1
                total_bug_locations += len(case.bug_locations)
            else:
                clean_cases += 1
            details.append(
                CaseScoreDetail(
                    case_id=case.case_id,
                    kind=case.kind,
                    verdict="MISSING",
                    expected_locations=len(case.bug_locations),
                    matched_locations=0,
                    matched_location_indices=(),
                    blocking_findings=0,
                    matched_blocking_findings=0,
                    bug_recalled=False,
                    clean_false_positive=False,
                )
            )
            continue

        if case_pred.verdict == "FAILED":
            failed_cases += 1
        else:
            evaluated_cases += 1

        blocking_findings = [f for f in case_pred.findings if f.is_blocking]
        total_blocking_findings += len(blocking_findings)

        if case.kind == "bug":
            bug_cases += 1
            total_bug_locations += len(case.bug_locations)
            matched_indices: tuple[int, ...] = ()
            if case_pred.verdict == "BLOCK":
                dedup_blocking_findings: list[PredictedFinding] = []
                seen_coords: set[tuple[str, int | None, int | None]] = set()
                for finding in blocking_findings:
                    coord_key = _finding_coord_key(finding)
                    if coord_key in seen_coords:
                        continue
                    seen_coords.add(coord_key)
                    dedup_blocking_findings.append(finding)
                matched_indices = _match_findings_to_locations(
                    case.bug_locations,
                    dedup_blocking_findings,
                    line_tolerance=line_tolerance,
                    max_finding_span=max_finding_span,
                )

            case_matched_blocking = len(matched_indices)
            matched_bug_locations += len(matched_indices)
            matched_blocking_findings += case_matched_blocking
            recalled = case_pred.verdict == "BLOCK" and len(matched_indices) > 0
            if recalled:
                recalled_bug_cases += 1

            details.append(
                CaseScoreDetail(
                    case_id=case.case_id,
                    kind=case.kind,
                    verdict=case_pred.verdict,
                    expected_locations=len(case.bug_locations),
                    matched_locations=len(matched_indices),
                    matched_location_indices=matched_indices,
                    blocking_findings=len(blocking_findings),
                    matched_blocking_findings=case_matched_blocking,
                    bug_recalled=recalled,
                    clean_false_positive=False,
                )
            )
        else:
            clean_cases += 1
            if case_pred.verdict in ("PASS", "BLOCK"):
                decided_clean_cases += 1
            # 干净 PR 只要终态为 BLOCK 一律计为误报（无论 findings 为空、仅含 nit 或含 important/blocking）。
            is_fp = case_pred.verdict == "BLOCK"
            if is_fp:
                clean_false_positive_cases += 1
            details.append(
                CaseScoreDetail(
                    case_id=case.case_id,
                    kind=case.kind,
                    verdict=case_pred.verdict,
                    expected_locations=0,
                    matched_locations=0,
                    matched_location_indices=(),
                    blocking_findings=len(blocking_findings),
                    matched_blocking_findings=0,
                    bug_recalled=False,
                    clean_false_positive=is_fp,
                )
            )

    coverage_rate = evaluated_cases / len(cases) if cases else 0.0
    bug_case_recall = recalled_bug_cases / bug_cases if bug_cases else 0.0
    bug_location_recall = matched_bug_locations / total_bug_locations if total_bug_locations else 0.0
    clean_false_positive_rate: float | None = (
        round(clean_false_positive_cases / decided_clean_cases, 6) if decided_clean_cases > 0 else None
    )
    blocking_precision = matched_blocking_findings / total_blocking_findings if total_blocking_findings else 0.0
    f1 = (
        2.0 * blocking_precision * bug_location_recall / (blocking_precision + bug_location_recall)
        if (blocking_precision + bug_location_recall) > 0.0
        else 0.0
    )

    return EvalScore(
        total_cases=len(cases),
        evaluated_cases=evaluated_cases,
        failed_cases=failed_cases,
        missing_cases=missing_cases,
        coverage_rate=round(coverage_rate, 6),
        bug_cases=bug_cases,
        clean_cases=clean_cases,
        decided_clean_cases=decided_clean_cases,
        recalled_bug_cases=recalled_bug_cases,
        total_bug_locations=total_bug_locations,
        matched_bug_locations=matched_bug_locations,
        clean_false_positive_cases=clean_false_positive_cases,
        total_blocking_findings=total_blocking_findings,
        matched_blocking_findings=matched_blocking_findings,
        bug_case_recall=round(bug_case_recall, 6),
        bug_location_recall=round(bug_location_recall, 6),
        clean_false_positive_rate=clean_false_positive_rate,
        blocking_precision=round(blocking_precision, 6),
        f1=round(f1, 6),
        line_tolerance=line_tolerance,
        max_finding_span=max_finding_span,
        cases_fingerprint=compute_cases_fingerprint(cases),
        case_details=tuple(details),
    )


def _score_from_dict(raw: dict[str, Any]) -> EvalScore:
    try:
        raw_details = raw["case_details"]
        if not isinstance(raw_details, list):
            raise EvalValidationError("case_details 必须是数组")
        parsed_details: list[CaseScoreDetail] = []
        for d in raw_details:
            if not isinstance(d, dict):
                raise EvalValidationError("case_details 元素必须是对象")
            kind_raw = d["kind"]
            if kind_raw not in ("bug", "clean"):
                raise EvalValidationError(f"无效的 case kind：{kind_raw!r}")
            kind: CaseKind = "bug" if kind_raw == "bug" else "clean"
            verdict_raw = d["verdict"]
            if verdict_raw not in _VALID_SCORE_VERDICTS:
                raise EvalValidationError(f"无效的 case verdict：{verdict_raw!r}")
            verdict: CaseScoreVerdict = (
                "PASS"
                if verdict_raw == "PASS"
                else "BLOCK"
                if verdict_raw == "BLOCK"
                else "FAILED"
                if verdict_raw == "FAILED"
                else "MISSING"
            )
            parsed_details.append(
                CaseScoreDetail(
                    case_id=str(d["case_id"]),
                    kind=kind,
                    verdict=verdict,
                    expected_locations=int(d["expected_locations"]),
                    matched_locations=int(d["matched_locations"]),
                    matched_location_indices=tuple(int(i) for i in d["matched_location_indices"]),
                    blocking_findings=int(d["blocking_findings"]),
                    matched_blocking_findings=int(d["matched_blocking_findings"]),
                    bug_recalled=bool(d["bug_recalled"]),
                    clean_false_positive=bool(d["clean_false_positive"]),
                )
            )
        cases_fp = _require_nonempty_str(raw["cases_fingerprint"], "cases_fingerprint")
        decided_clean_cases = _require_int(raw["decided_clean_cases"], "decided_clean_cases")
        if decided_clean_cases < 0:
            raise EvalValidationError(f"decided_clean_cases 不能为负：{decided_clean_cases}")
        raw_clean_fp_rate = raw["clean_false_positive_rate"]
        if raw_clean_fp_rate is None:
            clean_false_positive_rate: float | None = None
        elif isinstance(raw_clean_fp_rate, bool) or not isinstance(raw_clean_fp_rate, (int, float)):
            raise EvalValidationError("clean_false_positive_rate 必须是数值或 null")
        else:
            clean_false_positive_rate = float(raw_clean_fp_rate)
        if decided_clean_cases == 0 and clean_false_positive_rate is not None:
            raise EvalValidationError("decided_clean_cases 为 0 时 clean_false_positive_rate 必须为 null")
        if decided_clean_cases > 0 and clean_false_positive_rate is None:
            raise EvalValidationError("decided_clean_cases 大于 0 时 clean_false_positive_rate 不能为 null")
        return EvalScore(
            total_cases=int(raw["total_cases"]),
            evaluated_cases=int(raw["evaluated_cases"]),
            failed_cases=int(raw["failed_cases"]),
            missing_cases=int(raw["missing_cases"]),
            coverage_rate=float(raw["coverage_rate"]),
            bug_cases=int(raw["bug_cases"]),
            clean_cases=int(raw["clean_cases"]),
            decided_clean_cases=decided_clean_cases,
            recalled_bug_cases=int(raw["recalled_bug_cases"]),
            total_bug_locations=int(raw["total_bug_locations"]),
            matched_bug_locations=int(raw["matched_bug_locations"]),
            clean_false_positive_cases=int(raw["clean_false_positive_cases"]),
            total_blocking_findings=int(raw["total_blocking_findings"]),
            matched_blocking_findings=int(raw["matched_blocking_findings"]),
            bug_case_recall=float(raw["bug_case_recall"]),
            bug_location_recall=float(raw["bug_location_recall"]),
            clean_false_positive_rate=clean_false_positive_rate,
            blocking_precision=float(raw["blocking_precision"]),
            f1=float(raw["f1"]),
            line_tolerance=int(raw["line_tolerance"]),
            max_finding_span=int(raw["max_finding_span"]),
            cases_fingerprint=cases_fp,
            case_details=tuple(parsed_details),
        )
    except EvalValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalValidationError(f"无效的 EvalScore JSON：{exc}") from exc


def compare_scores(before: EvalScore, after: EvalScore) -> ScoreComparison:
    """对比两次打分，先核验评测集与配置一致性，再产出指标增量与逐案改进/回归/混合列表。"""
    if not before.cases_fingerprint or not after.cases_fingerprint:
        raise EvalValidationError("对比打分缺少 cases_fingerprint，无法确认评测集一致")
    if before.cases_fingerprint != after.cases_fingerprint:
        raise EvalValidationError(
            f"评测集指纹不一致，拒绝跨评测集对比：{before.cases_fingerprint} != {after.cases_fingerprint}"
        )
    if before.line_tolerance != after.line_tolerance:
        raise EvalValidationError(
            f"line_tolerance 不一致，拒绝对比：{before.line_tolerance} != {after.line_tolerance}"
        )
    if before.max_finding_span != after.max_finding_span:
        raise EvalValidationError(
            f"max_finding_span 不一致，拒绝对比：{before.max_finding_span} != {after.max_finding_span}"
        )

    before_map: dict[str, CaseScoreDetail] = {}
    for d in before.case_details:
        if d.case_id in before_map:
            raise EvalValidationError(f"before 打分存在重复 case_id：{d.case_id}")
        before_map[d.case_id] = d

    after_map: dict[str, CaseScoreDetail] = {}
    for d in after.case_details:
        if d.case_id in after_map:
            raise EvalValidationError(f"after 打分存在重复 case_id：{d.case_id}")
        after_map[d.case_id] = d

    if set(before_map) != set(after_map):
        raise EvalValidationError(
            f"before 与 after 的 case_id 集合不一致：{sorted(before_map)} != {sorted(after_map)}"
        )

    for case_id in sorted(before_map):
        if before_map[case_id].kind != after_map[case_id].kind:
            raise EvalValidationError(
                f"案例 {case_id} 在 before 与 after 中的 kind 不一致："
                f"{before_map[case_id].kind} != {after_map[case_id].kind}"
            )

    improved: list[str] = []
    regressed: list[str] = []
    mixed: list[str] = []
    unchanged: list[str] = []
    undecided: list[str] = []

    for case_id in sorted(before_map):
        b = before_map[case_id]
        a = after_map[case_id]
        b_undecided = b.verdict in _UNDECIDED_SCORE_VERDICTS
        a_undecided = a.verdict in _UNDECIDED_SCORE_VERDICTS
        if b_undecided or a_undecided:
            if b_undecided and a_undecided:
                undecided.append(case_id)
            elif a_undecided:
                b_was_good = (b.kind == "clean" and b.verdict == "PASS") or (b.kind == "bug" and b.bug_recalled)
                if b_was_good:
                    regressed.append(case_id)
                else:
                    undecided.append(case_id)
            else:
                undecided.append(case_id)
            continue

        if b.kind == "bug":
            b_recall = (int(b.bug_recalled), b.matched_locations)
            a_recall = (int(a.bug_recalled), a.matched_locations)
            b_false_blocking = b.blocking_findings - b.matched_blocking_findings
            a_false_blocking = a.blocking_findings - a.matched_blocking_findings

            recall_up = a_recall > b_recall
            recall_down = a_recall < b_recall
            fp_better = a_false_blocking < b_false_blocking
            fp_worse = a_false_blocking > b_false_blocking

            if (recall_up and fp_worse) or (recall_down and fp_better):
                mixed.append(case_id)
            elif (recall_up and not fp_worse) or (not recall_down and fp_better):
                improved.append(case_id)
            elif (recall_down and not fp_better) or (not recall_up and fp_worse):
                regressed.append(case_id)
            else:
                unchanged.append(case_id)
        else:
            b_clean_bad = (int(b.clean_false_positive), b.blocking_findings)
            a_clean_bad = (int(a.clean_false_positive), a.blocking_findings)
            if a_clean_bad < b_clean_bad:
                improved.append(case_id)
            elif a_clean_bad > b_clean_bad:
                regressed.append(case_id)
            else:
                unchanged.append(case_id)

    clean_fp_delta: float | None = (
        None
        if (
            before.decided_clean_cases == 0
            or after.decided_clean_cases == 0
            or before.clean_false_positive_rate is None
            or after.clean_false_positive_rate is None
        )
        else round(after.clean_false_positive_rate - before.clean_false_positive_rate, 6)
    )

    return ScoreComparison(
        bug_case_recall_delta=round(after.bug_case_recall - before.bug_case_recall, 6),
        bug_location_recall_delta=round(after.bug_location_recall - before.bug_location_recall, 6),
        clean_false_positive_rate_delta=clean_fp_delta,
        blocking_precision_delta=round(after.blocking_precision - before.blocking_precision, 6),
        f1_delta=round(after.f1 - before.f1, 6),
        coverage_rate_delta=round(after.coverage_rate - before.coverage_rate, 6),
        improved_cases=tuple(improved),
        regressed_cases=tuple(regressed),
        mixed_cases=tuple(mixed),
        unchanged_cases=tuple(unchanged),
        undecided_cases=tuple(undecided),
    )


def load_dispositions(jsonl_path: Path) -> tuple[DispositionEntry, ...]:
    """读取 JSONL 格式的审查发现显式去向台账，并拒绝重复键 (run_id, model, finding_index)。"""
    entries: list[DispositionEntry] = []
    seen_keys: set[tuple[str, str, int]] = set()
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise EvalValidationError(f"无法读取去向台账 {jsonl_path}: {exc}") from exc

    for line_no, raw_line in enumerate(lines, 1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise EvalValidationError(f"{jsonl_path}:{line_no} JSON 解析失败：{exc}") from exc
        if not isinstance(obj, dict):
            raise EvalValidationError(f"{jsonl_path}:{line_no} 必须是 JSON 对象")
        run_id = _require_nonempty_str(obj.get("run_id"), f"line {line_no}.run_id")
        pr_number = _require_int(obj.get("pr_number"), f"line {line_no}.pr_number")
        model = _require_nonempty_str(obj.get("model"), f"line {line_no}.model")
        finding_index = _require_int(obj.get("finding_index"), f"line {line_no}.finding_index")
        if finding_index < 0:
            raise EvalValidationError(f"line {line_no}.finding_index 不能为负")
        key = (run_id, model, finding_index)
        if key in seen_keys:
            raise EvalValidationError(
                f"{jsonl_path}:{line_no} 存在重复去向键：(run_id={run_id!r}, model={model!r}, finding_index={finding_index})"
            )
        seen_keys.add(key)
        disp_raw = _require_nonempty_str(obj.get("disposition"), f"line {line_no}.disposition").lower()
        try:
            disposition = DispositionLabel(disp_raw)
        except ValueError as exc:
            raise EvalValidationError(f"line {line_no}.disposition 非法：{disp_raw!r}") from exc
        note_raw = obj.get("note", "")
        if not isinstance(note_raw, str):
            raise EvalValidationError(f"line {line_no}.note 必须是字符串")
        entries.append(
            DispositionEntry(
                run_id=run_id,
                pr_number=pr_number,
                model=model,
                finding_index=finding_index,
                disposition=disposition,
                note=note_raw,
            )
        )
    return tuple(entries)


def _classify_severity_tag_text(tag_text: str) -> Literal["blocking", "non_blocking"] | None:
    if _TAG_NON_BLOCKING_RE.search(tag_text):
        return "non_blocking"
    tokens = [tok for tok in _TAG_SPLIT_RE.split(tag_text.strip()) if tok]
    if "低" in tokens:
        return "non_blocking"
    if _TAG_BLOCKING_RE.search(tag_text):
        return "blocking"
    if "高" in tokens:
        return "blocking"
    return None


def _parse_leading_severity_tag(text: str) -> Literal["blocking", "non_blocking"] | None:
    """解析行首显式严重度标签（支持列表符号、Markdown 粗体、连续中英文方括号标签与冒号前导）。"""
    cleaned = text.lstrip()
    while True:
        list_match = _LEADING_LIST_PREFIX_RE.match(cleaned)
        if not list_match:
            break
        cleaned = cleaned[list_match.end() :].lstrip()

    unbold = re.sub(r"^(?:\*\*|__)\s*", "", cleaned)
    bracket_tags: list[str] = []
    pos = 0
    while True:
        bracket_match = _LEADING_BRACKET_TAG_RE.match(unbold[pos:])
        if not bracket_match:
            break
        bracket_tags.append(bracket_match.group(1))
        pos += bracket_match.end()
    if bracket_tags:
        classified = _classify_severity_tag_text(" / ".join(bracket_tags))
        if classified is not None:
            return classified

    colon_match = _LEADING_COLON_TAG_RE.match(cleaned)
    if colon_match:
        prefix = colon_match.group(1).strip(" *_")
        if prefix and "." not in prefix and "\\" not in prefix:
            return _classify_severity_tag_text(prefix)
    return None


def is_non_blocking_or_nit_finding(text: str, receipt_result_status: str) -> bool:
    """启发式判断单条发现是否属于 Nit / 非阻断级别（行首显式标签优先，正文启发式仅兜底无标签发现）。"""
    if receipt_result_status == "completed":
        return True
    leading = _parse_leading_severity_tag(text)
    if leading == "non_blocking":
        return True
    if leading == "blocking":
        return False
    return bool(_NON_BLOCKING_NIT_RE.search(text))


def is_style_or_format_finding(text: str) -> bool:
    """启发式判断单条发现是否涉及代码格式/风格主题（与是否阻断正交）。"""
    return bool(_STYLE_FORMAT_RE.search(text))


def classify_finding_heuristic(text: str, receipt_result_status: str) -> str:
    """对历史纯文本审查发现做启发式归类（非人工真值，仅作基线参考）。

    先判阻断级别再判格式主题：Nit / 非阻断发现即使提及格式（如 `[Nit] formatting`）
    也归入 `non_blocking_or_nit`；格式主题由 `is_style_or_format_finding` 正交独立计数。
    """
    if is_non_blocking_or_nit_finding(text, receipt_result_status):
        return "non_blocking_or_nit"
    if is_style_or_format_finding(text):
        return "blocking_style_or_format"
    if (
        receipt_result_status == "blocked"
        or _parse_leading_severity_tag(text) == "blocking"
        or _BLOCKING_MARKER_RE.search(text)
    ):
        return "blocking_substantive"
    return "other"


def _compute_round_distribution(rounds_list: Sequence[int]) -> RoundDistribution:
    if not rounds_list:
        return RoundDistribution(
            prs_counted=0,
            bucket_1=0,
            bucket_2=0,
            bucket_3=0,
            bucket_4_plus=0,
            median=None,
            mean=None,
            max_rounds=None,
        )
    b1 = sum(1 for r in rounds_list if r == 1)
    b2 = sum(1 for r in rounds_list if r == 2)
    b3 = sum(1 for r in rounds_list if r == 3)
    b4 = sum(1 for r in rounds_list if r >= 4)
    return RoundDistribution(
        prs_counted=len(rounds_list),
        bucket_1=b1,
        bucket_2=b2,
        bucket_3=b3,
        bucket_4_plus=b4,
        median=round(float(statistics.median(rounds_list)), 4),
        mean=round(float(statistics.fmean(rounds_list)), 4),
        max_rounds=max(rounds_list),
    )


def _append_corrupted(path: Path, runs_dir: Path, corrupted: list[str], corrupted_seen: set[str]) -> None:
    rel = str(path.relative_to(runs_dir))
    if rel not in corrupted_seen:
        corrupted_seen.add(rel)
        corrupted.append(rel)


def _read_json_dict(
    path: Path,
    runs_dir: Path,
    corrupted: list[str],
    corrupted_seen: set[str],
) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _append_corrupted(path, runs_dir, corrupted, corrupted_seen)
        return None
    if not isinstance(data, dict):
        _append_corrupted(path, runs_dir, corrupted, corrupted_seen)
        return None
    return data


def _parse_optional_nonempty_str_field(data: dict[str, Any] | None, key: str) -> tuple[str | None, bool]:
    """解析可选非空字符串身份字段，返回 (规范值, 是否显式非法)；键省略返回 (None, False)。"""
    if data is None or key not in data:
        return (None, False)
    raw = data[key]
    if not isinstance(raw, str) or not raw.strip():
        return (None, True)
    return (raw.strip(), False)


def _parse_optional_positive_int_field(data: dict[str, Any] | None, key: str) -> tuple[int | None, bool]:
    """解析可选正整数身份字段，返回 (规范值, 是否显式非法)；键省略返回 (None, False)。"""
    if data is None or key not in data:
        return (None, False)
    raw = data[key]
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return (None, True)
    return (raw, False)


@dataclass(frozen=True)
class _RunTimelineRecord:
    registered_at_ns: int
    attempt: int
    dir_name: str
    head_sha: str
    verdict: str
    is_reused: bool
    blocking_finding_count: int


def analyze_review_runs(
    runs_dir: Path,
    *,
    dispositions_path: Path | None = None,
    dispositions: Sequence[DispositionEntry] | None = None,
) -> BaselineMetrics:
    """扫描外部正式审查 runs 目录，产出轮次分布、BLOCK 率（含/去复用双分母）、模型一致性与发现去向基线。"""
    if not runs_dir.is_dir():
        raise EvalValidationError(f"runs 目录不存在或不是目录：{runs_dir}")
    if dispositions_path is not None and dispositions is not None:
        raise EvalValidationError("不能同时传入 dispositions_path 与 dispositions")

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    corrupted_files: list[str] = []
    corrupted_seen: set[str] = set()
    verdict_counts: Counter[str] = Counter()
    missing_outcome_runs = 0
    reused_runs = 0
    reused_pass_runs = 0
    unorderable_runs = 0

    model_verdicts: dict[str, Counter[str]] = defaultdict(Counter)
    pair_agreement: dict[str, Counter[str]] = defaultdict(Counter)

    total_receipts = 0
    completed_receipts = 0
    failed_receipts = 0
    total_findings = 0
    findings_by_receipt_status: Counter[str] = Counter()
    findings_by_model: Counter[str] = Counter()
    finding_heuristic_categories: Counter[str] = Counter()
    style_or_format_findings = 0
    nit_style_or_format_findings = 0

    all_prs: set[int] = set()
    prs_with_any_pass: set[int] = set()
    unorderable_pass_heads_by_pr: dict[int, set[str | None]] = defaultdict(set)
    pr_timeline: dict[int, list[_RunTimelineRecord]] = defaultdict(list)
    undeterminable_block_findings = 0

    # (run_id, model) -> (pr_number, finding_count)
    scanned_receipts: dict[tuple[str, str], tuple[int | None, int]] = {}
    scanned_receipt_paths: dict[tuple[str, str], Path] = {}
    ambiguous_receipt_keys: set[tuple[str, str]] = set()

    def _register_receipt_key(
        receipt_key: tuple[str, str],
        receipt_path: Path,
        effective_pr: int | None,
        finding_count: int,
    ) -> None:
        if receipt_key in ambiguous_receipt_keys:
            _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
            return
        if receipt_key in scanned_receipt_paths:
            _append_corrupted(scanned_receipt_paths[receipt_key], runs_dir, corrupted_files, corrupted_seen)
            _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
            ambiguous_receipt_keys.add(receipt_key)
            scanned_receipts.pop(receipt_key, None)
            return
        scanned_receipt_paths[receipt_key] = receipt_path
        scanned_receipts[receipt_key] = (effective_pr, finding_count)

    for run_dir in run_dirs:
        target_path = run_dir / "target.json"
        outcome_path = run_dir / "outcome.json"
        receipt_paths = sorted(run_dir.glob("*/receipt.json"))

        # 第一阶段：先读取目录级文件并完成跨文件身份一致性校验，非法或冲突目录彻底隔离。
        target_data: dict[str, Any] | None = None
        if target_path.exists():
            target_data = _read_json_dict(target_path, runs_dir, corrupted_files, corrupted_seen)

        outcome_data: dict[str, Any] | None = None
        if outcome_path.exists():
            outcome_data = _read_json_dict(outcome_path, runs_dir, corrupted_files, corrupted_seen)

        outcome_target_invalid = (
            outcome_data is not None
            and "target" in outcome_data
            and not isinstance(outcome_data["target"], dict)
        )
        outcome_target = (
            outcome_data["target"]
            if outcome_data is not None and isinstance(outcome_data.get("target"), dict)
            else None
        )

        t_run_id, t_run_id_bad = _parse_optional_nonempty_str_field(target_data, "run_id")
        t_pr, t_pr_bad = _parse_optional_positive_int_field(target_data, "pr_number")
        t_head, t_head_bad = _parse_optional_nonempty_str_field(target_data, "head_sha")

        o_run_id, o_run_id_bad = _parse_optional_nonempty_str_field(outcome_data, "run_id")
        o_pr, o_pr_bad = _parse_optional_positive_int_field(outcome_data, "pr_number")
        o_head, o_head_bad = _parse_optional_nonempty_str_field(outcome_data, "head_sha")

        ot_run_id, ot_run_id_bad = _parse_optional_nonempty_str_field(outcome_target, "run_id")
        ot_pr, ot_pr_bad = _parse_optional_positive_int_field(outcome_target, "pr_number")
        ot_head, ot_head_bad = _parse_optional_nonempty_str_field(outcome_target, "head_sha")

        dir_run_ids = {rid for rid in (t_run_id, o_run_id, ot_run_id) if rid is not None}
        dir_prs = {pr for pr in (t_pr, o_pr, ot_pr) if pr is not None}
        dir_heads = {sha for sha in (t_head, o_head, ot_head) if sha is not None}

        dir_run_id_invalid = t_run_id_bad or o_run_id_bad or ot_run_id_bad
        dir_pr_invalid = t_pr_bad or o_pr_bad or ot_pr_bad
        dir_head_invalid = t_head_bad or o_head_bad or ot_head_bad
        dir_head_non_str = any(
            d is not None and "head_sha" in d and not isinstance(d["head_sha"], str)
            for d in (target_data, outcome_data, outcome_target)
        )
        dir_head_conflict = len(dir_heads) > 1 or (bool(dir_heads) and dir_head_invalid) or dir_head_non_str

        if not outcome_path.exists():
            missing_outcome_runs += 1

        dir_identity_corrupted = (
            outcome_target_invalid
            or len(dir_run_ids) > 1
            or len(dir_prs) > 1
            or dir_head_conflict
            or dir_run_id_invalid
            or dir_pr_invalid
        )
        if dir_identity_corrupted:
            if target_path.exists():
                _append_corrupted(target_path, runs_dir, corrupted_files, corrupted_seen)
            if outcome_path.exists():
                _append_corrupted(outcome_path, runs_dir, corrupted_files, corrupted_seen)
            for rp in receipt_paths:
                _append_corrupted(rp, runs_dir, corrupted_files, corrupted_seen)
            verdict_counts["CORRUPTED_IDENTITY"] += 1
            continue

        dir_run_id: str | None = next(iter(dir_run_ids), None)
        run_pr_number: int | None = next(iter(dir_prs), None)
        dir_head_sha: str = next(iter(dir_heads), "")

        verdict = "MISSING_OUTCOME"
        is_reused = False
        if outcome_data is not None:
            raw_verdict = outcome_data.get("verdict")
            verdict = str(raw_verdict).upper() if isinstance(raw_verdict, str) and raw_verdict.strip() else "UNKNOWN"
            verdict_counts[verdict] += 1
            if outcome_data.get("reused_from"):
                is_reused = True
                reused_runs += 1
                if verdict == "PASS":
                    reused_pass_runs += 1

            raw_reviews = outcome_data.get("reviews")
            if isinstance(raw_reviews, list):
                parsed_reviews: list[tuple[str, str]] = []
                for rev in raw_reviews:
                    if not isinstance(rev, dict):
                        continue
                    model = str(rev.get("model") or "unknown")
                    rev_verdict = str(rev.get("verdict") or "UNKNOWN").upper()
                    model_verdicts[model][rev_verdict] += 1
                    parsed_reviews.append((model, rev_verdict))
                if len(parsed_reviews) == 2:
                    ordered = sorted(parsed_reviews, key=lambda item: item[0])
                    pair_key = f"{ordered[0][0]} vs {ordered[1][0]}"
                    outcome_key = f"{ordered[0][1]} / {ordered[1][1]}"
                    pair_agreement[pair_key][outcome_key] += 1
        else:
            verdict_counts["MISSING_OUTCOME"] += 1

        if run_pr_number is not None:
            all_prs.add(run_pr_number)
            if verdict == "PASS":
                prs_with_any_pass.add(run_pr_number)

        # 第二阶段：预扫描目录内所有回执、校验单回执合法性与跨回执身份一致性后再提交统计与台账。
        candidate_receipts: list[tuple[Path, dict[str, Any], str | None, int | None, str | None]] = []
        for receipt_path in receipt_paths:
            receipt = _read_json_dict(receipt_path, runs_dir, corrupted_files, corrupted_seen)
            if receipt is None:
                continue
            r_run_id, r_run_id_bad = _parse_optional_nonempty_str_field(receipt, "run_id")
            r_pr, r_pr_bad = _parse_optional_positive_int_field(receipt, "pr_number")
            r_head, r_head_bad = _parse_optional_nonempty_str_field(receipt, "head_sha")

            if r_run_id_bad or r_pr_bad or r_head_bad:
                _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
                continue
            if dir_run_id is not None and r_run_id is not None and r_run_id != dir_run_id:
                _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
                continue
            if run_pr_number is not None and r_pr is not None and r_pr != run_pr_number:
                _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
                continue
            if dir_head_sha and r_head is not None and r_head != dir_head_sha:
                _append_corrupted(receipt_path, runs_dir, corrupted_files, corrupted_seen)
                continue
            candidate_receipts.append((receipt_path, receipt, r_run_id, r_pr, r_head))

        cand_run_ids = {r_rid for _, _, r_rid, _, _ in candidate_receipts if r_rid is not None}
        cand_prs = {r_pr for _, _, _, r_pr, _ in candidate_receipts if r_pr is not None}
        cand_heads = {r_head for _, _, _, _, r_head in candidate_receipts if r_head is not None}
        cross_receipt_conflict = (
            (dir_run_id is None and len(cand_run_ids) > 1)
            or (run_pr_number is None and len(cand_prs) > 1)
            or (not dir_head_sha and len(cand_heads) > 1)
        )
        if cross_receipt_conflict:
            for rp, _, _, _, _ in candidate_receipts:
                _append_corrupted(rp, runs_dir, corrupted_files, corrupted_seen)
            candidate_receipts = []

        resolved_receipt_run_id = dir_run_id or next(iter(cand_run_ids), None) or run_dir.name
        run_blocking_findings = 0
        for receipt_path, receipt, r_run_id, r_pr, _r_head in candidate_receipts:
            total_receipts += 1
            r_status = str(receipt.get("status") or "unknown").lower()
            if r_status == "completed":
                completed_receipts += 1
            elif r_status == "failed":
                failed_receipts += 1

            model = str(receipt.get("model") or receipt_path.parent.name)
            effective_run_id = r_run_id or resolved_receipt_run_id
            effective_pr = run_pr_number if run_pr_number is not None else r_pr
            receipt_key = (effective_run_id, model)

            result = receipt.get("result")
            if not isinstance(result, dict):
                _register_receipt_key(receipt_key, receipt_path, effective_pr, 0)
                continue
            result_status = str(result.get("status") or "unknown").lower()
            raw_findings = result.get("findings")
            if not isinstance(raw_findings, list):
                _register_receipt_key(receipt_key, receipt_path, effective_pr, 0)
                continue

            _register_receipt_key(receipt_key, receipt_path, effective_pr, len(raw_findings))
            for finding in raw_findings:
                text = finding if isinstance(finding, str) else json.dumps(finding, ensure_ascii=False)
                total_findings += 1
                findings_by_receipt_status[result_status] += 1
                findings_by_model[model] += 1
                is_non_blocking = is_non_blocking_or_nit_finding(text, result_status)
                if is_style_or_format_finding(text):
                    style_or_format_findings += 1
                    if is_non_blocking:
                        nit_style_or_format_findings += 1
                category = classify_finding_heuristic(text, result_status)
                finding_heuristic_categories[category] += 1
                if verdict == "BLOCK" and result_status == "blocked" and not is_non_blocking:
                    run_blocking_findings += 1

        target_source = target_data or outcome_target
        reg_raw = target_source.get("registered_at_ns") if isinstance(target_source, dict) else None
        has_valid_ts = isinstance(reg_raw, int) and not isinstance(reg_raw, bool) and reg_raw > 0
        if run_pr_number is None or not has_valid_ts:
            unorderable_runs += 1
            if run_pr_number is not None and verdict == "PASS":
                unorderable_pass_heads_by_pr[run_pr_number].add(dir_head_sha or None)
            if verdict == "BLOCK" and run_blocking_findings > 0:
                undeterminable_block_findings += run_blocking_findings
            continue

        assert isinstance(target_source, dict)
        assert isinstance(reg_raw, int)
        att_raw = target_source.get("attempt")
        attempt = att_raw if isinstance(att_raw, int) and not isinstance(att_raw, bool) else 0
        pr_timeline[run_pr_number].append(
            _RunTimelineRecord(
                registered_at_ns=reg_raw,
                attempt=attempt,
                dir_name=run_dir.name,
                head_sha=dir_head_sha,
                verdict=verdict,
                is_reused=is_reused,
                blocking_finding_count=run_blocking_findings,
            )
        )

    rounds_all: list[int] = []
    rounds_effective: list[int] = []
    prs_first_pass_reused = 0
    inferred_fixed = 0
    total_block_findings = 0

    for pr_number, records in sorted(pr_timeline.items()):
        ordered_runs = sorted(records, key=lambda r: (r.registered_at_ns, r.attempt, r.dir_name))

        first_pass_idx: int | None = None
        for idx, rec in enumerate(ordered_runs):
            if rec.verdict == "PASS":
                first_pass_idx = idx
                break
        if first_pass_idx is not None:
            rounds_all.append(first_pass_idx + 1)
            first_pass_rec = ordered_runs[first_pass_idx]
            if first_pass_rec.is_reused:
                prs_first_pass_reused += 1
            else:
                # 有效评审轮次：仅计真实新产生正式裁定（PASS / BLOCK 且非 reused_from）的轮次。
                fresh_effective_until_pass = sum(
                    1
                    for rec in ordered_runs[: first_pass_idx + 1]
                    if rec.verdict in ("PASS", "BLOCK") and not rec.is_reused
                )
                rounds_effective.append(fresh_effective_until_pass)

        unorderable_pass_heads = unorderable_pass_heads_by_pr.get(pr_number, set())
        for rec in ordered_runs:
            if rec.verdict != "BLOCK" or rec.blocking_finding_count <= 0:
                continue
            if not rec.head_sha:
                undeterminable_block_findings += rec.blocking_finding_count
                continue
            strictly_later_passes = [
                later
                for later in ordered_runs
                if later.verdict == "PASS" and later.registered_at_ns > rec.registered_at_ns
            ]
            has_diff_head_pass = any(
                later.head_sha and later.head_sha != rec.head_sha for later in strictly_later_passes
            )
            has_unorderable_diff_or_missing_head_pass = any(
                h is None or h != rec.head_sha for h in unorderable_pass_heads
            )
            if has_diff_head_pass:
                total_block_findings += rec.blocking_finding_count
                inferred_fixed += rec.blocking_finding_count
            elif has_unorderable_diff_or_missing_head_pass or any(
                not later.head_sha for later in strictly_later_passes
            ):
                undeterminable_block_findings += rec.blocking_finding_count
            else:
                total_block_findings += rec.blocking_finding_count

    disposition_counts_counter: Counter[str] = Counter({label.value: 0 for label in DispositionLabel})
    entries: tuple[DispositionEntry, ...] = ()
    if dispositions_path is not None:
        entries = load_dispositions(dispositions_path)
    elif dispositions is not None:
        seen_disp_keys: set[tuple[str, str, int]] = set()
        for idx_d, entry in enumerate(dispositions):
            if entry.finding_index < 0:
                raise EvalValidationError(f"dispositions[{idx_d}].finding_index 不能为负")
            d_key = (entry.run_id, entry.model, entry.finding_index)
            if d_key in seen_disp_keys:
                raise EvalValidationError(
                    f"dispositions 存在重复去向键：(run_id={entry.run_id!r}, model={entry.model!r}, finding_index={entry.finding_index})"
                )
            seen_disp_keys.add(d_key)
        entries = tuple(dispositions)

    for entry in entries:
        receipt_key = (entry.run_id, entry.model)
        if receipt_key in ambiguous_receipt_keys:
            raise EvalValidationError(
                f"去向台账引用了存在重复回执键的歧义回执，无法唯一指向发现："
                f"(run_id={entry.run_id!r}, model={entry.model!r})"
            )
        if receipt_key not in scanned_receipts:
            raise EvalValidationError(
                f"去向台账引用了不存在的回执：(run_id={entry.run_id!r}, model={entry.model!r})"
            )
        receipt_pr, finding_count = scanned_receipts[receipt_key]
        if receipt_pr != entry.pr_number:
            raise EvalValidationError(
                f"去向台账 pr_number 与回执不一致：(run_id={entry.run_id!r}, model={entry.model!r}) "
                f"回执为 {receipt_pr}，台账为 {entry.pr_number}"
            )
        if not (0 <= entry.finding_index < finding_count):
            raise EvalValidationError(
                f"去向台账 finding_index 越界：(run_id={entry.run_id!r}, model={entry.model!r}) "
                f"finding_index={entry.finding_index}，回执发现条数为 {finding_count}"
            )
        disposition_counts_counter[entry.disposition.value] += 1

    disposition_total = len(entries)
    disposition_coverage_rate = round(disposition_total / total_findings, 6) if total_findings else 0.0

    resolved_labels = (
        DispositionLabel.FIXED.value,
        DispositionLabel.FALSE_POSITIVE.value,
        DispositionLabel.INTENTIONAL.value,
        DispositionLabel.NOT_IMPORTANT.value,
    )
    resolved_total = sum(disposition_counts_counter[label] for label in resolved_labels)
    disposition_resolved_rates = {
        label: round(disposition_counts_counter[label] / resolved_total, 6) if resolved_total else 0.0
        for label in resolved_labels
    }

    total_runs = len(run_dirs)
    block_count = verdict_counts.get("BLOCK", 0)
    pass_count = verdict_counts.get("PASS", 0)
    fresh_pass_runs = max(0, pass_count - reused_pass_runs)
    decided_runs_including_reuse = block_count + pass_count
    fresh_decided_runs = block_count + fresh_pass_runs

    return BaselineMetrics(
        runs_dir=str(runs_dir),
        total_runs=total_runs,
        missing_outcome_runs=missing_outcome_runs,
        reused_runs=reused_runs,
        fresh_pass_runs=fresh_pass_runs,
        unorderable_runs=unorderable_runs,
        corrupted_files=tuple(corrupted_files),
        verdict_counts=dict(sorted(verdict_counts.items())),
        block_rate_all=round(block_count / total_runs, 6) if total_runs else 0.0,
        block_rate_decided_including_reuse=(
            round(block_count / decided_runs_including_reuse, 6) if decided_runs_including_reuse else 0.0
        ),
        block_rate_fresh_decided=round(block_count / fresh_decided_runs, 6) if fresh_decided_runs else 0.0,
        unique_prs=len(all_prs),
        prs_with_pass=len(prs_with_any_pass),
        prs_without_pass=len(all_prs) - len(prs_with_any_pass),
        prs_first_pass_reused=prs_first_pass_reused,
        rounds_to_first_pass_all=_compute_round_distribution(rounds_all),
        rounds_to_first_pass_effective=_compute_round_distribution(rounds_effective),
        model_verdict_counts={m: dict(sorted(c.items())) for m, c in sorted(model_verdicts.items())},
        model_pair_agreement={pair: dict(sorted(c.items())) for pair, c in sorted(pair_agreement.items())},
        total_receipts=total_receipts,
        completed_receipts=completed_receipts,
        failed_receipts=failed_receipts,
        total_findings=total_findings,
        findings_by_receipt_status=dict(sorted(findings_by_receipt_status.items())),
        findings_by_model=dict(sorted(findings_by_model.items())),
        finding_heuristic_categories=dict(sorted(finding_heuristic_categories.items())),
        style_or_format_findings=style_or_format_findings,
        nit_style_or_format_findings=nit_style_or_format_findings,
        subsequent_head_pass_inferred_fixed=inferred_fixed,
        subsequent_head_pass_total_block_findings=total_block_findings,
        subsequent_head_pass_undeterminable_findings=undeterminable_block_findings,
        subsequent_head_pass_inferred_rate=(
            round(inferred_fixed / total_block_findings, 6) if total_block_findings else 0.0
        ),
        disposition_total=disposition_total,
        disposition_coverage_rate=disposition_coverage_rate,
        disposition_counts=dict(disposition_counts_counter),
        disposition_resolved_rates=disposition_resolved_rates,
    )


def _fmt_pct(ratio: float) -> str:
    return f"{ratio * 100:.2f}%"


def _render_round_table(title: str, dist: RoundDistribution) -> list[str]:
    lines = [f"### {title}", ""]
    if dist.prs_counted == 0:
        lines.append("- 无已达到 PASS 的 PR 样本。")
        lines.append("")
        return lines
    total = dist.prs_counted
    lines.extend(
        [
            "| 轮次分桶 | PR 数 | 占比 |",
            "| --- | ---: | ---: |",
            f"| 1 轮 | {dist.bucket_1} | {_fmt_pct(dist.bucket_1 / total)} |",
            f"| 2 轮 | {dist.bucket_2} | {_fmt_pct(dist.bucket_2 / total)} |",
            f"| 3 轮 | {dist.bucket_3} | {_fmt_pct(dist.bucket_3 / total)} |",
            f"| 4+ 轮 | {dist.bucket_4_plus} | {_fmt_pct(dist.bucket_4_plus / total)} |",
            "",
            f"- 样本 PR 数：`{total}`；中位数：`{dist.median}`；均值：`{dist.mean}`；最大轮次：`{dist.max_rounds}`。",
            "",
        ]
    )
    return lines


def render_baseline_markdown(metrics: BaselineMetrics) -> str:
    """将 BaselineMetrics 渲染为简体中文基线报告。"""
    pass_count = metrics.verdict_counts.get("PASS", 0)
    block_count = metrics.verdict_counts.get("BLOCK", 0)
    decided_including_reuse = pass_count + block_count
    fresh_decided = metrics.fresh_pass_runs + block_count
    lines: list[str] = [
        "# 外部正式审查基线统计报告（#1931）",
        "",
        f"- 扫描目录：`{metrics.runs_dir}`",
        f"- 总运行数：`{metrics.total_runs}`（其中缺 `outcome.json` 未完结：`{metrics.missing_outcome_runs}`；沿用历史 PASS：`{metrics.reused_runs}`；新产生 PASS：`{metrics.fresh_pass_runs}`；缺合法时间戳不可排序运行：`{metrics.unorderable_runs}`；损坏跳过文件：`{len(metrics.corrupted_files)}`）",
        f"- 唯一 PR 数：`{metrics.unique_prs}`（已获 PASS：`{metrics.prs_with_pass}`；尚未 PASS：`{metrics.prs_without_pass}`；其中首次 PASS 为历史复用的 PR：`{metrics.prs_first_pass_reused}`）",
        f"- BLOCK 率（占全量运行 `{metrics.total_runs}`）：`{_fmt_pct(metrics.block_rate_all)}`",
        f"- BLOCK 率（含历史复用 PASS 分母 `PASS+BLOCK = {decided_including_reuse}`）：`{_fmt_pct(metrics.block_rate_decided_including_reuse)}`",
        f"- BLOCK 率（仅新产生裁定分母 `fresh_PASS+BLOCK = {fresh_decided}`，排除 `reused_from`）：`{_fmt_pct(metrics.block_rate_fresh_decided)}`",
        "",
        "## 一、终态分布（收据/outcome 实测）",
        "",
        "| 终态 | 次数 | 占总运行比例 |",
        "| --- | ---: | ---: |",
    ]
    for verdict, count in metrics.verdict_counts.items():
        pct = count / metrics.total_runs if metrics.total_runs else 0.0
        lines.append(f"| {verdict} | {count} | {_fmt_pct(pct)} |")
    lines.append("")

    lines.append("## 二、每 PR 达到首次 PASS 的轮次分布（收据/outcome 实测）")
    lines.append("")
    lines.extend(_render_round_table("2.1 全量运行口径（含 FAILED / STALE / 复用 / 未完结，仅计具备合法时间戳的运行）", metrics.rounds_to_first_pass_all))
    lines.extend(
        _render_round_table(
            f"2.2 有效评审口径（仅计新产生 PASS / BLOCK，排除 infra FAILED / STALE 与 reused_from；另有 {metrics.prs_first_pass_reused} 个 PR 首次 PASS 本身为历史复用已单列）",
            metrics.rounds_to_first_pass_effective,
        )
    )

    lines.extend(
        [
            "## 三、单模型终态与双模型一致性矩阵（outcome.reviews 实测）",
            "",
            "### 3.1 各模型裁定分布",
            "",
            "| 模型 | PASS | BLOCK | FAILED | 其他 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for model, counts in metrics.model_verdict_counts.items():
        other = sum(v for k, v in counts.items() if k not in ("PASS", "BLOCK", "FAILED"))
        lines.append(
            f"| `{model}` | {counts.get('PASS', 0)} | {counts.get('BLOCK', 0)} | {counts.get('FAILED', 0)} | {other} |"
        )
    lines.append("")

    lines.extend(["### 3.2 双模型配对一致性", ""])
    for pair_key, outcomes in metrics.model_pair_agreement.items():
        pair_total = sum(outcomes.values())
        lines.append(f"#### `{pair_key}`（共 {pair_total} 次双审）")
        lines.append("")
        lines.append("| 裁定组合 | 次数 | 占比 |")
        lines.append("| --- | ---: | ---: |")
        for combo, cnt in outcomes.items():
            lines.append(f"| `{combo}` | {cnt} | {_fmt_pct(cnt / pair_total if pair_total else 0.0)} |")
        lines.append("")

    lines.extend(
        [
            "## 四、审查发现统计（严格区分「收据实测」与「正则/启发式分类」）",
            "",
            "### 4.1 收据实测事实（`*/receipt.json` 原样计数）",
            "",
            f"- 回执总数：`{metrics.total_receipts}`（`completed`：`{metrics.completed_receipts}`；`failed`：`{metrics.failed_receipts}`）",
            f"- 发现总条数：`{metrics.total_findings}`",
            "",
            "| 按回执 `result.status` | 发现条数 | 占比 |",
            "| --- | ---: | ---: |",
        ]
    )
    for st, cnt in metrics.findings_by_receipt_status.items():
        lines.append(f"| `{st}` | {cnt} | {_fmt_pct(cnt / metrics.total_findings if metrics.total_findings else 0.0)} |")
    lines.extend(["", "| 按审查模型 | 发现条数 | 占比 |", "| --- | ---: | ---: |"])
    for model, cnt in metrics.findings_by_model.items():
        lines.append(f"| `{model}` | {cnt} | {_fmt_pct(cnt / metrics.total_findings if metrics.total_findings else 0.0)} |")

    lines.extend(
        [
            "",
            "### 4.2 正则/启发式分类（估算口径，非人工真值）",
            "",
            "> 说明：以下分类基于发现文本正则与回执状态自动估算，用于识别格式/Nit 噪声基线，不能替代人工去向台账。",
            "",
            "| 启发式类别 | 发现条数 | 占总发现比例 |",
            "| --- | ---: | ---: |",
        ]
    )
    for cat, cnt in metrics.finding_heuristic_categories.items():
        lines.append(f"| `{cat}` | {cnt} | {_fmt_pct(cnt / metrics.total_findings if metrics.total_findings else 0.0)} |")

    blocking_style_count = metrics.style_or_format_findings - metrics.nit_style_or_format_findings
    style_ratio = metrics.style_or_format_findings / metrics.total_findings if metrics.total_findings else 0.0
    lines.extend(
        [
            "",
            f"- 格式/风格主题正交命中总数（不区分阻断与 Nit）：`{metrics.style_or_format_findings}`（`{_fmt_pct(style_ratio)}`）",
            f"  - 其中阻断态格式类（`blocking_style_or_format`）：`{blocking_style_count}`",
            f"  - 其中 Nit / 非阻断格式类（`nit_style_or_format_findings`，互斥主类归入 `non_blocking_or_nit`）：`{metrics.nit_style_or_format_findings}`",
        ]
    )

    lines.extend(
        [
            "",
            "### 4.3 后续 head 转 PASS 推定（启发式）",
            "",
            f"- 可判定 BLOCK 运行中的非 Nit 阻断发现总数：`{metrics.subsequent_head_pass_total_block_findings}`",
            f"- 缺合法时间戳/`head_sha` 或同 PR 存在不可排序的不同/缺失 `head_sha` PASS 而不可判定的 BLOCK 发现条数：`{metrics.subsequent_head_pass_undeterminable_findings}`",
            f"- 同 PR 后续更晚时间戳出现不同非空 `head_sha` 且终态转 PASS 的推定已修条数：`{metrics.subsequent_head_pass_inferred_fixed}`（`{_fmt_pct(metrics.subsequent_head_pass_inferred_rate)}`）",
            "",
            "## 五、显式去向台账统计（`load_dispositions`）",
            "",
            f"- 当前显式去向覆盖率：`{_fmt_pct(metrics.disposition_coverage_rate)}`（`{metrics.disposition_total} / {metrics.total_findings}`）",
            "",
        ]
    )
    if metrics.disposition_total == 0:
        lines.append("- 本次运行未叠加显式人工去向 JSONL 台账（`disposition_total = 0`）；后续回填 `fixed / false_positive / intentional / not_important` 后可直接传入 `--dispositions` 输出四类精确占比。")
    else:
        lines.extend(
            [
                f"- 台账总条数：`{metrics.disposition_total}`",
                "",
                "| 去向类别 | 条数 | 占已定性四类比例 |",
                "| --- | ---: | ---: |",
            ]
        )
        for label in DispositionLabel:
            cnt = metrics.disposition_counts.get(label.value, 0)
            rate = metrics.disposition_resolved_rates.get(label.value)
            rate_str = _fmt_pct(rate) if rate is not None else "—"
            lines.append(f"| `{label.value}` | {cnt} | {rate_str} |")
    lines.append("")
    return "\n".join(lines)


def _write_text_file(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise EvalValidationError(f"无法写入输出文件 {path}: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pilot1742.review_eval",
        description="代码审查评测集校验、打分、回归对比与历史运行基线统计工具（#1931）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate-cases", help="校验评测集 schema 与 Git 提交/文件/行号/diff hunk 真实性")
    p_val.add_argument("--cases", type=Path, required=True, help="cases.json 路径")
    p_val.add_argument("--repo-root", type=Path, default=None, help="可选：Git 仓库根目录，用于核验 SHA、文件行号与 diff hunk")

    p_score = sub.add_parser("score", help="对审查预测 JSON 打分")
    p_score.add_argument("--cases", type=Path, required=True, help="cases.json 路径")
    p_score.add_argument("--predictions", type=Path, required=True, help="预测结果 JSON 路径")
    p_score.add_argument("--line-tolerance", type=int, default=15, help="行号匹配容差（默认 15）")
    p_score.add_argument("--max-finding-span", type=int, default=120, help="单条发现最大行跨度上限（默认 120）")
    p_score.add_argument("--allow-partial", action="store_true", help="允许预测缺漏案例（缺漏记为 MISSING 并暴露 coverage_rate）")
    p_score.add_argument("--out-json", type=Path, default=None, help="可选：输出 EvalScore JSON 文件路径")

    p_cmp = sub.add_parser("compare", help="对比两次 EvalScore JSON 产出增量与逐案变化")
    p_cmp.add_argument("--before", type=Path, required=True, help="改动前 EvalScore JSON 路径")
    p_cmp.add_argument("--after", type=Path, required=True, help="改动后 EvalScore JSON 路径")
    p_cmp.add_argument("--out-json", type=Path, default=None, help="可选：输出 ScoreComparison JSON 文件路径")

    p_base = sub.add_parser("baseline-stats", help="统计外部正式审查 runs 目录首期基线指标")
    p_base.add_argument("--runs-dir", type=Path, required=True, help="external-review/runs 目录路径")
    p_base.add_argument("--dispositions", type=Path, default=None, help="可选：人工发现去向 JSONL 台账")
    p_base.add_argument("--out-json", type=Path, default=None, help="可选：输出基线 JSON 报告路径")
    p_base.add_argument("--out-md", type=Path, default=None, help="可选：输出基线 Markdown 报告路径")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-cases":
            cases = load_cases(args.cases)
            if args.repo_root is not None:
                validate_cases(cases, repo_root=args.repo_root)
            bug_count = sum(1 for c in cases if c.kind == "bug")
            clean_count = sum(1 for c in cases if c.kind == "clean")
            loc_count = sum(len(c.bug_locations) for c in cases)
            summary = {
                "status": "ok",
                "schema_version": SCHEMA_VERSION,
                "total_cases": len(cases),
                "bug_cases": bug_count,
                "clean_cases": clean_count,
                "total_bug_locations": loc_count,
                "cases_fingerprint": compute_cases_fingerprint(cases),
                "git_verified": args.repo_root is not None,
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        if args.command == "score":
            cases = load_cases(args.cases)
            predictions = load_predictions(args.predictions)
            result = score_predictions(
                cases,
                predictions,
                line_tolerance=args.line_tolerance,
                max_finding_span=args.max_finding_span,
                allow_partial=args.allow_partial,
            )
            rendered = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            if args.out_json is not None:
                _write_text_file(args.out_json, rendered + "\n")
            print(rendered)
            return 0

        if args.command == "compare":
            try:
                before_raw = json.loads(args.before.read_text(encoding="utf-8"))
                after_raw = json.loads(args.after.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EvalValidationError(f"无法读取打分文件：{exc}") from exc
            if not isinstance(before_raw, dict) or not isinstance(after_raw, dict):
                raise EvalValidationError("before/after 打分文件必须是 JSON 对象")
            comparison = compare_scores(_score_from_dict(before_raw), _score_from_dict(after_raw))
            rendered = json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2)
            if args.out_json is not None:
                _write_text_file(args.out_json, rendered + "\n")
            print(rendered)
            return 0

        if args.command == "baseline-stats":
            metrics = analyze_review_runs(args.runs_dir, dispositions_path=args.dispositions)
            json_text = json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2)
            md_text = render_baseline_markdown(metrics)
            if args.out_json is not None:
                _write_text_file(args.out_json, json_text + "\n")
            if args.out_md is not None:
                _write_text_file(args.out_md, md_text)
            print(json_text)
            return 0

        raise EvalValidationError(f"未知子命令：{args.command}")
    except EvalValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
