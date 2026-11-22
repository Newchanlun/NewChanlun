"""ADR 0064 r6 的 Git 对象与补救原件本地核验。"""
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
ARCHIVE_SPEC_FILES = {"INTERFACE-CONTRACTS.md", "PUBLICATION-PREPARATION.md", "PLANNED-DAG.json"}
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
# ADR 0012 第三条：补救依据走权威链/正本，不从推论层原件反向引用。
MARKDOWN_BASIS_FILES = {
    "AGENTS.md", "README.md", "SECURITY.md", "CONTEXT.md", "docs/ROADMAP.md",
    ".chanlun/at18/pregate/README.md", ".chanlun/at18/pregate/scope-basis.md",
}
MARKDOWN_BASIS_DIRS = {
    ".chanlun/definitions", "docs/chanlun/text/blog", "docs/chanlun/text/chan99", "spec/theorems",
}
ADR_BASENAME = re.compile(r"(?:[0-9]{4}-[^/]+|README)\.md")
COMPONENT_TREES = (
    "s_session/", "rust/", "scripts/", "formal/", "tests/", "src/", "frontend/",
    "trading_system/", ".chanlun/at18/",
)
OUTPUT_DIRS = {"runs", "logs", "reports", "review-results", "diagnostics", "output", "outputs", "evidence"}
INFERENCE_TREES = (
    "analysis/", ".chanlun/genealogy/", ".chanlun/tower-construction/", "docs/architecture/",
    "docs/memory_snapshot/", "docs/chanlun/external-consults/", "docs/chanlun/text/mindmaps/",
)
DATA_EXTENSIONS = {".json", ".jsonl"}
CODE_EXTENSIONS = {
    ".rs", ".py", ".ts", ".mts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".yml", ".yaml",
    ".toml", ".lean", ".sql", ".cfg", ".ini",
}


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
    if (bundle, area) == ("issue1339-r2-spec-20260909", "spec") and leaf in ARCHIVE_SPEC_FILES:
        return False
    stem, _, extension = leaf.rpartition(".")
    allowed = ARCHIVE_BASIS_STEMS.get((bundle, area), ())
    return not (stem in allowed and extension in {"md", "json"})


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


POINTER_CODE = r"(?P<tick>`+)(?P<code>[^`\r\n]+)(?P=tick)(?!`)"
POINTER_CLAUSE = re.compile(POINTER_CODE + r"|(?P<end>[。；;！？]|[.!?](?=\s|$))")
POINTER_COMMA = re.compile(POINTER_CODE + r"|(?P<end>[，,])")
POINTER_ARROW = r"->|=>|→"
POINTER_DIRECTION = re.compile(
    POINTER_CODE + r"|(?P<direction>迁移(?:至|到)|迁(?:至|到)|移(?:至|到)|搬(?:至|到)|"
    r"\b(?:moved|migrated|renamed)\s+to\b|" + POINTER_ARROW + ")", re.I
)
POINTER_TOKEN = re.compile(POINTER_CODE + r"""|[^\s`，。；：！？、（）「」【】<>()\[\]{}"';,:*|]+""")
POINTER_LIST = re.compile(r"^(?:[-*+]|[0-9]+[.)])\s+")
POINTER_HEADING = re.compile(r"^#{1,6}\s+")
POINTER_FENCE = re.compile(r"`{3,}|~{3,}")
# 采纳表是声明的出处，不是迁移端点（#1394 的原始指针即如此）。
POINTER_ATTRIBUTION = re.compile(r"^`[^`\n]+`\s+的\s+`[^`\n]+`\s*表(?:中)?登记的\s*")
POINTER_UNASSERTED = re.compile(r"(?:未(?:曾|能)?|不(?:会|再)?|拟|计划|待|尚未|\b(?:not|be|if))\s*$", re.I)


def pointer_blocks(text):
    """软换行保留在声明中；硬换行、列表与表格行各自成段。"""
    block = []
    fence = None
    for raw in (*text.split("\n"), ""):
        raw = raw.removesuffix("\r")
        hard = raw.endswith(("  ", "\\"))
        line = raw.removesuffix("\\").strip()
        marker = POINTER_FENCE.match(line)
        if fence is not None:
            if marker and marker[0].startswith(fence) and not line[marker.end():].strip():
                fence = None
            continue
        if not line or marker or POINTER_HEADING.match(line) or line.startswith(">"):
            if block:
                yield "\n".join(block)
                block.clear()
            if marker:
                fence = marker[0]
            continue
        item = POINTER_LIST.match(line)
        table = "|" in line
        if (item or table) and block:
            yield "\n".join(block)
            block.clear()
        block.append(line[item.end():] if item else line)
        if hard or table:
            yield "\n".join(block)
            block.clear()


def pointer_clauses(block, delimiter):
    start = 0
    for match in delimiter.finditer(block):
        if match["end"]:
            yield block[start:match.start()]
            start = match.end()
    yield block[start:]


def pointer_paths(side):
    tokens = [m["code"] or m[0] for m in POINTER_TOKEN.finditer(side)
              if m["code"] or "/" in m[0] or "." in m[0]]
    bare = side.strip(" \t\n|")
    return tokens or ([bare] if re.fullmatch(r"[\w-]+", bare) else [])


