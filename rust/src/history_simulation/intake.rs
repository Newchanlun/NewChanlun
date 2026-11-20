pub(crate) use super::store::FrontierGuard;
use super::{
    model::{Fill, Model},
    store::RAW_FORMAT,
};
use crate::session_protocol::{canonical_json, nonnegative, required, sha256_hex, strict_json};
use rusqlite::{Connection, OpenFlags};
use serde_json::{json, Value};
use std::path::Path;

pub(crate) const EVENT: &str = "history-sim-unresolved/1";
fn digest(v: &Value) -> String {
    sha256_hex(canonical_json(v).as_bytes())
}
fn failure(e: impl std::fmt::Display) -> String {
    format!("MissingDependency：X 原件不可核：{e}")
}

/// 只规范事实身份和路由。金额分量仍待 E 的命令/成本证据，不生成 Pi/A/W。
pub(crate) fn decode(doc: &Value, pointer: &str) -> Result<(Value, Value), String> {
    if pointer != "/event" || doc["format"] != RAW_FORMAT {
        return Err("SchemaUnsupported：模拟原件须定位 /event".into());
    }
    let model: Model = serde_json::from_value(doc["model"].clone()).map_err(failure)?;
    model.validate()?;
    if doc["model_content_hash"] != digest(&doc["model"]) || doc["intra_batch_order"] != "Unknown" {
        return Err("IdentityConflict：模拟模型摘要或批顺序声明错误".into());
    }
    required(doc, "known_frontier_cut")?;
    let raw = &doc["event"];
    let source = &raw["source"];
    for key in [
        "source_namespace",
        "source_epoch",
        "external_fact_id",
        "source_cursor",
        "received_time",
        "source_event_time",
        "claimed_origin",
    ] {
        required(source, key)?;
    }
    nonnegative(required(source, "source_cursor")?, "source_cursor")?;
    let (chong, family, command) = match required(raw, "kind")? {
        "fill" => {
            let fill: Fill = serde_json::from_value(raw["fill"].clone()).map_err(failure)?;
            if fill.quantity <= 0
                || fill.price <= 0
                || fill.fee < 0
                || fill.amount
                    != fill
                        .quantity
                        .checked_mul(fill.price)
                        .and_then(|x| x.checked_mul(model.tick_value))
                        .ok_or("InvalidDomain：成交金额溢出")?
                || source["external_fact_id"] != fill.exec_id
            {
                return Err("IdentityConflict：模拟 fill 数量/价格/金额/身份不符".into());
            }
            (fill.chong_id, fill.family_id, fill.command_id)
        }
        "fee" | "bust" => {
            if raw["cause"]["kind"] != "fill" {
                return Err("InvalidDomain：模拟更正/费用须绑定原 fill".into());
            }
            required(&raw["cause"], "exec_id")?;
            if raw["kind"] == "fee" {
                if raw["amount"].as_i64().is_none_or(|x| x < 0)
                    || raw["fee_profile"] != model.fee_profile.reference
                {
                    return Err("InvalidDomain：费用额或费用合同不符".into());
                }
            } else if raw["quantity"].as_i64().is_none_or(|x| x <= 0)
                || doc["capacity"]["kind"] != "scenario"
                || doc["capacity"]["reference"] != raw["scenario_ref"]
            {
                return Err("InvalidDomain：bust 数量或场景合同不符".into());
            }
            (
                required(raw, "chong_id")?.into(),
                required(raw, "family_id")?.into(),
                required(raw, "command_id")?.into(),
            )
        }
        _ => return Err("SchemaUnsupported：未知模拟原件种类".into()),
    };
    if chong.is_empty() || family.is_empty() || command.is_empty() {
        return Err("InvalidDomain：模拟原件归属缺失".into());
    }
    let mut normalized = json!({"event":EVENT,"allocation_id":source["external_fact_id"],"source":source,"chong_id":chong,"family_id":family,"command_id":command,"simulation_original":raw});
    if raw["kind"] != "fill" {
        normalized["depends_on"] = json!({"source_namespace":source["source_namespace"],"source_epoch":source["source_epoch"],"external_fact_id":raw["cause"]["exec_id"]});
    }
    let mut document = doc.clone();
    document["units"] = json!({"quantity":{"unit":model.quantity_unit,"quantum":"1"},"money":{"unit":model.currency,"currency":model.currency,"quantum":"1"},"numeric_encoding":"exact_decimal_integer_text"});
    Ok((document, normalized))
}

