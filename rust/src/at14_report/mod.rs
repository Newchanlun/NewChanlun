//! #1418（TB-07-D，ADR 0058 §五）：AT-14 回放验收报告器（`at14-report/1`）。
//!
//! 职责为纯数据结构、边界拒收校验、fail-closed 判定、JCS+SHA-256 封存与同源 `summary.md` 渲染。
//! 不接入 launcher，不实现 H1–H4 运行本身；默认 cdylib 构建不编译（与 `lav_seal` 同门控）。

use std::collections::BTreeSet;
use std::fmt;
use std::path::{Component, Path, PathBuf};

use serde::de::Error as DeError;
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Map, Value};

use crate::lav_seal::{digest, jcs};

pub const SCHEMA_VERSION: &str = "at14-report/1";
pub const EXPECTED_MANIFEST_REVISION: &str = "production-session-manifest/1";
pub const EXPECTED_HISTORY_PROFILE_REVISION: &str = "history-input-profile/1";
pub const MODEL_BAR_BATCH_V1: &str = "history-sim/bar-batch-known-frontier/1";
pub const MODEL_STOCHASTIC_PREFIX: &str = "history-sim/stochastic-microevent/";
pub const MODEL_RECORDED_VENUE_REPLAY_V1: &str = "recorded-venue-replay/1";
pub const DEFAULT_SCHEDULER: &str = "launcher-sched/sequential/1";
pub const REPORT_JSON_FILE: &str = "at14-report.json";
pub const SUMMARY_MD_FILE: &str = "summary.md";
pub const BOUNDED_DOMAIN_MARKER: &str = "仅证有界受测域";
pub const DEFAULT_BOUNDED_DOMAIN_STATEMENT: &str =
    "仅证有界受测域；#1320 七标的十年 1min 及预注册 7/7 重型测量原义务单列保留，不以本报告 PASS 销项。";

pub const TEST_H1: &str = "dual_run_determinism_h1";
pub const TEST_H2: &str = "recovery_after_kill_h2";
pub const TEST_H3: &str = "seek_no_future_leak_h3";
pub const TEST_H4: &str = "asknown_evidence_segregation_h4";

const SHADOW_SOURCES: [&str; 9] = [
    "backtest_bin",
    "theta_backtest",
    "theta_replay",
    "theta_accept",
    "replay_compare",
    "MinimalEngine",
    "ThetaPiStream",
    "PyThetaStream",
    "run_theta_v0_pi",
];

const DIAGNOSTIC_SCHEMAS: [&str; 3] = [
    "diagnostic-fill-request/1",
    "diagnostic-fill-report/1",
    "diagnostic-fill-comparison/1",
];

/// 解析、边界拒收或落盘错误（与进入正式报告留档的非 PASS 结论严格分离）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum At14RejectError {
    InvalidManifestRevision {
        found: Option<String>,
    },
    DryRunNotAllowed,
    InvalidEvidenceClass {
        found: Option<String>,
    },
    ClockKindMismatch {
        evidence_class: EvidenceClass,
        found: Option<String>,
    },
    TestOnlyInputRejected {
        reason: String,
    },
    DiagnosticInputRejected {
        reason: String,
    },
    ShadowSessionRejected {
        source: String,
    },
    FaultScheduleNotAllowed {
        evidence_class: EvidenceClass,
    },
    InvalidModelId {
        found: String,
    },
    InvalidSeedForModel {
        model_id: String,
        seed: ReplaySeed,
    },
    InvalidField {
        field: &'static str,
        reason: String,
    },
    InvalidReportDir {
        path: String,
        reason: String,
    },
    ContentHashMismatch {
        expected: String,
        computed: String,
    },
    IoError {
        path: String,
        reason: String,
    },
}

impl fmt::Display for At14RejectError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidManifestRevision { found } => write!(
                f,
                "InvalidManifestRevision: manifest_revision must be {EXPECTED_MANIFEST_REVISION}, got {found:?}"
            ),
            Self::DryRunNotAllowed => {
                write!(f, "DryRunNotAllowed: dry-run is not a valid evidence_class")
            }
            Self::InvalidEvidenceClass { found } => write!(
                f,
                "InvalidEvidenceClass: evidence_class must be simulation|experiment|production, got {found:?}"
            ),
            Self::ClockKindMismatch {
                evidence_class,
                found,
            } => write!(
                f,
                "ClockKindMismatch: evidence_class {:?} requires clock {:?}, got {found:?}",
                evidence_class,
                evidence_class.expected_clock_kind()
            ),
            Self::TestOnlyInputRejected { reason } => {
                write!(f, "TestOnlyInputRejected: {reason}")
            }
            Self::DiagnosticInputRejected { reason } => {
                write!(f, "DiagnosticInputRejected: {reason}")
            }
            Self::ShadowSessionRejected { source } => {
                write!(f, "ShadowSessionRejected: shadow source `{source}` is forbidden")
            }
            Self::FaultScheduleNotAllowed { evidence_class } => write!(
                f,
                "FaultScheduleNotAllowed: fault_schedule is only valid for simulation, got {evidence_class:?}"
            ),
            Self::InvalidModelId { found } => {
                write!(f, "InvalidModelId: unsupported simulation model_id `{found}`")
            }
            Self::InvalidSeedForModel { model_id, seed } => write!(
                f,
                "InvalidSeedForModel: model `{model_id}` does not allow seed `{seed}`"
            ),
            Self::InvalidField { field, reason } => {
                write!(f, "InvalidField({field}): {reason}")
            }
            Self::InvalidReportDir { path, reason } => {
                write!(f, "InvalidReportDir({path}): {reason}")
            }
            Self::ContentHashMismatch { expected, computed } => write!(
                f,
                "ContentHashMismatch: report content_hash {expected} != computed {computed}"
            ),
            Self::IoError { path, reason } => write!(f, "IoError({path}): {reason}"),
        }
    }
}

impl std::error::Error for At14RejectError {}

/// 正本三值证据类（ADR 0038:74、ADR 0056:23-27、ADR 0058 §一.3）；`dry-run` 不可表示。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceClass {
    Simulation,
    Experiment,
    Production,
}

impl EvidenceClass {
    /// 直接解析 `production-session-manifest/1` 的 `profile` 字段取值（`production_session.rs:25,131`）。
    pub fn parse_profile(profile: &str) -> Result<Self, At14RejectError> {
        match profile {
            "simulation" => Ok(Self::Simulation),
            "experiment" => Ok(Self::Experiment),
            "production" => Ok(Self::Production),
            "dry-run" => Err(At14RejectError::DryRunNotAllowed),
            other => Err(At14RejectError::InvalidEvidenceClass {
                found: Some(other.to_string()),
            }),
        }
    }

    /// 从 `production-session-manifest/1` 清单 JSON 读取既有 `profile` 字段并校验。
    pub fn from_session_manifest(manifest: &Value) -> Result<Self, At14RejectError> {
        let rev = manifest.get("manifest_revision").and_then(Value::as_str);
        if rev != Some(EXPECTED_MANIFEST_REVISION) {
            return Err(At14RejectError::InvalidManifestRevision {
                found: rev.map(str::to_string),
            });
        }
        let Some(profile) = manifest.get("profile").and_then(Value::as_str) else {
            return Err(At14RejectError::InvalidEvidenceClass { found: None });
        };
        Self::parse_profile(profile)
    }

    /// ADR 0056:52：时钟 kind 由 `evidence_class` 一一推出，不设可选值。
    pub fn expected_clock_kind(self) -> ClockKind {
        match self {
            Self::Simulation => ClockKind::LogicalBarV1,
            Self::Experiment | Self::Production => ClockKind::System,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Simulation => "simulation",
            Self::Experiment => "experiment",
            Self::Production => "production",
        }
    }
}

/// 正式会话时钟种类封闭枚举（ADR 0056:52）；`TestOnly` 时钟不可表示。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ClockKind {
    #[serde(rename = "logical-bar/1")]
    LogicalBarV1,
    #[serde(rename = "System")]
    System,
}

impl ClockKind {
    pub fn parse_for(
        evidence_class: EvidenceClass,
        raw: Option<&str>,
    ) -> Result<Self, At14RejectError> {
        match raw {
            Some("TestOnly") => Err(At14RejectError::TestOnlyInputRejected {
                reason: "clock.kind=TestOnly is forbidden in AT-14 reports".into(),
            }),
            Some("logical-bar/1") if evidence_class == EvidenceClass::Simulation => {
                Ok(Self::LogicalBarV1)
            }
            Some("System")
                if matches!(
                    evidence_class,
                    EvidenceClass::Experiment | EvidenceClass::Production
                ) =>
            {
                Ok(Self::System)
            }
            other => Err(At14RejectError::ClockKindMismatch {
                evidence_class,
                found: other.map(str::to_string),
            }),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::LogicalBarV1 => "logical-bar/1",
            Self::System => "System",
        }
    }
}

