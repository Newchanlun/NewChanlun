//! #1375：E 外部接纳连续性守卫、正常停机交接与独立来源实时核验（SPEC C06.4–6）。
//!
//! - 不复活核清布尔位：不接受无独立原件支撑的主体自报 `events` 列表来解除封闸，也不落盘
//!   跳过复核的 `source_verified_handoff`。每次 `Reserve`/`ReleaseExact` 放行都在 E 写事务内
//!   由来源连续性、责任范围、缺口状态与当前放行前沿共同推出。
//! - 预武装租约：E 启动 serve 前即写入 `serving`，进程死在故障之前下一任仍见缺口。
//! - 正常交接：仅当本代收到显式停机信号（SIGTERM/SIGINT）、transport 无异常退出/丢帧/丢应答、
//!   本代无来源缺口且无缺口未核 Pending 时，才把当前 `(epoch, commit_seq, root_hash)` 落盘为
//!   一次性 `clean_handoff`。进程正常退出只证明本次服务期间已受理连接排空，不伪造来源历史。
//! - 独立持久原件来源：
//!   1. `test_only_capture_tape`：按本次放行提交时刻 `commit_ns` 实时核对全部已发原件（不拦未来项），
//!      同游标逐件核原字节/指针/token/来源身份。
//!   2. `history_simulation_source`：每次放行实时只读冷审冻结 `x_db` 全量已提交批与原件（`#1381`
//!      `validate_existing` + 无 `pending_batch` + 无在途 `x_exact_commands` + `x_sim_batches`/`x_sim_originals`
//!      前缀一致；缺口态拒绝空快照），防止核完后 X 继续推进而漏计新增原件。
//!   3. 多来源共同覆盖：缺口态下逐一核对 manifest 中所有 `CaptureExternal` 主体；任一主体缺少独立
//!      持久原件来源或存在漏件，整次新风险继续保持关闭，不简单凑主体。
//! - 责任范围：未知范围（`account:*`）或未覆盖 Pending 保守全域拦截；已知范围且已由 E 持久责任
//!   充分覆盖的无关 Pending 不额外全局停摆；受影响责任范围的缺口 Pending 须经正式核清。
use super::book::{decode, fact_key};
use super::store::{check_epoch, err, immediate, latest, set_meta, Config};
use crate::session_protocol::{
    canonical_json, nonnegative, positive, required, sha256_hex, strict_json,
};
use rusqlite::{Connection, OptionalExtension};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::sync::{Arc, Mutex};

const LEASE: &str = "external_intake_lease/1";
const TAPE: &str = "test_only_capture_tape";
const FORMAT: &str = "test-only-economic-source/1";
const WHO: [&str; 4] = [
    "source_namespace",
    "source_epoch",
    "producer_id",
    "producer_epoch",
];

fn authorized_manifest(manifest: &Value, op: &str) -> bool {
    manifest["authorized_sources"]
        .as_array()
        .is_some_and(|rows| {
            rows.iter().any(|p| {
                p["operations"]
                    .as_array()
                    .is_some_and(|ops| ops.iter().any(|o| o == op))
            })
        })
}

pub(super) fn relevant(c: &Config) -> bool {
    c.domain == "E"
        && super::finance::enabled(c)
        && authorized_manifest(&c.manifest, "CaptureExternal")
        && (authorized_manifest(&c.manifest, "Reserve")
            || authorized_manifest(&c.manifest, "ReleaseExact"))
}

fn principal_key(v: &Value) -> Result<String, String> {
    Ok(canonical_json(&json!({
        "source_namespace": required(v, "source_namespace")?,
        "source_epoch": required(v, "source_epoch")?,
        "producer_id": required(v, "producer_id")?,
        "producer_epoch": required(v, "producer_epoch")?,
    })))
}

fn record_principal_key(r: &Value) -> Result<String, String> {
    Ok(canonical_json(&json!({
        "source_namespace": required(&r["origin_message"], "source_namespace")?,
        "source_epoch": required(&r["origin_message"], "source_epoch")?,
        "producer_id": required(&r["source_producer"], "producer_id")?,
        "producer_epoch": required(&r["source_producer"], "producer_epoch")?,
    })))
}

fn capture_principals(manifest: &Value) -> Result<BTreeSet<String>, String> {
    let mut set = BTreeSet::new();
    for p in manifest["authorized_sources"]
        .as_array()
        .ok_or("InvalidDomain：缺来源")?
    {
        if p["operations"]
            .as_array()
            .is_some_and(|ops| ops.iter().any(|o| o == "CaptureExternal"))
        {
            set.insert(principal_key(p)?);
        }
    }
    Ok(set)
}

fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
}

/// 纯结构校验，不读磁盘原件文件：允许已释放命令后来源离线时仍能打开库、恢复与查询历史收据。
pub(super) fn validate_config(manifest: &Value) -> Result<(), String> {
    let Some(binding) = manifest.get(TAPE) else {
        return Ok(());
    };
    super::voice::exact(binding, &["path", "sha256"])?;
    let path = required(binding, "path")?;
    let sha = required(binding, "sha256")?;
    if !is_hex64(sha) {
        return Err("InvalidDomain：TestOnly 来源摘要须为 64 位小写十六进制 SHA-256".into());
    }
    if !Path::new(path).is_absolute()
        || manifest["clock"]["kind"] != "TestOnly"
        || manifest.get("history_simulation_source").is_some()
        || !super::finance::exact_release_selected(manifest)
        || !authorized_manifest(manifest, "CaptureExternal")
        || !(authorized_manifest(manifest, "Reserve")
            || authorized_manifest(manifest, "ReleaseExact"))
    {
        return Err("InvalidDomain：封闭原件源仅属于具名 TestOnly 精确交付域".into());
    }
    Ok(())
}

