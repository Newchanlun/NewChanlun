"""NewChanlun #2312 (head 0b99173677) 第二轮对抗实证的干净复现套件。
每项均使用与真实 formal_math/lakefile.toml 同构的干净配置，并分别核验 lake build --wfail 与门禁退出码。
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

WT = Path("/Users/silencehan/.t3/worktrees/NewChanlun/infra-2312-b-env-gates-2428b08ce810d112")
VER = WT / "formal_math/verification"
BASE_TMP = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_sandbox")
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
        'name = "cleanr2"\ndefaultTargets = ["Chan", "ChanTest"]\n\n'
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


RESULTS = []


def rec(cid, gate, desc, res):
    RESULTS.append({"id": cid, "gate": gate, "desc": desc, "rc": res.returncode,
                    "stdout": res.stdout.strip(), "stderr": res.stderr.strip()})
    print(f"[{cid}] gate={gate} rc={res.returncode} | {desc}", flush=True)
    if res.stdout.strip():
        for l in res.stdout.strip().splitlines()[:8]:
            print(f"    OUT: {l}", flush=True)
    if res.stderr.strip():
        for l in res.stderr.strip().splitlines()[:6]:
            print(f"    ERR: {l}", flush=True)


def main():
    BASE_TMP.mkdir(parents=True, exist_ok=True)

    # --- 1. Gate 8a/8b/9 statement wrapping: let, have, fun, True ∧, @[irreducible], non-project wrapper ---
    for name, stmt, proof in [
        ("let_wrap", "let _ : Nat := 0; ∀ (x : Nat), x = 0 → x = 1 → False",
         "fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)"),
        ("have_wrap", "have _ : True := trivial; ∀ (x : Nat), x = 0 → x = 1 → False",
         "fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)"),
        ("fun_wrap", "(fun _ : Nat => ∀ (x : Nat), x = 0 → x = 1 → False) 0",
         "fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)"),
        ("and_wrap", "True ∧ (∀ (x : Nat), x = 0 → x = 1 → False)",
         "⟨trivial, fun _ h0 h1 => Nat.noConfusion (h0.symm.trans h1)⟩"),
    ]:
        r = BASE_TMP / f"e2_{name}"
        make_clean_pkg(r, {
            "formal_math/Chan/Thm/Fixture.lean": f"module\npublic section\ntheorem claim : {stmt} := {proof}\n",
            "formal_math/ChanTest/Evidence.lean": "module\npublic section\ntheorem claim.witness : True := trivial\n",
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {"claim": {"about": [], "mode": "对任意实现成立", "needs_necessity": True}}
            }),
        })
        rec(f"E2-{name}-build", "9", f"{name} 编译核验", run_build(r, "--wfail"))
        rec(f"E2-{name}-g9", "9", f"{name} 包装矛盾空真定理测门9 (仅 True 见证)", run_gate(r, "9"))

    # Also test True ∧ wrapping mirror (8a) and unused premise (8b)!
    r = BASE_TMP / "e2_and_8a8b"
    make_clean_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem and_mirror : True ∧ (∀ (P : Nat → Prop), (∀ x, P x) → ∀ x, P x) :=\n"
            "  ⟨trivial, fun _ h x => h x⟩\n"
            "theorem and_bsp : True ∧ (∀ (d lvl side : Nat) (_hdiv : d > 0), ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side) :=\n"
            "  ⟨trivial, fun _ lvl side _ => ⟨(lvl, side), rfl, rfl⟩⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "and_mirror": {"about": [], "mode": "对任意实现成立"},
                "and_bsp": {"about": [], "mode": "对任意实现成立"},
            }
        }),
    })
    rec("E2-and-8a", "8a", "True ∧ 包装镜像定理测门8a", run_gate(r, "8a"))
    rec("E2-and-8b", "8b", "True ∧ 包装无用前提定理测门8b", run_gate(r, "8b"))

    # --- 2. Gate 8a ExistsUnique variants & AliasNat / conj premise (fixed compile) ---
    r = BASE_TMP / "e3_clean"
    make_clean_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Mathlib.Basic.ExistsUnique\n@[expose] public section\n"
            "def AliasNat := Nat\n"
            "end\npublic section\n"
            "theorem eu_eq_zero (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => y = f x ∧ 0 = 0) :=\n"
            "  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩\n"
            "theorem eu_dup (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => y = f x ∧ y = f x) :=\n"
            "  ⟨f x, ⟨rfl, rfl⟩, fun _ h => h.1⟩\n"
            "theorem eu_manual_rev (f : Nat → Nat) (x : Nat) :\n"
            "    ∃ y, (∀ z, z = f x → z = y) ∧ y = f x :=\n"
            "  ⟨f x, fun _ h => h, rfl⟩\n"
            "theorem eu_manual_id (f : Nat → Nat) (x : Nat) :\n"
            "    ∃ y, y = f x ∧ ∀ z, z = f x → id z = y :=\n"
            "  ⟨f x, rfl, fun _ h => h⟩\n"
            "theorem eu_pair (f : Nat → Nat) (x : Nat) :\n"
            "    ExistsUnique (fun y => (y, ()) = (f x, ())) :=\n"
            "  ⟨f x, rfl, fun _ h => congrArg Prod.fst h⟩\n"
            "theorem alias_mirror (P : Nat → Prop) (x : AliasNat) (h : ∀ n : Nat, P n) : P x := h x\n"
            "theorem conj_mirror (P : Nat → Prop) (h : (∀ n, P n) ∧ True) (x : Nat) : P x := h.1 x\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "eu_eq_zero": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_dup": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_manual_rev": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_manual_id": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "eu_pair": {"about": [], "mode": "对任意实现成立", "declarative_unique": True},
                "alias_mirror": {"about": [], "mode": "对任意实现成立"},
                "conj_mirror": {"about": [], "mode": "对任意实现成立"},
            }
        }),
    }, uses_mathlib=True)
    rec("E3-clean-build", "8a", "ExistsUnique 变体 + AliasNat/合取前提 编译核验", run_build(r, "--wfail"))
    rec("E3-clean-g8a", "8a", "ExistsUnique 变体 + AliasNat/合取前提 测门8a（每条未报即绕过）", run_gate(r, "8a"))

    # --- 3. Gate 8b individual clean repros for the 4 confirmed bypasses ---
    for cid, code in [
        ("E4-const", (
            "module\npublic section\n"
            "theorem bsp_const (d lvl side : Nat) :\n"
            "    d > 0 → ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  Function.const (d > 0) ⟨(lvl, side), rfl, rfl⟩\n"
        )),
        ("E4-sub-beta", (
            "module\npublic section\n"
            "theorem bsp_sub_beta (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), (fun _ => rfl) _hdiv, rfl⟩\n"
        )),
        ("E4-and-left", (
            "module\npublic section\n"
            "theorem bsp_and_left (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), And.left ⟨rfl, _hdiv⟩, rfl⟩\n"
        )),
        ("E4-sub-helper", (
            "module\npublic section\n"
            "private theorem mkEq {d lvl : Nat} (_ : d > 0) : lvl = lvl := rfl\n"
            "theorem bsp_sub_helper (d lvl side : Nat) (_hdiv : d > 0) :\n"
            "    ∃ sig : Nat × Nat, sig.1 = lvl ∧ sig.2 = side :=\n"
            "  ⟨(lvl, side), mkEq _hdiv, rfl⟩\n"
        )),
    ]:
        r = BASE_TMP / cid.lower()
        make_clean_pkg(r, {
            "formal_math/Chan/Thm/Fixture.lean": code,
            "formal_math/formalization.yaml": json.dumps({
                "nodes": {
                    "_private.Chan.Thm.Fixture.0.mkEq": {"about": [], "mode": "对任意实现成立", "doc_only": {"1": "辅助"}},
                }
            }),
        })
        rec(f"{cid}-build", "8b", f"{cid} 独立编译核验", run_build(r, "--wfail"))
        rec(f"{cid}-g8b", "8b", f"{cid} 独立测门8b（预期红，实测若0即硬绕过）", run_gate(r, "8b"))

    # --- 4. Gate 7b: 2-field Prop structure destructured with `cases h` (generates casesOn) ---
    r = BASE_TMP / "d6_2field_cases"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": "module\n@[expose] public section\ndef D (n : Nat) : Nat := n + 1\n",
        "formal_math/Chan/Hypotheses/Fixture.lean": (
            "module\npublic import Chan.Defs.Fixture\n@[expose] public section\n"
            "structure PullbackHyp (n : Nat) : Prop where\n  ok : D n = 1\n  aux : n = 0\n"
        ),
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic import Chan.Hypotheses.Fixture\npublic section\n"
            "theorem claim (h : PullbackHyp 0) : D 0 = 1 := by\n"
            "  cases h with\n  | mk hok _ => exact hok\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"claim": {"about": ["D"], "mode": "依赖具体定义"}}
        }),
    })
    rec("D6-2field-build", "7b", "双字段 Prop structure 用 cases h 解构 编译核验", run_build(r, "--wfail"))
    rec("D6-2field-g7b", "7b", "双字段 Prop structure 用 cases h 解构 测门7b是否崩溃退2", run_gate(r, "7b"))

    # --- 5. Gate 10 clean misses (Rat.inv, Inv.inv, Int.tdiv/ediv/fdiv, headD, getLastD, Option+panic!/head!/getLast!/[i]!) ---
    r = BASE_TMP / "f1_clean"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Init.Data.Rat.Basic\n@[expose] public section\n"
            "def invRat (y : Rat) : Rat := y.inv\n"
            "def intTdiv (x y : Int) : Int := Int.tdiv x y\n"
            "def intEdiv (x y : Int) : Int := Int.ediv x y\n"
            "def intFdiv (x y : Int) : Int := Int.fdiv x y\n"
            "def natMod (x y : Nat) : Nat := x % y\n"
            "def headD_fn (xs : List Nat) : Nat := xs.headD 0\n"
            "def getLastD_fn (xs : List Nat) : Nat := xs.getLastD 0\n"
            "def arrBang (xs : Array Nat) (i : Nat) : Nat := xs[i]!\n"
            "def optGetBang (o : Option Nat) : Nat := o.get!\n"
            "def optPanic (xs : List (Option Nat)) : Option Nat := if xs.isEmpty then panic! \"x\" else xs.head!\n"
            "def optLastBang (xs : List (Option Nat)) : Option Nat := xs.getLast!\n"
            "def optGetIdxBang (xs : List (Option Nat)) (i : Nat) : Option Nat := xs[i]!\n"
            "def intToNat (x : Int) : Nat := x.toNat\n"
        ),
    })
    rec("F1-clean-build", "10", "门10垃圾值集合编译核验", run_build(r, "--wfail"))
    rec("F1-clean-g10", "10", "门10垃圾值集合检测（逐声明核查漏报）", run_gate(r, "10"))

    # Also test Mathlib Rat `y⁻¹` (`Inv.inv`) alone!
    r = BASE_TMP / "f1_rat_inv_only"
    make_clean_pkg(r, {
        "formal_math/Chan/Defs/Fixture.lean": (
            "module\npublic import Init.Data.Rat.Basic\n@[expose] public section\n"
            "def invRat (y : Rat) : Rat := y.inv\n"
            "def divByInv (x y : Rat) : Rat := x * y.inv\n"
        ),
    })
    rec("F1-ratinv-build", "10", "Rat.inv 编译核验", run_build(r, "--wfail"))
    rec("F1-ratinv-g10", "10", "Rat.inv (0.inv = 0) 单独测门10（预期红，实测若0即漏检）", run_gate(r, "10"))

    # --- 6. Gate 7a/9 false positive on simple recursive theorem `match_1_1` in Chan/Thm ---
    r = BASE_TMP / "e5_rec_thm_7a9"
    make_clean_pkg(r, {
        "formal_math/Chan/Thm/Fixture.lean": (
            "module\npublic section\n"
            "theorem rec_thm (n : Nat) : n + 0 = n :=\n"
            "  match n with\n  | 0 => rfl\n  | k + 1 => congrArg Nat.succ (rec_thm k)\n"
        ),
        "formal_math/ChanTest/Evidence.lean": (
            "module\npublic section\n"
            "theorem rec_thm.witness : ∃ _n : Nat, True := ⟨0, trivial⟩\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {"rec_thm": {"about": [], "mode": "对任意实现成立"}}
        }),
    })
    rec("E5-rec-build", "7a", "普通递归定理 rec_thm 编译核验", run_build(r, "--wfail"))
    rec("E5-rec-g7a", "7a", "普通递归定理 rec_thm 是否触发编译器辅助定理误杀门7a", run_gate(r, "7a"))
    rec("E5-rec-g9", "9", "普通递归定理 rec_thm 是否触发编译器辅助定理误杀门9", run_gate(r, "9"))

    out = Path("/Volumes/AgentStorage/fm/r2/2312-r2-tmp/r2_clean_verify_results.json")
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    print(f"\nDONE R2 CLEAN VERIFY: {len(RESULTS)} experiments", flush=True)


if __name__ == "__main__":
    main()
