//! ADR 0050：S 域具名恢复请求、只读切面与回执验真，不授予开库写权。
use super::{
    admission::{emit_accounted_payload, DomainLocks, Lock},
    admission_anchor::{AdmissionAccounting, NamedContract, PreparedAdmission, Stage},
    admission_provider::RecoveryObservation,
};
use crate::{meta_get_opt, v2::ClockPlan};
use newchan_rust::{
    session_protocol::{canonical_json, nonnegative, positive, required, strict_json},
    structure_source::Declaration,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::{fs::File, os::unix::fs::FileExt, path::Path};

pub(super) const REQUEST_LIMIT: usize = 4_096;
const SCHEMA: &str = "s-recovery/1";
const UNPROVEN: &str = "SRecoveryMediumUnproven";
const CONFLICT: &str = "IdentityConflict";
const INVALID: &str = "StorageUnavailable：S恢复原件与历史不一致";

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Action {
    Inspect,
    Recover,
    Query,
    Current,
}
impl Action {
    pub(super) fn from_command(command: &str) -> Option<Self> {
        match command {
            "inspect-recovery" => Some(Self::Inspect),
            "recover-named" => Some(Self::Recover),
            "query-recovery" => Some(Self::Query),
            "current-recovery" => Some(Self::Current),
            _ => None,
        }
    }
}

pub(super) struct FrozenConfig {
    pub(super) profile_hash: String,
    pub(super) catalog_hash: String,
    pub(super) source: Declaration,
    pub(super) clock: ClockPlan,
}

pub(super) struct Request {
    document: Value,
    key: String,
    from: i64,
}
impl Request {
    pub(super) fn parse(raw: &[u8]) -> Result<Self, String> {
        if raw.len() > REQUEST_LIMIT {
            return Err("InvalidDomain：S恢复请求超过4096字节".into());
        }
        let document = strict_json(raw)?;
        if raw != canonical_json(&document).as_bytes()
            || !exact(
                &document,
                &[
                    "schema_revision",
                    "recovery_id",
                    "domain_id",
                    "session_id",
                    "session_generation",
                    "from_epoch",
                    "cut",
                    "config",
                    "clock_event_id",
                ],
            )
            || document["schema_revision"] != SCHEMA
            || document["domain_id"] != "S"
        {
            return Err("InvalidDomain：S恢复请求必须为规范s-recovery/1对象".into());
        }
        let id = required(&document, "recovery_id")?;
        if id.len() > 96
            || !id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
        {
            return Err("InvalidDomain：恢复身份必须为1..96字节ASCII标识".into());
        }
        let key = format!("{SCHEMA}:{id}");
        required(&document, "session_id")?;
        positive(
            required(&document, "session_generation")?,
            "session_generation",
        )?;
        let from = positive(required(&document, "from_epoch")?, "from_epoch")?;
        required(&document, "clock_event_id")?;
        validate_cut(&document["cut"])?;
        validate_config(&document["config"])?;
        Ok(Self {
            document,
            key,
            from,
        })
    }

    fn check_identity(&self, snapshot: &Snapshot) -> Result<(), String> {
        if self.document["session_id"] != snapshot.session
            || self.document["session_generation"] != snapshot.incarnation
            || self.document["config"] != snapshot.config
        {
            return Err(format!("{CONFLICT}：恢复请求未绑定当前S域和冻结配置"));
        }
        Ok(())
    }

    fn epoch_binding(&self) -> String {
        canonical_json(&json!({
            "request_key": self.key,
            "clock_event_id": self.document["clock_event_id"],
        }))
    }

    fn original(
        &self,
        conn: &Connection,
        clock: &ClockPlan,
    ) -> Result<Option<(i64, Value)>, String> {
        let original: Option<Option<String>> = conn.query_row(
            "SELECT CASE WHEN length(CAST(value AS BLOB))<=?2 THEN value END FROM meta WHERE key=?1",
            params![self.key, (REQUEST_LIMIT + 256) as i64], |r| r.get(0),
        ).optional().map_err(sql)?;
        let Some(raw) = original else { return Ok(None) };
        let raw = raw.ok_or(INVALID)?;
        let receipt = strict_json(raw.as_bytes()).map_err(|_| INVALID)?;
        if receipt["request"] != self.document {
            return Err(format!("{CONFLICT}：恢复ID已绑定不同请求"));
        }
        let epoch = self.from.checked_add(1).ok_or(INVALID)?;
        let cut = &self.document["cut"];
        if meta_get_opt(conn, &epoch_key(epoch))?.as_deref() != Some(self.epoch_binding().as_str())
        {
            return Err(INVALID.into());
        }
        // 历史回执不使用当前 root 重新拼装；唯一跃迁、事件和历史 cut 都必须在原库。
        let at: String = conn
            .query_row(
                "SELECT transitioned_at FROM writer_epoch_history
             WHERE from_epoch=?1 AND to_epoch=?2 AND generation_at_transition=?3
             AND advance_state_at_transition='idle'",
                params![
                    self.from.to_string(),
                    epoch.to_string(),
                    cut["generation"].as_str()
                ],
                |r| r.get(0),
            )
            .optional()
            .map_err(sql)?
            .ok_or(INVALID)?;
        let event = required(&self.document, "clock_event_id")?;
        let at_event: String = conn
            .query_row(
                "SELECT semantic_ns FROM s_clock_events
             WHERE clock_event_id=?1 AND phase='recover' AND attempt_index=-1
             AND generation=?2 AND message_key='' AND attempt_ordinal IS NULL",
                params![event, required(cut, "generation")?],
                |r| r.get(0),
            )
            .optional()
            .map_err(sql)?
            .ok_or(INVALID)?;
        let generation = nonnegative(required(cut, "generation")?, "generation")?;
        if historical_cut(conn, generation)? != *cut
            || at_event != at
            || planned(clock, event)? != at
            || raw
                != canonical_json(
                    &json!({"kind":"NamedRecoveryReceipt","request":self.document,
                                              "writer_epoch":epoch.to_string(),"recover_ns":at}),
                )
        {
            return Err(INVALID.into());
        }
        Ok(Some((epoch, receipt)))
    }
}
// `/` 不属于 recovery_id 字母表。按代绑定唯一请求，防止同 cut、同 ns 的另一个
// 恢复时钟可被当成历史跃迁的事件；请求及完整原回执仍保存在 ADR 登记的 ID 键。
fn epoch_key(epoch: i64) -> String {
    format!("{SCHEMA}:epoch/{epoch}")
}

fn sql(e: impl std::fmt::Display) -> String {
    format!("StorageUnavailable：S恢复读取失败：{e}")
}
fn exact(value: &Value, keys: &[&str]) -> bool {
    value
        .as_object()
        .is_some_and(|o| o.len() == keys.len() && keys.iter().all(|k| o.contains_key(*k)))
}
fn validate_cut(cut: &Value) -> Result<(), String> {
    if !exact(cut, &["generation", "structure_cut", "index_frontier"])
        || !cut["index_frontier"].is_string()
    {
        return Err("InvalidDomain：S恢复cut不是闭合对象".into());
    }
    nonnegative(required(cut, "generation")?, "generation")?;
    required(cut, "structure_cut")?;
    Ok(())
}
fn validate_config(config: &Value) -> Result<(), String> {
    if !exact(
        config,
        &[
            "rule_revision",
            "profile_hash",
            "catalog_hash",
            "clock_plan_hash",
            "structure_source",
        ],
    ) {
        return Err("InvalidDomain：S恢复config不是闭合对象".into());
    }
    required(config, "rule_revision")?;
    for field in ["profile_hash", "catalog_hash", "clock_plan_hash"] {
        let hash = required(config, field)?;
        if hash.len() != 64
            || !hash
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(format!("InvalidDomain：{field}不是规范摘要"));
        }
    }
    let parsed = Declaration::parse(&config["structure_source"])?;
    if parsed.canonical() != canonical_json(&config["structure_source"]) {
        return Err("InvalidDomain：S恢复structure_source未规范化".into());
    }
    Ok(())
}

