module

public section

theorem congruence (x y : Nat) (f : Nat → Nat) (h : x = y) : f x = f y :=
  congrArg f h
