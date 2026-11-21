//! ADR 0043 / #1651：回到零仓后开声部的资金求值。#1421 接线时由调用者提供
//! 已验签政策、同量纲的账本和固定 Q；本模块不读记录、不执行订单、不改写历史。

use super::ledger::{tw_step, TwEvent, TwState};
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
    QuantityZero,
    IllegalReexposure,
    AmountOutOfRange,
    KnownAtOutOfOrder,
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
        let withdrawn = tw.withdrawn.max(0);
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
    /// 按 `known_at` 非递减记录；同一求值点内按追加顺序。
    pub phase_events: Vec<PhaseEvent>,
}

impl VoiceOpenLedger {
    pub fn growth_eligible_long(&self) -> bool {
        self.k_cost_basis <= 0 && self.p_recovered >= self.principal_total
    }

    pub fn growth_eligible_short(&self) -> bool {
        self.cum_net_realized_profit >= self.principal_total
    }

    /// 只取在世或拟开方向对应的扩量谓词；空仓无拟开方向时不求值。
    /// 资格不是开局准入门，也不是 latch 的重算值。
    pub fn growth_eligible(&self, side: VoiceSide) -> Option<bool> {
        match side {
            VoiceSide::Long => Some(self.growth_eligible_long()),
            VoiceSide::Short => Some(self.growth_eligible_short()),
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
/// 调用方仍需在同一开局点处理场所粒度与订单；原账、已有 AsKnown 快照不会被求值改动。
pub fn evaluate_voice_open_funding(
    ledger: &VoiceOpenLedger,
    fixed_q: i64,
    policy: VoiceOpenFundingPolicy,
    known_at: i64,
) -> Result<VoiceOpenFunding, VoiceOpenFundingError> {
    if fixed_q <= 0 {
        return Err(VoiceOpenFundingError::QuantityZero);
    }
    let reexpose_amount = policy.reexpose_amount(&ledger.tw, fixed_q);
    let available = ledger
        .tw
        .free
        .checked_add(reexpose_amount)
        .ok_or(VoiceOpenFundingError::AmountOutOfRange)?;
    let opening_quantity = fixed_q.min(available.max(0));
    if opening_quantity == 0 {
        return Err(VoiceOpenFundingError::QuantityZero);
    }

    let mut projected = ledger.clone();
    let reexpose_event = if reexpose_amount == 0 {
        None
    } else {
        let event = TwEvent::ReexposePrincipal(reexpose_amount);
        if !event.is_legal_from(&ledger.tw) {
            return Err(VoiceOpenFundingError::IllegalReexposure);
        }
        if ledger
            .phase_events
            .last()
            .is_some_and(|last| known_at < last.known_at)
        {
            return Err(VoiceOpenFundingError::KnownAtOutOfOrder);
        }
        projected.p_recovered = ledger
            .p_recovered
            .checked_sub(reexpose_amount)
            .ok_or(VoiceOpenFundingError::AmountOutOfRange)?;
        projected.tw = tw_step(&ledger.tw, event);
        projected.phase_events.push(PhaseEvent { event, known_at });
        Some(event)
    };
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
