module

@[expose] public section

inductive Dir where
  | up
  | down
  deriving DecidableEq

def countdown (n : Nat) : Nat :=
  if h : n = 0 then 0 else countdown (n - 1)
termination_by n
decreasing_by omega

class Pos (n : Nat) : Prop where
  pos : 0 < n
