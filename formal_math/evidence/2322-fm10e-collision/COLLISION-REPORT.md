# FM-10e 第三方独立语义对撞报告（#2322）

## 0. 输入基线与对撞总览

- 对撞官：第三方独立语义对撞官 `fm10e-collider-neon`（`gemini-4-neon-xhigh`，与甲方 `claude-opus-5-5-high` 及乙方 `gpt-6.2-astra` 均不同家）
- 基线提交哈希绑定（`shas.txt`）：
  - 甲方（Opus，`origin/blind/fm10e-opus`）：`d722b1703fecbdcd23458f671b6831f470049904`
  - 乙方（Astra，`origin/blind/fm10e-astra`）：`b2bfc504fcb2a6a29c664f46c8e3f89abce65c06`
  - 上游基线（`decl/fm10c-core`）：`8c5ad6a215b41d6a905f02691964c947438637b8`
  - 裁定与引文包（`pack-fm10e`）：`3c1fd5e022a34bfd9683e28a86569ad81f0b6cfa`
- 外部对撞参考（仅在对撞阶段引入）：`astra_repair_design_audit.md`、`astra_plan_audit_review.md`
- 覆盖范围：`04-interface-constraints.md` 全部 13 个文件、全部 81 个点名公开定义

### 全局分类统计

| 分类 | 数量 | 占比 | 判定口径说明 |
|---|---:|---:|---|
| `EQUIV` | 31 | 38.3% | 类型同构（或固定 `ℚ` 载体下双射）且语义逻辑逐位等价 |
| `SEPARATED` | 43 | 53.1% | 存在可手算或可 `decide` 复现的有限反例见证，且依据原典、裁定包或数学标准可当下定性优劣 |
| `UNDECIDED` | 7 | 8.6% | 存在明确有限分离见证，但原典与 `#2295`/`#2322` 裁定包确留白，须交 `needs-fable` 拍板定口径 |
| **合计** | **81** | **100.0%** | 另附 FM-42 外部候选独立裁定轴 `U-8`，总计 8 条 `needs-fable` 裁定轴（`U-1` 至 `U-8`） |

### 关键结论摘要

1. **隔离与零公理红线全部过关**：甲乙全部 26 个文件均首行 `module`、公开定义放 `@[expose] public section`，零 `axiom`/`sorry`/`partial`/元编程，`Chan/Defs/` 零导入 `Chan/Proxy/` 与 `ChanDyn/`，`ChanDyn/` 零反向导入，五项假设均落在 `Prop`、无默认值且依赖闭包不含结论谓词（满足门禁 14），零 `105:518` 娇注泄漏。
2. **发现 6 项影响下游冻结的高危缺陷或结构失配**：
   - **M19b 模型 A 阻尼因子共同缺失**：甲乙双方的 `WellModel` 与 `ThrustModel` 均硬编码无阻尼步进（`ρ = 1`），均无法直接实例化 `#2322` 评论 1 模型 A 的阻尼临界预算 `B_* = 8/3`（`ρ = 1/2`）；甲另漏约束 `f 0` 与 `x 1`，且 `BudgetBound` 在滑行 `b` 段时瘫痪（`W29`, `W32`）。
   - **M19b 模型 B 甲方不可实例化**：甲 `AsyncAgentSystem` 为单维即时价格反馈，结构性无法实例化二阶异步滞后方程 `x_{t+1} = (1 - k_0) x_t - k_1 x_{t-1}`（如 `k_0 = 1, k_1 = 1/2`）；乙凭借向量状态与因果延迟时钟 `seen t i ≤ t` 可精确实例化模型 B 及渐近稳定域（`W34`, `W35`）。
   - **M16b 与 M16c 空头定向致命分歧**：甲 `StructImpulse` 缺失比较方向 `side : Dir`，致使所有下跌单腿的 `impulseFromRest .posVar` 恒塌缩为 `0` 且 `terminalVelocity` 符号颠倒（`W7`），同时用 `Seg.zigEnd - Seg.zigStart` 错把区间极值当真实出入价（`W6`）；甲 `ForceSpec.evalForce` 将 `orient` 置于势函数之前，对非奇对称势函数与乙不对易，且在 `first = 0` 触发 `0 - 1 = 0` 截断减法伪造前驱（`W11`）。
   - **M17 盘整背驰双方互斥、趋势终结甲不穷尽**：在 `ConsolDiv` 上，甲仅认 `i < z.start`（标准 `a+A+c`），乙仅认 `z.start ≤ i`（同枢两次离开），二者完全互斥（`W13`）；在 `trendEndClassify` 上，甲对“无背驰顺向离开后直接反向三卖”三分支全假（`W16`）；在 `SmallDivTriggersBigTurn` 上，甲遗漏 `044:24/26` 次级三类点必要条件（`W18`）。
   - **M18 可观测性拓扑错位**：甲将 `PrefixObservable` 写为闭开集（clopen），误杀“价格最终触及 1”这类基本开集事件；乙正确采用拓扑开集（`W19`）。
   - **M19a 第 30 课非趋同前提甲有逻辑漏网**：甲 `NonIdenticalTrading` 在双人完全同步两日同向交易上误判为真（`W28b`）；甲 `Chan/Proxy/Macd.lean` 模块注释另误将带 2 倍因子核常数 `56` 记为无系数版本口径（实际无系数版本核常数为 `28`）。

---

## 1. 逐定义三分类完整矩阵（13 文件、81 个点名公开定义）

按 `04-interface-constraints.md` 顺序逐文件、逐定义列出三分类结果与核心依据。`SEPARATED` 与 `UNDECIDED` 对应的具体有限反例见证 `W1` 至 `W35` 详列于第 2 节。

### 1.1 M16a `Chan/Proxy/Ema.lean`（5 项：2 `EQUIV` / 3 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `EmaParams` | `SEPARATED` | 甲限离散周期 `N : ℕ`（仅表达 `α = 2/(N+1)`），乙允许任意有理 `α ∈ (0,1]`；显式播种含义偏移一步（`W1`） |
| `emaSeq` | `SEPARATED` | 首值播种在 `α = 2/(N+1)` 时逐位等价；显式播种时甲将 `pre` 视为时刻 `-1` 并在 `t=0` 吸收 `x 0`，乙直接置 `ema 0 = v`（`W1`） |
| `smaSeq` | `EQUIV` | 在正周期 `N : ℕ+` 上公式逐位等价；注记甲以 `N : ℕ` 接收参数，未在类型层屏蔽 `N = 0` 的 `0/0 = 0` 退化 |
| `emaDecay` | `EQUIV` | 在正周期 `N : ℕ+` 上均为 `((N:ℚ)-1)/((N:ℚ)+1)`；注记甲允许 `N = 0` 得出 `-1` |
| `ZeroAxisBoundData` | `SEPARATED` | 双方均用精确有理 `11/13, 25/27, A` 且仅界定 `DIF`；但甲 `delta` 为独立上界参数并支持显式播种，乙将 `price` 绑入结构、自动计算精确最大距且写死首值播种（`W2`） |

### 1.2 M16a `Chan/Proxy/Macd.lean`（11 项：8 `EQUIV` / 3 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `MacdParams` | `SEPARATED` | 甲含 `seed, sigSeed : EmaSeed` 支持热启动（但快慢线共用同一 `seed`）；乙仅含三个 `ℕ+` 周期，写死首值播种（`W3`） |
| `MacdPoint` | `EQUIV` | 均为三有理字段 `dif, dea, hist` 且 `hist = 2*(dif - dea)`，类型同构；纠错甲文件头注释将核常数 `56` 错标为无系数版本 |
| `macdSeq` | `SEPARATED` | 首值播种下逐位等价；显式热启动播种时甲可算，乙无参数口（`W3`） |
| `signedSum` | `EQUIV` | 均为 `Finset.range (e + 1 - s)` 上求和，反向窗 `e < s` 均归零，逐位等价 |
| `posSum` | `EQUIV` | 均为闭窗口上 `max (h t) 0` 之和，逐位等价 |
| `negSum` | `EQUIV` | 均为闭窗口上 `max (-h t) 0` 之和（非负），逐位等价 |
| `absSum` | `EQUIV` | 均为闭窗口上 `|h t|` 之和，逐位等价 |
| `posVar` | `EQUIV` | 均为 `Finset.range (e - s)` 上相邻正增量之和，逐位等价 |
| `negVar` | `EQUIV` | 乙为 `posVar (-x)`，内项 `max (-x(k+1) - (-x k)) 0 = max (x k - x(k+1)) 0`，逐位等价 |
| `totalVar` | `EQUIV` | 甲求和 `|Δx|`，乙为 `posVar + negVar`，由 `|u| = max u 0 + max (-u) 0` 逐位等价 |
| `endpointDiff` | `SEPARATED` | 反向窗口 `e < s` 时甲返回 `h e - h s`（破坏 `posVar - negVar = endpointDiff`），乙返回 `0`（`W4`） |

### 1.3 M16a `Chan/Proxy/MaArea.lean`（4 项：3 `EQUIV` / 0 `SEPARATED` / 1 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `maSignedArea` | `EQUIV` | 闭窗口 `[s, e]` 上 `∑ (maS - maL)`，逐位等价 |
| `maPosArea` | `EQUIV` | 闭窗口 `[s, e]` 上 `∑ max (maS - maL) 0`，逐位等价 |
| `maNegArea` | `EQUIV` | 闭窗口 `[s, e]` 上 `∑ max (maL - maS) 0`，逐位等价 |
| `maAvgForce` | `UNDECIDED` | 均正确引 `[015:42]`；甲取带号面积除以时长（保核恒等式，但空头为负且缺 `s ≤ e` 除零守卫），乙取无向绝对面积除以时长并强制 `s ≤ e`（`W5`, 裁定轴 `U-1`） |

### 1.4 M16b `Chan/Defs/Dynamics/StructImpulse.lean`（5 项：0 `EQUIV` / 5 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `segSlope` | `SEPARATED` | 甲用区间极值 `zigEnd - zigStart` 且允许零时长除零归零；乙用真实出入价 `DirectedEndpoints` 且强制 `first < last`（`W6`） |
| `impulseIn` | `SEPARATED` | 甲缺失比较方向 `side : Dir` 定向且不要求非空与相邻交替链；乙带 `side` 定向与 `ImpulseWindow` 连续性不变式（`W6`, `W7`） |
| `impulsePre` | `SEPARATED` | 甲缺方向定向与前驱真实相邻证明；乙强制 `prev.followedBy w.first` 并带 `side` 定向（`W6`, `W7`） |
| `impulseZero` | `SEPARATED` | 甲缺方向定向导致空头正变差退化，但保留了显式基准速度 `v0`；乙正确定向但硬编码参考速度 `0`（`W6`, `W7`, `W8`） |
| `impulseFromRest` | `SEPARATED` | 均不设默认实例；甲因无定向致下跌单腿正变差恒为 `0` 且末速度符号颠倒（`W7`）；另与外部候选首次突破速度 `L_break` 构成三方相反排序见证（`W9`, FM-42 裁定轴 `U-8`） |

