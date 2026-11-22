"""ADR 0064 r6 的 R10 Git 对象与补救原件本地核验。"""
from __future__ import annotations

import ast
from collections import defaultdict
from enum import Enum, auto
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

# 名分由标题与前导证据共同决定；指南/规范中的审阅步骤不是执行记录。
REPORT_TITLE = re.compile(
    r"评审|复审|复核|复验|独审|独评|初审|[二三四五]审|真修|诊断结果|诊断(?:纪要|记录)?|"
    r"报告|结果(?:包)?|回执|审查|审计|汇报|终判|判决|(?:实测|验证|检验)裁决|回测(?:对照|复验|判决)?|验证|"
    r"\b(?:review|report|results?|receipt|audit|diagnostic|verdict)\b", re.I
)
RULE_TITLE = re.compile(
    r"指南|操作手册|预检|规范|规格|合同|协议|设计|方案|施工单|计划|提案|模板|"
    r"\b(?:guide|handbook|preflight|specification|contract|design)\b", re.I
)
ADR_TITLE = re.compile(r"^ADR[ -]+\d+\b", re.I)
MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
MD_LIST = re.compile(r"^(?:[-*+]|[0-9]+[.)])\s+")
MD_QUOTE = re.compile(r"^(?:>\s*)+")
REPORT_FIELD = re.compile(r"^(?P<key>[^：:|]{1,48}?)\s*[:：]\s*(?P<value>\S.*)$")
DISPOSITION = re.compile(
    r"(?<![\w-])(?:PASS(?:ED)?|FAIL(?:ED)?|BLOCK(?:ED)?|REJECT(?:ED)?|PWC|CHANGES_REQUIRED|"
    r"VERIFIED|ACCEPTED|ERROR)(?=$|[^\w-])|"
    r"有保留通过|不通过|未通过|通过|退回|拒绝|证伪|否证|全过|未修复|已修复|不成立|成立|实测|✅|❌", re.I
)
MEASUREMENT = re.compile(
    r"\bbit[- ]exact\b|\b\d+\s+(?:pass(?:ed)?|fail(?:ed)?|skip(?:ped)?)\b|"
    r"(?:进程退出|退出码|退出|EXIT)[：:\s]*-?\d+\b|修复项\s*=\s*\d+|全量跑通|全绿|零 panic", re.I
)
REPORT_SUBJECT = re.compile(
    r"(?:固定|受审|候选|冻结|主线)提交[ \t：:]+`?[0-9a-f]{7,40}\b|"
    r"\bgit diff[ \t]+`?[0-9a-f]{7,40}\b|(?:尖端(?: SHA)?|SHA|commit)[ \t：:]+`?[0-9a-f]{7,40}\b"
    r"|本次(?:审计|评审|复验)内执行", re.I
)
OUTCOME_KEY = re.compile(
    r"(?:本报告的?)?(?:一句话|核心|报告|执行|审计|评审|验收|运行|调研|修复|实证|最终|总)*(?:结论|结果|判定|裁决|判决|终判|总评|执行摘要|关键发现)"
    r"(?:提前给出|速览|摘要|汇总)?|(?:run )?result|verdict|status", re.I
)
EXECUTION_KEY = re.compile(
    r"(?:审计|审查|评审|复审|复验|测试|验证|调研|诊断)(?:范围|方法|方式|对象|日期|人|者|面|器|脚本|等级)|"
    r"任务|起点 commit|(?:固定|受审|候选|冻结|主线|评审)提交|实测|交付物|生成时间|总耗时|"
    r"脚本|跑法|探针|样本|数据来源|信号总数|审计基准|实测日期|验证等级|认识论等级|本次修改|"
    r"(?:测试|运行|实测)?退出码|产出文件|reviewed head|reviewer|review target|exit code", re.I
)
TABLE_RULE = re.compile(r":?-{3,}:?")
RUN_METRIC = re.compile(r"\d[\d,]*(?:[.]\d+)?\s*(?:%|pp\b|ms\b|bars?\b|笔|组|例)|"
                        r"(?:[^\s=:]+)\s*=\s*-?\d", re.I)
