module
public import Chan.Defs.Fixture
@[expose] public section
inductive PullbackInd (n : Nat) : Prop where
  | mk (ok : D n = 1)
