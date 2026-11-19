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

这个本地只读命令使用 E 库绑定的 manifest，不从请求接受 X 库路径（也不得修改原 manifest；若经原 E 读取已封存旧档，原 manifest 绑定的 `history_simulation_source.x_db` 绝对路径须实际指向独立可写工作副本，不直接打开封存原件；且原 E 仅接受符合其既有合同的十进制 `session_generation`，早期非十进制如 `g1` 旧档须经 `x_execution_session query-*` 读取）；在 X 的同一只读事务中按外层 `profile_revision`、内层 `exact_profile_revision` 与冻结键集严格判别核验：早期 `/1`（11 键无 `conditions` + 3 键 `e`/`s` + 3 项冻结条件 + 整数时钟，不伪造共同信封或新授权）、后期 `/1`（12 键含 `conditions` + 6 键 `e`/`s` + 整数时钟，按 12+6+6 布局共同可证条件语义核验且强制 `claimed_ns == bar.index`，不溯及重放后加的 `2ed00abd6c` 配对表或 `b66b61a0b0` 四项完备闸）、`/2`（含首次量、分配身份的 IC:13 命令、十进制文本时钟及完整配对表与四项完备闸，归档只读）、`/3`（在 `/2` 基础上强制核对 `model_ref` 与 X 实际装载模型内容摘要）。
外层版本与内层标记不符、键集混合/缺失、命令或 E/S 原收据不符、批重演或原件对不上，都拒绝；不宽松回退降格，不换版本重试。
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

> **审签状态：R6 候选条文（保留全部旧 `/1` 历史正式库只读可读承诺，不缩窄到 `#2078`；退场范围与操作生效条件可采用，但读回修复经独立评审签收前不批准运行切换，真正执行升级与停进程不在此次授权）。** 前次 C2 裁定（`#1407#issuecomment-6749476649`）仅退掉 `#1942` 数值编码的 `/1` 历史模拟写入入口，未授权自动退掉 `/2` 写入入口；本节条文须经独立非作者评审与主控显式签署后，再于下文拟定生效点切换生效。

### 1. 无法原地保全 `FIN/5 + X/2` 续写的证据依据

核查父头 `#2081`（`eabdfb02013135db78d21cb2d8a47dec0a71a555`）真实 `/2` 样本（`signed-c2-t3/a/manifest.json`、`input.json`）与 `tb03b-finance/5` 实现后，旧 `/5` 协议自身无法证明 E 授权过具体实装 `Model` 内容：

1. **原样本 `model_ref.content_hash` 仅为名/版摘要**：`signed-c2-t3/a/input.json` 的 `exact_release.model_coverage.model_ref.content_hash` 为 `e28cb65bf917085d648735d192848c2d1a9d460f0b61c3c57144055770f925cb`（即 `sha256("\"history-sim/bar-batch-known-frontier/1@oracle-1\"")`），只覆盖模型名与版本串，不覆盖费率、滑点、tick/量/金额量子、标的或撮合参数。
2. **FIN/5 wire 自身不绑定模型实装**：14 字段 `ExactCommand` 与 `command_hash` 均不含实装 `Model` 摘要；`signed-c2-t3/a/manifest.json` 亦无实装模型绑定字段。注：这证明的是 `/5` wire 自身不绑定实装模型，而非断言所有旧档外部均无任何历史证据。
3. **X 自持配置不等于 E 授权**：旧进程曾运行过或 X 本地持有 `x-profile.json`，都不能证明 E 授权过该实装模型（C3 反例 `06a767ab` 已证在 `FIN/5 + X/2` 下仅将 X 的 maker 费率分子 `1 → 10` 即可静默产生错费成交）。
4. **不伪造兼容、不放宽 `/3`**：不得给 `/3` 增加可选 `model_ref`、不得回填或重签旧 `/5` 命令、不得靠事后拆换旧二进制或仅改版本字符串假装兼容。

