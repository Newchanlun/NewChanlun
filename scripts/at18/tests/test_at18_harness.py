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

PROGRAMS = Path(__file__).resolve().parents[1]
ROOT = PROGRAMS.parents[1]
sys.path.insert(0, str(PROGRAMS))
adapter = importlib.import_module("adapter")
from common import ADAPTER, CROSSWALK, LEDGERS, REGISTRY, Invalid, json_bytes, sha, strict_json  # noqa: E402
from registry import OPENING_CENSUS, canonical_bases, load  # noqa: E402
from run_checks import execute, run_group, run_identity  # noqa: E402
from workflow import (_manifest, authority_comment, bundle_name, plan, producer_anchors,
                      producer_job_name, seal_matrix, seal_scaffold)  # noqa: E402

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
RUST_PACKAGE = '[package]\nname = "probe"\nversion = "0.1.0"\nedition = "2021"\n'
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
source = Path(__file__).relative_to(Path.cwd()).as_posix()
record = os.environ["AT18_RECORD"]
_, evidence, tb = record.split(".")
profile_id = os.environ["AT18_PROFILE_ID"] or None
payload = {
    "schema_version": "at18-tb-entity/1",
    "tb_id": tb, "evidence_class": evidence, "profile_id": profile_id,
    "tests": [{"check_id": os.environ["AT18_CHECK_ID"], "name": source, "source_path": source}],
    "keys": keys, "conditions": {"processes": 2}, "output": {"samples": [1, 2]}
}
doc = {"schema_version": "at18-run-record/1", "record": record,
       "head": os.environ["AT18_F"], "run_id": int(os.environ["AT18_RUN_ID"]),
       "run_attempt": int(os.environ["AT18_RUN_ATTEMPT"]), "check_id": os.environ["AT18_CHECK_ID"],
       "profile_id": profile_id, "payload": payload}
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
    (repo / "rust/Cargo.toml").write_text(RUST_PACKAGE)
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
    seal = seal_matrix(loaded, evidence, IDENTITY, artifacts, {None: sha((path / "execution.json").read_bytes())})
    assert seal["has_seals"] == "false"
    assert seal["scaffold_sha"] == sha((path / "execution.json").read_bytes())
    receipt = repo / "receipt"
    seal_scaffold(loaded, evidence, IDENTITY, path, seal["scaffold_sha"], receipt)
    assert read(receipt, "scaffold-seal.json")["execution_sha256"] == seal["scaffold_sha"]
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_scaffold(loaded, evidence, IDENTITY, path, "0" * 64, receipt)


def test_nonempty_group_seal_binds_every_record_and_exact_attempt(repo):
    check = register_r03_record(repo, R03_CASES[0])
    source = check["source"]["path"]
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
    digest = sha((path / "execution.json").read_bytes())
    anchors = {"g-1": digest}
    assert json.loads(seal_matrix(loaded, "simulation", IDENTITY, artifacts, anchors)["seals"]) == {
        "include": [{"group": "g-1", "profile": "none", "record": "tb.simulation.TB-01", "sha256": record["sha256"], "execution_sha": digest}]}
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_matrix(loaded, "simulation", IDENTITY | {"run_attempt": 3}, artifacts, anchors)
    entity = path / record["path"]
    entity.write_bytes(entity.read_bytes() + b" ")
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        seal_matrix(loaded, "simulation", IDENTITY, artifacts, anchors)


R03_CASES = [
    (CROSSWALK, "TB-01", "story", "US-ST-001", "/rows/0"),
    (LEDGERS[0], "TB-01", "detail", "A-CC-006-01", "/units/0"),
    (LEDGERS[1], "TB-02", "detail", "A-CC-008-01", "/units/1"),
    (LEDGERS[2], "TB-10", "family", "OE42", "/units/17"),
    (LEDGERS[3], "TB-01", "detail", "A-CC-001-01", "/rows/48"),
]


def r03_record_key(case):
    path, tb, kind, key_id, ptr = case
    return {"slice_id": tb, "kind": kind, "id": key_id, "basis_path": path, "basis_pointer": ptr}


def register_r03_record(repo, case, *, text=RECORD_CASE, group="g-1", evidence="simulation", profile=None,
                        also=(), produces_record=True):
    source = f"trial/{group}" if produces_record else f"trial/{group}-witness"
    check = bind(repo, text, runner="command", source=source, selector=source, group=group, profile=profile,
                 key_aware=True, record=f"tb.{evidence}.{case[1]}")
    reg = read(repo, REGISTRY)
    check["evidence_class"] = evidence
    if not produces_record:
        check["record"] = None
    reg["checks"][-1] = check
    reg["bindings"].extend({
        "binding_id": f"{check['check_id']}-{i}", "slice_id": tb, "keys": [{"kind": kind, "id": key_id}],
        "basis": {"path": path, "pointer": ptr, "sha256": sha((repo / path).read_bytes())},
        "domains": [{"evidence_class": evidence, "profile_id": profile, "result": "VERIFIED",
                     "deferred_gate": None, "checks": [check["check_id"]]}],
    } for i, (path, tb, kind, key_id, ptr) in enumerate((case, *also)))
    if evidence == "experiment":
        reg["experiment_profile_id"] = profile
    write(repo, REGISTRY, reg)
    if evidence == "experiment":
        contract = read(repo, ADAPTER)
        contract["experiment_authorization"]["group_actions"][group] = ["query"]
        repin_contract(repo, contract)
    return check