/// 合法模拟模型标识（ADR 0033:18、ADR 0056:69）；诊断模型 `adr0018-integer-bar/1` 不可表示。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SimulationModelId {
    BarBatchKnownFrontierV1,
    RecordedVenueReplayV1,
    StochasticMicroevent { revision: String },
}

impl SimulationModelId {
    pub fn parse(raw: &str) -> Result<Self, At14RejectError> {
        if raw == crate::diagnostic_fill::MODEL_ID {
            return Err(At14RejectError::DiagnosticInputRejected {
                reason: format!("diagnostic fill model `{raw}` cannot enter AT-14"),
            });
        }
        if raw == MODEL_BAR_BATCH_V1 {
            return Ok(Self::BarBatchKnownFrontierV1);
        }
        if raw == MODEL_RECORDED_VENUE_REPLAY_V1 {
            return Ok(Self::RecordedVenueReplayV1);
        }
        if let Some(rev) = raw.strip_prefix(MODEL_STOCHASTIC_PREFIX) {
            if !rev.is_empty() && !rev.chars().any(char::is_whitespace) {
                return Ok(Self::StochasticMicroevent {
                    revision: rev.to_string(),
                });
            }
        }
        Err(At14RejectError::InvalidModelId {
            found: raw.to_string(),
        })
    }

    pub fn as_string(&self) -> String {
        match self {
            Self::BarBatchKnownFrontierV1 => MODEL_BAR_BATCH_V1.to_string(),
            Self::RecordedVenueReplayV1 => MODEL_RECORDED_VENUE_REPLAY_V1.to_string(),
            Self::StochasticMicroevent { revision } => {
                format!("{MODEL_STOCHASTIC_PREFIX}{revision}")
            }
        }
    }

    pub fn is_stochastic(&self) -> bool {
        matches!(self, Self::StochasticMicroevent { .. })
    }

    /// ADR 0033:18：`stochastic-microevent` 待标定，当前不可作为 PASS 依据。
    pub fn is_uncalibrated(&self) -> bool {
        self.is_stochastic()
    }
}

impl Serialize for SimulationModelId {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.as_string())
    }
}

impl<'de> Deserialize<'de> for SimulationModelId {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        Self::parse(&raw).map_err(DeError::custom)
    }
}

/// 回放随机种子（ADR 0033:18）：确定性模型取 `none`，随机模型取非负 `i64`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReplaySeed {
    None,
    Integer(u64),
}

impl ReplaySeed {
    pub fn integer(value: u64) -> Result<Self, At14RejectError> {
        if value > i64::MAX as u64 {
            return Err(At14RejectError::InvalidField {
                field: "seed",
                reason: "seed exceeds nonnegative i64 range".into(),
            });
        }
        Ok(Self::Integer(value))
    }

    pub fn validate_for(&self, model: &SimulationModelId) -> Result<(), At14RejectError> {
        match (model.is_stochastic(), self) {
            (false, Self::None) => Ok(()),
            (true, Self::Integer(v)) if *v <= i64::MAX as u64 => Ok(()),
            _ => Err(At14RejectError::InvalidSeedForModel {
                model_id: model.as_string(),
                seed: *self,
            }),
        }
    }
}

impl fmt::Display for ReplaySeed {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::None => f.write_str("none"),
            Self::Integer(v) => write!(f, "{v}"),
        }
    }
}

impl Serialize for ReplaySeed {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Self::None => serializer.serialize_str("none"),
            Self::Integer(v) => serializer.serialize_u64(*v),
        }
    }
}

impl<'de> Deserialize<'de> for ReplaySeed {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let v = Value::deserialize(deserializer)?;
        match v {
            Value::String(ref s) if s == "none" => Ok(Self::None),
            Value::Number(ref n) => {
                let u = n
                    .as_u64()
                    .ok_or_else(|| DeError::custom("seed must be \"none\" or nonnegative i64"))?;
                Self::integer(u).map_err(DeError::custom)
            }
            _ => Err(DeError::custom("seed must be \"none\" or nonnegative i64")),
        }
    }
}

/// 容量来源枚举（ADR 0033:22, :27）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CapacitySource {
    ScenarioContract,
    BarVolumeDerived,
}

impl CapacitySource {
    /// ADR 0033:27：`bar_volume_derived` 待标定，选中时容量记 Unknown ⟹ AwaitingPolicy。
    pub fn is_uncalibrated(self) -> bool {
        matches!(self, Self::BarVolumeDerived)
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::ScenarioContract => "scenario_contract",
            Self::BarVolumeDerived => "bar_volume_derived",
        }
    }
}

/// 数据源可调字段（ADR 0052:306-308）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum InputSource {
    #[serde(rename = "massive-stock-tick/1")]
    MassiveStockTickV1,
    #[serde(rename = "databento-equs-mini-tick/1")]
    DatabentoEqusMiniTickV1,
}

impl InputSource {
    /// ADR 0052:308：采用 EQUS.MINI 时报告必须标注「校验源」。
    pub fn verification_source_label(self) -> Option<&'static str> {
        match self {
            Self::MassiveStockTickV1 => None,
            Self::DatabentoEqusMiniTickV1 => Some("校验源"),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::MassiveStockTickV1 => "massive-stock-tick/1",
            Self::DatabentoEqusMiniTickV1 => "databento-equs-mini-tick/1",
        }
    }
}

/// ADR 0051:245 政策引用形状。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PolicyRef {
    pub policy_id: String,
    pub version: String,
    pub profile_id: Option<String>,
    pub content_hash: String,
}

/// ADR 0051:246 模型引用形状。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelRef {
    pub model_id: String,
    pub revision: String,
    pub content_hash: String,
}

/// 规则版本项。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RuleVersionRef {
    pub rule_id: String,
    pub version: String,
    pub content_hash: String,
}

/// ADR 0058 §五.2 规则/政策/模型版本集。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VersionSet {
    pub rule_versions: Vec<RuleVersionRef>,
    pub policy_refs: Vec<PolicyRef>,
    pub model_ref: ModelRef,
}

/// ADR 0058 §五.2 构建指纹（commit、lockfile hash、features）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BuildFingerprint {
    pub commit: String,
    pub lockfile_hash: String,
    pub features: BTreeSet<String>,
}

/// ADR 0052:311 `input_range{symbol[], from, to}`。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InputRange {
    pub symbols: Vec<String>,
    pub from: String,
    pub to: String,
}

/// ADR 0058 §五.2 实际负载（`input_range`、bar 数、checkpoint 数）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActualLoad {
    pub input_range: InputRange,
    pub bar_count: u64,
    pub checkpoint_count: u64,
}

/// ADR 0052:300 故障触发点。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "value",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum FaultTriggerAt {
    BarIndex(u64),
    Cut(String),
}

/// ADR 0052:300 故障域集合。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "domain",
    content = "chong_id",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum FaultDomain {
    S,
    E,
    Bi(String),
    X,
    Transport,
    Store,
}

/// ADR 0052:229-240, :300 故障种类（9 值完整覆盖 SPEC :438 八项）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FaultKind {
    CrashBeforeCommit,
    CrashAfterCommit,
    ReorderReports,
    Drop,
    Duplicate,
    Restart,
    WriterEpochBump,
    StoreUnreadable,
    StoreWriteFailure,
}

/// ADR 0052:300 `scenario_contract.fault_schedule[]` 单项。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FaultScheduleEntry {
    pub at: FaultTriggerAt,
    pub target: FaultDomain,
    pub kind: FaultKind,
}

/// ADR 0052:302 运行时「调度轨迹」单步。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduleTraceEntry {
    pub step: u64,
    pub bar_index: u64,
    pub stage: String,
    pub triggered_fault: Option<FaultKind>,
    pub detail: String,
}

/// 10-26 增量：模型、随机种子与容量来源配置（#1418 10-26 评论、ADR 0033:18/:22/:27）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ModelExecutionConfig {
    pub model_id: SimulationModelId,
    pub seed: ReplaySeed,
    pub capacity_source: CapacitySource,
}

/// 10-26 增量：L1 随机模拟与 L0 假设分列计数（#1418 10-26 评论、ADR 0033:18/:24/:27）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssumptionCounts {
    pub stochastic_l1_count: u64,
    pub bar_volume_derived_l0_count: u64,
    pub unconstrained_capacity_l0_count: u64,
}

/// 10-26 增量：实际双跑五元组（ADR 0038:29/:47、ADR 0052:271/:302/:349）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DualRunFiveTuple {
    pub input_profile_hash: String,
    pub input_events_hash: String,
    pub fault_schedule_hash: String,
    pub schedule_trace_hash: String,
    pub policy_version: String,
    pub model_id: String,
    pub model_revision: String,
    pub seed: ReplaySeed,
    pub scheduler: String,
}

/// ADR 0058 §五.2 `profile`/`manifest` 回显与 hash（含 `evidence_class`、`clock.kind`、`scheduler`）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionEcho {
    pub manifest_revision: String,
    pub manifest_hash: String,
    pub manifest_echo: Value,
    pub profile_revision: String,
    pub profile_hash: String,
    pub profile_echo: Value,
    pub evidence_class: EvidenceClass,
    pub clock_kind: ClockKind,
    pub scheduler: String,
}

