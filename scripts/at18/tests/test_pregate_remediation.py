"""R10 补救原件：每例在独立 Git 仓库、普通和优化 Python 中走同一校验入口。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
PREGATE = ROOT / ".chanlun/at18/pregate"
REVIEW = ".chanlun/at18/pregate-review.json"
PRE_FIRST = "d896e31be8353a9445af46629737be6a4d6363e5"
FIRST = "c5cbb9ae12ee74233dd877ba99197f9e65b36ad2"
ORIGINAL = "1aed53fd7a1e0be271de949d7c37c0ac81aefc1b"
ARTIFACT = ".chanlun/at18/pregate-remediation.json"
BLOCKED = "bad.txt"
SECOND = "第二.txt"
PASSED = "passed.txt"
PROOF = "proof.txt"
PROBE = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from check_census import p0_rows
from pregate_contract import check_remediation, classify_review, git_tree, window
p0, gate, head = sys.argv[2:5]
verdicts = json.loads(sys.argv[5])
try:
    rows = [dict(row, verdict=verdicts[row["path"]]) for row in p0_rows(p0, set(verdicts))]
    final = git_tree(head)
    classes = classify_review(rows, final)
    override = Path(sys.argv[6]) if len(sys.argv) > 6 else None
    validated = check_remediation(rows, classes, final, p0, window(p0, gate, head), override=override)
except ValueError as error:
    sys.exit(str(error))
print(json.dumps({"classes": classes, "validated": sorted(validated)}))
"""


@pytest.fixture(params=[(), ("-O",)], ids=["python", "python-O"])
def options(request):
    return request.param


class History:
    def __init__(self, root):
        self.root = root
        root.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "AT-18 synthetic")
        self.git("config", "user.email", "at18-synthetic@example.invalid")
        self.git("config", "core.filemode", "true")
        for path in (BLOCKED, SECOND, PASSED):
            self.write(path, b"P0\n")
        self.write(PROOF, "原始依据第一行\n第二行\n".encode())
        self.p0 = self.commit("P0")
        self.g0 = None

    def git(self, *args):
        return subprocess.check_output(("git", *args), cwd=self.root, text=True).strip()

    def write(self, path, raw):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    def remove(self, path):
        (self.root / path).rename(self.root.parent / "removed")

    def commit(self, title, *, stage=True):
        if stage:
            self.git("add", "-A")
        self.git("commit", "--quiet", "--no-gpg-sign", "--allow-empty", "-m", title)
        return self.git("rev-parse", "HEAD")

    def gate(self, change=True):
        if change:
            self.write(BLOCKED, b"B1\n")
        self.g0 = self.commit("G0")
        return self.g0

    def make_gitlink(self, path):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.p0},{path}")

    def blob(self, sha, path):
        return self.git("rev-parse", f"{sha}:{path}")

    def row(self, path=BLOCKED, *, commits=None, basis=PROOF):
        head = self.git("rev-parse", "HEAD")
        at_f = self.git("ls-tree", head, "--", path).split()
        return {
            "path": path, "p0_blob": self.blob(self.p0, path), "p0_mode": "100644",
            "f_blob": at_f[2] if at_f else "0" * 40, "f_mode": at_f[0] if at_f else "100644",
            "remediation_commits": [self.g0] if commits is None else commits,
            "remediation_ticket": 91, "verdict": "REMEDIATED", "defect_summary": "合成测试中的原缺陷",
            "verification_basis": [
                {"path": basis, "blob": self.blob(head, basis), "line_start": 1, "line_end": 1}],
        }

    def artifact(self, rows, *, transform=None):
        raw = json.dumps({
            "schema_version": "at18-pregate-remediation/1", "owner_ticket": 2132, "rows": rows,
        }, ensure_ascii=False).encode("utf-8")
        self.write(ARTIFACT, transform(raw) if transform else raw)
        self.commit("Synthetic remediation record")

    def probe(self, options, verdicts=None, *, override=None):
        if verdicts is None:
            verdicts = {BLOCKED: "BLOCK", PASSED: "PASS"}
        args = [sys.executable, *options, "-c", PROBE, str(PREGATE), self.p0, self.g0,
                self.git("rev-parse", "HEAD"), json.dumps(verdicts)]
        if override is not None:
            args.append(str(override))
        return subprocess.run(args, cwd=self.root, text=True, capture_output=True, check=False)


@pytest.fixture
def history(tmp_path):
    return History(tmp_path / "repo")


@pytest.mark.parametrize("variant", ["regular", "symlink", "second-parent-merge", "no-final-lf", "two-rows"])
def test_valid_remediation(history, options, variant):
    h = history
    gate = h.gate()
    commits = [gate]
    if variant == "symlink":
        h.remove(BLOCKED)
        (h.root / BLOCKED).symlink_to("external-target-never-followed")
        commits.append(h.commit("Replace with symlink blob"))
    elif variant == "second-parent-merge":
        h.git("switch", "-q", "-c", "repair")
        h.write(BLOCKED, b"B2\n")
        h.commit("Repair on side branch")
        h.git("switch", "-q", "main")
        h.git("merge", "-q", "--no-ff", "--no-gpg-sign", "-m", "Integrate repair", "repair")
        commits.append(h.git("rev-parse", "HEAD"))
    elif variant == "no-final-lf":
        h.write(PROOF, b"one\ntwo")
        h.commit("Proof without final LF")
    elif variant == "two-rows":
        h.write(SECOND, b"second repair\n")
        second_commit = h.commit("Second repair")
    row = h.row(commits=commits)
    row["verification_basis"][0]["line_end"] = 2
    rows, verdicts = [row], {BLOCKED: "BLOCK", PASSED: "PASS"}
    if variant == "two-rows":
        rows.append(h.row(SECOND, commits=[second_commit]))
        verdicts[SECOND] = "BLOCK"
    h.artifact(rows)
    result = h.probe(options, verdicts)
    assert result.returncode == 0, result.stderr
    expected = {path: "pass" if verdict == "PASS" else "changed" for path, verdict in verdicts.items()}
    assert json.loads(result.stdout) == {"classes": expected, "validated": [r["path"] for r in rows]}


@pytest.mark.parametrize("variant", ["unchanged", "mode-only", "reverted", "deleted-and-readded", "deleted"])
def test_final_blob_not_touch_history_decides_membership(history, options, variant):
    h = history
    gate = h.gate(change=variant == "reverted")
    if variant == "mode-only":
        (h.root / BLOCKED).chmod(0o755)
        gate = h.commit("Mode only")
    elif variant == "reverted":
        h.write(BLOCKED, b"P0\n")
        gate = h.commit("Back to P0")
    elif variant in ("deleted-and-readded", "deleted"):
        h.remove(BLOCKED)
        gate = h.commit("Delete path")
        if variant == "deleted-and-readded":
            h.write(BLOCKED, b"P0\n")
            gate = h.commit("Re-add P0 blob")
    result = h.probe(options)
    if variant == "deleted":
        assert result.returncode == 0
        assert json.loads(result.stdout)["classes"][BLOCKED] == "deleted"
    else:
        assert result.returncode == 1 and f"pre:{ARTIFACT}: missing" in result.stderr
    row = h.row(commits=[gate])
    h.artifact([row])
    result = h.probe(options)
    assert result.returncode == 1 and f"pre:{BLOCKED}: unexpected remediation row" in result.stderr
    h.artifact([])
    result = h.probe(options)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "classes": {BLOCKED: "deleted" if variant == "deleted" else "hard", PASSED: "pass"}, "validated": []}


def test_aba_needs_last_first_parent_change_even_with_identical_f_blob(history, options):
    h = history
    h.gate()
    row = h.row()
    h.artifact([row])
    h.write(BLOCKED, b"B2\n")
    h.commit("Drift to B2")
    h.write(BLOCKED, b"B1\n")
    h.commit("Restore B1, producing a new M_last")
    result = h.probe(options)
    assert h.blob("HEAD", BLOCKED) == row["f_blob"]
    assert result.returncode == 1 and "omits last path change (M_last)" in result.stderr


