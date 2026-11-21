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

const STOP_SIGNALS: [libc::c_int; 2] = [libc::SIGTERM, libc::SIGINT];
static STOP_REQUESTED: AtomicBool = AtomicBool::new(false);

extern "C" fn on_stop(_: libc::c_int) {
    STOP_REQUESTED.store(true, Ordering::Release);
}

struct StopPolicy {
    signals: libc::sigset_t,
    child_mask: libc::sigset_t,
}

fn install_signal_policy() -> io::Result<StopPolicy> {
    // SAFETY：只在单线程 launcher 的首次 spawn 前设置处置。
    unsafe {
        // 恢复 SIGCHLD 默认动作（也清除 SA_NOCLDWAIT），保留子进程的真实退出状态。
        if libc::signal(libc::SIGCHLD, libc::SIG_DFL) == libc::SIG_ERR {
            return Err(io::Error::last_os_error());
        }
        let mut signals: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut signals);
        let stop = on_stop as *const () as libc::sighandler_t;
        for signal in STOP_SIGNALS {
            if libc::signal(signal, stop) == libc::SIG_ERR {
                return Err(io::Error::last_os_error());
            }
            libc::sigaddset(&mut signals, signal);
        }
        // launcher 始终接收停服信号，即使启动者屏蔽了它们；域仍继承启动者原掩码。
        let mut child_mask: libc::sigset_t = std::mem::zeroed();
        if libc::sigprocmask(libc::SIG_UNBLOCK, &signals, &mut child_mask) == -1 {
            return Err(io::Error::last_os_error());
        }
        Ok(StopPolicy {
            signals,
            child_mask,
        })
    }
}

