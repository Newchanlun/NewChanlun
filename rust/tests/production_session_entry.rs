//! #1769（ADR 0039 迁移步骤 1，C-L 验收第 3 项）：唯一生产 launcher 与 X 骨架的入口测试。
//!
//! 只在 Linux（nc-remote、CI ubuntu）运行：读 `/proc/<pid>/{environ,stat}`。凭据只用非敏感
//! 哨兵；不连接任何真实场所（端点指向测试内本地监听器）。S 的 admission 锚用与
//! `s_session/tests/issue1527_recovery/test_support.rs` 同口径的 TestOnly 造锚（生产签发归 #1657）。
//!
//! 两种构建都跑本文件，原八项在两种构建下都只走 S 正式配置路径（已签 synthetic profile，#1774）；
//! 纯 `production_session`（生产构建）另真实执行生产 launcher 与生产 S 遇 TestOnly 开关即拒的接线。
#![cfg(target_os = "linux")]
#![cfg_attr(
    not(feature = "production_session_testonly"),
    allow(dead_code, unused_imports)
)]

use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, ErrorKind, Read, Write};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Output, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

const SESSION: &str = "s-session-testonly-001";
const DECLARED_NS: &str = "testonly.ohlc";
/// 能力 manifest 中的 HL 场所 namespace（执行行情；不得进 S）。
const HL_NS: &str = "hl.perp.BTC";
const CREDENTIAL_KEY: &str = "NC_X_VENUE_CREDENTIAL_SENTINEL";
const CREDENTIAL_VALUE: &str = "sentinel-not-a-secret";
/// v3 serve 只接受此完整固定 OHLC profile（`writer_cli::checked_profile_bytes`）。
const TB02A_PROFILE: &str = "profiles/ohlc_integer_tb02a_v1.json";

fn s_bin() -> &'static str {
    env!("CARGO_BIN_EXE_s_structure_session")
}
fn x_bin() -> &'static str {
    env!("CARGO_BIN_EXE_x_execution_session")
}
fn launcher_bin() -> &'static str {
    env!("CARGO_BIN_EXE_production_session")
}
fn fixture(rel: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("s_session")
        .join(rel)
}
fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn write_json(path: &Path, value: &Value) -> PathBuf {
    std::fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
    path.to_path_buf()
}

struct Space(tempfile::TempDir);
impl Space {
    fn new() -> Self {
        Self(
            tempfile::Builder::new()
                .prefix("pse")
                .tempdir_in("/tmp")
                .unwrap(),
        )
    }
    fn path(&self, name: &str) -> PathBuf {
        self.0.path().canonicalize().unwrap().join(name)
    }
    /// S 库独占子目录：S admission 固定并核对库所在目录本身的身份（含 mtime），与 E/B/X 同目录时
    /// 它们并发建文件会使 S 以 SourceIdentityChanged 拒启。
    fn s_db(&self) -> PathBuf {
        let dir = self.path("s");
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("s.db")
    }
}

fn declaration(category: &str, ns: &str) -> Value {
    json!({"category": category, "namespaces": [ns]})
}

fn clock_plan(space: &Space) -> PathBuf {
    write_json(
        &space.path("clock.json"),
        &json!({"schema_revision":"s-clock-plan/1","clock_plan_id":"pse-01","origin_utc":"2000-01-01T00:00:00Z","unit":"ns",
            "events":{"input-1":{"accept_ns":"10","attempts":[{"begin_ns":"11","commit_ns":"12"}]},
                "input-2":{"accept_ns":"20","attempts":[{"begin_ns":"21","commit_ns":"22"}]}}}),
    )
}

fn run(cmd: &mut Command) -> Output {
    cmd.stdin(Stdio::null()).output().unwrap()
}

struct BoundedByteReader {
    state: Arc<(Mutex<(Vec<u8>, bool)>, Condvar)>,
    reader: Option<std::thread::JoinHandle<()>>,
}

impl BoundedByteReader {
    fn attach<R: Read + Send + 'static>(mut pipe: R) -> Self {
        let state = Arc::new((Mutex::new((Vec::new(), false)), Condvar::new()));
        let shared = Arc::clone(&state);
        let reader = std::thread::spawn(move || {
            let mut buf = Vec::new();
            let _ = pipe.read_to_end(&mut buf);
            let (lock, cv) = &*shared;
            let mut guard = lock.lock().unwrap_or_else(|e| e.into_inner());
            guard.0 = buf;
            guard.1 = true;
            cv.notify_all();
        });
        Self {
            state,
            reader: Some(reader),
        }
    }

    fn finish_bounded(&mut self, timeout: Duration) -> (Vec<u8>, bool) {
        let deadline = Instant::now() + timeout;
        let (lock, cv) = &*self.state;
        let mut guard = lock.lock().unwrap_or_else(|e| e.into_inner());
        while !guard.1 {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            guard = cv
                .wait_timeout(guard, remaining)
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
        let eof = guard.1;
        let bytes = std::mem::take(&mut guard.0);
        drop(guard);
        if eof {
            if let Some(handle) = self.reader.take() {
                let _ = handle.join();
            }
        }
        (bytes, eof)
    }
}

