"""Actions 作业计划、分组运行、封印；不接受手动 dispatch 输入。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from adapter import experiment_authority, profile_token, require_query_only, timestamp
from check_selector import selector_matches
from common import Invalid, SHA, git, json_bytes, read_regular, require, sha, strict_json, unique
from registry import load
from run_checks import run_group, run_identity, validate_record

FIRST_LIMIT = 256
EXECUTION_FIELDS = {"check_id", "argv", "expected", "executed", "ignored", "skipped",
                    "exit_code", "tests", "status", "diagnostic"}
AUTH_COMMENTS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    issue(number: $number) {
      number
      comments(first: 100, after: $endCursor) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { fullDatabaseId body createdAt lastEditedAt }
      }
    }
  }
}
"""


def action_outputs(values):
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        for name, value in values.items():
            print(f"{name}={value}", file=stream)


def groups_of(loaded, evidence):
    return sorted({c["group"] for c in loaded[0]["checks"] if c["evidence_class"] == evidence})


def bundle_name(evidence, attempt, group):
    return f"at18-{attempt}-{evidence}-" + ("scaffold" if group is None else "g-" + group)


def authority_comment(repo, rule, token):
    if rule["comment_id"] is None:
        return None
    # 完整分页取原件；签署后新增无法核实的评论（可能撤回）保持阻断。
    ticket = rule["ticket"]
    scope = f"ticket:{ticket}"
    try:
        require(token, "AUTH_REQUIRED", scope)

        def gh(*args):
            result = subprocess.run(["gh", "api", *args], capture_output=True,
                                    env=os.environ | {"GH_TOKEN": token})
            require(result.returncode == 0, "AUTH_REQUIRED", scope)
            return result.stdout
        resource = f"repos/{repo}/issues/{ticket}"
        issue = strict_json(gh(resource), "authorization issue")
        require(issue.get("state_reason") not in ("not_planned", "duplicate"),
                "AUTH_REQUIRED", scope)
        owner, name = repo.split("/")
        pages = strict_json(gh("graphql", "--paginate", "--slurp", "-f", "query=" + AUTH_COMMENTS_QUERY,
                               "-f", "owner=" + owner, "-f", "name=" + name, "-F", f"number={ticket}"),
                            "authorization comments", object_root=False)
        require(isinstance(pages, list) and pages, "AUTH_REQUIRED", scope)
        comments, totals = {}, []
        for index, page in enumerate(pages):
            require(isinstance(page, dict) and not page.get("errors"), "AUTH_REQUIRED", scope)
            repository = page["data"]["repository"]
            actual_repo = repository["nameWithOwner"]
            issue = repository["issue"]
            require(isinstance(actual_repo, str) and actual_repo.casefold() == repo.casefold()
                    and issue["number"] == ticket, "AUTH_REQUIRED", scope)
            connection = issue["comments"]
            require(connection["pageInfo"]["hasNextPage"] is (index < len(pages) - 1)
                    and isinstance(connection["nodes"], list), "AUTH_REQUIRED", scope)
            totals.append(connection["totalCount"])
            for row in connection["nodes"]:
                cid = row["fullDatabaseId"]
                if isinstance(cid, str) and cid.isascii() and cid.isdecimal():
                    cid = int(cid)
                require(type(cid) is int and cid > 0 and cid not in comments, "AUTH_REQUIRED", scope)
                comments[cid] = row
        require(all(type(n) is int and n == len(comments) for n in totals), "AUTH_REQUIRED", scope)
        pin = comments[rule["comment_id"]]
        signed = timestamp(pin["createdAt"])
        require(pin["lastEditedAt"] is None, "AUTH_REQUIRED", scope)
        for cid, row in comments.items():
            if cid == rule["comment_id"]:
                continue
            created = timestamp(row["createdAt"])
            edited = None if row["lastEditedAt"] is None else timestamp(row["lastEditedAt"])
            # GitHub 的时间戳不能用评论 ID 补出编辑顺序；同一秒一律不推断先后。
            require(created[0] < signed[0] and (edited is None or created <= edited and edited[0] < signed[0]),
                    "AUTH_REQUIRED", scope)
        return {"id": rule["comment_id"], "issue_url": f"https://api.github.com/{resource}", "body": pin["body"]}
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise Invalid(f"AUTH_REQUIRED: {scope}") from error