/// 单项 H1–H4 oracle 的输入状态。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OracleRunInput {
    Executed {
        diff_count: u64,
        diff_summary: String,
    },
    Unexecuted {
        reason: String,
    },
    MissingCapability {
        capability: String,
    },
}

/// 单项 H1–H4 oracle 的具名输出状态（区分通过、运行失配、未执行与缺能力）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum OracleResult {
    Pass,
    Fail,
    Unexecuted,
    MissingCapability,
}

impl OracleResult {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Fail => "FAIL",
            Self::Unexecuted => "UNEXECUTED",
            Self::MissingCapability => "MISSING_CAPABILITY",
        }
    }
}

/// ADR 0058 §五.2 `h1`..`h4` 报告记录项。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OracleEntry {
    pub test_name: String,
    pub result: OracleResult,
    pub diff_count: u64,
    pub diff_summary: String,
}

/// 单面行数与 diff 摘要。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FaceSummary {
    pub row_count: u64,
    pub diff_count: u64,
    pub diff_summary: String,
}

/// ADR 0038:49-54 六面逐面行数与 diff 摘要；六字段固定不可缺面。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SixFacesSummary {
    pub s_structure_snapshot: FaceSummary,
    pub b_chong_ledgers: FaceSummary,
    pub e_responsibility: FaceSummary,
    pub orders_and_fills: FaceSummary,
    pub physical_positions: FaceSummary,
    pub external_effect_journal: FaceSummary,
}

/// FU-14 判据 (a) 原始观测输入（ADR 0052:288）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CriterionAInput {
    Observed {
        root_process: String,
        child_domains: BTreeSet<String>,
    },
    Unexecuted {
        reason: String,
    },
    MissingCapability {
        capability: String,
    },
}

/// FU-14 判据 (b) 原始观测输入：六域输入与产出计数（ADR 0052:289）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CriterionBInput {
    Observed {
        structure_objects: u64,
        funding_resolutions: u64,
        commands: u64,
        simulated_fills: u64,
        position_projections: u64,
        fault_records: u64,
    },
    Unexecuted {
        reason: String,
    },
    MissingCapability {
        capability: String,
    },
}

/// FU-14 判据 (c) 原始观测输入：域外请求终态与旧臂零调用（ADR 0052:290）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CriterionCInput {
    Observed {
        out_of_domain_requests: u64,
        model_order_unspecified_terminals: u64,
        legacy_arm_calls: u64,
    },
    Unexecuted {
        reason: String,
    },
    MissingCapability {
        capability: String,
    },
}

/// FU-14 判据 (d) 原始观测输入：影子产出只标组件证据不进判据（ADR 0052:291）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CriterionDInput {
    Observed {
        shadow_outputs_in_verdict: u64,
        untagged_shadow_outputs: u64,
    },
    Unexecuted {
        reason: String,
    },
    MissingCapability {
        capability: String,
    },
}

/// ADR 0052:288-291 四条判据的原始输入集合。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fu14CriteriaInput {
    pub a: CriterionAInput,
    pub b: CriterionBInput,
    pub c: CriterionCInput,
    pub d: CriterionDInput,
}

/// 单项判据的具名四态结果。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    tag = "result",
    rename_all = "SCREAMING_SNAKE_CASE",
    deny_unknown_fields
)]
pub enum CheckOutcome {
    Pass,
    Unexecuted { detail: String },
    MissingCapability { detail: String },
    Mismatch { detail: String },
}

impl CheckOutcome {
    pub fn label(&self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Unexecuted { .. } => "UNEXECUTED",
            Self::MissingCapability { .. } => "MISSING_CAPABILITY",
            Self::Mismatch { .. } => "MISMATCH",
        }
    }

    pub fn detail(&self) -> Option<&str> {
        match self {
            Self::Pass => None,
            Self::Unexecuted { detail }
            | Self::MissingCapability { detail }
            | Self::Mismatch { detail } => Some(detail.as_str()),
        }
    }
}

/// ADR 0052:288-291 四项判据结果。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Fu14GateResults {
    pub a_launcher_process_tree: CheckOutcome,
    pub b_six_domains_nonempty: CheckOutcome,
    pub c_model_order_unspecified_no_legacy: CheckOutcome,
    pub d_shadow_component_only: CheckOutcome,
}

/// 报告整体判定结论：把「未执行」「缺能力」「失配」分为各自具名的非 PASS 变体。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "SCREAMING_SNAKE_CASE", deny_unknown_fields)]
pub enum ReportVerdict {
    Pass,
    Unexecuted {
        items: Vec<String>,
    },
    MissingCapability {
        items: Vec<String>,
    },
    Mismatch {
        items: Vec<String>,
    },
    MultipleFailures {
        unexecuted: Vec<String>,
        missing_capability: Vec<String>,
        mismatch: Vec<String>,
    },
}

impl ReportVerdict {
    pub fn is_pass(&self) -> bool {
        matches!(self, Self::Pass)
    }

    pub fn label(&self) -> &'static str {
        match self {
            Self::Pass => "PASS",
            Self::Unexecuted { .. } => "UNEXECUTED",
            Self::MissingCapability { .. } => "MISSING_CAPABILITY",
            Self::Mismatch { .. } => "MISMATCH",
            Self::MultipleFailures { .. } => "MULTIPLE_FAILURES",
        }
    }
}

/// 构建 AT-14 报告的原始边界输入；经 [`seal_report`] 校验、判定并封存后方成为 [`SealedAt14Report`]。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct At14ReportInput {
    pub producer: String,
    pub manifest_json: Value,
    pub profile_json: Value,
    pub scheduler: String,
    pub build_fingerprint: BuildFingerprint,
    pub version_set: VersionSet,
    pub capability_manifest_hash: String,
    pub model_execution: ModelExecutionConfig,
    pub dual_run_tuple: DualRunFiveTuple,
    pub actual_load: ActualLoad,
    pub fault_schedule: Vec<FaultScheduleEntry>,
    pub schedule_trace: Vec<ScheduleTraceEntry>,
    pub h1: Option<OracleRunInput>,
    pub h2: Option<OracleRunInput>,
    pub h3: Option<OracleRunInput>,
    pub h4: Option<OracleRunInput>,
    pub six_faces: SixFacesSummary,
    pub fu14_criteria: Fu14CriteriaInput,
    pub model_order_unspecified_count: u64,
    pub diagnostic_not_production_count: u64,
    pub input_source_unavailable_count: u64,
    pub input_source: InputSource,
    pub assumption_counts: AssumptionCounts,
    pub extra_unexecuted: Vec<String>,
    pub bounded_domain_statement: String,
    pub ci_run_id: Option<String>,
    pub review_binding: Option<String>,
}

/// 参与 `content_hash` 计算的 `at14-report/1` 主体（不含 `content_hash` 自身）。
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct At14ReportBody {
    pub schema_version: String,
    pub verdict: ReportVerdict,
    pub session: SessionEcho,
    pub build_fingerprint: BuildFingerprint,
    pub version_set: VersionSet,
    pub capability_manifest_hash: String,
    pub model_execution: ModelExecutionConfig,
    pub dual_run_tuple: DualRunFiveTuple,
    pub actual_load: ActualLoad,
    pub fault_schedule: Vec<FaultScheduleEntry>,
    pub schedule_trace: Vec<ScheduleTraceEntry>,
    pub h1: OracleEntry,
    pub h2: OracleEntry,
    pub h3: OracleEntry,
    pub h4: OracleEntry,
    pub six_faces: SixFacesSummary,
    pub fu14_gates: Fu14GateResults,
    pub model_order_unspecified_count: u64,
    pub diagnostic_not_production_count: u64,
    pub input_source_unavailable_count: u64,
    pub input_source: InputSource,
    pub verification_source_label: Option<String>,
    pub assumption_counts: AssumptionCounts,
    pub unexecuted: Vec<String>,
    pub bounded_domain_statement: String,
    pub ci_run_id: Option<String>,
    pub review_binding: Option<String>,
}

/// 经完整拒收校验、判定求值与 JCS+SHA-256 封存的不可变报告实体。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SealedAt14Report {
    body: At14ReportBody,
    content_hash: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SealedAt14Wire {
    #[serde(flatten)]
    body: At14ReportBody,
    content_hash: String,
}

