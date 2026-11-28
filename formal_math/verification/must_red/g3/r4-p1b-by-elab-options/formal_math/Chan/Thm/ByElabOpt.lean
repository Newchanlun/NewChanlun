module
import Batteries.Lean.LawfulMonad
public section
def silenceUnused : Nat → Nat := by_elab do
  Lean.withOptions (fun o => (o.setBool `linter.unusedVariables false).setBool `debug.skipKernelTC true) do
    Lean.Elab.Term.elabTerm (← `(fun unusedVar => 0)) (some (Lean.mkArrow (Lean.mkConst ``Nat) (Lean.mkConst ``Nat)))
