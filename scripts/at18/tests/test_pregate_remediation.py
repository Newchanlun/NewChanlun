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
PROOF = "docs/adr/0008-bsp-bridge-object-and-structural-key-v2.md"
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
        basis = "docs/adr/9999-proof-link.md"
        (h.root / basis).symlink_to(Path(PROOF).name)
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
        "basis-invalid-path": {"path": "./" + PROOF},
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
        target.symlink_to("../../" + PROOF)
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
    ("docs/spec/plain.md", "费率表：每百元三分，取整到分。\n", True),
    ("docs/spec/summary.md", "费率表：每百元三分，取整到分。\n", True),
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
    ("docs/spec/receipt-format.md", f"# 回执的格式\n\n```text\nHead: {RUN_HEAD}\nVerdict: PASS\n```\n", True),
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
    ("docs/spec/settlement.md", "## 费用计算规则" + SETTLEMENT_RULE, 3),
    ("docs/spec/settlement.md", SUMMARY_TITLE + SETTLEMENT_RULE, 3),
    ("docs/spec/settlement.md", SUMMARY_TITLE + "\n\n结论：**PASS**" + SETTLEMENT_RULE, 5),
    ("spec/fee-rounding.json", FEE_RULE, 2),
    ("spec/at18-report.json", FEE_RULE, 2),
    ("spec/at18-input-bundle.json", FEE_RULE, 2),
    ("spec/at18-verification.json", FEE_RULE, 2),
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
    path = source if mode == "archive" else "library/material" + Path(source).suffix
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
    path = "docs/spec/copied-receipt.md"
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


def check_basis(history, options, path, *, allowed, line=1, line_end=None):
    row = history.row(basis=path)
    row["verification_basis"][0].update(line_start=line, line_end=line if line_end is None else line_end)
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
        path = "docs/spec/neutral-note" + Path(source).suffix
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
    path = "spec/neutral-note.json"
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
    path = "docs/spec/neutral-note.md"
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
    path = "docs/spec/interface.md"
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
    active = "docs/spec/" + leaf
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
    dest = "spec/promoted.json"
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
    active = "docs/spec/neutral-note.md"
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
old_report = None
if deleted_report:
    require(not any(entry.blob == deleted_report for entry in tree.values()), "old report still present")
    tree["docs/spec/retained-note.md"] = c.Entry("100644", "blob", deleted_report)
    old_report = outcome("docs/spec/retained-note.md", 1)
print(json.dumps(dict(live=live, reviews=[outcome(p, 2) for p in reviews],
                      slices=[outcome(p, 2) for p in slices], old_report=old_report)))
