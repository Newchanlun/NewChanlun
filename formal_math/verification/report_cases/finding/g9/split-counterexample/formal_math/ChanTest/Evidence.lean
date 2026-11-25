module

public section

theorem claim.witness : ∃ x y : Nat, x = 0 ∧ y = 0 := ⟨0, 0, rfl, rfl⟩

theorem claim.without_1 : ∃ x y : Nat, ¬ x + y = 0 := ⟨1, 0, by decide⟩

theorem claim.without_2 : ∃ x y : Nat, x = 0 ∧ ¬ x + y = 0 := ⟨0, 1, rfl, by decide⟩
