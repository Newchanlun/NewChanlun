module
public import Chan.Defs.Fixture
@[expose] public section
inductive PullbackInd (n : Nat) : Prop where
  | mk : D n = 1 → PullbackInd n
  | other : D n = 1 → PullbackInd n

def PullbackAlias (n : Nat) : Prop := PullbackInd n

theorem extractPullback {n : Nat} (h : PullbackAlias n) : D n = 1 := by
  cases h with
  | mk e => exact e
  | other e => exact e
