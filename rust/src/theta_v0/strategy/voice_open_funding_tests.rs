use super::*;
use crate::theta_v0::strategy::{ledger::TStage, voice::voice_side};

const AVAILABLE: VoiceOpenFundingPolicy = VoiceOpenFundingPolicy {
    reversal_principal_exposure: ReversalPrincipalExposure::ProfitOnly,
    voice_open_shortfall: VoiceOpenShortfall::OpenAvailable,
};
const TOPUP: VoiceOpenFundingPolicy = VoiceOpenFundingPolicy {
    voice_open_shortfall: VoiceOpenShortfall::TopupFromWithdrawn,
    ..AVAILABLE
};
const FULL: VoiceOpenFundingPolicy = VoiceOpenFundingPolicy {
    reversal_principal_exposure: ReversalPrincipalExposure::ChongFull,
    ..AVAILABLE
};
const FULL_TOPUP: VoiceOpenFundingPolicy = VoiceOpenFundingPolicy {
    voice_open_shortfall: VoiceOpenShortfall::TopupFromWithdrawn,
    ..FULL
};

fn new_ledger() -> VoiceOpenLedger {
    VoiceOpenLedger {
        tw: TwState {
            free: 120,
            notional_in: 100,
            cum_net_cash: 13,
            hwm_gain: 9,
            ..TwState::initial()
        },
        principal_total: 100,
        p_recovered: 0,
        k_cost_basis: -4,
        cum_net_realized_profit: 100,
        phase_events: vec![],
    }
}

fn apply_phase(ledger: &mut VoiceOpenLedger, event: TwEvent, known_at: i64) {
    ledger.tw = tw_step_legal(&ledger.tw, event).expect("合法的阶段转换");
    if let TwEvent::RecoverCapital(amount) = event {
        ledger.p_recovered += amount;
    }
    ledger.phase_events.push(PhaseEvent { event, known_at });
}

fn capital_recovered_ledger() -> VoiceOpenLedger {
    let mut ledger = new_ledger();
    apply_phase(&mut ledger, TwEvent::RecoverCapital(100), 10);
    ledger
}

fn recovered_ledger() -> VoiceOpenLedger {
    let mut ledger = capital_recovered_ledger();
    apply_phase(&mut ledger, TwEvent::EnterEarning, 20);
    ledger
}

#[test]
fn signed_policy_requires_both_exact_values() {
    for (exposure, shortfall, expected) in [
        ("profit_only", "open_available", AVAILABLE),
        ("profit_only", "topup_from_withdrawn", TOPUP),
        ("chong_full", "open_available", FULL),
        ("chong_full", "topup_from_withdrawn", FULL_TOPUP),
    ] {
        assert_eq!(
            VoiceOpenFundingPolicy::parse(true, Some(exposure), Some(shortfall)),
            Ok(expected)
        );
    }
    for (signed, exposure, shortfall) in [
        (false, Some("chong_full"), Some("topup_from_withdrawn")),
        (false, Some("profit_only"), Some("open_available")),
        (true, None, None),
        (true, None, Some("open_available")),
        (true, Some("profit_only"), None),
        (true, Some(""), Some("open_available")),
        (true, Some("profit_only"), Some("  ")),
    ] {
        assert_eq!(
            VoiceOpenFundingPolicy::parse(signed, exposure, shortfall),
            Err(VoiceOpenFundingError::AwaitingPolicy),
        );
    }
    for (exposure, shortfall, field) in [
        (
            "fallback",
            "open_available",
            PolicyField::ReversalPrincipalExposure,
        ),
        (
            " profit_only",
            "open_available",
            PolicyField::ReversalPrincipalExposure,
        ),
        ("profit_only", "automatic", PolicyField::VoiceOpenShortfall),
    ] {
        assert_eq!(
            VoiceOpenFundingPolicy::parse(true, Some(exposure), Some(shortfall)),
            Err(VoiceOpenFundingError::InvalidPolicyValue(field)),
        );
    }
}

#[test]
fn profit_only_available_does_not_reexpose() {
    let before = recovered_ledger();
    let policy = VoiceOpenFundingPolicy::parse(true, Some("profit_only"), Some("open_available"))
        .expect("已签的政策有两个有效值");
    for (q, quantity) in [(60, 20), (10, 10), (20, 20)] {
        let result = evaluate_voice_open_funding(&before, q, policy, 30).expect("有可用资金");
        assert_eq!(result.reexpose_event, None);
        assert_eq!(result.reexpose_amount, 0);
        assert_eq!(result.opening_quantity, quantity);
        assert_eq!(result.ledger, before);
    }
}

