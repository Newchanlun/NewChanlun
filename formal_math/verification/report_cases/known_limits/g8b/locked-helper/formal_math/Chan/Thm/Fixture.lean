module

public import Chan.Defs.Fixture

public section

theorem claim (x : Nat) (h : x ≠ 0) : x + 0 = x := Eq.trans (lockedEq h) rfl