### 1.5 M16c `Chan/Defs/Dynamics/Potential.lean`（4 项：3 `EQUIV` / 1 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `ForceWindow` | `SEPARATED` | 甲 `anchor` 存中枢时间跨度 `Option Span` 且无 `ordered` 字段；乙 `anchor` 存中枢核心价格区间 `Option (Bar ℚ)` 且内建 `ordered` 不变式（`W10`） |
| `CausalPotential` | `EQUIV` | 均不强加价格平移不变性；在 `R = ℚ` 上，甲的 `(ℕ → ℚ) → ℕ → ℚ` 加 `causal` 证明与乙的结构化前缀 `List ℚ → ℚ → ℚ` 存在精确双射同构 |
| `PosHomogeneous` | `EQUIV` | 在上述双射下，整条序列正数倍缩放与前缀正数倍缩放逻辑完全等价 |
| `MirrorAntiSym` | `EQUIV` | 在上述双射下，整条序列取负与前缀取负逻辑完全等价 |

### 1.6 M16c `Chan/Defs/Dynamics/ForceSpec.lean`（8 项：3 `EQUIV` / 5 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `ReadingKind` | `EQUIV` | `endpointDiff` 与 `posVar` 二构造子无默认枚举，完全同构 |
| `EndpointConv` | `EQUIV` | `interiorOnly`、`leftClosed`/`withPredecessor`、`fromRest` 三槽位无默认枚举，语义槽位同构 |
| `ForceSpec` | `SEPARATED` | 四参数均无默认值；因内嵌 `ForceWindow` 结构差异而继承分离（`W10`） |
| `evalForce` | `SEPARATED` | 三重分离：空头定向在势函数前（甲）与后（乙）对非奇对称势不对易；`first = 0` 前驱约定时甲以 `0 - 1 = 0` 伪造前驱而乙返回 `none`；越界历史甲补零而乙返回 `none`（`W11`） |
| `ReadingShiftInvariant` | `SEPARATED` | 均正确挂在读数层；甲对配方全窗口量化，乙仅对单个固定 `spec.window` 量化（`W12`） |
| `PositiveAffineEquiv` | `SEPARATED` | 甲对配方全窗口量化，乙对单窗口量化并要求 `Option` 定义域不变（`W12`, `W11`） |
| `ForceCompareMode` | `EQUIV` | 严格小于与不大于两档开关完全同构，均标 `[二级旁证 051:246]` |
| `forceWeaker` | `SEPARATED` | 继承 `evalForce` 在 `first = 0` 前驱缺失、越界及非奇对称势空头定向上的分离（`W11`） |

### 1.7 M17 `Chan/Defs/Dynamics/Divergence.lean`（11 项：2 `EQUIV` / 6 `SEPARATED` / 3 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `MakesNewExtreme` | `EQUIV` | 均独立于力度比较且用严格不等号（顶高严格升、底低严格降）；在满足 `DivFrame.observed` 的一致分解下，甲读 `Seg.range` 与乙从 `List ℚ` 按 `Span` 取极值逻辑等价 |
| `DivOnline` | `SEPARATED` | 均只读当前前缀；但甲不要求末枢、出核与当下推进且与 `TrendDiv/ConsolDiv` 脱节，乙精确定义为 `TrendDiv \|\| ConsolDiv`（`W13`, `W14`） |
| `DivConfirmed` | `UNDECIDED` | 均以在线背驰和后缀不刷新极值为前提；但回拉核的判定上，甲用半平面穿越 `p ≤ ZG`（允许一步跳穿核），乙用离散点落入闭核 `p ∈ [ZD, ZG]`（`W15`, 裁定轴 `U-3`） |
| `TrendDiv` | `SEPARATED` | 甲抽取任意单段 `i` 且只要求存在某一前分离中枢，面向已完成段；乙合并两枢间全部连接段为整体 `b`、要求全链逐对分离，面向进行中 `c`（`W14`） |
| `ConsolDiv` | `UNDECIDED` | 甲只允许 `i < z.start`（标准 `a+A+c` 进入段与离开段比较），乙只允许 `z.start ≤ i`（围绕单中枢同侧相邻两次离开），二者完全互斥（`W13`, 裁定轴 `U-2`） |
| `TrendEndCase` | `EQUIV` | 独立 `c` 趋势背驰、末枢内部盘背反转、直接反向三类点三分支枚举完全同构 |
| `trendEndClassify` | `SEPARATED` | 甲因后两分支硬编码 `¬ForwardExit`，在“无背驰顺向离开后直接反向三卖”路径上三分支全假不穷尽；乙经 `confirmedCase?` 正确落入 `.reverseThird`（`W16`） |
| `DivSegment` | `SEPARATED` | 甲为含 `TrendDiv ∨ ConsolDiv` 证据的结构体（绑定已完成段），乙为指向进行中后段的布尔谓词；继承 `W13`, `W14` |
| `NestedDivChain` | `UNDECIDED` | 均不强加中间级同级背驰（合规 B-20）；各自有缺（甲下层未绑真实分解、乙顶层未要求 `DivSegment`）；且跳级与等跨度（甲）对比相邻逐级与真包含（乙）属原典留白（`W17`, 裁定轴 `U-4`） |
| `SmallDivTriggersBigTurn` | `SEPARATED` | 甲遗漏 `044:24/26` 最后次级中枢反向三类点必要条件且未检验切点前原趋势；乙完整校验次级三类点与原趋势转折（`W18a`） |
| `TurnWithoutSameLevelDiv` | `SEPARATED` | 甲要求本级反向三类点并全局否定全部历史背驰；乙检查次级三类点或反向离开并限定在本走势 `since` 范围内（`W18b`） |

### 1.8 M18 `Chan/Defs/Limits/Liveness.lean`（8 项：3 `EQUIV` / 4 `SEPARATED` / 1 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `InfPath` | `EQUIV` | 均为 `ℕ → A` 的透明缩写，定义相等 |
| `prefixOf` | `EQUIV` | 均为 `List.ofFn (fun i : Fin n => x i.val)`，定义相等 |
| `PrefixObservable` | `SEPARATED` | 甲定义为 Baire 空间闭开集（clopen），误杀“最终出现价位 1”等核心可观测事件；乙正确定义为开集（柱集并）（`W19`） |
| `EventuallyStable` | `EQUIV` | 均为 `Filter.EventuallyConst (fun n => f (prefixOf x n)) Filter.atTop`，定义相等 |
| `DecompExistsSpec` | `SEPARATED` | 甲无 `InterfaceLaws` 前提且把局部规范性混入存在性；乙以 `InterfaceLaws` 为前件且仅要求合法塔存在（`W20`） |
| `CanonicalUniqueSpec` | `SEPARATED` | 甲仅陈述至多唯一性（无解时空真）且写死局部规范；乙陈述存在且唯一并显式参数化 `canonical` 规范谓词（`W21`） |
| `BoundedTerminationSpec` | `SEPARATED` | 甲允许 `m = n` 零步终结且缺对象标识与跨级升级析取；乙强制 `n < m`、带对象标识 `id` 并显式区分完成与更高层升级（`W22`） |
| `WeakSafetySpec` | `UNDECIDED` | 甲要求不低于买入价的卖点落在同级中枢形成时刻 `m` 之内（`t < s ≤ m`）；乙仅要求买点后未来任意时刻存在（`buy < exitTime`）（`W23`, 裁定轴 `U-5`） |

### 1.9 M19a `Chan/Hypotheses/Dynamics.lean`（11 项：2 `EQUIV` / 7 `SEPARATED` / 2 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `LivenessHyp` | `UNDECIDED` | 甲为统一步数上界 `B` 的裸价格双向严格波动（对接有界终结但未保成段）；乙为无步数上界的指定级别双向成段活性（保成段但推不出统一 `bound`）（`W24`, 裁定轴 `U-6`） |
| `InertiaHyp` | `EQUIV` | 在 `ℚ` 上二阶差分绝对值受 `cap` 约束逻辑完全等价（`0 ≤ |secondDiff x 0| ≤ cap` 自动蕴含 `0 ≤ cap`） |
| `ExhaustionHyp` | `SEPARATED` | 甲约束原始价格顺向正变差预算（位移量纲）；乙约束残余外推力顺向正部预算（冲量量纲，直接对齐模型 A）（`W25`） |
| `PullbackHyp` | `UNDECIDED` | 均不引用结论谓词（合规门禁 14）；甲用线性胡克回复 `-κ·dist + ε`（近界趋零），乙用区间外一致常数正下界 `strength > 0`（对齐模型 A）（`W26`, 裁定轴 `U-7`） |
| `SymUnimodalBarGroupHyp` | `SEPARATED` | 双方均真修复 `[1, 2, 1]`（半计峰值得 `2 × 2 = 4`）；但甲限定奇数长 `2p+1` 排斥偶数平顶 `[1, 2, 2, 1]`，乙兼顾奇偶长度（`W27`） |
| `DynamicsHypBundle` | `SEPARATED` | 均零默认值；甲为含参 `Type*` 结构并另设独立展平条件命题 `DivReturnsToCenterStmt`；乙为 `Prop` 结构耦合残余推力但将无关的 `bars` 绑入回拉命题前件（继承 `W24` 至 `W27`） |
| `MarketParticipant` | `EQUIV` | 均为单字段 `id : ℕ` 结构体，完全同构 |
| `OrderEvent` | `SEPARATED` | 甲含 `time, qty` 五字段；乙不含 `time, qty` 三字段，时间改由外层成交带索引（`W28`） |
| `TaggedMarket` | `SEPARATED` | 甲用有限事件表加独立自由外生价格轨；乙用无限时间成交带、登记参与者集与递归派生成交价（`W28`） |
| `EfficientPriceMarket` | `SEPARATED` | 甲在同刻异价两笔成交上直接矛盾、在空事件表任意跳价上空真；乙相对于外参估值函数将成交带前缀映射到成交价（`W28a`） |
| `NonIdenticalTrading` | `SEPARATED` | 甲在双人完全同步两日同向交易上误判为真；乙以全称排斥同刻同向对手精确刻画非完全绝对趋同（`W28b`） |

