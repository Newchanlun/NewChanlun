module
public section
theorem t (x : Nat) : x = x := by
  grind =>
    set_option debug.skipKernelTC true in
    set_option linter.unusedVariables false in
    skip
