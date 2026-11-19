# X 历史模拟执行接口

`x_execution_session serve --db FILE --profile FILE --writer-epoch N` 用 `x-execution-profile/3`、
`mode: simulation` 与 `history_simulation` 对象运行历史撮合。X 不续写或恢复已有 `/1`、`/2` 历史模拟库（即使还没有命令）；要继续撮合须另起空库重放。不带历史撮合的模拟骨架以及 dry-run、experiment、production 仍使用 `/1`。

## 冻结输入

`history_simulation` 对应 `runtime::Profile`：模型、session_id、session_generation、
x_id、source_namespace、source_epoch、X socket、E/S authority socket/身份/epoch，
timeout_ms 与 max_frame_bytes。路径必须绝对，三端点不同。完整对象在 X SQLite
冻结；同库不得切成其他 profile，也不得换模型、来源或权威端点续跑。

模型 ID 是 `history-sim/bar-batch-known-frontier/1`。当前支持 per_leg、整数 tick、
整数 quantity/money quantum、确定性 seed=none、显式具名费率与市场滑点。
limit_role/market_role 必须由具名 role_source 明示 maker/taker，不按订单类型暗填角色。
RD12 固定为 `per-leg-source-attribution/1`；未知政策拒绝。netted 返回 Unsupported。容量分配复用经济域 ADR0032 算法，不自建配额算法。

## 单行 JSON wire

请求：`{"protocol":"x-exact-simulation/1","op":OP,"payload":VALUE}`。
每帧以 LF 结束并关闭写半边（EOF），读取回复后关闭连接；字段形状见 `runtime.rs` 与 `model.rs` 的具名类型。

- AcceptExact：payload 为完整 ExactCommand。先按 X 实际装载的 `model` 规范内容摘要核对 `command.model_ref`（`model_id`、`revision`、`content_hash = sha256(canonical_json(model))`），不符即以 `IdentityConflict` 拒绝且不问 E/S；再查询冻结 E 的 ReleasedExact，
  核全命令、计划/条件摘要、会话与 epoch 后持久 Accepted，不问 S、不产生调用权。
- AdvanceBar：payload 为 Batch。每个 close_change 解码后必须等于已接纳命令的 change（批合同保留 JSON 数字）；
  真正动作前向 S 请求 ExecuteCommitted，绑定 E release 收据与命令 eligibility_ref；
  X 先持久 MayHaveCalled，再原子提交模型状态、不可变原件、批结果与 Observed。
- QueryCommand：payload 为 command_id 字符串，回状态、x_accept 三相时钟与 E causal_refs。
- QueryOriginal：payload 为 external_fact_id 字符串，回 X 冻结的完整原件。

E/S wire 是 `x-exact-authority/1`。op 分别 QueryReleasedExact 与
RequestConditionalExecution。业务请求包含完整 ExactCommand、command_hash、会话、
authority_id/epoch 与可选 release_receipt_id；回复另含 state、receipt_id、commit_ns。
业务请求放在 IC:9 共同信封里（schema_revision、session、source_namespace/epoch、message_id、
producer_id/epoch、payload_hash、causal_refs），走 ADR 0056:39 同一个 `session_transport`，E 端就是
经济会话的正式 serve 入口与 `authorized` 判据。profile 的 e/s 各自冻结 schema_revision、reply_namespace
与 producer_id；回复整帧须等于由原请求经 `reply_envelope` 重建的结果，与 E↔B 财务输送同一判据（#1407 C2）。
S 回复必须同时绑定原 E release_receipt_id；命令资格引用必须等于 S receipt_id。
未知、Denied、不可达、不同内容/身份/epoch 均不取得调用权。

ConditionEvidence 清单由 profile 的 `conditions` 冻结，与 E 冻结原件 `exact_release.conditions` 是同一份
获准清单（含 ADR 0052 裁定二的 `model_coverage`）。命令证书的清单须与它逐项相等，否则 Unsupported。
每项须带齐九字段，能力与阶段须是 E/X 共用配对表（`economic_session::exact_command::CONDITION_PAIRS`）里的
已知配对，阶段前缀只能是 E./S./X.，失败语义为 Denied；X 阶段只有 simulation-local-transaction/1（#1407 C2）。
清单还须完备：配对表的四项能力（E 的 released-exact/1 与 model-coverage/1、S 的 execute-committed/1、
X 的 simulation-local-transaction/1）各出现恰一次，缺项按 MissingDependency、重复按 Unsupported 拒绝；
E 冻结原件与 X profile 走同一个 `check_required_capabilities`。
正式 E 的 C3 模型绑定合同用 `tb03b-finance/6`（保留 `tb03b-finance/5` 既有原件、旧收据与测试含义不变）；`/6` 将冻结的 `exact_release.model_coverage.model_ref`（含 64 位十六进制 SHA-256 `content_hash`）直接编入 `ExactCommand.model_ref` 并进入 `command_hash`，X 的 `/3` 只接纳带有效 `model_ref` 且与实际装载 `Model` 内容摘要完全一致的命令，因此旧 `/5` 命令不得借用 `/3` X 产生外效。X 的 `e.socket` 指向该会话 E，其来源须获 `QueryReleasedExact` 权限。模拟条件执行的 S 由夹具按冻结的 eligibility_ref 发证，真实 S 签发归 #1416。

