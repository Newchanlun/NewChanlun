"""ADR 0064 r6 的 R10 Git 对象与补救原件本地核验。"""
from __future__ import annotations

import ast
from collections import defaultdict
from functools import cache
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from typing import NamedTuple


sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.at18.common import decode_json


BLOB_MODES = ("100644", "100755", "120000")
REGULAR_MODES = BLOB_MODES[:2]
OID = re.compile(r"[0-9a-f]{40}")
REMEDIATION = ".chanlun/at18/pregate-remediation.json"
REMEDIATION_SCHEMA = "at18-pregate-remediation/1"
REVIEW_ARCHIVE = ".chanlun/review-results/"
REVIEW_TREE = re.compile(r"(?:^|/)review-results/")
RESULT_TREE = (
    ".chanlun/diagnostics/", ".chanlun/reports/", "analysis/reports/", "analysis/audit_logs/",
    "analysis/dual_settle_results/", "external/k4-soros-reports/",
)
RESULT_PATH = re.compile(
    r"(?:\.?chanlun/agent-roster-[^/]*\.md|\.chanlun/codex-(?:[^/]*-verdict-[^/]*|"
    r"cli-dual-decide-result|strict-fix-acceptance4-2026-06-30)\.md|"
    r"\.chanlun/at18/(?:pregate-review|pregate/unattributed-window-audit)\.json|STRICT-NEST-[^/]*(?:-RESULT|CHECK)\.md)"
)
INPUT_MANIFEST = "INPUT-MANIFEST.json"
OUTPUT_TOKEN = re.compile(
    r"(?:^|[^a-z0-9])(?:reviews?|reports?|results?|receipts?|audits?|verify|verification|"
    r"evidence|summary|summaries|verdicts?|runs)(?=$|[^a-z0-9])"
)
REGULAR_RAW_MODES = tuple(mode.encode() for mode in REGULAR_MODES)
# 按 #1339/#1340 的归档清单只开放具名规范。索引的 role 同时标记了规范和独评，
# 不能拿来放行；签署稿与阅读版须各按自己的 Git 路径/字节判定。
ARCHIVE_BASIS_STEMS = {
    ("issue1339-r2-spec-20260909", "spec"): {
        "ARCHITECTURE-ADOPTION", "EFFECTIVE-CONTRACTS", "IMPLEMENTATION-CROSSWALK", "SPEC",
        "inputs/RESIDUAL-DECISIONS", "inputs/SPEC-COVERAGE-INPUT", "inputs/TEST-SEAMS",
    },
    ("issue1340-publication-20260909", "inputs"): {
        "LEGACY-TICKET-DISPOSITION", "RD-17-MODEL-PLAN", "RESIDUAL-TICKET-PLAN",
        "TB01-EXECUTION-SLICES", "TB01-PARENT-CONTRIBUTION",
        "TB02-06-EXECUTION-SLICES", "TB07-11-EXECUTION-SLICES",
    },
}
ARCHIVE_SPEC_FILES = {
    "payload": {"INTERFACE-CONTRACTS.md", "PUBLICATION-PREPARATION.md", "PLANNED-DAG.json"},
    "view": {"INTERFACE-CONTRACTS.md", "PUBLICATION-PREPARATION.md"},
}
EMPTY_BLOB = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
ARTIFACT_BASIS_ERROR = "verification_basis cannot cite remediation, report or receipt"
# 版本化的验收产物，即使改名也不是缺陷本身的验证依据。
ARTIFACT_SCHEMA_FAMILIES = {
    "at18-report", "at18-input-bundle", "at18-verification", "at18-pregate-remediation",
    "at18-pregate-review", "at18-landing-census", "at18-run-record", "at18-group-execution",
    "at18-scaffold-seal", "at18-diagnostic", "at18-tb-entity", "at18-key-witness",
    "newchanlun.1323.protocol-spec-review", "newchanlun.1323.scope-spec-review",
    "newchanlun.1323.tb01-dispatch-review", "newchanlun.1323.published-graph-verify",
    "newchanlun.1323.full-leaf-published-verify",
    # #1372 TB-01-C 运行、交付和独审包使用 schema（.v1 和 /1 均有）。
    "tb01c.commit_check_inventory", "tb01c.devskim_evidence_index", "tb01c.devskim_pr1451_triage",
    "tb01c.final_ac3_independent_review", "tb01c.final_bounded_independent_review",
    "tb01c.final_current_gui_independent", "tb01c.gui_lossless_and_compact_ready_independent",
    "tb01c.gui_lossless_export_independent", "tb01c.independent_review_bundle",
    "tb01c.legacy_query_callers_audit", "tb01c.q_encoded_memo_independent_review",
    "tb01c.query_encoding_memo_delivery", "tb01c.r4_independent_review",
    "tb01c.r9_r10_compatibility_increment_review",
}
MANIFEST_FIELDS = {"schemaVersion", "ticket", "base", "head", "productDiff", "requiredReports",
                   "reports", "reviews", "requiredChecks", "checks", "scan"}
ROW_KEYS = {"path", "p0_blob", "p0_mode", "f_blob", "f_mode", "remediation_commits",
            "remediation_ticket", "verdict", "defect_summary", "verification_basis"}
