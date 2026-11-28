module
import Lean
def _a : String := s!"{'"'}"
set_option linter.unusedVariables false
set_option autoImplicit true
#eval 1 + 1
run_cmd Lean.logInfo (toString (1 + 1))
declare_syntax_cat sneaky_cat
infixl:65 " +++ " => Nat.add
def _b : Char := '"'
def useOp (ignored : α) : Nat := 2 +++ 3
