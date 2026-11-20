> 正本：本文件是双跑确定性、恢复语义、seek 不偷未来、AsKnown 分证协议的教义正本。
> 最后裁定：#1537（2026-10-19）；修订：#1539（2026-11-02）、#2127（2026-11-20），见文末各节
> 受影响代码清单：见「受影响票与 blocking 边变化」节及 #2127 修订末尾

## 问题

本票 #1537（FU-15）要求裁决「双跑确定性、恢复、seek 不偷未来、AsKnown 分证」的完整协议。票面列出两项验收：固定输入下双跑全状态等价；恢复/seek/AsKnown 反例通过。当前只有比较维度已列，但独立进程杀停/重启、seek 语义、AsKnown 分证的机制缺。

## 权威依据

1. **图内技术合同权威性**：`.sandcastle/docs/graph-engineering.md:23`【裁决面分级】定义「T 类（技术取舍）：数据结构、接口与 seam、owner 落点、状态机与事件 schema、测试锁、迁移步骤、恢复语义。有权威源或本仓判例可援引。→ 自动裁决」，明确将恢复语义列为 T 类判据。

2. **确定性回放的既有模型**：ADR 0033:12【裁定一】定义「第 t 根 bar 适用集合 S_{t−1}（t−1 收盘时已输出并经准入），bar t 的外效构成批 B_t，批内各重独立判定，`intra_batch_order: Unknown`」，v1 确定性标注 `seed: none`。

3. **owner 与写权分离**：ADR 0027:23【裁定一标题】定义「两个域各有一个 owner，所有权互不重叠」，ADR 0027:25-28【裁定一表格】将结构判定域与重操作程序的所有权明确分列。

4. **分档事实不回填**：`CONTEXT.md:435`【阶段事件史/扩量资格】定义「`TStage` latch 只投影 campaign 内达标事实史（AsKnown 不回填）；扩量资格由唯一谓词按当前真实成本 K 与已退本金计算，latch 不得作其输入」。

5. **恢复路径不偷未来**：ADR 0033:14【裁定一】援引 ADR 0018 裁定四「撤单不得用预算到期 bar」（锚 `049-第49课.md:62`【正文】「其后，中枢已经完成就无所谓中枢震荡了」），在多重上的形式即前沿规则。

6. **历史模拟与真实环境同核**：ADR 0027:44【裁定三标题】与 ADR 0027:46-47【裁定三正文】定义「历史回放、paper 与 live 必须共用同一个结构判定域实现和同一个重操作程序实现；环境差异只允许落在行情、撮合和场所 adapter」。

7. **场所 profile 版本化证据射程**：ADR 0028:13【裁定一表格】定义 profile 字段含 `environment`、`execution_form`、`evidence_class`、`credential_scope`，「任一字段变更即新版本；`environment` 与 `execution_form` 不得在版本内切换」。

## 候选

### 候选 A：固定输入下全状态确定性 + 幂等恢复 + AsKnown latch

1. **双跑确定性协议**：固定（input bar 序列，policy 版本，model id/revision，seed，launcher scheduler）五元组，同步在所有检查点比较六项全状态（S 结构快照与变化，各重 B 账与 TStage latch，E 责任与准入历史，订单/成交原件，物理持仓，外效历史）；批内顺序未知不作比较面。
2. **恢复与 seek 语义**：seek(t) 取 S/B/E 最后不晚于 t 的快照，从该快照重放至 t，`as_of` 输出只含 ≤t 的事实；seek 不拉未来数据，不改写 ≤t 的已持久事实，不提前触发 >t 的阶段转换。杀停后恢复按最后持久 checkpoint 重放。
3. **AsKnown 分证机制**：TStage latch（降成本闸、退本金闸、增股闸）只投影 campaign 内达标事实，存储值为「首次达标的 bar 索引+证据指纹」，后续 bar 不回填；回放/恢复时 latch 值按原 campaign 还原，不用当前成本重算；profile 证据类（simulation/experiment/production）进 schema，分证不交叉引用。

### 候选 B：弱确定性 + 可选快照策略

1. 双跑只比较端态（最后一 bar 的六项全状态），中间快照可选取；批内顺序明确排序（by priority/资金剩余/操作级别），以换取单线程确定性。
2. 恢复时允许用当前政策重算 TStage latch，以兼容政策热更新；seek 可看到未来数据做「追溯修订」。
3. AsKnown 只作标签，不作门；回放可用更新的阈值重判历史。

## 裁定