订单投影的 revision、quantity 和 price（市价为 exec_index）先编码成规范十进制字符串，再计算 plan_hash。整个命令还冻结 first_quantity、allocation_id、目标 X 与 x_epoch、以及 `model_ref`（`/6`+`/3`），一并进入 command_hash。接纳钟、权威 commit_ns、release_commit_ns 与执行 claimed_ns 同样使用字符串；数字、前导零或越出 i64 的文本均不属于该合同。

## 时间、恢复与消费边界

E 的 /5 组件按冻结的 `clock: {kind:"logical-bar/1",bars:{init:"0",messages:{"ReleaseExact-alpha":"2"},recover:["3"]}}` 选择调度读数。每条写消息须在 messages 声明，以数组区分恢复代际时按恢复索引取值；三相使用同一 bar，没有墙钟回退。

X 不读系统时钟。simulation 证据类的时钟固定为 `logical-bar/1`（ADR 0056:52，定义见
ADR 0052:296）：checkpoint 与前沿只认 bar_index。接纳三相 received/first_known/commit 都取
已提交前沿 last_bar+1（空历史为 0）；AdvanceBar 的调用占有 claimed_ns 取本批 bar.index。
批须连续，故占有读数不早于其命令的接纳读数。字段名沿用 `*_ns`，
在本域存的是该 bar_index 读数，不是纳秒。E release 与 S 执行回执的 commit_ns 须在同一时钟域：
要求 received <= first_known <= commit、first_known >= E release_commit_ns，调用占有不得早于
S commit_ns；写入与启动冷审计共用判据，早 1 个读数即拒（#1621）。同一输入的两个独立进程因此
留下逐字节相同的全部 X 表（ADR 0038）。
同 ID 同内容重送读原结果；改内容冲突。MayHaveCalled 只允许同一完整批内容恢复，
这是本地 SQLite 模拟 adapter 的幂等合同，不授权网络场所重发。

已准入订单在下一 bar 批执行，收盘撤改不抹当根成交。限价严格穿越、开盘取优，
市价只在具名 exec_index 收盘槽；批内顺序 Unknown。fill、fee、scenario bust 各有
独立原件，fee/bust 指回原 fill。原 fill 不因 bust 被改写或删掉。

经济会话须冻结 history_simulation_source（来源身份、producer 身份、x_db、模型摘要）。
CaptureExternal 对照 X 库原字节后可 Recorded+Pending。完整经济分量/short 归因未接通，
Resolve/Apply 明确拒绝；不得把 Pending 当作持仓或完整回放验收。

#1375 补录一个已知的模拟批时，使用当时 X 的 QueryBatch 原回执（/1 归档直接使用已保存回执，不需启动 X），对完整规范 JSON（键排序、紧凑 UTF-8、不含传输换行）取 SHA-256，再查询 E：

```sh
e_economic_session inspect-simulation-capture-batch --manifest MANIFEST --db E_DB \
  --batch-id BATCH_ID --batch-receipt-sha256 RECEIPT_SHA256 --x-id X_ID --x-epoch X_WRITER_EPOCH
```

这个本地只读命令使用 E 库绑定的 manifest，不从请求接受 X 库路径；在 X 的同一
只读事务中按持久版本选择核验：`/1` 用原数字命令和整数时钟，`/2` 用含首次量、分配身份的 IC:13 命令和时钟（归档只读），`/3` 在 `/2` 基础上强制核对 `model_ref` 与 X 实际装载模型内容摘要。
外层版本与内层标记不符、命令或 E/S 原收据不符、批重演或原件对不上，都拒绝；不换版本重试。
完整回执的摘要用于固定该批；回执中的 state_content_hash 仍是单独的状态读数。结果中的 `e_cut` 是接纳状态
所依据的切面；每个 `Recorded` 项带原收据和当前 Pending（若存在）。获准来源
把 `Missing` 项的原字节、指针和事件时刻走原 CaptureExternal 补录；有过发送的
请求沿用原消息和 token，不因未确定回执换身份。重查同一批可核对补录结果。

