"""ADR 0064 r6 的 R10 Git 对象与补救原件本地核验。"""
from __future__ import annotations

from collections import defaultdict
from functools import cache
from itertools import groupby
from pathlib import Path, PurePosixPath
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
FIXTURE_POINTER = "FIXTURE-MOVED.md"
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
RUN_TABLE_RULE = re.compile(r":?-+:?")
RUN_METRIC = re.compile(r"\d[\d,]*(?:[.]\d+)?\s*(?:%|pp\b|ms\b|bars?\b|笔|组|例)|"
                        r"(?:[^\s=:]+)\s*=\s*-?\d", re.I)
RUN_COLUMN = re.compile(r"回报|收益|覆盖率|复利|胜率|耗时|交易数|实测|bars|sharpe|drawdown|ms/bar|trades|MDD|BH|P&L|年化|回测|bps|卖飞率", re.I)

RUN_TITLE = re.compile(r"探针|标定记录|首验|重验|重测|重跑|首跑|复跑|复验|回测|实测|实证|对拍|验收|修复|测量|实验|结果")
NORMATIVE_TITLE = re.compile(
    RULE_TITLE.pattern + r"|规划|路线图|蓝图|总纲领|现场台账|交接台账|草案|\b(?:proposal|plan|spec|draft|roadmap)\b", re.I
)
RUN_EXECUTION = re.compile(
    r"\b(?:cargo test|pytest)[ \t`]+\d+|"
    r"\d+/\d+\s*(?:标的|通过|PASS\b|FAIL\b)|"
    r"回测重跑|终态对照|全标的重验|md5\s*验证|\d[\d,.]*[kKmM]?\s*bars?\b|"
    r"(?:回测|运行|总)耗时[：:\s]+[~≈]?\d|"
    r"汇总(?:本次|本轮|本 session)[^\n]{0,24}实验报告|"
    r"(?:测试|运行)[^\n]{0,12}(?:全过|全绿)|真实数据回测|"
    r"\d+/\d+\s*(?:[a-z]+\s*)?(?:测试通过|标的)|"
    r"(?:真实数据|实跑|复跑|重跑|首跑|重测|实测).{0,10}(?:已完成|已合并|结果|交叉验证)|"
    r"(?:数据|守卫)对账[^\n]{0,20}(?:全|均)\s*PASS", re.I
)
BEFORE_AFTER = re.compile(r"修复前\s*(?:→|->|vs\.?|/|\|)\s*修复后", re.I)
RUN_DECISION_TABLE = re.compile(r"(?:全标的|多标的|实测)(?:判决|对照)表")
RUN_DATA_COLUMN = re.compile(
    RUN_COLUMN.pattern + r"|bars? 数|\b(?:BH|P\d+|基线)%|p\d+\b|净现金|盈亏|延迟|滞后|"
    r"样本数|涨幅|跌破价|顶价|回撤|bar 数|\b(?:precision|recall|counters|bsp|div|trades|corr|nf|gap|settle|avg_span)\b|"
    r"计数|匹配率|通过率", re.I
)
RUN_OBSERVATION = re.compile(r"(?:Buy[- ]and[- ]hold|回测耗时|运行耗时)\s*[:：]\s*[+−~-]?\d", re.I)
RUN_SOURCE = re.compile(r"\b\w+_results\.json\b|(?:脚本|驱动|数据源|采样|落盘)\s*[:：]|"
                        r"(?:产出|输出|结果)[:： ]+`[^\n`]+\.json`|生成时间[:：]\s*\d{4}-\d{2}-\d{2}")
RUN_SAMPLE = re.compile(r"(?:\d+\s*(?:标的|个样本|个交易日|根)|样本[：:]|本次新拉|真实数据|官方盘|\bn\s*=\s*\d+|yfinance.{0,14}日线)")
RUN_RECORDED = re.compile(r"(?:实测裁决|数据对账|跨标的汇总|真实读数|已逐根验证|"
                          r"(?:本次|三标的|全标的)(?:重跑|复跑|重验)|"
                          r"\b(?:hold|MDD)(?:\s+|\s*[:：]\s*)[+−-]?\d|"
                          r"(?:几个|\d+\s*个?|[一二三四五六七八九]个)关键数字)", re.I)
