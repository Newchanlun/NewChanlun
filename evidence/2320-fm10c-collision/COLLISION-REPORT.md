# FM-10c（`#2320`）盲写双轨对撞裁定报告（M0 至 M9 与 M15）

- **分析角色**：第三模型家族盲写对撞分析官（Google `gemini-4-neon-xhigh`）
- **对撞对象**：
  - 甲方（Opus）：`origin/blind/fm10c-opus` @ `d7a2a8c094`（Anthropic `claude-opus-5-5-high`，17 份 Lean 4.36.0 文件）
  - 乙方（Astra）：`origin/blind/fm10c-astra` @ `9ab813738d`（OpenAI `gpt-6.2-astra`，17 份 Lean 4.36.0 文件）
- **权威基准**：`origin/pack/fm10c` @ `951a22fb28`（`01-rulings.md`、`02-citations.md`、`03-informal-specs.md`、`04-interface-constraints.md`）
- **统计总览**：共核查 17 个文件、**86** 对公开定义（含 `04-interface-constraints.md` 必选公开定义 **81** 对与双方共有关键辅助定义 **5** 对）：
  - `EQUIV`（数学等价）：**46** 对（必选 43 对 + 辅助 3 对）
  - `SEPARATED`（语义分离）：**37** 对（必选 35 对 + 辅助 2 对），归并为 **20** 组最小有限可机检见证（`W1` 至 `W20`）
  - `UNDECIDED`（原典未定）：**3** 对（必选 3 对：M6 `IsCanonical`、`CanonicalDecomp` 与 M7 `CarryNineParams`），另提炼出 **4** 条来自高危分离点的残留原典未定数学轴
  - **深审建议**：**需要标记 `needs-fable`**（围绕 M6 规范谓词局部贪心与全局回溯结合律、M6 偶数长度块粗化后的高阶方向交替性、M7 三分支参数空间与重启语义、M15 一类点离枢阈 `DD` vs `ZD` 及比较段口径提交数学深审与 `#2296` 冻结）

---

## 一、逐文件逐定义对撞总表

说明：`[必选]` 为 `04-interface-constraints.md` 清单列明的 81 个公开定义；`[辅助]` 为双方均公开且直接影响下游语义的 5 个关键辅助定义。

### 分模块汇总

| 模块 | 文件路径（相对 `Chan/Defs/`） | 必选对数 | 辅助对数 | `EQUIV` | `SEPARATED` | `UNDECIDED` |
|---|---|---:|---:|---:|---:|---:|
| M0 | `Order/Bar.lean` | 6 | 0 | 6 | 0 | 0 |
| M1 | `Order/IntervalAlg.lean` | 11 | 0 | 11 | 0 | 0 |
| M2 | `Path/History.lean` | 7 | 0 | 5 | 2 | 0 |
| M3 | `Path/Symmetry.lean` | 4 | 0 | 3 | 1 | 0 |
| M4 | `Alt/Basic.lean` | 6 | 2 | 7 | 1 | 0 |
| M4 | `Alt/Zigzag.lean` | 2 | 0 | 0 | 2 | 0 |
| M4 | `Alt/CutChain.lean` | 4 | 0 | 1 | 3 | 0 |
| M5 | `Center/Center.lean` | 8 | 1 | 6 | 3 | 0 |
| M6 | `Level/Rule.lean` | 5 | 1 | 1 | 5 | 0 |
| M6 | `Level/Tower.lean` | 3 | 0 | 2 | 1 | 0 |
| M6 | `Level/Canonical.lean` | 3 | 0 | 0 | 1 | 2 |
| M7 | `Level/CarryNine.lean` | 2 | 0 | 0 | 1 | 1 |
| M8 | `Level/SameLevel.lean` | 1 | 0 | 0 | 1 | 0 |
| M8 | `Level/NoCap.lean` | 1 | 0 | 0 | 1 | 0 |
| M9 | `Level/TrendType.lean` | 3 | 0 | 2 | 1 | 0 |
| M15 | `Signal/Phase.lean` | 2 | 0 | 1 | 1 | 0 |
| M15 | `Signal/Points.lean` | 13 | 1 | 1 | 13 | 0 |
| **合计** | **17 个文件** | **81** | **5** | **46** | **37** | **3** |

### 逐定义 86 对明细表