def final_seal(repo, bundle, check, identity, record_sha, execution_sha):
    return sh(repo, sys.executable, str(PROGRAMS / "workflow.py"), "seal", check["evidence_class"],
              "--root", str(repo), "--group", check["group"], "--artifacts", str(bundle),
              "--record", check["record"], "--profile", check["profile_id"] or "none",
              "--sha256", record_sha, "--execution-sha", execution_sha, check=False,
              env=os.environ | {"GITHUB_SHA": identity["head"], "GITHUB_RUN_ID": str(identity["run_id"]),
                                "GITHUB_RUN_ATTEMPT": str(identity["run_attempt"]),
                                "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch"})


@pytest.mark.parametrize(("path", "tb", "kind", "key_id", "ptr"), R03_CASES,
                         ids=["crosswalk-US-ST-001", "TB01-slices", "TB02-06-slices",
                              "TB07-11-slices", "TB01-contribution"])
def test_real_r03_basis_archives_one_original(repo, path, tb, kind, key_id, ptr):
    bases, _ = canonical_bases(repo, read(repo, CROSSWALK))
    assert {p for k, values in bases.items() if k[0] != "TB-11" for p, _ in values} == {
        case[0] for case in R03_CASES}
    assert bases[tb, kind, key_id] == {(path, ptr)}
    case = path, tb, kind, key_id, ptr
    if case == R03_CASES[0]:
        # 本 TB 另有登记键，见证全部执行；当前分件只声明其中一条。
        text = RECORD_CASE.replace('"keys": keys', '"keys": [key for key in keys if key["kind"] == "story"]')
        check = register_r03_record(repo, case, text=text, also=(R03_CASES[1],))
    else:
        check = register_r03_record(repo, case)
    head = commit(repo, "actual R03 registration and producer")
    checked = lint(repo)
    assert checked.returncode == 0, checked.stderr
    loaded = load(repo)
    identity = run_identity(head, 104, 2)
    artifacts = repo / "artifacts"
    group = check["group"]
    bundle = artifacts / bundle_name("simulation", identity["run_attempt"], group)
    assert run_group(repo, loaded, "simulation", group, identity, bundle, head=head), read(bundle, "execution.json")
    manifest = read(bundle, "execution.json")
    assert [(r["executed"], r["exit_code"]) for r in manifest["checks"]] == [(1, 0)]
    item, = manifest["records"]
    assert {p.name for p in bundle.iterdir()} == {"execution.json", item["path"]}
    original = read(bundle, item["path"])
    assert original["payload"]["keys"] == [r03_record_key(case)]
    execution_sha = sha((bundle / "execution.json").read_bytes())
    job = producer_job(loaded, "simulation", group, identity, execution_sha)
    anchors = producer_anchors(loaded, "simulation", identity, [{"jobs": [job], "total_count": 1}])
    sealed = seal_matrix(loaded, "simulation", identity, artifacts, anchors)
    assert sealed["has_seals"] == "true"
    assert json.loads(sealed["seals"]) == {"include": [{
        "group": group, "record": check["record"], "profile": "none",
        "sha256": item["sha256"], "execution_sha": execution_sha,
    }]}
    result = final_seal(repo, bundle, check, identity, item["sha256"], execution_sha)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("fault", ["wrong-row", "unregistered-path", "linebreak", "cross-tb",
                                   "cross-profile", "cross-evidence-class"])
def test_r03_rejects_bad_basis_in_group_and_final_seal(repo, fault):
    good = r03_record_key(R03_CASES[0])
    profile = "fixture-p1" if fault == "cross-evidence-class" else None
    if fault.startswith("cross-"):
        other = R03_CASES[2 if fault == "cross-tb" else 1]
        register_r03_record(repo, other, group="other", profile="fixture-p1" if fault != "cross-tb" else None,
                            evidence="experiment" if fault == "cross-evidence-class" else "simulation")
        bad = r03_record_key(other)
    else:
        bad = good | {"wrong-row": {"basis_pointer": "/rows/1"},
                      "unregistered-path": {"basis_path": ".chanlun/nonexistent-ledger.json"},
                      "linebreak": {"basis_pointer": "/rows/0\n"}}[fault]
    # 见证仍是正确登记键；原件写一个正确键和一个坏键。
    text = RECORD_CASE.replace("\ndoc =", f"\npayload['keys'] = [*keys, {bad!r}]\ndoc =")
    check = register_r03_record(repo, R03_CASES[0], text=text, profile=profile)
    assert_r03_rejected(repo, check, {"keys": [good, bad]},
                        "RECORD_PUBLIC_SCHEMA" if fault == "linebreak" else "BASIS_MISMATCH")