因此，本候选提出最小升级与退场合同：退掉可向目标真实历史 X 交付未绑定模型授权的旧写入入口，保留全部既有收据、其他 `/5` 经济写入、非历史用途、真正不可兑现的离线 C1 验算以及完整只读查询取证（涵盖全部历史正式 `/1` 世代、`/2` 与 `/3`）；新执行统一走显式 `tb03b-finance/6 + x-execution-profile/3` 新会话。

### 2. 拟定生效点、退场范围、现有能力分界与三处守门

- **拟定生效点（操作切换点，非 Git 合入）**：在主控显式签署本合同后，**成套新二进制（`production_session`、`e_economic_session`、`b_chong_session`、`x_execution_session`）实际启用，且全部旧历史写者进程（`/1`/`/2` X 及旧 `/5` E 历史交付写者）已停止或隔离的运行切换时刻**。Git 合入或构建产物生成本身不会停止已在运行的旧进程；切换亦不免除或改写旧 E 会话的既有责任。真正执行升级或停止运行中进程不在此次授权。
- **独立正式 E（`e_economic_session` / `finance.rs`）的现有能力分界**：
  - 守门守的是 **E 能否向冻结目标 `(x_target.x_id, x_target.x_epoch)` 对应的真实历史 X 实际交付新的可兑现授权**，而不是 `clock.kind` 名称、`history_simulation_source` 归档来源或 X 当时是否在线。
  - **判据（授权项内部核对，不跨项拼权限，不混淆可配置来源字段）**：当 E 为无模型绑定的 `tb03b-finance/5`（`!model_binding`），冻结 `exact_release` 面向历史模拟目标（`model_ref.model_id` 以 `history-sim/` 开头或 `conditions` 含 `simulation-local-transaction/1`），且 E 在 `init` 时钉死的 `manifest.authorized_sources` 中**存在同一条授权项**同时满足：
    1. `producer_id == exact_release.x_target.x_id`；
    2. `producer_epoch == exact_release.x_target.x_epoch`（即冻结目标 X 的 **writer epoch**；`source_namespace` 与 `source_epoch` 为可配置来源身份，不得误定为 writer epoch）；
    3. 该同一条授权项的 `operations` 包含 `"QueryReleasedExact"`。
    满足时：
    - **已提交收据优先重取**：`write_with_ingress` 先核审计并按原消息 ID（`previous_message`）与原收据键（`receipts`）查回已提交收据；命中则原样返回原收据（同键改内容仍报 `IdentityConflict`）。
    - **新交付当场拒绝**：未命中既有收据的新 `MakeDispatchable` 与新 `ReleaseExact` 直接以 `VersionUnsupported` 拒绝，不落行、不产生新收据，且不要求 X 在线。
  - **显式退场项与保留项（精确分界）**：
    - **必须退出正式交付的 `/5` 用法**：所有面向历史模拟目标且在同一条 `authorized_sources` 授权项内向冻结 `(x_target.x_id, x_target.x_epoch)` 授予 `QueryReleasedExact` 的配置——包括（a）`#2081` 形态（`logical-bar/1`、无归档源、`X/1` 获准）；（b）`b9d898` 祖先形态（`TestOnly` 时钟、无归档源、`X/1` 获准）；（c）即使 `source_namespace` / `source_epoch` 改为非 `"1"` 自定义值（如 `"99"`），只要同项 `producer_id`/`producer_epoch` 匹配冻结 `x_target` 且含 `QueryReleasedExact`，同样拒绝。
    - **保留的真正不可兑现离线 C1 / 错代验算**：未在单条授权项内向冻结 `(x_target.x_id, x_target.x_epoch)` 同时授予 `QueryReleasedExact` 的配置——包括（a）未授目标 X 的原始 C1 离线配置（`1f0a42bc20^`）；（b）冻结 `x_target=X/1` 但仅向错代 `X/2` 授 `QueryReleasedExact`（甚至另在独立项给 `X/1` 仅授 `ReadView`，不跨项拼权限）的 C2 正控配置。此类配置继续可离线签发 `Dispatchable` / `ReleasedExact`，但**不可能向真实历史 X 兑现**：真实 `X/1` 发起 `QueryReleasedExact` 必被 E `Config::authorized` 拒以 `来源未获准`（且 `manifest_hash` 已在 `init` 钉死不可后改）；真实 `X/2` 尝试接纳 `x_epoch=1` 命令必被 `ExactCommand::validate` 拒以 `IdentityConflict`；同时 `/3` X 亦拒绝缺 `model_ref` 的 `/5` 命令。