| 编号 | 模块 | 文件 | 定义名 | 类别 | 结论 | 一句话核心差异 |
|---:|---|---|---|---|---|---|
| 1 | M0 | `Order/Bar.lean` | `Bar` | 必选 | `EQUIV` | 仅序类型类载体不同（甲方 `LinearOrder` 缺 `DecidableEq` 派生，乙方 `Std.LinearOrderPackage` 含 `DecidableEq`）。 |
| 2 | M0 | `Order/Bar.lean` | `Bar.contains` | 必选 | `EQUIV` | 双方公式完全相同（`a.lo ≤ b.lo ∧ b.hi ≤ a.hi`），甲方为 `def` 配实例、乙方为 `abbrev`。 |
| 3 | M0 | `Order/Bar.lean` | `Bar.strictUp` | 必选 | `EQUIV` | 合取项次序互换（`hi < hi ∧ lo < lo` 对 `lo < lo ∧ hi < hi`），逻辑恒等。 |
| 4 | M0 | `Order/Bar.lean` | `Bar.strictDown` | 必选 | `EQUIV` | 甲方直写双严格不等，乙方复用 `b.strictUp a`，逻辑恒等。 |
| 5 | M0 | `Order/Bar.lean` | `Quantizer` | 必选 | `EQUIV` | 仅字段名与隐式参数不同（`toFun`/`mono` 对 `apply`/`monotone`），同构。 |
| 6 | M0 | `Order/Bar.lean` | `Quantizer.mapBar` | 必选 | `EQUIV` | 逐端点应用单调映射，实现完全一致。 |
| 7 | M1 | `Order/IntervalAlg.lean` | `overlaps` | 必选 | `EQUIV` | 双方均写作 `max a.lo b.lo ≤ min a.hi b.hi`，单点相触算重叠。 |
| 8 | M1 | `Order/IntervalAlg.lean` | `overlapsList` | 必选 | `EQUIV` | 非空列表 `a :: bs` 上依一维 Helly 性质严格等价；甲方接受空表返回 `False`，乙方以类型 `(a, bs)` 禁止空表。 |
| 9 | M1 | `Order/IntervalAlg.lean` | `interInterval` | 必选 | `EQUIV` | 双方均在 `overlaps` 证据下构造 `⟨max lo, min hi, h⟩`，完全一致。 |
| 10 | M1 | `Order/IntervalAlg.lean` | `hullInterval` | 必选 | `EQUIV` | 双方均对 `(b, rest)` 做 `foldl` 取 `(min lo, max hi)`，完全一致。 |
| 11 | M1 | `Order/IntervalAlg.lean` | `gapUp` | 必选 | `EQUIV` | 双方均为 `a.hi < b.lo`。 |
| 12 | M1 | `Order/IntervalAlg.lean` | `gapDown` | 必选 | `EQUIV` | 甲方为 `b.hi < a.lo`，乙方为 `gapUp b a`，恒等。 |
| 13 | M1 | `Order/IntervalAlg.lean` | `strictAbove` | 必选 | `EQUIV` | 双方均为 `x < b.lo`。 |
| 14 | M1 | `Order/IntervalAlg.lean` | `strictBelow` | 必选 | `EQUIV` | 双方均为 `b.hi < x`。 |
| 15 | M1 | `Order/IntervalAlg.lean` | `CoreHull` | 必选 | `EQUIV` | 字段均为 `core`/`hull`/`inside : hull.contains core`，乙方多派生 `DecidableEq`。 |
| 16 | M1 | `Order/IntervalAlg.lean` | `RelPos` | 必选 | `EQUIV` | 五构造子严格一一对应（`sepUp/sepDown/expandUp/expandDown/coreOverlap` 对 `separatedUp/.../coresOverlap`）。 |
| 17 | M1 | `Order/IntervalAlg.lean` | `relPos` | 必选 | `EQUIV` | 甲方先判核重叠再判波动分离，乙方先判波动分离再判核重叠，在 `CoreHull` 不变式下五分支结果恒等。 |
| 18 | M2 | `Path/History.lean` | `History` | 必选 | `EQUIV` | 双方均为 `List` 别名。 |
| 19 | M2 | `Path/History.lean` | `IsPrefix` | 必选 | `EQUIV` | 甲方用 `length ≤ ∧ take =`，乙方用 `List.IsPrefix`，两者严格等价。 |
| 20 | M2 | `Path/History.lean` | `Confirmed` | 必选 | `EQUIV` | 双方均为 `∀ t, f (h ++ t) = f h`。 |
| 21 | M2 | `Path/History.lean` | `DelayedCausal` | 必选 | `EQUIV` | 仅参数顺序相反，且在 `h.length ≤ i + k` 时 `take (i + k + 1) h = h` 使等式平凡成立，严格等价。 |
| 22 | M2 | `Path/History.lean` | `LimitStable` | 必选 | `EQUIV` | 甲方存在量化极限值，乙方显式传入目标极限值 `value`，满足 `Opus.LimitStable f s ↔ ∃ v, Astra.LimitStable f s v`。 |
| 23 | M2 | `Path/History.lean` | `RevisionCount` | 必选 | `SEPARATED` | 甲方按列表下标逐位比对（前端删除导致未改动项被重复计为修订）且层深自 1 起用 0 表无修订；乙方按稳定地址 `Key` 比对且用 `Option Nat` 自 0 起计层（见证 `W1`）。 |
| 24 | M2 | `Path/History.lean` | `PendingCandidates` | 必选 | `SEPARATED` | 甲方仅在调用方有限样本 `U` 上收集未去重列表（漏值且可重复）；乙方以 `FiniteImage` 刻画全体合法有限延拓上的精确无重像集（见证 `W2`）。 |
| 25 | M3 | `Path/Symmetry.lean` | `dualBar` | 必选 | `EQUIV` | 甲方落入 Mathlib `OrderDual P`，乙方落入自建 `PriceDual P`，二者序同构。 |
| 26 | M3 | `Path/Symmetry.lean` | `OrderEmb` | 必选 | `EQUIV` | 甲方用 `toFun x ≤ toFun y ↔ x ≤ y`，乙方用 `a < b → apply a < apply b`，在线性序上严格等价。 |
| 27 | M3 | `Path/Symmetry.lean` | `mapBarEmb` | 必选 | `EQUIV` | 逐端点提升严格保序映射到 `Bar`，行为等价。 |
| 28 | M3 | `Path/Symmetry.lean` | `SmallModel` | 必选 | `SEPARATED` | 甲方是有界离散格载体结构（无压缩映射），乙方是未去重秩压缩函数（输出未封装 `lo ≤ hi` 不变式，且重复端点导致非致密跳秩，见证 `W3`）。 |
| 29 | M4 | `Alt/Basic.lean` | `Dir` | 必选 | `EQUIV` | 二元枚举 `up | down`，完全一致。 |
| 30 | M4 | `Alt/Basic.lean` | `Dir.flip` | 辅助 | `EQUIV` | 二元取反，完全一致。 |
| 31 | M4 | `Alt/Basic.lean` | `Span` | 必选 | `EQUIV` | 闭索引跨度结构同构（`start/stop/le` 对 `first/last/ordered`），乙方多 `DecidableEq`。 |
| 32 | M4 | `Alt/Basic.lean` | `Seg` | 必选 | `EQUIV` | 字段同构（`dir/range/span` 对 `dir/range/source`），乙方多 `DecidableEq`。 |
| 33 | M4 | `Alt/Basic.lean` | `Seg.mapEmb` | 辅助 | `EQUIV` | 保留方向与跨度、提升区间映射，完全一致。 |
| 34 | M4 | `Alt/Basic.lean` | `dualSeg` | 必选 | `EQUIV` | 方向取反、值域取序对偶、跨度不变，等价。 |
| 35 | M4 | `Alt/Basic.lean` | `AltSeq` | 必选 | `SEPARATED` | 甲方用 `(start, body)` 导致空序列存在两个不同值（`up [] ≠ down []`）；乙方用 `List (Seg P)` 加交替证明使空序列唯一（见证 `W4`）。 |
| 36 | M4 | `Alt/Basic.lean` | `dualAltSeq` | 必选 | `EQUIV` | 在导出段表层面严格同构为 `segs.map dualSeg`（空序列自对偶性差异完全源于第 35 项 `AltSeq` 载体本身）。 |
| 37 | M4 | `Alt/Zigzag.lean` | `Zigzag` | 必选 | `SEPARATED` | 甲方外挂任意落在区间内的 `(起点价, 终点价)` 且漏检方向单调性；乙方限定为极值共端子类型 `zigEnd = zigStart`（见证 `W5a`/`W5b`）。 |
| 38 | M4 | `Alt/Zigzag.lean` | `Zigzag.toAltSeq` | 必选 | `SEPARATED` | 甲方投影忘掉非唯一端点表因而不单射；乙方是子类型值投影构成严格单射嵌入（见证 `W5b`）。 |
| 39 | M4 | `Alt/CutChain.lean` | `CutChain` | 必选 | `SEPARATED` | 甲方允许空表与非零首切点（如 `[2, 5]`）；乙方强制 `marks.head? = some 0`（见证 `W6`）。 |
| 40 | M4 | `Alt/CutChain.lean` | `NestedCuts` | 必选 | `SEPARATED` | 逐级子集嵌套律相同，但继承 `CutChain` 的零起点约束分离（见证 `W6`）。 |
| 41 | M4 | `Alt/CutChain.lean` | `Laminar` | 必选 | `SEPARATED` | 甲方漏检非空块 `b.1 < b.2`，导致空块 `(3,3)` 与倒置块 `(5,2)` 均被判为层状族；乙方强制 `∀ b ∈ blocks, b.1 < b.2`（见证 `W7`）。 |
| 42 | M4 | `Alt/CutChain.lean` | `MultiAddress` | 必选 | `EQUIV` | 在共有的零起点 `NestedCuts n` 与 `i : Fin n` 上返回完全相同的 `List (Option Nat)`（甲方接受越界 `Nat` 返回全 `none`）。 |
| 43 | M5 | `Center/Center.lean` | `CanSeedCenter` | 必选 | `EQUIV` | 均为连续三段闭区间 `max lo ≤ min hi` 判别；甲方取独立三段，乙方取 `AltSeq` 与下标 `i`。 |
| 44 | M5 | `Center/Center.lean` | `Center` | 必选 | `EQUIV` | 在 `AltSeq` 上，甲方 `Center + WellFormed` 与乙方自证段包 `Center + extract = cover` 一一对应（甲方免 `dupNamespace`，乙方触发 `Chan.Defs.Center.Center`）。 |
| 45 | M5 | `Center/Center.lean` | `Center.core` | 辅助 | `EQUIV` | 均为前三段公共交 `[ZD, ZG]`。 |
| 46 | M5 | `Center/Center.lean` | `Center.extendsWith` | 必选 | `EQUIV` | 均为单段值域与核的对称闭重叠。 |
| 47 | M5 | `Center/Center.lean` | `Center.leavesUp` | 必选 | `EQUIV` | 双方均为 `ZG < s.range.lo`。 |
| 48 | M5 | `Center/Center.lean` | `Center.leavesDown` | 必选 | `EQUIV` | 双方均为 `s.range.hi < ZD`。 |
| 49 | M5 | `Center/Center.lean` | `Center.thirdBuyEvent` | 必选 | `SEPARATED` | **高危**：甲方离开段仅需 `ZG < leave.hi`（允许起于核内）；乙方要求 `z.leavesUp leave`（整段跳空于 `ZG` 之上），导致连续折线永假（见证 `W8a`）。 |
| 50 | M5 | `Center/Center.lean` | `Center.thirdSellEvent` | 必选 | `SEPARATED` | **高危**：乙方要求 `z.leavesDown leave`，直接否决缠师 `[054:24]` `d1 > g2` 标杆回归例（见证 `W8b`）。 |
| 51 | M5 | `Center/Center.lean` | `Center.destroyed` | 必选 | `SEPARATED` | **高危**：作为向上/向下第三类事件之并，继承 `thirdBuyEvent`/`thirdSellEvent` 的连续离开与跳空离开分离（见证 `W8a`/`W8b`）。 |
| 52 | M6 | `Level/Rule.lean` | `Level` | 必选 | `EQUIV` | 均以基底标签为类型索引包装 `depth : Nat`（甲方置于 `Chan.Defs` 免 `dupNamespace`，乙方触发 `Chan.Defs.Level.Level`）。 |
| 53 | M6 | `Level/Rule.lean` | `BlockRule` | 必选 | `SEPARATED` | 甲方为无层级、无历史、无优先级的布尔块语言加自定义 `blockDir`；乙方带层深 `k`、历史切点 `past`、优先级 `rank : Option Nat` 与独立 `confirmed` 标志（见证 `W9b`/`W10b`）。 |
| 54 | M6 | `Level/Rule.lean` | `BlockRule.coarsen` | 辅助 | `SEPARATED` | 越界 `j > xs.length` 时甲方静默截断返回 `some`，乙方守卫返回 `none`；且甲方用 `r.blockDir`、乙方写死首段方向（见证 `W9a`）。 |
| 55 | M6 | `Level/Rule.lean` | `InterfaceLaws` | 必选 | `SEPARATED` | 甲方要求一切被接受块均前缀稳定（其自身 `carryNineRule(seeded)` 即违约），乙方仅对 `confirmed` 块要求稳定并作逐点 `Bool` 判定（见证 `W9b`）。 |
| 56 | M6 | `Level/Rule.lean` | `CarryBounded` | 必选 | `SEPARATED` | 甲方约束块内最长延伸段数 `ExtRun ≤ K`；乙方约束整块总长度 `j - i ≤ bound`，在 `bound = 9` 时否决 `[057:42]` 的 10 段进入加九段块（见证 `W9c`）。 |
| 57 | M6 | `Level/Rule.lean` | `DeterministicBlocks` | 必选 | `SEPARATED` | 甲方对规则强加全局单终点与有误的 `TailStart` 单调性（被其自身 `sameLevelRule` 证伪）；乙方针对切点表检验每步唯一占优终点加末切点尾部穷尽（见证 `W9d`）。 |
| 58 | M6 | `Level/Tower.lean` | `LevelTower` | 必选 | `SEPARATED` | **高危**：乙方 `Stage.ascend` 强检粗化后上级段方向严格交替，但 `coarsen` 取首段方向，导致任意非末尾偶数长度块（4/6/8/10 段）整体不可构造；甲方不检上级交替且允许空层（见证 `W10a`）。 |
| 59 | M6 | `Level/Tower.lean` | `LevelTower.cuts` | 必选 | `EQUIV` | 在双方均可构造的合法非空塔上返回完全相同的底层原始切点下标表。 |
| 60 | M6 | `Level/Tower.lean` | `LevelTower.sameCuts` | 必选 | `EQUIV` | 双方均仅比较 `cuts` 相等，不比较证书（符合 `#2318` 结论二）。 |
| 61 | M6 | `Level/Canonical.lean` | `ValidDecomp` | 必选 | `SEPARATED` | 甲方允许非末尾偶数长度块，但因 `accepts` 确定化吞并了多义合法分解；乙方允许同规则多合法分解，但因 `realize` 拒收非末尾偶数长度块（见证 `W10a`/`W10b`）。 |
| 62 | M6 | `Level/Canonical.lean` | `IsCanonical` | 必选 | `UNDECIDED` | 原典未钉死局部左至右最高优先级贪心（乙方）与全局高级中枢优先回溯结合律（`[099:22]`/`[099:26]`）及平票裁决；甲方仅查尾部穷尽，连 `#2318` 的 `3+5` 与 `5+3` 也无法区分。 |
| 63 | M6 | `Level/Canonical.lean` | `CanonicalDecomp` | 必选 | `UNDECIDED` | 直接封装 `ValidDecomp ∧ IsCanonical`，继承 M6 规范谓词的原典未定性（另载体为原始切点表对 `LevelTower` 子类型）。 |
| 64 | M7 | `Level/CarryNine.lean` | `CarryNineParams` | 必选 | `UNDECIDED` | `#2318` 三分支本属原典未定；且双方对分支 B 取了不相交选项空间（甲方：止于第 9 段 vs 延至下一成核点；乙方：进位后下块是否强制独立进入段）。 |
| 65 | M7 | `Level/CarryNine.lean` | `carryNineRule` | 必选 | `SEPARATED` | **高危**：即使参数对齐仍有四重分离：甲方未检 `3+3+3` 三凸包公共交（见证 `W11a`）；乙方无前导成核搜索遇非成核首段永久卡死（`W11b`）；分支 A 单段脱离 vs 两段破坏（`W11c`）；途径二离开回拉升级甲方缺失而乙方需跳空（`W11d`）。 |
| 66 | M8 | `Level/SameLevel.lean` | `sameLevelRule` | 必选 | `SEPARATED` | 甲方在所有层级重复三段截块、违背 `[038:26]` 向上不考虑原则；乙方限定 `k == atDepth` 但在 `atDepth > 0` 时第 0 层无规则导致永久停摆（见证 `W12a`/`W12b`）。 |
| 67 | M8 | `Level/NoCap.lean` | `noCapRule` | 必选 | `SEPARATED` | 甲方从 `firstSeedFrom` 起遇单段脱离核即截块；乙方要求精确从 `i` 成核且须发生跳空两段破坏或后枢波动重叠（见证 `W13`）。 |
| 68 | M9 | `Level/TrendType.lean` | `TrendKind` | 必选 | `EQUIV` | 三态枚举 `consolidation/upTrend/downTrend` 与 `consolidation/uptrend/downtrend` 一一对应。 |
| 69 | M9 | `Level/TrendType.lean` | `classifyTrend` | 必选 | `EQUIV` | 在合法完成块的中枢序列上，双方均按 0/1/≥2 个中枢及相邻波动区间严格分离分类，输出恒等（乙方外包 `Finished` 证明束）。 |
| 70 | M9 | `Level/TrendType.lean` | `TrendFormingProspect` | 必选 | `SEPARATED` | **高危**：离开段域完全不交（甲方要求离开段在核末覆盖位且重叠核，乙方要求离开段在 `z.stop` 且跳空离核）；且甲方不要求后续推进创新极值，乙方强制要求（见证 `W14a`/`W14b`）。 |
| 71 | M15 | `Signal/Phase.lean` | `Phase` | 必选 | `EQUIV` | 三阶段状态枚举 `zhongYin/oscillation/leaving` 与 `transition/oscillation/departure` 一一对应。 |
| 72 | M15 | `Signal/Phase.lean` | `phaseAt` | 必选 | `SEPARATED` | 甲方永久锁死转折后首个中枢导致进入第二新中枢仍判 `leaving` 且越界返回全函数值；乙方按分解中枢账取最近中枢、返回 `Option Phase` 并以跨核端点判离开（见证 `W15`）。 |
| 73 | M15 | `Signal/Points.lean` | `StrengthJudge` | 必选 | `SEPARATED` | 信息承载面不同：甲方传 `(List Seg, Center, Nat, Nat)` 无分解上下文，乙方传 `(Decomposition, Center, Seg, Seg)` 无段下标。 |
| 74 | M15 | `Signal/Points.lean` | `BreakoutRetest` | 必选 | `SEPARATED` | 甲方仅检 `bound < leave.hi`（允许起于界外的二次回抽与冲高回落刺破）；乙方要求 `entry ≤ bound < exit`（拒收跳空突破，见证 `W16a`/`W16b`）。 |
| 75 | M15 | `Signal/Points.lean` | `isFirstBuy` | 必选 | `SEPARATED` | **高危**：离开段阈甲方要求 `< DD`、乙方仅需 `exit < ZD`；甲方未校 `prev` 真实性（伪造前枢可把盘整误判为一买）、`c.first - 1` 存在自然数下溢与方向错配且缺中阴门；乙方 `∃ prior` 可跨回第一中枢前比较（见证 `W17a`/`W17b`）。 |
| 76 | M15 | `Signal/Points.lean` | `isFirstSell` | 必选 | `SEPARATED` | **高危**：`isFirstBuy` 的精确空头对偶，存在完全对称的四重分离（见证 `W17a`/`W17b` 对偶版）。 |
| 77 | M15 | `Signal/Points.lean` | `SecondStrength` | 必选 | `EQUIV` | 三档强弱枚举 `merged/rising/weak` 与 `strongest/intermediate/weak` 一一对应。 |
| 78 | M15 | `Signal/Points.lean` | `secondBuyStrength`/`secondSellStrength` 对 `secondStrength?` | 辅助 | `SEPARATED` | **高危**：乙方 `!ahead` 写出非严格不等 `ZG ≤ test.lo`，把单点触及 `ZG` 误判为最强二三买合一（违背分叉 4 与 `[054:24]`）；另甲方比区间极值、乙方比实际终点价（见证 `W18`）。 |
| 79 | M15 | `Signal/Points.lean` | `isSecondBuy` | 必选 | `SEPARATED` | 虽均采版本四（一买后上、下回试结束且处中阴），但直接继承 `isFirstBuy` 的 `DD`/`ZD`、伪造 `prev` 与比较段分离（见证 `W17a`/`W17b`）。 |
| 80 | M15 | `Signal/Points.lean` | `isSecondSell` | 必选 | `SEPARATED` | `isSecondBuy` 的空头对偶，继承 `isFirstSell` 全部结构分离（见证 `W17a` 对偶版）。 |
| 81 | M15 | `Signal/Points.lean` | `isThirdBuy` | 必选 | `SEPARATED` | **高危**：甲方允许第 3 成核段兼作离开段（匹配 `[054:24]`）且不限 `lvl > 0`、无阶段门；乙方强求 `z.start + 3 ≤ i`（拒收第 3 段离开）与 `0 < d.depth`、需 `entry ≤ ZG < exit`（见证 `W19b`/`W19c`）。 |
| 82 | M15 | `Signal/Points.lean` | `isThirdSell` | 必选 | `SEPARATED` | **高危**：在缠师 `[054:24]` `d1 > g2` 标杆例中甲方判真、乙方因 `3 ≤ 2` 判假（见证 `W19a`）。 |
| 83 | M15 | `Signal/Points.lean` | `isPseudoThirdBuy` | 必选 | `SEPARATED` | 底层 `depth = 0` 下同样存在第 3 成核段兼离开段、`entry ≤ ZG < exit` 与 `phaseAt` 门控分离（见证 `W19b`）。 |
| 84 | M15 | `Signal/Points.lean` | `isPseudoThirdSell` | 必选 | `SEPARATED` | 底层 `depth = 0` 下在 `[054:24]` 标杆例上甲方判真、乙方判假（见证 `W19a`）。 |
| 85 | M15 | `Signal/Points.lean` | `isOscillationBuy` | 必选 | `SEPARATED` | 甲方在触底段 `k` 当下在线判真（按 `lo ≤ ZD`）；乙方要求后继反弹段 `items[cut]` 已出现且端点严格相等 `p = q`（延迟 1 步且禁跳空），按 `exit ≤ ZD` 判（见证 `W20a`/`W20b`）。 |
| 86 | M15 | `Signal/Points.lean` | `isOscillationSell` | 必选 | `SEPARATED` | `isOscillationBuy` 的空头对偶（见证 `W20c`）。 |