pub(super) fn initialize(db: &Connection, c: &Config) -> Result<(), String> {
    validate_config(&c.manifest)?;
    if relevant(c) {
        if c.manifest.get(TAPE).is_some() {
            Tape::load(c)?;
        }
        set_meta(db, LEASE, "not-yet-serving")?;
    }
    Ok(())
}

#[derive(Default)]
struct IntakeState {
    source_gap: bool,
    had_gap: bool,
}

#[derive(Clone, Default)]
pub(crate) struct Intake(Option<Arc<Mutex<IntakeState>>>);

/// 只有消费 init 一次性交接或经核优雅停机 `clean_handoff` 的 actor 才无来源缺口。
/// recover 只换 epoch，不补发交接；旧库（无租约）与异常停机（serving）均保守进入缺口态，
/// 且不在内存或租约表里通过核清布尔位抹去缺口，而是每次新风险由独立持久来源实时核验。
pub(super) fn start(db: &mut Connection, c: &Config, epoch: i64) -> Result<Intake, String> {
    if !relevant(c) {
        return Ok(Intake::default());
    }
    let tx = immediate(db)?;
    check_epoch(&tx, epoch)?;
    let state: Option<String> = tx
        .query_row("SELECT v FROM meta WHERE k=?", [LEASE], |r| r.get(0))
        .optional()
        .map_err(err)?;
    let (source_gap, had_gap) = match state.as_deref() {
        Some("not-yet-serving") => {
            set_meta(&tx, LEASE, "serving")?;
            let fresh = epoch == 1;
            (!fresh, !fresh)
        }
        Some(raw) if raw.starts_with('{') => {
            let seal = strict_json(raw.as_bytes())
                .map_err(|_| "StorageUnavailable：外部接纳交接记录损坏".to_owned())?;
            let (seq, root, _, _) = latest(&tx)?;
            if seal["kind"].as_str() != Some("clean_handoff") {
                return Err("StorageUnavailable：外部接纳交接记录损坏".into());
            }
            super::voice::exact(&seal, &["kind", "epoch", "commit_seq", "root_hash"])?;
            let prev_epoch = positive(required(&seal, "epoch")?, "handoff.epoch")?;
            let seal_seq = nonnegative(required(&seal, "commit_seq")?, "handoff.commit_seq")?;
            let seal_root = required(&seal, "root_hash")?;
            if prev_epoch > epoch || seal_seq != seq || seal_root != root {
                return Err("StorageUnavailable：外部接纳交接记录与当前切面不符".into());
            }
            set_meta(&tx, LEASE, "serving")?;
            (false, false)
        }
        // 旧库存量没有初次交接，不能把不在场误作连续；写入 serving 以便后续异常停机仍可察觉。
        Some("serving") | None => {
            set_meta(&tx, LEASE, "serving")?;
            (true, true)
        }
        _ => return Err("StorageUnavailable：外部接纳交接记录损坏".into()),
    };
    tx.commit().map_err(err)?;
    Ok(Intake(Some(Arc::new(Mutex::new(IntakeState {
        source_gap,
        had_gap,
    })))))
}

/// 仅当收到显式停机信号（SIGTERM/SIGINT）、transport 正常返回且无不确定故障、
/// 本代全程无来源缺口且无缺口未核 Pending 时，才落盘一次性 `clean_handoff`。
pub(super) fn finish_clean(
    db: &mut Connection,
    c: &Config,
    epoch: i64,
    explicit_stop: bool,
    transport_uncertain: bool,
) -> Result<(), String> {
    if !relevant(c) || !explicit_stop {
        return Ok(());
    }
    let Some(lock) = &c.intake.0 else {
        return Ok(());
    };
    let (source_gap, had_gap) = {
        let s = lock
            .lock()
            .map_err(|_| "StorageUnavailable：接纳状态锁损坏")?;
        (s.source_gap, s.had_gap)
    };
    if source_gap || transport_uncertain {
        return Ok(());
    }
    let tx = immediate(db)?;
    check_epoch(&tx, epoch)?;
    let lease: Option<String> = tx
        .query_row("SELECT v FROM meta WHERE k=?", [LEASE], |r| r.get(0))
        .optional()
        .map_err(err)?;
    if lease.as_deref() != Some("serving") {
        return Ok(());
    }
    let (seq, root, _, image) = latest(&tx)?;
    if had_gap
        && image["pending"]
            .as_array()
            .is_none_or(|items| !items.is_empty())
    {
        return Ok(());
    }
    let seal = canonical_json(&json!({
        "kind": "clean_handoff",
        "epoch": epoch.to_string(),
        "commit_seq": seq.to_string(),
        "root_hash": root,
    }));
    set_meta(&tx, LEASE, &seal)?;
    tx.commit().map_err(err)?;
    Ok(())
}

