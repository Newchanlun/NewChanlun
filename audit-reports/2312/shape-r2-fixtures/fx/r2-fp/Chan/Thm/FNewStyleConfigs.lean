module

public import Mathlib.Tactic.Common

public section

theorem a (x : Nat) : x + 0 = x := by simp (maxSteps := 1000)
theorem b (p : Prop) (h : p) : p := by simp +contextual [h]
theorem c (x : Nat) : x = x := by simp -zeta
theorem d : 2 < 3 := by decide +kernel
theorem e (x : Nat) : x + 0 = x := by simp (maxDischargeDepth := 3) (singlePass := true)
theorem f (x y : Nat) (h : x = y) : x + x = y + x := by rw (occs := .pos [1]) [h]
theorem g (x : Nat) : x + 0 = x := by simp (disch := omega)
theorem h (x : Nat) : x + 0 = x := by simp (discharger := simp)
theorem i : True := by aesop (rule_sets := [builtin])
theorem j (x : Nat) : x + 0 = x := by simp_all (maxSteps := 10) +arith
theorem k (x : Nat) : x = x := by omega +splitDisjunctions
