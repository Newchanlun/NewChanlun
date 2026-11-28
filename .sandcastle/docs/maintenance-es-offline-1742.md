# macos-es-v1：离线因果闭包与真实后端接入边界

#1742 保留 HOST 原生 CLI 和 `127.0.0.1:8318`。本模块验证原生 ES 路线的协议，未启用 ES 后端。
[原生开发适配器](../deepagents-pilot/native-es/README.md)已提供可编译的 collector/helper 和专用管道消费端，尚未进行真实 ES 运行验收。
它不创建 ES client、socket 或后台服务，不启动 eslogger，不改变现役准入选择。

## 离线验证入口

在项目已有 Python/Node 测试环境运行：

```sh
python -m pytest .sandcastle/deepagents-pilot/tests/test_maintenance_es.py -q
python -m pytest .sandcastle/deepagents-pilot/tests/test_maintenance_poll_recovery.py -q
```

`pilot1742.maintenance_es.OfflineES` 使用测试的 `Gate`，将来源、动作和审计记录写入同一个 SQLite。
`prepare` 必须经原 `Gate.admit` 和 `reserve_local_resource` 新领取；关闭后不允许新动作，已领取动作仍能完成握手与执行。
没有旧 job/resource 接入接口，不给旧动作补 ES 来源。默认生产维护根被拒绝。

所有源记录持久标为 `protocol=macos-es-v1, trust=offline`。离线归约器从不写入旧
`local_resource_domains`、`sealed_at` 或生产完成回执。即使离线轨迹到达 COMPLETE，原 Gate 仍拒绝该资源终态。
不存在命令行或环境变量把 offline 证据升级成可信来源。

## 五个层次各有独立证据

|字段|依据|不能代替的证据|
|---|---|---|
|source_ready|单源版本≥5、完整 FORK/EXEC/EXIT 订阅、覆盖核验无缺口、连续序号|真实签名、root/FDA 与 mute 核验尚无适配器|
|action_armed|新准入资源、唯一 nonce、kernel peer 对应的精确启动 EXEC、持久化许可|ACK 不表示已派发；重复ACK不能再次派发|
|process_closed|同源连续事件中，最后活成员的 EXIT 因果前沿|业务 wait、Docker/Boat 终态|
|business_waited|原 peer、已消费许可、已绑定 primary 的真实 wait/code 记录|业务成功；信号/失败码保留原值|
|resources_closed|process_closed、business_waited，以及已有绑定的严格资源判据|生产 Gate 验收与全局 READY|

`offline_phase` 分 REGISTERING、ARMED、RUNNING、PROCESS_CLOSED、COMPLETE、UNKNOWN；
`production_accepted` 始终为 false。不得把 COMPLETE 解释成现役 macOS 门已过。

## 来源与身份合同

- 输入只包含版本、序号、事件枚举、epoch、8个整数的 audit token、受管 executable 身份别名。
  不采集 argv/env、路径、完整 ES message 或模型内容；wire 中出现额外字段即拒绝并 taint 来源。
- 真实后端须使用一个 ES client 的串行 handler，保留系统交付顺序。归约器在任何事件分支前检查
  epoch、版本和连续 global_seq_num；首序号不假定是0或1。无关事件也参与序号检查。
- `Coverage` 的离线配置用于驱动拒绝路径。未来适配器须实际核查默认 path/process/event mute、
  inversion 和应用转发路径，不得把此结构当成接受操作员布尔自述的认证接口。
- `AuditIdentity` 保存完整 audit_token_t；pidversion 随 exec 迁移。peer 必须来自 LOCAL_PEERTOKEN，
  不能从注册消息中的自报PID构造。预期调度器 PID 必须对应当前 Gate owner；其 token 也由可信适配器取得。
- 只有 prepare 前沿之后、预期调度器 FORK 出的新子进程、紧接受管 helper 签名身份的启动 EXEC
  才能成为根。非受管中间 EXEC 不追认。若该子进程在 helper EXEC 前已 fork，拒绝 ARM，避免带入未登记后代。
  调度器的其它 sibling 及其后代不归入该动作。

## 注册、ACK与一次派发

