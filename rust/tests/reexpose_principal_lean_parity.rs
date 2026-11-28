//! #1651：在 rust/ 运行
//! `cargo test --locked --test reexpose_principal_lean_parity -- --ignored --nocapture`。
//! 两端读取同一初态与轨迹。结果可表示时逐字段对拍（含非法 raw 见证）；
//! 超出 `i64` 时对照 Lean 的精确结果、Rust 的 typed error 和两端业务合法性。

use newchan_rust::theta_v0::strategy::ledger::{
    try_tw_step, tw_step, tw_step_legal, TStage, TwEvent, TwState, TwStepError, TwTransitionError,
};
use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
use std::process::{Command, Stdio};

struct Vector {
    name: &'static str,
    initial: TwState,
    units: i64,
    events: Vec<TwEvent>,
    overflow: Option<OverflowBoundary>,
}

struct OverflowBoundary {
    legal: bool,
    free: Value,
    withdrawn: Value,
}

impl Vector {
    fn input(&self) -> Value {
        let s = self.initial;
        json!({
            "name": self.name,
            "initial": {
                "free": s.free,
                "holding": s.holding,
                "withdrawn": s.withdrawn,
                "notional_in": s.notional_in,
                "stage_rank": s.stage.rank(),
                "open_legacy_legs": s.open_legacy_legs,
                "cum_net_cash": s.cum_net_cash,
                "units": self.units,
            },
            "events": self.events.iter().map(|event| {
                let (kind, amount) = match event {
                    TwEvent::RecoverCapital(a) => ("recover_capital", *a),
                    TwEvent::ReexposePrincipal(a) => ("reexpose_principal", *a),
                    TwEvent::EnterEarning => ("enter_earning", 0),
                    TwEvent::ClearCampaign => ("clear_campaign", 0),
                    _ => panic!("对拍输入不包含 {event:?}"),
                };
                json!({"kind": kind, "amount": amount})
            }).collect::<Vec<_>>(),
        })
    }
}

fn vectors() -> Vec<Vector> {
    use TwEvent::*;
    let basis = TwState {
        free: 25,
        holding: 51,
        withdrawn: 100,
        notional_in: 100,
        stage: TStage::EarningShares,
        open_legacy_legs: 0,
        cum_net_cash: -17,
        hwm_gain: 13,
    };
    let with_legs = TwState {
        stage: TStage::CostReduction,
        open_legacy_legs: 2,
        ..basis
    };
    let recovered = TwState {
        stage: TStage::CapitalRecovered,
        ..basis
    };
    let empty = TwState {
        withdrawn: 0,
        ..basis
    };
    let initial = TwState {
        free: 125,
        withdrawn: 0,
        stage: TStage::CostReduction,
        ..basis
    };
    let boundary = TwState {
        free: i64::MAX,
        holding: -2,
        withdrawn: 1,
        notional_in: 1,
        stage: TStage::CostReduction,
        open_legacy_legs: 2,
        cum_net_cash: 11,
        ..basis
    };
    [
        (
            "partial-cost-reduction-with-legs",
            with_legs,
            vec![ReexposePrincipal(40)],
        ),
        (
            "partial-capital-recovered",
            recovered,
            vec![ReexposePrincipal(29)],
        ),
        ("partial-earning", basis, vec![ReexposePrincipal(31)]),
        ("full-earning", basis, vec![ReexposePrincipal(100)]),
        ("clear-same-earning-input", basis, vec![ClearCampaign]),
        ("full-with-legs", with_legs, vec![ReexposePrincipal(100)]),
        ("clear-same-with-legs-input", with_legs, vec![ClearCampaign]),
        ("illegal-zero", basis, vec![ReexposePrincipal(0)]),
        ("illegal-negative", basis, vec![ReexposePrincipal(-3)]),
        ("illegal-overdraw", basis, vec![ReexposePrincipal(101)]),
        ("illegal-no-withdrawn", empty, vec![ReexposePrincipal(1)]),
        (
            "safe-free-boundary",
            TwState {
                free: i64::MAX - 1,
                ..boundary
            },
            vec![ReexposePrincipal(1)],
        ),
        (
            "recover-earn-reexpose-recover",
            initial,
            vec![
                RecoverCapital(100),
                EnterEarning,
                ReexposePrincipal(40),
                RecoverCapital(40),
            ],
        ),
    ]
    .into_iter()
    .map(|(name, initial, events)| Vector {
        name,
        initial,
        units: -9,
        events,
        overflow: None,
    })
    .chain([
        Vector {
            name: "legal-free-overflow",
            initial: boundary,
            units: -9,
            events: vec![ReexposePrincipal(1)],
            overflow: Some(OverflowBoundary {
                legal: true,
                free: json!(9_223_372_036_854_775_808_u64),
                withdrawn: json!(0),
            }),
        },
        Vector {
            name: "illegal-withdrawn-overflow",
            initial: TwState::initial(),
            units: -9,
            events: vec![ReexposePrincipal(i64::MIN)],
            overflow: Some(OverflowBoundary {
                legal: false,
                free: json!(i64::MIN),
                withdrawn: json!(9_223_372_036_854_775_808_u64),
            }),
        },
    ])
    .collect()
}

