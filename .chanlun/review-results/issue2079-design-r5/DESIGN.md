# #2079 第五稿方向：端点名归本域写者锁持有者，退役只移不删

目标：裁定「正常关停或崩溃后谁可再次提供原会话端点」，让 #1411 在其验收必经情形上没有设计选择。底稿取设计 A（写者锁＋owner 文件＋E/B 库内标记），嫁接 B 的「产品零删除」与 E/B 库部分缺失拒绝、C 的「列内失败不换路」。

## 一、改掉的前提

前四稿都假定：必须有域外第三方证明前代已退出并掌管名字，证据放在域外记录链上。代码否定了它：S/E/B/X 在整个服务期都持有 `<db>.writer.lock` 的内核 flock（`session_transport.rs:57-81`、`service.rs:1584`、`x_execution_session.rs:205`、`s_session_v3/admission.rs:19-48`），取得这把锁本身就是前代已死的证明；上次是否干净关库由域写在自己库里。于是没有模式、监督器、登记簿，也就没有「首次受管启动」。A 原稿「核 inode 后按名 unlink」正是 #2079 票面写明「已被非作者否决」的做法，本方向改为：把残留移到退役名，再核被移走的那个对象，不符就放回；产品从不删除 socket。SAFE-RACE 按原文字面成立，不需要第二个 UID。

## 二、规则

1. 归属。域 D（S、E、各 B、simulation X）的端点名 k 只归 D 的写者锁持有者。只有它在 k 上 bind、把 k 上的残留改到退役名。launcher、调用者、其他域、客户端不建、不移、不删。先持锁后 bind，监听 FD 关闭后才放锁。
2. 前代已退出的证据只有两样，都出自内核：本进程取得该锁；对钉住的残留对象非阻塞 connect 得 ECONNREFUSED。取不到锁按原文 `StaleWriter：<域>独占进程锁不可得` 退出。PID、boot ID、时间、日志、launcher 事件都不是证据；不等待、不终止任何进程。
3. 适用前提，域每次启动自核，任一不成立即旧合同（k 上有对象就按 main 首错拒绝，k 上无对象就照 main 直接 bind；不建 owner、不移动）：(a) Linux，且 openat2(RESOLVE_NO_SYMLINKS)、renameat2(RENAME_NOREPLACE)、O_PATH、/proc/self/fd 可用；(b) k 为绝对路径、无 `.` `..`，parent(k) 以 openat2 无符号链接打开为目录 FD `d`；(c) fstat(d) 属主为 euid，组与其他无写位；(d) 仅 S：canon(parent(k)) 不命中 ADR 0059 第 4 条三款。此后判定与动作一律相对 d（fstatat、openat、renameat2；bind 用 `/proc/self/fd/<d>/<basename>`）。
4. owner 文件 `d/<basename>.owner`，0600，规范 JSON 四字段：schema=`endpoint-owner/1`、socket=k、writer_lock=本进程所持锁的绝对路径、bound=null 或 {dev,ino,ctime_ns}。只由持锁域写：首建 O_CREAT|O_EXCL|O_NOFOLLOW，之后经 `<basename>.owner.tmp` 写入、fsync、rename、fsync(d)；产品不删它。「属于我」＝普通文件、nlink=1、属主 euid、严格解析、前三字段逐字节相符。bound=null 表示本锁谱系处在 bind 与记身份之间。
5. 判定表。位置：持锁且本域全部既有准入门通过之后、bind 之前。

| owner | k | 动作 |
|---|---|---|
| 无 | 无 | 写 owner(null)→bind→fsync(d)→写 bound |
| 我，null | 无 | bind→fsync(d)→写 bound |
| 我，有身份 | 无 | 写 null→bind→fsync(d)→写 bound |
| 我，有身份 | 有 | 按身份退役（第 6 条）→写 null→bind→同上 |
| 我，null | 有 | 按连续性退役→bind→同上 |
| 无 | 有 | 拒绝 |
| 非我或不可解析 | 任意 | 拒绝 |

