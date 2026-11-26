import Lean
import Mathlib.Tactic.Common
open Lean

partial def walk (label : String) (s : Syntax) (d : Nat) : IO Unit := do
  let k := s.getKind
  let ks := k.toString
  if (ks.splitOn "onfig").length > 1 then
    IO.println s!"{label}: depth={d} kind={k} nargs={s.getNumArgs} arg0kind={s[0].getKind} arg0atom={s[0].isAtom} arg1={s[1]}"
  for a in s.getArgs do walk label a (d+1)

def show1 (env : Environment) (label src : String) : IO Unit := do
  let ctx := Parser.mkInputContext src "<probe>"
  let (_, ps, _) ← Parser.parseHeader ctx
  let st := Elab.Command.mkState env {} {}
  let (stx, _, msgs) := Parser.parseCommand ctx { env := st.env, options := {}, currNamespace := .anonymous, openDecls := [] } ps {}
  if msgs.hasErrors then IO.println s!"{label}: PARSE ERROR"
  else walk label stx 0

unsafe def main : IO Unit := do
  enableInitializersExecution
  Lean.initSearchPath (← Lean.findSysroot)
  let env ← importModules #[{module := `Init}, {module := `Init, isMeta := true}, {module := `Mathlib.Tactic.Common}] {} (loadExts := true) (level := .exported)
  show1 env "plausible" "module\n\ntheorem t (n : Nat) : n = n := by plausible (config := {})\n"
  show1 env "aesop" "module\n\ntheorem t : True := by aesop (config := {})\n"
  show1 env "aesopsimp" "module\n\ntheorem t : True := by aesop (simp_config := {})\n"
  show1 env "simp" "module\n\ntheorem t : True := by simp (config := {})\n"
  show1 env "decide" "module\n\ntheorem t : True := by decide (config := {})\n"
  show1 env "simpnative" "module\n\ntheorem t : True := by simp (native := true)\n"
