"""审查发现分级、异家族核实、作者回复解析、多轮收敛与幂等评论渲染（#1927 / #1928）。

本模块为纯数据与判定内核，不依赖外部 IO，也不修改既有审查执行链。
所有外部边界（模型输出、评论文本、面板配置、轮次历史）均按 fail-closed 校验。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

MAX_AUTO_ROUNDS = 3
NON_CONVERGENT_DESCRIPTION = "已 3 轮未收敛，请重新考虑方案"
COMMENT_MARKER_PREFIX = "<!-- deepagents:review-findings"
_PRIOR_ROUND_PLACEHOLDER = "prior-round"

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

_FENCE_OPEN_BACKTICK_RE = re.compile(r"^ {0,3}(`{3,})[^`]*$")
_FENCE_OPEN_TILDE_RE = re.compile(r"^ {0,3}(~{3,}).*$")

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


def _normalize_str_collection(
    values: Collection[str],
    field_name: str,
    *,
    require_non_empty: bool = False,
    lowercase: bool = False,
) -> frozenset[str]:
    if not isinstance(values, Collection) or isinstance(values, (str, bytes)):
        raise ConvergenceError(f"{field_name} 必须是字符串集合：{values!r}")
    normalized: set[str] = set()
    for item in values:
        val = _require_non_empty_str(item, f"{field_name}[]")
        normalized.add(val.lower() if lowercase else val)
    if require_non_empty and not normalized:
        raise ConvergenceError(f"{field_name} 不能为空")
    return frozenset(normalized)


def _real_source_models(models: Sequence[str]) -> tuple[str, ...]:
    real = {
        m.strip()
        for m in models
        if isinstance(m, str) and m.strip() and m.strip().lower() != _PRIOR_ROUND_PLACEHOLDER
    }
    return tuple(sorted(real))


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


def _pick_best_text(values: Sequence[str]) -> str:
    return min((v.strip() for v in values), key=lambda s: (-len(s), s))


def _reduce_finding_group(entries: Sequence[tuple[str, Finding]]) -> Finding:
    """对同指纹分组一次性确定性归约，保证结果完全与输入顺序无关。"""
    group = [item for _, item in entries]
    max_rank = max(_SEVERITY_STRICTNESS[f.severity] for f in group)
    severity = next(f.severity for f in group if _SEVERITY_STRICTNESS[f.severity] == max_rank)
    top_members = [f for f in group if f.severity == severity]

    top_lines = [f.line for f in top_members if f.line is not None]
    if top_lines:
        preferred_line: int | None = min(top_lines)
    else:
        fallback_lines = [f.line for f in group if f.line is not None]
        preferred_line = min(fallback_lines) if fallback_lines else None

    category = _pick_best_text([f.category for f in top_members])
    failure_scenario = _pick_best_text([f.failure_scenario for f in top_members])
    evidence = _pick_best_text([f.evidence for f in group])
    scopes = [f.class_scope.strip() for f in group if f.class_scope is not None]
    class_scope = _pick_best_text(scopes) if scopes else None

    all_models: set[str] = set()
    for src_model, item in entries:
        all_models.add(src_model)
        all_models.update(m.strip() for m in item.source_models)
    real_models = {m for m in all_models if m.lower() != _PRIOR_ROUND_PLACEHOLDER}
    merged_models = tuple(sorted(real_models)) if real_models else tuple(sorted(all_models))

    return Finding(
        severity=severity,
        file=_normalize_file(group[0].file),
        line=preferred_line,
        category=category,
        failure_scenario=failure_scenario,
        evidence=evidence,
        class_scope=class_scope,
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
    grouped: dict[str, list[tuple[str, Finding]]] = {}
    for source_model, findings in finder_batches:
        model = _require_non_empty_str(source_model, "source_model")
        for item in findings:
            if not isinstance(item, Finding):
                raise ConvergenceError(f"finder_batches 元素必须是 Finding：{item!r}")
            grouped.setdefault(item.finding_id, []).append((model, item))
    reduced = [_reduce_finding_group(entries) for entries in grouped.values()]
    return tuple(sorted(reduced, key=_finding_sort_key))


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

    @property
    def reply_key(self) -> str:
        """稳定唯一消费键：同一评论内多条不同锚点回复互不冲突，且跨轮次重放保持一致。"""
        cid = self.comment_id.strip() if self.comment_id is not None else ""
        author = self.author.strip().lower() if self.author is not None else ""
        norm_id = self.finding_id.strip().lower() if self.finding_id is not None else ""
        norm_file = _normalize_file(self.file) if self.file is not None else ""
        norm_line = "" if self.line is None else str(self.line)
        norm_reason = re.sub(r"\s+", " ", self.reason.strip())
        canonical = json.dumps(
            [cid, author, norm_id, norm_file, norm_line, norm_reason],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        anchor = f"id:{norm_id}" if norm_id else f"loc:{norm_file}:{norm_line or '*'}"
        return f"{cid or 'no-comment'}|{anchor}|{digest}"


def _extract_comment_id(comment: Mapping[str, Any]) -> str | None:
    raw = comment.get("comment_id") if "comment_id" in comment else comment.get("id")
    if raw is None:
        return None
    if type(raw) is int:
        return str(raw)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _is_bot_comment(comment: Mapping[str, Any]) -> bool:
    user = comment.get("user")
    if isinstance(user, Mapping):
        raw_type = user.get("type")
        if isinstance(raw_type, str) and raw_type.strip().lower() == "bot":
            return True
    raw_author_type = comment.get("author_type")
    if isinstance(raw_author_type, str) and raw_author_type.strip().lower() == "bot":
        return True
    return False


def _extract_comment_author(comment: Mapping[str, Any]) -> str | None:
    raw_author = comment.get("author")
    author_val = raw_author.strip() if isinstance(raw_author, str) and raw_author.strip() else None
    user = comment.get("user")
    login_val: str | None = None
    if isinstance(user, Mapping):
        raw_login = user.get("login")
        if isinstance(raw_login, str) and raw_login.strip():
            login_val = raw_login.strip()
    if author_val is not None and login_val is not None:
        if author_val.lower() != login_val.lower():
            return None
        return login_val
    return login_val or author_val


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


def _leading_indent_columns(line: str) -> int:
    cols = 0
    for ch in line:
        if ch == " ":
            cols += 1
        elif ch == "\t":
            cols += 4 - (cols % 4)
        else:
            break
    return cols


def _match_opening_fence(line: str) -> tuple[str, int] | None:
    bt_match = _FENCE_OPEN_BACKTICK_RE.match(line)
    if bt_match:
        marker = bt_match.group(1)
        return marker[0], len(marker)
    tilde_match = _FENCE_OPEN_TILDE_RE.match(line)
    if tilde_match:
        marker = tilde_match.group(1)
        return marker[0], len(marker)
    return None


def _is_closing_fence(line: str, fence_char: str, fence_len: int) -> bool:
    return bool(re.fullmatch(rf" {{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*", line))


def parse_wontfix_replies(
    comments: Sequence[Mapping[str, Any]],
    *,
    allowed_authors: Collection[str],
) -> tuple[AuthorReply, ...]:
    """解析白名单作者的 `不修：<理由>` 回复；拒绝机器人、缺失或非白名单作者，并跳过代码块与引用行。"""
    allowed = _normalize_str_collection(
        allowed_authors,
        "allowed_authors",
        require_non_empty=True,
        lowercase=True,
    )
    replies: list[AuthorReply] = []
    for comment in comments:
        if not isinstance(comment, Mapping):
            continue
        body = comment.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        if COMMENT_MARKER_PREFIX in body:
            continue
        if _is_bot_comment(comment):
            continue

        author = _extract_comment_author(comment)
        if author is None or author.lower() not in allowed:
            continue

        comment_id = _extract_comment_id(comment)
        fallback_file, fallback_line = _extract_comment_file_and_line(comment)

        fence_char: str | None = None
        fence_len = 0
        for raw_line in body.splitlines():
            if fence_char is not None:
                if _is_closing_fence(raw_line, fence_char, fence_len):
                    fence_char = None
                    fence_len = 0
                continue

            # 必须在 .strip() 之前识别缩进代码块（4 空格或制表符）
            if _leading_indent_columns(raw_line) >= 4:
                continue

            opened = _match_opening_fence(raw_line)
            if opened is not None:
                fence_char, fence_len = opened
                continue

            stripped = raw_line.strip()
            if not stripped or stripped.startswith(">"):
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


def bind_author_replies(
    findings: Sequence[Finding],
    replies: Sequence[AuthorReply],
    *,
    consumed_reply_keys: Collection[str] = (),
    consumed_comment_ids: Collection[str] = (),
) -> dict[str, AuthorReply]:
    """面向整个候选集合做作者回复唯一绑定。

    规则：
    - 忽略已消费（consumed_reply_keys / consumed_comment_ids）的历史回复；
    - 任一条回复若命中超过 1 个活跃候选，视为歧义，拒绝绑定到任何发现；
    - 同一评论中的多条回复若各自唯一指向不同发现，可分别绑定；
    - 同一发现被多条有效回复命中时，按锚点精度（ID > 文件+行号 > 仅文件）择优，同精度取最新回复。
    """
    finding_list: list[Finding] = []
    seen_ids: set[str] = set()
    for item in findings:
        if not isinstance(item, Finding):
            raise ConvergenceError(f"findings 元素必须是 Finding：{item!r}")
        fid = item.finding_id
        if fid in seen_ids:
            raise ConvergenceError(f"findings 含重复指纹 {fid}，请先合并去重")
        seen_ids.add(fid)
        finding_list.append(item)

    consumed_keys = _normalize_str_collection(consumed_reply_keys, "consumed_reply_keys")
    consumed_cids = _normalize_str_collection(consumed_comment_ids, "consumed_comment_ids")

    best_by_id: dict[str, tuple[int, AuthorReply]] = {}
    for reply in replies:
        if not isinstance(reply, AuthorReply):
            raise ConvergenceError(f"replies 元素必须是 AuthorReply：{reply!r}")
        if reply.reply_key in consumed_keys:
            continue
        if reply.comment_id is not None and reply.comment_id.strip() in consumed_cids:
            continue

        matches: list[Finding]
        specificity: int
        if reply.finding_id is not None:
            prefix = reply.finding_id.strip().lower()
            matches = [f for f in finding_list if f.finding_id.startswith(prefix)]
            specificity = 3
        elif reply.file is not None:
            norm_file = _normalize_file(reply.file)
            if reply.line is not None:
                matches = [f for f in finding_list if _normalize_file(f.file) == norm_file and f.line == reply.line]
                specificity = 2
            else:
                matches = [f for f in finding_list if _normalize_file(f.file) == norm_file]
                specificity = 1
        else:
            continue

        # 命中 0 个或超过 1 个活跃候选均拒绝绑定（绝不让一条歧义回复解除多个发现）
        if len(matches) != 1:
            continue

        target_id = matches[0].finding_id
        current = best_by_id.get(target_id)
        if current is None or specificity >= current[0]:
            best_by_id[target_id] = (specificity, reply)

    return {fid: pair[1] for fid, pair in best_by_id.items()}


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
        if self.verdict == VerificationVerdict.RESOLVED_BY_WONTFIX and self.author_reply is None:
            raise ConvergenceError("verdict=resolved_by_wontfix 时必须绑定非空 author_reply")

    @property
    def is_blocking(self) -> bool:
        return self.verdict == VerificationVerdict.CONFIRMED and self.finding.severity == Severity.IMPORTANT


def is_blocking_finding(verified_finding: VerifiedFinding) -> bool:
    """唯一阻断判据（#1927 第 3 条）：仅核实成立的 Important 阻断合并。"""
    return verified_finding.is_blocking