- **正式装配入口（`production_session`）**：
  - **仅当 `x.profile` 含非空 `history_simulation` 时**，`load_manifest` 才预读 `economic.manifest` 并校验 E/X 合同配对：要求 `profile_revision == "x-execution-profile/3"` 且 `economic.manifest.finance.schema_revision == "tb03b-finance/6"`；任何不匹配组合（`FIN/5 + X/3`、`FIN/5 + X/2`、`FIN/6 + X/2`、无 `finance + X/3`）均在创建 `state_dir` 或域库前以 `VersionUnsupported` 拒绝。
  - **非历史装配完全恢复旧行为**：`x.profile` 不含 `history_simulation` 时，launcher 不预读 `economic.manifest`，不因坏非历史 X `profile_revision` 拉停整组 S/E/B，保持既有非关键 X 降级与启动条件不变。
- **历史模拟 X `/2`（及既有已退 `/1`）写入入口**：
  - `x_execution_session serve` 对含 `history_simulation` 的配置只接受 `x-execution-profile/3`。
  - 在获取 `<db>.writer.lock` 与调用 `open_durable_db`（读写打开）**之前**，先以 `SQLITE_OPEN_READ_ONLY`（不启用 `immutable=1`，故可见活 `-wal` 帧）预检既有库；凡已存在 `/1`（早期与后期）、`/2` 历史模拟库即当场以 `VersionUnsupported` 退出，不落锁文件、不改写业务表、不推进 `writer_epoch`、**不静默 checkpoint `-wal`**。

### 3. 操作者可用的只读查询入口、本地审计边界与撤掉 `/2` socket 的损失

撤掉 `/1`/`/2` X 的在线 Unix socket 服务（`x-exact-simulation/1`）后，操作者由 `x_execution_session` 的离线只读 CLI 入口（基于 `SQLITE_OPEN_READ_ONLY`，覆盖早期 `/1`、后期 `/1` 全部历史准入世代、`/2`、`/3`，不改变既有 `SimulationBatch` 存储格式；原 `query --db FILE` 仅元数据入口保持原样）完成档案取证：

| 入口 | 按实际读口返回的字段（不依赖 E/S 在线，也不要求 E 预配归档源） | 覆盖状态与实际边界 |
|---|---|---|
| `x_execution_session query-history --db FILE` | `profile_revision`、`archive_layout`（`v1_early` / `v1_late` / `v2` / `v3`）、`execute_evidence_claimed_ns_audit_policy`、`condition_audit_policy`、`condition_audit_unproven`、`writer_epoch`、`session_id`/`session_generation`/`x_id`、`source_namespace`/`source_epoch`、`model_content_hash`、前沿 `last_committed_batch_id`/`last_bar_index`、`pending_batch_id`/`pending_epoch`、`committed_batches[*]`（每批含 `batch_id`、`bar_index`、`batch_receipt_sha256`、`state_content_hash`、`original_count`）、`commands[*]` 摘要与 `originals` ID 列表 | 覆盖早期 `/1`、后期 `/1`（含 `1f0a42bc20` 旧能力配对与 `2ed00abd6c` 缺四项完备库）、`/2`、`/3` 通过对应布局本地一致性审计的库；`batch_receipt_sha256` 由此处的 `committed_batches[*]` 给出 |
| `x_execution_session query-command --db FILE --command-id ID` | `ExactCommandState`：`state`、`x_accept` 三相时钟、`causal_refs`、`attempt_batch_id`、`attempt_batch_bar_index`、`pending_batch_id`、`pending_epoch`、`has_execute_evidence`、`execute_evidence`、`execute_evidence_claimed_ns_audit`、`condition_audit_policy`、`condition_audit_unproven`、`archive_layout`、`last_committed_batch_id`、`last_bar_index` | 逐态覆盖 `Accepted`、`ExecutionReady`、`ExecutionRequested`（含 pending batch/epoch）、`MayHaveCalled`、`Observed` 与 `NoRecord`；原样保留 `/1` JSON 整数与 `/2`/`/3` 十进制文本 |
| `x_execution_session query-batch --db FILE --batch-id ID` | 原样已提交 `SimulationBatch` JSON：`kind`、`request_id`、`bar_index`、`model_content_hash`、`state_content_hash`、`intra_batch_order`、`capacity_transitions`、`capacity_evidence`、`l0_fill_count`、`unfilled_market`、`originals`（不变更原批格式，不含 `orders`/`fills`/`fees`/`scenario_busts`/`batch_receipt_sha256` 顶层键） | 仅返回已提交终态批（如 `b3` 含原 `fill`+`fee` 原件）；未提交 pending 批（如 `ExecutionRequested` 挂起的 `b2`）以 `MissingDependency` 明确拒绝 |
| `x_execution_session query-original --db FILE --original-id ID` | 完整冻结原件 JSON（如原 `fill` 与原 `fee` 文档） | 与原 socket `QueryOriginal` 逐字节一致，原样保留原字段与原整数 |

