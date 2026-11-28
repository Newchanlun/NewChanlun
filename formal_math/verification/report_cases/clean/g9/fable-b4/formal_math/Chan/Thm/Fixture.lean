module

public section

def sumTo : Nat → Nat
  | 0 => 0
  | n + 1 => n + 1 + sumTo n

theorem le_sumTo : ∀ n : Nat, n ≤ sumTo n
  | 0 => Nat.le_refl 0
  | n + 1 => by
    show n + 1 ≤ n + 1 + sumTo n
    exact Nat.le_add_right _ _
