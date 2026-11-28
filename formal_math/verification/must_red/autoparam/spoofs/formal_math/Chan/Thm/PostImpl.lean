module

public section

/-! 冒用：给真生成的载体事后挂 implemented_by（运行期改执行别的代码）。 -/

structure SpPost where
  a : Nat
  h : a ≤ a := by omega

meta def spPostTarget : Lean.Syntax := Lean.Syntax.missing

attribute [implemented_by spPostTarget] SpPost.h._autoParam
