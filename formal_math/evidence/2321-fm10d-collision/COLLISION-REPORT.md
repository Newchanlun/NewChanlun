# FM-10d（`#2321`，M10 至 M14）第三方独立语义对撞报告

## 0. 对撞元信息与版本绑定

- **任务编号**：`#2321`（FM-10d：M10 行情规范形、M11 分型、M12 笔、M13 线段、M14 四种递归基底）
- **对撞官**：`fm10d-collider-neon`（Google `gemini-4-neon-xhigh`，独立于甲方 Anthropic `claude-opus-5-5-high` 与乙方 OpenAI `gpt-6.2-astra`）
- **绑定提交哈希**（源自 `shas.txt`）：
  - 甲方（Opus，`origin/blind/fm10d-opus`）：`1fd3f0fe5e7910a66d63070ae82846245b2d5cca`
  - 乙方（Astra，`origin/blind/fm10d-astra`）：`ea71754a868c0867885b6c83d924e527f782933a`
  - 上游冻结基线（`decl/fm10c-core`，M0/M2/M3/M4）：`8c5ad6a215b41d6a905f02691964c947438637b8`
  - 规范与引文包（`pack-fm10d`）：`0bde991c1797e3d4baadaca235b2958578c0b4d4`
- **核验方式**：全量静态语义推演与有限整数模型逐步骤手算复核（遵守仅读写文件约束，未执行外部命令）。所有见证均在 `Int` 线性序上构造，可直接编入 `Chan/Audit/Separation/Fm10dSeparation.lean` 并通过 `decide` 或 `rfl` 机器核验。

---

## 1. 总体结论与三分类汇总

依据 `04-interface-constraints.md` 清单，M10 至 M14 共有 **41** 个公开定义（其中 M12 末项拆为 `PenOnlineState` 与 `penOnlineState` 两项）。对撞三分类统计如下：

| 模块 | 文件 | 公开定义数 | `EQUIV` | `SEPARATED` | `UNDECIDED` |
|---|---|---:|---:|---:|---:|
| M10 | `Chan/Defs/Base/Kline.lean` | 6 | 4 | 2 | 0 |
| M11 | `Chan/Defs/Base/Fractal.lean` | 7 | 5 | 2 | 0 |
| M12 | `Chan/Defs/Base/Pen.lean` | 12 | 6 | 4 | 2 |
| M13 | `Chan/Defs/Base/Segment.lean` | 9 | 5 | 4 | 0 |
| M14 | `Chan/Defs/Base/Instance.lean` | 7 | 3 | 3 | 1 |
| **总计** | **5 个文件** | **41** | **23** | **15** | **3** |

**核心判定摘要**：

1. **三项实质未决轴（需 `needs-fable` 裁定）**：
   - `U-1`（M12 `parsePens`）：等值分型均可成笔时的早晚破平方向（`077:54` 留白），以及在声明式饱和分解不唯一时（已被 13 根无包含 K 线反例 `W7c` 证伪）应采纳“保首极值在线递推”还是“全局最多笔数优先”。
   - `U-2`（M12 `penOnlineState`）：尚无保留分型时应返回 `Option` 还是总函数，以及“分型构造中 (0)”与“确认延伸为笔中 (1)”的精确切换边界（`091:28-30` 留白）。
   - `U-3`（M14 `klineOverlapBase`）：K 线重叠基底映射为 `AltSeq` 前是否先经 M10 包含处理，以及若不经包含处理时单端相等包含对（如 `[10, 20] -> [10, 25]`）应判无方向吸收还是定向推进（`017:40`/`018:58` 留白）。
2. **已可明确裁决的关键缺陷与架构胜负**：
   - **乙方（Astra）在类型不变式与线段引擎核上显著占优**：`classifyTriple` 的 `Option` 域守卫与 `OrderDual` 对称性、`RetainedFractal`/`Pen`/`Segment` 的类型级不变式（杜绝共根、同向与端顶低于端底）、`ValidPenDecomp` 的饱和性检查、`stdFeatureSeq` 递归栈消除固定方向级联包含、`parseSegments` 第二种情况同时检验第一与第二特征序列分型且不静默跳过起点。
   - **甲方（Opus）在配置参数化与在线笔回溯精神上具有独特优势**：`SegRuleConfig` 完整参数化两处答疑冲突（2x2 组合，便于审计对照）、`penStep` 在 `069:20` 反证回溯案例 `W7b` 中正确撤销旧顶改选新高（而 Astra 全局 DP 因末端极值比较失误倒退回旧段并吞掉新高）、`BaseOutput tag P` 在产出类型层阻断跨基底 `AltSeq` 混用。
3. **引文与规范门禁初筛**：双方 10 个文件全部遵守 `module` 首行、`@[expose] public section`、无禁用关键字、无非法 `import`，且全部逐字引文均严格命中 `02-citations.md` 准入表，二级旁证全部显式标注 `[二级旁证]`，零违规。

---

## 2. 逐定义三分类完整矩阵（41 项）

分类口径：
- `EQUIV`：双方类型与语义同构（允许构造子名、字段名、参数顺序或单字段包装差异），不存在行为反例。
- `SEPARATED`：存在可手算、可 `decide` 复现的有限反例见证（`W*`），且可依据 `01-rulings.md`、`02-citations.md`、`03-informal-specs.md` 或数学自洽性直接判定选型。
- `UNDECIDED`：存在有限分离见证（`W*`），且原典与现有裁定包均存在留白，需提交 `needs-fable` 裁定轴（`U-1..U-3`）。

### 2.1 M10 `Chan/Defs/Base/Kline.lean`（6 项：4 `EQUIV`，2 `SEPARATED`，0 `UNDECIDED`）

| # | 公开定义 | 分类 | 甲方（Opus）要点 | 乙方（Astra）要点 | 等价理由 / 分离见证 |
|---|---|---|---|---|---|
| 1 | `InitIncludePolicy` | `SEPARATED` | 三态枚举 `defaultUp \| defaultDown \| pending`（`pending` 取外包吸收） | 二态结构 `initial : Dir`（仅 `up` / `down`） | 基数 3 对 2；`pending` 语义无法被二态模拟，见 `W1` |
| 2 | `MergedBar` | `EQUIV` | 5 字段：`range, span, rawCount, hiIdx, loIdx`（`rawCount` 独立存储） | 4 字段：`range, source, lowAt, highAt`，`rawCount` 为派生函数 `last - first + 1` | 在所有 `klineNormalize` 输出像集上逐字段同构（注：Astra 排除冗余字段失配） |
| 3 | `hasInclusion` | `EQUIV` | `a.contains b ∨ b.contains a` | `a.contains b ∨ b.contains a` | 逐字一致 |
| 4 | `mergePair` | `EQUIV` | `Dir -> Bar P -> Bar P -> Bar P`（元数据合并拆入 `mergeInto`） | `Dir -> MergedBar P -> MergedBar P -> MergedBar P`（含 `source/lowAt/highAt`） | 区间运算完全相同；对并列下标双方均取较早者（`m.hi = r.hi` 等价于 `¬(m.hi < b.hi)`） |
| 5 | `klineNormalize` | `SEPARATED` | 状态机支持 `Option Dir`（含 `none` 外包合并） | 始终以 `policy.initial : Dir` 起步 | 在 `up`/`down` 子域上逐字段完全等价；Opus 独有 `.pending` 在 `W1` 输出 1 根而 Astra 全策略输出 2 根 |
| 6 | `IsInclusionFree` | `EQUIV` | `∀ p ∈ ms.zip ms.tail, ¬ hasInclusion p.1.range p.2.range` | `xs.IsChain (fun a b => ¬ hasInclusion a.range b.range)` | 对所有列表（含空表与单元素表）逻辑等价 |

