module

public section

/-! 冒用：名字形态不是 `_autoParam` 或 `_auto_<数字>`。 -/

meta def spName : Lean.Syntax :=
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

theorem spNameUse (_h : autoParam (1 = 1) spName) : True := trivial