#[test]
fn topup_reexposes_exact_shortfall_capped_by_withdrawn() {
    let ledger = recovered_ledger();
    for (free, withdrawn, q, amount, quantity) in [
        (20, 100, 60, 40, 60),
        (5, 12, 60, 12, 17),
        (95, 100, 60, 0, 60),
        (60, 100, 60, 0, 60),
        (5, 0, 60, 0, 5),
        (-4, 25, 10, 14, 10),
    ] {
        let mut before = ledger.clone();
        before.tw.free = free;
        before.tw.withdrawn = withdrawn;
        before.p_recovered = withdrawn;
        let result = evaluate_voice_open_funding(&before, q, TOPUP, 30).expect("有可开局数量");
        assert_eq!(
            result.reexpose_amount, amount,
            "topup amount: free={free}, withdrawn={withdrawn}, Q={q}"
        );
        assert_eq!(result.opening_quantity, quantity);
        assert_eq!(
            result.reexpose_event,
            (amount > 0).then_some(TwEvent::ReexposePrincipal(amount))
        );
        assert_eq!(result.ledger.tw.free, free + amount);
        assert_eq!(result.ledger.tw.withdrawn, withdrawn - amount);
        assert_eq!(result.ledger.p_recovered, withdrawn - amount);
    }
}

#[test]
fn chong_full_shortfall_values_are_identical() {
    let mut starting = recovered_ledger();
    starting.principal_total = 120;
    for free in [-15, 0, 8, 55] {
        for withdrawn in [0, 4, 40, 120] {
            for q in [0, 3, 20, 80, 160] {
                let mut before = starting.clone();
                before.tw.free = free;
                before.tw.withdrawn = withdrawn;
                before.p_recovered = withdrawn;
                let a = evaluate_voice_open_funding(&before, q, FULL, 30);
                let b = evaluate_voice_open_funding(&before, q, FULL_TOPUP, 30);
                assert_eq!(a, b, "free={free}, withdrawn={withdrawn}, Q={q}");
                if q <= 0 || free + withdrawn <= 0 {
                    assert_eq!(a, Err(VoiceOpenFundingError::QuantityZero));
                } else {
                    let result = a.expect("全额回流后有可开局数量");
                    assert_eq!(result.reexpose_amount, withdrawn);
                    assert_eq!(result.ledger.tw.withdrawn, 0);
                    assert_eq!(result.ledger.p_recovered, 0);
                    assert_eq!(result.opening_quantity, q.min(free + withdrawn));
                }
            }
        }
    }
}

/// 模拟 AsKnown 消费方：从初态重放选定的事件前缀，再编码 TW 字段和事件序列。
fn replay_bytes(prefix: &[PhaseEvent]) -> (TwState, Vec<u8>) {
    let (tw, known) =
        prefix
            .iter()
            .fold((new_ledger().tw, Vec::new()), |(tw, mut known), record| {
                known.push((record.known_at, format!("{:?}", record.event)));
                (
                    tw_step_legal(&tw, record.event).expect("合法的历史事件"),
                    known,
                )
            });
    let bytes = serde_json::to_vec(&(
        tw.free,
        tw.holding,
        tw.withdrawn,
        tw.notional_in,
        tw.stage.rank(),
        tw.open_legacy_legs,
        tw.cum_net_cash,
        tw.hwm_gain,
        known,
    ))
    .expect("固定整数与事件记录可编码");
    (tw, bytes)
}

fn as_known_bytes(events: &[PhaseEvent], cutoff: i64) -> Vec<u8> {
    let prefix_len = events.partition_point(|record| record.known_at <= cutoff);
    replay_bytes(&events[..prefix_len]).1
}

