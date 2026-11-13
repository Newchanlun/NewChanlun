# 共享代理维护：先关新工作准入，再等自然收尾

本入口服务 #1742 的现役 decision-claimer、Wayfinder、executor intake 与正式 review。
它只证明这四类本机入口的状态；T3 和其它外部请求 owner 由主控另行汇总。
`request-receipts-20261113-0900Z` 已关闭，本实现不重开该窗口，也不操作现役服务。

## 操作入口

在已完成下方部署核验的检出执行：

```sh
python3 .sandcastle/deepagents-pilot/pilot1742/maintenance.py request
python3 .sandcastle/deepagents-pilot/pilot1742/maintenance.py status
```

部署根固定为 `/Volumes/AgentStorage/newchanlun-maintenance`；`--root` 仅供离线测试。
`request` 幂等：open → closed 时加一代次，重复请求仍返回同一代次。
JSON 返回 `v`、`generation`、`state`、请求/观察时间、未确认入口、未覆盖进程、owner 和在途记录；
不输出环境、模型提示词、凭据、完整进程命令或上游错误文本。控制失败只返回固定错误代码。

- `open`：允许新工作，无维护关闭承诺。
- `unknown`：有入口未确认本代次、旧进程未覆盖、资源清点未证实，或有异常/失联任务。
- `draining`：各入口已确认关闭，但仍有已领取工作。
- `drained`：各入口已确认本代次，已登记工作全部有绑定的返回与资源结束证据（或明确未启动记录），且未发现未覆盖的相关进程。

没有 `READY` 状态。`drained` 是主控汇总的一个输入，不是共享代理可以重启的独立授权。

用户另行通知恢复后，使用**本次实际返回**的代次：

```sh
python3 .sandcastle/deepagents-pilot/pilot1742/maintenance.py resume --generation 2
```

示例 `2` 必须替换。旧代次或已恢复的重复 resume 失败，不会解开下一次维护。
恢复只重新允许新领取；不会清除异常任务、伪造结束或自动重派。调度器保持轮询，下一周期即可继续。
不运行 legacy `drain-control.py resume`：`draining/gen1` 与有效切流记录保持原样。

## 准入与结束证据

TS 与 Python 共用 SQLite 账本。`request` 与 `admit` 都使用短 `BEGIN IMMEDIATE` 事务：
先提交领取，则完整工作可继续；先提交关闭，则新领取被拒绝。网络、模型、子进程等待均在事务之外。
因此不使用 legacy admission.lock 阻塞在途工作，也没有“检查 open 后再无记录 spawn”的间隙。

领取粒度：共享模型 decision 单票/考古、live Wayfinder 单图动作/放行动作、executor 精确 run、review 单次 PR/head/attempt。
decision CLI 的默认 dry-run、显式 --dry-run 和 --archaeology-only 都会调用共享模型，因此必须登记 decision owner 并领取维护许可；旧版本这些进程也纳入 census。`--archaeology-only` 仍只接受 dry-run、单轮、指定票，GitHub/业务只读合同不变。这里的 dry-run 是“不写业务”，不是“无模型外效”：维护操作账本是新增且必要的控制记录。

纯离线 Deps 预览/测试、Wayfinder 不发模型的 dry-run，以及 executor 本地 status/reconcile 不登记维护 owner，不依赖生产维护根。CLI 的共享 runner 由 `attachCliMaintenance` 装配，离线依赖调用不经过此装配。
维护 CLI 的 `status` 会持久记下未覆盖进程的精确身份；它不派工、不恢复工作，不是无写入查询。
executor 的票/计划登记不等于执行准入：完成读取、等待判定与空间检查后，紧邻派工以一个事务领取并绑定 run。
登记后才关闸的计划不会被派发；awaiting_human、跳过的计划与 break 后的剩余票不占维护记录。
已经实际领取的同一 run 可以跨轮继续，新的 run-id 必须重新过闸，不能改绑或继承旧 run 的许可。

