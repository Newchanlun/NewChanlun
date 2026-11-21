"""审查发现分级、异家族核实、作者回复解析、多轮收敛与幂等评论渲染（#1927 / #1928）。

本模块为纯数据与判定内核，不依赖外部 IO，也不修改既有审查执行链。
所有外部边界（模型输出、评论文本、面板配置、轮次历史）均按 fail-closed 校验。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

MAX_AUTO_ROUNDS = 3
NON_CONVERGENT_DESCRIPTION = "已 3 轮未收敛，请重新考虑方案"
COMMENT_MARKER_PREFIX = "<!-- deepagents:review-findings"

ReviewScope = Literal["full_pr", "incremental_diff"]
RoundOutcome = Literal["pass", "blocked", "non_convergent"]
GitHubStatusState = Literal["success", "failure"]


class ConvergenceError(ValueError):
    """审查分级、核实或收敛边界校验失败。"""


class Severity(Enum):
    IMPORTANT = "Important"
    NIT = "Nit"
    PRE_EXISTING = "Pre-existing"


_SEVERITY_ALIASES: dict[str, Severity] = {
    "important": Severity.IMPORTANT,
    "重要": Severity.IMPORTANT,
    "nit": Severity.NIT,
    "细节": Severity.NIT,
    "pre-existing": Severity.PRE_EXISTING,
    "原本就有": Severity.PRE_EXISTING,
}

# 严重度从严到宽：Important > Pre-existing > Nit
_SEVERITY_STRICTNESS: dict[Severity, int] = {
    Severity.IMPORTANT: 3,
    Severity.PRE_EXISTING: 2,
    Severity.NIT: 1,
}


class VerificationVerdict(Enum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    RESOLVED_BY_FIX = "resolved_by_fix"
    RESOLVED_BY_WONTFIX = "resolved_by_wontfix"


_VERDICT_VALUES: dict[str, VerificationVerdict] = {v.value: v for v in VerificationVerdict}

_MODEL_FAMILY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic", re.compile(r"(?:^|[-/_:.])(claude|anthropic)(?:$|[-/_:.0-9])")),
    ("openai", re.compile(r"(?:^|[-/_:.])(gpt|openai|codex|astra|o[134])(?:$|[-/_:.0-9])")),
    ("moonshot", re.compile(r"(?:^|[-/_:.])(kimi|moonshot)(?:$|[-/_:.0-9])")),
    ("google", re.compile(r"(?:^|[-/_:.])(gemini|google)(?:$|[-/_:.0-9])")),
    ("deepseek", re.compile(r"(?:^|[-/_:.])deepseek(?:$|[-/_:.0-9])")),
    ("qwen", re.compile(r"(?:^|[-/_:.])qwen(?:$|[-/_:.0-9])")),
    ("mistral", re.compile(r"(?:^|[-/_:.])mistral(?:$|[-/_:.0-9])")),
    ("meta", re.compile(r"(?:^|[-/_:.])(llama|meta)(?:$|[-/_:.0-9])")),
)

_COMMENT_MARKER_RE = re.compile(
    r"^<!--\s*deepagents:review-findings\s+pr=(?P<pr>[1-9]\d*)\s+round=(?P<round>[1-9]\d*)\s+head=(?P<head>\S+)\s*-->$"
)

_WONTFIX_HEAD_RE = re.compile(
    r"^(?:(?:[-*+]|\d+[.)])\s+)?"
    r"(?:"
    r"`?\[(?P<id_bracket>[0-9a-fA-F]{6,16})\]`?\s*不修"
    r"|`?(?P<id_bare>[0-9a-fA-F]{8,16})`?\s+不修"
    r"|不修\s*[（(\[]\s*(?P<id_paren>[0-9a-fA-F]{6,16})\s*[）)\]]"
    r"|不修\s*[（(]\s*(?P<path_paren>[^\s:：()（）]+?)(?::(?P<line_paren>[1-9]\d*))?\s*[）)]"
    r"|`?(?P<path_prefix>(?:\./)?[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*\.[A-Za-z0-9_+-]+)(?::(?P<line_prefix>[1-9]\d*))?`?\s+不修"
    r"|不修"
    r")\s*[:：]\s*(?P<reason>.*)$"
)


def _require_non_empty_str(raw: Any, field_name: str) -> str:
    if not isinstance(raw, str):
        raise ConvergenceError(f"{field_name} 必须是非空字符串：{raw!r}")
    text = raw.strip()
    if not text:
        raise ConvergenceError(f"{field_name} 不能为空")
    return text


def _normalize_file(raw: Any) -> str:
    text = _require_non_empty_str(raw, "file").replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    while text.startswith("./"):
        text = text[2:]
    text = text.strip()
    if not text or text == ".":
        raise ConvergenceError(f"file 路径无效：{raw!r}")
    return text


def _normalize_line(raw: Any) -> int | None:
    if raw is None:
        return None
    if type(raw) is not int or raw <= 0:
        raise ConvergenceError(f"line 必须是正整数或 None：{raw!r}")
    return raw


def _normalize_fingerprint_text(raw: Any, field_name: str) -> str:
    text = _require_non_empty_str(raw, field_name)
    return re.sub(r"\s+", " ", text).lower()


def parse_severity(raw: Any) -> Severity:
    if isinstance(raw, Severity):
        return raw
    if not isinstance(raw, str):
        raise ConvergenceError(f"severity 非法：{raw!r}")
    matched = _SEVERITY_ALIASES.get(raw.strip().lower())
    if matched is None:
        raise ConvergenceError(f"severity 非法：{raw!r}")
    return matched


def parse_verification_verdict(raw: Any) -> VerificationVerdict:
    if isinstance(raw, VerificationVerdict):
        return raw
    if not isinstance(raw, str):
        raise ConvergenceError(f"verdict 非法：{raw!r}")
    matched = _VERDICT_VALUES.get(raw.strip().lower())
    if matched is None:
        raise ConvergenceError(f"verdict 非法：{raw!r}")
    return matched


def fingerprint(file: str, category: str, failure_scenario: str) -> str:
    """按 #1927 第 6 条生成去重指纹（文件 + 类别 + 失败场景），取 sha256 前 16 位 hex。"""
    norm_file = _normalize_file(file)
    norm_category = _normalize_fingerprint_text(category, "category")
    norm_scenario = _normalize_fingerprint_text(failure_scenario, "failure_scenario")
    canonical = json.dumps([norm_file, norm_category, norm_scenario], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Finding:
    severity: Severity
    file: str
    line: int | None
    category: str
    failure_scenario: str
    evidence: str
    class_scope: str | None = None
    source_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.severity, Severity):
            raise ConvergenceError(f"Finding.severity 必须是 Severity：{self.severity!r}")
        _normalize_file(self.file)
        _normalize_line(self.line)
        _require_non_empty_str(self.category, "category")
        _require_non_empty_str(self.failure_scenario, "failure_scenario")
        _require_non_empty_str(self.evidence, "evidence")
        if self.class_scope is not None:
            _require_non_empty_str(self.class_scope, "class_scope")
        if not isinstance(self.source_models, tuple):
            raise ConvergenceError("Finding.source_models 必须是字符串元组")
        for model in self.source_models:
            _require_non_empty_str(model, "source_models[]")

    @property
    def finding_id(self) -> str:
        return fingerprint(self.file, self.category, self.failure_scenario)