def accept_quick_pass_findings(
    panel: ReviewPanel,
    findings: Sequence[Finding],
) -> tuple[VerifiedFinding, ...]:
    """低风险快审显式直通入口（仅允许 panel.require_verifier=False，避免与异家族核实混用）。"""
    if not isinstance(panel, ReviewPanel):
        raise ConvergenceError("panel 必须是 ReviewPanel")
    if panel.require_verifier:
        raise ConvergenceError("当前审查面板要求独立核实（require_verifier=True），禁止走快审直通入口")

    allowed_finders = {m.strip() for m in panel.finder_models}
    seen_ids: set[str] = set()
    accepted: list[VerifiedFinding] = []
    quick_model = f"quick-pass:{panel.finder_models[0].strip()}"
    for item in findings:
        if not isinstance(item, Finding):
            raise ConvergenceError(f"findings 元素必须是 Finding：{item!r}")
        fid = item.finding_id
        if fid in seen_ids:
            raise ConvergenceError(f"findings 含重复指纹 {fid}，请先合并去重")
        seen_ids.add(fid)

        real_models = _real_source_models(item.source_models)
        if not real_models:
            raise ConvergenceError(f"快审发现 {fid} 缺少真实 finder 模型来源")
        unknown_sources = [m for m in real_models if m not in allowed_finders]
        if unknown_sources:
            raise ConvergenceError(
                f"快审发现 {fid} 的来源模型 {unknown_sources!r} 不在 panel.finder_models 中"
            )
        accepted.append(
            VerifiedFinding(
                finding=item,
                verdict=VerificationVerdict.CONFIRMED,
                verifier_model=quick_model,
                verifier_evidence=f"低风险快审直通（免独立核实，来源：{', '.join(real_models)}）：{item.evidence}",
                author_reply=None,
            )
        )
    return tuple(accepted)


