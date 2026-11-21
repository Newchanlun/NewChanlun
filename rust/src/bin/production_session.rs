//! #1769（ADR 0039 迁移步骤 1）：唯一生产 launcher 可运行骨架。
//!
//! 职责只有编排：校验 manifest（含结构源声明）→ 必要时 init 各域库 → 以独立进程拉起
//! S、E、每个 Bᵢ、X → 监督 → 收到 SIGTERM/SIGINT 时回收全部子进程。各域进程自持库、
//! `<db>.writer.lock` 与 `writer_epoch`；launcher 不打开任何域库，不放宽其锁/epoch/隔离。
//!
//! - 结构源违规（类别不在封闭集合、namespace 与执行能力 manifest 相交）在拉起 S 之前以
//!   `InvalidDomain` 退出，S 库文件不创建；既有 S 库由 S 持锁自核声明，失败按 critical exit 回收会话。
//! - 凭据按 X 执行 profile 的 `credential_scope` 读文件，只注入 X 子进程环境；S/E/B 子进程
//!   以清空的环境启动，launcher 自身环境不写入凭据。
//! - X 退出只记录，不停 S/E/B；S/E/B 任一退出视为会话失败，回收其余进程后非 0 退出。
//! - 日志经 `redact`（移植 `381fda3f` `trading_system/execution/hl_paper_launcher.py:46-53`
//!   `_redact`）过滤后写 stderr。
//!
//! 用法：production_session --manifest FILE
use newchan_rust::structure_source::Declaration;
use serde_json::{json, Value};
use std::collections::BTreeSet;
use std::io::{self, Read};
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

const MANIFEST_REVISION: &str = "production-session-manifest/1";
const PROFILES: [&str; 4] = ["simulation", "dry-run", "experiment", "production"];
const STOP_GRACE: Duration = Duration::from_secs(10);
const INIT_STOP_GRACE: Duration = Duration::from_secs(1);
const STOP_POLL: Duration = Duration::from_millis(50);
/// S 子进程从 launcher 环境放回的 admission 声明变量；凭据不在其中。
#[cfg(not(feature = "production_session_testonly"))]
const S_PASS: [&str; 2] = ["S_CONTROL_ADMISSION_SHA256", "S_CONTROL_ADMISSION_IDENTITY"];
/// #1769 TestOnly 构建：额外转交 S 的诊断 theta 开关；生产构建不转交（S 侧亦拒绝）。
#[cfg(feature = "production_session_testonly")]
const S_PASS: [&str; 3] = [
    "S_CONTROL_ADMISSION_SHA256",
    "S_CONTROL_ADMISSION_IDENTITY",
    "S_THETA_DIAGNOSTIC_TESTONLY",
];

static STOP_REQUESTED: AtomicBool = AtomicBool::new(false);

extern "C" fn on_stop(_: libc::c_int) {
    STOP_REQUESTED.store(true, Ordering::Relaxed);
}

/// 与 `_redact` 同口径：敏感键名的值整体遮蔽；24 位以上纯 token 字符的字符串遮蔽。
fn redact(value: &Value) -> Value {
    fn secret_key(key: &str) -> bool {
        let k: String = key
            .chars()
            .filter(|c| c.is_ascii_alphanumeric())
            .collect::<String>()
            .to_ascii_lowercase();
        let raw = key.to_ascii_lowercase();
        [
            "privatekey",
            "secret",
            "password",
            "token",
            "credential",
            "apikey",
        ]
        .iter()
        .any(|w| k.contains(w) || raw.contains(w))
            && !key.ends_with("_env")
    }
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| {
                    let v = if secret_key(k) {
                        json!("[REDACTED]")
                    } else {
                        redact(v)
                    };
                    (k.clone(), v)
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(redact).collect()),
        Value::String(s)
            if s.len() >= 24
                && s.chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') =>
        {
            json!("[REDACTED]")
        }
        other => other.clone(),
    }
}

fn log(event: &str, fields: Value) {
    let mut line = json!({"event": event});
    if let (Value::Object(target), Value::Object(extra)) = (&mut line, fields) {
        target.extend(extra);
    }
    eprintln!("production_session {}", redact(&line));
}

fn text<'a>(v: &'a Value, path: &str) -> Result<&'a str, String> {
    let mut node = v;
    for part in path.split('.') {
        node = &node[part];
    }
    node.as_str()
        .filter(|s| !s.is_empty())
        .ok_or_else(|| format!("InvalidDomain：manifest 缺 {path}"))
}

