> 正本：本文件是双跑确定性、恢复语义、seek 不偷未来、AsKnown 分证协议的教义正本。
> 最后裁定：#1537（2026-10-19）；修订：#1539（2026-11-02，见文末「修订」节）
> 受影响代码清单：见「受影响票与 blocking 边变化」节

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
2. **H2 杀停恢复**：t=1000 时 SIGKILL，重启从最后 checkpoint（如 t=950）恢复并续至 t=1050，六面快照与未杀停的连续运行在 t=1050 相同；**#2127 现行范围**：此连续参照判据适用于标准等价窗；必须停在安全状态的窗口另作专项验收，见[文末第四节](#四先冻结计划再分开验同轨迹确定性与-h2-恢复)。
3. **H3 seek 不偷未来**：seek(800) 后 `as_of=800` 输出不含 bar>800 的任何事实；TStage latch 值等于原运行在 t=800 的值，不等于 seek 时的当前成本重算值；
4. **H4 AsKnown 分证**：同一历史窗口分别以 `simulation` 与 `experiment` profile 跑，latch 触发 bar 可不同，各自独立，`simulation` 闸门通过不自动使 `experiment` 通过；
5. **反例通过判据**：任一 H1–H4 的 diff 非空 ⟹ FAIL 并留档，说明违反确定性/恢复/seek/分证之一；四项全空 ⟹ PASS。**#2127 现行范围**：H2 的空 diff 指标准等价窗；专项保留与连续臂的实际差异，按独立判据单列 PASS/FAIL，不能用专项 PASS 替代标准 H2。

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
4. **验收。** H1/H2（:80、:81、:89）判据与射程不变：照 ADR 0056:63 裁定七 (a)，三种证据类的同模式会话都在固定完整输入（输入及修订、政策/模型、时钟、种子、数值语义、故障与调度轨迹，#1340 C10.4；experiment/production 的场所侧用受控场所夹具）下验 H2，各证据类以本节第 2、3 条各自的恢复方法满足它。#1340 AT-13「回退保留所有已经发生的外效」与 C07.6 不重发是附加约束，不替代六面 H2。恢复幂等另按 ADR 0051 裁定三 (a)(b)。本修订不增删验收项。**#2127 现行范围**：前述连续参照等价指标准窗；无可证续接而必须保留责任或 `pending` 的故障窗，按文末第四节单列专项，实际外效或推进差异不报为空。
5. seek（:62-67）、不偷未来（:69）与裁定一、三、四不变。

## 修订（#2127，部署位置与双跑身份）

### 一、把账本身份和部署位置分开

同一份档案放在不同目录，应能查到同一笔账，也能验证同一条提交根链。主机本地的运行目录、`state_dir`、库和锁路径、Unix socket 路径、Voice 证据文件和 cap 签署原件的本机路径，都是**部署位置**；不构成事实、权威来源或会话身份。新格式不得把它们放进 E/B 账本原件、图像、提交根、回执或其传递依赖，也不得把它们放进 simulation X 的业务元数据。摘要、嵌入证明、原始见证字符串中间接带入也算带入。部署记录可以留绝对路径，但有独立的版本、校验和保存边界，不充当账本事实或业务根输入。

会话、代际、域、来源、模型、授权与实际外效仍按原语义绑定。本机 Unix socket 路径不同于 ADR 0028 的**场所 endpoint**，也不同于确认写权、代际、因果或权限的任何标识。路径可以决定一次启动能否合法提供服务；不进根并不放宽 ADR 0039 的单写者与代际 gate 或 ADR 0059 的布局拒绝，也不授权迁库、换端点或接管旧端点。原址续服责任由 #2079 裁定，权威升代由 #2129 裁定。

### 二、新格式在写入前固定可验证身份

1. **E/B。** 分别解析封闭、版本化的业务清单和部署清单。业务清单仍承诺政策、书账及资源合同、权威和来源、时钟/故障轨迹等原判据所需字段；业务 `manifest_hash` 只绑定业务清单。各 E/B 库在 `init` 取锁并校验布局后，与业务版本和创世提交同事务登记独立的部署版本和指纹。指纹按该部署版本绑定获准部署清单的规范字节，至少包括各域的库、锁、Unix socket 的规范路径与角色对应。该登记是库内启动元数据，不进业务表比较、图像、根、回执或跨域证明；验收另核登记的格式、值及实际路径。

   新库 `recover` 与任何 `serve` 在升代、业务写入或监听之前，须把当前配置经相同规则解析所得的部署指纹，与**该库首写的持久登记**核等，同时核业务版本及 `manifest_hash`。只验证新清单与其自报摘要相符不够；缺登记、未知版本、混合写合约或不符即拒，不补登或重绑，既有布局、锁与端点门照常执行。离线只读核证用归档的部署记录核其登记，无须重开原址。历史同名 `manifest_hash` 仍按原整份清单算法读。E/B 仍按规范图像、域、会话、会话代际、提交序号、前根和提交时刻算原根，跨域证明与回执只认实际所引原根。
