#!/usr/bin/env python3
"""独审 r2 的夹具生成器：每个变体一个文件，落到 fx/<批名>/Chan/Thm/<名>.lean，并写 EXPECT.tsv。
期望取值：SHAPE_FORBIDDEN（须含该红码）、SHAPE_PARSE、RED（任意红码）、GREEN（零命中）。
用法: gen_r2.py [输出根目录]"""
import os, sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else "/home/workspace/fm/tmp/review-g2/fx"
C = "Mathlib.Tactic.Common"
F, G, P, R = "SHAPE_FORBIDDEN", "GREEN", "SHAPE_PARSE", "RED"

# ---- 甲-1 复验：出现位置 ----
POS = [
    ("PSeqFocus", (C,), "theorem t : True ∧ True := by\n  constructor <;> aesop (config := { maxRuleApplications := 200 })", F),
    ("PAllGoals", (C,), "theorem t : True ∧ True := by\n  constructor\n  all_goals aesop (config := {})", F),
    ("PAnyGoals", (C,), "theorem t : True ∧ True := by\n  constructor\n  any_goals aesop (simp_config := {})", F),
    ("PRepeat", (C,), "theorem t : True := by\n  repeat aesop (config := {})", F),
    ("PTry", (C,), "theorem t : True := by\n  try aesop (config := {})\n  trivial", F),
    ("PNestedBy", (C,), "theorem t : True := by\n  exact (by exact (by aesop (config := {})))", F),
    ("PShowFromBy", (C,), "theorem t : True := show True from by aesop (config := {})", F),
    ("PCalcStep", (C,), "theorem t (a : Nat) : a = a := by\n  calc a = a := by aesop (config := {})\n    _ = a := by plausible (config := {})", F),
    ("PMatchArm", (C,), "theorem t (n : Nat) : True :=\n  match n with\n  | 0 => by aesop (config := {})\n  | _ + 1 => trivial", F),
    ("PHaveBy", (C,), "theorem t : True := by\n  have h : True := by aesop (simp_config := {})\n  exact h", F),
    ("PWhere", (C,), "theorem t : True := aux\nwhere\n  aux : True := by aesop (config := {})", F),
    ("PPlausibleSeqFocus", (C,), "theorem t (n : Nat) : n = n ∧ n = n := by\n  constructor <;> plausible (config := { numInst := 5 })", F),
    ("PPlausibleTry", (C,), "theorem t (n : Nat) : n = n := by\n  try plausible (config := { numInst := 5 })\n  rfl", F),
    ("PCongrNum", ("Batteries.Tactic.Congr",), "theorem t (f : Nat → Nat) (a b : Nat) (h : a = b) : f a = f b := by\n  congr (config := { closePost := false }) 1", F),
    ("PRcongr", ("Batteries.Tactic.Congr",), "theorem t (f g : Nat → Nat) (h : ∀ x, f x = g x) : (fun x => f x) = (fun x => g x) := by\n  rcongr (config := {}) x\n  exact h x", F),
    ("PInstanceAnon", (C,), "instance : Inhabited True := ⟨by aesop (config := {})⟩", F),
    ("PDecreasingBy", (C,), "def f (n : Nat) : Nat := if h : n = 0 then 0 else f (n - 1)\ntermination_by n\ndecreasing_by aesop (config := {})", F),
    ("PBullet", (C,), "theorem t : True ∧ True := by\n  constructor\n  · aesop (config := {})\n  · trivial", F),
    ("PCase", (C,), "theorem t : True ∧ True := by\n  constructor\n  case left => aesop (config := {})\n  next => aesop (simp_config := {})", F),
    ("PIterate", (C,), "theorem t : True := by\n  iterate 2 aesop (config := {})", F),
    ("PFunBy", (C,), "theorem t : Nat → True := fun _ => by aesop (config := {})", F),
    ("PBinderAutoParam", (C,), "theorem t (h : True := by aesop (config := {})) : True := h", F),
    ("PStructFieldDefault", (C,), "structure S where\n  n : Nat\n  ok : True := by aesop (config := {})", F),
    ("PSetOptionIn", (C,), "set_option maxHeartbeats 400000 in\ntheorem t : True := by aesop (config := {})", F),
    ("PNamespace", (C,), "namespace A\nnamespace B\ntheorem t : True := by aesop (config := {})\nend B\nend A", F),
    ("PMutual", (C,), "mutual\ntheorem t1 : True := by aesop (config := {})\ntheorem t2 : True := trivial\nend", F),
    ("PAesopQuestion", (C,), "theorem t : True := by\n  aesop? (config := {})", F),
    ("PAesopClauseAfterAdd", (C,), "theorem t : True := by\n  aesop (add norm simp Nat.add_zero) (config := {})", F),
    ("PAnonCtorPair", (C,), "theorem t : True ∧ True := ⟨by aesop (config := {}), by aesop (simp_config := {})⟩", F),
    ("PCheckCmd", (C,), "#check (by aesop (config := {}) : True)", F),
    ("PExample", (C,), "example : True := by aesop (config := {})", F),
    ("PSimpDischarger", (C,), "theorem t (a : Nat) : a + 0 = a := by\n  simp (disch := aesop (config := {}))", F),
    ("PParenSeq", (C,), "theorem t : True := by\n  all_goals (try aesop (config := {}))", F),
    ("PFirstInner", (C,), "theorem t : True := by\n  first | (aesop (simp_config := {}); done) | trivial", F),
    ("PSuffices", (C,), "theorem t : True := by\n  suffices h : True from h\n  aesop (config := {})", F),
    ("PTermSuffices", (C,), "theorem t : True :=\n  suffices h : True from h\n  by aesop (config := {})", F),
    ("PLetBy", (C,), "def d : Nat :=\n  let _h : True := by aesop (config := {})\n  1", F),
    ("PInduction", (C,), "theorem t (n : Nat) : True := by\n  induction n with\n  | zero => aesop (config := {})\n  | succ _ _ => trivial", F),
    ("PRcases", (C,), "theorem t (h : True ∨ True) : True := by\n  rcases h with _ | _\n  · aesop (config := {})\n  · trivial", F),
    ("PConvNested", (C,), "theorem t (a : Nat) : a + 0 = a := by\n  conv =>\n    lhs\n    simp (config := {})", F),
    ("PConvTactic", (C,), "theorem t (a : Nat) : a + 0 = a := by\n  conv =>\n    lhs\n    tactic => aesop (config := {})\n  rfl", F),
    ("PGrindSetConfig", (C,), "theorem t (a : Nat) : a = a := by\n  grind =>\n    set_config (config := {}) in\n    done", R),
]

