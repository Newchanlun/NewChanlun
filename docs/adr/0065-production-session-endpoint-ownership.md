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

1. **域锁定归属，改名不删除，库内记正常关库（采用）**。owner 记录端点归属与对象；E 和每个 B 的库内标记说明是否可在当前代重新服务。锁只属于本域；整会话另只读核各域共同完成的 checkpoint，不把这一核验变成跨域写锁或端点归属证明。
2. **重启发新端点**。绕开旧名字的处置，但会改变原布局和已冻结的引用，不能交付本票要求的同一 manifest 原址续服。路径进入提交根的取舍另归 #2127。
3. **独立发布身份或跨代保留监听 FD**。独立身份换全新监听器可行，但需要另设对名字的排他部署权限；不为原址续服增加部署角色和证明链。跨代持有同一 FD 会把旧监听队列交给下一代，Linux 和 Darwin 的[原件](https://github.com/Newchanlun/NewChanlun/blob/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation/EVIDENCE.md)都观察到了这一点。本裁定不转交监听 FD，不设模式、可调字段或放行开关。

## 四、裁定

### 端点

1. **唯一写者。** 对 S、E、各 B 以及带本地监听的 simulation X，端点名 `k` 只由持有本域实际 `<db>.writer.lock` 的进程 bind 或退役。guard 在 bind 前取得，覆盖整个服务期以及监听 FD 关闭、E/B 关库标记事务提交（如有）和域库关闭，最后才释放。正式 S driver 的 WriterScope、E/B CLI 的 guard、X 的 guard 已经先于现行 bind 获得；#1411 将认领与开始接纳拆开，不给 transport 新建一把锁。`b9d898dc` 的通用 acceptor 将监听器交给线程却不显式 join；沿用 #2077 的 join，并在所有返回路径保证上述关闭顺序。`production_session`、客户端和其他域不创建、不移动、不删除 `k`。
2. **退役只认两项内核证据。** 取得按第 4 条证明与前代连续的同一锁文件对象的内核锁，才证明前代已不持有这把写者锁。锁文件在部署使用期间不得替换、改名或删除；同名新对象取锁成功不能替代连续性证明。获得锁不证明前代 PID 已消失（[#1895](https://github.com/Newchanlun/NewChanlun/issues/1895#issuecomment-6727386306)），也不证明真实场所发送者已隔离。退役残留还必须对钉住的对象作 `AF_UNIX/SOCK_STREAM` 非阻塞 connect，且只接受 `ECONNREFUSED`。锁冲突沿用 S 的 `StaleWriter：S独占进程锁不可得`（保留 admission 包装）与 E/B/X 的 `StaleWriter：{domain_name}独占进程锁不可得：{e}`。不得等待或终止旧进程，不以旧 PID、boot ID、时间、日志或 launcher 事件放行。第 5 条的 peer pidfd 只用于证明**本次**监听器身份，不用于退役。
3. **先判布局、合同和地址，再动端点。**
   - **X 的端点 M 外硬门。** 带本地监听的 X 核本次加载并交给 runtime 的 `history_simulation.socket`（不是场所 `endpoint` 或权威读口）。端点命中 M，或参数缺失、目录或物理别名不可核，X 非零退出 `InvalidDomain：simulation X 监听端点须在 S 测量域 M 外`，附冲突字段与路径或不可核原因。只读门在 X 取锁、开库、`persist` 前执行；实际 bind 前重核两侧布局与已钉目录。拒绝不建 owner、不移动、不 bind，也不走旧合同。不读取 S 进程状态或等 S 就绪；不带本地监听的 X 不过端点门，仍过第 4 条的库布局门。该门归 #1411 实施，不等 #2130。
   - **E／各 B 的端点 M 外硬门。** launcher 在 `load_manifest` 用 ADR 0059 指定的 `e.socket` 和各 `chongs[j].socket` 执行下述统一判定，早于目录变更、任何 init 或 spawn（含恢复回执核验子进程）。命中 M 或不能证明 M 外，按 ADR 0059 报 `InvalidDomain`，点名端点字段与 S 冲突字段或不可核原因。E/B `serve` 也以第 4 条的同一对 S 布局参数初核、在动端点前用实际目录重核；直接调用同样适用。每次拒绝均不创建 owner、不退役、不 bind，不得回退到旧合同；不做端点操作的 `init`／`recover` 只过库布局门。
   - **S、E、各 B、X 共用 M 判定。** 用同一对 S 布局输入按 ADR 0059 第 1–4 条推导 P、S 族及 A，核 socket 目录项父目录 `Q₄` 与解析末级链接后可能 bind 的父目录 `Q₅`。Linux 还在 launcher 子进程共同继承的挂载视图（直接启动则用本进程视图）钉住 P、A、按族名在 P 中枚举的现有族目录及 `Q₄`、`Q₅`。P、A 尚不存在时，只接受从已核祖先证实确无条目的尾段，端点操作前重验。以目录 FD 的 `(dev, ino)` 比较：Q 本身与 P 同对象，或 Q 本身或任一祖先与 A 或某个族目录同对象，都命中 M。P 的普通非族子目录不因位于 P 下就变成 M。
   - **Linux 挂载链同样必核。** 从目录 FD 逐级打开 `..` 至进程根，以 FD 的挂载 ID（`statx(STATX_MNT_ID)`）对照 [`/proc/self/mountinfo`](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)；挂载 ID 判边界，不参与物理对象相等比较。Linux 的 [`..` 可越出挂载根](https://man7.org/linux/man-pages/man7/path_resolution.7.html#Mount_points)，不能沿别名的可见父目录推断挂载源的祖先。核对两侧经过的挂载记录与 FD，只接受可证明物理祖先的挂载链：若经过 `root` 非 `/` 的子树挂载，或经过在同一视图中有多个整文件系统挂载（同 `major:minor`、`root=/`、不同挂载 ID）的文件系统，即不可核。后者也拦住把 A 或族目录下独立文件系统的整根 bind 到 M 外的情形。挂载记录缺失、文件系统的物理身份不可核、族条目不可核或两次核验间对象或相关挂载记录变化，同样不能证明在 M 外。不得把两个 mount ID 不同当成物理目录不同。
   - **还要查从外向 M 的挂载。** 从同一份 `mountinfo` 枚举挂载点等于 P、A 或位于其后代的所有挂载项（含嵌套挂载），按上面的测量范围确定落在 M 内的挂载点：P 本身、A 树、S 族树。在打开并核实的可见挂载点取得挂入物的实际对象和文件系统内 `root`，不把 `mount source` 字符串当成源路径。对目录挂载，若源根的 `(dev, ino)` 等于候选目录或其任一物理祖先，候选目录就在挂入 M 的源子树中；对文件挂载，比较实际操作的叶身份（端点或第 4 条的库、侧件、锁）。嵌套挂载逐项比较，不能只查 A 本身。不能确认挂载记录、可见挂载对象及候选物理祖先是否相交，或重核发现这批记录变化，均不能证明 M 外。这样即使写者走原外部路径、不经过任何 bind 边界，也不会遗漏被 A 递归测量的同一子树或文件。
   - **认领资格。** 仅 Linux，且 `openat2(RESOLVE_NO_SYMLINKS)`、同目录 `renameat2(RENAME_NOREPLACE)`、`O_PATH`、`/proc/self/fd` 可用。`k` 为绝对路径，逐段无 `.`、`..`，以无链接的 `openat2` 将其父目录打开为可 fsync 的目录 FD `d`。`fstat(d)` 的属主是 euid，组和其他位均不可写；`fstatfs(d)` 的类型限 ext 家族、XFS、Btrfs 或 tmpfs。前三种是本合同的本地持久文件系统；overlayfs 不证明底层位于本机。S 在只读预筛和持锁选端点合同两个阶段都用上述 M 判据，后一次核实际目录 `d`；命中 M 或不能证明在 M 外时，只适用 driver open 后的 S 旧合同，不采用 X 的退出语义。
   - 通过适用的硬门后，仅因认领资格不适用才走旧端点合同（S 按上条保留旧合同）：`k` 有对象就按占用拒绝；`k` 空但有任意 `<basename>.owner` 条目，报 `TransportUnavailable：旧端点合同不接管已有 owner`；只在两个名字均不存在时 bind。不建 owner、不动残留；无法核验不视为不存在。**两条路径均须过 E/B 标记门，并在 bind 成功后、首个 accept 前消费标记。**
   - **E/B/X 两条合同都绑定已核目录。** E、各 B 和带本地监听的 X 从原始 `k` 打开父目录，不允许任何父路径分量为符号链接；不能先 canonicalize 后只核解析结果。Linux 用 `openat2(RESOLVE_NO_SYMLINKS)` 钉住目录 FD `d`，保留到 bind；M 门、目录项检查及绑定用同一目录对象，以 `/proc/self/fd/<d>/<basename>` bind，不交回 `UnixListener::bind(k)` 重新解析。bind 前无链接重开公开父目录、核与 `d` 同对象和挂载证明，首个 accept（E/B 消费标记前）再核公开路径通往本次绑定。父路径有链接、对象不符或不能证明固定目录绑定及 M 外时，按本域 M 硬门拒绝；非 Linux 须有等效证明，不以旧直绑替代。
   - **公开地址先核原始字节，两个地址分别量长。** 在任何端点变更前，按公开 `k` 的原始路径字节（不使用会规范化路径成分的 `Path::file_name`）拒绝空路径、内含 NUL、尾随 `/`、空末段以及末段恰为 `.` 或 `..`；不删除、替换任何字节。Linux [UAPI](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/un.h#L7-L12) 的 `sun_path` 为 108 字节，留一个字节作终止 NUL，公开 `k` 与内部绑定地址各自最多 107 字节。认领以及 Linux E/B/X 旧合同都在端点变更前用实际持有的 `d`（含其十进制 FD 位数）校验内部地址。S 的原 100 字节公开上限及既有参数首错优先；其他非法地址报 `TransportUnavailable：socket地址长度或内容非法：<公开地址|内部绑定地址>`。不改端点目录，不消费 E/B 标记，不降级、不截短、不改 `k`。开始认领后，`NOREPLACE` 不支持或任何核验、写入失败均拒绝，不回到直绑。
   - **认领先核监听器证明可用。** 对已选认领路径的启动，用本进程 `socketpair` 和 `pidfd_open(getpid(), 0)` 只读验证第 5 条所需的 `SO_PEERPIDFD`（Linux 6.5 起提供，按能力判）、`/proc/self/fdinfo` 和比较规则可用，才可建／改 owner、退役或 bind；能力不可核即拒绝，不回到直绑。
4. **先定库与侧件，再取实际库锁。** S 使用原准入 lease 绑定的规范库路径，保留原 R4 测量门。其余域在 `process_lock` 的共同路径解析处，先规范化父目录，再用不跟随末级链接的 stat 区分真正缺叶和已有条目。只有父目录可核、叶确无目录项，才用规范父目录拼原 basename；有条目则必须得到整个库路径的规范路径。末级链接无法解析（含悬空或成环）及其他不可核错误均拒绝，不以链接名代替目标。规范路径接 `.writer.lock` 后即为持锁代码实际打开的绝对路径；同一次启动用已选定的规范库路径打开 SQLite，不再从原参数重新解析。上线前若曾让旧二进制用悬空链接启动，须由获授权运维先确认旧写者已退出，再启新版；目标现在存在不能证明旧写者拿的是目标锁。该迁移处置归 #2130。
   - **E/B/X 的库、侧件和锁同样必须在 M 外。** launcher 保留 ADR 0059 的 Q₁–Q₃ 路径预检，并在同一只读阶段对这些目录、规范主库、实际锁及 `-wal`、`-shm`、`-journal` 套用第 3 条双向挂载证明：目录比对祖先，现存文件还核叶身份，确无叶也要核将创建它的父目录。反向挂入 A 或族树的库目录、单文件挂入的主库／任一侧件／锁，哪怕配置全走原外部路径，一样拒绝。并发写域在取锁（含建锁）、任何可写开库或创建前初核，在持锁后、可写打开前以实际 FD 重核；命中或无法证明 M 外报 `InvalidDomain`，点名库或侧件／锁字段及 S 路径或不可核原因。正式 launcher 给所有写入口传同一 manifest 的 `s.db`、`s.admission_job_limits` 原值为 `--s-db`、`--s-admission-job-limits`，不增加 manifest 字段，不传判定布尔值。本合同的直接写入口同样需要两项输入，包括 E/B init、正式恢复和无监听 X；缺参在建锁或可写打开前拒绝，只读命令不因本条增加参数。
   - **库及 SQLite 侧件不得有硬链接别名。** 规范化不能合并硬链接。E/B/X 创建或获取锁前，对规范主库以及同目录的 `-wal`、`-shm`、`-journal`，只接受确无条目或经无链接打开及 `fstat` 核实的单链接普通文件（`nlink == 1`）；已规范化的主库参数链接可用，侧件链接一律拒绝。持锁后、SQLite 打开或创建前重核钉住的父目录、存在状态、对象身份和链接数；新开文件也须符合相同条件。无法排除别名或证明是所核对象即拒绝，不尝试用另一条库路径。X 的所有 `serve`（含不监听的 profile）都过库路径与别名门，不把检查留到 `persist` 或 bind。S 保留原单链接检查及 WAL/SHM 准入禁项。
   - **Linux 同时排除文件挂载别名。** S/E/B/X 创建或取得写者锁前，钉住规范库父目录并按第 3 条核挂载链，对主库和每个现存 SQLite 侧件相对该 FD 无链接打开叶，检查叶 FD 的挂载 ID 与其父目录 FD 一致，并与 `/proc/self/mountinfo` 对照。叶不得是单文件挂载点（即使 `dev/ino` 相同且 `nlink == 1`）；父目录链也不得经子树挂载或同一文件系统的多个整根挂载取得另一条路径。确无叶时，仍须核实父目录可用于原址建库及创建侧件。锁后、可写开库或建库前，无链接重开规范父目录及相关叶，与原 FD 比较 `(dev, ino, mount_id)`，重核挂载记录和确无条目的叶；不得从原参数重新解析。记录缺失、对象或挂载链变化，或不能排除同一底层文件经不同挂载路径被当作两套库／侧件布局，均拒绝。S 的挂载前置门在 WriterScope 取得写者锁前执行，不能用其端点旧合同或 R4 跳过。
   - **SQLite 实际打开也受同一目录 FD 和对象表约束。** Linux 写者须在打开连接前注册并用 `Connection::open_with_flags_and_vfs` 显式选择受控 Unix VFS，绑定规范库父目录 FD、主库 basename 和三种侧件的既有对象 FD／确无叶状态；锁、目录和对象表保留至 SQLite 完全关闭。现行 `store.rs:534` 的 `open_with_flags` 已允许按名创建，:541 紧接着设置 WAL；仅传 `/proc/self/fd/<dir_fd>/<basename>` 或连接返回后再 stat 不够：bundled SQLite 的 `unixFullPathname` 可重解析路径，`unixOpenSharedMemory` 在 `xShmMap` 内另开 `-shm`。
     - `xFullPathname` 保留已登记的逻辑名，不交回通用路径解析。沿用仓内 native VFS／Unix 系统调用适配的接缝，保留 SQLite 原有锁、WAL、共享内存及同步语义（额外的钉住 FD 不得在 SQLite 仍持 POSIX 锁时关闭）。主库、WAL、journal 的 `xOpen` 和 SHM 的实际打开都在 VFS 内先核公开规范父目录仍与原 FD 同对象，再相对该 FD 开叶；之后即使父路径换名也不会打开新目录。已有文件用 `openat2(RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV)` 无创建、无截断打开，在把实际 FD 交给 SQLite 前核 `dev/ino/mount_id`、普通文件及单链接，与仍钉住的对象相符才可用；不能绕去复用未核 FD。只有已登记确无叶且本次允许创建时才以 `O_CREAT|O_EXCL` 建立并登记新 FD，抢占或不符即拒绝，不认领竞争者条目。每次重开同样核验，早于写、truncate、可写映射、改属主或 `PRAGMA journal_mode` 所触发的 I/O。
     - `xAccess`、侧件清理和目录同步也只用同一目录 FD。按名创建／删除的前提是部署已将库目录条目的变更权隔离给本域持同一锁的写者（运维只能在停服并另获授权后改动；`0700` 本身不隔离同 UID 进程）；不能把核 inode 后对可竞争目录调用 `unlinkat` 算成安全清理。VFS 只删除自身对象表记下且仍相符的 SQLite 侧件，并按原 SQLite 合同同步目录。未能核实目录隔离，或任何实际 FD／映射／按名操作无法受控，报 `StorageUnavailable`；不退回默认 VFS，不在未核对象上执行 WAL 设置或其他写入，不继续处理业务或端点。
   - **锁叶不跟随链接。** S 沿用现有 WriterScope，E/B/X 沿用 `process_lock`；在已核的规范库父目录下以 `O_NOFOLLOW` 打开实际锁叶，`fstat` 须为 euid 所有的单链接普通文件。不写、不截断锁内容。持锁后以 FD 及不跟随链接的目录项复核是否同一对象；在退役、bind 前再核。拟监听的 `k` 如已有 owner 条目，不因锁叶缺失而新建锁；取得锁后、打开可写库前，必须用实际加锁 FD 逐项核对 owner 记下的锁路径及 `lock.{dev,ino,ctime_ns}`。身份不符或不可核即拒绝开写、退役与接管，保留现场交 #2130；新同名锁即使可取得，也不准更新 owner 来承认它。
   - **一个 owner 文件。** `<basename>.owner` 位于 `d`、权限 `0600`；规范 JSON 恰有六键：`schema="endpoint-owner/1"`、`socket=k`、`writer_lock`（实际锁路径）、`lock`（实际锁 FD 身份）、`bound`、`retiring`。`lock` 和非 null 的 `bound` 恰含 `dev`、`ino`、`ctime_ns`（十进制字符串，无损比较）；`bound=null` 表示尚无已证明的绑定。`retiring` 为 `null` 或与非 null 的 `bound` 对应的唯一退役 basename（第 6 条）。普通文件、euid、单链接、模式 `0600`、规范解析且 schema、socket、锁路径及锁身份逐项相符才算“我”。读时钉住条目并核类型，不跟随目录内链接。持锁者首建用 `O_CREAT|O_EXCL|O_NOFOLLOW`，写完 fsync 文件和目录。更新只写同一个已钉住、复核为普通文件的 FD（从 `/proc/self/fd` 重新打开，核 dev/ino 后才写和截断），并 fsync；写前、写后核 owner 名仍对应该 inode。不得按目录名覆盖、删除 owner 或用临时文件覆盖目标，即使有人把 owner 名换入 socket 也不能销毁它。**原地更新不是原子的。** 进程中途被杀可留下不可解析的 owner，此时按“非我”拒绝并保留，交 #2130；不使用备用 owner。这里以可能需要人工恢复换取不按名覆盖 socket。
5. **先证明新目录项属于本次监听器。** 持锁且本域启动门均过后，先过第 6 条的退役前置核验，再用下表决定是否 bind。`ENOENT` 才算无；其他错误是不可核验。认领操作相对 `d`。bind、listen 成功后，尚不 accept；用 `openat(d, basename, O_PATH|O_NOFOLLOW)` 钉住候选目录项 `p`，核其为 euid 的单链接 socket。仅按名打开后再复核同 inode，不能证明它由本次 bind 创建。
   - **按 inode 连。** 每个正式域进程在证明前只对本次新建的一个 `AF_UNIX/SOCK_STREAM` FD 调 `listen`，不接收或交出监听 FD，也不启动 acceptor。用另一个本地非阻塞 stream FD connect `/proc/self/fd/<p>`，只接受立即成功。Linux procfs 的 magic link 返回 `p` 的 `f_path`（[`proc_fd_link`](https://github.com/torvalds/linux/blob/v6.12/fs/proc/fd.c#L175-L192)）；Unix pathname connect 按该路径的**内核 inode 对象**查找监听 socket，而非按原字符串匹配。成功连接会把监听端在 `listen()` 时记录的进程对象（`struct pid`）复制到探针端，不等 `accept`（[`unix_find_bsd`、`unix_listen`、`unix_stream_connect`](https://github.com/torvalds/linux/blob/v6.12/net/unix/af_unix.c)）。
   - **核监听进程。** 从探针的**连接发起端**取 [`SO_PEERPIDFD`](https://github.com/torvalds/linux/blob/v6.12/net/core/sock.c#L1856-L1885) 返回的 pidfd。保持它和 `pidfd_open(getpid(), 0)` 的本进程 pidfd 打开，从同一个已打开的 `/proc/self/fdinfo` 目录分别读两者的 `Pid:`，要求各恰有一个可解析的正整数且相等。内核只对仍有任务的 pidfd 报告可见 PID，已退出并回收的对象报 `-1`，不可见报 `0`（[`pidfd_show_fdinfo`](https://github.com/torvalds/linux/blob/v6.12/fs/pidfs.c#L71-L94)）；因此旧进程退场后，即使其监听 FD 仍被别的进程持有，重用同一数字 PID 也不能冒充本进程。只有本次唯一监听器能使比较成功；`SO_PEERCRED` 的数字 PID、UID 或 `getsockname` 都不足以替代。
   - 探针不发送帧，取证后关闭；今后若由接纳循环取到该连接，按无完整帧关闭，不交 handler。证明使用受信 Linux 路径解析；可改写该 syscall 的特权策略不在此合同内。证明失败（包括 `EAGAIN`、无法核验 pidfd 或不是本进程）关闭监听、拒绝，保留现有条目，不写 `bound`、不消费 E/B 标记、不 accept、不走直绑。
   - **记证。** 保持 `p` 打开，按原路径无链接重开父目录比 `dev,ino`；再不跟随链接核 `d` 下的名字仍指向 `p` 的同一对象且类型、属主、链接数仍合格。fsync 目录后，把 `p` 的身份持久写入 `bound`；接纳前（E/B 在消费标记前）重验父目录、条目及已记录的三元组。不符则关闭监听、拒绝，不删除任何对象。即使有人在初次 `openat` 之前换入了同 UID、单链接 socket，探针也不能把它认证为本次监听器；后续改名不能把已钉住并证明过的 inode 换成另一个对象。`bound` 证明的是本次创建的对象，不是对末次重验以后名字仍不变的承诺；可用性仍受第 15 条约束。`action` 取下表。

   | owner | k | 动作／action |
   |---|---|---|
   | 无 | 无 | 首建 owner（`bound`、`retiring` 均为 null），bind 并记对象／`fresh` |
   | 我，null，无退役意图 | 无 | bind 并记对象／`vacant` |
   | 我，有身份，无退役意图且对应退役名确实不存在 | 无 | 写 null，bind 并记对象／`vacant` |
   | 我，有身份 | 有 | 按身份退役，写 null，bind 并记对象／`retired` |
   | 我，null | 有 | 拒绝；保留 owner 和原对象，交 #2130 |
   | 无 | 有 | 拒绝；原对象保留 |
   | 非我或不可解析 | 任意 | 拒绝；原对象保留 |

   `bound=null` 不证明现有 `k` 属于本域。旧合同的两次空名检查与新合同的 owner 首建不互斥；不同域锁也不序列化两者的 bind。即使旧直绑的赢家已退出、试连会报 `ECONNREFUSED`，也不得凭 null 退役对象。入表时 `k` 存在，表内拒绝或退役预核中的类型、UID、链接数、身份或试连不符，都按占用报错，不再探查能否直绑。S 保留 `TransportUnavailable：socket路径已占用`；E/B/X 保留 `TransportUnavailable：socket绑定失败 {e}`，占用用 `EADDRINUSE`（Linux 已见原文 `TransportUnavailable：socket绑定失败 Address already in use (os error 98)`）。空址但 owner 非我：`TransportUnavailable：socket名字已由其他写者锁认领`（旧端点合同用第 3 条的专用错误）。S 不可 stat 时保留 `TransportUnavailable：socket路径不可核验：{e}`；S 原有空参数、长度和 `TransportUnavailable：socket父目录须已存在` 错误不变。不能确定路径状态，或监听器证明、改名、持久化、目录重验失败时，返回 `TransportUnavailable：socket认领失败：<步骤>：<原因>`；bind 返回原来的错误。不重试，不放行。退役预核按占用拒绝时不另报一次试连错误。
6. **退役只移不删，验证完成前空址不等于 vacant。**
   - **入表先核旧退役名。** 已有非 null 的 `bound` 时，对应退役名必为 `t=<basename>.retired.<bound.ino>`。无论 `k` 是否存在，相对 `d` 不跟随链接检查 `t`；若存在则钉住对象，核类型、属主、链接数和 `(dev, ino)` 是否与旧记录相符（改名后的 ctime 不可用于比较）。`t` 存在、不可核，或 owner 有非 null 的 `retiring` 时，均视为未确认退役，保留 `k`、owner 及退役条目，报告两名和核验结果，拒绝启动并交 #2130。即使重启后读到相符的 `dev,ino`，也不能补做上次仍持有 `p` 时才成立的连续性证明。不得清空 `bound`、自行放回或进入 `vacant`；只有 `retiring=null` 且对应 `t` 确实不存在，空 `k` 才可用表中旧 bound 的 `vacant`。
   - **先持久记意图，再移名。** 域用 `openat(d, basename, O_PATH|O_NOFOLLOW)` 钉住 `p`，其 `fstat` 须为 socket、euid、单链接，身份三元组与 `bound` 相等。对 `/proc/self/fd/<p>` 非阻塞 connect，成功、`EAGAIN`、超时或其他错误均拒绝；只有 `ECONNREFUSED` 才可保留旧 `bound`，按第 4 条把 `retiring=t` 写入并 fsync owner，然后以 `RENAME_NOREPLACE` 从原名移到 `t`。目标被占用或改名失败即拒绝。
   - **持原 FD 验证后才清意图。** 保持 `p` 打开，改名后对 `t` 不跟随链接，核类型、属主、链接数及 `dev,ino` 与 `p` 相符；`ctime_ns` 只在移走前比。不符（含无法核验）即尝试以 `RENAME_NOREPLACE` 放回原名并拒绝；原名若又被占用或放回失败，保留现场并报告两名与错误。失败不清意图，交 #2130。只有同一次启动在持有 `p` 时核验成功并 fsync `d` 后，才将 `bound`、`retiring` 一并写为 `null` 并 fsync owner，再 bind。完成此步骤的退役对象不参与下次的身份判断；停在改名与这次提交之间的重启一律按本条前置核验拒绝。
   - **不按名 unlink 的范围。** 正式域和 `production_session` 不覆盖、不 unlink 本 ADR 管辖的 S、E、各 B、带本地监听的 X 的写者 socket。S bin 的 `financial-serve` 是独立的财务只读监听器，不认领写者端点，保留自身原停机和失败清理合同。财务监听必须用专用目录：部署发放启用配置前，核实其实际目录树与所有写者端点目录树不重合、互不包含，且路径不能经符号链接或挂载别名交叉；任何一侧均不得使用或重指另一侧的目录或端点。不能核实即不启用该财务配置。这是部署隔离前提，不给 launcher 新增财务监听或清理职责。
7. **S 预筛只读。** `ServeOptions::parse` 原 socket 检查处，以本域配置的锁路径和 M 调同一认领判定的只读部分。可以开目录和钉住对象、试连，不创建文件、不改名、不绑定、不把预筛通过当成资格。预筛拒绝沿用第 5 条的 S 首错；预筛过后仍走原 admission，取得 WriterScope 的写者锁后在可写开库前核第 4 条锁对象，直到端点操作前仍须持锁重判。E/B/X 无参数期的 socket 预筛。
8. **停机不改名字。** #2077 有序停止先收监听再关库；有序停止不修改 `k` 或 owner。旧监听关闭后，下次使用新监听器，不继承上一代排队连接。

### 再服务前提

9. **E/B 各自记正常关库。** 本域 SQLite `meta` 新增键 `clean_close/1`，值恰为 `{"writer_epoch":"N"}`，N 为持久正整数代的十进制字符串。不改表、schema 或业务提交根。
   - 只有三处写标记：init 在写代 1 的同一事务；正式 `recover` 和 `recover-named` 经 `advance_recovery` 在升代的同一事务写新代（重取已存在的同请求回执不重写标记）；`SupervisedStdin` 收到规定字节、服务循环 `Ok` 返回（监听已关且不再执行 handler）后，由本域在关库之前用同一连接提交本代标记。末项提交失败非 0 退出，不报告正常关库。以事务已提交为界；即使在提交后、进程退出前被杀，也已无业务 handler 或监听。`writer_closed` 只是 launcher 观察量，EOF、SIGTERM 或 `Standalone` 不写正常标记。
   - 任一 `serve` 持锁、`check_epoch` 和全域 `audit` 通过后，先验标记。缺失、不可核或 N 不等于持久代，返回 `StaleWriter：缺本代正常关库标记，须先正式恢复`，不 bind、不改权威库内容、不动 `k`。过标记门后才进入端点路径。**无论经认领表还是经旧合同直绑，bind 成功后、首个 accept 前，都必须在一个事务中删除标记并提交。** 走认领表须先完成第 5 条证明、持久记录和末次重验；证明失败不得借旧直绑消费标记。删除须恰命中已核的这条标记，失败即关闭监听、非 0 退出，不 accept。此前不写本域业务或启动 meta；SQLite 本身的侧件及锁不算业务写入。旧库没有标记，一律先过正式恢复；独立 serve 消费标记后退出不补写，下一次 serve 须先正式恢复。
   - 库曾由不识该标记的二进制开服，或本次库来自备份时，旧标记可能仍匹配代。已获授权的域运维须在前滚或恢复备份后先执行正式恢复，不能把看起来有效的标记当成本次关库证明；程序无法仅凭库内两值发现这种外部替换。按 #2130 处理，操作权限或恢复条件不满足时不启动。
   - **为什么干净停机不升代：** C09.9 要 E 从持久 Recorded/Pending、证据、前沿、责任与 Released 的原状恢复，不准拿旧 Open 当起点；B 必须重新核原归属应用。当前代匹配和全域审计重验持久原件、逐步重放、引用和物化状态，再通过关库标记确认同代上一轮已停止处理，合 IC:62 的“先恢复本域未决状态、引用完整性和 writer 代际”。这里恢复的是已提交状态及其引用，未决责任仍按原身份保留，不把开服本身当作一次换代。无标记时，审计通过也不足以从旧 Open 续跑，必须显式正式恢复；C09.11 的升级及回退合同仍适用。#2082 的回执核当前代不核“上次 serve 已干净关库”，故不能替这个门。
10. **S、X 保留启动门。** S 仍核 R4 介质、未完成 Begin、epoch 和既有准入，不接受带 SHM 的介质；保留 `UnsupportedWalShmJournalCombination` 与需要 recover 时的 `StaleWriter：未完成Begin须先由监督器recover` 原诊断（该字样不授予新角色）。S 真实恢复后的介质再准入及有效代交接归 #2128。X 不加标记；过第 3、4 条的只读前置检查后，本地 simulation 仍先锁、核 epoch 不降、冻结 profile、审计，再 bind。正式 X 把已核的目录 FD、监听地址与布局输入交给 runtime 的绑定入口，不能绕回只凭 profile 路径直绑的旧调用。不提供本地监听的 profile 不过端点门，但仍须过第 4 条的库及锁前置门。C09.8 的旧 X 与仍可发送的子进程退出证明、发送门及已发请求责任，归 #1401 的真实场所路径，不由本地端点认领替代。
11. **拒绝后不换路。** 任一域任一门拒绝，本次域启动非 0，不另找路径、旧证明或宽判据。下一次从该域的持久状态重新判定。**X 在全员启动放行前是必备成员，放行后才按现行非关键域监督。** 整会话首启或续服尚未放行时，X 未通过准备核验（含 X 本地监听被 M 门拒绝）与 S/E/B 未通过同样中止本次启动；回收限本次拉起的子进程。已放行后，X 退出只记录，不回收 S/E/B；关键域失败仍按现行监督回收。端点门已完成的动作（例如已复核的退役）不因后续 bind、目录重验或持久化失败回滚；只有第 6 条移错对象才尝试原样放回。标记未消费的失败不会把库判为崩溃。端点和库输入都不可核的拒绝态交 #2130。
12. **launcher 只装配。** 第 3、4 条的 E/B 端点及 E/B/X 库布局预检先于写 `state_dir`、init 或任何 spawn。通过后、上述写入或拉起之前，先核 E 和全部 B 的库存在性：全无才可能走原 E/B init（须通过第七节首启重验）；全有不 init；部分存在即 `InvalidDomain：E/B 域库部分缺失：<缺失 manifest 字段>`，点名 `economic.e.db` 或 `economic.b[i].db`。不可读路径或悬空链接不算缺失。S 首启可已有初始库和签锚，X 首启仍自建。整会话续服先只读核共同 checkpoint；首启和续服均按第七节进入全员持锁准备，首启 init 不在准备放行前执行。#2082 的 `--economic-recovery-plan` 键集从 E/B 全集改为其子集（含空集），仍拒重复域、未知域及坏计划，按原 `current-recovery` 在拉起写者前核验每条且仅每条提交的回执。没条目的域用 manifest 代；不能从回执拒绝回退到 manifest。B 的 `--e-epoch` 一律取 E 有效代（有条目取已核回执，无则取 manifest）。E/B 持锁在 serve 再验自己的当前持久代（旧代报 `StaleWriter：持久epoch不等于获准写者`）；B 真读 E 权威时再验 E 的库持久代。恢复回执子集不改变共同 checkpoint 的组成。launcher 不恢复、不升代、不读 owner、不碰端点。
13. **域的写权只到本域。** 域用自己的锁、owner、库及介质决定端点归属和本域可恢复性，不读其他域的退出记录或库。整会话续服由 launcher 只读汇总本域证据，不把其他域的结果当成本域写权；独立域恢复不能宣称整会话已就绪。launcher 存活时只重拉一域、当健康域仍持锁时怎样取回执及更新来源代，归 #2120。#1363 下现有 TB-05 试验和监督语义不变、不在此裁。
14. **launcher 已退而域仍活。** #2077 的控制管道 EOF 不停机。孤儿照常服务、继续持锁；同址同域新启动被 S 预筛或域持锁门拒绝。已退出的域按第 5、9、10 条重判；宿主重启也是逐域重判，不把重启当关库。产品不终止孤儿；测试夹具只结束它自己拉起的进程，并等退出。实际运维出口是 #2130。
15. **授权与边界。** 本裁定不授予终止进程、unlink、改属主或权限、账户、凭据或部署启用。拒绝态清场、目录整改、结束孤儿与退役对象清理归 #2130，须另外取得运维权限，runbook 建立前保持拒绝。ADR 0039:286 将部署隔离留给 TB-09；同 UID 不守合同的进程（含不识标记仍写同库的旧二进制）不得进入共用库目录，端点名字被此类进程改动也不保证可以继续服务。写者端点不按名销毁；发现移错对象时按第 6 条尝试原样放回，不能安全放回或中断则保留现场。“原样”是同一对象，不承诺 ctime 或空窗内可连。财务只读监听按第 6 条隔离。仍有任一域的历史进展证据，不得因其他域库丢失而按首启；C09.3 不承诺全部原件丢失后的恢复。是否将路径计入提交根归 #2127，这里只要求同一布局的 `k` 字节不变。
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
| 整会话已放行后真杀本地 simulation X | launcher 只记 X 退出。其余域有序停后，整组能核共同边界才续服；X 通过本域门后 `retired`，同代；真实场所旧发送者确认归 #1401 | launcher 退出事件、完整边界、X 审计与原代 |
| 共同 checkpoint 已过预检，X 在准备态本地监听被 M 门拒绝 | 整组不放行；回收本次拉起的进程，不适用放行后 X 非关键规则 | 具名 X 布局错误，无域接纳、认领或消费标记 |
| 各域在提交前、提交后、回报或应用边界被杀 | 域按上列保留原件并逐域恢复；共同 checkpoint 无法核实或仅部分域推进时，launcher 拒绝普通整会话续服。不重复调用、不漏应用及同轨迹等价由原恢复合同与 #1411 验 | 各域原库、同边界 cut 向量或未完成证据、原身份回执、外效和业务差异报告 |
| launcher 被杀，S/E/各 B/X 仍活 | 孤儿继续服务。L2 中 S 对活对象试连拒绝（或锁拒），E/B/X 锁拒 | 同 inode、owner 未改，旧域仍应答 |
| 孤儿随后全部退出 | 无干净标记的 E/B 须正式恢复；S 看 R4，X 看原门；运维终止的授权与步骤归 #2130 | 新进程只见本域锁、库和介质；夹具只等自己创建的子进程 |
| 宿主重启 | 第 3 条允许的本地持久目录若保留 k、owner，且身份相符、无未确认退役，逐域退役；若挂载重建使 dev 改变则拒。tmpfs 上 k、owner 同失走 `fresh`。运行中的 E/B 标记已经消费，须恢复；持久标记有效且库未被外部替换则按正常列 | 不读 boot ID；本票不要求 #1411 做整机重启 |
| L1 活时 L2，含 SIGSTOP、积压满 | 拒绝并保留 L1；connect 成功或 `EAGAIN` 都不是死亡证据 | 原路径同 inode，L1 恢复执行后再取同身份应答 |
| 无 owner 残留、他人/坏 owner、身份或 UID 不符、普通文件、目录、链接、父路径链接、父目录不合权限 | 有对象即拒；合法检查不改原对象 | 前后 lstat，owner 和持久代对照 |
| 预核后换入活监听、普通文件或换父目录 | 不销毁、不覆盖；移错对象时复核后放回，回放受占则保留并拒绝。父目录换掉时不能在新目录接纳 | 对照原对象 dev/ino，活监听仍可应答；后置目录身份复核 |
| 写入退役意图后、完成验证和提交前被杀 | 下次启动拒绝；即使 `k` 空也不是 `vacant`。退役名残留不相符、相符但未经前次提交、不可核，均不自行处置 | 原 `bound`、意图、`k` 与退役名保持重启前状态，E/B 标记未消费；交 #2130 |
| 同名锁对象被换掉，或锁叶是符号链接、硬链接 | 即使新锁可取得也不接管，不开可写库或退役；不新建缺失的已登记锁 | 实际加锁 FD 与 owner 锁身份不同，或锁叶类型/链接数不合格；原 owner、端点和库内容不变 |
| bind 后首次打开新目录项前换入另一同 UID 的单链接 socket | 所有权证明失败，关本次监听，不写 `bound`、不消费 E/B 标记，保留条目 | 双方 inode、对端 pidfd、null 和原标记 |
| 域在 bind 后、开始写 bound 前被杀；或旧直绑抢到名字后退出 | owner(null) 与存在的 `k` 不足以证明归属；拒绝并保留两者，交 #2130。认领失败的本域 E/B 不消费标记 | null、原 ino、无退役名，拒绝域标记不变 |
| owner 正写时中断，JSON 半写 | 拒绝并保留；不把坏 JSON 当 null；归 #2130 | 无 accept，标记未消费，原件保留 |
| 启动在持锁／准入／退役预核阶段被拒 | 不消费标记，不改 k；修正失败条件后原样重试。若后来一步已确认退役后失败，按第 11 条保留已完成动作 | meta，k 和退役名，首错 |
| E/B 库部分缺失 | launcher `InvalidDomain`，不 init、无域 spawn | 缺失字段与退出，幸存库和目录投影 |
| 升级首次面对旧库和旧残留 | 旧 E/B 库无标记须按 C09.11 连同正式恢复处理，旧残留无 owner 则拒，别把恢复回执当端点资格 | 旧库 meta、原残留；清场归 #2130 |
| 恢复应答丢失后重试 | #2082 重取原件不再升代；若期间 serve 已消费标记再崩溃，原请求重取的回执不能重新放行 | 字节相同的旧回执与缺标记门 |
| launcher 活时单域原址重拉 | 由 #2120 裁触发、证据与来源代，不在本票实现 | #2120 仍依赖 #2079 |
| S 的 socket 在 M 内（含物理别名）或 M 外不可证；其他不适用认领而通过硬门的端点目录 | 旧端点合同，OBS-IN 两布局占用首错不变；无 k 但有 owner 时拒绝；E/B 标记门与 bind 后、accept 前消费在所有路径生效；E/B/X 的旧合同仍须绑定已核目录 | 不创建 owner、不移动；E/B 直绑就绪时标记已无 |
| E/B 或带监听 X 在 M 内（含物理挂载别名）、M 外不可证或父路径有链接；库或侧件有硬链接或挂载别名 | 第 3 或 4 条硬门拒绝，不走旧合同；E/B 对布局的 launcher 预检拒绝早于目录写入、init、spawn | 具名诊断、无端点变更；初核拒绝无新锁、库及侧件 |
| 公开地址末段非法、Linux 公开地址超限，或内部绑定地址单独超限 | 在端点变更前拒绝，指明哪个地址失败 | 原 `k`、owner 和退役目录项不变；E/B 标记不消费 |

## 五、验收清单

以下具名端点测试落在 `rust/tests/production_session_entry.rs`，用 Linux 正式入口的真进程；除明确的对照臂外，独立端点目录权限为 `0700`。实施 PR 的 `rust-test-production-session` 日志须逐行出现相应 `test <名> ... ok`（`.github/workflows/ci.yml:811、:830–841`），不以早先 #2077/#2082 的 PASS 代替。检测切面用原正式读口，不用打开可能改变 S admission 成员的观测连接冒充真实就绪。同步点只编入测试专用夹具。

- `endpoint_orderly_restart`：L1/L2 PID 不同，逐字节复用 manifest，并重开同一组库文件，不替换原库。启用带本地监听的 simulation X，S、E、各 B 和 X 同代；确认 cut-1 已绑定到共同 checkpoint，未改变业务状态的域也以原 cut 完成登记。每个原 ino 转到对应退役名并在原址出现新 ino。正式读口逐字节返回 cut-1 原收据，input-2 `Committed`，首次接纳前已消费 E/B 标记。
- `endpoint_crash_needs_recovery`：分别对 E、某 B 真杀。不恢复先报缺标记；该域 k、owner、代、最新 cut 不变。正式恢复后子集仅列该域，目标按回执代认领原址，其余在 manifest 代。E 臂核 B 的实际 `--e-epoch` 和权威读取；分别以漏掉已换代域、旧回执、未知/重复域作负控；测试不把 X 的权威代跟随算作通过，归 #2129。
- `endpoint_live_untouched`：存活、SIGSTOP、积压满三臂，L2 无第二写者/监听，原 inode 和 owner 不变；L1 恢复仍能应答；两种非死亡 connect 结果都不能放行。
- `endpoint_unknown_untouched`：无/他人/坏 owner、错身份、普通文件、目录、叶链接、父链接、不合格权限和 M 内两布局，都拒且保留原件。错 UID 臂用与正式路径同一个身份判定函数，输入除 UID 外全匹配的 stat 字段，断言拒绝，不要求 CI 提权。旧合同目录另加 k 空但有 owner 的负控。还核坏锚、旧 epoch 不因端点可退役而放行；ADR 0059 的 layout 拒绝仍断言没有 spawn、init 或建锚。
- `endpoint_race_replacement`：在预核与移动之间以明确同步点换入活 socket、普通文件或父目录。比对保留的原对象及 live 应答；放回时原名被占用不得覆盖；更新 owner 时换入 socket 也不得覆盖，拒绝后它仍应答。另在 E/B 的 bind、listen 后且**首次 `openat` 新条目之前**，让另一同 UID 进程的单链接监听 socket 占据原名；断言第 5 条拒绝，两对象保留、对手仍能服务，owner 仍为 null、关库标记未变，无本域 accept 或认领事件。以能力核验失败作负控，断言不曾进入变更目录的阶段，也不直绑。
- `endpoint_retirement_crash`：E/B 有有效关库标记。退役预核后换入活 socket 或普通文件，在 `RENAME_NOREPLACE` 成功、尚未核退役对象或放回前同步 `SIGKILL` 并等待退出。确认 `k` 已空，退役名下是换入对象而非原 `bound`。重启必须拒绝，不清 `bound` 或意图，不重绑、不消费标记、不输出认领行；按名和 inode 比对现场。再覆盖退役名下是原 inode 但仍有未清意图，以及无意图但旧 bound 对应退役名已有不匹配对象；同样保持并拒绝。
- `endpoint_bind_window`：在 bind 后写 bound 前强杀，重启报占用，原 ino、owner(null) 和 E/B 标记不变，无退役名。用不同域锁的两进程调度旧直绑先看到两名为空、新认领再首建 owner(null)、旧直绑先完成 bind 并退出；重启认领者同样拒绝，即使试连该残留会返回 `ECONNREFUSED`。无退役意图、`k` 空且旧 bound（如有）对应的退役名也不存在时，null 与旧 bound 两臂均报告 `vacant`、不造退役对象、写妥新身份。在 owner 已写部分字节、尚未完成有效 JSON 时用同步点强杀，重启报占用且保留原 k、半写 owner 和未消费标记，不 accept。
- `endpoint_x_measurement_domain_refused`：只把 `history_simulation.socket` 移到 P、独立 A 的子树、S 族目录三处，X 库及锁均在 M 外；空址一律不建 owner 或 k，预置本锁有效 bound 与已死残留时同样不修改、不退役。挂载臂在私有 Linux 挂载命名空间中分别 bind 三类目录到规范路径位于 M 外的位置：P 本身、A 或族目录的后代、挂在 A 下的独立文件系统整根。确认路径比较原本通过，且新门在取锁、开库、`persist`、动端点前拒绝。此臂须在能创建该命名空间和真实 bind mount 的 runner 执行，不能以跳过当通过。不传 M 输入或无法核验时，连空址也不得走旧合同；须核 X 的实际拒绝诊断，不能只看 launcher 退出码。正控用 M 外目录（与 `endpoint_orderly_restart` 共用）及 P 下非族、非 A 子目录，均能认领。
- `endpoint_s_measurement_mount_alias`：S 的库和侧件走原规范路径，仅让 `s.socket` 的父目录通过 bind mount 指向 P、A 的后代或 A 下独立挂载的整根。以空址验证 S 走 driver open 后的旧合同（可 bind，无 owner 或退役对象）；预置已死残留再跑，保留 S 占用首错，inode、owner（如有）和退役名原样，不报 X 的 M 门错误。实际 M 目录与公开别名两侧都查；沿用上述私有挂载命名空间要求。
- `endpoint_e_b_measurement_domain_refused`：E 与每个 B 分别只把端点改到 M 内，或改到规范路径在 M 外但 bind 别名指向 M 的位置；另覆盖挂载证明不可核。核 launcher 具名拒绝，`state_dir`、任何域库或锚未创建，无 init 或 spawn，已有端点、owner、库保持原样。用可走旧合同的目录复核，不因认领不适用而放行；另移入挂载别名于 launcher 初核之后，验证本域重核拒绝、不消费 E/B 标记。
- `endpoint_reverse_measurement_mount`：与正向别名相反，在私有 Linux 挂载命名空间中把外部目录的子树挂入 A 的后代，端点配置始终使用原外部路径，置于源根下更深一级，并确认候选向上的链不经过新增挂载点。E、各 B、X 均按 M 硬门拒绝且不动端点；S 按旧合同空址可在 driver open 后绑定，但不建 owner、不退役，已有残留按原占用拒绝。验 A 下嵌套挂载也会纳入，另以不相交的外部目录为正控。
- `database_reverse_measurement_mount`：E、各 B 和 X 的端点均在独立 M 外目录；分别把各域外部库目录子树、现存主库、WAL、SHM、journal、写者锁单文件挂入 A 的后代。候选使用原外部路径、字面 Q₁–Q₃ 均在 M 外。核 launcher 不创建目录、不 init、不 spawn；也以直接写入口核本域取锁、可写打开前拒绝，原库、锁和侧件不变，缺叶不创建。覆盖无监听 X，并以真正不相交的目录为正控。
- `endpoint_x_legacy_pinned_directory`：用本来只适用旧合同的 M 外目录核正控，带监听 X 可连接，不建 owner。用指向该目录的父符号链接核负控，即使初始指向 M 外也拒绝。另在无链接原路径通过末次重核的同步点，将公开父路径换为通向 M 的链接；bind 即使已进入内核也只能用原目录 FD，断言 M 内无新端点或 owner，且公开路径重验不通过时不 accept。夹具分别检视已钉目录和 M，而不仅看退出码。
- `endpoint_x_writer_lock_stable`：悬空末级库链接（含相对目标）在首次 `serve` 即拒绝；目标库、两种可能的锁路径、端点和 owner 均不新建，原链接不动。无链接缺库首启、以及指向已存在库的链接分别核正控：同 manifest 停启锁路径和锁 inode 不变，旧进程持锁时第二进程在写库前被 `StaleWriter` 拒，原代及 owner 不变。分别测试两个硬链接库名、各有一条硬链接的 `-wal`、`-shm`、`-journal`。挂载负控在私有命名空间中分别对主库和这三种侧件建立单文件 bind 别名（先确认两名 `dev/ino` 相同且 `nlink == 1`）；再通过同底层目录的子树挂载或整文件系统别名启动。断言别名一侧未取／建锁、未开可写库，原库和侧件未变、无端点变更。硬链接和挂载负控均覆盖带监听及不带监听的 X `serve`。
- `database_vfs_object_replacement`：在启动末次 FD 核验之后、SQLite 实际打开前以同步点分别换掉公开父目录、主库、WAL 与 journal；另在 `xShmMap` 的实际 SHM 打开前换入同类普通文件，并在一个已登记确无叶的侧件位置抢先建文件。断言原父路径或实际打开对象不符即拒绝，在错对象上不产生写、truncate、改属主、可写映射、删除或 `PRAGMA journal_mode` 引发的 I/O。按 FD、inode 及原件字节比对，非只看最终报错；无替换的正控仍通过 WAL、同步和同库续服。
- `endpoint_writer_lock_identity`：保留 owner 和已死残留，让夹具持有其登记的旧锁 FD，再把锁叶换成可独立加锁的同名普通文件；确认两个 inode 不同、新锁可单独取得、旧锁仍被持有。服务须在打开可写库前按身份不符拒绝，不改 owner、库或端点。对原 `k` 已空、锁叶缺失、符号链接和多硬链接分别作负控；缺失时不创建替代锁。
- `endpoint_address_bounds`：长目录短 basename 使公开地址 ≥108 字节而内部合法；短目录长 basename（如 5+95，含分隔符）使 S 的公开地址符合 100 字节旧上限而内部 ≥108 字节。分别核拒绝步、空址不创建、已有 owner/残留不动；E/B 两种超限均不消费标记。另对 E、B 分别传尾随 `/`、末段 `.`、末段 `..` 及空地址，覆盖可认领目录和旧合同目录：即使剥去末段后的 basename 合法可绑也必须拒绝，不创建或移动任何端点目录项，`clean_close/1` 原值不变。覆盖多字节名称与实际 FD 号长度；E/B 两地址各在 107 字节合法边界时仍能从公开 `k` 连接。
- `endpoint_launcher_crash`：只杀 L1 不杀子进程，S/E/B/X 保持原 inode、锁和应答，L2 拒绝。夹具随后只结束自建子进程并等待；E/B 缺标记拒绝，S 带 SHM 首错为 R4，k 和 owner 原样。
- `economic_store_partial_refused`：E 缺、任一 B 缺分别拒绝，点名准确字段，无 init、spawn 或 state_dir 写入；S 预建不影响 E/B 全无的首启；全有不 init。
- `session_checkpoint_partial_commit_refused`：先完成全组 checkpoint N，再让部分域的 N+1 业务提交及边界证据确实落盘、其余域留在 N，以同步点强杀，不走关停回调。确认各域单独审计仍通过；原 manifest 普通续服须报共同 checkpoint 未完成，不以 N 或不同的域 cut 拼装，不写 `state_dir`、不 init、不拉起写者、不改端点或标记，不改持久事实和责任。再测已有业务推进但 N+1 尚无任何完成记录，以及相同 ID 下 bar 边界不符；全体完成 N+1 是正控，须从对应完整向量恢复。
- `session_checkpoint_partial_commit_recover`：从上述 N+1 部分推进的原库先复验普通启动拒绝，再用获授权的具名离线恢复计划和本域 `recover-checkpoint`，从 N 补齐 N+1；期间无监听或场所调用。再压一次恢复中断及同计划续做，核已持久原件、原回执、命令计数不受改写或重复应用。验证因果闭合的 N+1 向量、E/B 原换代及标记门后，原 manifest 普通原址续服成功，和不中断对照的快照与责任相同；真实场所模式用受控场所检验只读对账、未知最大责任和零重发。
- `session_checkpoint_causal_closure`：构造相同共同键、各域本地均通过审计，但 B cut 所引用的 E 权威提交在所选 E cut 之后的两条证据；整组须拒绝。另测已封口后的迟到回报只能进入后续 bar，旧 Pending／在途责任和旧 cut 字节不变。
- `session_initial_boundary_rechecked_under_locks`：在首启只读预检之后、域取得锁前，让另一组合法进程推进一个原有初始域并干净关停，使新启动仍能取锁且标记有效；须在准备态拒绝整组，不 init、不改已推进库、不消费标记、不 bind。另覆盖预检缺失库在间隙被合法建出并推进。
- `session_x_preparation_required_then_noncritical`：先使已有的 X checkpoint 与全组一致并通过只读预检，只改变本地监听的实际挂载视图使 X 在准备态命中 M，核 X 具名退出、本次整组收回且 S/E/B 不接纳、不消费标记。用合法布局重新通过全员放行后再杀 X，S/E/B 继续服务，launcher 仅记录 X 退出。
- `clean_close_negative`：夹具手删、损坏、写错代标记均拒绝；准入拒绝前后不消费标记；恢复丢应答重取同字节，消费标记后崩溃再取原回执不能再次服役。旧合同两臂分别让 E、B 在 `0770` 目录真进程直绑服务，确认无 owner、标记已消费；真杀并等待退出后，夹具只移走它自己创建的残留，再启须报 `StaleWriter：缺本代正常关库标记，须先正式恢复`，不得 bind。受监督关停臂在关库标记事务提交处用测试专用故障注入令提交失败；断言进程非 0、监听已关、库内无标记且无正常关库结果。
- #1411 在原库续服验收中核本域恢复幂等，而非只看新代和监听就绪：选取 checkpoint 后已应用事件重放，按 ADR 0051 裁定三核原 application、不增行及原 commit root 逐位相等；分别破坏两项判据，须报 `StorageUnavailable`、不得继续写入或接纳。三种证据类整会话的 H2 六面对拍仍按 ADR 0038 的 #1539 修订执行，见下文「恢复职责分派」。
- #2077 `b7b79657` 的测试 `orderly_stop_closes_same_s_db_without_claiming_socket_handoff`（函数 :934）改为验证再启成功；`killed_s_is_not_orderly_and_its_socket_remains_for_explicit_recovery`（函数 :1068）在适用目录首错改为 R4，S 原 inode 不变。原 OBS-IN/OUT 的占用对照可用未认领残留，不能用以取消新成功路径。

同一 #1411 实施 PR 还须通过 CI 纯生产构建的现有 `real_x_process_authority_restart_and_double_replay`。在 `rust/tests/history_simulation_entry.py` 的真 X `serve` argv 补齐 `--s-db`、`--s-admission-job-limits`，准备独立、可核的 P 和 A，让 X 的库及 socket 保持在 M 外；不借用受控 S authority 的 socket 路径冒充 S 布局。正例保留原权威、重启和两次回放对拍：同库重启保留 owner 与旧 socket，由 X 按适用合同退役；在夹具确认所有子进程退出后才清理自己的目录，并为下一套新库在同一路径重建空目录，保持原权威配置字节相同。分别缺少任一布局参数及两者均缺的负控，在库尚未创建时跑真 X，断言具名 `InvalidDomain`，不建库、侧件、锁、owner 或监听端点。单独的 `runtime-fixture` argv 不改。

**独立 E/B 控制器与 macOS 真进程夹具随 #1411 迁移。** `economic-launcher/1` 的写操作配置明确给出 `s_db`、`s_admission_job_limits`；Python 控制器在清理、init 或 spawn 前拒绝缺参，将这两项传入 E/B 的 `init`／`serve`／`recover`，Rust 仍独立执行硬门。迁移 `.github/workflows/ci-macos.yml` 现有 `tb03b_cap_service_faults.py`：为 HFS+ 载体和独立短 socket 路径配置可核的 M 外布局，保留真 E 进程的前／后提交强杀、换代恢复、原回执与独立 oracle 断言；加直接 Rust `serve` 缺参拒绝负控，不创建锁或端点。macOS 以本地挂载表与实际目录／卷对象证明隔离；旧合同的短路径绑定在启动任何工作线程前，可用保存原 cwd FD、`fchdir(d)` 后仅 bind basename、再恢复 cwd 的固定目录方式，不按公开路径重解析。其他复用该控制器的配置夹具与单测同步迁移；不把 Python 控制器升级为正式 launcher 或用于本合同的生产端点目录。

财务只读监听的部署配置以第 6 条为验收口径：保留两组目录的实际查证结果；共用、嵌套或别名指回写者目录均不得获发启用配置。只为 #1411 验收写者端点不要求启用财务监听。

## 六、受影响票与 blocking 边

| 票 | 承接及边变化 |
|---|---|
| #1323 / #1340 | 不改 Destination、SPEC 或关图门。 |
| #2079 / #1411 | #2079 是 #1411 原生子票，关闭解除子票门，不等于 #1411 已放行；不另接 #2079 → #1411 的 blocking 边。#1411 实施端点认领、关库标记、库及侧件的 FD/VFS 与锁身份门、端点和库的统一 M 判定、E/B/X 固定目录绑定、共同 checkpoint 的因果封口、全员持锁准备和受限离线恢复；迁移 CI 真进程 X 和独立 E/B 控制器及夹具，完成原库续服与恢复幂等验收。 |
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

### 恢复职责分派

**launcher 只编排，域持锁恢复。** ADR 0039 文末 #2079 修订明确了原裁定三及 #1539 所列恢复义务的执行者。ADR 0038「修订（#1539）」第 1 条对三种证据类的恢复义务仍有效，由 S、E、各 B 与 X 的本域恢复／启动路径分别执行。launcher 只读汇总并编排，不加载快照、不重放、不持域写者锁、不自动升代。

- **共同 checkpoint 如何落盘。** 同一组使用 `(session_id, session_generation, checkpoint_id, bar_close)`：`checkpoint_id` 取会话代内共同逻辑 bar 序号的规范十进制字符串，不取本域 commit 序号；`bar_close` 钉住 ADR 0038 的收盘／下一 bar 开盘前边界及其输入前沿，同一 ID 不得改写边界。各域在推进 bar 的持久事务中同步记录本域最高已推进边界，包括已写入但未封口的 bar。封口时在本域事务中持久追加这组键、`domain_id`、候选 `cut`、本域快照／重放起点和截至该 cut 引用的跨域前件；本 bar 无业务变化的域以原 cut 登记。既有 `store.rs:665` 的域 cut 不含共同 checkpoint 身份，不改其格式或既有业务 root。
- **封口顺序与在途归属。** 先由各域按同一输入前沿停止接纳本 bar 的新业务，按实际事件的因果顺序收束此前已经接纳的工作。已产生但未完成的操作以本域持久的 Pending／在途责任留在本 bar；前沿之后才获知的新事实登记在后续 bar，引用旧责任，不回填到已封口 bar。各域先钉定不会再更改的候选 cut，提供本域原件中的跨域引用；按 S、E、manifest 顺序的各 B、X 组成有序 `(domain_id, cut)` 向量，验证因果闭合后，再按这个次序各自在本域事务落绑定该向量的封口记录。封口顺序不代替业务事件的因果顺序，也不要求一个域拿另一个域的锁。已有提交的 bar 归属不为凑齐向量而改写。
- **何时算共同完成。** 预期成员是本会话 manifest 的 S、E、每个 B 和 X，不从幸存回执或换代子集推断。各域从原件只读核实 manifest／证据类绑定、共同键、本域 cut、快照引用、跨域前件与推进边界。全员完成记录须绑定同一候选向量和同一 bar 边界；每个跨域前件必须在其源域所选 cut 的已核提交链内（逐项核源域、提交序号、root 及被引用记录）。例如 B 在写事务前读到的 E 权威事实（`service.rs:1043–1057`），其 E 提交必须包含在向量所选 E cut 内；只对上序号、业务 ID 或 bar 键都不够。闭合后才是完整向量，无另外的“已完成”文件或跨域写事务。普通续服采用最新完整向量；证据缺失或冲突、前件落在向量外，或某域已推进到更高未完成 bar，报 `StorageUnavailable：共同 checkpoint 未完成或不可核验`，不 init、不拉起写者、不接纳或发送。不拿旧向量掩盖推进，也不当作首启。
- **首启和续服均全员持锁重验。** launcher 传初始边界预检结果或已核向量。S、E、各 B 与 X 在准备态执行本域布局门（含 X 的本地监听 M 门），各取并持本域写者锁，重验实际域库。首启要重证预检时缺失的库仍确无条目、已有初始库仍在初始边界、无本会话进展，且 E/B 仍为预检的存在组合；任一域在间隙推进，整组不得按首启放行。续服重核所选证据与推进边界，按本域介质门加载快照、重放并核验。全员准备回报前不 init、bind、不消费标记、不开放服务或发送；首启放行后用这些同一把锁执行本域 init／自建，不用先放锁的独立 init 结果替代重验。launcher 收齐同一启动批次的全员结果才放行；不符、未齐或放行前观察到成员退出，就中止本次并回收本次子进程，X 适用第 11 条。未放行时监督管道 EOF，域退出；已放行后的监督语义不变。启动同步不产生新写锁或持久放行记录。
- **只补齐已中断的 bar，不绕过普通启动门。** 当已有因果闭合的最后共同 checkpoint N、但 N+1 仅部分域推进时，停服并确认旧域已退出（场所 X 连同旧发送者），由获授权的域运维按同一具名离线恢复计划执行 `recover-checkpoint`，不由 launcher 自动调用。计划绑定原 session／manifest／证据类、N 的完整 cut 向量、N+1 的 bar 边界和原输入、策略、时钟及已有前件证据，只准补 N+1；无可核 N 或缺必需原件就停。各域命令只持本域锁、使用原库，依据已核的不可变前件按实际因果顺序从 N 重放；沿用下条分证规则，禁止监听、接纳新业务、启动发送 adapter、重新调用场所或伪造完成事实。若实验／生产需要对账，只能用已获授权的只读证据，未知责任仍保留。已有原件与封口只能按原 ID/cut 校验和复用，不重复写、不回退；缺的应用或封口在本域事务追加。依上文形成因果闭合的 N+1 向量后才重走普通启动。任一域失败或恢复再中断，保留已提交原件，同名同计划可按幂等判据续做；冲突或证据不足继续拒绝普通启动。
- **换代和关库门另外成立。** `store.rs:1694、:1722` 的 `recover` 只审计及返回当前域 cut 并升代，`recover-named` 的回执也不能补共同 bar。受限恢复不替代原域换代或证明干净停机；它在 E/B 首次改写的事务撤销旧关库标记，不自行补写。完成共同向量后，需要恢复的 E/B 再按第 9、12 条用原 `recover`／`recover-named` 取得有效代、回执和本代标记；S 的介质与代按 #2128，场所 X 按 #1401/C09.8，指纹门不变。
- **重放边界。** simulation 依 ADR 0038 #1539 第 2 条，从 checkpoint 的工作态用受控撮合重跑未完成 bar，不删除已持久真相行。experiment/production 重放到最后持久提交，保留 checkpoint 后的 E Recorded/Pending、B Applied、X OwnAttempt/MayHaveCalled 及既有观测，不回退它们；场所 X 对在途订单先只读对账，未知保留最大责任，不自动重发。离线确定性回放与 seek 口径不变。
- **恢复验收。** 各域按 ADR 0051 裁定三同时证明重复 `fact_key`／`command_id` 返回原 application、不增行，以及重放 root 与原 commit 逐位相等；任一失败报 `StorageUnavailable`、停止写入。#1411 交本域原库续服证据，换代回执或同址监听都不能替代；各域分面合成同一 checkpoint 的六面，三种证据类按 ADR 0038 #1539 第 4 条在各自固定轨迹上与未中断运行做 H2 对拍，不以本域幂等代替整图验收。

### 与布局裁定的关系

ADR 0059 第 6 条的“不比较 `s.socket`”作为 launcher 静态布局检查范围仍保留。该条“残留一律在 S 参数期拒绝”及“清理归 #1823 调查”的理由由第 3、5–7 条取代：M 内继续按旧合同，有资格的 M 外残留只允许持锁域退役；正常 bind 仍晚于 driver open。本 ADR 第 3、4 条强化 ADR 0059 第 3、4、9 条：E/B 端点以及并发写域的库、侧件、锁须在原有路径预检之外再过物理目录和双向挂载证明；`history_simulation.socket` 另过 X 域内硬门。第 4 条取代 0059 对悬空库链接可先取链接名锁、再取目标锁的现状描述，不放宽库与锁的原布局门。

受影响代码（默认以 `b9d898dccf46c2a716115eaa1215bc39c458a959` 计）：

- `rust/src/session_transport.rs:50–81、:617–680`：规范库及侧件的硬链接与挂载前置核验、实际锁 FD、owner 与持久退役意图、监听生命周期和认领/接纳拆分；`:649` 的按名 bind 不能接收带监听 X 的公开地址。`:618、:648` 关于监督器、PID 的旧注释由本裁定取代。#2077 同文件 `:702–728、:735–755、:797–809` 对应停止字节、监听器与 join。
- `rust/src/bin/s_session_v3/writer_cli.rs:267–275、:372–395、:779–861`，`admission.rs:19–65、:324–343`、`driver.rs:171–185`：S 预筛与持锁端点选择共用 M 物理判定、取锁前库及侧件挂载门、正式锁身份和 bind；`admission_provider.rs:49–67、:231–233、:261–338`、`audit_owner.rs:1198`：单链接源对象、介质及 A 和 S 族递归枚举原门不改。
- `rust/src/economic_session/service.rs:1043–1057、:1515–1595`：已读 E 权威事实的跨域前件、E/B 布局 argv、硬门、锁、audit 与固定目录 bind。#2077 同文件 `:1521–1568`（标记门、消费及服务返回后标记）；#2082 `rust/src/economic_session/store.rs:659–663、:786–835、:967–1084、:1694–1743`（init、逐键审计与恢复），`recovery.rs:112–154`（当前回执与同事务），`service.rs:905–926、:1619–1635`（E 来源代与 serve 自身代）。
- `rust/src/economic_session/store.rs:519–546、:665–681、:1694–1726`：可写打开改接受控 VFS；域 cut 保持原形，原 recover 与新增离线补 bar 分工。S 的 `admission_anchor/native_vfs.rs`、`admission_anchor/native_n1.rs` 提供现有 SQLite VFS 与 Unix 调用适配接缝；`admission_private/fd_wal.rs` 的只读私有路径不直接承担可写打开。
- `rust/src/bin/production_session.rs:124–201、:276–448`；#2082 同文件 `:249–342、:351–425、:553–584`：端点及库布局预检、有效代装配、共同 checkpoint 只读汇总和首启／续服持锁准备；`:336、:448` 的 X 非关键退出语义限全员放行后。正式 E/B/X 写入口传 S 的两个布局输入。
- `rust/src/bin/x_execution_session.rs:118–162、:178–212`、`rust/src/history_simulation/runtime.rs:42–56、:815–831、:866–897`：X argv、M 门、库锁路径、冻权威配置、启动审计与受核本地 bind。
- `rust/src/economic_session/finance_transport.rs:32、:98–109`：客户端仍按原字节使用公开 `k`，不替服务端修剪末段；服务端先核原地址，需要固定目录绑定时另核内部 bind 地址。
- `rust/tests/production_session_entry.rs`：本 ADR 验收及 #2077 的两个现有测试函数（`:934、:1068`）。
- `rust/tests/history_simulation_entry.py:114–151、:449–456`，`rust/tests/history_simulation_entry.rs:5–23`，`.github/workflows/ci.yml:837–841`：#1411 迁移 CI 现有真进程 X 夹具的正例 argv、重启与清理，保留缺参拒绝负控；仍由纯生产构建执行。
- `rust/src/bin/s_session_v3/mod.rs:273–281`，`financial_session.rs:1516–1535、:1693–1698、:1728–1740、:1768–1798`：范围对照。财务只读入口仍可清理自己的 socket；第 6 条要求部署目录隔离，不把这些分支改成写者认领。
- `s_session/economic_service_control.py:19–58、:68–73、:83–95、:126–132`：独立布局配置、E/B 写入口 argv 和缺参拒绝。保留 `s_session/s_service_control.py:505–528、:727` 的独立用途；两者均不是正式 launcher，不得用于本合同管辖的生产会话端点目录。独立 serve 不写正常关库标记；再 start 须按第 9 条正式 `recover` 并用有效代。
- `.github/workflows/ci-macos.yml:174–198`、`s_session/tests/tb03b_cap_service_faults.py:48–85、:113–116、:155–185`：持续执行真实 macOS E/B bin 的现有故障夹具，补布局配置、argv 与缺参负控。复用控制器的 `tb03b_runtime.py`、`tb1716_formal_consumption.py`、`test_economic_service_control.py` 同步迁移，不删既有检查。