RUN_COLUMN = re.compile(r"回报|收益|覆盖率|复利|胜率|耗时|交易数|实测|bars|sharpe|drawdown|ms/bar|trades|MDD|BH|P&L|年化|回测|bps|卖飞率", re.I)



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
JS_OPERATORS = JS_ASSIGNMENTS + r"|===|!==|==|!=|=>|\+\+|--|\.\.\.|\?\.|\?\?|\|\||&&"
JS_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)"
    r"(?:[eE][+-]?[\d_]+)?"
)
JS_TOKENS = re.compile(
    r'(?P<single>\'(?:\\[^\r\n]|[^\'\\\r\n])*\')|`(?:\\[\s\S]|[^`\\])*`'
    r'|/(?![/*])(?:\\[^\r\n]|\[(?:\\.|[^\]\\\r\n])*\]|[^/\\[\r\n])+/[dgimsuvy]*|'
    + JS_OPERATORS + "|" + JS_NUMBER.pattern + "|" + COMMON_TOKENS
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
                r"[\w$]+|[.:=(),;!{}\[\]*?+<>|\-]|" + JS_OPERATORS + "|" + JS_NUMBER.pattern, token
            ) else "~")
    return tokens, literals, linebreaks


JS_NAME = re.compile(r"[A-Za-z_$][\w$]*")
JS_MUTATION = re.compile(r"\+\+|--|" + JS_ASSIGNMENTS)
JS_CONTINUATION = {".", "?.", ",", "in", "instanceof", "as", "satisfies", "of"}
JS_CONTROL = {"if", "else", "while", "for", "switch", "catch", "with"}
JS_UNKNOWN = frozenset()


class JSAtom(Enum):
    TDZ = auto()
    FS = auto()
    PATH = auto()


class JSScope(NamedTuple):
    function: bool
    bindings: dict[str, frozenset[str] | JSAtom]


class JSStatement(NamedTuple):
    kind: str
    span: tuple[int, int]
    children: tuple[JSStatement, ...] = ()


def js_join_values(values):
    first, *rest = values
    if all(value == first for value in rest):
        return first
    return JS_UNKNOWN.union(*(value for value in values if isinstance(value, frozenset)))


def js_join(*scopes):
    """同一程序点的路径取并集；内建模块须在各分支保持相同来源。"""
    return tuple(JSScope(frames[0].function, {
        name: js_join_values([frame.bindings[name] for frame in frames])
        for name in frames[0].bindings
    }) for frames in zip(*scopes))


def js_merge(target, source):
    for completion, env in source.items():
        target[completion] = js_join(target[completion], env) if completion in target else env


