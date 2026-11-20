use std::{collections::BTreeSet, num::NonZeroU32};

use serde_json::{json, Value};

use super::registry::{sha256, Authority, OriginalKind, Row, Store};
use super::*;
use crate::theta_v0::policy_records::{PolicyError, PolicyVersion, ACTIVE_EVIDENCE_GATE_JSON};

const P0: CostStopProfile = CostStopProfile::P0;
const P1: CostStopProfile = CostStopProfile::P1HlTestnet;
const P0_JSON: &str = include_str!("../policy_records/cost-stop/P0.v1.json");
const P1_JSON: &str = include_str!("../policy_records/cost-stop/P1-hl-testnet.v1.json");
const FEE_BOOK: &[u8] =
    include_bytes!("../../../../analysis/data_cache/venue_fee_binance_spot_20260726.json");
const GATE: &str = "#1677/evidence-gate/v1";
const PREREG: &str = "fixture/windows";
const RUN: &str = "fixture/run";
const COMPONENTS: [&str; 3] = ["slippage", "latency_error", "holding"];
const COSTS: [&str; 3] = ["fixture/slippage", "fixture/latency", "fixture/holding"];
const FIRST: i64 = 1_514_764_800; // 2018-01-01 00:00 UTC
const DAY: i64 = 86_400;
const YEAR: i64 = 366 * DAY;
const STARTED: i64 = 1_800_000_000;
const AT_GATE: u64 = 5_200_000;
const AMP_GAP: CostStopStatus = CostStopStatus::InsufficientEvidence(InsufficientReason::Amplitude);
const UPPER_GAP: CostStopStatus =
    CostStopStatus::InsufficientEvidence(InsufficientReason::UpperBoundOnly);
const MEASURED_FAIL: CostStopStatus = CostStopStatus::Disabled(FailureBasis::Measured);
const PROXY_FAIL: CostStopStatus = CostStopStatus::Disabled(FailureBasis::UpperBoundOnly);
const ZERO: CostStopStatus = CostStopStatus::NotEvaluable(NotEvaluableReason::ZeroTotalCost);

fn revision(n: u32) -> NonZeroU32 {
    NonZeroU32::new(n).unwrap()
}

fn fixture_row(kind: OriginalKind, key: &'static str, bytes: &'static [u8]) -> Row {
    Row {
        kind,
        key,
        path: key,
        bytes,
        sha256: Box::leak(sha256(bytes).into_boxed_str()),
        authority: Authority::TestOnly,
    }
}

fn value_row(kind: OriginalKind, key: &'static str, value: Value) -> Row {
    fixture_row(
        kind,
        key,
        Box::leak(serde_json::to_vec(&value).unwrap().into_boxed_slice()),
    )
}

fn bound(row: Row) -> Value {
    json!({"key":row.key, "sha256":row.sha256})
}
fn span(first_bar: i64, last_bar: i64) -> Value {
    json!({"first_bar":first_bar, "last_bar":last_bar})
}

fn signed(profile: CostStopProfile) -> Value {
    serde_json::from_str(if profile == P0 { P0_JSON } else { P1_JSON }).unwrap()
}

struct Case {
    profile: CostStopProfile,
    policy: Value,
    gate: Row,
    prereg: Value,
    run: Value,
    readings: [Option<Value>; 3],
    extra: Vec<Row>,
    include_run: bool,
    include_prereg: bool,
}

