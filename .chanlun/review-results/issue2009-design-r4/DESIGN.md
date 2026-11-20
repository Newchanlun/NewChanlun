# #2009 第四轮方向简报

**选定**：设计 2：在 owner 连接的两个生产出生点安装无状态 SQLite 授权回调（票面方向 3），静态门第三轴整体不做。嫁接：设计 1 的「不做测试/生产分类」与「.github 逐字节不变」；设计 3 与两位评委指出的 pragma_update、savepoint() API 形态进测试表；评委 2 的 h1_close_after_failure 对齐写进 installed。评委 1 的登记册、评委 2 的 begin 自检与 DEFENSIVE 经开码核实后不采纳。

**目标**：#2009 要把「owner 连接上不得发 SAVEPOINT／ROLLBACK TO、不得写 schema_version」变成结构性约束。第四轮改走票面方向 3（授权器），静态门第三轴不再做。本设计来自读源码与合并模拟，未运行 cargo。

## 1 换掉的前提
前三轮共用一句前提：「脚本读 Rust 源码文本，能判出哪段只在测试下编译」，三轮反例全落在这一步。第四轮不读源码。owner 上的任何 SQL 都要在该句柄上 prepare，SQLite 3.53.2 在 prepare 时回调授权器并拒绝。语句写在哪、怎么拼出来都不是判定输入。我复核的依据（libsqlite3-sys 0.38.2 的 sqlite3.c）：:131705-131717 三种 savepoint 语句同走 `sqlite3AuthCheck(SQLITE_SAVEPOINT)`，调用点只有 :183510/:183515/:183520；:145129 PRAGMA 以名与值过授权，读时值为 NULL；:126209-126222 `sqlite3_set_authorizer` 令全部已编译语句过期；:126346-126366 回调返回 OK 时不改语法树、不分配。

## 2 机制
新文件 `rust/src/bin/s_session_v3/audit_owner/raw_sql_floor.rs`，不带 cfg 门：

- `unsafe extern "C" fn floor(_ctx, action, first, second, _db, _origin) -> c_int`。`action == SQLITE_SAVEPOINT` 返回 `SQLITE_DENY`。`action == SQLITE_PRAGMA`、`second` 非空、且 `first` 为空或 `CStr::from_ptr(first).to_bytes().eq_ignore_ascii_case(b"schema_version")`，返回 `SQLITE_DENY`。其余 `SQLITE_OK`。无状态、无分配、不解码 UTF-8、不看库名。
- `pub(super) fn installed(connection: Connection) -> Result<Connection, String>`。调 `ffi::sqlite3_set_authorizer(connection.handle(), Some(floor), null_mut())`；rc 非 `SQLITE_OK` 得 `Err(super::invalid(..))`。随后照 `fn new`（audit_owner.rs:439-440）的收尾写：`#[cfg(all(feature = "s_incremental", unix))] let result = crate::h1_close_after_failure(&connection, result, false);`，最后 `result.map(|()| connection)`。裸 FFI 先例见 fd_wal.rs:1171-1179。

`audit_owner.rs` 只改三行：
1. :204 `mod construction_state;` 之后加 `mod raw_sql_floor;`
2. :415 改为 `Self::new(raw_sql_floor::installed(open_db(db)?)?)`
3. :987 改为 `*output = Some(Self::new(raw_sql_floor::installed(connection)?)?);`

`fn new` 私有，生产调用只有这两处；:2234、:2263 是测试，不动。不装进 `open_db`，因为非 owner 命令和测试共用它，ram.rs 的测试就在 `open_db` 连接上用 SAVEPOINT。

三项提议不采纳：
- begin 自检（judge 2）。裸 prepare 探针被拒时 SQLite 给连接分配并留住错误值（sqlite3.c:36576），会动保留量读数；任何自检都要改 `begin`，而 #1855 把 `begin` 挪进了泛型 impl，必冲突。
- `SQLITE_DBCONFIG_DEFENSIVE`（judge 2）。它把写 cookie 变成静默空操作而非拒绝（:147000-147003），还改 writable_schema 等行为，未证。
- authorizer 调用点登记册（judge 1）与 syn 门（设计 3）。两者都回到读源码文本，设计 3 还漏 `pragma_update(None, "schema_version", v)`。

## 3 从第三轮删除
`origin/impl/2009-raw-sql-axis@94d2ec5e` 整支弃用，不 rebase，不 cherry-pick。新分支自 origin/main 起。`.github/` 全目录、`rust/Cargo.toml`、`rust/Cargo.lock` 与 origin/main 逐字节相同，不新增 `test_check_prod_no_test_hooks_raw_sql.py`。原有两条轴因此原样保留，`gen-prod-banned-literals.py` 不碰。