def assert_r03_rejected(repo, check, payload_change, diagnostic, *, peer=None):
    head = commit(repo, "register producer and R03 fixtures")
    identity = run_identity(head, 104, 2)
    loaded = load(repo)
    group = check["group"]
    if peer is not None and peer["group"] != group:
        peer_bundle = repo / "peer-bundle"
        assert run_group(repo, loaded, "simulation", peer["group"], identity, peer_bundle, head=head)
        peer_execution, = read(peer_bundle, "execution.json")["checks"]
        assert (peer_execution["check_id"], peer_execution["executed"], peer_execution["status"]) == (
            peer["check_id"], 1, "PASS")
    bundle = repo / "bundle"
    accepted = run_group(repo, loaded, "simulation", group, identity, bundle, head=head)
    manifest = read(bundle, "execution.json")
    execution = next(row for row in manifest["checks"] if row["check_id"] == check["check_id"])
    if peer is not None and peer["group"] == group:
        peer_execution = next(row for row in manifest["checks"] if row["check_id"] == peer["check_id"])
        assert (peer_execution["executed"], peer_execution["status"]) == (1, "PASS")
    # 直喂末级 seal：原件与清单摘要自洽，登记检查有成功执行证据，只有 payload 有错。
    source = check["source"]["path"]
    payload = {"schema_version": "at18-tb-entity/1", "tb_id": "TB-01", "evidence_class": "simulation",
               "profile_id": check["profile_id"], "keys": [r03_record_key(R03_CASES[0])],
               "tests": [{"check_id": check["check_id"], "name": source, "source_path": source}],
               "conditions": {}, "output": {}} | payload_change
    raw = {"schema_version": "at18-run-record/1", "record": check["record"], **identity,
           "check_id": check["check_id"], "profile_id": check["profile_id"], "payload": payload}
    record_sha = sha(json_bytes(raw))
    forged = repo / "forged"
    filename = f"record-{record_sha}.json"
    write(forged, filename, raw)
    forged_manifest = manifest | {
        "checks": [row | {"status": "PASS", "diagnostic": None} for row in manifest["checks"]],
        "records": [{"path": filename, "record": check["record"], "sha256": record_sha,
                     "check_id": check["check_id"], "profile_id": check["profile_id"]}],
    }
    write(forged, "execution.json", forged_manifest)
    decision = final_seal(repo, forged, check, identity, record_sha, sha(json_bytes(forged_manifest)))
    assert (accepted, len(manifest["records"]), decision.returncode) == (False, 0, 1), (manifest, decision.stderr)
    assert execution["executed"] == 1 and execution["exit_code"] == 0
    assert execution["diagnostic"] == diagnostic and diagnostic in decision.stderr
    assert {p.name for p in bundle.iterdir()} == {"execution.json"}


@pytest.mark.parametrize(("fault", "diagnostic"), [
    ("other-group-check", "BASIS_MISMATCH"),
    ("same-group-check", "BASIS_MISMATCH"),
    ("empty-keys", "RECORD_PUBLIC_SCHEMA"),
    ("duplicate-key", "RECORD_PUBLIC_SCHEMA"),
    ("test-check-id", "RECORD_UNSEALED"),
    ("test-name", "RECORD_UNSEALED"),
    ("test-source-path", "RECORD_UNSEALED"),
    ("test-empty", "RECORD_PUBLIC_SCHEMA"),
    ("test-duplicate", "RECORD_PUBLIC_SCHEMA"),
])
def test_r03_rejects_bad_partition_in_group_and_final_seal(repo, fault, diagnostic):
    own_key = r03_record_key(R03_CASES[0])
    if fault.startswith("test-"):
        test = {"check_id": "check-0", "name": "trial/g-1", "source_path": "trial/g-1"}
        payload_change = {"tests": {
            "test-check-id": [test | {"check_id": "check-1"}],
            "test-name": [test | {"name": "not-executed"}],
            "test-source-path": [test | {"source_path": "trial/other"}],
            "test-empty": [],
            "test-duplicate": [test, test],
        }[fault]}
    else:
        keys = {"empty-keys": [], "duplicate-key": [own_key, own_key]}.get(fault, [r03_record_key(R03_CASES[1])])
        payload_change = {"keys": keys}
    text = RECORD_CASE.replace("\ndoc =", f"\npayload.update({payload_change!r})\ndoc =")
    producer = register_r03_record(repo, R03_CASES[0], text=text)
    peer = None
    if fault in ("same-group-check", "other-group-check", "test-check-id"):
        group = "other" if fault == "other-group-check" else producer["group"]
        peer = register_r03_record(repo, R03_CASES[1], text=COMMAND_CASE, group=group, produces_record=False)
    assert_r03_rejected(repo, producer, payload_change, diagnostic, peer=peer)


