BATCH = "c-probe"
T = "Chan/Thm/"
FB = {"SHAPE_FORBIDDEN"}
G = set()
MT = ("Mathlib.Tactic.Common",)
def c(name, body, exp, imports=()):
    return (T + name + ".lean", imports, body, exp)
CASES = [
 c("PlausibleConfig", "theorem t (n : Nat) : n = n := by plausible (config := {})", FB, MT),
 c("PlausibleConfig2", "theorem t (n : Nat) : n = n := by\n  plausible (config := { numInst := 3 })", FB, MT),
 c("AesopConfig", "theorem t : True := by aesop (config := { warnOnNonterminal := false })", FB, MT),
 c("AesopSimpConfig", "theorem t : True := by aesop (simp_config := { decide := true })", FB, MT),
 c("ApplyConfig", "theorem t : True := by apply (config := {}) trivial", FB, ("Mathlib.Tactic.ApplyWith",)),
 c("SimpArithConfig", "theorem t (a : Nat) : a + 0 = a := by simp +arith (config := {})", FB),
 c("ExactModCast", "theorem t : True := by solve_by_elim (config := {})", FB, MT),
 c("ConvertConfig", "theorem t : True := by convert (config := {}) trivial", FB, ("Mathlib.Tactic.Convert",)),
 c("CongrConfig", "theorem t : 1 = 1 := by congr! (config := {})", FB, ("Mathlib.Tactic.CongrExclamation",)),
 c("PushCastConfig", "theorem t : 1 = 1 := by push_cast (config := {})", FB, MT),
 c("FieldSimpConfig", "theorem t : 1 = 1 := by nlinarith (config := {})", FB, ("Mathlib.Tactic.Linarith",)),
 c("PositivityConfig", "theorem t : 1 = 1 := by abel_nf (config := {})", FB, ("Mathlib.Tactic.Abel",)),
 c("TautoConfig", "theorem t : True := by tauto (config := {})", FB, ("Mathlib.Tactic.Tauto",)),
 c("GcongrConfig", "theorem t : True := by exact? (config := {})", FB, MT),
 c("RwSearchConfig", "theorem t (h : 1 = 2) : 2 = 1 := by rewrite (config := {}) [h]; rfl", FB),
 c("NthRwConfig", "theorem t (h : 1 = 2) : 2 = 1 := by nth_rw (config := {}) 1 [h]", FB, ("Mathlib.Tactic.NthRewrite",)),
 c("ErwConfig", "theorem t (h : 1 = 2) : 2 = 1 := by erw (config := {}) [h]", FB, MT),
 c("InferInstConfig", "theorem t : 1 = 1 := by simp_wf (config := {})", FB),
 c("DeltaConfig", "theorem t : 1 = 1 := by simp! (config := {})", FB),
 c("ZetaConfig", "theorem t : 1 = 1 := by simp_all? (config := {})", FB),
 c("DsimpOnly", "theorem t : 1 = 1 := by dsimp only (config := {})", {"SHAPE_PARSE", "SHAPE_FORBIDDEN"}),
 c("BvDecideConfig", "theorem t : 1 = 1 := by bv_omega (config := {})", {"SHAPE_PARSE", "SHAPE_FORBIDDEN"}),
 # 未点名的占位／求值相关写法：记录实际行为
 c("Stop", "theorem t : 1 = 2 := by\n  stop\n  rfl", G),
 c("ExactQ", "theorem t : True := by exact?", G),
 c("PlausibleBare", "theorem t (n : Nat) : n = n := by plausible", G, MT),
 c("BvDecide", "theorem t (x : BitVec 8) : x = x := by bv_decide", G, ("Std.Tactic.BVDecide",)),
 c("DecideKernel", "theorem t : 2 ^ 10 = 1024 := by decide +kernel", G),
 c("LcProof", "theorem t : 1 = 2 := lcProof", G),
 c("DbgTrace", "def d : Nat := dbgTrace \"x\" fun _ => 1", G),
 c("TraceState", "theorem t : True := by\n  trace_state\n  trivial", G),
 c("AesopAddTactic", "theorem t : True := by aesop (add safe tactic foo)", G, MT),
 c("SimpNativeCfg", "theorem t : 1 = 1 := by simp (maxSteps := (dbgTrace \"x\" fun _ => 100))", G),
 c("Unreachable", "def d : Nat := unreachable!", G),
 c("PanicTerm", "def d : Nat := panic! \"x\"", G),
 c("ReduceCmd", "theorem t : True := by\n  simp_arith\n", G),
 c("NormNumExt", "theorem t : (2 : Nat) + 2 = 4 := by norm_num1", G, ("Mathlib.Tactic.NormNum.Basic",)),
 c("Says", "theorem t : True := by\n  simp says simp only", G, ("Mathlib.Tactic.Says",)),
 c("UnsafeIdent", "def d : Nat := unsafeCast 1", G),
 c("OfReduceBool", "theorem t : True := Lean.ofReduceBool true true rfl ▸ trivial", G),
 c("ReduceBoolAx", "theorem t : Lean.reduceBool true = true := rfl", G),
 c("TrustCompiler", "theorem t : True := Lean.trustCompiler ▸ trivial", G),
]
