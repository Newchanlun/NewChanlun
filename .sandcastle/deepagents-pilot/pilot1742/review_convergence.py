"""审查发现分级、异家族核实、作者回复解析、多轮收敛与幂等评论渲染（#1927 / #1928）。

本模块为纯数据与判定内核，不依赖外部 IO，也不修改既有审查执行链。
所有外部边界（模型输出、评论文本、面板配置、轮次历史）均按 fail-closed 校验。
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Literal

MAX_AUTO_ROUNDS = 3
NON_CONVERGENT_DESCRIPTION = "已 3 轮未收敛，请重新考虑方案"
COMMENT_MARKER_PREFIX = "<!-- deepagents:review-findings"
_PRIOR_ROUND_PLACEHOLDER = "prior-round"

ReviewScope = Literal["full_pr", "incremental_diff"]
GitHubStatusState = Literal["success", "failure"]


class RoundOutcome(str, Enum):
    PASS = "pass"
    BLOCKED = "blocked"
    NON_CONVERGENT = "non_convergent"


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


_VERDICT_VALUES: dict[str, VerificationVerdict] = {
    **{v.value: v for v in VerificationVerdict},
    "false_positive": VerificationVerdict.REJECTED,
}

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
    r"^<!--\s*deepagents:review-findings\s+pr=(?P<pr>[1-9][0-9]*)\s+round=(?P<round>[1-9][0-9]*)\s+head=(?P<head>[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\s*-->$"
)

_FENCE_OPEN_BACKTICK_BODY_RE = re.compile(r"^(`{3,})[^`]*$")
_FENCE_OPEN_TILDE_BODY_RE = re.compile(r"^(~{3,}).*$")
_ATX_HEADING_BODY_RE = re.compile(r"^#{1,6}(?:[ \t]|$)")
_SETEXT_UNDERLINE_BODY_RE = re.compile(r"^(?:=+|-+)[ \t]*$")
_THEMATIC_BREAK_BODY_RE = re.compile(r"^(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$")
_LIST_ITEM_MARKER_BODY_RE = re.compile(r"^(?:(?P<bullet>[-*+])|(?P<num>[0-9]{1,9})[.)])(?=[ \t]|$)")
_GFM_TABLE_DELIM_CELL_RE = re.compile(r"^:?-+:?$")
_HTML_BLOCK_1_START_RE = re.compile(r"^<(?:pre|script|style|textarea)(?:[ \t>]|$)", re.IGNORECASE)
_HTML_BLOCK_1_END_RE = re.compile(r"</(?:pre|script|style|textarea)>", re.IGNORECASE)
_HTML_BLOCK_4_START_RE = re.compile(r"^<![A-Za-z]")
_HTML_BLOCK_6_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|"
    "dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|"
    "h1|h2|h3|h4|h5|h6|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|"
    "noframes|ol|optgroup|option|p|param|search|section|summary|table|tbody|td|tfoot|th|"
    "thead|title|tr|track|ul"
)
_HTML_BLOCK_6_START_RE = re.compile(
    rf"^</?(?:{_HTML_BLOCK_6_TAGS})(?:[ \t>]|/>|$)",
    re.IGNORECASE,
)
_HTML_OPEN_TAG_PATTERN = (
    r"<[A-Za-z][A-Za-z0-9-]*"
    r"(?:[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*(?:[ \t]*=[ \t]*(?:[^ \t\n\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*"
    r"[ \t]*/?>"
)
_HTML_CLOSE_TAG_PATTERN = r"</[A-Za-z][A-Za-z0-9-]*[ \t]*>"
_HTML_BLOCK_7_START_RE = re.compile(rf"^(?:{_HTML_OPEN_TAG_PATTERN}|{_HTML_CLOSE_TAG_PATTERN})[ \t]*$")

_COMMONMARK_LINE_ENDING_RE = re.compile(r"\r\n|\n|\r")
_ASCII_PUNCTUATION = frozenset(r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~""")
_AUTOLINK_URI_RE = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]{1,31}:[^\x00-\x20<>]*>")
_AUTOLINK_EMAIL_RE = re.compile(
    r"<[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*>"
)
_INLINE_HTML_OPEN_TAG_PATTERN = (
    r"<[A-Za-z][A-Za-z0-9-]*"
    r"(?:[ \t\n]+[A-Za-z_:][A-Za-z0-9_.:-]*(?:[ \t\n]*=[ \t\n]*(?:[^ \t\n\"'=<>`]+|'[^']*'|\"[^\"]*\"))?)*"
    r"[ \t\n]*/?>"
)
_INLINE_HTML_CLOSE_TAG_PATTERN = r"</[A-Za-z][A-Za-z0-9-]*[ \t\n]*>"
_INLINE_RAW_HTML_RE = re.compile(
    rf"(?:<!--(?:>|->|.*?-->)|<\?.*?\?>|<![A-Za-z][^>]*>|<!\[CDATA\[.*?\]\]>|"
    rf"{_INLINE_HTML_CLOSE_TAG_PATTERN}|{_INLINE_HTML_OPEN_TAG_PATTERN})",
    re.DOTALL,
)
_INLINE_HTML_OPEN_NAME_RE = re.compile(r"^<([A-Za-z][A-Za-z0-9-]*)")
_INLINE_HTML_CLOSE_NAME_RE = re.compile(r"^</([A-Za-z][A-Za-z0-9-]*)[ \t\n]*>$")
_SUPPRESSED_INLINE_HTML_TAGS = frozenset(
    {
        "code",
        "pre",
        "kbd",
        "samp",
        "var",
        "head",
        "script",
        "style",
        "textarea",
        "title",
        "template",
        "noscript",
        "blockquote",
        "q",
    }
)
_RAW_TEXT_HTML_TAGS = frozenset({"script", "style", "textarea", "title"})
_SILENT_INLINE_HTML_TAGS = frozenset({"head", "script", "style", "textarea", "title", "template", "noscript"})
_RAW_HTML_START_RE = re.compile(r"<(?:!--|\?|!|/?[A-Za-z])")
_RAW_TEXT_CLOSE_RES: dict[str, re.Pattern[str]] = {
    tag: re.compile(rf"</{tag}[ \t\n]*>", re.IGNORECASE) for tag in _RAW_TEXT_HTML_TAGS
}
_COMMONMARK_ENTITY_RE = re.compile(
    r"&(?:#[0-9]{1,7}|#[Xx][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});"
)
_INVISIBLE_STRIP_CATEGORIES = frozenset({"Cf", "Cc", "Cs", "Zl", "Zp"})
_INVISIBLE_CHECK_CATEGORIES = frozenset({"Cf", "Cc", "Cs", "Cn", "Co", "Zl", "Zp", "Zs", "Mn", "Me", "Mc"})
_DEFAULT_IGNORABLE_OR_BLANK_CODE_POINTS = frozenset(
    {
        0x00AD,
        0x034F,
        0x061C,
        0x115F,
        0x1160,
        0x2800,
        0x3164,
        0xFEFF,
        0xFFA0,
    }
)
_DEFAULT_IGNORABLE_OR_BLANK_RANGES: tuple[tuple[int, int], ...] = (
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x206F),
    (0xFE00, 0xFE0F),
    (0xFFF0, 0xFFF8),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
_CONSUMED_FINDING_HEX_RE = re.compile(r"[0-9a-f]{6,16}")
_CONSUMED_DIGEST_HEX_RE = re.compile(r"[0-9a-f]{16}")
_CONSUMED_POS_INT_RE = re.compile(r"[1-9][0-9]*")

_WONTFIX_HEAD_RE = re.compile(
    r"^(?:(?:[-*+]|[0-9]+[.)])[ \t]+)?"
    r"(?:"
    r"`?\[(?P<id_bracket>[0-9a-fA-F]{6,16})\]`?[ \t]*不修"
    r"|`?(?P<id_bare>[0-9a-fA-F]{8,16})`?[ \t]+不修"
    r"|不修[ \t]*[（(\[][ \t]*(?P<id_paren>[0-9a-fA-F]{6,16})[ \t]*[）)\]]"
    r"|不修[ \t]*[（(][ \t]*(?P<path_paren>[^\s:：()（）]+?)(?::(?P<line_paren>[1-9][0-9]*))?[ \t]*[）)]"
    r"|`?(?P<path_prefix>(?:\./)?[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*\.[A-Za-z0-9_+-]+)(?::(?P<line_prefix>[1-9][0-9]*))?`?[ \t]+不修"
    r"|不修"
    r")[ \t]*[:：][ \t]*(?P<reason>.*)$"
)


_COMMIT_SHA_HEX_RE = re.compile(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}")


def _require_non_empty_str(raw: Any, field_name: str) -> str:
    if not isinstance(raw, str):
        raise ConvergenceError(f"{field_name} 必须是非空字符串：{raw!r}")
    text = raw.strip()
    if not text:
        raise ConvergenceError(f"{field_name} 不能为空")
    return text


def _require_visible_text(raw: Any, field_name: str) -> str:
    """要求字段为非空字符串且至少包含 1 个可见基字符（封堵 U+3164/零宽/控制/变体选择符等不可见占位文本）。"""
    text = _require_non_empty_str(raw, field_name)
    if not any(not _is_invisible_or_ignorable_char(ch) for ch in text):
        raise ConvergenceError(f"{field_name} 不能仅包含空白或不可见/可忽略字符：{raw!r}")
    return text


def _require_visible_markdown_text(raw: Any, field_name: str) -> str:
    """要求字段在 GFM 渲染后至少包含 1 个可见基字符（保留原始前导缩进，避免破坏 4 空格/Tab 缩进代码块语义）。"""
    _require_visible_text(raw, field_name)
    assert isinstance(raw, str)
    if _has_visible_gfm_text(raw):
        return raw
    raise ConvergenceError(f"{field_name} 在 Markdown/GFM 渲染后不包含任何可见字符：{raw!r}")


def _normalize_commit_sha(raw: Any, field_name: str) -> str:
    value = _require_non_empty_str(raw, field_name)
    if not _COMMIT_SHA_HEX_RE.fullmatch(value):
        raise ConvergenceError(
            f"{field_name} 必须是完整的 40 位（SHA-1）或 64 位（SHA-256）十六进制 Git 提交 SHA：{raw!r}"
        )
    return value.lower()


def _normalize_file(raw: Any) -> str:
    text = _require_visible_text(raw, "file").replace("\\", "/")
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


def _normalize_inline_fingerprint_text(chunk: str) -> str:
    """在单段/块内归一化指纹文本：保留 CommonMark §6.1 行内代码的大小写与内部水平空格，仅对普通叙述折叠空白并转小写。"""
    out: list[str] = []
    for seg_kind, seg_raw in _tokenize_inline_clip_segments(chunk):
        if seg_kind == "code":
            k = 0
            while k < len(seg_raw) and seg_raw[k] == "`":
                k += 1
            inner = _COMMONMARK_LINE_ENDING_RE.sub("\n", seg_raw[k : len(seg_raw) - k])
            out.append(_wrap_markdown_code_span(_extract_code_span_text(inner)))
        else:
            out.append(re.sub(r"\s+", " ", seg_raw).lower())
    return "".join(out).strip()


def _normalize_fingerprint_text(raw: Any, field_name: str) -> str:
    text = _require_non_empty_str(raw, field_name)
    assert isinstance(raw, str)
    doc_blocks, _ = _parse_commonmark_blocks(raw, include_all_visible_blocks=True)
    if not doc_blocks:
        return _normalize_inline_fingerprint_text(text)

    parts: list[str] = []
    for kind, block_text in doc_blocks:
        if kind == "code":
            code_lines = _split_commonmark_lines(block_text)
            while code_lines and not code_lines[0].strip(" \t"):
                code_lines.pop(0)
            while code_lines and not code_lines[-1].strip(" \t"):
                code_lines.pop()
            code_body = "\n".join(code_lines)
            parts.append(f"\x00code\x00{code_body}\x00")
        else:
            norm_block = _normalize_inline_fingerprint_text(block_text)
            if norm_block:
                parts.append(norm_block)
    if not parts:
        return _normalize_inline_fingerprint_text(text)
    return " ".join(parts)


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


def _parse_consumed_reply_key(raw: Any, field_name: str) -> tuple[str, str, str]:
    """严格解析并校验规范回复键，返回 (comment_id, kind, payload)；拒绝任何非 4 种规范格式的键。"""
    if not isinstance(raw, str):
        raise ConvergenceError(f"{field_name} 必须是非空字符串：{raw!r}")
    if not raw or raw != raw.strip():
        raise ConvergenceError(f"{field_name} 不得为空或含首尾空白：{raw!r}")
    if not raw.startswith("comment:"):
        raise ConvergenceError(
            f"{field_name} 必须以小写 'comment:' 开头并符合 4 种规范回复键格式之一：{raw!r}"
        )
    rest = raw[len("comment:") :]
    parts = rest.split(":", 2)
    if len(parts) != 3:
        raise ConvergenceError(f"{field_name} 格式非法：{raw!r}")
    cid, kind, payload = parts
    if not cid or cid != cid.strip() or any(_is_invisible_or_ignorable_char(ch) for ch in cid):
        raise ConvergenceError(f"{field_name} 中的评论 ID 非法（不得为空或含空白/不可见字符）：{raw!r}")
    if kind == "finding":
        if not _CONSUMED_FINDING_HEX_RE.fullmatch(payload):
            raise ConvergenceError(f"{field_name} 的 finding 指纹必须是 6–16 位小写十六进制：{raw!r}")
    elif kind in ("inline", "resolved"):
        if not _CONSUMED_DIGEST_HEX_RE.fullmatch(payload):
            raise ConvergenceError(f"{field_name} 的 {kind} 指纹/摘要必须是 16 位小写十六进制：{raw!r}")
    elif kind == "loc":
        if not payload or payload != payload.strip():
            raise ConvergenceError(f"{field_name} 的 loc 坐标非法：{raw!r}")
        if ":" in payload:
            file_part, line_part = payload.rsplit(":", 1)
            if ":" in file_part or not _CONSUMED_POS_INT_RE.fullmatch(line_part):
                raise ConvergenceError(f"{field_name} 的 loc 行号或路径格式非法：{raw!r}")
        else:
            file_part = payload
        if not file_part or file_part != file_part.strip():
            raise ConvergenceError(f"{field_name} 的 loc 路径含空白或为空：{raw!r}")
        try:
            norm_file = _normalize_file(file_part)
        except ConvergenceError as exc:
            raise ConvergenceError(f"{field_name} 的 loc 路径非法：{raw!r}") from exc
        if norm_file != file_part:
            raise ConvergenceError(
                f"{field_name} 的 loc 路径必须为规范形式（期望 {norm_file!r}）：{raw!r}"
            )
    else:
        raise ConvergenceError(f"{field_name} 包含未知回复键类型 {kind!r}：{raw!r}")
    return cid, kind, payload


def _validate_consumed_reply_key(raw: Any, field_name: str) -> str:
    """严格校验已消费回复键必须匹配 4 种规范格式之一。"""
    _parse_consumed_reply_key(raw, field_name)
    assert isinstance(raw, str)
    return raw


def _validate_consumed_reply_keys(values: Collection[str], field_name: str) -> frozenset[str]:
    if not isinstance(values, Collection) or isinstance(values, (str, bytes)):
        raise ConvergenceError(f"{field_name} 必须是字符串集合：{values!r}")
    return frozenset(_validate_consumed_reply_key(item, f"{field_name}[]") for item in values)


def _normalize_bound_reply_targets(
    values: Mapping[str, str] | Collection[tuple[str, str]],
    field_name: str,
) -> dict[str, str]:
    """严格校验坐标/行内回复目标锁定集合，禁止非 loc/inline 键、非法指纹或同一键绑定到不同目标。"""
    if isinstance(values, Mapping):
        items: Collection[Any] = tuple(values.items())
    elif isinstance(values, Collection) and not isinstance(values, (str, bytes)):
        items = values
    else:
        raise ConvergenceError(f"{field_name} 必须是 (reply_key, target_finding_id) 集合或映射：{values!r}")

    mapping: dict[str, str] = {}
    for item in items:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ConvergenceError(f"{field_name}[] 必须是长度为 2 的 (reply_key, target_finding_id) 元组：{item!r}")
        raw_key, raw_target = item
        _, kind, _ = _parse_consumed_reply_key(raw_key, f"{field_name}[][0]")
        assert isinstance(raw_key, str)
        if kind not in ("loc", "inline"):
            raise ConvergenceError(f"{field_name} 仅允许锁定 loc 或 inline 回复键，收到 {kind!r}：{raw_key!r}")
        if not isinstance(raw_target, str) or not _CONSUMED_DIGEST_HEX_RE.fullmatch(raw_target):
            raise ConvergenceError(f"{field_name} 的 target_finding_id 必须是 16 位小写十六进制指纹：{raw_target!r}")
        existing = mapping.get(raw_key)
        if existing is not None and existing != raw_target:
            raise ConvergenceError(
                f"{field_name} 中回复键 {raw_key!r} 冲突绑定到多个目标指纹：{existing!r} vs {raw_target!r}"
            )
        mapping[raw_key] = raw_target
    return mapping


def _validate_bound_reply_targets_frozenset(values: Any, field_name: str) -> dict[str, str]:
    if not isinstance(values, frozenset):
        raise ConvergenceError(f"{field_name} 必须是 frozenset[tuple[str, str]]")
    return _normalize_bound_reply_targets(values, field_name)


def _merge_bound_reply_targets(base: dict[str, str], incoming: Mapping[str, str], context: str) -> None:
    for rk, target_fid in incoming.items():
        existing = base.get(rk)
        if existing is not None and existing != target_fid:
            raise ConvergenceError(
                f"{context}：回复键 {rk!r} 已锁定到发现 {existing!r}，禁止改绑到不同指纹 {target_fid!r}"
            )
        base[rk] = target_fid