RUN_VALUE = re.compile(r"(?<![\w/])[+−-]?\d[\d,.]*(?![\w/])")
RUN_SUMMARY_HEADING = re.compile(
    r"^#{1,6} [^\n]{0,46}(?:session(?:全局|核心|全局核心)?(?:成果(?:总览|清单|链)|终局)|决定性结果|下游重验)",
    re.I | re.M,
)
RUN_SUMMARY_VALUE = re.compile(
    r"[+−-]\d+(?:[.]\d+)?\s*(?:%|pp(?![a-z]))|"
    r"\d+(?:[.]\d+)?\s*→\s*\d+(?:[.]\d+)?\s*(?:%|s\b)"
)
NUMERIC_CHANGE = re.compile(r"\d[^|\n]{0,65}(?:→|->)\s*[+-]?\d")
RUN_RESULT_COUNT = re.compile(
    r"\b(?:cargo test|pytest)[ \t`]+\d+[^\n]{0,30}(?:全过|通过|PASS\b|FAIL\b)|"
    r"\d+/\d+\s*(?:标的\s*)?(?:通过|PASS\b|FAIL\b)", re.I
)
GENERATED_AT = re.compile(r"(?:生成(?:时间)?|Generated(?: at)?)\s*[:：]\s*\d{4}-\d{2}-\d{2}", re.I)
EMPIRICAL_CONTEXT = re.compile(
    r"(?:数据|本体)实测|两版真实数据|"
    r"(?:样本|数据|数据范围)[:：][^\n]{0,120}\d[^\n]{0,50}(?:根|bars?\b|行|笔|交易日)|"
    r"(?:样本|raw)[^\n]{0,16}\d[\d,]+\s*(?:行|笔|交易日)|"
    r"\d[\d,.]*[万亿kKmM]?\s*(?:共同交易日|公共交易日|交易日|根(?:\s*\d+min)?|bars?\b)|"
    r"\d{4}-\d{2}-\d{2}[^\n]{0,45}(?:~|至|\.\.)[^\n]{0,20}\d{4}-\d{2}-\d{2}", re.I
)
OBSERVED_FINDING = re.compile(
    r"证伪|否证|唯一合格|有效涌现深度|\d+\s*组共享|"
    r"\d[\d,]+\s*(?:行|笔|例|次|根)|重复率[^\n]{0,20}\d+\.?\d*%|"
    r"(?:回测|实测|实跑|首验|重验|对拍|实验)(?:\s*结果|\s*读数)"
)
RUN_CELL = re.compile(r"^[*~≈ +−-]*\d[\d,.]*(?:%|s|ms|pp|x|倍|\s|$)", re.I)
PERFORMANCE_COLUMN = re.compile(r"\b(?:BH|MDD|Sharpe|trades)\b|复利|夏普|盈亏比|胜率|净现金|耗时|收益|回撤|\bstrat(?:%|_pct)?\b|P&L|PnL|(?:多头|空头)净", re.I)
RUN_DELIVERY = re.compile(r"实施(?:侧)?交付|本次交付|交付(?:小结|文档|记录)")
RUN_EMPIRICAL_GRADE = re.compile(r"认识论(?:等级)?[^\n]{0,8}L[23]\b|\bepistemic levels?[^\n]{0,60}L[23]\b", re.I)
RUN_EXECUTED = re.compile(r"实测复现|观察到的规律|本轮做的|已经查清|已确定性.{0,4}查清|"
                          r"跑(?:了|出|过|完|决定性)[^\n]{0,25}(?:实证|回测|实验|测试)|"
                          r"\b(?:numbers? (?:were )?re-verified|observed results|experiment results)\b", re.I)
RUN_RESULT_SECTION = re.compile(
    r"(?:回测|实测|首验|实验|实证)(?:结果|复现|读数|证伪|否证)|观察到的规律|结果[:：].{0,60}(?:证伪|否证)"
)
RUN_STATISTIC = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|pp\b)|[+−-]\d[\d,]*(?:\.\d+)?")
EXECUTION_RECORD = re.compile(r"(?:编译|构建|测试)[^\n]{0,45}(?:矛盾|失败|异常|报错)记录|"
                              r"编译器暴露[^\n]{0,20}记录")
RUN_DIGEST = re.compile(r"(?:session|本轮).{0,20}(?:关键发现链|实验结论|实测摘要)|"
                        r"产生机制追查|工作清单.{0,20}已核实", re.I)