采纳候选 A。双跑确定性、恢复语义、seek 不偷未来、AsKnown 分证是图内技术合同（graph-engineering.md 明文列举「恢复语义」与「状态机」为 T 类），本票有权援引 #799/#804 判据、决策地图 FU-11/14 前置定义及 ADR 0027/0033/0028 已裁的 owner、模型与 profile 条款裁定技术协议。

正本落点：docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md

### 一、双跑确定性协议

固定五元组（input, policy_version, model_id/revision, seed, scheduler）下，两次独立运行在每个 checkpoint 的全状态必须逐位等价。全状态六面：

1. S 结构快照（Classification 全部级别的结构对象、修订链、撤回记录）；
2. 各重 B 账（Voice、TStage latch 值与转换历史、筹码、毛账、cost_remaining）；
3. E 责任（共同占用、在途订单、最大责任保留）；
4. 订单/成交原件（epoch、身份、前后状态、cause 链）；
5. 物理持仓（场所回报与内部投影对账）；
6. 外效历史（已发送命令、回报、更正、bust 的完整 journal）。

批内顺序声明为 `Unknown`（ADR 0033 裁定一），不作比较维度；checkpoint 取每 bar 收盘后、下一 bar 开盘前，不取 bar 内中间态。v1 `seed: none` 确定性；引入随机化时另开版本。

### 二、恢复与 seek 语义

**恢复**：launcher 启动时检测上次 checkpoint，从该点加载六面快照并重放至当前 bar；杀停等同未完成 bar 的全部外效未发生，S/B/E 回退到上一 checkpoint。

**seek(t) 语义**：
1. 取 S/B/E 最后不晚于 t 的快照；
2. 从该快照向前重放至 t 的收盘；
3. `as_of=t` 输出只含索引 ≤t 的事实，不拉 >t 的未来数据；
4. TStage latch 值按原 campaign 的达标历史还原，不用 seek 时的当前成本重算；
5. 不改写 ≤t 的已持久事实，不提前触发 >t 的阶段转换。

**不偷未来**：seek/恢复路径不得利用当下已知而 t 时刻未知的信息（阶段达标、policy 版本更新、后续成交）改写 ≤t 的决策或状态；这是 ADR 0033 裁定一「前沿规则」在时间轴上的不变式。

### 三、AsKnown 分证机制

1. **TStage latch 只投影 campaign 内达标事实**（CONTEXT.md:435）：latch 存储「首次达标 bar 索引 + 证据指纹（成本/频率/速率下界的原始数值）」，后续 bar 不回填，恢复/seek 时按原 campaign 还原该值；
2. **profile 证据类进 schema**：`evidence_class ∈ {simulation, experiment, production}` 作为 profile 版本字段（ADR 0028 裁定一），实验证据不得读为生产有效，simulation 产出不进 TStage 触闸计数；
3. **分证不交叉引用**：回放验证用的 `simulation` profile 不共享 `experiment`/`production` 的 latch 状态，各自独立累计；同一历史窗口在不同 profile 下可有不同 TStage；
4. **政策版本不回退覆盖**：历史 bar 的 latch 值与当时适用的 policy 版本绑定，后续政策更新不追溯修改历史 latch，新 campaign 从新版本起算。

### 四、验收 oracle 与反例机制

1. **H1 确定性对拍**：同一输入五元组在两个独立进程跑至同一 t，diff 六面快照，逐字段 assert 等值；
2. **H2 杀停恢复**：t=1000 时 SIGKILL，重启从最后 checkpoint（如 t=950）恢复并续至 t=1050，六面快照与未杀停的连续运行在 t=1050 相同；
3. **H3 seek 不偷未来**：seek(800) 后 `as_of=800` 输出不含 bar>800 的任何事实；TStage latch 值等于原运行在 t=800 的值，不等于 seek 时的当前成本重算值；
4. **H4 AsKnown 分证**：同一历史窗口分别以 `simulation` 与 `experiment` profile 跑，latch 触发 bar 可不同，各自独立，`simulation` 闸门通过不自动使 `experiment` 通过；
5. **反例通过判据**：任一 H1–H4 的 diff 非空 ⟹ FAIL 并留档，说明违反确定性/恢复/seek/分证之一；四项全空 ⟹ PASS。

## 验收清单

