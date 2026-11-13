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

领取粒度：live decision 单票、live Wayfinder 单图动作/放行动作、executor 精确 run、review 单次 PR/head/attempt。
dry-run、archaeology-only 与 executor 的本地 status/reconcile 不登记维护 owner，也不依赖生产维护根。
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

域核验使用同 UID 的内核 PID/精确出生身份/父身份清单（macOS libproc，Linux proc），不是 ps 中父进程无 children 或单一 session 空闲。预派发基线界定无关的既有分支；任何无法沿身份/父链归属到该无关分支的新进程（包括 setsid 后再被 init 接管的后代）阻止证明。不可读、PID 复用、枚举变化、缺 wait 均不放行。原监督器可持久封闭单个已结束域；此后无须依赖它仍在运行。

动作退出写 `action_exits`，封住该 job 后续资源预留。资源暂未结束时保留原 unknown；原 owner 后续 poll 或自然退出后的精确 owner reconcile 可消费其完整 wait/域证据，在 `resolutions` 记录 `local-session-ended`，不修改失败与原时间，不 resume。四入口仍须确认当前维护代次。只有 close 的旧适配器仍不足以证明。

此证明限本机同 UID CLI 及其后代，不能用于 Docker/Boat/T3 或会变更执行身份的命令。新生但来源已不可追溯的**无关孤儿**也可能阻止域封闭；不能靠名称、年龄、PID 消失或手填布尔排除。监督器在绑定/wait 之前自身丢失、动作没有返回、或缺可信后代域证据时仍 unknown。它解决可控超时与自然重启，不追认双失联历史。

对账新增 `resolutions/reconciliations`，不改原 jobs 状态、owner stopped 标志或历史时间。旧 owner 被 fence，下一代仍要求当前入口的新确认。`status.reconciled` 给出原 owner 和完成对账代次。

### 历史 review 监督异常：先核资源来源，再对账终态

`SupervisorExitedWithoutReceipt` 的失败回执保持原样。现有 reaper 在删资源前，把实际带 launch 标签的对象与 Docker daemon 身份写入 `resource-observation.json`。需要人工发起资源核验时，用目标回执中的精确身份运行：

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

双 BLOCK 回归另覆盖普通业务失败与资源不明的区分、等待票不占许可、新 run 不继承旧许可、真实 SIGKILL 后同 run 跨关闭续做、旧 owner 转交历史、Popen/绑定前失败可重试、只读 census 和 dry-run 不落账本。`test_model_rules.py` 同时断言 child 的规则路径、maintenance 参数及原环境继承。

Wayfinder 的临时入口快照通过 `scripts/wayfinder-maintenance-fixture.mts` 复制 TS/Python 准入助手，并显式向 `MaintenanceOwner` 传入快照内的 `maintenance` 目录；不使用生产维护根。构造点变化会使夹具立即报错，不能静默恢复默认根。壳层测试同时验证 dry-run 不生成维护账本，live 快照的准入调用使用临时根，原业务断言保持不变。

## 接入接口与回退边界

executor 的原子准入接口为 `Gate.admit_executor(owner, run_id, ticket, state_root, source_repo)`，结束使用 `settle_bound` 验证返回链与资源；预留未启动撤销仅供实际启动异常分支，没有 CLI force 入口。

Python `Owner(lane)` 提供 `poll/admit/reserve/finish/coverage/stop`；TS 通过 `.sandcastle/maintenance.mts` 调用同一账本。`reserve` 只供 detached review 交接，`finish(natural=False)` 保留 unknown。入口覆盖依赖当前解释器命令识别及本地 PID/启动时间（秒级），不是操作系统级全请求拦截；自定义启动壳与远端/T3 owner 必须另行盘点。

回退旧代码同样只能在全部在途工作自然结束后，由部署 owner 恢复原版本和原启动参数。保留维护账本及回执；回退后旧进程不具备本协议，不能继续沿用此前 drained 结论。恢复派发用本代次 resume，代码回退、代理升级与全局 READY 均不是该命令的功能。