答案只覆盖指定的已提交批。这个命令不建立故障结束界、不核清 Pending，也不改变
放行资格；它会全量审计 X 历史，供恢复取证使用，不进入每条 Capture 的热路径。


## 容量 epoch（#1381 R3）

input/scenario 的 capacity_manifest 与 E projection_manifest 分属不同身份、累计和用途。
X 从完整已知命令状态和完整bar计算可成集合；不能由请求方传入子集。集合、额度和合同
语义不变时保留冻结 requested_q 与累计C，只调用现有ADR0032的 A(Cnew)-A(Cold)。
正常成交耗尽的零余量成员留在冻结向量中，不因它退出资格集合而重置；纯bar/ref/容量
数值变化或不改变资格的改价也不重置。实际资格/成员边界才封存旧证据、以合法剩余量
创建新epoch。空集合/全部完成关闭，不造空投影。收盘市价槽过了唯一exec_index即无人可成，
部分或零成交的epoch在该bar同批关闭，不留到下一bar。family累计从不因epoch归零。

限价区间先消费同方向总budget，收盘市价槽只用余额；买卖方向独立，不按每槽复制额度。
每个输出绑定获准命令、family、revision和projection_manifest，容量身份不授执行权。
QueryBatch 的字符串payload为request_id，返回同事务保存的capacity_transitions和
capacity_evidence；不可变fill、fee、bust保留原容量/投影因果引用。close变化先规范排序，
同close同family多个动作拒绝，不靠到达序选胜者。


## 调用前验证与不确定窗口恢复

AdvanceBar 在取得任何 S 资格前完成同一模型的完整只读计算及全部精确命令核对；
非法 OHLC、close 变化、容量、金额或 bust 不消费 Accepted。各命令的 S 请求帧也在此时编码并核帧界，
超限按 Unsupported 拒绝整批，不写 PendingBatch。随后先持久唯一 PendingBatch，再逐条调用 S、
保存实际 ExecuteCommitted 回执为 ExecutionReady。全部回执保存后才置 MayHaveCalled；模型状态、
原件、Observed 与清除 PendingBatch 同事务提交。pending 期间只接受同完整批内容恢复或只读，
不能用空 close 异批绕过。

对每条 Accepted 命令，X 先连接 S，连接成功后才置 ExecutionRequested，再写请求帧。
权威期限（timeout_ms）只从写帧开始计，不含这次 ExecutionRequested 的本地持久写；否则慢盘会在一个字节都没
发出时超时，把命令误标成可能已发出（#1407 C2）。

残余窗口（未消除，归 #1407 C2 后续，与真 S producer 一起处理）：上面只挪了 X 自己的期限。对端若走
`session_transport`，它的读期限从接受连接起算（`io_connection_inner`），而 X 是连接之后才做这次持久写。
持久写超过对端的读期限时，对端回输送层的 `{"ok":false,…}` 或直接关连接；X 此时已持久 ExecutionRequested，
S 却一个字节都没处理。之后只能查 QueryExecuteCommitted，得到 NoRecord，按下段规则保持 pending，没有自动出路。
本仓现有的受控 S 夹具不设读期限，测试覆盖不到这条路径。没有改成「先持久、再连接、连接失败退回 Accepted」，
因为那要新增一条 ExecutionRequested → Accepted 的反向迁移：今天「S 不可达时命令保持 Accepted」不依赖任何写入，
改后要靠第二次持久写成功才成立，写失败就把一条确定未发出的命令留在只能查询的状态；这条迁移没有规格，也没有
真 S 可以对拍。

两类失败以此为界：

- 确定未发出：编码失败、帧界超限、连接失败。S 一个字节都没收到，命令保持 Accepted；
  同批重试照常调用 RequestConditionalExecution。
- 可能已发出：置 ExecutionRequested 之后的任何失败，包括写帧中途、关写半边、读回复、
  回执校验失败，以及置 ExecutionRequested 之后、写帧之前崩溃。这是不确定窗口，按下段恢复。

ExecutionRequested 的恢复只调用 x-exact-authority/1 的 QueryExecuteCommitted，要求返回
同精确 command/content/session/epoch/E release 的既有不可变 ExecuteCommitted 原件。
NoRecord、未知、不可达或没有确定结果时保持 pending；不得重新调用 RequestConditionalExecution
或把未查到当作再授权许可。已持久回执直接复用，不重复 S 授权。没有 S 确定原件就不能自动前进，
不清占有、不补发。正式 S producer 尚未实现本查询接缝，#1407 / TB04-D/E 必须真实消费；
受控 fixture 的唯一授权计数不替代该实证。

