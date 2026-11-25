module
@[expose] public section
structure VacSub where
  raw : { _n : Nat // False }
  flag : Bool

structure VacEmpty where
  raw : Empty
  flag : Bool

structure VacFin where
  raw : Fin 0
  flag : Bool
end
public section
theorem vacSub_ref (e : VacSub) : e.flag = (fun _ : { _n : Nat // False } => false) e.raw :=
  False.elim e.raw.property

theorem vacEmpty_ref (e : VacEmpty) : e.flag = (fun _ : Empty => false) e.raw :=
  Empty.elim e.raw

theorem vacFin_ref (e : VacFin) : e.flag = (fun _ : Fin 0 => false) e.raw :=
  Fin.elim0 e.raw
