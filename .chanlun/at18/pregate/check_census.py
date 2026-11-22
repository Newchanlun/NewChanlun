"""核对冻结清册、P0 历史裁定与指定 F 的 R10 补救状态。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

from pregate_contract import (
    BLOB_MODES, OID, REGULAR_MODES, Entry, changes_on_window, check_remediation, classify_review, diff_paths,
    final_blob_changed, git, git_tree, pre_scope, read_json, require, require_blob,
    strict_json, valid_path, window,
)
from rebuild_pregate import G0, landing_scopes


AT18 = Path(__file__).resolve().parents[1]
ROOT = AT18.parents[1]
FROZEN_F = "b9d898dccf46c2a716115eaa1215bc39c458a959"
REVIEW = ".chanlun/at18/pregate-review.json"
REVIEW_SCOPE = f"pre:{REVIEW}"
HISTORICAL_REVIEW_BLOB = "1aed53fd7a1e0be271de949d7c37c0ac81aefc1b"
VERDICTS = ("PASS", "BLOCK")


def landing_paths(shas, *, cwd=None):
    paths = set()
    for sha in shas:
        paths |= diff_paths(f"{sha}^1", sha, cwd=cwd)
    return paths


def pre_paths(touched, before, final):
    paths = touched & before.keys() & final.keys()
    for path in sorted(paths):
        final_blob_changed(path, before[path], final[path])
    return paths


def retained(shas, p0, f, *, cwd=None):
    return pre_paths(landing_paths(shas, cwd=cwd), git_tree(p0, cwd=cwd), git_tree(f, cwd=cwd))


def p0_rows(p0, paths, *, cwd=None, tree=None):
    """只读 P0 Git 树；符号链接使用链接自身的 blob。"""
    return p0_tree_rows(git_tree(p0, cwd=cwd) if tree is None else tree, paths)


def p0_tree_rows(before, paths):
    require(paths <= before.keys(), "PREGATE_REVIEW", "missing paths in P0")
    rows = []
    for path in sorted(paths, key=str.encode):
        entry = before[path]
        require_blob(entry, path, "P0")
        rows.append(dict(path=path, mode=entry.mode, blob=entry.blob))
    return rows


def review_bytes(path):
    require(not path.is_symlink() and path.is_file(), "PREGATE_REVIEW", "expected a regular review file")
    return path.read_bytes()


def check_review(path, expected_rows):
    """核验结构和精确覆盖，并返回原裁定计数。"""
    return match_review(strict_json(review_bytes(path), "PREGATE_REVIEW", path.name), expected_rows)


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
        if not valid_path(name):
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid path")
        if name in actual:
            raise ValueError(f"PREGATE_REVIEW: row {n}: duplicate path")
        if name < previous:
            raise ValueError(f"PREGATE_REVIEW: row {n}: invalid path order")
        if not isinstance(blob, str) or not OID.fullmatch(blob):
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


def original_review(raw, blob, expected, identity):
    review = strict_json(raw, "PREGATE_REVIEW", identity)
    counts = match_review(review, expected)
    require(blob == HISTORICAL_REVIEW_BLOB and counts == {"PASS": 978, "BLOCK": 47},
            "PREGATE_REVIEW", "original review Git blob or historical verdict counts mismatch")
    return review, counts


def tree_review_entry(commit, *, cwd):
    record = git("ls-tree", "-z", commit, "--", REVIEW, cwd=cwd)
    if not record:
        return None
    metadata, _ = record.split(b"\t", 1)
    return Entry(*metadata.decode("ascii").split())


def tree_review_bytes(entry, *, cwd):
    require(entry.kind == "blob" and entry.mode in REGULAR_MODES, "PREGATE_REVIEW",
            f"{REVIEW_SCOPE}: expected a regular review file in F history")
    return git("cat-file", "blob", entry.blob, cwd=cwd)


def record_verdicts(review, verdicts, *, introduce):
    for row in review["rows"]:
        path, mode, blob, verdict = (row[key] for key in ("path", "mode", "blob", "verdict"))
        key = path, mode, blob
        if introduce:
            verdicts.setdefault(key, verdict)
        prior = verdicts.get(key)
        require(prior is not None, "PREGATE_REVIEW", f"{pre_scope(path)}: no verdict in first-parent review history")
        require(prior == verdict, "PREGATE_REVIEW",
                f"{pre_scope(path)}: historical verdict mismatch: {prior} -> {verdict}")


def check_head_review(head, tree, before, touched, frozen_rows, *, cwd, override=None):
    """从 F 及第一父链取本地 Git 事实；R09 正式采信另验。"""
    entry = tree.get(REVIEW)
    require(entry is not None or override is not None, "PREGATE_REVIEW", f"{REVIEW_SCOPE}: missing")
    commits = git("log", "--first-parent", "--full-history", "--root", "--format=%H",
                  head, "--", REVIEW, cwd=cwd).decode().splitlines()
    first = None
    verdicts = {}
    for commit in reversed(commits):
        at_commit = tree_review_entry(commit, cwd=cwd)
        if at_commit is None:
            continue  # 文件退出不清除任何路径的历史判词。
        if first is None:
            require(at_commit.blob == HISTORICAL_REVIEW_BLOB, "PREGATE_REVIEW",
                    f"{REVIEW_SCOPE}: missing (first-parent introduction is not the original review blob)")
        raw = tree_review_bytes(at_commit, cwd=cwd)
        if first is None:
            first = commit
            review, _ = original_review(raw, at_commit.blob, frozen_rows, REVIEW_SCOPE)
        else:
            review = strict_json(raw, "PREGATE_REVIEW", REVIEW_SCOPE)
        recorded_tree = tree if commit == head else git_tree(commit, cwd=cwd)
        match_review(review, p0_tree_rows(before, pre_paths(touched, before, recorded_tree)))
        record_verdicts(review, verdicts, introduce=True)

    if entry is None:
        # 首载前只能用固定原件约束预检，不把候选行视为历史裁定。
        if first is None:
            original = git("cat-file", "blob", HISTORICAL_REVIEW_BLOB, cwd=cwd)
            review, _ = original_review(original, HISTORICAL_REVIEW_BLOB, frozen_rows, REVIEW_SCOPE)
            record_verdicts(review, verdicts, introduce=True)
        raw = review_bytes(override)
    else:
        require(first is not None, "PREGATE_REVIEW", f"{REVIEW_SCOPE}: missing (no first-parent introduction)")
        raw = tree_review_bytes(entry, cwd=cwd)
    review = strict_json(raw, "PREGATE_REVIEW", REVIEW_SCOPE)
    counts = match_review(review, p0_tree_rows(before, pre_paths(touched, before, tree)))
    record_verdicts(review, verdicts, introduce=False)
    if entry is not None and override is not None:
        require(review_bytes(override) == raw, "PREGATE_REVIEW",
                f"{REVIEW_SCOPE}: local review differs from the fixed F artifact")
    return review, counts, first, verdicts


def check_landings(registered, ledger, issues, attributions):
    """登记册给出提交分母，回放的两张表都必须与之相符。"""
    by_ticket = [{k: row[k] for k in ("ticket", "commits", "attribution_scopes")}
                 for row in registered]
    require(by_ticket == ledger["by_ticket"], "PREGATE_LANDINGS", "registry differs from by_ticket")
    by_tkt = {}
    for row in by_ticket:
        ticket, commits = row["ticket"], row["commits"]
        require(type(ticket) is int and ticket > 0 and ticket not in by_tkt,
                "PREGATE_LANDINGS", "invalid or duplicate registered ticket")
        require(isinstance(commits, list) and commits
                and all(isinstance(sha, str) and OID.fullmatch(sha) for sha in commits)
                and commits == sorted(set(commits)), "PREGATE_LANDINGS", f"invalid commits for #{ticket}")
        by_tkt[ticket] = set(commits)
    try:
        scopes = landing_scopes(issues, set(by_tkt), attributions)
    except ValueError as error:
        raise ValueError(f"PREGATE_LANDINGS: {error}") from error
    for row in by_ticket:
        ticket = row["ticket"]
        require(row["attribution_scopes"] == scopes[ticket], "PREGATE_LANDINGS",
                f"attribution_scopes mismatch for #{ticket}: expected {scopes[ticket]}")
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


def check_r3(by_tkt, ledger, r3, runs, p0, pre, before, frozen_tree, chain, issues, replay=None):
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
    old_pre = pre_paths(landing_paths(old, cwd=ROOT), before, frozen_tree)
    closed_pre = old_pre | pre_paths(landing_paths(extra, cwd=ROOT), before, frozen_tree)
    require((len(old_pre), len(closed_pre)) == (483, 493), "R3_CENSUS", "expected 483 -> 493 PRE paths")
    require(closed_pre <= pre, "R3_CENSUS", "closed historical landings absent from PRE")
    open_tickets = {row["number"] for row in issues if row["state"] == "open"} & by_tkt.keys()
    require(1406 in pr_tickets(1616) and 1406 in open_tickets,
            "R3_CENSUS", "#1616 must belong to open ticket #1406")
    landing = by_pr[1616]["commit"]
    landed = landing_paths({landing}, cwd=ROOT)
    new_open = pre_paths(landed, before, frozen_tree) - old_pre
    require(len(new_open) == 90 and new_open <= pre, "R3_CENSUS", "#1616 must add 90 PRE paths")
    path = "rust/src/economic_session/tb03c_c5_read_tests.rs"
    post = changes_on_window(p0, chain, new_open | {path}, cwd=ROOT)
    require(sum(not post.get(name) for name in new_open) == 89,
            "R3_CENSUS", "#1616 must have 89 untouched retained paths")
    require({1381, 1481, 1491, 1527, 1715, 1716, 1717, 1718, 1719} <= open_tickets,
            "R3_CENSUS", "missing open landing")
    expected_entry = ("100644", "blob", "0bcc46e9535554ee76ec3426e29f638a147427c4")
    require(before.get(path) == frozen_tree.get(path) == expected_entry,
            "R3_CENSUS", f"unexpected #1616 blob: {path}")
    require(path in landed and not post.get(path), "R3_CENSUS", f"unexpected #1616 provenance: {path}")
    if replay is not None:
        report, paths = replay
        replay_open = report["open_ticket_landings"]
        require(all(str(tkt) in replay_open for tkt in (1406, 1381, 1481, 1491, 1527, 1715, 1716, 1717, 1718, 1719)),
                "R3_CENSUS", "missing open landing in replay")
        require(new_open <= paths.keys()
                and sum(paths[name]["disposition"] == "SURVIVING_UNTOUCHED" for name in new_open) == 89,
                "R3_CENSUS", "#1616 replay must have 89 untouched retained paths")
        require(path in paths and landing in paths[path]["pre_gate_commits"]
                and not paths[path]["post_gate_commits"], "R3_CENSUS", f"unexpected #1616 replay provenance: {path}")
    for pr, run_id in ((1553, 39223502349), (1571, 39321352559)):
        rs = runs.get(by_pr[pr]["commit"], {}).get(".github/workflows/ci.yml", ())
        require(any(r["id"] == run_id and r["conclusion"] == "failure" for r in rs),
                "R11_HISTORY", f"#1405 PR #{pr} run {run_id} is not recorded as a failure")
    print(f'R3 regression: {len(old)} -> {len(old | extra)} commits; {len(old_pre)} -> {len(closed_pre)} PRE paths')
    print('#1406 #1616 alone: 90 additional surviving paths over R3, of which 89 untouched')
    print('#1359 and #1372 share #1452 without duplicating paths')
    print('Known #1405 CI failures match the exact historical run IDs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", nargs="?", type=Path, help="可选：同时核对 rebuild_pregate.py 的输出")
    parser.add_argument("--sources", type=Path, default=AT18 / "pregate")
    parser.add_argument("--registry", type=Path, default=AT18 / "registry.json")
    parser.add_argument("--review", type=Path,
                        help="本地预检候选；已有 F 原件时须与其逐字节相同")
    parser.add_argument("--head", help="F 的 Git 提交或引用（显式指定时只认 F 树原件；省略时可回放冻结窗）")
    parser.add_argument("--remediation", type=Path, help="本地预检用原件（默认从 F 的固定路径读 Git blob）")
    args = parser.parse_args()

    census_path = AT18 / "landing-census.json"
    census_raw = census_path.read_bytes()
    census = strict_json(census_raw, "PREGATE_CENSUS", census_path.name)
    registry = read_json(args.registry)["pregate"]
    require(sha256(census_raw).hexdigest() == registry["census_sha256"], "PREGATE_LANDINGS", "census_sha256")
    relation_path = AT18 / "pregate" / "sources.json"
    relations = [row for row in census["sources"] if row["role"] == "relations"]
    relation_raw = relation_path.read_bytes()
    require(len(relations) == 1 and relations[0]["path"] == relation_path.relative_to(ROOT).as_posix()
            and relations[0]["sha256"] == sha256(relation_raw).hexdigest(),
            "PREGATE_LANDINGS", "frozen native relations do not match census")
    issues = strict_json(relation_raw, "PREGATE_LANDINGS", relation_path.name)["issues"]

    p0 = census["p0"]
    ledger = read_json((args.replay or AT18 / "pregate") / "landings.json")
    require(ledger["p0"] == p0 and ledger["gate"] == G0, "PREGATE_REVIEW", "replay uses a different P0 or G0")
    by_tkt, commits = check_landings(registry["landings"], ledger, issues, census["attributions"])
    r3 = read_json(args.sources / "r3-ticket-set.json")
    runs = read_json(args.sources / "historical-runs.json")

    def resolve(ref):
        return git("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", cwd=ROOT).decode().strip()

    head = resolve(args.head or (ledger["observation"] if args.replay else FROZEN_F))
    chain = window(p0, G0, head, cwd=ROOT)
    frozen_chain = chain if head == FROZEN_F else window(p0, G0, FROZEN_F, cwd=ROOT)
    touched = landing_paths(commits, cwd=ROOT)
    before, frozen_tree = git_tree(p0, cwd=ROOT), git_tree(FROZEN_F, cwd=ROOT)
    final_tree = frozen_tree if head == FROZEN_F else git_tree(head, cwd=ROOT)
    pre = pre_paths(touched, before, frozen_tree)
    frozen_rows = p0_tree_rows(before, pre)
    current = pre_paths(touched, before, final_tree)
    frozen_replay = args.head is None and head == FROZEN_F
    if frozen_replay:
        source = args.review or ROOT / REVIEW
        raw = review_bytes(source)
        blob = git("hash-object", "--stdin", input=raw, cwd=ROOT).decode().strip()
        review, counts = original_review(raw, blob, frozen_rows, source.name)
        deleted = 0
        inventory_source = "Frozen replay: local historical review; not an F registration"
    else:
        review, counts, first, verdicts = check_head_review(
            head, final_tree, before, touched, frozen_rows, cwd=ROOT, override=args.review)
        deleted = sum(verdict == "BLOCK" and path not in final_tree
                      for (path, _, _), verdict in verdicts.items())
        if REVIEW in final_tree:
            inventory_source = f"F review: first-parent introduction {first}; original blob {HISTORICAL_REVIEW_BLOB}"
        else:
            inventory_source = f"PREGATE_REVIEW: {REVIEW_SCOPE}: missing in F; --review is a local preview only"

    replay = None
    if args.replay:
        report = read_json(args.replay / "summary.json")
        paths = {row["path"]: row for row in read_json(args.replay / "paths.json")}
        rows = read_json(args.replay / "pre.json")
        # 历史偏差表逐字节一致性另由 README 的 cmp 核对。
        deviations = args.replay / "historical-deviations.json"
        if deviations.exists():
            read_json(deviations)
        require(report["p0"] == p0 and report["observed_main"] == ledger["observation"],
                "PREGATE_REVIEW", "replay summary uses a different P0 or observation")
        replay_head = resolve(ledger["observation"])
        if replay_head == FROZEN_F:
            replay_tree = frozen_tree
            replay = report, paths
        elif replay_head == head:
            replay_tree = final_tree
        else:
            window(p0, G0, replay_head, cwd=ROOT)
            replay_tree = git_tree(replay_head, cwd=ROOT)
        require(rows == p0_tree_rows(before, pre_paths(touched, before, replay_tree)),
                "PREGATE_REVIEW", "pre.json differs from retained P0 path/blob/mode")

    check_r3(by_tkt, ledger, r3, runs, p0, pre, before, frozen_tree, frozen_chain, issues, replay)

    print(f'R5 full evidence: {len(commits)} unique landings, {len(pre)} exact PRE paths')
    print(inventory_source)
    print(f'P0 review inventory: {len(current)} exact path/blob/mode matches; '
          f'{counts["PASS"]} PASS / {counts["BLOCK"]} BLOCK')

    rows = review["rows"]
    classes = classify_review(rows, final_tree)
    passed = sum(state == "pass" for state in classes.values())
    hard = [path for path, state in classes.items() if state == "hard"]
    changed = [path for path, state in classes.items() if state == "changed"]
    valid = set()
    failed = False
    try:
        valid = check_remediation(rows, classes, final_tree, p0, chain, cwd=ROOT, override=args.remediation)
    except ValueError as error:
        print(error, file=sys.stderr)
        failed = True
    for path in hard:
        print(f"PREGATE_REVIEW: {pre_scope(path)}: original blob; hard BLOCK", file=sys.stderr)
    print(f'R10 F={head}: {len(current)} PRE; {passed} surviving P0 PASS; '
          f'{len(hard)} hard BLOCK / {len(changed)} changed BLOCK / '
          f'{deleted} deleted BLOCK; {len(valid)} locally validated remediation rows; 0 released')
    for path in changed:
        print(f"R10 changed BLOCK: {pre_scope(path)}")
    return int(failed or bool(hard or changed))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