BASIS_KEYS = {"path", "blob", "line_start", "line_end"}
GIT_SHA = OID.pattern
NEXT_FIELD = r"[ \t]*\r?\n(?:[ \t]*\r?\n)*"
SUMMARY_HEADER = re.compile(
    rf"# AT-18 整图验收{NEXT_FIELD}结论：\*\*(?:PASS|FAIL)\*\*{NEXT_FIELD}"
    rf"主线提交：`{GIT_SHA}`[ \t]*(?:\r?\n|$)"
)
TB_RUN_HEADER = re.compile(
    r"# (?:三臂最终候选实际运行交付|最终候选 [^\r\n]+ 实际采集事实)\s+"
    rf"(?:三臂均绑定 `{GIT_SHA}`|候选 {GIT_SHA})[^\r\n]*"
    r"runtime(?: 与 |/)consumer (?:均退出|退出均为) [0-9]+[。 ，,；;]"
)
TB_REVIEW_HEADER = re.compile(
    r"# #[0-9]+ [^\r\n]+独立复核[^\r\n]*\s+"
    rf"结论：\*\*(?:PASS|BLOCK|FAIL|REJECT)[A-Z0-9_-]*\*\*。固定 [^`\r\n]+`{GIT_SHA}`"
)
RECEIPT_COMMIT = re.compile(
    rf"(?mi)^(?:[-*] )?(?:Reviewed head|Candidate commit|Head|Commit|评审提交|候选提交|受审提交)[:：][ \t]*"
    rf"(?:`{GIT_SHA}`|{GIT_SHA})[ \t]*\r?$"
)
RECEIPT_VERDICT = re.compile(
    r"(?mi)^(?:[-*] )?(?:Verdict|判定|结论)[:：][ \t]*"
    r"(?:\*\*)?(?:PASS|BLOCK|FAIL|REJECT)[A-Z0-9_-]*(?:\*\*)?[ \t]*\r?$"
)
RUN_EXIT_CODE = re.compile(r"(?mi)^(?:[-*] )?(?:Exit code|退出码)[:：][ \t]*[0-9]+[ \t]*\r?$")
RUN_RESULT = re.compile(r"(?mi)^(?:[-*] )?(?:Run result|运行结果)[:：][ \t]*(?:PASS|FAIL)[ \t]*\r?$")

REPORT_TITLE = re.compile(
    r"(?P<report>评审|复审|复核|复验|独审|独评|初审|[二三四五]审|真修|诊断|报告|结果|回执|审查|审计|汇报"
    r"|\b(?:review|report|result|receipt|audit|diagnostic|verdict)\b)|验收|判定|结论", re.I
)
REPORT_FIELD = re.compile(
    r"^\s*(?:#{1,6}\s+|(?:[-*+]|[0-9]+\.)\s+)?(?:\*\*)?"
    r"(?P<key>[\w /-]+?)(?:\*\*)?\s*[:：]\s*(?:\*\*)?(?P<value>\S.*)$"
)
DISPOSITION = re.compile(
    r"^(?:PASS(?:ED)?|FAIL(?:ED)?|BLOCK(?:ED)?|REJECT(?:ED)?|PWC|CHANGES_REQUIRED|"
    r"通过|不通过|未通过|拒绝|退回|阻断)(?=$|[\s*（(。，、；,;.！!/_-])", re.I
)
MEASUREMENT = re.compile(
    r"\bbit[- ]exact\b|\b\d+\s+(?:pass(?:ed)?|fail(?:ed)?|skip(?:ped)?)\b|"
    r"(?:进程退出|退出码|实测退出码)[：:\s]*-?\d+\b", re.I
)
REPORT_SUBJECT = re.compile(
    rf"(?:固定|受审|候选|冻结|主线)提交[ \t：:]+`?{GIT_SHA}\b|"
    r"\bgit diff[ \t]+`?[0-9a-f]{7,40}\b|(?:尖端(?: SHA)?|SHA|commit)[ \t：:]+`?[0-9a-f]{7,40}\b", re.I
)
OUTCOME_FIELDS = {"结论", "结果", "判定", "运行结果", "验收结果", "评审结论", "verdict", "result", "run result"}
EXECUTION_FIELDS = {
    "评审对象", "评审面", "评审器", "评审者", "审查对象", "实测退出码", "退出码",
    "reviewed head", "reviewer", "review target", "exit code",
}


class Entry(NamedTuple):
    mode: str
    kind: str
    blob: str


class ArchivedArtifacts(NamedTuple):
    blobs: set[str]
    loaded_inputs: set[tuple[str, str]]


class ContractError(ValueError):
    pass


def require(condition, code, message):
    if not condition:
        raise ContractError(f"{code}: {message}")


def git(*args, cwd=None, input=None):
    kwargs = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    return subprocess.check_output(["git", *args], cwd=cwd, **kwargs)


def strict_json(raw, code, identity):
    try:
        return decode_json(raw)
    except ValueError as error:
        raise ContractError(f"{code}: {identity}: {error}") from error


def read_json(path, code="PREGATE_CENSUS"):
    return strict_json(path.read_bytes(), code, path.name)


def valid_path(path):
    return (isinstance(path, str) and "\0" not in path
            and all(part not in ("", ".", "..") for part in path.split("/")))


def pre_scope(path):
    return f"pre:{path if path.isprintable() else repr(path)}"


def git_tree(head, *, cwd=None):
    """包括树和 gitlink，以区分删除与换成非法对象；不跟随符号链接。"""
    entries = {}
    for record in git("ls-tree", "-rtz", head, cwd=cwd).split(b"\0")[:-1]:
        metadata, path = record.split(b"\t", 1)
        entries[path.decode("utf-8")] = Entry(*metadata.decode("ascii").split())
    return entries


