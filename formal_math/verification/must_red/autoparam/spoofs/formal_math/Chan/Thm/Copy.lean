module

public section

/-! 冒用：手写 meta def，名字、类型、值都与 `by omega` 生成的逐字相同，且被 autoParam 引用；手写 def 的提示是 regular。 -/

meta def SpCopy._auto_1 : Lean.Syntax :=
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

theorem spCopyUse (_h : autoParam (1 = 1) SpCopy._auto_1) : True := trivial
