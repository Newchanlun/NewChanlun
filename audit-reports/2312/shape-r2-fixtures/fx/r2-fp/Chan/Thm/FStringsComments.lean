module

public import Mathlib.Tactic.Common

public section

/-- 文档注释：aesop (config := {}) 与 plausible (config := {}) -/
def s1 : String := "(config := x) aesop (config := {}) (simp_config := {})"

-- 行注释 aesop (config := { maxRuleApplications := 1 })
/- 块注释 (simp_config := {}) /- 嵌套 (config := {}) -/ -/
def s2 (config : Nat) : String := s!"(config := {config})"

def s3 : String := r"simp (config := {})"

/-! 模块注释 (config := 1) -/
def c1 : Char := '('