### 1.10 M19b `ChanDyn/Well.lean`（6 项：3 `EQUIV` / 3 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `WellModel` | `SEPARATED` | 甲外置二阶差分递推 `Evolves` 漏约束 `x 1` 与 `f 0`、不含 `inward`；乙内置半隐式欧拉 `kick/drift` 与 `inward` 字段；双方均缺阻尼因子 `ρ`（`W29`） |
| `WellSymmetric` | `SEPARATED` | 甲要求包含中枢内部的全域奇对称（强迫中点回复力为 `0`）；乙仅要求中枢上下界外等距处反号，更贴合 `033:26`（`W30`） |
| `WellTimeInvariant` | `EQUIV` | `∀ t s y, restore t y = restore s y` 与 `∀ t x, restoring t x = restoring 0 x` 逻辑等价 |
| `WellBoundedRange` | `EQUIV` | 均为 `0 ≤ r` 且区间外超出 `r` 处回复力为零，逐字等价 |
| `CoastingZeroThrust` | `EQUIV` | 均为左闭右开步区间内每步外力为零（`[a, b)` 与 `[start, start+steps)` 一一对应），逻辑等价 |
| `FallsFromRest` | `SEPARATED` | 甲仅约束起点静止且在带外（恒停带外也判真）；乙约束经 `steps > 0` 步在带外运动后首次落入中枢（`W31`） |

### 1.11 M19b `ChanDyn/Thrust.lean`（3 项：0 `EQUIV` / 3 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `ThrustModel` | `SEPARATED` | 甲继承时变 `WellModel` 且内嵌 `critical`；乙用定常回复力、半隐式欧拉与外置 `critical`；双方均缺模型 A 所需阻尼因子 `ρ`（继承 `W29`） |
| `BudgetBound` | `SEPARATED` | 甲强绑 `budget c ≤ budget b ≤ critical`，在滑行 `b` 段（零外力）下迫使 `c` 预算归零而无法接入模型 A；乙采用独立 `budget ≤ critical`（`W32`） |
| `BoundedReturn` | `SEPARATED` | 甲允许起点就在中枢内且 `t = t0` 在 `H = 0` 时平庸成立；乙要求起点严格在带外且在 `1..deadline` 步内落入中枢（`W33`） |

### 1.12 M19b `ChanDyn/Field.lean`（3 项：2 `EQUIV` / 1 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `MultiCenterField` | `SEPARATED` | 甲用变长 `List` 载入时变 `WellModel` 且无 `inward` 限制；乙用 `Fin n` 载入定常回复场并内置 `inward`（关联 `W29`） |
| `residualThrust` | `EQUIV` | 在定常同源场上均为 `x(t+2) - 2 x(t+1) + x t - ∑ restore_i(x(t+1))`，逐位等价 |
| `NearestCenterDominates` | `EQUIV` | 到闭区间距离公式与总场偏差上界在定常同源场（取 `y = x(t+1)`）下逻辑等价 |

### 1.13 M19b `ChanDyn/Agents.lean`（2 项：0 `EQUIV` / 2 `SEPARATED` / 0 `UNDECIDED`）

| 公开定义 | 分类 | 简要理由与见证索引 |
|---|---|---|
| `AsyncAgentSystem` | `SEPARATED` | 甲仅单维标量与即时价格反馈，结构性无法实例化模型 B（`k_0 = 1, k_1 = 1/2`）；乙具多维向量与因果延迟时钟 `seen t i ≤ t`，可精确实例化模型 B（`W34`） |
| `AsymptoticStable` | `SEPARATED` | 甲仅要求单轨标量价格收敛，容许个体状态发散与 Lyapunov 失稳；乙为标准域内平衡态不变性加 Lyapunov 稳定加全状态吸引（`W35`） |

---

## 2. 八大高风险分歧面深度剖析与有限反例见证（`W1` 至 `W35`）

以下所有有限反例见证均在精确有理数 `ℚ` 上逐项验算，无浮点近似，可直接移入 `Chan/Audit/Separation/Fm10eSeparation.lean` 以 `decide` 或有理算术证成。

### 面一：M16a 精确核代理层（`Proxy/{Ema,Macd,MaArea}.lean`）

#### 1.1 核参数、播种偏移与零轴回拉界核验
- **精确常数**：双方均正确给出 `q_12 = 11/13`、`q_26 = 25/27`、`A = (25/27)^9 - (11/13)^9`，无四位小数截断近似，且均明确声明该界仅适用于 `DIF`，`DEA` 须经信号均线二次卷积核另行表述，完全落实 `#2322` 评论 1 订正一。
- **核常数 `56` 注释纠错**：对 `(12, 26, 9)`，因 `DIF` 速度核质量为 `(26 - 12)/2 = 7`，`DEA_t = (1/5) DIF_t + (4/5) DEA_{t-1}` 推出 `DIF_t - DEA_t = 4 (DEA_t - DEA_{t-1}) = 28 Δṽ_t`，故带 2 倍因子的 `hist = 2 (dif - dea) = 56 Δṽ_t`。乙方 `Macd.lean:27` 准确记为倍柱核常数 `56`；甲方 `Macd.lean:10` 错记为“按无系数版本计”（实为 `28`），融合时须订正。
- **零周期与除零守卫**：甲 `smaSeq`、`emaDecay` 接受 `N : ℕ`，在 `N = 0` 时分别产生 `0 / 0 = 0` 与 `(0 - 1)/(0 + 1) = -1` 垃圾值；乙统一以 `ℕ+` 在类型层封死零周期。

#### 1.2 有限反例见证 `W1` 至 `W5`
- **W1（`EmaParams` / `emaSeq` 显式播种时刻 0 偏移与参数域分离）**：
  - 参数与输入：周期 `N = 3`（`α = 2/(3+1) = 1/2`，`q_3 = 1/2`），价格序列 `x = [10, 14, ...]`，显式播种 `v = 0`（甲 `EmaSeed.given 0`，乙 `some 0`）。
  - 甲读数：`emaSeq p x 0 = (1/2) * 10 + (1/2) * 0 = 5`；`emaSeq p x 1 = (1/2) * 14 + (1/2) * 5 = 19/2`。
  - 乙读数：`emaSeq p x 0 = 0`；`emaSeq p x 1 = (1/2) * 14 + (1/2) * 0 = 7`。
  - 参数域补充：`α = 3/4 ∈ (0, 1]` 在乙中合法，但在甲中无正整数 `N` 使 `2/(N+1) = 3/4`。
- **W2（`ZeroAxisBoundData` 显式初值热启动与自由 `delta` 分离）**：
  - 输入：价格序列恒为 `x t = 101`，窗口 `n = 9`，当下时刻 `t = 8`（`oldCount = 0`），价带 `[101, 101]`（`lo = 101, R = 0`），显式初值 `pre = 100`（距价带距离 `1`）。
  - 甲读数（取 `EmaSeed.given 100`, `delta = 1`）：`ema_12 8 = 101 - (11/13)^9`，`ema_26 8 = 101 - (25/27)^9`，`DIF 8 = (25/27)^9 - (11/13)^9 = A > 0`，精确触及 `bound = A * 0 + (q_26^9 - q_12^9) * 1 = A`。
  - 乙读数：因写死首值播种 `seed = none` 且 `oldCount = 0`，强制算得 `delta = 0` 与 `DIF 8 = 0`，无法表达显式初值漂移场景；另在 `x 0 = 100, x 1..9 = 101` 首值播种上甲乙精确值一致为 `A`，但甲允许宽松上界 `delta = 2`（`bound = 2A`），乙固定紧界 `delta = 1`（`A`）。
- **W3（`MacdParams` / `macdSeq` 非首值热启动分离）**：
  - 输入：`(fast, slow, sig) = (1, 3, 3)`，`x = [10, 14, ...]`。首值播种下甲乙均得 `t=0: (0,0,0)`、`t=1: dif=2, dea=1, hist=2`。
  - 热启动 `seed = given 0, sigSeed = given 0` 时，甲于 `t = 0` 算得 `fast = 10, slow = 5, dif = 5, dea = 5/2, hist = 5`；乙无播种字段，只能输出 `(0, 0, 0)`。
- **W4（`endpointDiff` 反向窗口 `e < s` 分离）**：
  - 输入：`x = [1, 5, ...]`，反向窗口 `s = 1, e = 0`。
  - 甲读数：`endpointDiff x 1 0 = 1 - 5 = -4`（此时 `posVar x 1 0 - negVar x 1 0 = 0 ≠ -4`，破坏变差恒等式）。
  - 乙读数：`endpointDiff x 1 0 = 0`（对全体 `s, e : ℕ` 保持 `posVar - negVar = endpointDiff`）。
- **W5（`maAvgForce` 空头符号与跨吻抵消分离，对应裁定轴 `U-1`）**：
  - **W5a（纯空头窗）**：`[0, 1]`，`maS = [8, 6]`，`maL = [10, 10]`（差值 `[-2, -4]`）。甲得 `(-6)/2 = -3`；乙得 `6/2 = +3`。
  - **W5b（跨吻窗）**：`[0, 1]`，`maS = [12, 8]`，`maL = [10, 10]`（差值 `[+2, -2]`）。甲得 `0/2 = 0`（保带号端点差恒等式）；乙得 `4/2 = +2`。
  - **除零边界**：`s = 2, e = 0` 时甲允许调用并产出 `0/0 = 0`，乙由 `s ≤ e` 在类型层拒绝。

---

### 面二：M16b 结构冲量（`StructImpulse.lean`）与评论 1 外部候选三方对照

#### 2.1 甲乙内部有限分离见证 `W6` 至 `W8`
- **W6（`segSlope` 区间极值 vs 真实出入价与零时长分离）**：
  - 输入：向上段 `s : Seg ℚ`，`dir = .up`，`range = [0, 10]`，`source = [0, 4]`（例如内部折线 `2 → 0 → 10 → 6`），合法真实端点 `p : DirectedEndpoints s` 为 `entry = 2, exit = 6`。
  - 甲读数：`segSlope s = (10 - 0) / 4 = 5/2`（误用 `zigEnd - zigStart`，违背 `070:48` 与上游 `DirectedEndpoints` 契约）。
  - 乙读数：`segSlope s p _ = (6 - 2) / 4 = 1`。
  - 零时长边界：当 `source = [2, 2]` 时甲返回 `0`（门禁 10 除零垃圾值风险），乙由 `first < last` 拒绝。