def diff_paths(parent, commit, *, cwd=None):
    raw = git("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z",
              parent, commit, cwd=cwd)
    return {path.decode("utf-8") for path in raw.split(b"\0") if path}


def window(p0, gate, head, *, cwd=None):
    commits = git("rev-list", "--first-parent", "--reverse", f"{p0}..{head}", cwd=cwd).decode().splitlines()
    require(commits and commits[0] == gate
            and git("rev-parse", f"{gate}^1", cwd=cwd).decode().strip() == p0,
            "PREGATE_REVIEW", "F must descend from G0 on the first-parent chain")
    return commits


def changes_on_window(p0, chain, paths, *, cwd=None):
    changes = defaultdict(list)
    parent = p0
    for sha in chain:
        for path in paths & diff_paths(parent, sha, cwd=cwd):
            changes[path].append(sha)
        parent = sha
    return changes


def require_blob(entry, path, side):
    require(entry.kind == "blob" and entry.mode in BLOB_MODES, "PREGATE_REVIEW",
            f"{pre_scope(path)}: not a legal {side} blob ({entry.mode}/{entry.kind})")


def final_blob_changed(path, p0, final):
    require_blob(p0, path, "P0")
    require_blob(final, path, "F")
    return p0.blob != final.blob


def classify_review(rows, final_tree):
    """只据历史裁定和 F 的最终对象分类；触及历史不决定能否进入补救。"""
    result = {}
    for row in rows:
        path = row["path"]
        p0 = Entry(row["mode"], "blob", row["blob"])
        require_blob(p0, path, "P0")
        final = final_tree.get(path)
        if final is None:
            result[path] = "deleted"
        else:
            changed = final_blob_changed(path, p0, final)
            result[path] = "pass" if row["verdict"] == "PASS" else ("changed" if changed else "hard")
    return result


def is_result_archive_path(path):
    return path.startswith(RESULT_TREE) or RESULT_PATH.fullmatch(path) is not None


def is_artifact_archive_path(path):
    if not path.startswith(REVIEW_ARCHIVE):
        return REVIEW_TREE.search(path) is not None or is_result_archive_path(path)
    parts = path.removeprefix(REVIEW_ARCHIVE).split("/", 3)
    if len(parts) != 4:
        return True
    bundle, edition, area, leaf = parts
    if edition not in ("payload", "view"):
        return True
    if (bundle, area) == ("issue1339-r2-spec-20260909", "spec") and leaf in ARCHIVE_SPEC_FILES[edition]:
        return False
    stem, _, extension = leaf.rpartition(".")
    allowed = ARCHIVE_BASIS_STEMS.get((bundle, area), ())
    return not (stem in allowed and (extension == "md" or (edition == "payload" and extension == "json")))


def frozen_copies(raw):
    try:
        doc = decode_json(raw)
    except ValueError:
        return {}
    copies = doc.get("frozen_copies") if isinstance(doc, dict) else None
    return copies if isinstance(copies, dict) else {}


def is_archive_output(path):
    review = REVIEW_TREE.search(path)
    relative = path[review.end():] if review else path
    return (relative.rsplit("/", 1)[-1].lower() == INPUT_MANIFEST.lower()
            or OUTPUT_TOKEN.search(relative.lower()) is not None)


# 只认有确定锚点的读取式，不把文件路径字符串本身当成加载证据。
JS_SUFFIXES = (".js", ".cjs", ".mjs", ".ts", ".mts", ".cts")
SOURCE_SUFFIXES = (*JS_SUFFIXES, ".rs", ".py")
BLOCK_DELIMITER = re.compile(r"/\*|\*/")
COMMON_TOKENS = (
    r'(?P<comment>//[^\r\n]*|/\*)|(?P<string>"(?:\\[^\r\n]|[^"\\\r\n])*")'
    r'|[A-Za-z_$][\w$]*|[^\s]'
)
RUST_TOKENS = re.compile(r'(?:br|r)(?P<hashes>\#*)"(?s:.*?)"(?P=hashes)|\'(?:\\.|[^\'\\\r\n])\'|'
                         + COMMON_TOKENS)
JS_ASSIGNMENTS = r"\*\*=|<<=|>>>=|>>=|&&=|\|\|=|\?\?=|[+*/%&|^\-]="
JS_OPERATORS = r"===|!==|==|!=|=>|\+\+|--|" + JS_ASSIGNMENTS
JS_TOKENS = re.compile(
    r'(?P<single>\'(?:\\[^\r\n]|[^\'\\\r\n])*\')|`(?:\\[\s\S]|[^`\\])*`'
    r'|/(?![/*])(?:\\[^\r\n]|\[(?:\\.|[^\]\\\r\n])*\]|[^/\\[\r\n])+/[dgimsuvy]*|'
    + JS_OPERATORS + "|" + COMMON_TOKENS
)