@pytest.mark.parametrize(("field", "value", "error"), [
    ("basis_path", "../escape", "basis path"),
    ("basis_path", ".chanlun/../escape", "basis path"),
    ("basis_path", "/etc/absolute", "basis path"),
    ("basis_path", "C:/absolute", "basis path"),
    ("basis_path", ".chanlun\\escape", "basis path"),
    ("basis_path", ".chanlun/has\ncontrol", "basis path"),
    ("basis_path", ".chanlun/has\x7fcontrol", "basis path"),
    ("basis_path", ".chanlun/has\x85control", "basis path"),
    ("basis_pointer", "rows/0", "SCHEMA"),
    ("basis_pointer", "/rows/~2", "SCHEMA"),
    ("basis_pointer", "/rows/0\r", "basis pointer"),
    ("basis_pointer", "/rows/\x00", "basis pointer"),
    ("basis_pointer", "/rows/\x1f", "basis pointer"),
    ("basis_pointer", "/rows/\x7f", "basis pointer"),
    ("id", ".not-a-business-token", "business token"),
    ("unregistered_fixture_note", "CANARY", "unknown or missing fields"),
])
def test_tb_key_public_schema_stays_closed(field, value, error):
    path, tb, kind, key_id, ptr = R03_CASES[0]
    key = {"slice_id": tb, "kind": kind, "id": key_id, "basis_path": path, "basis_pointer": ptr}
    payload = {"schema_version": "at18-tb-entity/1", "tb_id": tb, "evidence_class": "simulation",
               "profile_id": None, "keys": [key], "conditions": {}, "output": {},
               "tests": [{"check_id": "check-0", "name": "trial/g-1", "source_path": "trial/g-1"}]}
    contract = read(ROOT, ADAPTER)
    record = f"tb.simulation.{tb}"
    # RFC 6901 的空根、标点和转义不能按业务 token 审。
    for pointer in ("", "/.rows/a~1b/~0"):
        allowed = {(tb, kind, key_id, path, pointer)}
        assert adapter.public_payload(contract, record, payload | {
            "keys": [key | {"basis_pointer": pointer}]}, allowed_r03=allowed)["keys"][0]["basis_pointer"] == pointer
    with pytest.raises(Invalid, match=error):
        adapter.public_payload(contract, record, payload | {"keys": [key | {field: value}]})


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
    if problem == "valid-query":
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
    assert any(step.get("run") == "pytest -p no:cacheprovider scripts/at18/tests/test_at18_harness.py -v"
               and "if" not in step for step in ci["jobs"]["at18-registry-lint"]["steps"])
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
    identity = run_identity(head, 456, 3)
    digest = dict(row.split("=", 1) for row in output.read_text().splitlines())["execution_sha"]
    page = producer_job(load(repo), evidence, None, identity, digest)
    fixture_gh = temp / "gh"
    fixture_gh.write_text("#!/bin/sh\n[ \"$*\" = 'api --paginate --slurp repos/test/repo/actions/runs/456/attempts/3/jobs?per_page=100' ] || exit 8\n"
                          + "printf '%s' '" + json.dumps([{"total_count": 1, "jobs": [page]}]) + "'\n")
    fixture_gh.chmod(0o755)
    step("seal-plan", "--artifacts", str(artifacts),
         env=env | {"PATH": str(temp) + os.pathsep + env["PATH"], "GITHUB_REPOSITORY": "test/repo",
                    "GH_TOKEN": "test-only"})
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


def producer_job(loaded, evidence, group, identity, digest):
    return {"name": producer_job_name(loaded, evidence, group), "head_sha": identity["head"],
            "run_id": identity["run_id"], "run_attempt": identity["run_attempt"], "head_branch": "main",
            "status": "completed", "conclusion": "success",
            "steps": [{"name": f"at18-anchor {digest}", "status": "completed", "conclusion": "success"}]}


@pytest.mark.parametrize(("evidence", "label"), [("simulation", "acceptance"), ("experiment", "experiment")])
def test_seal_ancestors_require_exact_success_and_skip(evidence, label):
    jobs = yaml.safe_load((ROOT / f".github/workflows/at18-{label}.yml").read_text())["jobs"]

    def eligible(name, **state):
        expr = jobs[name]["if"].strip().removeprefix("${{").removesuffix("}}").strip()
        # 保留显式状态函数这一条件，不把 Actions 默认 success() 偷换成本地真值。
        assert expr.startswith("!cancelled() && ")
        expr = expr.replace("!cancelled()", "not cancelled").replace("&&", "and").replace("||", "or")
        for key, value in state.items():
            expr = expr.replace(key.replace("__", "."), repr(value))
        return eval(expr, {"__builtins__": {}})

    for has_groups, active, terminal in (("true", "checks", "seal"), ("false", "scaffold", "seal_scaffold")):
        condition = {"cancelled": False, "needs__plan__result": "success",
                     "needs__plan__outputs__has_groups": has_groups, "needs__checks__result": "skipped",
                     "needs__scaffold__result": "skipped", "needs__seal_plan__result": "success",
                     "needs__seal_plan__outputs__has_seals": "true",
                     "needs__seal_plan__outputs__scaffold_sha": "a" * 64}
        condition[f"needs__{active}__result"] = "success"
        assert eligible("seal_plan", **condition) and eligible(terminal, **condition)
        inactive = "checks" if active == "scaffold" else "scaffold"
        for failed in ("failure", "cancelled", "skipped"):
            assert not eligible("seal_plan", **(condition | {f"needs__{active}__result": failed}))
            assert not eligible(terminal, **(condition | {"needs__seal_plan__result": failed}))
            assert not eligible(terminal, **(condition | {f"needs__{active}__result": failed}))
        for result in ("success", "failure", "cancelled"):
            assert not eligible("seal_plan", **(condition | {f"needs__{inactive}__result": result}))
            assert not eligible(terminal, **(condition | {f"needs__{inactive}__result": result}))
        assert not eligible("seal_plan", **(condition | {"cancelled": True}))
        assert not eligible(terminal, **(condition | {"cancelled": True}))
        assert not eligible(terminal, **(condition | {"needs__plan__result": "failure"}))