- **W7（`impulseIn` / `impulsePre` / `impulseZero` / `impulseFromRest` 空头定向缺失分离）**：
  - 输入：两条单腿下跌段（出入价等于端点，时长均为 `1`）：前段 `b` 为 `10 → 4`（跨度 `[0, 1]`，`segSlope = -6`）；后段 `c` 为 `4 → 2`（跨度 `[2, 3]`，`segSlope = -2`，明显弱于 `b`）。
  - 甲读数：
    - `impulseFromRest .posVar [b] = listPosVar [0, -6] = 0`，`impulseFromRest .posVar [c] = listPosVar [0, -2] = 0`（任意下跌单腿全部塌缩为 `0`，完全失去分辨力）；
    - `impulseFromRest .terminalVelocity [b] = -6`，`[c] = -2`（`-6 < -2`，按常规 `<` 判定会把更强的前段 `b` 误判为更弱）。
  - 乙读数（`side = .down`）：`b.speedAlong .down = 6`，`c.speedAlong .down = 2`；`impulseFromRest .down [b] = ⟨6, 6⟩`，`impulseFromRest .down [c] = ⟨2, 2⟩`，两读数均准确给出 `2 < 6`。
- **W8（`impulseZero` 中枢基准参考速度 `v0` 分离）**：
  - 输入：向上单腿 `w = 0 → 5`（时长 `1`，速度 `5`），指定非零中枢基准速度 `v0 = 2`。
  - 甲读数：`impulseZero .endpointDiff 2 [w] = 5 - 2 = 3`，`impulseZero .posVar 2 [w] = 3`。
  - 乙读数：硬编码 `0`，仅能输出 `5`（不满足规范 `03-informal-specs.md:25`“置零或取中枢尺度基准速度”）。

#### 2.2 评论 1 外部候选（首次突破速度 `L_break`）三方对照见证 `W9`（服务 FM-42 默认值裁定轴 `U-8`）
将甲乙 M16b 结构冲量族、整段均速 `L_avg = (p_m - p_0)/(t_m - t_0)` 与 `astra_repair_design_audit.md` 的首次突破新价位速度 `L_break = (∑ u_i (r_i - r_{i-1})) / (r_m - r_0)` 在两组有限路径上做精确有理对照（均为向上离开上边界 `ZG = 0`，`side = .up`，无甲乙内部 `W6`/`W7` 干扰）：

- **W9a（同总时长 3、创新高路径上的完全反向排序）**：
  - 路径 `b`：`(0,0) → (1,5) → (2,4) → (3,6)`（三腿速度 `[5, -1, 2]`）
  - 路径 `c`：`(0,0) → (1,4) → (2,3) → (3,7)`（三腿速度 `[4, -1, 4]`，`c` 严格创新高 `7 > 6`）

| 候选力度读数 | 路径 `b` 读数 | 路径 `c` 读数 | 比较结论（`c` 是否弱于 `b`） |
|---|---:|---:|---|
| 整段均速 `L_avg` | `6/3 = 2` | `7/3` | 否（`7/3 > 2`） |
| M16b `impulseIn .endpointDiff` | `2 - 5 = -3` | `4 - 4 = 0` | 否（`0 > -3`） |
| M16b `impulseIn .posVar` | `0 + 3 = 3` | `0 + 5 = 5` | 否（`5 > 3`） |
| M16b `impulsePre`（前驱 `-2`）`.endpointDiff` / `.posVar` | `4` / `10` | `6` / `11` | 否（`6 > 4`, `11 > 10`） |
| M16b `impulseZero 0` / `impulseFromRest`（末态速度） | `2` | `4` | 否（`4 > 2`） |
| M16b `impulseZero 0` / `impulseFromRest`（正变差） | `5 + 0 + 3 = 8` | `4 + 0 + 5 = 9` | 否（`9 > 8`） |
| **外部候选：首次突破速度 `L_break`** | `(5×5 + 2×1)/6 = 9/2` | `(4×4 + 4×3)/7 = 4` | **是（`4 < 9/2`，严格减弱）** |

- **W9b（漫长盘旋时间耗散路径上的三方彻底分裂）**：
  - 路径 `b'`：`(0,0) → (1,4)`（单腿速度 `[4]`，总时长 `1`）
  - 路径 `c'`：`(0,0) → (1,4) → (9,3) → (10,8)`（三腿速度 `[4, -1/8, 5]`，中间耗时 8 根慢回踩不破新高，末腿急拉破高 `8 > 4`）

| 候选力度读数 | 路径 `b'` 读数 | 路径 `c'` 读数 | 比较结论（`c'` 是否弱于 `b'`） |
|---|---:|---:|---|
| 整段均速 `L_avg` | `4/1 = 4` | `8/10 = 4/5` | **是（大幅减弱 `4/5 < 4`）** |
| 外部候选 `L_break` | `16/4 = 4` | `(4×4 + 5×4)/8 = 9/2` | 否（忽略 8 根盘旋反判更强 `9/2 > 4`） |
| M16b `impulseFromRest`（末态速度） | `4` | `5` | 否（`5 > 4`） |
| M16b `impulseFromRest`（正变差） | `4` | `4 + 0 + (5 - (-1/8)) = 73/8` | 否（回踩再起脉冲导致读数翻倍 `73/8 > 4`） |

`W9a` 与 `W9b` 证成三类物理公设互不相容：冲量正变差累加每次提速脉冲、均速惩罚一切时长耗散、首次突破速度只量打开新价域的穿越速度。此双见证直接服务 FM-42 默认力度裁定（`U-8`）。

---

### 面三：M16c 力度接口（`Potential.lean` 与 `ForceSpec.lean`）

#### 3.1 四参数无默认值与平移不变性落点核验
- 甲乙双方四参数（窗口、势函数、读法、端点约定）全部无默认值；双方均未在 `CausalPotential` 上强加价格平移不变性，均准确将其挂在读数层 `ReadingShiftInvariant`，完整落实 `#2322` 评论 1 订正三。
- 双方均将 `ForceCompareMode` 显式二分为严格小于与不大于，并正确标注 `[二级旁证 051:246]`。

#### 3.2 有限反例见证 `W10` 至 `W12`
- **W10（`ForceWindow` / `ForceSpec` 锚定类型与时序不变式分离）**：
  - 输入：中枢 `z` 核价格区间 `[10, 12]`、覆盖跨度 `[2, 5]`，前段 `[0, 2]`，后段 `[5, 7]`。
  - 甲 `anchor = some [2, 5] : Option Span`（缺失核价格区间 `[10, 12]`），且接受逆序窗口 `before = [5, 7], after = [0, 2]`。
  - 乙 `anchor = some [10, 12] : Option (Bar ℚ)`（缺失中枢时间跨度 `[2, 5]`），且以 `ordered : earlier.last ≤ later.first` 拒绝逆序窗口。
- **W11（`evalForce` / `forceWeaker` 空头定向次序与 `first = 0` 前驱截断分离）**：
  - **W11a（空头定向在势前 vs 势后不对易，暴露甲伪镜像对称陷阱）**：
    - 输入：因果势 `Φ(x, t) = max (x t) 0`（满足因果性、不满足 `MirrorAntiSym`），读法 `endpointDiff`，端点约定 `interiorOnly`，窗口 `[0, 1]`，下跌历史 `h = [10, 6]`，方向 `side = .down`。
    - 甲先将历史取负 `orient .down h = [-10, -6]` 再入 `Φ` 得 `[0, 0]`，端点差为 `0`。
    - 乙先求势 `Φ(h) = [10, 6]` 再定向 `orientValue .down` 得 `[-10, -6]`，端点差为 `(-6) - (-10) = +4`。
    - 深层后果：甲的 `orient d.flip (-x) = orient d x` 使“价格镜像加方向翻转读数不变”对任何完全不对称的势函数都恒成立（空真），失去区分真假镜像对称的能力；乙的 `ReadingMirrorSymmetric` 是非平凡可检命题。
  - **W11b（`first = 0` 截断减法伪造前驱与越界处理）**：
    - 输入：历史 `h = [0, 10, 10, 15]`，势 `Φ(x, t) = x t`，`endpointDiff`，`leftClosed`/`withPredecessor`，窗口 `before = [0, 1]`、`after = [2, 3]`，方向 `side = .up`。
    - 甲将 `0 - 1` 截断为 `0`，构造前段采样 `[0, 0, 10]` 得 `10`、后段采样 `[10, 10, 15]` 得 `5`，故 `forceWeaker = True`。
    - 乙在 `before.first = 0` 时返回 `evalForce ... .earlier = none`，故 `forceWeaker = false`。
- **W12（`ReadingShiftInvariant` / `PositiveAffineEquiv` 全窗口量化 vs 单窗口量化分离）**：
  - 输入：时间依赖因果势 `Φ(x, t) = if t ≥ 2 then x t else 0`，读法 `endpointDiff`，端点约定 `fromRest`。
  - 对固定窗口 `w = ([0, 1], [0, 1])`：乙 `ReadingShiftInvariant {window := w, ...}` 为 `True`（窗内势恒为 `0`）；甲 `ReadingShiftInvariant rc` 对所有窗口全称量化，取 `w' = ([2, 3], [2, 3])` 时 `evalForce(x + 1) = x 3 + 1 ≠ x 3`，故甲判 `False`。

---

### 面四：M17 背驰与区间套（`Divergence.lean`）

#### 4.1 红线核验
- `MakesNewExtreme` 独立于力度且使用严格不等号（合规分叉 4 与 `061:28`）。
- `DivOnline` 与 `DivConfirmed` 严格分立（合规 B-16 与 `079:52`）。
- `TrendDiv` 与 `ConsolDiv` 分立（合规 B-15）。
- `NestedDivChain` 均不强加中间级同级背驰（合规 B-20 与 `056:66`）。
- `SmallDivTriggersBigTurn` 与 `TurnWithoutSameLevelDiv` 清晰分立（合规 B-21）。

