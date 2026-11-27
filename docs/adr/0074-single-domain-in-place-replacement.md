# ADR 0074：launcher 存活时单域原址换代与续服

> 正本：本文件是 launcher 存活时单域原址换代与续服合同的正本。
> 最后裁定：[#2120](https://github.com/Newchanlun/NewChanlun/issues/2120)（2026-11-21，P 类，依 #1909 / ADR 0041 代理独审裁定，非 UserSigned）。
> 受影响代码清单：见文末。

## 一、问题与前提修订

当 S、E、某个 B 或带本地监听的 simulation X 停止服务时，保留同一个 `production_session` 和其余健康域。只让失效域重开原库、在原地址建立新监听；仍在运行的依赖方核对权威代，已提交事实和在途责任不随进程重启。这里的**进程换代**总是更换进程；**写者升代**只发生在原域正式恢复事务中。正常关库后重开不强制升代。端点实例只指本轮实际 listener 的身份，不另设持久端点代或登记簿。

[#2120 票面 2026-11-21 更新](https://github.com/Newchanlun/NewChanlun/issues/2120)以 [ADR 0065](0065-production-session-endpoint-ownership.md) 为前置，适用其第 13 条划给 #2120 的在线单域范围。逐项替换旧题面：

- 删除「受管模式」「首次受管部署」「重登」「在 #2120 前不得作为默认部署」等模式/配置前提。仍未通过局部再服务验收的部署，不能声称已通过 C09.3 的重启局部性。
- 删除「独立部署监督器出具退出证明」「把退出证据交发布助手」：存活的正式 launcher 只观察自己拉起的进程和已受控的后代；本域进程证明实际写锁及端点资格。
- 删除「发布助手只处理该域登记」「按登记簿/登记代选新端点」「预留或交接监听 FD」：按 0065 第 1、5–6、8 条，本域锁持有者新 bind 并证明本次监听器；同名残留按持久意图核验后只改名退役，不删除、不移交旧监听 FD。整会话停启沿 0065 的共同 checkpoint 与两阶段放行合同。
- 保留三问：谁请求、谁有排他装配资格、怎样确认前代退出；新域怎样自证、健康 E/B 如何双向核来源代及 X 如何跟随；逐域协议与恢复、Ready、外部权限判据是什么。

本稿在触发主体、在线接续及来源切换上有真实方案取舍，属 P 类。按 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 39–48 行，绑定本稿精确版本的非作者 R1–R8 独审通过才生效；不是外部操作授权。第七节钉住所引 ADR 和实现版本；引用同辈分支不等于它们已经合入。

## 二、权威依据与实证事实

1. [SPEC #1340 C09.1–11](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L324-L334) 和 [IC:62](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/INTERFACE-CONTRACTS.md#L57-L62) 要求本域先恢复、单写者、局部恢复不共享闸、历史责任延续。[ADR 0039](0039-production-entry-inventory-and-unique-launcher.md) 裁定三（A，273–298 行）给 launcher 唯一装配权而非域写权；#2079 附记（A，514–518 行）明确各域持锁恢复、launcher 只读汇总共同证据。[ADR 0059](0059-production-session-layout-contract.md)（A，95–121 行）定 S 测量域 M，物理目录、挂载别名与库侧件硬门按 ADR 0065 第 3–4 条加强。[#799 规则](../agents/doctrine-rules.md)（A，43–55 行）要求同一资格不因失败换宽判据。
2. R5 简报（D，`DESIGN.md` 5–14、67–71 行）解释删掉外部发布身份、登记与模式。以 ADR 0065 为准：按第 2、4 条证明锁对象连续并取得锁，不等于前代已退出；六键 owner 只从钉住的普通 FD 更新（A，55–60 行），持久退役意图和已钉对象验证按第 6 条（A，78–82 行），新监听器单独按第 5 条出证（A，61–77 行）。E/B 的关库标记和 S R4 各走原库门（第 9–10 条，A，88–93 行）。#2120 增加 **launcher 存活下的装配前提**，不把进程观察改成端点授权。
3. PR #2082（N）要求恢复计划键与 launcher E/B 成员全集相同；ADR 0065 第 12 条（A，95 行）已裁可为子集，但每个提交项仍通过同样的当前回执核验；子集不缩减整会话共同 checkpoint 的成员。N 的 E/B `current-recovery` 虽然后续 SQLite 只读，CLI 仍先拿与 `serve` 相同的域锁；三条具名 CLI 均如此。B 的 `--e-epoch` 读一次进入服务闭包；每次新 `ApplyAllocation` 在自己的写事务外从固定 E 库只读核持久代、审计、原事实和原回执，不连接一个「E 换地址」即可通过的通道。本域已应用原请求的查回先于新读 E（N，文末列行）。
4. #2127（P、PI）分开业务身份与部署映射、按持久版本读历史，保留原根和证据；#2128（S、SI）在原 S 锁与 R4 下提供原址具名恢复及启动内复核，不让任何读口绕过 SHM 闸；#2129（X、XI）只推进 simulation X 的 E/S 权威向量，保留 X 自身写者/事实来源和 E 的 `authorized_sources`。XI 的 E 私有快照确实能从活动 WAL 复核**已由可信装配方定位**的具名原回执，不是发现活 E 的通用接口；`QueryAuthorityOriginal` 是 **X** 的历史原件读口（XI，`rust/src/history_simulation/runtime.rs:1663–1667`、[`authority_history.rs:107–129`](https://github.com/Newchanlun/NewChanlun/blob/b276e3f400c3c09f51793ec9cfcf4adde647274f/rust/src/history_simulation/authority_history.rs#L107-L129)），不在 E 的操作表（XI，`rust/src/economic_session/service.rs:1430–1492`）。XI 的重绑是二进制启动接缝，该候选没有 X 在线重绑。
5. **Boat Linux 隔离见证。** P1–P3 见 `/Users/silencehan/.t3/evidence/issue2120-r1/sol/`；P4–P7 见 `/Users/silencehan/.t3/evidence/issue2120-r2/sol/`。各轮的 `RESULT.md` 索引命令、脚本和原始输出。以下是组件/候选辨别，不充当第六节的正式入口验收：

   | 编号 | 隔离观测 | 区分什么 |
   |---|---|---|
   | P1 | `probe-1-2.log`、`probes/base_eb.py`：N 真 E 同一原回执停服时查询成功（单样本 2.91 ms），持锁时退出 1（1.22 ms）、`StaleWriter`；B 写者从 1→2 且新提交时，E 同 PID、同 socket、同代，从 cut 1 提交到 cut 2。用可信定位的原回执、原库只读事务、原事实/代/cut 和真 E 当前应答对照。 | 只读的旧 CLI 不等于在线可用；不用终止健康 E，可独立验证原件再核活体。 |
   | P1X | `probe-1x.log`、`probes/x_live.py`：XI 真 X 在真 E 持锁、活动 WAL 下复核 E 恢复原件；只看 immutable 主库读到前代。真 E 的 `ReadView` 能核实时服务与代，但不给具名恢复原件；`QueryAuthorityOriginal` 只能在 X 按引用读历史。 | 原件/内核活体是两项证据，普通在线查询、快照和预签件不能互相替代。 |
   | P2 | `probe-1-2.log`：N 的运行中 B 在 E 升代后仍按 argv 的旧来源代拒 `ApplyAllocation`；B 自身锁、端点、原 cut 仍在。隔离原型用真 E 两代帧、真实 pidfd 和本地 SQLite 事务区分旧实例退出、当前身份校验、切代、丢 ACK 重读及旧字节保留。 | 固定参数与换 sockaddr 都不能推进 B；本域单序事务有可测切换点，不需要停健康 B。 |
   | P3 | `probe-3.log`、`probes/kernel.py`：已验明的正常退出和强杀获得锁及 `ECONNREFUSED`，钉住对象后只改名、新 bind；活、SIGSTOP、未知、坏 owner 及后代保留锁/监听/仅 bind FD 均拒。可观察到进程仍活而锁空且试连拒绝；也可观察到主进程退出且两个内核端点条件成立，但后代仍持仅 bind FD。 | 排除用探活、flock 或主进程退出单独授权。复用 launcher 的子进程身份，无须独立发布进程。 |
   | P4-frame | 原版 E：切面 2 的完整 image 为 34,271 B，帧界 24,000 B 时 `ReadView` 返回 0 B/EOF；原 E 拒未登记 B。头协议原型对同一真实历史 cut 精确核根与摘要；原 E 提交 cut 3 前后均 929 B，错根和错主体拒绝。 | 活体探针走独立有界读头；不能靠普通单帧或借主体。 |
   | P5-finance-s | 固定源码证实两种财务读把 S 代锁在 manifest；三个独立 SQLite 消费方原型在测试权威 1→2 后各追加一行，拒延迟旧帧，丢 ACK 重读，不改历史字节。 | 持久单步绑定可以保住新接纳与原历史的不同预期，不用重拉 E/B。 |
   | P6-sigstop-pipe | 原版 E 暂停时未检查就写 `0x01`，`SIGCONT` 后原进程退出；先核 `WIFSTOPPED`、不写的臂恢复后原 PID/socket 应答。 | 已暂停拒绝与写后超时不是同一个状态。 |
   | P7-opath-lock | 传原锁 FD：持锁进程被杀后两锁仍忙。传独立 `O_PATH`：`flock/read/write` 均 `EBADF`，原进程被杀后继任者立即实取两锁；反向交付匹配，换 maintenance inode 拒绝。 | 参照不续命锁；必须在下任域开库/认领前查原锁对象。 |

## 三、按 ADR 0065 新形状重列的平行候选与取舍

| 候选 | 触发与交付 | 代价与取舍 |
|---|---|---|
| A：操作方显式请求，存活的 launcher 单域装配，B/X 本地切换，对 E 使用原库私有快照核证 | 值班操作方选目标；launcher 收束进程身份及受信交接；目标域自己持锁、核准入、认领地址；消费者走同一个当前绑定判据。 | **采用。** 不改变健康写者的进程/锁，不增监督进程。E 业务 socket 新增仅对登记成员开放的有界活体头，不负责出原件；快照超预算或不一致就拒。B/X 需本地权威链，带 finance 的 E/B 还需 S 权威链。 |
| B：同一 launcher 自动发起，活 E 利用现有写者锁提供专用读证 | 只允许已证实退出的成员由 launcher 自动排队，仍由域认领；在线 E 新增只读操作，从现有权威库取得原回执。 | 可避免整库复制，但把故障期间的出证请求、限额、问答授权和审计开销加到健康写者；现有 `ReadView` 不是该证明（P1X、P4）。自动周转还需要给具名恢复、修复拒绝态和重试授权定策略，带来重启风暴与无人可处理的碰撞。首版不选。由 E 直接出恢复原件不是 A 的失败分支。 |
| C：显式或控制器请求，但依赖预签域级原回执 | 已取得的原件在启动前转交，不访问健康的对端库。 | 取证便宜，原回执能证明那次恢复曾发生，却不能证明该代现在仍被同一进程使用（P1/P2）。加上同源库当前严格复核和活体校验，就成为 A 的定位件；额外签发、轮换、撤销均没有补足缺证。拒绝单独使用。 |
| D：只隔离，保留整会话有序停启 | 不引入单域重拉和在线依赖切换；沿 ADR 0065 已有启动合同。 | 安全与实装成本最低，仍是整会话运维路径；恢复需要打断健康域，不满足本票和 C09.3 重启局部性验收。不能以 TB-05 已隔离替代本票成功。 |

A、B、C、D 是评审时备选，不是运行时档位。A 的原库证明、活体核对、端点资格和本域准入分别回答不同问题，须同时通过。在位切换拒绝后不自动整会话重启、不改名绕过、不用 manifest 代或旧收据重试。整会话停启只由另一次明确的原合同操作发起。

## 四、确定性合同裁定

### Q1：操作方请求；launcher 装配；本域持锁后才动名字

**1. 成员闭包。** 在线换代只用 Linux 上 ADR 0065 第 3–6 条的原址认领合同：S、E、各 B 和带本地监听的 simulation X 的公开端点须可证在 M 外；并发写域的库、侧件与锁也须通过第 4 条，不改走旧直绑。唯一装配方是本次仍存活的 `production_session`，只按启动时已核的原 manifest/profile、部署映射和相邻同构建二进制组合目标；不换库、不 init 缺库、不重新写 launcher 状态、配置或凭据，不把子集恢复计划当在线命令。控制入口不是域业务 socket：用 launcher 创建且按部署既有权限只交获授权操作方的控制通道。控制方不能提交 argv、路径、新代或任意进程号。launcher 不取域锁、不读 .owner、不 bind、不替域恢复或改库；已授权恢复方仅按各域原正式恢复入口执行。S 用 ADR 0050 的正式有限动作转交（S，68 行；SI 仅为 S 侧取证；launcher 仍须消费前置合同），与本次存活 launcher 的域启动权分开。

**2. 触发与有限状态。** 两个命令均由获准操作方发起，固定绑定本次 launcher、目标域、旧装配实例和操作 ID。控制方不能提交裸代或改动布局。命令以调用意图分派，互不降级。

- `ReplaceExited` 只接续已确证退出且受控后代均已退出的目标。活体返回 `StillLive`，已暂停返回 `Paused`，归属不明或后代未退出各返原拒绝；不写停止管道、不改变目标状态或原址。需要恢复时，由获授权恢复方在这些退出条件成立后走第 5 条原域入口，操作方附原具名请求。没有当前原证就回域首错，不由 launcher 自动恢复。
- `OrderlyReplace` 只接管已知健康、可有序停服的受控实例，**禁止**携恢复请求、禁止升代。在唯一 Child 等待者中，写停止字节前先对目标做 `waitpid(pid, WNOHANG | WUNTRACED)`，结合已收集且未被继续事件取消的状态，并逐一核受控后代的身份及非暂停正常状态。命中 `WIFSTOPPED` 或任一受控后代已暂停就返 `Paused`，**不写** `SUPERVISED_STOP_BYTE`（`0x01`）；已退、未知或不健康也不写。不暂停且门全过才向本目标 stdin 写一次 `0x01`，进入 `Draining`。等真实退出后才同代装配；有序停止的 X 使用同一停止字节。若写后超时，`StopTimeout` 表示 `0x01` 已进入内核管道且不能撤回；目标保持 `Isolated` 等真实退出，不承诺继续服务、不发信号升级、不起第二写者。预检之后才暂停也按此写后状态处理。退出确证后，须另行显式提交 `ReplaceExited`，仍过原有标记/正式恢复门；两命令不会自动转换。

launcher 每域只在内存保留一个操作槽和 Child/等待状态，不新增持久登记簿。成功路径为 `Serving → Draining → AwaitingProof → Starting → Serving` 或 `Isolated → AwaitingProof → Starting → Serving`。本合同只在整批放行且第 5 条初次服役证明已齐后接管受控成员的运行期故障：Child 真实异常退出可自动隔离并撤销依赖就绪，不自动换代；初次装配失败及未启用本合同的部署仍按 ADR 0065 第 11、14 条和第七节处理。显式全停与单域装配不能交错提交：全停到来后不再 spawn，原全停合同收束已有成员；拒绝单域请求不触发全停。在线换代不重启整组、不提交新的批次放行字，也不补造或宣称完成共同 checkpoint；各域照 0065 保留收盘原件、只在因果证据齐备时封口。以后整会话停启仍核共同 checkpoint，不用单域证明越过整组门。

**3. 出证分工与 FD。**

- launcher 在 spawn 时保留 Child 和 Linux pidfd（回收 Child 之前取得）；只依据该 Child 的已回收退出状态和相同 pidfd 的退出信号，不靠数字 PID、心跳、PID 文件、日志、EOF 或客户端超时。缺成员或初始证据不从过去 pid、owner 或残留逆向建档。
- 域实取锁后，从**正在持锁的 FD** 执行 `open("/proc/self/fd/<lock_fd>", O_PATH | O_CLOEXEC)`，`fstat` 核两 FD 的 `(st_dev, st_ino)` 相同，经私有 `SOCK_SEQPACKET` / `SCM_RIGHTS` 向 launcher 交该参照；接收用 `MSG_CMSG_CLOEXEC`。参照是独立 OFD，不经锁路径重开，不续命写者的 flock；`flock`、`read`、`write` 都返 `EBADF`。禁止直接传、dup 持锁 FD。S 按 ADR 0050:71（S） 和原 E5 锁序同时持有、分别钉住并交付 `.writer.lock` 和 `.maintenance.lock`；保留原 uid、类型、链接数及路径重验。
- 换代 spawn 时 launcher 先用同一通道把**上一任**的参照 FD 反向交给下任；下任按原锁序打开已有锁（不新建）、实取 flock 后，第一时间 `fstat` 比对参照和实锁对象（S 两把都比），**先于开库、消费 `clean_close/1` 和任何 ADR 0065 认领/退役**。这是本次 launcher 才持有的追加证据，不替代 0065 第 4 条的 `<db>.writer-lock-id`、锁叶及适用的 owner 锁三元组；S 恢复仍用本库持久端点索引定位并核验 owner。缺、换或错锁立即硬拒并退出：不动库、不消费标记、不改名 socket。不能等新域已认领才比对。launcher 留存上一任参照，直到新证明匹配即续存；已获授权的具名恢复短命域入口也由 launcher 经受控私有通道交同一参照，且须在持锁、首次触及介质之前核验，不能通过先恢复再发现锁被换绕过此门。
- 域的监听、业务 FD、写锁具备关闭和不传递约束：有序停用停止门、排队退出、关闭旧监听及连接、关库、释放写锁；强杀以真实进程退出与内核回收为准。派生链必须在能力传递之前由 launcher 的装配闭包掌握：允许非持权子进程不继承上述 FD（CLOEXEC，及 fork/exec 窗口的关闭约束），可能携带 FD/发送权的实现必须纳入明确、封闭的受控成员集并逐个持有可等待的身份；无法给出闭包的布局不准在线重拉。等待受控后代的真实退出，不能以进程组为空、主 PID 已退或锁可取代替。当前本地 simulation X 无发送子进程；有发送子进程的真实场所另走 C09.8/#1401，不能凭该观察链打开下一任发送门。
- 确认退出只允许准备**同域装配**，不授予名字。目标域实取同一写锁并通过本域启动门后，按 ADR 0065 第 5–6 条认 owner、先核旧退役名和未竟意图；适用退役行才对钉住的旧 socket 非阻塞 connect，仅 `ECONNREFUSED` 可进入持久记意图、移名及复核。新 bind/listen 后按第 5 条用 inode 与 `SO_PEERPIDFD` 证明本次监听器，再持久化 `bound` 并末次重验；消费者活体连接的 `SO_PEERCRED` 核对不替代该证明。按原表处置空址、坏 owner、占用、fsync 或目录重验失败，不改走旧直绑。活/暂停/未知/旧 FD 未收束时不派第二 writer、原名原样；旧锁实取不可得为原 `StaleWriter`，坏 owner 等沿 ADR 0065 的 `TransportUnavailable`，不启第二监听。合法退役完成后若 bind 或持久化失败，保留已完成的退役；未确认的退役不按空址收认，只有第 6 条的移错对象才尝试无覆盖放回。

**4. 重试。** 通过控制权限及会话核验后，先查操作 ID，再核当前目标实例：`ReplaceExited`、`OrderlyReplace` 各自同 ID、同字节只查/等同一结果；命令名也是请求字节，同 ID 换命令或异内容均为 `IdentityConflict`。同一域一项在途，其他 ID 得 `DomainBusy`，不排无限队。对已替换的旧实例给 `StaleIncarnation`，即使裸 PID 或 socket 名被复用。前置不满足需等待事实改变，再显式提交新操作 ID；重放不会补写停机字节；故障场景的具名恢复请求仍重取原 ID、原字节，不因丢启动或恢复回复自动升代。启动中或已激活的回复丢失，使用已在槽的子进程和既有结果，不能再 spawn。launcher 失去控制或重启时，本在线合同结束；不收编孤儿，转原整会话启动/运维边界。

### Q2：新域自证；各来源只按已核原件推进

**5. 目标域启动证明。** 恢复方先通过第 3 条成员边界，不对健康域调用会争域锁的 CLI。E/B 按 ADR 0065 第 9 条，先持锁核代、全域审计并验本代 `clean_close/1`，再认领；单域须 bind 成功、完成 0065 第 5 条监听证明及末次重验后、首个 accept 前才原子消费。整会话另须待批次放行。缺标记直接按 0065 拒绝。未清洁退出、外部备份或不可信版本的 E/B：只用 PR #2082 的原库 `recover-named → current-recovery`，再由目标 `serve` 在同一域锁内重验原请求、正在生效的原回执、持久代与标记，之后才允许认领；在线切换不消费只有裸代的 `recover`。同一具名回执已返回不代表尚有标记，重读旧回执不绕过新故障。正常重开的当前代若已正式恢复过，继续使用已核原回执；无此历史则以本域已审计的创世代/原切面自证，不造恢复收据。

S 不带 SHM 且原 R4/epoch/Begin 门均过时可按原许可代正常重开；崩溃带 SHM 时普通 serve E6 仍先拒，保留原名字与库。获授权方按 ADR 0050 #2128 修订在原锁下核故障前部署登记、独立前沿和活动意图，审计并按该合同收尾介质、过同一 R4、完成 `s-recovery/1`（S，70–92 行）；首版具名恢复仅适用获准的固定 Plan。launcher 预核 `current-recovery`，S 在服役锁内按同一规范请求再核回执，早于推进 pending、bind 或接纳。孤立 SHM、未知介质、旧回执、未处理的 Begin 都按原门拒，不能改名消除症状。带本地监听的 simulation X 沿原 X 锁、持久代、profile、审计和端点门启动，不冒称有 S/E/B 同型的具名恢复 CLI。

目标域只在自身持锁全部启动门成功、原地址已监听、所有指定原始读回可核后，经私有通道给 launcher **本次服务证明**：原会话/代、域、原业务及部署身份、所核本域 writer_epoch、原恢复收据（如有）/创世或干净重开根据、被核的具名 cut/原回执、本次进程身份及第 3 条锁参照。E 另交已审计的创世 cut 与出证时当前 cut、各自的 `image_hash` 和钉住的 E main 文件身份；launcher 保存首次可信原址与创世证据作为本轮参照，后续不覆盖。此证明仅证明本次启动，不能代替原恢复回执。launcher 按 Child/pidfd 和请求关联，原业务提交身份仍按原合同。

采用本合同部署的整会话首启或续服，先走 [ADR 0065「恢复职责分派」](0065-production-session-endpoint-ownership.md#恢复职责分派) 的两阶段门（A，212–218 行）：全员先 spawn 到准备态、持各自原锁重验；收齐后才许可初始化／绑定；待适用的初始共同 checkpoint 落盘、全员完成绑定及末次存活复核后，才原子提交批次放行字。**准备和绑定不等待任何上游服役证明，不接纳业务。** 放行后才按 **S 本次服务证明 → E 本次服务证明（创世/当前 cut、锁参照）→ 各 Bᵢ 自核 E 并交本次服务证明 → X 自核 S/E 并交本次服务证明** 串行接续。B/X 已在本批次内，不再 spawn；未自核的权威方向保持关闭。即使 E 有恢复履历，也须审读 `seq=0` 的真实创世 cut 后再交下游。B 的创世绑定只在第 6 条首次核证通过后、首个依赖业务前持久化；它不是共同初始 checkpoint 的前置，不以准备库填默认绑定，不替换已有链。

**6. A 向：B 换而 E 活。** launcher 经私有装配通道向 B 交同一 E 的已证业务/部署身份、原库身份、选定 cut/当前原件及新 pidfd。**唯一核证是原 E 库的私有、只读一致快照，加原业务 socket 的 `ReadAuthorityHead` 活体挑战。** X 对 E 使用同一核证。

- **原件。** 复用 XI 的介质前后重验及 `verify_current`，沿 PR #2082 的原件和当前代判据。只读钉住原 main/WAL，在部署外私有 `0700/0600` 目录建副本并独立审计，核原库介质身份、业务/部署、持久代、恢复时间、原 cut/root、其 `image_hash` 和具名回执规范字节；不复制 SHM，不在 E 目录重建索引。创世与恢复由已校验的唯一 init 或具名恢复履历区分；创世基于本次装配交付并持久钉住的真实 `seq=0` cut，恢复须在同一验证中证明所交原回执当前有效。不能以缺回执判为创世。
- **预算。** `recovery_snapshot::read(db, deadline, max_bytes, verify)` 新增绝对单调期限和正整数复制字节上限。B 从新版经济业务合同的 `replacement.e_snapshot.{timeout_ms,max_bytes}` 取值（适用两种经济业务信封）；simulation X 从新版 `Profile` / `BusinessProfile` 的 `e_snapshot.{timeout_ms,max_bytes}` 取值。两者在首写时冻结、持久审计；均为必填正整数并检查范围及单位。复制前用受检加法核 main 与 WAL 总字节；分块复制、打开私有 SQLite、审计与前后重验共用同一绝对期限，取建立本次核证的时刻加 `timeout_ms` 与外层已有操作截止（如有）的较早值。限额或稳定性失败直接拒绝，不切换到另一种读法、不阻塞 E 写序列。
- **身份和帧。** 新版经济业务清单为每个 Bᵢ 和所需 simulation X 登记一个专属、冻结的四元组 `source_namespace/source_epoch/producer_id/producer_epoch`，在 E 的 `authorized_sources` 中只许 `ReadAuthorityHead`。新部署清单的 `replacement.e_head_callers` 将成员一一映射至这些条目；消费者从已核装配得到自己的条目并核对冻结配置。该探针四元组不同于普通 B/X 事实生产身份，数值不随 B/X 的 writer_epoch 换代而重写。launcher 向 E 私有通道交实际调用成员的 pidfd 与已核身份（首启 B/X spawn 后、放行其挑战前交付；换 E 时先交仍活的成员）。E 同时核四元组、专属操作权限、连接的 `SO_PEERCRED` 和登记 pidfd 仍活；第三方或另一成员不能借用条目。原普通来源的授权不扩展。
- **挑战。** 仍用 E 业务信封；typed payload 只有 `{op:"ReadAuthorityHead",cut}`，请求必须给具名 E cut（`domain_id,commit_seq,root_hash`）、长度固定的 32 个小写十六进制字符新 `message_id`、空 `causal_refs`。E 在同一当前代只读事务按序号精确匹配根，取持久审计约束的 commit header（现有根和新增持久 `image_hash`；在新版随 commit 原子登记并由原图像审计复算）。成功仅返 `{kind:"EconomicAuthorityHead",business_id,cut,image_hash,writer_epoch}`，其中 `business_id` 是冻结 E 业务清单身份摘要，cut 中带 `root_hash`；不读出或编码整个 `image`。请求、成功回复和拒绝均用封闭字段、固定类型及有界值，完整编码含换行一律 **≤ 4,096 字节**；身份文本及外层信封须在配置准入时证明最坏长度在界内，E 传输帧界及消费者帧界不得小于此值。拒绝用固定错误码，不回显输入。帧长与账本大小无关；同一身份和代，对同一历史 cut 的成功帧等长。本入口不是分页读，不发 `ReadView`，不因失败发 `EconomicReadOpen`。
- **活体核对。** B/X 连接原 E 地址，在发帧前及收答后验证 E pidfd 未退出、`SO_PEERCRED` 的 PID/部署 uid 匹配本次实例；复算规范回复信封、请求因果及 producer 身份。用快照所核业务身份、具名 cut、`root_hash`、`image_hash` 和当前 writer_epoch 逐项对读；允许 E 已有更新 cut，但不以较新切面替代所问历史 cut。裸代、预签件、只读 immutable 主库、`query-recovery` 或抢活 E 锁的旧 CLI 均不作为当前凭据。

B 本地链尾必须与所核证据吻合，或按第 7 条提交唯一的合法下一步。未核证时 B 独立能力可就绪，E 依赖关闭；不得报全会话 Ready。真读 E 业务事实仍逐笔按原域事务核持久代、全审计和原事实，不能拿挑战当业务收据。核证不取 E writer lock 或跨域持有事务。

**7. B 向：E 换而一个或多个 B 活。** 每个 B 在自己的写者和事件序列下持久管理一条 E 来源绑定链 `b-e-authority-binding/1`（首写登记在新的业务合同，不就地升旧库）。当前值不再永久取自 argv；旧参数只用于首建的期望值，不能覆写尾项。链内具名记录会话/代、B 与 E 业务身份、绑定序号及父序号、E 前后代、精确具名 E 恢复原件及本域已接纳事件边界。创世行另固化首次已证 E 的创世 cut（含 `root_hash`）与创世 `image_hash`，每次启动/换绑均核原值；`System` 时钟下初始根来自实际 init，不能用同 manifest 的另一新库替代。进程句柄、路径、端点实例和操作 ID 不入链、不进业务提交根；部署核验单列。源身份、可调用操作及历史业务 schema 不改；只推进 E 的**权威写者代**，不把 E 自身代复制给 B 写者或更改外部来源授权。

1. E 的旧 pidfd 退出（或已观察到暂停、失联而被隔离）即关闭该项新 E 依赖。B 核 E 依赖操作时不得只信异步通知：在本域单序接纳点以同一当前绑定复查 pidfd 未退出、来源未隔离和具名原件。网络回复必须来自绑定的实例；直接读取原库的历史事实还须在该读事务中核当前持久 E 代。没有经过当前身份核对的旧帧、排队未核、部分帧不成责任；未观察到的未来故障不是一次已经接纳的判据。已经过该接纳点的原事务可依原冻结证据结清/查回，若有已持久化的在途责任则按原身份查询或继续既有责任，不以新代制造新命令。切换事务排在此已经接纳的本域事务之后；不能把切换前的活体核证缓存拿来接纳切换后的新请求。语义的切点是本域接纳/提交顺序；旧回复晚到即拒，不让跨域锁去模拟一个全局提交瞬间。
2. 经任何 B 进度无关的原 E 恢复，E 已按第 5 条在原址持锁服务并给证后，launcher 经私有、按成员绑定的控制通道发送 `AdvanceEAuthority` 给每个 B。B 校验自己的成员实例、父绑定、E 的原业务/部署与新 pidfd，再独立执行第 6 条同一 E 当前核证；只接受 `from_epoch=尾项E代` 且 `writer_epoch=from_epoch+1`。同代有序换进程只重验当前证明并替换内存中的活体句柄，**不追加代跃迁**，旧句柄对应的帧同样失效；更换原址本身不推进来源。恢复请求冲突、过代、跳代、错库、缺来源/epoch 或旧帧拒绝，不从现行值覆盖旧链或补造中间记录。
3. B 在本域事务内复核自身 writer_epoch、历史与原件，在此边界原子追加/激活一条绑定，提交后 ACK；同一父/子和完全相同原件重查尾项，只读原 ACK，不新增行。同一转换异内容为 `IdentityConflict`。失败时 E 依赖留闭，B 的 PID、listener、本域代和独立业务不变；恢复后 E 可独立提交，不等待所有 B 的 ACK。对后来进入的 B 也只能沿持久原链做一步；缺连续链保持隔离，交 #2130，不用过期原件当当前。带 E 因果的入口及其回包按新绑定严格核证；包括 N 的 `ApplyAllocation` 纯读路径和 `CommitDecision` 读 E grant proof 的路径，均在取得原件的只读事务核**绑定要求的**当前 E 代，而不是从 proof 自报代反填参数。普通来讯仍照其原消息源鉴权，不以 E 的新代替换事实生产者的原代。
4. 历史读取与活体接纳分开：保留旧源和原信封、原 fact/cut/root、回执及所属绑定、原提交/获知时点。已应用 ID 同内容只读回原回执，异内容冲突；新 E 对历史事实的证明区分当前出证代与历史事实代。未应用、待查或可能已发送的责任保留原 key、旧凭据及最大责任，由原具名协议查询/结清；不得把旧消息做为新来源重新发布。E 回执切换不改首建冻结的来源授权（含第 6 条专属挑战条目），不放宽原 E/B 写和审计门。

仅把新 inode 或新 E 数字传给 B，过不了 B 持续检查的原 E 持久代，且无从区分迟到原件和新接纳；冻结旧代则在 E 已升代时永久拒绝合法依赖。上述显式推进用原证明、更换本地当前绑定并保全旧链，不需要 B 重新启动。N 的既有 B 不具备该协议，不能用配置重载冒充。

**8. C 向：E 或 S 换而 X 活。** simulation X 保持进程、监听、自身 writer_epoch、业务来源和原业务授权。旧权威退出即关闭受影响的新交换，保留历史读和已接纳责任。launcher 私有通道交替换域的当前证明，X 在线逐项核验：

1. 校验私有通道、目标与父绑定、新 pidfd 未退出，以及第 5 条本次服务证明。E 方向依第 6 条做有界快照，核原 E 库和原件，再用**同一个** `ReadAuthorityHead` 挑战，核业务身份、历史 cut、摘要与当前代，校验 `SO_PEERCRED` 和 pidfd。首启及同代换句柄也用同一判据。
2. S 方向使用经 launcher 受信交接、在新 S 原锁内复核的 #2128 具名当前回执；没有升代史的原实例用已证创世身份，同代重开仍重验对应根据。X 向当前实例的 S 业务地址发送 `s-session/3` 信封（payload 为 `{"op":"ready"}`），发帧前和收答后核 `SO_PEERCRED` 和 pidfd。成功采用真实 `kind="Ready"` / `ok=true`，核 `schema_revision`、`session_id`、`session_generation`、`writer_epoch`、`profile_id`、`profile_hash`、`clock_plan_hash` 与冻结 S 身份及交接证据相符，重算 `s-session/replies`、`S:<session>` 和因果信封。现有头另含 `advance_state`、`generation`、`structure_cut`、`index_frontier`、`delivery_frontier`；它们读的是当前态，不拿它们替代/重算恢复切面。本合同准入校验有界头及其信封可容入双方帧界。X 不打开活 S SQLite。
3. X 在原写者循环复查父尾、活体和原件引用，按 [ADR 0073](https://github.com/Newchanlun/NewChanlun/blob/032a99603d44fe2f0acca56bd66d7830d8d0c8d1/docs/adr/0073-simulation-x-recovery-authority-binding.md#L32-L64) 复用 `x-authority-binding/1`：单次只推进该分量一步，事务提交后 ACK；同代有序重开只换活体句柄。各通知在同一通道串行，同时可交付时先 E 后 S；同批双域冷启动仍按 0073 原顺序。每次后续权威连接发帧前及收答后核本次 peer 等于当前绑定实例、pidfd 未退出，并在单序接纳点再核该连接证明/父尾；旧实例的帧即使同代也不接纳。
4. X 的业务交换保留 `QueryReleasedExact`、`RequestConditionalExecution`、`QueryExecuteCommitted` 的原用途。后两者不是原 S3 的 `ready`/ `receipt`/ `ingest`；若 X 声明该依赖，可在线的部署须把 simulation 执行权威处理器接到同一个持锁 S 实例，在原 S socket 上用 `s-session/3` 信封分派，并由 S 出具端点及能力证明。业务正文按 [ADR 0038 #2127 修订](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L162-L174) 与 ADR 0073 第 7 条核 `x-exact-authority/2` 的当前应答及原交付／提交证据；旧 `/1` 保留其原会话合同，只作本票的实现取证，不是在线降级路径。只向冻结 profile 中获准 simulation X 的受控实例开放，S 核来源身份与 launcher 交付的 peer/pidfd；不开放真实发送。只会返回 `ready` 的 S 或另一个进程的代理不能通过该业务方向，不承认假 fixture 可达为实服。X 不消费 B 绑定链，不借新 S/X 代修改 E 的业务来源授权。

切换后新交换只走当前绑定，旧帧不准作为新的成功。旧 `Accepted` 在持久证据确认未请求时，仅在原命令仍完整通过当前资格时能第一次发送；`ExecutionRequested` 等可能已发送，只能向当前权威具名查原尝试及其原绑定，查不到保留 pending 和最大责任；`ExecutionReady` 保留原资格，只能为原批首次取得调用占有；`MayHaveCalled` 只按原批和已有占有继续本地幂等处理或读回，不二次占有、不补发；`Observed` 只查原件。X 本域确需替换时走原库、原 profile 和原本域排他启动；如另有 E/S 绑定变化仍逐条核 0073，缺原库或历史不能新建。XI 候选的 `--authority-rebind` 只适用冷启动；在线在原 X 写者中增加控制交付，不新起第二 X 作重绑代理。

**8a. D 向：S 换而带 finance 的 E/B 活。** 仅启用 finance 的 E 和各 B 在各自原库首写 `economic-s-authority-binding/1`。创世行冻结 `manifest["finance"]["structure"]` 中初始 `writer_epoch` 及 S 会话/代、域、profile/规则与构建身份（业务、部署分开核）。链行记录序号/父序号、S 前后代、#2128 具名原回执的规范字节及本域接纳边界；进程句柄仅在内存，不进入历史业务事实。旧 manifest 代只用来建创世，不再当新财务请求的预期代。

- S 已经 #2128 正式升代，并按第 5 条以有效代在原址持锁服务后，launcher 经各 E/B 成员私有 `SOCK_SEQPACKET` 发送 `AdvanceSAuthority`，附具名当前回执、本次服务证明和新 S pidfd。消费者独立核 #2128 会话、S 身份、请求/回执、前后代、原历史切面与本次持锁证明的一致性，走第 8 条同一 S `ready` 活体验证；不打开活 S SQLite。关闭该方向新接纳直至本地绑定完成。与 X 相同，同代有序重开重核同一根据后只换内存句柄，旧连接失效，不追加跃迁。
- E 的 `Reserve`/ `SourcePins`、每个 B 的 `PrepareDecision` / `CommitDecision` / `SourcePins` 与控制消息共用各自单写序列。核证后的短事务复查本域有效写者、新 S 活体及父尾，仅准 `from_epoch=尾项 S 代`、`writer_epoch=from_epoch+1` 的当前原回执，原子追加/激活并在提交后 ACK。丢 ACK 用同转换、同原件重查尾项只回原 ACK，异内容 `IdentityConflict`；跳代、少原件、换 S 身份、过期证明均拒。不等待所有消费方 ACK 才让 S 独立服务。
- 新财务读取从本域已提交的**当前绑定**构造 S 预期，不从来帧自报代反填。`verify_structure` 以及 `financial_content::read_once` 的请求、回复头、内容 proof/闭包的 anchor 共用这一个预期。在线版在冻结的 S 业务 socket 走 `s-session/3` 信封，由该持锁 S 实例复用原财务读判据；仅对按冻结业务/部署登记的 finance 消费方开放，S 逐连接核来源和 launcher 托管的 peer/pidfd，保留原期限及请求、字节、内容资源门。旧式 finance 语义的新版本用 S owner 的 `financial-basis` 读；内容版使用 S owner 的 `financial-basis-ref` 和 `financial-closure`，不逐片冷读。二者按冻结业务版本分派，均是**需纳入 S 正式 serve 的接缝**，不是已有 S3 公共 op；读在现有 S owner 内受原准入、计量与审计约束，不能开第二个 S SQLite 连接、启动冷读 CLI 或让旁路代理出证。每个连接发帧前、收答后核 `SO_PEERCRED`、pidfd；每次财务接纳/写事务内复核当前尾项与同一活体。失败只封 S 依赖，不回旧代/裸代、不换读法。
- 新的财务事实/收据关联接纳时的 S 绑定序号；随后历史审计和具名读回沿该行核原证据头和内容，不以当前代重写过去。切换前已接纳的责任按原证据结清；未获接纳和延迟旧帧不能当作新财务事实。S/E/B 之外不增持久权威写者，不改 S、E 或 B 的业务来源身份。

### Q3：增量按域落地；本域可用不等于全会话 Ready

**9. 协议清单。** 控制输入用 launcher 单独持有的、在启动时交付给既有获准操作方的 Unix 控制 FD；每个域另用 launcher 随 spawn 交付的私有 Unix `SOCK_SEQPACKET` 通道。句柄随消息以 `SCM_RIGHTS` 交给指定成员，不在 argv、日志或业务 socket 暴露。未知消息版本、越界消息或成员/token 不符即拒。原停止字节和普通业务信封保留；新 typed 操作单独列下。

| 域 | 足够的现有机制 | 本票唯一需要的增量 |
|---|---|---|
| launcher | 同构建 sibling、manifest/profile/layout、Child、原恢复计划；0065 整批放行 | 放行后的串行权威接续；`ReplaceExited` / `OrderlyReplace` 及独立重放；保存进程与 `O_PATH` 参照、换代前反向交付；检查域证明、托管头客户端身份、定向交 `AdvanceEAuthority` / `AdvanceSAuthority` 或同代句柄及 ACK；不持锁、不写库。 |
| S | 原 E5 双锁、R4、#2128 具名回执和 serve 复核、`s-session/3` 的 `ready`/具名读口 | 双锁 `O_PATH` 前置比较及回交、私有服务证明。受启用子合同约束，同一 S owner 正式承接第 8/8a 条所需 simulation 与财务业务操作，证明 endpoint/能力和原准入计量；`ready` 本身不增字段，不复制活 S 介质。 |
| E | 持锁 serve、#2082 原库具名恢复、0065 标记及端点 | 持锁重验及证明（含创世/当前切面、原库与锁参照）；新版业务/部署合同登记 B/X 只读主体与 `authorized_sources` 专属 `ReadAuthorityHead`、有界编解码及持久 commit header；带 finance 时持久 S 绑定、`AdvanceSAuthority`、同代句柄和 ACK。 |
| 各 B | 本域独立持锁、E 原事实核验、本地收据及幂等、#2082 本域恢复 | 锁参照/启动证明；使用自有专属主体挑战 E；冻结 `replacement.e_snapshot.{timeout_ms,max_bytes}` 并调用有界 `recovery_snapshot::read`；钉 E 创世 cut、持久 `b-e-authority-binding/1`、`AdvanceEAuthority` 及 ACK；带 finance 时加第 8a 条 S 方向及 ACK。 |
| 本地 simulation X | 原 X 锁/审计/持久 profile；0073 绑定、历史与 E 快照；原命令查询 | 锁参照、停止/成员闭包和服务证明；新版 `Profile` / `BusinessProfile` 冻结 `e_snapshot.{timeout_ms,max_bytes}`；专属 E 主体、在线 E/S 交接和同代句柄、单序绑定与 ACK；每次权威连接核同一实例，不新增 X 公开业务操作。 |
| 无本地监听的 X | 原 profile、原场所发送门、C09.8/#1401 | 无本地端点认领或真实发送增量；本票既不重拉场所 X，也不把其已验证不可用当成 Ready。 |

各消费方等待对端或准备私有证明时，仅关闭受影响方向。耗时读证在有界工作单元完成，不跨域持事务或停止独立处理；回到本域单写序列再复核父尾、控制成员与活体句柄，短事务提交。过期证明拒绝，不拿时钟或旧 ACK 继续放行。

首写/审计核新版业务、部署及 profile 的冻结字段和对应持久版本；不以启动参数或配置热改给旧库补记。旧版 E/B（含原 `economic-session/1` B 和现行版）/X 缺头操作、专属身份、快照预算、锁参照或已启用方向能力时，在在线操作准入即拒；同样拒缺单域服役证明、已启用的 S 正式财务/执行能力或绑定协议的部署。不加默认预算、兼容开关或读法换档。原版本仍走 ADR 0065 既有启动与原恢复合同，不让 recover/serve 就地重写历史。

**10. 状态判据。**

- **单域恢复可用**当且仅当：新目标确属本轮同一原布局、原库及原写锁谱系；原启动门和接纳前动作全成功；原名上的本次实现完成有效具名读回（恢复前已提交的 cut/收据或操作指定的原状态，结果按原协议逐字节核对）；本域当前写者证明与实际进程一致，且可在本地独立接受合法下一次提交。目标原本依赖 E/S 的方向，只有本地绑定证明和复核完成后才各自可用。仅 spawn、listen、owner 更新、恢复 CLI 零退出、pidfd 存活或日志均不足。生产状态不得为凑就绪伪造业务写；有获准输入时实际下一次提交是验收证据。
- **全会话 Ready**当且仅当：本轮既有 manifest/profile 所需的 S、E、所有 B 及所需 X，均有当前活体、无隔离、持有各自有效写服务资格、通过指定原库具名读回，并能独立接受合法的下一次提交；所有必需权威方向均已由实际消费方确认到同一当前提供方的合法绑定：各 B→E，所需 X→E/S，带 finance 时 E→S 和每个启用 finance 的 B→S。当前实例的 ACK 齐备才算该方向就绪；未回 ACK、历史链未补齐、依赖尚未恢复或无任何本域能力证据时，报分域 `Degraded`（列缺的域和边），不报全局 Ready。受影响方向在活体失效时立刻撤销自身能力，不能持续展示旧 Ready。待定原责任按既有规则受保护，留存本身不等于服务失效；但不能核证正在使用的原件/绑定时仍不 Ready。launcher 对同一批当下实例和 ACK 求交发布 Ready，随后发现实例或证明失效即撤销；Ready 不是对未来存活的承诺。
- **安全边界。** 不新增真实发单、撤单、补发、资金/账户权限、目录属主或凭据操作。没有独立真实授权不杀孤儿、不改宿主权限；已有真实 X 的指纹、能力和发送子进程隔离条件不变。目录整改、拒绝态清场和缺失历史依 #2130；无确认就保留。有序停止请求只写本轮受控目标的现有停止通道，不把失联转换成杀进程的许可。

## 五、角色、状态及失败矩阵

表内「健康域保持」指 PID、原 listener（如有）、本域 writer_epoch 不变，且可真正独立提交；E/S 的失效方向只暂停依赖操作。域的拒绝文本保留既有门，表中的控制错误是本次 launcher/本地切换状态，不覆盖原域首错。

| 场景 | 触发方 | 出证方 | 交付方 | 健康域不变式 | 失败或拒绝 | 观测证据 |
|---|---|---|---|---|---|---|
| 有序停止一个已知、响应的 S/E/B/本地 X | 操作方 `OrderlyReplace` | 写前核目标及后代非暂停；真实退出；新域锁、原准入和具名读回 | launcher 写一次停止字节，确认退出后同代 spawn；新域持锁认领 | 健康域保持；依赖方仅换活体句柄 | `Paused` 无写；写后 `StopTimeout` 隔离至真实退出，不升级信号或自动改命令；缺标记拒绝 | P3、P6；AT1、AT3 |
| 崩溃 S | launcher 观察隔离；操作方 `ReplaceExited` | 旧 Child 及双锁参照；S #2128、原锁内当前回执与活体 | S 先独立服役；launcher 交 X，启用 finance 时分别向 E/各 B 交 `AdvanceSAuthority`；各消费方自核并 ACK | E、B、X 保持；依赖暂闭，财务读随后只认新 S，历史按原绑定 | 旧 FD 拒；SHM/Begin/坏锚沿 R4 原首错；部分 ACK、旧 S 帧、跳代或回执冲突不放行相关方向及 Ready | P3、P5、P7；AT2、AT4、AT6、AT7、AT9 |
| 崩溃某个 B，E 健康 | launcher 隔离，操作方请求 | 旧 B 退出及 B 原库当前回执/标记；B 独立核真 E 与 E 原件 | 授权方恢复 B；launcher 单拉；新 B 自取锁、续原址 | E 不停、不让锁；S、其他 B/X 保持 | 缺 B 标记/过时收据拒绝；E 证据缺只封 E 依赖；不调 E 锁内 CLI | P1、P1X、P4；AT2、AT5 |
| 崩溃 E，多个 B 与 X 活 | launcher 隔离，操作方请求 | 旧 E 退出与 E 原库当前回执；Bᵢ/X 各核新代及原链 | 新 E 先独立交付；launcher 定向传证；各 B/X 事务 ACK | 所有健康域保持；B 只关闭 E 方向 | 过时/裸代/跳代/异库不激活；旧帧拒；个别 ACK 缺不拦 E，不报 Ready | P2、P1X；AT2、AT6、AT7、AT9 |
| 崩溃本地 simulation X | launcher 隔离，操作方请求 | Child 及受控后代退出；本域锁、profile、原指令及在途档 | 只新拉 X，X 自核原库并认领 | S/E/B 保持 | FD 未清、原库/档缺或不能核旧发送状态均隔离；不重发 | P3；AT2、AT7 |
| 旧实例活、SIGSTOP、失联、写后超时，或未知归属/后代 | 操作方显式选命令 | 未满足退出、暂停检查或子代闭包 | 无新域装配 | 写前拒绝不动目标、原址/owner；只有写后超时的目标保持隔离等退出 | `ReplaceExited` 活体 `StillLive`，已暂停 `Paused`；`OrderlyReplace` 暂停不写，写后 `StopTimeout` 不许声称继续服务。未知/旧 FD 按首错拒，即便锁空且试连拒绝 | P3、P6；AT3 |
| 原锁不可取、锁对象更换、已验退出但残留仍占用，或坏 owner | 操作方请求 | 本域实取同锁、原 owner 与钉住 socket | 拒绝于域门，不接纳 | 保持健康域 | 等锁不成立；对象异常/坏 owner 按 0065 拒，原对象保留；不回退直绑 | P3、P7；AT3、AT4 |
| 同域并发、重复触发、丢回包、旧操作 | 操作方重送原请求 | launcher 操作槽、原域恢复事务、各消费方本地绑定尾 | 只返回已在途或已落地的原结果 | 保持健康域 | 异内容冲突，异 ID 在途忙，旧实例拒；新故障要重新核前件 | P2；AT8 |
| 介质、标记或原件不明，旧合同进程或 launcher 已失去 | 操作方仅按各自原合同处理 | 缺在线装配/本域门证据 | 不在线接管 | 不动幸存者/孤儿 | 留 `Isolated`/拒绝；按 #2130 运维或另启既有全停路径，不报告 Ready | 0065 / 0050 负控；AT4、AT9 |
| 无本地监听的 X 或外部发送身份未证 | 仅原获准外部流程 | #1401/C09.8 原证、原 profile | 本票无发送或新真实进程 | 其他健康域保持 | 不进入本地端点流程；不增加发送、不杀旧发送者或孤儿 | AT7、AT9 |

## 六、下游实施片的具名验收测试合同

在 Linux 的 `rust/tests/production_session_entry.rs` 用正式 launcher 真进程、同一原 manifest 字节、原库 inode 及 M 外原地址交付。每个臂用独立的测试工作目录；同步点只进测试夹具。CI 的 `rust-test-production-session` 必须逐名给出结果（M，`.github/workflows/ci.yml` 811、830–841 行）。下列编号不是已跑测试，P1–P7 是第二区分方案的证据。按 #2127 留住时钟、根、证据来源和同轨迹记录，不因恢复抹掉不同代字段。

| 编号／测试 | 充足证据 |
|---|---|
| AT1 `replace_one_clean_same_epoch` | 分别对健康 S/E/B/本地 X 发 `OrderlyReplace`，写前核非暂停、停机成功后同代重开；launcher 相同，只有目标 PID/listener 变，E/B 关库标记持锁先有后消费。恢复字段提交即拒，不写停止字节；原 cut/收据、健康 PID/端点/代不变，目标及健康域各有下一笔合法提交。E/S 同代只换依赖句柄，旧实例帧不放行。 |
| AT2 `replace_one_crash_same_address` | 分别对真实 S/E/B/本地 X 在业务提交前后、回报/应用边界断开，确认真实退出后 `ReplaceExited`。正式恢复才升一次代；其余域不重启、不换库、不 init，退役对象核原 ino，新 listener 在原址。旧请求不复活，具名原结果逐字节回读，各域实际完成下一合法提交。S 臂用获准固定 Plan 并启用 finance：同 PID 的 E/多个 B 消费 S #2128 原件，经各自绑定推进后实际完成 `Reserve`、`PrepareDecision`、`CommitDecision`；原财务事实按旧切面验证。 |
| AT3 `replace_one_refuses_live_unknown_or_old_fd` | `ReplaceExited` 对活/SIGSTOP 各返 `StillLive`/`Paused`，不写且不改目标；`OrderlyReplace` 对已暂停目标或后代拒 `Paused` 并证明管道未写，`SIGCONT` 后同 PID/socket 应答。写后超时另臂证明只写一次且目标隔离等待退出、无升级信号/重拉，不要求能应答。未知、旧 FD（含仅 bind）、无退出证据、锁空与试连拒绝同现仍拒。实取错锁（含 S 任一锁错）、坏 owner、活 socket 或 M 布局错均拒；在开库及认领前验证反向 `O_PATH` 比对，不消费标记、不改端点、无新监听或第二 writer。 |
| AT4 `replace_one_checks_own_recovery_and_sidecars` | E/B 缺/坏/错代 `clean_close/1` 或未正式恢复，S 带 SHM、非法 WAL、坏锚或未决 Begin 均按原门拒；原库/端点未替换，S 真 #2128 合规恢复并校验两个原锁参照才准再绑。两锁逐把检测持锁后、开库和介质处置前缺/换/错参照；对照误传原 FD 会续命写锁与传 `O_PATH` 后立即可重新取锁。另核原回执重取、旧回执/请求拒、预核与 serve 复查竞态，用 0065 整会话旧直绑对照臂确认标记门不得绕过，在线换代的认领失败不得转入该臂。 |
| AT5 `replace_b_reads_current_e_without_e_lock` | 创世及活动 WAL 升代臂保 E PID/端点/持锁、E 真新提交，直接 `current-recovery` 锁拒；新 B 先核有界私有快照、凭专属主体用同一头挑战精确核大 image 的历史 cut，再在 B 原库提交真依赖操作。拒未登记/冒名、错 peer、陈旧收据、同 manifest 另 init、仅 immutable 旧库、超时间/总字节或不稳快照；强制头挑战失败并确认不发 `ReadView` / `EconomicReadOpen`，专属授权不增加其他读写能力。首启单独验证：全员可先准备、放行前不接纳也不消费 E/B 标记；放行后未核上游证明的下游不得执行权威交换，核证后同一批次下游可接续，无第二次 spawn。 |
| AT6 `replace_e_advances_live_b_source` | E 臂中至少两个活 B 保持本域 writer/端点，已接纳与未接纳分开；退出、切换前后注入旧帧、错误 E 原件与错 peer，仅新绑定一次，真 E 依赖成功、历史不改。同代 E 仅换句柄。S/finance 对照臂向 E/多个活 B 发真 `AdvanceSAuthority`，带在途操作，验证两种财务版本按尾项单步接纳新 S、拒旧 S/跳代及异内容，历史证据仍按旧绑定核；同代重开仅换活体，旧 peer 不放行。 |
| AT7 `replace_e_or_s_rebinds_live_x_without_resend` | 分别真换 E/S，另测同代重开；原 X PID、端点、自身代、X 事实来源及 E 原业务授权不变，私有快照不动 E 部署，只动相应分量。E 用同一头/S 用实际 `ready` 核活体，随后真权威交换再查 peer/pidfd；错 peer、旧帧或只会 `ready` 的 S 不可用。覆盖 Accepted、可能已发送/丢回包、ExecutionReady、MayHaveCalled、Observed；资格/占有/发送不重复，未知最大责任不降。另打断本地 X；非监听 profile 不进本地重拉，无真实场所发送。 |
| AT8 `replace_one_retry_and_competing_requests` | 两命令各测不同 ID 并发、重复同 ID、同 ID 换命令/异内容、迟到旧实例；重复不会再写停止字节或 spawn。分别在具名恢复/启动、各消费方绑定提交后丢回包，查回原字节；代、行、进程不重复，提交前中断可按原请求语义重试。 |
| AT9 `replace_one_requires_real_session_ready` | 真依赖失败、部分 B→E、带 finance 时部分 E/B→S ACK 未交、旧 S 帧、X 原件或真实 S 业务能力缺失、旧部署缺头/主体/预算、已 bind 未证读回、健康域提交失败和 launcher 消失均非 Ready。只有实际恢复所有必需边、原库具名读回及每域独立提交后才报 Ready。整会话重启、新路径、手改库/裸代、TB-05 只隔离、假 PID 均不能做正控。 |

## 七、受影响代码及票据边

### 固定取证版本

下表的短名只作本文件行号的版本前缀；每条均按对应提交的 blob 核对。

| 短名 | 提交 | 用途 |
|---|---|---|
| A | `855cf58a42919bf904b06e000682b71a64feabc0` | 本稿叠栈基线（PR #2139）：ADR 0065、0039 含 #2079 附记、0059、0041。 |
| M | `0e29d008f766a82a05898244caf5a30924f24b51` | A 已包含的 `origin/main`，用于核现役源码和 CI；与 N、PI、SI、XI 的候选代码行号不混用。 |
| D | `70e90c8a72e09f32135fded556e4165fba9ae1d6` | [R5 简报](https://github.com/Newchanlun/NewChanlun/blob/70e90c8a72e09f32135fded556e4165fba9ae1d6/.chanlun/review-results/issue2079-design-r5/DESIGN.md#L5-L14)，是设计来历，冲突处依 A。 |
| N | `329be34f5a9ca9c2bcc38ae75783304cc654904c` | PR #2082 具名 E/B 恢复及 launcher 取证基线，不是 M 的现役行为。 |
| P / PI | `e9b12ef9eeff26cab51e295826a11c871e189ac7` / `3c3da289ea7882f0d58c1eea6385101f87f24d21` | [ADR 0038 #2127 修订](https://github.com/Newchanlun/NewChanlun/blob/e9b12ef9eeff26cab51e295826a11c871e189ac7/docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md#L142-L274)与路径无关实现取证片。 |
| S / SI | `be40eb8a5d7256f017b103bf644fa22ec82e3993` / `e661118f24b5685b3018d7539e645bc5f928e3e3` | [ADR 0050 #2128 修订](https://github.com/Newchanlun/NewChanlun/blob/be40eb8a5d7256f017b103bf644fa22ec82e3993/docs/adr/0050-s-resource-admission-contract-v1.md#L62-L99)与 S 具名恢复实现取证片。 |
| X / XI | `032a99603d44fe2f0acca56bd66d7830d8d0c8d1` / `b276e3f400c3c09f51793ec9cfcf4adde647274f` | ADR 0073、[X 绑定与原 E 回执复核](https://github.com/Newchanlun/NewChanlun/blob/b276e3f400c3c09f51793ec9cfcf4adde647274f/rust/src/history_simulation/authority_binding.rs#L434-L485)。 |

### 受影响接缝

- **正式装配和进程**：M 的 `rust/src/bin/production_session.rs:276–320,322–367,370–448` 是现役 init、Child 监督及拉起接缝；其中 435–436 冻结 B `--e-epoch`。N 同文件 `:249–342` 是具名计划原成员全集及当前核验，`:344–382,429–501` 是 Child、总 failure 与停机，`:504–594` 是 spawn（583 仍冻结 B `--e-epoch`）；两者均无两阶段或放行后的服务证明门。保留初始失败的原回收责任。N 的端点锁、超帧断连、监听/停机及 join：`rust/src/session_transport.rs:42–81,597–600,679–696,702–810,721–728`；共同回复信封见 `rust/src/session_protocol.rs:618–643`。
- **E/B 本域恢复、头协议与授权**（N）：`rust/src/bin/e_economic_session.rs:1–7`、`rust/src/bin/b_chong_session.rs:1–7`；`rust/src/economic_session/service.rs:905–960,995–1058,1314–1329,1414–1433,1484–1511,1521–1568,1556–1566,1570–1636`（固定 E 介质/代、审计、查回先于新读、单帧全 image、业务授权与路由）；`rust/src/economic_session/store.rs:72,114–123,355–395,659–680,1694–1743`（commit schema、配置、授权、切面/摘要与恢复）；[`recovery.rs:28–78,81–154`](https://github.com/Newchanlun/NewChanlun/blob/329be34f5a9ca9c2bcc38ae75783304cc654904c/rust/src/economic_session/recovery.rs#L28-L154)（原件和同一当前核验）。PI 的 [`deployment.rs:84–91,105–165,205–250`](https://github.com/Newchanlun/NewChanlun/blob/3c3da289ea7882f0d58c1eea6385101f87f24d21/rust/src/economic_session/deployment.rs#L84-L250) 是业务/部署闭集及新版成员主体/预算的配置接缝。
- **E/B 财务与历史**（N）：`rust/src/economic_session/finance.rs:283,819–855,957–997,998–1043,1938–1976,2030–2071,2072–2122,2123–2147,2347–2407`（原 S 冻结代、E/B proof、财务入口及 `QueryReleasedExact`）；`rust/src/economic_session/financial_content.rs:314–359,334–341,531–610,759–790`（`SourcePins`、当前与持久证据核验），PI 的 `rust/src/economic_session/finance.rs:1099–1107` 仍核冻结代。把当前 S 尾项/实例贯通读取与接纳；历史审计改按归属行。原事实、回执和具名读语义不变。
- **S 双锁、介质、回执与原服务**（S，ADR 0050:70–72、87–92；SI 为候选代码）：`rust/src/bin/s_session_v3/admission.rs:15–115,112–119,418–431`；`rust/src/bin/s_session_v3/writer_cli.rs:446–468,610–658,906–923,998–1023,1025–1055`；[`named_recovery.rs:17–33,54–114,121–188,324–413,486–518`](https://github.com/Newchanlun/NewChanlun/blob/e661118f24b5685b3018d7539e645bc5f928e3e3/rust/src/bin/s_session_v3/named_recovery.rs#L17-L518)；`rust/src/bin/s_session_v3/driver.rs:8–37`、`rust/src/bin/s_session_v3/audit_owner.rs:1182–1214`、`rust/src/bin/s_session_v2/mod.rs:3495–3508`（SI 的 `ready` 字段）；M 的真实 `ready` 见同文件 `:2882–2898`，分派见 `rust/src/bin/s_session_v3/driver.rs:8–37`。财务只读内核接缝：`rust/src/bin/s_session_v3/financial_reader.rs:152–183`、`rust/src/bin/s_session_v3/financial_session.rs:1124–1160`；把需要的服务接到同一持锁 owner，不借旧冷读入口。
- **E 的一致私有快照和 simulation X**（XI）：[`recovery_snapshot.rs:60–90,98–157,164–202,242–269`](https://github.com/Newchanlun/NewChanlun/blob/b276e3f400c3c09f51793ec9cfcf4adde647274f/rust/src/economic_session/recovery_snapshot.rs#L60-L269)（钉介质、私有副本、前后重验、测试；在这里加期限/总量）；[`recovery.rs:166–196`](https://github.com/Newchanlun/NewChanlun/blob/b276e3f400c3c09f51793ec9cfcf4adde647274f/rust/src/economic_session/recovery.rs#L166-L196)（同一当前收据判据）；`rust/src/bin/x_execution_session.rs:206–232,243–278`（X 锁、冷重绑与非监听发送门）；[`authority_binding.rs:426–485`](https://github.com/Newchanlun/NewChanlun/blob/b276e3f400c3c09f51793ec9cfcf4adde647274f/rust/src/history_simulation/authority_binding.rs#L426-L485) 与 `rust/src/history_simulation/runtime.rs:25–27,78–92,121–135,189–247,319–355,899–949,952–1020,1611–1694`（profile 缺预算、权威连接与信封、持久绑定、冻住的服务循环及原件读口）；`rust/tests/history_simulation_entry.py:454–475,704–765,807–850` 的 fixture 不能出正式 S 执行资格证明。
- **路径无关、原档读取**（PI）：`rust/src/economic_session/store.rs:144–212,345–389,745–766,1099–1131,1839–1876`（业务/部署两身份、域定位、持久审计、根与代）；[`recovery.rs:28–78,81–154`](https://github.com/Newchanlun/NewChanlun/blob/3c3da289ea7882f0d58c1eea6385101f87f24d21/rust/src/economic_session/recovery.rs#L28-L154)（同 E/B 具名契约适应业务版本）；[`session_business_id.rs:29–85`](https://github.com/Newchanlun/NewChanlun/blob/3c3da289ea7882f0d58c1eea6385101f87f24d21/rust/src/session_business_id.rs#L29-L85)（保留业务名和参考值的语法）；测试接缝为 M 的 `rust/tests/production_session_entry.rs:391–439,474–540`。

### 票与 blocking 边

- 保留 **#2079 → #2120**、#2120 挂 #1363；保留 **#1376 → #1396 → #1409 → #1417 → #1423 → #1411**；不关闭 #1363 或 #1411，不改任何 TB-05 逐域真实中断或 #1411 整会话恢复门。
- #2127、#2128、#2129 各自已有对 #1411 的阻塞关系不动；PR #2077/#2082 实施基线与 #2130 运维拒绝出口依 ADR 0065。P、S、X 是同辈待合入的裁定引用，N、PI、SI、XI 的代码只定位接缝；下游按实际合入的正本和实现复核，不把候选或历史探针当现役能力。引用这些接缝不是新增本票对现有 #1411 或 #1363 的阻塞边。
- 未来由 **#2120 → 专门的 launcher 存活单域原址实施片** 接本 ADR；只承接在线控制、单域启动证明、活 E/B/X 的本域绑定推进、所需权威接缝和第六节实测。原最大责任、#1401 权限/真实 X 送单隔离和 #1323 Destination / #1340 验收范围照旧；这条实施片不能用 #1411 的全停成功销项。