### 2.2 M11 `Chan/Defs/Base/Fractal.lean`（7 项：5 `EQUIV`，2 `SEPARATED`，0 `UNDECIDED`）

| # | 公开定义 | 分类 | 甲方（Opus）要点 | 乙方（Astra）要点 | 等价理由 / 分离见证 |
|---|---|---|---|---|---|
| 7 | `TripleKind` | `EQUIV` | `up \| down \| top \| bottom` | `rising \| falling \| top \| bottom` | 4 构造子命名双射同构 |
| 8 | `classifyTriple` | `SEPARATED` | 全函数返回 `TripleKind`，末分支静默落 `.down` | 偏函数返回 `Option TripleKind`，依赖 `strictUp/strictDown` | 无包含域内等价；域外（等端/包含）Opus 错判 `.down`/`.up` 且破 `OrderDual` 对称性，Astra 返回 `none`，见 `W2` |
| 9 | `FractalKind` | `EQUIV` | `top \| bottom` | `top \| bottom` | 逐字一致 |
| 10 | `LocalFractal` | `EQUIV` | `kind, center, left, mid, right, shape`（`IsTopTriple/IsBottomTriple`） | `first, left, middle, right, kind, shape`（`classifyTriple = some ...`，`center := first + 1`） | 形态命题在全域严格逻辑等价，扫描像集完全同构（注：Astra 用 `first` 静态排除 `center = 0`） |
| 11 | `scanLocalFractals` | `EQUIV` | 右移 1 扫描三连窗，以 `IsTopTriple/IsBottomTriple` 判定 | 右移 1 扫描三连窗，以 `classifyTriple` 判定 | 对任意 `List (MergedBar P)` 输出逐项同构 |
| 12 | `RetainedFractal` | `SEPARATED` | 单字段空壳 `base : LocalFractal P`，无任何类型不变式 | 含 `pivot, previous, separated`（非首项必异性且 `p.first + 3 ≤ pivot.first`） | Opus 允许包装任意共根/同向分型，Astra 在类型层静态阻断，见 `W3` |
| 13 | `fractalEdge` | `EQUIV` | `top => f.range.lo`, `bottom => f.range.hi` | `top => f.range.lo`, `bottom => f.range.hi` | 逐字等价（三根凸包 `hullInterval` 亦同构） |

### 2.3 M12 `Chan/Defs/Base/Pen.lean`（12 项：6 `EQUIV`，4 `SEPARATED`，2 `UNDECIDED`）

| # | 公开定义 | 分类 | 甲方（Opus）要点 | 乙方（Astra）要点 | 等价理由 / 分离见证 |
|---|---|---|---|---|---|
| 14 | `PenRule` | `EQUIV` | `{ minMergedSpan, minRawSpan, requireDisjointFractal }` | `{ minMergedSpan, minRawSpan, requireDisjointFractal }` | 字段与计数语义一致（`a + k < b ↔ a + 1 + k ≤ b`） |
| 15 | `oldPenRule` | `EQUIV` | `⟨4, 0, false⟩` | `⟨4, 0, false⟩` | 逐字一致 |
| 16 | `newPenRule` | `EQUIV` | `⟨3, 3, false⟩` | `⟨3, 3, false⟩` | 逐字一致 |
| 17 | `sixBarPenRule` | `EQUIV` | `⟨3, 4, false⟩` | `⟨3, 4, false⟩` | 逐字一致 |
| 18 | `disjointFractalPenRule` | `SEPARATED` | 常值 `⟨3, 0, true⟩`（`minRawSpan = 0`） | 修饰函数 `(rule := newPenRule) => { rule with requireDisjointFractal := true }`（默认 `⟨3, 3, true⟩`） | 签名与默认原始间隔均分离，见 `W4` |
| 19 | `Pen` | `SEPARATED` | 5 字段无不变式记录 `dir, start, stop, range, rawSpan` | `start, stop, linked : stop.previous = some start.pivot`，其余字段派生 | Opus 允许构造共根/同向/缓存失配笔，Astra 类型级封堵，见 `W3` |
| 20 | `ValidPenPair` | `SEPARATED` | 不接收 `bars`；`PenHeightOK` 始终比 `mid.hi`（破坏 `OrderDual`） | 接收 `bars` 检查 `[a.center..b.center]` 极值包络；升比 `hi` 降比 `lo`（满足 `OrderDual`） | 包络过滤与高低对称口径双重分离，见 `W5a`、`W5b` |
| 21 | `ValidPenDecomp` | `SEPARATED` | 仅查相邻合法与中间无更优分型及末端后继；漏空表、首前驱与笔内细分 | `Sublist ∧ IsChain ∧ (empty -> empty) ∧ penChoicesSaturated`（含首尾延伸、支配、细分三检） | Opus 放行空分解与跳笔合并，Astra 拒绝，见 `W6a`、`W6b` |
| 22 | `parsePens` | `UNDECIDED` | 在线贪心栈 + 单步反证回溯 + `PenCluster` 等值暂存（等值取晚） | 全局最长链 DP + 末端极值比较（等值取早） | 归类 **`U-1`**；三类有限反例见证 `W7a`、`W7b`、`W7c` |
| 23 | `PenPhase` | `EQUIV` | `building \| extending` | `forming \| extending` | 2 构造子命名同构 |
| 24 | `PenOnlineState` | `EQUIV` | `{ dir : Dir, phase : PenPhase }`（附 `.code`） | `{ dir : Dir, phase : PenPhase }` | 结构完全同构 |
| 25 | `penOnlineState` | `UNDECIDED` | 返回 `Option PenOnlineState`；凭 `fs.any` 检查最后保留分型后曾否出现反向局部分型 | 接收 `InitIncludePolicy` 返回总函数 `PenOnlineState`；凭末两根合并 K 线方向判阶段 | 归类 **`U-2`**；有限反例见证 `W8a`、`W8b` |

### 2.4 M13 `Chan/Defs/Base/Segment.lean`（9 项：5 `EQUIV`，4 `SEPARATED`，0 `UNDECIDED`）

| # | 公开定义 | 分类 | 甲方（Opus）要点 | 乙方（Astra）要点 | 等价理由 / 分离见证 |
|---|---|---|---|---|---|
| 26 | `SegRuleConfig` | `SEPARATED` | 2x2 结构：`BreakConfirmRule × PivotRule`，默认 `main` 对齐正文 | 单点枚举 `chronologicalStrictBreak` | 4 态参数配置对 1 态单位类型，见 `W9` |
| 27 | `FeatureElem` | `EQUIV` | `{ range : Bar P, penSpan : Span }` | `{ range : Bar P, penSpan : Span }` | 逐字一致 |
| 28 | `featureSeq` | `EQUIV` | `featureSeq d i pens`，过滤 `p.dir ≠ d` | `featureSeq d pens (offset := 0)`，过滤 `p.dir ≠ d` | 仅参数顺序差异，语义全同 |
| 29 | `hasFeatureGap` | `EQUIV` | `gapUp a.range b.range ∨ gapDown a.range b.range` | `gapUp a.range b.range ∨ gapDown a.range b.range` | 逐字一致 |
| 30 | `stdFeatureSeq` | `SEPARATED` | 单步栈顶合并，不回溯检验新区间与次栈顶包含；无 `boundary` 参数 | 递归栈 `pushFeature` 级联消除逆向包含；支持 `boundary : Option Nat` | 固定方向合并触发逆向包含时 Opus 产出非法含包含序列，Astra 保持无包含，见 `W10` |
| 31 | `SegTermKind` | `EQUIV` | `firstCase \| secondCase` | `noGap \| secondFractal` | 2 构造子命名同构 |
| 32 | `Segment` | `SEPARATED` | 仅证 `3 ≤ length`, 奇数, 前三笔重叠；未证交替共端与 `078:20` 端顶高于端底 | 结构固定 `a, b, c, more`，证 `common`, `evenTail`, `chain`, `forward`（端顶严格高于端底） | Opus 允许端顶等于/低于端底的退化段，Astra 按 `078:20` 拒绝，见 `W11` |
| 33 | `parseSegments` | `SEPARATED` | 单假设前向状态机；反向破起点则 `.voided` 自动后移起点；第二种情况未检第一特征序列分型 | 枚举奇数切点 `nextSegment`；严守调用者起点；第二种情况同时要求 `turned && counter`；`stdFeatureSeq` 级联无包含 | 即使同用主线口径，在三类合法笔序列上全面分离，见 `W12a`、`W12b`、`W12c` |
| 34 | `standardizeSegment` | `EQUIV` | `up => (lo, hi)`, `down => (hi, lo)` | `up => (lo, hi)`, `down => (hi, lo)` | 合法段上语义完全等价 |