**本地一致性审计范围、存储布局与条件准入世代分离原则及责任边界（必须明示）**：
1. **读档不是给旧命令重发执行许可；严格区分存储布局与条件准入世代，绝不靠失败降格，绝不削弱晚 `/1` 与 `/2`/`/3`**：
   - 任何 `authority_profile` 解码前先核对外层 `x_meta.profile_revision` 与内层 `x_sim_meta.exact_profile_revision` 一致性（`/1` 必须缺省，`/2` 必须为 `x-execution-profile/2`，`/3` 必须为 `x-execution-profile/3`），不符即以 `VersionUnsupported` 拒绝。
   - **有可信落盘记录能识别准入世代时才核其特有约束**：`/2` 与 `/3` 具外层/内层版号（均晚于 `8d23381b0c`），恒直接解码完整 12 键/6 键 `Profile` 并强制现行 `check_condition_semantics` 配对表与 `check_required_capabilities` 四项完备闸（`condition_audit_policy: "verified_current_condition_semantics_and_completeness"`、`condition_audit_unproven: []`），绝不回退或降格到早期 `/1` 或晚 `/1` 共同语义路径。
   - `/1` 在反序列化之前按冻结键集同时判别顶层及 `e`/`s` 端点：
     - **早期 `/1`（`archive_layout: "v1_early"`，历史正式写者 `18446a3d35`–`d1c46577b1`）**：顶层精确 11 键（无 `conditions`）且 `e`/`s` 各精确 3 键（仅 `socket`、`authority_id`、`authority_epoch`）；不补写、不伪造共同信封或新授权，按当年冻结的 3 项条件清单（`released-exact/1`、`execute-committed/1`、`simulation-local-transaction/1`）、整数时钟、批重演与原 E/S 收据闭包核档；显式输出 `condition_audit_policy: "v1_early_frozen_three_conditions"` 与 `condition_audit_unproven: ["model_coverage_condition_1f0a42bc20", "condition_semantics_pairing_table_2ed00abd6c", "required_four_capabilities_completeness_b66b61a0b0"]`。
     - **后期 `/1`（`archive_layout: "v1_late"`，历史正式写者 `1f0a42bc20`–`734847be00`，含 `#2078` 归档布局）**：顶层精确 12 键（含 `conditions`）且 `e`/`s` 各精确 6 键（含 `schema_revision`、`reply_namespace`、`producer_id`）。该布局跨越三个条件准入世代——`1f0a42bc20`（允许旧能力配对如 `released-exact-probe/1`）、`2ed00abd6c`（引入配对表但尚不要求四项必备能力齐全）、`b66b61a0b0`–`734847be00`（加入四项完备闸）——且三代在 SQLite 中不落写者修订号、共享完全相同的 12+6+6 落盘布局。因此读回按该布局**共同可证语义**核验（`validate_conditions_common_12_6`：每项九字段非空、`condition_id` 唯一、`X.*` 阶段能力必属 `X_CAPABILITIES`、必含 `E.ReleaseExact` 阶段 `model_coverage`、命令 `conditions == profile.conditions`），**不溯及重放 `2ed00abd6c` 配对表与 `b66b61a0b0` 四项完备闸**，同时在读出元数据中显式标明 `condition_audit_policy: "v1_late_common_12_6_invariants_only"` 与 `condition_audit_unproven: ["condition_semantics_pairing_table_2ed00abd6c", "required_four_capabilities_completeness_b66b61a0b0"]`；且**完整保留**晚 `/1` 的逻辑 bar 核证（`claimed_ns == attempt_batch.bar.index`）、内外层版号、严格 12+6+6 键集、端点非空与 E/S 回执原件闭包。
     - **反降格拒绝**：任何缺失键（如后期 `/1` 缺 `e.schema_revision`）、多余未知键、混合键集（12 键配 3 键 `e`/`s` 或 11 键配 6 键 `e`/`s`）、非对称 `e`/`s` 键集、空必填字段，或违反晚 `/1` 共同不变量（如 `X.*` 未支持能力、缺 `E.ReleaseExact` `model_coverage`、重复 `condition_id`、命令与档案条件清单不等）均直接拒绝，绝不做“按现行准入闸或 `Profile` 解码失败后降格”的宽松兜底。