def parse_verifier_output(
    payload: Mapping[str, Any],
    candidate_findings: Sequence[Finding],
    *,
    panel: ReviewPanel,
    verifier_model: str,
    author_replies: Sequence[AuthorReply] = (),
    consumed_reply_keys: Collection[str] = (),
    consumed_comment_ids: Collection[str] = (),
) -> tuple[VerifiedFinding, ...]:
    """解析核实者裁决并强制与审查面板及候选清单 1:1 绑定（fail-closed）。"""
    if not isinstance(panel, ReviewPanel):
        raise ConvergenceError("panel 必须是 ReviewPanel")
    if not panel.require_verifier:
        raise ConvergenceError("panel.require_verifier=False 必须走 accept_quick_pass_findings，禁止调用 parse_verifier_output")
    model = _require_non_empty_str(verifier_model, "verifier_model")
    expected_verifier = _require_non_empty_str(panel.verifier_model, "panel.verifier_model")
    if model != expected_verifier:
        raise ConvergenceError(f"verifier_model={model!r} 与 panel.verifier_model={expected_verifier!r} 不一致")
    verifier_family = infer_model_family(model)

    if not isinstance(payload, Mapping):
        raise ConvergenceError("verifier 输出必须是对象")
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        raise ConvergenceError("verifier 输出缺少 verdicts 列表")

    candidates_by_id: dict[str, Finding] = {}
    ordered_ids: list[str] = []
    candidate_list: list[Finding] = []
    for candidate in candidate_findings:
        if not isinstance(candidate, Finding):
            raise ConvergenceError(f"candidate_findings 元素必须是 Finding：{candidate!r}")
        cid = candidate.finding_id
        if cid in candidates_by_id:
            raise ConvergenceError(f"candidate_findings 含重复指纹 {cid}，请先合并去重")

        real_models = _real_source_models(candidate.source_models)
        if not real_models:
            raise ConvergenceError(f"候选发现 {cid} 缺少真实 finder source_models，禁止绕过异家族核实校验")
        for src_model in real_models:
            src_family = infer_model_family(src_model)
            if src_family == verifier_family:
                raise ConvergenceError(
                    f"核实者模型 {model!r}（家族 {verifier_family}）不得与候选发现 {cid} 来源模型 {src_model!r} 同家族"
                )

        candidates_by_id[cid] = candidate
        ordered_ids.append(cid)
        candidate_list.append(candidate)

    bound_replies = bind_author_replies(
        candidate_list,
        author_replies,
        consumed_reply_keys=consumed_reply_keys,
        consumed_comment_ids=consumed_comment_ids,
    )

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
        matched_reply: AuthorReply | None = None
        if verdict == VerificationVerdict.RESOLVED_BY_WONTFIX:
            matched_reply = bound_replies.get(fid)
            if matched_reply is None:
                raise ConvergenceError(
                    f"发现 {fid} 裁决为 resolved_by_wontfix，但缺少唯一匹配且未消费的作者不修回复"
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
    resolved_fingerprints: frozenset[str] = frozenset()
    consumed_reply_keys: frozenset[str] = frozenset()

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
        unresolved_ids: set[str] = set()
        for item in self.unresolved_important:
            if not isinstance(item, Finding):
                raise ConvergenceError("unresolved_important 元素必须是 Finding")
            if item.severity != Severity.IMPORTANT:
                raise ConvergenceError(f"unresolved_important 仅允许 Important 发现，收到 {item.severity.value}")
            unresolved_ids.add(item.finding_id)
        if not isinstance(self.resolved_fingerprints, frozenset):
            raise ConvergenceError("resolved_fingerprints 必须是 frozenset[str]")
        for fp in self.resolved_fingerprints:
            _require_non_empty_str(fp, "resolved_fingerprints[]")
        if unresolved_ids & self.resolved_fingerprints:
            raise ConvergenceError("同一轮次内 unresolved_important 与 resolved_fingerprints 不得重叠")
        if self.posted_fingerprints & self.resolved_fingerprints:
            raise ConvergenceError("同一轮次内 posted_fingerprints 与 resolved_fingerprints 不得重叠")
        if not isinstance(self.consumed_reply_keys, frozenset):
            raise ConvergenceError("consumed_reply_keys 必须是 frozenset[str]")
        for rk in self.consumed_reply_keys:
            _require_non_empty_str(rk, "consumed_reply_keys[]")


@dataclass(frozen=True)
class RoundPlan:
    round_number: int
    review_scope: ReviewScope
    diff_base_sha: str
    diff_head_sha: str
    unresolved_prior_important: tuple[Finding, ...]
    author_replies: tuple[AuthorReply, ...]
    already_posted_fingerprints: frozenset[str]
    consumed_reply_keys: frozenset[str] = frozenset()
    exceeds_auto_rounds: bool = False


def _active_posted_fingerprints(history: Sequence[RoundHistoryEntry]) -> frozenset[str]:
    """回放历史轮次中仍处于活跃态的已贴指纹；已被解除的发现会移出，允许重新引入后再次贴出。"""
    active: set[str] = set()
    prev_unresolved: set[str] = set()
    for entry in history:
        current_unresolved = {f.finding_id for f in entry.unresolved_important}
        resolved_in_round = (prev_unresolved - current_unresolved) | set(entry.resolved_fingerprints)
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
            consumed_reply_keys=frozenset(),
            exceeds_auto_rounds=False,
        )

    prev = history[-1]
    round_number = prev.round_number + 1
    consumed_reply_keys: frozenset[str] = frozenset().union(*(entry.consumed_reply_keys for entry in history))
    active_replies = tuple(reply for reply in author_replies if reply.reply_key not in consumed_reply_keys)
    return RoundPlan(
        round_number=round_number,
        review_scope="incremental_diff",
        diff_base_sha=prev.head_sha,
        diff_head_sha=head,
        unresolved_prior_important=prev.unresolved_important,
        author_replies=active_replies,
        already_posted_fingerprints=_active_posted_fingerprints(history),
        consumed_reply_keys=consumed_reply_keys,
        exceeds_auto_rounds=round_number > MAX_AUTO_ROUNDS,
    )


