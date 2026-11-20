本条依 #1909 代理独审裁定

状态：待非作者独审。上行是正式 resolution 的授权首行，本稿不能发布为裁定评论。

## 问题

#2079 要确定上一进程正常退出或崩溃后，谁可以在同一绝对路径发布原会话。#1823 的 CI 读数显示：两种构建各测三种布局时，S 首先在参数期以 `TransportUnavailable：socket路径已占用` 拒绝，未到 R4。#2077 正常关库仍保留名字，也按原门拒绝重启。关库、名字处置和持久写者换代必须分别证明。

## 权威依据

- ADR 0039 裁定三：沿用 `production_session` 的装配、监督和换代责任，不给发布者域写权或发送权。
- ADR 0059 裁定第 1–4、6–9 条：用已裁 M、canon 与前置拒绝；直绑 S 例外的后 bind 前提不能套到受管 S。
- SPEC #1340 C09.3、C09.7–9、C10.4 与 ADR 0038 #1539 修订：域独立、有效写者代、X 退出和在途责任、全状态恢复。
- #1823 的观察、排他反例与 SAFE 规格，#2077 与 #2082 的定向证据，见「引用自证」。#2082 的精确候选只供显式 E/B 计划参考。

## 候选

- 采纳同址每域每代新 listener。独立的 Linux 夹具观察到了原址两代答复、名字处置权与使用权分离、第一代待受理连接断开。
- 跨代留 FD 能保持连接地址，却会让新进程接受空窗排队的旧请求。保留为另一个队列合同的候选，不进入本合同。
- 未选入沿用原直绑。改址或额外入口不满足原路径条件；只有 PID 或文件身份比对不证明独占，排除据此改名或删除。

## 裁定

正本落点：docs/adr/0065-production-session-endpoint-rotation.md

仅对已获准并明确选入的同宿主部署，沿用 ADR 0039 的正式 launcher，经受信发布身份逐域管理原绝对路径。正常停机保留路径；下一代发布前分别核正常关停结果或异常退出的可证明状态、该域前代作业与 FD 回收、受管登记和持续排他。仅能退役完全匹配的旧对象。新代 FD 定向交付，不接上代待受理或已受理连接。未知、活实例、替换或排他失效保留现场。发布、退役的待办与完成使可证明的中断可以恢复，不能辨明的 bind 窗口原位保留。各域复用原业务门；端点代不充当写者代。

## 验收清单

1. 裁定件：`test -f docs/adr/0065-production-session-endpoint-rotation.md` 退出 0；`git diff --check 5a1ac9de73766f0a943c156f97cb467b7d690218 HEAD` 退出 0；获审对象确认编辑合同生成的正文与该提交字节相同。
2. 下游 #1411：在精确实现头的正式启动受控作业执行 `managed_endpoint_orderly_restart`、`managed_endpoint_crash_isolation`、`managed_endpoint_ownership_and_interruption`、`managed_endpoint_layout_and_legacy`并保留实际回执。成功线为原 cut-1 完整原业务回执逐字节相同，input-2 实际 Committed 且可读回持久提交。另验 #1411 原六面双跑与全状态合同。本稿不以未来实现结果作为本次起草交付的条件。

## 受影响票与 blocking 边变化

- #2079 待主控绑定本文及精确候选提交取得非作者独审。PASS 后由主控按流程落地、刊发 resolution 并维护 #1323 map；合入后关票。
- #1411 的完整恢复验收依赖此裁定和实际实现证据。可独立进行关库和 E/B 具名恢复验收，不把逻辑验收依赖写成已经存在的原生整票边。
- #1823 仅观察与测试规格；#2077 仅关库并保留路径；#2082 仅 E/B 具名恢复候选。#1818 → #1781 保持，ADR 0039/0059 和 #1340 原合同保持。本次不新增或删除 GitHub blocking 边。

## 授权引用

分级：P。持续负责既有 pathname 的发布和退役是仓内未裁的新取舍，不是补一段已授权清理的实现。依据「1. 分级」、#1323 Notes N-1 和 #1909。硬门清单为空；不要求真实资金、账户、场所、凭据、目录权限变更或部署。独审 PASS 不能代替这些操作的独立权限。

## 考古对照

