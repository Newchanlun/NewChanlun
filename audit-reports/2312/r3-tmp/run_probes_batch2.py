"""Batch 2 adversarial & false-positive probes for #2312 v3 review (serial, disk-guarded)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Volumes/AgentStorage/wt-2312-v3-review")
FM_SRC = WT / "formal_math"
VERIF = FM_SRC / "verification"
OUT_ROOT = Path("/Volumes/AgentStorage/fm/tmp/2312-v3-review")
CASES_DIR = OUT_ROOT / "cases"
SCRATCH_ROOT = OUT_ROOT / "scratch"
TEMPLATE_NO_MATHLIB = SCRATCH_ROOT / "tpl_plain"
TEMPLATE_MATHLIB = SCRATCH_ROOT / "tpl_mathlib"
MIN_FREE = 6 * 1024**3

sys.path.insert(0, str(VERIF))
import selftest  # noqa: E402


def check_disk(tag):
    free = shutil.disk_usage("/").free
    gib = free / 1024**3
    print(f"[DISK] {tag}: / free = {gib:.3f} GiB", flush=True)
    if free < MIN_FREE:
        raise RuntimeError(f"Root disk free {gib:.3f} GiB < 6 GiB at {tag}; stopping Lean runs!")
    return gib


def make_env(scratch):
    scratch.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = f"{os.path.expanduser('~')}/.elan/bin:" + env["PATH"]
    for k in ("TMPDIR", "TMP", "TEMP"):
        env[k] = str(scratch)
    env.pop("GITHUB_HEAD_REF", None)
    return env


def ensure_template(tpl_dir: Path, uses_mathlib: bool):
    if (tpl_dir / "formal_math/.lake/build/bin/fm_audit").is_file():
        return
    if tpl_dir.exists():
        shutil.rmtree(tpl_dir)
    dummy_fx = SCRATCH_ROOT / ("dummy_mathlib" if uses_mathlib else "dummy_plain")
    if dummy_fx.exists():
        shutil.rmtree(dummy_fx)
    for sub in ("Chan/Defs", "Chan/Hypotheses", "Chan/Thm", "Chan/Exec",
                "Chan/Final", "Chan/Audit/Math", "ChanTest"):
        (dummy_fx / "formal_math" / sub).mkdir(parents=True)
    if uses_mathlib:
        (dummy_fx / "formal_math/Chan/Thm/Dummy.lean").write_text(
            "module\npublic import Mathlib.Basic.ExistsUnique\n"
        )
    tpl_dir.mkdir(parents=True)
    selftest.base_package(tpl_dir, dummy_fx)
    env = make_env(SCRATCH_ROOT / "tpl_tmp")
    check_disk(f"before template build mathlib={uses_mathlib}")
    r = subprocess.run(
        ["lake", "build", "fm_audit"],
        cwd=tpl_dir / "formal_math",
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    check_disk(f"after template build mathlib={uses_mathlib}")
    if r.returncode != 0:
        raise RuntimeError(f"Template build failed: {r.stdout}\n{r.stderr}")
    shutil.rmtree(dummy_fx)


def copy_template(tpl_dir: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(tpl_dir, dst, symlinks=True)


def run_case(name: str, files: dict[str, str], gates: list[str], uses_mathlib: bool = False,
             build_wfail: bool = True):
    print(f"\n=== CASE {name} (mathlib={uses_mathlib}) ===", flush=True)
    check_disk(f"before {name}")
    case_dir = CASES_DIR / name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for rel, content in files.items():
        p = case_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    tpl = TEMPLATE_MATHLIB if uses_mathlib else TEMPLATE_NO_MATHLIB
    ensure_template(tpl, uses_mathlib)
    repo = SCRATCH_ROOT / f"run_{name}"
    copy_template(tpl, repo)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    env = make_env(repo / "tmp")
    res = {"name": name, "gates": {}}
    try:
        if build_wfail:
            fm = repo / "formal_math"
            lean_mods = []
            for lf in sorted(fm.rglob("*.lean")):
                rel_parts = lf.relative_to(fm).with_suffix("").parts
                if rel_parts[0] in ("verification", ".lake"):
                    continue
                lean_mods.append("+" + ".".join(rel_parts) + ":olean")
            b = subprocess.run(
                ["lake", "build", "--wfail", *lean_mods],
                cwd=fm,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            res["build_wfail"] = {
                "rc": b.returncode,
                "stdout": b.stdout.strip(),
                "stderr": b.stderr.strip(),
            }
            print(f"  build --wfail rc={b.returncode}", flush=True)
            if b.returncode != 0:
                print(f"    build out: {(b.stdout + b.stderr).strip()[:700]}", flush=True)
        for g in gates:
            p = subprocess.run(
                [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
                 "--repo-root", str(repo), "--gate", g],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            res["gates"][g] = {
                "rc": p.returncode,
                "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip(),
            }
            print(f"  gate {g}: rc={p.returncode} stdout={p.stdout.strip()[:260]!r} stderr={p.stderr.strip()[:240]!r}", flush=True)
    finally:
        if repo.exists():
            shutil.rmtree(repo)
        check_disk(f"after {name}")
    return res


CASES = [
    # --- A1c: @[macro] COMPLETE BYPASS of Gates 2, 3(src+env!), S, 7a, 8a, 8b, 9, 15 ---
    (
        "A1c_macro_full_bypass",
        {
            "formal_math/Chan/Thm/Helper.lean": """module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let opt1 := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent (Name.mkStr2 "linter" "unusedVariables"),
    mkIdent `false
  ]
  let defCmd ← `(public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd1 := Syntax.node .none `Lean.Parser.Command.in #[opt1, mkA "in", defCmd]

  let opt2 := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent `autoImplicit,
    mkIdent `true
  ]
  let impCmd ← `(public def hiddenAutoImp (x : α) : α := x)
  let inCmd2 := Syntax.node .none `Lean.Parser.Command.in #[opt2, mkA "in", impCmd]

  let vacCmd ← `(public theorem hiddenVacuous (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))

  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let declModsP := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode, mkNullNode #[partMod]
  ]
  let partDef ← `(def hiddenPartial (n : Nat) : Nat := hiddenPartial n)
  let partDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsP, partDef.raw[1]!]

  let unsafeMod := Syntax.node .none `Lean.Parser.Command.unsafe #[mkA ("un" ++ "safe")]
  let declModsU := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode #[unsafeMod], mkNullNode
  ]
  let unsafeDef ← `(def hiddenUnsafe : Nat := 0)
  let unsafeDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsU, unsafeDef.raw[1]!]

  let implName := Name.mkSimple ("implemented_" ++ "by")
  let attrSimple := Syntax.node .none `Lean.Parser.Attr.simple #[mkIdent implName, mkNullNode #[mkIdent `fakeImpl]]
  let attrInst := Syntax.node .none `Lean.Parser.Term.attrInstance #[mkNullNode, attrSimple]
  let attrs := Syntax.node .none `Lean.Parser.Term.attributes #[mkA "@[", mkNullNode #[attrInst], mkA "]"]
  let declModsI := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode #[attrs],
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode, mkNullNode
  ]
  let implDef ← `(def hiddenImplBy : Nat := 1)
  let implDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declModsI, implDef.raw[1]!]

  let fakeImplCmd ← `(public def fakeImpl : Nat := 999)
  return mkNullNode #[inCmd1, inCmd2, vacCmd, partDecl, unsafeDecl, fakeImplCmd, implDecl]
