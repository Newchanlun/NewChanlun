module

public import Mathlib.Order.Interval.Basic
public import Mathlib.Order.OrderDual

/-!
# M0 区间与 K 线序

K 线只保留高低点，建模为任意线性序上的非空闭区间。取整不是隐藏容差，而是调用方显式作用的
单调预处理映射（清单 B-8）。
-/

@[expose] public section

namespace Chan.Defs.Order

universe u v

/-- K 线（仅高低点）：线性序上的非空闭区间 `[lo, hi]`，携带不变式 `lo ≤ hi`。
最底层的单位 K 线即递归基底的输入。

[017:40]
> 对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
structure Bar (P : Type u) [LinearOrder P] where
  /-- 低点。 -/
  lo : P
  /-- 高点。 -/
  hi : P
  /-- 低点不超过高点。 -/
  valid : lo ≤ hi

/-- 显式单调预处理映射：从价格线性序 `P` 到目标价格线性序 `Q` 的保序函数（清单 B-8），
不内嵌任何容差，由调用方显式作用在 K 线或段序列上。

[017:40]
> 在实际之中，对最后不能分解的级别，其缠中说禅走势中枢就不能用“至少三个连续次级别走势类型所重叠”定义，而定义为至少三个该级别单位K线重叠部分。
-/
structure Quantizer (P : Type u) (Q : Type v) [LinearOrder P] [LinearOrder Q] where
  /-- 底层映射。 -/
  toFun : P → Q
  /-- 单调（保序，不要求严格）。 -/
  mono : ∀ x y, x ≤ y → toFun x ≤ toFun y

/-- 将预处理映射逐端点提升到 K 线；单调性保证结果仍是合法闭区间。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
def Quantizer.mapBar {P : Type u} {Q : Type v} [LinearOrder P] [LinearOrder Q]
    (q : Quantizer P Q) (b : Bar P) : Bar Q :=
  ⟨q.toFun b.lo, q.toFun b.hi, q.mono b.lo b.hi b.valid⟩

variable {P : Type u} [LinearOrder P]

/-- 闭区间包含：`a` 包含 `b` 当且仅当 `a.lo ≤ b.lo` 且 `b.hi ≤ a.hi`（任一端相等均算包含）。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
def Bar.contains (a b : Bar P) : Prop := a.lo ≤ b.lo ∧ b.hi ≤ a.hi

/-- `Bar.contains` 可判定。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
instance Bar.instDecidableContains (a b : Bar P) : Decidable (a.contains b) := by
  unfold Bar.contains; infer_instance

/-- 严格上升：`b` 的高点严格大于 `a` 的高点，且 `b` 的低点严格大于 `a` 的低点。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
def Bar.strictUp (a b : Bar P) : Prop := a.hi < b.hi ∧ a.lo < b.lo

/-- `Bar.strictUp` 可判定。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
instance Bar.instDecidableStrictUp (a b : Bar P) : Decidable (a.strictUp b) := by
  unfold Bar.strictUp; infer_instance

/-- 严格下降：`b` 的高点严格小于 `a` 的高点，且 `b` 的低点严格小于 `a` 的低点。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
def Bar.strictDown (a b : Bar P) : Prop := b.hi < a.hi ∧ b.lo < a.lo

/-- `Bar.strictDown` 可判定。

[017:40]
> 而定义为至少三个该级别单位K线重叠部分。
-/
instance Bar.instDecidableStrictDown (a b : Bar P) : Decidable (a.strictDown b) := by
  unfold Bar.strictDown; infer_instance

end Chan.Defs.Order
