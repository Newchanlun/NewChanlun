module
public meta import Lean
public section
open Lean Elab Term in
@[app_elaborator Nat.succ]
public meta def myAppElab : AppUnexpander := fun stx => pure stx
