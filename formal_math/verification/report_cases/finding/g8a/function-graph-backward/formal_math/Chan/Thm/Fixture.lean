module

public import Mathlib.Basic.ExistsUnique

public section

theorem main_step_unique (step : Nat → Nat) (x : Nat) :
    ExistsUnique (fun y => y = step x) :=
  ⟨step x, rfl, fun _ h => h⟩
