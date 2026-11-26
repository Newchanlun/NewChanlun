module

public import Mathlib.Tactic.Common

public section

theorem t : True := show True from by aesop (config := {})
