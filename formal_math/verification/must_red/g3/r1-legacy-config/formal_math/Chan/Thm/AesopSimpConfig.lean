module

public import Mathlib.Tactic.Common

public section

/-! 独审 r1 甲-1：Aesop 的旧式 `(simp_config := …)` 子句。 -/

theorem probe : True := by
  aesop (simp_config := { zeta := false })
