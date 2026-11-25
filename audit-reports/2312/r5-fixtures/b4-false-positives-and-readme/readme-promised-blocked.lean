-- 所有下列写法均在 formal_math/verification/README.md 门 3 白名单中明确承诺放行，
-- 但在提交 594e49b5ec034461f9196c6cfb0c58fe017e8dc5 下全部被 syntax-kinds.tsv 误拒（门 3 退 1）：
-- 1. open Nat（README.md:59 允许 open；报错 Lean.Parser.Command.openSimple）
-- 2. protected / nonrec / public 修饰符（README.md:69-70；报错 Lean.Parser.Command.{protected,nonrec,public}）
-- 3. class inductive（README.md:67；报错 Lean.Parser.Command.classInductive）
-- 4. @[grind] / @[norm_cast] / @[simps] / @[mono]（README.md:71-74；报错 Lean.Parser.Attr.{grind,norm_cast,simps}、Mathlib.Tactic.Monotonicity.Attr.mono）
-- 5. simp (maxSteps := 1000) / simp (zeta := false)（README.md:82；报错 Lean.Parser.Tactic.valConfigItem）
module
import Mathlib.Tactic.Common
import Mathlib.Tactic.Simps.Basic
import Mathlib.Tactic.Monotonicity
public section

open Nat

protected def fProt : Nat := 1
nonrec def fNonrec : Nat := 2
public def fPub : Nat := 3

class inductive MyClassInd (α : Type) : Type where
  | mk (v : α)

@[grind] theorem attrGrind (n : Nat) : n = n := rfl
@[norm_cast] theorem attrNormCast (n : Nat) : (n : Int) = (n : Int) := rfl
@[mono] theorem attrMono {a b : Nat} (h : a ≤ b) : a + 1 ≤ b + 1 := Nat.succ_le_succ h

structure PairS where
  x : Nat
@[simps] def mkPairS (n : Nat) : PairS := ⟨n⟩

theorem valConfigLiteral : 1 = 1 := by
  simp (maxSteps := 1000)
