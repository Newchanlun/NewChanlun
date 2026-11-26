module


public section

def a (cfg_config : Nat) : Nat := (cfg_config : Nat)

def b (config : Nat) : Nat := (config)

def c (config : Nat) : Nat × Nat := (config, config)

def d : Nat → Nat := fun (config : Nat) => config

theorem e : ∀ (config : Nat), config = config := fun _ => rfl

theorem f : ∃ config : Nat, config = 0 := ⟨0, rfl⟩
