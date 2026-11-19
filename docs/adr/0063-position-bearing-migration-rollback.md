# ADR 0063：带仓迁移、回退与责任退休

> 正本：本文件是带仓迁移、回退与责任退休协议（migration-cutover/1、migration-source/1、阶段停点、受控收尾）的正本。
> 最后裁定：#1535（FU-13，2026-11-13，T 类，依 #1323 Notes N-1 预授权判定；代理独审裁定，非 UserSigned）
> 受影响代码清单：见第八节

## 一、背景与范围

#1340 已裁切换先禁旧发送、新旧不双写、回退保留新外效、MayHaveCalled 不自动重发及责任退休原则。本 ADR 将这些原则组成带持久证据的带仓迁移协议，裁迁移记录、身份 crosswalk、归属继承、单写者衔接、回退和恢复语义。

本 ADR 只裁协议，不执行实际迁移。#1368 在目标部署导入／切换前取得真实持仓、未结单、尾账及历史归属读数并完成非空验收；现场读数不是本 ADR 的起草前件。本 ADR 不虚构现场库存，不声称生产切换已获准，也不新增 research/probe 或 blocking 边。

真实资金、账户或场所激活、量档容量、成本／风险阈值、凭据及权限授予仍须对应用户授权。本 ADR 不签署这些值，代理裁定来源不得写成 UserSigned。P2 激活时拒发期间真实挂单能否撤单或平仓，依 ADR 0062 裁定七届时重裁，本 ADR 不预设。

## 二、版本化记录及唯一写者

### 1. migration-cutover/1 是共同外壳，不是跨域总账

每次迁移有稳定 migration_id。各域权威收据共用 migration-cutover/1 外壳，至少包含：schema_revision、migration_id、domain_id、stage、输入身份及内容哈希、来源版本、前件收据引用、证据引用、前后提交前沿、writer_epoch 和结果。

每条权威收据只由所属域唯一写者在本域 SQLite/WAL 事务中持久化。migration_id 只是关联键，不授权 launcher、部署监督器或查询壳另写一份跨域权威总表。launcher 只收集各域收据并形成非权威编排证明；跨域阶段汇总和 migration-source 视图由 Q.ReadEconomicView 重算，只读、可重算、不反写。

### 2. migration-source/1 的权威 owner 是 E

E 域持久化 migration-source/1 权威来源行，每行有稳定 migration_source_id，并至少包含：migration_id、旧系统命名空间、旧入口与旧记录身份、标的及场所身份、原始内容或内容寻址引用、来源证据、旧操作级别与旧 Voice／订单／事实身份、责任及尾账因果锚，以及可用的新域身份引用。

E 另按既有合同写迁移外部事实原件、责任快照引用及逐重分配。各 Bᵢ 只在本域写 position application、与 E migration_source_id／allocation_id 的链接及核平前沿。X 只在本域写旧发送／观测身份链接、真实调用引用及后续观测。S 仅在自身结构身份或前沿实际受影响时写本域收据。跨域链接使用稳定身份逐跳拼接，不让任何域代写另一域的权威行。

### 3. X Imported 的实际输入

X Imported 接收只读迁移包中的 migration_id、migration_source_id、旧命名空间、旧命令／场所订单／观测身份、原始内容引用，以及旧系统中真实存在的 OwnAttempt／MayHaveCalled 和观测记录引用。X 将这些真实引用与本域迁移收据及实际观测关联。

旧命令没有新发送身份时显式记录 command_id=null；没有真实旧调用记录时 own_attempt_ref=null、may_have_called_ref=null。不得为导入伪造 OwnAttempt、MayHaveCalled 或观测。未知旧订单以 external_effect_status=unknown 保留最大责任，只进入只读对账与责任闭包，不进入新发送队列。缺少完成 crosswalk 所必需的真实观测跳时报缺，不用空引用冒充已核平。

## 三、固定阶段及停点

阶段严格为：

1. Surveyed：非权威枚举旧入口、记录和潜在外效路径，不把冻结前读数当权威快照。
2. SendFrozen：证明旧程序新发送和切换期间新发送均冻结；已在途外效继续保责。
3. LiabilitySnapshotted：冻结后由 E 记录旧订单、持仓、费用、更正、未决命令及最大责任。
4. CrosswalkValidated：离线验证 schema、原始事实、身份／责任／尾账 crosswalk；缺跳或冲突不得进入导入。
5. Imported：E、各 Bᵢ、X 各自由本域唯一写者按本域事务幂等导入；S 仅在有本域变化时参与。
6. Reconciled：逐身份核平旧外效、E 原件、逐重分配、Bᵢ 应用及 X 观测；各域分别记录核平前沿并发布各自新 writer_epoch。
7. SendEligible：只有既有授权、TB-09 隔离证据及该证据类现行发送门均满足时才允许 X 新发送；迁移完成或 epoch 提升本身不授予发送权。

