# FM-10c 接口约束页（M0 至 M9 与 M15）

本页只写文件路径、命名空间、公开定义名与一句话职责、Mathlib 载体类型、以及 Lean 4.36.0 `module` 与门禁规范。**本页不含任何 Lean 类型签名**，具体数据结构、参数顺序与实现方式由盲写双方独立决定。

## 一、文件、命名空间与公开定义清单

全部文件位于 `formal_math/Chan/Defs/` 下，文件模式 `100644`，每个 `.lean` 文件首行必须是 `module`，全部公开定义放进 `@[expose] public section`。

| 模块 | 文件路径（相对 `formal_math/`） | 命名空间 | 公开定义名及一句话职责 |
|---|---|---|---|
| M0 | `Chan/Defs/Order/Bar.lean` | `Chan.Defs.Order` | `Bar`（非空闭区间 K 线）；`Bar.contains`（闭区间包含，含端相等）；`Bar.strictUp`（严格上升）；`Bar.strictDown`（严格下降）；`Quantizer`（显式单调预处理映射）；`Quantizer.mapBar`（将预处理映射提升到 K 线） |
| M1 | `Chan/Defs/Order/IntervalAlg.lean` | `Chan.Defs.Order` | `overlaps`（两闭区间闭重叠）；`overlapsList`（有限非空区间列表公共交非空）；`interInterval`（两重叠闭区间之交）；`hullInterval`（有限非空区间列表凸包）；`gapUp`（向上缺口）；`gapDown`（向下缺口）；`strictAbove`（严格高于某价位）；`strictBelow`（严格低于某价位）；`CoreHull`（核区间含于波动区间的合法对）；`RelPos`（两 `CoreHull` 互斥穷尽相对位置枚举）；`relPos`（计算两 `CoreHull` 的相对位置） |
| M2 | `Chan/Defs/Path/History.lean` | `Chan.Defs.Path` | `History`（有限走势历史列表）；`IsPrefix`（前缀序）；`Confirmed`（对一切有限延拓不变的已确认谓词）；`DelayedCausal`（带有限展望步数的延迟因果谓词）；`LimitStable`（在无限延拓下最终稳定的极限谓词）；`RevisionCount`（前缀到延拓的被改写对象数与最深被拆层数度量）；`PendingCandidates`（未完成尾部的有限候选结果集合） |
| M3 | `Chan/Defs/Path/Symmetry.lean` | `Chan.Defs.Path` | `dualBar`（序对偶下的 K 线高低点互换）；`OrderEmb`（严格保序价格变换）；`mapBarEmb`（严格保序变换在区间上的提升）；`SmallModel`（有限长度序列压缩到有界离散格上的小模型载体） |
| M4 | `Chan/Defs/Alt/Basic.lean` | `Chan.Defs.Alt` | `Dir`（向上/向下方向与取反）；`Span`（起止索引来源跨度）；`Seg`（方向、值域闭区间、来源跨度构成的段）；`dualSeg`（段的多空对偶）；`AltSeq`（相邻段方向严格交替的段序列）；`dualAltSeq`（方向交替序列的多空对偶） |
| M4 | `Chan/Defs/Alt/Zigzag.lean` | `Chan.Defs.Alt` | `Zigzag`（相邻段共用端点的方向交替区间序列子类型）；`Zigzag.toAltSeq`（折线到方向交替序列的遗忘嵌入） |
| M4 | `Chan/Defs/Alt/CutChain.lean` | `Chan.Defs.Alt` | `CutChain`（单级严格递增切点下标表）；`NestedCuts`（多级逐级嵌套切点表）；`Laminar`（层状族谓词：两块不相交或互相包含）；`MultiAddress`（底层索引在多级切点链中的块路径地址） |
| M5 | `Chan/Defs/Center/Center.lean` | `Chan.Defs.Center` | `CanSeedCenter`（连续三段存在非空闭区间公共交）；`Center`（覆盖范围、核区间 `[ZD, ZG]`、波动区间 `[DD, GG]` 与不变式）；`Center.extendsWith`（单段与核闭重叠即为延伸）；`Center.leavesUp`（向上严格离开核）；`Center.leavesDown`（向下严格离开核）；`Center.thirdBuyEvent`（向上离开后首次向下回抽低点严格高于 `ZG`）；`Center.thirdSellEvent`（向下离开后首次向上回抽高点严格低于 `ZD`）；`Center.destroyed`（发生向上或向下第三类破坏事件） |
| M6 | `Chan/Defs/Level/Rule.lean` | `Chan.Defs.Level` | `Level`（以基底标签为索引的自然数深度）；`BlockRule`（块语言与粗化算子，上级段保留实际凸包值域）；`InterfaceLaws`（五条接口律：切点收缩、至少三段含核、保序不变、镜像等变、已确认稳定）；`CarryBounded`（进位有界律）；`DeterministicBlocks`（起点定终点加尾部穷尽条件，源自 `#2318`） |
| M6 | `Chan/Defs/Level/Tower.lean` | `Chan.Defs.Level` | `LevelTower`（给定规则与底层的逐级粗化塔）；`LevelTower.cuts`（提取各级原始切点下标表）；`LevelTower.sameCuts`（按各级原始切点表相等判同，不含证书） |
| M6 | `Chan/Defs/Level/Canonical.lean` | `Chan.Defs.Level` | `ValidDecomp`（规则与底层下的合法分解谓词）；`IsCanonical`（声明式规范性谓词）；`CanonicalDecomp`（同时合法且规范的分解） |
| M7 | `Chan/Defs/Level/CarryNine.lean` | `Chan.Defs.Level` | `CarryNineParams`（显式参数化 `#2318` 三处待裁定分支：成块时机、九段后重启、成核三段与进入段约定）；`carryNineRule`（规范进位块规则实例：支持九段 `3+3+3` 升级与三类回拉波动重叠升级，按优先确立高级别中枢择优） |
| M8 | `Chan/Defs/Level/SameLevel.lean` | `Chan.Defs.Level` | `sameLevelRule`（同级别分解规则实例：本级不延伸，三段重叠成块，允许盘整接盘整） |
| M8 | `Chan/Defs/Level/NoCap.lean` | `Chan.Defs.Level` | `noCapRule`（不设延伸上限的对照规则实例） |
| M9 | `Chan/Defs/Level/TrendType.lean` | `Chan.Defs.Level` | `TrendKind`（盘整、上涨趋势、下跌趋势三态枚举）；`classifyTrend`（仅按同级中枢个数及相邻波动区间严格分离分类，a、c 段可缺省）；`TrendFormingProspect`（单列的前瞻谓词：第一中枢后三买且未破坏） |
| M15 | `Chan/Defs/Signal/Phase.lean` | `Chan.Defs.Signal` | `Phase`（中阴阶段、中枢震荡阶段、离开阶段三态状态机）；`phaseAt`（结合分解与位置判定当前所处阶段） |
| M15 | `Chan/Defs/Signal/Points.lean` | `Chan.Defs.Signal` | `StrengthJudge`（抽象力度/背驰判定参数接口，不依赖具体指标）；`BreakoutRetest`（通用突破后首次回试纯几何谓词）；`isFirstBuy`、`isFirstSell`（带分解与力度参数的第一类买卖点）；`SecondStrength`（二买强弱三分枚举）；`isSecondBuy`、`isSecondSell`（中阴阶段版本四第二类买卖点及强弱分类）；`isThirdBuy`、`isThirdSell`（B-11 全要件严格第三类买卖点）；`isPseudoThirdBuy`、`isPseudoThirdSell`（最低级别类第三类买卖点）；`isOscillationBuy`、`isOscillationSell`（中枢震荡阶段买卖点） |

