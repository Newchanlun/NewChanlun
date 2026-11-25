"""Batch 1 adversarial & false-positive probes for #2312 v3 review (serial, disk-guarded)."""
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
    (dummy_fx / "formal_math/Chan/Defs").mkdir(parents=True)
    (dummy_fx / "formal_math/Chan/Hypotheses").mkdir(parents=True)
    (dummy_fx / "formal_math/Chan/Thm").mkdir(parents=True)
    (dummy_fx / "formal_math/Chan/Exec").mkdir(parents=True)
    (dummy_fx / "formal_math/Chan/Final").mkdir(parents=True)
    (dummy_fx / "formal_math/Chan/Audit/Math").mkdir(parents=True)
    (dummy_fx / "formal_math/ChanTest").mkdir(parents=True)
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
    # Save text fixture permanently in CASES_DIR
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
            # Build all Chan* and ChanTest* lean files discovered
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
                print(f"    build out: {(b.stdout + b.stderr).strip()[:600]}", flush=True)
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
            print(f"  gate {g}: rc={p.returncode} stdout={p.stdout.strip()[:240]!r} stderr={p.stderr.strip()[:200]!r}", flush=True)
    finally:
        if repo.exists():
            shutil.rmtree(repo)
        check_disk(f"after {name}")
    return res


