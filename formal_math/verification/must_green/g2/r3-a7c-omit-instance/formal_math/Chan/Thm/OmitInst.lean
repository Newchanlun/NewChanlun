module
public section
section
variable {α : Type} [DecidableEq α]
theorem uses_dec (a b : α) : decide (a = b) = decide (a = b) := rfl
omit [DecidableEq α] in
theorem no_dec (a : α) : a = a := rfl
end
