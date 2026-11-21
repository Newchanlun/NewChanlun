use newchan_rust::theta_v0::{cost_stop as c, policy_records};

#[cfg(issue1441_cost_stop_refusal)]
#[rustfmt::skip]
fn reject_supplied_values(policy: &mut c::CostStopPolicy) {
    let _ = c::AmplitudeEvidence::Insufficient;                      // R1-H1：没有调用方证据类型。
    let _ = policy_records::parse_cost_stop(Some("{}"));              // R1-H2：没有文本装载口。
    let _ = c::SourceRef::new("");                                    // R1-H3：没有引用构造口。
    let _ = policy.evaluate(0, (30, 12));                             // R2-H1：不收申报的事件与块数。
    let _: c::CostStopPolicy = serde_json::from_str("{}").unwrap();    // R2-H2：不能绕过可信装载。
    let _ = policy.evaluate(0, "missing/path");                       // R2-HIGH：不能注入不存在的探针。
    let _ = policy.evaluate(0, "venue_fee_binance_spot_20260726.json");// R2-HIGH：不能注入错类探针。
    let _ = c::CostInputs {};                                         // R2-HIGH：不能注入费用原件。
    let _ = c::CostStopPolicy::load(c::CostStopProfile::P0, "AwaitingPolicy"); // R2-MED：无文本入口。
    let _ = c::CostEvidence::Missing;                                 // R2-LOW：不能注入读数类别。
    let _ = &mut policy.terms;                                        // #2111：不能覆写已装载的成本。
}