def test_rust_same_leaf_in_different_file_is_not_the_pinned_definition(repo, monkeypatch):
    marked = "// @at18 TB-01 story US-ST-001\n#[test]\nfn count() {}\n"
    check = bind(repo, "mod child;\n" + marked, runner="cargo-test", selector="lib/count", source="rust/src/lib.rs")
    (repo / "rust/Cargo.toml").write_text(RUST_PACKAGE)
    child = repo / "rust/src/child.rs"
    child.write_text("#[test]\nfn count() {}\n")
    loaded = load(repo)
    bad = copy.deepcopy(check)
    bad["selector"] = "lib/child::count"
    reg = read(repo, REGISTRY)
    reg["checks"] = [bad]
    write(repo, REGISTRY, reg)
    result = lint(repo)
    assert result.returncode == 1 and "Rust definition file is rust/src/child.rs" in result.stderr
    monkeypatch.setattr("run_checks.subprocess.run", lambda *a, **k: pytest.fail("wrong file must not execute"))
    result, _ = execute(repo, bad, loaded[1], IDENTITY, set(), loaded[-1][check["check_id"]])
    assert result["status"] == "FAIL" and result["diagnostic"] == "CHECK_SELECTOR"
    bad["source"] = {"path": "rust/src/child.rs", "sha256": sha(child.read_bytes())}
    write(repo, REGISTRY, reg)
    with pytest.raises(Invalid, match="CHECK_NOT_ANNOTATED"):
        load(repo)
    child.write_text(marked)
    bad["source"]["sha256"] = sha(child.read_bytes())
    write(repo, REGISTRY, reg)
    assert load(repo)[-1][check["check_id"]] == (2, 3)


@pytest.mark.parametrize(("selector", "target"), [("bin:probe/outer::count", "--bin"),
                                                  ("test:probe/outer::count", "--test")])
def test_rust_explicit_cargo_target_and_inline_path(repo, selector, target):
    from check_selector import command
    tagged = "mod outer {\n// @at18 TB-01 story US-ST-001\n#[test]\nfn count() {}\n}\n"
    check = bind(repo, tagged, runner="cargo-test", selector=selector, source="rust/custom.rs")
    (repo / "rust/Cargo.toml").write_text(RUST_PACKAGE + f'[[{target[2:]}]]\nname = "probe"\npath = "custom.rs"\n')
    assert load(repo)[-1][check["check_id"]] == (3, 4)
    assert command(check, repo)[5:8] == [target, "probe", "outer::count"]


@pytest.mark.parametrize(("where", "attribute", "child_dir", "diagnostic"), [
    ("inline", '#![path = "redirected"]', "redirected", "unsupported inner attribute: path"),
    ("inline", '#![path = "api"]', "api", "unsupported inner attribute: path"),
    ("inline", '#![r#path = "api"]', "api", "unsupported inner attribute: path"),
    ("inline", '#![/* marker */ path = "api"]', "api", "unsupported inner attribute: path"),
    ("nested", '#![cfg_attr(test, cfg_attr(all(), path = "redirected"))]', "redirected",
     "unsupported inner attribute: cfg_attr"),
    ("inline", "#![test_runner(custom)]", "api", "unsupported inner attribute: test_runner"),
    ("root", "#![test_runner(custom)]", "api", "unsupported inner attribute: test_runner"),
    ("child", '#![path = "api"]', "api", "unsupported inner attribute: path"),
    ("outer", '#[path = "api/child.rs"]', "api", "definition-changing attribute"),
    ("root", "macro_rules! item { () => { const C: u8 = 1; } }\nitem!();", "api", "item expansion"),
])
def test_rust_rejects_unmodelled_scope_before_trusting_definition(repo, where, attribute, child_dir, diagnostic):
    parent = "mod api { mod child; }\n"
    selector = "lib/api::child::count"
    marked = "// @at18 TB-01 story US-ST-001\n#[test]\nfn count() {}\n"
    if where == "root":
        parent = attribute + "\n" + parent
    elif where == "inline":
        parent = f"mod api {{\n{attribute}\nmod child;\n}}\n"
    elif where == "nested":
        parent = f"mod outer {{ mod api {{\n{attribute}\nmod child;\n}} }}\n"
        selector = "lib/outer::api::child::count"
    elif where == "child":
        marked = attribute + "\n" + marked
    else:
        parent = f"mod api {{\n{attribute}\nmod child;\n}}\n"
    source = f"rust/src/{child_dir}/child.rs"
    bind(repo, marked, runner="cargo-test", selector=selector, source=source)
    (repo / "rust/src/lib.rs").write_text(parent)
    (repo / "rust/Cargo.toml").write_text(RUST_PACKAGE)
    result = lint(repo)
    assert result.returncode == 1
    assert f"CHECK_SELECTOR: Rust {diagnostic}" in result.stderr


