module
public import Chan.Defs.Alias
public section
theorem vac_locked : LockedWrap (∀ x : Nat, x = 0 → x = 1 → False) :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