/// 隔离进程组内执行一次性命令（init 探针 / 拒启门）：对进程退出、后代兜底清理及 stdout/stderr 读者收尾均设上限。
fn run_command_bounded(cmd: &mut Command, timeout: Duration, what: &str) -> Output {
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0)
        .spawn()
        .unwrap();
    let pgid = child.id();
    let mut out_reader = BoundedByteReader::attach(child.stdout.take().unwrap());
    let mut err_reader = BoundedByteReader::attach(child.stderr.take().unwrap());
    let started = Instant::now();
    let deadline = started + timeout;
    let mut exit_status: Option<ExitStatus> = None;
    loop {
        if let Some(status) = child.try_wait().unwrap() {
            exit_status = Some(status);
            break;
        }
        if Instant::now() >= deadline {
            let (_, _, remaining) =
                terminate_owned_group(&mut child, pgid, &mut exit_status, Duration::from_secs(2));
            let (_, _) = out_reader.finish_bounded(Duration::from_secs(5));
            let (stderr, err_eof) = err_reader.finish_bounded(Duration::from_secs(5));
            panic!(
                "{what}：进程超过上限 {timeout:?}（耗时 {:?}）未退出，已按本测试进程组 {pgid} 清理\
                 （残留 PID={remaining:?}，stderr_eof={err_eof}）：{}",
                started.elapsed(),
                String::from_utf8_lossy(&stderr)
            );
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let (_, _, remaining) =
        terminate_owned_group(&mut child, pgid, &mut exit_status, Duration::from_secs(2));
    let (stdout, out_eof) = out_reader.finish_bounded(Duration::from_secs(5));
    let (stderr, err_eof) = err_reader.finish_bounded(Duration::from_secs(5));
    assert!(
        remaining.is_empty(),
        "{what}：进程退出后本测试进程组 {pgid} 仍有残留 PID={remaining:?}：{}",
        String::from_utf8_lossy(&stderr)
    );
    assert!(
        out_eof && err_eof,
        "{what}：stdout/stderr 读者收尾超时（out_eof={out_eof}, err_eof={err_eof}）：{}",
        String::from_utf8_lossy(&stderr)
    );
    Output {
        status: exit_status.expect("child exited"),
        stdout,
        stderr,
    }
}

/// 期望「拒绝启动」的命令：限时等待退出。门失效时 S/launcher 会进入服务循环不退出，
/// 此处超时即按隔离进程组先停后杀并判红，不吃满 job 超时。
#[cfg_attr(feature = "production_session_testonly", allow(dead_code))]
fn run_refusal(cmd: &mut Command) -> Output {
    run_command_bounded(cmd, Duration::from_secs(60), "拒启门失效（应以拒绝退出）")
}

/// v3 init（可带结构源声明）。
fn s_init_v3(space: &Space, declared: Option<&Value>) -> PathBuf {
    let db = space.s_db();
    let mut c = Command::new(s_bin());
    c.args(["init", "--protocol-revision", "s-session/3", "--db"])
        .arg(&db)
        .args(["--session", SESSION, "--catalog"])
        .arg(fixture("catalog/signed-catalog.json"))
        .arg("--profile")
        .arg(fixture(TB02A_PROFILE))
        .args(["--session-generation", "1", "--clock-plan"])
        .arg(clock_plan(space))
        .args(["--delivery-retain-generations", "4"]);
    if let Some(d) = declared {
        c.arg("--structure-source")
            .arg(write_json(&space.path("source.json"), d));
    }
    let out = run_command_bounded(&mut c, Duration::from_secs(30), "S v3 init");
    assert!(
        out.status.success(),
        "S v3 init: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    db
}

/// TestOnly 造锚：owner 绑定 + state/s-admission/{limits,binding}.json；返回 limits 路径。
fn anchor(db: &Path) -> PathBuf {
    anchor_with_wire_limit(db, 1_073_741_824)
}

fn anchor_with_wire_limit(db: &Path, max_total_wire_bytes: u64) -> PathBuf {
    let db = db.canonicalize().unwrap();
    let state = db.parent().unwrap().join("s-state");
    let published = state.join("s-admission");
    std::fs::create_dir_all(&published).unwrap();
    std::fs::set_permissions(&published, std::fs::Permissions::from_mode(0o700)).unwrap();
    let limits = published.join("limits.json");
    let binding_path = published.join("binding.json");
    let raw = serde_json::to_vec(&json!({
        "max_total_wire_bytes":max_total_wire_bytes.to_string(), "max_total_node_bytes":"1073741824", "max_total_nodes":"10000000",
        "max_total_records":"10000000", "max_total_requests":"1000000", "max_elapsed_ms":"600000",
        "max_staged_bytes":"67108864", "max_store_bytes":"1073741824"
    }))
    .unwrap();
    for (p, bytes) in [(&limits, raw.as_slice()), (&binding_path, &b""[..])] {
        std::fs::write(p, bytes).unwrap();
        std::fs::set_permissions(p, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    let identity = |p: &Path| {
        let m = std::fs::metadata(p).unwrap();
        json!({"device":m.dev(),"inode":m.ino(),"uid":m.uid(),"mode":m.mode()&0o7777})
    };
    let binding = json!({"db":db,"path":limits,"sha256":sha256_hex(&raw),"file_identity":identity(&limits),
        "binding_identity":identity(&binding_path),"directory_identity":identity(&published)});
    std::fs::write(&binding_path, serde_json::to_vec(&binding).unwrap()).unwrap();
    let owner = PathBuf::from(format!("{}.control-owner.json", db.display()));
    std::fs::write(
        &owner,
        serde_json::to_vec(&json!({"db":db,"state_dir":state,"admission":binding})).unwrap(),
    )
    .unwrap();
    std::fs::set_permissions(&owner, std::fs::Permissions::from_mode(0o600)).unwrap();
    limits
}

fn raw_rows(db: &Path) -> i64 {
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    c.query_row("SELECT COUNT(*) FROM raw_events", [], |r| r.get(0))
        .unwrap()
}

/// S 未运行时读行数：`immutable=1` 不建 `-shm`（普通只读连接留下的 `-shm` 会让 S 写者
/// admission 拒绝启动）。S 运行中读最新提交用 [`raw_rows`]。
fn raw_rows_offline(db: &Path) -> i64 {
    let c = Connection::open_with_flags(
        format!("file:{}?mode=ro&immutable=1", db.display()),
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
    )
    .unwrap();
    c.query_row("SELECT COUNT(*) FROM raw_events", [], |r| r.get(0))
        .unwrap()
}

fn meta(db: &Path, sql: &str) -> Option<String> {
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()?;
    c.query_row(sql, [], |r| r.get(0)).ok()
}

fn x_profile(
    space: &Space,
    mode: &str,
    endpoint: Option<&str>,
    fingerprint: Option<&str>,
    credential: bool,
) -> PathBuf {
    let file = space.path("credential.txt");
    if credential {
        std::fs::write(&file, CREDENTIAL_VALUE).unwrap();
    }
    write_json(
        &space.path("x-profile.json"),
        &json!({"profile_revision":"x-execution-profile/1","mode":mode,"endpoint":endpoint,
            "tb09_fingerprint":fingerprint,"credential_scope":{"env":CREDENTIAL_KEY,"file":file}}),
    )
}

fn economic_manifest(space: &Space) -> PathBuf {
    write_json(
        &space.path("economic.json"),
        &json!({"schema_revision":"economic-manifest/1","session_id":"pse","session_generation":"1","book_revision":"tb03c-book/1",
            "e":{"db":space.path("e.db"),"socket":space.path("e.sock")},
            "chongs":[{"chong_id":"one","symbol":"TEST","operation_level":"1","fixed_q":"10","db":space.path("b.db"),"socket":space.path("b.sock")}],
            "authorized_sources":[{"source_namespace":"pse-test","source_epoch":"1","producer_id":"reader","producer_epoch":"1","operations":["ReadView","Watch"]}],
            "resources":{"max_frame_bytes":"1048576","read_timeout_ms":"1000","write_timeout_ms":"1000","response_timeout_ms":"30000","queue_capacity":"2","max_connections":"2"},
            "clock":{"kind":"TestOnly","plan":{"init_ns":"1","recover_ns":["90000"],"messages":{}}}}),
    )
}

fn s_resources(space: &Space) -> PathBuf {
    write_json(
        &space.path("s-resources.json"),
        &json!({"schema_revision":"s-structure-resources/1","s_resources":{
            "max_frame_bytes":"1048576","read_timeout_ms":"1000","write_timeout_ms":"1000","response_timeout_ms":"30000",
            "audit_cache_source_bytes":"1048576","queue_capacity":"2","max_connections":"2"}}),
    )
}

/// S 写者以诊断夹具 theta 配置开门的 TestOnly 开关（仅 `production_session_testonly` 构建认）。
/// 本文件只在拒启负控里设置它；成功助手一律 `env_remove`，走已签 synthetic 正式配置（#1769）。
const THETA_DIAGNOSTIC: (&str, &str) = ("S_THETA_DIAGNOSTIC_TESTONLY", "1");

/// S 正式写者（`serve --protocol-revision s-session/3`）命令；不含 TestOnly 开关。
fn s_serve_command(space: &Space, db: &Path, limits: &Path) -> Command {
    let mut command = Command::new(s_bin());
    command
        .args([
            "serve",
            "--protocol-revision",
            "s-session/3",
            "--admission-job-limits",
        ])
        .arg(limits)
        .arg("--db")
        .arg(db)
        .arg("--profile")
        .arg(fixture(TB02A_PROFILE))
        .args(["--writer-epoch", "1", "--clock-plan"])
        .arg(space.path("clock.json"))
        .arg("--socket")
        .arg(space.path("s.sock"))
        .arg("--resource-config")
        .arg(s_resources(space))
        .env_remove(THETA_DIAGNOSTIC.0)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    command
}

/// 以正式配置（已签 synthetic profile）拉起 S 写者，等 socket 就绪。
fn s_serve(space: &Space, db: &Path, limits: &Path) -> Child {
    let socket = space.path("s.sock");
    let mut child = s_serve_command(space, db, limits).spawn().unwrap();
    let deadline = Instant::now() + Duration::from_secs(30);
    while !socket.exists() {
        if let Some(status) = child.try_wait().unwrap() {
            panic!("S serve 提前退出 {status}：{}", launcher_stderr(&mut child));
        }
        assert!(Instant::now() < deadline, "S socket 未就绪");
        std::thread::sleep(Duration::from_millis(50));
    }
    child
}

fn launcher_manifest(
    space: &Space,
    profile: &str,
    source: &Value,
    s_db: &Path,
    limits: &Path,
    x_prof: &Path,
) -> PathBuf {
    let resources = s_resources(space);
    write_json(
        &space.path("production.json"),
        &json!({"manifest_revision":"production-session-manifest/1","profile":profile,
            "state_dir":space.path("launcher-state"),
            "execution_capabilities":{"namespaces":[HL_NS]},
            "structure_source":source,
            "s":{"db":s_db,"session":SESSION,"catalog":fixture("catalog/signed-catalog.json"),
                "profile":fixture(TB02A_PROFILE),"clock_plan":space.path("clock.json"),
                "session_generation":"1","delivery_retain_generations":"4","admission_job_limits":limits,
                "writer_epoch":"1","socket":space.path("s.sock"),"resource_config":resources},
            "economic":{"manifest":economic_manifest(space),"e":{"db":space.path("e.db"),"epoch":"1"},
                "b":[{"chong":"one","db":space.path("b.db"),"epoch":"1"}]},
            "x":{"db":space.path("x.db"),"profile":x_prof,"writer_epoch":"1"}}),
    )
}

fn spawn_launcher(manifest: &Path) -> Child {
    assert!(
        std::env::var_os(CREDENTIAL_KEY).is_none(),
        "测试进程环境不得含哨兵键"
    );
    Command::new(launcher_bin())
        .arg("--manifest")
        .arg(manifest)
        .env_remove(CREDENTIAL_KEY)
        .env_remove(THETA_DIAGNOSTIC.0)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap()
}

fn proc_stat_ids(pid: u32) -> Option<(u32, u32)> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let mut fields = stat.rsplit_once(')')?.1.split_whitespace();
    let ppid = fields.nth(1)?.parse().ok()?;
    let pgrp = fields.next()?.parse().ok()?;
    Some((ppid, pgrp))
}

fn ppid(pid: u32) -> Option<u32> {
    proc_stat_ids(pid).map(|(ppid, _)| ppid)
}

/// 仅返回归属本测试隔离进程组（`pgrp == owner_pgid`）的 PID（排除当前测试进程）。
fn owned_group_pids(owner_pgid: u32) -> Vec<u32> {
    let self_pid = std::process::id();
    let mut out = Vec::new();
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return out;
    };
    for entry in entries.flatten() {
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        if pid == self_pid {
            continue;
        }
        if proc_stat_ids(pid).is_some_and(|(_, pgrp)| pgrp == owner_pgid) {
            out.push(pid);
        }
    }
    out.sort_unstable();
    out
}

/// 优先向目标根进程发 SIGTERM 走正常停机；仅当逾期或根进程退出后仍有本测试进程组残留时，
/// 才对 `owned_group_pids(pgid)` 兜底升级，不波及任何其他进程或并发工位。
fn terminate_owned_group(
    child: &mut Child,
    pgid: u32,
    exit_status: &mut Option<ExitStatus>,
    grace: Duration,
) -> (bool, bool, Vec<u32>) {
    if exit_status.is_none() {
        if let Ok(Some(st)) = child.try_wait() {
            *exit_status = Some(st);
        }
    }
    let mut escalated = false;
    if exit_status.is_none() {
        // SAFETY: `pgid == child.id()` 且 `child` 尚未回收，只向本测试创建的根进程发 SIGTERM。
        unsafe { libc::kill(pgid as libc::pid_t, libc::SIGTERM) };
        let grace_deadline = Instant::now() + grace;
        while exit_status.is_none() && Instant::now() < grace_deadline {
            match child.try_wait() {
                Ok(Some(st)) => {
                    *exit_status = Some(st);
                    break;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(25)),
                Err(_) => break,
            }
        }
    }
    if exit_status.is_none() {
        escalated = true;
        for pid in owned_group_pids(pgid) {
            // SAFETY: 仅向 `pgrp == pgid` 且由本测试隔离进程组拥有的 PID 发 SIGKILL。
            unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) };
        }
        let _ = child.kill();
        let kill_deadline = Instant::now() + Duration::from_secs(5);
        while exit_status.is_none() && Instant::now() < kill_deadline {
            match child.try_wait() {
                Ok(Some(st)) => {
                    *exit_status = Some(st);
                    break;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(25)),
                Err(_) => break,
            }
        }
    }

    let mut stragglers_cleaned = false;
    let settle_deadline = Instant::now() + Duration::from_millis(200);
    while !owned_group_pids(pgid).is_empty() && Instant::now() < settle_deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    let mut remaining = owned_group_pids(pgid);
    if !remaining.is_empty() {
        stragglers_cleaned = true;
        for &pid in &remaining {
            unsafe { libc::kill(pid as libc::pid_t, libc::SIGTERM) };
        }
        let term_deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < term_deadline {
            remaining = owned_group_pids(pgid);
            if remaining.is_empty() {
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        if !remaining.is_empty() {
            let kill_deadline = Instant::now() + Duration::from_secs(5);
            while Instant::now() < kill_deadline {
                remaining = owned_group_pids(pgid);
                if remaining.is_empty() {
                    break;
                }
                for &pid in &remaining {
                    unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) };
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            remaining = owned_group_pids(pgid);
        }
    }
    (escalated, stragglers_cleaned, remaining)
}

fn exe_name(pid: u32) -> String {
    std::fs::read(format!("/proc/{pid}/cmdline"))
        .ok()
        .and_then(|b| {
            b.split(|c| *c == 0)
                .next()
                .map(|s| String::from_utf8_lossy(s).into_owned())
        })
        .map(|s| {
            Path::new(&s)
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned()
        })
        .unwrap_or_default()
}
fn environ(pid: u32) -> String {
    String::from_utf8_lossy(&std::fs::read(format!("/proc/{pid}/environ")).unwrap()).into_owned()
}
/// launcher 直接子进程：域名 → pid。
fn domain_children(launcher: u32) -> Vec<(String, u32)> {
    let mut out = Vec::new();
    for entry in std::fs::read_dir("/proc").unwrap().flatten() {
        let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() else {
            continue;
        };
        if ppid(pid) == Some(launcher) {
            out.push((exe_name(pid), pid));
        }
    }
    out.sort();
    out
}
const DOMAINS: [&str; 4] = [
    "b_chong_session",
    "e_economic_session",
    "s_structure_session",
    "x_execution_session",
];

fn launcher_stderr(child: &mut Child) -> String {
    let mut s = String::new();
    if let Some(mut e) = child.stderr.take() {
        let _ = e.read_to_string(&mut s);
    }
    s
}

fn launcher_events(lines: &[String]) -> Vec<Value> {
    lines
        .iter()
        .filter_map(|line| line.strip_prefix("production_session "))
        .filter_map(|raw| serde_json::from_str::<Value>(raw).ok())
        .collect()
}

/// 边运行边读取 launcher stderr，以结构化事件而非进程列表快照作为有界同步点，
/// 且收尾对 EOF 等待设上限，避免残留写端卡死测试。
struct LauncherStderr {
    state: Arc<(Mutex<(Vec<String>, bool)>, Condvar)>,
    reader: Option<std::thread::JoinHandle<()>>,
}

impl LauncherStderr {
    fn attach(launcher: &mut Child) -> Self {
        let stderr = launcher.stderr.take().expect("launcher stderr piped");
        let state = Arc::new((Mutex::new((Vec::new(), false)), Condvar::new()));
        let shared = Arc::clone(&state);
        let reader = std::thread::spawn(move || {
            let mut reader = BufReader::new(stderr);
            let mut line = String::new();
            loop {
                line.clear();
                match reader.read_line(&mut line) {
                    Ok(0) | Err(_) => break,
                    Ok(_) => {
                        let trimmed = line.trim_end_matches(['\r', '\n']).to_string();
                        let (lock, cv) = &*shared;
                        lock.lock()
                            .unwrap_or_else(|e| e.into_inner())
                            .0
                            .push(trimmed);
                        cv.notify_all();
                    }
                }
            }
            let (lock, cv) = &*shared;
            lock.lock().unwrap_or_else(|e| e.into_inner()).1 = true;
            cv.notify_all();
        });
        Self {
            state,
            reader: Some(reader),
        }
    }

    fn snapshot_log(&self) -> String {
        self.state
            .0
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .0
            .join("\n")
    }

    fn wait_for<T>(
        &self,
        what: &str,
        launcher: &mut Child,
        exit_status: &mut Option<ExitStatus>,
        timeout: Duration,
        mut check: impl FnMut(&[String]) -> Option<T>,
    ) -> T {
        let deadline = Instant::now() + timeout;
        let (lock, cv) = &*self.state;
        let mut guard = lock.lock().unwrap_or_else(|e| e.into_inner());
        loop {
            if let Some(found) = check(&guard.0) {
                return found;
            }
            if exit_status.is_none() {
                if let Some(status) = launcher.try_wait().unwrap() {
                    *exit_status = Some(status);
                }
            }
            if let Some(status) = *exit_status {
                let drain_until = (Instant::now() + Duration::from_millis(200)).min(deadline);
                while !guard.1 {
                    let slice = drain_until.saturating_duration_since(Instant::now());
                    if slice.is_zero() {
                        break;
                    }
                    guard = cv
                        .wait_timeout(guard, slice)
                        .unwrap_or_else(|e| e.into_inner())
                        .0;
                }
                let log = guard.0.join("\n");
                panic!("{what}：launcher 提前退出 {status}\n{log}");
            }
            if guard.1 {
                let log = guard.0.join("\n");
                panic!("{what}：launcher stderr 已关闭但未观测到目标事件\n{log}");
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                let log = guard.0.join("\n");
                panic!("{what} 超时（上限 {timeout:?}）\n{log}");
            }
            guard = cv
                .wait_timeout(guard, remaining.min(Duration::from_millis(50)))
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
    }

    fn finish_bounded(&mut self, timeout: Duration) -> (Vec<String>, bool) {
        let deadline = Instant::now() + timeout;
        let (lock, cv) = &*self.state;
        let mut guard = lock.lock().unwrap_or_else(|e| e.into_inner());
        while !guard.1 {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            guard = cv
                .wait_timeout(guard, remaining)
                .unwrap_or_else(|e| e.into_inner())
                .0;
        }
        let eof = guard.1;
        let lines = guard.0.clone();
        drop(guard);
        if eof {
            if let Some(handle) = self.reader.take() {
                let _ = handle.join();
            }
        }
        (lines, eof)
    }
}

/// 隔离进程组托管的 launcher 守卫：在正常停止、断言 panic、stderr 提前 EOF 与等待超时路径上
/// 统一优先正常 SIGTERM 停机、逾期仅对本测试进程组兜底清理、并对日志读者收尾设上限。
/// 声明在 `Space` 之后时，Rust 逆序 Drop 保证进程先退出再删除临时目录。
struct ManagedLauncher {
    child: Child,
    pgid: u32,
    stderr: LauncherStderr,
    exit_status: Option<ExitStatus>,
    stop_grace: Duration,
    drain_timeout: Duration,
    cleaned: bool,
}

impl ManagedLauncher {
    fn spawn(manifest: &Path) -> Self {
        assert!(
            std::env::var_os(CREDENTIAL_KEY).is_none(),
            "测试进程环境不得含哨兵键"
        );
        let mut child = Command::new(launcher_bin())
            .arg("--manifest")
            .arg(manifest)
            .env_remove(CREDENTIAL_KEY)
            .env_remove(THETA_DIAGNOSTIC.0)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .process_group(0)
            .spawn()
            .unwrap();
        let pgid = child.id();
        let stderr = LauncherStderr::attach(&mut child);
        Self {
            child,
            pgid,
            stderr,
            exit_status: None,
            stop_grace: Duration::from_secs(15),
            drain_timeout: Duration::from_secs(5),
            cleaned: false,
        }
    }

    fn id(&self) -> u32 {
        self.pgid
    }

    fn try_wait(&mut self) -> Option<ExitStatus> {
        if self.exit_status.is_none() {
            if let Some(st) = self.child.try_wait().unwrap() {
                self.exit_status = Some(st);
            }
        }
        self.exit_status
    }

    fn wait_for_stderr<T>(
        &mut self,
        what: &str,
        timeout: Duration,
        check: impl FnMut(&[String]) -> Option<T>,
    ) -> T {
        self.stderr
            .wait_for(what, &mut self.child, &mut self.exit_status, timeout, check)
    }

    fn wait_until(&mut self, what: &str, timeout: Duration, mut ready: impl FnMut() -> bool) {
        let deadline = Instant::now() + timeout;
        while !ready() {
            if let Some(status) = self.try_wait() {
                panic!(
                    "{what}：launcher 提前退出 {status}\n{}",
                    self.stderr.snapshot_log()
                );
            }
            assert!(
                Instant::now() < deadline,
                "{what} 未在 {timeout:?} 内就绪\n{}",
                self.stderr.snapshot_log()
            );
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    fn shutdown_bounded(
        &mut self,
        require_graceful: bool,
    ) -> Result<(ExitStatus, Vec<String>), String> {
        let (escalated, stragglers_cleaned, remaining) = terminate_owned_group(
            &mut self.child,
            self.pgid,
            &mut self.exit_status,
            self.stop_grace,
        );
        let (lines, eof) = self.stderr.finish_bounded(self.drain_timeout);
        self.cleaned = true;
        let log = lines.join("\n");
        if escalated {
            return Err(format!(
                "launcher 正常停止超过上限 {:?}，已仅对本测试进程组 {} 升级 SIGKILL 清理\
                 （残留 PID={remaining:?}，stderr_eof={eof}）：\n{log}",
                self.stop_grace, self.pgid
            ));
        }
        if !remaining.is_empty() {
            return Err(format!(
                "launcher 退出后本测试进程组 {} 仍有残留 PID={remaining:?}：\n{log}",
                self.pgid
            ));
        }
        if require_graceful && stragglers_cleaned {
            return Err(format!(
                "launcher 正常退出后未自行回收本测试进程组 {} 的全部子进程（已兜底清理）：\n{log}",
                self.pgid
            ));
        }
        if !eof {
            return Err(format!(
                "launcher stderr 读者收尾超过上限 {:?}：\n{log}",
                self.drain_timeout
            ));
        }
        let status = self
            .exit_status
            .ok_or_else(|| format!("launcher 未返回退出状态：\n{log}"))?;
        Ok((status, lines))
    }

    fn stop_gracefully(mut self) -> Result<(ExitStatus, Vec<String>), String> {
        self.shutdown_bounded(true)
    }
}

impl Drop for ManagedLauncher {
    fn drop(&mut self) {
        if !self.cleaned {
            let _ = self.shutdown_bounded(false);
        }
    }
}

/// 等四类域进程都在 launcher 名下存活；launcher 先退出则带其 stderr 失败。
fn wait_domains(launcher: &mut Child) -> Vec<(String, u32)> {
    let deadline = Instant::now() + Duration::from_secs(30);
    loop {
        if let Some(status) = launcher.try_wait().unwrap() {
            panic!("launcher 提前退出 {status}：{}", launcher_stderr(launcher));
        }
        let kids = domain_children(launcher.id());
        let names: Vec<&str> = kids.iter().map(|(n, _)| n.as_str()).collect();
        if DOMAINS.iter().all(|d| names.contains(d)) {
            return kids;
        }
        assert!(Instant::now() < deadline, "域进程未全部就绪：{kids:?}");
        std::thread::sleep(Duration::from_millis(100));
    }
}

fn stop(launcher: &mut Child) -> std::process::ExitStatus {
    unsafe { libc::kill(launcher.id() as libc::pid_t, libc::SIGTERM) };
    launcher.wait().unwrap()
}

/// 域进程出现在 launcher 名下不等于已持锁/建库/开 socket；就绪类断言一律限时轮询。
fn eventually(what: &str, ready: impl Fn() -> bool) {
    let deadline = Instant::now() + Duration::from_secs(30);
    while !ready() {
        assert!(Instant::now() < deadline, "{what} 未就绪");
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn assert_lock_held(db: &Path) {
    let path = format!("{}.writer.lock", db.display());
    eventually(&format!("{path} 被持有"), || {
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .is_ok_and(|lock| lock.try_lock().is_err())
    });
}

/// 完整 simulation 夹具：S 带声明 init + 锚；返回 (manifest, s_db)。
fn simulation(space: &Space, profile: &str, credential: bool) -> (PathBuf, PathBuf) {
    let source = declaration("TestOnlyStructure", DECLARED_NS);
    let s_db = s_init_v3(space, Some(&source));
    let limits = anchor(&s_db);
    let xp = x_profile(space, profile, None, Some("tb09-sentinel"), credential);
    (
        launcher_manifest(space, profile, &source, &s_db, &limits, &xp),
        s_db,
    )
}

#[test]
fn simulation_profile_spawns_isolated_domain_processes() {
    let space = Space::new();
    let (manifest, s_db) = simulation(&space, "simulation", false);
    let mut launcher = spawn_launcher(&manifest);
    let kids = wait_domains(&mut launcher);
    let mut pids: Vec<u32> = kids.iter().map(|(_, p)| *p).collect();
    pids.sort_unstable();
    pids.dedup();
    assert_eq!(pids.len(), kids.len(), "PID 必须互异");
    for db in [
        s_db.clone(),
        space.path("e.db"),
        space.path("b.db"),
        space.path("x.db"),
    ] {
        assert_lock_held(&db);
    }
    // S 持写锁后仍在做 admission（枚举并固定库文件家族）；开 socket 前读库会新建/改动 `-shm`，
    // 使 admission 以 SourceIdentityChanged 拒启。先等 socket，再读。
    eventually("S socket", || space.path("s.sock").exists());
    assert!(meta(&s_db, "SELECT value FROM meta WHERE key='writer_epoch'").is_some());
    for db in ["e.db", "b.db"] {
        eventually(&format!("{db} 的 writer_epoch"), || {
            meta(&space.path(db), "SELECT v FROM meta WHERE k='writer_epoch'").is_some()
        });
    }
    eventually("x.db 的 writer_epoch=1", || {
        meta(
            &space.path("x.db"),
            "SELECT value FROM x_meta WHERE key='writer_epoch'",
        )
        .as_deref()
            == Some("1")
    });
    let status = stop(&mut launcher);
    assert_eq!(status.code(), Some(0), "{}", launcher_stderr(&mut launcher));
    for (_, pid) in kids {
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "子进程 {pid} 未回收"
        );
    }
}

#[test]
fn credential_sentinel_only_in_x_process_environment() {
    let space = Space::new();
    // 凭据文件须存在，launcher 才按 credential_scope 读取并只注入 X。
    let (manifest, _) = simulation(&space, "simulation", true);
    let mut launcher = spawn_launcher(&manifest);
    let kids = wait_domains(&mut launcher);
    assert!(
        !environ(launcher.id()).contains(CREDENTIAL_KEY),
        "launcher 环境含哨兵键"
    );
    for (name, pid) in &kids {
        let has = environ(*pid).contains(CREDENTIAL_KEY);
        assert_eq!(
            has,
            name == "x_execution_session",
            "{name} 环境哨兵键归属错误"
        );
    }
    assert_eq!(stop(&mut launcher).code(), Some(0));
}

#[test]
fn missing_credential_refuses_x_send_surface() {
    let space = Space::new();
    let listener = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0)).unwrap();
    listener.set_nonblocking(true).unwrap();
    let endpoint = listener.local_addr().unwrap().to_string();
    let xp = x_profile(
        &space,
        "experiment",
        Some(&endpoint),
        Some("tb09-sentinel"),
        false,
    );
    let out = run(Command::new(x_bin())
        .args(["serve", "--db"])
        .arg(space.path("x.db"))
        .arg("--profile")
        .arg(&xp)
        .args(["--writer-epoch", "1"])
        .env_remove(CREDENTIAL_KEY));
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("MissingDependency"));
    std::thread::sleep(Duration::from_millis(200));
    let mut connections = 0;
    while listener.accept().is_ok() {
        connections += 1;
    }
    assert_eq!(connections, 0, "X 不得连接端点");
    // S 不受 X 缺凭据影响：声明源输入经正式写入口照常接纳。
    let s_db = s_init_v3(&space, Some(&declaration("TestOnlyStructure", DECLARED_NS)));
    let limits = anchor(&s_db);
    let mut s = s_serve(&space, &s_db, &limits);
    let reply = s_ingest(&space.path("s.sock"), DECLARED_NS, 1);
    assert!(!reply.to_string().contains("InvalidDomain"), "{reply}");
    assert_eq!(raw_rows(&s_db), 1, "{reply}");
    s.kill().unwrap();
    s.wait().unwrap();
}

#[test]
fn production_profile_without_tb09_fingerprint_refuses_send() {
    let space = Space::new();
    let xp = x_profile(&space, "production", None, None, true);
    let db = space.path("x.db");
    let mut x = Command::new(x_bin())
        .args(["serve", "--db"])
        .arg(&db)
        .arg("--profile")
        .arg(&xp)
        .args(["--writer-epoch", "1"])
        .env(CREDENTIAL_KEY, CREDENTIAL_VALUE)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    let state = loop {
        let out = run(Command::new(x_bin()).args(["query", "--db"]).arg(&db));
        if out.status.success() {
            break serde_json::from_slice::<Value>(&out.stdout).unwrap();
        }
        assert!(Instant::now() < deadline, "X 查询不可用");
        std::thread::sleep(Duration::from_millis(100));
    };
    assert_eq!(state["send_state"], "refused");
    assert_eq!(state["send_refusal_reason"], "MissingTb09Fingerprint");
    assert_eq!(state["tb09_fingerprint"], "");
    let submit = run(Command::new(x_bin()).args(["submit", "--db"]).arg(&db));
    assert!(String::from_utf8_lossy(&submit.stderr).contains("UnsupportedCapability"));
    x.kill().unwrap();
    x.wait().unwrap();
}

#[test]
fn manifest_rejects_execution_feed_as_structure_source() {
    let space = Space::new();
    let s_db = space.s_db();
    let xp = x_profile(&space, "simulation", None, Some("tb09-sentinel"), false);
    // HL 场所 namespace，载荷与美股 bar 同形，类别仍标个股线。
    let source = declaration("UsEquityStockLineTick", HL_NS);
    let manifest = launcher_manifest(
        &space,
        "simulation",
        &source,
        &s_db,
        &space.path("limits.json"),
        &xp,
    );
    let out = run(Command::new(launcher_bin())
        .arg("--manifest")
        .arg(&manifest));
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("InvalidDomain"));
    assert!(!s_db.exists(), "S 库不得被创建");
}

#[test]
fn s_rejects_same_shape_bars_from_undeclared_source() {
    let space = Space::new();
    let s_db = s_init_v3(&space, Some(&declaration("TestOnlyStructure", DECLARED_NS)));
    let limits = anchor(&s_db);
    let before = raw_rows_offline(&s_db);
    let mut s = s_serve(&space, &s_db, &limits);
    let rejected = s_ingest(&space.path("s.sock"), HL_NS, 1);
    assert!(rejected.to_string().contains("InvalidDomain"), "{rejected}");
    assert_eq!(raw_rows(&s_db), before);
    let accepted = s_ingest(&space.path("s.sock"), DECLARED_NS, 2);
    assert!(
        !accepted.to_string().contains("InvalidDomain"),
        "{accepted}"
    );
    assert_eq!(raw_rows(&s_db), before + 1, "{accepted}");
    s.kill().unwrap();
    s.wait().unwrap();
}

// #1845：所有声明负控使用同一 v3/profile/clock/resource/admission 夹具，避免旧库版本先拒启。
fn structure_source_fixture(space: &Space, fault: &str) -> (PathBuf, PathBuf, PathBuf) {
    let source = declaration("TestOnlyStructure", DECLARED_NS);
    let db = s_init_v3(
        space,
        if fault == "missing" {
            None
        } else {
            Some(&source)
        },
    );
    if fault == "stored_corrupt" {
        let conn = Connection::open(&db).unwrap();
        conn.execute("UPDATE meta SET value='{' WHERE key='structure_source'", [])
            .unwrap();
    }
    let limits = anchor(&db);
    let expected = if fault == "mismatch" {
        declaration("TestOnlyStructure", "testonly.other")
    } else {
        source
    };
    let file = write_json(&space.path("expected-source.json"), &expected);
    if fault == "file_corrupt" {
        std::fs::write(&file, "{").unwrap();
    } else if fault == "file_missing" {
        std::fs::remove_file(&file).unwrap();
    }
    (db, limits, file)
}

fn assert_source_refusal(fault: &str, expected_error: &str) {
    let space = Space::new();
    let (db, limits, file) = structure_source_fixture(&space, fault);
    let before = raw_rows_offline(&db);
    let out = run_refusal(
        s_serve_command(&space, &db, &limits)
            .arg("--structure-source")
            .arg(&file),
    );
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains(expected_error), "{stderr}");
    if fault == "mismatch" {
        for ns in [DECLARED_NS, "testonly.other"] {
            let canonical = newchan_rust::structure_source::Declaration::parse(&declaration(
                "TestOnlyStructure",
                ns,
            ))
            .unwrap()
            .canonical();
            // S 的错误字段是 JSON 字符串；去掉外层引号后核对完整声明的转义内容。
            let encoded = serde_json::to_string(&canonical).unwrap();
            assert!(stderr.contains(&encoded[1..encoded.len() - 1]), "{stderr}");
        }
    }
    assert!(!space.path("s.sock").exists());
    assert_eq!(raw_rows_offline(&db), before);
}

#[test]
fn s_serve_explicit_source_rejects_missing_stored_declaration() {
    assert_source_refusal("missing", "不带结构源声明");
}

#[test]
fn s_serve_explicit_source_rejects_mismatch_with_both_canonical_declarations() {
    assert_source_refusal("mismatch", "不一致");
}

#[test]
fn s_serve_explicit_source_rejects_corrupt_file() {
    assert_source_refusal("file_corrupt", "结构源声明 JSON 解析失败");
}

#[test]
fn s_serve_explicit_source_rejects_missing_file() {
    assert_source_refusal("file_missing", "读结构源声明");
}

#[test]
fn s_serve_explicit_source_charges_declaration_bytes_to_startup_limit() {
    let space = Space::new();
    let (db, _, file) = structure_source_fixture(&space, "match");
    let wire_limit = 8 * 1024 * 1024;
    let limits = anchor_with_wire_limit(&db, wire_limit);
    // 声明语义仍匹配，仅在合法 JSON 后追加超过整本启动账字节帽的空白。
    let mut bytes = std::fs::read(&file).unwrap();
    bytes.resize(bytes.len() + wire_limit as usize + 1, b' ');
    std::fs::write(&file, bytes).unwrap();
    let out = run_refusal(
        s_serve_command(&space, &db, &limits)
            .arg("--structure-source")
            .arg(&file),
    );
    assert!(!out.status.success());
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("读结构源声明"), "{stderr}");
    assert!(stderr.contains("max_total_wire_bytes"), "{stderr}");
    assert!(!space.path("s.sock").exists());
}

