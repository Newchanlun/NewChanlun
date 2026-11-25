module
public section
theorem rec_thm (n : Nat) (h : n = n) : n + 0 = n :=
  match n with
  | 0 => h
  | k + 1 => congrArg Nat.succ (rec_thm k rfl)
