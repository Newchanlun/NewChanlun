module

public section

theorem m5 (P : Nat → Prop) (h : ∀ p : Nat × Nat, P p.1) (k : Nat) : P k := h (k, 0)
