module

public section

/-! 自动参数的各个绑定器位置（第 1 步查到的生成点各一个）：def、theorem、abbrev 的参数，类型里的 ∀ 绑定器，
structure 参数，inductive 构造子参数；以及省略这些参数的使用处（structure 参数的自动参数在投影、构造子处不会被自动补，Lean 自身报错，不写使用处）。 -/

def apDef (n : Nat) (_h : n ≤ n + 1 := by omega) : Nat := n

theorem apThm (n : Nat) (_h : 0 < n := by omega) : n = n := rfl

abbrev apAbbrev (n : Nat) (_h : n ≤ n := by omega) : Nat := n

theorem apForall : ∀ (n : Nat) (_h : 0 < n := by omega), n = n := fun _ _ => rfl

structure ApParam (n : Nat) (_h : 0 < n := by decide) where
  v : Nat

inductive ApInd where
  | mk (n : Nat) (_h : n ≤ n := by omega)

def apUse : Nat := apDef 3 + apAbbrev 2

theorem apUseThm : (5 : Nat) = 5 := apThm 5

def apIndUse : ApInd := ApInd.mk 1