- [ ] `cargo test dual_run_determinism_h1` 通过（同输入双跑六面逐位相同）
- [ ] `cargo test recovery_after_kill_h2` 通过（杀停恢复后续接与连续运行等价）
- [ ] `cargo test seek_no_future_leak_h3` 通过（seek(t) 输出不含 >t 事实，latch 值按原 campaign）
- [ ] `cargo test asknown_evidence_segregation_h4` 通过（simulation/experiment 分证独立）
- [ ] 文件存在 `docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md`
- [ ] TB-07 实施票（#1381/1399/1411/1418）引用本 ADR 的确定性协议
- [ ] TB-11 整图验收包含 H1–H4 四项 oracle 的实际运行证据

## 受影响票与 blocking 边变化

**受影响票**：
- #1534（FU-11，事件 schema 须含 epoch、policy/model hash、前后状态以支持恢复）
- #1536（FU-14，完整历史 profile 须含 model_id/revision、seed、scheduler）
- #1381/1399/1411/1418（TB-07，历史双跑实现须实装 H1–H4 四项 oracle）
- #1387（TB-11，整图验收须核 H1–H4 证据）
- #1340（SPEC，C10.3/AT-14/AT-17 恢复与双跑验收引用本 ADR）

**blocking 边变化**：
- 新增：本票 #1537 blocks #1381（TB-07-A 双跑实现依赖确定性协议）
- 新增：本票 #1537 blocks #1387（TB-11 整图验收依赖 H1–H4 oracle 定义）
- 保持：#1534（FU-11）blocks #1537（依赖既存）
- 保持：#1536（FU-14）blocks #1537（依赖既存）

## 授权引用

本条依 #1323 Notes N-1 预授权判定。用户 2026-10-18 原话：「其实很多技术的东西 完全不需要我来做 我完全信任你的判断」。双跑确定性、恢复语义、seek 不偷未来、AsKnown 分证均属图内技术合同（`.sandcastle/docs/graph-engineering.md:23` 明文列举「恢复语义」与「状态机」为 T 类），本裁决援引 #799/#804 收敛通则、决策地图 FU-11/14 前置定义、ADR 0027（owner）/0033（bar 批模型）/0028（profile 分证）已裁条款，在技术取舍权限内裁定。

## 引用自证

| 引用 | 核实命令 | 结果摘要 |
|---|---|---|
| `.sandcastle/docs/graph-engineering.md:23` | `sed -n '23p' .sandcastle/docs/graph-engineering.md` | 第 23 行：「- **T 类（技术取舍）**：数据结构、接口与 seam、owner 落点、状态机与事件 schema、测试锁、迁移步骤、恢复语义。有权威源或本仓判例可援引。→ 自动裁决。」 |
| ADR 0033:12【裁定一】 | `sed -n '12p' docs/adr/0033-history-simulation-bar-batch-model.md` | 第 12 行：「模型 id `history-sim/bar-batch-known-frontier/1`。第 t 根 bar 适用集合 `S_{t−1}`（t−1 收盘时已输出并经 RD-11 准入）；bar t 的外效构成批 `B_t`；批内各重订单各自独立对 OHLC 判定（严格穿越、开盘取优），互不排序、互不占用对方资金，`intra_batch_order: Unknown`」 |
| ADR 0027:23【裁定一标题】 | `sed -n '23p' docs/adr/0027-classification-chong-operating-program-ownership.md` | 第 23 行：「### 一、两个域各有一个 owner，所有权互不重叠」 |
| ADR 0027:25-28【裁定一表格】 | `sed -n '25,28p' docs/adr/0027-classification-chong-operating-program-ownership.md` | 第 25-28 行：表格分两行，结构判定域拥有 Classification，重操作程序拥有 TStage/Voice/筹码/毛账/交易意图 |
| `CONTEXT.md:435` | `sed -n '435p' CONTEXT.md` | 第 435 行：「**阶段事件史 / 扩量资格**（同上，裁定三）:`TStage` latch 只投影 campaign 内达标事件史（AsKnown 不回填）」 |
| ADR 0033:14【裁定一】| `sed -n '14p' docs/adr/0033-history-simulation-bar-batch-model.md` | 第 14 行含教义依据援引链，指向 ADR 0018 裁定四「撤单不得用预算到期 bar」与 `049-第49课.md:62` |
| ADR 0027:44【裁定三标题】 | `sed -n '44p' docs/adr/0027-classification-chong-operating-program-ownership.md` | 第 44 行：「### 三、历史、paper 与 live 共用两个核心 owner」 |
| ADR 0027:46-47【裁定三正文】 | `sed -n '46,47p' docs/adr/0027-classification-chong-operating-program-ownership.md` | 第 46-47 行：「历史回放、paper 与 live 必须共用同一个结构判定域实现和同一个重操作程序实现。不得为任一运行环境保留特有的结构判定、重状态推进或交易决策程序。」 |
| ADR 0028:13【裁定一表格】| `rg -n "evidence_class" docs/adr/0028-first-capability-verification-profile.md` | 第 13 行起 profile schema 表含 `environment`、`execution_form`、`evidence_class`、`credential_scope` 四字段 |
| `049-第49课.md:62` | `sed -n '62p' docs/chanlun/text/blog/049-第49课.md` | 第 62 行：「其后，中枢已经完成就无所谓中枢震荡了」 |

