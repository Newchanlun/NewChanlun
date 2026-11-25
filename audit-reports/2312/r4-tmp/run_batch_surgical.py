"""Surgical follow-up serial probes: zero-import RCE, fixed P7b/P7a/P5b/P6c, sudo set_option, W2/W3."""

import json
from pathlib import Path
from probe_lib import TMP_ROOT, ensure_warm, run_case, run_cmd

warm = ensure_warm()
out_jsonl = TMP_ROOT / "batch_surgical.jsonl"
if out_jsonl.exists():
    out_jsonl.unlink()


def emit(rec):
    with out_jsonl.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# 1. P0: ZERO-IMPORT ARBITRARY IO EXECUTION INSIDE `fm_audit source` (pure Init, zero traces in env!)
sentinel_rce = TMP_ROOT / "sentinel_zero_import_rce.txt"
sentinel_rce_src = TMP_ROOT / "sentinel_zero_import_rce_source_only.txt"
secret_file = TMP_ROOT / "host_secret_probe.txt"
secret_file.write_text("TOP_SECRET_HOST_CONTENT_42\n")

def p0_check_source_first(repo, fm, env, rec):
    # First prove fm_audit source ALONE (before any lake build!) executes host IO
    if sentinel_rce.exists():
        sentinel_rce.unlink()
    s_only = run_cmd(
        fm,
        ["lake", "exe", "fm_audit", "source", "Chan.Thm.ZeroImportRCE", "Chan/Thm/ZeroImportRCE.lean", "3"],
        env,
    )
    rec["steps"].append({"name": "fm_audit_source_only_before_build", **s_only})
    rec["sentinel_after_source_only"] = sentinel_rce.read_text() if sentinel_rce.exists() else None
    if sentinel_rce.exists():
        sentinel_rce.unlink()
    # Now build with --wfail and run all blocking gates 2, 3, 15
    rec["steps"].append({
        "name": "build_wfail",
        **run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Thm.ZeroImportRCE:olean"], env),
    })
    for g in ("2", "3", "15"):
        rec["steps"].append({
            "name": f"gate_{g}",
            **run_cmd(repo, [__import__("sys").executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", g], env),
        })

emit(run_case(
    warm,
    "P0_zero_import_io_rce_in_audit",
    {
        "formal_math/Chan/Thm/ZeroImportRCE.lean": (
            "module\n"
            "public section\n"
            "@[expose] def payload : String :=\n"
            "  include_str (unsafe (\n"
            "    match unsafeIO (do\n"
            f'      IO.FS.writeFile "{sentinel_rce}" "ZERO_IMPORT_IO_EXECUTED_IN_AUDIT"\n'
            f'      return System.FilePath.mk "{secret_file}") with\n'
            '    | .ok p => p\n'
            '    | .error _ => System.FilePath.mk ""))\n'
            'theorem exfiltrated : payload = "TOP_SECRET_HOST_CONTENT_42\\n" := rfl\n'
        ),
    },
    gates=[],
    run_build=False,
    sentinel_paths=[sentinel_rce],
    extra_fn=p0_check_source_first,
))

# 2. P7b2: Fixed Env Gate 3 Exemption 1 spoof (`@getObjTagNat Nat n` on Prop inductive!)
emit(run_case(
    warm,
    "P7b2_env_ctoridx_spoof_fixed",
    {
        "formal_math/Chan/Thm/SpoofCtorIdx.lean": (
            "module\n"
            "public section\n"
            "inductive MyProp : Prop where\n"
            "  | mk\n\n"
            "unsafe def fakeImpl (n : Nat) : Nat := @getObjTagNat Nat n\n\n"
            "@[implemented_by fakeImpl]\n"
            "def MyProp.ctorIdx (n : Nat) : Nat := 0\n"
        ),
    },
    gates=[],
    run_build=False,
    env_only_mods=["Chan.Thm.SpoofCtorIdx"],
))

# 3. P7a2: Clean zero-warning Env Gate 3 Exemption 3 spoof (`instance instReprTree`)
emit(run_case(
    warm,
    "P7a2_env_deriving_spoof_clean",
    {
        "formal_math/Chan/Thm/SpoofDeriveClean.lean": (
            "module\n"
            "public section\n"
            "inductive Tree where\n"
            "  | leaf\n"
            "  | node (cs : List Tree)\n\n"
            "namespace instReprTree\n"
            "partial def repr (n : Nat) : Nat := repr (n + 1)\n"
            "end instReprTree\n\n"
            "instance instReprTree : Repr Tree :=\n"
            "  let _ := @instReprTree.repr\n"
            "  { reprPrec := fun _ _ => Std.Format.nil }\n\n"
            "def callPartial (n : Nat) : Nat := instReprTree.repr n\n"
        ),
    },
    gates=[],
    run_build=False,
    env_only_mods=["Chan.Thm.SpoofDeriveClean"],
))

# 4. P5b: Clean zero-warning #guard_msgs (substring := true) swallowing error, warning, AND wrapping deriving instance
emit(run_case(
    warm,
    "P5b_guard_msgs_clean_swallow",
    {
        "formal_math/Chan/Thm/Dep.lean": (
            "module\n"
            "@[expose] public section\n"
            '@[deprecated "old" (since := "2026-01-01")] def oldFn : Nat := 1\n'
            "inductive PairTag | a | b\n"
        ),
        "formal_math/Chan/Final/GuardSwallow.lean": (
            "module\n"
            "import Chan.Thm.Dep\n"
            "public section\n"
            "#guard_msgs (substring := true) in\n"
            "#check (1 : String)\n"
            "#guard_msgs (substring := true) in\n"
            "#check oldFn\n"
            "#guard_msgs (substring := true) in\n"
            "deriving instance Repr for PairTag\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 5. P6c: Gate 2 package-level [leanOptions] bypass (`linter.deprecated = false`, `debug.skipKernelTC = true`)
emit(run_case(
    warm,
    "P6c_lakefile_pkg_leanOptions_bypass",
    {
        "formal_math/Chan/Thm/DepUse.lean": (
            "module\n"
            "public section\n"
            '@[deprecated "old" (since := "2026-01-01")] def oldFn : Nat := 1\n'
            "def useOld : Nat := oldFn\n"
        ),
    },
    gates=["2", "3"],
    run_build=False,
    custom_lakefile=(
        'name = "fixture"\ndefaultTargets = ["Chan"]\n\n'
        '[leanOptions]\n'
        'autoImplicit = false\n'
        'relaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n'
        'linter.deprecated = false\n'
        'debug.skipKernelTC = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n\n'
        '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n\n'
        '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
    ),
))

# 6. P2b: sudo set_option clean zero-warning bypass (Mathlib.Tactic.SudoSetOption)
emit(run_case(
    warm,
    "P2b_sudo_set_option_clean",
    {
        "formal_math/Chan/Thm/SudoClean.lean": (
            "module\n"
            "import Mathlib.Tactic.SudoSetOption\n"
            "public section\n"
            "def setControlledOpts : Nat :=\n"
            "  sudo set_option debug.skipKernelTC true in\n"
            "  sudo set_option autoImplicit true in\n"
            "  sudo set_option relaxedAutoImplicit true in\n"
            "  sudo set_option smartUnfolding false in\n"
            "  sudo set_option linter.unusedVariables false in\n"
            "  0\n\n"
            "theorem silenceUnusedInTactic : True :=\n"
            "  sudo set_option linter.unusedVariables false in\n"
            "  by\n"
            "    have unusedLocal : Nat := 42\n"
            "    trivial\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 7. P1d: sudo set_option compiler.checkMeta false + Batteries.Lean.LawfulMonad + by_elab -> FULL TermElabM + IO in audit!
sentinel_sudo_by_elab = TMP_ROOT / "sentinel_sudo_by_elab_pwned.txt"

def p1d_check_source_first(repo, fm, env, rec):
    if sentinel_sudo_by_elab.exists():
        sentinel_sudo_by_elab.unlink()
    s_only = run_cmd(
        fm,
        ["lake", "exe", "fm_audit", "source", "Chan.Thm.SudoByElab", "Chan/Thm/SudoByElab.lean", "3"],
        env,
    )
    rec["steps"].append({"name": "fm_audit_source_only_before_build", **s_only})
    rec["sentinel_after_source_only"] = sentinel_sudo_by_elab.read_text() if sentinel_sudo_by_elab.exists() else None
    if sentinel_sudo_by_elab.exists():
        sentinel_sudo_by_elab.unlink()
    rec["steps"].append({
        "name": "build_wfail",
        **run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Thm.SudoByElab:olean"], env),
    })
    for g in ("2", "3", "15"):
        rec["steps"].append({
            "name": f"gate_{g}",
            **run_cmd(repo, [__import__("sys").executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", g], env),
        })

emit(run_case(
    warm,
    "P1d_sudo_by_elab_io_audit",
    {
        "formal_math/Chan/Thm/SudoByElab.lean": (
            "module\n"
            "import Mathlib.Tactic.SudoSetOption\n"
            "import Batteries.Lean.LawfulMonad\n"
            "public section\n"
            "def pwn : Nat :=\n"
            "  sudo set_option compiler.checkMeta false in\n"
            "  by_elab do\n"
            f'    IO.FS.writeFile "{sentinel_sudo_by_elab}" "SUDO_BY_ELAB_EXECUTED_IN_AUDIT"\n'
            "    return Lean.mkNatLit 42\n"
        ),
    },
    gates=[],
    run_build=False,
    sentinel_paths=[sentinel_sudo_by_elab],
    extra_fn=p1d_check_source_first,
))

# 8. P3d: Mathlib.Tactic.Trace & SuccessIfFailWithMsg executing user code during fm_audit source
emit(run_case(
    warm,
    "P3d_mathlib_trace_and_siffwm_eval",
    {
        "formal_math/Chan/Thm/TraceEval.lean": (
            "module\n"
            "import Mathlib.Tactic.Trace\n"
            "import Mathlib.Tactic.SuccessIfFailWithMsg\n"
            "public section\n"
            'def mkTrace : String := dbgTrace "TRACE_EVAL_RAN" fun _ => "hello"\n'
            'def mkExpected : String := dbgTrace "SIFFWM_EVAL_RAN" fun _ => "Tactic `rfl` failed: The left-hand side\\n  0\\nis not definitionally equal to the right-hand side\\n  1\\n\\n⊢ 0 = 1"\n'
            "theorem t : True := by\n"
            "  trace mkTrace\n"
            "  success_if_fail_with_msg mkExpected (have : 0 = 1 := by rfl)\n"
            "  trivial\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 9. W2: Comprehensive W3 proof file exercising EVERY item in section 乙
emit(run_case(
    warm,
    "W1e_ns_param_deriving_visitNamespace",
    {
        "formal_math/Chan/Exec/NsParamDerive.lean": (
            "module\n"
            "public section\n"
            "structure Bar where\n"
            "  x : Nat\n"
            "deriving Repr\n"
            "namespace Bar\n"
            "inductive Tree (b : Bar) where\n"
            "  | leaf\n"
            "  | node (cs : List (Tree b))\n"
            "deriving Repr\n"
            "end Bar\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

emit(run_case(
    warm,
    "W2_comprehensive_w3_proof",
    {
        "formal_math/Chan/Defs/Model.lean": (
            "module\n"
            "public import Mathlib.Algebra.BigOperators.Group.Finset.Defs\n"
            "public import Mathlib.Algebra.Order.Ring.Defs\n"
            "@[expose] public section\n"
            "structure IntervalBar (P : Type) [LinearOrder P] where\n"
            "  lo : P\n"
            "  hi : P\n"
            "  valid : lo ≤ hi\n"
            "@[ext] structure Pt where\n"
            "  x : Nat\n"
            "  y : Nat\n"
            "deriving DecidableEq, BEq, Inhabited\n"
            "@[reducible] def Pt.sum (p : Pt) : Nat := p.x + p.y\n"
        ),
        "formal_math/Chan/Thm/W3Proofs.lean": (
            "module\n"
            "public import Chan.Defs.Model\n"
            "public import Mathlib.Tactic.Common\n"
            "public import Mathlib.Tactic.Linarith\n"
            "public import Mathlib.Tactic.NormNum\n"
            "public import Mathlib.Tactic.Positivity\n"
            "public import Mathlib.Algebra.BigOperators.Group.Finset.Basic\n"
            "public import Mathlib.Data.Finset.Range\n"
            "public import Mathlib.Data.Rat.Defs\n"
            "public import Mathlib.Tactic.Ring\n"
            "public section\n"
            "open scoped BigOperators\n\n"
            "def steps : Nat → Nat\n"
            "  | 0 => 0\n"
            "  | n + 1 => 1 + steps (n / 2)\n"
            "termination_by n => n\n"
            "decreasing_by omega\n\n"
            "def sumWithWhere (xs : List Nat) : Nat := go xs 0\n"
            "where\n"
            "  go : List Nat → Nat → Nat\n"
            "    | [], acc => acc\n"
            "    | a :: as, acc => go as (acc + a)\n\n"
            "def sumLetRec (xs : List Nat) : Nat :=\n"
            "  let rec loop : List Nat → Nat\n"
            "    | [] => 0\n"
            "    | a :: as => a + loop as\n"
            "  loop xs\n\n"
            "mutual\n"
            "  inductive ExprA | lit (n : Nat) | wrap (b : ExprB)\n"
            "  inductive ExprB | neg (a : ExprA)\n"
            "end\n"
            "deriving instance Repr, BEq, DecidableEq, Hashable, Ord for ExprA, ExprB\n\n"
            "mutual\n"
            "  def szA : ExprA → Nat\n"
            "    | .lit _ => 1\n"
            "    | .wrap b => 1 + szB b\n"
            "  def szB : ExprB → Nat\n"
            "    | .neg a => 1 + szA a\n"
            "end\n\n"
            "section Params\n"
            "variable {α : Type} [DecidableEq α] (a : α)\n"
            "include a\n"
            "omit [DecidableEq α] in\n"
            "theorem id_eq_self : a = a := rfl\n"
            "end Params\n\n"
            "@[simp] theorem pt_sum_mk (a b : Nat) : (⟨a, b⟩ : Pt).sum = a + b := rfl\n\n"
            "theorem use_calc_omega (a b c : Nat) (h1 : a ≤ b) (h2 : b ≤ c) : a ≤ c + 1 := by\n"
            "  calc a ≤ b := h1\n"
            "    _ ≤ c := h2\n"
            "    _ ≤ c + 1 := by omega\n\n"
            "theorem use_decide : (2 + 3 : Nat) = 5 := by decide\n\n"
            "theorem use_grind (x y : Nat) (h : x = y) : x + 1 = y + 1 := by grind\n\n"
            "theorem use_aesop (P Q : Prop) (h : P ∧ Q) : Q ∧ P := by aesop\n\n"
            "theorem use_linarith (x y : Int) (h1 : x ≤ y) (h2 : y ≤ x) : x = y := by linarith\n\n"
            "theorem use_norm_num : (2 : Rat) + 3 / 2 = 7 / 2 := by norm_num\n\n"
            "theorem use_positivity (x : Rat) (hx : 0 < x) : 0 < x * x := by positivity\n\n"
            "theorem use_rcases_obtain (h : ∃ p : Pt, p.x = 1 ∧ p.y = 2) : ∃ n : Nat, n = 3 := by\n"
            "  rcases h with ⟨⟨x, y⟩, hx, hy⟩\n"
            "  obtain ⟨m, hm⟩ : ∃ m, m = x + y := ⟨x + y, rfl⟩\n"
            "  exact ⟨m, by omega⟩\n\n"
            "theorem use_induction (xs : List Nat) : sumLetRec xs = xs.sum := by\n"
            "  induction xs with\n"
            "  | nil => rfl\n"
            "  | cons a as ih => simp [sumLetRec, sumLetRec.loop, ih]\n\n"
            "theorem use_big_ops (n : Nat) : (∑ i ∈ Finset.range n, (0 : Nat)) = 0 := by\n"
            "  simp\n\n"
            "theorem use_list_big_op (xs : List Nat) : (xs.map (· + 0)).sum = xs.sum := by\n"
            "  simp\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

print("BATCH SURGICAL COMPLETE", flush=True)