---

## 二、等价对（`EQUIV`）翻译映射

以下覆盖全部 **46** 组 `EQUIV` 定义对的载体互转函数与待机检 Lean 4.36.0 等价引理陈述。设公共价格载体 `P` 同时具备 `[LinearOrder P]`（并由此派生对应的 `Std.LinearOrderPackage P`，记为 `instPkgOfLinearOrder P`）。

### 2.1 基础载体翻译函数

```lean
-- 载体桥接：从 Mathlib LinearOrder 派生 Std.LinearOrderPackage
def toOrderPkg (P : Type u) [LinearOrder P] : Std.LinearOrderPackage P :=
  Astra.priceOrder P

-- M0 Bar 互转（互逆双射）
def mapBar (b : Opus.Bar P) : Astra.Bar P := ⟨b.lo, b.hi, b.valid⟩
def unmapBar (b : Astra.Bar P) : Opus.Bar P := ⟨b.lo, b.hi, b.ordered⟩

-- M0 Quantizer 互转
def mapQuantizer (q : Opus.Quantizer P Q) : Astra.Quantizer P Q :=
  ⟨q.toFun, fun h => q.mono _ _ h⟩

-- M1 CoreHull 与 RelPos 互转
def mapCoreHull (c : Opus.CoreHull P) : Astra.CoreHull P :=
  ⟨mapBar c.core, mapBar c.hull, c.inside⟩

def mapRelPos : Opus.RelPos → Astra.RelPos
  | .sepUp => .separatedUp
  | .sepDown => .separatedDown
  | .expandUp => .expansionUp
  | .expandDown => .expansionDown
  | .coreOverlap => .coresOverlap

-- M3 对偶价格桥接：OrderDual P ≃o PriceDual P
def dualBridge (x : OrderDual P) : Astra.PriceDual P := OrderDual.ofDual x

-- M4 Dir / Span / Seg 互转
def mapDir : Opus.Dir → Astra.Dir | .up => .up | .down => .down
def mapSpan (s : Opus.Span) : Astra.Span := ⟨s.start, s.stop, s.le⟩
def mapSeg (s : Opus.Seg P) : Astra.Seg P := ⟨mapDir s.dir, mapBar s.range, mapSpan s.span⟩

-- M9 TrendKind 与 M15 Phase / SecondStrength 枚举互转
def mapTrendKind : Opus.TrendKind → Astra.TrendKind
  | .consolidation => .consolidation
  | .upTrend => .uptrend
  | .downTrend => .downtrend

def mapPhase : Opus.Phase → Astra.Phase
  | .zhongYin => .transition
  | .oscillation => .oscillation
  | .leaving => .departure

def mapSecondStrength : Opus.SecondStrength → Astra.SecondStrength
  | .merged => .strongest
  | .rising => .intermediate
  | .weak => .weak
```

### 2.2 逐模块待机检 Lean 等价引理陈述（46 组全覆盖）

1. **M0（第 1 至 6 项）**：
   - `Bar`：`∀ b : Opus.Bar P, unmapBar (mapBar b) = b` 与逆方向。
   - `Bar.contains`：`∀ a b : Opus.Bar P, a.contains b ↔ (mapBar a).contains (mapBar b)`。
   - `Bar.strictUp`：`∀ a b : Opus.Bar P, a.strictUp b ↔ (mapBar a).strictUp (mapBar b)`（由 `And.comm`）。
   - `Bar.strictDown`：`∀ a b : Opus.Bar P, a.strictDown b ↔ (mapBar a).strictDown (mapBar b)`（由 `And.comm`）。
   - `Quantizer` / `Quantizer.mapBar`：`∀ q b, mapBar (q.mapBar b) = (mapQuantizer q).mapBar (mapBar b)`。

2. **M1（第 7 至 17 项）**：
   - `overlaps`：`∀ a b, Opus.overlaps a b ↔ Astra.overlaps (mapBar a) (mapBar b)`。
   - `overlapsList`（一维 Helly 等价，限定共享非空域 `a :: bs`）：
     `∀ (a : Opus.Bar P) (bs : List (Opus.Bar P)), Opus.overlapsList (a :: bs) ↔ Astra.overlapsList (mapBar a) (bs.map mapBar)`。
   - `interInterval`：`∀ a b h, mapBar (Opus.interInterval a b h) = Astra.interInterval (mapBar a) (mapBar b) h'`。
   - `hullInterval`：`∀ b rest, mapBar (Opus.hullInterval b rest) = Astra.hullInterval (mapBar b) (rest.map mapBar)`。
   - `gapUp` / `gapDown` / `strictAbove` / `strictBelow`：各自按 `mapBar` 直接 `Iff.rfl`。
   - `CoreHull`：`mapCoreHull` 为双射。
   - `RelPos` / `relPos`（依赖 `CoreHull.inside` 核含于波动区间不变式）：
     `∀ x y : Opus.CoreHull P, mapRelPos (Opus.relPos x y) = Astra.relPos (mapCoreHull x) (mapCoreHull y)`。

3. **M2（第 18 至 22 项）**：
   - `History`：`Opus.History α = Astra.History α`（`rfl`）。
   - `IsPrefix`：`∀ h₁ h₂ : List α, Opus.IsPrefix h₁ h₂ ↔ Astra.IsPrefix h₁ h₂`。
   - `Confirmed`：`∀ f h, Opus.Confirmed f h ↔ Astra.Confirmed f h`（`Iff.rfl`）。
   - `DelayedCausal`（利用 `h.length ≤ i + k → h.take (i + k + 1) = h`）：
     `∀ (k : Nat) (f : List α → Nat → β), Opus.DelayedCausal k f ↔ Astra.DelayedCausal f k`。
   - `LimitStable`（存在投影等价，且 `streamPrefix s n = List.ofFn (fun i : Fin n => s i.val)`）：
     `∀ f s, Opus.LimitStable f s ↔ ∃ v : β, Astra.LimitStable f s v`。

4. **M3（第 25 至 27 项）**：
   - `dualBar`：`∀ b : Opus.Bar P, (Opus.dualBar b).lo = OrderDual.toDual b.hi ∧ (Astra.dualBar (mapBar b)).lo = Astra.asDual b.hi`，且经 `dualBridge` 与 `mapBar` 交换。
   - `OrderEmb`（在线性序上 `le_iff ↔ strict`）：
     `∀ f : P → Q, (∀ x y, f x ≤ f y ↔ x ≤ y) ↔ (∀ x y, x < y → f x < f y)`。
   - `mapBarEmb`：`∀ e b, mapBar (Opus.mapBarEmb e b) = Astra.mapBarEmb (mapOrderEmb e) (mapBar b)`。

5. **M4（第 29 至 34、36、42 项）**：
   - `Dir` / `Dir.flip`：`∀ d, mapDir d.flip = (mapDir d).flip`。
   - `Span` / `Seg` / `Seg.mapEmb` / `dualSeg`：`mapSpan`、`mapSeg` 为双射且与 `mapEmb`、`dualSeg` 交换。
   - `dualAltSeq`（导出段表层等价）：
     `∀ a : Opus.AltSeq P, (Opus.dualAltSeq a).segs.map mapDualSeg = (Astra.dualAltSeq (toAstraAlt a)).items`（对任意非空 `a`，以及空表上导出段列表均为空 `[]`）。
   - `MultiAddress`（在共享的零起点 `NestedCuts n` 与 `i : Fin n` 上）：
     `∀ (nc : Astra.NestedCuts n) (i : Fin n), Opus.MultiAddress (toOpusNested nc) i.val = Astra.MultiAddress nc i`。

6. **M5（第 43 至 48 项）**：
   - `CanSeedCenter`：`∀ (xs : Astra.AltSeq P) (i : Nat) (h : i + 2 < xs.items.length), Opus.CanSeedCenter (unmapSeg xs.items[i]) (unmapSeg xs.items[i+1]) (unmapSeg xs.items[i+2]) ↔ Astra.CanSeedCenter xs i = true`。
   - `Center` 与 `Center.core`（在 `xs : Astra.AltSeq P` 上，`WellFormed` 对应 `extract = cover` 的双射）：
     设 `embedCenter (z : Astra.Center P) : Opus.Center P := ⟨z.start, z.cover.length, by simp [Astra.Center.cover], unmapCoreHull z.zone⟩`，则：
     `∀ (xs : Astra.AltSeq P) (z : Astra.Center P), z.stop ≤ xs.items.length ∧ xs.items.extract z.start z.stop = z.cover → (embedCenter z).WellFormed (xs.items.map unmapSeg)`；反之任意满足 `c.WellFormed (xs.items.map unmapSeg)` 的 `c : Opus.Center P` 唯一确定 `Astra.Center.window? xs.items c.first (c.first + c.count) = some z` 且 `mapBar c.core = z.core`、`mapCoreHull c.ch = z.zone`。
   - `Center.extendsWith` / `Center.leavesUp` / `Center.leavesDown`：在上述 `embedCenter` 对应下逐点 `↔` 恒等。

7. **M6（第 52、59、60 项）**：
   - `Level`：`Opus.Level base ≃ Astra.Level base`（`⟨fun l => ⟨l.depth⟩, fun l => ⟨l.depth⟩, ...⟩`）。
   - `LevelTower.cuts` / `LevelTower.sameCuts`：在双方均可构造的非空逐级原始切点对应塔 `t_op ↔ t_as` 上，`t_op.cuts = t_as.cuts`，从而 `t1_op.sameCuts t2_op ↔ t1_as.sameCuts t2_as`。

8. **M9（第 68、69 项）**：
   - `TrendKind`：`mapTrendKind` 为三元双射。
   - `classifyTrend`：对任意 `b : Astra.Finished s`，
     `Option.map mapTrendKind (Opus.classifyTrend (b.centers.map embedCenter)) = Astra.classifyTrend b`。

9. **M15（第 71、77 项）**：
   - `Phase`：`mapPhase` 为三元双射。
   - `SecondStrength`：`mapSecondStrength` 为三元双射。

---

## 三、分离对（`SEPARATED`）最小有限见证与裁定

下面针对全部 **37** 处 `SEPARATED` 定义对，归纳为 **20** 组具体有限数值见证（均在 `Int`/`Nat` 上给出显式值，可直接用 Lean 4 `decide` 核验一真一假或两输出不等），逐条给出裁定结论与 `Chan/Audit/Separation/` 入库条目清单。

约定简记：段 `(d, [l, h], [s, e])` 表示方向 `d ∈ {up, down}`、值域 `Bar Int = ⟨l, h, _⟩`、来源跨度 `Span = ⟨s, e, _⟩`；若未特别说明，第 `i` 段的跨度取 `[i, i]`。

### 3.1 逐组最小有限见证与裁定（`W1` 至 `W20`）

#### `W1`：M2 `RevisionCount`（对应表第 23 项）
- **最小有限见证**：单层（层号 `0`），前缀 `h = [0, 1]` 对应两个稳定地址对象 `k = 0 ↦ some 10`、`k = 1 ↦ some 20`（列表表示 `[[10, 20]]`）；延拓 `h ++ [2]` 撤销 `k = 0`（`0 ↦ none`）而保留 `k = 1 ↦ some 20`（列表表示 `[[20]]`）。
- **双方核验结果**：
  - 甲方 `Opus.RevisionCount.measure [[10, 20]] [[20]]` = `{ rewritten := 2, deepest := 1 }`（索引错位导致未改动的 `20` 被重复计为改写，且层深自 1 起计）。
  - 乙方 `Astra.RevisionCount [0, 1] [2] [0, 1] _ (fun _ => 0) readAt` = `(1, some 0)`（仅计真正被撤销的 `k = 0`，且用 `Option Nat` 自 0 起计层）。