@pytest.mark.parametrize(("case", "message"), [
    ("missing", "missing remediation row"),
    ("pass-row", "unexpected remediation row"),
    ("f-blob", "F blob/mode mismatch"),
    ("f-mode", "F blob/mode mismatch"),
    ("p0-blob", "P0 blob/mode mismatch"),
    ("p0-mode", "P0 blob/mode mismatch"),
    ("basis-blob", "must bind a regular F blob"),
    ("basis-no-lf-line", "line range outside F text"),
    ("basis-reversed-range", "line range outside F text"),
    ("basis-zero-start", "line range outside F text"),
    ("basis-bool", "line range outside F text"),
    ("basis-float", "line range outside F text"),
    ("basis-self", "cannot cite remediation, report or receipt"),
    ("basis-extra", "invalid verification_basis keys"),
    ("basis-missing-key", "invalid verification_basis keys"),
    ("basis-empty", "must be nonempty"),
    ("basis-unsorted", "must be unique and UTF-8 sorted"),
    ("basis-duplicate", "must be unique and UTF-8 sorted"),
    ("basis-invalid-path", "invalid verification_basis path"),
    ("basis-symlink", "must bind a regular F blob"),
    ("basis-bad-utf8", "must be UTF-8 text"),
    ("basis-renamed-report", "cannot cite remediation, report or receipt"),
    ("basis-receipt", "cannot cite remediation, report or receipt"),
    ("commits-duplicate", "must be unique and in first-parent order"),
    ("commits-unordered", "must be unique and in first-parent order"),
    ("commits-empty", "must be nonempty Git SHAs"),
    ("commits-unrelated", "did not change path on first parent"),
    ("commits-second-parent", "did not change path on first parent"),
    ("ticket-bool", "must be a positive integer"),
    ("ticket-float", "must be a positive integer"),
    ("ticket-zero", "must be a positive integer"),
    ("blank-summary", "must be nonblank"),
    ("surrogate-summary", "invalid UTF-8 JSON"),
    ("wrong-verdict", "invalid remediation verdict"),
    ("bad-path-segment", "invalid row path"),
    ("bad-path-nul", "invalid row path"),
    ("bad-path-dot", "invalid row path"),
    ("absolute-path", "invalid row path"),
    ("row-extra", "invalid row keys"),
    ("row-missing", "invalid row keys"),
    ("row-duplicate", "rows must be unique and UTF-8 sorted"),
    ("rows-unsorted", "rows must be unique and UTF-8 sorted"),
    ("duplicate-key", "duplicate JSON key"),
    ("root-extra", "invalid envelope"),
    ("root-owner-float", "invalid envelope"),
])
def test_invalid_remediation_row(history, options, case, message):
    h = history
    g0 = h.gate()
    commits = None
    basis = PROOF
    if case == "commits-unordered":
        h.write(BLOCKED, b"B2\n")
        commits = [h.commit("Second change"), g0]
    if case == "commits-second-parent":
        h.git("switch", "-q", "-c", "repair")
        h.write(BLOCKED, b"B2\n")
        side = h.commit("Side repair")
        h.git("switch", "-q", "main")
        h.git("merge", "-q", "--no-ff", "--no-gpg-sign", "-m", "Integrate", "repair")
        commits = [side, h.git("rev-parse", "HEAD")]
    if case == "basis-symlink":
        basis = "proof-link"
        (h.root / basis).symlink_to(PROOF)
        h.commit("Symlink to proof")
    if case == "basis-bad-utf8":
        h.write(PROOF, b"\xff\n")
        h.commit("Binary evidence")
    if case in ("basis-renamed-report", "basis-receipt"):
        basis = "renamed.json" if case == "basis-renamed-report" else "evidence/at18-verification.json"
        h.write(basis, b'{"schema_version":"at18-report/1"}\n')
        h.commit("Output cannot serve as evidence")

    row = h.row(commits=commits, basis=basis)
    item = row["verification_basis"][0]
    rows, transform, verdicts = [row], None, {BLOCKED: "BLOCK", PASSED: "PASS"}
    updates = {
        "f-blob": {"f_blob": row["p0_blob"]}, "f-mode": {"f_mode": "100755"},
        "p0-blob": {"p0_blob": row["f_blob"]}, "p0-mode": {"p0_mode": "100755"},
        "basis-empty": {"verification_basis": []},
        "commits-duplicate": {"remediation_commits": [g0, g0]},
        "commits-empty": {"remediation_commits": []}, "commits-unrelated": {"remediation_commits": [h.p0]},
        "ticket-bool": {"remediation_ticket": True}, "ticket-float": {"remediation_ticket": 91.0},
        "ticket-zero": {"remediation_ticket": 0}, "blank-summary": {"defect_summary": " \t\n"},
        "wrong-verdict": {"verdict": "PASS"}, "bad-path-segment": {"path": "a//bad.txt"},
        "bad-path-nul": {"path": "\0bad.txt"}, "bad-path-dot": {"path": "a/../bad.txt"},
        "absolute-path": {"path": "/bad.txt"}, "row-extra": {"signed": True},
    }
    basis_updates = {
        "basis-blob": {"blob": "1" * 40}, "basis-no-lf-line": {"line_end": 3},
        "basis-reversed-range": {"line_start": 2, "line_end": 1},
        "basis-zero-start": {"line_start": 0}, "basis-bool": {"line_start": True},
        "basis-float": {"line_end": 1.0}, "basis-self": {"path": ARTIFACT}, "basis-extra": {"note": ""},
        "basis-invalid-path": {"path": "./proof.txt"},
    }
    if case in updates:
        row.update(updates[case])
    elif case in basis_updates:
        item.update(basis_updates[case])
    elif case == "basis-missing-key":
        item.pop("line_end")
    elif case == "basis-unsorted":
        row["verification_basis"].insert(0, dict(item, line_start=2, line_end=2))
    elif case == "basis-duplicate":
        row["verification_basis"].append(dict(item))
    elif case == "row-missing":
        row.pop("p0_mode")
    elif case == "row-duplicate":
        rows.append(dict(row))
    elif case == "rows-unsorted":
        h.write(SECOND, b"C1\n")
        rows.insert(0, h.row(SECOND, commits=[h.commit("Second repair")]))
        verdicts[SECOND] = "BLOCK"
    elif case == "missing":
        rows = []
    elif case == "pass-row":
        rows.append(h.row(PASSED))
    transforms = {
        "duplicate-key": lambda raw: raw.replace(b'"line_end": 1', b'"line_end": 2, "line_end": 1'),
        "root-extra": lambda raw: raw.replace(b'"rows":', b'"extra": 1, "rows":'),
        "root-owner-float": lambda raw: raw.replace(b'2132', b'2132.0'),
        "surrogate-summary": lambda raw: raw.replace("合成测试中的原缺陷".encode(), br"\ud800"),
    }
    transform = transforms.get(case)
    h.artifact(rows, transform=transform)
    result = h.probe(options, verdicts)
    assert result.returncode == 1 and message in result.stderr and not result.stdout


@pytest.mark.parametrize("where", ["P0", "F", "F-tree"])
def test_non_blob_is_rejected(history, options, where):
    h = history
    if where == "P0":
        h.make_gitlink(BLOCKED)
        h.p0 = h.commit("Non-blob P0", stage=False)
        h.gate()
    else:
        h.gate()
        if where == "F":
            h.make_gitlink(BLOCKED)
            h.commit("Non-blob F", stage=False)
        else:
            h.remove(BLOCKED)
            h.write(f"{BLOCKED}/child", b"directory replaces file\n")
            h.commit("Tree at former F leaf")
    side = "P0" if where == "P0" else "F"
    result = h.probe(options)
    assert result.returncode == 1 and f"pre:{BLOCKED}: not a legal {side} blob" in result.stderr


@pytest.mark.parametrize("case", ["no-block-missing", "no-block-corrupt", "no-block-empty", "block-missing",
                                  "no-block-uncommitted", "no-block-symlink"])
def test_remediation_presence_and_exact_f_path(history, options, case):
    h = history
    h.gate()
    verdicts = {BLOCKED: "BLOCK" if case == "block-missing" else "PASS"}
    if case == "no-block-corrupt":
        h.write(ARTIFACT, b"{")
        h.commit("Commit corrupt optional artifact")
    elif case == "no-block-uncommitted":
        h.write(ARTIFACT, b"{")  # 工作树不取代 F。
    elif case == "no-block-empty":
        h.artifact([])
    elif case == "no-block-symlink":
        target = h.root / ARTIFACT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to("../../proof.txt")
        h.commit("Commit symlink at artifact path")
    result = h.probe(options, verdicts)
    if case in ("no-block-missing", "no-block-empty", "no-block-uncommitted"):
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"classes": {BLOCKED: "pass"}, "validated": []}
    else:
        assert result.returncode == 1 and f"pre:{ARTIFACT}:" in result.stderr and not result.stdout


@pytest.mark.parametrize(("change", "diagnostic"), [
    ("blob", "F blob/mode mismatch"), ("mode", "F blob/mode mismatch"),
    ("basis", "must bind a regular F blob"),
])
def test_existing_remediation_is_invalidated_by_new_f(history, options, change, diagnostic):
    h = history
    h.gate()
    h.artifact([h.row()])
    if change == "blob":
        h.write(BLOCKED, b"B2\n")
    elif change == "mode":
        (h.root / BLOCKED).chmod(0o755)
    else:
        h.write(PROOF, b"changed proof\n")
    h.commit("Next F")
    result = h.probe(options)
    assert result.returncode == 1 and diagnostic in result.stderr


@pytest.mark.parametrize("fixed_present", [True, False])
def test_detached_candidate_cannot_replace_fixed_f_artifact(history, options, fixed_present):
    h = history
    h.gate()
    if fixed_present:
        h.write(ARTIFACT, b"{")
        h.commit("Malformed canonical artifact")
    candidate = h.root.parent / "candidate.json"
    candidate.write_text(json.dumps({
        "schema_version": "at18-pregate-remediation/1", "owner_ticket": 2132, "rows": [h.row()],
    }), encoding="utf-8")
    result = h.probe(options, override=candidate)
    if fixed_present:
        assert result.returncode == 1 and "differs from the fixed F artifact" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["validated"] == [BLOCKED]


def test_f_must_be_on_g0_first_parent(history, options):
    h = history
    h.gate()
    h.git("switch", "-q", "-c", "side", h.p0)
    h.commit("F outside G0 first parent")
    result = h.probe(options, {PASSED: "PASS"})
    assert result.returncode == 1 and "F must descend from G0 on the first-parent chain" in result.stderr


