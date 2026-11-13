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

领取粒度：decision 单票/考古任务、Wayfinder 单图动作/放行动作、executor 单票、review 单次 PR/head/attempt。
executor 在登记票之前领取，原任务跨轮使用同一在途记录；未领取的新票在维护时不登记、不启动。
关闸前登记过的任务继续原来的 legacy、SPEC、票锁和发布判据，不获得新的权限。

review 父进程先持久预留，再 `Popen(start_new_session=True)`；子进程原子接收这份预留，
即使接收前已关闸也能继续。预留只能接收一次。父进程退出或没有 children 不消除预留。
正式审查还检查 supervisor 与容器结束回执；缺回执或 `container_closed != true` 不计完成。
executor 复用 `_worker_activity` 的本地/Boat 生命周期证据，仍在途或 effect_unknown 的 worker 不释放维护记录。

owner 绑定 PID 与启动时间。正常退出显式记账；进程消失、非正常失败和不完整回执保留 unknown，
没有 TTL、心跳过期自动释放或 TCP 空闲推断。重启会登记新 owner，不能覆盖旧记录。
异常待对账时，保留账本和原任务回执；此版本没有“强制清零”命令，必须修复/补齐原生命周期证据后再评估维护。

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
python -m pytest .sandcastle/deepagents-pilot/tests/test_maintenance.py
python -m pytest .sandcastle/deepagents-pilot/tests/test_queue.py .sandcastle/deepagents-pilot/tests/test_review_sweep.py -k maintenance
npm run typecheck
```

测试使用临时账本、真实 SQLite 多进程竞争与管道同步；fake 工作者不访问模型或生产控制根。
包括关闸/领取竞争、已领取持续推进、真实 detached 子进程接收与结束、缺入口确认、失联重启、精确代次恢复以及旧 freeze 不变。
