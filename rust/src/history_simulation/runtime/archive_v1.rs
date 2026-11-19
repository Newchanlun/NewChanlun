//! 封存的 `/1` 命令与档案布局（覆盖早期 `18446a3d35`–`d1c46577b1` 与后期 `1f0a42bc20`–`734847be00` 两种冻结存储布局）。
//! 摘要按当年的整数、字段及 `Change` 原样计算；按冻结键集严格判别，不回退降格，不伪造共同信封或新授权；
//! 后期 `/1` 三个条件准入世代（`1f0a42bc20` / `2ed00abd6c` / `b66b61a0b0+`）共享同一 12+6+6 存储布局且无写者修订落盘，
//! 因此按该布局共同可证语义核验并在读出元数据中显式标明未证项，不溯及重放后加准入闸。
use super::{
    hash, validate_conditions_common_12_6, AuditProfile, Certificate, Change, CommandRecord, Model,
    Profile,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;

const EARLY_PROFILE_KEYS: &[&str] = &[
    "e",
    "max_frame_bytes",
    "model",
    "s",
    "session_generation",
    "session_id",
    "socket",
    "source_epoch",
    "source_namespace",
    "timeout_ms",
    "x_id",
];
const LATE_PROFILE_KEYS: &[&str] = &[
    "conditions",
    "e",
    "max_frame_bytes",
    "model",
    "s",
    "session_generation",
    "session_id",
    "socket",
    "source_epoch",
    "source_namespace",
    "timeout_ms",
    "x_id",
];
const EARLY_AUTH_KEYS: &[&str] = &["authority_epoch", "authority_id", "socket"];
const LATE_AUTH_KEYS: &[&str] = &[
    "authority_epoch",
    "authority_id",
    "producer_id",
    "reply_namespace",
    "schema_revision",
    "socket",
];

fn exact_object_keys(v: &Value, expected: &[&str]) -> bool {
    let Some(map) = v.as_object() else {
        return false;
    };
    map.len() == expected.len() && expected.iter().all(|k| map.contains_key(*k))
}

pub(super) enum V1ProfileLayout {
    Early,
    Late,
}

/// 在任何结构体反序列化之前，按冻结键集严格区分早期 `/1`（11 键 profile + 3 键 E/S）
/// 与后期 `/1`（12 键含 `conditions` + 6 键含共同信封字段）。
/// 任何混合、缺键、多键或非对称布局直接拒绝，绝不做“失败后降格为早期”的宽松兜底。
pub(super) fn classify_v1_profile(v: &Value) -> Result<V1ProfileLayout, String> {
    let e = v.get("e").unwrap_or(&Value::Null);
    let s = v.get("s").unwrap_or(&Value::Null);
    if exact_object_keys(v, EARLY_PROFILE_KEYS)
        && exact_object_keys(e, EARLY_AUTH_KEYS)
        && exact_object_keys(s, EARLY_AUTH_KEYS)
    {
        Ok(V1ProfileLayout::Early)
    } else if exact_object_keys(v, LATE_PROFILE_KEYS)
        && exact_object_keys(e, LATE_AUTH_KEYS)
        && exact_object_keys(s, LATE_AUTH_KEYS)
    {
        Ok(V1ProfileLayout::Late)
    } else {
        Err(
            "InvalidDomain：/1 归档 authority_profile 布局既不符合早期冻结格式也不符合后期冻结格式"
                .into(),
        )
    }
}

/// 早期 `/1`（`18446a3d35`–`d1c46577b1`）冻结的权威端点结构：无共同信封字段。
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EarlyAuthority {
    pub(super) socket: String,
    pub(super) authority_id: String,
    pub(super) authority_epoch: String,
}

/// 早期 `/1`（`18446a3d35`–`d1c46577b1`）冻结的 `authority_profile` 结构：无 `conditions` 清单。
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct EarlyProfile {
    pub(super) model: Model,
    pub(super) session_id: String,
    pub(super) session_generation: String,
    pub(super) x_id: String,
    pub(super) source_namespace: String,
    pub(super) source_epoch: String,
    pub(super) socket: String,
    pub(super) e: EarlyAuthority,
    pub(super) s: EarlyAuthority,
    pub(super) timeout_ms: u64,
    pub(super) max_frame_bytes: usize,
}

impl AuditProfile for EarlyProfile {
    fn validate_profile(&self) -> Result<(), String> {
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

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct ArchivedCommandFields {
    command_id: String,
    logical_order_family: String,
    session_id: String,
    session_generation: String,
    x_id: String,
    x_epoch: i64,
    symbol: String,
    projection_kind: String,
    change: Change,
    plan_hash: String,
    certificate_hash: String,
    certificate: Certificate,
}

impl ArchivedCommandFields {
    fn validate_common<P: AuditProfile>(&self, p: &P) -> Result<(), String> {
        if self.session_id != p.session_id()
            || self.session_generation != p.session_generation()
            || self.x_id != p.x_id()
            || self.symbol != p.model().symbol
            || self.projection_kind != p.model().projection_kind
            || self.certificate.rd11_policy != p.model().rd11_policy
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
        if matches!(&self.change, Change::Submit { order } | Change::Replace { order } if order.projection_manifest.is_empty())
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
        Ok(())
    }
}

/// 早期 `/1`（`18446a3d35`、`5f3361ca8b`、`d1c46577b1`）归档命令：
/// 按当年冻结的 3 项条件清单不变量核证；因前两版写墙钟 `now_ns()`、后一版写 `bar.index`
/// 且共享完全相同的 11 键/3 键布局，不能溯及强制 `claimed_ns == attempt_batch.bar.index`。
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(transparent)]
pub(super) struct EarlyArchivedCommand(ArchivedCommandFields);

impl CommandRecord for EarlyArchivedCommand {
    type Profile = EarlyProfile;
    type Tick = i64;
    const INNER_REVISION: Option<&'static str> = None;
    const CLAIMED_MATCHES_BATCH_BAR: bool = false;
    const CLAIMED_NS_AUDIT_POLICY: &'static str = "raw_claim_only_non_retroactive_v1";
    const ARCHIVE_LAYOUT: &'static str = "v1_early";
    const CONDITION_AUDIT_POLICY: &'static str = "v1_early_frozen_three_conditions";
    const CONDITION_AUDIT_UNPROVEN: &'static [&'static str] = &[
        "model_coverage_condition_1f0a42bc20",
        "condition_semantics_pairing_table_2ed00abd6c",
        "required_four_capabilities_completeness_b66b61a0b0",
    ];

    fn id(&self) -> &str {
        &self.0.command_id
    }
    fn change(&self) -> &Change {
        &self.0.change
    }
    fn validate_record(&self, p: &EarlyProfile) -> Result<(), String> {
        self.0.validate_common(p)?;
        let expected = [
            ("released-exact/1", "E.ReleaseExact"),
            ("execute-committed/1", "S.RequestConditionalExecution"),
            ("simulation-local-transaction/1", "X.OwnAttemptAndCall"),
        ];
        let c = &self.0.certificate;
        if c.conditions.len() != expected.len() {
            return Err("Unsupported：不完整或未知条件清单".into());
        }
        let mut ids = std::collections::BTreeSet::new();
        for (capability, stage) in expected {
            let matching: Vec<_> = c
                .conditions
                .iter()
                .filter(|x| x.validator_capability == capability)
                .collect();
            if matching.len() != 1 {
                return Err("Unsupported：未知或重复 ConditionEvidence 核验能力".into());
            }
            let x = matching[0];
            if x.condition_id.is_empty()
                || !ids.insert(&x.condition_id)
                || x.authority_revision != capability
                || x.required_check_stages != [stage]
                || x.dependency_set.is_empty()
                || x.dependency_set.iter().any(String::is_empty)
                || x.evidence_refs.is_empty()
                || x.evidence_refs.iter().any(String::is_empty)
                || x.invalidation_sources.is_empty()
                || x.invalidation_sources.iter().any(String::is_empty)
                || x.coverage_proof.is_empty()
                || x.failure_result != "Denied"
            {
                return Err("Unsupported：ConditionEvidence 阶段/覆盖/失败语义未支持".into());
            }
        }
        Ok(())
    }
}

/// 后期 `/1`（`1f0a42bc20`–`734847be00`，含 `#2078` 封存布局）的只读档案 profile 包装：
/// 保留严格 12 键/6 键形态、端点与模型基础不变量，并按 12+6+6 布局共同可证条件语义
/// （`validate_conditions_common_12_6`）核验；因 `1f0a42bc20`、`2ed00abd6c`、`b66b61a0b0+`
/// 共享完全相同的落盘键集且无写者修订记录，不溯及重放 `2ed00abd6c` 配对表与 `b66b61a0b0` 四项完备闸，
/// 而是由 `LateArchivedCommand::CONDITION_AUDIT_UNPROVEN` 显式标明未证项。
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(transparent)]
pub(super) struct LateV1Profile(pub(super) Profile);