def build_round_candidates(
    plan: RoundPlan,
    finder_batches: Sequence[tuple[str, Sequence[Finding]]],
) -> tuple[Finding, ...]:
    """合并本轮 finder 新发现与上一轮未解除的 Important 发现，完整保留原有真实 source_models。"""
    batches: list[tuple[str, Sequence[Finding]]] = list(finder_batches)
    if plan.unresolved_prior_important:
        prior_by_model: dict[str, list[Finding]] = {}
        for item in plan.unresolved_prior_important:
            real_models = _real_source_models(item.source_models)
            model_key = real_models[0] if real_models else _PRIOR_ROUND_PLACEHOLDER
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
    retained_posted_fingerprints: frozenset[str] = frozenset()
    resolved_fingerprints: frozenset[str] = frozenset()
    consumed_reply_keys: frozenset[str] = frozenset()

    def to_history_entry(
        self,
        head_sha: str,
        *,
        posted_in_comment: frozenset[str],
    ) -> RoundHistoryEntry:
        """基于实际出现在渲染评论中的指纹生成轮次历史，避免被截断的非阻断项永久漏贴。"""
        if not isinstance(posted_in_comment, frozenset):
            raise ConvergenceError("posted_in_comment 必须是 frozenset[str]")
        for fp in posted_in_comment:
            _require_non_empty_str(fp, "posted_in_comment[]")
        if posted_in_comment & self.resolved_fingerprints:
            raise ConvergenceError("posted_in_comment 不得包含本轮已解除的发现指纹")
        return RoundHistoryEntry(
            round_number=self.round_number,
            head_sha=_require_non_empty_str(head_sha, "head_sha"),
            posted_fingerprints=self.retained_posted_fingerprints | posted_in_comment,
            unresolved_important=self.unresolved_important,
            resolved_fingerprints=self.resolved_fingerprints,
            consumed_reply_keys=self.consumed_reply_keys,
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
    retained_posted = already_posted - resolved_ids
    postable = select_postable_findings(verified_tuple, already_posted, resolved_fingerprints=resolved_ids)
    next_posted = retained_posted | frozenset(vf.finding.finding_id for vf in postable)
    unresolved_important = tuple(vf.finding for vf in blocking)
    consumed_reply_keys = frozenset(
        vf.author_reply.reply_key
        for vf in resolved
        if vf.verdict == VerificationVerdict.RESOLVED_BY_WONTFIX and vf.author_reply is not None
    )

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
        retained_posted_fingerprints=retained_posted,
        resolved_fingerprints=resolved_ids,
        consumed_reply_keys=consumed_reply_keys,
    )


