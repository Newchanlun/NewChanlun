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
use std::io::{self, PipeReader, Read};
use std::os::fd::AsRawFd;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicPtr, AtomicU8, Ordering};
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

const START_COMMITTED: u8 = 1;
const STOP_REQUESTED: u8 = 2;
// 启动器进程存续期间保留共享映射，供 fork 后、exec 前的子进程参与门控。
struct StartGate {
    launcher_pid: libc::pid_t,
    state: AtomicU8,
}

static START_GATE: AtomicPtr<StartGate> = AtomicPtr::new(std::ptr::null_mut());

fn start_gate() -> &'static StartGate {
    // SAFETY：在安装处理器及首次 spawn 前初始化；映射在 launcher 退出前一直有效。
    unsafe { &*START_GATE.load(Ordering::Acquire) }
}

extern "C" fn on_stop(_: libc::c_int) {
    let gate = start_gate();
    // SAFETY：getpid 是 async-signal-safe；未 exec 的域不能代 launcher 标记停服。
    if unsafe { libc::getpid() } == gate.launcher_pid {
        gate.state.fetch_or(STOP_REQUESTED, Ordering::AcqRel);
    }
}

fn install_signal_policy() -> io::Result<()> {
    // SAFETY：映射私有于 launcher 及 fork 后尚未 exec 的子进程；只通过原子访问。
    unsafe {
        let gate = libc::mmap(
            std::ptr::null_mut(),
            std::mem::size_of::<StartGate>(),
            libc::PROT_READ | libc::PROT_WRITE,
            libc::MAP_SHARED | libc::MAP_ANON,
            -1,
            0,
        );
        if gate == libc::MAP_FAILED {
            return Err(io::Error::last_os_error());
        }
        let gate = gate.cast::<StartGate>();
        gate.write(StartGate {
            launcher_pid: libc::getpid(),
            state: AtomicU8::new(0),
        });
        START_GATE.store(gate, Ordering::Release);
        let stop = on_stop as *const () as libc::sighandler_t;
        // 恢复 SIGCHLD 默认动作（也清除 SA_NOCLDWAIT），保留子进程的真实退出状态。
        for (signal, handler) in [
            (libc::SIGCHLD, libc::SIG_DFL),
            (libc::SIGTERM, stop),
            (libc::SIGINT, stop),
        ] {
            if libc::signal(signal, handler) == libc::SIG_ERR {
                return Err(io::Error::last_os_error());
            }
        }
    }
    Ok(())
}

/// 预查节省不必要的 fork；真正的授权在子进程 exec 前，与停服共用一次原子状态转换。
fn spawn_before_stop(command: &mut Command) -> io::Result<Option<Child>> {
    if shutdown_requested() {
        return Ok(None);
    }
    // SAFETY：在 setsid 后只访问无锁原子；失败时 Rust 报回 errno，不执行域程序。
    unsafe {
        command.pre_exec(|| {
            start_gate()
                .state
                .compare_exchange(0, START_COMMITTED, Ordering::AcqRel, Ordering::Acquire)
                .map(|_| ())
                .map_err(|_| io::Error::from_raw_os_error(libc::ECANCELED))
        });
    }
    let result = command.spawn();
    // 若子进程先获得授权，spawn 返回前它仍属本次在途启动。保留其间收到的停服，
    // 登记该子进程后就回收，不再授权下一次启动。
    let state = start_gate()
        .state
        .fetch_and(!START_COMMITTED, Ordering::AcqRel);
    match result {
        Err(e) if e.raw_os_error() == Some(libc::ECANCELED) && state == STOP_REQUESTED => Ok(None),
        result => result.map(Some),
    }
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
    start_gate().state.load(Ordering::Acquire) & STOP_REQUESTED != 0
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
    leader_unwaitable: bool,
    // Some 只用于常驻域；init 的退出由 run_once 处理。
    critical: Option<bool>,
    phase: StopPhase,
    group_gone: bool,
    kill_failed: bool,
}

