module

@[expose] public section

def Statement : Prop := ∀ (x : Nat), x = 0 → x = 1 → False

end
public section

theorem claim : Statement := fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
