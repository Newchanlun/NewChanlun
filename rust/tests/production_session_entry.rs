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
use std::io::{Read, Write};
use std::os::unix::fs::{symlink, FileTypeExt, MetadataExt, PermissionsExt};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Output, Stdio};
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

/// 期望「拒绝启动」的命令：限时等待退出。门失效时 S/launcher 会进入服务循环不退出，
/// 此处超时即杀掉 launcher 及其域子进程并判红，不吃满 job 超时。
#[cfg_attr(feature = "production_session_testonly", allow(dead_code))]
fn run_refusal(cmd: &mut Command) -> Output {
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut stdout = child.stdout.take().unwrap();
    let mut stderr = child.stderr.take().unwrap();
    let out_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.read_to_end(&mut buf);
        buf
    });
    let err_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stderr.read_to_end(&mut buf);
        buf
    });
    let deadline = Instant::now() + Duration::from_secs(60);
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break status;
        }
        if Instant::now() >= deadline {
            for (_, pid) in domain_children(child.id()) {
                unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) };
            }
            let _ = child.kill();
            let _ = child.wait();
            panic!("拒启门失效：进程 60s 内未退出（应以拒绝退出），已杀掉");
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    Output {
        status,
        stdout: out_reader.join().unwrap(),
        stderr: err_reader.join().unwrap(),
    }
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
    let out = run(&mut c);
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
    anchor_in(&db, &state, max_total_wire_bytes)
}

