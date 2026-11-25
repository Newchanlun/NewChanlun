module

public import Chan.Defs.Fixture

public section

private theorem helper : D 0 = 1 := rfl

theorem claim : D 0 = 1 := helper
