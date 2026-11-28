module

public section

/-! 冒用：值里引用别的 meta 常量。 -/

meta def spRefHelper : Lean.Syntax := Lean.mkAtom "omega"

meta def SpRef._auto_1 : Lean.Syntax :=
  Lean.Syntax.node Lean.SourceInfo.none (Lean.Name.mkStr1 "null") (Array.push Array.empty spRefHelper)

theorem spRefUse (_h : autoParam (1 = 1) SpRef._auto_1) : True := trivial