def _collect_history_bound_targets(history: Sequence[RoundHistoryEntry]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for idx, entry in enumerate(history):
        entry_targets = _validate_bound_reply_targets_frozenset(
            entry.bound_reply_targets,
            f"history[{idx}].bound_reply_targets",
        )
        _merge_bound_reply_targets(merged, entry_targets, f"history[{idx}].bound_reply_targets")
    return merged


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
        _require_visible_text(self.category, "category")
        _require_visible_markdown_text(self.failure_scenario, "failure_scenario")
        _require_visible_markdown_text(self.evidence, "evidence")
        if self.class_scope is not None:
            _require_visible_text(self.class_scope, "class_scope")
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
        category = _require_visible_text(item.get("category"), f"findings[{idx}].category")
        failure_scenario = _require_visible_markdown_text(
            item.get("failure_scenario"), f"findings[{idx}].failure_scenario"
        )
        evidence = _require_visible_markdown_text(item.get("evidence"), f"findings[{idx}].evidence")
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


def _pick_best_markdown_text(values: Sequence[str]) -> str:
    """在保留原始 Markdown 前导缩进语义的前提下确定性择优。"""
    return min(values, key=lambda s: (-len(s.strip()), s))


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
    failure_scenario = _pick_best_markdown_text([f.failure_scenario for f in top_members])
    evidence = _pick_best_markdown_text([f.evidence for f in group])
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
    """识别模型所属家族；未知模型或同时命中多个家族均 fail-closed 拒绝，避免伪异家族绕过独立核实。"""
    normalized = _require_non_empty_str(model, "model").lower()
    matched_families = {family for family, pattern in _MODEL_FAMILY_PATTERNS if pattern.search(normalized)}
    if len(matched_families) > 1:
        raise ConvergenceError(
            f"模型名 {model!r} 同时命中多个模型家族 {sorted(matched_families)!r}，无法判定独立跨家族核实"
        )
    if len(matched_families) == 1:
        return next(iter(matched_families))
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


def _resolved_reply_key(comment_id: str, finding_fingerprint: str) -> str:
    cid = _require_non_empty_str(comment_id, "comment_id")
    fp = _require_non_empty_str(finding_fingerprint, "finding_fingerprint").lower()
    return f"comment:{cid}:resolved:{fp}"


@dataclass(frozen=True)
class AuthorReply:
    finding_id: str | None
    file: str | None
    line: int | None
    reason: str
    comment_id: str
    author: str
    is_inline_anchor: bool = False

    def __post_init__(self) -> None:
        if type(self.is_inline_anchor) is not bool:
            raise ConvergenceError(f"AuthorReply.is_inline_anchor 必须是 bool：{self.is_inline_anchor!r}")
        if self.finding_id is not None:
            if self.is_inline_anchor:
                raise ConvergenceError("AuthorReply 含显式 finding_id 时不得标记为 is_inline_anchor=True")
            fid = _require_non_empty_str(self.finding_id, "finding_id").lower()
            if not re.fullmatch(r"[0-9a-f]{6,16}", fid):
                raise ConvergenceError(f"AuthorReply.finding_id 格式非法：{self.finding_id!r}")
        if self.file is not None:
            _normalize_file(self.file)
        _normalize_line(self.line)
        _require_non_empty_str(self.reason, "reason")
        if not _clean_display_reason(self.reason):
            raise ConvergenceError("AuthorReply.reason 不能为空或仅含空白/不可见字符")
        _require_non_empty_str(self.comment_id, "comment_id")
        norm_author = _require_non_empty_str(self.author, "author")
        object.__setattr__(self, "author", norm_author)

    @property
    def target_finding_id(self) -> str | None:
        return self.finding_id.strip().lower() if self.finding_id is not None else None

    @property
    def reply_key(self) -> str:
        """按三类锚定形态构造顺序无关的稳定消费键：显式 ID / 显式坐标 / 纯行内回复。"""
        cid = self.comment_id.strip()
        if self.finding_id is not None:
            norm_id = self.finding_id.strip().lower()
            return f"comment:{cid}:finding:{norm_id}"
        if not self.is_inline_anchor and self.file is not None:
            norm_file = _normalize_file(self.file)
            if self.line is not None:
                return f"comment:{cid}:loc:{norm_file}:{self.line}"
            return f"comment:{cid}:loc:{norm_file}"
        norm_reason = _normalize_fingerprint_text(self.reason, "reason")
        digest = hashlib.sha256(norm_reason.encode("utf-8")).hexdigest()[:16]
        return f"comment:{cid}:inline:{digest}"


def _extract_comment_id(comment: Mapping[str, Any]) -> str | None:
    raw = comment.get("comment_id") if "comment_id" in comment else comment.get("id")
    if raw is None:
        return None
    if type(raw) is int:
        return str(raw) if raw > 0 else None
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
    # 仅使用当前 HEAD 新侧（RIGHT）上的现行 line；LEFT 或非法 side 严禁绑定新侧发现，line is None 时严禁回退 original_line
    side = comment.get("side")
    start_side = comment.get("start_side")
    side_allowed = True
    if side is not None:
        side_allowed = isinstance(side, str) and side.strip().upper() == "RIGHT"
    elif start_side is not None:
        side_allowed = isinstance(start_side, str) and start_side.strip().upper() == "RIGHT"
    raw_line = comment.get("line") if side_allowed else None
    line: int | None = raw_line if type(raw_line) is int and raw_line > 0 else None
    return file_path, line


class _LineCursor:
    """按 CommonMark §2.2 4 列制表位精确追踪行内位置、虚拟列与半展开 Tab。"""

    __slots__ = ("line", "pos", "col", "partial")

    def __init__(self, line: str) -> None:
        self.line = line
        self.pos = 0
        self.col = 0
        self.partial = 0

    def save(self) -> tuple[int, int, int]:
        return (self.pos, self.col, self.partial)

    def restore(self, state: tuple[int, int, int]) -> None:
        self.pos, self.col, self.partial = state

    def indent_ahead(self) -> int:
        cols = self.partial
        col = self.col + self.partial
        pos = self.pos
        line = self.line
        n = len(line)
        while pos < n:
            ch = line[pos]
            if ch == " ":
                cols += 1
                col += 1
                pos += 1
            elif ch == "\t":
                step = 4 - (col % 4)
                cols += step
                col += step
                pos += 1
            else:
                break
        return cols

    def is_blank(self) -> bool:
        pos = self.pos
        line = self.line
        n = len(line)
        while pos < n:
            if line[pos] not in (" ", "\t"):
                return False
            pos += 1
        return True

    def advance_cols(self, count: int) -> int:
        consumed = 0
        line = self.line
        n = len(line)
        while consumed < count:
            if self.partial > 0:
                take = min(self.partial, count - consumed)
                self.partial -= take
                self.col += take
                consumed += take
            elif self.pos < n:
                ch = line[self.pos]
                if ch == " ":
                    self.pos += 1
                    self.col += 1
                    consumed += 1
                elif ch == "\t":
                    step = 4 - (self.col % 4)
                    self.pos += 1
                    need = count - consumed
                    if step <= need:
                        self.col += step
                        consumed += step
                    else:
                        self.col += need
                        self.partial = step - need
                        consumed += need
                else:
                    break
            else:
                break
        return consumed

    def peek_char(self) -> str:
        if self.partial > 0:
            return " "
        if self.pos < len(self.line):
            return self.line[self.pos]
        return ""

    def advance_chars(self, count: int) -> None:
        self.pos += count
        self.col += count

    def rest_text(self) -> str:
        if self.partial > 0:
            return (" " * self.partial) + self.line[self.pos :]
        return self.line[self.pos :]


@dataclass
class _BlockQuote:
    pass


@dataclass
class _ListItem:
    padding: int
    has_content: bool = False


@dataclass
class _FencedCode:
    fence_char: str
    fence_len: int
    lines: list[str] = field(default_factory=list)


@dataclass
class _IndentedCode:
    lines: list[str] = field(default_factory=list)


@dataclass
class _HTMLBlock:
    kind: int
    lines: list[str]


@dataclass
class _Paragraph:
    lines: list[str]


@dataclass
class _Table:
    header_cells: tuple[str, ...]
    body_rows: list[tuple[str, ...]] = field(default_factory=list)


_Container = _BlockQuote | _ListItem
_Leaf = _FencedCode | _IndentedCode | _HTMLBlock | _Paragraph | _Table


def _match_html_block_start(rest: str, *, allow_type7: bool) -> int | None:
    if not rest.startswith("<"):
        return None
    if _HTML_BLOCK_1_START_RE.match(rest):
        return 1
    if rest.startswith("<!--"):
        return 2
    if rest.startswith("<?"):
        return 3
    if _HTML_BLOCK_4_START_RE.match(rest):
        return 4
    if rest.startswith("<![CDATA["):
        return 5
    if _HTML_BLOCK_6_START_RE.match(rest):
        return 6
    if allow_type7 and _HTML_BLOCK_7_START_RE.match(rest):
        return 7
    return None


def _is_html_block_end(kind: int, text: str, *, is_opening_line: bool = False) -> bool:
    if kind == 1:
        return bool(_HTML_BLOCK_1_END_RE.search(text))
    if kind == 2:
        haystack = text[4:] if is_opening_line and text.startswith("<!--") else text
        return "-->" in haystack
    if kind == 3:
        haystack = text[2:] if is_opening_line and text.startswith("<?") else text
        return "?>" in haystack
    if kind == 4:
        haystack = text[2:] if is_opening_line and text.startswith("<!") else text
        return ">" in haystack
    if kind == 5:
        haystack = text[9:] if is_opening_line and text.startswith("<![CDATA[") else text
        return "]]>" in haystack
    return False


def _split_commonmark_lines(text: str) -> list[str]:
    """按 CommonMark §2.1 / §2.3 规则切分行：将 NUL 替换为 U+FFFD，且仅以 CRLF/LF/CR 断行。"""
    if not text:
        return []
    normalized = text.replace("\x00", "\ufffd")
    lines = _COMMONMARK_LINE_ENDING_RE.split(normalized)
    if normalized.endswith(("\r\n", "\n", "\r")):
        lines.pop()
    return lines


def _normalize_link_label(raw_label: str) -> str:
    return re.sub(r"[ \t\n]+", " ", raw_label.strip(" \t\n")).casefold()


def _skip_ws_at_most_one_nl(text: str, pos: int) -> tuple[int, bool]:
    n = len(text)
    i = pos
    while i < n and text[i] in (" ", "\t"):
        i += 1
    saw_nl = False
    if i < n and text[i] == "\n":
        saw_nl = True
        i += 1
        while i < n and text[i] in (" ", "\t"):
            i += 1
    return i, saw_nl


def _parse_link_destination(text: str, pos: int) -> int | None:
    n = len(text)
    if pos >= n:
        return None
    if text[pos] == "<":
        i = pos + 1
        while i < n:
            ch = text[i]
            if ch in ("\n", "<"):
                return None
            if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                i += 2
                continue
            if ch == ">":
                return i + 1
            i += 1
        return None

    i = pos
    depth = 0
    while i < n:
        ch = text[i]
        if ch == " " or ord(ch) <= 0x1F or ord(ch) == 0x7F:
            break
        if ch == "\\":
            if i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                i += 2
                continue
            i += 1
            continue
        if ch == "(":
            depth += 1
            if depth > 32:
                return None
            i += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
            i += 1
        else:
            i += 1
    if i == pos or depth != 0:
        return None
    return i


def _parse_link_title(text: str, pos: int) -> int | None:
    n = len(text)
    if pos >= n:
        return None
    opener = text[pos]
    if opener == '"':
        closer = '"'
    elif opener == "'":
        closer = "'"
    elif opener == "(":
        closer = ")"
    else:
        return None
    i = pos + 1
    while i < n:
        ch = text[i]
        if ch == "\\":
            if i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                i += 2
                continue
            i += 1
            continue
        if ch == closer:
            return i + 1
        if opener == "(" and ch == "(":
            return None
        i += 1
    return None


def _consume_line_end(text: str, pos: int) -> int | None:
    n = len(text)
    i = pos
    while i < n and text[i] in (" ", "\t"):
        i += 1
    if i == n:
        return n
    if text[i] == "\n":
        return i + 1
    return None


def _match_link_label_brackets(text: str, pos: int) -> tuple[int, str] | None:
    n = len(text)
    if pos >= n or text[pos] != "[":
        return None
    i = pos + 1
    label_start = i
    label_len = 0
    has_non_ws = False
    while i < n:
        ch = text[i]
        if ch == "]":
            break
        if ch == "[":
            return None
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
            label_len += 2
            has_non_ws = True
            i += 2
        else:
            if ch not in (" ", "\t", "\n"):
                has_non_ws = True
            label_len += 1
            i += 1
        if label_len > 999:
            return None
    if i >= n or text[i] != "]" or label_len == 0 or not has_non_ws:
        return None
    return i + 1, _normalize_link_label(text[label_start:i])


def _match_single_link_ref_def(text: str, start: int) -> tuple[int, str] | None:
    n = len(text)
    i = start
    spaces = 0
    while i < n and text[i] == " " and spaces < 3:
        i += 1
        spaces += 1
    label_match = _match_link_label_brackets(text, i)
    if label_match is None:
        return None
    i, norm_label = label_match
    if i >= n or text[i] != ":":
        return None
    i += 1
    i, _ = _skip_ws_at_most_one_nl(text, i)
    dest_end = _parse_link_destination(text, i)
    if dest_end is None:
        return None

    no_title_eol = _consume_line_end(text, dest_end)
    ws_end, _ = _skip_ws_at_most_one_nl(text, dest_end)
    if ws_end > dest_end:
        title_end = _parse_link_title(text, ws_end)
        if title_end is not None:
            after_title_eol = _consume_line_end(text, title_end)
            if after_title_eol is not None:
                return after_title_eol, norm_label
    if no_title_eol is not None:
        return no_title_eol, norm_label
    return None


def _strip_leading_link_ref_defs(
    paragraph_text: str,
    defined_labels: set[str] | None = None,
) -> str:
    """按 CommonMark §4.7 剥离段落开头的全部合法链接引用定义，并记录定义标签。"""
    pos = 0
    n = len(paragraph_text)
    while pos < n:
        matched = _match_single_link_ref_def(paragraph_text, pos)
        if matched is None:
            break
        next_pos, norm_label = matched
        if defined_labels is not None:
            defined_labels.add(norm_label)
        pos = next_pos
    return paragraph_text[pos:]


def _find_code_span_end(text: str, start: int) -> tuple[int, int]:
    """返回 (tick_end, found_end)；未闭合时 found_end 为 -1。"""
    n = len(text)
    tick_end = start
    while tick_end < n and text[tick_end] == "`":
        tick_end += 1
    tick_len = tick_end - start
    j = tick_end
    while j < n:
        if text[j] == "`":
            run_start = j
            while j < n and text[j] == "`":
                j += 1
            if j - run_start == tick_len:
                return tick_end, j
        else:
            j += 1
    return tick_end, -1


def _match_inline_link_dest_title(text: str, pos: int) -> int | None:
    n = len(text)
    if pos >= n or text[pos] != "(":
        return None
    i = pos + 1
    while i < n and text[i] in (" ", "\t", "\n"):
        i += 1
    if i < n and text[i] == ")":
        return i + 1
    dest_end = _parse_link_destination(text, i)
    if dest_end is None:
        return None
    i = dest_end
    ws_start = i
    while i < n and text[i] in (" ", "\t", "\n"):
        i += 1
    if i < n and text[i] == ")":
        return i + 1
    if i > ws_start:
        title_end = _parse_link_title(text, i)
        if title_end is None:
            return None
        i = title_end
        while i < n and text[i] in (" ", "\t", "\n"):
            i += 1
        if i < n and text[i] == ")":
            return i + 1
    return None


def _match_link_tail(
    text: str,
    open_bracket: int,
    close_bracket: int,
    defined_labels: frozenset[str],
) -> int | None:
    """在 `]` 之后匹配行内 `(dest title)` 或引用 `[label]` / `[]` / 简写引用。"""
    n = len(text)
    after = close_bracket + 1
    if after < n and text[after] == "(":
        inline_end = _match_inline_link_dest_title(text, after)
        if inline_end is not None:
            return inline_end
    if defined_labels:
        if after < n and text[after] == "[":
            if after + 1 < n and text[after + 1] == "]":
                self_label = _match_link_label_brackets(text, open_bracket)
                if self_label is not None and self_label[0] == close_bracket + 1 and self_label[1] in defined_labels:
                    return after + 2
            ref_label = _match_link_label_brackets(text, after)
            if ref_label is not None and ref_label[1] in defined_labels:
                return ref_label[0]
        else:
            self_label = _match_link_label_brackets(text, open_bracket)
            if self_label is not None and self_label[0] == close_bracket + 1 and self_label[1] in defined_labels:
                return close_bracket + 1
    return None


def _find_matching_bracket(
    text: str,
    open_pos: int,
    *,
    allow_nested_links: bool,
    defined_labels: frozenset[str],
) -> int:
    n = len(text)
    i = open_pos + 1
    depth = 1
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
            i += 2
            continue
        if ch == "`":
            tick_end, found_end = _find_code_span_end(text, i)
            i = found_end if found_end != -1 else tick_end
            continue
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
            if auto_m is not None:
                i = auto_m.end()
                continue
            html_m = _INLINE_RAW_HTML_RE.match(text, i)
            if html_m is not None:
                i = html_m.end()
                continue
            i += 1
            continue
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            img_close = _find_matching_bracket(
                text,
                i + 1,
                allow_nested_links=True,
                defined_labels=defined_labels,
            )
            if img_close == -1:
                return -1
            img_end = _match_link_tail(text, i + 1, img_close, defined_labels)
            i = img_end if img_end is not None else img_close + 1
            continue
        if ch == "[":
            if not allow_nested_links:
                inner_close = _find_matching_bracket(
                    text,
                    i,
                    allow_nested_links=False,
                    defined_labels=defined_labels,
                )
                if inner_close == -1:
                    return -1
                if _match_link_tail(text, i, inner_close, defined_labels) is not None:
                    return -1
                i = inner_close + 1
                continue
            depth += 1
            i += 1
            continue
        if ch == "]":
            depth -= 1
            if depth == 0:
                return i
            i += 1
            continue
        i += 1
    return -1


def _is_invisible_or_ignorable_char(ch: str) -> bool:
    """判定字符是否为空白、不可见格式/控制/组合记号、Unicode Default_Ignorable_Code_Point 或空白填充符。"""
    if ch.isspace() or unicodedata.category(ch) in _INVISIBLE_CHECK_CATEGORIES:
        return True
    cp = ord(ch)
    if cp in _DEFAULT_IGNORABLE_OR_BLANK_CODE_POINTS:
        return True
    return any(lo <= cp <= hi for lo, hi in _DEFAULT_IGNORABLE_OR_BLANK_RANGES)


def _clean_display_reason(raw: str) -> str:
    """剥离行内匹配哨兵与不可见格式/控制/代理/分隔字符，保留正文组合记号并校验至少含一个可见基字符。"""
    cleaned = "".join(
        ch for ch in raw if ch != "\x01" and unicodedata.category(ch) not in _INVISIBLE_STRIP_CATEGORIES
    ).strip()
    if not any(not _is_invisible_or_ignorable_char(ch) for ch in cleaned):
        return ""
    return cleaned


def _decode_commonmark_entity(text: str, pos: int) -> tuple[str, int] | None:
    """按 CommonMark §6.2 解码带分号的命名/十进制/十六进制 HTML 字符实体。"""
    ent_m = _COMMONMARK_ENTITY_RE.match(text, pos)
    if ent_m is None:
        return None
    raw_ent = ent_m.group(0)
    decoded = html.unescape(raw_ent)
    if decoded == raw_ent:
        return None
    return decoded, ent_m.end()


_HTML_OPEN_TAG_HEAD_RE = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)(?=[ \t\n\r\f/>]|$)")
_HTML_CLOSE_TAG_HEAD_RE = re.compile(r"</([A-Za-z][A-Za-z0-9-]*)[ \t\n\r\f]*>")


@dataclass
class _HtmlSuppressState:
    """跨空行/跨段落持久传递的文档级 HTML 抑制状态（抑制标签栈、未闭 HTML 注释/处理指令/CDATA/声明、未闭原始文本标签、跨块开放标签与引号属性）。"""

    tag_stack: list[str] = field(default_factory=list)
    in_comment: bool = False
    in_pi: bool = False
    in_cdata: bool = False
    in_decl: bool = False
    raw_text_tag: str | None = None
    in_open_tag: bool = False
    open_tag_quote: str | None = None
    pending_open_tag_name: str | None = None
    suppressed_tags: frozenset[str] = _SUPPRESSED_INLINE_HTML_TAGS


@dataclass
class _DelimRun:
    token_idx: int
    char: str
    orig_len: int
    rem: int
    can_open: bool
    can_close: bool


def _is_cm_whitespace(ch: str) -> bool:
    if not ch:
        return True
    return ch in (" ", "\t", "\n", "\r", "\f") or unicodedata.category(ch) == "Zs"


def _is_cm_punctuation(ch: str) -> bool:
    if not ch:
        return False
    return ch in _ASCII_PUNCTUATION or unicodedata.category(ch)[0] in ("P", "S")


def _apply_emphasis_delimiters(
    tokens: list[tuple[str, str] | None],
    delims: list[_DelimRun],
) -> None:
    """按 CommonMark §6.2 与 GFM ~~ 左右翼规则在整段范围内剥离配对强调/删除线定界符的 display_stream 文本。"""
    if len(delims) < 2:
        return
    for closer_idx, closer in enumerate(delims):
        while closer.rem > 0 and closer.can_close:
            if closer.char == "~" and closer.rem < 2:
                break
            matched_opener_idx = -1
            for opener_idx in range(closer_idx - 1, -1, -1):
                opener = delims[opener_idx]
                if opener.rem == 0 or not opener.can_open or opener.char != closer.char:
                    continue
                if closer.char == "~" and opener.rem < 2:
                    continue
                if closer.char in ("*", "_"):
                    if (
                        (opener.can_close or closer.can_open)
                        and (closer.orig_len % 3 != 0)
                        and ((opener.orig_len + closer.orig_len) % 3 == 0)
                    ):
                        continue
                matched_opener_idx = opener_idx
                break
            if matched_opener_idx == -1:
                break
            opener = delims[matched_opener_idx]
            use = 2 if (closer.char == "~" or (opener.rem >= 2 and closer.rem >= 2)) else 1
            opener.rem -= use
            closer.rem -= use
            for mid_idx in range(matched_opener_idx + 1, closer_idx):
                delims[mid_idx].can_open = False
                delims[mid_idx].can_close = False
    for d in delims:
        if d.rem != d.orig_len:
            tok = tokens[d.token_idx]
            assert tok is not None
            m_part, _ = tok
            tokens[d.token_idx] = (m_part, d.char * d.rem)


def _finish_open_tag(state: _HtmlSuppressState) -> None:
    """按 HTML5 规则完成开标签闭合：受抑制标签均属非空元素，无论是否带 `/>` 均入栈。"""
    tag_name = state.pending_open_tag_name
    state.in_open_tag = False
    state.open_tag_quote = None
    state.pending_open_tag_name = None
    if tag_name is not None and tag_name in state.suppressed_tags:
        state.tag_stack.append(tag_name)
        if tag_name in _RAW_TEXT_HTML_TAGS:
            state.raw_text_tag = tag_name


def _advance_in_open_tag(text: str, start: int, state: _HtmlSuppressState) -> int:
    """按 HTML5 词法推进原始 HTML 块内的开放标签属性扫描，支持跨块未闭引号属性。"""
    n = len(text)
    i = start
    expect_attr_value = False
    in_unquoted_value = False
    while i < n:
        if state.open_tag_quote is not None:
            q_pos = text.find(state.open_tag_quote, i)
            if q_pos == -1:
                return n
            state.open_tag_quote = None
            i = q_pos + 1
            expect_attr_value = False
            in_unquoted_value = False
            continue
        ch = text[i]
        if ch == ">":
            _finish_open_tag(state)
            return i + 1
        if expect_attr_value:
            if ch in (" ", "\t", "\n", "\r", "\f"):
                i += 1
                continue
            if ch in ('"', "'"):
                state.open_tag_quote = ch
                expect_attr_value = False
                i += 1
                continue
            expect_attr_value = False
            in_unquoted_value = True
            i += 1
            continue
        if in_unquoted_value:
            if ch in (" ", "\t", "\n", "\r", "\f"):
                in_unquoted_value = False
            i += 1
            continue
        if ch == "=":
            expect_attr_value = True
        i += 1
    return n