fn shared_step(legal: bool, s: TwState) -> Value {
    json!({
        "legal": legal,
        "free": s.free,
        "holding": s.holding,
        "withdrawn": s.withdrawn,
        "notional_in": s.notional_in,
        "stage_rank": s.stage.rank(),
        "open_legacy_legs": s.open_legacy_legs,
        "cum_net_cash": s.cum_net_cash,
        "tw": s.tw(),
        "l_wc": s.l_wc(),
    })
}

#[test]
#[ignore = "需 Lean 工具链；用 --ignored --nocapture 显式运行"]
fn reexpose_principal_matches_origin_total_wealth() {
    let formal = Path::new(env!("CARGO_MANIFEST_DIR")).join("../formal");
    let build = Command::new("lake")
        .current_dir(&formal)
        .args(["build", "Origin.TotalWealth"])
        .status()
        .expect("执行 lake build");
    assert!(build.success(), "Origin.TotalWealth 编译失败：{build}");

    let vectors = vectors();
    let fixture = serde_json::to_string(&vectors.iter().map(Vector::input).collect::<Vec<_>>())
        .expect("共用向量可编码");
    let mut lean = Command::new("lake")
        .current_dir(&formal)
        .args([
            "env",
            "lean",
            "--run",
            "Origin/ReexposePrincipalParity.lean",
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("运行 Lean 对拍入口");
    writeln!(lean.stdin.take().expect("Lean stdin"), "{fixture}").expect("传入共用向量");
    let output = lean.wait_with_output().expect("收取 Lean 对拍输出");
    let lean_json = String::from_utf8(output.stdout).expect("Lean 输出应为 UTF-8");
    println!("inputs={fixture}\nlean={lean_json}");
    assert!(
        output.status.success(),
        "Lean {:?}：{}",
        output.status,
        String::from_utf8_lossy(&output.stderr),
    );

    let lean_rows: Vec<Value> = serde_json::from_str(&lean_json).expect("Lean JSON 输出");
    assert_eq!(lean_rows.len(), vectors.len());
    let mut step_count = 0;
    let mut overflow_count = 0;
    for (vector, lean_row) in vectors.iter().zip(&lean_rows) {
        assert_eq!(lean_row["name"], vector.name);
        let lean_steps = lean_row["steps"].as_array().expect("逐步输出");
        assert_eq!(lean_steps.len(), vector.events.len(), "{}", vector.name);
        let mut state = vector.initial;
        let mut units = vector.units;
        let mut hwm_gain = state.hwm_gain;
        if let Some(boundary) = &vector.overflow {
            let [event] = vector.events.as_slice() else {
                panic!("超界向量须是单步：{}", vector.name);
            };
            let lean_shared = &lean_steps[0]["shared"];
            assert_eq!(lean_shared["legal"], boundary.legal, "{}", vector.name);
            assert_eq!(lean_shared["free"], boundary.free, "{}", vector.name);
            assert_eq!(
                lean_shared["withdrawn"], boundary.withdrawn,
                "{}",
                vector.name
            );
            assert_eq!(lean_shared["tw"], state.tw(), "{}", vector.name);
            assert_eq!(lean_steps[0]["units"], units, "{}", vector.name);

            let legal = event.is_legal_from(&state);
            let raw = try_tw_step(&state, *event);
            let checked = tw_step_legal(&state, *event);
            assert_eq!(legal, boundary.legal, "{}", vector.name);
            assert_eq!(
                raw,
                Err(TwStepError::RepresentationOverflow),
                "{}",
                vector.name
            );
            let error = if boundary.legal {
                TwTransitionError::RepresentationOverflow
            } else {
                TwTransitionError::IllegalTransition
            };
            assert_eq!(checked, Err(error), "{}", vector.name);
            println!(
                "rust[{}][0]: legal={legal}; raw={raw:?}; checked={checked:?}",
                vector.name
            );
            overflow_count += 1;
            continue;
        }
        for (i, (&event, lean_step)) in vector.events.iter().zip(lean_steps).enumerate() {
            let legal = event.is_legal_from(&state);
            let raw = try_tw_step(&state, event).expect("结果可表示");
            assert_eq!(tw_step(&state, event), raw, "{}[{i}] raw", vector.name);
            assert_eq!(
                tw_step_legal(&state, event),
                if legal {
                    Ok(raw)
                } else {
                    Err(TwTransitionError::IllegalTransition)
                },
                "{}[{i}] legal",
                vector.name
            );
            state = raw;
            let rust = shared_step(legal, state);
            println!(
                "rust[{}][{i}]={rust}; hwm_gain={}",
                vector.name, state.hwm_gain
            );
            assert_eq!(rust, lean_step["shared"], "{}[{i}] {event:?}", vector.name);

            // 两端不共有的字段分别验其原生契约，不把不同语义合并成一个字段。
            if event == TwEvent::ClearCampaign {
                units = 0;
                hwm_gain = 0;
            }
            assert_eq!(lean_step["units"], units, "{}[{i}] units", vector.name);
            assert_eq!(state.hwm_gain, hwm_gain, "{}[{i}] hwm_gain", vector.name);
            step_count += 1;
        }
    }
    println!(
        "matched_vectors={} matched_steps={step_count} shared_fields_per_step=10 overflow_boundaries={overflow_count}",
        vectors.len() - overflow_count
    );
}
