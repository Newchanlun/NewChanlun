module

public import Mathlib.Tactic.Common

public section

theorem a (config : Nat) (h : config = 0) : config + 0 = 0 := by
  obtain rfl := h
  rfl

theorem b (h : ∃ config : Nat, config = 0) : True := by
  obtain ⟨config, hconfig⟩ := h
  trivial

theorem c (config : Nat) : config = config := by
  calc config = config := rfl

theorem d (n : Nat) : n = n := by
  induction n with
  | zero => rfl
  | succ config ih => rfl

theorem e : ∀ config : Nat, config = config := by
  intro (config : Nat)
  rfl

theorem f (config : Nat ∨ Nat) : True := by
  rcases config with (config | config)
  · trivial
  · trivial

def g (config : Nat) : Nat :=
  let config := config + 1
  have _hconfig : config = config := rfl
  config

instance (priority := low) instC : Inhabited Nat := ⟨0⟩