队列提示手动续跑时，仍使用 `executor run --run-id <原run> --resume`，不必提供内部 maintenance-job。
新代码在实际执行前登记 owner、绑定原 run 和 witness，执行期间确认维护代次，返回后核对资源终态。
serve 仍活着时保留其原任务 owner；并行控制器由 witness 原子互斥拒绝。同一已领取 run 可在关闭后续做，
未领取的新 run 返回 75；这不会 resume 维护代次。无维护时原命令参数、模型规则和业务返回码不变。
手动 run 收尾也清点完整 executor scope；未知资源仍阻止 drained。返回 75 时与 serve 一致保留原 run 许可，不提前 settle；资源返回证据仍照常记录。

review sweep 若在扫描后、reserve 前遇到关闸，会撤回本次 `.resumes`／`.launched` 标记；
恢复准入后可以继续原 attempt，不消耗唯一自动续跑名额，也不产生虚假的 600 秒启动退避。
已成功派出的任务仍保留原标记与重试限制。
原有 legacy、SPEC、票锁和发布判据仍然生效。

review 父进程先持久预留，再 `Popen(start_new_session=True)`；子进程原子接收这份预留，
即使接收前已关闸也能继续。预留只能接收一次。Popen 明确失败时，启动方通过原子撤销记录证明未启动；与 adopt 竞争时只能一方成功，不能撤销已转交的任务。子进程在 gh/身份/target 绑定前返回，则记未启动收尾，可在开闸期间重试。启动方还保留原 Popen 对象：poll/wait 确认子进程退出、且原子核实未 adopt/未产生 witness 时，记录 spawn_exits 与 exited_before_adopt 撤销。关闸期间也收集此证据，并撤回该次精确匹配的启动/续跑标记，不派新任务。adopt 先完成则不得撤销。父进程退出或没有 children 不消除预留；父也在收集 wait 证据前死亡的预留仍 unknown，本版没有可追认的持久 wait 回执。
正式审查还检查 supervisor 与容器结束回执；缺回执不计完成。`container_closed != true` 的监督退出失败只允许使用下述绑定资源终态证据恢复。
executor 复用 `_worker_activity` 的本地/Boat 生命周期证据，仍在途或 effect_unknown 的 worker 不释放维护记录。正常轮询与恢复对账都清点整个 `state_root/runs`，包括未被 queued unit/claim 引用的孤儿和非 queued 运行；派工仍只消费原 queued 范围。每轮先撤销旧 coverage，前后两次使用同一完整 scope 判据；目录或资源读取失败保持 unknown。

review 的正常 sweep、已绑定任务结束与 reconcile 共用 `ExternalReview.maintenance_idle`：遍历所有 run 目录，核 target 与目录身份、全部现役/退役 reviewer 的 launch 和 receipt 的 run/head/base/controller/model/launch-id，以及 supervisor 与容器终态。缺 target、孤儿 worker、缺 launch 或错配关闭回执均不能证明覆盖。唯一未派发分支：worker 目录仅有 prepare.json 与 checkout-cleanup.json，二者精确匹配 target/run/model 的预期 checkout，cleanup=removed 且路径（含符号链接）已不存在，才证明准备阶段没有模型资源；多余文件或任何启动记录均拒绝。

owner 绑定 PID 与启动时间；ps 读取固定 LC_ALL=C、TZ=UTC，避免终端 locale/TZ 改变同一进程身份。业务结果与生命周期终止分开：普通错误返回且资源已收尾，可以结束本次维护工作；退出码本身不是证明。进程消失、未返回的异常与不完整资源回执保留 unknown，
没有 TTL、心跳过期自动释放或 TCP 空闲推断。重启会登记新 owner，不能覆盖旧记录。
失联 owner 使用下面的证据对账入口；保留账本与原任务回执，不删记录绕过 unknown。

## 失联后的证据对账

先查看 `status` 的 owner ID 和当前关闭代次。只对该精确 owner 操作：