### 2.5 M14 `Chan/Defs/Base/Instance.lean`（7 项：3 `EQUIV`，3 `SEPARATED`，1 `UNDECIDED`）

| # | 公开定义 | 分类 | 甲方（Opus）要点 | 乙方（Astra）要点 | 等价理由 / 分离见证 |
|---|---|---|---|---|---|
| 35 | `BaseTag` | `EQUIV` | `segment \| fractalDirect \| klineOverlap \| tick` | `segments \| directFractals \| klineOverlap \| ticks` | 4 构造子命名同构 |
| 36 | `Tick` | `EQUIV` | `{ idx : Nat, price : P }` | `{ time : Nat, price : P }` | 2 字段命名同构 |
| 37 | `BaseInterface` | `EQUIV` | `BaseInterface (tag : BaseTag) P` 含 `Input` 与 `run : Input -> BaseOutput tag P` | `BaseInterface (tag : BaseTag) P` 含 `Input` 与 `build : Input -> AltSeq P`（另配 `BaseLevel tag`） | 单字段包装同构 `BaseOutput tag P ≃ AltSeq P`（防混比落点互补） |
| 38 | `segmentBase` | `SEPARATED` | 4 参 `(pol, r, cfg, start)` | 3 参 `(policy, r, start)`，固定 `.chronologicalStrictBreak` | 签名不同且端到端继承 M10/M12/M13 分离，见 `W13` |
| 39 | `fractalDirectBase` | `SEPARATED` | 经 `klineNormalize pol` 后 `fractalChain` 直连 | 经 `klineNormalize policy` 后 `directPivots` 直连 | `up`/`down` 子域上算法完全等价；Opus 独有 `.pending` 导致输出段数分离，见 `W14` |
| 40 | `klineOverlapBase` | `UNDECIDED` | 接收 `pol`，先经 `klineNormalize` 消包含再按高点升降切段 | 无参数，不经包含处理，用 `rangeStep` 按原始区间单端变动切段 | 归类 **`U-3`**；有限反例见证 `W15` |
| 41 | `tickBase` | `SEPARATED` | `Input := List (Tick P)`；平价点在 `tickSteps` 被丢弃不计入跨度 | `Input := { ts // ts.IsChain (a.time < b.time) }`；平价点归并保留连续跨度 | 输入类型与平价成交跨度均分离，见 `W16` |

---

## 3. 有限反例见证全集（`W1` 至 `W16`）

所有价格均取 `P := Int`，区间记为 `[lo, hi]`，原始下标从 `0` 起计。

### `W1`（M10 `InitIncludePolicy` 与 `klineNormalize`：`pending` 外包吸收 vs 定向合并）
- **输入**：`bars = [[10, 20], [12, 18], [11, 19]]`（3 根 K 线，下标 0, 1, 2）。
- **甲方（Opus）**：`klineNormalize .pending bars` 将 0 与 1 外包合并为 `[10, 20]`，再与 2 包含继续外包合并，输出 **1 根**：`[⟨[10, 20], span=0..2, rawCount=3, hiIdx=0, loIdx=0⟩]`。
- **乙方（Astra）**：
  - `klineNormalize ⟨.up⟩ bars` 将 0 与 1 向上合并为 `[12, 20]`，与 2 (`[11, 19]`) 无包含（严格下降），输出 **2 根**：`[⟨[12, 20], 0..1, lo=1, hi=0⟩, ⟨[11, 19], 2..2, lo=2, hi=2⟩]`。
  - `klineNormalize ⟨.down⟩ bars` 将 0 与 1 向下合并为 `[10, 18]`，与 2 (`[11, 19]`) 无包含（严格上升），输出 **2 根**：`[⟨[10, 18], 0..1, lo=0, hi=1⟩, ⟨[11, 19], 2..2, lo=2, hi=2⟩]`。
- **结论**：`pending` 无法用任何 `Dir` 策略模拟，且其外包语义会扩大合并区间并吞并本应无包含的第 3 根 K 线。

### `W2`（M11 `classifyTriple`：域外包含/等端输入与 `OrderDual` 对称性）
- **输入 A（全等包含）**：`a = [0, 10], b = [0, 10], c = [0, 10]`。
  - **甲方（Opus）**：`classifyTriple a b c = .down`；对其施加 `dualBar` 翻转后在对称序上仍返回 `.down`（不翻转为 `.up`），**破坏 `OrderDual` 对称性**。
  - **乙方（Astra）**：`classifyTriple a b c = none`（对偶翻转亦返回 `none`）。
- **输入 B（前升后包含）**：`a = [0, 5], b = [2, 10], c = [3, 8]`（`b` 包含 `c`）。
  - **甲方（Opus）**：`classifyTriple a b c = .up`（错把包含三元组判作上升）。
  - **乙方（Astra）**：`classifyTriple a b c = none`。

### `W3`（M11 `RetainedFractal` 与 M12 `Pen`：类型级阻断共用 K 线）
- **输入**：4 根无包含合并 K 线 `[[2, 12], [0, 10], [3, 13], [1, 11]]`（下标 0..3），扫描出两个共用索引 1, 2 的局部分型 `f1`（底，`first=0, center=1`）与 `f2`（顶，`first=1, center=2`）。
- **甲方（Opus）**：可良型构造 `RetainedFractal.mk f1`、`RetainedFractal.mk f2` 及 `Pen.ofPair ⟨f1⟩ ⟨f2⟩`（类型系统不拦共根与同向笔）。
- **乙方（Astra）**：类型 `{ r : RetainedFractal Int // r.pivot = f2 ∧ r.previous = some f1 }` 空缺（需证 `0 + 3 ≤ 1`），`Pen` 的 `linked` 字段同步静态排除共根笔。

### `W4`（M12 `disjointFractalPenRule`：常值 `minRawSpan=0` vs 默认新笔修饰器 `minRawSpan=3`）
- **输入**：6 根无包含 K 线 `[[2, 5], [0, 3], [1, 6], [7, 10], [9, 13], [8, 12]]`（下标 0..5）。
  - 扫描出 2 个分型：`B1`（底，`center=1, extremeAt=1, range=[0, 6]`）与 `T1`（顶，`center=4, extremeAt=4, range=[7, 13]`），三根窗口不共根（`1 + 3 = 4`）、分型区间完全不相交，但极值间仅隔 2 根原始 K 线（索引 2, 3）。
- **甲方（Opus）**：`disjointFractalPenRule = ⟨3, 0, true⟩`，`parsePens disjointFractalPenRule ms` 输出 **1 笔**（`B1 -> T1`）。
- **乙方（Astra）**：`disjointFractalPenRule` 默认展开为 `⟨3, 3, true⟩`，`1 + 1 + 3 ≤ 4` 为假，`parsePens (disjointFractalPenRule) ms` 输出 **`[]`（0 笔）**。

