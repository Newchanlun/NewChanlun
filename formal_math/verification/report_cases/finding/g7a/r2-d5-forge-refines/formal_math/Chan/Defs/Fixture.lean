module
@[expose] public section
structure BadS1 where
  raw : Nat
  flag : Bool
  bot : False
end
public section
theorem ref1 (e : BadS1) : e.flag = (e.raw == 0) := False.elim e.bot