2. **审计范围与不可过度承诺**：上述只读查询先在只读事务内执行对应布局的本地一致性审计（外层/内层版本匹配、`pending_epoch == writer_epoch`、冻结 `contract`/`authority_profile` 规范字节校验、从空历史确定性重演所有已提交批及 `originals`/`busts`、命令与 E/S 回执引用闭包及各代可证时钟/条件语义）。该审计**只能检测违反该布局共同可证不变量的损坏或不一致，不能承诺发现一切离线篡改，也不能证明无写者修订落盘的旧 `/1` 档案曾满足后来才引入的准入闸**（未核证的准入闸已在 `condition_audit_unproven` 中显式列出）。
3. **`execute_evidence.claimed_ns` 按各代写者真实可证明不变量区分**：
   - **后期 `/1`（`v1_late`）、`/2`（`v2`）与 `/3`（`v3`）**：全部后期 `/1`（自 `1f0a42bc20`，晚于 `d1c46577b1` 删除 `now_ns()`）、`/2`（自 `8d23381b0c` 至 `#2081`）与 `/3` 写者在持久化 `execute_evidence.claimed_ns` 时恒写入 `batch.bar.index`（后期 `/1` 为整数，`/2`/`/3` 为规范十进制字符串）。因此本地审计强制核验 `claimed_ns == attempt_batch.bar.index` 且 `>= reply.commit_ns`（不符则以 `IdentityConflict` 拒绝），并在输出中标为 `verified_equal_to_attempt_bar`。
   - **早期 `/1`（`v1_early`）**：早期 `/1` 写者中 `18446a3d35`/`5f3361ca8b` 写墙钟 `now_ns()`、`d1c46577b1` 写 `batch.bar.index`，且共享完全相同的 11 键/3 键布局。审计无法溯及强制早期 `/1` 满足 `claimed_ns == attempt_batch.bar.index`，仅核验当年可证明的 `claimed_ns >= reply.commit_ns`，并在 `query-history.execute_evidence_claimed_ns_audit_policy` 与 `query-command.execute_evidence_claimed_ns_audit` 中明确标为 `"raw_claim_only_non_retroactive_v1"`——**绝不把早期墙钟说成已验证等于 `bar.index`**。
   - **不构成授权或免责**：无论 `verified_equal_to_attempt_bar` 还是 `raw_claim_only_non_retroactive_v1`，亦无论 `condition_audit_policy` 为何值，X 本地查询输出均**不得作为重发执行许可、自动重放授权、自动补录授权或原 E 责任免责依据**。测试中基于真实 `/2` 库构造的 `MayHaveCalled` 派生工作副本仅用于验证本地审计分支，不得描述为真实进程崩溃现场。
