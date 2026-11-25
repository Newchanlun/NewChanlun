"""Batch 4: Nuclear @[macro] v2 (fresh), Mathlib List.headI isolated, M1/M2 checks, and fresh BLOCK confirmations."""
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


def run_case(name: str, files: dict[str, str], gates: list[str], uses_mathlib: bool = False, fresh: bool = True):
    print(f"\n=== CASE {name} (mathlib={uses_mathlib}, fresh={fresh}) ===", flush=True)
    check_disk(f"before {name}")
    case_dir = CASES_DIR / name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for rel, content in files.items():
        p = case_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    repo = SCRATCH_ROOT / f"run_{name}"
    if repo.exists():
        shutil.rmtree(repo)
    if fresh:
        repo.mkdir(parents=True)
        selftest.base_package(repo, case_dir)
    else:
        shutil.copytree(TEMPLATE_MATHLIB, repo, symlinks=True)
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    env = make_env(repo / "tmp")
    res = {"name": name, "gates": {}}
    try:
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
    # --- A1e: @[macro] NUCLEAR BYPASS v2 (100% fresh selftest.base_package!) ---
    (
        "A1e_macro_nuclear_fresh",
        {
            "formal_math/Chan/Thm/Helper.lean": """module
public meta import Lean
public section
open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let baseOpt1 ← `(set_option pp.all false in public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd1 := baseOpt1.raw.setArg 0 (baseOpt1.raw[0]!.setArg 1 (mkIdent (Name.mkStr2 "linter" "unusedVariables")))

  let baseOpt2 ← `(set_option pp.all true in public def hiddenAutoImp (x : α) : α := x)
  let inCmd2 := baseOpt2.raw.setArg 0 (baseOpt2.raw[0]!.setArg 1 (mkIdent `autoImplicit))

  let vacCmd ← `(public theorem hiddenVacuous (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))

  let partBase ← `(public def hiddenPartial (n : Nat) : Nat := hiddenPartial n)
  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let partDecl := partBase.raw.setArg 0 (partBase.raw[0]!.setArg 6 (mkNullNode #[partMod]))

  let unsafeBase ← `(public def hiddenUnsafe : Nat := 0)
  let unsafeMod := Syntax.node .none `Lean.Parser.Command.unsafe #[mkA ("un" ++ "safe")]
  let unsafeDecl := unsafeBase.raw.setArg 0 (unsafeBase.raw[0]!.setArg 5 (mkNullNode #[unsafeMod]))

  let fakeImplCmd ← `(public def fakeImpl : Nat := 999)
  let implName := Name.mkSimple ("implemented_" ++ "by")
  let attrSimple := Syntax.node .none `Lean.Parser.Attr.simple #[mkIdent implName, mkNullNode #[mkIdent `fakeImpl]]
  let attrInst := Syntax.node .none `Lean.Parser.Term.attrInstance #[mkNullNode, attrSimple]
  let attrs := Syntax.node .none `Lean.Parser.Term.attributes #[mkA "@[", mkNullNode #[attrInst], mkA "]"]
  let implBase ← `(public def hiddenImplBy : Nat := 1)
  let implDecl := implBase.raw.setArg 0 (implBase.raw[0]!.setArg 1 (mkNullNode #[attrs]))

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

    # --- D5: Mathlib List.headI / List.getLastI / Option.iget isolated in Gate 10 ---
    (
        "D5_g10_mathlib_headI",
        {
            "formal_math/Chan/Defs/HeadI.lean": """module
public import Mathlib.Data.List.Basic
@[expose] public section
def listHeadI (l : List Nat) : Nat := l.headI
def listGetLastI (l : List Nat) : Nat := l.getLastI
def optIget (o : Option Nat) : Nat := o.iget
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        True,
        False,
    ),

    # --- Fresh verification of B1/B2/C1/D1b/D3/E2 ---
    (
        "F_B1_B2_gateS_fresh",
        {
            "formal_math/Chan/Thm/WrapFresh.lean": """module
public section
inductive WrapInd (P : Prop) : Prop where
  | mk : P → WrapInd P

theorem vac_and (x : Nat) : (x = x) ∧ (x = 0 → x = 1 → False) :=
  ⟨rfl, fun h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem mirror_and (P : Nat → Prop) (k : Nat) : (k = k) ∧ ((∀ n, P n) → P k) :=
  ⟨rfl, fun h => h k⟩

theorem unused_and (x : Nat) : (x = x) ∧ (x = 0 → x + 0 = x) :=
  ⟨rfl, fun _ => rfl⟩

theorem vac_iff : True ↔ (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1), fun _ => trivial⟩

theorem vac_eq : (∀ x : Nat, x = 0 → x = 1 → False) = True :=
  propext ⟨fun _ => trivial, fun _ _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_nonempty : Nonempty (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩

theorem vac_ind : WrapInd (∀ x : Nat, x = 0 → x = 1 → False) :=
  ⟨fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩
""",
            "formal_math/ChanTest/Evidence.lean": """module
public import Chan.Thm.WrapFresh
public section
theorem vac_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem mirror_and.witness : ∃ (_P : Nat → Prop) (_k : Nat), True := ⟨fun _ => True, 0, trivial⟩
theorem unused_and.witness : ∃ _x : Nat, True := ⟨0, trivial⟩
theorem vac_iff.witness : True := trivial
theorem vac_eq.witness : True := trivial
theorem vac_nonempty.witness : True := trivial
theorem vac_ind.witness : True := trivial
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    k: {"about": [], "mode": "对任意实现成立", "main_theorem": True, "necessary": [], "convenience": {}}
                    for k in ["vac_and", "mirror_and", "unused_and", "vac_iff", "vac_eq", "vac_nonempty", "vac_ind"]
                }
            }),
        },
        ["2", "3", "S", "7a", "8a", "8b", "9"],
        False,
        True,
    ),

    (
        "F_C1_g7a_vac_fresh",
        {
            "formal_math/Chan/Defs/VacFresh.lean": """module
@[expose] public section
structure VacSub where
  raw : { _n : Nat // False }
  flag : Bool
end
public section
theorem vacSub_ref (e : VacSub) : e.flag = (fun _ : { _n : Nat // False } => false) e.raw :=
  False.elim e.raw.property
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {},
                "refinements": {"VacSub": "vacSub_ref"},
            }),
        },
        ["2", "3", "S", "7a", "9"],
        False,
        True,
    ),

    (
        "F_D1_g10_bypass_fresh",
        {
            "formal_math/Chan/Defs/BadDivFresh.lean": """module
@[expose] public section
def fakeLTNat (a b : Nat) : Nat :=
  let _h : @LT.lt Nat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeLTRat (a b : Rat) : Rat :=
  let _h : @LT.lt Rat ⟨fun _ _ => True⟩ 0 b := trivial
  a / b

def fakeOneInt (a : Int) : Int :=
  a / @OfNat.ofNat Int (nat_lit 1) ⟨0⟩

def junkDivInt (a b : Int) : Rat := Rat.divInt a b
def junkMkRat (a : Int) (b : Nat) : Rat := mkRat a b
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
        True,
    ),

    (
        "F_D3_g10_class_crash_fresh",
        {
            "formal_math/Chan/Defs/ClassDivFresh.lean": """module
@[expose] public section
def divWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
        True,
    ),
]


def test_m1_gate1_manifest_path():
    print("\n=== CASE M1_g1_manifest_path ===", flush=True)
    check_disk("before M1")
    repo = SCRATCH_ROOT / "run_M1_g1"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    case_dir = CASES_DIR / "M1_g1_manifest_path"
    if case_dir.exists():
        shutil.rmtree(case_dir)
    (case_dir / "formal_math").mkdir(parents=True)
    selftest.base_package(repo, case_dir)
    mf_path = repo / "formal_math/lake-manifest.json"
    mf = json.loads(mf_path.read_text())
    for pkg in mf["packages"]:
        if pkg["name"] == "Cli":
            pkg["type"] = "path"
            pkg["dir"] = "../evil_pkg"
            pkg.pop("url", None)
    mf_text = json.dumps(mf, indent=2)
    mf_path.write_text(mf_text)
    (case_dir / "formal_math/lake-manifest.json").write_text(mf_text)
    env = make_env(repo / "tmp")
    p = subprocess.run(
        [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
         "--repo-root", str(repo), "--gate", "1"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=120,
    )
    print(f"  gate 1: rc={p.returncode} stdout={p.stdout.strip()!r} stderr={p.stderr.strip()!r}", flush=True)
    shutil.rmtree(repo)
    check_disk("after M1")
    return {"name": "M1_g1_manifest_path", "rc": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}


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
    try:
        results.append(test_m1_gate1_manifest_path())
    except Exception as exc:
        print(f"EXCEPTION in M1: {exc}", flush=True)
        results.append({"name": "M1_g1_manifest_path", "error": str(exc)})
    (OUT_ROOT / "batch4.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