#### 4.2 有限反例见证 `W13` 至 `W18`
- **W13（`ConsolDiv` / `DivOnline` 互斥域分离，对应裁定轴 `U-2`）**：
  - **W13a（标准 `a+A+c` 盘整路径）**：历史 `h = [0, 10, 6, 9, 7, 11]`（单位时长 5 段：段 0 为 `0→10` 向上进入段 `a`；段 1 至 3 为 `10→6→9→7` 成中枢 `z`，`z.start = 1, z.stop = 4`，核 `[7, 9]`；段 4 为 `7→11` 向上离开段 `c`）。取价格势、`endpointDiff`、`interiorOnly`、`.up`、严格比较：前段 `a` 力度 `10`，后段 `c` 力度 `4 < 10`，新高 `11 > 10`。
    - 甲（要求 `i < z.start`）：选 `i = 0, j = 4`，`ConsolDiv = True`，`DivOnline = True`。
    - 乙（要求 `z.start ≤ i` 且 `leaveAt` 严格出核）：段 1、3 向下，段 2 终点 `9` 不严格大于 `ZG = 9`，`consolWindows = []`，故 `ConsolDiv = false`、`DivOnline = false`。
  - **W13b（无进入段、围绕单中枢同侧两次出核离开）**：历史 `h = [16, 20, 14, 24, 16, 25]`（中枢 `z` 起于 `0` 覆盖段 0 至 2，核 `[16, 20]`；段 2 为 `14→24` 出核位移 `10`；段 3 为 `24→16` 反向触核；段 4 为 `16→25` 创新高 `25 > 24` 且位移 `9 < 10`）。
    - 甲：因 `z.start = 0`，不存在 `i < 0`，`ConsolDiv = False`、`DivOnline = False`。
    - 乙：段 2 满足 `0 ≤ 2` 且 `leaveAt = true`，段 3 反向触核，故 `ConsolDiv = true`、`DivOnline = true`。
- **W14（`TrendDiv` 复合连接段合并 vs 单段抽取分离）**：
  - 输入：上涨趋势含分离中枢 `prev`（核 `[0, 2]`, `hull = [0, 2]`, `stop = 3`）与 `z`（核 `[10, 12]`, `hull = [10, 12]`, `start = 6, stop = 9`）；两枢间三段复合连接 `b` 为段 3（`2→8`, 位移 `6`）、段 4（`8→5`, 位移 `-3`）、段 5（`5→10`, 位移 `5`），整段 `b` 跨度 `[3, 6]` 净位移 `10 - 2 = 8`；离开段 `c` 为 `10→17`（净位移 `7`，新高 `17 > 10`）。取价格势、`endpointDiff`、`interiorOnly`、`.up`、严格比较。
  - 乙：自动合并 `b = [3, 6]` 得力度 `8`，`7 < 8` 成立，`TrendDiv = true`。
  - 甲：只能抽取单段 `i ∈ {3, 5}`，位移分别为 `6` 与 `5`，均不大于 `7`，对所有 `i` 均判 `TrendDiv = False`。
- **W15（`DivConfirmed` 一步跳穿中枢核 vs 离散点落入闭核分离，对应裁定轴 `U-3`）**：
  - 输入：前缀 `h` 在双方口径下均构成针对末枢 `z`（核 `[10, 12]`）的向上 `DivOnline`，离开段极值 `15`；延拓后缀 `tail = [8]`（一步跳空直接跌破 `ZD = 10` 至 `8`，不创新高 `8 ≤ 15`）。
  - 甲：检查 `¬BeyondLevel .up 12 8` 即 `8 ≤ 12` 成立，故 `DivConfirmed = True`。
  - 乙：检查 `touches [10, 12] 8` 即 `10 ≤ 8 ∧ 8 ≤ 12` 失败，故 `DivConfirmed = false`。
- **W16（`trendEndClassify` 无背驰顺向离开后反向三卖的穷尽性分离）**：
  - 输入：上涨趋势末枢 `z`（核 `[10, 12]`）之后出现强劲顺向离开段 `c`（`10→20`，力度大于 `b`，无 `TrendDiv`），但延拓中 `z` 紧接出现反向跌破与回试不入核的第三类卖点（`ReverseExit = True`）。
  - 甲：因 `ForwardExit = True` 且 `¬TrendDiv`，三分支 `.divergenceExit`、`.consolidationReversal`、`.reverseThird` 分别判定为 `False`、`False`、`False`（不穷尽）。
  - 乙：`confirmedCase?` 跳过前两分支，由反向三卖命中第三分支，返回 `some .reverseThird`（即 `trendEndClassify ... .reverseThird = true`）。
- **W17（`NestedDivChain` 跳级、等跨度、顶层背驰与下层真实性分离，对应裁定轴 `U-4`）**：
  - **W17a**：顶层 `top` 位于 `depth = 2`、跨度 `[4, 7]`，下层列表为 `[(0, [4, 7])]`（跳过了层 `1`、跨度相等且层 `0` 分解中并无 `[4, 7]` 对应段）。甲满足 `0 < 2` 与 `SpanWithin [4, 7] [4, 7]` 判合法；乙因违反 `k = j + 1`、`u ≠ v` 及 `observedSpan` 判 `false`。
  - **W17b**：无背驰强势上涨中，层 `1` 块跨度 `[0, 6]` 真实包含层 `0` 段跨度 `[4, 6]`。甲因顶层无法构造 `DivSegment` 而拒绝；乙未检查顶层背驰，返回 `NestedDivChain = true`。
- **W18（`SmallDivTriggersBigTurn` 与 `TurnWithoutSameLevelDiv` 必要条件与级别域分离）**：
  - **W18a（`SmallDivTriggersBigTurn`）**：大级别 `big = 1` 在 `cut = 4` 前后均为盘整完成块（无原上涨趋势），段 `3` 向上覆盖 `small`（`depth = 0`）的背驰段，但次级别 `0` 最后中枢未出现反向三卖。甲因 `classifyTrend b ≠ some .uptrend` 成立且未检次级三卖而误判 `True`；乙因 `oldTrend? = none` 且 `subBreak ... true = false` 判 `false`。
  - **W18b（`TurnWithoutSameLevelDiv`）**：大级别 `big = 1` 上涨趋势末段无本级背驰、亦无本级反向三卖，但次级别 `0` 最后中枢已出现反向三卖并伴随大级别转折。甲因要求本级 `ReverseExit` 判 `False`；乙检查次级 `subBreak ... false = true` 且本走势域内 `!divergent`，判 `true`。

---

### 面五：M18 无限历史与活性（`Limits/Liveness.lean`）

#### 5.1 有限反例见证 `W19` 至 `W23`
- **W19（`PrefixObservable` 闭开集 vs 拓扑开集分离）**：
  - 输入：价格域 `ℚ`，可观测事件 `Q x := ∃ t : ℕ, x t = 1`（“价格最终触及 1”）。
  - 乙（开集）：任取满足 `Q x` 的路径 `x`（设 `x t = 1`），取 `n = t + 1`，凡与 `x` 共享前 `t + 1` 步的 `y` 必有 `y t = 1` 即 `Q y`，故 `PrefixObservable Q = True`。
  - 甲（闭开集）：取全零路径 `x := fun _ => 0`（`¬Q x`）。对任意 `n`，构造 `y t := if t < n then 0 else 1`，共享前 `n` 步但 `Q y` 为真，故 `Q y ↔ Q x` 恒失败，`PrefixObservable Q = False`。
- **W20（`DecompExistsSpec` 合法存在 vs 局部规范存在分离）**：
  - 输入：满足 `InterfaceLaws` 但在长 4 成核段列上对块尾 `3` 和 `4` 赋同等优先级 `some 1`（`confirmed = false`）的 `BlockRule`。
  - 乙：单块 `[0, 3]` 构成 `ValidDecomp = true` 的合法塔，故 `DecompExistsSpec = True`。
  - 甲：因最高优先级块尾有 `[3, 4]` 两个并列，`DeterministicBlocks` 为 `false`，不存在 `LocalCanonicalDecomp`，故 `DecompExistsSpec = False`。
- **W21（`CanonicalUniqueSpec` 无解空真 vs 存在且唯一分离）**：
  - 输入：沿用 `W20` 中有优先级平局的规则，规范取 `IsLocalCanonical`。
  - 甲：因 `LocalCanonicalDecomp` 为空，全称量化 `∀ a b, a.sameCuts b` 空真，故 `CanonicalUniqueSpec = True`。
  - 乙：要求 `∃ a : CanonicalDecomp, ...`，无解，故 `CanonicalUniqueSpec = False`。
- **W22（`BoundedTerminationSpec` 零步边界 `n ≤ m` vs `n < m` 分离）**：
  - 输入：`bound = 0`，`live := fun _ => True`，`pending := fun _ => True`，`done := fun _ => True`（乙对应 `complete := fun _ _ => True`）。
  - 甲：取 `m = n` 满足 `n ≤ n ∧ n ≤ n + 0`，故 `BoundedTerminationSpec = True`。
  - 乙：要求 `n < m ∧ m ≤ n + 0`，矛盾，故 `BoundedTerminationSpec = False`。
- **W23（`WeakSafetySpec` 窗内 `s ≤ m` vs 无限未来 `buy < exitTime` 分离，对应裁定轴 `U-5`）**：
  - 输入：价格路径 `x = [10, 6, 8, 5, 7, 10, 10, ...]`，在 `buy = 0`（买价 `10`）买入，时刻 `1..4` 形成同级中枢 `[6, 7]`（完成于 `m = 4`，期间价格全小于 `10`），直至中枢形成后的 `t = 5` 才涨回 `10`。
  - 甲：在 `0 < s ≤ 4` 内所有价格 `< 10`，故 `WeakSafetySpec = False`。
  - 乙：取 `exitTime = 5 > 0`，`x 0 = 10 ≤ 10 = x 5`，故 `WeakSafetySpec = True`。

---

### 面六：M19a 五假设与第 30 课市场模型（`Hypotheses/Dynamics.lean`）

#### 6.1 红线核验（五假设、零公理、门禁 14 防循环、`[1, 2, 1]` 修复）
- 五项命名假设全部为 `Prop`、无默认值、零 `axiom`。
- 门禁 14 依赖闭包核查：甲的五项假设均不引用 `ReturnsToCenter`；乙的五项假设均不引用 `ConditionalPullbackSpec` 或回拉结论谓词。双方均无循环定义。
- `[1, 2, 1]` 柱组核验：双方均采用“半计峰值点”真修复（`[1, 2, 1]` 的半峰面积为 `1 + 2/2 = 2`，翻倍精确等于全组面积 `4`，不再把含峰面积 `3` 翻倍成 `6`）。

#### 6.2 有限反例见证 `W24` 至 `W28`
- **W24（`LivenessHyp` 有界振荡 vs 无界成段分离，对应裁定轴 `U-6`）**：
  - 输入：变周期振荡路径 `x`，第 `k` 轮先平走 `k` 步取 `0`，再跳至 `1`、`-1`、回 `0`。
  - 甲：对任意固定常数 `B : ℕ`，取第 `k = B + 1` 轮平走起点 `n`，此后 `B` 步恒 `0`，故 `LivenessHyp B x = False`。
  - 乙（`depth = 0` 交替折线）：任意 `since` 之后均反复出现 `0→1` 上段与 `1→-1` 下段，故 `LivenessHyp = True`。