def parse_finder_output(payload: Mapping[str, Any], *, source_model: str) -> tuple[Finding, ...]:
    model = _require_non_empty_str(source_model, "source_model")
    if not isinstance(payload, Mapping):
        raise ConvergenceError("finder 输出必须是对象")
    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise ConvergenceError("finder 输出缺少 findings 列表")

    parsed: list[Finding] = []
    for idx, item in enumerate(raw_findings):
        if not isinstance(item, Mapping):
            raise ConvergenceError(f"findings[{idx}] 必须是对象")
        severity = parse_severity(item.get("severity"))
        file_path = _normalize_file(item.get("file"))
        line = _normalize_line(item.get("line"))
        category = _require_non_empty_str(item.get("category"), f"findings[{idx}].category")
        failure_scenario = _require_non_empty_str(item.get("failure_scenario"), f"findings[{idx}].failure_scenario")
        evidence = _require_non_empty_str(item.get("evidence"), f"findings[{idx}].evidence")
        raw_scope = item.get("class_scope")
        if raw_scope is None:
            class_scope: str | None = None
        elif isinstance(raw_scope, str):
            stripped_scope = raw_scope.strip()
            class_scope = stripped_scope or None
        else:
            raise ConvergenceError(f"findings[{idx}].class_scope 必须是字符串或 None")
        parsed.append(
            Finding(
                severity=severity,
                file=file_path,
                line=line,
                category=category,
                failure_scenario=failure_scenario,
                evidence=evidence,
                class_scope=class_scope,
                source_models=(model,),
            )
        )
    return tuple(parsed)


def _pick_more_complete(current: str, candidate: str) -> str:
    c_curr = current.strip()
    c_cand = candidate.strip()
    if len(c_cand) != len(c_curr):
        return c_cand if len(c_cand) > len(c_curr) else c_curr
    return min(c_curr, c_cand)


def _pick_more_complete_optional(current: str | None, candidate: str | None) -> str | None:
    if current is None:
        return candidate.strip() if candidate is not None else None
    if candidate is None:
        return current.strip()
    return _pick_more_complete(current, candidate)


