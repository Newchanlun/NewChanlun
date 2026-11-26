module

public import Chan.Thm.Basic

public section

namespace Chan.Final

theorem result : (1 : Nat) + 0 = 1 := by simp

/-- info: 'Chan.Final.result' depends on axioms: [propext] -/
#guard_msgs in
#print axioms result

/-- info: Nat : Type -/
#guard_msgs in
#check Nat

end Chan.Final