@pytest.fixture(scope="module")
def review_history(tmp_path_factory):
    # 用真正的首载与 P0 构造 F，但所有新对象与索引留在夹具库。
    root = tmp_path_factory.mktemp("review-history")
    objects = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-path", "objects"], cwd=ROOT, text=True).strip()
    repo = root / "history.git"
    subprocess.run(["git", "init", "--bare", "-q", str(repo)], check=True)
    env = dict(os.environ, GIT_DIR=str(repo), GIT_WORK_TREE=str(root), GIT_ALTERNATE_OBJECT_DIRECTORIES=objects,
               GIT_INDEX_FILE=str(root / "index"), GIT_AUTHOR_NAME="AT-18 synthetic",
               GIT_AUTHOR_EMAIL="at18-synthetic@example.invalid", GIT_COMMITTER_NAME="AT-18 synthetic",
               GIT_COMMITTER_EMAIL="at18-synthetic@example.invalid")

    def git(*args, raw=None):
        return subprocess.check_output(["git", *args], cwd=root, env=env, input=raw)

    def snapshot(parent, document, *, remove=None, restore=None, merge=False):
        git("read-tree", parent)
        if remove:
            git("update-index", "--force-remove", "--", remove)
        if restore:
            git("update-index", "--add", "--cacheinfo", f"{restore['mode']},{restore['blob']},{restore['path']}")
        raw = document if isinstance(document, bytes) else json.dumps(document, ensure_ascii=False).encode()
        blob = git("hash-object", "-w", "--stdin", raw=raw).decode().strip()
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{REVIEW}")
        tree = git("write-tree").decode().strip()
        args = ["commit-tree", tree, "-p", parent]
        if merge:
            # 与第二父同树，仍必须按第一父差异看到登记变化。
            side = git(*args, "-m", "Synthetic side").decode().strip()
            args += ["-p", side]
        return git(*args, "-m", "Synthetic F").decode().strip(), raw

    original_raw = git("cat-file", "blob", ORIGINAL)
    original = json.loads(original_raw)
    rows = original["rows"]
    drop = "docs/reference-theta-v0.md"
    reduced = dict(original, rows=[row for row in rows if row["path"] != drop])
    reduced_head, reduced_raw = snapshot(FIRST, reduced, remove=drop, merge=True)
    override = root / "current-1024-review.json"
    override.write_bytes(reduced_raw)
    original_copy = root / "historic-original.json"
    original_copy.write_bytes(original_raw)

    block = next(row for row in rows if row["verdict"] == "BLOCK")
    # 退出后恢复 F 实际的 mode/blob，不以 P0 blob 代替。
    entry = git("ls-tree", FIRST, "--", block["path"]).decode().split()
    restore = dict(path=block["path"], blob=entry[2], mode=entry[0])
    edited = dict(original, rows=[dict(row, verdict="PASS") if row == block else row for row in rows])
    flipped, _ = snapshot(FIRST, edited)
    exited, _ = snapshot(FIRST, dict(original, rows=[row for row in rows if row != block]), remove=block["path"])
    faithful_reentry, _ = snapshot(exited, original, restore=restore, merge=True)
    washed_reentry, _ = snapshot(exited, edited, restore=restore, merge=True)
    first_wrong, _ = snapshot(PRE_FIRST, edited)
    wrong_then_restored, _ = snapshot(first_wrong, original_raw)
    damaged, _ = snapshot(FIRST, b"{")

    path = ".chanlun/review-results/issue1394-content-v3-20260916/inputs/content-format-vectors.json"
    census_doc = json.loads((PREGATE.parent / "landing-census.json").read_bytes())
    mode, _, blob = git("ls-tree", census_doc["p0"], "--", path).decode().split("\t")[0].split()
    new_row = dict(path=path, blob=blob, mode=mode, verdict="BLOCK")
    new_registration = dict(original, rows=sorted([*rows, new_row], key=lambda row: row["path"]))
    expanded, _ = snapshot(FIRST, new_registration, restore=new_row)
    new_row["verdict"] = "PASS"
    new_verdict_flip, _ = snapshot(expanded, new_registration)
    return env, {"reduced": reduced_head, "reduced_override": override, "preview": original_copy,
                 "flipped": flipped, "faithful_reentry": faithful_reentry, "washed_reentry": washed_reentry,
                 "wrong_then_restored": wrong_then_restored, "damaged": damaged, "block_path": block["path"],
                 "expanded": expanded, "new_verdict_flip": new_verdict_flip, "new_path": path}


def census(options, *args, env=None):
    return subprocess.run([sys.executable, *options, str(PREGATE / "check_census.py"), *args],
                          cwd=ROOT, env=env, text=True, capture_output=True, check=False)


@pytest.mark.parametrize("case", ["before", "explicit-frozen", "first", "reduced", "reduced_override", "preview",
                                  "flipped", "faithful_reentry", "washed_reentry", "wrong_then_restored",
                                  "damaged", "stale_override", "expanded", "new_verdict_flip"])
def test_review_distinguishes_current_f_from_immutable_first_parent_review(review_history, options, case):
    env, data = review_history
    head = {"before": PRE_FIRST, "preview": PRE_FIRST, "explicit-frozen": "b9d898dc", "first": FIRST,
            "reduced_override": data["reduced"], "stale_override": data["reduced"]}.get(case, data.get(case))
    flags = ["--review", str({
        "reduced_override": data["reduced_override"], "stale_override": data["preview"],
        "preview": data["preview"], "damaged": data["preview"],
    }[case])] if case in ("reduced_override", "stale_override", "preview", "damaged") else []
    result = census(options, "--head", head, *flags, env=env)
    assert result.returncode == 1, result.stderr
    missing = f"PREGATE_REVIEW: pre:{REVIEW}: missing"
    if case in ("before", "explicit-frozen", "wrong_then_restored"):
        assert missing in result.stderr and not result.stdout
    elif case in ("flipped", "washed_reentry", "new_verdict_flip"):
        path = data["new_path"] if case == "new_verdict_flip" else data["block_path"]
        assert f"pre:{path}: historical verdict mismatch: BLOCK -> PASS" in result.stderr
        assert not result.stdout
    elif case in ("damaged", "stale_override"):
        reason = "invalid UTF-8 JSON" if case == "damaged" else "local review differs from the fixed F artifact"
        assert reason in result.stderr and not result.stdout
    else:
        if case == "preview":
            assert f"{missing} in F; --review is a local preview only" in result.stdout
            assert "F review: first-parent introduction" not in result.stdout
        else:
            assert f"F review: first-parent introduction {FIRST}; original blob {ORIGINAL}" in result.stdout
        matches = {
            "reduced": (1024, 977, 47, 42), "reduced_override": (1024, 977, 47, 42),
            "expanded": (1026, 978, 48, 43),
        }
        count, passed, blocked, hard = matches.get(case, (1025, 978, 47, 42))
        assert f"{count} exact path/blob/mode matches; {passed} PASS / {blocked} BLOCK" in result.stdout
        assert f"{hard} hard BLOCK / 5 changed BLOCK / 0 deleted BLOCK" in result.stdout
        assert "0 released" in result.stdout and "path coverage mismatch" not in result.stderr


@pytest.mark.parametrize("number", [b"1" + b"0" * 400, b"1e400", b"-1" + b"0" * 400, b"-1e400", b"NaN",
                                    b"Infinity", b"-Infinity"],
                         ids=["int", "exp", "negative-int", "negative-exp", "nan", "inf", "negative-inf"])
@pytest.mark.parametrize("field", ["ticket", "line", "nested"])
def test_jcs_numeric_domain_precedes_remediation_shape(history, options, number, field):
    h = history
    h.gate()
    marker = b'"JCS_OVERFLOW"'
    row = h.row()
    if field == "ticket":
        row["remediation_ticket"] = "JCS_OVERFLOW"
    elif field == "line":
        row["verification_basis"][0]["line_end"] = "JCS_OVERFLOW"
    else:
        row["extra"] = {"nested": [{"value": "JCS_OVERFLOW"}]}
    h.artifact([row], transform=lambda raw: raw.replace(marker, number))
    result = h.probe(options)
    assert result.returncode == 1 and not result.stdout
    assert f"pre:{ARTIFACT}: JCS_CANONICALIZE: number outside finite IEEE 754 binary64" in result.stderr


@pytest.mark.parametrize("number", [b"1" + b"0" * 400, b"1e400"], ids=["integer-token", "exponent-token"])
def test_census_uses_jcs_domain_on_other_strict_json_inputs(options, tmp_path, number):
    path = tmp_path / "registry.json"
    path.write_bytes(b'{"pregate":{"nested":[{"extra":' + number + b'}]}}')
    result = census(options, "--registry", str(path))
    assert result.returncode == 1 and not result.stdout
    assert "PREGATE_CENSUS: registry.json: JCS_CANONICALIZE: number outside finite IEEE 754 binary64" in result.stderr


SUMMARY_TITLE = "# AT-18 整图验收"
RUN_HEAD = "17edc9cd0f909f58e6ec51caeb92742a050d7495"
RENDERED_SUMMARY = (
    f"{SUMMARY_TITLE}\n\n结论：**FAIL**\n\n主线提交：`{RUN_HEAD}`\n\n"
    "覆盖账本：97 个故事、345 个 family、496 个细项。\n\n## Destination\n\n"
    "- DST-01：FAIL\n\n## TB 关票门\n\n- TB-01 #1359：CLOSED，满足\n\n"
    "## 失败项\n\n共 10 项。逐项 scope 和证据见同批 at18-report.json。\n"
)
SETTLEMENT_RULE = "\n\n计价规范：计算以分为单位，不足一分向上取整。\n"
FEE_RULE = '{\n  "unit": "cent",\n  "low_fraction": "round_up"\n}'


