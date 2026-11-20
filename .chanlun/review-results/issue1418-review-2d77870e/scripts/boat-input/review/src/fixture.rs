use std::collections::BTreeSet;

use serde_json::{json, Value};
use newchan_rust::at14_report::*;
use newchan_rust::lav_seal::{digest,jcs};
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

pub(super) fn valid_pass_input() -> At14ReportInput {
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
