# ADR 0050：S 资源准入合同 v1 与操作员签撤

> 正本范围：S 资源准入合同 v1 取值、版本登记和操作员入口。已审定：主控 2026-10-22 依 #1323 Notes N-2 审定取值规则；非作者独审 PASS（审查者 `/root/review1657_final`，报告 [`INDEPENDENT-REVIEW.md`](../../.chanlun/review-results/issue1657-closeout-20261028/INDEPENDENT-REVIEW.md)、[`review.json`](../../.chanlun/review-results/issue1657-closeout-20261028/review.json)）。
> 独审对象：候选 `507c3fed75`，当时本文件名为 `docs/adr/0049-s-resource-admission-contract-v1.md`，报告中的「ADR0049」即本文件。PR #1710 合入前改名为 0050，相对独审版仅标题行编号不同（`git diff -M 507c3fed75 8f02689951 -- docs/adr/` 中本文件一行差异）；本首部为 #1657 收尾补登记。
> 依据：#1567 / ADR 0046、#1657。
> 受影响代码：`rust/src/bin/s_session_v3/admission_issuance.rs`、`s_session/s_service_control.py`；入口登记见 ADR 0039。

## 当前合同不能签锚

版本 `s-admission-small/1-awaiting-measurement` 只面向 S86 / MIN12 小库的 bounded-layout/1。9011 留给 v2。规范文件为 `s_session/contracts/admission-small-v1.json`。JSON 对象键排序、紧凑编码、无末尾换行的 SHA256 是 `5ef9d83dd6eb1ae4ebd9664d3de576c847ce0267be49eaad41bed29d1e7f636f`。

| 字段 | v1 值 |
|---|---|
| max_store_bytes | 68719476736 |
| max_staged_bytes | AwaitingMeasurement |
| max_total_node_bytes | AwaitingMeasurement |
| max_total_nodes | AwaitingMeasurement |
| max_total_records | AwaitingMeasurement |
| max_total_wire_bytes | AwaitingMeasurement |
| max_total_requests | AwaitingMeasurement |
| max_elapsed_ms | AwaitingMeasurement |

64 GiB 沿用 ADR 0037；七项不得用测试值或 v2 推导值代填。#1675 对 S86、MIN12 各作一遍完整准入审计，以两库较大峰值乘 2，独审后更版。不得为两遍审计自行翻倍。启动器窗口必须不小于合同 max_elapsed_ms，不够时改启动器配置，不缩合同。

#1675 更版时还须给出适用 S86/MIN12 的可信辨识证据和接缝。目前材料未给可用于机器判定的布局/具名库标识，本版本全局拒签，未用文件名或任意 CLI 字符串冒充该证据。按主控本轮指令，不新增部署 path/dev/inode 编译白名单，不把每次合法重建变成重编译政策。具体库身份仍由 R4 binding 与原 FD 核验承担。

## 一个注册表，两种调用

生效版本及规范合同编译进 S 二进制，签发和启动校验共用 `Contract::authorize`。输入文件仅是待核原件，不是清单；运行时没有环境变量、外部 JSON 或 CLI 开关可替换注册表。合同更版必须经审查构建。部署仍须使用受审二进制；内嵌清单不声称抵抗替换整个程序。

`AwaitingMeasurement` 不能解析为生产 JobLimits。版本缺失、旧版本、未知摘要、未实测值、启动窗口不足均拒绝。签发前先核合同，失败不创建 pending/published。

启动窗口在两条路径各有负控：签发路径 `admission_prepare_rejects_insufficient_startup_window`；启动器在发布与调用 R4 之前经 `admission-contract` 入口核验，负控为 `admission_contract_rejects_insufficient_startup_window_before_r4`（`startup_timeout_ms` 比合同 `max_elapsed_ms` 少 1 即 `AdmissionStartupWindowTooShort`，等于时放行），由 `.github/workflows/issue-1657-admission.yml` 实际执行。

## 操作员用法

当前版本执行以下签发命令会返回 AdmissionContractAwaitingMeasurement。七项实测并独审更版后，替换版本名和合同文件。

```sh
s_structure_session admission-prepare --db /absolute/source.sqlite --state-dir /absolute/state --service-uid 501 --contract-version s-admission-small/1-awaiting-measurement --contract s_session/contracts/admission-small-v1.json --startup-timeout-ms 10000
s_structure_session admission-revoke --db /absolute/source.sqlite --state-dir /absolute/state --service-uid 501 --revocation-id operator-change-1
```

service-uid 是部署服务的实际 uid，命令须以同 uid 执行，并核 DB 和控制原件 uid；示例 501 不是项目政策值。签发不建立数据库和 state 目录，不授予交易发送权。活写者、maintenance/control 占用、既存 published/pending、未完成撤销、外来 uid 或可被组/其他用户改写的 DB 均拒绝。路径每级无跟随，DB 已解析路径沿 R4 既有语义。

