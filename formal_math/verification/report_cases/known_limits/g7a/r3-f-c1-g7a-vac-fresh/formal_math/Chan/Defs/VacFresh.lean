module
@[expose] public section
structure VacSub where
  raw : { _n : Nat // False }
  flag : Bool
end
public section
theorem vacSub_ref (e : VacSub) : e.flag = (fun _ : { _n : Nat // False } => false) e.raw :=
  False.elim e.raw.property
