module

public import Chan.Defs.Order.Bar
public import Mathlib.Algebra.Order.Field.Rat
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
public import Mathlib.Data.Fintype.Fin

@[expose] public section

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