def _merge_two_findings(existing: Finding, incoming: Finding, merged_models: tuple[str, ...]) -> Finding:
    existing_rank = _SEVERITY_STRICTNESS[existing.severity]
    incoming_rank = _SEVERITY_STRICTNESS[incoming.severity]
    if incoming_rank > existing_rank:
        severity = incoming.severity
        preferred_line = incoming.line if incoming.line is not None else existing.line
        category = incoming.category.strip()
        failure_scenario = incoming.failure_scenario.strip()
    elif existing_rank > incoming_rank:
        severity = existing.severity
        preferred_line = existing.line if existing.line is not None else incoming.line
        category = existing.category.strip()
        failure_scenario = existing.failure_scenario.strip()
    else:
        severity = existing.severity
        if existing.line is None:
            preferred_line = incoming.line
        elif incoming.line is None:
            preferred_line = existing.line
        else:
            preferred_line = min(existing.line, incoming.line)
        category = _pick_more_complete(existing.category, incoming.category)
        failure_scenario = _pick_more_complete(existing.failure_scenario, incoming.failure_scenario)

    return Finding(
        severity=severity,
        file=_normalize_file(existing.file),
        line=preferred_line,
        category=category,
        failure_scenario=failure_scenario,
        evidence=_pick_more_complete(existing.evidence, incoming.evidence),
        class_scope=_pick_more_complete_optional(existing.class_scope, incoming.class_scope),
        source_models=merged_models,
    )


def _finding_sort_key(finding: Finding) -> tuple[int, str, bool, int, str]:
    return (
        -_SEVERITY_STRICTNESS[finding.severity],
        _normalize_file(finding.file),
        finding.line is None,
        finding.line or 0,
        finding.finding_id,
    )


def merge_and_dedupe_findings(finder_batches: Sequence[tuple[str, Sequence[Finding]]]) -> tuple[Finding, ...]:
    merged: dict[str, Finding] = {}
    for source_model, findings in finder_batches:
        model = _require_non_empty_str(source_model, "source_model")
        for item in findings:
            if not isinstance(item, Finding):
                raise ConvergenceError(f"finder_batches 元素必须是 Finding：{item!r}")
            fid = item.finding_id
            models = {model, *(m.strip() for m in item.source_models)}
            normalized = Finding(
                severity=item.severity,
                file=_normalize_file(item.file),
                line=item.line,
                category=item.category.strip(),
                failure_scenario=item.failure_scenario.strip(),
                evidence=item.evidence.strip(),
                class_scope=item.class_scope.strip() if item.class_scope is not None else None,
                source_models=tuple(sorted(models)),
            )
            if fid not in merged:
                merged[fid] = normalized
            else:
                prev = merged[fid]
                all_models = tuple(sorted(set(prev.source_models) | models))
                merged[fid] = _merge_two_findings(prev, normalized, all_models)
    return tuple(sorted(merged.values(), key=_finding_sort_key))


def infer_model_family(model: str) -> str:
    """识别模型所属家族；未知模型 fail-closed 拒绝，避免伪异家族绕过独立核实。"""
    normalized = _require_non_empty_str(model, "model").lower()
    for family, pattern in _MODEL_FAMILY_PATTERNS:
        if pattern.search(normalized):
            return family
    raise ConvergenceError(f"无法识别模型家族：{model!r}")


@dataclass(frozen=True)
class ReviewPanel:
    finder_models: tuple[str, ...]
    verifier_model: str | None = None
    require_verifier: bool = True

    def __post_init__(self) -> None:
        if type(self.require_verifier) is not bool:
            raise ConvergenceError("require_verifier 必须是 bool")
        if not isinstance(self.finder_models, tuple):
            raise ConvergenceError("finder_models 必须是模型名元组")
        min_finders = 2 if self.require_verifier else 1
        if len(self.finder_models) < min_finders:
            raise ConvergenceError(
                f"当前审查路径至少需要 {min_finders} 个 finder 会话，实际收到 {len(self.finder_models)} 个"
            )
        finder_families = {infer_model_family(m) for m in self.finder_models}
        if self.require_verifier:
            if self.verifier_model is None or not isinstance(self.verifier_model, str) or not self.verifier_model.strip():
                raise ConvergenceError("require_verifier=True 时必须指定非空 verifier_model")
            verifier_family = infer_model_family(self.verifier_model)
            if verifier_family in finder_families:
                raise ConvergenceError(
                    f"核实者模型 {self.verifier_model!r}（家族 {verifier_family}）不得与 finder 同家族"
                )
        elif self.verifier_model is not None:
            verifier_family = infer_model_family(self.verifier_model)
            if verifier_family in finder_families:
                raise ConvergenceError(
                    f"核实者模型 {self.verifier_model!r}（家族 {verifier_family}）不得与 finder 同家族"
                )

    @property
    def finder_families(self) -> frozenset[str]:
        return frozenset(infer_model_family(m) for m in self.finder_models)

    @property
    def verifier_family(self) -> str | None:
        return infer_model_family(self.verifier_model) if self.verifier_model is not None else None


