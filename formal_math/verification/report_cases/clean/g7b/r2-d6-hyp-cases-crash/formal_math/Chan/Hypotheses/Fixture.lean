module
public import Chan.Defs.Fixture
@[expose] public section
structure PullbackHyp (n : Nat) : Prop where
  ok : D n = 1