impl Case {
    fn new(profile: CostStopProfile, level: u32, rates: [u64; 3], lower_bounds: &[u64]) -> Self {
        let mut policy = signed(profile);
        policy["version"] = json!(2);
        policy["supersedes"] = json!("v1");
        let domain = json!({
            "profile_id": profile.label(), "symbol": "BTC", "granularity": "1m", "tower_base_ref": "tower-base/1",
            "fee_tier": policy["fee"]["tier"],
        });
        let readings = std::array::from_fn(|i| {
            policy[COMPONENTS[i]] = json!({"kind":"Known", "source":"bind-fixture"});
            if i == 2 {
                policy["holding"]["start_level"] = json!(0);
            }
            Some(json!({
                "schema":"test-only/cost-reading/0", "component":COMPONENTS[i], "basis":"Measured",
                "domain":domain, "level":level, "rate":rates[i],
            }))
        });
        let gate = fixture_row(
            OriginalKind::EvidenceGate,
            GATE,
            ACTIVE_EVIDENCE_GATE_JSON.as_bytes(),
        );
        let mut windows = Vec::new();
        let mut samples = Vec::new();
        for (i, &lower_bound) in lower_bounds.iter().enumerate() {
            let first = FIRST + i as i64 * YEAR;
            windows.push(span(first, first + YEAR - 60));
            for month in 0..12 {
                let middle = first + (14 + month * 30) * DAY;
                for j in 0..if month < 6 { 3 } else { 2 } {
                    let ts = middle + j * 60;
                    samples.push([ts, ts, i64::try_from(lower_bound).unwrap()]);
                }
            }
        }
        let dataset = json!({
            "id":"fixture/data", "sha256":"a".repeat(64), "first_bar":FIRST,
            "last_bar": FIRST + 2 * (YEAR - 60) * lower_bounds.len().max(3) as i64,
        });
        let prereg = json!({
            "schema":"cost-stop/prereg-windows/1", "domain":domain, "dataset":dataset,
            "evidence_gate":bound(gate), "frozen_at":STARTED - 1, "windows":windows,
        });
        let run = json!({
            "schema":"cost-stop/amplitude-run/1", "domain":domain, "dataset":dataset,
            "evidence_gate":bound(gate), "prereg":"bind-fixture", "level":level,
            "pairing":"ROUNDTRIP", "method_id":"test-only/constant-window/0", "run_started_at":STARTED,
            "samples":samples,
        });
        Self {
            profile,
            policy,
            gate,
            prereg,
            run,
            readings,
            extra: Vec::new(),
            include_run: true,
            include_prereg: true,
        }
    }

    fn p0(level: u32, rates: [u64; 3], bounds: &[u64]) -> Self {
        Self::new(P0, level, rates, bounds)
    }
    fn zero() -> Self {
        let mut case = Self::p0(0, [0; 3], &[0; 3]);
        case.policy["fee"]["rate"]["numerator"] = json!(0);
        case
    }

    fn proxy(&mut self, i: usize) {
        self.policy[COMPONENTS[i]]["kind"] = json!("ProxyLowerBound");
        self.readings[i].as_mut().unwrap()["basis"] = json!("ProxyLowerBound");
    }

    fn replace_gate(&mut self, mutate: impl FnOnce(&mut Value)) {
        let mut gate: Value = serde_json::from_slice(self.gate.bytes).unwrap();
        mutate(&mut gate);
        self.gate = value_row(OriginalKind::EvidenceGate, self.gate.key, gate);
        self.run["evidence_gate"] = bound(self.gate);
        self.prereg["evidence_gate"] = bound(self.gate);
    }

    fn with_data_end(&mut self, last_bar: i64) {
        self.run["dataset"]["last_bar"] = json!(last_bar);
        self.prereg["dataset"]["last_bar"] = json!(last_bar);
    }

    fn rows(mut self) -> Vec<Row> {
        let mut rows = vec![self.gate];
        for (i, reading) in self.readings.into_iter().enumerate() {
            if let Some(reading) = reading {
                let row = value_row(OriginalKind::CostReading, COSTS[i], reading);
                if self.policy[COMPONENTS[i]]["source"] == "bind-fixture" {
                    self.policy[COMPONENTS[i]]["source"] = bound(row);
                }
                rows.push(row);
            } else if self.policy[COMPONENTS[i]]["source"] == "bind-fixture" {
                self.policy[COMPONENTS[i]]["source"] =
                    json!({"key":COSTS[i], "sha256":"f".repeat(64)});
            }
        }
        let table = value_row(OriginalKind::PreregWindows, PREREG, self.prereg);
        if self.run["prereg"] == "bind-fixture" {
            self.run["prereg"] = bound(table);
        }
        if self.include_prereg {
            rows.push(table);
        }
        if self.include_run {
            rows.push(value_row(OriginalKind::AmplitudeRun, RUN, self.run));
        }
        rows.push(value_row(
            OriginalKind::Policy,
            policy_key(self.profile, 2),
            self.policy,
        ));
        rows.extend(self.extra);
        rows
    }

    fn eval(self, level: u32) -> CostStopOutcome {
        let profile = self.profile;
        evaluate(self.rows(), profile, 2, level)
    }
}

fn policy_key(profile: CostStopProfile, revision: u32) -> &'static str {
    match (profile, revision) {
        (P0, 1) => "#1354/cost-stop-policy/P0@1",
        (P1, 1) => "#1354/cost-stop-policy/P1-hl-testnet@1",
        (P0, 2) => "#1354/cost-stop-policy/P0@2",
        (P1, 2) => "#1354/cost-stop-policy/P1-hl-testnet@2",
        _ => unreachable!(),
    }
}

fn evaluate(rows: Vec<Row>, profile: CostStopProfile, rev: u32, level: u32) -> CostStopOutcome {
    CostStopPolicy::load_from(Store::test_only(rows), profile, revision(rev))
        .unwrap()
        .evaluate(level)
        .unwrap()
}

