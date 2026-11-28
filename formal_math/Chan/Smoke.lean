module

import Mathlib.Algebra.BigOperators.Group.Finset.Defs
import Mathlib.Algebra.Order.Ring.Defs
import Mathlib.Order.Filter.AtTopBot.Defs
import Mathlib.Order.Filter.EventuallyConst
import Mathlib.Order.Interval.Basic
import Mathlib.Order.Interval.Finset.Defs
import Mathlib.Order.OrderDual
import Mathlib.Topology.MetricSpace.PiNat

/-!
# FM-02 冒烟验证

确认工具链与 Mathlib 固定版本可用，不承载任何缠论定义。

* `#check` 段核对总计划拟用的核心符号在本版 Mathlib 中存在，并只经上面八个子模块导入
  （`List.IsPrefix` 与 `WellFounded` 来自 Lean 核心，不需要 Mathlib 导入）。
* `Chan.Smoke` 段用 `decide` 让内核算出一个具体反例：朴素的向下包含合并会让序列最高价
  从结果里消失。这里的 `mergeAllDown` 只是见证用的玩具函数，正式定义由后续票给出。
-/

#check @NonemptyInterval
#check @OrderDual
#check @List.IsPrefix
#check @PiNat.cylinder
#check @PiNat.firstDiff
#check @Filter.atTop
#check @Filter.EventuallyConst
#check @Finset.sum
#check @IsStrictOrderedRing
#check @LocallyFiniteOrder
#check @WellFounded

@[expose] public section

namespace Chan.Smoke

/-- K 线，记作 `(低, 高)`。 -/
abbrev Bar := Nat × Nat

/-- 两根 K 线有包含关系：一方的区间盖住另一方。 -/
def nested (a b : Bar) : Bool :=
  (a.1 ≤ b.1 && b.2 ≤ a.2) || (b.1 ≤ a.1 && a.2 ≤ b.2)

/-- 向下合并：低点取低、高点也取低。 -/
def mergeDown (a b : Bar) : Bar :=
  (min a.1 b.1, min a.2 b.2)

/-- 把新 K 线并入已处理序列；`acc` 逆序存放，表头是最近一根。 -/
def push (acc : List Bar) (k : Bar) : List Bar :=
  match acc with
  | [] => [k]
  | last :: rest => if nested last k then mergeDown last k :: rest else k :: last :: rest

/-- 从左到右对整段 K 线做向下包含合并。 -/
def mergeAllDown (ks : List Bar) : List Bar :=
  (ks.foldl push []).reverse

/-- 四根 K 线：第三根 `[7, 20]` 包含第二根 `[8, 11]`，且带着全段最高价 20。 -/
def sample : List Bar :=
  [(10, 12), (8, 11), (7, 20), (5, 9)]

theorem mergeAllDown_sample : mergeAllDown sample = [(10, 12), (7, 11), (5, 9)] := by
  decide

/-- 最高价 20 在输入的高点里，却不在合并结果的高点里。 -/
theorem mergeAllDown_sample_drops_high :
    20 ∈ sample.map Prod.snd ∧ 20 ∉ (mergeAllDown sample).map Prod.snd := by
  decide

end Chan.Smoke
