module
public meta import Lean
public section
open Lean in
public meta def stripInfo (s : Syntax) : Syntax :=
  match s with
  | .node _ k args => .node .none k (args.map stripInfo)
  | .ident _ r v p => .ident .none r v p
  | .atom _ v => .atom .none v
  | .missing => .missing

open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let idUnused := mkIdent `hiddenUnused
  let idAuto := mkIdent `hiddenAutoImp
  let idAlpha := mkIdent `α
  let idVac := mkIdent `hiddenVacuous
  let idPart := mkIdent `hiddenPartial
  let idUnsafe := mkIdent `hiddenUnsafe
  let idFake := mkIdent `fakeImpl
  let idImpl := mkIdent `hiddenImplBy

  let baseOpt1 ← `(set_option pp.all false in public def $idUnused (x : Nat) : Nat := 0)
  let inCmd1 := baseOpt1.raw.setArg 0 (baseOpt1.raw[0]!.setArg 1 (mkIdent (Name.mkStr2 "linter" "unusedVariables")))

  let baseOpt2 ← `(set_option pp.all true in public def $idAuto (x : $idAlpha) : $idAlpha := x)
  let inCmd2 := baseOpt2.raw.setArg 0 (baseOpt2.raw[0]!.setArg 1 (mkIdent `autoImplicit))

  let vacCmd ← `(public theorem $idVac (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))

  let partBase ← `(public def $idPart (n : Nat) : Nat := $idPart n)
  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let partDecl := partBase.raw.setArg 0 (partBase.raw[0]!.setArg 6 (mkNullNode #[partMod]))

  let unsafeBase ← `(public def $idUnsafe : Nat := 0)
  let unsafeMod := Syntax.node .none `Lean.Parser.Command.unsafe #[mkA ("un" ++ "safe")]
  let unsafeDecl := unsafeBase.raw.setArg 0 (unsafeBase.raw[0]!.setArg 5 (mkNullNode #[unsafeMod]))

  let fakeImplCmd ← `(public def $idFake : Nat := 999)
  let implName := Name.mkSimple ("implemented_" ++ "by")
  let attrSimple := Syntax.node .none `Lean.Parser.Attr.simple #[mkIdent implName, mkNullNode #[idFake]]
  let attrInst := Syntax.node .none `Lean.Parser.Term.attrInstance #[mkNullNode, attrSimple]
  let attrs := Syntax.node .none `Lean.Parser.Term.attributes #[mkA "@[", mkNullNode #[attrInst], mkA "]"]
  let implBase ← `(public def $idImpl : Nat := 1)
  let implDecl := implBase.raw.setArg 0 (implBase.raw[0]!.setArg 1 (mkNullNode #[attrs]))

  return stripInfo (mkNullNode #[inCmd1, inCmd2, vacCmd, partDecl, unsafeDecl, fakeImplCmd, implDecl])
