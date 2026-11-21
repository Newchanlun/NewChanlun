mod archive_v1;
mod archive_v2;
use super::exact_wire::{decimal, Plan, SignedChange};
use super::{
    model::{Batch, Change, Model, ModelRef},
    store,
};
use crate::session_protocol::{canonical_json, reply_envelope, sha256_hex, strict_json};
use crate::session_transport::{
    read_frame, serve_unix, write_frame_observed, NoObserver, TransportBounds,
};
use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::{Duration, Instant};

pub const WIRE: &str = "x-exact-simulation/1";
pub const AUTHORITY_WIRE: &str = "x-exact-authority/1";
fn hash<T: Serialize>(v: &T) -> String {
    sha256_hex(canonical_json(&serde_json::to_value(v).expect("integer domain")).as_bytes())
}
fn error(e: impl std::fmt::Display) -> String {
    format!("InvalidDomain：{e}")
}
fn io(e: impl std::fmt::Display) -> String {
    format!("AuthorityUnavailable：{e}")
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Authority {
    pub socket: String,
    pub authority_id: String,
    pub authority_epoch: String,
    /// IC:9 共同信封与 ADR 0056:39 同一 `session_transport`：请求带完整信封，回复整帧须等于
    /// `reply_envelope` 由原请求重建的结果（与 E↔B `finance_transport` 同一判据）。
    pub schema_revision: String,
    pub reply_namespace: String,
    pub producer_id: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub model: Model,
    pub session_id: String,
    pub session_generation: String,
    pub x_id: String,
    pub source_namespace: String,
    pub source_epoch: String,
    pub socket: String,
    pub e: Authority,
    pub s: Authority,
    /// manifest 引用的获准条件清单；与 E 冻结的 `exact_release.conditions` 是同一份（#1407 C2）。
    pub conditions: Vec<Condition>,
    pub timeout_ms: u64,
    pub max_frame_bytes: usize,
}
impl Profile {
    pub(super) fn validate_base(&self) -> Result<(), String> {
        self.model.validate()?;
        for s in [
            &self.session_id,
            &self.session_generation,
            &self.x_id,
            &self.source_namespace,
            &self.source_epoch,
            &self.e.authority_id,
            &self.e.authority_epoch,
            &self.s.authority_id,
            &self.s.authority_epoch,
            &self.e.schema_revision,
            &self.e.reply_namespace,
            &self.e.producer_id,
            &self.s.schema_revision,
            &self.s.reply_namespace,
            &self.s.producer_id,
        ] {
            if s.is_empty() {
                return Err("InvalidDomain：模拟会话/权威身份缺失".into());
            }
        }
        for path in [&self.socket, &self.e.socket, &self.s.socket] {
            if !Path::new(path).is_absolute() {
                return Err("InvalidDomain：模拟权威 socket 须绝对路径".into());
            }
        }
        if self.socket == self.e.socket
            || self.socket == self.s.socket
            || self.e.socket == self.s.socket
            || self.timeout_ms == 0
            || self.max_frame_bytes == 0
        {
            return Err("InvalidDomain：模拟端点须独立且资源界为正".into());
        }
        Ok(())
    }

    pub fn validate(&self) -> Result<(), String> {
        self.validate_base()?;
        validate_conditions(&self.conditions)?;
        validate_fx_marker_uniformity(&self.conditions)
    }
}

fn condition_is_fx_release_bound(c: &Condition) -> bool {
    let m = crate::economic_session::FX_RELEASE_BOUND_MARKER;
    c.dependency_set.len() == 1
        && c.dependency_set[0] == m
        && c.invalidation_sources.len() == 1
        && c.invalidation_sources[0] == m
        && c.evidence_refs.len() == 1
        && c.evidence_refs[0] == m
        && c.coverage_proof == m
}

fn is_fx_release_bound_profile(list: &[Condition]) -> bool {
    !list.is_empty() && list.iter().all(condition_is_fx_release_bound)
}

fn validate_fx_marker_uniformity(list: &[Condition]) -> Result<(), String> {
    // 一项的四个槽完整声明才是模板；单独出现在静态证据里的同名字符串只是数据。
    let any = list.iter().any(condition_is_fx_release_bound);
    if any && !is_fx_release_bound_profile(list) {
        return Err(format!(
            "Unsupported：{} 须在获准条件清单四项内统一声明，不得混写",
            crate::economic_session::FX_RELEASE_BOUND_MARKER
        ));
    }
    Ok(())
}

fn validate_fx_release_bound_certificate(
    c: &Certificate,
    approved: &[Condition],
) -> Result<(), String> {
    validate_conditions(&c.conditions)?;
    if c.conditions.len() != approved.len() {
        return Err("Unsupported：FX 放行条件清单项数与获准 manifest 不等".into());
    }
    let refs = crate::economic_session::FxReleaseReferences::new(
        c.market_dependencies.iter().map(String::as_str),
    )?;
    for (got, want) in c.conditions.iter().zip(approved.iter()) {
        if got.condition_id != want.condition_id
            || got.authority_revision != want.authority_revision
            || got.required_check_stages != want.required_check_stages
            || got.validator_capability != want.validator_capability
            || got.failure_result != want.failure_result
        {
            return Err("Unsupported：FX 放行条件清单元数据与获准 manifest 不一致".into());
        }
        refs.validate_condition(
            got.dependency_set.iter().map(String::as_str),
            got.invalidation_sources.iter().map(String::as_str),
            got.evidence_refs.iter().map(String::as_str),
            &got.coverage_proof,
        )?;
    }
    Ok(())
}

/// X 自身持有核验能力的条件；自 `1f0a42bc20` 起所有 12+6+6 写者均拒绝未支持的 X 阶段能力。
const X_CAPABILITIES: [&str; 1] = ["simulation-local-transaction/1"];

fn validate_conditions_shape(list: &[Condition]) -> Result<(), String> {
    let mut ids = std::collections::BTreeSet::new();
    let filled = |a: &[String]| !a.is_empty() && a.iter().all(|x| !x.is_empty());
    for c in list {
        if !ids.insert(&c.condition_id)
            || [
                &c.condition_id,
                &c.authority_revision,
                &c.coverage_proof,
                &c.validator_capability,
                &c.failure_result,
            ]
            .iter()
            .any(|x| x.is_empty())
            || ![
                &c.dependency_set,
                &c.invalidation_sources,
                &c.required_check_stages,
                &c.evidence_refs,
            ]
            .iter()
            .all(|a| filled(a))
        {
            return Err(
                "Unsupported：获准条件缺 ConditionEvidence 字段或 condition_id 重复".into(),
            );
        }
    }
    Ok(())
}

fn require_model_coverage(list: &[Condition]) -> Result<(), String> {
    if !list.iter().any(|c| {
        c.condition_id == "model_coverage"
            && c.required_check_stages
                .iter()
                .any(|s| s == "E.ReleaseExact")
    }) {
        return Err("MissingDependency：获准条件清单缺 E-Release 阶段的 model_coverage".into());
    }
    Ok(())
}

/// 全部 12+6+6 布局（后期 `/1` 自 `1f0a42bc20` 起）共同可证的条件清单不变量：
/// 1. 逐项带齐 IC「ConditionEvidence」九字段且非空，`condition_id` 不重复；
/// 2. 任何 `X.*` 阶段条件的核验能力须属于 `X_CAPABILITIES`；
/// 3. 清单包含 ADR 0052 裁定二 `E.ReleaseExact` 阶段的 `model_coverage`。
/// 不包含后来在 `2ed00abd6c` 新增的语义配对表与 `b66b61a0b0` 新增的四项必备能力完备闸。
pub(super) fn validate_conditions_common_12_6(list: &[Condition]) -> Result<(), String> {
    validate_conditions_shape(list)?;
    for c in list {
        if c.required_check_stages.iter().any(|s| s.starts_with("X."))
            && !X_CAPABILITIES.contains(&c.validator_capability.as_str())
        {
            return Err("Unsupported：X 阶段条件的核验能力 X 未支持".into());
        }
    }
    require_model_coverage(list)
}

/// 现行（`/2` 自 `8d23381b0c` 及 `/3`）完整准入条件清单校验：
/// 除九字段非空与 `model_coverage` 外，强制逐项配对表（`2ed00abd6c+`）与四项必备能力完备闸（`b66b61a0b0+`）。
fn validate_conditions(list: &[Condition]) -> Result<(), String> {
    validate_conditions_shape(list)?;
    for c in list {
        // 与 E 冻结原件同一张配对表：X.* 阶段只有 X 支持的能力，失败结果必须 Denied。
        let stages: Vec<&str> = c.required_check_stages.iter().map(String::as_str).collect();
        crate::economic_session::check_condition_semantics(
            &c.condition_id,
            &c.authority_revision,
            &stages,
            &c.validator_capability,
            &c.failure_result,
        )?;
    }
    require_model_coverage(list)?;
    // 与 E 同一个完备闸：E/S/X 各阶段的必备能力都在、各一次。
    crate::economic_session::check_required_capabilities(
        list.iter().map(|c| c.validator_capability.as_str()),
    )
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Condition {
    pub condition_id: String,
    pub authority_revision: String,
    pub dependency_set: Vec<String>,
    pub invalidation_sources: Vec<String>,
    pub required_check_stages: Vec<String>,
    pub evidence_refs: Vec<String>,
    pub coverage_proof: String,
    pub validator_capability: String,
    pub failure_result: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Certificate {
    pub rd11_policy: String,
    pub responsibility_refs: Vec<String>,
    pub structure_dependencies: Vec<String>,
    pub market_dependencies: Vec<String>,
    pub rule_revision: String,
    pub conditions: Vec<Condition>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ExactCommand {
    pub command_id: String,
    pub logical_order_family: String,
    #[serde(with = "decimal")]
    pub first_quantity: i64,
    pub allocation_id: String,
    pub session_id: String,
    pub session_generation: String,
    pub x_id: String,
    #[serde(with = "decimal")]
    pub x_epoch: i64,
    pub symbol: String,
    pub projection_kind: String,
    pub model_ref: ModelRef,
    #[serde(with = "SignedChange")]
    pub change: Change,
    pub plan_hash: String,
    pub certificate_hash: String,
    pub certificate: Certificate,
}
impl ExactCommand {
    pub(crate) fn validate(&self, p: &Profile, epoch: i64) -> Result<(), String> {
        if self.session_id != p.session_id
            || self.session_generation != p.session_generation
            || self.x_id != p.x_id
            || self.x_epoch != epoch
            || self.symbol != p.model.symbol
            || self.projection_kind != p.model.projection_kind
            || self.certificate.rd11_policy != p.model.rd11_policy
        {
            return Err("IdentityConflict：精确命令会话/执行域/模型不符".into());
        }
        if self.model_ref != p.model.model_ref() {
            return Err("IdentityConflict：精确命令获准模型身份与 X 实际装载模型内容不符".into());
        }
        let (command, family) = match &self.change {
            Change::Submit { order } | Change::Replace { order } => {
                (&order.command_id, &order.family_id)
            }
            Change::Cancel {
                command_id,
                family_id,
                ..
            } => (command_id, family_id),
        };
        if command != &self.command_id
            || family != &self.logical_order_family
            || command.is_empty()
            || family.is_empty()
            || self.plan_hash != hash(&Plan(&self.change))
            || self.certificate_hash != hash(&self.certificate)
        {
            return Err("IdentityConflict：精确命令身份/计划/条件摘要不符".into());
        }
        if matches!(&self.change,Change::Submit{order}|Change::Replace{order} if order.projection_manifest.is_empty())
        {
            return Err("MissingDependency：精确命令缺 E 投影清单引用".into());
        }
        let c = &self.certificate;
        if c.rule_revision.is_empty()
            || [
                &c.responsibility_refs,
                &c.structure_dependencies,
                &c.market_dependencies,
            ]
            .iter()
            .any(|a| a.is_empty() || a.iter().any(String::is_empty))
        {
            return Err("MissingDependency：精确命令缺责任/结构/市场/规则依赖".into());
        }
        if self.first_quantity <= 0 || self.allocation_id.is_empty() {
            return Err("MissingDependency：精确命令缺首次量 L 或分配身份".into());
        }
        if matches!(&self.change, Change::Submit { order } if order.quantity != self.first_quantity)
        {
            return Err("IdentityConflict：首次提交量与 L 不同".into());
        }
        if is_fx_release_bound_profile(&p.conditions) {
            validate_fx_release_bound_certificate(c, &p.conditions)?;
        } else if c.conditions != p.conditions {
            return Err("Unsupported：条件清单与获准 manifest 清单不逐项相等".into());
        }
        Ok(())
    }
}

pub(super) trait AuditProfile {
    fn validate_profile(&self) -> Result<(), String>;
    fn model(&self) -> &Model;
    fn session_id(&self) -> &str;
    fn session_generation(&self) -> &str;
    fn x_id(&self) -> &str;
    fn source_namespace(&self) -> &str;
    fn source_epoch(&self) -> &str;
    fn e_identity(&self) -> (&str, &str);
    fn s_identity(&self) -> (&str, &str);
}

impl AuditProfile for Profile {
    fn validate_profile(&self) -> Result<(), String> {
        self.validate()
    }
    fn model(&self) -> &Model {
        &self.model
    }
    fn session_id(&self) -> &str {
        &self.session_id
    }
    fn session_generation(&self) -> &str {
        &self.session_generation
    }
    fn x_id(&self) -> &str {
        &self.x_id
    }
    fn source_namespace(&self) -> &str {
        &self.source_namespace
    }
    fn source_epoch(&self) -> &str {
        &self.source_epoch
    }
    fn e_identity(&self) -> (&str, &str) {
        (&self.e.authority_id, &self.e.authority_epoch)
    }
    fn s_identity(&self) -> (&str, &str) {
        (&self.s.authority_id, &self.s.authority_epoch)
    }
}

/// 冷审绑定原命令、对应冻结 profile 布局及其时钟编码。活动的接纳、调用与恢复接口只接 ExactCommand。
trait CommandRecord: Serialize + serde::de::DeserializeOwned + PartialEq {
    type Profile: AuditProfile + Serialize;
    type Tick: serde::de::DeserializeOwned + Copy + Into<i64>;
    const INNER_REVISION: Option<&'static str>;
    /// 后期 `/1`（`1f0a42bc20`–`b66b61a0b0`）、`/2` 与 `/3` 写者在持久化 `execute_evidence.claimed_ns`
    /// 时恒写 `batch.bar.index`；早期 `/1`（`18446a3d35`、`5f3361ca8b` 写墙钟 `now_ns()`，
    /// `d1c46577b1` 改写 `batch.bar.index`，同用 11 键/3 键早期布局）不能溯及强制等于 `bar.index`。
    const CLAIMED_MATCHES_BATCH_BAR: bool;
    const CLAIMED_NS_AUDIT_POLICY: &'static str;
    const ARCHIVE_LAYOUT: &'static str;
    /// 标明只读核档所核证的条件清单世代边界，以及因旧档缺少可信写者修订记录而未核证的后加准入闸。
    const CONDITION_AUDIT_POLICY: &'static str;
    const CONDITION_AUDIT_UNPROVEN: &'static [&'static str];
    fn id(&self) -> &str;
    fn change(&self) -> &Change;
    fn validate_record(&self, p: &Self::Profile) -> Result<(), String>;
}

#[derive(Debug, Copy, Clone, Serialize, Deserialize)]
#[serde(transparent)]
struct DecimalTick(#[serde(with = "decimal")] i64);
impl From<DecimalTick> for i64 {
    fn from(t: DecimalTick) -> i64 {
        t.0
    }
}
impl CommandRecord for ExactCommand {
    type Profile = Profile;
    type Tick = DecimalTick;
    const INNER_REVISION: Option<&'static str> = Some(super::EXACT_PROFILE_REVISION);
    const CLAIMED_MATCHES_BATCH_BAR: bool = true;
    const CLAIMED_NS_AUDIT_POLICY: &'static str = "verified_equal_to_attempt_bar";
    const ARCHIVE_LAYOUT: &'static str = "v3";
    const CONDITION_AUDIT_POLICY: &'static str =
        "verified_current_condition_semantics_and_completeness";
    const CONDITION_AUDIT_UNPROVEN: &'static [&'static str] = &[];
    fn id(&self) -> &str {
        &self.command_id
    }
    fn change(&self) -> &Change {
        &self.change
    }
    fn validate_record(&self, p: &Profile) -> Result<(), String> {
        self.validate(p, self.x_epoch)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    protocol: String,
    op: String,
    payload: Value,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Receipt<C, T> {
    protocol: String,
    session_id: String,
    session_generation: String,
    authority_id: String,
    authority_epoch: String,
    command_id: String,
    command_hash: String,
    command: C,
    state: String,
    receipt_id: String,
    release_receipt_id: Option<String>,
    commit_ns: T,
}
type AuthorityReply = Receipt<ExactCommand, DecimalTick>;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ExecuteEvidence<C, T> {
    reply: Receipt<C, T>,
    claimed_ns: T,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AcceptClock<T> {
    received_ns: T,
    first_known_ns: T,
    commit_ns: T,
}
/// simulation 证据类的 `logical-bar/1` 接纳读数（ADR 0052:296、ADR 0056:52）：已提交前沿
/// last_bar+1，空历史为 0。X 不读系统时钟；*_ns 字段在本域存 bar_index 读数。
fn logical_now(c: &Connection) -> Result<i64, String> {
    let raw: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(error)?;
    let state: super::model::State = serde_json::from_str(&raw).map_err(error)?;
    state
        .last_bar
        .map_or(Some(0), |bar| bar.checked_add(1))
        .ok_or_else(|| "InvalidDomain：逻辑 bar 时钟溢出".into())
}
fn validate_accept_clock<T: Into<i64> + Copy>(
    clock: &AcceptClock<T>,
    release_commit_ns: i64,
) -> Result<(), String> {
    if release_commit_ns < 0
        || clock.received_ns.into() < 0
        || clock.received_ns.into() > clock.first_known_ns.into()
        || clock.first_known_ns.into() > clock.commit_ns.into()
        || clock.first_known_ns.into() < release_commit_ns
    {
        return Err("InvalidDomain：X 接纳时钟早于 E 持久交付或本地相位倒退".into());
    }
    Ok(())
}
fn audit_accepts<C: CommandRecord>(c: &Connection, p: &C::Profile) -> Result<(), String> {
    let mut q = c
        .prepare("SELECT accept_clock,release_evidence,command FROM x_exact_commands")
        .map_err(error)?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .map_err(error)?;
    for row in rows {
        let (clock, release, command) = row.map_err(error)?;
        let clock: AcceptClock<C::Tick> = serde_json::from_str(&clock).map_err(error)?;
        let release: Receipt<C, C::Tick> = serde_json::from_str(&release).map_err(error)?;
        if canonical_json(&serde_json::to_value(&release.command).map_err(error)?) != command {
            return Err("IdentityConflict：恢复交付与命令不符".into());
        }
        let command: C = serde_json::from_str(&command).map_err(error)?;
        validate_authority_reply(
            p,
            p.e_identity(),
            "QueryReleasedExact",
            &command,
            None,
            &release,
        )?;
        validate_accept_clock(&clock, release.commit_ns.into())?;
    }
    Ok(())
}
fn audit_execution<C: CommandRecord>(c: &Connection, p: &C::Profile) -> Result<(), String> {
    let pending = store::pending_batch(c)?;
    let mut required = std::collections::BTreeMap::new();
    let mut q = c
        .prepare("SELECT request FROM x_sim_batches")
        .map_err(error)?;
    let rows = q.query_map([], |r| r.get::<_, String>(0)).map_err(error)?;
    for row in rows {
        let raw = row.map_err(error)?;
        let b: Batch = serde_json::from_str(&raw).map_err(error)?;
        let bar_index = b.bar.index;
        for change in b.close_changes {
            let id = command_id(&change).to_owned();
            if required
                .insert(id, (raw.clone(), change, bar_index, false))
                .is_some()
            {
                return Err("IdentityConflict：命令跨批重复".into());
            }
        }
    }
    if let Some(raw) = &pending {
        let b: Batch = serde_json::from_str(raw).map_err(error)?;
        let mut normal = b.clone();
        normal.normalize();
        if canonical_json(&serde_json::to_value(normal).map_err(error)?) != *raw
            || store::replay_batch(c, &b)?.is_some()
        {
            return Err("IdentityConflict：pending内容非法或已提交".into());
        }
        store::validate_batch(c, &b)?;
        let bar_index = b.bar.index;
        for change in b.close_changes {
            let id = command_id(&change).to_owned();
            if required
                .insert(id, (raw.clone(), change, bar_index, true))
                .is_some()
            {
                return Err("IdentityConflict：pending重复已执行命令".into());
            }
        }
    }
    let mut q=c.prepare("SELECT id,command,release_receipt,state,attempt_batch,execute_evidence,release_evidence FROM x_exact_commands").map_err(error)?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, Option<String>>(4)?,
                r.get::<_, Option<String>>(5)?,
                r.get::<_, String>(6)?,
            ))
        })
        .map_err(error)?;
    for row in rows {
        let (id, raw, release, state, attempt, evidence, released) = row.map_err(error)?;
        let command: C = serde_json::from_str(&raw).map_err(error)?;
        command.validate_record(p)?;
        let released: Receipt<C, C::Tick> = serde_json::from_str(&released).map_err(error)?;
        if id != command.id() || released.receipt_id != release {
            return Err("IdentityConflict：接纳身份或交付引用不符".into());
        }
        if let Some((batch, change, expected_bar_index, is_pending)) = required.remove(&id) {
            if command.change() != &change {
                return Err("IdentityConflict：批命令与已接纳内容不符".into());
            }
            if is_pending && state == "Accepted" {
                if attempt.is_some() || evidence.is_some() {
                    return Err("IdentityConflict：Accepted混入调用证据".into());
                }
                continue;
            }
            let allowed = if is_pending {
                matches!(
                    state.as_str(),
                    "ExecutionRequested" | "ExecutionReady" | "MayHaveCalled"
                )
            } else {
                state == "Observed"
            };
            if !allowed || attempt.as_deref() != Some(batch.as_str()) {
                return Err("IdentityConflict：批执行状态或占有内容不符".into());
            }
            if state == "ExecutionRequested" {
                if evidence.is_some() {
                    return Err("IdentityConflict：未取得终态却有回执".into());
                }
            } else {
                let evidence: Value = serde_json::from_str(
                    evidence.as_deref().ok_or("IdentityConflict：执行缺S原件")?,
                )
                .map_err(error)?;
                validate_execution_record(p, &command, &release, &evidence, expected_bar_index)?;
            }
        } else if state != "Accepted" || attempt.is_some() || evidence.is_some() {
            return Err("IdentityConflict：游离执行命令".into());
        }
    }
    if !required.is_empty() {
        return Err("IdentityConflict：工作状态或批次缺已接纳命令权威原件".into());
    }
    Ok(())
}

fn validate_execution_record<C: CommandRecord>(
    p: &C::Profile,
    command: &C,
    release: &str,
    evidence: &Value,
    expected_bar_index: i64,
) -> Result<Receipt<C, C::Tick>, String> {
    let parsed: ExecuteEvidence<C, C::Tick> =
        serde_json::from_value(evidence.clone()).map_err(error)?;
    let reply = parsed.reply;
    validate_authority_reply(
        p,
        p.s_identity(),
        "RequestConditionalExecution",
        command,
        Some(release),
        &reply,
    )?;
    let eligibility = match command.change() {
        Change::Submit { order } | Change::Replace { order } => &order.eligibility_ref,
        Change::Cancel {
            eligibility_ref, ..
        } => eligibility_ref,
    };
    let claimed = parsed.claimed_ns.into();
    if eligibility != &reply.receipt_id || claimed < reply.commit_ns.into() {
        return Err("IdentityConflict：持久S执行证据与资格/调用占有时刻不符".into());
    }
    if C::CLAIMED_MATCHES_BATCH_BAR && claimed != expected_bar_index {
        return Err(format!(
            "IdentityConflict：持久S执行证据调用占有时刻({claimed})与占有批bar.index({expected_bar_index})不符"
        ));
    }
    Ok(reply)
}

fn validate_frame(v: Value) -> Result<Value, String> {
    let r: Request = serde_json::from_value(v.clone()).map_err(error)?;
    if r.protocol != WIRE {
        return Err("VersionUnsupported：X wire".into());
    }
    Ok(v)
}
fn json_frame(v: Value) -> Result<Value, String> {
    Ok(v)
}
/// 已通过帧界检查、尚未连接的权威请求帧。编码或帧界失败时 S 一个字节都没收到。
struct AuthorityFrame {
    envelope: Value,
    bytes: Vec<u8>,
}
/// 业务请求放在 IC:9 共同信封里：来源是 X 的事实命名空间，producer 是 X 身份与 writer epoch。
/// message_id 由规范业务字节决定，同一请求重试不换身份。
fn authority_frame(
    p: &Profile,
    a: &Authority,
    epoch: i64,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
) -> Result<AuthorityFrame, String> {
    let payload = json!({"op":op,"protocol":AUTHORITY_WIRE,"session_id":p.session_id,"session_generation":p.session_generation,"authority_id":a.authority_id,"authority_epoch":a.authority_epoch,"command_id":command.command_id,"command_hash":hash(command),"command":command,"release_receipt_id":release});
    let payload_hash = sha256_hex(canonical_json(&payload).as_bytes());
    let envelope = json!({"schema_revision":a.schema_revision,"session_id":p.session_id,"session_generation":p.session_generation,"source_namespace":p.source_namespace,"source_epoch":p.source_epoch,"message_id":format!("x-authority-{payload_hash}"),"producer_id":p.x_id,"producer_epoch":epoch.to_string(),"payload_hash":payload_hash,"causal_refs":[],"payload":payload});
    let mut bytes = canonical_json(&envelope).into_bytes();
    bytes.push(b'\n');
    if bytes.len() > p.max_frame_bytes {
        return Err("Unsupported：权威请求超过帧界".into());
    }
    Ok(AuthorityFrame { envelope, bytes })
}
/// 连接失败时同样确定未发出；只有返回的连接写出帧后才进入可能已发出的窗口。
fn authority_connect(a: &Authority) -> Result<UnixStream, String> {
    UnixStream::connect(&a.socket).map_err(io)
}
fn authority_exchange(
    p: &Profile,
    a: &Authority,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
    mut stream: UnixStream,
    frame: &AuthorityFrame,
) -> Result<AuthorityReply, String> {
    // 权威期限只量这次交换。连接之后、写帧之前 X 先持久 ExecutionRequested（synchronous=FULL），
    // 本地落盘不计入对端期限：否则慢盘会在一个字节都没发出时超时，命令却已标成「可能已发出」，
    // 只能查询 S 的 NoRecord，永远卡住（#1407 C2，CI run 42772775704）。
    let deadline = Instant::now() + Duration::from_millis(p.timeout_ms);
    write_frame_observed(&mut stream, &frame.bytes, deadline, &mut NoObserver)?;
    stream.shutdown(std::net::Shutdown::Write).map_err(io)?;
    let reply = read_frame(&mut stream, p.max_frame_bytes, deadline, json_frame)?;
    let expected = reply_envelope(
        &frame.envelope,
        reply["payload"].clone(),
        &a.schema_revision,
        &p.session_id,
        &p.session_generation,
        &a.reply_namespace,
        &a.producer_id,
        &a.authority_epoch,
    );
    if reply != expected {
        return Err("IdentityConflict：权威回复信封的身份/epoch/因果/规范字节不符".into());
    }
    let payload = &reply["payload"];
    if payload["kind"] == "Error" {
        return Err(format!(
            "MissingDependency：权威拒绝：{}",
            payload["error"].as_str().unwrap_or("未具名错误")
        ));
    }
    let r: AuthorityReply = serde_json::from_value(payload.clone()).map_err(error)?;
    validate_authority_reply(
        p,
        (&a.authority_id, &a.authority_epoch),
        op,
        command,
        release,
        &r,
    )?;
    Ok(r)
}
fn authority(
    p: &Profile,
    a: &Authority,
    epoch: i64,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
) -> Result<AuthorityReply, String> {
    let frame = authority_frame(p, a, epoch, op, command, release)?;
    let connection = authority_connect(a)?;
    authority_exchange(p, a, op, command, release, connection, &frame)
}

fn validate_authority_reply<C: CommandRecord>(
    p: &C::Profile,
    auth: (&str, &str),
    op: &str,
    command: &C,
    release: Option<&str>,
    r: &Receipt<C, C::Tick>,
) -> Result<(), String> {
    if r.protocol != AUTHORITY_WIRE
        || r.session_id != p.session_id()
        || r.session_generation != p.session_generation()
        || r.authority_id != auth.0
        || r.authority_epoch != auth.1
        || r.command_id != command.id()
        || r.command_hash != hash(command)
        || r.command != *command
        || r.receipt_id.is_empty()
    {
        return Err("IdentityConflict：权威回执未绑定原命令/内容/会话/身份".into());
    }
    let expected = if op == "QueryReleasedExact" {
        "ReleasedExact"
    } else {
        "ExecuteCommitted"
    };
    if r.commit_ns.into() < 0 {
        return Err("InvalidDomain：权威提交时刻不得为负".into());
    }
    if r.state != expected {
        return Err(format!(
            "MissingDependency：权威结果为{}，需要{expected}",
            r.state
        ));
    }
    if release.is_some() && r.release_receipt_id.as_deref() != release {
        return Err("IdentityConflict：S 收据未绑定本次精确交付".into());
    }
    Ok(())
}

fn get(
    c: &Connection,
    id: &str,
) -> Result<Option<(String, String, String, Option<String>)>, String> {
    c.query_row(
        "SELECT command,release_receipt,state,attempt_batch FROM x_exact_commands WHERE id=?1",
        [id],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
    )
    .optional()
    .map_err(error)
}
fn query_command(c: &Connection, p: &Profile, id: &str) -> Result<Value, String> {
    match get(c, id)? {
        None => Ok(json!({"kind":"ExactCommandState","command_id":id,"state":"NoRecord"})),
        Some((_, release, state, _)) => {
            let (clock, evidence): (String, String) = c
                .query_row(
                    "SELECT accept_clock,release_evidence FROM x_exact_commands WHERE id=?1",
                    [id],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(error)?;
            let clock: Value = serde_json::from_str(&clock).map_err(error)?;
            let evidence: AuthorityReply = serde_json::from_str(&evidence).map_err(error)?;
            Ok(
                json!({"kind":"ExactCommandState","command_id":id,"state":state,"x_accept":clock,"causal_refs":[{"authority_id":p.e.authority_id,"authority_epoch":p.e.authority_epoch,"receipt_id":release,"command_hash":evidence.command_hash,"release_commit_ns":evidence.commit_ns}]}),
            )
        }
    }
}
fn accept(
    c: &mut Connection,
    p: &Profile,
    epoch: i64,
    command: ExactCommand,
) -> Result<Value, String> {
    if store::pending_batch(c)?.is_some() {
        return Err("PendingBatch：未完成批次只允许同内容恢复或只读".into());
    }
    let received_ns = logical_now(c)?;
    let raw = canonical_json(&serde_json::to_value(&command).map_err(error)?);
    if let Some((old, _, _, _)) = get(c, &command.command_id)? {
        if raw != old {
            return Err("IdentityConflict：同 command_id 改变内容/epoch".into());
        }
        return query_command(c, p, &command.command_id);
    }
    command.validate(p, epoch)?;
    let released = authority(p, &p.e, epoch, "QueryReleasedExact", &command, None)?;
    let clock = AcceptClock {
        received_ns: DecimalTick(received_ns),
        first_known_ns: DecimalTick(received_ns),
        commit_ns: DecimalTick(received_ns),
    };
    validate_accept_clock(&clock, released.commit_ns.0)?;
    c.execute("INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence) VALUES(?1,?2,?3,'Accepted',NULL,?4,?5)",params![command.command_id,raw,released.receipt_id,canonical_json(&serde_json::to_value(&clock).map_err(error)?),canonical_json(&serde_json::to_value(&released).map_err(error)?)]).map_err(error)?;
    query_command(c, p, &command.command_id)
}
fn command_id(change: &Change) -> &str {
    match change {
        Change::Submit { order } | Change::Replace { order } => &order.command_id,
        Change::Cancel { command_id, .. } => command_id,
    }
}
fn execute(c: &mut Connection, p: &Profile, epoch: i64, mut batch: Batch) -> Result<Value, String> {
    batch.normalize();
    let encoded = canonical_json(&serde_json::to_value(&batch).map_err(error)?);
    if store::pending_batch(c)?.is_some_and(|old| old != encoded) {
        return Err("PendingBatch：未完成批次不得由另一批推进".into());
    }
    if let Some(result) = store::replay_batch(c, &batch)? {
        return Ok(result);
    }
    // 完整输入/模型校验必须先于 S 资格消费和 MayHaveCalled。
    store::validate_batch(c, &batch)?;
    let mut ids = std::collections::BTreeSet::new();
    let mut commands = Vec::new();
    for change in &batch.close_changes {
        let id = command_id(change);
        if !ids.insert(id.to_owned()) {
            return Err("IdentityConflict：批内重复 command".into());
        }
        let (raw, release, state, attempt) =
            get(c, id)?.ok_or("MissingDependency：X 尚未接纳精确命令")?;
        if state != "Accepted"
            && !((state == "MayHaveCalled"
                || state == "ExecutionReady"
                || state == "ExecutionRequested")
                && attempt.as_deref()
                    == Some(canonical_json(&serde_json::to_value(&batch).map_err(error)?).as_str()))
        {
            return Err("IdentityConflict：该 command 已作用于另一批次".into());
        }
        let command: ExactCommand = serde_json::from_str(&raw).map_err(error)?;
        command.validate(p, epoch)?;
        if command.change != *change {
            return Err("IdentityConflict：批次改变精确命令".into());
        }
        let op = match state.as_str() {
            "Accepted" => Some("RequestConditionalExecution"),
            "ExecutionRequested" => Some("QueryExecuteCommitted"),
            _ => None,
        };
        // 帧界超限是确定未发出的失败，须在持久 PendingBatch 前拒绝，否则同批恢复永远超限。
        let call = match op {
            Some(op) => Some((
                op,
                authority_frame(p, &p.s, epoch, op, &command, Some(&release))?,
            )),
            None => None,
        };
        commands.push((command, release, call));
    }
    let pending_tx = c.transaction().map_err(error)?;
    pending_tx.execute("INSERT INTO x_sim_meta(k,v) VALUES('pending_batch',?1) ON CONFLICT(k) DO UPDATE SET v=excluded.v",[&encoded]).map_err(error)?;
    pending_tx.execute("INSERT INTO x_sim_meta(k,v) VALUES('pending_epoch',?1) ON CONFLICT(k) DO UPDATE SET v=excluded.v",[epoch.to_string()]).map_err(error)?;
    pending_tx.commit().map_err(error)?;
    let mut executed_records = Vec::new();
    for (command, release, call) in commands {
        // AcceptExact 不产生调用权；在真正模型动作前才取得本命令 S 终态。
        let executed = match call {
            Some((op, frame)) => {
                let connection = authority_connect(&p.s)?;
                if op == "RequestConditionalExecution" {
                    c.execute("UPDATE x_exact_commands SET state='ExecutionRequested',attempt_batch=?2 WHERE id=?1 AND state='Accepted'",params![command.command_id,encoded]).map_err(error)?;
                    // 测试钩：把这次持久写拉长到超过对端期限，复现慢盘。
                    #[cfg(test)]
                    if std::env::var("ISSUE1381_TEST_SLOW_CLAIM").is_ok() {
                        std::thread::sleep(Duration::from_millis(p.timeout_ms + 200));
                    }
                }
                authority_exchange(p, &p.s, op, &command, Some(&release), connection, &frame)?
            }
            None => {
                let raw: String = c
                    .query_row(
                        "SELECT execute_evidence FROM x_exact_commands WHERE id=?1",
                        [&command.command_id],
                        |r| r.get(0),
                    )
                    .map_err(error)?;
                let evidence: Value = serde_json::from_str(&raw).map_err(error)?;
                validate_execution_record(p, &command, &release, &evidence, batch.bar.index)?
            }
        };
        let eligibility = match &command.change {
            Change::Submit { order } | Change::Replace { order } => &order.eligibility_ref,
            Change::Cancel {
                eligibility_ref, ..
            } => eligibility_ref,
        };
        if eligibility != &executed.receipt_id {
            return Err("IdentityConflict：命令资格引用未绑定 S 实际提交收据".into());
        }
        let claimed_ns = batch.bar.index;
        if claimed_ns < executed.commit_ns.0 {
            return Err("InvalidDomain：X 调用占有早于 S 持久提交".into());
        }
        let evidence = json!({"reply":executed,"claimed_ns":claimed_ns.to_string()});
        c.execute("UPDATE x_exact_commands SET state='ExecutionReady',attempt_batch=?2,execute_evidence=COALESCE(execute_evidence,?3) WHERE id=?1 AND state IN ('ExecutionRequested','ExecutionReady')",params![command.command_id,encoded,canonical_json(&evidence)]).map_err(error)?;
        executed_records.push((command.command_id, evidence));
    }
    let tx = c.transaction().map_err(error)?;
    tx.execute("INSERT INTO x_sim_meta(k,v) VALUES('pending_batch',?1) ON CONFLICT(k) DO UPDATE SET v=excluded.v",[&encoded]).map_err(error)?;
    for (id, evidence) in &executed_records {
        let changed=tx.execute("UPDATE x_exact_commands SET state='MayHaveCalled',attempt_batch=?2,execute_evidence=COALESCE(execute_evidence,?3) WHERE id=?1 AND (state='ExecutionReady' OR (state='MayHaveCalled' AND attempt_batch=?2))",params![id,encoded,canonical_json(evidence)]).map_err(error)?;
        if changed != 1 {
            return Err("IdentityConflict：X 同命令调用占有冲突".into());
        }
    }
    tx.commit().map_err(error)?;
    #[cfg(test)]
    if std::env::var("ISSUE1381_TEST_CRASH_AFTER_CLAIM")
        .ok()
        .as_deref()
        == Some(batch.request_id.as_str())
    {
        std::process::exit(43);
    }
    // 仅本地模拟 adapter 有已验证的同批 SQLite 幂等合同；此恢复许可不适用于网络场所。
    store::commit_batch_with_commands(c, &batch, &ids.into_iter().collect::<Vec<_>>())
}

fn validate_pending_epoch(c: &Connection, epoch: i64) -> Result<(), String> {
    let saved: Option<String> = c
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='pending_epoch'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(error)?;
    if store::pending_batch(c)?.is_some() {
        let saved: i64 = saved
            .ok_or("IdentityConflict：pending缺原writer epoch")?
            .parse()
            .map_err(error)?;
        if saved != epoch {
            return Err("PendingBatch：不兼容pending换代须在writer epoch写入前拒绝".into());
        }
    } else if saved.is_some() {
        return Err("IdentityConflict：游离pending epoch".into());
    }
    Ok(())
}

/// 在 bin 写入 writer_epoch 之前检查已有冻结合同与接纳记录。
pub fn validate_existing(c: &Connection, p: &Profile, epoch: i64) -> Result<(), String> {
    audit_existing::<ExactCommand>(c, p, epoch)
}

/// 仅只读冷审与 E 固定批事务可选 C2 封存 `/2` 格式；不供 X 初始化或续写使用。
#[cfg_attr(not(test), allow(dead_code))]
pub(super) fn audit_archived_v2(
    tx: &rusqlite::Transaction<'_>,
    p: &Profile,
    epoch: i64,
) -> Result<(), String> {
    audit_existing::<archive_v2::ArchivedCommand>(tx, p, epoch)
}

pub(super) struct AuditedArchiveIdentity {
    pub(super) profile_revision: String,
    pub(super) archive_layout: &'static str,
    pub(super) claimed_ns_audit_policy: &'static str,
    pub(super) condition_audit_policy: &'static str,
    pub(super) condition_audit_unproven: &'static [&'static str],
    pub(super) writer_epoch: i64,
    pub(super) session_id: String,
    pub(super) session_generation: String,
    pub(super) x_id: String,
    pub(super) source_namespace: String,
    pub(super) source_epoch: String,
    pub(super) model_content_hash: String,
    pub(super) e_authority_id: String,
    pub(super) e_authority_epoch: String,
}

enum ArchiveProfileInner {
    EarlyV1(archive_v1::EarlyProfile),
    LateV1(archive_v1::LateV1Profile),
    V2(Profile),
    V3(Profile),
}

/// 按外层 `profile_revision` + 内层 `exact_profile_revision` + 冻结键集判别出的归档 profile。
/// 仅用于只读冷审（`inspect_*`）与 E 固定批核档（`intake::committed_capture_batch`），绝不供 X 续写。
pub(super) struct ArchiveProfile(ArchiveProfileInner);

impl ArchiveProfile {
    fn as_audit_profile(&self) -> &dyn AuditProfile {
        match &self.0 {
            ArchiveProfileInner::EarlyV1(p) => p,
            ArchiveProfileInner::LateV1(p) => p,
            ArchiveProfileInner::V2(p) | ArchiveProfileInner::V3(p) => p,
        }
    }

    pub(super) fn identity(&self, revision: String, writer_epoch: i64) -> AuditedArchiveIdentity {
        let p = self.as_audit_profile();
        let (
            archive_layout,
            claimed_ns_audit_policy,
            condition_audit_policy,
            condition_audit_unproven,
        ) = match &self.0 {
            ArchiveProfileInner::EarlyV1(_) => (
                archive_v1::EarlyArchivedCommand::ARCHIVE_LAYOUT,
                archive_v1::EarlyArchivedCommand::CLAIMED_NS_AUDIT_POLICY,
                archive_v1::EarlyArchivedCommand::CONDITION_AUDIT_POLICY,
                archive_v1::EarlyArchivedCommand::CONDITION_AUDIT_UNPROVEN,
            ),
            ArchiveProfileInner::LateV1(_) => (
                archive_v1::LateArchivedCommand::ARCHIVE_LAYOUT,
                archive_v1::LateArchivedCommand::CLAIMED_NS_AUDIT_POLICY,
                archive_v1::LateArchivedCommand::CONDITION_AUDIT_POLICY,
                archive_v1::LateArchivedCommand::CONDITION_AUDIT_UNPROVEN,
            ),
            ArchiveProfileInner::V2(_) => (
                archive_v2::ArchivedCommand::ARCHIVE_LAYOUT,
                archive_v2::ArchivedCommand::CLAIMED_NS_AUDIT_POLICY,
                archive_v2::ArchivedCommand::CONDITION_AUDIT_POLICY,
                archive_v2::ArchivedCommand::CONDITION_AUDIT_UNPROVEN,
            ),
            ArchiveProfileInner::V3(_) => (
                ExactCommand::ARCHIVE_LAYOUT,
                ExactCommand::CLAIMED_NS_AUDIT_POLICY,
                ExactCommand::CONDITION_AUDIT_POLICY,
                ExactCommand::CONDITION_AUDIT_UNPROVEN,
            ),
        };
        let (e_authority_id, e_authority_epoch) = p.e_identity();
        AuditedArchiveIdentity {
            profile_revision: revision,
            archive_layout,
            claimed_ns_audit_policy,
            condition_audit_policy,
            condition_audit_unproven,
            writer_epoch,
            session_id: p.session_id().to_owned(),
            session_generation: p.session_generation().to_owned(),
            x_id: p.x_id().to_owned(),
            source_namespace: p.source_namespace().to_owned(),
            source_epoch: p.source_epoch().to_owned(),
            model_content_hash: hash(p.model()),
            e_authority_id: e_authority_id.to_owned(),
            e_authority_epoch: e_authority_epoch.to_owned(),
        }
    }

    pub(super) fn audit(&self, tx: &rusqlite::Transaction<'_>, epoch: i64) -> Result<(), String> {
        match &self.0 {
            ArchiveProfileInner::EarlyV1(p) => {
                audit_existing::<archive_v1::EarlyArchivedCommand>(tx, p, epoch)
            }
            ArchiveProfileInner::LateV1(p) => {
                audit_existing::<archive_v1::LateArchivedCommand>(tx, p, epoch)
            }
            ArchiveProfileInner::V2(p) => {
                audit_existing::<archive_v2::ArchivedCommand>(tx, p, epoch)
            }
            ArchiveProfileInner::V3(p) => audit_existing::<ExactCommand>(tx, p, epoch),
        }
    }
}

/// 在任何 `authority_profile` 解码之前，先核对外层 `x_meta.profile_revision`
/// 与内层 `x_sim_meta.exact_profile_revision` 一致性，阻断跨代混装。
pub(super) fn check_inner_revision(tx: &Connection, revision: &str) -> Result<(), String> {
    let expected = match revision {
        super::EXACT_PROFILE_REVISION => Some(super::EXACT_PROFILE_REVISION),
        "x-execution-profile/2" => Some("x-execution-profile/2"),
        "x-execution-profile/1" => None,
        other => {
            return Err(format!("VersionUnsupported：未知历史模拟库版本 `{other}`"));
        }
    };
    let actual: Option<String> = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='exact_profile_revision'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(storage_ro)?;
    if actual.as_deref() != expected {
        return Err("VersionUnsupported：历史模拟库内层版本与所选格式不符".into());
    }
    Ok(())
}

/// 按版本与冻结键集严格判别归档 profile：
/// `/2` 与 `/3` 恒直接解码完整 12 键/6 键 `Profile`；
/// `/1` 先按严格键集区分早期（11 键 + 3 键）与后期（12 键 + 6 键），不回退降格。
pub(super) fn parse_archive_profile(
    revision: &str,
    raw_profile: &str,
) -> Result<ArchiveProfile, String> {
    let val = strict_json(raw_profile.as_bytes())?;
    let inner = match revision {
        super::EXACT_PROFILE_REVISION => {
            ArchiveProfileInner::V3(serde_json::from_value(val).map_err(error)?)
        }
        "x-execution-profile/2" => {
            ArchiveProfileInner::V2(serde_json::from_value(val).map_err(error)?)
        }
        "x-execution-profile/1" => match archive_v1::classify_v1_profile(&val)? {
            archive_v1::V1ProfileLayout::Early => {
                ArchiveProfileInner::EarlyV1(serde_json::from_value(val).map_err(error)?)
            }
            archive_v1::V1ProfileLayout::Late => {
                ArchiveProfileInner::LateV1(serde_json::from_value(val).map_err(error)?)
            }
        },
        other => {
            return Err(format!("VersionUnsupported：未知历史模拟库版本 `{other}`"));
        }
    };
    Ok(ArchiveProfile(inner))
}

fn audit_existing<C: CommandRecord>(
    c: &Connection,
    p: &C::Profile,
    epoch: i64,
) -> Result<(), String> {
    p.validate_profile()?;
    let exists: bool = c
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_sim_meta')",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    if exists {
        let version: Option<String> = c
            .query_row(
                "SELECT v FROM x_sim_meta WHERE k='exact_profile_revision'",
                [],
                |r| r.get(0),
            )
            .optional()
            .map_err(error)?;
        if version.as_deref() != C::INNER_REVISION {
            return Err("VersionUnsupported：历史模拟库内层版本与所选格式不符".into());
        }
        validate_pending_epoch(c, epoch)?;
        store::audit_history(c)?;
        let frozen: Option<String> = c
            .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
                r.get(0)
            })
            .optional()
            .map_err(error)?;
        let expected = canonical_json(&json!({
            "model": p.model(),
            "source_namespace": p.source_namespace(),
            "source_epoch": p.source_epoch(),
        }));
        if frozen.as_ref().is_some_and(|s| s != &expected) {
            return Err("IdentityConflict：X 模型或事实来源已冻结".into());
        }
        let prior: Option<String> = c
            .query_row(
                "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
                [],
                |r| r.get(0),
            )
            .optional()
            .map_err(error)?;
        let binding = canonical_json(&serde_json::to_value(p).map_err(error)?);
        if prior.as_ref() != Some(&binding) {
            return Err("IdentityConflict：X 权威端点合同已冻结".into());
        }
    }
    let commands:bool=c.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_exact_commands')",[],|r|r.get(0)).map_err(error)?;
    if commands {
        audit_accepts::<C>(c, p)?;
        audit_execution::<C>(c, p)?;
    } else if exists {
        return Err("IdentityConflict：模拟历史缺命令权威表".into());
    }
    Ok(())
}

