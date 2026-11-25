module

public section

theorem claim (x : Nat) (h : x = 0) : x + 1 = 1 := congrArg (· + 1) h
