//! #1769（ADR 0039 迁移步骤 1）：X 执行域可运行骨架。
//!
//! X 与 S/E/B 同型：自有 SQLite 库、`<db>.writer.lock` 独占进程锁、持久化 `writer_epoch`。
//! 本骨架只持久化执行 profile 版本与 TB-09 指纹字段、发送面状态，并提供只读查询；
//! **不含任何场所写代码**：一切写调用（`submit`/`cancel`）返回 `UnsupportedCapability`，
//! 不返回假成功。experiment/production profile 缺凭据时，在构造任何传输之前以
//! `MissingDependency` 非 0 退出；production profile 缺 TB-09 指纹时持久化拒绝发送状态。
//!
//! 用法：
//!   x_execution_session serve --db FILE --profile FILE --writer-epoch N
//!   x_execution_session query --db FILE
//!   x_execution_session query-history --db FILE
//!   x_execution_session query-command --db FILE --command-id ID
//!   x_execution_session query-batch --db FILE --batch-id ID
//!   x_execution_session query-original --db FILE --original-id ID
//!   x_execution_session submit|cancel --db FILE      （恒 UnsupportedCapability）
use newchan_rust::history_simulation::{
    runtime, EXACT_PROFILE_REVISION, FX_RELEASE_PROFILE_REVISION,
};
use newchan_rust::session_protocol::{canonical_json, positive, strict_json};
use newchan_rust::session_transport::process_lock;
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::Path;
use std::time::Duration;

const PROFILE_REVISION: &str = "x-execution-profile/1";
const MODES: [&str; 4] = ["simulation", "dry-run", "experiment", "production"];
const SCHEMA: &str =
    "CREATE TABLE IF NOT EXISTS x_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);";

/// 历史模拟采用静态 /3 或显式 FX/2 的 /4，其他执行 profile 保留 /1。凭据只经 `credential_scope.env` 指明的环境变量
/// 进入本进程；值永不落库、不打印。
struct Profile {
    revision: String,
    mode: String,
    endpoint: Option<String>,
    credential_env: String,
    tb09_fingerprint: Option<String>,
    history_simulation: Option<runtime::Profile>,
}

impl Profile {
    fn load(path: &Path) -> Result<Self, String> {
        let raw =
            std::fs::read(path).map_err(|e| format!("InvalidDomain：读执行 profile 失败：{e}"))?;
        let v = strict_json(&raw)
            .map_err(|e| format!("InvalidDomain：执行 profile JSON 解析失败：{e}"))?;
        let revision = v["profile_revision"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        if v["history_simulation"].is_null() && revision != PROFILE_REVISION {
            return Err(format!(
                "VersionUnsupported：执行 profile 版本 `{revision}` 不是 {PROFILE_REVISION}"
            ));
        }
        if !v["history_simulation"].is_null()
            && !matches!(
                revision.as_str(),
                EXACT_PROFILE_REVISION | FX_RELEASE_PROFILE_REVISION
            )
        {
            return Err(format!(
                "VersionUnsupported：历史模拟 X profile `{revision}` 不支持续写；须用 {EXACT_PROFILE_REVISION} 或 {FX_RELEASE_PROFILE_REVISION}"
            ));
        }
        let mode = v["mode"]
            .as_str()
            .filter(|m| MODES.contains(m))
            .ok_or(
                "InvalidDomain：执行 profile mode 必须是 simulation|dry-run|experiment|production",
            )?
            .to_string();
        let credential_env = v["credential_scope"]["env"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or("InvalidDomain：执行 profile 缺 credential_scope.env")?
            .to_string();
        let opt = |key: &str| -> Result<Option<String>, String> {
            match &v[key] {
                Value::Null => Ok(None),
                Value::String(s) if !s.is_empty() => Ok(Some(s.clone())),
                _ => Err(format!(
                    "InvalidDomain：执行 profile {key} 必须是非空字符串或 null"
                )),
            }
        };
        let history_simulation = match v.get("history_simulation") {
            None | Some(Value::Null) => None,
            Some(value) => {
                if mode != "simulation" {
                    return Err(
                        "InvalidDomain：history_simulation 仅允许 simulation profile".into(),
                    );
                }
                Some(runtime::Profile::from_declared_revision(
                    &revision,
                    value.clone(),
                )?)
            }
        };
        Ok(Self {
            history_simulation,
            revision,
            mode,
            endpoint: opt("endpoint")?,
            credential_env,
            tb09_fingerprint: opt("tb09_fingerprint")?,
        })
    }

    fn needs_credential(&self) -> bool {
        matches!(self.mode.as_str(), "experiment" | "production")
    }
}

fn err(e: impl std::fmt::Display) -> String {
    format!("StorageUnavailable：{e}")
}

fn meta_get(conn: &Connection, key: &str) -> Result<Option<String>, String> {
    conn.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
        .optional()
        .map_err(err)
}

/// #1407 C3 R3：在持写锁与可读写 WAL 打开之前，以只读连接（可看见 live WAL、不触发 checkpoint、
/// 不改写 `.db` 或 `-wal` 字节）预检既有 X 库版本/域兼容性，防止错误续开旧 `/1`、`/2` 历史模拟库时
/// 悄然合入或删除未 checkpoint 的 WAL。
fn preflight_existing_db(db: &Path, profile: &Profile, epoch: i64) -> Result<(), String> {
    if !db.exists() {
        return Ok(());
    }
    let conn = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(err)?;
    conn.busy_timeout(Duration::from_secs(2)).map_err(err)?;
    let has_meta: bool = conn
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='x_meta')",
            [],
            |r| r.get(0),
        )
        .map_err(err)?;
    if !has_meta {
        return Ok(());
    }
    let simulation = profile.history_simulation.is_some();
    let old_simulation = meta_get(&conn, "history_simulation")?;
    let old_mode = meta_get(&conn, "profile_mode")?;
    if old_mode.is_some() && (old_simulation.as_deref() == Some("true")) != simulation {
        return Err("IdentityConflict：模拟原件执行域不可与其他 profile 共用 X 库".into());
    }
    if old_simulation.as_deref() == Some("true")
        && meta_get(&conn, "profile_revision")?.as_deref() != Some(profile.revision.as_str())
    {
        return Err("VersionUnsupported：历史模拟库版本不兼容，升级须从空库重放".into());
    }
    if let Some(stored) = meta_get(&conn, "writer_epoch")? {
        let stored: i64 = stored.parse().map_err(err)?;
        if epoch < stored {
            return Err(format!(
                "StaleWriter：X writer_epoch={epoch} 低于已持久化的 {stored}"
            ));
        }
    }
    Ok(())
}

