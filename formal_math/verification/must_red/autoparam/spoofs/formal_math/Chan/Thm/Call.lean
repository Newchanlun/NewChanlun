module

public section

/-! 冒用：值里有函数调用。 -/

meta def SpCall._auto_1 : Lean.Syntax := Lean.mkAtom ("om" ++ "ega")

theorem spCallUse (_h : autoParam (1 = 1) SpCall._auto_1) : True := trivial