@pytest.mark.parametrize(("path", "doc", "allowed"), [
    ("spec/plain.md", "费率表：每百元三分，取整到分。\n", True),
    ("spec/summary.md", "费率表：每百元三分，取整到分。\n", True),
    ("out/summary.md", RENDERED_SUMMARY, False),
    ("spec/copied-report.md", RENDERED_SUMMARY, False),
    ("out/at18-report.json", {"schema_version": "at18-report/1"}, False),
    ("out/at18-verification.json", {"schema_version": "at18-verification/1"}, False),
    ("spec/copied-receipt.json", {"schema_version": "at18-verification/1"}, False),
    ("spec/copied-input.json", {"schema_version": "at18-input-bundle/1"}, False),
    ("spec/copied-run.json", {"schema_version": "at18-run-record/1"}, False),
    ("spec/copied-remediation.json", {"schema_version": "at18-pregate-remediation/1"}, False),
    ("spec/copied-review.json", {"schema_version": "at18-pregate-review/1"}, False),
    ("spec/copied-seal.json", {"schema_version": "at18-scaffold-seal/1"}, False),
    ("spec/copied-report.data", {"schema_version": "at18-report/1"}, False),
    ("spec/independent.json", {"review_round": "R2", "reviewer": "reader",
                               "conclusion": "PASS_WITH_GATES"}, False),
    ("spec/queue.json", {"gate": "queue", "status": "passed", "checks": [], "exit_code": 0}, False),
    ("spec/fee-rounding.json", {"gate": "rounding", "status": "specified",
                                "checks": [{"input": "0.1", "result": "1"}]}, True),
    ("spec/fee-rounding.json", {"unit": "cent", "result": "round_up", "status": "PASS"}, True),
    ("spec/local-receipt.txt", f"Reviewed head: {RUN_HEAD}\nVerdict: PASS\n", False),
    ("spec/local-run.txt", f"Commit: {RUN_HEAD}\nExit code: 0\nRun result: PASS\n", False),
    ("spec/receipt-format.md", f"# 回执的格式\n\n```text\nHead: {RUN_HEAD}\nVerdict: PASS\n```\n", True),
    ("spec/copied-manifest.json", {"schemaVersion": 1, "ticket": 1372, "base": "1" * 40, "head": "2" * 40,
                                  "productDiff": [], "requiredReports": [], "reports": [], "reviews": [],
                                  "requiredChecks": [], "checks": [], "scan": {"status": "not_run"}}, False),
])
def test_verification_basis_checks_artifact_identity(history, options, path, doc, allowed):
    h = history
    h.gate()
    if not isinstance(doc, str):
        doc = json.dumps(doc)
    h.write(path, doc.encode())
    h.commit("Add verification evidence")
    h.artifact([h.row(basis=path)])
    result = h.probe(options)
    if allowed:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["validated"] == [BLOCKED]
    else:
        assert result.returncode == 1 and not result.stdout
        assert "verification_basis cannot cite remediation, report or receipt" in result.stderr


@pytest.mark.parametrize(("path", "doc", "line"), [
    ("spec/settlement.md", "## 费用计算规则" + SETTLEMENT_RULE, 3),
    ("spec/settlement.md", SUMMARY_TITLE + SETTLEMENT_RULE, 3),
    ("spec/settlement.md", SUMMARY_TITLE + "\n\n结论：**PASS**" + SETTLEMENT_RULE, 5),
    ("spec/fee-rounding.json", FEE_RULE, 2),
    ("spec/at18-report.json", FEE_RULE, 2),
    ("spec/at18-input-bundle.json", FEE_RULE, 2),
    ("spec/at18-verification.json", FEE_RULE, 2),
    ("docs/reports/settlement.md", SETTLEMENT_RULE, 3),
])
def test_verification_basis_accepts_rules_not_named_artifacts(history, options, path, doc, line):
    h = history
    h.gate()
    h.write(path, doc.encode())
    h.commit("Add rule")
    row = h.row(basis=path)
    row["verification_basis"][0].update(line_start=line, line_end=line)
    h.artifact([row])
    result = h.probe(options)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["validated"] == [BLOCKED]


TB_REPORT_PATH = (
    ".chanlun/review-results/issue1372-tb01c-20260913/reports/"
    "browser-continuation-performance/final-run-results/REPORT.md"
)
TB_REPORT_BLOB = "0f94d1625e745af8fa040cc96d8c992d83fca985"
TB_ROOT = ".chanlun/review-results/issue1372-tb01c-20260913/reports/"


@pytest.mark.parametrize(("mode", "source", "blob", "line"), [
    ("archive", TB_REPORT_PATH, TB_REPORT_BLOB, 3),
    ("copy", TB_REPORT_PATH, TB_REPORT_BLOB, 3),
    ("isolated", TB_REPORT_PATH, TB_REPORT_BLOB, 3),
    ("isolated", TB_ROOT + "legacy-query-callers-audit/REPORT.json", "154af3f5240d8b90657274ac2bd303e463d26b8d", 3),
    ("isolated", TB_ROOT + "runtime/trajectory-r5-a/FACTS.json", "f845d2bbb066b9798dcc07067c9c711b3097efe1", 3),
    ("isolated", TB_ROOT + "q-memo-independent/REVIEW.md", "ad2b826a02d3246a8f364729133adc05862ec16e", 3),
    ("isolated", TB_ROOT + "browser-continuation-performance/final-run-results/MANIFEST.json",
     "bae060f976620d1158bb510b8a157d605bce4ee1", 3),
    ("move", TB_REPORT_PATH, TB_REPORT_BLOB, 3),
    ("move", TB_ROOT + "legacy-query-callers-audit/REPORT.json", "154af3f5240d8b90657274ac2bd303e463d26b8d", 3),
    ("move", TB_ROOT + "runtime/trajectory-r5-a/FACTS.json", "f845d2bbb066b9798dcc07067c9c711b3097efe1", 3),
    ("move", TB_ROOT + "q-memo-independent/REVIEW.md", "ad2b826a02d3246a8f364729133adc05862ec16e", 3),
    ("move", TB_ROOT + "browser-continuation-performance/final-run-results/MANIFEST.json",
     "bae060f976620d1158bb510b8a157d605bce4ee1", 3),
])
def test_verification_basis_rejects_actual_tb_artifacts(history, options, mode, source, blob, line):
    h = history
    h.gate()
    raw = subprocess.check_output(["git", "cat-file", "blob", blob], cwd=ROOT)
    path = source if mode == "archive" else "spec/evidence.dat"
    if mode in ("copy", "move"):
        h.write(source, raw)
    if mode == "move":
        h.commit("Archive the original before relocation")
        h.remove(source)
    h.write(path, raw)
    h.commit("Add the historical artifact")
    assert h.blob("HEAD", path) == blob
    row = h.row(basis=path)
    row["verification_basis"][0].update(line_start=line, line_end=line)
    h.artifact([row])
    result = h.probe(options)
    assert result.returncode == 1 and not result.stdout
    assert "verification_basis cannot cite remediation, report or receipt" in result.stderr


@pytest.mark.parametrize("section", ["reports", "receipts", "runs", "reviews"])
def test_verification_basis_rejects_same_blob_of_unstructured_archived_receipt(history, options, section):
    h = history
    h.gate()
    path = "spec/copied-receipt.txt"
    raw = "产物由对应工位核对。\n".encode()
    h.write(f".chanlun/review-results/topic/{section}/sealed/receipt.txt", raw)
    h.write(path, raw)
    h.commit("Archive receipt and copy")
    h.artifact([h.row(basis=path)])
    result = h.probe(options)
    assert result.returncode == 1 and not result.stdout
    assert "verification_basis cannot cite remediation, report or receipt" in result.stderr


def test_verification_basis_accepts_archived_spec_view(history, options):
    h = history
    h.gate()
    path = ".chanlun/review-results/issue1339-r2-spec-20260909/view/spec/INTERFACE-CONTRACTS.md"
    blob = "ab06de5061db7b28ef49acdcfd57e97fbd0ff66d"
    h.write(path, subprocess.check_output(["git", "cat-file", "blob", blob], cwd=ROOT))
    h.commit("Add the historical spec view")
    h.artifact([h.row(basis=path)])
    result = h.probe(options)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["validated"] == [BLOCKED]


ARCHIVE = ".chanlun/review-results/"
SPEC_PACKAGE = ARCHIVE + "issue1339-r2-spec-20260909/"
PUBLICATION = ARCHIVE + "issue1340-publication-20260909/"
DELIVERY = ARCHIVE + "issue1719-recovery-20261026/REPORT.md"
QUEUE_RESULT = TB_ROOT + "rust-p4-independent/queue-fix-recheck/RESULT.json"
PROTOCOL_REVIEW_JSON = SPEC_PACKAGE + "payload/spec/review/PROTOCOL-SPEC-REVIEW.json"
SPEC_INTERFACE = SPEC_PACKAGE + "view/spec/INTERFACE-CONTRACTS.md"
ADR_DESIGN = "docs/adr/0008-bsp-bridge-object-and-structural-key-v2.md"
R3_HEAD = "16698eaefb3854b6e91fc0541e0af09ebb8f35ff"
BASIS_ERROR = "verification_basis cannot cite remediation, report or receipt"