@dataclass(frozen=True)
class AuthorReply:
    finding_id: str | None
    file: str | None
    line: int | None
    reason: str
    comment_id: str | None = None
    author: str | None = None

    def __post_init__(self) -> None:
        if self.finding_id is not None:
            fid = _require_non_empty_str(self.finding_id, "finding_id").lower()
            if not re.fullmatch(r"[0-9a-f]{6,16}", fid):
                raise ConvergenceError(f"AuthorReply.finding_id 格式非法：{self.finding_id!r}")
        if self.file is not None:
            _normalize_file(self.file)
        _normalize_line(self.line)
        _require_non_empty_str(self.reason, "reason")
        if self.comment_id is not None:
            _require_non_empty_str(self.comment_id, "comment_id")
        if self.author is not None:
            _require_non_empty_str(self.author, "author")


def _extract_comment_id(comment: Mapping[str, Any]) -> str | None:
    raw = comment.get("comment_id") if "comment_id" in comment else comment.get("id")
    if raw is None:
        return None
    if type(raw) is int:
        return str(raw)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _extract_comment_author(comment: Mapping[str, Any]) -> str | None:
    raw_author = comment.get("author")
    if isinstance(raw_author, str) and raw_author.strip():
        return raw_author.strip()
    user = comment.get("user")
    if isinstance(user, Mapping):
        login = user.get("login")
        if isinstance(login, str) and login.strip():
            return login.strip()
    return None


def _extract_comment_file_and_line(comment: Mapping[str, Any]) -> tuple[str | None, int | None]:
    raw_path = comment.get("path") if "path" in comment else comment.get("file")
    file_path: str | None = None
    if isinstance(raw_path, str) and raw_path.strip():
        try:
            file_path = _normalize_file(raw_path)
        except ConvergenceError:
            file_path = None
    raw_line = comment.get("line") if comment.get("line") is not None else comment.get("original_line")
    line: int | None = raw_line if type(raw_line) is int and raw_line > 0 else None
    return file_path, line


def parse_wontfix_replies(comments: Sequence[Mapping[str, Any]]) -> tuple[AuthorReply, ...]:
    """解析作者 `不修：<理由>` 回复；忽略机器人自身评论、空理由、引用行与代码块。"""
    replies: list[AuthorReply] = []
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        body = comment.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        if COMMENT_MARKER_PREFIX in body:
            continue

        comment_id = _extract_comment_id(comment)
        author = _extract_comment_author(comment)
        fallback_file, fallback_line = _extract_comment_file_and_line(comment)

        in_fence = False
        for raw_line in body.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not stripped or stripped.startswith(">"):
                continue
            match = _WONTFIX_HEAD_RE.match(stripped)
            if not match:
                continue
            reason = match.group("reason").strip()
            if not reason:
                continue

            raw_id = match.group("id_bracket") or match.group("id_bare") or match.group("id_paren")
            finding_id = raw_id.lower() if raw_id else None

            raw_path = match.group("path_prefix") or match.group("path_paren")
            raw_line_num = match.group("line_prefix") or match.group("line_paren")
            if raw_path:
                try:
                    file_path: str | None = _normalize_file(raw_path)
                except ConvergenceError:
                    continue
                line_num: int | None = int(raw_line_num) if raw_line_num else None
            elif finding_id is None:
                file_path = fallback_file
                line_num = fallback_line
            else:
                file_path = None
                line_num = None

            replies.append(
                AuthorReply(
                    finding_id=finding_id,
                    file=file_path,
                    line=line_num,
                    reason=reason,
                    comment_id=comment_id,
                    author=author,
                )
            )
    return tuple(replies)


def match_author_reply(finding: Finding, replies: Sequence[AuthorReply]) -> AuthorReply | None:
    fid = finding.finding_id
    for reply in replies:
        if reply.finding_id is not None and fid.startswith(reply.finding_id.lower()):
            return reply
    norm_file = _normalize_file(finding.file)
    for reply in replies:
        if reply.finding_id is None and reply.file is not None and _normalize_file(reply.file) == norm_file:
            if reply.line is None or reply.line == finding.line:
                return reply
    return None


@dataclass(frozen=True)
class VerifiedFinding:
    finding: Finding
    verdict: VerificationVerdict
    verifier_model: str
    verifier_evidence: str
    author_reply: AuthorReply | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.finding, Finding):
            raise ConvergenceError("VerifiedFinding.finding 必须是 Finding")
        if not isinstance(self.verdict, VerificationVerdict):
            raise ConvergenceError("VerifiedFinding.verdict 必须是 VerificationVerdict")
        _require_non_empty_str(self.verifier_model, "verifier_model")
        _require_non_empty_str(self.verifier_evidence, "verifier_evidence")
        if self.author_reply is not None and not isinstance(self.author_reply, AuthorReply):
            raise ConvergenceError("VerifiedFinding.author_reply 必须是 AuthorReply 或 None")

    @property
    def is_blocking(self) -> bool:
        return self.verdict == VerificationVerdict.CONFIRMED and self.finding.severity == Severity.IMPORTANT


def is_blocking_finding(verified_finding: VerifiedFinding) -> bool:
    """唯一阻断判据（#1927 第 3 条）：仅核实成立的 Important 阻断合并。"""
    return verified_finding.is_blocking


