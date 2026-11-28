module

public import Chan.Defs.Alt.Zigzag
public import Chan.Defs.Center.Center
public import Chan.Defs.Level.Canonical
public import Chan.Defs.Order.Bar
public import Chan.Defs.Path.History
public import Chan.Defs.Signal.Phase
public import Chan.Defs.Signal.Points
import Mathlib.Algebra.BigOperators.Fin
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Algebra.Order.Archimedean.Basic
public import Mathlib.Algebra.Order.Field.Basic
public import Mathlib.Algebra.Order.Field.Rat
public import Mathlib.Algebra.Order.Ring.Rat
public import Mathlib.Data.Fintype.Fin
public import Mathlib.Data.Rat.Cast.Order
public import Mathlib.Order.Filter.AtTopBot.Basic
public import Mathlib.Order.Filter.EventuallyConst
import Mathlib.Tactic.FinCases
import Mathlib.Tactic.IntervalCases
import Mathlib.Tactic.Linarith
import Mathlib.Tactic.NormNum
import Mathlib.Tactic.Positivity
import Mathlib.Tactic.Ring

/-!
# FM-10e 盲写分离见证（#2322）

甲方 `d722b1703fecbdcd23458f671b6831f470049904`，乙方 `b2bfc504fcb2a6a29c664f46c8e3f89abce65c06`。
两个命名空间只重建模块边界；每个原始公开段（含本地作用域和文档）逐字节嵌入。
动力学研究类同样内嵌，审计模块不导入研究库。独立对照与定理写在嵌入之后。
-/

@[expose] public section

namespace Opus

section Source0
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Proxy/Ema.lean

namespace Chan.Proxy

/-- 指数均线播种方式：`firstValue` 以首值 `x 0` 播种；`given pre` 显式给定第 0 根之前的初值 `pre`。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
inductive EmaSeed where
  /-- 首值播种：`ema 0 = x 0`。 -/
  | firstValue : EmaSeed
  /-- 显式初值播种：`pre` 视为第 0 根之前的均线值。 -/
  | given (pre : ℚ) : EmaSeed

/-- 指数均线参数：周期 `N`（`0 < N`）与播种方式；平滑系数 `alpha = 2 / (N + 1)` 由周期导出。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure EmaParams where
  /-- 周期 `N`。 -/
  period : ℕ
  /-- 周期正性。 -/
  period_pos : 0 < period
  /-- 播种方式。 -/
  seed : EmaSeed

/-- 精确有理衰减因子 `q_N = (N - 1) / (N + 1)`；例如 `q_12 = 11/13`、`q_26 = 25/27`。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def emaDecay (N : ℕ) : ℚ := ((N : ℚ) - 1) / ((N : ℚ) + 1)

/-- 平滑系数 `alpha = 2 / (N + 1)`，与衰减因子满足 `alpha + emaDecay N = 1`。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def EmaParams.alpha (p : EmaParams) : ℚ := 2 / ((p.period : ℚ) + 1)

/-- 第 0 根的指数均线值（按播种方式）。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def EmaParams.init (p : EmaParams) (x0 : ℚ) : ℚ :=
  match p.seed with
  | EmaSeed.firstValue => x0
  | EmaSeed.given pre => p.alpha * x0 + emaDecay p.period * pre

/-- 指数均线序列：`ema (t+1) = alpha * x (t+1) + q_N * ema t`，起点由播种方式给出。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def emaSeq (p : EmaParams) (x : ℕ → ℚ) : ℕ → ℚ
  | 0 => p.init (x 0)
  | t + 1 => p.alpha * x (t + 1) + emaDecay p.period * emaSeq p x t

/-- 窗口宽度 `N` 的简单移动平均；历史不足 `N` 根时取已有 `t + 1` 根的平均。