def authorize(loaded, groups, token=None):
    registry, contract, _, _, _ = loaded
    rule = contract["experiment_authorization"]
    require_query_only(contract, groups)
    repo = os.environ["GITHUB_REPOSITORY"]
    comments = {2133: authority_comment(repo, rule, token or os.environ.get("GH_TOKEN"))}
    return experiment_authority(contract, comments, repo=repo, profile_id=registry["experiment_profile_id"],
                                now=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                groups=groups)


def plan(loaded, evidence, *, authorize_groups=authorize):
    groups = groups_of(loaded, evidence)
    require(len(groups) <= FIRST_LIMIT, "CHECK_JOB_MISSING", "Actions group matrix limit")
    auth = authorize_groups(loaded, groups) if groups and evidence == "experiment" else {}
    return {"registry_sha": loaded[2], "has_groups": str(bool(groups)).lower(),
            "groups": json_bytes({"include": [{"group": g} for g in groups]}).decode().rstrip(),
            "runner_group": auth.get("runner_group", ""), "runner_label": auth.get("runner_label", "")}


def producer_job_name(loaded, evidence, group):
    prefix = f"at18-scaffold {evidence}" if group is None else f"at18 {group}"
    return f"{prefix} {loaded[2]}"


def producer_anchors(loaded, evidence, identity, pages):
    """只从本 attempt 成功生产作业的服务端 step 元数据取摘要，不从 artifact 取。"""
    groups = groups_of(loaded, evidence) or [None]
    expected = {producer_job_name(loaded, evidence, group): group for group in groups}
    anchors = {}
    jobs = [job for page in pages for job in page["jobs"]]
    require(pages and all(type(page["total_count"]) is int and page["total_count"] == len(jobs)
                          for page in pages), "RECORD_UNSEALED", "incomplete producer job pagination")
    for job in jobs:
        if job["name"] not in expected:
            continue
        group = expected[job["name"]]
        require(group not in anchors and all(job[key] == value for key, value in {
            "head_sha": identity["head"], "run_id": identity["run_id"], "run_attempt": identity["run_attempt"],
            "head_branch": "main", "status": "completed", "conclusion": "success",
        }.items()), "RECORD_UNSEALED", "producer job identity")
        steps = [step for step in job["steps"] if step["name"].startswith("at18-anchor ")]
        require(len(steps) == 1, "RECORD_UNSEALED", "producer anchor count")
        step = steps[0]
        digest = step["name"].removeprefix("at18-anchor ")
        require(step["status"] == "completed" and step["conclusion"] == "success" and SHA.fullmatch(digest),
                "RECORD_UNSEALED", "producer anchor identity")
        anchors[group] = digest
    require(anchors.keys() == set(groups),
            "RECORD_UNSEALED", "missing producer anchors")
    return anchors


def fetch_producer_jobs(identity):
    resource = (f"repos/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{identity['run_id']}"
                f"/attempts/{identity['run_attempt']}/jobs?per_page=100")
    require(os.environ.get("GH_TOKEN"), "RECORD_UNSEALED", "producer Jobs API authorization")
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", resource], capture_output=True)
    require(result.returncode == 0, "RECORD_UNSEALED", "producer Jobs API")
    return strict_json(result.stdout, "producer Jobs API", object_root=False)


