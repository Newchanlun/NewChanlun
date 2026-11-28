module

public import Mathlib.Data.Rat.Cast.Order
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Tactic.NormNum

@[expose] public section

namespace Chan.Proxy

/-- 三种播种分别以首价、时刻零的均线，或吸收首价以前的状态为起点。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
inductive EmaSeed where
  | firstValue
  | atZero (v : ℚ)
  | priorState (pre : ℚ)
  deriving DecidableEq

/-- 用有理平滑系数和播种方式指定 EMA。标准周期 `N` 对应 `alpha = 2/(N+1)`。
平滑系数属于 `(0,1]`；出厂周期由正自然数给出。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
structure EmaParams where
  alpha : ℚ
  alpha_pos : 0 < alpha
  alpha_le_one : alpha ≤ 1
  seed : EmaSeed
  deriving DecidableEq

/-- 用正周期构造指数均线参数；播种方式仍由调用者给出。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def EmaParams.ofPeriod (period : ℕ+) (seed : EmaSeed) : EmaParams := by
  have hn : (1 : ℚ) ≤ (period.val : ℚ) := by exact_mod_cast period.pos
  have hd : (2 : ℚ) ≤ (period.val : ℚ) + 1 := by
    simpa only [one_add_one_eq_two] using add_le_add_left hn (1 : ℚ)
  have hp : (0 : ℚ) < (period.val : ℚ) + 1 := lt_of_lt_of_le (by norm_num) hd
  exact ⟨2 / ((period.val : ℚ) + 1), div_pos (by norm_num) hp,
    (div_le_iff₀ hp).2 (by simpa using hd), seed⟩

/-- 首值播种和显式零时刻播种直接设值；前态播种先吸收时刻零的样本。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def EmaParams.init (p : EmaParams) (x0 : ℚ) : ℚ :=
  match p.seed with
  | .firstValue => x0
  | .atZero v => v
  | .priorState pre => (1 - p.alpha) * pre + p.alpha * x0

/-- 从零时刻向前递推，每一步只使用上一步均线和本步价格。
[050:18] 「必须明白一个道理，就是MACD的计算方法决定了，1分钟和30分钟MACD之间并没有实质的区别，只是计算的周期不同而已，而相应的计算是线性的，只是稍微灵敏与迟钝的区别，没有太大的区别。」 -/
def emaSeq (p : EmaParams) (price : ℕ → ℚ) : ℕ → ℚ
  | 0 => p.init (price 0)
  | t + 1 => (1 - p.alpha) * emaSeq p price t + p.alpha * price (t + 1)

/-- 取截至 `t` 最近至多 `period` 根的算术平均；起始未满窗口时，以实有根数为分母。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def smaSeq (period : ℕ+) (price : ℕ → ℚ) (t : ℕ) : ℚ :=
  let count := min period.val (t + 1)
  (Finset.range count).sum (fun i => price (t - i)) / (count : ℚ)

/-- 标准周期的精确衰减因子；先转有理数再作减法和除法。
[025:16] 「MACD的灵敏度，和参数有关，一般都取用12、26、9为参数，这对付一般的走势就可以了，但一个太快速的走势，1分钟图的反应也太慢了」 -/
def emaDecay (period : ℕ+) : ℚ :=
  let n : ℚ := period.val
  (n - 1) / (n + 1)

/-- 最近 `n ≥ 9` 根落在宽度 `R` 的闭价带内；末端为 `oldCount + n - 1`。
此处只给标准 DIF 的窗口数据，DEA 须另取二次卷积核。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
structure ZeroAxisBoundData where
  price : ℕ → ℚ
  oldCount : ℕ
  n : ℕ
  nine_le : 9 ≤ n
  lower : ℚ
  R : ℚ
  width_nonneg : 0 ≤ R
  recent_mem : ∀ i < n, lower ≤ price (oldCount + i) ∧ price (oldCount + i) ≤ lower + R

/-- 标准快线的精确衰减因子。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.q12 : ℚ := 11 / 13

/-- 标准慢线的精确衰减因子。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.q26 : ℚ := 25 / 27

/-- DIF 价格核的正部总质量，由首九项给出。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.coefA : ℚ := q26 ^ 9 - q12 ^ 9

/-- 旧价距新价带的紧界；带内距离为零，无旧价时亦取零。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.delta (d : ZeroAxisBoundData) : ℚ :=
  (List.range d.oldCount).foldl (fun acc t =>
    max acc (max (d.lower - d.price t) (d.price t - (d.lower + d.R)))) 0

/-- 外给带距需覆盖所有旧价以及显式播种状态。若从时刻零的均线值播种，
零时刻不得计入最近 `n` 次更新；否则尾核少衰减一步。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
abbrev ZeroAxisBoundData.SeedWithinDelta (d : ZeroAxisBoundData) (seed : EmaSeed) (δ : ℚ) : Prop :=
  let within (x : ℚ) := d.lower - δ ≤ x ∧ x ≤ d.lower + d.R + δ
  0 ≤ δ ∧ (∀ i : Fin d.oldCount, within (d.price i.val)) ∧
    match seed with
    | .firstValue => True
    | .atZero v => 0 < d.oldCount ∧ within v
    | .priorState pre => within pre

/-- DIF 界的右端：精确正核质量乘价宽，再加旧价和共享播种状态的尾核项。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.bound (d : ZeroAxisBoundData) (δ : ℚ) : ℚ :=
  coefA * d.R + (q26 ^ d.n - q12 ^ d.n) * δ

/-- 快慢线共享同一个播种状态时的 DIF。两线初值独立时不能直接套用同一尾核系数。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
def ZeroAxisBoundData.dif (d : ZeroAxisBoundData) (seed : EmaSeed) : ℚ :=
  let t := d.oldCount + d.n - 1
  let fast := emaSeq ⟨1 - q12, by norm_num [q12], by norm_num [q12], seed⟩ d.price t
  let slow := emaSeq ⟨1 - q26, by norm_num [q26], by norm_num [q26], seed⟩ d.price t
  fast - slow

/-- 以外部给出的带距（含旧价和共享显式初值）检验标准 DIF 界。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
abbrev ZeroAxisBoundData.difWithinSeedBound (d : ZeroAxisBoundData) (seed : EmaSeed)
    (δ : ℚ) : Prop :=
  d.SeedWithinDelta seed δ ∧ |d.dif seed| ≤ d.bound δ

/-- 首值播种时，直接用自动计算的最紧旧价带距检验标准 DIF 界。
[024:24] 「归纳上述，用MACD 判断背驰的前提是，A、B、C 段在一个大的趋势里，其中A 之前已经有一个中枢，而B 是这个大趋势的另一个中枢，这个中枢一般会把MACD 的黄白线（也就是DIFF 和DEA）回拉到0 轴附近。」 -/
abbrev ZeroAxisBoundData.difWithinBound (d : ZeroAxisBoundData) : Prop :=
  |d.dif .firstValue| ≤ d.bound d.delta

end Chan.Proxy
