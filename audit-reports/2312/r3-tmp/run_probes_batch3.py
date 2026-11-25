"""Batch 3 probes: macro nuclear bypass, fixed B3c Gate S FPs, grind set_option, E3b 8b, fresh BLOCK repros."""
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


def copy_template(tpl_dir: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(tpl_dir, dst, symlinks=True)


def run_case(name: str, files: dict[str, str], gates: list[str], fresh: bool = False):
    print(f"\n=== CASE {name} (fresh={fresh}) ===", flush=True)
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
        copy_template(TEMPLATE_NO_MATHLIB, repo)
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
    # --- A1d: @[macro] NUCLEAR BYPASS of Gates 2, 3 (src+env!), S, 7a, 8a, 8b, 9, 15 ---
    (
        "A1d_macro_nuclear_bypass",
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
    mkA "false"
  ]
  let defCmd ← `(public def hiddenUnused (x : Nat) : Nat := 0)
  let inCmd1 := Syntax.node .none `Lean.Parser.Command.in #[opt1, mkA "in", defCmd]

  let opt2 := Syntax.node .none `Lean.Parser.Command.set_option #[
    mkA ("set_" ++ "option"),
    mkIdent `autoImplicit,
    mkA "true"
  ]
  let impCmd ← `(public def hiddenAutoImp (x : α) : α := x)
  let inCmd2 := Syntax.node .none `Lean.Parser.Command.in #[opt2, mkA "in", impCmd]

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
        True,
    ),

    # --- B3c: Fixed Gate S false positives on Chan/Audit counterexample, [Pos 2], w.1 ---
    (
        "B3c_gateS_audit_class_proj_fp",
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
theorem counterexample : Premise 0 ∧ ¬ Concl 0 := ⟨rfl, fun h => Nat.noConfusion h⟩
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
    ),

    # --- B3d: Chan/Smoke.lean theorem shape placed in Chan/Thm ---
    (
        "B3d_smoke_in_thm_gateS",
        {
            "formal_math/Chan/Thm/SmokeLike.lean": """module
public section
def sample : List Nat := [10, 20, 5]
theorem sample_bounds : 20 ∈ sample ∧ 99 ∉ sample := by decide
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {"sample_bounds": {"about": [], "mode": "对任意实现成立"}}
            }),
        },
        ["2", "3", "S"],
        False,
    ),

    # --- A5c: grind set_option suppressing debug.skipKernelTC / linter ---
    (
        "A5c_grind_skip_kernel_opt",
        {
            "formal_math/Chan/Thm/GrindKernel.lean": """module
public section
theorem t (x : Nat) : x = x := by
  grind =>
    set_option debug.skipKernelTC true in
    set_option linter.unusedVariables false in
    skip
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {"t": {"about": [], "mode": "对任意实现成立"}}
            }),
        },
        ["2", "3"],
        False,
    ),

    # --- E3b: Fixed Gate 8b real proofs & README truthfulness (PProd, id, omega) ---
    (
        "E3b_g8b_real_and_limits",
        {
            "formal_math/Chan/Thm/G8bProbe.lean": """module
public section
theorem uses_h_omega (a b : Nat) (h : a < b) : a ≤ b := by omega
theorem dead_pprod_fst (x : Nat) (h : x ≠ 0) : x + 0 = x := PProd.fst ⟨rfl, h⟩
theorem dead_pprod_dot1 (x : Nat) (h : x ≠ 0) : x + 0 = x := (PProd.mk (rfl : x + 0 = x) h).1
theorem dead_id (x : Nat) (h : x ≠ 0) : x + 0 = x := (id (fun (_ : x ≠ 0) => (rfl : x + 0 = x))) h
""",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    k: {"about": [], "mode": "对任意实现成立"}
                    for k in ["uses_h_omega", "dead_pprod_fst", "dead_pprod_dot1", "dead_id"]
                }
            }),
        },
        ["8b"],
        False,
    ),

    # --- A4c: Clean fresh-base_package verification of #guard_msgs broken in Chan/Final ---
    (
        "A4c_guard_msgs_legal_fresh",
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
        True,
    ),

    # --- D3: Gate 10 crash on ANY class parameter (no Mathlib needed!) + List.head! vs headI ---
    (
        "D3_g10_typeclass_mkAppM_crash",
        {
            "formal_math/Chan/Defs/ClassDiv.lean": """module
@[expose] public section
def divWithClass {α : Type} [Div α] [LT α] [OfNat α 0] (a b : α) (_h : 0 < b) : α := a / b
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
    ),

    # --- D4: Gate 10 crash on guarded Rat/Nat div when an unrelated [Inhabited α] class is in scope! ---
    (
        "D4_g10_any_class_in_scope_crash",
        {
            "formal_math/Chan/Defs/ClassScope.lean": """module
@[expose] public section
def divSignedWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b
""",
            "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
        },
        ["2", "3", "10"],
        False,
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
    (OUT_ROOT / "batch3.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
