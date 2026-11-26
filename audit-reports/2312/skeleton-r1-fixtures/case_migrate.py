"""环境层搬家：各类明文必红写法经新入口整条流水线跑一遍；外加必绿对照与初始化器哨兵（带正对照）。"""
import rf, os, sys, json, subprocess, shutil
r = rf.repo()
base, files = rf.base_and_files(r)
only = sys.argv[1:]
M = "module\n\npublic section\n\n"
summary = []
def case(name, extra, expect, **kw):
    if only and name not in only:
        return None
    head = r.commit({**files, **{"formal_math/" + k: (v if isinstance(v, bytes) else v.encode()) for k, v in extra.items()}}, base)
    res = rf.run(name, r, head, base, **kw)
    reds = sorted({l.split(" ")[3] for l in res["out"].splitlines() if l.startswith("FM RED ")})
    summary.append((name, res["rc"], ",".join(reds) or "-", expect))
    return res

case("M2-sorry-warn-off", {"Chan/Thm/M2.lean": M + "set_option warn.sorry false in\ntheorem m2 : False := sorry\n"}, "1 ENV_SORRY")
case("M2b-sorry-plain", {"Chan/Thm/M2b.lean": M + "theorem m2b : False := sorry\n"}, "1 BUILD_WFAIL")
case("M2c-sorryAx-direct", {"Chan/Thm/M2c.lean": M + "set_option warn.sorry false in\ntheorem m2c : False := sorryAx False false\n"}, "1 ENV_SORRY")
case("M3-native-decide", {"Chan/Thm/M3.lean": M + "theorem m3 : 2 + 2 = 4 := by native_decide\n"}, "1 ENV_AXIOM,ENV_AXIOM_DEP")
case("M3b-decide-native", {"Chan/Thm/M3b.lean": M + "theorem m3b : 2 + 2 = 4 := by decide +native\n"}, "1 ENV_AXIOM,ENV_AXIOM_DEP")
case("M4-unsafe", {"Chan/Thm/M4.lean": M + "unsafe def m4 : Nat := 1\n"}, "1 ENV_UNSAFE")
case("M5-partial", {"Chan/Thm/M5.lean": M + "partial def m5 (n : Nat) : Nat := m5 (n + 1)\n"}, "1 ENV_PARTIAL")
case("M6-implemented-by", {"Chan/Thm/M6.lean": M + "def m6impl (n : Nat) : Nat := n\n\n@[implemented_by m6impl] def m6 (n : Nat) : Nat := n + 0\n"}, "1 ENV_IMPLEMENTED_BY")
case("M7-extern", {"Chan/Thm/M7.lean": M + '@[extern "rf_m7"] opaque m7 : Nat → Nat\n'}, "1 ENV_EXTERN")
case("M8-meta", {"Chan/Thm/M8.lean": M + "meta def m8 : Nat := 1\n"}, "1 ENV_META")
case("M9-private-axiom", {"Chan/Thm/M9.lean": "module\n\nprivate axiom m9 : False\n\npublic theorem m9use : False := m9\n"}, "1 ENV_AXIOM,ENV_AXIOM_DEP")
case("M9b-axiom-in-explore", {"ChanExplore/M9b.lean": M + "axiom m9b : False\n"}, "1 ENV_AXIOM,ENV_AXIOM_DEP")
case("M9c-axiom-in-instance-proof", {"Chan/Thm/M9c.lean": M + "axiom m9c : ∀ n : Nat, n = n + 0\n\ninstance : Inhabited { n : Nat // n = n + 0 } := ⟨⟨0, m9c 0⟩⟩\n"}, "1 ENV_AXIOM,ENV_AXIOM_DEP")
# 头部写法
case("H1-prelude", {"Chan/Thm/H1.lean": "module\nprelude\n"}, "1 PRELUDE")
case("H2-meta-import", {"Chan/Thm/H2.lean": "module\n\nmeta import Chan.Base\n"}, "1 META_IMPORT")
case("H2b-public-meta-import", {"Chan/Thm/H2b.lean": "module\n\npublic meta import Chan.Base\n"}, "1 META_IMPORT")
case("H3-import-all", {"Chan/Thm/H3.lean": "module\n\nimport all Chan.Base\n"}, "1 IMPORT_ALL")
case("H4-import-lean", {"Chan/Thm/H4.lean": "module\n\nimport Lean\n"}, "1 IMPORT_PINNED")
case("H4b-import-unknown-root", {"Chan/Thm/H4b.lean": "module\n\nimport Foo.Bar\n"}, "1 IMPORT_SOURCE(+IMPORT_EDGE)")
case("H5-no-module", {"Chan/Thm/H5.lean": "import Chan.Base\n"}, "1 MODULE_FIRST")
case("H6-thm-imports-explore", {"Chan/Thm/H6.lean": "module\n\nimport ChanExplore.Base\n"}, "1 IMPORT_EDGE(+IMPORT_SOURCE)")
case("H7-defs-imports-thm", {"Chan/Defs/H7.lean": "module\n\nimport Chan.Base\n"}, "1 IMPORT_EDGE", branch="decl/review")
case("H8-whole-mathlib", {"Chan/Thm/H8.lean": "module\n\nimport Mathlib\n"}, "1 WHOLE_MATHLIB")
case("H9-header-garbage", {"Chan/Thm/H9.lean": "module\n\nimport import\n"}, "1 HEADER_PARSE 或构建红")
# 必绿对照：归纳类型（ctorIdx 豁免）、结构递归、良基递归、实例、私有定义、几种证明战术
green = M + """inductive Color where
  | red | green | blue

def Color.next : Color → Color
  | .red => .green
  | .green => .blue
  | .blue => .red

def fact : Nat → Nat
  | 0 => 1
  | n + 1 => (n + 1) * fact n

def gcd' (a b : Nat) : Nat :=
  if b = 0 then a else gcd' b (a % b)
termination_by b
decreasing_by exact Nat.mod_lt _ (by omega)

instance : Inhabited Color := ⟨.red⟩

private def helper (n : Nat) : Nat := n + 1

private theorem helper_pos (n : Nat) : 0 < helper n := by unfold helper; omega

theorem fact_zero : fact 0 = 1 := by decide

theorem color_next3 (c : Color) : c.next.next.next = c := by cases c <;> rfl

noncomputable def pick : Nat := Classical.choice ⟨0⟩
"""
case("G1-honest-green", {"Chan/Thm/G1.lean": green}, "0 -")
# Defs 文件完全不用 public section：旧实现源码层判 EXPOSE_SECTION；新实现环境层看不见（私有名跳过）
res = case("X1-defs-no-public-section", {"Chan/Defs/X1.lean": "module\n\ndef hidden : Nat := 1\n", "statement-lock.json": "{}\n"}, "旧：1 EXPOSE_SECTION；新：见实测", branch="decl/review")
case("X1b-defs-no-public-section-locked", {"Chan/Defs/X1.lean": "module\n\ndef hidden : Nat := 1\n", "statement-lock.json": json.dumps({"_private.Chan.Defs.X1.0.hidden": "39d6fa2a2ab7ac2a1ba4a8f5a4d6f8e8f0b38b9f4e3f1a2c0d9e8b7a6c5d4e3f"}) + "\n"}, "占位哈希→LOCK_CHANGED，取现算值", branch="decl/review")
print("\n名字\t退出码\t红码\t期望")
for row in summary:
    print("\t".join(map(str, row)))
