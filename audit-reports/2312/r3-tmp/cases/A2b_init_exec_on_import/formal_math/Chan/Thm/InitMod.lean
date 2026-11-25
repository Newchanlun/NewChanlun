module
public meta import Lean
public section
public meta def runOnLoad : IO Unit := do
  IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-v3-review/init_pwned2.txt" "INIT_EXECUTED_IN_AUDIT"

@[init runOnLoad]
public meta def initTrigger : Unit := ()
