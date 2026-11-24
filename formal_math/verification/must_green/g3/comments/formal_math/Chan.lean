module

/- 被引用的记号不是命令： /- sorry -/ unsafe #eval -/
private def labels : String := "axiom sorry native_decide"

private theorem good : (0 : Nat) < 1 := by decide