#[test]
fn reexposure_appends_once_without_rewriting_as_known() {
    let before = recovered_ledger();
    let starting = before.clone();
    let snapshots = [10, 20, 29].map(|cutoff| as_known_bytes(&before.phase_events, cutoff));
    let result = evaluate_voice_open_funding(&before, 60, TOPUP, 30).expect("可补到 Q");
    assert_eq!(before, starting);
    let after = result.ledger;
    assert_eq!(
        &after.phase_events[..before.phase_events.len()],
        before.phase_events
    );
    assert_eq!(
        &after.phase_events[before.phase_events.len()..],
        &[PhaseEvent {
            event: TwEvent::ReexposePrincipal(40),
            known_at: 30,
        }]
    );
    assert_eq!(
        snapshots,
        [10, 20, 29].map(|cutoff| as_known_bytes(&after.phase_events, cutoff))
    );
    assert_ne!(snapshots[2], as_known_bytes(&after.phase_events, 30));
    assert_eq!(after.principal_total, before.principal_total);
    assert_eq!(after.k_cost_basis, before.k_cost_basis);
    assert_eq!(
        after.cum_net_realized_profit,
        before.cum_net_realized_profit
    );
    assert_eq!(
        after.tw,
        TwState {
            free: 60,
            withdrawn: 60,
            ..before.tw
        }
    );
    assert_eq!(after.tw.tw(), before.tw.tw());
}

#[test]
fn same_known_at_keeps_the_frozen_prefix_not_the_bare_cutoff() {
    let before = recovered_ledger();
    let prefix_len = before.phase_events.len();
    let known_at = 20;
    assert_eq!(before.phase_events[prefix_len - 1].known_at, known_at);
    let frozen = as_known_bytes(&before.phase_events, known_at);
    let after = evaluate_voice_open_funding(&before, 60, TOPUP, known_at)
        .expect("同刻允许顺序追加")
        .ledger;

    assert_eq!(after.phase_events.len(), prefix_len + 1);
    assert_eq!(&after.phase_events[..prefix_len], before.phase_events);
    assert_eq!(
        after.phase_events[prefix_len],
        PhaseEvent {
            event: TwEvent::ReexposePrincipal(40),
            known_at,
        }
    );
    let (replayed, bytes) = replay_bytes(&after.phase_events[..prefix_len]);
    assert_eq!((replayed.free, replayed.withdrawn), (20, 100));
    assert_eq!(bytes, frozen);
    assert_ne!(as_known_bytes(&after.phase_events, known_at), frozen);
    assert_eq!((after.tw.free, after.tw.withdrawn), (60, 60));
}

#[test]
fn every_policy_rejects_future_or_disordered_history_even_when_q_is_zero() {
    let before = recovered_ledger();
    let mut disordered = before.clone();
    disordered.phase_events.swap(0, 1);
    for policy in [AVAILABLE, TOPUP, FULL, FULL_TOPUP] {
        for q in [60, 0] {
            for (ledger, known_at) in [(&before, 9), (&before, 19), (&disordered, 30)] {
                assert_eq!(
                    evaluate_voice_open_funding(ledger, q, policy, known_at),
                    Err(VoiceOpenFundingError::NonMonotonicKnownAt),
                    "{policy:?} Q={q} @ {known_at}",
                );
            }
        }
    }
}

#[test]
fn long_recovery_can_be_lost_and_regained_without_latch_regression() {
    let mut before = new_ledger();
    assert_eq!(before.tw.stage, TStage::CostReduction);
    assert_eq!(before.growth_eligible(VoiceSide::Long), Some(false));
    apply_phase(&mut before, TwEvent::RecoverCapital(100), 10);

    for stage in [TStage::CapitalRecovered, TStage::EarningShares] {
        if stage == TStage::EarningShares {
            apply_phase(&mut before, TwEvent::EnterEarning, 20);
        }
        assert_eq!(before.tw.stage, stage);
        assert_eq!(before.growth_eligible(VoiceSide::Long), Some(true));
        assert_eq!(before.tw.l_wc(), 0);

        let mut after = evaluate_voice_open_funding(&before, 60, TOPUP, 30)
            .expect("可补到 Q")
            .ledger;
        assert_eq!(after.tw.stage, stage);
        assert_eq!(after.p_recovered, 60);
        assert_eq!(after.growth_eligible(VoiceSide::Long), Some(false));
        assert_eq!(after.tw.l_wc(), 40);

        // 上游再次退足本金后，资格恢复；两条轨迹各自保持阶段。
        apply_phase(&mut after, TwEvent::RecoverCapital(40), 40);
        assert_eq!(after.tw.stage, stage);
        assert_eq!(after.p_recovered, after.principal_total);
        assert_eq!(after.growth_eligible(VoiceSide::Long), Some(true));
        assert_eq!(after.tw.l_wc(), 0);
    }
}

