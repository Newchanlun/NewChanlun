module

public import Mathlib.Data.Rat.Cast.Order
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic

@[expose] public section

namespace Chan.Proxy

/-- 在编号 `s,…,e` 的等时长柱上以短均线减长均线，按每根一单位时间累加。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maSignedArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => fast (s + i) - slow (s + i)

/-- 短均线在长均线上方时，两线之间的面积。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maPosArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  (Finset.range (e + 1 - s)).sum fun i => max (fast (s + i) - slow (s + i)) 0

/-- 短均线在长均线下方时，两线之间的面积，取非负值。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maNegArea (fast slow : ℕ → ℚ) (s e : ℕ) : ℚ :=
  maPosArea slow fast s e

/-- #2322 U-1 暂取非空窗口的趋势平均力度：两均线间的无向面积除以时长。
窗口包含首尾两根单位时间柱，因此总时长为 `e + 1 - s`。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maAvgForce (fast slow : ℕ → ℚ) (s e : ℕ) (_ : s ≤ e) : ℚ :=
  (maPosArea fast slow s e + maNegArea fast slow s e) / ((e + 1 - s : ℕ) : ℚ)

/-- 同一非空窗口的带号口径：短长均线差可互相抵消。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maSignedAvgForce (fast slow : ℕ → ℚ) (s e : ℕ) (_ : s ≤ e) : ℚ :=
  maSignedArea fast slow s e / ((e + 1 - s : ℕ) : ℚ)

end Chan.Proxy