## 4 31 条字面量
一条不动，不建豁免表。30 条测试字面量都跑在非 owner 连接上。我核过的：ram.rs 经 `with_mixed_control_fixture` 用 `open_db` 连接（v2/mod.rs:3909-3913）；object_index.rs 用 `database()` 内存库（:4893）；content_publication.rs:2991 内存库；content_store.rs:1815-1822 自开连接；其余 8 条在 E 连接。datum_io.rs:106 到不了 prepare。首轮 CI 若有既有测试因 AUTH 变红，说明有 SAVEPOINT 真跑在 owner 上，按本票真实发现上报，不改测试绕过。

## 5 测试
全部放新文件的 `#[cfg(test)] mod tests`。测试字面量须全 ASCII；不得整串匹配 `[A-Z][A-Z0-9_]{7,}`（单写 "SAVEPOINT" 会被当成环境变量名）；16 字节以上的不含 testonly、for_test、_probe、probe_、inject、fault（default 含 fault）。否则 `prod-banned-literals.txt` 会变。断言比 `rusqlite::ErrorCode`，不比报错文本。下文 AUTH 指 `ErrorCode::AuthorizationForStatementDenied`，F 指 `installed(Connection::open_in_memory()?)`。

1. `savepoint_family_is_refused_at_prepare`：F 上 `SAVEPOINT a`、`RELEASE a`、`ROLLBACK TO a`、`ROLLBACK TRANSACTION TO SAVEPOINT a`、`RELEASE SAVEPOINT a`、`savepoint a`、`/*x*/ SaVePoInT a`、`ROLLBACK/**/TO a` 均得 AUTH，`is_autocommit()` 仍为真。对照：未安装连接上 `SAVEPOINT a` 成功；无保存点时 `ROLLBACK TO a` 的错误码不是 AUTH。
2. `batch_stops_at_the_refused_statement`：`INSERT; SAVEPOINT a; INSERT` 得 Err(AUTH)，表里恰 1 行。
3. `refusal_ignores_how_the_text_was_built`（表驱动）：`concat!("SAVE", "POINT a")`、`format!` 拼接、`String::from_utf8(b"SAVEPOINT a".to_vec())`、`"\x53AVEPOINT a"`、`macro_rules!` 产出的串、`match` 里紧邻 `#[cfg(test)]` 臂的默认臂中的串、带 `#[cfg(feature = "s_session")]` 的 const，均得 AUTH。API 形态：`conn.savepoint()`、`pragma_update(None, "schema_version", 7)`、`pragma_update(Some(DatabaseName::Main), "schema_version", 7)`，均得 AUTH。
4. `schema_version_write_is_refused_in_every_spelling`：`PRAGMA schema_version=7`、`main.schema_version = 7`、`temp.schema_version=7`、`SCHEMA_VERSION=7`、带双引号的名字、`schema_version(7)`、`schema_version=-1` 均得 AUTH；之后读 `PRAGMA main.schema_version` 与之前相等。
5. `reads_and_other_pragmas_are_untouched`：读到的 cookie 与做过同样 DDL 的未安装连接相等；`user_version=7` 读回 7；`schema_versionx=1` 与 `xschema_version=1` 返回 Ok；`BEGIN IMMEDIATE`、INSERT、`COMMIT`、`ROLLBACK` 与 `transaction()?.commit()` 正常。
6. `d2_replay_cannot_restore_cookie`：事务内读出 c0，DROP 再 CREATE 表，`PRAGMA main.schema_version=<c0>` 得 AUTH，再读不等于 c0。
7. `d1_replay_cannot_undo_rows`：事务内 INSERT 一行，`SAVEPOINT s` 与 `ROLLBACK TO s` 均得 AUTH，行数多 1，`total_changes()` 多 1。
8. `statement_cached_before_install_is_refused_after`：未安装连接上 `prepare_cached("SAVEPOINT a")` 后归还，再 `installed`。再次 `prepare_cached` 返回 Ok（命中缓存），`execute` 返回 Err，`is_autocommit()` 仍为真。预期码 AUTH，依据 sqlite3.c:94481-94503，属推断。首跑若不是 AUTH，上报实际码后钉死，不得放宽成只判 `is_err()`。
9. `owner_opened_by_path_is_born_refusing`：照 audit_owner.rs:2231-2233 用 `prepared::tests::Fixture` 发布一轮，`AuditConnection::open(&f.db_path())`。经测试专用 Deref 执行 `SAVEPOINT a` 得 AUTH。`begin(Deferred)` 成功（它要读 `PRAGMA main.schema_version`）；事务内 `ROLLBACK TO a` 与 `PRAGMA main.schema_version=1` 得 AUTH；`read_end()`。再走一轮 begin 与 read_end 后仍得 AUTH。
10. `h1_rebuilt_owner_is_born_refusing`（`#[cfg(all(feature = "s_incremental", unix))]`）：`AuditConnection::initialize_rebuilt_owner(Connection::open_in_memory()?, &mut out)`，对 out 执行 `SAVEPOINT a` 得 AUTH。

