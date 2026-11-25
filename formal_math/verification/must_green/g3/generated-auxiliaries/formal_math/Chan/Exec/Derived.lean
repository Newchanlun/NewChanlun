module
public section
namespace Shapes
inductive Tree where
  | leaf
  | node (cs : List Tree)
deriving Repr, BEq, Hashable, Ord, Inhabited, Nonempty

mutual
inductive A where
  | a
  | b (x : B)
inductive B where
  | c (x : A)
end
deriving instance Repr, DecidableEq, BEq, Hashable, Ord for A, B

structure P where
  x : Nat
  y : Bool
deriving Repr, DecidableEq, BEq, Hashable, Ord, Inhabited
end Shapes

inductive Color where
  | red
  | green
  | blue
deriving Repr, DecidableEq, BEq, Hashable, Ord, Inhabited

def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib n + fib (n + 1)

def ack : Nat → Nat → Nat
  | 0, n => n + 1
  | m + 1, 0 => ack m 1
  | m + 1, n + 1 => ack m (ack (m + 1) n)
termination_by m n => (m, n)

def halve (n : Nat) : Nat := if n ≤ 1 then n else halve (n / 2) + 1

mutual
def even : Nat → Bool
  | 0 => true
  | n + 1 => odd n
def odd : Nat → Bool
  | 0 => false
  | n + 1 => even n
end

def useLet (n : Nat) : Nat :=
  let rec go : Nat → Nat
    | 0 => 0
    | k + 1 => go k + 1
  go n
end
