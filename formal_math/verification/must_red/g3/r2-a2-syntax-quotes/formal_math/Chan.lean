module
def _a : String := s!"{'"'}"
syntax "my_secret_syn" : term
macro_rules | `(my_secret_syn) => `(42)
def _b : Char := '"'
def useSecret : Nat := my_secret_syn
