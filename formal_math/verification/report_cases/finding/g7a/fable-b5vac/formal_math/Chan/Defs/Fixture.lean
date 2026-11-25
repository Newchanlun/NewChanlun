module

@[expose] public section

structure Bogus where
  n : Nat
  flag : Prop
  bot : False

end

public section

theorem bogus_refines (e : Bogus) : e.flag = (e.n = 0) := False.elim e.bot