CASES = [
    # --- GROUP E1: CRITICAL TEST OF GATE 8a FALSE POSITIVE (isDefEq v a without type check!) ---
    (
        "E1_g8a_syllogism_fp",
        {
            "formal_math/Chan/Thm/Legit.lean": """module
public section
theorem syllogism (P Q R : Prop) (h1 : P → Q) (h2 : Q → R) (hp : P) : R :=
  h2 (h1 hp)

theorem lt_chain (Q : Nat → Prop) (h : ∀ n : Nat, 5 < n → Q n) (k : Nat) (h10 : 10 < k) : Q k :=
  h k (Nat.lt_trans (by decide : 5 < 10) h10)

theorem succ_step (Q : Nat → Prop) (h : ∀ n : Nat, 0 < n → Q n) (k : Nat) : Q (k + 1) :=
  h (k + 1) (Nat.succ_pos k)
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "syllogism": {"about": [], "mode": "对任意实现成立"},
                    "lt_chain": {"about": [], "mode": "对任意实现成立"},
                    "succ_step": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["8a"],
        False,
        True,
    ),

    # --- GROUP A1: GATE 2 & 3 BYPASS VIA @[macro] + synthetic syntax (no decl range!) ---
    (
        "A1_macro_bypass",
        {
            "formal_math/Chan/Thm/Helper.lean": """module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let opt1 := mkIdent `linter.unusedVariables
  let f := mkIdent `false
  let id1 := mkIdent `hiddenUnused
  let id2 := mkIdent `hiddenPartial
  let id3 := mkIdent `hiddenUnsafe
  let id4 := mkIdent `hiddenVacuous
  let opt2 := mkIdent `autoImplicit
  let t := mkIdent `true
  let id5 := mkIdent `hiddenAutoImp
  let stx1 ← `(set_option $opt1 $f in public def $id1 (x : Nat) : Nat := 0)
  let stx2 ← `(set_option $opt2 $t in public def $id5 (x : α) : α := x)
  let stx3 ← `(public partial def $id2 (n : Nat) : Nat := $id2 n)
  let stx4 ← `(public unsafe def $id3 : Nat := 0)
  let stx5 ← `(public theorem $id4 (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))
  return mkNullNode #[stx1, stx2, stx3, stx4, stx5]
""",
            "formal_math/Chan/Thm/Victim.lean": """module
public import Chan.Thm.Helper
public section
#check Nat
def callPartial : Nat := hiddenPartial 0
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9", "15"],
        False,
        True,
    ),

    # --- GROUP A1b: @[macro] constructing raw Syntax without forbidden tokens in Helper ---
    (
        "A1b_macro_clean_syntax",
        {
            "formal_math/Chan/Thm/Helper.lean": """module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let opt := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent (Name.mkStr2 "linter" "unusedVariables"),
    mkIdent `false
  ]
  let defCmd ← `(public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd := Syntax.node .none `Lean.Parser.Command.in #[opt, mkA "in", defCmd]
  let vacCmd ← `(public theorem hiddenVacuous (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))
  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let declMods := Syntax.node .none `Lean.Parser.Command.declModifiers #[
    mkNullNode, mkNullNode,
    mkNullNode #[Syntax.node .none `Lean.Parser.Command.visibility #[mkA "public"]],
    mkNullNode, mkNullNode, mkNullNode #[partMod], mkNullNode
  ]
  let partDef ← `(def hiddenPartial (n : Nat) : Nat := hiddenPartial n)
  let partDecl := Syntax.node .none `Lean.Parser.Command.declaration #[declMods, partDef[1]]
  return mkNullNode #[inCmd, vacCmd, partDecl]
""",
            "formal_math/Chan/Thm/Victim.lean": """module
public import Chan.Thm.Helper
public section
#check Nat
def useHidden : Nat := hiddenUnused 1 + hiddenPartial 0
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9", "15"],
        False,
        True,
    ),

    # --- GROUP A2: @[init] arbitrary IO execution during Gate 3 ---
    (
        "A2_init_attr",
        {
            "formal_math/Chan/Thm/InitProbe.lean": """module
public section
def runOnLoad : IO Unit := do
  IO.FS.writeFile "/Volumes/AgentStorage/fm/tmp/2312-v3-review/init_pwned.txt" "INIT_RAN"

@[init runOnLoad]
def initTrigger : Unit := ()
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "15"],
        False,
        True,
    ),

    # --- GROUP A4: #guard_msgs in Chan/Final child index check ---
    (
        "A4_guard_msgs_index",
        {
            "formal_math/Chan/Final/GuardProbe.lean": """module
public section
#guard_msgs (drop all) in
#eval 1 + 1
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- GROUP A7: Legal W3 commands / syntax false positives in Gate 2/3/15/7a/9 ---
    (
        "A7_legal_w3_omit",
        {
            "formal_math/Chan/Thm/OmitTest.lean": """module
public section
section
variable (x y : Nat) (h : x = y)
include h
theorem t1 : y = x := h.symm
omit h in
theorem t2 : x = x := rfl
end
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "t1": {"about": [], "mode": "对任意实现成立"},
                    "t2": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["2", "3", "S"],
        False,
        True,
    ),
    (
        "A7_legal_w3_noncomputable_section",
        {
            "formal_math/Chan/Thm/NoncompSec.lean": """module
public section
noncomputable section
def chooseNat : Nat := Classical.choice ⟨0⟩
end
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),
    (
        "A7_legal_w3_open_scoped_and_attr",
        {
            "formal_math/Chan/Thm/ScopedTest.lean": """module
public section
namespace Foo
scoped instance : Inhabited Unit := ⟨()⟩
end Foo
open scoped Foo
@[simp] theorem trivEq (x : Nat) : x + 0 = x := rfl
def f (x : Nat) : Nat := x
attribute [simp] f
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),
    (
        "A7_legal_w3_open_scoped_only",
        {
            "formal_math/Chan/Thm/ScopedOnly.lean": """module
public section
namespace Foo
def a : Nat := 1
end Foo
open scoped Foo
@[simp] theorem trivEq (x : Nat) : x + 0 = x := rfl
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),
    (
        "A7_legal_w3_named_expose_section",
        {
            "formal_math/Chan/Defs/NamedExpose.lean": """module
@[expose] public section MySec
def bar : Nat := 1
end MySec
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "15"],
        False,
        True,
    ),
    (
        "A7_legal_w3_struct_extends",
        {
            "formal_math/Chan/Exec/Extends.lean": """module
public section
structure Base where
  n : Nat
  ok : 0 < n
structure Child extends Base where
  m : Nat
def mkChild : Child := ⟨⟨1, by decide⟩, 2⟩
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "9"],
        False,
        True,
    ),
    (
        "A7_legal_w3_default_prop_field",
        {
            "formal_math/Chan/Exec/DefProp.lean": """module
public section
structure WithDef where
  n : Nat
  ok : n = n := rfl
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "S", "7a", "9"],
        False,
        True,
    ),
    (
        "A7_legal_w3_tactic_var",
        {
            "formal_math/Chan/Thm/TacVar.lean": """module
public section
def score (tactic : Nat) : Nat := tactic + 1
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3"],
        False,
        True,
    ),

    # --- GROUP B1: GATE S + 7a + 8a + 8b + 9 BYPASSES VIA CONNECTIVES & PROP ATOMS ---
    (
        "B1_gateS_connective_bypasses",
        {
            "formal_math/Chan/Thm/Wrap.lean": """module
public section
theorem vac_and (x : Nat) : (x = x) ∧ (x = 0 → x = 1 → False) :=
  ⟨rfl, fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem mirror_and (P : Nat → Prop) (k : Nat) : (k = k) ∧ ((∀ n, P n) → P k) :=
  ⟨rfl, fun h => h k⟩

theorem unused_and (x : Nat) : (x = x) ∧ (x = 0 → x + 0 = x) :=
  ⟨rfl, fun _ => rfl⟩

theorem vac_or : False ∨ (∀ x : Nat, x = 0 → x = 1 → False) :=
  Or.inr (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_iff : True ↔ (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1), fun _ => trivial⟩

theorem vac_notnot : ¬ ¬ (∀ x : Nat, x = 0 → x = 1 → False) :=
  fun h => h (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_exists : ∃ _ : Nat, ∀ x : Nat, x = 0 → x = 1 → False :=
  ⟨0, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Thm.Wrap
public section
theorem vac_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem mirror_and.witness : ∃ (_P : Nat → Prop) (_k : Nat), True := ⟨fun _ => True, 0, trivial⟩
theorem unused_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem vac_or.witness : True := trivial
theorem vac_iff.witness : True := trivial
theorem vac_notnot.witness : True := trivial
theorem vac_exists.witness : True := trivial
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    k: {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [], "convenience": {}}
                    for k in ["vac_and", "mirror_and", "unused_and", "vac_or", "vac_iff", "vac_notnot", "vac_exists"]
                }
            }),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9"],
        False,
        True,
    ),

    (
        "B2_gateS_atom_wrappers",
        {
            "formal_math/Chan/Thm/AtomWrap.lean": """module
public section
inductive WrapInd (P : Prop) : Prop where
  | mk : P → WrapInd P

structure WrapBox (n : Nat) : Prop where
  claim : n = 0 → n = 1 → False

theorem vac_eq : (∀ x : Nat, x = 0 → x = 1 → False) = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_heq : HEq (∀ x : Nat, x = 0 → x = 1 → False) True :=
  heq_of_eq vac_eq

theorem vac_nonempty : Nonempty (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_sub : Nonempty { _u : Unit // ∀ x : Nat, x = 0 → x = 1 → False } :=
  ⟨⟨(), fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩⟩

theorem vac_dec : decide (∀ x : Fin 5, x.val = 0 → x.val = 1 → False) = true := by
  decide

theorem vac_ind : WrapInd (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_box (n : Nat) : WrapBox n :=
  ⟨fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_hidden_getd : Option.getD (some (∀ x : Nat, x = 0 → x = 1 → False)) True = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_fvar (W : Prop → Prop) (h : W = id) : W (∀ x : Nat, x = 0 → x = 1 → False) :=
  h ▸ (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))

theorem vac_iff_var (P : Prop) (h : P ↔ (∀ x : Nat, x = 0 → x = 1 → False)) : P :=
  h.mpr (fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1))
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Thm.AtomWrap
public section
theorem vac_eq.witness : True := trivial
theorem vac_heq.witness : True := trivial
theorem vac_nonempty.witness : True := trivial
theorem vac_sub.witness : True := trivial
theorem vac_dec.witness : True := trivial
theorem vac_ind.witness : True := trivial
theorem vac_box.witness : ∃ _n : Nat, True := ⟨0, trivial⟩
theorem vac_hidden_getd.witness : True := trivial
theorem vac_fvar.witness : ∃ W : Prop → Prop, W = id := ⟨id, rfl⟩
theorem vac_fvar.without_1 : ∃ W : Prop → Prop, ¬ W (∀ x : Nat, x = 0 → x = 1 → False) := ⟨fun _ => False, id⟩
theorem vac_iff_var.witness : ∃ P : Prop, P ↔ (∀ x : Nat, x = 0 → x = 1 → False) := ⟨_, Iff.rfl⟩
theorem vac_iff_var.without_1 : ∃ P : Prop, ¬ P := ⟨False, id⟩
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    **{
                        k: {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [], "convenience": {}}
                        for k in ["vac_eq", "vac_heq", "vac_nonempty", "vac_sub", "vac_dec", "vac_ind", "vac_box", "vac_hidden_getd"]
                    },
                    "vac_fvar": {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [1], "convenience": {}},
                    "vac_iff_var": {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [1], "convenience": {}},
                }
            }),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9"],
        False,
        True,
    ),

    # --- GROUP B3: GATE S FALSE POSITIVES ON LEGAL REAL CODE ---
    (
        "B3_gateS_false_positives",
        {
            "formal_math/Chan/Defs/Model.lean": """module
@[expose] public section
def price (n : Nat) : Nat := n + 1
""",
            "formal_math/Chan/Hypotheses/Market.lean": """module
public import Chan.Defs.Model
@[expose] public section
def PositivePrices : Prop := ∀ n : Nat, 0 < price n
structure GlobalMarket : Prop where
  pos : ∀ n : Nat, 0 < price n
""",
            "formal_math/Chan/Thm/Normal.lean": """module
public import Chan.Hypotheses.Market
public section
theorem use_named_hyp (h : PositivePrices) (k : Nat) : 0 < price k := h k
theorem use_inline_hyp (h : ∀ n : Nat, 0 < price n) (k : Nat) : 0 < price k := h k
theorem concrete_conj : price 0 = 1 ∧ price 1 = 2 := ⟨rfl, rfl⟩
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "use_named_hyp": {"about": [], "mode": "对任意实现成立"},
                    "use_inline_hyp": {"about": [], "mode": "对任意实现成立"},
                    "concrete_conj": {"about": [], "mode": "对任意实现成立"},
                }
            }),
        },
        ["2", "3", "S"],
        False,
        True,
    ),

    # --- GROUP C1: GATE 7a VACUOUS REFINEMENT BYPASS (no Prop field -> skips resident!) ---
    (
        "C1_g7a_vacuous_subtype_bypass",
        {
            "formal_math/Chan/Defs/VacStruct.lean": """module
@[expose] public section
structure VacSub where
  raw : { _n : Nat // False }
  flag : Bool

structure VacEmpty where
  raw : Empty
  flag : Bool

structure VacFin where
  raw : Fin 0
  flag : Bool
end
public section
theorem vacSub_ref (e : VacSub) : e.flag = (fun _ : { _n : Nat // False } => false) e.raw :=
  False.elim e.raw.property

theorem vacEmpty_ref (e : VacEmpty) : e.flag = (fun _ : Empty => false) e.raw :=
  Empty.elim e.raw

theorem vacFin_ref (e : VacFin) : e.flag = (fun _ : Fin 0 => false) e.raw :=
  Fin.elim0 e.raw
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {},
                "refinements": {
                    "VacSub": "vacSub_ref",
                    "VacEmpty": "vacEmpty_ref",
                    "VacFin": "vacFin_ref",
                },
            }),
        },
        ["2", "3", "S", "7a", "9"],
        False,
        True,
    ),

    # --- GROUP D1: GATE 10 HARD BYPASSES ---
    (
        "D1_g10_bypasses",
        {
            "formal_math/Chan/Defs/BadDiv.lean": """module
@[expose] public section
def fakeLTNat (a b : Nat) : Nat :=
  let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeLTRat (a b : Rat) : Rat :=
  let _h : @LT.lt Rat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeOneInt (a : Int) : Int :=
  a / @OfNat.ofNat Int 1 ⟨0⟩

def fakeOneRat (a : Rat) : Rat :=
  a / @OfNat.ofNat Rat 1 ⟨0⟩

def fakeZeroGuard (a b : Int) (_h : b ≠ @OfNat.ofNat Int 0 ⟨1⟩) : Int :=
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

    # --- GROUP D2: GATE 10 LEGAL GUARDED DIVS ---
    (
        "D2_g10_legal_guards",
        {
            "formal_math/Chan/Defs/GoodDiv.lean": """module
@[expose] public section
def gtInt (a b : Int) (_h : b > 0) : Int := a / b
def gtRat (a b : Rat) (_h : b > 0) : Rat := a / b
def negInt (a b : Int) (_h : b < 0) : Int := a / b
def invGuarded (b : Rat) (_h : 0 < b) : Rat := b⁻¹
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
        True,
    ),

    # --- GROUP E2: GATE 7b EDGE CASE (helper hides PullbackInd) ---
    (
        "E2_g7b_hyp_helper",
        {
            "formal_math/Chan/Defs/Fixture.lean": """module
@[expose] public section
def D (n : Nat) : Nat := n + 1
""",
            "formal_math/Chan/Hypotheses/Fixture.lean": """module
public import Chan.Defs.Fixture
@[expose] public section
inductive PullbackInd (n : Nat) : Prop where
  | mk : D n = 1 → PullbackInd n
  | other : D n = 1 → PullbackInd n

def PullbackAlias (n : Nat) : Prop := PullbackInd n

theorem extractPullback {n : Nat} (h : PullbackAlias n) : D n = 1 := by
  cases h with
  | mk e => exact e
  | other e => exact e
""",
            "formal_math/Chan/Thm/Fixture.lean": """module
public import Chan.Hypotheses.Fixture
public section
theorem claim (h : PullbackAlias 0) : D 0 = 1 := extractPullback h
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "claim": {
                        "about": ["D"],
                        "mode": "依赖具体定义",
                    }
                }
            }),
        },
        ["7b"],
        False,
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
    (OUT_ROOT / "batch1.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    pwn = OUT_ROOT / "init_pwned.txt"
    print(f"\ninit_pwned.txt exists = {pwn.exists()}", flush=True)
    if pwn.exists():
        print(f"init_pwned.txt content = {pwn.read_text()!r}", flush=True)


if __name__ == "__main__":
    main()
