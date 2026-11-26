module

public section

/-! 自动参数与 deriving、instance、mutual、private、protected 同时出现。 -/

structure ApRec where
  a : Nat
  b : Nat
  hab : a ≤ a + b := by omega
  deriving Repr, DecidableEq, BEq, Hashable, Ord, Inhabited

inductive ApTree where
  | leaf
  | node (l r : ApTree) (k : Nat) (_hk : k ≤ k + 1 := by omega)
  deriving Repr, BEq, Hashable, Ord, DecidableEq, Inhabited

class ApBound (α : Type) where
  bound : Nat
  pos : 0 < bound + 1 := by omega

instance : ApBound ApRec where
  bound := 7

mutual
def apEven (k : Nat) (_h : k ≤ k := by omega) : Bool := match k with
  | 0 => true
  | k + 1 => apOdd k
def apOdd (k : Nat) (_h : k ≤ k := by omega) : Bool := match k with
  | 0 => false
  | k + 1 => apEven k
end

private def apPriv (k : Nat) (_h : k ≤ k := by omega) : Nat := k

namespace ApNs
protected def prot (k : Nat) (_h : k ≤ k := by omega) : Nat := k
end ApNs

def apCombinedUse : Nat := apPriv 1 + ApNs.prot 2 + (if apEven 4 then 1 else 0) + ApBound.bound ApRec +
  ({ a := 1, b := 2 } : ApRec).b + (ApTree.node .leaf .leaf 3).ctorIdx