@pytest.mark.parametrize("drift", ["changed-bytes", "symlink", "repinned-outside-f"])
def test_check_revalidates_loaded_source_at_execution(repo, drift):
    check = bind(repo, PY_CASE)
    head = commit(repo, "F")
    loaded = load(repo)
    path = repo / check["source"]["path"]
    if drift == "symlink":
        target = repo / "test_other.py"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.write_text(PY_CASE + "# later bytes\n")
        if drift == "repinned-outside-f":
            loaded[0]["checks"][0]["source"]["sha256"] = sha(path.read_bytes())
    out = repo / "results"
    assert not run_group(repo, loaded, "simulation", "g-1", IDENTITY, out, head=head)
    result = read(out, "execution.json")["checks"][0]
    assert result["status"] == "FAIL" and result["exit_code"] is None
    assert result["diagnostic"] == ("INVALID_PATH" if drift == "symlink" else "CHECK_SOURCE_DRIFT")


def test_destination_membership_rejects_wrong_owner_even_after_repin(repo):
    base = commit(repo, "valid")
    crosswalk = read(repo, CROSSWALK)
    first = next(x for x in crosswalk["destination_success_obligations"] if x["destination_id"] == "DST-01")
    family = next(x for x in crosswalk["family_entry_links"] if x["id"] == "DST-02")
    assert first["destination_id"] not in family["destination_ids"]
    first["family_entry_ids"].append(family["id"])
    write(repo, CROSSWALK, crosswalk)
    reg = read(repo, REGISTRY)
    reg["crosswalk_sha256"] = sha((repo / CROSSWALK).read_bytes())
    write(repo, REGISTRY, reg)
    result = lint(repo, "--base", base)
    assert result.returncode == 1 and "COVERAGE_SOURCE: DST-01.family_entry_ids ownership" in result.stderr


def test_started_key_requires_all_bases_even_when_other_keys_are_unbound(repo):
    assert lint(repo).returncode == 0
    bind(repo, PY_CASE.replace("TB-01", "TB-02"))
    reg = read(repo, REGISTRY)
    bases = canonical_bases(repo, read(repo, CROSSWALK))[0][("TB-02", "story", "US-ST-001")]
    assert len(bases) == 24
    template = reg["bindings"][0] | {"slice_id": "TB-02"}
    reg["bindings"] = [template | {"binding_id": f"b-{i}",
                        "basis": {"path": path, "pointer": ptr, "sha256": sha((repo / path).read_bytes())}}
                       for i, (path, ptr) in enumerate(sorted(bases))]
    write(repo, REGISTRY, reg | {"bindings": reg["bindings"][:1]})
    result = lint(repo)
    assert result.returncode == 1 and "BASIS_INCOMPLETE" in result.stderr
    write(repo, REGISTRY, reg)
    assert lint(repo).returncode == 0


