"""R2 补充边界核查：protected(带namespace)、自定义 instance/abbrev 未 expose、doc_only 精准性、gate6a 属性差异。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_extra_sandbox")

ENV = os.environ.copy()
ENV["TMPDIR"] = "/Volumes/AgentStorage/fm/r2/2312-r2-tmp/tmp"
ENV["PATH"] = f"{Path.home() / '.elan/bin'}:{ENV.get('PATH', '')}"
ENV.pop("GITHUB_HEAD_REF", None)


def make_clean_pkg(repo: Path, files: dict[str, str]):
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
    (fm / "lakefile.toml").write_text(
        'name = "extra"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nroots = ["ChanTest.Probe"]\nglobs = ["ChanTest.+"]\n\n'
        '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\n\n'
        '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates"]\n'
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


def lock_hashes(repo: Path, mods: list[str]):
    fm = repo / "formal_math"
    b = subprocess.run(["lake", "build", *(f"+{m}:olean" for m in mods)],
                       cwd=fm, env=ENV, capture_output=True, text=True, check=False, timeout=300)
    if b.returncode != 0:
        return None, b
    res = subprocess.run(["lake", "exe", "fm_audit", "6a", *mods],
                         cwd=fm, env=ENV, input="{}", capture_output=True, text=True, check=False, timeout=300)
    if res.returncode != 0:
        return None, res
    out = {}
    for line in res.stdout.splitlines():
        name, mod, stmt = json.loads(line)
        payload = json.dumps(stmt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        out[name] = (hashlib.sha256(payload).hexdigest(), stmt)
    return out, res


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)

    # 1. protected inside namespace (gate 6a)
    r1, r2 = BASE_TMP / "prot1", BASE_TMP / "prot2"
    make_clean_pkg(r1, {"formal_math/Chan/Defs/Fixture.lean": "module\n@[expose] public section\nnamespace N\ndef f (x : Nat) : Nat := x\nend N\n"})
    make_clean_pkg(r2, {"formal_math/Chan/Defs/Fixture.lean": "module\n@[expose] public section\nnamespace N\nprotected def f (x : Nat) : Nat := x\nend N\n"})
    h1, _ = lock_hashes(r1, ["ChanTest.Probe", "Chan.Defs.Fixture"])
    h2, _ = lock_hashes(r2, ["ChanTest.Probe", "Chan.Defs.Fixture"])
    print(f"[X1-protected-6a] same_hashes={ {k:v[0] for k,v in h1.items()} == {k:v[0] for k,v in h2.items()} } keys={sorted(h1.keys())}", flush=True)

    # 2. abbrev / instance unexposed in Chan/Defs + empty @[expose] (gate 15)
    r = BASE_TMP / "unexp_inst"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\npublic section\n"
            "structure MyNat where val : Nat\n"
            "instance : BEq MyNat where beq a b := a.val == b.val\n"
            "end\n@[expose] public section\nend\n"
        ),
        "formal_math/ChanTest/UseFlag.lean": (
            "module\npublic import Chan.Defs.Flag\npublic section\n"
            "example : (MyNat.mk 1 == MyNat.mk 1) = true := by decide\n"
        ),
    })
    b = run_build(r)
    g15 = run_gate(r, "15")
    print(f"[X2-unexp-inst] build_rc={b.returncode} g15_rc={g15.returncode}", flush=True)
    if b.stdout.strip():
        print("  BUILD OUT:", "\n  ".join(b.stdout.strip().splitlines()[-6:]), flush=True)
    if g15.stdout.strip():
        print("  G15 OUT:", g15.stdout.strip(), flush=True)

    # 3. doc_only partial exemption in gate 8b (exempt #1, #2 still droppable -> must be RED!)
    r = BASE_TMP / "doc_only_partial"
    make_clean_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem two_unused (_h1 : 1 = 1) (_h2 : 2 = 2) : True := trivial\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"two_unused": {"about": [], "mode": "对任意实现成立", "doc_only": {"1": "仅文档"}}}
        }),
    })
    g8b = run_gate(r, "8b")
    print(f"[X3-doc-only-partial] g8b_rc={g8b.returncode} out={g8b.stdout.strip()}", flush=True)

    # 4. Gate 6a: let vs have actually differs in definitional equality in Lean 4.36?
    r = BASE_TMP / "let_have_defeq"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def fLet (x : Nat) : Nat := let y := x + 1; y\n"
            "def fHave (x : Nat) : Nat := have y := x + 1; y\n"
            "theorem tLet : fLet 0 = 1 := rfl\n"
            "theorem tHave : fHave 0 = 1 := rfl\n"
        ),
    })
    b = run_build(r)
    print(f"[X4-let-have-rfl] build_rc={b.returncode}", flush=True)
    if b.stdout.strip():
        print("  BUILD OUT:", "\n  ".join(b.stdout.strip().splitlines()[:8]), flush=True)

    # 5. Gate 8b: check if `noncomputable def` or `structure` with `Prop` in `Chan/Defs` has any issue in gate 15
    # What if Chan/Defs has `def f : Nat := 0` OUTSIDE any `public section` (private by default) and no @[expose]?
    r = BASE_TMP / "g15_priv_only"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Flag.lean": (
            "module\n"
            "def secretOnly : Nat := 1\n"
        ),
    })
    g15 = run_gate(r, "15")
    print(f"[X5-g15-priv-only] g15_rc={g15.returncode} out={g15.stdout.strip()}", flush=True)

    # 6. Gate 10: check what `List.get!`, `Array.get!`, `List.head!`, `Option.get!` elaborate to in Lean 4.36!
    r = BASE_TMP / "g10_check_names"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\n@[expose] public section\n"
            "def f_arr_get (xs : Array Nat) (i : Nat) : Nat := xs[i]!\n"
            "def f_list_get (xs : List Nat) (i : Nat) : Nat := xs[i]!\n"
            "def f_list_head (xs : List Nat) : Nat := xs.head!\n"
            "def f_list_headD (xs : List Nat) : Nat := xs.headD 0\n"
            "def f_arr_back (xs : Array Nat) : Nat := xs.back!\n"
            "def f_arr_getD (xs : Array Nat) (i : Nat) : Nat := xs.getD i 0\n"
            "def f_opt_get (o : Option Nat) : Nat := o.get!\n"
            "def f_opt_getD (o : Option Nat) : Nat := o.getD 0\n"
            "def f_tail (xs : List Nat) : List Nat := xs.tail!\n"
        ),
    })
    g10 = run_gate(r, "10")
    print(f"[X6-g10-names] g10_rc={g10.returncode}\n{g10.stdout.strip()}", flush=True)


if __name__ == "__main__":
    main()
