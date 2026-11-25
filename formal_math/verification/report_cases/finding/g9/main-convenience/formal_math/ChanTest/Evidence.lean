module

public section

theorem claim.witness : ∃ x y : Nat, x = 0 ∧ y = 0 := ⟨0, 0, rfl, rfl⟩

theorem claim.without_1 : ∃ x y : Nat, y = 0 ∧ ¬ x + y = 0 := ⟨1, 0, rfl, by decide⟩

theorem claim.without_2 : ∃ x y : Nat, x = 0 ∧ ¬ x + y = 0 := ⟨0, 1, rfl, by decide⟩

theorem _private.Chan.Thm.Fixture.«0».privateClaim.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
