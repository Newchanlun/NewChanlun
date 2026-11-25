module

public import Mathlib.Basic.ExistsUnique

public section

theorem eu_pair (f : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => (y, ()) = (f x, ())) :=
  ⟨f x, rfl, fun _ h => congrArg Prod.fst h⟩
