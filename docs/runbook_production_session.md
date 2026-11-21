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

launcher 不打开任何域库；各域进程自行持锁与 epoch。S/E/B 任一退出 → 回收其余域、退出码 1；
X 退出只记日志，S/E/B 继续。旧 simulation / dry-run 骨架收到 SIGTERM/SIGINT 后向存活子进程发 SIGTERM，超出 10 秒宽限期则强制回收。
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
        "admission_job_limits": "<state>/s-admission/limits.json", "writer_epoch": "1",
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

S `serve` 需要 admission 锚（`<db>.control-owner.json` + `state/s-admission/{limits,binding}.json`）。
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

2. **保全共用的库文件。** 全部停止后，逐件登记文件原件的绝对路径、设备号/inode、字节大小、mtime 与采集时间，复制后复核原件这些属性和副本字节。符号链接登记链接本身的元数据及链接目标，悬空链接也算原件。不存在的旁挂记录为不存在；副本 inode 不能代替原件记录。复制或核对失败即停在人工门，保留错误，不覆盖旧证据包。

   下列清单覆盖主库、SQLite 与 audit-ledger 旁挂、控制 owner、控制锁和写锁；audit-ledger 名称见 `rust/src/bin/s_session_v3/admission_provider.rs:117-123`。将 `S_DB`、`S_EVIDENCE` 设为已核对的主库和全新仓外证据目录的绝对路径，证据目录须位于原件目录之外。`cp -RPp` 复制链接本身并保留属性，不移动或删除原件。元数据清单与停机记录一并归档。

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
     .control-owner.json .control.lock .writer.lock; do
     if [ -e "$S_DB$suffix" ] || [ -L "$S_DB$suffix" ]; then
       cp -RPp "$S_DB$suffix" "$S_EVIDENCE/database/"
     fi
   done
   )
   ```

3. **按入口保全首错与运行记录。** 两种入口都要保全实际发布件的版本、冻结配置、资源原件和 clock plan；归档文件时沿用步骤 2 的元数据与字节核对，并记原件到副本的路径映射。

   **正式会话（`production_session`）：** 从部署记录核对本次实例、启动批次（宿主机/启动时间或调用 ID）、launcher PID、发布件和原 manifest，登记 manifest 中实际使用的 `state_dir`；归档 manifest 和本次生成的 `state_dir/structure-source.json`，若拒启发生在生成前则记录未生成。正式 launcher 不生成 Python 控制器的 `s.log`、`s.process.json` 或 `q.process.json`。

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

启动被拒时，先分清是进程仍在、端点名被占，还是域库不准入。修好一项不会放行另一项。以下流程供已实施并部署 [ADR 0065（#2079 获审版）](https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md) 的实例使用；以实际发布版本为准，不能从本手册推定当前二进制已支持认领或恢复计划。

**本节只定义流程，不授予任何账户终止进程、移动或删除文件、改属主或权限、恢复库、启用部署或使用凭据的权限。** 值班负责人按 [ADR 0041](adr/0041-degrees-of-freedom-configurable-not-excluded.md) 和 TB-09 [#1383](https://github.com/Newchanlun/NewChanlun/issues/1383)、[#1401](https://github.com/Newchanlun/NewChanlun/issues/1401) 核对实际执行身份与权限。真实 X 的发送者隔离和在途责任仍走 #1401；本地 socket 或写者锁不能证明真实发送停止。

### 变更现场前，先控制谁能写

1. 从已部署的 manifest、域配置和服务记录取实例、域、库、端点和二进制版本。约定下文 `K` 是原端点绝对路径，`OWNER="$K.owner"`，`DIR` 是端点父目录，`WRITER_LOCK` 是域实际打开的锁路径，不是从显示的库别名猜出的路径。库已存在时，取其规范路径再接 `.writer.lock`；S 取原准入 lease 绑定的路径。锁名不代表锁 inode。
2. 由值班负责人暂停相关实例的自动拉起；对动文件的步骤，隔离所有可能改动相关目录的进程和外部工具，在实际宿主机及对应的挂载、PID、网络命名空间核实已停。清场和恢复还须排除外部库连接。停单个服务、一次 `lsof` 空结果、同 UID 或一次试连失败，都不能建立排他窗口。拿不到排他窗口就保留现场并移交部署负责人。
3. 在 Linux 上用 `namei -l -- "$K" "$OWNER" "$WRITER_LOCK"`、`findmnt -T "$DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS`、`stat -c '%d:%i %F uid=%u gid=%g mode=%a links=%h ctime=%z %n' -- "$K" "$OWNER" "$WRITER_LOCK"` 记录路径分量和原件。GNU `stat` 在这里不加 `-L`，记录链接本身。区分明确的不存在与无法核验；后者停止。仅在父路径无链接、权限及对象身份已核清之后，才执行下面的文件操作。
4. 对要改动的每个现有端点，持有其所有相关域的原写者锁，含异锁 owner 指向的已核实域；不跟随 owner 字段任意打开路径。对每把锁，在同一维护 shell 重复下列步骤，保存 FD 到动作和复核完成；`LOCK_ID` 来自步骤 3 已核实的锁文件 `dev:ino`。锁文件缺失、是链接、换过 inode、身份不明或锁不可取时，不创建或替换锁，停止并交域负责人核实。命令失败不得继续。正式恢复和开服前关掉这些 FD，继续保持部署侧隔离，直到移交给正式入口。

   <!-- drill: writer-lock -->
   ```bash
   test -f "$WRITER_LOCK" && test ! -L "$WRITER_LOCK" &&
     exec {lock_fd}<"$WRITER_LOCK" &&
     test "$(stat -Lc '%d:%i' "/proc/$$/fd/$lock_fd")" = "$LOCK_ID" &&
     flock -nx "$lock_fd"
   ```

