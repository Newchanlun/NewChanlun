//! ADR 0073：冻结创世身份，追加权威代向量；部署定位符不进入业务原件。
use super::{error, ids, Profile};
use crate::economic_session::validate_recovery_id;
use crate::session_protocol::{canonical_json, nonnegative, positive, strict_json};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;

const BINDING: &str = "x-authority-binding/1";
const HANDOFF: &str = "x-authority-rebind-input/1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Identities {
    e_manifest_hash: String,
    s_config: Value,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Domains {
    pub(super) e_db: PathBuf,
    pub(super) e_manifest: PathBuf,
    pub(super) s_db: PathBuf,
}

impl Domains {
    pub(super) fn validate(&self, x_db: &str) -> Result<(), String> {
        let paths = [&self.e_db, &self.e_manifest, &self.s_db];
        if paths
            .iter()
            .any(|p| !p.is_absolute() || p.to_str().is_none_or(|s| s.contains('\0') || s == x_db))
            || self.e_db == self.s_db
            || self.e_db == self.e_manifest
            || self.s_db == self.e_manifest
        {
            return Err(error("恢复域部署路径不独立或非法"));
        }
        Ok(())
    }
}

/// 只由受控启动方在显式 current-recovery 成功后组装。不是 socket 协议。
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RebindInput {
    schema_revision: String,
    domains: Vec<String>,
    e: Option<CurrentReceipt>,
    s: Option<CurrentReceipt>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CurrentReceipt {
    verification: String,
    db: PathBuf,
    receipt: Value,
}

impl RebindInput {
    pub fn parse(raw: &[u8]) -> Result<Self, String> {
        let v: Self = serde_json::from_value(strict_json(raw)?).map_err(error)?;
        let supplied: Vec<&str> = [("E", &v.e), ("S", &v.s)]
            .into_iter()
            .filter_map(|(id, record)| record.as_ref().map(|_| id))
            .collect();
        if v.schema_revision != HANDOFF || supplied.is_empty() || v.domains != supplied {
            return Err(error("恢复交接版本未知或指定域缺具名当前回执"));
        }
        Ok(v)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Original {
    kind: String,
    request: Value,
    writer_epoch: String,
    recover_ns: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EconomicRequest {
    schema_revision: String,
    domain_id: String,
    session_id: String,
    session_generation: String,
    recovery_id: String,
    from_epoch: String,
    manifest_hash: String,
    cut: EconomicCut,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EconomicCut {
    domain_id: String,
    commit_seq: String,
    root_hash: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StructureRequest {
    schema_revision: String,
    domain_id: String,
    session_id: String,
    session_generation: String,
    recovery_id: String,
    from_epoch: String,
    config: Value,
    cut: StructureCut,
    clock_event_id: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StructureCut {
    generation: String,
    structure_cut: String,
    index_frontier: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StructureConfig {
    rule_revision: String,
    profile_hash: String,
    catalog_hash: String,
    clock_plan_hash: String,
    structure_source: Value,
}
fn digest(s: &str) -> Result<(), String> {
    if s.len() == 64
        && s.bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        Ok(())
    } else {
        Err(error("恢复配置或切面摘要不是规范业务摘要"))
    }
}
impl Identities {
    pub(super) fn validate(&self, p: &Profile) -> Result<(), String> {
        digest(&self.e_manifest_hash)?;
        let s: StructureConfig = serde_json::from_value(self.s_config.clone()).map_err(error)?;
        ids::s_rule_revision(&s.rule_revision)?;
        for value in [&s.profile_hash, &s.catalog_hash, &s.clock_plan_hash] {
            digest(value)?;
        }
        let declaration = crate::structure_source::Declaration::parse(&s.structure_source)?;
        if canonical_json(&s.structure_source) != declaration.canonical() {
            return Err(error("S 结构源配置未规范化"));
        }
        for namespace in declaration.namespaces {
            ids::namespace(&namespace, "S structure_source namespace")?;
        }
        positive(&p.e.authority_epoch, "E authority_epoch")?;
        positive(&p.s.authority_epoch, "S authority_epoch")?;
        if p.e.authority_id != "E" || p.s.authority_id != "S" {
            return Err(error("恢复配置须绑定 E 与 S 域"));
        }
        Ok(())
    }

    fn transition(
        &self,
        p: &Profile,
        receipt: &Value,
        domain: Domain,
    ) -> Result<(i64, i64), String> {
        let r: Original = serde_json::from_value(receipt.clone()).map_err(error)?;
        if r.kind != "NamedRecoveryReceipt" {
            return Err(error("缺原域具名恢复回执"));
        }
        nonnegative(&r.recover_ns, "recover_ns")?;
        let (from, session, generation) = match domain {
            Domain::E => {
                let q: EconomicRequest = serde_json::from_value(r.request).map_err(error)?;
                if q.schema_revision != "economic-recovery/1"
                    || q.domain_id != "E"
                    || q.cut.domain_id != "E"
                    || q.manifest_hash != self.e_manifest_hash
                {
                    return Err(conflict("E 回执未绑定创世域/版本/业务配置"));
                }
                validate_recovery_id(&q.recovery_id)?;
                nonnegative(&q.cut.commit_seq, "commit_seq")?;
                digest(&q.cut.root_hash)?;
                (q.from_epoch, q.session_id, q.session_generation)
            }
            Domain::S => {
                let q: StructureRequest = serde_json::from_value(r.request).map_err(error)?;
                if q.schema_revision != "s-recovery/1"
                    || q.domain_id != "S"
                    || q.config != self.s_config
                {
                    return Err(conflict("S 回执未绑定创世域/版本/业务配置"));
                }
                validate_recovery_id(&q.recovery_id)?;
                ids::reference(&q.clock_event_id, "S clock_event_id")?;
                nonnegative(&q.cut.generation, "generation")?;
                ids::reference(&q.cut.structure_cut, "S structure_cut")?;
                if !q.cut.index_frontier.is_empty() {
                    ids::reference(&q.cut.index_frontier, "S index_frontier")?;
                }
                (q.from_epoch, q.session_id, q.session_generation)
            }
        };
        if session != p.session_id || generation != p.session_generation {
            return Err(conflict("域回执未绑定创世会话"));
        }
        let from = positive(&from, "from_epoch")?;
        let to = positive(&r.writer_epoch, "writer_epoch")?;
        if from.checked_add(1) != Some(to) {
            return Err(conflict("权威恢复必须单步升代"));
        }
        Ok((from, to))
    }
}

#[derive(Clone, Copy)]
enum Domain {
    E,
    S,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Vector {
    e_authority_epoch: i64,
    s_authority_epoch: i64,
}
impl Vector {
    fn initial(p: &Profile) -> Result<Self, String> {
        Ok(Self {
            e_authority_epoch: positive(&p.e.authority_epoch, "E authority_epoch")?,
            s_authority_epoch: positive(&p.s.authority_epoch, "S authority_epoch")?,
        })
    }
    fn changed(&mut self, domain: Domain) -> &mut i64 {
        match domain {
            Domain::E => &mut self.e_authority_epoch,
            Domain::S => &mut self.s_authority_epoch,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Receipt {
    domain_id: String,
    original: Value,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct Binding {
    binding_schema_revision: String,
    binding_seq: i64,
    parent_binding_seq: Option<i64>,
    session_id: String,
    session_generation: String,
    x_id: String,
    x_writer_epoch: i64,
    old_vector: Vector,
    new_vector: Vector,
    receipts: Vec<Receipt>,
    event_frontier: i64,
}

fn conflict(message: &str) -> String {
    format!("IdentityConflict：{message}")
}

fn document<T: Serialize>(record: &T) -> String {
    canonical_json(&serde_json::to_value(record).expect("typed binding"))
}

impl Binding {
    fn genesis(p: &Profile, epoch: i64) -> Result<Self, String> {
        let vector = Vector::initial(p)?;
        Ok(Self {
            binding_schema_revision: BINDING.into(),
            binding_seq: 0,
            parent_binding_seq: None,
            session_id: p.session_id.clone(),
            session_generation: p.session_generation.clone(),
            x_id: p.x_id.clone(),
            x_writer_epoch: epoch,
            old_vector: vector,
            new_vector: vector,
            receipts: vec![],
            event_frontier: 0,
        })
    }

    fn successor(
        &self,
        p: &Profile,
        identities: &Identities,
        receipts: Vec<Receipt>,
        frontier: i64,
    ) -> Result<Self, String> {
        let mut new = self.clone();
        new.binding_seq = self
            .binding_seq
            .checked_add(1)
            .ok_or_else(|| error("绑定序号溢出"))?;
        new.parent_binding_seq = Some(self.binding_seq);
        new.old_vector = self.new_vector;
        new.receipts = receipts;
        new.event_frontier = frontier;
        if frontier < self.event_frontier || new.receipts.is_empty() {
            return Err(conflict("恢复向量缺回执或事件前沿倒退"));
        }
        let mut prior = "";
        for receipt in &new.receipts {
            let domain = match (prior, receipt.domain_id.as_str()) {
                ("", "E") => Domain::E,
                ("" | "E", "S") => Domain::S,
                _ => return Err(conflict("回执须按 E、S 唯一顺序")),
            };
            prior = &receipt.domain_id;
            let (from, to) = identities.transition(p, &receipt.original, domain)?;
            let slot = new.new_vector.changed(domain);
            if *slot != from {
                return Err(conflict("恢复回执缺当前绑定的单步前驱"));
            }
            *slot = to;
        }
        Ok(new)
    }
}

pub(super) struct History {
    chain: Vec<Binding>,
}

fn insert(c: &Connection, binding: &Binding) -> Result<(), String> {
    c.execute(
        "INSERT INTO x_authority_bindings VALUES(?1,?2)",
        params![binding.binding_seq, document(binding)],
    )
    .map_err(error)?;
    Ok(())
}

pub(super) fn initialize(c: &Connection, p: &Profile, epoch: i64) -> Result<(), String> {
    c.execute_batch(
        "CREATE TABLE x_authority_bindings(
        binding_seq INTEGER PRIMARY KEY, record TEXT NOT NULL
    ) STRICT;
    CREATE TABLE x_authority_events(
        event_seq INTEGER PRIMARY KEY, command_id TEXT NOT NULL, phase TEXT NOT NULL,
        binding_seq INTEGER NOT NULL REFERENCES x_authority_bindings(binding_seq),
        original TEXT NOT NULL, UNIQUE(command_id,phase)
    ) STRICT;",
    )
    .map_err(error)?;
    insert(c, &Binding::genesis(p, epoch)?)
}

pub(super) fn frontier(c: &Connection) -> Result<i64, String> {
    c.query_row(
        "SELECT COALESCE(MAX(event_seq),0) FROM x_authority_events",
        [],
        |r| r.get(0),
    )
    .map_err(error)
}

impl History {
    pub(super) fn load(
        c: &Connection,
        p: &Profile,
        epoch: i64,
        identities: &Identities,
    ) -> Result<Self, String> {
        let mut q = c
            .prepare("SELECT binding_seq,record FROM x_authority_bindings ORDER BY binding_seq")
            .map_err(error)?;
        let rows = q
            .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
            .map_err(error)?;
        let frontier = frontier(c)?;
        let mut chain: Vec<Binding> = Vec::new();
        for row in rows {
            let (seq, raw) = row.map_err(error)?;
            let b: Binding = serde_json::from_str(&raw).map_err(error)?;
            if raw != document(&b) || b.binding_seq != seq || b.event_frontier > frontier {
                return Err(conflict("持久绑定序号/事件前沿/规范原件不符"));
            }
            let expected = match chain.last() {
                Some(parent) => {
                    parent.successor(p, identities, b.receipts.clone(), b.event_frontier)?
                }
                None => Binding::genesis(p, epoch)?,
            };
            if b != expected {
                return Err(conflict("持久绑定不存在唯一连续前驱"));
            }
            chain.push(b);
        }
        if chain.is_empty() {
            return Err(conflict("缺创世权威绑定"));
        }
        Ok(Self { chain })
    }

    pub(super) fn current_seq(&self) -> i64 {
        self.chain.last().expect("validated genesis").binding_seq
    }

    pub(super) fn profile_at(&self, genesis: &Profile, seq: i64) -> Result<Profile, String> {
        let b = usize::try_from(seq)
            .ok()
            .and_then(|i| self.chain.get(i))
            .ok_or_else(|| conflict("历史事件引用不存在的权威绑定"))?;
        let mut p = genesis.clone();
        p.e.authority_epoch = b.new_vector.e_authority_epoch.to_string();
        p.s.authority_epoch = b.new_vector.s_authority_epoch.to_string();
        Ok(p)
    }

    pub(super) fn seq_at_event(&self, event: i64) -> i64 {
        self.chain
            .iter()
            .rev()
            .find(|b| b.event_frontier < event)
            .map_or(-1, |b| b.binding_seq)
    }

    pub(super) fn append(
        &self,
        c: &Connection,
        p: &Profile,
        identities: &Identities,
        domains: &Domains,
        input: &RebindInput,
    ) -> Result<(), String> {
        let mut originals = Vec::new();
        for (id, provided, db) in [
            ("E", &input.e, &domains.e_db),
            ("S", &input.s, &domains.s_db),
        ] {
            let Some(provided) = provided else { continue };
            if provided.verification != "current-recovery" || provided.db != *db {
                return Err(conflict("恢复回执缺当前核验来源或来自另一部署"));
            }
            originals.push(Receipt {
                domain_id: id.into(),
                original: provided.receipt.clone(),
            });
        }
        let last = self.chain.last().expect("validated genesis");
        let next = if let Some(previous) = self.chain.iter().rev().nth(1) {
            // 仅允许重开当前尾，不能拿更久的历史回执回退。
            match previous.successor(p, identities, originals.clone(), last.event_frontier) {
                Ok(retry) if retry.new_vector == last.new_vector => {
                    if retry != *last {
                        return Err(conflict("同权威转换的原回执内容不同"));
                    }
                    None
                }
                _ => Some(last.successor(p, identities, originals, frontier(c)?)?),
            }
        } else {
            Some(last.successor(p, identities, originals, frontier(c)?)?)
        };
        if let Some(provided) = &input.e {
            crate::economic_session::verify_x_current_recovery(
                &domains.e_manifest,
                &domains.e_db,
                &p.e.socket,
                &provided.receipt,
            )?;
        }
        // S 的介质准入/锁/cut 由 #2128 current-recovery 及启动验证拥有。
        // 此处仅消费可信启动方转交的原件，不绕过 S 准入另开其库。
        if let Some(next) = next {
            insert(c, &next)?;
        }
        Ok(())
    }
}
