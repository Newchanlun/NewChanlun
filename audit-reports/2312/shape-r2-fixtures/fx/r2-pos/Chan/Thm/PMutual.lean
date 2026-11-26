module

public import Mathlib.Tactic.Common

public section

mutual
theorem t1 : True := by aesop (config := {})
theorem t2 : True := trivial
end