fn target_owners(record: &Value) -> Result<BTreeSet<String>, String> {
    let mut owners = BTreeSet::new();
    match record["state"].as_str() {
        Some("ReleasedExact") => {
            owners.insert(required(record, "owner")?.to_owned());
        }
        Some("Reserved") => {
            for g in record["grants"]
                .as_array()
                .ok_or("StorageUnavailable：Reserved 缺 grants")?
            {
                owners.insert(required(g, "owner")?.to_owned());
            }
        }
        _ => {}
    }
    Ok(owners)
}

fn check_scoped_pending(
    c: &Config,
    image: &Value,
    owners: &BTreeSet<String>,
    had_gap: bool,
) -> Result<(), String> {
    let pending = image["pending"]
        .as_array()
        .ok_or("StorageUnavailable：缺 Pending")?;
    if pending.is_empty() {
        return Ok(());
    }
    let retained: Vec<Value> = image["finance"]["responsibilities"]
        .as_array()
        .ok_or("MissingDependency：缺 E 已持久责任集合")?
        .iter()
        .filter_map(|r| r["source"]["covered_facts"].as_array())
        .flatten()
        .cloned()
        .collect();
    let is_tb03c = c.book_rules()?.is_tb03c();
    for p in pending {
        // 先复用既有完整责任界判据：未覆盖、account:* 未知范围、AwaitingPolicy、
        // 未满足 AwaitingDependency 一律立即拒绝，保护共享账户约束。
        super::finance::covered_pending(image, &retained, p)?;
        if had_gap && is_tb03c {
            let scope = required(p, "scope")?;
            // 未知范围（account:*）已在 covered_pending 拒收；此处仅阻断受本次风险影响的
            // 责任范围，已核且充分覆盖的无关重 Pending 不额外使全账停摆。
            if owners.contains(scope) {
                let key = required(p, "fact_key")?;
                return Err(format!(
                    "MissingDependency：受影响责任范围 {scope} 的缺口事实 {key} 仍为 Pending，须先经正式核清"
                ));
            }
        }
    }
    Ok(())
}

/// 在 E 放行写事务内实时冷审冻结 `history_simulation_source`，把 `x_db` 全量已提交原件
/// 与当前 `image["recorded"]` 逐字对照。不写核清布尔位，X 随后推进新批会在下次放行立刻被拦。
fn verify_simulation_live(
    c: &Config,
    image: &Value,
    record: &Value,
    require_committed_frontier: bool,
) -> Result<String, String> {
    let binding = &c.manifest["history_simulation_source"];
    let sim_principal = principal_key(binding)?;
    let (expected_x_id, expected_x_epoch) = if record["state"] == "ReleasedExact" {
        let cmd = &record["command"];
        let x_id = required(cmd, "x_id")?;
        let x_epoch = cmd["x_epoch"]
            .as_i64()
            .filter(|e| *e > 0)
            .ok_or("IdentityConflict：ReleaseExact 命令缺正整数 x_epoch")?;
        (Some(x_id), Some(x_epoch))
    } else {
        (None, None)
    };
    let history = crate::history_simulation::intake::committed_capture_frontier(
        &c.manifest,
        expected_x_id,
        expected_x_epoch,
        require_committed_frontier,
    )?;
    let facts = image["recorded"]
        .as_array()
        .ok_or("StorageUnavailable：缺 Recorded")?;
    let mut recorded_from_sim = BTreeMap::new();
    for rec in facts {
        if record_principal_key(rec)? == sim_principal {
            recorded_from_sim.insert(required(rec, "fact_key")?.to_owned(), rec);
        }
    }
    let originals = history["originals"]
        .as_array()
        .ok_or("StorageUnavailable：模拟历史缺原件列表")?;
    let rules = c.book_rules()?;
    let mut seen = BTreeSet::new();
    for doc in originals {
        let raw = canonical_json(doc);
        let (_, event) = decode(&raw, "/event", rules)?;
        let key = fact_key(&event)?;
        if !seen.insert(key.clone()) {
            return Err("IdentityConflict：模拟 X 原件身份重复".into());
        }
        let rec = recorded_from_sim
            .get(&key)
            .ok_or_else(|| format!("MissingDependency：模拟 X 原件未补录 {key}"))?;
        if rec["raw_utf8"] != raw || rec["json_pointer"] != "/event" {
            return Err("IdentityConflict：模拟 X 原件与 E 已接纳事实不一致".into());
        }
    }
    if seen.len() != recorded_from_sim.len() {
        return Err("IdentityConflict：E 存在模拟 X 完整历史之外的游离原件".into());
    }
    Ok(sim_principal)
}

impl Intake {
    pub(super) fn failed(&self, reason: &str) {
        // 已授权且原件可解码。明确的身份/输入拒绝不算日志故障；存储、超时、来源不可核等
        // 不确定结果则进入缺口态，含 COMMIT 返回未知。已提交事实仍由原收据认回。
        if !reason.starts_with("IdentityConflict")
            && !reason.starts_with("InvalidDomain")
            && !reason.starts_with("SchemaUnsupported")
            && !reason.starts_with("StaleWriter")
        {
            if let Some(lock) = &self.0 {
                if let Ok(mut s) = lock.lock() {
                    s.source_gap = true;
                    s.had_gap = true;
                }
            }
        }
    }