冷启动核批请求/结果、模型重演状态、不可变原件表、bust 账及 command/E/S 引用闭合；
缺 command、缺原件、缺实际 S 回执均拒绝恢复，不从剩余表补造证据。


## 完整原件冷重演与 pending 换代

fill、fee、bust 由提交与冷审共用的纯计算生成。冷审从空历史逐批前进，用该批以前的
原成交与 bust 累计核算，再逐字核完整批结果及独立原件/账表；不能拿最终累计倒算前批，
也不能以派生表彼此一致代替原始 batch/model 的确定性义务。既有库缺 authority_profile
或绑定不同均拒绝，不能重建绑定后换端点。

PendingBatch 与 pending_epoch 同事务保存。尚有 pending 时，任何不兼容 writer epoch
必须在 launcher 写 writer_epoch 之前拒绝；旧 epoch 仍可查既有 S 终态并完成原批。
本片不提供 pending 换代接管政策，不改旧命令/回执，不以重发 S 解锁。


## 持久化前件

X 库保存 PendingBatch、ExecutionRequested、MayHaveCalled 等「S 只授权一次」的状态。
`x_execution_session serve` 与 E 共用 `economic_session::open_durable_db`：本地文件系统、
WAL、synchronous=FULL、fullfsync=ON，并核验读回值（macOS 上 fullfsync 须为 1）；不满足即
StorageUnavailable 拒启。启动时把实际读到的存储证据写到 stderr。

## 首次初始化也是一次发布

模拟schema、初始contract/state、exact_commands和authority_profile在同一SQLite事务
内建立。X launcher还将自身x_meta/初始writer_epoch放入同一事务；提交前中断只留下
未初始化状态，提交后中断留下完整冻结绑定。已有模拟库仍严格拒绝缺profile，不能
按表为空补绑。事务内初始化函数接收Transaction类型，不接受裸Connection。


## 已知缺口（#1381 R6 正式门登记，本片不改行为）

- 回复超帧静默断开：批结果与原件内嵌完整 families 与 model，并随历史增长。
  AdvanceBar/QueryBatch 回复超过 `max_frame_bytes` 时，`session_transport` 的 serve 循环
  不报错、直接关连接；批已提交，调用方只见 EOF。长历史下会出现。
- 确定 Denied 永久停住 pending：S 返回 Denied 被当作 MissingDependency，命令停在
  ExecutionRequested，pending 批不清除；其后异批 AdvanceBar、新 AcceptExact、换 writer epoch
  全被拒绝。需区分「确定拒绝且未调用」与「结果不确定」；换代接管政策另开票。
- 同重多 family：接纳收盘变化时不限制同一 chong 同时挂多个活动 family，要到后续 bar
  两者同时可成才报 ModelOrderUnspecified；bar 须连续，此时模拟不可恢复。
- Model 尚缺 ADR 0033「版本合同字段（v1）」要求的字段（input_domain、带条款 id 的
  price_rules、capacity_source、unsupported_domains、clock/known_frontier_cut 等）。#1381 不关。
- 启动重放两次：`x_execution_session` 的 persist 与 `runtime::serve` 各调用一次
  initialize_in_transaction，两次都经 validate_existing 从空状态重放全部历史批。

## 在 Linux 复跑 #1407 C2

从仓根进入 `rust/`。L1 生成 /5 项目输入；第二步只读其中的 JSON，不复用 L1 的库。输出根选短路径（Unix socket 有长度限制）。

```sh
r=$(mktemp -d /tmp/c2.XXXXXX)
mkdir "$r/fixture"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$PWD/target}"
cargo build --locked --features production_session --bin e_economic_session --bin b_chong_session --bin x_execution_session
TB03B_TEST_ROOT="$r/fixture" cargo test --locked --features production_session --lib \
  economic_session::finance::tests::exact_release::l1_formal_entry_releases_exact_in_the_e_sequence -- --exact
python3 tests/c2_formal_entry.py --fixture "$r"/fixture/unit-* --bin "$CARGO_TARGET_DIR/debug" \
  --out "$r/proof" --twice --geckodriver "$(command -v geckodriver)"
```

Firefox 和 geckodriver 须能共用临时 profile；Snap 安装可追加 `--profile-root "$HOME/snap/firefox/common"`。省略 `--geckodriver` 只跑到真实 HTTP，不验浏览器。两轮均通过正式 launcher 启动 E 与两个 B，通过正式 X socket 提交同一份命令。看 `proof/b/summary.json` 的接纳、占有、模拟调用与 S 签发计数，`proof/b/browser/cut-{5,6}.json` 的同切面原件；`proof/{a,b}/business.json` 是包含空表在内的全表规范转储。