# ---- 甲-1 复验：记号之间的空白、换行、注释 ----
WS = [
    ("WSpaceInside", (C,), "theorem t : True := by\n  aesop ( config := {} )", F),
    ("WNoSpace", (C,), "theorem t : True := by\n  aesop (config:={})", F),
    ("WNewlines", (C,), "theorem t : True := by\n  aesop (\n      config\n      :=\n      {})", F),
    ("WLineComment", (C,), "theorem t : True := by\n  aesop ( -- 行注释\n      config := {})", F),
    ("WBlockComments", (C,), "theorem t : True := by\n  aesop (/- 块 -/ config /- 块 -/ := /- 块 -/ {})", F),
    ("WLineCommentBeforeAssign", (C,), "theorem t : True := by\n  aesop (config -- c\n      := {})", F),
    ("WNestedBlockComment", (C,), "theorem t : True := by\n  aesop (/- 外 /- 内 -/ 外 -/ simp_config := {})", F),
    ("WSimpConfigSpaces", (C,), "theorem t : True := by\n  aesop (   simp_config   :=   {}   )", F),
    ("WPlausibleNewline", (C,), "theorem t (n : Nat) : n = n := by\n  plausible (\n      config := { numInst := 5 })", F),
    ("WPlausibleBlock", (C,), "theorem t (n : Nat) : n = n := by\n  plausible (/- x -/config/- y -/:=/- z -/{ numInst := 5 })", F),
    ("WCongrNewline", ("Batteries.Tactic.Congr",), "theorem t (f : Nat → Nat) (a b : Nat) (h : a = b) : f a = f b := by\n  congr (\n      config := {})", F),
    ("WSimpNewStyleBlock", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (/- a -/ config /- b -/ := {})", F),
    ("WSimpNewStyleNewline", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (\n      config\n      := {})", F),
    ("WClauseOnNextLine", (C,), "theorem t : True := by\n  aesop\n    (config := {})", F),
    ("WDocCommentBetween", (C,), "theorem t : True := by\n  aesop (config := /- 取值前 -/ { maxRuleApplications := 1 } /- 取值后 -/)", F),
]

# ---- 甲-1 复验：旧式子句与新式配置项混写 ----
MIX = [
    ("XSimpCfgThenPos", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (config := {}) +contextual", F),
    ("XSimpPosThenCfg", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp +contextual (config := { zeta := false })", F),
    ("XSimpValThenCfg", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (maxSteps := 10) (config := {})", F),
    ("XSimpNegCfgLemmas", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp -zeta (config := {}) [Nat.add_zero]", F),
    ("XSimpCfgValAt", (), "theorem t (a : Nat) (h : a + 0 = a) : a + 0 = a := by\n  simp (config := {}) (maxSteps := 10) at h ⊢", F),
    ("XAesopBoth", (C,), "theorem t : True := by\n  aesop (config := {}) (simp_config := {})", F),
    ("XAesopAddSimpCfg", (C,), "theorem t : True := by\n  aesop (add norm simp Nat.add_zero) (simp_config := {}) (rule_sets := [builtin])", F),
    ("XDecideKernelCfg", (), "theorem t : 2 < 3 := by\n  decide +kernel (config := {})", F),
    ("XSimpAll", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp_all (config := {})", F),
    ("XDsimp", (), "theorem t (a : Nat) : a + 0 = a := by\n  dsimp (config := {})", F),
    ("XRw", (), "theorem t (a b : Nat) (h : a = b) : a = b := by\n  rw (config := {}) [h]", F),
    ("XSimpa", (), "theorem t (a : Nat) (h : a = a) : a + 0 = a := by\n  simpa (config := {}) using h", F),
    ("XOmega", (), "theorem t (a : Nat) : a = a := by\n  omega (config := {})", F),
    ("XConstructor", (), "theorem t : True := by\n  constructor (config := {})", F),
    ("XNormNum", ("Mathlib.Tactic.NormNum.Basic",), "theorem t : (2 : Nat) + 2 = 4 := by\n  norm_num (config := {})", F),
    ("XRingNf", ("Mathlib.Tactic.Ring.RingNF",), "theorem t (a : Nat) : a + 0 = a := by\n  ring_nf (config := {})", F),
    ("XSimpOnlyCfgPosVal", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp +arith (maxSteps := 5) (config := {}) -zeta only [Nat.add_zero]", F),
    ("XNativeAndCfg", (), "theorem t : 2 < 3 := by\n  decide +native (config := {})", F),
]

# ---- 名字判据：README 写「名字以 config 结尾」----
NAME = [
    ("NSimpConfigAesop", (C,), "theorem t : True := by\n  aesop (simp_config := {})", F),
    ("NMyConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (my_config := 1)", F),
    ("NReconfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (reconfig := 1)", F),
    ("NCapitalConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (Config := 1)", G),
    ("NConfigPrime", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (config' := 1)", G),
    ("NConfigs", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (configs := 1)", G),
    ("NConfigUnderscore", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (config_ := 1)", G),
    ("NUpperCONFIG", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (CONFIG := 1)", G),
    ("NGuillemetConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp («config» := {})", F),
    ("NNamespacedConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (X.config := 1)", F),
    ("NRootConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp (_root_.config := {})", F),
    ("NGuillemetSpaceConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp («my config» := 1)", G),
    ("NGuillemetDottedConfig", (), "theorem t (a : Nat) : a + 0 = a := by\n  simp («x.config» := 1)", G),
    ("NAesopGuillemet", (C,), "theorem t : True := by\n  aesop («config» := {})", R),
    ("NAesopCapital", (C,), "theorem t : True := by\n  aesop (Config := {})", P),
    ("NAesopMyConfig", (C,), "theorem t : True := by\n  aesop (my_config := {})", P),
    ("NAesopConfigPrime", (C,), "theorem t : True := by\n  aesop (config' := {})", P),
    ("NAesopNamespaced", (C,), "theorem t : True := by\n  aesop (X.config := {})", P),
    ("NPlausibleGuillemet", (C,), "theorem t (n : Nat) : n = n := by\n  plausible («config» := {})", R),
    ("NPlausibleSimpConfig", (C,), "theorem t (n : Nat) : n = n := by\n  plausible (simp_config := {})", P),
    ("NTermConfigItem", (C,), "theorem t (n : Nat) : n = n := by\n  simp (config.zeta := false)", G),
]

# ---- 新规则的误拒探针 ----
PRE = "structure S where\n  config : Nat\n  n : Nat\n\ndef run (config : Nat) (n : Nat) : Nat := config + n\n\n"
FP = [
    # 函数应用的命名参数
    ("FNamedArgConfig", (), PRE + "theorem t : run (config := 1) 2 = 3 := rfl", F),
    ("FNamedArgCtor", (), PRE + "def s : S := S.mk (config := 1) (n := 2)", F),
    ("FNamedArgDot", (), PRE + "def S.go (s : S) (cfg_config : Nat) : Nat := s.n + cfg_config\n\ndef v (s : S) : Nat := s.go (cfg_config := 1)", F),
    ("FNamedArgSuffix", (), "def re (reconfig : Nat) (simp_config : Nat) : Nat := reconfig + simp_config\n\ndef v : Nat := re (reconfig := 1) (simp_config := 2)", F),
    ("FNamedArgInTactic", (), PRE + "theorem run_eq (config n : Nat) : run config n = config + n := rfl\n\ntheorem t : run 1 2 = 1 + 2 := by\n  exact run_eq (config := 1) (n := 2)", F),
    ("FNamedArgInSimpLemma", (), PRE + "theorem run_eq (config n : Nat) : run config n = config + n := rfl\n\ntheorem t : run 1 2 = 1 + 2 := by\n  rw [run_eq (config := 1)]", F),
    ("FNamedArgPipe", (), PRE + "def v : Nat := id <| run (config := 1) 2", F),
    ("FNamedArgOther", (), "def run2 (cfg : Nat) (n : Nat) : Nat := cfg + n\n\ntheorem t : run2 (cfg := 1) (n := 2) = 3 := rfl", G),
    ("FNamedArgConfigPrefix", (), "def run3 (configN : Nat) (config' : Nat) : Nat := configN + config'\n\ntheorem t : run3 (configN := 1) (config' := 2) = 3 := rfl", G),
    # 结构实例记法、匿名构造子
    ("FStructInst", (), PRE + "def s : S := { config := 1, n := 2 }\n\ndef s2 : S := { s with config := 3 }\n\ndef s3 : S := ⟨1, 2⟩\n\ndef s4 : S where\n  config := 1\n  n := 2", G),
    ("FStructPattern", (), PRE + "def g (s : S) : Nat :=\n  match s with\n  | ⟨config, n⟩ => config + n\n\ndef g2 (s : S) : Nat :=\n  let ⟨config, _⟩ := s\n  config\n\ndef g3 : S → Nat\n  | { config := c, n := _ } => c", G),
    # 类型标注、绑定器
    ("FTypeAscription", (), "def a (cfg_config : Nat) : Nat := (cfg_config : Nat)\n\ndef b (config : Nat) : Nat := (config)\n\ndef c (config : Nat) : Nat × Nat := (config, config)\n\ndef d : Nat → Nat := fun (config : Nat) => config\n\ntheorem e : ∀ (config : Nat), config = config := fun _ => rfl\n\ntheorem f : ∃ config : Nat, config = 0 := ⟨0, rfl⟩", G),
    ("FBinderDefault", (), "def a (config := 5) (n : Nat := config) : Nat := config + n\n\ndef b (config : Nat := 5) : Nat := config\n\nvariable (simp_config := 3)\n\ndef c : Nat := simp_config", G),
    ("FStructFieldBinder", (), "structure T where\n  (config : Nat := 5)\n  (simp_config := 3)\n  n : Nat", G),
    ("FAutoParamBinder", (), "theorem a (config : Nat) (h : config = config := by rfl) : config = config := h", G),
    # 不存在但形似的写法（只记录实际行为）
    ("FLetParenAssign", (), "def a : Nat :=\n  let (config := 5) := 1\n  config", R),
    ("FFunBinderDefault", (), "def a : Nat → Nat := fun (config := 5) => config", R),
    ("FParenAssignTerm", (), "def a (config : Nat) : Nat := (config := 5)", R),
    # 新式配置项
    ("FNewStyleConfigs", (C,), "theorem a (x : Nat) : x + 0 = x := by simp (maxSteps := 1000)\ntheorem b (p : Prop) (h : p) : p := by simp +contextual [h]\ntheorem c (x : Nat) : x = x := by simp -zeta\ntheorem d : 2 < 3 := by decide +kernel\ntheorem e (x : Nat) : x + 0 = x := by simp (maxDischargeDepth := 3) (singlePass := true)\ntheorem f (x y : Nat) (h : x = y) : x + x = y + x := by rw (occs := .pos [1]) [h]\ntheorem g (x : Nat) : x + 0 = x := by simp (disch := omega)\ntheorem h (x : Nat) : x + 0 = x := by simp (discharger := simp)\ntheorem i : True := by aesop (rule_sets := [builtin])\ntheorem j (x : Nat) : x + 0 = x := by simp_all (maxSteps := 10) +arith\ntheorem k (x : Nat) : x = x := by omega +splitDisjunctions", G),
    # 字符串与注释里的同形文字
    ("FStringsComments", (C,), "/-- 文档注释：aesop (config := {}) 与 plausible (config := {}) -/\ndef s1 : String := \"(config := x) aesop (config := {}) (simp_config := {})\"\n\n-- 行注释 aesop (config := { maxRuleApplications := 1 })\n/- 块注释 (simp_config := {}) /- 嵌套 (config := {}) -/ -/\ndef s2 (config : Nat) : String := s!\"(config := {config})\"\n\ndef s3 : String := r\"simp (config := {})\"\n\n/-! 模块注释 (config := 1) -/\ndef c1 : Char := '('", G),
    # 名为 config 的局部变量在各种日常位置
    ("FLocalsNamedConfig", (C,), "theorem a (config : Nat) (h : config = 0) : config + 0 = 0 := by\n  obtain rfl := h\n  rfl\n\ntheorem b (h : ∃ config : Nat, config = 0) : True := by\n  obtain ⟨config, hconfig⟩ := h\n  trivial\n\ntheorem c (config : Nat) : config = config := by\n  calc config = config := rfl\n\ntheorem d (n : Nat) : n = n := by\n  induction n with\n  | zero => rfl\n  | succ config ih => rfl\n\ntheorem e : ∀ config : Nat, config = config := by\n  intro (config : Nat)\n  rfl\n\ntheorem f (config : Nat ∨ Nat) : True := by\n  rcases config with (config | config)\n  · trivial\n  · trivial\n\ndef g (config : Nat) : Nat :=\n  let config := config + 1\n  have _hconfig : config = config := rfl\n  config\n\ninstance (priority := low) instC : Inhabited Nat := ⟨0⟩", G),
    # 白名单属性 simps 的配置（按规则判红的设计内行为）
    ("FSimpsAttrConfig", ("Mathlib.Tactic.Simps.Basic",), "structure P where\n  a : Nat\n  b : Nat\n\n@[simps (config := { fullyApplied := false })]\ndef p : P := ⟨1, 2⟩", F),
    ("FSimpsAttrNewStyle", ("Mathlib.Tactic.Simps.Basic",), "structure P where\n  a : Nat\n  b : Nat\n\n@[simps -fullyApplied]\ndef p : P := ⟨1, 2⟩\n\n@[simps (attr := simp) a]\ndef q : P := ⟨1, 2⟩", G),
]

# ---- 原 valConfigItem 分支改动后：native 仍红；config 键没有两边都不管的写法 ----
NAT = [
    ("VDecidePlusNative", (), "theorem t : 2 < 3 := by decide +native", F),
    ("VDecideMinusNative", (), "theorem t : 2 < 3 := by decide -native", F),
    ("VDecideValNative", (), "theorem t : 2 < 3 := by decide (native := true)", F),
    ("VDecideValNativeFalse", (), "theorem t : 2 < 3 := by decide (native := false)", F),
    ("VNativeDecide", (), "theorem t : 2 < 3 := by native_decide", F),
    ("VDecideGuillemetNative", (), "theorem t : 2 < 3 := by decide («native» := true)", F),
    ("VDecidePlusGuillemetNative", (), "theorem t : 2 < 3 := by decide +«native»", F),
    ("VDecideKernelNative", (), "theorem t : 2 < 3 := by decide +kernel +native", F),
    ("VDecideCfgNative", (), "theorem t : 2 < 3 := by decide (config := { native := true })", F),
    ("VDecideNativeNewline", (), "theorem t : 2 < 3 := by\n  decide (\n      native\n      := true)", F),
    ("VDecideNativeComment", (), "theorem t : 2 < 3 := by\n  decide (/- x -/ native /- y -/ := true)", F),
    ("VSimpNative", (), "theorem t (a : Nat) : a + 0 = a := by simp +native", F),
    ("VDecideCfgPlain", (), "theorem t : 2 < 3 := by decide (config := {})", F),
    ("VSimpCfgPlain", (), "theorem t (a : Nat) : a + 0 = a := by simp (config := {})", F),
    ("VSimpPlusConfig", (), "theorem t (a : Nat) : a + 0 = a := by simp +config", G),
    ("VSimpMinusConfig", (), "theorem t (a : Nat) : a + 0 = a := by simp -config", G),
    ("VDecideKernelOnly", (), "theorem t : 2 < 3 := by decide +kernel", G),
    ("VNamedArgNative", (), "def nat (native : Bool) : Bool := native\n\ntheorem t : nat (native := true) = true := rfl", G),
    ("VSimpsNative", ("Mathlib.Tactic.Simps.Basic",), "structure P where\n  a : Nat\n\n@[simps +native]\ndef p : P := ⟨1⟩", F),
]

BATCHES = {"r2-pos": POS, "r2-ws": WS, "r2-mix": MIX, "r2-name": NAME, "r2-fp": FP, "r2-native": NAT}
for batch, cases in BATCHES.items():
    base = os.path.join(ROOT, batch)
    os.makedirs(os.path.join(base, "Chan", "Thm"), exist_ok=True)
    rows = []
    for name, imports, body, expect in cases:
        rel = "Chan/Thm/%s.lean" % name
        text = "module\n\n" + "".join("public import %s\n" % i for i in imports) + "\npublic section\n\n" + body + "\n"
        open(os.path.join(base, rel), "w", encoding="utf-8").write(text)
        rows.append("%s\t%s" % (rel, expect))
    open(os.path.join(base, "EXPECT.tsv"), "w").write("\n".join(rows) + "\n")
    print(batch, len(cases))