@pytest.mark.parametrize("change", [
    "unaltered", "edited-before", "edited-after", "edited-at-signature", "edit-before-creation",
    "missing-edit-field", "missing-pin-edit-field", "signed-comment-edited", "signed-comment-edited-same-second",
    "new-comment", "same-second-created", "same-second-created-and-edited", "same-second-fraction",
    "truncated", "wrong-count", "graphql-errors", "duplicate-id", "wrong-ticket",
])
def test_authority_observes_edits_to_earlier_comments(monkeypatch, change):
    before, signed, after = ("2026-11-21T00:00:00Z", "2026-11-21T00:00:02Z", "2026-11-21T00:00:03Z")
    pin_id = 5_000_000_006  # GraphQL Int/databaseId 无法表达这样的评论 ID。
    past = {"fullDatabaseId": pin_id - 1, "createdAt": before, "lastEditedAt": None}
    pin = {"fullDatabaseId": str(pin_id), "createdAt": signed, "lastEditedAt": None, "body": "signed body"}
    if change == "edited-before":
        past["lastEditedAt"] = "2026-11-21T00:00:01Z"
    if change == "edited-after":
        past["lastEditedAt"] = after
    if change == "edited-at-signature":
        past["lastEditedAt"] = signed
    if change == "edit-before-creation":
        past["lastEditedAt"] = "2026-11-20T23:59:59Z"
    if change == "missing-edit-field":
        del past["lastEditedAt"]
    if change == "missing-pin-edit-field":
        del pin["lastEditedAt"]
    if change == "signed-comment-edited":
        pin["lastEditedAt"] = after
    if change == "signed-comment-edited-same-second":
        pin["lastEditedAt"] = pin["createdAt"]
    if change == "new-comment":
        past.update(fullDatabaseId=pin_id + 1, createdAt=after)
    if change in {"same-second-created", "same-second-created-and-edited"}:
        past["createdAt"] = signed
    if change == "same-second-created-and-edited":
        past["lastEditedAt"] = signed
    if change == "same-second-fraction":
        past["createdAt"] = "2026-11-21T00:00:02.100Z"
        pin["createdAt"] = "2026-11-21T00:00:02.200Z"
    if change == "duplicate-id":
        past["fullDatabaseId"] = pin_id

    def page(row, more):
        return {"data": {"repository": {"nameWithOwner": "Test/Repo", "issue": {
            "number": 2132 if change == "wrong-ticket" else 2133,
            "comments": {"nodes": [row], "totalCount": 3 if change == "wrong-count" else 2,
                         "pageInfo": {"hasNextPage": more, "endCursor": "fixture-cursor"}},
        }}}}

    pages = [page(past, True), page(pin, False)]
    if change == "truncated":
        pages = pages[:1]
    if change == "graphql-errors":
        pages[1]["errors"] = [{"message": "lastEditedAt unavailable"}]

    def gh(argv, **kwargs):
        if argv[2] == "graphql":
            assert argv[:5] == ["gh", "api", "graphql", "--paginate", "--slurp"]
            query = next(arg.removeprefix("query=") for arg in argv if arg.startswith("query="))
            assert query.lstrip().startswith("query(") and "nodes { fullDatabaseId body createdAt lastEditedAt }" in query
            assert "after: $endCursor" in query and argv[-6:] == ["-f", "owner=test", "-f", "name=repo", "-F", "number=2133"]
            body = pages
        else:
            assert argv == ["gh", "api", "repos/test/repo/issues/2133"]
            body = {}
        return subprocess.CompletedProcess(argv, 0, json_bytes(body), b"")

    monkeypatch.setattr("workflow.subprocess.run", gh)
    rule = {"ticket": 2133, "comment_id": pin_id}
    if change in {"unaltered", "edited-before"}:
        assert authority_comment("test/repo", rule, "fixture") == {
            "id": pin_id, "issue_url": "https://api.github.com/repos/test/repo/issues/2133", "body": pin["body"]}
    else:
        with pytest.raises(Invalid, match="AUTH_REQUIRED"):
            authority_comment("test/repo", rule, "fixture")


@pytest.mark.parametrize("action", ["place", "cancel", "modify", "reduce_only_close"])
def test_experiment_send_hard_gate_precedes_remote_signatures(repo, monkeypatch, action):
    import workflow
    loaded = load(repo)
    rule = loaded[1]["experiment_authorization"]
    rule.update(comment_id=301, body_sha256="a" * 64, group_actions={"g": ["query", action]})
    rule["send_authorization"].update(comment_id=302, body_sha256="b" * 64)
    monkeypatch.setattr(workflow, "authority_comment", lambda *_: pytest.fail("external action blocked before lookup"))
    with pytest.raises(Invalid, match="1412/per-action gate not connected"):
        workflow.authorize(loaded, ["g"], "fixture-token")


@pytest.mark.parametrize("payload_change", [
    'payload["unregistered_fixture_note"] = "CANARY"',
    'payload["conditions"]["debug"] = {"note": "CANARY"}',
    'payload["output"]["samples"] = [{"debug_context": "CANARY"}]',
    'payload["tests"] = [{"check_id": "ck", "source_path": "x", "name": "n", "note": "CANARY"}]',
])
def test_original_record_is_rejected_before_group_upload(repo, payload_change):
    source = "trial/record"
    bind(repo, RECORD_CASE.replace("\ndoc =", f"\n{payload_change}\ndoc ="), runner="command",
         source=source, selector=source, key_aware=True, record="tb.simulation.TB-01")
    loaded = load(repo)
    bundle = repo / "results"
    assert not run_group(repo, loaded, "simulation", "g-1", IDENTITY, bundle)
    assert {p.name for p in bundle.iterdir()} == {"execution.json"}
    raw = (bundle / "execution.json").read_bytes()
    assert b"CANARY" not in raw and b"RECORD_PUBLIC_SCHEMA" in raw


@pytest.mark.parametrize("fault", ["wrong-group", "wrong-attempt", "wrong-head", "failed-job", "failed-step",
                                   "duplicate-job", "extra-anchor", "incomplete-page", "no-anchor"])
def test_server_anchor_is_bound_to_exact_producer(repo, fault):
    bind(repo, PY_CASE)
    loaded = load(repo)
    job = producer_job(loaded, "simulation", "g-1", IDENTITY, "e" * 64)
    assert producer_anchors(loaded, "simulation", IDENTITY, [{"jobs": [job], "total_count": 1}]) == {"g-1": "e" * 64}
    if fault == "wrong-group":
        job["name"] = job["name"].replace("g-1", "g-2")
    if fault == "wrong-attempt":
        job["run_attempt"] += 1
    if fault == "wrong-head":
        job["head_sha"] = "f" * 40
    if fault == "failed-job":
        job["conclusion"] = "failure"
    if fault == "failed-step":
        job["steps"][0]["conclusion"] = "failure"
    if fault == "extra-anchor":
        job["steps"] *= 2
    if fault == "no-anchor":
        job["steps"] = []
    with pytest.raises(Invalid, match="RECORD_UNSEALED"):
        producer_anchors(loaded, "simulation", IDENTITY, [
            {"jobs": [job], "total_count": 2 if fault == "incomplete-page" else 1}
        ] if fault != "duplicate-job" else [{"jobs": [job], "total_count": 2}] * 2)


