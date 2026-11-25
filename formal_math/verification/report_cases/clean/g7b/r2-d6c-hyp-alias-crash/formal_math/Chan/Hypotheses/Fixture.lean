module
public import Chan.Defs.Fixture
@[expose] public section
structure PullbackHyp (n : Nat) : Prop where
  ok : D n = 1
def HypAlias (n : Nat) : Prop := PullbackHyp n