/// 必须由调用方持有SQLite事务；X launcher把自身meta/epoch纳入同一次提交。
pub fn initialize_in_transaction(
    c: &rusqlite::Transaction<'_>,
    p: &Profile,
    epoch: i64,
) -> Result<(), String> {
    p.validate()?;
    validate_existing(c, p, epoch)?;
    let exists: bool = c
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_sim_meta')",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    if exists {
        return Ok(());
    }
    store::initialize_in_transaction(c, &p.model, &p.source_namespace, &p.source_epoch)?;
    c.execute_batch("CREATE TABLE x_exact_commands(id TEXT PRIMARY KEY,command TEXT NOT NULL,release_receipt TEXT NOT NULL,state TEXT NOT NULL,attempt_batch TEXT,accept_clock TEXT NOT NULL,release_evidence TEXT NOT NULL,execute_evidence TEXT) STRICT;").map_err(error)?;
    c.execute(
        "INSERT INTO x_sim_meta VALUES('authority_profile',?1),('exact_profile_revision',?2)",
        params![
            canonical_json(&serde_json::to_value(p).map_err(error)?),
            super::EXACT_PROFILE_REVISION
        ],
    )
    .map_err(error)?;
    Ok(())
}

pub fn serve(c: &mut Connection, p: &Profile, epoch: i64) -> Result<(), String> {
    let tx = c.transaction().map_err(error)?;
    initialize_in_transaction(&tx, p, epoch)?;
    #[cfg(test)]
    if std::env::var("ISSUE1381_TEST_INIT_INTERRUPT")
        .ok()
        .as_deref()
        == Some("before")
    {
        std::process::exit(44);
    }
    tx.commit().map_err(error)?;
    #[cfg(test)]
    if std::env::var("ISSUE1381_TEST_INIT_INTERRUPT")
        .ok()
        .as_deref()
        == Some("after")
    {
        std::process::exit(45);
    }
    let timeout = Duration::from_millis(p.timeout_ms);
    serve_unix(
        Path::new(&p.socket),
        TransportBounds {
            frame: p.max_frame_bytes,
            read: timeout,
            write: timeout,
            response: timeout.saturating_mul(4),
            queue: 16,
            connections: 16,
        },
        validate_frame,
        |v| {
            let result = (|| {
                let r: Request = serde_json::from_value(v.clone()).map_err(error)?;
                match r.op.as_str() {
                    "AcceptExact" => accept(
                        c,
                        p,
                        epoch,
                        serde_json::from_value(r.payload).map_err(error)?,
                    ),
                    "AdvanceBar" => execute(
                        c,
                        p,
                        epoch,
                        serde_json::from_value(r.payload).map_err(error)?,
                    ),
                    "QueryCommand" => {
                        let id = r
                            .payload
                            .as_str()
                            .ok_or("InvalidDomain：QueryCommand 身份须字符串")?;
                        query_command(c, p, id)
                    }
                    "QueryBatch" => store::read_batch(
                        c,
                        r.payload
                            .as_str()
                            .ok_or("InvalidDomain：QueryBatch 身份须字符串")?,
                    ),
                    "QueryOriginal" => store::read_original(
                        c,
                        r.payload
                            .as_str()
                            .ok_or("InvalidDomain：QueryOriginal 身份须字符串")?,
                    ),
                    _ => Err("UnsupportedCapability：未知 X 操作".into()),
                }
            })();
            match result {
                Ok(v) => v,
                Err(e) => json!({"kind":"Error","error":e}),
            }
        },
    )
}