### `W5a` 与 `W5b`（M12 `ValidPenPair`：中间极值包络与 `OrderDual` 高低关系）
- **`W5a`（真实无包含序列上的中间极值包络检查）**：
  - **输入**：7 根无包含 K 线 `bars = [[12, 22], [10, 20], [11, 21], [4, 14], [8, 18], [14, 24], [12, 22]]`（下标 0..6），取扫描出的 `a = B(center=1, ext=10)` 与 `b = T(center=5, ext=24)`，规则 `oldPenRule`。
  - **甲方（Opus）**：`ValidPenPair oldPenRule a b = True`（不检验 `bars[3] = [4, 14]` 跌破 10）。
  - **乙方（Astra）**：`ValidPenPair oldPenRule bars a b = False`（因 `bars[3].lo = 4 < 10` 破坏极值包络）。
- **`W5b`（单对分型 `PenHeightOK` 的 `OrderDual` 对称性破坏）**：
  - **输入**：上升对 `a'`（底分型，`left=[12,22], mid=[10,20], right=[12,22], center=1`）与 `b'`（顶分型，`left=[8,28], mid=[10,30], right=[8,28], center=5`），以及它们的 `OrderDual` 翻转下降对 `a`（顶分型，`mid=[-20,-10]`）与 `b`（底分型，`mid=[-30,-10]`）。
  - **甲方（Opus）**：`PenHeightOK a' b'` 为 `20 < 30`（`True`），但对偶翻转后 `PenHeightOK a b` 为 `-10 < -10`（`False`），破坏 `OrderDual` 对称性。
  - **乙方（Astra）**：原序比较 `a'.mid.hi < b'.mid.hi`（`20 < 30` 为 `True`），对偶翻转后下降分支比较 `b.mid.lo < a.mid.lo`（`-30 < -20` 为 `True`），保持 `OrderDual` 对称性。

### `W6a` 与 `W6b`（M12 `ValidPenDecomp`：空分解与跳笔合并漏洞）
- **`W6a`（非空分型集上的空分解）**：
  - **输入**：3 根无包含 K 线 `bars = [[0, 5], [2, 10], [1, 8]]`（1 个顶分型），候选分解 `xs = []`。
  - **甲方（Opus）**：`ValidPenDecomp oldPenRule bars [] = True`（全称量词空真漏洞）。
  - **乙方（Astra）**：`ValidPenDecomp oldPenRule bars [] = False`（要求无分型方可为空）。
- **`W6b`（跳过中间完整转折笔）**：
  - **输入**：15 根无包含 K 线（下标 0..14）：
    `[[4,6], [0,2], [3,5], [6,8], [9,11], [12,14], [10,12], [8,10], [6,8], [4,6], [8,10], [12,14], [16,18], [20,22], [18,20]]`。
    扫描得 4 个合法交替分型 `B1(c=1, ext=0), T1(c=5, ext=14), B2(c=9, ext=4), T2(c=13, ext=22)`。考察跳过中间的 1 笔候选 `xs = [B1, T2]`。
  - **甲方（Opus）**：`ValidPenDecomp oldPenRule bars [⟨B1⟩, ⟨T2⟩] = True`（放行将三笔并成一笔，违背 `062:26`“相邻顶底”）。
  - **乙方（Astra）**：`ValidPenDecomp oldPenRule bars [B1, T2] = False`（`subdivides` 检出内部合法链 `B1-T1-B2-T2`）。

### `W7a`、`W7b`、`W7c`（M12 `parsePens`：三大解析分歧，归类 `U-1`）
- **`W7a`（等值底分型取晚 vs 取早）**：
  - **输入**：11 根无包含 K 线（下标 0..10），`oldPenRule`：
    `[[2,12], [0,10], [1,11], [2,12], [1,11], [0,10], [1,11], [2,12], [3,13], [4,14], [3,13]]`。
    局部分型为 `B1(c=1, ext=0), T1(c=3, ext=12), B2(c=5, ext=0), T2(c=9, ext=14)`。
  - **甲方（Opus）**：输出 1 笔 **`B2(c=5) -> T2(c=9)`**（`rawSpan = 5..9`，等值取较晚可成笔分型）。
  - **乙方（Astra）**：输出 1 笔 **`B1(c=1) -> T2(c=9)`**（`source = 1..9`，等值取较早分型）。
- **`W7b`（`069:20` 反证回溯 vs 全局 DP 末端极值误选）**：
  - **输入**：13 根无包含 K 线（下标 0..12），`oldPenRule`：
    `[[18,19], [19,20], [16,18], [14,16], [12,14], [10,12], [15,18], [23,25], [20,22], [17,19], [14,16], [12,13], [14,15]]`。
    局部分型为 `T1(c=1, ext=20), B1(c=5, ext=10), T2(c=7, ext=25), B2(c=11, ext=12)`。
  - **甲方（Opus）**：`T2(25)` 与 `B1` 间距不足且击败 `T1(20)`，触发反证回溯撤销 `T1-B1`，输出 1 笔 **`T2(c=7, ext=25) -> B2(c=11, ext=12)`**（区间 `[12, 25]`）。
  - **乙方（Astra）**：候选链 `[B1, T1]` 与 `[B2, T2]` 等长（长 2），`preferPenPath` 仅比较末端底值 `B1(10) < B2(12)`，输出 1 笔 **`T1(c=1, ext=20) -> B1(c=5, ext=10)`**（区间 `[10, 20]`，直接吞掉后续新高 `T2(25)` 与下跌段）。
- **`W7c`（声明式饱和非唯一：保首底 1 笔 vs 弃首底 2 笔）**：
  - **输入**：13 根无包含 K 线（下标 0..12），`oldPenRule`：
    `[[2,4], [0,2], [8,10], [13,15], [11,13], [9,11], [7,9], [5,7], [9,11], [12,14], [15,17], [18,20], [16,18]]`。
    局部分型为 `B1(c=1, ext=0), T1(c=3, ext=15), B2(c=7, ext=5), T2(c=11, ext=20)`。注意 `[B1, T2]` 与 `[T1, B2, T2]` **同时满足乙方自己的 `ValidPenDecomp`**。
  - **甲方（Opus）**：从首底 `B1(0)` 延伸，忽略距近的 `T1` 与较高的 `B2`，输出 **1 笔 `B1(c=1, ext=0) -> T2(c=11, ext=20)`**。
  - **乙方（Astra）**：因路径长 3 胜过长 2，抛弃全场最低点 `B1(0)`，从半山腰输出 **2 笔 `T1(c=3, ext=15) -> B2(c=7, ext=5)` 与 `B2(c=7, ext=5) -> T2(c=11, ext=20)`**。

### `W8a` 与 `W8b`（M12 `penOnlineState`：无分型与历史小分型滞留，归类 `U-2`）
- **`W8a`（无分型短序列）**：
  - **输入**：2 根无包含 K 线 `bars = [[0, 10], [2, 12]]`。
  - **甲方（Opus）**：`penOnlineState oldPenRule bars = none`。
  - **乙方（Astra）**：`penOnlineState ⟨.up⟩ oldPenRule bars = ⟨.up, .forming⟩`。
- **`W8b`（历史出现未成笔反向分型后已创新高顺向延伸）**：
  - **输入**：6 根无包含 K 线 `bars = [[2,12], [0,10], [3,13], [1,11], [4,14], [6,16]]`（下标 0..5），`oldPenRule`。双方唯一保留分型均为 `B1(c=1, ext=0)`，当前笔方向 `.up`。
  - **甲方（Opus）**：因 `fs` 中存在历史未成笔顶分型 `T1(c=2)`，`fs.any` 恒真，输出 **`some ⟨.up, .building⟩`**（即使最新已涨至 16 仍滞留构造态）。
  - **乙方（Astra）**：末两根 `[4,14] < [6,16]` 为 `strictUp`，与当前笔同向，输出 **`⟨.up, .extending⟩`**。

