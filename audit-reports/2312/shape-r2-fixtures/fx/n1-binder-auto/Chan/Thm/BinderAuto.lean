module

public section

/-! 绑定器上的自动参数 `(h : p := by tac)`：README 说推测同样被 ENV_META 误拒、未实测。 -/

theorem probe (n : Nat) (h : n ≤ n := by omega) : n ≤ n := h
