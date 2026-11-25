module

public section

theorem vac : ∀ x : Nat, x < 0 → x = 5 := by
  intro x h
  exact absurd h (Nat.not_lt_zero x)

theorem mirror : ∀ x : Nat, x = 0 → x = 0 := fun _ h => h

theorem redundant : ∀ x : Nat, x = 0 → x + 0 = x := fun _ _ => rfl