fn storage_ro(e: impl std::fmt::Display) -> String {
    format!("StorageUnavailable：{e}")
}

fn open_readonly_db(db: &Path) -> Result<Connection, String> {
    let conn =
        Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(storage_ro)?;
    conn.busy_timeout(Duration::from_secs(2))
        .map_err(storage_ro)?;
    Ok(conn)
}

fn audit_readonly_tx(tx: &rusqlite::Transaction<'_>) -> Result<AuditedArchiveIdentity, String> {
    let has_meta: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_meta')",
            [],
            |r| r.get(0),
        )
        .map_err(storage_ro)?;
    if !has_meta {
        return Err("InvalidDomain：X 库尚未初始化 x_meta".into());
    }
    let meta = |key: &str| -> Result<String, String> {
        tx.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .map_err(storage_ro)
    };
    if meta("history_simulation")? != "true" || meta("profile_mode")? != "simulation" {
        return Err("InvalidDomain：该 X 库不是历史模拟执行库".into());
    }
    let revision = meta("profile_revision")?;
    let epoch: i64 = meta("writer_epoch")?.parse().map_err(error)?;
    check_inner_revision(tx, &revision)?;
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(storage_ro)?;
    let parsed = parse_archive_profile(&revision, &raw_profile)?;
    parsed.audit(tx, epoch)?;
    Ok(parsed.identity(revision, epoch))
}

