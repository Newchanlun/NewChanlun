module

public import Chan.Defs.Fixture

public section

def aboveResident : Above Nat :=
  ⟨0, 1, 0 < 1, rfl⟩
def boundedResident : Bounded 2 :=
  ⟨1, true, rfl⟩
