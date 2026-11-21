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
use std::fs::{File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::os::fd::{AsRawFd, FromRawFd};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::net::UnixStream;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Output, Stdio};
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
fn eventually(what: &str, mut ready: impl FnMut() -> bool) {
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

struct ForegroundLauncher {
    child: Child,
    master: File,
    kids: Vec<(String, u32)>,
    space: Space,
}

impl Drop for ForegroundLauncher {
    fn drop(&mut self) {
        if !matches!(self.child.try_wait(), Ok(None)) {
            return;
        }
        // 失败断言也让 launcher 回收自己的子进程：先排空 stderr，再唤醒可能暂停的 launcher。
        let pid = self.child.id() as libc::pid_t;
        if let Some(mut stderr) = self.child.stderr.take() {
            std::thread::spawn(move || std::io::copy(&mut stderr, &mut std::io::sink()));
        }
        unsafe {
            libc::kill(pid, libc::SIGTERM);
            libc::kill(pid, libc::SIGCONT);
        }
        let deadline = Instant::now() + Duration::from_secs(12);
        while Instant::now() < deadline {
            if self.child.try_wait().ok().flatten().is_some() {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        // launcher 自身失效时，直接杀其子 PID；各域已不一定与 launcher 同组。
        for (_, pid) in domain_children(self.child.id()) {
            unsafe { libc::kill(pid as libc::pid_t, libc::SIGKILL) };
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn spawn_foreground_launcher() -> ForegroundLauncher {
    spawn_foreground_configured(|_| {})
}

fn spawn_foreground_configured(configure: impl FnOnce(&mut Command)) -> ForegroundLauncher {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let mut launcher = start_foreground_launcher(space, &manifest, configure);
    launcher.kids = wait_domains(&mut launcher.child);
    for socket in ["s.sock", "e.sock", "b.sock"] {
        eventually(socket, || launcher.space.path(socket).exists());
    }
    eventually("X writer_epoch", || {
        meta(
            &launcher.space.path("x.db"),
            "SELECT value FROM x_meta WHERE key='writer_epoch'",
        )
        .as_deref()
            == Some("1")
    });
    launcher
}

fn start_foreground_launcher(
    space: Space,
    manifest: &Path,
    configure: impl FnOnce(&mut Command),
) -> ForegroundLauncher {
    start_foreground_launcher_at(space, manifest, Path::new(launcher_bin()), configure)
}

fn start_foreground_launcher_at(
    space: Space,
    manifest: &Path,
    bin: &Path,
    configure: impl FnOnce(&mut Command),
) -> ForegroundLauncher {
    let master = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(libc::O_NOCTTY)
        .open("/dev/ptmx")
        .unwrap();
    // SAFETY: master 是活的 PTY，TIOCGPTPEER 返回测试拥有的新 slave fd。
    let slave = unsafe {
        assert_eq!(libc::unlockpt(master.as_raw_fd()), 0);
        let fd = libc::ioctl(
            master.as_raw_fd(),
            libc::TIOCGPTPEER,
            libc::O_RDWR | libc::O_NOCTTY | libc::O_CLOEXEC,
        );
        assert!(fd >= 0, "{}", std::io::Error::last_os_error());
        File::from_raw_fd(fd)
    };
    let mut command = Command::new(bin);
    command
        .arg("--manifest")
        .arg(manifest)
        .env_remove(CREDENTIAL_KEY)
        .env_remove(THETA_DIAGNOSTIC.0)
        .stdin(slave)
        .stdout(Stdio::null())
        .stderr(Stdio::piped());
    // SAFETY: exec 前只用系统调用从新会话接管 stdin 对应的 PTY slave。
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() == -1 || libc::ioctl(0, libc::TIOCSCTTY, 0) == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    configure(&mut command);
    let launcher = ForegroundLauncher {
        child: command.spawn().unwrap(),
        master,
        kids: Vec::new(),
        space,
    };
    // SAFETY：验证真实 PTY 前台组与 VINTR 映射；Ctrl-C 测试不对 launcher PID 模拟 SIGINT。
    unsafe {
        let fd = launcher.master.as_raw_fd();
        assert_eq!(libc::tcgetpgrp(fd), launcher.child.id() as libc::pid_t);
        let mut attrs = std::mem::MaybeUninit::uninit();
        assert_eq!(libc::tcgetattr(fd, attrs.as_mut_ptr()), 0);
        let attrs = attrs.assume_init();
        assert_ne!(attrs.c_lflag & libc::ISIG, 0);
        assert_eq!(attrs.c_cc[libc::VINTR], 3);
    }
    launcher
}

fn signal(pid: u32, sig: libc::c_int) {
    // SAFETY：只向本测试启动的进程发送信号。
    assert_eq!(unsafe { libc::kill(pid as libc::pid_t, sig) }, 0);
}

fn proc_stat(pid: u32) -> Option<(char, Option<i32>)> {
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let mut fields = stat.rsplit_once(')')?.1.split_whitespace();
    let state = fields.next()?.chars().next()?;
    // stat 去掉 pid 和 comm 后，从 state（字段 3）到 exit_code（字段 52）。
    Some((state, fields.nth(48).and_then(|s| s.parse().ok())))
}

fn proc_signal_set(pid: u32, field: &str) -> Option<u64> {
    let status = std::fs::read_to_string(format!("/proc/{pid}/status")).ok()?;
    let value = status.lines().find_map(|line| line.strip_prefix(field))?;
    u64::from_str_radix(value.trim(), 16).ok()
}

fn signal_bit(sig: libc::c_int) -> u64 {
    1 << (sig - 1)
}

#[derive(Clone, Copy, Debug)]
enum ParentStop {
    CtrlC,
    Sigterm,
}

impl ParentStop {
    fn signal(self) -> libc::c_int {
        match self {
            Self::CtrlC => libc::SIGINT,
            Self::Sigterm => libc::SIGTERM,
        }
    }
}

impl ForegroundLauncher {
    fn domain_pid(&self, domain: &str) -> u32 {
        let exe = match domain {
            "S" => "s_structure_session",
            "E" => "e_economic_session",
            "B:one" => "b_chong_session",
            "X" => "x_execution_session",
            _ => unreachable!("{domain}"),
        };
        self.kids.iter().find(|(name, _)| name == exe).unwrap().1
    }

    fn request_stop(&mut self, stop: ParentStop) {
        match stop {
            ParentStop::CtrlC => self.master.write_all(&[3]).unwrap(),
            ParentStop::Sigterm => signal(self.child.id(), libc::SIGTERM),
        }
    }

    fn pause(&self) {
        let pid = self.child.id();
        signal(pid, libc::SIGSTOP);
        eventually("launcher 已暂停", || {
            proc_stat(pid).is_some_and(|(state, _)| state == 'T')
        });
    }

    fn stop_while_paused(&mut self, stop: ParentStop) {
        self.request_stop(stop);
        let pid = self.child.id();
        let sig = stop.signal();
        // PTY 写入与终端发送 SIGINT 不同步。确认进程级信号已挂起才恢复 launcher。
        eventually("停服信号已送达暂停的 launcher", || {
            proc_signal_set(pid, "ShdPnd:").is_some_and(|bits| bits & signal_bit(sig) != 0)
        });
        signal(pid, libc::SIGCONT);
    }

    fn crash_and_wait_for_zombie(&self, domain: &str, sig: libc::c_int) {
        let pid = self.domain_pid(domain);
        // E serve 有连接监听线程。leader 的 /proc 状态先变成 Z 时，waitpid 可能仍返回 0；
        // 进程级 pidfd 可读才表示整个线程组已退出，又不抢走 launcher 的等待状态。
        // SAFETY：pidfd_open 只观察本夹具的子域；返回的新 fd 归本测试。
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid as libc::pid_t, 0u32) };
        assert!(
            fd >= 0,
            "pidfd_open({pid}): {}",
            std::io::Error::last_os_error()
        );
        let pidfd = unsafe { File::from_raw_fd(fd as i32) };
        signal(pid, sig);
        eventually(
            &format!("{domain} 已按信号 {sig} 退出且组长可回收"),
            || {
                let mut poll = libc::pollfd {
                    fd: pidfd.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                };
                // SAFETY：poll 只读本测试持有的 pidfd，超时为 0。
                let ready = unsafe { libc::poll(&mut poll, 1, 0) };
                assert!(
                    ready >= 0,
                    "poll({pid}): {}",
                    std::io::Error::last_os_error()
                );
                ready == 1
                    && poll.revents & libc::POLLIN != 0
                    && proc_stat(pid) == Some(('Z', Some(sig)))
            },
        );
    }

    fn fill_stderr_pipe(&self) {
        let mut startup = Vec::new();
        let fd = self.child.stderr.as_ref().unwrap().as_raw_fd();
        // 重新打开 pipe，而不是改 launcher 写端的文件状态标志。
        let mut reader = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(format!("/proc/self/fd/{fd}"))
            .unwrap();
        eventually("X spawn 日志已输出", || {
            if let Err(e) = reader.read_to_end(&mut startup) {
                assert_eq!(e.kind(), ErrorKind::WouldBlock);
            }
            launcher_events(&String::from_utf8_lossy(&startup))
                .any(|e| e["event"] == "spawn" && e["domain"] == "X")
        });
        let mut writer = OpenOptions::new()
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(format!("/proc/{}/fd/2", self.child.id()))
            .unwrap();
        // 大写入耗尽空闲页；单字节写入填满最后的余量。
        for bytes in [&[b'\n'; 4096][..], b"\n"] {
            loop {
                match writer.write(bytes) {
                    Ok(n) => assert_eq!(n, bytes.len()),
                    Err(e) if e.kind() == ErrorKind::WouldBlock => break,
                    Err(e) => panic!("填充 stderr pipe：{e}"),
                }
            }
        }
    }

    fn assert_exit(mut self, label: &str, expected_exits: &[(&str, bool, libc::c_int)]) {
        self.assert_exit_within(label, expected_exits, Duration::from_secs(30));
    }

    fn assert_exit_within(
        &mut self,
        label: &str,
        expected_exits: &[(&str, bool, libc::c_int)],
        timeout: Duration,
    ) -> Vec<Value> {
        let (status, stderr) = self.finish(label, timeout);
        let stderr = stderr.trim_start_matches('\n'); // 去掉回归夹具注入的 pipe 填充。
        let events: Vec<_> = launcher_events(stderr).collect();
        let failed = expected_exits.iter().any(|&(_, critical, _)| critical);
        let code = i32::from(failed);
        assert_eq!(status.code(), Some(code), "{label}：{stderr}");
        assert_eq!(
            events
                .iter()
                .filter(|e| e["event"] == "stopped")
                .collect::<Vec<_>>(),
            vec![&json!({"event": "stopped", "failed": failed})],
            "{label}：{stderr}"
        );
        let exits: Vec<_> = events
            .iter()
            .filter(|e| e["event"] == "exit")
            .cloned()
            .collect();
        let expected: Vec<_> = expected_exits
            .iter()
            .map(|&(domain, critical, sig)| {
                json!({
                    "event": "exit", "domain": domain, "critical": critical,
                    "status": ExitStatus::from_raw(sig).to_string()
                })
            })
            .collect();
        assert_eq!(exits, expected, "{label}：{stderr}");
        println!("{label}: exit={code}, failed={failed}, exits={exits:?}, all children reaped");
        events
    }
    fn finish(&mut self, label: &str, timeout: Duration) -> (ExitStatus, String) {
        let mut stderr = self.child.stderr.take().unwrap();
        let reader = std::thread::spawn(move || {
            let mut buf = String::new();
            stderr.read_to_string(&mut buf).unwrap();
            buf
        });
        let deadline = Instant::now() + timeout;
        let status = loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                break status;
            }
            assert!(Instant::now() < deadline, "{label}：launcher 未退出");
            std::thread::sleep(Duration::from_millis(50));
        };
        // 先检查 PID，避免在失败臂中因仍有活域持有 stderr 而无限 join。
        let survivors: Vec<_> = self
            .kids
            .iter()
            .filter(|(_, pid)| proc_stat(*pid).is_some())
            .collect();
        for (_, pid) in &survivors {
            // SAFETY：只清理该夹具已登记的域组；包括失败对照泄漏的组。
            unsafe { libc::kill(-(*pid as libc::pid_t), libc::SIGKILL) };
        }
        assert!(survivors.is_empty(), "{label}：未回收 {survivors:?}");
        for (_, pid) in &self.kids {
            assert_group_gone(*pid, label);
        }
        (status, reader.join().unwrap())
    }
}

fn launcher_events(stderr: &str) -> impl Iterator<Item = Value> + '_ {
    stderr
        .split_inclusive('\n')
        .filter_map(|line| line.strip_suffix('\n')?.strip_prefix("production_session "))
        .map(|line| serde_json::from_str(line).unwrap())
}

#[test]
fn foreground_ctrl_c_stops_cleanly_but_critical_child_exit_fails() {
    for stop in [ParentStop::CtrlC, ParentStop::Sigterm] {
        let mut launcher = spawn_foreground_launcher();
        for (_, pid) in &launcher.kids {
            // SAFETY：各域是独立会话/进程组的组长，不接收终端的前台信号。
            unsafe {
                assert_eq!(libc::getsid(*pid as libc::pid_t), *pid as libc::pid_t);
                assert_eq!(libc::getpgid(*pid as libc::pid_t), *pid as libc::pid_t);
            }
        }
        launcher.request_stop(stop);
        launcher.assert_exit(&format!("{stop:?}"), &[]);
    }
    for domain in ["S", "E", "B:one"] {
        for sig in [libc::SIGINT, libc::SIGKILL] {
            let launcher = spawn_foreground_launcher();
            signal(launcher.domain_pid(domain), sig);
            launcher.assert_exit(&format!("{domain} 信号 {sig}"), &[(domain, true, sig)]);
        }
    }
}

#[test]
fn later_parent_stop_does_not_hide_child_sigint() {
    for (domain, critical, stop) in [
        ("E", true, ParentStop::CtrlC),
        ("E", true, ParentStop::Sigterm),
        ("X", false, ParentStop::CtrlC),
    ] {
        let mut launcher = spawn_foreground_launcher();
        launcher.pause();
        launcher.crash_and_wait_for_zombie(domain, libc::SIGINT);
        launcher.stop_while_paused(stop);
        launcher.assert_exit(
            &format!("{domain} 已因 SIGINT 退出 → {stop:?}"),
            &[(domain, critical, libc::SIGINT)],
        );
    }
}

#[test]
fn parent_stop_rechecks_domain_after_last_poll() {
    for stop in [ParentStop::Sigterm, ParentStop::CtrlC] {
        let mut launcher = spawn_foreground_launcher();
        launcher.fill_stderr_pipe();
        let x = launcher.domain_pid("X");
        signal(x, libc::SIGKILL);
        let pid = launcher.child.id();
        // X 排在 E 后面。X 已回收且 launcher 卡在写 X 的退出日志，固定在同一轮监督内。
        eventually("X 已回收，launcher 阻塞在 stderr 写入", || {
            !Path::new(&format!("/proc/{x}")).exists()
                && std::fs::read_to_string(format!("/proc/{pid}/wchan"))
                    .is_ok_and(|channel| channel.trim().ends_with("pipe_write"))
        });
        launcher.pause();
        launcher.crash_and_wait_for_zombie("E", libc::SIGKILL);
        launcher.stop_while_paused(stop);
        launcher.assert_exit(
            &format!("已检查 E → E 因 SIGKILL 退出 → {stop:?}"),
            &[("X", false, libc::SIGKILL), ("E", true, libc::SIGKILL)],
        );
    }
}

fn assert_group_gone(pgid: u32, label: &str) {
    // SAFETY：只探测测试启动的 PGID，不发送信号。
    assert_eq!(
        unsafe { libc::kill(-(pgid as libc::pid_t), 0) },
        -1,
        "{label}：进程组 {pgid} 仍存在"
    );
    assert_eq!(
        std::io::Error::last_os_error().raw_os_error(),
        Some(libc::ESRCH),
        "{label}：无法确认进程组 {pgid} 已消失"
    );
}

// 用系统调用入口停住真实 launcher；只有显式的等待失败臂注入错误。
#[cfg(target_env = "gnu")]
struct SyscallTrace(libc::pid_t);

#[cfg(target_env = "gnu")]
impl SyscallTrace {
    fn command(&self, op: libc::c_uint, addr: usize, data: usize) -> libc::c_long {
        // SAFETY：目标是本测试自己的 launcher；各操作的附加参数由调用方按 ptrace ABI 传入。
        let result = unsafe { libc::ptrace(op, self.0, addr, data) };
        assert_ne!(
            result,
            -1,
            "ptrace {op}: {}",
            std::io::Error::last_os_error()
        );
        result
    }

    fn wait_status(&self) -> libc::c_int {
        let mut status = 0;
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            // SAFETY：只等待本线程跟踪的进程。
            let got = unsafe { libc::waitpid(self.0, &mut status, libc::__WALL | libc::WNOHANG) };
            assert!(got >= 0, "ptrace wait: {}", std::io::Error::last_os_error());
            if got == self.0 {
                return status;
            }
            assert!(Instant::now() < deadline, "ptrace 未收到下一事件");
            std::thread::sleep(Duration::from_millis(1));
        }
    }

    fn wait_stop(&self) -> libc::c_int {
        let status = self.wait_status();
        assert!(
            libc::WIFSTOPPED(status),
            "launcher 提前退出，wait 状态 {status}"
        );
        libc::WSTOPSIG(status)
    }

    fn start(pid: u32) -> Self {
        let trace = Self(pid as libc::pid_t);
        trace.command(libc::PTRACE_SEIZE, 0, libc::PTRACE_O_TRACESYSGOOD as usize);
        trace.command(libc::PTRACE_INTERRUPT, 0, 0);
        assert_eq!(trace.wait_stop(), libc::SIGTRAP);
        trace
    }

    fn at_entry(&self, matches: impl FnMut(libc::c_long, [u64; 6]) -> bool) {
        self.at_entry_until(Duration::from_secs(10), matches);
    }

    fn at_entry_until(
        &self,
        timeout: Duration,
        mut matches: impl FnMut(libc::c_long, [u64; 6]) -> bool,
    ) {
        let mut deliver = 0;
        let deadline = Instant::now() + timeout;
        loop {
            assert!(Instant::now() < deadline, "未找到预期的系统调用入口");
            self.command(libc::PTRACE_SYSCALL, 0, deliver);
            let signal = self.wait_stop();
            if signal != (libc::SIGTRAP | 0x80) {
                assert!(
                    matches!(signal, libc::SIGTERM | libc::SIGCHLD),
                    "意外跟踪信号 {signal}"
                );
                deliver = signal as usize;
                continue;
            }
            deliver = 0;
            if let Some((nr, args)) = self.syscall_entry() {
                if matches(nr, args) {
                    return;
                }
            }
        }
    }

    fn syscall_entry(&self) -> Option<(libc::c_long, [u64; 6])> {
        // SAFETY：结构仅含数值和数值联合体；零初始化后由 ptrace 写入。
        let mut info: libc::ptrace_syscall_info = unsafe { std::mem::zeroed() };
        self.command(
            libc::PTRACE_GET_SYSCALL_INFO,
            std::mem::size_of_val(&info),
            &mut info as *mut _ as usize,
        );
        if info.op == libc::PTRACE_SYSCALL_INFO_ENTRY {
            // SAFETY：op 确认内核写入了 entry 成员。
            let entry = unsafe { info.u.entry };
            Some((entry.nr as libc::c_long, entry.args))
        } else {
            None
        }
    }

    /// 追到 launcher 退出；fork 臂在新子进程尚未运行时触发停服。
    fn domain_execs_before_launcher_exit(
        &self,
        mut stop_after_fork: Option<(&mut ForegroundLauncher, ParentStop)>,
        inherited_mask: u64,
    ) -> Vec<u32> {
        self.command(
            libc::PTRACE_SETOPTIONS,
            0,
            (libc::PTRACE_O_TRACESYSGOOD
                | libc::PTRACE_O_TRACEFORK
                | libc::PTRACE_O_TRACEVFORK
                | libc::PTRACE_O_TRACECLONE
                | libc::PTRACE_O_TRACEEXEC) as usize,
        );
        let mut executed = Vec::new();
        let mut deliver = 0;
        let stop_bits = signal_bit(libc::SIGTERM) | signal_bit(libc::SIGINT);
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            assert!(Instant::now() < deadline, "一次停服后 launcher 未退出");
            self.command(libc::PTRACE_SYSCALL, 0, deliver);
            let status = self.wait_status();
            assert!(
                libc::WIFSTOPPED(status),
                "launcher 未经过 exit_group：{status}"
            );
            let event = status >> 16;
            deliver = 0;
            if matches!(
                event,
                libc::PTRACE_EVENT_FORK | libc::PTRACE_EVENT_VFORK | libc::PTRACE_EVENT_CLONE
            ) {
                let mut pid = 0 as libc::c_ulong;
                self.command(libc::PTRACE_GETEVENTMSG, 0, &mut pid as *mut _ as usize);
                let child = Self(pid as libc::pid_t);
                child.wait_stop(); // 自动接管的新进程尚未运行。
                let stop = stop_after_fork.take().map(|(launcher, stop)| {
                    assert_eq!(
                        proc_signal_set(self.0 as u32, "SigBlk:").unwrap() & stop_bits,
                        stop_bits
                    );
                    let ctrl_c = matches!(stop, ParentStop::CtrlC);
                    if ctrl_c {
                        child.at_entry(|nr, _| nr == libc::SYS_setsid);
                        // SAFETY：跟踪停在 setsid 入口，内核尚未更改子进程的会话和组。
                        unsafe {
                            assert_eq!(libc::getpgid(child.0), self.0);
                            assert_eq!(libc::tcgetpgrp(launcher.master.as_raw_fd()), self.0);
                        }
                    }
                    launcher.request_stop(stop);
                    let pending = |pid| {
                        proc_signal_set(pid, "ShdPnd:")
                            .is_some_and(|bits| bits & signal_bit(stop.signal()) != 0)
                    };
                    eventually("停服信号已送达 launcher 与 PTY 前台组", || {
                        pending(self.0 as u32)
                            && (!ctrl_c
                                || pending(pid as u32)
                                || proc_signal_set(pid as u32, "SigBlk:")
                                    .is_some_and(|bits| bits & signal_bit(libc::SIGINT) == 0))
                    });
                    stop
                });
                child.command(libc::PTRACE_CONT, 0, 0);
                let mut status = child.wait_status();
                // 转交子进程收到的 INT，不能由夹具吞掉它（R6 会在 exec 前被杀）。
                if status >> 16 == 0
                    && libc::WIFSTOPPED(status)
                    && libc::WSTOPSIG(status) == libc::SIGINT
                {
                    child.command(libc::PTRACE_CONT, 0, libc::SIGINT as usize);
                    status = child.wait_status();
                }
                if libc::WIFSTOPPED(status) {
                    assert_eq!(
                        status >> 16,
                        libc::PTRACE_EVENT_EXEC,
                        "意外子进程事件 {status}"
                    );
                    executed.push(pid as u32);
                    if let Some(stop) = stop {
                        assert_ne!(
                            proc_signal_set(self.0 as u32, "ShdPnd:").unwrap()
                                & signal_bit(stop.signal()),
                            0,
                            "父进程在子进程 exec 前已处理停服"
                        );
                        assert_eq!(
                            proc_signal_set(pid as u32, "SigBlk:").unwrap() & stop_bits,
                            inherited_mask,
                            "子进程 exec 时应恢复原掩码"
                        );
                    }
                } else {
                    assert!(
                        libc::WIFEXITED(status)
                            || matches!(stop, Some(ParentStop::CtrlC)) && libc::WIFSIGNALED(status),
                        "被拒绝的 spawn 未正常向父进程报告 {status}"
                    );
                }
                // Drop 恢复子进程，正式 launcher 随后负责清理。
            } else if libc::WSTOPSIG(status) == (libc::SIGTRAP | 0x80) {
                if self
                    .syscall_entry()
                    .is_some_and(|(nr, _)| nr == libc::SYS_exit_group)
                {
                    assert!(stop_after_fork.is_none(), "未到达 fork 后的停服点");
                    return executed;
                }
            } else {
                deliver = libc::WSTOPSIG(status) as usize;
            }
        }
    }
}