#[test]
fn zero_quantity_does_not_return_a_transfer() {
    let mut before = recovered_ledger();
    before.tw.free = i64::MAX; // 非正 Q 不会尝试回流（否则可用资金会越界）。
    assert_eq!(
        evaluate_voice_open_funding(&before, -1, FULL, 30),
        Err(VoiceOpenFundingError::QuantityZero),
    );
    assert_eq!(
        evaluate_voice_open_funding(&before, 0, FULL, 30),
        Err(VoiceOpenFundingError::QuantityZero)
    );
    before.tw.free = -100;
    for policy in [AVAILABLE, TOPUP, FULL, FULL_TOPUP] {
        assert_eq!(
            evaluate_voice_open_funding(&before, 20, policy, 30),
            Err(VoiceOpenFundingError::QuantityZero)
        );
    }
    assert_eq!(before.p_recovered, 100);
    assert_eq!(before.tw.withdrawn, 100);
    assert_eq!(before.phase_events.len(), 2);
}

fn reexposure_boundary_ledger(free: i64, p_recovered: i64) -> VoiceOpenLedger {
    let mut ledger = recovered_ledger();
    ledger.tw.free = free;
    ledger.tw.withdrawn = 10;
    ledger.p_recovered = p_recovered;
    ledger
}

#[test]
fn zero_quantity_precedes_insufficient_recovered_principal() {
    let before = reexposure_boundary_ledger(-10, 9);
    let snapshot = before.clone();
    for policy in [AVAILABLE, TOPUP, FULL, FULL_TOPUP] {
        assert_eq!(
            evaluate_voice_open_funding(&before, 60, policy, 30),
            Err(VoiceOpenFundingError::QuantityZero),
            "{policy:?}",
        );
        assert_eq!(before, snapshot);
    }
}

#[test]
fn positive_quantity_requires_full_recovered_principal() {
    let before = reexposure_boundary_ledger(-9, 9);
    let snapshot = before.clone();
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, AVAILABLE, 30),
        Err(VoiceOpenFundingError::QuantityZero),
    );
    assert_eq!(before, snapshot);
    for policy in [TOPUP, FULL, FULL_TOPUP] {
        assert_eq!(
            evaluate_voice_open_funding(&before, 60, policy, 30),
            Err(VoiceOpenFundingError::InsufficientRecoveredPrincipal {
                requested: 10,
                available: 9,
            }),
            "{policy:?}",
        );
        assert_eq!(before, snapshot);
    }
}

#[test]
fn positive_quantity_with_full_recovered_principal_appends_one_reexposure() {
    let before = reexposure_boundary_ledger(-9, 10);
    let snapshot = before.clone();
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, AVAILABLE, 30),
        Err(VoiceOpenFundingError::QuantityZero),
    );
    assert_eq!(before, snapshot);
    let event = TwEvent::ReexposePrincipal(10);
    let appended = [PhaseEvent {
        event,
        known_at: 30,
    }];
    for policy in [TOPUP, FULL, FULL_TOPUP] {
        let after = evaluate_voice_open_funding(&before, 60, policy, 30).expect("本金足额");
        assert_eq!(after.opening_quantity, 1, "{policy:?}");
        assert_eq!(after.reexpose_amount, 10);
        assert_eq!(after.reexpose_event, Some(event));
        assert_eq!(after.ledger.tw.free, 1);
        assert_eq!(after.ledger.tw.withdrawn, 0);
        assert_eq!(after.ledger.p_recovered, 0);
        assert_eq!(
            after
                .ledger
                .phase_events
                .split_at(before.phase_events.len()),
            (before.phase_events.as_slice(), appended.as_slice()),
        );
        assert_eq!(before, snapshot);
    }
}

#[test]
fn updates_each_recovery_balance_by_the_same_amount() {
    let mut before = recovered_ledger();
    before.principal_total = 200;
    before.p_recovered = 140;
    let after = evaluate_voice_open_funding(&before, 60, TOPUP, 30)
        .expect("可补到 Q")
        .ledger;
    assert_eq!(after.tw.withdrawn, 60);
    assert_eq!(after.p_recovered, 100);
    assert!(!after.growth_eligible_long());
}