def source_tokens(text, *, rust):
    """去掉注释，把字符串/模板/正则作为不可拆分的词元。"""
    scan = RUST_TOKENS if rust else JS_TOKENS
    literals, tokens, linebreaks = {}, [], set()
    end = tail = 0
    while match := scan.search(text, end):
        token = match[0]
        end = match.end()
        if match["comment"]:
            if token == "/*":
                depth = 1
                for delimiter in BLOCK_DELIMITER.finditer(text, end):
                    if rust or delimiter[0] == "*/":
                        depth += 1 if delimiter[0] == "/*" else -1
                    if depth == 0:
                        end = delimiter.end()
                        break
                else:
                    break
            continue
        if not rust and ("\n" in text[tail:match.start()] or "\r" in text[tail:match.start()]):
            linebreaks.add(len(tokens))
        tail = end
        if match["string"] or (not rust and match["single"]):
            # 不解码转义：只承认可逐字对到仓库相对路径的字符串。
            key = f"@{len(literals)}"
            literals[key] = token[1:-1]
            tokens.append(key)
        else:
            tokens.append(token if re.fullmatch(
                r"[\w$]+|[.:=(),;!{}\[\]*]|" + JS_OPERATORS, token
            ) else "~")
    return tokens, literals, linebreaks


JS_NAME = re.compile(r"[A-Za-z_$][\w$]*")
JS_MUTATION = re.compile(r"\+\+|--|" + JS_ASSIGNMENTS)


def js_scope_declarations(tokens, linebreaks):
    """先登记块里的声明名，让内层 TDZ 也能遮蔽外层值。"""
    closes, openers = {}, []
    pairs = {")": "(", "}": "{", "]": "["}
    for i, token in enumerate(tokens):
        if token in {"(", "{", "["}:
            openers.append(i)
        elif token in pairs and openers and tokens[openers[-1]] == pairs[token]:
            closes[openers.pop()] = i

    names, declarations, blocks = defaultdict(set), {}, [-1]
    for i, token in enumerate(tokens):
        if token == "{":
            blocks.append(i)
        elif token == "}" and len(blocks) > 1:
            blocks.pop()
        elif token == "function":
            # 普通函数参数也会遮蔽模块名、__dirname 或外层路径。
            start = i + 1
            if tokens[start:start + 1] == ["*"]:
                start += 1
            if start < len(tokens) and JS_NAME.fullmatch(tokens[start]):
                start += 1
            end = closes.get(start)
            if end is not None and tokens[end + 1:end + 2] == ["{"]:
                j = start + 1
                while j < end:
                    if JS_NAME.fullmatch(tokens[j]):
                        names[end + 1].add(tokens[j])
                    while j < end and tokens[j] != ",":
                        j = closes.get(j, j) + 1
                    j += 1
        elif token in {"const", "let", "var"} and (not i or tokens[i - 1] != "."):
            j = i + 1
            while j < len(tokens) and JS_NAME.fullmatch(tokens[j]):
                names[blocks[-1]].add(tokens[j])
                name = j
                j += 1
                if (tokens[j:j + 1] == [":"] and j + 1 < len(tokens)
                        and JS_NAME.fullmatch(tokens[j + 1])):
                    j += 2  # 简单 TS 类型标注，如 const fixturePath: string。
                declarations[name] = j
                # 跳过初值里的参数/对象，不把内部逗号当成下一个声明。
                while (j < len(tokens) and tokens[j] not in {",", ";", ")", "}"}
                       and not (j in linebreaks and JS_NAME.fullmatch(tokens[j])
                                and (JS_NAME.fullmatch(tokens[j - 1]) or tokens[j - 1].startswith("@")
                                     or tokens[j - 1] in {")", "]", "}"}))):
                    j = closes.get(j, j) + 1
                if j == len(tokens) or tokens[j] != ",":
                    break
                j += 1
    return names, declarations


def js_relative_reads(tokens, literals, linebreaks):
    """只取源码位置上能绑定到内建模块与字面量的 CommonJS 读取。"""
    names, declarations = js_scope_declarations(tokens, linebreaks)
    scopes = [dict.fromkeys(names[-1])]

    def environment(name):
        return next((scope for scope in reversed(scopes) if name in scope), None)

    def value(name):
        scope = environment(name)
        return scope[name] if scope is not None else None

    def joined(start):
        if (start + 5 >= len(tokens) or value(tokens[start]) != ("module", "path")
                or tokens[start + 1:start + 5] != [".", "join", "(", "__dirname"]
                or environment("__dirname") is not None):
            return None
        j, parts = start + 5, []
        while tokens[j:j + 1] == [","]:
            j += 1
            if tokens[j:j + 1] == [")"]:
                break
            if j == len(tokens) or tokens[j] not in literals:
                return None
            parts.append(literals[tokens[j]])
            j += 1
        if parts and not any(part.startswith("/") for part in parts) and tokens[j:j + 1] == [")"]:
            return "/".join(part for part in parts if part), j + 1
        return None

    def complete(end):
        return (end == len(tokens) or tokens[end] in {";", ",", ")", "}", "]"}
                or (end in linebreaks and (tokens[end] == "{" or JS_NAME.fullmatch(tokens[end]))
                    and tokens[end] not in {"in", "instanceof", "as", "satisfies"}))

    for i, token in enumerate(tokens):
        if token == "{":
            scopes.append(dict.fromkeys(names[i]))
        elif token == "}" and len(scopes) > 1:
            scopes.pop()
        elif JS_NAME.fullmatch(token) and (not i or tokens[i - 1] != "."):
            operator = declarations.get(i, i + 1)
            if tokens[operator:operator + 1] == ["="]:
                scope = scopes[-1] if i in declarations else environment(token)
                if scope is None:
                    continue
                start = operator + 1
                binding = None
                if (i in declarations and tokens[start:start + 2] == ["require", "("]
                        and tokens[start + 3:start + 4] == [")"] and complete(start + 4)
                        and environment("require") is None):
                    module = literals.get(tokens[start + 2], "")
                    if module in {"fs", "path", "node:fs", "node:path"}:
                        binding = ("module", module.removeprefix("node:"))
                elif (path := joined(start)) is not None and complete(path[1]):
                    binding = ("path", path[0])
                scope[token] = binding
            elif (operator < len(tokens) and JS_MUTATION.fullmatch(tokens[operator])
                  or i and tokens[i - 1] in {"++", "--"}):
                if (scope := environment(token)) is not None:
                    scope[token] = None
            elif value(token) == ("module", "fs") and tokens[i + 1:i + 4] == [".", "readFileSync", "("]:
                start = i + 4
                if start == len(tokens):
                    continue
                argument = value(tokens[start])
                if argument is not None and argument[0] == "path" and tokens[start + 1:start + 2] in ([","], [")"]):
                    yield argument[1]
                elif (path := joined(start)) is not None and tokens[path[1]:path[1] + 1] in ([","], [")"]):
                    yield path[0]