- **W25（`ExhaustionHyp` 价格正变差预算 vs 残余外推力预算分离）**：
  - 输入：无外力自由滑行减速轨迹 `x = [10, 14, 16, 16, 14, ...]`（`side = .up`，`onset = 0`），常值回复力 `restore _ = -2`，每步二阶差分 `secondDiff x 0 = 16 - 28 + 10 = -2`、`secondDiff x 1 = -2`、`secondDiff x 2 = -2`，残余外推力恒为 `0`。取预算 `budget = 0`。
  - 乙（残余推力版）：外推力正部和恒为 `0 ≤ 0`，`ExhaustionHyp = True`。
  - 甲（价格正变差版）：正增量和为 `(14 - 10) + (16 - 14) = 6 > 0`，`ExhaustionHyp = False`。
  - 对偶样本：带外恒静路径 `x ≡ 15` 在 `restore 15 = -2` 下每步需外推力 `+2`，甲判 `budget = 0` 为 `True`，乙对任意有限 `budget` 判 `False`。
- **W26（`PullbackHyp` 线性弹性回复 vs 一致正下界回复分离，对应裁定轴 `U-7`）**：
  - 输入：中枢核 `[0, 1]`，无噪声胡克弹性回复 `restore p := if p > 1 then -(p - 1) else if p < 0 then -p else 0`，轨道满足 `secondDiff x t = restore (x (t+1))`。
  - 甲（`κ = 1, ε = 0`）：精确成立，`PullbackHyp = True`。
  - 乙：对任意 `strength > 0`，取 `p = 1 + strength / 2 > 1`，有 `restore p = -strength / 2 > -strength`，故 `PullbackHyp = False`。
  - 对偶样本：常数回复 `restore p = -2`（`p > 1`）在 `x(t+1) = 10` 时，乙（`strength = 2`）为 `True`，甲（`κ = 1, ε = 0`）因 `-9 < -2` 判 `False`。
- **W27（`SymUnimodalBarGroupHyp` 偶数长度对称平顶柱组 `[1, 2, 2, 1]` 分离）**：
  - 输入：柱组 `g = [1, 2, 2, 1]`（全组面积 `6`，左半 `[1, 2]` 面积 `3`，`2 × 3 = 6`）。
  - 甲：要求 `g.length = 2 * p + 1`，因 `4` 为偶数对一切 `p` 均判 `SymUnimodalBarGroupHyp = False`。
  - 乙：满足非空、回文、非负及左半 `[1, 2]` 单调不减，`SymUnimodalBarGroupHyp = True` 且 `halfPeakArea [1, 2, 2, 1] = 3`。
- **W28（第 30 课市场模型分离：`OrderEvent` / `TaggedMarket` / `EfficientPriceMarket` / `NonIdenticalTrading`）**：
  - **W28a（`EfficientPriceMarket` 同刻异价与零交易分离）**：
    - 情形 1：时刻 `0` 连续两笔成交 `(P0, up, 10)` 与 `(P1, up, 11)`，市场价取末笔 `11`。甲要求 `price 0 = 10 ∧ price 0 = 11` 矛盾判 `False`；乙取末笔估值函数判 `True`。
    - 情形 2：空事件表 `events = []` 配任意跳价 `price t = t`。甲全称空真判 `True`；乙因 `tape t = []` 必保 `tradePrice ≡ openingPrice`，无法生成跳价。
  - **W28b（`NonIdenticalTrading` 双人完全同步两日交易反例）**：
    - 输入：参与者 `P0, P1` 在 `t = 0` 同步买入（价 `10`），在 `t = 1` 再次同步买入（价 `11`），完全绝对趋同。
    - 甲：取 `e₁ = (P0, t=0, up)` 与 `e₂ = (P1, t=1, up)`，满足 `P0 ≠ P1 ∧ 0 ≠ 1`，误判 `NonIdenticalTrading = True`。
    - 乙：无论取 `t = 0` 或 `t = 1` 及任意 `a`，同刻另一人均存在 `other.side = a.side = up`，准确判 `NonIdenticalTrading = False`。

---

### 面七：M19b 独立研究库（`ChanDyn/`）与评论 1 两基准原型兼容性实测

#### 7.1 基准原型一：模型 A（临界推力预算 `B_* = 8/3`）兼容性实测
模型 A 方程（`ZD = -1, ZG = 0`，带外距离 `x_t = P_t`，期限 `N = 2`，参数 `ρ = 1/2, γ = 2, x_0 = 1, v_0 = 0`）：
$$v_{t+1} = \frac{1}{2} v_t - 2 + f_t, \qquad x_{t+1} = x_t + v_{t+1}$$
精确手算：
- 临界预算 `B_* = (2 × (1 + 3/2) - 1 - 0) / (3/2) = 4 / (3/2) = 8/3`；
- 输入 `f = [8/3, 0]`：`v_1 = 2/3, x_1 = 5/3`；`v_2 = 1/3 - 2 = -5/3, x_2 = 0`（精确触边）；
- 输入 `f = [3, 0]`：`v_1 = 1, x_1 = 2`；`v_2 = 1/2 - 2 = -3/2, x_2 = 1/2 > 0`（逃逸）。

**实测实例化结果（双方均存在结构失配！）**：
1. **阻尼因子 `ρ` 双方共同缺失**：甲的 `WellModel.Evolves` 与乙的 `ThrustModel.kick` 均将速度继承系数硬编码为 `1`（即 `ρ = 1`），且 `restore`/`restoring` 均不接收速度参数。在 `ρ = 1` 下，同参数 `(N=2, γ=2, x_0=1, v_0=0)` 的临界预算变为 `B_* = (2 × (1 + 2) - 1) / 2 = 5/2 ≠ 8/3`：代入 `f = [8/3, 0]` 得 `v_1 = 2/3, x_1 = 5/3`，`v_2 = 2/3 - 2 = -4/3, x_2 = 1/3 > 0`（模型 A 应触边，但甲乙无阻尼模型均逃逸）。若强行将阻尼 `-(1/2) v_1 = -1/3` 塞入外力 `thrust 1`，则因 `BudgetBound` 对 `|thrust|` 求绝对值和，会将其误计入消耗预算得 `8/3 + 1/3 = 3 > 8/3`。
2. **甲方额外两处失配**：甲的二阶差分 `x(t+2) - 2 x(t+1) + x t = restore(t+1)(x(t+1)) + f(t+1)` 完全不约束 `f 0` 与 `x 1`（丢拍 1 步），且 `BudgetBound` 强迫 `budget c ≤ budget b`，在 `b` 段滑行（零外力）下直接将 `c` 段预算封死为 `0`。乙的半隐式欧拉 `kick/drift` 与独立 `BudgetBound` 在步长下标和预算槽位上与模型 A 严丝合缝，仅缺阻尼字段 `rho : ℚ`（`0 ≤ rho ≤ 1`）。

#### 7.2 基准原型二：模型 B（渐近稳定域 `k_1 < 1, k_0 + k_1 > 0, k_0 < 2 + k_1`）兼容性实测
模型 B 方程：`x_{t+1} = (1 - k_0) x_t - k_1 x_{t-1}`，代表点：`k_0 = 1, k_1 = 1/2`（渐近稳定，`x_{t+1} = -(1/2) x_{t-1}`）；`k_0 = 1, k_1 = 1`（周期 4 振荡 `1, 1, -1, -1, ...`）；`k_0 = 5/2, k_1 = 1/2`（周期 2 振荡 `1, -1, 1, -1, ...`）。

**实测实例化结果（乙方完胜，甲方结构性阻断！）**：
1. **甲方 `AsyncAgentSystem` 不可实例化（`W34`）**：甲每组只有 1 个标量状态，且 `respond i (st i) (price st)` 仅能看到本组旧状态与标量叠加价。尝试以 2 组编码 `(x_t, x_{t-1})`：
   - 若置 `weight = (1, 0)`（使 `price = x_t`），则组 0 的 `respond 0` 拿到 `(x_t, x_t)`，无法获知 `x_{t-1}`；
   - 若置 `weight = (1 - k_0, -k_1)`（使 `price = x_{t+1}`），在稳定见证 `k_0 = 1, k_1 = 1/2` 处 `price = -(1/2) x_{t-1}` 完全丢失 `x_t`，组 1 无法更新为 `x_t`。
   - 此外甲的 `AsymptoticStable` 缺失 Lyapunov 稳定性且仅看标量价格，容许状态向量发散抵消（`W35`）。
2. **乙方 `AsyncAgentSystem` 精确实例化**：
   - **态空间编码（`groups = 1, dim = 2`，全时刻 `t ≥ 0` 一步不差）**：状态向量 `(x_t, x_{t-1})`，`seen t 0 = t`，`contribute 0 v = v`，`respond 0 _ v = ((1 - k_0) v 0 - k_1 v 1, v 0)`，唯一平衡态 `(0, 0)`，乙的 `AsymptoticStable` 精确等价于 Jury 稳定域 `k_1 < 1, k_0 + k_1 > 0, k_0 < 2 + k_1`。
   - **双组异步时钟编码（`groups = 2, dim = 1`，`t ≥ 1` 精确）**：组 0 取 `seen t 0 = t`、`respond 0 u x = u - k_0 x`，组 1 取 `seen t 1 = t - 1`（满足 `causal : t - 1 ≤ t`）、`respond 1 w x = w - k_1 x`，`contribute j v = v`，则 `x_{t+1} = u_{t+1} + w_{t+1} = (1 - k_0) x_t - k_1 x_{t-1}` 逐符号成立。同时须注意在此 2 组编码中，`u_t` 与 `w_t` 收敛到守恒流形 `u_∞ + w_∞ = 0` 而非单点 `(0, 0)`，因此需在融合版中并列保留“全状态渐近稳定（乙现有）”与“叠加价渐近稳定”两个谓词。

#### 7.3 `ChanDyn/` 其余有限分离见证 `W29` 至 `W35`
- **W29（`WellModel` / `ThrustModel` / `MultiCenterField` 首步约束与 `inward` 内置分离）**：
  - 取 `center = [0, 0]`，`restore _ y = -y`，`externalForce = [1, 0, ...]`，初态 `x_0 = 0, v_0 = 0`。乙强制 `v_1 = 1, x_1 = 1`；甲 `Evolves` 接受 `x_0 = 0, x_1 = 99`（完全无视 `f_0 = 1`）。另取排斥势 `restore _ y = +y`，甲可构造用于独立性反例测试，乙因内置 `inwardBelow/Above` 无法构造。