class JSFixtureReads:
    """对固定 CommonJS 读式做源码级解释；不执行代码，不推断动态模块、路径或调用。"""

    def __init__(self, tokens, literals, linebreaks):
        self.t = tokens
        self.literals = literals
        self.linebreaks = linebreaks
        self.groups = {}
        stack = []
        pairs = {")": "(", "}": "{", "]": "["}
        for i, token in enumerate(tokens):
            if token in pairs.values():
                stack.append(i)
            elif token in pairs and stack and tokens[stack[-1]] == pairs[token]:
                self.groups[stack.pop()] = i
        self.reads = set()

    def level(self, lo, hi):
        """只遍历当前括号层；表达式中的内部逗号、冒号和花括号各归其主。"""
        while lo < hi:
            yield lo
            lo = self.groups.get(lo, lo) + 1

    def split(self, lo, hi, delimiter=","):
        for i in self.level(lo, hi):
            if self.t[i] == delimiter:
                yield lo, i
                lo = i + 1
        yield lo, hi

    def statement_end(self, lo, hi):
        for i in self.level(lo, hi):
            token = self.t[i]
            if token == ";" or token in {"else", "catch", "finally"}:
                return i
            if i > lo and i in self.linebreaks and token not in JS_CONTINUATION:
                prior = self.t[i - 1]
                if ((JS_NAME.fullmatch(prior) and prior not in JS_CONTROL | {"function", "new", "const", "let", "var"})
                        or prior.startswith("@") or prior in {")", "]", "}"}):
                    if JS_NAME.fullmatch(token) or token == "{":
                        return i
        return hi

    def sequence(self, lo, hi):
        result = []
        while lo < hi:
            node, lo = self.statement(lo, hi)
            result.append(node)
        return tuple(result)

    def statement(self, lo, hi):
        t = self.t
        if lo >= hi:
            return JSStatement("empty", (lo, lo)), lo
        kind = t[lo]
        if kind == ";":
            return JSStatement("empty", (lo, lo)), lo + 1
        if kind == "{" and lo in self.groups:
            close = self.groups[lo]
            return JSStatement("block", (lo + 1, close), self.sequence(lo + 1, close)), close + 1
        if kind in {"if", "switch", "for", "while"} and t[lo + 1:lo + 2] == ["("] and lo + 1 in self.groups:
            close = self.groups[lo + 1]
            span = (lo + 2, close)
            if kind == "switch" and t[close + 1:close + 2] == ["{"] and close + 1 in self.groups:
                end = self.groups[close + 1]
                return JSStatement(kind, span, self.cases(close + 2, end)), end + 1
            if kind != "switch":
                body, end = self.statement(close + 1, hi)
                children = (body,)
                if kind == "if" and end < hi and t[end] == "else":
                    other, end = self.statement(end + 1, hi)
                    children += (other,)
                return JSStatement(kind, span, children), end
        if kind == "try" and t[lo + 1:lo + 2] == ["{"]:
            body, end = self.statement(lo + 1, hi)
            handlers = [body]
            if t[end:end + 1] == ["catch"]:
                start = end + 1
                close = self.groups.get(start) if t[start:start + 1] == ["("] else None
                catch, end = self.statement(close + 1 if close is not None else start, hi)
                params = (start + 1, close) if close is not None else (start, start)
                handlers.append(JSStatement("catch", params, catch.children))
            if t[end:end + 1] == ["finally"]:
                final, end = self.statement(end + 1, hi)
                handlers.append(JSStatement("finally", final.span, final.children))
            return JSStatement("try", (lo, end), tuple(handlers)), end
        # 声明的函数（含 class）在闭合大括号处结束，不吞下同一行的下一条语句。
        prefix = lo
        while t[prefix:prefix + 1] and t[prefix] in {"export", "default", "async"}:
            prefix += 1
        if t[prefix:prefix + 1] and t[prefix] in {"function", "class"}:
            for i in self.level(prefix + 1, hi):
                if t[i] == "{" and i in self.groups:
                    end = self.groups[i] + 1
                    return JSStatement("function-decl", (prefix, end)), end
                if t[i] == ";":
                    break
        end = self.statement_end(lo, hi)
        if end == lo:  # 非本分析子集的孤立控制词也要推进。
            return JSStatement("empty", (lo, lo)), lo + 1
        after = end + (end < hi and t[end] == ";")
        if kind in {"let", "const", "var", "return", "throw", "break", "continue"}:
            start = lo + 1
            if kind == "return" and start in self.linebreaks:
                return JSStatement(kind, (start, start)), start
            return JSStatement(kind, (start, end)), after
        return JSStatement("expr", (lo, end)), after

    def cases(self, lo, hi):
        labels = []
        for i in self.level(lo, hi):
            if self.t[i] not in {"case", "default"}:
                continue
            depth = 0
            for j in self.level(i + 1, hi):
                token = self.t[j]
                if token == ":" and not depth:
                    labels.append((self.t[i], i + 1, j))
                    break
                depth += (token == "?") - (token == ":")
        return tuple(JSStatement(kind, (start, colon), self.sequence(
            colon + 1, labels[k + 1][1] - 1 if k + 1 < len(labels) else hi,
        )) for k, (kind, start, colon) in enumerate(labels))

    def binding_pattern(self, lo, hi):
        # 解构可遮蔽内建名，但不从解构的值推导模块或路径。
        if lo >= hi:
            return
        token = self.t[lo]
        if token == "...":
            yield from self.binding_pattern(lo + 1, hi)
        elif JS_NAME.fullmatch(token):
            yield token
        elif token in {"{", "["} and lo in self.groups:
            for start, end in self.split(lo + 1, self.groups[lo]):
                if token == "{":
                    colon = next((i for i in self.level(start, end) if self.t[i] in {":", "="}), end)
                    if colon < end and self.t[colon] == ":":
                        start = colon + 1
                yield from self.binding_pattern(start, end)

    def declarations(self, span):
        for lo, hi in self.split(*span):
            equal = next((i for i in self.level(lo, hi) if self.t[i] == "="), hi)
            names = tuple(self.binding_pattern(lo, equal))
            yield names, (min(equal + 1, hi), hi), lo < equal and JS_NAME.fullmatch(self.t[lo])

    def locals(self, nodes):
        names = {}
        for node in nodes:
            if node.kind in {"let", "const"}:
                for keys, _, _ in self.declarations(node.span):
                    names.update(dict.fromkeys(keys, JSAtom.TDZ))
            elif node.kind == "function-decl":
                lo, hi = node.span
                i = lo + (2 if self.t[lo + 1:lo + 2] == ["*"] else 1)
                if i < hi and JS_NAME.fullmatch(self.t[i]):
                    names[self.t[i]] = JS_UNKNOWN if self.t[lo] == "function" else JSAtom.TDZ
        return names

    def hoisted(self, nodes):
        for node in nodes:
            if node.kind == "var":
                for names, _, _ in self.declarations(node.span):
                    yield from names
            elif node.kind == "for":
                lo, hi = node.span
                if self.t[lo:lo + 1] == ["var"]:
                    stop = next((i for i in self.level(lo + 1, hi) if self.t[i] in {";", "in", "of"}), hi)
                    for names, _, _ in self.declarations((lo + 1, stop)):
                        yield from names
            yield from self.hoisted(node.children)

    @staticmethod
    def lookup(env, name):
        return next((frame.bindings for frame in reversed(env) if name in frame.bindings), None)

    def value(self, env, name):
        scope = self.lookup(env, name)
        return scope[name] if scope is not None else JS_UNKNOWN

    def unwrap(self, lo, hi):
        while self.t[lo:lo + 1] == ["("] and self.groups.get(lo) == hi - 1:
            lo, hi = lo + 1, hi - 1
        return lo, hi

    def literal(self, lo, hi, env):
        lo, hi = self.unwrap(lo, hi)
        t = self.t[lo:hi]
        if len(t) == 1:
            token = t[0]
            if token in self.literals:
                # 对路径不解码转义，对真值只有空字面串是假。
                return ("str", self.literals[token])
            if token in {"false", "true"}:
                return ("bool", token == "true")
            if token == "null" or token == "undefined" and self.lookup(env, token) is None:
                return (token, None)
        if len(t) == 1 or len(t) == 2 and t[0] in {"-", "+"}:
            number = "".join(t).replace("_", "")
            if JS_NUMBER.fullmatch(number.lstrip("+-")):
                try:
                    value = int(number, 0) if number.lower().lstrip("+-").startswith(("0x", "0b", "0o")) else float(number)
                except ValueError:
                    return None
                return ("num", value)
        return None

    def truth(self, lo, hi, env):
        literal = self.literal(lo, hi, env)
        return bool(literal[1]) if literal is not None else None

    def function(self, body, end, params, env, name=None):
        nodes = self.sequence(body + 1, end)
        bindings = dict.fromkeys(self.hoisted(nodes), JS_UNKNOWN)
        bindings.update(dict.fromkeys(params, JS_UNKNOWN))
        if name:
            bindings[name] = JS_UNKNOWN
        self.block(nodes, (*js_join(env), JSScope(True, bindings)))

    def parameters(self, lo, hi):
        return (name for start, end in self.split(lo, hi) for name in self.binding_pattern(start, end))

    def after_params(self, close, hi):
        body = close + 1
        if self.t[body:body + 1] == [":"]:  # TS 返回类型
            body += 1
            while body < hi and (JS_NAME.fullmatch(self.t[body]) or self.t[body] in {"[", "]", ".", "<", ">", "|"}):
                body += 1
        return body

    def conditional(self, lo, hi):
        question = None
        depth = 0
        for i in self.level(lo, hi):
            if self.t[i] == "?":
                question = i if question is None else question
                depth += 1
            elif self.t[i] == ":" and depth:
                depth -= 1
                if not depth:
                    return question, i
        return None

    def expr(self, lo, hi, env):
        lo, hi = self.unwrap(lo, hi)
        if lo >= hi:
            return JS_UNKNOWN
        t = self.t
        first = t[lo]
        parts = list(self.split(lo, hi))
        if len(parts) > 1:
            for start, end in parts:
                value = self.expr(start, end, env)
            return value
        if JS_NAME.fullmatch(first) and lo + 1 < hi:
            op = t[lo + 1]
            if op == "=" or JS_MUTATION.fullmatch(op):
                scope = self.lookup(env, first)
                value = self.expr(lo + 2, hi, env) if op != "++" and op != "--" else JS_UNKNOWN
                if scope is not None and scope[first] is not JSAtom.TDZ:
                    scope[first] = value if op == "=" else JS_UNKNOWN
                    return scope[first]
                return JS_UNKNOWN
        if first in {"++", "--"} and hi == lo + 2:
            scope = self.lookup(env, t[lo + 1])
            if scope is not None and scope[t[lo + 1]] is not JSAtom.TDZ:
                scope[t[lo + 1]] = JS_UNKNOWN
            return JS_UNKNOWN

        # 箭头体有自己的函数帧，形参不从外部调用表达式推值。
        arrow_start = lo + (first == "async" and t[lo + 1:lo + 2] != ["=>"])
        arrow_end = self.groups.get(arrow_start, arrow_start)
        arrow = self.after_params(arrow_end, hi) if t[arrow_start:arrow_start + 1] == ["("] else arrow_end + 1
        if arrow < hi and t[arrow] == "=>":
            params = self.parameters(arrow_start + 1, arrow_end) if t[arrow_start] == "(" else (t[arrow_start],)
            body = arrow + 1
            if t[body:body + 1] == ["{"] and body in self.groups:
                self.function(body, self.groups[body], params, env)
            else:
                self.expr(body, hi, (*js_join(env), JSScope(True, dict.fromkeys(params, JS_UNKNOWN))))
            return JS_UNKNOWN

        if conditional := self.conditional(lo, hi):
            question, colon = conditional
            self.expr(lo, question, env)
            truth = self.truth(lo, question, env)
            if truth is not None:
                return self.expr(question + 1, colon, env) if truth else self.expr(colon + 1, hi, env)
            left, right = js_join(env), js_join(env)
            a, b = self.expr(question + 1, colon, left), self.expr(colon + 1, hi, right)
            for original, merged in zip(env, js_join(left, right)):
                original.bindings.update(merged.bindings)
            return js_join_values((a, b))
        for op in ("||", "&&", "??"):
            points = list(self.split(lo, hi, op))
            if len(points) > 1:
                start, end = points[0]
                left = self.expr(start, end, env)
                if op == "??":
                    literal = self.literal(start, end, env)
                    skip = None if literal is None else literal[0] not in {"null", "undefined"}
                else:
                    truth = self.truth(start, end, env)
                    skip = None if truth is None else truth == (op == "||")
                if skip is True:
                    return left
                if skip is False:
                    return self.expr(end + 1, hi, env)
                right = js_join(env)
                self.expr(end + 1, hi, right)
                for original, merged in zip(env, js_join(env, right)):
                    original.bindings.update(merged.bindings)
                return JS_UNKNOWN

        if hi == lo + 1:
            value = self.value(env, first)
            return JS_UNKNOWN if value is JSAtom.TDZ else value
        if (first == "require" and hi == lo + 4 and t[lo + 1] == "(" and t[lo + 3] == ")"
                and self.lookup(env, first) is None):
            module = self.literals.get(t[lo + 2], "").removeprefix("node:")
            return {"fs": JSAtom.FS, "path": JSAtom.PATH}.get(module, JS_UNKNOWN)
        if (t[lo + 1:lo + 5] in ([".", "join", "(", "__dirname"], [".", "resolve", "(", "__dirname"])
                and self.groups.get(lo + 3) == hi - 1 and self.value(env, first) is JSAtom.PATH
                and self.lookup(env, "__dirname") is None and t[lo + 5:lo + 6] == [","]):
            spans = list(self.split(lo + 6, hi - 1))
            if spans[-1][0] == spans[-1][1]:
                spans.pop()
            parts = [self.literals.get(t[a]) if b == a + 1 else None for a, b in spans]
            if parts and all(part is not None and not part.startswith("/") for part in parts):
                return frozenset({"/".join(part for part in parts if part)})

        i = lo
        while i < hi:
            token = t[i]
            previous = t[i - 1] if i > lo else ""
            # 只认真实名称绑定上的读，不把 obj.fs.readFileSync 当成内建 fs。
            if (previous not in {".", "?."} and self.value(env, token) is JSAtom.FS
                    and t[i + 1:i + 4] == [".", "readFileSync", "("] and i + 3 in self.groups):
                close = self.groups[i + 3]
                for j, (a, b) in enumerate(self.split(i + 4, close)):
                    value = self.expr(a, b, env)
                    if j == 0 and isinstance(value, frozenset):
                        self.reads.update(value)
                i = close + 1
                continue
            if token == "class" and previous not in {".", "?."}:
                name = t[i + 1] if t[i + 1:i + 2] and JS_NAME.fullmatch(t[i + 1]) and t[i + 1] != "extends" else None
                body = next((j for j in self.level(i + 1, hi) if t[j] == "{"), None)
                if body is not None and body in self.groups:
                    local = (*js_join(env), JSScope(False, {name: JS_UNKNOWN} if name else {}))
                    self.expr(body + 1, self.groups[body], local)
                    i = self.groups[body] + 1
                    continue
            if token in {"(", "[", "{"} and i in self.groups:
                close = self.groups[i]
                body = self.after_params(close, hi)
                # 普通函数、对象/类方法的参数括号紧接其函数体。
                if (token == "(" and previous not in JS_CONTROL and body < hi and t[body] == "{"
                        and body in self.groups and i > lo and (JS_NAME.fullmatch(previous) or previous in {"*", "]"})):
                    name = previous if t[max(lo, i - 3):i].count("function") and previous != "function" else None
                    self.function(body, self.groups[body], self.parameters(i + 1, close), env, name)
                    i = self.groups[body] + 1
                    continue
                if token == "{":
                    for a, b in self.split(i + 1, close):
                        # 对象属性值也可能是箭头函数；方法的参数不是属性键。
                        colon = next((j for j in self.level(a, b) if t[j] in {":", "(", "=", "?"}), b)
                        self.expr(colon + 1 if colon < b and t[colon] == ":" else a, b, env)
                else:
                    self.expr(i + 1, close, env)
                i = close
            i += 1
        return JS_UNKNOWN

    def block(self, nodes, env, params=()):
        local = dict.fromkeys(params, JS_UNKNOWN) | self.locals(nodes)
        result = self.run(nodes, (*env, JSScope(False, local)))
        return {exit: state[:-1] for exit, state in result.items()}

    def run(self, nodes, env):
        flow = {"next": env}
        for node in nodes:
            if "next" not in flow:
                break
            js_merge(flow, self.execute(node, flow.pop("next")))
        return flow

    def declare(self, kind, span, env):
        scope = next(frame.bindings for frame in reversed(env) if frame.function) if kind == "var" else env[-1].bindings
        for names, (lo, hi), simple in self.declarations(span):
            if kind != "var" or lo < hi:
                value = self.expr(lo, hi, env)
                for name in names:
                    scope[name] = value if simple else JS_UNKNOWN

    def execute(self, node, env):
        kind, (lo, hi), children = node
        if kind == "block":
            return self.block(children, env)
        if kind in {"var", "const", "let"}:
            self.declare(kind, (lo, hi), env)
        elif kind == "if":
            self.expr(lo, hi, env)
            choice = self.truth(lo, hi, env)
            other = children[1] if len(children) == 2 else JSStatement("empty", (hi, hi))
            if choice is not None:
                return self.execute(children[0] if choice else other, env)
            result = self.execute(children[0], js_join(env))
            js_merge(result, self.execute(other, js_join(env)))
            return result
        elif kind == "switch":
            return self.switch(children, (lo, hi), env)
        elif kind == "try":
            return self.try_block(children, env)
        elif kind in {"while", "for"}:
            return self.loop(node, env)
        elif kind in {"return", "throw", "break", "continue"}:
            if kind in {"return", "throw"}:
                self.expr(lo, hi, env)
            return {kind: env}
        elif kind in {"expr", "function-decl"}:
            self.expr(lo, hi, env)
            if kind == "function-decl" and self.t[lo] == "class" and lo + 1 < hi:
                env[-1].bindings[self.t[lo + 1]] = JS_UNKNOWN
        return {"next": env}

    def switch(self, cases, span, env):
        self.expr(*span, env)
        literal = self.literal(*span, env)
        values = [self.literal(*case.span, env) if case.kind == "case" else None for case in cases]
        default = next((i for i, case in enumerate(cases) if case.kind == "default"), None)
        known = literal is not None and all(value is not None or i == default for i, value in enumerate(values))
        entry = next((i for i, value in enumerate(values) if value == literal), default) if known else None
        locals_ = self.locals(stmt for case in cases for stmt in case.children)
        inside = (*env, JSScope(False, locals_))
        exits, flow = {}, {}
        if (known and entry is None) or (not known and default is None):
            exits["next"] = js_join(inside)
        for i, case in enumerate(cases):
            if not known and case.kind == "case":
                self.expr(*case.span, js_join(inside))
            if not known or i == entry:
                js_merge(flow, {"next": js_join(inside)})
            if "next" in flow:
                branch = self.run(case.children, flow.pop("next"))
                if "break" in branch:
                    js_merge(exits, {"next": branch.pop("break")})
                if "next" in branch:
                    flow["next"] = branch.pop("next")
                js_merge(exits, branch)
        js_merge(exits, flow)
        return {exit: state[:-1] for exit, state in exits.items()}

    def try_block(self, handlers, env):
        result = self.execute(handlers[0], js_join(env))
        for handler in handlers[1:]:
            if handler.kind == "catch":
                # Opaque calls may throw; explicit throw also propagates preceding writes to catch.
                thrown = result.pop("throw", None)
                catch_env = js_join(env, thrown) if thrown is not None else js_join(env)
                js_merge(result, self.block(handler.children, catch_env, self.parameters(*handler.span)))
            else:
                final = {}
                for completion, state in result.items():
                    applied = self.block(handler.children, state)
                    if "next" in applied:
                        js_merge(final, {completion: applied.pop("next")})
                    js_merge(final, applied)
                result = final
        return result

    def loop(self, node, env):
        lo, hi = node.span
        condition, step, scoped = (lo, hi), (hi, hi), False
        iteration = None
        if node.kind == "for":
            parts = list(self.split(lo, hi, ";"))
            if len(parts) == 3:
                init, condition, step = parts
            else:
                separator = next((i for i in self.level(lo, hi) if self.t[i] in {"in", "of"}), hi)
                init, condition, iteration = (lo, separator), None, (min(separator + 1, hi), hi)
            kind = self.t[lo] if lo < init[1] else ""
            if kind in {"let", "const"}:
                names = (name for keys, _, _ in self.declarations((lo + 1, init[1])) for name in keys)
                env = (*env, JSScope(False, dict.fromkeys(names, JSAtom.TDZ)))
                scoped = True
            if kind in {"let", "const", "var"}:
                self.declare(kind, (lo + 1, init[1]), env)
            else:
                self.expr(*init, env)
            if iteration is not None:
                self.expr(*iteration, env)
        pre = current = js_join(env)
        exits = {}
        while True:
            head = js_join(current)
            if condition is None:
                truth = None
            elif condition[0] == condition[1]:
                truth = True
            else:
                self.expr(*condition, head)
                truth = self.truth(*condition, head)
            if truth is not True:
                js_merge(exits, {"next": js_join(head)})
            if truth is False:
                break
            branch = self.execute(node.children[0], head)
            if "break" in branch:
                js_merge(exits, {"next": branch.pop("break")})
            back = [branch.pop(kind) for kind in ("next", "continue") if kind in branch]
            js_merge(exits, branch)
            if not back:
                break
            tail = js_join(*back)
            self.expr(*step, tail)
            upcoming = js_join(pre, current, tail)
            if upcoming == current:
                break
            current = upcoming
        return {exit: state[:-1] for exit, state in exits.items()} if scoped else exits

    def extract(self):
        nodes = self.sequence(0, len(self.t))
        self.block(nodes, (JSScope(True, dict.fromkeys(self.hoisted(nodes), JS_UNKNOWN)),))
        return self.reads