fn gap(outcome: CostStopOutcome, expected: AmplitudeGap) {
    assert_eq!(outcome.status(), AMP_GAP);
    assert_eq!(outcome.amplitude_gap(), Some(&expected));
    assert!(outcome.windows().is_empty());
}

fn unavailable(outcome: CostStopOutcome, component: CostComponent, cost_gap: CostGap) {
    assert_eq!(
        outcome.status(),
        CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(component))
    );
    assert_eq!(outcome.cost_gap(), Some((component, cost_gap)));
    assert_eq!(outcome.amplitude_gap(), None);
}

#[test]
fn p0_p1_v1_not_evaluable_on_slippage() {
    for profile in [P0, P1] {
        let row = *Store::registered()
            .rows_of(OriginalKind::Policy)
            .find(|row| row.key == policy_key(profile, 1))
            .unwrap();
        for level in [0, 1, 5] {
            unavailable(
                evaluate(vec![row], profile, 1, level),
                CostComponent::Slippage,
                CostGap::SignedMissing,
            );
        }
    }
}

#[test]
fn v1_matches_adr_0044() {
    // §一、§签署记录：签署值与已裁来源，逐 profile 核对；不是从登记行自证。
    for (profile, fee, fee_den, venue, tier, url, retrieved_at, fee_ref) in [
        (
            P0,
            1,
            1_000,
            "BINANCE_SPOT",
            "VIP0",
            "https://www.binance.com/en/fee/trading",
            "2026-07-26",
            Some("analysis/data_cache/venue_fee_binance_spot_20260726.json"),
        ),
        (
            P1,
            45,
            100_000,
            "Hyperliquid 主 DEX 永续",
            "Tier 0 Base rate",
            "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees",
            "2026-10-20",
            None,
        ),
    ] {
        let policy = CostStopPolicy::load(profile, revision(1)).unwrap();
        let read_fee = policy.fee();
        assert_eq!(policy.record().version, PolicyVersion::Signed(1));
        assert_eq!(policy.identity().key(), policy_key(profile, 1));
        assert_eq!(policy.domain().profile_id(), profile.label());
        assert_eq!(
            (
                policy.domain().symbol(),
                policy.domain().granularity(),
                policy.domain().tower_base_ref()
            ),
            ("BTC", "1m", "tower-base/1")
        );
        assert_eq!(
            (
                policy.theta().numerator(),
                policy.theta().denominator().get()
            ),
            (2, 1)
        );
        assert_eq!(policy.supersedes(), "none");
        assert_eq!(
            (
                read_fee.venue(),
                read_fee.tier(),
                read_fee.role(),
                read_fee.source_url().as_str(),
                read_fee.retrieved_at()
            ),
            (venue, tier, "taker", url, retrieved_at)
        );
        assert_eq!(
            (
                read_fee.rate().numerator(),
                read_fee.rate().denominator().get()
            ),
            (fee, fee_den)
        );
        assert_eq!(read_fee.record_ref().map(SourceRef::as_str), fee_ref);
        assert_eq!(policy.evidence_gate_ref(), GATE);
        let (ref_, authorized_at, valid_through) = policy.authorization();
        assert_eq!(
            ref_,
            "https://github.com/xy7365527-lang/NewChanlun/issues/1559#issuecomment-6310844461"
        );
        assert_eq!((authorized_at, valid_through), ("2026-10-21", "2027-10-21"));
        let (slip, latency, holding) = policy.cost_terms();
        assert_eq!(slip, &CostTerm::Missing);
        match (profile, latency, holding) {
            (
                P0,
                CostTerm::ProxyLowerBound(SourceBinding::Unbound(probe)),
                HoldingTerm::Missing {
                    start_level: 0,
                    designated_source: None,
                },
            ) => assert_eq!(
                probe.as_str(),
                ".chanlun/review-results/issue907-cost-gate-level-20260805.md:161-169"
            ),
            (
                P1,
                CostTerm::Missing,
                HoldingTerm::Missing {
                    start_level: 0,
                    designated_source: Some(source),
                },
            ) => assert_eq!(
                source.as_str(),
                "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding"
            ),
            other => panic!("签署成本项不符：{other:?}"),
        }
    }
}