fn anchor_in(db: &Path, state: &Path, max_total_wire_bytes: u64) -> PathBuf {
    let db = db.canonicalize().unwrap();
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

fn ppid(pid: u32) -> Option<u32> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    stat.rsplit_once(')')?
        .1
        .split_whitespace()
        .nth(1)?
        .parse()
        .ok()
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

/// 经 S socket 提交第 `n` 条 ingest（`s-session/3` 封包、`s-ohlc/1` 原件；一帧 LF + 写端 EOF）。
fn s_ingest(socket: &Path, ns: &str, n: u32) -> Value {
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
    let mut stream = UnixStream::connect(socket).unwrap();
    stream
        .write_all(
            format!(
                "{}\n",
                newchan_rust::session_protocol::canonical_json(&envelope)
            )
            .as_bytes(),
        )
        .unwrap();
    stream.shutdown(std::net::Shutdown::Write).unwrap();
    let mut reply = String::new();
    stream.read_to_string(&mut reply).unwrap();
    serde_json::from_str(reply.trim_end()).unwrap()
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

// ADR 0059：拒启夹具不预先 init；正控用真实 launcher 和已签 synthetic S 配置，两档 feature 共跑。
struct LayoutFixture {
    space: Space,
    manifest: PathBuf,
    launcher: Value,
    economic: Value,
}

impl LayoutFixture {
    fn new() -> Self {
        Self::with_layout(true, false)
    }

    fn with_layout(separate: bool, init_s: bool) -> Self {
        let space = Space::new();
        let source = declaration("TestOnlyStructure", DECLARED_NS);
        let p = space.path("s");
        let a = if separate {
            space.path("admission")
        } else {
            p.join("s-state")
        };
        let db = if init_s {
            s_init_v3(&space, Some(&source))
        } else {
            space.s_db()
        };
        let limits = if init_s {
            anchor_in(&db, &a, 1_073_741_824)
        } else {
            std::fs::create_dir_all(&a).unwrap();
            a.join("s-admission/limits.json")
        };
        let xp = x_profile(&space, "simulation", None, Some("tb09-sentinel"), false);
        let manifest = launcher_manifest(&space, "simulation", &source, &db, &limits, &xp);
        let launcher: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
        let economic =
            serde_json::from_slice(&std::fs::read(space.path("economic.json")).unwrap()).unwrap();
        let mut fixture = Self {
            space,
            manifest,
            launcher,
            economic,
        };
        if separate {
            for domain in ["e", "b", "x"] {
                fixture.dir(domain);
            }
            fixture.e_db(&fixture.path("e/e.db"));
            fixture.b_db(&fixture.path("b/b.db"));
            fixture.launcher["x"]["db"] = json!(fixture.path("x/x.db"));
            fixture.economic["e"]["socket"] = json!(fixture.path("e/e.sock"));
            fixture.economic["chongs"][0]["socket"] = json!(fixture.path("b/b.sock"));
        }
        fixture
    }

    fn path(&self, rel: &str) -> PathBuf {
        self.space.path(rel)
    }

    fn dir(&self, rel: &str) -> PathBuf {
        let path = self.path(rel);
        std::fs::create_dir_all(&path).unwrap();
        path
    }

    fn e_db(&mut self, db: &Path) {
        self.launcher["economic"]["e"]["db"] = json!(db);
        self.economic["e"]["db"] = json!(db);
    }

    fn b_db(&mut self, db: &Path) {
        self.launcher["economic"]["b"][0]["db"] = json!(db);
        self.economic["chongs"][0]["db"] = json!(db);
    }

    fn write_manifests(&self) {
        write_json(&self.manifest, &self.launcher);
        write_json(&self.path("economic.json"), &self.economic);
    }

    fn assert_refused(&self) -> String {
        // 递归比对整份场地（包含 P、A、域目录和 launcher state_dir），不跟随软链。
        // 这样也会查到夹具中预置的悬空链接目标被创建，或原有条目被移走。
        fn entries(dir: &Path) -> Vec<PathBuf> {
            let mut paths = Vec::new();
            for entry in std::fs::read_dir(dir).unwrap() {
                let entry = entry.unwrap();
                let path = entry.path();
                if entry.file_type().unwrap().is_dir() {
                    paths.extend(entries(&path));
                }
                paths.push(path);
            }
            paths.sort_unstable();
            paths
        }

        let before = entries(self.space.0.path());
        let out = run_refusal(
            Command::new(launcher_bin())
                .arg("--manifest")
                .arg(&self.manifest)
                .env_remove(THETA_DIAGNOSTIC.0),
        );
        let stderr = String::from_utf8(out.stderr).unwrap();
        assert_eq!(out.status.code(), Some(2), "{stderr}");
        assert!(!stderr.contains("\"event\":\"start\""), "{stderr}");
        assert_eq!(entries(self.space.0.path()), before, "{stderr}");
        stderr
    }

    fn assert_conflict(&self, field: &str, q: &Path, source: &str, member: &Path) {
        self.write_manifests();
        let stderr = self.assert_refused();
        let expected =
            format!("InvalidDomain：{field} 的判定目录 {q:?} 命中 {source} 的测量域 {member:?}");
        assert!(stderr.lines().any(|line| line == expected), "{stderr}");
    }

    fn assert_listens(&self) {
        self.write_manifests();
        let mut launcher = spawn_launcher(&self.manifest);
        let sockets = [
            &self.launcher["s"]["socket"],
            &self.economic["e"]["socket"],
            &self.economic["chongs"][0]["socket"],
        ]
        .map(|v| Path::new(v.as_str().unwrap()));
        let x_db = Path::new(self.launcher["x"]["db"].as_str().unwrap());
        let deadline = Instant::now() + Duration::from_secs(30);
        let ready = loop {
            if let Some(status) = launcher.try_wait().unwrap() {
                panic!(
                    "launcher 提前退出 {status}：{}",
                    launcher_stderr(&mut launcher)
                );
            }
            if sockets.iter().all(|p| {
                std::fs::symlink_metadata(p).is_ok_and(|meta| meta.file_type().is_socket())
            }) && domain_children(launcher.id())
                .iter()
                .any(|(name, _)| name == "x_execution_session")
                && meta(x_db, "SELECT value FROM x_meta WHERE key='writer_epoch'").as_deref()
                    == Some("1")
            {
                break true;
            }
            if Instant::now() >= deadline {
                break false;
            }
            std::thread::sleep(Duration::from_millis(50));
        };
        let status = stop(&mut launcher);
        let stderr = launcher_stderr(&mut launcher);
        assert!(ready, "S/E/B socket 或 X epoch 未就绪：{stderr}");
        assert_eq!(status.code(), Some(0), "{stderr}");
    }
}

#[test]
fn layout_rejects_e_db_in_s_db_parent() {
    let mut f = LayoutFixture::new();
    f.e_db(&f.path("s/e.db"));
    f.assert_conflict("economic.e.db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_b_db_in_s_db_parent() {
    let mut f = LayoutFixture::new();
    f.b_db(&f.path("s/b.db"));
    f.assert_conflict("economic.b[0].db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_x_db_in_s_db_parent() {
    let mut f = LayoutFixture::new();
    f.launcher["x"]["db"] = json!(f.path("s/x.db"));
    f.assert_conflict("x.db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_e_db_under_admission_state() {
    let mut f = LayoutFixture::new();
    f.launcher["s"]["admission_job_limits"] = json!(f.path("s/s-admission/limits.json"));
    let q = f.dir("s/e");
    f.e_db(&q.join("e.db"));
    f.assert_conflict("economic.e.db", &q, "s.admission_job_limits", &f.path("s"));
}

#[test]
fn layout_rejects_e_db_under_separate_admission_state() {
    let mut f = LayoutFixture::new();
    let q = f.dir("admission/e");
    f.e_db(&q.join("e.db"));
    f.assert_conflict(
        "economic.e.db",
        &q,
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_rejects_e_db_under_s_family_entry() {
    let mut f = LayoutFixture::new();
    let q = f.dir("s/s.db.admission-private/e");
    f.e_db(&q.join("e.db"));
    f.assert_conflict(
        "economic.e.db",
        &q,
        "s.db",
        &f.path("s/s.db.admission-private"),
    );
}

#[test]
fn layout_rejects_symlink_alias_of_s_parent() {
    let mut f = LayoutFixture::new();
    symlink(f.path("s"), f.path("linked-s")).unwrap();
    f.e_db(&f.path("linked-s/e.db"));
    f.assert_conflict("economic.e.db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_resolves_not_yet_existing_db_dirs() {
    let mut f = LayoutFixture::new();
    symlink(f.path("admission"), f.path("linked-a")).unwrap();
    f.e_db(&f.path("linked-a/new/e.db"));
    f.assert_conflict(
        "economic.e.db",
        &f.path("admission/new"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_rejects_x_db_file_symlink_into_s_parent() {
    let mut f = LayoutFixture::new();
    std::fs::File::create(f.path("s/x.db")).unwrap();
    symlink(f.path("s/x.db"), f.path("x/alias.db")).unwrap();
    f.launcher["x"]["db"] = json!(f.path("x/alias.db"));
    f.assert_conflict("x.db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_e_db_dangling_symlink_into_admission_state() {
    let mut f = LayoutFixture::new();
    // 相对目标跨两跳：每跳都从该链接的父目录解析。
    symlink("../admission/e.db", f.path("b/next.db")).unwrap();
    symlink("../b/next.db", f.path("e/alias.db")).unwrap();
    f.e_db(&f.path("e/alias.db"));
    f.assert_conflict(
        "economic.e.db",
        &f.path("admission"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_rejects_writer_lock_symlink_into_s_parent() {
    let f = LayoutFixture::new();
    std::fs::File::create(f.path("x/x.db")).unwrap();
    symlink(f.path("s/x-external-lock"), f.path("x/x.db.writer.lock")).unwrap();
    f.assert_conflict("x.db", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_absent_db_writer_lock_symlink_into_admission_state() {
    let mut f = LayoutFixture::new();
    let e_real = f.dir("e-real");
    symlink(e_real.join("e.db"), f.path("e/alias.db")).unwrap();
    symlink(
        f.path("admission/e-external-lock"),
        f.path("e/alias.db.writer.lock"),
    )
    .unwrap();
    f.e_db(&f.path("e/alias.db"));
    f.assert_conflict(
        "economic.e.db",
        &f.path("admission"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_rejects_e_socket_in_s_parent() {
    let mut f = LayoutFixture::new();
    f.economic["e"]["socket"] = json!(f.path("s/e.sock"));
    f.assert_conflict("e.socket", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_b_socket_under_admission_state() {
    let mut f = LayoutFixture::new();
    f.economic["chongs"][0]["socket"] = json!(f.path("admission/b.sock"));
    f.assert_conflict(
        "chongs[0].socket",
        &f.path("admission"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_rejects_e_socket_under_s_family_entry() {
    let mut f = LayoutFixture::new();
    let q = f.dir("s/s.db.admission-private");
    f.economic["e"]["socket"] = json!(q.join("e.sock"));
    f.assert_conflict("e.socket", &q, "s.db", &q);
}

#[test]
fn layout_rejects_b_socket_parent_symlink_into_s_parent() {
    let mut f = LayoutFixture::new();
    symlink(f.path("s"), f.path("b/run")).unwrap();
    f.economic["chongs"][0]["socket"] = json!(f.path("b/run/b.sock"));
    f.assert_conflict("chongs[0].socket", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_e_socket_final_dangling_symlink_into_s_parent() {
    let mut f = LayoutFixture::new();
    let run = f.dir("e-run");
    let alias = run.join("alias.sock");
    symlink(f.path("s/e.sock"), &alias).unwrap();
    f.economic["e"]["socket"] = json!(alias);
    f.assert_conflict("e.socket", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_b_socket_final_dangling_symlink_into_admission_state() {
    let mut f = LayoutFixture::new();
    let run = f.dir("b-run");
    let alias = run.join("alias.sock");
    symlink(f.path("admission/b.sock"), &alias).unwrap();
    f.economic["chongs"][0]["socket"] = json!(alias);
    f.assert_conflict(
        "chongs[0].socket",
        &f.path("admission"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_accepts_db_file_symlink_between_safe_dirs() {
    let mut f = LayoutFixture::with_layout(true, true);
    let db = f.dir("x-real").join("x.db");
    std::fs::File::create(&db).unwrap();
    symlink(&db, f.path("x/alias.db")).unwrap();
    // 库已存在：只走 L2，词法文件名派生的 L1 不会被打开。
    let unused = f.path("s/unused-lock");
    symlink(&unused, f.path("x/alias.db.writer.lock")).unwrap();
    f.launcher["x"]["db"] = json!(f.path("x/alias.db"));
    f.assert_listens();
    assert!(!unused.exists());
}

#[test]
fn layout_accepts_sockets_in_non_family_subdir_of_s_parent() {
    let mut f = LayoutFixture::with_layout(true, true);
    let run = f.dir("s/run");
    f.economic["e"]["socket"] = json!(run.join("e.sock"));
    f.economic["chongs"][0]["socket"] = json!(run.join("b.sock"));
    f.assert_listens();
}

#[test]
fn layout_allows_s_socket_in_s_parent() {
    let mut f = LayoutFixture::with_layout(true, true);
    f.launcher["s"]["socket"] = json!(f.path("s/s.sock"));
    f.assert_listens();
}

#[test]
fn layout_accepts_db_in_non_family_subdir_of_s_parent() {
    let mut f = LayoutFixture::with_layout(true, true);
    // 用相同前缀但下一字节不是点或连字符的名字，锁住 S 族的精确边界。
    let q = f.dir("s/s.dbwork");
    f.e_db(&q.join("e.db"));
    f.assert_listens();
}

#[test]
fn layout_accepts_original_fixture_layout() {
    LayoutFixture::with_layout(false, true).assert_listens();
}

#[test]
fn layout_accepts_separate_directories() {
    LayoutFixture::with_layout(true, true).assert_listens();
}

#[test]
fn layout_allows_launcher_state_dir_equal_s_parent() {
    let mut f = LayoutFixture::with_layout(true, true);
    f.launcher["state_dir"] = json!(f.path("s"));
    f.assert_listens();
    assert!(f.path("s/structure-source.json").is_file());
}

#[test]
fn layout_rejects_absent_db_future_writer_lock() {
    let mut f = LayoutFixture::new();
    let db = f.dir("e-real").join("e.db");
    symlink(db, f.path("e/alias.db")).unwrap();
    symlink(
        f.path("admission/e-external-lock"),
        f.path("e-real/e.db.writer.lock"),
    )
    .unwrap();
    f.e_db(&f.path("e/alias.db"));
    f.assert_conflict(
        "economic.e.db",
        &f.path("admission"),
        "s.admission_job_limits",
        &f.path("admission"),
    );
}

#[test]
fn layout_uses_actual_s_db_parent_and_basename() {
    let mut f = LayoutFixture::new();
    symlink(f.path("s/real.db"), f.path("s-alias.db")).unwrap();
    f.launcher["s"]["db"] = json!(f.path("s-alias.db"));
    let q = f.dir("s/real.db-private");
    f.e_db(&q.join("e.db"));
    f.assert_conflict("economic.e.db", &q, "s.db", &q);
}

#[test]
fn layout_rejects_symlink_loops_before_start() {
    let mut f = LayoutFixture::new();
    symlink("second", f.path("e/first")).unwrap();
    symlink("first", f.path("e/second")).unwrap();
    for rel in ["e/first", "e/first/e.db"] {
        f.e_db(&f.path(rel));
        f.write_manifests();
        assert!(f
            .assert_refused()
            .contains("InvalidDomain：economic.e.db 路径"));
    }
}

#[test]
fn layout_reads_b_socket_by_chong_identity() {
    let mut f = LayoutFixture::new();
    let mut extra = f.economic["chongs"][0].clone();
    extra["chong_id"] = json!("two");
    extra["operation_level"] = json!("2");
    extra["db"] = json!(f.path("b/two.db"));
    extra["socket"] = json!(f.path("b/two.sock"));
    f.economic["chongs"]
        .as_array_mut()
        .unwrap()
        .insert(0, extra);
    f.economic["chongs"][1]["socket"] = json!(f.path("s/b.sock"));
    f.assert_conflict("chongs[1].socket", &f.path("s"), "s.db", &f.path("s"));
}

#[test]
fn layout_rejects_unreadable_or_incomplete_economic_manifest() {
    let mut f = LayoutFixture::new();
    let econ = f.path("economic.json");
    f.launcher["economic"]["manifest"] = json!(f.path("absent.json"));
    f.write_manifests();
    assert!(f
        .assert_refused()
        .contains("InvalidDomain：读经济 manifest"));

    f.launcher["economic"]["manifest"] = json!(econ);
    f.write_manifests();
    std::fs::write(&econ, "{").unwrap();
    assert!(f
        .assert_refused()
        .contains("InvalidDomain：经济 manifest JSON"));

    let valid = f.economic.clone();
    for (field, path) in [
        ("e.socket", "/e/socket"),
        ("chongs[0].socket", "/chongs/0/socket"),
        ("economic.b[0].chong", "/chongs/0/chong_id"),
    ] {
        *f.economic.pointer_mut(path).unwrap() = Value::Null;
        f.write_manifests();
        let stderr = f.assert_refused();
        assert!(
            stderr.contains("InvalidDomain") && stderr.contains(field),
            "{stderr}"
        );
        f.economic = valid.clone();
    }
}
