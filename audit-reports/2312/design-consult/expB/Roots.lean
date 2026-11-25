import Lean
open Lean
unsafe def main (args : List String) : IO UInt32 := do
  let env ← importModules (args.toArray.map fun s => { module := s.toName }) {} (level := .exported)
  let mut hist : Std.HashMap Name Nat := {}
  for m in env.header.moduleNames do hist := hist.insert m.getRoot (hist.getD m.getRoot 0 + 1)
  IO.println s!"modules={env.header.moduleNames.size} roots={hist.toList}"
  return 0
