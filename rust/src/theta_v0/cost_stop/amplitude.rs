use serde_json::Value;

use super::policy::{
    bad, bound_ref, digest_string, json, object, read_domain, reference, req, string, unsigned,
};
use super::registry::{OriginalKind, Store, Verified};
use super::{CostStopPolicy, Domain, OriginalRef, RatePpb, RecordIdentity, SourceRef, WindowGap};
use crate::theta_v0::evidence_gate::{self, QualifiedWindow, WindowSpan};
use crate::theta_v0::policy_records::PolicyError;

#[derive(Debug, PartialEq, Eq)]
pub enum AmplitudeGap {
    EvidenceGateUnavailable,
    GateIdentity,
    NoRun,
    AmbiguousRuns,
    RunUnreadable,
    GateDigest,
    PreregUnavailable,
    PreregUnreadable,
    PreregMismatch,
    MethodNotRuled,
    Timing,
    Window(WindowGap),
    MethodRejected,
}

#[derive(Debug, PartialEq, Eq)]
pub struct WindowReading {
    span: WindowSpan,
    lower_bound: RatePpb,
    median: (u128, u32),
    blocks: Vec<(i64, usize)>,
}

impl WindowReading {
    pub fn first_bar(&self) -> i64 {
        self.span.first_bar
    }
    pub fn last_bar(&self) -> i64 {
        self.span.last_bar
    }
    pub fn lower_bound_ppb(&self) -> u64 {
        self.lower_bound.0
    }
    /// 精确的 ppb 中位数整数对，仅供报告，不作准入读数。
    pub fn median_ppb(&self) -> (u128, u32) {
        self.median
    }
    pub fn samples(&self) -> usize {
        self.blocks.iter().map(|(_, n)| n).sum()
    }
    pub fn nonempty_blocks(&self) -> usize {
        self.blocks.len()
    }
    pub fn max_month_count(&self) -> usize {
        self.blocks.iter().map(|&(_, n)| n).max().unwrap_or(0)
    }
    /// 最大月桶样本数 / 窗内全部样本数，返回约分后的整数对。
    /// 口径见 #907 `p907_cost_gate_level.rs:128–146,166–170`；合格窗至少有一个样本。
    pub fn max_month_cluster(&self) -> (usize, usize) {
        let (numerator, denominator) = (self.max_month_count(), self.samples());
        let (mut gcd, mut remainder) = (denominator, numerator);
        while remainder != 0 {
            (gcd, remainder) = (remainder, gcd % remainder);
        }
        (numerator / gcd, denominator / gcd)
    }
    /// (UTC 年 × 12 + 月 - 1, 样本数)。
    pub fn month_blocks(&self) -> &[(i64, usize)] {
        &self.blocks
    }
}

#[derive(Debug, PartialEq, Eq)]
struct Dataset {
    id: SourceRef,
    sha256: String,
    span: WindowSpan,
}

struct Sample {
    event: (i64, i64),
    value: u64,
}

struct Prereg {
    domain: Domain,
    dataset: Dataset,
    gate: OriginalRef,
    frozen_at: i64,
    windows: Vec<WindowSpan>,
}

struct Run {
    domain: Domain,
    dataset: Dataset,
    gate: OriginalRef,
    prereg: OriginalRef,
    level: u32,
    pairing: String,
    method_id: String,
    started: i64,
    samples: Vec<Sample>,
}

pub(super) struct QualifiedAmplitude {
    windows: Vec<(QualifiedWindow, RatePpb)>,
    samples: Vec<Sample>,
}

impl QualifiedAmplitude {
    pub fn lower_bounds(&self) -> impl Iterator<Item = RatePpb> + '_ {
        self.windows.iter().map(|(_, bound)| *bound)
    }

    pub fn into_readings(self) -> Vec<WindowReading> {
        self.windows
            .into_iter()
            .map(|(window, lower_bound)| {
                let mut values = window_values(&window, &self.samples);
                values.sort_unstable();
                let middle = values.len() / 2;
                let median = if values.len() % 2 == 0 {
                    (
                        u128::from(values[middle - 1]) + u128::from(values[middle]),
                        2,
                    )
                } else {
                    (u128::from(values[middle]), 1)
                };
                WindowReading {
                    span: window.span,
                    lower_bound,
                    median,
                    blocks: window
                        .blocks
                        .iter()
                        .map(|block| (block.index, block.events.len()))
                        .collect(),
                }
            })
            .collect()
    }
}

