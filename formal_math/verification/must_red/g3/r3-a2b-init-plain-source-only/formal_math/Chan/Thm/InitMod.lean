module
public meta import Lean
public section
public meta def runOnLoad : IO Unit := do
  IO.FS.writeFile "init-executed.txt" "INIT_EXECUTED_IN_AUDIT"

@[init runOnLoad]
public meta def initTrigger : Unit := ()
