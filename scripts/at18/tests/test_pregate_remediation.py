"""R10 补救原件：每例在独立 Git 仓库、普通和优化 Python 中走同一校验入口。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


PREGATE = Path(__file__).resolve().parents[3] / ".chanlun/at18/pregate"
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
