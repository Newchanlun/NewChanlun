use super::model::{advance, Batch, Model, State};
use crate::session_protocol::{canonical_json, sha256_hex};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub const RAW_FORMAT: &str = "history-sim-economic-originals/1";
const SCHEMA: &str = "CREATE TABLE IF NOT EXISTS x_sim_meta(k TEXT PRIMARY KEY,v TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS x_sim_batches(id TEXT PRIMARY KEY,request TEXT NOT NULL,result TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS x_sim_originals(id TEXT PRIMARY KEY,raw TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS x_sim_busts(id TEXT PRIMARY KEY,exec_id TEXT NOT NULL,quantity INTEGER NOT NULL) STRICT;";
fn storage(e: impl std::fmt::Display) -> String {
    format!("StorageUnavailable：{e}")
}
fn value<T: serde::Serialize>(v: &T) -> Value {
    serde_json::to_value(v).expect("typed finite integer model")
}
fn digest(v: &Value) -> String {
    sha256_hex(canonical_json(v).as_bytes())
}

/// #1375 R5：支持前沿顺序协议的模拟 X 单写者进程锁。
/// - 独占 `<canonical>.sim_writer.lock`：保证至多一个支持前沿顺序协议的模拟 X 写者运行。
/// - 共享 `<canonical>.writer.lock`：与不支持前沿顺序协议的旧 X / 非模拟 X（独占
///   `<canonical>.writer.lock`）天然互斥，同时允许缺口态 E 以只读 fd 持 `LOCK_SH(writer.lock)`
///   在不停车的前提下安全在线核清，且外部 `try_lock()` 探针仍可观测到 `writer.lock` 被持有。
/// - 持锁后在任何 DB 写入（含 `writer_epoch` 持久化）前就位 `<canonical>.frontier.lock`。
/// - 析构时显式 `unlock()`，避免子进程继承 fd 延迟放锁（同 `#1895/#2008`）。
#[derive(Debug)]
#[must_use = "模拟 X 写者锁须持续持有至进程退出"]
pub struct SimulationWriterLock {
    sim_writer: File,
    writer: File,
}
impl Drop for SimulationWriterLock {
    fn drop(&mut self) {
        let _ = self.writer.unlock();
        let _ = self.sim_writer.unlock();
    }
}

/// #1375 R5：模拟 X 前沿/epoch 写事务与 E 缺口放行提交之间的跨进程/跨连接顺序护栏。
/// - 模拟 X 仅在写入 `x_meta.writer_epoch`、`pending_batch` 与提交 `x_sim_batches`/`x_sim_originals`
///   的本地盘事务期间持 `<canonical>.frontier.lock` 独占锁，调用 S/E 期间不持此锁，
///   保持严格无环锁序（`e.db` -> `writer.lock` -> `frontier.lock` -> `x.db`）。
/// - E 在 `source_gap == true` 校验模拟 X 时以**严格只读**（`O_RDONLY`，永不新建 X 目录内文件）
///   先核准既有 `<canonical>.writer.lock`：
///   - 若 `<canonical>.frontier.lock` 存在：先非阻塞取 `LOCK_SH(writer.lock)`（若旧 X / 非模拟 X
///     正独占 `writer.lock` 则在写任何新收据前立即拒绝），再取 `LOCK_SH(frontier.lock)`；
///   - 若 `<canonical>.frontier.lock` 不存在（旧 X 创建且已停机）：非阻塞取 `LOCK_EX(writer.lock)`
///     （若旧 X 运行或新 X 启动则立即拒绝；取得后在整个 E 提交窗口内同时阻挡旧 X 与新 X 启动）。
/// - 调用者须持续持有 `FrontierGuard` 至 E `tx.commit()` 完成后释放；析构时先放 `frontier`
///   再放 `writer`，显式 `unlock()`（同 `#1895/#2008`）。
#[derive(Debug)]
#[must_use = "前沿顺序锁须持续持有至提交完成；`let _ = ...` 会立刻放锁"]
pub struct FrontierGuard {
    writer: Option<File>,
    frontier: Option<File>,
}
impl Drop for FrontierGuard {
    fn drop(&mut self) {
        if let Some(f) = &self.frontier {
            let _ = f.unlock();
        }
        if let Some(w) = &self.writer {
            let _ = w.unlock();
        }
    }
}