@dataclass(frozen=True)
class RenderedComment:
    body: str
    posted_fingerprints: frozenset[str]
    omitted_non_blocking_fingerprints: frozenset[str]
    truncated: bool


def parse_comment_marker(body: str) -> tuple[int, int, str] | None:
    first_line = body.splitlines()[0].strip() if body else ""
    match = _COMMENT_MARKER_RE.match(first_line)
    if not match:
        return None
    return int(match.group("pr")), int(match.group("round")), match.group("head")


def _format_location(finding: Finding) -> str:
    norm_file = _normalize_file(finding.file)
    return f"{norm_file}:{finding.line}" if finding.line is not None else norm_file


def _render_new_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_location(f)
    lines = [
        f"- `[{fid}]` `{loc}` — **{f.category}**",
        f"  - 失败场景：{f.failure_scenario}",
        f"  - 核实证据：{vf.verifier_evidence}",
    ]
    if f.class_scope:
        lines.append(f"  - 同类范围：{f.class_scope}")
    lines.append(f"  - 处置：请在新提交中修复，或回复 `[{fid}] 不修：<理由>`")
    return "\n".join(lines)


def _render_prior_blocking_summary(prior_blocking: Sequence[VerifiedFinding]) -> str:
    refs = "、".join(f"`[{vf.finding.finding_id}]` `{_format_location(vf.finding)}`" for vf in prior_blocking)
    return f"- 前轮已贴出且仍未解除：{refs}"