def parse_verifier_output(
    payload: Mapping[str, Any],
    candidate_findings: Sequence[Finding],
    *,
    verifier_model: str,
    author_replies: Sequence[AuthorReply] = (),
) -> tuple[VerifiedFinding, ...]:
    """解析核实者裁决并强制与候选清单 1:1 对齐：禁止引入新问题、禁止漏判或重复判。"""
    model = _require_non_empty_str(verifier_model, "verifier_model")
    if not isinstance(payload, Mapping):
        raise ConvergenceError("verifier 输出必须是对象")
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        raise ConvergenceError("verifier 输出缺少 verdicts 列表")

    candidates_by_id: dict[str, Finding] = {}
    ordered_ids: list[str] = []
    for candidate in candidate_findings:
        if not isinstance(candidate, Finding):
            raise ConvergenceError(f"candidate_findings 元素必须是 Finding：{candidate!r}")
        cid = candidate.finding_id
        if cid in candidates_by_id:
            raise ConvergenceError(f"candidate_findings 含重复指纹 {cid}，请先合并去重")
        candidates_by_id[cid] = candidate
        ordered_ids.append(cid)

    verdicts_by_id: dict[str, VerifiedFinding] = {}
    for idx, item in enumerate(raw_verdicts):
        if not isinstance(item, Mapping):
            raise ConvergenceError(f"verdicts[{idx}] 必须是对象")
        fid = _require_non_empty_str(item.get("finding_id"), f"verdicts[{idx}].finding_id").lower()
        if fid not in candidates_by_id:
            raise ConvergenceError(f"核实者不得引入候选清单外的新发现：{fid}")
        if fid in verdicts_by_id:
            raise ConvergenceError(f"核实者对同一发现重复裁决：{fid}")
        verdict = parse_verification_verdict(item.get("verdict"))
        raw_evidence = item["verifier_evidence"] if "verifier_evidence" in item else item.get("evidence")
        verifier_evidence = _require_non_empty_str(raw_evidence, f"verdicts[{idx}].verifier_evidence")
        finding = candidates_by_id[fid]
        matched_reply = (
            match_author_reply(finding, author_replies)
            if verdict == VerificationVerdict.RESOLVED_BY_WONTFIX and author_replies
            else None
        )
        verdicts_by_id[fid] = VerifiedFinding(
            finding=finding,
            verdict=verdict,
            verifier_model=model,
            verifier_evidence=verifier_evidence,
            author_reply=matched_reply,
        )

    missing = [cid for cid in ordered_ids if cid not in verdicts_by_id]
    if missing:
        raise ConvergenceError(f"核实者遗漏候选发现：{', '.join(missing)}")

    return tuple(verdicts_by_id[cid] for cid in ordered_ids)


@dataclass(frozen=True)
class RoundHistoryEntry:
    round_number: int
    head_sha: str
    posted_fingerprints: frozenset[str]
    unresolved_important: tuple[Finding, ...]

    def __post_init__(self) -> None:
        if type(self.round_number) is not int or self.round_number <= 0:
            raise ConvergenceError(f"round_number 必须是正整数：{self.round_number!r}")
        _require_non_empty_str(self.head_sha, "head_sha")
        if not isinstance(self.posted_fingerprints, frozenset):
            raise ConvergenceError("posted_fingerprints 必须是 frozenset[str]")
        for fp in self.posted_fingerprints:
            _require_non_empty_str(fp, "posted_fingerprints[]")
        if not isinstance(self.unresolved_important, tuple):
            raise ConvergenceError("unresolved_important 必须是 Finding 元组")
        for item in self.unresolved_important:
            if not isinstance(item, Finding):
                raise ConvergenceError("unresolved_important 元素必须是 Finding")
            if item.severity != Severity.IMPORTANT:
                raise ConvergenceError(f"unresolved_important 仅允许 Important 发现，收到 {item.severity.value}")


@dataclass(frozen=True)
class RoundPlan:
    round_number: int
    review_scope: ReviewScope
    diff_base_sha: str
    diff_head_sha: str
    unresolved_prior_important: tuple[Finding, ...]
    author_replies: tuple[AuthorReply, ...]
    already_posted_fingerprints: frozenset[str]
    exceeds_auto_rounds: bool = False


def _active_posted_fingerprints(history: Sequence[RoundHistoryEntry]) -> frozenset[str]:
    """回放历史轮次中仍处于活跃态的已贴指纹；已被解除的 Important 会移出，允许重新引入后再次贴出。"""
    active: set[str] = set()
    prev_unresolved: set[str] = set()
    for entry in history:
        current_unresolved = {f.finding_id for f in entry.unresolved_important}
        resolved_in_round = prev_unresolved - current_unresolved
        active.difference_update(resolved_in_round)
        active.update(entry.posted_fingerprints)
        prev_unresolved = current_unresolved
    return frozenset(active)