def _update_html_suppress_state(
    text: str,
    state: _HtmlSuppressState,
    *,
    visible_chunks: list[str] | None = None,
) -> None:
    """扫描真实原始 HTML 块内容，按 HTML5 开/闭标签、跨块注释、原始文本标签与未闭引号属性状态更新持久抑制状态；可选收集非静默可见文本片段。"""
    n = len(text)
    i = 0

    def emit_visible(segment: str) -> None:
        if visible_chunks is not None and segment and not any(t in _SILENT_INLINE_HTML_TAGS for t in state.tag_stack):
            visible_chunks.append(segment)

    while i < n:
        if state.in_comment:
            end_pos = text.find("-->", i)
            if end_pos == -1:
                return
            state.in_comment = False
            i = end_pos + 3
            continue
        if state.in_pi:
            end_pos = text.find("?>", i)
            if end_pos == -1:
                return
            state.in_pi = False
            i = end_pos + 2
            continue
        if state.in_cdata:
            end_pos = text.find("]]>", i)
            if end_pos == -1:
                return
            state.in_cdata = False
            i = end_pos + 3
            continue
        if state.in_decl:
            end_pos = text.find(">", i)
            if end_pos == -1:
                return
            state.in_decl = False
            i = end_pos + 1
            continue
        if state.raw_text_tag is not None:
            close_m = _RAW_TEXT_CLOSE_RES[state.raw_text_tag].search(text, i)
            if close_m is None:
                return
            closing_tag = state.raw_text_tag
            state.raw_text_tag = None
            if closing_tag in state.tag_stack:
                while state.tag_stack:
                    if state.tag_stack.pop() == closing_tag:
                        break
            i = close_m.end()
            continue
        if state.in_open_tag:
            i = _advance_in_open_tag(text, i, state)
            continue
        lt = text.find("<", i)
        if lt == -1:
            emit_visible(text[i:])
            return
        if lt > i:
            emit_visible(text[i:lt])
        if text.startswith("<!--", lt):
            if text.startswith("<!-->", lt):
                i = lt + 5
                continue
            if text.startswith("<!--->", lt):
                i = lt + 6
                continue
            end_pos = text.find("-->", lt + 4)
            if end_pos == -1:
                state.in_comment = True
                return
            i = end_pos + 3
            continue
        if text.startswith("<?", lt):
            end_pos = text.find("?>", lt + 2)
            if end_pos == -1:
                state.in_pi = True
                return
            i = end_pos + 2
            continue
        if text.startswith("<![CDATA[", lt):
            end_pos = text.find("]]>", lt + 9)
            if end_pos == -1:
                state.in_cdata = True
                return
            i = end_pos + 3
            continue
        if lt + 2 < n and text[lt + 1] == "!" and text[lt + 2].isalpha():
            end_pos = text.find(">", lt + 2)
            if end_pos == -1:
                state.in_decl = True
                return
            i = end_pos + 1
            continue
        close_tag_m = _HTML_CLOSE_TAG_HEAD_RE.match(text, lt)
        if close_tag_m is not None:
            tag_name = close_tag_m.group(1).lower()
            if tag_name in state.tag_stack:
                while state.tag_stack:
                    if state.tag_stack.pop() == tag_name:
                        break
            i = close_tag_m.end()
            continue
        open_head_m = _HTML_OPEN_TAG_HEAD_RE.match(text, lt)
        if open_head_m is not None:
            state.in_open_tag = True
            state.open_tag_quote = None
            state.pending_open_tag_name = open_head_m.group(1).lower()
            i = _advance_in_open_tag(text, open_head_m.end(), state)
            continue
        emit_visible("<")
        i = lt + 1


def _extract_code_span_text(inner: str) -> str:
    """按 CommonMark §6.1 提取行内代码跨度纯文本：换行转空格，非全空格且首尾均为空格时各剥离 1 个。"""
    text = inner.replace("\n", " ")
    if len(text) >= 2 and text[0] == " " and text[-1] == " " and any(ch != " " for ch in text):
        return text[1:-1]
    return text


def _scan_inline_dual(
    text: str,
    defined_labels: frozenset[str] = frozenset(),
    suppress_state: _HtmlSuppressState | None = None,
    *,
    is_top_level_paragraph: bool = True,
) -> list[list[tuple[str, str]]]:
    """CommonMark §6 段落行内双流扫描器：整段配对强调/删除线定界符后，再按行切分对齐的 (match_stream, display_stream)。

    - match_stream：用于指令头匹配；代码跨度、自动链接、跨块未闭注释/开放标签/引号属性、抑制标签（<code>/<blockquote>/<pre>/<script> 等）、
      图片与链接目标/标题均写入非匹配哨兵 `\\x01` 且不产生新行，彻底阻断伪指令注入。
    - display_stream：用于确认合法指令后提取人类可读理由；行内代码跨度原样保留不解码，对普通文本严格单次解码 HTML 实体，
      剥离原始 HTML 与整段配对 Markdown 强调/删除线定界符（含跨软换行配对）。
    """
    state = suppress_state if suppress_state is not None else _HtmlSuppressState()
    stack = state.tag_stack
    tokens: list[tuple[str, str] | None] = []
    delims: list[_DelimRun] = []
    n = len(text)
    i = 0

    def emit(m_part: str, d_part: str) -> None:
        if m_part or d_part:
            tokens.append((m_part, d_part))

    def emit_newline() -> None:
        tokens.append(None)

    while i < n:
        # 0a. 处于跨块未闭 HTML 注释内：忽略一切标签，仅当行内原始 HTML 含 --> 时关闭注释
        if state.in_comment:
            ch = text[i]
            if ch == "`":
                tick_end, found_end = _find_code_span_end(text, i)
                emit("\x01", "")
                i = found_end if found_end != -1 else tick_end
                continue
            if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                emit("\x01", "")
                i += 2
                continue
            if ch == "<":
                auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
                if auto_m is not None:
                    emit("\x01", "")
                    i = auto_m.end()
                    continue
                html_m = _INLINE_RAW_HTML_RE.match(text, i)
                if html_m is not None:
                    raw_html = html_m.group(0)
                    emit("\x01", "")
                    if "-->" in raw_html:
                        state.in_comment = False
                    i = html_m.end()
                    continue
            emit("\x01", "")
            i += 1
            continue

        # 0a-ext. 处于跨块未闭 HTML 处理指令/CDATA/声明内
        if state.in_pi or state.in_cdata or state.in_decl:
            ch = text[i]
            if ch == "`":
                tick_end, found_end = _find_code_span_end(text, i)
                emit("\x01", "")
                i = found_end if found_end != -1 else tick_end
                continue
            if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                emit("\x01", "")
                i += 2
                continue
            if ch == "<":
                auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
                if auto_m is not None:
                    emit("\x01", "")
                    i = auto_m.end()
                    continue
                html_m = _INLINE_RAW_HTML_RE.match(text, i)
                if html_m is not None:
                    raw_html = html_m.group(0)
                    emit("\x01", "")
                    if state.in_pi and "?>" in raw_html:
                        state.in_pi = False
                    elif state.in_cdata and "]]>" in raw_html:
                        state.in_cdata = False
                    elif state.in_decl and ">" in raw_html:
                        state.in_decl = False
                    i = html_m.end()
                    continue
            emit("\x01", "")
            i += 1
            continue

        # 0b. 处于未闭原始文本 HTML 标签（<script>/<style>/<textarea>/<title>）内
        if state.raw_text_tag is not None:
            ch = text[i]
            if ch == "`":
                tick_end, found_end = _find_code_span_end(text, i)
                emit("\x01", "")
                i = found_end if found_end != -1 else tick_end
                continue
            if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
                emit("\x01", "")
                i += 2
                continue
            if ch == "<":
                auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
                if auto_m is not None:
                    emit("\x01", "")
                    i = auto_m.end()
                    continue
                html_m = _INLINE_RAW_HTML_RE.match(text, i)
                if html_m is not None:
                    raw_html = html_m.group(0)
                    emit("\x01", "")
                    if _RAW_TEXT_CLOSE_RES[state.raw_text_tag].search(raw_html) is not None:
                        closing_tag = state.raw_text_tag
                        state.raw_text_tag = None
                        if closing_tag in stack:
                            while stack:
                                if stack.pop() == closing_tag:
                                    break
                    i = html_m.end()
                    continue
            emit("\x01", "")
            i += 1
            continue

        # 0c. 处于跨块未闭 HTML 开标签（含跨块未闭带引号属性）内
        if state.in_open_tag:
            if state.open_tag_quote is not None:
                q_pos = text.find(state.open_tag_quote, i)
                if q_pos == -1:
                    emit("\x01", "")
                    i = n
                    break
                state.open_tag_quote = None
                emit("\x01", "")
                i = q_pos + 1
                continue
            ch = text[i]
            if ch == "`":
                tick_end, found_end = _find_code_span_end(text, i)
                emit("\x01", "")
                if found_end != -1:
                    _finish_open_tag(state)
                    i = found_end
                else:
                    i = tick_end
                continue
            if ch == "<":
                auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
                if auto_m is not None:
                    _finish_open_tag(state)
                    emit("\x01", "")
                    i = auto_m.end()
                    continue
                html_m = _INLINE_RAW_HTML_RE.match(text, i)
                if html_m is not None:
                    _finish_open_tag(state)
                    emit("\x01", "")
                    i = html_m.end()
                    continue
            if ch == "=":
                j = i + 1
                while j < n and text[j] in (" ", "\t", "\n", "\r", "\f"):
                    j += 1
                if j < n and text[j] in ('"', "'"):
                    state.open_tag_quote = text[j]
                    emit("\x01", "")
                    i = j + 1
                    continue
            emit("\x01", "")
            i += 1
            continue

        # 0d. 处于抑制 HTML 标签栈内（如 <code>、<blockquote>、<pre>、<kbd> 等）
        if stack:
            silent = any(t in _SILENT_INLINE_HTML_TAGS for t in stack)
            ch = text[i]
            if ch == "`":
                tick_end, found_end = _find_code_span_end(text, i)
                if found_end != -1:
                    code_val = _extract_code_span_text(text[tick_end : found_end - (tick_end - i)])
                    emit("\x01", "" if silent else code_val)
                    i = found_end
                else:
                    emit("\x01", "" if silent else text[i:tick_end])
                    i = tick_end
                continue
            if ch == "<":
                auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
                if auto_m is not None:
                    emit("\x01", "" if silent else auto_m.group(0)[1:-1])
                    i = auto_m.end()
                    continue
                html_m = _INLINE_RAW_HTML_RE.match(text, i)
                if html_m is not None:
                    raw_html = html_m.group(0)
                    close_tag_m = _INLINE_HTML_CLOSE_NAME_RE.fullmatch(raw_html)
                    if close_tag_m is not None:
                        tag_name = close_tag_m.group(1).lower()
                        if tag_name in stack:
                            while stack:
                                popped = stack.pop()
                                if popped == tag_name:
                                    break
                    elif not raw_html.startswith(("<!--", "<?", "<!")):
                        open_tag_m = _INLINE_HTML_OPEN_NAME_RE.match(raw_html)
                        if open_tag_m is not None:
                            tag_name = open_tag_m.group(1).lower()
                            if tag_name in state.suppressed_tags:
                                stack.append(tag_name)
                                if tag_name in _RAW_TEXT_HTML_TAGS:
                                    state.raw_text_tag = tag_name
                    i = html_m.end()
                    continue
                emit("\x01", "" if silent else ch)
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                nxt = text[i + 1]
                if nxt in _ASCII_PUNCTUATION:
                    emit("\x01", "" if silent else nxt)
                    i += 2
                    continue
                if nxt == "\n":
                    emit("\x01", "" if silent else " ")
                    i += 2
                    continue
            if ch == "&":
                decoded_ent = _decode_commonmark_entity(text, i)
                if decoded_ent is not None:
                    decoded_val, next_i = decoded_ent
                    emit("\x01", "" if silent else decoded_val)
                    i = next_i
                    continue
            if ch == "\n":
                emit("\x01", "" if silent else " ")
                i += 1
                continue
            emit("\x01", "" if silent else ch)
            i += 1
            continue

        ch = text[i]
        # 1. 普通换行
        if ch == "\n":
            emit_newline()
            i += 1
            continue

        # 2. 反斜杠转义（§2.4）与反斜杠硬换行（§6.7）
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in _ASCII_PUNCTUATION:
                emit(nxt, nxt)
                i += 2
                continue
            if nxt == "\n":
                emit_newline()
                i += 2
                continue
            emit(ch, ch)
            i += 1
            continue

        # 3. 行内代码跨度（§6.1）：match_stream 写入哨兵，display_stream 保留字面纯文本内容（不解码 HTML 实体）
        if ch == "`":
            tick_end, found_end = _find_code_span_end(text, i)
            if found_end != -1:
                tick_len = tick_end - i
                code_val = _extract_code_span_text(text[tick_end : found_end - tick_len])
                emit("\x01", code_val)
                i = found_end
            else:
                raw_ticks = text[i:tick_end]
                emit(raw_ticks, raw_ticks)
                i = tick_end
            continue

        # 4. 自动链接（§6.5）与行内原始 HTML（§6.6）
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
            if auto_m is not None:
                emit("\x01", auto_m.group(0)[1:-1])
                i = auto_m.end()
                continue
            html_m = _INLINE_RAW_HTML_RE.match(text, i)
            if html_m is not None:
                raw_html = html_m.group(0)
                if not raw_html.startswith(("<!--", "<?", "<!", "</")):
                    open_tag_m = _INLINE_HTML_OPEN_NAME_RE.match(raw_html)
                    if open_tag_m is not None:
                        tag_name = open_tag_m.group(1).lower()
                        if tag_name in state.suppressed_tags:
                            stack.append(tag_name)
                            if tag_name in _RAW_TEXT_HTML_TAGS:
                                state.raw_text_tag = tag_name
                            emit("\x01", "")
                i = html_m.end()
                continue
            emit(ch, ch)
            i += 1
            continue

        # 5. 行内/引用图片（§6.4）
        if ch == "!" and i + 1 < n and text[i + 1] == "[":
            close_bracket = _find_matching_bracket(
                text,
                i + 1,
                allow_nested_links=True,
                defined_labels=defined_labels,
            )
            if close_bracket != -1:
                img_end = _match_link_tail(text, i + 1, close_bracket, defined_labels)
                if img_end is not None:
                    emit("\x01", "")
                    i = img_end
                    continue
            emit(ch, ch)
            i += 1
            continue

        # 6. 行内/引用链接（§6.3）
        if ch == "[":
            close_bracket = _find_matching_bracket(
                text,
                i,
                allow_nested_links=False,
                defined_labels=defined_labels,
            )
            if close_bracket != -1:
                link_end = _match_link_tail(text, i, close_bracket, defined_labels)
                if link_end is not None:
                    inner_lines = _scan_inline_dual(
                        text[i + 1 : close_bracket],
                        defined_labels,
                        state,
                        is_top_level_paragraph=False,
                    )
                    tokens.extend(inner_lines[0])
                    for extra_line in inner_lines[1:]:
                        emit_newline()
                        tokens.extend(extra_line)
                    if link_end > close_bracket + 1:
                        emit("\x01", "")
                    i = link_end
                    continue
            emit(ch, ch)
            i += 1
            continue

        # 7. CommonMark §6.2 字符实体解码（仅对非行内代码跨度的普通文本严格单次解码）
        if ch == "&":
            decoded_ent = _decode_commonmark_entity(text, i)
            if decoded_ent is not None:
                decoded_val, next_i = decoded_ent
                match_val = decoded_val.replace("\r", " ").replace("\n", " ")
                emit(match_val, decoded_val)
                i = next_i
                continue

        # 8. CommonMark §6.2 / GFM ~~ 强调与删除线定界符串记录（基于原始源码左右字符判定左右翼，跨整段配对）
        if ch in ("*", "_", "~"):
            run_end = i + 1
            while run_end < n and text[run_end] == ch:
                run_end += 1
            run = text[i:run_end]
            before_ch = text[i - 1] if i > 0 else ""
            after_ch = text[run_end] if run_end < n else ""
            before_ws = _is_cm_whitespace(before_ch)
            after_ws = _is_cm_whitespace(after_ch)
            before_punct = _is_cm_punctuation(before_ch)
            after_punct = _is_cm_punctuation(after_ch)
            left_flanking = (not after_ws) and ((not after_punct) or before_ws or before_punct)
            right_flanking = (not before_ws) and ((not before_punct) or after_ws or after_punct)
            if ch == "_":
                can_open = left_flanking and ((not right_flanking) or before_punct)
                can_close = right_flanking and ((not left_flanking) or after_punct)
            else:
                can_open = left_flanking
                can_close = right_flanking
            token_idx = len(tokens)
            emit(run, run)
            if can_open or can_close:
                delims.append(
                    _DelimRun(
                        token_idx=token_idx,
                        char=ch,
                        orig_len=len(run),
                        rem=len(run),
                        can_open=can_open,
                        can_close=can_close,
                    )
                )
            i = run_end
            continue

        # 9. 普通字符原样输出
        emit(ch, ch)
        i += 1

    # 顶层段落由 `</p>` 收尾：若仍处于已闭引号的开放标签内，`</p>` 的 `>` 会在 HTML5 中闭合该开标签
    if is_top_level_paragraph and state.in_open_tag and state.open_tag_quote is None:
        _finish_open_tag(state)

    if delims:
        _apply_emphasis_delimiters(tokens, delims)

    lines: list[list[tuple[str, str]]] = [[]]
    for tok in tokens:
        if tok is None:
            lines.append([])
        else:
            lines[-1].append(tok)
    return lines


def _extract_display_slice(tokens: Sequence[tuple[str, str]], start_match_pos: int) -> str:
    """按 match_stream 中的起始偏移精确截取对应 display_stream 尾部文本。"""
    parts: list[str] = []
    pos = 0
    for m_part, d_part in tokens:
        end = pos + len(m_part)
        if pos >= start_match_pos:
            parts.append(d_part)
        elif end > start_match_pos:
            offset = start_match_pos - pos
            parts.append(d_part[offset:])
        pos = end
    return "".join(parts)


def _extract_atx_heading_text(rest: str) -> str:
    """按 CommonMark §4.2 剥离 ATX 标题首部 `#` 序列与可选尾部 `#` 闭合序列。"""
    i = 0
    n = len(rest)
    while i < n and rest[i] == "#":
        i += 1
    content = rest[i:].strip(" \t")
    if not content:
        return ""
    j = len(content)
    while j > 0 and content[j - 1] == "#":
        j -= 1
    if j == 0:
        return ""
    if j < len(content) and content[j - 1] in (" ", "\t"):
        content = content[:j].rstrip(" \t")
    return content


def _split_gfm_table_row(line: str, *, require_pipe: bool = True) -> list[str] | None:
    """按 GFM §4.10 / `pandoc -f gfm` 规则将表格行拆分为单元格列表。

    - 剥离首尾 ASCII 空格/制表符；
    - 索引 `idx` 处的 `|` 被转义，当且仅当紧邻前字符为 `\\`（`idx > 0 and stripped[idx - 1] == "\\"`）；
    - 若 `require_pipe=True` 且全行不存在未转义 `|`，返回 None；
    - 剥离首部单个未转义 `|` 与尾部单个未转义 `|`（尾部紧邻 `\\` 的 `|` 不剥离）；
    - 按剩余未转义 `|` 切分单元格，每格去除首尾 ASCII 空格/制表符并将 `\\|` 还原为 `|`。
    """
    stripped = line.strip(" \t")
    if not stripped:
        return None if require_pipe else []
    pipe_positions: list[int] = [
        idx
        for idx, ch in enumerate(stripped)
        if ch == "|" and not (idx > 0 and stripped[idx - 1] == "\\")
    ]
    if require_pipe and not pipe_positions:
        return None
    if len(pipe_positions) == 1 and len(stripped) == 1:
        return []
    start = 0
    end = len(stripped)
    inner_pipes = pipe_positions
    if inner_pipes and inner_pipes[0] == 0:
        start = 1
        inner_pipes = inner_pipes[1:]
    if inner_pipes and inner_pipes[-1] == len(stripped) - 1:
        end = len(stripped) - 1
        inner_pipes = inner_pipes[:-1]
    cells: list[str] = []
    seg_start = start
    for p in inner_pipes:
        cells.append(stripped[seg_start:p].strip(" \t").replace("\\|", "|"))
        seg_start = p + 1
    cells.append(stripped[seg_start:end].strip(" \t").replace("\\|", "|"))
    return cells


def _is_gfm_table_delimiter_row(line: str, expected_cols: int) -> bool:
    """按 GFM §4.10 校验表格分隔行：必须含至少一个未转义 `|`，列数与表头一致，且每格匹配 `^:?-+:?$`。"""
    if expected_cols <= 0:
        return False
    cells = _split_gfm_table_row(line, require_pipe=True)
    if cells is None or len(cells) != expected_cols:
        return False
    return all(_GFM_TABLE_DELIM_CELL_RE.fullmatch(cell) is not None for cell in cells)


def _is_html_suppressed(state: _HtmlSuppressState) -> bool:
    return (
        state.in_comment
        or state.in_pi
        or state.in_cdata
        or state.in_decl
        or state.raw_text_tag is not None
        or state.in_open_tag
        or any(t in _SILENT_INLINE_HTML_TAGS for t in state.tag_stack)
    )


