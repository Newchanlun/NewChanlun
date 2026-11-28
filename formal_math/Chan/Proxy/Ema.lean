module

public import Mathlib.Data.Rat.Cast.Order
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
import Mathlib.Tactic.NormNum

@[expose] public section

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
