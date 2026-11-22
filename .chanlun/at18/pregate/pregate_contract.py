"""ADR 0064 r6 的 R10 Git 对象与补救原件本地核验。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
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
ARTIFACT_ARCHIVE_SECTIONS = {"reports", "receipts", "runs", "review", "reviews"}
ARCHIVE_INPUT_SECTIONS = {("payload", "spec"), ("view", "spec"), ("payload", "inputs")}
ARTIFACT_BASIS_ERROR = "verification_basis cannot cite remediation, report or receipt"
# 版本化的验收产物，即使改名也不是缺陷本身的验证依据。
ARTIFACT_SCHEMA_FAMILIES = {
    "at18-report", "at18-input-bundle", "at18-verification", "at18-pregate-remediation",
    "at18-pregate-review", "at18-landing-census", "at18-run-record", "at18-group-execution",
    "at18-scaffold-seal", "at18-diagnostic", "at18-tb-entity", "at18-key-witness",
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


class Entry(NamedTuple):
    mode: str
    kind: str
    blob: str


class ContractError(ValueError):
    pass


def require(condition, code, message):
    if not condition:
        raise ContractError(f"{code}: {message}")


def git(*args, cwd=None, input=None):
    return subprocess.check_output(["git", *args], cwd=cwd, input=input)


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
    parts = path.split("/")
    if parts[:2] != [".chanlun", "review-results"]:
        return False
    # 只在 bundle 的归档布局中认这些目录；规范与输入可含同名子目录。
    for index in range(3, len(parts) - 1):
        if tuple(parts[index:index + 2]) in ARCHIVE_INPUT_SECTIONS:
            return False
        if parts[index] in ARTIFACT_ARCHIVE_SECTIONS:
            return True
    return False


def is_git_sha(value):
    return isinstance(value, str) and OID.fullmatch(value) is not None


def is_json_artifact(obj):
    for key in ("schema_version", "schema"):
        value = obj.get(key)
        version = re.fullmatch(r"(.+)(?:/|\.v)[1-9][0-9]*", value) if isinstance(value, str) else None
        if version and version[1] in ARTIFACT_SCHEMA_FAMILIES:
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
    return bool(RECEIPT_COMMIT.search(metadata)
                and (RECEIPT_VERDICT.search(metadata)
                     or (RUN_EXIT_CODE.search(metadata) and RUN_RESULT.search(metadata))))


def basis_key(item, final_tree, archived_artifacts, cache, fail, *, cwd):
    fail(isinstance(item, dict) and item.keys() == BASIS_KEYS, "invalid verification_basis keys")
    path, blob, start, end = (item[k] for k in ("path", "blob", "line_start", "line_end"))
    fail(valid_path(path), "invalid verification_basis path")
    fail(path != REMEDIATION, ARTIFACT_BASIS_ERROR)
    entry = final_tree.get(path)
    fail(entry is not None and entry.kind == "blob" and entry.mode in REGULAR_MODES
         and entry.blob == blob, "verification_basis must bind a regular F blob")
    fail(blob not in archived_artifacts, ARTIFACT_BASIS_ERROR)
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
    # F 中的同一 blob 即同一产物；改路径或扩展名不会改变身份。
    archived_artifacts = {
        entry.blob for path, entry in final_tree.items()
        if path.startswith(".chanlun/review-results/") and entry.kind == "blob"
        and entry.mode in REGULAR_MODES and is_artifact_archive_path(path)
    }
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
