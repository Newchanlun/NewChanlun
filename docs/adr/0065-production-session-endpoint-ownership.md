# ADR 0065：生产会话端点归本域写者锁持有者

> 正本：本文件是 `production_session` 正常关停或崩溃后的同址本地 Unix socket 归属、退役与再服务前提的正本。
> 最后裁定：[#2079](https://github.com/Newchanlun/NewChanlun/issues/2079)（2026-11-20，P 类，依 #1909 代理独审裁定，非 UserSigned）。
> 受影响代码清单：见文末；`session_transport.rs:618、:648` 的旧注释由本裁定取代。

## 一、问题

原库正常关闭，不等于原 socket 现在可以使用。#2077 的有序关停保住非空 S 库的 cut-1，SQLite 收掉 WAL 和 SHM，但原址再启仍被拒。#1823 的 Linux OBS-IN-A、OBS-IN-BASENAME、OBS-OUT 也都停在 S 参数期：`TransportUnavailable：socket路径已占用`。这六份读数没有走到 R4 或 S bind。本票裁谁可以再用同一个端点名，并把名字的判定与库能否继续服务分开。#1411 以同一原布局、同一原库、同一 manifest 字节读回 cut-1 原收据，再令 input-2 提交。

## 二、权威依据

- [ADR 0039 三.1–4](0039-production-entry-inventory-and-unique-launcher.md#三唯一正式-launcher-的-seam)（:273–287）规定正式 launcher、逐域写者锁和权限边界。#1818 的[已裁规则](https://github.com/Newchanlun/NewChanlun/issues/1818#issuecomment-6550813315)与 [ADR 0059 第 1–10 条](0059-production-session-layout-contract.md#裁定)（:95–121）定义 S 测量域 M，保留 S 自己在 driver open 后直绑的例外，并把残留处置留给 #1823。此处只给 **M 外**的 S 增加退役，不改 M 判据。
- [SPEC #1340 C09.3–11](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md#L326-L334) 与 [INTERFACE-CONTRACTS:62](https://github.com/Newchanlun/NewChanlun/blob/efc1ddc4d6c015f4f8c6d44f904d704a88308b46/.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/INTERFACE-CONTRACTS.md#L57-L62) 保留域独立、先恢复本地权威再供读取、真实发送隔离、长期责任、升级和回退约束。
- [#1823 的观测](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294)、[SAFE 原件](https://github.com/Newchanlun/NewChanlun/blob/cc674e88768c6386ad58c6480b815dd9fb860221/.chanlun/review-results/issue2079-decision-inputs-r3/sources/1823-safe-original.md) 与[并发条件](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)：最后一次预核后路径仍可换主，不能核完 inode 再按名删除。SAFE-STALE 的“清理”在此指改名退役，新测试用域锁和钉住的对象取代 PID/boot/start-time 链。SAFE-LIVE、UNKNOWN、RACE、ADMISSION 的负控照保留。
- [#1372 PY-XR-02 的限定复核](https://github.com/Newchanlun/NewChanlun/blob/b9d898dccf46c2a716115eaa1215bc39c458a959/.chanlun/review-results/issue1372-tb01c-20260913/reports/python-cross-review-fix-01/REVIEW.md#L8)验证了旧控制器的已停止记录、登记身份、拒绝连接及删前复核。保留未知与存活对象必须被拒的判据，不沿用按名删除：复核与删除之间没有排他保证。
- [ADR 0041 授权边界](0041-degrees-of-freedom-configurable-not-excluded.md#授权来源与生效边界1909--pr-19152026-11-07)（:39–48）与 [#799 收敛通则](../agents/doctrine-rules.md#收敛通则同一判断不得有宽严两档799-裁定2026-07-30)（:43–54）：端点资格、域库准入各自成立，不能用一个门的证据替代另一个门，也不在拒绝后换宽路。

## 三、候选

1. **域锁定归属，改名不删除，库内记正常关库（采用）**。两份持久记录解决两件事：owner 记录当前名字归谁、记录了哪个对象；E 和每个 B 的库内标记说明其数据库何时可在当前代重新服务。锁只属于本域，不加跨域恢复闸。
2. **重启发新端点**。绕开旧名字的处置，但会改变原布局和已冻结的引用，不能交付本票要求的同一 manifest 原址续服。路径进入提交根的取舍另归 #2127。
3. **独立发布身份或跨代保留监听 FD**。独立身份换全新监听器可行，但需要另设对名字的排他部署权限；不为原址续服增加部署角色和证明链。跨代持有同一 FD 会把旧监听队列交给下一代，Linux 和 Darwin 的[原件](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/EVIDENCE.md)都观察到了这一点。本裁定不转交监听 FD，不设模式、可调字段或放行开关。

## 四、裁定

### 端点

1. **唯一写者。** 对 S、E、各 B 以及带本地监听的 simulation X，端点名 `k` 只由持有本域实际 `<db>.writer.lock` 的进程 bind 或退役。guard 在 bind 前取得，覆盖整个服务期以及监听 FD 关闭、E/B 关库标记事务提交（如有）和域库关闭，最后才释放。正式 S driver 的 WriterScope、E/B CLI 的 guard、X 的 guard 已经先于现行 bind 获得；#1411 将认领与开始接纳拆开，不给 transport 新建一把锁。`b9d898dc` 的通用 acceptor 将监听器交给线程却不显式 join；沿用 #2077 的 join，并在所有返回路径保证上述关闭顺序。`production_session`、客户端和其他域不创建、不移动、不删除 `k`。
2. **退役只认两项内核证据。** 取得同一锁文件对象的内核锁，证明前代已不持有这把写者锁；锁文件不得在持有期间被替换。获得锁不证明前代 PID 已消失（[#1895](https://github.com/Newchanlun/NewChanlun/issues/1895#issuecomment-6727386306)），也不证明真实场所发送者已隔离。退役残留还必须对钉住的对象作 `AF_UNIX/SOCK_STREAM` 非阻塞 connect，且只接受 `ECONNREFUSED`。锁冲突沿用 S 的 `StaleWriter：S独占进程锁不可得`（保留 admission 包装）与 E/B/X 的 `StaleWriter：{domain_name}独占进程锁不可得：{e}`。不得等待或终止旧进程，不以旧 PID、boot ID、时间、日志或 launcher 事件放行。第 5 条的 peer pidfd 只用于证明**本次**监听器身份，不用于退役。
3. **先判布局、合同和地址，再动端点。**
   - **X 的 M 外硬门。** 正式 launcher 把同一 manifest 中已经用于 S 的 `s.db`、`s.admission_job_limits` 原值经 `--s-db`、`--s-admission-job-limits` 传给 X `serve`，不新增 manifest 字段，不传「已通过」布尔值。带本地监听的 X 用本次加载并交给 runtime 的 `history_simulation.socket`（不是场所 `endpoint` 或权威读口），按 ADR 0059 第 1–4 条用这对参数推导 P、S 族及 A，同时核 socket 的目录项父目录 `Q₄` 与解析最终链接后可能 bind 的父目录 `Q₅`。任一命中 M，或参数缺失、路径不可核，则 X 非零退出 `InvalidDomain：simulation X 监听端点须在 S 测量域 M 外`，附冲突字段与路径或不可核原因。此只读门在 X 取锁、开库、`persist` 前执行；在进入任一端点路径前，用实际用于 bind 的目录重核，认领时核 `d` 对应的目录。拒绝不建 owner、不移动、不 bind，也不走旧直绑。M 判定复用 0059 的布局语义，不读取 S 进程状态或等 S 就绪；不带本地监听的 X 不要求这对参数。该门归 #1411 实施，不等 #2130。
   - **认领资格。** 仅 Linux，且 `openat2(RESOLVE_NO_SYMLINKS)`、同目录 `renameat2(RENAME_NOREPLACE)`、`O_PATH`、`/proc/self/fd` 可用。`k` 为绝对路径，逐段无 `.`、`..`，以无链接的 `openat2` 将其父目录打开为可 fsync 的目录 FD `d`。`fstat(d)` 的属主是 euid，组和其他位均不可写；`fstatfs(d)` 的类型限 ext 家族、XFS、Btrfs 或 tmpfs。前三种是本合同的本地持久文件系统；overlayfs 不证明底层位于本机。S 还核 `canon(parent(k))` 不命中 ADR 0059 第 4 条的三款；M 用规范库路径及 `--admission-job-limits` 推导，未核明算不适用。S 在 M 内仍保留 driver open 后的旧合同，不沿用 X 的拒绝语义。
   - 开始认领前判定不适用时走旧端点合同：`k` 有对象就按占用拒绝；`k` 空但有任意 `<basename>.owner` 条目，报 `TransportUnavailable：旧端点合同不接管已有 owner`；只在两个名字均不存在时直绑。不建 owner、不动残留；无法核验不视为不存在。这样保留从未认领的空址在组可写目录和非 Linux 上的 bind，不让已认领的名字因环境变化被直绑绕开。**两条路径均须过 E/B 标记门，并在 bind 成功后、首个 accept 前消费标记。**
   - **两个地址分别量字节。** Linux [UAPI](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/un.h#L7-L12) 的 `sun_path` 为 108 字节；本合同与客户端一致，留一个字节作终止 NUL。公开 `k` 和认领 bind 用的 `/proc/self/fd/<d>/<basename>` 均不得内含 NUL，且各自最多 107 字节；S 的原 100 字节公开上限仍有效。Linux 直绑也先核公开地址；认领须在建／改 owner、退役或 bind 前，用将一直持有到 bind 的实际 `d`（含其十进制 FD 位数）核内部地址。任一非法按 `TransportUnavailable：socket地址长度或内容非法：<公开地址|内部绑定地址>` 拒绝（S 的既有参数错误优先）；不改端点目录，不降级、不截短、不改 `k`。开始认领后，`NOREPLACE` 不支持或任何核验、写入失败均拒绝，不回到直绑。
   - **认领先核监听器证明可用。** 对已选认领路径的启动，用本进程 `socketpair` 和 `pidfd_open(getpid(), 0)` 只读验证第 5 条所需的 `SO_PEERPIDFD`（Linux 6.5 起提供，按能力判）、`/proc/self/fdinfo` 和比较规则可用，才可建／改 owner、退役或 bind；能力不可核即拒绝，不回到直绑。
4. **锁路径先定，owner 记实际锁路径。** S 使用原准入 lease 绑定的规范库路径。其余域在 `process_lock` 的共同路径解析处，先规范化父目录，再用不跟随末级链接的 stat 区分真正缺叶和已有条目。只有父目录可核、叶确无目录项，才用规范父目录拼原 basename；有条目则必须得到整个库路径的规范路径。末级链接无法解析（含悬空或成环）及其他不可核错误均拒绝，不以链接名代替目标。规范路径接 `.writer.lock` 后即为持锁代码实际打开的绝对路径；同一次启动用已选定的规范库路径打开 SQLite，不再从原参数重新解析。X 所有 `serve` 在创建锁、开库及 `persist` 前执行此门：无链接首启建库前后取同一锁，目标已存在的链接从一开始就取目标锁。上线前若曾让旧二进制用悬空链接启动，须由获授权运维先确认旧写者已退出，再启新版；目标现在存在不能证明旧写者拿的是目标锁。该迁移处置归 #2130。锁路径不另解析锁文件末级链接，也不替代实际内核锁对象。
   - **一个 owner 文件。** `<basename>.owner` 位于 `d`、权限 `0600`；规范 JSON 恰有四键：`schema="endpoint-owner/1"`、`socket=k`、`writer_lock`（上述实际打开的锁路径）、`bound`。`bound` 为 `null` 或含 `dev`、`ino`、`ctime_ns` 的对象（十进制字符串，无损比较）。普通文件、euid、单链接、模式 `0600`、规范解析且前三项逐字节相符才算“我”。读时钉住条目并核类型，不跟随目录内链接。持锁者首建用 `O_CREAT|O_EXCL|O_NOFOLLOW`，写完 fsync 文件和目录。更新只写同一个已钉住、复核为普通文件的 FD（从 `/proc/self/fd` 重新打开，核 dev/ino 后才写和截断），并 fsync；写前、写后核 owner 名仍对应该 inode。不得按目录名覆盖、删除 owner 或用临时文件覆盖目标，即使有人把 owner 名换入 socket 也不能销毁它。**原地更新不是原子的。** 进程中途被杀可留下不可解析的 owner，此时按“非我”拒绝并保留，交 #2130；不使用备用 owner。这里以可能需要人工恢复换取不按名覆盖 socket。
5. **先证明新目录项属于本次监听器。** 持锁且本域启动门均过后，域用下表决定是否 bind。`ENOENT` 才算无；其他错误是不可核验。认领操作相对 `d`。bind、listen 成功后，尚不 accept；用 `openat(d, basename, O_PATH|O_NOFOLLOW)` 钉住候选目录项 `p`，核其为 euid 的单链接 socket。仅按名打开后再复核同 inode，不能证明它由本次 bind 创建。
   - **按 inode 连。** 每个正式域进程在证明前只对本次新建的一个 `AF_UNIX/SOCK_STREAM` FD 调 `listen`，不接收或交出监听 FD，也不启动 acceptor。用另一个本地非阻塞 stream FD connect `/proc/self/fd/<p>`，只接受立即成功。Linux procfs 的 magic link 返回 `p` 的 `f_path`（[`proc_fd_link`](https://github.com/torvalds/linux/blob/v6.12/fs/proc/fd.c#L175-L192)）；Unix pathname connect 按该路径的**内核 inode 对象**查找监听 socket，而非按原字符串匹配。成功连接会把监听端在 `listen()` 时记录的进程对象（`struct pid`）复制到探针端，不等 `accept`（[`unix_find_bsd`、`unix_listen`、`unix_stream_connect`](https://github.com/torvalds/linux/blob/v6.12/net/unix/af_unix.c)）。
   - **核监听进程。** 从探针的**连接发起端**取 [`SO_PEERPIDFD`](https://github.com/torvalds/linux/blob/v6.12/net/core/sock.c#L1856-L1885) 返回的 pidfd。保持它和 `pidfd_open(getpid(), 0)` 的本进程 pidfd 打开，从同一个已打开的 `/proc/self/fdinfo` 目录分别读两者的 `Pid:`，要求各恰有一个可解析的正整数且相等。内核只对仍有任务的 pidfd 报告可见 PID，已退出并回收的对象报 `-1`，不可见报 `0`（[`pidfd_show_fdinfo`](https://github.com/torvalds/linux/blob/v6.12/fs/pidfs.c#L71-L94)）；因此旧进程退场后，即使其监听 FD 仍被别的进程持有，重用同一数字 PID 也不能冒充本进程。只有本次唯一监听器能使比较成功；`SO_PEERCRED` 的数字 PID、UID 或 `getsockname` 都不足以替代。
   - 探针不发送帧，取证后关闭；今后若由接纳循环取到该连接，按无完整帧关闭，不交 handler。证明使用受信 Linux 路径解析；可改写该 syscall 的特权策略不在此合同内。证明失败（包括 `EAGAIN`、无法核验 pidfd 或不是本进程）关闭监听、拒绝，保留现有条目，不写 `bound`、不消费 E/B 标记、不 accept、不走直绑。
   - **记证。** 保持 `p` 打开，按原路径无链接重开父目录比 `dev,ino`；再不跟随链接核 `d` 下的名字仍指向 `p` 的同一对象且类型、属主、链接数仍合格。fsync 目录后，把 `p` 的身份持久写入 `bound`；接纳前（E/B 在消费标记前）重验父目录、条目及已记录的三元组。不符则关闭监听、拒绝，不删除任何对象。即使有人在初次 `openat` 之前换入了同 UID、单链接 socket，探针也不能把它认证为本次监听器；后续改名不能把已钉住并证明过的 inode 换成另一个对象。`bound` 证明的是本次创建的对象，不是对末次重验以后名字仍不变的承诺；可用性仍受第 15 条约束。`action` 取下表。

   | owner | k | 动作／action |
   |---|---|---|
   | 无 | 无 | 首建 owner(null)，bind 并记对象／`fresh` |
   | 我，null | 无 | bind 并记对象／`vacant` |
   | 我，有身份 | 无 | 写 null，bind 并记对象／`vacant` |
   | 我，有身份 | 有 | 按身份退役，写 null，bind 并记对象／`retired` |
   | 我，null | 有 | 拒绝；保留 owner 和原对象，交 #2130 |
   | 无 | 有 | 拒绝；原对象保留 |
   | 非我或不可解析 | 任意 | 拒绝；原对象保留 |

   `null` 只证明准备过 bind。旧合同的两次空名检查与新合同的 owner 首建不互斥；不同域锁也不序列化两者的 bind。即使旧直绑的赢家已退出、试连会报 `ECONNREFUSED`，也不得凭 null 退役对象。入表时 `k` 存在，表内拒绝或退役预核中的类型、UID、链接数、身份或试连不符，都按占用报错，不再探查能否直绑。S 保留 `TransportUnavailable：socket路径已占用`；E/B/X 保留 `TransportUnavailable：socket绑定失败 {e}`，占用用 `EADDRINUSE`（Linux 已见原文 `TransportUnavailable：socket绑定失败 Address already in use (os error 98)`）。空址但 owner 非我：`TransportUnavailable：socket名字已由其他写者锁认领`（旧端点合同用第 3 条的专用错误）。S 不可 stat 时保留 `TransportUnavailable：socket路径不可核验：{e}`；S 原有空参数、长度和 `TransportUnavailable：socket父目录须已存在` 错误不变。不能确定路径状态，或监听器证明、改名、持久化、目录重验失败时，返回 `TransportUnavailable：socket认领失败：<步骤>：<原因>`；bind 返回原来的错误。不重试，不放行。退役预核按占用拒绝时不另报一次试连错误。
6. **退役只移不删。** 域用 `openat(d, basename, O_PATH|O_NOFOLLOW)` 钉住 `p`。其 `fstat` 须为 socket、euid、单链接，且与非 null 的 `bound` 三元组相等。对 `/proc/self/fd/<p>` 非阻塞 connect，成功、`EAGAIN`、超时或其他错误均拒绝；只有 `ECONNREFUSED` 才从原名以 `RENAME_NOREPLACE` 改到 `<basename>.retired.<ino>`。目标被占用或改名失败即拒绝。保持 `p` 打开；改名后对退役名不跟随链接，核 `dev,ino` 与 `p` 相同。`ctime_ns` 只在移走前比，不能假定改名时必变或不变。不符（含无法核验）即尝试以 `RENAME_NOREPLACE` 放回原名并拒绝，原名若又被占用或放回失败，则保留退役现场并报告两个名字与错误，交 #2130。整个过程不覆盖任何已有条目；正式域 Rust bin 和 `production_session` 不 unlink 任何 socket。已确认退役的对象不参与后续身份判断。
7. **S 预筛只读。** `ServeOptions::parse` 原 socket 检查处，以本域配置的锁路径和 M 调同一认领判定的只读部分。可以开目录和钉住对象、试连，不创建文件、不改名、不绑定、不把预筛通过当成资格。预筛拒绝沿用第 5 条的 S 首错；预筛过后仍走原 admission，最后在持锁状态重判。E/B/X 无预筛。
8. **停机不改名字。** #2077 有序停止先收监听再关库；有序停止不修改 `k` 或 owner。旧监听关闭后，下次使用新监听器，不继承上一代排队连接。

### 再服务前提

9. **E/B 各自记正常关库。** 本域 SQLite `meta` 新增键 `clean_close/1`，值恰为 `{"writer_epoch":"N"}`，N 为持久正整数代的十进制字符串。不改表、schema 或业务提交根。
   - 只有三处写标记：init 在写代 1 的同一事务；正式 `recover` 和 `recover-named` 经 `advance_recovery` 在升代的同一事务写新代（重取已存在的同请求回执不重写标记）；`SupervisedStdin` 收到规定字节、服务循环 `Ok` 返回（监听已关且不再执行 handler）后，由本域在关库之前用同一连接提交本代标记。末项提交失败非 0 退出，不报告正常关库。以事务已提交为界；即使在提交后、进程退出前被杀，也已无业务 handler 或监听。`writer_closed` 只是 launcher 观察量，EOF、SIGTERM 或 `Standalone` 不写正常标记。
   - 任一 `serve` 持锁、`check_epoch` 和全域 `audit` 通过后，先验标记。缺失、不可核或 N 不等于持久代，返回 `StaleWriter：缺本代正常关库标记，须先正式恢复`，不 bind、不改权威库内容、不动 `k`。过标记门后才进入端点路径。**无论经认领表还是经旧合同直绑，bind 成功后、首个 accept 前，都必须在一个事务中删除标记并提交。** 走认领表须先完成第 5 条证明、持久记录和末次重验；证明失败不得借旧直绑消费标记。删除须恰命中已核的这条标记，失败即关闭监听、非 0 退出，不 accept。此前不写本域业务或启动 meta；SQLite 本身的侧件及锁不算业务写入。旧库没有标记，一律先过正式恢复；独立 serve 消费标记后退出不补写，下一次 serve 须先正式恢复。
   - 库曾由不识该标记的二进制开服，或本次库来自备份时，旧标记可能仍匹配代。已获授权的域运维须在前滚或恢复备份后先执行正式恢复，不能把看起来有效的标记当成本次关库证明；程序无法仅凭库内两值发现这种外部替换。按 #2130 处理，操作权限或恢复条件不满足时不启动。
   - **为什么干净停机不升代：** C09.9 要 E 从持久 Recorded/Pending、证据、前沿、责任与 Released 的原状恢复，不准拿旧 Open 当起点；B 必须重新核原归属应用。当前代匹配和全域审计重验持久原件、逐步重放、引用和物化状态，再通过关库标记确认同代上一轮已停止处理，合 IC:62 的“先恢复本域未决状态、引用完整性和 writer 代际”。这里恢复的是已提交状态及其引用，未决责任仍按原身份保留，不把开服本身当作一次换代。无标记时，审计通过也不足以从旧 Open 续跑，必须显式正式恢复；C09.11 的升级及回退合同仍适用。#2082 的回执核当前代不核“上次 serve 已干净关库”，故不能替这个门。
10. **S、X 保留启动门。** S 仍核 R4 介质、未完成 Begin、epoch 和既有准入，不接受带 SHM 的介质；保留 `UnsupportedWalShmJournalCombination` 与需要 recover 时的 `StaleWriter：未完成Begin须先由监督器recover` 原诊断（该字样不授予新角色）。S 真实恢复后的介质再准入及有效代交接归 #2128。X 不加标记；过第 3、4 条的只读前置检查后，本地 simulation 仍先锁、核 epoch 不降、冻结 profile、审计，再 bind。正式 X 把已核的监听路径与布局输入交给 runtime 的绑定入口，不能绕回只凭 profile 路径直绑的旧调用。不提供本地监听的 profile 沿原服务合同（库锁路径仍按第 4 条）。C09.8 的旧 X 与仍可发送的子进程退出证明、发送门及已发请求责任，归 #1401 的真实场所路径，不由本地端点认领替代。
11. **拒绝后不换路。** 任一域任一门拒绝，本次域启动非 0，不另找路径、旧证明或宽判据。下一次从该域的持久状态重新判定。既有 launcher 对关键域与非关键 X 的处理保持原样；关键域失败仍按现行监督回收本次拉起的子进程。端点门已完成的动作（例如已复核的退役）不因后续 bind、目录重验或持久化失败回滚；只有第 6 条移错对象才尝试原样放回。标记未消费的失败不会把库判为崩溃。端点和库输入都不可核的拒绝态交 #2130。
12. **launcher 只装配。** 除按第 3 条向 X 传递 S 的布局输入外，再加两处约束。第一，在写 `state_dir` 或任何 init、核恢复计划、spawn 以前，读 E 和全部 B 库路径的存在性。全无才走原 E/B init；全有不 init。部分存在即 `InvalidDomain：E/B 域库部分缺失：<缺失 manifest 字段>`，点名 `economic.e.db` 或 `economic.b[i].db`，不 init、不 spawn。不把不可读路径或悬空链接当成缺失。S 仍按原合同单独判断（首启可已有库和签锚），X 仍自建。第二，#2082 的 `--economic-recovery-plan` 键集从 E/B 全集改为其子集（含空集），仍拒重复域、未知域及坏计划，按原 `current-recovery` 在 spawn 前核验每条且仅每条提交的回执。没条目的域用 manifest 代；不能从回执拒绝回退到 manifest。B 的 `--e-epoch` 一律取 E 有效代（有条目取已核回执，无则取 manifest）。E/B 持锁在 serve 再验自己的当前持久代（旧代报 `StaleWriter：持久epoch不等于获准写者`）；B 真读 E 权威时再验 E 的库持久代，非启动时跨域验库。子集扩展的是计划可省略未换代的域，不放宽域内任何校验。launcher 不恢复、不升代、不读 owner、不碰端点。
13. **作用域只到本域。** 域用自己的锁、owner、库及介质决定再服务，不读其他域的退出记录或会话级证明。launcher 存活时只重拉一域、当健康域仍持锁时怎样取回执及更新来源代，归 #2120。#1363 下现有 TB-05 试验和监督语义不变、不在此裁。
14. **launcher 已退而域仍活。** #2077 的控制管道 EOF 不停机。孤儿照常服务、继续持锁；同址同域新启动被 S 预筛或域持锁门拒绝。已退出的域按第 5、9、10 条重判；宿主重启也是逐域重判，不把重启当关库。产品不终止孤儿；测试夹具只结束它自己拉起的进程，并等退出。实际运维出口是 #2130。
15. **授权与边界。** 本裁定不授予终止进程、unlink、改属主或权限、账户、凭据或部署启用。拒绝态清场、目录整改、结束孤儿与退役对象清理归 #2130，须另外取得运维权限，runbook 建立前保持拒绝。对同 UID 不守合同的进程（含不识标记仍写同库的旧二进制），本裁定不承诺名字持续不变或继续服务；ADR 0039:286 将部署隔离留给 TB-09。本合同保证正式域 Rust bin 和 `production_session` 不销毁 socket，移错对象时原样放回，若原名不能安全恢复即在退役名保留；“原样”是同一对象，不承诺 ctime 或空窗内可连。E/B 库全失不可与首启区分，X 库丢失仍按既有处理；C09.3 不承诺磁盘灾难。是否将路径计入提交根归 #2127，这里只要求同一布局的 `k` 字节不变。
16. **观察而不授权。** 域在 bind 成功且接纳前各项义务完成后，若走了认领表，向 stderr 输出一行：ASCII 前缀 `endpoint-claim ` 后接带换行的 UTF-8 单行规范 JSON。对象恰有 `action`（`fresh`、`vacant` 或 `retired`）、`domain`（`S`、`E`、`B:<id>` 或 `X`）、`retired`（退役 basename，无退役为 `null`）。旧合同直绑不输出该行；E/B 的消费事务必须完成，与是否输出无关。该行只供观察。

### 情形表

| 域 × 情形 | 结果 | 可查证据 |
|---|---|---|
| 首启，S/E/各 B/带监听 X | E/B init 写标记，首次认领 `fresh`，接纳前删标记；S 原 gate、X 原 gate 不变 | owner，接纳后的 meta；S 可预先 init 并签锚 |
| E/各 B 有序停后同 manifest 再启 | 同代标记可用，`retired` 再销标记；曾正式换代的域在计划携带原回执 | 原库代不变，退役 ino 等于原 bound |
| S 有序停后同 manifest 再启 | 预筛通过，#2077 合同下无 WAL/SHM，R4 与 Begin 门通过后 `retired` | cut-1 原收据逐字节读回，input-2 `Committed` |
| X 有序停止会话后同 manifest 再启 | 本地 X 过原门后 `retired` | `x_meta.writer_epoch` 不变 |
| 真杀 E 或某 B | 现行 launcher 收其余关键进程并非 0 退出。死域未正式恢复先拒，k、owner、业务库不动；正式恢复后只为升代域提供子集回执，可认领原名。其余正常关闭域代不变 | 缺标记原错，恢复回执，实际 argv 和持久代 |
| E 升代，X 按旧 E 权威配置交换 | 旧配置不会自动跟随；真实 E 回复信封代变后 X 拒绝。跟随、E 的 `authorized_sources` 与在途责任归 #2129 | 基线真进程 E 从 1 恢复到 2，同一 X 由权威业务拒绝变为 `IdentityConflict：权威回复信封的身份/epoch/因果/规范字节不符` |
| 真杀 S，M 外自有残留、带 SHM | 名字预筛通过，R4 先拒，不退役 `s.socket`。介质及代交接归 #2128 | R4 具名首错，S 原 ino 和 owner 不变 |
| 真杀本地 simulation X | 现行 launcher 只记 X 退出。其余域有序停后重启，X 通过原门即 `retired`，同代；真实场所 profile 无本地监听，其旧发送者确认归 #1401 | launcher 退出事件，X 审计与原代 |
| 各域在提交前、提交后、回报或应用边界被杀 | 端点及是否须恢复仍按上列逐域判；保留责任、不重复调用、不漏应用及同轨迹等价由原恢复合同与 #1411 验 | 各域原库、原身份回执、外效和业务差异报告 |
| launcher 被杀，S/E/各 B/X 仍活 | 孤儿继续服务。L2 中 S 对活对象试连拒绝（或锁拒），E/B/X 锁拒 | 同 inode、owner 未改，旧域仍应答 |
| 孤儿随后全部退出 | 无干净标记的 E/B 须正式恢复；S 看 R4，X 看原门；运维终止的授权与步骤归 #2130 | 新进程只见本域锁、库和介质；夹具只等自己创建的子进程 |
| 宿主重启 | 第 3 条允许的本地持久目录若保留 k、owner 且身份相符，逐域退役；若挂载重建使 dev 改变则拒。tmpfs 上 k、owner 同失走 `fresh`。运行中的 E/B 标记已经消费，须恢复；持久标记有效且库未被外部替换则按正常列 | 不读 boot ID；本票不要求 #1411 做整机重启 |
| L1 活时 L2，含 SIGSTOP、积压满 | 拒绝并保留 L1；connect 成功或 `EAGAIN` 都不是死亡证据 | 原路径同 inode，L1 恢复执行后再取同身份应答 |
| 无 owner 残留、他人/坏 owner、身份或 UID 不符、普通文件、目录、链接、父路径链接、父目录不合权限 | 有对象即拒；合法检查不改原对象 | 前后 lstat，owner 和持久代对照 |
| 预核后换入活监听、普通文件或换父目录 | 不销毁、不覆盖；移错对象时复核后放回，回放受占则保留并拒绝。父目录换掉时不能在新目录接纳 | 对照原对象 dev/ino，活监听仍可应答；后置目录身份复核 |
| bind 后首次打开新目录项前换入另一同 UID 的单链接 socket | 所有权证明失败，关本次监听，不写 `bound`、不消费 E/B 标记，保留条目 | 双方 inode、对端 pidfd、null 和原标记 |
| 域在 bind 后、开始写 bound 前被杀；或旧直绑抢到名字后退出 | owner(null) 与存在的 `k` 不足以证明归属；拒绝并保留两者，交 #2130。认领失败的本域 E/B 不消费标记 | null、原 ino、无退役名，拒绝域标记不变 |
| owner 正写时中断，JSON 半写 | 拒绝并保留；不把坏 JSON 当 null；归 #2130 | 无 accept，标记未消费，原件保留 |
| 启动在持锁／准入／退役预核阶段被拒 | 不消费标记，不改 k；修正失败条件后原样重试。若后来一步已确认退役后失败，按第 11 条保留已完成动作 | meta，k 和退役名，首错 |
| E/B 库部分缺失 | launcher `InvalidDomain`，不 init、无域 spawn | 缺失字段与退出，幸存库和目录投影 |
| 升级首次面对旧库和旧残留 | 旧 E/B 库无标记须按 C09.11 连同正式恢复处理，旧残留无 owner 则拒，别把恢复回执当端点资格 | 旧库 meta、原残留；清场归 #2130 |
| 恢复应答丢失后重试 | #2082 重取原件不再升代；若期间 serve 已消费标记再崩溃，原请求重取的回执不能重新放行 | 字节相同的旧回执与缺标记门 |
| launcher 活时单域原址重拉 | 由 #2120 裁触发、证据与来源代，不在本票实现 | #2120 仍依赖 #2079 |
| S 的 socket 在 M 内；非 Linux 或其他不适用认领的目录 | 旧端点合同，OBS-IN 两布局占用首错不变；无 k 但有 owner 时拒绝；E/B 标记门与 bind 后、accept 前消费在所有路径生效 | 不创建 owner、不移动；E/B 直绑就绪时标记已无 |
| 带监听 X 在 M 内或无法确定 M 外；X 库叶为不可解析链接 | 按第 3 或 4 条拒绝，M 门不走旧直绑；X 拒绝在创建锁、开库、写端点前 | X 非零退出；原件和持久代不变，无锁或库新建 |
| Linux 公开地址超限，或认领的内部绑定地址单独超限 | 在端点变更前拒绝，指明哪个地址失败 | 原 `k`、owner 和退役目录项不变；E/B 标记不消费 |

## 五、验收清单

以下测试落在 `rust/tests/production_session_entry.rs`，用 Linux 正式入口的真进程；除明确的对照臂外，独立端点目录权限为 `0700`。实施 PR 的 `rust-test-production-session` 日志须逐行出现相应 `test <名> ... ok`（`.github/workflows/ci.yml:811、:830–841`），不以早先 #2077/#2082 的 PASS 代替。检测切面用原正式读口，不用打开可能改变 S admission 成员的观测连接冒充真实就绪。同步点只编入测试专用夹具。

- `endpoint_orderly_restart`：L1/L2 PID 不同，逐字节复用 manifest，并重开同一组库文件，不替换原库。启用带本地监听的 simulation X，S、E、各 B 和 X 同代；每个原 ino 转到对应退役名并在原址出现新 ino。正式读口逐字节返回 cut-1 原收据，input-2 `Committed`，首次接纳前已消费 E/B 标记。
- `endpoint_crash_needs_recovery`：分别对 E、某 B 真杀。不恢复先报缺标记；该域 k、owner、代、最新 cut 不变。正式恢复后子集仅列该域，目标按回执代认领原址，其余在 manifest 代。E 臂核 B 的实际 `--e-epoch` 和权威读取；分别以漏掉已换代域、旧回执、未知/重复域作负控；测试不把 X 的权威代跟随算作通过，归 #2129。
- `endpoint_live_untouched`：存活、SIGSTOP、积压满三臂，L2 无第二写者/监听，原 inode 和 owner 不变；L1 恢复仍能应答；两种非死亡 connect 结果都不能放行。
- `endpoint_unknown_untouched`：无/他人/坏 owner、错身份、普通文件、目录、叶链接、父链接、不合格权限和 M 内两布局，都拒且保留原件。错 UID 臂用与正式路径同一个身份判定函数，输入除 UID 外全匹配的 stat 字段，断言拒绝，不要求 CI 提权。旧合同目录另加 k 空但有 owner 的负控。还核坏锚、旧 epoch 不因端点可退役而放行；ADR 0059 的 layout 拒绝仍断言没有 spawn、init 或建锚。
- `endpoint_race_replacement`：在预核与移动之间以明确同步点换入活 socket、普通文件或父目录。比对保留的原对象及 live 应答；放回时原名被占用不得覆盖；更新 owner 时换入 socket 也不得覆盖，拒绝后它仍应答。另在 E/B 的 bind、listen 后且**首次 `openat` 新条目之前**，让另一同 UID 进程的单链接监听 socket 占据原名；断言第 5 条拒绝，两对象保留、对手仍能服务，owner 仍为 null、关库标记未变，无本域 accept 或认领事件。以能力核验失败作负控，断言不曾进入变更目录的阶段，也不直绑。
- `endpoint_bind_window`：在 bind 后写 bound 前强杀，重启报占用，原 ino、owner(null) 和 E/B 标记不变，无退役名。用不同域锁的两进程调度旧直绑先看到两名为空、新认领再首建 owner(null)、旧直绑先完成 bind 并退出；重启认领者同样拒绝，即使试连该残留会返回 `ECONNREFUSED`。其余三臂：owner 为 null 或旧 bound、且 k 不存在时，两臂均报告 `vacant`，不造退役对象、写妥新身份；在 owner 已写部分字节、尚未完成有效 JSON 时用同步点强杀，重启报占用且保留原 k、半写 owner 和未消费标记，不 accept。
- `endpoint_x_measurement_domain_refused`：只把 `history_simulation.socket` 移到 P、独立 A 的子树、S 族目录三处，X 库及锁均在 M 外；空址一律不建 owner 或 k，预置本锁有效 bound 与已死残留时同样不修改、不退役。不传 M 输入或无法核验时，连空址也不得走旧合同；假定其余域正常，按非关键 X 的实际退出结果核具名诊断，不拿 launcher 退出码当 X 结果。M 外同一配置能认领（与 `endpoint_orderly_restart` 共用正控）。
- `endpoint_x_writer_lock_stable`：悬空末级库链接（含相对目标）在首次 `serve` 即拒绝；目标库、两种可能的锁路径、端点和 owner 均不新建，原链接不动。无链接缺库首启、以及指向已存在库的链接分别核正控：同 manifest 停启锁路径和锁 inode 不变，旧进程持锁时第二进程在写库前被 `StaleWriter` 拒，原代及 owner 不变。
- `endpoint_address_bounds`：长目录短 basename 使公开地址 ≥108 字节而内部合法；短目录长 basename（如 5+95，含分隔符）使 S 的公开地址符合 100 字节旧上限而内部 ≥108 字节。分别核拒绝步、空址不创建、已有 owner/残留不动；E/B 两种超限均不消费标记。覆盖多字节名称与实际 FD 号长度；E/B 两地址各在 107 字节合法边界时仍能从公开 `k` 连接。
- `endpoint_launcher_crash`：只杀 L1 不杀子进程，S/E/B/X 保持原 inode、锁和应答，L2 拒绝。夹具随后只结束自建子进程并等待；E/B 缺标记拒绝，S 带 SHM 首错为 R4，k 和 owner 原样。
- `economic_store_partial_refused`：E 缺、任一 B 缺分别拒绝，点名准确字段，无 init、spawn 或 state_dir 写入；S 预建不影响 E/B 全无的首启；全有不 init。
- `clean_close_negative`：夹具手删、损坏、写错代标记均拒绝；准入拒绝前后不消费标记；恢复丢应答重取同字节，消费标记后崩溃再取原回执不能再次服役。旧合同两臂分别让 E、B 在 `0770` 目录真进程直绑服务，确认无 owner、标记已消费；真杀并等待退出后，夹具只移走它自己创建的残留，再启须报 `StaleWriter：缺本代正常关库标记，须先正式恢复`，不得 bind。受监督关停臂在关库标记事务提交处用测试专用故障注入令提交失败；断言进程非 0、监听已关、库内无标记且无正常关库结果。
- #2077 `b7b79657` 的测试 `orderly_stop_closes_same_s_db_without_claiming_socket_handoff`（函数 :934）改为验证再启成功；`killed_s_is_not_orderly_and_its_socket_remains_for_explicit_recovery`（函数 :1068）在适用目录首错改为 R4，S 原 inode 不变。原 OBS-IN/OUT 的占用对照可用未认领残留，不能用以取消新成功路径。

## 六、受影响票与 blocking 边

| 票 | 承接及边变化 |
|---|---|
| #1323 / #1340 | 不改 Destination、SPEC 或关图门。 |
| #2079 / #1411 | #2079 是 #1411 原生子票，关闭解除子票门，不等于 #1411 已放行；不另接 #2079 → #1411 的 blocking 边。#1411 实施认领与服务拆分、关库标记、稳定锁路径、X 布局硬门及 argv 装配、launcher 两处约束和全链验证。 |
| #2077 / #2082 | 实施前依次先合 #2077 `b7b79657d85c4d9ef830d0422c29f944c7a4cc87`、#2082 `329be34f5a9ca9c2bcc38ae75783304cc654904c` 对应合同；头变须重核行号与接缝。它们是 #1411 的 PR，不新增票边。 |
| #1823 / #1818 | #2079 承接 #1823 的残留归属裁定，#1411 实施并提供 SAFE 读数。#1823 不随本裁定关闭；它继续留作 OBS 现状与 SAFE 复验的证据入口，具名验收证据齐备后由票主销项。不改 #1818 的布局范围或边。 |
| #2128 / #2129 / #2127 | 均挂 #1366，三条各自已有 blocking → #1411，保留。分别承接 S 介质与有效代、X 权威代与 E 来源、路径与提交根。 |
| #2120 / #1363 | #2120 挂 #1363；保留 #2079 → #2120。#2120 原址在线单域重拉与 TB-05 的局部隔离不是同一验收。#1363 的子票门也影响其下游 #1366、#1367、#1368、#1369、#1382、#1391、#1523。 |
| #1376 / #1396 / #1409 / #1417 / #1423 | 保留现有 TB-05 局部隔离链，不增加端点或恢复权限，#1423 → #1411 不变。 |
| #1413 / #1368 | 总验引用相应实施证据；若验证 launcher 存活时原址重拉，取 #2120 的合同，不以整会话重启代替；不新增边。 |
| #2130 / #1365 / #1383 / #1401 | #2130 挂 #1365，不直接阻塞 #1411；X 布局硬门在 #1411 实装，拒绝现场的处置和旧二进制迁移归获授权的运维。TB-09 的真实部署及 X 发送者隔离不变。 |
| #1769 / #1781 / #1845 / #2029 | launcher、X、S 布局、停机和测试夹具写区有重叠，实施按已合基线串接；不改这些票的既有范围与边。 |

## 七、授权引用与受影响代码

本条依 [#1909](https://github.com/Newchanlun/NewChanlun/issues/1909) 代理独审裁定；须绑定实际获审版本才生效。P 类新增本域端点归属和持久关库门，非 UserSigned。实际外部操作不在此授权。

**与旧条文的关系。** ADR 0039:285 的“换代”在本合同内是编排与消费各域已核回执，不给 launcher 写库或升代权。ADR 0039:291 和 ADR 0038:60 的 checkpoint 恢复描述不再作为本合同 E/B 原库启动顺序或自动升代依据，实装按第 9、12 条；不把真实外效视为未发生。ADR 0038 的离线确定性回放与 seek、ADR 0039:290 的 X 指纹禁止发送门和真实 X 换代合同不变。需要在生产中正式恢复 E/B 时，由另行获授权的域运维在原域已停的前提下，用对应域 bin 的 `recover` 或 `recover-named`；域 bin 自己取同一写者锁，审计与换代在本域完成。launcher 不代为执行。S 的强杀恢复归 #2128，场所 X 的恢复按 C09.8 及 #1401。

ADR 0059 第 6 条的“不比较 `s.socket`”作为 launcher 静态布局检查范围仍保留。该条“残留一律在 S 参数期拒绝”及“清理归 #1823 调查”的理由由第 3、5–7 条取代：M 内继续按旧合同，有资格的 M 外残留只允许持锁域退役；正常 bind 仍晚于 driver open。第 3、4 条的 E/B 布局预检不变。对 X，第 3 条补上 `history_simulation.socket` 的域内 M 外硬门；第 4 条取代 0059 对悬空库链接可先取链接名锁、再取目标锁的现状描述，0059 对库与锁的布局拒绝范围不因此放宽。

受影响代码（默认以 `b9d898dccf46c2a716115eaa1215bc39c458a959` 计）：

- `rust/src/session_transport.rs:50–81、:617–680`：锁、监听生命周期与认领/接纳拆分。`:618、:648` 关于监督器、PID 的旧注释由本裁定取代。#2077 同文件 `:702–728、:735–755、:797–809` 对应停止字节、监听器与 join。
- `rust/src/bin/s_session_v3/writer_cli.rs:267–275、:372–395、:779–861`，`admission.rs:19–65、:324–343`、`driver.rs:171–185`：S 预筛、正式锁和 bind；`admission_provider.rs:231–233`、`audit_owner.rs:1198` 保持原门。
- `rust/src/economic_session/service.rs:1515–1595`：E/B 锁、audit 与 bind。#2077 同文件 `:1521–1568`（标记门、消费及服务返回后标记）；#2082 `rust/src/economic_session/store.rs:659–663、:786–835、:967–1084、:1694–1743`（init、逐键审计与恢复），`recovery.rs:112–154`（当前回执与同事务），`service.rs:905–926、:1619–1635`（E 来源代与 serve 自身代）。
- `rust/src/bin/production_session.rs:276–448`；#2082 同文件 `:249–342、:351–425、:553–584`：库存在性、自身恢复计划与有效代装配；正式 X argv 同时传 S 的两个布局输入。
- `rust/src/bin/x_execution_session.rs:118–162、:178–212`、`rust/src/history_simulation/runtime.rs:42–56、:815–831、:866–897`：X argv、M 门、库锁路径、冻权威配置、启动审计与受核本地 bind。
- `rust/src/economic_session/finance_transport.rs:98–109`：客户端仍使用公开 `k`，保留原地址校验；认领另核自己的内部 bind 地址。
- `rust/tests/production_session_entry.rs`：本 ADR 验收及 #2077 的两个现有测试函数（`:934、:1068`）。
- `s_session/s_service_control.py:505–528、:727` 与 `s_session/economic_service_control.py:83–95、:126–132`：按 ADR 0039:278、:286，两者不是正式入口，不能用于本合同管辖的生产会话端点目录，不改其独立用途或把删名逻辑移植过来。调用新版 E/B bin 时仍受第 9 条：独立 serve 不写正常关库标记，stop 后再 start 须先正式 `recover` 并使用有效代。