fn pending_and_frontier(
    tx: &Connection,
) -> Result<(Option<String>, Option<String>, Option<String>, Option<i64>), String> {
    let pending_batch_id = match store::pending_batch(tx)? {
        Some(raw) => {
            let b: Batch = serde_json::from_str(&raw).map_err(error)?;
            Some(b.request_id)
        }
        None => None,
    };
    let pending_epoch: Option<String> = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='pending_epoch'",
            [],
            |r| r.get(0),
        )
        .optional()
        .map_err(storage_ro)?;
    let raw_state: String = tx
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(storage_ro)?;
    let state: super::model::State = serde_json::from_str(&raw_state).map_err(error)?;
    Ok((
        pending_batch_id,
        pending_epoch,
        state.last_request_id,
        state.last_bar,
    ))
}

/// #1407 C3 R3–R5：对 `/1`（早期/后期）、`/2`、`/3` 历史模拟 X 库的只读冷审摘要查询（不获取 writer lock、不触发 WAL checkpoint）。
pub fn inspect_history(db: &Path) -> Result<Value, String> {
    let mut conn = open_readonly_db(db)?;
    let tx = conn.transaction().map_err(storage_ro)?;
    let identity = audit_readonly_tx(&tx)?;
    let (pending_batch_id, pending_epoch, last_committed_batch_id, last_bar_index) =
        pending_and_frontier(&tx)?;

    let mut batches = Vec::new();
    {
        let mut stmt = tx
            .prepare("SELECT id, result FROM x_sim_batches ORDER BY rowid")
            .map_err(storage_ro)?;
        let rows = stmt
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(storage_ro)?;
        for row in rows {
            let (id, raw) = row.map_err(storage_ro)?;
            let parsed = strict_json(raw.as_bytes())?;
            let orig_count = parsed["originals"].as_array().map_or(0, Vec::len);
            batches.push(json!({
                "batch_id": id,
                "bar_index": parsed["bar_index"],
                "batch_receipt_sha256": sha256_hex(raw.as_bytes()),
                "state_content_hash": parsed["state_content_hash"],
                "original_count": orig_count,
            }));
        }
    }

    let mut commands = Vec::new();
    {
        let mut stmt = tx
            .prepare("SELECT id, state, attempt_batch, release_receipt, execute_evidence IS NOT NULL FROM x_exact_commands ORDER BY id")
            .map_err(storage_ro)?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, bool>(4)?,
                ))
            })
            .map_err(storage_ro)?;
        for row in rows {
            let (id, state, attempt, receipt, has_exec) = row.map_err(storage_ro)?;
            let attempt_batch_id = match attempt {
                Some(raw) => {
                    let b: Batch = serde_json::from_str(&raw).map_err(error)?;
                    Some(b.request_id)
                }
                None => None,
            };
            commands.push(json!({
                "command_id": id,
                "state": state,
                "attempt_batch_id": attempt_batch_id,
                "release_receipt": receipt,
                "has_execute_evidence": has_exec,
            }));
        }
    }

    let mut originals = Vec::new();
    {
        let mut stmt = tx
            .prepare("SELECT id FROM x_sim_originals ORDER BY rowid")
            .map_err(storage_ro)?;
        let rows = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .map_err(storage_ro)?;
        for row in rows {
            originals.push(row.map_err(storage_ro)?);
        }
    }

    tx.commit().map_err(storage_ro)?;
    Ok(json!({
        "kind": "HistorySimulationArchiveSummary",
        "read_only": true,
        "profile_revision": identity.profile_revision,
        "archive_layout": identity.archive_layout,
        "execute_evidence_claimed_ns_audit_policy": identity.claimed_ns_audit_policy,
        "condition_audit_policy": identity.condition_audit_policy,
        "condition_audit_unproven": identity.condition_audit_unproven,
        "writer_epoch": identity.writer_epoch.to_string(),
        "session_id": identity.session_id,
        "session_generation": identity.session_generation,
        "x_id": identity.x_id,
        "source_namespace": identity.source_namespace,
        "source_epoch": identity.source_epoch,
        "model_content_hash": identity.model_content_hash,
        "last_committed_batch_id": last_committed_batch_id,
        "last_bar_index": last_bar_index,
        "pending_batch_id": pending_batch_id,
        "pending_epoch": pending_epoch,
        "committed_batches": batches,
        "commands": commands,
        "originals": originals,
    }))
}