def source_relative_reads(text, suffix):
    if suffix == ".py":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return
        if not any(isinstance(stmt, ast.ImportFrom) and stmt.module == "pathlib" and stmt.level == 0
                   and any(n.name == "Path" and n.asname is None for n in stmt.names) for stmt in tree.body):
            return
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            joined = node.func.value
            if node.func.attr not in {"read_bytes", "read_text"} or not isinstance(joined, ast.BinOp):
                continue
            if not isinstance(joined.op, ast.Div) or not isinstance(joined.right, ast.Constant):
                continue
            parent = joined.left
            if not isinstance(parent, ast.Attribute) or parent.attr != "parent":
                continue
            anchor = parent.value
            if (isinstance(anchor, ast.Call) and isinstance(anchor.func, ast.Name)
                    and anchor.func.id == "Path" and len(anchor.args) == 1 and not anchor.keywords
                    and isinstance(anchor.args[0], ast.Name) and anchor.args[0].id == "__file__"
                    and isinstance(joined.right.value, str)):
                yield joined.right.value
        return

    rust = suffix == ".rs"
    tokens, literals, linebreaks = source_tokens(text, rust=rust)
    if rust:
        for read in re.finditer(r"(?<!\S)include_(?:str|bytes) ! \( (@[0-9]+)(?: ,)? \)", " ".join(tokens)):
            yield literals[read[1]]
        return

    yield from js_relative_reads(tokens, literals, linebreaks)


def loaded_archive_inputs(final_tree, head, candidates, forbidden, *, cwd):
    if not candidates:
        return set()
    names = sorted({posixpath.basename(path) for path in candidates if "\n" not in path})
    if not names:
        return set()
    patterns = [part for name in names for part in ("-e", name)]
    matches = subprocess.run(
        ["git", "grep", "-IlzF", "--no-textconv", *patterns, head, "--",
         *(f"*{suffix}" for suffix in SOURCE_SUFFIXES)],
        cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, check=False,
    )
    if matches.returncode == 1:
        return set()
    matches.check_returncode()
    loaded = set()
    for record in matches.stdout.split(b"\0")[:-1]:
        path = record.split(b":", 1)[1].decode("utf-8")
        entry = final_tree.get(path)
        if (entry is None or entry.kind != "blob" or entry.mode not in REGULAR_MODES
                or REVIEW_TREE.search(path) or is_result_archive_path(path)
                or entry.blob in forbidden):
            continue
        # 读取 F 中的已跟踪普通文件，不查看工作树或执行被检查的代码。
        try:
            text = git("cat-file", "blob", f"{head}:{path}", cwd=cwd).decode("utf-8")
        except UnicodeError:
            continue
        for relative in source_relative_reads(text, PurePosixPath(path).suffix):
            if not relative or relative.startswith("/") or "\\" in relative or "\0" in relative:
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), relative))
            if target in candidates:
                loaded.add((target, candidates[target]))
    return loaded