#[test]
fn s_serve_explicit_source_rejects_corrupt_stored_declaration() {
    assert_source_refusal("stored_corrupt", "meta.structure_source 损坏");
}

fn assert_source_listens(fault: &str, explicit: bool) {
    let space = Space::new();
    let (db, limits, file) = structure_source_fixture(&space, fault);
    let mut command = s_serve_command(&space, &db, &limits);
    if explicit {
        command.arg("--structure-source").arg(file);
    }
    let mut child = command.spawn().unwrap();
    let deadline = Instant::now() + Duration::from_secs(30);
    while !space.path("s.sock").exists() {
        if let Some(status) = child.try_wait().unwrap() {
            panic!("S serve 提前退出 {status}：{}", launcher_stderr(&mut child));
        }
        if Instant::now() >= deadline {
            child.kill().unwrap();
            child.wait().unwrap();
            panic!("S socket 未就绪");
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert_lock_held(&db);
    child.kill().unwrap();
    child.wait().unwrap();
}

#[test]
fn s_serve_explicit_source_match_listens() {
    assert_source_listens("match", true);
}

#[test]
fn s_serve_standalone_without_source_keeps_missing_declaration_contract() {
    assert_source_listens("missing", false);
}

#[test]
fn s_serve_standalone_without_source_does_not_check_corrupt_declaration() {
    assert_source_listens("stored_corrupt", false);
}

fn assert_launcher_source_failure(fault: &str) {
    let space = Space::new();
    let (db, limits, _) = structure_source_fixture(&space, fault);
    let before = raw_rows_offline(&db);
    let source = declaration(
        "TestOnlyStructure",
        if fault == "mismatch" {
            "testonly.other"
        } else {
            DECLARED_NS
        },
    );
    let xp = x_profile(&space, "simulation", None, Some("tb09-sentinel"), false);
    let manifest = launcher_manifest(&space, "simulation", &source, &db, &limits, &xp);
    let out = run_refusal(Command::new(launcher_bin()).arg("--manifest").arg(manifest));
    assert_eq!(out.status.code(), Some(1));
    let stderr = String::from_utf8_lossy(&out.stderr);
    let events: Vec<Value> = stderr
        .lines()
        .filter_map(|line| line.strip_prefix("production_session "))
        .filter_map(|line| serde_json::from_str(line).ok())
        .collect();
    assert!(
        events
            .iter()
            .any(|e| e["event"] == "exit" && e["domain"] == "S" && e["critical"] == true),
        "{stderr}"
    );
    assert!(
        events
            .iter()
            .any(|e| e["event"] == "stopped" && e["failed"] == true),
        "{stderr}"
    );
    assert!(!space.path("s.sock").exists());
    assert_eq!(raw_rows_offline(&db), before);
}

#[test]
fn production_session_refuses_s_db_without_source_declaration() {
    assert_launcher_source_failure("missing");
}

#[test]
fn production_session_refuses_s_db_with_mismatched_source_declaration() {
    assert_launcher_source_failure("mismatch");
}

#[test]
fn production_session_refuses_s_db_with_corrupt_source_declaration() {
    assert_launcher_source_failure("stored_corrupt");
}

#[test]
fn production_session_new_s_init_and_serve_share_source_declaration() {
    let space = Space::new();
    let (manifest, db) = simulation(&space, "simulation", false);
    // 锚绑定规范路径，init 重建同一路径；不改 admission 合同。
    std::fs::remove_file(&db).unwrap();
    let mut launcher = spawn_launcher(&manifest);
    let deadline = Instant::now() + Duration::from_secs(30);
    while !space.path("s.sock").exists() {
        if let Some(status) = launcher.try_wait().unwrap() {
            panic!(
                "launcher 提前退出 {status}：{}",
                launcher_stderr(&mut launcher)
            );
        }
        if Instant::now() >= deadline {
            stop(&mut launcher);
            panic!("新 S 库未监听");
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert_eq!(stop(&mut launcher).code(), Some(0));
    let stderr = launcher_stderr(&mut launcher);
    assert!(stderr.contains("\"event\":\"init\""), "{stderr}");
    let conn = Connection::open(&db).unwrap();
    let stored = newchan_rust::structure_source::stored(&conn)
        .unwrap()
        .unwrap();
    assert_eq!(
        std::fs::read_to_string(space.path("launcher-state/structure-source.json")).unwrap(),
        stored.canonical()
    );
}

fn s_ingest_frame(ns: &str, n: u32) -> String {
    let raw = json!({"schema_revision":"s-ohlc/1","session_id":SESSION,"source_namespace":ns,"source_epoch":"1",
        "instrument":"TEST.OHLC","profile":"ohlc_integer_tb02a_v1",
        "events":[{"event_id":format!("bar-{n}"),"revision":"1","seq":(n * 10).to_string(),"received_at":"2026-09-18T00:00:00Z",
            "raw_text":"3/12","open":"6","high":"12","low":"3","close":"7","timestamp":(n * 10).to_string(),"volume":"1"}]});
    let payload = json!({"op":"ingest","target_session_id":SESSION,"target_session_generation":"1","writer_epoch":"1",
        "clock_event_id":format!("input-{n}"),"raw_input":raw});
    let envelope = json!({"schema_revision":"s-session/3","session_id":SESSION,"session_generation":"1",
        "source_namespace":ns,"source_epoch":"1","message_id":format!("message-{n}"),"producer_id":"pse-test",
        "producer_epoch":"1","payload_hash":sha256_hex(newchan_rust::session_protocol::canonical_json(&payload).as_bytes()),
        "causal_refs":[],"payload":payload});
    format!(
        "{}\n",
        newchan_rust::session_protocol::canonical_json(&envelope)
    )
}

/// 经 Unix socket 执行一次完整 JSON 请求-应答（含连接、写帧、写端 EOF、读至对端 EOF 与解析），
/// 全程共享同一总截止时间 `timeout`，而非单一读/写调用超时。
fn exchange_unix_json_bounded(
    socket: &Path,
    frame: &str,
    timeout: Duration,
) -> Result<Value, String> {
    let started = Instant::now();
    let deadline = started + timeout;
    let mut stream = loop {
        match UnixStream::connect(socket) {
            Ok(s) => break s,
            Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::Interrupted) => {
                if Instant::now() >= deadline {
                    return Err(format!(
                        "S socket 事务超时（上限 {timeout:?}，耗时 {:?}，连接 {} 未完成）：{e}",
                        started.elapsed(),
                        socket.display()
                    ));
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            Err(e) => {
                return Err(format!("连接 S socket {} 失败：{e}", socket.display()));
            }
        }
    };

    let bytes = frame.as_bytes();
    let mut written = 0;
    while written < bytes.len() {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(format!(
                "S socket 事务超时（上限 {timeout:?}，耗时 {:?}，写请求未完成：已写 {written}/{} 字节）",
                started.elapsed(),
                bytes.len()
            ));
        }
        stream
            .set_write_timeout(Some(remaining.max(Duration::from_millis(1))))
            .map_err(|e| format!("设置 S socket 写超时失败：{e}"))?;
        match stream.write(&bytes[written..]) {
            Ok(0) => {
                return Err(format!(
                    "S socket 写请求中断（返回 0 字节，已写 {written}/{} 字节）",
                    bytes.len()
                ));
            }
            Ok(n) => written += n,
            Err(e) if e.kind() == ErrorKind::Interrupted => continue,
            Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                if Instant::now() >= deadline {
                    return Err(format!(
                        "S socket 事务超时（上限 {timeout:?}，耗时 {:?}，写请求未完成：已写 {written}/{} 字节）",
                        started.elapsed(),
                        bytes.len()
                    ));
                }
            }
            Err(e) => {
                return Err(format!(
                    "S socket 写请求失败（已写 {written}/{} 字节）：{e}",
                    bytes.len()
                ));
            }
        }
    }
    stream
        .shutdown(std::net::Shutdown::Write)
        .map_err(|e| format!("S socket 关闭写端失败：{e}"))?;

    let mut reply = Vec::new();
    let mut chunk = [0u8; 4096];
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            let preview = String::from_utf8_lossy(&reply);
            return Err(format!(
                "S socket 事务超时（上限 {timeout:?}，耗时 {:?}，等待回复/EOF；已收 {} 字节：{preview:?}）",
                started.elapsed(),
                reply.len()
            ));
        }
        stream
            .set_read_timeout(Some(remaining.max(Duration::from_millis(1))))
            .map_err(|e| format!("设置 S socket 读超时失败：{e}"))?;
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(n) => reply.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == ErrorKind::Interrupted => continue,
            Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {
                if Instant::now() >= deadline {
                    let preview = String::from_utf8_lossy(&reply);
                    return Err(format!(
                        "S socket 事务超时（上限 {timeout:?}，耗时 {:?}，等待回复/EOF；已收 {} 字节：{preview:?}）",
                        started.elapsed(),
                        reply.len()
                    ));
                }
            }
            Err(e) => {
                return Err(format!(
                    "S socket 读取回复失败（已收 {} 字节）：{e}",
                    reply.len()
                ));
            }
        }
    }

    let text = String::from_utf8_lossy(&reply);
    serde_json::from_str(text.trim_end()).map_err(|e| {
        format!(
            "S socket 收到不完整或非法 JSON 应答（{} 字节，耗时 {:?}）：{text:?}（{e}）",
            reply.len(),
            started.elapsed()
        )
    })
}

