"""Independent spot checks for the exact R3 objections, using only Git trees."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def git(*args):
    return subprocess.check_output(["git", *args])


def names(*args):
    return set(git(*args).decode().strip("\0").split("\0")) - {""}


def retained(shas, p0, f):
    paths = set()
    for sha in shas:
        paths |= names("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", f"{sha}^1", sha)
    return paths & names("ls-tree", "-r", "--name-only", "-z", p0) & names("ls-tree", "-r", "--name-only", "-z", f)


root = Path(sys.argv[1])
def data(name):
    return json.loads((root / name).read_bytes())


report = data("summary.json")
p0, f = report["p0"], report["observed_main"]
r3 = data("r3-ticket-set.json")
old = {sha for commits in r3["table"].values() for sha in commits}
ledger = data("landings.json")
by_pr = {pr: row for row in ledger["by_commit"] for pr in row["prs"]}
by_tkt = {row["ticket"]: set(row["commits"]) for row in ledger["by_ticket"]}
paths = {row["path"]: row for row in data("paths.json")}
pre = {row["path"] for row in data("pre.json")}
assert len(old) == 15
assert all(commits and set(commits) <= by_tkt[int(tkt)] for tkt, commits in r3["table"].items())
assert 1359 in by_pr[1452]["tickets"] and 1372 in by_pr[1452]["tickets"]
extra_prs = {1553: 1405, 1571: 1405, 1583: 1394}
for pr, tkt in extra_prs.items():
    assert tkt in by_pr[pr]["tickets"]
extra = {by_pr[pr]["commit"] for pr in extra_prs}
old_pre = retained(old, p0, f)
closed_pre = retained(old | extra, p0, f)
assert (len(old_pre), len(closed_pre)) == (483, 493)
assert closed_pre <= pre
assert 1406 in by_pr[1616]["tickets"] and "1406" in report["open_ticket_landings"]
new_open = retained({by_pr[1616]["commit"]}, p0, f) - old_pre
assert len(new_open) == 90 and new_open <= pre
assert sum(paths[path]["disposition"] == "SURVIVING_UNTOUCHED" for path in new_open) == 89
for tkt in (1381, 1481, 1491, 1527, 1715, 1716, 1717, 1718, 1719):
    assert str(tkt) in report["open_ticket_landings"], tkt

rows = data("pre.json")
assert len(pre) == len(rows)
assert pre == retained({row["commit"] for row in ledger["by_commit"]}, p0, f)
path = "rust/src/economic_session/tb03c_c5_read_tests.rs"
for sha in (p0, f):
    actual = git("ls-tree", sha, "--", path).decode().split()
    assert actual[:3] == [
        "100644", "blob", "0bcc46e9535554ee76ec3426e29f638a147427c4"
    ]
assert by_pr[1616]["commit"] in paths[path]["pre_gate_commits"] and not paths[path]["post_gate_commits"]
runs = data("historical-runs.json")
for pr, run_id in ((1553, 39223502349), (1571, 39321352559)):
    rs = runs[by_pr[pr]["commit"]][".github/workflows/ci.yml"]
    assert any(r["id"] == run_id and r["conclusion"] == "failure" for r in rs)
print(f'R3 regression: {len(old)} -> {len(old | extra)} commits; {len(old_pre)} -> {len(closed_pre)} PRE paths')
print('#1406 #1616 alone: 90 additional surviving paths over R3, of which 89 untouched')
print('#1359 and #1372 share #1452 without duplicating paths')
print('Known #1405 CI failures match the exact historical run IDs')
print(f'R5 full evidence: {len(ledger["by_commit"])} unique landings, {len(pre)} exact PRE paths')