def js_relative_reads(tokens, literals, linebreaks):
    try:
        return JSFixtureReads(tokens, literals, linebreaks).extract()
    except RecursionError:
        # 深到无法分析的源码不提供证据；不保留中途观察到的路径。
        return ()

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


def report_preamble(content):
    """保留 Markdown 段落结构；围栏内部的示例不提供前导证据。"""
    lines = []
    fence = None
    for raw in content.split("\n", 40)[:40]:
        line = MD_QUOTE.sub("", raw.strip())
        if marker := re.match(r"`{3,}|~{3,}", line):
            if fence is None:
                fence = marker[0]
            elif marker[0].startswith(fence) and not line[marker.end():].strip():
                fence = None
            lines.append("")
        elif fence is None:
            lines.append(line.replace("**", ""))
    return lines


def report_title(label):
    # 有身份的主标题优先；副标题提到“设计文档”不会改变“实装审计”的身份。
    # 括注里的“诊断”或“设计”常只是主题限定，不参与主标题的角色裁定。
    main = re.sub(r"（[^（）]*）|\([^()]*\)", "", label)
    lead = re.split(r"：|:\s|——| [—–] ", main, maxsplit=1)[0]

    def role(title):
        marks = [(m.start(), is_report) for pattern, is_report in ((REPORT_TITLE, True), (RULE_TITLE, False))
                 for m in pattern.finditer(title)]
        return max(marks)[1] if marks else None

    primary = role(lead)
    if primary is not None:
        return primary
    secondary = role(main)
    return bool(role(label) if secondary is None else secondary)