fn try_s_ingest_bounded(
    socket: &Path,
    ns: &str,
    n: u32,
    timeout: Duration,
) -> Result<Value, String> {
    exchange_unix_json_bounded(socket, &s_ingest_frame(ns, n), timeout)
}

/// 经 S socket 提交第 `n` 条 ingest（`s-session/3` 封包、`s-ohlc/1` 原件；一帧 LF + 写端 EOF，整体有界）。
fn s_ingest(socket: &Path, ns: &str, n: u32) -> Value {
    try_s_ingest_bounded(socket, ns, n, Duration::from_secs(30)).unwrap_or_else(|e| panic!("{e}"))
}

#[test]
fn s_keeps_committing_while_x_is_stopped() {
    let space = Space::new();
    let (manifest, s_db) = simulation(&space, "simulation", false);
    let mut launcher = spawn_launcher(&manifest);
    let kids = wait_domains(&mut launcher);
    let x = kids
        .iter()
        .find(|(n, _)| n == "x_execution_session")
        .unwrap()
        .1;
    let generation = |db: &Path| meta(db, "SELECT value FROM meta WHERE key='generation'").unwrap();
    // 开 socket 前读 S 库会干扰其 admission（见 simulation_profile_spawns_isolated_domain_processes）。
    eventually("S socket", || space.path("s.sock").exists());
    let before = generation(&s_db);
    unsafe { libc::kill(x as libc::pid_t, libc::SIGSTOP) };
    let reply = s_ingest(&space.path("s.sock"), DECLARED_NS, 1);
    let deadline = Instant::now() + Duration::from_secs(20);
    while generation(&s_db) == before {
        assert!(
            Instant::now() < deadline,
            "X 停止期间 S generation 未增加：{reply}"
        );
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(
        meta(&s_db, "SELECT value FROM meta WHERE key='structure_cut'").is_some(),
        "快照不可读"
    );
    unsafe { libc::kill(x as libc::pid_t, libc::SIGCONT) };
    std::thread::sleep(Duration::from_millis(300));
    assert!(
        launcher.try_wait().unwrap().is_none(),
        "launcher 应仍在监督"
    );
    let now: Vec<String> = domain_children(launcher.id())
        .into_iter()
        .map(|(n, _)| n)
        .collect();
    for d in DOMAINS {
        assert!(now.iter().any(|n| n == d), "{d} 不在监督中：{now:?}");
    }
    assert_eq!(stop(&mut launcher).code(), Some(0));
}

/// S 子进程的环境不得含 TestOnly 开关键（无论 launcher 自身环境有没有）。
fn assert_s_environ_lacks_theta_diagnostic(kids: &[(String, u32)]) {
    let (_, s_pid) = kids
        .iter()
        .find(|(name, _)| name == "s_structure_session")
        .expect("S 在 launcher 名下");
    let environ = environ(*s_pid);
    assert!(
        !environ.contains(&format!("{}=", THETA_DIAGNOSTIC.0)),
        "launcher 不得向 S 转交 {}",
        THETA_DIAGNOSTIC.0
    );
}

/// #1774 用户批后（synthetic 三项成本已签）正式路径的替换锁：不带 TestOnly 开关的 S 正式写者以
/// 已签 synthetic profile 开门（开 socket），不再以 AwaitingPolicy 拒启；未签拒启负控迁到
/// `driver.rs` 的 synthetic v1 夹具测试（`production_open_rejects_unsigned_profile_before_pending_begin`）。
#[test]
fn signed_synthetic_s_serve_starts_without_testonly_opt_in() {
    let space = Space::new();
    let s_db = s_init_v3(&space, Some(&declaration("TestOnlyStructure", DECLARED_NS)));
    let limits = anchor(&s_db);
    let socket = space.path("s.sock");
    let mut s = s_serve_command(&space, &s_db, &limits).spawn().unwrap();
    let deadline = Instant::now() + Duration::from_secs(30);
    while !socket.exists() {
        if let Some(status) = s.try_wait().unwrap() {
            panic!(
                "正式路径 S serve 提前退出 {status}：{}",
                launcher_stderr(&mut s)
            );
        }
        assert!(Instant::now() < deadline, "S socket 未就绪");
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(
        !environ(s.id()).contains(&format!("{}=", THETA_DIAGNOSTIC.0)),
        "正式路径不带 TestOnly 开关"
    );
    s.kill().unwrap();
    s.wait().unwrap();
}

/// launcher 本身不替 S 打开 TestOnly 臂：不设开关时经 launcher 拉起的 S 走正式路径（已签 synthetic）
/// 开门，其环境不含开关键。
#[test]
fn signed_synthetic_launcher_starts_s_without_testonly_opt_in() {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let mut launcher = Command::new(launcher_bin())
        .arg("--manifest")
        .arg(&manifest)
        .env_remove(CREDENTIAL_KEY)
        .env_remove(THETA_DIAGNOSTIC.0)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let kids = wait_domains(&mut launcher);
    eventually("S socket", || space.path("s.sock").exists());
    assert_s_environ_lacks_theta_diagnostic(&kids);
    assert_eq!(stop(&mut launcher).code(), Some(0));
}

/// 生产构建（不含 production_session_testonly）的 S 正式写者遇 TestOnly 开关即拒启：
/// 真实执行 `writer_cli` 里 `cfg!(feature = "production_session_testonly")` 的接线，不开 socket、不改库。
#[test]
#[cfg(not(feature = "production_session_testonly"))]
fn production_build_s_serve_refuses_theta_diagnostic_switch() {
    let space = Space::new();
    let s_db = s_init_v3(&space, Some(&declaration("TestOnlyStructure", DECLARED_NS)));
    let limits = anchor(&s_db);
    let before = raw_rows_offline(&s_db);
    let out = run_refusal(
        s_serve_command(&space, &s_db, &limits).env(THETA_DIAGNOSTIC.0, THETA_DIAGNOSTIC.1),
    );
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(!out.status.success(), "{stderr}");
    assert!(
        stderr.contains("ThetaDiagnosticTestOnlyInvalid"),
        "{stderr}"
    );
    assert!(stderr.contains("此构建不支持"), "{stderr}");
    assert!(!space.path("s.sock").exists(), "生产构建不得开 socket");
    assert_eq!(raw_rows_offline(&s_db), before);
}

/// 生产 launcher 的 `S_PASS` 不转交 TestOnly 开关：即使 launcher 自身环境带开关，S 也只按正式路径
/// 以已签 synthetic 开门，环境不含开关键（若被转交，生产构建的 S 会以 ThetaDiagnosticTestOnlyInvalid
/// 拒启、launcher 提前退出，`wait_domains` 据此带 stderr 失败）。
#[test]
#[cfg(not(feature = "production_session_testonly"))]
fn production_launcher_does_not_forward_theta_diagnostic_switch() {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let mut launcher = Command::new(launcher_bin())
        .arg("--manifest")
        .arg(&manifest)
        .env_remove(CREDENTIAL_KEY)
        .env(THETA_DIAGNOSTIC.0, THETA_DIAGNOSTIC.1)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let kids = wait_domains(&mut launcher);
    eventually("S socket", || space.path("s.sock").exists());
    assert_s_environ_lacks_theta_diagnostic(&kids);
    assert_eq!(stop(&mut launcher).code(), Some(0));
}

/// #1407 C3 R2：正式 launcher 在创建 state_dir 或任何域库前，拒绝明确不兼容的 E/X 历史模拟装配
/// （FIN/5 + X/3、FIN/5 + X/2、FIN/6 + X/2、缺 finance + X/3），不落任何域文件。
#[test]
fn launcher_refuses_incompatible_history_simulation_assemblies_before_writing() {
    for (case, fin_rev, x_rev) in [
        ("fin5_x3", Some("tb03b-finance/5"), "x-execution-profile/3"),
        ("fin5_x2", Some("tb03b-finance/5"), "x-execution-profile/2"),
        ("fin6_x2", Some("tb03b-finance/6"), "x-execution-profile/2"),
        ("none_x3", None, "x-execution-profile/3"),
    ] {
        let space = Space::new();
        let source = declaration("TestOnlyStructure", DECLARED_NS);
        let s_db = space.s_db();
        let limits = space.path("limits.json");
        let econ_path = space.path("economic.json");
        let mut econ = json!({
            "schema_revision": "economic-manifest/1",
            "session_id": "pse",
            "session_generation": "1",
            "book_revision": "tb03c-book/1",
            "e": {"db": space.path("e.db"), "socket": space.path("e.sock")},
            "chongs": [{"chong_id": "one", "symbol": "TEST", "operation_level": "1", "fixed_q": "10", "db": space.path("b.db"), "socket": space.path("b.sock")}],
            "authorized_sources": [{"source_namespace": "pse-test", "source_epoch": "1", "producer_id": "reader", "producer_epoch": "1", "operations": ["ReadView", "Watch"]}],
            "resources": {"max_frame_bytes": "1048576", "read_timeout_ms": "1000", "write_timeout_ms": "1000", "response_timeout_ms": "30000", "queue_capacity": "2", "max_connections": "2"},
            "clock": {"kind": "TestOnly", "plan": {"init_ns": "1", "recover_ns": ["90000"], "messages": {}}}
        });
        if let Some(rev) = fin_rev {
            econ["finance"] = json!({"schema_revision": rev});
        }
        write_json(&econ_path, &econ);
        let xp = write_json(
            &space.path("x-profile.json"),
            &json!({
                "profile_revision": x_rev,
                "mode": "simulation",
                "endpoint": null,
                "tb09_fingerprint": null,
                "credential_scope": {"env": CREDENTIAL_KEY, "file": space.path("credential.txt")},
                "history_simulation": {"x_id": "X"}
            }),
        );
        let manifest = write_json(
            &space.path("production.json"),
            &json!({
                "manifest_revision": "production-session-manifest/1",
                "profile": "simulation",
                "state_dir": space.path("launcher-state"),
                "execution_capabilities": {"namespaces": [HL_NS]},
                "structure_source": source,
                "s": {
                    "db": s_db, "session": SESSION,
                    "catalog": fixture("catalog/signed-catalog.json"),
                    "profile": fixture(TB02A_PROFILE),
                    "clock_plan": space.path("clock.json"),
                    "session_generation": "1", "delivery_retain_generations": "4",
                    "admission_job_limits": limits, "writer_epoch": "1",
                    "socket": space.path("s.sock"), "resource_config": s_resources(&space)
                },
                "economic": {
                    "manifest": econ_path,
                    "e": {"db": space.path("e.db"), "epoch": "1"},
                    "b": [{"chong": "one", "db": space.path("b.db"), "epoch": "1"}]
                },
                "x": {"db": space.path("x.db"), "profile": xp, "writer_epoch": "1"}
            }),
        );
        let out = run_refusal(
            Command::new(launcher_bin())
                .arg("--manifest")
                .arg(&manifest),
        );
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(!out.status.success(), "{case}: {stderr}");
        assert!(stderr.contains("VersionUnsupported"), "{case}: {stderr}");
        assert!(
            !space.path("launcher-state").exists(),
            "{case}: 不兼容装配不得创建 state_dir"
        );
        for db in [
            s_db,
            space.path("e.db"),
            space.path("b.db"),
            space.path("x.db"),
        ] {
            assert!(!db.exists(), "{case}: 不兼容装配不得创建 {}", db.display());
        }
    }
}

struct NonHistoryBadXObservation {
    s_pid: u32,
    e_pid: u32,
    b_pid: u32,
    x_pid: u32,
    x_exit: Value,
}

fn start_non_history_bad_x_until_x_exit(
    space: &Space,
) -> (PathBuf, ManagedLauncher, NonHistoryBadXObservation) {
    let source = declaration("TestOnlyStructure", DECLARED_NS);
    let s_db = s_init_v3(space, Some(&source));
    let limits = anchor(&s_db);
    let bad_xp = write_json(
        &space.path("x-bad-non-history.json"),
        &json!({
            "profile_revision": "x-execution-profile/99",
            "mode": "simulation",
            "endpoint": null,
            "tb09_fingerprint": null,
            "credential_scope": {"env": CREDENTIAL_KEY, "file": space.path("credential.txt")}
        }),
    );
    let manifest = launcher_manifest(space, "simulation", &source, &s_db, &limits, &bad_xp);
    let mut launcher = ManagedLauncher::spawn(&manifest);

    // 停止前的有界同步点：必须等 launcher 监督循环真已观察并记录同一 X 的退出事件，
    // 而不以 `/proc` 瞬时看不到 X（可能是尚未被 100ms 监督周期 try_wait 回收的僵尸）作为停止信号。
    let obs = launcher.wait_for_stderr(
        "launcher 观测到同一 X 的退出事件",
        Duration::from_secs(30),
        |lines| {
            let events = launcher_events(lines);
            let spawn_pid = |domain: &str| -> Option<(usize, u32)> {
                events.iter().enumerate().find_map(|(idx, ev)| {
                    (ev["event"] == "spawn" && ev["domain"] == domain)
                        .then(|| ev["pid"].as_u64().and_then(|p| u32::try_from(p).ok()))
                        .flatten()
                        .map(|pid| (idx, pid))
                })
            };
            let (_, s_pid) = spawn_pid("S")?;
            let (_, e_pid) = spawn_pid("E")?;
            let (_, b_pid) = spawn_pid("B:one")?;
            let (x_spawn_idx, x_pid) = spawn_pid("X")?;
            let x_exit = events
                .iter()
                .enumerate()
                .find(|(idx, ev)| {
                    *idx > x_spawn_idx && ev["event"] == "exit" && ev["domain"] == "X"
                })
                .map(|(_, ev)| ev.clone())?;
            Some(NonHistoryBadXObservation {
                s_pid,
                e_pid,
                b_pid,
                x_pid,
                x_exit,
            })
        },
    );
    (s_db, launcher, obs)
}

fn panic_payload_text(payload: Box<dyn std::any::Any + Send>) -> String {
    if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else if let Some(s) = payload.downcast_ref::<&str>() {
        (*s).to_string()
    } else {
        "<non-string panic payload>".to_string()
    }
}

/// #1407 C3 R3：非历史模拟 `/1` 装配恢复父版行为：
/// 1. 坏非历史 X `profile_revision` 仍由非关键 X 自行拒绝退出，S/E/B 照常启动存活；
/// 2. launcher 不在 `load_manifest` 预读 `economic.manifest`，未给正常非历史配置新增前置依赖。
#[test]
fn non_history_preserves_parent_startup_and_x_degradation() {
    // 1) 非历史配置 + 坏 X revision：S/E/B 正常启动，X 作为非关键进程自行拒绝，launcher 观察到同一 X 退出后仍继续监督 S/E/B。
    // `launcher` 声明在 `space` 之后，任何返回/panic/超时均先清理进程组与 stderr 读者，再删临时目录。
    let space = Space::new();
    let (s_db, mut launcher, obs) = start_non_history_bad_x_until_x_exit(&space);
    let NonHistoryBadXObservation {
        s_pid,
        e_pid,
        b_pid,
        x_pid,
        x_exit,
    } = obs;

    // 坏 X 及其非关键属性：已非 0 退出并被 launcher 回收，未建 x.db，且 critical=false。
    assert_eq!(
        x_exit["critical"],
        json!(false),
        "launcher 应将坏 X 退出标记为非关键：{x_exit}"
    );
    let x_status = x_exit["status"].as_str().unwrap_or_default();
    assert!(
        x_status.starts_with("exit status: ") && x_status != "exit status: 0",
        "坏 X 应自行非 0 退出：{x_exit}"
    );
    assert!(
        !Path::new(&format!("/proc/{x_pid}")).exists(),
        "launcher 记录 X 退出后应已回收原 X pid={x_pid}"
    );
    assert!(
        !space.path("x.db").exists(),
        "坏 X 应先因 VersionUnsupported 拒启，不得创建 x.db"
    );
    assert!(
        launcher.try_wait().is_none(),
        "坏非历史 X 不应导致整组 launcher 提前退出"
    );

    // 其他域继续：原 S/E/B 进程存活、持锁、开 socket，且 X 退出后 S 仍正常接纳声明源写入并推进 generation。
    launcher.wait_until("S socket", Duration::from_secs(30), || {
        space.path("s.sock").exists()
    });
    launcher.wait_until("E socket", Duration::from_secs(30), || {
        space.path("e.sock").exists()
    });
    launcher.wait_until("B socket", Duration::from_secs(30), || {
        space.path("b.sock").exists()
    });
    let expected_kids = vec![
        ("b_chong_session".to_string(), b_pid),
        ("e_economic_session".to_string(), e_pid),
        ("s_structure_session".to_string(), s_pid),
    ];
    assert_eq!(
        domain_children(launcher.id()),
        expected_kids,
        "X 非关键退出后应仅保留原 S/E/B 子进程"
    );
    for db in [s_db.clone(), space.path("e.db"), space.path("b.db")] {
        assert_lock_held(&db);
    }
    assert!(meta(&s_db, "SELECT value FROM meta WHERE key='writer_epoch'").is_some());
    for db in ["e.db", "b.db"] {
        launcher.wait_until(
            &format!("{db} 的 writer_epoch"),
            Duration::from_secs(30),
            || meta(&space.path(db), "SELECT v FROM meta WHERE k='writer_epoch'").is_some(),
        );
    }
    let before_rows = raw_rows(&s_db);
    let before_gen = meta(&s_db, "SELECT value FROM meta WHERE key='generation'").unwrap();
    let accepted = try_s_ingest_bounded(
        &space.path("s.sock"),
        DECLARED_NS,
        1,
        Duration::from_secs(30),
    )
    .unwrap_or_else(|e| panic!("X 退出后有界 S socket 写入失败：{e}"));
    assert!(
        !accepted.to_string().contains("InvalidDomain")
            && !accepted.to_string().contains("\"error\""),
        "X 退出后 S 应继续接纳声明源写入：{accepted}"
    );
    launcher.wait_until(
        "X 退出后 S 提交推进 generation",
        Duration::from_secs(30),
        || {
            meta(&s_db, "SELECT value FROM meta WHERE key='generation'")
                .is_some_and(|g| g != before_gen)
        },
    );
    assert_eq!(raw_rows(&s_db), before_rows + 1, "{accepted}");
    assert_eq!(
        domain_children(launcher.id()),
        expected_kids,
        "S 写入后原 S/E/B 子进程应继续存活"
    );
    assert!(
        launcher.try_wait().is_none(),
        "其他域继续运行期间 launcher 不得提前退出"
    );

    let launcher_pid = launcher.id();
    let (status, lines) = launcher
        .stop_gracefully()
        .unwrap_or_else(|e| panic!("有界正常停止失败：{e}"));
    let stderr = lines.join("\n");
    assert_eq!(status.code(), Some(0), "正常停止应返回 0：{stderr}");
    for pid in [launcher_pid, s_pid, e_pid, b_pid, x_pid] {
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "停止后进程 {pid} 未回收"
        );
    }
    assert!(
        owned_group_pids(launcher_pid).is_empty(),
        "停止后本测试进程组 {launcher_pid} 不得有残留"
    );
    assert!(
        stderr.contains("VersionUnsupported") && stderr.contains("x-execution-profile/99"),
        "X 应报 VersionUnsupported：{stderr}"
    );
    let events = launcher_events(&lines);
    let x_spawns: Vec<&Value> = events
        .iter()
        .filter(|e| e["event"] == "spawn" && e["domain"] == "X")
        .collect();
    assert_eq!(x_spawns.len(), 1, "同一 X 应只拉起一次：{stderr}");
    assert_eq!(x_spawns[0]["pid"].as_u64(), Some(u64::from(x_pid)));
    let exits: Vec<&Value> = events.iter().filter(|e| e["event"] == "exit").collect();
    assert_eq!(exits.len(), 1, "除坏 X 外不应有其他域提前退出：{stderr}");
    assert_eq!(exits[0]["domain"], "X", "{stderr}");
    assert_eq!(exits[0]["critical"], json!(false), "{stderr}");
    assert!(
        events
            .iter()
            .any(|e| e["event"] == "stopped" && e["failed"] == json!(false)),
        "非关键 X 退出不应将整组停止标为 failed：{stderr}"
    );

    // 2) 非历史配置 + 缺失 economic.manifest：load_manifest 不预读 E 配置，先建 state_dir 再由 E init 报错（有界探针）。
    let space2 = Space::new();
    let source2 = declaration("TestOnlyStructure", DECLARED_NS);
    let s_db2 = s_init_v3(&space2, Some(&source2));
    let limits2 = anchor(&s_db2);
    let xp2 = x_profile(&space2, "simulation", None, Some("tb09-sentinel"), false);
    let manifest2 = launcher_manifest(&space2, "simulation", &source2, &s_db2, &limits2, &xp2);
    std::fs::remove_file(space2.path("economic.json")).unwrap();
    let out = run_command_bounded(
        Command::new(launcher_bin())
            .arg("--manifest")
            .arg(&manifest2),
        Duration::from_secs(30),
        "缺 economic.manifest 启动探针",
    );
    let stderr2 = String::from_utf8_lossy(&out.stderr);
    assert!(!out.status.success(), "{stderr2}");
    assert!(
        space2.path("launcher-state").is_dir(),
        "非历史配置不应在 load_manifest 预读 economic.manifest：{stderr2}"
    );
    assert!(
        stderr2.contains("E init 失败") && !stderr2.contains("VersionUnsupported"),
        "缺 economic.manifest 应推进至 E init 报错而非版本预检拒绝：{stderr2}"
    );
}

/// 反例 1：连接后对端不给回复、慢速滴漏不给 EOF 或写回一帧后不关闭连接时，
/// 整体 socket 事务必须在总上限内以可辨认根因失败，并触发托管 launcher 与全部后代进程收尾。
#[test]
fn non_history_stalled_s_socket_times_out_and_cleans_up_launcher() {
    let space = Space::new();
    let socket_cap = Duration::from_millis(450);

    // 1a) 连接后读取请求但既不写回复也不给 EOF。
    let silent_sock = space.path("stalled-silent.sock");
    let listener = UnixListener::bind(&silent_sock).unwrap();
    let (tx_a, rx_a) = std::sync::mpsc::channel::<()>();
    let srv_a = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut req = Vec::new();
        let _ = stream.read_to_end(&mut req);
        let _ = rx_a.recv_timeout(Duration::from_secs(5));
    });
    let t0 = Instant::now();
    let err_a = try_s_ingest_bounded(&silent_sock, DECLARED_NS, 1, socket_cap).unwrap_err();
    let elapsed_a = t0.elapsed();
    let _ = tx_a.send(());
    srv_a.join().unwrap();
    assert!(
        elapsed_a >= Duration::from_millis(350) && elapsed_a < Duration::from_secs(3),
        "静默卡死耗时超出预期窗口：{elapsed_a:?}，err={err_a}"
    );
    assert!(
        err_a.contains("S socket 事务超时")
            && err_a.contains("等待回复/EOF")
            && err_a.contains("已收 0 字节"),
        "静默卡死报错未指明根因：{err_a}"
    );

    // 1b) 慢速滴漏（每 90ms 写 1 字节且不给 EOF），证明上限约束的是整个事务而非单次 read。
    let trickle_sock = space.path("stalled-trickle.sock");
    let listener = UnixListener::bind(&trickle_sock).unwrap();
    let (tx_b, rx_b) = std::sync::mpsc::channel::<()>();
    let srv_b = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut req = Vec::new();
        let _ = stream.read_to_end(&mut req);
        while rx_b.try_recv().is_err() {
            if stream.write_all(b" ").is_err() {
                break;
            }
            if rx_b.recv_timeout(Duration::from_millis(90)).is_ok() {
                break;
            }
        }
    });
    let t1 = Instant::now();
    let err_b = try_s_ingest_bounded(&trickle_sock, DECLARED_NS, 1, socket_cap).unwrap_err();
    let elapsed_b = t1.elapsed();
    let _ = tx_b.send(());
    srv_b.join().unwrap();
    assert!(
        elapsed_b >= Duration::from_millis(350) && elapsed_b < Duration::from_secs(3),
        "慢速滴漏事务总耗时超出预期窗口：{elapsed_b:?}，err={err_b}"
    );
    assert!(
        err_b.contains("S socket 事务超时")
            && err_b.contains("等待回复/EOF")
            && !err_b.contains("已收 0 字节"),
        "慢速滴漏报错未指明根因：{err_b}"
    );

    // 1c) 真实 launcher + S/E/B 存活且 X 已非关键退出后，模拟写回一帧但不关闭 EOF 触发事务超时 panic，
    // 验证 Drop 在临时目录撤走前收口 launcher 及全部后代。
    let no_eof_sock = space.path("stalled-no-eof.sock");
    let listener = UnixListener::bind(&no_eof_sock).unwrap();
    let (tx_c, rx_c) = std::sync::mpsc::channel::<()>();
    let srv_c = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        let mut req = Vec::new();
        let _ = stream.read_to_end(&mut req);
        let _ = stream.write_all(b"{\"ok\":true}\n");
        let _ = rx_c.recv_timeout(Duration::from_secs(5));
    });
    let recorded: Arc<Mutex<Option<(u32, u32, u32, u32, u32, PathBuf, Instant)>>> =
        Arc::new(Mutex::new(None));
    let recorded_inner = Arc::clone(&recorded);
    let panic_res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let (s_db, mut launcher, obs) = start_non_history_bad_x_until_x_exit(&space);
        launcher.wait_until("S socket", Duration::from_secs(30), || {
            space.path("s.sock").exists()
        });
        launcher.wait_until("E socket", Duration::from_secs(30), || {
            space.path("e.sock").exists()
        });
        launcher.wait_until("B socket", Duration::from_secs(30), || {
            space.path("b.sock").exists()
        });
        let phase_start = Instant::now();
        *recorded_inner.lock().unwrap() = Some((
            launcher.id(),
            obs.s_pid,
            obs.e_pid,
            obs.b_pid,
            obs.x_pid,
            s_db,
            phase_start,
        ));
        try_s_ingest_bounded(&no_eof_sock, DECLARED_NS, 1, socket_cap)
            .unwrap_or_else(|e| panic!("反例1受控失败：{e}"));
    }));
    let _ = tx_c.send(());
    srv_c.join().unwrap();
    let panic_msg = panic_payload_text(panic_res.expect_err("不给 EOF 必须超时失败"));
    let (launcher_pid, s_pid, e_pid, b_pid, x_pid, s_db, phase_start) =
        recorded.lock().unwrap().take().expect("已记录运行 PID");
    let total_elapsed = phase_start.elapsed();
    assert!(
        panic_msg.contains("S socket 事务超时")
            && panic_msg.contains("等待回复/EOF")
            && panic_msg.contains("已收 12 字节"),
        "不给 EOF 报错未指明根因：{panic_msg}"
    );
    assert!(
        total_elapsed < Duration::from_secs(10),
        "事务超时与 launcher 清理总耗时过长：{total_elapsed:?}"
    );
    for pid in [launcher_pid, s_pid, e_pid, b_pid, x_pid] {
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "反例1清理后进程 {pid} 仍存活"
        );
    }
    assert!(
        owned_group_pids(launcher_pid).is_empty(),
        "反例1清理后进程组 {launcher_pid} 仍有残留"
    );
    for db in [s_db, space.path("e.db"), space.path("b.db")] {
        let lock_path = format!("{}.writer.lock", db.display());
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&lock_path)
            .unwrap();
        assert!(file.try_lock().is_ok(), "反例1清理后 {lock_path} 仍被占用");
    }
    eprintln!(
        "NEG1_EVIDENCE socket_cap_ms={} silent_ms={} trickle_ms={} no_eof_plus_cleanup_ms={} \
         pids=[launcher:{launcher_pid},S:{s_pid},E:{e_pid},B:{b_pid},X:{x_pid}] \
         remaining_group={:?} err={panic_msg}",
        socket_cap.as_millis(),
        elapsed_a.as_millis(),
        elapsed_b.as_millis(),
        total_elapsed.as_millis(),
        owned_group_pids(launcher_pid),
    );
}

