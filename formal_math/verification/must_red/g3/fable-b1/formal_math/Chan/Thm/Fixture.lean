module

public import Lean.Elab.Command

public section

def quoteChar : String := s!"{'"'}"
set_option linter.unusedVariables false in
def unusedArg (n : Nat) : Nat := 0
set_option autoImplicit true in
def implicitId (x : α) : α := x
#eval 1 + 1
run_cmd pure ()
declare_syntax_cat fmcat
syntax "fmtok" : fmcat
infixl:65 " +++ " => Nat.add
macro "fmzero" : term => `(0)
def resync : Char := '"'

theorem plain : (1 : Nat) +++ 1 = 2 := rfl