4. **历史 X 离线取证与原 E 固定路径读回的区别（`x_execution_session query-*` vs `e_economic_session inspect-simulation-capture-batch`）**（`service.rs:1555`、`intake.rs:157`）：
   - **历史 X 只读入口（`x_execution_session query-*`）**：对恢复到任意独立可写取证目录的旧 `/1`（含早期非十进制 `session_generation` 如 `"g1"` 以及全部晚期 `/1` 准入世代）、`/2`、`/3` 工作副本直接只读核档，不依赖原 E `manifest` 或在线服务，输出前沿、命令语义、原批、`fill`/`fee` 原件及 `condition_audit_policy`/`condition_audit_unproven`。
   - **原 E 固定批读回入口（`e_economic_session inspect-simulation-capture-batch` / `CaptureExternal`）**：
     - 须针对**原 E 会话自身的未改动 `manifest` 与 `E_DB`** 执行（不得另起“新归档 reader E”冒充原 E 的 cut 与责任，也不得改写 `session_generation` 或重算原档哈希冒充原 E 路径）；
     - 原 E `manifest` 须在 `init` 时已预冻结 `history_simulation_source`（含 `x_db` 绝对路径、`source_namespace`、`source_epoch`、`producer_id`、`producer_epoch`、`model_content_hash`，`manifest_hash` 钉死后不可事后补写或修改），且遵循 E 既有的十进制 `session_generation` 合同（早期非十进制 `g1` 旧档不经 E `init`/固定路径读回，由 `x_execution_session query-*` 取证）；
     - **固定路径要求**：`inspect-simulation-capture-batch` 不从命令行接受 X 库路径，且严禁修改原 `manifest`；因此经原 E 读取已封存旧档时，原 `manifest` 绑定的 `history_simulation_source.x_db` 绝对路径本身必须实际指向独立可写工作副本（将封存副本成套恢复到该原绑定路径，封存原件保持不打开、零改动）；
     - `history_simulation_source` 对应来源须在原 E `authorized_sources` 中获准 `CaptureExternal`；调用方须显式提供已提交批的 `--batch-id`、完整规范回执摘要 `--batch-receipt-sha256`（取自原 `QueryBatch` 回执或 `x_execution_session query-history.committed_batches[*].batch_receipt_sha256`）、`--x-id` 与 `--x-epoch`；
     - 若原 E 会话未预配 `history_simulation_source`（例如 `#2081` 形态），只能先用 `x_execution_session query-*` 取出原批与原件，再按既有人工/外部事实审计流程处理，且不减免原 E 责任。

**撤掉 `/2` socket 的实际损失（明示）**：
- 不再为 `/1`/`/2` X 库提供在线 Unix socket（`x-exact-simulation/1`）的 `QueryCommand`、`QueryBatch`、`QueryOriginal`、`AcceptExact`、`AdvanceBar` 服务；在线客户端查询须改调 `x_execution_session query-*` 离线只读 CLI。
- 停留在未终结态（`Accepted`、`ExecutionReady`、`ExecutionRequested + pending`、`MayHaveCalled`）的旧 `/1`/`/2` 命令无法经 `/3` X 推进至 `Observed`，其未决外效风险与原 E 责任原样保留，不得自动重放或免责。

### 4. 单一可操作封存与取证规程（不引入 `#1375` VFS）

为保证既有 `/1`（早期/后期）、`/2` 档案（尤其是存在未 checkpoint 活 `-wal` 的现场）在封存后既不丢失仅在 WAL 中的状态，又不改写封存原件，统一采用以下**唯一操作路径**（同步见 [`docs/runbook_production_session.md`](../../../docs/runbook_production_session.md)）：