fn timestamp(root: &Value, path: &str) -> Result<i64, PolicyError> {
    req(root, path)?
        .as_i64()
        .ok_or_else(|| bad(path, "须为 Unix 秒整数"))
}

fn read_span(root: &Value) -> Result<WindowSpan, PolicyError> {
    Ok(WindowSpan {
        first_bar: timestamp(root, "first_bar")?,
        last_bar: timestamp(root, "last_bar")?,
    })
}

fn dataset(root: &Value) -> Result<Dataset, PolicyError> {
    let value = req(root, "dataset")?;
    object(value, "dataset", &["id", "sha256", "first_bar", "last_bar"])?;
    Ok(Dataset {
        id: reference(root, "dataset.id")?,
        sha256: digest_string(root, "dataset.sha256")?,
        span: read_span(value)?,
    })
}

fn parse_prereg(original: &Verified) -> Result<Prereg, PolicyError> {
    let root = json(original)?;
    object(
        &root,
        "<prereg>",
        &[
            "schema",
            "domain",
            "dataset",
            "evidence_gate",
            "frozen_at",
            "windows",
        ],
    )?;
    if string(&root, "schema")? != "cost-stop/prereg-windows/1" {
        return Err(bad("schema", "不支持的预登记窗表"));
    }
    let windows = req(&root, "windows")?
        .as_array()
        .ok_or_else(|| bad("windows", "须为数组"))?
        .iter()
        .map(|item| {
            object(item, "windows[]", &["first_bar", "last_bar"])?;
            read_span(item)
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Prereg {
        domain: read_domain(&root)?,
        dataset: dataset(&root)?,
        gate: bound_ref(&root, "evidence_gate")?,
        frozen_at: timestamp(&root, "frozen_at")?,
        windows,
    })
}

fn parse_run(original: &Verified) -> Result<Run, PolicyError> {
    let root = json(original)?;
    object(
        &root,
        "<run>",
        &[
            "schema",
            "domain",
            "level",
            "pairing",
            "evidence_gate",
            "prereg",
            "dataset",
            "method_id",
            "run_started_at",
            "samples",
        ],
    )?;
    if string(&root, "schema")? != "cost-stop/amplitude-run/1" {
        return Err(bad("schema", "不支持的波幅读数原件"));
    }
    let samples = req(&root, "samples")?
        .as_array()
        .ok_or_else(|| bad("samples", "须为数组"))?
        .iter()
        .map(|item| {
            let parse = || -> Option<Sample> {
                let values = item.as_array()?;
                let [entry, exit, value] = values.as_slice() else {
                    return None;
                };
                Some(Sample {
                    event: (entry.as_i64()?, exit.as_i64()?),
                    value: value.as_u64()?,
                })
            };
            parse().ok_or_else(|| bad("samples[]", "须为 [进场秒, 出场秒, 波幅 ppb]"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Run {
        domain: read_domain(&root)?,
        dataset: dataset(&root)?,
        gate: bound_ref(&root, "evidence_gate")?,
        prereg: bound_ref(&root, "prereg")?,
        level: unsigned(&root, "level")?,
        pairing: string(&root, "pairing")?.to_owned(),
        method_id: string(&root, "method_id")?.to_owned(),
        started: timestamp(&root, "run_started_at")?,
        samples,
    })
}

fn window_values(window: &QualifiedWindow, samples: &[Sample]) -> Vec<u64> {
    window
        .blocks
        .iter()
        .flat_map(|block| block.events.iter().map(|&index| samples[index].value))
        .collect()
}

type Method = fn(&[u64]) -> Option<RatePpb>;

fn method(_id: &str) -> Option<Method> {
    // #2121 尚未裁定 A_ℓ 的生产统计量、重采样及分位计算。
    #[cfg(test)]
    if _id == "test-only/constant-window/0" {
        return Some(|values| {
            let (&first, rest) = values.split_first()?;
            rest.iter()
                .all(|&value| value == first)
                .then_some(RatePpb(first))
        });
    }
    None
}

pub(super) fn resolve(
    store: Store,
    policy: &CostStopPolicy,
    level: u32,
    consumed: &mut Vec<RecordIdentity>,
) -> Result<QualifiedAmplitude, AmplitudeGap> {
    let gate_key = policy.evidence_gate_ref();
    let gate = store
        .fetch(OriginalKind::EvidenceGate, gate_key)
        .map_err(|_| AmplitudeGap::EvidenceGateUnavailable)?;
    gate.trace(consumed);
    if !gate.approved() {
        return Err(AmplitudeGap::EvidenceGateUnavailable);
    }
    let text =
        std::str::from_utf8(gate.bytes()).map_err(|_| AmplitudeGap::EvidenceGateUnavailable)?;
    let (rules, authorized_at) = evidence_gate::parse_record(Some(text))
        .map_err(|_| AmplitudeGap::EvidenceGateUnavailable)?;
    if rules.record.label() != gate.identity().key() {
        return Err(AmplitudeGap::GateIdentity);
    }

    let mut matching = Vec::new();
    for row in store.rows_of(OriginalKind::AmplitudeRun) {
        let original = store
            .fetch(OriginalKind::AmplitudeRun, row.key)
            .map_err(|_| AmplitudeGap::RunUnreadable)?;
        original.trace(consumed);
        if !original.approved() {
            return Err(AmplitudeGap::RunUnreadable);
        }
        let run = parse_run(&original).map_err(|_| AmplitudeGap::RunUnreadable)?;
        if &run.domain == policy.domain()
            && run.level == level
            && run.pairing == "ROUNDTRIP"
            && run.gate.key() == gate_key
        {
            matching.push(run);
        }
    }
    let run = match matching.len() {
        0 => return Err(AmplitudeGap::NoRun),
        1 => matching.pop().expect("恰有一条读数"),
        _ => return Err(AmplitudeGap::AmbiguousRuns),
    };
    if run.gate.sha256() != gate.identity().sha256() {
        return Err(AmplitudeGap::GateDigest);
    }

    let original = store
        .fetch_bound(OriginalKind::PreregWindows, &run.prereg)
        .map_err(|_| AmplitudeGap::PreregUnavailable)?;
    original.trace(consumed);
    if !original.approved() {
        return Err(AmplitudeGap::PreregUnavailable);
    }
    let prereg = parse_prereg(&original).map_err(|_| AmplitudeGap::PreregUnreadable)?;
    if prereg.domain != run.domain || prereg.gate != run.gate || prereg.dataset != run.dataset {
        return Err(AmplitudeGap::PreregMismatch);
    }

    let lower_bound = method(&run.method_id).ok_or(AmplitudeGap::MethodNotRuled)?;
    let authorized_before = signed_day_end(&authorized_at).ok_or(AmplitudeGap::Timing)?;
    if run.started < authorized_before || prereg.frozen_at >= run.started {
        return Err(AmplitudeGap::Timing);
    }
    let events: Vec<_> = run.samples.iter().map(|sample| sample.event).collect();
    let windows = rules
        .qualify(
            run.dataset.span,
            run.domain.granularity(),
            &prereg.windows,
            &events,
        )
        .map_err(AmplitudeGap::Window)?
        .0;
    let windows = windows
        .into_iter()
        .map(|window| {
            let bound = lower_bound(&window_values(&window, &run.samples))
                .ok_or(AmplitudeGap::MethodRejected)?;
            Ok((window, bound))
        })
        .collect::<Result<Vec<_>, AmplitudeGap>>()?;
    Ok(QualifiedAmplitude {
        windows,
        samples: run.samples,
    })
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
