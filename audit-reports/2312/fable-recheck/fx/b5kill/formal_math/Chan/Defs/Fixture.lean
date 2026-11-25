module

@[expose] public section

structure Above (P : Type) [LT P] where
  lo : P
  x : P
  above : Prop
  correct : above = (lo < x)

structure Bounded (k : Nat) where
  v : Nat
  ok : Bool
  correct : ok = decide (v < k)

end

public section

theorem above_refines {P : Type} [LT P] (s : Above P) : s.above = (s.lo < s.x) := s.correct

theorem bounded_refines {k : Nat} (s : Bounded k) : s.ok = decide (s.v < k) := s.correct
