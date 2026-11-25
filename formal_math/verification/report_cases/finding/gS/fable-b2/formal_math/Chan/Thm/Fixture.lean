module

public section

theorem vac : Option.getD (some (∀ x : Nat, x < 0 → x = 5)) True := by
  intro x h
  exact absurd h (Nat.not_lt_zero x)

theorem mirror : Function.const Unit (∀ x : Nat, x = 0 → x = 0) () := fun _ h => h

theorem redundant : True ∧ (∀ x : Nat, x = 0 → x + 0 = x) := ⟨trivial, fun _ _ => rfl⟩