```sh
python3 .sandcastle/deepagents-pilot/pilot1742/maintenance.py reconcile --generation 2 --owner <owner-id>
python3 .sandcastle/deepagents-pilot/pilot1742/maintenance.py status
```

代次取实际值。返回 `reconciled` 表示旧 owner 已被永久禁止再次领取，其相关任务有可信结束依据；不表示四入口都已确认，更不表示全局 READY。`unknown` 带固定原因码，不输出路径、上游错误或凭据。
重复对账返回原记账代次；错误代次拒绝。事务提交前重验关闭代次、任务和执行身份快照；并发启动或证据变化返回 `evidence_changed`，重新查状态后再对账。对账从不执行 resume、重派、kill、容器删除或 Boat 回收。

证据链由代码在工作执行前后留下。CLI 的 returned-action/finish/action-exited 是同用户信任域内的 TS 桥接 RPC，不是供运维手填终态的对账入口；没有接受任意历史回执的 reconcile force 选项：

- **executor**：派工前把 job/票号绑定到精确 run-id、state root 和 source；`run` 在执行前登记 PID/启动身份及唯一 witness。正常返回记录 `returns`，不论是否 busy。随后和对账时读取原 WorkUnit、`run.json`、`_worker_activity` 本地监督/进程组回执及 Boat 的绑定 teardown 证据。对账时原进程必须结束。SIGKILL 后允许按原合同启动同一绑定 run 的恢复调用；旧 witness 不补签返回，而是记录它与恢复 witness 的关联。只有恢复调用实际返回、记下完成并核实所有资源收尾，关联链才成立。资源仍在运行或 effect_unknown 则不放行。退出1/2不自动 natural finish，busy 与信号退出仍保留同 run 续做许可。进入 run 之前的身份错误留下精确 witness 的 preflight_returns；仍核 WorkUnit/票号绑定与本地/Boat遗留状态，不能用一份无绑定回执消除未知任务。
- **detached review**：保留父→子 job lineage；实际派发前绑定完整 target（PR/head/attempt/run/controller）与 witness。返回后重验 target、每个 model 的 launch-id、run/head/base/controller、supervisor 和 `container_closed`；仅有一份不匹配 launch 的关闭回执不接受。卷删除失败或 checkout 残留同样阻止维护终态；原 prepare 必须有精确路径 removed 收据，卷须有原监督删除记录、绑定卷名的宿主补删记录或严格 resource-closure。业务审阅 verdict 不受删卷失败影响，维护结论则不能沿用业务完成。父失联但子自然返回后，可以分别对账父、子 owner。
- **decision/Wayfinder**：await 动作返回（包括 gh 失败、锁忙与业务失败）后，须确认该动作登记的模型进程均已明确结束，再记录绑定 job/owner/领取代次/PID 的 `action_returns`，随后 finish。模型通过 `maintenanceCommand` 启动前预留 job/resource，监督器在实际 Popen 前绑定 host/boot、PID 出生身份和进程域基线。实际 wait 后持久记录退出码（包括信号/超时），另核完整本机后代域终态；业务失败不改写成成功。没有 wait、后代仍活或核验不完整则保留 unknown，不因 close 或异常被业务捕获而消失。若返回记录与 finish 之间父退出，前一条可恢复；未返回的动作仍不能凭父无 children 推断结束。
- **空闲失联 owner**：须有原进程原子 poll 的准入账本检查点（或本代次关闭确认）、已覆盖记录且没有任何未证实任务。退休不代替新入口对本代次的确认。只见进程消失不能退休。executor/review 还检查事先绑定的 state-root 资源范围；任务转交历史不丢失。

新 TS owner 在登记及每次动作准入前绑定本机 OS host/boot 身份（macOS IOPlatformUUID + kern.bootsessionuuid；Linux machine-id + boot_id）。当前 decision/Wayfinder 动作的模型子进程域限定为本机 CLI，不含 Docker/Boat/T3。若未来扩展资源域，不得沿用该证明。同一 host 的原生 boot 已变化时，reconcile 可用整个旧本机进程域已结束的证据退休该代动作；这证明本地执行生命周期终止，不证明业务或远端请求成功。对账再核 boot，另存 local_actions/epoch_resolutions，保留原 unknown 与时间。不同 host、同 boot、旧任务无预绑定、绑定 executor/review 的任务均不得使用跨 boot 路径。此入口不会重启机器；重启影响现役任务，必须另由主控安排，不能为清账自行执行。旧 owner 仍被 fence，新一代仍需重新确认。