跨域阶段转换只引用前序各域已持久收据，不由汇总写者补写。同 ID 同内容重复导入返回原收据，不新增事实、应用或调用；同 ID 异内容报 IdentityConflict。任何缺证、冲突或失败均停留当前阶段，不删除事实、不恢复旧 writer、不改用宽松判据。

## 四、持仓、成本与尾账继承

逐条继承已证明的重、Voice、成本和尾账归属。旧 ladder、旧 Voice 标识和旧实现字段只是待核来源，不自动等于新重编号或新 Voice。

已有迟到事实回到原 Voice；归属或成本无法证明的部分保留未决责任和最大敞口并封闸，不按净仓重建、不平均分摊、不统一挂 Voice 0。非空持仓只能经 crosswalk 记录 id 进入 TB-10 输入，禁止裸数量。迁移不生成新的资金分配政策。

## 五、不双写及旧发送隔离

切换期间旧核不得继续权威写，新核不得在旧发送仍可能外效时开启新发送。迁移收据必须分别引用：

1. 外效隔离证据：目标部署中的旧入口、发送子进程、持久发送身份、凭据作用域和旁路核查结果，并衔接 ADR 0048 逐入口清单及 TB-09 具名证据。
2. 域库单写者证据：S、E、X、各 Bᵢ 的排他锁、获准 epoch 及旧 epoch 写入拒绝结果。

两种证据不得相互替代。锁或 epoch 不取消已发网络请求，其最大责任继续保留。迁移或回退后 X 的新 epoch 必须重走发送门，绑定行不回退。实际退出进程、撤销或更换凭据、修改账户权限只按既有合同及具体授权执行，本 ADR 不追加授权。

## 六、在途未知、长期身份与 MayHaveCalled 不补发

真实 OwnAttempt／MayHaveCalled 的身份、内容绑定、已持久观测和最大责任全部保留。没有记录、超时或未见回报均不证明未发送。未知旧订单只进入只读对账和最大责任闭包，不铸造第二次调用资格。

迁移前后相同旧外效只能命中同一迁移身份；重复导入同内容返回原收据，异内容构成冲突。恢复从持久日志重放至最后提交并先只读对账。首次占有前、MayHaveCalled 提交后调用前、调用后回报前、迁移提交、换档中断及 epoch 更替均不得新增调用。本 ADR 不启用 #1340 C07.6 另列的强幂等重投例外。

不可复活命令身份、内容摘要、判定和一次调用占有记录为长期审计事实；可迁往只读分段归档，但查询必须覆盖全部有效代际。归档去重依据不可读时报缺，不得把历史 ID 当新 ID；回收普通流游标不回收命令去重依据。

## 七、回退、受控收尾与责任退休

回退是保留新外效和尾责的受控收尾，不是恢复旧交易。当前能读取新责任格式的新核及其唯一 X 写路径接管：停止新增承担，保留全部已提交原件、应用、调用状态和尾账，先只读对账。

只有有效 ADR 0030 退出授权且该证据类现行发送门允许时，才按原授权 id 和动作范围续做撤单或平仓：

- P1/experiment：依 ADR 0062:114-120，拒发期间下单、撤单、reduce-only 平仓及急停展开命令均被拦截；退出授权保持待续，只读查询和恢复对账照常，到下一个通过发送门的新 epoch 再以同一授权 id 续做。
- production/P2：不外推 P1 拒发语义；拒发期间能否撤单或平仓服从 ADR 0062 裁定七届时重裁结果。本 ADR 不预设其值，也不生成该分支的发送资格。

不能理解新格式的旧程序不得恢复交易，不删除事实、不回退旧 writer。发布或二进制回退前必须证明候选仍能读取并保全现行责任，否则停在新核收尾态。

责任退休继续按 ADR 0030 四条件同时成立：全部订单经场所回报确认终态；归属该 Voice 的持仓为零；费用及锁额费用尾由实收事实结清、差额进尾账；E 中无 Pending。迁移不改变退休判据，也不删除退休历史。迟到事实在同一 Voice 重开责任，永不挂新 Voice；恢复续退使用同一授权 id，并服从分域发送门。

## 八、实施验收锁与受影响代码

以下测试是 #1402、#1368 及下游的交付义务，当前不声称已存在或通过。生产资格测试统一落 rust/tests/production_session_entry.rs，在 Linux/CI 以 --features production_session --test production_session_entry 实际运行；每项使用 --exact，退出码为 0 且实际执行恰 1 项，过滤为 0 项即失败。不得靠默认构建扩容、脱离生产路径的模型骨架或 TestOnly 证据满足生产资格。若另加 TestOnly 故障臂，须显式使用 production_session_testonly，且只能作补充。不得在 macOS 本机运行 cargo/rustc。