拒绝文本：k 存在时沿用该域 main 首错（S `TransportUnavailable：socket路径已占用`，E/B/X 的 `socket绑定失败`）；k 不存在而 owner 非我，用 `TransportUnavailable：socket名字已由其他写者锁认领`。bind 后按路径重开 parent(k)，(dev,ino) 不等于 d 即关闭监听并失败。写 bound 成功前不 accept。
6. 退役＝移走再核，不删除。① openat(d,basename,O_PATH|O_NOFOLLOW) 钉住对象 p；fstat(p) 须为 socket、属主 euid、nlink=1，按身份时 (dev,ino,ctime_ns) 等于 bound；connect(`/proc/self/fd/<p>`) 须得 ECONNREFUSED，成功、EAGAIN、超时、其他错误一律拒绝。② renameat2(d,basename,d,`<basename>.retired.<ino>`,NOREPLACE)，EEXIST 即拒绝。③ fstatat(d,退役名) 的 (dev,ino) 须等于 fstat(p)；不等即以 NOREPLACE 放回原名并拒绝，放回失败则留在退役名并拒绝。产品不对任何 socket 调用 unlink；退役对象此后不参与任何判定。「按连续性」只用于 bound=null（只可能由本锁谱系在 bind 后崩溃留下），不比对已记身份，其余相同。
7. S 在参数期（现 `s_session_v3/writer_cli.rs:389-393`）以只读方式调用同一判定函数，结果为拒绝即按原文拒绝；通过后仍在第 5 条位置正式判定。E/B/X 无预筛。
8. 有序关停不动 k 与 owner（#2077 不变）。
9. E 与各 B 的正常关库标记：本域库 meta 键 `clean_close/1`，值 `{"writer_epoch":"N"}`。只在三处写：init；`advance_recovery`（与升代同一事务，recover 与 recover-named 共用）；受监督有序关停，即 SupervisedStdin 下传输循环以 Ok 返回之后、关库之前，同一连接提交一个事务，失败即非 0 退出。任何 serve 在 check_epoch 与 audit 之后核它，缺失或 N 不等于持久代即 `StaleWriter：缺本代正常关库标记，须先正式恢复`，不 bind、不改库、不动 k。写 bound 之后、accept 之前，以一个已提交事务删除它；此前 serve 不对本域库做其他写入。独立 serve 同规则，它没有有序关停，退出后须先正式恢复。标记门不受第 3 条影响，所有平台生效。launcher 的 `writer_closed` 只是观察量。正文须写明这一条与 SPEC 的关系：有序关停后的再服务不经 recover，serve 的 check_epoch 与全域 audit（逐步重放）就是 IC:62 的「先恢复本域未决状态、引用完整性和 writer 代际」；C09.9 所禁的「从旧 Open 恢复」由标记门挡住。
10. S、X 不加标记，启动门不改。S 仍由 R4 介质准入（`admission_provider.rs:231`，有 SHM 即拒）与未完成 Begin（`audit_owner.rs:1198`）决定；X 仍是持锁、epoch 不降、冻结 profile 与审计，每次启动同一道门。simulation X 不派生常驻子进程，取得锁即旧 X 已退出；C09.8 的「部署监督器确认旧进程及发送子进程已退出」针对真实场所发送，归 #1401，那些 profile 没有本地监听，不适用本裁定。
11. 列内失败不换路：任一门拒绝即本次启动失败，不改走别的路径，下次从持久状态重判。
12. launcher 两处改动，都只多拒。(a) 任何 init 之前看 E 与全部 B 的库：全无则照 main init，全有则不 init，部分存在即 `InvalidDomain` 点名缺失字段，不 init、不 spawn。S 库照 main 单独判（S 库先建并签锚后才首启，是正常形态）；X 库由 X 自建，不在此条。(b) `--economic-recovery-plan` 的条目集合由等于 E/B 域集合改为其子集（改 #2082 `production_session.rs:295`）：有条目的域用 current-recovery 核过的回执代，无条目的用 manifest 代，B 的 `--e-epoch` 取 E 的有效代，代不符由域以 StaleWriter 拒绝。launcher 不恢复、不升代、不碰 k、不读 owner。
13. 再服务判定只读本域的锁、owner、库与介质，不读其他域、launcher 或会话级记录。launcher 存活期的监督语义不改不裁（TB-05 #1363）；在线单域重拉归 #2120。
14. launcher 崩溃：孤儿持锁照常服务；新启动被第 2 或第 7 条拒，现场不动；本裁定不让任何一方终止孤儿。孤儿退出后按第 5、9、10 条。宿主重启同此。
15. 不授予与明文边界。只规定产品二进制对自己目录内对象的行为，不授予终止进程、unlink、改属主或权限、账户、凭据、部署启用。第 5 条拒绝态与第 3 条不成立只在外部改动后出现，出口是 runbook 票的另获授权动作，建立前保持拒绝。同 UID 且不守合同的进程（能直接改库、改 owner）不在排除范围，与域库单写者同层，按 ADR 0039:286 归 TB-09；对它只保证产品不销毁任何 socket、被移对象可原样放回。不认识标记的旧二进制在同一库上 serve 属同类。E/B 库全失与首启不可区分、X 库丢失属磁盘灾难（C09.3 不承诺），不改现行行为。路径是否进提交根归 #2127，本裁定只要求同一布局下 k 字节不变。
16. 可观察量：第 5 条成功后域向 stderr 写一行 `endpoint-claim`（domain、action=fresh|vacant|retired|adopted、retired）。只供验收，不是判定输入。