### `W9`（M13 `SegRuleConfig`：答疑冲突配置能力分离）
- **输入**：6 笔严格交替共端笔序列 `p0(up 0->10), p1(down 10->5), p2(up 5->20), p3(down 20->10), p4(up 10->18), p5(down 18->12)`（转折点 `p2` 后第一笔 `p3` 封闭缺口，第三笔 `p5` 落于 `p3` 内部未破 10）。
- **甲方（Opus）**：可在配置 `⟨.anyThreePens, .eachTurningPoint⟩`（对应 `[二级旁证 067:194]`）下在 `p2` 结束切出 2 段，在 `.main`（对应 `071:30-32`）下输出 1 段；亦可配置 `.extremeVertex` 对照 `[二级旁证 081:222]`。
- **乙方（Astra）**：`SegRuleConfig` 仅含单点 `.chronologicalStrictBreak`，无法表达两处答疑对照分支。

### `W10`（M13 `stdFeatureSeq`：固定方向合并引发逆向级联包含）
- **输入**：`d = .up`，特征元素序列 `xs = [⟨[10, 20], 1..1⟩, ⟨[5, 15], 3..3⟩, ⟨[12, 14], 5..5⟩]`。
- **甲方（Opus）**：`stdFeatureSeq .up xs` 将后两项向上合并为 `[12, 15]` 后不再与首项 `[10, 20]` 比较，输出 **2 项 `[⟨[10, 20], 1..1⟩, ⟨[12, 15], 3..5⟩]`**（输出仍存在包含关系 `[10, 20].contains [12, 15]`，违背 `067:20` 标准特征序列无包含性质）。
- **乙方（Astra）**：`stdFeatureSeq .up xs none` 经 `pushFeature` 递归回溯，再次向上合并 `[10, 20]` 与 `[12, 15]`，输出 **1 项 `[⟨[12, 20], 1..5⟩]`**（严格无包含）。

### `W11`（M13 `Segment`：`078:20` 端顶高于端底不变式）
- **输入**：3 笔严格交替共端笔序列 `p0(up 10->20), p1(down 20->0), p2(up 0->10)`（三笔单点相触于 10 满足重叠，但首笔起点 10 与末笔终点 10 相等）。
- **甲方（Opus）**：`Segment.mk? .up 0 [p0, p1, p2] none` 返回 **`some seg`**。
- **乙方（Astra）**：`segmentOfPens 0 none [p0, p1, p2]` 因 `advances .up 10 10 = false` 返回 **`none`**（落实 `078:20`）。

### `W12a`、`W12b`、`W12c`（M13 `parseSegments`：同用主线配置下的三类实质分离）
以下三组输入均为严格交替共端的合法 `List (Pen Int)`，`start = 0`，甲方用 `.main`，乙方用 `.chronologicalStrictBreak`。

- **`W12a`（起点被第二笔跌破：自动右移起点 vs 严守调用者起点）**：
  - **输入**：4 笔 `p0(up 10->20), p1(down 20->5), p2(up 5->15), p3(down 15->2)`。
  - **甲方（Opus）**：`p1` 跌破 `origin=10` 触发 `.voided`，`segLoop` 丢弃 `p0` 右移至 `start = 1`，输出 **1 段向下 `down [2, 20]`**。
  - **乙方（Astra）**：严守 `start = 0`，前三笔 `[p0, p1, p2]` 有公共交 `[10, 15]` 且末点 `15 > 10`，输出 **1 段向上 `up [5, 20]`**（方向完全相反）。
- **`W12b`（第二种情况未成第一特征序列顶分型，但第二特征序列已成底分型）**：
  - **输入**：9 笔 `p0(up 0->15), p1(down 15->10), p2(up 10->30), p3(down 30->20), p4(up 20->30), p5(down 30->19), p6(up 19->25), p7(down 25->21), p8(up 21->28)`。
  - **甲方（Opus）**：`p3=[20,30]` 与 `p1=[10,15]` 有缺口直接进 `.caseTwo`，忽略第一特征序列后续包含合并（`p3` 与 `p5=[19,30]`、`p7=[21,25]` 向上合并后始终只剩 1 元素 `[21,30]`，未出顶分型），仅见第二特征序列 `[[20,30], [19,25], [21,28]]` 成底分型即在 `p2` 切段，随后 `[p3..p5]` 又在 `p5` 以第一种情况被 `[p6..p8]` 切段，输出 **3 段：`[up [0,30], down [19,30], up [19,28]]`**。
  - **乙方（Astra）**：按 `071:42` 对转折点后同侧特征序列合并得 `turned = false`，拒绝在 `p2` 切分；`n=5` 处 `leftTip=30` 不小于 `tip=30` 亦拒；输出 **1 段：`[up [0,30]]`**。
- **`W12c`（`stdFeatureSeq` 级联包含端到端传导至线段划分）**：
  - **输入**：10 笔 `p0(up 0->20), p1(down 20->10), p2(up 10->15), p3(down 15->5), p4(up 5->14), p5(down 14->12), p6(up 12->18), p7(down 18->10), p8(up 10->13), p9(down 13->8)`（起点 0 为全场最低，无 `.voided` 干扰）。
  - **甲方（Opus）**：前 3 特征元素 `[[10,20], [5,15], [12,14]]` 未回溯合并得末元素 `[12,15]`，导致 `p6` 高点 `18 > 15` 误触第一种情况破坏，输出 **2 段：`[up [0,20], down [8,18]]`**。
  - **乙方（Astra）**：级联包含合并得末元素 `[12,20]`，`18 < 20` 拒绝在 `p6` 切分，输出 **1 段：`[up [0,20]]`**。

### `W13`（M14 `segmentBase`：端到端管线与参数签名分离）
- 签名分离：甲方暴露 `SegRuleConfig`（4 参），乙方硬编码 `.chronologicalStrictBreak`（3 参）。
- 行为分离：在端到端 K 线输入上直接继承 `W1`（`.pending`）、`W7a..W7c`（成笔输入扩展至三笔段）及 `W12a..W12c`（对应 K 线实现）全部输出差异。

### `W14`（M14 `fractalDirectBase`：`pending` 策略传导分离）
- **输入**：6 根原始 K 线 `[[10,20], [12,18], [11,19], [12,20], [11,19], [12,20]]`（下标 0..5）。
- **甲方（Opus）**：`fractalDirectBase .pending` 将全部 6 根外包吞并为 1 根 `[10, 20]`，输出 **`[]`（0 段）**。
- **乙方（Astra）**：
  - `fractalDirectBase ⟨.up⟩` 合并为 5 根交替序列 `[12,20], [11,19], [12,20], [11,19], [12,20]`，扫出 `B(2), T(3), B(4)`，输出 **2 段：`[up [11,20] (2..3), down [11,20] (3..4)]`**。
  - `fractalDirectBase ⟨.down⟩` 合并为 `[10,18], [11,19], [12,20], [11,19], [12,20]`，扫出 `T(3), B(4)`，输出 **1 段：`[down [11,20] (3..4)]`**。
- **注**：在相同 `up`/`down` 策略下，双方 `fractalDirectBase` 内部直连算法逐分支完全等价。