def _parse_commonmark_blocks(
    body: str,
    *,
    include_all_visible_blocks: bool = False,
) -> tuple[list[tuple[Literal["paragraph", "heading", "html", "code", "table_cell"], str]], frozenset[str]]:
    """按 CommonMark Phase-1 容器栈/叶子块（含 GFM §4.10 管道表格）+ §4.7 链接引用定义剥离收集文档块与已定义链接标签。"""
    containers: list[_Container] = []
    leaf: _Leaf | None = None
    defined_labels: set[str] = set()
    doc_blocks: list[tuple[Literal["paragraph", "heading", "html", "code", "table_cell"], str]] = []

    def in_blockquote() -> bool:
        return any(isinstance(c, _BlockQuote) for c in containers)

    def close_leaf(*, emit: bool = True) -> None:
        nonlocal leaf
        if isinstance(leaf, _Paragraph):
            remaining = _strip_leading_link_ref_defs("\n".join(leaf.lines), defined_labels)
            if emit and remaining and (include_all_visible_blocks or not in_blockquote()):
                doc_blocks.append(("paragraph", remaining))
        elif isinstance(leaf, _HTMLBlock):
            if emit and leaf.lines and (include_all_visible_blocks or not in_blockquote()):
                doc_blocks.append(("html", "\n".join(leaf.lines)))
        elif isinstance(leaf, (_FencedCode, _IndentedCode)):
            if include_all_visible_blocks and emit and leaf.lines:
                doc_blocks.append(("code", "\n".join(leaf.lines)))
        elif isinstance(leaf, _Table):
            if include_all_visible_blocks and emit:
                for cell in leaf.header_cells:
                    doc_blocks.append(("table_cell", cell))
                for row in leaf.body_rows:
                    for cell in row:
                        doc_blocks.append(("table_cell", cell))
        leaf = None

    def close_unmatched(matched_count: int) -> None:
        if matched_count < len(containers):
            close_leaf()
            del containers[matched_count:]

    def mark_parent_has_content() -> None:
        if containers and isinstance(containers[-1], _ListItem):
            containers[-1].has_content = True

    for raw_line in _split_commonmark_lines(body):
        cursor = _LineCursor(raw_line)

        # 1. 从外到内匹配已打开容器栈
        matched = 0
        for container in containers:
            if isinstance(container, _BlockQuote):
                indent = cursor.indent_ahead()
                if indent <= 3:
                    saved = cursor.save()
                    cursor.advance_cols(indent)
                    if cursor.peek_char() == ">":
                        cursor.advance_chars(1)
                        if cursor.peek_char() in (" ", "\t"):
                            cursor.advance_cols(1)
                        matched += 1
                        continue
                    cursor.restore(saved)
                break
            else:
                if cursor.is_blank():
                    if not container.has_content:
                        break
                    matched += 1
                    continue
                if cursor.indent_ahead() >= container.padding:
                    cursor.advance_cols(container.padding)
                    matched += 1
                    continue
                break

        # 2. 全部容器匹配时，先续接或闭合非段落叶子块
        if matched == len(containers) and leaf is not None and not isinstance(leaf, _Paragraph):
            if isinstance(leaf, _FencedCode):
                if not cursor.is_blank() and cursor.indent_ahead() <= 3:
                    saved = cursor.save()
                    cursor.advance_cols(cursor.indent_ahead())
                    rest = cursor.rest_text()
                    if re.fullmatch(rf"{re.escape(leaf.fence_char)}{{{leaf.fence_len},}}[ \t]*", rest):
                        close_leaf()
                        continue
                    cursor.restore(saved)
                leaf.lines.append(cursor.rest_text())
                continue
            if isinstance(leaf, _HTMLBlock):
                if leaf.kind in (6, 7):
                    if cursor.is_blank():
                        close_leaf()
                        continue
                    leaf.lines.append(cursor.rest_text())
                    continue
                leaf.lines.append(cursor.rest_text())
                if _is_html_block_end(leaf.kind, cursor.rest_text()):
                    close_leaf()
                continue
            if isinstance(leaf, _IndentedCode):
                if cursor.is_blank():
                    cursor.advance_cols(4)
                    leaf.lines.append(cursor.rest_text())
                    continue
                if cursor.indent_ahead() >= 4:
                    cursor.advance_cols(4)
                    leaf.lines.append(cursor.rest_text())
                    continue
                close_leaf()
            if isinstance(leaf, _Table):
                if cursor.is_blank():
                    close_leaf()
                    continue
                row_cells = _split_gfm_table_row(cursor.rest_text(), require_pipe=True)
                if row_cells is not None:
                    leaf.body_rows.append(tuple(row_cells[: len(leaf.header_cells)]))
                    continue
                close_leaf()

        if matched < len(containers) and not isinstance(leaf, _Paragraph):
            close_unmatched(matched)

        if cursor.is_blank():
            close_unmatched(matched)
            if isinstance(leaf, _Paragraph):
                close_leaf()
            continue

        # 3. 按 CommonMark 优先级开启新容器或叶子块
        line_consumed = False
        while True:
            if cursor.is_blank():
                line_consumed = True
                break

            indent = cursor.indent_ahead()
            same_container_para = matched == len(containers) and isinstance(leaf, _Paragraph)
            any_open_para = isinstance(leaf, _Paragraph)

            if indent >= 4:
                if any_open_para:
                    break
                close_unmatched(matched)
                mark_parent_has_content()
                cursor.advance_cols(4)
                leaf = _IndentedCode(lines=[cursor.rest_text()])
                line_consumed = True
                break

            saved = cursor.save()
            cursor.advance_cols(indent)
            rest = cursor.rest_text()

            if rest.startswith(">"):
                close_unmatched(matched)
                close_leaf()
                cursor.advance_chars(1)
                if cursor.peek_char() in (" ", "\t"):
                    cursor.advance_cols(1)
                mark_parent_has_content()
                containers.append(_BlockQuote())
                matched = len(containers)
                continue

            if _ATX_HEADING_BODY_RE.match(rest):
                close_unmatched(matched)
                close_leaf()
                mark_parent_has_content()
                if include_all_visible_blocks:
                    heading_text = _extract_atx_heading_text(rest)
                    if heading_text:
                        doc_blocks.append(("heading", heading_text))
                line_consumed = True
                break

            bt_match = _FENCE_OPEN_BACKTICK_BODY_RE.match(rest)
            tilde_match = _FENCE_OPEN_TILDE_BODY_RE.match(rest) if bt_match is None else None
            fence_match = bt_match or tilde_match
            if fence_match is not None:
                close_unmatched(matched)
                close_leaf()
                mark_parent_has_content()
                marker = fence_match.group(1)
                leaf = _FencedCode(fence_char=marker[0], fence_len=len(marker))
                line_consumed = True
                break

            html_kind = _match_html_block_start(rest, allow_type7=not any_open_para)
            if html_kind is not None:
                close_unmatched(matched)
                close_leaf()
                mark_parent_has_content()
                leaf = _HTMLBlock(kind=html_kind, lines=[rest])
                if html_kind in (1, 2, 3, 4, 5) and _is_html_block_end(html_kind, rest, is_opening_line=True):
                    close_leaf()
                line_consumed = True
                break

            if same_container_para and _SETEXT_UNDERLINE_BODY_RE.match(rest):
                assert isinstance(leaf, _Paragraph)
                remaining_before_setext = _strip_leading_link_ref_defs("\n".join(leaf.lines), defined_labels)
                if remaining_before_setext:
                    if include_all_visible_blocks:
                        doc_blocks.append(("heading", remaining_before_setext))
                    leaf = None
                    line_consumed = True
                    break
                # 仅含链接引用定义的段落不可变成 Setext 标题：先关闭该空段落，再按普通块继续解析当前行
                leaf = None
                same_container_para = False
                any_open_para = False

            if _THEMATIC_BREAK_BODY_RE.match(rest):
                close_unmatched(matched)
                close_leaf()
                mark_parent_has_content()
                line_consumed = True
                break

            list_match = _LIST_ITEM_MARKER_BODY_RE.match(rest)
            if list_match is not None:
                marker_width = list_match.end()
                is_bullet = list_match.group("bullet") is not None
                ordered_num = int(list_match.group("num")) if not is_bullet else 0
                after_marker_state = cursor.save()
                cursor.advance_chars(marker_width)
                is_empty_item = cursor.is_blank()
                can_open_list = (not same_container_para) or (
                    (not is_empty_item) and (is_bullet or ordered_num == 1)
                )
                if can_open_list:
                    close_unmatched(matched)
                    close_leaf()
                    if is_empty_item:
                        padding = indent + marker_width + 1
                    else:
                        spaces_after = cursor.indent_ahead()
                        if spaces_after >= 5:
                            padding = indent + marker_width + 1
                            cursor.advance_cols(1)
                        else:
                            padding = indent + marker_width + spaces_after
                            cursor.advance_cols(spaces_after)
                    mark_parent_has_content()
                    containers.append(_ListItem(padding=padding, has_content=False))
                    matched = len(containers)
                    continue
                cursor.restore(after_marker_state)

            if (
                same_container_para
                and isinstance(leaf, _Paragraph)
                and len(leaf.lines) == 1
                and _strip_leading_link_ref_defs(leaf.lines[0], None)
            ):
                header_cells = _split_gfm_table_row(leaf.lines[0], require_pipe=True)
                if header_cells and _is_gfm_table_delimiter_row(rest, len(header_cells)):
                    leaf = _Table(header_cells=tuple(header_cells))
                    line_consumed = True
                    break

            cursor.restore(saved)
            break

        if line_consumed:
            continue

        # 4. 段落续行（含 BlockQuote / ListItem 惰性续行）或开启新段落；按 CommonMark §4.8 仅剥离 ASCII 空格/制表符
        text_line = cursor.rest_text().strip(" \t")
        if isinstance(leaf, _Paragraph):
            leaf.lines.append(text_line)
        else:
            close_unmatched(matched)
            mark_parent_has_content()
            leaf = _Paragraph(lines=[text_line])

    close_leaf()
    return doc_blocks, frozenset(defined_labels)


def _extract_visible_paragraph_lines(body: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """按 CommonMark Phase-1 容器栈/叶子块 + §4.7 链接引用定义剥离 + 跨块持久 HTML 抑制栈 + §6 双流扫描提取非引用可见段落行。"""
    doc_blocks, frozen_labels = _parse_commonmark_blocks(body, include_all_visible_blocks=False)
    html_suppress_state = _HtmlSuppressState()
    visible_lines: list[tuple[str, list[tuple[str, str]]]] = []
    for block_kind, block_text in doc_blocks:
        if block_kind == "html":
            _update_html_suppress_state(block_text, html_suppress_state)
            continue
        for line_tokens in _scan_inline_dual(block_text, frozen_labels, html_suppress_state):
            raw_match = "".join(m for m, _ in line_tokens)
            stripped_match = raw_match.strip(" \t")
            if stripped_match:
                visible_lines.append((raw_match, line_tokens))
    return visible_lines


def _has_visible_gfm_text(text: str) -> bool:
    """按 GFM 渲染语义判定文本是否包含至少 1 个可见基字符（覆盖段落/列表/引用/标题/围栏与缩进代码/GFM 表格/非静默 HTML）。"""
    doc_blocks, frozen_labels = _parse_commonmark_blocks(text, include_all_visible_blocks=True)
    html_suppress_state = _HtmlSuppressState(suppressed_tags=_SILENT_INLINE_HTML_TAGS)
    for block_kind, block_text in doc_blocks:
        if block_kind == "html":
            visible_chunks: list[str] = []
            _update_html_suppress_state(block_text, html_suppress_state, visible_chunks=visible_chunks)
            for chunk in visible_chunks:
                if _clean_display_reason(html.unescape(chunk)):
                    return True
            continue
        if block_kind == "code":
            if _is_html_suppressed(html_suppress_state):
                continue
            for code_line in block_text.split("\n"):
                if _clean_display_reason(code_line):
                    return True
            continue
        if block_kind == "table_cell":
            if _is_html_suppressed(html_suppress_state):
                continue
            for line_tokens in _scan_inline_dual(block_text, frozen_labels, html_suppress_state):
                display_text = "".join(d_part for _, d_part in line_tokens)
                if _clean_display_reason(display_text):
                    return True
            continue
        for line_tokens in _scan_inline_dual(block_text, frozen_labels, html_suppress_state):
            display_text = "".join(d_part for _, d_part in line_tokens)
            if _clean_display_reason(display_text):
                return True
    return False


def _match_reply_location(
    reply: AuthorReply,
    findings: Sequence[Finding],
) -> tuple[list[Finding], int]:
    """仅按坐标（行内锚定 / file:line / 仅 file）匹配发现，不含过期或锁定过滤。"""
    if reply.is_inline_anchor:
        if reply.file is None or reply.line is None:
            return [], 0
        norm_file = _normalize_file(reply.file)
        return [f for f in findings if _normalize_file(f.file) == norm_file and f.line == reply.line], 2
    if reply.file is not None:
        norm_file = _normalize_file(reply.file)
        if reply.line is not None:
            return [f for f in findings if _normalize_file(f.file) == norm_file and f.line == reply.line], 2
        return [f for f in findings if _normalize_file(f.file) == norm_file], 1
    return [], 0


def _match_reply_targets(
    reply: AuthorReply,
    findings: Sequence[Finding],
    *,
    stale_location_fingerprints: Collection[str] = (),
    bound_reply_targets: Mapping[str, str] | None = None,
) -> tuple[list[Finding], int]:
    """唯一作者回复目标匹配规则（由 bind_author_replies、VerifiedFinding 与 VerifiedRound 共同复用）。

    - 对属于 stale_location_fingerprints 的跨 HEAD 结转且未在新 HEAD 重新定位的发现，
      仅允许显式 reply.finding_id 匹配，严禁按 (file, line) / 行内锚定或文件坐标绑定。
    - 对无显式 finding_id 且未在 bound_reply_targets 中显式锁定到非过期目标的坐标/行内回复，
      只要其坐标也命中了任何过期结转发现，即判为跨 HEAD 坐标歧义并返回空匹配，严禁排掉过期发现后把同坐标新发现当作唯一目标。
    - 对已在 bound_reply_targets 中锁定目标指纹的 loc / inline 回复，仅允许匹配该锁定指纹，禁止改绑其他发现。
    """
    if reply.finding_id is not None:
        prefix = reply.finding_id.strip().lower()
        return [f for f in findings if f.finding_id.startswith(prefix)], 3
    stale = (
        frozenset(fp.strip().lower() for fp in stale_location_fingerprints)
        if stale_location_fingerprints
        else frozenset()
    )
    pinned_fid = bound_reply_targets.get(reply.reply_key) if bound_reply_targets else None
    raw_matched, specificity = _match_reply_location(reply, findings)
    if not raw_matched:
        return [], 0
    if pinned_fid is not None:
        if pinned_fid in stale:
            return [], 0
        matched = [f for f in raw_matched if f.finding_id == pinned_fid]
        return matched, specificity
    if stale and any(f.finding_id in stale for f in raw_matched):
        return [], 0
    return raw_matched, specificity


def parse_wontfix_replies(
    comments: Sequence[Mapping[str, Any]],
    *,
    allowed_authors: Collection[str],
) -> tuple[AuthorReply, ...]:
    """解析白名单作者的 `不修：<理由>` 回复；拒绝机器人、缺失 comment_id 或非白名单作者，并按 CommonMark 隔离非可见块。"""
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
        if parse_comment_marker(body) is not None:
            continue
        if _is_bot_comment(comment):
            continue

        author = _extract_comment_author(comment)
        if author is None or author.lower() not in allowed:
            continue

        comment_id = _extract_comment_id(comment)
        if comment_id is None:
            continue
        fallback_file, fallback_line = _extract_comment_file_and_line(comment)

        seen_exact: set[tuple[str | None, str | None, int | None, bool, str]] = set()
        for raw_match, line_tokens in _extract_visible_paragraph_lines(body):
            leading_ws = len(raw_match) - len(raw_match.lstrip(" \t"))
            stripped_match = raw_match.strip(" \t")
            match = _WONTFIX_HEAD_RE.match(stripped_match)
            if not match:
                continue
            raw_display_reason = _extract_display_slice(line_tokens, leading_ws + match.start("reason"))
            reason = _clean_display_reason(raw_display_reason)
            if not reason:
                continue

            raw_id = match.group("id_bracket") or match.group("id_bare") or match.group("id_paren")
            finding_id = raw_id.lower() if raw_id else None

            raw_path = match.group("path_prefix") or match.group("path_paren")
            raw_line_num = match.group("line_prefix") or match.group("line_paren")
            is_inline_anchor = False
            if raw_path:
                try:
                    file_path: str | None = _normalize_file(raw_path)
                except ConvergenceError:
                    continue
                line_num: int | None = int(raw_line_num) if raw_line_num else None
            elif finding_id is None:
                file_path = fallback_file
                line_num = fallback_line
                is_inline_anchor = True
            else:
                file_path = None
                line_num = None

            norm_reason = _normalize_fingerprint_text(reason, "reason")
            exact_sig = (finding_id, file_path, line_num, is_inline_anchor, norm_reason)
            if exact_sig in seen_exact:
                continue
            seen_exact.add(exact_sig)

            # 仅对完全相同的 (锚点形态, 归一化理由) 做幂等去重；不同理由指令全部保留交由下游按解析后最终目标整组裁决
            replies.append(
                AuthorReply(
                    finding_id=finding_id,
                    file=file_path,
                    line=line_num,
                    reason=reason,
                    comment_id=comment_id,
                    author=author,
                    is_inline_anchor=is_inline_anchor,
                )
            )
    return tuple(replies)


def _analyze_author_replies(
    findings: Sequence[Finding],
    replies: Sequence[AuthorReply],
    *,
    consumed_reply_keys: Collection[str] = (),
    consumed_comment_ids: Collection[str] = (),
    stale_location_fingerprints: Collection[str] = (),
    bound_reply_targets: Mapping[str, str] | Collection[tuple[str, str]] = (),
) -> tuple[dict[str, AuthorReply], dict[str, frozenset[str]]]:
    """同时计算唯一绑定回复与每个发现关联的全部未消费回复键（含 reply_key 与 comment:resolved:fp）。"""
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

    consumed_keys = _validate_consumed_reply_keys(consumed_reply_keys, "consumed_reply_keys")
    consumed_cids = _normalize_str_collection(consumed_comment_ids, "consumed_comment_ids")
    stale_fps = _normalize_str_collection(
        stale_location_fingerprints,
        "stale_location_fingerprints",
        lowercase=True,
    )
    pinned_targets = _normalize_bound_reply_targets(bound_reply_targets, "bound_reply_targets")

    validated_replies: list[AuthorReply] = []
    for reply in replies:
        if not isinstance(reply, AuthorReply):
            raise ConvergenceError(f"replies 元素必须是 AuthorReply：{reply!r}")
        _require_non_empty_str(reply.comment_id, "reply.comment_id")
        validated_replies.append(reply)

    matched_keys_by_id: dict[str, set[str]] = {}
    comment_target_reasons: dict[tuple[str, str], set[str]] = {}
    resolved_entries: list[tuple[str, str, int, AuthorReply]] = []
    for reply in validated_replies:
        cid = reply.comment_id.strip()
        if reply.reply_key in consumed_keys:
            continue
        if cid in consumed_cids:
            continue

        matches, specificity = _match_reply_targets(
            reply,
            finding_list,
            stale_location_fingerprints=stale_fps,
            bound_reply_targets=pinned_targets,
        )
        if not matches:
            if reply.finding_id is None and reply.reply_key not in pinned_targets and stale_fps:
                raw_loc_matches, _ = _match_reply_location(reply, finding_list)
                if any(f.finding_id in stale_fps for f in raw_loc_matches):
                    for loc_finding in raw_loc_matches:
                        matched_keys_by_id.setdefault(loc_finding.finding_id, set()).add(reply.reply_key)
            continue

        norm_reason = _normalize_fingerprint_text(reply.reason, "reason")
        for matched_finding in matches:
            matched_fid = matched_finding.finding_id
            keys_set = matched_keys_by_id.setdefault(matched_fid, set())
            keys_set.add(reply.reply_key)
            keys_set.add(_resolved_reply_key(cid, matched_fid))
            if _resolved_reply_key(cid, matched_fid) not in consumed_keys:
                comment_target_reasons.setdefault((cid, matched_fid), set()).add(norm_reason)

        # 命中 0 个或超过 1 个活跃候选均拒绝绑定（绝不让一条歧义回复解除多个发现）
        if len(matches) != 1:
            continue

        target_id = matches[0].finding_id
        if _resolved_reply_key(cid, target_id) in consumed_keys:
            continue

        resolved_entries.append((cid, target_id, specificity, reply))

    # 同一 (comment_id, target_id) 下聚合全部命中回复后若存在 > 1 种不同归一化理由，整组拒收
    conflicting_comment_targets = {pair for pair, reasons in comment_target_reasons.items() if len(reasons) > 1}
    best_by_id: dict[str, tuple[int, AuthorReply]] = {}
    for cid, target_id, specificity, reply in resolved_entries:
        if (cid, target_id) in conflicting_comment_targets:
            continue
        current = best_by_id.get(target_id)
        if current is None or specificity >= current[0]:
            best_by_id[target_id] = (specificity, reply)

    return (
        {fid: pair[1] for fid, pair in best_by_id.items()},
        {fid: frozenset(keys) for fid, keys in matched_keys_by_id.items()},
    )


def bind_author_replies(
    findings: Sequence[Finding],
    replies: Sequence[AuthorReply],
    *,
    consumed_reply_keys: Collection[str] = (),
    consumed_comment_ids: Collection[str] = (),
    stale_location_fingerprints: Collection[str] = (),
    bound_reply_targets: Mapping[str, str] | Collection[tuple[str, str]] = (),
) -> dict[str, AuthorReply]:
    """面向整个候选集合做作者回复唯一绑定。

    规则：
    - 忽略已消费（consumed_reply_keys / consumed_comment_ids）的历史回复；
    - 对已在 bound_reply_targets 中锁定目标的 loc / inline 回复，仅允许匹配其锁定指纹；
    - 对属于 stale_location_fingerprints 的发现，仅允许显式 finding_id 绑定，禁止按坐标锚定；
    - 任一条回复若命中超过 1 个活跃候选，视为歧义，拒绝绑定到任何发现；
    - 同一评论中的多条回复若各自唯一指向不同发现，可分别绑定；
    - 同一发现被多条有效回复命中时，按锚点精度（ID > 文件+行号 > 仅文件）择优，同精度取最新回复。
    """
    bound, _ = _analyze_author_replies(
        findings,
        replies,
        consumed_reply_keys=consumed_reply_keys,
        consumed_comment_ids=consumed_comment_ids,
        stale_location_fingerprints=stale_location_fingerprints,
        bound_reply_targets=bound_reply_targets,
    )
    return bound


@dataclass(frozen=True)
class VerifiedFinding:
    finding: Finding
    verdict: VerificationVerdict
    verifier_model: str
    verifier_evidence: str
    round_number: int
    head_sha: str
    author_reply: AuthorReply | None = None
    related_reply_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.finding, Finding):
            raise ConvergenceError("VerifiedFinding.finding 必须是 Finding")
        if not isinstance(self.verdict, VerificationVerdict):
            raise ConvergenceError("VerifiedFinding.verdict 必须是 VerificationVerdict")
        _require_non_empty_str(self.verifier_model, "verifier_model")
        _require_visible_markdown_text(self.verifier_evidence, "verifier_evidence")
        if type(self.round_number) is not int or self.round_number < 1:
            raise ConvergenceError(f"VerifiedFinding.round_number 必须是 >= 1 的整数：{self.round_number!r}")
        norm_head = _normalize_commit_sha(self.head_sha, "VerifiedFinding.head_sha")
        object.__setattr__(self, "head_sha", norm_head)
        if self.author_reply is not None and not isinstance(self.author_reply, AuthorReply):
            raise ConvergenceError("VerifiedFinding.author_reply 必须是 AuthorReply 或 None")
        if self.verdict == VerificationVerdict.RESOLVED_BY_WONTFIX:
            if self.author_reply is None:
                raise ConvergenceError("verdict=resolved_by_wontfix 时必须绑定非空 author_reply")
            _require_non_empty_str(self.author_reply.comment_id, "author_reply.comment_id")
            _require_non_empty_str(self.author_reply.author, "author_reply.author")
            matched, _ = _match_reply_targets(self.author_reply, (self.finding,))
            if len(matched) != 1 or matched[0].finding_id != self.finding.finding_id:
                raise ConvergenceError(
                    f"verdict=resolved_by_wontfix 绑定的 author_reply（comment_id={self.author_reply.comment_id}）"
                    f"与发现 {self.finding.finding_id} 不匹配"
                )
        if not isinstance(self.related_reply_keys, tuple):
            raise ConvergenceError("VerifiedFinding.related_reply_keys 必须是字符串元组")
        for rk in self.related_reply_keys:
            _validate_consumed_reply_key(rk, "related_reply_keys[]")

    @property
    def is_blocking(self) -> bool:
        return self.verdict == VerificationVerdict.CONFIRMED and self.finding.severity == Severity.IMPORTANT