Q 来源需获 `QueryCommand` 权限；启用已有 `EconomicReadOpen/Page/Close` 三项权限后，既有测试页通过分页读取超出单帧的完整快照和变化，命令原件仍由 E 的 `QueryCommand` 按所选 cut 返回。

## C3 升级、退场合同候选与迁移说明（待独立评审与主控裁定）

> **审签状态：R3 候选条文（尚未批准 /2 退场）。** 前次 C2 裁定（`#1407#issuecomment-6749476649`）仅退掉 `#1942` 数值编码的 `/1` 历史模拟写入入口，未授权自动退掉 `/2` 写入入口；本节条文须经独立非作者评审与主控显式裁定后方视为生效合同。

### 1. 无法原地保全 `FIN/5 + X/2` 续写的证据依据

核查父头 `#2081`（`eabdfb02013135db78d21cb2d8a47dec0a71a555`）真实 `/2` 样本（`signed-c2-t3/a/manifest.json`、`input.json`）与 `tb03b-finance/5` 实现后，旧 `/5` 协议自身无法证明 E 授权过具体实装 `Model` 内容：

1. **原样本 `model_ref.content_hash` 仅为名/版摘要**：`signed-c2-t3/a/input.json` 的 `exact_release.model_coverage.model_ref.content_hash` 为 `e28cb65bf917085d648735d192848c2d1a9d460f0b61c3c57144055770f925cb`（即 `sha256("\"history-sim/bar-batch-known-frontier/1@oracle-1\"")`），只覆盖模型名与版本串，不覆盖费率、滑点、tick/量/金额量子、标的或撮合参数。
2. **FIN/5 wire 自身不绑定模型实装**：14 字段 `ExactCommand` 与 `command_hash` 均不含实装 `Model` 摘要；`signed-c2-t3/a/manifest.json` 亦无实装模型绑定字段。注：这证明的是 `/5` wire 自身不绑定实装模型，而非断言所有旧档外部均无任何历史证据。
3. **X 自持配置不等于 E 授权**：旧进程曾运行过或 X 本地持有 `x-profile.json`，都不能证明 E 授权过该实装模型（C3 反例 `06a767ab` 已证在 `FIN/5 + X/2` 下仅将 X 的 maker 费率分子 `1 → 10` 即可静默产生错费成交）。
4. **不伪造兼容、不放宽 `/3`**：不得给 `/3` 增加可选 `model_ref`、不得回填或重签旧 `/5` 命令、不得靠事后拆换旧二进制或仅改版本字符串假装兼容。

因此，本候选提出最小升级与退场合同：退掉可向真实历史 X 交付未绑定模型授权的旧写入口，保留全部既有收据、其他 `/5` 经济写入、非历史用途、真正隔离的 C1 离线验算以及完整只读查询取证；新执行统一走显式 `tb03b-finance/6 + x-execution-profile/3` 新会话。

### 2. 退场范围、现有能力分界与三处守门

- **拟定生效点**：本 C3 模型绑定二进制组（`tb03b-finance/6` + `x-execution-profile/3`）经独立评审与主控裁定合入/发布之时。
- **独立正式 E（`e_economic_session` / `finance.rs`）的现有能力分界**：
  - 守门守的是 **E 能否向真实历史 X 实际交付新的可兑现授权**，而不是 `clock.kind` 名称、`history_simulation_source` 归档来源或 X 当时是否在线。
  - 判据（仅复用现有冻结入口与授权能力，不新增任何开关或新入口）：当 E 为无模型绑定的 `tb03b-finance/5`（`!model_binding`），冻结 `exact_release` 面向历史模拟目标（`model_ref.model_id` 以 `history-sim/` 开头或 `conditions` 含 `simulation-local-transaction/1`），且 E 在 `init` 时钉死的 `manifest.authorized_sources` 将 `QueryReleasedExact` 授予了冻结的 `x_target.x_id` 时：
    - **已提交收据优先重取**：`write_with_ingress` 先核审计并按原消息 ID（`previous_message`）与原收据键（`receipts`）查回已提交收据；命中则原样返回原收据（同键改内容仍报 `IdentityConflict`）。
    - **新交付当场拒绝**：未命中既有收据的新 `MakeDispatchable` 与新 `ReleaseExact` 直接以 `VersionUnsupported` 拒绝，不落行、不产生新收据，且不要求 X 在线。
  - **显式退场项与保留项（两臂对比）**：
    - **必须退出正式交付的两类既有 `/5` 用法**：（a）`#2081` 形态（`logical-bar/1`、无归档源、`X` 获准 `QueryReleasedExact`）；（b）`b9d898` 祖先形态（`TestOnly` 时钟、无归档源、`X` 获准 `QueryReleasedExact`，曾由正式 E/B 放行并被真实旧 `/1` X 在 cut `162` 接纳）。两者具备向真实历史 X 出具未绑定模型授权的完全相同能力，故均须退出正式交付。
    - **保留的真正隔离 C1 离线验算**：沿用原始 C1（`1f0a42bc20^`）形态的 `TestOnly` 离线配置，其 `manifest.authorized_sources` **未将 `QueryReleasedExact` 授予 `x_target.x_id`**。该配置可继续离线产成 `Dispatchable` / `ReleasedExact` 与 `exact_command_oracle.json` 验算，但**不可能向真实历史 X 出具可兑现授权**：因 `ExactCommand::validate` 钉死 `command.x_id == profile.x_id`、`authority_frame` 以 `producer_id = profile.x_id` 向 E 发起 `QueryReleasedExact`、E 的 `Config::authorized` 拒绝未授权来源（`来源未获准`）且 `manifest_hash` 在 `init` 时钉死不可后改；同时 `/3` X 亦直接拒绝缺 `model_ref` 的 `/5` 命令。