/// `summary.md` 渲染器专用的只读投影视图：仅携带已计算 `verdict` 与展示信息，
/// 在签名上不暴露任何判定所需的原始输入。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SummaryView<'a> {
    pub schema_version: &'a str,
    pub content_hash: &'a str,
    pub verdict: &'a ReportVerdict,
    pub evidence_class: EvidenceClass,
    pub clock_kind: ClockKind,
    pub scheduler: &'a str,
    pub manifest_hash: &'a str,
    pub profile_hash: &'a str,
    pub capability_manifest_hash: &'a str,
    pub commit: &'a str,
    pub lockfile_hash: &'a str,
    pub features: &'a BTreeSet<String>,
    pub model_id: String,
    pub model_revision: &'a str,
    pub seed: ReplaySeed,
    pub capacity_source: CapacitySource,
    pub input_source: InputSource,
    pub verification_source_label: Option<&'a str>,
    pub dual_run_tuple: &'a DualRunFiveTuple,
    pub actual_load: &'a ActualLoad,
    pub fault_schedule_count: usize,
    pub schedule_trace_count: usize,
    pub oracle_rows: [OracleSummaryRow<'a>; 4],
    pub six_face_rows: [FaceSummaryRow<'a>; 6],
    pub fu14_rows: [GateSummaryRow<'a>; 4],
    pub model_order_unspecified_count: u64,
    pub diagnostic_not_production_count: u64,
    pub input_source_unavailable_count: u64,
    pub assumption_counts: AssumptionCounts,
    pub unexecuted: &'a [String],
    pub bounded_domain_statement: &'a str,
    pub ci_run_id: Option<&'a str>,
    pub review_binding: Option<&'a str>,
    _sealed: (),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OracleSummaryRow<'a> {
    pub test_name: &'a str,
    pub result_label: &'static str,
    pub diff_summary: &'a str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FaceSummaryRow<'a> {
    pub face_name: &'static str,
    pub row_count: u64,
    pub diff_summary: &'a str,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GateSummaryRow<'a> {
    pub gate_id: &'static str,
    pub outcome_label: &'static str,
    pub detail: Option<&'a str>,
}

/// 经规范校验的 AT-14 报告落盘目录（`.chanlun/review-results/issue1304-at14-<YYYYMMDD>-<short-sha>`）。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct At14ReportDir {
    path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmittedReportFiles {
    pub dir: PathBuf,
    pub report_json: PathBuf,
    pub summary_md: PathBuf,
}

impl At14ReportDir {
    /// 按 ADR 0058 §五.3 构造绑定 `#1304` 的标准目录路径。
    pub fn issue1304(
        review_results_dir: impl AsRef<Path>,
        yyyymmdd: &str,
        short_sha: &str,
    ) -> Result<Self, At14RejectError> {
        let dir_name = format!("issue1304-at14-{yyyymmdd}-{short_sha}");
        Self::parse(review_results_dir.as_ref().join(dir_name))
    }

    /// 校验目录名符合 `issue1304-at14-<YYYYMMDD>-<short-sha>`（或 ADR 0058 §五.3 留档说明的 `issue1366-at14-...`），
    /// 并禁止路径穿越。
    pub fn parse(path: impl Into<PathBuf>) -> Result<Self, At14RejectError> {
        let path = path.into();
        if path.components().any(|c| matches!(c, Component::ParentDir)) {
            return Err(At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: "parent directory traversal is forbidden".into(),
            });
        }
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            return Err(At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: "missing directory name".into(),
            });
        };
        let rest = name
            .strip_prefix("issue1304-at14-")
            .or_else(|| name.strip_prefix("issue1366-at14-"))
            .ok_or_else(|| At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: "directory name must start with issue1304-at14- or issue1366-at14-".into(),
            })?;
        let Some((date, sha)) = rest.split_once('-') else {
            return Err(At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: "directory name must end with <YYYYMMDD>-<short-sha>".into(),
            });
        };
        if date.len() != 8 || !date.bytes().all(|b| b.is_ascii_digit()) {
            return Err(At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: format!("invalid YYYYMMDD segment `{date}`"),
            });
        }
        if sha.len() < 7
            || sha.len() > 40
            || !sha
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(At14RejectError::InvalidReportDir {
                path: path.display().to_string(),
                reason: format!("invalid lowercase hex short-sha `{sha}`"),
            });
        }
        Ok(Self { path })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

fn jcs_sha256(value: &Value) -> String {
    digest::sha256_hex(&jcs::canonical_bytes(value))
}

fn jcs_sha256_serializable<T: Serialize>(value: &T) -> Result<String, At14RejectError> {
    let json_val = serde_json::to_value(value).map_err(|e| At14RejectError::InvalidField {
        field: "serialization",
        reason: e.to_string(),
    })?;
    Ok(jcs_sha256(&json_val))
}

fn require_non_empty(field: &'static str, value: &str) -> Result<(), At14RejectError> {
    if value.trim().is_empty() {
        return Err(At14RejectError::InvalidField {
            field,
            reason: "must not be empty".into(),
        });
    }
    Ok(())
}

fn require_opt_non_empty(
    field: &'static str,
    value: &Option<String>,
) -> Result<(), At14RejectError> {
    if let Some(s) = value {
        if s.trim().is_empty() {
            return Err(At14RejectError::InvalidField {
                field,
                reason: "optional field must not be blank when Some".into(),
            });
        }
    }
    Ok(())
}

fn reject_shadow_producer(
    producer: &str,
    manifest: &Value,
    profile: &Value,
) -> Result<(), At14RejectError> {
    require_non_empty("producer", producer)?;
    for shadow in SHADOW_SOURCES {
        if producer == shadow || producer.contains(shadow) {
            return Err(At14RejectError::ShadowSessionRejected {
                source: producer.to_string(),
            });
        }
    }
    for doc in [manifest, profile] {
        for key in [
            "provenance",
            "evidence_kind",
            "producer",
            "launcher",
            "engine",
        ] {
            if let Some(val) = doc.get(key).and_then(Value::as_str) {
                if val == "component_evidence"
                    || val == "shadow"
                    || SHADOW_SOURCES.iter().any(|s| val == *s || val.contains(s))
                {
                    return Err(At14RejectError::ShadowSessionRejected {
                        source: format!("{key}={val}"),
                    });
                }
            }
        }
    }
    Ok(())
}

fn reject_diagnostic_artifact(doc: &Value, label: &str) -> Result<(), At14RejectError> {
    if let Some(schema) = doc.get("schema").and_then(Value::as_str) {
        if DIAGNOSTIC_SCHEMAS.contains(&schema) {
            return Err(At14RejectError::DiagnosticInputRejected {
                reason: format!("{label} carries diagnostic schema `{schema}`"),
            });
        }
    }
    if let Some(mode) = doc.get("mode").and_then(Value::as_str) {
        if mode == "diagnostic" {
            return Err(At14RejectError::DiagnosticInputRejected {
                reason: format!("{label} carries mode=diagnostic"),
            });
        }
    }
    if let Some(model_id) = doc.get("model_id").and_then(Value::as_str) {
        if model_id == crate::diagnostic_fill::MODEL_ID {
            return Err(At14RejectError::DiagnosticInputRejected {
                reason: format!("{label} references diagnostic model `{model_id}`"),
            });
        }
    }
    if let Some(fill_rule) = doc.get("fill_rule") {
        if fill_rule == "Touch" || fill_rule == "touch" {
            return Err(At14RejectError::DiagnosticInputRejected {
                reason: format!("{label} uses diagnostic fill_rule=touch"),
            });
        }
    }
    Ok(())
}

fn reject_testonly_artifact(
    manifest: &Value,
    profile: &Value,
    evidence_class: EvidenceClass,
) -> Result<(), At14RejectError> {
    if profile.get("kind").and_then(Value::as_str) == Some("TestOnly") {
        return Err(At14RejectError::TestOnlyInputRejected {
            reason: "profile input declares kind=TestOnly".into(),
        });
    }
    if manifest.get("kind").and_then(Value::as_str) == Some("TestOnly") {
        return Err(At14RejectError::TestOnlyInputRejected {
            reason: "manifest declares kind=TestOnly".into(),
        });
    }
    if manifest
        .get("structure_source")
        .and_then(|s| s.get("category"))
        .and_then(Value::as_str)
        == Some("TestOnlyStructure")
    {
        return Err(At14RejectError::TestOnlyInputRejected {
            reason: "manifest structure_source.category is TestOnlyStructure".into(),
        });
    }
    if manifest
        .get("clock")
        .and_then(|c| c.get("kind"))
        .and_then(Value::as_str)
        == Some("TestOnly")
    {
        return Err(At14RejectError::TestOnlyInputRejected {
            reason: "manifest clock.kind is TestOnly".into(),
        });
    }
    if profile
        .get("clock")
        .and_then(|c| c.get("kind"))
        .and_then(Value::as_str)
        == Some("TestOnly")
    {
        return Err(At14RejectError::TestOnlyInputRejected {
            reason: "profile clock.kind is TestOnly".into(),
        });
    }
    if let Some(rev) = profile.get("schema_revision").and_then(Value::as_str) {
        if rev.starts_with("tb03b-finance/") {
            return Err(At14RejectError::TestOnlyInputRejected {
                reason: format!("profile schema_revision `{rev}` is a component finance fixture, not {EXPECTED_HISTORY_PROFILE_REVISION}"),
            });
        }
        if evidence_class == EvidenceClass::Simulation && rev != EXPECTED_HISTORY_PROFILE_REVISION {
            return Err(At14RejectError::TestOnlyInputRejected {
                reason: format!("simulation profile schema_revision must be {EXPECTED_HISTORY_PROFILE_REVISION}, got `{rev}`"),
            });
        }
    } else if evidence_class == EvidenceClass::Simulation {
        return Err(At14RejectError::InvalidField {
            field: "profile_json.schema_revision",
            reason: format!("simulation profile must declare schema_revision={EXPECTED_HISTORY_PROFILE_REVISION}"),
        });
    }
    Ok(())
}