| 测试名 | 二值判据 |
|---|---|
| migration_phase_receipts_enforce_freeze_before_authoritative_snapshot | 无有效 SendFrozen 收据不得进入 LiabilitySnapshotted |
| migration_domain_receipts_have_single_writer_and_readonly_projection | 各域权威行只能由本域写者提交；launcher／投影写请求数为 0，投影可重算 |
| migration_import_is_idempotent_and_preserves_crosswalk | 同内容重复导入不新增事实或应用，异内容报 IdentityConflict |
| migration_crosswalk_rejects_missing_or_conflicting_voice_attribution | 缺跳、异内容和不可证归属报缺或封闸，不按净仓补猜 |
| migration_old_sender_isolation_is_distinct_from_writer_epoch | 只有 epoch／锁证据而无外效隔离证据时拒开新发送 |
| migration_may_have_called_never_resends_across_fault_points | 占有、调用、回报、迁移提交、换档中断及 epoch 更替各断点新增调用数为 0，最大责任不丢 |
| migration_x_import_never_fabricates_own_attempt | 无真实旧调用时相关引用为空，且不进入新发送队列 |
| p1_migration_rollback_preserves_external_effects_and_respects_send_refusal | 仅 P1/experiment 射程内，回退保留外效、尾账及绑定行，拒发 epoch 写请求数为 0 |
| migration_late_fact_reopens_original_voice | 迟到事实重开原 Voice，不生成新 Voice 承接旧责任 |
| migration_nonempty_positions_open_orders_and_tails_are_required | 非空持仓、未结单、费用尾、中断恢复及回退实际构造并通过，空仓样例不计通过 |
| migration_long_term_identity_survives_generation_change_and_archive | 换档、迁移及归档后长期身份仍可查；归档去重依据不可读时报缺，历史 ID 不当新 ID |

受影响代码及理由：

- rust/src/theta_v0/nautilus/account_adapter.rs:6-10：不编译骨架把场所净仓写入 voice_qty[0]，不得作为迁移归属先例。
- rust/src/trading/isolated_fugue.rs:88-119：旧 VoiceLedger 的 ladder、units、basis 和亲缘字段只能作待核来源。
- rust/src/economic_session/store.rs:657-661：StaleWriter 只证明域库 epoch 拒绝，不证明旧发送外效隔离。
- rust/src/session_transport.rs:56-75：现有 .writer.lock 是各域单写者证据之一，不是跨域权威总表入口。
- rust/src/bin/x_execution_session.rs:1-22、113-145：当前 X 骨架无场所写实现且含 dry-run；Imported 实装不得伪造调用历史或借骨架声称迁移完成。
- rust/Cargo.toml:63-95、299-308：default=[] 及 required-features 决定验收必须显式绑定生产 feature/target。
- rust/tests/production_session_entry.rs:1-13：本节生产测试的落点；保持 Linux 实际进程入口与 TestOnly cfg 分流。

本 ADR 不声称当前代码已具备真实迁移能力，也不以协议裁定关闭下游行为验收。

## 九、对下游的接口

- #1365／#1383／#1401：消费外效隔离与域库单写者双证据；#1401 不得把 P1 拒发语义外推为 production 已裁。
- #1367：传递迁移或回退后 X 新 epoch 重走发送门、绑定行不回退。
- #1368／#1402／#1413：执行现场盘点、非空迁移、默认启动、回退及恢复验收。#1402 承接第八节测试的实现与交付；换档中断由故障点恢复测试和长期身份测试承接，长期不可复活身份及归档去重由长期身份测试承接；#1413 继续核默认启动只到新核。
- #1369：将不丢权利、不复制资金、不双写和不补发纳入整体验收，P1 与 production 证据分列。
- #1330：继续实现 OwnAttempt／MayHaveCalled 实体合同；本 ADR 不新增其对 #1535 的阻塞。
- #1769：继续消费 X profile、绑定行、发送门实装、dry-run 实装滞后及恢复时钟合同；本 ADR 不定 recover_ns。
- #1551：整图报告引用本 ADR，但仍须核对下游实际证据。
- P2 激活路径：依 ADR 0030:74 的 #1561 后继指针及 ADR 0062:118 重裁拒发期间撤单／平仓与退出授权续做。

本 ADR 不新增或删除 blocking 边。

## 十、不在范围

- 实际目标部署的持仓、未结单、尾账和历史归属读数；
- 真实切换、撤单、平仓或任何场所写调用；
- 真实资金投入／取出／改额、账户或场所激活、量档容量、成本／风险阈值；
- 凭据授予、撤销、更换或账户权限修改；
- P2/production 拒发期间撤单、平仓及退出授权续做的政策选择；
- 资金或 Voice 的重新分配政策；
- OwnAttempt／MayHaveCalled 的实体实现；
- ADR 0060 已裁的运行期四跳 crosswalk；
- 关闭 TB-08、TB-09、TB-10、TB-11 或整图验收。
