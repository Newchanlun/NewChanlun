//! #1441 · ADR 0044：只消费编内、验过登记摘要的原件。调用方点名 profile、修订、级别；
//! 请求时点选版归 TB-07。数据集身份、全史区间和时间戳只核原件间一致与内部自洽，
//! 信任根是登记行和独审出处，不在核内认证原始行情。此构建没有已登记的窗表、波幅 run 或成本读数。
//!
//! 事件进出皆须在窗内，允许同 bar，依进场 UTC 月分块；修改这些规则须出 amplitude-run/2。
//! 只支持 1m 和 CalendarMonthUTC。#2121 裁定前生产不识别任何波幅方法；
//! 接入按月 bootstrap 时，方法须接收已核验的月块边界和所签置信度，不能只接收扁平样本。
//! #2111（ADR 0044 §三）要求先核来源与波幅资格，再区分正分母、实测零及代理零。

use std::fmt;

mod amplitude;
mod policy;
mod reading;
mod registry;
mod total;
mod zero_total;

use amplitude::QualifiedAmplitude;
use reading::Basis;
use total::{CostTotal, NonZeroTotal, SplitTotal};

pub use super::evidence_gate::WindowGap;
use super::policy_records::PolicyRef;
pub use amplitude::{AmplitudeGap, WindowReading};
pub use policy::{
    CostStopPolicy, CostTerm, Domain, Fraction, HoldingTerm, OriginalRef, SignedFee, SourceBinding,
    SourceRef,
};
pub use registry::RecordIdentity;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopProfile {
    P0,
    P1HlTestnet,
}

