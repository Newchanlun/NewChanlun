use super::{
    model::{Batch, Change, Model},
    store,
};
use crate::session_business_id as ids;
use crate::session_protocol::{canonical_json, positive, reply_envelope, sha256_hex};
use crate::session_transport::{
    read_frame, serve_unix, write_frame_observed, NoObserver, TransportBounds,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::os::unix::{fs::MetadataExt, net::UnixStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

#[path = "authority_binding.rs"]
mod authority_binding;
#[path = "authority_history.rs"]
mod authority_history;
pub use authority_binding::RebindInput;
use authority_binding::{Domains, History, Identities};

pub const WIRE: &str = "x-exact-simulation/1";
pub const AUTHORITY_WIRE: &str = "x-exact-authority/1";
const EXECUTION_PROFILE_V1: &str = "x-execution-profile/1";

/// 外层执行合同同时约束在线配置与持久归档；只有 simulation 可以选内层合同。
pub fn validate_execution_profile_header(
    revision: &str,
    mode: &str,
    history_simulation: bool,
) -> Result<(), String> {
    if revision != EXECUTION_PROFILE_V1 {
        return Err(format!(
            "VersionUnsupported：执行 profile 版本 `{revision}` 不是 {EXECUTION_PROFILE_V1}"
        ));
    }
    if !matches!(mode, "simulation" | "dry-run" | "experiment" | "production") {
        return Err(
            "InvalidDomain：执行 profile mode 必须是 simulation|dry-run|experiment|production"
                .into(),
        );
    }
    if history_simulation && mode != "simulation" {
        return Err("InvalidDomain：history_simulation 仅允许 simulation profile".into());
    }
    Ok(())
}
fn hash<T: Serialize>(v: &T) -> String {
    sha256_hex(canonical_json(&serde_json::to_value(v).expect("integer domain")).as_bytes())
}
fn encode<T: Serialize>(value: &T) -> Result<String, String> {
    Ok(canonical_json(&serde_json::to_value(value).map_err(error)?))
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
const X_BUSINESS: &str = "x-simulation-authority/2";
const X_DEPLOYMENT: &str = "x-simulation-deployment/1";
const DEPLOYMENT_SQL: &str = "CREATE TABLE x_sim_deployment(singleton INTEGER PRIMARY KEY CHECK(singleton=1), mapping TEXT NOT NULL, fingerprint TEXT NOT NULL) STRICT;";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct AuthorityIdentity {
    authority_id: String,
    authority_epoch: String,
    schema_revision: String,
    reply_namespace: String,
    producer_id: String,
}
impl AuthorityIdentity {
    fn local(self, socket: String) -> Authority {
        Authority {
            socket,
            authority_id: self.authority_id,
            authority_epoch: self.authority_epoch,
            schema_revision: self.schema_revision,
            reply_namespace: self.reply_namespace,
            producer_id: self.producer_id,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BusinessProfile {
    schema_revision: String,
    recovery_identity: Option<Identities>,
    model: Model,
    session_id: String,
    session_generation: String,
    x_id: String,
    source_namespace: String,
    source_epoch: String,
    e: AuthorityIdentity,
    s: AuthorityIdentity,
    conditions: Vec<Condition>,
    timeout_ms: u64,
    max_frame_bytes: usize,
}

impl BusinessProfile {
    fn validate_identity(&self) -> Result<(), String> {
        ids::name(&self.session_id, "session_id")?;
        positive(&self.session_generation, "session_generation")?;
        ids::domain_name(&self.x_id, "x_id")?;
        ids::namespace(&self.source_namespace, "source_namespace")?;
        ids::name(&self.source_epoch, "source_epoch")?;
        for authority in [&self.e, &self.s] {
            ids::name(&authority.authority_id, "authority_id")?;
            ids::name(&authority.authority_epoch, "authority_epoch")?;
            ids::reference(&authority.schema_revision, "schema_revision")?;
            ids::namespace(&authority.reply_namespace, "reply_namespace")?;
            ids::domain_name(&authority.producer_id, "producer_id")?;
        }
        let model = &self.model;
        ids::instrument(&model.symbol, "model.symbol")?;
        for (field, value) in [
            ("model.revision", &model.revision),
            ("model.quantity_unit", &model.quantity_unit),
            ("model.currency", &model.currency),
        ] {
            ids::name(value, field)?;
        }
        for (field, value) in [
            ("model.rd11_policy", &model.rd11_policy),
            ("fee_profile.reference", &model.fee_profile.reference),
            ("fee_profile.role_source", &model.fee_profile.role_source),
            (
                "fee_profile.market_slippage_source",
                &model.fee_profile.market_slippage_source,
            ),
        ] {
            ids::reference(value, field)?;
        }
        for condition in &self.conditions {
            ids::reference(&condition.condition_id, "condition_id")?;
            ids::reference(&condition.coverage_proof, "coverage_proof")?;
            for (field, refs) in [
                ("dependency_set", &condition.dependency_set),
                ("invalidation_sources", &condition.invalidation_sources),
                ("evidence_refs", &condition.evidence_refs),
            ] {
                for reference in refs {
                    ids::reference(reference, field)?;
                }
            }
        }
        // 模型族、RD12、投影/seed、检查阶段/能力/失败语义由 Profile::validate 的闭集校验。
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Deployment {
    schema_revision: String,
    recovery_domains: Option<Domains>,
    db: String,
    socket: String,
    e_socket: String,
    s_socket: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SplitProfile {
    business: Value,
    deployment: Value,
}

/// 旧版直接解析混合 profile；新版两份闭集单独解析，组装的 Profile 只向既有运行时供给参数。
pub struct ConfiguredProfile {
    profile: Profile,
    binding: Option<(Value, Value)>,
    recovery: Option<(Identities, Domains)>,
}
impl ConfiguredProfile {
    pub fn parse(value: Value) -> Result<Self, String> {
        if value.get("business").is_some() || value.get("deployment").is_some() {
            let split: SplitProfile = serde_json::from_value(value).map_err(error)?;
            return Self::split(split.business, split.deployment);
        }
        Self::legacy(value)
    }
    fn legacy(value: Value) -> Result<Self, String> {
        let profile: Profile = serde_json::from_value(value).map_err(error)?;
        profile.validate()?;
        Ok(Self {
            profile,
            binding: None,
            recovery: None,
        })
    }
    fn split(business: Value, deployment: Value) -> Result<Self, String> {
        let b: BusinessProfile = serde_json::from_value(business.clone()).map_err(error)?;
        let d: Deployment = serde_json::from_value(deployment.clone()).map_err(error)?;
        if b.schema_revision != X_BUSINESS || d.schema_revision != X_DEPLOYMENT {
            return Err("SchemaUnsupported：未知模拟 X 业务或部署版本".into());
        }
        if !Path::new(&d.db).is_absolute()
            || [&d.db, &d.socket, &d.e_socket, &d.s_socket]
                .iter()
                .any(|p| p.contains('\0'))
        {
            return Err("InvalidDomain：X 部署位置非法".into());
        }
        b.validate_identity()?;
        let recovery = match (b.recovery_identity, d.recovery_domains) {
            (Some(identity), Some(domains)) => {
                domains.validate(&d.db)?;
                Some((identity, domains))
            }
            (None, None) => None,
            _ => return Err(error("新版 X 的恢复身份与部署须同时固定")),
        };
        let profile = Profile {
            model: b.model,
            session_id: b.session_id,
            session_generation: b.session_generation,
            x_id: b.x_id,
            source_namespace: b.source_namespace,
            source_epoch: b.source_epoch,
            socket: d.socket,
            e: b.e.local(d.e_socket),
            s: b.s.local(d.s_socket),
            conditions: b.conditions,
            timeout_ms: b.timeout_ms,
            max_frame_bytes: b.max_frame_bytes,
        };
        profile.validate()?;
        if let Some((identity, _)) = &recovery {
            identity.validate(&profile)?;
        }
        Ok(Self {
            profile,
            binding: Some((business, deployment)),
            recovery,
        })
    }
    fn check_db(&self, db: &Path) -> Result<(), String> {
        if let Some((_, d)) = &self.binding {
            let expected = d["db"].as_str().unwrap();
            if Path::new(expected) != db {
                return Err("IdentityConflict：X DB 不等于固定部署".into());
            }
        }
        Ok(())
    }
    /// 只在启服前访问真实目录；离线核证只读冻结的部署原字节。
    pub fn check_serve_deployment(&self, db: &Path) -> Result<(), String> {
        self.check_db(db)?;
        if self.binding.is_some() {
            let p = &self.profile;
            let mut names = std::collections::BTreeSet::new();
            let mut objects = std::collections::BTreeSet::new();
            for socket in [&p.socket, &p.e.socket, &p.s.socket] {
                let target = socket_target(socket)?;
                if !names.insert(target.path) || target.object.is_some_and(|id| !objects.insert(id))
                {
                    return Err("IdentityConflict：X/E/S socket 实际目标重复".into());
                }
            }
        }
        Ok(())
    }
    pub fn initialize_in_transaction(
        &self,
        c: &rusqlite::Transaction<'_>,
        epoch: i64,
    ) -> Result<(), String> {
        initialize_bound(
            c,
            &self.profile,
            self.binding.as_ref(),
            self.identities(),
            epoch,
        )
    }
    fn identities(&self) -> Option<&Identities> {
        self.recovery.as_ref().map(|(identities, _)| identities)
    }

    /// 既有库、持有原 X writer lock；启动方不得用此入口初始化。
    pub fn rebind_in_transaction(
        &self,
        c: &rusqlite::Transaction<'_>,
        epoch: i64,
        input: &RebindInput,
    ) -> Result<(), String> {
        let (identities, domains) = self
            .recovery
            .as_ref()
            .ok_or("IdentityConflict：原 X 库没有创世恢复合同，不允许就地升级")?;
        let history = validate_bound(
            c,
            &self.profile,
            self.binding.as_ref(),
            Some(identities),
            epoch,
        )?
        .ok_or("IdentityConflict：恢复要求已初始化的 X 原库")?;
        history.append(c, &self.profile, identities, domains, input)
    }

    pub fn serve(&self, c: &mut Connection, epoch: i64) -> Result<(), String> {
        let tx = c.transaction().map_err(error)?;
        self.initialize_in_transaction(&tx, epoch)?;
        tx.commit().map_err(error)?;
        self.serve_initialized(c, epoch)
    }

    /// bin 已在原 writer lock 下提交初始化/重绑事务，之后才能发布 socket。
    pub fn serve_initialized(&self, c: &mut Connection, epoch: i64) -> Result<(), String> {
        let history = self
            .identities()
            .map(|ids| History::load(c, &self.profile, epoch, ids))
            .transpose()?;
        serve_initialized(c, &self.profile, history.as_ref(), epoch)
    }
}

struct SocketTarget {
    path: PathBuf,
    object: Option<(u64, u64)>,
}

fn socket_target(raw: &str) -> Result<SocketTarget, String> {
    let path = Path::new(raw);
    let parent = path.parent().ok_or("InvalidDomain：模拟 socket 缺父目录")?;
    let name = path
        .file_name()
        .ok_or("InvalidDomain：模拟 socket 缺文件名")?;
    let mut path = parent.canonicalize().map_err(io)?.join(name);
    let object = match path.symlink_metadata() {
        Ok(meta) => {
            let meta = if meta.is_symlink() {
                path = path.canonicalize().map_err(io)?;
                fs::metadata(&path).map_err(io)?
            } else {
                meta
            };
            Some((meta.dev(), meta.ino()))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => None,
        Err(e) => return Err(io(e)),
    };
    Ok(SocketTarget { path, object })
}

fn has_deployment(c: &Connection) -> Result<bool, String> {
    c.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE name='x_sim_deployment')",
        [],
        |r| r.get(0),
    )
    .map_err(error)
}
fn deployed(c: &Connection) -> Result<(String, String), String> {
    c.query_row(
        "SELECT mapping,fingerprint FROM x_sim_deployment WHERE singleton=1",
        [],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )
    .map_err(error)
}

/// E 只从选定的新版 X 部署读事实；同模型的另一会话或旧版库不是替代权威。
pub(crate) fn verify_intake_binding(
    c: &Connection,
    db: &Path,
    source: &Value,
    session: &Value,
) -> Result<(), String> {
    let raw: String = c
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    let business = crate::session_protocol::strict_json(raw.as_bytes())?;
    let (mapping, fingerprint) = deployed(c)?;
    let deployment = crate::session_protocol::strict_json(mapping.as_bytes())?;
    if fingerprint != hash(&deployment) {
        return Err("IdentityConflict：X 部署摘要不符".into());
    }
    let config = ConfiguredProfile::split(business.clone(), deployment)?;
    config.check_db(db)?;
    let writer_epoch: String = c
        .query_row(
            "SELECT value FROM x_meta WHERE key='writer_epoch'",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    if business["session_id"] != session["session_id"]
        || business["session_generation"] != session["session_generation"]
        || business["x_id"] != source["producer_id"]
        || business["source_namespace"] != source["source_namespace"]
        || business["source_epoch"] != source["source_epoch"]
        || source["producer_epoch"] != writer_epoch
        || source["model_content_hash"] != hash(&business["model"])
    {
        return Err("IdentityConflict：X 业务身份或事实写者未绑定".into());
    }
    Ok(())
}

/// 先分派持久的外层与内层合同，再核证因果记录和模型原件；不访问原部署。
pub fn audit_persisted(c: &Connection) -> Result<(), String> {
    let meta = |key| -> Result<String, String> {
        c.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .optional()
            .map_err(error)?
            .ok_or_else(|| format!("SchemaUnsupported：X 持久元数据缺 {key}"))
    };
    let revision = meta("profile_revision")?;
    let mode = meta("profile_mode")?;
    let history = meta("history_simulation")? == "true";
    validate_execution_profile_header(&revision, &mode, history)?;
    if !history {
        return Err("SchemaUnsupported：离线 audit 仅用于 simulation X".into());
    }
    let epoch = positive(&meta("writer_epoch")?, "writer_epoch")?;
    let raw: String = c
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    let business = crate::session_protocol::strict_json(raw.as_bytes())?;
    let config = if has_deployment(c)? {
        let (raw, _) = deployed(c)?;
        ConfiguredProfile::split(
            business,
            crate::session_protocol::strict_json(raw.as_bytes())?,
        )?
    } else {
        ConfiguredProfile::legacy(business)?
    };
    validate_bound(
        c,
        &config.profile,
        config.binding.as_ref(),
        config.identities(),
        epoch,
    )
    .map(|_| ())
}

impl Profile {
    pub fn validate(&self) -> Result<(), String> {
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
        validate_conditions(&self.conditions)
    }
}

/// 获准清单逐项带齐 IC「ConditionEvidence」九字段；含 ADR 0052 裁定二 E-Release 阶段的 `model_coverage`。
fn validate_conditions(list: &[Condition]) -> Result<(), String> {
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
    if !list.iter().any(|c| {
        c.condition_id == "model_coverage"
            && c.required_check_stages
                .iter()
                .any(|s| s == "E.ReleaseExact")
    }) {
        return Err("MissingDependency：获准条件清单缺 E-Release 阶段的 model_coverage".into());
    }
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
    pub session_id: String,
    pub session_generation: String,
    pub x_id: String,
    pub x_epoch: i64,
    pub symbol: String,
    pub projection_kind: String,
    pub change: Change,
    pub plan_hash: String,
    pub certificate_hash: String,
    pub certificate: Certificate,
}
impl ExactCommand {
    fn validate(&self, p: &Profile, epoch: i64) -> Result<(), String> {
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
            || self.plan_hash != hash(&self.change)
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
        if c.conditions != p.conditions {
            return Err("Unsupported：条件清单与获准 manifest 清单不逐项相等".into());
        }
        Ok(())
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
struct AuthorityReply {
    protocol: String,
    session_id: String,
    session_generation: String,
    authority_id: String,
    authority_epoch: String,
    command_id: String,
    command_hash: String,
    command: ExactCommand,
    state: String,
    receipt_id: String,
    release_receipt_id: Option<String>,
    commit_ns: i64,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct AcceptClock {
    received_ns: i64,
    first_known_ns: i64,
    commit_ns: i64,
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
fn validate_accept_clock(clock: &AcceptClock, release_commit_ns: i64) -> Result<(), String> {
    if release_commit_ns < 0
        || clock.received_ns < 0
        || clock.received_ns > clock.first_known_ns
        || clock.first_known_ns > clock.commit_ns
        || clock.first_known_ns < release_commit_ns
    {
        return Err("InvalidDomain：X 接纳时钟早于 E 持久交付或本地相位倒退".into());
    }
    Ok(())
}
fn audit_accepts(c: &Connection, p: &Profile) -> Result<(), String> {
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
        let clock: AcceptClock = serde_json::from_str(&clock).map_err(error)?;
        let release: AuthorityReply = serde_json::from_str(&release).map_err(error)?;
        if canonical_json(&serde_json::to_value(&release.command).map_err(error)?) != command {
            return Err("IdentityConflict：恢复交付与命令不符".into());
        }
        let command: ExactCommand = serde_json::from_str(&command).map_err(error)?;
        validate_authority_reply(p, &p.e, "QueryReleasedExact", &command, None, &release)?;
        validate_accept_clock(&clock, release.commit_ns)?;
    }
    Ok(())
}
fn audit_execution(c: &Connection, p: &Profile, history: Option<&History>) -> Result<(), String> {
    let pending = store::pending_batch(c)?;
    let mut required = std::collections::BTreeMap::new();
    let mut q = c
        .prepare("SELECT request FROM x_sim_batches")
        .map_err(error)?;
    let rows = q.query_map([], |r| r.get::<_, String>(0)).map_err(error)?;
    for row in rows {
        let raw = row.map_err(error)?;
        let b: Batch = serde_json::from_str(&raw).map_err(error)?;
        for change in b.close_changes {
            let id = command_id(&change).to_owned();
            if required.insert(id, (raw.clone(), change, false)).is_some() {
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
        for change in b.close_changes {
            let id = command_id(&change).to_owned();
            if required.insert(id, (raw.clone(), change, true)).is_some() {
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
        let command: ExactCommand = serde_json::from_str(&raw).map_err(error)?;
        command.validate(p, command.x_epoch)?;
        let released: AuthorityReply = serde_json::from_str(&released).map_err(error)?;
        if id != command.command_id || released.receipt_id != release {
            return Err("IdentityConflict：接纳身份或交付引用不符".into());
        }
        if let Some((batch, change, is_pending)) = required.remove(&id) {
            if command.change != change {
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
                if history.is_none() {
                    validate_execution_record(p, &command, &release, &evidence)?;
                }
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

fn validate_execution_record(
    p: &Profile,
    command: &ExactCommand,
    release: &str,
    evidence: &Value,
) -> Result<AuthorityReply, String> {
    let reply: AuthorityReply = serde_json::from_value(evidence["reply"].clone()).map_err(error)?;
    validate_authority_reply(
        p,
        &p.s,
        "RequestConditionalExecution",
        command,
        Some(release),
        &reply,
    )?;
    let eligibility = match &command.change {
        Change::Submit { order } | Change::Replace { order } => &order.eligibility_ref,
        Change::Cancel {
            eligibility_ref, ..
        } => eligibility_ref,
    };
    if eligibility != &reply.receipt_id
        || evidence["claimed_ns"]
            .as_i64()
            .is_none_or(|t| t < reply.commit_ns)
    {
        return Err("IdentityConflict：持久S执行证据与资格/调用占有时刻不符".into());
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
    checked_frame(p, a, epoch, payload)
}
fn checked_frame(
    p: &Profile,
    a: &Authority,
    epoch: i64,
    payload: Value,
) -> Result<AuthorityFrame, String> {
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
/// 当前 S 的只读查询显式携带发生时的原请求；查询不能变成新的资格申请。
fn query_execution_frame(
    p: &Profile,
    epoch: i64,
    command: &ExactCommand,
    release: &str,
    attempt: &Value,
) -> Result<AuthorityFrame, String> {
    let frame = authority_frame(
        p,
        &p.s,
        epoch,
        "QueryExecuteCommitted",
        command,
        Some(release),
    )?;
    let mut payload = frame.envelope["payload"].clone();
    payload["original_attempt"] = attempt.clone();
    checked_frame(p, &p.s, epoch, payload)
}

fn authority_exchange(
    p: &Profile,
    mut stream: UnixStream,
    frame: &AuthorityFrame,
) -> Result<Value, String> {
    // 连接之后、写帧之前 X 先持久 ExecutionRequested（synchronous=FULL）。
    // 本地落盘不计入对端期限，不能在一个字节未发时误入只读恢复（#1407 C2）。
    let deadline = Instant::now() + Duration::from_millis(p.timeout_ms);
    write_frame_observed(&mut stream, &frame.bytes, deadline, &mut NoObserver)?;
    stream.shutdown(std::net::Shutdown::Write).map_err(io)?;
    read_frame(&mut stream, p.max_frame_bytes, deadline, json_frame)
}

fn checked_payload<'a>(
    p: &Profile,
    a: &Authority,
    frame: &AuthorityFrame,
    reply: &'a Value,
) -> Result<&'a Value, String> {
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
    if *reply != expected {
        return Err("IdentityConflict：权威回复信封的身份/epoch/因果/规范字节不符".into());
    }
    let payload = &reply["payload"];
    if payload["kind"] == "Error" {
        return Err(format!(
            "MissingDependency：权威拒绝：{}",
            payload["error"].as_str().unwrap_or("未具名错误")
        ));
    }
    Ok(payload)
}

fn authority_reply(
    p: &Profile,
    a: &Authority,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
    frame: &AuthorityFrame,
    reply: &Value,
) -> Result<AuthorityReply, String> {
    let r: AuthorityReply =
        serde_json::from_value(checked_payload(p, a, frame, reply)?.clone()).map_err(error)?;
    validate_authority_reply(p, a, op, command, release, &r)?;
    Ok(r)
}

fn verified_query_original<'a>(
    p: &Profile,
    frame: &AuthorityFrame,
    reply: &'a Value,
) -> Result<&'a Value, String> {
    let payload = checked_payload(p, &p.s, frame, reply)?;
    if payload["kind"] != "ExecuteCommittedOriginal"
        || !payload
            .as_object()
            .is_some_and(|o| o.len() == 2 && o.contains_key("original_reply"))
    {
        return Err("MissingDependency：S 查询缺可独立核证的原 ExecuteCommitted".into());
    }
    Ok(&payload["original_reply"])
}

#[cfg(test)]
fn authority(
    p: &Profile,
    a: &Authority,
    epoch: i64,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
) -> Result<AuthorityReply, String> {
    let frame = authority_frame(p, a, epoch, op, command, release)?;
    let reply = authority_exchange(p, authority_connect(a)?, &frame)?;
    authority_reply(p, a, op, command, release, &frame, &reply)
}

fn validate_authority_reply(
    p: &Profile,
    a: &Authority,
    op: &str,
    command: &ExactCommand,
    release: Option<&str>,
    r: &AuthorityReply,
) -> Result<(), String> {
    if r.protocol != AUTHORITY_WIRE
        || r.session_id != p.session_id
        || r.session_generation != p.session_generation
        || r.authority_id != a.authority_id
        || r.authority_epoch != a.authority_epoch
        || r.command_id != command.command_id
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
    if r.commit_ns < 0 {
        return Err("InvalidDomain：权威提交时刻不得为负".into());
    }
    if r.state != expected {
        return Err(format!(
            "MissingDependency：权威结果为{}，需要{expected}",
            r.state
        ));
    }
    if r.release_receipt_id.as_deref() != release {
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
fn query_command(
    c: &Connection,
    genesis: &Profile,
    history: Option<&History>,
    epoch: i64,
    id: &str,
) -> Result<Value, String> {
    if let Some(history) = history {
        return authority_history::query(c, genesis, history, epoch, id);
    }
    let p = genesis;
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
    genesis: &Profile,
    history: Option<&History>,
) -> Result<Value, String> {
    let pending = store::pending_batch(c)?.is_some();
    if pending && history.is_none() {
        return Err("PendingBatch：未完成批次只允许同内容恢复或只读".into());
    }
    let raw = encode(&command)?;
    if let Some((old, _, _, _)) = get(c, &command.command_id)? {
        if raw != old {
            return Err("IdentityConflict：同 command_id 改变内容/epoch".into());
        }
        return query_command(c, genesis, history, epoch, &command.command_id);
    }
    if pending {
        return Err("PendingBatch：未完成批次只允许同内容恢复或只读".into());
    }
    let received_ns = logical_now(c)?;
    command.validate(p, epoch)?;
    let frame = authority_frame(p, &p.e, epoch, "QueryReleasedExact", &command, None)?;
    let reply = authority_exchange(p, authority_connect(&p.e)?, &frame)?;
    let released = authority_reply(
        p,
        &p.e,
        "QueryReleasedExact",
        &command,
        None,
        &frame,
        &reply,
    )?;
    let clock = AcceptClock {
        received_ns,
        first_known_ns: received_ns,
        commit_ns: received_ns,
    };
    validate_accept_clock(&clock, released.commit_ns)?;
    let tx = c.transaction().map_err(error)?;
    tx.execute("INSERT INTO x_exact_commands(id,command,release_receipt,state,attempt_batch,accept_clock,release_evidence) VALUES(?1,?2,?3,'Accepted',NULL,?4,?5)",params![command.command_id,raw,released.receipt_id,encode(&clock)?,encode(&released)?]).map_err(error)?;
    authority_history::record(
        &tx,
        history,
        &command.command_id,
        "accept",
        json!({"request":frame.envelope,"reply":reply,"clock":clock}),
    )?;
    tx.commit().map_err(error)?;
    query_command(c, genesis, history, epoch, &command.command_id)
}
fn command_id(change: &Change) -> &str {
    match change {
        Change::Submit { order } | Change::Replace { order } => &order.command_id,
        Change::Cancel { command_id, .. } => command_id,
    }
}
fn execute(
    c: &mut Connection,
    p: &Profile,
    epoch: i64,
    mut batch: Batch,
    genesis: &Profile,
    history: Option<&History>,
) -> Result<Value, String> {
    batch.normalize();
    let encoded = encode(&batch)?;
    let pending = store::pending_batch(c)?;
    if pending.as_ref().is_some_and(|old| *old != encoded) {
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
            && !(matches!(
                state.as_str(),
                "MayHaveCalled" | "ExecutionReady" | "ExecutionRequested"
            ) && attempt.as_deref() == Some(encoded.as_str()))
        {
            return Err("IdentityConflict：该 command 已作用于另一批次".into());
        }
        let command: ExactCommand = serde_json::from_str(&raw).map_err(error)?;
        command.validate(p, epoch)?;
        if command.change != *change {
            return Err("IdentityConflict：批次改变精确命令".into());
        }
        let claimed_ns = batch.bar.index;
        let original = if let Some(h) = history {
            let accepted: String = c
                .query_row(
                    "SELECT accept_clock FROM x_exact_commands WHERE id=?1",
                    [id],
                    |r| r.get(0),
                )
                .map_err(error)?;
            let clock: AcceptClock = serde_json::from_str(&accepted).map_err(error)?;
            if claimed_ns < clock.commit_ns {
                return Err("InvalidDomain：原 S 尝试不得早于 X 接纳".into());
            }
            if state == "Accepted" {
                None
            } else {
                Some(authority_history::attempt(c, h, id)?)
            }
        } else {
            None
        };
        // 在 PendingBatch 持久化前检查所有出帧界。
        let call = match state.as_str() {
            "Accepted" => Some(authority_frame(
                p,
                &p.s,
                epoch,
                "RequestConditionalExecution",
                &command,
                Some(&release),
            )?),
            "ExecutionRequested" => Some(match &original {
                Some(attempt) => query_execution_frame(
                    p,
                    epoch,
                    &command,
                    &release,
                    &attempt.original["request"],
                )?,
                None => authority_frame(
                    p,
                    &p.s,
                    epoch,
                    "QueryExecuteCommitted",
                    &command,
                    Some(&release),
                )?,
            }),
            _ => None,
        };
        commands.push((command, release, state, call, original));
    }
    if pending.is_none() {
        let tx = c.transaction().map_err(error)?;
        tx.execute(
            "INSERT INTO x_sim_meta(k,v) VALUES('pending_batch',?1)",
            [&encoded],
        )
        .map_err(error)?;
        tx.execute(
            "INSERT INTO x_sim_meta(k,v) VALUES('pending_epoch',?1)",
            [epoch.to_string()],
        )
        .map_err(error)?;
        tx.commit().map_err(error)?;
    }
    let batch_doc = serde_json::to_value(&batch).map_err(error)?;
    for (command, release, state, call, original) in commands {
        let Some(frame) = call else {
            let evidence: String = c
                .query_row(
                    "SELECT execute_evidence FROM x_exact_commands WHERE id=?1",
                    [&command.command_id],
                    |r| r.get(0),
                )
                .map_err(error)?;
            let evidence = crate::session_protocol::strict_json(evidence.as_bytes())?;
            let old = match (history, original) {
                (Some(h), Some(attempt)) => h.profile_at(genesis, attempt.binding_seq)?,
                (None, _) => p.clone(),
                _ => return Err("IdentityConflict：已取得资格的命令缺原请求".into()),
            };
            validate_execution_record(&old, &command, &release, &evidence)?;
            continue;
        };
        let connection = authority_connect(&p.s)?;
        let first = state == "Accepted";
        if first {
            let tx = c.transaction().map_err(error)?;
            let changed = tx.execute("UPDATE x_exact_commands SET state='ExecutionRequested',attempt_batch=?2 WHERE id=?1 AND state='Accepted'",
                params![command.command_id,encoded]).map_err(error)?;
            if changed != 1 {
                return Err("IdentityConflict：原 S 请求只占一次".into());
            }
            authority_history::record(
                &tx,
                history,
                &command.command_id,
                "request",
                json!({"request":frame.envelope,"batch":batch_doc}),
            )?;
            tx.commit().map_err(error)?;
            #[cfg(test)]
            if std::env::var("ISSUE1381_TEST_SLOW_CLAIM").is_ok() {
                std::thread::sleep(Duration::from_millis(p.timeout_ms + 200));
            }
        }
        let wire = authority_exchange(p, connection, &frame)?;
        let claimed_ns = batch.bar.index;
        let (receipt, execution_profile, original_reply, observed) =
            if let (Some(h), Some(attempt)) = (history, original) {
                let raw = verified_query_original(p, &frame, &wire)?.clone();
                let old = h.profile_at(genesis, attempt.binding_seq)?;
                let request = authority_frame(
                    &old,
                    &old.s,
                    epoch,
                    "RequestConditionalExecution",
                    &command,
                    Some(&release),
                )?;
                if request.envelope != attempt.original["request"] {
                    return Err("IdentityConflict：S 查询并非针对已持久的原尝试".into());
                }
                let receipt = authority_reply(
                    &old,
                    &old.s,
                    "RequestConditionalExecution",
                    &command,
                    Some(&release),
                    &request,
                    &raw,
                )?;
                (
                    receipt,
                    old,
                    raw,
                    json!({"request":frame.envelope,"reply":wire,"read_ns":claimed_ns}),
                )
            } else {
                let op = if first {
                    "RequestConditionalExecution"
                } else {
                    "QueryExecuteCommitted"
                };
                let receipt =
                    authority_reply(p, &p.s, op, &command, Some(&release), &frame, &wire)?;
                (receipt, p.clone(), wire, Value::Null)
            };
        let evidence = json!({"reply":receipt,"claimed_ns":claimed_ns});
        validate_execution_record(&execution_profile, &command, &release, &evidence)?;
        let tx = c.transaction().map_err(error)?;
        let changed = tx.execute("UPDATE x_exact_commands SET state='ExecutionReady',execute_evidence=?3 WHERE id=?1 AND attempt_batch=?2 AND state='ExecutionRequested'",
            params![command.command_id,encoded,canonical_json(&evidence)]).map_err(error)?;
        if changed != 1 {
            return Err("IdentityConflict：S 原资格只落一次".into());
        }
        authority_history::record(
            &tx,
            history,
            &command.command_id,
            "evidence",
            json!({"original_reply":original_reply,"observed_query":observed,"claimed_ns":claimed_ns}),
        )?;
        tx.commit().map_err(error)?;
    }
    let tx = c.transaction().map_err(error)?;
    for id in &ids {
        let changed = tx.execute("UPDATE x_exact_commands SET state='MayHaveCalled' WHERE id=?1 AND attempt_batch=?2 AND state='ExecutionReady'",
            params![id,encoded]).map_err(error)?;
        if changed == 1 {
            if history.is_some() {
                let evidence = authority_history::link(&tx, id, "evidence")?;
                authority_history::record(&tx, history, id, "claim",
                    json!({"batch":batch_doc,"evidence_event_seq":evidence}))?;
            }
        } else if !tx.query_row("SELECT EXISTS(SELECT 1 FROM x_exact_commands WHERE id=?1 AND attempt_batch=?2 AND state='MayHaveCalled')",
            params![id,encoded], |r| r.get::<_, bool>(0)).map_err(error)? {
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
    // 仅本地模拟 adapter 有同批 SQLite 幂等合同；不适用于网络场所。
    let ids: Vec<_> = ids.into_iter().collect();
    store::commit_batch_with_commands(c, &batch, &ids, |tx| {
        if history.is_some() {
            authority_history::record(
                tx,
                history,
                &batch.request_id,
                "publish",
                json!({"batch":batch_doc}),
            )?;
            for id in &ids {
                let claim = authority_history::link(tx, id, "claim")?;
                authority_history::record(
                    tx,
                    history,
                    id,
                    "observe",
                    json!({"batch":batch_doc,"claim_event_seq":claim}),
                )?;
            }
        }
        Ok(())
    })
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
    validate_bound(c, p, None, None, epoch).map(|_| ())
}
fn validate_bound(
    c: &Connection,
    p: &Profile,
    binding: Option<&(Value, Value)>,
    identities: Option<&Identities>,
    epoch: i64,
) -> Result<Option<History>, String> {
    p.validate()?;
    let mut history = None;
    let exists: bool = c
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_sim_meta')",
            [],
            |r| r.get(0),
        )
        .map_err(error)?;
    let has_local = has_deployment(c)?;
    if (!exists && has_local) || (exists && has_local != binding.is_some()) {
        return Err("IdentityConflict：现有 X 原件禁止切换部署合同版本".into());
    }
    if exists {
        if let Some((_, mapping)) = binding {
            let (raw, fingerprint) = deployed(c)?;
            if raw != canonical_json(mapping) || fingerprint != hash(mapping) {
                return Err("IdentityConflict：X 部署位置已冻结".into());
            }
        }
        let frozen: Option<String> = c
            .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
                r.get(0)
            })
            .optional()
            .map_err(error)?;
        let expected = canonical_json(
            &json!({"model":p.model,"source_namespace":p.source_namespace,"source_epoch":p.source_epoch}),
        );
        if frozen.as_ref().is_some_and(|s| s != &expected)
            || (binding.is_some() && frozen.is_none())
        {
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
        if prior.as_ref() != Some(&business_binding(p, binding)?) {
            return Err("IdentityConflict：X 权威端点合同已冻结".into());
        }
        validate_pending_epoch(c, epoch)?;
        store::audit_history(c)?;
        if let Some(identities) = identities {
            history = Some(History::load(c, p, epoch, identities)?);
        }
    }
    let commands:bool=c.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_exact_commands')",[],|r|r.get(0)).map_err(error)?;
    if commands {
        if let Some(history) = &history {
            authority_history::audit(c, p, history, epoch)?;
        } else {
            audit_accepts(c, p)?;
        }
        audit_execution(c, p, history.as_ref())?;
    } else if exists {
        return Err("IdentityConflict：模拟历史缺命令权威表".into());
    }
    Ok(history)
}

/// 必须由调用方持有SQLite事务；X launcher把自身meta/epoch纳入同一次提交。
pub fn initialize_in_transaction(
    c: &rusqlite::Transaction<'_>,
    p: &Profile,
    epoch: i64,
) -> Result<(), String> {
    initialize_bound(c, p, None, None, epoch)
}
fn business_binding(p: &Profile, binding: Option<&(Value, Value)>) -> Result<String, String> {
    Ok(match binding {
        Some((business, _)) => canonical_json(business),
        None => canonical_json(&serde_json::to_value(p).map_err(error)?),
    })
}
fn initialize_bound(
    c: &rusqlite::Transaction<'_>,
    p: &Profile,
    binding: Option<&(Value, Value)>,
    identities: Option<&Identities>,
    epoch: i64,
) -> Result<(), String> {
    validate_bound(c, p, binding, identities, epoch)?;
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
        "INSERT INTO x_sim_meta VALUES('authority_profile',?1)",
        [business_binding(p, binding)?],
    )
    .map_err(error)?;
    if let Some((_, deployment)) = binding {
        c.execute_batch(DEPLOYMENT_SQL).map_err(error)?;
        c.execute(
            "INSERT INTO x_sim_deployment VALUES(1,?,?)",
            params![canonical_json(deployment), hash(deployment)],
        )
        .map_err(error)?;
    }
    if identities.is_some() {
        authority_binding::initialize(c, p, epoch)?;
    }
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
    serve_initialized(c, p, None, epoch)
}

fn serve_initialized(
    c: &mut Connection,
    genesis: &Profile,
    history: Option<&History>,
    epoch: i64,
) -> Result<(), String> {
    let active;
    let p = if let Some(h) = history {
        active = h.profile_at(genesis, h.current_seq())?;
        &active
    } else {
        genesis
    };
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
                        genesis,
                        history,
                    ),
                    "AdvanceBar" => execute(
                        c,
                        p,
                        epoch,
                        serde_json::from_value(r.payload).map_err(error)?,
                        genesis,
                        history,
                    ),
                    "QueryCommand" => {
                        let id = r
                            .payload
                            .as_str()
                            .ok_or("InvalidDomain：QueryCommand 身份须字符串")?;
                        query_command(c, genesis, history, epoch, id)
                    }
                    "QueryAuthorityOriginal" => authority_history::query_original(
                        c,
                        history.ok_or("UnsupportedCapability：本库没有权威履历")?,
                        serde_json::from_value(r.payload).map_err(error)?,
                    ),
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
            let response = match result {
                Ok(v) => v,
                Err(e) => json!({"kind":"Error","error":e}),
            };
            // 和传输层使用同一规范编码，加一字节行尾。旧 profile 保留原协议行为。
            if history.is_some() && canonical_json(&response).len() >= p.max_frame_bytes {
                return json!({"kind":"Error","error":"ResponseTooLarge"});
            }
            response
        },
    )
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