#[cfg(test)]
static FRONTIER_EXCLUSIVE_WOULD_BLOCK_COUNT: std::sync::atomic::AtomicUsize =
    std::sync::atomic::AtomicUsize::new(0);

#[cfg(test)]
pub(crate) fn frontier_exclusive_would_block_count() -> usize {
    FRONTIER_EXCLUSIVE_WOULD_BLOCK_COUNT.load(std::sync::atomic::Ordering::SeqCst)
}

fn canonical_db_path(db: &Path) -> Result<PathBuf, String> {
    if db.exists() {
        db.canonicalize().map_err(storage)
    } else {
        let parent = db
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or_else(|| Path::new("."));
        Ok(parent.canonicalize().map_err(storage)?.join(
            db.file_name()
                .ok_or("InvalidDomain：X 数据库路径缺文件名")?,
        ))
    }
}

fn sidecar_lock_path(db: &Path, suffix: &str) -> Result<PathBuf, String> {
    let canonical = canonical_db_path(db)?;
    Ok(PathBuf::from(format!("{}{suffix}", canonical.display())))
}

pub fn acquire_simulation_writer_lock(db: &Path) -> Result<SimulationWriterLock, String> {
    let sim_writer_path = sidecar_lock_path(db, ".sim_writer.lock")?;
    let writer_path = sidecar_lock_path(db, ".writer.lock")?;
    let frontier_path = sidecar_lock_path(db, ".frontier.lock")?;

    let sim_writer = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&sim_writer_path)
        .map_err(storage)?;
    sim_writer
        .try_lock()
        .map_err(|e| format!("StaleWriter：X模拟独占进程锁不可得：{e}"))?;

    let writer = match OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&writer_path)
    {
        Ok(f) => f,
        Err(e) => {
            let _ = sim_writer.unlock();
            return Err(storage(e));
        }
    };
    if let Err(e) = writer.try_lock_shared() {
        let _ = sim_writer.unlock();
        return Err(format!(
            "StaleWriter：X共享写者准入锁不可得（存在旧版或非模拟独占写者或缺口态E正独占锁库）：{e}"
        ));
    }

    if let Err(e) = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&frontier_path)
    {
        let _ = writer.unlock();
        let _ = sim_writer.unlock();
        return Err(storage(e));
    }

    Ok(SimulationWriterLock { sim_writer, writer })
}

pub(crate) fn ensure_frontier_lock(c: &Connection) -> Result<(), String> {
    let Some(path) = c.path().filter(|p| !p.is_empty()) else {
        return Ok(());
    };
    let lock_path = sidecar_lock_path(Path::new(path), ".frontier.lock")?;
    OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)
        .map_err(storage)?;
    Ok(())
}