#[test]
fn threshold_table() {
    for (value, expected) in [
        (AT_GATE - 1, MEASURED_FAIL),
        (AT_GATE, CostStopStatus::Enabled),
        (AT_GATE + 1, CostStopStatus::Enabled),
    ] {
        assert_eq!(
            Case::p0(0, [100_000, 200_000, 300_000], &[value; 3])
                .eval(0)
                .status(),
            expected
        );
    }
    for (bound, status) in [
        (1_799_999, MEASURED_FAIL),
        (1_800_000, CostStopStatus::Enabled),
    ] {
        assert_eq!(
            Case::new(P1, 0, [0; 3], &[bound; 3]).eval(0).status(),
            status
        );
    }
    let rates = [100_000, 200_000, 300_000];
    for bounds in [
        vec![AT_GATE, AT_GATE - 1, AT_GATE],
        vec![AT_GATE, AT_GATE - 1, AT_GATE, AT_GATE + 1],
    ] {
        assert_eq!(Case::p0(0, rates, &bounds).eval(0).status(), MEASURED_FAIL);
    }
    assert_eq!(
        Case::p0(0, [200_000, 200_000, 300_000], &[AT_GATE - 1; 3])
            .eval(0)
            .status(),
        MEASURED_FAIL
    );
    for basis in [[true, false], [false, true], [true, true]] {
        for (bound, expected) in [
            (AT_GATE - 1, PROXY_FAIL),
            (AT_GATE, UPPER_GAP),
            (AT_GATE + 1, UPPER_GAP),
        ] {
            let mut case = Case::p0(0, rates, &[bound; 3]);
            for (i, proxy) in basis.into_iter().enumerate() {
                if proxy {
                    case.proxy(i);
                }
            }
            assert_eq!(case.eval(0).status(), expected);
        }
    }
    for level in [0, 1] {
        let mut case = Case::p0(level, rates, &[AT_GATE; 3]);
        case.policy["holding"] = json!({"kind":"Missing","start_level":1});
        let outcome = case.eval(level);
        if level == 0 {
            assert_eq!(outcome.status(), CostStopStatus::Enabled);
        } else {
            unavailable(outcome, CostComponent::Holding, CostGap::SignedMissing);
        }
    }
}

#[test]
fn level_is_only_an_input() {
    for level in [0, 1, 5] {
        let outcome = Case::p0(level, [0; 3], &[4_000_000; 3]).eval(level);
        assert_eq!(outcome.status(), CostStopStatus::Enabled);
        assert_eq!(outcome.windows().len(), 3);
    }
}

#[test]
fn registry_rows_verify_and_parse() {
    let store = Store::registered();
    for profile in [P0, P1] {
        CostStopPolicy::load(profile, revision(1)).unwrap();
    }
    let gate = store.fetch(OriginalKind::EvidenceGate, GATE).unwrap();
    assert_eq!(
        crate::theta_v0::evidence_gate::parse_record(Some(
            std::str::from_utf8(gate.bytes()).unwrap()
        ))
        .unwrap()
        .0
        .record
        .label(),
        gate.identity().key()
    );
    let mut layers = BTreeSet::new();
    for kind in [
        OriginalKind::Policy,
        OriginalKind::EvidenceGate,
        OriginalKind::PreregWindows,
        OriginalKind::AmplitudeRun,
        OriginalKind::CostReading,
    ] {
        for row in store.rows_of(kind) {
            let original = store.fetch(kind, row.key).unwrap();
            assert!(matches!(original.authority(), Authority::Registered { .. }));
            assert!(!std::str::from_utf8(original.bytes())
                .unwrap()
                .contains("test-only/"));
            if kind == OriginalKind::AmplitudeRun {
                let run: Value = serde_json::from_slice(original.bytes()).unwrap();
                assert!(layers.insert(
                    json!([
                        run["domain"],
                        run["level"],
                        run["pairing"],
                        run["evidence_gate"]["key"]
                    ])
                    .to_string()
                ));
            }
        }
    }
}

#[test]
fn tampered_bytes_fail_digest() {
    let mut row = fixture_row(OriginalKind::Policy, policy_key(P0, 1), P0_JSON.as_bytes());
    let mut policy = signed(P0);
    policy["theta"]["numerator"] = json!(1);
    row.bytes = Box::leak(serde_json::to_vec(&policy).unwrap().into_boxed_slice());
    assert!(
        matches!(CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)),
        Err(PolicyError::Invalid { field, .. }) if field == "content_sha256")
    );
}

#[test]
fn reregistered_copy_is_not_signed() {
    let mut policy = signed(P0);
    policy["theta"]["numerator"] = json!(1);
    let mut row = value_row(OriginalKind::Policy, policy_key(P0, 1), policy);
    let original = Store::registered()
        .fetch(OriginalKind::Policy, policy_key(P0, 1))
        .unwrap();
    row.authority = original.authority();
    let copy = CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)).unwrap();
    assert_eq!(copy.record().version, PolicyVersion::ResearchOverride);
    unavailable(
        copy.evaluate(0).unwrap(),
        CostComponent::Slippage,
        CostGap::SignedMissing,
    );
    row.authority = Authority::Registered {
        reference: "fixture/wrong-approval",
    };
    assert!(
        matches!(CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)),
        Err(PolicyError::Invalid { field, .. }) if field == "authorizer_ref")
    );
}