签发持锁顺序为 state.control、DB.control、DB.writer、DB.maintenance。先写 0700 pending 与 0600 limits/binding，fsync 后原子更新 owner，再 no-replace 发布。失败保留证据，不清理后重签。owner 已落盘的完整 pending 可由既有 Python publish 续发布；不完整 pending 使用显式撤销。

撤销先落持久 intent，再把原目录移入 `.s-admission-revoking`，将 owner 改为保留 db/state_dir 的两字段记录，最后改名 `s-admission-revoked-<id>`。原件与 intent 保留。已落 intent 后中断，用同一 revocation-id 重试，仅补未完成步骤；不同 id、对象身份改变或已有归档拒绝覆盖。若在 intent 完整持久化前发生 I/O 故障，保留半成品并拒绝自动恢复，须按现场原件人工处置，不宣称任意磁盘损坏可自愈。换锚须先完成显式撤销。

## 启动与控制分开

launcher 的写动作链是 Python prepare 原件核验及前导记账 → admission-contract → publish → Rust R4 → 服务。此处 ADR 0046 的「调用 R4 之前」指 Rust 消费入口前，主控本轮已采纳。合同命令只取 Python 已核摘要，不重复读取控制原件；与后续进程共用原启动绝对期限。合同失败不 publish、不启动，不修改原锚或数据库。Controller.close 释放控制锁，下一合法生命周期可重新取得。

配置新增 `admission_contract_version`，仅 start-s/recover 要求。status/stop 不读合同，不因旧合同、坏 limits 或缺版本丧失控制能力。`recovery_admission.py` 与 Rust R4 六身份字段、八项 exact 检查未改。

## 验证与后续

靶向 Rust `admission_prepare_` 实跑含九项具名负控、pending、窗口、mode、签撤再签正控与撤销中断恢复。Python 合同门测试真实调用 Controller 和子进程，旧生命周期测试在测试夹具中显式隔离合同门。release 必须无 test_prepare 符号，且真实 admission-prepare 对本版合同拒签。CI 为 `.github/workflows/issue-1657-admission.yml`。

本票不提供正式成功收据；#1675 承接实测、适用库辨识、有效合同新版本和正式成功收据。合入顺序 #1527 → #1657，不把失败收据重新绑定到本票。

## 修订（#2128，S 原址具名恢复与再准入，2026-11-21）

**在原库续接，不把能打开的旧切面当成当前写权。** S 崩溃留下 WAL/SHM 时，S 域先核上一代部署身份与已提交前沿，在持久隔离下收尾，再走原 R4，最后在原库原子提交新代及具名回执。资源锚、部署身份证据、业务原件各证其事；旧 cut、内容对象、获知时点、已接纳输入及业务回执仍从原库核取。

### 1. 先核生效合同与上一代部署，再动原库