/// Capture 的首次写入验证冻结 X 库中的原字节；请求不能自行提供来源路径或升级格式。
pub(crate) fn verify_capture(manifest: &Value, envelope: &Value, raw: &str) -> Result<(), String> {
    let doc = strict_json(raw.as_bytes())?;
    let binding = &manifest["history_simulation_source"];
    if doc["format"] != RAW_FORMAT {
        if binding.is_object()
            && binding["source_namespace"] == envelope["source_namespace"]
            && binding["source_epoch"] == envelope["source_epoch"]
        {
            return Err("IdentityConflict：同一执行来源不得混用模拟与场所原件".into());
        }
        return Ok(());
    }
    for key in [
        "source_namespace",
        "source_epoch",
        "producer_id",
        "producer_epoch",
    ] {
        if required(binding, key)? != required(envelope, key)? {
            return Err("IdentityConflict：模拟原件不是冻结 X 来源".into());
        }
    }
    if binding["model_content_hash"] != doc["model_content_hash"] {
        return Err("IdentityConflict：模拟模型不是本会话冻结版本".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let c = Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(failure)?;
    // 与 economic_session::store 的打开取值一致：X 正在提交时等锁，而非立即报原件不可核。
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    let contract: String = c
        .query_row("SELECT v FROM x_sim_meta WHERE k='contract'", [], |r| {
            r.get(0)
        })
        .map_err(failure)?;
    let contract = strict_json(contract.as_bytes())?;
    if digest(&contract["model"]) != binding["model_content_hash"]
        || contract["source_namespace"] != binding["source_namespace"]
        || contract["source_epoch"] != binding["source_epoch"]
    {
        return Err("IdentityConflict：冻结 X 库合同与会话来源不符".into());
    }
    let stored: String = c
        .query_row(
            "SELECT raw FROM x_sim_originals WHERE id=?1",
            [required(&doc["event"]["source"], "external_fact_id")?],
            |r| r.get(0),
        )
        .map_err(failure)?;
    if stored != raw {
        return Err("IdentityConflict：模拟原件不等于 X 持久原字节".into());
    }
    Ok(())
}

/// #1375：从 E 已冻结的 X 只读库核验一批已提交原件。调用者须指定批身份，
/// 不能用最新读数主张故障结束；此结果也不证明任何事实已经济核清。
pub(crate) fn committed_capture_batch(
    manifest: &Value,
    batch_id: &str,
    receipt_digest: &str,
    x_id: &str,
    x_epoch: i64,
) -> Result<Value, String> {
    let binding = &manifest["history_simulation_source"];
    if !binding.is_object() {
        return Err("SchemaUnsupported：本会话未冻结模拟 X 原件来源".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let mut c =
        Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(failure)?;
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    let tx = c.transaction().map_err(failure)?;
    let x_meta = |key| -> Result<String, String> {
        tx.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .map_err(failure)
    };
    if x_meta("profile_revision")? != "x-execution-profile/1"
        || x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || x_meta("writer_epoch")? != x_epoch.to_string()
    {
        return Err("IdentityConflict：指定 X 模型或当前 writer epoch 不符".into());
    }
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let profile: super::runtime::Profile =
        serde_json::from_value(strict_json(raw_profile.as_bytes())?).map_err(failure)?;
    if profile.session_id != required(manifest, "session_id")?
        || profile.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X 与 E 的会话或化身不同".into());
    }
    if profile.source_namespace != required(binding, "source_namespace")?
        || profile.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X 持久来源与 E 冻结来源不同".into());
    }
    if profile.x_id != x_id
        || digest(&serde_json::to_value(&profile.model).map_err(failure)?)
            != required(binding, "model_content_hash")?
    {
        return Err("IdentityConflict：X 身份或模型与冻结范围不同".into());
    }
    let raw: String = tx
        .query_row(
            "SELECT result FROM x_sim_batches WHERE id=?1",
            [batch_id],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let receipt = strict_json(raw.as_bytes())?;
    if canonical_json(&receipt) != raw
        || receipt["request_id"] != batch_id
        || sha256_hex(raw.as_bytes()) != receipt_digest
    // DevSkim: ignore DS197836 内容寻址摘要
    {
        return Err("IdentityConflict：指定 X 批的完整回执摘要不同".into());
    }
    // 复用正式 X 恢复入口的只读部分：批重演之外，还核接纳、原 Release 与
    // S 执行证据。只核原件相符不能证明该批由正式命令产生。
    super::runtime::validate_existing(&tx, &profile, x_epoch)?;
    tx.commit().map_err(failure)?;
    Ok(receipt)
}

/// 仅用于缺口态只读打开模拟 X 库的非默认 SQLite VFS（`makeDflt = 0`）：
/// - 主库 (`SQLITE_OPEN_MAIN_DB`) 附 `mode=ro&readonly_shm=1` 复用默认 `unix` VFS 的 `SHARED` 锁与
///   `unixInodeInfo`/`unixShmNode` 引用计数（跨 Linux / macOS 与同进程写者共享 `-shm` 锁归属，
///   关闭只读连接绝不误释同进程 SQLite 写者的 POSIX DMS 锁）；
/// - 注册时通过官方 SQLite VFS `xGetSystemCall`/`xSetSystemCall` 为默认 `unix` VFS 的 `fchown` 与 `fchmod`
///   安装线程局部守卫（仅当本线程处于 `history_sim_ro` 打开/映射临界区时拦截为空操作，其余所有线程与
///   健康连接原样透传原系统调用），确保即便以 `euid == 0`（root）读取正常非空 `-shm` 或 0 字节异权限
///   `-shm`，也不会触发 `unixOpenSharedMemory` 的 `robustFchown`/`robust_open` 改写 owner/mode/`ctime`；
/// - WAL (`SQLITE_OPEN_WAL`) 直接以 `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` 打开并仅做 `pread` / `fstat`
///   （SQLite 不在 `-wal` 上持 POSIX 锁），既彻底避开 0 字节只读 `-wal` 的 `robust_open`/`fchmod`，
///   又在 `-wal` 与 `-shm` 双缺（`ENOENT` 且 `ENOENT`，即正式 X 正常末连接 checkpoint 闭库态）下进入
///   受检虚拟空 WAL 只读态，无需重启 X、无需 `immutable=1`、绝不创建任何文件；一旦 `-wal` 或 `-shm`
///   存在/中途出现/不可读/非普通文件，立即走真实 WAL 读取或显式拒绝，绝不回落陈旧主库；
/// - SHM (`xShmMap`/`xShmLock`/`xShmBarrier`/`xShmUnmap`) 分两态：
///   1) `AbsentClean`：仅当 `-wal` 与 `-shm` 双 `ENOENT` 时返回 `SQLITE_READONLY_CANTINIT`，并在每次
///      `xShmMap`/`xShmLock`/`xFileSize`/`xRead` 复检双缺；
///   2) `Delegated`：所有存在的普通文件 `-shm`（含非空与 0 字节、root 与非 root）统一委托默认 `unix`
///      VFS（带 `readonly_shm=1`、禁扩展、禁独占锁、禁删除、`SQLITE_READONLY` 标记及线程局部元数据写守卫），
///      零 `fchmod`/`fchown` 且完整保留同进程/跨平台 POSIX `unixShmNode` 锁归属；
/// - 绝不影响健康财务路径、`#2078` 单批核验与旧查询。
mod readonly_vfs {
    use rusqlite::ffi;
    use std::cell::Cell;
    use std::ffi::{c_char, c_int, c_void, CStr, CString};
    use std::sync::atomic::{fence, Ordering};
    use std::sync::OnceLock;

    const VFS_NAME: &str = "history_sim_ro";
    const VFS_NAME_CSTR: &[u8] = b"history_sim_ro\0";
    const REAL_OFFSET: usize = (std::mem::size_of::<RoMainFile>() + 15) & !15;

    type SyscallPtr = unsafe extern "C" fn();
    type FchownFn = unsafe extern "C" fn(c_int, libc::uid_t, libc::gid_t) -> c_int;
    type FchmodFn = unsafe extern "C" fn(c_int, libc::mode_t) -> c_int;

    static REGISTERED: OnceLock<Result<&'static str, String>> = OnceLock::new();
    static ORIG_FCHOWN: OnceLock<FchownFn> = OnceLock::new();
    static ORIG_FCHMOD: OnceLock<FchmodFn> = OnceLock::new();

    thread_local! {
        static SUPPRESS_METADATA_WRITES: Cell<usize> = const { Cell::new(0) };
    }

    struct MetadataWriteSuppressGuard;

    impl MetadataWriteSuppressGuard {
        #[inline]
        fn enter() -> Self {
            SUPPRESS_METADATA_WRITES.with(|depth| depth.set(depth.get() + 1));
            Self
        }
    }

    impl Drop for MetadataWriteSuppressGuard {
        #[inline]
        fn drop(&mut self) {
            SUPPRESS_METADATA_WRITES.with(|depth| depth.set(depth.get().saturating_sub(1)));
        }
    }

    unsafe extern "C" fn guarded_fchown(fd: c_int, uid: libc::uid_t, gid: libc::gid_t) -> c_int {
        if SUPPRESS_METADATA_WRITES.with(|depth| depth.get() > 0) {
            return 0;
        }
        let Some(&orig) = ORIG_FCHOWN.get() else {
            return 0;
        };
        orig(fd, uid, gid)
    }

    unsafe extern "C" fn guarded_fchmod(fd: c_int, mode: libc::mode_t) -> c_int {
        if SUPPRESS_METADATA_WRITES.with(|depth| depth.get() > 0) {
            return 0;
        }
        let Some(&orig) = ORIG_FCHMOD.get() else {
            return 0;
        };
        orig(fd, mode)
    }

    unsafe fn install_metadata_write_guards(
        parent: *mut ffi::sqlite3_vfs,
    ) -> Result<(Option<SyscallPtr>, Option<SyscallPtr>), String> {
        if (*parent).iVersion < 3 {
            return Err("StorageUnavailable：默认 SQLite VFS 不支持系统调用拦截接口".into());
        }
        let (Some(get), Some(set)) = ((*parent).xGetSystemCall, (*parent).xSetSystemCall) else {
            return Err(
                "StorageUnavailable：默认 SQLite VFS 缺少 xGetSystemCall/xSetSystemCall".into(),
            );
        };
        let orig_fchown = get(parent, c"fchown".as_ptr());
        if let Some(raw) = orig_fchown {
            let _ = ORIG_FCHOWN.set(std::mem::transmute::<SyscallPtr, FchownFn>(raw));
            let rc = set(
                parent,
                c"fchown".as_ptr(),
                Some(std::mem::transmute::<FchownFn, SyscallPtr>(guarded_fchown)),
            );
            if rc != ffi::SQLITE_OK {
                return Err(format!(
                    "StorageUnavailable：安装 SQLite fchown 只读守卫失败（rc={rc}）"
                ));
            }
        }
        let orig_fchmod = get(parent, c"fchmod".as_ptr());
        if let Some(raw) = orig_fchmod {
            let _ = ORIG_FCHMOD.set(std::mem::transmute::<SyscallPtr, FchmodFn>(raw));
            let rc = set(
                parent,
                c"fchmod".as_ptr(),
                Some(std::mem::transmute::<FchmodFn, SyscallPtr>(guarded_fchmod)),
            );
            if rc != ffi::SQLITE_OK {
                if let Some(prev) = orig_fchown {
                    let _ = set(parent, c"fchown".as_ptr(), Some(prev));
                }
                return Err(format!(
                    "StorageUnavailable：安装 SQLite fchmod 只读守卫失败（rc={rc}）"
                ));
            }
        }
        Ok((orig_fchown, orig_fchmod))
    }

    enum ShmMode {
        Uninit,
        AbsentClean,
        Delegated,
    }

    struct RoMainState {
        wal_path: CString,
        shm_path: CString,
        shm_mode: ShmMode,
    }

    #[repr(C)]
    struct RoMainFile {
        base: ffi::sqlite3_file,
        real: *mut ffi::sqlite3_file,
        state: *mut RoMainState,
    }

    #[repr(C)]
    struct RoWalFile {
        base: ffi::sqlite3_file,
        fd: c_int,
        absent_paths: *mut (CString, CString),
    }

    pub(super) fn name() -> Result<&'static str, String> {
        REGISTERED
            .get_or_init(|| {
                let init_rc = unsafe { ffi::sqlite3_initialize() };
                if init_rc != ffi::SQLITE_OK {
                    return Err(format!(
                        "StorageUnavailable：初始化 SQLite 失败（rc={init_rc}）"
                    ));
                }
                let parent = unsafe { ffi::sqlite3_vfs_find(std::ptr::null()) };
                if parent.is_null() {
                    return Err("StorageUnavailable：未找到默认 SQLite VFS".into());
                }
                let parent_vfs = unsafe { *parent };
                let (orig_fchown, orig_fchmod) = unsafe { install_metadata_write_guards(parent)? };
                let sz_os_file = parent_vfs
                    .szOsFile
                    .checked_add(REAL_OFFSET as c_int)
                    .ok_or_else(|| "StorageUnavailable：只读 VFS 文件句柄尺寸溢出".to_string())?
                    .max(std::mem::size_of::<RoWalFile>() as c_int);
                let mut vfs = Box::new(parent_vfs);
                vfs.iVersion = parent_vfs.iVersion.min(2);
                vfs.szOsFile = sz_os_file;
                vfs.zName = VFS_NAME_CSTR.as_ptr().cast::<c_char>();
                vfs.pNext = std::ptr::null_mut();
                vfs.pAppData = parent.cast::<c_void>();
                // unix VFS 的 xFullPathname/xRandomness/xSleep/xCurrentTime/xGetLastError/
                // xCurrentTimeInt64 均不读取 pVfs/pAppData，直接沿用 parent_vfs 指针以收简 FFI 包装层。
                vfs.xOpen = Some(ro_open);
                vfs.xDelete = Some(ro_delete);
                vfs.xAccess = Some(ro_access);
                vfs.xDlOpen = None;
                vfs.xDlError = None;
                vfs.xDlSym = None;
                vfs.xDlClose = None;
                vfs.xSetSystemCall = None;
                vfs.xGetSystemCall = None;
                vfs.xNextSystemCall = None;
                let raw = Box::into_raw(vfs);
                let rc = unsafe { ffi::sqlite3_vfs_register(raw, 0) };
                if rc != ffi::SQLITE_OK {
                    unsafe {
                        if let Some(set) = (*parent).xSetSystemCall {
                            if let Some(prev) = orig_fchown {
                                let _ = set(parent, c"fchown".as_ptr(), Some(prev));
                            }
                            if let Some(prev) = orig_fchmod {
                                let _ = set(parent, c"fchmod".as_ptr(), Some(prev));
                            }
                        }
                        drop(Box::from_raw(raw));
                    }
                    return Err(format!(
                        "StorageUnavailable：注册只读 SQLite VFS 失败（rc={rc}）"
                    ));
                }
                Ok(VFS_NAME)
            })
            .clone()
    }

    #[inline]
    unsafe fn parent_vfs(vfs: *mut ffi::sqlite3_vfs) -> *mut ffi::sqlite3_vfs {
        (*vfs).pAppData.cast::<ffi::sqlite3_vfs>()
    }

    #[inline]
    unsafe fn main_parts<'a>(
        file: *mut ffi::sqlite3_file,
    ) -> (*mut ffi::sqlite3_file, &'a ffi::sqlite3_io_methods) {
        let main = &*file.cast::<RoMainFile>();
        (main.real, &*(*main.real).pMethods)
    }

    #[inline]
    unsafe fn is_enoent(path: *const c_char) -> bool {
        let mut st: libc::stat = std::mem::zeroed();
        if libc::lstat(path, &mut st) == 0 {
            return false;
        }
        std::io::Error::last_os_error().raw_os_error() == Some(libc::ENOENT)
    }

    #[inline]
    unsafe fn both_sidecars_absent(wal_path: &CString, shm_path: &CString) -> bool {
        is_enoent(wal_path.as_ptr()) && is_enoent(shm_path.as_ptr())
    }

    unsafe fn open_ro_regular_errno(path: *const c_char) -> Result<c_int, i32> {
        let fd = loop {
            let fd = libc::open(path, libc::O_RDONLY | libc::O_NOFOLLOW | libc::O_CLOEXEC);
            if fd >= 0 {
                break fd;
            }
            let err = std::io::Error::last_os_error()
                .raw_os_error()
                .unwrap_or(libc::EIO);
            if err == libc::EINTR {
                continue;
            }
            return Err(err);
        };
        let mut st: libc::stat = std::mem::zeroed();
        if libc::fstat(fd, &mut st) != 0
            || (st.st_mode as u32 & libc::S_IFMT as u32) != libc::S_IFREG as u32
        {
            libc::close(fd);
            return Err(libc::EINVAL);
        }
        Ok(fd)
    }

    unsafe extern "C" fn ro_open(
        vfs: *mut ffi::sqlite3_vfs,
        name: *const c_char,
        file: *mut ffi::sqlite3_file,
        flags: c_int,
        out: *mut c_int,
    ) -> c_int {
        (*file).pMethods = std::ptr::null();
        if name.is_null() {
            return ffi::SQLITE_READONLY;
        }
        let ro_flags = (flags
            & !(ffi::SQLITE_OPEN_READWRITE
                | ffi::SQLITE_OPEN_CREATE
                | ffi::SQLITE_OPEN_EXCLUSIVE
                | ffi::SQLITE_OPEN_DELETEONCLOSE))
            | ffi::SQLITE_OPEN_READONLY;

        if flags & ffi::SQLITE_OPEN_WAL != 0 {
            match open_ro_regular_errno(name) {
                Ok(fd) => {
                    file.cast::<RoWalFile>().write(RoWalFile {
                        base: ffi::sqlite3_file {
                            pMethods: &RO_WAL_IO_METHODS,
                        },
                        fd,
                        absent_paths: std::ptr::null_mut(),
                    });
                }
                Err(libc::ENOENT) => {
                    // 仅当 `-wal` 与 `-shm` 均确认为 `ENOENT`（正式 X 末连接正常 checkpoint 闭库）时，
                    // 允许进入受检空 WAL 态；若残留 `-shm` 或目录不可查，显式拒绝，绝不回落陈旧主库。
                    let wal_bytes = CStr::from_ptr(name).to_bytes();
                    let Some(prefix) = wal_bytes.strip_suffix(b"-wal") else {
                        return ffi::SQLITE_CANTOPEN;
                    };
                    let Ok(wal_path) = CString::new(wal_bytes) else {
                        return ffi::SQLITE_CANTOPEN;
                    };
                    let mut shm_bytes = prefix.to_vec();
                    shm_bytes.extend_from_slice(b"-shm");
                    let Ok(shm_path) = CString::new(shm_bytes) else {
                        return ffi::SQLITE_CANTOPEN;
                    };
                    if !is_enoent(shm_path.as_ptr()) {
                        return ffi::SQLITE_CANTOPEN;
                    }
                    let absent_paths = Box::into_raw(Box::new((wal_path, shm_path)));
                    file.cast::<RoWalFile>().write(RoWalFile {
                        base: ffi::sqlite3_file {
                            pMethods: &RO_WAL_IO_METHODS,
                        },
                        fd: -1,
                        absent_paths,
                    });
                }
                Err(_) => return ffi::SQLITE_CANTOPEN,
            }
            if !out.is_null() {
                *out = ro_flags;
            }
            return ffi::SQLITE_OK;
        }

        if flags & ffi::SQLITE_OPEN_MAIN_DB == 0 {
            return ffi::SQLITE_READONLY;
        }

        let parent = parent_vfs(vfs);
        let Some(open) = (*parent).xOpen else {
            return ffi::SQLITE_CANTOPEN;
        };
        let db_bytes = CStr::from_ptr(name).to_bytes();
        let mut wal_bytes = db_bytes.to_vec();
        wal_bytes.extend_from_slice(b"-wal");
        let Ok(wal_path) = CString::new(wal_bytes) else {
            return ffi::SQLITE_CANTOPEN;
        };
        let mut shm_bytes = db_bytes.to_vec();
        shm_bytes.extend_from_slice(b"-shm");
        let Ok(shm_path) = CString::new(shm_bytes) else {
            return ffi::SQLITE_CANTOPEN;
        };
        let real = file
            .cast::<u8>()
            .add(REAL_OFFSET)
            .cast::<ffi::sqlite3_file>();
        (*real).pMethods = std::ptr::null();
        let mut child_out: c_int = 0;
        let rc = {
            let _guard = MetadataWriteSuppressGuard::enter();
            open(parent, name, real, ro_flags, &mut child_out)
        };
        if !(*real).pMethods.is_null() {
            let state = Box::into_raw(Box::new(RoMainState {
                wal_path,
                shm_path,
                shm_mode: ShmMode::Uninit,
            }));
            file.cast::<RoMainFile>().write(RoMainFile {
                base: ffi::sqlite3_file {
                    pMethods: &RO_MAIN_IO_METHODS,
                },
                real,
                state,
            });
        }
        if !out.is_null() {
            *out = (child_out
                & !(ffi::SQLITE_OPEN_READWRITE
                    | ffi::SQLITE_OPEN_CREATE
                    | ffi::SQLITE_OPEN_EXCLUSIVE
                    | ffi::SQLITE_OPEN_DELETEONCLOSE))
                | ffi::SQLITE_OPEN_READONLY;
        }
        rc
    }

    unsafe extern "C" fn ro_delete(
        _vfs: *mut ffi::sqlite3_vfs,
        _name: *const c_char,
        _sync_dir: c_int,
    ) -> c_int {
        ffi::SQLITE_READONLY
    }

    unsafe extern "C" fn ro_access(
        vfs: *mut ffi::sqlite3_vfs,
        name: *const c_char,
        flags: c_int,
        out: *mut c_int,
    ) -> c_int {
        if flags == ffi::SQLITE_ACCESS_READWRITE {
            if !out.is_null() {
                *out = 0;
            }
            return ffi::SQLITE_OK;
        }
        let parent = parent_vfs(vfs);
        (*parent).xAccess.map_or(ffi::SQLITE_IOERR_ACCESS, |call| {
            call(parent, name, flags, out)
        })
    }

    // --- 公共写/截断/同步阻断 ---

    unsafe extern "C" fn ro_write(
        _file: *mut ffi::sqlite3_file,
        _buf: *const c_void,
        _amt: c_int,
        _offset: ffi::sqlite3_int64,
    ) -> c_int {
        ffi::SQLITE_READONLY
    }

    unsafe extern "C" fn ro_truncate(
        _file: *mut ffi::sqlite3_file,
        _size: ffi::sqlite3_int64,
    ) -> c_int {
        ffi::SQLITE_READONLY
    }

    unsafe extern "C" fn ro_sync(_file: *mut ffi::sqlite3_file, _flags: c_int) -> c_int {
        ffi::SQLITE_READONLY
    }

    // --- WAL 直读 IO 方法（纯 O_RDONLY，永不触发 fchmod/fchown/O_CREAT） ---

    unsafe extern "C" fn ro_wal_close(file: *mut ffi::sqlite3_file) -> c_int {
        let wal = &mut *file.cast::<RoWalFile>();
        if wal.fd >= 0 {
            libc::close(wal.fd);
            wal.fd = -1;
        }
        if !wal.absent_paths.is_null() {
            drop(Box::from_raw(wal.absent_paths));
            wal.absent_paths = std::ptr::null_mut();
        }
        (*file).pMethods = std::ptr::null();
        ffi::SQLITE_OK
    }

    unsafe extern "C" fn ro_wal_read(
        file: *mut ffi::sqlite3_file,
        buf: *mut c_void,
        amt: c_int,
        offset: ffi::sqlite3_int64,
    ) -> c_int {
        if amt < 0 || offset < 0 {
            return ffi::SQLITE_IOERR_READ;
        }
        let wal = &*file.cast::<RoWalFile>();
        if wal.fd < 0 {
            return ffi::SQLITE_IOERR_READ;
        }
        let mut done = 0usize;
        let total = amt as usize;
        let dst = buf.cast::<u8>();
        while done < total {
            let Some(off) = (offset as i64).checked_add(done as i64) else {
                return ffi::SQLITE_IOERR_READ;
            };
            let n = libc::pread(
                wal.fd,
                dst.add(done).cast::<c_void>(),
                total - done,
                off as libc::off_t,
            );
            if n > 0 {
                done += n as usize;
            } else if n == 0 {
                std::ptr::write_bytes(dst.add(done), 0, total - done);
                return ffi::SQLITE_IOERR_SHORT_READ;
            } else if std::io::Error::last_os_error().raw_os_error() == Some(libc::EINTR) {
                continue;
            } else {
                return ffi::SQLITE_IOERR_READ;
            }
        }
        ffi::SQLITE_OK
    }

    unsafe extern "C" fn ro_wal_file_size(
        file: *mut ffi::sqlite3_file,
        out: *mut ffi::sqlite3_int64,
    ) -> c_int {
        let wal = &*file.cast::<RoWalFile>();
        if wal.fd < 0 {
            if !wal.absent_paths.is_null() {
                let (wal_path, shm_path) = &*wal.absent_paths;
                if both_sidecars_absent(wal_path, shm_path) {
                    *out = 0;
                    return ffi::SQLITE_OK;
                }
            }
            return ffi::SQLITE_IOERR_FSTAT;
        }
        let mut st: libc::stat = std::mem::zeroed();
        if libc::fstat(wal.fd, &mut st) != 0 {
            return ffi::SQLITE_IOERR_FSTAT;
        }
        *out = st.st_size as ffi::sqlite3_int64;
        ffi::SQLITE_OK
    }

    unsafe extern "C" fn ro_wal_lock(_file: *mut ffi::sqlite3_file, _level: c_int) -> c_int {
        ffi::SQLITE_READONLY
    }

    unsafe extern "C" fn ro_wal_unlock(_file: *mut ffi::sqlite3_file, _level: c_int) -> c_int {
        ffi::SQLITE_OK
    }

    unsafe extern "C" fn ro_wal_check_reserved_lock(
        _file: *mut ffi::sqlite3_file,
        out: *mut c_int,
    ) -> c_int {
        *out = 0;
        ffi::SQLITE_OK
    }

    unsafe extern "C" fn ro_wal_file_control(
        _file: *mut ffi::sqlite3_file,
        _op: c_int,
        _arg: *mut c_void,
    ) -> c_int {
        ffi::SQLITE_NOTFOUND
    }

    unsafe extern "C" fn ro_wal_sector_size(_file: *mut ffi::sqlite3_file) -> c_int {
        4096
    }

    unsafe extern "C" fn ro_wal_device_characteristics(_file: *mut ffi::sqlite3_file) -> c_int {
        0
    }

    static RO_WAL_IO_METHODS: ffi::sqlite3_io_methods = ffi::sqlite3_io_methods {
        iVersion: 1,
        xClose: Some(ro_wal_close),
        xRead: Some(ro_wal_read),
        xWrite: Some(ro_write),
        xTruncate: Some(ro_truncate),
        xSync: Some(ro_sync),
        xFileSize: Some(ro_wal_file_size),
        xLock: Some(ro_wal_lock),
        xUnlock: Some(ro_wal_unlock),
        xCheckReservedLock: Some(ro_wal_check_reserved_lock),
        xFileControl: Some(ro_wal_file_control),
        xSectorSize: Some(ro_wal_sector_size),
        xDeviceCharacteristics: Some(ro_wal_device_characteristics),
        xShmMap: None,
        xShmLock: None,
        xShmBarrier: None,
        xShmUnmap: None,
        xFetch: None,
        xUnfetch: None,
    };

    // --- 主库 IO 方法（复用 unix 主库锁；SHM 按三态精确分流） ---

    unsafe extern "C" fn ro_main_close(file: *mut ffi::sqlite3_file) -> c_int {
        let _ = ro_shm_unmap(file, 0);
        let main = &mut *file.cast::<RoMainFile>();
        if !main.state.is_null() {
            drop(Box::from_raw(main.state));
            main.state = std::ptr::null_mut();
        }
        let rc = if !(*main.real).pMethods.is_null() {
            (*(*main.real).pMethods)
                .xClose
                .map_or(ffi::SQLITE_OK, |call| call(main.real))
        } else {
            ffi::SQLITE_OK
        };
        (*file).pMethods = std::ptr::null();
        rc
    }

    unsafe extern "C" fn ro_main_read(
        file: *mut ffi::sqlite3_file,
        buf: *mut c_void,
        amt: c_int,
        offset: ffi::sqlite3_int64,
    ) -> c_int {
        let main = &*file.cast::<RoMainFile>();
        let absent_clean =
            !main.state.is_null() && matches!((*main.state).shm_mode, ShmMode::AbsentClean);
        if absent_clean {
            let state = &*main.state;
            if !both_sidecars_absent(&state.wal_path, &state.shm_path) {
                return ffi::SQLITE_IOERR_READ;
            }
        }
        let (real, methods) = main_parts(file);
        let rc = methods
            .xRead
            .map_or(ffi::SQLITE_IOERR_READ, |call| call(real, buf, amt, offset));
        if rc == ffi::SQLITE_OK && absent_clean {
            let state = &*main.state;
            if !both_sidecars_absent(&state.wal_path, &state.shm_path) {
                return ffi::SQLITE_IOERR_READ;
            }
        }
        rc
    }

    unsafe extern "C" fn ro_main_file_size(
        file: *mut ffi::sqlite3_file,
        out: *mut ffi::sqlite3_int64,
    ) -> c_int {
        let (real, methods) = main_parts(file);
        methods
            .xFileSize
            .map_or(ffi::SQLITE_IOERR_FSTAT, |call| call(real, out))
    }

    unsafe extern "C" fn ro_main_lock(file: *mut ffi::sqlite3_file, level: c_int) -> c_int {
        if level > ffi::SQLITE_LOCK_SHARED {
            return ffi::SQLITE_READONLY;
        }
        let (real, methods) = main_parts(file);
        methods
            .xLock
            .map_or(ffi::SQLITE_IOERR_LOCK, |call| call(real, level))
    }

    unsafe extern "C" fn ro_main_unlock(file: *mut ffi::sqlite3_file, level: c_int) -> c_int {
        let (real, methods) = main_parts(file);
        methods
            .xUnlock
            .map_or(ffi::SQLITE_IOERR_UNLOCK, |call| call(real, level))
    }

    unsafe extern "C" fn ro_main_check_reserved_lock(
        file: *mut ffi::sqlite3_file,
        out: *mut c_int,
    ) -> c_int {
        let (real, methods) = main_parts(file);
        methods
            .xCheckReservedLock
            .map_or(ffi::SQLITE_IOERR_CHECKRESERVEDLOCK, |call| call(real, out))
    }

    unsafe extern "C" fn ro_main_file_control(
        file: *mut ffi::sqlite3_file,
        op: c_int,
        arg: *mut c_void,
    ) -> c_int {
        match op {
            ffi::SQLITE_FCNTL_SIZE_HINT
            | ffi::SQLITE_FCNTL_BEGIN_ATOMIC_WRITE
            | ffi::SQLITE_FCNTL_COMMIT_ATOMIC_WRITE
            | ffi::SQLITE_FCNTL_ROLLBACK_ATOMIC_WRITE => return ffi::SQLITE_NOTFOUND,
            ffi::SQLITE_FCNTL_PERSIST_WAL => {
                if !arg.is_null() {
                    let slot = arg.cast::<c_int>();
                    if *slot < 0 {
                        *slot = 1;
                        return ffi::SQLITE_OK;
                    }
                }
                return ffi::SQLITE_NOTFOUND;
            }
            ffi::SQLITE_FCNTL_MMAP_SIZE => {
                if !arg.is_null() {
                    *arg.cast::<i64>() = 0;
                }
            }
            _ => {}
        }
        let (real, methods) = main_parts(file);
        methods
            .xFileControl
            .map_or(ffi::SQLITE_NOTFOUND, |call| call(real, op, arg))
    }

    unsafe extern "C" fn ro_main_sector_size(file: *mut ffi::sqlite3_file) -> c_int {
        let (real, methods) = main_parts(file);
        methods.xSectorSize.map_or(4096, |call| call(real))
    }

    unsafe extern "C" fn ro_main_device_characteristics(file: *mut ffi::sqlite3_file) -> c_int {
        let (real, methods) = main_parts(file);
        methods.xDeviceCharacteristics.map_or(0, |call| call(real))
    }

    unsafe fn delegated_shm_map(
        file: *mut ffi::sqlite3_file,
        page: c_int,
        size: c_int,
        out: *mut *mut c_void,
    ) -> c_int {
        let (real, methods) = main_parts(file);
        let Some(shm_map) = methods.xShmMap else {
            return ffi::SQLITE_IOERR_SHMMAP;
        };
        let rc = {
            let _guard = MetadataWriteSuppressGuard::enter();
            shm_map(real, page, size, 0, out)
        };
        if rc == ffi::SQLITE_OK {
            if !(*out).is_null() || page == 0 {
                ffi::SQLITE_READONLY
            } else {
                ffi::SQLITE_IOERR_SHMSIZE
            }
        } else {
            rc
        }
    }

    unsafe extern "C" fn ro_shm_map(
        file: *mut ffi::sqlite3_file,
        page: c_int,
        size: c_int,
        _extend: c_int,
        out: *mut *mut c_void,
    ) -> c_int {
        *out = std::ptr::null_mut();
        if page < 0 || size <= 0 {
            return ffi::SQLITE_IOERR_SHMSIZE;
        }
        let main = &mut *file.cast::<RoMainFile>();
        if main.state.is_null() {
            return ffi::SQLITE_IOERR_SHMMAP;
        }
        let state = &mut *main.state;
        match &mut state.shm_mode {
            ShmMode::Uninit => {
                let mut st: libc::stat = std::mem::zeroed();
                if libc::lstat(state.shm_path.as_ptr(), &mut st) != 0 {
                    let err = std::io::Error::last_os_error().raw_os_error();
                    if err == Some(libc::ENOENT) && is_enoent(state.wal_path.as_ptr()) {
                        state.shm_mode = ShmMode::AbsentClean;
                        return ffi::SQLITE_READONLY_CANTINIT;
                    }
                    return ffi::SQLITE_CANTOPEN;
                }
                if (st.st_mode as u32 & libc::S_IFMT as u32) != libc::S_IFREG as u32 {
                    return ffi::SQLITE_CANTOPEN;
                }
                state.shm_mode = ShmMode::Delegated;
                delegated_shm_map(file, page, size, out)
            }
            ShmMode::AbsentClean => {
                if both_sidecars_absent(&state.wal_path, &state.shm_path) {
                    ffi::SQLITE_READONLY_CANTINIT
                } else {
                    ffi::SQLITE_IOERR_SHMMAP
                }
            }
            ShmMode::Delegated => delegated_shm_map(file, page, size, out),
        }
    }

    unsafe extern "C" fn ro_shm_lock(
        file: *mut ffi::sqlite3_file,
        offset: c_int,
        n: c_int,
        flags: c_int,
    ) -> c_int {
        if flags & ffi::SQLITE_SHM_EXCLUSIVE != 0 && flags & ffi::SQLITE_SHM_UNLOCK == 0 {
            return ffi::SQLITE_READONLY;
        }
        let main = &*file.cast::<RoMainFile>();
        if main.state.is_null() {
            return ffi::SQLITE_IOERR_SHMLOCK;
        }
        let state = &*main.state;
        match &state.shm_mode {
            ShmMode::AbsentClean => {
                if flags & ffi::SQLITE_SHM_UNLOCK != 0 {
                    return ffi::SQLITE_OK;
                }
                if both_sidecars_absent(&state.wal_path, &state.shm_path) {
                    ffi::SQLITE_OK
                } else {
                    ffi::SQLITE_IOERR_SHMLOCK
                }
            }
            ShmMode::Delegated => {
                let (real, methods) = main_parts(file);
                methods.xShmLock.map_or(ffi::SQLITE_IOERR_SHMLOCK, |call| {
                    call(real, offset, n, flags)
                })
            }
            ShmMode::Uninit => ffi::SQLITE_IOERR_SHMLOCK,
        }
    }

    unsafe extern "C" fn ro_shm_barrier(file: *mut ffi::sqlite3_file) {
        let main = &*file.cast::<RoMainFile>();
        if !main.state.is_null() && matches!((*main.state).shm_mode, ShmMode::Delegated) {
            let (real, methods) = main_parts(file);
            if let Some(call) = methods.xShmBarrier {
                call(real);
                return;
            }
        }
        fence(Ordering::SeqCst);
    }

    unsafe extern "C" fn ro_shm_unmap(file: *mut ffi::sqlite3_file, _delete_flag: c_int) -> c_int {
        let main = &mut *file.cast::<RoMainFile>();
        if main.state.is_null() {
            return ffi::SQLITE_OK;
        }
        let prev = std::mem::replace(&mut (*main.state).shm_mode, ShmMode::Uninit);
        match prev {
            ShmMode::Delegated => {
                let (real, methods) = main_parts(file);
                methods
                    .xShmUnmap
                    .map_or(ffi::SQLITE_OK, |call| call(real, 0))
            }
            ShmMode::AbsentClean | ShmMode::Uninit => ffi::SQLITE_OK,
        }
    }

    static RO_MAIN_IO_METHODS: ffi::sqlite3_io_methods = ffi::sqlite3_io_methods {
        iVersion: 2,
        xClose: Some(ro_main_close),
        xRead: Some(ro_main_read),
        xWrite: Some(ro_write),
        xTruncate: Some(ro_truncate),
        xSync: Some(ro_sync),
        xFileSize: Some(ro_main_file_size),
        xLock: Some(ro_main_lock),
        xUnlock: Some(ro_main_unlock),
        xCheckReservedLock: Some(ro_main_check_reserved_lock),
        xFileControl: Some(ro_main_file_control),
        xSectorSize: Some(ro_main_sector_size),
        xDeviceCharacteristics: Some(ro_main_device_characteristics),
        xShmMap: Some(ro_shm_map),
        xShmLock: Some(ro_shm_lock),
        xShmBarrier: Some(ro_shm_barrier),
        xShmUnmap: Some(ro_shm_unmap),
        xFetch: None,
        xUnfetch: None,
    };
}

fn sqlite_readonly_uri(canonical: &Path) -> Result<String, String> {
    use std::os::unix::ffi::OsStrExt as _;
    let bytes = canonical.as_os_str().as_bytes();
    if bytes.is_empty() || bytes[0] != b'/' {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let mut uri = String::with_capacity("file://".len() + bytes.len() + 32);
    uri.push_str("file://");
    for &b in bytes {
        if b.is_ascii_alphanumeric() || matches!(b, b'/' | b'-' | b'_' | b'.' | b'~') {
            uri.push(b as char);
        } else {
            use std::fmt::Write as _;
            let _ = write!(&mut uri, "%{b:02X}");
        }
    }
    uri.push_str("?mode=ro&readonly_shm=1");
    Ok(uri)
}

/// 缺口态只读打开模拟 X 业务库：
/// 1) 规范化路径并按 SQLite URI 语法逐字节百分号编码，附 `mode=ro&readonly_shm=1`，
///    通过非默认 `history_sim_ro` VFS 只读打开：
///    - 所有存在的普通文件 `-shm` 统一复用 `unix` VFS `unixShmNode` 引用计数（保障 Linux/macOS
///      同进程 POSIX 锁归属），并在临界区经线程局部守卫屏蔽 `fchown`/`fchmod`（`euid == 0` 亦零改元数据）；
///    - `-wal` 永远纯 `O_RDONLY | O_NOFOLLOW | O_CLOEXEC` 直读，零 `fchmod`/`fchown`；
///    - 仅当 `-wal` 与 `-shm` 双 `ENOENT`（正式 X 末连接正常闭库态）允许受检只读主库，绝不建文件、绝不 `immutable`；
/// 2) 打开后核对 `Connection::path()` 与规范化绝对路径完全一致，并开启 `query_only` 与内存临时库。
pub(crate) fn open_readonly_source_db(db: &Path) -> Result<Connection, String> {
    let canonical = db.canonicalize().map_err(failure)?;
    let uri = sqlite_readonly_uri(&canonical)?;
    let vfs = readonly_vfs::name()?;
    let c = Connection::open_with_flags_and_vfs(
        &uri,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI,
        vfs,
    )
    .map_err(failure)?;
    if let Some(expected) = canonical.to_str() {
        if c.path() != Some(expected) {
            return Err(format!(
                "IdentityConflict：模拟 X 只读路径解析不一致（期望 {expected}，实际 {:?}）",
                c.path()
            ));
        }
    }
    c.busy_timeout(std::time::Duration::from_secs(2))
        .map_err(failure)?;
    c.execute_batch("PRAGMA query_only = ON; PRAGMA temp_store = MEMORY;")
        .map_err(failure)?;
    Ok(c)
}

fn inspect_committed_history(
    manifest: &Value,
    expected_x_id: Option<&str>,
    expected_x_epoch: Option<i64>,
    end_pin: Option<(Option<&str>, Option<&str>)>,
    require_committed_frontier: bool,
) -> Result<Value, String> {
    let binding = &manifest["history_simulation_source"];
    if !binding.is_object() {
        return Err("SchemaUnsupported：本会话未冻结模拟 X 原件来源".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let mut c = open_readonly_source_db(db)?;
    let tx = c.transaction().map_err(failure)?;
    let x_meta = |key| -> Result<String, String> {
        tx.query_row("SELECT value FROM x_meta WHERE key=?1", [key], |r| r.get(0))
            .map_err(failure)
    };
    let actual_epoch_raw = x_meta("writer_epoch")?;
    let actual_epoch = actual_epoch_raw
        .parse::<i64>()
        .ok()
        .filter(|e| *e > 0)
        .ok_or("IdentityConflict：模拟 X writer_epoch 非正整数")?;
    if x_meta("profile_revision")? != "x-execution-profile/1"
        || x_meta("profile_mode")? != "simulation"
        || x_meta("history_simulation")? != "true"
        || expected_x_epoch.is_some_and(|e| e != actual_epoch)
    {
        return Err("IdentityConflict：指定 X 模型或当前 writer epoch 不符".into());
    }
    let raw_profile: String = tx
        .query_row(
            "SELECT v FROM x_sim_meta WHERE k='authority_profile'",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    let profile: super::runtime::Profile =
        serde_json::from_value(strict_json(raw_profile.as_bytes())?).map_err(failure)?;
    if profile.session_id != required(manifest, "session_id")?
        || profile.session_generation != required(manifest, "session_generation")?
    {
        return Err("IdentityConflict：X 与 E 的会话或化身不同".into());
    }
    if profile.source_namespace != required(binding, "source_namespace")?
        || profile.source_epoch != required(binding, "source_epoch")?
    {
        return Err("IdentityConflict：X 持久来源与 E 冻结来源不同".into());
    }
    if expected_x_id.is_some_and(|id| profile.x_id != id)
        || digest(&serde_json::to_value(&profile.model).map_err(failure)?)
            != required(binding, "model_content_hash")?
    {
        return Err("IdentityConflict：X 身份或模型与冻结范围不同".into());
    }
    // #1381 全量冷审：逐批重演 x_sim_batches，核对 x_sim_originals 原字节与总数、bust 累计及末状态。
    super::runtime::validate_existing(&tx, &profile, actual_epoch)?;
    if super::store::pending_batch(&tx)?.is_some() {
        return Err("MissingDependency：模拟 X 尚有未提交在途批，无法证明完整结束界".into());
    }
    let in_flight: i64 = tx
        .query_row(
            "SELECT count(*) FROM x_exact_commands WHERE state IN ('ExecutionRequested','ExecutionReady','MayHaveCalled')",
            [],
            |r| r.get(0),
        )
        .map_err(failure)?;
    if in_flight != 0 {
        return Err("MissingDependency：模拟 X 存在在途执行命令，尚未落批结束界".into());
    }
    let raw_state: String = tx
        .query_row("SELECT v FROM x_sim_meta WHERE k='state'", [], |r| r.get(0))
        .map_err(failure)?;
    let state: super::model::State =
        serde_json::from_value(strict_json(raw_state.as_bytes())?).map_err(failure)?;
    let state_hash = digest(&serde_json::to_value(&state).map_err(failure)?);
    let mut batches: Vec<(i64, String, Value)> = Vec::new();
    {
        let mut stmt = tx
            .prepare("SELECT id, result FROM x_sim_batches")
            .map_err(failure)?;
        let rows = stmt
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(failure)?;
        for row in rows {
            let (id, raw) = row.map_err(failure)?;
            let receipt = strict_json(raw.as_bytes())?;
            if canonical_json(&receipt) != raw || receipt["request_id"] != id {
                return Err("IdentityConflict：模拟 X 批回执不规范".into());
            }
            let bar = receipt["bar_index"]
                .as_i64()
                .ok_or("IdentityConflict：模拟 X 批缺 bar_index")?;
            batches.push((bar, id, receipt));
        }
    }
    batches.sort_by_key(|(bar, _, _)| *bar);
    match batches.last() {
        Some((last_bar, last_id, _)) => {
            if state.last_bar != Some(*last_bar)
                || state.last_request_id.as_deref() != Some(last_id.as_str())
            {
                return Err("IdentityConflict：模拟 X 末状态与批前沿不一致".into());
            }
        }
        None => {
            if state.last_bar.is_some() || state.last_request_id.is_some() {
                return Err("IdentityConflict：模拟 X 空批表与末状态不一致".into());
            }
            if require_committed_frontier {
                return Err(
                    "MissingDependency：模拟 X 空快照无已提交批前沿，不能证明外部调度已覆盖本次缺口"
                        .into(),
                );
            }
        }
    }
    if let Some((end_batch_id, end_receipt_digest)) = end_pin {
        match (end_batch_id, end_receipt_digest) {
            (Some(id), Some(expected_digest)) => {
                if state.last_request_id.as_deref() != Some(id) {
                    return Err(
                        "MissingDependency：指定结束批不是模拟 X 当前完整前沿，单一 QueryBatch 不能证明整段无漏报"
                            .into(),
                    );
                }
                let raw: String = tx
                    .query_row("SELECT result FROM x_sim_batches WHERE id=?1", [id], |r| {
                        r.get(0)
                    })
                    .map_err(failure)?;
                if sha256_hex(raw.as_bytes()) != expected_digest {
                    // DevSkim: ignore DS197836 内容寻址摘要
                    return Err("IdentityConflict：指定 X 结束批的完整回执摘要不同".into());
                }
            }
            (None, None) => {
                if state.last_request_id.is_some() || !batches.is_empty() {
                    return Err("MissingDependency：模拟 X 已有已提交批，须指定完整结束批".into());
                }
            }
            _ => {
                return Err("InvalidDomain：模拟 X 结束批号与回执摘要须成对提供".into());
            }
        }
    }
    let mut originals = Vec::new();
    for (_, _, receipt) in &batches {
        let docs = receipt["originals"]
            .as_array()
            .ok_or("StorageUnavailable：模拟批缺原件列表")?;
        for doc in docs {
            originals.push(doc.clone());
        }
    }
    tx.commit().map_err(failure)?;
    Ok(json!({
        "x_id": profile.x_id,
        "x_writer_epoch": actual_epoch.to_string(),
        "last_bar": state.last_bar,
        "last_request_id": state.last_request_id,
        "state_content_hash": state_hash,
        "batch_count": batches.len().to_string(),
        "originals": originals
    }))
}

/// #1375 R4：先持模拟 X 前沿共享顺序锁，再在 E 放行事务内实时冷审已冻结模拟 X 库的
/// 全量已提交批与原件前沿；调用者须持续持有返回的 `FrontierGuard` 至 E `tx.commit()` 完成，
/// 使 X 无法在核对完毕与本次 E 提交落盘之间推进新批。
pub(crate) fn committed_capture_frontier(
    manifest: &Value,
    expected_x_id: Option<&str>,
    expected_x_epoch: Option<i64>,
    require_committed_frontier: bool,
) -> Result<(Value, FrontierGuard), String> {
    let binding = &manifest["history_simulation_source"];
    if !binding.is_object() {
        return Err("SchemaUnsupported：本会话未冻结模拟 X 原件来源".into());
    }
    let db = Path::new(required(binding, "x_db")?);
    if !db.is_absolute() {
        return Err("InvalidDomain：X 原件库须为冻结绝对路径".into());
    }
    let guard = super::store::lock_frontier_shared(db)?;
    let history = inspect_committed_history(
        manifest,
        expected_x_id,
        expected_x_epoch,
        None,
        require_committed_frontier,
    )?;
    Ok((history, guard))
}

/// #1375：按显式结束批与完整回执摘要核验模拟 X 全部已提交批（供冷审与回归测试使用）。
#[cfg(test)]
pub(crate) fn committed_capture_history(
    manifest: &Value,
    x_id: &str,
    x_epoch: i64,
    end_batch_id: Option<&str>,
    end_receipt_digest: Option<&str>,
) -> Result<Value, String> {
    inspect_committed_history(
        manifest,
        Some(x_id),
        Some(x_epoch),
        Some((end_batch_id, end_receipt_digest)),
        false,
    )
}