/// #1407 C3 R3–R6：对 `/1`（早期/后期）、`/2`、`/3` 历史模拟 X 库的只读命令状态查询。
/// 保留 `QueryCommand` 原字段（`state`、`x_accept`、`causal_refs`），并显式回传 `archive_layout`、
/// `condition_audit_policy`、`condition_audit_unproven`、`attempt_batch_id`、`attempt_batch_bar_index`、
/// `pending_batch_id`、`execute_evidence`、`execute_evidence_claimed_ns_audit` 与已提交前沿，逐态覆盖
/// `Accepted`、`ExecutionReady`、`ExecutionRequested`、`MayHaveCalled`、`Observed` 与 `NoRecord`。
pub fn inspect_command(db: &Path, id: &str) -> Result<Value, String> {
    let mut conn = open_readonly_db(db)?;
    let tx = conn.transaction().map_err(storage_ro)?;
    let identity = audit_readonly_tx(&tx)?;
    let (pending_batch_id, pending_epoch, last_committed_batch_id, last_bar_index) =
        pending_and_frontier(&tx)?;
    let row: Option<(String, String, Option<String>, String, String, Option<String>)> = tx
        .query_row(
            "SELECT release_receipt, state, attempt_batch, accept_clock, release_evidence, execute_evidence FROM x_exact_commands WHERE id=?1",
            [id],
            |r| {
                Ok((
                    r.get(0)?,
                    r.get(1)?,
                    r.get(2)?,
                    r.get(3)?,
                    r.get(4)?,
                    r.get(5)?,
                ))
            },
        )
        .optional()
        .map_err(storage_ro)?;
    let out = match row {
        None => json!({
            "kind": "ExactCommandState",
            "command_id": id,
            "state": "NoRecord",
            "profile_revision": identity.profile_revision,
            "archive_layout": identity.archive_layout,
            "condition_audit_policy": identity.condition_audit_policy,
            "condition_audit_unproven": identity.condition_audit_unproven,
            "writer_epoch": identity.writer_epoch.to_string(),
            "pending_batch_id": pending_batch_id,
            "pending_epoch": pending_epoch,
            "last_committed_batch_id": last_committed_batch_id,
            "last_bar_index": last_bar_index,
            "read_only": true,
        }),
        Some((release_receipt, state, attempt, clock_raw, rel_raw, exec_raw)) => {
            let clock: Value = strict_json(clock_raw.as_bytes())?;
            let rel: Value = strict_json(rel_raw.as_bytes())?;
            let (attempt_batch_id, attempt_batch_bar_index) = match attempt {
                Some(raw) => {
                    let b: Batch = serde_json::from_str(&raw).map_err(error)?;
                    (Some(b.request_id), Some(b.bar.index))
                }
                None => (None, None),
            };
            let execute_evidence = match exec_raw {
                Some(raw) => strict_json(raw.as_bytes())?,
                None => Value::Null,
            };
            let claimed_ns_audit = if execute_evidence.is_null() {
                Value::Null
            } else {
                json!(identity.claimed_ns_audit_policy)
            };
            json!({
                "kind": "ExactCommandState",
                "command_id": id,
                "state": state,
                "x_accept": clock,
                "causal_refs": [{
                    "authority_id": identity.e_authority_id,
                    "authority_epoch": identity.e_authority_epoch,
                    "receipt_id": release_receipt,
                    "command_hash": rel["command_hash"],
                    "release_commit_ns": rel["commit_ns"],
                }],
                "attempt_batch_id": attempt_batch_id,
                "attempt_batch_bar_index": attempt_batch_bar_index,
                "pending_batch_id": pending_batch_id,
                "pending_epoch": pending_epoch,
                "has_execute_evidence": !execute_evidence.is_null(),
                "execute_evidence": execute_evidence,
                "execute_evidence_claimed_ns_audit": claimed_ns_audit,
                "condition_audit_policy": identity.condition_audit_policy,
                "condition_audit_unproven": identity.condition_audit_unproven,
                "profile_revision": identity.profile_revision,
                "archive_layout": identity.archive_layout,
                "writer_epoch": identity.writer_epoch.to_string(),
                "last_committed_batch_id": last_committed_batch_id,
                "last_bar_index": last_bar_index,
                "read_only": true,
            })
        }
    };
    tx.commit().map_err(storage_ro)?;
    Ok(out)
}

