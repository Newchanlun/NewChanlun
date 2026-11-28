module

public import ChanDyn.Well

/-!
# M19b D2 推力预算模型类（独立研究库）

在 D1 上加外加推力序列与临界阈值；`BudgetBound` 为比较式预算上界假设，
`ReturnUnderBudgetStmt` 是各假设与背驰式预算前提逐个为前件的条件陈述（不断言成立）。
-/

@[expose] public section

namespace ChanDyn

/-- D2 推力模型：势阱、外加推力序列与临界阈值参数位。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
structure ThrustModel (R : Type*) [LinearOrder R] extends WellModel R where
  /-- 外加推力序列。 -/
  thrust : ℕ → R
  /-- 临界阈值。 -/
  critical : R

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 轨迹在自身推力下服从势阱递推。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ThrustModel.Evolves (M : ThrustModel R) (x : ℕ → R) : Prop :=
  M.toWellModel.Evolves x M.thrust

/-- 时刻区间 `[s, e)` 的已显示推力预算（推力绝对值之和）。

[033:26]「对a+A+b+B+c，背驰的大概意思就是c段的力度比b的小了。」 -/
def ThrustModel.budget (M : ThrustModel R) (s e : ℕ) : R :=
  ((List.range (e - s)).map fun i => abs (M.thrust (s + i))).sum

/-- 比较式预算上界假设：`c` 窗口预算不超过 `b` 窗口预算，且后者不超过临界阈值。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def BudgetBound (M : ThrustModel R) (bS bE cS cE : ℕ) : Prop :=
  M.budget cS cE ≤ M.budget bS bE ∧ M.budget bS bE ≤ M.critical

/-- 目标状态：自 `t0` 起 `H` 步内回到中枢区间。

[033:26]「所谓顶背驰，就是最后这个中枢，向上离开比向下离开要弱，而中枢有这样的特性，就是对无论向上或向下离开的，都有相同的回拉作用，既然向上离开比向下离开要弱，而向下离开都能拉回中枢，那向上的离开当然也能拉回中枢里，对于b+B+c向上的走势，这就构成顶背驰，而对于b+B+c向下的走势，就构成底背驰。」 -/
def BoundedReturn (M : ThrustModel R) (x : ℕ → R) (t0 H : ℕ) : Prop :=
  ∃ t, t0 ≤ t ∧ t ≤ t0 + H ∧ M.zd ≤ x t ∧ x t ≤ M.zg

/-- 条件陈述：各势阱假设、自静止落入、预算比较前提与递推各为独立前件，结论为有限期限回到中枢。

[033:30]「那么，这个反转是否成功，不妨把这个后续的反转写成c，那么也只要比较一下a+A+b与c这两段的力度就可以，因为中枢B对这两段的回拉力度是一样的，如果c比a+A+b弱，那当然反转不成功，也就意味着一定要重新回到中枢里，在最强的情况下也至少有一次回拉去确认能否构成一个第三类买点。」 -/
def ReturnUnderBudgetStmt (M : ThrustModel R) (x : ℕ → R) (ρ : R) (t0 H bS bE cS cE : ℕ) :
    Prop :=
  WellSymmetric M.toWellModel → WellTimeInvariant M.toWellModel →
    WellBoundedRange M.toWellModel ρ → WellInward M.toWellModel →
    FallsFromRest M.toWellModel x t0 → BudgetBound M bS bE cS cE → M.Evolves x →
    BoundedReturn M x t0 H

end ChanDyn