- **裁定**：**融合修复（主体采乙方）**。按 `03-informal-specs.md` M2 及 `[099:22]` 结合律拆改语义，前端合并或拆分会移动后续稳定结构的列表下标，按位比对必然虚增修订数。最终合稿采用甲方命名结构形态 `{ rewritten : Nat, deepest : Option Nat }`，配合乙方基于稳定地址 `Key`（如 `(level, origStart)`）的精确测量函数。

#### `W2`：M2 `PendingCandidates`（对应表第 24 项）
- **最小有限见证**：`α = Nat`，`β = Nat`，`h = []`，`legal _ = true`，`f xs = min xs.length 2`，有限样本 `U = [[], [0], [1]]`。
- **双方核验结果**：
  - 甲方 `Opus.PendingCandidates (fun _ => true) f [] U` = `[0, 1, 1]`（长度 3、含重复项 `1`，且遗漏由 `tail = [0, 0]` 可达的 `2`）。
  - 乙方 `Astra.PendingCandidates f [] (fun _ => True)` 要求 `values.Nodup` 且 `∀ b, b ∈ values ↔ b ≤ 2`，故 `2 ∈ values` 且无重复（`[0, 1, 2]` 的排列）。
- **裁定**：**采乙方主定义，保留甲方作有限采样辅助**。`03-informal-specs.md` 明确要求刻画"所有在至少一条合法延拓下可能实现的有限候选结果集合"，乙方 `FiniteImage` 给出精确可达像集（且反哺 `Confirmed` 的可判定性）；甲方按有限样本收集的去重版本可作为辅助函数 `sampleCandidatesOn` 留供小模型穷举。

#### `W3`：M3 `SmallModel`（对应表第 28 项）
- **最小有限见证**：`bars : List (Bar Int) = [⟨10, 20⟩, ⟨20, 30⟩]`（长度 `n = 2`）。
- **双方核验结果**：
  - 乙方 `Astra.SmallModel bars` 返回函数 `0 ↦ (0, 1), 1 ↦ (1, 3)`（类型 `Fin 2 → Fin 5 × Fin 5`，因未去重端点表 `[10, 20, 20, 30]` 使 `rank 30 = 3` 跳过 `2`，且返回类型未携带 `lo ≤ hi` 不变式）。
  - 甲方 `Opus.SmallModel 2 3` 为结构载体，允许致密表示 `[(0, 1), (1, 2)]` 并携带 `c.1 ≤ c.2 ∧ c.2 < 3`，但缺少从 `List (Bar P)` 到 `SmallModel` 的压缩算子。
- **裁定**：**融合修复**。保留甲方 `SmallModel (n bound : Nat)` 作为小模型载体结构（改存 `Bar (Fin bound)` 或带 `lo ≤ hi < bound` 的列表以便穷举），并吸收乙方秩压缩思想提供 `SmallModel.compress (bars : List (Bar P)) : SmallModel bars.length (2 * bars.length + 1)`（且对端点去重以实现紧致压缩）。

#### `W4`：M4 `AltSeq`（对应表第 35 项）
- **最小有限见证**：`P = Int`，空段列 `n = 0`。
- **双方核验结果**：
  - 甲方 `a₁ = Opus.AltSeq.mk .up []` 与 `a₂ = Opus.AltSeq.mk .down []` 导出相同空段表 `[]`，却 `a₁ ≠ a₂` 且 `Opus.dualAltSeq a₁ = a₂ ≠ a₁`。
  - 乙方 `Astra.AltSeq` 在 `items = []` 上唯一（任意两个空 `AltSeq` 相等），且 `Astra.dualAltSeq empty = empty` 自对偶。
- **裁定**：**采乙方**。`03-informal-specs.md` 定义 `AltSeq` 为满足相邻方向严格相反的段有限列表；空序列不应携带幽灵方向位，且采用 `List.IsChain (fun a b => a.dir ≠ b.dir)` 可直接对接 `04-interface-constraints.md` 推荐载体并在 M5 至 M15 全链条复用 `AltSeq`（甲方在 M5 至 M15 事实上被迫放弃了自建的 `AltSeq`）。

#### `W5`：M4 `Zigzag` 与 `Zigzag.toAltSeq`（对应表第 37、38 项）
- **最小有限见证**：
  - `W5a`（非极值共端，`[070:48]` 场景）：`s0 = (up, [0, 10])`，`s1 = (down, [2, 8])`。甲方配 `ends = [(0, 6), (6, 2)]` 使 `Opus.IsZigzag = True`；乙方检 `s0.zigEnd = 10 ≠ 8 = s1.zigStart` 判 `False`。
  - `W5b`（方向倒置端点与非单射性）：单段 `s0 = (up, [0, 10])`。甲方同时接受 `z₁ = ⟨alt, [(9, 1)]⟩`（向上段起点 `9 > 1` 终点！）与 `z₂ = ⟨alt, [(0, 10)]⟩`，且 `z₁ ≠ z₂` 而 `z₁.toAltSeq = z₂.toAltSeq`；乙方纤维唯一，`toAltSeq` 严格单射。
- **裁定**：**采乙方主定义，按需单列带端点结构**。清单 B-9 与 `04-interface-constraints.md` 明确将 `Zigzag` 定位为 `AltSeq` 的**子类型**、`Zigzag.toAltSeq` 为**遗忘嵌入**（数学上嵌入须单射），且经典极值折线恰是 `[067:16]` 成立、在 `[070:48]` 断裂的对照子类型。若 M15 需显式起止价，应像乙方 `Signal/Phase.lean` 的 `Endpoints` 那样作为带方向单调性 `entry ≤ exit` / `exit ≤ entry` 的独立附加结构提供，不混入 `Zigzag`。

#### `W6`：M4 `CutChain` 与 `NestedCuts`（对应表第 39、40 项）
- **最小有限见证**：`N = 6`，切点表 `cuts = [2, 5]`（或 `cuts = []`），两层嵌套 `[[2, 5], [2, 5]]`。
- **双方核验结果**：
  - 甲方 `StrictIncr [2, 5]` 与 `∀ c ∈ [2, 5], c ≤ 6` 均真，构成合法 `Opus.CutChain 6` 与 `Opus.NestedCuts 6`。
  - 乙方 `starts : marks.head? = some 0` 在 `[2, 5]`（`some 2 ≠ some 0`）与 `[]`（`none ≠ some 0`）上均假。
- **裁定**：**融合修复（倾向乙方严格非空，零起点单列或显式标记）**。`03-informal-specs.md` 写"首切点在合法范围内、末切点不超过 `N`"（允许局部区间起点如转折后 `origin` 起切，但空表无首切点）。建议 `CutChain N` 要求 `cuts ≠ []`、`List.IsChain (· < ·) cuts`、`∀ c ∈ cuts, c ≤ N`，再在 `LevelTower` 上加 `AnchoredZero`（`cuts.head? = some 0`），兼顾全塔与局部子段切点链。

#### `W7`：M4 `Laminar`（对应表第 41 项）
- **最小有限见证**：`blocks = [(3, 3)]`（空半开区间）或 `blocks = [(1, 4), (3, 2)]`（含倒置区间 `(3, 2)`）。
- **双方核验结果**：
  - 甲方 `Opus.Laminar [(3, 3)]` 因 `blockWithin (3, 3) (3, 3)` 恒真而判 `True`；`Opus.Laminar [(1, 4), (3, 2)]` 因 `blockWithin (3, 2) (1, 4)` 即 `1 ≤ 3 ∧ 2 ≤ 4` 成立而判 `True`。
  - 乙方 `Astra.Laminar` 显式要求 `∀ b ∈ blocks, b.1 < b.2`，对两者均判 `False`。
- **裁定**：**采乙方**。左闭右开非空块必须满足 `b.1 < b.2`，甲方遗漏该约束构成明确边界缺陷。

#### `W8`：M5 `Center.thirdBuyEvent`、`Center.thirdSellEvent`、`Center.destroyed`（对应表第 49、50、51 项，高危）
- **最小有限见证**：
  - `W8a`（连续向上第三类买点）：`xs = [(down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[10,30]), (down,[25,30])]`。初核 `[ZD, ZG] = [10, 20]`，离开段 `s3 = (up,[10,30])` 起于核内并严格越过 `20`，回试段 `s4 = (down,[25,30])` 低点 `25 > 20`。
    - 甲方：`c = ⟨0, 3, _, [10,20], [10,20]⟩`，`Opus.Center.thirdBuyEvent c s3 s4 = True`，`destroyed = True`。
    - 乙方：若 `z` 覆盖 `[0, 3)`，`z.leavesUp s3` 即 `20 < 10` 为 `False`；若 `z'` 覆盖 `[0, 4)`，`xs[4] = s4` 为 `down` 且无 `xs[5]` 亦为 `False`（即使追加 `s5 = (up,[25,35])`，`xs[4].dir = down ≠ up` 仍为 `False`）。对 `xs` 内所有合法 `Center`，`Astra.Center.thirdBuyEvent = False`、`destroyed = False`。
  - `W8b`（缠师 `[054:24]` `d1 > g2` 标杆回归例，向下第三类卖点）：`xs = [(up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[5,20]), (up,[5,8])]`（核 `[d1, g1] = [10, 20]`，`s3` 跌至 `d2 = 5 < 10`，`s4` 回抽至 `g2 = 8 < 10`）。
    - 甲方：`Opus.Center.thirdSellEvent c s3 s4 = True`，`destroyed = True`。
    - 乙方：`z.leavesDown s3` 即 `20 < 10` 为 `False`，`Astra.Center.thirdSellEvent = False`、`destroyed = False`。
- **裁定**：**融合修复（核心几何采甲方，位置锚定吸收乙方并修补连续与跳空两类离开）**。乙方误将 `leavesUp`（整段脱离核，`020:56`）套用到离开段本身，导致一切无跳空连续走势（含 `[054:24]` 标杆例）永远无法触发中枢破坏，并连锁污染其 M7 `carryNineRule`、M8 `noCapRule` 与 M9 `TrendFormingProspect`。融合版应严格区分：离开段满足 `s.dir = up ∧ ZG < s.range.hi`（允许起于核内或跳空高于 `ZG`），回试段 `back` 紧随其后且满足 `c.leavesUp back`（`ZG < back.range.lo`，严格不等按分叉 4 与 `[054:24]`）；向下对称；并提供序列级定位谓词支持 `k = c.stop - 1`（连续重叠离开，含 `[054:24]` 第 3 段兼离开）与 `k = c.stop`（跳空离开）两种合法衔接。

#### `W9`：M6 `BlockRule`、`BlockRule.coarsen`、`InterfaceLaws`、`CarryBounded`、`DeterministicBlocks`（对应表第 53 至 57 项）
- **最小有限见证**：
  - `W9a`（`BlockRule.coarsen` 越界）：`xs = [(up,[10,20])]`（长度 1），`i = 0, j = 5`。甲方 `coarsen r (blockOf xs 0 5) = some (up,[10,20])`；乙方 `coarsen xs 0 5 = none`。
  - `W9b`（`InterfaceLaws` 稳定律与 `BlockRule` 表达力）：`ctx = [(up,[10,20]), (down,[10,20]), (up,[10,20])]`（3 段），`ext` 为 6 段同范围交替段（`ctx ++ ext` 共 9 段），规则取 `CarryNine(seeded / finishAtSeed = true, afterNine / false, mayIncludeFirst / false)`。甲方 `accepts ctx 0 3 = true` 但 `accepts (ctx ++ ext) 0 3 = false`（进位改为 `0..9`），直接证伪甲方自身 `InterfaceLaws.confirmedStable`；乙方 `rank 0 ctx [] 0 3 = some 0` 而 `confirmed = false`，故乙方 `InterfaceLaws.stable = true`。
  - `W9c`（`CarryBounded` 在 `K = bound = 9` 下）：10 段序列（对应 `[057:42]` 进入段加九段延伸）`xs = [(down,[0,5]), (up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[10,20])]`，规则接受块 `[0, 10)`。块内最长 `ExtRun` 长度为 `9`（从下标 1 起），故甲方 `Opus.CarryBounded r 9` 在此块上为 `True`；乙方检 `10 ≤ 0 + 9` 为 `False`。
  - `W9d`（`DeterministicBlocks` 在 `sameLevelRule` 上）：4 段序列 `xs = [(up,[0,1]), (down,[10,20]), (up,[10,20]), (down,[10,20])]`。对甲方 `sameLevelRule`，`i = 0` 不成块（`TailStart ... 0 = True`），而 `i' = 1 ≥ 0` 处 `[1, 4)` 成块（`TailStart ... 1 = False`），故甲方 `Opus.DeterministicBlocks sameLevelRule`（`tailExhaust`）为 **`False`**；乙方 `Astra.DeterministicBlocks sameLevelRule 0 xs [0]` 为 **`True`**。
