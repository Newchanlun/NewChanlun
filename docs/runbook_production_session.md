# production_session 运行手册（simulation / dry-run）

> #1769（ADR 0039 迁移步骤 1，#1523-L）。场所写代码、生产签锚（#1657）、P0 场所 profile 与成本项签署均不在骨架范围。
> 已部署 ADR 0065 的实例拒启时，见 [TB-09 端点运维](#端点拒启与原址续服2130)。

## 构建

```bash
cd rust && cargo build --release --features production_session \
  --bin production_session --bin x_execution_session \
  --bin s_structure_session --bin e_economic_session --bin b_chong_session
```

`production_session` feature 只含 `s_session`（S/E/B 会话依赖与 X 骨架所需 rusqlite/libc），
不含 `backtest_bin`、`nautilus`（ADR 0039 B11）。launcher 从自身所在目录找四个域进程二进制。

## 进程与隔离

| 域 | 二进制 | 自有库 | 锁 | epoch |
|---|---|---|---|---|
| S | `s_structure_session serve --protocol-revision s-session/3` | `s.db` | `<db>.writer.lock` | `meta.writer_epoch` |
| E | `e_economic_session serve` | `economic.e.db` | 同上 | `meta(k='writer_epoch')` |
| Bᵢ | `b_chong_session serve --chong <id>` | `economic.b[i].db` | 同上 | 同上 |
| X | `x_execution_session serve` | `x.db` | 同上 | `x_meta.writer_epoch` |

launcher 不以写者身份打开域库；各域进程自行持锁与核验 epoch。S/E/B 任一异常退出，launcher 回收本次其余域、退出码 1。
已部署 ADR 0065 两阶段启动时，**最终接纳／发送放行前** X 是必需成员：X 准备、绑定或末次核验失败、退出，或域收到监督管道 EOF，均中止整组启动，关闭本次已开监听并退出；E/B 不消费关库标记、不补写标记、不接客。初始化／绑定许可不是最终放行。
**最终放行后**，X 单独退出只记日志，S/E/B 继续；监督管道 EOF 后仍持锁服务的进程按[第 1 节](#1-结束仍持写者锁的孤儿)处置。
旧 simulation / dry-run 骨架没有两阶段放行，X 退出只记日志；收到 SIGTERM/SIGINT 后向存活子进程发 SIGTERM，超出 10 秒宽限期则强制回收。
已部署有序停止的正式会话由 launcher 先向 S、E 和各 B 的控制管道写停止字节；停机可能失败，按[第 8 节](#8-选对启动停止与恢复入口)逐域核实。

## manifest（`production-session-manifest/1`）

```json
{
  "manifest_revision": "production-session-manifest/1",
  "profile": "simulation",
  "state_dir": "/abs/launcher-state",
  "execution_capabilities": {"namespaces": ["hl.perp.BTC"]},
  "structure_source": {"category": "TestOnlyStructure", "namespaces": ["testonly.tick.ohlc"]},
  "s": {"db": "...", "session": "...", "catalog": "...", "profile": "...", "clock_plan": "...",
        "session_generation": "1", "delivery_retain_generations": "4",
        "admission_job_limits": "/abs/s-control/s-admission/limits.json", "writer_epoch": "1",
        "socket": "...", "resource_config": "<s-structure-resources/1 文件>"},
  "economic": {"manifest": "<economic-manifest/1 文件>", "e": {"db": "...", "epoch": "1"},
               "b": [{"chong": "one", "db": "...", "epoch": "1"}]},
  "x": {"db": "...", "profile": "<x-execution-profile/1 文件>", "writer_epoch": "1"}
}
```

### 结构源声明

- `category` 只认 `UsEquityStockLineTick`、`TestOnlyStructure`（ADR 0020:151-154、ADR 0023:9-34）。
- `namespaces` 与 `execution_capabilities.namespaces` 相交即 `InvalidDomain`，在拉起 S、创建 S 库之前退出——
  HL 行情即使与美股 bar 同形、类别标成个股线也不进 S。
- launcher 每次启动在拉起域之前，把 manifest 的规范声明写到 `<state_dir>/structure-source.json`（#1845）。
- S 库不存在：launcher 以 `init --protocol-revision s-session/3 ... --structure-source <state_dir>/structure-source.json` 建库，
  声明作为库固定属性落 `meta.structure_source`。
- launcher 每次调用 S `serve --protocol-revision s-session/3` 都传同一文件的 `--structure-source`。
  S 在取得自身写锁、完成原 admission 后，读取文件并与 `meta.structure_source` 的规范文本逐字比较。
  缺声明、文件不可读或损坏、库中声明损坏或不一致时，S 非零退出，不监听 socket；不一致错误点名两侧规范声明。
  launcher 按现有监督合同记录 S critical `exit`，最终 `stopped.failed=true`、退出码 1；S 错误文本写 S stderr。
- standalone S v3 `serve` 的 `--structure-source` 可选；不传时保持既有合同，不额外核声明。
- S.AcceptInput（`raw_input::accept_events`，v1/S2/S3 共用）对声明之外的 `source_namespace` 返回 `InvalidDomain`，
  不落行。不带声明的既有 TestOnly 库行为不变（但进不了 production_session）。

S `serve` 需要准入锚（`<db>.control-owner.json` 和该 owner 指定的准入控制目录内的 `s-admission/{limits,binding}.json`）。它不从 launcher 的 `state_dir` 推导。
生产首签归 #1657，未决前只能用 TestOnly 夹具造锚。

## X 执行 profile（`x-execution-profile/1`）

```json
{"profile_revision": "x-execution-profile/1", "mode": "simulation",
 "endpoint": null, "tb09_fingerprint": null,
 "credential_scope": {"env": "NC_X_VENUE_CREDENTIAL", "file": "/abs/credential-file"}}
```

- `mode` 必须等于 manifest `profile`。
- 凭据：launcher 读 `credential_scope.file`，只以 `credential_scope.env` 注入 X 子进程；S/E/B 以清空环境启动
  （只放回 PATH 与 S 的两个 admission 声明变量），launcher 自身环境不写凭据。凭据值永不落库、不打印。
- experiment/production 缺凭据：X 在构造任何传输之前以 `MissingDependency` 非 0 退出。
- production 缺 `tb09_fingerprint`：X 持久化 `send_state=refused`、`send_refusal_reason=MissingTb09Fingerprint`。
- 写调用（`submit`/`cancel`）恒返回 `UnsupportedCapability`；本步不含任何场所写代码。
- 查询：`x_execution_session query --db x.db`（只读）。

## simulation / dry-run 启动

```bash
production_session --manifest production.json   # 前台运行；Ctrl-C / SIGTERM 回收全部子进程
```

dry-run 与 simulation 同一流程：X 不需要凭据，不连接端点。

## 日志

launcher 日志写 stderr，每行 `production_session {json}`，经 `redact` 过滤（移植 `381fda3f`
`trading_system/execution/hl_paper_launcher.py:46-53` 的 `_redact`）：键名含
private key / secret / password / token / credential / api key（不以 `_env` 结尾）的值整体遮蔽；
24 位以上纯 `[A-Za-z0-9_-]` 字符串遮蔽。

## H1 生效条件

只有以 `s_session,s_incremental` 构建的 S 写者才启用 H1 准入。本手册[构建节](runbook_production_session.md#L9)的现有命令是 `docs/runbook_production_session.md:9-11`：

```bash
cd rust && cargo build --release --features production_session \
  --bin production_session --bin x_execution_session \
  --bin s_structure_session --bin e_economic_session --bin b_chong_session
```

该命令只启用 `production_session`，其依赖为 `s_session`，不含 `s_incremental`，因此不会启用 H1。feature 定义见 [`rust/Cargo.toml:81-91`](../rust/Cargo.toml#L81)。H1 写者构建沿用 [CI 的生产增量构建命令](../.github/workflows/ci.yml#L563)，出处 `.github/workflows/ci.yml:563`，在 `rust/` 目录执行：

```bash
../.github/scripts/run-cargo-with-telemetry.sh cargo build --release --locked --features s_session,s_incremental --bin s_structure_session --jobs 1
```

下述 `s-launcher/4` 的 `start-s`、`recover` 只适用于独立 S。ADR 0065 管辖的端点目录改走[正式会话入口](#8-选对启动停止与恢复入口)，不得使用 S 或 E/B Python 控制器。

增量构建的 v3 `serve` / `advance` / `recover` 必须显式传 `--resource-config`。`serve` 的必填检查见 [`writer_cli.rs:426-429`](../rust/src/bin/s_session_v3/writer_cli.rs#L426-L429)，`s-launcher/4` 由 [`start-s` 传入](../s_session/s_service_control.py#L733)。`advance` / `recover` 的允许参数表见 [`writer_cli.rs:82-93` 的 ADVANCE_FLAGS](../rust/src/bin/s_session_v3/writer_cli.rs#L82) 与 [`:104-113` 的 RECOVER_FLAGS](../rust/src/bin/s_session_v3/writer_cli.rs#L104)，必填检查分别在同文件 [`:464-468`](../rust/src/bin/s_session_v3/writer_cli.rs#L464) 与 [`:530-534`](../rust/src/bin/s_session_v3/writer_cli.rs#L530)。

`s-launcher/4` 的 `recover` 由 [`s_session/s_service_control.py:845-847`](../s_session/s_service_control.py#L845) 先确认原 S 已停止，再从该 `start-s` 进程记录的冻结 `resource_identity` 取路径，传入 `--resource-config` 并核验身份，见同文件 [`:862-868`](../s_session/s_service_control.py#L862)。`start-s` 冻结资源、传参并登记身份的位置分别是同文件 [`:725`](../s_session/s_service_control.py#L725)、[`:733`](../s_session/s_service_control.py#L733)、[`:744`](../s_session/s_service_control.py#L744)。不得另造资源档或改用当前配置的替代文件。

仅 `s_session` 的构建仍走原完整审计，不产生 H1 冷认证证据，不能作为 H1 验收。只换 feature 的重跑不证明 H1 被消费：H1 只经正式写者入口（`serve` / `advance` / `recover`，即 [`driver::Driver`](../rust/src/bin/s_session_v3/driver.rs#L84) 与 [`audit_owner::PublishPhase`](../rust/src/bin/s_session_v3/audit_owner.rs#L286-L318) 的正式发布路径）生效；测试专用的 [`Runtime::commit`](../rust/src/bin/s_session_v3/prepared.rs#L464-L478) 一类不带 [`bound_audit`](../rust/src/bin/s_session_v3/prepared.rs#L542) 的路径绕过 H1，不能作为 H1 验收。正式写者入口的接入与下游消费，由 [#1419（g77）](https://github.com/xy7365527-lang/NewChanlun/issues/1419) 和 [#1673（全 95）](https://github.com/xy7365527-lang/NewChanlun/issues/1673) 各自承接，本节只留指针。

## H1 写入完整性 fail-stop

本节是 [#1481](https://github.com/xy7365527-lang/NewChanlun/issues/1481) 的 H1 冷认证到写者交接失败处置合同，适用于 Unix 上的 `s_incremental` 写者。完整性拒绝会保留 `NO_CKPT_ON_CLOSE=true`，刻意保留现场可能存在的 `-wal/-shm`，避免失败关闭时检查点改写主库/WAL。遇到下列拒绝，先停机保全，再交人工恢复门。

### 识别触发类别

[具名分类器](../rust/src/bin/s_structure_session.rs#L406) 精确匹配以下八类。表内路径相对仓库根目录。

| 错误原名 | 实际判据 | 分类位置 |
|---|---|---|
| `SourceIdentityChanged` | 路径或持有 FD 的身份/stat 与固定原件不符 | `rust/src/bin/s_structure_session.rs:409`；`rust/src/bin/s_session_v3/admission_provider.rs:75-86` |
| `SourcePathLost` | 路径元数据无法复核 | `rust/src/bin/s_structure_session.rs:410`；`rust/src/bin/s_session_v3/admission_provider.rs:77` |
| `SourceFdLost` | 持有 FD 的元数据无法复核 | `rust/src/bin/s_structure_session.rs:411`；`rust/src/bin/s_session_v3/admission_provider.rs:76` |
| `SourceMetadataUnavailable` | 原件元数据不可得，无法证明只是自身暂时失败 | `rust/src/bin/s_structure_session.rs:412`；`rust/src/bin/s_session_v3/admission_provider.rs:50`、`:64` |
| `SourceWalChanged` | 转换交接所需空 WAL 的类型、硬链接数、属主或长度不符，或固定 WAL 不是合法空 WAL | `rust/src/bin/s_structure_session.rs:413`；`rust/src/bin/s_session_v3/admission_provider.rs:141-149`、`:400-402` |
| `SourceTypeOrHardlinkUnsupported` | 原件不是普通文件/目录，或文件硬链接数不为 1 | `rust/src/bin/s_structure_session.rs:414`；`rust/src/bin/s_session_v3/admission_provider.rs:50-52` |
| `SourceChangedDuringPin` | 打开 FD 前后的原件 stat 不一致 | `rust/src/bin/s_structure_session.rs:415`；`rust/src/bin/s_session_v3/admission_provider.rs:64-66` |
| `ColdConversionMediumUnsupported` | 转换凭据要求 `MainOnly`，实际介质不符 | `rust/src/bin/s_structure_session.rs:416`；`rust/src/bin/s_session_v3/admission_provider.rs:388-390` |

Clamp 与迁移后 `data_version` 连续性复核还会以 `HistoricalAuditStale：` 为前缀报告下列完整性拒绝。固定文本逐字列出；底层 I/O 错误没有固定子类名，须保留完整错误文本。

| 错误文本或底层错误 | 实际置位判据与位置 |
|---|---|
| `HistoricalAuditStale：` 后接底层打开或元数据错误；`路径与持有文件身份/stat不一致` | 主库/WAL 打开失败，持有 FD 或路径 stat 失证，或二者 stat 不同。`rust/src/bin/s_session_v3/audit_owner/history_clamp.rs:45-65` |
| `H1组件要求既有WAL域，不自动改变journal_mode` | 实际 `journal_mode != "wal"`。同文件 `:144-149` |
| `HistoricalAuditStale：` 后接底层 WAL 头读取错误；`文件观测期间发生变化` | WAL 头读取失败，或读头前后主库/WAL stat 改变。同文件 `:203-221` |
| `锁内观测期间文件变化` | 一次锁内观测前后的文件集合不相等。同文件 `:229-254` |
| `私有认证交接期间发生外部SQLite提交` | 第二把锁首检的 `data_version` 与第一把锁继承值不同。同文件 `:258-263` |
| `版本、文件、控制原件、写计数或连接域改变` | 当前观测与夹持基线不相等。同文件 `:266-270` |
| `私有认证交接期间发生外部SQLite提交`；`失败后源连续性失证：{error}` | 迁移后任一失败收口时，复核 `data_version` 不等于继承值，或无法读取版本。`rust/src/bin/s_session_v3/audit_owner.rs:879-896` |

`HistoricalAuditStale` 前缀本身不是完整性分类器。明确的自身预算、期限、seed/adopt、迁移等失败，在未发现源完整性拒绝且迁移后连续性复核通过时，恢复正常关闭并返回原错误，可按既有启动合同直接重启，无需本节的介质人工恢复。`SourcePinFailed` 属元数据已核后的自身开 FD 失败；当前 `SourceWalMetadataFailed` 也未列入八类，不能擅自写成完整性拒绝。依据为 `rust/src/bin/s_structure_session.rs:402-430`、`rust/src/bin/s_session_v3/admission_provider.rs:153`；关闭配置恢复失败会把关闭错误附在原错误后，不能当成已经正常清理。若仍有旁挂或关闭失败，停止直接重试，保全后交人工门。

下次准入的[真实拒启条件](../rust/src/bin/s_session_v3/admission_provider.rs#L231) 是 `shm || (journal && wal_index.is_some())`，即主库 `-shm` 存在，或 `-journal` 与 `-wal` 同存，报 `UnsupportedWalShmJournalCombination`。因此完整性 fail-stop 保留的 SHM 会挡住下一次 `recover/start-s`；单独存在 WAL 不触发这一类别。重复启动不能代替介质恢复。

### 停机与证据保全

1. **按实际部署入口停机。**

   **正式会话：** 按[第 8 节](#8-选对启动停止与恢复入口)通过本次部署的控制面停机，记录实例、启动批次、launcher 及相关域的 PID 和停止结果。不要运行下列独立 S 命令。

   **独立 S（`s_service_control.py`）：** 使用故障实例的原配置和控制目录执行 status/stop，再查 status。命令来自 [README:74-75](../s_session/README.md#L74) 与 [README:107-108](../s_session/README.md#L107-L108)。`stop` 按 Q→S 停止，仅管理已登记且身份匹配的进程。保留 status/stop 输出。

   ```bash
   ./s_session/launch_s.sh service status \
     --config "$S_RUN_ROOT/manual/config.json" --state-dir "$S_RUN_ROOT/manual/control"
   ./s_session/launch_s.sh service stop \
     --config "$S_RUN_ROOT/manual/config.json" --state-dir "$S_RUN_ROOT/manual/control"
   ./s_session/launch_s.sh service status \
     --config "$S_RUN_ROOT/manual/config.json" --state-dir "$S_RUN_ROOT/manual/control"
   ```

   **两种入口都要确认**同库的写者、读者及外部 SQLite 工具、调试器等进程与连接均已停止，并记录确认人。任一停止超时、身份不明或仍有连接时，不复制变化中的库现场，不自动升级为 KILL，也不打开 SQLite 探查库。

2. **保全共用的库文件。** 全部停止后，逐件登记原件绝对路径、存在性、类型、设备号/inode、`ctime_ns`、UID/GID、权限、链接数、字节大小、mtime 与采集时间。复制后复核原件属性和副本字节。符号链接登记链接本身及链接目标，悬空链接也算原件。只有确认没有目录项才记为不存在；不可读或无法核验时保留错误。副本 inode 不能代替原件记录。复制或核对失败即停在人工门，不覆盖旧证据包。

   下列清单覆盖主库、SQLite 与 audit-ledger 旁挂、控制 owner、控制锁、写者锁、维护锁及适用的持久锁身份记录。S 准入按[实际库路径](../rust/src/bin/s_session_v3/admission.rs#L329-L343)取得 `<db>.writer.lock`，随后取得 `<db>.maintenance.lock`；部署锁连续性合同的域还须逐域采集实际库旁的 `<db>.writer-lock-id`，记录缺失，不现场补建。audit-ledger 名称见 `rust/src/bin/s_session_v3/admission_provider.rs:117-123`。将 `S_DB` 设为已核对的 S 规范库绝对路径，`S_EVIDENCE` 设为原件目录之外全新的仓外证据目录。`cp -RPp` 复制链接本身并保留属性，不移动或删除原件。命令只复制可见条目；逐项存在性与原件身份另记清单，随停机记录归档。

   <!-- drill: preserve-s-db -->
   ```bash
   (
   set -eu
   : "${S_DB:?须设置故障主库绝对路径}"
   : "${S_EVIDENCE:?须设置全新仓外证据目录绝对路径}"
   mkdir -m 0700 "$S_EVIDENCE"
   mkdir "$S_EVIDENCE/database"
   cp -RPp "$S_DB" "$S_EVIDENCE/database/"
   for suffix in -wal -shm -journal \
     .audit-ledger.sqlite .audit-ledger.sqlite-wal \
     .audit-ledger.sqlite-shm .audit-ledger.sqlite-journal \
     .control-owner.json .control.lock .writer.lock .maintenance.lock .writer-lock-id; do
     if [ -e "$S_DB$suffix" ] || [ -L "$S_DB$suffix" ]; then
       cp -RPp "$S_DB$suffix" "$S_EVIDENCE/database/"
     fi
   done
   )
   ```

3. **按入口保全首错与运行记录。** 两种入口都要保全实际发布件的版本、冻结配置、资源原件和 clock plan；归档文件时沿用步骤 2 的元数据与字节核对，并记原件到副本的路径映射。

   **正式会话（`production_session`）：** 从部署记录核对本次实例、启动批次（宿主机/启动时间或调用 ID）、launcher PID、发布件和原 manifest。用两个原件分别定位目录：

   - **launcher 状态目录：** 取原 manifest 的顶层 `state_dir`。归档 manifest 和该目录本次生成的 `structure-source.json`；拒启发生在生成前则记录未生成。正式 launcher 不生成 Python 控制器的 `s.log`、`s.process.json` 或 `q.process.json`。
   - **S 准入控制目录：** 取规范 S 库旁原 `<db>.control-owner.json` 内的 `state_dir`，不用 launcher 的 `state_dir` 代替。按 [S 签锚合同](../rust/src/bin/s_session_v3/admission_anchor.rs#L1328-L1385)对照 owner 的 `db`、`admission` 及 manifest 的 `s.admission_job_limits`，登记控制目录自身、`s-admission/`、`s-admission/binding.json`、`s-admission/limits.json` 和同级于 `s-admission/` 的 `.s-admission-pending`。逐项记原件身份和存在性，复制现有原件；pending 是目录时连同内容保全。owner 缺失、半写、路径冲突或不可核时，记录冲突与已知候选路径的来源和现场，不把任一候选冒充已证实的签锚目录。

   **正式与独立入口都按本次实际合同保存签锚和 pending**，并与步骤 2 的 owner、维护锁及适用的 `.writer-lock-id` 清单一起归档。副本只供取证，不补发签锚，不清 pending 或旁挂。

   - **定位日志。** S `serve` 的 stdout 被丢弃，stderr 继承 launcher 的 stderr。查本次启动实际生效的重定向或服务配置，从真正收到 stderr 的文件、服务管理器或采集器保存本次调用从启动到退出的原始日志。
   - **限定批次。** 共享日志用部署记录中的实例和调用 ID 限定；无调用 ID 时须有等价的宿主机、实例与启动时间/PID 记录来排除其他批次。保留事件原序、选择条件及来源。
   - **核对首错。** 用同一批次的 `spawn` 核 S 域及子 PID，并对照 `exit`/停止记录。子进程错误可能早于 `spawn` 行，且不一定自带域和 PID；采集器若只标 launcher PID，不得当成 S PID。未 `spawn` 就拒绝时保留 launcher 首错（S init 失败也经 launcher 报出），将 S `serve` PID 记为未分配。仅凭 `stopped`、时间相近或错误文本相似不能确认归属；归属不明时记录缺口，保留现场，不取其他实例的日志代替。

   例如 stderr 已重定向到**仅属本次调用、已封存**的文件时，将 `SESSION_STDERR` 设为该文件经核实的实际绝对路径（不是链接），复制原件后在副本中定位首错。共享日志先按上段限定并导出，保留原始行与来源记录，不把整份混合文件当作本次调用的证据。

   <!-- drill: preserve-formal-stderr -->
   ```bash
   test -f "$SESSION_STDERR" && test ! -L "$SESSION_STDERR" &&
     mkdir "$S_EVIDENCE/logs" &&
     cp -p "$SESSION_STDERR" "$S_EVIDENCE/logs/session-stderr.log"
   ```

   **独立 S（`s_service_control.py`）：** 归档原控制目录。控制器将 S stdout/stderr 同写 `s.log`，进程记录为 `s.process.json` 和（启用 Q 时的）`q.process.json`，见 `s_session/s_service_control.py:329-330`、`:550-553`。核对这些记录是否匹配故障实例与 PID；若还有外部 stderr 重定向，另外保全。将 `S_STATE` 设为已核对的原控制目录绝对路径，在步骤 2 新建的证据目录下执行 `mkdir "$S_EVIDENCE/control" && cp -RPp "$S_STATE/." "$S_EVIDENCE/control/"`。

### 人工恢复门

**证据保全后停在人工恢复门。禁止手工删除 -shm/-wal。** 保持停写，不通过普通 SQLite 连接、手工检查点、改日志模式或换入口绕过准入。下述监督器合同只适用于独立 S；正式会话的 S 恢复与有效代交接见[第 8 节](#8-选对启动停止与恢复入口)。

已核对 [ADR 0042:38-42](adr/0042-s-writer-incremental-production-path.md#L38) 与 [README:111-120](../s_session/README.md#L111)：它们批准的是监督器 `recover`、增量持久态重建、随后 `start-s` 的既有链；README 的具体 `stop-s → service recover → start-s` 示例绑定冻结 op95、epoch 2 和 `recover-001`，不能直接套到任意完整性故障。这两份合同均未批准完整性拒绝后“用普通 SQLite 连接正常关闭以清理旁挂”。本节因此不提供该操作或后续可执行恢复序列，`recover` 也不能越过上面的介质拒门。

运维负责人将完整错误文本、触发类别、故障时间、二进制版本/摘要、配置/资源/clock plan、对应启动入口的日志与运行记录、进程身份与停止回执、外部连接停止确认、原件元数据清单和完整副本交给 #1481 主控；由 #1481 主控提交用户/恢复合同裁定人决定可信原件来源、冲突处置、允许的介质恢复步骤和与故障匹配的 epoch/恢复事件，并将批准结果补入运维合同。未经该决定不恢复写入。若后续批准普通连接正常关闭，须明确它会把 WAL 检查点进主库；独立 S 操作后仍须完整执行 `recover/start-s` 的 H1 冷认证，正式会话仍按第 8 节的恢复门，不能将旁挂消失当成认证成功。

## 已知卡点（#1769）

> #1774 追加（2026-10-31，ADR 0057 追加修订段）：S 写者生产入口改经 `ThetaConfig::for_s_structure_writer()`
> 绑定已签的 synthetic profile（`venue-profile-synthetic-tb02a/2`），本卡点的 S 拒启原因已解除；
> 下文记录的是解除前的实测状态。replay `P0` 三项成本仍 `AwaitingPolicy{cost_inputs}`，
> 原八项生产验收与五项 TestOnly cfg 的去除仍归 #1769。
> #1774 v3 现状（2026-11-08，ADR 0057 第九、十节及其裁定依据节）：用户签署 replay `P0` 的 `entry_delay_bars=1`、`tax_bps=0`
> （模型假设，仅用于历史回放），只剩 `slippage_bps` 未落（slippage_bps=2 已由用户 2026-11-08 签署，在 v4（#1947）落地；v3 记录中仍为 AwaitingPolicy），v3 下 P0 仍拒启于 `AwaitingPolicy{cost_inputs}`。下文「解除条件」中的
> `tax_bps`、`entry_delay_bars` 两项对 replay P0 已满足。
> #1774 v4 现状（2026-11-08，ADR 0057 第十一节及其裁定依据节）：同一签署再签 replay `P0` 的 `slippage_bps=2`（模型假设，
> 仅用于历史回放），P0 v4 三项成本均已签、`admissible()` 为真；S 写者仍绑 synthetic，不绑 P0。

非 test 构建下 S 写者（v3 `serve`/`advance`、v1 `advance`）启动即因
`ThetaConfig::for_production_profile("P0")` 返回 `AwaitingPolicy{venue_profile, cost_inputs}` 退出，
launcher 因此会在 S 退出后回收全部进程、退出码 1。实测报错：
`AwaitingPolicy{venue-profile-P0.tick_size|slippage_bps|tax_bps|entry_delay_bars}：字段未签，不回退任何备用值`。
解除条件：P0 场所 profile（tick_size）与成本项（slippage_bps、tax_bps、entry_delay_bars）签署。
v1 `accept` 另被 `LegacyAdmissionBudgetAdapterMissing` 设计性关闭，S 唯一输入口是 v3 `serve` 的 socket ingest。

在此之前，`production_session_entry` 中依赖 S 写者运行的 5 个测试（simulation 拉起、凭据归属、
缺凭据时 S 照常接纳、S 拒收声明外 namespace、X 停止时 S 照常提交）会红；声明闸门本身由
`s_structure_session` bin 内单测 `v3::driver::tests::declared_structure_source_gates_accept_input`
在测试 Driver（`ThetaConfig::default()`）上验证。

## 端点拒启与原址续服（#2130）

启动被拒时，先分清是进程仍在、端点名被占，还是域库不准入。修好一项不会放行另一项。按部署记录核对 launcher 和各域二进制实际实现的合同。本节所称新版指 [ADR 0065 的修订口径（#2139）](https://github.com/Newchanlun/NewChanlun/blob/92b6ea489217db9204f6a169b2e317e052f8c1f2/docs/adr/0065-production-session-endpoint-ownership.md)；原四键 owner 等历史行为按[旧版口径](https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md)取证。下列正式入口仅供已经实施、获批且已部署相应能力的实例使用。版本或能力不能确认时，保全原件，停在人工门。

**本节只定义流程，不授予任何账户终止进程、移动或删除文件、改属主或权限、恢复库、启用部署或使用凭据的权限。** 值班负责人按 [ADR 0041](adr/0041-degrees-of-freedom-configurable-not-excluded.md) 和 TB-09 [#1383](https://github.com/Newchanlun/NewChanlun/issues/1383)、[#1401](https://github.com/Newchanlun/NewChanlun/issues/1401) 核对实际执行身份与权限。真实 X 的发送者隔离和在途责任仍走 #1401；本地 socket 或写者锁不能证明真实发送停止。

### 变更现场前，先控制谁能写

1. 从已部署的 manifest、域配置和服务记录取实例、域、库、端点和二进制版本。约定下文 `K` 是原端点绝对路径，`OWNER="$K.owner"`，`DIR` 是端点父目录，`WRITER_LOCK` 是域实际打开的锁路径，不是从显示的库别名猜出的路径。库已存在时，取其规范路径再接 `.writer.lock`；S 取原准入 lease 绑定的路径。锁名不代表锁 inode。
2. 由值班负责人暂停相关实例的自动拉起；对动文件的步骤，隔离所有可能改动相关目录的进程和外部工具，在实际宿主机及对应的挂载、PID、网络命名空间核实已停。清场和恢复还须排除外部库连接。停单个服务、一次 `lsof` 空结果、同 UID 或一次试连失败，都不能建立排他窗口。拿不到排他窗口就保留现场并移交部署负责人。
3. 在 Linux 上用 `namei -l -- "$K" "$OWNER" "$WRITER_LOCK"`、`findmnt -T "$DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS` 和不跟随叶链接的 `stat` 采集目录、端点、owner、锁和锁身份记录的原件。区分确无条目和无法核验；后者停止。这些读数只描述现场，不证明锁与前代连续，也不能排除挂载别名。动名字、改权或开服前，还须按第 3、6 节核清物理布局和隔离。
4. **动名字前，核的是前代的锁。** 每个相关域（包括经部署记录证实归属的异锁域）先按 [ADR 0065 锁连续性](https://github.com/Newchanlun/NewChanlun/blob/92b6ea489217db9204f6a169b2e317e052f8c1f2/docs/adr/0065-production-session-endpoint-ownership.md#L51-L53) 核原 `<db>.writer-lock-id`：从已核的规范库父目录无链接打开，核普通文件、域 euid、单链接、`0600`、规范内容和目录项仍指向所读原件。按第 7 节核适用的端点 owner；存在新版 owner 时，`writer_lock` 和 `lock.{dev,ino,ctime_ns}` 必须与持久记录逐项相同。锁路径取原配置及记录共同证实的实际路径，不从 owner 任意取路径。旧库未登记、首登中断、已登记锁缺失、记录或 owner 冲突或不可核时，保持拒绝，带原件移交域与部署负责人走专门的旧库导入或身份处置；不在现场创建、替换锁或重建锁身份记录。

   在交互终端用下例为每把锁取非阻塞排他锁。在取锁后、每次动名字前和动作复核时，将实际持锁 FD、无链接的当前锁叶、持久身份记录及适用的 owner 锁字段核到同一路径和同一 `dev/ino/ctime_ns`；锁叶与 FD 均须是域 euid 所有的单链接普通文件。填写 `LOCK_DEV`、`LOCK_INO`、`LOCK_CTIME_NS` 为**持久记录**的原值，不从事故现场 `stat` 填写；`LOCK_UID` 为这个域的已核 euid。脚本只核内核对象与这些原值，不代读或认证记录。多把锁时逐把进入内层维护 shell，最后一把取到之前不动任何名字。用输出的 shell PID 与 FD 编号复核，各 FD 保留到动作和复核完成。失败不可继续，不用后台进程保锁。正式恢复和开服前退出所有维护 shell，继续保持部署侧隔离。

   <!-- drill: writer-lock -->
   ```bash
   python3 - "$WRITER_LOCK" "$LOCK_DEV" "$LOCK_INO" "$LOCK_CTIME_NS" "$LOCK_UID" <<'PY'
   import fcntl, os, stat, sys

   path = sys.argv[1]
   dev, ino, ctime_ns, uid = map(int, sys.argv[2:])

   def matches(st):
       return (stat.S_ISREG(st.st_mode) and st.st_nlink == 1
               and (st.st_dev, st.st_ino, st.st_ctime_ns, st.st_uid)
               == (dev, ino, ctime_ns, uid))

   fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
   if not matches(os.fstat(fd)):
       sys.exit("锁 FD 不符前代记录；保持现场")
   fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
   if not matches(os.fstat(fd)) or not matches(os.lstat(path)):
       sys.exit("持锁复核不符前代记录；保持现场")
   os.set_inheritable(fd, True)
   with open("/dev/tty", "rb", buffering=0) as tty:
       os.dup2(tty.fileno(), 0)
   print(f"维护 shell PID={os.getpid()}，持锁 FD={fd}，路径={path}", flush=True)
   os.execlp("bash", "bash", "--noprofile", "--norc", "-i")
   PY
   ```

每次操作留一份故障单记录：实例、域、时间、授权引用和执行人，原始拒绝、暂停拉起与排他确认，操作的绝对路径和前后身份，命令退出码、复核结果、剩余阻塞。只记录核验所需的字段，不记录凭据、进程环境或含秘密的完整参数。

### 1. 结束仍持写者锁的孤儿

新版在最终放行前收到监督 EOF 必须中止整组启动、关闭已开的监听并退出，不消费 E/B 标记或接客；若仍有进程或持锁，按中止异常保全并移交，不当作已放行。**最终放行后**控制管道 EOF 不停域；launcher 已退出而域仍在原端点服务或持原锁，由获准发信号的部署运维处置。不能因 launcher PID 消失就启动第二个写者。

1. 从部署记录核实例、域、boot ID、PID 和启动 tick、运行 UID、可执行文件身份、cgroup、服务参数中的库及端点；对照 `/proc/<pid>/fd` 和 `fdinfo`，确认持的是原锁 inode。若是场所 X，先按 #1401 处置可能发送的旧进程和已有请求。任一身份对不上，不发送信号。
2. 确认部署没有更合适的有序停止入口后，向**已核定的单个进程**发 TERM。以下 Linux 示例使用 Python 3.9+（含 pidfd 接口）和支持 pidfd 的 Linux 内核。把 `PID BOOT START_TICKS RUN_UID EXE_ID LOCK_FD LOCK_ID` 填成上一步已核值，`EXE_ID` 是可执行文件 `dev:ino`，`LOCK_FD` 是该进程的持锁 FD 编号。pidfd 不可用时，交部署控制面处理，不换裸 PID、不按进程名杀。TERM 超时停止；升级信号须有对应处置授权并重新核身份。

   <!-- drill: orphan -->
   ```bash
   python3 - "$PID" "$BOOT" "$START_TICKS" "$RUN_UID" "$EXE_ID" "$LOCK_FD" "$LOCK_ID" <<'PY'
   import os, select, signal, sys
   from pathlib import Path

   pid, boot, ticks, uid, exe_id, lock_fd, lock_id = sys.argv[1:]
   proc = Path("/proc") / str(int(pid))

   def identity(path):
       st = path.stat()
       return f"{st.st_dev}:{st.st_ino}"

   pidfd = os.pidfd_open(int(pid))
   poll = select.poll()
   poll.register(pidfd, select.POLLIN)
   start = (proc / "stat").read_text().rsplit(") ", 1)[1].split()[19]
   effective_uid = next(line.split()[2] for line in (proc / "status").read_text().splitlines()
                        if line.startswith("Uid:"))
   owns_lock = any(line.startswith("lock:") and {"FLOCK", "WRITE"} <= set(line.split())
                   for line in (proc / "fdinfo" / lock_fd).read_text().splitlines())
   if (poll.poll(0) or Path("/proc/sys/kernel/random/boot_id").read_text().strip() != boot
       or start != ticks or effective_uid != uid or identity(proc / "exe") != exe_id
       or identity(proc / "fd" / lock_fd) != lock_id or not owns_lock):
       sys.exit("进程身份或持锁状态不符；未发信号")
   signal.pidfd_send_signal(pidfd, signal.SIGTERM)
   if not poll.poll(10_000):
       sys.exit("TERM 后未确认退出；保持暂停，交部署负责人")
   print(f"PID {pid}: pidfd 已确认退出")
   PY
   ```

3. 确认目标进程退出、原锁可按上节取得、没有仍持监听或代发的其他进程。保留 `K`、owner 和库侧件，不用杀进程代替清场或库恢复。整会话先按第 5 节核共同 checkpoint，再分别判断 E/B 正常关库标记、S 介质或未完成 Begin 和 X 的恢复需要。记录身份核验、信号、退出、锁与各域后续决定；TERM 成功本身不是正常关库证据。

### 2. 隔离端点名上的拒绝对象

`K` 上有无 owner 的残留 socket、异锁认领的名、普通文件、目录或链接时，启动应拒绝。由获准改动端点目录的运维和相关域负责人先核对对象来源和去向：正常自有残留由产品按认领表退役，无需人工移动；异锁名若仍合法属于另一域，修正错配的部署布局，不抢占。归属或影响未确认，保持拒绝。

1. 在排他窗口按上节核对两条名字及锁。当对象是 socket，且已确认没有仍可能持有它的进程，钉住对象试连；对普通文件、目录、符号链接只核链接自身、用途及处置许可，不对其目标试连。若 owner 名本身是 socket，也按 socket 核验。对任何 socket，只接受下面的 `ECONNREFUSED`；能连接、`EAGAIN`、超时或其他错误都保持现场。将 `SRC` 填成待处置的绝对路径。

   <!-- drill: probe -->
   ```bash
   python3 - "$SRC" <<'PY'
   import errno, os, socket, stat, sys
   fd = os.open(sys.argv[1], os.O_PATH | os.O_NOFOLLOW)
   st = os.fstat(fd)
   if not stat.S_ISSOCK(st.st_mode):
       sys.exit("不是 socket；保持现场")
   with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
       s.setblocking(False)
       result = s.connect_ex(f"/proc/self/fd/{fd}")
   print(f"dev={st.st_dev} ino={st.st_ino} connect={errno.errorcode.get(result, result)}")
   sys.exit(0 if result == errno.ECONNREFUSED else 1)
   PY
   ```

2. 通过上述核对并获准隔离的对象，逐件移入**同文件系统**的专用隔离目录。隔离目录须在本次已排他的范围内，不在 S 测量域 M 或任何现役端点目录内；目标 `DST` 取该目录下未占用的绝对路径。填 `SRC_ID` 为本次核准对象的 `dev:ino`。以下命令不覆盖、不跟随源叶链接，也不会跨文件系统退化成复制后删除。只有已批准的名字才移；保留合法 owner 时不要把它连同 `K` 一起移走。

   <!-- drill: quarantine -->
   ```bash
   python3 - "$SRC" "$DST" "$SRC_ID" <<'PY'
   import ctypes, errno, os, sys
   src, dst, expected = sys.argv[1:]

   def identity(path):
       st = os.lstat(path)
       return f"{st.st_dev}:{st.st_ino}"

   if identity(src) != expected:
       sys.exit("源对象已改变；未移动")
   rename = ctypes.CDLL(None, use_errno=True).renameat2
   rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
   if rename(-100, os.fsencode(src), -100, os.fsencode(dst), 1) != 0:  # AT_FDCWD, RENAME_NOREPLACE
       code = ctypes.get_errno()
       sys.exit(f"{errno.errorcode.get(code, code)}: {os.strerror(code)}")
   if os.path.lexists(src) or identity(dst) != expected:
       sys.exit("改名后身份不符；保持暂停，不覆盖放回")
   print(f"{src} -> {dst} ({expected})")
   PY
   ```

3. 复核原名缺失、隔离名还是原 inode，其他名字及库未动；链接还要核目标内容未动。留原名→隔离名映射和保留期限。需撤销时，只在重新建立排他、确认目标原名空且无新代认领后，以同一不覆盖改名反向移动。清场后在原址走正式启动门，不换路径或回退直绑；若清的是旧合同原本允许的空址，也不能由此推定当前布局支持认领。

### 3. 整改端点目录属主、权限或链接路径

预核发现父目录属主不是域的运行 euid、组或其他位可写，或路径分量是符号链接时，由部署目录管理员处置；旧合同只可能在端点名和 owner 名都明确不存在时直绑，不会接管残留，也不是整改方案。

1. 按共用步骤查 `namei -l` 和 `findmnt`，对照实际运行 UID/GID、调用方目录搜索权限、文件系统与 ADR 0065 的适用条件。先过第 6 节的物理布局和部署隔离核验；路径初筛退出 0 不授权改权、改名或开服。若目录共享、经链接或挂载混用，或文件系统不合规，先由部署方批准独立真实目录和引用变更，不能给链接目标递归改权。只有同名路径能按原布局重建时才保留同址承诺。

   **涉及 `financial-serve` 时另核专用目录。** 该监听器只读财务，但[启动失败可按名删除自己的 socket](../rust/src/bin/s_session_v3/financial_session.rs#L1728-L1740)，不遵守写者端点的认领锁。核它的实际目录树与所有写者端点树不重合、互不包含，且双向均无符号链接或挂载别名。两边均不得使用或重指对方的目录或端点。整改前后均核；不能证明隔离就不启用该财务监听配置。
2. 对已确认专用、真实且已排他的目录，设 `DIR_ID` 为核准的 inode 身份、`RUN_UID:RUN_GID` 为部署身份、`DIR_MODE` 为已核准的非组/其他可写模式（仅服务用户访问时用 `0700`）。只改这一级，不改锁、owner、库或子项。新目录由管理员用 `install -d -o "$RUN_UID" -g "$RUN_GID" -m "$DIR_MODE" -- "$DIR"` 创建；先核新路径，不能借此覆盖已有条目。

   <!-- drill: permissions -->
   ```bash
   test -d "$DIR" && test ! -L "$DIR" &&
     test "$(stat -c '%d:%i' -- "$DIR")" = "$DIR_ID" &&
     chown --no-dereference -- "$RUN_UID:$RUN_GID" "$DIR" &&
     chmod -- "$DIR_MODE" "$DIR" &&
     namei -l -- "$DIR" &&
     stat -c '%d:%i uid=%u gid=%g mode=%a %n' -- "$DIR"
   ```

3. 用域运行身份复核路径可达，父目录 UID 与其 euid 一致、权限与调用方需求相符且组/其他不可写。重核完整路径、挂载视图、实际目录和第 6 节适用的 M 门；S 若在 M 内或 M 外不可证，不做 M 外认领。记录前后属主、权限、挂载和已批准的配置改动，确认未改其他路径，再按第 8 节启动。

### 4. 清理已确认的退役对象

域把旧 socket 改名到 `<basename>.retired.<ino>`，不删除。达到部署保留期限或容量门槛时，由获准清理的运维在维护窗处理。若只凭文件名找到条目，不得删除：放回失败留下的对象也可能占用退役名。

1. 先按第 7 节核 owner 版本、锁字段和退役状态。新版 `endpoint-claim` 只认 `fresh`、`vacant`、`retired` 三种事件，日志只用于观察。用同版本已完成的退役证据（持原 FD 复核并已提交清除意图）、原对象身份和运维清单核对退役来源、basename、`dev:ino` 及保留期限；`retired` 事件只能辅助关联。任何 `bound=null` 但 `K` 存在、`retiring` 未清、当前 owner 的旧 `bound` 对应退役名仍在或不可核，均移交第 7 节，不进入本批清理。旧版 `adopted` 只留作历史线索，不作为 `unlink` 凭据，也不得跨版本沿用。放回失败、来源不明、留档冻结或仍被引用的对象留在原地。锁、身份记录、`K` 和 owner 都不在清理对象内。
2. 处于排他窗口并持原域锁时，逐件用第 2 节钉住试连，确认仅返回 `ECONNREFUSED`。以下 `RETIRED` 是该端点确认退役的绝对路径，`RETIRED_ID` 是已核 `dev:ino`，`RUN_UID` 是原域 euid。保留前后清单，不用通配删除。

   <!-- drill: retired -->
   ```bash
   test "$RETIRED" = "$K.retired.${RETIRED_ID#*:}" &&
     test -S "$RETIRED" && test ! -L "$RETIRED" &&
     test "$(stat -c '%d:%i:%u:%h' -- "$RETIRED")" = "$RETIRED_ID:$RUN_UID:1" &&
     unlink -- "$RETIRED" &&
     test ! -e "$RETIRED" && test ! -L "$RETIRED"
   ```

3. 复核退役名消失，现役名、owner、原锁及旁挂身份不变。运行正式入口后复核原址读口。记录退役来源、身份、保留期判定、删除回执及未清理对象；删除没有改名隔离的回退能力。

### 5. 先补齐共同 checkpoint，再对需要恢复的域升代

恢复备份、从旧二进制前滚或异常停机后，先判断整会话能否续上同一业务边界，再判断哪些域需要升代。E 或任一 B 从备份恢复，或曾由不识 `clean_close/1` 的二进制开服时，即使库内标记匹配持久代，也不能证明最近一次正常关库；该域仍须正式恢复。

1. **停旧会话和发送者。** 按第 8 节第 1 步停机并确认全部旧域已退出、自动拉起暂停、外部 SQLite 连接已隔离。真实场所 X 另按 #1401 隔离旧发送者并保留在途责任。记录原发布件、原 manifest、备份来源与范围、原代，保全 S、E、每个 B、X 的原库、侧件、配置、快照、原收据和未决责任。任何原库缺失或不可核都停，不 init；全失也不能当作首启。严禁用普通启动探测：所核 [`main` launcher](../rust/src/bin/production_session.rs#L297-L319) 会逐个 `init` 缺失的 E/B 库。
2. **只读核共同向量与推进边界。** 按 [ADR 0065 共同 checkpoint](https://github.com/Newchanlun/NewChanlun/blob/92b6ea489217db9204f6a169b2e317e052f8c1f2/docs/adr/0065-production-session-endpoint-ownership.md#L194-L201)，以原 manifest 的 S、E、全部 B（manifest 顺序）、X 为全员，不按幸存回执或换代计划选成员。逐域从原件核同一会话、会话代、manifest／证据类、`checkpoint_id`、bar 边界和输入前沿、各域 cut、快照／重放起点、实际最高已推进边界。

   每条跨域前件都须在源域所选 cut 的已核链内，核其提交序号、root 和被引用的原记录。全员封口记录绑定同一向量且因果闭合，才得到最后共同向量。首个业务 bar 中断时，可用已封齐的初始向量 N=0。原件不足、向量冲突或不可核即停，不能取更旧向量掩盖推进。
3. **仅部分推进时，只离线补这一 bar。** 若共同向量之后的下一 bar 仅部分推进，由获授权的域运维使用已获批、已部署的 `recover-checkpoint`。同一具名离线计划绑定原会话／manifest／证据类、最后共同向量、下一 bar 的确切边界及冻结输入、策略、时钟和前件。缺实现、批准或原件就保持停机。

   释放人工 FD 后，命令在部署隔离下取本域原锁，按因果顺序复用已提交原件，只补缺失的应用或封口；不监听、不接纳新业务、不重调场所、不重发、不回退。实验／生产只按获准的只读对账取证，未知责任保留。中断保留已提交原件；仅在同一计划可幂等核验时续做。复核全员完成的下一 bar 向量与因果闭合后才能继续。`recover-checkpoint` 在 E/B 首次改写的事务撤销旧关库标记，不写新标记，也不代替换代。
4. **共同向量完成后，才对确需恢复的域升代。** E 和各 B 走本节具名恢复，S 走第 8 节的具名恢复，真实 X 仍按 #1401/C09.8。保持部署侧隔离；执行恢复命令前释放人工维护 FD，由对应域二进制自取原锁。不要手工改关库标记或库代。

   **先核 E/B CLI 世代，再选命令。** 从发布清单核对 launcher 与域二进制，不拿原库试探参数。

   | 发布能力 | 写入型恢复 | 回执查询与 launcher 计划 |
   |---|---|---|
   | 此处所核 `main`（`0e29d008`） | [只提供非具名 `recover`](../rust/src/economic_session/service.rs#L1553-L1597)，会[直接提交新 epoch](../rust/src/economic_session/store.rs#L1709-L1725) | 无具名核验；[launcher 只认 `--manifest`](../rust/src/bin/production_session.rs#L251-L256)，不支持计划 |
   | [#2082 具名基线](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/service.rs#L1570-L1622) | `recover-named` 需要经济 manifest、原库、原请求，B 另带 `--chong`；没有 S 布局两参 | `query-recovery`／`current-recovery` 只读域库，**可能创建缺失的锁文件**，须先过下文旧代锁门。[计划键集必须等于 E/B 全集](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L273-L296)，不能用下文子集计划，也不得为填齐键而多升代 |
   | 已部署 ADR 0065 修订及具名恢复 | 下列 `recover-named` 另须 `--s-db`、`--s-admission-job-limits`，按第 6 节核布局并核原锁连续性 | 两个只读子命令不因布局条款增加参数；launcher 支持子集计划，先核共同向量，再按第 8 节两阶段装配 |

   **下面两个写命令仅用于第三行发布件。** 能力不符、版本不可核或命令被拒就在人工门保留首错；严禁改用非具名 `recover` 试错。所核 `main` 的 launcher [报 `refused` 并退出 2](../rust/src/bin/production_session.rs#L451-L457)也不证明前面的 init 等动作未发生。

   准备获准的 `economic-recovery/1` 原请求，绑定域、会话及会话代、经济 manifest、共同边界完成后的本域持久 cut 和恢复前代，使用本事故的唯一 `recovery_id`。只对确需恢复的域运行。`RELEASE` 取已核 bin 目录，经济 manifest、各域原库和请求路径取部署记录；`S_DB`、`S_LIMITS` 取同一 launcher manifest 的 `s.db`、`s.admission_job_limits` 原值。`RECOVERY_EVIDENCE` 是本事故已核准、已存在的证据父目录绝对路径。每次尝试分存 stdout、stderr 和退出码。

   <!-- drill: recover-e -->
   ```bash
   (
   set -eu
   stamp=$(date -u +%Y%m%dT%H%M%SZ)
   attempt=$(mktemp -d "${RECOVERY_EVIDENCE:?}/e-$stamp.XXXXXX")
   printf 'E 恢复证据：%s\n' "$attempt"
   rc=0
   "$RELEASE/e_economic_session" recover-named --manifest "$ECON_MANIFEST" \
     --db "$E_DB" --recovery-request "$E_REQUEST" \
     --s-db "${S_DB:?}" --s-admission-job-limits "${S_LIMITS:?}" \
     > "$attempt/recover.stdout" 2> "$attempt/recover.stderr" || rc=$?
   printf '%s\n' "$rc" > "$attempt/exit-code"
   exit "$rc"
   )
   ```

   <!-- drill: recover-b -->
   ```bash
   (
   set -eu
   stamp=$(date -u +%Y%m%dT%H%M%SZ)
   attempt=$(mktemp -d "${RECOVERY_EVIDENCE:?}/b-$stamp.XXXXXX")
   printf 'B:%s 恢复证据：%s\n' "$CHONG" "$attempt"
   rc=0
   "$RELEASE/b_chong_session" recover-named --manifest "$ECON_MANIFEST" \
     --db "$B_DB" --chong "$CHONG" --recovery-request "$B_REQUEST" \
     --s-db "${S_DB:?}" --s-admission-job-limits "${S_LIMITS:?}" \
     > "$attempt/recover.stdout" 2> "$attempt/recover.stderr" || rc=$?
   printf '%s\n' "$rc" > "$attempt/exit-code"
   exit "$rc"
   )
   ```

   非零退出时，本次目录只登记为失败证据，即使 stdout 非空也不当作回执；保留旧回执原件，不覆盖、不删除，不启动 launcher。成功退出后仍须核对 stdout 的回执，核对通过才登记为本次成功回执；再次尝试也使用新目录。

   **旧代锁门（#2082）。** 两个查询动作都先取 `process_lock`，再[只读打开域库](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L112-L119)。[取锁会以读写和 `create(true)` 打开](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/session_transport.rs#L70-L79)，即使原库和原请求都在，缺锁时也会新建，改变现场。

   直接查询或由旧 launcher 代调前，先停服隔离并保全现场，再依据可信的前代证据逐域核实规范库旁的原 `<db>.writer.lock` 仍在，且原路径、对象身份和属主可信；一次现场 `stat` 不足以证明是原锁。原锁缺失或不可核就停，不能调用或补建锁。#2082 没有新版的 `<db>.writer-lock-id`，不以该记录为旧代查询前提，也不为查询补写。保留部署隔离，调用前释放人工持锁 FD，让命令自取已核原锁。

   **回执读法。** 已部署匹配的具名 CLI 且通过适用的锁门后，用 `query-recovery` 和同一原请求查原回执，用 `current-recovery` 核当前代。两者传 `--manifest`、`--db`、`--recovery-request`（B 另加 `--chong`）；不加两个 S 布局参数。历史回执不证明当前资格；重取不重写被 serve 消费的标记。若期间开服又崩溃，重新判断恢复需要，不拿旧回执放行。
5. **核完回执，再准备启动交接。** 核回执的域、cut、有效代。仅当已部署 ADR 0065 修订版的子集能力时，才用 `launcher-economic-recovery/1` 的 `requests` 把需交接有效代的域（`E`、`B:<id>`）映射到各自**原请求**绝对路径，不填回执路径。未列的域使用原 manifest 的代，B 的 `--e-epoch` 取 E 有效代。launcher 在拉写者前用 `current-recovery` 逐项核；有一项被拒就停止，不删条目、不退回 manifest 旧代。仅 E 需交接且已部署子集能力时：

   ```json
   {"schema_revision":"launcher-economic-recovery/1","requests":{"E":"/abs/recovery/e-request.json"}}
   ```

   保留备份或旧版本来源、完整共同向量、需要补齐时的离线计划及原件、前后代、原请求和回执。最后按第 8 节两阶段启动和验证；端点认领事件不能代替恢复证据。

### 6. 核实 E、各 B、X 的库和端点在 S 测量域之外

布局管理员和域负责人在变更或启动前核对。新版的 launcher 在任何目录写入、init 或子进程启动前初核 E、各 B 的监听端点以及 E/B/X 的库布局；各域仍须在实际操作前复核。模拟 X 取实际加载的 profile 的 `history_simulation.socket`，不是场所 `endpoint`，也不是 X 指向 S/E 的客户端读口。无本地监听的 X 不核端点，但仍核库、侧件和锁。

1. **先做路径初筛。** 从原 launcher manifest 取 `s.db`、`s.admission_job_limits`、E/各 B/X 的库路径和 `x.profile`；从经济 manifest 取 `e.socket` 和各 `chongs[j].socket`。按 [ADR 0059 第 1–4 条](adr/0059-production-session-layout-contract.md#裁定) 取 `P=parent(canon(S_DB))`、`b=basename(canon(S_DB))`、`A=canon(parent(parent(S_LIMITS)))`。用 `namei -l` 核路径分量、`readlink` 查叶链接、`realpath -e` 核存在路径。只有父目录已核且确认无叶才可拼接剩余路径；拒绝访问不是缺失。新版拒绝悬空的库链接和带链接的 E/B/X 端点父路径；不能把解析后的路径当作原路径合格。

   将 `S_CANON` 和 `A` 填成上面的 S 规范库和准入控制目录。对 E、每个 B 和 X 的下列目录逐一填 `Q`：

   - 库：库参数父目录及规范库父目录。
   - 锁和侧件：实际规范库旁的写锁、锁身份记录、`-wal`、`-shm`、`-journal` 所在目录，含确无条目时将创建它们的目录；发现链接另记，不跟随以放行。
   - 监听端点：目录项父目录及叶链接可能指向的目录。

   P 内的普通子目录不自动属于 M；A 的所有子目录都属于 M。以下脚本只检查规范路径文字，退出 0 **不证明 M 外**，不能据此改权、移动或开服。

   <!-- drill: measure -->
   ```bash
   (
     set -eu
     : "${S_CANON:?}" "${A:?}" "${Q:?}"
     P=$(dirname -- "$S_CANON")
     b=$(basename -- "$S_CANON")
     case "$Q/" in
       "${A%/}/"*) printf 'M: A %s (%s)\n' "$A" "$Q"; exit 1 ;;
     esac
     if [ "$Q" = "$P" ]; then printf 'M: P %s\n' "$Q"; exit 1; fi
     case "$Q" in
       "${P%/}/"*)
         relative=${Q#"${P%/}/"}
         case "${relative%%/*}" in
           "$b"|"$b".*|"$b"-*) printf 'M: S 族条目 %s\n' "$Q"; exit 1 ;;
         esac ;;
     esac
     printf '路径初筛通过，仍须核物理对象和挂载: %s\n' "$Q"
   )
   ```

2. **在实际部署的挂载视图核物理对象和双向别名。** 按 [ADR 0065 第 3、4 条](https://github.com/Newchanlun/NewChanlun/blob/92b6ea489217db9204f6a169b2e317e052f8c1f2/docs/adr/0065-production-session-endpoint-ownership.md#L31-L47)，钉住 P、A、现存 S 族目录及候选目录，按 FD 的 `dev/ino` 比较：Q 本身与 P 同对象，或 Q 或其物理祖先与 A、S 族目录同对象，都命中 M。核实际主库、侧件、锁和锁身份记录的叶；按该合同核类型、链接数及父子挂载 ID，排除硬链接、单文件挂载和未证实的叶。

   - **从候选向 M 查：** 对照 FD 的挂载 ID（`statx(STATX_MNT_ID)`）与同一视图的 `/proc/self/mountinfo` 核物理祖先。遇子树挂载、同一文件系统的多个整根挂载或物理身份不可核，不判 M 外；挂载 ID 不同不代表不是同一对象。
   - **从 M 向候选查：** 枚举 P、A 及后代的挂载项（含嵌套项），按其实际落点确定是否属于 M。打开可见挂载点，核源对象和文件系统内 `root`，不把 `mount source` 字符串当成源路径。仅因挂载点等于 P 入选时，只比源根与 Q 自身；落在 A 或族树时，比源根与 Q 及其物理祖先；文件挂载比源叶与实际操作叶。任一方向相交、不可核或复核时变动，E/B/X 停止写入或绑定，不回退直绑。
3. **核部署隔离及复核时点。** 从实际 UID、父目录权限、ACL 和可绕过权限核变更权，确保非授权主体不能移动相关目录或重指 M；仅把端点目录设成 `0700` 不保护父目录里的名字。S/E/B/X 使用同一受控私有挂载视图；排除外部挂载传播，核业务和并发主体不能变更挂载或进入视图改挂载。E/B/X 在取锁或开库前初核库布局，持锁后在可写开库或创建前用实际 FD 重核。带监听的模拟 X **在取锁、开库或写入前初核监听路径，实际 bind 前重核 S 测量域和已钉目录**；E/B 也在动端点前重核。E/B/X 用已核目录绑定，bind 后、报告完成前再核公开路径、实际目录和 M 分类；隔离贯穿整个窗口。S 的 M 外认领同样须证实布局和隔离。
4. 有交集或不可核时保持停机。如获批准，按第 3 节用独立实际目录整改，同步核 profile、manifest、客户端引用和冻结合同；涉及财务只读监听时另核其专用树隔离。冻结路径不能直接编辑库绑定；无批准的迁移与重绑流程就移交，不另建空库。改后重跑路径和物理核验，记录 P、A、族目录、各 Q、挂载视图、隔离依据和复核结果，再走第 8 节。旧残物按第 2 节处置，不借整改删库侧件。

### 7. 按版本核 owner，保全未确认的退役现场

owner 原地更新中断可能留下半写 JSON；退役可能停在改名后、复核和提交前，也可能移错对象且放回失败。先保全，不把这些状态当成可用空址或正常退役。

1. 在排他窗口从已核目录无链接钉住 owner，核普通文件、域 euid、单链接、`0600` 和路径仍指向所读原件。解析规范 JSON，不能用通用 JSON 语法检查代替版本及归属核验。按发布件选择合同：历史四键是 `schema`、`socket`、`writer_lock`、`bound`；新版同样叫 `endpoint-owner/1`，却必须**恰有六键**，另含 `lock`、`retiring`。逐项核 `schema`、原 `socket=K`、实际 `writer_lock`；新版 `lock` 按共用步骤 4 核持久记录和 FD，`lock` 及非 null 的 `bound` 各恰含十进制字符串 `dev`、`ino`、`ctime_ns`。`retiring` 只可为 null 或非 null 的 `bound` 对应的唯一退役 basename。禁止把旧四键文件当作新版合法 owner。
2. **保留三类现场：** `bound=null` 但 `K` 存在；`retiring` 非 null；或者当前 owner 的旧 `bound` 对应的 `$K.retired.<bound.ino>` 仍在或不可核。最后一项无论 `K` 是否存在都要查；用不跟随叶链接的元数据核退役对象类型、属主、链接数和 `dev:ino`。改名后不比较旧 ctime。即使 `dev:ino` 一致或试连拒绝，也不能补回崩溃前持原 FD 验证并提交的证据。这三类不走 `vacant`，不清 `bound` 或意图，不自动放回，不进入第 4 节。
3. 半写、身份冲突或放回失败时，保留原 owner 字节及日志，记录原名、候选退役名、现有占用者、身份与核验错误，移交获授权的域与部署负责人。任何专门处置须另定，先证明前代锁连续性、原对象归属和非在用；未满足共用锁与布局门就保持原样。获准隔离时按第 2 节逐件操作；获准人工放回还须证实原名确无条目且无后续认领，用同一不覆盖改名移回同一 inode。**不补写 JSON，不手造 owner，不删除库旁挂。**
4. 记录每件原件去向、对象身份、未被覆盖的名字和剩余拒绝条件。受影响域照常走库准入；标记未消费不能解除端点拒绝。

### 8. 选对启动、停止与恢复入口

在 [H1 生效条件](#h1-生效条件) 中引用的 `s_service_control.py start-s` 和 `recover`，只描述独立 S 的 `s-launcher/4` 链。对 ADR 0065 管辖的生产会话端点目录，**不得运行** [S Python 控制器](../s_session/s_service_control.py) 或 [E/B Python 控制器](../s_session/economic_service_control.py)（包括用来清场、启动、停止或恢复）。不得借用两者的旧端点清理逻辑（包括 `prepare_socket`）。即使本次布局只适用 ADR 0065 的旧合同直绑，也不切换到 Python 控制器。其他原有独立用法不变。

1. 正式会话拒启、计划停机或恢复时，由已授权的会话运维先核发布件、原 manifest、域与端点目录范围。launcher 仍存活时，通过部署控制面请求已核身份的 launcher 有序停止；核每个域退出、监听关闭、锁释放。最终放行后若 launcher 已退而有孤儿，走第 1 节；真实场所 X 的旧发送者另按 #1401 确认隔离。启动失败的 `stopped` 或退出码不是逐域正常关库证据。
2. **停完先走第 5 节第 1–3 步：** 核最后共同向量，若且仅若下一 bar 部分推进，离线补齐它。共同向量完成后才对确需恢复的域升代；launcher 只校验和装配。E/B 用第 5 节的具名恢复。S 用本次已获批、已部署的 [ADR 0050 #2128](https://github.com/Newchanlun/NewChanlun/blob/be2749f2996f8e928e72051193a693819c72fdbf/docs/adr/0050-s-resource-admission-contract-v1.md#L62-L101) 正式恢复链：从同一原 manifest 用 `production_session s-recovery inspect-recovery` 只读取证、制备原 `s-recovery/1` 请求，再用该入口的 `recover-named` 恢复。保留原 R4、签锚、未完成 Begin 处置和 H1 冻结 `resource_identity`；不手删 SHM/WAL，不换介质或入口硬启。S 恢复、E/B 具名子集、模拟 X 连续交接或共同 checkpoint／两阶段放行，**凡本次需要但尚未部署，停在人工门**。

   持久版本先决定读写合同。按 [ADR 0038 旧原件边界](https://github.com/Newchanlun/NewChanlun/blob/aeb79b0e1a8ce5318fe34bb370ffdb11630a2af9/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L186-L190)，旧库按原写合同与原布局续服，不能用 `recover` 或 `serve` 原地升级格式，也不能混写或把旧责任自动迁入新库。旧部署缺本事故所需的恢复能力时，停在人工门；需迁移另走获准流程。

   **四分支之前先排除 X 自身故障。** 若模拟 X 自己在持有 `ExecutionRequested` 原批时被杀，下面四行都不适用，即使 E、S 和各 B 都未换代。先核旧 X 写者已退出。仅在已部署且获准的原址受限入口下，由 X 持本域原锁核真实升代和原批，用获准新 `producer_epoch` 对原批只发 `QueryExecuteCommitted`。保留旧 `pending_epoch`、原命令 `x_epoch`、原命令字节和摘要、E 原交付回执；由 S 核新代对原会话、原 X 的只读权限。不接纳新业务、不取得调用占有。没有该入口就保持停机，不用旧代常规 `serve` 或裸 `--manifest` 补查。[当前 `main` 拒绝带旧 pending 换代](../rust/src/history_simulation/runtime.rs#L776-L785)不是向 S 查询，更不是取得 `NoRecord`。

   仅当独立监督器证实“S 资格请求已落盘、首字节未发”时，才按 [ADR 0038 专项](https://github.com/Newchanlun/NewChanlun/blob/aeb79b0e1a8ce5318fe34bb370ffdb11630a2af9/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L231-L233)预期并实核 S 返回 `NoRecord`。首字节已发或无法确认时，按 [ADR 0073 第 8 条](https://github.com/Newchanlun/NewChanlun/blob/032a99603d44fe2f0acca56bd66d7830d8d0c8d1/docs/adr/0073-simulation-x-recovery-authority-binding.md#L53-L62)以 S 实际持久原件为准。只有核到原 `ExecuteCommitted` 才按原合同续接；确定拒绝或终止也按原合同。遇 `NoRecord`、超时或结果不可核，保留原 pending 和最大责任，资格申请零重发，不新增占有或撮合。
3. **用原 manifest 装配有效代。** 通过上述 X 排除门后，且已部署新版 ADR 0065 启动门及本行所需能力，才可选下表；共同向量、布局及本域准入前件须已核。先退出所有人工维护 shell。表中“换代”指相对原 manifest 仍须凭原回执交接有效代：以前已换代而这次仍须交接的域带原请求，不再次升代。设置 `SESSION_MANIFEST` 为原 manifest，`RECOVERY_PLAN` 为第 5 节计划，`S_REQUEST` 为对应 S 的原请求文件。选择一行，不按失败顺序试跑：

   | 换代交接 | 启动实参（均带 `--manifest "$SESSION_MANIFEST"`） | 模拟 X 的权威绑定 |
   |---|---|---|
   | 无换代 | 无额外实参 | E、S 按原合法代；不新增绑定 |
   | 仅 E/B | `--economic-recovery-plan "$RECOVERY_PLAN"` | 若 E 换代，只续 E；仅 B 换代不改 X 权威绑定 |
   | 仅 S | `--s-recovery-request "$S_REQUEST"` | 只续 S |
   | S 与 E/B 均换代 | 两个参数都带 | 续 S；若 E 也换代，按 E、S 顺序一次提交一个向量 |

   **仅使用本行匹配的发布件。** S 参数须是已部署 #2128 的 launcher 能力；经济计划须是已部署 ADR 0065 修订的子集能力（#2082 基线只收全集，`main` 不接收任一恢复参数）。S 换代必带原 `--s-recovery-request`：launcher 用 `current-recovery` 核原切面及当前持久代，S 在自身 serve 锁内再核同一原回执。核验失败不退回 manifest 旧代。

   **仅对端换代时，模拟 X 按 [ADR 0073 #2129](https://github.com/Newchanlun/NewChanlun/blob/032a99603d44fe2f0acca56bd66d7830d8d0c8d1/docs/adr/0073-simulation-x-recovery-authority-binding.md#L32-L44) 保代交接。** launcher 用匹配域的 `current-recovery` 在原配置指定的同一库、同一域 bin 上核原请求，取当前原回执；不拿历史查询、手填代、日志或 socket 应答代替。等相关 E/S 按已核有效代持锁启动、满足各自前件后，launcher 才经受控启动输入交回执。X 在自己的原库和原锁内核首写部署登记、原绑定、历史和 pending，按每项 `from_epoch` 等于当前绑定且新代恰为下一代的规则原子追加或核回同一已提交绑定；提交且全员获最终放行后，才可按当前绑定交换。X 仍绑 E1、E 已到 E3 又缺 E1→E2 交接时就停，不凭 E3 当前回执跨代，不补造中间记录。保留 X 自身会话、写者代、源身份及 E 的 `authorized_sources`；不编辑 manifest 或冻结 profile（[所核 `main` 会拒绝档案不符](../rust/src/history_simulation/runtime.rs#L815-L826)）。真实 X 的发送、对账和在途责任仍按 #1401。

   **无换代，已部署两阶段放行：**

   <!-- drill: start -->
   ```bash
   "$RELEASE/production_session" --manifest "${SESSION_MANIFEST:?}"
   ```

   **仅 E/B 换代，另须已部署子集计划：**

   <!-- drill: start-plan -->
   ```bash
   "$RELEASE/production_session" --manifest "${SESSION_MANIFEST:?}" --economic-recovery-plan "${RECOVERY_PLAN:?}"
   ```

   **仅 S 换代，另须已部署 #2128：**

   <!-- drill: start-s-plan -->
   ```bash
   "$RELEASE/production_session" --manifest "${SESSION_MANIFEST:?}" --s-recovery-request "${S_REQUEST:?}"
   ```

   **S 和 E/B 均换代，另须已部署两种参数的组合：**

   <!-- drill: start-combined-plan -->
   ```bash
   "$RELEASE/production_session" --manifest "${SESSION_MANIFEST:?}" \
     --s-recovery-request "${S_REQUEST:?}" --economic-recovery-plan "${RECOVERY_PLAN:?}"
   ```

4. **等全员两阶段放行。** 第一阶段，S、E、每个 B 和 X 各持原锁重核本域布局、介质和同一共同向量；launcher 收齐准备回报才发初始化／绑定许可。续服不 init。第二阶段，各监听域实际 bind／listen 并完成末次布局、身份及适用的认领核验后回报；无监听 X 也须完成本域启动前件。launcher 收齐同批全员回报才最终放行；此前不消费 E/B 标记、不 accept、不发送，此后 E/B 仍须先事务消费本代标记才首个 accept。X 失败或监督 EOF 落在最终放行前时，关闭监听整组退出；不抹去已验证完成的合法退役，不补写关库标记。
5. 常规续服获最终放行后，从正式读口核原 cut、原收据与各域有效代，核本代 E/B 标记已在接纳前消费，再恢复自动拉起。X 受限查询后仍留停时，记录实际 S 查询结果、原 pending 和责任，保持暂停，不按整组续服登记。真实 X 仍须单独满足部署及发送门。记录原目录和端点、实际 manifest／计划／请求路径、各域回执、两阶段与读口结果。拒绝就保留首错和现场，不改走 Python、另换路径或新建库。单条 `endpoint-claim` 不是整组已就绪的证据。