## 修订（#1539，恢复语义按证据类分述，2026-11-02）

（append-only：裁定一至四与验收清单原文不改，本节为现行修订。依据 #1539 P 类裁定稿，用户 2026-11-02 批复（[批复评论](https://github.com/xy7365527-lang/NewChanlun/issues/1539#issuecomment-6564138279)）；草稿、考古与审查原件：首两轮在 `/Volumes/AgentStorage/decisions/1539/`，其后依次为 `/Volumes/AgentStorage/fu17-repair40r/`、`/Volumes/AgentStorage/fu17-review40y/`、`/Volumes/AgentStorage/fu17-repair41f/`、`/Volumes/AgentStorage/fu17-review41k/`、`/Volumes/AgentStorage/fu17-publish41p/`（获批版本）；本仓存档 `.chanlun/review-results/issue1539-decision-20261102/`。）

**原因**：裁定二「恢复」条（:60）含两句。前句「检测上次 checkpoint、加载六面快照并重放至当前 bar」对三种证据类都成立，ADR 0051 裁定三（:274）即据此定恢复幂等。后句「杀停等同未完成 bar 的全部外效未发生，S/B/E 回退到上一 checkpoint」的前提只在 simulation 成立。experiment/production 下 checkpoint 之后可能已有真实回报和可能已发出的调用，按后句回退与 #1340 C07.6、C09.8、C09.9、AT-13 及 ADR 0030 裁定五相反。ADR 0039 把本条写进正式 launcher 启动序列（:27、:147、:289），故在本文件修订。

1. **通用（三种证据类）。** 恢复＝从最后一个 checkpoint 加载六面快照，再按持久日志重放。幂等判据为 ADR 0051:275-276 的 (a)(b)，任一不成立报 `StorageUnavailable` 并停写。任何证据类下恢复都不删除 append-only 真相行（ADR 0051:310）。
2. **simulation。** :60 后句照旧：未完成 bar 的外效视为未发生，S/B/E 工作态回到 checkpoint 快照，由受控撮合按同一五元组重跑该 bar。重跑产出与已持久行同 `fact_key` 同内容，按 (a) 返回原 application、不新增行；不一致即报 `StorageUnavailable`。
3. **experiment / production。** 不适用 :60 后句。重放持久日志直至最后提交：checkpoint 之后已 Recorded 的 E 事实与 Pending、已 Applied 的 Bᵢ 应用、X 已持久的 OwnAttempt/MayHaveCalled 与观测记录全部保留，不回到旧状态（#1340 C09.9）。恢复后先只读对账在途订单，外部未知按最大责任保留、不伪造终态（ADR 0030:48）；MayHaveCalled 保留最大责任、不自动重发（C07.6）；X 重启或换代先确认旧发送者已退出（C09.8）。
4. **验收。** H1/H2（:80、:81、:89）判据与射程不变：照 ADR 0056:63 裁定七 (a)，三种证据类的同模式会话都在固定完整输入（输入及修订、政策/模型、时钟、种子、数值语义、故障与调度轨迹，#1340 C10.4；experiment/production 的场所侧用受控场所夹具）下验 H2，各证据类以本节第 2、3 条各自的恢复方法满足它。#1340 AT-13「回退保留所有已经发生的外效」与 C07.6 不重发是附加约束，不替代六面 H2。恢复幂等另按 ADR 0051 裁定三 (a)(b)。本修订不增删验收项。
5. seek（:62-67）、不偷未来（:69）与裁定一、三、四不变。

## 修订（#2127，部署位置与双跑身份）

### 一、把账本身份和部署位置分开

