module

public import Mathlib.Algebra.Order.Field.Rat
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic

/-!
# M16a 精确核代理层：均线面积

两条均线序列之差在闭窗口 `[s, e]` 上的离散面积，及 `015:42` 的趋势平均力度。
只保留精确面积恒等式的代理读数，不含主观均线操作规则（B-25）。
-/

@[expose] public section

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