def archive_artifact_blobs(final_tree, head, *, cwd):
    """在 F 的首父历史拒绝归档 blob；迁出的夹具只放行其被加载的路径。"""
    # 根快照及新增/变更足以覆盖已删除的产出；合并只与第一父比较。
    raw = git("log", "--root", "--first-parent", "--diff-merges=first-parent",
              "--no-renames", "--no-abbrev", "--raw", "-z", "--format=%x00%H",
              "--diff-filter=AMT", "--reverse", head, cwd=cwd)
    fields = raw.split(b"\0")
    fields.pop()
    del raw

    def additions():
        records = iter(fields)
        for metadata in records:
            if not metadata:
                commit = next(records)
                continue
            path = next(records)
            _, mode, _, blob, _ = metadata.split()
            if mode in REGULAR_RAW_MODES:
                yield commit, path, blob

    archive_paths = defaultdict(set)
    for path, entry in final_tree.items():
        if entry.kind == "blob" and entry.mode in REGULAR_MODES and is_artifact_archive_path(path):
            archive_paths[entry.blob.encode()].add(path)
    manifests = set()
    # 先限定候选；不为从未在受禁归档出现的 blob 建历史索引。
    for _, path, blob in additions():
        text_path = path.decode("utf-8", errors="surrogateescape")
        review = REVIEW_TREE.search(text_path)
        # 归档根自身的清单从来不是某个包的输入声明。
        if review and text_path[review.end():].endswith("/" + INPUT_MANIFEST):
            manifests.add(text_path)
        if is_artifact_archive_path(text_path):
            archive_paths[blob].add(text_path)
    archive_paths.pop(EMPTY_BLOB.encode(), None)
    if not archive_paths:
        return ArchivedArtifacts(set(), set())

    origins = {}
    for commit, path, blob in additions():
        if blob in archive_paths:
            first, paths = origins.setdefault(blob, (commit, []))
            if first == commit:
                paths.append(path.decode("utf-8", errors="surrogateescape"))

    manifest_dirs = tuple(path.rsplit("/", 1)[0] + "/" for path in manifests)

    @cache
    def manifest_copies(blob):
        return frozen_copies(git("cat-file", "blob", blob, cwd=cwd))

    @cache
    def declared_inputs(commit):
        # 只读首见提交的清单；仅索引 frozen_copies，不认文件列表或摘要表。
        raw_manifests = git("--literal-pathspecs", "ls-tree", "--full-tree", "-rz", commit,
                            "--", *sorted(manifests), cwd=cwd)
        declared = defaultdict(list)
        for record in raw_manifests.split(b"\0")[:-1]:
            metadata, path = record.split(b"\t", 1)
            mode, kind, blob = metadata.decode().split()
            if kind == "blob" and mode in REGULAR_MODES:
                directory = path.decode("utf-8", errors="surrogateescape").rsplit("/", 1)[0]
                for item, source in manifest_copies(blob).items():
                    if valid_path(item) and isinstance(source, str):
                        declared[f"{directory}/{item}"].append(source)
        return declared

    @cache
    def tree_at(commit):
        return git_tree(commit, cwd=cwd)

    def frozen_source_matches(source, blob, commit):
        path, separator, ref = source.strip().partition(" @ ")
        if not valid_path(path) or REVIEW_TREE.search(path) or is_result_archive_path(path) or path == REMEDIATION:
            return False
        if separator:
            # 可钉住该提交的祖先对象，不能跟随可变引用或仓外路径。
            match = re.fullmatch(r"(?:[\w./-]+ )?([0-9a-f]{7,40})", ref)
            if not match:
                return False
            revision = match[1]
            if subprocess.run(["git", "merge-base", "--is-ancestor", revision, commit],
                              cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              check=False).returncode != 0:
                return False
            commit = revision
        entry = tree_at(commit).get(path)
        return entry is not None and entry.kind == "blob" and entry.mode in REGULAR_MODES and entry.blob == blob

    def declared_copy(path, blob, commit):
        return (REVIEW_TREE.search(path) and path.startswith(manifest_dirs) and not is_archive_output(path)
                and any(frozen_source_matches(source, blob, commit)
                        for source in declared_inputs(commit).get(path, ())))

    forbidden = set()
    migrated = set()
    for raw_blob, history in archive_paths.items():
        blob = raw_blob.decode()
        if raw_blob not in origins:
            forbidden.add(blob)
            continue
        commit, paths = origins[raw_blob]
        if REMEDIATION in paths:
            forbidden.add(blob)
            continue
        restricted = [path for path in paths if is_artifact_archive_path(path)]
        # 首父上已存在的现役/具名规范原件，不会被后来的归档副本污染。
        if not restricted or all(declared_copy(path, blob, commit.decode()) for path in restricted):
            continue
        forbidden.add(blob)
        # 同期的中性别名不是起源证明；只有归档中的所有旧路径已经迁出才考虑夹具。
        if (all(REVIEW_TREE.search(path) for path in paths)
                and all(REVIEW_TREE.search(path) and path not in final_tree and not is_archive_output(path)
                        for path in history)):
            migrated.add(blob)
    candidates = {
        path: entry.blob for path, entry in final_tree.items()
        if entry.kind == "blob" and entry.mode in REGULAR_MODES and entry.blob in migrated
        and not REVIEW_TREE.search(path) and not is_result_archive_path(path)
    }
    return ArchivedArtifacts(forbidden, loaded_archive_inputs(final_tree, head, candidates, forbidden, cwd=cwd))


def is_git_sha(value):
    return isinstance(value, str) and OID.fullmatch(value) is not None


def has_outcome(value):
    return (isinstance(value, str)
            and re.fullmatch(r"(?:PASS(?:ED)?|FAIL(?:ED)?|BLOCK(?:ED)?|REJECT(?:ED)?|CHANGES_REQUIRED)(?:_[A-Z0-9]+)*",
                             value.upper()) is not None)


def is_independent_artifact(obj):
    keys = obj.keys()
    if (any(has_outcome(obj.get(key)) for key in ("conclusion", "verdict", "status"))
            and any(isinstance(obj.get(key), str) and obj[key].strip() for key in ("reviewer", "reviewer_role"))
            and keys & {"round", "review_round", "phase", "findings", "checks"}):
        return True
    # 有门禁对象与执行结果的回执；孤立的 status/result 或同名文件不是证据。
    if (isinstance(obj.get("gate"), str) and obj["gate"].strip()
            and any(has_outcome(obj.get(key)) for key in ("status", "result", "verdict", "conclusion"))
            and (isinstance(obj.get("checks"), (list, dict)) or type(obj.get("exit_code")) is int)):
        return True
    # 无版本号的独立运行回执（含 #1372 队列复验）：提交、运行状态、实际命令退出记录。
    commands = obj.get("commands")
    return (any(is_git_sha(obj.get(key)) for key in ("source_commit", "head", "commit", "candidate_commit"))
            and isinstance(obj.get("status"), str) and bool(obj["status"].strip())
            and isinstance(commands, list) and bool(commands)
            and all(isinstance(command, dict) and type(command.get("exit_code")) is int
                    and isinstance(command.get("command"), (list, str)) for command in commands))