| 点 | 归类 | 处置 |
| --- | --- | --- |
| Q1 | A | 沿用正式 owner，未选入的入口合同不动。 |
| Q2 | B | 复用 M 与前置拒绝，扩到受管 S/X 监听及发布写足迹，不扩 M。 |
| Q3 | B | 关库及回收按域取证，名字留给后续独占发布，X 独立。 |
| Q4 | B | 持续排他、登记、回收缺任一即不碰原对象。 |
| Q5 | B | 原址按域换 listener，旧队列不跨代。 |
| Q6 | C | 按域持久记发布/退役意图和完成，未知原位保留。 |
| Q7 | B | 定向交付本域本代 FD，其余副本关闭。 |
| Q8 | B | 显式使用经域核验的当前持久写者代；#2082 仅 E/B。 |
| Q9 | A | 沿用局部故障、真实就绪及 X 的发送/尾责合同。 |
| Q10 | A | 设计裁定不代签实际部署和外部权限。 |
| Q11 | B | 用同库原回执和 input-2 锁住原址恢复，不缩 #1411 全状态验收。 |

## 引用自证

| 原件 | 回查位置和本稿所用内容 |
| --- | --- |
| 分级与授权 | `.sandcastle/docs/graph-engineering.md:25-32` 及「资金与权限硬门」「SPEC 裁定」；`docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:39-48` 区分代理裁定与外部许可；[#1323 Notes N-1](https://github.com/Newchanlun/NewChanlun/issues/1323) 清单原件见同目录 `1323-map.txt`。 |
| ADR 0039、0059 | `docs/adr/0039-production-entry-inventory-and-unique-launcher.md:273-298` 正式 launcher；`docs/adr/0059-production-session-layout-contract.md:95-121` M、canon、启动前拒绝及直绑 S 例外。[#1818 正式评论](https://github.com/Newchanlun/NewChanlun/issues/1818#issuecomment-6550813315) 确认裁定，虽票现仍 OPEN。 |
| #1823 | [观察原件](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294) 两构建各三种布局，S 参数期拒绝；[后续复核](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216) 区分关库与名字排他；[规格](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6550850441) 明确未授予清理权。基线 `rust/src/bin/s_session_v3/writer_cli.rs:382-395,845-856` 校验首错与直绑顺序。 |
| #2077 | `b7b79657:rust/tests/production_session_entry.rs:934-1001` 断言 S/E/B 正常关库、路径保持、原 S 库 cut-1、重启按原门拒绝；定向 [CI 原件](https://github.com/Newchanlun/NewChanlun/actions/runs/44421504980/job/135215669141)。 |
| #2082 | `329be34f:rust/src/bin/production_session.rs:265-341,351-372,572-590` E/B 显式计划和代际接线；`329be34f:rust/src/economic_session/recovery.rs:111-154` 具名收据、当前代和同事务提交。PR 说明及非作者原件把范围限于 E/B，不包括 S 路径。 |
| 基线 X | `rust/src/bin/x_execution_session.rs:73-95,201-234` 历史模拟分支与普通骨架；`rust/src/history_simulation/runtime.rs:42-51,866-897` 本地 socket 字段及监听。 |
| SPEC 与恢复语义 | `efc1ddc4:.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:324-334,338-343,413-420` 局部隔离、发送和全状态验收；`docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md:134-139` 按证据类恢复。 |
| Linux 新 listener | `.chanlun/review-results/issue2079-endpoint-rotation/linux-fresh.log:1-9`，另核 `fresh_listener.py:4-5,17-28,42-51` 与 `run_fresh.py:18-29`。 |
| Darwin/Linux 保留 listener | `.chanlun/review-results/issue2079-endpoint-rotation/darwin-fd.jsonl:1-4` 与 `linux-fd.jsonl:1-4`，另核 `probe.py:15-27,50-54,60-80`。初试 errno 无原始日志，不作观测断言。 |

```canonical_edit
{"version": 1, "operation": "create", "path": "docs/adr/0065-production-session-endpoint-rotation.md", "content": "# ADR 0065：原会话端点同址换代\n\n> 正本范围：`production_session` 在正常关停或进程崩溃后，重新提供原会话的本地 Unix socket 端点。\n> 裁定票：[#2079](https://github.com/Newchanlun/NewChanlun/issues/2079)，P 类，依 #1909。正文经绑定当前版本的非作者独审并落地后生效。\n> 受影响接口：正式 launcher、S/E/B 受管监听入口、适用的 X 本地监听入口和 #1411 恢复验收。本 ADR 不修改实现。\n\n## 裁定\n\n**每个受管域每代新建一个监听器，公开绝对路径不变。** [ADR 0039 裁定三](0039-production-entry-inventory-and-unique-launcher.md#三唯一正式-launcher-的-seam) 的 `production_session` 仍是正式 launcher。它经受信部署入口发布、退役原名，将新监听 FD 交给指定域进程。部署可以用既有监督器执行名字操作与回收证明；监督器不独立装配业务会话。域进程只接管本域监听器，不取得目录写权；launcher 和发布者不取得域写权或发送权。\n\n显式选入适用于同一宿主内的进程接续，选入及注册绑定已获准部署的固定版本。部署保留原客户端的连接权限；客户端继续使用原会话配置声明的绝对路径、协议、请求身份和资源约束。不把上代的监听 FD、内核待受理连接或已受理连接交给新代。一条连接在换代时可以断开，客户端按既有协议查询原身份或在该协议允许时重投同一请求；断线不等于未提交、不撤销已生责任，不能触发 X 自动补发。\n\n**未选入则保持原合同。** 原 manifest、直接 pathname bind、独立 `serve` 和原 wire 调用不增加登记、目录、FD 或恢复回执前提。直接路径上遇占用仍按原行为拒绝。选入后不满足条件即拒绝，不改路径、不初始化空库、不退回直接 bind 或旧 writer。\n\n## 各域的发布与接续\n\n正常关停保留名字；新实例发布时才判断能否退役。每个域的公开端点按下表从选定配置逐项枚举。对每个实际监听名检查注册和 OS 解析后的目录项身份。两个注册项不会获得同一目录项的权利：判重覆盖同会话的各域及其他已登记会话，按宿主名字比较规则判断，不能只比路径文本。\n\n| 域与公开地址 | 正常关停后 | 崩溃后 |\n| --- | --- | --- |\n| S：launcher manifest 的 `s.socket` | S 按本域合同正常关库；发布者确认前代退出并核对登记后原址换监听器，只把 FD 交给新 S。S 仍做 R4 与原会话核验。 | 发布者确认旧作业和 FD 已回收并核对登记后才能换监听器。新 S 按正式崩溃恢复，保持旧接纳身份；R4 或持久身份失败则拒绝。 |\n| E：经济 manifest 的 `e.socket` | E 正常关库后，发布者按 E 自己的收据和退出证据原址换监听器，只交给新 E。 | 发布者独立核对旧 E 的作业与 FD 已回收，只换 E 的监听器。E 按原合同恢复 Recorded/Pending 等持久状态及当前写者代。 |\n| 各 Bᵢ：按 `economic.b[i].chong` 匹配经济 manifest 的 `chongs[j].chong_id`，取 `chongs[j].socket` | 每个 B 单独核其正常关库和退出证据；发布者只向对应重的新 B 交付其监听器。 | 只接续受影响的重；发布者确认其旧作业和 FD 已回收。B 重放自己的原归属应用，继续核对协议要求的 E 来源身份。 |\n| X：选定 profile **实际声明并监听**的本地端点 | 有本地监听器时，复用相同发布规则并只交给新 X。正常关停按 X 自己的合同证明，不把 S/E/B 关库收据当成 X 收据。 | 有本地监听器时，仅在旧 X、发送子进程及其 FD 已回收且登记相符后换监听器；发送仍须另核持久发送身份、排他锁、`MayHaveCalled` 和在途责任。 |\n\nX 没有本地监听器时，不登记地址、不传 FD、不增加 Ready RPC，X 原有的启动与就绪条件仍按获准 profile 的进程、锁和持久身份核验。X 对外连接地址不属于受管端点。在取证基线上，[历史模拟 X](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/rust/src/history_simulation/runtime.rs#L866-L897) 监听 `history_simulation.socket`；[非该分支的 X 骨架](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/rust/src/bin/x_execution_session.rs#L201-L234) 不监听 profile 的 `endpoint`。\n\n## 名字处置权来自受管部署\n\n1. **首次登记。** 在受信部署边界内，先持久绑定部署实例、不可变会话配置、本域身份（B 含重 ID）、公开路径、锚定目录和专用发布身份。该目录以及能改变路径解析的祖先和挂载由部署保护。注册只从已确认空的地址开始；直接启动遗留的地址、未登记的对象以及无法确认归属的已有目录项，不得补登记为受管资产。\n2. **排他。** 在改变名字前，发布者须持有该目录项的独占发布资格，并从核验一直持有到变更及记录完成。部署须持续禁止域进程、客户端、旧入口以及同发布身份的其他作业绕开排他，或通过改动目录、祖先、挂载与权限改变路径解析。可用专用非特权发布身份、禁止域写入的锚定目录和既有部署管理器的同名作业互斥；单靠同 UID 下的 `0700`、协作锁、PID、探活或 inode 比对不能建立排他。路径在受保护锚内无跟随核验；遇符号链接、无法核验的祖先或保护连续性中断，拒绝变更。更换部署身份、锚或挂载后重新走部署登记，不转授旧记录的清退权。\n3. **退出证据。** 正常关停须有该域的正常结果和可信监督记录，证明旧作业、持 FD 的派生进程及受控持有者副本都已回收。崩溃或强杀是异常接续；可信监督记录仍须证明同一前代作业已终止及受控 FD 无副本，launcher 崩溃也不例外。用部署监管的不可混淆作业身份、进程回收和 FD 保管约束取证；PID 消失或复用、超时、不能 connect、出现在目录里都不构成单独证据。旧域、持有者或竞争发布者仍在运行或暂停时，拒绝二次发布，不为清名杀进程。\n4. **先记意图，再改名字。** 受保护的域级登记包含端点代、发布和退役的意图与完成状态，以及实际绑定的目录项身份。只有排他、登记、退出证据相符，且目录项是上一代完整登记的原 socket 时，受信发布者才可 unlink 该目录项，再在原址 bind 新监听器。类型、设备号、inode、属主用于查错；路径目录项的 inode 不是内核 FD 的 inode。不得清理 SQLite 侧件、业务库、其他域或相邻路径。\n5. **中断按可证明状态续接。** `已登记空址` 或 `已退役` 且确认原位为空时，持久写新代发布意图，再 bind，并在交付 FD 前持久记录 `已发布`。发布意图未完成且现场是空位时，须先证明该次作业与副本均已回收，才可结束该次尝试，以新端点代重试；若已出现对象却欠发布完成记录，报「端点需恢复」并保留现场。退役意图先绑定已验的旧代和对象，再 unlink。中断后若排他及退出证据仍成立、原对象仍匹配，则续做退役；若原位已空且该退役意图及排他连续性均能证明，则补记 `已退役`。其余不一致、记录丢失、替换、退出证据不足或权限漂移，一律报「端点需恢复」并保留现场。不移走、不删后重试、不从现场猜归属。\n6. **FD 定向交付。** launcher 以显式继承白名单或经认证的私有通道交付本代监听 FD。接收方验证部署、域、代、socket 类型、原绝对地址和监听状态。当平台不提供 `SO_ACCEPTCONN` 时，用受信创建过程证明该 FD 已进入监听；不能以业务消息试发代替。其他域、客户端以及后续 exec 不得获得该 FD；拒绝时关闭收到的错误或额外副本。发布方交付后释放自己的多余副本，不把监听器留在跨代持有者手中。域仍用原协议校验、资源限制与超时，不按名字自行 bind 或 unlink。\n\n## 先做布局核验，再接业务恢复\n\n[ADR 0059 裁定第 1–4、6–9 条](0059-production-session-layout-contract.md#裁定) 仍管路径解析、并发写域以及启动前 `InvalidDomain` 拒绝。第 6 条直绑 S 的例外依赖 S 自己在 driver 打开后 bind。受管模式可更早发布，不能借用这条例外。\n\n正式入口在改名、传 FD、建域文件或拉起写域前，只读核验受管地址、登记、角色以及 [ADR 0059](0059-production-session-layout-contract.md#裁定) 的布局。受管 S、E、各 B、适用的 X 及发布、登记和互斥产生的目录变更不得位于 ADR 0059 测量边界 M：`P` 目录本身、`P` 中的 S 族条目及其子树、`A` 及其子树。按所在和实际目标目录检查副作用；不把 `P` 的其余子树误当成 M。保持原 `state_dir` 例外仅适用于原来的一次性写入，不借该例外安放受管发布状态。拒绝在业务子进程启动前抛出，并点名冲突字段和地址。接收 FD 只替换传输装配，S 仍运行 R4、资源、媒体及持久身份核验；各域仍按原规则核库和持有独占写者锁。\n\n**端点代与持久写者代分开取证。** #1411 的接续以原 launcher manifest 及所引用的域配置为静态输入。需要换写者代时，取域 owner 对原配置、库、域、前代及新代核验过的当前恢复凭证；已经提交但丢回包，按同一恢复身份取回原件，再核它仍授权当前代。不得改原 manifest 的 epoch、读裸整数加一、以历史回执冒充当前授权，或用端点代派生写者代。`serve` 在自己的域锁下仍须核现有持久代，不把 launcher 预检当写权。正常关库不自行推进写者代；是否沿用合法的当前代、是否须执行恢复换代，由本域合同决定。\n\n[#2082](https://github.com/Newchanlun/NewChanlun/pull/2082) 在候选 `329be34f5a9ca9c2bcc38ae75783304cc654904c` 提供 E/B 的实现接口：显式 `--economic-recovery-plan`，以各域的 `current-recovery` 核对回执，B 分别使用自己的写者代与对应 E 的来源代。该候选验的是完整 launcher 的 E/B 计划，不是局部重启方案。健康 E 或其他 B 不为局部恢复关停、换代或交出锁；B 对健康 E 继续走既有来源校验。本 ADR 不用该候选代替 S 或 X 的恢复凭证。独立域恢复不共享跨域事务、恢复锁或就绪闸。[SPEC #1340 C09.3、C09.7–9](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L326-L332) 与 [ADR 0038 的 #1539 修订](0038-dual-run-determinism-recovery-seek-asknown.md#修订1539恢复语义按证据类分述2026-11-02) 继续管业务状态与外效。\n\n端点可连不表示域就绪。S 以实际新域进程回答原协议的具名读请求；E 和各 B 核自身持久身份及锁，并通过原协议确认服务；X 依所选 profile 的真实服务或持锁状态判断。实现应逐项记录本次 manifest 所装配的 S、E、各 B 和适用 X 的就绪或首错。域未完成原启动门时不处理业务写入。全会话只在原合同要求的域均已就绪时报告 Ready，不能用 Ready 总状态卡住其他健康域的服务。\n\n## 候选取舍与实证\n\n- **同址新建监听器。** [Linux 探针第 1–3、6–9 行](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/linux-fresh.log#L1-L9) 记录两个 worker 的不同 PID 和同一夹具原址的 `from-1`、`from-2`。与 worker 同 UID 的客户端两次都不能创建、改名或删除该目录项。第 4–5 行记录上一代待受理连接已经写入，最后一个监听 FD 关闭后收到 `ECONNRESET`；第二代只受理了夹具的新连接。该实测分离了名字写权和监听权，代价是必须证明排他及持有者回收，有短暂断连，不能自动接管已存在的陌生地址。\n- **跨代保留同一个监听 FD。** [Darwin 第 1–4 行](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/darwin-fd.jsonl#L1-L4) 与 [Linux 第 1–4 行](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/linux-fd.jsonl#L1-L4) 记载地址仍在、不能另 bind，两层应用进程换过后目录项 inode 不变，二代实际收到空窗中排队的 `queued-before-next-generation`。最后持有者关闭后，路径仍在。跨代保留 FD 若用于另一个合同，须先裁排队、丢弃与恢复授权；它不满足本裁定的旧队列隔离，不作本合同的可切换项。\n- **保留直绑或改址。** 直绑保留在未选入的部署。轮换私有路径、抽象名或重建运行目录不满足同一原绝对路径接续；先比 PID、inode 再删除也不满足持续的排他，[#1823 的复核记录](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216) 已否决该做法。\n\n这些探针只运行本地 socket 夹具。它们未运行产品 writer、正式协议或数据库恢复，也未测 Darwin 的异 UID 同址新建；每个声称支持的部署环境须各自验证。最后持有者退出后另 bind 的 `EADDRINUSE` 是跨代探针的[断言](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/probe.py#L74-L80)，不是 JSONL 里的原始 errno 字段。\n\n## #1411 的实施验收\n\n在精确实现提交的 `rust/tests/production_session_entry.rs` 或同一正式入口的受控集成作业中执行下列验收。使用已选入、无真实外效的部署，保存 launcher 实际配置和域配置、过程收据与实际退出状态。下面是实施验收，不是本 ADR 的已跑结果。\n\n| 验收 | 二值判据 |\n| --- | --- |\n| `managed_endpoint_orderly_restart` | L1 从登记空址启动并提交 input-1。核正常关库，记录写者、旧地址及停机状态。不同的 L2 使用原 manifest 字节、原路径、原库、原会话身份和当前有效的恢复凭证启动。经正式读口固定 cut-1，读出的**原业务回执**与首次响应逐字节相同；以该会话提交 input-2，收到原协议 `Committed` 并读回其持久提交。原身份重投不产生新的业务效果。单看 SQLite cut、只探 connect 或换新库均不通过。 |\n| `managed_endpoint_crash_isolation` | 保留 #1823 既有直绑 OBS 对照的首错。在合法受管布局分别真实中断域和 launcher，覆盖旧发送者未退出和已持久接纳但丢回包。已知且可证明的退出只接续受影响域；健康域仍产生正式提交。未知情况拒绝，强杀不记正常关库。按原身份取恢复回执不会重复升代；按原业务身份查询不重复外效；`MayHaveCalled` 责任保留。simulation 及受控场所夹具分别按 ADR 0038 检查。 |\n| `managed_endpoint_ownership_and_interruption` | 对照 #1823 SAFE：活实例、暂停、PID 复用、错域/错属主、未知或被替换对象、符号链接、祖先或保护失效都保留原现场。用确定同步点验证非发布身份不能改变目录项，第二发布作业不能同时进入，错传、多传或串域 FD 被拒绝。覆盖 bind 后发布记录未完成、unlink 后退役记录未完成及记录不一致的分支；新 handler 未收到旧代积压。 |\n| `managed_endpoint_layout_and_legacy` | 受管端点、登记或锁命中 M 时，在文件变更或 spawn 前拒绝；原 R4、坏锚、旧 epoch 和独占锁负控仍拒绝并保留真实首错。未选入部署用原调用与原占用拒绝对照；无本地监听器的 X 不新增地址前提。 |\n\n[#2077](https://github.com/Newchanlun/NewChanlun/pull/2077) 的验收是正常停止 S/E/B 写者并保留 socket 路径；它不提供路径接续。负责 [#1411](https://github.com/Newchanlun/NewChanlun/issues/1411) 实施验收的 owner 按本节接入原路径与各域有效恢复证据，并执行该票原有双跑、崩溃和全状态比较。端点接续及 E/B 子合同的 PASS 都不能代替这份结果。[#1823](https://github.com/Newchanlun/NewChanlun/issues/1823) 提供观察与 SAFE 规格，不承担实现或授权。\n\n## 不授予的权限\n\n本 ADR 规定满足何种前提的发布者可在未来获准部署中退役自己的受管目录项，不给任何现有进程、账户或运维人员新增 `unlink` 权限。发布者不读取或持有场所凭据，launcher 既有 X 凭据装配不变。本 ADR 不授权修改宿主目录、服务身份、隔离或挂载，不授权安装、迁移或启用生产部署，不授权真实资金、下单、场所/账户激活、风险参数、密钥、凭据或发送权限。涉及这些操作时使用其各自的授权与验收入口。[ADR 0041「授权来源与生效边界」](0041-degrees-of-freedom-configurable-not-excluded.md#授权来源与生效边界1909--pr-19152026-11-07) 不变。此处不修改 ADR 0039、ADR 0059、缠论/交易判据、R4、既有恢复帽或 #1323 的 Destination。\n"}
```
