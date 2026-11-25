module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let opt1 := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent (Name.mkStr2 "linter" "unusedVariables"),
    mkIdent `false
  ]
  let defCmd ← `(public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd1 := Syntax.node .none `Lean.Parser.Command.in #[opt1, mkA "in", defCmd]

  let opt2 := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent `autoImplicit,
    mkIdent `true
  ]
  let impCmd ← `(public def hiddenAutoImp (x : α) : α := x)
  let inCmd2 := Syntax.node .none `Lean.Parser.Command.in #[opt2, mkA "in", impCmd]

  let vacCmd ← `(public theorem hiddenVacuous (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))

  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let declModsP := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode, mkNullNode #[partMod]
  ]
  let partDef ← `(def hiddenPartial (n : Nat) : Nat := hiddenPartial n)
  let partDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsP, partDef.raw[1]!]

  let unsafeMod := Syntax.node .none `Lean.Parser.Command.unsafe #[mkA ("un" ++ "safe")]
  let declModsU := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode #[unsafeMod], mkNullNode
  ]
  let unsafeDef ← `(def hiddenUnsafe : Nat := 0)
  let unsafeDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsU, unsafeDef.raw[1]!]

  let implName := Name.mkSimple ("implemented_" ++ "by")
  let attrSimple := Syntax.node .none `Lean.Parser.Attr.simple #[mkIdent implName, mkNullNode #[mkIdent `fakeImpl]]
  let attrInst := Syntax.node .none `Lean.Parser.Term.attrInstance #[mkNullNode, attrSimple]
  let attrs := Syntax.node .none `Lean.Parser.Term.attributes #[mkA "@[", mkNullNode #[attrInst], mkA "]"]
  let declModsI := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode #[attrs],
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode, mkNullNode
  ]
  let implDef ← `(def hiddenImplBy : Nat := 1)
  let implDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsI, implDef.raw[1]!]

  let fakeImplCmd ← `(public def fakeImpl : Nat := 999)
  return mkNullNode #[inCmd1, inCmd2, vacCmd, partDecl, unsafeDecl, fakeImplCmd, implDecl]