#[test]
fn awaiting_spellings_are_one_state() {
    for (parent, field, expected) in [
        (None, "theta", "theta"),
        (None, "fee", "fee"),
        (Some("theta"), "numerator", "theta.numerator"),
        (Some("fee"), "record_ref", "fee.record_ref"),
    ] {
        for replacement in [None, Some(Value::Null), Some(json!("AwaitingPolicy"))] {
            let mut policy = signed(P0);
            let obj = match parent {
                Some(key) => &mut policy[key],
                None => &mut policy,
            }
            .as_object_mut()
            .unwrap();
            match replacement {
                Some(value) => {
                    obj.insert(field.to_owned(), value);
                }
                None => {
                    obj.remove(field);
                }
            };
            let row = value_row(OriginalKind::Policy, policy_key(P0, 1), policy);
            assert!(
                matches!(CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)),
                Err(PolicyError::AwaitingPolicy { field, .. }) if field == expected)
            );
        }
    }
    let mut row = value_row(OriginalKind::Policy, policy_key(P0, 1), signed(P0));
    row.authority = Authority::AwaitingApproval;
    assert!(
        matches!(CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)),
        Err(PolicyError::AwaitingPolicy { field, .. }) if field == "approval_ref")
    );
}

#[test]
fn same_day_hour_windows_are_insufficient() {
    for value in [4_000_000, 3_999_999] {
        let mut case = Case::p0(0, [0; 3], &[value; 3]);
        let mut windows = Vec::new();
        let mut samples = Vec::new();
        for i in 0..3 {
            let first = FIRST + i * 7200;
            windows.push(span(first, first + 3600));
            for j in 0..30 {
                let t = first + j * 60;
                samples.push(json!([t, t, value]));
            }
        }
        case.prereg["windows"] = json!(windows);
        case.run["samples"] = json!(samples);
        case.with_data_end(FIRST + 18_000);
        gap(
            case.eval(0),
            AmplitudeGap::Window(WindowGap::TooFewBlocks { got: 1, need: 12 }),
        );
    }
}

#[test]
fn reported_counts_are_rejected() {
    for field in ["events", "nonempty_blocks", "lower_bound_95", "confidence"] {
        let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        case.run[field] = json!(30);
        gap(case.eval(0), AmplitudeGap::RunUnreadable);
    }
}

#[test]
fn blocks_equal_distinct_utc_months() {
    let outcome = Case::p0(0, [0; 3], &[AT_GATE; 3]).eval(0);
    let first = &outcome.windows()[0];
    assert_eq!(
        (
            first.samples(),
            first.nonempty_blocks(),
            first.max_month_cluster()
        ),
        (30, 12, 3)
    );
    assert_eq!(
        first
            .month_blocks()
            .iter()
            .map(|&(month, _)| month)
            .collect::<Vec<_>>(),
        (2018 * 12..2019 * 12).collect::<Vec<_>>()
    );
    assert_eq!(first.median_ppb(), (u128::from(AT_GATE) * 2, 2));
    let mut missing_month = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    let samples = missing_month.run["samples"].as_array_mut().unwrap();
    let (end_a, end_b) = (
        samples[26][0].as_i64().unwrap() + 120,
        samples[26][0].as_i64().unwrap() + 180,
    );
    samples[28] = json!([end_a, end_a, AT_GATE]);
    samples[29] = json!([end_b, end_b, AT_GATE]);
    gap(
        missing_month.eval(0),
        AmplitudeGap::Window(WindowGap::TooFewBlocks { got: 11, need: 12 }),
    );
}

#[test]
fn qualification_monotone_in_events() {
    let mut addition = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    let extra = FIRST + 60;
    addition.run["samples"]
        .as_array_mut()
        .unwrap()
        .insert(0, json!([extra, extra, AT_GATE]));
    let output = addition.eval(0);
    assert_eq!(output.status(), CostStopStatus::Enabled);
    assert_eq!(output.windows()[0].samples(), 31);
    for removed in [1, 2] {
        let mut deletion = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        deletion.run["samples"]
            .as_array_mut()
            .unwrap()
            .drain(..removed);
        gap(
            deletion.eval(0),
            AmplitudeGap::Window(WindowGap::TooFewEvents {
                got: 30 - removed,
                need: 30,
            }),
        );
    }
}

