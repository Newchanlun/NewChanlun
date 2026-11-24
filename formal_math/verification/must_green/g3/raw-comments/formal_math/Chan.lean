module

@[expose] public section

def quoted : String := r""
def escaped : String := r##"/- #eval "# run_cmd -/"##
/- 外层 /- 内层 -/ 外层 -/
def character : Char := '"'
