module
public import Mathlib.Data.Nat.Factorial.Basic
public section
namespace Nat
theorem g1 : 3 ! = 6 := rfl
section
end
theorem g2 : 3 ! = 6 := rfl
end Nat
section Inner
open Nat
theorem g3 : 3 ! = 6 := rfl
end Inner
open Nat in
theorem g4 : 3 ! = 6 := rfl
mutual
def ev : Nat → Bool
  | 0 => true
  | n + 1 => od n
def od : Nat → Bool
  | 0 => false
  | n + 1 => ev n
end
end
public section
open Nat
theorem g5 : 3 ! = 6 := rfl