#[test]
fn window_rules() {
    let run = |change: fn(&mut Case), expected| {
        let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        change(&mut case);
        gap(case.eval(0), AmplitudeGap::Window(expected));
    };
    run(
        |case| {
            case.prereg["windows"].as_array_mut().unwrap().truncate(2);
            case.with_data_end(FIRST + 3 * (YEAR - 60)); // 覆盖过线，只缺窗数。
            case.run["samples"].as_array_mut().unwrap().truncate(60);
        },
        WindowGap::TooFewWindows { got: 2, need: 3 },
    );
    run(
        |case| {
            case.prereg["windows"][1]["first_bar"] = case.prereg["windows"][0]["last_bar"].clone()
        },
        WindowGap::OverlappingWindows,
    );
    run(
        |case| case.prereg["windows"][0]["first_bar"] = json!(FIRST + 1),
        WindowGap::InvalidWindow,
    );
    run(
        |case| case.prereg["windows"][0]["first_bar"] = json!(FIRST - 60),
        WindowGap::InvalidWindow,
    );
    run(
        |case| case.with_data_end(FIRST + 6 * (YEAR - 60) + 60),
        WindowGap::InsufficientCoverage,
    );
    run(
        |case| case.run["samples"][0][1] = json!(FIRST),
        WindowGap::InvalidEvent { index: 0 },
    );
    run(
        |case| case.run["samples"][0][1] = json!(FIRST + 14 * DAY + 1),
        WindowGap::InvalidEvent { index: 0 },
    );
    run(
        |case| case.run["samples"][1] = case.run["samples"][0].clone(),
        WindowGap::UnorderedEvents { index: 1 },
    );
    run(
        |case| {
            case.run["samples"][0][1] = json!(FIRST + YEAR); // 进入窗但未在该窗退出。
        },
        WindowGap::TooFewEvents { got: 29, need: 30 },
    );
    run(
        |case| {
            case.replace_gate(|gate| {
                gate["fields"]["block_unit"]["value"] = json!("FixedBars1m{43200}")
            })
        },
        WindowGap::UnsupportedBlockUnit,
    );
    run(
        |case| {
            case.policy["granularity"] = json!("5m");
            case.run["domain"]["granularity"] = json!("5m");
            case.prereg["domain"]["granularity"] = json!("5m");
            for reading in case.readings.iter_mut().flatten() {
                reading["domain"]["granularity"] = json!("5m");
            }
        },
        WindowGap::UnsupportedGranularity,
    );
}

#[test]
fn header_and_timing_rules() {
    let run = |change: fn(&mut Case), expected| {
        let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        change(&mut case);
        gap(case.eval(0), expected);
    };
    run(
        |case| case.policy["evidence_gate_ref"] = json!("nonexistent/gate"),
        AmplitudeGap::EvidenceGateUnavailable,
    );
    run(
        |case| case.replace_gate(|gate| gate["version"] = json!(2)),
        AmplitudeGap::GateIdentity,
    );
    run(
        |case| case.run["evidence_gate"]["sha256"] = json!("0".repeat(64)),
        AmplitudeGap::GateDigest,
    );
    run(
        |case| case.include_prereg = false,
        AmplitudeGap::PreregUnavailable,
    );
    run(
        |case| case.run["prereg"] = json!({"key":"missing/path", "sha256":"0".repeat(64)}),
        AmplitudeGap::PreregUnavailable,
    );
    run(
        |case| case.run["prereg"] = json!({"key":PREREG, "sha256":"0".repeat(64)}),
        AmplitudeGap::PreregUnavailable,
    );
    run(
        |case| case.prereg["schema"] = json!("other"),
        AmplitudeGap::PreregUnreadable,
    );
    run(
        |case| case.prereg["dataset"]["id"] = json!("other"),
        AmplitudeGap::PreregMismatch,
    );
    run(
        |case| case.prereg["domain"]["fee_tier"] = json!("other"),
        AmplitudeGap::PreregMismatch,
    );
    run(
        |case| case.prereg["evidence_gate"]["sha256"] = json!("0".repeat(64)),
        AmplitudeGap::PreregMismatch,
    );
    run(
        |case| case.prereg["frozen_at"] = json!(STARTED),
        AmplitudeGap::Timing,
    );
    run(
        |case| {
            case.run["run_started_at"] = json!(1_786_751_999); // 2026-08-14 23:59:59 UTC
            case.prereg["frozen_at"] = json!(1_786_751_998);
        },
        AmplitudeGap::Timing,
    );
}

