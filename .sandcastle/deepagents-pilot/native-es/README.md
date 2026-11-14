# 原生 ES 显式集成候选（默认禁用）

本批把真实平台 API 接到既有 `macos-es-v1` 消费协议。collector/helper、IPC 动态库均可编译；
新增 TS 本地执行边界的显式选择路径；未启用现役配置。只有 root 保护的签名产物及内核 peer 认证会话
可写原 Gate 的本机资源封闭记录。开发消费端与隔离测试仍是 `trust=offline`，不能签生产 drained。

## 编译与不启动 ES 的检查

在 macOS 13+ SDK 环境，输出放证据目录：

```sh
.sandcastle/deepagents-pilot/native-es/build.sh /absolute/evidence/es-build
.sandcastle/deepagents-pilot/native-es/check.sh /absolute/evidence/es-build
```

`build.sh` 只调用 Clang/linker，不签名、不运行产物。`check.sh` 增加纯 framing 测试、临时 Unix socket
上本次子进程的真实 `LOCAL_PEERTOKEN` 双向身份核验，以及两个程序无参数返回78的默认禁用检查。
它从不调用 collector 的 development 入口，不创建 ES client。测试不使用签名私钥、sudo/FDA 或模型。

产物：`maintenance-es-collector`、`maintenance-es-helper`、`libmaintenance-es-ipc.dylib`。
没有 launchd plist、安装脚本、entitlement/profile 占位伪件或现役配置更改。
现有 Swift approval-signing 工具处理人工审批签名，未提供 ES/Unix peer 设施；本适配器留在原 pilot 模块，
不复用审批私钥或建立另一套调度/账本。

## 各组件的职责

- **collector.c**：单 ES client、串行 callback；仅订阅 NOTIFY_FORK/EXEC/EXIT。在事件分支前检查版本≥5和
  global_seq_num 连续性。初始、每条事件及 ARM 前检查订阅集合、path/process event mute 与三类 inversion。
  任一缺口或 API 读取失败即失效；不自动 unmute 默认保护路径。输出只含白名单 audit token/epoch/序号/枚举/image别名。
- **common.c**：`LOCAL_PEERTOKEN` 取完整内核 audit_token；以 `kSecGuestAttributeAudit` 查动态 SecCode，
  按调用方提供的固定 requirement 校验，拒绝 ad-hoc。requirement 文件必须 root 所有、普通文件、非 symlink、
  不可被组/其他用户写入。没有内置 Team ID、bundle ID 或“任意签名即可信”的默认 requirement。
- **helper.c**：先核自身签名及对端 root collector 的签名；连接后 REGISTER，阻塞等待一次 ARM。
  ARM 前不 fork 业务。ARM 后只 fork/exec 一次，保留业务 stdio和退出码；START、真实 wait 结果走独立 socket。
  WAIT 后等待持久化回执或 EOF，让 collector 能在 helper 仍活着时校验精确 peer。IPC 丢失不杀业务、不重试模型。
- **maintenance_es_native.py**：`DevelopmentConsumer.accept` 消费专用 stdout；`consume_stream` 在 EOF、
  畸形帧或来源丢失时撤销来源并关闭许可写管道。复用既有原子准入、EXEC/peer绑定、事件归约与外部资源判据。
  `claim_launch` 在发送 ARM 前持久消费许可；发送失败不能重传重派。START 的 PID 只用于选择已记录的真实 helper→child
  FORK边；ES尚未送达时等待，不能从PID自述签绑定。真实wait落库后发送 WAITED。

helper PRIMARY 退出不等于全部资源收尾：ES 后代仍活或 Docker/Boat 绑定证据未齐，不能 COMPLETE。
collector EOF/退出只撤销后续许可；已启动 helper/业务自然继续，不能靠停止 collector 实现排空。

## 开发接口与精确身份来源

collector stdout 是独立 JSONL 控制管道；不是模型日志。记录有 `source/event/register/started/waited/lost`。
stdin 只接受 `ARM resource nonce permit`、`WAITED resource nonce`。写端必须属于启动该 collector 的受管消费进程，
不可把任意文件/网络记录接入后声称它是真实来源。此 development 管道仍没有生产信任提升能力；
新的 managed socket 会话另走下面的认证入口。

