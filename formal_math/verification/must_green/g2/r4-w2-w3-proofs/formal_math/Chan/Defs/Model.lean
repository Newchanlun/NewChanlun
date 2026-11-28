module
public import Mathlib.Algebra.BigOperators.Group.Finset.Defs
public import Mathlib.Algebra.Order.Ring.Defs
@[expose] public section
structure IntervalBar (P : Type) [LinearOrder P] where
  lo : P
  hi : P
  valid : lo ≤ hi
@[ext] structure Pt where
  x : Nat
  y : Nat
deriving DecidableEq, BEq, Inhabited
@[reducible] def Pt.sum (p : Pt) : Nat := p.x + p.y