fn meta(conn: &Connection, key: &str) -> Result<String, String> {
    meta_get_opt(conn, key)?.ok_or_else(|| format!("StorageUnavailable：S缺持久{key}"))
}

fn historical_cut(conn: &Connection, generation: i64) -> Result<Value, String> {
    let (cut, frontier): (String, String) = if generation == 0 {
        ("cut-0".into(), String::new())
    } else {
        conn.query_row(
            "SELECT next_cut,index_frontier FROM structure_deltas WHERE generation=?1",
            [generation],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(sql)?
        .ok_or(INVALID)?
    };
    Ok(json!({"generation":generation.to_string(),"structure_cut":cut,"index_frontier":frontier}))
}

struct Snapshot {
    epoch: i64,
    session: String,
    incarnation: String,
    cut: Value,
    config: Value,
    idle: bool,
    phase_frontier: String,
}
impl Snapshot {
    fn read(conn: &Connection, config: &FrozenConfig) -> Result<Self, String> {
        let rule = meta(conn, "rule_revision")?;
        super::require_current_writer_rule(&rule)?;
        let source = meta(conn, newchan_rust::structure_source::META_KEY)?;
        let profile = meta(conn, "profile_hash")?;
        let catalog_hash = meta(conn, "catalog_hash")?;
        if catalog_hash != config.catalog_hash {
            return Err("IdentityConflict：S恢复冻结 catalog_hash 与库不一致".into());
        }
        let (incarnation, clock_hash, clock_json, phase_frontier): (String, String, String, String) =
            conn.query_row(
                "SELECT session_generation,clock_plan_hash,clock_plan_json,logical_phase_frontier FROM s_protocol_meta WHERE singleton=1",
                [], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?)),
            ).map_err(sql)?;
        if source != config.source.canonical()
            || profile != config.profile_hash
            || clock_hash != config.clock.hash
            || clock_json != canonical_json(&config.clock.value)
        {
            return Err(format!("{CONFLICT}：S恢复冻结配置与库不一致"));
        }
        let generation = meta(conn, "generation")?;
        let cut = json!({"generation":generation, "structure_cut":meta(conn, "structure_cut")?,
                            "index_frontier":meta(conn, "index_frontier")?});
        if historical_cut(conn, nonnegative(&generation, "generation")?)? != cut {
            return Err(INVALID.into());
        }
        Ok(Self {
            session: meta(conn, "session_id")?,
            incarnation,
            epoch: positive(&meta(conn, "writer_epoch")?, "writer_epoch")?,
            cut,
            config: json!({"rule_revision":rule, "profile_hash":profile, "catalog_hash":catalog_hash,
                           "clock_plan_hash":clock_hash, "structure_source":strict_json(source.as_bytes())?}),
            idle: meta(conn, "advance_state")? == "idle",
            phase_frontier,
        })
    }

    fn inspect(&self, has_shm: bool) -> Value {
        json!({"kind":"SRecoveryInspection","schema_revision":SCHEMA,"domain_id":"S",
            "session_id":self.session,"session_generation":self.incarnation,
            "from_epoch":self.epoch.to_string(),"cut":self.cut,"config":self.config,
            "has_shm":has_shm,"unresolved_begin":!self.idle,"logical_phase_frontier":self.phase_frontier})
    }
}