- **正式装配入口（`production_session`）**：
  - **仅当 `x.profile` 含非空 `history_simulation` 时**，`load_manifest` 才预读 `economic.manifest` 并校验 E/X 合同配对：要求 `profile_revision == "x-execution-profile/3"` 且 `economic.manifest.finance.schema_revision == "tb03b-finance/6"`；任何不匹配组合（`FIN/5 + X/3`、`FIN/5 + X/2`、`FIN/6 + X/2`、无 `finance + X/3`）均在创建 `state_dir` 或域库前以 `VersionUnsupported` 拒绝。
  - **非历史装配完全恢复旧行为**：`x.profile` 不含 `history_simulation` 时，launcher 不预读 `economic.manifest`，不因坏非历史 X `profile_revision` 拉停整组 S/E/B，保持既有非关键 X 降级与启动条件不变。
- **历史模拟 X `/2`（及既有已退 `/1`）写入入口**：
  - `x_execution_session serve` 对含 `history_simulation` 的配置只接受 `x-execution-profile/3`。
  - 在获取 `<db>.writer.lock` 与调用 `open_durable_db`（读写打开）**之前**，先以 `SQLITE_OPEN_READ_ONLY`（不启用 `immutable=1`，故可见活 `-wal` 帧）预检既有库；凡已存在 `/1`、`/2` 历史模拟库即当场以 `VersionUnsupported` 退出，不落锁文件、不改写业务表、不推进 `writer_epoch`、**不静默 checkpoint `-wal`**。

### 3. 操作者可用的只读查询入口、跨域补录前提与撤掉 `/2` socket 的损失

撤掉 `/1`/`/2` X 的在线 Unix socket 服务（`x-exact-simulation/1`）后，操作者不再需要借助 E `ReleasedExact`、直接 SQL 或新起归档 reader E 才能查旧 X 状态；改由 `x_execution_session` 提供经过完整只读审计（`SQLITE_OPEN_READ_ONLY`，覆盖 `/1`、`/2`、`/3`）的离线 CLI 入口（原 `query --db FILE` 仅元数据入口保持原样）：

| 入口 | 可直接查询的对象（不依赖 E/S 在线，也不要求 E 预配归档源） | 覆盖状态与边界 |
|---|---|---|
| `x_execution_session query-history --db FILE` | 库 schema 版本、profile/模型摘要、已提交前沿 `last_bar_index`、全部命令摘要、已提交批列表（含 `batch_receipt_sha256`）与原件 ID 列表 | 覆盖 `/1`、`/2`、`/3` 全部合法库；损坏或篡改库在审计期拒绝 |
| `x_execution_session query-command --db FILE --command-id ID` | 完整 `ExactCommandState`：`state`、`x_accept` 三相时钟、`causal_refs`、`attempt_batch_id`、`pending_batch_id`、`pending_epoch`、`has_execute_evidence`、`execute_evidence`、`last_committed_batch_id`、`last_bar_index` | 逐项覆盖 `Accepted`、`ExecutionReady`、`ExecutionRequested`（含 pending batch/epoch）、`MayHaveCalled`、`Observed` |
| `x_execution_session query-batch --db FILE --batch-id ID` | 完整已提交 `SimulationBatch` JSON（含 `orders`、`fills`、`fees`、`scenario_busts`、`originals`、`batch_receipt_sha256`） | 仅返回已提交终态批（如 `b3` 含原 `fill`+`fee`）；未提交 pending 批（如 `ExecutionRequested` 挂起的 `b2`）以 `MissingDependency` 明确拒绝 |
| `x_execution_session query-original --db FILE --original-id ID` | 完整冻结原件 JSON（如原 `fill` 与原 `fee` 文档） | 与原 `/2` socket `QueryOriginal` 逐字节一致 |