#[cfg(target_env = "gnu")]
impl Drop for SyscallTrace {
    fn drop(&mut self) {
        // SAFETY：结束本测试的跟踪并恢复 launcher 正常执行。
        unsafe { libc::ptrace(libc::PTRACE_DETACH, self.0, 0usize, 0usize) };
    }
}

#[cfg(target_env = "gnu")]
#[test]
fn first_stop_syscall_cannot_hide_independent_domain_death() {
    for (domain, critical, fault) in [
        ("E", true, libc::SIGKILL),
        ("X", false, libc::SIGINT),
        ("E", true, libc::SIGTERM),
        ("X", false, libc::SIGTERM),
    ] {
        let mut launcher = spawn_foreground_launcher();
        let trace = SyscallTrace::start(launcher.child.id());
        trace.at_entry(|nr, _| matches!(nr, libc::SYS_clock_nanosleep | libc::SYS_nanosleep));
        launcher.request_stop(ParentStop::Sigterm);
        let s = launcher.domain_pid("S");
        trace.at_entry(|nr, args| {
            nr == libc::SYS_kill && args[0] as i32 == -(s as i32) && args[1] == libc::SIGTERM as u64
        });
        assert!(proc_stat(s).is_some_and(|(state, _)| state != 'Z'));
        launcher.crash_and_wait_for_zombie(domain, fault);
        assert!(proc_stat(s).is_some_and(|(state, _)| state != 'Z'));
        println!("{domain}：第一条给 S 的 SIGTERM 执行前，内核记录信号 {fault}");
        drop(trace); // 执行第一条 SIGTERM，随后真实回收。
        launcher.assert_exit(
            &format!("第一条 SIGTERM 前 {domain} 独立退出"),
            &[(domain, critical, fault)],
        );
    }
}

