module

public import Mathlib.Tactic.Common

public section

/-! 独审 r2 甲-C1／甲-C2 的必绿对照：新式字面量配置项、名字不以 config 结尾的命名参数、
「( 以 config 结尾的名字」后面不是 := 的写法（类型标注、元组），都须过第 5 步并能构建。 -/

theorem cfgSteps (a : Nat) : a + 0 = a := by simp (maxSteps := 1000)
theorem cfgContextual (p : Prop) (h : p) : p := by simp +contextual [h]
theorem cfgKernel : 2 < 3 := by decide +kernel
def runCfg (cfg n : Nat) : Nat := cfg + n
theorem runCfgNamed : runCfg (cfg := 1) 2 = runCfg 1 2 := rfl
def ascribe (my_config : Nat) : Nat := (my_config : Nat)
def pairUp (config : Nat) : Nat × Nat := (config, config)
