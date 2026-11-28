module

public section

/-! 冒用：类型是定义上相等的别名，不是 Lean.Syntax 本身。 -/

abbrev SpSyn := Lean.Syntax

meta def SpAlias._auto_1 : SpSyn :=
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

theorem spAliasUse (_h : autoParam (1 = 1) SpAlias._auto_1) : True := trivial
