# FM-10e 接口约束页（M16、M17、M18、M19a 与 M19b）

本页只写文件路径、命名空间、公开定义名与一句话职责、Mathlib 载体类型、以及 Lean 4.36.0 `module` 与门禁规范。**本页不含任何 Lean 类型签名**，具体数据结构、参数顺序与实现方式由盲写双方独立决定。

## 一、文件、命名空间与公开定义清单

全部文件模式 `100644`，每个 `.lean` 文件首行必须是 `module`，全部公开定义放进 `@[expose] public section`。注意分层隔离：`Chan/Defs/` 绝不得导入 `Chan/Proxy/` 或 `ChanDyn/`；`ChanDyn/` 是完全独立的研究库，不得被 `Chan/Final` 或 `Chan/Defs/` 导入。

| 模块 | 文件路径（相对 `formal_math/`） | 命名空间 | 公开定义名及一句话职责 |
|---|---|---|---|
| M16a | `Chan/Proxy/Ema.lean` | `Chan.Proxy` | `EmaParams`（平滑系数/周期与播种方式参数）；`emaSeq`（指数均线序列）；`smaSeq`（简单移动平均序列）；`emaDecay`（精确有理衰减因子 `(N-1)/(N+1)`）；`ZeroAxisBoundData`（带旧价带距 `delta` 的精确有理零轴回拉界参数结构） |
| M16a | `Chan/Proxy/Macd.lean` | `Chan.Proxy` | `MacdParams`（短周期、长周期、信号周期参数）；`MacdPoint`（`dif`、`dea`、`hist` 三分量）；`macdSeq`（MACD 序列）；`signedSum`（带号柱和）；`posSum`（红柱正部和）；`negSum`（绿柱负部绝对值和）；`absSum`（绝对值和）；`posVar`、`negVar`、`totalVar`、`endpointDiff`（离散变差与端点差） |
| M16a | `Chan/Proxy/MaArea.lean` | `Chan.Proxy` | `maSignedArea`（窗口内双均线带号面积）；`maPosArea`、`maNegArea`（正负部面积）；`maAvgForce`（`015:42` 均线面积除以窗口时长） |
| M16b | `Chan/Defs/Dynamics/StructImpulse.lean` | `Chan.Defs.Dynamics` | `segSlope`（单段离散斜率/均速）；`impulseIn`（纯段内读数 `L_in`）；`impulsePre`（带前驱读数 `L_pre`）；`impulseZero`（从静止起算读数 `L_zero`）；`impulseFromRest`（从静止起算正变差/末态速度族，不设默认实例） |
| M16c | `Chan/Defs/Dynamics/Potential.lean` | `Chan.Defs.Dynamics` | `ForceWindow`（由分解给出的两比较段跨度与可选锚定中枢）；`CausalPotential`（因果势函数接口，不含价格平移强约束）；`PosHomogeneous`（一次正齐次性谓词）；`MirrorAntiSym`（多空镜像反号谓词） |
| M16c | `Chan/Defs/Dynamics/ForceSpec.lean` | `Chan.Defs.Dynamics` | `ReadingKind`（端点差/正变差读法枚举）；`EndpointConv`（窗口端点约定枚举）；`ForceSpec`（含窗口、势函数、读法、端点约定四参数且无默认值的综合力度接口）；`evalForce`（在给定历史与窗口上评估力度）；`ReadingShiftInvariant`（挂在读数层上的价格平移不变性谓词）；`PositiveAffineEquiv`（正仿射等变性谓词）；`ForceCompareMode`（严格小于/不大于比较开关）；`forceWeaker`（两窗口力度减弱谓词） |
| M17 | `Chan/Defs/Dynamics/Divergence.lean` | `Chan.Defs.Dynamics` | `MakesNewExtreme`（创新高/新低独立前提谓词）；`DivOnline`（仅依赖当前历史前缀的在线背驰谓词）；`DivConfirmed`（依赖后续延拓的事后确认背驰谓词）；`TrendDiv`（趋势背驰：比较最后中枢两侧连接段）；`ConsolDiv`（盘整背驰：比较单中枢同侧相邻两次离开）；`TrendEndCase`（趋势终结三分互斥枚举）；`trendEndClassify`（趋势终结三分谓词）；`DivSegment`（某级别背驰段）；`NestedDivChain`（纯结构逐级嵌套区间套，不强加每级背驰）；`SmallDivTriggersBigTurn`（小级别背驰引发大级别转折谓词）；`TurnWithoutSameLevelDiv`（无本级背驰转折谓词） |
| M18 | `Chan/Defs/Limits/Liveness.lean` | `Chan.Defs.Limits` | `InfPath`（自然数索引无限价格路径）；`prefixOf`（截断至前 `n` 步有限历史）；`PrefixObservable`（由有限前缀决定的可观测谓词）；`EventuallyStable`（基于 `Filter.atTop` 与 `Filter.EventuallyConst` 的最终稳定谓词）；`DecompExistsSpec`、`CanonicalUniqueSpec`、`BoundedTerminationSpec`、`WeakSafetySpec`（B-24 拆分的四条独立命名命题签名） |
| M19a | `Chan/Hypotheses/Dynamics.lean` | `Chan.Hypotheses` | `LivenessHyp`（活性假设 `Prop`）；`InertiaHyp`（惯性假设 `Prop`）；`ExhaustionHyp`（衰竭假设 `Prop`）；`PullbackHyp`（回复假设 `Prop`，依赖闭包不含结论谓词）；`SymUnimodalBarGroupHyp`（修正后的柱组对称单峰假设 `Prop`）；`DynamicsHypBundle`（五项假设的显式打包结构，无默认值）；`MarketParticipant`、`OrderEvent`、`TaggedMarket`、`EfficientPriceMarket`、`NonIdenticalTrading`（第 30 课极小带参与者标签市场模型与两前提） |
| M19b | `ChanDyn/Well.lean` | `ChanDyn` | `WellModel`（D1 单中枢势阱二阶离散递推模型类）；`WellSymmetric`（两侧对称性谓词）；`WellTimeInvariant`（时间不变性谓词）；`WellBoundedRange`（作用范围有界谓词）；`CoastingZeroThrust`（滑行期零外力谓词）；`FallsFromRest`（`b` 段自静止落入谓词） |
| M19b | `ChanDyn/Thrust.lean` | `ChanDyn` | `ThrustModel`（D2 带外加推力序列的拓展势阱模型类）；`BudgetBound`（有限推力预算比较上界假设）；`BoundedReturn`（有限步内回到中枢的目标状态谓词） |
| M19b | `ChanDyn/Field.lean` | `ChanDyn` | `MultiCenterField`（D3 多中枢叠加回复场模型类）；`residualThrust`（二阶差分减去结构场的残余推力）；`NearestCenterDominates`（最近中枢主导误差界接口） |
| M19b | `ChanDyn/Agents.lean` | `ChanDyn` | `AsyncAgentSystem`（D4 多参与者向量叠加与异步响应递推模型类）；`AsymptoticStable`（无限时间渐近稳定谓词，显式区别于有限期限可达） |