### 同 boot 的本机 CLI 收尾

`maintenanceCommand(file, args)` 仅在 `MaintenanceOwner.work` 内启用监督器；旧的无 context 调用原样返回命令。不持锁执行 CLI，stdin/env/stdout 原样透传，不记命令或凭据。decision 的异步 spawn 和 Wayfinder 的同步 execFileSync 共用此入口。监督器转发 SIGTERM/SIGINT，实际 wait 并保存业务退出码，然后记录可验证域封闭；不会自动 kill 逃逸后代。

Linux 新派发不再依赖全机 census 收敛：专用 guardian 在 Popen 前启用并核实 `PR_SET_CHILD_SUBREAPER`，确认没有既有 children，记录精确 PID、内核出生身份及 `linux-subreaper-v1` 域。primary 的真实 wait/业务码与域封闭分开。primary 已返回但还有后代时，外层仍返回原业务码，guardian 关闭自己的继承输出并继续自然 wait；setsid/换组、双重 fork 或被收养的孤儿不能脱离这个内核后代域。只有原 guardian 在该出生身份、subreaper 标志仍成立且 waitpid 返回 ECHILD 时，才持久封闭资源。其它 status/reconcile 进程不能用自己的 ECHILD 代签。guardian 异常丢失且没有封闭回执时仍 unknown，不能凭后代 PID 消失补签。

macOS 及旧的已绑定 census 域沿用同 UID 内核 PID/精确出生身份/父身份清单（macOS libproc，旧 Linux proc）。预派发基线界定无关既有分支；无法沿身份/父链归属的新进程阻止证明。权限/身份不可读、PID 复用、无法完成后置枚举、缺 wait 均不放行。旧域不能追认为新的 subreaper 域。

派发前采集失败与在途收尾失败分别处理：监督器先绑定精确身份，再采集基线。只有原监督器、尚无已封存基线且未进入 Popen 时，才能写 `local_resource_not_started(reason=baseline_unavailable)` 并以退出78返回；不启动命令，也不伪造 wait/自然成功。此证据只结束该次未派发资源，不自动重试。绑定前自身丢失或来不及落证据仍 unknown。已生成基线的资源不能使用此取消路径。

旧 census 后端将正常退出竞态与权限/身份失败分开。Linux 用 `/proc/<pid>` 目录 fd 绑定一次读取的 incarnation，再从该 fd 读取 uid/stat；macOS 只把零长度且 ESRCH 识别为已退出。遇 ENOENT/ESRCH 或首次观察 zombie，必须重新枚举并读取后置集合，纳入此间出生及被 init 接管的后代，不能只复查消失 PID 或接受原枚举的部分结果。已成功取得的身份记录保留为保守上界；跨轮同 PID 出生身份不同即拒绝。zombie 的出生身份也参与复用检查。

后置集合允许新增、退出，无需两次 PID 集合相同；但最终一轮的每个在场 PID 必须取得身份或此前已核实的终态。连续三轮仍存在未完成的退出覆盖则返回 `exit_fence_incomplete`，不无限重试；权限错误、短读和身份错配不走退出分支。外层最多三次采集的固定原因仍落 `local_resource_diagnostics`。这不是原子全机快照，而是用于严格资源分类的保守覆盖；未归属存活后代仍阻止封闭。高强度 churn 若持续阻止旧后端覆盖仍返回 unknown；Linux 新 guardian 后端通过独立内核后代域避开这个全机收敛前件。macOS 可用性不能由 Linux 验证代替。