## 二、推荐 Mathlib 载体（Lean `v4.36.0` + Mathlib `v4.36.0` 已实测存在）

- 闭区间：`NonemptyInterval P`（或自建带 `lo <= hi` 证明的二元结构并在需要时与 `NonemptyInterval P` 互转；`NonemptyInterval.toProd`、`NonemptyInterval.toDualProd`、`NonemptyInterval.dual` 均已核实可用）
- 列表与相邻关系：`List`、`List.IsChain`（注意：`List.Chain'` 已更名为 `List.IsChain`）、`List.IsPrefix`
- 有限极值：`Finset.sup'`、`Finset.inf'` 或列表直接 `max`/`min` 递归
- 多空对偶：`OrderDual`
- 无限历史与最终稳定：`PiNat.cylinder`、`PiNat.firstDiff`、`Filter.atTop`、`Filter.EventuallyConst`
- 可判定性：全部在可判定线性序上定义的核心谓词应提供 `Decidable` / `DecidablePred` 实例（或等价的可计算布尔判别函数并配正确性定义），以便小模型穷举与 `decide` 核验。

## 三、Lean `v4.36.0` 模块系统与 `#2312` 阻断门硬规范（原样附 3.9 十四条约束）

1. 每个 `.lean` 文件第一条命令必须是 `module`。公开签名用到的模块用 `public import`，其余用 `import`。`Chan/Defs/` 下的定义一律放进 `@[expose] public section`。
2. 禁止整库 `import Mathlib`，只导入用到的具体子模块；`Chan/Defs/` 仅允许导入 `Chan.Defs.*`、`Mathlib.*` 与 `Init.*`（禁止导入 `Chan.Proxy`、`Chan.Thm`、`ChanExplore` 等）。
3. Mathlib 名称先在本机 `#check` 核实后再用（`List.Chain'` 已不存在，现名 `List.IsChain`）。
4. 禁用 `axiom`、`sorry`、`admit`、`native_decide`、`unsafe`、`extern`、`implemented_by`、`partial`、任何受控 `set_option`（`autoImplicit`、`relaxedAutoImplicit`、`linter.*`）及本地元编程（`macro`、`syntax`、`elab`、`notation`、`initialize`、`#eval`、`run_cmd` 等）。
5. 盲写工位只允许在自身盲写分支创建/修改 `formal_math/Chan/Defs/` 下上表列出的文件，禁止修改 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`、`statement-lock.json`、`verification/`、`scripts/`、`.github/`。
6. 写定义阶段不写定理证明（可仅附构造性实例或必要类型不变式证明，确保定义良型、可判定）。
7. 每条 shell 命令保持短、单一用途；多行脚本先写成文件再执行。
8. 环境优先复用外置盘 `/Volumes/AgentStorage/fm/` 下的只读 Mathlib 依赖目录与 `TMPDIR`，不向系统内置盘复制 Mathlib。
9. 严禁从源码重新编译 Mathlib；若发现 Lake 开始编译 Mathlib 立即中止并报告。
10. 交卷前必须通过 `lake build --wfail`（以及 `#2312` 阻断门第 4、5、6、7 步检查，除未更新 `statement-lock.json` 外的全部红项必须为零）。
11. 文档串中的课行号与逐字引文只能从本引文包 `02-citations.md` 原样复制；硬证据标 `[课号:行号]`，二级旁证必须显式标 `[二级旁证 课号:行号]`，不得引用编者注或修改引文。
12. 严禁读取对方盲写分支、对方会话、旧 `formal/` 目录或 `.chanlun/definitions/` 目录。
13. 后台任务未结束前不结束回合，必须拿到最终退出码。
14. 盲写期间不推送分支到远端（封存 SHA 后才揭示）；交卷末行按格式回报 `RESULT: 分支，head SHA，构建命令与退出码，门禁结果，未解决项`。
