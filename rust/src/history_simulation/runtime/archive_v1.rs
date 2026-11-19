//! #2078 封存的 /1 命令。摘要按当年的整数、字段及 Change 原样计算；不构造 /2 命令。
use super::{hash, Certificate, Change, CommandRecord, Profile};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub(super) struct ArchivedCommand {
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
impl CommandRecord for ArchivedCommand {
    type Tick = i64;
    const INNER_REVISION: Option<&'static str> = None;
    const CLAIMED_MATCHES_BATCH_BAR: bool = false;

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