每次操作留一份故障单记录：实例、域、时间、授权引用和执行人，原始拒绝、暂停拉起与排他确认，操作的绝对路径和前后身份，命令退出码、复核结果、剩余阻塞。只记录核验所需的字段，不记录凭据、进程环境或含秘密的完整参数。

### 1. 结束仍持写者锁的孤儿

launcher 已退出，而域仍在原端点服务或持原锁时，由获准发信号的部署运维处置。launcher 控制管道 EOF 不停域，不能因 launcher 的 PID 消失就启动第二个写者。

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

3. 确认目标进程退出、原锁可按上节取得、没有仍持监听或代发的其他进程。保留 `K`、owner 和库侧件，不用杀进程代替清场或库恢复。E/各 B 无本代正常关库标记须先正式恢复；S 若留 SHM 或遇未完成 Begin，见下文恢复门；本地 X 走原有启动门。记录身份核验、信号、退出、锁与各域后续决定；TERM 成功本身不是正常关库证据。

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

1. 按共用步骤查 `namei -l` 和 `findmnt`，对照实际运行 UID/GID、调用方目录搜索权限、文件系统与 ADR 0065 的适用条件。若是共享目录、链接、挂载或文件系统不合规，先由部署方批准独立真实目录和引用变更，不能给链接目标递归改权。只有同名路径能按原布局重建时才保留同址承诺。
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

3. 用域运行身份复核路径可达，父目录 UID 与其 euid 一致、权限与调用方需求相符且组/其他不可写。复查整个路径无链接、挂载在适用清单内；S 或带监听的模拟 X 还须核 M。记录前后属主、权限、挂载和已批准的配置改动，确认未改其他路径后再开服。

### 4. 清理已确认的退役对象

域把旧 socket 改名到 `<basename>.retired.<ino>`，不删除。达到部署保留期限或容量门槛时，由获准清理的运维在维护窗处理。若只凭文件名找到条目，不得删除：放回失败留下的对象也可能占用退役名。

1. 用认领成功的 `endpoint-claim`（`retired` 或 `adopted` 且有对应退役 basename）与原对象身份、运维清单核对来源、`dev:ino` 和保留期限；留档冻结的留在原地。排除任何放回失败、未知或仍被引用的对象。锁和 `K`、owner 不在清理对象内。
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

### 5. 恢复备份或从旧二进制前滚后，先正式恢复再启动

E 或任一 B 的库从备份恢复，或曾由不识 `clean_close/1` 的二进制开服时，即使库内标记与当前持久代相同，也不能证明最近一次服务已正常关库。由获授权的域运维逐域正式恢复，不能先试启看是否报错。