同一份档案放在不同目录，应能查到同一笔账，也能验证同一条提交根链。主机本地的运行目录、`state_dir`、库和锁路径、Unix socket 路径、Voice 证据文件的本机路径，都是**部署位置**；不构成事实、权威来源或会话身份。新格式不得把它们放进 E/B 账本原件、图像、提交根、回执或其传递依赖，也不得把它们放进 simulation X 的业务元数据。摘要、嵌入证明、原始见证字符串中间接带入也算带入。部署记录可以留绝对路径，但有独立的版本、校验和保存边界，不充当账本事实或业务根输入。

会话、代际、域、来源、模型、授权与实际外效仍按原语义绑定。本机 Unix socket 路径不同于 ADR 0028 的**场所 endpoint**，也不同于确认写权、代际、因果或权限的任何标识。路径可以决定一次启动能否合法提供服务；不进根并不放宽 ADR 0039 的单写者与代际 gate 或 ADR 0059 的布局拒绝，也不授权迁库、换端点或接管旧端点。原址续服责任由 #2079 裁定，权威升代由 #2129 裁定。

### 二、新格式在写入前固定可验证身份

1. **E/B。** 以封闭、版本化的业务清单与部署清单分别解析，而不是从混合清单复制后剔除几个字段。业务清单保留政策、书账及资源合同、权威和来源、时钟/故障轨迹等所有原判据所需的字段；路径及仅部署层摘要不得混入。新版本业务 `manifest_hash` 只绑定该业务清单，部署清单的完整校验及部署指纹仍照其原入口核验。同名历史 `manifest_hash` 仍按原整份 manifest 算法读。E/B 的提交仍按规范图像、域、会话、会话代际、提交序号、前根和提交时刻算根；没有第二条可用于准入的「等价根」。跨域证明与回执仍查实际所引根。新 schema 在首写前由发布版本及持久登记绑定；未知版本、混合写合约、缺项或校验失败即拒。
2. **Voice。** 新版 bundle 的 artifact 条目为 `{name, sha256, bytes}`，`name` 是 bundle 内唯一逻辑角色，不是路径；独评仍覆盖整个 bundle 的精确字节、相同有序条目及全部唯一 `evidence_id`，其精确字节摘要与 bundle 摘要由受信业务清单预先固定。保留原有的 authority、标的、重、载体/γ、开局事实与分配、来源映射及 AsKnown 时点校验。部署解析器可供给文件或内容库位置；产品按逻辑角色和内容地址取得限定长度的原件，验证长度与 SHA-256 才接纳，缺项、换件、错独评均失败。入账持久化新版 bundle 与独评的精确字节；以内容地址闭包保存被独评的全部原件，使 B、依赖该证据的跨域证明消费者与离线验证器在原目录不可见时仍能按原件核证。部署解析器不能更换受信摘要、独评或原件归属。旧 `/1` bundle/独评里的路径已受字节摘要约束，不能删改、重签冒充旧证据或当成新版输入。
3. **simulation X。** 新版业务 `authority_profile` 持久保存模型、会话及代际、X 身份、事实来源、E/S 权威身份及代、信封版本/producer/namespace、条件清单与资源界；`socket`、`e.socket`、`s.socket` 只在部署清单。受准部署映射将本地路径定到唯一域；同一部署的重新打开仍按冻结位置和现有单写者、布局、回复身份、代际、因果门核对，不接受只换一个 profile 值就把旧库指向另一端点。路径冻结从混合 profile 移到部署边界，权威冻结和事实单源校验留在业务边界。公开权威、启动审计和离线查账按各自边界取数据；不以影子或回放数据冒充 X 原事实，也不把业务 profile 的相等当作迁址许可。

### 三、历史原件按原版本核验

旧库已提交的原件、图像、根链、消息、回执、依赖向量、`manifest_hash`、X profile 和获知时刻一律不改、不可回算覆盖。封存账套按原持久版本只读打开：随原件保留完整旧 manifest/profile、所需 SQLite 一致切面（含仍承载事实的 WAL 内容）、跨域依赖、及独评所引原件；在离线只读介质中根据归档索引用摘要取原件，而非连接旧 socket 或要求原目录存在。按原规则核原始根链、配置、证明与回执，再按原切面提供 `AsKnown`；业务读不到、引用不可复算或要求的原件闭包缺件就显式失败，不从别的版本、当前态或 `RecomputedWithRevision` 补齐。旧 Voice 持久重放能用原 witness 核清单和独评的原字节绑定，但这不等于重读了全部外部 artifact；归档若缺后者，差异报告列缺项，不报完整核证通过。