Linux 离线回归使用无秘密 Boat VM，保持 pytest -n 4 全工作负载及原 TS 入口并发；另在独立的持续 fork/wait 发生器运行时执行原 TS/Python 超时入口，保留 143、ETIMEDOUT、自然重启后 drained 及活后代 unknown 断言；定序测试另外锁住退出后出生的孤儿、权限失败、PID 复用和覆盖耗尽。

动作退出写 `action_exits`，封住该 job 后续资源预留。资源暂未结束时保留原 unknown；原 owner 后续 poll 或自然退出后的精确 owner reconcile 可消费其完整 wait/域证据，在 `resolutions` 记录 `local-session-ended`，不修改失败与原时间，不 resume。四入口仍须确认当前维护代次。只有 close 的旧适配器仍不足以证明。

此证明限本机同 UID CLI 及其后代，不能用于 Docker/Boat/T3 或会变更执行身份的命令。旧 census 后端中新生但来源已不可追溯的**无关孤儿**也可能阻止域封闭；不能靠名称、年龄、PID 消失或手填布尔排除。监督器在绑定/wait 之前自身丢失、动作没有返回、或缺可信后代域证据时仍 unknown。Linux guardian 支持调度器自然退出后继续收尾并供新 owner 对账；guardian 自身也丢失的情况仍需额外可信证据。六项历史资源退休依赖不受此变更影响。

对账新增 `resolutions/reconciliations`，不改原 jobs 状态、owner stopped 标志或历史时间。旧 owner 被 fence，下一代仍要求当前入口的新确认。`status.reconciled` 给出原 owner 和完成对账代次。

### 历史 review 监督异常：先核资源来源，再对账终态

`SupervisorExitedWithoutReceipt` 的失败回执保持原样。reaper 先取得 run 锁、重核 launch/target/daemon 与监督状态，持久化实际带标签的对象来源 `resource-observation.json`（文件及目录项同步），再在同一锁区间删除容器和卷。锁忙、身份或持久化失败时保留资源，下一轮再取证。review_pr 的 reviewer 线程可借用同实例仍持有的 run 锁 fd；核进程身份、锁文件 inode，并串行借用。其它进程/实例的锁不能借用，调用方不能用布尔参数绕锁。需要人工发起资源核验时，用目标回执中的精确身份运行：

```sh
python -m pilot1742.external_review reconcile-resources --run-id <run-uuid> --model <reviewer> --launch-id <launch-uuid>
```

该入口不读凭据、不删 Docker 对象、不启动模型。它核 target/launch/原失败回执/监督登记，在同一 daemon 上清点该 launch 标签的全部容器和卷；有遗留对象时只记录来源并返回未完成，交原回收流程处理。对象已清空且来源绑定完整后，另写 `resource-closure.json`，正常 scope、bound 和 reconcile 共用该证据。并发调用由原 run 锁串行化；旧 launch 证据不能用于替换后的 launch，也不会确认下一维护代次或 resume。

若升级前资源已删且从未记录 daemon/launch 来源，空 Docker 列表不足以证明查的是原 daemon，这类历史仍明确 unknown。新记录只在实际带标签资源仍存在时产生，不能手填布尔补签。监督仍活跃、Docker 不可读、daemon 变化、缺少精确退出回执或资源未清空也不放行。

### 执行期间的确认与异常隔离

detached review 和手动 review/migrate 在已准入工作执行期间轮询确认维护代次，不阻断工作收尾。`migrate-stale` 在实际发布前绑定原 target/witness，不记录为未启动取消。TS 关闸后停止领取后续票，但保留同轮已完成结果；executor/sweep 轮次内维护调用失败时跳过领取并下轮重试，stop 失败仍关闭 sweep/client；executor 的 sweep 工厂失败不阻断 intake，下轮重试工厂。TS loop 的 poll 失败进入原轮次异常路径并继续轮询，单轮调用返回失败。启动时尚未成功建立 owner 的故障仍由服务启动恢复处理，不宣称已覆盖。tsx 外壳只在观察到同 lane 后代时消重，包含本机验证的 `node_modules/.bin/tsx` 链；无对应后代的进程仍计未覆盖。

