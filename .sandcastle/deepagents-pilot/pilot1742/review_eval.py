"""代码审查回滚/事故评测集打分与外部审查运行基线统计（#1931）。"""

from __future__ import annotations

import argparse
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

_BLOCKING_SEVERITIES: frozenset[str] = frozenset({"blocking", "important"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"blocking", "important", "nit", "pre_existing", "info"})
_VALID_VERDICTS: frozenset[str] = frozenset({"PASS", "BLOCK", "FAILED"})
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# 启发式正则：仅用于对历史纯文本 findings 做粗粒度归类，非人工标注真值。
_STYLE_FORMAT_RE = re.compile(
    r"(?:rustfmt|cargo\s+fmt|prettier|eslint|ruff|flake8|black|"
    r"import\s*(?:排序|顺序|分组|order)|"
    r"格式(?:化|问题|对齐)?|缩进|尾随空格|多余空行|拼写错误|typo|"
    r"style\s*(?:only|issue|nit)|formatting|whitespace)",
    re.IGNORECASE,
)
_NON_BLOCKING_NIT_RE = re.compile(
    r"(?:\[\s*nit\s*\]|\bnit\s*[:：]|非阻断|不阻断|non[- ]?blocking|"
    r"建议后续|后续跟进|可选(?:建议|优化)?|顺手|minor\b|仅作记录|低优先级)",
    re.IGNORECASE,
)
_BLOCKING_MARKER_RE = re.compile(
    r"(?:\[\s*p[012]\s*\]|\bp[012]\s*[:：]|阻断|必须修复|blocking|critical|high\s+severity)",
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
    verdict: ReviewVerdict
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
    bug_cases: int
    clean_cases: int
    recalled_bug_cases: int
    total_bug_locations: int
    matched_bug_locations: int
    clean_false_positive_cases: int
    total_blocking_findings: int
    matched_blocking_findings: int
    bug_case_recall: float
    bug_location_recall: float
    clean_false_positive_rate: float
    blocking_precision: float
    f1: float
    line_tolerance: int
    case_details: tuple[CaseScoreDetail, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreComparison:
    """两次评测打分的增量与逐案变化。"""

    bug_case_recall_delta: float
    bug_location_recall_delta: float
    clean_false_positive_rate_delta: float
    blocking_precision_delta: float
    f1_delta: float
    improved_cases: tuple[str, ...]
    regressed_cases: tuple[str, ...]
    unchanged_cases: tuple[str, ...]

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
    corrupted_files: tuple[str, ...]
    verdict_counts: dict[str, int]
    block_rate_all: float
    block_rate_decided: float
    unique_prs: int
    prs_with_pass: int
    prs_without_pass: int
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
    subsequent_head_pass_inferred_fixed: int
    subsequent_head_pass_total_block_findings: int
    subsequent_head_pass_inferred_rate: float
    disposition_total: int
    disposition_counts: dict[str, int]
    disposition_resolved_rates: dict[str, float]

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
    value = _require_nonempty_str(raw, field).lower()
    if not _SHA_RE.fullmatch(value):
        raise EvalValidationError(f"字段 {field} 不是合法的 Git SHA：{raw!r}")
    return value


def _parse_bug_location(raw: Any, prefix: str) -> BugLocation:
    if not isinstance(raw, dict):
        raise EvalValidationError(f"{prefix} 必须是 JSON 对象")
    file_path = _norm_path(_require_nonempty_str(raw.get("file"), f"{prefix}.file"))
    line_start = _require_int(raw.get("line_start"), f"{prefix}.line_start")
    line_end = _require_int(raw.get("line_end"), f"{prefix}.line_end")
    if line_start < 1 or line_end < line_start:
        raise EvalValidationError(f"{prefix} 行号区间非法：{line_start}..{line_end}")
    summary = _require_nonempty_str(raw.get("summary"), f"{prefix}.summary")
    category = _require_nonempty_str(raw.get("category"), f"{prefix}.category")
    return BugLocation(
        file=file_path,
        line_start=line_start,
        line_end=line_end,
        summary=summary,
        category=category,
    )


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    """读取并做 schema 级校验，返回评测案例元组。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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


def validate_cases(cases: Sequence[EvalCase], repo_root: Path | None = None) -> None:
    """校验评测集不变式；提供 repo_root 时同时核验 Git 提交、文件与行号界限。"""
    if not cases:
        raise EvalValidationError("评测集不能为空")

    seen_ids: set[str] = set()
    line_count_cache: dict[tuple[str, str], int] = {}

    for case in cases:
        if not case.case_id.strip():
            raise EvalValidationError("存在空 case_id")
        if case.case_id in seen_ids:
            raise EvalValidationError(f"重复的 case_id：{case.case_id}")
        seen_ids.add(case.case_id)

        if not _SHA_RE.fullmatch(case.base_sha) or not _SHA_RE.fullmatch(case.head_sha):
            raise EvalValidationError(f"{case.case_id} 包含非法 SHA")
        if case.fix_sha is not None and not _SHA_RE.fullmatch(case.fix_sha):
            raise EvalValidationError(f"{case.case_id} 包含非法 fix_sha：{case.fix_sha!r}")
        if case.base_sha == case.head_sha:
            raise EvalValidationError(f"{case.case_id} 的 base_sha 与 head_sha 相同")

        if case.kind == "bug":
            if not case.bug_locations:
                raise EvalValidationError(f"bug 案 {case.case_id} 的 bug_locations 不能为空")
            for loc in case.bug_locations:
                if not _norm_path(loc.file):
                    raise EvalValidationError(f"{case.case_id} 存在空文件路径")
                if loc.line_start < 1 or loc.line_end < loc.line_start:
                    raise EvalValidationError(
                        f"{case.case_id} 的 {loc.file} 行号非法：{loc.line_start}..{loc.line_end}"
                    )
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
                if loc.line_end > total_lines:
                    raise EvalValidationError(
                        f"{case.case_id} 的 {norm_file} 行号越界：{loc.line_end} > {total_lines}"
                    )


def load_predictions(path: Path) -> tuple[CasePrediction, ...]:
    """读取待评测审查器的预测 JSON（支持数组或 {"predictions": [...]}）。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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


def _finding_matches_location(loc: BugLocation, finding: PredictedFinding, line_tolerance: int) -> bool:
    if not finding.is_blocking or finding.line_start is None:
        return False
    if _norm_path(loc.file) != _norm_path(finding.file):
        return False
    f_start = finding.line_start
    f_end = finding.line_end if finding.line_end is not None else finding.line_start
    return f_start <= loc.line_end + line_tolerance and f_end >= max(1, loc.line_start - line_tolerance)


def score_predictions(
    cases: Sequence[EvalCase],
    predictions: Sequence[CasePrediction],
    *,
    line_tolerance: int = 15,
) -> EvalScore:
    """按位置容差对审查预测结果打分。

    口径：
    - bug_case_recall：真实 bug 案被判 BLOCK 且至少一条阻断/Important 发现命中真实 bug_location 的比例。
    - bug_location_recall：所有真实 bug_location 中被 BLOCK 案例的阻断/Important 发现命中的比例。
    - clean_false_positive_rate：真实 clean 案中因阻断/Important 误报（或无发现空 BLOCK）被判 BLOCK 的比例；仅含 nit/info 建议且未阻断不计误报。
    - blocking_precision：所有阻断/Important 发现中命中真实 bug_location 的比例。
    - f1：blocking_precision 与 bug_location_recall 的调和平均。
    """
    if line_tolerance < 0:
        raise EvalValidationError(f"line_tolerance 不能为负：{line_tolerance}")
    validate_cases(cases)

    case_ids = {c.case_id for c in cases}
    pred_map: dict[str, CasePrediction] = {}
    for pred in predictions:
        if pred.case_id in pred_map:
            raise EvalValidationError(f"预测中存在重复 case_id：{pred.case_id}")
        if pred.case_id not in case_ids:
            raise EvalValidationError(f"预测中存在未知 case_id：{pred.case_id}")
        pred_map[pred.case_id] = pred

    bug_cases = 0
    clean_cases = 0
    recalled_bug_cases = 0
    total_bug_locations = 0
    matched_bug_locations = 0
    clean_false_positive_cases = 0
    total_blocking_findings = 0
    matched_blocking_findings = 0
    details: list[CaseScoreDetail] = []

    for case in cases:
        pred = pred_map.get(case.case_id, CasePrediction(case_id=case.case_id, verdict="PASS", findings=()))
        blocking_findings = [f for f in pred.findings if f.is_blocking]
        total_blocking_findings += len(blocking_findings)

        if case.kind == "bug":
            bug_cases += 1
            total_bug_locations += len(case.bug_locations)
            matched_indices: list[int] = []
            case_matched_blocking = 0

            if pred.verdict == "BLOCK":
                for idx, loc in enumerate(case.bug_locations):
                    if any(_finding_matches_location(loc, f, line_tolerance) for f in blocking_findings):
                        matched_indices.append(idx)
                for f in blocking_findings:
                    if any(_finding_matches_location(loc, f, line_tolerance) for loc in case.bug_locations):
                        case_matched_blocking += 1

            matched_bug_locations += len(matched_indices)
            matched_blocking_findings += case_matched_blocking
            recalled = pred.verdict == "BLOCK" and len(matched_indices) > 0
            if recalled:
                recalled_bug_cases += 1

            details.append(
                CaseScoreDetail(
                    case_id=case.case_id,
                    kind=case.kind,
                    verdict=pred.verdict,
                    expected_locations=len(case.bug_locations),
                    matched_locations=len(matched_indices),
                    matched_location_indices=tuple(matched_indices),
                    blocking_findings=len(blocking_findings),
                    matched_blocking_findings=case_matched_blocking,
                    bug_recalled=recalled,
                    clean_false_positive=False,
                )
            )
        else:
            clean_cases += 1
            # 仅统计阻断/Important 误报导致的 BLOCK（以及无发现明细却强行 BLOCK 的异常情形）。
            is_fp = pred.verdict == "BLOCK" and (len(blocking_findings) > 0 or len(pred.findings) == 0)
            if is_fp:
                clean_false_positive_cases += 1
            details.append(
                CaseScoreDetail(
                    case_id=case.case_id,
                    kind=case.kind,
                    verdict=pred.verdict,
                    expected_locations=0,
                    matched_locations=0,
                    matched_location_indices=(),
                    blocking_findings=len(blocking_findings),
                    matched_blocking_findings=0,
                    bug_recalled=False,
                    clean_false_positive=is_fp,
                )
            )

    bug_case_recall = recalled_bug_cases / bug_cases if bug_cases else 0.0
    bug_location_recall = matched_bug_locations / total_bug_locations if total_bug_locations else 0.0
    clean_false_positive_rate = clean_false_positive_cases / clean_cases if clean_cases else 0.0
    blocking_precision = matched_blocking_findings / total_blocking_findings if total_blocking_findings else 0.0
    f1 = (
        2.0 * blocking_precision * bug_location_recall / (blocking_precision + bug_location_recall)
        if (blocking_precision + bug_location_recall) > 0.0
        else 0.0
    )

    return EvalScore(
        total_cases=len(cases),
        bug_cases=bug_cases,
        clean_cases=clean_cases,
        recalled_bug_cases=recalled_bug_cases,
        total_bug_locations=total_bug_locations,
        matched_bug_locations=matched_bug_locations,
        clean_false_positive_cases=clean_false_positive_cases,
        total_blocking_findings=total_blocking_findings,
        matched_blocking_findings=matched_blocking_findings,
        bug_case_recall=round(bug_case_recall, 6),
        bug_location_recall=round(bug_location_recall, 6),
        clean_false_positive_rate=round(clean_false_positive_rate, 6),
        blocking_precision=round(blocking_precision, 6),
        f1=round(f1, 6),
        line_tolerance=line_tolerance,
        case_details=tuple(details),
    )


def _score_from_dict(raw: dict[str, Any]) -> EvalScore:
    try:
        raw_details = raw["case_details"]
        details = tuple(
            CaseScoreDetail(
                case_id=str(d["case_id"]),
                kind="bug" if d["kind"] == "bug" else "clean",
                verdict="PASS" if d["verdict"] == "PASS" else ("BLOCK" if d["verdict"] == "BLOCK" else "FAILED"),
                expected_locations=int(d["expected_locations"]),
                matched_locations=int(d["matched_locations"]),
                matched_location_indices=tuple(int(i) for i in d["matched_location_indices"]),
                blocking_findings=int(d["blocking_findings"]),
                matched_blocking_findings=int(d["matched_blocking_findings"]),
                bug_recalled=bool(d["bug_recalled"]),
                clean_false_positive=bool(d["clean_false_positive"]),
            )
            for d in raw_details
        )
        return EvalScore(
            total_cases=int(raw["total_cases"]),
            bug_cases=int(raw["bug_cases"]),
            clean_cases=int(raw["clean_cases"]),
            recalled_bug_cases=int(raw["recalled_bug_cases"]),
            total_bug_locations=int(raw["total_bug_locations"]),
            matched_bug_locations=int(raw["matched_bug_locations"]),
            clean_false_positive_cases=int(raw["clean_false_positive_cases"]),
            total_blocking_findings=int(raw["total_blocking_findings"]),
            matched_blocking_findings=int(raw["matched_blocking_findings"]),
            bug_case_recall=float(raw["bug_case_recall"]),
            bug_location_recall=float(raw["bug_location_recall"]),
            clean_false_positive_rate=float(raw["clean_false_positive_rate"]),
            blocking_precision=float(raw["blocking_precision"]),
            f1=float(raw["f1"]),
            line_tolerance=int(raw["line_tolerance"]),
            case_details=details,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise EvalValidationError(f"无效的 EvalScore JSON：{exc}") from exc


def compare_scores(before: EvalScore, after: EvalScore) -> ScoreComparison:
    """对比两次打分，产出指标增量与逐案回归/改进列表。"""
    before_map = {d.case_id: d for d in before.case_details}
    after_map = {d.case_id: d for d in after.case_details}

    improved: list[str] = []
    regressed: list[str] = []
    unchanged: list[str] = []

    for case_id in sorted(set(before_map) & set(after_map)):
        b = before_map[case_id]
        a = after_map[case_id]
        if b.kind == "bug" and a.kind == "bug":
            b_rank = (int(b.bug_recalled), b.matched_locations)
            a_rank = (int(a.bug_recalled), a.matched_locations)
            if a_rank > b_rank:
                improved.append(case_id)
            elif a_rank < b_rank:
                regressed.append(case_id)
            else:
                unchanged.append(case_id)
        elif b.kind == "clean" and a.kind == "clean":
            if b.clean_false_positive and not a.clean_false_positive:
                improved.append(case_id)
            elif not b.clean_false_positive and a.clean_false_positive:
                regressed.append(case_id)
            else:
                unchanged.append(case_id)
        else:
            unchanged.append(case_id)

    return ScoreComparison(
        bug_case_recall_delta=round(after.bug_case_recall - before.bug_case_recall, 6),
        bug_location_recall_delta=round(after.bug_location_recall - before.bug_location_recall, 6),
        clean_false_positive_rate_delta=round(after.clean_false_positive_rate - before.clean_false_positive_rate, 6),
        blocking_precision_delta=round(after.blocking_precision - before.blocking_precision, 6),
        f1_delta=round(after.f1 - before.f1, 6),
        improved_cases=tuple(improved),
        regressed_cases=tuple(regressed),
        unchanged_cases=tuple(unchanged),
    )


def load_dispositions(jsonl_path: Path) -> tuple[DispositionEntry, ...]:
    """读取 JSONL 格式的审查发现显式去向台账。"""
    entries: list[DispositionEntry] = []
    try:
        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
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


def classify_finding_heuristic(text: str, receipt_result_status: str) -> str:
    """对历史纯文本审查发现做启发式归类（非人工真值，仅作基线参考）。"""
    if _STYLE_FORMAT_RE.search(text):
        return "style_or_format"
    if _NON_BLOCKING_NIT_RE.search(text) or receipt_result_status == "completed":
        return "non_blocking_or_nit"
    if receipt_result_status == "blocked" or _BLOCKING_MARKER_RE.search(text):
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


def _read_json_dict(path: Path, runs_dir: Path, corrupted: list[str]) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        corrupted.append(str(path.relative_to(runs_dir)))
        return None
    if not isinstance(data, dict):
        corrupted.append(str(path.relative_to(runs_dir)))
        return None
    return data


@dataclass(frozen=True)
class _RunTimelineRecord:
    registered_at_ns: int
    attempt: int
    dir_name: str
    head_sha: str
    verdict: str
    blocking_finding_count: int


def analyze_review_runs(
    runs_dir: Path,
    *,
    dispositions_path: Path | None = None,
) -> BaselineMetrics:
    """扫描外部正式审查 runs 目录，产出轮次分布、BLOCK 率、模型一致性与发现去向基线。"""
    if not runs_dir.is_dir():
        raise EvalValidationError(f"runs 目录不存在或不是目录：{runs_dir}")

    run_dirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    corrupted_files: list[str] = []
    verdict_counts: Counter[str] = Counter()
    missing_outcome_runs = 0
    reused_runs = 0

    model_verdicts: dict[str, Counter[str]] = defaultdict(Counter)
    pair_agreement: dict[str, Counter[str]] = defaultdict(Counter)

    total_receipts = 0
    completed_receipts = 0
    failed_receipts = 0
    total_findings = 0
    findings_by_receipt_status: Counter[str] = Counter()
    findings_by_model: Counter[str] = Counter()
    finding_heuristic_categories: Counter[str] = Counter()

    pr_timeline: dict[int, list[_RunTimelineRecord]] = defaultdict(list)

    for run_dir in run_dirs:
        target_path = run_dir / "target.json"
        outcome_path = run_dir / "outcome.json"

        target_data: dict[str, Any] | None = None
        if target_path.exists():
            target_data = _read_json_dict(target_path, runs_dir, corrupted_files)

        outcome_data: dict[str, Any] | None = None
        if outcome_path.exists():
            outcome_data = _read_json_dict(outcome_path, runs_dir, corrupted_files)
        else:
            missing_outcome_runs += 1

        verdict = "MISSING_OUTCOME"
        if outcome_data is not None:
            raw_verdict = outcome_data.get("verdict")
            verdict = str(raw_verdict).upper() if isinstance(raw_verdict, str) and raw_verdict.strip() else "UNKNOWN"
            verdict_counts[verdict] += 1
            if outcome_data.get("reused_from"):
                reused_runs += 1

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

        run_blocking_findings = 0
        for receipt_path in sorted(run_dir.glob("*/receipt.json")):
            receipt = _read_json_dict(receipt_path, runs_dir, corrupted_files)
            if receipt is None:
                continue
            total_receipts += 1
            r_status = str(receipt.get("status") or "unknown").lower()
            if r_status == "completed":
                completed_receipts += 1
            elif r_status == "failed":
                failed_receipts += 1

            model = str(receipt.get("model") or receipt_path.parent.name)
            result = receipt.get("result")
            if not isinstance(result, dict):
                continue
            result_status = str(result.get("status") or "unknown").lower()
            raw_findings = result.get("findings")
            if not isinstance(raw_findings, list):
                continue

            for finding in raw_findings:
                text = finding if isinstance(finding, str) else json.dumps(finding, ensure_ascii=False)
                total_findings += 1
                findings_by_receipt_status[result_status] += 1
                findings_by_model[model] += 1
                category = classify_finding_heuristic(text, result_status)
                finding_heuristic_categories[category] += 1
                if verdict == "BLOCK" and result_status == "blocked" and category != "non_blocking_or_nit":
                    run_blocking_findings += 1

        target_source = target_data or (
            outcome_data.get("target") if outcome_data and isinstance(outcome_data.get("target"), dict) else None
        )
        if isinstance(target_source, dict):
            pr_raw = target_source.get("pr_number")
            if isinstance(pr_raw, int) and not isinstance(pr_raw, bool):
                reg_raw = target_source.get("registered_at_ns")
                reg_ns = reg_raw if isinstance(reg_raw, int) and not isinstance(reg_raw, bool) else 0
                att_raw = target_source.get("attempt")
                attempt = att_raw if isinstance(att_raw, int) and not isinstance(att_raw, bool) else 0
                head_sha = str(target_source.get("head_sha") or "")
                pr_timeline[pr_raw].append(
                    _RunTimelineRecord(
                        registered_at_ns=reg_ns,
                        attempt=attempt,
                        dir_name=run_dir.name,
                        head_sha=head_sha,
                        verdict=verdict,
                        blocking_finding_count=run_blocking_findings,
                    )
                )

    rounds_all: list[int] = []
    rounds_effective: list[int] = []
    prs_with_pass = 0
    inferred_fixed = 0
    total_block_findings = 0

    for _pr_number, records in sorted(pr_timeline.items()):
        ordered_runs = sorted(records, key=lambda r: (r.registered_at_ns, r.attempt, r.dir_name))

        first_pass_all: int | None = None
        for idx, rec in enumerate(ordered_runs, 1):
            if rec.verdict == "PASS":
                first_pass_all = idx
                break
        if first_pass_all is not None:
            prs_with_pass += 1
            rounds_all.append(first_pass_all)

        # 有效评审轮次：仅计产生正式评审结论（PASS / BLOCK）的运行，排除 infra FAILED、STALE 与未完结运行。
        effective_runs = [r for r in ordered_runs if r.verdict in ("PASS", "BLOCK")]
        for idx, rec in enumerate(effective_runs, 1):
            if rec.verdict == "PASS":
                rounds_effective.append(idx)
                break

        for idx, rec in enumerate(ordered_runs):
            if rec.verdict == "BLOCK" and rec.blocking_finding_count > 0:
                total_block_findings += rec.blocking_finding_count
                later_diff_head_pass = any(
                    later.verdict == "PASS" and later.head_sha and later.head_sha != rec.head_sha
                    for later in ordered_runs[idx + 1 :]
                )
                if later_diff_head_pass:
                    inferred_fixed += rec.blocking_finding_count

    disposition_counts_counter: Counter[str] = Counter({label.value: 0 for label in DispositionLabel})
    disposition_total = 0
    if dispositions_path is not None:
        entries = load_dispositions(dispositions_path)
        disposition_total = len(entries)
        for entry in entries:
            disposition_counts_counter[entry.disposition.value] += 1

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
    decided_runs = block_count + pass_count

    return BaselineMetrics(
        runs_dir=str(runs_dir),
        total_runs=total_runs,
        missing_outcome_runs=missing_outcome_runs,
        reused_runs=reused_runs,
        corrupted_files=tuple(corrupted_files),
        verdict_counts=dict(sorted(verdict_counts.items())),
        block_rate_all=round(block_count / total_runs, 6) if total_runs else 0.0,
        block_rate_decided=round(block_count / decided_runs, 6) if decided_runs else 0.0,
        unique_prs=len(pr_timeline),
        prs_with_pass=prs_with_pass,
        prs_without_pass=len(pr_timeline) - prs_with_pass,
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
        subsequent_head_pass_inferred_fixed=inferred_fixed,
        subsequent_head_pass_total_block_findings=total_block_findings,
        subsequent_head_pass_inferred_rate=(
            round(inferred_fixed / total_block_findings, 6) if total_block_findings else 0.0
        ),
        disposition_total=disposition_total,
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
    lines: list[str] = [
        "# 外部正式审查基线统计报告（#1931）",
        "",
        f"- 扫描目录：`{metrics.runs_dir}`",
        f"- 总运行数：`{metrics.total_runs}`（其中缺 `outcome.json` 未完结：`{metrics.missing_outcome_runs}`；沿用历史 PASS：`{metrics.reused_runs}`；损坏跳过文件：`{len(metrics.corrupted_files)}`）",
        f"- 唯一 PR 数：`{metrics.unique_prs}`（已获 PASS：`{metrics.prs_with_pass}`；尚未 PASS：`{metrics.prs_without_pass}`）",
        f"- BLOCK 率（占全量运行）：`{_fmt_pct(metrics.block_rate_all)}`；BLOCK 率（占 PASS+BLOCK 有效裁定）：`{_fmt_pct(metrics.block_rate_decided)}`",
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
    lines.extend(_render_round_table("2.1 全量运行口径（含 FAILED / STALE / 未完结）", metrics.rounds_to_first_pass_all))
    lines.extend(
        _render_round_table("2.2 有效评审口径（仅计 PASS / BLOCK，排除 infra FAILED / STALE）", metrics.rounds_to_first_pass_effective)
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

    lines.extend(
        [
            "",
            "### 4.3 后续 head 转 PASS 推定（启发式）",
            "",
            f"- BLOCK 运行中的非 Nit 阻断发现总数：`{metrics.subsequent_head_pass_total_block_findings}`",
            f"- 同 PR 后续出现不同 `head_sha` 且终态转 PASS 的推定已修条数：`{metrics.subsequent_head_pass_inferred_fixed}`（`{_fmt_pct(metrics.subsequent_head_pass_inferred_rate)}`）",
            "",
            "## 五、显式去向台账统计（`load_dispositions`）",
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pilot1742.review_eval",
        description="代码审查评测集校验、打分、回归对比与历史运行基线统计工具（#1931）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser("validate-cases", help="校验评测集 schema 与 Git 提交/文件/行号真实性")
    p_val.add_argument("--cases", type=Path, required=True, help="cases.json 路径")
    p_val.add_argument("--repo-root", type=Path, default=None, help="可选：Git 仓库根目录，用于核验 SHA 与文件行号")

    p_score = sub.add_parser("score", help="对审查预测 JSON 打分")
    p_score.add_argument("--cases", type=Path, required=True, help="cases.json 路径")
    p_score.add_argument("--predictions", type=Path, required=True, help="预测结果 JSON 路径")
    p_score.add_argument("--line-tolerance", type=int, default=15, help="行号匹配容差（默认 15）")
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
                "git_verified": args.repo_root is not None,
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        if args.command == "score":
            cases = load_cases(args.cases)
            predictions = load_predictions(args.predictions)
            result = score_predictions(cases, predictions, line_tolerance=args.line_tolerance)
            rendered = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
            if args.out_json is not None:
                _write_text_file(args.out_json, rendered + "\n")
            print(rendered)
            return 0

        if args.command == "compare":
            try:
                before_raw = json.loads(args.before.read_text(encoding="utf-8"))
                after_raw = json.loads(args.after.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
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
