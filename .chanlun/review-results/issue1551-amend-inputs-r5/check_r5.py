"""Verify the r5 census, state-independent attribution, and all six R10 routes."""
from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from rebuild_pregate import landing_scopes

B, replay, flipped = map(Path, sys.argv[1:4])
r4 = B.with_name("issue1551-amend-inputs-r4")


def read(root, name):
    return json.loads((root / name).read_bytes())


census = read(B, "landing-census.json")
roles = dict(history="all-first-parent.jsonl", relations="sources.json",
             signals="candidate-signals.json", adjudication="adjudication.json")
assert [row["role"] for row in census["sources"]] == list(roles)
for row in census["sources"]:
    assert set(row) == {"role", "path", "sha256"}
    assert Path(row["path"]).parts[-2:] == (B.name, roles[row["role"]])
    assert row["sha256"] == sha256((B / roles[row["role"]]).read_bytes()).hexdigest()

stable = (*roles.values(), "landings.json", "paths.json", "pre.json",
          "historical-deviations.json", "postgate-path-history.json", "unattributed-window-audit.json")
generated = set(stable) - {"sources.json", "adjudication.json"}
assert len(generated) == 8
for name in generated:
    assert (B / name).read_bytes() == (replay / name).read_bytes() == (flipped / name).read_bytes(), name
    if name != "landings.json":
        assert (B / name).read_bytes() == (r4 / name).read_bytes(), name
original, inverted = (read(root, "summary.json") for root in (B, flipped))
assert (B / "summary.json").read_bytes() == (replay / "summary.json").read_bytes()
assert (B / "summary.json").read_bytes() == (r4 / "summary.json").read_bytes()
old_open, new_open = (set(s.pop("open_ticket_landings")) for s in (original, inverted))
assert len(old_open) == 21 and len(new_open) == 41 and not old_open & new_open
assert original == inverted

landings, former = (read(root, "landings.json") for root in (B, r4))
rows = copy.deepcopy(landings["by_ticket"])
scopes = {row["ticket"]: row.pop("attribution_scopes") for row in rows}
assert dict(landings, by_ticket=rows) == former
commits = {row["ticket"]: set(row["commits"]) for row in rows}
assert old_open | new_open == {str(n) for n in commits} and "1406" in old_open
assert (len(commits), sum(map(len, commits.values())), len(landings["by_commit"]),
        len(read(B, "pre.json"))) == (62, 133, 115, 1025)

issues = read(B, "sources.json")["issues"]
parents = {row["number"]: row["parent"] for row in issues} | {1493: 1360}
native_tb = {1358 + i: f"TB-{i:02d}" for i in range(1, 11)}
native = {}
for n in commits:
    chain = [n]
    while chain[-1] not in native_tb and parents.get(chain[-1]) is not None:
        assert parents[chain[-1]] not in chain
        chain.append(parents[chain[-1]])
    if chain[-1] in native_tb:
        native[n] = native_tb[chain[-1]]
supplements = {row["ticket"]: row["attribution_scopes"] for row in census["attributions"]}
assert len(supplements) == 33 and set(supplements) == commits.keys() - native.keys()
assert all(scopes[n] == (supplements[n] if n in supplements else [native[n]]) for n in commits)
exclusive = set.union(*(commits[n] for n in supplements)) - set.union(*(commits[n] for n in native))
assert len(exclusive) == 61
for ticket, expected in {1493: ["TB-02"], 1495: ["TB-02"], 1608: ["TB-03"],
                         1653: ["TB-02", "TB-10"], 1737: ["TB-03"], 1678: ["GRAPH"]}.items():
    assert scopes[ticket] == expected

attributions = census["attributions"]
bad = [
    attributions[1:],
    [attributions[0], *attributions],
    [dict(attributions[0], attribution_scopes=["GRAPH", "TB-03"]), *attributions[1:]],
    [dict(attributions[0], attribution_scopes=["TB-11"]), *attributions[1:]],
    [dict(attributions[0], attribution_scopes=["TB-03", "TB-03"]), *attributions[1:]],
    [*attributions, dict(attributions[-1], ticket=999999)],
]
for candidate in bad:
    try:
        landing_scopes(issues, set(commits), candidate)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid scope accepted")

f = landings["observation"]
path = ".chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/IMPLEMENTATION-CROSSWALK.json"
cw = json.loads(subprocess.check_output(["git", "show", f"{f}:{path}"]))
spec = {"story_ids": ("rows", "story_id"), "family_entry_ids": ("family_entry_links", "id"),
        "detailed_acceptance_ids": ("detailed_acceptance_links", "id")}
by_kind = {k: {r[id_col]: r for r in cw[table]} for k, (table, id_col) in spec.items()}
def project(closure):
    return {(n, scope) for n, ss in scopes.items() for scope in ss if scope in closure or scope == "GRAPH"}


narrow = project({"TB-10"})
assert (1653, "TB-10") in narrow and (1653, "TB-02") not in narrow
assert (1737, "TB-03") not in narrow and (1678, "GRAPH") in narrow
routed = set()
print("r5: verified 4 census pins; 62 tickets, 133 pairs, 115 unique landings, 1025 PRE paths")
print("r5: 33 non-native mappings with 61 exclusive commits; 6 invalid mapping fixtures rejected")
for dst in cw["destination_success_obligations"]:
    closure = {s for k in spec for i in dst[k] for s in by_kind[k][i]["success_closure_slice_ids"]}
    pairs = project(closure)
    ticket_ids = {n for n, _ in pairs}
    dst_commits = {f} | {sha for n in ticket_ids for sha in commits[n]}
    assert "TB-11" in closure
    assert (1678, "GRAPH") in pairs
    routed |= ticket_ids
    print(f"{dst['destination_id']}: {len(pairs)} R10 ticket/scope pairs, "
          f"{len(ticket_ids)} R10 ticket IDs, {len(dst_commits)} unique commits including F")
assert routed == commits.keys()
print("r5: 9/9 files replay byte-for-byte; state inversion 8/8 stable and summary state-only 21 -> 41")
