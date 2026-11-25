module
public section
theorem rec_thm (n : Nat) : n + 0 = n :=
  match n with
  | 0 => rfl
  | k + 1 => congrArg Nat.succ (rec_thm k)