def plan_next_round(
    base_sha: str,
    head_sha: str,
    history: Sequence[RoundHistoryEntry],
    author_replies: Sequence[AuthorReply] = (),
) -> RoundPlan:
    base = _require_non_empty_str(base_sha, "base_sha")
    head = _require_non_empty_str(head_sha, "head_sha")
    for reply in author_replies:
        if not isinstance(reply, AuthorReply):
            raise ConvergenceError(f"author_replies 元素必须是 AuthorReply：{reply!r}")
    for idx, entry in enumerate(history, start=1):
        if not isinstance(entry, RoundHistoryEntry):
            raise ConvergenceError(f"history[{idx - 1}] 必须是 RoundHistoryEntry")
        if entry.round_number != idx:
            raise ConvergenceError(f"history 轮次必须从 1 连续递增：期望 {idx}，实际 {entry.round_number}")

    if not history:
        return RoundPlan(
            round_number=1,
            review_scope="full_pr",
            diff_base_sha=base,
            diff_head_sha=head,
            unresolved_prior_important=(),
            author_replies=tuple(author_replies),
            already_posted_fingerprints=frozenset(),
            exceeds_auto_rounds=False,
        )

    prev = history[-1]
    round_number = prev.round_number + 1
    return RoundPlan(
        round_number=round_number,
        review_scope="incremental_diff",
        diff_base_sha=prev.head_sha,
        diff_head_sha=head,
        unresolved_prior_important=prev.unresolved_important,
        author_replies=tuple(author_replies),
        already_posted_fingerprints=_active_posted_fingerprints(history),
        exceeds_auto_rounds=round_number > MAX_AUTO_ROUNDS,
    )


def build_round_candidates(
    plan: RoundPlan,
    finder_batches: Sequence[tuple[str, Sequence[Finding]]],
) -> tuple[Finding, ...]:
    """合并本轮 finder 新发现与上一轮未解除的 Important 发现，供核实者统一裁决。"""
    batches: list[tuple[str, Sequence[Finding]]] = list(finder_batches)
    if plan.unresolved_prior_important:
        prior_by_model: dict[str, list[Finding]] = {}
        for item in plan.unresolved_prior_important:
            model_key = item.source_models[0] if item.source_models else "prior-round"
            prior_by_model.setdefault(model_key, []).append(item)
        for model_key, items in prior_by_model.items():
            batches.append((model_key, items))
    return merge_and_dedupe_findings(batches)


def select_postable_findings(
    verified: Sequence[VerifiedFinding],
    already_posted: frozenset[str],
    *,
    resolved_fingerprints: frozenset[str] = frozenset(),
) -> tuple[VerifiedFinding, ...]:
    """筛选本轮应新贴出的核实成立发现：同指纹已贴过且未曾解除者不重复贴。"""
    effective_posted = already_posted - resolved_fingerprints
    return tuple(
        vf
        for vf in verified
        if vf.verdict == VerificationVerdict.CONFIRMED and vf.finding.finding_id not in effective_posted
    )


@dataclass(frozen=True)
class RoundDecision:
    round_number: int
    outcome: RoundOutcome
    github_state: GitHubStatusState
    description: str
    stop_auto_rereview: bool
    verified_findings: tuple[VerifiedFinding, ...]
    blocking_findings: tuple[VerifiedFinding, ...]
    non_blocking_findings: tuple[VerifiedFinding, ...]
    resolved_findings: tuple[VerifiedFinding, ...]
    rejected_findings: tuple[VerifiedFinding, ...]
    postable_findings: tuple[VerifiedFinding, ...]
    next_posted_fingerprints: frozenset[str]
    unresolved_important: tuple[Finding, ...]

    def to_history_entry(self, head_sha: str) -> RoundHistoryEntry:
        return RoundHistoryEntry(
            round_number=self.round_number,
            head_sha=_require_non_empty_str(head_sha, "head_sha"),
            posted_fingerprints=self.next_posted_fingerprints,
            unresolved_important=self.unresolved_important,
        )


