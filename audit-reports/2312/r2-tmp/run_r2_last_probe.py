"""检验 statementHead 非项目不可约包装 (Option.getD / Function.const) 击穿门 8a/8b/9，以及 Mathlib Inv.inv 测门 10。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_last_sandbox")
PKG_LINK = (WT / "formal_math/.lake/packages").resolve()

ENV = os.environ.copy()
ENV["TMPDIR"] = "/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp"
ENV["PATH"] = f"{Path.home() / '.elan/bin'}:{ENV.get('PATH', '')}"
ENV.pop("GITHUB_HEAD_REF", None)


def make_clean_pkg(repo: Path, files: dict[str, str], uses_mathlib=False):
    if repo.exists():
        shutil.rmtree(repo)
    fm = repo / "formal_math"
    vdir = fm / "verification"
    vdir.mkdir(parents=True)
    for fn in ("run_gates.py", "pins.json", "Audit.lean", "EnvGates.lean", "garbage-signoffs.yaml"):
        shutil.copy2(VER / fn, vdir)
    for fn in ("lean-toolchain", "lake-manifest.json", "formalization.yaml", "statement-lock.json"):
        shutil.copy2(WT / "formal_math" / fn, fm)
    (fm / "ChanTest").mkdir()
    shutil.copy2(WT / "formal_math/ChanTest/Probe.lean", fm / "ChanTest/Probe.lean")
    (fm / "Chan.lean").write_text("module\n")
    (fm / "Chan").mkdir()
    if uses_mathlib:
        (fm / ".lake").mkdir(exist_ok=True)
        (fm / ".lake/packages").symlink_to(PKG_LINK)
    (fm / "lakefile.toml").write_text(
        'name = "lastr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n'
        + ('\n[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4.git"\n'
           'rev = "v4.36.0"\n' if uses_mathlib else "")
        + '\n[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        + '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n\n'
        + '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\n\n'
        + '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates"]\n'
    )
    for rel, content in files.items():
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)


def run_gate(repo: Path, gate: str):
    return subprocess.run(
        [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
         "--repo-root", str(repo), "--gate", gate],
        cwd=repo, env=ENV, capture_output=True, text=True, check=False, timeout=300,
    )


def run_build(repo: Path, *extra_args):
    return subprocess.run(
        ["lake", "build", *extra_args],
        cwd=repo / "formal_math", env=ENV, capture_output=True, text=True, check=False, timeout=300,
    )


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)

    # 1. Option.getD / Function.const wrapping vacuous/mirror/bsp statements -> bypass 8a, 8b, 9!
    r = BASE_TMP / "opt_getd_wrap"
    make_clean_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem mirror_getd : Option.getD (some (∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x)) True :=\n"
            "  fun _ h x => h x\n"
            "theorem bsp_getd : Option.getD (some (∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side)) True :=\n"
            "  fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩\n"
            "theorem vac_getd : Option.getD (some (∀ (x : Nat), x = 0 → x = 1 → False)) True :=\n"
            "  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
            "theorem vac_const : Function.const Unit (∀ (x : Nat), x = 0 → x = 1 → False) () :=\n"
            "  fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)\n"
        ),
        "formal_math/ChanTest/Evidence.lean": (
            "module\npublic section\n"
            "theorem mirror_getd.witness : True := trivial\n"
            "theorem bsp_getd.witness : True := trivial\n"
            "theorem vac_getd.witness : True := trivial\n"
            "theorem vac_const.witness : True := trivial\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "mirror_getd": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "bsp_getd": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "vac_getd": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
                "vac_const": {"about": [], "mode": "对任意实现成立", "needs_necessity": True},
            }
        }),
    })
    b = run_build(r, "--wfail")
    print(f"[L1-build] rc={b.returncode}", flush=True)
    if b.returncode != 0:
        print(b.stdout + b.stderr, flush=True)
    for g in ("7a", "8a", "8b", "9"):
        res = run_gate(r, g)
        print(f"[L1-g{g}] rc={res.returncode} out={res.stdout.strip()}", flush=True)

    # 2. Mathlib Inv.inv (y⁻¹) in gate 10
    r = BASE_TMP / "mathlib_inv"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Mathlib.Algebra.Field.Defs\n@[expose] public section\n"
            "def invField {K : Type} [Field K] (y : K) : K := y⁻¹\n"
            "def divViaInv {K : Type} [Field K] (x y : K) : K := x * y⁻¹\n"
        ),
    }, uses_mathlib=True)
    b = run_build(r, "--wfail")
    res = run_gate(r, "10")
    print(f"[L2-invField-build] rc={b.returncode}", flush=True)
    print(f"[L2-invField-g10] rc={res.returncode} out={res.stdout.strip()}", flush=True)


if __name__ == "__main__":
    main()
