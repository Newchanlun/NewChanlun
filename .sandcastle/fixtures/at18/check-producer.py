"""Use #2131's original public_payload on the exact payload from each R07 artifact."""
import json
import sys
from pathlib import Path

from adapter import public_payload
from common import Invalid, strict_json

repo, evidence, peer = map(Path, sys.argv[1:])
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
    payload = raw["payload"]
    valid = public_payload(contract, raw["record"], payload, allowed_r03=allowed)
    assert len(valid["keys"]) == len(allowed)
    findings.append({"record": raw["record"], "keys": len(allowed), "source": str(source), "accepted": True})
    if raw["record"] == "tb.simulation.TB-01":
        payload = strict_json(peer.read_bytes(), peer.name)
        valid = public_payload(contract, raw["record"], payload, allowed_r03=allowed)
        assert len(valid["keys"]) == 803
        try:
            public_payload(contract, raw["record"], {**payload, "output": {"samples": [[1, 2]]}}, allowed_r03=allowed)
        except Invalid as error:
            assert str(error).startswith("RECORD_PUBLIC_SCHEMA")
        else:
            raise AssertionError("two-dimensional samples accepted by producer")
        findings.append({"record": "upstream-tb01", "keys": 803, "source": str(peer), "accepted": True})
assert len(findings) == 11
print(json.dumps(findings, ensure_ascii=False, indent=2))
