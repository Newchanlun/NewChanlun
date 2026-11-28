module
public section
theorem syllogism (P Q R : Prop) (h1 : P → Q) (h2 : Q → R) (hp : P) : R :=
  h2 (h1 hp)

theorem lt_chain (Q : Nat → Prop) (h : ∀ n : Nat, 5 < n → Q n) (k : Nat) (h10 : 10 < k) : Q k :=
  h k (Nat.lt_trans (by decide : 5 < 10) h10)

theorem succ_step (Q : Nat → Prop) (h : ∀ n : Nat, 0 < n → Q n) (k : Nat) : Q (k + 1) :=
  h (k + 1) (Nat.succ_pos k)
