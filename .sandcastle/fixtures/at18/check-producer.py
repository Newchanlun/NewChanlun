"""Use #2131's original public_payload on the exact payload from each R07 artifact."""
import ast
import json
import sys
from pathlib import Path

from adapter import decode_fields, public_payload, tb_test_identity
from common import Invalid, RECORD, SPECIAL, require, strict_json

repo, evidence, peer = map(Path, sys.argv[1:])
# 只装载原函数与常量；Cargo 选择器及 tree-sitter 不参与记录验收。
producer = ast.parse(repo.joinpath("run_checks.py").read_text())
nodes = [node for node in producer.body
         if (isinstance(node, ast.FunctionDef) and node.name == "validate_record")
         or (isinstance(node, ast.Assign) and any(
             isinstance(target, ast.Name) and target.id == "RECORD_FIELDS" for target in node.targets))]
assert len(nodes) == 2
exec(compile(ast.Module(body=nodes, type_ignores=[]), "aae6abf9:run_checks.py", "exec"))
contract = strict_json(repo.joinpath("adapter-contract.json").read_bytes(), "contract")
registry = strict_json(repo.joinpath("registry.json").read_bytes(), "registry")
findings = []
for source in sorted(evidence.glob("tb.*.json")):
    raw = strict_json(source.read_bytes(), source.name)
    allowed = {
        (b["slice_id"], key["kind"], key["id"], b["basis"]["path"], b["basis"]["pointer"])
        for b in registry["bindings"]
        for key in b["keys"]
        if any(raw["check_id"] in domain["checks"] for domain in b["domains"])
    }
    check = next(check for check in registry["checks"] if check["check_id"] == raw["check_id"])
    identity = {key: raw[key] for key in ("head", "run_id", "run_attempt")}
    def verify(record):
        return validate_record(contract, record, check, identity, allowed_r03=allowed, executed_names=[check["selector"]])
    verify(raw)
    payload = raw["payload"]
    valid = public_payload(contract, raw["record"], payload, allowed_r03=allowed)
    assert len(valid["keys"]) == len(allowed)
    findings.append({"record": raw["record"], "keys": len(allowed), "source": str(source), "accepted": True})
    if raw["record"] == "tb.simulation.TB-01":
        payload = strict_json(peer.read_bytes(), peer.name)
        valid = public_payload(contract, raw["record"], payload, allowed_r03=allowed)
        assert len(valid["keys"]) == 803
        verify({**raw, "payload": payload})
        for field, literal, expected in (
            ("processes", "1.0", False), ("processes", "1e0", False),
            ("processes", "9007199254740992", True), ("processes", "9007199254740993", True),
            ("processes", "1" + "0" * 400, True), ("run_attempt", "2.0", False),
        ):
            data = source.read_bytes().replace(f'"{field}":2'.encode(), f'"{field}":{literal}'.encode())
            assert data != source.read_bytes()
            try:
                verify(strict_json(data, field))
            except Invalid:
                assert not expected, (field, literal)
            else:
                assert expected, (field, literal)
        findings[-1]["numeric_cases"] = 6
        try:
            public_payload(contract, raw["record"], {**payload, "output": {"samples": [[1, 2]]}}, allowed_r03=allowed)
        except Invalid as error:
            assert str(error).startswith("RECORD_PUBLIC_SCHEMA")
        else:
            raise AssertionError("two-dimensional samples accepted by producer")
        findings.append({"record": "upstream-tb01", "keys": 803, "source": str(peer), "accepted": True})
assert len(findings) == 11
print(json.dumps(findings, ensure_ascii=False, indent=2))