1. 停原实例并排除旧 writer、SQLite 外部连接和自动拉起。查备份来源、恢复范围、原库及旁挂一致性、最后可信 cut、原代、刚才用过的二进制、未决责任。确认 E 和各 B 原库齐全；部分缺库不 init，全失也不能把产品的首启行为当成恢复。保全原库、侧件、配置及已有回执。不要手工改标记或库代。
2. 使用含具名恢复和本合同的正式发布件。部署侧隔离继续生效，先释放人工维护 FD，由对应域 bin 自取原锁。准备获准的 `economic-recovery/1` 原件，绑定域、会话、会话代、经济 manifest、最新持久 cut 和恢复前代，使用本事故的唯一 `recovery_id`。下例只运行需要恢复的域；`RELEASE` 是已核 bin 目录，`ECON_MANIFEST` 和各 DB、请求路径从部署记录取。将 `RECOVERY_EVIDENCE` 设为本事故已核准、已存在的证据父目录绝对路径。每次尝试独占创建新的子目录，分存 stdout、stderr 和退出码。

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
     > "$attempt/recover.stdout" 2> "$attempt/recover.stderr" || rc=$?
   printf '%s\n' "$rc" > "$attempt/exit-code"
   exit "$rc"
   )
   ```

   非零退出时，本次目录只登记为失败证据，即使 stdout 非空也不当作回执；保留旧回执原件，不覆盖、不删除，不启动 launcher。成功退出后仍须核对 stdout 的回执，核对通过才登记为本次成功回执；再次尝试也使用新目录。

   只有明确获准按非具名恢复合同交接有效代的部署，才改用对应域的 `recover`（同一 `--manifest`、`--db` 及 B 的 `--chong`，无 `--recovery-request`）；非具名结果不能冒充 launcher 的具名请求。恢复回执丢失时，用相同请求 `query-recovery` 查原回执，再用 `current-recovery` 核是否对应当前代，两者参数与 `recover-named` 相同。重取回执不会重写已被 serve 消费的标记；若期间开服又崩溃，重新判明恢复需要，不能复用旧回执放行。
3. 核对回执的域、cut、有效代和实际部署合同。对具名链，用 `launcher-economic-recovery/1` 的 `requests` 对象把已恢复、需回执交接的域（`E`、`B:<id>`）映射到各自原请求文件的绝对路径；未换代域继续用 manifest 的代。不要把回执文件当成请求文件。例如仅恢复 E 时，计划为：

   ```json
   {"schema_revision":"launcher-economic-recovery/1","requests":{"E":"/abs/recovery/e-request.json"}}
   ```

   先处理端点拒绝与依赖域准入，再按第 8 节启动。S 的强杀和介质再准入见 [#2128](https://github.com/Newchanlun/NewChanlun/issues/2128) 与本文 H1 人工恢复门；E/S 升代后的模拟 X 权威绑定见 [#2129](https://github.com/Newchanlun/NewChanlun/issues/2129)，未经对应交接不得改冻结配置强启。
4. 从正式读口核原 cut/收据和本次有效代；核 E/B 接纳前已消费该代标记的版本证据，不能仅凭 `endpoint-claim` 通过就判断恢复正确。留备份或旧版本来源、前后代、恢复请求/回执、计划、启动序列及首个正式读口结果。

### 6. 把带本地监听的模拟 X 放在 S 测量域之外

部署预检或拒启排查发现模拟 X 目录可能落在 M 时，由布局管理员和 S/X 域负责人在启动前核对。X 认领本身不核 M，launcher 的 ADR 0059 预检也不核 X 的本地监听路径。取 X profile 的 `history_simulation.socket`，不是场所 `endpoint`，也不是 X 指向 S/E 的客户端 socket；无本地监听的 profile 不适用这项端点检查，但 X 库和锁仍受布局合同约束。

1. 从 manifest 读 `S_DB=s.db`、`S_LIMITS=s.admission_job_limits`、`X_DB=x.db` 与 `x.profile`，从对应 profile 取 `X_K`。按 [ADR 0059 第 1–4 条](adr/0059-production-session-layout-contract.md#裁定) 取 `P=parent(canon(S_DB))`、`b=basename(canon(S_DB))` 和 `A=canon(parent(parent(S_LIMITS)))`。检查 X 的库目录、实际库目录、锁目标目录（含库未存在的锁候选）以及端点名所在目录、端点叶链接的实际目标所在目录；缺失或悬空条目按 ADR 0059 追到最近存在祖先，不能把拒绝访问误当成缺失。
2. 用 `namei -l` 对照链接走向，必要时用 `readlink -- "$X_K"` 读端点叶链接（相对目标从链接所在目录解析）。对已存在的路径用 `realpath -e`。只有确认缺失时，才从已核祖先拼接剩余路径；不可核验就保持暂停。把规范库路径 `canon(S_DB)` 和上一步的 A 分别记为 `S_CANON`、`A`。逐一填写以下规范目录 `Q` 并运行判定：

   - X 库：`canon(parent(X_DB))`、`parent(canon(X_DB))`。
   - X 写者锁：取 `canon(X_DB)` 接 `.writer.lock` 后解析锁路径，取其父目录。库未存在时，也核 `canon(parent(X_DB))/basename(X_DB)` 接 `.writer.lock` 后解析的锁目标父目录。
   - X 端点：`canon(parent(X_K))` 和 `parent(canon(X_K))`，即端点目录项和叶链接目标所在目录。

   P 内的普通子目录不自动属于 M；A 的所有子目录都属于 M。

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
     printf 'M 外: %s\n' "$Q"
   )
   ```