fn read_json(path: &Path, what: &str) -> Result<Value, String> {
    let raw = std::fs::read_to_string(path)
        .map_err(|e| format!("InvalidDomain：读{what} {} 失败：{e}", path.display()))?;
    serde_json::from_str(&raw).map_err(|e| format!("InvalidDomain：{what} JSON 解析失败：{e}"))
}

struct Manifest {
    raw: Value,
    profile: String,
    state_dir: PathBuf,
    source: Declaration,
    x_profile: PathBuf,
    credential: Option<(String, String)>,
}

/// 完整校验 manifest；此阶段不创建任何域文件。
fn load_manifest(path: &Path) -> Result<Manifest, String> {
    let raw = read_json(path, "manifest")?;
    if raw["manifest_revision"].as_str() != Some(MANIFEST_REVISION) {
        return Err(format!(
            "VersionUnsupported：manifest_revision 必须是 {MANIFEST_REVISION}"
        ));
    }
    let profile = text(&raw, "profile")?.to_string();
    if !PROFILES.contains(&profile.as_str()) {
        return Err(format!("InvalidDomain：未知运行 profile `{profile}`"));
    }
    let source = Declaration::parse(&raw["structure_source"])?;
    let execution: BTreeSet<String> = raw["execution_capabilities"]["namespaces"]
        .as_array()
        .ok_or("InvalidDomain：manifest 缺 execution_capabilities.namespaces")?
        .iter()
        .map(|v| {
            v.as_str()
                .map(str::to_string)
                .ok_or("InvalidDomain：执行能力 namespace 必须是字符串".to_string())
        })
        .collect::<Result<_, _>>()?;
    source.check_disjoint_from_execution(&execution)?;
    for key in [
        "s.db",
        "s.session",
        "s.catalog",
        "s.profile",
        "s.clock_plan",
        "s.session_generation",
        "s.delivery_retain_generations",
        "s.admission_job_limits",
        "s.writer_epoch",
        "s.socket",
        "s.resource_config",
        "economic.manifest",
        "economic.e.db",
        "economic.e.epoch",
        "x.db",
        "x.profile",
        "x.writer_epoch",
    ] {
        text(&raw, key)?;
    }
    let chongs = raw["economic"]["b"]
        .as_array()
        .filter(|b| !b.is_empty())
        .ok_or("InvalidDomain：manifest economic.b 至少一个 B")?;
    for b in chongs {
        for key in ["chong", "db", "epoch"] {
            text(b, key)?;
        }
    }
    let x_profile = PathBuf::from(text(&raw, "x.profile")?);
    let xp = read_json(&x_profile, "X 执行 profile")?;
    if xp["mode"].as_str() != Some(profile.as_str()) {
        return Err(format!(
            "InvalidDomain：X 执行 profile mode `{}` 与运行 profile `{profile}` 不一致",
            xp["mode"]
        ));
    }
    if xp.get("history_simulation").is_some_and(|v| !v.is_null()) {
        check_history_simulation_assembly(
            &profile,
            &xp,
            Path::new(text(&raw, "economic.manifest")?),
        )?;
    }
    let credential_env = text(&xp, "credential_scope.env")?.to_string();
    // 凭据文件缺失不在此判错：是否必需由 X 按 profile 裁决（MissingDependency）。
    let credential = xp["credential_scope"]["file"]
        .as_str()
        .and_then(|f| std::fs::read_to_string(f).ok())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .map(|value| (credential_env, value));
    Ok(Manifest {
        state_dir: PathBuf::from(text(&raw, "state_dir")?),
        raw,
        profile,
        source,
        x_profile,
        credential,
    })
}

