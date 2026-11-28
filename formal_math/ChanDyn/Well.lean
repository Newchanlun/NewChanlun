module

public import Chan.Defs.Order.Bar
public import Mathlib.Algebra.Order.Field.Rat

@[expose] public section

namespace ChanDyn

/-- D1 单中枢二阶模型。每步在旧位置取力，先更新速度，再以新速度移动；
每个时刻的回复场只读位置，与外力分开。场是否随时间改变由另一项假设检查。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
structure WellModel where
  center : Chan.Defs.Order.Bar ℚ
  position : ℕ → ℚ
  velocity : ℕ → ℚ
  restoring : ℕ → ℚ → ℚ
  externalForce : ℕ → ℚ
  rho : ℚ
  rhoBounds : 0 ≤ rho ∧ rho ≤ 1
  kick : ∀ t, velocity (t + 1) = rho * velocity t + restoring t (position t) + externalForce t
  drift : ∀ t, position (t + 1) = position t + velocity (t + 1)

/-- 在上下边界外相距同一距离的两点，回复力大小相同、符号相反。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def WellSymmetric (m : WellModel) : Prop :=
  ∀ t r, 0 ≤ r → m.restoring t (m.center.lo - r) = -m.restoring t (m.center.hi + r)

/-- 固定位置时，各时刻的回复力都与初始场相同。
[033:30] 「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def WellTimeInvariant (m : WellModel) : Prop :=
  ∀ t x, m.restoring t x = m.restoring 0 x

/-- 半径从两侧边界分别向外量；超出给定半径时场为零。
#2322 U-7：这与同一中枢、同一回复场在固定时刻满足 `PullbackHyp` 互斥，
因为后者在整个核外要求一致正下界；联立作前提会使命题空真。
[033:24] 「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def WellBoundedRange (m : WellModel) (radius : ℚ) : Prop :=
  0 ≤ radius ∧ ∀ t x, x < m.center.lo - radius ∨ m.center.hi + radius < x →
    m.restoring t x = 0

/-- 从起点起的指定步数内，每次速度更新的外力项均为零。
[033:24] 「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
abbrev CoastingZeroThrust (m : WellModel) (start steps : ℕ) : Prop :=
  ∀ k : Fin steps, m.externalForce (start + k.val) = 0

/-- 已观察到的 b 段：从区间外静止出发，第 steps 步首次落入闭区间。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
abbrev FallsFromRest (m : WellModel) (start steps : ℕ) : Prop :=
  0 < steps ∧ m.velocity start = 0 ∧
  (∀ k : Fin steps, m.position (start + k.val) < m.center.lo ∨
    m.center.hi < m.position (start + k.val)) ∧
  m.center.lo ≤ m.position (start + steps) ∧ m.position (start + steps) ≤ m.center.hi

/-- 区间外回复力不朝远离中枢的方向；作为独立前提，不约束模型的构造。
[033:26] 「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def WellInward (center : Chan.Defs.Order.Bar ℚ) (restoring : ℕ → ℚ → ℚ) : Prop :=
  (∀ t x, x < center.lo → 0 ≤ restoring t x) ∧
  (∀ t x, center.hi < x → restoring t x ≤ 0)

end ChanDyn