def is_json_artifact(obj):
    for key in ("schema_version", "schema"):
        value = obj.get(key)
        version = re.fullmatch(r"(.+)(?:/|\.v)[1-9][0-9]*", value) if isinstance(value, str) else None
        if version and version[1] in ARTIFACT_SCHEMA_FAMILIES:
            return True
    if is_independent_artifact(obj):
        return True
    # deliveryManifestSchema 的票号在外层业务约束，不是清单身份的一部分。
    if (MANIFEST_FIELDS <= obj.keys() and type(obj["schemaVersion"]) is int
            and obj["schemaVersion"] == 1 and type(obj["ticket"]) is int and obj["ticket"] > 0
            and is_git_sha(obj["base"]) and is_git_sha(obj["head"])):
        return True
    # #1372 无版本号的运行事实、封存结论、独审回执和运行输出索引。
    if is_git_sha(obj.get("head")) and isinstance(obj.get("status"), str):
        if ({"process_result", "source_manifest", "semantic_core"} <= obj.keys()
                or {"runtime_manifests", "r5_b_final_seal_check"} <= obj.keys()
                or {"runtime", "consumer", "commands", "post_run_stop"} <= obj.keys()):
            return True
    if (is_git_sha(obj.get("candidate_commit"))
            and {"reviewer", "runtime", "status", "findings", "checks", "execution"} <= obj.keys()):
        return True
    if ({"argv", "expected_pids", "exit", "stdout", "stderr", "at_utc"} <= obj.keys()
            or {"ticket", "baseline", "report_kind", "platform", "ac"} <= obj.keys()):
        return True
    # 执行对拍同时记录运行时、退出状态和计数，不是只有输入/期望值的向量。
    if ({"issue", "status", "runtime", "source_basis", "exit_code", "counts"} <= obj.keys()
            and type(obj["exit_code"]) is int and isinstance(obj["counts"], dict)):
        return True
    files = obj.get("files")
    return ({"utc", "scope", "files"} <= obj.keys() and isinstance(files, list) and bool(files)
            and all(isinstance(file, dict) and {"path", "bytes", "sha256"} <= file.keys() for file in files))


def is_report_artifact(raw, text):
    content = text.lstrip("\ufeff \t\r\n")
    if content.startswith("{"):
        try:
            obj = strict_json(raw.removeprefix(b"\xef\xbb\xbf"), "PREGATE_REVIEW", "verification_basis")
        except ValueError:
            return False  # 普通源码片段无需是 JSON。
        return isinstance(obj, dict) and is_json_artifact(obj)
    # #1391 renderSummary 与 TB 报告核对正文中的绑定字段，不用标题或文件名代替。
    if any(pattern.match(content) for pattern in (SUMMARY_HEADER, TB_RUN_HEADER, TB_REVIEW_HEADER)):
        return True
    preamble = "\n".join(content.split("\n", 25)[:25])
    metadata = re.split(r"(?m)^[ \t]*(?:```|~~~)", preamble, maxsplit=1)[0]
    if RECEIPT_COMMIT.search(metadata) and (RECEIPT_VERDICT.search(metadata)
                                          or (RUN_EXIT_CODE.search(metadata) and RUN_RESULT.search(metadata))):
        return True
    lines = metadata.splitlines()
    if not lines:
        return False
    title = re.match(r"^#{1,6}[ \t]+(.+)", lines[0])
    first_field = REPORT_FIELD.match(lines[0])
    title_is_field = first_field and first_field["key"].lower() in OUTCOME_FIELDS | EXECUTION_FIELDS
    titles = list(REPORT_TITLE.finditer(title[1])) if title and not title_is_field else []
    execution = RECEIPT_COMMIT.search(metadata) is not None
    disposition = explicit_outcome = standalone_status = False
    for line in lines[1 if title and not title_is_field else 0:]:
        if (field := REPORT_FIELD.match(line)) is None:
            continue
        key, value = field["key"].lower(), field["value"].strip("`* \t")
        # 执行信息要落在实际字段中：正文提到 bit-exact 或 git diff 不算执行记录。
        if key in EXECUTION_FIELDS or REPORT_SUBJECT.search(value):
            execution = True
        if key not in OUTCOME_FIELDS:
            continue
        status = DISPOSITION.match(value)
        measured = MEASUREMENT.search(value) is not None
        execution |= measured
        if status or measured:
            disposition = True
            explicit_outcome |= bool(re.match(r"\s*(?:#|[-*+]|[0-9]+\.)", line))
        if status and not value[status.end():].strip("*。.!！ \t"):
            standalone_status = True
    # 单独的裁定值需有明确报告标题；仅称「验收」的正文仍需结构化裁定或执行记录。
    return bool((titles and (execution or explicit_outcome
                             or (standalone_status and any(m.lastgroup for m in titles))))
                or (disposition and execution))


