use super::total::ZeroTotal;
use super::{AmplitudeFacts, Assessment, CostStopStatus, InsufficientReason, NotEvaluableReason};

/// ADR 0044 §三（#2111）的唯一零分母落点。证据不足不被零分母取代。
pub(super) fn settle(zero: ZeroTotal, amplitude: impl FnOnce() -> AmplitudeFacts) -> Assessment {
    let amplitude = amplitude()?;
    let status = if zero.is_proxy() {
        CostStopStatus::InsufficientEvidence(InsufficientReason::UpperBoundOnly)
    } else {
        CostStopStatus::NotEvaluable(NotEvaluableReason::ZeroTotalCost)
    };
    Ok((status, amplitude))
}
