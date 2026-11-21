#!/usr/bin/env python3
"""Rebuild ADR 0064's historical landing/path census from a complete Git graph.

Online capture: python3 rebuild_pregate.py --capture --out <dir>
Offline replay: python3 rebuild_pregate.py --source <dir>/sources.json --out <dir>
Run from a clone with full history and origin/main. The capture and replay paths
share the projection, but replay never consults GitHub or uses hand-picked SHAs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

REPO = "repos/Newchanlun/NewChanlun"
G0 = "bd54d4b28ec4f83d596837f84f1f861dd085124c"
GRAPH = 1323
SPEC = 1340
TBS = tuple(range(1359, 1369))
SPECIAL_PARENT = {1493: 1360}
WORKFLOWS = (".github/workflows/ci.yml", ".github/workflows/devskim.yml")
PR_HINT = re.compile(r"(?i)\b(?:merge(?: approved)? (?:pull request|PR)|pull request|PR) #([1-9][0-9]*)|\(#([1-9][0-9]*)\)\s*$")
URL_PR = re.compile(r"https://github\.com/(?:Newchanlun|xy7365527-lang)/NewChanlun/pull/([1-9][0-9]*)", re.I)
TICKET = re.compile(r"(?<![\w#])#([1-9][0-9]*)\b|https://github\.com/(?:Newchanlun|xy7365527-lang)/NewChanlun/issues/([1-9][0-9]*)\b", re.I)
LEADING_OWNERS = re.compile(
    r"^(?:(?:[\w.-]+(?:\([^()]*\))?|Sandcastle)\s*[: ]\s*)?(?:[\[(]\s*)?"
    r"(#[0-9]+(?:[ ,/#、，]+#?[0-9]+)*)"
)
OWNER_REF = re.compile(r"^(?:(?:codex|opus|claude|sandcastle|fix|impl|feat|decision)/)*(?:issue[-/]?)?([0-9]+)(?:[-_/]|$)", re.I)
SHA = re.compile(r"(?<![0-9a-f])([0-9a-f]{7,40})(?![0-9a-f])")
TB_CODE = re.compile(r"(?i)(?<![\w-])TB-(?:0[1-9]|10)(?:-[A-Z0-9]+)?(?![\w-])")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args])


def gh(*args: str) -> dict | list:
    return json.loads(subprocess.check_output(["gh", "api", *args]))


def pages(route: str) -> list:
    records = gh("--paginate", "--slurp", f"{REPO}/{route}")
    if not isinstance(records, list) or not records or any(not isinstance(p, list) for p in records):
        raise ValueError(f"not a complete array response: {route}")
    return [item for page in records for item in page]


def refs(pattern: re.Pattern, value: str) -> set[int]:
    return {int(x if isinstance(x, str) else next(i for i in x if i)) for x in pattern.findall(value)}


def leading(value: str) -> set[int]:
    match = LEADING_OWNERS.match(value)
    return {int(n) for n in re.findall(r"[0-9]+", match[1])} if match else set()


def git_history(f: str) -> tuple[str, list[dict]]:
    if git("rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("complete first-parent history required")
    if subprocess.run(["git", "merge-base", "--is-ancestor", f, "origin/main"], check=False).returncode:
        raise ValueError("observation must be reachable from origin/main")
    if f not in git("rev-list", "--first-parent", "origin/main").decode().splitlines():
        raise ValueError("observation must be on origin/main first-parent chain")
    if G0 not in git("rev-list", "--first-parent", f).decode().splitlines():
        raise ValueError("G0 missing on the first-parent chain")
    p0 = git("rev-parse", f"{G0}^1").decode().strip()
    # Use NUL separators: Markdown/newlines in a commit body are not record boundaries.
    chunks = git("log", "-z", "--first-parent", "--format=%H%x00%P%x00%ct%x00%s%x00%b", p0).split(b"\0")
    rows = []
    fields = iter(chunks[:-1])
    for sha, parents, epoch, subject, body in zip(fields, fields, fields, fields, fields, strict=True):
        rows.append(dict(commit=sha.decode(), parents=parents.decode().split(),
                         epoch=int(epoch), subject=subject.decode("utf-8", "replace"),
                         body=body.decode("utf-8", "replace")))
    return p0, rows


def inventory_issues(pool: ThreadPoolExecutor) -> tuple[str, list[dict]]:
    root = gh(f"{REPO}/issues/{GRAPH}")
    edges = {}
    issues = {}
    pending = {GRAPH, SPEC, *TBS}
    while pending:
        items = sorted(pending)
        found = list(pool.map(lambda n: pages(f"issues/{n}/sub_issues?per_page=100"), items))
        pending.clear()
        for parent, children in zip(items, found, strict=True):
            edges[parent] = sorted(item["number"] for item in children)
            for item in children:
                n = item["number"]
                if n in issues and issues[n][0] != parent:
                    raise ValueError(f"ambiguous native parent for #{n}")
                issues[n] = (parent, item)
                if n not in edges and (parent != GRAPH or any(label["name"] == "wayfinder:impl" for label in item["labels"])):
                    pending.add(n)
        pending.difference_update(edges)
    for n in sorted(set(TBS) - issues.keys()):
        item = gh(f"{REPO}/issues/{n}")
        issues[n] = (None, item)
    rows = [dict(number=n, parent=parent, state=item["state"], state_reason=item["state_reason"],
                 impl=any(label["name"] == "wayfinder:impl" for label in item["labels"]))
            for n, (parent, item) in sorted(issues.items())]
    return root["created_at"], rows


def owners(issues: list[dict]) -> set[int]:
    # The slice tickets remain in scope even if their issue type or state changes.
    # Non-implementation descendants are searched via their parent/project links,
    # not automatically treated as product owners.
    return {*TBS, *SPECIAL_PARENT, *(i["number"] for i in issues if i["impl"])}


def pr_batch(numbers: list[int]) -> list[dict]:
    fields = "number mergedAt baseRefName headRefName mergeCommit{oid} title body closingIssuesReferences(first:100){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage}}"
    query = '{repository(owner:"Newchanlun",name:"NewChanlun"){'
    query += " ".join(f"p{n}:issueOrPullRequest(number:{n}){{__typename ... on PullRequest{{{fields}}}}}"
                      for n in numbers) + "}}"
    cmd = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                         capture_output=True, check=False)
    response = json.loads(cmd.stdout)
    aliases = {f"p{n}" for n in numbers}
    for error in response.get("errors", []):
        alias = error.get("path", [])
        if (len(alias) != 2 or alias[0] != "repository" or alias[1] not in aliases
                or error.get("type") != "NOT_FOUND"):
            raise ValueError(f"incomplete PR query: {error.get('type')}, {alias}")
    if cmd.returncode and not response.get("errors"):
        raise ValueError("GitHub PR request failed")
    repo = response["data"]["repository"]
    if set(repo) != aliases:
        raise ValueError("PR query omitted aliases")
    return [p for p in repo.values() if p and p["__typename"] == "PullRequest"]


def git_pr_hints(row: dict) -> set[int]:
    return refs(PR_HINT, row["subject"]) | refs(URL_PR, row["subject"] + "\n" + row["body"])


def captured_issue(n: int, known: set[int], known_prs: set[int], commit_ids: set[str]) -> list[dict]:
    issue = gh(f"{REPO}/issues/{n}")
    docs = [(issue["html_url"], issue["body"] or "")]
    docs += [(item["html_url"], item["body"] or "")
             for item in pages(f"issues/{n}/comments?per_page=100")]
    docs += [(item["source"]["issue"]["html_url"], item["source"]["issue"]["html_url"])
             for item in pages(f"issues/{n}/timeline?per_page=100")
             if item.get("event") == "cross-referenced" and (item.get("source") or {}).get("issue", {}).get("pull_request")]
    rows = []
    for url, body in docs:
        prs = refs(URL_PR, body) | (refs(PR_HINT, body) & known_prs)
        # Resolve only unique first-parent prefixes; a mention nominates a row for
        # adjudication, it does not claim authorship of that merge.
        commits = set()
        for aid in set(SHA.findall(body)):
            matches = [c for c in commit_ids if c.startswith(aid)]
            if len(matches) == 1:
                commits.add(matches[0])
        related = refs(TICKET, body) & (known - {n})
        if prs or commits or related:
            rows.append(dict(url=url, prs=sorted(prs), commits=sorted(commits),
                             related_tickets=sorted(related)))
    return rows


def merged_pr_index() -> dict[str, int]:
    index = {}
    for row in pages("pulls?state=closed&base=main&per_page=100&sort=created&direction=desc"):
        sha = row["merge_commit_sha"]
        if row["merged_at"] is None or sha is None:
            continue
        if sha in index and index[sha] != row["number"]:
            raise ValueError(f"ambiguous exact PR merge object: {sha}")
        index[sha] = row["number"]
    return index


def capture(rows: list[dict], followups: set[int]) -> dict:
    with ThreadPoolExecutor(max_workers=8) as pool:
        created, issues = inventory_issues(pool)
        start = int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp())
        missing = sorted(followups - {i["number"] for i in issues})
        for item in pool.map(lambda n: gh(f"{REPO}/issues/{n}"), missing):
            issues.append(dict(number=item["number"], parent=None, state=item["state"],
                               state_reason=item["state_reason"], impl=False))
        issues.sort(key=lambda i: i["number"])
        known = owners(issues) | followups
        ids = {r["commit"] for r in rows}
        # Review all first-parent git objects. The birth date only bounds GitHub
        # PR metadata for unreferenced older rows; named older inputs remain eligible.
        pr_ids = set().union(*(git_pr_hints(r) for r in rows if r["epoch"] >= start or
                              refs(TICKET, r["subject"] + "\n" + r["body"]) & known))
        index = merged_pr_index()
        pr_ids.update(index[c] for c in ids & index.keys())
        evidence = dict(zip(sorted(known), pool.map(
            lambda n: captured_issue(n, known, pr_ids, ids), sorted(known)), strict=True))
        pr_ids.update(p for records in evidence.values() for row in records for p in row["prs"])
        all_ids = sorted(pr_ids)
        prs = {}
        for batch in pool.map(pr_batch, [all_ids[i:i+20] for i in range(0, len(all_ids), 20)]):
            for p in batch:
                close = p["closingIssuesReferences"]
                if close["pageInfo"]["hasNextPage"]:
                    raise ValueError(f"truncated closing issues: PR #{p['number']}")
                text = p["title"] + "\n" + (p["body"] or "")
                branch = OWNER_REF.match(p["headRefName"])
                prs[p["number"]] = dict(
                    number=p["number"], merged_at=p["mergedAt"], base=p["baseRefName"],
                    commit=(p["mergeCommit"] or {}).get("oid"),
                    owners=sorted(({int(branch[1])} if branch else set()) & known | leading(p["title"]) & known),
                    closing=sorted(i["number"] for i in close["nodes"]
                                   if i["repository"]["nameWithOwner"].lower() == "newchanlun/newchanlun" and i["number"] in known),
                    mentions=sorted(refs(TICKET, text) & known),
                    tb_markers=sorted(set(TB_CODE.findall(p["title"]))),
                )
        return dict(graph_created_at=created, issues=issues, issue_evidence=evidence,
                    followups=sorted(followups), merge_index=index, pr_query_ids=all_ids, pull_requests=[prs[n] for n in sorted(prs)])


def candidates(rows: list[dict], data: dict) -> list[dict]:
    known = owners(data["issues"]) | set(data["followups"])
    linked = defaultdict(set)
    for raw_n, evidence in data["issue_evidence"].items():
        for record in evidence:
            for commit in record["commits"]:
                linked[commit].add((int(raw_n), record["url"]))
    prs = defaultdict(list)
    for pr in data["pull_requests"]:
        if pr["base"] == "main" and pr["merged_at"] and pr["commit"]:
            prs[pr["commit"]].append(pr)
            for raw_n, evidence in data["issue_evidence"].items():
                for record in evidence:
                    if pr["number"] in record["prs"]:
                        linked[pr["commit"]].add((int(raw_n), record["url"]))
    out = []
    for row in rows:
        sha = row["commit"]
        metadata = row["subject"] + "\n" + row["body"]
        declared = (leading(row["subject"]) | refs(
            re.compile(r"(?im)^(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|part of)\s+#([1-9][0-9]*)"),
            row["body"])) & known
        mentions = refs(TICKET, metadata) & known
        pr_rows = prs[sha]
        for pr in pr_rows:
            declared.update(pr["owners"], pr["closing"])
            mentions.update(pr["mentions"])
        tb = sorted(set(TB_CODE.findall(row["subject"])) |
                    {code for pr in pr_rows for code in pr["tb_markers"]})
        links = [{"ticket": num, "url": url} for num, url in sorted(linked[sha])]
        out.append(dict(commit=sha, parent=row["parents"][0] if row["parents"] else None,
                        epoch=row["epoch"], subject=row["subject"], prs=[p["number"] for p in pr_rows],
                        declared=sorted(declared), mentions=sorted(mentions),
                        references=links, tb_markers=tb))
    return out


def tree(sha: str) -> dict[str, dict]:
    out = {}
    for entry in git("ls-tree", "-r", "-z", sha).split(b"\0"):
        if not entry:
            continue
        identity, path = entry.split(b"\t", 1)
        mode, kind, oid = map(bytes.decode, identity.split())
        out[path.decode("utf-8", "strict")] = dict(mode=mode, type=kind, oid=oid)
    return out


def changed(parent: str, sha: str) -> set[str]:
    return {p.decode("utf-8", "strict") for p in
            git("diff", "--name-only", "--no-renames", "-z", parent, sha).split(b"\0") if p}


def run_observations(sha: str) -> tuple[str, dict]:
    out = {}
    for path in WORKFLOWS:
        route = f"actions/workflows/{Path(path).name}/runs?head_sha={sha}&branch=main&event=push&per_page=100"
        results = gh("--paginate", "--slurp", f"{REPO}/{route}")
        if not isinstance(results, list) or not results:
            raise ValueError(f"missing response for {sha}/{path}")
        runs = []
        for page in results:
            for r in page["workflow_runs"]:
                if r["head_sha"] != sha or r["head_branch"] != "main" or r["event"] != "push":
                    raise ValueError(f"GitHub returned an out-of-scope run {r['id']}")
                runs.append(dict(id=r["id"], status=r["status"], conclusion=r["conclusion"],
                                 url=r["html_url"], attempt=r["run_attempt"]))
        if len({r["id"] for r in runs}) != len(runs):
            raise ValueError(f"duplicate push run for {sha}/{path}")
        out[path] = sorted(runs, key=lambda r: r["id"])
    return sha, out


def materialize(f: str, p0: str, history: list[dict], data: dict, adjudication: dict,
                out_dir: Path, observed: dict | None, capture_runs: bool) -> None:
    by_sha = {r["commit"]: r for r in history}
    landings = defaultdict(set)
    inverse = defaultdict(set)
    considered = {r["number"] for r in data["issues"]}
    admitted = {int(n) for n in adjudication["admitted_related"]}
    if admitted != set(data["followups"]):
        raise ValueError("discovery of non-native ownership requires an explicit scope disposition")
    for n in admitted:
        if not adjudication["admitted_related"][str(n)]["source"]:
            raise ValueError(f"related #{n} has no cited source")
    for record in history:
        for n in record["declared"]:
            inverse[record["commit"]].add(n)
    for row in adjudication["additional_associations"]:
        sha, n = row["commit"], row["ticket"]
        if n not in considered | admitted | owners(data["issues"]) or sha not in by_sha or not row["source"]:
            raise ValueError(f"unbound ownership addition: {row}")
        if n in inverse[sha]:
            raise ValueError(f"redundant attribution: #{n} at {sha}")
        inverse[sha].add(n)
    for row in adjudication["rejected_signals"]:
        sha, n = row["commit"], row["ticket"]
        if n not in inverse[sha] or not row["source"]:
            raise ValueError(f"unbound ownership exclusion: {row}")
        inverse[sha].remove(n)
    for sha, ns in sorted(inverse.items()):
        for n in sorted(ns):
            landings[n].add(sha)
    members = {sha: sorted(ns) for sha, ns in sorted(inverse.items()) if ns}
    if not members:
        raise ValueError("empty graph landing ledger")
    p_tree, f_tree = tree(p0), tree(f)
    path_origins = defaultdict(list)
    diffs = {}
    for sha in members:
        delta = sorted(changed(by_sha[sha]["parent"], sha))
        diffs[sha] = delta
        for path in delta:
            path_origins[path].append(sha)
    after = {}
    post_changes = defaultdict(list)
    chain = git("rev-list", "--first-parent", "--reverse", f"{p0}..{f}").decode().splitlines()
    prior = p0
    for sha in chain:
        paths = changed(prior, sha)
        after[sha] = dict(parent=prior, changed_graph_paths=sorted(paths & path_origins.keys()))
        for path in paths & path_origins.keys():
            post_changes[path].append(sha)
        prior = sha
    path_rows = []
    states = Counter()
    for path, origins in sorted(path_origins.items()):
        before, at = p_tree.get(path), f_tree.get(path)
        state = ("ABSENT_P0" if before is None else "ABSENT_F" if at is None else
                 "SURVIVING_POSTGATE_TOUCHED" if post_changes[path] else "SURVIVING_UNTOUCHED")
        states[state] += 1
        path_rows.append(dict(path=path, pre_gate_commits=origins, at_p0=before, at_f=at,
                              disposition=state, post_gate_commits=post_changes[path]))
    pre = [r for r in path_rows if r["at_p0"] and r["at_f"]]
    if any(r["at_p0"]["type"] != "blob" or r["at_f"]["type"] != "blob" for r in pre):
        raise ValueError("unhandled PRE object type")
    write(out_dir / "landings.json", dict(p0=p0, observation=f, gate=G0,
          by_ticket=[dict(ticket=n, commits=sorted(shas)) for n, shas in sorted(landings.items())],
          by_commit=[dict(commit=sha, parent=by_sha[sha]["parent"], tickets=ns,
                          prs=by_sha[sha]["prs"], paths=diffs[sha]) for sha, ns in members.items()]))
    write(out_dir / "paths.json", path_rows)
    write(out_dir / "pre.json", [dict(path=r["path"], mode=r["at_p0"]["mode"], blob=r["at_p0"]["oid"]) for r in pre])
    write(out_dir / "postgate-path-history.json", after)
    created = int(datetime.fromisoformat(data["graph_created_at"].replace("Z", "+00:00")).timestamp())
    residual = []
    for row in history:
        if row["commit"] in members or row["epoch"] < created or row["parent"] is None:
            continue
        paths = changed(row["parent"], row["commit"])
        residual.append(dict(commit=row["commit"], prs=row["prs"],
                             graph_markers=row["tb_markers"], mentions=row["mentions"],
                             provenance_mentions=row["references"],
                             touched_paths=sorted(paths),
                             retained_overlap=sorted(paths & {x["path"] for x in pre})))
    write(out_dir / "unattributed-window-audit.json", residual)
    issue_state = {r["number"]: r["state"] for r in data["issues"]}
    open_landed = {}
    for n in sorted(landings):
        if issue_state.get(n) != "open":
            continue
        rows = [r for r in pre if set(r["pre_gate_commits"]) & landings[n]]
        open_landed[n] = dict(commits=sorted(landings[n]), surviving=len(rows),
                              untouched=sum(not r["post_gate_commits"] for r in rows))
    write(out_dir / "summary.json", dict(observed_main=f, p0=p0, gate=G0,
          enumerated_pre_gate_main_commits=len(history), pre_gate_landing_commits=len(members),
          ticket_commit_pairs=sum(map(len, landings.values())), landing_tickets=len(landings),
          pre_paths=len(pre), path_dispositions=states, open_ticket_landings=open_landed))
    if observed is not None:
        if sorted(observed) != sorted(members):
            raise ValueError("historical push observations do not cover the landing set")
        deviations = []
        for sha, ns in members.items():
            for path in WORKFLOWS:
                for item in observed[sha][path] or [None]:
                    if item and item["conclusion"] == "success":
                        continue
                    state = ("NO_RUN" if item is None else "INCOMPLETE"
                             if item["status"] != "completed" else (item["conclusion"] or "UNKNOWN").upper())
                    for n in ns:
                        deviations.append(dict(ticket=n, commit=sha, workflow=path, observed=state,
                                               run_id=item["id"] if item else None))
        write(out_dir / "historical-deviations.json", sorted(deviations, key=lambda r: (
            r["ticket"], r["commit"], r["workflow"], r["run_id"] or 0)))

    if capture_runs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            write(out_dir / "historical-runs.json", dict(pool.map(run_observations, members)))

def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    inputs = cli.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--capture", action="store_true")
    inputs.add_argument("--source", type=Path)
    cli.add_argument("--adjudication", type=Path)
    cli.add_argument("--followup", type=int, action="append", default=[])
    cli.add_argument("--historical-runs", type=Path)
    cli.add_argument("--capture-runs", action="store_true")
    cli.add_argument("--f", default="origin/main")
    cli.add_argument("--out", required=True, type=Path)
    args = cli.parse_args()
    f = git("rev-parse", "--verify", f"{args.f}^{{commit}}").decode().strip()
    p0, rows = git_history(f)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.capture:
        data = capture(rows, set(args.followup))
        write(args.out / "sources.json", data)
    else:
        data = json.loads(args.source.read_bytes())
    out = candidates(rows, data)
    (args.out / "all-first-parent.jsonl").write_text("".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in out), encoding="utf-8")
    write(args.out / "candidate-signals.json", [r for r in out if
          r["declared"] or r["mentions"] or r["references"] or r["tb_markers"]])
    if data.get("merge_index"):
        indexed = data["merge_index"]
        for row in out:
            if row["commit"] in indexed and indexed[row["commit"]] not in row["prs"]:
                raise ValueError(f"exact merge object omitted from PR capture: {row['commit']}")
    if args.adjudication:
        adjudication = json.loads(args.adjudication.read_bytes())
        observed = json.loads(args.historical_runs.read_bytes()) if args.historical_runs else None
        materialize(f, p0, out, data, adjudication, args.out, observed, args.capture_runs)


def write(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