impl DomainProcess {
    fn new(domain: String, leader: Child, critical: Option<bool>) -> Self {
        Self {
            domain,
            leader,
            status: None,
            leader_unwaitable: false,
            critical,
            phase: StopPhase::NotSignaled,
            group_gone: false,
            kill_failed: false,
        }
    }

    fn pgid(&self) -> libc::pid_t {
        // setsid 成功后 SID == PGID == 组长 PID，组长退出后仍用这个组号回收。
        self.leader.id() as libc::pid_t
    }

    /// 首次取得的退出按当时的阶段登记；之后清理后代时不改写。
    fn observe_exit(&mut self) -> io::Result<bool> {
        if self.status.is_some() || self.leader_unwaitable {
            return Ok(false);
        }
        match self.leader.try_wait() {
            Ok(None) => Ok(false),
            Ok(Some(status)) => {
                self.status = Some(status);
                if let Some(critical) = self.critical.filter(|_| !self.phase.explains(status)) {
                    log(
                        "exit",
                        json!({"domain": self.domain, "status": status.to_string(), "critical": critical}),
                    );
                    return Ok(critical);
                }
                Ok(false)
            }
            Err(e) => {
                self.leader_unwaitable = e.raw_os_error() == Some(libc::ECHILD);
                Err(e)
            }
        }
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
        if self.probe_or_signal_group(raw)? && self.status.is_none() && !self.leader_unwaitable {
            self.phase = phase;
        }
        Ok(())
    }

    fn reap_group(&mut self) -> io::Result<()> {
        #[cfg(target_os = "linux")]
        if !self.group_gone && (self.status.is_some() || self.leader_unwaitable) {
            self.reap_adopted()?;
        }
        Ok(())
    }