fn evaluate_oracle(
    test_name: &'static str,
    input: Option<OracleRunInput>,
    unexecuted: &mut BTreeSet<String>,
    missing_capability: &mut BTreeSet<String>,
    mismatch: &mut BTreeSet<String>,
    report_unexecuted: &mut BTreeSet<String>,
) -> OracleEntry {
    match input {
        None => {
            unexecuted.insert(format!("{test_name}: missing"));
            report_unexecuted.insert(test_name.to_string());
            OracleEntry {
                test_name: test_name.to_string(),
                result: OracleResult::Unexecuted,
                diff_count: 0,
                diff_summary: "missing oracle run".to_string(),
            }
        }
        Some(OracleRunInput::Unexecuted { reason }) => {
            let reason = if reason.trim().is_empty() {
                "unexecuted".to_string()
            } else {
                reason
            };
            unexecuted.insert(format!("{test_name}: {reason}"));
            report_unexecuted.insert(test_name.to_string());
            OracleEntry {
                test_name: test_name.to_string(),
                result: OracleResult::Unexecuted,
                diff_count: 0,
                diff_summary: reason,
            }
        }
        Some(OracleRunInput::MissingCapability { capability }) => {
            let capability = if capability.trim().is_empty() {
                "unspecified capability".to_string()
            } else {
                capability
            };
            missing_capability.insert(format!("{test_name}: {capability}"));
            OracleEntry {
                test_name: test_name.to_string(),
                result: OracleResult::MissingCapability,
                diff_count: 0,
                diff_summary: capability,
            }
        }
        Some(OracleRunInput::Executed {
            diff_count,
            diff_summary,
        }) => {
            if diff_count == 0 {
                OracleEntry {
                    test_name: test_name.to_string(),
                    result: OracleResult::Pass,
                    diff_count: 0,
                    diff_summary,
                }
            } else {
                let summary = if diff_summary.trim().is_empty() {
                    format!("diff_count={diff_count}")
                } else {
                    diff_summary
                };
                mismatch.insert(format!("{test_name}: {summary}"));
                OracleEntry {
                    test_name: test_name.to_string(),
                    result: OracleResult::Fail,
                    diff_count,
                    diff_summary: summary,
                }
            }
        }
    }
}

fn evaluate_fu14_a(
    input: CriterionAInput,
    unexecuted: &mut BTreeSet<String>,
    missing_capability: &mut BTreeSet<String>,
    mismatch: &mut BTreeSet<String>,
    report_unexecuted: &mut BTreeSet<String>,
) -> CheckOutcome {
    match input {
        CriterionAInput::Unexecuted { reason } => {
            unexecuted.insert(format!("fu14(a): {reason}"));
            report_unexecuted.insert("fu14(a)".to_string());
            CheckOutcome::Unexecuted { detail: reason }
        }
        CriterionAInput::MissingCapability { capability } => {
            missing_capability.insert(format!("fu14(a): {capability}"));
            CheckOutcome::MissingCapability { detail: capability }
        }
        CriterionAInput::Observed {
            root_process,
            child_domains,
        } => {
            let has_s = child_domains.contains("S");
            let has_e = child_domains.contains("E");
            let has_x = child_domains.contains("X");
            let has_b = child_domains
                .iter()
                .any(|d| d == "B" || d.starts_with("B:"));
            if root_process == "production_session" && has_s && has_e && has_b && has_x {
                CheckOutcome::Pass
            } else {
                let detail = format!(
                    "root={root_process}, domains={child_domains:?} (requires production_session with S,E,B*,X)"
                );
                mismatch.insert(format!("fu14(a): {detail}"));
                CheckOutcome::Mismatch { detail }
            }
        }
    }
}

fn evaluate_fu14_b(
    input: CriterionBInput,
    unexecuted: &mut BTreeSet<String>,
    missing_capability: &mut BTreeSet<String>,
    mismatch: &mut BTreeSet<String>,
    report_unexecuted: &mut BTreeSet<String>,
) -> CheckOutcome {
    match input {
        CriterionBInput::Unexecuted { reason } => {
            unexecuted.insert(format!("fu14(b): {reason}"));
            report_unexecuted.insert("fu14(b)".to_string());
            CheckOutcome::Unexecuted { detail: reason }
        }
        CriterionBInput::MissingCapability { capability } => {
            missing_capability.insert(format!("fu14(b): {capability}"));
            CheckOutcome::MissingCapability { detail: capability }
        }
        CriterionBInput::Observed {
            structure_objects,
            funding_resolutions,
            commands,
            simulated_fills,
            position_projections,
            fault_records,
        } => {
            let mut empty_domains = Vec::new();
            for (name, count) in [
                ("structure", structure_objects),
                ("funding", funding_resolutions),
                ("orders", commands),
                ("simulated_fills", simulated_fills),
                ("positions", position_projections),
                ("faults", fault_records),
            ] {
                if count == 0 {
                    empty_domains.push(name);
                }
            }
            if empty_domains.is_empty() {
                CheckOutcome::Pass
            } else {
                let detail = format!("empty domains: {}", empty_domains.join(", "));
                mismatch.insert(format!("fu14(b): {detail}"));
                CheckOutcome::Mismatch { detail }
            }
        }
    }
}

fn evaluate_fu14_c(
    input: CriterionCInput,
    unexecuted: &mut BTreeSet<String>,
    missing_capability: &mut BTreeSet<String>,
    mismatch: &mut BTreeSet<String>,
    report_unexecuted: &mut BTreeSet<String>,
) -> CheckOutcome {
    match input {
        CriterionCInput::Unexecuted { reason } => {
            unexecuted.insert(format!("fu14(c): {reason}"));
            report_unexecuted.insert("fu14(c)".to_string());
            CheckOutcome::Unexecuted { detail: reason }
        }
        CriterionCInput::MissingCapability { capability } => {
            missing_capability.insert(format!("fu14(c): {capability}"));
            CheckOutcome::MissingCapability { detail: capability }
        }
        CriterionCInput::Observed {
            out_of_domain_requests,
            model_order_unspecified_terminals,
            legacy_arm_calls,
        } => {
            if out_of_domain_requests > 0
                && model_order_unspecified_terminals == out_of_domain_requests
                && legacy_arm_calls == 0
            {
                CheckOutcome::Pass
            } else {
                let detail = format!(
                    "out_of_domain_requests={out_of_domain_requests}, terminals={model_order_unspecified_terminals}, legacy_arm_calls={legacy_arm_calls}"
                );
                mismatch.insert(format!("fu14(c): {detail}"));
                CheckOutcome::Mismatch { detail }
            }
        }
    }
}

fn evaluate_fu14_d(
    input: CriterionDInput,
    unexecuted: &mut BTreeSet<String>,
    missing_capability: &mut BTreeSet<String>,
    mismatch: &mut BTreeSet<String>,
    report_unexecuted: &mut BTreeSet<String>,
) -> CheckOutcome {
    match input {
        CriterionDInput::Unexecuted { reason } => {
            unexecuted.insert(format!("fu14(d): {reason}"));
            report_unexecuted.insert("fu14(d)".to_string());
            CheckOutcome::Unexecuted { detail: reason }
        }
        CriterionDInput::MissingCapability { capability } => {
            missing_capability.insert(format!("fu14(d): {capability}"));
            CheckOutcome::MissingCapability { detail: capability }
        }
        CriterionDInput::Observed {
            shadow_outputs_in_verdict,
            untagged_shadow_outputs,
        } => {
            if shadow_outputs_in_verdict == 0 && untagged_shadow_outputs == 0 {
                CheckOutcome::Pass
            } else {
                let detail = format!(
                    "shadow_outputs_in_verdict={shadow_outputs_in_verdict}, untagged_shadow_outputs={untagged_shadow_outputs}"
                );
                mismatch.insert(format!("fu14(d): {detail}"));
                CheckOutcome::Mismatch { detail }
            }
        }
    }
}