- **裁定**：
  - `BlockRule`：**采乙方核心骨架**（保留层深 `k`、历史切点 `past`、优先级 `rank : Option Nat` 与独立 `confirmed : Bool`），并视需要保留可配置方向映射 `blockDir`。只有分离 `rank.isSome`（合法）与 `preferred`（占优），才满足 B-4、B-32、M7 与 `[038:26]`。
  - `BlockRule.coarsen`：**采乙方越界守卫**（`i < j ∧ j ≤ xs.length` 否则 `none`）。
  - `InterfaceLaws`：**融合修复**。采用乙方的"仅对 `confirmed` 块要求前缀稳定"与 `AltSeq` 域，但同时提供全称 `Prop` 结构（供定理层引用）与逐点 `Bool` 核验函数（供有限模型 `decide` 核验）。
  - `CarryBounded`：**融合修复（主口径采甲方 `ExtRun ≤ K`）**。`[057:42]` 10 段块与途径二双枢波动重叠块的总段数均可超过 9，进位有界律实质约束的是**单中枢连续延伸段数不超 `K`**（`ExtRun ≤ K`），而非块总长 `j - i ≤ 9`；同时保留可选块长上界供同级别分解对照。
  - `DeterministicBlocks`：**采乙方切点表级定义并补规则级占优唯一前提**。彻底删除甲方有误的 `TailStart i → TailStart i'` 单调性，将规则级条件定为"凡存在合法终点则占优终点唯一"（用于支撑 `#2318` 唯一性定理）。

#### `W10`：M6 `LevelTower` 与 `ValidDecomp`（对应表第 58、61 项，高危）
- **最小有限见证**：
  - `W10a`（非末尾偶数长度块）：8 段交替序列 `base = [(up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[30,40]), (down,[30,40]), (up,[30,40]), (down,[50,60])]`，切点 `[0, 4, 7]`（块 0 为 4 段中枢 `[0, 4)`、首段 `up`；块 1 为 3 段中枢 `[4, 7)`、首段 `up`）。
    - 甲方：在 `noCapRule` 下 `Opus.ValidDecomp noCapRule base [[0, 4, 7]] = True`（合法构造 `LevelTower`）。
    - 乙方：`Stage.ascend (Stage.bottom base) [0, 4, 7]` 粗化得两段均为 `dir = up`，触发 `blocks[0].dir ≠ blocks[1].dir` 失败，返回 `none`，**无法构造任何含 `[0, 4, 7]` 的 `Astra.LevelTower`**。
  - `W10b`（多合法分解并存）：9 段交替 `[10, 20]`，规则取 `CarryNine(seeded / finishAtSeed = true)`，切点 `[0, 3, 6, 9]`。
    - 甲方：`Opus.carryNineRule` 在 `i = 0` 仅接受 `j = 9`，`Opus.ValidDecomp ... [[0, 3, 6, 9]] = False`。
    - 乙方：`Astra.carryNineRule` 给 `[0, 3)`、`[3, 6)`、`[6, 9)` 赋 `rank = some 0`（合法非占优），且三块均长 3 方向交替，`Astra.ValidDecomp = True`。
- **裁定**：**融合修复（高危缺陷修复）**。保留乙方将"几何可实现塔 `LevelTower`"与"规则合法性 `ValidDecomp`"分层解耦、并强制每层 `raw.length ≥ 2` 的优点；但**必须解除乙方 `Stage.ascend` 对粗化后高阶块强行按首段方向交替的错误假设**（否则 4/6/8/10 段完成块后接任意块均无法成塔，直接与 `CarryNine` 10 段块及 `NoCap` 偶数延伸中枢冲突）。详见第四节轴 U-1 及 4.3 项 1。

#### `W11`：M7 `carryNineRule`（对应表第 65 项，高危）
固定对齐参数：`p_opus = ⟨.coreBroken, .afterNine, .mayIncludeFirst⟩`，`p_astra = ⟨false, false, false⟩`。
- **最小有限见证（四重独立分离）**：
  - `W11a`（9 段单核延伸但 `3+3+3` 三凸包不交）：9 段交替序列 `s0..s2 = [10,20]`（`up,down,up`，凸包 `[10,20]`）、`s3..s5 = [0,10]`（`down,up,down`，每段单点触核 `10`，凸包 `[0,10]`）、`s6..s8 = [20,30]`（`up,down,up`，每段单点触核 `20`，凸包 `[20,30]`）。
    - 甲方：`seedRunLen xs 0 = 9 ≥ 9`，`Opus.carryAccepts p_opus xs 0 9 = true`。
    - 乙方：`overlapsList [10,20] [[0,10], [20,30]]` 即 `20 ≤ 10` 为假，`Astra.nineAt xs 0 = false`，`carryScore p_astra xs [] 0 9 = none`。
  - `W11b`（非成核前导段）：6 段序列 `s0 = (up,[0,5])`，`s1..s3 = [10,20]`（`down,up,down`），`s4 = (up,[25,30])`，`s5 = (down,[26,30])`。
    - 甲方：`firstSeedFrom xs 0 = some 1`，`seedRunLen xs 1 = 3 < 6`，`Opus.carryAccepts p_opus xs 0 4 = true`。
    - 乙方：`seed = 0`，`Center.window? xs 0 j = none`，对所有 `j` 返回 `none`。
  - `W11c`（分支 A `coreBroken`：单段脱离 vs 两段破坏）：4 段序列 `s0..s2 = [10,20]`（`up,down,up`），`s3 = (down,[0,5])`。
    - 甲方：`seedRunLen xs 0 = 3 < 4`，`Opus.carryAccepts p_opus xs 0 3 = true`。
    - 乙方：无 `s4` 无法满足 `z.destroyed xs`，`carryScore p_astra xs [] 0 3 = none`。
  - `W11d`（途径二离开回拉波动重叠升级）：7 段序列 `s0 = (down,[0,20])`，`s1 = (up,[10,20])`，`s2 = (down,[10,20])`（`z` 核 `[10,20]`、波动 `[0,20]`），`s3 = (up,[25,35])`，`s4 = (down,[22,35])`（破坏 `z`），`s5 = (up,[18,30])`，`s6 = (down,[18,30])`（`s4..s6` 成新枢 `next`，核 `[22,30]`、波动 `[18,35]` 与 `[0,20]` 重叠于 `[18,20]`）。
    - 甲方：未实现途径二，`Opus.carryAccepts p_opus xs 0 7 = false`（仅接受 `0..3`）。
    - 乙方：`returningCenter xs z 7 true = true`，`Astra.carryScore p_astra xs [] 0 7 = some 2`（优先确立高级别中枢）。
- **裁定**：**融合修复**。1. 吸收乙方 `nineAt` 强制校验 `3+3+3` 三凸包公共交非空（修正甲方 `W11a` 漏洞，注意在 `AltSeq` 中 9 段单核延伸并不蕴含三凸包有公共交）；2. 吸收甲方 `firstSeedFrom` 允许跨过非成核前导段（修正乙方 `W11b` 永久卡死）；3. 吸收乙方途径二 `returningCenter` 与双层 `rank` 优先级框架（修正甲方缺失 `[020:44]` 途径二升级），但将其内部调用的 `z.destroyed` 与 `leavesUp/Down` 替换为修正后的 M5 连续/跳空通用破坏谓词，并约束第二枢 `next` 自身不得超过 9 段延伸；4. `W11c`（单段脱离 vs 完整三类破坏）并入分支 A 参数化留待 `#2296` 冻结。

#### `W12`：M8 `sameLevelRule`（对应表第 66 项）
- **最小有限见证**：
  - `W12a`（超出目标层）：9 段 `[10,20]` 经第 0 层 `[0, 3, 6, 9]` 粗化为 3 段 `[10,20]`（记为 `xs₁`），考察深度 `k = 1`、`i = 0, j = 3`（目标层 `atDepth = 0`）。甲方 `sameLevelRule.accepts xs₁ 0 3 = true`；乙方 `rank 1 xs₁ [] 0 3 = none`。
  - `W12b`（`atDepth = 1` 停摆）：同上 9 段输入，取 `atDepth = 1`，考察深度 `k = 0`。乙方 `sameLevelRule 1` 在 `k = 0` 对所有 `(i, j)` 返回 `none`，塔永远无法到达第 1 层。
- **裁定**：**融合修复**。严格对照 `[038:26]`（本级不延伸允许盘整接盘整，本级以下允许延伸，本级以上不考虑），将签名定为 `sameLevelRule (atDepth : Nat := 0) (subRule : BlockRule)`：当 `k < atDepth` 委托 `subRule`，当 `k = atDepth` 取三段成核截块，当 `k > atDepth` 返回 `none`。

#### `W13`：M8 `noCapRule`（对应表第 67 项）
- **最小有限见证**：5 段 `[054:24]` 连续破坏序列 `xs = [(up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[5,20]), (up,[5,8])]`（另可取 4 段单脱离序列 `[(up,[10,20]), (down,[10,20]), (up,[10,20]), (down,[0,5])]`）。
- **双方核验结果**：
  - 甲方：在 5 段例中 `seedRunLen = 4 < 5` 得 `noCapAccepts xs 0 4 = true`；在 4 段例中得 `noCapAccepts xs 0 3 = true`。
  - 乙方：在 5 段例中因 M5 跳空缺陷对所有 `j` 均得 `completesUncapped xs 0 j = false`；在 4 段例中因无回试段得 `false`。
- **裁定**：**融合修复**。对照 `03-informal-specs.md` M8（"允许单一中枢无限延伸，仅在核被破坏离开或波动区间重叠时结束中枢，不设九段强制进位上限"），吸收乙方"破坏或后枢波动重叠"双终结条件，并修复 M5 连续破坏与前导 `firstSeedFrom` 搜索。

#### `W14`：M9 `TrendFormingProspect`（对应表第 70 项，高危）
- **最小有限见证**：
  - `W14a`（连续三买加推进）：`xs = [(down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[10,30]), (down,[22,30]), (up,[22,40])]`。甲方取 `c` 覆盖 `[0, 4)`、`k = 3` 判 `True`；乙方因 `s3` 不满足 `z.leavesUp s3` 判 `False`。
  - `W14b`（跳空三买加推进）：`xs = [(down,[10,20]), (up,[10,20]), (down,[10,20]), (up,[25,30]), (down,[26,30]), (up,[26,40])]`。乙方取 `centers = [z]`（`[0, 3)`）、`atCut = 6` 判 `True`；甲方 `c` 只能覆盖 `[0, 3)` 迫使 `k = 2`（`s2` 方向为 `down ≠ up`）判 `False`。
  - 另将 `W14b` 的 `s5` 改为 `(up,[26,29])`（未超 `leave.hi = 30`）：乙方因缺少顺向新高推进判 `False`，而甲方（若在连续版上）不要求突破前高仍判 `True`。
- **裁定**：**融合修复**。采用修复后的 M5 通用第三类事件（同时覆盖连续与跳空离开），并保留乙方"回试后须有顺向段突破离开段极值且期间不回核"的几何推进条件（精准对应 `03-informal-specs.md` "出现第三类事件并继续单向推进"，剥离 `[107:32]` 非背驰动力学条件）。

#### `W15`：M15 `phaseAt`（对应表第 72 项）
- **最小有限见证**：7 段序列，`s0 = (down,[0,5])`（转折段，`turn = 0` / `origin = 1`），中枢一 `s1..s3 = [10,20]`（`up,down,up`），中枢二 `s4..s6 = [30,40]`（`down,up,down`）。查询 `s6` 处阶段（甲方 `turn = 0, k = 6`；乙方 `origin = 1, cut = 7`）。
- **双方核验结果**：
  - 甲方：`firstSeedFrom segs 1 = some 1`、`seedRunLen = 3`，因 `6 ≥ 4` 永久返回 `Phase.leaving`（无视已形成的中枢二）。
  - 乙方：`d.recent 1 7` 取到最近中枢 `z2`（`[4, 7)`），返回 `some Phase.oscillation`。
- **裁定**：**采乙方状态机架构（微调跨核离开条件）**。阶段判定必须追踪分解中自转折以来**最近确立的同级中枢**，并对越界或早于转折起点的查询返回 `Option Phase = none`。

#### `W16`：M15 `BreakoutRetest`（对应表第 74 项）
- **最小有限见证**：
  - `W16a`（跳空突破）：`zone = [10,20]`（`bound = 20`），`s0 = (up,[22,30])` 端点 `(22, 30)`，`s1 = (down,[25,30])` 端点 `(30, 25)`。甲方判 `True`；乙方因 `entry = 22 > 20`（`!ahead .up 22 20` 为假）判 `False`。
  - `W16b`（冲高回落刺破，非极值终点）：`zone = [10,20]`，`s0 = (up,[15,30])` 端点 `(15, 18)`，`s1 = (down,[25,30])`。甲方按 `s0.hi = 30 > 20` 判 `True`；乙方按 `exit = 18 > 20` 判 `False`。
- **裁定**：**融合修复**。`BreakoutRetest` 应像甲方那样剥离 `Decomposition` 成为纯几何模板（输入 `d : Dir`、`zone : Bar P`、段列与位置），同时防止甲方把远在界外的二次回调误判为首次突破（加入"离开段起于 `zone` 内或为其前一段仍触及 `zone` 的首次跳空"约束；端点 `exit` 与极值 `hi/lo` 差异按第四节议题处理）。