def _manifest(loaded, evidence, group, identity, bundle, expected_sha):
    reg, contract, digest, _, _ = loaded
    raw_manifest = read_regular(bundle, "execution.json")
    require(isinstance(expected_sha, str) and SHA.fullmatch(expected_sha)
            and sha(raw_manifest) == expected_sha, "RECORD_UNSEALED", "producer manifest sha256")
    manifest = strict_json(raw_manifest, "execution.json")
    require(manifest.keys() == {"schema_version", "registry_sha256", *identity, "group",
                                "evidence_class", "checks", "records"}
            and all(manifest[k] == v for k, v in {
                "schema_version": "at18-group-execution/1", "registry_sha256": digest,
                "group": group, "evidence_class": evidence, **identity,
            }.items()), "RECORD_UNSEALED", "execution manifest")
    expected = {c["check_id"]: c for c in reg["checks"] if (c["evidence_class"], c["group"]) == (evidence, group)}
    require(expected.keys() == unique((r["check_id"] for r in manifest["checks"]), "RECORD_UNSEALED", "checks"),
            "RECORD_UNSEALED", "group checks")
    for result in manifest["checks"]:
        check = expected[result["check_id"]]
        require(result.keys() == EXECUTION_FIELDS and result["status"] == "PASS" and result["diagnostic"] is None
                and result["expected"] == result["executed"] == check["expected_count"]
                and result["exit_code"] == result["skipped"] == result["ignored"] == 0
                and isinstance(result["argv"], list) and bool(result["argv"])
                and all(isinstance(a, str) for a in result["argv"])
                and isinstance(result["tests"], list) and len(result["tests"]) == result["executed"],
                "RECORD_UNSEALED", "execution counts")
        names = unique((row["name"] for row in result["tests"]), "RECORD_UNSEALED", "test identities")
        require(all(selector_matches(check, name) for name in names)
                and all(row["status"] == "passed" for row in result["tests"]),
                "RECORD_UNSEALED", "execution identities")
    paths, producer_ids, seals = set(), set(), []
    for row in manifest["records"]:
        require(row.keys() == {"path", "record", "sha256", "check_id", "profile_id"}
                and isinstance(row["sha256"], str) and SHA.fullmatch(row["sha256"])
                and row["path"] == "record-" + row["sha256"] + ".json" and row["path"] not in paths,
                "RECORD_UNSEALED", "inventory path")
        check = expected.get(row["check_id"])
        require(check and row["record"] == check["record"] and row["profile_id"] == check["profile_id"],
                "RECORD_UNSEALED", "inventory owner")
        raw = read_regular(bundle, row["path"])
        require(sha(raw) == row["sha256"], "RECORD_UNSEALED", "record sha256")
        validate_record(contract, strict_json(raw, "record"), check, identity)
        paths.add(row["path"])
        producer_ids.add(row["check_id"])
        seals.append(dict(group=group, record=row["record"], profile=profile_token(row["profile_id"]),
                          sha256=row["sha256"], execution_sha=expected_sha))
    require(producer_ids == {cid for cid, c in expected.items() if c["record"] is not None}
            and {p.name for p in bundle.iterdir()} == paths | {"execution.json"},
            "RECORD_UNSEALED", "inventory coverage")
    return seals


def seal_matrix(loaded, evidence, identity, artifacts, anchors):
    groups = groups_of(loaded, evidence)
    expected = {bundle_name(evidence, identity["run_attempt"], group): group for group in groups or [None]}
    require({path.name for path in artifacts.iterdir()} == expected.keys()
            and anchors.keys() == set(expected.values()), "RECORD_UNSEALED", "group inventory")
    seals, scaffold_sha = [], ""
    for name, group in expected.items():
        require(not (artifacts / name).is_symlink(), "RECORD_UNSEALED", "group path")
        seals.extend(_manifest(loaded, evidence, group, identity, artifacts / name, anchors[group]))
        if group is None:
            scaffold_sha = anchors[group]
    require(len(seals) <= FIRST_LIMIT, "RECORD_UNSEALED", "Actions seal matrix limit")
    unique(((r["record"], r["profile"], r["sha256"]) for r in seals), "RECORD_UNSEALED", "duplicate seals")
    return {"has_seals": str(bool(seals)).lower(), "scaffold_sha": scaffold_sha,
            "seals": json_bytes({"include": seals}).decode().rstrip()}


def seal_scaffold(loaded, evidence, identity, artifacts, expected_sha, output):
    require(not groups_of(loaded, evidence) and expected_sha and SHA.fullmatch(expected_sha),
            "RECORD_UNSEALED", "scaffold identity")
    require(not _manifest(loaded, evidence, None, identity, artifacts, expected_sha),
            "RECORD_UNSEALED", "scaffold inventory")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": "at18-scaffold-seal/1", "registry_sha256": loaded[2], **identity,
               "evidence_class": evidence, "execution_sha256": expected_sha}
    (output / "scaffold-seal.json").write_bytes(json_bytes(receipt))



