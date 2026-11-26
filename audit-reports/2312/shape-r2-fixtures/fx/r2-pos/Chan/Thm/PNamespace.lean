module

public import Mathlib.Tactic.Common

public section

namespace A
namespace B
theorem t : True := by aesop (config := {})
end B
end A