### `W15`（M14 `klineOverlapBase`：消包含 vs 原始区间单端定向，归类 `U-3`）
- **输入**：3 根原始 K 线 `[[10, 20], [10, 25], [10, 18]]`（下标 0, 1, 2；相邻均存在单端相等的包含关系）。
- **甲方（Opus）**：无论选 `.defaultUp`、`.defaultDown` 还是 `.pending`，`klineNormalize` 均合为 1 根，输出 **`[]`（0 段）**。
- **乙方（Astra）**：不做包含处理，`rangeStep [10,20] [10,25] = some .up`，`rangeStep [10,25] [10,18] = some .down`，输出 **2 段：`[up [10,25] (0..1), down [10,25] (1..2)]`**。

### `W16`（M14 `tickBase`：平价成交跨度丢弃 vs 连续保留）
- **输入 A（开头持平）**：3 笔严格递增时间戳成交 `[⟨0, 10⟩, ⟨1, 10⟩, ⟨2, 15⟩]`。
  - **甲方（Opus）**：`tickSteps` 跳过平价对 `(0, 1)`，输出 1 段 `up [10, 15]`，**`source = ⟨1, 2⟩`**（丢弃时刻 0）。
  - **乙方（Astra）**：`priceRuns` 将平价点并入首段，输出 1 段 `up [10, 15]`，**`source = ⟨0, 2⟩`**。
- **输入 B（转折平台）**：4 笔成交 `[⟨0, 10⟩, ⟨1, 15⟩, ⟨2, 15⟩, ⟨3, 12⟩]`。
  - **甲方（Opus）**：输出两段跨度 `⟨0, 1⟩` 与 `⟨2, 3⟩`，在平台 `1..2` 断开。
  - **乙方（Astra）**：输出两段跨度 `⟨0, 2⟩` 与 `⟨2, 3⟩`，在时刻 `2` 首尾衔接。

---

## 4. 待 `needs-fable` 裁定轴（共 3 项：`U-1` 至 `U-3`）

### `U-1`：M12 `parsePens` 的等值破平方向与非唯一声明式分解的确定性主线裁定
- **对应公开定义**：`parsePens`（并传导至 `segmentBase`）。
- **原典留白与数学事实**：
  1. `077:54` 规定同性质等值分型“都可以先保留”，未规定当先后两个等值分型均能与后继相反分型成笔时（`W7a`），应取较早端点（Astra）还是较晚端点（Opus）。
  2. `W7c` 证明：即使在 `oldPenRule` 与极严格的饱和谓词 `Astra.ValidPenDecomp` 下，合法无包含 K 线序列的笔分解仍可不唯一（`[B1, T2]` 与 `[T1, B2, T2]` 均饱和）。原典 `077:40` 的唯一性宣称需在形式化主线通过显式确定性选优规则补全。
  3. 同时 `W7b` 暴露乙方全局 DP 在同长链末点比较时会违背 `069:20` 反证回溯（丢弃后续新高 `T2(25)`）。
- **对撞官推荐方案**：主线确立“**在线从左至右 + 保首极值优先 + 完整多步反证回溯**”为主线确定性解析算法（修复甲方单步回溯边界并排除乙方 `W7b`/`W7c` 抛弃极值问题），并由裁定明确等值均可成笔时的默认破平方向（建议默认**取较早者**以与 M10 合并极值下标并列取早一致，或将等值破平作为 `PenRule` 可选字段）。

### `U-2`：M12 `penOnlineState` 的无分型返回值与四态切换精确判据
- **对应公开定义**：`penOnlineState`。
- **原典留白**：`091:28-30` 提出 `(方向 ±1, 阶段 0/1)` 四态数组，但未给出：(a) 历史不足以形成首个保留分型时的定义域策略（`Option` 偏函数 vs 借 `InitIncludePolicy` 返回总函数，`W8a`）；(b) “分型构造中 (0)”与“确认延伸为笔中 (1)”之间的精确边界（甲方“历史上曾出现未成笔反向分型”会永久卡死于 `.building`，见 `W8b`；乙方“末两根合并 K 线同向即 `.extending`、逆向即 `.forming`”简洁但忽略分型三根确认过程）。
- **对撞官推荐方案**：无保留分型时采用 `Option PenOnlineState` 返回 `none`（不凭空伪造笔方向）；有保留分型时采用乙方思路的精确修复版：若末段处于顺向（且未形成尚未被新高/新低否决的反向局部分型）为 `.extending`，若末步逆向或正处于有效反向局部分型后回落期为 `.forming`（`building`）。

### `U-3`：M14 `klineOverlapBase` 是否前置 M10 包含处理及单端相等包含的方向归属
- **对应公开定义**：`klineOverlapBase`。
- **原典留白**：`017:40` 与 `018:58` 早于 62 课包含处理提出，未指明最低级别 K 线重叠基底切分为 M4 `AltSeq` 前是否应先作 M10 包含处理；若跳过包含处理，依据分叉 4 单端相等（如 `[10, 20]` 到 `[10, 25]`）属于包含关系，将其直接判为严格方向推进（乙方 `rangeStep`，见 `W15`）还是判无方向并入当前段，现有裁定均未锁死。
- **对撞官推荐方案**：若追求与 M10 分叉 4 绝对自洽，应**先经 M10 `klineNormalize`（或仅在 `strictUp`/`strictDown` 时判向、一切包含对均作无方向吸收）**，避免出现同一份原始 K 线在 M10 判作包含、在 M14 `klineOverlapBase` 却判作涨跌换向的口径撕裂。

---

## 5. 七大高风险分歧面深度剖析

### 面一：M10 `Kline.lean`（开头包含策略、元数据追踪与 3+ 连续包含链）
- **方向继承与无包含不变式**：双方对 3 根以上连续包含链均严格按顺序原则保持当前 `Dir` 不变，且可证在无包含触发换向后，后续顺向合并的新区间只会沿该方向单调推移，绝不会与已落定前一根重新产生包含关系（对 `.up`、`.down` 乃至 Opus `.pending` 均成立）。
- **开头即包含**：Opus 引入第三态 `.pending` 并以 `hullInterval` 外包合并，虽满足无包含不变式，但 `hullInterval` 并非 `062:28` 的包含合并算子（它会撑宽区间，如 `W1` 与 `W14` 所示吞并后续独立 K 线）。Astra 仅二态 `Dir` 更贴合 `062:28`，若未来确需“待定”，亦应明确是“外包吸收”还是“暂存后按首个严格方向回补重算”。
- **元数据与极值下标**：双方对并列极值下标均保留较早者，区间与下标更新在 `up`/`down` 下完全同构；Astra 将 `rawCount` 定义为由 `source : Span` 派生的函数，比 Opus 独立存储 `rawCount : Nat` 更安全，无失配风险。

### 面二：M11 `Fractal.lean`（`classifyTriple`、两种分型类型分离与 `fractalEdge`）
- **`classifyTriple` 域边界**：Opus 写成全函数且末分支兜底 `.down`，在包含或等端输入上既误报方向又破坏 `OrderDual` 对称性（`W2`）；Astra 复用上游 `Bar.strictUp`/`Bar.strictDown` 返回 `Option TripleKind`，定义域精准、完全对称。
- **`LocalFractal` 与 `RetainedFractal` 严格分离（`#2321` 专项要求二）**：Opus 仅以空壳 `structure RetainedFractal where base : LocalFractal P` 区分名义类型，不携带任何结合律证明；Astra 在 `RetainedFractal` 中显式记录 `previous : Option (LocalFractal P)` 与 `separated` 证明（异性且 `p.first + 3 ≤ pivot.first`），将 `077:34` 结合律真正编码进类型系统（`W3`）。
- **`fractalEdge`**：双方完全等价，均取三根分型凸包区间下沿（顶分型）或上沿（底分型），仅作结构特征接口，严守 B-36 不作充分条件。

