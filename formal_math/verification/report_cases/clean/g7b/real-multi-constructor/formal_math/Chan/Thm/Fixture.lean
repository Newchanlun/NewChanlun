module

public import Chan.Hypotheses.Fixture

public section

theorem claim (h : PullbackInd 0) : D 0 = 1 := by
  cases h with
  | mk e => exact e
  | other e => exact e
