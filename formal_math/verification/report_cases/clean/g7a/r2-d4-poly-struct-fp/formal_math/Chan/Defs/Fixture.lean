module
public import Mathlib.Order.Basic
@[expose] public section
structure GoodBar (P : Type) [LinearOrder P] where
  lo : P
  hi : P
  isUp : Bool
  h_up : isUp = decide (lo ≤ hi)
end
public section
theorem goodBar_ref (P : Type) [LinearOrder P] (e : GoodBar P) :
    e.isUp = decide (e.lo ≤ e.hi) := e.h_up
