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

/-- 闭窗内短长均线差全非负或全非正；相等也属于同侧。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
abbrev MaSameSide (fast slow : ℕ → ℚ) (s e : ℕ) : Prop :=
  (∀ i : Fin (e + 1 - s), 0 ≤ fast (s + i.val) - slow (s + i.val)) ∨
  (∀ i : Fin (e + 1 - s), fast (s + i.val) - slow (s + i.val) ≤ 0)

/-- #2322 U-1：用两均线间的无向面积除以时长比较强弱。闭窗每柱一单位，
总时长为 `e + 1 - s`，由 `s ≤ e` 保证非空。原文限于相邻两吻之间的 `MaSameSide` 窗；
此时无向版等于带号版的绝对值。跨吻窗上的读数只是代数延拓。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maAvgForce (fast slow : ℕ → ℚ) (s e : ℕ) (_ : s ≤ e) : ℚ :=
  (maPosArea fast slow s e + maNegArea fast slow s e) / ((e + 1 - s : ℕ) : ℚ)

/-- 同一非空同侧窗的带号读数，用于端点差恒等式；比较力度前须按方向取号。
跨吻窗只作代数延拓，短长均线差可能互相抵消。
[015:42] 「称为缠中说禅趋势平均力度：当下与前一“吻”的结束时短线均线与长期均线形成的面积除以时间」 -/
def maSignedAvgForce (fast slow : ℕ → ℚ) (s e : ℕ) (_ : s ≤ e) : ℚ :=
  maSignedArea fast slow s e / ((e + 1 - s : ℕ) : ℚ)

end Chan.Proxy