def evaluate_round(
    round_number: int,
    verified: Sequence[VerifiedFinding],
    *,
    already_posted: frozenset[str] = frozenset(),
    max_auto_rounds: int = MAX_AUTO_ROUNDS,
) -> RoundDecision:
    if type(round_number) is not int or round_number <= 0:
        raise ConvergenceError(f"round_number 必须是正整数：{round_number!r}")
    if type(max_auto_rounds) is not int or max_auto_rounds <= 0:
        raise ConvergenceError(f"max_auto_rounds 必须是正整数：{max_auto_rounds!r}")

    seen: set[str] = set()
    ordered: list[VerifiedFinding] = []
    for vf in verified:
        if not isinstance(vf, VerifiedFinding):
            raise ConvergenceError(f"verified 元素必须是 VerifiedFinding：{vf!r}")
        fid = vf.finding.finding_id
        if fid in seen:
            raise ConvergenceError(f"verified 含重复指纹：{fid}")
        seen.add(fid)
        ordered.append(vf)

    verified_tuple = tuple(ordered)
    blocking = tuple(vf for vf in verified_tuple if vf.is_blocking)
    non_blocking = tuple(
        vf for vf in verified_tuple if vf.verdict == VerificationVerdict.CONFIRMED and not vf.is_blocking
    )
    resolved = tuple(
        vf
        for vf in verified_tuple
        if vf.verdict in (VerificationVerdict.RESOLVED_BY_FIX, VerificationVerdict.RESOLVED_BY_WONTFIX)
    )
    rejected = tuple(vf for vf in verified_tuple if vf.verdict == VerificationVerdict.REJECTED)

    resolved_ids = frozenset(vf.finding.finding_id for vf in resolved)
    postable = select_postable_findings(verified_tuple, already_posted, resolved_fingerprints=resolved_ids)
    next_posted = (already_posted - resolved_ids) | frozenset(vf.finding.finding_id for vf in postable)
    unresolved_important = tuple(vf.finding for vf in blocking)

    if not blocking:
        n_nit = sum(1 for vf in non_blocking if vf.finding.severity == Severity.NIT)
        n_pre = sum(1 for vf in non_blocking if vf.finding.severity == Severity.PRE_EXISTING)
        outcome: RoundOutcome = "pass"
        github_state: GitHubStatusState = "success"
        stop_auto_rereview = False
        description = f"审查通过：0 项 Important，{n_nit} 项 Nit，{n_pre} 项 Pre-existing"
    elif round_number > max_auto_rounds:
        outcome = "non_convergent"
        github_state = "failure"
        stop_auto_rereview = True
        description = (
            NON_CONVERGENT_DESCRIPTION
            if max_auto_rounds == MAX_AUTO_ROUNDS
            else f"已 {max_auto_rounds} 轮未收敛，请重新考虑方案"
        )
    else:
        outcome = "blocked"
        github_state = "failure"
        stop_auto_rereview = False
        description = f"发现 {len(blocking)} 项未解除的 Important 问题（第 {round_number}/{max_auto_rounds} 轮）"

    return RoundDecision(
        round_number=round_number,
        outcome=outcome,
        github_state=github_state,
        description=description,
        stop_auto_rereview=stop_auto_rereview,
        verified_findings=verified_tuple,
        blocking_findings=blocking,
        non_blocking_findings=non_blocking,
        resolved_findings=resolved,
        rejected_findings=rejected,
        postable_findings=postable,
        next_posted_fingerprints=next_posted,
        unresolved_important=unresolved_important,
    )


def parse_comment_marker(body: str) -> tuple[int, int, str] | None:
    first_line = body.splitlines()[0].strip() if body else ""
    match = _COMMENT_MARKER_RE.match(first_line)
    if not match:
        return None
    return int(match.group("pr")), int(match.group("round")), match.group("head")


def _format_location(finding: Finding) -> str:
    norm_file = _normalize_file(finding.file)
    return f"{norm_file}:{finding.line}" if finding.line is not None else norm_file


def _render_blocking_item(vf: VerifiedFinding, *, already_posted: bool) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_location(f)
    if already_posted:
        return (
            f"- `[{fid}]` `{loc}`（前轮已贴出，仍未解除）—— **{f.category}**：{f.failure_scenario}\n"
            f"  - 核实证据：{vf.verifier_evidence}\n"
            f"  - 处置：请在新提交中修复，或回复 `[{fid}] 不修：<理由>`"
        )
    lines = [
        f"- `[{fid}]` `{loc}` — **{f.category}**",
        f"  - 失败场景：{f.failure_scenario}",
        f"  - 核实证据：{vf.verifier_evidence}",
    ]
    if f.class_scope:
        lines.append(f"  - 同类范围：{f.class_scope}")
    lines.append(f"  - 处置：请在新提交中修复，或回复 `[{fid}] 不修：<理由>`")
    return "\n".join(lines)


def _render_non_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_location(f)
    lines = [
        f"- `[{fid}]` [{f.severity.value}] `{loc}` — **{f.category}**",
        f"  - 失败场景：{f.failure_scenario}",
        f"  - 核实证据：{vf.verifier_evidence}",
    ]
    if f.class_scope:
        lines.append(f"  - 同类范围：{f.class_scope}")
    return "\n".join(lines)


def _render_compact_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_location(f)
    return f"- `[{fid}]` `{loc}` — {f.category}：{f.failure_scenario}（回复 `[{fid}] 不修：<理由>`）"


