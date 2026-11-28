module
import Batteries.Lean.LawfulMonad
public section
def pwn : Nat := by_elab do
  IO.FS.writeFile "sentinel_by_elab_pwned.txt" "BY_ELAB_EXECUTED_IN_AUDIT"
  return Lean.mkNatLit 42