def report_table(lines):
    def cells(line):
        return [cell.strip() for cell in line.strip("|").split("|")] if "|" in line else []

    for i, line in enumerate(lines[:-2]):
        header, rule = cells(line), cells(lines[i + 1])
        if len(header) != len(rule) or not rule or not all(map(TABLE_RULE.fullmatch, rule)):
            continue
        columns = [j for j, name in enumerate(header)
                   if OUTCOME_KEY.fullmatch(name) or name in {"状态", "实测", "认识论等级"}]
        metrics = [j for j, name in enumerate(header) if RUN_COLUMN.search(name)]
        for row in lines[i + 2:]:
            data = cells(row)
            if len(data) != len(header):
                break
            if len(header) == 2 and header[0] in {"字段", "项", "Field", "Key"} and EXECUTION_KEY.fullmatch(data[0]):
                return True
            if (any(DISPOSITION.search(data[j]) or MEASUREMENT.search(data[j]) for j in columns)
                    or sum(bool(re.search(r"\d", data[j])) for j in metrics) >= 2
                    or sum(bool(re.match(r"[✓✗✅❌]", cell)) for cell in data) >= 2):
                return True
    return False


def is_report_artifact(raw, text):
    content = text.lstrip("\ufeff \t\r\n")
    if content.startswith("{"):
        try:
            obj = strict_json(raw.removeprefix(b"\xef\xbb\xbf"), "PREGATE_REVIEW", "verification_basis")
        except ValueError:
            return False  # 普通源码片段无需是 JSON。
        return isinstance(obj, dict) and is_json_artifact(obj)
    if any(pattern.match(content) for pattern in (SUMMARY_HEADER, TB_RUN_HEADER, TB_REVIEW_HEADER)):
        return True
    lines = report_preamble(content)
    if not lines:
        return False
    # 报告前置修订说明可能是引用段；以下取第一个实际标题，而非首物理行。
    title_index = next((i for i, line in enumerate(lines) if MD_HEADING.fullmatch(line)), None)
    title = MD_HEADING.fullmatch(lines[title_index]) if title_index is not None else None
    if title and ADR_TITLE.match(title[1]):
        return False
    first_field = REPORT_FIELD.fullmatch(title[1]) if title else None
    title_is_field = first_field and (OUTCOME_KEY.fullmatch(first_field["key"])
                                     or EXECUTION_KEY.fullmatch(first_field["key"]))
    metadata = "\n".join(lines)
    declaration = re.compile(r"^状态\s*[:：]\s*(?:设计(?:稿|草案)|规范草案|预注册)(?=$|[\s（(。])")
    declared = bool(title and not title_is_field and report_title(title[1])
                    and not any(declaration.match(MD_LIST.sub("", line)) for line in lines[:12]))
    bound = RECEIPT_COMMIT.search(metadata) is not None
    if bound and (RECEIPT_VERDICT.search(metadata) or (RUN_EXIT_CODE.search(metadata) and RUN_RESULT.search(metadata))):
        return True

    execution = bound
    outcome = False
    in_outcome_section = False
    body = [line for i, line in enumerate(lines) if i != title_index or title_is_field]
    for line in body:
        heading = MD_HEADING.fullmatch(line)
        label = MD_LIST.sub("", heading[1] if heading else line)
        label = re.sub(r"^(?:第?[一二三四五六七八九十]+[、.]|\d+[、.])\s*", "", label)
        fields = () if label.startswith("|") else label.split(" | ")
        for segment in fields:
            field = REPORT_FIELD.fullmatch(segment.strip())
            if field is None:
                continue
            key, value = field["key"], field["value"]
            key = re.split(r"[（(]", key, maxsplit=1)[0].strip()
            execution |= bool(EXECUTION_KEY.fullmatch(key) or REPORT_SUBJECT.search(value))
            if OUTCOME_KEY.fullmatch(key):
                outcome |= bool(DISPOSITION.search(value) or MEASUREMENT.search(value) or RUN_METRIC.search(value))
        if heading:
            name = re.split(r"[（(：:]", label, maxsplit=1)[0].strip()
            in_outcome_section = bool(OUTCOME_KEY.fullmatch(name))
            execution |= bool(EXECUTION_KEY.fullmatch(name) or REPORT_SUBJECT.search(label))
        else:
            # 小节正文可能先写实测再给表，或把多行结论排在同一个引用段。
            if in_outcome_section:
                outcome |= bool(DISPOSITION.search(line) or MEASUREMENT.search(line) or RUN_METRIC.search(line))
            execution |= bool(declared and (REPORT_SUBJECT.search(line) or MEASUREMENT.search(line)
                                            or re.search(r"本次.{0,24}(?:实跑|实测|执行)|生成：\d{4}-\d{2}-\d{2}", line)))
    return (declared and (execution or outcome or report_table(body))) or (bound and outcome)


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
