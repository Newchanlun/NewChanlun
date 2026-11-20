use std::collections::BTreeSet;

use serde_json::{json, Value};

use super::*;
use crate::diagnostic_fill;
use crate::lav_seal::{digest, jcs};
use crate::theta_v0::config::FillRule;

fn valid_manifest(profile: &str) -> Value {
    json!({
        "manifest_revision": "production-session-manifest/1",
        "profile": profile,
        "state_dir": "/tmp/at14-fixture/state",
        "execution_capabilities": { "namespaces": ["hl.perp.BTC"] },
        "structure_source": {
            "category": "UsEquityStockLineTick",
            "namespaces": ["massive.us.equity.tick"]
        },
        "s": { "db": "/tmp/at14-fixture/s.db" },
        "economic": { "manifest": "/tmp/at14-fixture/economic.json" },
        "x": { "db": "/tmp/at14-fixture/x.db", "profile": "/tmp/at14-fixture/x-profile.json" }
    })
}

fn valid_history_profile(evidence_class: &str, clock_kind: &str) -> Value {
    json!({
        "schema_revision": "history-input-profile/1",
        "evidence_class": evidence_class,
        "clock": {
            "kind": clock_kind,
            "known_frontier_cut": "bar_close"
        },
        "input_source": "massive-stock-tick/1",
        "gap_handling": "preserve-gap/1"
    })
}

fn c3_control_testonly_input_json() -> Value {
    // 形状取自 #1407 C3 control 原件（issue #1418 评论 7023492017）。
    json!({
        "kind": "TestOnly",
        "schema_revision": "tb03b-finance/6",
        "source_epoch": "1",
        "source_id": "unit-fixture",
        "baseline": {
            "amount": "20",
            "responsibility_id": "existing20",
            "source_ref": "TestOnly-existing-full-liability-original"
        },
        "exact_release": {
            "market_dependencies": ["TestOnly-market/1407-c1"],
            "model_coverage": {
                "domain_id": "TestOnly-domain/1407-c1",
                "input_domain": [{
                    "allocation_model": "#1349/atomic-slot-wait/v1",
                    "concurrency": "single",
                    "order_kind": "limit"
                }],
                "model_ref": {
                    "content_hash": "7f7817be1f748290c3761d66cea766845ed379db1962f202f76dc2a7f1afc81f",
                    "model_id": "history-sim/bar-batch-known-frontier/1",
                    "revision": "oracle-1"
                },
                "unsupported_domains": [{
                    "allocation_model": "#1349/atomic-slot-wait/v1",
                    "concurrency": "batched",
                    "order_kind": "limit"
                }]
            },
            "projection_kind": "per_leg",
            "rd11_policy": "controlled-fixture-rd11",
            "rule_revision": "TestOnly-rule/1407-c1",
            "x_target": { "x_epoch": "1", "x_id": "X" }
        },
        "policy": {
            "allocation_policy_id": "#1349/atomic-slot-wait/v1",
            "cap": "100",
            "capability_id": "TestOnly-no-leverage-no-venue",
            "currency": "TEST-CASH",
            "model": "TestOnlyUnleveragedCashBuy",
            "policy_id": "TestOnly-cash-cap-100"
        },
        "plans": [{ "plan_id": "plan-alpha", "owner": "B:alpha" }],
        "rights": [{ "right_id": "alpha", "owner": "B:alpha", "amount": "40" }],
        "slots": [{ "slot_id": "slot", "applicants": ["alpha", "beta"] }]
    })
}

fn sample_fault_schedule() -> Vec<FaultScheduleEntry> {
    vec![FaultScheduleEntry {
        at: FaultTriggerAt::BarIndex(10),
        target: FaultDomain::E,
        kind: FaultKind::CrashAfterCommit,
    }]
}

fn sample_schedule_trace() -> Vec<ScheduleTraceEntry> {
    vec![ScheduleTraceEntry {
        step: 1,
        bar_index: 10,
        stage: "S->B->E->X->fact->B->obs".to_string(),
        triggered_fault: Some(FaultKind::CrashAfterCommit),
        detail: "restarted from checkpoint 9".to_string(),
    }]
}

fn recompute_tuple_hashes(input: &mut At14ReportInput) {
    input.dual_run_tuple.input_profile_hash =
        digest::sha256_hex(&jcs::canonical_bytes(&input.profile_json));
    input.dual_run_tuple.fault_schedule_hash = digest::sha256_hex(&jcs::canonical_bytes(
        &serde_json::to_value(&input.fault_schedule).unwrap(),
    ));
    input.dual_run_tuple.schedule_trace_hash = digest::sha256_hex(&jcs::canonical_bytes(
        &serde_json::to_value(&input.schedule_trace).unwrap(),
    ));
}