    #[cfg(target_os = "linux")]
    fn reap_adopted(&self) -> io::Result<()> {
        loop {
            // SAFETY：组长已回收或不具备 wait 资格；这里只等同 PGID 下被接养的后代。
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

fn supervise(children: &mut [DomainProcess]) -> Result<bool, String> {
    let mut failed = false;
    for child in children {
        failed |= child
            .observe_exit()
            .map_err(|e| format!("{}：等待组长退出失败：{e}", child.domain))?;
        // X 可能很早退出；及时回收并确认组消失，不在很久以后使用旧 PGID。
        if child.status.is_some() {
            child
                .reap_group()
                .and_then(|()| child.probe_or_signal_group(0))
                .map_err(|e| format!("{}：进程组回收失败：{e}", child.domain))?;
        }
    }
    Ok(failed)
}

#[derive(Default)]
struct StopOutcome {
    failed: bool,
    errors: BTreeSet<String>,
}

impl StopOutcome {
    fn record<T>(&mut self, result: io::Result<T>, domain: &str, action: &str) -> Option<T> {
        match result {
            Ok(value) => Some(value),
            Err(e) => {
                self.errors.insert(format!("{domain}：{action}：{e}"));
                None
            }
        }
    }

    fn observe(&mut self, child: &mut DomainProcess) -> bool {
        let result = child.observe_exit();
        match self.record(result, &child.domain, "等待组长退出失败") {
            Some(failed) => {
                self.failed |= failed;
                true
            }
            None => false,
        }
    }
}

fn stop_groups(
    children: &mut [DomainProcess],
    grace: Duration,
    mut extra: impl FnMut(StopSignal) -> io::Result<bool>,
) -> Result<bool, String> {
    let mut outcome = StopOutcome::default();
    let mut deadline = None;
    let mut phase = StopSignal::Term;
    let mut signal = Some(phase);
    loop {
        let escalated = matches!(phase, StopSignal::Kill);
        let mut all_reaped = true;
        for child in children.iter_mut() {
            // 发送信号前就地核验这个组长，不能用前一个组尚未收到信号时的陈旧状态推进阶段。
            let wait_ok = outcome.observe(child);
            if let Some(signal) = signal {
                let result = child.signal(signal);
                if outcome
                    .record(result, &child.domain, "进程组停服信号失败")
                    .is_none()
                    && escalated
                {
                    child.kill_failed = true;
                }
            }
            // 回收报错仍查组是否存活；已尝试 KILL 的故障组不阻止其他组收尾。
            let result = child.reap_group();
            let reap_ok = outcome
                .record(result, &child.domain, "进程组回收失败")
                .is_some();
            let result = child.probe_or_signal_group(0);
            let alive = outcome.record(result, &child.domain, "核验进程组退出失败");
            all_reaped &= alive == Some(false)
                || (escalated && (!wait_ok || !reap_ok || child.kill_failed || alive.is_none()));
        }
        all_reaped &= match extra(phase) {
            Ok(reaped) => reaped,
            Err(e) => {
                outcome.errors.insert(format!("init 清理失败：{e}"));
                matches!(phase, StopSignal::Kill)
            }
        };
        if all_reaped {
            return if outcome.errors.is_empty() {
                Ok(outcome.failed)
            } else {
                Err(outcome.errors.into_iter().collect::<Vec<_>>().join("；"))
            };
        }
        let deadline = *deadline.get_or_insert_with(|| Instant::now() + grace);
        if !escalated && Instant::now() >= deadline {
            phase = StopSignal::Kill;
            signal = Some(phase);
        } else {
            signal = None;
            std::thread::sleep(STOP_POLL);
        }
    }
}

#[cfg(target_os = "linux")]
fn stop_adopted_init_children(
    sid: libc::pid_t,
    phase: StopSignal,
    signaled: &mut std::collections::BTreeMap<libc::pid_t, libc::c_int>,
) -> io::Result<bool> {
    // launcher 是单线程 subreaper。只处理已接养、仍在该 init SID、但不在原组的直属子进程。
    // SIGCHLD 默认处理保证未 wait 的 PID 不会在检查后被复用。
    let children = std::fs::read_to_string("/proc/thread-self/children")?;
    let signal = match phase {
        StopSignal::Term => libc::SIGTERM,
        StopSignal::Kill => libc::SIGKILL,
    };
    let mut all_reaped = true;
    for pid in children
        .split_ascii_whitespace()
        .filter_map(|p| p.parse::<libc::pid_t>().ok())
    {
        if pid == sid {
            continue;
        }
        // SAFETY：getsid/getpgid 只读取内核元数据，不操作其他子进程的等待状态。
        if unsafe { libc::getsid(pid) != sid || libc::getpgid(pid) == sid } {
            continue;
        }
        // 即使本轮全部 wait 成功，也补扫一次：已退出的养子可能又留下了同会话子进程。
        all_reaped = false;
        // SAFETY：只 wait 已核验的直属养子；WNOHANG 不阻塞。
        match unsafe { libc::waitpid(pid, std::ptr::null_mut(), libc::WNOHANG) } {
            n if n > 0 => {
                signaled.remove(&pid);
            }
            0 => {
                if signaled.get(&pid) != Some(&signal) {
                    // SAFETY：这个 PID 是尚待回收的同会话直属养子。
                    if unsafe { libc::kill(pid, signal) } == -1 {
                        let e = io::Error::last_os_error();
                        if e.raw_os_error() != Some(libc::ESRCH) {
                            return Err(e);
                        }
                    }
                    signaled.insert(pid, signal);
                }
            }
            _ => {
                let e = io::Error::last_os_error();
                if !matches!(e.raw_os_error(), Some(libc::EINTR | libc::ECHILD)) {
                    return Err(e);
                }
            }
        }
    }
    Ok(all_reaped)
}

/// init stdout 无消费者；stderr 在 launcher 线程非阻塞限量排空，取消不依赖写端 EOF。
fn drain_init_output(pipe: &mut PipeReader, bytes: &mut Vec<u8>) -> io::Result<()> {
    let mut buf = [0_u8; 8192];
    for _ in 0..16 {
        match pipe.read(&mut buf) {
            Ok(0) => return Ok(()),
            Ok(n) => bytes.extend_from_slice(&buf[..n]),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(()),
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(())
}

/// 返回 false 表示停服已取消启动。
fn run_once(mut command: Command, what: &str) -> Result<bool, String> {
    if shutdown_requested() {
        return Ok(false);
    }
    let read_error = |e| format!("StorageUnavailable：读取 {what} init 输出失败：{e}");
    let (mut pipe, writer) = io::pipe().map_err(read_error)?;
    // SAFETY：只设置 launcher 的私有读端；子进程的写端保持阻塞语义。
    if unsafe { libc::fcntl(pipe.as_raw_fd(), libc::F_SETFL, libc::O_NONBLOCK) } == -1 {
        return Err(read_error(io::Error::last_os_error()));
    }
    command.stdout(Stdio::null()).stderr(writer);
    let leader = spawn_before_stop(&mut command)
        .map_err(|e| format!("MissingDependency：{what} 启动失败：{e}"))?;
    drop(command);
    let Some(leader) = leader else {
        return Ok(false);
    };
    let mut child = DomainProcess::new(what.into(), leader, None);
    let mut bytes = Vec::new();
    let finished = loop {
        if shutdown_requested() {
            break Ok(None);
        }
        if let Err(e) = drain_init_output(&mut pipe, &mut bytes) {
            break Err(read_error(e));
        }
        if let Err(e) = child.observe_exit() {
            break Err(format!("{what}：等待 init 退出失败：{e}"));
        }
        if child.status.is_some() {
            break Ok(child.status);
        }
        std::thread::sleep(STOP_POLL);
    };
    #[cfg(target_os = "linux")]
    let sid = child.pgid();
    #[cfg(target_os = "linux")]
    let mut signaled = std::collections::BTreeMap::new();
    let mut output_error = None;
    stop_groups(
        std::slice::from_mut(&mut child),
        INIT_STOP_GRACE,
        |_phase| {
            if output_error.is_none() {
                output_error = drain_init_output(&mut pipe, &mut bytes).err();
            }
            #[cfg(target_os = "linux")]
            if shutdown_requested() {
                return stop_adopted_init_children(sid, _phase, &mut signaled);
            }
            Ok(true)
        },
    )?;
    let Some(status) = finished? else {
        return Ok(false);
    };
    if let Some(e) = output_error {
        return Err(read_error(e));
    }
    if !status.success() {
        return Err(format!(
            "{}（{what} init 失败，{status}）",
            String::from_utf8_lossy(&bytes).trim(),
        ));
    }
    if shutdown_requested() {
        return Ok(false);
    }
    log("init", json!({"domain": what}));
    Ok(true)
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
    install_signal_policy().map_err(|e| format!("MissingDependency：无法设置会话信号处理：{e}"))?;
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
            match supervise(&mut children) {
                Ok(false) if !shutdown_requested() => {
                    std::thread::sleep(Duration::from_millis(100));
                }
                result => break result,
            }
        }
    } else {
        Ok(false)
    };

    let cleanup = stop_groups(&mut children, STOP_GRACE, |_| Ok(true));
    match (spawned.and(supervised), cleanup) {
        (Ok(failed), Ok(stopped_failed)) => Ok(stopped(failed | stopped_failed)),
        (Err(first), Err(cleanup)) => Err(format!("{first}；{cleanup}")),
        (Err(error), _) | (_, Err(error)) => Err(error),
    }
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
        c.stdout(Stdio::null());
        let Some(child) = spawn_before_stop(&mut c)
            .map_err(|e| format!("MissingDependency：{domain} 启动失败：{e}"))?
        else {
            return Ok(());
        };
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