`register_peer(resource, nonce, peer)` 可以先于或晚于启动 EXEC；两者精确匹配前 `arm` 不返回许可。
错误身份、错误image、旧nonce、来源失效或缺EXEC都不会进入派发回调。
同一调度器可并行 prepare 多个动作；每项保留 prepare 前沿之后的候选启动 EXEC，只有注册 peer 精确匹配的候选才成为该动作根。
注册早到只选择匹配的后续 EXEC，注册晚到则选择已记录的候选；其它 helper 的正常执行不污染该动作。
候选在注册前已经退出或 fork 的违规事实仍保留，不能靠迟到注册追认。

许可先在 SQLite 提交，再返回 ACK。`launch` 在同一账本事务中消费许可，提交后才进入离线派发回调；
并发或重复 ACK 最多进入一次。消费提交后、派发或绑定之前崩溃不能重用许可，仍需原严格证据恢复。
注册和许可不是新一套调度：任务ID、owner、代次、关闸原子边界继续由原 Gate 管理。

当前 `Peer` 和 `launch` 回调仍是离线测试接缝；原生开发适配器在 C 层另行做 LOCAL_PEERTOKEN/SecCode 核验，不把 fixture 升级为认证来源。
真实 helper 必须经受管签名核验；在 ARM 前只做注册与阻塞，不 fork/exec 业务、不调用共享模型。
将来接入时必须保留这条可测试不变量，不能把任意已有长寿进程作为根。

## 事件归约与故障

FORK 从活成员加入子执行身份；EXEC 原子迁移 old→target 并保留归属；EXIT 只移除精确执行身份。
setsid/reparent不删除已记录归属。旧token、同PID冲突身份和重复fork不允许释放新执行根。
活集合首次为空即记录 process_closed 的序号；不等待全机静止，不要求无关消息队列为空。

来源缺口、乱序/重复、内部丢包、覆盖变化、事件持久化失败或collector重开都会 taint 未闭合动作。
重新建立来源必须用新epoch和新动作，不能改写旧unknown；来源与原事件审计保留。
所有失效入口（畸形 wire、lost、覆盖变化、内部丢包和来源替换）先撤销本实例对旧 epoch 的准入，再尝试写 taint。
即使 SQLite 写入失败，恢复数据库后旧 ACK 仍不能 ARM/launch；本实例 status 报告本地撤销原因，不读取旧 ready 冒充可用。
无法写入的失效事实不能假称已持久化；重开 collector 会先将原有 ready 来源持久标为 collector_reopened，完成后才可建立新 epoch。
新 epoch 不恢复旧动作或旧许可。

已在完整因果前沿封闭的本地域不会被随后无关事件的缺口重新打开；来源本身仍标失效，不能派新动作。
这只保留已经成立的过程闭包，缺业务wait或外部资源证据仍不能 COMPLETE。

绑定 Docker/Boat/正式review时，沿用 `Gate._resources_idle` 和原生命周期文件判据；缺失、错配、异常或仍在途
均不能由本地集合为空代替。经独立daemon/XPC/launchd生成的外部工作必须在原派发接口另行绑定，不能用ES后代猜测。

## 真实后端仍需交付

1. 正常 SIP 下，真实开发也需要 Apple 批准的自有 ES entitlement、匹配 provisioning profile 与开发签名；ad-hoc 不能替代。开发批准不自动覆盖 Developer ID 分发，分发类型与对应 profile 需另核。当前无已核可用签名来源，不借第三方签名，真实 backend 默认禁用。
2. 真实 root/FDA 前件与受管 collector/helper；分别处理 NOT_ENTITLED、NOT_PERMITTED、NOT_PRIVILEGED。
3. 验收已编译的原生 LOCAL_PEERTOKEN、签名身份、单client覆盖配置与消息适配器；接通受管开发调度调用链，无原始消息/环境泄露。
4. 在受控窗口复用同一轨迹做真实系统验收：fork/exec/setsid、慢consumer丢包、observer丢失和高并发出生退出。
5. 独立审阅后另行接通生产 Gate 证据适配；不能把本模块的 offline 标志改成布尔 true 就启用。

六项历史资源域、旧无绑定 sighting 的证据缺口均不由新epoch解决。现役自动ff/重启可能加载main，
所以 PR 发布BLOCK保持；本实现不授权合入、部署、停止服务或共享proxy维护。

## 独立的observer恢复修正

`Owner.observing` 一次可恢复poll错误不再永久退出。`observer_faults`单独保留控制故障，期间status保持unknown；
同一owner成功poll后只清除该控制故障，不恢复资源coverage、不完成任务、不清理ES来源taint。
持续错误继续unknown；退出observer上下文仍终止其轮询线程。