def _render_minimal_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    return f"- `[{f.finding_id}]` `{_format_location(f)}`"


def _render_compact_new_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_location(f)
    return f"- `[{fid}]` `{loc}` — {f.category}：{f.failure_scenario}（回复 `[{fid}] 不修：<理由>`）"


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


def _render_blocking_section_with_budget(
    header: str,
    blocking_findings: Sequence[VerifiedFinding],
    postable_ids: set[str],
    note: str,
    max_chars: int,
) -> str:
    """在保证全部阻断项最小清单完整落盘的前提下，将剩余预算分配给本轮新阻断项的说明文字。"""
    section_header = "### 阻断项（Important）\n\n"
    new_blocking = [vf for vf in blocking_findings if vf.finding.finding_id in postable_ids]
    prior_blocking = [vf for vf in blocking_findings if vf.finding.finding_id not in postable_ids]

    compact_lines = [_render_compact_new_blocking_item(vf) for vf in new_blocking]
    if prior_blocking:
        compact_lines.append(_render_prior_blocking_summary(prior_blocking))
    compact_text = f"{header}\n\n{section_header}" + "\n".join(compact_lines) + note
    if len(compact_text) <= max_chars:
        return compact_text

    minimal_lines = [_render_minimal_blocking_item(vf) for vf in blocking_findings]
    base_body = f"{header}\n\n{section_header}" + "\n".join(minimal_lines)
    extra_budget = max_chars - len(base_body) - len(note)
    for idx, vf in enumerate(blocking_findings):
        if extra_budget <= 0:
            break
        if vf.finding.finding_id not in postable_ids:
            continue
        f = vf.finding
        suffix = f" — {f.category}：{f.failure_scenario}"
        if len(suffix) <= extra_budget:
            minimal_lines[idx] += suffix
            extra_budget -= len(suffix)
        elif extra_budget >= 4:
            clipped = suffix[: extra_budget - 1].rstrip()
            if clipped:
                minimal_lines[idx] += f"{clipped}…"
            extra_budget = 0

    return f"{header}\n\n{section_header}" + "\n".join(minimal_lines) + note