    pub(super) fn check_new_risk(
        &self,
        c: &Config,
        image: &Value,
        record: &Value,
        at: &str,
    ) -> Result<(), String> {
        let (source_gap, had_gap) = match &self.0 {
            Some(lock) => {
                let s = lock
                    .lock()
                    .map_err(|_| "StorageUnavailable：接纳状态锁损坏")?;
                (s.source_gap, s.had_gap)
            }
            None => (false, false),
        };
        let owners = target_owners(record)?;
        let principals = capture_principals(&c.manifest)?;
        let has_tape = c.manifest.get(TAPE).is_some();
        let has_sim = c.manifest["history_simulation_source"].is_object();
        let mut covered_principals = BTreeSet::new();

        if has_tape {
            let tape = Tape::load(c)?;
            let now = nonnegative(at, "commit_ns")?;
            let facts = image["recorded"]
                .as_array()
                .ok_or("StorageUnavailable：缺 Recorded")?;
            for (key, item) in &tape.items {
                // 始终按本次放行提交时刻作为来源真实结束界：未来尚未发出的事实不得挡在当前放行前。
                if item.emitted_ns > now {
                    continue;
                }
                let r = facts
                    .iter()
                    .find(|r| r["fact_key"] == key.as_str())
                    .ok_or_else(|| format!("MissingDependency：TestOnly 来源未补录 {key}"))?;
                item.verify(r, &tape.source)?;
            }
            covered_principals.insert(principal_key(&tape.source)?);
        }

        if has_sim {
            let sim_principal = verify_simulation_live(c, image, record, source_gap)?;
            covered_principals.insert(sim_principal);
        }

        if source_gap {
            for principal in &principals {
                if !covered_principals.contains(principal) {
                    return Err(format!(
                        "MissingDependency：E 外部接纳存在未核来源缺口，获准来源 {principal} 缺少独立持久原件与可证结束界，不能仅凭自述放行新风险"
                    ));
                }
            }
        }

        if has_tape || has_sim || had_gap {
            check_scoped_pending(c, image, &owners, had_gap)?;
        }
        Ok(())
    }
}
struct Original {
    raw: Arc<str>,
    pointer: String,
    token: String,
    emitted_ns: i64,
}
impl Original {
    fn verify(&self, r: &Value, source: &Value) -> Result<(), String> {
        if r["raw_utf8"].as_str() != Some(self.raw.as_ref())
            || r["json_pointer"] != self.pointer
            || r["token"] != self.token
            || r["source_producer"]["producer_id"] != source["producer_id"]
            || r["source_producer"]["producer_epoch"] != source["producer_epoch"]
            || r["origin_message"]["source_namespace"] != source["source_namespace"]
            || r["origin_message"]["source_epoch"] != source["source_epoch"]
        {
            return Err(
                "IdentityConflict：原件、指针、token 或来源身份不等于冻结 TestOnly 来源".into(),
            );
        }
        Ok(())
    }
}

/// 冻结 TestOnly 封闭源：新 Capture 只接受该文件成员；按提交时刻 `commit_ns` 对账至实际已发出边界。
/// 不能把任意 adapter 的一次导出、单个批的 QueryBatch 或请求人的「全部送完」传成这类来源。
struct Tape {
    source: Value,
    items: BTreeMap<String, Original>,
}
impl Tape {
    fn load(c: &Config) -> Result<Self, String> {
        validate_config(&c.manifest)?;
        let binding = &c.manifest[TAPE];
        let path = required(binding, "path")?;
        let raw = super::finance::original_raw(path, "只读 TestOnly 原件源")?;
        if sha256_hex(raw.as_bytes()) != required(binding, "sha256")? {
            return Err("MissingDependency：冻结的 TestOnly 来源内容不可核".into());
        }
        let tape = strict_json(raw.as_bytes())?;
        super::voice::exact(
            &tape,
            &[
                "format",
                "session_id",
                "session_generation",
                "source",
                "documents",
            ],
        )?;
        if tape["format"] != FORMAT
            || tape["session_id"] != c.session
            || tape["session_generation"] != c.generation
        {
            return Err("IdentityConflict：TestOnly 来源版本/会话/化身不符".into());
        }
        let source = &tape["source"];
        super::voice::exact(source, &WHO)?;
        let mut captures = c.manifest["authorized_sources"]
            .as_array()
            .ok_or("InvalidDomain：缺来源")?
            .iter()
            .filter(|p| {
                p["operations"]
                    .as_array()
                    .is_some_and(|ops| ops.iter().any(|o| o == "CaptureExternal"))
            })
            .peekable();
        if captures.peek().is_none() || !captures.all(|p| WHO.iter().all(|k| p[k] == source[k])) {
            return Err("InvalidDomain：TestOnly 封闭源须覆盖全部获准外部接纳主体".into());
        }
        let rules = c.book_rules()?;
        let mut items = BTreeMap::new();
        let mut tokens = BTreeSet::new();
        let mut previous = 0;
        for doc in tape["documents"]
            .as_array()
            .ok_or("InvalidDomain：TestOnly 来源缺原件序列")?
        {
            super::voice::exact(doc, &["emitted_ns", "raw_utf8", "tokens"])?;
            let emitted_ns = nonnegative(required(doc, "emitted_ns")?, "emitted_ns")?;
            if emitted_ns < previous {
                return Err("InvalidDomain：TestOnly 来源发出顺序倒退".into());
            }
            previous = emitted_ns;
            let raw: Arc<str> = required(doc, "raw_utf8")?.into();
            let envelope = strict_json(raw.as_bytes())?;
            if envelope["format"]
                != "neutral TestOnly economic raw originals; not production transport wire"
            {
                return Err("SchemaUnsupported：封闭源只接受中性 TestOnly 经济原件".into());
            }
            let events = envelope["events"]
                .as_array()
                .filter(|es| !es.is_empty())
                .ok_or("InvalidDomain：原件无事件")?;
            let ids = doc["tokens"]
                .as_array()
                .filter(|ts| ts.len() == events.len())
                .ok_or("InvalidDomain：原件须逐事件绑定 token")?;
            for (index, (event, id)) in events.iter().zip(ids).enumerate() {
                let token = id
                    .as_str()
                    .filter(|t| !t.is_empty())
                    .ok_or("InvalidDomain：token 为空")?
                    .to_owned();
                let pointer = format!("/events/{index}");
                super::book::decode(&raw, &pointer, rules)?;
                if ["source_namespace", "source_epoch"]
                    .iter()
                    .any(|k| event["source"][k] != source[k])
                    || !tokens.insert(token.clone())
                {
                    return Err("IdentityConflict：来源错绑或重复 token".into());
                }
                let item = Original {
                    raw: raw.clone(),
                    pointer,
                    token,
                    emitted_ns,
                };
                if items.insert(fact_key(event)?, item).is_some() {
                    return Err("IdentityConflict：TestOnly 原件身份重复".into());
                }
            }
        }
        Ok(Tape {
            source: source.clone(),
            items,
        })
    }
}