3. 有交集就停实例，在已获准的 M 外专用目录按第 3 节建目录。改动布局时同步核 X profile、生产 manifest、各客户端引用及冻结合同；已冻结的路径不能直接编辑库中的绑定。若没有经批准的迁移与重绑路径，保持停机交部署及域负责人，不另建空 X 库来绕过。对旧端点残物按第 2 节处置，不借整改删库侧件。
4. 重跑全部目录判定并核新路径无链接、属主及权限满足认领，正式启动后从 S 的准入结果与 X 的正式读口核对，确认 X 不再在 M 内写入。留 P、A、族条目、各 Q、命中判据、批准的改动和复核结果。

### 7. 保全半写 owner 或放回失败的现场

进程在原地写 owner 时中断，可能留下不可解析的 JSON；退役后复核发现移错对象，若原名被占或放回失败，程序保留退役名并报告两个名字。二者都交获准处置端点名的运维和域负责人，不能当作 `bound=null` 或正常退役。

1. 按共用步骤锁定现场。对已钉明是普通文件且获准读取的 owner，用 `python3 -m json.tool "$OWNER" > /dev/null` 判是否可解析。解析成功还须对照 `endpoint-owner/1` 四个键（`schema`、`socket`、`writer_lock`、`bound`）及类型、UID、单链接、`0600` 和原始身份；JSON 工具不判合同归属。保存原字节、副本和拒绝日志，记录半写前后的原名及 inode。**不补写 JSON，不手造 owner，不删库旁挂。**
2. 半写 owner 经核属本域且已获准清场：按第 2 节逐件隔离半写 owner 和相伴的无可信归属残留，不能只移 owner 然后把原 socket 当作可接管。若 socket 仍能连接或来源未明，保持两个名字和服务拒绝。原端点不存在时，只隔离确认的半写 owner。
3. 放回失败：用错误中的原名与退役名分别 `stat`（不跟随叶链接），对照先前固定对象、现有占用者及退役名下对象的实际 `dev:ino`。若能证明该对象应回原名、原名明确空且没有后续认领，经双方负责人批准用第 2 节的不覆盖改名放回同一 inode。原名仍被占、对象可能仍在用或证据不全时保留两名原件，不自动恢复；经审定不应放回且处置安全的对象移到隔离目录，不纳入第 4 节批次。
4. 核对每件原件的去向、对象身份和未被覆盖的名字，受影响域照常走库准入；标记未消费并不能解除端点拒绝。记录日志中的两个名字和错误、原件字节或对象身份、复核/放回/隔离结果及是否仍须保持拒绝。

### 8. 选对启动、停止与恢复入口

在 [H1 生效条件](#h1-生效条件) 中引用的 `s_service_control.py start-s` 和 `recover`，只描述独立 S 的 `s-launcher/4` 链。对 ADR 0065 管辖的生产会话端点目录，**不得运行** [S Python 控制器](../s_session/s_service_control.py) 或 [E/B Python 控制器](../s_session/economic_service_control.py)（包括用来清场、启动、停止或恢复）。不得借用两者的旧端点清理逻辑（包括 `prepare_socket`）。即使本次布局只适用 ADR 0065 的旧合同直绑，也不切换到 Python 控制器。其他原有独立用法不变。

1. 正式会话拒启、计划停机或恢复时，由已授权的会话运维先核发布件、原 manifest、域与端点目录范围。launcher 仍存活时通过部署控制面向已确认身份的 launcher 请求有序停止，核每个域退出、监听关闭、锁释放；已退出且有孤儿则走第 1 节。不把启动失败的 `stopped` 或退出码当作各域已干净关库证据。
2. 恢复由获准的本域正式入口执行，launcher 只校验和装配。E/B 按第 5 节。S 维持原 R4、未完成 Begin、epoch 与签锚，H1 仍使用原冻结 `resource_identity` 对应配置，不另造资源档。若 S 介质或者恢复后有效代无已部署合同，停在 H1 人工恢复门，等 #2128 对应的部署流程；不得用 Python `recover`、手删 SHM/WAL 或换域入口硬启。
3. 已核各域可接纳、关闭人工维护 FD 后，从同一 manifest 用正式 launcher 启动。未发生需要回执交接的 E/B 换代时不加计划；否则使用第 5 节的 `RECOVERY_PLAN`。两个命令是条件分支，不是失败后的回退顺序。

   <!-- drill: start -->
   ```bash
   "$RELEASE/production_session" --manifest "$SESSION_MANIFEST"
   ```

   <!-- drill: start-plan -->
   ```bash
   "$RELEASE/production_session" --manifest "$SESSION_MANIFEST" --economic-recovery-plan "$RECOVERY_PLAN"
   ```

4. 确认用的是原目录、原端点名和已核有效代；用正式读口复核原收据、各域就绪和监听（认领布局才有 `endpoint-claim`），把部署入口、实参中的 manifest/计划路径、回执、每域结果记进故障单。拒绝就留首错和现场，不改走 Python 控制器、改名启动或另建库。放开自动拉起前仍须满足部署及发送门。
