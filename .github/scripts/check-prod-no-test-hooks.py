#!/usr/bin/env python3
r"""#1640 §2.3 第 2 层：s_incremental 生产构建不含测试钩子（源码机检，不编译）。

扫描本 PR 写集（`PR_WRITE_SET`，含 `rust/src/bin/s_structure_session.rs`）及其模块目录
（`MODULE_DIRS`）里名字像测试钩子的 `fn` / `static` / `thread_local!`。cfg 门由小型求值器
（any/all/not/feature/test）在生产 feature 集合 {s_session}、{s_session, s_incremental} 下以
test=false 求值；任一集合为真即生产可达，判违规。未知谓词（unix、target_os、debug_assertions
等）真假两可，保守地按「可能为真」求值，即视为生产可达。
已知生产例外列在 ALLOWLIST，新增例外须评审。
第二条轴不看名字：沿 crate 模块图找管辖面内的 `env::var` / `var_os` 读取（参数为字面量、同文件 const，
或其他表达式——后者记为不可解析，名单外即违规），增量生产构建可达的只准读 PRODUCTION_ENV，
默认构建另准 DEFAULT_BUILD_ONLY_ENV / DEFAULT_BUILD_ONLY_ENV_ARGS；改函数名绕不过此轴。
已知盲区：`use std::env::var` 后裸调 `var(..)`、别名 `use std::env as e`、turbofish、`env::vars()` 遍历。
第三条轴（#2009 方向 1）：全量扫描 `rust/src` 下所有 `.rs` 文件的字符串字面量，
默认按生产代码处理，禁止出现 `SAVEPOINT`、`ROLLBACK TO` 或对 `schema_version` 的赋值（`schema_version\s*=(?!=)`）。
仅排除编译器保证只在测试下编译的位置：文件顶层开头 `#![cfg(test)]`、外属性恰为 `#[cfg(test)]` 的完整项、
属性恰为 `#[test]` 的完整函数（及内联模块块首的 `#![cfg(test)]`）；`rust/tests/` 不在扫描范围。
其余 cfg/宏（`any(test, ...)`、`all(test, ...)`、`not(...)`、`cfg_attr(...)`、`feature = ...`、`#[tokio::test]` 等）均按生产报告。
已知边界：只检单个 `&str`/`c"..."` 字面量，不拼接 `concat!`/`format!` 跨片段拆分的关键字，也不检字节串 `b"..."`。

用法：python3 .github/scripts/check-prod-no-test-hooks.py [仓根]
exit 0 = 无违规；exit 1 = 有违规（逐条打出 文件:行）。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

# #1640 写集：`git diff --name-only da03a10ee028..HEAD -- rust/src` 的全部 `.rs`（显式列出，运行时不调 git），
# 另加这些文件所在的模块目录；新增写集文件须同步补入。
PR_WRITE_SET = (
    "rust/src/bin/s_session_v2/cache.rs",
    "rust/src/bin/s_session_v2/content_bi.rs",
    "rust/src/bin/s_session_v2/content_manifest.rs",
    "rust/src/bin/s_session_v2/content_producer.rs",
    "rust/src/bin/s_session_v2/content_publication.rs",
    "rust/src/bin/s_session_v2/content_store.rs",
    "rust/src/bin/s_session_v2/mod.rs",
    "rust/src/bin/s_session_v2/tb02a_facts.rs",
    "rust/src/bin/s_session_v3/admission_anchor.rs",
    "rust/src/bin/s_session_v3/admission_anchor/ram.rs",
    "rust/src/bin/s_session_v3/audit_header.rs",
    "rust/src/bin/s_session_v3/audit_owner.rs",
    "rust/src/bin/s_session_v3/audit_owner/effects.rs",
    "rust/src/bin/s_session_v3/audit_owner/native.rs",
    "rust/src/bin/s_session_v3/audit_owner/q.rs",
    "rust/src/bin/s_session_v3/audit_retention.rs",
    "rust/src/bin/s_session_v3/audit_store.rs",
    "rust/src/bin/s_session_v3/aux_index.rs",
    "rust/src/bin/s_session_v3/business_json.rs",
    "rust/src/bin/s_session_v3/business_json/json_layout.rs",
    "rust/src/bin/s_session_v3/catalog_evidence.rs",
    "rust/src/bin/s_session_v3/commit.rs",
    "rust/src/bin/s_session_v3/construction_state.rs",
    "rust/src/bin/s_session_v3/control_audit.rs",
    "rust/src/bin/s_session_v3/cross_request_source_cache.rs",
    "rust/src/bin/s_session_v3/driver.rs",
    "rust/src/bin/s_session_v3/fixed_radix.rs",
    "rust/src/bin/s_session_v3/generation.rs",
    "rust/src/bin/s_session_v3/history.rs",
    "rust/src/bin/s_session_v3/mod.rs",
    "rust/src/bin/s_session_v3/native_record_fields.rs",
    "rust/src/bin/s_session_v3/native_shared.rs",
    "rust/src/bin/s_session_v3/object_diff.rs",
    "rust/src/bin/s_session_v3/object_index.rs",
    "rust/src/bin/s_session_v3/object_records.rs",
    "rust/src/bin/s_session_v3/pending_source_tests.rs",
    "rust/src/bin/s_session_v3/prepared.rs",
    "rust/src/bin/s_session_v3/q_retained.rs",
    "rust/src/bin/s_session_v3/request_audit.rs",
    "rust/src/bin/s_session_v3/s_allocation.rs",
    "rust/src/bin/s_session_v3/source_audit.rs",
    "rust/src/bin/s_session_v3/source_order.rs",
    "rust/src/bin/s_session_v3/source_pending.rs",
    "rust/src/bin/s_session_v3/source_prefix.rs",
    "rust/src/bin/s_session_v3/sqlite_pager_probe.rs",
    "rust/src/bin/s_session_v3/state.rs",
    "rust/src/bin/s_session_v3/writer_cli.rs",
    "rust/src/bin/s_structure_session.rs",
    "rust/src/s_content.rs",
    "rust/src/s_content/capture_allocation/native_owned.rs",
    "rust/src/s_content/capture_allocation/native_tree.rs",
    "rust/src/s_content/capture_allocation/scratch.rs",
    "rust/src/s_content/capture_allocation/sqlite.rs",
    "rust/src/s_content/capture_allocation/work.rs",
    "rust/src/s_content/closed.rs",
    "rust/src/session_protocol.rs",
    "rust/src/session_transport.rs",
)
MODULE_DIRS = (
    "rust/src/s_content",
    "rust/src/bin/s_session_v3",
    "rust/src/bin/s_session_v2",
)
ROOTS = PR_WRITE_SET + MODULE_DIRS
PRODUCTION_FEATURE_SETS = (
    frozenset({"s_session"}),
    frozenset({"s_session", "s_incremental"}),
)
CFG_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*|"[^"]*"|[(),=]')
HOOK_NAME = re.compile(r"(_for_test|testonly|_testonly|inject|_probe_for|trace_event|TEST_HOOK)", re.I)
ITEM = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:const\s+|unsafe\s+|async\s+)*"
    r"(?:fn|static(?:\s+mut)?)\s+([A-Za-z_][A-Za-z0-9_]*)"
)
THREAD_LOCAL_ITEM = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?static\s+([A-Za-z_][A-Za-z0-9_]*)\s*:")
BLOCK = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?(?:mod|impl|trait)\b")

# 文件相对路径 → 允许的名字（门外既有生产诊断）。
ALLOWLIST: dict[str, set[str]] = {
    # sqlite_pager_probe：ADR 0042 D8 只读 pager 诊断行，#1640 b12c28f12e 新进生产；私有缓存实验已门控为 testonly。
    "rust/src/bin/s_session_v3/sqlite_pager_probe.rs": set(),
    # #1527 受限故障注入入口：dead_code、无调用方，产物不含；真实 I4/I5 验证票收口时再门控。
    "rust/src/bin/s_session_v3/admission_private/fd_wal.rs": {"inject"},
    # #1769 拒启守卫：非 production_session_testonly 构建中只返回 false 或拒绝启动，不开诊断路径。
    "rust/src/bin/s_session_v3/writer_cli.rs": {"theta_diagnostic_testonly"},
}

# 文件相对路径 → 只在默认 {s_session} 构建可达的名字。豁免仅当该条目在 {s_session, s_incremental}
# 生产增量构建下不可达时成立；去掉门控即重新判违规。
DEFAULT_BUILD_ONLY: dict[str, set[str]] = {
    # #1371 默认构建 SIGKILL 试验钩子，s_incremental 生产构建已门控排除，#1640 待主控分类。
    "rust/src/bin/s_structure_session.rs": {"testonly_pause"},
}
DEFAULT_BUILD = frozenset({"s_session"})
INCREMENTAL_BUILD = frozenset({"s_session", "s_incremental"})

# 第二条轴（不看函数名）：管辖面内生产可达的运行时环境变量读取（`std::env::var` / `var_os`）。
# 生产写者只准读下列变量；其余读取一律视为测试/诊断开关入口，须 cfg 门控出生产构建。
PRODUCTION_ENV: dict[str, str] = {
    "S_CONTROL_INSTANCE_ID": "launcher 下发的控制实例身份（writer_cli / q_serve / v2 回执）",
    "S_CONTROL_ADMISSION_SHA256": "launcher 下发的准入锚摘要（admission_anchor）",
    "S_CONTROL_ADMISSION_IDENTITY": "launcher 下发的准入锚身份（admission_anchor）",
    "S_CONTROL_START_GATE": "#1527 托管 serve 的父进程登记握手（admission_anchor）",
    "S_CONTROL_RESOURCE_SHA256": "launcher 下发的资源档摘要（writer_cli）",
    "S_MANIFEST_WORKSPACE_DIAGNOSTICS": "ADR 0042 D8 诊断行开关（#1640 b12c28f12e 随 sqlite_pager_probe 新进生产）",
    "S_THETA_DIAGNOSTIC_TESTONLY": "#1769 拒启守卫：生产构建读到即拒绝启动（writer_cli parse_theta_diagnostic），不开诊断臂",
}
# 只在默认 {s_session} 构建可达的环境变量（与 DEFAULT_BUILD_ONLY 同一豁免口径：增量生产构建须门控排除）。
DEFAULT_BUILD_ONLY_ENV: dict[str, str] = {
    "S_SESSION_PAUSE": "#1371 testonly_pause",
    "S_SESSION_PAUSE_DB": "#1371 testonly_pause",
    "S_SESSION_PAUSE_MARKER": "#1371 testonly_pause",
    "S_SESSION_PAUSE_RELEASE": "#1371 testonly_pause",
    "S_SESSION_PRAGMA_SIDECAR": "#1371 record_connection_pragmas 诊断 sidecar",
    "S_SESSION_PRAGMA_SIDECAR_DB": "#1371 record_connection_pragmas 诊断 sidecar",
    "S_SESSION_PRAGMA_SIDECAR_PATH": "#1371 record_connection_pragmas 诊断 sidecar",
    "SESSION_TRANSPORT_TESTONLY_TRACE_DIR": "#1374 输送读轨迹（#1640 A9 与 testonly_pause 同门）",
}
# 参数不是字面量也不是同文件 const 的读取：文件 → 允许的参数名（同样只准默认构建可达）。
DEFAULT_BUILD_ONLY_ENV_ARGS: dict[str, set[str]] = {
    # #1394 对照臂选择：S_CAPTURE_NATIVE_TESTONLY 与 Owned 私有输入，增量生产构建走 incremental_mode()。
    "rust/src/bin/s_session_v3/s_allocation.rs": {"name"},
}
NON_LITERAL = "<非字面量参数 "
# 第三条轴（#2009 方向 1）：rust/src 全量扫描，非测试位置的字符串字面量禁含 SAVEPOINT、ROLLBACK TO 或 schema_version 写。
RAW_SQL_SCAN_DIR = "rust/src"
RAW_SQL_PATTERN = re.compile(r"\bsavepoint\b|\brollback\s+to\b|\bschema_version\s*=(?!=)", re.I)
# 逐条显式豁免表：(相对路径, 完整字面量原文) -> 理由。三者全等才豁免，禁止通配、目录或正则。
RAW_SQL_LITERAL_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "rust/src/theta_v0/venue_fee/datum_io.rs",
        "venue fee datum {}: schema_version={} 不受支持（本实装只认 {}）",
    ): "非 S owner 的回测 datum JSON 版本校验报错格式串，不是可执行 SQL（仅在 backtest_bin/test 编入）",
}
_RAW_STR_HEAD = re.compile(r'(?:b|c)?r(#*)"')
_WS = re.compile(r"\s+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'"}
_INNER_CFG_TEST = re.compile(r"^#!\[\s*cfg\s*\(\s*test\s*\)\s*\]$")
_OUTER_CFG_TEST = re.compile(r"^#\[\s*cfg\s*\(\s*test\s*\)\s*\]$")
_OUTER_TEST_ATTR = re.compile(r"^#\[\s*(?:::\s*)?(?:(?:core|std)\s*::\s*prelude\s*::\s*v1\s*::\s*)?test\s*\]$")


def parse_cfg(text: str):
    tokens = CFG_TOKEN.findall(text)
    position = 0

    def node():
        nonlocal position
        name = tokens[position]
        position += 1
        if position < len(tokens) and tokens[position] == "(":
            position += 1
            args = []
            while tokens[position] != ")":
                args.append(node())
                if tokens[position] == ",":
                    position += 1
            position += 1
            return ("call", name, args)
        if position < len(tokens) and tokens[position] == "=":
            position += 1
            value = tokens[position].strip('"')
            position += 1
            return ("pair", name, value)
        return ("word", name)

    return node()


def cfg_outcomes(tree, features) -> frozenset:
    """cfg 在给定 feature 集合、test=false 下可能取到的真值；未知谓词两值皆可能。"""
    if tree[0] == "call":
        _, name, args = tree
        if name in ("any", "all"):
            outcomes = [cfg_outcomes(arg, features) for arg in args]
            if name == "any":
                can_true = any(True in o for o in outcomes)
                can_false = all(False in o for o in outcomes)
            else:
                can_true = all(True in o for o in outcomes)
                can_false = any(False in o for o in outcomes)
            return frozenset(v for v, ok in ((True, can_true), (False, can_false)) if ok)
        if name == "not" and len(args) == 1:
            return frozenset(not v for v in cfg_outcomes(args[0], features))
        return frozenset({True, False})
    if tree[0] == "pair" and tree[1] == "feature":
        return frozenset({tree[2] in features})
    if tree == ("word", "test"):
        return frozenset({False})
    return frozenset({True, False})


def evaluate_cfg(tree, features) -> bool:
    """可能为真即判真：未知谓词（unix、target_os、debug_assertions 等）保守视为生产可达。"""
    return True in cfg_outcomes(tree, features)


def reachable_in(cfg_text: str, features) -> bool:
    body = cfg_text.strip()
    if body.startswith("#[cfg("):
        body = body[len("#[cfg(") :]
    if body.endswith(")]"):
        body = body[:-2]
    try:
        tree = parse_cfg(body)
    except (IndexError, ValueError):
        return True
    return evaluate_cfg(tree, features)


def production_reachable(cfg_text: str) -> bool:
    return any(reachable_in(cfg_text, features) for features in PRODUCTION_FEATURE_SETS)


def gate_is_test(cfg_text: str) -> bool:
    """生产 feature 集合下（test=false）均不可达才算测试门。"""
    return not production_reachable(cfg_text)


def scan(path: Path, rel: str) -> list[str]:
    if rel in ALLOWLIST and not ALLOWLIST[rel]:
        return []
    allowed = ALLOWLIST.get(rel, set())
    lines = path.read_text(encoding="utf-8").splitlines()
    violations: list[str] = []
    pending: list[str] = []  # 当前条目之前累积的 #[cfg(...)] 文本（cfg_attr 不门控编译，不计）
    attr: list[str] = []  # 跨行属性的累积
    stack: list[list] = []  # [块起始深度, 该 mod/impl 自身的 cfg 列表, 是否已见到 `{`]
    depth = 0
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if attr or stripped.startswith("#["):
            attr.append(stripped)
            text = " ".join(attr)
            if text.count("[") <= text.count("]"):
                if text.startswith("#[cfg("):
                    pending.append(text)
                attr = []
            continue
        chain = [c for _, gates, _ in stack for c in gates] + pending
        reachable = [f for f in PRODUCTION_FEATURE_SETS if all(reachable_in(c, f) for c in chain)]
        gated = not reachable
        if BLOCK.match(line):
            stack.append([depth, list(pending), False])
        else:
            item = ITEM.match(line) or THREAD_LOCAL_ITEM.match(line)
            default_only = item and item.group(1) in DEFAULT_BUILD_ONLY.get(rel, set()) and reachable == [DEFAULT_BUILD]
            if (item and HOOK_NAME.search(item.group(1)) and item.group(1) not in allowed and not gated
                    and not default_only):
                violations.append(f"{rel}:{number}: {item.group(1)} 未受 cfg(test)/testonly 门控")
        if stripped:
            pending = []
        depth += line.count("{") - line.count("}")
        if stack and depth > stack[-1][0]:
            stack[-1][2] = True
        while stack and (depth < stack[-1][0] or (stack[-1][2] and depth <= stack[-1][0]) or stripped.endswith(";") and not stack[-1][2]):
            stack.pop()
    return violations


_GEN = None


def load_gen():
    """crate 模块图遍历与 cfg 链求值复用第 3 层生成器（它反向载入本文件求 cfg）。"""
    global _GEN
    if _GEN is None:
        spec = importlib.util.spec_from_file_location(
            "gen_prod_banned_literals", Path(__file__).with_name("gen-prod-banned-literals.py")
        )
        _GEN = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_GEN)
    return _GEN


def env_violations(root: Path) -> list[str]:
    """沿 crate 模块图（含 `#[cfg] mod x;` 与 fn/块作用域）求每处环境变量读取的 cfg 链。"""
    gen = load_gen()
    reads: list = []
    gen.collect(root, reads)
    violations = []
    for name, chain, path in reads:
        if not gen.in_scope(root, path.resolve()) or name in PRODUCTION_ENV:
            continue
        rel = path.resolve().relative_to(root).as_posix()
        if gen.reachable(chain, INCREMENTAL_BUILD, False):
            violations.append(f"{rel}: 环境变量 {name} 在 s_incremental 生产构建可达（未列入 PRODUCTION_ENV）")
        elif (gen.reachable(chain, DEFAULT_BUILD, False) and name not in DEFAULT_BUILD_ONLY_ENV
              and name.removeprefix(NON_LITERAL).rstrip(">") not in DEFAULT_BUILD_ONLY_ENV_ARGS.get(rel, set())):
            violations.append(f"{rel}: 环境变量 {name} 在默认 s_session 构建可达（未列入 DEFAULT_BUILD_ONLY_ENV）")
    return violations


def _skip_string(text: str, quote: int) -> int:
    index, size = quote + 1, len(text)
    while index < size and text[index] != '"':
        index += 2 if text[index] == "\\" else 1
    return min(index + 1, size)


def _skip_char(text: str, index: int, size: int) -> int:
    if text[index + 1 : index + 2] == "\\":
        end = text.find("'", index + 3)
        return size if end < 0 else end + 1
    if index + 2 < size and text[index + 2] == "'":
        return index + 3
    return index + 1


def _unescape(raw: str) -> str | None:
    out, index, size = [], 0, len(raw)
    while index < size:
        char = raw[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= size:
            return None
        code = raw[index + 1]
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
            index += 2
        elif code == "x" and index + 4 <= size:
            out.append(chr(int(raw[index + 2 : index + 4], 16)))
            index += 4
        elif code == "u" and "}" in raw[index + 2 :]:
            end = raw.index("}", index)
            out.append(chr(int(raw[index + 3 : end], 16)))
            index = end + 1
        elif code == "\n" or (code == "\r" and raw[index + 2 : index + 3] == "\n"):
            index += 2 if code == "\n" else 3
            while index < size and raw[index] in " \t\r\n":
                index += 1
        else:
            return None
    return "".join(out)


def _raw_sql_lex(text: str):
    """单遍 O(n) 词法扫描：跳注释/字符/生命周期，产出 (1-based 起始行, kind, value)。"""
    index, size, line = 0, len(text), 1
    while index < size:
        char = text[index]
        if char.isspace():
            end = _WS.match(text, index).end()
            line += text.count("\n", index, end)
            index = end
        elif char == "/" and text.startswith("//", index):
            end = text.find("\n", index)
            index = size if end < 0 else end
        elif char == "/" and text.startswith("/*", index):
            depth, end = 1, index + 2
            while depth and end < size:
                if text.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif text.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
            line += text.count("\n", index, end)
            index = end
        elif char == "#" and (text.startswith("[", index + 1) or text.startswith("![", index + 1)):
            start_line = line
            end = text.index("[", index) + 1
            depth = 1
            while depth and end < size:
                inner = text[end]
                if inner in "bcr" and (raw := _RAW_STR_HEAD.match(text, end)) and (
                    end == 0 or not (text[end - 1].isalnum() or text[end - 1] == "_")
                ):
                    hashes = raw.group(1)
                    close = text.find('"' + hashes, raw.end())
                    end = size if close < 0 else close + 1 + len(hashes)
                    continue
                if inner == '"':
                    end = _skip_string(text, end)
                    continue
                if inner == "'":
                    end = _skip_char(text, end, size)
                    continue
                depth += {"[": 1, "]": -1}.get(inner, 0)
                end += 1
            yield (start_line, "attr", _WS.sub(" ", text[index:end]))
            line += text.count("\n", index, end)
            index = end
        else:
            raw = _RAW_STR_HEAD.match(text, index) if char in "bcr" else None
            if raw and (index == 0 or not (text[index - 1].isalnum() or text[index - 1] == "_")):
                start_line = line
                hashes = raw.group(1)
                start = raw.end()
                close = text.find('"' + hashes, start)
                if close < 0:
                    break
                yield (start_line, "str", None if char == "b" else text[start:close])
                next_index = close + 1 + len(hashes)
                line += text.count("\n", index, next_index)
                index = next_index
            elif char == '"' or (char in "bc" and text[index + 1 : index + 2] == '"'):
                start_line = line
                quote = index if char == '"' else index + 1
                end = _skip_string(text, quote)
                yield (start_line, "str", None if char == "b" else _unescape(text[quote + 1 : end - 1]))
                line += text.count("\n", index, end)
                index = end
            elif char == "'":
                end = _skip_char(text, index, size)
                line += text.count("\n", index, end)
                index = end
            elif (match := _IDENT.match(text, index)):
                yield (line, "ident", match.group(0))
                index = match.end()
            else:
                yield (line, "punct", char)
                index += 1


class _SqlBlockFrame:
    __slots__ = (
        "excluded",
        "at_block_start",
        "paren_depth",
        "bracket_depth",
        "pending_cfg_test",
        "pending_test_attr",
        "pending_saw_fn",
        "closes_outer_item",
        "was_excluded_item",
        "just_closed_excluded_block",
    )

    def __init__(
        self,
        excluded: bool,
        at_block_start: bool = True,
        closes_outer_item: bool = False,
        was_excluded_item: bool = False,
    ) -> None:
        self.excluded = excluded
        self.at_block_start = at_block_start
        self.paren_depth = 0
        self.bracket_depth = 0
        self.pending_cfg_test = False
        self.pending_test_attr = False
        self.pending_saw_fn = False
        self.closes_outer_item = closes_outer_item
        self.was_excluded_item = was_excluded_item
        self.just_closed_excluded_block = False


def _scan_raw_sql_file(path: Path) -> tuple[int, list[tuple[int, str | None]]]:
    """扫描单个 .rs 文件，返回 (全文件字符串 token 数, 非测试位置的字符串字面量列表)。"""
    tokens = list(_raw_sql_lex(path.read_text(encoding="utf-8")))
    frames = [_SqlBlockFrame(excluded=False, at_block_start=True)]
    all_str_tokens = 0
    prod_literals: list[tuple[int, str | None]] = []
    for pos, (line, kind, value) in enumerate(tokens):
        frame = frames[-1]
        if frame.just_closed_excluded_block:
            frame.just_closed_excluded_block = False
            if kind == "ident" and value == "else":
                frame.pending_cfg_test = True
        if kind == "attr":
            if value.startswith("#!["):
                if frame.at_block_start and frame.paren_depth == 0 and frame.bracket_depth == 0:
                    if _INNER_CFG_TEST.match(value):
                        frame.excluded = True
            else:
                frame.at_block_start = False
                if frame.paren_depth == 0 and frame.bracket_depth == 0:
                    if _OUTER_CFG_TEST.match(value):
                        frame.pending_cfg_test = True
                    elif _OUTER_TEST_ATTR.match(value):
                        frame.pending_test_attr = True
            continue
        frame.at_block_start = False
        if kind == "ident" and value == "fn" and frame.paren_depth == 0 and frame.bracket_depth == 0:
            if pos + 1 < len(tokens) and tokens[pos + 1][1] == "ident":
                frame.pending_saw_fn = True
        elif kind == "str":
            all_str_tokens += 1
            item_excluded = (
                frame.excluded
                or frame.pending_cfg_test
                or (frame.pending_test_attr and frame.pending_saw_fn)
            )
            if not item_excluded:
                prod_literals.append((line, value))
        elif kind == "punct":
            if value == "(":
                frame.paren_depth += 1
            elif value == ")":
                frame.paren_depth = max(0, frame.paren_depth - 1)
            elif value == "[":
                frame.bracket_depth += 1
            elif value == "]":
                frame.bracket_depth = max(0, frame.bracket_depth - 1)
            elif value == "{":
                item_excluded = frame.pending_cfg_test or (frame.pending_test_attr and frame.pending_saw_fn)
                if frame.paren_depth == 0 and frame.bracket_depth == 0:
                    frames.append(
                        _SqlBlockFrame(
                            excluded=frame.excluded or item_excluded,
                            at_block_start=True,
                            closes_outer_item=True,
                            was_excluded_item=item_excluded,
                        )
                    )
                    frame.pending_cfg_test = False
                    frame.pending_test_attr = False
                    frame.pending_saw_fn = False
                else:
                    frames.append(
                        _SqlBlockFrame(
                            excluded=frame.excluded or item_excluded,
                            at_block_start=True,
                            closes_outer_item=False,
                            was_excluded_item=False,
                        )
                    )
            elif value == "}":
                if len(frames) > 1:
                    closed = frames.pop()
                    if closed.closes_outer_item and closed.was_excluded_item:
                        frames[-1].just_closed_excluded_block = True
            elif value == ";" and frame.paren_depth == 0 and frame.bracket_depth == 0:
                frame.pending_cfg_test = False
                frame.pending_test_attr = False
                frame.pending_saw_fn = False
    return all_str_tokens, prod_literals


def raw_sql_violations(root: Path) -> list[str]:
    """#2009 第三条轴：全量扫描 rust/src/**/*.rs，非测试位置字面量禁含 SAVEPOINT / ROLLBACK TO / schema_version 写。"""
    root = root.resolve()
    src_dir = root / RAW_SQL_SCAN_DIR
    if not src_dir.is_dir():
        return []
    violations: list[str] = []
    for path in sorted(src_dir.rglob("*.rs")):
        rel = path.relative_to(root).as_posix()
        _, prod_literals = _scan_raw_sql_file(path)
        for line, value in prod_literals:
            if value is None or (rel, value) in RAW_SQL_LITERAL_ALLOWLIST:
                continue
            match = RAW_SQL_PATTERN.search(value)
            if match is not None:
                matched = _WS.sub(" ", match.group(0))
                violations.append(
                    f"{rel}:{line}: 生产可达字符串字面量含禁用裸 SQL 模式（{matched}，#2009）"
                )
    return violations


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    violations: list[str] = []
    seen: set[Path] = set()
    for base in ROOTS:
        target = root / base
        if not target.exists():
            violations.append(f"{base}: ROOTS 条目不存在（写集或模块目录已改名，须同步检查器）")
            continue
        paths = [target] if target.is_file() else sorted(target.rglob("*.rs"))
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            violations.extend(scan(path, path.relative_to(root).as_posix()))
    violations.extend(env_violations(root))
    violations.extend(raw_sql_violations(root))
    for violation in violations:
        print(f"::error::{violation}")
    print(f"check-prod-no-test-hooks violations={len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