/// 反例 2：拿到 X 非关键退出回执后刻意触发断言失败（模拟 generation 未推进等提前失败），
/// 验证 ManagedLauncher::drop 在临时目录撤走前优先正常停机并回收本测试 launcher 及全部后代。
#[test]
fn non_history_panic_after_x_exit_cleans_up_launcher_and_descendants() {
    let space = Space::new();
    let recorded: Arc<Mutex<Option<(u32, u32, u32, u32, u32, PathBuf, Instant)>>> =
        Arc::new(Mutex::new(None));
    let recorded_inner = Arc::clone(&recorded);
    let panic_res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let (s_db, mut launcher, obs) = start_non_history_bad_x_until_x_exit(&space);
        assert_eq!(obs.x_exit["critical"], json!(false));
        launcher.wait_until("S socket", Duration::from_secs(30), || {
            space.path("s.sock").exists()
        });
        launcher.wait_until("E socket", Duration::from_secs(30), || {
            space.path("e.sock").exists()
        });
        launcher.wait_until("B socket", Duration::from_secs(30), || {
            space.path("b.sock").exists()
        });
        let expected_kids = vec![
            ("b_chong_session".to_string(), obs.b_pid),
            ("e_economic_session".to_string(), obs.e_pid),
            ("s_structure_session".to_string(), obs.s_pid),
        ];
        assert_eq!(domain_children(launcher.id()), expected_kids);
        let panic_at = Instant::now();
        *recorded_inner.lock().unwrap() = Some((
            launcher.id(),
            obs.s_pid,
            obs.e_pid,
            obs.b_pid,
            obs.x_pid,
            s_db,
            panic_at,
        ));
        panic!("反例2受控失败：X 非关键退出回执后模拟 generation 未推进断言失败");
    }));
    let panic_msg = panic_payload_text(panic_res.expect_err("刻意失败必须触发 panic"));
    let (launcher_pid, s_pid, e_pid, b_pid, x_pid, s_db, panic_at) =
        recorded.lock().unwrap().take().expect("已记录运行 PID");
    let cleanup_elapsed = panic_at.elapsed();
    assert!(
        panic_msg.contains("反例2受控失败") && panic_msg.contains("generation 未推进"),
        "反例2报错未保留根因：{panic_msg}"
    );
    assert!(
        cleanup_elapsed < Duration::from_secs(15),
        "反例2清理超过正常停止上限 15s：{cleanup_elapsed:?}"
    );
    for pid in [launcher_pid, s_pid, e_pid, b_pid, x_pid] {
        assert!(
            !Path::new(&format!("/proc/{pid}")).exists(),
            "反例2清理后进程 {pid} 仍存活"
        );
    }
    assert!(
        owned_group_pids(launcher_pid).is_empty(),
        "反例2清理后进程组 {launcher_pid} 仍有残留"
    );
    for db in [s_db, space.path("e.db"), space.path("b.db")] {
        let lock_path = format!("{}.writer.lock", db.display());
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&lock_path)
            .unwrap();
        assert!(file.try_lock().is_ok(), "反例2清理后 {lock_path} 仍被占用");
    }
    eprintln!(
        "NEG2_EVIDENCE stop_grace_ms=15000 drain_cap_ms=5000 cleanup_ms={} \
         pids=[launcher:{launcher_pid},S:{s_pid},E:{e_pid},B:{b_pid},X:{x_pid}] \
         remaining_group={:?} err={panic_msg}",
        cleanup_elapsed.as_millis(),
        owned_group_pids(launcher_pid),
    );
}