def is_blocking_finding(verified_finding: VerifiedFinding) -> bool:
    """唯一阻断判据（#1927 第 3 条）：仅核实成立的 Important 阻断合并。"""
    return verified_finding.is_blocking


@dataclass(frozen=True)
class RoundHistoryEntry:
    round_number: int
    head_sha: str
    posted_fingerprints: frozenset[str]
    unresolved_important: tuple[Finding, ...]
    panel: ReviewPanel
    finder_session_ids: frozenset[str]
    resolved_fingerprints: frozenset[str] = frozenset()
    consumed_reply_keys: frozenset[str] = frozenset()
    rejected_fingerprints: frozenset[str] = frozenset()
    pending_non_blocking: tuple[VerifiedFinding, ...] = ()
    outcome: RoundOutcome | None = None
    relocated_fingerprints: frozenset[str] = frozenset()
    bound_reply_targets: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if type(self.round_number) is not int or self.round_number <= 0:
            raise ConvergenceError(f"round_number 必须是正整数：{self.round_number!r}")
        norm_head = _normalize_commit_sha(self.head_sha, "head_sha")
        object.__setattr__(self, "head_sha", norm_head)
        if not isinstance(self.posted_fingerprints, frozenset):
            raise ConvergenceError("posted_fingerprints 必须是 frozenset[str]")
        for fp in self.posted_fingerprints:
            _require_non_empty_str(fp, "posted_fingerprints[]")
        if not isinstance(self.unresolved_important, tuple):
            raise ConvergenceError("unresolved_important 必须是 Finding 元组")
        if not isinstance(self.panel, ReviewPanel):
            raise ConvergenceError("RoundHistoryEntry.panel 必须是 ReviewPanel")

        panel_verifier_family = self.panel.verifier_family
        panel_finders = frozenset(m.strip() for m in self.panel.finder_models)
        unresolved_ids: set[str] = set()
        for item in self.unresolved_important:
            if not isinstance(item, Finding):
                raise ConvergenceError("unresolved_important 元素必须是 Finding")
            if item.severity != Severity.IMPORTANT:
                raise ConvergenceError(f"unresolved_important 仅允许 Important 发现，收到 {item.severity.value}")
            fid = item.finding_id
            if fid in unresolved_ids:
                raise ConvergenceError(f"unresolved_important 含重复指纹：{fid}")
            unresolved_ids.add(fid)
            real_models = _real_source_models(item.source_models)
            if not real_models:
                raise ConvergenceError(f"历史未解除发现 {fid} 缺少真实 finder source_models")
            for src_model in real_models:
                src_family = infer_model_family(src_model)
                if panel_verifier_family is not None and src_family == panel_verifier_family:
                    raise ConvergenceError(
                        f"历史轮次 {self.round_number} 核实者与未解除发现 {fid} 来源模型 {src_model!r} 同家族"
                    )
            if self.round_number == 1:
                unknown = [m for m in real_models if m not in panel_finders]
                if unknown:
                    raise ConvergenceError(
                        f"第 1 轮历史未解除发现 {fid} 的来源模型 {unknown!r} 不在 panel.finder_models 中"
                    )

        if self.outcome is None:
            if not self.unresolved_important:
                derived_outcome = RoundOutcome.PASS
            elif self.round_number > MAX_AUTO_ROUNDS:
                derived_outcome = RoundOutcome.NON_CONVERGENT
            else:
                derived_outcome = RoundOutcome.BLOCKED
            object.__setattr__(self, "outcome", derived_outcome)
        else:
            if not isinstance(self.outcome, RoundOutcome):
                raise ConvergenceError(f"RoundHistoryEntry.outcome 必须是 RoundOutcome：{self.outcome!r}")
            if self.outcome == RoundOutcome.PASS and self.unresolved_important:
                raise ConvergenceError("outcome=PASS 时 unresolved_important 必须为空")
            if self.outcome != RoundOutcome.PASS and not self.unresolved_important:
                raise ConvergenceError("outcome 非 PASS 时 unresolved_important 不能为空")

        if not isinstance(self.resolved_fingerprints, frozenset):
            raise ConvergenceError("resolved_fingerprints 必须是 frozenset[str]")
        for fp in self.resolved_fingerprints:
            _require_non_empty_str(fp, "resolved_fingerprints[]")
        if not isinstance(self.rejected_fingerprints, frozenset):
            raise ConvergenceError("rejected_fingerprints 必须是 frozenset[str]")
        for fp in self.rejected_fingerprints:
            _require_non_empty_str(fp, "rejected_fingerprints[]")
        if not self.panel.require_verifier and (self.resolved_fingerprints or self.rejected_fingerprints):
            raise ConvergenceError("快审直通轮次无独立核实者，禁止记录 resolved_fingerprints 或 rejected_fingerprints")
        if self.resolved_fingerprints & self.rejected_fingerprints:
            raise ConvergenceError("同一轮次内 resolved_fingerprints 与 rejected_fingerprints 不得重叠")
        cleared_ids = self.resolved_fingerprints | self.rejected_fingerprints
        if unresolved_ids & cleared_ids:
            raise ConvergenceError("同一轮次内 unresolved_important 与已解除/驳回指纹不得重叠")
        if self.posted_fingerprints & cleared_ids:
            raise ConvergenceError("同一轮次内 posted_fingerprints 与已解除/驳回指纹不得重叠")
        if not isinstance(self.consumed_reply_keys, frozenset):
            raise ConvergenceError("consumed_reply_keys 必须是 frozenset[str]")
        for rk in self.consumed_reply_keys:
            _validate_consumed_reply_key(rk, "consumed_reply_keys[]")
        if not isinstance(self.finder_session_ids, frozenset):
            raise ConvergenceError("finder_session_ids 必须是 frozenset[str]")
        norm_sessions = frozenset(_require_non_empty_str(sid, "finder_session_ids[]") for sid in self.finder_session_ids)
        if len(norm_sessions) != len(self.panel.finder_models):
            raise ConvergenceError(
                f"RoundHistoryEntry.finder_session_ids 数量必须等于 panel.finder_models 数量："
                f"期望 {len(self.panel.finder_models)} 个，实际收到 {len(norm_sessions)} 个"
            )
        object.__setattr__(self, "finder_session_ids", norm_sessions)
        if not isinstance(self.pending_non_blocking, tuple):
            raise ConvergenceError("pending_non_blocking 必须是 VerifiedFinding 元组")
        pending_ids: set[str] = set()
        for vf in self.pending_non_blocking:
            if not isinstance(vf, VerifiedFinding):
                raise ConvergenceError("pending_non_blocking 元素必须是 VerifiedFinding")
            if vf.verdict != VerificationVerdict.CONFIRMED or vf.is_blocking:
                raise ConvergenceError("pending_non_blocking 仅允许核实成立的非阻断发现")
            if vf.round_number > self.round_number:
                raise ConvergenceError(
                    f"pending_non_blocking 发现 {vf.finding.finding_id} 的 round_number={vf.round_number} "
                    f"不得大于历史轮次 {self.round_number}"
                )
            fid = vf.finding.finding_id
            if fid in pending_ids:
                raise ConvergenceError(f"pending_non_blocking 含重复指纹：{fid}")
            pending_ids.add(fid)
        if pending_ids & (self.posted_fingerprints | cleared_ids):
            raise ConvergenceError("pending_non_blocking 不得与已贴出或已解除/驳回指纹重叠")
        if not isinstance(self.relocated_fingerprints, frozenset):
            raise ConvergenceError("relocated_fingerprints 必须是 frozenset[str]")
        norm_relocated = frozenset(
            _require_non_empty_str(fp, "relocated_fingerprints[]").lower()
            for fp in self.relocated_fingerprints
        )
        if not (norm_relocated <= unresolved_ids):
            extra_relocated = sorted(norm_relocated - unresolved_ids)
            raise ConvergenceError(
                f"relocated_fingerprints 必须是 unresolved_important 指纹的子集，发现多余指纹：{extra_relocated!r}"
            )
        object.__setattr__(self, "relocated_fingerprints", norm_relocated)
        _validate_bound_reply_targets_frozenset(self.bound_reply_targets, "RoundHistoryEntry.bound_reply_targets")


def _validate_history_chain(
    history: Sequence[RoundHistoryEntry],
) -> tuple[frozenset[str], dict[str, tuple[str, str, int | None] | None], dict[str, str]]:
    """校验连续轮次历史链的完整性、会话唯一性、跨轮异家族核实、解除依据、回复目标锁定与未解除 Important 守恒。"""
    allowed_historical_finders: set[str] = set()
    historical_session_ids: set[str] = set()
    historical_consumed_reply_keys: set[str] = set()
    historical_bound_targets: dict[str, str] = {}
    prev_entry: RoundHistoryEntry | None = None
    prev_unresolved_sources: dict[str, frozenset[str]] = {}
    prev_unresolved_ids: set[str] = set()
    located_anchor_by_fp: dict[str, tuple[str, str, int | None] | None] = {}
    for idx, entry in enumerate(history, start=1):
        if not isinstance(entry, RoundHistoryEntry):
            raise ConvergenceError(f"history[{idx - 1}] 必须是 RoundHistoryEntry")
        if entry.round_number != idx:
            raise ConvergenceError(f"history 轮次必须从 1 连续递增：期望 {idx}，实际 {entry.round_number}")
        _normalize_commit_sha(entry.head_sha, f"history[{idx - 1}].head_sha")

        entry_bound_targets = _validate_bound_reply_targets_frozenset(
            entry.bound_reply_targets,
            f"history[{idx - 1}].bound_reply_targets",
        )
        _merge_bound_reply_targets(
            historical_bound_targets,
            entry_bound_targets,
            f"history[{idx - 1}].bound_reply_targets",
        )

        reused_hist_sessions = entry.finder_session_ids & historical_session_ids
        if reused_hist_sessions:
            raise ConvergenceError(
                f"history[{idx - 1}] 存在跨轮复用的 finder session_id：{sorted(reused_hist_sessions)!r}"
            )
        historical_session_ids.update(entry.finder_session_ids)

        if not entry.panel.require_verifier and (entry.resolved_fingerprints or entry.rejected_fingerprints):
            raise ConvergenceError(
                f"历史第 {idx} 轮为快审直通模式（无独立核实者），禁止记录 resolved_fingerprints 或 rejected_fingerprints"
            )
        entry_verifier_family = entry.panel.verifier_family
        if entry_verifier_family is not None:
            for prev_fp, prev_sources in prev_unresolved_sources.items():
                for src_model in prev_sources:
                    if infer_model_family(src_model) == entry_verifier_family:
                        raise ConvergenceError(
                            f"历史第 {idx} 轮核实者模型 {entry.panel.verifier_model!r}（家族 {entry_verifier_family}）"
                            f"不得与前轮结转发现 {prev_fp} 来源模型 {src_model!r} 同家族"
                        )

        entry_finders = frozenset(m.strip() for m in entry.panel.finder_models)
        allowed_historical_finders.update(entry_finders)

        seen_hist_ids: set[str] = set()
        next_located_anchor: dict[str, tuple[str, str, int | None] | None] = {}
        for item in entry.unresolved_important:
            if item.severity != Severity.IMPORTANT:
                raise ConvergenceError(f"历史未解除发现仅允许 Important，收到 {item.severity.value}")
            fid = item.finding_id
            if fid in seen_hist_ids:
                raise ConvergenceError(f"history[{idx - 1}].unresolved_important 含重复指纹 {fid}")
            seen_hist_ids.add(fid)
            real_models = _real_source_models(item.source_models)
            if not real_models:
                raise ConvergenceError(f"历史发现 {fid} 缺少真实 finder source_models，禁止绕过异家族核实校验")
            for src_model in real_models:
                src_family = infer_model_family(src_model)
                if entry_verifier_family is not None and src_family == entry_verifier_family:
                    raise ConvergenceError(
                        f"历史第 {idx} 轮核实者模型 {entry.panel.verifier_model!r} "
                        f"不得与发现 {fid} 来源模型 {src_model!r} 同家族"
                    )
            prev_sources = prev_unresolved_sources.get(fid, frozenset())
            missing_sources = prev_sources - set(real_models)
            if missing_sources:
                raise ConvergenceError(
                    f"历史第 {idx} 轮未解除发现 {fid} 丢失了前轮来源模型 {sorted(missing_sources)!r}，"
                    "禁止缩减 source_models 绕过异家族核实约束"
                )
            allowed_in_entry = entry_finders | prev_sources
            unknown_models = [
                m for m in real_models if m not in allowed_in_entry or m not in allowed_historical_finders
            ]
            if unknown_models:
                raise ConvergenceError(
                    f"历史第 {idx} 轮未解除发现 {fid} 的来源模型 {unknown_models!r} "
                    f"既不在当轮 panel.finder_models 中，也非合法累计历史结转来源"
                )
            item_loc = (_normalize_file(item.file), item.line)
            if fid in prev_unresolved_ids:
                if fid in entry.relocated_fingerprints:
                    if not (set(real_models) & entry_finders):
                        raise ConvergenceError(
                            f"历史第 {idx} 轮声明重新定位了发现 {fid}，但其 source_models {real_models!r} 不含当轮任何 finder"
                        )
                    next_located_anchor[fid] = (entry.head_sha, item_loc[0], item_loc[1])
                else:
                    prev_anchor = located_anchor_by_fp.get(fid)
                    if prev_anchor is not None and (prev_anchor[1], prev_anchor[2]) == item_loc:
                        next_located_anchor[fid] = prev_anchor
                    else:
                        next_located_anchor[fid] = None
            else:
                next_located_anchor[fid] = (entry.head_sha, item_loc[0], item_loc[1])

        parsed_entry_consumed: list[tuple[str, str, str, str]] = []
        for rk in entry.consumed_reply_keys:
            cid, kind, payload = _parse_consumed_reply_key(rk, f"history[{idx - 1}].consumed_reply_keys[]")
            parsed_entry_consumed.append((rk, cid, kind, payload))
        validated_entry_consumed = frozenset(rk for rk, _, _, _ in parsed_entry_consumed)

        for raw_fp in entry.resolved_fingerprints:
            norm_fp = raw_fp.strip().lower()
            can_resolve_by_fix = (
                prev_entry is not None
                and norm_fp in prev_unresolved_sources
                and entry.head_sha != prev_entry.head_sha
            )
            if not can_resolve_by_fix:
                has_wontfix_proof = any(
                    rk not in historical_consumed_reply_keys and kind == "resolved" and payload == norm_fp
                    for rk, _, kind, payload in parsed_entry_consumed
                )
                if not has_wontfix_proof:
                    raise ConvergenceError(
                        f"历史第 {idx} 轮将发现 {norm_fp} 标为已解除（resolved_fingerprints），"
                        "但既不满足新提交修复条件（须为前轮结转项且 head_sha 相对前轮有新提交），"
                        "也缺少未被前轮消费过的作者不修回复消费记录（comment:<id>:resolved:<fp>）"
                    )

        unaccounted = prev_unresolved_ids - (seen_hist_ids | entry.resolved_fingerprints | entry.rejected_fingerprints)
        if unaccounted:
            raise ConvergenceError(
                f"历史第 {idx} 轮遗漏了前轮未解除的 Important 发现（无结转/解除/驳回记录）：{sorted(unaccounted)!r}"
            )

        historical_consumed_reply_keys.update(validated_entry_consumed)
        prev_entry = entry
        if entry.outcome == RoundOutcome.PASS:
            prev_unresolved_sources = {}
            prev_unresolved_ids = set()
            located_anchor_by_fp = {}
        else:
            prev_unresolved_sources = {
                f.finding_id: frozenset(_real_source_models(f.source_models))
                for f in entry.unresolved_important
            }
            prev_unresolved_ids = seen_hist_ids
            located_anchor_by_fp = next_located_anchor
    return frozenset(historical_session_ids), located_anchor_by_fp, historical_bound_targets


@dataclass(frozen=True)
class FinderBatch:
    """单个独立 finder 会话的产出批次：强绑定模型名、会话 ID、HEAD SHA 与每条发现的来源归属。"""

    model: str
    session_id: str
    head_sha: str
    findings: tuple[Finding, ...] = ()

    def __post_init__(self) -> None:
        norm_model = _require_non_empty_str(self.model, "FinderBatch.model")
        norm_session = _require_non_empty_str(self.session_id, "FinderBatch.session_id")
        norm_head = _normalize_commit_sha(self.head_sha, "FinderBatch.head_sha")
        object.__setattr__(self, "model", norm_model)
        object.__setattr__(self, "session_id", norm_session)
        object.__setattr__(self, "head_sha", norm_head)
        if not isinstance(self.findings, tuple):
            raise ConvergenceError("FinderBatch.findings 必须是 Finding 元组")
        for item in self.findings:
            if not isinstance(item, Finding):
                raise ConvergenceError(f"FinderBatch.findings 元素必须是 Finding：{item!r}")
            if not item.source_models:
                raise ConvergenceError(f"FinderBatch 发现 {item.finding_id} 缺少 source_models")
            item_models = {m.strip() for m in item.source_models}
            if item_models != {norm_model}:
                raise ConvergenceError(
                    f"FinderBatch(model={norm_model!r}) 的发现 {item.finding_id} "
                    f"来源模型 {item.source_models!r} 必须非空且仅含 {norm_model!r}"
                )


@dataclass(frozen=True)
class RoundCandidates:
    """不可绕过的单轮核实候选单一事实源：强绑定轮次、HEAD、面板、完整 finder 批次与连续历史链。"""

    round_number: int
    head_sha: str
    panel: ReviewPanel
    finder_batches: tuple[FinderBatch, ...]
    history: tuple[RoundHistoryEntry, ...] = ()
    prior_important: tuple[Finding, ...] = field(init=False)
    current_round_findings: tuple[Finding, ...] = field(init=False)
    findings: tuple[Finding, ...] = field(init=False)
    stale_location_fingerprints: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        if type(self.round_number) is not int or self.round_number < 1:
            raise ConvergenceError(f"RoundCandidates.round_number 必须是 >= 1 的整数：{self.round_number!r}")
        norm_head = _normalize_commit_sha(self.head_sha, "RoundCandidates.head_sha")
        object.__setattr__(self, "head_sha", norm_head)
        if not isinstance(self.panel, ReviewPanel):
            raise ConvergenceError("RoundCandidates.panel 必须是 ReviewPanel")
        if not isinstance(self.finder_batches, tuple):
            raise ConvergenceError("RoundCandidates.finder_batches 必须是 FinderBatch 元组")
        for batch in self.finder_batches:
            if not isinstance(batch, FinderBatch):
                raise ConvergenceError(f"RoundCandidates.finder_batches 元素必须是 FinderBatch：{batch!r}")
            if batch.head_sha != norm_head:
                raise ConvergenceError(
                    f"FinderBatch(session_id={batch.session_id!r}) 的 head_sha={batch.head_sha!r} "
                    f"与当前轮 head_sha={norm_head!r} 不匹配"
                )
        if not isinstance(self.history, tuple):
            raise ConvergenceError("RoundCandidates.history 必须是 RoundHistoryEntry 元组")
        if len(self.history) != self.round_number - 1:
            raise ConvergenceError(
                f"历史链长度必须等于 round_number - 1：期望 {self.round_number - 1}，实际 {len(self.history)}"
            )

        verifier_family = self.panel.verifier_family
        historical_session_ids, located_anchor_by_fp, _ = _validate_history_chain(self.history)

        if not self.history or self.history[-1].outcome == RoundOutcome.PASS:
            prior_important: tuple[Finding, ...] = ()
        else:
            prior_important = self.history[-1].unresolved_important

        # 仅对当前轮实际结转的 prior_important 校验与当前轮核实者的异家族约束，不阻拦已结清历史发现
        if verifier_family is not None:
            for prior in prior_important:
                fid = prior.finding_id
                for src_model in _real_source_models(prior.source_models):
                    src_family = infer_model_family(src_model)
                    if src_family == verifier_family:
                        raise ConvergenceError(
                            f"核实者模型 {self.panel.verifier_model!r}（家族 {verifier_family}）"
                            f"不得与本轮结转发现 {fid} 来源模型 {src_model!r} 同家族"
                        )

        # 校验 finder 批次完备性：逐槽位多重集精确匹配 panel.finder_models，且会话 ID 轮内与跨轮均不重复
        if len(self.finder_batches) != len(self.panel.finder_models):
            raise ConvergenceError(
                f"finder_batches 数量必须与 panel.finder_models 一致："
                f"期望 {len(self.panel.finder_models)} 批，实际收到 {len(self.finder_batches)} 批"
            )
        expected_models = Counter(m.strip() for m in self.panel.finder_models)
        actual_models = Counter(b.model for b in self.finder_batches)
        if actual_models != expected_models:
            raise ConvergenceError(
                f"finder_batches 模型分布 {dict(actual_models)!r} 与 panel.finder_models {dict(expected_models)!r} 不匹配"
            )
        session_ids = [b.session_id for b in self.finder_batches]
        if len(set(session_ids)) != len(session_ids):
            raise ConvergenceError(f"本轮 finder_batches 存在重复 session_id：{session_ids!r}")
        reused_from_history = [sid for sid in session_ids if sid in historical_session_ids]
        if reused_from_history:
            raise ConvergenceError(
                f"本轮 finder_batches 复用了历史轮次已使用过的 session_id：{reused_from_history!r}"
            )

        # 1. 轮内合并（保留当前轮最新定位）
        current_round_findings = merge_and_dedupe_findings([(b.model, b.findings) for b in self.finder_batches])

        # 2. 跨轮结转合并：同指纹在本轮重现时保留当前轮新定位与证据，锁定 severity=IMPORTANT 并合并 source_models；
        # 未在本轮重现且最后一次定位提交 != 当前 HEAD 的发现，保留 prior.line 供展示但 fail-closed 记入 stale_location_fingerprints
        current_by_fp = {f.finding_id: f for f in current_round_findings}
        merged_by_fp: dict[str, Finding] = dict(current_by_fp)
        stale_fps: set[str] = set()
        for prior in prior_important:
            fp = prior.finding_id
            prior_sources = set(_real_source_models(prior.source_models))
            if fp in current_by_fp:
                cur = current_by_fp[fp]
                combined_sources = tuple(sorted(set(_real_source_models(cur.source_models)) | prior_sources))
                merged_by_fp[fp] = Finding(
                    severity=Severity.IMPORTANT,
                    file=_normalize_file(cur.file),
                    line=cur.line,
                    category=cur.category,
                    failure_scenario=cur.failure_scenario,
                    evidence=cur.evidence,
                    class_scope=cur.class_scope,
                    source_models=combined_sources,
                )
            else:
                anchor = located_anchor_by_fp.get(fp)
                if anchor is None or anchor != (norm_head, _normalize_file(prior.file), prior.line):
                    stale_fps.add(fp)
                merged_by_fp[fp] = Finding(
                    severity=Severity.IMPORTANT,
                    file=_normalize_file(prior.file),
                    line=prior.line,
                    category=prior.category,
                    failure_scenario=prior.failure_scenario,
                    evidence=prior.evidence,
                    class_scope=prior.class_scope,
                    source_models=tuple(sorted(prior_sources)),
                )

        merged = tuple(sorted(merged_by_fp.values(), key=_finding_sort_key))
        object.__setattr__(self, "prior_important", prior_important)
        object.__setattr__(self, "current_round_findings", current_round_findings)
        object.__setattr__(self, "findings", merged)
        object.__setattr__(self, "stale_location_fingerprints", frozenset(stale_fps))


