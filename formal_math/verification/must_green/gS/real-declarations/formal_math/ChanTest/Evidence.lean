module

public import Chan.Exec.Shape

public section

theorem Pos.mk.witness : ∃ n : Nat, 0 < n := ⟨1, by decide⟩
theorem Pos.pos.witness : ∃ n : Nat, Pos n := ⟨1, ⟨by decide⟩⟩
theorem posOne.witness : True := trivial
theorem instPosOfNatNat.witness : True := trivial
theorem recThm.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem fromWhere.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem mutualA.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem mutualB.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem fromLetRec.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».hidden.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».privateWhere.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».privateWhere.helper.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».fromWhere.helper.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».fromLetRec.helper.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».fromPrivateLetRec.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem _private.Chan.Exec.Shape.«0».fromPrivateLetRec.helper.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