## 三、情形表

| 情形 | 结果 | 证据 |
|---|---|---|
| 首启 | E/B init 写标记；各域 fresh；E/B accept 前销标记 | owner；meta 无标记 |
| 有序停后原 manifest 重启，E/B | 标记在且代相等，retired，销标记，代不升；曾恢复过的域在计划里带原回执 | 标记；退役对象 ino 等于原 bound |
| 同上，S | 预筛过，持锁，R4 过（#2077 关库后无 WAL/SHM），Begin idle，retired | 读回 cut-1 原收据，input-2 Committed |
| 同上，X | 既有启动门，retired，代不变 | x_meta.writer_epoch |
| kill -9 E 或某 B | launcher 回收其余并非 0 退（现行）。该域无标记：不恢复即拒，k、owner、库不变；recover-named 后计划只含该域，以回执代启动并 retired；其余域正常、代不变 | 该域 meta 与回执 |
| E 升代之后 X 对 E 的权威交换 | X 冻结 `authority_profile` 里的 e/s authority_epoch（`runtime.rs:506-517、815-826`），回复代不等即 IdentityConflict。deferred to 新票 T-X | 读码推断，未实跑 |
| kill -9 S | 端点不挡路，R4 因 SHM 拒，s.socket 不动。介质再准入与 S 恢复后有效代交接 deferred to 新票 T-S | 首错为 R4 类 |
| kill -9 X | launcher 只记录；整会话有序停后重启，X 走既有门并 retired，代不变。真实场所 profile 无本地监听，旧发送者退出证明 deferred to #1401 | |
| 提交前后、回报应用边界处被杀 | 端点与是否须恢复同上四行，不随中断点变；不重复调用等四项由各域恢复合同负责 | 各域库 |
| launcher 被杀，子进程活 | 孤儿续服；L2：S 预筛 connect 成功即拒，E/B/X 锁拒；现场不动 | inode 与 owner 不变 |
| 孤儿随后退出 | 只能被信号结束，E/B 须恢复，S 过 R4 门。谁可结束孤儿 deferred to runbook 票；#1411 夹具只结束自己拉起的进程 | |
| 宿主重启 | 持久卷残留按表 retired，tmpfs 上 k 与 owner 同失则 fresh；E/B 须恢复；不读 boot ID。#1411 不要求 | |
| L1 活时启动 L2，含 SIGSTOP、积压满 | 拒；connect 成功或 EAGAIN 都不是 ECONNREFUSED | |
| 无 owner 残留、他人 owner、身份不等、普通文件、目录、链接、父路径链接、目录他人可写 | 拒，原对象不动 | lstat 前后相同 |
| 预核与移动之间被同 UID 进程替换 | 移走后复核不等，放回，拒；竞争者对象未删且仍应答 | 探针 race_* |
| bind 与写 bound 之间崩溃 | (null,有) 按连续性退役后照常；E/B 标记未销 | action=adopted |
| 被拒的启动 | 标记与 k 都不变，可原样重试 | |
| E/B 库部分缺失 | InvalidDomain，不 init | |
| 升级后首次、旧残留 | 无标记须正式恢复（C09.11）；无 owner 残留拒 | |
| 恢复应答丢失后重试 | #2082 不变；其间 serve 运行并崩溃则原回执不能再用 | |
| launcher 活时只重拉一域 | deferred to #2120 | |
| S 的 socket 在 M 内；非 Linux | 旧合同，OBS-IN 读数不变；标记门仍生效 | |

