//! #1407 C2 封存的 /2 命令。摘要按当年无 `model_ref` 的十四字段十进制文本原样计算；不构造 /3 命令。
use super::{
    decimal, hash, Certificate, Change, CommandRecord, DecimalTick, Plan, Profile, SignedChange,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(super) struct ArchivedCommand {
    command_id: String,
    logical_order_family: String,
    #[serde(with = "decimal")]
    first_quantity: i64,
    allocation_id: String,
    session_id: String,
    session_generation: String,
    x_id: String,
    #[serde(with = "decimal")]
    x_epoch: i64,
    symbol: String,
    projection_kind: String,
    #[serde(with = "SignedChange")]
    change: Change,
    plan_hash: String,
    certificate_hash: String,
    certificate: Certificate,
}

impl CommandRecord for ArchivedCommand {
    type Profile = Profile;
    type Tick = DecimalTick;
    const INNER_REVISION: Option<&'static str> = Some("x-execution-profile/2");
    const CLAIMED_MATCHES_BATCH_BAR: bool = true;
    const CLAIMED_NS_AUDIT_POLICY: &'static str = "verified_equal_to_attempt_bar";
    const ARCHIVE_LAYOUT: &'static str = "v2";

    fn id(&self) -> &str {
        &self.command_id
    }
    fn change(&self) -> &Change {
        &self.change
    }
    fn validate_record(&self, p: &Profile) -> Result<(), String> {
        if self.session_id != p.session_id
            || self.session_generation != p.session_generation
            || self.x_id != p.x_id
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
            || self.plan_hash != hash(&Plan(&self.change))
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
        if self.first_quantity <= 0 || self.allocation_id.is_empty() {
            return Err("MissingDependency：精确命令缺首次量 L 或分配身份".into());
        }
        if matches!(&self.change, Change::Submit { order } if order.quantity != self.first_quantity)
        {
            return Err("IdentityConflict：首次提交量与 L 不同".into());
        }
        if c.conditions != p.conditions {
            return Err("Unsupported：条件清单与获准 manifest 清单不逐项相等".into());
        }
        Ok(())
    }
}
