"""AT-18 的正例、故障注入及 F 版数据合同夹具。"""
from __future__ import annotations

import copy
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "scripts/at18"
sys.path.insert(0, str(PROGRAMS))
adapter = importlib.import_module("adapter")
from common import ADAPTER, CROSSWALK, LEDGERS, REGISTRY, Invalid, json_bytes, sha, strict_json  # noqa: E402
from registry import OPENING_CENSUS, canonical_bases, load  # noqa: E402
from run_checks import execute, run_group, run_identity  # noqa: E402
from workflow import bundle_name, plan, seal_matrix, seal_scaffold  # noqa: E402

DATA = ROOT / "tests/fixtures/at18"
IDENTITY = run_identity("d" * 40, 104, 2)


def read(root, path):
    return json.loads((root / path).read_bytes())


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(json_bytes(value))


def sh(root, *args, check=True, env=None):
    return subprocess.run(args, cwd=root, check=check, capture_output=True, text=True, env=env)


def lint(root, *flags):
    return sh(root, sys.executable, str(PROGRAMS / "at18-registry-lint"), "--root", str(root), *flags, check=False)


def commit(root, message):
    sh(root, "git", "add", ".")
    sh(root, "git", "commit", "--quiet", "-m", message)
    return sh(root, "git", "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "checkout"
    target.mkdir()
    for path in (REGISTRY, ADAPTER, CROSSWALK, *LEDGERS, ".chanlun/at18/registry.schema.json",
                 ".chanlun/at18/adapter-contract.schema.json", "scripts/at18/node_reporter.mjs"):
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
    # 固定骨架夹具独立于日后 #2132/TB 分批登记的工作树。
    contract = read(target, ADAPTER)
    signature = contract["experiment_authorization"]
    signature.update(comment_id=None, body_sha256=None, group_actions={})
    signature["send_authorization"].update(comment_id=None, body_sha256=None)
    write(target, ADAPTER, contract)
    write(target, REGISTRY, {"schema_version": "at18-registry/1", "checks": [], "bindings": [],
                               "experiment_profile_id": None, "crosswalk_sha256": sha((target / CROSSWALK).read_bytes()),
                               "adapter_contract_sha256": sha((target / ADAPTER).read_bytes()),
                               "pregate": {"census_sha256": OPENING_CENSUS, "landings": []}})
    sh(target, "git", "init", "-q", "-b", "main")
    sh(target, "git", "config", "user.name", "AT-18 fixture")
    sh(target, "git", "config", "user.email", "at18-fixture@example.invalid")
    return target


@pytest.fixture
def cases():
    return read(DATA, "projection-cases.json")


def repin_contract(repo, contract):
    write(repo, ADAPTER, contract)
    registry = read(repo, REGISTRY)
    registry["adapter_contract_sha256"] = sha((repo / ADAPTER).read_bytes())
    write(repo, REGISTRY, registry)


def bind(repo, text, *, runner="pytest", selector="test_exact", source="trial/test_probe.py",
         expected=1, profile=None, group="g-1", record=None, key_aware=False):
    reg = read(repo, REGISTRY)
    target = repo / source
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    if runner == "command":
        target.chmod(0o755)
    if record is not None and runner == "command":
        keys = []
    else:
        keys = [{"kind": "story", "id": "US-ST-001"}]
    check = {"check_id": f"check-{len(reg['checks'])}", "group": group, "evidence_class": "simulation",
             "profile_id": profile, "runner": runner, "selector": selector, "expected_count": expected,
             "key_aware": key_aware, "source": {"path": source, "sha256": sha(target.read_bytes())},
             "record": record}
    reg["checks"].append(check)
    if keys:
        path, ptr = sorted(canonical_bases(repo, read(repo, CROSSWALK))[0][("TB-01", "story", "US-ST-001")])[0]
        binding = {"binding_id": "example", "slice_id": "TB-01", "keys": keys,
                   "basis": {"path": path, "sha256": sha((repo / path).read_bytes()), "pointer": ptr},
                   "domains": []}
        if reg["bindings"]:
            binding = reg["bindings"][0]
        else:
            reg["bindings"].append(binding)
        binding["domains"].append({"evidence_class": "simulation", "profile_id": profile,
                                   "result": "VERIFIED", "deferred_gate": None, "checks": [check["check_id"]]})
    write(repo, REGISTRY, reg)
    return check


PY_CASE = "# @at18 TB-01 story US-ST-001\ndef test_exact():\n    assert True\n"
NODE_CASE = """import { test } from 'node:test';
// @at18 TB-01 story US-ST-001
test('run.entry+1', () => {});
test('runXentry+1', () => { throw Error('this is not the registered identity') });
"""
COMMAND_CASE = """#!/usr/bin/env python3
import json, os
from pathlib import Path
keys = json.loads(Path(os.environ["AT18_KEYS_FILE"]).read_text())
witness = {"schema_version": "at18-key-witness/1", "entries": [dict(key, ok=True) for key in keys]}
Path(os.environ["AT18_WITNESS_FILE"]).write_text(json.dumps(witness))
"""
RECORD_CASE = COMMAND_CASE + """
payload = {
    "schema_version": "at18-tb-entity/1",
    "tb_id": "TB-01", "evidence_class": "simulation", "profile_id": None,
    "tests": [], "keys": [], "conditions": {"processes": 2}, "output": {"samples": [1, 2]}
}
doc = {"schema_version": "at18-run-record/1", "record": os.environ["AT18_RECORD"],
       "head": os.environ["AT18_F"], "run_id": int(os.environ["AT18_RUN_ID"]),
       "run_attempt": int(os.environ["AT18_RUN_ATTEMPT"]), "check_id": os.environ["AT18_CHECK_ID"],
       "profile_id": None, "payload": payload}
Path(os.environ["AT18_RECORD_DIR"], "actual.json").write_text(json.dumps(doc))
"""


def test_frozen_opening(repo):
    reg, contract, digest, keys, definitions = load(repo)
    basis, boundaries = canonical_bases(repo, read(repo, CROSSWALK))
    assert len(basis) == 4071 and sum(k[0] == "TB-11" for k in basis) == 113
    assert boundaries == {"OE41", "OE45"}
    assert not reg["checks"] and not reg["bindings"] and not reg["pregate"]["landings"]
    assert reg["experiment_profile_id"] is None and not keys and not definitions
    assert reg["crosswalk_sha256"] == sha((repo / CROSSWALK).read_bytes())
    assert digest == sha((repo / REGISTRY).read_bytes())
    assert reg["adapter_contract_sha256"] == sha((repo / ADAPTER).read_bytes())
    assert contract["experiment_authorization"]["comment_id"] is None
    assert lint(repo).returncode == 0


@pytest.mark.parametrize(("damage", "code"), [
    ("source", "CHECK_SOURCE_DRIFT"), ("adapter", "adapter_contract_sha256"),
    ("adapter-unknown", "REGISTRY_INVALID"), ("adapter-alternative", "REGISTRY_INVALID"),
    ("none", "REGISTRY_INVALID"), ("extra", "REGISTRY_INVALID"), ("crosswalk", "crosswalk_sha256"),
    ("missing-annotation", "CHECK_NOT_ANNOTATED"), ("basis-subnode", "BASIS_MISMATCH"),
])
def test_lint_rejects_invalid_pr(repo, damage, code):
    check = bind(repo, PY_CASE)
    base = commit(repo, "valid")
    reg = read(repo, REGISTRY)
    path = repo / check["source"]["path"]
    if damage == "source":
        path.write_bytes(path.read_bytes() + b"\n")
    elif damage == "adapter":
        (repo / ADAPTER).write_bytes((repo / ADAPTER).read_bytes() + b"\n")
    elif damage.startswith("adapter-"):
        doc = read(repo, ADAPTER)
        locator = doc["external_sources"]["capability_record"]["fields"]["source_url"]
        locator["candidates" if damage == "adapter-unknown" else "pointer"] = ["/one", "/two"]
        repin_contract(repo, doc)
        reg = read(repo, REGISTRY)
    elif damage == "missing-annotation":
        # 正确标注确实出现在同源，但属于另一个检查定义。
        path.write_text("def test_exact():\n    pass\n" + PY_CASE.replace("test_exact", "test_other"))
        reg["checks"][0]["source"]["sha256"] = sha(path.read_bytes())
    elif damage == "crosswalk":
        (repo / CROSSWALK).write_bytes((repo / CROSSWALK).read_bytes() + b"\n")
    elif damage == "basis-subnode":
        reg["bindings"][0]["basis"]["pointer"] += "/id"
    elif damage == "none":
        reg["checks"][0]["profile_id"] = reg["bindings"][0]["domains"][0]["profile_id"] = "none"
    else:
        reg["bindings"][0]["domains"][0]["self_reported"] = True
    write(repo, REGISTRY, reg)
    result = lint(repo, *(() if damage == "basis-subnode" else ("--base", base)))
    assert result.returncode == 1 and code in result.stderr


@pytest.mark.parametrize("damage", ["remove-domain", "remove-binding", "move-basis", "defer-active"])
def test_lint_detects_merge_base_regressions(repo, damage):
    bind(repo, PY_CASE)
    bind(repo, PY_CASE, source="trial/test_other.py", profile="simulation-v2", group="g-2")
    commit(repo, "registered before PR")
    sh(repo, "git", "switch", "-q", "-c", "topic")
    reg = read(repo, REGISTRY)
    if damage == "remove-domain":
        reg["bindings"][0]["domains"].pop()
        reg["checks"].pop()
    elif damage == "remove-binding":
        reg["bindings"], reg["checks"] = [], []
    elif damage == "move-basis":
        reg["bindings"][0]["basis"]["pointer"] += "/id"
    else:
        reg["bindings"][0]["domains"][0]["result"] = "BOUNDED_DEFERRED"
    write(repo, REGISTRY, reg)
    commit(repo, damage)
    sh(repo, "git", "switch", "-q", "main")
    (repo / "parallel.txt").write_text("independent advance\n")
    commit(repo, "advance target")
    sh(repo, "git", "merge", "--quiet", "--no-ff", "topic", "-m", "GitHub PR merge ref")
    result = lint(repo, "--pr-merge-ref")
    assert result.returncode == 1 and "DOMAIN_SHRINK" in result.stderr


@pytest.mark.parametrize(("text", "expected", "metric", "value", "status"), [
    (PY_CASE, 1, "executed", 1, "PASS"),
    (PY_CASE, 2, "executed", 1, "FAIL"),
    ("import pytest\n# @at18 TB-01 story US-ST-001\n@pytest.mark.skip\ndef test_exact(): pass\n", 1, "skipped", 1, "FAIL"),
    (PY_CASE.replace("assert True", "assert False"), 1, "exit_code", 1, "FAIL"),
])
def test_pytest_actual_counts(repo, text, expected, metric, value, status):
    check = bind(repo, text, expected=expected)
    _, contract, _, keys, definitions = load(repo)
    actual, records = execute(repo, check, contract, IDENTITY, keys[check["check_id"]], definitions[check["check_id"]])
    assert actual[metric] == value and actual["status"] == status and not records


@pytest.mark.parametrize(("kind", "status"), [("", "PASS"), (".skip", "FAIL"), (".todo", "FAIL")])
def test_node_reporter_and_literal_selection(repo, kind, status):
    check = bind(repo, NODE_CASE.replace("test('run.entry", f"test{kind}('run.entry"),
                 runner="node-test", selector="run.entry+1", source="trial/actual.mjs")
    _, contract, _, keys, definitions = load(repo)
    actual, _ = execute(repo, check, contract, IDENTITY, keys[check["check_id"]], definitions[check["check_id"]])
    assert actual["status"] == status
    assert actual["skipped"] == int(kind == ".skip") and actual["ignored"] == int(kind == ".todo")


@pytest.mark.parametrize(("outcome", "passed", "failed", "ignored", "status"), [
    ("ok", 1, 0, 0, "PASS"), ("ignored", 0, 0, 1, "FAIL"), ("FAILED", 0, 1, 0, "FAIL"),
])
def test_cargo_libtest_isolated_process_stub(repo, monkeypatch, outcome, passed, failed, ignored, status):
    check = bind(repo, "// @at18 TB-01 story US-ST-001\n#[test]\nfn guard() {}\n",
                 runner="cargo-test", selector="guard+production_session/guard", source="rust/tests/guard.rs")
    mock = repo / "fixture-bin/cargo"
    mock.parent.mkdir()
    mock.write_text(f"""#!/bin/sh
[ "$*" = 'test --locked --manifest-path rust/Cargo.toml --features production_session --test guard guard -- --exact --test-threads 1 --color never' ] || exit 3
printf '%s\\n' 'running 1 test' 'test guard ... {outcome}' 'test result: {"FAILED" if failed else "ok"}. {passed} passed; {failed} failed; {ignored} ignored; 0 measured; 25 filtered out; finished in 0.00s'
exit {int(bool(failed))}
""")
    mock.chmod(0o755)
    monkeypatch.setenv("PATH", str(mock.parent) + os.pathsep + os.environ["PATH"])
    _, contract, _, keys, definitions = load(repo)
    result, _ = execute(repo, check, contract, IDENTITY, keys[check["check_id"]], definitions[check["check_id"]])
    assert result["status"] == status and result["ignored"] == ignored


@pytest.mark.parametrize(("mutation", "expected"), [
    ("", "PASS"), ("different", "FAIL"), ("duplicate", "FAIL"), ("exit", "FAIL"), ("empty", "FAIL"),
])
def test_command_requires_positive_exact_key_witness(repo, mutation, expected):
    source = "trial/witness"
    extra = {"": "", "different": 'witness["entries"][0]["id"] = "other"',
             "duplicate": 'witness["entries"] *= 2', "exit": "raise SystemExit(18)",
             "empty": 'witness["entries"] = []'}[mutation]
    check = bind(repo, COMMAND_CASE.replace("Path(os.environ[\"AT18_WITNESS_FILE\"]).write_text",
                 extra + '\nPath(os.environ["AT18_WITNESS_FILE"]).write_text'), runner="command",
                 source=source, selector=source, key_aware=True)
    _, contract, _, keys, definitions = load(repo)
    result, _ = execute(repo, check, contract, IDENTITY, keys[check["check_id"]], definitions[check["check_id"]])
    assert result["status"] == expected
    assert result["exit_code"] == (18 if mutation == "exit" else 0)


@pytest.mark.parametrize("evidence", ["simulation", "experiment"])
def test_scaffold_plan_normalized_execution_and_seal(repo, evidence):
    loaded = load(repo)
    meta = plan(loaded, evidence, authorize_groups=lambda *_: pytest.fail("scaffold must not touch authorization"))
    assert meta["has_groups"] == "false" and json.loads(meta["groups"]) == {"include": []}
    artifacts = repo / "artifacts"
    path = artifacts / bundle_name(evidence, IDENTITY["run_attempt"], None)
    assert run_group(repo, loaded, evidence, None, IDENTITY, path)
    doc = read(path, "execution.json")
    assert doc["registry_sha256"] == meta["registry_sha"] and doc["checks"] == doc["records"] == []
    seal = seal_matrix(loaded, evidence, IDENTITY, artifacts)
    assert seal["has_seals"] == "false"
    assert seal["scaffold_sha"] == sha((path / "execution.json").read_bytes())
    receipt = repo / "receipt"
    seal_scaffold(loaded, evidence, IDENTITY, path, seal["scaffold_sha"], receipt)
    assert read(receipt, "scaffold-seal.json")["execution_sha256"] == seal["scaffold_sha"]
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_scaffold(loaded, evidence, IDENTITY, path, "0" * 64, receipt)


def test_nonempty_group_seal_binds_every_record_and_exact_attempt(repo):
    source = "trial/record"
    bind(repo, RECORD_CASE, runner="command", source=source, selector=source,
         key_aware=True, record="tb.simulation.TB-01")
    loaded = load(repo)
    meta = plan(loaded, "simulation")
    assert json.loads(meta["groups"]) == {"include": [{"group": "g-1"}]}
    artifacts = repo / "artifacts"
    path = artifacts / bundle_name("simulation", IDENTITY["run_attempt"], "g-1")
    assert run_group(repo, loaded, "simulation", "g-1", IDENTITY, path)
    manifest = read(path, "execution.json")
    assert manifest["checks"][0]["executed"] == manifest["checks"][0]["expected"] == 1
    assert manifest["checks"][0]["argv"] == [str(repo / source)]
    record = manifest["records"][0]
    assert json.loads(seal_matrix(loaded, "simulation", IDENTITY, artifacts)["seals"]) == {
        "include": [{"group": "g-1", "profile": "none", "record": "tb.simulation.TB-01", "sha256": record["sha256"]}]}
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_matrix(loaded, "simulation", IDENTITY | {"run_attempt": 3}, artifacts)
    entity = path / record["path"]
    entity.write_bytes(entity.read_bytes() + b" ")
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_matrix(loaded, "simulation", IDENTITY, artifacts)


def test_f_adapter_requires_f_bytes_and_recent_accepted_anchor(repo):
    p0 = commit(repo, "pre-gate")
    (repo / "opening.txt").write_text("G0")
    g0 = commit(repo, "gate")
    with pytest.raises(Invalid, match="has no G0..F anchor"):
        adapter.from_f(repo, g0, p0, g0, {g0})
    # 引入版本文件的新 mode/blob，保留语义不变。
    doc = read(repo, ADAPTER)
    (repo / ADAPTER).write_bytes((repo / ADAPTER).read_bytes() + b"\n")
    reg = read(repo, REGISTRY)
    reg["adapter_contract_sha256"] = sha((repo / ADAPTER).read_bytes())
    write(repo, REGISTRY, reg)
    anchor = commit(repo, "introduce gate inputs")
    (repo / "unrelated.txt").write_text("later")
    f = commit(repo, "unrelated")
    with pytest.raises(Invalid, match="REVIEW_FINAL_PRODUCT"):
        adapter.from_f(repo, f, p0, g0, {f})
    (repo / ADAPTER).write_text("not even JSON")
    assert adapter.from_f(repo, f, p0, g0, {anchor}) == doc
    bad = commit(repo, "drift")
    with pytest.raises(Invalid, match="adapter_contract_sha256"):
        adapter.from_f(repo, bad, p0, g0, {bad, anchor})
    (repo / ADAPTER).rename(repo / "moved-adapter.json")
    missing = commit(repo, "missing byte source")
    with pytest.raises(Invalid, match="REGISTRY_INVALID.*adapter blob"):
        adapter.from_f(repo, missing, p0, g0, {bad, anchor, missing})


@pytest.mark.parametrize("bad", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e400}', b'{"x":"\\ud800"}'])
def test_strict_json_does_not_repair_inputs(bad):
    with pytest.raises(Invalid, match="JSON_PARSE"):
        strict_json(bad, "input")


def test_scope_templates_are_injective_and_none_is_reserved(repo, cases):
    case = cases["scopes"]
    args = case["slice"], case["kind"], case["id"]
    basis, domain = case["basis"], case["domain"]
    assert [adapter.scope_key(*args), adapter.scope_key(*args, basis=basis),
            adapter.scope_key(*args, domain=domain), adapter.scope_key(*args, basis=basis, domain=domain)] == case["expected"]
    assert adapter.scope_key(*args, basis=(basis[0], "/")) != adapter.scope_key(*args, basis=basis)
    assert adapter.scope_key(*args, domain=("simulation", "x")) != adapter.scope_key(*args, domain=domain)
    assert adapter.scope_ticket(1279, "a%@/b") == case["ticket"]
    assert adapter.scope_slot("tb.simulation.TB-01", None) == case["slot"]
    with pytest.raises(Invalid, match="profile_id"):
        adapter.scope_slot("tb.simulation.TB-01", "none")
    contract = read(repo, ADAPTER)
    assert len(contract["failed_check_scope"]["templates"]) == 6


def test_special_slots_required_when_unsigned_and_artifact_roles(repo, cases):
    doc = read(repo, ADAPTER)
    blocked = cases["authorization_absent"]
    assert [{"obligation": adapter.scope_slot(slot, "P1-demo"), **routes}
            for slot, routes in sorted(doc["record_slots"].items())] == sorted(blocked["required"], key=lambda r: r["obligation"])
    assert blocked["required_flag"] and blocked["reason"] == "AUTH_REQUIRED"
    assert blocked["blocker_or_gap"] == "ticket:2133"
    roles = doc["reference_roles"]
    assert all(roles[field] == role for field, role in cases["references"].items())
    projection = doc["evidence_projection"]
    assert projection["tb_special_refs"] == []
    assert all(not (set(projection["top_level_only"]) | set(projection["excluded"])) & set(fields)
               and all(roles[f] == "RUN_RECORD" for f in fields)
               for fields in projection["destination_experiment"].values())
    assert projection["destination_experiment"]["DST-05"] == ["runtime_verification", "non_empty_evidence_refs"]


@pytest.mark.parametrize("problem", ["unsigned", "wrong-ticket", "wrong-profile", "expired",
                                      "future", "revoked-by-edit", "unscoped", "only-query", "no-send-authority",
                                      "wrong-runner", "valid-query", "valid-send"])
def test_2133_and_1412_signature_origins_reject_wrong_domain(repo, problem):
    contract = read(repo, ADAPTER)
    repo_id = "Newchanlun/NewChanlun"
    rule = contract["experiment_authorization"]
    auth_doc = {"schema_version": rule["signature_fence"], "runner_group": "at18-test-only",
                "runner_label": "at18-qa", "actions": ["query"],
                "profile_id": "P1-demo", "not_before": "2026-11-20T00:00:00Z",
                "expires_at": "2026-11-22T00:00:00Z"}
    rule["group_actions"] = {"g": ["query"]}
    if problem in {"only-query", "no-send-authority", "wrong-runner", "valid-send"}:
        rule["group_actions"]["g"].append("place")
    if problem in {"no-send-authority", "wrong-runner", "valid-send"}:
        auth_doc["actions"].append("place")
    if problem == "wrong-profile":
        auth_doc["profile_id"] = "P1-other"
    if problem == "wrong-runner":
        auth_doc["runner_group"] = "Default"
    if problem == "future":
        auth_doc["not_before"] = "2026-11-21T00:00:00.0000011Z"
    if problem == "unscoped":
        rule["group_actions"] = {}
    def signature(ref, data, cid):
        pin = f"```{ref['signature_fence']}\n{json.dumps(data)}\n```"
        ref.update(comment_id=cid, body_sha256=sha(pin.encode()))
        return {"id": cid, "body": pin, "issue_url": f"https://api.github.com/repos/{repo_id}/issues/{ref['ticket']}"}
    comments = {}
    if problem != "unsigned":
        comments[2133] = signature(rule, auth_doc, 301)
        if problem == "wrong-ticket":
            comments[2133]["issue_url"] = comments[2133]["issue_url"].replace("2133", "1770")
        if problem == "revoked-by-edit":
            comments[2133]["body"] += "\n撤回"
        if problem == "valid-send":
            send_rule = rule["send_authorization"]
            comments[1412] = signature(send_rule, auth_doc | {"schema_version": send_rule["signature_fence"],
                                                              "actions": ["place"]}, 302)
    params = {"repo": repo_id, "profile_id": "P1-demo", "groups": ["g"],
              "now": "2026-11-22T00:00:00Z" if problem == "expired" else "2026-11-21T00:00:00.000001Z"}
    if problem in ("valid-query", "valid-send"):
        assert adapter.experiment_authority(contract, comments, **params) == auth_doc
    else:
        with pytest.raises(Invalid, match="AUTH_REQUIRED"):
            adapter.experiment_authority(contract, comments, **params)


def test_unsigned_experiment_plan_fails_instead_of_falling_back(repo, monkeypatch):
    check = bind(repo, PY_CASE, profile="P1-demo")
    contract, reg = read(repo, ADAPTER), read(repo, REGISTRY)
    contract["experiment_authorization"]["group_actions"] = {"g-1": ["query"]}
    repin_contract(repo, contract)
    reg = read(repo, REGISTRY)
    reg["checks"][0]["evidence_class"] = "experiment"
    reg["bindings"][0]["domains"][0]["evidence_class"] = "experiment"
    reg["experiment_profile_id"] = check["profile_id"]
    write(repo, REGISTRY, reg)
    monkeypatch.setenv("GITHUB_REPOSITORY", "Newchanlun/NewChanlun")
    with pytest.raises(Invalid, match="AUTH_REQUIRED: ticket:2133"):
        plan(load(repo), "experiment")
    assert plan(load(repo), "simulation")["has_groups"] == "false"


def test_1770_single_exact_source_and_changed_legal_scalar(repo):
    contract = read(repo, ADAPTER)
    fields = contract["external_sources"]["capability_record"]["fields"]
    original = {"version": "cap/1", "session_permission": {"source": {
        "url": "https://example.invalid/spec", "retrieved_at": "2026-11-20T00:01:02Z", "sha256": "3"*64}}}
    data = adapter.decode_fields(contract, fields, original)
    after = copy.deepcopy(original)
    after["session_permission"]["source"]["retrieved_at"] = "2026-11-20T00:01:03Z"
    assert adapter.report_mismatches(data, adapter.decode_fields(contract, fields, after)) == ["/retrieved_at"]
    after["source_url"] = after["session_permission"]["source"].pop("url")
    with pytest.raises(Invalid, match="BAD_POINTER"):
        adapter.decode_fields(contract, fields, after)


def test_1279_known_provenance_only_and_no_silent_premature_release(repo):
    contract = read(repo, ADAPTER)
    ids = contract["issue_1279"]["release_disposition"]["known_historical_comments"]
    issues = {1279: {"state": "open", "body": "自有判据，不释放外部前置"}}
    comments = {}
    contract["legacy_sources"]["i1279"]["sha256"] = sha(issues[1279]["body"].encode())
    for source in ids:
        rule = contract["legacy_sources"][source]
        body = "\n".join(f"原件项目 {i}" for i in range(8))
        rule["sha256"] = sha(body.encode())
        comments[(1279, rule["comment_id"])] = {"body": body}
    expected = ["ISSUE_1279:5440707729/3", "ISSUE_1279:5462459006/1", "ISSUE_1279:5466854598/1", "ISSUE_1279:5596452227/2",
                "ISSUE_1279:5596452227/3", "ISSUE_1279:5596452227/5"]
    assert adapter.own_1279_obligations(repo, contract, issues, comments) == expected
    assert adapter.own_1279_obligations(repo, contract, issues, dict(reversed(list(comments.items())))) == expected
    with pytest.raises(Invalid, match="LEGACY_DISPOSITION"):
        adapter.own_1279_obligations(repo, contract, issues, comments | {(1279, 1): {"body": "我宣布可以试运行"}})


def test_deterministic_order_and_exact_report_mismatch_ignores_log_text(cases, repo):
    mismatch = cases["scalar_mismatch"]
    assert adapter.report_mismatches(mismatch["actual"], mismatch["expected"]) == mismatch["pointers"]
    assert adapter.report_mismatches({"a~/b": 6}, {"a~/b": 7}) == ["/a~0~1b"]
    same = [{"id": 3, "name": "at18 g-other " + "1"*64, "conclusion": "failure"},
            {"id": 1, "name": "at18 g-main " + "1"*64, "conclusion": "success"}]
    payloads = [[same[0], same[1], same[0]], [same[1], same[0]]]
    computed = []
    for data, message in zip(payloads, ("only status matters", "this claims success but is never consumed")):
        upstream = [row | {"message": message} for row in data]
        trusted = [{k: row[k] for k in ("id", "name", "conclusion")} for row in upstream]
        computed.append(adapter.canonical_rows(trusted, lambda row: row["id"]))
    assert computed[0] == computed[1] == ([same[1], same[0]], [])
    conflict = [same[0], same[0] | {"conclusion": "success"}]
    assert adapter.canonical_rows(conflict, lambda row: row["id"]) == ([], [3])


def test_r10_r12_r13_projection_fixture(cases):
    landing = cases["landing"]
    def attribution(claims):
        declared = {row["ticket"]: set(row["attribution_scopes"]) for row in claims}
        routed = set()
        for t in landing["sha_by_ticket"]:
            ticket = int(t)
            native = {landing["native"][t]} if t in landing["native"] else set()
            scope = native | declared.get(ticket, set())
            if not scope:
                raise Invalid("PREGATE_LANDINGS")
            routed.update((ticket, s) for s in scope if s == "GRAPH" or s in landing["dst_closure"])
        return sorted(routed)
    assert [list(row) for row in attribution(landing["attributions"])] == landing["dst_tickets"]
    assert attribution(landing["attributions"]) == attribution(reversed(landing["attributions"]))
    assert sorted({"F"} | {sha for t, _ in attribution(landing["attributions"])
                           for sha in landing["sha_by_ticket"][str(t)]}) == landing["dst_commits"]
    with pytest.raises(Invalid, match="PREGATE_LANDINGS"):
        attribution(landing["attributions"][:-1])
    case = cases["deferrals"]
    tb, dst = defaultdict(set), set()
    for key in case["keys"]:
        tb[key["slice_id"]].add(key["gate"])
        if key["slice_id"] in case["dst_closure"] and [key["kind"], key["id"]] in case["dst_coverage"]:
            dst.add(key["gate"])
    tb["TB-11"].add("ISSUE_1320_HEAVY_MEASUREMENT")
    assert {k: sorted(v) for k, v in tb.items()} == case["expected_tb"]
    assert sorted(dst) == case["expected_dst"]
    assert set(case["expected_dst"]).isdisjoint({row["obligation"] for row in cases["authorization_absent"]["required"]})


def test_tb11_fixture_projects_ticket_state_at_report_time():
    def state_at(start, events, at):
        state = start
        for time, to in sorted(events):
            if time <= at:
                state = to
        return state
    events = [(15, "CLOSED"), (20, "OPEN")]
    assert state_at("OPEN", events, 14) == "OPEN"
    assert state_at("OPEN", reversed(events), 14) == "OPEN"
    assert state_at("OPEN", events, 16) == "CLOSED"


def test_yamls_dispatch_shapes_and_unchanged_gates():
    class ActionsLoader(yaml.SafeLoader):
        pass
    ActionsLoader.yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
    for key, entries in ActionsLoader.yaml_implicit_resolvers.items():
        ActionsLoader.yaml_implicit_resolvers[key] = [(tag, resolver) for tag, resolver in entries
                                                       if tag != "tag:yaml.org,2002:bool"]
    ActionsLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF"))
    def workflow(name):
        return yaml.load((ROOT / f".github/workflows/{name}.yml").read_text(), Loader=ActionsLoader)
    ci = workflow("ci")
    assert set(ci["jobs"]["ci-ok"]["needs"]) >= {"at18-registry-lint", "changes", "test", "rust-check",
        "rust-test-default", "rust-test-s-session", "rust-test-s-session-coverage", "rust-test-s-session-extra-groups",
        "rust-test-production-session", "s-sequence-1488", "s-fields-native-1488", "s-observer", "fixture-drift",
        "sandcastle-ts", "deepagents-pilot"}
    assert workflow("devskim")["on"]["workflow_dispatch"] is None
    for name, evidence in (("at18-acceptance", "simulation"), ("at18-experiment", "experiment")):
        doc = workflow(name)
        assert doc["on"] == {"workflow_dispatch": None}
        jobs = doc["jobs"]
        assert jobs["checks"]["name"] == "at18 ${{ matrix.group }} ${{ needs.plan.outputs.registry_sha }}"
        assert jobs["scaffold"]["name"] == f"at18-scaffold {evidence} " + "${{ needs.plan.outputs.registry_sha }}"
        assert jobs["scaffold"]["runs-on"] == jobs["seal"]["runs-on"] == "ubuntu-latest"
        assert jobs["seal_scaffold"]["name"] == (
            f"at18-seal-scaffold {evidence} " +
            "${{ needs.plan.outputs.registry_sha }} ${{ needs.seal_plan.outputs.scaffold_sha }}")
        assert jobs["seal"]["name"] == (
            "at18-seal ${{ matrix.record }} ${{ matrix.profile }} "
            "${{ needs.plan.outputs.registry_sha }} ${{ matrix.sha256 }}")
        assert set(jobs["seal_plan"]["needs"]) == {"checks", "scaffold", "plan"}
        assert jobs["checks"]["runs-on"] == ("ubuntu-latest" if evidence == "simulation" else {
            "group": "${{ needs.plan.outputs.runner_group }}",
            "labels": "${{ needs.plan.outputs.runner_label }}",
        })


@pytest.mark.parametrize("evidence", ["simulation", "experiment"])
def test_actions_entrypoints_scaffold_at_f(repo, evidence):
    head = commit(repo, "F")
    cli = (sys.executable, str(PROGRAMS / "workflow.py"))
    temp = repo / "action-temp"
    temp.mkdir()
    output = temp / "github-output"
    env = os.environ | {"GITHUB_SHA": head, "GITHUB_RUN_ID": "456", "GITHUB_RUN_ATTEMPT": "3",
                        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                        "GITHUB_OUTPUT": str(output)}
    def step(operation, *flags, **kwargs):
        return sh(repo, *cli, operation, evidence, "--root", str(repo), *flags,
                  **({"env": env} | kwargs))
    step("plan")
    assert "has_groups=false" in output.read_text()
    artifacts = temp / "artifacts"
    bundle = artifacts / bundle_name(evidence, 3, None)
    step("run", "--output", str(bundle))
    step("seal-plan", "--artifacts", str(artifacts))
    results = dict(row.split("=", 1) for row in output.read_text().splitlines())
    assert results["scaffold_sha"] == sha((bundle / "execution.json").read_bytes())
    sealed = temp / "sealed"
    step("seal-scaffold", "--artifacts", str(bundle), "--output", str(sealed),
         "--sha256", results["scaffold_sha"])
    receipt = read(sealed, "scaffold-seal.json")
    assert receipt["head"] == head and receipt["run_attempt"] == 3
    assert receipt["registry_sha256"] == results["registry_sha"]
    wrong = step("plan", env=env | {"GITHUB_REF": "refs/heads/not-main"}, check=False)
    assert wrong.returncode == 1 and "RUN_IDENTITY" in wrong.stderr