pub fn lock_frontier_exclusive(c: &Connection) -> Result<Option<FrontierGuard>, String> {
    let Some(path) = c.path().filter(|p| !p.is_empty()) else {
        return Ok(None);
    };
    let lock_path = sidecar_lock_path(Path::new(path), ".frontier.lock")?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)
        .map_err(storage)?;
    let deadline = Instant::now() + Duration::from_secs(5);
    let mut logged_contention = false;
    loop {
        match file.try_lock() {
            Ok(()) => {
                return Ok(Some(FrontierGuard {
                    writer: None,
                    frontier: Some(file),
                }));
            }
            Err(std::fs::TryLockError::WouldBlock) => {
                #[cfg(test)]
                FRONTIER_EXCLUSIVE_WOULD_BLOCK_COUNT
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                if !logged_contention {
                    eprintln!(
                        "x_sim_frontier_lock_would_block path={}",
                        lock_path.display()
                    );
                    logged_contention = true;
                }
                if Instant::now() >= deadline {
                    return Err("StorageUnavailable：等待模拟 X 前沿独占顺序锁超时".into());
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            Err(std::fs::TryLockError::Error(e)) => return Err(storage(e)),
        }
    }
}

pub(crate) fn lock_frontier_shared(db: &Path) -> Result<FrontierGuard, String> {
    let canonical = db.canonicalize().map_err(storage)?;
    let writer_path = PathBuf::from(format!("{}.writer.lock", canonical.display()));
    let frontier_path = PathBuf::from(format!("{}.frontier.lock", canonical.display()));

    // E 对 X 业务库及其目录始终保持严格只读：绝不新建 writer.lock 或 frontier.lock。
    let writer = OpenOptions::new()
        .read(true)
        .open(&writer_path)
        .map_err(|e| {
            format!(
                "StorageUnavailable：模拟 X 缺既有单写者准入锁文件 {}：{e}",
                writer_path.display()
            )
        })?;

    match OpenOptions::new().read(true).open(&frontier_path) {
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            // 未就位 frontier.lock（例如旧版 X 创建该库）：仅当旧 X 已停机且可取得
            // writer.lock 独占锁时允许核清；整个 E 提交窗口内同时阻挡旧 X 与新 X 启动。
            match writer.try_lock() {
                Ok(()) => Ok(FrontierGuard {
                    writer: Some(writer),
                    frontier: None,
                }),
                Err(std::fs::TryLockError::WouldBlock) => Err(
                    "StorageUnavailable：模拟 X 写者锁被持有且缺少前沿顺序锁（旧版或非协作 X 正在运行），拒绝缺口态新风险放行"
                        .into(),
                ),
                Err(std::fs::TryLockError::Error(e)) => Err(storage(e)),
            }
        }
        Err(e) => Err(storage(e)),
        Ok(frontier) => {
            // 先非阻塞取 LOCK_SH(writer.lock)：若当前运行的是旧版 X / 非模拟独占写者，
            // 立即在写新收据前拒绝；取到后立即交给 FrontierGuard 托管，保证异常路径必释放。
            match writer.try_lock_shared() {
                Ok(()) => {}
                Err(std::fs::TryLockError::WouldBlock) => {
                    return Err(
                        "StorageUnavailable：模拟 X 正在运行不支持前沿顺序协议的独占写者（writer.lock 被独占持有），拒绝缺口态新风险放行"
                            .into(),
                    );
                }
                Err(std::fs::TryLockError::Error(e)) => return Err(storage(e)),
            }
            let mut guard = FrontierGuard {
                writer: Some(writer),
                frontier: None,
            };
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                match frontier.try_lock_shared() {
                    Ok(()) => {
                        guard.frontier = Some(frontier);
                        return Ok(guard);
                    }
                    Err(std::fs::TryLockError::WouldBlock) => {
                        if Instant::now() >= deadline {
                            return Err("StorageUnavailable：等待模拟 X 前沿共享顺序锁超时".into());
                        }
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(std::fs::TryLockError::Error(e)) => return Err(storage(e)),
                }
            }
        }
    }
}

/// 调用者持有 X 进程锁。模型、来源与状态在本库冻结，不接受换来源续跑。
pub fn initialize(
    c: &mut Connection,
    model: &Model,
    source_namespace: &str,
    source_epoch: &str,
) -> Result<(), String> {
    let tx = c.transaction().map_err(storage)?;
    initialize_in_transaction(&tx, model, source_namespace, source_epoch)?;
    tx.commit().map_err(storage)
}

pub(crate) fn initialize_in_transaction(
    c: &rusqlite::Transaction<'_>,
    model: &Model,
    source_namespace: &str,
    source_epoch: &str,
) -> Result<(), String> {
    model.validate()?;
    if source_namespace.is_empty() || source_epoch.is_empty() {
        return Err("InvalidDomain：X 来源身份为空".into());
    }
    ensure_frontier_lock(c)?;
    c.execute_batch(SCHEMA).map_err(storage)?;
    let frozen = canonical_json(
        &json!({"model":model,"source_namespace":source_namespace,"source_epoch":source_epoch}),
    );
    let old: Option<String> = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
            r.get(0)
        })
        .optional()
        .map_err(storage)?;
    match old {
        Some(old) if old != frozen => return Err("IdentityConflict：X 模型或事实来源已冻结".into()),
        Some(_) => (),
        None => {
            c.execute("INSERT INTO x_sim_meta VALUES('contract',?1)", [&frozen])
                .map_err(storage)?;
            c.execute(
                "INSERT INTO x_sim_meta VALUES('state',?1)",
                [canonical_json(&value(&State::default()))],
            )
            .map_err(storage)?;
        }
    }
    Ok(())
}

