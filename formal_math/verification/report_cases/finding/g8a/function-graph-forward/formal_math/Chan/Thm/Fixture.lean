module

public import Mathlib.Basic.ExistsUnique

public section

theorem main_step_unique (step : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => step x = y) :=
  ⟨step x, rfl, fun _ h => h.symm⟩
