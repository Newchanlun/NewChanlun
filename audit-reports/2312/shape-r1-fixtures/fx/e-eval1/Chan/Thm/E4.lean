module

public section

/-- 探针 E4：核心战术新式配置项的取值在精化期求值（纯代码标记）。 -/
theorem e4 : (1 : Nat) + 0 = 1 := by
  simp (maxSteps := (dbgTrace "FM-E4-MARK" fun _ => 1000))