fn planned(clock: &ClockPlan, event: &str) -> Result<String, String> {
    if clock.is_system() {
        return Err("InvalidDomain：具名恢复事件必须有冻结语义时刻".into());
    }
    clock.phase(event, "recover", -1)
}

pub(super) fn run(
    db: &Path,
    admission: PreparedAdmission,
    action: Action,
    config: FrozenConfig,
    request: Option<&Request>,
    contract: Option<NamedContract<'_>>,
    output: impl FnOnce(&Value, &mut super::admission_anchor::FinishedAdmission) -> Result<(), String>,
) -> Result<(), String> {
    let admission = admission.consume().map_err(|e| e.to_string())?;
    let original = admission.lease().db_path();
    if db != original {
        return Err(UNPROVEN.into());
    }
    // 沿原 R4 锁序；具名动作只使用既存锁，不补造缺失的锁条目。
    let writer = Lock::acquire_existing(original, ".writer.lock")?;
    admission.check(Stage::E5).map_err(|e| e.to_string())?;
    let maintenance = Lock::acquire_existing(original, ".maintenance.lock")?;
    let locks = DomainLocks::new(writer, maintenance, true);
    admission.check(Stage::E5).map_err(|e| e.to_string())?;
    if action != Action::Query {
        admission.authorize_named(contract.ok_or("AdmissionContractVersionMissing")?)?;
    }
    let source = if action == Action::Current {
        RecoveryObservation::through_r4(&admission)?
    } else {
        RecoveryObservation::probe(&admission)?
    };
    let mut started = admission
        .into_job(source.source().existing)
        .map_err(|e| e.to_string())?;
    let value = {
        let mut account = started.accounting();
        account.charge_requests(1).map_err(|e| e.to_string())?;
        super::admission_private::inspect_recovery(source.source(), &mut account, |conn| {
            observe(conn, &config, action, request, source.has_shm())
        })?
    };
    source.source().verify_before_open()?;
    let mut finished = started.seal().map_err(|e| e.to_string())?;
    finished
        .lease()
        .revalidate_paths()
        .map_err(|e| e.to_string())?;
    locks.check()?;
    output(&value, &mut finished)
}