DELIVERED = re.compile(r"(?:代码|改动|测试|修复).{0,12}(?:已落|已合入|已完成|全过|全通)|"
                       r"(?:新增|修改)文件[：:]|(?:离线|合成|回归|单元)测试[^\n]{0,40}\d+\s*(?:项|通过)")
SELF_REPORT = re.compile(r"(?:^|[（(，。；;：:\s])本报告(?:的|所|中|为|记载|记录|只产出|不再|\s|[，。])", re.M)



class Entry(NamedTuple):
    mode: str
    kind: str
    blob: str


class ArchivedArtifacts(NamedTuple):
    blobs: set[str]
    migrated_inputs: set[tuple[str, str]]


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


def fixture_pointer_locations(path):
    """包根以下、旧路径的祖先目录；同时给出相对于指针所在目录的旧路径。"""
    archive = REVIEW_TREE.search(path)
    if archive is None:
        return
    end = path.find("/", archive.end())
    while end != -1:
        yield path[:end] + "/" + FIXTURE_POINTER, path[end + 1:]
        end = path.find("/", end + 1)


def fixture_pointer_paths(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        return set()
    if "\0" in text or is_report_artifact(raw, text):
        return set()
    # 按完整 Markdown 行内代码或独立词元取路径，绝不靠子串匹配。
    tokens = re.compile(r"""`+([^`]+)`+|[^\s`，。；：！、（）「」【】<>()\[\]{}"'，;,:*]+""")
    return {match[1] or match[0] for line in report_preamble(text.lstrip("\ufeff"), limit=text.count("\n") + 1, strip_bold=False)
            for match in tokens.finditer(line)}


def atomic_fixture_migrations(records, final_tree, candidates, *, cwd):
    """从同一份 raw log 取 D+A 与迁移时的指针版本；F 工作树不参与。"""
    pointers = {
        path.encode(): entry.blob for path, entry in final_tree.items()
        if path.endswith("/" + FIXTURE_POINTER) and REVIEW_TREE.search(path)
        and entry.kind == "blob" and entry.mode in REGULAR_MODES
    }
    if not candidates or not pointers:
        return set()

    @cache
    def tokens(blob):
        return fixture_pointer_paths(git("cat-file", "blob", blob, cwd=cwd))

    current_pointers = {}
    migrated = set()
    for commit, changes in groupby(records, key=lambda record: record[0]):
        removed = defaultdict(list)
        added = []
        for _, path, old_mode, mode, old_blob, blob, status in changes:
            if path in pointers:
                if mode in REGULAR_RAW_MODES:
                    current_pointers[path] = blob.decode()
                else:
                    current_pointers.pop(path, None)
            if status == b"D" and old_mode in REGULAR_RAW_MODES and old_blob in candidates:
                first, old_paths = candidates[old_blob]
                if commit != first and path in old_paths:
                    removed[old_blob].append(path.decode("utf-8"))
            if (status == b"A" and mode in REGULAR_RAW_MODES and blob in candidates
                    and (entry := final_tree.get(path.decode("utf-8", errors="surrogateescape")))
                    and entry.mode in REGULAR_MODES and entry.blob.encode() == blob):
                target = path.decode("utf-8")
                if target != REMEDIATION and not (REVIEW_TREE.search(target) or is_result_archive_path(target)):
                    added.append((target, blob))
        for target, blob in added:
            for path in removed.get(blob, ()):
                locations = list(fixture_pointer_locations(path))
                for pointer, relative_old in locations:
                    key = pointer.encode()
                    if key not in current_pointers:
                        continue
                    # 深一层的指针可以用所在目录或包根作为源路径锚点。
                    old_tokens = {relative_old, locations[0][1]}
                    at_migration = tokens(current_pointers[key])
                    at_final = tokens(pointers[key])
                    if (target in at_migration and target in at_final
                            and old_tokens & at_migration and old_tokens & at_final):
                        migrated.add((target, blob.decode()))
    return migrated


def archive_artifact_blobs(final_tree, head, *, cwd):
    """按 F 的首父历史区分原件、冻结副本和有明确指针的原子迁移。"""
    # 根快照提供首见记录，合并只与第一父比较；一次读出所有增、删、改、换类。
    raw = git("log", "--root", "--first-parent", "--diff-merges=first-parent",
              "--no-renames", "--no-abbrev", "--raw", "-z", "--format=%x00%H",
              "--diff-filter=ADMT", "--reverse", head, cwd=cwd)
    fields = raw.split(b"\0")
    fields.pop()
    del raw

    def records():
        records = iter(fields)
        for metadata in records:
            if not metadata:
                commit = next(records)
                continue
            path = next(records)
            old_mode, mode, old_blob, blob, status = metadata.split()
            yield commit, path, old_mode[1:], mode, old_blob, blob, status

    archive_paths = defaultdict(set)
    for path, entry in final_tree.items():
        if entry.kind == "blob" and entry.mode in REGULAR_MODES and is_artifact_archive_path(path):
            archive_paths[entry.blob.encode()].add(path)
    review_paths = defaultdict(set)
    manifests = set()
    # 先限定候选；不为从未在受禁归档出现的 blob 建历史索引。
    for _, path, _, mode, _, blob, _ in records():
        if mode not in REGULAR_RAW_MODES and mode != b"120000":
            continue
        text_path = path.decode("utf-8", errors="surrogateescape")
        review = REVIEW_TREE.search(text_path)
        # 归档根自身的清单从来不是某个包的输入声明。
        if review:
            review_paths[blob].add(text_path)
            if mode in REGULAR_RAW_MODES and text_path[review.end():].endswith("/" + INPUT_MANIFEST):
                manifests.add(text_path)
        if mode in REGULAR_RAW_MODES and is_artifact_archive_path(text_path):
            archive_paths[blob].add(text_path)
    archive_paths.pop(EMPTY_BLOB.encode(), None)
    if not archive_paths:
        return ArchivedArtifacts(set(), set())

    origins = {}
    # A/B 保持原有的普通文件首见口径；C 另核首见的全部 blob 路径（包括符号链接）。
    blob_origins = {}
    for commit, path, _, mode, _, blob, _ in records():
        if blob not in archive_paths:
            continue
        text_path = path.decode("utf-8", errors="surrogateescape")
        if mode in REGULAR_RAW_MODES or mode == b"120000":
            first, paths = blob_origins.setdefault(blob, (commit, []))
            if first == commit:
                paths.append(text_path)
        if mode in REGULAR_RAW_MODES:
            first, paths = origins.setdefault(blob, (commit, []))
            if first == commit:
                paths.append(text_path)

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
    candidates = {}
    final_blobs = {entry.blob for entry in final_tree.values() if entry.mode in REGULAR_MODES}
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
        # C1/C2：只考虑首见全在审查归档、无产物名且全部旧路径已经消失的 blob。
        first, appearances = blob_origins[raw_blob]
        all_paths = history | review_paths[raw_blob]
        if (blob in final_blobs and all(REVIEW_TREE.search(path) for path in appearances)
                and all(REVIEW_TREE.search(path) and path not in final_tree and not is_archive_output(path)
                        for path in all_paths)):
            candidates[raw_blob] = (first, {path.encode("utf-8", errors="surrogateescape") for path in all_paths})
    return ArchivedArtifacts(forbidden, atomic_fixture_migrations(records(), final_tree, candidates, cwd=cwd))


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


def report_preamble(content, limit=40, *, strip_bold=True):
    """保留 Markdown 段落结构；围栏内部的示例不提供前导证据。"""
    lines = []
    fence = None
    for raw in content.split("\n", limit)[:limit]:
        line = MD_QUOTE.sub("", raw.strip())
        if marker := re.match(r"`{3,}|~{3,}", line):
            if fence is None:
                fence = marker[0]
            elif marker[0].startswith(fence) and not line[marker.end():].strip():
                fence = None
            lines.append("")
        elif fence is None:
            lines.append(line.replace("**", "") if strip_bold else line)
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


def markdown_tables(lines, rule_pattern):
    def cells(line):
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))] if "|" in line else []

    for i, line in enumerate(lines[:-2]):
        header, rule = cells(line), cells(lines[i + 1])
        if len(header) != len(rule) or not rule or not all(map(rule_pattern.fullmatch, rule)):
            continue
        rows = []
        for row in lines[i + 2:]:
            data = cells(row)
            if len(data) != len(header):
                break
            rows.append(data)
        if rows:
            yield header, rows