/// 当前状态必须与上一批原子发布的内容身份相符，不能删掉旧容量累计再重置。
pub(crate) fn audit_state(c: &Connection) -> Result<(), String> {
    let raw: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(storage)?;
    let state: State = serde_json::from_str(&raw).map_err(storage)?;
    if let Some(id) = &state.last_request_id {
        let prior: String = c
            .query_row("SELECT result FROM x_sim_batches WHERE id=?1", [id], |r| {
                r.get(0)
            })
            .map_err(storage)?;
        let prior: Value = serde_json::from_str(&prior).map_err(storage)?;
        if prior["state_content_hash"] != digest(&value(&state)) {
            return Err("IdentityConflict：持久状态与上一批容量/原件前沿不符".into());
        }
    } else {
        let count: i64 = c
            .query_row("SELECT count(*) FROM x_sim_batches", [], |r| r.get(0))
            .map_err(storage)?;
        if count != 0 || state != State::default() {
            return Err("IdentityConflict：初始状态丢失既有批前沿".into());
        }
    }
    Ok(())
}

/// 资格核验在调用前完成。事务原子发布整个 bar、执行进度及各独立原件。
pub(crate) fn replay_batch(c: &Connection, batch: &Batch) -> Result<Option<Value>, String> {
    let prior: Option<(String, String)> = c
        .query_row(
            "SELECT request,result FROM x_sim_batches WHERE id=?1",
            [&batch.request_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(storage)?;
    if let Some((original, result)) = prior {
        if original != canonical_json(&value(batch)) {
            return Err("IdentityConflict：重送改变批次内容".into());
        }
        return Ok(Some(serde_json::from_str(&result).map_err(storage)?));
    }
    Ok(None)
}
/// 冷启动核全部批、模型前沿和不可变原件；缺行绝不从其他表补造。
pub(crate) fn audit_history(c: &Connection) -> Result<(), String> {
    audit_state(c)?;
    let contract: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
            r.get(0)
        })
        .map_err(storage)?;
    let contract: Value = serde_json::from_str(&contract).map_err(storage)?;
    let mut q = c
        .prepare("SELECT id,request,result FROM x_sim_batches")
        .map_err(storage)?;
    let rows = q
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
            ))
        })
        .map_err(storage)?;
    let mut batches = Vec::new();
    for row in rows {
        let (id, request, response) = row.map_err(storage)?;
        let batch: Batch = serde_json::from_str(&request).map_err(storage)?;
        let response: Value = serde_json::from_str(&response).map_err(storage)?;
        if id != batch.request_id || request != canonical_json(&value(&batch)) {
            return Err("IdentityConflict：批请求身份/内容不符".into());
        }
        batches.push((batch, response));
    }
    batches.sort_by_key(|(b, _)| b.bar.index);
    let mut replay = State::default();
    let mut originals = std::collections::BTreeMap::new();
    let mut bust_totals = std::collections::BTreeMap::<String, i64>::new();
    let mut bust_ids = std::collections::BTreeSet::new();
    for (batch, response) in batches {
        let computed = compute_batch(&contract, &replay, &batch, &originals, &bust_totals)?;
        if response != computed.response {
            return Err("IdentityConflict：完整批原件/结果与历史纯计算不符".into());
        }
        for doc in computed.documents {
            let id = doc["event"]["source"]["external_fact_id"]
                .as_str()
                .ok_or("IdentityConflict：原件身份缺失")?
                .to_owned();
            let raw: String = c
                .query_row("SELECT raw FROM x_sim_originals WHERE id=?1", [&id], |r| {
                    r.get(0)
                })
                .map_err(storage)?;
            if raw != canonical_json(&doc) || originals.insert(id, doc).is_some() {
                return Err("IdentityConflict：独立原件缺失/重复或与历史纯计算不符".into());
            }
        }
        for (id, exec, quantity) in computed.busts {
            let stored: (String, i64) = c
                .query_row(
                    "SELECT exec_id,quantity FROM x_sim_busts WHERE id=?1",
                    [&id],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(storage)?;
            if stored != (exec.clone(), quantity) || !bust_ids.insert(id) {
                return Err("IdentityConflict：bust累计与历史纯计算不符".into());
            }
            let prior = bust_totals.entry(exec).or_default();
            *prior = prior
                .checked_add(quantity)
                .ok_or("InvalidDomain：bust累计溢出")?;
        }
        replay = computed.next_state;
    }
    let raw: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(storage)?;
    let actual: State = serde_json::from_str(&raw).map_err(storage)?;
    let original_count: i64 = c
        .query_row("SELECT count(*) FROM x_sim_originals", [], |r| r.get(0))
        .map_err(storage)?;
    let bust_count: i64 = c
        .query_row("SELECT count(*) FROM x_sim_busts", [], |r| r.get(0))
        .map_err(storage)?;
    if actual != replay
        || original_count != originals.len() as i64
        || bust_count != bust_ids.len() as i64
    {
        return Err("IdentityConflict：状态/原件存在缺失或游离前沿".into());
    }
    Ok(())
}

