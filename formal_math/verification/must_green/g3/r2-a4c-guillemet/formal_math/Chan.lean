module
def «set_option» : Nat := 1
def «axiom» : Nat := 2
def okChar : Char := '\x22'
def multiLine : String := "line1
#eval 1
set_option linter.unusedVariables false
line4"
def rawMulti : String := r#"line1
#eval 1
-/
"#
