//! ADR 0043 / #1651：回到零仓后开声部的资金求值。#1421 接线时由调用者提供
//! 已验签政策、同量纲的账本和固定 Q；本模块不读记录、不执行订单、不改写历史。

use super::ledger::{tw_step_legal, TwEvent, TwState, TwTransitionError};
use super::voice::VoiceSide;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReversalPrincipalExposure {
    ProfitOnly,
    ChongFull,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceOpenShortfall {
    OpenAvailable,
    TopupFromWithdrawn,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct VoiceOpenFundingPolicy {
    pub reversal_principal_exposure: ReversalPrincipalExposure,
    pub voice_open_shortfall: VoiceOpenShortfall,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PolicyField {
    ReversalPrincipalExposure,
    VoiceOpenShortfall,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VoiceOpenFundingError {
    AwaitingPolicy,
    InvalidPolicyValue(PolicyField),
    InvalidLedgerState,
    NonMonotonicKnownAt,
    QuantityZero,
    IllegalReexposure,
    InsufficientRecoveredPrincipal { requested: i64, available: i64 },
    AmountOutOfRange,
}

impl VoiceOpenFundingPolicy {
    /// 读取 #1590/voice-open-funding/v1 的两个值。签署与有效期由记录读取方核实；
    /// 未找到有效签署时传入 `signed = false`。只有记录里写出的值能够生效。
    pub fn parse(
        signed: bool,
        reversal_principal_exposure: Option<&str>,
        voice_open_shortfall: Option<&str>,
    ) -> Result<Self, VoiceOpenFundingError> {
        let (Some(exposure), Some(shortfall)) = (reversal_principal_exposure, voice_open_shortfall)
        else {
            return Err(VoiceOpenFundingError::AwaitingPolicy);
        };
        if !signed || exposure.trim().is_empty() || shortfall.trim().is_empty() {
            return Err(VoiceOpenFundingError::AwaitingPolicy);
        }

        let reversal_principal_exposure = match exposure {
            "profit_only" => ReversalPrincipalExposure::ProfitOnly,
            "chong_full" => ReversalPrincipalExposure::ChongFull,
            _ => {
                return Err(VoiceOpenFundingError::InvalidPolicyValue(
                    PolicyField::ReversalPrincipalExposure,
                ));
            }
        };
        let voice_open_shortfall = match shortfall {
            "open_available" => VoiceOpenShortfall::OpenAvailable,
            "topup_from_withdrawn" => VoiceOpenShortfall::TopupFromWithdrawn,
            _ => {
                return Err(VoiceOpenFundingError::InvalidPolicyValue(
                    PolicyField::VoiceOpenShortfall,
                ));
            }
        };
        Ok(Self {
            reversal_principal_exposure,
            voice_open_shortfall,
        })
    }

    fn reexpose_amount(self, tw: &TwState, fixed_q: i64) -> i64 {
        let withdrawn = tw.withdrawn;
        match (self.reversal_principal_exposure, self.voice_open_shortfall) {
            (ReversalPrincipalExposure::ChongFull, _) => withdrawn,
            (ReversalPrincipalExposure::ProfitOnly, VoiceOpenShortfall::TopupFromWithdrawn) => {
                // 即使差额超出 i64，随后取 min(withdrawn) 也会得到同一个精确值。
                fixed_q.saturating_sub(tw.free).clamp(0, withdrawn)
            }
            (ReversalPrincipalExposure::ProfitOnly, VoiceOpenShortfall::OpenAvailable) => 0,
        }
    }
}

/// 只追加的阶段记录；`known_at` 是求值点的知识时间，沿用上游知识时钟的单位。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PhaseEvent {
    pub event: TwEvent,
    pub known_at: i64,
}

/// 同一重在开局求值点的账本。方向不是重的字段；切换声部不能另开成本或利润账。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceOpenLedger {
    pub tw: TwState,
    pub principal_total: i64,
    pub p_recovered: i64,
    pub k_cost_basis: i64,
    pub cum_net_realized_profit: i64,
    /// 按 `known_at` 非递减，同刻按追加顺序。已发布快照须冻结事件前缀长度：
    /// 新事件时间更晚时，裸时间截止也能固定旧快照；同刻追加时，只有旧前缀能固定旧快照。
    pub phase_events: Vec<PhaseEvent>,
}

impl VoiceOpenLedger {
    fn has_valid_principal_balances(&self) -> bool {
        self.principal_total > 0
            && self.tw.withdrawn >= 0
            && (0..=self.principal_total).contains(&self.p_recovered)
    }

    pub fn growth_eligible_long(&self) -> bool {
        self.growth_eligible(VoiceSide::Long) == Some(true)
    }

    pub fn growth_eligible_short(&self) -> bool {
        self.growth_eligible(VoiceSide::Short) == Some(true)
    }

    /// 按在世或拟开方向取扩量谓词。无方向或本金余额无效时返回 `None`。
    /// 空头只按 ADR 0043 裁定二比较累计费后已实现利润与本金。阶段由业务事件推进，
    /// 空头负债按 ADR 0031 登记；两项由 `economic_session`（`tb03c_book` / 切片 2）负责。
    pub fn growth_eligible(&self, side: VoiceSide) -> Option<bool> {
        if !self.has_valid_principal_balances() {
            return None;
        }
        match side {
            VoiceSide::Long => {
                Some(self.k_cost_basis <= 0 && self.p_recovered >= self.principal_total)
            }
            VoiceSide::Short => Some(self.cum_net_realized_profit >= self.principal_total),
            VoiceSide::Flat => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceOpenFunding {
    pub opening_quantity: i64,
    pub reexpose_event: Option<TwEvent>,
    pub reexpose_amount: i64,
    pub ledger: VoiceOpenLedger,
}

/// 返回开局量与待提交的新账本。零开局量返回 `QuantityZero`，不交付回流供提交。
/// 所有政策先拒绝无效余额、失序历史或早于账本末事件的求值点。同刻可追加，已发布的
/// AsKnown 快照由冻结的事件前缀重放。调用方仍需在同一开局点处理场所粒度与订单。
pub fn evaluate_voice_open_funding(
    ledger: &VoiceOpenLedger,
    fixed_q: i64,
    policy: VoiceOpenFundingPolicy,
    known_at: i64,
) -> Result<VoiceOpenFunding, VoiceOpenFundingError> {
    if !ledger.has_valid_principal_balances() {
        return Err(VoiceOpenFundingError::InvalidLedgerState);
    }
    if ledger
        .phase_events
        .windows(2)
        .any(|pair| pair[0].known_at > pair[1].known_at)
        || ledger
            .phase_events
            .last()
            .is_some_and(|last| known_at < last.known_at)
    {
        return Err(VoiceOpenFundingError::NonMonotonicKnownAt);
    }
    if fixed_q <= 0 {
        return Err(VoiceOpenFundingError::QuantityZero);
    }

    let reexpose_amount = policy.reexpose_amount(&ledger.tw, fixed_q);
    let (tw, p_recovered, reexpose_event) = if reexpose_amount == 0 {
        (ledger.tw, ledger.p_recovered, None)
    } else {
        let event = TwEvent::ReexposePrincipal(reexpose_amount);
        if reexpose_amount > ledger.p_recovered {
            return Err(VoiceOpenFundingError::InsufficientRecoveredPrincipal {
                requested: reexpose_amount,
                available: ledger.p_recovered,
            });
        }
        let tw = tw_step_legal(&ledger.tw, event).map_err(|error| match error {
            TwTransitionError::IllegalTransition => VoiceOpenFundingError::IllegalReexposure,
            TwTransitionError::RepresentationOverflow => VoiceOpenFundingError::AmountOutOfRange,
        })?;
        // 0 < amount <= p_recovered，且 p_recovered 本来就在 [0, P]。
        (tw, ledger.p_recovered - reexpose_amount, Some(event))
    };

    let opening_quantity = fixed_q.min(tw.free.max(0));
    if opening_quantity == 0 {
        return Err(VoiceOpenFundingError::QuantityZero);
    }
    let mut projected = ledger.clone();
    projected.tw = tw;
    projected.p_recovered = p_recovered;
    if let Some(event) = reexpose_event {
        projected.phase_events.push(PhaseEvent { event, known_at });
    }
    Ok(VoiceOpenFunding {
        opening_quantity,
        reexpose_event,
        reexpose_amount,
        ledger: projected,
    })
}

#[cfg(test)]
#[path = "voice_open_funding_tests.rs"]
mod tests;