## 二、推荐 Mathlib 载体（Lean `v4.36.0` + Mathlib `v4.36.0` 已实测存在）

- 数值与有序域：`Rat`（`ℚ`）或抽象 `[Field R] [LinearOrder R] [IsStrictOrderedRing R]`（注：`LinearOrderedField` 在新版 Mathlib 已拆分，使用 `IsStrictOrderedRing` 已实测存在）
- 有限求和：`Finset.sum`（`Mathlib.Algebra.BigOperators.Group.Finset.Basic`）
- 无限历史与稳定：`PiNat.cylinder`、`PiNat.firstDiff`、`Filter.atTop`、`Filter.EventuallyConst`
- 多空对偶：`OrderDual`
- 可判定性：全部代理计算与有限窗口谓词在 `ℚ` 上可计算/可判定；无限路径与 `Prop` 命名假设不强求 `Decidable`，但须保持无公理、构造清晰且不含结论循环。

## 三、Lean `v4.36.0` 模块系统与 `#2312` 阻断门硬规范（原样附 3.9 十四条约束）

1. 每个 `.lean` 文件第一条命令必须是 `module`。公开签名用到的模块用 `public import`，其余用 `import`。公开定义一律放进 `@[expose] public section`。
2. 禁止整库 `import Mathlib`，只导入用到的具体子模块；`Chan/Defs/` 仅允许导入 `Chan.Defs.*`、`Mathlib.*` 与 `Init.*`（严禁导入 `Chan.Proxy`、`ChanDyn`、`Chan.Thm`、`ChanExplore`）；`Chan/Hypotheses/` 允许导入 `Chan.Defs.*`、`Mathlib.*`、`Init.*`；`Chan/Proxy/` 允许导入 `Chan.Defs.*`、`Mathlib.*`、`Init.*`；`ChanDyn/` 允许导入 `Chan.Defs.*`、`Chan.Hypotheses.*`、`Mathlib.*`、`Init.*`，但绝不被其他库反向导入。
3. Mathlib 名称先在本机 `#check` 核实后再用（`List.Chain'` 已不存在，现名 `List.IsChain`；`IsStrictOrderedRing` 已实测存在）。
4. 禁用 `axiom`、`sorry`、`admit`、`native_decide`、`unsafe`、`extern`、`implemented_by`、`partial`、任何受控 `set_option`（`autoImplicit`、`relaxedAutoImplicit`、`linter.*`）及本地元编程（`macro`、`syntax`、`elab`、`notation`、`initialize`、`#eval`、`run_cmd` 等）。
5. 盲写工位只允许在自身盲写分支创建/修改上表列出的 13 个文件，禁止修改 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`、`statement-lock.json`、`verification/`、`scripts/`、`.github/`。
6. 写定义阶段不写定理证明（可仅附构造性实例或必要类型不变式证明，确保定义良型）。
7. 每条 shell 命令保持短、单一用途；多行脚本先写成文件再执行。
8. 环境优先复用外置盘 `/Volumes/AgentStorage/fm/` 下的只读 Mathlib 依赖目录与 `TMPDIR`，不向系统内置盘复制 Mathlib。
9. 严禁从源码重新编译 Mathlib；若发现 Lake 开始编译 Mathlib 立即中止并报告。
10. 交卷前必须通过 `lake build --wfail`（以及 `#2312` 阻断门第 4、5、6、7 步检查，除未更新 `statement-lock.json` 与 `ChanDyn` 跨角色路径外，其余红项必须为零）。
11. 文档串中的课行号与逐字引文只能从本引文包 `02-citations.md` 原样复制；硬证据标 `[课号:行号]`，二级旁证必须显式标 `[二级旁证 课号:行号]`，不得引用编者注或修改引文。
12. 严禁读取对方盲写分支、对方会话、旧 `formal/` 目录或 `.chanlun/definitions/` 目录。
13. 后台任务未结束前不结束回合，必须拿到最终退出码。
14. 盲写期间不推送分支到远端（封存 SHA 后才揭示）；交卷末行按格式回报 `RESULT: 分支，head SHA，构建命令与退出码，门禁结果，未解决项`。
