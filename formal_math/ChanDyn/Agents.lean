module

public import Mathlib.Algebra.Order.Field.Rat
public import Mathlib.Algebra.BigOperators.Group.Finset.Basic
public import Mathlib.Data.Fintype.Fin

@[expose] public section

namespace ChanDyn

/-- D4 每组持有一个有理向量。被调度的组用自己的当前状态和所见时刻的
叠加向量更新，其余组保持原值；所见时刻不超过当下。轨道以初态为参数，
使改变初态后的稳定性可以在同一套响应规则下检验。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。
[033:24] 把这种看法推广到所有的走势中，那么任何的走势图，其实就是一些级别大小不同的中枢，把这些看成不同的星球，在当下位置上的星球对当下位置产生向上的力，当下位置下的产生向下的力，而这些所有力的合力构成一个总的力量，而市场当下的力，也就是当下买卖产生的力，买的是向上的力，卖的是向下的力，这也构成一个合力，前一个合力是市场已有走势构成的一个当下的力，后者是当下的交易产生的力，而研究这两种力之间的关系，就构成了市场研究的另一个角度，也就是另一种释义的过程。 -/
structure AsyncAgentSystem (groups dim : ℕ) where
  active : ℕ → Fin groups → Bool
  seen : ℕ → Fin groups → ℕ
  causal : ∀ t i, seen t i ≤ t
  contribute : Fin groups → (Fin dim → ℚ) → Fin dim → ℚ
  respond : Fin groups → (Fin dim → ℚ) → (Fin dim → ℚ) → Fin dim → ℚ
  orbit : (Fin groups → Fin dim → ℚ) → ℕ → Fin groups → Fin dim → ℚ
  initial : ∀ x, orbit x 0 = x
  update : ∀ x t i, orbit x (t + 1) i =
    if active t i then
      respond i (orbit x t i) (fun d =>
        Finset.univ.sum (fun j => contribute j (orbit x (seen t i) j) d))
    else orbit x t i

/-- 指定域内的渐近稳定：平衡态保持不变，任意小扰动的轨道始终邻近它，
且域内各初态的轨道最终留在每个正半径邻域内。进入邻域的时刻可随半径
和初态改变，不要求在某个统一期限达到平衡态。
[030:24] 其次，社会结构的现实多层性以及个体的差异性决定了，任何的群体性交易都不具有同时性，也就是说，即使是相同原因造成的相同买卖，都不可能同时出现，必然有先后，也就是说，交易具有延异性，不会完全地趋同，这是交易能形成可分析走势的现实基础。 -/
def AsymptoticStable {groups dim : ℕ} (m : AsyncAgentSystem groups dim)
    (domain : (Fin groups → Fin dim → ℚ) → Prop) (eq : Fin groups → Fin dim → ℚ) : Prop :=
  let near := fun (x : Fin groups → Fin dim → ℚ) (r : ℚ) => ∀ i d, |x i d - eq i d| < r
  domain eq ∧ (∀ t, m.orbit eq t = eq) ∧
    (∀ ε : ℚ, 0 < ε → ∃ δ : ℚ, 0 < δ ∧
      ∀ x, domain x → near x δ → ∀ t, near (m.orbit x t) ε) ∧
    (∀ x, domain x → ∀ ε : ℚ, 0 < ε → ∃ n : ℕ, ∀ t ≥ n, near (m.orbit x t) ε)

end ChanDyn
