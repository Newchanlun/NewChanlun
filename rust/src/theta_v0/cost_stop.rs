//! #1441：以 ADR 0044 的具名政策求值；不选择请求时点的版本，不更新塔底。

use std::{fmt, num::NonZeroU32};

use serde::Deserialize;

use super::evidence_gate::{self, BlockUnit, EvidenceGate};
use super::policy_records::{
    invalid, PolicyError, PolicyRef, PolicyVersion, ACTIVE_EVIDENCE_GATE_JSON, COST_STOP_ID,
    EVIDENCE_GATE_ID,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopProfile {
    P0,
    P1HlTestnet,
}

#[derive(Debug)]
pub struct CostStopRecords {
    p0: CostStopPolicy,
    p1_hl_testnet: CostStopPolicy,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RecordData {
    id: String,
    profiles: ProfileData,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProfileData {
    #[serde(rename = "P0")]
    p0: PolicyData,
    #[serde(rename = "P1-hl-testnet")]
    p1_hl_testnet: PolicyData,
}

fn awaiting(field: &str) -> PolicyError {
    PolicyError::AwaitingPolicy {
        id: COST_STOP_ID,
        field: field.to_owned(),
    }
}

impl CostStopRecords {
    pub(super) fn parse(text: Option<&str>) -> Result<Self, PolicyError> {
        let text = text.ok_or(PolicyError::RecordMissing { id: COST_STOP_ID })?;
        let raw: RecordData = serde_json::from_str(text).map_err(|error| {
            let message = error.to_string();
            match message
                .strip_prefix("missing field `")
                .and_then(|rest| rest.split_once('`'))
            {
                Some((field, _)) => awaiting(field),
                None => invalid(COST_STOP_ID, "<record>", message),
            }
        })?;
        if raw.id != COST_STOP_ID {
            return Err(invalid(COST_STOP_ID, "id", "记录族不符"));
        }

        let ProfileData { p0, p1_hl_testnet } = raw.profiles;
        // ADR 0044:55,80：这两份 v1 的专属签署出处不能缺。
        if p0.version.get() == 1 && p0.fee.record_ref.is_none() {
            return Err(awaiting("fee.record_ref"));
        }
        if p1_hl_testnet.version.get() == 1
            && matches!(
                p1_hl_testnet.holding,
                HoldingSource::Missing {
                    designated_source: None,
                    ..
                }
            )
        {
            return Err(awaiting("holding.designated_source"));
        }

        let (gate, authorized_at) = evidence_gate::parse_record(Some(ACTIVE_EVIDENCE_GATE_JSON))?;
        let authorized_before = signed_day_end(&authorized_at)
            .ok_or_else(|| invalid(EVIDENCE_GATE_ID, "authorized_at", "须为有效 UTC 日期"))?;
        let label = gate.record.label();
        let bind = |data: PolicyData| {
            let gate = (data.evidence_gate_ref.as_str() == label).then(|| ResolvedGate {
                record: gate.clone(),
                authorized_before,
            });
            CostStopPolicy { data, gate }
        };
        Ok(Self {
            p0: bind(p0),
            p1_hl_testnet: bind(p1_hl_testnet),
        })
    }

    pub fn profile(&self, profile: CostStopProfile) -> &CostStopPolicy {
        match profile {
            CostStopProfile::P0 => &self.p0,
            CostStopProfile::P1HlTestnet => &self.p1_hl_testnet,
        }
    }
}

/// 只有成本停止记录装载器可以构造的只读政策。
#[derive(Debug)]
pub struct CostStopPolicy {
    data: PolicyData,
    gate: Option<ResolvedGate>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyData {
    version: NonZeroU32,
    supersedes: String,
    symbol: String,
    granularity: String,
    tower_base_ref: String,
    fee: KnownFee,
    slippage: CostSource,
    latency_error: CostSource,
    holding: HoldingSource,
    theta: threshold::Theta,
    evidence_gate_ref: SourceRef<String>,
    authorizer_ref: AuthorizerRef,
    authorized_at: String,
    valid_through: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SourceRef<T>(T);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EmptySourceRef;

impl fmt::Display for EmptySourceRef {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("来源引用不得为空")
    }
}

impl std::error::Error for EmptySourceRef {}

impl<T: AsRef<str>> SourceRef<T> {
    pub fn new(value: T) -> Result<Self, EmptySourceRef> {
        if value.as_ref().trim().is_empty() {
            return Err(EmptySourceRef);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        self.0.as_ref()
    }
}

impl<'de> Deserialize<'de> for SourceRef<String> {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

#[derive(Debug)]
struct AuthorizerRef(SourceRef<String>);

impl<'de> Deserialize<'de> for AuthorizerRef {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        SourceRef::new(String::deserialize(deserializer)?)
            .map(Self)
            .map_err(|_| serde::de::Error::custom("authorizer_ref 不得为空"))
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KnownFee {
    pub venue: String,
    pub tier: String,
    pub role: String,
    pub source_url: SourceRef<String>,
    pub retrieved_at: String,
    pub record_ref: Option<SourceRef<String>>,
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
    Known { source_ref: SourceRef<String> },
    ProxyLowerBound { source_ref: SourceRef<String> },
    // 空对象变体仍检查未知键；serde 的单元变体会丢弃余下的键。
    Missing {},
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
pub enum HoldingSource {
    Known {
        source_ref: SourceRef<String>,
        start_level: u32,
    },
    Missing {
        start_level: u32,
        designated_source: Option<SourceRef<String>>,
    },
}

/// 相对名义本金的十亿分率。非负；波幅和成本使用同一尺度。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RatePpb(pub u64);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostEvidence<'a> {
    Measured {
        rate: RatePpb,
        source_ref: SourceRef<&'a str>,
    },
    ProxyLowerBound {
        rate: RatePpb,
        source_ref: SourceRef<&'a str>,
    },
    Missing,
}

/// 费率由政策给出；其余成本按同一有效域、级别和 ROUNDTRIP 口径提供。
pub struct CostInputs<'a> {
    pub slippage: CostEvidence<'a>,
    pub latency_error: CostEvidence<'a>,
    pub holding: CostEvidence<'a>,
}

/// 首末 bar 时间戳（Unix 秒）；覆盖按首末读数之差计算，不重复计算边界。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TimeSpan {
    pub first_bar: i64,
    pub last_bar: i64,
}

/// 上游探针在一个预登记窗上的 ROUNDTRIP 单边 block bootstrap 下界和样本计数。
#[derive(Debug, Clone, Copy)]
pub struct AmplitudeWindow {
    pub span: TimeSpan,
    pub lower_bound: RatePpb,
    /// 合格样本数；按所引 ADR 的采样单位计，不是 bar 数。
    pub events: u32,
    /// 按此次读数的 block_unit 统计的非空块数。
    pub nonempty_blocks: u32,
}

/// 探针回执，不是合格证书。内核校验门、方法参数、时序与窗口后才消费下界。
pub struct RoundTripBlockBootstrap<'a> {
    pub probe_run_ref: SourceRef<&'a str>,
    pub evidence_gate_ref: &'a str,
    pub confidence: (u32, u32),
    pub block_unit: BlockUnit,
    pub run_started_at: i64,
    pub prereg_frozen_at: i64,
    pub data_span: TimeSpan,
    pub preregistered: &'a [TimeSpan],
    pub per_window: &'a [AmplitudeWindow],
}

pub enum AmplitudeEvidence<'a> {
    Insufficient,
    RoundTripBlockBootstrap(RoundTripBlockBootstrap<'a>),
}

#[derive(Debug)]
struct ResolvedGate {
    record: EvidenceGate,
    authorized_before: i64,
}

// ADR 0022:161：只记授权日期的记录不能证明同日读数已在授权之后。
fn signed_day_end(date: &str) -> Option<i64> {
    let (year, rest) = date.split_once('-')?;
    let (month, day) = rest.split_once('-')?;
    if (year.len(), month.len(), day.len()) != (4, 2, 2)
        || ![year, month, day]
            .iter()
            .all(|part| part.bytes().all(|b| b.is_ascii_digit()))
    {
        return None;
    }
    let (year, month, day): (i64, usize, i64) =
        (year.parse().ok()?, month.parse().ok()?, day.parse().ok()?);
    let leap = |y| y % 4 == 0 && (y % 100 != 0 || y % 400 == 0);
    let month_days = [
        31,
        if leap(year) { 29 } else { 28 },
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ];
    let month = month.checked_sub(1)?;
    if year == 0 || !(1..=*month_days.get(month)?).contains(&day) {
        return None;
    }
    let leaps_before = |y: i64| (y - 1) / 4 - (y - 1) / 100 + (y - 1) / 400;
    let days = (year - 1970) * 365 + leaps_before(year) - leaps_before(1970)
        + month_days[..month].iter().sum::<i64>()
        + day;
    Some(days * 86_400)
}

impl ResolvedGate {
    /// ADR 0022 裁定三、六、七与版本规则；覆盖以时间算，不以事件数算。
    fn admits(
        &self,
        reading: &RoundTripBlockBootstrap<'_>,
        signed_ref: &str,
        granularity: &str,
    ) -> bool {
        let gate = &self.record;
        let (confidence_num, confidence_den) = reading.confidence;
        if reading.evidence_gate_ref != signed_ref
            || reading.block_unit != gate.block_unit
            || (matches!(gate.block_unit, BlockUnit::FixedBars1m { .. }) && granularity != "1m")
            || confidence_den == 0
            || u64::from(confidence_num) * u64::from(gate.confidence.1)
                != u64::from(confidence_den) * u64::from(gate.confidence.0)
            || reading.run_started_at < self.authorized_before
            || reading.prereg_frozen_at >= reading.run_started_at
            || reading.per_window.len() < gate.min_windows as usize
            || reading.per_window.len() != reading.preregistered.len()
            || reading.data_span.first_bar >= reading.data_span.last_bar
        {
            return false;
        }

        let mut windows: Vec<_> = reading.per_window.iter().collect();
        if windows
            .iter()
            .zip(reading.preregistered)
            .any(|(window, span)| window.span != *span)
        {
            return false;
        }
        windows.sort_unstable_by_key(|window| window.span.first_bar);
        let mut prev_end = None;
        let mut coverage = 0;
        for window in windows {
            let TimeSpan {
                first_bar,
                last_bar,
            } = window.span;
            if first_bar >= last_bar
                || first_bar < reading.data_span.first_bar
                || last_bar > reading.data_span.last_bar
                || prev_end.is_some_and(|end| first_bar <= end)
                || window.events < gate.min_events
                || window.nonempty_blocks < gate.min_blocks
                || window.nonempty_blocks > window.events
            {
                return false;
            }
            prev_end = Some(last_bar);
            coverage += i128::from(last_bar) - i128::from(first_bar);
        }
        let history =
            i128::from(reading.data_span.last_bar) - i128::from(reading.data_span.first_bar);
        coverage * i128::from(gate.min_coverage.1) >= history * i128::from(gate.min_coverage.0)
    }
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostStopError {
    /// #2111 裁定前，实测总成本为零不产生四态判定。
    ZeroMeasuredCostAwaitingRuling2111,
}

impl fmt::Display for CostStopError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("实测总成本为零，成本停止归属待 #2111 裁定")
    }
}

impl std::error::Error for CostStopError {}

impl CostStopPolicy {
    pub fn record(&self) -> PolicyRef {
        PolicyRef {
            id: COST_STOP_ID,
            version: PolicyVersion::Signed(self.data.version.get()),
        }
    }

    pub fn theta(&self) -> &Fraction {
        self.data.theta.fraction()
    }

    pub fn fee(&self) -> &KnownFee {
        &self.data.fee
    }

    /// (标的、粒度、塔底)；费率档见 fee。
    pub fn domain(&self) -> (&str, &str, &str) {
        (
            &self.data.symbol,
            &self.data.granularity,
            &self.data.tower_base_ref,
        )
    }

    pub fn cost_sources(&self) -> (&CostSource, &CostSource, &HoldingSource) {
        (
            &self.data.slippage,
            &self.data.latency_error,
            &self.data.holding,
        )
    }

    pub fn evidence_gate_ref(&self) -> &str {
        self.data.evidence_gate_ref.as_str()
    }

    pub fn supersedes(&self) -> &str {
        &self.data.supersedes
    }

    /// (签署原件、签署日、有效期末)。
    pub fn authorization(&self) -> (&str, &str, &str) {
        (
            self.data.authorizer_ref.0.as_str(),
            &self.data.authorized_at,
            &self.data.valid_through,
        )
    }

    /// 调用方选择请求时点的生效政策并绑定有效域；核验证据门是本函数的责任。
    pub fn evaluate(
        &self,
        level: u32,
        costs: CostInputs<'_>,
        amplitude: AmplitudeEvidence<'_>,
    ) -> Result<CostStopStatus, CostStopError> {
        use CostStopStatus::*;
        let unavailable =
            |component| Ok(NotEvaluable(NotEvaluableReason::UnavailableCost(component)));
        let Some((RatePpb(slippage), slippage_is_proxy)) =
            self.data.slippage.resolve(costs.slippage)
        else {
            return unavailable(CostComponent::Slippage);
        };
        let Some((RatePpb(latency), latency_is_proxy)) =
            self.data.latency_error.resolve(costs.latency_error)
        else {
            return unavailable(CostComponent::LatencyError);
        };
        let holding = match &self.data.holding {
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
                } if got.as_str() == source_ref.as_str() => rate,
                _ => return unavailable(CostComponent::Holding),
            },
            HoldingSource::Missing { .. } => return unavailable(CostComponent::Holding),
        };

        // ADR 0035:14：以 ppb × fee.denominator 为共同单位，不舍入费率。
        let fee = u128::from(self.data.fee.rate.numerator) * 1_000_000_000;
        let fee_den = u128::from(self.data.fee.rate.denominator.get());
        let other_cost = u128::from(slippage) + u128::from(latency) + u128::from(holding.0);
        let total = fee + fee + other_cost * fee_den;
        let proxy = slippage_is_proxy || latency_is_proxy;
        if total == 0 && !proxy {
            return Err(CostStopError::ZeroMeasuredCostAwaitingRuling2111);
        }

        let (Some(gate), AmplitudeEvidence::RoundTripBlockBootstrap(reading)) =
            (&self.gate, amplitude)
        else {
            return Ok(InsufficientEvidence(InsufficientReason::Amplitude));
        };
        if !gate.admits(&reading, self.evidence_gate_ref(), &self.data.granularity) {
            return Ok(InsufficientEvidence(InsufficientReason::Amplitude));
        }
        if total == 0 {
            // 零代理下界不能证明真实总成本为零，也不能给出有限比值上界。
            return Ok(InsufficientEvidence(InsufficientReason::UpperBoundOnly));
        }

        let theta = self.theta();
        let required = total.checked_mul(u128::from(theta.numerator));
        let all_pass = required.is_some_and(|required| {
            reading.per_window.iter().all(|window| {
                // u64 × u32 × u32 必可放入 u128；右侧溢出意味着任一左值都不足。
                u128::from(window.lower_bound.0) * fee_den * u128::from(theta.denominator.get())
                    >= required
            })
        });

        Ok(match (proxy, all_pass) {
            (false, true) => Enabled,
            (false, false) => Disabled(FailureBasis::Measured),
            (true, false) => Disabled(FailureBasis::UpperBoundOnly),
            (true, true) => InsufficientEvidence(InsufficientReason::UpperBoundOnly),
        })
    }
}

impl CostSource {
    fn resolve(&self, evidence: CostEvidence<'_>) -> Option<(RatePpb, bool)> {
        match (self, evidence) {
            (
                Self::Known { source_ref },
                CostEvidence::Measured {
                    rate,
                    source_ref: got,
                },
            ) if got.as_str() == source_ref.as_str() => Some((rate, false)),
            (
                Self::ProxyLowerBound { source_ref },
                CostEvidence::ProxyLowerBound {
                    rate,
                    source_ref: got,
                },
            ) if got.as_str() == source_ref.as_str() => Some((rate, true)),
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

    const GATE: &str = "#1677/evidence-gate/v1";
    const SLIPPAGE: &str = "fixture/slippage";
    const LATENCY: &str = "fixture/latency";
    const HOLDING: &str = "fixture/holding";
    // P0 的手算盘：往返手续费 20 bps，滑点、延迟、持有各 1、2、3 bps，门槛波幅 52 bps。
    const AT_GATE: u64 = 5_200_000;
    const INSUFFICIENT: CostStopStatus =
        CostStopStatus::InsufficientEvidence(InsufficientReason::Amplitude);
    const FAIL: CostStopStatus = CostStopStatus::Disabled(FailureBasis::Measured);

    fn record(profile: CostStopProfile, change: impl FnOnce(&mut Value)) -> CostStopRecords {
        let mut raw: Value = serde_json::from_str(ACTIVE_COST_STOP_JSON).unwrap();
        let key = match profile {
            CostStopProfile::P0 => "P0",
            CostStopProfile::P1HlTestnet => "P1-hl-testnet",
        };
        let row = &mut raw["profiles"][key];
        row["version"] = json!(2);
        row["supersedes"] = json!("v1");
        row["authorizer_ref"] = json!("fixture/authorization");
        row["slippage"] = json!({"kind": "Known", "source_ref": SLIPPAGE});
        row["latency_error"] = json!({"kind": "Known", "source_ref": LATENCY});
        row["holding"] = json!({"kind": "Known", "source_ref": HOLDING, "start_level": 0});
        change(row);
        parse_cost_stop(Some(&raw.to_string())).unwrap()
    }

    fn p0(change: impl FnOnce(&mut Value)) -> CostStopRecords {
        record(CostStopProfile::P0, change)
    }

    fn source(value: &str) -> SourceRef<&str> {
        SourceRef::new(value).unwrap()
    }

    fn measured(rate: u64, source_ref: &str) -> CostEvidence<'_> {
        CostEvidence::Measured {
            rate: RatePpb(rate),
            source_ref: source(source_ref),
        }
    }

    fn proxy(rate: u64, source_ref: &str) -> CostEvidence<'_> {
        CostEvidence::ProxyLowerBound {
            rate: RatePpb(rate),
            source_ref: source(source_ref),
        }
    }

    fn costs(rates: [u64; 3]) -> CostInputs<'static> {
        CostInputs {
            slippage: measured(rates[0], SLIPPAGE),
            latency_error: measured(rates[1], LATENCY),
            holding: measured(rates[2], HOLDING),
        }
    }

    fn measured_costs() -> CostInputs<'static> {
        costs([100_000, 200_000, 300_000])
    }

    struct Reading {
        preregistered: Vec<TimeSpan>,
        per_window: Vec<AmplitudeWindow>,
    }

    impl Reading {
        const YEAR_SECONDS: i64 = 366 * 86_400;
        const RUN_STARTED: i64 = 1_800_000_000;
        fn new(bounds: &[u64]) -> Self {
            let per_window: Vec<_> = bounds
                .iter()
                .enumerate()
                .map(|(i, &bound)| {
                    let first_bar = i as i64 * Self::YEAR_SECONDS;
                    AmplitudeWindow {
                        span: TimeSpan {
                            first_bar,
                            last_bar: first_bar + Self::YEAR_SECONDS - 1,
                        },
                        lower_bound: RatePpb(bound),
                        events: 30,
                        nonempty_blocks: 12,
                    }
                })
                .collect();
            Self {
                preregistered: per_window.iter().map(|window| window.span).collect(),
                per_window,
            }
        }

        fn bootstrap(&self) -> RoundTripBlockBootstrap<'_> {
            RoundTripBlockBootstrap {
                probe_run_ref: source("fixture/probe"),
                evidence_gate_ref: GATE,
                confidence: (95, 100),
                block_unit: BlockUnit::CalendarMonthUTC,
                run_started_at: Self::RUN_STARTED,
                prereg_frozen_at: Self::RUN_STARTED - 1,
                data_span: TimeSpan {
                    first_bar: 0,
                    last_bar: 6 * (Self::YEAR_SECONDS - 1),
                },
                preregistered: &self.preregistered,
                per_window: &self.per_window,
            }
        }

        fn amplitude(&self) -> AmplitudeEvidence<'_> {
            AmplitudeEvidence::RoundTripBlockBootstrap(self.bootstrap())
        }
    }

    fn eval(policy: &CostStopPolicy, costs: CostInputs<'_>, bounds: &[u64]) -> CostStopStatus {
        policy
            .evaluate(0, costs, Reading::new(bounds).amplitude())
            .unwrap()
    }

    #[test]
    fn enabled_on_inclusive_threshold() {
        // ADR 0044:41，0035:14：完整证据、每窗下界恰过线也通过。
        for level in [0, 1, 5] {
            for (bound, expected) in [
                (3_999_999, FAIL),
                (4_000_000, CostStopStatus::Enabled),
                (4_000_001, CostStopStatus::Enabled),
            ] {
                assert_eq!(
                    p0(|_| {}).profile(CostStopProfile::P0).evaluate(
                        level,
                        costs([0; 3]),
                        Reading::new(&[bound; 3]).amplitude()
                    ),
                    Ok(expected)
                );
            }
        }
        assert_eq!(
            eval(
                p0(|_| {}).profile(CostStopProfile::P0),
                measured_costs(),
                &[AT_GATE; 3]
            ),
            CostStopStatus::Enabled
        );
    }

    #[test]
    fn disabled_when_a_qualified_window_fails() {
        // ADR 0044:41，0035:14，0022 裁定七：不允许别的窗口替这一窗过线。
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        assert_eq!(
            eval(policy, measured_costs(), &[u64::MAX, AT_GATE - 1, u64::MAX]),
            FAIL
        );
    }

    #[test]
    fn insufficient_evidence_with_fewer_than_signed_windows() {
        // 独审 H1：过线和不过线都先过证据门。
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        for bounds in [&[][..], &[4_000_000], &[4_000_000; 2], &[3_999_999]] {
            let status = eval(policy, costs([0; 3]), bounds);
            println!("窗数={} 下界={bounds:?} -> {status:?}", bounds.len());
            assert_eq!(status, INSUFFICIENT);
        }
    }

    #[test]
    fn unresolvable_gate_cannot_qualify_even_when_labels_match() {
        let records = p0(|row| row["evidence_gate_ref"] = json!("nonexistent/gate"));
        let reading = Reading::new(&[4_000_000; 3]);
        let mut bootstrap = reading.bootstrap();
        bootstrap.evidence_gate_ref = "nonexistent/gate";
        assert_eq!(
            records.profile(CostStopProfile::P0).evaluate(
                0,
                costs([0; 3]),
                AmplitudeEvidence::RoundTripBlockBootstrap(bootstrap)
            ),
            Ok(INSUFFICIENT)
        );
    }

    #[test]
    fn gate_checks_every_window_and_actual_time_coverage() {
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        let assert_short = |reading: &Reading| {
            assert_eq!(
                policy.evaluate(0, costs([0; 3]), reading.amplitude()),
                Ok(INSUFFICIENT)
            );
        };

        let mut reading = Reading::new(&[4_000_000; 3]);
        assert_eq!(
            policy.evaluate(0, costs([0; 3]), reading.amplitude()),
            Ok(CostStopStatus::Enabled)
        );

        reading.per_window[1].events -= 1;
        assert_short(&reading);
        reading.per_window[1].events += 1;
        reading.per_window[1].nonempty_blocks -= 1;
        assert_short(&reading);
        reading.per_window[1].nonempty_blocks += 1;
        reading.per_window[1].span.last_bar -= 1;
        assert_short(&reading); // 读数与冻结窗口不吻合。
        reading.preregistered[1] = reading.per_window[1].span;
        assert_short(&reading); // 仅少一秒覆盖，仍不足一半。
        reading.per_window[1].span.first_bar = reading.per_window[0].span.last_bar;
        reading.per_window[1].span.last_bar += 2;
        reading.preregistered[1] = reading.per_window[1].span;
        assert_short(&reading); // 总时长达标也不能共享边界 bar。
    }

    #[test]
    fn gate_checks_the_frozen_method_and_version_timing() {
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        let reading = Reading::new(&[4_000_000; 3]);
        let breaks: [fn(&mut RoundTripBlockBootstrap<'_>); 5] = [
            |r| r.evidence_gate_ref = "different/gate",
            |r| r.confidence = (90, 100),
            |r| r.block_unit = BlockUnit::FixedBars1m { bars: 43_200 },
            |r| r.prereg_frozen_at = r.run_started_at,
            |r| {
                // 2026-08-14 23:59:59 UTC，日期精度不证明签署早于读数。
                r.run_started_at = 1_786_751_999;
                r.prereg_frozen_at = r.run_started_at - 1;
            },
        ];
        for break_rule in breaks {
            let mut bootstrap = reading.bootstrap();
            break_rule(&mut bootstrap);
            assert_eq!(
                policy.evaluate(
                    0,
                    costs([0; 3]),
                    AmplitudeEvidence::RoundTripBlockBootstrap(bootstrap)
                ),
                Ok(INSUFFICIENT)
            );
        }
        assert_eq!(
            policy.evaluate(0, costs([0; 3]), AmplitudeEvidence::Insufficient),
            Ok(INSUFFICIENT)
        );
    }

    #[test]
    fn runtime_missing_is_not_zero_for_signed_known_cost() {
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        for component in [
            CostComponent::Slippage,
            CostComponent::LatencyError,
            CostComponent::Holding,
        ] {
            let mut input = costs([0; 3]);
            *match component {
                CostComponent::Slippage => &mut input.slippage,
                CostComponent::LatencyError => &mut input.latency_error,
                CostComponent::Holding => &mut input.holding,
            } = CostEvidence::Missing;
            assert_eq!(
                eval(policy, input, &[4_000_000; 3]),
                CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(component))
            );
        }
    }

    fn check_missing_slippage(profile: CostStopProfile) {
        // ADR 0044:26,32,41：签署记录的 Missing 不被调用方覆盖。
        let records = active_cost_stop().unwrap();
        let policy = records.profile(profile);
        for slippage in [
            CostEvidence::Missing,
            measured(0, SLIPPAGE),
            proxy(0, SLIPPAGE),
        ] {
            assert_eq!(
                eval(
                    policy,
                    CostInputs {
                        slippage,
                        ..costs([0; 3])
                    },
                    &[u64::MAX; 3]
                ),
                CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                    CostComponent::Slippage
                ))
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
        // ADR 0044:27,38；ADR 0035:19：两种代理分别使用或同时使用，结论均限于失败方向。
        for (slip_proxy, latency_proxy) in [(true, false), (false, true), (true, true)] {
            let records = p0(|row| {
                if slip_proxy {
                    row["slippage"]["kind"] = json!("ProxyLowerBound");
                }
                if latency_proxy {
                    row["latency_error"]["kind"] = json!("ProxyLowerBound");
                }
            });
            let policy = records.profile(CostStopProfile::P0);
            let inputs = || CostInputs {
                slippage: if slip_proxy {
                    proxy(0, SLIPPAGE)
                } else {
                    measured(0, SLIPPAGE)
                },
                latency_error: if latency_proxy {
                    proxy(0, LATENCY)
                } else {
                    measured(0, LATENCY)
                },
                holding: measured(0, HOLDING),
            };
            assert_eq!(
                eval(policy, inputs(), &[3_999_999; 3]),
                CostStopStatus::Disabled(FailureBasis::UpperBoundOnly)
            );
            for bound in [4_000_000, u64::MAX] {
                assert_eq!(
                    eval(policy, inputs(), &[bound; 3]),
                    CostStopStatus::InsufficientEvidence(InsufficientReason::UpperBoundOnly)
                );
            }
        }
    }

    #[test]
    fn source_reference_cannot_be_empty_or_cross_source() {
        assert_eq!(SourceRef::new(""), Err(EmptySourceRef));
        assert_eq!(SourceRef::new(" \t"), Err(EmptySourceRef));
        let records = p0(|_| {});
        let policy = records.profile(CostStopProfile::P0);
        assert_eq!(
            eval(
                policy,
                CostInputs {
                    slippage: measured(0, "other/slippage"),
                    ..costs([0; 3])
                },
                &[4_000_000; 3]
            ),
            CostStopStatus::NotEvaluable(NotEvaluableReason::UnavailableCost(
                CostComponent::Slippage
            ))
        );
    }

    #[test]
    fn roundtrip_lower_bound_not_median_drives_the_gate() {
        // ADR 0035:14,16：输入只有各窗 ROUNDTRIP 单边下界，没有中位数槽位。
        assert_eq!(
            eval(
                p0(|_| {}).profile(CostStopProfile::P0),
                measured_costs(),
                &[AT_GATE - 1; 3]
            ),
            FAIL
        );
    }

    #[test]
    fn theta_is_read_from_record_without_fallback() {
        let higher = p0(|row| {
            let theta = &mut row["theta"];
            theta["numerator"] = json!(
                theta["numerator"].as_u64().unwrap() + theta["denominator"].as_u64().unwrap()
            );
        });
        assert_eq!(
            eval(
                higher.profile(CostStopProfile::P0),
                measured_costs(),
                &[AT_GATE; 3]
            ),
            FAIL
        );
    }

    #[test]
    fn p1_signed_fee_moves_the_exact_ppb_boundary() {
        let p1 = CostStopProfile::P1HlTestnet;
        // 手算盘：P1 来回费率 9 bps、其余实测零，过线波幅 18 bps。
        for scale in [1, 10] {
            let records = record(p1, |row| {
                let fee = &mut row["fee"]["rate"]["numerator"];
                *fee = json!(fee.as_u64().unwrap() * scale);
            });
            let policy = records.profile(p1);
            let bound = 1_800_000 * scale;
            assert_eq!(eval(policy, costs([0; 3]), &[bound - 1; 3]), FAIL);
            assert_eq!(
                eval(policy, costs([0; 3]), &[bound; 3]),
                CostStopStatus::Enabled
            );
        }
    }

    #[test]
    fn holding_missing_only_from_its_signed_start_level() {
        let records = p0(|row| row["holding"] = json!({"kind": "Missing", "start_level": 1}));
        let policy = records.profile(CostStopProfile::P0);
        let reading = Reading::new(&[AT_GATE; 3]);
        assert_eq!(
            policy.evaluate(0, measured_costs(), reading.amplitude()),
            Ok(CostStopStatus::Enabled)
        );
        assert_eq!(
            policy.evaluate(1, measured_costs(), reading.amplitude()),
            Ok(CostStopStatus::NotEvaluable(
                NotEvaluableReason::UnavailableCost(CostComponent::Holding)
            ))
        );
    }

    #[test]
    fn zero_measured_total_never_produces_a_four_state_result() {
        let records = p0(|row| row["fee"]["rate"]["numerator"] = json!(0));
        let policy = records.profile(CostStopProfile::P0);
        let reading = Reading::new(&[4_000_000; 3]);
        for amplitude in [reading.amplitude(), AmplitudeEvidence::Insufficient] {
            assert_eq!(
                policy.evaluate(0, costs([0; 3]), amplitude),
                Err(CostStopError::ZeroMeasuredCostAwaitingRuling2111)
            );
        }
        assert_eq!(
            eval(policy, costs([2_000_000, 0, 0]), &[4_000_000; 3]),
            CostStopStatus::Enabled
        );
    }
}