""",
            "formal_math/Chan/Thm/Victim.lean": """module
public import Chan.Thm.Helper
public section
#check Nat
def useAll : Nat := hiddenUnused 1 + hiddenAutoImp 2 + hiddenPartial 0 + hiddenImplBy
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9", "15"],
        False,
        True,
    ),

    # --- A4b: LEGAL #guard_msgs in Chan/Final PERMANENTLY BROKEN by i==3 bug ---
    (
        "A4b_guard_msgs_legal_broken",
        {
            "formal_math/Chan/Final/LegalGuard.lean": """module
public section
/-- info: Nat : Type -/
#guard_msgs in
#check Nat
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- A5a: example with sorryAx (no env constant!) ---
    (
        "A5a_example_sorryAx",
        {
            "formal_math/Chan/Thm/ExSorry.lean": """module
public section
example : False := sorryAx False false
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- A5b: grind set_option ---
    (
        "A5b_grind_set_option",
        {
            "formal_math/Chan/Thm/GrindOpt.lean": """module
public section
theorem t (x : Nat) : x = x := by
  grind =>
    set_option linter.unusedVariables false in
    skip
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- A3: @[app_elaborator] / @[deriving_handler] / @[export] ---
    (
        "A3_other_meta_attrs",
        {
            "formal_math/Chan/Thm/MetaAttrs.lean": """module
public meta import Lean
public section
open Lean Elab Term in
@[app_elaborator Nat.succ]
public meta def myAppElab : AppUnexpander := fun stx => pure stx
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        False,
    ),

    # --- A3b: @[export] and @[app_elaborator] real compiling ---
    (
        "A3b_app_elab_compiling",
        {
            "formal_math/Chan/Thm/AppElab.lean": """module
public meta import Lean
public section
open Lean Elab Term in
@[app_elaborator Nat.succ]
public meta def myAppElab : TermElab := fun _ _ => return mkNatLit 0

@[export my_c_symbol]
def exportedFn (x : Nat) : Nat := x
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "15"],
        False,
        True,
    ),

    # --- A7b: mutual inductive + deriving instance (impossible inline in Lean 4!) ---
    (
        "A7b_mutual_deriving",
        {
            "formal_math/Chan/Exec/MutualDerive.lean": """module
public section
mutual
  inductive TreeA where
    | leaf : Nat → TreeA
    | node : TreeB → TreeA
  inductive TreeB where
    | nil : TreeB
    | cons : TreeA → TreeB → TreeB
end
deriving instance Repr for TreeA, TreeB
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "7a", "9"],
        False,
        True,
    ),

    # --- A7c: section variable auto-inclusion with [DecidableEq α] needing omit ---
    (
        "A7c_omit_instance_needed",
        {
            "formal_math/Chan/Thm/OmitInst.lean": """module
public section
section
variable {α : Type} [DecidableEq α]
theorem uses_dec (a b : α) : decide (a = b) = decide (a = b) := rfl
omit [DecidableEq α] in
theorem no_dec (a : α) : a = a := rfl
end
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- A7d: deriving Nonempty / Subsingleton on Exec structure ---
    (
        "A7d_deriving_nonempty",
        {
            "formal_math/Chan/Exec/DeriveProp.lean": """module
public section
structure Pt where
  x : Nat
  deriving DecidableEq, Repr, Inhabited, Nonempty
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "9"],
        False,
        True,
    ),

    # --- B3b: Gate S false positives on Chan/Audit counterexample & Pos class & .1 proj ---
    (
        "B3b_gateS_audit_and_class_fp",
        {
            "formal_math/Chan/Defs/Spec.lean": """module
@[expose] public section
def Premise (x : Nat) : Prop := x = 0
def Concl (x : Nat) : Prop := x = 1
class Pos (n : Nat) : Prop where
  pos : 0 < n
instance : Pos 2 := ⟨by decide⟩
structure PredWrap where
  P : Nat → Prop
""",
            "formal_math/Chan/Audit/Math/Counter.lean": """module
public import Chan.Defs.Spec
public section
theorem counterexample : Premise 0 ∧ ¬ Concl 0 := ⟨rfl, by decide⟩
""",
            "formal_math/Chan/Thm/UseClass.lean": """module
public import Chan.Defs.Spec
public section
theorem with_pos [Pos 2] (n : Nat) : 0 < n + 2 := Nat.succ_pos _
theorem with_proj (w : PredWrap) (n : Nat) (h : w.1 n) : w.1 n := h
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "with_pos": {"about": [], "mode": "对任意实现成立"},
                    "with_proj": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["2", "3", "S"],
        False,
        True,
    ),

    # --- B4: Locked Chan/Defs alias bypassing S, 8a, 8b, 9 ---
    (
        "B4_locked_alias_bypass",
        {
            "formal_math/Chan/Defs/Alias.lean": """module
@[expose] public section
def LockedWrap (P : Prop) : Prop := P
""",
            "formal_math/Chan/Thm/UseAlias.lean": """module
public import Chan.Defs.Alias
public section
theorem vac_locked : LockedWrap (∀ x : Nat, x = 0 → x = 1 → False) :=
  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Thm.UseAlias
public section
theorem vac_locked.witness : True := trivial
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "vac_locked": {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [], "convenience": {}}
                }
            }),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9"],
        False,
        True,
    ),

    # --- C2: Gate 7a functional predicate refinement ---
    (
        "C2_g7a_func_pred_ref",
        {
            "formal_math/Chan/Defs/FuncPred.lean": """module
@[expose] public section
structure BarSeq where
  bars : List Nat
  isPivot : Nat → Prop
  spec : ∀ i, isPivot i ↔ i < bars.length
end
public section
theorem barSeq_ref_pointwise (s : BarSeq) (i : Nat) : s.isPivot i ↔ i < s.bars.length := s.spec i
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Defs.FuncPred
public section
def barSeq_w : BarSeq := ⟨[1], fun i => i < 1, fun _ => Iff.rfl⟩
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {},
                "refinements": {"BarSeq": "barSeq_ref_pointwise"},
            }),
        },
        ["7a"],
        False,
        True,
    ),

    # --- E3: Gate 8b README truthfulness & non-FP on real proofs ---
    (
        "E3_g8b_real_and_limits",
        {
            "formal_math/Chan/Thm/G8bProbe.lean": """module
public section
theorem uses_h_omega (a b : Nat) (h : a < b) : a ≤ b := by omega
theorem dead_prod_fst (x : Nat) (h : x ≠ 0) : x + 0 = x := Prod.fst (rfl, h)
theorem dead_dot1 (x : Nat) (h : x ≠ 0) : x + 0 = x := (rfl, h).1
theorem dead_id (x : Nat) (h : x ≠ 0) : x + 0 = x := (id (fun (_ : x ≠ 0) => (rfl : x + 0 = x))) h
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    k: {"about": [], "mode": "对任意实现成立"}
                    for k in ["uses_h_omega", "dead_prod_fst", "dead_dot1", "dead_id"]
                }
            }),
        },
        ["8b"],
        False,
        True,
    ),

    # --- E4: Gate 9 dependent premise with necessary vs convenience ---
    (
        "E4_g9_dep_premise_nec",
        {
            "formal_math/Chan/Thm/DepPrem.lean": """module
public section
theorem dep_get (l : List Nat) (i : Nat) (h1 : i < l.length) (h2 : l[i] = 0) : l[i] + 1 = 1 := by
  simp [h2]
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Thm.DepPrem
public section
theorem dep_get.witness : ∃ (l : List Nat) (i : Nat) (h1 : i < l.length), l[i] = 0 :=
  ⟨[0], 0, by decide, rfl⟩
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "dep_get": {
                        "about": [],
                        "mode": "对任意实现成立",
                        "main_theorem": True,
                        "necessary": [1, 2],
                    }
                }
            }),
        },
        ["9"],
        False,
        True,
    ),

    # --- A2b: @[init] actually executing IO inside fm_audit source! ---
    (
        "A2b_init_exec_on_import",
        {
            "formal_math/Chan/Thm/InitMod.lean": """module
public meta import Lean
public section
public meta def runOnLoad : IO Unit := do
  IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-v3-review/init_pwned2.txt" "INIT_EXECUTED_IN_AUDIT"

@[init runOnLoad]
public meta def initTrigger : Unit := ()
""",
            "formal_math/Chan/Thm/Importer.lean": """module
public meta import Chan.Thm.InitMod
public section
def ok : Nat := 1
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "15"],
        False,
        True,
    ),

    # --- D1b: Gate 10 fake OfNat with nat_lit + isolated fakeLTNat/Rat ---
    (
        "D1b_g10_isolated_bypasses",
        {
            "formal_math/Chan/Defs/BadDivClean.lean": """module
@[expose] public section
def fakeLTNat (a b : Nat) : Nat :=
  let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeLTRat (a b : Rat) : Rat :=
  let _h : @LT.lt Rat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeOneInt (a : Int) : Int :=
  a / @OfNat.ofNat Int (nat_lit 1) ⟨0⟩

def fakeOneRat (a : Rat) : Rat :=
  a / @OfNat.ofNat Rat (nat_lit 1) ⟨0⟩

def fakeZeroGuard (a b : Int) (_h : b ≠ @OfNat.ofNat Int (nat_lit 0) ⟨1⟩) : Int :=
  a / b

def junkDivInt (a b : Int) : Rat := Rat.divInt a b
def junkMkRat (a : Int) (b : Nat) : Rat := mkRat a b
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
        True,
    ),

    # --- A8: Mathlib W3 checks (open scoped, Filter, RelHom, headI, generic ordered Field div) ---
    (
        "A8_mathlib_w3_checks",
        {
            "formal_math/Chan/Defs/MathlibDefs.lean": """module
public import Mathlib.Algebra.Order.Field.Basic
public import Mathlib.Data.List.Basic
@[expose] public section
def genericPosDiv {K : Type} [Field K] [LinearOrder K] (a b : K) (_h : 0 < b) : K := a / b
def genericLitDiv {K : Type} [Field K] [LinearOrder K] (a : K) : K := a / 2
def listHeadI (l : List Nat) : Nat := l.headI
""",
            "formal_math/Chan/Thm/MathlibThm.lean": """module
public import Mathlib.Order.Filter.AtTopBot.Defs
public import Mathlib.Order.RelIso.Basic
public section
open scoped Classical
theorem ev_thm (p : Nat → Prop) (h : ∀ n, p n) : ∀ᶠ n in Filter.atTop, p n :=
  Filter.Eventually.of_forall h
theorem rel_hom_thm (r : Nat → Nat → Prop) (f : RelHom r r) (a b : Nat) (h : r a b) : r (f a) (f b) :=
  f.map_rel' h
theorem rel_emb_thm (r : Nat → Nat → Prop) (f : RelEmbedding r r) (a b : Nat) (h : r a b) : r (f a) (f b) :=
  f.map_rel_iff.mpr h
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "ev_thm": {"about": [], "mode": "对任意实现成立"},
                    "rel_hom_thm": {"about": [], "mode": "对任意实现成立"},
                    "rel_emb_thm": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["2", "3", "S", "10"],
        True,
        True,
    ),

    # --- A8b: Mathlib lemma command ---
    (
        "A8b_mathlib_lemma",
        {
            "formal_math/Chan/Thm/LemmaTest.lean": """module
public import Mathlib.Tactic.Lemma
public section
lemma triv_lemma (n : Nat) : n = n := rfl
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "triv_lemma": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["2", "3"],
        True,
        True,
    ),
]


def main():
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    for args in CASES:
        try:
            r = run_case(*args)
            results.append(r)
        except Exception as exc:
            print(f"EXCEPTION in {args[0]}: {exc}", flush=True)
            results.append({"name": args[0], "error": str(exc)})
            if "Root disk free" in str(exc):
                break
    (OUT_ROOT / "batch2.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