1. **获取单一一致切面**：先停止/隔离旧历史写者及全部其他可能写入或触发 checkpoint 的连接（确认无活写进程与外部 SQLite 工具连接），或使用可保证单一一致切面的存储/文件系统快照取得整套档案。
2. **成套封存原件（绝不直接打开）**：将同一一致切面的 `<x>.db` 及所有存在的 `<x>.db-wal`（连同对应原 E 会话的 `manifest`、`E_DB`、收据等原 E 责任证据）成套封存至只读归档介质/目录，并登记文件清单与 SHA-256。**严禁直接对封存原件运行 SQLite、`x_execution_session serve`、`query-*` 或 `e_economic_session inspect-simulation-capture-batch`。**
3. **恢复到独立可写取证目录再查询**：需要核查前沿、pending 批、命令状态或原批/原件时，从封存归档完整复制一套副本（`.db` + 存在的 `-wal`）到**独立的可写取证工作目录**，再对工作副本运行 `x_execution_session query-history` / `query-command` / `query-batch` / `query-original`；若需用原 E 的 `e_economic_session inspect-simulation-capture-batch` 读取固定批，须在不修改原 `manifest` 的前提下，令原 `manifest` 绑定的 `history_simulation_source.x_db` 绝对路径实际指向该独立可写工作副本（不直接打开封存原件）。工作副本查询期间可正常产生 `-wal`/`-shm`（`query-*` 本身不触发写回或静默 checkpoint，可见仅在 WAL 中的状态），封存原件始终保持零改动。

**明确不作为通用方案的做法**：
- **仅做 `wal_checkpoint(TRUNCATE)`**：checkpoint 后主库头字节 `[18:20]` 仍为 WAL 模式 `[2, 2]`，放到只读目录/介质上以 `SQLITE_OPEN_READ_ONLY` 打开仍会因 `attempt to write a readonly database` 失败。
- **分时拷贝活库文件**：写者未停且非一致快照时先后拷贝 `.db` 与 `-wal`，可能取得跨切面不一致文件。
- **直接在只读介质/目录上查询裸 `.db` + `-wal`**：缺 `-shm` 且目录不可写时，不启用 `immutable=1` 的 `SQLITE_OPEN_READ_ONLY` 会报 `unable to open database file`。
- **使用 `immutable=1`**：会静默忽略未 checkpoint 的 `-wal`，导致把 `ExecutionRequested + pending` 误读成旧主库的 `Accepted`。
- **引入 `#1375` 自定义只读 VFS**：本合同明确不引入该 VFS。

### 5. 保持不变的能力

- **非历史模拟 X profile（`/1` 骨架、`dry-run`、`experiment`、`production`）及 launcher 既有启动/降级路径**：完全不变。
- **`tb03b-finance/5` 其余经济写操作**：`ImportResponsibility`、`PrepareDecision`、`Reserve`、`CommitDecision`、`AbortDecision`、`CloseApplicants`、`CaptureExternal`、`ResolveEvidence`、`ApplyAllocation`、`BindVoice` 继续可用，不把整个 FIN/5 库改只读。
- **真正不可兑现的离线 C1 / 错代验算**：未在同一条 `authorized_sources` 授权项内向冻结 `(x_target.x_id, x_target.x_epoch)` 授予 `QueryReleasedExact` 的配置保持原义（其产物无法被目标真实历史 X 兑现）。
- **全部查询、只读视图与旧收据**：`QueryCommand`、`QueryReleasedExact`、`QueryDecision`、`QueryGrant`、`QueryFact`、`QueryAllocation`、`ReadView`、`Watch`、`EconomicRead*` 与原已提交收据重取保持原义。

### 6. 既有会话逐态处置与可执行迁移步骤