pub(crate) fn pending_batch(c: &Connection) -> Result<Option<String>, String> {
    c.query_row(
        "SELECT v FROM x_sim_meta WHERE k='pending_batch'",
        [],
        |r| r.get(0),
    )
    .optional()
    .map_err(storage)
}

struct PreparedBatch {
    documents: Vec<Value>,
    busts: Vec<(String, String, i64)>,
    next_state: State,
    response: Value,
}

/// 调用前与事务提交共用完整只读计算，不消费 S 资格或 X 调用占有。
fn prepare_batch(c: &Connection, batch: &Batch) -> Result<PreparedBatch, String> {
    let contract: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
            r.get(0)
        })
        .map_err(storage)?;
    let contract: Value = serde_json::from_str(&contract).map_err(storage)?;
    let state: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(storage)?;
    let state: State = serde_json::from_str(&state).map_err(storage)?;
    audit_state(c)?;
    let mut originals = std::collections::BTreeMap::new();
    let mut bust_totals = std::collections::BTreeMap::new();
    for bust in &batch.scenario_busts {
        let raw: String = c
            .query_row(
                "SELECT raw FROM x_sim_originals WHERE id=?1",
                [&bust.exec_id],
                |r| r.get(0),
            )
            .map_err(storage)?;
        originals.insert(
            bust.exec_id.clone(),
            serde_json::from_str(&raw).map_err(storage)?,
        );
        let quantity: i64 = c
            .query_row(
                "SELECT COALESCE(SUM(quantity),0) FROM x_sim_busts WHERE exec_id=?1",
                [&bust.exec_id],
                |r| r.get(0),
            )
            .map_err(storage)?;
        bust_totals.insert(bust.exec_id.clone(), quantity);
    }
    compute_batch(&contract, &state, batch, &originals, &bust_totals)
}