### 仍不能补造的证据

`on_execution` 已进入但 `open_v2_run` 尚未写出 run.json 就失败的 executor，当前保守保持 resources_unsettled；需要原 same-run 成功恢复生成可信状态。此活性缺口未在本轮改动，不能当作普通已收尾失败放行。

升级前没有预先绑定的旧 owner/job、孤儿 executor，或既没有返回记录、也没有成功同 run 恢复链的调用，没有足够来源证明结束。它们保持 `missing_bound_completion`；旧未覆盖进程的观察也持久保留，退出不自动清除（`missing_prelaunch_binding`）。新代码补上的预执行绑定和执行端返回记录解决后续父失联/孤儿自然完成，不把新协议追认到旧运行。启动后、登记前的同一精确进程身份稍后完成登记，可变为覆盖；原观察历史仍保留。

对 `status.uncovered` 的精确 lane/pid/start，可在当前关闭代次请求身份对账：

```sh
python .sandcastle/deepagents-pilot/pilot1742/maintenance.py --root <原账本根> reconcile \
  --generation <当前代次> --lane <lane> --pid <pid> --start '<status中的原始start>'
```

入口只查原账本已有的 owner/witness 绑定，再复用同一严格 owner reconcile 核全部任务与资源。
成功另存 `sighting_resolutions`（原身份、代次、已核owner、时间），保留原 sightings；重复调用不重复记录。
没有原始身份绑定返回 `missing_original_identity_binding`；换PID、进程消失、手填终态和旧代次都不能清除。
旧版本误识别若只留下 lane/pid/start、没有原 argv 来源或任务绑定，目前仍不能追认成无外效；需要原始绑定与可信终态来源，不能让操作员补一份自述回执。

新 census 区分实际子命令和参数值，不把 `release --reason run` 当执行；serve 的 review flag 也不替代实际 review owner。
外域排除必须同时具备原生 argv 中可判定的分离形式 `--maintenance-root <绝对路径>`，以及该根原账本中同 lane、PID、出生身份且未停止的 owner。参数只提供查证位置，不证明旧二进制消费过它；缺账本、缺绑定或读取失败时仍纳入当前清点。等号形式、`--` 后文字、参数值中的旗标与未知参数消费语义均不作为外域证明。清点只读外域账本，不创建账本；身份/argv读取失败拒绝核验。Python 解释器的 `-X`/`-W` 有参、附着值和组合旗标均按入口语法处理；无法识别语法却可见目标模块时保守计入，不能据此报告 drained。
Wayfinder/decision CLI 与 executor serve 支持该参数；隔离 fixture 同时把实际账本和启动参数绑定到临时根。
executor serve 预检前、decision CLI 的 gh 身份查询前已登记 owner，早退仍有精确身份记录。


升级前已经留下、没有 action_returns 或预派发资源绑定的 TS unknown 记录仍缺证据；新代码不能为过去补签。同 boot 的新动作使用下述真实 wait/资源域证据恢复，不要求重启；整机启动代次证明只是额外恢复路径。此入口不从 CLI 日志或单个模型回执推测整项工作结束。缺 witness、目标漂移、旧 PID 被复用、缺少容器/Boat 结束证据均不能恢复。首次加载必须沿自然轮次完成旧运行，不能把切换旧运行的证明交给本命令。

## 由部署 owner 在自然边界加载

本 PR 不部署。不能把更新磁盘文件当成已有进程已接入。

1. 固定经审查版本与三个 launchd plist 原参数，盘点在途 decision、图动作、executor/Boat 和 detached review。
   不读取或复制 plist 环境值。保留原版本和恢复路径。
2. 旧代码没有可靠全局维护入口。逐个等待原轮次自然完成；确认相应进程及其任务、detached worker/容器已结束后，
   才能由部署 owner 停空闲调度器并加载新代码。不能为安装本入口先杀活跃父服务。
