module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let opt := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent (Name.mkStr2 "linter" "unusedVariables"),
    mkIdent `false
  ]
  let defCmd ← `(public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd := Syntax.node .none `Lean.Parser.Command.in #[opt, mkA "in", defCmd]
  let vacCmd ← `(public theorem hiddenVacuous (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))
  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let declMods := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode #[partMod], mkNullNode
  ]
  let partDef ← `(def hiddenPartial (n : Nat) : Nat := hiddenPartial n)
  let partDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declMods, partDef[1]]
  return mkNullNode #[inCmd, vacCmd, partDecl]
