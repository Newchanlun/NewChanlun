module

public import Chan.Hypotheses.Fixture

public section

theorem claim (h : PullbackHyp 0) : D 0 = 1 := h.ok