[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def smaSeq (N : ℕ) (x : ℕ → ℚ) (t : ℕ) : ℚ :=
  (Finset.sum (Finset.range (min N (t + 1))) fun i => x (t - i)) / ((min N (t + 1) : ℕ) : ℚ)

/-- 带旧价带距 `delta` 的精确有理零轴回拉界参数（`#2322` 评论 1 订正一）。

当下时刻 `t`，最近 `n` 根（`9 ≤ n`）落在价格带 `[lo, lo + R]` 内；更早价格（及显式初值）
到该价格带的最大距离为 `delta`。界只针对 `DIF`：
`|DIF| ≤ A * R + (q_26^n - q_12^n) * delta`，`q_12 = 11/13`，`q_26 = 25/27`，
`A = (25/27)^9 - (11/13)^9`（精确有理数，不取小数近似）；`DEA` 需用卷积后的核另行表述。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
structure ZeroAxisBoundData where
  /-- 当下时刻。 -/
  t : ℕ
  /-- 最近窗口根数。 -/
  n : ℕ
  /-- 窗口至少 9 根。 -/
  n_ge : 9 ≤ n
  /-- 窗口不超出已有历史。 -/
  n_le : n ≤ t + 1
  /-- 价格带下沿。 -/
  lo : ℚ
  /-- 价格带宽。 -/
  R : ℚ
  /-- 带宽非负。 -/
  R_nonneg : 0 ≤ R
  /-- 更早价格到价格带的最大距离。 -/
  delta : ℚ
  /-- 带距非负。 -/
  delta_nonneg : 0 ≤ delta

namespace ZeroAxisBoundData

/-- 精确常数 `q_12 = 11/13`。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def q12 : ℚ := 11 / 13

/-- 精确常数 `q_26 = 25/27`。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def q26 : ℚ := 25 / 27

/-- 精确常数 `A = (25/27)^9 - (11/13)^9`。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def coefA : ℚ := q26 ^ 9 - q12 ^ 9

/-- 零轴回拉界右端 `A * R + (q_26^n - q_12^n) * delta`。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def bound (d : ZeroAxisBoundData) : ℚ :=
  coefA * d.R + (q26 ^ d.n - q12 ^ d.n) * d.delta

/-- 最近 `n` 根落在价格带 `[lo, lo + R]` 内。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def RecentInBand (d : ZeroAxisBoundData) (x : ℕ → ℚ) : Prop :=
  ∀ i, i < d.n → d.lo ≤ x (d.t - i) ∧ x (d.t - i) ≤ d.lo + d.R

/-- 更早价格（时刻 `s` 满足 `s + n ≤ t`）到价格带的距离不超过 `delta`。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def EarlierWithinDelta (d : ZeroAxisBoundData) (x : ℕ → ℚ) : Prop :=
  ∀ s, s + d.n ≤ d.t → d.lo - d.delta ≤ x s ∧ x s ≤ d.lo + d.R + d.delta

/-- 显式初值（若有）到价格带的距离不超过 `delta`；首值播种无额外条件。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def SeedWithinDelta (d : ZeroAxisBoundData) : EmaSeed → Prop
  | EmaSeed.firstValue => True
  | EmaSeed.given pre => d.lo - d.delta ≤ pre ∧ pre ≤ d.lo + d.R + d.delta

end ZeroAxisBoundData

end Chan.Proxy
-- SOURCE END Opus Chan/Proxy/Ema.lean
end Source0

section Source1
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Proxy/Macd.lean

namespace Chan.Proxy

/-- MACD 参数：短周期、长周期、信号周期与两处播种方式；标准配置 `(12, 26, 9)` 不写死在通用定义里。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure MacdParams where
  /-- 短周期。 -/
  fast : ℕ
  /-- 长周期。 -/
  slow : ℕ
  /-- 信号周期。 -/
  sig : ℕ
  /-- 短周期正性。 -/
  fast_pos : 0 < fast
  /-- 短周期严格小于长周期。 -/
  fast_lt_slow : fast < slow
  /-- 信号周期正性。 -/
  sig_pos : 0 < sig
  /-- 两条价格均线的播种方式。 -/
  seed : EmaSeed
  /-- 信号线的播种方式。 -/
  sigSeed : EmaSeed

/-- 标准参数 `(12, 26, 9)`，播种方式仍须显式给出。

[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def MacdParams.standard (seed sigSeed : EmaSeed) : MacdParams where
  fast := 12
  slow := 26
  sig := 9
  fast_pos := by decide
  fast_lt_slow := by decide
  sig_pos := by decide
  seed := seed
  sigSeed := sigSeed

/-- 短周期均线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.fastEma (p : MacdParams) : EmaParams := ⟨p.fast, p.fast_pos, p.seed⟩

/-- 长周期均线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.slowEma (p : MacdParams) : EmaParams :=
  ⟨p.slow, Nat.lt_trans p.fast_pos p.fast_lt_slow, p.seed⟩

/-- 信号线参数。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdParams.sigEma (p : MacdParams) : EmaParams := ⟨p.sig, p.sig_pos, p.sigSeed⟩

/-- MACD 单点三分量：`dif`、`dea` 与柱值 `hist`（系数 2 版本）。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
structure MacdPoint where
  /-- 快慢均线差。 -/
  dif : ℚ
  /-- `dif` 的信号均线。 -/
  dea : ℚ
  /-- 柱值 `2 * (dif - dea)`。 -/
  hist : ℚ

/-- 无系数柱值 `dif - dea`，与 `hist` 相差因子 2。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def MacdPoint.histRaw (m : MacdPoint) : ℚ := m.dif - m.dea

/-- `dif` 序列。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def difSeq (p : MacdParams) (x : ℕ → ℚ) (t : ℕ) : ℚ :=
  emaSeq p.fastEma x t - emaSeq p.slowEma x t

/-- `dea` 序列（`dif` 的信号均线，其核为两次卷积，零轴界须单独表述）。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def deaSeq (p : MacdParams) (x : ℕ → ℚ) : ℕ → ℚ :=
  emaSeq p.sigEma (difSeq p x)

/-- MACD 序列。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def macdSeq (p : MacdParams) (x : ℕ → ℚ) (t : ℕ) : MacdPoint where
  dif := difSeq p x t
  dea := deaSeq p x t
  hist := 2 * (difSeq p x t - deaSeq p x t)

/-- 闭窗口 `[s, e]` 上的带号和。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def signedSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => h (s + i)

/-- 闭窗口 `[s, e]` 上的红柱和（正部和）。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def posSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的绿柱和（负部绝对值和）。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def negSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (-h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的绝对值和。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def absSum (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => abs (h (s + i))

/-- 闭窗口 `[s, e]` 上的离散正变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def posVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => max (h (s + i + 1) - h (s + i)) 0

/-- 闭窗口 `[s, e]` 上的离散负变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def negVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => max (h (s + i) - h (s + i + 1)) 0

/-- 闭窗口 `[s, e]` 上的离散全变差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def totalVar (h : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e - s)) fun i => abs (h (s + i + 1) - h (s + i))

/-- 闭窗口 `[s, e]` 上的端点差。

[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def endpointDiff (h : ℕ → ℚ) (s e : ℕ) : ℚ := h e - h s

/-- 精确零轴回拉界命题（只针对标准参数下的 `DIF`，是待检陈述而非已断言事实）：
最近 `n` 根在价格带内、更早价格与显式初值到价格带的距离不超过 `delta` 时，
`|DIF t| ≤ A * R + (q_26^n - q_12^n) * delta`。

[103:22]「就一个最简单MACD指标，0轴分为多空主导，也就是说，一旦MACD指标陷入0轴之下，那么就在对应时间单位的图表下进入空头主导，而这是必须远离的。」 -/
def ZeroAxisBoundData.DifClaim (d : ZeroAxisBoundData) (seed sigSeed : EmaSeed)
    (x : ℕ → ℚ) : Prop :=
  d.RecentInBand x → d.EarlierWithinDelta x → d.SeedWithinDelta seed →
    abs (difSeq (MacdParams.standard seed sigSeed) x d.t) ≤ d.bound

end Chan.Proxy
-- SOURCE END Opus Chan/Proxy/Macd.lean
end Source1

section Source2
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Proxy/MaArea.lean

namespace Chan.Proxy

/-- 闭窗口 `[s, e]` 内短线均线与长期均线之差的带号面积。

[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maSignedArea (maS maL : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => maS (s + i) - maL (s + i)

/-- 闭窗口 `[s, e]` 内均线差的正部面积。

[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maPosArea (maS maL : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (maS (s + i) - maL (s + i)) 0

/-- 闭窗口 `[s, e]` 内均线差的负部面积（取绝对值）。

[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maNegArea (maS maL : ℕ → ℚ) (s e : ℕ) : ℚ :=
  Finset.sum (Finset.range (e + 1 - s)) fun i => max (maL (s + i) - maS (s + i)) 0

/-- 趋势平均力度：带号面积除以窗口时长（窗口根数 `e + 1 - s`）。

[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」
[015:42]「因为这个概念是即时的，马上就可以判断当下的缠中说禅趋势平均力度与前一次缠中说禅趋势平均力度的强弱对比，一旦这次比上次弱，就可以判断“背驰”即将形成，然后再根据短线均线与长期均线的距离，一旦延伸长度缩短，就意味着真正的低部马上形成。」 -/
def maAvgForce (maS maL : ℕ → ℚ) (s e : ℕ) : ℚ :=
  maSignedArea maS maL s e / ((e + 1 - s : ℕ) : ℚ)

end Chan.Proxy
-- SOURCE END Opus Chan/Proxy/MaArea.lean
end Source2

section Source3
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Defs/Dynamics/Potential.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Order

/-- 力度比较窗口：比较前段跨度、比较后段跨度与可选锚定中枢跨度（全部为原始坐标闭跨度）。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
structure ForceWindow where
  /-- 比较前段跨度。 -/
  before : Span
  /-- 比较后段跨度。 -/
  after : Span
  /-- 可选锚定中枢跨度。 -/
  anchor : Option Span

/-- 窗口两侧的选择。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
inductive WindowSide where
  /-- 比较前段。 -/
  | before
  /-- 比较后段。 -/
  | after

/-- 取窗口某一侧的跨度。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ForceWindow.span (w : ForceWindow) : WindowSide → Span
  | .before => w.before
  | .after => w.after

/-- 前段不晚于后段开始（端点可共享）。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def ForceWindow.Ordered (w : ForceWindow) : Prop := w.before.last ≤ w.after.first

/-- 中枢全部覆盖段的来源跨度凸包。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def centerSpan {P : Type*} [LinearOrder P] (z : Center P) : Span :=
  z.more.foldl (fun s x => s.join x.source) ((z.a.source.join z.b.source).join z.c.source)

/-- 由分解中的两比较段与可选锚定中枢给出窗口（B-19）。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def ForceWindow.ofSegs {P : Type*} [LinearOrder P] (b c : Seg P) (z : Option (Center P)) :
    ForceWindow :=
  ⟨b.source, c.source, z.map centerSpan⟩

/-- 因果势函数：价格历史与时刻到标量的映射，只依赖截至该时刻的前缀；不含价格平移约束。

[二级旁证 105:442]「另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。」 -/
structure CausalPotential (R : Type*) where
  /-- 势函数值。 -/
  phi : (ℕ → R) → ℕ → R
  /-- 因果性：前缀相同则当下取值相同。 -/
  causal : ∀ (x y : ℕ → R) (t : ℕ), (∀ s, s ≤ t → x s = y s) → phi x t = phi y t

/-- 构造性实例：当下价格本身。它不具价格平移不变性，平移不变性只在端点差读数层成立。

[104:26]「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
def CausalPotential.price (R : Type*) : CausalPotential R :=
  ⟨fun x t => x t, fun _ _ t h => h t (Nat.le_refl t)⟩

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 一次正齐次性：价格历史整体乘正数，势函数值同倍缩放。

[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def PosHomogeneous (Φ : CausalPotential R) : Prop :=
  ∀ c : R, 0 < c → ∀ (x : ℕ → R) (t : ℕ), Φ.phi (fun s => c * x s) t = c * Φ.phi x t

/-- 多空镜像反号：价格历史取负，势函数值取负。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def MirrorAntiSym (Φ : CausalPotential R) : Prop :=
  ∀ (x : ℕ → R) (t : ℕ), Φ.phi (fun s => -x s) t = -Φ.phi x t

end Chan.Defs.Dynamics
-- SOURCE END Opus Chan/Defs/Dynamics/Potential.lean
end Source3

section Source4
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Defs/Dynamics/ForceSpec.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 读法：端点差或正变差。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
inductive ReadingKind where
  /-- 末值减首值。 -/
  | endpointDiff
  /-- 相邻增量正部之和。 -/
  | posVar

/-- 端点约定：`interiorOnly` 只取窗口内时刻 `[first, last]`；`leftClosed` 把前驱终点
`first - 1` 并入左端（保相邻窗口可加性）；`fromRest` 在窗口前置零参考值。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
inductive EndpointConv where
  /-- 带前驱终点的左闭约定。 -/
  | leftClosed
  /-- 纯窗口内约定。 -/
  | interiorOnly
  /-- 从静止起算约定。 -/
  | fromRest

/-- 力度三分量（势函数、读法、端点约定），全部无默认值。

[072:28]「本ID的理论，本质上分两部分，一是形态学，二是动力学，当然三就是两者的结合。」 -/
structure ForceRecipe (R : Type*) where
  /-- 势函数。 -/
  potential : CausalPotential R
  /-- 读法。 -/
  reading : ReadingKind
  /-- 端点约定。 -/
  endpoint : EndpointConv

/-- 综合力度接口：窗口、势函数、读法、端点约定四参数，全部无默认值。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
structure ForceSpec (R : Type*) extends ForceRecipe R where
  /-- 比较窗口。 -/
  window : ForceWindow

/-- 三分量配上窗口得到综合力度接口。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def ForceRecipe.withWindow {R : Type*} (rc : ForceRecipe R) (w : ForceWindow) : ForceSpec R :=
  { toForceRecipe := rc, window := w }

/-- 比较开关：严格小于，或不大于（相等也算减弱）。

[二级旁证 051:246]「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
inductive ForceCompareMode where
  /-- 严格小于。 -/
  | strictLt
  /-- 不大于。 -/
  | notGreater

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 有限列的端点差（空列为零）。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def listEndpointDiff (l : List R) : R := l.getLastD 0 - l.headD 0

/-- 有限列的正变差。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def listPosVar (l : List R) : R := ((l.zip l.tail).map fun p => max (p.2 - p.1) 0).sum

/-- 按读法从取样列提取标量。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ReadingKind.read (k : ReadingKind) (l : List R) : R :=
  match k with
  | .endpointDiff => listEndpointDiff l
  | .posVar => listPosVar l

/-- 按端点约定在跨度上取样势函数值。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def EndpointConv.sample (conv : EndpointConv) (v : ℕ → R) (sp : Span) : List R :=
  let inner := (List.range (sp.last + 1 - sp.first)).map fun i => v (sp.first + i)
  match conv with
  | .interiorOnly => inner
  | .leftClosed => v (sp.first - 1) :: inner
  | .fromRest => 0 :: inner

/-- 多空定向：向上原样，向下取负，使两侧都量“顺向”力度。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def orient (d : Dir) (x : ℕ → R) : ℕ → R :=
  match d with
  | .up => x
  | .down => fun t => -x t

/-- 在给定历史、方向与窗口一侧上评估力度。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def evalForce (spec : ForceSpec R) (d : Dir) (x : ℕ → R) (side : WindowSide) : R :=
  spec.reading.read (spec.endpoint.sample (spec.potential.phi (orient d x)) (spec.window.span side))

/-- 读数层的价格平移不变性：对任意窗口，历史整体平移不改变完整读数。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def ReadingShiftInvariant (rc : ForceRecipe R) : Prop :=
  ∀ (w : ForceWindow) (d : Dir) (x : ℕ → R) (c : R) (side : WindowSide),
    evalForce (rc.withWindow w) d (fun t => x t + c) side = evalForce (rc.withWindow w) d x side

/-- 读数层的正仿射等变性：`x ↦ a * x + b`（`0 < a`）使读数乘 `a`。

[104:18]「现代物理的一个核心概念，就是物理与几何的高度统一。」 -/
def PositiveAffineEquiv (rc : ForceRecipe R) : Prop :=
  ∀ (w : ForceWindow) (d : Dir) (x : ℕ → R) (a b : R) (side : WindowSide), 0 < a →
    evalForce (rc.withWindow w) d (fun t => a * x t + b) side =
      a * evalForce (rc.withWindow w) d x side

/-- 按开关比较两标量。

[二级旁证 051:246]「不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。」 -/
def ForceCompareMode.cmp (m : ForceCompareMode) (a b : R) : Prop :=
  match m with
  | .strictLt => a < b
  | .notGreater => a ≤ b

/-- 力度减弱：窗口后段读数按开关弱于前段读数。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def forceWeaker (spec : ForceSpec R) (m : ForceCompareMode) (d : Dir) (x : ℕ → R) : Prop :=
  m.cmp (evalForce spec d x .after) (evalForce spec d x .before)

end Chan.Defs.Dynamics
-- SOURCE END Opus Chan/Defs/Dynamics/ForceSpec.lean
end Source4

section Source5
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Defs/Dynamics/StructImpulse.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 从静止起算族的两种读法：正变差或末态速度。

[104:26]「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
inductive FromRestMode where
  /-- 自零速度起算的正变差。 -/
  | posVar
  /-- 末态速度。 -/
  | terminalVelocity

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 段的来源跨度时长（原始坐标步数）。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def segDuration (s : Seg R) : ℕ := s.source.last - s.source.first

/-- 时间跨度正性条件：只有在此条件下段斜率才是有意义的均速。

[072:40]「所谓形态学、动力学，其实很好分辨，任何涉及背驰的，都是动力学的范围，背驰是动力学的基本点之一。另外，中枢、走势的能量结构之类的东西，也属于动力学。而形态学，就是中枢、走势类型、笔、线段之类的东西。」 -/
def SegPosDuration (s : Seg R) : Prop := s.source.first < s.source.last

/-- 单段离散斜率（带方向符号的均速）：折线终点减起点，除以来源跨度时长；时长为零时按域约定取零，须配合 `SegPosDuration` 使用。

[104:26]「而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。」 -/
def segSlope (s : Seg R) : R := (s.zigEnd - s.zigStart) / ((segDuration s : ℕ) : R)

/-- 纯段内读数 `L_in`：只依赖窗口内各段的速度列。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def impulseIn (k : ReadingKind) (ws : List (Seg R)) : R := k.read (ws.map segSlope)

/-- 带前驱读数 `L_pre`：速度列前置窗口起始前一段，以保持相邻窗口可加性。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def impulsePre (k : ReadingKind) (pre : Seg R) (ws : List (Seg R)) : R :=
  k.read ((pre :: ws).map segSlope)

/-- 从参考速度起算读数 `L_zero`：速度列前置显式参考速度 `v0`（零或中枢尺度基准速度）。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def impulseZero (k : ReadingKind) (v0 : R) (ws : List (Seg R)) : R :=
  k.read (v0 :: ws.map segSlope)

/-- 从静止起算族：正变差或末态速度，由调用方显式选择，不设默认实例。

[033:34]「c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？」 -/
def impulseFromRest (m : FromRestMode) (ws : List (Seg R)) : R :=
  match m with
  | .posVar => listPosVar ((0 : R) :: ws.map segSlope)
  | .terminalVelocity => (ws.map segSlope).getLastD 0

end Chan.Defs.Dynamics
-- SOURCE END Opus Chan/Defs/Dynamics/StructImpulse.lean
end Source5

section Source6
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Defs/Dynamics/Divergence.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Order Chan.Defs.Alt Chan.Defs.Center Chan.Defs.Level Chan.Defs.Signal Chan.Defs.Path

/-- 趋势终结三分：离开最后中枢的 `c` 段且趋势背驰；无独立 `c` 段而在最后中枢内部背驰后反向离开；
最后中枢直接出现反向第三类买卖点。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」
[029:52]「以上三种情况，就完全分类了某级别背驰后的级别与力度，也就是某级别的第一类买点后将发生怎么样的情况，而第一类卖点的情况是一样的，只是方向相反。」 -/
inductive TrendEndCase where
  /-- 情形一：`c` 段离开并趋势背驰。 -/
  | divergenceExit
  /-- 情形二：中枢内部背驰后反向离开。 -/
  | consolidationReversal
  /-- 情形三：直接出现反向第三类买卖点。 -/
  | reverseThird

/-- 区间套中的一层：层深与原始坐标跨度。

[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」 -/
structure ChainLevel where
  /-- 层深。 -/
  depth : ℕ
  /-- 原始坐标跨度。 -/
  span : Span

/-- 跨度包含：`inner` 落在 `outer` 之内。

[027:38]「以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。」 -/
def SpanWithin (inner outer : Span) : Prop :=
  outer.first ≤ inner.first ∧ inner.last ≤ outer.last

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 创新高/新低（严格不等号）：顶背驰要求后段高点严格高于前段高点，底背驰对称。

[061:28]「对于65开始背驰段的内部走势，当下走到69时，并不构成任何背驰，为什么？」
[061:28]「因为背驰如果没有创新高，是不存在的。」
[二级旁证 044:234]「==创新高或新低才有背驰或盘整背驰的可能。未创新高的情况，其实可以按中枢震荡的方式去看，等于达不到上次震荡的力度，也可以用MACD等辅助看，但和背驰不是同一样东西，这在关于中枢震荡的力度判断那一课里里都有的。」 -/
def MakesNewExtreme (side : Dir) (prev cur : Seg R) : Prop :=
  match side with
  | .up => prev.range.hi < cur.range.hi
  | .down => cur.range.lo < prev.range.lo

/-- 价位 `p` 在方向 `side` 上严格越过 `level`。

[061:28]「因为背驰如果没有创新高，是不存在的。」 -/
def BeyondLevel (side : Dir) (level p : R) : Prop :=
  match side with
  | .up => level < p
  | .down => p < level

/-- 有限历史读成时间序列（越界补零；因果势函数只在历史内取样）。

[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def histSeq (h : History R) : ℕ → R := fun t => h.getD t 0

/-- 进行中的离开段：起点已确认，终点为当下（历史末位）。

[043:30]「例如，一个30分钟的走势类型，在30分钟级别进入背驰段，当然，这个背驰段并不一定就演化成背驰，因为，小级别的延伸足以使得大级别最终摆脱背驰，这与当下的走势判断相关。」 -/
def onlineLeg (cStart : ℕ) (h : History R) : Span :=
  ⟨cStart, max cStart (h.length - 1), Nat.le_max_left _ _⟩

/-- 跨度上的顺向极值：向上取最高，向下取最低。

[061:28]「因为背驰如果没有创新高，是不存在的。」 -/
def windowExtreme (side : Dir) (x : ℕ → R) (sp : Span) : R :=
  let idx := List.range (sp.last + 1 - sp.first)
  match side with
  | .up => idx.foldl (fun m i => max m (x (sp.first + i))) (x sp.first)
  | .down => idx.foldl (fun m i => min m (x (sp.first + i))) (x sp.first)

/-- 两中枢在方向 `side` 上分离（波动区间不重叠）。

[027:14]「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」 -/
def SepDir (side : Dir) (a b : Center R) : Prop :=
  match side with
  | .up => gapUp a.zone.hull b.zone.hull
  | .down => gapDown a.zone.hull b.zone.hull

/-- 在线背驰：只依赖当前有限历史 `h`。比较段 `b` 为分解中位于中枢 `z` 之前的同向段，
进行中的离开段起于 `cStart`、止于当下；创新极值与力度减弱并列。

[061:26]「要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。」 -/
def DivOnline (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Center R) (i cStart : ℕ) (h : History R) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ (centerSpan z).last ≤ cStart ∧ cStart < h.length ∧
    ∃ b, d.steps[i]? = some b ∧ b.dir = side ∧
      BeyondLevel side (edge side b.range) (windowExtreme side (histSeq h) (onlineLeg cStart h)) ∧
      forceWeaker (rc.withWindow ⟨b.source, onlineLeg cStart h, some (centerSpan z)⟩) mode side
        (histSeq h)

/-- 事后确认背驰：在线背驰成立，后续延拓 `tail` 不再刷新离开段极值，且其中出现回到中枢核边界以内的价位。

[079:52]「有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。」 -/
def DivConfirmed (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Center R) (i cStart : ℕ) (h tail : History R) : Prop :=
  DivOnline rc mode side d z i cStart h ∧
    (∀ p ∈ tail, ¬BeyondLevel side (windowExtreme side (histSeq h) (onlineLeg cStart h)) p) ∧
    ∃ p ∈ tail, ¬BeyondLevel side (edge side z.core) p

/-- 趋势背驰：`z` 为最后中枢，之前有同向分离的同级中枢；比较 `z` 两侧连接段 `b`（下标 `i`）与 `c`（下标 `j`）。

[027:14]「趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。」
[015:36]「必须注意：没有趋势，没有背驰。在盘整中是无所谓“背驰”的，这点是必须特别明确的。」 -/
def TrendDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) (i j : ℕ) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ z.stop ≤ j ∧
    (∀ w ∈ d.ledger.centers, w.start ≤ j → w.start ≤ z.start) ∧
    (∃ prev ∈ d.ledger.centers, prev.stop ≤ i ∧ SepDir side prev z) ∧
    ∃ b c, d.steps[i]? = some b ∧ d.steps[j]? = some c ∧ b.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side b c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs b c (some z))) mode side x

/-- 盘整背驰：单个同级中枢 `z` 之前没有同向分离中枢；比较 `z` 同侧相邻的两次进入/离开段。

[027:16]「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」
[027:20]「注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。」 -/
def ConsolDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) (i j : ℕ) : Prop :=
  z ∈ d.ledger.centers ∧ i < z.start ∧ z.stop ≤ j ∧
    (∀ w ∈ d.ledger.centers, w.start ≤ j → w.start ≤ z.start) ∧
    (¬∃ prev ∈ d.ledger.centers, prev.stop ≤ i ∧ SepDir side prev z) ∧
    ∃ a c, d.steps[i]? = some a ∧ d.steps[j]? = some c ∧ a.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side a c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs a c (some z))) mode side x

/-- 中枢覆盖范围之后存在顺向越过核边界的独立离开段。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」 -/
def ForwardExit (side : Dir) (d : Decomposition R) (z : Center R) : Prop :=
  ∃ j, z.stop ≤ j ∧ ∃ c, d.steps[j]? = some c ∧ c.dir = side ∧
    BeyondLevel side (edge side z.core) (edge side c.range)

/-- 中枢出现反向第三类事件。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」 -/
def ReverseExit (side : Dir) (d : Decomposition R) (z : Center R) : Prop :=
  (z.departureIndex? side.flip d.steps).isSome = true

/-- 中枢覆盖段内部两次同向段之间的背驰比较。

[027:16]「如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。」 -/
def InnerDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir) (d : Decomposition R)
    (x : ℕ → R) (z : Center R) : Prop :=
  ∃ i j, z.start ≤ i ∧ i < j ∧ j < z.stop ∧
    ∃ b c, d.steps[i]? = some b ∧ d.steps[j]? = some c ∧ b.dir = side ∧ c.dir = side ∧
      MakesNewExtreme side b c ∧
      forceWeaker (rc.withWindow (ForceWindow.ofSegs b c (some z))) mode side x

/-- 趋势终结三分谓词：以“有无顺向独立离开段”与“有无内部背驰”两道判别划分，三情形按构造互斥。

[029:16]「缠中说禅背驰-转折定理：某级别趋势的背驰将导致该趋势最后一个中枢的级别扩展、该级别更大级别的盘整或该级别以上级别的反趋势。」
[029:52]「以上三种情况，就完全分类了某级别背驰后的级别与力度，也就是某级别的第一类买点后将发生怎么样的情况，而第一类卖点的情况是一样的，只是方向相反。」 -/
def trendEndClassify (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (x : ℕ → R) (z : Center R) : TrendEndCase → Prop
  | .divergenceExit => ForwardExit side d z ∧ ∃ i j, TrendDiv rc mode side d x z i j
  | .consolidationReversal =>
      ¬ForwardExit side d z ∧ ReverseExit side d z ∧ InnerDiv rc mode side d x z
  | .reverseThird =>
      ¬ForwardExit side d z ∧ ReverseExit side d z ∧ ¬InnerDiv rc mode side d x z

/-- 某级别背驰段：构成趋势背驰或盘整背驰的那段走势类型，记其分解、方向、锚定中枢与原始跨度。

[027:22]「这里，先补充一个定义：就是在某级别的某类型走势，如果构成背驰或盘整背驰，就把这段走势类型称为某级别的背驰段。」 -/
structure DivSegment (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R) where
  /-- 所在级别的显式分解。 -/
  decomp : Decomposition R
  /-- 离开方向。 -/
  side : Dir
  /-- 锚定中枢。 -/
  center : Center R
  /-- 比较前段下标。 -/
  enter : ℕ
  /-- 背驰段下标。 -/
  leave : ℕ
  /-- 背驰段原始跨度。 -/
  span : Span
  /-- 跨度取自分解中的实际段。 -/
  spanOf : (decomp.steps[leave]?).map Seg.source = some span
  /-- 构成趋势背驰或盘整背驰。 -/
  diverges : TrendDiv rc mode side decomp x center enter leave ∨
    ConsolDiv rc mode side decomp x center enter leave

/-- 背驰段作为区间套的一层。

[061:34]「由此可见，72点这个背驰点的精确定位，是由65开始背驰段的背驰段的背驰段的背驰段构成的，这就构成一个区间套的精确定位，这一切，都可以当下地进行。」 -/
def DivSegment.level {rc : ForceRecipe R} {mode : ForceCompareMode} {x : ℕ → R}
    (s : DivSegment rc mode x) : ChainLevel :=
  ⟨s.decomp.depth, s.span⟩

/-- 纯结构区间套：顶层为背驰段，其下各层层深严格递减、跨度逐级包含；不要求中间级别出现同级背驰。

[027:44]「定理：某大级别的转折点，可以通过不同级别背驰段的逐级收缩范围而确定。」
[027:46]「换言之，某大级别的转折点，先找到其背驰段，然后在次级别图里，找出相应背驰段在次级别里的背驰段，将该过程反复进行下去，直到最低级别，相应的转折点就在该级别背驰段确定的范围内。」
[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
structure NestedDivChain (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R) where
  /-- 顶层背驰段。 -/
  top : DivSegment rc mode x
  /-- 逐级向下的层。 -/
  lower : List ChainLevel
  /-- 层深严格递减。 -/
  depthDesc : (top.level :: lower).IsChain (fun a b => b.depth < a.depth)
  /-- 跨度逐级包含。 -/
  nested : (top.level :: lower).IsChain (fun a b => SpanWithin b.span a.span)

/-- 原趋势方向对应的完成形态。

[029:14]「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」 -/
def trendOf (side : Dir) : TrendKind :=
  match side with
  | .up => .uptrend
  | .down => .downtrend

/-- 大级别在切点 `cut` 处转折：自该切点起的完成块不再是原方向趋势。

[029:14]「对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：」 -/
def BigTurnAt (side : Dir) (big : Decomposition R) (cut : ℕ) : Prop :=
  ∃ b ∈ big.ledger.completed, b.first = cut ∧ classifyTrend b ≠ some (trendOf side)

/-- 小转大义一：次级别背驰段落在大级别末段之内并同向，随后大级别转折。

[043:24]「如果市场的转折与背驰都有这在级别上一一对应关系，那这市场也太没意思、太刻板了，而由于这种小级别背驰逐步积累后导致大级别转折的可能，才使得市场充满当下的生机。」
[044:24]「小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；」
[044:26]「小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。」
[044:30]「注意，关于这种情况，只有必要条件，而没有充分条件，也就是说不能有一个充分的判断使得一旦出现某种情况，就必然导致大级别的转折。」 -/
def SmallDivTriggersBigTurn {rc : ForceRecipe R} {mode : ForceCompareMode} {x : ℕ → R}
    (small : DivSegment rc mode x) (big : Decomposition R) (cut : ℕ) : Prop :=
  small.decomp.depth < big.depth ∧
    (∃ s, big.steps[cut - 1]? = some s ∧ s.dir = small.side ∧ SpanWithin small.span s.source) ∧
    BigTurnAt small.side big cut

/-- 小转大义二：本级别在切点前没有趋势背驰或盘整背驰，却经反向第三类事件完成转折。

[043:26]「由于背驰的级别不可能大于当下走势的级别，例如一个30分钟级别的背驰，只可能存在于一个至少是30分钟级别的走势类型中，所以就有这两种不同转折方式的明确分类。」
[056:66]「这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。」 -/
def TurnWithoutSameLevelDiv (rc : ForceRecipe R) (mode : ForceCompareMode) (x : ℕ → R)
    (side : Dir) (big : Decomposition R) (cut : ℕ) : Prop :=
  BigTurnAt side big cut ∧
    (¬∃ z i j, j < cut ∧
      (TrendDiv rc mode side big x z i j ∨ ConsolDiv rc mode side big x z i j)) ∧
    ∃ z ∈ big.ledger.centers, ReverseExit side big z

end Chan.Defs.Dynamics
-- SOURCE END Opus Chan/Defs/Dynamics/Divergence.lean
end Source6

section Source7
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Defs/Limits/Liveness.lean

namespace Chan.Defs.Limits

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Path

universe u

/-- 自然数索引的无限价格路径。

[017:60]「因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”；」 -/
abbrev InfPath (A : Type*) := ℕ → A

/-- 截断至前 `n` 步的有限历史。

[二级旁证 105:442]「另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。」 -/
def prefixOf {A : Type*} (x : InfPath A) (n : ℕ) : History A :=
  List.ofFn (fun i : Fin n => x i.val)

/-- 由有限前缀决定的可观测谓词：每条路径都有一个前缀长度，凡与之共享该前缀的路径取值相同。

[二级旁证 105:442]「另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。」 -/
def PrefixObservable {A : Type*} (Q : InfPath A → Prop) : Prop :=
  ∀ x : InfPath A, ∃ n, ∀ y : InfPath A, prefixOf y n = prefixOf x n → (Q y ↔ Q x)

/-- 在线分析量沿逐步加长的前缀在 `Filter.atTop` 下最终常值。

[102:20]「同样，本ID的理论给出的递归函数，完美地给出市场走势一个类似记数法一样的唯一分解，也就是说，本ID揭示了看似毫无规律的市场走势竟然有着和自然数有着类似的整体结构，完全超越一般的想象，这才是真正最牛的地方。」 -/
def EventuallyStable {A B : Type*} (f : History A → B) (x : InfPath A) : Prop :=
  Filter.EventuallyConst (fun n => f (prefixOf x n)) Filter.atTop

/-- 命题一（分解存在）：任一有限基底在给定规则与粗化策略下存在局部规范的合法分解。

[101:52]「所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。」 -/
def DecompExistsSpec {P : Type u} [LinearOrder P] (r : BlockRule.{u}) (dir : CoarseDirPolicy P) :
    Prop :=
  ∀ base : AltSeq P, Nonempty (LocalCanonicalDecomp r dir base)

/-- 命题二（规范唯一）：任意两个局部规范分解逐层切点相同。

[101:56]「本ID理论最牛的地方，就是把仿佛毫无头绪的股票走势，给出了唯一分解定理，也就是走势必完美，这等于引进理想数，使得代数数论升堂入室一样牛。」
[102:14]「如果是单纯地唯一分解，并不能显示本ID理论真正厉害之处，因为走势必完美对应的是一种最特殊、最强有力的唯一分解，这看似毫无规律的市场走势竟然有这样完美的整体结构，这才是最牛的地方。」 -/
def CanonicalUniqueSpec {P : Type u} [LinearOrder P] (r : BlockRule.{u})
    (dir : CoarseDirPolicy P) : Prop :=
  ∀ (base : AltSeq P) (a b : LocalCanonicalDecomp r dir base), a.val.sameCuts b.val

/-- 命题三（有界活性下终结）：满足显式活性谓词的路径上，任一未完成状态在 `bound` 步内完成或升级。

[069:28]「其实，本ID的理论的关键不是什么中枢、走势类型，而是走势必完美，这才是本ID理论的核心。但要真正理解这个关键，可不是看字面意思就能明白的。」 -/
def BoundedTerminationSpec {A : Type*} (live : InfPath A → Prop) (pending done : History A → Prop)
    (bound : ℕ) : Prop :=
  ∀ x : InfPath A, live x → ∀ n, pending (prefixOf x n) →
    ∃ m, n ≤ m ∧ m ≤ n + bound ∧ done (prefixOf x m)

/-- 命题四（弱安全性）：买点之后若在时刻 `m` 前形成同级中枢，则其间存在价格不低于买入价的时刻；不宣称操作上的绝对安全。

[107:22]「显然，没有任何绝对性可以保障上下上中，最后一个上一定有比第一个上有更高的高点，特别那种所谓奔走型的反弹，后上的高点可能只刚好触及前上的低点，因此，如果你一定要等上下上都完成才抛出，那很可能面对这样的尴尬，就是你在第一个上的最低点买的，在上下上的电梯过后，你只有一个可能连手续费都不够、稍纵即逝的卖点。因此，这种操作，注定是只有相对的理论上的绝对安全性，而没有具体操作上的绝对安全性。」
[017:60]「因为上涨和盘整必然要在图形上完成，而上涨和盘整在图形上的要求，是必须包含三个以上的次级别运动，因此后面必须还至少有一个向上的次级别运动，这样的买点是绝对安全的，其安全性由走势的“不患”而保证，这，就是在前面反复强调的第二类买点。」 -/
def WeakSafetySpec {P : Type*} [LinearOrder P] (buyAt : InfPath P → ℕ → Prop)
    (centerAfter : InfPath P → ℕ → ℕ → Prop) : Prop :=
  ∀ (x : InfPath P) (t : ℕ), buyAt x t → ∀ m, centerAfter x t m →
    ∃ s, t < s ∧ s ≤ m ∧ x t ≤ x s

end Chan.Defs.Limits
-- SOURCE END Opus Chan/Defs/Limits/Liveness.lean
end Source7

section Source8
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus Chan/Hypotheses/Dynamics.lean

namespace Chan.Hypotheses

open Chan.Defs.Alt Chan.Defs.Limits Chan.Defs.Dynamics Chan.Defs.Signal Chan.Defs.Path

/-- 参与者标签。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
structure MarketParticipant where
  /-- 编号。 -/
  id : ℕ

/-- 订单/成交事件：参与者、时刻、买卖方向（`up` 买、`down` 卖）、价格与数量。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
structure OrderEvent (R : Type*) where
  /-- 参与者。 -/
  participant : MarketParticipant
  /-- 时刻。 -/
  time : ℕ
  /-- 买卖方向。 -/
  side : Dir
  /-- 价格。 -/
  price : R
  /-- 数量。 -/
  qty : R

/-- 带参与者标签的市场：按时间不减排列的事件表与成交价格投影。

[030:16]「而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。」 -/
structure TaggedMarket (R : Type*) where
  /-- 事件表。 -/
  events : List (OrderEvent R)
  /-- 成交价格投影。 -/
  price : ℕ → R
  /-- 交易时间不可逆：事件按时间不减排列。 -/
  irreversible : events.IsChain (fun a b => a.time ≤ b.time)

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 二阶差分 `x (t+2) - 2 x (t+1) + x t`。

[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def secondDiff (x : InfPath R) (t : ℕ) : R := x (t + 2) - 2 * x (t + 1) + x t

/-- 活性假设：任意时刻后 `B` 步内既有严格上行也有严格下行，排除永久静止与无回抽单边。

[017:60]「因为上涨和盘整必然要在图形上完成，而上涨和盘整在图形上的要求，是必须包含三个以上的次级别运动，因此后面必须还至少有一个向上的次级别运动，这样的买点是绝对安全的，其安全性由走势的“不患”而保证，这，就是在前面反复强调的第二类买点。」 -/
def LivenessHyp (B : ℕ) (x : InfPath R) : Prop :=
  ∀ n, (∃ m, n < m ∧ m ≤ n + B ∧ x n < x m) ∧ (∃ m, n < m ∧ m ≤ n + B ∧ x m < x n)

/-- 惯性假设：二阶差分绝对值有显式上界 `K`。

[072:34]「动力学，是属于物理范畴的，但站在更高的层次上看物理，物理的本质就是几何，当然，这是所有物理学家都不可能认同的，但如果用一些几何结构就可以把所有物理的常量给搞掂，那物理学家不认同也是白搭。同样道理，本ID理论里的动力学部分，本质上也是几何，只是这种几何比较特别，需要把价格充分有效市场里的非完全绝对趋同交易作为前提转化为某些几何结构，然后构造出理论的证明来。」 -/
def InertiaHyp (K : R) (x : InfPath R) : Prop :=
  ∀ t, abs (secondDiff x t) ≤ K

/-- 衰竭假设：自时刻 `t0`（背驰离开段结束）起，顺向累计推进（定向增量正部之和）不超过预算 `budget`。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def ExhaustionHyp (side : Dir) (t0 : ℕ) (budget : R) (x : InfPath R) : Prop :=
  ∀ k, ((List.range k).map fun i =>
    max (orient side x (t0 + i + 1) - orient side x (t0 + i)) 0).sum ≤ budget

/-- 回复假设：位于中枢核之外时，二阶差分含指向核的回复项（系数 `κ > 0`，误差 `ε`）。不引用“回到中枢”。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def PullbackHyp (z : Chan.Defs.Center R) (κ ε : R) (x : InfPath R) : Prop :=
  0 < κ ∧ ∀ t,
    (z.core.hi < x (t + 1) → secondDiff x t ≤ -(κ * (x (t + 1) - z.core.hi)) + ε) ∧
    (x (t + 1) < z.core.lo → κ * (z.core.lo - x (t + 1)) - ε ≤ secondDiff x t)

/-- 柱组对称单峰假设（离散、峰值点居中）：长度 `2p+1`，非负，峰前单调不减，关于峰位 `p` 对称。
此时“全组面积 = 2 × 半计峰值点的到峰面积”（见 `barGroupHalfPeakArea`）；含峰整计再翻倍不成立，
例如 `1, 2, 1`：全组 4，含峰到峰 3，翻倍 6，而半计峰值点到峰为 2，翻倍 4。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def SymUnimodalBarGroupHyp (g : List R) (p : ℕ) : Prop :=
  g.length = 2 * p + 1 ∧
    (∀ i, i < g.length → 0 ≤ g.getD i 0) ∧
    (∀ i, i < p → g.getD i 0 ≤ g.getD (i + 1) 0) ∧
    ∀ k, k ≤ p → g.getD (p - k) 0 = g.getD (p + k) 0

/-- 半计峰值点的到峰面积：峰前各柱之和加峰值的一半。

[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def barGroupHalfPeakArea (g : List R) (p : ℕ) : R := (g.take p).sum + g.getD p 0 / 2

/-- 五项假设的显式打包，参数与证明全部为字段，无默认值。

[030:32]「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」 -/
structure DynamicsHypBundle (x : InfPath R) where
  /-- 活性步数界。 -/
  liveBound : ℕ
  /-- 活性假设。 -/
  liveness : LivenessHyp liveBound x
  /-- 惯性上界。 -/
  inertiaBound : R
  /-- 惯性假设。 -/
  inertia : InertiaHyp inertiaBound x
  /-- 衰竭方向。 -/
  exhaustSide : Dir
  /-- 衰竭起点。 -/
  exhaustStart : ℕ
  /-- 推进预算。 -/
  budget : R
  /-- 衰竭假设。 -/
  exhaustion : ExhaustionHyp exhaustSide exhaustStart budget x
  /-- 回复所指中枢。 -/
  center : Chan.Defs.Center R
  /-- 回复系数。 -/
  kappa : R
  /-- 回复误差。 -/
  eps : R
  /-- 回复假设。 -/
  pullback : PullbackHyp center kappa eps x
  /-- 柱组。 -/
  barGroup : List R
  /-- 峰位。 -/
  peak : ℕ
  /-- 柱组对称单峰假设。 -/
  symUnimodal : SymUnimodalBarGroupHyp barGroup peak

/-- 结论谓词：时刻 `t0` 之后价格回到中枢核之内。五项假设的定义均不引用本谓词。

[098:16]「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」 -/
def ReturnsToCenter (z : Chan.Defs.Center R) (x : InfPath R) (t0 : ℕ) : Prop :=
  ∃ t, t0 ≤ t ∧ z.core.lo ≤ x t ∧ x t ≤ z.core.hi

/-- 待检条件命题“在线背驰后回到最后中枢”：各假设与背驰前提为独立前件。只是陈述，不断言成立。

[098:16]「一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。」 -/
def DivReturnsToCenterStmt (rc : ForceRecipe R) (mode : ForceCompareMode) (side : Dir)
    (d : Decomposition R) (z : Chan.Defs.Center R) (i cStart : ℕ) (B : ℕ) (K budget κ ε : R)
    (x : InfPath R) (n : ℕ) : Prop :=
  LivenessHyp B x → InertiaHyp K x → ExhaustionHyp side n budget x → PullbackHyp z κ ε x →
    DivOnline rc mode side d z i cStart (prefixOf x (n + 1)) → ReturnsToCenter z x n

/-- 价格充分有效：每笔事件的价格都等价反映在该时刻的价格轨迹上。

[030:32]「对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。」
[072:32]「站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。」 -/
def EfficientPriceMarket (M : TaggedMarket R) : Prop :=
  ∀ e ∈ M.events, M.price e.time = e.price

/-- 非完全绝对趋同交易：至少有两名不同参与者的事件不同时或方向不同。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def NonIdenticalTrading (M : TaggedMarket R) : Prop :=
  ∃ e₁ ∈ M.events, ∃ e₂ ∈ M.events,
    e₁.participant ≠ e₂.participant ∧ (e₁.time ≠ e₂.time ∨ e₁.side ≠ e₂.side)

end Chan.Hypotheses
-- SOURCE END Opus Chan/Hypotheses/Dynamics.lean
end Source8

section Source9
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus ChanDyn/Well.lean

namespace ChanDyn

/-- D1 单中枢势阱：中枢区间 `[zd, zg]` 与随时刻、位置给出的回复力。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
structure WellModel (R : Type*) [LinearOrder R] where
  /-- 中枢下沿。 -/
  zd : R
  /-- 中枢上沿。 -/
  zg : R
  /-- 区间有序。 -/
  zd_le_zg : zd ≤ zg
  /-- 回复力。 -/
  restore : ℕ → R → R

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 轨迹 `x` 在外力 `f` 下服从势阱递推。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def WellModel.Evolves (M : WellModel R) (x f : ℕ → R) : Prop :=
  ∀ t, x (t + 2) - 2 * x (t + 1) + x t = M.restore (t + 1) (x (t + 1)) + f (t + 1)

/-- 两侧对称：回复力关于中枢中点奇对称。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def WellSymmetric (M : WellModel R) : Prop :=
  ∀ (t : ℕ) (u : R), M.restore t ((M.zd + M.zg) / 2 + u) = -M.restore t ((M.zd + M.zg) / 2 - u)

/-- 时间不变：回复力与时刻无关。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def WellTimeInvariant (M : WellModel R) : Prop :=
  ∀ (t s : ℕ) (y : R), M.restore t y = M.restore s y

/-- 作用范围有界：离中枢区间超过 `ρ` 处回复力为零。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def WellBoundedRange (M : WellModel R) (ρ : R) : Prop :=
  0 ≤ ρ ∧ ∀ (t : ℕ) (y : R), (y < M.zd - ρ ∨ M.zg + ρ < y) → M.restore t y = 0

/-- 指向中枢：区间之上回复力不为正，区间之下不为负。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def WellInward (M : WellModel R) : Prop :=
  ∀ (t : ℕ) (y : R), (M.zg < y → M.restore t y ≤ 0) ∧ (y < M.zd → 0 ≤ M.restore t y)

/-- 滑行期零外力：时刻区间 `[a, b)` 内外力为零。

[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
def CoastingZeroThrust (f : ℕ → R) (a b : ℕ) : Prop :=
  ∀ t, a ≤ t → t < b → f t = 0

/-- `b` 段自静止落入：起点 `t0` 处速度为零且位于中枢区间之外。

[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
def FallsFromRest (M : WellModel R) (x : ℕ → R) (t0 : ℕ) : Prop :=
  x (t0 + 1) = x t0 ∧ (M.zg < x t0 ∨ x t0 < M.zd)

end ChanDyn
-- SOURCE END Opus ChanDyn/Well.lean
end Source9

section Source10
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus ChanDyn/Thrust.lean

namespace ChanDyn

/-- D2 推力模型：势阱、外加推力序列与临界阈值参数位。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
structure ThrustModel (R : Type*) [LinearOrder R] extends WellModel R where
  /-- 外加推力序列。 -/
  thrust : ℕ → R
  /-- 临界阈值。 -/
  critical : R

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 轨迹在自身推力下服从势阱递推。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ThrustModel.Evolves (M : ThrustModel R) (x : ℕ → R) : Prop :=
  M.toWellModel.Evolves x M.thrust

/-- 时刻区间 `[s, e)` 的已显示推力预算（推力绝对值之和）。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ThrustModel.budget (M : ThrustModel R) (s e : ℕ) : R :=
  ((List.range (e - s)).map fun i => abs (M.thrust (s + i))).sum

/-- 比较式预算上界假设：`c` 窗口预算不超过 `b` 窗口预算，且后者不超过临界阈值。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def BudgetBound (M : ThrustModel R) (bS bE cS cE : ℕ) : Prop :=
  M.budget cS cE ≤ M.budget bS bE ∧ M.budget bS bE ≤ M.critical

/-- 目标状态：自 `t0` 起 `H` 步内回到中枢区间。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def BoundedReturn (M : ThrustModel R) (x : ℕ → R) (t0 H : ℕ) : Prop :=
  ∃ t, t0 ≤ t ∧ t ≤ t0 + H ∧ M.zd ≤ x t ∧ x t ≤ M.zg

/-- 条件陈述：各势阱假设、自静止落入、预算比较前提与递推各为独立前件，结论为有限期限回到中枢。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def ReturnUnderBudgetStmt (M : ThrustModel R) (x : ℕ → R) (ρ : R) (t0 H bS bE cS cE : ℕ) :
    Prop :=
  WellSymmetric M.toWellModel → WellTimeInvariant M.toWellModel →
    WellBoundedRange M.toWellModel ρ → WellInward M.toWellModel →
    FallsFromRest M.toWellModel x t0 → BudgetBound M bS bE cS cE → M.Evolves x →
    BoundedReturn M x t0 H

end ChanDyn
-- SOURCE END Opus ChanDyn/Thrust.lean
end Source10

section Source11
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus ChanDyn/Field.lean

namespace ChanDyn

/-- 场源：一个势阱及其级别。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
structure CenterSource (R : Type*) [LinearOrder R] where
  /-- 势阱。 -/
  well : WellModel R
  /-- 级别。 -/
  level : ℕ

/-- D3 多中枢叠加场：有限个场源。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
structure MultiCenterField (R : Type*) [LinearOrder R] where
  /-- 场源表。 -/
  sources : List (CenterSource R)

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 结构场：各场源回复力之和。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def MultiCenterField.field (F : MultiCenterField R) (t : ℕ) (y : R) : R :=
  (F.sources.map fun c => c.well.restore t y).sum

/-- 残余推力：二阶差分减去结构场，对应当下交易产生的力。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def residualThrust (F : MultiCenterField R) (x : ℕ → R) (t : ℕ) : R :=
  (x (t + 2) - 2 * x (t + 1) + x t) - F.field (t + 1) (x (t + 1))

/-- 位置到势阱中枢区间的距离（区间内为零）。

[033:24]「在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。」 -/
def bandDistance (M : WellModel R) (y : R) : R := max (M.zd - y) (max (y - M.zg) 0)

/-- 最近中枢主导误差界：`near` 是距当下位置最近的场源，且结构场与其单独回复力之差不超过 `ε`。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def NearestCenterDominates (F : MultiCenterField R) (near : CenterSource R) (ε : R)
    (x : ℕ → R) (t : ℕ) : Prop :=
  near ∈ F.sources ∧
    (∀ c ∈ F.sources, bandDistance near.well (x (t + 1)) ≤ bandDistance c.well (x (t + 1))) ∧
    abs (F.field (t + 1) (x (t + 1)) - near.well.restore (t + 1) (x (t + 1))) ≤ ε

end ChanDyn
-- SOURCE END Opus ChanDyn/Field.lean
end Source11

section Source12
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Opus ChanDyn/Agents.lean

namespace ChanDyn

/-- D4 异步多参与者系统：组数、各组权重、响应函数（旧状态与当下价格到新状态）与激活表。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
structure AsyncAgentSystem (R : Type*) where
  /-- 组数。 -/
  nGroups : ℕ
  /-- 各组权重。 -/
  weight : ℕ → R
  /-- 响应函数：组号、旧状态、当下价格到新状态。 -/
  respond : ℕ → R → R → R
  /-- 激活表：时刻与组号到是否响应。 -/
  active : ℕ → ℕ → Bool

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 向量叠加价格：各组状态加权和。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def AsyncAgentSystem.price (S : AsyncAgentSystem R) (st : ℕ → R) : R :=
  ((List.range S.nGroups).map fun i => S.weight i * st i).sum

/-- 异步一步：被激活的组按当下价格响应，其余组保持。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def AsyncAgentSystem.step (S : AsyncAgentSystem R) (t : ℕ) (st : ℕ → R) : ℕ → R :=
  fun i => if S.active t i then S.respond i (st i) (S.price st) else st i

/-- 自初始状态起的递推轨道。

[030:16]「而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。」 -/
def AsyncAgentSystem.run (S : AsyncAgentSystem R) (st0 : ℕ → R) : ℕ → ℕ → R
  | 0 => st0
  | t + 1 => S.step t (S.run st0 t)

/-- 有限期限可达：`H` 步内价格进入目标的 `ε` 邻域。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
def FiniteHorizonReach (S : AsyncAgentSystem R) (st0 : ℕ → R) (target ε : R) (H : ℕ) : Prop :=
  ∃ t, t ≤ H ∧ abs (S.price (S.run st0 t) - target) ≤ ε

/-- 无限时间渐近稳定：对任意正 `ε`，某时刻之后价格永远留在目标的 `ε` 邻域内。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
def AsymptoticStable (S : AsyncAgentSystem R) (st0 : ℕ → R) (target : R) : Prop :=
  ∀ ε : R, 0 < ε → ∃ T, ∀ t, T ≤ t → abs (S.price (S.run st0 t) - target) ≤ ε

/-- 稳定性域：使系统渐近稳定于目标的初始状态全体。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def StabilityDomain (S : AsyncAgentSystem R) (target : R) : (ℕ → R) → Prop :=
  fun st0 => AsymptoticStable S st0 target

end ChanDyn
-- SOURCE END Opus ChanDyn/Agents.lean
end Source12
end Opus

namespace Astra

section Source0
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Proxy/Ema.lean

namespace Chan.Proxy

/-- 用有理平滑系数和播种方式指定 EMA。标准周期 `N` 对应 `alpha = 2/(N+1)`。
`none` 在时刻零取首价；`some v` 指定时刻零的均线值为 `v`。
[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure EmaParams where
  alpha : ℚ
  alpha_pos : 0 < alpha
  alpha_le_one : alpha ≤ 1
  seed : Option ℚ

/-- 从零时刻向前递推，每一步只使用上一步均线和本步价格。
[050:18]「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def emaSeq (p : EmaParams) (price : ℕ → ℚ) : ℕ → ℚ
  | 0 => p.seed.getD (price 0)
  | t + 1 => (1 - p.alpha) * emaSeq p price t + p.alpha * price (t + 1)

/-- 取截至 `t` 最近至多 `period` 根的算术平均；起始未满窗口时，以实有根数为分母。
[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def smaSeq (period : ℕ+) (price : ℕ → ℚ) (t : ℕ) : ℚ :=
  let count := min period.val (t + 1)
  (Finset.range count).sum (fun i => price (t - i)) / (count : ℚ)

/-- 标准周期的精确衰减因子；先转有理数再作减法和除法。
[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def emaDecay (period : ℕ+) : ℚ :=
  let n : ℚ := period.val
  (n - 1) / (n + 1)

/-- 最近 `n` 根均在宽度 `R` 的闭价带内；更早的 `oldCount` 根单独计入带距。
价格从首值播种，观测末端是 `oldCount + n - 1`。
[024:24]「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
structure ZeroAxisBoundData where
  price : ℕ → ℚ
  oldCount : ℕ
  n : ℕ
  nine_le : 9 ≤ n
  lower : ℚ
  R : ℚ
  width_nonneg : 0 ≤ R
  recent_mem : ∀ i < n, lower ≤ price (oldCount + i) ∧ price (oldCount + i) ≤ lower + R

/-- 所有旧价到新价带的最大距离。带内的价距为零；无旧价时最大带距也取零。
[024:24]「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.delta (d : ZeroAxisBoundData) : ℚ :=
  (List.range d.oldCount).foldl (fun acc t =>
    max acc (max (d.lower - d.price t) (d.price t - (d.lower + d.R)))) 0

/-- 对标准 12、26 周期首值播种的 DIF，在最近窗口末端检验精确回拉界。
第一项为核正部质量乘带宽，第二项为窗口以前的核尾质量乘旧价带距。
DEA 的信号均线另有卷积核，不使用此界。
[024:24]「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.difWithinBound (d : ZeroAxisBoundData) : Prop :=
  let q12 : ℚ := 11 / 13
  let q26 : ℚ := 25 / 27
  let a := q26 ^ 9 - q12 ^ 9
  let t := d.oldCount + d.n - 1
  let fast := emaSeq ⟨1 - q12, by norm_num [q12], by norm_num [q12], none⟩ d.price t
  let slow := emaSeq ⟨1 - q26, by norm_num [q26], by norm_num [q26], none⟩ d.price t
  |fast - slow| ≤ a * d.R + (q26 ^ d.n - q12 ^ d.n) * d.delta

/-- 回拉界的两端都是有限历史的有理读数，故可直接判定。
[024:24]「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
instance (d : ZeroAxisBoundData) : Decidable d.difWithinBound := by
  unfold ZeroAxisBoundData.difWithinBound
  infer_instance

end Chan.Proxy
-- SOURCE END Astra Chan/Proxy/Ema.lean
end Source0

section Source1
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Proxy/Macd.lean

namespace Chan.Proxy

/-- 三个正周期；在快慢线的命名中，快线的周期严格短于慢线。
[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure MacdParams where
  fast : ℕ+
  slow : ℕ+
  signal : ℕ+
  fast_lt_slow : fast < slow

/-- 双线之差、差线的信号均线、带倍数 2 的柱高。无倍数口径的柱高是 `hist / 2`。
[024:24]「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
structure MacdPoint where
  dif : ℚ
  dea : ℚ
  hist : ℚ
  deriving DecidableEq

/-- 首价同时播种快慢线，故首个 DIF 及其播种的 DEA 为零。用同一时刻的新 DIF 更新 DEA，
再取 `hist = 2 * (dif - dea)`；标准三周期的倍柱核常数为 `(9-1)*(26-12)/2 = 56`。
[025:16]「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def macdSeq (p : MacdParams) (price : ℕ → ℚ) (t : ℕ) : MacdPoint :=
  let update (period : ℕ+) (old new : ℚ) :=
    old + 2 / ((period.val : ℚ) + 1) * (new - old)
  let step (k : ℕ) (state : ℚ × ℚ × ℚ) : ℚ × ℚ × ℚ :=
    let fast := update p.fast state.1 (price (k + 1))
    let slow := update p.slow state.2.1 (price (k + 1))
    (fast, slow, update p.signal state.2.2 (fast - slow))
  let (fast, slow, dea) := Nat.rec (price 0, price 0, 0) step t
  let dif := fast - slow
  ⟨dif, dea, 2 * (dif - dea)⟩

/-- 闭窗口 `[s,e]` 内各根柱的带号和；反向窗口为空。MACD 输入可取 `fun t => (m t).hist`。
[024:24]「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def signedSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => bars (s + i)

/-- 仅累加闭窗口中红柱的高度。
[024:24]「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def posSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => max (bars t) 0) s e

/-- 仅累加闭窗口中绿柱的深度，读数非负。
[024:24]「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def negSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => max (-bars t) 0) s e

/-- 各根柱不分颜色，取绝对值后相加。
[024:24]「而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。」 -/
def absSum (bars : ℕ → ℚ) (s e : ℕ) : ℚ :=
  signedSum (fun t => |bars t|) s e

/-- 只计两个端点都在窗口内的相邻增量，累加其正部。
[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def posVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e - s)).sum fun i => max (x (s + i + 1) - x (s + i)) 0

/-- 与正变差使用同一批相邻增量，累加负部的绝对值。
[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def negVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  posVar (fun t => -x t) s e

/-- 离散全变差等于窗口内上行变差与下行变差之和。
[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def totalVar (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  posVar x s e + negVar x s e

/-- 末值减初值。反向窗口不含增量，读数为零。
[025:16]「不难发现，MACD的柱子伸长，和乖离有关，大致就是走势和均线的偏离度。」 -/
def endpointDiff (x : ℕ → ℚ) (s e : ℕ) : ℚ :=
  if s ≤ e then x e - x s else 0

end Chan.Proxy
-- SOURCE END Astra Chan/Proxy/Macd.lean
end Source1

section Source2
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Proxy/MaArea.lean

namespace Chan.Proxy

/-- 在编号 `s,…,e` 的等时长柱上以短均线减长均线，按每根一单位时间累加。
[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maSignedArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => fast (s + i) - slow (s + i)

/-- 短均线在长均线上方时，两线之间的面积。
[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maPosArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => max (fast (s + i) - slow (s + i)) 0

/-- 短均线在长均线下方时，两线之间的面积，取非负值。
[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maNegArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  maPosArea slow fast s e

/-- 非空窗口的趋势平均力度：两均线间的无向面积除以时长。
窗口包含首尾两根单位时间柱，因此总时长为 `e + 1 - s`。
[015:42]「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maAvgForce (fast slow : ℕ → ℚ) (s e : ℕ) (_ : s ≤ e) : ℚ :=
  (maPosArea fast slow s e + maNegArea fast slow s e) / ((e + 1 - s : ℕ) : ℚ)

end Chan.Proxy
-- SOURCE END Astra Chan/Proxy/MaArea.lean
end Source2

section Source3
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Defs/Dynamics/Potential.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Signal

/-- 所选分解中两个同向比较段的原始闭跨度（可共用转接点）。锚是可选的中枢核，不是价格样本。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。 -/
structure ForceWindow where
  earlier : Span
  later : Span
  anchor : Option (Bar ℚ)
  ordered : earlier.last ≤ later.first
  deriving DecidableEq

/-- 按段号从同一分解取比较对；指定锚时也从同级账本取核。越界、异向或错序无窗口。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
def ForceWindow.ofDecomp? (d : Decomposition ℚ) (i j : Nat) (center? : Option Nat) :
    Option ForceWindow := do
  let a ← d.steps[i]?
  let b ← d.steps[j]?
  if i ≥ j || a.dir != b.dir then none else
    let anchor ← match center? with
      | none => some none
      | some k => (d.ledger.centers[k]?).map (fun z => some z.core)
    if h : a.source.last ≤ b.source.first then some ⟨a.source, b.source, anchor, h⟩ else none

/-- 在时刻 t 只给出严格过去的 t 个样本及当下成交价。旧时刻求值不会见到后续价格；
绝对价位本身也可以是势。
[二级旁证 105:442] 另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。 -/
structure CausalPotential where
  sample : List ℚ → ℚ → ℚ

/-- 全历史与现价同比例放大时，势值也按该正比例放大。
[050:18] 必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。 -/
def PosHomogeneous (v : CausalPotential) : Prop :=
  ∀ a : ℚ, 0 < a → ∀ past x, v.sample (past.map (a * ·)) (a * x) = a * v.sample past x

/-- 整条价格历史镜像后势值反号；这是可单独检验的性质。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
def MirrorAntiSym (v : CausalPotential) : Prop :=
  ∀ past x, v.sample (past.map Neg.neg) (-x) = -v.sample past x

end Chan.Defs.Dynamics
-- SOURCE END Astra Chan/Defs/Dynamics/Potential.lean
end Source3

section Source4
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Defs/Dynamics/ForceSpec.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt

/-- 端点差保留回吐；正变差只累计沿比较方向的正向增量。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
inductive ReadingKind where
  | endpointDiff | posVar
  deriving DecidableEq

/-- 内部读法只取两端都在窗内的增量；另两种分别把真实前驱或零参考接在窗首之前。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。 -/
inductive EndpointConv where
  | interiorOnly | withPredecessor | fromRest
  deriving DecidableEq

/-- 先选择一对窗口、一种势、一种读法及一套端点约定，两段共享后三者。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
structure ForceSpec where
  window : ForceWindow
  potential : CausalPotential
  reading : ReadingKind
  endpoint : EndpointConv

/-- 在同一窗口对中选择前段或后段，避免将层内段号误作价格下标。
[024:22] 用MACD 判断背驰，首先要有两段同向的趋势。同向趋势之间一定有一个盘整或反向趋势连接，把这三段分别称为A、B、C 段。 -/
inductive ForceLeg where
  | earlier | later
  deriving DecidableEq

/-- 把势或速度投到比较方向：多头取原值，空头取反号，然后才计算正变差。
[024:24] 而C 段的走势类型完成时对应的MACD 柱子面积（向上的看红柱子，向下看绿柱子）比A 段对应的面积要小，这时候就构成标准的背弛。 -/
def orientValue (side : Dir) (x : ℚ) : ℚ :=
  match side with | .up => x | .down => -x

/-- 非空采样列的读数。端点差取末值减首值；正变差逐对累加正部，单点两者均为零。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
def readSamples (kind : ReadingKind) (first : ℚ) (rest : List ℚ) : ℚ :=
  match kind with
  | .endpointDiff => rest.getLastD first - first
  | .posVar => (rest.foldl (fun (st : ℚ × ℚ) x => (x, st.2 + max (x - st.1) 0)) (first, 0)).2

/-- 在原始价格坐标上观察所选闭窗。每个势值只看至该点为止的历史；
窗尾未到或约定需要但没有前驱时返回无值，不以零替代。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。 -/
def evalForce (spec : ForceSpec) (h : List ℚ) (side : Dir) (leg : ForceLeg) : Option ℚ := do
  let w := match leg with | .earlier => spec.window.earlier | .later => spec.window.later
  if w.last ≥ h.length then none else
    let value := fun t x => orientValue side (spec.potential.sample (h.take t) x)
    let points := (h.extract w.first (w.last + 1)).mapIdx (fun i x => value (w.first + i) x)
    match points with
    | [] => none
    | first :: rest =>
      match spec.endpoint with
      | .interiorOnly => some (readSamples spec.reading first rest)
      | .fromRest => some (readSamples spec.reading 0 points)
      | .withPredecessor =>
        if w.first = 0 then none else
          let prev := w.first - 1
          let x ← h[prev]?
          some (readSamples spec.reading (value prev x) points)

/-- 固定来源跨度，整体平移价格后比较实际读数；不要求势本身在平移下不动。
[015:42] 称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间 -/
def ReadingShiftInvariant (spec : ForceSpec) : Prop :=
  ∀ h side leg (b : ℚ),
    evalForce spec (h.map (· + b)) side leg = evalForce spec h side leg

/-- 正仿射换价后，已定义的力度读数按比例缩放，读数的定义域不变。
[050:18] 必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。 -/
def PositiveAffineEquiv (spec : ForceSpec) : Prop :=
  ∀ (a b : ℚ), 0 < a → ∀ h side leg,
    evalForce spec (h.map (fun x => a * x + b)) side leg =
      (evalForce spec h side leg).map (a * ·)

/-- 同时镜像价格并互换比较方向，检验两侧读数是否相同。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
def ReadingMirrorSymmetric (spec : ForceSpec) : Prop :=
  ∀ h side leg, evalForce spec (h.map Neg.neg) side.flip leg = evalForce spec h side leg

/-- 相等是否算减弱由调用方选择；两种比较各自独立。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。
[二级旁证 051:246] 不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。 -/
inductive ForceCompareMode where
  | strict | nonStrict
  deriving DecidableEq

/-- 用同一把尺量前后两段。未取得两个读数时不能报告力度减弱。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。
[二级旁证 051:246] 不一定要缩小，不大于就可以，而且深圳那边明显变小，对照一下就更能确定了。1分钟以下级别的背驰，反抽到1分钟以下级别的中枢里，这当然被理论所保证。 -/
def forceWeaker (mode : ForceCompareMode) (spec : ForceSpec) (h : List ℚ) (side : Dir) : Bool :=
  match evalForce spec h side .earlier, evalForce spec h side .later with
  | some a, some b => match mode with
    | .strict => decide (b < a)
    | .nonStrict => decide (b ≤ a)
  | _, _ => false

end Chan.Defs.Dynamics
-- SOURCE END Astra Chan/Defs/Dynamics/ForceSpec.lean
end Source4

section Source5
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Defs/Dynamics/StructImpulse.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Signal

/-- 单位时间取相邻原始样本的间距。用实际出入价之差除以历时，不把区间极值当成端点。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
def segSlope (s : Seg ℚ) (p : DirectedEndpoints s) (_elapsed : s.source.first < s.source.last) : ℚ :=
  (p.exit - p.entry) / ((s.source.last - s.source.first : Nat) : ℚ)

/-- 可测速的一个结构段：有实际端点，且两个时间戳不同。
[104:18] 现代物理的一个核心概念，就是物理与几何的高度统一。 -/
structure ImpulseLeg where
  seg : Seg ℚ
  prices : DirectedEndpoints seg
  elapsed : seg.source.first < seg.source.last

/-- 以原始闭跨度判相邻：共用转折样本或占用相接的两组样本；相邻底段方向交替。
[104:26] 而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。 -/
abbrev ImpulseLeg.followedBy (a b : ImpulseLeg) : Prop :=
  a.seg.dir ≠ b.seg.dir ∧
    (a.seg.source.last = b.seg.source.first ∨ a.seg.source.last + 1 = b.seg.source.first)

/-- 非空连续段窗。起点之前的速度不属于这个窗口。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。 -/
structure ImpulseWindow where
  first : ImpulseLeg
  rest : List ImpulseLeg
  connected : (first :: rest).IsChain ImpulseLeg.followedBy

/-- 先按实测端点计算带号速度，再投到本次比较的方向。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
def ImpulseLeg.speedAlong (leg : ImpulseLeg) (side : Dir) : ℚ :=
  orientValue side (segSlope leg.seg leg.prices leg.elapsed)

/-- L_in 只读窗内的速度变化；只有一段时，两个内部读法均读零。
[104:26] 而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。 -/
def impulseIn (kind : ReadingKind) (side : Dir) (w : ImpulseWindow) : ℚ :=
  readSamples kind (w.first.speedAlong side) (w.rest.map (·.speedAlong side))

/-- L_pre 把紧邻前驱到窗首的速度变化分配给本窗；前驱必须真实相邻。
[104:26] 而本ID的理论，本质上是站在这种现代物理的角度构建自己的能量动力学结构的。这里，一切都是几何结构说了算，一切的能量动力形态，都变几何化，因此，必须有这种思维上的根本改变，才会有真正的理解。否则，还是牛顿时代那种弱智思维，那就将陷入一种机械化思维的陷阱中。 -/
def impulsePre (kind : ReadingKind) (side : Dir) (prev : ImpulseLeg) (w : ImpulseWindow)
    (_adjacent : prev.followedBy w.first) : ℚ :=
  readSamples kind (prev.speedAlong side) ((w.first :: w.rest).map (·.speedAlong side))

/-- L_zero 在首段前插入零速度。它与 L_pre 的区别在于参考态，不在于改动窗内的数据。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
def impulseZero (kind : ReadingKind) (side : Dir) (w : ImpulseWindow) : ℚ :=
  readSamples kind 0 ((w.first :: w.rest).map (·.speedAlong side))

/-- 同一静止参考下并列保留末态速度与正变差。窗口中途有回吐时，两者可以不同。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
structure RestImpulseReadings where
  terminalSpeed : ℚ
  positiveVariation : ℚ
  deriving DecidableEq

/-- 同时取出从静止起算的两项读数，不替比较者选一项作为力度。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
def impulseFromRest (side : Dir) (w : ImpulseWindow) : RestImpulseReadings :=
  ⟨impulseZero .endpointDiff side w, impulseZero .posVar side w⟩

end Chan.Defs.Dynamics
-- SOURCE END Astra Chan/Defs/Dynamics/StructImpulse.lean
end Source5

section Source6
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Defs/Dynamics/Divergence.lean

namespace Chan.Defs.Dynamics

open Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Level Chan.Defs.Signal Chan.Defs.Center

/-- 取闭区间全部原始价格样本。
[027:38] 以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。
-/
def DivGeometry.samples (h : List ℚ) (w : Span) := h.extract w.first (w.last + 1)

open DivGeometry

/-- 取窗口的最低价和最高价，越过当前历史时没有值。
[061:28] 因为背驰如果没有创新高，是不存在的。
-/
def DivGeometry.bounds? (h : List ℚ) (w : Span) : Option (ℚ × ℚ) := do
  if w.last ≥ h.length then none else
    let xs := samples h w
    return (← xs.min?, ← xs.max?)

/-- 向上比较高点，向下比较低点。
[061:28] 因为背驰如果没有创新高，是不存在的。
-/
def DivGeometry.extremum (side : Dir) (bounds : ℚ × ℚ) : ℚ :=
  match side with | .up => bounds.2 | .down => bounds.1

/-- 候选后段必须严格刷新前段的方向极值；相触不算，两段都必须完整可见。
[061:28] 因为背驰如果没有创新高，是不存在的。
[二级旁证 044:234] ==创新高或新低才有背驰或盘整背驰的可能。未创新高的情况，其实可以按中枢震荡的方式去看，等于达不到上次震荡的力度，也可以用MACD等辅助看，但和背驰不是同一样东西，这在关于中枢震荡的力度判断那一课里里都有的。
-/
def MakesNewExtreme (h : List ℚ) (side : Dir) (a c : Span) : Bool :=
  match bounds? h a, bounds? h c with
  | some x, some y => ahead side (extremum side y) (extremum side x)
  | _, _ => false

/-- 单个历史前缀的分解。账本只记已完成段；待定段仅记录已知起点，终点由当下时钟给出。
段表的实际价格、极值和来源索引都用同一价格前缀核对。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。
-/
structure DivFrame (rule : BlockRule.{0}) (depth : Nat) (h : List ℚ) where
  stage : Decomposition ℚ
  atRule : stage.rule = rule
  atDepth : stage.depth = depth
  observed : ∀ (i : Fin stage.steps.length), let s := stage.steps[i.val]
    s.source.last < h.length ∧ bounds? h s.source = some (s.range.lo, s.range.hi) ∧
      h[s.source.first]? = some (stage.ledger.price i).entry ∧
      h[s.source.last]? = some (stage.ledger.price i).exit
  chronological : stage.steps.Pairwise (fun a b => a.source.last ≤ b.source.first)
  opened : Option Nat
  boundary : ∀ j, opened = some j → j < h.length ∧
    (match stage.steps.getLast? with
     | none => j = 0
     | some s => s.source.last = j ∨ s.source.last + 1 = j)

/-- 固定级别规则和分解办法后，只把要求观察的前缀交给分解器；不能查询未来行情。
[043:26] 由于背驰的级别不可能大于当下走势的级别，例如一个30分钟级别的背驰，只可能存在于一个至少是30分钟级别的走势类型中，所以就有这两种不同转折方式的明确分类。
-/
abbrev DivAnalysis (rule : BlockRule.{0}) :=
  (depth : Nat) → (h : List ℚ) → Option (DivFrame rule depth h)

/-- 以先后有序的来源坐标构造闭跨度。
[027:38] 以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。
-/
def DivGeometry.span? (a b : Nat) : Option Span :=
  if h : a ≤ b then some ⟨a, b, h⟩ else none

/-- 先后两个原始跨度共用一个中枢。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。
-/
def DivGeometry.window? (a c : Span) (z : Center ℚ) : Option ForceWindow :=
  if h : a.last ≤ c.first then some ⟨a, c, some z.core, h⟩ else none

/-- 用实际起止价判定该段沿选定方向推进。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。
-/
def DivGeometry.progresses (h : List ℚ) (w : Span) (side : Dir) : Bool :=
  match h[w.first]?, h[w.last]? with
  | some p, some q => ahead side q p
  | _, _ => false

/-- 只取本走势起点以来账本记载的中枢。
[027:14] 趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。
-/
def DivGeometry.sameScope (d : Decomposition ℚ) (since n : Nat) :=
  if d.marks.any (fun j => since < j && d.steps[j-1]?.any (fun s => s.source.last+1 < n))
  then [] else d.ledger.centers.filter fun z => decide (since ≤ z.start)

/-- 至少两个中枢，逐对检验整个波动区间同向严格分离。
[027:14] 趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。
-/
def DivGeometry.trendSide (side : Dir) (zs : List (Center ℚ)) : Bool :=
  zs.length ≥ 2 && (zs.zip zs.tail).all fun (a,b) =>
    match side with
    | .up => decide (gapUp a.zone.hull b.zone.hull)
    | .down => decide (gapDown a.zone.hull b.zone.hull)

/-- 由最后两枢定位入枢段与从末枢延伸到当下的出枢段。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。
-/
def DivGeometry.trendWindow? {r k h} (f : DivFrame r k h) (since : Nat) (side : Dir) :
    Option ForceWindow := do
  let zs := sameScope f.stage since h.length
  guard (trendSide side zs)
  let z :: prev :: _ := zs.reverse | none
  guard (prev.stop < z.start)
  let xs := f.stage.steps
  let firstB ← xs[prev.stop]?
  let lastB ← xs[z.start - 1]?
  let b ← span? firstB.source.first lastB.source.last
  let openAt ← f.opened
  -- 独立 c 可以已有完成的内部段；只取第一段的已知起点，不取未来终点。
  let c ← span? ((xs[z.stop]?.map (·.source.first)).getD openAt) (h.length - 1)
  let now ← h.getLast?
  guard (progresses h b side && progresses h c side && ahead side now (edge side z.core))
  window? b c z

/-- 到达中枢闭区间，触及边界也计入。
[098:16] 一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。
-/
def DivGeometry.touches (z : Center ℚ) (x : ℚ) := decide (z.core.lo ≤ x ∧ x ≤ z.core.hi)

/-- 检验从当前中枢向指定方向突破的已完成段。
[027:16] 如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。
-/
def DivGeometry.leaveAt (d : Decomposition ℚ) (z : Center ℚ) (side : Dir) (i : Nat) : Bool :=
  match d.steps[i]?, d.prices? i with
  | some s, some (_,out) =>
    s.dir == side && ahead side out (edge side z.core) &&
      (decide (overlaps z.core s.range) ||
       (i > 0 && d.steps[i-1]?.any fun prev => decide (overlaps z.core prev.range)))
  | _, _ => false

/-- 取末次同侧离开与当下尝试，两者之间须有反向触枢。
[027:20] 注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。
-/
def DivGeometry.consolWindows {r k h} (f : DivFrame r k h) (since : Nat) (side : Dir) :
    List ForceWindow := Id.run do
  let [z] := sameScope f.stage since h.length | return []
  let some j := f.opened | return []
  let some c := span? j (h.length-1) | return []
  let some (p,q) := bounds? h c | return []
  let some out := h.getLast? | return []
  let xs := f.stage.steps
  unless progresses h c side && ahead side out (edge side z.core) &&
      (decide (p ≤ z.core.hi ∧ z.core.lo ≤ q) ||
       xs.getLast?.any fun prev => decide (overlaps z.core prev.range)) do return []
  -- 只认最近一次同侧离开；两次离开之间须有反向回试，不能把一次离开切成两次。
  let some i := ((List.range xs.length).filter fun i =>
    z.start ≤ i && leaveAt f.stage z side i).getLast? | return []
  unless (xs.drop (i+1)).any (fun s => s.dir == side.flip && decide (overlaps s.range z.core))
    do return []
  let some a := xs[i]? | return []
  return (window? a.source c z).toList

/-- 核对比较跨度，指定了锚定区间时也核对中枢。
[061:26] 要比较力度，发现背驰，首先要搞清楚是哪两段比较，其实，只要是围绕一中枢的两段走势都可以比较力度。显然，对于60-65这个1分钟中枢，55-60与65开始的一段之间就可以比较。在实际操作中，65开始的走势，由于没实际走出来，所以在和55-60比较时，都可以先假设是进入背驰段。而当走势实际走出来，一旦力度大于前者，那么就可以断定背驰段不成立，也就不会出现背驰。在没有证据否定背驰之前，就要观察从65开始的一段其内部结构中的背驰情况，这种方法可以逐次下去，这就是区间套的定位方法，这种方法，可以在当下精确地定位走势的转折点。
-/
def DivGeometry.matchesWindow (w v : ForceWindow) : Bool :=
  w.earlier == v.earlier && w.later == v.later &&
    (w.anchor.isNone || decide (w.anchor = v.anchor))

/-- 对匹配的结构窗口分别检验创新极值和力度减弱。
[061:28] 因为背驰如果没有创新高，是不存在的。
-/
def DivGeometry.passes (mode : ForceCompareMode) (spec : ForceSpec) (h : List ℚ) (side : Dir)
    (w : ForceWindow) : Bool :=
  matchesWindow spec.window w && MakesNewExtreme h side w.earlier w.later &&
    forceWeaker mode spec h side

variable (rule : BlockRule.{0}) (analyse : DivAnalysis rule)

/-- 趋势至少有两个连续同向、严格分离的同级中枢。比较倒数两个中枢之间的 b 与最后中枢以后的 c。
`since` 是本走势在本层段表的起点，价格窗口另用底层坐标。
[027:14] 趋势，一定有至少两个同级别中枢，对于背驰来说，肯定不会发生在第一个中枢之后，肯定是至少是第二个中枢之后，对于那种延伸的趋势来说，很有可能在发生第100个中枢以后才背驰，当然，这种情况，一般来说，一百年见不到几次。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。
-/
def TrendDiv (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (trendWindow? f since side).any (passes mode spec h side)

/-- 单个中枢同侧相邻两次离开使用同一把力度尺；中间的反向回试把两次尝试分开。
[027:16] 如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。
[027:20] 注意，这里是把第一、三段看成两个走势类型之间的比较，这和趋势背驰里的情况有点不同，这两个走势类型是否一定是趋势，都问题不大，两个盘整在盘整背驰中也是可以比较力度的。
-/
def ConsolDiv (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  (analyse depth h).any fun f => (consolWindows f since side).any (passes mode spec h side)

/-- 只用当前前缀检验趋势或盘整的候选背驰，不预扣下一根价格或下一段回拉。
[043:40] 这种小级别背驰最终转化成大级别转折的情况，最值得注意的，是出现在趋势走势的冲顶或赶底之中，这种情况一般都会引发大级别的转折，这种例子前面都说过，例如20070104的工行，20061207的北辰实业、20070122的水井坊等。
[079:52] 有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。
-/
def DivOnline (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  TrendDiv rule analyse depth since h side spec mode || ConsolDiv rule analyse depth since h side spec mode

/-- 在同一前缀上保留在线判定，再用实际后缀检验：到确认时触及原中枢，期间未再刷新方向极值。
确认期限由后缀终点给出，不要求之后所有价格永远留在中枢一侧。
[079:52] 有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。
[098:16] 一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。
-/
def DivConfirmed (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) : Bool :=
  DivOnline rule analyse depth since h side spec mode &&
    match analyse depth h, bounds? h spec.window.later with
    | some f, some limits =>
      let cap := extremum side limits
      (sameScope f.stage since h.length).getLast?.any (fun z => tail.any (touches z)) &&
        tail.all (fun p => !ahead side p cap)
    | _, _ => false

/-- 三种互斥的终结机制。仍在发展的走势没有终结标签。
[033:24] 在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。
[027:18] 但如果是低位，那意义就不同了，因为多数的第二、三类买点，其实都是由盘整背驰构成的，而第一类买点，多数由趋势的背驰构成。
[044:24] 小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；
-/
inductive TrendEndCase where
  | divergentExit | internalReversal | reverseThird
  deriving DecidableEq

/-- 取中枢末覆盖段的底层末坐标。
[027:38] 以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。
-/
def DivGeometry.lastRaw? (z : Center ℚ) := z.cover.getLast?.map (·.source.last)

/-- 沿实际延拓寻找终结证据；尚未终结时不发出标签。
[079:52] 有人可能会提这样无聊的问题，在背驰的地方让他不背驰继续上涨难道不可以吗？这是一句废话，没有任何地方是该背驰的，背驰是一个合力的结果，如果合力最终的结果把可能的背驰给破坏了，就证明这地方没出现背驰，这也是合力的结果。
-/
def DivGeometry.confirmedCase? (depth since : Nat) (h tail : List ℚ) (side : Dir)
    (spec : ForceSpec) (mode : ForceCompareMode) : Option TrendEndCase := do
  let some f := analyse depth h | none
  let some g := analyse depth (h ++ tail) | none
  let zs := sameScope f.stage since h.length
  guard (trendSide side zs && !tail.isEmpty)
  let z ← zs.getLast?
  -- 延拓中允许原枢延伸，但须仍是同一组三段成核。
  let z' ← g.stage.ledger.centers.find? fun v =>
    decide (v.start = z.start ∧ v.a = z.a ∧ v.b = z.b ∧ v.c = z.c)
  let kind := match side with | .up => TrendKind.uptrend | .down => TrendKind.downtrend
  let finished ← g.stage.ledger.completed.find? fun b =>
    decide (b.first = since ∧ classifyTrend b = some kind ∧ b.centers.getLast? = some z')
  let endZ ← lastRaw? z'
  let w := spec.window.later
  if endZ ≤ w.first && g.stage.steps[finished.stop-1]?.any (fun s => s.source.last == w.last) &&
      TrendDiv rule analyse depth since h side spec mode &&
      DivConfirmed rule analyse depth since h tail side spec mode then return .divergentExit
  let opposite := side.flip
  if w.last ≤ endZ && ConsolDiv rule analyse depth z.start h side spec mode &&
      [z'.stop - 1, z'.stop].any (fun i =>
        g.stage.steps[i]?.any fun s => h.length ≤ s.source.last &&
          leaveAt g.stage z' opposite i) then return .internalReversal
  let i ← z'.departureIndex? opposite g.stage.steps
  let retest ← g.stage.steps[i+1]?
  guard (h.length ≤ retest.source.last)
  return .reverseThird

/-- 对已见的终结事件只给一个标签：独立 c 趋势背驰、末枢内部盘背后反向离开、直接反向三类点。
按延拓中已确认的末枢边界区分内部与独立 c；最后一类也必须实际出现三类事件。
[033:24] 在最极端的情况下，在a+A+b+B+c的走势系列类型里，a和c并不是必然存在的，而b完全可以是一个跳空缺口，这样，整个走势就可以简化为两个孤零零的中枢。
[027:16] 如果在第一个中枢就出现背驰，那不会是真正意义上的背驰，只能算是盘整背驰，其真正的技术含义，其实就是一个企图脱离中枢的运动，由于力度有限，被阻止而出现回到中枢里。
[044:26] 小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。
-/
def trendEndClassify (depth since : Nat) (h tail : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (label : TrendEndCase) : Bool :=
  decide (confirmedCase? rule analyse depth since h tail side spec mode = some label)

/-- 把在线趋势背驰或盘整背驰定位到该层后一个比较段的原始跨度。
[027:22] 这里，先补充一个定义：就是在某级别的某类型走势，如果构成背驰或盘整背驰，就把这段走势类型称为某级别的背驰段。
-/
def DivSegment (depth since : Nat) (h : List ℚ) (side : Dir) (spec : ForceSpec)
    (mode : ForceCompareMode) (source : Span) : Bool :=
  source == spec.window.later && DivOnline rule analyse depth since h side spec mode

/-- 检验区间套一层的跨度是否始末均有该层的来源边界。
[027:38] 以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。
-/
def DivGeometry.observedSpan {r k h} (f : DivFrame r k h) (s : Span) : Bool :=
  let xs := f.stage.steps
  xs.any (fun a => a.source == s) ||
    f.stage.ledger.completed.any (fun b =>
      xs[b.first]?.any (fun a => a.source.first == s.first) &&
      xs[b.stop-1]?.any (fun a => a.source.last == s.last)) ||
    (f.opened.isSome && s.last+1 == h.length &&
      (f.opened == some s.first || f.stage.ledger.centers.any (fun z =>
        xs[z.stop]?.any (fun a => a.source.first == s.first))))

/-- 逐级核查实际分解中的原始跨度。内层必须真包含于外层；中间层只需有此段，不逐层要求力度背驰。
[027:38] 以万科为例子，季度图上的第三段，在月线上，可以找到针对月线最后中枢的背驰段，而这背驰段，一定在季度线的背驰段里，而且区间比之小，把这个过程从月线延伸到周线、日线、30分钟、5分钟、1分钟，甚至是每笔成交，这区间不断缩小，在理论上，甚至可以达到这样一种情况，就是明确指出，就这一笔是万科历史底部的最后一笔成交，这成交完成意味着万科一个历史性底部的形成与时代的开始。
[056:66] 这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。
-/
def NestedDivChain (h : List ℚ) (chain : List (Nat × Span)) : Bool :=
  !chain.isEmpty && chain.all (fun (k,s) => s.last < h.length &&
    ((analyse k h).any (fun f => observedSpan f s) ||
      (analyse k (h.take (s.last+1))).any (fun f => observedSpan f s))) &&
    (chain.zip chain.tail).all fun ((k,u),(j,v)) =>
      decide (k = j+1 ∧ u.first ≤ v.first ∧ v.last ≤ u.last ∧ u ≠ v)

/-- 把离开方向映射为相应的趋势类型。
[029:14] 对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：
-/
def DivGeometry.trendKind : Dir → TrendKind
  | .up => .uptrend
  | .down => .downtrend

-- 转折要有两段相邻完成走势：原趋势以及异类后继；不能单凭次级三类点宣告大级别转折。
/-- 同级相邻的已完成块先为原趋势、后为异类走势，在给定原始时点衔接。
[029:14] 对于上涨的转折，有两种情况：下跌与盘整；对于下跌的转折，也有两种情况：上涨与盘整。转折是有级别的，关于转折与背驰的关系，有如下定理：
-/
def DivGeometry.oldTrend? (d : Decomposition ℚ) (side : Dir) (turn : Nat) : Option Span := do
  let done := d.ledger.completed
  let (a,_) ← (done.zip done.tail).find? fun (a,b) =>
    decide (a.stop = b.first ∧ classifyTrend a = some (trendKind side)) &&
      (classifyTrend b).any (fun kind => kind != trendKind side) &&
      d.steps[a.stop-1]?.any (fun s => s.source.last == turn)
  let first ← d.steps[a.first]?
  span? first.source.first turn

/-- 在大趋势实际覆盖的最后次级中枢上检验反向三类点或反向离开。
[044:24] 小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；
-/
def DivGeometry.subBreak (d : Decomposition ℚ) (span : Span) (earliest : Nat)
    (side : Dir) (thirdOnly : Bool) : Bool := Id.run do
  let zs := d.ledger.centers.filter fun z =>
    decide (span.first ≤ z.a.source.first ∧ z.c.source.last ≤ span.last)
  let some z := zs.getLast? | return false
  if let some i := z.departureIndex? side d.steps then
    if d.steps[i+1]?.any (fun s => earliest ≤ s.source.last) then return true
  if thirdOnly then return false
  return [z.stop-1, z.stop].any fun i =>
    d.steps[i]?.any fun s => earliest ≤ s.source.last && leaveAt d z side i

/-- 小级别出现背驰，大级别确已转折，并在其最后次级中枢找到反向三类点。
小级别可以低于次级；次级三类点是独立必要条件，不能单凭它推出转折。
[043:24] 如果市场的转折与背驰都有这在级别上一一对应关系，那这市场也太没意思、太刻板了，而由于这种小级别背驰逐步积累后导致大级别转折的可能，才使得市场充满当下的生机。
[044:24] 小级别顶背驰引发大级别向下的必要条件是该级别走势的最后一个次级别中枢出现第三类卖点；
[044:26] 小级别底背驰引发大级别向上的必要条件提是该级别走势的最后一个次级别中枢出现第三类买点。
[044:30] 注意，关于这种情况，只有必要条件，而没有充分条件，也就是说不能有一个充分的判断使得一旦出现某种情况，就必然导致大级别的转折。
-/
def SmallDivTriggersBigTurn (small big since turn : Nat) (h tail : List ℚ)
    (side : Dir) (spec : ForceSpec) (mode : ForceCompareMode) : Bool :=
  small < big && h.length-1 ≤ turn &&
    (List.range tail.length).any (fun n =>
      DivConfirmed rule analyse small since h (tail.take (n+1)) side spec mode) &&
    match analyse big (h ++ tail), analyse (big-1) (h ++ tail) with
    | some g, some sub =>
      (oldTrend? g.stage side turn).any (fun span => span.first ≤ spec.window.later.first &&
        subBreak sub.stage span (h.length-1) side.flip true)
    | _, _ => false

/-- 固定读法、端点、势和比较开关，遍历本次分解实际给出的本级比较窗。即使没有本级背驰，
次级三类点或反向离开仍可伴随一个已由完成块认证的大级别转折。
[056:66] 这个例子说明，一个大的盘整背驰段的内部结构，完全可以不必有该级别的背驰，完全可以小级别转大级别，昨天的图上就有这样一个标准的例子。
[102:38] 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。
-/
def TurnWithoutSameLevelDiv (big since : Nat) (h tail : List ℚ)
    (side : Dir) (spec : ForceSpec) (mode : ForceCompareMode) : Bool := Id.run do
  let some f := analyse big h | return false
  let some g := analyse big (h ++ tail) | return false
  let some sub := analyse (big-1) (h ++ tail) | return false
  let turn := h.length-1
  let some span := oldTrend? g.stage side turn | return false
  let windows := (trendWindow? f since side).toList ++ consolWindows f since side
  let divergent := windows.any fun w =>
    let v := if spec.window.anchor.isNone then {w with anchor := none} else w
    passes mode {spec with window := v} h side w
  let aligned := f.stage.steps[since]?.any (fun s => s.source.first == span.first)
  return big > 0 && !h.isEmpty && aligned && !divergent && subBreak sub.stage span turn side.flip false

end Chan.Defs.Dynamics
-- SOURCE END Astra Chan/Defs/Dynamics/Divergence.lean
end Source6

section Source7
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Defs/Limits/Liveness.lean

namespace Chan.Defs.Limits

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Path Chan.Defs.Signal

universe u
variable {P : Type u} {V : Type*}

/-- 无限路径按成交时间顺序取值，从时刻零起算。
[030:16] 而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。 -/
abbrev InfPath (P : Type*) := Nat → P

/-- 前 `n` 个观测对应半开时间段 `[0,n)`。空前缀不含零时刻的价格。
[030:16] 而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。 -/
def prefixOf (x : InfPath P) (n : Nat) : History P :=
  List.ofFn (fun i : Fin n => x i.val)

/-- 柱集可观测：性质一旦为真，总有一个有限前缀能作证，任何共享此前缀的延拓也为真。
[二级旁证 105:442] 另外，由于大多数人的科学与哲学知识都很贫乏，容易被人唬住，本ID给大家一个最简单的判别标准，就是可观察量。现代科学最基本的概念不是其他，而是可观察量，任何在科学的范围内谈论的东西，必须是可观察的。因此，那一切涉及非可观察量的玩意都是可疑的，例如什么宇宙的无穷，事件的无穷，神秘的自然规律，上帝的启示，辨证唯物主义或这主义那非主义的规律所引发的所谓宇宙规律等等。 -/
def PrefixObservable (property : InfPath P → Prop) : Prop :=
  ∀ x, property x → ∃ n, ∀ y, prefixOf y n = prefixOf x n → property y

/-- 依次把更长前缀交给同一读数器；最终常值并不要求在首次取到该值时就能确认。
[102:38] 而级别的存在，一个必然的结论就是，任何高级别的改变都必须先从低级别开始。例如，绝对不可能出现5分钟从下跌转折为上涨，而1分钟还在下跌段中。 -/
def EventuallyStable (readout : History P → V) (x : InfPath P) : Prop :=
  Filter.EventuallyConst (fun n => readout (prefixOf x n)) Filter.atTop

variable [LinearOrder P]

/-- B-24（存在）：抽取器把有限价格历史变为底层段列；合法规则下须能给出合法塔。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
def DecompExistsSpec (rule : BlockRule.{u}) (dir : CoarseDirPolicy P)
    (extractBase : History P → AltSeq P) : Prop :=
  InterfaceLaws rule → ∀ h, ∃ t : LevelTower rule dir (extractBase h), ValidDecomp t = true

/-- B-24（规范唯一）：在同一历史、规则与方向策略下，有一座满足指定规范的合法塔，
且所有这样的塔具有相同切点。
[101:56] 本ID理论最牛的地方，就是把仿佛毫无头绪的股票走势，给出了唯一分解定理，也就是走势必完美，这等于引进理想数，使得代数数论升堂入室一样牛。 -/
def CanonicalUniqueSpec (rule : BlockRule.{u}) (dir : CoarseDirPolicy P)
    (extractBase : History P → AltSeq P)
    (canonical : (h : History P) → LevelTower rule dir (extractBase h) → Prop) : Prop :=
  InterfaceLaws rule → ∀ h, ∃ a : CanonicalDecomp rule dir (extractBase h) (canonical h),
    ∀ b : CanonicalDecomp rule dir (extractBase h) (canonical h), a.val.sameCuts b.val

/-- 从已到达的历史取指定层的分解。账本自身记录的规则和层深必须与查询一致。
[101:52] 所谓走势必完美，就是本ID所给出的分型、笔、线段、不同级别走势类型所对应的递归函数，能将行情的任何走势唯一地分解。 -/
abbrev StageReader (P : Type u) [LinearOrder P] (rule : BlockRule.{u}) :=
  (depth : Nat) → History P → {d : Decomposition P // d.rule = rule ∧ d.depth = depth}

/-- B-24（有界终结）：在指定活性条件下，当前未完成的同一对象须在给定期限内完成或升级。
`id` 是跨前缀、跨级别不变的对象标识；升级要在严格更高级别的账本上认出该对象。
[017:60] 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”； -/
def BoundedTerminationSpec {Id : Type*} (rule : BlockRule.{u}) (readStage : StageReader P rule)
    (live : InfPath P → Prop) (bound : Nat)
    (pending complete promoted : Id → Decomposition P → Prop) : Prop :=
  ∀ x, live x → ∀ n depth id, pending id (readStage depth (prefixOf x n)).val →
    ∃ m, n < m ∧ m ≤ n + bound ∧
      (complete id (readStage depth (prefixOf x m)).val ∨
       ∃ higher, depth < higher ∧ promoted id (readStage higher (prefixOf x m)).val)

/-- B-24（弱安全）：买点以当时的分解判读。其后若形成同级中枢，买入后至少一次可达买价；
等价亦计，不计费用，不把买入时刻本身当卖出机会。
[107:22] 显然，没有任何绝对性可以保障上下上中，最后一个上一定有比第一个上有更高的高点，特别那种所谓奔走型的反弹，后上的高点可能只刚好触及前上的低点，因此，如果你一定要等上下上都完成才抛出，那很可能面对这样的尴尬，就是你在第一个上的最低点买的，在上下上的电梯过后，你只有一个可能连手续费都不够、稍纵即逝的卖点。因此，这种操作，注定是只有相对的理论上的绝对安全性，而没有具体操作上的绝对安全性。 -/
def WeakSafetySpec (rule : BlockRule.{u}) (readStage : StageReader P rule)
    (buyNow : Decomposition P → Prop) : Prop :=
  ∀ (x : InfPath P) (depth buy t : Nat), buy < t →
    buyNow (readStage depth (prefixOf x (buy+1))).val →
    (∃ z ∈ (readStage depth (prefixOf x (t+1))).val.ledger.centers,
      buy < z.c.source.last ∧ z.c.source.last ≤ t) →
    ∃ exitTime, buy < exitTime ∧ x buy ≤ x exitTime

end Chan.Defs.Limits
-- SOURCE END Astra Chan/Defs/Limits/Liveness.lean
end Source7

section Source8
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra Chan/Hypotheses/Dynamics.lean

namespace Chan.Hypotheses

open Chan.Defs.Alt Chan.Defs.Level Chan.Defs.Limits Chan.Defs.Order Chan.Defs.Signal

/-- 任一时刻之后，所选级别终会各自形成严格上涨和严格下跌的段。
两端取自原始价格路径，证据来自该有限时刻的分解；恒值路径与永久单边走势均不能作证。
[017:60] 因为某种类型的走势完成以后就会转化为其他类型的走势，对于下跌的走势来说，一旦完成，只能转化为上涨与盘整，因此，一旦能把握下跌走势转化的关节点买入，就在市场中占据了一个最有利的位置，而这个买点，就是前面反复强调的“第一类买点”； -/
def LivenessHyp (rule : BlockRule.{0}) (readStage : StageReader Rat rule)
    (depth : Nat) (x : InfPath Rat) : Prop :=
  ∀ (since : Nat) (side : Dir), ∃ t, ∃ s ∈ (readStage depth (prefixOf x (t+1))).val.steps,
    since ≤ s.source.first ∧ s.source.last ≤ t ∧ s.dir = side ∧
      match side with
      | .up => x s.source.first < x s.source.last
      | .down => x s.source.last < x s.source.first

/-- 以 `x (t+1) - x t` 作离散速度，惯性参数限制相邻两步速度变化的绝对值。
[033:34] c段大致从02281100算起，这个c要反转成功，在相同级别内至少要表现出比b的力度不能小，这可以从MACD来辅助分析，也可以从一个最直观的位置来分析，就是必须能重新回来b的起跌点，这就如同向天上抛球，力度大的如果还抛不高，那怎么能算力度大？ -/
def InertiaHyp (x : InfPath Rat) (cap : Rat) : Prop :=
  0 ≤ cap ∧ ∀ t, |(x (t+2) - x (t+1)) - (x (t+1) - x t)| ≤ cap

/-- 从指定离开时刻起，只把推力的同向部分记入预算；对任意有限时长均施加同一个上界。
起算时刻由离开段给定，假设自身不判断背驰。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
def ExhaustionHyp (thrust : InfPath Rat) (side : Dir) (onset : Nat) (budget : Rat) : Prop :=
  0 ≤ budget ∧ ∀ length : Nat, (Finset.range length).sum (fun i =>
    let f := thrust (onset + i)
    max 0 (match side with | .up => f | .down => -f)) ≤ budget

/-- 偏离锚定区间时，结构回复力指向区间，且强度至少为正数 `strength`。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
def PullbackHyp (zone : Bar Rat) (restore : Rat → Rat) (strength : Rat) : Prop :=
  0 < strength ∧ ∀ p, (p < zone.lo → strength ≤ restore p) ∧
    (zone.hi < p → restore p ≤ -strength)

/-- 取同色柱的非负高度。非空柱组左右镜像，左半直到中点不减；允许平顶。
奇数长度的中央柱是唯一没有镜像伙伴的柱，偶数长度则无此柱。
[024:28] 注意，看MACD 柱子的面积不需要全出来，一般柱子伸长的力度变慢时，把已经出现的面积乘2，就可以当成是该段的面积。 -/
abbrev SymUnimodalBarGroupHyp (heights : List Rat) : Prop :=
  heights ≠ [] ∧ heights = heights.reverse ∧ (∀ a ∈ heights, 0 ≤ a) ∧
    (heights.take ((heights.length + 1) / 2)).IsChain (· ≤ ·)

/-- 对称组的半组面积：左半各柱全计，奇数长度再计中央柱的一半。
例如 `[1,2,1]` 的读数为 `1 + 2/2 = 2`，而非含整根峰柱的 3。
[024:28] 注意，看MACD 柱子的面积不需要全出来，一般柱子伸长的力度变慢时，把已经出现的面积乘2，就可以当成是该段的面积。 -/
def halfPeakArea (heights : List Rat) : Rat :=
  let k := heights.length / 2
  (heights.take k).sum + (if heights.length % 2 = 1 then heights[k]?.getD 0 / 2 else 0)

/-- 一次动力学比较的观测与参数。离开方向、锚定区间、预算和待比较柱组均显式给出。
[072:32] 站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。 -/
structure DynamicsInputs where
  rule : BlockRule.{0}
  readStage : StageReader Rat rule
  depth : Nat
  price : InfPath Rat
  onset : Nat
  side : Dir
  anchor : Bar Rat
  restore : Rat → Rat
  accelerationCap : Rat
  thrustBudget : Rat
  minRestoringForce : Rat
  barHeights : List Rat

/-- 五项条件独立给证。在同一路径上，留给外推力的部分是速度变化减去结构回复力。
`t` 标记两步窗口的起点，回复力取中间时刻 `t+1` 的价位，无需虚设零时刻之前的速度。
[072:32] 站在纯理论的角度，形态学是最根本的。形态学，从本质上就是几何，这部分内容，是无须任何前提的。以前说的本ID理论成立的前提，其实并不是针对这部分的，主要是针对动力学部分。因此，就算一个庄家自己全买了，一个人天天自我交易，也永远逃不出形态学画的圈圈。而动力学方面的东西就不同了，必须有本ID要求的那两个前提：价格充分有效市场里的非完全绝对趋同交易。 -/
structure DynamicsHypBundle (s : DynamicsInputs) : Prop where
  liveness : LivenessHyp s.rule s.readStage s.depth s.price
  inertia : InertiaHyp s.price s.accelerationCap
  exhaustion : ExhaustionHyp
    (fun t => (s.price (t+2) - s.price (t+1)) - (s.price (t+1) - s.price t) -
      s.restore (s.price (t+1))) s.side s.onset s.thrustBudget
  pullback : PullbackHyp s.anchor s.restore s.minRestoringForce
  bars : SymUnimodalBarGroupHyp s.barHeights

/-- B-17 的待检条件命题。在线判据在离开时刻读取同一前缀及其最后中枢；
满足假设后只要求一次后续触及该中枢闭区间。
[098:16] 一个背驰后，无论是盘整背驰还是真正的背驰，理论只能保证其回拉原来的中枢，这是正确的思维方式，那么，回拉之后如何，这涉及预测。正确的思维是，把回拉后出现的情况进行完全的分类，根据每种分类对应的后果，决定你自己的对策。 -/
def ConditionalPullbackSpec (s : DynamicsInputs)
    (divNow : Chan.Defs.Path.History Rat → Decomposition Rat → Dir → Prop) : Prop :=
  let h := prefixOf s.price (s.onset + 1)
  let d := (s.readStage s.depth h).val
  DynamicsHypBundle s → divNow h d s.side →
    (∃ z, d.recent 0 d.steps.length = some z ∧ z.core = s.anchor) →
    ∃ t, s.onset < t ∧ s.anchor.lo ≤ s.price t ∧ s.price t ≤ s.anchor.hi

/-- 参与者标签；同方向、同价格的成交仍可区分不同参与者。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。 -/
structure MarketParticipant where
  id : Nat
  deriving DecidableEq

/-- 一笔已成交委托保留参与者、买卖方向（上为买、下为卖）和成交价。
[030:18] 交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。 -/
structure OrderEvent where
  participant : MarketParticipant
  side : Dir
  price : Rat
  deriving DecidableEq

/-- 同一时刻可有多笔成交，按先后排列；每笔成交均来自登记参与者。
第一笔成交之前沿用给定初价。
[030:32] 对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。 -/
structure TaggedMarket where
  participants : Finset MarketParticipant
  tape : Nat → List OrderEvent
  registered : ∀ t, ∀ e ∈ tape t, e.participant ∈ participants
  openingPrice : Rat

/-- 成交价投影取截至该时刻的最后一笔成交；空时刻沿用上次价格。
[030:18] 交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。 -/
def tradePrice (m : TaggedMarket) : Nat → Rat
  | 0 => ((m.tape 0).getLast?.map OrderEvent.price).getD m.openingPrice
  | t+1 => ((m.tape (t+1)).getLast?.map OrderEvent.price).getD (tradePrice m t)

/-- 价格有效性相对于给定估值口径：该时刻全部已发生交易所含的估值信息，
由当时的成交价格完全反映。估值函数作为参数独立指定。
[030:32] 对本ID的理论有一点是必须明确的，就是本ID的理论是对价格充分有效市场非完全绝对趋同交易的一个完全的数学公理化理论，唯一需要监控的就是价格充分有效市场与非完全绝对趋同交易这两个前提是否还存在，更重要的是，这归根结底是一套关系人的理论，只能不断在交易中修炼，最后比的可是功力。 -/
def EfficientPriceMarket (m : TaggedMarket)
    (value : List (List OrderEvent) → Rat) : Prop :=
  ∀ t, tradePrice m t = value (prefixOf m.tape (t+1))

/-- 两名实际参与者有不同的交易时序或方向：一人下单时，另一人没有同方向交易。
不能用两人完全同步的记录中不同日期的两笔成交作证。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。 -/
def NonIdenticalTrading (m : TaggedMarket) : Prop :=
  ∃ t u, ∃ a ∈ m.tape t, ∃ b ∈ m.tape u, a.participant ≠ b.participant ∧
    ∀ other ∈ m.tape t, other.participant = b.participant → other.side ≠ a.side

end Chan.Hypotheses
-- SOURCE END Astra Chan/Hypotheses/Dynamics.lean
end Source8

section Source9
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra ChanDyn/Well.lean

namespace ChanDyn

/-- D1 单中枢二阶模型。每步在旧位置取力，先更新速度，再以新速度移动；
每个时刻的回复场只读位置，与外力分开。场是否随时间改变由另一项假设检查。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
structure WellModel where
  center : Chan.Defs.Order.Bar ℚ
  position : ℕ → ℚ
  velocity : ℕ → ℚ
  restoring : ℕ → ℚ → ℚ
  externalForce : ℕ → ℚ
  inwardBelow : ∀ t x, x < center.lo → 0 ≤ restoring t x
  inwardAbove : ∀ t x, center.hi < x → restoring t x ≤ 0
  kick : ∀ t, velocity (t + 1) = velocity t + restoring t (position t) + externalForce t
  drift : ∀ t, position (t + 1) = position t + velocity (t + 1)

/-- 在上下边界外相距同一距离的两点，回复力大小相同、符号相反。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
def WellSymmetric (m : WellModel) : Prop :=
  ∀ t r, 0 ≤ r → m.restoring t (m.center.lo - r) = -m.restoring t (m.center.hi + r)

/-- 固定位置时，各时刻的回复力都与初始场相同。
[033:30] 那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。 -/
def WellTimeInvariant (m : WellModel) : Prop :=
  ∀ t x, m.restoring t x = m.restoring 0 x

/-- 半径从两侧边界分别向外量；超出给定半径时场为零。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
def WellBoundedRange (m : WellModel) (radius : ℚ) : Prop :=
  0 ≤ radius ∧ ∀ t x, x < m.center.lo - radius ∨ m.center.hi + radius < x →
    m.restoring t x = 0

/-- 从起点起的指定步数内，每次速度更新的外力项均为零。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
abbrev CoastingZeroThrust (m : WellModel) (start steps : ℕ) : Prop :=
  ∀ k : Fin steps, m.externalForce (start + k.val) = 0

/-- 已观察到的 b 段：从区间外静止出发，第 steps 步首次落入闭区间。
[033:26] 所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。 -/
abbrev FallsFromRest (m : WellModel) (start steps : ℕ) : Prop :=
  0 < steps ∧ m.velocity start = 0 ∧
  (∀ k : Fin steps, m.position (start + k.val) < m.center.lo ∨
    m.center.hi < m.position (start + k.val)) ∧
  m.center.lo ≤ m.position (start + steps) ∧ m.position (start + steps) ≤ m.center.hi

end ChanDyn
-- SOURCE END Astra ChanDyn/Well.lean
end Source9

section Source10
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra ChanDyn/Thrust.lean

namespace ChanDyn

/-- D2 固定位置场与逐步外推力分别进入速度更新。推力预算只约束外推力，
不扣除回复力；可以在同一条轨道上单独检验预算和是否回到中枢。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
structure ThrustModel where
  center : Chan.Defs.Order.Bar ℚ
  position : ℕ → ℚ
  velocity : ℕ → ℚ
  restoring : ℚ → ℚ
  thrust : ℕ → ℚ
  inwardBelow : ∀ x, x < center.lo → 0 ≤ restoring x
  inwardAbove : ∀ x, center.hi < x → restoring x ≤ 0
  kick : ∀ t, velocity (t + 1) = velocity t + restoring (position t) + thrust t
  drift : ∀ t, position (t + 1) = position t + velocity (t + 1)

/-- 计算指定步数内已施推力的绝对量之和。总支出不得超过预算，预算不得超过
显式比较临界值；对所有期限施加此式即可约束整个未来的预算。
[033:26] 对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。 -/
abbrev BudgetBound (m : ThrustModel) (start steps : ℕ) (budget critical : ℚ) : Prop :=
  (Finset.range steps).sum (fun k => |m.thrust (start + k)|) ≤ budget ∧ budget ≤ critical

/-- 从区间外的出发时刻计，在此后第一步至给定期限之间有一步落入中枢（含边界）。
[033:30] 那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。 -/
abbrev BoundedReturn (m : ThrustModel) (start deadline : ℕ) : Prop :=
  (m.position start < m.center.lo ∨ m.center.hi < m.position start) ∧
  ∃ k : Fin deadline, m.center.lo ≤ m.position (start + k.val + 1) ∧
    m.position (start + k.val + 1) ≤ m.center.hi

end ChanDyn
-- SOURCE END Astra ChanDyn/Thrust.lean
end Source10

section Source11
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra ChanDyn/Field.lean

namespace ChanDyn

/-- D3 有限个带级别的中枢。每个回复场按位置取值；同一位置上的场值以
单位质量、单位时间步长逐项相加，交易产生的力留给残余项。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
structure MultiCenterField (n : ℕ) where
  level : Fin n → ℕ
  center : Fin n → Chan.Defs.Order.Bar ℚ
  restoring : Fin n → ℚ → ℚ
  inwardBelow : ∀ i x, x < (center i).lo → 0 ≤ restoring i x
  inwardAbove : ∀ i x, (center i).hi < x → restoring i x ≤ 0

/-- 三个连续观测给出中间时刻的二阶差分；扣除该位置全部中枢的回复场。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
def residualThrust {n : ℕ} (m : MultiCenterField n) (price : ℕ → ℚ) (t : ℕ) : ℚ :=
  let x := price (t + 1)
  price (t + 2) - 2 * x + price t - Finset.univ.sum (fun i => m.restoring i x)

/-- 给定候选中枢必须离当前位置最近（到闭区间的距离，平局可任选）。
只保留它的力时，与总场的绝对误差须在给定容差内。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
abbrev NearestCenterDominates {n : ℕ} (m : MultiCenterField n) (x : ℚ)
    (nearest : Fin n) (tolerance : ℚ) : Prop :=
  let dist := fun i => max 0 (max ((m.center i).lo - x) (x - (m.center i).hi))
  (∀ i, dist nearest ≤ dist i) ∧
    |Finset.univ.sum (fun i => m.restoring i x) - m.restoring nearest x| ≤ tolerance

end ChanDyn
-- SOURCE END Astra ChanDyn/Field.lean
end Source11

section Source12
open _root_.Chan.Defs (Center)
-- SOURCE BEGIN Astra ChanDyn/Agents.lean

namespace ChanDyn

/-- D4 每组持有一个有理向量。被调度的组用自己的当前状态和所见时刻的
叠加向量更新，其余组保持原值；所见时刻不超过当下。轨道以初态为参数，
使改变初态后的稳定性可以在同一套响应规则下检验。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
structure AsyncAgentSystem (groups dim : ℕ) where
  active : ℕ → Fin groups → Bool
  seen : ℕ → Fin groups → ℕ
  causal : ∀ t i, seen t i ≤ t
  contribute : Fin groups → (Fin dim → ℚ) → Fin dim → ℚ
  respond : Fin groups → (Fin dim → ℚ) → (Fin dim → ℚ) → Fin dim → ℚ
  orbit : (Fin groups → Fin dim → ℚ) → ℕ → Fin groups → Fin dim → ℚ
  initial : ∀ x, orbit x 0 = x
  update : ∀ x t i, orbit x (t + 1) i =
    if active t i then
      respond i (orbit x t i) (fun d =>
        Finset.univ.sum (fun j => contribute j (orbit x (seen t i) j) d))
    else orbit x t i

/-- 指定域内的渐近稳定：平衡态保持不变，任意小扰动的轨道始终邻近它，
且域内各初态的轨道最终留在每个正半径邻域内。进入邻域的时刻可随半径
和初态改变，不要求在某个统一期限达到平衡态。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。 -/
def AsymptoticStable {groups dim : ℕ} (m : AsyncAgentSystem groups dim)
    (domain : (Fin groups → Fin dim → ℚ) → Prop) (eq : Fin groups → Fin dim → ℚ) : Prop :=
  let near := fun (x : Fin groups → Fin dim → ℚ) (r : ℚ) => ∀ i d, |x i d - eq i d| < r
  domain eq ∧ (∀ t, m.orbit eq t = eq) ∧
    (∀ ε : ℚ, 0 < ε → ∃ δ : ℚ, 0 < δ ∧
      ∀ x, domain x → near x δ → ∀ t, near (m.orbit x t) ε) ∧
    (∀ x, domain x → ∀ ε : ℚ, 0 < ε → ∃ n : ℕ, ∀ t ≥ n, near (m.orbit x t) ε)

end ChanDyn
-- SOURCE END Astra ChanDyn/Agents.lean
end Source12
end Astra

-- WITNESSES BEGIN
namespace ExternalRef

open Chan.Defs.Alt

/-- 有理价格的带时标折线：两端、以及各腿的严格正时长。 -/
structure Run (n : Nat) where
  price : Fin (n + 1) → ℚ
  time : Fin (n + 1) → Nat
  strict : ∀ i : Fin n, time i.castSucc < time i.succ

/-- 方向定向：上涨保号，下跌翻号。 -/
def along (side : Dir) (x : ℚ) : ℚ :=
  match side with | .up => x | .down => -x

/-- 首次穿越新价域的价格长度加权速度；无新价域时不产生读数。 -/
def L_break {n : Nat} (side : Dir) (edge : ℚ) (r : Run n) : Option ℚ :=
  let y := fun i => along side (r.price i - edge)
  let start := max 0 (y 0)
  let (peak, total) := (List.finRange n).foldl (fun (peak, total) i =>
    let next := max peak (y i.succ)
    let speed := (y i.succ - y i.castSucc) / ((r.time i.succ - r.time i.castSucc : Nat) : ℚ)
    (next, total + speed * (next - peak))) (start, 0)
  if start < peak then some (total / (peak - start)) else none

/-- 整段端点位移除以总时长。 -/
def L_avg {n : Nat} (side : Dir) (r : Run (n + 1)) : ℚ :=
  let last := Fin.last (n + 1)
  along side (r.price last - r.price 0) / ((r.time last - r.time 0 : Nat) : ℚ)

/-- 模型 A 在中枢 [-1,0] 带外以常数幅度回复。 -/
def restoreA (x : ℚ) : ℚ :=
  if 0 < x then -2 else if x < -1 then 2 else 0

/-- 模型 A 的半隐式 Euler 状态（位置、速度），显式传入阻尼和外力。 -/
def modelA (rho : ℚ) (force : Nat → ℚ) : Nat → ℚ × ℚ
  | 0 => (1, 0)
  | t + 1 =>
    let (x,v) := modelA rho force t
    let v' := rho * v + restoreA x + force t
    (x + v', v')

end ExternalRef

namespace Chan.Audit.Separation.Fm10e

open Chan.Defs Chan.Defs.Alt Chan.Defs.Order Chan.Defs.Signal Chan.Defs.Level
open ExternalRef

/-- 有限价史的序列读法；所用指数均在历史范围内。 -/
def price (xs : List ℚ) (t : Nat) : ℚ := xs.getD t 0

/-- W1：甲先将热启动状态吸收首价；乙把显式种子直接放在时刻零。 -/
theorem sep_ema_explicit_seed :
    Opus.Chan.Proxy.emaSeq ⟨3, by decide +kernel, .given 0⟩ (price [10,14]) 0 = 5 ∧
    Opus.Chan.Proxy.emaSeq ⟨3, by decide +kernel, .given 0⟩ (price [10,14]) 1 = 19/2 ∧
    Astra.Chan.Proxy.emaSeq ⟨1/2, by decide +kernel, by decide +kernel, some 0⟩ (price [10,14]) 0 = 0 ∧
    Astra.Chan.Proxy.emaSeq ⟨1/2, by decide +kernel, by decide +kernel, some 0⟩ (price [10,14]) 1 = 7 := by
  decide +kernel

/-- W2 早期种子距零宽价带一单位。 -/
def hotBand : Opus.Chan.Proxy.ZeroAxisBoundData := ⟨8, 9, by decide +kernel, by decide +kernel, 101, 0,
  by decide +kernel, 1, by decide +kernel⟩
/-- W2 首值播种的零宽价带与空旧窗。 -/
def coldBand : Astra.Chan.Proxy.ZeroAxisBoundData := ⟨fun _ => 101, 0, 9, by decide +kernel, 101, 0,
  by decide +kernel, fun _ _ => by decide +kernel⟩

/-- W2：零宽价带仍保留显式旧状态贡献；自动紧界只见到首值播种。 -/
theorem sep_zero_axis_explicit_seed :
    Opus.Chan.Proxy.difSeq (Opus.Chan.Proxy.MacdParams.standard (.given 100) .firstValue) (fun _ => 101) 8 =
      (25/27 : ℚ)^9 - (11/13 : ℚ)^9 ∧
    0 < (25/27 : ℚ)^9 - (11/13 : ℚ)^9 ∧
    hotBand.SeedWithinDelta (.given 100) ∧
    hotBand.bound = (25/27 : ℚ)^9 - (11/13 : ℚ)^9 ∧
    coldBand.delta = 0 ∧ (Astra.Chan.Proxy.macdSeq ⟨12, 26, 9, by decide +kernel⟩ coldBand.price 8).dif = 0 := by
  unfold Opus.Chan.Proxy.ZeroAxisBoundData.SeedWithinDelta
  decide +kernel

/-- W4：反向窗不包含任何相邻变化；只有乙口径保持端点差恒等式。 -/
theorem sep_endpoint_diff_reversed :
    Opus.Chan.Proxy.endpointDiff (price [1,5]) 1 0 = -4 ∧
    Opus.Chan.Proxy.posVar (price [1,5]) 1 0 - Opus.Chan.Proxy.negVar (price [1,5]) 1 0 ≠ -4 ∧
    Astra.Chan.Proxy.endpointDiff (price [1,5]) 1 0 = 0 ∧
    Astra.Chan.Proxy.posVar (price [1,5]) 1 0 - Astra.Chan.Proxy.negVar (price [1,5]) 1 0 = 0 := by
  decide +kernel

/-- W5：纯空头和跨吻两窗分别分离平均力度的符号和正负抵消。 -/
theorem sep_ma_avg_force_sign :
    Opus.Chan.Proxy.maAvgForce (price [8,6]) (price [10,10]) 0 1 = -3 ∧
    Astra.Chan.Proxy.maAvgForce (price [8,6]) (price [10,10]) 0 1 (by decide +kernel) = 3 ∧
    Opus.Chan.Proxy.maAvgForce (price [12,8]) (price [10,10]) 0 1 = 0 ∧
    Astra.Chan.Proxy.maAvgForce (price [12,8]) (price [10,10]) 0 1 (by decide +kernel) = 2 := by
  decide +kernel

/-- 构造使用闭端点的原始坐标跨度。 -/
def span (a b : Nat) (ordered : a ≤ b) : Span := ⟨a,b,ordered⟩
/-- 用显式价域构造段，起止价证书另存。 -/
def seg (a b : Nat) (ordered : a ≤ b) (d : Dir) (lo hi : ℚ)
    (inside : lo ≤ hi) : Seg ℚ := ⟨d, ⟨lo,hi,inside⟩, span a b ordered⟩

/-- W6 的全价域：端点未必给出区间极值。 -/
def slopeSeg : Seg ℚ := seg 0 4 (by decide +kernel) .up 0 10 (by decide +kernel)

/-- W6：一条价域 [0,10] 的段，真实起终价 2、6 不必为极值。 -/
theorem sep_seg_slope_endpoints :
    Opus.Chan.Defs.Dynamics.segSlope slopeSeg = 5/2 ∧
    Astra.Chan.Defs.Dynamics.segSlope slopeSeg ⟨2,6,by decide +kernel,by decide +kernel,by change (2 : ℚ) ≤ 6; decide +kernel⟩ (by decide +kernel) = 1 := by
  decide +kernel

/-- 按有时标的真实起终价构造带证据的单腿。 -/
def leg (a b : Nat) (elapsed : a < b) (p q : ℚ) : Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  if h : p ≤ q then
    ⟨seg a b (Nat.le_of_lt elapsed) .up p q h,
      ⟨p, q, ⟨le_rfl, h⟩, ⟨h, le_rfl⟩, h⟩, elapsed⟩
  else
    let h' := le_of_not_ge h
    ⟨seg a b (Nat.le_of_lt elapsed) .down q p h',
      ⟨p, q, ⟨h', le_rfl⟩, ⟨le_rfl, h'⟩, h'⟩, elapsed⟩

/-- W7 下跌前段。 -/
def bearB := leg 0 1 (by decide +kernel) 10 4
/-- W7 下跌后段。 -/
def bearC := leg 2 3 (by decide +kernel) 4 2
/-- 单腿窗口没有跨段连续性义务。 -/
def singleton (a : Astra.Chan.Defs.Dynamics.ImpulseLeg) : Astra.Chan.Defs.Dynamics.ImpulseWindow :=
  ⟨a, [], List.IsChain.singleton _⟩

/-- W7：未定向的下跌正变差全零、末速排序相反，定向后两种读法均区分 6 与 2。 -/
theorem sep_impulse_down_orientation :
    Opus.Chan.Defs.Dynamics.impulseFromRest .posVar [bearB.seg] = 0 ∧ Opus.Chan.Defs.Dynamics.impulseFromRest .posVar [bearC.seg] = 0 ∧
    Opus.Chan.Defs.Dynamics.impulseFromRest .terminalVelocity [bearB.seg] = -6 ∧
    Opus.Chan.Defs.Dynamics.impulseFromRest .terminalVelocity [bearC.seg] = -2 ∧
    Astra.Chan.Defs.Dynamics.impulseFromRest .down (singleton bearB) = ⟨6,6⟩ ∧
    Astra.Chan.Defs.Dynamics.impulseFromRest .down (singleton bearC) = ⟨2,2⟩ := by
  decide +kernel

/-- W9a 前段的折线。 -/
def breakB : Run 3 :=
  ⟨fun i => ([0,5,4,6] : List ℚ).getD i.val 0, Fin.val, fun i => Nat.lt_succ_self i.val⟩
/-- W9a 后段的折线。 -/
def breakC : Run 3 :=
  ⟨fun i => ([0,4,3,7] : List ℚ).getD i.val 0, Fin.val, fun i => Nat.lt_succ_self i.val⟩
/-- W9b 不经回踩的前段。 -/
def detourB : Run 1 := ⟨fun i => 4 * (i.val : ℚ), Fin.val, fun i => Nat.lt_succ_self i.val⟩
/-- W9b 含八步慢回踩的后段。 -/
def detourC : Run 3 :=
  ⟨fun i => ([0,4,3,8] : List ℚ).getD i.val 0,
   fun i => ([0,1,9,10] : List Nat).getD i.val 0, by intro i; fin_cases i <;> decide +kernel⟩

/-- 同一有时标折线转成甲方读取的段列。 -/
def legs {n : Nat} (r : Run n) : List (Seg ℚ) :=
  (List.finRange n).map fun i => (leg (r.time i.castSucc) (r.time i.succ) (r.strict i)
    (r.price i.castSucc) (r.price i.succ)).seg


/-- 以相邻链证明将三腿组合成乙方窗口。 -/
def legWindow (a b c : Astra.Chan.Defs.Dynamics.ImpulseLeg)
    (connected : [a,b,c].IsChain Astra.Chan.Defs.Dynamics.ImpulseLeg.followedBy) :
    Astra.Chan.Defs.Dynamics.ImpulseWindow := ⟨a,[b,c],connected⟩

/-- W9a 乙方的前窗。 -/
def breakBW := legWindow (leg 0 1 (by decide) 0 5)
  (leg 1 2 (by decide) 5 4) (leg 2 3 (by decide) 4 6) (by decide +kernel)
/-- W9a 乙方的后窗。 -/
def breakCW := legWindow (leg 0 1 (by decide) 0 4)
  (leg 1 2 (by decide) 4 3) (leg 2 3 (by decide) 3 7) (by decide +kernel)
/-- W9b 乙方的长回踩后窗。 -/
def detourCW := legWindow (leg 0 1 (by decide) 0 4)
  (leg 1 9 (by decide) 4 3) (leg 9 10 (by decide) 3 8) (by decide +kernel)

/-- W9a、W9b：首次突破、端点均速、从静止正变差对同一对有时标路径给出不同排序。 -/
theorem sep_impulse_vs_first_breakout :
    (L_avg .up breakB = 2 ∧ L_avg .up breakC = 7/3) ∧
    (L_break .up 0 breakB = some (9/2) ∧ L_break .up 0 breakC = some 4) ∧
    (Opus.Chan.Defs.Dynamics.impulseFromRest .posVar (legs breakB) = 8 ∧ Opus.Chan.Defs.Dynamics.impulseFromRest .posVar (legs breakC) = 9) ∧
    (Opus.Chan.Defs.Dynamics.impulseFromRest .terminalVelocity (legs breakB) = 2 ∧
     Opus.Chan.Defs.Dynamics.impulseFromRest .terminalVelocity (legs breakC) = 4) ∧
    (L_avg .up detourB = 4 ∧ L_avg .up detourC = 4/5) ∧
    (L_break .up 0 detourB = some 4 ∧ L_break .up 0 detourC = some (9/2)) ∧
    (Opus.Chan.Defs.Dynamics.impulseFromRest .posVar (legs detourB) = 4 ∧
      Opus.Chan.Defs.Dynamics.impulseFromRest .posVar (legs detourC) = 73/8) ∧
    (Astra.Chan.Defs.Dynamics.impulseFromRest .up breakBW = ⟨2,8⟩ ∧
     Astra.Chan.Defs.Dynamics.impulseFromRest .up breakCW = ⟨4,9⟩ ∧
     Astra.Chan.Defs.Dynamics.impulseFromRest .up (singleton (leg 0 1 (by decide) 0 4)) = ⟨4,4⟩ ∧
     Astra.Chan.Defs.Dynamics.impulseFromRest .up detourCW = ⟨5,73/8⟩) := by
  decide +kernel

/-- 甲方价格势、端点差及调用方选择的端点约定。 -/
def recipeO (conv : Opus.Chan.Defs.Dynamics.EndpointConv) : Opus.Chan.Defs.Dynamics.ForceRecipe ℚ :=
  ⟨Opus.Chan.Defs.Dynamics.CausalPotential.price ℚ, .endpointDiff, conv⟩
/-- 乙方价格势和匹配的先后跨度。 -/
def specA (a c : Span) (ordered : a.last ≤ c.first) (conv : Astra.Chan.Defs.Dynamics.EndpointConv) : Astra.Chan.Defs.Dynamics.ForceSpec :=
  ⟨⟨a,c,none,ordered⟩, ⟨fun _ x => x⟩, .endpointDiff, conv⟩

/-- 闭窗口 [0,1]。 -/
def w01 := span 0 1 (by decide +kernel)
/-- 闭窗口 [2,3]。 -/
def w23 := span 2 3 (by decide +kernel)

/-- 甲方非奇对称的正部价格势。 -/
def maxO : Opus.Chan.Defs.Dynamics.ForceSpec ℚ :=
  (⟨⟨fun x t => max (x t) 0, fun _ _ t h => congrArg (fun k => max k 0) (h t (Nat.le_refl t))⟩,
    .endpointDiff,.interiorOnly⟩ : Opus.Chan.Defs.Dynamics.ForceRecipe ℚ).withWindow ⟨w01,w23,none⟩
/-- 乙方同一非奇势，势以后定向。 -/
def maxA : Astra.Chan.Defs.Dynamics.ForceSpec :=
  {specA w01 w23 (by decide +kernel) .interiorOnly with potential := ⟨fun _ x => max x 0⟩}

/-- W11a、W11b：空头定向不与非奇势交换；时刻零没有前驱。 -/
theorem sep_eval_force_orient_and_zero :
    Opus.Chan.Defs.Dynamics.evalForce maxO .down (price [10,6]) .before = 0 ∧
    Astra.Chan.Defs.Dynamics.evalForce maxA [10,6] .down .earlier = some 4 ∧
    Opus.Chan.Defs.Dynamics.forceWeaker ((recipeO .leftClosed).withWindow ⟨w01,w23,none⟩)
      .strictLt .up (price [0,10,10,15]) ∧
    Astra.Chan.Defs.Dynamics.evalForce (specA w01 w23 (by decide +kernel) .withPredecessor) [0,10,10,15] .up .earlier = none ∧
    Astra.Chan.Defs.Dynamics.forceWeaker .strict (specA w01 w23 (by decide +kernel) .withPredecessor) [0,10,10,15] .up = false := by
  unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp
  decide +kernel

/-- W19：一次可见的触及有有限证书，永不触及却没有有限证书。 -/
theorem sep_prefix_observable_open_vs_clopen :
    Astra.Chan.Defs.Limits.PrefixObservable (fun x : Nat → ℚ => ∃ t, x t = 1) ∧
    ¬ Opus.Chan.Defs.Limits.PrefixObservable (fun x : Nat → ℚ => ∃ t, x t = 1) := by
  constructor
  · intro x hx
    obtain ⟨t, ht⟩ := hx
    refine ⟨t + 1, fun y hp => ⟨t, ?_⟩⟩
    have e := congrArg (fun xs : List ℚ => xs[t]?) hp
    have bound : t < t + 1 := Nat.lt_succ_self t
    simpa only [Astra.Chan.Defs.Limits.prefixOf, List.getElem?_ofFn, dite_eq_left bound,
      Option.some.injEq, ht] using e
  · intro f
    obtain ⟨n, hn⟩ := f (fun _ => 0)
    let y : Nat → ℚ := fun t => if t < n then 0 else 1
    have hp : Opus.Chan.Defs.Limits.prefixOf y n = Opus.Chan.Defs.Limits.prefixOf (fun _ : Nat => (0 : ℚ)) n :=
      congrArg List.ofFn (funext fun i => ite_eq_left i.isLt)
    obtain ⟨_, hbad⟩ := (hn y hp).mp ⟨n, by simp [y]⟩
    exact (by decide +kernel : (0 : ℚ) ≠ 1) hbad

/-- 初速 4、恒定加速度 -2 的滑行价轨。 -/
def coast (t : Nat) : ℚ := 10 + 5 * (t : ℚ) - (t : ℚ)^2

/-- W25：价格仍向上走，减去常数回复力后的外推力预算却为零。 -/
theorem sep_exhaustion_price_vs_thrust :
    ([coast 0,coast 1,coast 2,coast 3,coast 4] : List ℚ) = [10,14,16,16,14] ∧
    Astra.Chan.Hypotheses.ExhaustionHyp (fun t => Opus.Chan.Hypotheses.secondDiff coast t - (-2)) .up 0 0 ∧
    ¬ Opus.Chan.Hypotheses.ExhaustionHyp .up 0 0 coast := by
  refine ⟨by decide +kernel, ⟨by decide +kernel, ?_⟩, ?_⟩
  · intro n
    have hzero (i : Nat) : Opus.Chan.Hypotheses.secondDiff coast i - (-2) = 0 := by
      simp only [Opus.Chan.Hypotheses.secondDiff, coast, Nat.cast_add, Nat.cast_ofNat]
      ring
    simp only [Nat.zero_add, hzero, max_self, Finset.sum_const_zero, le_rfl]
  · intro h
    exact (by decide +kernel : ¬ (((List.range 2).map fun i =>
      max (Opus.Chan.Defs.Dynamics.orient .up coast (0 + i + 1) - Opus.Chan.Defs.Dynamics.orient .up coast (0 + i)) 0).sum ≤ 0)) (h 2)

/-- W27：有两个并列峰的偶数长度柱组只有乙能表达，半峰与全组面积相合。 -/
theorem sep_sym_unimodal_even_group :
    Astra.Chan.Hypotheses.SymUnimodalBarGroupHyp [1,2,2,1] ∧
    2 * Astra.Chan.Hypotheses.halfPeakArea [1,2,2,1] = 6 ∧
    (∀ p, ¬ Opus.Chan.Hypotheses.SymUnimodalBarGroupHyp ([1,2,2,1] : List ℚ) p) := by
  refine ⟨⟨by decide +kernel, by decide +kernel, ?_, by decide +kernel⟩, by decide +kernel, ?_⟩
  · intro a ha
    simp only [List.mem_cons, List.not_mem_nil, or_false] at ha
    rcases ha with rfl | rfl | rfl | rfl <;> decide +kernel
  · intro p h
    have e := h.1
    simp only [List.length_cons, List.length_nil] at e
    omega

/-- 甲方记录两个参与者同两日同步买入。 -/
def syncO : Opus.Chan.Hypotheses.TaggedMarket ℚ :=
  ⟨[⟨⟨0⟩,0,.up,10,1⟩,⟨⟨1⟩,0,.up,10,1⟩,⟨⟨0⟩,1,.up,11,1⟩,⟨⟨1⟩,1,.up,11,1⟩],
    price [10,11], by decide +kernel⟩
/-- 乙方成交带形式的同一同步交易。 -/
def syncA : Astra.Chan.Hypotheses.TaggedMarket :=
  ⟨{⟨0⟩, ⟨1⟩}, (fun t => if t < 2 then [⟨⟨0⟩,.up,10 + (t : ℚ)⟩,⟨⟨1⟩,.up,10 + (t : ℚ)⟩] else []),
    (by
      intro t e he
      split at he
      · simp only [List.mem_cons, List.not_mem_nil, or_false] at he
        rcases he with rfl | rfl <;> simp
      · simp at he), 10⟩

/-- W28b：同样的双人两日同步买入，跨日取样不能证明市场存在非趋同交易。 -/
theorem sep_non_identical_sync_pair :
    Opus.Chan.Hypotheses.NonIdenticalTrading syncO ∧ ¬ Astra.Chan.Hypotheses.NonIdenticalTrading syncA := by
  constructor
  · refine ⟨⟨⟨0⟩,0,.up,10,1⟩, by simp [syncO], ⟨⟨1⟩,1,.up,11,1⟩, by simp [syncO],
      ?_, Or.inl (by decide +kernel)⟩
    intro h
    exact (by decide +kernel : (0 : Nat) ≠ 1) (congrArg Opus.Chan.Hypotheses.MarketParticipant.id h)
  · rintro ⟨t, u, a, ha, b, hb, _, excludes⟩
    change a ∈ (if t < 2 then _ else []) at ha
    change b ∈ (if u < 2 then _ else []) at hb
    have ht : t < 2 := by by_contra h; simp [h] at ha
    have hu : u < 2 := by by_contra h; simp [h] at hb
    simp only [ite_eq_left ht, List.mem_cons, List.not_mem_nil, or_false] at ha
    simp only [ite_eq_left hu, List.mem_cons, List.not_mem_nil, or_false] at hb
    have up : a.side = .up := by rcases ha with rfl | rfl <;> rfl
    rcases hb with rfl | rfl
    · exact excludes ⟨⟨0⟩,.up,10 + (t : ℚ)⟩ (by simp [syncA, ht]) rfl up.symm
    · exact excludes ⟨⟨1⟩,.up,10 + (t : ℚ)⟩ (by simp [syncA, ht]) rfl up.symm

/-- 只在指定时刻释放一次外推力。 -/
def thrust (start : Nat) (f : ℚ) (t : Nat) : ℚ := if t = start then f else 0

/-- 乙方原样步进，即外部模型 A 的无阻尼对照。 -/
def undamped (f : Nat → ℚ) : Astra.ChanDyn.ThrustModel where
  center := ⟨-1,0,by decide +kernel⟩
  position t := (modelA 1 f t).1
  velocity t := (modelA 1 f t).2
  restoring := restoreA
  thrust := f
  inwardBelow := by intro x hx; simp [restoreA, hx, show ¬ 0 < x by linarith]
  inwardAbove := by intro x hx; simp [restoreA, hx]
  kick := by intro t; simp only [modelA, one_mul]
  drift := by intro t; rfl

/-- 甲方预算对照：参考窗口滑行，后窗外推力为 1。 -/
def opusBudget : Opus.ChanDyn.ThrustModel ℚ :=
  ⟨⟨-1,0,by decide +kernel, fun _ => restoreA⟩, thrust 2 1, 5/2⟩

/-- W29、W32：阻尼改变两步能否触边；滑行参考段会把甲的后段预算错误地锁为零。 -/
theorem sep_modelA_damping_and_budget :
    (modelA (1/2) (thrust 0 (8/3)) 2).1 = 0 ∧
    (modelA (1/2) (thrust 0 3) 2).1 = 1/2 ∧
    (undamped (thrust 0 (8/3))).position 2 = 1/3 ∧
    Astra.ChanDyn.BudgetBound (undamped (thrust 0 (8/3))) 0 2 (8/3) (8/3) ∧
    ¬ Opus.ChanDyn.BudgetBound opusBudget 0 2 2 4 ∧
    Astra.ChanDyn.BudgetBound (undamped (thrust 2 1)) 2 2 1 (5/2) := by
  unfold Opus.ChanDyn.BudgetBound
  decide +kernel

/-- 同一价腿投影同时给出段与真实端点，防止对拍样本拼错索引。 -/
def priceTable (legs : List Astra.Chan.Defs.Dynamics.ImpulseLeg) (i : Fin (legs.map (·.seg)).length) :
    DirectedEndpoints (legs.map (·.seg))[i.val] := by
  have hi : i.val < legs.length := by simpa only [List.length_map] using i.isLt
  rw [List.getElem_map]
  exact legs[i.val].prices

/-- 分离见证固定同一切块规则，不以算出的切块充当唯一性结论。 -/
def witnessRule : BlockRule.{0} := ⟨fun _ _ _ _ _ => some 1, fun _ _ _ _ _ => true⟩

/-- 只在当前输入实际等于观察快照时返回相应证书。 -/
def oneFrame (h₀ : List ℚ) (f : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 h₀) :
    Astra.Chan.Defs.Dynamics.DivAnalysis witnessRule :=
  fun k h => if hk : k = 0 then if hh : h = h₀ then some (hk.symm ▸ (hh.symm ▸ f)) else none else none

/-- 在前缀和实际延拓处各提供一份独立可验的观察证书。 -/
def twoFrames (h₀ h₁ : List ℚ) (f : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 h₀)
    (g : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 h₁) : Astra.Chan.Defs.Dynamics.DivAnalysis witnessRule :=
  fun k h => (oneFrame h₀ f k h).orElse (fun _ => oneFrame h₁ g k h)

/-- w13a 的逐时刻实价。 -/
def w13aH : List ℚ := [0,10,6,9,7,11]

/-- w13a 的有证据价腿。 -/
def w13aLegs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w13aH 0) (price w13aH 1),
   leg 1 2 (by decide +kernel) (price w13aH 1) (price w13aH 2),
   leg 2 3 (by decide +kernel) (price w13aH 2) (price w13aH 3),
   leg 3 4 (by decide +kernel) (price w13aH 3) (price w13aH 4),
   leg 4 5 (by decide +kernel) (price w13aH 4) (price w13aH 5)]

/-- 中枢由同一段表的相邻三段起核。 -/
def z13a : Center ℚ :=
  ⟨1, (w13aLegs[1]).seg, (w13aLegs[2]).seg, (w13aLegs[3]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w13aASteps : List (Seg ℚ) :=
  ((w13aLegs).take 4).map (·.seg)

/-- w13aA 的分解账本。 -/
def w13aAStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w13aASteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w13aLegs.take 4)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [z13a]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl
      (rcases hj with rfl)
      decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w13aA 的账本以同一历史核对价域和真实出入价。 -/
def w13aAFrame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w13aH where
  stage := w13aAStage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 4 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := some 4
  boundary := by
    intro j h
    have eq := Option.some.inj h; subst j; exact ⟨by decide +kernel, Or.inl (by decide +kernel)⟩


/-- 段表只含该前缀中声明完成的段。 -/
def w13aOSteps : List (Seg ℚ) :=
  ((w13aLegs).take 5).map (·.seg)

/-- w13aO 的分解账本。 -/
def w13aOStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w13aOSteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w13aLegs.take 5)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [z13a]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl
      (rcases hj with rfl)
      decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w13b 的逐时刻实价。 -/
def w13bH : List ℚ := [16,20,14,24,16,25]

/-- w13b 的有证据价腿。 -/
def w13bLegs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w13bH 0) (price w13bH 1),
   leg 1 2 (by decide +kernel) (price w13bH 1) (price w13bH 2),
   leg 2 3 (by decide +kernel) (price w13bH 2) (price w13bH 3),
   leg 3 4 (by decide +kernel) (price w13bH 3) (price w13bH 4),
   leg 4 5 (by decide +kernel) (price w13bH 4) (price w13bH 5)]

/-- 中枢由同一段表的相邻三段起核。 -/
def z13b : Center ℚ :=
  ⟨0, (w13bLegs[0]).seg, (w13bLegs[1]).seg, (w13bLegs[2]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w13bASteps : List (Seg ℚ) :=
  ((w13bLegs).take 4).map (·.seg)

/-- w13bA 的分解账本。 -/
def w13bAStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w13bASteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w13bLegs.take 4)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [z13b]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl
      (rcases hj with rfl)
      decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w13bA 的账本以同一历史核对价域和真实出入价。 -/
def w13bAFrame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w13bH where
  stage := w13bAStage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 4 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := some 4
  boundary := by
    intro j h
    have eq := Option.some.inj h; subst j; exact ⟨by decide +kernel, Or.inl (by decide +kernel)⟩


/-- 段表只含该前缀中声明完成的段。 -/
def w13bOSteps : List (Seg ℚ) :=
  ((w13bLegs).take 5).map (·.seg)

/-- w13bO 的分解账本。 -/
def w13bOStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w13bOSteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w13bLegs.take 5)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [z13b]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl
      (rcases hj with rfl)
      decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w14 的逐时刻实价。 -/
def w14H : List ℚ := [0,2,0,2,8,5,10,12,10,12,10,17]

/-- w14 的有证据价腿。 -/
def w14Legs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w14H 0) (price w14H 1),
   leg 1 2 (by decide +kernel) (price w14H 1) (price w14H 2),
   leg 2 3 (by decide +kernel) (price w14H 2) (price w14H 3),
   leg 3 4 (by decide +kernel) (price w14H 3) (price w14H 4),
   leg 4 5 (by decide +kernel) (price w14H 4) (price w14H 5),
   leg 5 6 (by decide +kernel) (price w14H 5) (price w14H 6),
   leg 7 8 (by decide +kernel) (price w14H 7) (price w14H 8),
   leg 8 9 (by decide +kernel) (price w14H 8) (price w14H 9),
   leg 9 10 (by decide +kernel) (price w14H 9) (price w14H 10),
   leg 10 11 (by decide +kernel) (price w14H 10) (price w14H 11)]

/-- 中枢由同一段表的相邻三段起核。 -/
def p14 : Center ℚ :=
  ⟨0, (w14Legs[0]).seg, (w14Legs[1]).seg, (w14Legs[2]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 中枢由同一段表的相邻三段起核。 -/
def z14 : Center ℚ :=
  ⟨6, (w14Legs[6]).seg, (w14Legs[7]).seg, (w14Legs[8]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w14ASteps : List (Seg ℚ) :=
  ((w14Legs).take 9).map (·.seg)

/-- w14A 的分解账本。 -/
def w14AStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w14ASteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w14Legs.take 9)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [p14,z14]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl | rfl
      all_goals (rcases hj with rfl)
      all_goals decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w14A 的账本以同一历史核对价域和真实出入价。 -/
def w14AFrame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w14H where
  stage := w14AStage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 9 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := some 10
  boundary := by
    intro j h
    have eq := Option.some.inj h; subst j; exact ⟨by decide +kernel, Or.inl (by decide +kernel)⟩


/-- 段表只含该前缀中声明完成的段。 -/
def w14OSteps : List (Seg ℚ) :=
  ((w14Legs).take 10).map (·.seg)

/-- w14O 的分解账本。 -/
def w14OStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w14OSteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w14Legs.take 10)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [p14,z14]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl | rfl
      all_goals (rcases hj with rfl)
      all_goals decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w15 的逐时刻实价。 -/
def w15H : List ℚ := [7,14,10,12,10,29/2,11,15]

/-- w15 的有证据价腿。 -/
def w15Legs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w15H 0) (price w15H 1),
   leg 1 2 (by decide +kernel) (price w15H 1) (price w15H 2),
   leg 2 3 (by decide +kernel) (price w15H 2) (price w15H 3),
   leg 3 4 (by decide +kernel) (price w15H 3) (price w15H 4),
   leg 4 5 (by decide +kernel) (price w15H 4) (price w15H 5),
   leg 5 6 (by decide +kernel) (price w15H 5) (price w15H 6),
   leg 6 7 (by decide +kernel) (price w15H 6) (price w15H 7)]

/-- 中枢由同一段表的相邻三段起核。 -/
def z15 : Center ℚ :=
  ⟨1, (w15Legs[1]).seg, (w15Legs[2]).seg, (w15Legs[3]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w15Steps : List (Seg ℚ) :=
  ((w15Legs).take 6).map (·.seg)

/-- w15 的分解账本。 -/
def w15Stage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w15Steps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w15Legs.take 6)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [z15]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl
      (rcases hj with rfl)
      decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w15 的账本以同一历史核对价域和真实出入价。 -/
def w15Frame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w15H where
  stage := w15Stage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 6 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := some 6
  boundary := by
    intro j h
    have eq := Option.some.inj h; subst j; exact ⟨by decide +kernel, Or.inl (by decide +kernel)⟩


/-- w16P 的逐时刻实价。 -/
def w16PH : List ℚ := [0,3,0,3,12,10,12,10,20]

/-- w16P 的有证据价腿。 -/
def w16PLegs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w16PH 0) (price w16PH 1),
   leg 1 2 (by decide +kernel) (price w16PH 1) (price w16PH 2),
   leg 2 3 (by decide +kernel) (price w16PH 2) (price w16PH 3),
   leg 3 4 (by decide +kernel) (price w16PH 3) (price w16PH 4),
   leg 4 5 (by decide +kernel) (price w16PH 4) (price w16PH 5),
   leg 5 6 (by decide +kernel) (price w16PH 5) (price w16PH 6),
   leg 6 7 (by decide +kernel) (price w16PH 6) (price w16PH 7),
   leg 7 8 (by decide +kernel) (price w16PH 7) (price w16PH 8)]

/-- 中枢由同一段表的相邻三段起核。 -/
def p16 : Center ℚ :=
  ⟨0, (w16PLegs[0]).seg, (w16PLegs[1]).seg, (w16PLegs[2]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 中枢由同一段表的相邻三段起核。 -/
def z16 : Center ℚ :=
  ⟨4, (w16PLegs[4]).seg, (w16PLegs[5]).seg, (w16PLegs[6]).seg, [], by decide +kernel, by decide +kernel, by
    intro s hs; simp at hs⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w16PSteps : List (Seg ℚ) :=
  ((w16PLegs).take 7).map (·.seg)

/-- w16P 的分解账本。 -/
def w16PStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w16PSteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w16PLegs.take 7)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [p16,z16]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl | rfl
      all_goals (rcases hj with rfl)
      all_goals decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }

/-- w16P 的账本以同一历史核对价域和真实出入价。 -/
def w16PFrame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w16PH where
  stage := w16PStage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 7 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := some 7
  boundary := by
    intro j h
    have eq := Option.some.inj h; subst j; exact ⟨by decide +kernel, Or.inl (by decide +kernel)⟩


/-- w16E 的逐时刻实价。 -/
def w16EH : List ℚ := [0,3,0,3,12,10,12,10,20,8,9]

/-- w16E 的有证据价腿。 -/
def w16ELegs : List Astra.Chan.Defs.Dynamics.ImpulseLeg :=
  [leg 0 1 (by decide +kernel) (price w16EH 0) (price w16EH 1),
   leg 1 2 (by decide +kernel) (price w16EH 1) (price w16EH 2),
   leg 2 3 (by decide +kernel) (price w16EH 2) (price w16EH 3),
   leg 3 4 (by decide +kernel) (price w16EH 3) (price w16EH 4),
   leg 4 5 (by decide +kernel) (price w16EH 4) (price w16EH 5),
   leg 5 6 (by decide +kernel) (price w16EH 5) (price w16EH 6),
   leg 6 7 (by decide +kernel) (price w16EH 6) (price w16EH 7),
   leg 7 8 (by decide +kernel) (price w16EH 7) (price w16EH 8),
   leg 8 9 (by decide +kernel) (price w16EH 8) (price w16EH 9),
   leg 9 10 (by decide +kernel) (price w16EH 9) (price w16EH 10)]

/-- 中枢由同一段表的相邻三段起核。 -/
def z16E : Center ℚ :=
  ⟨4, (w16ELegs[4]).seg, (w16ELegs[5]).seg, (w16ELegs[6]).seg, [(w16ELegs[7]).seg, (w16ELegs[8]).seg], by decide +kernel, by decide +kernel, by
    intro s hs
    simp only [List.mem_cons, List.not_mem_nil, or_false] at hs
    rcases hs with rfl | rfl <;> decide +kernel⟩

/-- 段表只含该前缀中声明完成的段。 -/
def w16ESteps : List (Seg ℚ) :=
  ((w16ELegs).take 10).map (·.seg)

/-- 完成趋势块：两枢足迹和三段成核位置逐一认证。 -/
def w16Finished : Finished w16ESteps where
  first := 0
  stop := 9
  bounded := by decide +kernel
  centers := [p16,z16E]
  inside := by
    intro z h
    simp only [List.mem_cons, List.not_mem_nil, or_false] at h
    rcases h with rfl | rfl
    all_goals decide +kernel
  ordered := by decide +kernel
  accounted := by
    intro i _ _ hi seed
    change i + 3 ≤ 9 at hi
    have hh : i ≤ 9 - 3 := by omega
    interval_cases i <;> revert seed <;> decide +kernel


/-- w16E 的分解账本。 -/
def w16EStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w16ESteps
  marks := [0,9]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    price := priceTable (w16ELegs.take 10)
    legal := by intro _ _; rfl
    completed := [w16Finished]
    aligned := rfl
    centers := [p16,z16E]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl | rfl
      all_goals (rcases hj with rfl | rfl)
      all_goals decide +kernel
    accounts := by
      intro b hb
      simp only [List.mem_singleton] at hb; subst b; rfl
    origin := 0
    originBounded := by decide +kernel
  }

/-- w16E 的账本以同一历史核对价域和真实出入价。 -/
def w16EFrame : Astra.Chan.Defs.Dynamics.DivFrame witnessRule 0 w16EH where
  stage := w16EStage
  atRule := rfl
  atDepth := rfl
  observed := by
    intro i
    change Fin 10 at i
    fin_cases i <;> decide +kernel
  chronological := by decide +kernel
  opened := none
  boundary := by
    intro j h
    cases h


/-- 段表只含该前缀中声明完成的段。 -/
def w16OSteps : List (Seg ℚ) :=
  ((w16ELegs).take 10).map (·.seg)

/-- w16O 的分解账本。 -/
def w16OStage : Decomposition ℚ where
  depth := 0
  rule := witnessRule
  steps := w16OSteps
  marks := [0]
  ledger := {
    validMarks := by
      refine ⟨by decide +kernel, by decide +kernel, ?_⟩
      intro j h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl
      decide +kernel
    price := priceTable (w16ELegs.take 10)
    legal := by intro p h; simp at h
    completed := []
    aligned := rfl
    centers := [p16,z16]
    chronological := by decide +kernel
    actual := by
      intro z h
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h
      rcases h with rfl | rfl
      all_goals decide +kernel
    respectsCuts := by
      intro z h j hj
      simp only [List.mem_cons, List.not_mem_nil, or_false] at h hj
      rcases h with rfl | rfl
      all_goals (rcases hj with rfl)
      all_goals decide +kernel
    accounts := by
      intro b hb
      simp at hb
    origin := 0
    originBounded := by decide +kernel
  }
/-- W13：标准进入—出核 比较与同一中枢的两次出核，在盲写版本中各漏一类。 -/
theorem sep_consol_div_disjoint :
    Opus.Chan.Defs.Dynamics.ConsolDiv (recipeO .interiorOnly) .strictLt .up
      w13aOStage (price w13aH) z13a 0 4 ∧
    Astra.Chan.Defs.Dynamics.ConsolDiv witnessRule (oneFrame w13aH w13aAFrame) 0 0 w13aH .up
      (specA w01 (span 4 5 (by decide)) (by decide) .interiorOnly) .strict = false ∧
    (∀ i, ¬ Opus.Chan.Defs.Dynamics.ConsolDiv (recipeO .interiorOnly) .strictLt .up
      w13bOStage (price w13bH) z13b i 4) ∧
    Astra.Chan.Defs.Dynamics.ConsolDiv witnessRule (oneFrame w13bH w13bAFrame) 0 0 w13bH .up
      (specA w23 (span 4 5 (by decide)) (by decide) .interiorOnly) .strict = true := by
  refine ⟨?_, by decide +kernel, ?_, by decide +kernel⟩
  · refine ⟨by simp [w13aOStage], by decide, by decide, ?_, ?_, ?_⟩
    · intro w hw _
      change w ∈ [z13a] at hw
      simp only [List.mem_singleton] at hw
      subst w
      exact le_rfl
    · rintro ⟨prev,hprev,hstop,_⟩
      change prev ∈ [z13a] at hprev
      simp only [List.mem_singleton] at hprev
      subst prev
      exact (by decide : ¬ z13a.stop ≤ 0) hstop
    · refine ⟨(w13aLegs[0]).seg, (w13aLegs[4]).seg, rfl, rfl, rfl, rfl, ?_, ?_⟩
      · change (10 : ℚ) < 11; decide
      · unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp; decide +kernel
  · intro i hi
    exact Nat.not_lt_zero i hi.2.1

/-- W14：乙比较三腿合成的净位移 8，甲只能单取一腿，最强同向腿也弱于后段 7。 -/
theorem sep_trend_div_composite_b :
    Astra.Chan.Defs.Dynamics.TrendDiv witnessRule (oneFrame w14H w14AFrame) 0 0 w14H .up
      (specA (span 3 6 (by decide)) (span 10 11 (by decide)) (by decide) .interiorOnly) .strict = true ∧
    (∀ i, ¬ Opus.Chan.Defs.Dynamics.TrendDiv (recipeO .interiorOnly) .strictLt .up
      w14OStage (price w14H) z14 i 9) := by
  refine ⟨by decide +kernel, ?_⟩
  rintro i ⟨_, hi, _, _, ⟨prev, hprev, hstop, _⟩, b, c, hb, hc, hdir, _, _, hweak⟩
  change prev ∈ [p14,z14] at hprev
  simp only [List.mem_cons, List.not_mem_nil, or_false] at hprev
  have hlo : 3 ≤ i := by
    rcases hprev with rfl | rfl
    · exact hstop
    · exact Nat.le_trans (by decide : 3 ≤ z14.stop) hstop
  change i < 6 at hi
  change some (w14Legs[9]).seg = some c at hc
  injection hc with hc
  subst c
  interval_cases i
  · change some (w14Legs[3]).seg = some b at hb
    injection hb with hb
    subst b
    revert hweak
    unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp
    decide +kernel
  · change some (w14Legs[4]).seg = some b at hb
    injection hb with hb
    subst b
    cases hdir
  · change some (w14Legs[5]).seg = some b at hb
    injection hb with hb
    subst b
    revert hweak
    unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp
    decide +kernel

/-- W15：同一前缀在两口径均在线（各自比较合法先段）；8 跳穿 [10,12]，不命中离散闭核。 -/
theorem sep_div_confirmed_gap_through :
    z15.core.lo = 10 ∧ z15.core.hi = 12 ∧
    Opus.Chan.Defs.Dynamics.DivConfirmed (recipeO .interiorOnly) .strictLt .up
      w15Stage z15 0 6 w15H [8] ∧
    Astra.Chan.Defs.Dynamics.DivOnline witnessRule (oneFrame w15H w15Frame) 0 0 w15H .up
      (specA (span 4 5 (by decide)) (span 6 7 (by decide)) (by decide) .interiorOnly) .strict = true ∧
    Astra.Chan.Defs.Dynamics.DivConfirmed witnessRule (oneFrame w15H w15Frame) 0 0 w15H [8] .up
      (specA (span 4 5 (by decide)) (span 6 7 (by decide)) (by decide) .interiorOnly) .strict = false := by
  refine ⟨by decide +kernel, by decide +kernel, ?_, by decide +kernel, by decide +kernel⟩
  refine ⟨⟨by simp [w15Stage], by decide, by decide, by decide, (w15Legs[0]).seg, rfl, rfl, ?_, ?_⟩,
    ?_, 8, by simp, ?_⟩
  · change (14 : ℚ) < 15; decide
  · unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp; decide +kernel
  · intro p hp
    simp only [List.mem_singleton] at hp
    subst p
    change ¬ (15 : ℚ) < 8; decide
  · change ¬ (12 : ℚ) < 8; decide

/-- W16：先顺向走强且无趋势背驰，延拓认证反向三卖；乙归类，甲三类皆不可满足。 -/
theorem sep_trend_end_non_exhaustive :
    Opus.Chan.Defs.Dynamics.ForwardExit .up w16OStage z16 ∧
    (∀ label, ¬ Opus.Chan.Defs.Dynamics.trendEndClassify (recipeO .interiorOnly)
      .strictLt .up w16OStage (price w16EH) z16 label) ∧
    Astra.Chan.Defs.Dynamics.trendEndClassify witnessRule
      (twoFrames w16PH w16EH w16PFrame w16EFrame) 0 0 w16PH [8,9] .up
      (specA (span 3 4 (by decide)) (span 7 8 (by decide)) (by decide) .interiorOnly) .strict
      .reverseThird = true := by
  have hf : Opus.Chan.Defs.Dynamics.ForwardExit .up w16OStage z16 := by
    refine ⟨7, by decide, (w16ELegs[7]).seg, rfl, rfl, ?_⟩
    change (12 : ℚ) < 20; decide
  refine ⟨hf, ?_, by decide +kernel⟩
  intro label hl
  cases label with
  | consolidationReversal => exact hl.1 hf
  | reverseThird => exact hl.1 hf
  | divergenceExit =>
    rcases hl.2 with ⟨i, j, _, hi, hj, _, ⟨prev, hprev, hstop, _⟩, b, c, hb, hc, _, hdir, hext, hweak⟩
    change prev ∈ [p16,z16] at hprev
    simp only [List.mem_cons, List.not_mem_nil, or_false] at hprev
    have ilo : 3 ≤ i := by
      rcases hprev with rfl | rfl
      · exact hstop
      · exact Nat.le_trans (by decide : 3 ≤ z16.stop) hstop
    change i < 4 at hi
    have ie : i = 3 := by omega
    subst i
    change some (w16ELegs[3]).seg = some b at hb
    injection hb with hb
    subst b
    change 7 ≤ j at hj
    have jhi := (List.getElem?_eq_some_iff.mp hc).1
    change j < 10 at jhi
    interval_cases j
    · change some (w16ELegs[7]).seg = some c at hc
      injection hc with hc
      subst c
      have notWeaker : ¬ Opus.Chan.Defs.Dynamics.forceWeaker
          ((recipeO .interiorOnly).withWindow
            (Opus.Chan.Defs.Dynamics.ForceWindow.ofSegs
              (w16ELegs[3]'(by decide)).seg (w16ELegs[7]'(by decide)).seg (some z16)))
           .strictLt .up (price w16EH) := by
        unfold Opus.Chan.Defs.Dynamics.forceWeaker Opus.Chan.Defs.Dynamics.ForceCompareMode.cmp
        decide +kernel
      exact notWeaker hweak
    · change some (w16ELegs[8]).seg = some c at hc
      injection hc with hc
      subst c
      cases hdir
    · change some (w16ELegs[9]).seg = some c at hc
      injection hc with hc
      subst c
      change (12 : ℚ) < 9 at hext
      exact (by decide : ¬ (12 : ℚ) < 9) hext

section ModelB

open Astra.ChanDyn

/-- 两维状态的坐标读数。 -/
def vec (a b : ℚ) (j : Fin 2) : ℚ := if j = 0 then a else b

/-- 半隐递推的伴随状态轨道：依次保存本期值与上一期值。 -/
def bOrbit (k0 k1 : ℚ) (x : Fin 1 → Fin 2 → ℚ) : ℕ → Fin 1 → Fin 2 → ℚ
  | 0 => x
  | t + 1 => fun i =>
    let s := bOrbit k0 k1 x t i
    vec ((1 - k0) * s 0 - k1 * s 1) (s 0)

/-- 乙方一组二维的模型 B 实例；状态恰保存完整二阶信息。 -/
def modelB (k0 k1 : ℚ) : AsyncAgentSystem 1 2 where
  active _ _ := true
  seen t _ := t
  causal _ _ := le_rfl
  contribute _ v := v
  respond _ _ v := vec ((1 - k0) * v 0 - k1 * v 1) (v 0)
  orbit := bOrbit k0 k1
  initial _ := rfl
  update x t i := by
    have hi : i = 0 := Subsingleton.elim _ _
    subst i
    simp [bOrbit]

/-- 模型 B 的状态坐标。 -/
def bCoord (k0 k1 : ℚ) (x : Fin 1 → Fin 2 → ℚ) (t : ℕ) (j : Fin 2) : ℚ :=
  (modelB k0 k1).orbit x t 0 j

private theorem bCoord_succ_zero (k0 k1 : ℚ) (x : Fin 1 → Fin 2 → ℚ) (t : ℕ) :
    bCoord k0 k1 x (t+1) 0 = (1-k0)*bCoord k0 k1 x t 0-k1*bCoord k0 k1 x t 1 := rfl

private theorem bCoord_succ_one (k0 k1 : ℚ) (x : Fin 1 → Fin 2 → ℚ) (t : ℕ) :
    bCoord k0 k1 x (t+1) 1 = bCoord k0 k1 x t 0 := rfl

private theorem bCoord_two (c : ℚ) (x : Fin 1 → Fin 2 → ℚ) (t : ℕ) (j : Fin 2) :
    bCoord 1 c x (t+2) j = -c * bCoord 1 c x t j := by
  fin_cases j
  · change bCoord 1 c x (t+2) 0 = -c * bCoord 1 c x t 0
    rw [show t+2 = (t+1)+1 by omega, bCoord_succ_zero, bCoord_succ_one]
    ring
  · change bCoord 1 c x (t+2) 1 = -c * bCoord 1 c x t 1
    rw [show t+2 = (t+1)+1 by omega, bCoord_succ_one, bCoord_succ_zero]
    ring

private theorem twoStep_pow (f : ℕ → ℚ) (c : ℚ) (h : ∀ t, f (t+2) = c * f t)
    (n r : ℕ) : f (2*n+r) = c^n * f r := by
  induction n with
  | zero => simp
  | succ n ih =>
    rw [show 2*(n+1)+r = 2*n+r+2 by omega, h, ih, pow_succ]
    ring

private theorem twoStep_abs (f : ℕ → ℚ) (c : ℚ) (h : ∀ t, f (t+2) = c * f t)
    (t : ℕ) : |f t| = |c|^(t/2) * |f (t%2)| := by
  have he := twoStep_pow f c h (t/2) (t%2)
  rw [show 2*(t/2)+t%2 = t by omega] at he
  rw [he, abs_mul, abs_pow]

private theorem half_lt (f : ℕ → ℚ) (h : ∀ t, f (t+2) = -(1/2) * f t)
    (ε : ℚ) (h0 : |f 0| < ε) (h1 : |f 1| < ε) (t : ℕ) : |f t| < ε := by
  have hr : |f (t%2)| < ε := by
    rcases (show t%2=0 ∨ t%2=1 by omega) with he | he
    · simpa [he] using h0
    · simpa [he] using h1
  rw [twoStep_abs f _ h]
  norm_num
  exact (mul_le_of_le_one_left (abs_nonneg _) (pow_le_one₀ (by norm_num) (by norm_num))).trans_lt hr

private theorem half_eventual (f : ℕ → ℚ) (h : ∀ t, f (t+2) = -(1/2) * f t)
    (ε : ℚ) (he : 0 < ε) : ∃ n : ℕ, ∀ t ≥ n, |f t| < ε := by
  let M := max |f 0| |f 1| + 1
  have hM : 0 < M := by
    have hn : 0 ≤ max |f 0| |f 1| := (abs_nonneg _).trans (le_max_left ..)
    dsimp [M]
    linarith
  obtain ⟨n, hn⟩ := exists_pow_lt_of_lt_one (div_pos he hM) (show (1/2:ℚ) < 1 by norm_num)
  refine ⟨2*n, fun t ht => ?_⟩
  have hr : |f (t%2)| ≤ M := by
    rcases (show t%2=0 ∨ t%2=1 by omega) with hh | hh
    · rw [hh]
      exact (le_max_left ..).trans (by dsimp [M]; linarith)
    · rw [hh]
      exact (le_max_right ..).trans (by dsimp [M]; linarith)
  have hp : (1/2:ℚ)^(t/2) ≤ (1/2:ℚ)^n := by
    rw [show t/2=n+(t/2-n) by omega, pow_add]
    exact mul_le_of_le_one_right (by positivity) (pow_le_one₀ (by norm_num) (by norm_num))
  rw [twoStep_abs f _ h]
  norm_num
  calc
    _ ≤ (1/2:ℚ)^n * M := mul_le_mul hp hr (abs_nonneg _) (by positivity)
    _ < ε := (lt_div_iff₀ hM).mp hn

/-- 一组二维系统的零平衡态。 -/
def zeroOne : Fin 1 → Fin 2 → ℚ := fun _ _ => 0

private theorem modelB_half_stable :
    AsymptoticStable (modelB 1 (1/2)) (fun _ => True) zeroOne := by
  refine ⟨trivial, ?_, ?_, ?_⟩
  · intro t
    induction t with
    | zero => rfl
    | succ t ih =>
      funext i d
      have hi : i = 0 := Subsingleton.elim _ _
      subst i
      have h0 := congrFun (congrFun ih 0) 0
      have h1 := congrFun (congrFun ih 0) 1
      change bCoord 1 (1/2) zeroOne t 0 = 0 at h0
      change bCoord 1 (1/2) zeroOne t 1 = 0 at h1
      fin_cases d
      · change bCoord 1 (1/2) zeroOne (t+1) 0 = 0
        rw [bCoord_succ_zero, h0, h1]
        ring
      · change bCoord 1 (1/2) zeroOne (t+1) 1 = 0
        rw [bCoord_succ_one, h0]
  · intro ε he
    refine ⟨ε, he, ?_⟩
    intro x _ hx t i d
    have hi : i = 0 := Subsingleton.elim _ _
    subst i
    change |bCoord 1 (1/2) x t d - 0| < ε
    rw [sub_zero]
    have h0 (j : Fin 2) : |bCoord 1 (1/2) x 0 j| < ε := by
      change |x 0 j| < ε
      simpa [zeroOne] using hx 0 j
    have h1 (j : Fin 2) : |bCoord 1 (1/2) x 1 j| < ε := by
      fin_cases j
      · change |bCoord 1 (1/2) x (0+1) 0| < ε
        rw [bCoord_succ_zero]
        norm_num [abs_mul]
        have hpos := abs_nonneg (bCoord 1 (1/2) x 0 1)
        linarith [h0 1]
      · change |bCoord 1 (1/2) x (0+1) 1| < ε
        exact h0 0
    exact half_lt (fun t => bCoord 1 (1/2) x t d) (fun t => bCoord_two _ _ t d) ε (h0 d) (h1 d) t
  · intro x _ ε he
    obtain ⟨n0, h0⟩ := half_eventual (fun t => bCoord 1 (1/2) x t 0)
      (fun t => bCoord_two _ _ t 0) ε he
    obtain ⟨n1, h1⟩ := half_eventual (fun t => bCoord 1 (1/2) x t 1)
      (fun t => bCoord_two _ _ t 1) ε he
    refine ⟨max n0 n1, ?_⟩
    intro t ht i d
    have hi : i = 0 := Subsingleton.elim _ _
    subst i
    change |bCoord 1 (1/2) x t d - 0| < ε
    rw [sub_zero]
    fin_cases d
    · exact h0 t ((le_max_left ..).trans ht)
    · exact h1 t ((le_max_right ..).trans ht)

private theorem periodic_not_eventual (f : ℕ → ℚ) (p : ℕ) (hp : 0 < p)
    (period : ∀ t, f (t+p) = f t) (h0 : f 0 = 1) :
    ¬ ∃ n : ℕ, ∀ t ≥ n, |f t| < 1 := by
  have hmul (n : ℕ) : f (p*n) = 1 := by
    induction n with
    | zero => simpa using h0
    | succ n ih => rw [Nat.mul_succ, period, ih]
  rintro ⟨n, hn⟩
  have hle : n ≤ p*n := by simpa using Nat.mul_le_mul_right n (show 1 ≤ p by omega)
  have hbad := hn (p*n) hle
  norm_num [hmul] at hbad

private theorem bNotStable (k0 k1 : ℚ) (x : Fin 1 → Fin 2 → ℚ)
    (hn : ¬ ∃ n : ℕ, ∀ t ≥ n, |bCoord k0 k1 x t 0| < 1) :
    ¬ AsymptoticStable (modelB k0 k1) (fun _ => True) zeroOne := by
  intro h
  apply hn
  obtain ⟨n, ht⟩ := h.2.2.2 x trivial 1 (by norm_num)
  refine ⟨n, fun t hnt => ?_⟩
  simpa [bCoord, zeroOne] using ht t hnt 0 0

/-- 将价格从 1 起步的周期轨道初态 (1,-1)。 -/
def oneOsc : Fin 1 → Fin 2 → ℚ := fun _ => vec 1 (-1)

private theorem modelB_period_four (t : ℕ) (j : Fin 2) :
    bCoord 1 1 oneOsc (t+4) j = bCoord 1 1 oneOsc t j := by
  rw [show t+4 = t+2+2 by omega, bCoord_two, bCoord_two]
  ring

private theorem modelB_alternating (t : ℕ) (j : Fin 2) :
    bCoord (5/2) (1/2) oneOsc (t+1) j = -bCoord (5/2) (1/2) oneOsc t j := by
  induction t generalizing j with
  | zero =>
    fin_cases j <;>
      norm_num [bCoord, modelB, bOrbit, oneOsc, vec]
  | succ t ih =>
    fin_cases j
    · change bCoord (5/2) (1/2) oneOsc (t+1+1) 0 = -bCoord (5/2) (1/2) oneOsc (t+1) 0
      conv_rhs => rw [bCoord_succ_zero]
      rw [bCoord_succ_zero, ih 0, ih 1]
      ring
    · change bCoord (5/2) (1/2) oneOsc (t+1+1) 1 = -bCoord (5/2) (1/2) oneOsc (t+1) 1
      conv_rhs => rw [bCoord_succ_one]
      rw [bCoord_succ_one, ih 0]

/-- 旧版两组标量状态的直接编码。 -/
def twoScalar (a b : ℚ) (i : Nat) : ℚ := if i = 0 then a else b

private theorem noPreviousWithCurrentPrice (m : Opus.ChanDyn.AsyncAgentSystem ℚ)
    (n : m.nGroups = 2) (w1 : m.weight 1 = 0) :
    ¬ (∀ a b, m.step 0 (twoScalar a b) 0 = -(1/2) * b) := by
  intro h
  have same : m.step 0 (twoScalar 0 0) 0 = m.step 0 (twoScalar 0 1) 0 := by
    simp [Opus.ChanDyn.AsyncAgentSystem.step, Opus.ChanDyn.AsyncAgentSystem.price,
      n, w1, twoScalar, List.range_succ]
  rw [h, h] at same
  norm_num at same

/-- 甲方抵消轨道：两组分别加一、减一；合成价恒为零。 -/
def cancelO : Opus.ChanDyn.AsyncAgentSystem ℚ :=
  ⟨2, fun _ => 1, fun i x _ => if i = 0 then x+1 else x-1, fun _ _ => true⟩

/-- 乙方同一规则的两组一维系统。 -/
def cancelA : Astra.ChanDyn.AsyncAgentSystem 2 1 where
  active _ _ := true
  seen t _ := t
  causal _ _ := le_rfl
  contribute _ v := v
  respond i x _ d := if i = 0 then x d + 1 else x d - 1
  orbit x t i d := if i = 0 then x i d + (t : ℚ) else x i d - (t : ℚ)
  initial x := by funext i d; split <;> simp
  update x t i := by
    funext d
    by_cases h : i = 0 <;> simp [h, Nat.cast_add] <;> ring

private theorem cancelO_coords (t : Nat) :
    cancelO.run (fun _ => 0) t 0 = (t : ℚ) ∧ cancelO.run (fun _ => 0) t 1 = -(t : ℚ) := by
  induction t with
  | zero => exact ⟨rfl, rfl⟩
  | succ t ih =>
    simp only [Opus.ChanDyn.AsyncAgentSystem.run, Opus.ChanDyn.AsyncAgentSystem.step, cancelO,
      Nat.cast_succ]
    change (cancelO.run (fun _ => 0) t 0 + 1 = (t : ℚ) + 1) ∧
      (cancelO.run (fun _ => 0) t 1 - 1 = -((t : ℚ) + 1))
    rw [ih.1, ih.2]
    constructor <;> ring

/-- W34、W35：带上一拍状态的二阶稳定域、两个周期边界及个体状态发散的价格抵消。 -/
theorem sep_modelB_async_stability :
    AsymptoticStable (modelB 1 (1/2)) (fun _ => True) zeroOne ∧
    (∀ t j, bCoord 1 1 oneOsc (t+4) j = bCoord 1 1 oneOsc t j) ∧
    ¬ AsymptoticStable (modelB 1 1) (fun _ => True) zeroOne ∧
    (∀ t j, bCoord (5/2) (1/2) oneOsc (t+1) j = -bCoord (5/2) (1/2) oneOsc t j) ∧
    ¬ AsymptoticStable (modelB (5/2) (1/2)) (fun _ => True) zeroOne ∧
    (∀ m : Opus.ChanDyn.AsyncAgentSystem ℚ, m.nGroups = 2 → m.weight 1 = 0 →
      ¬ (∀ a b, m.step 0 (twoScalar a b) 0 = -(1/2) * b)) ∧
    (∀ t, cancelO.run (fun _ => 0) t 0 = (t : ℚ) ∧ cancelO.run (fun _ => 0) t 1 = -(t : ℚ)) ∧
    Opus.ChanDyn.AsymptoticStable cancelO (fun _ => 0) 0 ∧
    ¬ AsymptoticStable cancelA (fun _ => True) (fun _ _ => 0) := by
  refine ⟨modelB_half_stable, modelB_period_four, ?_, modelB_alternating, ?_,
    noPreviousWithCurrentPrice, cancelO_coords, ?_, ?_⟩
  · exact bNotStable 1 1 oneOsc (periodic_not_eventual (fun t => bCoord 1 1 oneOsc t 0) 4
      (by decide) (fun t => modelB_period_four t 0) rfl)
  · apply bNotStable (5/2) (1/2) oneOsc
    apply periodic_not_eventual _ 2 (by decide) _ rfl
    intro t
    rw [show t+2 = t+1+1 by omega, modelB_alternating, modelB_alternating, neg_neg]
  · intro ε he
    refine ⟨0,fun t _ => ?_⟩
    obtain ⟨hp,hq⟩ := cancelO_coords t
    unfold Opus.ChanDyn.AsyncAgentSystem.price
    change |1 * cancelO.run (fun _ => 0) t 0 + (1 * cancelO.run (fun _ => 0) t 1 + 0) - 0| ≤ ε
    rw [hp,hq]
    simpa using he.le
  · intro h
    obtain ⟨n, hn⟩ := h.2.2.2 (fun _ _ => 0) trivial 1 (by norm_num)
    have ht := hn (n+1) (by omega) 0 0
    have nonneg : (0 : ℚ) ≤ (n : ℚ) := by positivity
    simp [cancelA, Nat.cast_add, abs_of_nonneg (by linarith : 0 ≤ (n : ℚ) + 1)] at ht
    linarith

end ModelB

end Chan.Audit.Separation.Fm10e