/// 校验边界输入、独立计算判定结论，并对 `at14-report/1` 主体执行 JCS + SHA-256 封存。
pub fn seal_report(input: At14ReportInput) -> Result<SealedAt14Report, At14RejectError> {
    reject_shadow_producer(&input.producer, &input.manifest_json, &input.profile_json)?;
    reject_diagnostic_artifact(&input.manifest_json, "manifest")?;
    reject_diagnostic_artifact(&input.profile_json, "profile")?;

    let evidence_class = EvidenceClass::from_session_manifest(&input.manifest_json)?;
    if let Some(profile_ec) = input
        .profile_json
        .get("evidence_class")
        .and_then(Value::as_str)
    {
        let parsed = EvidenceClass::parse_profile(profile_ec)?;
        if parsed != evidence_class {
            return Err(At14RejectError::InvalidEvidenceClass {
                found: Some(format!(
                    "manifest.profile={} != profile.evidence_class={profile_ec}",
                    evidence_class.as_str()
                )),
            });
        }
    }

    reject_testonly_artifact(&input.manifest_json, &input.profile_json, evidence_class)?;

    let raw_clock_kind = input
        .profile_json
        .get("clock")
        .and_then(|c| c.get("kind"))
        .and_then(Value::as_str)
        .or_else(|| {
            input
                .manifest_json
                .get("clock")
                .and_then(|c| c.get("kind"))
                .and_then(Value::as_str)
        });
    let clock_kind = ClockKind::parse_for(evidence_class, raw_clock_kind)?;

    if evidence_class != EvidenceClass::Simulation && !input.fault_schedule.is_empty() {
        return Err(At14RejectError::FaultScheduleNotAllowed { evidence_class });
    }

    input
        .model_execution
        .seed
        .validate_for(&input.model_execution.model_id)?;

    require_non_empty("scheduler", &input.scheduler)?;
    require_non_empty("build_fingerprint.commit", &input.build_fingerprint.commit)?;
    require_non_empty(
        "build_fingerprint.lockfile_hash",
        &input.build_fingerprint.lockfile_hash,
    )?;
    require_non_empty("capability_manifest_hash", &input.capability_manifest_hash)?;
    require_non_empty(
        "version_set.model_ref.model_id",
        &input.version_set.model_ref.model_id,
    )?;
    require_non_empty(
        "version_set.model_ref.revision",
        &input.version_set.model_ref.revision,
    )?;
    require_non_empty(
        "version_set.model_ref.content_hash",
        &input.version_set.model_ref.content_hash,
    )?;
    require_non_empty(
        "actual_load.input_range.from",
        &input.actual_load.input_range.from,
    )?;
    require_non_empty(
        "actual_load.input_range.to",
        &input.actual_load.input_range.to,
    )?;
    if input.actual_load.input_range.symbols.is_empty()
        || input
            .actual_load
            .input_range
            .symbols
            .iter()
            .any(|s| s.trim().is_empty())
    {
        return Err(At14RejectError::InvalidField {
            field: "actual_load.input_range.symbols",
            reason: "must contain at least one non-empty symbol".into(),
        });
    }
    require_non_empty("bounded_domain_statement", &input.bounded_domain_statement)?;
    if !input
        .bounded_domain_statement
        .contains(BOUNDED_DOMAIN_MARKER)
    {
        return Err(At14RejectError::InvalidField {
            field: "bounded_domain_statement",
            reason: format!("must include `{BOUNDED_DOMAIN_MARKER}`"),
        });
    }
    require_opt_non_empty("ci_run_id", &input.ci_run_id)?;
    require_opt_non_empty("review_binding", &input.review_binding)?;

    let manifest_hash = jcs_sha256(&input.manifest_json);
    let profile_hash = jcs_sha256(&input.profile_json);
    let profile_revision = input
        .profile_json
        .get("schema_revision")
        .and_then(Value::as_str)
        .unwrap_or("unspecified")
        .to_string();

    let fault_schedule_hash = jcs_sha256_serializable(&input.fault_schedule)?;
    let schedule_trace_hash = jcs_sha256_serializable(&input.schedule_trace)?;

    let mut unexecuted = BTreeSet::new();
    let mut missing_capability = BTreeSet::new();
    let mut mismatch = BTreeSet::new();
    let mut report_unexecuted = BTreeSet::new();

    for extra in &input.extra_unexecuted {
        if !extra.trim().is_empty() {
            unexecuted.insert(extra.clone());
            report_unexecuted.insert(extra.clone());
        }
    }

    let h1 = evaluate_oracle(
        TEST_H1,
        input.h1,
        &mut unexecuted,
        &mut missing_capability,
        &mut mismatch,
        &mut report_unexecuted,
    );
    let h2 = evaluate_oracle(
        TEST_H2,
        input.h2,
        &mut unexecuted,
        &mut missing_capability,
        &mut mismatch,
        &mut report_unexecuted,
    );
    let h3 = evaluate_oracle(
        TEST_H3,
        input.h3,
        &mut unexecuted,
        &mut missing_capability,
        &mut mismatch,
        &mut report_unexecuted,
    );
    let h4 = evaluate_oracle(
        TEST_H4,
        input.h4,
        &mut unexecuted,
        &mut missing_capability,
        &mut mismatch,
        &mut report_unexecuted,
    );

    let fu14_gates = Fu14GateResults {
        a_launcher_process_tree: evaluate_fu14_a(
            input.fu14_criteria.a,
            &mut unexecuted,
            &mut missing_capability,
            &mut mismatch,
            &mut report_unexecuted,
        ),
        b_six_domains_nonempty: evaluate_fu14_b(
            input.fu14_criteria.b,
            &mut unexecuted,
            &mut missing_capability,
            &mut mismatch,
            &mut report_unexecuted,
        ),
        c_model_order_unspecified_no_legacy: evaluate_fu14_c(
            input.fu14_criteria.c,
            &mut unexecuted,
            &mut missing_capability,
            &mut mismatch,
            &mut report_unexecuted,
        ),
        d_shadow_component_only: evaluate_fu14_d(
            input.fu14_criteria.d,
            &mut unexecuted,
            &mut missing_capability,
            &mut mismatch,
            &mut report_unexecuted,
        ),
    };

    for (face_name, face) in [
        (
            "s_structure_snapshot",
            &input.six_faces.s_structure_snapshot,
        ),
        ("b_chong_ledgers", &input.six_faces.b_chong_ledgers),
        ("e_responsibility", &input.six_faces.e_responsibility),
        ("orders_and_fills", &input.six_faces.orders_and_fills),
        ("physical_positions", &input.six_faces.physical_positions),
        (
            "external_effect_journal",
            &input.six_faces.external_effect_journal,
        ),
    ] {
        if face.diff_count > 0 {
            mismatch.insert(format!(
                "six_faces.{face_name}: diff_count={}",
                face.diff_count
            ));
        }
    }

    if input.actual_load.bar_count == 0 {
        mismatch.insert("actual_load.bar_count: must be > 0".to_string());
    }

    if input.model_execution.model_id.is_uncalibrated() {
        missing_capability.insert(format!(
            "model_id: {} is uncalibrated",
            input.model_execution.model_id.as_string()
        ));
    }
    if input.model_execution.capacity_source.is_uncalibrated() {
        missing_capability
            .insert("capacity_source: bar_volume_derived is uncalibrated".to_string());
    }
    if input.input_source_unavailable_count > 0 {
        missing_capability.insert(format!(
            "input_source_unavailable_count={}",
            input.input_source_unavailable_count
        ));
    }

    if !input.model_execution.model_id.is_stochastic()
        && input.assumption_counts.stochastic_l1_count > 0
    {
        mismatch.insert(
            "assumption_counts.stochastic_l1_count > 0 with deterministic model_id".to_string(),
        );
    }
    if input.model_execution.capacity_source != CapacitySource::BarVolumeDerived
        && input.assumption_counts.bar_volume_derived_l0_count > 0
    {
        mismatch.insert(
            "assumption_counts.bar_volume_derived_l0_count > 0 without bar_volume_derived"
                .to_string(),
        );
    }

    let model_id_str = input.model_execution.model_id.as_string();
    if input.version_set.model_ref.model_id != model_id_str {
        mismatch.insert(format!(
            "version_set.model_ref.model_id `{}` != model_execution.model_id `{model_id_str}`",
            input.version_set.model_ref.model_id
        ));
    }
    if input.dual_run_tuple.input_profile_hash != profile_hash {
        mismatch.insert("dual_run_tuple.input_profile_hash != profile_hash".to_string());
    }
    if input.dual_run_tuple.fault_schedule_hash != fault_schedule_hash {
        mismatch.insert(
            "dual_run_tuple.fault_schedule_hash != computed fault_schedule_hash".to_string(),
        );
    }
    if input.dual_run_tuple.schedule_trace_hash != schedule_trace_hash {
        mismatch.insert(
            "dual_run_tuple.schedule_trace_hash != computed schedule_trace_hash".to_string(),
        );
    }
    if input.dual_run_tuple.model_id != model_id_str {
        mismatch.insert(format!(
            "dual_run_tuple.model_id `{}` != `{model_id_str}`",
            input.dual_run_tuple.model_id
        ));
    }
    if input.dual_run_tuple.model_revision != input.version_set.model_ref.revision {
        mismatch
            .insert("dual_run_tuple.model_revision != version_set.model_ref.revision".to_string());
    }
    if input.dual_run_tuple.seed != input.model_execution.seed {
        mismatch.insert("dual_run_tuple.seed != model_execution.seed".to_string());
    }
    if input.dual_run_tuple.scheduler != input.scheduler {
        mismatch.insert("dual_run_tuple.scheduler != session.scheduler".to_string());
    }
    if input.dual_run_tuple.input_events_hash.trim().is_empty() {
        mismatch.insert("dual_run_tuple.input_events_hash is empty".to_string());
    }
    if input.dual_run_tuple.policy_version.trim().is_empty() {
        mismatch.insert("dual_run_tuple.policy_version is empty".to_string());
    }

    let unexecuted_vec: Vec<String> = unexecuted.into_iter().collect();
    let missing_vec: Vec<String> = missing_capability.into_iter().collect();
    let mismatch_vec: Vec<String> = mismatch.into_iter().collect();

    let verdict = match (
        unexecuted_vec.is_empty(),
        missing_vec.is_empty(),
        mismatch_vec.is_empty(),
    ) {
        (true, true, true) => ReportVerdict::Pass,
        (false, true, true) => ReportVerdict::Unexecuted {
            items: unexecuted_vec,
        },
        (true, false, true) => ReportVerdict::MissingCapability { items: missing_vec },
        (true, true, false) => ReportVerdict::Mismatch {
            items: mismatch_vec,
        },
        _ => ReportVerdict::MultipleFailures {
            unexecuted: unexecuted_vec,
            missing_capability: missing_vec,
            mismatch: mismatch_vec,
        },
    };

    let verification_source_label = input
        .input_source
        .verification_source_label()
        .map(str::to_string);

    let body = At14ReportBody {
        schema_version: SCHEMA_VERSION.to_string(),
        verdict,
        session: SessionEcho {
            manifest_revision: EXPECTED_MANIFEST_REVISION.to_string(),
            manifest_hash,
            manifest_echo: input.manifest_json,
            profile_revision,
            profile_hash,
            profile_echo: input.profile_json,
            evidence_class,
            clock_kind,
            scheduler: input.scheduler,
        },
        build_fingerprint: input.build_fingerprint,
        version_set: input.version_set,
        capability_manifest_hash: input.capability_manifest_hash,
        model_execution: input.model_execution,
        dual_run_tuple: input.dual_run_tuple,
        actual_load: input.actual_load,
        fault_schedule: input.fault_schedule,
        schedule_trace: input.schedule_trace,
        h1,
        h2,
        h3,
        h4,
        six_faces: input.six_faces,
        fu14_gates,
        model_order_unspecified_count: input.model_order_unspecified_count,
        diagnostic_not_production_count: input.diagnostic_not_production_count,
        input_source_unavailable_count: input.input_source_unavailable_count,
        input_source: input.input_source,
        verification_source_label,
        assumption_counts: input.assumption_counts,
        unexecuted: report_unexecuted.into_iter().collect(),
        bounded_domain_statement: input.bounded_domain_statement,
        ci_run_id: input.ci_run_id,
        review_binding: input.review_binding,
    };

    let content_hash = jcs_sha256_serializable(&body)?;
    Ok(SealedAt14Report { body, content_hash })
}