fn valid_pass_input() -> At14ReportInput {
    let manifest_json = valid_manifest("simulation");
    let profile_json = valid_history_profile("simulation", "logical-bar/1");
    let fault_schedule = sample_fault_schedule();
    let schedule_trace = sample_schedule_trace();
    let child_domains: BTreeSet<String> = ["S", "E", "B:alpha", "X"]
        .into_iter()
        .map(str::to_string)
        .collect();

    let mut input = At14ReportInput {
        producer: "production_session".to_string(),
        manifest_json,
        profile_json,
        scheduler: DEFAULT_SCHEDULER.to_string(),
        build_fingerprint: BuildFingerprint {
            commit: "b9d898dccf000000000000000000000000000000".to_string(),
            lockfile_hash: digest::sha256_hex(b"Cargo.lock"),
            features: ["production_session".to_string()].into_iter().collect(),
        },
        version_set: VersionSet {
            rule_versions: vec![RuleVersionRef {
                rule_id: "chanlun-strict".to_string(),
                version: "v1".to_string(),
                content_hash: digest::sha256_hex(b"rule-v1"),
            }],
            policy_refs: vec![PolicyRef {
                policy_id: "rd11-funding".to_string(),
                version: "1".to_string(),
                profile_id: Some("P0".to_string()),
                content_hash: digest::sha256_hex(b"policy-v1"),
            }],
            model_ref: ModelRef {
                model_id: MODEL_BAR_BATCH_V1.to_string(),
                revision: "1".to_string(),
                content_hash: digest::sha256_hex(b"model-v1"),
            },
        },
        capability_manifest_hash: digest::sha256_hex(b"capability-manifest"),
        model_execution: ModelExecutionConfig {
            model_id: SimulationModelId::BarBatchKnownFrontierV1,
            seed: ReplaySeed::None,
            capacity_source: CapacitySource::ScenarioContract,
        },
        dual_run_tuple: DualRunFiveTuple {
            input_profile_hash: String::new(),
            input_events_hash: digest::sha256_hex(b"raw-events-seq"),
            fault_schedule_hash: String::new(),
            schedule_trace_hash: String::new(),
            policy_version: "rd11-funding@1".to_string(),
            model_id: MODEL_BAR_BATCH_V1.to_string(),
            model_revision: "1".to_string(),
            seed: ReplaySeed::None,
            scheduler: DEFAULT_SCHEDULER.to_string(),
        },
        actual_load: ActualLoad {
            input_range: InputRange {
                symbols: vec!["AAPL".to_string()],
                from: "2024-01-02T14:30:00Z".to_string(),
                to: "2024-01-02T21:00:00Z".to_string(),
            },
            bar_count: 120,
            checkpoint_count: 120,
        },
        fault_schedule,
        schedule_trace,
        h1: Some(OracleRunInput::Executed {
            diff_count: 0,
            diff_summary: "zero diff across 120 checkpoints".to_string(),
        }),
        h2: Some(OracleRunInput::Executed {
            diff_count: 0,
            diff_summary: "recovered identically after SIGKILL".to_string(),
        }),
        h3: Some(OracleRunInput::Executed {
            diff_count: 0,
            diff_summary: "seek(80) has zero >80 facts".to_string(),
        }),
        h4: Some(OracleRunInput::Executed {
            diff_count: 0,
            diff_summary: "simulation and experiment latches isolated".to_string(),
        }),
        six_faces: SixFacesSummary {
            s_structure_snapshot: FaceSummary {
                row_count: 120,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
            b_chong_ledgers: FaceSummary {
                row_count: 240,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
            e_responsibility: FaceSummary {
                row_count: 60,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
            orders_and_fills: FaceSummary {
                row_count: 18,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
            physical_positions: FaceSummary {
                row_count: 120,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
            external_effect_journal: FaceSummary {
                row_count: 36,
                diff_count: 0,
                diff_summary: "exact match".to_string(),
            },
        },
        fu14_criteria: Fu14CriteriaInput {
            a: CriterionAInput::Observed {
                root_process: "production_session".to_string(),
                child_domains,
            },
            b: CriterionBInput::Observed {
                structure_objects: 12,
                funding_resolutions: 1,
                commands: 6,
                simulated_fills: 4,
                position_projections: 6,
                fault_records: 1,
            },
            c: CriterionCInput::Observed {
                out_of_domain_requests: 2,
                model_order_unspecified_terminals: 2,
                legacy_arm_calls: 0,
            },
            d: CriterionDInput::Observed {
                shadow_outputs_in_verdict: 0,
                untagged_shadow_outputs: 0,
            },
        },
        model_order_unspecified_count: 2,
        diagnostic_not_production_count: 0,
        input_source_unavailable_count: 0,
        input_source: InputSource::MassiveStockTickV1,
        assumption_counts: AssumptionCounts {
            stochastic_l1_count: 0,
            bar_volume_derived_l0_count: 0,
            unconstrained_capacity_l0_count: 0,
        },
        extra_unexecuted: Vec::new(),
        bounded_domain_statement: DEFAULT_BOUNDED_DOMAIN_STATEMENT.to_string(),
        ci_run_id: Some("44634325084".to_string()),
        review_binding: Some("deadbeef0123456789".to_string()),
    };
    recompute_tuple_hashes(&mut input);
    input
}

fn issue1304_dir(tmp: &tempfile::TempDir) -> PathBuf {
    tmp.path()
        .join(".chanlun")
        .join("review-results")
        .join("issue1304-at14-20261120-b9d898d")
}

#[test]
fn positive_control_all_criteria_and_oracles_satisfied_yields_pass() {
    let report = seal_report(valid_pass_input()).expect("valid input must seal");
    assert_eq!(report.verdict(), &ReportVerdict::Pass);
    assert!(report.verdict().is_pass());
    assert_eq!(report.body().schema_version, SCHEMA_VERSION);
    assert_eq!(report.body().h1.result, OracleResult::Pass);
    assert_eq!(report.body().h2.result, OracleResult::Pass);
    assert_eq!(report.body().h3.result, OracleResult::Pass);
    assert_eq!(report.body().h4.result, OracleResult::Pass);
    assert_eq!(
        report.body().fu14_gates.a_launcher_process_tree,
        CheckOutcome::Pass
    );
    assert_eq!(
        report.body().fu14_gates.b_six_domains_nonempty,
        CheckOutcome::Pass
    );
    assert_eq!(
        report.body().fu14_gates.c_model_order_unspecified_no_legacy,
        CheckOutcome::Pass
    );
    assert_eq!(
        report.body().fu14_gates.d_shadow_component_only,
        CheckOutcome::Pass
    );
    assert!(report.body().unexecuted.is_empty());
    assert_eq!(report.body().verification_source_label, None);
}

#[test]
fn rejects_dry_run_and_unknown_evidence_class_from_manifest_profile() {
    let mut dry_run = valid_pass_input();
    dry_run.manifest_json = valid_manifest("dry-run");
    assert_eq!(seal_report(dry_run), Err(At14RejectError::DryRunNotAllowed));

    for bad in ["staging", "paper", "live", "", "SIMULATION"] {
        let mut input = valid_pass_input();
        input.manifest_json = valid_manifest(bad);
        assert_eq!(
            seal_report(input),
            Err(At14RejectError::InvalidEvidenceClass {
                found: Some(bad.to_string())
            })
        );
    }

    let mut missing = valid_pass_input();
    missing
        .manifest_json
        .as_object_mut()
        .unwrap()
        .remove("profile");
    assert_eq!(
        seal_report(missing),
        Err(At14RejectError::InvalidEvidenceClass { found: None })
    );

    // 正对照：experiment 与 production 配合 System 时钟与空 fault_schedule 均被接纳。
    for (ec_str, expected_ec) in [
        ("experiment", EvidenceClass::Experiment),
        ("production", EvidenceClass::Production),
    ] {
        let mut input = valid_pass_input();
        input.manifest_json = valid_manifest(ec_str);
        input.profile_json = valid_history_profile(ec_str, "System");
        input.fault_schedule.clear();
        recompute_tuple_hashes(&mut input);
        let sealed = seal_report(input).expect("experiment/production with System clock accepted");
        assert_eq!(sealed.body().session.evidence_class, expected_ec);
        assert_eq!(sealed.body().session.clock_kind, ClockKind::System);
        assert_eq!(sealed.verdict(), &ReportVerdict::Pass);
    }

    // 负对照：时钟与 evidence_class 不匹配被拒（ADR 0056:52-53）。
    let mut wrong_clock = valid_pass_input();
    wrong_clock.profile_json = valid_history_profile("simulation", "System");
    recompute_tuple_hashes(&mut wrong_clock);
    assert_eq!(
        seal_report(wrong_clock),
        Err(At14RejectError::ClockKindMismatch {
            evidence_class: EvidenceClass::Simulation,
            found: Some("System".to_string()),
        })
    );
}

#[test]
fn rejects_c3_control_testonly_input_and_refuses_to_write_issue1304_dir() {
    let tmp = tempfile::tempdir().unwrap();
    let target_dir = issue1304_dir(&tmp);

    let mut testonly = valid_pass_input();
    testonly.profile_json = c3_control_testonly_input_json();
    recompute_tuple_hashes(&mut testonly);

    let err = seal_and_write_report(testonly, &target_dir).unwrap_err();
    assert!(matches!(err, At14RejectError::TestOnlyInputRejected { .. }));
    assert!(
        !target_dir.exists(),
        "TestOnly input must not create issue1304-at14-* directory"
    );

    let mut testonly_source = valid_pass_input();
    testonly_source.manifest_json["structure_source"]["category"] = json!("TestOnlyStructure");
    let err = seal_and_write_report(testonly_source, &target_dir).unwrap_err();
    assert!(matches!(err, At14RejectError::TestOnlyInputRejected { .. }));
    assert!(!target_dir.exists());

    let mut testonly_clock = valid_pass_input();
    testonly_clock.profile_json["clock"]["kind"] = json!("TestOnly");
    let err = seal_and_write_report(testonly_clock, &target_dir).unwrap_err();
    assert!(matches!(err, At14RejectError::TestOnlyInputRejected { .. }));
    assert!(!target_dir.exists());

    // 正对照：合法输入可落盘且文件可重验。
    let (sealed, files) =
        seal_and_write_report(valid_pass_input(), &target_dir).expect("valid report writes");
    assert!(files.report_json.is_file());
    assert!(files.summary_md.is_file());
    let raw_json = std::fs::read_to_string(&files.report_json).unwrap();
    let verified = verify_sealed_json(&raw_json).expect("written report json must verify");
    assert_eq!(verified.content_hash(), sealed.content_hash());
    assert_eq!(verified.verdict(), &ReportVerdict::Pass);
}

#[test]
fn rejects_issue1718_diagnostic_fill_and_shadow_sessions_without_writing_dir() {
    let tmp = tempfile::tempdir().unwrap();
    let target_dir = issue1304_dir(&tmp);

    let req = diagnostic_fill::Request {
        schema: diagnostic_fill::REQUEST_SCHEMA.to_string(),
        model_id: diagnostic_fill::MODEL_ID.to_string(),
        record_version: "diag-v1".to_string(),
        mode: "diagnostic".to_string(),
        fill_rule: FillRule::Cross(1),
        market_snapshot: "snap-1".to_string(),
        as_of: 100,
        orders: vec![diagnostic_fill::Order {
            id: "o1".to_string(),
            side: diagnostic_fill::Side::Buy,
            quantity: 1,
            limit_ticks: 100,
            submitted_at: 1,
        }],
        bars: vec![diagnostic_fill::Bar {
            opened_at: 1,
            event_time: 10,
            known_at: 10,
            open: 102,
            high: 105,
            low: 98,
            close: 101,
        }],
    };
    let diag_report = diagnostic_fill::replay(req.clone()).expect("diagnostic replay works");
    let diag_comparison = diagnostic_fill::compare(&req).expect("diagnostic compare works");

    for doc in [
        serde_json::to_value(&diag_report).unwrap(),
        serde_json::to_value(&diag_comparison).unwrap(),
    ] {
        let mut input = valid_pass_input();
        input.profile_json = doc;
        let err = seal_and_write_report(input, &target_dir).unwrap_err();
        assert!(matches!(
            err,
            At14RejectError::DiagnosticInputRejected { .. }
        ));
        assert!(!target_dir.exists());
    }

    for shadow in [
        "backtest_bin",
        "theta_backtest",
        "theta_replay",
        "theta_accept",
        "replay_compare",
        "MinimalEngine",
        "ThetaPiStream",
        "run_theta_v0_pi",
    ] {
        let mut input = valid_pass_input();
        input.producer = shadow.to_string();
        let err = seal_and_write_report(input, &target_dir).unwrap_err();
        assert!(matches!(err, At14RejectError::ShadowSessionRejected { .. }));
        assert!(!target_dir.exists());
    }
}

#[test]
fn h1_to_h4_each_unexecuted_missing_capability_or_fail_is_named_non_pass() {
    type Mutator = fn(&mut At14ReportInput, Option<OracleRunInput>);
    let slots: [(&str, Mutator); 4] = [
        (TEST_H1, |i, v| i.h1 = v),
        (TEST_H2, |i, v| i.h2 = v),
        (TEST_H3, |i, v| i.h3 = v),
        (TEST_H4, |i, v| i.h4 = v),
    ];

    for (name, setter) in slots {
        let mut missing = valid_pass_input();
        setter(&mut missing, None);
        let report = seal_report(missing).unwrap();
        assert!(!report.verdict().is_pass());
        match report.verdict() {
            ReportVerdict::Unexecuted { items } => {
                assert!(items.iter().any(|s| s.contains(name)));
            }
            other => panic!("expected Unexecuted for missing {name}, got {other:?}"),
        }
        assert!(report.body().unexecuted.iter().any(|u| u == name));

        let mut unexec = valid_pass_input();
        setter(
            &mut unexec,
            Some(OracleRunInput::Unexecuted {
                reason: "waiting for #1411".to_string(),
            }),
        );
        let report = seal_report(unexec).unwrap();
        assert!(matches!(report.verdict(), ReportVerdict::Unexecuted { .. }));
        assert!(report.body().unexecuted.iter().any(|u| u == name));

        let mut missing_cap = valid_pass_input();
        setter(
            &mut missing_cap,
            Some(OracleRunInput::MissingCapability {
                capability: "recovery arm unavailable".to_string(),
            }),
        );
        let report = seal_report(missing_cap).unwrap();
        assert!(matches!(
            report.verdict(),
            ReportVerdict::MissingCapability { .. }
        ));

        let mut failed = valid_pass_input();
        setter(
            &mut failed,
            Some(OracleRunInput::Executed {
                diff_count: 1,
                diff_summary: "first diff at bar 42".to_string(),
            }),
        );
        let report = seal_report(failed).unwrap();
        assert!(matches!(report.verdict(), ReportVerdict::Mismatch { .. }));
    }

    // 四项全缺。
    let mut all_missing = valid_pass_input();
    all_missing.h1 = None;
    all_missing.h2 = None;
    all_missing.h3 = None;
    all_missing.h4 = None;
    let report = seal_report(all_missing).unwrap();
    match report.verdict() {
        ReportVerdict::Unexecuted { items } => assert_eq!(items.len(), 4),
        other => panic!("expected Unexecuted for all missing, got {other:?}"),
    }
    assert_eq!(
        report.body().unexecuted,
        vec![
            TEST_H4.to_string(),
            TEST_H1.to_string(),
            TEST_H2.to_string(),
            TEST_H3.to_string(),
        ]
    );
}

#[test]
fn fu14_criteria_a_through_d_each_failure_is_non_pass() {
    // (a) 错误根进程或缺少子域。
    let mut bad_a_root = valid_pass_input();
    bad_a_root.fu14_criteria.a = CriterionAInput::Observed {
        root_process: "s_structure_session".to_string(),
        child_domains: ["S", "E", "B:alpha", "X"]
            .into_iter()
            .map(str::to_string)
            .collect(),
    };
    assert!(matches!(
        seal_report(bad_a_root).unwrap().verdict(),
        ReportVerdict::Mismatch { .. }
    ));

    let mut bad_a_domain = valid_pass_input();
    bad_a_domain.fu14_criteria.a = CriterionAInput::Observed {
        root_process: "production_session".to_string(),
        child_domains: ["S", "E", "X"].into_iter().map(str::to_string).collect(),
    };
    assert!(matches!(
        seal_report(bad_a_domain).unwrap().verdict(),
        ReportVerdict::Mismatch { .. }
    ));

    // (b) 六域任一为空。
    let six_zero_cases = [
        (0, 1, 1, 1, 1, 1),
        (1, 0, 1, 1, 1, 1),
        (1, 1, 0, 1, 1, 1),
        (1, 1, 1, 0, 1, 1),
        (1, 1, 1, 1, 0, 1),
        (1, 1, 1, 1, 1, 0),
    ];
    for (s, f, c, fills, p, faults) in six_zero_cases {
        let mut bad_b = valid_pass_input();
        bad_b.fu14_criteria.b = CriterionBInput::Observed {
            structure_objects: s,
            funding_resolutions: f,
            commands: c,
            simulated_fills: fills,
            position_projections: p,
            fault_records: faults,
        };
        assert!(matches!(
            seal_report(bad_b).unwrap().verdict(),
            ReportVerdict::Mismatch { .. }
        ));
    }

    // (c) 域外请求数=0、终态不足、或调用了旧臂。
    for (req, term, legacy) in [(0, 0, 0), (2, 1, 0), (2, 2, 1)] {
        let mut bad_c = valid_pass_input();
        bad_c.fu14_criteria.c = CriterionCInput::Observed {
            out_of_domain_requests: req,
            model_order_unspecified_terminals: term,
            legacy_arm_calls: legacy,
        };
        assert!(matches!(
            seal_report(bad_c).unwrap().verdict(),
            ReportVerdict::Mismatch { .. }
        ));
    }

    // (d) 影子产出进入判据或未标组件证据。
    for (in_verdict, untagged) in [(1, 0), (0, 1)] {
        let mut bad_d = valid_pass_input();
        bad_d.fu14_criteria.d = CriterionDInput::Observed {
            shadow_outputs_in_verdict: in_verdict,
            untagged_shadow_outputs: untagged,
        };
        assert!(matches!(
            seal_report(bad_d).unwrap().verdict(),
            ReportVerdict::Mismatch { .. }
        ));
    }

    // 多类失败不合并成布尔值，保留全部分类。
    let mut mixed = valid_pass_input();
    mixed.h1 = Some(OracleRunInput::Executed {
        diff_count: 2,
        diff_summary: "face 2 diff".to_string(),
    });
    mixed.h2 = None;
    mixed.fu14_criteria.d = CriterionDInput::MissingCapability {
        capability: "shadow audit log missing".to_string(),
    };
    match seal_report(mixed).unwrap().verdict() {
        ReportVerdict::MultipleFailures {
            unexecuted,
            missing_capability,
            mismatch,
        } => {
            assert!(!unexecuted.is_empty());
            assert!(!missing_capability.is_empty());
            assert!(!mismatch.is_empty());
        }
        other => panic!("expected MultipleFailures, got {other:?}"),
    }
}

#[test]
fn increment_1026_fields_calibration_gates_and_digest_consistency() {
    // 随机模型待标定 -> MissingCapability，且 L1 计数独立留存。
    let mut stochastic = valid_pass_input();
    stochastic.model_execution.model_id = SimulationModelId::StochasticMicroevent {
        revision: "1".to_string(),
    };
    stochastic.model_execution.seed = ReplaySeed::integer(42).unwrap();
    stochastic.version_set.model_ref.model_id = "history-sim/stochastic-microevent/1".to_string();
    stochastic.dual_run_tuple.model_id = "history-sim/stochastic-microevent/1".to_string();
    stochastic.dual_run_tuple.seed = ReplaySeed::integer(42).unwrap();
    stochastic.assumption_counts.stochastic_l1_count = 7;
    let report = seal_report(stochastic).unwrap();
    assert!(matches!(
        report.verdict(),
        ReportVerdict::MissingCapability { .. }
    ));
    assert_eq!(report.body().assumption_counts.stochastic_l1_count, 7);
    assert_eq!(
        report.body().assumption_counts.bar_volume_derived_l0_count,
        0
    );

    // bar_volume_derived 待标定 -> MissingCapability，且 L0 计数独立分列。
    let mut bar_vol = valid_pass_input();
    bar_vol.model_execution.capacity_source = CapacitySource::BarVolumeDerived;
    bar_vol.assumption_counts.bar_volume_derived_l0_count = 5;
    let report = seal_report(bar_vol).unwrap();
    assert!(matches!(
        report.verdict(),
        ReportVerdict::MissingCapability { .. }
    ));
    assert_eq!(
        report.body().assumption_counts.bar_volume_derived_l0_count,
        5
    );
    assert_eq!(report.body().assumption_counts.stochastic_l1_count, 0);

    // 确定性模型不允许整数 seed；随机模型不允许 none seed。
    let mut bad_det_seed = valid_pass_input();
    bad_det_seed.model_execution.seed = ReplaySeed::integer(1).unwrap();
    assert!(matches!(
        seal_report(bad_det_seed),
        Err(At14RejectError::InvalidSeedForModel { .. })
    ));

    let mut bad_stoch_seed = valid_pass_input();
    bad_stoch_seed.model_execution.model_id = SimulationModelId::StochasticMicroevent {
        revision: "1".to_string(),
    };
    bad_stoch_seed.model_execution.seed = ReplaySeed::None;
    assert!(matches!(
        seal_report(bad_stoch_seed),
        Err(At14RejectError::InvalidSeedForModel { .. })
    ));

    // 双跑五元组摘要失配 -> Mismatch（不能假 PASS）。
    let mut bad_digest = valid_pass_input();
    bad_digest.dual_run_tuple.input_profile_hash = digest::sha256_hex(b"tampered");
    assert!(matches!(
        seal_report(bad_digest).unwrap().verdict(),
        ReportVerdict::Mismatch { .. }
    ));

    // EQUS.MINI 自动标「校验源」。
    let mut equs = valid_pass_input();
    equs.input_source = InputSource::DatabentoEqusMiniTickV1;
    let equs_report = seal_report(equs).unwrap();
    assert_eq!(
        equs_report.body().verification_source_label.as_deref(),
        Some("校验源")
    );
}

#[test]
fn identical_input_gives_identical_hash_and_every_field_mutation_changes_hash() {
    let base_a = seal_report(valid_pass_input()).unwrap();
    let base_b = seal_report(valid_pass_input()).unwrap();
    assert_eq!(base_a.content_hash(), base_b.content_hash());
    assert_eq!(base_a.canonical_body_bytes(), base_b.canonical_body_bytes());
    assert_eq!(base_a.render_summary(), base_b.render_summary());

    let expected_hash = digest::sha256_hex(&jcs::canonical_bytes(
        &serde_json::to_value(base_a.body()).unwrap(),
    ));
    assert_eq!(base_a.content_hash(), expected_hash);

    // 篡改落盘 JSON 但不改 content_hash -> verify_sealed_json 拒收。
    let mut tampered: Value = serde_json::from_str(&base_a.to_pretty_json()).unwrap();
    tampered["actual_load"]["bar_count"] = json!(121);
    assert!(matches!(
        verify_sealed_json(&tampered.to_string()),
        Err(At14RejectError::ContentHashMismatch { .. })
    ));

    let mutations: Vec<(&str, Box<dyn FnOnce(&mut At14ReportInput)>)> = vec![
        (
            "manifest_echo",
            Box::new(|i| {
                i.manifest_json["state_dir"] = json!("/tmp/at14-fixture/state-2");
            }),
        ),
        (
            "profile_echo",
            Box::new(|i| {
                i.profile_json["clock"]["known_frontier_cut"] = json!("bar_close_v2");
                recompute_tuple_hashes(i);
            }),
        ),
        (
            "evidence_class",
            Box::new(|i| {
                i.manifest_json = valid_manifest("experiment");
                i.profile_json = valid_history_profile("experiment", "System");
                i.fault_schedule.clear();
                recompute_tuple_hashes(i);
            }),
        ),
        (
            "scheduler",
            Box::new(|i| {
                i.scheduler = "launcher-sched/sequential/2".to_string();
                i.dual_run_tuple.scheduler = i.scheduler.clone();
            }),
        ),
        (
            "build_fingerprint.commit",
            Box::new(|i| i.build_fingerprint.commit = "1111111111111111".to_string()),
        ),
        (
            "build_fingerprint.lockfile_hash",
            Box::new(|i| i.build_fingerprint.lockfile_hash = digest::sha256_hex(b"lock-2")),
        ),
        (
            "build_fingerprint.features",
            Box::new(|i| {
                i.build_fingerprint.features.insert("lav_seal".to_string());
            }),
        ),
        (
            "version_set.rule_versions",
            Box::new(|i| i.version_set.rule_versions[0].version = "v2".to_string()),
        ),
        (
            "version_set.policy_refs",
            Box::new(|i| i.version_set.policy_refs[0].version = "2".to_string()),
        ),
        (
            "version_set.model_ref.revision",
            Box::new(|i| {
                i.version_set.model_ref.revision = "2".to_string();
                i.dual_run_tuple.model_revision = "2".to_string();
            }),
        ),
        (
            "version_set.model_ref.content_hash",
            Box::new(|i| i.version_set.model_ref.content_hash = digest::sha256_hex(b"model-v2")),
        ),
        (
            "capability_manifest_hash",
            Box::new(|i| i.capability_manifest_hash = digest::sha256_hex(b"cap-2")),
        ),
        (
            "model_execution.model_id",
            Box::new(|i| {
                i.model_execution.model_id = SimulationModelId::RecordedVenueReplayV1;
                i.version_set.model_ref.model_id = MODEL_RECORDED_VENUE_REPLAY_V1.to_string();
                i.dual_run_tuple.model_id = MODEL_RECORDED_VENUE_REPLAY_V1.to_string();
            }),
        ),
        (
            "model_execution.seed",
            Box::new(|i| {
                i.model_execution.model_id = SimulationModelId::StochasticMicroevent {
                    revision: "1".to_string(),
                };
                i.model_execution.seed = ReplaySeed::integer(7).unwrap();
                i.version_set.model_ref.model_id =
                    "history-sim/stochastic-microevent/1".to_string();
                i.dual_run_tuple.model_id = "history-sim/stochastic-microevent/1".to_string();
                i.dual_run_tuple.seed = ReplaySeed::integer(7).unwrap();
            }),
        ),
        (
            "model_execution.capacity_source",
            Box::new(|i| i.model_execution.capacity_source = CapacitySource::BarVolumeDerived),
        ),
        (
            "dual_run_tuple.input_events_hash",
            Box::new(|i| i.dual_run_tuple.input_events_hash = digest::sha256_hex(b"events-2")),
        ),
        (
            "dual_run_tuple.policy_version",
            Box::new(|i| i.dual_run_tuple.policy_version = "rd11-funding@2".to_string()),
        ),
        (
            "actual_load.input_range.symbols",
            Box::new(|i| i.actual_load.input_range.symbols.push("MSFT".to_string())),
        ),
        (
            "actual_load.input_range.from",
            Box::new(|i| i.actual_load.input_range.from = "2024-01-03T14:30:00Z".to_string()),
        ),
        (
            "actual_load.input_range.to",
            Box::new(|i| i.actual_load.input_range.to = "2024-01-03T21:00:00Z".to_string()),
        ),
        (
            "actual_load.bar_count",
            Box::new(|i| i.actual_load.bar_count = 121),
        ),
        (
            "actual_load.checkpoint_count",
            Box::new(|i| i.actual_load.checkpoint_count = 119),
        ),
        (
            "fault_schedule",
            Box::new(|i| {
                i.fault_schedule[0].kind = FaultKind::Restart;
                recompute_tuple_hashes(i);
            }),
        ),
        (
            "schedule_trace",
            Box::new(|i| {
                i.schedule_trace[0].detail = "restarted from checkpoint 8".to_string();
                recompute_tuple_hashes(i);
            }),
        ),
        (
            "h1",
            Box::new(|i| {
                i.h1 = Some(OracleRunInput::Executed {
                    diff_count: 0,
                    diff_summary: "zero diff (variant)".to_string(),
                })
            }),
        ),
        (
            "h2",
            Box::new(|i| {
                i.h2 = Some(OracleRunInput::Executed {
                    diff_count: 0,
                    diff_summary: "recovered (variant)".to_string(),
                })
            }),
        ),
        (
            "h3",
            Box::new(|i| {
                i.h3 = Some(OracleRunInput::Executed {
                    diff_count: 0,
                    diff_summary: "seek (variant)".to_string(),
                })
            }),
        ),
        (
            "h4",
            Box::new(|i| {
                i.h4 = Some(OracleRunInput::Executed {
                    diff_count: 0,
                    diff_summary: "asknown (variant)".to_string(),
                })
            }),
        ),
        (
            "six_faces.s_structure_snapshot",
            Box::new(|i| i.six_faces.s_structure_snapshot.row_count += 1),
        ),
        (
            "six_faces.b_chong_ledgers",
            Box::new(|i| i.six_faces.b_chong_ledgers.row_count += 1),
        ),
        (
            "six_faces.e_responsibility",
            Box::new(|i| i.six_faces.e_responsibility.row_count += 1),
        ),
        (
            "six_faces.orders_and_fills",
            Box::new(|i| i.six_faces.orders_and_fills.row_count += 1),
        ),
        (
            "six_faces.physical_positions",
            Box::new(|i| i.six_faces.physical_positions.row_count += 1),
        ),
        (
            "six_faces.external_effect_journal",
            Box::new(|i| i.six_faces.external_effect_journal.row_count += 1),
        ),
        (
            "fu14_gates",
            Box::new(|i| {
                i.fu14_criteria.d = CriterionDInput::Observed {
                    shadow_outputs_in_verdict: 1,
                    untagged_shadow_outputs: 0,
                }
            }),
        ),
        (
            "model_order_unspecified_count",
            Box::new(|i| i.model_order_unspecified_count = 3),
        ),
        (
            "diagnostic_not_production_count",
            Box::new(|i| i.diagnostic_not_production_count = 1),
        ),
        (
            "input_source_unavailable_count",
            Box::new(|i| i.input_source_unavailable_count = 1),
        ),
        (
            "input_source",
            Box::new(|i| i.input_source = InputSource::DatabentoEqusMiniTickV1),
        ),
        (
            "assumption_counts.stochastic_l1_count",
            Box::new(|i| i.assumption_counts.stochastic_l1_count = 1),
        ),
        (
            "assumption_counts.bar_volume_derived_l0_count",
            Box::new(|i| i.assumption_counts.bar_volume_derived_l0_count = 1),
        ),
        (
            "assumption_counts.unconstrained_capacity_l0_count",
            Box::new(|i| i.assumption_counts.unconstrained_capacity_l0_count = 1),
        ),
        (
            "unexecuted",
            Box::new(|i| i.extra_unexecuted.push("pending_heavy_check".to_string())),
        ),
        (
            "bounded_domain_statement",
            Box::new(|i| {
                i.bounded_domain_statement = "仅证有界受测域；附加测试范围说明。".to_string()
            }),
        ),
        (
            "ci_run_id",
            Box::new(|i| i.ci_run_id = Some("99999999".to_string())),
        ),
        (
            "review_binding",
            Box::new(|i| i.review_binding = Some("cafebabe0123456789".to_string())),
        ),
    ];

    for (field_name, mutate) in mutations {
        let mut input = valid_pass_input();
        mutate(&mut input);
        let mutated = seal_report(input)
            .unwrap_or_else(|e| panic!("mutation `{field_name}` unexpectedly failed seal: {e}"));
        assert_ne!(
            mutated.content_hash(),
            base_a.content_hash(),
            "mutating `{field_name}` must change content_hash"
        );
    }
}

#[test]
fn summary_md_verdict_matches_report_and_renderer_signature_excludes_raw_inputs() {
    // 编译期签名锁：render_summary 只接受只读投影 SummaryView，拿不到 At14ReportInput / Fu14CriteriaInput / OracleRunInput。
    let renderer: fn(&SummaryView<'_>) -> String = render_summary;

    let mut cases: Vec<(&str, At14ReportInput)> = Vec::new();
    cases.push(("PASS", valid_pass_input()));

    let mut unexec = valid_pass_input();
    unexec.h3 = None;
    cases.push(("UNEXECUTED", unexec));

    let mut missing_cap = valid_pass_input();
    missing_cap.model_execution.capacity_source = CapacitySource::BarVolumeDerived;
    cases.push(("MISSING_CAPABILITY", missing_cap));

    let mut mismatch = valid_pass_input();
    mismatch.six_faces.e_responsibility.diff_count = 3;
    cases.push(("MISMATCH", mismatch));

    let mut multi = valid_pass_input();
    multi.h1 = None;
    multi.input_source_unavailable_count = 1;
    multi.fu14_criteria.c = CriterionCInput::Observed {
        out_of_domain_requests: 1,
        model_order_unspecified_terminals: 0,
        legacy_arm_calls: 1,
    };
    cases.push(("MULTIPLE_FAILURES", multi));

    for (expected_label, input) in cases {
        let sealed = seal_report(input).unwrap();
        assert_eq!(sealed.verdict().label(), expected_label);
        let md = renderer(&sealed.summary_view());
        assert!(
            md.contains(&format!("- verdict: `{expected_label}`")),
            "summary.md must echo verdict `{expected_label}`, got:\n{md}"
        );
        assert!(md.contains(sealed.content_hash()));
        assert!(md.contains(&sealed.body().bounded_domain_statement));
        assert_eq!(md, sealed.render_summary());
    }
}
