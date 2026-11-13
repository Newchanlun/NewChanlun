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
- `drained`：各入口已确认本代次，已登记工作全部有自然结束记录，且未发现未覆盖的相关进程。

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
dry-run、archaeology-only 与本地只读 status/reconcile 不登记维护 owner，也不依赖生产维护根。
executor 的票/计划登记不等于执行准入：完成读取、等待判定与空间检查后，紧邻派工以一个事务领取并绑定 run。
登记后才关闸的计划不会被派发；awaiting_human、跳过的计划与 break 后的剩余票不占维护记录。
已经实际领取的同一 run 可以跨轮继续，新的 run-id 必须重新过闸，不能改绑或继承旧 run 的许可。
原有 legacy、SPEC、票锁和发布判据仍然生效。

review 父进程先持久预留，再 `Popen(start_new_session=True)`；子进程原子接收这份预留，
即使接收前已关闸也能继续。预留只能接收一次。Popen 明确失败时，启动方通过原子撤销记录证明未启动；与 adopt 竞争时只能一方成功，不能撤销已转交的任务。子进程在 gh/身份/target 绑定前返回，则记未启动收尾，可在开闸期间重试。父进程退出或没有 children 不消除预留。
正式审查还检查 supervisor 与容器结束回执；缺回执或 `container_closed != true` 不计完成。
executor 复用 `_worker_activity` 的本地/Boat 生命周期证据，仍在途或 effect_unknown 的 worker 不释放维护记录。

owner 绑定 PID 与启动时间。业务结果与生命周期终止分开：普通错误返回且资源已收尾，可以结束本次维护工作；退出码本身不是证明。进程消失、未返回的异常与不完整资源回执保留 unknown，
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

证据链由代码在工作执行前后留下，CLI 没有上传回执或 force 入口：

- **executor**：派工前把 job/票号绑定到精确 run-id、state root 和 source；`run` 在执行前登记 PID/启动身份及唯一 witness。正常返回记录 `returns`，不论是否 busy。随后和对账时读取原 WorkUnit、`run.json`、`_worker_activity` 本地监督/进程组回执及 Boat 的绑定 teardown 证据。对账时原进程必须结束。SIGKILL 后允许按原合同启动同一绑定 run 的恢复调用；旧 witness 不补签返回，而是记录它与恢复 witness 的关联。只有恢复调用实际返回、记下完成并核实所有资源收尾，关联链才成立。资源仍在运行或 effect_unknown 则不放行。退出1/2不自动 natural finish，busy 与信号退出仍保留同 run 续做许可。进入 run 之前的身份错误留下精确 witness 的 preflight_returns；仍核 WorkUnit/票号绑定与本地/Boat遗留状态，不能用一份无绑定回执消除未知任务。
- **detached review**：保留父→子 job lineage；实际派发前绑定完整 target（PR/head/attempt/run/controller）与 witness。返回后重验 target、每个 model 的 launch-id、run/head/base/controller、supervisor 和 `container_closed`；仅有一份不匹配 launch 的关闭回执不接受。父失联但子自然返回后，可以分别对账父、子 owner。
- **decision/Wayfinder**：await 动作返回（包括 gh 失败、锁忙与业务失败）后，须确认该动作登记的模型进程均已明确结束，再记录绑定 job/owner/领取代次/PID 的 `action_returns`，随后 finish。模型资源在启动前登记；信号、超时或未等待的资源保留 unknown，不因异常被业务捕获而消失。若返回记录与 finish 之间父退出，前一条可恢复；未返回的动作仍不能凭父无 children 推断结束。
- **空闲失联 owner**：须有原进程原子 poll 的准入账本检查点（或本代次关闭确认）、已覆盖记录且没有任何未证实任务。退休不代替新入口对本代次的确认。只见进程消失不能退休。executor/review 还检查事先绑定的 state-root 资源范围；任务转交历史不丢失。

对账新增 `resolutions/reconciliations`，不改原 jobs 状态、owner stopped 标志或历史时间。旧 owner 被 fence，下一代仍要求当前入口的新确认。`status.reconciled` 给出原 owner 和完成对账代次。

### 仍不能补造的证据

升级前没有预先绑定的旧 owner/job、孤儿 executor，或既没有返回记录、也没有成功同 run 恢复链的调用，没有足够来源证明结束。它们保持 `missing_bound_completion`；旧未覆盖进程的观察也持久保留，退出不自动清除（`missing_prelaunch_binding`）。新代码补上的预执行绑定和执行端返回记录解决后续父失联/孤儿自然完成，不把新协议追认到旧运行。启动后、登记前的同一精确进程身份稍后完成登记，可变为覆盖；原观察历史仍保留。

升级前已经留下、没有 action_returns 的 TS unknown 记录仍缺证据；新代码不能为过去补签。模型被信号/超时中断且资源收尾未证实的 TS 调用也保留 unknown。此入口不从 CLI 日志或单个模型回执推测整项工作结束。缺 witness、目标漂移、旧 PID 被复用、缺少容器/Boat 结束证据均不能恢复。首次加载必须沿自然轮次完成旧运行，不能把切换旧运行的证明交给本命令。

## 由部署 owner 在自然边界加载

本 PR 不部署。不能把更新磁盘文件当成已有进程已接入。

1. 固定经审查版本与三个 launchd plist 原参数，盘点在途 decision、图动作、executor/Boat 和 detached review。
   不读取或复制 plist 环境值。保留原版本和恢复路径。
2. 旧代码没有可靠全局维护入口。逐个等待原轮次自然完成；确认相应进程及其任务、detached worker/容器已结束后，
   才能由部署 owner 停空闲调度器并加载新代码。不能为安装本入口先杀活跃父服务。
3. 加载全部新入口，保持既有 `--review-sweep --review-sweep-max-running 2`、模型来源、私钥路径与 Boat 参数。
   #2062 的 `--model-rules` 传递由其 owner 管理；本补丁不引入或改写该接口。
4. 首次核验 `status` 中四类 owner；request 后各入口须显式确认当前 generation。
   旧代码进程仍存在、入口未出现或资源核对失败时只能是 unknown，继续等或修复，不卸载活跃服务。
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

Wayfinder 的临时入口快照通过 `scripts/wayfinder-maintenance-fixture.mts` 复制 TS/Python 准入助手，并显式向 `MaintenanceOwner` 传入快照内的 `maintenance` 目录；不使用生产维护根。构造点变化会使夹具立即报错，不能静默恢复默认根。壳层测试同时验证 dry-run 不生成维护账本，live 快照的准入调用使用临时根，原业务断言保持不变。

## 接入接口与回退边界

executor 的原子准入接口为 `Gate.admit_executor(owner, run_id, ticket, state_root, source_repo)`，结束使用 `settle_bound` 验证返回链与资源；预留未启动撤销仅供实际启动异常分支，没有 CLI force 入口。

Python `Owner(lane)` 提供 `poll/admit/reserve/finish/coverage/stop`；TS 通过 `.sandcastle/maintenance.mts` 调用同一账本。`reserve` 只供 detached review 交接，`finish(natural=False)` 保留 unknown。入口覆盖依赖当前解释器命令识别及本地 PID/启动时间（秒级），不是操作系统级全请求拦截；自定义启动壳与远端/T3 owner 必须另行盘点。

回退旧代码同样只能在全部在途工作自然结束后，由部署 owner 恢复原版本和原启动参数。保留维护账本及回执；回退后旧进程不具备本协议，不能继续沿用此前 drained 结论。恢复派发用本代次 resume，代码回退、代理升级与全局 READY 均不是该命令的功能。