impl SealedAt14Report {
    pub fn body(&self) -> &At14ReportBody {
        &self.body
    }

    pub fn verdict(&self) -> &ReportVerdict {
        &self.body.verdict
    }

    pub fn content_hash(&self) -> &str {
        &self.content_hash
    }

    /// 报告主体（不含 `content_hash`）的 RFC 8785 JCS 规范 UTF-8 字节串。
    pub fn canonical_body_bytes(&self) -> Vec<u8> {
        let value = serde_json::to_value(&self.body).expect("at14-report/1 body serializable");
        jcs::canonical_bytes(&value)
    }

    /// 含 `content_hash` 的规范 JSON 字符串（JCS 键序，无多余空白）。
    pub fn to_canonical_json(&self) -> String {
        let mut obj = match serde_json::to_value(&self.body).expect("body to value") {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        obj.insert(
            "content_hash".to_string(),
            Value::String(self.content_hash.clone()),
        );
        jcs::canonicalize(&Value::Object(obj))
    }

    /// 含 `content_hash` 的格式化 JSON（落盘 `at14-report.json` 用）。
    pub fn to_pretty_json(&self) -> String {
        let wire = SealedAt14Wire {
            body: self.body.clone(),
            content_hash: self.content_hash.clone(),
        };
        let mut s = serde_json::to_string_pretty(&wire).expect("sealed wire serializable");
        s.push('\n');
        s
    }

    /// 投影出只读渲染视图；渲染层只从该视图读取已定结论与展示信息。
    pub fn summary_view(&self) -> SummaryView<'_> {
        let b = &self.body;
        SummaryView {
            schema_version: &b.schema_version,
            content_hash: &self.content_hash,
            verdict: &b.verdict,
            evidence_class: b.session.evidence_class,
            clock_kind: b.session.clock_kind,
            scheduler: &b.session.scheduler,
            manifest_hash: &b.session.manifest_hash,
            profile_hash: &b.session.profile_hash,
            capability_manifest_hash: &b.capability_manifest_hash,
            commit: &b.build_fingerprint.commit,
            lockfile_hash: &b.build_fingerprint.lockfile_hash,
            features: &b.build_fingerprint.features,
            model_id: b.model_execution.model_id.as_string(),
            model_revision: &b.version_set.model_ref.revision,
            seed: b.model_execution.seed,
            capacity_source: b.model_execution.capacity_source,
            input_source: b.input_source,
            verification_source_label: b.verification_source_label.as_deref(),
            dual_run_tuple: &b.dual_run_tuple,
            actual_load: &b.actual_load,
            fault_schedule_count: b.fault_schedule.len(),
            schedule_trace_count: b.schedule_trace.len(),
            oracle_rows: [
                OracleSummaryRow {
                    test_name: &b.h1.test_name,
                    result_label: b.h1.result.as_str(),
                    diff_summary: &b.h1.diff_summary,
                },
                OracleSummaryRow {
                    test_name: &b.h2.test_name,
                    result_label: b.h2.result.as_str(),
                    diff_summary: &b.h2.diff_summary,
                },
                OracleSummaryRow {
                    test_name: &b.h3.test_name,
                    result_label: b.h3.result.as_str(),
                    diff_summary: &b.h3.diff_summary,
                },
                OracleSummaryRow {
                    test_name: &b.h4.test_name,
                    result_label: b.h4.result.as_str(),
                    diff_summary: &b.h4.diff_summary,
                },
            ],
            six_face_rows: [
                FaceSummaryRow {
                    face_name: "1. S 结构快照",
                    row_count: b.six_faces.s_structure_snapshot.row_count,
                    diff_summary: &b.six_faces.s_structure_snapshot.diff_summary,
                },
                FaceSummaryRow {
                    face_name: "2. 各重 B 账",
                    row_count: b.six_faces.b_chong_ledgers.row_count,
                    diff_summary: &b.six_faces.b_chong_ledgers.diff_summary,
                },
                FaceSummaryRow {
                    face_name: "3. E 责任",
                    row_count: b.six_faces.e_responsibility.row_count,
                    diff_summary: &b.six_faces.e_responsibility.diff_summary,
                },
                FaceSummaryRow {
                    face_name: "4. 订单/成交原件",
                    row_count: b.six_faces.orders_and_fills.row_count,
                    diff_summary: &b.six_faces.orders_and_fills.diff_summary,
                },
                FaceSummaryRow {
                    face_name: "5. 物理持仓",
                    row_count: b.six_faces.physical_positions.row_count,
                    diff_summary: &b.six_faces.physical_positions.diff_summary,
                },
                FaceSummaryRow {
                    face_name: "6. 外效历史",
                    row_count: b.six_faces.external_effect_journal.row_count,
                    diff_summary: &b.six_faces.external_effect_journal.diff_summary,
                },
            ],
            fu14_rows: [
                GateSummaryRow {
                    gate_id: "(a) 进程树根 production_session",
                    outcome_label: b.fu14_gates.a_launcher_process_tree.label(),
                    detail: b.fu14_gates.a_launcher_process_tree.detail(),
                },
                GateSummaryRow {
                    gate_id: "(b) 六域输入与产出非空",
                    outcome_label: b.fu14_gates.b_six_domains_nonempty.label(),
                    detail: b.fu14_gates.b_six_domains_nonempty.detail(),
                },
                GateSummaryRow {
                    gate_id: "(c) 域外 ModelOrderUnspecified 且旧臂零调用",
                    outcome_label: b.fu14_gates.c_model_order_unspecified_no_legacy.label(),
                    detail: b.fu14_gates.c_model_order_unspecified_no_legacy.detail(),
                },
                GateSummaryRow {
                    gate_id: "(d) 影子 bin 仅组件证据",
                    outcome_label: b.fu14_gates.d_shadow_component_only.label(),
                    detail: b.fu14_gates.d_shadow_component_only.detail(),
                },
            ],
            model_order_unspecified_count: b.model_order_unspecified_count,
            diagnostic_not_production_count: b.diagnostic_not_production_count,
            input_source_unavailable_count: b.input_source_unavailable_count,
            assumption_counts: b.assumption_counts,
            unexecuted: &b.unexecuted,
            bounded_domain_statement: &b.bounded_domain_statement,
            ci_run_id: b.ci_run_id.as_deref(),
            review_binding: b.review_binding.as_deref(),
            _sealed: (),
        }
    }

    pub fn render_summary(&self) -> String {
        render_summary(&self.summary_view())
    }
}

