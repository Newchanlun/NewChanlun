module
import Mathlib.Tactic.SuccessIfFailWithMsg
public section
def mkMsg : String := dbgTrace "SIFFWM_EVAL_RAN" fun _ => "tactic 'rfl' failed, the left-hand side\n  0\nis not definitionally equal to the right-hand side\n  1\n⊢ 0 = 1"
theorem t : True := by
  success_if_fail_with_msg mkMsg (have : 0 = 1 := by rfl)
  trivial
