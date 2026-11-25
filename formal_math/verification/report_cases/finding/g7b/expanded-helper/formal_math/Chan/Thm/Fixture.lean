module

public import Chan.Hypotheses.Fixture

public section

private theorem helper (n : Nat) : H n := rfl

theorem claim (n : Nat) : H n := helper n