/// 验证已落盘的 `at14-report.json`：校验 schema 版本、JCS+SHA-256 `content_hash` 与字段合法性。
pub fn verify_sealed_json(raw: &str) -> Result<SealedAt14Report, At14RejectError> {
    let wire: SealedAt14Wire =
        serde_json::from_str(raw).map_err(|e| At14RejectError::InvalidField {
            field: "at14-report.json",
            reason: e.to_string(),
        })?;
    if wire.body.schema_version != SCHEMA_VERSION {
        return Err(At14RejectError::InvalidField {
            field: "schema_version",
            reason: format!(
                "expected {SCHEMA_VERSION}, got {}",
                wire.body.schema_version
            ),
        });
    }
    let computed = jcs_sha256_serializable(&wire.body)?;
    if computed != wire.content_hash {
        return Err(At14RejectError::ContentHashMismatch {
            expected: wire.content_hash,
            computed,
        });
    }
    Ok(SealedAt14Report {
        body: wire.body,
        content_hash: computed,
    })
}

/// 纯格式化渲染 `summary.md`。函数签名仅接收 [`SummaryView`]，无法接触做判定所需的原始输入。
pub fn render_summary(view: &SummaryView<'_>) -> String {
    let mut out = String::new();
    out.push_str("# AT-14 回放验收报告摘要\n\n");
    out.push_str(&format!("- schema_version: `{}`\n", view.schema_version));
    out.push_str(&format!("- content_hash: `{}`\n", view.content_hash));
    out.push_str(&format!("- verdict: `{}`\n", view.verdict.label()));
    match view.verdict {
        ReportVerdict::Pass => {}
        ReportVerdict::Unexecuted { items } => {
            out.push_str(&format!("- verdict_unexecuted: {}\n", items.join("; ")));
        }
        ReportVerdict::MissingCapability { items } => {
            out.push_str(&format!(
                "- verdict_missing_capability: {}\n",
                items.join("; ")
            ));
        }
        ReportVerdict::Mismatch { items } => {
            out.push_str(&format!("- verdict_mismatch: {}\n", items.join("; ")));
        }
        ReportVerdict::MultipleFailures {
            unexecuted,
            missing_capability,
            mismatch,
        } => {
            if !unexecuted.is_empty() {
                out.push_str(&format!(
                    "- verdict_unexecuted: {}\n",
                    unexecuted.join("; ")
                ));
            }
            if !missing_capability.is_empty() {
                out.push_str(&format!(
                    "- verdict_missing_capability: {}\n",
                    missing_capability.join("; ")
                ));
            }
            if !mismatch.is_empty() {
                out.push_str(&format!("- verdict_mismatch: {}\n", mismatch.join("; ")));
            }
        }
    }

    out.push_str("\n## 会话与构建\n\n");
    out.push_str(&format!(
        "- evidence_class: `{}`\n- clock.kind: `{}`\n- scheduler: `{}`\n",
        view.evidence_class.as_str(),
        view.clock_kind.as_str(),
        view.scheduler
    ));
    out.push_str(&format!(
        "- manifest_hash: `{}`\n- profile_hash: `{}`\n- capability_manifest_hash: `{}`\n",
        view.manifest_hash, view.profile_hash, view.capability_manifest_hash
    ));
    let features: Vec<&str> = view.features.iter().map(String::as_str).collect();
    out.push_str(&format!(
        "- build: commit=`{}`, lockfile_hash=`{}`, features=`[{}]`\n",
        view.commit,
        view.lockfile_hash,
        features.join(", ")
    ));
    out.push_str(&format!(
        "- ci_run_id: `{}`\n- review_binding: `{}`\n",
        view.ci_run_id.unwrap_or("none"),
        view.review_binding.unwrap_or("none")
    ));

    out.push_str("\n## 模型、容量来源与双跑五元组\n\n");
    out.push_str(&format!(
        "- model_id: `{}` (revision=`{}`)\n- seed: `{}`\n- capacity_source: `{}`\n",
        view.model_id,
        view.model_revision,
        view.seed,
        view.capacity_source.as_str()
    ));
    out.push_str(&format!(
        "- input_source: `{}` (校验源标注: `{}`)\n",
        view.input_source.as_str(),
        view.verification_source_label.unwrap_or("无")
    ));
    out.push_str(&format!(
        "- dual_run_tuple: profile=`{}`, events=`{}`, fault_schedule=`{}`, schedule_trace=`{}`, policy=`{}`, model=`{}@{}`, seed=`{}`, scheduler=`{}`\n",
        view.dual_run_tuple.input_profile_hash,
        view.dual_run_tuple.input_events_hash,
        view.dual_run_tuple.fault_schedule_hash,
        view.dual_run_tuple.schedule_trace_hash,
        view.dual_run_tuple.policy_version,
        view.dual_run_tuple.model_id,
        view.dual_run_tuple.model_revision,
        view.dual_run_tuple.seed,
        view.dual_run_tuple.scheduler
    ));
    out.push_str(&format!(
        "- actual_load: symbols=`[{}]`, range=`{}..{}`, bars={}, checkpoints={}, fault_schedule={}, schedule_trace={}\n",
        view.actual_load.input_range.symbols.join(", "),
        view.actual_load.input_range.from,
        view.actual_load.input_range.to,
        view.actual_load.bar_count,
        view.actual_load.checkpoint_count,
        view.fault_schedule_count,
        view.schedule_trace_count
    ));

    out.push_str("\n## FU-14 判据 (a)-(d)\n\n");
    for row in &view.fu14_rows {
        match row.detail {
            Some(detail) => out.push_str(&format!(
                "- {}: `{}` ({detail})\n",
                row.gate_id, row.outcome_label
            )),
            None => out.push_str(&format!("- {}: `{}`\n", row.gate_id, row.outcome_label)),
        }
    }

    out.push_str("\n## H1-H4 Oracle\n\n");
    for row in &view.oracle_rows {
        out.push_str(&format!(
            "- `{}`: `{}` ({})\n",
            row.test_name, row.result_label, row.diff_summary
        ));
    }

    out.push_str("\n## 六面摘要\n\n");
    for row in &view.six_face_rows {
        out.push_str(&format!(
            "- {}: rows={}, diff={}\n",
            row.face_name, row.row_count, row.diff_summary
        ));
    }

    out.push_str("\n## 专项与假设分层计数\n\n");
    out.push_str(&format!(
        "- model_order_unspecified_count: {}\n- diagnostic_not_production_count: {}\n- input_source_unavailable_count: {}\n",
        view.model_order_unspecified_count,
        view.diagnostic_not_production_count,
        view.input_source_unavailable_count
    ));
    out.push_str(&format!(
        "- L1 stochastic_l1_count: {}\n- L0 bar_volume_derived_l0_count: {}\n- L0 unconstrained_capacity_l0_count: {}\n",
        view.assumption_counts.stochastic_l1_count,
        view.assumption_counts.bar_volume_derived_l0_count,
        view.assumption_counts.unconstrained_capacity_l0_count
    ));

    out.push_str("\n## 未执行项与有界受测域声明\n\n");
    if view.unexecuted.is_empty() {
        out.push_str("- unexecuted: []\n");
    } else {
        out.push_str(&format!("- unexecuted: [{}]\n", view.unexecuted.join(", ")));
    }
    out.push_str(&format!(
        "- bounded_domain_statement: {}\n",
        view.bounded_domain_statement
    ));
    out
}

/// 将已封存的报告与同源 `summary.md` 写入已校验目录。
pub fn write_report_bundle(
    report: &SealedAt14Report,
    dir: &At14ReportDir,
) -> Result<EmittedReportFiles, At14RejectError> {
    std::fs::create_dir_all(dir.path()).map_err(|e| At14RejectError::IoError {
        path: dir.path().display().to_string(),
        reason: e.to_string(),
    })?;
    let report_json = dir.path().join(REPORT_JSON_FILE);
    let summary_md = dir.path().join(SUMMARY_MD_FILE);
    std::fs::write(&report_json, report.to_pretty_json()).map_err(|e| {
        At14RejectError::IoError {
            path: report_json.display().to_string(),
            reason: e.to_string(),
        }
    })?;
    std::fs::write(&summary_md, report.render_summary()).map_err(|e| At14RejectError::IoError {
        path: summary_md.display().to_string(),
        reason: e.to_string(),
    })?;
    Ok(EmittedReportFiles {
        dir: dir.path().to_path_buf(),
        report_json,
        summary_md,
    })
}

/// 原子入口：先完成全部边界拒收与目录校验，再封存并落盘；被拒收输入绝不创建目录或写盘。
pub fn seal_and_write_report(
    input: At14ReportInput,
    dir_path: impl Into<PathBuf>,
) -> Result<(SealedAt14Report, EmittedReportFiles), At14RejectError> {
    let dir = At14ReportDir::parse(dir_path)?;
    let sealed = seal_report(input)?;
    let files = write_report_bundle(&sealed, &dir)?;
    Ok((sealed, files))
}

#[cfg(test)]
mod tests;
