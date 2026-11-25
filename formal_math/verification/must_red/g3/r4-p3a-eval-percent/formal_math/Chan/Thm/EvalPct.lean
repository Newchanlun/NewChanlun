module
import Mathlib.Tactic.Eval
public section
def userCode (n : Nat) : Nat := dbgTrace "EVAL_PCT_USER_CODE_RAN" fun _ => n + 1
def res : Nat := eval% (userCode 41)
