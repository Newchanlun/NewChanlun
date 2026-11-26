module

public import Batteries.Tactic.Congr

public section

theorem t (f g : Nat → Nat) (h : ∀ x, f x = g x) : (fun x => f x) = (fun x => g x) := by
  rcongr (config := {}) x
  exact h x
