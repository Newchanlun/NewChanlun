module

public import Chan.Exec.Fixture

public section

theorem le_sumTo.witness : ∃ _n : Nat, True := ⟨0, trivial⟩

theorem Pos.mk.witness : ∃ n : Nat, 0 < n := ⟨1, by decide⟩
theorem Pos.pos.witness : ∃ n : Nat, Pos n := ⟨1, ⟨by decide⟩⟩
