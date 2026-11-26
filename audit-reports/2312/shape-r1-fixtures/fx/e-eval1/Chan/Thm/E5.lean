module

import Mathlib.Tactic.Common

public section

/-- 探针 E5：plausible (config := …)（旧式 config 语法种类，形状门声称判红）。 -/
theorem e5 (n : Nat) : n = n := by
  plausible (config := { numInst := (dbgTrace "FM-E5-MARK" fun _ => 3) })