"""


def test_real_history_separates_live_inputs_from_deleted_reports(options):
    migration = "ddacd324ba36dd70d0a40dc5f496d281572be8c6"
    package = ARCHIVE + "issue1394-content-v3-20260916/"
    old = package + "inputs/content-format-vectors.json"
    pointer = package + "FIXTURE-MOVED.md"
    target = REAL_LIVE_BASES[3][0]
    diff = git_at_r3("diff-tree", "-r", "--no-commit-id", "--no-renames", "--no-abbrev",
                     "--raw", migration + "^1", migration, "--", old, target, pointer)
    entries = dict((path.decode(), header.split()) for header, path in (line.split(b"\t") for line in diff.splitlines()))
    assert entries[old][-1] == b"D" and entries[target][-1] == entries[pointer][-1] == b"A"
    assert entries[old][2] == entries[target][3]
    assert entries[target][3].decode() == git_at_r3("rev-parse", f"{R4_HEAD}:{target}").decode().strip()
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
    neutral = ("library/material.md" if move == "body" else "docs/spec/retained-note" + Path(source).suffix)
    path = neutral if move == "body" else source
    h.write(path, raw)
    h.gate()
    if move in ("copy", "move"):
        path = neutral
        if move == "move":
            h.remove(source)
        h.write(path, raw)
        h.commit("Reuse the genuine archive bytes under a neutral name")
        assert h.blob("HEAD", path) == git_at_r3("rev-parse", f"{ref}:{source}").decode().strip()
    check_basis(h, options, path, allowed=False, line=line)


MIGRATION_PACKAGE = ARCHIVE + "generic-bundle/"
MIGRATION_TARGET = "tests/fixtures/vectors.json"
MIGRATION_POINTER = MIGRATION_PACKAGE + "FIXTURE-MOVED.md"


@pytest.mark.parametrize(("scenario", "allowed"), [
    ("atomic", True), ("nested-pointer", True), ("plain-path-tokens", True),
    ("unlisted-alias", False), ("missing-pointer", False), ("late-pointer", False),
    ("deleted-pointer", False), ("rewritten-pointer", False), ("symlink-pointer", False),
    ("wrong-package", False), ("wrong-old-path", False), ("wrong-new-path", False),
    ("prefixed-path", False), ("suffixed-path", False), ("pointer-is-report", False),
    ("retained-archive", False), ("historical-output-token", False), ("output-name", False),
    ("same-commit-origin-alias", False), ("split-move", False), ("preexisting-target", False),
    ("target-in-archive", False), ("target-in-results", False),
    ("report-body", False), ("json-report-body", False),
])
def test_condition_c_requires_atomic_pointer_bound_migration(history, options, scenario, allowed):
    h = history
    leaf = "inputs/VECTOR-RESULTS.json" if scenario == "output-name" else "inputs/vectors.json"
    archived = MIGRATION_PACKAGE + leaf
    target, pointer = MIGRATION_TARGET, MIGRATION_POINTER
    if scenario == "target-in-archive":
        target = ARCHIVE + "another-bundle/vectors.json"
    if scenario == "target-in-results":
        target = ".chanlun/diagnostics/vectors.json"
    if scenario == "wrong-package":
        pointer = ARCHIVE + "another-bundle/FIXTURE-MOVED.md"
    if scenario == "nested-pointer":
        pointer = MIGRATION_PACKAGE + "inputs/FIXTURE-MOVED.md"
        leaf = "vectors.json"

    raw = FEE_RULE.encode()
    if scenario == "report-body":
        raw = git_at_r3("show", f"{R5_HEAD}:{DURABILITY}")
    if scenario == "json-report-body":
        raw = b'{"schema_version":"at18-report/1"}'

    h.gate()
    h.write(archived, raw)
    if scenario == "same-commit-origin-alias":
        h.write("spec/origin-alias.json", raw)
    old_output = MIGRATION_PACKAGE + "verify-round/vectors.json"
    if scenario == "historical-output-token":
        h.write(old_output, raw)
    h.commit("Archive fixture")
    if scenario == "historical-output-token":
        (h.root / old_output).rename(h.root.parent / "old-output")
        h.commit("Remove older output copy")
    if scenario == "preexisting-target":
        h.write(target, raw)
        h.commit("Copy the bytes before the archive is deleted")
    h.remove(archived)
    if scenario == "split-move":
        h.commit("Remove archive in an earlier commit")
    h.write(target, raw)
    if scenario == "retained-archive":
        h.write(archived, raw)
    if scenario == "unlisted-alias":
        h.write("spec/retained-note.json", raw)

    old = "other/vectors.json" if scenario == "wrong-old-path" else leaf
    new = {
        "wrong-new-path": "other/vectors.json", "prefixed-path": "prefix/" + target,
        "suffixed-path": target + ".old",
    }.get(scenario, target)
    declaration = f"`{old}` 原样迁到 `{new}`。\n".encode()
    if scenario == "plain-path-tokens":
        declaration = f"{old} → {new}。\n".encode()
    if scenario == "pointer-is-report":
        declaration = f"Reviewed head: {RUN_HEAD}\nVerdict: PASS\n".encode() + declaration
    if scenario not in ("missing-pointer", "late-pointer", "symlink-pointer"):
        h.write(pointer, declaration)
    if scenario == "symlink-pointer":
        h.write("pointer.md", declaration)
        (h.root / pointer).symlink_to("../../../pointer.md")
    h.commit("Integrate migration")
    if scenario == "late-pointer":
        h.write(pointer, declaration)
        h.commit("Add a pointer after integration")
    if scenario == "deleted-pointer":
        (h.root / pointer).rename(h.root.parent / "old-pointer")
        h.commit("Delete the pointer before F")
    if scenario == "rewritten-pointer":
        h.write(pointer, b"Moved (no precise destination).\n")
        h.commit("Remove the migration declaration from the pointer")

    check_basis(h, options, target, allowed=allowed or scenario == "unlisted-alias")
    if scenario == "unlisted-alias":
        check_basis(h, options, "spec/retained-note.json", allowed=False)
    if scenario == "atomic":
        check_basis(h, options, pointer, allowed=False)


def test_condition_c_cannot_promote_into_remediation_path(history, options):
    h = history
    h.gate()
    old = MIGRATION_PACKAGE + "inputs/vectors.json"
    h.write(old, FEE_RULE.encode())
    h.commit("Archive fixture")
    h.remove(old)
    h.write(ARTIFACT, FEE_RULE.encode())
    h.write(MIGRATION_POINTER, f"`inputs/vectors.json` → `{ARTIFACT}`\n".encode())
    h.commit("Attempt migration into the remediation path")
    result = subprocess.check_output(
        [sys.executable, *options, "-c", ORIGIN_PROBE, str(PREGATE), h.git("rev-parse", "HEAD"),
         "", PUBLICATION, json.dumps([(ARTIFACT, 1)])],
        cwd=h.root, text=True,
    )
    assert json.loads(result)["live"][ARTIFACT] == BASIS_ERROR


@pytest.mark.parametrize(("at_migration", "at_final", "accepted"), [
    ("matched", "matched", 2), ("crossed", "crossed", 0),
    ("crossed", "matched", 0), ("matched", "crossed", 0),
    *((style, style, 2) for style in (
        "table", "bullets", "wrapped", "comma", "ascii-comma", "semicolon",
        "chinese-semicolon", "period", "hardbreak", "backslash",
    )),
    *((style, style, 0) for style in (
        "two-origins", "comma-origins", "cross-clauses", "wrong-aside",
    )),
])
def test_condition_c_keeps_both_ends_of_each_pair(history, options, at_migration, at_final, accepted):
    h = history
    names = ("amber.json", "blue.json")
    old = [f"inputs/{name}" for name in names]
    new = [f"testdata/{name}" for name in names]
    payloads = [b'{"fixture":1}\n', b'{"fixture":2}\n']

    def pointer(style):
        destinations = new[::-1] if style in ("crossed", "wrong-aside") else new
        pairs = [(f"`{src}`", f"`{dst}`") for src, dst in zip(old, destinations)]
        arrows = [f"{src} → {dst}" for src, dst in pairs]
        separators = {
            "comma": "，", "ascii-comma": ", ", "semicolon": "; ", "chinese-semicolon": "；",
            "period": "。", "hardbreak": "  \n", "backslash": chr(92) + "\n",
        }
        if style in separators:
            text = separators[style].join(arrows) + "。"
        elif style == "table":
            text = "|旧路径|方向|新路径|\n|---|---|---|\n" + "\n".join(
                f"|{src}|→|{dst}|" for src, dst in pairs)
        elif style == "bullets":
            text = "\n".join(f"- {src} => {dst}" for src, dst in pairs)
        elif style == "wrapped":
            text = "\n".join(f"{src} migrated to\n{dst}；" for src, dst in pairs)
        elif style == "two-origins":
            text = f"{pairs[0][0]} 和 {arrows[1]}。"
        elif style == "comma-origins":
            text = f"{pairs[0][0]}，{arrows[1]}。"
        elif style == "cross-clauses":
            text = f"{pairs[0][0]} 单列；另迁到 {pairs[0][1]}。"
        elif style == "wrong-aside":
            text = "\n".join(f"{arrow}。参考目录另有 {dst}。" for arrow, dst in zip(arrows, new))
        else:
            text = "\n".join(f"{src} moved to {dst}." for src, dst in pairs)
        return (text + "\n").encode()

    h.gate()
    for src, raw in zip(old, payloads):
        h.write(MIGRATION_PACKAGE + src, raw)
    h.commit("Archive distinct fixtures")
    for (src, dst), raw in zip(zip(old, new), payloads):
        h.remove(MIGRATION_PACKAGE + src)
        h.write(dst, raw)
    h.write(MIGRATION_POINTER, pointer(at_migration))
    h.commit("Atomically move both fixtures")
    if at_final != at_migration:
        h.write(MIGRATION_POINTER, pointer(at_final))
        h.commit("Revise the pointer after the move")
    for path in new:
        check_basis(h, options, path, allowed=(accepted == 2))


@pytest.mark.parametrize(("declaration", "allowed"), [
    ("`vectors.json` migrated to\n`tests/fixtures/vectors.json`", True),
    ("| vectors.json | => | tests/fixtures/vectors.json |", True),
    ("`orphan.json`。`vectors.json` moved to `tests/fixtures/vectors.json`", True),
    ("`vectors.json` 和 `other.json` 迁至 `tests/fixtures/vectors.json`", False),
    ("`vectors.json` renamed to `other.json` / `tests/fixtures/vectors.json`", False),
    ("`vectors.json` 未迁至 `tests/fixtures/vectors.json`", False),
    ("`vectors.json` mentioned; moved to `tests/fixtures/vectors.json`", False),
    ("`vectors.json` moved to\n\n`tests/fixtures/vectors.json`", False),
    ("- `vectors.json` moved to\n- `tests/fixtures/vectors.json`", False),
    ("| `vectors.json` moved to |\n| `tests/fixtures/vectors.json` |", False),
    ("`tests/fixtures/vectors.json` -> `vectors.json`", False),
])
def test_condition_c_migration_declaration_is_one_unambiguous_clause(history, options, declaration, allowed):
    h = history
    h.gate()
    source = MIGRATION_PACKAGE + "vectors.json"
    h.write(source, b'{"fixture":1}\n')
    h.commit("Archive fixture")
    h.remove(source)
    h.write(MIGRATION_TARGET, b'{"fixture":1}\n')
    h.write(MIGRATION_POINTER, declaration.encode())
    h.commit("Move fixture with declaration")
    check_basis(h, options, MIGRATION_TARGET, allowed=allowed)


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
R10_REPORTS = (
    ("analysis/fugue_version_i_results.md", 13),
    ("analysis/av_recursive_5min_qqq.md", 9),
    ("analysis/k4_config_transition_matrix_1min_6d.md", 20),
    ("analysis/k4_config_transition_matrix_1min_6d_dx.md", 24),
    ("analysis/sip_cross_venue_cluster_probe_20260818.md", 8),
    ("analysis/sip_dedup_key_calibration_record.md", 12),
    ("analysis/k4_hierarchical_gamma.md", 28),
    ("analysis/recursive_position_experiment.md", 150),
    ("analysis/residual_anchor_sensitivity.md", 20),
    ("analysis/sip_consolidated_pipeline_raw_disposition.md", 32),
    ("analysis/reports/btc_short_eats_long.md", 10),
    ("analysis/reports/t_vs_v3_shortless_report.md", 12),
    ("analysis/fugue_v3_short_exit_failure_critique.md", 19),
    ("analysis/organic_fugue_rust_compiler_contradictions.md", 77),
    ("docs/recover_failure_reasoning.md", 29),
    ("docs/session_handoff_2026-06-20_t_redesign_and_falsification.md", 22),
    ("docs/chanlun/external-consults/parity-alternation-question-20260701.md", 24),
    ("docs/chanlun/external-consults/sigma-higher-level-interaction-question-20260701.md", 20),
    ("docs/chanlun/external-consults/how-to-extract-alpha-question-20260701.md", 10),
    ("docs/recursive_t_deadlock_escalation.md", 82),
    ("docs/nautilustrader_research.md", 354),
)
R9_HEAD = "5d485818f2e51b7c00993034354b62d99b1d4ab6"


def test_r12_inference_layer_fee_provenance_is_not_basis(history, options):
    path = "analysis/data_cache/venue_fee_provenance.md"
    history.write(path, git_at_r3("show", f"{R9_HEAD}:{path}"))
    history.gate()
    check_basis(history, options, path, allowed=False, line=13)


@pytest.mark.parametrize(("source", "line"), R10_REPORTS)
@pytest.mark.parametrize("placement", ("original", "neutral"))
def test_r10_real_measured_and_delivery_reports_are_not_basis(history, options, source, line, placement):
    dest = source if placement == "original" else "spec/material.md"
    history.write(dest, git_at_r3("show", f"{R9_HEAD}:{source}"))
    history.gate()
    check_basis(history, options, dest, allowed=False, line=line)


R11_HEAD = "5093b91a8728d1a48cfe12df4bcf7fcde5d23d83"


@pytest.mark.parametrize(("source", "lines"), [
    (".chanlun/genealogy/settled/245-divergence-structure-analysis.md", (41,)),
    (".chanlun/genealogy/settled/247-real-data-multi-tf-validation.md", (26,)),
    (".chanlun/genealogy/settled/251-divergence-comparison-60min.md", (19,)),
    (".chanlun/genealogy/settled/279-oq5-caliber-a-verification.md", (41, 61, 70)),
    ("analysis/trend_counter_segment_research.md", (115, 133, 150, 154, 180)),
    ("analysis/recursive_regularization_theory.md", (171, 186, 194, 195)),
    ("analysis/sip_consolidated_dedup_rule_draft.md", (103, 117, 121, 160)),
    ("analysis/options_short_fixed_point_research.md", (815, 832, 1013, 1014, 1093)),
])
def test_r12_excludes_inference_layer_independently_of_the_referenced_line(history, options, source, lines):
    raw = git_at_r3("show", f"{R11_HEAD}:{source}")
    paths = (source, "library/material.md")
    for path in paths:
        history.write(path, raw)
    history.gate()
    for path in paths:
        for line in lines:
            check_basis(history, options, path, allowed=False, line=line)


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
    dest = "tests/fixtures/neutral.py"
    h.remove(source)
    h.write(dest, raw)
    h.commit("Move an archive blob without proving it is a live input")
    check_basis(h, options, dest, allowed=False)


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


R8_HEAD = "09b29405edf91f7a30a085b182758c93d82e370d"
R9_REPORTS = (
    ("analysis/engine_c_segment_fix.md", 27),
    ("analysis/theta_relative_full_revalidation.md", 20),
    ("analysis/fugue_adaptive_ph_backtest_1min.md", 22),
    ("analysis/urs_phase0_recursive_confirm_results.md", 30),
    ("analysis/session_trading_analysis_comprehensive.md", 17),
    ("analysis/brn_upleg_settle.md", 28),
    ("analysis/mos_analysis.md", 13),
    ("analysis/qqq_soxx_settle.md", 26),
    ("analysis/bsp_engine_sublevel_fix.md", 14),
    ("docs/memory_snapshot/project_c_segment_fix.md", 48),
    ("docs/memory_snapshot/project_alpha_diagnosis.md", 18),
    ("docs/memory_snapshot/project_session2_organic_fugue.md", 13),
)


@pytest.mark.parametrize(("source", "line"), R9_REPORTS)
def test_r9_run_results_rejected_at_original_and_neutral_path(history, options, source, line):
    raw = git_at_r3("show", f"{R8_HEAD}:{source}")
    paths = (source, "spec/neutral-note.md")
    for path in paths:
        history.write(path, raw)
    history.gate()
    for path in paths:
        check_basis(history, options, path, allowed=False, line=line)


@pytest.mark.parametrize(("path", "allowed"), [
    (path, True) for path in (
        "CONTEXT.md", "AGENTS.md", "README.md", "SECURITY.md", "docs/ROADMAP.md",
        "docs/adr/README.md", "docs/adr/0012-inference-layer-document-naming.md",
        ".chanlun/definitions/beichi.md", "docs/agents/nested/guide.md", "docs/spec/nested/contract.md",
        "docs/chanlun/text/blog/INDEX.md", "docs/chanlun/text/chan99/INDEX.md",
        "spec/theorems/definitions.md", ".chanlun/at18/pregate/README.md",
        ".chanlun/at18/pregate/scope-basis.md", ".sandcastle/deepagents-pilot/EXTERNAL-REVIEW.md",
        "s_session/README.md", "rust/a/ORACLE.md", "scripts/a/README.md", "formal/a/ORACLE.md",
        "tests/a/README.md", "src/a/README.md", "frontend/a/README.md",
        "trading_system/a/README.md", ".chanlun/at18/a/ORACLE.md",
    )
] + [
    (path, False) for path in (
        "docs/adr/unratified.md", "docs/adr/draft/0042-nested.md", ".chanlun/definitions/draft/nested.md",
        "docs/specish/contract.md", "docs/chanlun/text/mindmaps/INDEX.md",
        "docs/chanlun/text/blog/nested/INDEX.md", "spec/theorems/nested/definitions.md",
        "analysis/p3_design.md", ".chanlun/genealogy/material.md", "docs/architecture/README.md",
        "docs/memory_snapshot/README.md", "docs/chanlun/external-consults/README.md",
        "docs/three_phase_unified_design.md", "STRICT-NEST-EXAMPLE-RESULT.md",
        ".chanlun/tower-construction/tower_continuous_axis_unify.md", "formal/Tlayers/SPIRAL_RESULT.md",
        "library/material-000.md", "spec/plain.md", "spec/copied-report.md", "s_session/named-contract.md",
        *(".sandcastle/worker/" + segment + "/README.md" for segment in (
            "runs", "logs", "reports", "review-results", "diagnostics", "output", "outputs", "evidence",
        )),
    )
])
def test_r12_markdown_path_is_the_eligibility_boundary(history, options, path, allowed):
    # 同一正文与 Git blob，路径是唯一变量；不猜常见标题、YAML 或结论字段。
    history.write(path, RENDERED_SUMMARY.encode())
    history.gate()
    check_basis(history, options, path, allowed=allowed)


@pytest.mark.parametrize("path", [
    "analysis/p3_random_gate_control.py", "rust/src/example.rs", "src/code.ts", "scripts/code.mts",
    "frontend/view.tsx", "src/runtime.js", "scripts/tool.mjs", "scripts/tool.cjs", "tests/drive.sh",
    ".github/workflows/job.yml", ".github/config.yaml", "rust/Cargo.toml", "formal/Origin.lean",
    "scripts/query.sql", "scripts/tool.cfg", "rust/pytest.ini", "s_session/Dockerfile", "Makefile",
])
def test_r12_accepts_code_config_and_proofs(history, options, path):
    history.write(path, b"# fixture\n")
    history.gate()
    check_basis(history, options, path, allowed=True)


@pytest.mark.parametrize("suffix", ["txt", "log", "out", "err", "csv", "tsv", "html", "rst", "dat"])
def test_r12_rejects_report_renamed_to_free_text(history, options, suffix):
    path = "docs/spec/material." + suffix
    history.write(path, RENDERED_SUMMARY.encode())
    history.gate()
    check_basis(history, options, path, allowed=False)


@pytest.mark.parametrize(("path", "raw", "allowed"), [
    ("fixtures/results.json", b'{"result": "expected"}', True),
    ("fixtures/results.jsonl", b'{"id":1}\n{"id":2}\n', True),
    ("fixtures/results.jsonl", b'{"id":1}\n{"schema_version":"at18-report/1"}\n', False),
    ("fixtures/results.json", b'historical review prose\n', False),
    ("fixtures/results.jsonl", b'{"id":1}\nhistorical review prose\n', False),
    ("docs/spec/example.md", b'{"schema_version":"at18-report/1"}\n', False),
    ("tests/fixture.yaml", b'{"schema_version":"at18-report/1"}\n', False),
    *((path, b'{"result": "expected"}', False) for path in (
        "analysis/fixture.json", ".chanlun/genealogy/fixture.json", ".chanlun/diagnostics/fixture.json",
        "docs/memory_snapshot/fixture.json", "docs/reports/fixture.json", "reports/fixture.json",
        ".sandcastle/pilot/logs/fixture.jsonl", "tests/evidence/fixture.json",
    )),
])
def test_r12_structured_data_requires_eligible_location_and_no_artifact_envelope(history, options, path, raw, allowed):
    history.write(path, raw)
    history.gate()
    check_basis(history, options, path, allowed=allowed)


@pytest.mark.parametrize(("m", "f", "accepted"), [
    ("two", "two", ()), ("two", "one", ()), ("one", "two", ()),
    ("reverse", "one", ()), ("one", "reverse", ()),
    ("repeat", "repeat", (0,)), ("distinct", "distinct", (0, 1)),
    ("nested", "one", ()), ("one", "nested", ()), ("nested-repeat", "one", (0,)),
])
def test_r13_condition_c_requires_one_to_one_mapping(history, options, m, f, accepted):
    h = history
    old = ("inputs/amber.json", "inputs/blue.json")
    new = ("testdata/amber.json", "testdata/blue.json")
    payloads = (b'{"input":"amber"}\n', b'{"input":"blue"}\n')
    h.gate()
    for path, raw in zip(old, payloads):
        h.write(MIGRATION_PACKAGE + path, raw)
    h.commit("Archive both fixtures")
    for path in old:
        (h.root / (MIGRATION_PACKAGE + path)).rename(h.root.parent / Path(path).name)
    h.write(new[0], payloads[0])
    h.write(new[1], payloads[1] if m == "distinct" else payloads[0])

    nested = MIGRATION_PACKAGE + "inputs/FIXTURE-MOVED.md"

    def write_declarations(style):
        pairs = [(old[0], new[0])]
        if extra := {"two": (old[0], new[1]), "reverse": (old[1], new[0]),
                     "repeat": pairs[0], "distinct": (old[1], new[1])}.get(style):
            pairs.append(extra)
        h.write(MIGRATION_POINTER, "".join(f"`{src}` → `{dst}`。\n" for src, dst in pairs).encode())
        if style in ("nested", "nested-repeat"):
            target = new[1] if style == "nested" else new[0]
            h.write(nested, f"`amber.json` → `{target}`。\n".encode())
        elif (h.root / nested).exists():
            (h.root / nested).rename(h.root.parent / "m-only-pointer.md")

    write_declarations(m)
    h.commit("Move both fixtures and declare their targets")
    if f != m:
        write_declarations(f)
        h.commit("Change declarations at F")
    for i, path in enumerate(new):
        check_basis(h, options, path, allowed=i in accepted)


R12_HEAD = "38d0000a7c1065180c75909a506b1f22066c40c4"
SWIFT_FIXTURES = ".sandcastle/approval-signing/tests/fixtures/swift/"


@pytest.mark.parametrize(("source", "start", "end"), [
    ("experiments/discrete_morse/dm1_results.json", 46, 46),
    ("experiments/discrete_morse/dm2_results.json", 2, 8),
    *((SWIFT_FIXTURES + path, 1, 1) for path in (
        "receipt-1-approve.json", "receipt-2-reject.json",
        "authority/0123456789abcdef0123456789abcdef/1.json",
        "authority/0123456789abcdef0123456789abcdef/2.json",
    )),
])
@pytest.mark.parametrize("neutral", [False, True], ids=["original", "neutral"])
def test_r13_rejects_actual_experiment_outputs_and_approval_receipts(history, options, source, start, end, neutral):
    path = "fixtures/topology-input.json" if neutral else source
    history.write(path, git_at_r3("show", f"{R12_HEAD}:{source}"))
    history.gate()
    check_basis(history, options, path, allowed=False, line=start, line_end=end)


@pytest.mark.parametrize("path", [
    ".chanlun/handoff/current.json", ".chanlun/handoff/history/2026-03-10-2034.json",
    ".chanlun/goals/events.jsonl", "trading_system/data_cache/fugue_v3_ES.json",
    ".chanlun/block-topology/relations.jsonl", ".chanlun/block-topology/meta.json",
    ".chanlun/morse_landscape.json", ".chanlun/concept_registry.json", "scripts/.corpus_ingest_resume.json",
])
def test_r13_rejects_actual_non_input_data(history, options, path):
    history.write(path, git_at_r3("show", f"{R12_HEAD}:{path}"))
    history.gate()
    check_basis(history, options, path, allowed=False)


@pytest.mark.parametrize(("key", "value", "allowed"), [
    ("format", "newchanlun-approval-trust/v1", True),
    ("schema_version", "tb02a/hand-oracle/1", True),
    ("format", "sample-receipt/v1", False),
    ("schema_version", "sample-approval/2", False),
    ("schema", "sample.report.v1", False),
    ("format", "sample-review/v2", False),
    ("format", "sample-verdict/10", False),
])
def test_r13_versioned_artifact_envelope_keeps_input_formats(history, options, key, value, allowed):
    path = "fixtures/sequence.jsonl"
    # 共同的业务字段不是拒绝理由；逐条检查第二条记录的协议身份。
    data = {key: value, "status": "PASS", "result": "expected", "reports": []}
    history.write(path, b'{"id":1}\n' + json.dumps(data).encode() + b"\n")
    history.gate()
    check_basis(history, options, path, allowed=allowed, line=2)


@pytest.mark.parametrize(("path", "allowed"), [
    *((path, False) for path in (
        ".sandcastle/runs/note.md", ".sandcastle/RUNS/note.md",
        "reports/data.json", "REPORTS/data.json", "analysis/data.json", "Analysis/data.json",
        "experiments/dm1_results.json", "EXPERIMENTS/dm1_results.json", "DATA_CACHE/x.json",
        "HANDOFF/x.json", "GOALS/x.jsonl", ".chanlun/BLOCK-TOPOLOGY/x.json",
        ".chanlun/REVIEW-RESULTS/bundle/rules.py", "CHANLUN/REVIEW-RESULTS/bundle/data.json",
        "EXTERNAL/K4-SOROS-REPORTS/rules.py", "docs/MEMORY_SNAPSHOT/probe.json",
        "README.MD", "README.Md", "readme.md", "docs/adr/0001-a/b.md", "docs/SPEC/contract.md",
    )),
    ("analysis/p3_random_gate_control.py", True),
])
def test_r13_only_exclusions_ignore_directory_case(history, options, path, allowed):
    history.write(path, b'{"fixture":1}\n')
    history.gate()
    check_basis(history, options, path, allowed=allowed)
