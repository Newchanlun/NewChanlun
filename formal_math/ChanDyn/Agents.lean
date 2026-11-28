module

public import Mathlib.Algebra.Order.Field.Basic

/-!
# M19b D4 多参与者异步响应模型类（独立研究库）

多组参与者状态按权重叠加为价格；每时刻只有被激活的组响应。
有限期限可达 `FiniteHorizonReach` 与无限时间渐近稳定 `AsymptoticStable` 显式分立。
-/

@[expose] public section

namespace ChanDyn

/-- D4 异步多参与者系统：组数、各组权重、响应函数（旧状态与当下价格到新状态）与激活表。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
structure AsyncAgentSystem (R : Type*) where
  /-- 组数。 -/
  nGroups : ℕ
  /-- 各组权重。 -/
  weight : ℕ → R
  /-- 响应函数：组号、旧状态、当下价格到新状态。 -/
  respond : ℕ → R → R → R
  /-- 激活表：时刻与组号到是否响应。 -/
  active : ℕ → ℕ → Bool

variable {R : Type*} [Field R] [LinearOrder R] [IsStrictOrderedRing R]

/-- 向量叠加价格：各组状态加权和。

[033:24]「把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。」 -/
def AsyncAgentSystem.price (S : AsyncAgentSystem R) (st : ℕ → R) : R :=
  ((List.range S.nGroups).map fun i => S.weight i * st i).sum

/-- 异步一步：被激活的组按当下价格响应，其余组保持。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def AsyncAgentSystem.step (S : AsyncAgentSystem R) (t : ℕ) (st : ℕ → R) : ℕ → R :=
  fun i => if S.active t i then S.respond i (st i) (S.price st) else st i

/-- 自初始状态起的递推轨道。

[030:16]「而本ID的理论，当然也是以这交易时间的不可逆为前提，如果今天的交易可以变成昨天的或者干脆不算了，那本ID的理论马上土崩瓦解。」 -/
def AsyncAgentSystem.run (S : AsyncAgentSystem R) (st0 : ℕ → R) : ℕ → ℕ → R
  | 0 => st0
  | t + 1 => S.step t (S.run st0 t)

/-- 有限期限可达：`H` 步内价格进入目标的 `ε` 邻域。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
def FiniteHorizonReach (S : AsyncAgentSystem R) (st0 : ℕ → R) (target ε : R) (H : ℕ) : Prop :=
  ∃ t, t ≤ H ∧ abs (S.price (S.run st0 t) - target) ≤ ε

/-- 无限时间渐近稳定：对任意正 `ε`，某时刻之后价格永远留在目标的 `ε` 邻域内。

[030:18]「交易，当然是有规律的，而且这规律是万古不变的，归纳上述就是：交易以时间的不可逆为前提完全等价地反映在价格轨迹上。」 -/
def AsymptoticStable (S : AsyncAgentSystem R) (st0 : ℕ → R) (target : R) : Prop :=
  ∀ ε : R, 0 < ε → ∃ T, ∀ t, T ≤ t → abs (S.price (S.run st0 t) - target) ≤ ε

/-- 稳定性域：使系统渐近稳定于目标的初始状态全体。

[030:24]「其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。」 -/
def StabilityDomain (S : AsyncAgentSystem R) (target : R) : (ℕ → R) → Prop :=
  fun st0 => AsymptoticStable S st0 target

end ChanDyn
