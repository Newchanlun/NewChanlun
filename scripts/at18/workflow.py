"""Actions 作业计划、分组运行、封印；不接受手动 dispatch 输入。"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from adapter import experiment_authority, profile_token, timestamp
from check_selector import selector_matches
from common import Invalid, SHA, git, json_bytes, read_regular, require, sha, strict_json, unique
from registry import load
from run_checks import run_group, run_identity, validate_record

FIRST_LIMIT = 256
EXECUTION_FIELDS = {"check_id", "argv", "expected", "executed", "ignored", "skipped",
                    "exit_code", "tests", "status", "diagnostic"}


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
    try:
        require(token, "AUTH_REQUIRED", f"ticket:{rule['ticket']}")

        def gh(*args):
            result = subprocess.run(["gh", "api", *args], capture_output=True,
                                    env=os.environ | {"GH_TOKEN": token})
            require(result.returncode == 0, "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
            return result.stdout
        resource = f"repos/{repo}/issues/{rule['ticket']}"
        issue = strict_json(gh(resource), "authorization issue")
        require(issue.get("state_reason") not in ("not_planned", "duplicate"),
                "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
        pages = strict_json(gh("--paginate", "--slurp", resource + "/comments?per_page=100"),
                            "authorization comments", object_root=False)
        comments = [row for page in pages for row in page]
        unique((r["id"] for r in comments), "AUTH_REQUIRED", "duplicate authorization comments")
        pin = next((row for row in comments if row["id"] == rule["comment_id"]), None)
        require(pin is not None and all(timestamp(row["created_at"]) <= timestamp(pin["created_at"])
                    and (timestamp(row["created_at"]) < timestamp(pin["created_at"]) or row["id"] <= pin["id"])
                    for row in comments), "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
        return pin
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise Invalid(f"AUTH_REQUIRED: ticket:{rule['ticket']}") from error


def authorize(loaded, groups, token=None):
    registry, contract, _, _, _ = loaded
    rule = contract["experiment_authorization"]
    repo = os.environ["GITHUB_REPOSITORY"]
    comments = {2133: authority_comment(repo, rule, token or os.environ.get("GH_TOKEN"))}
    if any(action != "query" for group in groups for action in rule["group_actions"][group]):
        comments[1412] = authority_comment(repo, rule["send_authorization"], token or os.environ.get("GH_TOKEN"))
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


def _manifest(loaded, evidence, group, identity, bundle):
    reg, contract, digest, _, _ = loaded
    manifest = strict_json(read_regular(bundle, "execution.json"), "execution.json")
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
                          sha256=row["sha256"]))
    require(producer_ids == {cid for cid, c in expected.items() if c["record"] is not None}
            and {p.name for p in bundle.iterdir()} == paths | {"execution.json"},
            "RECORD_UNSEALED", "inventory coverage")
    return seals


def seal_matrix(loaded, evidence, identity, artifacts):
    groups = groups_of(loaded, evidence)
    expected = {bundle_name(evidence, identity["run_attempt"], group): group for group in groups or [None]}
    require({path.name for path in artifacts.iterdir()} == expected.keys(), "RECORD_UNSEALED", "group inventory")
    seals, scaffold_sha = [], ""
    for name, group in expected.items():
        require(not (artifacts / name).is_symlink(), "RECORD_UNSEALED", "group path")
        seals.extend(_manifest(loaded, evidence, group, identity, artifacts / name))
        if group is None:
            scaffold_sha = sha(read_regular(artifacts / name, "execution.json"))
    require(len(seals) <= FIRST_LIMIT, "RECORD_UNSEALED", "Actions seal matrix limit")
    unique(((r["record"], r["profile"], r["sha256"]) for r in seals), "RECORD_UNSEALED", "duplicate seals")
    return {"has_seals": str(bool(seals)).lower(), "scaffold_sha": scaffold_sha,
            "seals": json_bytes({"include": seals}).decode().rstrip()}


def seal_scaffold(loaded, evidence, identity, artifacts, expected_sha, output):
    require(not groups_of(loaded, evidence) and expected_sha and SHA.fullmatch(expected_sha),
            "RECORD_UNSEALED", "scaffold identity")
    require(not _manifest(loaded, evidence, None, identity, artifacts)
            and sha(read_regular(artifacts, "execution.json")) == expected_sha,
            "RECORD_UNSEALED", "scaffold sha256")
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema_version": "at18-scaffold-seal/1", "registry_sha256": loaded[2], **identity,
               "evidence_class": evidence, "execution_sha256": expected_sha}
    (output / "scaffold-seal.json").write_bytes(json_bytes(receipt))


def main():
    parser = argparse.ArgumentParser(description="在 Actions 固定 F 上运行和封印 AT-18")
    parser.add_argument("operation", choices=("plan", "run", "seal-plan", "seal", "seal-scaffold"))
    parser.add_argument("evidence", choices=("simulation", "experiment"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--group")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--record")
    parser.add_argument("--profile")
    parser.add_argument("--sha256")
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        identity = run_identity(os.environ["GITHUB_SHA"], int(os.environ["GITHUB_RUN_ID"]),
                                int(os.environ["GITHUB_RUN_ATTEMPT"]))
        require(os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
                and os.environ.get("GITHUB_REF") == "refs/heads/main"
                and identity["head"] == git(root, "rev-parse", "HEAD").decode().strip(),
                "RUN_IDENTITY", "main dispatch")
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
            return 0 if run_group(root, loaded, args.evidence, args.group, identity, args.output,
                                  before_check=before_check) else 1
        elif args.operation == "seal-plan":
            action_outputs(seal_matrix(loaded, args.evidence, identity, args.artifacts))
        elif args.operation == "seal-scaffold":
            seal_scaffold(loaded, args.evidence, identity, args.artifacts, args.sha256, args.output)
        else:
            require(args.group in groups_of(loaded, args.evidence), "RECORD_UNSEALED", "unknown group")
            seals = _manifest(loaded, args.evidence, args.group, identity, args.artifacts)
            require(sum((row["record"], row["profile"], row["sha256"]) == (args.record, args.profile, args.sha256)
                        for row in seals) == 1, "RECORD_UNSEALED", "seal identity")
        return 0
    except (ValueError, KeyError, TypeError, OSError, SyntaxError) as error:
        print(f"AT-18: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