**区分两类对象的职责与调用前提**：
1. **X 可直接只读查询的对象**：上述四条 `x_execution_session query-*` 命令直接按 X 库路径审计并返回旧 X 的全态命令、已提交批与冻结原件，无需原 E 会话预配 `history_simulation_source`。
2. **E 跨域核验与补录对象（`e_economic_session inspect-simulation-capture-batch` / `CaptureExternal`）**：仅当**原 E 会话在 `init` 时已预先冻结 `history_simulation_source`**（`manifest_hash` 钉死后不可事后补写）才可直接按原 E 归档通道核验/补录缺失原件；若原 E 会话未预配 `history_simulation_source`（例如 `#2081` 形态），不能靠另起“新归档 reader E”替代原 E 会话的 cut 与责任，只能先用上述 X 只读 CLI 取出原批与原件，再按既有人工/外部事实审计流程处理，且不减免原 E 责任。

**撤掉 `/2` socket 的实际损失（明示）**：
- 不再为 `/1`/`/2` X 库提供在线 Unix socket（`x-exact-simulation/1`）的 `QueryCommand` / `QueryOriginal` / `AcceptExact` / `AdvanceBar` 服务；在线客户端查询须改调 `x_execution_session query-*` 离线只读 CLI。
- 停留在未终结态（`Accepted`、`ExecutionReady`、`ExecutionRequested + pending`、`MayHaveCalled`）的旧 `/2` 命令无法经 `/3` X 推进至 `Observed`，其未决外效风险与原 E 责任原样保留，不得自动重放或免责。

### 4. 原档不静默 checkpoint 与封存条件（待裁合同）

- **首次拒绝与只读查询不改原档与活 WAL**：`x_execution_session serve` 的预检与全部 `query-*` 命令均使用 `SQLITE_OPEN_READ_ONLY`（不传 `immutable=1`，不使用自造 VFS），因此能够看到未 checkpoint 的活 `-wal` 帧，同时保证在首次被拒打开与重复只读查询后，原 `<db>` 与 `<db>-wal` 的字节内容（SHA-256）完全不变，也不会生成 `<db>.writer.lock`。
- **必须明示的 SQLite WAL 封存边界（不宣称为“目录零变化”）**：
  - 当归档库处于 WAL 模式且存在未 checkpoint 的 `<db>-wal` 但缺少 `<db>-shm` 时，SQLite 在不使用 `immutable=1` 的前提下以 `SQLITE_OPEN_READ_ONLY` 打开，**会在可写目录中建立 `<db>-shm` 共享内存索引文件**（不会修改 `<db>` 或 `<db>-wal` 字节，也不会 checkpoint）；若所在目录本身为只读权限（如 `chmod 0555` / 只读介质）且缺少 `-shm`，则 SQLite 只读打开会因无法建立 `-shm` 而拒绝（`SQLITE_READONLY`），这正是保持活 WAL 可见性、不使用 `immutable=1` 漏看活 WAL 的代价。
  - **待裁封存规程**：（1）在可写取证目录直接运行 `query-*` 或误触 `serve` 时，原 `.db` 与 `.db-wal` 字节 100% 保全可恢复，仅可能伴生瞬态 `.db-shm`；（2）若要求只读介质或目录级零 sidecar 不可变封存，操作者须在封存时成对拷贝 `.db` + `.db-wal` 到只读归档并**对副本执行 `query-*`**，或在旧二进制停机封存前先做一次显式 clean checkpoint 再转入只读介质。

### 5. 保持不变的能力

- **非历史模拟 X profile（`/1` 骨架、`dry-run`、`experiment`、`production`）及 launcher 既有启动/降级路径**：完全不变。
- **`tb03b-finance/5` 其余经济写操作**：`ImportResponsibility`、`PrepareDecision`、`Reserve`、`CommitDecision`、`AbortDecision`、`CloseApplicants`、`CaptureExternal`、`ResolveEvidence`、`ApplyAllocation`、`BindVoice` 继续可用，不把整个 FIN/5 库改只读。
- **真正隔离的 C1 离线 `TestOnly` 验算**：未向 `x_target.x_id` 授予 `QueryReleasedExact` 的配置保持原义（其产物无法被真实历史 X 兑现）。
- **全部查询、只读视图与旧收据**：`QueryCommand`、`QueryReleasedExact`、`QueryDecision`、`QueryGrant`、`QueryFact`、`QueryAllocation`、`ReadView`、`Watch`、`EconomicRead*` 与原已提交收据重取保持原义。