def render_findings_comment(
    pr_number: int,
    head_sha: str,
    decision: RoundDecision,
    *,
    max_chars: int = 65536,
) -> RenderedComment:
    """渲染幂等 PR 审查评论：强制保留首行 marker、三级计数首行与全部阻断项最小清单，并精确回报实际贴出指纹。"""
    if type(pr_number) is not int or pr_number <= 0:
        raise ConvergenceError(f"pr_number 必须是正整数：{pr_number!r}")
    sha = _require_non_empty_str(head_sha, "head_sha")
    if not isinstance(decision, RoundDecision):
        raise ConvergenceError("decision 必须是 RoundDecision")
    if type(max_chars) is not int or max_chars <= 0:
        raise ConvergenceError(f"max_chars 必须是正整数：{max_chars!r}")

    marker = f"{COMMENT_MARKER_PREFIX} pr={pr_number} round={decision.round_number} head={sha} -->"

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
    blocking_ids = frozenset(vf.finding.finding_id for vf in decision.blocking_findings)

    blocking_section = ""
    if decision.blocking_findings:
        new_blocking = [vf for vf in decision.blocking_findings if vf.finding.finding_id in postable_ids]
        prior_blocking = [vf for vf in decision.blocking_findings if vf.finding.finding_id not in postable_ids]
        blocking_items = [_render_new_blocking_item(vf) for vf in new_blocking]
        if prior_blocking:
            blocking_items.append(_render_prior_blocking_summary(prior_blocking))
        blocking_section = "### 阻断项（Important）\n\n" + "\n".join(blocking_items)

    new_non_blocking = [vf for vf in decision.non_blocking_findings if vf.finding.finding_id in postable_ids]
    suppressed_nb_count = len(decision.non_blocking_findings) - len(new_non_blocking)
    rendered_nb_items = [(vf.finding.finding_id, _render_non_blocking_item(vf)) for vf in new_non_blocking]
    all_new_nb_ids = frozenset(fid for fid, _ in rendered_nb_items)

    non_blocking_section = ""
    if decision.non_blocking_findings:
        nb_lines: list[str] = ["### 非阻断项（Nit / Pre-existing）", ""]
        nb_lines.extend(text for _, text in rendered_nb_items)
        if suppressed_nb_count > 0:
            nb_lines.append(f"- 另有 {suppressed_nb_count} 项前轮已贴出的非阻断发现未重复列出。")
        non_blocking_section = "\n".join(nb_lines)

    disposition_lines: list[str] = []
    if decision.resolved_findings or decision.rejected_findings:
        for vf in decision.resolved_findings:
            label = "已修复" if vf.verdict == VerificationVerdict.RESOLVED_BY_FIX else "作者确认不修"
            reply_note = f"（理由：{vf.author_reply.reason}）" if vf.author_reply is not None else ""
            disposition_lines.append(
                f"- `[{vf.finding.finding_id}]` `{_format_location(vf.finding)}` — {label}{reply_note}：{vf.verifier_evidence}"
            )
        for vf in decision.rejected_findings:
            disposition_lines.append(
                f"- `[{vf.finding.finding_id}]` `{_format_location(vf.finding)}` — 核实驳回：{vf.verifier_evidence}"
            )
    disposition_section = (
        "### 已解除与核实驳回摘要\n\n" + "\n".join(disposition_lines) if disposition_lines else ""
    )

    full_parts = [header]
    if blocking_section:
        full_parts.append(blocking_section)
    if non_blocking_section:
        full_parts.append(non_blocking_section)
    if disposition_section:
        full_parts.append(disposition_section)
    full_text = "\n\n".join(full_parts)
    if len(full_text) <= max_chars:
        return RenderedComment(
            body=full_text,
            posted_fingerprints=blocking_ids | all_new_nb_ids,
            omitted_non_blocking_fingerprints=frozenset(),
            truncated=False,
        )

    truncation_note = "\n\n…（评论超长已截断，阻断项已优先保留）"
    short_note = "\n…（已截断）"
    base_full_blocking = f"{header}\n\n{blocking_section}" if blocking_section else header

    if len(base_full_blocking) + len(truncation_note) <= max_chars:
        parts = [base_full_blocking]
        current_len = len(base_full_blocking)
        limit_without_note = max_chars - len(truncation_note)

        included_nb_ids: set[str] = set()
        if decision.non_blocking_findings:
            nb_header = "### 非阻断项（Nit / Pre-existing）\n\n"
            chosen_nb_texts: list[str] = []
            for fid, item_text in rendered_nb_items:
                candidate_nb = nb_header + "\n".join([*chosen_nb_texts, item_text])
                if current_len + 2 + len(candidate_nb) <= limit_without_note:
                    chosen_nb_texts.append(item_text)
                    included_nb_ids.add(fid)
                else:
                    break
            if suppressed_nb_count > 0:
                suppressed_line = f"- 另有 {suppressed_nb_count} 项前轮已贴出的非阻断发现未重复列出。"
                candidate_nb = nb_header + "\n".join([*chosen_nb_texts, suppressed_line])
                if current_len + 2 + len(candidate_nb) <= limit_without_note:
                    chosen_nb_texts.append(suppressed_line)
            if chosen_nb_texts:
                nb_block = nb_header + "\n".join(chosen_nb_texts)
                parts.append(nb_block)
                current_len += 2 + len(nb_block)

        if disposition_lines:
            disp_header = "### 已解除与核实驳回摘要\n\n"
            chosen_disp: list[str] = []
            for line in disposition_lines:
                candidate_disp = disp_header + "\n".join([*chosen_disp, line])
                if current_len + 2 + len(candidate_disp) <= limit_without_note:
                    chosen_disp.append(line)
                else:
                    break
            if chosen_disp:
                disp_block = disp_header + "\n".join(chosen_disp)
                parts.append(disp_block)

        body = "\n\n".join(parts) + truncation_note
        omitted_nb = all_new_nb_ids - included_nb_ids
        return RenderedComment(
            body=body,
            posted_fingerprints=blocking_ids | frozenset(included_nb_ids),
            omitted_non_blocking_fingerprints=omitted_nb,
            truncated=True,
        )

    # 阻断项展开版本身超长时，强制保证 header + 全部阻断项最小清单完整落盘，绝不静默丢弃任一阻断项
    if decision.blocking_findings:
        minimal_blocking_section = "### 阻断项（Important）\n\n" + "\n".join(
            _render_minimal_blocking_item(vf) for vf in decision.blocking_findings
        )
        mandatory_base = f"{header}\n\n{minimal_blocking_section}"
    else:
        mandatory_base = header

    if len(mandatory_base) > max_chars:
        raise ConvergenceError(
            f"max_chars={max_chars} 过小，无法容纳评论头与全部 {len(decision.blocking_findings)} 项阻断发现的最小清单"
            f"（至少需 {len(mandatory_base)} 字符）"
        )

    if len(mandatory_base) + len(truncation_note) <= max_chars:
        note = truncation_note
    elif len(mandatory_base) + len(short_note) <= max_chars:
        note = short_note
    else:
        note = ""

    if decision.blocking_findings:
        body = _render_blocking_section_with_budget(
            header,
            decision.blocking_findings,
            postable_ids,
            note,
            max_chars,
        )
    else:
        body = f"{header}{note}"

    return RenderedComment(
        body=body,
        posted_fingerprints=blocking_ids,
        omitted_non_blocking_fingerprints=all_new_nb_ids,
        truncated=True,
    )