旧会话续服仍用旧写合同、原布局与恢复门；旧账在用不等于允许改历史。新版从新空会话建档，不让 `recover`、`serve` 或对拍器就地升版，不自动迁移存量真实责任。新旧并存时用已登记版本先分派读法，跨版本可独立核原件或另列重算结果，但不可拿旧根与新根的比较销 #1411。同一条历史链不混写格式。需接管旧活账或移动现役部署，分别走 C09.11、C11.5 的迁移及相应运维授权，保留旧权威账的可读链与尾责。

### 四、H1/H2 先声明比较合同，再严格验全状态

双跑使用 #1340 C10.4 所列全部固定输入。#1411 验收夹具负责人在 A/B 两臂启动前提交、冻结版本化比较计划；被比较的进程、请求和导出文件无权决定哪些字段可改名。计划绑定实现、读法/比较版本、完整输入与调度、检查点表、两臂标签与各自部署记录；H2 还绑定恢复用例与连续参照。由验收侧控制的追加式记录先封存计划规范字节，再登记实际启动回执（计划摘要、臂、有效输入和部署摘要、输出档案的验收侧身份）。启动器拒绝无预置记录；独立于被测进程的验收校验器用登记顺序、精确摘要与两臂绑定核先后和来源，不信任产物自报的计划、时戳或臂标签。未知合约或记录缺失、错序、错绑均失败；运行后的登记不能补成预声明。

本同模式比较合同的**业务改名闭集为空**；确定的会话业务身份作为同一份输入，由两套互不通信的介质和端点分别运行，不借同一命名空间复用进程或库。唯一可预声明改名项是验收夹具每臂报告头的 `/run_id`（每臂一个、非空字符串，不入业务清单、原件、根或回执）。计划按 A、B 预先登记两个不同值，校验器按精确位置核单值、不同值及反向唯一性，按计划把 A 头值映射到 B；没有该项的成对报告声明空映射且两臂均无此字段。其他位置的 run ID 引用不享有豁免。两臂路径取何值在部署记录中保留、单独核对，**不是重命名**。`session_id`、域与代际、源身份、时钟、Voice/命令/外效、摘要、根、回执及所有因果引用均不作为同模式改名项。ADR 0056 裁定七 (c) 的跨模式录放闭集只用于该 oracle，不移用到 H1/H2。

每个检查点独立核验两臂各自的实际持久根链、原件闭包、回执、引用及完整记录，再以同一已冻结合同逐字节比较六面（包括根、前根、图像、持久审计关系），并比 E、各 B 与 simulation X 业务库完整表清单、行数和规范字节。只要出现缺项、错误映射、根或闭集外差异，差异报告指明检查点、域、行和字段，判 **FAIL**。旧格式已经承诺路径，换路径导致的不同根就是该旧格式对拍失败；不换摘要、重签旧见证、投影后复判或扩大白名单。若今后想允许某种已入根的值改名，当前合同不通：需另立版本先证明它可从写端移出根闭包，再经独审变更比较合同，不能把现有两根互配为一一映射。

### 五、实施与验证边界

从正式 launcher 建两份新库，固定完整业务输入与时钟，**只换**两份隔离部署的 `--out`、其 `state_dir`、库/锁/socket 和 Voice 原件位置；两臂须实际生成 BindVoice、跨域证明、X 交换、成交/费用与原重应用。对拍须给出完整业务全表和 E/B 原根逐字节相等、两份部署记录分别有效；用真实中断/重启检查同一部署的原收据与 AsKnown。旧格式用原版本保留同路径正控、不同路径根不等负控，以及异机原目录不可见时保留原根的离线读取正控。篡改独评、artifact、任一实质身份/代、AsKnown、跨域引用、账项或根，及事后提交改名计划、未知字段/版本、缺一臂/检查点，均须有失败锁。单一受控夹具只证其适用域，不取代 Destination ④ 的完整历史及 #1411 的全部恢复矩阵。

受影响代码（#2127 取证基线 `b9d898dccf46c2a716115eaa1215bc39c458a959`）：`rust/src/economic_session/evidence.rs:45,95–175,178–263,285–354`、`voice.rs:235–265,272–278,332–384`、`service.rs:915–948,1125–1137,1213–1263,1472–1474`、`finance.rs:816–867,890–950,1948–1989,2210–2247`、`store.rs:281–301,665–682,766–776,797–816,993–1019,1099–1114,1615–1642`、`rust/src/history_simulation/runtime.rs:28–95,487–517,790–864`。本修订只定合同；产品写入、只读验档及正式差异报告由后续实施承担。
