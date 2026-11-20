//! #1441：以 ADR 0044 的具名政策求值；不选择请求时点的版本，不更新塔底。

use std::num::NonZeroU32;

use serde::Deserialize;

use super::policy_records::{invalid, PolicyError, PolicyRef, PolicyVersion, COST_STOP_ID};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopProfile {
    P0,
    P1HlTestnet,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CostStopRecords {
    id: String,
    profiles: Profiles,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Profiles {
    #[serde(rename = "P0")]
    p0: CostStopPolicy,
    #[serde(rename = "P1-hl-testnet")]
    p1_hl_testnet: CostStopPolicy,
}

impl CostStopRecords {
    pub(super) fn parse(text: Option<&str>) -> Result<Self, PolicyError> {
        let text = text.ok_or(PolicyError::RecordMissing { id: COST_STOP_ID })?;
        let records: Self = serde_json::from_str(text)
            .map_err(|error| invalid(COST_STOP_ID, "<record>", error.to_string()))?;
        if records.id != COST_STOP_ID {
            return Err(invalid(COST_STOP_ID, "id", "记录族不符"));
        }
        Ok(records)
    }

    pub fn profile(&self, profile: CostStopProfile) -> &CostStopPolicy {
        match profile {
            CostStopProfile::P0 => &self.profiles.p0,
            CostStopProfile::P1HlTestnet => &self.profiles.p1_hl_testnet,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CostStopPolicy {
    version: NonZeroU32,
    pub supersedes: String,
    pub symbol: String,
    pub granularity: String,
    pub tower_base_ref: String,
    pub fee: KnownFee,
    pub slippage: CostSource,
    pub latency_error: CostSource,
    pub holding: HoldingSource,
    theta: threshold::Theta,
    pub evidence_gate_ref: String,
    pub authorizer_ref: String,
    pub authorized_at: String,
    pub valid_through: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnownFee {
    pub venue: String,
    pub tier: String,
    pub role: String,
    pub source_url: String,
    pub retrieved_at: String,
    pub record_ref: Option<String>,
    pub rate: Fraction,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Fraction {
    pub numerator: u32,
    pub denominator: NonZeroU32,
}

mod threshold {
    use super::Fraction;
    use serde::{Deserialize, Deserializer};

    /// 只从记录反序列化，没有常数构造器或默认值。
    #[derive(Debug)]
    pub(super) struct Theta(Fraction);

    impl<'de> Deserialize<'de> for Theta {
        fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
            let value = Fraction::deserialize(deserializer)?;
            if value.numerator < value.denominator.get() {
                return Err(serde::de::Error::custom(
                    "theta：分子不得小于分母（ADR 0035 裁定一）",
                ));
            }
            Ok(Self(value))
        }
    }

    impl Theta {
        pub(super) fn fraction(&self) -> &Fraction {
            &self.0
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum CostSource {
    Known { source_ref: String },
    ProxyLowerBound { source_ref: String },
    Missing,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum HoldingSource {
    Known {
        source_ref: String,
        start_level: u32,
    },
    Missing {
        start_level: u32,
        designated_source: Option<String>,
    },
}

/// 相对名义本金的十亿分率。非负；波幅和成本使用同一尺度。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RatePpb(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostEvidence<'a> {
    Measured { rate: RatePpb, source_ref: &'a str },
    ProxyLowerBound { rate: RatePpb, source_ref: &'a str },
    Missing,
}

/// 费率由政策给出；其余成本按同一有效域、级别和 ROUNDTRIP 口径提供。
pub struct CostInputs<'a> {
    pub slippage: CostEvidence<'a>,
    pub latency_error: CostEvidence<'a>,
    pub holding: CostEvidence<'a>,
}

pub enum AmplitudeEvidence<'a> {
    Insufficient,
    /// 生产者先按具名证据门验证冻结时间、块数、事件数及不重叠窗口的覆盖。
    /// 此处只消费每个合格窗的 ROUNDTRIP 单边置信下界，不接收中位数或合计。
    QualifiedRoundTripLowerBounds {
        evidence_gate_ref: &'a str,
        per_window: &'a [RatePpb],
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostComponent {
    Slippage,
    LatencyError,
    Holding,
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

impl CostStopPolicy {
    pub fn record(&self) -> PolicyRef {
        PolicyRef {
            id: COST_STOP_ID,
            version: PolicyVersion::Signed(self.version.get()),
        }
    }

    pub fn theta(&self) -> &Fraction {
        self.theta.fraction()
    }

    /// 调用方负责选择请求时点的生效政策并绑定有效域。这里不跨域借用读数。
    pub fn evaluate(
        &self,
        level: u32,
        costs: CostInputs<'_>,
        amplitude: AmplitudeEvidence<'_>,
    ) -> CostStopStatus {
        use CostStopStatus::*;
        let unavailable = |component| NotEvaluable(NotEvaluableReason::UnavailableCost(component));
        let Some((RatePpb(slippage), slippage_is_proxy)) = self.slippage.resolve(costs.slippage)
        else {
            return unavailable(CostComponent::Slippage);
        };
        let Some((RatePpb(latency), latency_is_proxy)) =
            self.latency_error.resolve(costs.latency_error)
        else {
            return unavailable(CostComponent::LatencyError);
        };
        let holding = match &self.holding {
            HoldingSource::Known { start_level, .. }
            | HoldingSource::Missing { start_level, .. }
                if level < *start_level =>
            {
                RatePpb(0)
            }
            HoldingSource::Known { source_ref, .. } => match costs.holding {
                CostEvidence::Measured {
                    rate,
                    source_ref: got,
                } if got == source_ref => rate,
                _ => return unavailable(CostComponent::Holding),
            },
            HoldingSource::Missing { .. } => return unavailable(CostComponent::Holding),
        };

        // ADR 0035:14。保持费率整数对的精度，分母统一到 ppb × fee.denominator。
        let fee = u128::from(self.fee.rate.numerator) * 1_000_000_000;
        let fee_den = u128::from(self.fee.rate.denominator.get());
        let other_cost = u128::from(slippage) + u128::from(latency) + u128::from(holding.0);
        let total = fee + fee + other_cost * fee_den;
        if total == 0 {
            return NotEvaluable(NotEvaluableReason::ZeroTotalCost);
        }

        let AmplitudeEvidence::QualifiedRoundTripLowerBounds {
            evidence_gate_ref,
            per_window,
        } = amplitude
        else {
            return InsufficientEvidence(InsufficientReason::Amplitude);
        };
        if evidence_gate_ref != self.evidence_gate_ref || per_window.is_empty() {
            return InsufficientEvidence(InsufficientReason::Amplitude);
        }

        let theta = self.theta();
        let required = total.checked_mul(u128::from(theta.numerator));
        let all_pass = required.is_some_and(|required| {
            per_window.iter().all(|bound| {
                // u64 × u32 × u32 必可放入 u128；右侧溢出意味着任一左值都不足。
                u128::from(bound.0) * fee_den * u128::from(theta.denominator.get()) >= required
            })
        });

        match (slippage_is_proxy || latency_is_proxy, all_pass) {
            (false, true) => Enabled,
            (false, false) => Disabled(FailureBasis::Measured),
            (true, false) => Disabled(FailureBasis::UpperBoundOnly),
            (true, true) => InsufficientEvidence(InsufficientReason::UpperBoundOnly),
        }
    }
}

impl CostSource {
    /// 第二项表示成本只有限定方向的下界。
    fn resolve(&self, evidence: CostEvidence<'_>) -> Option<(RatePpb, bool)> {
        match (self, evidence) {
            (
                Self::Known { source_ref },
                CostEvidence::Measured {
                    rate,
                    source_ref: got,
                },
            ) if got == source_ref => Some((rate, false)),
            (
                Self::ProxyLowerBound { source_ref },
                CostEvidence::ProxyLowerBound {
                    rate,
                    source_ref: got,
                },
            ) if got == source_ref => Some((rate, true)),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::theta_v0::policy_records::{
        active_cost_stop, parse_cost_stop, ACTIVE_COST_STOP_JSON,
    };
    use serde_json::{json, Value};

    // P0 夹具只改成本来源；阈值和费率沿用记录。手算盘：往返手续费 20 bps，
    // 滑点、延迟、持有各 1/2/3 bps，总成本 26 bps；门槛波幅是 52 bps。
    const AT_GATE: RatePpb = RatePpb(5_200_000);
    const BELOW: RatePpb = RatePpb(AT_GATE.0 - 1);
    const ABOVE: RatePpb = RatePpb(AT_GATE.0 + 1);
    const SLIPPAGE: &str = "fixture/slippage";
    const LATENCY: &str = "fixture/latency";
    const HOLDING: &str = "fixture/holding";

    fn with_fixture(change: impl FnOnce(&mut Value)) -> CostStopRecords {
        let mut raw: Value = serde_json::from_str(ACTIVE_COST_STOP_JSON).unwrap();
        let p0 = &mut raw["profiles"]["P0"];
        p0["slippage"] = json!({"kind": "Known", "source_ref": SLIPPAGE});
        p0["latency_error"] = json!({"kind": "Known", "source_ref": LATENCY});
        p0["holding"] = json!({"kind": "Known", "source_ref": HOLDING, "start_level": 0});
        change(p0);
        parse_cost_stop(Some(&raw.to_string())).unwrap()
    }

    fn measured(rate: u64, source_ref: &'static str) -> CostEvidence<'static> {
        CostEvidence::Measured {
            rate: RatePpb(rate),
            source_ref,
        }
    }

    fn costs() -> CostInputs<'static> {
        CostInputs {
            slippage: measured(100_000, SLIPPAGE),
            latency_error: measured(200_000, LATENCY),
            holding: measured(300_000, HOLDING),
        }
    }

    fn amplitude(per_window: &[RatePpb]) -> AmplitudeEvidence<'_> {
        AmplitudeEvidence::QualifiedRoundTripLowerBounds {
            evidence_gate_ref: "#1677/evidence-gate/v1",
            per_window,
        }
    }

    #[test]
    fn enabled_on_inclusive_threshold() {
        // ADR 0044:41 Enabled；ADR 0035:14 单边下界比值等于阈值也通过。
        let records = with_fixture(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        assert_eq!(
            policy.evaluate(0, costs(), amplitude(&[AT_GATE; 3])),
            CostStopStatus::Enabled
        );
    }

    #[test]
    fn disabled_when_a_qualified_window_fails() {
        // ADR 0044:41 Disabled；ADR 0035:14，ADR 0022 裁定七：任一合格窗不过线。
        let records = with_fixture(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        assert_eq!(
            policy.evaluate(0, costs(), amplitude(&[ABOVE, BELOW, ABOVE])),
            CostStopStatus::Disabled(FailureBasis::Measured),
        );
    }

    #[test]
    fn insufficient_evidence_without_qualified_amplitude() {
        // ADR 0044:37,41 InsufficientEvidence；ADR 0035:22 的 #907 不作通过证据。
        let records = with_fixture(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        for evidence in [
            AmplitudeEvidence::Insufficient,
            amplitude(&[]),
            AmplitudeEvidence::QualifiedRoundTripLowerBounds {
                evidence_gate_ref: "#1677/evidence-gate/v999",
                per_window: &[ABOVE; 3],
            },
        ] {
            assert_eq!(
                policy.evaluate(0, costs(), evidence),
                CostStopStatus::InsufficientEvidence(InsufficientReason::Amplitude),
            );
        }
    }

    fn check_missing_slippage(profile: CostStopProfile) {
        // ADR 0044:26,32,41 NotEvaluable；传了数也不能把已签 Missing 当 Known。
        let records = active_cost_stop().unwrap();
        let policy = records.profile(profile);
        for slippage in [CostEvidence::Missing, measured(0, SLIPPAGE)] {
            assert_eq!(
                policy.evaluate(
                    0,
                    CostInputs {
                        slippage,
                        ..costs()
                    },
                    amplitude(&[ABOVE; 3])
                ),
                CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                    CostComponent::Slippage
                )),
            );
        }
    }

    #[test]
    fn p0_missing_slippage_is_not_evaluable() {
        check_missing_slippage(CostStopProfile::P0);
    }

    #[test]
    fn p1_missing_slippage_is_not_evaluable() {
        check_missing_slippage(CostStopProfile::P1HlTestnet);
    }

    #[test]
    fn proxy_lower_bound_can_only_prove_failure() {
        // ADR 0044:27,38；ADR 0035:19：上界低于门槛可判失败，上界过线不能放行。
        let records = with_fixture(|p0| {
            p0["latency_error"]["kind"] = json!("ProxyLowerBound");
        });
        let policy = records.profile(CostStopProfile::P0);
        let proxy_costs = || CostInputs {
            latency_error: CostEvidence::ProxyLowerBound {
                rate: RatePpb(200_000),
                source_ref: LATENCY,
            },
            ..costs()
        };
        assert_eq!(
            policy.evaluate(0, proxy_costs(), amplitude(&[BELOW; 3])),
            CostStopStatus::Disabled(FailureBasis::UpperBoundOnly),
        );
        for bound in [AT_GATE, ABOVE] {
            assert_eq!(
                policy.evaluate(0, proxy_costs(), amplitude(&[bound; 3])),
                CostStopStatus::InsufficientEvidence(InsufficientReason::UpperBoundOnly),
            );
        }
        assert_eq!(
            policy.evaluate(0, costs(), amplitude(&[ABOVE; 3])),
            CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                CostComponent::LatencyError
            )),
        );
    }

    #[test]
    fn roundtrip_lower_bound_not_median_drives_the_gate() {
        // ADR 0035:14,16：同一往返波幅，仅下界过线才通过；中位数过线无效。
        let records = with_fixture(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        let median_above = [RatePpb(AT_GATE.0 * 4); 3];
        let lower_bounds = [BELOW; 3];
        assert!(median_above
            .iter()
            .zip(&lower_bounds)
            .all(|(median, lower)| median.0 > AT_GATE.0 && lower.0 < AT_GATE.0));
        assert_eq!(
            policy.evaluate(0, costs(), amplitude(&lower_bounds)),
            CostStopStatus::Disabled(FailureBasis::Measured),
        );
    }

    #[test]
    fn theta_is_read_from_record_without_fallback() {
        let baseline = with_fixture(|_| {});
        let higher = with_fixture(|p0| {
            let theta = &mut p0["theta"];
            theta["numerator"] = json!(
                theta["numerator"].as_u64().unwrap() + theta["denominator"].as_u64().unwrap()
            );
        });
        assert_eq!(
            baseline
                .profile(CostStopProfile::P0)
                .evaluate(0, costs(), amplitude(&[AT_GATE; 3])),
            CostStopStatus::Enabled,
        );
        assert_eq!(
            higher
                .profile(CostStopProfile::P0)
                .evaluate(0, costs(), amplitude(&[AT_GATE; 3])),
            CostStopStatus::Disabled(FailureBasis::Measured),
        );
    }

    #[test]
    fn holding_missing_only_from_its_signed_start_level() {
        // ADR 0035:19：未到起始级别是不适用，不把适用但缺失的持有成本当零。
        let records = with_fixture(|p0| {
            p0["holding"] = json!({"kind": "Missing", "start_level": 1});
        });
        let policy = records.profile(CostStopProfile::P0);
        assert_eq!(
            policy.evaluate(0, costs(), amplitude(&[AT_GATE; 3])),
            CostStopStatus::Enabled
        );
        assert_eq!(
            policy.evaluate(1, costs(), amplitude(&[AT_GATE; 3])),
            CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                CostComponent::Holding
            )),
        );
    }
}