### 6. 既有会话逐态处置与可执行迁移步骤

| 既有 FIN/5 + /2 状态 | 本包行为与处置要求 | 可用只读入口与责任/外效边界 |
|---|---|---|
| 仅 `Committed`（未 `Dispatchable`） | 独立 E（含 X `QueryReleasedExact` 授权）拒绝新 `MakeDispatchable`（`VersionUnsupported`）；不进入 `Dispatchable` | E `QueryCommand`/`ReadView`；E 责任不变，零新收据 |
| 已有 `Dispatchable` | 原 ID 重试返回原 `DispatchableReceipt`；`QueryCommand` 仍为 `Dispatchable`；新 `ReleaseExact` 被拒（`VersionUnsupported`） | E `QueryCommand`/`ReadView`；保持 `Dispatchable`，E 责任不变，零新 `ReleasedExact` |
| 已有 `ReleasedExact` | 原 ID / 同内容重试返回原 `ReleasedExactReceipt`（篡改报 `IdentityConflict`）；`QueryCommand`、`QueryReleasedExact` 仍返原 14 字段命令；送 `/3` X（原样或伪造 `model_ref`）均被拒 | E `QueryCommand`/`QueryReleasedExact`；E 责任不变，零 X/S 调用与成交 |
| `/2` X 库 `Accepted`（已接纳、未起批） | `/3` X `serve` 预检以 `VersionUnsupported` 拒绝，原 `.db`/`.db-wal` 零字节改动、无锁文件 | `x_execution_session query-history` / `query-command` 查 `Accepted`、`x_accept`、`causal_refs`；原库封存备审，不减免原 E 责任 |
| `/2` X 库 `ExecutionReady` / `ExecutionRequested` + pending 批 / `MayHaveCalled` | `/3` X `serve` 预检以 `VersionUnsupported` 拒绝，不静默 checkpoint 活 WAL，不得自动重放成新外效 | `x_execution_session query-command` 查 `state`、`attempt_batch_id`、`pending_batch_id`、`pending_epoch`、`execute_evidence`；`query-batch` 对未提交 pending 批报 `MissingDependency`；保留未决外效与原 E 责任 |
| `/2` X 库已提交终态批（`Observed`，如 `b3` 含原 `fill`+`fee`） | `/3` X `serve` 拒绝续写；原批与原件零改写保留 | `x_execution_session query-command` / `query-batch` / `query-original` 逐字节读出 `Observed`、原批与 `fill`+`fee` 原件；若原 E 会话在 `init` 时已预冻结 `history_simulation_source`，可继续用 `e_economic_session inspect-simulation-capture-batch` 核验并按需 `CaptureExternal` 补录 |

**新历史模拟会话迁移步骤（显式 `FIN/6 + X/3`）：**

1. 固定本次拟执行的 typed `Model` JSON，计算规范内容摘要：`content_hash = sha256(canonical_json(model))`（64 位小写十六进制）。
2. 新建独立的会话目录与全新空 S/E/B/X 库及新的 `session_id` / `session_generation`（不得原地覆写或复用旧 FIN/5 E 库或 `/2` X 库）。
3. 准备新的冻结财务输入 `input.json`：`schema_revision` 设为 `"tb03b-finance/6"`，`exact_release.model_coverage.model_ref` 写入 `{"model_id": model.model_id, "revision": model.revision, "content_hash": content_hash}`。
4. 准备新的 `economic.manifest`：`finance.schema_revision` 设为 `"tb03b-finance/6"`，更新 `finance.input_path` 与 `finance.input_sha256`，保持 `clock.kind = "logical-bar/1"`。
5. 准备新的 `x-profile.json`：`profile_revision` 设为 `"x-execution-profile/3"`、`mode` 设为 `"simulation"`，其中 `history_simulation.model` 与第 1 步取摘要的 `Model` 逐字段一致。
6. 通过正式入口 `production_session --manifest <new-production.json>` 启动新会话。
7. **账务与责任边界**：若需从原市场/策略输入重放历史模拟，新 `FIN/6 + X/3` 运行严格属于**独立新会话**，不得将其视为延续旧 FIN/5 账本，也不得以重放结果清零或抵消旧 FIN/5 会话的既有责任。