def render_findings_comment(
    pr_number: int,
    round_number: int,
    head_sha: str,
    decision: RoundDecision,
    *,
    max_chars: int = 65536,
) -> str:
    """渲染幂等 PR 审查评论，始终保留首行隐式 marker、三级计数首行与阻断项。"""
    if type(pr_number) is not int or pr_number <= 0:
        raise ConvergenceError(f"pr_number 必须是正整数：{pr_number!r}")
    if type(round_number) is not int or round_number <= 0:
        raise ConvergenceError(f"round_number 必须是正整数：{round_number!r}")
    sha = _require_non_empty_str(head_sha, "head_sha")
    if not isinstance(decision, RoundDecision):
        raise ConvergenceError("decision 必须是 RoundDecision")
    if type(max_chars) is not int or max_chars <= 0:
        raise ConvergenceError(f"max_chars 必须是正整数：{max_chars!r}")

    marker = f"{COMMENT_MARKER_PREFIX} pr={pr_number} round={round_number} head={sha} -->"

    n_imp = len(decision.blocking_findings)
    n_nit = sum(1 for vf in decision.non_blocking_findings if vf.finding.severity == Severity.NIT)
    n_pre = sum(1 for vf in decision.non_blocking_findings if vf.finding.severity == Severity.PRE_EXISTING)

    count_prefix = f"{n_imp} 项 Important，{n_nit} 项 Nit，{n_pre} 项 Pre-existing"
    if n_imp == 0 and n_nit == 0 and n_pre == 0:
        visible_first_line = f"{count_prefix} — 无需要修复的问题。"
    elif decision.outcome == "non_convergent":
        visible_first_line = f"{count_prefix}（{decision.description}）"
    else:
        visible_first_line = count_prefix

    header = f"{marker}\n{visible_first_line}"
    if len(header) > max_chars:
        raise ConvergenceError(f"max_chars={max_chars} 过小，不足以容纳去重标记与首行摘要（至少需 {len(header)} 字符）")

    postable_ids = {vf.finding.finding_id for vf in decision.postable_findings}

    blocking_section = ""
    if decision.blocking_findings:
        items = [
            _render_blocking_item(vf, already_posted=vf.finding.finding_id not in postable_ids)
            for vf in decision.blocking_findings
        ]
        blocking_section = "### 阻断项（Important）\n\n" + "\n".join(items)

    non_blocking_section = ""
    if decision.non_blocking_findings:
        new_non_blocking = [vf for vf in decision.non_blocking_findings if vf.finding.finding_id in postable_ids]
        suppressed_count = len(decision.non_blocking_findings) - len(new_non_blocking)
        nb_lines: list[str] = ["### 非阻断项（Nit / Pre-existing）", ""]
        if new_non_blocking:
            nb_lines.extend(_render_non_blocking_item(vf) for vf in new_non_blocking)
        if suppressed_count > 0:
            nb_lines.append(f"- 另有 {suppressed_count} 项前轮已贴出的非阻断发现未重复列出。")
        non_blocking_section = "\n".join(nb_lines)

    disposition_section = ""
    if decision.resolved_findings or decision.rejected_findings:
        disp_lines: list[str] = ["### 已解除与核实驳回摘要", ""]
        for vf in decision.resolved_findings:
            label = "已修复" if vf.verdict == VerificationVerdict.RESOLVED_BY_FIX else "作者确认不修"
            reply_note = f"（理由：{vf.author_reply.reason}）" if vf.author_reply is not None else ""
            disp_lines.append(
                f"- `[{vf.finding.finding_id}]` `{_format_location(vf.finding)}` — {label}{reply_note}：{vf.verifier_evidence}"
            )
        for vf in decision.rejected_findings:
            disp_lines.append(
                f"- `[{vf.finding.finding_id}]` `{_format_location(vf.finding)}` — 核实驳回：{vf.verifier_evidence}"
            )
        disposition_section = "\n".join(disp_lines)

    optional_sections = [s for s in (non_blocking_section, disposition_section) if s]
    full_parts = [header]
    if blocking_section:
        full_parts.append(blocking_section)
    full_parts.extend(optional_sections)
    full_text = "\n\n".join(full_parts)
    if len(full_text) <= max_chars:
        return full_text

    truncation_note = "\n\n…（评论超长已截断，阻断项已优先保留）"
    base_parts = [header]
    if blocking_section:
        base_parts.append(blocking_section)
    base_text = "\n\n".join(base_parts)

    if len(base_text) + len(truncation_note) <= max_chars:
        remaining = max_chars - len(base_text) - len(truncation_note)
        extra = "\n\n".join(optional_sections)
        if remaining > 2 and extra:
            clipped = extra[: remaining - 2].rstrip()
            if clipped:
                return f"{base_text}\n\n{clipped}{truncation_note}"
        return f"{base_text}{truncation_note}"

    # 阻断项本身超长时，退回紧凑版阻断项以尽量保住全部阻断清单，同时严格不超过 max_chars
    compact_blocking = (
        "### 阻断项（Important）\n\n"
        + "\n".join(_render_compact_blocking_item(vf) for vf in decision.blocking_findings)
        if decision.blocking_findings
        else ""
    )
    compact_text = f"{header}\n\n{compact_blocking}" if compact_blocking else header
    if len(compact_text) + len(truncation_note) <= max_chars:
        return f"{compact_text}{truncation_note}"

    short_note = "\n…（已截断）"
    budget = max_chars - len(header) - len(short_note)
    if budget <= 2 or not compact_blocking:
        return header[:max_chars]
    return f"{header}\n\n{compact_blocking[: budget - 2].rstrip()}{short_note}"