### 面三：M12 `Pen.lean`（四种规则、高低口径、回溯解析与在线四态）
- **参数化笔规则**：`PenRule`、`oldPenRule`、`newPenRule`、`sixBarPenRule` 双方数值完全一致（老笔 `⟨4, 0, false⟩`，新笔 `⟨3, 3, false⟩`，六根笔 `⟨3, 4, false⟩`）；仅 `disjointFractalPenRule` 在“固定常值 `⟨3, 0, true⟩`”与“叠在新笔上的修饰函数默认 `⟨3, 3, true⟩`”上分离（`W4`）。
- **顶底高低口径与包络约束（`077:38`）**：
  - Opus `PenHeightOK` 不论方向一律只检 `底.mid.hi < 顶.mid.hi`，打破 `OrderDual` 对称性（`W5b`），且不检查中间 K 线极值包络（`W5a`）。
  - Astra 升笔检 `a.mid.hi < b.mid.hi`、降笔检 `b.mid.lo < a.mid.lo`，在 `OrderDual` 下精确对称；进一步推演可证：在合法无包含规范形 `bars` 上，Astra 的单边条件叠加中间 K 线极值包络约束与顶底分型定义，**自动蕴含双边严格偏序 `底.mid.strictUp 顶.mid`**！融合版宜直接写明 `底.mid.strictUp 顶.mid` 并保留包络约束，使其在全域兼具 `OrderDual` 对称与时间反演对称。
- **声明式谓词 vs 解析算法**：Astra 的 `ValidPenDecomp` 远胜 Opus（Opus 遗漏空表、首前驱与笔内细分，`W6a`/`W6b`）；但在确定性解析 `parsePens` 上，Astra 的“全局最多笔数 DP + 末端极值比较”反而在 `069:20` 反证案 `W7b` 倒退丢弃新高，并在 `W7c` 抛弃全场最低点从半山腰起笔。此处需按 `U-1` 裁定后综合重构。

### 面四：M13 `Segment.lean`（答疑配置、包含范围、一二种情况、端点非极值与 `AltSeq`）
- **答疑冲突配置（`067:194` vs `071:30`、`071:40` vs `081:222`）**：Opus 用 2x2 `SegRuleConfig` 显式暴露两种对照臂且默认 `.main` 锁死正文；Astra 仅留 1 态单位类型 `.chronologicalStrictBreak`（`W9`）。
- **标准特征序列的固定方向级联包含（重大隐蔽分歧）**：因特征序列按固定段方向（而非动态相邻方向）合并，当出现下降排列后的内部包含时（如 `W10` 的 `[[10,20], [5,15], [12,14]]`），向上合并后两项得 `[12,15]` 会反被前项 `[10,20]` 包含！Opus 单步合并漏检此级联，产出含包含非法序列，且直接导致 `parseSegments` 误切线段（`W12c`）；Astra 的递归栈 `pushFeature` 彻底消除级联包含，且显式用 `boundary : Option Nat` 清晰区分 `071:42`（跨假设分界不合并）与 `078:54`（第二特征序列全程合并）。
- **第一种与第二种情况及起点处理**：
  - Opus 在第二种情况（`.caseTwo`）中完全未检验第一特征序列经 `071:42` 包含合并后是否形成顶/底分型，导致 `W12b` 误切出 3 段；Astra 用 `turned && counter` 同时把关两列分型，忠于 `067:38`。
  - Opus 的 `.voided` 在反向第二笔越过起点时悄悄丢弃首笔并右移起点（`W12a`），不仅违背调用者指定起点语义，在中段接续时还会破坏 `078:42` 合法出现的“起点非极值古怪线段”，被迫靠 `coalesceSegs` 兜底强合并同向段。Astra 严守调用者起点且以 `Segment.forward` 落实 `078:20`（`W11`），架构明显更干净。
- **端点非极值与 `standardizeSegment`**：双方均保留整段实际凸包区间输出为 M4 `AltSeq`，并独立提供 `standardizeSegment` 视图，均符合 B-9 与 `070:48`/`078:58`。

### 面五：M14 `Instance.lean`（防跨基底混比与四种基底退化边界）
- **类型级防跨基底混比（B-26）**：双方均以 `BaseTag` 索引 `BaseInterface`。差异在于下游投影：Opus 用 `BaseOutput tag P` 锁住基底产出序列使其不可跨基底混用，但未定义级别类型；Astra 用 `BaseLevel tag` 与 `BaseLevel.atMost` 锁住递归深度比较，但 `build` 直接返回裸 `AltSeq P`。二者天然互补，融合时建议同时保留。
- **四种基底退化与边界**：
  - `segmentBase` 继承 M10/M12/M13 分离；
  - `fractalDirectBase` 在 `up`/`down` 下完全等价，仅因 Opus `.pending` 在 `W14` 分离；
  - `klineOverlapBase` 暴露了“是否前置包含处理”与“单端相等算包含还是算方向”的本质分歧（`W15`，归 `U-3`）；
  - `tickBase` 上 Astra 静态要求时间戳严格递增且连续保留开头/转折/尾部的平价成交跨度，比 Opus 丢弃平价跨度产生时间断层（`W16`）更严谨。

### 面六：上游 M0/M2/M3/M4 复用与 `OrderDual` 多空对称性
- **上游复用**：Astra 全面复用 `Bar.strictUp`/`Bar.strictDown`、`overlapsList`、`hullInterval`、`gapUp`/`gapDown` 与 Mathlib `List.IsChain`；Opus 复用了 `Bar.contains`、`hullInterval`、`gapUp`/`gapDown`、`overlapsList?`、`AltSeq`，但在 M11/M12 手写了 `IsTopTriple`/`IsBottomTriple`/`FractalDisjointPart` 并用 `zip/tail` 替代 `List.IsChain`。
- **`OrderDual` 对称性审计结果**：
  - **甲方（Opus）发现 2 处对称性破坏**：M11 `classifyTriple` 域外恒落 `.down`（`W2`）；M12 `ValidPenPair`/`PenHeightOK` 恒检高点 `mid.hi`（`W5b`）。
  - **乙方（Astra）核心构造全链路满足 `OrderDual` 对称性**（仅需注意 M12 `penOnlineState` 若误喂未消包含等值 K 线，末步 `strictUp` 回退 `.down`，而在无包含规范形定义域内完全对称）。

### 面七：引文与规范门禁初筛
- 逐文件全量核对 10 份源码文档串：
  - 甲方（Opus）：全部引文逐字匹配 `02-citations.md`；所引二级旁证（`081:110`、`099:56`、`067:194`、`081:222`、`102:346`）全部显式带 `[二级旁证 ...]` 标签。
  - 乙方（Astra）：全部引文逐字匹配 `02-citations.md`（甚至保留了 `067:16` 原文中的不间断空格字符）；所引二级旁证（`081:110`、`099:56`、`067:194`、`081:222`）全部显式带 `[二级旁证 ...]` 标签。
  - 双方均满足 `#2312` 阻断门硬规范（`module` 首行、`@[expose] public section`、无禁用关键字、无 `Chan.Proxy` 导入、无编者注或娇注）。

---

## 6. 下游融合蓝图（`decl/fm10d-base` 逐模块选型表）

