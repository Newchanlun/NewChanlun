module

public import Mathlib.Tactic.Common

public section

theorem t (a : Nat) : a = a := by
  grind =>
    set_config (config := {}) in
    done