def git_at_r3(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def archive_source(path):
    # 固定真实原件。临时仓库只含本例加入的文件及历史。
    return git_at_r3("show", f"{R3_HEAD}:{path}")


def check_basis(history, options, path, *, allowed, line=1):
    row = history.row(basis=path)
    row["verification_basis"][0].update(line_start=line, line_end=line)
    history.artifact([row])
    result = history.probe(options)
    if allowed:
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["validated"] == [BLOCKED]
    else:
        assert result.returncode == 1 and not result.stdout
        assert BASIS_ERROR in result.stderr


@pytest.mark.parametrize("mode", ["archive", "copy", "move"])
@pytest.mark.parametrize(("source", "line"), [
    (PROTOCOL_REVIEW_JSON, 8),
    (SPEC_PACKAGE + "payload/spec/review/PROTOCOL-SPEC-REVIEW.md", 3),
    (SPEC_PACKAGE + "view/spec/review/PROTOCOL-SPEC-REVIEW.md", 5),
    (DELIVERY, 3),
    (QUEUE_RESULT, 2),
], ids=["protocol-json", "protocol-original", "protocol-view", "delivery", "queue"])
def test_verification_basis_rejects_named_archive_cases(history, options, source, line, mode):
    h = history
    raw = archive_source(source)
    h.write(source, raw)
    h.p0 = h.commit("Archive original before the R10 window")
    h.gate()
    path = source
    if mode != "archive":
        path = "spec/neutral-note.dat"
        if mode == "move":
            h.remove(source)
        h.write(path, raw)
        h.commit("Reuse the original bytes at a neutral path")
        assert h.blob("HEAD", path) == h.blob(h.p0, source)
        if mode == "move":
            assert not h.git("ls-tree", "HEAD", "--", source)
    check_basis(h, options, path, allowed=False, line=line)


@pytest.mark.parametrize("source", [QUEUE_RESULT, PROTOCOL_REVIEW_JSON])
def test_verification_basis_rejects_unarchived_independent_json(history, options, source):
    h = history
    path = "spec/neutral-note.dat"
    h.write(path, archive_source(source))
    h.gate()
    assert not h.git("log", "--all", "--format=%H", "--", ARCHIVE)
    check_basis(h, options, path, allowed=False, line=2)


@pytest.mark.parametrize(("source", "allowed"), [
    (SPEC_PACKAGE + "payload/spec/SPEC.json", True),
    (SPEC_PACKAGE + "payload/spec/IMPLEMENTATION-CROSSWALK.json", True),
    (SPEC_PACKAGE + "payload/spec/inputs/SPEC-COVERAGE-INPUT.json", True),
    (SPEC_INTERFACE, True),
    (SPEC_PACKAGE + "APPROVAL.json", False),
    (SPEC_PACKAGE + "ARCHIVE-INDEX.json", False),
    (SPEC_PACKAGE + "ARCHIVE-VALIDATION.json", False),
    (SPEC_PACKAGE + "payload/spec/evidence/DOC-VALIDATION-S2.json", False),
    (SPEC_PACKAGE + "payload/spec/snapshots/s1-initial-reviews/PROTOCOL-SPEC-REVIEW.md", False),
    (SPEC_PACKAGE + "payload/sources/newchanlun-1339-requirements-20260908/evidence/DOCUMENT-CHECK.json", False),
    (PUBLICATION + "payload/inputs/TB01-DISPATCH-REVIEW.json", False),
    (PUBLICATION + "payload/inputs/PUBLISHED-GRAPH-VERIFY.json", False),
    (PUBLICATION + "view/inputs/FULL-LEAF-PUBLISHED-VERIFY.md", False),
    (PUBLICATION + "payload/inputs/TB01-EXECUTION-SLICES.json", True),
    (PUBLICATION + "view/inputs/TB07-11-EXECUTION-SLICES.md", True),
    (ADR_DESIGN, True),
])
def test_verification_basis_archive_allows_only_specification_originals(history, options, source, allowed):
    h = history
    raw = archive_source(source)
    h.write(source, raw)
    h.gate()
    check_basis(h, options, source, allowed=allowed, line=2)


@pytest.mark.parametrize("integrated", [False, True], ids=["side-only", "first-parent-merge"])
def test_verification_basis_archive_blob_requires_first_parent_provenance(history, options, integrated):
    h = history
    path = "spec/neutral-note.txt"
    archived = ARCHIVE + "unknown-bundle/payload/spec/unclassified\toutput.md"
    raw = "不含机器标记的记录。\n".encode()
    h.gate()
    h.git("switch", "-q", "-c", "review-side")
    h.write(archived, raw)
    h.commit("Only the review side writes the archive first")
    h.git("switch", "-q", "main")
    strategy = [] if integrated else ["-s", "ours"]
    h.git("merge", "-q", "--no-ff", "--no-gpg-sign", *strategy, "-m", "Merge", "review-side")
    if integrated:
        h.remove(archived)
    h.write(path, raw)
    h.commit("The final tree only has the neutral name")
    check_basis(h, options, path, allowed=not integrated)


def test_verification_basis_keeps_specification_identity_after_move(history, options):
    h = history
    raw = archive_source(SPEC_INTERFACE)
    h.write(SPEC_INTERFACE, raw)
    h.gate()
    h.remove(SPEC_INTERFACE)
    path = "spec/interface.md"
    h.write(path, raw)
    h.commit("Move the specification out of the archive")
    check_basis(h, options, path, allowed=True, line=9)


@pytest.fixture(scope="module")
def archive_preview(tmp_path_factory):
    root = tmp_path_factory.mktemp("archive-preview")
    rows = json.loads(git_at_r3("show", f"{R3_HEAD}:{REVIEW}"))["rows"]
    entries = []
    for row in rows:
        if row["verdict"] != "BLOCK":
            continue
        entry = git_at_r3("ls-tree", R3_HEAD, "--", row["path"]).split()
        if not entry or entry[2].decode() == row["blob"]:
            continue
        last = git_at_r3("log", "-1", "--first-parent", "--format=%H", R3_HEAD,
                         "--", row["path"]).decode().strip()
        entries.append({"path": row["path"], "p0_blob": row["blob"], "p0_mode": row["mode"],
                        "f_blob": entry[2].decode(), "f_mode": entry[0].decode(),
                        "remediation_commits": [last], "remediation_ticket": 2132,
                        "verdict": "REMEDIATED", "defect_summary": "测试真实 F 上的复核依据身份。"})
    assert len(entries) == 5
    previews = {}
    for path, line, count in [(PROTOCOL_REVIEW_JSON, 8, 0), (SPEC_INTERFACE, 9, 5), (QUEUE_RESULT, 2, 0)]:
        blob = git_at_r3("rev-parse", f"{R3_HEAD}:{path}").decode().strip()
        basis = {"path": path, "blob": blob, "line_start": line, "line_end": line}
        doc = {"schema_version": "at18-pregate-remediation/1", "owner_ticket": 2132,
               "rows": [dict(entry, verification_basis=[basis]) for entry in entries]}
        target = root / f"{count}-{Path(path).stem}.json"
        target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        previews[path] = (target, count)
    return previews


@pytest.mark.parametrize("path", [PROTOCOL_REVIEW_JSON, SPEC_INTERFACE, QUEUE_RESULT],
                         ids=["protocol-review", "interface", "queue-result"])
def test_census_archive_preview_validates_only_specifications(options, archive_preview, path):
    preview, count = archive_preview[path]
    result = census(options, "--head", R3_HEAD, "--remediation", str(preview))
    assert result.returncode == 1, result.stderr
    assert ("42 hard BLOCK / 5 changed BLOCK / 0 deleted BLOCK; "
            f"{count} locally validated remediation rows; 0 released") in result.stdout, result.stderr
    assert (BASIS_ERROR in result.stderr) == (count == 0)


@pytest.mark.parametrize("leaf", ["payload/spec/rules.md", "view/spec/rules.md", "payload/inputs/receipts/rules.md"])
@pytest.mark.parametrize("cite_archive", [False, True], ids=["live-original", "archive-path"])
def test_basis_keeps_rules_first_published_outside_archive(history, options, leaf, cite_archive):
    h = history
    active = "standards/" + leaf
    frozen = ARCHIVE + "topic/" + leaf
    h.write(active, SETTLEMENT_RULE.encode())
    h.gate()
    h.write(frozen, SETTLEMENT_RULE.encode())
    h.commit("Freeze an already published rule")
    check_basis(h, options, frozen if cite_archive else active, allowed=not cite_archive, line=3)


@pytest.mark.parametrize(("kind", "leaf", "raw", "allowed"), [
    ("directory", "inputs/vectors.json", FEE_RULE, False),
    ("same-dir", "frozen/material.json", FEE_RULE, True),
    ("manifest-inputs", "frozen/material.json", FEE_RULE, False),
    ("package", "frozen/material.json", FEE_RULE, True),
    ("digest-list", "frozen/material.json", FEE_RULE, False),
    ("archive-root", "frozen/material.json", FEE_RULE, False),
    ("wrong-path", "frozen/material.json", FEE_RULE, False),
    ("late", "frozen/material.json", FEE_RULE, False),
    ("wrong-blob", "frozen/material.json", FEE_RULE, False),
    ("archive-source", "frozen/material.json", FEE_RULE, False),
    ("late", "old/result-copy.txt", "Unstructured delivery record\n", False),
    ("same-dir", "frozen/REPORT.md", "Unstructured delivery record\n", False),
    ("directory", "inputs/NODE-RESULT.json", FEE_RULE, False),
    ("directory", "inputs/receipts/material.json", FEE_RULE, False),
    ("directory", "inputs/PROTOCOL-REVIEW.json", FEE_RULE, False),
    ("directory", "inputs/PROTOCOL-VERIFY.md", SETTLEMENT_RULE, False),
    ("same-dir", "frozen/material.json", '{"schema_version":"at18-report/1"}', False),
    ("directory", "inputs/material.txt", f"Reviewed head: {RUN_HEAD}\nVerdict: PASS\n", False),
], ids=[
    "bare-input-dir", "sibling-manifest", "inputs-list", "package-manifest", "digest-list",
    "archive-root-manifest", "same-basename-not-exact", "late-declaration", "wrong-blob",
    "archive-source", "late-input-alias",
    "manifest-names-report", "result-under-inputs", "receipt-dir-under-inputs",
    "review-under-inputs", "verify-under-inputs", "report-content-in-manifest", "receipt-content-under-inputs",
])
def test_basis_promotes_only_archive_inputs(history, options, kind, leaf, raw, allowed):
    h = history
    package = ARCHIVE + "generic-bundle/"
    archived = package + leaf
    dest = "spec/promoted.dat"
    h.gate()
    h.write(archived, raw.encode())
    prefixes = {"package": package, "wrong-path": package, "archive-root": ARCHIVE}
    prefix = prefixes.get(kind, archived.rsplit("/", 1)[0] + "/")
    manifest = prefix + "INPUT-MANIFEST.json"
    relative = Path(archived).name if kind == "wrong-path" else archived.removeprefix(prefix)
    if kind == "manifest-inputs":
        declaration = {"inputs": [relative]}
    elif kind == "digest-list":
        declaration = {"files_sha256": {relative: "a" * 64}}
    else:
        source = (package if kind == "archive-source" else "inputs/") + "origin.dat"
        # 首次归档和活源同提交出现，不能靠条件 A 通过。
        if kind != "late":
            h.write(source, b"different bytes" if kind == "wrong-blob" else raw.encode())
        declaration = {"frozen_copies": {relative: source}}
    if kind not in ("directory", "late"):
        h.write(manifest, json.dumps(declaration).encode())
    h.commit("Archive the original")
    if kind == "late":
        h.write(source, raw.encode())
        h.write(manifest, json.dumps(declaration).encode())
        h.write(package + "inputs/late-copy.txt", raw.encode())
        h.commit("A later input declaration cannot change origin")
    h.remove(archived)
    h.write(dest, raw.encode())
    h.commit("Promote the same bytes under a neutral name")
    check_basis(h, options, dest, allowed=allowed)


def test_basis_same_commit_input_does_not_override_archive_output(history, options):
    h = history
    raw = b"An unstructured output with no body signature.\n"
    archived = ARCHIVE + "generic-bundle/"
    active = "spec/neutral-note.txt"
    h.gate()
    h.write(archived + "inputs/vector.txt", raw)
    h.write(archived + "reports/note.txt", raw)
    h.write(active, raw)
    h.commit("Input, neutral alias and archive output enter in one commit")
    check_basis(h, options, active, allowed=False)


def test_basis_rejects_report_body_even_if_first_published_outside_archive(history, options):
    h = history
    raw = b'{"schema_version":"at18-report/1"}'
    active = "spec/neutral.json"
    h.write(active, raw)
    h.gate()
    h.write(ARCHIVE + "generic-bundle/inputs/material.json", raw)
    h.commit("Freeze an already published report")
    check_basis(h, options, active, allowed=False)


REAL_LIVE_BASES = (
    ("s_session/profiles/ohlc_integer_tb02a_v1.json", 5),
    ("s_session/catalog/signed-catalog.json", 2),
    ("s_session/tests/drive_tb03c_fin2_hfs.sh", 1),
    ("s_session/tests/fixtures/s-content-v3/content-format-vectors.json", 2),
    ("s_session/tests/fixtures/tb03c_allocation/HAND-ORACLE.json", 2),
    ("s_session/tests/fixtures/tb03c_allocation/RAW.json", 2),
    (".chanlun/tower-construction/tower_continuous_axis_unify.md", 1),
    (".chanlun/.crystallization-debt.json", 1),
)
R4_HEAD = "41aa16e8270b422bc2c6d5659b677d116fbd6184"
S86_REMOVAL = "f0492560977191c8a33e0a4eb767bacbabbc04d1"
S86_REPORT = ARCHIVE + "1488-acceptance/s86/r8/REPORT.md"
ORIGIN_PROBE = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import pregate_contract as c
head, deleted_report, publication = sys.argv[2:5]
tree = c.git_tree(head)
ban = c.archive_artifact_blobs(tree, head, cwd=None)
def require(ok, message):
    if not ok:
        raise ValueError(message)
def outcome(path, line):
    blob = tree[path].blob
    try:
        c.basis_key(dict(path=path, blob=blob, line_start=line, line_end=line), tree, ban, {}, require, cwd=None)
    except ValueError as error:
        return str(error)
    return "accepted"
live = {path: outcome(path, line) for path, line in json.loads(sys.argv[5])}
reviews = [path for path, entry in tree.items() if entry.mode in c.REGULAR_MODES
           and path.startswith(publication) and Path(path).stem.endswith(("-REVIEW", "-VERIFY"))]
slices = [path for path, entry in tree.items() if entry.mode in c.REGULAR_MODES
          and path.startswith(publication) and Path(path).stem in
          ("TB01-EXECUTION-SLICES", "TB02-06-EXECUTION-SLICES", "TB07-11-EXECUTION-SLICES")]
require(not any(entry.blob == deleted_report for entry in tree.values()), "old report still present")
tree["spec/retained-note.md"] = c.Entry("100644", "blob", deleted_report)
print(json.dumps(dict(live=live, reviews=[outcome(p, 2) for p in reviews],
                      slices=[outcome(p, 2) for p in slices], old_report=outcome("spec/retained-note.md", 1))))
"""


def test_real_history_separates_live_inputs_from_deleted_reports(options):
    report = git_at_r3("rev-parse", f"{S86_REMOVAL}^1:{S86_REPORT}").decode().strip()
    result = subprocess.run(
        [sys.executable, *options, "-c", ORIGIN_PROBE, str(PREGATE), R4_HEAD, report,
         PUBLICATION, json.dumps(REAL_LIVE_BASES)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "live": dict.fromkeys((path for path, _ in REAL_LIVE_BASES), "accepted"),
        "reviews": [BASIS_ERROR] * 26,
        "slices": ["accepted"] * 9,
        "old_report": BASIS_ERROR,
    }


R5_HEAD = "3aff72dd0c274f33ace1286927ece96b0b32401d"
DURABILITY = ARCHIVE + "issue1370-tb01-a/acceptance/payload/inputs/tb01-post-repair-durability/REVIEW-9a.md"
BROWSER = ARCHIVE + "issue1394-financial-owner-20260930/inputs/ECONOMIC-BROWSER-RESULTS.md"
VECTOR_RESULT = ARCHIVE + "issue1394-content-v3-20260916/inputs/historical-independent-vector-result.json"
VECTOR = "s_session/tests/fixtures/s-content-v3/content-format-vectors.json"


@pytest.mark.parametrize(("ref", "source", "line", "move"), [
    (R5_HEAD, DURABILITY, 3, "archive"),
    (R5_HEAD, DURABILITY, 3, "copy"),
    (R5_HEAD, DURABILITY, 3, "body"),
    ("6badaa60494740702c217abc9921809de3899ce0", BROWSER, 3, "move"),
    ("6badaa60494740702c217abc9921809de3899ce0", BROWSER, 3, "body"),
    (R5_HEAD, VECTOR_RESULT, 2, "copy"),
    (R5_HEAD, VECTOR_RESULT, 2, "move"),
    (R5_HEAD, VECTOR_RESULT, 2, "body"),
    (S86_REMOVAL + "^1", S86_REPORT, 1, "move"),
], ids=["durability-original", "durability-copy", "durability-body", "browser-restored",
        "browser-body", "vector-result-copy", "vector-result-restored", "vector-result-body",
        "s86-restored"])
def test_real_archive_reports_never_become_inputs(history, options, ref, source, line, move):
    h = history
    raw = git_at_r3("show", f"{ref}:{source}")
    path = "spec/retained-note.md" if move == "body" else source
    h.write(path, raw)
    h.gate()
    if move in ("copy", "move"):
        path = "spec/retained-note.md"
        if move == "move":
            h.remove(source)
        h.write(path, raw)
        h.commit("Reuse the genuine archive bytes under a neutral name")
        assert h.blob("HEAD", path) == git_at_r3("rev-parse", f"{ref}:{source}").decode().strip()
    check_basis(h, options, path, allowed=False, line=line)


JS_LOADER = b"""const fs = require("node:fs"), path = require("node:path");
const vectors = fs.readFileSync(path.join(__dirname, "fixtures/vectors.json"));
"""
PY_LOADER = b"""from pathlib import Path
vectors = (Path(__file__).parent / "fixtures/vectors.json").read_bytes()
"""
RUST_LOADER = b'const VECTORS: &str = include_str!("fixtures/vectors.json");\n'


@pytest.mark.parametrize(("scenario", "allowed"), [
    ("node", True), ("node-binding", True), ("python", True), ("rust", True),
    ("same-blob-alias", False), ("same-commit-loaded", False),
    ("retained-archive", False), ("report-name", False), ("old-output-name", False),
    ("report-body", False), ("comment", False), ("string", False), ("doc", False),
    ("path-variable-only", False), ("wrong-reader", False), ("wrong-dir", False), ("no-loader", False),
    ("wrong-f", False),
])
def test_basis_promotes_only_the_migrated_path_loaded_in_f(history, options, scenario, allowed):
    h = history
    package = ARCHIVE + "generic-bundle/"
    archived = package + "inputs/" + ("VECTOR-RESULTS.json" if scenario == "report-name" else "vectors.json")
    path = "tests/fixtures/vectors.json"
    raw = FEE_RULE.encode()
    if scenario == "report-body":
        raw = git_at_r3("show", f"{R5_HEAD}:{DURABILITY}")
    h.gate()
    h.write(archived, raw)
    if scenario == "same-commit-loaded":
        h.write(path, raw)
    old_output = h.root / (package + "old-VERIFY-round/vectors.json")
    if scenario == "old-output-name":
        h.write(str(old_output.relative_to(h.root)), raw)
    h.commit("First appearance in archived collection")
    if scenario == "old-output-name":
        old_output.rename(h.root.parent / "old-output")
        h.commit("Remove the older output alias")
        archived = package + "inputs/vectors.json"
    if scenario != "retained-archive":
        h.remove(archived)
    h.write(path, raw)
    code_path, code = "tests/test_vectors.cjs", JS_LOADER
    if scenario == "node-binding":
        code = code.replace(b'const vectors = fs.readFileSync(path.join(__dirname, "fixtures/vectors.json"));',
                            b'const vectorPath = path.join(__dirname, "fixtures/vectors.json",);\n'
                            b'const vectors = fs.readFileSync(vectorPath, "utf8");')
    if scenario == "python":
        code_path, code = "tests/test_vectors.py", PY_LOADER
    if scenario == "rust":
        code_path, code = "tests/test_vectors.rs", RUST_LOADER
    if scenario == "comment":
        code = b"/*\n" + code + b"*/\n"
    if scenario == "string":
        code = b"const example = `\n" + code + b"`;\n"
    if scenario == "doc":
        code_path = "tests/example.md"
    if scenario == "path-variable-only":
        code = code.replace(b"fs.readFileSync(", b"String(")
    if scenario == "wrong-reader":
        code = code.replace(b"fs.readFileSync(", b"other.fs.readFileSync(")
    if scenario == "wrong-dir":
        code_path = "other/test_vectors.cjs"
    if scenario not in ("no-loader", "wrong-f"):
        h.write(code_path, code)
    if scenario == "same-blob-alias":
        path = "spec/retained-note.md"
        h.write(path, raw)
    h.commit("Retain the selected fixture outside the archive")
    if scenario == "wrong-f":
        h.artifact([h.row(basis=path)])
        # 未写入 F 的现役加载器不能影响归档身份。
        h.write(code_path, code)
        result = h.probe(options)
        assert result.returncode == 1 and not result.stdout and BASIS_ERROR in result.stderr
        return
    check_basis(h, options, path, allowed=allowed)


@pytest.mark.parametrize(("path", "line", "count"), [
    ("s_session/profiles/ohlc_integer_tb02a_v1.json", 5, 5),
    ("s_session/README.md", 166, 5),
    (VECTOR, 2, 5),
    (DURABILITY, 3, 0),
])
def test_census_r5_previews_keep_live_inputs_and_refuse_report(options, archive_preview, tmp_path, path, line, count):
    original, _ = archive_preview[SPEC_INTERFACE]
    preview = json.loads(original.read_bytes())
    blob = git_at_r3("rev-parse", f"{R5_HEAD}:{path}").decode().strip()
    for row in preview["rows"]:
        row["verification_basis"] = [dict(path=path, blob=blob, line_start=line, line_end=line)]
    remediation = tmp_path / "preview.json"
    remediation.write_text(json.dumps(preview, ensure_ascii=False), encoding="utf-8")
    result = census(options, "--head", R5_HEAD, "--remediation", str(remediation))
    assert result.returncode == 1, result.stderr
    assert f"{count} locally validated remediation rows; 0 released" in result.stdout
    assert (BASIS_ERROR in result.stderr) == (count == 0)


R6_HEAD = "491e074427686376ab23d2cf36598d8cb1d4883b"
R6_REPORTS = (
    ("chanlun/review-results/code-review-issue550-spec-20260728.md", 7),
    ("chanlun/review-results/shadow-668-review3-20260729.md", 12),
    (".chanlun/diagnostics/acceptance4-4f-result.md", 3),
)
REVIEW_GUIDE = ".sandcastle/deepagents-pilot/EXTERNAL-REVIEW.md"


@pytest.mark.parametrize(("source", "line"), R6_REPORTS)
@pytest.mark.parametrize("placement", ["original", "copy", "body-only"])
def test_r7_rejects_real_review_and_diagnostic_results(history, options, source, line, placement):
    h = history
    raw = git_at_r3("show", f"{R6_HEAD}:{source}")
    if placement != "body-only":
        h.write(source, raw)
    h.gate()
    path = source
    if placement != "original":
        path = "spec/neutral-note.dat"
        h.write(path, raw)
        h.commit("Copy the historical bytes under a neutral name")
    check_basis(h, options, path, allowed=False, line=line)


@pytest.mark.parametrize("source", [REVIEW_GUIDE, "docs/adr/0024-total-ledger-convention.md"])
def test_r7_keeps_guides_and_decisions_that_mention_review_or_measurement(history, options, source):
    h = history
    h.write(source, git_at_r3("show", f"{R6_HEAD}:{source}"))
    h.gate()
    check_basis(h, options, source, allowed=True, line=3)


@pytest.mark.parametrize("source", [
    "review-results/old/material.dat",
    "chanlun/review-results/old/material.dat",
    "rust/.chanlun/review-results/old/material.dat",
    ".rtas/review-results/old/material.dat",
    "topological-computation/.chanlun/review-results/old/material.dat",
    ".chanlun/diagnostics/old/material.dat",
    ".chanlun/reports/old/material.dat",
    ".chanlun/agent-roster-example.md",
    "chanlun/agent-roster-example.md",
    ".chanlun/codex-local-verdict-r7.md",
    ".chanlun/codex-cli-dual-decide-result.md",
    ".chanlun/codex-strict-fix-acceptance4-2026-06-30.md",
    ".chanlun/at18/pregate-review.json",
    ".chanlun/at18/pregate/unattributed-window-audit.json",
    "analysis/reports/old/material.dat",
    "analysis/audit_logs/old/material.dat",
    "analysis/dual_settle_results/old/material.dat",
    "external/k4-soros-reports/old/material.dat",
    "STRICT-NEST-EXAMPLE-RESULT.md",
    "STRICT-NEST-EXAMPLE-CHECK.md",
])
def test_r7_tracks_first_parent_origin_across_archives(history, options, source):
    h = history
    raw = b"No report signature in the body.\n"
    h.write(source, raw)
    h.gate()
    check_basis(h, options, source, allowed=False)
    dest = "tests/fixtures/neutral.dat"
    h.remove(source)
    h.write(dest, raw)
    h.commit("Move an archive blob without proving it is a live input")
    check_basis(h, options, dest, allowed=False)


@pytest.mark.parametrize(("text", "allowed"), [
    (f"# 发布批次\n\n### 判定：BLOCK\n- Commit: {RUN_HEAD}\n", False),
    ("# 日常运行报告\n\n" + "\n" * 15 + "- **评审对象：候选分支**\n", False),
    ("# 回执操作指南\n\n~~~text\n- 评审对象：候选分支\n- 结论：FAIL\n~~~\n", True),
    ("# 验收合同\n\n未满足下列条件就返回 BLOCK，而不是 PASS。\n", True),
    ("# 评审操作指南\n\n先用 `git diff` 找到待审文件。\n", True),
    ("# 复审：第四轮\n\n## 结论：FAIL\n", False),
    ("# 独立评审\n\n结论：FAIL\n", False),
    ("# 评审操作指南\n\n结论：PASS 表示可合入。\n", True),
])
def test_r7_uses_report_preamble_not_mentions_or_fenced_examples(history, options, text, allowed):
    h = history
    path = "spec/material.md"
    h.write(path, text.encode())
    h.gate()
    check_basis(h, options, path, allowed=allowed)


JS_MODULES = b'const fs = require("node:fs"), path = require("node:path");\n'
DUAL_JS_LOADER = JS_MODULES + b"""
function readVectors() {
  const fixturePath = path.join(__dirname, "fixtures/vectors.json");
  return JSON.parse(fs.readFileSync(fixturePath, "utf8"));
}
function readUnits() {
  const fixturePath = path.join(__dirname, "fixtures/units.json");
  return JSON.parse(fs.readFileSync(fixturePath, "utf8"));
}
console.log(JSON.stringify({vectorKeys: Object.keys(readVectors()), units: readUnits()}));
"""


def migrate_fixtures(h, files, code, *, archive=ARCHIVE + "generic-bundle/inputs/", suffix=".cjs"):
    h.gate()
    for leaf, raw in files.items():
        h.write(archive + leaf, raw)
    h.commit("Fixture bytes first appear in the archive")
    for leaf, raw in files.items():
        (h.root / (archive + leaf)).rename(h.root.parent / leaf)
        h.write("tests/fixtures/" + leaf, raw)
    h.write("tests/input" + suffix, code)
    h.commit("Migrate fixture and commit consumer in F")


def test_r7_both_local_const_reads_are_basis_but_unread_alias_is_not(history, options):
    h = history
    raw = git_at_r3("show", f"{R6_HEAD}:{VECTOR}")
    migrate_fixtures(h, {"vectors.json": raw, "units.json": b'{"unit":"ticks"}\n'}, DUAL_JS_LOADER)
    h.write("tests/fixtures/alias.json", raw)
    h.commit("Same blob at an unread path")
    check_basis(h, options, "tests/fixtures/vectors.json", allowed=True, line=2)
    check_basis(h, options, "tests/fixtures/units.json", allowed=True)
    check_basis(h, options, "tests/fixtures/alias.json", allowed=False, line=2)


@pytest.mark.parametrize(("code", "allowed"), [
    ('''let fixturePath = path.join(__dirname, "fixtures", "vectors.json")
{ const fixturePath = null; }
fs.readFileSync(fixturePath, "utf8")''', True),
    ('''let fixturePath = path.join(__dirname, "other.json");
{ fixturePath = path.join(__dirname, "fixtures", "vectors.json",); }
fs.readFileSync(fixturePath);''', True),
    ('''let fixturePath = path.join(__dirname, "fixtures/vectors.json");
fixturePath == other; fixturePath === other; fixturePath != other; fixturePath !== other;
fs.readFileSync(fixturePath);''', True),
    ('''const fixturePath = path.join(__dirname, "fixtures/vectors.json");
{ const fixturePath = String("elsewhere"); fs.readFileSync(fixturePath); }''', False),
    ('''const fixturePath = path.join(__dirname, "fixtures/vectors.json");
{ fs.readFileSync(fixturePath); const fixturePath = String("elsewhere"); }''', False),
    ('''fs.readFileSync(fixturePath);
const fixturePath = path.join(__dirname, "fixtures/vectors.json");''', False),
    ('''let fixturePath = path.join(__dirname, "fixtures/vectors.json");
{ fixturePath = String("elsewhere"); }
fs.readFileSync(fixturePath);''', False),
    ('''let fixturePath = path.join(__dirname, "fixtures/vectors.json");
let value = null, second = fs.readFileSync(fixturePath);
''', True),
    ('''let fixturePath = path.join(__dirname, "fixtures/vectors.json");
{ let dummy = {}, fixturePath = null; fs.readFileSync(fixturePath); }''', False),
    ('''const fixturePath = path.join(__dirname, "fixtures/vectors.json");
{ const fs = require("./not-fs"); fs.readFileSync(fixturePath); }''', False),
    ('''{ const path = require("./not-path"); fs.readFileSync(path.join(__dirname, "fixtures/vectors.json")); }''',
     False),
    ('''const fixturePath = path.join(__dirname, "fixtures/vectors.json");
fs.readFileSync(fixturePath + ".other");''', False),
    ('''const fixturePath: string = path.join(__dirname, "fixtures/vectors.json");
fs.readFileSync(fixturePath);''', True),
    ('''const fixturePath = path.join(__dirname, "fixtures/vectors.json");
function run(fs) { fs.readFileSync(fixturePath); }''', False),
    ('''let fixturePath = path.join(__dirname, "fixtures/vectors.json");
fixturePath += ".other";
fs.readFileSync(fixturePath);''', False),
], ids=["scope-pop-asi", "rebind", "comparison", "shadow", "nested-tdz", "tdz", "invalidate",
        "read-in-declaration", "comma-shadow", "fake-fs", "fake-path", "not-exact-argument",
        "ts-type", "parameter-shadow", "compound-assignment"])
def test_r7_checks_js_bindings_at_the_read_position(history, options, code, allowed):
    h = history
    migrate_fixtures(h, {"vectors.json": FEE_RULE.encode()}, JS_MODULES + code.encode(), suffix=".ts")
    check_basis(h, options, "tests/fixtures/vectors.json", allowed=allowed)


def test_r7_cannot_promote_result_archive_via_live_reader(history, options):
    h = history
    migrate_fixtures(h, {"vectors.json": FEE_RULE.encode()}, JS_LOADER, archive=".chanlun/diagnostics/old/")
    check_basis(h, options, "tests/fixtures/vectors.json", allowed=False)


R7_HEAD = "bf1b9dcbb5cb46330f2f3877e70182c6ca3a4477"
R8_REPORTS = (
    ("analysis/opus_code_audit.md", 25),
    ("docs/twelve_contradictions_fix_report.md", 13),
    ("docs/architecture/opus48_audit_report.md", 19),
    ("docs/architecture/openclaw-security-audit.md", 11),
    ("docs/rec_t_8x3_l3_verification.md", 13),
    ("docs/theta-v0-l2-results-v0.md", 11),
    ("formal/Tlayers/SPIRAL_RESULT.md", 3),
    ("analysis/unn_stream_verification.md", 8),
    ("analysis/urs_complete_system_verdict.md", 11),
    ("analysis/1s_a0_nest_coverage_results.md", 13),
    (".chanlun/downstream_resolution_312.md", 10),
    ("analysis/hk_china_index_backtest_hstech.md", 11),
    ("analysis/v2_selloff_fix_robustness.md", 9),
)


@pytest.mark.parametrize(("source", "line"), R8_REPORTS)
def test_r8_report_original_and_neutral_copy_are_not_basis(history, options, source, line):
    raw = git_at_r3("show", f"{R7_HEAD}:{source}")
    copy = "spec/neutral-note.md"
    history.write(source, raw)
    history.write(copy, raw)
    history.gate()
    for path in (source, copy):
        check_basis(history, options, path, allowed=False, line=line)


@pytest.mark.parametrize(("text", "allowed"), [
    ("# 接口独审\n\n>> - **评审对象**：候选分支\n", False),
    ("# 验证报告\n\n" + "\n" * 28 + "> ## 1. 核心结论\n> 修复项 = 0\n", False),
    ("# 实测终判\n\n| 断言 | **Status** |\n| :--- | ---: |\n| A | ✅ |\n", False),
    ("# 审计操作指南\n\n| 字段 | 判定 |\n| --- | --- |\n| 模板 | PASS |\n", True),
    ("# ADR 0999：审计报告在门禁中的处置\n\n> **审计范围**：所有客户端\n", True),
    ("# Board review report\n\n> ```md\n> - Verdict: REJECT\n> ```\n", True),
    ("# 独审报告\n\n> ```md\n> - 字段：示例\n> ```\n\n> **结论**：有保留通过\n", False),
])
def test_r8_report_preamble_distinguishes_record_from_example(history, options, text, allowed):
    path = "spec/material.md"
    history.write(path, text.encode())
    history.gate()
    check_basis(history, options, path, allowed=allowed)


R8_JS_CASES = [
    ("var-block", '''
function getVectors() {
  { var fixturePath = path.join(__dirname, "fixtures/vectors.json"); }
  var fixturePath;
  return JSON.parse(fs.readFileSync(fixturePath, "utf8"));
}
console.log(Object.keys(getVectors()));
''', {"vectors.json"}),
    ("branch-two-calls", '''
function load(wantVector) {
  let fixturePath;
  if (wantVector) { fixturePath = path.join(__dirname, "fixtures/vectors.json"); }
  else { fixturePath = path.resolve(__dirname, "fixtures", "units.json"); }
  return JSON.parse(fs.readFileSync(fixturePath, "utf8"));
}
console.log(Object.keys(load(true)), load(false).unit);
''', {"vectors.json", "units.json"}),
    ("if-single-arm", '''
function load(wantVector) {
  let p = path.join(__dirname, "fixtures/units.json");
  if (wantVector) p = path.join(__dirname, "fixtures/vectors.json");
  return fs.readFileSync(p).length;
}
console.log(load(true), load(false));
''', {"vectors.json", "units.json"}),
    ("ternary", '''
const load = (wantVector) => {
  return fs.readFileSync(wantVector
    ? path.join(__dirname, "fixtures", "vectors.json")
    : path.resolve(__dirname, "fixtures", "units.json")).length;
};
console.log(load(true), load(false));
''', {"vectors.json", "units.json"}),
    ("static-truth", '''
let p = path.join(__dirname, "fixtures/units.json");
if (false) fs.readFileSync(p);
if (0.0) fs.readFileSync(p);
if ("") fs.readFileSync(p);
if (null) fs.readFileSync(p);
if (undefined) fs.readFileSync(p);
if ("yes") { p = path.resolve(__dirname, "fixtures", "vectors.json"); }
else fs.readFileSync(path.join(__dirname, "fixtures/units.json"));
fs.readFileSync(-0x2 ? p : path.join(__dirname, "fixtures/units.json"));
''', {"vectors.json"}),
    ("switch", '''
function load(choice) {
  var p;
  switch (choice) {
    case 0: p = path.join(__dirname, "fixtures/vectors.json"); break;
    default: p = path.join(__dirname, "fixtures/units.json");
  }
  return fs.readFileSync(p).length;
}
console.log(load(0), load(1));
''', {"vectors.json", "units.json"}),
    ("switch-static", '''
let p = path.join(__dirname, "fixtures/units.json");
switch (0) {
    case 1: fs.readFileSync(p); break;
    case 0: p = path.join(__dirname, "fixtures/vectors.json"); break;
    default: fs.readFileSync(p);
}
fs.readFileSync(p);
''', {"vectors.json"}),
    ("try-join", '''
function load(stop) {
  let p;
  try {
    p = path.join(__dirname, "fixtures/vectors.json");
    if (stop) throw Error("test");
  } catch { p = path.join(__dirname, "fixtures/units.json"); }
  finally { if (false) p = null; }
  return fs.readFileSync(p).length;
}
console.log(load(true), load(false));
''', {"vectors.json", "units.json"}),
    ("finally-overwrite", '''
let p;
try { p = path.join(__dirname, "fixtures/units.json"); }
catch { p = path.join(__dirname, "fixtures/units.json"); }
finally { p = path.join(__dirname, "fixtures/vectors.json"); }
fs.readFileSync(p);
''', {"vectors.json"}),
    ("function-frame-shadow", '''
const p = path.join(__dirname, "fixtures/vectors.json");
function local() {
  try { fs.readFileSync(p); } catch {}
  { var p = null; }
}
const anonymous = function(fs) { fs.readFileSync(p); };
const object = { arrow: (fs) => { fs.readFileSync(p); }, method(fs) { fs.readFileSync(p); } };
class Holder { read(fs) { fs.readFileSync(p); } }
const fake = { readFileSync: () => "fake" };
local(); anonymous(fake); object.arrow(fake); object.method(fake); new Holder().read(fake);
''', set()),
    ("block-and-loop", '''
let p = path.join(__dirname, "fixtures/vectors.json");
for (let p = null; false;) fs.readFileSync(p);
while (false) p = null;
{ const p = path.join(__dirname, "fixtures/units.json"); fs.readFileSync(p); }
fs.readFileSync(p);
''', {"vectors.json", "units.json"}),
    ("unused", '''
const unused = path.join(__dirname, "fixtures/vectors.json");
// fs.readFileSync(unused);
const text = "fs.readFileSync(unused)";
''', set()),
]


@pytest.mark.parametrize(("case", "code", "loaded"), R8_JS_CASES, ids=[case[0] for case in R8_JS_CASES])
def test_r8_tracks_paths_at_reads_across_control_flow(history, options, case, code, loaded):
    raw = git_at_r3("show", f"{R7_HEAD}:{VECTOR}")
    fixtures = {"vectors.json": raw, "units.json": b'{"unit":"ticks"}\n'}
    migrate_fixtures(history, fixtures, JS_MODULES + code.encode())
    history.write("tests/fixtures/alias.json", raw)
    history.commit("Retain an unread same-blob alias")
    for leaf in (*fixtures, "alias.json"):
        check_basis(history, options, "tests/fixtures/" + leaf, allowed=leaf in loaded)


@pytest.mark.parametrize("path", [
    "docs/backtest-protocol-v0.md",
    "docs/spec/tightness_selection_l2.md",
    "docs/chanlun/external-consults/pi-theta-backtest-workorder-20260701.md",
    ".chanlun/proofs/economic-positive-impl-design.md",
    "analysis/organic_fugue_v2_design.md",
])
def test_r8_keeps_original_plans_despite_real_run_references(history, options, path):
    history.write(path, git_at_r3("show", f"{R7_HEAD}:{path}"))
    history.gate()
    check_basis(history, options, path, allowed=True)