三轮反例在新机制下的结果：双路径引入的文件、旧 ROOTS 外的模块、`include!`、内联 `#![cfg(test)]`、`cfg_attr(path)` 与 `#[path]`、`feature = "production_session"` 常量、挂在 match 臂／字段／变体上的 `#[cfg(test)]`（含独审在真实 audit_owner.rs 上演示的默认臂）、属性里带 `[` 的块注释、带元数据和标签的宏、`#[::test]`、BOM 与 shebang，都只是「语句文本放在哪」。文本不是输入，语句一旦在 owner 上执行即得 AUTH，由测试 3 演示。属性里的字符串不是被执行的 SQL，无物可拒。`<{ 1 }>` 误报不存在，因为没有扫描。豁免表不存在，所以没有「比解码值」和「前缀匹配变异存活」；名字匹配的同类变异由测试 4、5 杀掉。

变异对照：去掉 :415 的 `installed`，9 红；去掉 :987 的，10 红；SAVEPOINT 臂改放行或改返回 `SQLITE_IGNORE`，1、7 红；去掉「值非空」条件，5、9 红；名字改大小写敏感，4 红；改前缀或包含匹配，5 红；拒绝一切带值 PRAGMA，5 红。`installed` 的 rc 非 OK 分支没有测试：3.53.2 对活句柄恒返回 OK（:126214-126222），它只为失败关闭而留，PR 里如实写明。

## 6 冲突
我重跑了三方合并。三行改动对 #1855@9e57032b 与 #2105@4402c64d 的 audit_owner.rs 执行 `git merge-file`，退出码均为 0。对照：再改 `begin` 和 :2234、:2263 会出 3 处冲突。两个 PR 里这两个调用点仍在 `impl AuditConnection` 内、传 rusqlite `Connection`（PR 行 :437、:977），合并后能编译是推断。新文件名在两个 PR 里都不存在。`.github` 零改动，与 #2098 和在途的 ci.yml 改动无交集。

git 不会提示的语义冲突：#1855 的 `LegacyOwner::unseal`（step_reader.rs:106-108）执行 `conn.authorizer(None)`，会清掉底线；`ChargedOwner` 连接不经过 `installed`。两者目前只在测试下编译。

## 7 明知不拦
- 用 Rust API 改写 owner 句柄的授权槽（`Connection::authorizer`、`sqlite3_set_authorizer`）。SQL 本身改不了授权槽。main 上生产代码没有一处对 owner 句柄这样做：fd_wal.rs:1171 与 native_n1.rs:1433 装在各自打开的句柄上，mixed_sql.rs 与 content_store.rs 的全在测试里。
- 将来在 audit_owner.rs 新增不经 `installed` 的第三处 `Self::new(` 调用。
- 非 owner 连接、`deserialize`、其他连接或进程写同一个库、任意 unsafe FFI。
- 票面两类之外、同样能绕过 total_changes 与 schema_version 的语句。
- 发现时机是运行时拒绝，不是 CI 静态变红。测试没走到的生产路径若发 SAVEPOINT，会以语句被拒暴露，属失败关闭。
- StageMemo 不在 main，也不在 #1855，端到端只能断言审计输入。
- 性能与「其余语句行为不变」是读源码的推断，未测量。

## 8 独审会跑的检查
- `git diff --stat origin/main...HEAD` 只有 audit_owner.rs（3 行）与新文件；`git diff origin/main -- .github rust/Cargo.toml rust/Cargo.lock` 为空。
- 本机可跑：`python3 .github/scripts/check-prod-no-test-hooks.py` 仍输出 `violations=0`；`python3 .github/scripts/gen-prod-banned-literals.py --check .` 通过。两条在 origin/main 上我都跑过，结果如此。
- 远端或 CI：`cargo test --locked --features s_session --bin s_structure_session raw_sql_floor` 跑 1 至 9；10 由 `test-feature-delta.sh s_capture_native_testonly`（ci.yml:616-627）执行。
- 精确 head 上 `ci-ok` 绿。作为「其余行为不变」证据的既有锁：rust-test-s-session 全分片、s-sequence-1488、s-fields-native-1488、rust-test-production-session、零全局分配锁（ci.yml:1102）。任何一条变红都按真实发现上报。
- 对两个 PR 头重跑 `git merge-file -p <改后> <main> <PR>`，退出码 0。

用到的原则：Attack the Premise 让我放弃第四个读源码的修法；Subtract Before You Add 让我删掉第三轴而不是再加一层；Test Behavior, Not Implementation 让测试只断言错误码与可读回的状态；Prove It Works 让我把没运行的结论逐条标成推断。
