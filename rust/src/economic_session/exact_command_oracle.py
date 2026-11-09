#!/usr/bin/env python3
"""#1407 C1 L9 独立 oracle：只用 Python 标准库，从手写字段算 alpha 的 ExactCommand 规范字节与 sha256。

字段逐项手写自 finance_tests.rs 的 `/5` 夹具（alpha 计划、单位 S 对象、会话 tb03b-unit/1）与
exact_release_tests.rs 的 `decorate_input`；形状对齐 #1942 head 40bf421fc3 的
history_simulation/runtime.rs:85-122 与 model.rs:21-31、186-198。不调用任何 Rust 代码。
用法：python3 exact_command_oracle.py > exact_command_oracle.json
"""
import hashlib
import json


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(v):
    return hashlib.sha256(canonical(v).encode()).hexdigest()


obj = {"object_id": "unit-S-object", "kind": "UnitStructuralTrustRoot", "branch": "RISING"}
s_ref = {"object_id": "unit-S-object", "object_hash": sha(obj), "profile_id": "unit"}
plan = {
    "decision_id": "alpha", "attempt_id": "attempt-alpha", "plan_id": "plan-alpha", "owner": "B:alpha",
    "voice_binding_id": "voice-alpha", "right_id": "alpha", "expected_book_version": "2",
    "expected_rights_version": "1", "applicant_epoch": "1", "applicant_generation": "1", "slot_id": "slot",
    "quantity": "2", "limit_price": "14", "fee_tail": "2", "quantity_source": "TestOnly-quantity/alpha",
    "price_source": "TestOnly-price/alpha", "fee_source": "TestOnly-tail/alpha", "s_ref": s_ref,
    "o_ref": {"operation_id": "TestOnly-operation-alpha", "kind": "TestOnlyCashBuy",
              "source_ref": "TestOnly-operation-sheet/alpha", "s_object_id": "unit-S-object", "quantity": "2"},
    "exact": {"command_id": "cmd-alpha", "logical_order_family": "family-alpha", "chong_id": "alpha",
              "revision": "1", "first_quantity": "2", "allocation_id": "alloc-alpha", "side": "buy",
              "symbol": "alpha", "projection_manifest": "TestOnly-projection/alpha",
              "eligibility_ref": "S:cmd-alpha", "concurrency": "single"},
}
# Reserve 的 grant_id：hash([REV, session, generation, slot_id, decision_id, hash(plan)])，REV 为 finance.rs 的 `/1` 常量。
grant_id = sha(["tb03b-finance/1", "tb03b-unit", "1", "slot", "alpha", sha(plan)])
conditions = [
    {"condition_id": cid, "authority_revision": cap, "dependency_set": ["controlled-dependency"],
     "invalidation_sources": ["controlled-invalidation"], "required_check_stages": [stage],
     "evidence_refs": ["controlled-evidence"], "coverage_proof": "controlled-coverage",
     "validator_capability": cap, "failure_result": "Denied"}
    for cid, cap, stage in [
        ("released-exact/1", "released-exact/1", "E.ReleaseExact"),
        ("execute-committed/1", "execute-committed/1", "S.RequestConditionalExecution"),
        ("simulation-local-transaction/1", "simulation-local-transaction/1", "X.OwnAttemptAndCall"),
        ("model_coverage", "model-coverage/1", "E.ReleaseExact"),
    ]
]
change = {"kind": "submit", "order": {
    "command_id": "cmd-alpha", "family_id": "family-alpha", "chong_id": "alpha", "revision": 1, "side": "buy",
    "quantity": 2, "kind": {"kind": "limit", "price": 14}, "eligibility_ref": "S:cmd-alpha",
    "projection_manifest": "TestOnly-projection/alpha"}}
certificate = {
    "rd11_policy": "controlled-fixture-rd11", "responsibility_refs": [grant_id],
    "structure_dependencies": ["unit-S-object@" + s_ref["object_hash"]],
    "market_dependencies": ["TestOnly-market/1407-c1"], "rule_revision": "TestOnly-rule/1407-c1",
    "conditions": conditions}
command = {
    "command_id": "cmd-alpha", "logical_order_family": "family-alpha", "session_id": "tb03b-unit",
    "session_generation": "1", "x_id": "X", "x_epoch": 1, "symbol": "alpha", "projection_kind": "per_leg",
    "change": change, "plan_hash": sha(change), "certificate_hash": sha(certificate), "certificate": certificate}
print(json.dumps({
    "scope": "#1407 C1 L9 hand-built ExactCommand worked example; Python stdlib only",
    "grant_id": grant_id,
    "plan_hash": sha(change),
    "certificate_hash": sha(certificate),
    "command_canonical": canonical(command),
    "command_sha256": sha(command),
}, indent=2, ensure_ascii=False))
