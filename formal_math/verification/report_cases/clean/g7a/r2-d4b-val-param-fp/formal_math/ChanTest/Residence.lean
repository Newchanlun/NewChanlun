module

public import Chan.Defs.Fixture

public section

def resident : Window 2 := ⟨1, true, propext ⟨fun _ => by decide, fun _ => rfl⟩⟩
