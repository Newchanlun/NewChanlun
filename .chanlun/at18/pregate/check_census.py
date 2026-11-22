"""核对 R3 清册回归与 P0 闸前逐 blob 复审原件。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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


def require(condition, code, message):
    if not condition:
        raise ValueError(f"{code}: {message}")


def read_json(path, code="PREGATE_CENSUS"):
    def unique_keys(pairs):
        result = dict(pairs)
        require(len(result) == len(pairs), code, f"{path.name}: duplicate JSON key")
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{code}: {path.name}: invalid UTF-8 JSON") from error


def read_review(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("PREGATE_REVIEW: expected a regular review file")
    return read_json(path, "PREGATE_REVIEW")


def check_review(path, expected_rows):
    """核验结构和精确覆盖，并返回原裁定计数。BLOCK 仍是 R10 的阻断。"""
    return match_review(read_review(path), expected_rows)


def match_review(review, expected_rows):
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


def check_landings(registered, ledger):
    """登记册给出提交分母，回放的两张表都必须与之相符。"""
    by_ticket = [{k: row[k] for k in ("ticket", "commits", "attribution_scopes")}
                 for row in registered]
    require(by_ticket == ledger["by_ticket"], "PREGATE_LANDINGS", "registry differs from by_ticket")
    by_tkt = {row["ticket"]: set(row["commits"]) for row in by_ticket}
    expected = defaultdict(set)
    for ticket, commits in by_tkt.items():
        for sha in commits:
            expected[sha].add(ticket)

    seen = set()
    for row in ledger["by_commit"]:
        sha, tickets = row["commit"], row["tickets"]
        require(sha in expected, "PREGATE_LANDINGS", f"unregistered commit in by_commit: {sha}")
        require(sha not in seen, "PREGATE_LANDINGS", f"duplicate commit in by_commit: {sha}")
        require(len(tickets) == len(expected[sha]) and all(type(t) is int for t in tickets)
                and set(tickets) == expected[sha],
                "PREGATE_LANDINGS", f"ticket mapping mismatch for {sha}")
        seen.add(sha)
    missing = expected.keys() - seen
    require(not missing, "PREGATE_LANDINGS", f"{len(missing)} registered commit(s) missing from by_commit")
    return by_tkt, set(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path, help="rebuild_pregate.py 的输出目录")
    parser.add_argument("--sources", type=Path, default=AT18 / "pregate")
    parser.add_argument("--registry", type=Path, default=Path(".chanlun/at18/registry.json"))
    parser.add_argument("--review", type=Path, default=AT18 / "pregate-review.json",
                        help="待校验的复审原件（默认使用仓内 pregate-review.json）")
    args = parser.parse_args()

    def data(name, *, frozen=False):
        return read_json((args.sources if frozen else args.replay) / name)

    report = data("summary.json")
    census = read_json(AT18 / "landing-census.json")
    r3 = data("r3-ticket-set.json", frozen=True)
    ledger = data("landings.json")
    registered = read_json(args.registry)["pregate"]["landings"]
    paths = {row["path"]: row for row in data("paths.json")}
    rows = data("pre.json")
    runs = data("historical-runs.json", frozen=True)
    review = read_review(args.review)
    # rebuild_pregate.py 只在提供历史 run 原件时产出偏差表；逐字节一致性由 README 的 cmp 核对。
    deviations = args.replay / "historical-deviations.json"
    if deviations.exists():
        read_json(deviations)

    p0, f = report["p0"], report["observed_main"]
    if p0 != census["p0"]:
        raise ValueError("PREGATE_REVIEW: replay uses a different P0")
    by_tkt, commits = check_landings(registered, ledger)
    expected = p0_rows(p0, retained(commits, p0, f))
    if rows != expected:
        raise ValueError("PREGATE_REVIEW: pre.json differs from retained P0 path/blob/mode")
    counts = match_review(review, expected)
    pre = {row["path"] for row in expected}
    old = {sha for landings in r3["table"].values() for sha in landings}
    by_pr = {pr: row for row in ledger["by_commit"] for pr in row["prs"]}

    def pr_tickets(pr):
        return by_pr.get(pr, {}).get("tickets", ())

    require(len(old) == 15, "R3_CENSUS", "expected 15 historical commits")
    for ticket, landings in r3["table"].items():
        require(landings and set(landings) <= by_tkt.get(int(ticket), set()),
                "R3_CENSUS", f"historical landings missing for #{ticket}")
    require({1359, 1372} <= set(pr_tickets(1452)), "R3_CENSUS", "#1452 must belong to #1359 and #1372")
    extra_prs = {1553: 1405, 1571: 1405, 1583: 1394}
    for pr, tkt in extra_prs.items():
        require(tkt in pr_tickets(pr), "R3_CENSUS", f"#{pr} must belong to #{tkt}")
    extra = {by_pr[pr]["commit"] for pr in extra_prs}
    old_pre = retained(old, p0, f)
    closed_pre = retained(old | extra, p0, f)
    require((len(old_pre), len(closed_pre)) == (483, 493), "R3_CENSUS", "expected 483 -> 493 PRE paths")
    require(closed_pre <= pre, "R3_CENSUS", "closed historical landings absent from PRE")
    open_landings = report["open_ticket_landings"]
    require(1406 in pr_tickets(1616) and "1406" in open_landings,
            "R3_CENSUS", "#1616 must belong to open ticket #1406")
    new_open = retained({by_pr[1616]["commit"]}, p0, f) - old_pre
    require(len(new_open) == 90 and new_open <= pre, "R3_CENSUS", "#1616 must add 90 PRE paths")
    require(new_open <= paths.keys()
            and sum(paths[path]["disposition"] == "SURVIVING_UNTOUCHED" for path in new_open) == 89,
            "R3_CENSUS", "#1616 must have 89 untouched retained paths")
    for tkt in (1381, 1481, 1491, 1527, 1715, 1716, 1717, 1718, 1719):
        require(str(tkt) in open_landings, "R3_CENSUS", f"missing open landing for #{tkt}")

    path = "rust/src/economic_session/tb03c_c5_read_tests.rs"
    for sha in (p0, f):
        actual = git("ls-tree", sha, "--", path).decode().split()
        require(actual[:3] == ["100644", "blob", "0bcc46e9535554ee76ec3426e29f638a147427c4"],
                "R3_CENSUS", f"unexpected #1616 blob at {sha}: {path}")
    require(path in paths and by_pr[1616]["commit"] in paths[path]["pre_gate_commits"]
            and not paths[path]["post_gate_commits"], "R3_CENSUS", f"unexpected #1616 provenance: {path}")
    for pr, run_id in ((1553, 39223502349), (1571, 39321352559)):
        rs = runs.get(by_pr[pr]["commit"], {}).get(".github/workflows/ci.yml", ())
        require(any(r["id"] == run_id and r["conclusion"] == "failure" for r in rs),
                "R11_HISTORY", f"#1405 PR #{pr} run {run_id} is not recorded as a failure")
    print(f'R3 regression: {len(old)} -> {len(old | extra)} commits; {len(old_pre)} -> {len(closed_pre)} PRE paths')
    print('#1406 #1616 alone: 90 additional surviving paths over R3, of which 89 untouched')
    print('#1359 and #1372 share #1452 without duplicating paths')
    print('Known #1405 CI failures match the exact historical run IDs')
    print(f'R5 full evidence: {len(commits)} unique landings, {len(pre)} exact PRE paths')
    print(f'P0 review inventory: {len(expected)} exact path/blob/mode matches; '
          f'{counts["PASS"]} PASS / {counts["BLOCK"]} BLOCK')
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