## 四、从第四稿删除

endpoint_mode；部署监督器；发布助手与发布日志；登记簿、登记代、端点代、重登许可；`production-session-deployment/1` 与 domain_exit_results；session_key、job_id、run_id、boot_id、process_start_id；FD 交付与 SO_ACCEPTCONN；managed-readiness、managed-recovery-selection；锚目录、受保护卷、双身份、获准环境清单；`scripts/verify_managed_endpoint_reboot.py` 与 7 组 managed_endpoint_*；「#2120 前不得作默认部署」一句。

另有五样不得加回：B 的回执 cut 新鲜性（会迫使每次重启升代，撞上 X 冻结的 authority_epoch）、调用者换目录链接、RENAME_EXCHANGE、标记绑定 cut、任何会话级回收证明。

## 五、验收（`rust/tests/production_session_entry.rs`，Linux 正式入口真进程，CI `rust-test-production-session` 日志逐行 `test <名> ... ok`；夹具把端点目录建成 0700）

endpoint_orderly_restart（原 manifest 字节；cut-1 原收据逐字节读回；input-2 Committed；四域代不变；每个 k 的 inode 已换且旧对象在退役名）。endpoint_crash_needs_recovery（E 臂、B 臂：不恢复被第 9 条拒且 k、owner、代、最新 cut 不变；恢复后子集计划启动成功，其余域代不变）。endpoint_live_untouched（存活、SIGSTOP、积压满）。endpoint_unknown_untouched（上表各类加 M 内两布局）。endpoint_race_replacement（testonly 同步点；竞争者换入活监听、普通文件、换父目录三例，对象未删未改）。endpoint_bind_window（bind 后同步点强杀，重启 adopted）。endpoint_launcher_crash。economic_store_partial_refused。clean_close_negative（手删标记；独立 serve 被杀；被拒启动后标记仍在）。#2077 的 :994、:1105 两处断言改写：前者改为重启成功，后者改为首错 R4 类且 s.socket inode 不变。

## 六、票与边

