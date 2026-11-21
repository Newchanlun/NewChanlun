use serde_json::{json, Value};
use std::path::Path;

const FX_RELEASE_BOUND_MARKER: &str = "fx-valuation/2:release-bound";

pub const FX1: &str = "fx-valuation/1";
pub const FX2: &str = "fx-valuation/2";

pub fn x_fx2_profile(sockets: &Path) -> Value {
    let authority = |name: &str| {
        json!({
            "socket": sockets.join(name), "authority_id": name, "authority_epoch": "1",
            "schema_revision": "fixture/1", "reply_namespace": "fixture/replies",
            "producer_id": name
        })
    };
    let rate = json!({"numerator": 1, "denominator": 100, "rounding": "ceiling"});
    let conditions = [
        ("released-exact/1", "released-exact/1", "E.ReleaseExact"),
        ("execute-committed/1", "execute-committed/1", "S.RequestConditionalExecution"),
        ("simulation-local-transaction/1", "simulation-local-transaction/1", "X.OwnAttemptAndCall"),
        ("model_coverage", "model-coverage/1", "E.ReleaseExact"),
    ].map(|(id, capability, stage)| {
        json!({
            "condition_id": id, "authority_revision": capability,
            "dependency_set": [FX_RELEASE_BOUND_MARKER], "invalidation_sources": [FX_RELEASE_BOUND_MARKER],
            "required_check_stages": [stage], "evidence_refs": [FX_RELEASE_BOUND_MARKER],
            "coverage_proof": FX_RELEASE_BOUND_MARKER, "validator_capability": capability,
            "failure_result": "Denied"
        })
    });
    json!({
        "profile_revision": "x-execution-profile/4", "mode": "simulation",
        "credential_scope": {"env": "UNUSED_SIMULATION_CREDENTIAL"},
        "history_simulation": {
            "fx_valuation_revision": FX2,
            "model": {
                "model_id": "history-sim/bar-batch-known-frontier/1", "revision": "fixture-1",
                "symbol": "TEST", "quantity_unit": "TEST-UNIT", "currency": "TEST-CASH",
                "tick_value": 1, "rd11_policy": "fixture-rd11",
                "rd12_policy": "per-leg-source-attribution/1", "projection_kind": "per_leg", "seed": "none",
                "fee_profile": {
                    "reference": "fixture-fee/1", "role_source": "fixture-roles/1",
                    "limit_role": "maker", "market_role": "taker", "maker": rate, "taker": rate,
                    "market_slippage_ticks": 1, "market_slippage_source": "fixture-slippage/1"
                }
            },
            "session_id": "pse", "session_generation": "1",
            "x_id": "X", "source_namespace": "x-sim", "source_epoch": "1",
            "socket": sockets.join("x"), "e": authority("e"), "s": authority("s"),
            "conditions": conditions, "timeout_ms": 500, "max_frame_bytes": 262144
        }
    })
}

/// 直接生成重复键字节；不能先把冲突项放进 Value 再序列化。
pub fn duplicate_revision(doc: &Value, key: &str, first: &str, last: &str) -> String {
    let raw = doc.to_string();
    let declared = format!(r#""{key}":"{FX2}""#);
    assert_eq!(raw.matches(&declared).count(), 1);
    raw.replacen(
        &declared,
        &format!(r#""{key}":"{first}","{key}":"{last}""#),
        1,
    )
}