impl CostStopProfile {
    fn label(self) -> &'static str {
        match self {
            Self::P0 => "P0",
            Self::P1HlTestnet => "P1-hl-testnet",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct RatePpb(u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostComponent {
    Slippage,
    LatencyError,
    Holding,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostGap {
    SignedMissing,
    Unbound,
    OriginalUnavailable,
    ReadingUnreadable,
    ReadingMismatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotEvaluableReason {
    UnavailableCost(CostComponent),
    ZeroTotalCost,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InsufficientReason {
    Amplitude,
    UpperBoundOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureBasis {
    Measured,
    UpperBoundOnly,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopStatus {
    Enabled,
    Disabled(FailureBasis),
    InsufficientEvidence(InsufficientReason),
    NotEvaluable(NotEvaluableReason),
}

/// 政策装载错误由 PolicyError 报告；#2111 已裁定原零成本待裁错误。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopError {}

impl fmt::Display for CostStopError {
    fn fmt(&self, _: &mut fmt::Formatter<'_>) -> fmt::Result {
        match *self {}
    }
}

impl std::error::Error for CostStopError {}

#[derive(Debug)]
pub struct CostStopOutcome {
    status: CostStopStatus,
    record: PolicyRef,
    consumed: Vec<RecordIdentity>,
    cost_gap: Option<(CostComponent, CostGap)>,
    amplitude_gap: Option<AmplitudeGap>,
    windows: Vec<WindowReading>,
}

impl CostStopOutcome {
    pub fn status(&self) -> CostStopStatus {
        self.status
    }
    pub fn record(&self) -> PolicyRef {
        self.record
    }
    pub fn consumed(&self) -> &[RecordIdentity] {
        &self.consumed
    }
    pub fn cost_gap(&self) -> Option<(CostComponent, CostGap)> {
        self.cost_gap
    }
    pub fn amplitude_gap(&self) -> Option<&AmplitudeGap> {
        self.amplitude_gap.as_ref()
    }
    pub fn windows(&self) -> &[WindowReading] {
        &self.windows
    }
}

impl CostStopPolicy {
    pub fn evaluate(&self, level: u32) -> Result<CostStopOutcome, CostStopError> {
        let mut consumed = vec![self.identity().copy_identity()];
        let costs = match self.costs(level, &mut consumed) {
            Ok(costs) => costs,
            Err((component, gap)) => {
                return Ok(CostStopOutcome {
                    status: CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                        component,
                    )),
                    record: self.record(),
                    consumed,
                    cost_gap: Some((component, gap)),
                    amplitude_gap: None,
                    windows: Vec::new(),
                })
            }
        };
        let assessment = decide(self.theta(), self.fee().rate(), costs, || {
            amplitude::resolve(self.store, self, level, &mut consumed)
        });
        let (status, windows, amplitude_gap) = match assessment {
            Ok((status, amplitude)) => (status, amplitude.into_readings(), None),
            Err(gap) => (
                CostStopStatus::InsufficientEvidence(InsufficientReason::Amplitude),
                Vec::new(),
                Some(gap),
            ),
        };
        Ok(CostStopOutcome {
            status,
            record: self.record(),
            consumed,
            cost_gap: None,
            amplitude_gap,
            windows,
        })
    }

    fn costs(
        &self,
        level: u32,
        consumed: &mut Vec<RecordIdentity>,
    ) -> Result<CostTotal, (CostComponent, CostGap)> {
        let read = |term, component, consumed: &mut Vec<_>| {
            reading::cost(self.store, term, self.domain(), level, component, consumed)
                .map_err(|gap| (component, gap))
        };
        let (slippage, slip_basis) = read(&self.terms.slippage, CostComponent::Slippage, consumed)?;
        let (latency, latency_basis) = read(
            &self.terms.latency_error,
            CostComponent::LatencyError,
            consumed,
        )?;
        let holding = match &self.terms.holding {
            HoldingTerm::Known { start_level, .. } | HoldingTerm::Missing { start_level, .. }
                if level < *start_level =>
            {
                RatePpb(0)
            }
            HoldingTerm::Known { source, .. } => {
                reading::holding(self.store, source, self.domain(), level, consumed)
                    .map_err(|gap| (CostComponent::Holding, gap))?
            }
            HoldingTerm::Missing { .. } => {
                return Err((CostComponent::Holding, CostGap::SignedMissing))
            }
        };
        let proxy = [slip_basis, latency_basis].contains(&Basis::ProxyLowerBound);
        Ok(CostTotal::new(
            self.fee().rate(),
            slippage,
            latency,
            holding,
            proxy,
        ))
    }
}

type AmplitudeFacts = Result<QualifiedAmplitude, AmplitudeGap>;
type Assessment = Result<(CostStopStatus, QualifiedAmplitude), AmplitudeGap>;

fn decide(
    theta: &Fraction,
    fee: &Fraction,
    costs: CostTotal,
    amplitude: impl FnOnce() -> AmplitudeFacts,
) -> Assessment {
    match costs.split() {
        SplitTotal::Zero(zero) => zero_total::settle(zero, amplitude),
        SplitTotal::NonZero(total) => {
            let amplitude = amplitude()?;
            Ok((compare(theta, fee, total, &amplitude), amplitude))
        }
    }
}

fn compare(
    theta: &Fraction,
    fee: &Fraction,
    total: NonZeroTotal,
    amplitude: &QualifiedAmplitude,
) -> CostStopStatus {
    let required = total.value().checked_mul(u128::from(theta.numerator()));
    let all_pass = required.is_some_and(|required| {
        amplitude.lower_bounds().all(|bound| {
            // 左侧 u64 × u32 × u32 必可表示；右侧溢出即每窗都低于门槛。
            u128::from(bound.0)
                * u128::from(fee.denominator().get())
                * u128::from(theta.denominator().get())
                >= required
        })
    });
    match (total.is_proxy(), all_pass) {
        (false, true) => CostStopStatus::Enabled,
        (false, false) => CostStopStatus::Disabled(FailureBasis::Measured),
        (true, false) => CostStopStatus::Disabled(FailureBasis::UpperBoundOnly),
        (true, true) => CostStopStatus::InsufficientEvidence(InsufficientReason::UpperBoundOnly),
    }
}

#[cfg(test)]
mod tests;
