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

REPORT_HEADING = re.compile(r"^#{1,6}[ \t]+[^\r\n]*(?:验收|复核|复验|评审|报告)")
REPORT_OUTCOME = re.compile(
    r"(?mi)^(?:[-*][ \t]+)?(?:\*\*)?(?:结果|结论|判定)[:：][ \t]*(?:\*\*)?"
    r"(?:PASS|FAIL|BLOCK|REJECT|CHANGES_REQUIRED)(?=$|[ \t*。，、；,;.!\r])"
)
REPORT_EXECUTION = re.compile(
    rf"(?:固定|受审|候选|冻结)提交[ \t：:]+`?{GIT_SHA}\b|(?:运行器)?进程退出(?:码)?[ \t：:]+[0-9]+\b"
)


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


def is_artifact_archive_path(path):
    if not path.startswith(REVIEW_ARCHIVE):
        return False
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
    relative = path.removeprefix(REVIEW_ARCHIVE)
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
JS_TOKENS = re.compile(
    r'(?P<single>\'(?:\\[^\r\n]|[^\'\\\r\n])*\')|`(?:\\[\s\S]|[^`\\])*`'
    r'|/(?![/*])(?:\\[^\r\n]|\[(?:\\.|[^\]\\\r\n])*\]|[^/\\[\r\n])+/[dgimsuvy]*|'
    + COMMON_TOKENS
)


def source_tokens(text, *, rust):
    """去掉注释，把字符串/模板/正则作为不可拆分的词元。"""
    scan = RUST_TOKENS if rust else JS_TOKENS
    literals, tokens = {}, []
    end = 0
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
        if match["string"] or (not rust and match["single"]):
            # 不解码转义：只承认可逐字对到仓库相对路径的字符串。
            key = f"@{len(literals)}"
            literals[key] = token[1:-1]
            tokens.append(key)
        else:
            tokens.append(token if re.fullmatch(r"[\w$]+|[.:=(),;!{}]", token) else "~")
    return " ".join(tokens), literals


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
    tokens, literals = source_tokens(text, rust=rust)
    if rust:
        for read in re.finditer(r"(?<!\S)include_(?:str|bytes) ! \( (@[0-9]+)(?: ,)? \)", tokens):
            yield literals[read[1]]
        return

    # Node CommonJS: 先核两个内建模块，再核 readFileSync 的直接实参或 const 路径绑定。
    modules = defaultdict(set)
    for binding in re.finditer(r"(?:^| )(?:const|,) ([\w$]+) = require \( (@[0-9]+) \)", tokens):
        modules[literals[binding[2]]].add(binding[1])
    for fs in modules["node:fs"] | modules["fs"]:
        for path in modules["node:path"] | modules["path"]:
            joined = rf"{re.escape(path)} \. join \( __dirname , (@[0-9]+)(?: ,)? \)"
            load = rf"(?<!\S)(?<!\. ){re.escape(fs)} \. readFileSync \( "
            for read in re.finditer(load + joined + r"(?= [,)])", tokens):
                yield literals[read[1]]
            variables = {m[1]: m[2] for m in re.finditer(rf"(?<!\S)const ([\w$]+) = {joined} ;", tokens)}
            for read in re.finditer(load + r"([\w$]+)(?= [,)])", tokens):
                if read[1] in variables:
                    yield literals[variables[read[1]]]


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
                or path.startswith(REVIEW_ARCHIVE) or entry.blob in forbidden):
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
    archive_paths = defaultdict(set)
    for path, entry in final_tree.items():
        if entry.kind == "blob" and entry.mode in REGULAR_MODES and is_artifact_archive_path(path):
            archive_paths[entry.blob.encode()].add(path)
    manifests = set()
    # 先限定候选；不为从未在受禁归档出现的 blob 建历史索引。
    marker = b"\0" + REVIEW_ARCHIVE.encode()
    end = 0
    while (start := raw.find(marker, end)) != -1:
        end = raw.index(b"\0", start + 1)
        path = raw[start + 1:end]
        metadata = raw[raw.rindex(b"\0", 0, start) + 1:start]
        _, mode, _, blob, _ = metadata.split()
        if mode in REGULAR_RAW_MODES:
            text_path = path.decode("utf-8", errors="surrogateescape")
            relative = text_path.removeprefix(REVIEW_ARCHIVE)
            if relative.endswith("/" + INPUT_MANIFEST):
                manifests.add(text_path)
            if is_artifact_archive_path(text_path):
                archive_paths[blob].add(text_path)
    archive_paths.pop(EMPTY_BLOB.encode(), None)
    if not archive_paths:
        return ArchivedArtifacts(set(), set())

    origins = {}
    records = iter(raw.split(b"\0")[:-1])
    for metadata in records:
        if not metadata:
            commit = next(records)
            continue
        path = next(records)
        _, mode, _, blob, _ = metadata.split()
        if blob in archive_paths and mode in REGULAR_RAW_MODES:
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
        if not valid_path(path) or path.startswith(REVIEW_ARCHIVE) or path == REMEDIATION:
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
        return (path.startswith(manifest_dirs) and not is_archive_output(path)
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
        if (all(path.startswith(REVIEW_ARCHIVE) for path in paths)
                and all(path not in final_tree and not is_archive_output(path) for path in history)):
            migrated.add(blob)
    candidates = {
        path: entry.blob for path, entry in final_tree.items()
        if entry.kind == "blob" and entry.mode in REGULAR_MODES and entry.blob in migrated
        and not path.startswith(REVIEW_ARCHIVE)
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
    preamble = "\n".join(content.split("\n", 12)[:12])
    metadata = re.split(r"(?m)^[ \t]*(?:```|~~~)", preamble, maxsplit=1)[0]
    if REPORT_HEADING.match(metadata) and REPORT_OUTCOME.search(metadata) and REPORT_EXECUTION.search(metadata):
        return True
    return bool(RECEIPT_COMMIT.search(metadata)
                and (RECEIPT_VERDICT.search(metadata)
                     or (RUN_EXIT_CODE.search(metadata) and RUN_RESULT.search(metadata))))


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