/// #1407 C3 R3：仅当 `x.profile` 显式声明 `history_simulation` 时，在创建任何状态目录、
/// 初始化或拉起任何域库前读取经济域 manifest 并拒绝不兼容的 E/X 历史模拟装配。
/// 非历史模拟配置（`/1` 骨架、dry-run、experiment、production，含坏非历史 X revision）
/// 不预读经济域 manifest、不改变原启动条件与非关键 X 降级行为。
fn check_history_simulation_assembly(
    profile: &str,
    xp: &Value,
    econ_path: &Path,
) -> Result<(), String> {
    if profile != "simulation" {
        return Err("InvalidDomain：history_simulation 仅允许 simulation profile".into());
    }
    let x_rev = xp["profile_revision"].as_str().unwrap_or_default();
    let expected_x = newchan_rust::history_simulation::EXACT_PROFILE_REVISION;
    if x_rev != expected_x {
        return Err(format!(
            "VersionUnsupported：历史模拟 X 执行 profile 版本 `{x_rev}` 已退场或不兼容，\
             正式装配必须使用 {expected_x} 搭配 tb03b-finance/6 新开会话（旧 /1、/2 历史模拟库仅保留只读取证）"
        ));
    }
    let econ = read_json(econ_path, "经济域 manifest")?;
    let finance_rev = econ
        .get("finance")
        .filter(|v| !v.is_null())
        .and_then(|f| f.get("schema_revision"))
        .and_then(Value::as_str);
    if finance_rev != Some("tb03b-finance/6") {
        return Err(format!(
            "VersionUnsupported：历史模拟装配拒绝将 E 财务子合同 `{}` 与 {expected_x} 混配\
             （tb03b-finance/5 命令不含实装模型内容摘要，无法通过 /3 核验；\
             请在新会话显式升级为 tb03b-finance/6 + {expected_x}，原 /5 收据、责任与查询保持原义）",
            finance_rev.unwrap_or("<none>")
        ));
    }
    Ok(())
}

fn sibling(name: &str) -> Result<PathBuf, String> {
    let exe = std::env::current_exe().map_err(|e| format!("MissingDependency：{e}"))?;
    let path = exe
        .parent()
        .ok_or("MissingDependency：launcher 无父目录")?
        .join(name);
    if path.is_file() {
        Ok(path)
    } else {
        Err(format!("MissingDependency：缺域进程 {}", path.display()))
    }
}

