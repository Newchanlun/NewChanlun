module
def _a := r"\"
set_option linter.unusedVariables false
#eval 1 + 1
syntax "my_secret_syn" : term
macro_rules | `(my_secret_syn) => `(42)
def _b := "\""
def useSecret : Nat := my_secret_syn