#[test]
fn zero_or_many_runs_are_insufficient() {
    let mut none = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    none.include_run = false;
    gap(none.eval(0), AmplitudeGap::NoRun);
    let mut rows = Case::p0(0, [0; 3], &[AT_GATE; 3]).rows();
    let duplicate = *rows
        .iter()
        .find(|row| row.kind == OriginalKind::AmplitudeRun)
        .unwrap();
    rows.push(Row {
        key: "fixture/another-run",
        ..duplicate
    });
    gap(evaluate(rows, P0, 2, 0), AmplitudeGap::AmbiguousRuns);
    let mut wrong_level = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    wrong_level.run["level"] = json!(1);
    gap(wrong_level.eval(0), AmplitudeGap::NoRun);
}

#[test]
fn unknown_method_is_not_ruled() {
    let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    case.run["method_id"] = json!("cost-stop/guess/1");
    gap(case.eval(0), AmplitudeGap::MethodNotRuled);
    let mut not_constant = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    not_constant.run["samples"][0][2] = json!(AT_GATE - 1);
    gap(not_constant.eval(0), AmplitudeGap::MethodRejected);
}

#[test]
fn fee_schedule_is_neither_run_nor_reading() {
    let mut fake_run = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    fake_run.include_run = false;
    fake_run
        .extra
        .push(fixture_row(OriginalKind::AmplitudeRun, RUN, FEE_BOOK));
    gap(fake_run.eval(0), AmplitudeGap::RunUnreadable);

    let wrong_kind = fixture_row(OriginalKind::PreregWindows, "fixture/fee-book", FEE_BOOK);
    let wrong_shape = fixture_row(OriginalKind::CostReading, "fixture/fee-book", FEE_BOOK);
    for (row, reason) in [
        (wrong_kind, CostGap::OriginalUnavailable),
        (wrong_shape, CostGap::ReadingUnreadable),
    ] {
        let mut fake = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        for component in COMPONENTS {
            fake.policy[component]["source"] = bound(row);
        }
        fake.extra.push(row);
        unavailable(fake.eval(0), CostComponent::Slippage, reason);
    }
}

#[test]
fn unbound_v1_refs_never_resolve() {
    let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    case.policy["latency_error"] = signed(P0)["latency_error"].clone();
    unavailable(case.eval(0), CostComponent::LatencyError, CostGap::Unbound);

    let mut removed = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    removed.readings[0] = None;
    unavailable(
        removed.eval(0),
        CostComponent::Slippage,
        CostGap::OriginalUnavailable,
    );
}

#[test]
fn proxy_term_rejects_measured_reading() {
    for (signed_basis, observed_basis) in [
        ("Known", "ProxyLowerBound"),
        ("ProxyLowerBound", "Measured"),
    ] {
        let mut case = Case::p0(0, [0; 3], &[AT_GATE; 3]);
        case.policy["latency_error"]["kind"] = json!(signed_basis);
        case.readings[1].as_mut().unwrap()["basis"] = json!(observed_basis);
        unavailable(
            case.eval(0),
            CostComponent::LatencyError,
            CostGap::ReadingMismatch,
        );
    }
    let mut wrong_scope = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    wrong_scope.readings[0].as_mut().unwrap()["domain"]["profile_id"] = json!(P1.label());
    unavailable(
        wrong_scope.eval(0),
        CostComponent::Slippage,
        CostGap::ReadingMismatch,
    );
    let mut wrong_level = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    wrong_level.readings[0].as_mut().unwrap()["level"] = json!(1);
    unavailable(
        wrong_level.eval(0),
        CostComponent::Slippage,
        CostGap::ReadingMismatch,
    );
}

#[test]
fn unrelated_rows_change_nothing() {
    let with_run = Case::p0(0, [0; 3], &[AT_GATE; 3]);
    let base = with_run.eval(0);
    let mut rows = Case::p0(0, [0; 3], &[AT_GATE; 3]).rows();
    let row = rows
        .iter()
        .find(|row| row.kind == OriginalKind::AmplitudeRun)
        .unwrap();
    let mut other_run: Value = serde_json::from_slice(row.bytes).unwrap();
    other_run["level"] = json!(1);
    rows.push(value_row(
        OriginalKind::AmplitudeRun,
        "fixture/other-level",
        other_run,
    ));
    rows.push(value_row(
        OriginalKind::Policy,
        policy_key(P1, 1),
        signed(P1),
    ));
    let outcome = evaluate(rows, P0, 2, 0);
    assert_eq!(
        (
            outcome.status(),
            outcome.cost_gap(),
            outcome.amplitude_gap(),
            outcome.windows()
        ),
        (
            base.status(),
            base.cost_gap(),
            base.amplitude_gap(),
            base.windows()
        )
    );
}