| 既有 FIN/5 + /2 状态 | 本包行为与处置要求 | 可用只读入口与责任/外效边界 |
|---|---|---|
| 仅 `Committed`（未 `Dispatchable`） | 独立 E（单条授权项已向冻结 `x_target.x_id` + `x_target.x_epoch` 授 `QueryReleasedExact`）拒绝新 `MakeDispatchable`（`VersionUnsupported`）；不进入 `Dispatchable` | E `QueryCommand`/`ReadView`；E 责任不变，零新收据 |
| 已有 `Dispatchable` | 原 ID 重试返回原 `DispatchableReceipt`；`QueryCommand` 仍为 `Dispatchable`；新 `ReleaseExact` 被拒（`VersionUnsupported`） | E `QueryCommand`/`ReadView`；保持 `Dispatchable`，E 责任不变，零新 `ReleasedExact` |
| 已有 `ReleasedExact` | 原 ID / 同内容重试返回原 `ReleasedExactReceipt`（篡改报 `IdentityConflict`）；`QueryCommand`、`QueryReleasedExact` 仍返原 14 字段命令；送 `/3` X（原样或伪造 `model_ref`）均被拒 | E `QueryCommand`/`QueryReleasedExact`；E 责任不变，零 X/S 调用与成交 |
| `/2` X 库 `Accepted`（已接纳、未起批） | `/3` X `serve` 预检以 `VersionUnsupported` 拒绝，原 `.db`/`.db-wal` 零字节改动、无锁文件 | 按第 4 节封存并恢复到独立可写取证目录后，用 `x_execution_session query-history` / `query-command` 查 `Accepted`、`x_accept`、`causal_refs`；保留原 E 责任证据，不减免原 E 责任 |
| `/2` X 库 `ExecutionReady` / `ExecutionRequested` + pending 批 / `MayHaveCalled` | `/3` X `serve` 预检以 `VersionUnsupported` 拒绝，不静默 checkpoint 活 WAL，不得自动重放成新外效 | 按第 4 节封存并恢复到独立可写取证目录后，用 `x_execution_session query-command` 查 `state`、`attempt_batch_id`、`attempt_batch_bar_index`、`pending_batch_id`、`pending_epoch`、`execute_evidence`、`execute_evidence_claimed_ns_audit`（`/2` 强制核验 `claimed_ns == attempt_batch.bar.index`）；`query-batch` 对未提交 pending 批报 `MissingDependency`；保留未决外效与原 E 责任 |
| `/2` X 库已提交终态批（`Observed`，如 `b3` 含原 `fill`+`fee`） | `/3` X `serve` 拒绝续写；原批与原件零改写保留 | 恢复至可写取证目录后，用 `x_execution_session query-history` / `query-command` / `query-batch` / `query-original` 逐字节读出 `Observed`、原批（含 `originals`）、`committed_batches[*].batch_receipt_sha256` 与 `fill`+`fee` 原件；若原 E 会话满足第 3 节全部前提（已冻结 `history_simulation_source` 且 `CaptureExternal` 获准），可继续用原 E 的 `e_economic_session inspect-simulation-capture-batch` 核验并按需 `CaptureExternal` 补录 |

**新历史模拟会话迁移步骤（显式 `FIN/6 + X/3`）：**

1. 固定本次拟执行的 typed `Model` JSON，计算规范内容摘要：`content_hash = sha256(canonical_json(model))`（64 位小写十六进制）。
2. 新建独立的会话目录与全新空 S/E/B/X 库及新的 `session_id` / `session_generation`（不得原地覆写或复用旧 FIN/5 E 库或 `/2` X 库）。
3. 准备新的冻结财务输入 `input.json`：`schema_revision` 设为 `"tb03b-finance/6"`，`exact_release.model_coverage.model_ref` 写入 `{"model_id": model.model_id, "revision": model.revision, "content_hash": content_hash}`。
4. 准备新的 `economic.manifest`：`finance.schema_revision` 设为 `"tb03b-finance/6"`，更新 `finance.input_path` 与 `finance.input_sha256`，保持 `clock.kind = "logical-bar/1"`。
5. 准备新的 `x-profile.json`：`profile_revision` 设为 `"x-execution-profile/3"`、`mode` 设为 `"simulation"`，其中 `history_simulation.model` 与第 1 步取摘要的 `Model` 逐字段一致。
6. 经主控签署并完成旧历史写者停机/隔离切换后，通过正式入口 `production_session --manifest <new-production.json>` 启动新会话。
7. **账务与责任边界**：若需从原市场/策略输入重放历史模拟，新 `FIN/6 + X/3` 运行严格属于**独立新会话**，不得将其视为延续旧 FIN/5 账本，也不得以重放结果清零或抵消旧 FIN/5 会话的既有责任。
