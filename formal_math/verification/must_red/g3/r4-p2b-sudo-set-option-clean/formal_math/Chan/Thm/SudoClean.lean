module
import Mathlib.Tactic.SudoSetOption
public section
def setControlledOpts : Nat :=
  sudo set_option debug.skipKernelTC true in
  sudo set_option autoImplicit true in
  sudo set_option relaxedAutoImplicit true in
  sudo set_option smartUnfolding false in
  sudo set_option linter.unusedVariables false in
  0

theorem silenceUnusedInTactic : True :=
  sudo set_option linter.unusedVariables false in
  by
    have unusedLocal : Nat := 42
    trivial