def pointer_pair(clause, *, arrow_only=False):
    clause = POINTER_ATTRIBUTION.sub("", clause.strip())
    directions = [m for m in POINTER_DIRECTION.finditer(clause) if m["direction"]]
    if len(directions) != 1:
        return None
    direction = directions[0]
    before = clause[:direction.start()]
    if (arrow_only and re.fullmatch(POINTER_ARROW, direction[0]) is None) or POINTER_UNASSERTED.search(before):
        return None
    old, new = pointer_paths(before), pointer_paths(clause[direction.end():])
    if len(old) == len(new) == 1 and valid_path(old[0]) and valid_path(new[0]):
        # 软换行只能续写声明，不能先吞一行无关的正文或回执字段。
        if "\n" not in before or pointer_paths(before.partition("\n")[0]) == old:
            return old[0], new[0]
    return None


def fixture_pointer_pairs(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        return set()
    if "\0" in text:
        return set()
    pairs = set()
    for block in pointer_blocks(text):
        declared = set()
        for clause in pointer_clauses(block, POINTER_CLAUSE):
            parts = list(pointer_clauses(clause, POINTER_COMMA))
            if len(parts) > 1:
                split_pairs = [pointer_pair(part, arrow_only=True) for part in parts]
                # 逗号也可能列举端点；只有两侧都是完整箭头声明才能分开。
                if all(split_pairs):
                    declared.update(split_pairs)
                continue
            if pair := pointer_pair(clause):
                declared.add(pair)
        # 指针从迁移声明开始，可有标题或表头，不从无关正文里捞配对。
        if not declared and not pairs and not block.startswith("|"):
            return set()
        pairs.update(declared)
    return pairs


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
    def pairs(blob):
        return fixture_pointer_pairs(git("cat-file", "blob", blob, cwd=cwd))

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
                    expected = {(relative_old, target), (locations[0][1], target)}
                    if expected & pairs(current_pointers[key]) & pairs(pointers[key]):
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


def is_basis_path(path, extension):
    if path == REMEDIATION or is_artifact_archive_path(path):
        return False
    if path.startswith(REVIEW_ARCHIVE):
        return True  # is_artifact_archive_path 已限定两份冻结包的具名规范。
    directory, _, name = path.rpartition("/")
    if extension == ".md":
        return (path in MARKDOWN_BASIS_FILES
                or directory in MARKDOWN_BASIS_DIRS
                or (directory == "docs/adr" and ADR_BASENAME.fullmatch(name) is not None)
                or path.startswith(("docs/agents/", "docs/spec/"))
                or (path.startswith(".sandcastle/") and OUTPUT_DIRS.isdisjoint(directory.split("/")))
                or (path.startswith(COMPONENT_TREES) and name in {"README.md", "ORACLE.md"}))
    if extension in DATA_EXTENSIONS:
        return not path.startswith(INFERENCE_TREES) and OUTPUT_DIRS.isdisjoint(directory.split("/"))
    return extension in CODE_EXTENSIONS or name in {"Dockerfile", "Makefile"}


def has_eligible_structure(raw, extension):
    """JSON 数据必须可解析，复核/运行对象即使改成其他后缀也不能引用。"""
    content = raw.removeprefix(b"\xef\xbb\xbf")
    if extension == ".jsonl":
        records = content.removesuffix(b"\n").split(b"\n")
    elif extension == ".json" or content.lstrip().startswith(b"{"):
        records = (content,)
    else:
        return True
    for record in records:
        try:
            obj = decode_json(record)
        except ValueError:
            return extension not in DATA_EXTENSIONS
        if isinstance(obj, dict) and is_json_artifact(obj):
            return False
    return True


def basis_key(item, final_tree, archived_artifacts, cache, fail, *, cwd):
    fail(isinstance(item, dict) and item.keys() == BASIS_KEYS, "invalid verification_basis keys")
    path, blob, start, end = (item[k] for k in ("path", "blob", "line_start", "line_end"))
    fail(valid_path(path), "invalid verification_basis path")
    extension = PurePosixPath(path).suffix
    fail(is_basis_path(path, extension), ARTIFACT_BASIS_ERROR)
    entry = final_tree.get(path)
    fail(entry is not None and entry.kind == "blob" and entry.mode in REGULAR_MODES
         and entry.blob == blob, "verification_basis must bind a regular F blob")
    fail(blob not in archived_artifacts.blobs or (path, blob) in archived_artifacts.migrated_inputs,
         ARTIFACT_BASIS_ERROR)
    cache_key = (blob, extension if extension in DATA_EXTENSIONS else None)
    if cache_key not in cache:
        raw = git("cat-file", "blob", entry.blob, cwd=cwd)
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            fail(False, "verification_basis must be UTF-8 text")
        fail("\0" not in text, "verification_basis must be UTF-8 text")
        fail(has_eligible_structure(raw, extension), ARTIFACT_BASIS_ERROR)
        cache[cache_key] = text.count("\n") + bool(text and not text.endswith("\n"))
    fail(type(start) is int and type(end) is int and 1 <= start <= end <= cache[cache_key],
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