3. 加载全部新入口，保持既有 `--review-sweep --review-sweep-max-running 2`、模型来源、私钥路径与 Boat 参数。
   #2062 已合入的 `--model-rules` 与 Boat 同源规则保持不变；`_serve.child` 同时传递该规则路径及精确 maintenance job/root。
4. 首次核验 `status` 中四类 owner；request 后各入口须显式确认当前 generation。
   入口未出现或资源核对失败时只能是 unknown。若已记录旧代码进程的未覆盖身份，单纯等待其退出不会清除该记录；
   必须另有精确绑定与资源终态证据，缺证据交主控处理部署边界，不卸载活跃服务。
5. 取得本线 drained 后交主控；主控还须等待 T3 外部 owner。后续共享代理升级和恢复各需相应授权。

本机模型监督器使用 `setsid()`，在途进程不再属于调度器进程组。停止 launchd 作业或终端按进程组发信号，
不等于取消已经准入的模型调用；它们可以继续自然运行，Linux guardian 还会等待其收养后代。
部署 owner 必须按原任务/资源证据确认终态，不能凭父服务停止认定排空，更不能因此停止共享 proxy。
本段仅说明停服务语义，不授权本次停止任何服务。

四类入口都需要本代次的确认。尚未登记或没有确认的类别显示 unknown；部署 owner 须核实际服务配置，不能把缺少进程当成已完成接入。

## 离线验证

```sh
node --import tsx --test .sandcastle/maintenance.test.mts .sandcastle/drain-control.test.mts
python -m pytest .sandcastle/deepagents-pilot/tests/test_maintenance.py .sandcastle/deepagents-pilot/tests/test_maintenance_recovery.py
python -m pytest .sandcastle/deepagents-pilot/tests/test_queue.py .sandcastle/deepagents-pilot/tests/test_review_sweep.py -k maintenance
npm run typecheck
```

测试使用临时账本、真实 SQLite 多进程竞争与管道同步；fake 工作者不访问模型或生产控制根。
包括关闸/领取竞争、已领取持续推进、真实 detached 子进程接收与结束、缺入口确认、失联重启、精确代次恢复以及旧 freeze 不变。

双 BLOCK 回归另覆盖普通业务失败与资源不明的区分、等待票不占许可、新 run 不继承旧许可、真实 SIGKILL 后同 run 跨关闭续做、旧 owner 转交历史、Popen/绑定前失败可重试、只读 census 和纯离线 dry-run 不落账本。`test_model_rules.py` 同时断言 child 的规则路径、maintenance 参数及原环境继承。

Wayfinder 的临时入口快照通过 `scripts/wayfinder-maintenance-fixture.mts` 复制 TS/Python 准入助手，并显式向 `MaintenanceOwner` 传入快照内的 `maintenance` 目录；不使用生产维护根。构造点变化会使夹具立即报错，不能静默恢复默认根。壳层测试同时验证 dry-run 不生成维护账本，live 快照的准入调用使用临时根，原业务断言保持不变。

## 接入接口与回退边界

executor 的原子准入接口为 `Gate.admit_executor(owner, run_id, ticket, state_root, source_repo)`，结束使用 `settle_bound` 验证返回链与资源；预留未启动撤销仅供实际启动异常分支，没有 CLI force 入口。

Python `Owner(lane)` 提供 `poll/admit/reserve/finish/coverage/stop`；TS 通过 `.sandcastle/maintenance.mts` 调用同一账本。`reserve` 只供 detached review 交接，`finish(natural=False)` 保留 unknown。入口覆盖依赖当前解释器命令识别及本地 PID/启动时间（秒级），不是操作系统级全请求拦截；自定义启动壳与远端/T3 owner 必须另行盘点。

回退旧代码同样只能在全部在途工作自然结束后，由部署 owner 恢复原版本和原启动参数。保留维护账本及回执；回退后旧进程不具备本协议，不能继续沿用此前 drained 结论。恢复派发用本代次 resume，代码回退、代理升级与全局 READY 均不是该命令的功能。


