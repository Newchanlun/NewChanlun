import concurrent.futures
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).parent
REPO = "repos/Newchanlun/NewChanlun"
G0 = "bd54d4b28ec4f83d596837f84f1f861dd085124c"

def call(*cmd):
    return subprocess.check_output(cmd, text=True).strip()

def api(route, qs):
    result = call("gh", "api", "--paginate", f"{REPO}/{route}", "--jq", qs)
    return [json.loads(x) for x in result.splitlines()]

def review_row(line):
    merge, p1, head, *_ = line.split()
    prs = api(f"commits/{merge}/pulls",
        f'.[] | select(.merge_commit_sha=="{merge}" and .base.ref=="main" and .head.sha=="{head}" and .merged_at!=null) | .number')
    statuses = api(f"commits/{head}/statuses",
        '.[] | select(.context=="deepagents/review") | {id,state,creator:.creator.login}')
    pair = call("git", "rev-parse", merge+"^{tree}", head+"^{tree}").splitlines()
    return {"merge":merge,"first_parent":p1,"head":head,"trees":pair,
            "prs":prs,"status": statuses[0] if statuses else None}

def historical(sha):
    rs = api(f"actions/runs?head_sha={sha}", '.workflow_runs[] | select(.event=="push" and (.path==".github/workflows/ci.yml" or .path==".github/workflows/devskim.yml")) | {id,path,status,conclusion}')
    return {"commit":sha,"runs":rs}

def count_keys():
    spec = Path(".chanlun/review-results/issue1339-r2-spec-20260909/payload/spec")
    ins = Path(".chanlun/review-results/issue1340-publication-20260909/payload/inputs")
    cw = json.loads((spec/"IMPLEMENTATION-CROSSWALK.json").read_bytes())
    names = [("rows","story_id","story_ids"),("family_entry_links","id","family_entry_ids"),("detailed_acceptance_links","id","detailed_acceptance_ids")]
    units = [u for region in ("TB01", "TB02-06", "TB07-11") for u in json.loads((ins/f"{region}-EXECUTION-SLICES.json").read_bytes())["units"]]
    keys = Counter()
    no_leaf = Counter()
    for section, identifier, unit_field in names:
        for row in cw[section]:
            for tb in row["success_closure_slice_ids"]:
                keys[tb] += 1
                if tb != "TB-11" and not any(tb==u["parent_tb"] and row[identifier] in u[unit_field] for u in units):
                    no_leaf[tb] += 1
    old = cw["slice_success_obligations"][0]
    print("keys", sum(keys.values()), dict(sorted(keys.items())))
    print("without_leaf", sum(no_leaf.values()), dict(sorted(no_leaf.items())))
    print("TB01_omitted_stories", sorted({r["story_id"] for r in cw["rows"] if "TB-01" in r["success_closure_slice_ids"]}-set(old["story_ids"])))
    print("every_destination_links_US-ENG-10", all("US-ENG-10" in r["story_ids"] for r in cw["destination_success_obligations"]))

if __name__ == "__main__":
    count_keys()
    prefixes = "2212eba31e d2219e8e01 e46cf3bca6 21b7898a 65298686cf 2706d87f abf5c0f8 c65f0219 8619a20f2800 f95a7f3e 465174240b 28df886697 b63a3fd586 6badaa6049 24c2fa068f".split()
    historical_shas = call("git","rev-parse",*prefixes).splitlines()
    chain = call("git","rev-list","--first-parent","--parents",G0+"^1..origin/main").splitlines()
    if "--local" not in sys.argv:
        with concurrent.futures.ThreadPoolExecutor(5) as pool:
            for name, rows in (("historical",pool.map(historical,historical_shas)),("postgate",pool.map(review_row,chain))):
                with (OUT/f"{name}.jsonl").open("w") as f:
                    for row in rows:
                        print(json.dumps(row),file=f,flush=True)
    boundary = G0+"^1"
    residual = set()
    for sha in historical_shas:
        residual.update(call("git","diff","--name-only","--no-renames",sha+"^1",sha).splitlines())
    p0 = set(call("git","ls-tree","-r","--name-only",boundary).splitlines())
    f = set(call("git","ls-tree","-r","--name-only","origin/main").splitlines())
    residual = residual & p0 & f
    print("current_residual_paths",len(residual))
    print("traditional_non_report_paths",sum(not p.startswith(".chanlun/review-results/") for p in residual))
    print("roster_retained", ".chanlun/agent-roster-2026-09-13.md" in residual)