def test_seal_rejects_a_fully_self_consistent_substitution(repo):
    register_r03_record(repo, R03_CASES[0])
    loaded = load(repo)
    bundle = repo / "artifact" / bundle_name("simulation", IDENTITY["run_attempt"], "g-1")
    assert run_group(repo, loaded, "simulation", "g-1", IDENTITY, bundle)
    anchor = sha((bundle / "execution.json").read_bytes())
    manifest = read(bundle, "execution.json")
    row = manifest["records"][0]
    raw = read(bundle, row["path"])
    raw["payload"]["output"]["samples"] = [90]
    row["sha256"] = sha(json_bytes(raw))
    revised = "record-" + row["sha256"] + ".json"
    (bundle / row["path"]).rename(bundle / revised)
    row["path"] = revised
    write(bundle, revised, raw)
    write(bundle, "execution.json", manifest)
    # 变化后的包内引用仍完整，但无权替换生产者从 Jobs API 传出的锚。
    with pytest.raises(Invalid, match="producer manifest sha256"):
        seal_matrix(loaded, "simulation", IDENTITY, bundle.parent, {"g-1": anchor})
    with pytest.raises(Invalid, match="producer manifest sha256"):
        _manifest(loaded, "simulation", "g-1", IDENTITY, bundle, anchor)


def test_permission_record_closes_nested_objects_and_does_not_archive_refusal_debug(repo):
    contract = load(repo)[1]
    rule = contract["run_records"]["permission.experiment"]
    timestamp = "2026-11-21T00:00:00Z"
    record = {"schema_version": rule["version"], "venue_profile_sha256": "a" * 64,
              "capability_record_sha256": "b" * 64, "derived_credential_public_id": "public-id",
              "user_role": {"request": {"public_id": "public-id"},
                            "response": {"role": "agent", "data": {"user": "public-id"}},
                            "received_at": timestamp},
              "binding": {"writer_epoch": 2, "profile_id": "P1-demo", "profile_version": 3,
                          "venue_profile_sha256": "a" * 64, "capability_record_version": "P1-v1",
                          "capability_record_sha256": "b" * 64, "tb09_fingerprint": "d" * 64,
                          "authorization_id": "ticket:2133", "evidence_class": "experiment"},
              "launch": {"writer_epoch": 2, "launch_seq": 1, "launched_at": timestamp,
                         "tb09_fingerprint_computed": "d" * 64, "credential_public_id_verified": True,
                         "session_permission_verified": True, "send_state": "refused",
                         "send_refusal_class": "ReadOnly", "send_refusal_detail": None}}
    assert adapter.public_payload(contract, "permission.experiment", record)["role_user"] == "public-id"
    for path, field, value in [
        (("user_role", "response", "data"), "debug", {"request_dump": "CANARY"}),
        (("binding",), "context", "CANARY"),
        (("launch",), "send_refusal_detail", "CANARY"),
    ]:
        mutated = copy.deepcopy(record)
        adapter.pointer(mutated, "/" + "/".join(path))[field] = value
        with pytest.raises(Invalid, match="RECORD_PUBLIC_SCHEMA"):
            adapter.public_payload(contract, "permission.experiment", mutated)


def test_experiment_failure_uploads_only_new_closed_diagnostic(repo):
    workflow = yaml.safe_load((ROOT / ".github/workflows/at18-experiment.yml").read_text())
    steps = workflow["jobs"]["checks"]["steps"]
    primary, diagnostic = [step for step in steps if step.get("uses") == "actions/upload-artifact@v4"]
    assert primary["if"] == "steps.run.outcome == 'success'"
    assert diagnostic["if"] == "${{ !cancelled() && steps.diagnostic.outcome == 'success' }}"
    assert diagnostic["with"]["path"] == "${{ steps.workspace.outputs.path }}/diagnostic.json"
    assert diagnostic["with"]["name"].startswith("at18-diagnostic-")
    head = commit(repo, "F")
    env = os.environ | {"GITHUB_SHA": head, "GITHUB_RUN_ID": "4", "GITHUB_RUN_ATTEMPT": "2",
                        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main"}
    temp = repo / "fixture-run"
    temp.mkdir()
    write(temp, "execution/raw.json", {"unregistered_fixture_note": "CANARY"})
    output = temp / "diagnostic.json"
    command = (sys.executable, str(PROGRAMS / "workflow.py"), "diagnostic", "experiment",
               "--root", str(repo), "--output", str(output))
    sh(repo, *command, env=env)
    assert read(temp, "diagnostic.json") == {
        "schema_version": "at18-diagnostic/1", **run_identity(head, 4, 2),
        "evidence_class": "experiment", "status": "GROUP_REJECTED"}
    assert sh(repo, *command, env=env, check=False).returncode == 1
