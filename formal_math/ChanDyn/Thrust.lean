module

public import ChanDyn.Well
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic

@[expose] public section

namespace ChanDyn

/-- D2 固定位置场与逐步外推力分别进入速度更新。推力预算只约束外推力，
不扣除回复力；可以在同一条轨道上单独检验预算和是否回到中枢。
[033:24] 「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
structure ThrustModel where
  center : Chan.Defs.Order.Bar ℚ
  position : ℕ → ℚ
  velocity : ℕ → ℚ
  restoring : ℚ → ℚ
  thrust : ℕ → ℚ
  rho : ℚ
  rhoBounds : 0 ≤ rho ∧ rho ≤ 1
  kick : ∀ t, velocity (t + 1) = rho * velocity t + restoring (position t) + thrust t
  drift : ∀ t, position (t + 1) = position t + velocity (t + 1)

/-- 计算指定步数内已施推力的绝对量之和。总支出不得超过预算，预算不得超过
显式比较临界值；对所有期限施加此式即可约束整个未来的预算。
[033:26] 「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
abbrev BudgetBound (m : ThrustModel) (start steps : ℕ) (budget critical : ℚ) : Prop :=
  (Finset.range steps).sum (fun k => |m.thrust (start + k)|) ≤ budget ∧ budget ≤ critical

/-- 从区间外的出发时刻计，在此后第一步至给定期限之间有一步落入中枢（含边界）。
[033:30] 「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
abbrev BoundedReturn (m : ThrustModel) (start deadline : ℕ) : Prop :=
  (m.position start < m.center.lo ∨ m.center.hi < m.position start) ∧
  ∃ k : Fin deadline, m.center.lo ≤ m.position (start + k.val + 1) ∧
    m.position (start + k.val + 1) ≤ m.center.hi

/-- 待检条件命题：将内向场、推力预算和离带出发分开，检验有限期限内回到闭核。
[033:30] 「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def ReturnUnderBudgetStmt (m : ThrustModel) (start deadline : ℕ) (budget critical : ℚ) : Prop :=
  WellInward m.center (fun _ => m.restoring) →
  BudgetBound m start deadline budget critical →
  (m.position start < m.center.lo ∨ m.center.hi < m.position start) →
  BoundedReturn m start deadline

end ChanDyn
