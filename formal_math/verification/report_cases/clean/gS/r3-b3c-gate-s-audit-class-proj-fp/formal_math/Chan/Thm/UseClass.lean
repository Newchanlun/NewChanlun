module
public import Chan.Defs.Spec
public section
theorem with_pos [Pos 2] (n : Nat) : 0 < n + 2 := Nat.succ_pos _
theorem with_proj (w : PredWrap) (n : Nat) (h : w.1 n) : w.1 n := h