def build_round_candidates(
    *,
    round_number: int,
    head_sha: str,
    panel: ReviewPanel,
    finder_batches: Sequence[FinderBatch],
    history: Sequence[RoundHistoryEntry] = (),
) -> RoundCandidates:
    """构建经完整面板、会话唯一性与连续历史链强校验的 RoundCandidates。"""
    if not isinstance(finder_batches, Sequence) or isinstance(finder_batches, (str, bytes)):
        raise ConvergenceError("finder_batches 必须是 FinderBatch 序列")
    if not isinstance(history, Sequence) or isinstance(history, (str, bytes)):
        raise ConvergenceError("history 必须是 RoundHistoryEntry 序列")
    return RoundCandidates(
        round_number=round_number,
        head_sha=head_sha,
        panel=panel,
        finder_batches=tuple(finder_batches),
        history=tuple(history),
    )


@dataclass(frozen=True)
class VerifiedRound:
    """核实后的整轮不可变结果：强绑定 RoundCandidates 与一一对应的 VerifiedFinding 元组。"""

    candidates: RoundCandidates
    verdicts: tuple[VerifiedFinding, ...]
    bound_reply_targets: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, RoundCandidates):
            raise ConvergenceError("VerifiedRound.candidates 必须是 RoundCandidates")
        if not isinstance(self.verdicts, tuple):
            raise ConvergenceError("VerifiedRound.verdicts 必须是 VerifiedFinding 元组")

        candidates_by_id = {f.finding_id: f for f in self.candidates.findings}
        prior_important_ids = frozenset(f.finding_id for f in self.candidates.prior_important)
        history_consumed: frozenset[str] = frozenset().union(
            *(entry.consumed_reply_keys for entry in self.candidates.history)
        )
        history_bound_targets = _collect_history_bound_targets(self.candidates.history)
        explicit_bound_targets = _validate_bound_reply_targets_frozenset(
            self.bound_reply_targets,
            "VerifiedRound.bound_reply_targets",
        )
        effective_bound_targets = dict(history_bound_targets)
        _merge_bound_reply_targets(
            effective_bound_targets,
            explicit_bound_targets,
            "VerifiedRound.bound_reply_targets",
        )
        panel = self.candidates.panel

        expected_verifier: str
        if panel.require_verifier:
            expected_verifier = _require_non_empty_str(panel.verifier_model, "panel.verifier_model")
            verifier_family = infer_model_family(expected_verifier)
        else:
            expected_verifier = f"quick-pass:{panel.finder_models[0].strip()}"
            verifier_family = None

        seen_ids: set[str] = set()
        for vf in self.verdicts:
            if not isinstance(vf, VerifiedFinding):
                raise ConvergenceError(f"VerifiedRound.verdicts 元素必须是 VerifiedFinding：{vf!r}")
            fid = vf.finding.finding_id
            if vf.round_number != self.candidates.round_number or vf.head_sha != self.candidates.head_sha:
                raise ConvergenceError(
                    f"VerifiedRound 发现 {fid} 绑定坐标 (round={vf.round_number}, head={vf.head_sha!r}) "
                    f"与当前轮 candidates (round={self.candidates.round_number}, head={self.candidates.head_sha!r}) 不匹配"
                )
            if fid not in candidates_by_id:
                raise ConvergenceError(f"VerifiedRound 包含候选清单外的发现：{fid}")
            if fid in seen_ids:
                raise ConvergenceError(f"VerifiedRound 含重复裁决指纹：{fid}")
            if vf.finding != candidates_by_id[fid]:
                raise ConvergenceError(f"VerifiedRound 发现 {fid} 与 candidates.findings 不一致")
            if vf.verifier_model.strip() != expected_verifier:
                raise ConvergenceError(
                    f"VerifiedRound 发现 {fid} 的 verifier_model={vf.verifier_model!r} 与期望 {expected_verifier!r} 不一致"
                )
            if not panel.require_verifier and vf.verdict != VerificationVerdict.CONFIRMED:
                raise ConvergenceError("快审直通模式无独立核实者，禁止使用非 CONFIRMED 裁决")
            if verifier_family is not None:
                for src_model in _real_source_models(vf.finding.source_models):
                    if infer_model_family(src_model) == verifier_family:
                        raise ConvergenceError(
                            f"核实者模型 {expected_verifier!r}（家族 {verifier_family}）"
                            f"不得与发现 {fid} 来源模型 {src_model!r} 同家族"
                        )
            if vf.verdict == VerificationVerdict.RESOLVED_BY_FIX:
                if fid not in prior_important_ids:
                    raise ConvergenceError(
                        f"发现 {fid} 不在本轮 prior_important 中，禁止标记为 resolved_by_fix（误报请标为 rejected/false_positive）"
                    )
                if not self.candidates.history or self.candidates.head_sha == self.candidates.history[-1].head_sha:
                    raise ConvergenceError(
                        f"发现 {fid} 所在轮次 head_sha={self.candidates.head_sha!r} 与上一轮相同（无新提交），"
                        "禁止标记为 resolved_by_fix"
                    )
            for rk in vf.related_reply_keys:
                pinned_for_rk = effective_bound_targets.get(rk)
                if pinned_for_rk is not None and pinned_for_rk != fid:
                    raise ConvergenceError(
                        f"发现 {fid} 的 related_reply_keys 包含已锁定到发现 {pinned_for_rk} 的回复键 {rk!r}"
                    )
            if vf.verdict == VerificationVerdict.RESOLVED_BY_WONTFIX:
                if vf.author_reply is None:
                    raise ConvergenceError(f"发现 {fid} 裁决为 resolved_by_wontfix 但缺少 author_reply")
                _require_non_empty_str(vf.author_reply.author, "author_reply.author")
                pinned_fid = effective_bound_targets.get(vf.author_reply.reply_key)
                if pinned_fid is not None and pinned_fid != fid:
                    raise ConvergenceError(
                        f"发现 {fid} 绑定的作者不修回复（{vf.author_reply.reply_key}）"
                        f"已锁定到发现 {pinned_fid}，禁止改绑到其他指纹"
                    )
                matched_targets, _ = _match_reply_targets(
                    vf.author_reply,
                    self.candidates.findings,
                    stale_location_fingerprints=self.candidates.stale_location_fingerprints,
                    bound_reply_targets=effective_bound_targets,
                )
                if len(matched_targets) != 1 or matched_targets[0].finding_id != fid:
                    raise ConvergenceError(
                        f"发现 {fid} 绑定的作者不修回复（comment_id={vf.author_reply.comment_id}）"
                        f"未唯一匹配本轮候选发现 {fid}"
                    )
                if (
                    vf.author_reply.reply_key in history_consumed
                    or _resolved_reply_key(vf.author_reply.comment_id, fid) in history_consumed
                ):
                    raise ConvergenceError(
                        f"发现 {fid} 绑定的作者不修回复（comment_id={vf.author_reply.comment_id}）已在历史轮次被消费，禁止复用"
                    )
            seen_ids.add(fid)

        missing = [f.finding_id for f in self.candidates.findings if f.finding_id not in seen_ids]
        if missing:
            raise ConvergenceError(f"VerifiedRound 遗漏候选发现：{', '.join(missing)}")

    @property
    def round_number(self) -> int:
        return self.candidates.round_number

    @property
    def head_sha(self) -> str:
        return self.candidates.head_sha

    @property
    def panel(self) -> ReviewPanel:
        return self.candidates.panel

    @property
    def history(self) -> tuple[RoundHistoryEntry, ...]:
        return self.candidates.history


def accept_quick_pass_findings(candidates: RoundCandidates) -> VerifiedRound:
    """低风险快审显式直通入口（仅允许 panel.require_verifier=False，并强绑定 RoundCandidates）。"""
    if not isinstance(candidates, RoundCandidates):
        raise ConvergenceError("candidates 必须是经面板强校验的 RoundCandidates")
    panel = candidates.panel
    if panel.require_verifier:
        raise ConvergenceError("当前审查面板要求独立核实（require_verifier=True），禁止走快审直通入口")

    quick_model = f"quick-pass:{panel.finder_models[0].strip()}"
    accepted: list[VerifiedFinding] = []
    for item in candidates.findings:
        real_models = _real_source_models(item.source_models)
        if not real_models:
            raise ConvergenceError(f"快审发现 {item.finding_id} 缺少真实 finder 模型来源")
        accepted.append(
            VerifiedFinding(
                finding=item,
                verdict=VerificationVerdict.CONFIRMED,
                verifier_model=quick_model,
                verifier_evidence=f"低风险快审直通（免独立核实，来源：{', '.join(real_models)}）：{item.evidence}",
                round_number=candidates.round_number,
                head_sha=candidates.head_sha,
                author_reply=None,
            )
        )
    return VerifiedRound(candidates=candidates, verdicts=tuple(accepted))


def parse_verifier_output(
    payload: Mapping[str, Any],
    candidates: RoundCandidates,
    *,
    verifier_model: str,
    author_replies: Sequence[AuthorReply] = (),
    consumed_reply_keys: Collection[str] = (),
    consumed_comment_ids: Collection[str] = (),
    bound_reply_targets: Mapping[str, str] | Collection[tuple[str, str]] = (),
) -> VerifiedRound:
    """解析核实者裁决并强制绑定 round_number、head_sha、审查面板与候选集（fail-closed）。"""
    if not isinstance(candidates, RoundCandidates):
        raise ConvergenceError("candidates 必须是经面板强校验的 RoundCandidates")
    panel = candidates.panel
    if not panel.require_verifier:
        raise ConvergenceError("panel.require_verifier=False 必须走 accept_quick_pass_findings，禁止调用 parse_verifier_output")
    model = _require_non_empty_str(verifier_model, "verifier_model")
    expected_verifier = _require_non_empty_str(panel.verifier_model, "panel.verifier_model")
    if model != expected_verifier:
        raise ConvergenceError(f"verifier_model={model!r} 与 panel.verifier_model={expected_verifier!r} 不一致")
    verifier_family = infer_model_family(model)

    if not isinstance(payload, Mapping):
        raise ConvergenceError("verifier 输出必须是对象")
    raw_round = payload.get("round_number")
    if type(raw_round) is not int or raw_round != candidates.round_number:
        raise ConvergenceError(
            f"verifier 输出 round_number={raw_round!r} 缺失或与 candidates.round_number={candidates.round_number} 不匹配"
        )
    raw_head = payload.get("head_sha")
    payload_head = _normalize_commit_sha(raw_head, "verifier.head_sha")
    if payload_head != candidates.head_sha:
        raise ConvergenceError(
            f"verifier 输出 head_sha={payload_head!r} 与 candidates.head_sha={candidates.head_sha!r} 不匹配"
        )
    raw_verdicts = payload.get("verdicts")
    if not isinstance(raw_verdicts, list):
        raise ConvergenceError("verifier 输出缺少 verdicts 列表")

    candidates_by_id: dict[str, Finding] = {}
    ordered_ids: list[str] = []
    candidate_list: list[Finding] = []
    for candidate in candidates.findings:
        cid = candidate.finding_id
        if cid in candidates_by_id:
            raise ConvergenceError(f"candidates.findings 含重复指纹 {cid}")
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

    history_consumed: frozenset[str] = frozenset().union(*(entry.consumed_reply_keys for entry in candidates.history))
    extra_consumed = _validate_consumed_reply_keys(consumed_reply_keys, "consumed_reply_keys")
    effective_consumed = history_consumed | extra_consumed
    history_bound_targets = _collect_history_bound_targets(candidates.history)
    extra_bound_targets = _normalize_bound_reply_targets(bound_reply_targets, "bound_reply_targets")
    effective_bound_targets = dict(history_bound_targets)
    _merge_bound_reply_targets(effective_bound_targets, extra_bound_targets, "bound_reply_targets")

    bound_replies, matched_keys_by_id = _analyze_author_replies(
        candidate_list,
        author_replies,
        consumed_reply_keys=effective_consumed,
        consumed_comment_ids=consumed_comment_ids,
        stale_location_fingerprints=candidates.stale_location_fingerprints,
        bound_reply_targets=effective_bound_targets,
    )

    prior_important_ids = frozenset(f.finding_id for f in candidates.prior_important)
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
        verifier_evidence = _require_visible_markdown_text(raw_evidence, f"verdicts[{idx}].verifier_evidence")
        if verdict == VerificationVerdict.RESOLVED_BY_FIX:
            if fid not in prior_important_ids:
                raise ConvergenceError(
                    f"发现 {fid} 不在本轮 prior_important 中，禁止标记为 resolved_by_fix（若属误报请标为 false_positive/rejected）"
                )
            if not candidates.history or candidates.head_sha == candidates.history[-1].head_sha:
                raise ConvergenceError(
                    f"发现 {fid} 所在轮次 head_sha={candidates.head_sha!r} 与上一轮相同（无新提交），"
                    "禁止标记为 resolved_by_fix"
                )
        finding = candidates_by_id[fid]
        matched_reply: AuthorReply | None = None
        if verdict == VerificationVerdict.RESOLVED_BY_WONTFIX:
            matched_reply = bound_replies.get(fid)
            if matched_reply is None:
                raise ConvergenceError(
                    f"发现 {fid} 裁决为 resolved_by_wontfix，但缺少唯一匹配且未消费的作者不修回复"
                )
            _require_non_empty_str(matched_reply.author, "author_reply.author")
        verdicts_by_id[fid] = VerifiedFinding(
            finding=finding,
            verdict=verdict,
            verifier_model=model,
            verifier_evidence=verifier_evidence,
            round_number=candidates.round_number,
            head_sha=candidates.head_sha,
            author_reply=matched_reply,
            related_reply_keys=tuple(sorted(matched_keys_by_id.get(fid, ()))),
        )

    missing = [cid for cid in ordered_ids if cid not in verdicts_by_id]
    if missing:
        raise ConvergenceError(f"核实者遗漏候选发现：{', '.join(missing)}")

    return VerifiedRound(
        candidates=candidates,
        verdicts=tuple(verdicts_by_id[cid] for cid in ordered_ids),
        bound_reply_targets=frozenset(extra_bound_targets.items()),
    )


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
    pending_non_blocking: tuple[VerifiedFinding, ...] = ()
    history: tuple[RoundHistoryEntry, ...] = ()
    bound_reply_targets: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diff_base_sha", _normalize_commit_sha(self.diff_base_sha, "RoundPlan.diff_base_sha"))
        object.__setattr__(self, "diff_head_sha", _normalize_commit_sha(self.diff_head_sha, "RoundPlan.diff_head_sha"))
        if not isinstance(self.consumed_reply_keys, frozenset):
            raise ConvergenceError("RoundPlan.consumed_reply_keys 必须是 frozenset[str]")
        for rk in self.consumed_reply_keys:
            _validate_consumed_reply_key(rk, "RoundPlan.consumed_reply_keys[]")
        _validate_bound_reply_targets_frozenset(self.bound_reply_targets, "RoundPlan.bound_reply_targets")

    @property
    def prior_important_ids(self) -> frozenset[str]:
        return frozenset(f.finding_id for f in self.unresolved_prior_important)

    @property
    def prior_important_sources(self) -> Mapping[str, frozenset[str]]:
        mapping: dict[str, frozenset[str]] = {}
        for item in self.unresolved_prior_important:
            fid = item.finding_id
            real = frozenset(_real_source_models(item.source_models))
            if fid in mapping:
                mapping[fid] = mapping[fid] | real
            else:
                mapping[fid] = real
        return MappingProxyType(mapping)


def _active_posted_fingerprints(history: Sequence[RoundHistoryEntry]) -> frozenset[str]:
    """回放历史轮次中仍处于活跃态的已贴指纹；已解除或被核实驳回的发现会移出，允许重新确认后完整贴出。"""
    active: set[str] = set()
    prev_unresolved: set[str] = set()
    for entry in history:
        current_unresolved = {f.finding_id for f in entry.unresolved_important}
        cleared_in_round = (
            (prev_unresolved - current_unresolved)
            | set(entry.resolved_fingerprints)
            | set(entry.rejected_fingerprints)
        )
        active.difference_update(cleared_in_round)
        active.update(entry.posted_fingerprints)
        prev_unresolved = current_unresolved
    return frozenset(active)


def _is_reply_obviously_consumed(reply: AuthorReply, consumed_reply_keys: frozenset[str]) -> bool:
    if reply.reply_key in consumed_reply_keys:
        return True
    if reply.finding_id is not None and len(reply.finding_id.strip()) == 16:
        if _resolved_reply_key(reply.comment_id, reply.finding_id) in consumed_reply_keys:
            return True
    return False