pub(super) fn verify_member(c: &Config, r: &Value) -> Result<(), String> {
    if c.manifest.get(TAPE).is_some() {
        let tape = Tape::load(c)?;
        let item = tape
            .items
            .get(required(r, "fact_key")?)
            .ok_or("IdentityConflict：事实不在冻结 TestOnly 来源")?;
        item.verify(r, &tape.source)?;
        if nonnegative(required(r, "received_ns")?, "received_ns")? < item.emitted_ns {
            return Err("InvalidDomain：TestOnly 原件尚未发出".into());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::economic_session::book::hash;
    use crate::session_protocol::canonical_json;
    use serde_json::json;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering as SeqOrdering};

    struct TempDir(PathBuf);
    impl TempDir {
        fn new(label: &str) -> Self {
            static COUNTER: AtomicU64 = AtomicU64::new(0);
            let n = COUNTER.fetch_add(1, SeqOrdering::Relaxed);
            let dir = std::env::temp_dir().join(format!(
                "nc-capture-continuity-{label}-{}-{n}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&dir);
            std::fs::create_dir_all(&dir).unwrap();
            Self(dir)
        }
    }
    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn test_source() -> Value {
        json!({
            "source_namespace": "test",
            "source_epoch": "one",
            "producer_id": "unit",
            "producer_epoch": "1"
        })
    }

    fn make_raw_doc_for(ext_id: &str, cursor: &str, chong_id: &str) -> String {
        let doc = json!({
            "format": "neutral TestOnly economic raw originals; not production transport wire",
            "units": {
                "quantity": {"unit": "TEST-UNIT", "quantum": "1"},
                "money": {"unit": "TEST-CASH", "currency": "TEST-CASH", "quantum": "1"},
                "numeric_encoding": "exact_decimal_integer_text"
            },
            "events": [{
                "event": "known-opening",
                "allocation_id": format!("alloc-{ext_id}"),
                "family_id": format!("fam-{ext_id}"),
                "source": {
                    "source_namespace": "test",
                    "source_epoch": "one",
                    "external_fact_id": ext_id,
                    "source_cursor": cursor,
                    "received_time": "source-received",
                    "claimed_origin": "TestOnly source",
                    "source_event_time": "100"
                },
                "book_identity": {
                    "chong_id": chong_id,
                    "symbol": chong_id,
                    "op_level": "2",
                    "fixed_q": "12",
                    "side": "long"
                },
                "stable_point": {"profile": "TestOnly", "seq": "1", "source_ref": "sp"},
                "observed_existing_book": {
                    "units": "1",
                    "Pi": "0",
                    "A": "14",
                    "W": "0",
                    "witness_refs": {"units": "u", "Pi": "p", "A": "a", "W": "w"}
                },
                "known_cost_components": [{
                    "kind": "acquisition_cash",
                    "amount_text": "14",
                    "canonical_amount": "14",
                    "source_ref": "cost",
                    "currency": "TEST-CASH",
                    "quantum": "1"
                }]
            }],
            "evidence_index": {
                "fragments": {
                    "sp": [{"json_pointer": "/events/0/stable_point"}],
                    "u": [{"json_pointer": "/events/0/observed_existing_book/units"}],
                    "p": [{"json_pointer": "/events/0/observed_existing_book/Pi"}],
                    "a": [{"json_pointer": "/events/0/observed_existing_book/A"}],
                    "w": [{"json_pointer": "/events/0/observed_existing_book/W"}],
                    "cost": [{"json_pointer": "/events/0/known_cost_components/0"}]
                }
            }
        });
        canonical_json(&doc)
    }

    fn make_record(raw_utf8: &str, token: &str, emitted_ns: &str) -> Value {
        let doc = strict_json(raw_utf8.as_bytes()).unwrap();
        let ev = &doc["events"][0];
        let fk = fact_key(ev).unwrap();
        let raw_hash = sha256_hex(raw_utf8.as_bytes());
        let fh = hash(&json!({
            "raw_sha256": raw_hash,
            "json_pointer": "/events/0",
            "event": ev,
            "units": doc["units"]
        }));
        json!({
            "fact_key": fk,
            "fact_hash": fh,
            "raw_sha256": raw_hash,
            "raw_utf8": raw_utf8,
            "json_pointer": "/events/0",
            "event": ev,
            "token": token,
            "received_ns": emitted_ns,
            "source_producer": {
                "producer_id": "unit",
                "producer_epoch": "1"
            },
            "origin_message": {
                "source_namespace": "test",
                "source_epoch": "one"
            }
        })
    }

    fn release_record(owner: &str) -> Value {
        json!({"state": "ReleasedExact", "owner": owner})
    }

    fn make_intake(source_gap: bool, had_gap: bool) -> Intake {
        Intake(Some(Arc::new(Mutex::new(IntakeState {
            source_gap,
            had_gap,
        }))))
    }

    fn is_gap(intake: &Intake) -> bool {
        intake.0.as_ref().unwrap().lock().unwrap().source_gap
    }

    fn make_config(tape_binding: Option<Value>) -> Config {
        let mut manifest = json!({
            "schema_revision": "economic-manifest/1",
            "session_id": "unit-sess",
            "session_generation": "1",
            "book_revision": "tb03c-book/1",
            "clock": {"kind": "TestOnly"},
            "finance": {
                "schema_revision": "tb03b-finance/5",
                "coordinator_source": test_source()
            },
            "authorized_sources": [{
                "source_namespace": "test",
                "source_epoch": "one",
                "producer_id": "unit",
                "producer_epoch": "1",
                "operations": ["CaptureExternal", "Reserve", "ReleaseExact", "ResolveEvidence"]
            }]
        });
        if let Some(binding) = tape_binding {
            manifest[TAPE] = binding;
        }
        let manifest_hash = hash(&manifest);
        Config {
            manifest,
            manifest_hash,
            domain: "E".into(),
            session: "unit-sess".into(),
            generation: "1".into(),
            producer: "E:unit-sess".into(),
            db: PathBuf::from("/tmp/unused-e.db"),
            socket: PathBuf::from("/tmp/unused-e.sock"),
            intake: Intake::default(),
        }
    }

    fn write_tape(dir: &Path, documents: Value) -> Value {
        let tape = json!({
            "format": FORMAT,
            "session_id": "unit-sess",
            "session_generation": "1",
            "source": test_source(),
            "documents": documents
        });
        let raw = canonical_json(&tape);
        let p = dir.join("tape.json");
        std::fs::write(&p, &raw).unwrap();
        json!({"path": p.to_str().unwrap(), "sha256": sha256_hex(raw.as_bytes())})
    }

    fn setup_meta_db() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch(
            "CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
             CREATE TABLE commits(seq INTEGER PRIMARY KEY, prev_root TEXT NOT NULL, root TEXT NOT NULL, commit_ns TEXT NOT NULL, image TEXT NOT NULL);",
        )
        .unwrap();
        set_meta(&c, "writer_epoch", "1").unwrap();
        c.execute(
            "INSERT INTO commits VALUES(1,'0000','root-1','10','{\"pending\":[]}')",
            [],
        )
        .unwrap();
        c
    }

    #[test]
    fn pre_armed_lease_and_clean_handoff_distinguish_healthy_vs_crash_and_fault() {
        let mut cfg = make_config(None);
        let mut db = setup_meta_db();
        initialize(&db, &cfg).unwrap();

        let first = start(&mut db, &cfg, 1).unwrap();
        assert!(!is_gap(&first));

        // 非显式停机（explicit_stop=false，如 transport 异常退出）绝不得签发 clean_handoff。
        cfg.intake = first.clone();
        finish_clean(&mut db, &cfg, 1, false, false).unwrap();
        let lease_after_abnormal: String = db
            .query_row("SELECT v FROM meta WHERE k=?", [LEASE], |r| r.get(0))
            .unwrap();
        assert_eq!(lease_after_abnormal, "serving");

        // 优雅停机（显式停机、无故障、输送无不确定）落盘一次性 clean_handoff；换代后可无缝续接。
        cfg.intake = first;
        finish_clean(&mut db, &cfg, 1, true, false).unwrap();
        set_meta(&db, "writer_epoch", "2").unwrap();
        let clean_next = start(&mut db, &cfg, 2).unwrap();
        assert!(!is_gap(&clean_next));

        // 未经优雅停机即重开（模拟 SIGKILL 崩溃），租约已是 serving，仍按缺口封闸。
        let after_kill = start(&mut db, &cfg, 2).unwrap();
        assert!(is_gap(&after_kill));

        // 写失败触发缺口后，即使随后收到 SIGTERM 也不得签发 clean_handoff。
        let faulted = make_intake(false, false);
        faulted.failed("StorageUnavailable：database or disk is full");
        assert!(is_gap(&faulted));
        cfg.intake = faulted;
        finish_clean(&mut db, &cfg, 2, true, false).unwrap();
        set_meta(&db, "writer_epoch", "3").unwrap();
        let after_fault_term = start(&mut db, &cfg, 3).unwrap();
        assert!(is_gap(&after_fault_term));

        // 输送丢帧/丢应答（transport_uncertain=true）同样不得签发 clean_handoff。
        cfg.intake = make_intake(false, false);
        finish_clean(&mut db, &cfg, 3, true, true).unwrap();
        set_meta(&db, "writer_epoch", "4").unwrap();
        let after_transport_uncertain = start(&mut db, &cfg, 4).unwrap();
        assert!(is_gap(&after_transport_uncertain));

        // R2 遗留或伪造的 source_verified_handoff 布尔免检章必须被启动校验拒绝。
        set_meta(
            &db,
            LEASE,
            &canonical_json(&json!({
                "kind": "source_verified_handoff",
                "epoch": "4",
                "commit_seq": "1",
                "root_hash": "root-1",
                "source_kind": "history_simulation_source",
                "proof_sha256": "a".repeat(64),
            })),
        )
        .unwrap();
        let forged_seal_err = start(&mut db, &cfg, 4).err().unwrap();
        assert!(
            forged_seal_err.contains("交接记录损坏"),
            "{forged_seal_err}"
        );
        set_meta(&db, LEASE, "serving").unwrap();

        // 篡改 clean_handoff 指向错误切面根，拒绝启动。
        set_meta(
            &db,
            LEASE,
            &canonical_json(&json!({
                "kind": "clean_handoff",
                "epoch": "4",
                "commit_seq": "1",
                "root_hash": "wrong-root"
            })),
        )
        .unwrap();
        let err = start(&mut db, &cfg, 4).err().unwrap();
        assert!(err.starts_with("StorageUnavailable"), "{err}");

        // 即使手工篡改 meta 回 not-yet-serving，epoch != 1 仍不放行。
        set_meta(&db, LEASE, "not-yet-serving").unwrap();
        let forged = start(&mut db, &cfg, 4).unwrap();
        assert!(is_gap(&forged));

        // 无租约记录的旧库保守视为缺口，不能靠无租约直接判安全。
        db.execute("DELETE FROM meta WHERE k=?", [LEASE]).unwrap();
        let legacy = start(&mut db, &cfg, 4).unwrap();
        assert!(is_gap(&legacy));

        // 损坏租约值明确以 StorageUnavailable 拒绝。
        set_meta(&db, LEASE, "corrupted").unwrap();
        let err = start(&mut db, &cfg, 4).err().unwrap();
        assert!(err.starts_with("StorageUnavailable"), "{err}");
    }

    #[test]
    fn failed_classifies_input_rejections_vs_fault_uncertainties() {
        let intake = make_intake(false, false);
        for benign in [
            "IdentityConflict：重复",
            "InvalidDomain：非法",
            "SchemaUnsupported：版本",
            "StaleWriter：陈旧",
        ] {
            intake.failed(benign);
            assert!(!is_gap(&intake), "{benign} should not trip gap");
        }
        for fault in [
            "StorageUnavailable：database or disk is full",
            "MissingDependency：来源不可读",
            "DeliveryUnknown：提交结果未知",
            "Incomplete：超时",
        ] {
            let guard = make_intake(false, false);
            guard.failed(fault);
            assert!(is_gap(&guard), "{fault} must trip gap");
        }
    }

    #[test]
    fn tape_gap_checks_release_time_bound_same_cursor_and_scoped_pending() {
        let dir = TempDir::new("gap-clear");
        let raw_fill = make_raw_doc_for("fill-1", "2", "alpha");
        let raw_fee = make_raw_doc_for("fee-1", "2", "alpha");
        let raw_beta = make_raw_doc_for("beta-1", "2", "beta");
        let raw_future = make_raw_doc_for("future-1", "3", "alpha");
        let binding = write_tape(
            &dir.0,
            json!([
                {"emitted_ns": "179", "raw_utf8": raw_fill, "tokens": ["tok-fill"]},
                {"emitted_ns": "179", "raw_utf8": raw_fee, "tokens": ["tok-fee"]},
                {"emitted_ns": "179", "raw_utf8": raw_beta, "tokens": ["tok-beta"]},
                {"emitted_ns": "2000", "raw_utf8": raw_future, "tokens": ["tok-future"]}
            ]),
        );
        let cfg = make_config(Some(binding));
        let rec_fill = make_record(&raw_fill, "tok-fill", "179");
        let rec_fee = make_record(&raw_fee, "tok-fee", "179");
        let rec_beta = make_record(&raw_beta, "tok-beta", "179");
        let covered_entry = |r: &Value| {
            json!({
                "fact_key": r["fact_key"],
                "fact_hash": r["fact_hash"],
                "token": r["token"]
            })
        };
        let pending_entry = |r: &Value, scope: &str| {
            json!({
                "fact_key": r["fact_key"],
                "token": r["token"],
                "target_domain": scope,
                "status": "Pending",
                "reason": {"kind": "Unresolved"},
                "scope": scope
            })
        };
        let base_image = |recorded: Value, pending: Value, covered: Value| {
            json!({
                "recorded": recorded,
                "pending": pending,
                "finance": {
                    "responsibilities": [{
                        "responsibility_id": "existing20",
                        "amount": "20",
                        "source": {"covered_facts": covered}
                    }]
                }
            })
        };

        let rel_alpha = release_record("B:alpha");
        let rel_beta = release_record("B:beta");

        // 故障态（gap=true）在 1202 放行：只核 emitted_ns <= 1202，不要求 2000 才出现的未来原件。
        let gapped = make_intake(true, true);

        // 1) 同游标漏录 fee（emitted_ns=179 <= 1202）必须拒绝。
        let only_fill = base_image(
            json!([rec_fill, rec_beta]),
            json!([]),
            json!([
                covered_entry(&rec_fill),
                covered_entry(&rec_fee),
                covered_entry(&rec_beta)
            ]),
        );
        let err = gapped
            .check_new_risk(&cfg, &only_fill, &rel_alpha, "1202")
            .unwrap_err();
        assert!(err.contains("未补录"), "{err}");

        // 2) alpha 受影响范围仍 Pending：阻断 alpha 放行。
        let alpha_pending = base_image(
            json!([rec_fill, rec_fee, rec_beta]),
            json!([pending_entry(&rec_fee, "B:alpha")]),
            json!([
                covered_entry(&rec_fill),
                covered_entry(&rec_fee),
                covered_entry(&rec_beta)
            ]),
        );
        let err = gapped
            .check_new_risk(&cfg, &alpha_pending, &rel_alpha, "1202")
            .unwrap_err();
        assert!(err.contains("Pending"), "{err}");

        // 3) 未知范围（account:*）Pending 必须保守全域阻断 alpha。
        let unknown_scope = base_image(
            json!([rec_fill, rec_fee, rec_beta]),
            json!([pending_entry(&rec_beta, "account:*")]),
            json!([
                covered_entry(&rec_fill),
                covered_entry(&rec_fee),
                covered_entry(&rec_beta)
            ]),
        );
        let err = gapped
            .check_new_risk(&cfg, &unknown_scope, &rel_alpha, "1202")
            .unwrap_err();
        assert!(err.contains("账户范围"), "{err}");

        // 4) 无关重 B:beta 未被持久责任界覆盖：共享约束未定，阻断 alpha。
        let uncovered_beta = base_image(
            json!([rec_fill, rec_fee, rec_beta]),
            json!([pending_entry(&rec_beta, "B:beta")]),
            json!([covered_entry(&rec_fill), covered_entry(&rec_fee)]),
        );
        let err = gapped
            .check_new_risk(&cfg, &uncovered_beta, &rel_alpha, "1202")
            .unwrap_err();
        assert!(err.contains("责任界"), "{err}");

        // 5) 已知范围 B:beta 且已由 E 持久责任界充分覆盖：不使无关 B:alpha 永久停摆，且未来 2000 不挡 1202！
        let covered_beta_only = base_image(
            json!([rec_fill, rec_fee, rec_beta]),
            json!([pending_entry(&rec_beta, "B:beta")]),
            json!([
                covered_entry(&rec_fill),
                covered_entry(&rec_fee),
                covered_entry(&rec_beta)
            ]),
        );
        gapped
            .check_new_risk(&cfg, &covered_beta_only, &rel_alpha, "1202")
            .unwrap();

        // 6) 同一状态下释放 B:beta 自身仍被阻断（属于受影响范围 Pending）。
        let err = gapped
            .check_new_risk(&cfg, &covered_beta_only, &rel_beta, "1202")
            .unwrap_err();
        assert!(err.contains("Pending"), "{err}");

        // 7) 推进到 2000 后，future-1 已发出而未补录，必须拒绝。
        let err = gapped
            .check_new_risk(&cfg, &covered_beta_only, &rel_alpha, "2000")
            .unwrap_err();
        assert!(err.contains("未补录"), "{err}");

        // 8) 无 tape 缺口时仍拒绝新风险，且验证 verify_member 拒绝提前接纳。
        let no_tape_cfg = make_config(None);
        let err = gapped
            .check_new_risk(&no_tape_cfg, &covered_beta_only, &rel_alpha, "1202")
            .unwrap_err();
        assert!(err.contains("未核来源缺口"), "{err}");

        let early = make_record(&raw_future, "tok-future", "1999");
        let err = verify_member(&cfg, &early).unwrap_err();
        assert!(err.contains("尚未发出"), "{err}");
    }

    #[test]
    fn validate_config_and_empty_tape_boundaries() {
        let dir = TempDir::new("empty-tape");
        let empty_binding = write_tape(&dir.0, json!([]));
        let cfg = make_config(Some(empty_binding));
        let gapped = make_intake(true, true);
        let clean = json!({"recorded": [], "pending": [], "finance": {"responsibilities": []}});
        gapped
            .check_new_risk(&cfg, &clean, &release_record("B:alpha"), "100")
            .unwrap();

        // 相对路径、非 TestOnly、含 history_simulation_source 或坏 sha256 均在 Config 校验阶段拒绝。
        let mut bad_path = cfg.manifest.clone();
        bad_path[TAPE]["path"] = json!("relative/tape.json");
        assert!(validate_config(&bad_path).is_err());

        let mut bad_sha = cfg.manifest.clone();
        bad_sha[TAPE]["sha256"] = json!("not-a-sha256");
        assert!(validate_config(&bad_sha).is_err());

        let mut non_testonly = cfg.manifest.clone();
        non_testonly["clock"]["kind"] = json!("System");
        assert!(validate_config(&non_testonly).is_err());

        let mut sim = cfg.manifest.clone();
        sim["history_simulation_source"] = json!({});
        assert!(validate_config(&sim).is_err());
    }
}
