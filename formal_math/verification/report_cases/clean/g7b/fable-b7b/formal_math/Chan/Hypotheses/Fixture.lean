module

public import Chan.Defs.Fixture

@[expose] public section

inductive PullbackInd (n : Nat) : Prop where
  | mk : D n = 1 → PullbackInd n
