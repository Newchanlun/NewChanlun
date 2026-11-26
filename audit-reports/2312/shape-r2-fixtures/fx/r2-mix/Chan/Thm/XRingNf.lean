module

public import Mathlib.Tactic.Ring.RingNF

public section

theorem t (a : Nat) : a + 0 = a := by
  ring_nf (config := {})