def report_table(lines, *, measured=False):
    rule_pattern = RUN_TABLE_RULE if measured else TABLE_RULE
    metric_column = RUN_DATA_COLUMN if measured else RUN_COLUMN
    for header, rows in markdown_tables(lines, rule_pattern):
        columns = [j for j, name in enumerate(header)
                   if OUTCOME_KEY.fullmatch(name) or name in {"状态", "实测", "认识论等级"}]
        metrics = [j for j, name in enumerate(header) if metric_column.search(name)]
        numeric_rows = 0
        sampled_table = measured and (
            header[0] in {"标的", "日期", "指标", "项", "regime", "维度", "级别", "id"}
            or header[0] == "" and len(header) >= 3
        )
        for data in rows:
            if len(header) == 2 and header[0] in {"字段", "项", "Field", "Key"} and EXECUTION_KEY.fullmatch(data[0]):
                return True
            if (any(DISPOSITION.search(data[j]) or MEASUREMENT.search(data[j]) for j in columns)
                    or sum(bool(re.search(r"\d", data[j])) for j in metrics) >= 2
                    or sum(bool(re.match(r"[✓✗✅❌]", cell)) for cell in data) >= 2):
                return True
            if sampled_table and sum(bool(RUN_VALUE.search(cell)) for cell in data[1:]) >= 2:
                numeric_rows += 1
                if numeric_rows >= 2:
                    return True
    return False


