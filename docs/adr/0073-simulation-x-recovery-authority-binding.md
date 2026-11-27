# ADR 0073：simulation X 凭域恢复回执续接权威纪元

> 正本：本文件规定完整历史会话在 E/S 正式恢复后，simulation X 如何续接同一权威。
> 最后裁定：[#2129](https://github.com/Newchanlun/NewChanlun/issues/2129)（2026-11-21，T 类，依 #1323 Notes N-1 预授权判定；代理独审裁定，非 UserSigned）。
> 受影响代码清单：见文末。

## 问题

E/S 的写者换代不等于新建会话。Boat Linux 上以 #2082 的 `329be34f5a9ca9c2bcc38ae75783304cc654904c` 跑了[真进程探针](https://github.com/Newchanlun/NewChanlun/blob/0f0fd605a8412e83276a1caabda8ee74be2513cd/.chanlun/review-results/issue2129-decision-inputs/probe/boat-probe.log#L73-L110)：E₁ 提交 `ReleaseExact` 后被 SIGKILL，使用原库和 manifest 经 `recover-named`、`current-recovery` 核到原 cut 不变、写者代 1→2。仍在运行的 simulation X 对 E₂ 的首次交换报 `IdentityConflict`；直接用同一来源和命令发查询，旧目标代收到 E₂ 封装的 `StaleWriter`，改用当前目标代才得到成功应答。手填新代重开旧 X 库仍被冻结合同拒绝。

[探针第 78 行](https://github.com/Newchanlun/NewChanlun/blob/0f0fd605a8412e83276a1caabda8ee74be2513cd/.chanlun/review-results/issue2129-decision-inputs/probe/boat-probe.log#L78) 是 E₁ 提交时返回的带 `cut` 的 `ReleasedExactReceipt`；[第 97 行](https://github.com/Newchanlun/NewChanlun/blob/0f0fd605a8412e83276a1caabda8ee74be2513cd/.chanlun/review-results/issue2129-decision-inputs/probe/boat-probe.log#L97) 是 E₂ 的 `x-exact-authority/1` 查询结果，含 `ReleasedExact` 状态、原收据 ID 和提交时刻，但代字段只表明 `authority_epoch=2`，不含 E₁ 原交付代和原 cut。探针证明旧绑定会挡住新交换、当前代能查到历史结果；它用受控事实、时钟和夹具 socket，不验新版原交付引用、正式同址再服务或 S 接续。正式同址再服务归 #2079，正式 launcher 全链归 #1411。

## 权威依据

- [SPEC #1340 C07.1–7](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L297-L305)、[C09.1–11](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L320-L334) 和 [C10.1–6](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L336-L343)：本域单写、原命令与责任不可复活、真实外效不重发；完整历史验收走唯一入口。
- [ADR 0039:273–298](0039-production-entry-inventory-and-unique-launcher.md#三唯一正式-launcher-的-seam) 的「换代」是编排，不授 launcher 域写权；[#2079 ADR 0065 第 9–13 条](https://github.com/Newchanlun/NewChanlun/blob/855cf58a42919bf904b06e000682b71a64feabc0/docs/adr/0065-production-session-endpoint-ownership.md#L88-L96) 把端点、再服务与每域持锁核代分开，launcher 只核和转交显式恢复计划。#2082 的 [E/B 原回执核验](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L81-L152) 以域库、持久代和原 cut 为准；具名 CLI 与 launcher 的源码锚点只属于该候选，见文末。
- [#2128](https://github.com/Newchanlun/NewChanlun/issues/2128) 独立规定 S 的介质再准入、升代及具名 `current-recovery`；[ADR 0051:271–276](0051-per-bar-domain-event-identity-lifecycle-contract.md#三撤回与恢复幂等-新缠论推论) 约束原事实与恢复幂等。
- 本 ADR 裁定**谁凭什么重绑 X 所认的目标权威代**。部署登记、查询协议、时钟下限、历史核证和 H2 分栏均以 [#2155（#2127 的 ADR 0038 修订）](https://github.com/Newchanlun/NewChanlun/pull/2155) 为准；文中链接固定到 `e9b12ef9` 的相应条款。
- [#799/#804](../agents/doctrine-rules.md) 与 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md#授权来源与生效边界1909--pr-19152026-11-07)：保持同一身份/代/因果判据，授权不靠通信失败后改值，也不把不同域的纪元改成一项配置自由度。

## 候选

| 候选 | 判决与理由 |
|---|---|
| 按具名恢复原回执重绑同一 X | **采用。** #2082 已用域本地收据回答「哪个写者代当前有效」；按 #2127 把新旧绑定持久分版，沿用原严格交换校验。增加一份 X 本地履历和一次启动核证，不改变源身份、命令 ID、物理端点或业务根算法。 |
| 仅冻结 E/S 身份；每次交换从回复中按单调规则认代 | 裸整数只表示顺序，不能证明原库、当前写权、旧 cut 或受权的连续恢复。真实 E2 还会先拒以旧目标代构造的请求。收到拒绝后再用自报新代重判违反 #799；若先查同一域已核恢复记录并固定版本，就是采用方案，不再是逐回复跟随。 |
| E/S 一升代就提升整个会话及 X 的代 | 不能交付 #1411 的原会话续接：改变 X 写者/来源或会话代会解绑 E 的发布目标、来源授权、历史命令与挂起批次；一起升代也不能证明其他域确有恢复。真正的会话更替属于已另行授权的迁移，不能当作同身份续接的可选恢复模式。 |
| 换地址、改 manifest/profile JSON、跳过升代或重发旧请求 | #2079 的端点归属不是写权证明；手填 profile 已实测被拒，改 manifest 会改固化身份；跳过正式恢复或重发旧调用违反 C07/C09。 |

## 裁定

### 保留 X 和 E 的来源授权；只切换对端绑定的当前写者代

1. **四种身份分开。** 仅对端换代时，`session_id/session_generation`、simulation X 的 `x_id/writer_epoch`、X 的事实来源 `source_namespace/source_epoch` 保持原值；`e.authority_epoch` 和 `s.authority_epoch` 各只跟随自己域的持久 `writer_epoch`。X 的请求信封继续用原 `producer_id/producer_epoch` 和来源，目标权威代在 payload；E/S 用自己的当前代封答。只换 E 不动 S，反之亦然；普通有序关停不因重启升代。X 持有 `ExecutionRequested` 原批时被杀，只有经独立监督器证实 S 资格请求已落盘且首字节未发，才按 [ADR 0038:236–238](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L236-L238) 的专项验收 `NoRecord`。首字节已发或无法确认是否发出时，按第 8 条核 S 的实际持久原件；不得仅凭 `ExecutionRequested` 推定 `NoRecord`，也不得把跨代只读权限当成新的调用权。
2. **E 的 `authorized_sources` 不改。** 该项验证来讯的来源、生产者、其纪元与获准操作，不是 E 自身回复代，也不是 S 介质代的副本。已经冻结的 X 源 (namespace, source_epoch, producer_id, producer_epoch, allowed operations) 逐项不变。若其他用途确实需要改来源、X 的自身身份或权限，应走原版本化授权和迁移；E/S 恢复、X 和 launcher 均无权改 manifest、补配额或增删操作。原 `manifest_hash`、原 E/B 根与已入账消息按原字节核验。E 仍在自身持锁入口核自身代，B 到 E 的有效代沿用 ADR 0065 第 12 条，不取 X 的代向量。

### 先核原回执，再由 X 本地原子续接

3. **唯一凭据来自该域。** 已授权的域运维按原入口正式恢复，只有相应 E 或 S 域持本域锁核原状态并升代。E 用 #2082 的 `economic-recovery/1`；S 用 #2128 的 `s-recovery/1`，核 S 域、会话及会话代、`from_epoch`、旧 `generation/structure_cut/index_frontier`、冻结的业务配置和 `clock_event_id`，复用 `NamedRecoveryReceipt {request, writer_epoch, recover_ns}` 外壳。仅由可信 launcher 在整会话停止后的正式装配中，对配置指定的同一库、同一域 bin 和原请求执行显式 `current-recovery`，取得当前原回执。计划只定位请求；不接受手写代、普通 `query-recovery` 输出、socket 应答、launcher 日志或计划自报作为当前资格。受检条目一旦拒绝就拒绝装配，不回退 manifest 的代；未换代的域保留现有合法代。
4. **launcher 转交证据，X 决定本地提交。** launcher 将通过当前核验的完整原回执、以原域标识绑定到已验证的生产装配，经其控制且不向接客端点暴露的启动输入交给 X；不写 X 库、不拼不同计划的回执，也不把私有通道当成对手工运行路径的授权。本轮指定的 E/S 必须通过各自原有准入、取得本域锁并按所核有效代完成启动，launcher 才交本次重绑输入，X 持久化后才发布可交换状态；X 失败不改 E/S 的持久代，E/S 不反向等待 X 提交，不持有跨域锁。其他域的启动门不由 X 替代。核验后对端退出、未按该代启动或又升代时，活体交换仍严格验证唯一当前绑定，失败不热重绑；在线单域重拉归 #2120。
5. **部署首写登记不随权威换代改写。** 依 [ADR 0038:156–160](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L156-L160) 分开业务 `authority_profile` 与部署登记。重开先用同一 X 库的首写登记核获准部署的库、锁、监听及 E/S 端点与其角色；清单自洽或对端身份相同都不能替代本库登记。缺项或不符，在升代、监听和首次交换前拒绝。X 不接另一部署的回执，也不因重绑更新首写登记。

   保留创世业务档；每次重绑追加一条 `x-authority-binding/1`，包含会话及代、X 原身份、本次与父绑定序号、完整旧/新 E/S 权威向量及每项变更的精确规范业务原回执。回执按已登记业务版本核验；路径、PID、墙钟旁证与端点 owner 不进业务履历，也不能借摘要传入。有效档由有唯一前驱的最后一条记录导出；除目标权威代外的业务字段与创世档逐项相等。两域同次换代按固定 E、S 顺序形成一个向量。
6. **单步、幂等、无补造。** X 持自己的原 writer lock，在 SQLite 持久事务内核原业务档、部署绑定、历史和 pending，核回执域/会话、业务配置与创世绑定相符、域本地对原 cut 的核验成立、`from_epoch` 等于该项当前绑定、`writer_epoch=from_epoch+1` 后才原子追加并激活。启动输入指定恢复而 X 原库缺失、原回执缺项、回执被篡改、回退、跳代、跨库或跨会话，一律拒绝，不 init、不改历史、不接新业务。同一已提交的绑定与原回执重开只读回原记录，不重复追加；同一转换不同内容拒绝。提交前被杀则从先前尾部原样重试，提交后未报告则按重开规则。若域已再次升代而 X 没有接上前代，单份当前收据不足以证明连续链；保留旧库和责任并按 #2130 报告缺口，不补造中间记录或把陈旧收据当作当前。不在本合同引入多跳桥接。旧格式继续按原合同读取/同址续服，不能靠本次 `serve` 或 `recover` 就地升版；#1411 正式新实验使用 #2127 规定的新空会话版本。

### 旧交换沿原链核证，新的网络交换只走新代

7. **当前应答与历史原件分开核证。** 活体请求、应答只走当前绑定，严格核会话、源/生产者/纪元、因果和命令原件。X 为接纳、S 请求、执行证据和本地占有持久保存各事件实际使用的绑定序号、相关规范请求/应答及命令、批次和收据的因果原件；S 资格请求须在发出首字节前持久化原请求和绑定。重开、`QueryCommand` 与离线重验按事件所指的实际绑定复核，不用当前值补旧因果，也不因旧代曾在链中出现就放行。

   - **E 查询。** 按 [ADR 0038:162–166](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L162-L166) 的 `x-exact-authority/2`：外层按本次查询绑定核当前 E 应答；从 `release_origin` 核原切面及同一 E 的已核原交付代。原代、原 cut、命令摘要、原收据 ID 和原提交时刻构成交付因果引用，与查询绑定及规范应答同事务落 X 库。现 `main` 的 [`query_command`](https://github.com/Newchanlun/NewChanlun/blob/0e29d008f766a82a05898244caf5a30924f24b51/rust/src/history_simulation/runtime.rs#L595-L609) 从当前 profile 填 `authority_epoch`，不读原 cut，不能给 E₁ 原交付作证。
   - **E 交付的首次获知。** 按同一 [ADR 0038 时钟条款](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L168) 随绑定序号持久保存受信生效证据：创世用获准初始记录，重绑用受信调度器在共同逻辑时钟下记录的实际启用时点，不早于对应恢复回执的 `recover_ns`。在线接纳、重开校验、离线重验均按**本次查询实际使用的绑定**核 `first_known_ns ≥ max(原交付 commit_ns, 本次查询绑定生效时刻)`，保留真实读数并核原相位次序。缺证、时间域不一致或本地前沿过早即拒，不补值、不抬高读数。
   - **S 查询。** 按 [ADR 0038:170–174](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L170-L174) 的 `x-exact-authority/2`，`RequestConditionalExecution` 与 `QueryExecuteCommitted` 的应答信封和外层 `authority_epoch` 按本次应答所用的当前 S 绑定核验。`ExecuteCommitted` 的 `execution_origin = {request_ref, queue_id, writer_epoch, receipt}` 分别核验：
     - `request_ref` 核发送首字节前已持久保存的原资格申请消息 ID、规范请求摘要及原 S 目标代，须与原申请及当时的 S 绑定相符。
     - `queue_id` 核 S 为原命令及 E 原交付唯一持久接纳的同一队列项；恢复保留原项及其 FIFO 位置，不重新入队。
     - `receipt` 核该队列项实际首次写入的不可变终态回执，核原会话及代、S 身份、原命令及摘要、E 原交付、S 原提交切面和时刻。`writer_epoch` 须与该回执所证的实际终态提交代相等，并由 S 连续持久恢复履历证实该代是提交时的获准写者；外层 `receipt_id` 和 `commit_ns` 须与原回执相符。S₁ 入队、S₂ 接续原项并在合法稳定点首次提交、X 从 S₂ 查回时，申请代=1、提交代=2、应答代=2。申请代不必等于提交代，不把提交代改写为申请代或应答代。

     S 在同一只读切面核原申请、入队记录与终态回执的相互引用，不重做资格判定或重签原收据。X 分别持久保存本次查询及绑定、原申请及其绑定、队列引用和原收据，并核原命令、原交付与 `eligibility_ref`。非 `ExecuteCommitted` 时 `execution_origin` 为 `null`，不取得执行资格。新版 `/2` 核证失败不退回旧 `/1`。
   - **X 调用占有以实际获知 S 资格为下限。** X 按实际取得资格回执时的逻辑读数记 `first_known_ns`，随该次交换的绑定序号保存实际生效证据；后来重查不得重标已持久化的首次获知，也不把首次获知回填到原提交时点。在线占有和离线重验均核 `claimed_ns ≥ first_known_ns ≥ max(S 原提交时刻, 首次获知所用 S 绑定的实际生效时刻)`，其中 `claimed_ns` 取自原批。证据不足或原批时刻过早时保留原 `pending` 和责任；可以留存真实查回的资格证据，但不得推进到 `ExecutionReady`、取得调用占有或记为 H2 已推进，不换批或改写原时点。
8. **按持久状态续接，不按恢复动作重置。**

   | X 原状态 | 恢复后唯一动作 |
   |---|---|
   | 未接纳的新输入 | 在当前绑定下以同一原命令、精确条件及真实获知时间正常接纳；新绑定不是 S 执行资格。 |
   | `Accepted` 且持久确认尚未请求 S | 保留原 E 交付和责任；原命令能通过当前 S 独立资格门，才可首次请求。缺依赖不转成新命令。 |
   | `ExecutionRequested`（可能已发） | 仅向当前 S 只读查询原命令 ID、摘要、原交付收据及原尝试所绑定的记录。核到原 `ExecuteCommitted` 且满足第 7 条时序门才推进原批；确定拒绝/终止按原合同处理。`NoRecord`、超时、缺档或不可核：保留原 pending 和最大责任，不重发资格申请，也不取得调用占有。 |
   | `ExecutionReady`（已持久保存 S 资格，尚无调用占有） | 保留原 S 资格，不再次申请；原批和资格仍可核且满足第 7 条时序门时，按原批首次且仅一次持久取得占有，从 `ExecutionReady` 转为 `MayHaveCalled`。 |
   | `MayHaveCalled`（调用占有已持久提交） | 保留原资格与占有；不二次占有，不复制、重发或补发。simulation 只按同一原批和原提交锁走本地幂等事务，已提交则读回原结果。真实场所未知仍按 C07/C09 保留最大责任，真实 X 发送门与 #1401 不变。 |
   | `Observed` / 已完成 | 原命令、原应用、原时间、原收据可只读查询；相同内容重送读回原结果，异内容冲突。不重写责任、资格或原绑定。 |

   档案缺失、历史绑定不连续或原结果无法核验时，不以当前端点、其他代的同名记录、重算或仿真补齐。历史读取与活体写权是不同判断；活体仍只跑一套严格判据 #799/#804。

## 验收清单

由 #1411 随实施交付。故障窗由独立监督器在正式 launcher 拉起的域进程边界触发，验收以独立 oracle 和持久原件为准。

### 权威重绑与原件核证

- `authority_rebind_e_named_recovery`：真杀 E₁ 后仅 E 升 1→2，原库、原名、原 cut 不变；X 同库同纪元恢复，首个新交换收到真实 E₂ 的有效应答，B 权威读使用 E₂。核 E 的业务清单和来源授权、X 请求来源及源代、S 代、X 自身代、既有命令和收据原字节不变。
- `authority_rebind_e_release_origin`：按 [ADR 0038:218–219](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L218-L219)，真杀前由 E₁ 持久交付两笔，一笔 X 已接纳，一笔尚未接纳。重绑后，旧接纳保持 E₁ 绑定、字节不变；X 向 E₂ 查询第二笔且只新增一次接纳，E 不新增交付。重开后从 X 库核 E₂ 查询绑定和规范应答；从 `QueryCommand` 读回持久交付引用中的 E₁ 原代、原 cut、原收据 ID、命令摘要和原交付时刻。用预先独立保存的 E₁ 原件核等，不从 E 库事后补证。正式 launcher 下的 `logical-bar/1` E 精确交付与新版查询未就绪时，此项待 [#1407 C2 第 4 项的时钟接入](https://github.com/Newchanlun/NewChanlun/issues/1407#issuecomment-6738960310)；`TestOnly` 和 FIN `/6` 组件结果不销项。
- `authority_rebind_rejects_early_first_known`：按 [ADR 0038:220](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L220) 分跑两例。E₁ 均在逻辑时点 10 交付：第一例 E₂ 在 20 恢复且绑定在 20 生效，X 前沿为 15；第二例 `recover_ns=20`、实际绑定在 30 生效，X 前沿为 25。即使两层原件都有效，在线接纳、重开校验和离线重验均须拒绝；不抬高 X 读数，也不以恢复时刻代替生效时刻。真实前沿满足下限后，才可按原合同再次尝试。
- `authority_rebind_s_named_recovery`：按 #2128 正式介质再准入和当前回执恢复 S₁，下一次到期业务交换只走真实 S₂；E 不升代、不改来源。另验 E/S 同次换代只追加一个双域向量，无部分提交。
- `authority_rebind_s_commit_before_reply`：按 [ADR 0038:221](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L221)，真实 S₁ 持久提交 `ExecuteCommitted` 后、发出回复前真杀；独立证实 X 从未收到 S₁ 原包且仍为 `ExecutionRequested`。X 绑定 S₂ 后对原命令只读查回，不再次申请。核 `request_ref` 对应 X 发前持久保存的 S₁ 原申请，`queue_id` 对应原队列项，`execution_origin.writer_epoch` 为 S₁，信封与外层 `authority_epoch` 为 S₂。逐字节核 `execution_origin.receipt` 与独立封存的 S₁ 原收据相同，外层 `receipt_id`、`commit_ns` 与之相符。从 X 库核原申请及绑定、原命令、E 原交付、`eligibility_ref`、本次查询绑定和真实获知时点。独立记录须显示原资格申请一次、S 终态提交一次、X 调用占有至多一次。
- `authority_rebind_s_enqueue_commit_after_recovery`：按 [ADR 0038:222](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L222)，在 S₁ 已将原申请持久入队、尚未在稳定点提交终态时真杀，独立封存原申请、队列项和无终态的持久切面。固定条件使 S₂ 具名恢复后仍能在同一队列项的合法稳定点首次提交 `ExecuteCommitted`。X 不重发申请，仅向 S₂ 只读查回；从查回应答和 X 持久引用核 `request_ref` 承诺的原申请与申请代=1、同一 `queue_id` 及原 FIFO 位置、`execution_origin.writer_epoch` 的实际提交代=2、信封与外层 `authority_epoch` 的应答代=2，收据字节与独立封存的 S₂ 原件相同。总计一次申请、一次终态提交、至多一次 X 调用占有。

  两个 S 正控均须预置真实获知能够满足原批 `claimed_ns` 的轨迹；核过第 7 条时序门才可推进，不换批、不补造回包、不二次占有。两窗均依赖 [ADR 0038:265 的真实 S producer（TB-04-D/E）](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L265)，未交付则待前置；[内存 S 夹具](https://github.com/Newchanlun/NewChanlun/blob/0e29d008f766a82a05898244caf5a30924f24b51/rust/src/economic_session/exact_x_e2e_tests.rs#L153-L190) 和 `NoRecord` 安全留停不覆盖这两窗。

- `authority_rebind_rejects_wrong_s_origin`：在其余证据及 S₂ 外层应答均有效时，分别把 `queue_id` 换为另一队列项、把提交代错标为申请代（S₂ 才提交）或应答代（S₁ 已提交）。在线及离线均须因与原队列、原收据或 S 持久履历不符而拒绝；不接纳资格、不重发、不取得新占有，保留原 `pending` 和责任。
- `authority_rebind_rejects_early_s_claim`：按 [ADR 0038:240–242](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L240-L242) 分验两种错误。在线：S₁ 在 15 提交后、回包前真杀，S₂ 查询绑定在 20 生效，X 从持久前沿 `last_bar=14` 实读原批 15；真实查回也须留停，不进 `ExecutionReady` 或 `MayHaveCalled`，无新占有或撮合，保留原批及责任。离线：原提交 15、绑定生效 20、`first_known_ns=20`、`claimed_ns=15`，单因占有早于首次获知而拒绝；不得以这份档案充当在线读数。该留停单列专项，不计作 H2 已推进。
- `authority_rebind_rejects_invalid_transition`：缺回执、过时的 `query-recovery`、跳代、跨域/库/会话、被替换的原件、错误 cut 或配置、手填代、缺原 X 库、域未就绪或复核与使用间换主均拒绝；断言无新业务写或第二条路径。旧端点或旧写者回复不得成为有效接纳。
- `authority_rebind_rejects_cross_arm_endpoint`：直接验 [ADR 0038:270](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L270) 的 X 负控。固定原 X 库、锁、本机监听地址和业务 `authority_profile`，分别只换 `e.socket` 或 `s.socket`，指向另一真实合法运行臂的对应 socket，两臂会话、域和应答代相同。即使新清单合法且指纹自洽，X 也须因**本库首写部署登记不符**在升代、监听和任何 E/S 交换前拒绝；换回原 socket 即可重开。另验离线负控：将事件绑定错指到另一条合法记录（例如仅 S 变代、E 应答代相同的两个绑定），原 socket 不可用时仍须用持久事件证据与绑定履历查出错绑，不向对端取证。
- `authority_rebind_reopens_at_commit_boundary`：在 X 绑定事务提交前、提交后报告前分别真杀；当次分别为零条和一条新增绑定，重开最终恰一条。旧行不变、旧业务不重复，无恢复的正常再启不追加。

### 原批的一次占有与恢复分类

`ExecutionReady` 落盘、`MayHaveCalled` 占有提交、同批 `Observed` 提交是三个边界，见 `runtime.rs:738–754`、`store.rs:386–390`（文末 `main` 基线）和 SPEC C07.5–6。以下两窗分别真杀；逐命令核杀前持久状态、原 S 资格、原批、占有转换和本地事务的提交数，不能只比最终外效计数。

- `recovery_execution_ready_before_own_attempt`：在 `ExecutionReady` 已持久、`MayHaveCalled` 占有尚未提交的两事务之间杀 X。核杀前有原 S 资格、零次占有；续接保留该资格和原批，不再向 S 申请，按原批首次且仅一次提交调用占有。
- `recovery_may_have_called_after_own_attempt`：占有已提交、本地模拟原子批尚未提交时杀 X。核原占有不变、恢复新增占有为零；只走原批幂等事务，成批提交恰一次，结果可读回。
- 其他状态按第 8 条核：`Accepted` 只可首次申请；`Observed` 同 ID 同内容只读回，异内容冲突。未知时保留最大责任。持久证据不得因换代而重标，也不得复活旧身份。

**专项安全留停：X 自己在 `ExecutionRequested` 后被杀。** 专项故障点是 X 已落盘原请求、尚未发出首字节，不是仅 E/S 换代且 X 保代。按 [ADR 0038:236–238](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L236-L238)，先具备原址获准的新 `producer_epoch` 对旧批的只读路径；新代只可执行 `QueryExecuteCommitted`，保留原 `pending_epoch`、命令 `x_epoch`、原命令字节、摘要和原交付回执，不改旧批、不放宽写门或调用门。现 `main` 的 `runtime.rs:767–785` 拒绝带 pending 换代；只读路径未交付记待前置，启动拒绝不是安全留停通过。路径齐备后，R₁、R₂ 须各实得 S 的 `NoRecord`、资格申请零重发、无新占有或撮合，原批保持 pending 与原责任；在同一等待切面对拍六面，并如实记录 C 已获资格并推进的差异。这个结果只判专项安全通过。

**标准 H2：可证续跑。** 按 [ADR 0038:210–223](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L210-L223) 先验 R₁/R₂ 同轨迹，再分别对未中断的 C 核同一逻辑检查点的六面，连同写者履历、权威绑定、时点、根、原收据及因果逐项核证。未达检查点或差异无法按冻结规则核证均不通过；专项安全留停不替代此栏。H1、H3、H4 和全状态验收照 ADR 0038。

## 受影响票与 blocking 边变化

| 票 | 承接或保持 |
|---|---|
| #2129、#1366、#1411、#1418 | #2129 为 #1366 子票，保持 #2129 → #1411；#1411 实装并验收，保持 #1411 → #1418，报告消费实际绑定与履历。 |
| #2127、#2128 | 各自保持 → #1411；分别提供路径无关业务版本及 S 当前回执合同。不把实现先后当作新增原生票边。 |
| #2079、#2077、#2082、#2130 | #2079 的本域端点与关库门不变；有序关停和 E/B 具名回执沿相应 #1411 实现；#2130 接收不能证明连续性的运维诊断。 |
| #2120、#1401、#1407、#1422 | #2079 → #2120 保持，在线重拉另裁；真实发送者隔离不改；原精确交付与一次占有语义不改，#1411 消费该合同。 |
| #1323、#1340 | 不改 Destination ④、SPEC、资金或实际操作权限，无新增或删除原生边。 |

## 授权引用

本条依 #1323 Notes N-1 预授权判定。用户 2026-10-18 原话：「其实很多技术的东西 完全不需要我来做 我完全信任你的判断」。本票只为正式历史双跑选择有原件证明的恢复 seam，未开启真实场所调用、实盘权限或新资金政策；候选需非作者 R1–R8 独审通过才可落地。

受影响代码行号（未单列基线的路径以 `main` 的 `0e29d008f766a82a05898244caf5a30924f24b51` 为准）。该基线的 [launcher](https://github.com/Newchanlun/NewChanlun/blob/0e29d008f766a82a05898244caf5a30924f24b51/rust/src/bin/production_session.rs#L251-L255) 仅收 `--manifest`，[经济域 CLI](https://github.com/Newchanlun/NewChanlun/blob/0e29d008f766a82a05898244caf5a30924f24b51/rust/src/economic_session/service.rs#L1584-L1597) 无 `current-recovery`。下列具名恢复锚点只属于 #2082 的 `329be34f`，不作为 `main` 已交付的证据。

- X 接口、接纳与恢复：`rust/src/bin/x_execution_session.rs:118–162、:202–234`；`rust/src/history_simulation/runtime.rs:28–95、:296–448、:468–528、:595–640、:682–715、:729–786、:790–864、:866–941`（区分当前/历史绑定、写前证据、幂等、启动及输出）；`rust/src/history_simulation/store.rs:386–390`（同批占有才可转 `Observed`）。
- E 来源与历史：`rust/src/economic_session/store.rs:299–306、:355–395、:797–805、:993–1004`；[E `/1` 查询的目标代检查、收据 ID 与时刻](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/finance.rs#L2347-L2407)，[E 具名 CLI](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/service.rs#L1570-L1636)，[具名回执](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L81-L152)（后三项为 #2082 基线）。
- launcher 装配：[核当前回执](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L249-L342)、[E/B 有效代与 X 启动](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/bin/production_session.rs#L553-L595)（#2082 基线）；S 的接缝消费 #2128，保留本域准入门。现有夹具入口：`rust/src/economic_session/exact_x_e2e_tests.rs:153–190、:228–284`、`rust/tests/history_simulation_entry.rs:3–33`、`rust/tests/production_session_entry.rs`。