/// 清空环境后只放回 PATH 与显式白名单；凭据不在任何白名单里。
fn clean(mut command: Command, pass: &[&str]) -> Command {
    command.env_clear();
    for key in std::iter::once("PATH").chain(pass.iter().copied()) {
        if let Some(value) = std::env::var_os(key) {
            command.env(key, value);
        }
    }
    command.stdin(Stdio::null());
    // SAFETY：exec 前只调用 setsid；域进程不共享前台 Ctrl-C 或后台终端作业控制。
    unsafe {
        command.pre_exec(|| {
            if libc::setsid() == -1 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }
    command
}

fn shutdown_requested() -> bool {
    STOP_REQUESTED.load(Ordering::Relaxed)
}

/// 接养组长退出后遗留的组内后代；Linux 上不能假设外部 PID 1 会回收它们。
#[cfg(target_os = "linux")]
fn adopt_orphans() -> io::Result<()> {
    // SAFETY：只设置当前 launcher 的子收养者属性。
    if unsafe { libc::prctl(libc::PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) } == -1 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum StopPhase {
    NotSignaled,
    TermSent,
    KillSent,
}

impl StopPhase {
    fn explains(self, status: ExitStatus) -> bool {
        match self {
            Self::NotSignaled => false,
            Self::TermSent => status.success() || status.signal() == Some(libc::SIGTERM),
            Self::KillSent => {
                status.success() || matches!(status.signal(), Some(libc::SIGTERM | libc::SIGKILL))
            }
        }
    }
}

#[derive(Clone, Copy)]
enum StopSignal {
    Term,
    Kill,
}

struct DomainProcess {
    domain: String,
    leader: Child,
    status: Option<ExitStatus>,
    // Some 只用于常驻域；init 的退出由 run_once 处理。
    critical: Option<bool>,
    phase: StopPhase,
    group_gone: bool,
}

impl DomainProcess {
    fn new(domain: String, leader: Child, critical: Option<bool>) -> Self {
        Self {
            domain,
            leader,
            status: None,
            critical,
            phase: StopPhase::NotSignaled,
            group_gone: false,
        }
    }

    fn pgid(&self) -> libc::pid_t {
        // setsid 成功后 SID == PGID == 组长 PID，组长退出后仍用这个组号回收。
        self.leader.id() as libc::pid_t
    }

    /// 返回且保存首次取得的组长状态。组长状态和组是否已消失是两件事。
    fn poll_leader(&mut self) -> io::Result<Option<ExitStatus>> {
        if self.status.is_some() {
            return Ok(None);
        }
        self.status = self.leader.try_wait()?;
        Ok(self.status)
    }

    fn probe_or_signal_group(&mut self, signal: libc::c_int) -> io::Result<bool> {
        if !self.group_gone {
            // SAFETY：只探测或通知本 launcher 通过 setsid 建立的进程组。
            if unsafe { libc::kill(-self.pgid(), signal) } == -1 {
                let error = io::Error::last_os_error();
                if error.raw_os_error() != Some(libc::ESRCH) {
                    return Err(error);
                }
                self.group_gone = true;
            }
        }
        Ok(!self.group_gone)
    }

    fn signal(&mut self, signal: StopSignal) -> io::Result<()> {
        let (raw, phase) = match signal {
            StopSignal::Term => (libc::SIGTERM, StopPhase::TermSent),
            StopSignal::Kill => (libc::SIGKILL, StopPhase::KillSent),
        };
        if self.probe_or_signal_group(raw)? {
            self.phase = phase;
        }
        Ok(())
    }

    fn fully_reaped(&mut self) -> io::Result<bool> {
        if self.status.is_none() {
            return Ok(false);
        }
        if !self.group_gone {
            #[cfg(target_os = "linux")]
            self.reap_adopted()?;
            self.probe_or_signal_group(0)?;
        }
        Ok(self.group_gone)
    }

    #[cfg(target_os = "linux")]
    fn reap_adopted(&self) -> io::Result<()> {
        loop {
            // SAFETY：组长已由 Child 回收；这里只等同 PGID 下被接养的后代，不取其他域的状态。
            match unsafe { libc::waitpid(-self.pgid(), std::ptr::null_mut(), libc::WNOHANG) } {
                0 => return Ok(()),
                n if n > 0 => continue,
                _ => {
                    let error = io::Error::last_os_error();
                    match error.raw_os_error() {
                        Some(libc::ECHILD) => return Ok(()),
                        Some(libc::EINTR) => continue,
                        _ => return Err(error),
                    }
                }
            }
        }
    }
}

struct GroupPoll {
    failed: bool,
    all_reaped: bool,
}

/// 监督、停服前和回收时走同一个出口；已登记的状态不重算。
fn poll_groups(children: &mut [DomainProcess]) -> Result<GroupPoll, String> {
    let mut result = GroupPoll {
        failed: false,
        all_reaped: true,
    };
    for child in children {
        let status = child
            .poll_leader()
            .map_err(|e| format!("{}：等待组长退出失败：{e}", child.domain))?;
        // X 可能很早退出；持续回收并记下组已消失，不在很久以后再用旧 PGID 发信号。
        result.all_reaped &= child
            .fully_reaped()
            .map_err(|e| format!("{}：进程组回收失败：{e}", child.domain))?;
        if let (Some(status), Some(critical)) = (status, child.critical) {
            if !child.phase.explains(status) {
                log(
                    "exit",
                    json!({"domain": child.domain, "status": status.to_string(), "critical": critical}),
                );
                result.failed |= critical;
            }
        }
    }
    Ok(result)
}

fn stop_groups(children: &mut [DomainProcess], grace: Duration) -> Result<bool, String> {
    let signal_all = |children: &mut [DomainProcess], signal| {
        for child in children {
            child
                .signal(signal)
                .map_err(|e| format!("{}：进程组停服信号失败：{e}", child.domain))?;
        }
        Ok::<_, String>(())
    };
    // 保留已经可取得的退出状态，但不依赖这次补查与发信号之间没有竞态。
    let mut failed = poll_groups(children)?.failed;
    signal_all(children, StopSignal::Term)?;
    let deadline = Instant::now() + grace;
    let mut escalated = false;
    loop {
        let poll = poll_groups(children)?;
        failed |= poll.failed;
        if poll.all_reaped {
            return Ok(failed);
        }
        if !escalated && Instant::now() >= deadline {
            signal_all(children, StopSignal::Kill)?;
            escalated = true;
        }
        std::thread::sleep(STOP_POLL);
    }
}

/// 返回 false 表示停服已取消启动。两条管道在等待和停服期间都持续排空。
fn run_once(mut command: Command, what: &str) -> Result<bool, String> {
    if shutdown_requested() {
        return Ok(false);
    }
    let mut leader = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("MissingDependency：{what} 启动失败：{e}"))?;
    let mut stdout = leader.stdout.take().expect("init stdout 已配置管道");
    let mut stderr = leader.stderr.take().expect("init stderr 已配置管道");
    let mut child = DomainProcess::new(what.into(), leader, None);
    std::thread::scope(|scope| {
        let stdout = scope.spawn(move || io::copy(&mut stdout, &mut io::sink()));
        let stderr = scope.spawn(move || {
            let mut bytes = Vec::new();
            stderr.read_to_end(&mut bytes).map(|_| bytes)
        });
        let finished = loop {
            if shutdown_requested() {
                break Ok(None);
            }
            match child.poll_leader() {
                Ok(None) => std::thread::sleep(STOP_POLL),
                result => break result,
            }
        };
        // 正常结束也要收尾；组长退出不保证所有继承管道的后代都退出了。
        stop_groups(std::slice::from_mut(&mut child), INIT_STOP_GRACE)?;
        let read_error = |e| format!("StorageUnavailable：读取 {what} init 输出失败：{e}");
        stdout
            .join()
            .expect("init stdout 读取线程")
            .map_err(read_error)?;
        let stderr = stderr
            .join()
            .expect("init stderr 读取线程")
            .map_err(read_error)?;
        let Some(status) = finished.map_err(|e| format!("{what}：等待 init 退出失败：{e}"))?
        else {
            return Ok(false);
        };
        if !status.success() {
            return Err(format!(
                "{}（{what} init 失败，{status}）",
                String::from_utf8_lossy(&stderr).trim(),
            ));
        }
        if shutdown_requested() {
            return Ok(false);
        }
        log("init", json!({"domain": what}));
        Ok(true)
    })
}

fn stopped(failed: bool) -> i32 {
    log("stopped", json!({"failed": failed}));
    i32::from(failed)
}

fn run() -> Result<i32, String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let manifest_path = match args.as_slice() {
        [flag, path] if flag == "--manifest" => PathBuf::from(path),
        _ => return Err("InvalidDomain：usage: production_session --manifest FILE".into()),
    };
    // SAFETY：只登记写原子标志的 async-signal-safe 处理器。
    unsafe {
        libc::signal(libc::SIGTERM, on_stop as *const () as libc::sighandler_t);
        libc::signal(libc::SIGINT, on_stop as *const () as libc::sighandler_t);
    }
    #[cfg(target_os = "linux")]
    adopt_orphans().map_err(|e| format!("MissingDependency：无法接养域进程组后代：{e}"))?;
    let m = load_manifest(&manifest_path)?;
    if shutdown_requested() {
        return Ok(stopped(false));
    }
    let raw = &m.raw;
    let s_db = PathBuf::from(text(raw, "s.db")?);
    let (s_bin, e_bin, b_bin, x_bin) = (
        sibling("s_structure_session")?,
        sibling("e_economic_session")?,
        sibling("b_chong_session")?,
        sibling("x_execution_session")?,
    );
    log(
        "start",
        json!({"profile": m.profile, "structure_source": serde_json::from_str::<Value>(&m.source.canonical()).unwrap_or_default()}),
    );

    // ── init：只对尚不存在的库；S 一律带声明 init ──
    std::fs::create_dir_all(&m.state_dir).map_err(|e| format!("StorageUnavailable：{e}"))?;
    let decl = m.state_dir.join("structure-source.json");
    std::fs::write(&decl, m.source.canonical()).map_err(|e| format!("StorageUnavailable：{e}"))?;
    if !s_db.exists() {
        let mut c = clean(Command::new(&s_bin), &S_PASS);
        c.args(["init", "--protocol-revision", "s-session/3", "--db"])
            .arg(&s_db)
            .args(["--session", text(raw, "s.session")?])
            .args(["--catalog", text(raw, "s.catalog")?])
            .args(["--profile", text(raw, "s.profile")?])
            .args(["--session-generation", text(raw, "s.session_generation")?])
            .args(["--clock-plan", text(raw, "s.clock_plan")?])
            .args([
                "--delivery-retain-generations",
                text(raw, "s.delivery_retain_generations")?,
            ])
            .arg("--structure-source")
            .arg(&decl);
        if !run_once(c, "S")? {
            return Ok(stopped(false));
        }
    }
    let econ = text(raw, "economic.manifest")?;
    let e_db = text(raw, "economic.e.db")?;
    if !Path::new(e_db).exists() {
        let mut c = clean(Command::new(&e_bin), &[]);
        c.args(["init", "--manifest", econ, "--db", e_db]);
        if !run_once(c, "E")? {
            return Ok(stopped(false));
        }
    }
    let chongs = raw["economic"]["b"].as_array().cloned().unwrap_or_default();
    for b in &chongs {
        let db = text(b, "db")?;
        if !Path::new(db).exists() {
            let mut c = clean(Command::new(&b_bin), &[]);
            c.args([
                "init",
                "--manifest",
                econ,
                "--db",
                db,
                "--chong",
                text(b, "chong")?,
            ]);
            if !run_once(c, "B")? {
                return Ok(stopped(false));
            }
        }
    }

    // ── 拉起：每域独立进程；中途失败也先回收已拉起的子进程再报错，不留孤儿 ──
    let mut children = Vec::new();
    let spawned = spawn_domains(&m, &s_bin, &e_bin, &b_bin, &x_bin, &mut children);

    let supervised = if spawned.is_ok() {
        loop {
            match poll_groups(&mut children).map(|poll| poll.failed) {
                Ok(false) if !shutdown_requested() => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                result => break result,
            }
        }
    } else {
        Ok(false)
    };

    let stopped_failed = stop_groups(&mut children, STOP_GRACE)?;
    spawned?;
    Ok(stopped(supervised? | stopped_failed))
}

/// 按 S、E、各 Bᵢ、X 顺序拉起；已拉起的子进程即刻登记进 `children`，供调用方统一回收。
fn spawn_domains(
    m: &Manifest,
    s_bin: &Path,
    e_bin: &Path,
    b_bin: &Path,
    x_bin: &Path,
    children: &mut Vec<DomainProcess>,
) -> Result<(), String> {
    let raw = &m.raw;
    let s_db = text(raw, "s.db")?;
    let econ = text(raw, "economic.manifest")?;
    let e_db = text(raw, "economic.e.db")?;
    let chongs = raw["economic"]["b"].as_array().cloned().unwrap_or_default();
    let mut spawn = |domain: String, mut c: Command, critical: bool| -> Result<(), String> {
        if shutdown_requested() {
            return Ok(());
        }
        c.stdout(Stdio::null());
        let child = c
            .spawn()
            .map_err(|e| format!("MissingDependency：{domain} 启动失败：{e}"))?;
        let pid = child.id();
        children.push(DomainProcess::new(domain.clone(), child, Some(critical)));
        log("spawn", json!({"domain": domain, "pid": pid}));
        Ok(())
    };
    let mut s = clean(Command::new(s_bin), &S_PASS);
    s.args(["serve", "--protocol-revision", "s-session/3"])
        .args([
            "--admission-job-limits",
            text(raw, "s.admission_job_limits")?,
        ])
        .arg("--db")
        .arg(s_db)
        .args(["--profile", text(raw, "s.profile")?])
        .args(["--writer-epoch", text(raw, "s.writer_epoch")?])
        .args(["--clock-plan", text(raw, "s.clock_plan")?])
        .args(["--socket", text(raw, "s.socket")?])
        .args(["--resource-config", text(raw, "s.resource_config")?])
        .arg("--structure-source")
        .arg(m.state_dir.join("structure-source.json"));
    spawn("S".into(), s, true)?;
    let e_epoch = text(raw, "economic.e.epoch")?;
    let mut e = clean(Command::new(e_bin), &[]);
    e.args([
        "serve",
        "--manifest",
        econ,
        "--db",
        e_db,
        "--epoch",
        e_epoch,
    ]);
    spawn("E".into(), e, true)?;
    for b in &chongs {
        let chong = text(b, "chong")?;
        let mut c = clean(Command::new(b_bin), &[]);
        c.args(["serve", "--manifest", econ, "--db", text(b, "db")?])
            .args([
                "--chong",
                chong,
                "--epoch",
                text(b, "epoch")?,
                "--e-epoch",
                e_epoch,
            ]);
        spawn(format!("B:{chong}"), c, true)?;
    }
    let mut x = clean(Command::new(x_bin), &[]);
    x.args(["serve", "--db", text(raw, "x.db")?])
        .arg("--profile")
        .arg(&m.x_profile)
        .args(["--writer-epoch", text(raw, "x.writer_epoch")?]);
    if let Some((key, value)) = &m.credential {
        x.env(key, value);
    }
    spawn("X".into(), x, false)
}

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            log("refused", json!({"error": e}));
            eprintln!("{e}");
            std::process::exit(2);
        }
    }
}