#2079 是 #1411 的原生子票，关闭即放行。两张新票由主控先开（挂 #1366，blocks #1411），票号写进正文再送审：T-S 裁 S 被强杀后带 SHM 的介质怎样再准入、S 正式恢复后的有效代怎样交给 launcher；T-X 裁 E 或 S 恢复升代后，X 冻结的 authority_profile 与 E manifest 的 authorized_sources 怎样跟随。runbook 票承接：结束孤儿、拒绝态清场、目录整改、退役对象清理，不 blocks #1411。#2120 保持 blocked by #2079，票面去掉受管前提。#2077、#2082 按现头先合，标记、子集计划、库存在性检查、传输层拆成「认领端点」与「服务」两步归 #1411。#1823 的 SAFE 五族由第 2–6 条满足，PID/boot 绑定由内核锁取代，SAFE-STALE 的「清理」在本裁定指退役改名、不 unlink。#1363 不新增边；#1769、#2029 写区重叠列入受影响票。

## 七、关键步骤依赖的条文原文

ADR 0059:117「重启时谁来清理，归 #1823 调查，不在本裁定范围内」；:121「不设可调字段，不设放行开关」。ADR 0039:284「每个域有自己的 `--db`、`.writer.lock`、`writer_epoch`」；:285「launcher 只负责启动、顺序、监督、换代和指纹计算。它不持任何域的写者身份」；:286「手工用生产库路径启动域 bin 的情形，是 TB-09 部署隔离（#1383/#1401）的验收对象，本 ADR 不把「约定」算作锁」。ADR 0041:43「不能把文书裁定当成外部操作许可」；:46「代理可裁定方法、形成推荐值和实现方案；独审 PASS 不代签具体外部操作」。SPEC:326「S/E/B 之间不共享应用级锁、读写事务或故障恢复闸」；:332「E 重启先恢复 Recorded/Pending…不能从旧 Open 恢复」；INTERFACE-CONTRACTS:62「每个域重启先恢复本域未决状态、引用完整性和 writer 代际」；SPEC:334「版本升级…发布新 writer_epoch 后旧写者不得再写」。#1823 评论 6994092216「须明确哪一方从创建到清退有可执行的名字空间所有权；无法确定时保留端点」；SAFE-RACE「删除必须拒绝或在排他协议下无法发生替换；竞争者的对象不得被删除」。#2079 票面「优先考虑不需要删除归属不明路径的方案」「本票不授予 unlink」。

## 八、落地形态与证据

以 main 为基只含 ADR 一个文件（`docs/adr/0065-production-session-endpoint-ownership.md`）；头三行为正本、最后裁定（日期、分级重跑、依 #1909 代理独审、非 UserSigned）、受影响代码清单；注明 `session_transport.rs:618、:648` 旧注释被取代。受影响代码清单至少列：`rust/src/session_transport.rs:57-81、:641-650`，`rust/src/bin/s_session_v3/writer_cli.rs:372-395、:848`，`rust/src/economic_session/service.rs:1515-1595`，#2082 的 `store.rs:1722`（advance_recovery）与 `production_session.rs:288-296`，`rust/src/bin/production_session.rs:276-320`，`rust/src/history_simulation/runtime.rs:866-897`，`rust/src/bin/x_execution_session.rs:202-212`，`rust/tests/production_session_entry.rs`；实施归 #1411。

证据分级。实测：内核行为探针 `/tmp/p2079-brief-probe/probe.py` 与 `probe2.py` 在本机 Linux 7.0 tmpfs 上输出 28 项读数，下列各项成立（杀后锁可得、残留 connect 得 ECONNREFUSED、残留上 bind 得 EADDRINUSE、经钉住对象探测时死对象得 ECONNREFUSED 而活对象连上、NOREPLACE 移走后 dev/ino 不变、经目录 FD bind、openat2 遇链接 ELOOP、竞争者换入活监听后放回且仍应答、SIGSTOP 时 connect 得成功或 EAGAIN）。它须入证据分支并在 CI Linux ext4 复跑后才可引用；macOS 未测，故限 Linux。读码未实跑：E/B audit 只逐键读 meta（`store.rs:993-1003`），新增键不触发拒绝，#2082 已把回执写进 meta；X 对回复代的比较；S 被杀后 R4 的读数（#1411 评论 6989751686 有正常停机旧版的实测）。