#[test]
fn insufficient_recovered_principal_rejects_the_whole_requested_transfer() {
    let mut before = recovered_ledger();
    before.p_recovered = 10;
    let snapshot = before.clone();

    for (policy, requested) in [(TOPUP, 40), (FULL, 100), (FULL_TOPUP, 100)] {
        assert_eq!(
            evaluate_voice_open_funding(&before, 60, policy, 30),
            Err(VoiceOpenFundingError::InsufficientRecoveredPrincipal {
                requested,
                available: 10,
            }),
        );
        assert_eq!(before, snapshot);
    }

    let result = evaluate_voice_open_funding(&before, 60, AVAILABLE, 30).expect("无需回流凭证");
    assert_eq!(result.opening_quantity, 20);
    assert_eq!(result.reexpose_event, None);
    assert_eq!(result.ledger, snapshot);
}

#[test]
fn invalid_principal_balances_never_project_or_qualify() {
    for (principal, recovered, withdrawn) in [
        (100, 100, -1),
        (-1, 0, 100),
        (0, 0, 100),
        (100, -1, 100),
        (100, 101, 100),
    ] {
        let mut before = recovered_ledger();
        before.principal_total = principal;
        before.p_recovered = recovered;
        before.tw.withdrawn = withdrawn;
        let snapshot = before.clone();

        assert_eq!(before.growth_eligible(VoiceSide::Long), None);
        assert_eq!(before.growth_eligible(VoiceSide::Short), None);
        assert!(!before.growth_eligible_long());
        assert!(!before.growth_eligible_short());
        for policy in [AVAILABLE, TOPUP, FULL, FULL_TOPUP] {
            for q in [60, 0] {
                assert_eq!(
                    evaluate_voice_open_funding(&before, q, policy, 30),
                    Err(VoiceOpenFundingError::InvalidLedgerState),
                    "P={principal}, P_recovered={recovered}, withdrawn={withdrawn}, {policy:?} Q={q}",
                );
                assert_eq!(before, snapshot);
            }
        }
    }
}

#[test]
fn projection_does_not_wrap_i64() {
    let mut before = recovered_ledger();
    before.tw.free = i64::MAX;
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, FULL, 30),
        Err(VoiceOpenFundingError::AmountOutOfRange)
    );
    before.tw.free = -1;
    before.tw.withdrawn = i64::MAX;
    before.p_recovered = i64::MAX;
    before.principal_total = i64::MAX;
    let result =
        evaluate_voice_open_funding(&before, i64::MAX, TOPUP, 30).expect("差额超界后取已退余额");
    assert_eq!(result.reexpose_amount, i64::MAX);
    assert_eq!(result.opening_quantity, i64::MAX - 1);
}

#[test]
fn growth_eligible_same_inputs_per_side_on_l0_l1_l2_after_direction_switch() {
    use VoiceSide::{Long, Short};
    // 独立期望表：塔顶是 L2；每行从 L0 到 L2，不从实现反推期望方向。
    let routing = [(Long, [Long, Short, Long]), (Short, [Short, Long, Short])];
    for (basis, profit, long, short) in [
        (0, 99, true, false),
        (1, 100, false, true),
        (-1, 100, true, true),
    ] {
        let mut ledger = recovered_ledger();
        ledger.k_cost_basis = basis;
        ledger.cum_net_realized_profit = profit;
        let after = evaluate_voice_open_funding(&ledger, 60, FULL, 30)
            .expect("可开局")
            .ledger;
        assert_eq!(ledger.growth_eligible(VoiceSide::Flat), None);
        for (root, expected_sides) in routing {
            for (level, expected_side) in (0..=2).zip(expected_sides) {
                let actual_side = voice_side(root, 2 - level);
                assert_eq!(actual_side, expected_side, "方向路由：根 {root:?} L{level}");
                let (before_expected, after_expected) = if expected_side == Long {
                    (long, false)
                } else {
                    (short, short)
                };
                assert_eq!(ledger.growth_eligible(actual_side), Some(before_expected));
                assert_eq!(after.growth_eligible(actual_side), Some(after_expected));
            }
        }
    }
}

#[test]
fn short_growth_threshold_does_not_read_the_stage_or_long_inputs() {
    let mut ledger = new_ledger();
    ledger.k_cost_basis = 1;
    assert_eq!(ledger.tw.stage, TStage::CostReduction);
    assert_eq!(ledger.p_recovered, 0);
    // ADR 0043 裁定二仅验数值阈值；业务事件的 latch 和负债登记由切片 2 验证。
    for (profit, expected) in [(99, false), (100, true), (101, true)] {
        ledger.cum_net_realized_profit = profit;
        assert_eq!(ledger.growth_eligible(VoiceSide::Short), Some(expected));
        assert_eq!(ledger.growth_eligible(VoiceSide::Long), Some(false));
    }
}
