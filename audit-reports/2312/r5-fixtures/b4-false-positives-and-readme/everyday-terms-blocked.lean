-- 日常 Lean 4 / Mathlib 基础项语法误拒汇总（每项均已在单文件夹具中独立实测门 3 退 1）
module
import Mathlib.Data.Finset.Basic
import Mathlib.Data.Rat.Defs
public section

def negInt (x : Int) : Int := -x
def arrLit : Array Nat := #[1, 2]
def ratInv (q : Rat) : Rat := q⁻¹
def exMem (xs : List Nat) : Prop := ∃ x ∈ xs, x = 0
def termCalc (a : Nat) : a + 0 = a :=
  calc a + 0 = a := Nat.add_zero a
def showFrom (n : Nat) : n = n := show n = n from rfl
def doIfAndBind (o : Option Nat) : Option Nat := do
  let x ← o
  if x = 0 then return 1 else return x
def finsetOps (a b : Finset Nat) : Finset Nat := a ∪ b
def finsetLit : Finset Nat := {1, 2}
def polyType.{u} (α : Type*) : Type _ := α