- **W30（`WellSymmetric` 中枢内部回复力分离）**：
  - 输入：中枢 `[0, 2]`，`restore t y := if y > 2 then -(y - 2) else if y < 0 then -y else if y = 1 then 1 else 0`。
  - 乙：对所有 `r ≥ 0`，`restore t (0 - r) = r = -restore t (2 + r)`，判 `WellSymmetric = True`。
  - 甲：在 `u = 0`（中点 `1`）处 `1 ≠ -1`，判 `WellSymmetric = False`。
- **W31（`FallsFromRest` 恒停带外反例）**：
  - 输入：中枢 `[0, 1]`，恒定轨 `x t = 5`（全程静止在带外）。
  - 甲：`x 1 = x 0 = 5 ∧ 1 < 5`，判 `FallsFromRest = True`。
  - 乙：不存在 `steps > 0` 使 `position steps ∈ [0, 1]`，判 `FallsFromRest = False`。
- **W32（`BudgetBound` 滑行 `b` 段零外力瘫痪反例）**：
  - 输入：`b` 段 `[0, 2)` 满足 `CoastingZeroThrust`（外推力 `0, 0`，`budget b = 0`）；`c` 段 `[2, 4)` 外推力 `[1, 0]`（总推力 `1 ≤ critical = 5/2`）。
  - 甲：`1 ≤ 0` 为假，判 `BudgetBound = False`。
  - 乙（`budget = 1, critical = 5/2`）：`1 ≤ 1 ≤ 5/2`，判 `BudgetBound = True`。
- **W33（`BoundedReturn` 带内起点与 `H = 0` 分离）**：
  - 输入：中枢 `[0, 1]`，起点 `t0 = 0` 处 `x 0 = 1/2`（已在带内），期限 `H = 0`。
  - 甲：取 `t = 0` 得 `BoundedReturn = True`。
  - 乙：违反起点带外且 `Fin 0` 为空，得 `BoundedReturn = False`。
- **W34（`AsyncAgentSystem` 模型 B 实例化分离）**：如 7.2 所证，模型 B 在 `k_0 = 1, k_1 = 1/2` 上乙可精确构造，甲 2 组标量结构性不可实现。
- **W35（`AsymptoticStable` 状态发散抵消与 Lyapunov 失稳分离）**：
  - **W35a**：2 组权重 `(1, 1)`，轨道 `st 0 = t, st 1 = -t`，叠加价恒为 `0`。甲判 `AsymptoticStable = True`；乙因个体状态发散判 `False`。
  - **W35b**：1 维跳变系统 `f(0)=0`、`f(x)=10`（`0 < |x| < 1`）、`f(x)=0`（`|x| ≥ 1`），初值 `1/2` 经 `10` 到 `0`。甲仅查单轨收敛判 `True`；乙因 `ε = 1` 无 `δ > 0` 满足 Lyapunov 稳定判 `False`。

---

### 面八：分层隔离、阻断门与引文规范全检

| 审计项 | 甲方（Opus，13 文件） | 乙方（Astra，13 文件） | 结论 |
|---|---|---|---|
| `module` 首行与 `@[expose] public section` | 13/13 合规 | 13/13 合规 | 双方通过 |
| `Chan/Defs/` 零导入 `Chan/Proxy/` 与 `ChanDyn/` | 5/5 零违规 | 5/5 零违规 | 双方通过 |
| `ChanDyn/` 零被反向导入 | 4/4 独立（连 `Chan.Defs` 未引） | 4/4 仅单向引 `Chan.Defs.Order.Bar` | 双方通过 |
| 禁用项（`axiom`/`sorry`/`partial`/整库 `Mathlib`/元编程/`set_option`） | 零命中 | 零命中 | 双方通过 |
| `[二级旁证]` 显式标签（`105:442`, `051:246`, `044:234`） | 全部标注正确 | 全部标注正确 | 双方通过 |
| `105:518` 娇注零泄漏与编者注零混入 | 零泄漏 | 零泄漏 | 双方通过 |
| `015:42` 均线面积出处核正 | 全部引 `[015:42]` | 全部引 `[015:42]` | 双方通过 |
| 原字逐字节一致性与 NBSP/原典错字保留 | 保留 `044:26`“必要条件提是”及 `044:234`“里里” | 保留全部 NBSP 与原字；但后 10 文件省去 `「」` 括号 | 融合时统一带 `「」` |
| 注释与引文主题精确性 | `Macd.lean:10` 核常数 `56` 错标为无系数版本；`ZeroAxisBoundData` 漏贴 `[024:24]`；`SymUnimodalBarGroupHyp` 漏贴 `[024:28]` | `Potential.lean:40` 借用了 `M16a` 引文 `[050:18]`；其余均高度贴合 | 融合时修正甲三处注释 |

---

## 3. 待 `needs-fable` 裁定轴汇总（`U-1` 至 `U-8`）

以下 8 条轴对应原典与既有裁定包确有留白的实质分歧（前 7 条直接对应矩阵中的 7 个 `UNDECIDED` 定义，第 8 条对应 FM-42 外部候选选型）：

| 轴号 | 对应模块与定义 | 分歧选项 | 见证 | 对撞官建议 |
|---|---|---|---|---|
| `U-1` | M16a `maAvgForce` | 选项 A：带号面积除以时长（保平滑价端点差恒等式）；选项 B：无向绝对面积除以时长（空头非负直比） | `W5` | 保留无向版 `maAvgForce` 并强制 `s ≤ e`，同时增设带号版 `maSignedAvgForce` |
| `U-2` | M17 `ConsolDiv` | 选项 A：仅比 `i < z.start` 进入段 `a` 与离开段 `c`；选项 B：仅比 `z.start ≤ i` 同枢两次离开；选项 C：合并覆盖两种窗 | `W13` | 强烈建议选项 C：同时收纳 `a+A+c`（`027:20`）与同枢两次出核离开（`061:26`） |
| `U-3` | M17 `DivConfirmed` | 选项 A：半平面穿越 `p ≤ ZG`（允许大步跳穿中枢）；选项 B：离散点落入闭核 `[ZD, ZG]` | `W15` | 建议将选项 A 设为 `DivCrossedCore`、选项 B 设为 `DivTouchedCore`，由 `needs-fable` 锁定 `DivConfirmed` 主口径 |
| `U-4` | M17 `NestedDivChain` | 选项 A：允许跨级跳层且非严格包含；选项 B：必须相邻逐级（`k = j+1`）且严格真包含（`u ≠ v`） | `W17` | 必须先合并修复顶层 `DivSegment` 与下层 `observedSpan`；建议允许跳层以兼容 `056:66`、跨度用 `SpanWithin` 并另设严格真包含谓词 |
| `U-5` | M18 `WeakSafetySpec` | 选项 A：卖点必在同级中枢形成时刻 `m` 之内（`t < s ≤ m`）；选项 B：买点后无限未来存在即可（`buy < exitTime`） | `W23` | 建议选项 A（更忠实 `017:60` 与 `107:22`“上下上完成前即具理论卖点”） |
| `U-6` | M19a `LivenessHyp` | 选项 A：统一步数界 `B` 裸价格双向波动；选项 B：无步数界指定级别双向成段；选项 C：统一步数界 `B` 内指定级别双向成段 | `W24` | 建议选项 C（既对接 M18 `BoundedTerminationSpec` 的 `bound`，又锚定分解器层级） |
| `U-7` | M19a `PullbackHyp` | 选项 A：线性胡克回复 `-κ·dist + ε`；选项 B：区间外一致常数正下界 `strength > 0`；选项 C：抽象回复函数加参数化下界族 | `W26` | 建议选项 B 为主线（直连模型 A 常数 `γ`），选项 A 作为独立命名变体 `LinearPullbackHyp` |
| `U-8` | M16b / FM-42 默认内蕴力度 | 选项 A：速度冲量族（`impulseFromRest`）；选项 B：外部候选首次突破速度 `L_break`；选项 C：整段均速 `L_avg` | `W9` | 融合期 M16b 仍零默认值，但建议将 `L_break` 与 `L_avg` 作为具名平行候选并入对照审计层，交 FM-42 依 `W9a/W9b` 拍板 |

---

## 4. 下游融合蓝图（`decl/fm10e-dyn`）

### 4.1 逐模块融合选型表

