"""核对 R3 清册回归与 P0 闸前逐 blob 复审原件。"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys


AT18 = Path(__file__).resolve().parents[1]
BLOB_MODES = ("100644", "100755", "120000")
VERDICTS = ("PASS", "BLOCK")


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd)


def names(*args, cwd=None):
    return set(git(*args, cwd=cwd).decode().strip("\0").split("\0")) - {""}


def retained(shas, p0, f, *, cwd=None):
    paths = set()
    for sha in shas:
        paths |= names("diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z",
                       f"{sha}^1", sha, cwd=cwd)
    return (paths & names("ls-tree", "-r", "--name-only", "-z", p0, cwd=cwd)
            & names("ls-tree", "-r", "--name-only", "-z", f, cwd=cwd))


def p0_rows(p0, paths, *, cwd=None):
    """只读 P0 Git 树；符号链接使用链接自身的 blob。"""
    rows = {}
    for entry in git("ls-tree", "-r", "-z", p0, cwd=cwd).split(b"\0")[:-1]:
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode("utf-8")
        if path not in paths:
            continue
        mode, kind, blob = metadata.decode("ascii").split()
        if kind != "blob" or mode not in BLOB_MODES:
            raise ValueError(f"PREGATE_REVIEW: not a P0 blob: {path!r}")
        rows[path] = dict(path=path, mode=mode, blob=blob)
    if rows.keys() != paths:
        raise ValueError("PREGATE_REVIEW: missing paths in P0")
    return [rows[path] for path in sorted(rows)]


def check_review(path, expected_rows):
    """核验结构和精确覆盖，并返回原裁定计数。BLOCK 仍是 R10 的阻断。"""
    def unique_keys(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("PREGATE_REVIEW: duplicate JSON key")
        return result

    if path.is_symlink() or not path.is_file():
        raise ValueError("PREGATE_REVIEW: expected a regular review file")
    try:
        review = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PREGATE_REVIEW: invalid UTF-8 JSON") from error
    if (not isinstance(review, dict) or review.keys() != {"schema_version", "owner_ticket", "rows"}
            or review["schema_version"] != "at18-pregate-review/1"
            or type(review["owner_ticket"]) is not int or review["owner_ticket"] != 2132
            or not isinstance(review["rows"], list)):
        raise ValueError("PREGATE_REVIEW: invalid envelope")

    actual, counts, previous = {}, Counter(), ""
    for n, row in enumerate(review["rows"], 1):
        if not isinstance(row, dict) or row.keys() != {"path", "blob", "mode", "verdict"}:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid row keys")
        name, blob, mode, verdict = (row[k] for k in ("path", "blob", "mode", "verdict"))
        if not isinstance(name, str) or not name:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid path")
        if name in actual:
            raise ValueError(f"PREGATE_REVIEW: row {n}: duplicate path")
        if name < previous:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid path order")
        if not isinstance(blob, str) or not re.fullmatch(r"[0-9a-f]{40}", blob):
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid blob")
        if mode not in BLOB_MODES:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid mode")
        if verdict not in VERDICTS:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid verdict")
        actual[name] = (blob, mode)
        counts[verdict] += 1
        previous = name
    expected = {r["path"]: (r["blob"], r["mode"]) for r in expected_rows}
    if expected.keys() != actual.keys():
        raise ValueError(f"PREGATE_REVIEW: path coverage mismatch: {len(expected.keys() - actual.keys())} missing, "
                         f"{len(actual.keys() - expected.keys())} extra")
    for name, identity in expected.items():
        if actual[name] != identity:
            raise ValueError(f"PREGATE_REVIEW: P0 blob/mode mismatch at {name!r}")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path, help="rebuild_pregate.py 的输出目录")
    parser.add_argument("--sources", type=Path, default=AT18 / "pregate")
    parser.add_argument("--registry", type=Path, default=Path(".chanlun/at18/registry.json"))
    parser.add_argument("--review", type=Path, default=AT18 / "pregate-review.json",
                        help="待校验的复审原件（默认使用仓内 pregate-review.json）")
    args = parser.parse_args()

    def data(name, *, frozen=False):
        return json.loads(((args.sources if frozen else args.replay) / name).read_bytes())

    report = data("summary.json")
    p0, f = report["p0"], report["observed_main"]
    if p0 != json.loads((AT18 / "landing-census.json").read_bytes())["p0"]:
        raise ValueError("PREGATE_REVIEW: replay uses a different P0")
    r3 = data("r3-ticket-set.json", frozen=True)
    old = {sha for commits in r3["table"].values() for sha in commits}
    ledger = data("landings.json")
    registered = json.loads(args.registry.read_bytes())["pregate"]["landings"]
    assert [{k: row[k] for k in ("ticket", "commits", "attribution_scopes")} for row in registered] == ledger["by_ticket"]
    by_pr = {pr: row for row in ledger["by_commit"] for pr in row["prs"]}
    by_tkt = {row["ticket"]: set(row["commits"]) for row in ledger["by_ticket"]}
    paths = {row["path"]: row for row in data("paths.json")}
    rows = data("pre.json")
    expected = p0_rows(p0, retained({row["commit"] for row in ledger["by_commit"]}, p0, f))
    if rows != expected:
        raise ValueError("PREGATE_REVIEW: pre.json differs from retained P0 path/blob/mode")
    counts = check_review(args.review, expected)
    pre = {row["path"] for row in expected}
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

    path = "rust/src/economic_session/tb03c_c5_read_tests.rs"
    for sha in (p0, f):
        actual = git("ls-tree", sha, "--", path).decode().split()
        assert actual[:3] == [
            "100644", "blob", "0bcc46e9535554ee76ec3426e29f638a147427c4"
        ]
    assert by_pr[1616]["commit"] in paths[path]["pre_gate_commits"] and not paths[path]["post_gate_commits"]
    runs = data("historical-runs.json", frozen=True)
    for pr, run_id in ((1553, 39223502349), (1571, 39321352559)):
        rs = runs[by_pr[pr]["commit"]][".github/workflows/ci.yml"]
        assert any(r["id"] == run_id and r["conclusion"] == "failure" for r in rs)
    print(f'R3 regression: {len(old)} -> {len(old | extra)} commits; {len(old_pre)} -> {len(closed_pre)} PRE paths')
    print('#1406 #1616 alone: 90 additional surviving paths over R3, of which 89 untouched')
    print('#1359 and #1372 share #1452 without duplicating paths')
    print('Known #1405 CI failures match the exact historical run IDs')
    print(f'R5 full evidence: {len(ledger["by_commit"])} unique landings, {len(pre)} exact PRE paths')
    print(f'P0 review inventory: {len(expected)} exact path/blob/mode matches; '
          f'{counts["PASS"]} PASS / {counts["BLOCK"]} BLOCK')
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
