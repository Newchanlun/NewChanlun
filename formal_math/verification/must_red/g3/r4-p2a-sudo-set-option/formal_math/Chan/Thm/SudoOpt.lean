module
import Mathlib.Tactic.SudoSetOption
public section
def bypassUnused : Nat → Nat :=
  sudo set_option linter.unusedVariables false in
  sudo set_option debug.skipKernelTC true in
  sudo set_option autoImplicit true in
  sudo set_option smartUnfolding false in
  fun unusedArg => 0