pub(super) fn emit(
    db: &Path,
    admission: PreparedAdmission,
    action: Action,
    config: FrozenConfig,
    request: Option<Request>,
    contract: Option<NamedContract<'_>>,
) -> Result<(), String> {
    run(
        db,
        admission,
        action,
        config,
        request.as_ref(),
        contract,
        |value, account| {
            let mut payload = canonical_json(value).into_bytes();
            payload.push(b'\n');
            let budget = account.accounting().snapshot();
            if budget.wire_bytes + payload.len() as u128
                > u128::from(budget.limits.max_total_wire_bytes)
            {
                return Err("job_limit_exceeded：S恢复回包超过可用wire额度".into());
            }
            emit_accounted_payload(&payload, account)
        },
    )
}

pub(super) fn verify_startup(
    conn: &Connection,
    config: &FrozenConfig,
    request: &Request,
    epoch: &str,
) -> Result<(), String> {
    let receipt = observe(conn, config, Action::Current, Some(request), false)?;
    if receipt["writer_epoch"] != epoch {
        return Err("StaleWriter：具名恢复当前回执与配置写者代不一致".into());
    }
    Ok(())
}

fn observe(
    conn: &Connection,
    config: &FrozenConfig,
    action: Action,
    request: Option<&Request>,
    has_shm: bool,
) -> Result<Value, String> {
    let snapshot = Snapshot::read(conn, config)?;
    if action == Action::Inspect {
        return Ok(snapshot.inspect(has_shm));
    }
    let request = request.ok_or("InvalidDomain：具名恢复需要请求")?;
    request.check_identity(&snapshot)?;
    if let Some((epoch, receipt)) = request.original(conn, &config.clock)? {
        return match action {
            Action::Current
                if epoch != snapshot.epoch
                    || snapshot.cut != request.document["cut"]
                    || !snapshot.idle =>
            {
                Err("StaleWriter：历史恢复回执不能授权当前写者".into())
            }
            Action::Recover if has_shm => Err(UNPROVEN.into()),
            _ => Ok(receipt),
        };
    }
    if action != Action::Recover {
        return Err("MissingDependency：S具名恢复回执不存在".into());
    }
    preflight_transition(conn, &config.clock, request, &snapshot)?;
    // 本构建没有登记覆盖受控检查点及 EXCLUSIVE 写者的实测准入合同。
    Err("AdmissionNamedRecoveryContractUnregistered".into())
}

fn preflight_transition(
    conn: &Connection,
    clock: &ClockPlan,
    request: &Request,
    snapshot: &Snapshot,
) -> Result<(i64, String), String> {
    if request.from != snapshot.epoch {
        return Err("StaleWriter：S具名恢复前代与持久代不一致".into());
    }
    if request.document["cut"] != snapshot.cut {
        return Err(format!("{CONFLICT}：S具名恢复切面未命中当前持久切面"));
    }
    let event = required(&request.document, "clock_event_id")?;
    let time = planned(clock, event)?;
    let at = nonnegative(&time, "recover_ns")?;
    let used: bool = conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM s_clock_events WHERE clock_event_id=?1 AND phase='recover')",
        [event], |r| r.get(0),
    ).map_err(sql)?;
    if used || at < crate::parse_canonical_i64(&snapshot.phase_frontier, "clock frontier")? {
        return Err(format!("{CONFLICT}：S恢复时钟已使用或早于持久前沿"));
    }
    let next = request
        .from
        .checked_add(1)
        .ok_or("InvalidDomain：S恢复epoch溢出")?;
    Ok((next, time))
}

/// 未接物理资格的构建只在隔离测试中验证原 Recover 事务的变化面。
#[cfg(test)]
pub(super) struct TestTransition<'a> {
    pub(super) request: &'a Request,
    pub(super) config: &'a FrozenConfig,
}
#[cfg(test)]
impl TestTransition<'_> {
    pub(super) fn check(&self, conn: &Connection) -> Result<(i64, String), String> {
        let snapshot = Snapshot::read(conn, self.config)?;
        self.request.check_identity(&snapshot)?;
        if self.request.original(conn, &self.config.clock)?.is_some() {
            return Err(format!("{CONFLICT}：原回执必须走只读分支"));
        }
        preflight_transition(conn, &self.config.clock, self.request, &snapshot)
    }

    pub(super) fn record(
        &self,
        conn: &Connection,
        next: i64,
        expected: &str,
        at: &str,
    ) -> Result<Value, String> {
        if at != expected {
            return Err(INVALID.into());
        }
        let receipt = json!({"kind":"NamedRecoveryReceipt","request":self.request.document,
                             "writer_epoch":next.to_string(),"recover_ns":at});
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?1,?2)",
            params![self.request.key, canonical_json(&receipt)],
        )
        .map_err(sql)?;
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?1,?2)",
            params![epoch_key(next), self.request.epoch_binding()],
        )
        .map_err(sql)?;
        Ok(receipt)
    }

    pub(super) fn event(&self) -> Result<&str, String> {
        required(&self.request.document, "clock_event_id")
    }

    pub(super) fn next(&self) -> Result<String, String> {
        self.request
            .from
            .checked_add(1)
            .map(|n| n.to_string())
            .ok_or_else(|| "InvalidDomain：S恢复epoch溢出".into())
    }
}