#### `W17`：M15 `isFirstBuy`、`isFirstSell`、`isSecondBuy`、`isSecondSell`（对应表第 73、75、76、79、80 项，高危）
- **最小有限见证**：
  - `W17a`（`DD` vs `ZD` 阈分离，同时分离一买与二买）：10 段下跌趋势加反弹回试：
    - 中枢 `A`（`0..3`）：`s0 = (up,[40,50])`，`s1 = (down,[40,50])`，`s2 = (up,[40,50])`（核/波动 `[40,50]`）。
    - 连接段 `b`（`3`）：`s3 = (down,[20,40])`（端点 `(40, 20)`）。
    - 中枢 `B`（`4..7`）：`s4 = (up,[10,25])`，`s5 = (down,[5,20])`，`s6 = (up,[10,20])`（核 `[ZD, ZG] = [10, 20]`，波动 `[DD, GG] = [5, 25]`，满足 `B.gg = 25 < 40 = A.dd` 构成下跌趋势）。
    - 离开段 `c`（`7`）：`s7 = (down,[8,20])`（端点 `(20, 8)`，满足 `DD = 5 < 8 < 10 = ZD`！）。
    - 二买反弹与回试（`8, 9`）：`s8 = (up,[8,15])`，`s9 = (down,[11,15])`。取恒真 `StrengthJudge`。
    - **核验**：在一买位置（甲方 `k = 7`，乙方 `cut = 8`）与二买位置（甲方 `k = 7`，乙方 `cut = 10`），甲方因 `s7.lo = 8 < 5 = DD` 为假对 `isFirstBuy` 与 `isSecondBuy` 均判 **`False`**；乙方因 `exit = 8 < 10 = ZD` 为真对 `isFirstBuy` 与 `isSecondBuy` 均判 **`True`**。
    - 对偶空头见证（`x ↦ 60 - x` 与方向取反）：`A = [10,20]`、`b = (up,[20,40])`、`B` 核 `[40,50]` 波动 `[35,55]`、`c = s7 = (up,[40,52])`（`ZG = 50 < 52 < 55 = GG`）、`s8 = (down,[45,52])`、`s9 = (up,[45,49])`，对 `isFirstSell` 与 `isSecondSell` 甲方均判 `False`、乙方均判 `True`。
  - `W17b`（甲方伪造 `prev` 与自然数下溢，及乙方 `∃ prior` 过宽）：
    - 4 段单中枢盘整 `s0 = (up,[10,20])`，`s1 = (down,[10,20])`，`s2 = (up,[10,20])`，`s3 = (down,[2,15])`。甲方传入伪造 `prev = [⟨99, 3, _, [50,60], [50,60]⟩]`，且 `c.first - 1 = 0 - 1 = 0` 把向上段 `s0` 错传为比较段，仍使 `Opus.isFirstBuy = True`；乙方凭 `Finished` 认证检无两中枢下跌趋势判 `False`。
    - 若在 `W17a` 中令 `s7 = (down,[2,20])`、前段加 `a = (down,[50,60])`，且 `judge` 仅对 `(a, c)` 为真、对 `(b, c)` 为假，则甲方（只比 `b`）判 `False`，乙方（`∃ prior` 命中 `a`）判 `True`。
- **裁定**：**融合修复**。1. **必须采乙方认证块 `Finished` 与中阴阶段门**，堵死甲方伪造 `prev` 与 `c.first - 1` 下溢/反向漏洞；2. **收紧乙方 `∃ prior` 为连接最后两中枢之间的同向段 `b`（位于 `prevLast.stop .. z.start`）**，避免跨回第一中枢前误比；3. 融合 `StrengthJudge` 签名为 `(Decomposition/Tower, Center, Nat, Nat)`，同时提供完整分解上下文与精确段下标；4. 将 `DD`（创新低）与 `ZD`（出核）之争明晰化：形态学结构层只需出核（`< ZD`），把是否创新极值（`< DD`）交由 `StrengthJudge`（下游 `#2322` M17）或显式开关控制（见第四节）。

#### `W18`：M15 `secondBuyStrength`/`secondSellStrength` 对 `secondStrength?`（对应表第 78 项，高危）
- **最小有限见证**：在 `W17a` 中令 `s7 = (down,[3,20])`（低于 `DD = 5`，使双方均认可一买与二买），`s8 = (up,[3,28])`，`s9 = (down,[20,28])`（端点 `(28, 20)`，**低点恰好单点触及 `ZG = 20`**）。
- **双方核验结果**：
  - 甲方 `Opus.secondBuyStrength` 检 `20 < 20` 为假、`3 < 20` 为真，返回 `some .rising`（依次抬高，非二三买合一）。
  - 乙方 `Astra.secondStrength?` 执行 `!ahead .up (edge .up z.core) (edge .down s9.range)` 即 `!(20 < 20) = true`，**误判返回 `some .strongest`（二三买合一）**！
- **裁定**：**采甲方严格不等号口径（修复乙方分叉 4 违约）**。按 `#2295` 分叉 4 与 `[054:24]`，单点触及 `ZG` 属于中枢震荡而不构成第三类买点，因此绝不能判为二三买合一。

#### `W19`：M15 `isThirdBuy`、`isThirdSell`、`isPseudoThirdBuy`、`isPseudoThirdSell`（对应表第 81 至 84 项，高危）
- **最小有限见证**：
  - `W19a`（缠师 `[054:24]` 第 3 段兼离开段标杆例 `d1 = 10 > 8 = g2`）：4 段序列 `s0 = (down,[10,30])`，`s1 = (up,[10,20])`，`s2 = (down,[5,20])`（核 `[d1, g1] = [10, 20]`，第 3 段结束于 `d2 = 5 < 10`），`s3 = (up,[5,8])`（回抽高点 `g2 = 8 < 10`）。
    - 在 `isPseudoThirdSell`（`depth = 0`）与 `isThirdSell`（`depth = 1`，以此 4 段为第 1 级段）上：甲方取 `k = 2` 判 **`True`**；乙方因 `i = 4 - 2 = 2` 违背 `z.start + 3 ≤ i`（`3 ≤ 2`）判 **`False`**。
  - `W19b`（向上对称例）：`s0 = (up,[0,20])`，`s1 = (down,[10,20])`，`s2 = (up,[10,25])`，`s3 = (down,[22,25])`。甲方对 `isThirdBuy`/`isPseudoThirdBuy` 判 `True`；乙方判 `False`。
  - `W19c`（第 0 级分流）：5 段序列 `s0..s2 = [10,20]`（`down,up,down`），`s3 = (up,[10,30])`，`s4 = (down,[25,30])`，层级 `lvl = depth = 0`。甲方 `Opus.isThirdBuy t 0 c 3 = True`；乙方 `Astra.isThirdBuy d 5 = False`（因 `0 < d.depth` 强制路由至 `isPseudoThirdBuy`）。
- **裁定**：**融合修复**。1. **采甲方放宽至 `z.start + 2 ≤ i`**，使缠师 `[054:24]` `d1 > g2` 标杆例（第 3 成核段同时跌破 `ZD` 并紧接不触核回抽）成为正例；2. **采乙方 `0 < d.depth` 与 `d.depth = 0` 互斥分流**（严格落实 B-11 将 `isThirdBuy` 与最低级别 `isPseudoThirdBuy` 分立）；3. **采乙方最近同级中枢检索与 `oscillation → departure` 阶段转换门**（同时在 `k = z.start + 2` 处允许自刚成核瞬态直接转入离开）；4. 保持纯结构定义、绝不加底部特判（落实 B-14，保留 `[086:76]` 作审计反例）。

#### `W20`：M15 `isOscillationBuy` 与 `isOscillationSell`（对应表第 85、86 项）
- **最小有限见证**：
  - `W20a`（在线 vs 延迟 1 步）：5 段序列 `s0 = (down,[0,5])`（转折段），`s1..s3 = [10,20]`（`up,down,up`），`s4 = (down,[8,15])`（触破 `ZD = 10`，尚无后续 `s5`）。在 `s4` 末（甲方 `turn = 0, k = 4`；乙方 `origin = 1, cut = 5`），甲方 `isOscillationBuy = True`；乙方因 `items[5]? = none` 判 `False`。
  - `W20b`（跳空端点不等）：在 `W20a` 后追加 `s5 = (up,[9,18])`（`s4.exit = 8 ≠ 9 = s5.entry`）。甲方判 `True`；乙方因 `p = q` 失败判 `False`。
  - `W20c`（卖侧对偶）：`s0 = (up,[30,35])`，`s1..s3 = [10,20]`（`down,up,down`），`s4 = (up,[15,22])`（无 `s5`）。甲方 `isOscillationSell = True`；乙方判 `False`。
- **裁定**：**融合修复**。按 B-13 与 `[101:42]`，采用乙方基于最近中枢的 `phaseAt = some .oscillation` 门控（修复甲方第一中枢锁死问题），但**去掉乙方强行要求端点相等 `p = q`（与 `AltSeq` 允许跳空矛盾）**，并把"是否要求后继反转段 `b` 已完成（确认版 vs 实时在线版）"显式拆分为在线原语与延迟 1 步确认版（或参数化，见第四节）。

### 3.2 `Chan/Audit/Separation/` 入库条目清单

以下 14 条高价值分离记录建议入库 `formal_math/Chan/Audit/Separation/`（每条含对应 `decide` 机检分离定理，验证甲方与乙方原始语义在有限见证上一真一假）：

| 入库文件名（相对 `Chan/Audit/Separation/`） | 对应模块与定义 | 见证编号 | 权威裁定与锚点 | 状态 |
|---|---|---|---|---|
| `M2_RevisionPositionalVsKey.lean` | M2 `RevisionCount` | `W1` | 融合（采稳定地址 + `Option Nat`），`[099:22]` | 建议入库 |
| `M2_PendingSampleVsExact.lean` | M2 `PendingCandidates` | `W2` | 采乙方精确像集，B-28、`[099:16]` | 建议入库 |
| `M4_AltSeqEmptyPhantomDir.lean` | M4 `AltSeq` | `W4` | 采乙方唯一空列，B-9 | 建议入库 |
| `M4_ZigzagExtremalVsFreeEnds.lean` | M4 `Zigzag`、`toAltSeq` | `W5a`/`W5b` | 采乙方极值子类型嵌入，B-9、`[067:16]`、`[070:48]` | 建议入库 |
| `M4_LaminarEmptyBlock.lean` | M4 `Laminar` | `W7` | 采乙方强制 `b.1 < b.2` | 建议入库 |
| `M5_ThirdEventContinuousVsGap.lean` | M5 `thirdBuyEvent`/`thirdSellEvent`/`destroyed` | `W8a`/`W8b` | 融合修复（连续与跳空兼收），分叉 4、`[054:24]`、`[018:64]` | **高危必入** |
| `M6_InterfaceStabilityAndTailExhaust.lean` | M6 `InterfaceLaws`、`CarryBounded`、`DeterministicBlocks` | `W9b`/`W9c`/`W9d` | 融合（仅 `confirmed` 稳定 + `ExtRun ≤ K` + 切点级占优唯一），`#2318` | **高危必入** |
| `M6_EvenLengthBlockAscend.lean` | M6 `LevelTower`、`ValidDecomp` | `W10a`/`W10b` | 融合修复（解除高阶块首段方向交替锁死），`[038:26]`、`[057:42]` | **高危必入** |
| `M7_CarryNine3x3HullAndPullback.lean` | M7 `carryNineRule` | `W11a` 至 `W11d` | 融合修复（补三凸包交 + 前导搜索 + 通用破坏途径二），`[057:42]`、`[020:44]` | **高危必入** |
| `M8_SameLevelDepthAndNoCap.lean` | M8 `sameLevelRule`、`noCapRule` | `W12a`/`W12b`/`W13` | 融合修复（`atDepth + subRule` + 连续破坏），`[038:26]`、`[018:40]` | 建议入库 |
| `M9_TrendProspectLeaveDomain.lean` | M9 `TrendFormingProspect` | `W14a`/`W14b` | 融合修复（通用离开域 + 顺向推进），B-22、`[107:32]` | 建议入库 |
| `M15_PhaseFirstCenterLockIn.lean` | M15 `phaseAt` | `W15` | 采乙方最近中枢状态机，B-13、`[101:42]` | 建议入库 |
| `M15_FirstBuyDDvsZDAndFakePrev.lean` | M15 `isFirstBuy`/`isFirstSell`/`isSecondBuy`/`isSecondSell` | `W17a`/`W17b` | 融合修复（`Finished` 认证 + `b` 段定位 + 阈参数化），B-4、`[017:60]` | **高危必入** |
| `M15_SecondTouchZGAndThird05424.lean` | M15 `secondStrength?`、`isThirdBuy`/`isThirdSell`/`isOscillation*` | `W18`/`W19a`/`W20a` | 修复乙方 `ZG` 等号违约与 `[054:24]` 第 3 段离开，分叉 4、B-11、`[054:24]` | **高危必入** |

---

## 四、原典未定对（`UNDECIDED`）与参数化/升级处置

### 4.1 明确判为 `UNDECIDED` 的 3 项定义