/// 生产提交和冷审唯一的完整原件纯计算；history只包含严格早于本批的原件和bust累计。
fn compute_batch(
    contract: &Value,
    state: &State,
    batch: &Batch,
    originals: &std::collections::BTreeMap<String, Value>,
    bust_totals: &std::collections::BTreeMap<String, i64>,
) -> Result<PreparedBatch, String> {
    let model: Model = serde_json::from_value(contract["model"].clone()).map_err(storage)?;
    let result = advance(&model, &state, batch)?;
    let mut documents = Vec::new();
    let model_hash = digest(&contract["model"]);
    for fill in &result.fills {
        let exec_id = fill.exec_id.clone();
        let source = json!({"source_namespace":contract["source_namespace"],"source_epoch":contract["source_epoch"],"external_fact_id":exec_id,"source_cursor":batch.bar.index.to_string(),"received_time":batch.bar.index.to_string(),"source_event_time":batch.bar.index.to_string(),"claimed_origin":"X simulation"});
        let body = json!({"format":RAW_FORMAT,"model":contract["model"],"model_content_hash":model_hash,"known_frontier_cut":batch.known_frontier_cut,"bar":batch.bar,"capacity":batch.capacity,"intra_batch_order":"Unknown","capacity_evidence":result.capacity_evidence.iter().find(|e|e["capacity_epoch"].as_str()==fill.capacity_epoch.as_deref()),"event":{"kind":"fill","source":source,"fill":fill}});
        documents.push(body);
        let mut fee_source = source;
        fee_source["external_fact_id"] = json!(format!("fee:{exec_id}"));
        documents.push(json!({"format":RAW_FORMAT,"model":contract["model"],"model_content_hash":model_hash,"known_frontier_cut":batch.known_frontier_cut,"bar":batch.bar,"capacity":batch.capacity,"intra_batch_order":"Unknown","event":{"kind":"fee","source":fee_source,"cause":{"kind":"fill","exec_id":exec_id},"chong_id":fill.chong_id,"family_id":fill.family_id,"command_id":fill.command_id,"projection_manifest":fill.projection_manifest,"capacity_epoch":fill.capacity_epoch,"amount":fill.fee,"fee_profile":model.fee_profile.reference}}));
    }
    let mut busts = Vec::new();
    let mut busted_execs = std::collections::BTreeSet::new();
    for bust in &batch.scenario_busts {
        if !busted_execs.insert(&bust.exec_id) {
            return Err("IdentityConflict：同批重复bust原成交".into());
        }
        if !matches!(&batch.capacity, super::model::Capacity::Scenario { reference, .. } if reference == &bust.scenario_ref)
            || bust.quantity <= 0
        {
            return Err("Unsupported：bust 须具名 scenario 合同且数量为正".into());
        }
        let original = originals
            .get(&bust.exec_id)
            .ok_or("IdentityConflict：bust缺截至本批的原成交")?;
        if original["event"]["kind"] != "fill" {
            return Err("IdentityConflict：bust 前件不是 fill".into());
        }
        let fill: super::model::Fill =
            serde_json::from_value(original["event"]["fill"].clone()).map_err(storage)?;
        let prior = bust_totals.get(&bust.exec_id).copied().unwrap_or(0);
        if prior
            .checked_add(bust.quantity)
            .is_none_or(|q| q > fill.quantity)
        {
            return Err("IdentityConflict：bust 超出原成交累计量".into());
        }
        let id = digest(&json!(["bust", batch.request_id, bust.exec_id]));
        let source = json!({"source_namespace":contract["source_namespace"],"source_epoch":contract["source_epoch"],"external_fact_id":id,"source_cursor":batch.bar.index.to_string(),"received_time":batch.bar.index.to_string(),"source_event_time":batch.bar.index.to_string(),"claimed_origin":"X simulation"});
        documents.push(json!({"format":RAW_FORMAT,"model":contract["model"],"model_content_hash":model_hash,"known_frontier_cut":batch.known_frontier_cut,"bar":batch.bar,"capacity":batch.capacity,"intra_batch_order":"Unknown","event":{"kind":"bust","source":source,"cause":{"kind":"fill","exec_id":bust.exec_id},"chong_id":fill.chong_id,"family_id":fill.family_id,"command_id":fill.command_id,"projection_manifest":fill.projection_manifest,"capacity_epoch":fill.capacity_epoch,"original_capacity_evidence":original["capacity_evidence"],"quantity":bust.quantity,"scenario_ref":bust.scenario_ref}}));
        busts.push((id, bust.exec_id.clone(), bust.quantity));
    }
    let response = json!({"kind":"SimulationBatch","request_id":batch.request_id,"model_content_hash":model_hash,"bar_index":batch.bar.index,"l0_fill_count":result.l0_fill_count,"intra_batch_order":result.intra_batch_order,"originals":documents,"unfilled_market":result.unfilled_market,"capacity_transitions":result.capacity_transitions,"capacity_evidence":result.capacity_evidence,"state_content_hash":digest(&value(&result.next_state))});
    Ok(PreparedBatch {
        documents,
        busts,
        next_state: result.next_state,
        response,
    })
}