- **正式入口。** [ADR 0039](0039-production-entry-inventory-and-unique-launcher.md):273–298 的唯一 launcher 是 `production_session`。`production_session s-recovery` 提供操作员显式选择的 `inspect-recovery`、`recover-named`、`query-recovery`、`current-recovery`。launcher 只把原 manifest 的 S 控制配置及请求定位交给同构建的 `s_structure_session`，不开库、不读 X 凭据、不拉起其他域、不建缺失库、不动 socket；旧 Python 控制器不承接。普通 `serve`、一次性 `advance`、既有 `recover --new-epoch` 不隐式转入具名恢复；未登记具名能力的健康库仍走原入口。ADR 0039:291 的整会话恢复义务按第 4 节执行，不是自动调用 S 具名恢复。
- **首错与预算。** `inspect-recovery`、`recover-named`、`current-recovery` 和带 S 请求的 `serve` 共用顺序：用有界控制前导钉住已发布 owner/锚、binding 与 limits 原件，先核身份及原字节（含 limits 原字节摘要），再由内嵌注册表的 `Contract::authorize` 裁定版本、摘要、适用域和启动窗口；只有放行后才信任数值预算，读取和解析请求、catalog、profile、clock plan、结构源等业务配置；随后在锁内再核原件、租约、注册表裁定与部署绑定，才审计主库/WAL 的业务载荷。launcher 在裁定前只读定位所需的 manifest 控制字段，不解释内嵌业务字段，不预读请求或外部业务载荷。`AwaitingMeasurement` 的首错为 `AdmissionContractAwaitingMeasurement`，不先按生产 `JobLimits` 解析，不创建恢复记录或进入 SQLite 收尾。
- **用故障前的证据认原库。** 在受准部署首次启用具名恢复能力时、允许本能力覆盖的业务写入前，持锁在受保护的 admission state 目录持久登记原会话、会话代、规范库路径、库父目录与主库的稳定文件身份，以及原 maintenance 锁的规范路径及 `dev/ino/ctime_ns`。主库身份须用该文件系统可验证、跨正常写入不变且能区分 inode 重用的持久对象标识；没有这种证明的部署不登记；不能用随 SQLite 写入变化的主库 ctime，也不能只认内容相同。本次 `load_for_db` 才采到的主库 inode 和只钉控制原件的六字段 Binding 都不是前代身份证据；不得在发现故障后从当前文件倒填登记。
- **用原 guard，不在恢复时补锁。** 写者锁接 [#2139 的 ADR 0065](https://github.com/Newchanlun/NewChanlun/blob/855cf58a42919bf904b06e000682b71a64feabc0/docs/adr/0065-production-session-endpoint-ownership.md#L51-L60) 的 `<db>.writer-lock-id`：在钉住的规范父目录下无链接、不创建地取原 `.writer.lock` 和 `.maintenance.lock`，按 E5 顺序持有；配置使用控制锁时仍遵守本 ADR 原锁序。在锁内把实际 guard FD、公开路径叶、故障前登记的 DB／锁身份与已发布控制原件逐项核同。依 ADR 0065 只读核 S 库内持久端点索引；只以所钉的父目录与 basename 定位 owner，不取 argv 或 cwd。已登记 owner 须核父目录隔离、文件三元组、原 socket、锁路径及其 `lock.{dev,ino,ctime_ns}`；旧直绑须核父目录和 owner 确无条目，只有索引明确未配置才免核。不创建或改 owner。原锁缺失、换锁或 owner 不符即拒绝（写者锁连续性按 ADR 0065 报 `StaleWriter`），在 checkpoint 前保全，不能通过当前 `Lock::acquire` 的创建分支补一把锁。确证空址的普通首启仍按 ADR 0065 的首建与 guard 交接，不能把既有库、锁记录或 owner 的缺项当首建。
- **保护与计量。** 可写恢复在第一次可写打开前重核 DB、侧件、受控 VFS、目录和挂载隔离；其他能打开原库的旧组件（含直接读者）须停止或隔离。双锁持至 SQLite 关闭、持久收尾与记账结束；域锁只排除同协议持锁者，不代替介质隔离或 SQLite 锁。PID、mtime、手工声明不授写权。只支持经登记的本机持久 WAL、当前库规则；拒绝 rollback journal、混合日志、外来或未知侧件、别名、替换、缺引用及无预算，不迁移旧 schema。按 [ADR 0059](0059-production-session-layout-contract.md) 把部署记录、持久前沿、恢复意图和所有侧件列入已知来源及测量域 M；登记它们是为了核验和计量，不是让 E6 放行 SHM。控制前导、业务原件只读审计、SQLite I/O、记录、R4 及输出共用一次账与一个绝对期限；预留可证明的物理分配上界，事后照实结算。注册表须明确覆盖具名能力及其附加成本，不能沿用 #1675 的旧路径读数当作新动作实测，不能用 TestOnly 供值；原锚六字段及八项资源含义不变。普通 R4/E6 对 `-shm` 或 WAL 与 rollback journal 并存仍报 `UnsupportedWalShmJournalCombination`，没有第二档判据（#799、#804）。

### 2. 用独立前沿核介质，用持久意图跨越两种连接

1. **先核有证据的切面。** 通过钉住主库/WAL 的只读 FD/VFS 审计有效提交、版本、引用、持久代、cut、时钟、未决及原件；不靠 SHM 内容选前沿，不用只读主库的 `immutable=1` 代替 WAL 核验。`inspect-recovery` 只返回制备请求所需的已核持久身份与切面，不建改 SQL 原件，不发接纳资格。介质校验能验证可见帧和引用是否自洽；SQLite 的 `walIndexRecover` 到首个无效帧即停，截掉的后缀也可能只剩一个能通过 `quick_check` 的旧切面。只读审计和 NORMAL 打开读到同一切面，不是两份证据。
2. **独立前沿从启用能力起登记。** S 的受准写者在同一部署的受保护控制目录持久保存与 SQLite 主库/WAL/SHM 分开的前沿见证；只在同一部署身份及 guard 下更新，不能在恢复时用现存介质重造。它绑定单调事务序号及 SQLite 同事务写入的对应标识、代和 cut，并覆盖会改变恢复判断的时钟、Begin/pending、提交及回执；cut 不动的事务也不能漏记。先持久登记待提交前沿及其前一确认前沿，再提交 SQLite；COMMIT 成功后持久确认，确认前不公开该次业务或恢复成功。两处记录的写入各自保证文件及目录持久、可辨中断。已确认见证须与所见最后提交相符；未确认时，若原库含完全相符的待提交事务标识及其证据，则可判断已提交；若只见旧切面，则不能区分没提交与提交后丢失，首版拒绝自动继续。见证缺失、冲突、不可核或无法辨别时，报 `SRecoveryMediumUnproven`，不 checkpoint、不回退旧 cut，交 #2130 保全。检测范围止于该见证所绑定的事实。

   **已登记库的所有写入口都核前沿。** 包括无恢复标志的普通 `serve`、一次性 `advance`、旧式恢复和 `recover-checkpoint`。持本域原写者锁，先用钉住的原件只读核对已见提交和持久见证，早于可写打开；在替换上一份见证前，仍须在同一 guard 下核其与上一事务的已证结果相符。普通路径保留原 R4/E6 的拒绝，不因核前沿而放行 SHM；即使 E6 判为 MainOnly、代匹配且 Begin 为 idle，也不能拿这些条件代替前沿核验。核不符即报 `SRecoveryMediumUnproven`，零库写、原见证字节不变。未登记该能力的健康旧库不增加此前置条件。
3. **首次改变介质前落意图。** `recover-named` 持原双锁，先查同 ID 的持久回执：同请求按第 6 点取原结果或收尾，不走新跃迁的键检查；同 ID 异内容照旧拒绝。新跃迁须命中当前旧代与已核切面，通过时钟／预算／介质门，并在落意图及任何物理动作前，核 `s_clock_events` 的 `(clock_event_id, recover, -1)` 未占用，且 `N+1` 可在原非负 `i64` 纪元域表示。任一不符即拒，零新增意图、零 checkpoint。全部通过才把唯一活动意图持久登记在上述受保护控制目录。登记具名能力时即写明无活动意图；已登记部署须读到一份完整、可核的当前状态，记录缺失不等于没有活动意图。意图绑定部署身份、原请求规范字节、旧代、已核前沿及原待收尾介质；文件和目录同步后才允许可写 SQLite open。意图不在 WAL/SHM 内，不随 close 或进程死亡消失。原有库的所有写入口在本域锁内、可写开库或启服前查此状态：活动意图使普通启动、`advance`、旧式恢复等报 `StaleWriter：S 具名恢复意图尚未完成` 并拒写，即使已经无 SHM、R4/E6 会通过；不能当成首启。意图存在但不完整或不可核也拒写，保全现场。仅同 ID、同字节、同部署的具名请求可继续；不同请求不能覆盖或清除。无活动意图不触发此项拒绝，已登记库仍须核前沿。
4. **有 SHM 才走 NORMAL 收尾。** 只在已持久登记意图后，以受控 VFS 打开钉住的现有库（不 CREATE、不跟链接、不换 inode、不变更日志模式），用 SQLite NORMAL WAL 连接。配置 FULL 与平台同步要求，禁自动 checkpoint，失败路径禁 close-checkpoint。先用 SQLite 锁和真实读取复核已证切面，再执行 `PRAGMA main.wal_checkpoint(TRUNCATE)`，只接受 `(busy=0, log=0, checkpointed=0)`；之后才恢复 SQLite 本地最后关库行为并检查显式 close、必要同步、原主库身份不变、无替换或未知旁挂、SHM/journal 不在、WAL 不在或为零。侧件只由 SQLite 在受控 VFS 下收尾，不按名手工 unlink/truncate。WAL 在且为零字节可按此核验；孤立 SHM（无 WAL）首版仍以 `SRecoveryMediumUnproven` 拒绝，含 SQLite 已删 WAL 但未删 SHM 的中断窗口。无 SHM 不做物理收尾。
5. **原 R4 后才用 EXCLUSIVE 提交。** 重新枚举并核收尾后切面，通过同一个 R4（`MeasuredDomain::measure`、只读认证、计量及适用的 H1），核切面及业务原件与见证相符。具名恢复的写连接在第一次 WAL 访问前进入 SQLite EXCLUSIVE WAL（内存索引、不产 SHM），不启用会另建 SHM 的并行 SQL 连接；拿不到实际排他锁就拒绝，不降级 NORMAL。复用 S 原 Recover 事务：在事务内重核身份、旧代、cut、恢复时钟、恢复键未占用和 `N+1` 可表示性，只结未终结 Begin，保留 pending 原字节及引用。检查过的 `N+1`、恢复时钟行、`writer_epoch_history`、Begin 处置和具名原回执同一事务持久提交；不推进结构发布、不作新业务 Commit、不等待 E 或重发外效。
6. **同请求收尾，不凭退出码推断提交。** NORMAL close 已成功、换代事务尚未开始就被杀：活动意图挡住普通写者；同请求在双锁内核原件、旧代及旧前沿，无 SHM 时重走原 R4 并完成一次跃迁。若已留下事务待提交见证，则按第 2 点核实，不用旧切面授权重做。EXCLUSIVE COMMIT 后即使还未 close 就被杀，新进程也不得为同请求再写一条跃迁：核同一持久回执、时钟、跃迁与前沿，补齐控制见证并收尾。验证原事务持久结果及 SQLite 成功关闭后，才把活动意图持久标为已完成；不在提交前或按 stdout 清隔离。close、回包或记账失败一律不报成功，按同 ID 查询或重送，不换名试写。已完成的同名回执若遇另一次 SHM 事件，只能读历史；新故障须绑定当时当前代与切面另走具名入口。物理中断可留下 checkpoint 进度，但不改业务事实和端点。

### 3. 原回执与当前资格分开

- **请求。** `s-recovery/1` 是严格规范 UTF-8 JSON 整件，最多 4,096 字节：`recovery_id`（1–96 字节 ASCII 字母、数字、`-_.`）、`domain_id="S"`、`session_id`、`session_generation`、`from_epoch`、`cut={generation,structure_cut,index_frontier}`、`config={rule_revision,profile_hash,catalog_hash,clock_plan_hash,structure_source}`、`clock_event_id`，另含 `schema_revision="s-recovery/1"`。整数沿原协议用规范十进制字符串。结构源是持久规范对象的全量内嵌值，不能换成摘要、路径或截断版；各业务字段逐项核冻结配置和 S 原值。部署路径、设备及 inode 留在控制证据，不进业务回执。沿用 PR #2082 的封闭解析边界，拒未知、重复及错误字段，不接受请求自报新代或调用时刻。
- **登记时证明请求可表示。** 在启用该部署的具名能力前，用将来实际采用的规范编码和计长规则，按冻结配置、完整结构源、最长合法恢复 ID、可用 Plan 事件 ID 与协议字段最大编码宽度验整件上界（含 UTF-8、JSON 转义和结构开销）。不确定或大于 4,096 就不登记该能力；实发请求仍按硬上限检查。不把 4,096 字节反向施加给普通结构源、manifest 或普通 service。
- **首版时钟只支持固定 Plan。** 按原时钟计划中的 `clock_event_id` 取恢复相位和语义纳秒，核不早于持久时钟前沿；等于前沿并不证明恢复键未占用，仍须过第 2 节第 3、5 点；不得取调用时钟、拼计划或把 System 当 Plan。System 不登记首版具名能力；具名检查及写入口若实际识别为 System，在意图、可写 SQLite open 或 checkpoint 前拒绝，不改变普通服务与既有恢复对 System 的合同。历史查询按回执生成时的登记版本与持久时钟行核原件，不重新采样。
- **持久回执。** `{"kind":"NamedRecoveryReceipt","request":<规范请求对象>,"writer_epoch":"<N+1>","recover_ns":"<语义纳秒>"}`。在原库 `meta` 的 `s-recovery/1:<recovery_id>` 命名空间持久存原请求及回执规范字节，绑定原跃迁、历史 cut 及恢复时钟，不用当前态再造旧回执。同 ID 同内容回原字节；同 ID 异内容或跨库／配置报 `IdentityConflict`，新 ID 的前代不符报 `StaleWriter`，未知 ID 查询报 `MissingDependency`。
- **历史只读。** `query-recovery` 核部署原件及原读权限，在可证明一致的只读介质上核请求、历史回执、时钟、跃迁和历史 cut。可查已经过代的原回执；不要求当前可签的写合同、当前代、共同 checkpoint 或已完成意图收尾。不创建锁或侧件，不 checkpoint，不在不可核的介质上推断不存在，也不授写权。
- **当前凭据。** `current-recovery` 过第 1 节的生效合同、部署身份、原锁、原 R4 及当前前沿门；只读核同一规范原件、持久代及一致切面，要求无活动恢复意图、无未结 Begin。拒绝 dirty、回执缺失或过代，不代为收尾。launcher 只有等子进程正常退出为 0 且得完整规范原件才可转交；完整 stdout 后非零退出和 signal 一样不得转交或启动，须按同 ID 查询持久结果，再独立过当前核验。带 `--s-recovery-request` 的 S serve 在本域锁内以本次确证的同一请求字节重验，早于任何 pending 推进、bind 或接纳；不能只复读可替换路径。拒绝后不拿 manifest 的旧代重试。无 S 请求时仍须由 manifest 自己的代通过原 R4/Begin/epoch 门；已登记部署也须过第 2 节的前沿及活动意图门。

### 4. 整会话独立过共同 checkpoint 门

- **本域成功不等于全员封口。** 按 [ADR 0038](0038-dual-run-determinism-recovery-seek-asknown.md):134–138 分证据类重放，按 [#2139 的 ADR 0065](https://github.com/Newchanlun/NewChanlun/blob/855cf58a42919bf904b06e000682b71a64feabc0/docs/adr/0065-production-session-endpoint-ownership.md#L212-L222) 核同一会话的 S、E、各 B、X 的进度、全员封口与因果闭合 cut 向量。旧向量不能盖住下一 bar 的域推进。若 S 已提交而下一 bar 未全员封口，即使 S `current-recovery` 成功，普通整会话仍报 `StorageUnavailable：共同 checkpoint 未完成或不可核验`；不 init、不起写者、不 bind，零接纳、零发送。由获授权运维在整组停服、旧域退出后按同一具名离线计划执行 `recover-checkpoint`，从最后共同边界逐 bar 补至停服时所证的最高推进边界；复用本域原收盘 cut，保留已提交事实及原责任，不监听或接纳。全部闭合才重走普通启动；两阶段绑定及批次原子放行沿 ADR 0065。S 回执不能替代任一阶段，launcher 不自动跑域恢复。
- **只换 S，只更新 X 对 S 的目标代。** [#2129 的 ADR 0073](https://github.com/Newchanlun/NewChanlun/blob/032a99603d44fe2f0acca56bd66d7830d8d0c8d1/docs/adr/0073-simulation-x-recovery-authority-binding.md#L34-L52) 消费 S 原回执和 `request.from_epoch → writer_epoch`。仅 S 换代时，S 先按新代完成本域启动前件，simulation X 由自身持锁提交绑定后才可交换，只将权威向量中的 `s.authority_epoch` 从 N 改为 N+1；E 自身 `writer_epoch`、E `authorized_sources`、X 的 `e.authority_epoch`、X 自身 `writer_epoch/producer_epoch`、X 的 `source_namespace/source_epoch` 及会话身份保持原值。新交换的目标代及应答信封按 S 新代核；读到旧执行原件时仍按原资格请求的绑定核旧代、原收据和在途责任，不重发资格申请。S 恢复不写 E/B/X 库、权威档或 manifest；裸整数、日志和 readiness 均不构成跨域凭据。PR #2077 关停、PR #2082 E/B 恢复及真实 X 的 SPEC C09.8 边界不变。

### 5. 正式入口验收

通过 ADR 0065 准备 M 外、由 S 已认领的原 socket，走专用 TestOnly 历史夹具的正式 launcher。各正控先发布非空 cut。一臂在 Begin 已持久、下一业务 COMMIT 的待提交见证尚未登记时杀旧 S；另一臂在业务 COMMIT 及前沿确认已持久、尚未回包时杀。夹具只向自建子进程发送 SIGKILL，以通知锁定边界、以 wait status 验信号 9 和退出，不用 sleep 猜测；保留库、原锁、WAL/SHM 和 owner。验 S 的 E6 和活动意图门须另用共同向量已闭合、manifest 代正确、Begin 为 idle、端点只读预筛通过的夹具，证明无恢复标志的正式启动实际到达 S 的目标门。未封口夹具只验共同 checkpoint 首错；端点预筛或其他前置拒绝均不能替代 S 的首错。另构造无 SHM、未终结 Begin 的场景保留原 `StaleWriter：未完成Begin须先由监督器recover`。

`REQUEST` 取 inspect 所证切面和原 Plan 的事件；从头到尾用同一 `MANIFEST`。最后一行是普通服务启动，仅转交当前凭据；E/B 确需换代则从第一次升代就用 `recover-named`，续服同时传定位其原请求的具名计划。

```sh
production_session s-recovery inspect-recovery --manifest "$MANIFEST"
production_session s-recovery recover-named --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session s-recovery query-recovery --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session s-recovery current-recovery --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
```

实施须在 **Boat Linux** 添加并实际执行 `cargo test --manifest-path rust/Cargo.toml --features production_session_testonly,s_incremental --test production_session_entry tb07_s_named_recovery -- --nocapture`，并在受准生产构建用同一正式进程接缝验正负控；TestOnly 不作正式注册表供值源。以下子用例均须登记：

| `tb07_s_named_recovery_` 子用例后缀 | 硬断言 |
|---|---|
| `before_commit`、`after_commit_before_reply` | 真杀旧 S，保留实际侧件及原锁；正常两段恢复。对比旧 pending、原 Commit、业务回执、时钟与 cut，已提交不重写，未提交原输入按原身份只接续一次。 |
| `e6_before_cleanup` | 用上述共同向量已闭合的夹具，在无活动意图、实际 SHM 尚在时，以无恢复标志的原 manifest 启动；须实际到达 S R4/E6，首错为 `UnsupportedWalShmJournalCombination`，不接纳、不动端点。 |
| `killed_after_normal_close` | 用同样满足闭合及启动前件的夹具，在 NORMAL close 成功、确认 SHM 消失但换代事务还未开始时真杀具名子进程。无标志启动须实际到达 S 锁内意图门，首错为 `StaleWriter：S 具名恢复意图尚未完成`，不接写、不重放 pending、不动端点；同请求续做，最终恰一条跃迁、同一回执、无活动意图。 |
| `killed_after_named_commit_before_close` | 具名 COMMIT 成功，在该写连接任何 close/析构及回包之前真杀；此时和退出后均无 SHM。确证同请求重送、query 取同一原字节，恰一条跃迁，补完意图后 current 可用。此项不能用正常退出后丢回包替代。 |
| `lost_reply` | 子进程正常成功退出，只在传输边界丢回包。重送、query 与持久回执逐字节相同，不再升代。新故障新名成功后旧 query 可读、旧 current 拒绝；旧请求遇另一次 SHM 不收尾。 |
| `stdout_complete_exit_nonzero` | 在已提交回执的启动路径上，先证 current 子进程完整写出规范 stdout，再在最终记账收尾注入失败、验非零退出。launcher 不转交、不启动；同 ID 查询核持久原件与唯一跃迁，不能拿旧 stdout 授权。 |
| `deployment_identity` | ① 在调用前同址换入字节相同的库；② 原 writer 或 maintenance 锁缺失或替换；③ 实际 writer 锁与既存 endpoint owner 不符，或索引已登记的 owner 缺失／替换。逐项在首次可写 SQLite open/checkpoint 前拒绝，零补锁、零 owner 变更、零跃迁；普通真空址首启仍可走原首建合同。 |
| `lost_wal_suffix` | 故障前独立持久证实最后一笔只在 WAL、未进主库；在隔离夹具分别丢失和损坏该后缀。证明主库一致、幸存旧切面能经 SQLite 重建索引并过 `quick_check`，而正式只读具名检查和恢复因故障前见证不符拒绝，保留介质、零 checkpoint／升代；未确认见证只剩旧切面同样拒绝。 |
| `lost_wal_and_shm_unflagged` | 已登记库的见证已确认事务 T，但 T 仅在 WAL。在隔离夹具丢失 WAL 和 SHM，原主库为 T-1，epoch 不变、Begin 为 idle 且无活动意图，原 E6 可归为 MainOnly。无恢复标志的一次性 `advance` 须在可写打开前报 `SRecoveryMediumUnproven`，原库零写、见证逐字节不变；不能以 launcher 的共同 checkpoint 拒绝代替。未登记的健康旧库对照按原合同可写。 |
| `recovery_key_and_epoch_preflight` | 在上一恢复已用事件 r1 且持久时钟前沿未再推进的库上，用新 ID 误用 r1。须明确拒绝已占用恢复键，零新增活动意图、零可写打开、零 checkpoint；同一新 ID 改用合法未用事件后可完成且只升一代。另以当前代为 `i64::MAX`、恢复键未占用的夹具验溢出拒绝，同样零意图、零可写打开、零 checkpoint。 |
| `contract_first`、`request_size`、`clock_modes` | 使用控制原件完整且注册表为 `AwaitingMeasurement` 的夹具，四条具名路径都返回合同首错，并以读探针证明请求、catalog 等业务载荷零读取、零物理动作；历史查询仍能读原回执。请求整件最大编码为 4,096 字节可登记并核过；上界为 4,097 字节的能力配置、以及实际送入的 4,097 字节请求，分别在登记和入口拒绝；普通结构源不因此受限。Plan 用原事件时刻且不倒退；System 在物理动作前拒绝、普通 System 路径行为不变。 |
| `clean_common_checkpoint_ready` | 全员向量已闭合，普通同址启动用当前 S 回执及不变 manifest，全员经批次放行后 S 报 `Ready` N+1。经公开 `receipt` 查原业务回执逐字节相同、按原根查原 cut；新合法输入以 N+1 得 `Committed`，旧代新写报 `StaleWriter`。查询新信封的代不冒充旧业务回执的代。 |
| `unsealed_next_bar` | 另用仅 S 推进、下一 bar 未全员封口的夹具，先取得 S current 原回执，再走普通整会话启动；首错须为 `StorageUnavailable：共同 checkpoint 未完成或不可核验`，零写者子进程启动、零接纳／发送。此项不计作 E6 或活动意图门覆盖。由获授权 `recover-checkpoint` 补齐下一 bar 向量，再持同一当前回执普通启动，达到全员接纳许可；逐项核原提交、前件与责任不重写。 |
| `media_and_handoff_refusals` | 活锁、未隔离读者、链接、锚缺损、孤立 SHM、journal 混合、超帽或到期、坏时钟或错 cut、同 ID 改请求、旧／假回执及核验至 spawn 间换代均拒。前件失败无物理动作；checkpoint 中断可审计、不写业务、代或回执。 |
| `s_only_authority_handoff` | S 恰升一代；逐字段验 X 的 `s.authority_epoch=N+1`，而 E 自身代、E `authorized_sources`、X `e.authority_epoch`、自身写者／生产者代、来源命名空间／来源代不变；下一次实际业务交换请求和应答信封使用真实 S 新代，旧执行原件仍核原代，不重发资格申请。S 动作对 E/B/X 零写，原履历与责任保持。 |

完整 H2 按 #2127 与 ADR 0038 先验同一冻结故障轨迹的恢复重复臂 R₁、R₂，再分别对未中断 C 验六面、原件、时钟、真实代际、因果与责任；本域成功或同净额不能代替整链。首版具名路径只覆盖 Plan；System 的整链验证仍取其正式支持的时钟和恢复路径，不以 Plan 或 TestOnly 的结果代替。

### 6. 实施落点与票边

仓内源码行号以 `main@0e29d008f766a82a05898244caf5a30924f24b51` 为准；以下为现有接缝，新增合同及用例由实施方交付：

- `rust/src/bin/s_session_v3/admission_anchor.rs:176–210,1359–1414`（原锚、E3/E4 拆序和当次主库身份）；`rust/src/bin/s_session_v3/admission_issuance.rs:24–47`（生效合同裁定）；`rust/src/bin/s_session_v3/admission.rs:19–55,324–343,484–532`（取原锁、原 R4、输出先于最终记账）；`rust/src/bin/s_session_v3/admission_provider.rs:159–259,261–309`（计量、侧件枚举、E6）；`rust/src/bin/s_session_v3/admission_private/mod.rs:624–677,681–740`（原 FD/VFS 审计）。
- `rust/src/structure_source.rs:23–71`（现有结构源语义无该请求上限）；`rust/src/bin/s_session_v2/mod.rs:44–52,443–476,838–854`（恢复键、Plan/System 及持久时钟）；`rust/src/bin/s_structure_session.rs:645–651`（纪元整数域）；`rust/src/bin/s_session_v3/audit_owner.rs:1155–1208,1802–1875` 和 `rust/src/bin/s_session_v3/control.rs:328–332`（Begin 门、Recover 事务及其时钟写入）；`rust/src/bin/production_session.rs:123–192,228–241,251–257,398–448`（manifest 读取、进程退出及装配）；`rust/tests/production_session_entry.rs:804–868`（正式进程夹具）。
- SQLite 证据：`rust/Cargo.lock:838–846` 所锁 `libsqlite3-sys 0.38.2` 的 bundled `sqlite3/sqlite3.c:68442–68489,68924–68960`（帧校验、扫描停止及最后有效提交）。
- 相邻基线：[E/B 请求与事务](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L27-L154)、[launcher 先核退出再消费回执](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L306-L339)、[#2139 ADR 0065 锁连续性及 owner 只读核验](https://github.com/Newchanlun/NewChanlun/blob/855cf58a42919bf904b06e000682b71a64feabc0/docs/adr/0065-production-session-endpoint-ownership.md#L51-L60)、[共同 checkpoint 与放行](https://github.com/Newchanlun/NewChanlun/blob/855cf58a42919bf904b06e000682b71a64feabc0/docs/adr/0065-production-session-endpoint-ownership.md#L212-L222)、[#2160 ADR 0073 逐域代及交换验收](https://github.com/Newchanlun/NewChanlun/blob/032a99603d44fe2f0acca56bd66d7830d8d0c8d1/docs/adr/0073-simulation-x-recovery-authority-binding.md#L72-L77)、[#2127 的双跑比较](https://github.com/Newchanlun/NewChanlun/blob/aeb79b0e1a8ce5318fe34bb370ffdb11630a2af9/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L206-L218)。未合入候选在实施前按实际合入版本复核。

原生 `#2128 → #1411` 与 `#2129 → #1411` 保留，#1366 是汇总父票，不倒设为 blocker。#2079（ADR 0065 的裁定票，当前候选 PR #2139）与 #2129 不互相等待本票；#1411 消费三份实际成果。#1527 的首错与既有消费端、#1675 的签锚及正式成功件、#1823 的端点调查、#2120 的健康域在线局部重启、#2130 的拒绝态运维各保留原职责。无法证明可安全续接时由获授权运维保全，不从历史快照自动接管；本修订不扩 Destination ④、真实宿主权限、资金或发送权。