1. **M6 `IsCanonical` 与 `CanonicalDecomp`（表第 62、63 项）**
   - **未定实质**：`[038:18]`、`[101:52]` 要求分解唯一，`[099:22]`、`[099:26]` 要求"首先保证高级别中枢成立，在这前提下根据结合律使连接中枢的走势最完美"，但原典从未给出形式化的全局优化目标函数或平票决胜次序。
   - **双方暴露的缺口**：甲方仅写"尾部穷尽"，连 `#2318` 已证伪的 8 段 `3+5` 与 `5+3` 也不能分开；乙方采用"逐切点局部左至右唯一最大 `rank`"（`DeterministicBlocks`），可解决 `3+5` 与 `5+3` 局部歧义，却**无法表达 `[099:22]`/`[099:26]` 的向后结合律重构**（例如前段已按 `c+d+e` 成块，后续扩展到 9 段要求回头拆开前块以保 5 分钟中枢）。
   - **处置方案**：在 `decl/fm10c-core` 中将规范性谓词**参数化**为两层接口：
     - 规则接口保留 `rank` 与 `confirmed`，提供默认声明式谓词 `IsLocalCanonical`（每步唯一占优终点加尾部穷尽加顶层不可再分，满足 B-32 声明式刻画且不等于算法输出）；
     - 另提供全局偏好参数化谓词 `IsGlobalCanonical (pref : LevelTower r base → LevelTower r base → Prop)`（在全体 `ValidDecomp` 中极优且无更优合法分解），把"局部贪心 vs 全局回溯"的最终选择保留到 **`#2296` 冻结**，并**标记 `needs-fable`** 交由数学深审（检验全局回溯下在线稳定性 `Confirmed` 与唯一性前提是否相容）。

2. **M7 `CarryNineParams`（表第 64 项，连带影响 `carryNineRule`）**
   - **未定实质**：`#2318` 实测确认原典在以下三处留白，且本次双轨盲写进一步暴露双方连分支 B 的候选集合都不一致：
     - **分支 A（九段前成块时机）**：三段成核即成块（`seeded`）、单段不与核重叠即成块（甲方 `coreBroken`）、发生完整第三类破坏才成块（乙方 `finishAtSeed = false`）共 **3 档**。
     - **分支 B（九段 `3+3+3` 进位后的重启策略）**：止于第 9 段末从第 10 段起核（甲方 `afterNine` / 乙方 `entryAfterCarry = false`）、第 10 段强制作为新块进入段从第 11 段起核（乙方 `entryAfterCarry = true`）、当前块延展至第 9 段后下一个成核点（甲方 `atNextSeed`）、以及进位后继续围绕新生成的上级核心延伸共 **4 档**（前三档可直接在单层规则实现）。
     - **分支 C（成核三段与进入段约定）**：成核三段可含块首段且允许跳过非成核前导段（`mayIncludeFirst`）、块首段强制为独立进入段且从 `i + 1` 起搜索成核（`requireEntry`）、以及严格固定从 `i` 或 `i + 1` 成核（不跳前导段）。
   - **处置方案**：合稿中**绝不硬编码默认裁定**，将 `CarryNineParams` 扩展为显式三枚举结构（`TimingPolicy` 三态、`RestartPolicy` 三态、`EntryPolicy` 二态加可选前导搜索开关），全部保留到 **`#2296` 冻结** 时拍定主线默认值，并**标记 `needs-fable`**（特别需深审分支 B 中 `atNextSeed` 与 `entryAfterCarry` 是否满足 `InterfaceLaws` 确认稳定律及进位有界律）。

### 4.2 从分离对提炼的 4 条关联未定数学轴（参数化 / `needs-fable` 处置）

| 轴号 | 关联模块与定义 | 原典未定实质 | `#2296` 参数化策略 | 是否需 `needs-fable` |
|---|---|---|---|---|
| U-1 | M6 `LevelTower`、`BlockRule.coarsen` | 偶数长度完成块（4/6/8/10 段，如 `[057:42]` 10 段块与 `NoCap` 4 段中枢）粗化为上级段后，若取首段方向则相邻两上级块可同向，与 `AltSeq` 严格方向交替冲突；若改取净走势方向，则盘整块本无净方向。 | 合稿底层严格用 `AltSeq P`，高阶粗化序列先采用 `List (Seg P)`（不强行施加交替拦截），并将 `CoarseDirPolicy`（首段方向 vs 净极值方向 vs 无向盘整态）参数化。 | **是（高优先）**：关系整个多级塔类型论基石与 M5/M9 上级中枢能否成立。 |
| U-2 | M15 `isFirstBuy`/`isFirstSell` | 原典与 `02-citations.md` 均未在形态学层写死离开段 `c` 须跌破波动低点 `DD`（创新低）还是仅须跌破核下沿 `ZD`；且动力学背驰比较对象（严格取最后两中枢间 `b` 段 vs 允许与前序多段比较）归声明包丙 `#2322` M17 管辖。 | 主线结构条件设为出核（`< ZD`）且比较段锚定 `b` 段区间；以显式参数 `FirstExitThreshold := .core | .hull`（默认不锁死）或交由 `StrengthJudge` 承载创新极值条件，待 `#2322` 与 `#2296` 对齐。 | **是**：需与 `#2322` M17 背驰正本接口联审，避免 M15 与 M17 重复或漏检 Extreme 条件。 |
| U-3 | M15 `BreakoutRetest`、`isThirdBuy`/`isThirdSell` | 面对 `[070:48]` 非极值端点与跳空缺口，原典未写死离开段越界应看整段区间极值 `s.range.hi > ZG` 还是实际收束终点 `exit > ZG`，也未写死隔夜整段跳空于 `ZG` 之上的离开是否直接构成第三类买点。 | 在 `BreakoutRetest` 显式保留 `allowGapLeave : Bool` 与 `useExitEndpoint : Bool` 开关（或单列区间版与端点版），待 `#2296` 冻结主线口径。 | 否（属边界开关，常规审阅即可拍定）。 |
| U-4 | M15 `isOscillationBuy`/`isOscillationSell` | 原典 `[101:42]` 未区分中枢震荡买卖点是定义在触界段 `a` 完成瞬间（在线、零延迟）还是须待反向段 `b` 完成确认（延迟 1 步因果）。 | 拆分为在线原语 `isOscillationBuy`（在 `a` 末实时成立）与确认版 `isConfirmedOscillationBuy`（附反向段 `b` 存在，不要求 `p = q`），零冲突保留两者。 | 否（拆分两谓词即可完全消解）。 |

### 4.3 `needs-fable` 总体判定

**结论：必须标记 `needs-fable`**，定向提交以下 4 项核心数学深审任务：
1. **M6 `LevelTower` 高阶方向交替律（轴 U-1）**：偶数长度完成块（4/6/8/10 段）粗化后能否、以及应如何保持高阶 `AltSeq` 结构（若放弃高阶交替，M5 上级中枢的"至少三段次级别走势类型"是否无需方向交替即可成核？）。
2. **M6 `IsCanonical` 局部贪心 vs 全局结合律回溯（第 62 项）**：如何在声明式 `IsCanonical` 中同时兼容 `#2318` 局部唯一性定理与 `[099:22]`/`[099:26]` 跨块结合律重组，而不破坏 `InterfaceLaws` 的已确认前缀稳定性。
3. **M7 `CarryNineParams` 三分支完备性与性质保持（第 64 项）**：逐组合验证分支 A（3 档）× 分支 B（3 档）× 分支 C（2 档）下 `InterfaceLaws`、`CarryBounded` 与 `DeterministicRule` 的可满足性，剔除内在矛盾组合以供 `#2296` 冻结。
4. **M15 一类点离枢阈与 `#2322` M17 接口边界（轴 U-2）**：明确 `DD`（创新低/新高）究竟由 M15 形态学硬锁还是下沉至 M17 `StrengthJudge` 统一管理。

---

## 五、`decl/fm10c-core` 统一融合蓝图

### 5.1 全局架构、命名空间与可判定性铁律

1. **统一序载体**：全部 17 个文件统一使用 Mathlib `[LinearOrder P]`（导入具体子模块 `Mathlib.Order.Interval.Basic`、`Mathlib.Order.OrderDual`、`Mathlib.Data.List.Chain` 等，**严禁 `import Mathlib`**），放弃乙方自建的 `Std.LinearOrderPackage` 与 `PriceDual`，消除后续与 Mathlib `NonemptyInterval`、`OrderDual`、`Filter.EventuallyConst` 及 `Chan/Thm/` 证明层的类型类菱形冲突。
2. **零 `linter.dupNamespace`、零 `export`、零 `set_option` 铁律**：
   - 严格沿用甲方第 3 轮已通过 `#2312` 门禁的命名空间解法：
     - `Center/Center.lean` 中将 `structure Center` 直接声明于 `namespace Chan.Defs` 下（全名 `Chan.Defs.Center`），随即切入 `namespace Chan.Defs.Center` 定义 `CanSeedCenter`、`extendsWith`、`leavesUp`、`leavesDown`、`thirdBuyEvent`、`thirdSellEvent`、`destroyed` 等全部成员（全名 `Chan.Defs.Center.extendsWith` 等）。
     - `Level/Rule.lean` 中将 `structure Level` 直接声明于 `namespace Chan.Defs` 下（全名 `Chan.Defs.Level`），随即切入 `namespace Chan.Defs.Level` 定义 `BlockRule`、`InterfaceLaws` 等。
   - **修复乙方两处 `dupNamespace` 红项**（乙方 `Chan.Defs.Center.Center` 与 `Chan.Defs.Level.Level` 不可照搬）。
   - 全包 17 个文件均首行 `module`，公开定义一律置于 `@[expose] public section`，公开签名依赖用 `public import`，其余用 `import`；**严禁 `export`、`set_option`、`axiom`、`sorry`、`admit`、`native_decide`、`partial`、`macro`/`syntax`/`elab`/`notation`**。
3. **全面可判定性补全**：
   - 为 `Bar`、`CoreHull`、`Span`、`Seg`、`AltSeq`、`Zigzag`、`CutChain`、`NestedCuts`、`Center`、`SmallModel`、`RevisionCount`、`CarryNineParams`、`Level`、`Finished` 全部提供 `DecidableEq` 实例（注意在 `[LinearOrder P]` 下 `DecidableEq P` 已自动就绪，结构中含 `Prop` 证明字段时借助证明无关性手写或 `deriving DecidableEq`）。
   - 所有有限域核心谓词（`Bar.contains`、`overlaps`、`overlapsList`、`relPos`、`Laminar`、`CanSeedCenter`、`Center.extendsWith`、`leavesUp/Down`、`thirdBuyEvent/SellEvent`、`destroyed`、`ValidDecomp`、`IsCanonical`、`classifyTrend`、`TrendFormingProspect`、`phaseAt`、`BreakoutRetest` 及全部买卖点谓词）均提供 `Decidable` 实例或直接配等价 `Bool` 计算函数，保证 `W1` 至 `W20` 均可由 Lean 内核 `decide` 秒级机检。

### 5.2 逐文件最终合稿蓝图（全部 17 个文件）

