module
@[expose] public section
structure ExecState where
  step : Nat
def execRun : List Nat → Nat
  | [] => 0
  | _ :: xs => 1 + execRun xs
