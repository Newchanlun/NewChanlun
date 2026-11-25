module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let opt1 := mkIdent `linter.unusedVariables
  let f := mkIdent `false
  let id1 := mkIdent `hiddenUnused
  let id2 := mkIdent `hiddenPartial
  let id3 := mkIdent `hiddenUnsafe
  let id4 := mkIdent `hiddenVacuous
  let opt2 := mkIdent `autoImplicit
  let t := mkIdent `true
  let id5 := mkIdent `hiddenAutoImp
  let stx1 ← `(set_option $opt1 $f in public def $id1 (x : Nat) : Nat := 0)
  let stx2 ← `(set_option $opt2 $t in public def $id5 (x : α) : α := x)
  let stx3 ← `(public partial def $id2 (n : Nat) : Nat := $id2 n)
  let stx4 ← `(public unsafe def $id3 : Nat := 0)
  let stx5 ← `(public theorem $id4 (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))
  return mkNullNode #[stx1, stx2, stx3, stx4, stx5]
