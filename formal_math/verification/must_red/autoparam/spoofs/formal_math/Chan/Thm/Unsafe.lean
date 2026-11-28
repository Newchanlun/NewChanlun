module

public section

/-! 冒用：unsafe 的同形定义。 -/

meta unsafe def SpUnsafe._auto_1 : Lean.Syntax :=
  Lean.Syntax.node Lean.SourceInfo.none (Lean.Name.mkStr4 "Lean" "Parser" "Tactic" "tacticSeq")
    (Array.push Array.empty (Lean.Syntax.node Lean.SourceInfo.none
      (Lean.Name.mkStr4 "Lean" "Parser" "Tactic" "tacticSeq1Indented")
      (Array.push Array.empty (Lean.Syntax.node Lean.SourceInfo.none (Lean.Name.mkStr1 "null")
        (Array.push Array.empty (Lean.Syntax.node Lean.SourceInfo.none
          (Lean.Name.mkStr4 "Lean" "Parser" "Tactic" "omega")
          (Array.push (Array.push Array.empty (Lean.mkAtom "omega"))
            (Lean.Syntax.node Lean.SourceInfo.none (Lean.Name.mkStr4 "Lean" "Parser" "Tactic" "optConfig")
              (Array.push Array.empty
                (Lean.Syntax.node Lean.SourceInfo.none (Lean.Name.mkStr1 "null") Array.empty))))))))))

unsafe def spUnsafeUse (_h : autoParam (1 = 1) SpUnsafe._auto_1) : Nat := 0
