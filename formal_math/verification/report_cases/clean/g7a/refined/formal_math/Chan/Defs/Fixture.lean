module

@[expose] public section

structure Raw where
  points : Nat

structure Reviewed where
  raw : Raw
  inRange : Bool
  correct : inRange = decide (raw.points > 0)

end

public section

theorem raw_to_criterion (r : Reviewed) : r.inRange = decide (r.raw.points > 0) :=
  r.correct
