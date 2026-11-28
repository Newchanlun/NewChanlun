module
import Mathlib.Tactic.Trace
import Mathlib.Tactic.SuccessIfFailWithMsg
public section
def mkTrace : String := dbgTrace "TRACE_EVAL_RAN" fun _ => "hello"
def mkExpected : String := dbgTrace "SIFFWM_EVAL_RAN" fun _ => "Tactic `rfl` failed: The left-hand side\n  0\nis not definitionally equal to the right-hand side\n  1\n\n⊢ 0 = 1"
theorem t : True := by
  trace mkTrace
  success_if_fail_with_msg mkExpected (have : 0 = 1 := by rfl)
  trivial
