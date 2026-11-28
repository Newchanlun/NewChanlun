module

public import Mathlib.Algebra.Order.Field.Rat
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic

/-!
# M16a 精确核代理层：指数均线与简单均线

本文件属代理层 `Chan/Proxy/`，不进入 `Chan/Defs/` 核心依赖。全部读数在 `ℚ` 上精确可计算。
-/

@[expose] public section

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