/// 持锁后建库/续库：epoch 只增不减（低 epoch 为陈旧写者），profile 版本、模式、指纹与
/// 发送面状态在同一事务落盘。
fn persist(conn: &mut Connection, profile: &Profile, epoch: i64) -> Result<Value, String> {
    let tx = conn.transaction().map_err(err)?;
    tx.execute_batch(SCHEMA).map_err(err)?;
    let simulation = profile.history_simulation.is_some();
    let old_simulation = meta_get(&tx, "history_simulation")?;
    let old_mode = meta_get(&tx, "profile_mode")?;
    if old_mode.is_some() && (old_simulation.as_deref() == Some("true")) != simulation {
        return Err("IdentityConflict：模拟原件执行域不可与其他 profile 共用 X 库".into());
    }
    if old_simulation.as_deref() == Some("true")
        && meta_get(&tx, "profile_revision")?.as_deref() != Some(profile.revision.as_str())
    {
        return Err("VersionUnsupported：历史模拟库版本不兼容，升级须从空库重放".into());
    }
    if let Some(stored) = meta_get(&tx, "writer_epoch")? {
        let stored: i64 = stored.parse().map_err(err)?;
        if epoch < stored {
            return Err(format!(
                "StaleWriter：X writer_epoch={epoch} 低于已持久化的 {stored}"
            ));
        }
    }
    if let Some(simulation) = &profile.history_simulation {
        runtime::initialize_in_transaction(&tx, simulation, epoch)?;
    }
    let (send_state, reason) = if profile.mode == "production" && profile.tb09_fingerprint.is_none()
    {
        ("refused", "MissingTb09Fingerprint")
    } else {
        ("unsupported", "UnsupportedCapability")
    };
    let rows = [
        ("writer_epoch", epoch.to_string()),
        ("history_simulation", simulation.to_string()),
        ("profile_revision", profile.revision.clone()),
        ("profile_mode", profile.mode.clone()),
        (
            "tb09_fingerprint",
            profile.tb09_fingerprint.clone().unwrap_or_default(),
        ),
        ("send_state", send_state.to_string()),
        ("send_refusal_reason", reason.to_string()),
    ];
    for (key, value) in rows {
        tx.execute(
            "INSERT INTO x_meta(key,value) VALUES(?1,?2) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [key, value.as_str()],
        )
        .map_err(err)?;
    }
    tx.commit().map_err(err)?;
    query_conn(conn)
}

fn query_conn(conn: &Connection) -> Result<Value, String> {
    let mut stmt = conn
        .prepare("SELECT key,value FROM x_meta ORDER BY key")
        .map_err(err)?;
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
        .map_err(err)?
        .collect::<Result<BTreeMap<_, _>, _>>()
        .map_err(err)?;
    Ok(json!(rows))
}