### b6d 后续：新动作与原执行续跑

TS `work(key, action)` 每次调用都是新动作，不以同 key 的未完成 job 作为新回调许可。
若前次 action-exited/finish RPC 丢失，开闸时拒绝该 key 的未决动作，关闸时拒绝新回调；旧证据保留。
原回调内部的后续请求仍由它已经领取的 job 覆盖。Python executor 精确 run 绑定恢复合同不变。
本机监督器的 Popen 同步 OSError 记录原监督身份绑定的 `exec_failed` 未派发证据，返回 127；
这依赖 Popen 的 exec-error 通道完成未 exec 子进程回收，不制造 wait 或业务成功回执。
缺失监督器回执、异步崩溃、身份不符仍 unknown。Python 3.9 读取维护模块采用延迟注解。

**macOS 现役可用性仍未验收**：真实隔离反例证明，基线之后由动作祖先启动的无关长寿兄弟进程也会
阻止当前全机快照域封闭。当前父链不能区别该分支与已经 reparent 的动作后代；不能豁免 PID 1/祖先，
也不能把这条保守拒绝称为恢复。需要派发前建立、不会因 reparent 丢失且能检测记录丢失的后代归属来源，
再替换 macOS 快照判据；Linux subreaper 的证据不能替代它。此缺口独立于六项历史资源域退休依赖。

### 监督与准入故障的退出合同

本机监督器已取得真实 `wait()` 后，业务退出码和原 stdout/stderr 不依赖维护账本提交成功。
TS action-exited/finish、Python returned/complete/settle、review finish 及退出时 coverage/stop 均隔离证据提交失败，
不替换原业务异常、退出码、Summary 或审查结果 JSON。顺序依赖的证据链失败后不继续签后续完成，下一次准入仍检查原未决任务。
wait/封域记录失败时只输出固定诊断，不重派业务；Linux guardian 仍自然等待内核收养域的所有后代。
只有真实 wait 已持久化且严格资源判据通过才能封域。缺 wait 或封闭证据的占用仍保留，业务退出不充当 drained。

review sweep 仅在派发边界证明未启动时撤回本轮 `.resumes`/`.launched`：reserve 失败、或 Popen 同步启动失败。
Popen 已返回后的登记/文件异常保留标记与原占用，不能借异常获得重派权限；撤回标记不清除未证实的账本占用。
手动 executor 同 run 被活控制器拒绝时仍返回 Busy75，不新增见证、不释放原执行许可；绑定损坏等其它错误仍按原错误处理。

**发布门仍关闭**：macOS 活性与六项历史资源域缺证据未解决。现役 arch_hotzone/claim-loop 的自动 fast-forward
与重启路径可能加载 main，因此本候选不得先合入 main 再以“未手工部署”规避验收；发布由主控另行裁决。

### 原生 ES 离线机制

[macos-es-v1 离线合同](maintenance-es-offline-1742.md)实现新动作的精确注册、一次许可和有序生命周期归约。
证据持久标记 offline，原 Gate 不接受其生产封闭结论；现役 macOS 仍用原判据且发布BLOCK不变。
`status.observer_faults`另列暂时控制故障：成功poll只恢复入口确认，不能补签资源coverage或旧任务完成。

### 未交付的 review owner 与手动收尾

`serve_round` 工厂在登记后构造失败，会原子撤销本次尚未交付的 owner，保留 stopped/ack=-1 历史。
仅无 lineage、scope、census、本机动作登记的精确活 owner 可以撤销；已接受任务不适用，也不补签资源清点。
下一轮新 owner 仍需完成原全域清点和当前代次确认。撤销写入失败仍保留 unknown，不以异常当作退休证据。
手动 executor 的 complete-bound 失败不再跳过 settle：返回链已持久但资源未闭合时记 unknown，业务结果保留。
后续仍走原 reconcile：精确身份已退出、原返回链齐全、绑定资源与整个 scope 均闭合才能解除；没有新增 force 通路。
