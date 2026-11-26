module

public import Mathlib.Tactic.Common

public section

set_option maxHeartbeats 400000 in
theorem t : True := by aesop (config := {})