fn read_exact(
    file: &File,
    account: &mut AdmissionAccounting<'_>,
    mut out: &mut [u8],
    mut offset: u64,
) -> Result<(), String> {
    while !out.is_empty() {
        account.pre_io_check().map_err(|e| e.to_string())?;
        let count = file.read_at(out, offset).map_err(sql)?;
        account
            .charge_wire_bytes(count as u64)
            .map_err(|e| e.to_string())?;
        if count == 0 {
            return Err(UNPROVEN.into());
        }
        offset += count as u64;
        out = &mut out[count..];
    }
    Ok(())
}

pub(super) fn validate_main(
    file: File,
    account: &mut AdmissionAccounting<'_>,
) -> Result<(), String> {
    let mut header = [0; 20];
    read_exact(&file, account, &mut header, 0)?;
    if &header[..16] != b"SQLite format 3\0" || header[18..20] != [2, 2] {
        return Err(UNPROVEN.into());
    }
    Ok(())
}

/// 0 字节且仍存在的 WAL 是已归零情形。非空 WAL 至少要有一个有效提交；头部
/// 或第一条提交不可读时，不让 SQLite 悄悄回落主库。最终读切面仍由 SQLite 选定。
pub(super) fn validate_wal(
    file: Option<File>,
    account: &mut AdmissionAccounting<'_>,
) -> Result<(), String> {
    let Some(file) = file else { return Ok(()) };
    account.pre_io_check().map_err(|e| e.to_string())?;
    let length = file.metadata().map_err(sql)?.len();
    if length == 0 {
        return Ok(());
    }
    let mut header = [0; 32];
    read_exact(&file, account, &mut header, 0)?;
    let big_endian = match be_word(&header[..4]) {
        0x377f0682 => false,
        0x377f0683 => true,
        _ => return Err(UNPROVEN.into()),
    };
    let page_size = be_word(&header[8..12]);
    if be_word(&header[4..8]) != 3_007_000
        || !(512..=65_536).contains(&page_size)
        || !page_size.is_power_of_two()
    {
        return Err(UNPROVEN.into());
    }
    let mut checksum = (0, 0);
    wal_checksum(&header[..24], big_endian, &mut checksum);
    if checksum != (be_word(&header[24..28]), be_word(&header[28..32])) {
        return Err(UNPROVEN.into());
    }
    let mut frame = vec![0; 24 + page_size as usize];
    let stride = frame.len() as u64;
    let mut offset = 32;
    while length - offset >= stride {
        read_exact(&file, account, &mut frame, offset)?;
        if frame[8..16] != header[16..24] || be_word(&frame[..4]) == 0 {
            break;
        }
        wal_checksum(&frame[..8], big_endian, &mut checksum);
        wal_checksum(&frame[24..], big_endian, &mut checksum);
        if checksum != (be_word(&frame[16..20]), be_word(&frame[20..24])) {
            break;
        }
        if be_word(&frame[4..8]) != 0 {
            return Ok(());
        }
        offset += stride;
    }
    Err(UNPROVEN.into())
}

fn be_word(bytes: &[u8]) -> u32 {
    u32::from_be_bytes(bytes.try_into().expect("WAL word has four bytes"))
}

fn wal_checksum(bytes: &[u8], be: bool, state: &mut (u32, u32)) {
    let word = |input: &[u8]| {
        let input = input.try_into().expect("WAL word has four bytes");
        if be {
            u32::from_be_bytes(input)
        } else {
            u32::from_le_bytes(input)
        }
    };
    for pair in bytes.chunks_exact(8) {
        state.0 = state.0.wrapping_add(word(&pair[..4])).wrapping_add(state.1);
        state.1 = state.1.wrapping_add(word(&pair[4..])).wrapping_add(state.0);
    }
}