pub(crate) fn validate_batch(c: &Connection, batch: &Batch) -> Result<(), String> {
    prepare_batch(c, batch).map(|_| ())
}

#[cfg(test)]
pub(crate) fn commit_batch(c: &mut Connection, batch: &Batch) -> Result<Value, String> {
    commit_batch_with_commands(c, batch, &[])
}
pub(crate) fn commit_batch_with_commands(
    c: &mut Connection,
    batch: &Batch,
    command_ids: &[String],
) -> Result<Value, String> {
    let mut normalized = batch.clone();
    normalized.normalize();
    let batch = &normalized;
    let _frontier_lock = lock_frontier_exclusive(c)?;
    let tx = c.transaction().map_err(storage)?;
    let request = canonical_json(&value(batch));
    let prior: Option<(String, String)> = tx
        .query_row(
            "SELECT request,result FROM x_sim_batches WHERE id=?1",
            [&batch.request_id],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .map_err(storage)?;
    if let Some((original, result)) = prior {
        if original != request {
            return Err("IdentityConflict：重送改变批次内容".into());
        }
        return serde_json::from_str(&result).map_err(storage);
    }
    let PreparedBatch {
        documents,
        busts,
        next_state,
        response,
    } = prepare_batch(&tx, batch)?;
    for (id, exec_id, quantity) in busts {
        tx.execute(
            "INSERT INTO x_sim_busts VALUES(?1,?2,?3)",
            params![id, exec_id, quantity],
        )
        .map_err(storage)?;
    }
    for doc in &documents {
        let id = doc["event"]["source"]["external_fact_id"].as_str().unwrap();
        tx.execute(
            "INSERT INTO x_sim_originals(id,raw) VALUES(?1,?2)",
            params![id, canonical_json(doc)],
        )
        .map_err(storage)?;
    }
    tx.execute(
        "UPDATE x_sim_meta SET v=?1 WHERE k='state'",
        [canonical_json(&value(&next_state))],
    )
    .map_err(storage)?;
    tx.execute(
        "INSERT INTO x_sim_batches VALUES(?1,?2,?3)",
        params![batch.request_id, request, canonical_json(&response)],
    )
    .map_err(storage)?;
    for id in command_ids {
        let changed = tx.execute("UPDATE x_exact_commands SET state='Observed' WHERE id=?1 AND state='MayHaveCalled' AND attempt_batch=?2", params![id,request]).map_err(storage)?;
        if changed != 1 {
            return Err("IdentityConflict：X 调用占有不属于本批次".into());
        }
    }
    tx.execute(
        "DELETE FROM x_sim_meta WHERE k IN ('pending_batch','pending_epoch')",
        [],
    )
    .map_err(storage)?;
    #[cfg(test)]
    if batch.request_id == "b1" && std::env::var_os("ISSUE1381_TEST_CRASH_BEFORE_COMMIT").is_some()
    {
        std::process::exit(42);
    }
    tx.commit().map_err(storage)?;
    Ok(response)
}

pub fn read_original(c: &Connection, id: &str) -> Result<Value, String> {
    let raw: String = c
        .query_row("SELECT raw FROM x_sim_originals WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .map_err(storage)?;
    serde_json::from_str(&raw).map_err(storage)
}

pub(crate) fn read_batch(c: &Connection, id: &str) -> Result<Value, String> {
    let raw: String = c
        .query_row("SELECT result FROM x_sim_batches WHERE id=?1", [id], |r| {
            r.get(0)
        })
        .map_err(storage)?;
    serde_json::from_str(&raw).map_err(storage)
}