#[test]
fn inherited_sigchld_ignore_does_not_lose_exit_status() {
    let mut launcher = spawn_foreground_configured(|command| {
        // SAFETY：exec launcher 前只修改夹具子进程的 SIGCHLD disposition。
        unsafe {
            command.pre_exec(|| {
                if libc::signal(libc::SIGCHLD, libc::SIG_IGN) == libc::SIG_ERR {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
    });
    launcher.pause();
    launcher.crash_and_wait_for_zombie("E", libc::SIGKILL);
    launcher.stop_while_paused(ParentStop::Sigterm);
    launcher.assert_exit("继承 SIGCHLD=SIG_IGN", &[("E", true, libc::SIGKILL)]);
}

#[cfg(all(target_env = "gnu", target_arch = "x86_64"))]
#[test]
fn wait_error_does_not_leave_other_serving_groups_running() {
    let mut launcher = spawn_foreground_launcher();
    let trace = SyscallTrace::start(launcher.child.id());
    trace.at_entry(|nr, _| matches!(nr, libc::SYS_clock_nanosleep | libc::SYS_nanosleep));
    launcher.request_stop(ParentStop::Sigterm);
    let s = launcher.domain_pid("S");
    let mut calls = 0;
    trace.at_entry(|nr, args| {
        if nr == libc::SYS_wait4 && args[0] as u32 == s && args[2] as i32 == libc::WNOHANG {
            calls += 1;
        }
        calls == 2 // 首轮监督之后、停服检查 S 组长时，只注入一次等待错误。
    });
    trace.command(libc::PTRACE_SYSCALL, 0, 0);
    assert_eq!(trace.wait_stop(), libc::SIGTRAP | 0x80);
    // SAFETY：内核将填充本进程跟踪的 launcher 的 x86-64 寄存器；只替换一次 wait4 的返回值。
    let mut regs: libc::user_regs_struct = unsafe { std::mem::zeroed() };
    trace.command(libc::PTRACE_GETREGS, 0, &mut regs as *mut _ as usize);
    assert_eq!(regs.orig_rax as libc::c_long, libc::SYS_wait4);
    assert_eq!(regs.rax, 0, "S 原先应仍存活，注入不夺走真实退出状态");
    regs.rax = (-libc::EIO as i64) as u64;
    trace.command(libc::PTRACE_SETREGS, 0, &regs as *const _ as usize);
    drop(trace);
    let (status, stderr) = launcher.finish("一个组长等待失败仍停净四域", Duration::from_secs(5));
    assert_eq!(status.code(), Some(2), "{stderr}");
    assert!(
        stderr.contains("S：等待组长退出失败") && stderr.contains("os error 5"),
        "{stderr}"
    );
}

#[cfg(target_env = "gnu")]
#[test]
fn first_escalation_syscall_cannot_hide_independent_domain_death() {
    let mut launcher = spawn_foreground_launcher();
    for domain in ["S", "E"] {
        let pid = launcher.domain_pid(domain);
        signal(pid, libc::SIGSTOP);
        eventually(&format!("{domain} 全部线程已暂停"), || {
            proc_stat(pid).is_some_and(|(state, _)| state == 'T')
                && std::fs::read_dir(format!("/proc/{pid}/task"))
                    .unwrap()
                    .all(|task| {
                        let tid = task.unwrap().file_name().to_str().unwrap().parse().unwrap();
                        proc_stat(tid).is_some_and(|(state, _)| state == 'T')
                    })
        });
    }
    let trace = SyscallTrace::start(launcher.child.id());
    let s = launcher.domain_pid("S");
    launcher.request_stop(ParentStop::Sigterm);
    let started = Instant::now();
    trace.at_entry(|nr, args| {
        nr == libc::SYS_kill && args[0] as i32 == -(s as i32) && args[1] == libc::SIGTERM as u64
    });
    // 在第一条超时 KILL 的入口固定顺序，真实经过 10 秒宽限。
    trace.at_entry_until(Duration::from_secs(20), |nr, args| {
        nr == libc::SYS_kill && args[0] as i32 == -(s as i32) && args[1] == libc::SIGKILL as u64
    });
    assert!(started.elapsed() >= Duration::from_secs(10));
    assert_eq!(proc_stat(launcher.domain_pid("E")).unwrap().0, 'T');
    launcher.crash_and_wait_for_zombie("E", libc::SIGKILL);
    drop(trace);
    launcher.assert_exit(
        "先向 S 升级；E 已死于外部 KILL",
        &[("E", true, libc::SIGKILL)],
    );
}

fn fifo(path: &Path) {
    use std::os::unix::ffi::OsStrExt;
    let name = std::ffi::CString::new(path.as_os_str().as_bytes()).unwrap();
    // SAFETY：路径为私有 tempdir 内非空 C 字符串。
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
}

fn waiting_on_fifo(pid: u32) -> bool {
    std::fs::read_to_string(format!("/proc/{pid}/wchan"))
        .is_ok_and(|channel| channel.trim() == "wait_for_partner")
}

struct FifoHelper(u32);

impl Drop for FifoHelper {
    fn drop(&mut self) {
        if waiting_on_fifo(self.0) {
            // SAFETY：只清理由本测试启动、仍阻塞在 FIFO 上的 helper。
            unsafe { libc::kill(self.0 as libc::pid_t, libc::SIGKILL) };
        }
    }
}

fn start_with_e_helper(ignore_term: bool) -> (ForegroundLauncher, FifoHelper) {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    fifo(&space.path("stat-fifo"));
    let stat = space.path("stat");
    // 只替换真实 E serve 的文件系统检查；shell 自己阻塞，不再另起 FIFO 读者。
    std::fs::write(
        &stat,
        format!(
            r#"#!/bin/sh
case "$(tr '\000' ' ' < /proc/$PPID/cmdline)" in
  */e_economic_session\ serve\ *)
    {}
    printf '%s\n' "$$" > "${{0%/*}}/stat-pid"
    read -r blocked < "${{0%/*}}/stat-fifo"
    ;;
esac
exec /usr/bin/stat "$@"
"#,
            if ignore_term { "trap '' TERM" } else { ":" }
        ),
    )
    .unwrap();
    std::fs::set_permissions(&stat, std::fs::Permissions::from_mode(0o700)).unwrap();
    let path =
        std::env::join_paths([space.0.path(), Path::new("/usr/bin"), Path::new("/bin")]).unwrap();
    let mut launcher = start_foreground_launcher(space, &manifest, |command| {
        command.env("PATH", path);
    });
    launcher.kids = wait_domains(&mut launcher.child);
    let e = launcher.domain_pid("E");
    let mut helper = None;
    eventually("E serve 的 stat helper 阻塞在 FIFO", || {
        helper = std::fs::read_to_string(launcher.space.path("stat-pid"))
            .ok()
            .and_then(|s| s.trim().parse::<u32>().ok());
        helper.is_some_and(waiting_on_fifo)
    });
    let helper = FifoHelper(helper.unwrap());
    assert_eq!(ppid(helper.0), Some(e));
    // SAFETY：校验真实 helper 与 E 组长的所有权。
    unsafe {
        assert_eq!(libc::getsid(helper.0 as libc::pid_t), e as libc::pid_t);
        assert_eq!(libc::getpgid(helper.0 as libc::pid_t), e as libc::pid_t);
    }
    (launcher, helper)
}

#[test]
fn shutdown_drains_entire_domain_groups_even_after_leader_exit() {
    for stop in [ParentStop::CtrlC, ParentStop::Sigterm] {
        let (mut launcher, helper) = start_with_e_helper(false);
        launcher.request_stop(stop);
        launcher.assert_exit_within(
            &format!("{stop:?} 回收真实 E stat 同组孙进程"),
            &[],
            Duration::from_secs(5),
        );
        assert!(proc_stat(helper.0).is_none(), "helper {} 未回收", helper.0);
    }

    let (mut launcher, helper) = start_with_e_helper(true);
    let e = launcher.domain_pid("E");
    launcher.pause();
    launcher.crash_and_wait_for_zombie("E", libc::SIGKILL);
    assert!(waiting_on_fifo(helper.0), "E 已退后 helper 仍应存活");
    let started = Instant::now();
    launcher.stop_while_paused(ParentStop::Sigterm);
    eventually("组长被回收且 helper 已由 launcher 接养", || {
        proc_stat(e).is_none() && ppid(helper.0) == Some(launcher.child.id())
    });
    assert!(waiting_on_fifo(helper.0), "忽略 TERM 的 helper 未等到宽限");
    launcher.assert_exit("E 已回收、仍有同组 helper", &[("E", true, libc::SIGKILL)]);
    assert!(
        started.elapsed() >= Duration::from_secs(10),
        "没有保留 10 秒宽限"
    );
    assert!(
        proc_stat(helper.0).is_none(),
        "宽限后 helper {} 未回收",
        helper.0
    );
    println!(
        "已先回收 E；同组 helper 经 {:.3}s 后强杀并回收",
        started.elapsed().as_secs_f64()
    );
}

#[test]
fn paused_domain_gets_full_stop_grace() {
    let mut launcher = spawn_foreground_launcher();
    let e = launcher.domain_pid("E");
    signal(e, libc::SIGSTOP);
    eventually("E 已暂停", || {
        proc_stat(e).is_some_and(|(state, _)| state == 'T')
    });
    let started = Instant::now();
    launcher.request_stop(ParentStop::Sigterm);
    launcher.assert_exit("launcher 宽限后强杀暂停的 E", &[]);
    assert!(
        started.elapsed() >= Duration::from_secs(10),
        "暂停的 E 被过早强杀"
    );
    println!("暂停的 E 得到 {:.3}s 宽限", started.elapsed().as_secs_f64());
}

#[test]
fn stop_cancels_real_blocked_init_before_starting_other_domains() {
    for (stop, paused) in [
        (ParentStop::CtrlC, false),
        (ParentStop::Sigterm, false),
        (ParentStop::Sigterm, true),
    ] {
        let space = Space::new();
        let (manifest, _) = simulation(&space, "simulation", false);
        let blocked = space.path("blocked-e-manifest");
        fifo(&blocked);
        let mut value: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
        value["economic"]["manifest"] = json!(blocked);
        write_json(&manifest, &value);
        let mut launcher = start_foreground_launcher(space, &manifest, |_| {});
        let mut e = None;
        eventually("真实 E init 阻塞在 manifest FIFO", || {
            e = domain_children(launcher.child.id())
                .into_iter()
                .find(|(name, pid)| name == "e_economic_session" && waiting_on_fifo(*pid));
            e.is_some()
        });
        let (_, pid) = e.unwrap();
        let cmdline = std::fs::read(format!("/proc/{pid}/cmdline")).unwrap();
        assert_eq!(cmdline.split(|&b| b == 0).nth(1), Some(&b"init"[..]));
        // SAFETY：确认 init 与已经验证的 PTY 前台组隔离。
        assert_eq!(
            unsafe { libc::getsid(pid as libc::pid_t) },
            pid as libc::pid_t
        );
        launcher.kids.push(("E init".into(), pid));
        if paused {
            signal(pid, libc::SIGSTOP);
            eventually("E init 已暂停", || {
                proc_stat(pid).is_some_and(|(state, _)| state == 'T')
            });
        }
        let b_db = launcher.space.path("b.db");
        let x_db = launcher.space.path("x.db");
        let started = Instant::now();
        launcher.request_stop(stop);
        let events = launcher.assert_exit_within(
            &format!("{stop:?} 取消卡在 FIFO 的 E init（暂停={paused}）"),
            &[],
            Duration::from_secs(3),
        );
        assert!(events
            .iter()
            .all(|e| e["event"] != "spawn" && e["event"] != "init"));
        assert!(!b_db.exists() && !x_db.exists(), "启动了后续域");
        println!(
            "{stop:?}：{:.3}s 回收 E init 进程组，没有后续 init 或 serve",
            started.elapsed().as_secs_f64()
        );
    }
}

fn isolated_launcher_with_e_wrapper(space: &Space, wrapper: &str) -> PathBuf {
    let bins = space.path("bin");
    std::fs::create_dir(&bins).unwrap();
    for (name, source) in [
        ("s_structure_session", s_bin()),
        ("e-real", env!("CARGO_BIN_EXE_e_economic_session")),
        ("b_chong_session", env!("CARGO_BIN_EXE_b_chong_session")),
        ("x_execution_session", x_bin()),
    ] {
        std::os::unix::fs::symlink(source, bins.join(name)).unwrap();
    }
    let launcher = bins.join("production_session");
    std::fs::copy(launcher_bin(), &launcher).unwrap();
    let e = bins.join("e_economic_session");
    std::fs::write(&e, wrapper).unwrap();
    std::fs::set_permissions(e, std::fs::Permissions::from_mode(0o700)).unwrap();
    launcher
}

/// 大管道加父进程暂停：E 退出时整段 stderr 都仍在管道中，不能靠边写边读让旧实现碰巧通过。
#[test]
fn failed_init_retains_all_buffered_stderr_without_waiting_for_eof() {
    for retain_writer in [false, true] {
        let space = Space::new();
        let (manifest, _) = simulation(&space, "simulation", false);
        fifo(&space.path("write-diagnostic"));
        let bin = isolated_launcher_with_e_wrapper(
            &space,
            r#"#!/usr/bin/python3
import fcntl, os, sys
from pathlib import Path
assert sys.argv[1] == 'init'
home = Path(__file__).parent.parent
data = b'START-DIAG ' + b'x' * 524288 + b' END-DIAG-TAG\n'
assert fcntl.fcntl(2, fcntl.F_SETPIPE_SZ, 1048576) >= len(data)
(home / 'e-init-pid').write_text(f'{os.getpid()}\n')
with open(home / 'write-diagnostic', 'rb', buffering=0) as barrier:
    assert barrier.read(1) == b'1'
os.write(1, b'OUT-CONTROL-ONLY\n')
assert os.write(2, data) == len(data)
sys.exit(7)
"#,
        );
        let mut launcher = start_foreground_launcher_at(space, &manifest, &bin, |_| {});
        let mut e = None;
        eventually("E init 已扩大 stderr 管道并等待写入", || {
            e = std::fs::read_to_string(launcher.space.path("e-init-pid"))
                .ok()
                .and_then(|s| s.trim().parse::<u32>().ok())
                .filter(|&pid| waiting_on_fifo(pid));
            e.is_some()
        });
        let e = e.unwrap();
        launcher.kids.push(("E init".into(), e));
        let extra_writer = retain_writer.then(|| {
            OpenOptions::new()
                .write(true)
                .open(format!("/proc/{e}/fd/2"))
                .unwrap()
        });
        launcher.pause();
        OpenOptions::new()
            .write(true)
            .custom_flags(libc::O_NONBLOCK)
            .open(launcher.space.path("write-diagnostic"))
            .unwrap()
            .write_all(b"1")
            .unwrap();
        eventually("524,313 字节已入管道，E init 以 7 退出", || {
            proc_stat(e) == Some(('Z', Some(7 << 8)))
        });
        signal(launcher.child.id(), libc::SIGCONT);

        let (status, stderr) = launcher.finish("正常 init 失败", Duration::from_secs(4));
        assert_eq!(status.code(), Some(2));
        let summary = stderr
            .lines()
            .find(|line| line.starts_with("START-DIAG "))
            .unwrap();
        let body = summary
            .strip_prefix("START-DIAG ")
            .unwrap()
            .strip_suffix(" END-DIAG-TAG（E init 失败，exit status: 7）")
            .expect("长 stderr 的尾标记或退出状态丢失");
        assert_eq!(body.len(), 524288);
        assert!(body.bytes().all(|b| b == b'x'));
        assert!(!stderr.contains("OUT-CONTROL-ONLY"));
        drop(extra_writer);
        assert!(!launcher.space.path("b.db").exists() && !launcher.space.path("x.db").exists());
    }
}

#[test]
fn successful_real_e_init_starts_all_domains_with_stderr_writer_open() {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let barrier = space.path("exec-e-init");
    fifo(&barrier);
    let bin = isolated_launcher_with_e_wrapper(
        &space,
        r#"#!/usr/bin/python3
import os, sys
from pathlib import Path
here = Path(__file__).parent
if sys.argv[1] == 'init':
    with open(here.parent / 'exec-e-init', 'rb', buffering=0) as barrier:
        assert barrier.read(1) == b'1'
real = str(here / 'e-real')
os.execv(real, sys.argv)
"#,
    );
    let mut launcher = start_foreground_launcher_at(space, &manifest, &bin, |_| {});
    let mut e = None;
    eventually("E init 包装器等待 exec", || {
        e = domain_children(launcher.child.id())
            .into_iter()
            .find_map(|(_, pid)| waiting_on_fifo(pid).then_some(pid));
        e.is_some()
    });
    let e = e.unwrap();
    let extra_writer = OpenOptions::new()
        .write(true)
        .open(format!("/proc/{e}/fd/2"))
        .unwrap();
    OpenOptions::new()
        .write(true)
        .custom_flags(libc::O_NONBLOCK)
        .open(barrier)
        .unwrap()
        .write_all(b"1")
        .unwrap();
    launcher.kids = wait_domains(&mut launcher.child);
    for socket in ["s.sock", "e.sock", "b.sock"] {
        eventually(socket, || launcher.space.path(socket).exists());
    }
    assert_lock_held(&launcher.space.path("x.db"));
    assert!(proc_stat(e).is_none(), "E init 未回收");
    launcher.request_stop(ParentStop::Sigterm);
    let events = launcher.assert_exit_within("外部 stderr 写端仍打开", &[], Duration::from_secs(5));
    for domain in ["E", "B"] {
        assert!(events
            .iter()
            .any(|e| e["event"] == "init" && e["domain"] == domain));
    }
    drop(extra_writer);
}

#[test]
fn graceful_domain_exit_zero_after_launcher_term_is_clean() {
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let bin = isolated_launcher_with_e_wrapper(
        &space,
        r#"#!/usr/bin/python3
import os, signal, sys
from pathlib import Path
here = Path(__file__).parent
real = here / 'e-real'
if sys.argv[1] != 'serve':
    os.execv(real, [str(real), *sys.argv[1:]])
mask = {signal.SIGTERM}
signal.pthread_sigmask(signal.SIG_BLOCK, mask)
(here / 'ready').touch()
sender = signal.sigwaitinfo(mask).si_pid
(here / 'term-sender').write_text(str(sender))
"#,
    );
    let mut launcher = start_foreground_launcher_at(space, &manifest, &bin, |_| {});
    eventually("E 等待 TERM 且四域均启动", || {
        launcher.kids = domain_children(launcher.child.id());
        launcher.kids.len() == 4 && launcher.space.path("bin/ready").exists()
    });
    launcher.request_stop(ParentStop::Sigterm);
    launcher.assert_exit_within(
        "E 收到 launcher TERM 后主动返回 0",
        &[],
        Duration::from_secs(5),
    );
    assert_eq!(
        std::fs::read_to_string(launcher.space.path("bin/term-sender")).unwrap(),
        launcher.child.id().to_string()
    );
}

#[test]
fn cancelled_init_reaps_adopted_children_without_requiring_pipe_eof() {
    for own_group in [false, true] {
        let space = Space::new();
        let (manifest, _) = simulation(&space, "simulation", false);
        let blocked = space.path("blocked-e-manifest");
        let blocked_helper = space.path("blocked-helper");
        fifo(&blocked);
        fifo(&blocked_helper);
        let mut value: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
        value["economic"]["manifest"] = json!(blocked);
        write_json(&manifest, &value);
        let wrapper = r#"#!/usr/bin/python3
import os, signal, sys
from pathlib import Path
here = Path(__file__).parent
if sys.argv[1] == 'init' and os.fork() == 0:
    if OWN_GROUP:
        os.setpgid(0, 0)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (here / 'helper-pid').write_text(str(os.getpid()))
    os.open(here.parent / 'blocked-helper', os.O_RDONLY)
    os._exit(0)
real = here / 'e-real'
os.execv(real, [str(real), *sys.argv[1:]])
"#
        .replace("OWN_GROUP", if own_group { "True" } else { "False" });
        let bin = isolated_launcher_with_e_wrapper(&space, &wrapper);
        let mut launcher = start_foreground_launcher_at(space, &manifest, &bin, |_| {});
        let mut helper = None;
        eventually("继承 stderr 的 init 孙进程已阻塞", || {
            helper = std::fs::read_to_string(launcher.space.path("bin/helper-pid"))
                .ok()
                .and_then(|s| s.parse::<u32>().ok())
                .filter(|&pid| waiting_on_fifo(pid));
            helper.is_some()
        });
        let helper = FifoHelper(helper.unwrap());
        let e = ppid(helper.0).unwrap();
        eventually("真实 E init 已阻塞", || waiting_on_fifo(e));
        assert_eq!(ppid(e), Some(launcher.child.id()));
        let helper_pid = helper.0 as libc::pid_t;
        // SAFETY：只读夹具孙进程的组与会话身份。
        unsafe {
            assert_eq!(libc::getsid(helper_pid), e as libc::pid_t);
            assert_eq!(
                libc::getpgid(helper_pid),
                if own_group {
                    helper_pid
                } else {
                    e as libc::pid_t
                }
            );
        }
        let fd = format!("/proc/{helper_pid}/fd/2");
        assert!(std::fs::read_link(&fd)
            .unwrap()
            .to_string_lossy()
            .starts_with("pipe:"));
        // 另保留一个 launcher 管辖范围外的写端，证明直到最后也不需要 EOF。
        let extra_writer = OpenOptions::new().write(true).open(fd).unwrap();
        launcher.kids.push(("E init".into(), e));
        let start = Instant::now();
        launcher.request_stop(ParentStop::Sigterm);
        let events = launcher.assert_exit_within(
            &format!("取消 init（独立 PGID={own_group}）"),
            &[],
            Duration::from_secs(4),
        );
        assert!(start.elapsed() >= Duration::from_secs(1));
        assert!(proc_stat(helper.0).is_none(), "同会话被接养孙进程未回收");
        assert!(events
            .iter()
            .all(|e| e["event"] != "spawn" && e["event"] != "init"));
        assert!(!launcher.space.path("b.db").exists() && !launcher.space.path("x.db").exists());
        drop(extra_writer);
    }
}

#[cfg(target_env = "gnu")]
fn assert_stop_at_spawn_boundary(
    next: &str,
    point: &str,
    inherit_term_block: bool,
    stop: ParentStop,
) {
    let after_fork = point == "after-fork";
    let space = Space::new();
    let (manifest, _) = simulation(&space, "simulation", false);
    let mut value: Value = serde_json::from_slice(&std::fs::read(&manifest).unwrap()).unwrap();
    let econ = value["economic"]["manifest"].as_str().unwrap().to_owned();
    let barrier = space.path("launch-barrier");
    fifo(&barrier);
    let (input, manifest) = if next == "B init" {
        value["economic"]["manifest"] = json!(barrier);
        write_json(&manifest, &value);
        (std::fs::read(&econ).unwrap(), manifest)
    } else {
        run(
            Command::new(env!("CARGO_BIN_EXE_e_economic_session")).args([
                "init",
                "--manifest",
                &econ,
                "--db",
                value["economic"]["e"]["db"].as_str().unwrap(),
            ]),
        );
        let b = &value["economic"]["b"][0];
        run(Command::new(env!("CARGO_BIN_EXE_b_chong_session")).args([
            "init",
            "--manifest",
            &econ,
            "--db",
            b["db"].as_str().unwrap(),
            "--chong",
            b["chong"].as_str().unwrap(),
        ]));
        (serde_json::to_vec(&value).unwrap(), barrier.clone())
    };
    let mut launcher = start_foreground_launcher(space, &manifest, |command| {
        if inherit_term_block {
            // SAFETY：只在测试启动器的 fork 后、exec 前，修改子进程掩码。
            unsafe {
                command.pre_exec(|| {
                    let mut mask: libc::sigset_t = std::mem::zeroed();
                    libc::sigemptyset(&mut mask);
                    libc::sigaddset(&mut mask, libc::SIGTERM);
                    if libc::sigprocmask(libc::SIG_BLOCK, &mask, std::ptr::null_mut()) == -1 {
                        return Err(std::io::Error::last_os_error());
                    }
                    Ok(())
                });
            }
        }
    });
    let pid = launcher.child.id();
    let mut waiting = None;
    eventually("下一启动前的 FIFO 屏障", || {
        waiting = if next == "B init" {
            domain_children(pid).iter().find_map(|(exe, child)| {
                (exe == "e_economic_session" && waiting_on_fifo(*child)).then_some(*child)
            })
        } else {
            waiting_on_fifo(pid).then_some(pid)
        };
        waiting.is_some()
    });
    let trace = SyscallTrace::start(pid);
    // ptrace 可以让 launcher 的 FIFO open 重启；写者与跟踪并行，且等待有上限。
    std::thread::scope(|scope| {
        scope.spawn(move || {
            eventually("FIFO 已有读者", || {
                match OpenOptions::new()
                    .write(true)
                    .custom_flags(libc::O_NONBLOCK)
                    .open(&barrier)
                {
                    Ok(mut pipe) => {
                        pipe.write_all(&input).unwrap();
                        true
                    }
                    Err(e) if e.raw_os_error() == Some(libc::ENXIO) => false,
                    Err(e) => panic!("打开启动屏障：{e}"),
                }
            });
        });
        trace.at_entry(|nr, args| {
            if point == "before-mask" {
                nr == libc::SYS_rt_sigprocmask && args[0] as i32 == libc::SIG_BLOCK
            } else {
                nr == libc::SYS_rt_sigpending
            }
        });
    });
    if !after_fork {
        launcher.request_stop(stop);
    }
    let executed = trace.domain_execs_before_launcher_exit(
        after_fork.then_some((&mut launcher, stop)),
        if inherit_term_block {
            signal_bit(libc::SIGTERM)
        } else {
            0
        },
    );
    drop(trace);
    let label = format!("{next}（{point}，{stop:?}，继承屏蔽 TERM={inherit_term_block}）");
    let exec_count = executed.len();
    launcher
        .kids
        .extend(executed.into_iter().map(|pid| (next.into(), pid)));
    let events = launcher.assert_exit_within(&label, &[], Duration::from_secs(5));
    assert_eq!(exec_count, usize::from(after_fork), "{label}");
    let spawns: Vec<_> = events.iter().filter(|e| e["event"] == "spawn").collect();
    assert_eq!(
        spawns.len(),
        usize::from(after_fork && next == "S serve"),
        "{label}"
    );
    if let Some(spawn) = spawns.first() {
        assert_eq!(spawn["domain"], "S");
    }
}

#[cfg(target_env = "gnu")]
#[test]
fn stop_at_spawn_boundary_skips_or_reaps_b_init_and_s_serve() {
    for next in ["B init", "S serve"] {
        for point in ["before-mask", "pending-at-gate", "after-fork"] {
            assert_stop_at_spawn_boundary(next, point, false, ParentStop::Sigterm);
        }
    }
}

#[cfg(target_env = "gnu")]
#[test]
fn foreground_ctrl_c_during_s_fork_before_setsid_is_clean() {
    assert_stop_at_spawn_boundary("S serve", "after-fork", false, ParentStop::CtrlC);
}

#[cfg(target_env = "gnu")]
#[test]
fn inherited_term_mask_stops_before_first_domain() {
    assert_stop_at_spawn_boundary("S serve", "pending-at-gate", true, ParentStop::Sigterm);
}

#[cfg(target_env = "gnu")]
#[test]
fn inherited_term_mask_stops_with_s_in_flight() {
    assert_stop_at_spawn_boundary("S serve", "after-fork", true, ParentStop::Sigterm);
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

/// #1407 C3 R3：非历史模拟 `/1` 装配恢复父版行为：
/// 1. 坏非历史 X `profile_revision` 仍由非关键 X 自行拒绝退出，S/E/B 照常启动存活；
/// 2. launcher 不在 `load_manifest` 预读 `economic.manifest`，未给正常非历史配置新增前置依赖。
#[test]
fn non_history_preserves_parent_startup_and_x_degradation() {
    // 1) 非历史配置 + 坏 X revision：S/E/B 正常启动，X 作为非关键进程自行拒绝，launcher 不提前整组退出。
    let space = Space::new();
    let source = declaration("TestOnlyStructure", DECLARED_NS);
    let s_db = s_init_v3(&space, Some(&source));
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
    let manifest = launcher_manifest(&space, "simulation", &source, &s_db, &limits, &bad_xp);
    let mut launcher = spawn_launcher(&manifest);
    eventually("S socket", || space.path("s.sock").exists());
    eventually("E socket", || space.path("e.sock").exists());
    eventually("B socket", || space.path("b.sock").exists());
    eventually("X 非关键退出后仅 S/E/B 存活", || {
        let names: Vec<String> = domain_children(launcher.id())
            .into_iter()
            .map(|(n, _)| n)
            .collect();
        names.iter().any(|n| n == "s_structure_session")
            && names.iter().any(|n| n == "e_economic_session")
            && names.iter().any(|n| n == "b_chong_session")
            && !names.iter().any(|n| n == "x_execution_session")
    });
    assert!(
        launcher.try_wait().unwrap().is_none(),
        "坏非历史 X 不应导致整组 launcher 提前退出"
    );
    assert_eq!(stop(&mut launcher).code(), Some(0));
    let stderr = launcher_stderr(&mut launcher);
    assert!(
        stderr.contains("VersionUnsupported"),
        "X 应报 VersionUnsupported：{stderr}"
    );
    assert!(
        stderr.contains("\"domain\":\"X\"") && stderr.contains("\"critical\":false"),
        "launcher 应记录非关键 X 退出：{stderr}"
    );

    // 2) 非历史配置 + 缺失 economic.manifest：load_manifest 不预读 E 配置，先建 state_dir 再由 E init 报错。
    let space2 = Space::new();
    let source2 = declaration("TestOnlyStructure", DECLARED_NS);
    let s_db2 = s_init_v3(&space2, Some(&source2));
    let limits2 = anchor(&s_db2);
    let xp2 = x_profile(&space2, "simulation", None, Some("tb09-sentinel"), false);
    let manifest2 = launcher_manifest(&space2, "simulation", &source2, &s_db2, &limits2, &xp2);
    std::fs::remove_file(space2.path("economic.json")).unwrap();
    let out = run_refusal(
        Command::new(launcher_bin())
            .arg("--manifest")
            .arg(&manifest2),
    );
    assert!(!out.status.success());
    assert!(
        space2.path("launcher-state").is_dir(),
        "非历史配置不应在 load_manifest 预读 economic.manifest"
    );
}