impl AuditProfile for LateV1Profile {
    fn validate_profile(&self) -> Result<(), String> {
        self.0.validate_base()?;
        validate_conditions_common_12_6(&self.0.conditions)
    }
    fn model(&self) -> &Model {
        &self.0.model
    }
    fn session_id(&self) -> &str {
        &self.0.session_id
    }
    fn session_generation(&self) -> &str {
        &self.0.session_generation
    }
    fn x_id(&self) -> &str {
        &self.0.x_id
    }
    fn source_namespace(&self) -> &str {
        &self.0.source_namespace
    }
    fn source_epoch(&self) -> &str {
        &self.0.source_epoch
    }
    fn e_identity(&self) -> (&str, &str) {
        (&self.0.e.authority_id, &self.0.e.authority_epoch)
    }
    fn s_identity(&self) -> (&str, &str) {
        (&self.0.s.authority_id, &self.0.s.authority_epoch)
    }
}

/// 后期 `/1`（`1f0a42bc20`–`734847be00`，含 `#2078` 封存布局）归档命令：
/// 按严格 12 键/6 键 `LateV1Profile` 校验 `c.conditions == p.0.conditions` 与 12+6+6 共同可证条件语义；
/// 该代全部写者均在 `d1c46577b1` 移除 `now_ns()` 之后恒写 `claimed_ns = batch.bar.index`，
/// 因此仍按占有批 `bar.index` 强制核证，不削弱逻辑 bar、版号、布局与回执原件闭包。
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(transparent)]
pub(super) struct LateArchivedCommand(ArchivedCommandFields);

impl CommandRecord for LateArchivedCommand {
    type Profile = LateV1Profile;
    type Tick = i64;
    const INNER_REVISION: Option<&'static str> = None;
    const CLAIMED_MATCHES_BATCH_BAR: bool = true;
    const CLAIMED_NS_AUDIT_POLICY: &'static str = "verified_equal_to_attempt_bar";
    const ARCHIVE_LAYOUT: &'static str = "v1_late";
    const CONDITION_AUDIT_POLICY: &'static str = "v1_late_common_12_6_invariants_only";
    const CONDITION_AUDIT_UNPROVEN: &'static [&'static str] = &[
        "condition_semantics_pairing_table_2ed00abd6c",
        "required_four_capabilities_completeness_b66b61a0b0",
    ];

    fn id(&self) -> &str {
        &self.0.command_id
    }
    fn change(&self) -> &Change {
        &self.0.change
    }
    fn validate_record(&self, p: &LateV1Profile) -> Result<(), String> {
        self.0.validate_common(p)?;
        if self.0.certificate.conditions != p.0.conditions {
            return Err("Unsupported：条件清单与获准 manifest 清单不逐项相等".into());
        }
        Ok(())
    }
}