/// 父进程在 spawn 交界内只挂起停服信号，不执行处理器。进入交界前检查已处理和已挂起
/// 的请求；通过此门后的在途启动可以 exec，父进程恢复掩码后将其纳入统一回收。
fn spawn_before_stop(command: &mut Command, policy: &StopPolicy) -> io::Result<Option<Child>> {
    if shutdown_requested() {
        return Ok(None);
    }
    // SAFETY：sigset 均由 POSIX API 初始化；launcher 单线程，掩码覆盖其整个 spawn 交界。
    unsafe {
        let mut previous: libc::sigset_t = std::mem::zeroed();
        if libc::sigprocmask(libc::SIG_BLOCK, &policy.signals, &mut previous) == -1 {
            return Err(io::Error::last_os_error());
        }
        let result = (|| {
            let mut pending: libc::sigset_t = std::mem::zeroed();
            if libc::sigpending(&mut pending) == -1 {
                return Err(io::Error::last_os_error());
            }
            if STOP_SIGNALS
                .iter()
                .any(|&s| libc::sigismember(&pending, s) == 1)
            {
                STOP_REQUESTED.store(true, Ordering::Release);
            }
            if shutdown_requested() {
                return Ok(None);
            }
            let StopPolicy {
                signals,
                child_mask,
            } = *policy;
            // 只调用 async-signal-safe 的 POSIX 函数。
            command.pre_exec(move || {
                // fork 后仍在 launcher 前台组。SIG_IGN 丢弃已为该子进程挂起的停服信号，
                // 并覆盖到 setsid 完成；由收到同一请求的 launcher 回收这次在途启动。
                for signal in STOP_SIGNALS {
                    if libc::signal(signal, libc::SIG_IGN) == libc::SIG_ERR {
                        return Err(io::Error::last_os_error());
                    }
                }
                // Linux 仍可能挂起被屏蔽的信号，即使其处置为 SIG_IGN。
                // 在 setsid 前解除屏蔽，确保后续前台信号也直接被丢弃。
                if libc::sigprocmask(libc::SIG_UNBLOCK, &signals, std::ptr::null_mut()) == -1 {
                    return Err(io::Error::last_os_error());
                }
                if libc::setsid() == -1 {
                    return Err(io::Error::last_os_error());
                }
                if libc::sigprocmask(libc::SIG_SETMASK, &child_mask, std::ptr::null_mut()) == -1 {
                    return Err(io::Error::last_os_error());
                }
                for signal in STOP_SIGNALS {
                    if libc::signal(signal, libc::SIG_DFL) == libc::SIG_ERR {
                        return Err(io::Error::last_os_error());
                    }
                }
                Ok(())
            });
            command.spawn().map(Some)
        })();
        // SIG_SETMASK 和内核刚返回的掩码是有效参数。解除屏蔽时挂起的停服信号会交给处理器。
        if libc::sigprocmask(libc::SIG_SETMASK, &previous, std::ptr::null_mut()) == -1 {
            return Err(io::Error::last_os_error());
        }
        // 成功启动的组必须交给调用方登记，即使此时已经停服；失败且正在停服则没有组可登记。
        if shutdown_requested() && result.is_err() {
            return Ok(None);
        }
        result
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
    command
}

fn shutdown_requested() -> bool {
    STOP_REQUESTED.load(Ordering::Acquire)
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
            // 发送前就地核验当前组长；已观察到的退出按原阶段登记。POSIX kill/waitpid
            // 不提供来源证明：核验至本组发送同号信号的交界内，外部同号信号不可区分。
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

enum InitOutput {
    Drained,
    BatchLimit,
}

/// 非阻塞且每轮限量，让进程回收和停服请求不被持续输出饿死。
fn drain_init_output(pipe: &mut PipeReader, bytes: &mut Vec<u8>) -> io::Result<InitOutput> {
    let mut buf = [0_u8; 8192];
    for _ in 0..16 {
        match pipe.read(&mut buf) {
            Ok(0) => return Ok(InitOutput::Drained),
            Ok(n) => bytes.extend_from_slice(&buf[..n]),
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Ok(InitOutput::Drained),
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    Ok(InitOutput::BatchLimit)
}

fn reap_init(
    child: &mut DomainProcess,
    pipe: &mut PipeReader,
    bytes: &mut Vec<u8>,
) -> Result<Option<io::Error>, String> {
    #[cfg(target_os = "linux")]
    let sid = child.pgid();
    #[cfg(target_os = "linux")]
    let mut signaled = std::collections::BTreeMap::new();
    let mut output_error = None;
    stop_groups(std::slice::from_mut(child), INIT_STOP_GRACE, |_phase| {
        if output_error.is_none() {
            output_error = drain_init_output(pipe, bytes).err();
        }
        #[cfg(target_os = "linux")]
        if shutdown_requested() {
            return stop_adopted_init_children(sid, _phase, &mut signaled);
        }
        Ok(true)
    })?;
    Ok(output_error)
}

/// 返回 false 表示停服已取消启动。
fn run_once(mut command: Command, what: &str, policy: &StopPolicy) -> Result<bool, String> {
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
    let leader = spawn_before_stop(&mut command, policy)
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
    let output_error = reap_init(&mut child, &mut pipe, &mut bytes)?;
    let Some(status) = finished? else {
        return Ok(false);
    };
    let mut output_error = output_error;
    // init 已回收，读完已排队的全部字节；EOF 或 WouldBlock 都表示此时已排空。
    while !shutdown_requested() && output_error.is_none() {
        match drain_init_output(&mut pipe, &mut bytes) {
            Ok(InitOutput::Drained) => break,
            Ok(InitOutput::BatchLimit) => (),
            Err(e) => output_error = Some(e),
        }
    }
    if shutdown_requested() {
        // 同组已回收；若停服发生在最后排空时，仍需回收同会话的 Linux 养子。
        reap_init(&mut child, &mut pipe, &mut bytes)?;
        return Ok(false);
    }
    if let Some(e) = output_error {
        return Err(read_error(e));
    }
    if !status.success() {
        return Err(format!(
            "{}（{what} init 失败，{status}）",
            String::from_utf8_lossy(&bytes).trim(),
        ));
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
    let policy = install_signal_policy()
        .map_err(|e| format!("MissingDependency：无法设置会话信号处理：{e}"))?;
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
        if !run_once(c, "S", &policy)? {
            return Ok(stopped(false));
        }
    }
    let econ = text(raw, "economic.manifest")?;
    let e_db = text(raw, "economic.e.db")?;
    if !Path::new(e_db).exists() {
        let mut c = clean(Command::new(&e_bin), &[]);
        c.args(["init", "--manifest", econ, "--db", e_db]);
        if !run_once(c, "E", &policy)? {
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
            if !run_once(c, "B", &policy)? {
                return Ok(stopped(false));
            }
        }
    }

    // ── 拉起：每域独立进程；中途失败也先回收已拉起的子进程再报错，不留孤儿 ──
    let mut children = Vec::new();
    let spawned = spawn_domains(&m, &s_bin, &e_bin, &b_bin, &x_bin, &mut children, &policy);

    let supervised = if spawned.is_ok() && !shutdown_requested() {
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
    policy: &StopPolicy,
) -> Result<(), String> {
    let raw = &m.raw;
    let s_db = text(raw, "s.db")?;
    let econ = text(raw, "economic.manifest")?;
    let e_db = text(raw, "economic.e.db")?;
    let chongs = raw["economic"]["b"].as_array().cloned().unwrap_or_default();
    let mut spawn = |domain: String, mut c: Command, critical: bool| -> Result<bool, String> {
        c.stdout(Stdio::null());
        let Some(child) = spawn_before_stop(&mut c, policy)
            .map_err(|e| format!("MissingDependency：{domain} 启动失败：{e}"))?
        else {
            return Ok(false);
        };
        let pid = child.id();
        children.push(DomainProcess::new(domain.clone(), child, Some(critical)));
        log("spawn", json!({"domain": domain, "pid": pid}));
        Ok(!shutdown_requested())
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
    if !spawn("S".into(), s, true)? {
        return Ok(());
    }
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
    if !spawn("E".into(), e, true)? {
        return Ok(());
    }
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
        if !spawn(format!("B:{chong}"), c, true)? {
            return Ok(());
        }
    }
    let mut x = clean(Command::new(x_bin), &[]);
    x.args(["serve", "--db", text(raw, "x.db")?])
        .arg("--profile")
        .arg(&m.x_profile)
        .args(["--writer-epoch", text(raw, "x.writer_epoch")?]);
    if let Some((key, value)) = &m.credential {
        x.env(key, value);
    }
    spawn("X".into(), x, false).map(|_| ())
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
