module

public section

/-! 探针：新式配置项（键不是 native/config，按设计放行）的取值是否在构建期被求值。 -/

theorem probe (n : Nat) : n + 0 = n := by
  simp (maxSteps := (dbgTrace "FM-NEWCFG-RAN" fun _ => 1000))