#[test]
fn known_zero_total_is_not_evaluable_with_qualified_windows() {
    for bound in [0, AT_GATE] {
        let mut case = Case::p0(0, [0; 3], &[bound; 3]);
        case.policy["fee"]["rate"]["numerator"] = json!(0);
        let outcome = case.eval(0);
        assert_eq!(outcome.status(), ZERO);
        assert!(outcome
            .windows()
            .iter()
            .all(|window| window.lower_bound_ppb() == bound));
        assert_eq!(outcome.windows().len(), 3);
    }
}

#[test]
fn insufficient_amplitude_precedes_known_zero_total() {
    let mut case = Case::zero();
    case.include_run = false;
    gap(case.eval(0), AmplitudeGap::NoRun);
}

#[test]
fn signed_and_measured_zero_keep_their_sources() {
    let rows = Case::zero().rows();
    let expected: Vec<_> = std::iter::once(policy_key(P0, 2))
        .chain(COSTS)
        .map(|key| {
            let row = rows.iter().find(|row| row.key == key).unwrap();
            (row.key, row.sha256)
        })
        .collect();
    let policy = CostStopPolicy::load_from(Store::test_only(rows), P0, revision(2)).unwrap();
    assert_eq!(policy.fee().rate().numerator(), 0);
    let outcome = policy.evaluate(0).unwrap();
    assert_eq!(outcome.status(), ZERO);
    assert_eq!(
        outcome.consumed()[..4]
            .iter()
            .map(|id| (id.key(), id.sha256()))
            .collect::<Vec<_>>(),
        expected
    );
}

#[test]
fn zero_proxy_lower_bound_is_not_known_zero() {
    let mut case = Case::zero();
    case.proxy(1);
    let outcome = case.eval(0);
    assert_eq!(outcome.status(), UPPER_GAP);
    assert!(outcome.amplitude_gap().is_none());
    assert_eq!(outcome.windows().len(), 3);
}

#[test]
fn proxy_zero_total_unchanged() {
    for proxy_index in [0, 1] {
        let mut case = Case::zero();
        case.proxy(proxy_index);
        assert_eq!(case.eval(0).status(), UPPER_GAP);
    }
}

#[test]
fn zero_cost_rule_is_level_invariant() {
    for level in [0, 1, 5] {
        let mut case = Case::p0(level, [0; 3], &[0; 3]);
        case.policy["fee"]["rate"]["numerator"] = json!(0);
        assert_eq!(case.eval(level).status(), ZERO);
    }
}

#[test]
fn missing_cost_precedes_insufficient_amplitude() {
    let mut case = Case::zero();
    case.policy["slippage"] = json!({"kind":"Missing"});
    case.include_run = false;
    unavailable(
        case.eval(0),
        CostComponent::Slippage,
        CostGap::SignedMissing,
    );
}

#[test]
fn insufficient_amplitude_precedes_zero_proxy_lower_bound() {
    let mut case = Case::zero();
    case.proxy(0);
    case.include_run = false;
    gap(case.eval(0), AmplitudeGap::NoRun);
}

#[test]
fn positive_known_cost_fails_at_qualified_zero_amplitude() {
    let outcome = Case::p0(0, [0; 3], &[0; 3]).eval(0);
    assert_eq!(outcome.status(), MEASURED_FAIL);
    assert_eq!(outcome.windows().len(), 3);
}

#[test]
fn positive_proxy_lower_bound_fails_at_qualified_zero_amplitude() {
    let mut case = Case::p0(0, [0; 3], &[0; 3]);
    case.proxy(0);
    let outcome = case.eval(0);
    assert_eq!(outcome.status(), PROXY_FAIL);
    assert_eq!(outcome.windows().len(), 3);
}

#[test]
fn policy_and_binding_strictness() {
    fn check(change: impl FnOnce(&mut Value)) {
        let mut value = signed(P0);
        change(&mut value);
        let row = value_row(OriginalKind::Policy, policy_key(P0, 1), value);
        assert!(matches!(
            CostStopPolicy::load_from(Store::test_only(vec![row]), P0, revision(1)),
            Err(PolicyError::Invalid { .. })
        ));
    }
    check(|policy| policy["id"] = json!("other"));
    check(|policy| policy["profile_id"] = json!(P1.label()));
    check(|policy| policy["version"] = json!(2));
    check(|policy| policy["theta"]["numerator"] = json!(0));
    check(|policy| policy["theta"]["denominator"] = json!(0));
    check(|policy| policy["authorizer_ref"] = json!("  "));
    check(|policy| policy["latency_error"]["source_ref"] = json!(""));
    check(|policy| {
        policy["latency_error"]["source"] = json!({"key":"fixture", "sha256":"f".repeat(64)})
    });
    check(|policy| policy["slippage"]["fallback_rate"] = json!(123));
}
