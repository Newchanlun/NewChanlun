module
public import Chan.Hypotheses.Market
public section
theorem use_named_hyp (h : PositivePrices) (k : Nat) : 0 < price k := h k
theorem use_inline_hyp (h : ∀ n : Nat, 0 < price n) (k : Nat) : 0 < price k := h k
theorem concrete_conj : price 0 = 1 ∧ price 1 = 2 := ⟨rfl, rfl⟩