def plan_next_round(
    base_sha: str,
    head_sha: str,
    history: Sequence[RoundHistoryEntry],
    author_replies: Sequence[AuthorReply] = (),
) -> RoundPlan:
    base = _normalize_commit_sha(base_sha, "base_sha")
    head = _normalize_commit_sha(head_sha, "head_sha")
    for reply in author_replies:
        if not isinstance(reply, AuthorReply):
            raise ConvergenceError(f"author_replies 元素必须是 AuthorReply：{reply!r}")
    history_tuple = tuple(history)
    _, _, history_bound_targets = _validate_history_chain(history_tuple)

    if not history_tuple:
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
            pending_non_blocking=(),
            history=(),
            bound_reply_targets=frozenset(),
        )

    prev = history_tuple[-1]
    round_number = prev.round_number + 1
    already_posted = _active_posted_fingerprints(history_tuple)
    consumed_reply_keys: frozenset[str] = frozenset().union(*(entry.consumed_reply_keys for entry in history_tuple))
    active_replies = tuple(
        reply for reply in author_replies if not _is_reply_obviously_consumed(reply, consumed_reply_keys)
    )
    pending_non_blocking = tuple(
        vf for vf in prev.pending_non_blocking if vf.finding.finding_id not in already_posted
    )
    unresolved_prior = () if prev.outcome == RoundOutcome.PASS else prev.unresolved_important
    return RoundPlan(
        round_number=round_number,
        review_scope="incremental_diff",
        diff_base_sha=prev.head_sha,
        diff_head_sha=head,
        unresolved_prior_important=unresolved_prior,
        author_replies=active_replies,
        already_posted_fingerprints=already_posted,
        consumed_reply_keys=consumed_reply_keys,
        exceeds_auto_rounds=round_number > MAX_AUTO_ROUNDS,
        pending_non_blocking=pending_non_blocking,
        history=history_tuple,
        bound_reply_targets=frozenset(history_bound_targets.items()),
    )


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
    head_sha: str
    panel: ReviewPanel
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
    unresolved_important: tuple[Finding, ...]
    retained_posted_fingerprints: frozenset[str] = frozenset()
    resolved_fingerprints: frozenset[str] = frozenset()
    rejected_fingerprints: frozenset[str] = frozenset()
    consumed_reply_keys: frozenset[str] = frozenset()
    finder_session_ids: frozenset[str] = frozenset()
    stale_location_fingerprints: frozenset[str] = frozenset()
    relocated_fingerprints: frozenset[str] = frozenset()
    bound_reply_targets: frozenset[tuple[str, str]] = frozenset()

    def __post_init__(self) -> None:
        norm_head = _normalize_commit_sha(self.head_sha, "RoundDecision.head_sha")
        object.__setattr__(self, "head_sha", norm_head)
        if not isinstance(self.consumed_reply_keys, frozenset):
            raise ConvergenceError("RoundDecision.consumed_reply_keys 必须是 frozenset[str]")
        for rk in self.consumed_reply_keys:
            _validate_consumed_reply_key(rk, "RoundDecision.consumed_reply_keys[]")
        if not isinstance(self.stale_location_fingerprints, frozenset):
            raise ConvergenceError("RoundDecision.stale_location_fingerprints 必须是 frozenset[str]")
        norm_stale = frozenset(
            _require_non_empty_str(fp, "stale_location_fingerprints[]").lower()
            for fp in self.stale_location_fingerprints
        )
        object.__setattr__(self, "stale_location_fingerprints", norm_stale)
        if not isinstance(self.relocated_fingerprints, frozenset):
            raise ConvergenceError("RoundDecision.relocated_fingerprints 必须是 frozenset[str]")
        norm_relocated = frozenset(
            _require_non_empty_str(fp, "relocated_fingerprints[]").lower()
            for fp in self.relocated_fingerprints
        )
        object.__setattr__(self, "relocated_fingerprints", norm_relocated)
        _validate_bound_reply_targets_frozenset(self.bound_reply_targets, "RoundDecision.bound_reply_targets")

    @property
    def cleared_fingerprints(self) -> frozenset[str]:
        return self.resolved_fingerprints | self.rejected_fingerprints

    def to_history_entry(
        self,
        head_sha: str | None = None,
        *,
        rendered: RenderedComment,
    ) -> RoundHistoryEntry:
        """基于实际渲染结果生成轮次历史，作为已贴指纹、面板、HEAD 与待补发非阻断项的唯一权威更新入口。"""
        if not isinstance(rendered, RenderedComment):
            raise ConvergenceError("rendered 必须是 RenderedComment")
        if head_sha is not None:
            norm_sha = _normalize_commit_sha(head_sha, "head_sha")
            if norm_sha != self.head_sha:
                raise ConvergenceError(f"head_sha={norm_sha!r} 与 RoundDecision.head_sha={self.head_sha!r} 不一致")
        if rendered.round_number != self.round_number or rendered.head_sha != self.head_sha:
            raise ConvergenceError(
                f"rendered 绑定坐标 (round={rendered.round_number}, head={rendered.head_sha!r}) "
                f"与 RoundDecision (round={self.round_number}, head={self.head_sha!r}) 不匹配"
            )
        if not rendered.posted_fingerprints.isdisjoint(rendered.deferred_fingerprints):
            raise ConvergenceError("rendered.posted_fingerprints 与 rendered.deferred_fingerprints 不得重叠")
        omitted_ids = frozenset(vf.finding.finding_id for vf in rendered.omitted_non_blocking)
        if omitted_ids != rendered.omitted_non_blocking_fingerprints or omitted_ids != rendered.deferred_fingerprints:
            raise ConvergenceError("rendered.omitted_non_blocking 与 deferred_fingerprints 不一致")
        blocking_ids = frozenset(vf.finding.finding_id for vf in self.blocking_findings)
        expected_non_blocking = (
            frozenset(vf.finding.finding_id for vf in self.non_blocking_findings) - self.retained_posted_fingerprints
        )
        valid_active_ids = blocking_ids | frozenset(vf.finding.finding_id for vf in self.non_blocking_findings)
        if not (rendered.posted_fingerprints <= valid_active_ids):
            raise ConvergenceError("rendered.posted_fingerprints 包含非本轮活跃发现指纹")
        if not (blocking_ids <= rendered.posted_fingerprints):
            raise ConvergenceError("rendered.posted_fingerprints 遗漏了本轮阻断发现指纹")
        if not (omitted_ids <= valid_active_ids):
            raise ConvergenceError("rendered.omitted_non_blocking 包含非本轮活跃发现指纹")
        if rendered.posted_fingerprints & omitted_ids:
            raise ConvergenceError("同一发现不得同时出现在 posted_fingerprints 与 omitted_non_blocking 中")
        if rendered.posted_fingerprints & self.cleared_fingerprints:
            raise ConvergenceError("rendered.posted_fingerprints 不得包含本轮已解除或已驳回的发现指纹")
        if omitted_ids & (self.retained_posted_fingerprints | self.cleared_fingerprints):
            raise ConvergenceError("rendered.omitted_non_blocking 不得包含已贴出或已解除/驳回的发现指纹")
        self_nb_by_fp = {vf.finding.finding_id: vf for vf in self.non_blocking_findings}
        for vf in rendered.omitted_non_blocking:
            fid = vf.finding.finding_id
            expected_vf = self_nb_by_fp.get(fid)
            if expected_vf is None or vf != expected_vf:
                raise ConvergenceError(
                    f"rendered.omitted_non_blocking 中的发现 {fid} 与当前 RoundDecision 的非阻断核实记录不一致"
                )
        posted_non_blocking = rendered.posted_fingerprints - blocking_ids
        if (posted_non_blocking | rendered.deferred_fingerprints) != expected_non_blocking:
            raise ConvergenceError(
                "rendered 未守恒覆盖本轮全部应发/待补发非阻断发现："
                f"期望 {sorted(expected_non_blocking)!r}，"
                f"实际 {sorted(posted_non_blocking | rendered.deferred_fingerprints)!r}"
            )
        return RoundHistoryEntry(
            round_number=self.round_number,
            head_sha=self.head_sha,
            posted_fingerprints=self.retained_posted_fingerprints | rendered.posted_fingerprints,
            unresolved_important=self.unresolved_important,
            panel=self.panel,
            resolved_fingerprints=self.resolved_fingerprints,
            rejected_fingerprints=self.rejected_fingerprints,
            consumed_reply_keys=self.consumed_reply_keys,
            pending_non_blocking=tuple(
                self_nb_by_fp[vf.finding.finding_id] for vf in rendered.omitted_non_blocking
            ),
            finder_session_ids=self.finder_session_ids,
            outcome=self.outcome,
            relocated_fingerprints=self.relocated_fingerprints
            & frozenset(f.finding_id for f in self.unresolved_important),
            bound_reply_targets=self.bound_reply_targets,
        )


def evaluate_round(
    verified: VerifiedRound,
    *,
    author_replies: Sequence[AuthorReply] = (),
    max_auto_rounds: int = MAX_AUTO_ROUNDS,
) -> RoundDecision:
    """基于经强校验绑定的 VerifiedRound 计算单轮收敛裁决（不再接受松散 round_number 与裸 verdicts）。"""
    if not isinstance(verified, VerifiedRound):
        raise ConvergenceError("verified 必须是 VerifiedRound")
    if type(max_auto_rounds) is not int or max_auto_rounds <= 0:
        raise ConvergenceError(f"max_auto_rounds 必须是正整数：{max_auto_rounds!r}")

    round_number = verified.round_number
    head_sha = verified.head_sha
    panel = verified.panel
    history = verified.history
    already_posted = _active_posted_fingerprints(history)
    pending_non_blocking = history[-1].pending_non_blocking if history else ()

    seen: set[str] = set()
    ordered: list[VerifiedFinding] = []
    for vf in verified.verdicts:
        fid = vf.finding.finding_id
        if fid in seen:
            raise ConvergenceError(f"verified 含重复指纹：{fid}")
        seen.add(fid)
        ordered.append(vf)

    pending_seen: set[str] = set()
    carried_non_blocking: list[VerifiedFinding] = []
    for vf in pending_non_blocking:
        fid = vf.finding.finding_id
        if fid in pending_seen:
            raise ConvergenceError(f"pending_non_blocking 含重复指纹：{fid}")
        pending_seen.add(fid)
        if fid in seen or fid in already_posted:
            continue
        carried_non_blocking.append(vf)

    effective_verified = tuple(ordered) + tuple(carried_non_blocking)
    blocking = tuple(vf for vf in effective_verified if vf.is_blocking)
    non_blocking = tuple(
        vf for vf in effective_verified if vf.verdict == VerificationVerdict.CONFIRMED and not vf.is_blocking
    )
    resolved = tuple(
        vf
        for vf in effective_verified
        if vf.verdict in (VerificationVerdict.RESOLVED_BY_FIX, VerificationVerdict.RESOLVED_BY_WONTFIX)
    )
    rejected = tuple(vf for vf in effective_verified if vf.verdict == VerificationVerdict.REJECTED)

    resolved_ids = frozenset(vf.finding.finding_id for vf in resolved)
    rejected_ids = frozenset(vf.finding.finding_id for vf in rejected)
    cleared_ids = resolved_ids | rejected_ids
    retained_posted = already_posted - cleared_ids
    postable = select_postable_findings(effective_verified, already_posted, resolved_fingerprints=cleared_ids)
    unresolved_important = tuple(vf.finding for vf in blocking)

    history_consumed: frozenset[str] = frozenset().union(*(entry.consumed_reply_keys for entry in history))
    history_bound_targets = _collect_history_bound_targets(history)
    verified_bound_targets = _validate_bound_reply_targets_frozenset(
        verified.bound_reply_targets,
        "verified.bound_reply_targets",
    )
    effective_bound_targets = dict(history_bound_targets)
    _merge_bound_reply_targets(
        effective_bound_targets,
        verified_bound_targets,
        "verified.bound_reply_targets",
    )

    consumed_keys: set[str] = set()
    for vf in (*resolved, *rejected):
        fid = vf.finding.finding_id
        if vf.author_reply is not None:
            consumed_keys.add(vf.author_reply.reply_key)
            consumed_keys.add(_resolved_reply_key(vf.author_reply.comment_id, fid))
        consumed_keys.update(vf.related_reply_keys)
    for rk, pinned_fid in effective_bound_targets.items():
        if pinned_fid in cleared_ids:
            consumed_keys.add(rk)
    matched_keys_by_id: dict[str, frozenset[str]] = {}
    if author_replies:
        _, matched_keys_by_id = _analyze_author_replies(
            [vf.finding for vf in effective_verified],
            author_replies,
            consumed_reply_keys=history_consumed,
            stale_location_fingerprints=verified.candidates.stale_location_fingerprints,
            bound_reply_targets=effective_bound_targets,
        )
        for fid in cleared_ids:
            consumed_keys.update(matched_keys_by_id.get(fid, ()))

    bound_targets: dict[str, str] = dict(effective_bound_targets)
    stale_fps = verified.candidates.stale_location_fingerprints
    round_loc_inline_targets: dict[str, set[str]] = {}
    for vf in effective_verified:
        fid = vf.finding.finding_id
        candidate_rks: set[str] = set(vf.related_reply_keys)
        if vf.author_reply is not None:
            candidate_rks.add(vf.author_reply.reply_key)
        if matched_keys_by_id:
            candidate_rks.update(matched_keys_by_id.get(fid, ()))
        for rk in candidate_rks:
            _, kind, _ = _parse_consumed_reply_key(rk, "related_reply_keys[]")
            if kind in ("loc", "inline"):
                round_loc_inline_targets.setdefault(rk, set()).add(fid)
    for rk, target_fids in round_loc_inline_targets.items():
        if rk in bound_targets:
            pinned = bound_targets[rk]
            if any(fid != pinned for fid in target_fids):
                raise ConvergenceError(
                    f"回复键 {rk!r} 已锁定到发现 {pinned!r}，不得改绑到 {sorted(target_fids)!r}"
                )
        elif len(target_fids) == 1:
            only_fid = next(iter(target_fids))
            if only_fid not in stale_fps:
                bound_targets[rk] = only_fid
            else:
                # 跨 HEAD 坐标/行内回复仅命中未在前轮锁定的过期发现，立即消费以防后续轮次过期发现移位后复活误绑新发现
                consumed_keys.add(rk)
        else:
            # 同一 loc/inline 回复在本轮同时命中多个发现属歧义回复，标记为已消费以防后续轮次改绑新发现
            consumed_keys.add(rk)

    consumed_reply_keys = frozenset(consumed_keys)
    bound_reply_targets = frozenset(bound_targets.items())
    unresolved_ids = frozenset(f.finding_id for f in unresolved_important)
    stale_unresolved = verified.candidates.stale_location_fingerprints & unresolved_ids
    relocated_unresolved = (
        frozenset(f.finding_id for f in verified.candidates.current_round_findings) & unresolved_ids
    )

    if not blocking:
        n_nit = sum(1 for vf in non_blocking if vf.finding.severity == Severity.NIT)
        n_pre = sum(1 for vf in non_blocking if vf.finding.severity == Severity.PRE_EXISTING)
        outcome: RoundOutcome = RoundOutcome.PASS
        github_state: GitHubStatusState = "success"
        stop_auto_rereview = False
        description = f"审查通过：0 项 Important，{n_nit} 项 Nit，{n_pre} 项 Pre-existing"
    elif round_number > max_auto_rounds:
        outcome = RoundOutcome.NON_CONVERGENT
        github_state = "failure"
        stop_auto_rereview = True
        description = (
            NON_CONVERGENT_DESCRIPTION
            if max_auto_rounds == MAX_AUTO_ROUNDS
            else f"已 {max_auto_rounds} 轮未收敛，请重新考虑方案"
        )
    else:
        outcome = RoundOutcome.BLOCKED
        github_state = "failure"
        stop_auto_rereview = False
        description = f"发现 {len(blocking)} 项未解除的 Important 问题（第 {round_number}/{max_auto_rounds} 轮）"

    return RoundDecision(
        round_number=round_number,
        head_sha=head_sha,
        panel=panel,
        outcome=outcome,
        github_state=github_state,
        description=description,
        stop_auto_rereview=stop_auto_rereview,
        verified_findings=effective_verified,
        blocking_findings=blocking,
        non_blocking_findings=non_blocking,
        resolved_findings=resolved,
        rejected_findings=rejected,
        postable_findings=postable,
        unresolved_important=unresolved_important,
        retained_posted_fingerprints=retained_posted,
        resolved_fingerprints=resolved_ids,
        rejected_fingerprints=rejected_ids,
        consumed_reply_keys=consumed_reply_keys,
        finder_session_ids=frozenset(b.session_id for b in verified.candidates.finder_batches),
        stale_location_fingerprints=stale_unresolved,
        relocated_fingerprints=relocated_unresolved,
        bound_reply_targets=bound_reply_targets,
    )


@dataclass(frozen=True)
class RenderedComment:
    round_number: int
    head_sha: str
    body: str
    posted_fingerprints: frozenset[str]
    deferred_fingerprints: frozenset[str]
    omitted_non_blocking_fingerprints: frozenset[str]
    truncated: bool
    omitted_non_blocking: tuple[VerifiedFinding, ...] = ()

    def __post_init__(self) -> None:
        if type(self.round_number) is not int or self.round_number < 1:
            raise ConvergenceError(f"RenderedComment.round_number 必须是 >= 1 的整数：{self.round_number!r}")
        norm_head = _normalize_commit_sha(self.head_sha, "RenderedComment.head_sha")
        object.__setattr__(self, "head_sha", norm_head)
        if not isinstance(self.body, str):
            raise ConvergenceError("RenderedComment.body 必须是字符串")
        if not isinstance(self.posted_fingerprints, frozenset):
            raise ConvergenceError("RenderedComment.posted_fingerprints 必须是 frozenset[str]")
        for fp in self.posted_fingerprints:
            _require_non_empty_str(fp, "posted_fingerprints[]")
        if not isinstance(self.deferred_fingerprints, frozenset):
            raise ConvergenceError("RenderedComment.deferred_fingerprints 必须是 frozenset[str]")
        for fp in self.deferred_fingerprints:
            _require_non_empty_str(fp, "deferred_fingerprints[]")
        if not isinstance(self.omitted_non_blocking_fingerprints, frozenset):
            raise ConvergenceError("RenderedComment.omitted_non_blocking_fingerprints 必须是 frozenset[str]")
        if type(self.truncated) is not bool:
            raise ConvergenceError("RenderedComment.truncated 必须是 bool")
        if not self.posted_fingerprints.isdisjoint(self.deferred_fingerprints):
            raise ConvergenceError("RenderedComment.posted_fingerprints 与 deferred_fingerprints 不得重叠")
        if not isinstance(self.omitted_non_blocking, tuple):
            raise ConvergenceError("omitted_non_blocking 必须是 VerifiedFinding 元组")
        omitted_ids: set[str] = set()
        for vf in self.omitted_non_blocking:
            if not isinstance(vf, VerifiedFinding):
                raise ConvergenceError("omitted_non_blocking 元素必须是 VerifiedFinding")
            if vf.verdict != VerificationVerdict.CONFIRMED or vf.is_blocking:
                raise ConvergenceError("omitted_non_blocking 仅允许核实成立的非阻断发现")
            fid = vf.finding.finding_id
            if fid in omitted_ids:
                raise ConvergenceError(f"omitted_non_blocking 含重复指纹：{fid}")
            omitted_ids.add(fid)
        if omitted_ids != self.omitted_non_blocking_fingerprints or omitted_ids != self.deferred_fingerprints:
            raise ConvergenceError("omitted_non_blocking、omitted_non_blocking_fingerprints 与 deferred_fingerprints 不一致")


def parse_comment_marker(body: str) -> tuple[int, int, str] | None:
    lines = _split_commonmark_lines(body) if body else []
    if not lines:
        return None
    first_line = lines[0]
    leading_spaces = 0
    while leading_spaces < len(first_line) and first_line[leading_spaces] == " ":
        leading_spaces += 1
    if leading_spaces >= 4 or (leading_spaces < len(first_line) and first_line[leading_spaces] == "\t"):
        return None
    candidate = first_line[leading_spaces:].rstrip(" \t")
    match = _COMMENT_MARKER_RE.match(candidate)
    if not match:
        return None
    return int(match.group("pr")), int(match.group("round")), _normalize_commit_sha(match.group("head"), "head")


def _format_location(finding: Finding) -> str:
    norm_file = _normalize_file(finding.file)
    return f"{norm_file}:{finding.line}" if finding.line is not None else norm_file


def _format_code_location(finding: Finding) -> str:
    return _wrap_markdown_code_span(_format_location(finding))


def _wrap_markdown_code_span(text: str) -> str:
    """按 CommonMark §6.1 用最短安全反引号序列将单行字面文本包裹为行内代码。"""
    single = re.sub(r"[\r\n]+", " ", text)
    max_run = max((len(m.group(0)) for m in re.finditer(r"`+", single)), default=0)
    fence = "`" * (max_run + 1)
    if (
        single.startswith("`")
        or single.endswith("`")
        or (single.startswith(" ") and single.endswith(" ") and bool(single.strip(" ")))
    ):
        return f"{fence} {single} {fence}"
    return f"{fence}{single}{fence}"


def _has_unclosed_inline_html_opener(text: str) -> bool:
    """检查行内非代码片段是否遗留未闭合的 HTML 注释/处理指令/声明/CDATA 或未闭合开标签起点。"""
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
            i += 2
            continue
        if ch == "`":
            tick_end, found_end = _find_code_span_end(text, i)
            i = found_end if found_end != -1 else tick_end
            continue
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
            if auto_m is not None:
                i = auto_m.end()
                continue
            html_m = _INLINE_RAW_HTML_RE.match(text, i)
            if html_m is not None:
                i = html_m.end()
                continue
            if (
                text.startswith("<!--", i)
                or text.startswith("<?", i)
                or text.startswith("<![CDATA[", i)
                or (i + 2 < n and text[i + 1] == "!" and text[i + 2].isalpha())
            ):
                return True
            open_head_m = _HTML_OPEN_TAG_HEAD_RE.match(text, i)
            if open_head_m is not None:
                probe_state = _HtmlSuppressState(
                    in_open_tag=True,
                    pending_open_tag_name=open_head_m.group(1).lower(),
                    suppressed_tags=frozenset(),
                )
                _advance_in_open_tag(text, open_head_m.end(), probe_state)
                if probe_state.in_open_tag:
                    return True
        i += 1
    return False


def _has_visible_inline_gfm_text(single_line: str) -> tuple[bool, bool]:
    """判定单行文本作为行内内容渲染时：(是否含可见基字符, 扫描结束后是否泄漏未闭合 HTML 抑制态)。"""
    state = _HtmlSuppressState(suppressed_tags=_SILENT_INLINE_HTML_TAGS)
    visible = False
    for line_tokens in _scan_inline_dual(single_line, frozenset(), state):
        display_text = "".join(d_part for _, d_part in line_tokens)
        if _clean_display_reason(display_text):
            visible = True
    return visible, _is_html_suppressed(state) or _has_unclosed_inline_html_opener(single_line)


def _leaves_html_suppressed(text: str) -> bool:
    """按完整块+行内双流管线判定 Markdown 片段渲染结束后是否遗留未闭合 HTML 抑制态。"""
    doc_blocks, frozen_labels = _parse_commonmark_blocks(text, include_all_visible_blocks=True)
    state = _HtmlSuppressState(suppressed_tags=_SILENT_INLINE_HTML_TAGS)
    for block_kind, block_text in doc_blocks:
        if block_kind == "html":
            _update_html_suppress_state(block_text, state)
            continue
        if block_kind == "code":
            continue
        if block_kind == "table_cell":
            if not _is_html_suppressed(state):
                _scan_inline_dual(block_text, frozen_labels, state)
                if _has_unclosed_inline_html_opener(block_text):
                    return True
            continue
        _scan_inline_dual(block_text, frozen_labels, state)
        if not _is_html_suppressed(state) and _has_unclosed_inline_html_opener(block_text):
            return True
    return _is_html_suppressed(state)


def _inline_contains_raw_html(text: str) -> bool:
    """按 CommonMark §6 跳过反斜杠转义、闭合行内代码跨度与合法自动链接后，检测是否含任意原始 HTML 起始结构。"""
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in _ASCII_PUNCTUATION:
            i += 2
            continue
        if ch == "`":
            tick_end, found_end = _find_code_span_end(text, i)
            i = found_end if found_end != -1 else tick_end
            continue
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(text, i) or _AUTOLINK_EMAIL_RE.match(text, i)
            if auto_m is not None:
                i = auto_m.end()
                continue
            if _RAW_HTML_START_RE.match(text, i) is not None:
                return True
        i += 1
    return False