| 模块 | 公开定义 | 推荐选型 | 具体融合与修复要求 |
|---|---|---|---|
| M10 | `InitIncludePolicy`, `klineNormalize` | **采纳乙（可选扩充）** | 主线优先采用乙方二态 `InitIncludePolicy`（忠于 `062:28`）；若经评审需保留第三态 `pending`，须明确其是外包吸收还是延迟重算，不得与 `up`/`down` 混用 |
| M10 | `MergedBar`, `hasInclusion`, `mergePair`, `IsInclusionFree` | **采纳乙** | 采用乙方派生 `rawCount`、封装元数据更新的 `mergePair` 与 `List.IsChain` 版本的 `IsInclusionFree` |
| M11 | 全部 7 项（`TripleKind` 至 `fractalEdge`） | **采纳乙** | 完整采用乙方 `Option TripleKind`、`first : Nat` 编码与带 `previous`/`separated` 证明的 `RetainedFractal` |
| M12 | `PenRule`, 3 组基础规则, `disjointFractalPenRule` | **采纳乙** | 采用高阶修饰器 `disjointFractalPenRule (rule : PenRule := newPenRule)` |
| M12 | `Pen`, `ValidPenPair`, `ValidPenDecomp` | **采纳乙并微修** | 保留乙方 `Pen.linked`、`ValidPenDecomp` 饱和三检与 `ValidPenPair` 包络约束；将 `ValidPenPair` 端点高低显式强化为双边 `底.middle.range.strictUp 顶.middle.range`，实现全域 `OrderDual` 与时间反演双重对称 |
| M12 | `parsePens` | **待 `U-1` 裁定后综合修复** | 锁定 `U-1`（等值取早/取晚 + 保首极值优先）后，基于乙方类型体系重构“在线从左至右 + 多步反证回溯”解析器，修复乙方 `W7b`/`W7c` 缺陷并补充甲方缺失的中间极值包络与多步回溯 |
| M12 | `PenPhase`, `PenOnlineState`, `penOnlineState` | **待 `U-2` 裁定后综合修复** | 采纳甲方 `Option PenOnlineState`（附 `.code`）处理无分型情形，阶段判定以乙方末步方向为基线并结合有效反向局部分型修复甲方 `W8b` 永久滞留问题 |
| M13 | `SegRuleConfig` | **采纳甲（接入乙引擎）** | 采纳甲方 2x2 参数化 `SegRuleConfig`（默认 `main` 锁死正文），使两处答疑冲突可被下游审计显式对照 |
| M13 | `FeatureElem`, `featureSeq`, `hasFeatureGap`, `stdFeatureSeq`, `SegTermKind`, `Segment`, `parseSegments`, `standardizeSegment` | **采纳乙（扩展配置分支）** | 以乙方全部 M13 引擎为基底（保留 `pushFeature` 递归防级联包含、`boundary` 分界、`Segment.chain`/`forward`、严守起点、`turned && counter` 双分型检验），再接入 `SegRuleConfig` 的答疑对照分支 |
| M14 | `BaseTag`, `Tick`, `BaseInterface` | **综合甲乙** | 保留乙方 `BaseLevel tag`（防跨基底深度混比）并引入甲方 `BaseOutput tag P`（或于接口同时提供带标签产出），全面落实 B-26 |
| M14 | `segmentBase`, `fractalDirectBase`, `tickBase` | **采纳乙（补 `cfg` 参数）** | `segmentBase` 补充 `SegRuleConfig` 参数（默认正文主线）；`fractalDirectBase` 与 `tickBase` 采纳乙方实现（保留时间递增子类型与平价连续跨度） |
| M14 | `klineOverlapBase` | **待 `U-3` 裁定** | 锁定是否前置 M10 包含处理及单端相等包含的方向归属后落地（建议与 M10 分叉 4 保持一致，不把包含对判为方向推进） |

---

## 7. 下游形式化分离定理蓝图（`audit/fm10d-collision`）

建议在 `formal_math/Chan/Audit/Separation/Fm10dSeparation.lean` 中导入甲乙双方的隔离副本命名空间（如 `Opus` 与 `Astra`），全部在 `P := Int` 上以有限常量列表 + `decide`（或 `rfl`）证成以下 **14 条核心分离定理**（精确覆盖全部 16 组见证中的核心分离面）：

| 编号 | 定理名建议 | 对应见证 | 目标分离性质（可 `decide` 核验） |
|---|---|---|---|
| 1 | `sep_klineNormalize_pending` | `W1` | 3 根 K 线 `[[10,20],[12,18],[11,19]]` 上，Opus `.pending` 输出长度 `1`，而对任意 `d : Dir`，Astra `⟨d⟩` 输出长度 `2` |
| 2 | `sep_classifyTriple_domain_and_dual` | `W2` | `([0,10],[0,10],[0,10])` 与 `([0,5],[2,10],[3,8])` 上，Opus 输出 `.down`/`.up`（且破坏 `OrderDual`），Astra 输出 `none` |
| 3 | `sep_retainedFractal_shared_bar` | `W3` | 4 根无包含 K 线扫出的相邻共根分型 `f1, f2`，Opus 可构造 `Pen.ofPair ⟨f1⟩ ⟨f2⟩`，而 Astra `RetainedFractal` 后继类型空缺（`¬ (0 + 3 ≤ 1)`） |
| 4 | `sep_disjointFractalPenRule_default` | `W4` | 6 根无包含 K 线（中心距 3、原始极值距 2、区间不交），Opus 产出 `1` 笔，Astra 默认修饰器产出 `0` 笔 |
| 5 | `sep_validPenPair_envelope_and_dual` | `W5a`, `W5b` | 7 根序列中间下破时 Opus `ValidPenPair` 为真而 Astra 为假；单对分型翻转 `OrderDual` 后 Opus `PenHeightOK` 真值翻转而 Astra 守恒 |
| 6 | `sep_validPenDecomp_empty_and_skip` | `W6a`, `W6b` | 3 根含分型序列空分解 `[]` 与 15 根序列跳笔分解 `[B1, T2]`，Opus `ValidPenDecomp` 均为真而 Astra 均为假 |
| 7 | `sep_parsePens_tie_break` | `W7a` | 11 根双等值底序列，Opus 输出起止下标 `5..9`（取晚），Astra 输出 `1..9`（取早） |
| 8 | `sep_parsePens_contradiction_backtrack` | `W7b` | 13 根 `069:20` 反证序列，Opus 正确回溯输出 `[12, 25]`，Astra 倒退输出 `[10, 20]` |
| 9 | `sep_parsePens_nonunique_saturated` | `W7c` | 13 根序列证成 `[B1, T2]` 与 `[T1, B2, T2]` **均满足 `Astra.ValidPenDecomp`**，且 Opus 输出 1 笔、Astra 输出 2 笔 |
| 10 | `sep_penOnlineState_empty_and_sticky` | `W8a`, `W8b` | 2 根序列 Opus 为 `none` 而 Astra 有值；6 根新高延伸序列 Opus 滞留 `.building` 而 Astra 为 `.extending` |
| 11 | `sep_stdFeatureSeq_cascade_inclusion` | `W10` | `[[10,20],[5,15],[12,14]]` 向上标准化，Opus 输出长度 `2` 且仍满足 `hasInclusion`，Astra 输出长度 `1` 且无包含 |
| 12 | `sep_segment_forward_and_parse` | `W11`, `W12a`, `W12b`, `W12c` | (a) 端顶等于端底 3 笔 Opus 接受、Astra 拒绝；(b) 4 笔破起点序列 Opus 输出 `down`、Astra 输出 `up`；(c) 9 笔缺口无顶分型序列 Opus 输出 3 段、Astra 输出 1 段；(d) 10 笔级联包含序列 Opus 输出 2 段、Astra 输出 1 段 |
| 13 | `sep_fractalDirect_and_klineOverlap` | `W14`, `W15` | 6 根输入 `fractalDirectBase` Opus `.pending` 0 段 vs Astra `⟨.up⟩` 2 段 / `⟨.down⟩` 1 段；3 根输入 `klineOverlapBase` Opus 全策略 0 段 vs Astra 2 段 |
| 14 | `sep_tickBase_flat_span` | `W16` | `[⟨0,10⟩, ⟨1,10⟩, ⟨2,15⟩]` 上 Opus 产出 `source = ⟨1, 2⟩`，Astra 产出 `source = ⟨0, 2⟩` |