`source` 只在签名、订阅及覆盖检查通过后发送；首条 ES 消息仍检查最低版本。原 `prepare` 要求已有有效事件前沿，
所以只有 source 消息而无事件时不能领取 ES 动作。签名未验证的 EXEC 使用保留别名 `other-executable`，不能配置成 helper 别名。

调度器可显式调用 `scheduler_identity(library, socket_path, collector_requirement)`：动态库在**调度器本进程**连接
collector，核对端 root/signature，再请求只读 IDENTITY。collector 返回该连接的真实 kernel peer token，动态库核 PID/euid。
IDENTITY 不授予 helper 签名状态或 ARM。该身份可传给原 `prepare`，Gate 继续核 owner PID/存活身份；禁止用子进程探针的
身份冒充调度器。然后调度器创建新的受管 helper，消费端等待该 helper 精确启动 EXEC 与注册身份一致。

独立 development 身份调用仍不自动接入调度器；新 TS 选择入口使用 SESSION，一次绑定既有 owner/job/resource 与新 helper。
没有自动启用配置。显式 development 参数也不是部署授权，真实运行须完成下列前件。

### 程序参数合同（仅供后续受控接入，不是本轮执行命令）

- collector：`--development-only socket-path collector-requirement-file helper-requirement-file image-alias helper-uid`
- helper：`--development-only socket-path collector-requirement-file helper-requirement-file resource nonce image-alias -- command args...`

socket 必须是新路径，父目录 root 所有且不可被组/其他用户写入；不覆盖已有 listener。socket权限0600，归属指定helper UID。
最多64个并发连接，已结束连接槽可复用；跨连接/重启的旧nonce和许可重放由持久归约器拒绝，而非依赖fd号。
requirement 必须由签名 owner 提供并独审为自有受管产物的精确约束，不能使用宽泛的 `true`/仅平台签名约束。

## 已验证与未验证

已完成实际 SDK 编译/link；隔离 socket 的 LOCAL_PEERTOKEN 确实返回本次连接双方的准确身份。
假来源轨迹验证了 C wire schema 对应的消费状态机、先持久claim后ACK、延迟FORK、EOF/覆盖失败/签名不匹配等拒绝路径。
假来源不构成 ES 或有效签名来源。未运行 collector development 模式，也未创建任何 ES client。

尚未验证：自有批准签名的正向 SecCode/ES 建立、真实默认 mute 覆盖是否满足、kernel event→完整消费链的顺序与压力行为、
签名 helper 的真实业务wait与全部后代闭包、collector失联下的真实系统反例。不可把编译或内核peer单项通过当作这些验收。
若默认mute覆盖生命周期事件，当前实现准确拒绝；不自行放宽覆盖或修改保护配置。

正常 SIP 的开发也需 Apple 批准的 ES capability、匹配 profile 与开发签名；ad-hoc不能替代。Developer ID 分发须另核授权类型。
还需用户授权的 root/FDA、签名产物/配置完整性及受控真实验收。前件未齐，真实 backend 保持禁用。
macOS现役可用性、六历史资源域、旧无绑定来源仍独立BLOCK；不得合入后借自动ff/重启绕过发布门。

### 有界 wire 与输出

IPC 行最多1023字节、单字段最多128字节；仅接受指定动词、精确字段数与单空格分隔，拒绝尾随内容、内嵌NUL和截断行。
PID/UID/退出码使用逐位十进制解析，在乘加前检查各自上限，拒绝正负号、溢出和数值尾随垃圾。
格式输出使用编译器可检查的字面量 `snprintf`，统一检查负返回值和截断，再写完整片段；不发送截断ACK或JSON。
流写失败退出74，消费端EOF撤销来源；socket写正确处理EINTR、短写和失败，不重授已消费许可。
`check.sh`包含确定性的三字节短写/EINTR/中途失败注入，以及截断、超长字段、数值边界和只读流写失败验证。

## 显式调度器选择与原账本消费

decision-claimer 与 Wayfinder 支持 `--maintenance-es-config /absolute/root-protected/config.json`。
省略时完全保持原本机执行路径；纯离线预览不新增账本前件。TS 的 `maintenanceCommand` 将选择传给原
`maintenance_local.py --es-config`。Python executor/review 的原同 run 与 Docker/Boat 判据不变；本次不替换其执行器。

