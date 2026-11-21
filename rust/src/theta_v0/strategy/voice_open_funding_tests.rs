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

fn recovered_ledger() -> VoiceOpenLedger {
    let mut ledger = new_ledger();
    for (known_at, event) in [
        (10, TwEvent::RecoverCapital(100)),
        (20, TwEvent::EnterEarning),
    ] {
        assert!(event.is_legal_from(&ledger.tw));
        ledger.tw = tw_step(&ledger.tw, event);
        ledger.phase_events.push(PhaseEvent { event, known_at });
    }
    ledger.p_recovered = 100;
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
    let starting = recovered_ledger();
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

/// 模拟只读 AsKnown 消费方：在知识截止点用原始账本与可知阶段事件重放，并编码结果。
fn as_known_bytes(events: &[PhaseEvent], cutoff: i64) -> Vec<u8> {
    let ledger = new_ledger();
    let (tw, known) = events
        .iter()
        .take_while(|record| record.known_at <= cutoff)
        .fold((ledger.tw, Vec::new()), |(tw, mut known), record| {
            known.push((record.known_at, format!("{:?}", record.event)));
            (tw_step(&tw, record.event), known)
        });
    serde_json::to_vec(&(
        tw.free,
        tw.withdrawn,
        tw.stage.rank(),
        tw.cum_net_cash,
        known,
    ))
    .expect("固定整数与事件记录可编码")
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
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, TOPUP, 19),
        Err(VoiceOpenFundingError::KnownAtOutOfOrder),
    );
}

#[test]
fn long_recovery_can_be_lost_and_regained_without_latch_regression() {
    let before = recovered_ledger();
    assert!(before.growth_eligible_long());
    assert_eq!(before.tw.l_wc(), 0);
    let mut after = evaluate_voice_open_funding(&before, 60, TOPUP, 30)
        .expect("可补到 Q")
        .ledger;
    assert_eq!(after.p_recovered, 60);
    assert!(!after.growth_eligible_long());
    assert_eq!(after.tw.l_wc(), 40);
    assert_eq!(after.tw.stage, TStage::EarningShares);
    assert!(after.tw.stage.rank() >= before.tw.stage.rank());

    // RecoverCapital 由账本上游记入，两种读数都恢复，不改 K、P 或利润。
    let recover = TwEvent::RecoverCapital(40);
    assert!(recover.is_legal_from(&after.tw));
    after.tw = tw_step(&after.tw, recover);
    after.p_recovered += 40;
    assert_eq!(after.p_recovered, after.principal_total);
    assert!(after.growth_eligible_long());
    assert_eq!(after.tw.l_wc(), 0);
    assert_eq!(after.tw.stage, TStage::EarningShares);
}

#[test]
fn zero_quantity_does_not_return_a_transfer() {
    let mut before = recovered_ledger();
    before.tw.free = i64::MAX; // 非正 Q 不会尝试回流（否则可用资金会越界）。
    assert_eq!(
        evaluate_voice_open_funding(&before, -1, FULL, 19),
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

#[test]
fn updates_each_recovery_balance_by_the_same_amount() {
    let mut before = recovered_ledger();
    before.p_recovered = 140;
    let after = evaluate_voice_open_funding(&before, 60, TOPUP, 30)
        .expect("可补到 Q")
        .ledger;
    assert_eq!(after.tw.withdrawn, 60);
    assert_eq!(after.p_recovered, 100);
    assert!(after.growth_eligible_long());
}

#[test]
fn projection_does_not_wrap_i64() {
    let mut before = recovered_ledger();
    before.tw.free = i64::MAX;
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, FULL, 30),
        Err(VoiceOpenFundingError::AmountOutOfRange)
    );
    before.tw.free = 0;
    before.p_recovered = i64::MIN;
    assert_eq!(
        evaluate_voice_open_funding(&before, 60, FULL, 30),
        Err(VoiceOpenFundingError::AmountOutOfRange)
    );

    before.tw.free = -1;
    before.tw.withdrawn = i64::MAX;
    before.p_recovered = i64::MAX;
    let result =
        evaluate_voice_open_funding(&before, i64::MAX, TOPUP, 30).expect("差额超界后取已退余额");
    assert_eq!(result.reexpose_amount, i64::MAX);
    assert_eq!(result.opening_quantity, i64::MAX - 1);
}

#[test]
fn growth_eligible_same_inputs_per_side_on_l0_l1_l2_after_direction_switch() {
    for (basis, profit, long, short) in [
        (0, 99, true, false),
        (1, 100, false, true),
        (-1, 100, true, true),
    ] {
        for stage in [TStage::CapitalRecovered, TStage::EarningShares] {
            let mut before = recovered_ledger();
            if stage == TStage::CapitalRecovered {
                before.tw = tw_step(&new_ledger().tw, TwEvent::RecoverCapital(100));
                assert_eq!(
                    before.phase_events.pop().map(|record| record.event),
                    Some(TwEvent::EnterEarning)
                );
            }
            before.k_cost_basis = basis;
            before.cum_net_realized_profit = profit;

            let after = evaluate_voice_open_funding(&before, 60, FULL, 30)
                .expect("可开局")
                .ledger;
            assert_eq!(after.tw.stage, stage);
            assert_eq!(before.growth_eligible(VoiceSide::Flat), None);
            assert_eq!(
                after.growth_eligible_short(),
                before.growth_eligible_short()
            );
            assert!(
                !after.growth_eligible_short()
                    || after.tw.stage.rank() >= TStage::CapitalRecovered.rank()
            );

            // 塔顶是 L2；两种根方向都走一遍 L2→L1→L0，避免把方向与级别绑死。
            for level in 0..=2 {
                for root in [VoiceSide::Long, VoiceSide::Short] {
                    let side = voice_side(root, 2 - level);
                    for (state, want_long) in [(&before, long), (&after, false)] {
                        let expected = if side == VoiceSide::Long {
                            want_long
                        } else {
                            short
                        };
                        assert_eq!(
                            state.growth_eligible(side),
                            Some(expected),
                            "L{level} {side:?}"
                        );
                        assert_eq!(
                            state.growth_eligible(side.flip()),
                            Some(if side == VoiceSide::Short {
                                want_long
                            } else {
                                short
                            }),
                            "L{level} {side:?} 换向"
                        );
                    }
                }
            }
        }
    }
}