| 序号 | 文件（相对 `Chan/Defs/`） | 最终选型与融合要点 | 命名空间与可判定性修复 |
|---:|---|---|---|
| 1 | `Order/Bar.lean` | 采甲方 `[LinearOrder P]` 骨架 + 乙方 `deriving DecidableEq` 与 `Bar.strictDown := b.strictUp a` 精简写法；提供 `Bar.toNonemptyInterval` 互转桥。 | `Chan.Defs.Order`；为 `Bar` 补 `DecidableEq`；三序谓词均有 `Decidable` 实例。 |
| 2 | `Order/IntervalAlg.lean` | `overlapsList` 采乙方非空签名 `(a : Bar P) (bs : List (Bar P))`（与 `hullInterval` 对称）并保留 `overlapsList? : List (Bar P) → Prop`；`relPos` 采乙方先波动后核的清晰分支 + 甲方声明式 `RelPos.Holds`。 | `Chan.Defs.Order`；为 `CoreHull` 补 `DecidableEq`；`overlapsList`、`RelPos.Holds` 全可判定。 |
| 3 | `Path/History.lean` | `History`/`IsPrefix`/`Confirmed`/`DelayedCausal` 沿用等价共性；`LimitStable` 同时提供 `LimitStableTo f s v`（乙方）与 `LimitStable f s := ∃ v, LimitStableTo f s v`（甲方）；`PendingCandidates` 采乙方 `FiniteImage` 精确像集并保留甲方 `sampleCandidatesOn`；`RevisionCount` 采结构 `{ rewritten : Nat, deepest : Option Nat }` 配乙方稳定地址 `Key` 测量。 | `Chan.Defs.Path`；保留甲方有限样本 `ConfirmedOn`/`DelayedCausalOn`/`StableBetween` 供穷举，保留乙方基于 `FiniteImage`/`TailSpectrum` 的 `Decidable` 实例。 |
| 4 | `Path/Symmetry.lean` | `dualBar` 采甲方 Mathlib `OrderDual P`；`OrderEmb` 采甲方 `le_iff`（附 `strict` 构造子）；`SmallModel` 融合甲方结构载体 `SmallModel n bound` 与乙方去重秩压缩函数 `SmallModel.compress`。 | `Chan.Defs.Path`；`SmallModel` 补 `DecidableEq` 与 `SmallModel.Valid` 可判定。 |
| 5 | `Alt/Basic.lean` | `Dir`/`Span`/`Seg`/`dualSeg`/`Seg.mapEmb` 融合甲方 `OrderDual` 与乙方 `DecidableEq`；`AltSeq` 采乙方 `items : List (Seg P)` 配 `List.IsChain (fun a b => a.dir ≠ b.dir)` 消除空序列幽灵方向。 | `Chan.Defs.Alt`；`Span`/`Seg`/`AltSeq` 全具 `DecidableEq`。 |
| 6 | `Alt/Zigzag.lean` | 采乙方极值共端子类型 `Zigzag P := { xs : AltSeq P // ... }` 使 `Zigzag.toAltSeq` 为严格单射嵌入；另在此文件或 `Signal/Phase.lean` 独立提供带方向单调性的 `DirectedEndpoints`。 | `Chan.Defs.Alt`；子类型谓词直接可判定，`Zigzag` 具 `DecidableEq`。 |
| 7 | `Alt/CutChain.lean` | `CutChain N` 要求非空（`cuts ≠ []`）、`List.IsChain (· < ·) cuts`、`∀ c ∈ cuts, c ≤ N` 并单列 `CutChain.anchoredZero : cuts.head? = some 0`；`Laminar` 采乙方强制 `∀ b ∈ blocks, b.1 < b.2`；`MultiAddress` 取 `i : Fin N`。 | `Chan.Defs.Alt`；`CutChain`/`NestedCuts` 补 `DecidableEq`，`Laminar` 可判定。 |
| 8 | `Center/Center.lean` | `structure Center` 置于 `namespace Chan.Defs`，融合乙方自证段包 `(start, a, b, c, more, alternating, seed, extension)` 并导出现成 `core`/`hull`/`zone : CoreHull P`/`stop`；**重写 `thirdBuyEvent`/`thirdSellEvent`/`destroyed` 修复乙方跳空缺陷**：离开段判 `dir = up ∧ ZG < leave.range.hi`（向下对称），回试段判 `dir = down ∧ c.leavesUp back`，序列级提供 `thirdBuyAt`/`thirdSellAt` 同时支持 `k = c.stop - 1`（连续重叠离开，含 `[054:24]`）与 `k = c.stop`（跳空离开）。 | `Center` 落 `Chan.Defs`，其余落 `Chan.Defs.Center`（零 `dupNamespace`）；全核心谓词 `Decidable` 且 `Center` 具 `DecidableEq`。 |
| 9 | `Level/Rule.lean` | `structure Level` 置于 `namespace Chan.Defs`；`BlockRule` 采乙方 `(k, xs, past, i, j) → rank : Option Nat` + `confirmed : Bool` + 可选 `blockDir`；`coarsen` 采乙方越界守卫；`InterfaceLaws` 同时提供全称 `Prop`（仅对 `confirmed` 块要求前缀稳定）与逐点 `Bool` 核验；`CarryBounded` 采甲方块内 `ExtRun ≤ K`；`DeterministicBlocks` 采乙方切点表级占优唯一加尾部穷尽，并增 `DeterministicRule` 规则级前提。 | `Level` 落 `Chan.Defs`，其余落 `Chan.Defs.Level`（零 `dupNamespace`）；逐点检定与 `DeterministicBlocks` 全可判定。 |
| 10 | `Level/Tower.lean` | 采乙方几何塔与 `ValidDecomp` 解耦架构、直接存底层原始 `NestedCuts` 且要求 `anchoredZero` 与 `raw.length ≥ 2`；**解除 `Stage.ascend` 对上级粗化块按首段方向交替的硬拦截**（高阶暂用 `List (Seg P)`，待 `needs-fable` 轴 U-1 拍定）。 | `Chan.Defs.Level`；`cuts`/`sameCuts` 可判定。 |
| 11 | `Level/Canonical.lean` | `ValidDecomp` 采乙方逐层 `rank.isSome` 检查；`IsCanonical` 拆为默认局部版 `IsLocalCanonical`（乙方 `DeterministicBlocks` 加顶层不可再分）与参数化全局版 `IsGlobalCanonical pref`（保留至 `#2296`）；`CanonicalDecomp` 封装 `LevelTower` 子类型。 | `Chan.Defs.Level`；`ValidDecomp`、`IsLocalCanonical` 全可判定。 |
| 12 | `Level/CarryNine.lean` | `CarryNineParams` 扩充为三枚举（分支 A：3 档；分支 B：3 档；分支 C：2 档加前导搜索开关）；`carryNineRule` 融合乙方 `nineAt`（`3+3+3` 三凸包公共交）+ 甲方 `firstSeedFrom` 前导搜索 + 乙方途径二 `returningCenter`（改调修复后的 M5 通用破坏并限制次枢延伸 ≤ 9 段）+ 双层 `rank` 与 `confirmed`。 | `Chan.Defs.Level`；`CarryNineParams` 具 `DecidableEq`，`carryNineRule` 全可计算。 |
| 13 | `Level/SameLevel.lean` | 采融合签名 `sameLevelRule (atDepth : Nat := 0) (subRule : BlockRule)`：`k < atDepth` 委托 `subRule`，`k = atDepth` 三段成核截块，`k > atDepth` 返回 `none`。 | `Chan.Defs.Level`；全可计算。 |
| 14 | `Level/NoCap.lean` | 融合甲方前导 `firstSeedFrom` 搜索与乙方"通用 M5 破坏或后枢波动重叠"双终结条件，不设 9 段上限。 | `Chan.Defs.Level`；全可计算。 |
| 15 | `Level/TrendType.lean` | 采乙方 `Finished` 认证块载体配等价的 `classifyTrend`；`TrendFormingProspect` 改调修复后的 M5 通用第三类事件（兼收连续与跳空离开），并保留乙方顺向突破离开段极值的推进要求。 | `Chan.Defs.Level`；`TrendKind` 具 `DecidableEq` 与 `dual`，`TrendFormingProspect` 可判定。 |
| 16 | `Signal/Phase.lean` | 采乙方 `Phase`、`Endpoints`、`Decomposition` 认证账本与 `phaseAt : Decomposition P → Nat → Option Phase`（按最近同级中枢判阶段，消除甲方第一中枢锁死），并支持 `LevelTower` 到 `Decomposition` 的构造桥接。 | `Chan.Defs.Signal`；`phaseAt` 全可计算。 |
| 17 | `Signal/Points.lean` | `StrengthJudge` 统一为 `(Decomposition P, Center P, Nat, Nat) → Bool`；`BreakoutRetest` 剥离为纯几何模板并参数化跳空/端点开关；`isFirstBuy`/`isFirstSell` 采乙方 `Finished` 与中阴门、收紧比较段为最后两中枢间 `b` 段并参数化 `DD`/`ZD`；`secondStrength?` **修复乙方 `ZG` 等号违约**（改严格 `<`）；`isThirdBuy`/`isThirdSell` 与 `isPseudoThird*` 按 `0 < depth` 与 `depth = 0` 互斥分流并放宽至 `z.start + 2 ≤ i`（通过 `[054:24]`），坚持 B-14 不加底部特判；`isOscillation*` 采乙方最近中枢震荡门、去掉 `p = q` 跳空限制并分立在线版与确认版。 | `Chan.Defs.Signal`；全部 13 个公开谓词及强弱分类均返回 `Bool` 或附 `Decidable` 实例。 |

### 5.3 引文合规与门禁逐文件审查报告

依据 `01-rulings.md` 第二节与 `04-interface-constraints.md` 第 11 条（文档串中的课行号与逐字引文只能从 `02-citations.md` 原样复制；硬证据标 `[课号:行号]`；二级旁证必须显式标 `[二级旁证 课号:行号]`；不得引用编者注/娇注或篡改引文），逐一核查全部 34 份文件结论如下：

#### 甲方（Opus）17 份文件核查结论
1. **课行号范围与 Tier 2 标注**：**合规**。甲方共引用 47 条 Tier 1 硬证据与 7 条 Tier 2 旁证（`Level/Rule.lean:169` `[二级旁证 018:36]`、`Level/CarryNine.lean:40` `[二级旁证 066:186]`、`:103` `[二级旁证 095:86]`、`:136` `[二级旁证 069:423]`、`Level/SameLevel.lean:24` `[二级旁证 041:259]`、`:35` `[二级旁证 038:20]`、`Level/TrendType.lean:47` `[二级旁证 106:186]`），**零漏标 `[二级旁证]`、零超包引文、零编者注/娇注**。
2. **逐字原样复制合规性**：**不合规（系统性截断）**。全部 17 个文件均普遍存在把 `02-citations.md` 准入条文**截断为子句或半句**的现象（违背"只能从本引文包 `02-citations.md` 原样复制"），典型位置如下：
   - `Order/Bar.lean:23,37,48,59,66,74,81,89,96`（`[017:40]` 反复被截断为后半句或尾句，且硬贴到 `Bar.contains`/`strictUp`/`strictDown` 等与递归底极限无关的谓词上）
   - `Order/IntervalAlg.lean:57,64,73,81,97,106,114,144,188,195,203,216,228`（`[054:24]`、`[020:48]`、`[020:56]`、`[020:58]` 均被截句）
   - `Path/History.lean:29,43,51,85,94,103,111,119,160,170,183,191,201`（`[099:22]`、`[102:38]`、`[099:16]` 截句）
   - `Path/Symmetry.lean:48`（`[054:24]` 截句）
   - `Alt/Basic.lean:23,35,91,108,117,125,133,142`（`[067:16]`、`[054:24]` 截句；另 `:80` 把 `[067:16]` 原文中的不间断空格 `U+00A0` 改为普通空格）
   - `Alt/Zigzag.lean:43,56`（`[067:16]` 截句）
   - `Alt/CutChain.lean:19,26,34,60,67,74,82,89,122`（`[057:42]`、`[057:40]`、`[053:20]` 截句）
   - `Center/Center.lean:51,58,76,85,116,123,130,146,161,177,186,193,201,208,220,238,246,272,282`（多条截句）
   - `Level/Rule.lean:41,48,57,77,86,107,143,153,195`、`Level/Tower.lean:24,111,120`、`Level/Canonical.lean:32`、`Level/CarryNine.lean:38,80,124,137`（含 `[二级旁证 069:423]` 截句）、`Level/TrendType.lean:48`（含 `[二级旁证 106:186]` 截句）
   - `Signal/Phase.lean:42,45`、`Signal/Points.lean:58,68,79,88,106,263,292,322,340,348,357,365`（多条截句）
3. **`#2312` 语法与门禁**：零禁用关键字、零 `export`、零 `set_option`、零 `linter.dupNamespace`。

#### 乙方（Astra）17 份文件核查结论
1. **课行号范围与逐字原样复制**：**高度合规**。全部 17 个文件仅使用 `02-citations.md` 第一部分（Tier 1）硬证据，**每一条引文均为完整逐字原样复制**（甚至完整保留了 `[020:48]`、`[067:16]`、`[099:22]` 中的原始 `U+00A0` 空白字符），**零截断、零篡改、零超包引文、零编者注/娇注**。
2. **Tier 2 使用**：乙方全程未引用任何 Tier 2 条目，故**零漏标 `[二级旁证]`**。
3. **瑕疵与门禁红项**：
   - 命名空间红项：`Center/Center.lean:8,28`（`Chan.Defs.Center.Center`）与 `Level/Rule.lean:8,17`（`Chan.Defs.Level.Level`）触发 `linter.dupNamespace`，合稿必须改采甲方写法；
   - 语境瑕疵：`Signal/Points.lean:134` 在 `isThirdBuy` 上并列引用 `[020:60]` 与 `[054:24]` 但未在说明中注明 `[020:60]` 字面"不跌破"已按分叉 4 由 `[054:24]` 覆写；`Order/Bar.lean` 将 `[018:24]` 挂于 `Quantizer`、`[020:58]` 挂于 `strictUp/strictDown` 略偏宽泛。
   - 其余 `#2312` 禁用关键字、`export`、`set_option`、`import Mathlib` 均为零。

#### 合稿 `decl/fm10c-core` 引文整顿规则
- 以乙方"整条原样逐字复制 `02-citations.md`"为唯一文本规范，彻底清除甲方所有子句截断；
- 凡涉及 Tier 2 辅助背景（如 M7 九段 `3+3+3` 与途径二、M8 同级别 3 段成块、M9 `a`/`c` 缺省），一律按甲方规范显式标注 `[二级旁证 课号:行号]` 并整条原文复制，绝不作为硬证据；
- 凡引用 `[020:60]` 处须显式注明"字面口径与分叉 4 相反，主线统一按 `[054:24]` 严格不等号"；
- 仅为语义定义本身挂接相关引文，不对机械 `Decidable` 实例重复贴无关联引文。