/// #1407 C3 R3：对 `/1`、`/2`、`/3` 历史模拟 X 库的只读已提交批查询（与原 X socket `QueryBatch` 同形）。
pub fn inspect_batch(db: &Path, id: &str) -> Result<Value, String> {
    let mut conn = open_readonly_db(db)?;
    let tx = conn.transaction().map_err(storage_ro)?;
    let _ = audit_readonly_tx(&tx)?;
    let raw: Option<String> = tx
        .query_row("SELECT result FROM x_sim_batches WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .optional()
        .map_err(storage_ro)?;
    let out = match raw {
        Some(raw) => strict_json(raw.as_bytes())?,
        None => {
            if let Some(pending_raw) = store::pending_batch(&tx)? {
                let b: Batch = serde_json::from_str(&pending_raw).map_err(error)?;
                if b.request_id == id {
                    return Err(format!(
                        "MissingDependency：批次 `{id}` 尚未提交（当前为未终态 pending_batch，不能按已提交终态批消费）"
                    ));
                }
            }
            return Err(format!("MissingDependency：未找到已提交批次 `{id}`"));
        }
    };
    tx.commit().map_err(storage_ro)?;
    Ok(out)
}

/// #1407 C3 R3：对 `/1`、`/2`、`/3` 历史模拟 X 库的只读原件查询（与原 X socket `QueryOriginal` 同形）。
pub fn inspect_original(db: &Path, id: &str) -> Result<Value, String> {
    let mut conn = open_readonly_db(db)?;
    let tx = conn.transaction().map_err(storage_ro)?;
    let _ = audit_readonly_tx(&tx)?;
    let raw: Option<String> = tx
        .query_row("SELECT raw FROM x_sim_originals WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .optional()
        .map_err(storage_ro)?;
    let out = match raw {
        Some(raw) => strict_json(raw.as_bytes())?,
        None => return Err(format!("MissingDependency：未找到已提交原件 `{id}`")),
    };
    tx.commit().map_err(storage_ro)?;
    Ok(out)
}

#[cfg(test)]
#[path = "runtime_c2_tests.rs"]
mod c2_tests;
#[cfg(test)]
mod clock_tests {
    use super::*;
    #[test]
    fn acceptance_clock_rejects_exactly_one_ns_early() {
        let mut c = AcceptClock {
            received_ns: 98,
            first_known_ns: 99,
            commit_ns: 101,
        };
        assert!(validate_accept_clock(&c, 100)
            .unwrap_err()
            .starts_with("InvalidDomain"));
        c.first_known_ns = 100;
        assert!(validate_accept_clock(&c, 100).is_ok());
    }
}