| 模块 | 文件 | 主干基座 | 必须吸纳的对侧精华与必改修复项 |
|---|---|---|---|
| M16a | `Chan/Proxy/Ema.lean` | **以乙为骨，合甲显式播种** | 保留乙 `alpha ∈ (0,1]`、`ℕ+` 防零周期及 `Decidable` 判定；`EmaSeed` 显式区分 `firstValue`、`atZero (v)`（乙语义）与 `priorState (pre)`（甲语义）；`ZeroAxisBoundData` 同时支持自动紧距 `delta` 与外部显式初值项 `SeedWithinDelta` |
| M16a | `Chan/Proxy/Macd.lean` | **以乙为骨，合甲播种参数** | 采纳乙的 `ℕ+`、`DecidableEq`、反向窗归零 `endpointDiff` 及正确核常数 `56` 说明；补入可分别指定 `fastSeed, slowSeed, sigSeed` 的播种参数（保留标准首值播种构造器） |
| M16a | `Chan/Proxy/MaArea.lean` | **以乙为骨** | 强制 `s ≤ e` 杜绝除零；`maAvgForce` 依 `U-1` 裁定落位，并列保留带号与无向两函数 |
| M16b | `Chan/Defs/Dynamics/StructImpulse.lean` | **以乙为骨，合甲 `v0` 与多态思路** | 采纳乙的 `DirectedEndpoints` 真实出入价、`first < last` 防除零、`ImpulseWindow` 相邻链与 `side : Dir` 定向（根治 `W6, W7`）；为 `impulseZero` 补回甲的显式基准速度参数 `v0`（根治 `W8`）；不设主线默认值 |
| M16c | `Chan/Defs/Dynamics/Potential.lean` | **以乙为骨** | 采纳乙结构化因果 `CausalPotential`（`List ℚ → ℚ → ℚ`，免证明义务）及 `ForceWindow` 的 `ordered` 不变式；`ForceWindow.anchor` 改为同时携带中枢核 `Bar ℚ` 与覆盖跨度 `Span`（或 `Option (Span × Bar ℚ)`）消除 `W10` 信息丢失 |
| M16c | `Chan/Defs/Dynamics/ForceSpec.lean` | **以乙为骨，合甲配方层量化** | 采纳乙的势后定向 `orientValue`、`Option ℚ` 越界与 `first = 0` 保护、`ReadingMirrorSymmetric`（根治 `W11`）；同时引入甲的 `ForceRecipe` 抽象，将 `ReadingShiftInvariant` 与 `PositiveAffineEquiv` 挂在配方层对所有合法窗口全称量化（根治 `W12`） |
| M17 | `Chan/Defs/Dynamics/Divergence.lean` | **以乙为骨，合甲 `a+A+c` 与顶层证书** | 采纳乙的 `DivFrame` 历史绑定、`DivOnline := TrendDiv \|\| ConsolDiv`、整段 `b` 合并、穷尽 `confirmedCase?`（根治 `W16`）与完整次级三类点小转大（根治 `W18`）；按 `U-2` 补齐 `ConsolDiv` 对 `i < z.start` 标准 `a+A+c` 的支持（根治 `W13a`）；`NestedDivChain` 补齐顶层 `DivSegment` 校验并按 `U-4` 定跳级与真包含；`DivConfirmed` 按 `U-3` 定口径 |
| M18 | `Chan/Defs/Limits/Liveness.lean` | **以乙为骨，按 `U-5` 调 `WeakSafetySpec`** | 采纳乙的开集 `PrefixObservable`（根治 `W19`）、带 `InterfaceLaws` 的 `DecompExistsSpec`/`CanonicalUniqueSpec`（根治 `W20, W21`）及带 `id`/`n < m`/跨级升级析取的 `BoundedTerminationSpec`（根治 `W22`）；`WeakSafetySpec` 推荐吸纳甲的 `exitTime ≤ t` 窗内上界（依 `U-5` 裁定） |
| M19a | `Chan/Hypotheses/Dynamics.lean` | **以乙为骨，合甲独立展平命题** | 采纳乙的残余推力 `ExhaustionHyp`（`W25`）、奇偶兼容 `SymUnimodalBarGroupHyp`（`W27`）与完整第 30 课成交带市场模型（根治 `W28`）；参考甲 `DivReturnsToCenterStmt` 将条件回拉命题前件展平（剥离无关的 `bars` 并允许逐项剥离检验）；`LivenessHyp` 与 `PullbackHyp` 按 `U-6, U-7` 落定；`OrderEvent` 可选保留 `qty : ℚ` 字段以支持 `030:26` |
| M19b | `ChanDyn/Well.lean` 与 `ChanDyn/Thrust.lean` | **以乙为骨，必补阻尼因子 `ρ` 与独立 `WellInward`** | 采纳乙的半隐式欧拉步进、`WellSymmetric` 外部对称（`W30`）、`FallsFromRest` 落入条件（`W31`）、独立 `BudgetBound`（`W32`）与 `BoundedReturn`（`W33`）；**关键升级两项**：（1）在 `WellModel`/`ThrustModel` 中新增惯性阻尼系数 `rho : ℚ`（`0 ≤ rho ∧ rho ≤ 1`），改 `kick` 为 `velocity (t+1) = rho * velocity t + restoring ... + thrust t`，立刻原生支持模型 A 临界值 `8/3`（`ρ = 1/2`）及无阻尼特例（`ρ = 1`）；（2）将 `inwardBelow/Above` 抽成独立 `WellInward` 谓词（采纳甲的独立可违反设计），再补充甲式 `ReturnUnderBudgetStmt` 展平条件命题 |
| M19b | `ChanDyn/Field.lean` | **以乙为骨，抽离 `inward` 为独立谓词** | 保留乙 `Fin n` 定常结构与完全等价的 `residualThrust`、`NearestCenterDominates`；将 `inward` 改为独立 `Prop` 谓词便于反例测试 |
| M19b | `ChanDyn/Agents.lean` | **以乙为骨，增补投影价渐近稳定** | 完整采纳乙的 `AsyncAgentSystem groups dim`（含因果延迟 `seen t i ≤ t`）与标准 Lyapunov `AsymptoticStable`（直接支持模型 B 稳定域 `k_1 < 1, k_0 + k_1 > 0, k_0 < 2 + k_1`）；额外增补 `PriceAsymptoticStable` 谓词覆盖双组 1 维延迟编码下“叠加价收敛而个体状态落入零和守恒流形”的情形 |

### 4.2 M19b 与 `#2322` 评论 1 两基准原型对接验收方案

1. **模型 A 对接验收**：在融合后的 `ChanDyn/Thrust.lean`（带 `rho` 字段）中，构造具体有理实例 `modelA (f0 : ℚ) : ThrustModel`（`center = [-1, 0], rho = 1/2, restoring x = if 0 < x then -2 else if x < -1 then 2 else 0, position 0 = 1, velocity 0 = 0, thrust = [f0, 0, 0, ...]`），由内核直接验证 `modelA (8/3)` 满足 `BudgetBound ... (8/3) (8/3)` 且 `BoundedReturn ... 0 2`（`position 2 = 0`），而 `modelA 3` 满足 `¬BoundedReturn ... 0 2`（`position 1 = 2, position 2 = 1/2`）。
2. **模型 B 对接验收**：在融合后的 `ChanDyn/Agents.lean` 中，构造模型 B 态空间实例 `modelB (k0 k1 : ℚ) : AsyncAgentSystem 1 2` 与异步双组延迟实例 `modelBTwoGroup (k0 k1 : ℚ) : AsyncAgentSystem 2 1`（`seen t 0 = t, seen t 1 = t - 1`），核验三个基准参数点：`(1, 1/2)` 轨道严格指数衰减至 `0`，`(1, 1)` 轨道产出周期 4 振荡 `1, 1, -1, -1, ...` 证伪 `AsymptoticStable`，`(5/2, 1/2)` 轨道产出周期 2 振荡 `1, -1, 1, -1, ...` 证伪 `AsymptoticStable`。

---

## 5. 形式化分离定理蓝图（`audit/fm10e-collision`）

下游应在 `Chan/Audit/Separation/Fm10eSeparation.lean` 中并列导入双方定义（或同构镜像别名），用 `decide` / `norm_num` / 有限算术构造以下 18 条核心形式化分离定理，作为 `#2322` 对撞证据与融合回归锁：

| 定理名 | 对应见证 | 形式化断言核心 | 证明手段 |
|---|---|---|---|
| `sep_ema_explicit_seed` | `W1` | `N=3, x=[10,14], seed=0` 时甲 `ema 0 = 5, ema 1 = 19/2` 而乙 `ema 0 = 0, ema 1 = 7` | `decide` / `norm_num` |
| `sep_zero_axis_explicit_seed` | `W2` | `x ≡ 101, pre = 100, n = 9` 时甲 `DIF 8 = (25/27)^9 - (11/13)^9 > 0` 而乙 `DIF 8 = 0` | `norm_num` |
| `sep_endpoint_diff_reversed` | `W4` | `x = [1, 5], s = 1, e = 0` 时甲 `endpointDiff = -4` 破坏 `posVar - negVar = endpointDiff`，乙为 `0` 保持恒等 | `decide` |
| `sep_ma_avg_force_sign` | `W5` | `[0,1]` 上 `maS=[8,6], maL=[10,10]` 时甲得 `-3`、乙得 `3`；`maS=[12,8]` 时甲得 `0`、乙得 `2` | `decide` |
| `sep_seg_slope_endpoints` | `W6` | `range=[0,10], source=[0,4], entry=2, exit=6` 时甲得 `5/2`、乙得 `1` | `decide` |
| `sep_impulse_down_orientation` | `W7` | 下跌段 `b: 10→4` 与 `c: 4→2` 上甲 `impulseFromRest .posVar` 全为 `0` 且末速 `-6 < -2`，乙得 `⟨6,6⟩` 与 `⟨2,2⟩` | `decide` |
| `sep_impulse_vs_first_breakout` | `W9a, W9b` | `0→5→4→6` vs `0→4→3→7` 上冲量族与均速判不弱而 `L_break` 判 `4 < 9/2`；`(0,0)→(1,4)` vs `(0,0)→(1,4)→(9,3)→(10,8)` 上均速判 `4/5 < 4` 而 `L_break` 判 `9/2 > 4`、正变差判 `73/8 > 4` | `decide` / `norm_num` |
| `sep_eval_force_orient_and_zero` | `W11a, W11b` | 非奇对称势 `max x 0` 在下跌窗上甲得 `0` 乙得 `4`；`first = 0` 前驱窗甲 `forceWeaker = True` 乙为 `false` | `decide` |
| `sep_consol_div_disjoint` | `W13a, W13b` | `a+A+c` 历史 `[0,10,6,9,7,11]` 上甲 `True` 乙 `false`；二次出核历史 `[16,20,14,24,16,25]` 上甲 `False` 乙 `true` | `decide` / 有限构造 |
| `sep_trend_div_composite_b` | `W14` | 两枢间三段复合连接 `b`（净位移 `8`、单段 `6, 5`）与 `c`（位移 `7`）上乙 `TrendDiv = true`、甲对所有 `i` 为 `False` | 有限构造 |
| `sep_div_confirmed_gap_through` | `W15` | 核 `[10, 12]` 离开极值 `15`、后缀 `tail = [8]` 时甲 `DivConfirmed = True`、乙为 `false` | 有限构造 |
| `sep_trend_end_non_exhaustive` | `W16` | 无背驰顺向离开后反向三卖路径上甲三分支全假，乙命中 `.reverseThird` | 有限构造 |
| `sep_prefix_observable_open_vs_clopen` | `W19` | `Q x := ∃ t, x t = 1` 在乙中 `PrefixObservable Q` 为真，在甲中 `¬PrefixObservable Q` | 构造性证明 |
| `sep_exhaustion_price_vs_thrust` | `W25` | 自由滑行轨 `[10, 14, 16, 16, 14, ...]` 配 `restore = -2, budget = 0` 上乙真甲假 | `norm_num` |
| `sep_sym_unimodal_even_group` | `W27` | 柱组 `[1, 2, 2, 1]` 在乙中 `SymUnimodalBarGroupHyp` 成立且 `2 * halfPeakArea = 6`，在甲中对任意 `p` 为假 | `decide` / `omega` |
| `sep_non_identical_sync_pair` | `W28b` | 双人两日完全同步买入市场上甲误判 `NonIdenticalTrading = True`，乙准确证 `¬NonIdenticalTrading` | `decide` / 有限构造 |
| `sep_modelA_damping_and_budget` | `W29, W32` | `ρ = 1/2, B_* = 8/3` 触边而无阻尼 `ρ = 1` 在 `f_0 = 8/3` 处逃逸至 `x_2 = 1/3`；滑行 `b` 段使甲 `BudgetBound` 封死为 `0` | `norm_num` |
| `sep_modelB_async_stability` | `W34, W35` | 乙在 `(1, 1/2)` 上实例化模型 B 且 `(1, 1)`、`(5/2, 1/2)` 产出非收敛周期轨；状态 `(t, -t)` 分离甲乙 `AsymptoticStable` | `norm_num` / 有限构造 |