def failure_diagnostic(output, evidence, identity):
    # 不读取任何失败作业文件；新建且仅接受固定身份和固定分类。
    expected = {"schema_version": "at18-diagnostic/1", **identity,
                "evidence_class": evidence, "status": "GROUP_REJECTED"}
    with output.open("xb") as stream:
        stream.write(json_bytes(expected))
    require(strict_json(read_regular(output.parent, output.name), "diagnostic") == expected,
            "RECORD_PUBLIC_SCHEMA", "diagnostic fields")

def main():
    parser = argparse.ArgumentParser(description="在 Actions 固定 F 上运行和封印 AT-18")
    parser.add_argument("operation", choices=("plan", "run", "seal-plan", "seal", "seal-scaffold", "diagnostic"))
    parser.add_argument("evidence", choices=("simulation", "experiment"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--group")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--record")
    parser.add_argument("--profile")
    parser.add_argument("--sha256")
    parser.add_argument("--execution-sha")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        identity = run_identity(os.environ["GITHUB_SHA"], int(os.environ["GITHUB_RUN_ID"]),
                                int(os.environ["GITHUB_RUN_ATTEMPT"]))
        require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
                and os.environ.get("GITHUB_REF") == "refs/heads/main"
                and identity["head"] == git(root, "rev-parse", "HEAD").decode().strip(),
                "RUN_IDENTITY", "main dispatch")
        if args.operation == "diagnostic":
            require(args.output is not None, "RECORD_PUBLIC_SCHEMA", "missing diagnostic path")
            failure_diagnostic(args.output, args.evidence, identity)
            return 0
        # GitHub 提供运行身份；登记册和原件从这次 checkout 读，不从事件 payload 取值。
        loaded = load(root)
        if args.operation == "plan":
            action_outputs(plan(loaded, args.evidence))
        elif args.operation == "run":
            require(args.output is not None, "RUN_IDENTITY", "missing output directory")
            # 令牌只用于查签署原件，不进入被执行检查的环境。在每个检查启动前重取当前授权。
            token = os.environ.pop("GH_TOKEN", None)
            before_check = None
            if args.evidence == "experiment" and args.group is not None:
                def before_check():
                    auth = authorize(loaded, [args.group], token)
                    require((auth["runner_group"], auth["runner_label"]) ==
                            (os.environ.get("AT18_RUNNER_GROUP"), os.environ.get("AT18_RUNNER_LABEL"))
                            and os.environ.get("AT18_RUNNER_ENVIRONMENT") == "self-hosted",
                            "AUTH_REQUIRED", "runner scope")
            if not run_group(root, loaded, args.evidence, args.group, identity, args.output,
                             before_check=before_check, head=identity["head"]):
                return 1
            digest = sha(read_regular(args.output, "execution.json"))
            _manifest(loaded, args.evidence, args.group, identity, args.output, digest)
            action_outputs({"execution_sha": digest})
        elif args.operation == "seal-plan":
            anchors = producer_anchors(loaded, args.evidence, identity, fetch_producer_jobs(identity))
            action_outputs(seal_matrix(loaded, args.evidence, identity, args.artifacts, anchors))
        elif args.operation == "seal-scaffold":
            seal_scaffold(loaded, args.evidence, identity, args.artifacts, args.sha256, args.output)
        else:
            require(args.group in groups_of(loaded, args.evidence), "RECORD_UNSEALED", "unknown group")
            seals = _manifest(loaded, args.evidence, args.group, identity, args.artifacts, args.execution_sha)
            require(sum((row["record"], row["profile"], row["sha256"]) == (args.record, args.profile, args.sha256)
                        for row in seals) == 1, "RECORD_UNSEALED", "seal identity")
        return 0
    except (ValueError, KeyError, TypeError, OSError, SyntaxError) as error:
        print(f"AT-18: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
