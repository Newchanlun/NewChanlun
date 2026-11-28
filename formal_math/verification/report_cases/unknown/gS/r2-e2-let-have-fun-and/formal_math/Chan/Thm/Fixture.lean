module
public section
theorem let_wrap : let T := Nat; ∀ (x : T), x = 0 → x = 1 → False :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
theorem have_wrap : have T := Nat; ∀ (x : T), x = 0 → x = 1 → False :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
theorem fun_wrap : (fun T => ∀ (x : T), x = 0 → x = 1 → False) Nat :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
theorem and_wrap : True ∧ (∀ (x : Nat), x = 0 → x = 1 → False) :=
  ⟨trivial, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
