module
public section
def runOnLoad : IO Unit := do
  IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-v3-review/init_pwned.txt" "INIT_RAN"

@[init runOnLoad]
def initTrigger : Unit := ()
