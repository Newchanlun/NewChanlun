module

public section

inductive Dir where
  | up
  | down
  deriving DecidableEq, Repr, Ord

def countdown (n : Nat) : Nat :=
  if h : n = 0 then 0 else countdown (n - 1)
termination_by n
decreasing_by omega

theorem recThm (n : Nat) : n + 0 = n :=
  match n with
  | 0 => rfl
  | k + 1 => congrArg Nat.succ (recThm k)

theorem fromWhere (n : Nat) : n = n := helper n
where
  helper (k : Nat) : k = k := rfl

def fromDefWhere (n : Nat) : Bool := helper n
where
  helper (k : Nat) : Bool := k == 0

mutual
  theorem mutualA (n : Nat) : n = n :=
    match n with
    | 0 => rfl
    | k + 1 => congrArg Nat.succ (mutualB k)
  theorem mutualB (n : Nat) : n = n :=
    match n with
    | 0 => rfl
    | k + 1 => congrArg Nat.succ (mutualA k)
end

class Pos (n : Nat) : Prop where
  pos : 0 < n

instance posOne : Pos 1 := ⟨by decide⟩
instance : Pos 2 := ⟨by decide⟩

private theorem hidden (n : Nat) : n = n := rfl

private theorem privateWhere (n : Nat) : n = n := helper n
where
  helper (k : Nat) : k = k := rfl

theorem fromLetRec (n : Nat) : n = n :=
  let rec helper (k : Nat) : k = k :=
    match k with
    | 0 => rfl
    | j + 1 => congrArg Nat.succ (helper j)
  helper n

private theorem fromPrivateLetRec (n : Nat) : n = n :=
  let rec helper (k : Nat) : k = k := rfl
  helper n