def basis_key(item, final_tree, archived_artifacts, cache, fail, *, cwd):
    fail(isinstance(item, dict) and item.keys() == BASIS_KEYS, "invalid verification_basis keys")
    path, blob, start, end = (item[k] for k in ("path", "blob", "line_start", "line_end"))
    fail(valid_path(path), "invalid verification_basis path")
    fail(path != REMEDIATION and not is_artifact_archive_path(path), ARTIFACT_BASIS_ERROR)
    entry = final_tree.get(path)
    fail(entry is not None and entry.kind == "blob" and entry.mode in REGULAR_MODES
         and entry.blob == blob, "verification_basis must bind a regular F blob")
    fail(blob not in archived_artifacts.blobs or (path, blob) in archived_artifacts.loaded_inputs,
         ARTIFACT_BASIS_ERROR)
    if blob not in cache:
        raw = git("cat-file", "blob", entry.blob, cwd=cwd)
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            fail(False, "verification_basis must be UTF-8 text")
        fail("\0" not in text, "verification_basis must be UTF-8 text")
        fail(not is_report_artifact(raw, text), ARTIFACT_BASIS_ERROR)
        cache[blob] = text.count("\n") + bool(text and not text.endswith("\n"))
    fail(type(start) is int and type(end) is int and 1 <= start <= end <= cache[blob],
         "verification_basis line range outside F text")
    return (path.encode("utf-8"), blob.encode("utf-8"), start, end)


def check_remediation(review_rows, classes, final_tree, p0, chain, *, cwd=None, override=None):
    """核对封闭合同、Git 事实和末次集成；不产生 R09 或非作者签审结论。"""
    location = f"pre:{REMEDIATION}"

    def need(condition, detail):
        require(condition, "PREGATE_REVIEW", f"{location}: {detail}")

    entry = final_tree.get(REMEDIATION)
    if entry is not None:
        need(entry.kind == "blob" and entry.mode in REGULAR_MODES, "expected a regular remediation file in F")
        raw = git("cat-file", "blob", entry.blob, cwd=cwd)
        if override is not None:
            need(not override.is_symlink() and override.is_file() and override.read_bytes() == raw,
                 "local remediation differs from the fixed F artifact")
    elif override is not None:
        need(not override.is_symlink() and override.is_file(), "expected a regular local remediation file")
        raw = override.read_bytes()
    else:
        need(not any(state in ("hard", "changed") for state in classes.values()), "missing")
        return set()

    doc = strict_json(raw, "PREGATE_REVIEW", location)
    need(isinstance(doc, dict) and doc.keys() == {"schema_version", "owner_ticket", "rows"}
         and doc["schema_version"] == REMEDIATION_SCHEMA
         and type(doc["owner_ticket"]) is int and doc["owner_ticket"] == 2132
         and isinstance(doc["rows"], list), "invalid envelope")
    changed = {path for path, state in classes.items() if state == "changed"}
    review = {row["path"]: row for row in review_rows}
    rows = {}
    previous = b""
    for row in doc["rows"]:
        need(isinstance(row, dict) and row.keys() == ROW_KEYS, "invalid row keys")
        path = row["path"]
        need(valid_path(path), "invalid row path")
        key = path.encode("utf-8")
        need(key > previous, "rows must be unique and UTF-8 sorted")
        previous = key
        rows[path] = row
    if rows.keys() != changed:
        path = min(rows.keys() ^ changed, key=str.encode)
        detail = "missing remediation row" if path in changed else "unexpected remediation row"
        raise ContractError(f"PREGATE_REVIEW: {pre_scope(path)}: {detail}")

    if not rows:
        return changed
    changes = changes_on_window(p0, chain, changed, cwd=cwd)
    archived_artifacts = archive_artifact_blobs(final_tree, chain[-1], cwd=cwd)
    cache = {}
    for path, row in rows.items():
        def fail(condition, detail):
            require(condition, "PREGATE_REVIEW", f"{pre_scope(path)}: {detail}")

        before, final = review[path], final_tree[path]
        fail((row["p0_blob"], row["p0_mode"]) == (before["blob"], before["mode"]),
             "remediation P0 blob/mode mismatch")
        fail((row["f_blob"], row["f_mode"]) == (final.blob, final.mode),
             "remediation F blob/mode mismatch")
        fail(row["verdict"] == "REMEDIATED", "invalid remediation verdict")
        fail(type(row["remediation_ticket"]) is int and row["remediation_ticket"] > 0,
             "remediation_ticket must be a positive integer")
        fail(isinstance(row["defect_summary"], str) and row["defect_summary"].strip(),
             "defect_summary must be nonblank")
        commits = row["remediation_commits"]
        fail(isinstance(commits, list) and commits
             and all(isinstance(sha, str) and OID.fullmatch(sha) for sha in commits),
             "remediation_commits must be nonempty Git SHAs")
        touched = changes.get(path, ())
        positions = {sha: i for i, sha in enumerate(touched)}
        fail(all(sha in positions for sha in commits), "remediation commit did not change path on first parent")
        indexes = [positions[sha] for sha in commits]
        fail(indexes == sorted(set(indexes)), "remediation_commits must be unique and in first-parent order")
        fail(commits[-1] == touched[-1], "remediation_commits omits last path change (M_last)")
        basis = row["verification_basis"]
        fail(isinstance(basis, list) and basis, "verification_basis must be nonempty")
        keys = [basis_key(item, final_tree, archived_artifacts, cache, fail, cwd=cwd) for item in basis]
        fail(keys == sorted(set(keys)), "verification_basis must be unique and UTF-8 sorted")
    return changed