2. **Voice。** 新版 bundle 的 artifact 条目为 `{name, sha256, bytes}`，`name` 是 bundle 内唯一逻辑角色，不是路径；独评仍覆盖整个 bundle 的精确字节、相同有序条目及全部唯一 `evidence_id`，其精确字节摘要与 bundle 摘要由受信业务清单预先固定。保留原有的 authority、标的、重、载体/γ、开局事实与分配、来源映射及 AsKnown 时点校验。部署解析器可供给文件或内容库位置；产品按逻辑角色和内容地址取得限定长度的原件，验证长度与 SHA-256 才接纳，缺项、换件、错独评均失败。入账持久化新版 bundle 与独评的精确字节；以内容地址闭包保存被独评的全部原件，使 B、依赖该证据的跨域证明消费者与离线验证器在原目录不可见时仍能按原件核证。部署解析器不能更换受信摘要、独评或原件归属。旧 `/1` bundle/独评里的路径已受字节摘要约束，不能删改、重签冒充旧证据或当成新版输入。
3. **simulation X。** 新版业务 `authority_profile` 持久保存模型、会话及代际、X 身份、事实来源、E/S 权威身份及代、信封版本/producer/namespace、条件清单与资源界；`socket`、`e.socket`、`s.socket` 只在部署清单。受准部署映射将本地路径定到唯一域；同一部署的重新打开仍按冻结位置和现有单写者、布局、回复身份、代际、因果门核对，不接受只换一个 profile 值就把旧库指向另一端点。路径冻结从混合 profile 移到部署边界，权威冻结和事实单源校验留在业务边界。公开权威、启动审计和离线查账按各自边界取数据；不以影子或回放数据冒充 X 原事实，也不把业务 profile 的相等当作迁址许可。

   冻结的是创世绑定和每次交换实际使用的绑定。E/S 恢复升代后的活体接续，以 [#2129（ADR 0073）](https://github.com/Newchanlun/NewChanlun/issues/2129) 的具名恢复原回执核验与持久续接已交付为前置：正式 launcher 对同一域库核验当前 `current-recovery` 原回执，确认对端已按获准代启动，X 核旧→新连续关系并原子追加 `x-authority-binding/1`，才开放新交换。只更新恢复域的当前目标代，不改创世 profile、X 自身代、E 的 `authorized_sources` 或原命令；缺证据、旧代或手填新代均不放行。

   历史接纳、S 执行与占有证据按发生时记录的绑定序号和原纪元核验，原请求、回执、时刻和因果引用逐字节不变。新 `QueryReleasedExact` 只按当前获准 E 代发出并核应答信封。新应答不是重签的原回执，也不授予 S 执行资格或新的调用权。S 的历史证据和当前查询按同一原则分开。

   **新版 E 查询用 `x-exact-authority/2`。** 只版本化 E 侧 `QueryReleasedExact`，保留 `/1` 请求字段和十二个回复字段，`protocol` 改为 `x-exact-authority/2`，回复必带 `release_origin`。`ReleasedExact` 时，`authority_epoch` 是当前应答代，`receipt_id` 与 `commit_ns` 分别是原交付回执身份与提交时刻，`release_origin` 为 `{writer_epoch, cut}`；其中 `writer_epoch` 沿用原请求的正整数文本，`cut` 是原回执的 `{domain_id, commit_seq, root_hash}`。E 在同一只读切面按命令身份和内容查回实际 `ReleaseExact` 原件及持久 `ReleasedExactReceipt`，从原提交请求的 `writer_epoch` 取原交付代，从原回执取 cut，并核原序号、时刻和回执绑定；不得用当前 writer 或当前 cut 补值。`NoRecord` 和 `Unsupported` 的 `release_origin` 为 `null`，不接纳。新版会话在首写时绑定该查询版本，旧 `/1` 与 S 查询形状不改，不在失败后降级。

   X 在接纳前核 `/2` 实际应答与当前绑定，并核命令和摘要、`release_origin` 的 E 域、合法原切面、原交付代在同一 E 的已核绑定链内且不晚于应答代、本次获知不早于原提交。缺项或不一致不接纳。X 将本次查询绑定序号、规范请求和应答与交付因果引用同事务持久化；该引用绑定命令摘要、原回执 ID、原交付纪元、原 cut 和原提交时刻。其中 `causal_refs` 的交付 `authority_epoch` 和 `release_cut` 分别取 `release_origin.writer_epoch` 和 `release_origin.cut`。恢复和 `QueryCommand` 从此持久引用核验与读回，不能从当前 profile 填入原交付代或要求外部验收器补证。

4. **FIN cap 激活与精确交付。** 新格式首版登记单一受控写合同 `tb03b-finance/6`，只配套本节新版清单和非内容型 E/B 域。它以 `economic-session/1` 上的 FIN/5 财务语义为底座，保留 `MakeDispatchable`、`ReleaseExact`、`QueryCommand`，并使用上文 `x-exact-authority/2` 的 `QueryReleasedExact`；同时承接 FIN/3、/4 共有的 cap 激活与原鉴权规则，不并入 FIN/4 独有的内容域接口。选用 `/6` 的受控会话在 E 与所有 Bᵢ 首写时统一绑定该版，财务输入、业务图像和恢复均按 `/6` 核验，既有 `/1`–`/5` 边界不变。新旧组合在初始化及打开时先校持久版本，写入口拒绝旧请求形状、未知字段和混合版本。

   `ActivateCapPolicy` 的业务请求中，`policy_record` 只接受 `{sha256}`，角色固定为「cap 签署原件」。部署清单以该角色和已承诺摘要解析唯一位置；调用方直接生成并按新合同鉴权无路径请求；路径不进入消息、payload 摘要、图像或证明。不得接收旧 `{path, sha256}` 再删字段、重算请求摘要。

   新激活仍在原 E 写者锁和当前纪元下，沿用原文件类型、字节上限、UTF-8 和资源/期限门读取精确签署字节，先核 SHA-256，再照原判据验证签署记录类型、签署者和签署引用、资金 profile/政策/币种/量纲、版本及所取代版本、金额、有效期和签署时点；在同一提交原子点核现有责任和现行 cap 版本。签署引用是业务证据引用，不能用本机定位代替。错件、缺件、越权、过期或责任不符不提交消息、回执、cap 或新根。原始签署字节随 `witness.cap_policy_raw` 保留，与无路径的请求、E 历史和回执原子提交；后续跨域引用、审计重放与离线核验用持久原件及原摘要，不回读部署路径。已提交的同身份同内容重送查回原回执、不同内容仍拒；不得因原文件移动而否定或重发已提交激活。受控 FIN `/6` 仍只用于 `TestOnly` 组件，不能提供正式 `logical-bar/1` 的 E 交付；不新增可签人、真实资金权限或额度。旧 FIN/3、/4 仍用旧请求和原签署字节验旧图像、根与回执，原址续服按旧合同。

   `/6` 的 `Reserve` 在 E 同一事务按当时生效的 cap 版本、金额、有效期和全量责任决定准入，留存实际使用的 cap 记录。`ReleaseExact` 在提交原子点从真实前切面重核当时生效的 cap：其 `valid_through_ns` **替换**旧的创世 cap 期限门，不叠加，也不回退。签署激活取代旧版本的金额和有效期；过期的旧版本无否决权，仍有效的旧版本也不能救济已过期的现行版。全量责任仍须在现行 cap 内且原 grant 责任完整；冻结能力及其独立有效期、Pending、目标代际和条件清单等原交付门照常核验，激活不延长这些前件、不改旧 grant 或已交付命令、不释放既存责任。验收以 E 的激活原件和回执、`Reserve` 记录及 `ReleaseExact` 前后原切面核证；X 按新版查询核原交付，再走 S 条件核验和唯一调用边，不重判 cap。

### 三、历史原件按原版本核验

旧库已提交的原件、图像、根链、消息、回执、依赖向量、`manifest_hash`、X profile 和获知时刻一律不改、不可回算覆盖。封存账套按原持久版本只读打开：随原件保留完整旧 manifest/profile、所需 SQLite 一致切面（含仍承载事实的 WAL 内容）、跨域依赖、独评所引原件及历史 FIN 激活的原请求与签署见证；在离线只读介质中根据归档索引用摘要取原件，而非连接旧 socket 或要求原目录存在。按原规则核原始根链、配置、证明与回执，再按原切面提供 `AsKnown`；业务读不到、引用不可复算或要求的原件闭包缺件就显式失败，不从别的版本、当前态或 `RecomputedWithRevision` 补齐。旧 Voice 持久重放能用原 witness 核清单和独评的原字节绑定，但这不等于重读了全部外部 artifact；归档若缺后者，差异报告列缺项，不报完整核证通过。

旧会话续服仍用旧写合同、原布局与恢复门；旧账在用不等于允许改历史。新版从新空会话建档，不让 `recover`、`serve` 或对拍器就地升版，不自动迁移存量真实责任。新旧并存时用已登记版本先分派读法，跨版本可独立核原件或另列重算结果，但不可拿旧根与新根的比较销 #1411。同一条历史链不混写格式。需接管旧活账或移动现役部署，分别走 C09.11、C11.5 的迁移及相应运维授权，保留旧权威账的可读链与尾责。

### 四、先冻结计划，再分开验同轨迹确定性与 H2 恢复

本节细化 #1539 第 4 条的 H1/H2 验收；各证据类的恢复方法不变。#1411 验收夹具负责人在任何臂启动前冻结版本化计划，绑定 #1340 C10.4 的全部输入、实现、证据类、调度、时钟合同、读法与比较版本、检查点、各臂角色、预期故障位置和部署记录。计划绑定未中断连续臂 C，以及同一故障用例的两个恢复重复臂 R₁、R₂；逐用例预先指定故障边界及所属验收栏（标准等价或本节列出的专项），不按实测差异改栏。三臂用同一业务输入及同一场所脚本；脚本按收到的写调用产生回报，不向未调用的臂补送。experiment/production 用受控场所夹具和外部进程监督器做真杀，不在正式 manifest 配置 `TestOnly` 或 `fault_schedule`（ADR 0056 裁定五）。

**正式 simulation 的三臂输入。** C 的 `scenario_contract.fault_schedule` 冻结为空数组，不注入故障；R₁、R₂ 冻结完全相同的有序计划、目标域和触发点，实际触发必须与计划逐项相符。按 ADR 0052 裁定一、五保留各臂完整 profile、实际调度及触发轨迹，分别按原规则核 `content_hash` 和完整输入承诺；不要求 C 与 R 的完整摘要相等。

独立校验器从各臂实际加载并已核证的 profile 和原始输入出发，仅从 `history-input-profile/1` 的比较副本移去 `/scenario_contract/fault_schedule`，核其余字段的 JCS 规范字节和同序原件逐字节相等，再按冻结比较版本重算并核等三臂的业务输入摘要。容量、bust、模型、时钟、调度器及其余字段一律保留。完整 profile 的差异只能来自该故障计划；轨迹差异必须能从真实触发、退出与接续证据逐项归因。比较用摘要只用于验收，不替换原 `content_hash`、任何持久摘要或提交根。

验收方先在其控制的追加式记录封存计划的规范字节，再登记实际启动回执（计划摘要、臂、有效输入和部署摘要、档案身份）。独立校验器按登记顺序、精确摘要及逐臂绑定核来源与时序，不能信任产物自报的时戳、计划或标签。冻结计划缺失、错绑、迟登记、未知版本均失败。业务改名闭集为空；同一会话业务身份在互不通信的介质和端点上重复运行。唯一可映射项是成对报告头的 `/run_id`：每个参与臂的非空标签由计划预登记且互异，比较时只核该对头值的双射；空映射时两头均无该字段。部署路径各自核验，不是重命名。会话、域、代际、源身份、时钟、事实、根和因果引用都不能改名；不借用 ADR 0056 裁定七 (c) 的跨模式闭集。

1. **H1 与同轨迹重复（R₁ 对 R₂）。** H1 两臂同为未中断；R₁、R₂ 在隔离部署重跑同一冻结故障和调度。每个检查点先逐臂核实际原根链、原件闭包、回执与引用，再比完整六面及 E/各 B/simulation X 业务库的表清单和行数；写者代数、升代原因和顺序必须相等。按启动前登记的时钟合同判定其余字节：

   - **固定逻辑读数。** 正式 simulation 按 `logical-bar/1`；直调域的组件夹具单独固定 E/B 的 `TestOnly` 读数及 X 的逻辑 bar 前沿。两臂读数相同，业务全表与原件逐字节相等，含 `meta.writer_epoch`、完整 `epochs`、提交图像、前根、原根和原回执。旧格式只换路径导致原根不同，仍是 FAIL。
   - **`System`（正式 experiment/production）。** 按 ADR 0056 保持正式时钟。`SystemTime::now` 的实际纳秒在首写同时进入 `epochs` 和创世 `commit_ns`，而 `commit_ns` 和前根都参与算根；不能从逻辑检查点相同推出原根相同。计划冻结读数位置、事件顺序、允许时间窗和时间门预期，验收方以独立于业务库与导出器的只读观察记录逐臂采集时钟返回值（包括经 vDSO 返回的读数），按域、稳定业务事件或写者转换、读取阶段和序号绑定；不替换时钟，不从待比较的行反推读数。缺测、越窗、顺序改变或期限/有效期/获知门结果与冻结预期不符即失败。
   - **`System` 的逐字段判据。** 版本化比较表在启动前列明允许随上述读数变化的类型和字段位置：本机时钟写出的接收、首次获知和提交时间，`epochs` 的 init/recover 时点，以及从这些读数传递得出的字段（含前根/原根、内嵌 proof、回执、摘要）。例如 `source.received_time` 只有经版本合同证明取自本机读数时才列入；场所原始报文与场所给出的事件时刻仍须原样相等。在每对对应行中，直接或复制的时点核到该臂实际读数及来源，派生字段按各自真实前根、图像、原件与因果边逐一复算。根输入相同必须原根逐字节相等；根输入不同时，须逐项证明差异只来自已核证的读数及其派生链，不能仅验两条链各自一致。其余字段一律逐字节相等，包括业务身份、epoch 数值、提交序号、账与责任、命令/回报/分配。无规则的差异或缺少独立证据即失败；不得丢字段、替代摘要、改写 `AsKnown` 或按字段名批量放行。

2. **标准 H2：恢复后与连续参照六面等价（R₁、R₂ 分别对 C）。** 对可证续接的标准窗，按 :81 和 #1539 在同一逻辑检查点列出六面、事件输入及业务键、原件、回执和因果链；对业务值与来源纪元、身份、顺序、因果关系逐字段硬判，并以独立 oracle 核账、责任/最大保留、外部调用、获知时点与恢复结果。不比两类轨迹的整库字节；标准窗不接受实质外效缺行或未达检查点。试验记录须证明 R₁、R₂ 各自在指定边界真实退出、原址正式恢复和接续，C 保持未中断。不能用同进程第二实例、跳过锁或给 C 补造恢复事件。
   - **写者履历是必验输出。** 依事件序验证获准域旧写者退出、原址锁交接及恢复回执。E 从首代正式恢复一次时，C 的 `meta.writer_epoch=1`、`epochs=[(1, init, init_ns)]`；R 必须为 `2`，保有原行并恰好追加 `(2, recover, recover_ns)`。每次恢复只升一代，时间按各臂时钟合同核证且不早于已提交事实；`Recovered.cut` 与该臂恢复前最后持久切面相同。新写须用获准纪元，旧代不得新写。跨域后续查询或授权按真实获准代和原合同核验；不把 E 的升代数套到别域。旧代在途、提交事实和已发或可能已发调用继续保有原身份及责任。
   - **升代后实读原交付。** 该用例有两项具名前置：#2129 的权威绑定接续，以及正式 E 精确交付（`logical-bar/1`，#1407 C2 第 4 项的时钟接入）。后者须能在正式 launcher 下用获准的正式财务输入持久提交 `ReleaseExact` 并应答新版查询；当前 `TestOnly` 财务输入及第五节 FIN `/6` 组件结果不能销项。前置齐备后，在正式 simulation 恢复臂真杀 E₁ 前，由 E₁ 持久交付两笔 `ReleasedExact`：一笔已被 X 接纳，一笔尚未接纳。E 按具名回执升到 E₂，X 完成第二节 3 的绑定接续。
   - **直接核 X 持久因果引用。** 旧接纳证据仍按 E₁ 核且字节不变。X 首次接纳第二笔时实际向 E₂ 发 `QueryReleasedExact`；从 X 持久接纳记录核查询绑定和规范应答指向 E₂，交付因果引用保存 E₁ 的原回执 ID、原交付代、原 cut、命令摘要和提交时刻，并与独立保存的 E₁ 原件逐项核等。重开后 `QueryCommand` 必须从 X 持久记录读回同一引用；引用缺项或写成 E₂ 即失败，不从 E 库事后补证。E 不新增交付，X 只新增一次接纳，不改两笔命令的身份、既有责任或已取得的 S 资格；重复接纳只查原结果。S 单独换代按 #2129 核查真实 S₂ 交换及 S₁ 历史证据，不联动改变 E 的绑定。
   - **代、时钟或根进入六面时仍要逐项核证。** 以相同业务身份和逻辑因果边配对，不把 writer epoch、真实时刻、根值或原回执配成改名。共同已提交前缀按第 1 项适用的时钟合同核等；若字段按合同承诺完整 profile 或故障轨迹，按本节输入规则逐臂复算。各恢复臂重启前后原件、原根、原回执逐字节不变。已提交重送返回该臂原回执，不追加原业务提交；未提交的按原合同续接。后续检查点按版本化类型穷举字段：相同业务值硬比；确由恢复导致的差异，用逐臂时钟及独立记录的事实、写权转换和具体因果边核出预期值。proof 的 `current_epoch`、`current_epoch_at_ns` 对应该臂取证点有效的 `epochs` 行；历史/当前 cut、图像、前根、时刻、回执必须指向该臂真实提交并按原根式复算。首次获知不能回填，cause 链逐边核对。只有已核证的故障配置及其轨迹、时钟、写权或实际外效差异传入根，才允许原根不同；未知差异即失败。

3. **专项安全验收：不重发，保留责任或 `pending`。** 下列窗口不参加第 2 项的 R/C 六面等价判定。R₁、R₂ 仍在同一恢复后切面按第 1 项核六面等价和持久证据；各自与 C 比较时，按专项期待核真实差异，不虚构恢复臂已经到达连续臂的下一检查点。

   - **`MayHaveCalled`：写意图已落库、实际场所调用前（experiment/production，SPEC C07.6）。** 外部监督器在 X 持久提交 `MayHaveCalled` 后、进入唯一调用边前停住并杀死 R 的旧进程，记录实际故障边界。验收方按臂、原命令 ID 和检查点核独立受控场所的完整请求、回报及持仓记录；不以 X 自报、超时或未见回报证明未发。

     | 臂 | 该命令的场所写调用 | 回报、应用与责任 |
     |---|---|---|
     | R₁、R₂ 各自 | **0** 次，杀前与恢复后合计，只读对账不计 | **0** 条场所回报或新增分配；X 保留原占有记录，E 保留原最大责任，B 无该命令的成交或费用，物理持仓不因该命令改变。 |
     | C | **1** 次 | 原始成交与费用按冻结脚本实际发出、记录、分配并应用。完整证据到达前 E 保留最大责任，之后按真实回报和独立责任 oracle 核应留余额，不假定成交即归零。 |

     核各臂六面、受影响行数、金额和因果链；除已核证的时钟及恢复履历外，只允许上述一次调用及其已核证后果造成的差异，并如实列出。这一栏的 PASS 是不重发且保留最大责任，不是 R/C 六面全等。

   - **`ExecutionRequested`：X 已持久记录 S 资格请求、尚未发送首字节（simulation）。** 在同一原命令及批次上真杀 X，并独立核 S 侧请求/记录。C 正常发送一次 `RequestConditionalExecution`，在夹具条件满足时核真实 `ExecuteCommitted` 并推进。每条恢复臂发送该申请 **0** 次，只能用原命令、原摘要和原交付回执发 `QueryExecuteCommitted`；实际 S 回 `NoRecord` 后，原批仍 `pending`，原 `ExecutionRequested` 和责任不变，无 S 资格收据、X 新占有或撮合原件，不得到 C 的下一检查点。R₁、R₂ 的六面在该等待切面核等，报告保留 C 已推进、R 仍等待的差异。此状态的可证续接是继续推进的待解决前置；`NoRecord` 不授权重发，本地撮合事务幂等也不覆盖这条 X→S 边。只证得安全留停，不得记作该窗口已恢复推进。

报告分列同轨迹对拍、标准 H2 等价及专项安全结果。标准窗只有同轨迹、连续参照与履历核证均通过才判 H2 PASS；专项按自身判据给 PASS/FAIL，保留实际差异及未达的检查点，不写成空 diff，不替代标准窗。缺前置单列未验，未解释差异一律 FAIL，定位到检查点、域、行和字段。H3/H4、恢复不重发与尾责、原合同的恢复幂等、AT-14 及 #1411 的实际故障边界与独立 oracle 不变。

### 五、实施与验证边界

路径与根的正控分两层，各自新建两套隔离部署，固定完整业务输入，只换 `--out`、`state_dir`、库/锁/socket 和适用的证据位置。两层不得拼证：

1. **正式 launcher 验装配和续服。** 用正式准入的 simulation manifest，以 `logical-bar/1` 启动并实际产生已获准的非空业务提交，在相同检查点比较 E/B/simulation X 业务全表与 E/B 原根，独立核部署登记，并验原址正式续服。其中两笔 `ReleasedExact` 后真杀 E 的用例须先具备第四节的正式 E 交付能力。experiment/production 正控保持 `System`，双跑与真杀按第四节核验。正式 launcher 遇 `TestOnly` 或模式与时钟不符，须在拉起任何域前以 `InvalidDomain` 拒绝；experiment/production 不接纳会话 `fault_schedule`。本层不以组件的 BindVoice、FIN cap 或 TestOnly 原件证明正式准入。
2. **直调域组件验签署、用 cap 和精确交付。** 不经过 `production_session`。在两套测试部署分别直调真实域进程，E/B 使用 `TestOnly` 和同一 `tb03b-finance/6`，每套实际完成 `BindVoice`、跨域证明、从同一精确字节的签署原件激活 cap，并用激活后的版本对夹具的同一命令做 `Reserve`、实际 `ReleaseExact`、X 向该套 E 查 `QueryReleasedExact`、S 核验、受控撮合产成交/费用并应用到原重。固定组件时钟，使 X 的逻辑接纳不早于 E 交付、调用不早于 S 提交；不换权威端点、不注入合成回执。原责任加本单新增责任须高于创世 cap 而在新 cap 内；`Reserve` 与 `ReleaseExact` 均须用已激活版本。比 E/B/X 完整业务全表和 E/B 原根，核 cap 签署字节、摘要、消息、版本、原回执及原命令因果链，并验证原目录不可用时仍能按原件核证和查回。结果只作组件证据。

   - **两条独立 cap 负控。** 不激活时，在 `Reserve` 断言无该 grant 或 `ReleasedExact`，既存责任不变。另起一用例：已激活的 cap 在 `Reserve` 和 `MakeDispatchable` 时均有效，已取得完整 grant 与 `Dispatchable`；冻结时钟使激活版在 `ReleaseExact` 的拟提交时刻已过期、创世版和其他交付条件仍有效。必须因当前 cap 过期拒绝，不能回退创世版；保留原 `Dispatchable` 和 grant 全量责任，无 `ReleasedExact` 提交或交付回执。X 用原命令向实际 E 查询 `QueryReleasedExact`，核 E 应答为 `NoRecord` 且 X 不接纳，超时不算通过。错摘要、缺件/换件、跨 profile、签署或量纲不符、旧请求写新版、cap 不足仍各有失败锁。
   - **cap 期限反向正控。** 在创世版与激活版均有效时取得完整 grant 和 `Dispatchable`，随后在创世版过期、激活版仍有效且其余交付门均满足时提交 `ReleaseExact`。必须放行；核 E 的实际 `ReleasedExactReceipt` 及原切面，X 向同一 E 发新版 `QueryReleasedExact` 可查并接纳，持久引用与该回执相符。不得因创世版过期拒绝，也不得把现行 cap 的有效期当作其他能力证据的展期。
   - **真实 S 资格提交与查询前置（TB-04-D/E）。** S producer 必须经真实 `RequestConditionalExecution` 对原命令及其 E 原交付核验条件并持久提交资格；再以原命令 ID、摘要和原交付回执执行 `QueryExecuteCommitted`，查回 S 的原持久回执。X 只以它核 `eligibility_ref` 和调用时序。真实 producer 未交付时，此正控待前置；现有受控夹具直接构造的 `ExecuteCommitted` 不得销项。
   - **回报应用的具名前置。** 此正控依赖 [TB-04-F（#1425）](https://github.com/Newchanlun/NewChanlun/issues/1425) 单一明确归属闭环在受控撮合原件上的两项能力：E 按获准分配合同从真实 X 成交/费用原件核原命令、归属、完整经济分量及费用前件，持久化权威分配和对应解待证据；B 按首写冻结的 TB-03-C `book_revision` 走真实书账分派，核 E 原分配后应用到原重，返回实际 `Applied` 回执。验收逐笔连查 X 原件与 `fact_key`、E 分配身份与原提交切面、B 回执的分配身份与原重，核费用对原成交的因果引用、实际账项与独立 oracle；仅有原件接纳、`Recorded`、`Pending` 或 `Unmatched` 均不通过。FIN `/6` 不改变 `history-sim-unresolved/1` 的 E 解待及 B 应用门；上述能力未交付时本正控待前置，不得绕过门、伪造经济分量或把部分结果报通过。

**部署绑定负控。** 对已初始化的新 E/B 库，保持业务清单和 `manifest_hash` 不变，分别替换一个已绑定的库路径或 Unix socket 路径；提交自身合法且指纹自洽的新部署清单。库路径用例以有完整一致切面的原库副本在另一个有效路径重开，不能以文件不存在或布局冲突代替核证；socket 用例指向合法、未占用的不同路径。`recover` 和 `serve` 都须因首写部署登记不符而拒绝，不升代、不业务写、不监听；原部署仍能续服。离线只读核证不授予迁址续服权。

以真杀和原址重启跑同轨迹对拍、标准 H2 与专项安全验收。应能抓到 R 少升一代、C 多出恢复行、恢复改写原收据、旧代新写、错误 proof 纪元或根、错误获知时点、重复外发或少留责任，即使终值相同也失败。`System` 双跑须有实际读数不同、原根随之不同但业务轨迹通过的正控；单改时点后连带重算根，若不符独立读数仍必须失败。保留旧格式同路径正控、不同路径根不等负控和原目录不可见时按原根离线读取正控。篡改独评、artifact、身份/代、AsKnown、跨域引用、账项或根，或事后提交计划、未知字段/版本、缺臂或缺少该验收栏规定的检查点，均须失败。单一受控夹具不替代 Destination ④ 完整历史与 #1411 的全部恢复矩阵。

受影响代码（#2127 取证基线 `b9d898dccf46c2a716115eaa1215bc39c458a959`）：

- 路径、内容与跨域根：`rust/src/economic_session/evidence.rs:45,95–175,178–263,285–354`、`voice.rs:235–265,272–278,332–384`、`service.rs:915–948,1125–1137,1213–1263,1472–1474`、`finance.rs:816–867,890–952,1948–1989,2210–2247`、`store.rs:281–301,665–682,766–776,797–816,993–1019,1099–1114,1615–1642`、`rust/src/history_simulation/runtime.rs:28–95,487–517,790–864`。
- FIN cap 与精确交付：`rust/src/economic_session/finance.rs:45–121,124–174,194–232,335–348,765–790,1244–1374,1476–1521,1633–1712,1811–1849,1860–1931,1977–1981,2080–2085,2221–2247,2303–2407`；`service.rs:642–674`（消息原件）；`finance_tests.rs:1555–1565,1741–1772`（现有受控夹具）；`rust/src/history_simulation/runtime.rs:273–294,543–580,614–640,729–764`（X 权威应答、时钟与本地事务边界）。
- 恢复后的 X 交换、原交付引用与安全等待：`rust/src/history_simulation/runtime.rs:296–320,490–517,595–640,682–715,735–764,790–831`、`rust/src/economic_session/exact_command.rs:411–433`、`rust/src/economic_session/finance.rs:1730–1736,2184–2189,2221–2247,2362–2407`（按 #2129）。
- 交付期限与正式时钟、真实 S 资格前置：`rust/src/economic_session/finance.rs:214–232,1164–1183`、`rust/src/economic_session/exact_x_e2e_tests.rs:1–4,153–191`。
- 模拟原件的解待、分配与书账分派：`rust/src/history_simulation/intake.rs:10–95`、`rust/src/economic_session/tb03c_e.rs:89–97,172–181,255–273`、`tb03c_allocation.rs:401–515`、`book.rs:39–50,398–416`、`service.rs:1150,1982–2072`。
- 恢复、时钟与 proof 核证：`rust/src/economic_session/store.rs:318–353,659–682,797–805,829–835,1075–1086,1694–1725`、`service.rs:679–695`、`finance.rs:829–855,890–952,2184–2207`。原址端点和锁见 #2079 已发布裁定；本修订只定合同，产品写入、正式恢复与差异报告由后续实施承担。