配置只接受七个字符串字段：`library`、`library_requirement`、`collector_requirement`、`helper`、
`helper_requirement`、`socket`、`image`。配置、动态库、helper及requirement文件必须是绝对路径、root所有、
每级祖先无symlink且不可组/其他用户写。先以系统 codesign 验证精确 requirement 与非ad-hoc，再加载动态库；
C层重新核对socket对端的root UID、完整LOCAL_PEERTOKEN与动态SecCode。没有fixture/信任布尔或fallback开关。
签名owner须提供精确的自有产物约束；当前仓库没有可用签名配置，不能启动该路径到真实ES。

后续受管启动方提供 `collector --managed-socket socket self.req helper.req image uid`。
本候选只连接既有受管collector，不sudo、不安装服务、不自动启动root来源。原local supervisor先setsid并绑定原resource，
然后由本进程发 `SESSION resource nonce image`。collector返回其内核观察到的peer身份及全新epoch，身份必须匹配该监督器。
每session独立epoch/nonce/ARM，单ES client广播相同有序事件；双动作不串行。collector最多64连接（session与helper各占一个），
写端有界超时，短写/失联撤销来源，不重派业务。SESSION初始握手有5秒期限。

`NativeES`复用已审归约器，持久证据放原SQLite的独立native表；不能重开旧epoch或将旧resource追认为新动作。
离线表与native表分离，原`OfflineES`不升级trust。只有原已领取job的未使用resource可进入SESSION；
关闸后原动作继续，下一次work仍由原原子admit拒绝。收到精确helper EXEC与REGISTER后先持久消费许可再发送一次ARM。
helper的`--managed-session`验证与原开发helper相同，只fork一次业务，保留stdio与真实wait码。

消费端等待实际wait及最后归属进程EXIT；绑定的外部资源未闭合则不能seal。只有认证NativeES可把精确epoch、
监督身份、业务wait及域闭包提交到原`local_resources/local_resource_domains`。来源或消费端死亡、事件丢失、
持久化失败仍unknown；已接受helper继续自然wait，禁止失败后直接spawn。已持久的native闭包可由原action-exited/poll/reconcile路径消费（包括consumer已退出之后）；
消费只核原epoch/任务/监督身份及资源，不重开source、不补造callback return、不改变维护代次。监督器在域未闭合期间继续存活；
来源失效时保留业务退出码而不补签闭包。配置失败、尚未Popen的取消及Popen同步失败分别记录未派发证据，不伪造业务wait。

### helper 提前终止与证据等待

helper 的真实 `wait()` 结果与维护闭包分开处理。若 helper 已终止而本 SESSION 尚未发送 ARM，
监督器在与 REGISTER/许可消费相同的锁下先撤销本 session，再返回原退出码（信号转为128+信号）。
这不是“从未启动”的证明：延迟帧仍可能在途，因此不写 not_started、业务 wait 或 seal，原占用保持 unknown。
已读取但尚未处理的 REGISTER 也不能在撤销后发送 ARM；其他 SESSION 不因该本地决定被主动关闭。
ARM 已消费/发送的路径仍等待原精确 wait/进程域闭包或来源失效；短写不回滚许可，不重派。
提前终止不靠退出码78、超时或全局来源EOF作判据，真实来源验证要求不变。

### 本批验证边界

共享SESSION编排的隔离来源走同一个prepare/register/ARM/wait归约及原reserve，但保持offline表，
即使模拟轨迹完整也断言原Gate不接受封闭。覆盖关闭后已领取推进、ACK失败、source EOF、seal持久化失败、
实际无模型子命令退出23、启动同步失败、旧epoch/resource拒绝、缺可信配置拒绝与无fallback。
现有双动作交错、后代逃逸、外部资源未闭合、序号缺口和短写测试继续适用。

真实认证连接到ES、正向签名来源、完整原生多session负载、consumer死亡后的真实内核闭包仍未运行。
不能以fixture或编译证明这些门通过；root/FDA/profile/签名及现役验收、六历史域与旧无绑定发布BLOCK保持。
