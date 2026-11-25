module
import Lean
def _a : String := s!"{'"'}"
set_option linter.unusedVariables false
#eval 1 + 1
run_cmd Lean.logInfo (toString (1 + 1))
declare_syntax_cat sneaky_cat
infixl:65 " +++ " => Nat.add
def _b : Char := '"'
def useOp : Nat := 2 +++ 3
