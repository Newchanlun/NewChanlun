module
@[expose] public section
inductive Dir where
  | up
  | down
  deriving DecidableEq, Repr, BEq
structure Bar where
  lo : Nat
  hi : Nat
  valid : lo ≤ hi
  deriving DecidableEq
def countdown (n : Nat) : Nat :=
  if h : n = 0 then 0 else countdown (n - 1)
termination_by n
def firstElem (arr : Array Nat) (h : 0 < arr.size) : Nat := arr[0]
