module

import Mathlib.Tactic.Common

public section

/-- 探针 E3：aesop (config := …) 的取值是否在精化期求值（纯代码标记，不碰文件系统）。 -/
theorem e3 : True := by
  aesop (config := { maxRuleApplications := (dbgTrace "FM-E3-MARK" fun _ => 200) })
