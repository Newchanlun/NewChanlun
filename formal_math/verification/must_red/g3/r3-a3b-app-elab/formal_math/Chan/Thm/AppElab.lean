module
public meta import Lean
public section
open Lean Elab Term in
@[app_elaborator Nat.succ]
public meta def myAppElab : TermElab := fun _ _ => return mkNatLit 0

@[export my_c_symbol]
def exportedFn (x : Nat) : Nat := x
