module
public section
def runOnLoad : IO Unit := do
  IO.FS.writeFile "init-executed.txt" "INIT_RAN"

@[init runOnLoad]
def initTrigger : Unit := ()
