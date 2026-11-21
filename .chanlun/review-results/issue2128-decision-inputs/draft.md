# #2128：S 崩溃介质原址具名恢复（R1 候选；P — 原域持锁、R4 判据和换代事务均有先例；在完整 R4 前给原库加入受限的 SQLite 物理写入并发布跨域可消费的 S 原回执，仓内无同合同。本裁研发路径，不新增资金、账户、凭据、服务 uid 或宿主权限。）

## 问题

S 强杀后，能合法退役的旧 socket 不等于可启动的介质。原 R4/E6 对存在 SHM 拒绝；现有 S recover 自己也需先过 R4，且没有可供重试及跨域消费的持久具名回执。必须保住原 WAL 中已提交事实和未决输入，恢复可运行的新 S 写者；不以回退至一次较早 checkpoint 代替本次库的真实继续。

## 权威依据

- [已批 SPEC C09.2–C09.11](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L324-L334)：逐域单写、SQLite WAL 持久、引用可达、写者代守门；S 只恢复自身未完成状态，不等 E；X 的场所发送条件不同。
- ADR 0039:273–298、ADR 0059:89–124、ADR 0046:17–55 与 ADR 0050:8–35 判定 launcher/域写权、布局、锚和预算；[#2079 正式票面裁决](https://github.com/Newchanlun/NewChanlun/issues/2079#issuecomment-7051663296) 的[固定正文](https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L49-L65)保留 S 介质门，不替它执行恢复。
- [#799](https://github.com/Newchanlun/NewChanlun/issues/799)、[#804](https://github.com/Newchanlun/NewChanlun/issues/804) 与 ADR 0041:9–23：一种服务判断，各级同一；不把同一判断的宽档变成运行时自由度。不同合法任务各有边界，S 不从已拒的 serve 自动恢复。
- [非空库 R4 首错原始读数](https://github.com/Newchanlun/NewChanlun/issues/1411#issuecomment-6991449080)、[E/B 独审具名实现](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L27-L154)、[相邻比较候选](https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L159-L185)；分辨已批合同、实测和未入 main 的候选。Linux 原始机制探针在本证据分支 `probe/`，不替代产品验收。

## 候选

1. **显式域恢复，物理归一后仍跑原 R4（推荐）**。原锁、原库、原业务切面；先界定有权且有余量作物理收尾的输入，再授予逻辑恢复。代价是可测的受控 I/O 与一次具名事务；失败保留现场。与 E/B 共用具名握手语义，不混用双方 cut 或表。
2. **把“死者的 SHM”直接放进 R4。** 若仍带 SHM 就把它判为合格，或失败后自动转宽判断，违反 #799；判断死活不证明最后有效 WAL、未决以及资源合规。如果把清理变成独立有授权的动作再重新走原 R4，则等于候选 1，不是第二档。S 的各级结构不能另加例外（#804）。
3. **从最近签锚重建另库并重放。** ADR 0046 的锚不保存事实快照，无法凭它找回已提交 WAL 中的 cut 或未决；新库还改变 R4 原件身份。经审批的迁移、只读备份或灾难重建另走 C09.11，不是本次原址接续的替代。
4. **依赖正常关库、手删侧件或只执行 checkpoint。** #2077 的有序关库不能消除真实 SIGKILL；手删可能丢已提交 WAL；Linux 对照确认 EXCLUSIVE 在已有 SHM 上即使 checkpoint 成功也会留下 SHM。“成功关闭”须可见且经第二个原件切面复核。

## 裁定

正本落点：docs/adr/0050-s-resource-admission-contract-v1.md

采纳候选 1；Q4、Q5 的同族默认值拟采用。追加 ADR 0050 文末（ADR 0039 另有 #2134 在途追加，避免重叠，也不占 #2129 的 ADR 编号）。以下为正本追加正文：

## 修订（#2128，S 原址具名恢复与再准入，2026-11-21）

**断点之后继续的是原库。** S 崩溃留下 WAL/SHM 时，由 S 域持有原锁，把已提交的 WAL 纳入同一物理切面，再走原 R4；然后在原库完成具名恢复并交出新代回执。锚证明的是同一库的资源授权，不是历史快照。旧服务的 cut、内容对象、首次获知时点、已接纳输入和业务回执都从原库读取。

### 1. 显式恢复不改准入表

- 唯一正式入口仍是 [ADR 0039](0039-production-entry-inventory-and-unique-launcher.md):273–298 的 `production_session`。本节登记 `production_session s-recovery` 的四个有限动作：`inspect-recovery`、`recover-named`、`query-recovery`、`current-recovery`。动作由操作员显式选定；launcher 只把原 manifest 的 S 配置和请求交给同构建的 `s_structure_session`，不打开库、不读取 X 凭据、不拉起其他域、不创建缺失库、不处理 socket。此处替代 ADR 0039:291 对 S 原库的自动 checkpoint 启动解释。常规 `serve`、一次性 `advance`、既存 `recover --new-epoch` 的入口及拒绝语义不变；它们不隐式转入此动作。旧 Python 控制器不承接正式路径。
- 从调用开始，由 S 按原顺序验证生效合同、已发布锚和部署身份，固定原库、状态目录和侧件来源，在现行 E5 顺序取得同一个 DB `.writer.lock` 和 `.maintenance.lock`；配置使用控制锁时继续遵守本 ADR 原锁序。两个域锁从首次原件检查保持到最终连接关闭、记账和回执结束；不要释放后再把不同介质当作同一次恢复。获准部署必须能排除原库目录及锁条目被非遵约进程替换，并保证其他能打开该原库（含直接读库者）的旧组件已隔离、停止或退出。独占域锁只证明兼容写者不并发，不能代替访问隔离或 SQLite 自身锁；PID、mtime、无 FD 的一次观察、socket 归属、手工声明均不能单独授权。遇占用或无法证明隔离，保留现场。
- 仅适用经注册验证的本机持久 SQLite WAL 部署及本库当前规则。拒绝 journal、混合日志、未知侧件、不受信目录、链接、非普通或外来文件、锚/身份/介质更换、引用损坏、资源或期限不足；不尝试迁移旧 schema/旧规则。沿用 [ADR 0059](0059-production-session-layout-contract.md) 的测量域，不把 SQLite 侧件、锁或前置读写移出账。受控收尾有原 R4 之外的实际工作，需在生效准入合同的登记适用域明确覆盖该动作；锚六字段、八项资源的值与含义不改，无裸开关、无默认上限。请求解析、原件只读审计、SQLite I/O、记录，以及同次恢复的 R4、公开回执收尾，共用一次账和一个绝对期限；以调用前可证明的增量上界预留物理分配，事后照实结算。不能计量、等待超过预算或不能在受准 VFS 上验证物理界，就不批准该实现进入合同。上文 `AwaitingMeasurement` 版本仍不签锚；正式成功实例基于 #1675 的有效合同；该票旧路径读数不自动覆盖具名动作，其实际用量及适用域须由实施方核实并登进同一注册表，不以 TestOnly 通过代替。
- 普通 R4 仍在 E6 对存在 `-shm`，或 WAL 和 rollback journal 同时存在，返回 `UnsupportedWalShmJournalCombination`。具名动作先核恢复资格、改变物理介质，后面只调用这一个 R4 判定；从不让“验证过死者”成为 R4 接纳带 SHM 的第二档。物理资格衡量的是能否安全作一次原址转换，不发写者资格、不打开 listener。S 各结构级共享该判据，级别只属于输入；同介质同请求必须同结果（#799、#804）。

### 2. 清理旧介质与提交新代各有一条路

1. **只读识别切面。** 持上述锁，不经普通 SQLite pathname open，用既有钉住 main/WAL 的只读 FD/VFS 对最后有效提交做完整性和域审计、核版本、配置、当前 epoch、可达 cut、未决和持久队列，保留扫描到的 SHM 事实，但不以 SHM 内容选 WAL 前沿。不使用普通 `immutable=1` 主库直读替代 WAL 验证。仅凭尚未回包的最后一条 input 推测 cut 不可靠：`inspect-recovery` 从该审计返回制备请求所需的持久身份与切面；不发布接纳资格，不建立或更改任何 SQL 原件。新请求在恢复进程内重验原只读切面，不能凭先前 inspect 回包放行。任何非致命 WAL 尾部只由 SQLite 的有效提交语义解释；读不出真实提交、介质来源或引用不完整就拒绝，不能回退到主库旧切面。
2. **有 SHM 才物理收尾。** 只有无同名历史回执、且请求命中当前旧代/切面、时钟与媒介门均过，才可进入。用受控 VFS 在钉住的原目录打开现有库（不 CREATE、不跟链接、不换 inode、不迁移或改变日志模式），SQLite **NORMAL** WAL 连接；先配置 FULL、适用平台的同步设置与禁自动 checkpoint/失败时禁 close-checkpoint。用 SQLite 锁与真实读取复核该连接看到的最后有效切面和未决状态仍和只读证据一致；执行 `PRAGMA main.wal_checkpoint(TRUNCATE)`，只接受完整成功的 `(busy=0, log=0, checkpointed=0)`。成功才恢复 SQLite 的本地最后关库行为并检查显式 close，确认主库仍为同一原件、未出现替换/未知旁挂、SHM 和 rollback journal 不存在、WAL 不存在或已清空，完成所需同步。仅 SQLite 在受控 close 时处置自身侧件；launcher、运维脚本和 Rust 应用层均不对侧件按名 unlink/truncate，不向上交仅有 PRAGMA 成功的结果。孤立 SHM（无 WAL）不能区分 WAL 已按序清空与 WAL 丢失，首版统一以 `SRecoveryMediumUnproven` 拒绝，原件交 #2130；包括恢复进程在 SQLite 删 WAL 后、删 SHM 前被杀的罕见窗口。正常强杀服务的 **WAL 文件在且为 0 字节**不是这一情形：仍须读审计、持锁和 SQLite 收尾。没有 SHM 时不做物理收尾，支持的 MainOnly/WAL 仍进同一个 R4。
3. **再准入，再换代。** 收尾后在同一控制、锁和预算内重取本库的受控后切面，重新经过原本的 `MeasuredDomain::measure`、只读认证、计量和 H1 资格（如适用），与前切面核对可达发布、业务原件、持久未决和时钟履历。此前不得写逻辑代、收据或业务表。随后，具名恢复的原库写连接必须在第一次 WAL 访问前进入 SQLite EXCLUSIVE WAL（内存索引），不启用会另建 SHM 的并行 SQL 连接；实际排他拿不到就失败，不转 NORMAL 写者。复用 S 的 Recover 事务与审计，不经普通 serve bootstrap 或另造 Begin 处理器。事务内重新核身份、持久代、cut 和恢复时钟，按原规则只结未终结的 Begin，保留原 pending 字节及引用；原历史和已发业务回执不动。以当前代 `N` 为准做检查过的 `N+1`，和同一事务内的恢复时钟行、`writer_epoch_history`、Begin 处置和具名原回执一起持久提交。事务不推进结构发布，不作新业务 Commit，不等待 E，不重发外效。普通 S 服务开服前仍须按原逻辑接续已接纳的原件、保持相关条件门关闭直到恢复成功。
4. **中断不重算。** 物理阶段可留下内部 checkpoint 进度；失败不是原物理字节必定不变，但必须不产生业务变更、代际或成功回执，不动端点。明确已提交或未提交由 SQLite 的持久事实判，不凭进程退出码。物理收尾后、逻辑提交前中断，旧请求还只在原旧代和原切面有效；未满足第 2 点的介质继续拒绝。具名事务阶段不产生 SHM，故在事务前后真杀最多留下合法 WAL；新进程经同一 R4 可以核同一请求并回读已提交原回执，不再次升代。回包、close 或记账失败不能回报成功；一旦提交了，必须以原请求再查，不能自动换请求 ID。若已存在同请求回执又出现 SHM，视为不能由该具名事务产生的另一次介质事件：读口最多取历史回执，旧请求不能再次做物理收尾；新故障要另行绑定当前代/切面。对照：Linux SQLite 小探针中，EXCLUSIVE 对原有 SHM 的 checkpoint 返回 `(0,0,0)` 后 close 仍留 SHM；在**无 SHM** 的库上，EXCLUSIVE 事务提交后真杀则留下 WAL、没有 SHM。两个连接模式在此承担不同职责，不是两种准入判据。

### 3. 回执是域内事实，交接不改 manifest

- 请求为严格规范 JSON（最多 4,096 字节，沿用 #2082 的具名请求输入界）：`schema_revision="s-recovery/1"`、`recovery_id`（1–96 字节 ASCII 字母、数字、`-_.`）、`domain_id="S"`、`session_id`、`session_generation`、`from_epoch`、`cut={generation,structure_cut,index_frontier}`、`config={rule_revision,profile_hash,catalog_hash,clock_plan_hash,structure_source}`、`clock_event_id`。整数用原协议的规范十进制字符串；`cut` 和 `config` 取 S 持久态对应原值，结构源用已审定的规范对象。冻结配置与同一份 launcher 业务配置逐项核对，时间取原计划中该恢复事件的语义时刻且不早于持久前沿。部署路径、设备和 inode 单独在控制证据中核，不进业务回执；请求文件不含新代或调用时刻覆盖值。按 #2082 的封闭协议拒绝未知、重复、超界或错误字段。
- 成功正文为 `{"kind":"NamedRecoveryReceipt","request":<规范请求对象>,"writer_epoch":"<N+1>","recover_ns":"<语义纳秒>"}`。域在原库 `meta` 的 `s-recovery/1:<recovery_id>` 命名空间中，于同一恢复事务保存规范请求和回执原字节，绑定对应的跃迁、历史 cut 和时钟事件；保留原 Recover 的 Begin 处置证据。读取时交叉核验原件、时钟行、跃迁和历史切面，不用当前状态重新制造旧回执。同 ID 同内容回原字节，同 ID 异内容或异库/配置 `IdentityConflict`；新 ID 前代不符 `StaleWriter`，未知 ID 查询 `MissingDependency`。前代已不当前的回执仍可由 `query-recovery` 查询，不得给当前写权；读口不写库、不 checkpoint、不创建侧件。负控的主判据是持久代／恢复行／业务原件不变，而不是错误字符串恰好出现。
- 启动用 `production_session --manifest FILE --s-recovery-request REQUEST`，可与 #2082 的 `--economic-recovery-plan` 组合。启动前由 S 的 `current-recovery` 在同样的身份、锁和原 R4 下核 canonical 原件与当前持久代、无未结 Begin 及一致切面；dirty、回执缺失或过代则拒绝。旧请求仅重取原件不会恢复启动资格。launcher 只把已核的 S 回执和有效代交给 S 及 #2129 的装配边界，使用固定的同一份请求字节；S 在自己的 serve 锁内再核当前代与同一回执，早于任何 pending 推进、bind 或接纳，防核验与 spawn 间换代。失败不取 manifest 的旧代重试。未给 S 请求维持既有入口合同：manifest 自己的代与原 R4/Begin/epoch 门必须成立。
- [#2129](https://github.com/Newchanlun/NewChanlun/issues/2129) 接收此原回执及同一域从 `request.from_epoch` 到 `writer_epoch` 的有序证据，负责 E `authorized_sources`、simulation X 冻结配置的受控跟随和旧在途责任的原身份。S 不修改 E/B/X 的库、manifest、权威档或 epoch；不把裸整数、launcher 日志或 readiness 当作跨域授权。不改变 #2079 的端点认领表、#2077 的关停和 #2082 的 E/B 恢复规则。真实 X 继续受 SPEC C09.8 约束。

### 4. 可执行交接与验收

通过相邻端点合同准备 M 外、由 S 已认领的原 socket，再在专用 TestOnly 历史夹具走正式 launcher。夹具只向自己创建的 S 子进程发送 SIGKILL，并以 wait status 验证信号 9 和原进程退出；边界用通知同步，不用 sleep 推测。两个正控都先发布非空 cut；一臂再在持久 Begin 之后、业务 Commit 之前杀，一臂在持久 Commit 之后、回包之前杀。保留原库和实际 WAL/SHM、owner，禁止夹具删任何侧件或手工编辑代。先用未加恢复参数的原 manifest 重启一次：原 socket 只读预筛通过时，S 首错须为 R4/E6 `UnsupportedWalShmJournalCombination`，由原包装返回、非 0 退出，旧 socket/owner 保留。若预筛本身拒绝，则首错仍是 #2079 的 `TransportUnavailable`，不能算此用例通过；另构造无 SHM、未终结 Begin 的场景验证原 `StaleWriter：未完成Begin须先由监督器recover`。

待实施的正式入口按以下顺序调用，`REQUEST` 来自 inspect 的持久切面、冻结计划中的恢复 ID 与时钟事件；同一 `MANIFEST` 文件从头到尾不改：

```sh
production_session s-recovery inspect-recovery --manifest "$MANIFEST"
production_session s-recovery recover-named --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session s-recovery query-recovery --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session s-recovery current-recovery --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
production_session --manifest "$MANIFEST" --s-recovery-request "$REQUEST"
```

最后一步在 E/B 也发生正式换代时另传其具名计划；加入 #2129 输出参与完整 H2。S `Ready` 报 N+1；以S 公开 `receipt` 请求按原消息身份逐字节取回最后已提交的原业务回执，并从原根查同一发布切面，不比较新查询信封的代和旧业务回执的代为同一字段。提交前被杀的原 pending 依原身份接续一次，提交后被杀的已提交消息不再提交一次。新合法输入以 N+1 得到 `Committed`，旧代的新写为 `StaleWriter`；相应 H2 三臂按 #2127 与 ADR 0038 的比较合同验全历史、真实代际、因果与责任，不能删字段或以同净额代替。

实施验收在 **Boat Linux** 添加并实际执行 `cargo test --manifest-path rust/Cargo.toml --features production_session_testonly,s_incremental --test production_session_entry tb07_s_named_recovery -- --nocapture`，并对计划支持的生产构建用同一正式进程 seam 核正负控制；夹具不得成为正式注册表的供值源：

| 具名子用例（实现须登记） | 硬断言 |
|---|---|
| `tb07_s_named_recovery_before_commit`、`tb07_s_named_recovery_after_commit_before_reply` | SIGKILL、原介质、具名首错、两段恢复、同库同 socket 回到 Ready、原件与下一次 Committed；分别保留 pending 与回包前已提交原件。 |
| `tb07_s_named_recovery_lost_reply` | 在具名事务提交紧后真杀或丢弃回包；无 SHM，重送与 query 字节逐一相同、恰一条跃迁；当前核验可用。再以新故障与新名升一代后，原 query 仍可查而 current 拒绝。旧请求遇再次带 SHM 不准收尾。 |
| `tb07_s_named_recovery_media_refusals` | 活锁/未隔离读者、置换或符号链接、错误或缺锚、WAL 遗失/损坏、journal 混合、超帽/期限、坏时钟或错误 cut 均拒；前件拒绝无物理动作，checkpoint 中断可审计且不写业务或代；原 R4 拒绝照旧。 |
| `tb07_s_named_recovery_handoff_refusals` | 同 ID 改请求、旧/假回执、复核与 spawn 中间换代均不得开服；无恢复标志的健康旧入口行为不变。独立核 E/X 当前代由 #2129 原回执跟随，S 恢复动作本身对另域零写。 |

### 5. 实施落点与票边

以下位置以 main `b9d898dccf46c2a716115eaa1215bc39c458a959` 为基准；新增子命令与用例由后续实现接单：

- `rust/src/bin/s_session_v3/admission_anchor.rs:529–563,776–844,1030–1132,1239–1421`（锚、同一次 Job/期限与保全）；`rust/src/bin/s_session_v3/admission.rs:19–65,324–429`（双锁、原 R4）；`rust/src/bin/s_session_v3/admission_provider.rs:158–259,261–309`（侧件枚举、E6 不变）；`rust/src/bin/s_session_v3/admission_private/mod.rs:624–677,681–740`（原 FD/VFS 审计）。
- `rust/src/bin/s_session_v3/writer_cli.rs:262–299,769–861,978–1010`（有限动作、serve 内复核）；`rust/src/bin/s_structure_session.rs:335–403,440–495,646–655`（SQLite 持久/打开方式和 epoch）；`rust/src/bin/s_session_v3/driver.rs:626–648,800–860,867–909,7659–7742`（pending、冷恢复、旧回执先例）。
- `rust/src/bin/s_session_v3/audit_owner.rs:1155–1208,1802–1875` 与 `rust/src/bin/s_session_v3/control.rs:329–332`（原 Begin 门与唯一 Recover 事务）；`rust/src/bin/production_session.rs:251–257,276–325,398–448`（显式动作、原址装配）；`rust/src/history_simulation/runtime.rs:506–517,815–831`（#2129 消费边界）；`rust/tests/production_session_entry.rs:804–868`（正式进程夹具）；`s_session/s_service_control.py:711–748,882–915`（既存独立控制器，不接入）。
- 相邻实现参照：[已获独审的 E/B 请求、原件与事务](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L27-L154)，[launcher 调域核回执](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L249-L342)，[#2079 端点与 S 介质分工](https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L49-L65)，[#2127 候选的同轨迹与连续臂比较](https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L159-L185)。未合入代码在实现前按实际合入版本复核。

原生 `#2128 → #1411` 与 `#2129 → #1411` 都保留；#1366 是汇总父票，不倒设为 blocker。#2079 与 #2129 不互相等本票裁决；#1411 的原址整链验收消费三份实际成果。#1527 的首错与既有消费端、#1675 的签锚及正式成功件、#1823 的端点调查、#2120 的健康域在线局部重启、#2130 的拒绝态运维各保留原职责。未证明可安全收尾的库交原有获准运维保全，不从历史快照自动接管；本修订不扩 Destination ④、真实宿主权限、资金或发送权。


## 验收清单

- [ ] 同库两次真杀链照上文四个具名子用例组实际跑，原失败无建库/无代际/无业务变化，恢复后从原介质读取原回执且能继续。保留实际支持的生产构建与 TestOnly 作用域。
- [ ] `pytest -p no:cacheprovider tests/test_retired_references.py -v` 零失败，`git diff --check` 退出 0。
- [ ] 独立从 `sourceCommit` 应用 `canonical_edit`；精确 before、after 与正本提交 Git blob 逐字节对照；主分支不入送审证据。

## 受影响票与 blocking 边变化

保持 #2128、#2127、#2129 分别直接阻塞 #1411；不将 #1366 的父子关系冒充 blocker。#2079 端点、#2077 停机、#2082 E/B 回执是后续完整集成的接口，不增边、不关他们；#2120/ #2130 不收编进本票。#1527 和 #1675 的正式连续路径仍须验收，实际产品成功不由本文或 TestOnly 探针顶替。逐票状态以证据分支 `source/edges-*.json` 所载 API 查询为准。

## 授权引用

[ADR 0041 授权来源与生效边界](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md#L39-L50) 与 [#1909](https://github.com/Newchanlun/NewChanlun/issues/1909)：此为普通研发 P 类候选，待非作者异家族独审与主控消费；`user_gate=[]`。无新资金、账户、凭据、部署权限或真实运维动作授权，不修改任何旧批准记录。现有登记合同仍是运行前提。

## 引用自证

| 证据 | 回查 | 判读 |
|---|---|---|
| SPEC C09.2–11 | 固定 blob 324–334 | 逐域的先后、边界；不替换 C09.8。 |
| ADR 0039、0059、0046、0050 | 0039:273–298、0059:89–124、0046:17–55、0050:8–35 | 启动、布局、签锚、预算；锚不是快照。 |
| E6、Begin、Recover、Pending | admission_provider.rs:225–233、audit_owner.rs:1155–1208/1802–1875、driver.rs:800–829 | 普通拒绝、同一逻辑事务、原件续接。 |
| #1411、#1823 | issuecomment-6991449080、issuecomment-6687775294 | 实测 R4 与更早 socket 错误；清楚区分 SIGTERM 与 SIGKILL。 |
| #2079/#2082/#2127 | `blob-http.txt` 的固定 SHA 内容校验与 `canonical-plan.json` | 端点归属、相邻已核实现、比较候选各自范围。 |
| SQLite | `probe/wal.py`、`probe/boat.txt` | NORMAL/EXCLUSIVE 收尾对照和丢回包机制；非产品 SQLite 版本。 |

## 考古对照

| 点 | 类 | 草稿处置 |
|---|---|---|
| Q1 | A | 原 R4 拒绝、首错前提和 Begin 门照旧，见裁定 1、4。 |
| Q2 | A | 逐域所有权、同锁及端点不互认，见裁定 1、3。 |
| Q3 | A | 现行签锚、限额/原时钟不改，新增动作范围需注册，见裁定 1。 |
| Q4 | B | 采用 E/B 原回执和 S Recover 事务组合，见裁定 2–3。 |
| Q5 | B | 采用域核原回执至 launcher 的接口，同锁再校，#2129 投影，见裁定 3。 |
| Q6 | C | 推荐并采纳显式原址物理收尾；用 Linux 探针排除 EXCLUSIVE 专做清理，见候选及裁定 2。 |
| Q7 | A | 正式真进程、原始 H2、#1411 原生依赖及相邻合同，见裁定 4–5。 |

```canonical_edit
{"version":1,"operation":"edit","path":"docs/adr/0050-s-resource-admission-contract-v1.md","replacements":[{"before":"本票不提供正式成功收据；#1675 承接实测、适用库辨识、有效合同新版本和正式成功收据。合入顺序 #1527 → #1657，不把失败收据重新绑定到本票。\n","after":"本票不提供正式成功收据；#1675 承接实测、适用库辨识、有效合同新版本和正式成功收据。合入顺序 #1527 → #1657，不把失败收据重新绑定到本票。\n\n## 修订（#2128，S 原址具名恢复与再准入，2026-11-21）\n\n**断点之后继续的是原库。** S 崩溃留下 WAL/SHM 时，由 S 域持有原锁，把已提交的 WAL 纳入同一物理切面，再走原 R4；然后在原库完成具名恢复并交出新代回执。锚证明的是同一库的资源授权，不是历史快照。旧服务的 cut、内容对象、首次获知时点、已接纳输入和业务回执都从原库读取。\n\n### 1. 显式恢复不改准入表\n\n- 唯一正式入口仍是 [ADR 0039](0039-production-entry-inventory-and-unique-launcher.md):273–298 的 `production_session`。本节登记 `production_session s-recovery` 的四个有限动作：`inspect-recovery`、`recover-named`、`query-recovery`、`current-recovery`。动作由操作员显式选定；launcher 只把原 manifest 的 S 配置和请求交给同构建的 `s_structure_session`，不打开库、不读取 X 凭据、不拉起其他域、不创建缺失库、不处理 socket。此处替代 ADR 0039:291 对 S 原库的自动 checkpoint 启动解释。常规 `serve`、一次性 `advance`、既存 `recover --new-epoch` 的入口及拒绝语义不变；它们不隐式转入此动作。旧 Python 控制器不承接正式路径。\n- 从调用开始，由 S 按原顺序验证生效合同、已发布锚和部署身份，固定原库、状态目录和侧件来源，在现行 E5 顺序取得同一个 DB `.writer.lock` 和 `.maintenance.lock`；配置使用控制锁时继续遵守本 ADR 原锁序。两个域锁从首次原件检查保持到最终连接关闭、记账和回执结束；不要释放后再把不同介质当作同一次恢复。获准部署必须能排除原库目录及锁条目被非遵约进程替换，并保证其他能打开该原库（含直接读库者）的旧组件已隔离、停止或退出。独占域锁只证明兼容写者不并发，不能代替访问隔离或 SQLite 自身锁；PID、mtime、无 FD 的一次观察、socket 归属、手工声明均不能单独授权。遇占用或无法证明隔离，保留现场。\n- 仅适用经注册验证的本机持久 SQLite WAL 部署及本库当前规则。拒绝 journal、混合日志、未知侧件、不受信目录、链接、非普通或外来文件、锚/身份/介质更换、引用损坏、资源或期限不足；不尝试迁移旧 schema/旧规则。沿用 [ADR 0059](0059-production-session-layout-contract.md) 的测量域，不把 SQLite 侧件、锁或前置读写移出账。受控收尾有原 R4 之外的实际工作，需在生效准入合同的登记适用域明确覆盖该动作；锚六字段、八项资源的值与含义不改，无裸开关、无默认上限。请求解析、原件只读审计、SQLite I/O、记录，以及同次恢复的 R4、公开回执收尾，共用一次账和一个绝对期限；以调用前可证明的增量上界预留物理分配，事后照实结算。不能计量、等待超过预算或不能在受准 VFS 上验证物理界，就不批准该实现进入合同。上文 `AwaitingMeasurement` 版本仍不签锚；正式成功实例基于 #1675 的有效合同；该票旧路径读数不自动覆盖具名动作，其实际用量及适用域须由实施方核实并登进同一注册表，不以 TestOnly 通过代替。\n- 普通 R4 仍在 E6 对存在 `-shm`，或 WAL 和 rollback journal 同时存在，返回 `UnsupportedWalShmJournalCombination`。具名动作先核恢复资格、改变物理介质，后面只调用这一个 R4 判定；从不让“验证过死者”成为 R4 接纳带 SHM 的第二档。物理资格衡量的是能否安全作一次原址转换，不发写者资格、不打开 listener。S 各结构级共享该判据，级别只属于输入；同介质同请求必须同结果（#799、#804）。\n\n### 2. 清理旧介质与提交新代各有一条路\n\n1. **只读识别切面。** 持上述锁，不经普通 SQLite pathname open，用既有钉住 main/WAL 的只读 FD/VFS 对最后有效提交做完整性和域审计、核版本、配置、当前 epoch、可达 cut、未决和持久队列，保留扫描到的 SHM 事实，但不以 SHM 内容选 WAL 前沿。不使用普通 `immutable=1` 主库直读替代 WAL 验证。仅凭尚未回包的最后一条 input 推测 cut 不可靠：`inspect-recovery` 从该审计返回制备请求所需的持久身份与切面；不发布接纳资格，不建立或更改任何 SQL 原件。新请求在恢复进程内重验原只读切面，不能凭先前 inspect 回包放行。任何非致命 WAL 尾部只由 SQLite 的有效提交语义解释；读不出真实提交、介质来源或引用不完整就拒绝，不能回退到主库旧切面。\n2. **有 SHM 才物理收尾。** 只有无同名历史回执、且请求命中当前旧代/切面、时钟与媒介门均过，才可进入。用受控 VFS 在钉住的原目录打开现有库（不 CREATE、不跟链接、不换 inode、不迁移或改变日志模式），SQLite **NORMAL** WAL 连接；先配置 FULL、适用平台的同步设置与禁自动 checkpoint/失败时禁 close-checkpoint。用 SQLite 锁与真实读取复核该连接看到的最后有效切面和未决状态仍和只读证据一致；执行 `PRAGMA main.wal_checkpoint(TRUNCATE)`，只接受完整成功的 `(busy=0, log=0, checkpointed=0)`。成功才恢复 SQLite 的本地最后关库行为并检查显式 close，确认主库仍为同一原件、未出现替换/未知旁挂、SHM 和 rollback journal 不存在、WAL 不存在或已清空，完成所需同步。仅 SQLite 在受控 close 时处置自身侧件；launcher、运维脚本和 Rust 应用层均不对侧件按名 unlink/truncate，不向上交仅有 PRAGMA 成功的结果。孤立 SHM（无 WAL）不能区分 WAL 已按序清空与 WAL 丢失，首版统一以 `SRecoveryMediumUnproven` 拒绝，原件交 #2130；包括恢复进程在 SQLite 删 WAL 后、删 SHM 前被杀的罕见窗口。正常强杀服务的 **WAL 文件在且为 0 字节**不是这一情形：仍须读审计、持锁和 SQLite 收尾。没有 SHM 时不做物理收尾，支持的 MainOnly/WAL 仍进同一个 R4。\n3. **再准入，再换代。** 收尾后在同一控制、锁和预算内重取本库的受控后切面，重新经过原本的 `MeasuredDomain::measure`、只读认证、计量和 H1 资格（如适用），与前切面核对可达发布、业务原件、持久未决和时钟履历。此前不得写逻辑代、收据或业务表。随后，具名恢复的原库写连接必须在第一次 WAL 访问前进入 SQLite EXCLUSIVE WAL（内存索引），不启用会另建 SHM 的并行 SQL 连接；实际排他拿不到就失败，不转 NORMAL 写者。复用 S 的 Recover 事务与审计，不经普通 serve bootstrap 或另造 Begin 处理器。事务内重新核身份、持久代、cut 和恢复时钟，按原规则只结未终结的 Begin，保留原 pending 字节及引用；原历史和已发业务回执不动。以当前代 `N` 为准做检查过的 `N+1`，和同一事务内的恢复时钟行、`writer_epoch_history`、Begin 处置和具名原回执一起持久提交。事务不推进结构发布，不作新业务 Commit，不等待 E，不重发外效。普通 S 服务开服前仍须按原逻辑接续已接纳的原件、保持相关条件门关闭直到恢复成功。\n4. **中断不重算。** 物理阶段可留下内部 checkpoint 进度；失败不是原物理字节必定不变，但必须不产生业务变更、代际或成功回执，不动端点。明确已提交或未提交由 SQLite 的持久事实判，不凭进程退出码。物理收尾后、逻辑提交前中断，旧请求还只在原旧代和原切面有效；未满足第 2 点的介质继续拒绝。具名事务阶段不产生 SHM，故在事务前后真杀最多留下合法 WAL；新进程经同一 R4 可以核同一请求并回读已提交原回执，不再次升代。回包、close 或记账失败不能回报成功；一旦提交了，必须以原请求再查，不能自动换请求 ID。若已存在同请求回执又出现 SHM，视为不能由该具名事务产生的另一次介质事件：读口最多取历史回执，旧请求不能再次做物理收尾；新故障要另行绑定当前代/切面。对照：Linux SQLite 小探针中，EXCLUSIVE 对原有 SHM 的 checkpoint 返回 `(0,0,0)` 后 close 仍留 SHM；在**无 SHM** 的库上，EXCLUSIVE 事务提交后真杀则留下 WAL、没有 SHM。两个连接模式在此承担不同职责，不是两种准入判据。\n\n### 3. 回执是域内事实，交接不改 manifest\n\n- 请求为严格规范 JSON（最多 4,096 字节，沿用 #2082 的具名请求输入界）：`schema_revision=\"s-recovery/1\"`、`recovery_id`（1–96 字节 ASCII 字母、数字、`-_.`）、`domain_id=\"S\"`、`session_id`、`session_generation`、`from_epoch`、`cut={generation,structure_cut,index_frontier}`、`config={rule_revision,profile_hash,catalog_hash,clock_plan_hash,structure_source}`、`clock_event_id`。整数用原协议的规范十进制字符串；`cut` 和 `config` 取 S 持久态对应原值，结构源用已审定的规范对象。冻结配置与同一份 launcher 业务配置逐项核对，时间取原计划中该恢复事件的语义时刻且不早于持久前沿。部署路径、设备和 inode 单独在控制证据中核，不进业务回执；请求文件不含新代或调用时刻覆盖值。按 #2082 的封闭协议拒绝未知、重复、超界或错误字段。\n- 成功正文为 `{\"kind\":\"NamedRecoveryReceipt\",\"request\":<规范请求对象>,\"writer_epoch\":\"<N+1>\",\"recover_ns\":\"<语义纳秒>\"}`。域在原库 `meta` 的 `s-recovery/1:<recovery_id>` 命名空间中，于同一恢复事务保存规范请求和回执原字节，绑定对应的跃迁、历史 cut 和时钟事件；保留原 Recover 的 Begin 处置证据。读取时交叉核验原件、时钟行、跃迁和历史切面，不用当前状态重新制造旧回执。同 ID 同内容回原字节，同 ID 异内容或异库/配置 `IdentityConflict`；新 ID 前代不符 `StaleWriter`，未知 ID 查询 `MissingDependency`。前代已不当前的回执仍可由 `query-recovery` 查询，不得给当前写权；读口不写库、不 checkpoint、不创建侧件。负控的主判据是持久代／恢复行／业务原件不变，而不是错误字符串恰好出现。\n- 启动用 `production_session --manifest FILE --s-recovery-request REQUEST`，可与 #2082 的 `--economic-recovery-plan` 组合。启动前由 S 的 `current-recovery` 在同样的身份、锁和原 R4 下核 canonical 原件与当前持久代、无未结 Begin 及一致切面；dirty、回执缺失或过代则拒绝。旧请求仅重取原件不会恢复启动资格。launcher 只把已核的 S 回执和有效代交给 S 及 #2129 的装配边界，使用固定的同一份请求字节；S 在自己的 serve 锁内再核当前代与同一回执，早于任何 pending 推进、bind 或接纳，防核验与 spawn 间换代。失败不取 manifest 的旧代重试。未给 S 请求维持既有入口合同：manifest 自己的代与原 R4/Begin/epoch 门必须成立。\n- [#2129](https://github.com/Newchanlun/NewChanlun/issues/2129) 接收此原回执及同一域从 `request.from_epoch` 到 `writer_epoch` 的有序证据，负责 E `authorized_sources`、simulation X 冻结配置的受控跟随和旧在途责任的原身份。S 不修改 E/B/X 的库、manifest、权威档或 epoch；不把裸整数、launcher 日志或 readiness 当作跨域授权。不改变 #2079 的端点认领表、#2077 的关停和 #2082 的 E/B 恢复规则。真实 X 继续受 SPEC C09.8 约束。\n\n### 4. 可执行交接与验收\n\n通过相邻端点合同准备 M 外、由 S 已认领的原 socket，再在专用 TestOnly 历史夹具走正式 launcher。夹具只向自己创建的 S 子进程发送 SIGKILL，并以 wait status 验证信号 9 和原进程退出；边界用通知同步，不用 sleep 推测。两个正控都先发布非空 cut；一臂再在持久 Begin 之后、业务 Commit 之前杀，一臂在持久 Commit 之后、回包之前杀。保留原库和实际 WAL/SHM、owner，禁止夹具删任何侧件或手工编辑代。先用未加恢复参数的原 manifest 重启一次：原 socket 只读预筛通过时，S 首错须为 R4/E6 `UnsupportedWalShmJournalCombination`，由原包装返回、非 0 退出，旧 socket/owner 保留。若预筛本身拒绝，则首错仍是 #2079 的 `TransportUnavailable`，不能算此用例通过；另构造无 SHM、未终结 Begin 的场景验证原 `StaleWriter：未完成Begin须先由监督器recover`。\n\n待实施的正式入口按以下顺序调用，`REQUEST` 来自 inspect 的持久切面、冻结计划中的恢复 ID 与时钟事件；同一 `MANIFEST` 文件从头到尾不改：\n\n```sh\nproduction_session s-recovery inspect-recovery --manifest \"$MANIFEST\"\nproduction_session s-recovery recover-named --manifest \"$MANIFEST\" --s-recovery-request \"$REQUEST\"\nproduction_session s-recovery query-recovery --manifest \"$MANIFEST\" --s-recovery-request \"$REQUEST\"\nproduction_session s-recovery current-recovery --manifest \"$MANIFEST\" --s-recovery-request \"$REQUEST\"\nproduction_session --manifest \"$MANIFEST\" --s-recovery-request \"$REQUEST\"\n```\n\n最后一步在 E/B 也发生正式换代时另传其具名计划；加入 #2129 输出参与完整 H2。S `Ready` 报 N+1；以S 公开 `receipt` 请求按原消息身份逐字节取回最后已提交的原业务回执，并从原根查同一发布切面，不比较新查询信封的代和旧业务回执的代为同一字段。提交前被杀的原 pending 依原身份接续一次，提交后被杀的已提交消息不再提交一次。新合法输入以 N+1 得到 `Committed`，旧代的新写为 `StaleWriter`；相应 H2 三臂按 #2127 与 ADR 0038 的比较合同验全历史、真实代际、因果与责任，不能删字段或以同净额代替。\n\n实施验收在 **Boat Linux** 添加并实际执行 `cargo test --manifest-path rust/Cargo.toml --features production_session_testonly,s_incremental --test production_session_entry tb07_s_named_recovery -- --nocapture`，并对计划支持的生产构建用同一正式进程 seam 核正负控制；夹具不得成为正式注册表的供值源：\n\n| 具名子用例（实现须登记） | 硬断言 |\n|---|---|\n| `tb07_s_named_recovery_before_commit`、`tb07_s_named_recovery_after_commit_before_reply` | SIGKILL、原介质、具名首错、两段恢复、同库同 socket 回到 Ready、原件与下一次 Committed；分别保留 pending 与回包前已提交原件。 |\n| `tb07_s_named_recovery_lost_reply` | 在具名事务提交紧后真杀或丢弃回包；无 SHM，重送与 query 字节逐一相同、恰一条跃迁；当前核验可用。再以新故障与新名升一代后，原 query 仍可查而 current 拒绝。旧请求遇再次带 SHM 不准收尾。 |\n| `tb07_s_named_recovery_media_refusals` | 活锁/未隔离读者、置换或符号链接、错误或缺锚、WAL 遗失/损坏、journal 混合、超帽/期限、坏时钟或错误 cut 均拒；前件拒绝无物理动作，checkpoint 中断可审计且不写业务或代；原 R4 拒绝照旧。 |\n| `tb07_s_named_recovery_handoff_refusals` | 同 ID 改请求、旧/假回执、复核与 spawn 中间换代均不得开服；无恢复标志的健康旧入口行为不变。独立核 E/X 当前代由 #2129 原回执跟随，S 恢复动作本身对另域零写。 |\n\n### 5. 实施落点与票边\n\n以下位置以 main `b9d898dccf46c2a716115eaa1215bc39c458a959` 为基准；新增子命令与用例由后续实现接单：\n\n- `rust/src/bin/s_session_v3/admission_anchor.rs:529–563,776–844,1030–1132,1239–1421`（锚、同一次 Job/期限与保全）；`rust/src/bin/s_session_v3/admission.rs:19–65,324–429`（双锁、原 R4）；`rust/src/bin/s_session_v3/admission_provider.rs:158–259,261–309`（侧件枚举、E6 不变）；`rust/src/bin/s_session_v3/admission_private/mod.rs:624–677,681–740`（原 FD/VFS 审计）。\n- `rust/src/bin/s_session_v3/writer_cli.rs:262–299,769–861,978–1010`（有限动作、serve 内复核）；`rust/src/bin/s_structure_session.rs:335–403,440–495,646–655`（SQLite 持久/打开方式和 epoch）；`rust/src/bin/s_session_v3/driver.rs:626–648,800–860,867–909,7659–7742`（pending、冷恢复、旧回执先例）。\n- `rust/src/bin/s_session_v3/audit_owner.rs:1155–1208,1802–1875` 与 `rust/src/bin/s_session_v3/control.rs:329–332`（原 Begin 门与唯一 Recover 事务）；`rust/src/bin/production_session.rs:251–257,276–325,398–448`（显式动作、原址装配）；`rust/src/history_simulation/runtime.rs:506–517,815–831`（#2129 消费边界）；`rust/tests/production_session_entry.rs:804–868`（正式进程夹具）；`s_session/s_service_control.py:711–748,882–915`（既存独立控制器，不接入）。\n- 相邻实现参照：[已获独审的 E/B 请求、原件与事务](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L27-L154)，[launcher 调域核回执](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L249-L342)，[#2079 端点与 S 介质分工](https://github.com/Newchanlun/NewChanlun/blob/d18e70fad7aae91156ac28860acab1132a076bea/docs/adr/0065-production-session-endpoint-ownership.md#L49-L65)，[#2127 候选的同轨迹与连续臂比较](https://github.com/Newchanlun/NewChanlun/blob/15ffe5083724a858e1f0fc669f457f8e6451d84d/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L159-L185)。未合入代码在实现前按实际合入版本复核。\n\n原生 `#2128 → #1411` 与 `#2129 → #1411` 都保留；#1366 是汇总父票，不倒设为 blocker。#2079 与 #2129 不互相等本票裁决；#1411 的原址整链验收消费三份实际成果。#1527 的首错与既有消费端、#1675 的签锚及正式成功件、#1823 的端点调查、#2120 的健康域在线局部重启、#2130 的拒绝态运维各保留原职责。未证明可安全收尾的库交原有获准运维保全，不从历史快照自动接管；本修订不扩 Destination ④、真实宿主权限、资金或发送权。\n"}]}
```
