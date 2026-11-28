module
public import Init.Data.Rat.Basic
@[expose] public section
def safeNatNeZero (x dt : Nat) (_h : dt ≠ 0) : Nat := x / dt
def safeNatZeroNe (x dt : Nat) (_h : 0 ≠ dt) : Nat := x / dt
def safeNatGt (x dt : Nat) (_h : dt > 0) : Nat := x / dt
def safeNatAdd1 (x dt : Nat) : Nat := x / (dt + 1)
def safeNat1Add (x dt : Nat) : Nat := x / (1 + dt)
def safeNatSub (x : Nat) (dt : { n : Nat // 0 < n }) : Nat := x / dt.val
def safeNatSubNe (x : Nat) (dt : { n : Nat // n ≠ 0 }) : Nat := x / dt.1
def safeNatDite (x dt : Nat) : Nat := if _h : dt ≠ 0 then x / dt else 0
def safeFinList (xs : List Nat) (i : Fin xs.length) : Nat := xs[i]
def safeFinArr (xs : Array Nat) (i : Fin xs.size) : Nat := xs[i]
def safeFinDiv (x : Nat) (i : Fin 5) : Nat := x / (i.1 + 1)
def safeIntPos (x dt : Int) (_h : 0 < dt) : Int := x / dt
def safeRatPos (x dt : Rat) (_h : 0 < dt) : Rat := x / dt
def safeRatSubPos (x : Rat) (dt : { q : Rat // 0 < q }) : Rat := x / dt.val
def safeRatLit (x : Rat) : Rat := x / (2 : Rat)