def _contains_raw_html_outside_code(text: str) -> bool:
    """检测 Markdown 文本在代码块与行内代码跨度之外是否含任何块级或行内原始 HTML。"""
    doc_blocks, _ = _parse_commonmark_blocks(text, include_all_visible_blocks=True)
    for block_kind, block_text in doc_blocks:
        if block_kind == "html":
            return True
        if block_kind == "code":
            continue
        if _inline_contains_raw_html(block_text):
            return True
    return False


def _escape_unmatched_backticks(seg: str) -> str:
    """扫描单行普通片段，跳过已闭合 CommonMark §6.1 代码段、反斜杠转义与自动链接，将所有未配对裸反引号转义为 \\`。"""
    if "`" not in seg:
        return seg
    out: list[str] = []
    n = len(seg)
    i = 0
    while i < n:
        ch = seg[i]
        if ch == "\\" and i + 1 < n and seg[i + 1] in _ASCII_PUNCTUATION:
            out.append(seg[i : i + 2])
            i += 2
            continue
        if ch == "`":
            tick_end, found_end = _find_code_span_end(seg, i)
            if found_end != -1:
                out.append(seg[i:found_end])
                i = found_end
            else:
                out.append(r"\`" * (tick_end - i))
                i = tick_end
            continue
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(seg, i) or _AUTOLINK_EMAIL_RE.match(seg, i)
            if auto_m is not None:
                out.append(auto_m.group(0))
                i = auto_m.end()
                continue
            html_m = _INLINE_RAW_HTML_RE.match(seg, i)
            if html_m is not None:
                out.append(html_m.group(0))
                i = html_m.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _format_nested_fenced_code(text: str, *, content_indent: str) -> str:
    """用足够长的反引号围栏将文本原样包裹为嵌套围栏代码块，彻底隔离未闭合 HTML/注释。"""
    max_run = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, max_run + 1)
    body_lines = [
        f"{content_indent}{line}" if line else ""
        for line in _split_commonmark_lines(text)
    ]
    return "\n".join([f"{content_indent}{fence}", *body_lines, f"{content_indent}{fence}"])


def _indent_markdown_line(line: str, content_indent: str) -> str:
    """为嵌套列表块内容加缩进；当 content_indent 非 4 列对齐时先按 CommonMark §2.2 展开首 4 列内前导 Tab。"""
    if not line:
        return ""
    if len(content_indent) % 4 != 0:
        col = 0
        idx = 0
        expanded: list[str] = []
        has_tab = False
        while idx < len(line) and col < 4 and line[idx] in (" ", "\t"):
            if line[idx] == " ":
                expanded.append(" ")
                col += 1
            else:
                has_tab = True
                step = 4 - (col % 4)
                expanded.append(" " * step)
                col += step
            idx += 1
        if has_tab:
            line = "".join(expanded) + line[idx:]
    return f"{content_indent}{line}"


def _format_bullet_markdown_field(
    label: str,
    text: str,
    *,
    bullet_prefix: str = "  - ",
    content_indent: str = "    ",
) -> str:
    """将 Markdown 字段渲染到子列表项，保全缩进代码块与块级结构、隔离代码外原始 HTML 与未闭合抑制态并保持单行普通文本原样。"""
    if _leaves_html_suppressed(text) or _contains_raw_html_outside_code(text):
        return f"{bullet_prefix}{label}\n\n{_format_nested_fenced_code(text, content_indent=content_indent)}"

    if "\n" not in text and "\r" not in text:
        cursor = _LineCursor(text)
        indent = cursor.indent_ahead()
        if indent < 4:
            cursor.advance_cols(indent)
            rest = cursor.rest_text()
            is_block_start = (
                rest.startswith(">")
                or _ATX_HEADING_BODY_RE.match(rest) is not None
                or _FENCE_OPEN_BACKTICK_BODY_RE.match(rest) is not None
                or _FENCE_OPEN_TILDE_BODY_RE.match(rest) is not None
                or _match_html_block_start(rest, allow_type7=True) is not None
                or _THEMATIC_BREAK_BODY_RE.match(rest) is not None
                or _LIST_ITEM_MARKER_BODY_RE.match(rest) is not None
            )
            if not is_block_start:
                visible, suppressed = _has_visible_inline_gfm_text(text)
                if visible and not suppressed:
                    return f"{bullet_prefix}{label}{text}"

    indented_lines = [
        _indent_markdown_line(line, content_indent)
        for line in _split_commonmark_lines(text)
    ]
    return f"{bullet_prefix}{label}\n\n" + "\n".join(indented_lines)


def _format_inline_markdown_field(text: str, *, collapse_whitespace: bool = False) -> str:
    """将 Markdown 字段安全格式化为单行行内文本，防止缩进代码或块级文本在单行位置丧失可见性，并隔离代码外原始 HTML 与未配对反引号。"""
    doc_blocks, _ = _parse_commonmark_blocks(text, include_all_visible_blocks=True)
    has_code_block = any(kind == "code" for kind, _ in doc_blocks)
    if not has_code_block and "\n" not in text and "\r" not in text:
        candidate = _single_line(text) if collapse_whitespace else text
        visible, suppressed = _has_visible_inline_gfm_text(candidate)
        if visible and not suppressed and not _contains_raw_html_outside_code(candidate):
            return _escape_unmatched_backticks(candidate)
        return _wrap_markdown_code_span(_single_line(text) if collapse_whitespace else text.strip())

    if has_code_block or len(doc_blocks) > 1:
        parts: list[str] = []
        for kind, block_text in doc_blocks:
            if kind == "html":
                html_literal = re.sub(r"[\r\n]+", " ", block_text).strip()
                if html_literal:
                    parts.append(_wrap_markdown_code_span(html_literal))
                continue
            if kind == "code":
                code_literal = re.sub(r"[\r\n]+", " ", block_text.strip("\r\n"))
                if _clean_display_reason(code_literal):
                    parts.append(_wrap_markdown_code_span(code_literal))
                continue
            seg = _single_line(block_text)
            if not seg:
                continue
            seg_visible, seg_suppressed = _has_visible_inline_gfm_text(seg)
            if seg_visible and not seg_suppressed and not _contains_raw_html_outside_code(seg):
                parts.append(_escape_unmatched_backticks(seg))
            elif seg_visible or seg_suppressed or _contains_raw_html_outside_code(seg):
                parts.append(_wrap_markdown_code_span(seg))
        if parts:
            joined = " ".join(parts)
            joined_visible, joined_suppressed = _has_visible_inline_gfm_text(joined)
            if joined_visible and not joined_suppressed and not _contains_raw_html_outside_code(joined):
                return joined

    single = _single_line(text)
    visible, suppressed = _has_visible_inline_gfm_text(single)
    if visible and not suppressed and not _contains_raw_html_outside_code(single):
        return _escape_unmatched_backticks(single)
    return _wrap_markdown_code_span(single)


def _tokenize_inline_clip_segments(
    formatted: str,
) -> list[tuple[Literal["text", "code", "html"], str]]:
    """按 CommonMark §6 从左到右将单行格式化文本切分为普通文本、闭合行内代码与原子行内 HTML/自动链接片段。"""
    segments: list[tuple[Literal["text", "code", "html"], str]] = []
    text_buf: list[str] = []
    n = len(formatted)
    i = 0

    def flush_text() -> None:
        if text_buf:
            segments.append(("text", "".join(text_buf)))
            text_buf.clear()

    while i < n:
        ch = formatted[i]
        if ch == "\\" and i + 1 < n and formatted[i + 1] in _ASCII_PUNCTUATION:
            text_buf.append(formatted[i : i + 2])
            i += 2
            continue
        if ch == "`":
            tick_end, found_end = _find_code_span_end(formatted, i)
            if found_end != -1:
                flush_text()
                segments.append(("code", formatted[i:found_end]))
                i = found_end
            else:
                text_buf.append(formatted[i:tick_end])
                i = tick_end
            continue
        if ch == "<":
            auto_m = _AUTOLINK_URI_RE.match(formatted, i) or _AUTOLINK_EMAIL_RE.match(formatted, i)
            if auto_m is not None:
                flush_text()
                segments.append(("html", auto_m.group(0)))
                i = auto_m.end()
                continue
            html_m = _INLINE_RAW_HTML_RE.match(formatted, i)
            if html_m is not None:
                flush_text()
                segments.append(("html", html_m.group(0)))
                i = html_m.end()
                continue
        text_buf.append(ch)
        i += 1

    flush_text()
    return segments


def _is_safe_inline_clip(candidate: str) -> bool:
    visible, suppressed = _has_visible_inline_gfm_text(candidate)
    return (
        visible
        and not suppressed
        and not _leaves_html_suppressed(candidate)
        and not _contains_raw_html_outside_code(candidate)
    )


def _ends_in_split_escape(text_part: str, take: int) -> bool:
    """判断截断点是否将 `\\` + ASCII 标点转义序列切成半个孤立反斜杠。"""
    if take <= 0 or take >= len(text_part) or text_part[take] not in _ASCII_PUNCTUATION:
        return False
    bs = 0
    idx = take - 1
    while idx >= 0 and text_part[idx] == "\\":
        bs += 1
        idx -= 1
    return bs % 2 == 1


def _clip_code_span_to_budget(raw_code: str, budget: int) -> str:
    if budget < 4:
        return ""
    k = 0
    while k < len(raw_code) and raw_code[k] == "`":
        k += 1
    inner = _extract_code_span_text(raw_code[k : len(raw_code) - k])
    for take in range(min(len(inner), budget - 3), 0, -1):
        candidate = inner[:take].rstrip()
        if not candidate:
            return ""
        wrapped = _wrap_markdown_code_span(f"{candidate}…")
        if len(wrapped) <= budget:
            return wrapped
    return ""


def _clip_text_to_safe_inline(prefix: str, text_part: str, max_len: int) -> str:
    rem = max_len - len(prefix)
    if rem <= 0:
        return ""
    max_take = min(len(text_part), rem - 1)
    for take in range(max_take, -1, -1):
        if _ends_in_split_escape(text_part, take):
            continue
        combined = (prefix + text_part[:take]).rstrip()
        if not combined:
            continue
        candidate = f"{combined}…"
        if len(candidate) <= max_len and _is_safe_inline_clip(candidate):
            return candidate
    return ""


def _clip_formatted_inline(formatted: str, max_len: int) -> str:
    """按 CommonMark §6.1 解析行内片段并在预算上限内安全截断，保持反引号闭合且不泄漏 HTML 抑制态。"""
    if len(formatted) <= max_len:
        return formatted
    if max_len < 4:
        return ""

    segments = _tokenize_inline_clip_segments(formatted)
    committed: list[tuple[Literal["text", "code", "html"], str]] = []
    prefix_parts: list[str] = []
    prefix_len = 0

    for idx, (kind, raw) in enumerate(segments):
        is_last = idx == len(segments) - 1
        if prefix_len + len(raw) < max_len or (is_last and prefix_len + len(raw) <= max_len):
            committed.append((kind, raw))
            prefix_parts.append(raw)
            prefix_len += len(raw)
            continue

        prefix = "".join(prefix_parts)
        rem = max_len - prefix_len
        if kind == "code":
            clipped_code = _clip_code_span_to_budget(raw, rem)
            if clipped_code:
                candidate = f"{prefix}{clipped_code}"
                if len(candidate) <= max_len and _is_safe_inline_clip(candidate):
                    return candidate
        elif kind == "text":
            clipped_text = _clip_text_to_safe_inline(prefix, raw, max_len)
            if clipped_text:
                return clipped_text
        break

    while committed:
        prefix = "".join(raw for _, raw in committed)
        trimmed = prefix.rstrip()
        if trimmed and len(trimmed) + 1 <= max_len:
            candidate = f"{trimmed}…"
            if _is_safe_inline_clip(candidate):
                return candidate
        last_kind, last_raw = committed.pop()
        prior_prefix = "".join(raw for _, raw in committed)
        rem = max_len - len(prior_prefix)
        if last_kind == "code":
            clipped_code = _clip_code_span_to_budget(last_raw, rem)
            if clipped_code:
                candidate = f"{prior_prefix}{clipped_code}"
                if len(candidate) <= max_len and _is_safe_inline_clip(candidate):
                    return candidate
        elif last_kind == "text":
            clipped_text = _clip_text_to_safe_inline(prior_prefix, last_raw, max_len)
            if clipped_text:
                return clipped_text

    return ""


def _render_new_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_code_location(f)
    lines = [
        f"- `[{fid}]` {loc} — **{_format_inline_markdown_field(f.category)}**",
        _format_bullet_markdown_field("失败场景：", f.failure_scenario),
        _format_bullet_markdown_field("核实证据：", vf.verifier_evidence),
    ]
    if f.class_scope:
        lines.append(_format_bullet_markdown_field("同类范围：", f.class_scope))
    lines.append(f"  - 处置：请在新提交中修复，或回复 `[{fid}] 不修：<理由>`")
    return "\n".join(lines)


def _render_prior_blocking_summary(prior_blocking: Sequence[VerifiedFinding]) -> str:
    refs = "、".join(f"`[{vf.finding.finding_id}]` {_format_code_location(vf.finding)}" for vf in prior_blocking)
    return f"- 前轮已贴出且仍未解除：{refs}"


def _render_minimal_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    return f"- `[{f.finding_id}]` {_format_code_location(f)}"


def _render_compact_new_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_code_location(f)
    cat = _format_inline_markdown_field(f.category)
    scen = _format_inline_markdown_field(f.failure_scenario)
    return f"- `[{fid}]` {loc} — {cat}：{scen}（回复 `[{fid}] 不修：<理由>`）"


_COMPACT_DESC_MAX_CHARS = 400
_COMPACT_EVIDENCE_MAX_CHARS = 200


def _collapse_prose_whitespace(chunk: str) -> str:
    """在单个段落/块内折叠非代码文本连续空白，完整保留 CommonMark §6.1 闭合行内代码内部水平空格（仅将换行转单空格）。"""
    out: list[str] = []
    for kind, raw in _tokenize_inline_clip_segments(chunk):
        if kind == "code":
            out.append(_COMMONMARK_LINE_ENDING_RE.sub(" ", raw))
        else:
            out.append(re.sub(r"\s+", " ", raw))
    return "".join(out).strip()


def _single_line(text: str) -> str:
    """将文本规整为单行：按空行分段避免跨段伪配对反引号，段落内仅折叠行内代码跨度外的连续空白。"""
    if "\n" not in text and "\r" not in text:
        return _collapse_prose_whitespace(text)
    paragraphs: list[str] = []
    current_lines: list[str] = []
    for line in _split_commonmark_lines(text):
        if not line.strip(" \t"):
            if current_lines:
                collapsed = _collapse_prose_whitespace("\n".join(current_lines))
                if collapsed:
                    paragraphs.append(collapsed)
                current_lines.clear()
        else:
            current_lines.append(line)
    if current_lines:
        collapsed = _collapse_prose_whitespace("\n".join(current_lines))
        if collapsed:
            paragraphs.append(collapsed)
    return " ".join(paragraphs)


def _render_non_blocking_item(vf: VerifiedFinding) -> str:
    f = vf.finding
    fid = f.finding_id
    loc = _format_code_location(f)
    lines = [
        f"- `[{fid}]` [{f.severity.value}] {loc} — **{_format_inline_markdown_field(f.category)}**",
        _format_bullet_markdown_field("失败场景：", f.failure_scenario),
        _format_bullet_markdown_field("核实证据：", vf.verifier_evidence),
    ]
    if f.class_scope:
        lines.append(_format_bullet_markdown_field("同类范围：", f.class_scope))
    return "\n".join(lines)


def _render_compact_non_blocking_item(vf: VerifiedFinding, max_item_chars: int) -> str | None:
    """在预算受限时将超长非阻断项降级为紧凑单行版，避免单条超长证据导致整条蒸发。"""
    f = vf.finding
    fid = f.finding_id
    loc = _format_code_location(f)
    base = f"- `[{fid}]` [{f.severity.value}] {loc}"
    if len(base) > max_item_chars:
        return None

    cat_fmt = _format_inline_markdown_field(f.category, collapse_whitespace=True)
    scen_fmt = _format_inline_markdown_field(f.failure_scenario, collapse_whitespace=True)
    desc = f"{cat_fmt}：{scen_fmt}"
    desc_budget = max_item_chars - len(base) - len(" — ")
    if len(desc) > desc_budget or len(desc) > _COMPACT_DESC_MAX_CHARS:
        cap_desc = min(desc_budget, _COMPACT_DESC_MAX_CHARS)
        if cap_desc >= 4:
            scen_budget = cap_desc - len(cat_fmt) - 1
            clipped_scen = _clip_formatted_inline(scen_fmt, scen_budget) if scen_budget >= 4 else ""
            if clipped_scen:
                head = f"{base} — {cat_fmt}：{clipped_scen}"
            else:
                clipped_cat = _clip_formatted_inline(cat_fmt, cap_desc)
                if clipped_cat:
                    head = f"{base} — {clipped_cat}"
                else:
                    return base
        else:
            return base
    else:
        head = f"{base} — {desc}"

    ev = _format_inline_markdown_field(vf.verifier_evidence, collapse_whitespace=True)
    ev_prefix = "（核实证据："
    ev_suffix = "）"
    ev_budget = max_item_chars - len(head) - len(ev_prefix) - len(ev_suffix)
    if ev_budget <= 0:
        return head
    if len(ev) <= ev_budget and len(ev) <= _COMPACT_EVIDENCE_MAX_CHARS:
        return f"{head}{ev_prefix}{ev}{ev_suffix}"
    cap = min(ev_budget, _COMPACT_EVIDENCE_MAX_CHARS)
    clipped_ev = _clip_formatted_inline(ev, cap)
    if clipped_ev:
        return f"{head}{ev_prefix}{clipped_ev}{ev_suffix}"
    return head


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
        cat_fmt = _format_inline_markdown_field(f.category)
        scen_fmt = _format_inline_markdown_field(f.failure_scenario)
        suffix = f" — {cat_fmt}：{scen_fmt}"
        if len(suffix) <= extra_budget:
            minimal_lines[idx] += suffix
            extra_budget -= len(suffix)
        elif extra_budget >= 4:
            content_budget = extra_budget - len(" — ")
            scen_budget = content_budget - len(cat_fmt) - 1
            clipped_scen = _clip_formatted_inline(scen_fmt, scen_budget) if scen_budget >= 4 else ""
            if clipped_scen:
                minimal_lines[idx] += f" — {cat_fmt}：{clipped_scen}"
            else:
                clipped_cat = _clip_formatted_inline(cat_fmt, content_budget)
                if clipped_cat:
                    minimal_lines[idx] += f" — {clipped_cat}"
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
    sha = _normalize_commit_sha(head_sha, "head_sha")
    if not isinstance(decision, RoundDecision):
        raise ConvergenceError("decision 必须是 RoundDecision")
    if sha != decision.head_sha:
        raise ConvergenceError(f"head_sha={sha!r} 与 decision.head_sha={decision.head_sha!r} 不一致")
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
    rendered_nb_items = [(vf, _render_non_blocking_item(vf)) for vf in new_non_blocking]
    all_new_nb_ids = frozenset(vf.finding.finding_id for vf in new_non_blocking)

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
            reply_note = (
                f"（理由：{_format_inline_markdown_field(vf.author_reply.reason)}）"
                if vf.author_reply is not None
                else ""
            )
            disp_label = f"`[{vf.finding.finding_id}]` {_format_code_location(vf.finding)} — {label}{reply_note}："
            disposition_lines.append(
                _format_bullet_markdown_field(
                    disp_label,
                    vf.verifier_evidence,
                    bullet_prefix="- ",
                    content_indent="  ",
                )
            )
        for vf in decision.rejected_findings:
            disp_label = f"`[{vf.finding.finding_id}]` {_format_code_location(vf.finding)} — 核实驳回："
            disposition_lines.append(
                _format_bullet_markdown_field(
                    disp_label,
                    vf.verifier_evidence,
                    bullet_prefix="- ",
                    content_indent="  ",
                )
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
            round_number=decision.round_number,
            head_sha=sha,
            body=full_text,
            posted_fingerprints=blocking_ids | all_new_nb_ids,
            deferred_fingerprints=frozenset(),
            omitted_non_blocking_fingerprints=frozenset(),
            truncated=False,
            omitted_non_blocking=(),
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
            for vf, item_text in rendered_nb_items:
                fid = vf.finding.finding_id
                candidate_nb = nb_header + "\n".join([*chosen_nb_texts, item_text])
                if current_len + 2 + len(candidate_nb) <= limit_without_note:
                    chosen_nb_texts.append(item_text)
                    included_nb_ids.add(fid)
                    continue
                if chosen_nb_texts:
                    existing_nb_len = len(nb_header) + len("\n".join(chosen_nb_texts))
                    item_budget = limit_without_note - current_len - 2 - existing_nb_len - 1
                else:
                    item_budget = limit_without_note - current_len - 2 - len(nb_header)
                compact_text = _render_compact_non_blocking_item(vf, item_budget)
                if compact_text is not None:
                    candidate_compact = nb_header + "\n".join([*chosen_nb_texts, compact_text])
                    if current_len + 2 + len(candidate_compact) <= limit_without_note:
                        chosen_nb_texts.append(compact_text)
                        included_nb_ids.add(fid)
                        continue
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
        omitted_nb_items = tuple(vf for vf in new_non_blocking if vf.finding.finding_id not in included_nb_ids)
        omitted_nb_ids = frozenset(vf.finding.finding_id for vf in omitted_nb_items)
        return RenderedComment(
            round_number=decision.round_number,
            head_sha=sha,
            body=body,
            posted_fingerprints=blocking_ids | frozenset(included_nb_ids),
            deferred_fingerprints=omitted_nb_ids,
            omitted_non_blocking_fingerprints=omitted_nb_ids,
            truncated=True,
            omitted_non_blocking=omitted_nb_items,
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
        round_number=decision.round_number,
        head_sha=sha,
        body=body,
        posted_fingerprints=blocking_ids,
        deferred_fingerprints=all_new_nb_ids,
        omitted_non_blocking_fingerprints=all_new_nb_ids,
        truncated=True,
        omitted_non_blocking=tuple(new_non_blocking),
    )