fn args() -> Result<(String, BTreeMap<String, String>), String> {
    let mut it = std::env::args().skip(1);
    let command = it
        .next()
        .ok_or("usage: serve|query|query-history|query-command|query-batch|query-original|submit|cancel --db FILE ...")?;
    let mut opts = BTreeMap::new();
    while let Some(k) = it.next() {
        if ![
            "--db",
            "--profile",
            "--writer-epoch",
            "--command-id",
            "--batch-id",
            "--original-id",
        ]
        .contains(&k.as_str())
            || opts.contains_key(&k)
        {
            return Err(format!("InvalidDomain：未知/重复参数 {k}"));
        }
        opts.insert(k, it.next().ok_or("InvalidDomain：参数缺值")?);
    }
    Ok((command, opts))
}

fn check_allowed(opts: &BTreeMap<String, String>, allowed: &[&str]) -> Result<(), String> {
    for k in opts.keys() {
        if !allowed.contains(&k.as_str()) {
            return Err(format!("InvalidDomain：本子命令不接受参数 {k}"));
        }
    }
    Ok(())
}

fn run() -> Result<(), String> {
    let (command, opts) = args()?;
    let get = |k: &str| {
        opts.get(k)
            .map(String::as_str)
            .ok_or_else(|| format!("InvalidDomain：缺{k}"))
    };
    let db = Path::new(get("--db")?);
    match command.as_str() {
        "serve" => {
            check_allowed(&opts, &["--db", "--profile", "--writer-epoch"])?;
            let profile = Profile::load(Path::new(get("--profile")?))?;
            let epoch = positive(get("--writer-epoch")?, "writer_epoch")?;
            preflight_existing_db(db, &profile, epoch)?;
            let _lock = process_lock(db, "X")?;
            let (mut conn, storage) = newchan_rust::economic_session::open_durable_db(db)?;
            eprintln!("x_execution_session storage {storage}");
            let state = persist(&mut conn, &profile, epoch)?;
            if let Some(simulation) = &profile.history_simulation {
                return runtime::serve(&mut conn, simulation, epoch);
            }
            drop(conn);
            // 凭据门在任何传输构造之前：缺即 MissingDependency 非 0 退出，端点从未被连接。
            if profile.needs_credential()
                && std::env::var_os(&profile.credential_env).is_none_or(|v| v.is_empty())
            {
                return Err(format!(
                    "MissingDependency：{} profile 缺凭据（credential_scope.env={}）；发送面未启动",
                    profile.mode, profile.credential_env
                ));
            }
            // 骨架：场所传输待后续叶落地（ADR 0039 迁移步骤 2+）；此处不连接 endpoint。
            let _ = &profile.endpoint;
            eprintln!(
                "x_execution_session serving（发送面 {}）",
                state["send_state"].as_str().unwrap_or_default()
            );
            println!("{state}");
            loop {
                std::thread::sleep(Duration::from_millis(200));
            }
        }
        "query" => {
            check_allowed(&opts, &["--db"])?;
            let conn =
                Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(err)?;
            conn.busy_timeout(Duration::from_secs(2)).map_err(err)?;
            println!("{}", query_conn(&conn)?);
            Ok(())
        }
        "query-history" => {
            check_allowed(&opts, &["--db"])?;
            let out = newchan_rust::history_simulation::runtime::inspect_history(db)?;
            println!("{}", canonical_json(&out));
            Ok(())
        }
        "query-command" => {
            check_allowed(&opts, &["--db", "--command-id"])?;
            let out = newchan_rust::history_simulation::runtime::inspect_command(
                db,
                get("--command-id")?,
            )?;
            println!("{}", canonical_json(&out));
            Ok(())
        }
        "query-batch" => {
            check_allowed(&opts, &["--db", "--batch-id"])?;
            let out =
                newchan_rust::history_simulation::runtime::inspect_batch(db, get("--batch-id")?)?;
            println!("{}", canonical_json(&out));
            Ok(())
        }
        "query-original" => {
            check_allowed(&opts, &["--db", "--original-id"])?;
            let out = newchan_rust::history_simulation::runtime::inspect_original(
                db,
                get("--original-id")?,
            )?;
            println!("{}", canonical_json(&out));
            Ok(())
        }
        "submit" | "cancel" => Err(format!(
            "UnsupportedCapability：X `{command}` 写调用在场所适配叶落地前不可用"
        )),
        other => Err(format!("InvalidDomain：未知子命令 {other}")),
    }
}

fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(2);
    }
}