def observed_table(lines, *, sampled, generated, reported_run):
    """用表头和实际数值分辨测量结果与定义、阈值或预期行为表。"""
    for header, rows in markdown_tables(lines, RUN_TABLE_RULE):
        labels = {name.casefold() for name in header}
        numeric = {name.casefold() for j, name in enumerate(header)
                   if any(RUN_CELL.match(row[j]) for row in rows)}
        bars = any(re.fullmatch(r"bars?(?:\s*数)?", label) for label in numeric)
        performance = sum(bool(PERFORMANCE_COLUMN.search(label)) for label in numeric)
        if (bars and performance) or (reported_run and performance >= 2):
            return True
        if sampled and {"笔", "线段", "中枢", "走势", "买卖点"} <= numeric:
            return True
        if sampled and {"唯一键数", "重复率"} <= numeric and (
            "判定" in labels or any(re.search(r"[✅❌]", cell) for row in rows for cell in row)
        ):
            return True
        if generated and sampled and len(numeric) >= 2:
            return True
    return False


def measured_report(title, content, *, draft):
    """无「报告」名分时，查是否记录已执行的结果，而非制定验证方法。"""
    if draft or title and NORMATIVE_TITLE.search(title):
        return False
    # YAML 的「来源 commit」等字段是文档溯源，不是正文宣称的本次执行。
    if content.startswith(("---\n", "---\r\n")):
        metadata = re.match(r"---\r?\n(?=[^\n]*:[^\n]*\n).*?\r?\n(?:---|\.\.\.)\r?\n", content, re.S)
        if metadata:
            content = content[metadata.end():]
    lines = report_preamble(content, limit=90)
    preamble = "\n".join(lines)
    table = report_table(lines, measured=True) or RUN_DECISION_TABLE.search(preamble)
    measured_change = BEFORE_AFTER.search(preamble) and NUMERIC_CHANGE.search(preamble)
    sampled = EMPIRICAL_CONTEXT.search(preamble)
    generated = GENERATED_AT.search("\n".join(lines[:12]))
    run_title = bool(title and RUN_TITLE.search(title))
    empirical_grade = RUN_EMPIRICAL_GRADE.search(preamble)
    if observed_table(lines, sampled=sampled, generated=generated,
                      reported_run=(run_title and sampled) or empirical_grade):
        return True
    if sampled and (table or OBSERVED_FINDING.search(preamble)) and (generated or run_title):
        return True
    if (title and re.search(r"(?:研究|调研)报告\s*$", title)
            and re.search(r"基于[^\n]{0,120}(?:研读|调研)|(?:调研|研究)日期\s*[:：]", preamble)
            and re.search(r"(?m)^#{2,6} [^\n]{0,45}(?:结论|评估|建议)", content)):
        return True
    if RUN_DELIVERY.search("\n".join(lines[:12])) and (DELIVERED.search(preamble) or RUN_EXECUTED.search(preamble)):
        return True
    if RUN_EXECUTED.search(preamble) and (sampled or empirical_grade) and (
        OBSERVED_FINDING.search(preamble) or len(RUN_STATISTIC.findall(preamble)) >= 2
    ):
        return True
    if title and EXECUTION_RECORD.search(title) and re.search(r"实际报错|实际失败|\bE[0-9]{4}\b", preamble):
        return True
    if title and RUN_DIGEST.search(title) and (
        len(RUN_STATISTIC.findall(preamble)) >= 3
        or len(re.findall(r"(?m)^\d+\. .*?[✅❌]", preamble)) >= 2
    ):
        return True
    # 有些实验先列设计及预注册，后列实际结果；只在明确的运行结果小节内取数值。
    if run_title or sampled or empirical_grade:
        all_lines = report_preamble(content, limit=content.count("\n") + 1)
        for index, line in enumerate(all_lines):
            if not (MD_HEADING.fullmatch(line) and RUN_RESULT_SECTION.search(line)):
                continue
            section = all_lines[index + 1:index + 55]
            section_text = "\n".join(section)
            if observed_table(section, sampled=True, generated=False, reported_run=True) or (
                (sampled or EMPIRICAL_CONTEXT.search(section_text))
                and len(RUN_STATISTIC.findall(section_text)) >= 2
            ):
                return True
            if empirical_grade and re.search(r"证伪|否证", line) and len(RUN_METRIC.findall(section_text)) >= 2:
                return True
    execution = (REPORT_SUBJECT.search(preamble) or RUN_EXECUTION.search(preamble)
                 or RUN_SOURCE.search(preamble) and RUN_SAMPLE.search(preamble))
    if execution and (table or measured_change or RUN_OBSERVATION.search(preamble) or RUN_RECORDED.search(preamble)):
        return True
    self_report = SELF_REPORT.search(preamble)
    explicit_result = re.search(r"^本报告(?:结论先行[:：]|只产出)|^本报告为 .{0,24}(?:诊断|结果|实测)", preamble, re.M)
    if (self_report and (RUN_RECORDED.search(preamble) or explicit_result and table)
            or explicit_result and re.search(r"^#{2,6} .{0,10}(?:结论|判决|结果)", preamble, re.M)):
        return True
    # 复盘摘要也可能用带单位的读数列项目，而不复印原报告的表。
    if RUN_SUMMARY_HEADING.search(preamble) and (table or len(RUN_SUMMARY_VALUE.findall(preamble)) >= 2):
        return True
    if not title or not RUN_TITLE.search(title):
        return False
    if (REPORT_SUBJECT.search(preamble) or RUN_RESULT_COUNT.search(preamble)
            or MEASUREMENT.search(preamble) or measured_change
            or RUN_RECORDED.search(preamble) and execution):
        return True
    # 探针、基准也可能先报采样口径，随后只用数字表给出读数。
    if RUN_SAMPLE.search(preamble) and table:
        return True
    result_heading = any(
        OUTCOME_KEY.fullmatch(re.sub(r"^\d+\.\s*", "", heading[1]).split("（", 1)[0])
        for line in lines if (heading := MD_HEADING.fullmatch(line))
    )
    return bool(result_heading and SELF_REPORT.search(content))


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
    draft = any(declaration.match(MD_LIST.sub("", line)) for line in lines[:12])
    declared = bool(title and not title_is_field and report_title(title[1]) and not draft)
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
    return ((declared and (execution or outcome or report_table(body))) or (bound and outcome)
            or measured_report(title[1] if title and not title_is_field else None, content, draft=draft))


def basis_key(item, final_tree, archived_artifacts, cache, fail, *, cwd):
    fail(isinstance(item, dict) and item.keys() == BASIS_KEYS, "invalid verification_basis keys")
    path, blob, start, end = (item[k] for k in ("path", "blob", "line_start", "line_end"))
    fail(valid_path(path), "invalid verification_basis path")
    fail(path != REMEDIATION and not is_artifact_archive_path(path), ARTIFACT_BASIS_ERROR)
    entry = final_tree.get(path)
    fail(entry is not None and entry.kind == "blob" and entry.mode in REGULAR_MODES
         and entry.blob == blob, "verification_basis must bind a regular F blob")
    fail(blob not in archived_artifacts.blobs or (path, blob) in archived_artifacts.migrated_inputs,
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
