"""Batch 1: Priority 甲 (Blocking Gate Bypasses)."""

import json
from pathlib import Path
from probe_lib import TMP_ROOT, ensure_warm, run_case, run_cmd

warm = ensure_warm()
results = []

# P1a: by_elab + Batteries.Lean.LawfulMonad -> arbitrary IO file write during fm_audit source AND build
sentinel_by_elab = TMP_ROOT / "sentinel_by_elab_pwned.txt"
results.append(run_case(
    warm,
    "P1a_by_elab_io_audit",
    {
        "formal_math/Chan/Thm/ByElabPwn.lean": (
            "module\n"
            "import Batteries.Lean.LawfulMonad\n"
            "public section\n"
            "def pwn : Nat := by_elab do\n"
            f'  IO.FS.writeFile "{sentinel_by_elab}" "BY_ELAB_EXECUTED_IN_AUDIT"\n'
            "  return Lean.mkNatLit 42\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=False,  # Run gates FIRST (gate 3 source runs fm_audit source!) to prove audit-time execution!
    sentinel_paths=[sentinel_by_elab],
    extra_fn=lambda repo, fm, env, rec: rec["steps"].append({
        "name": "build_wfail_after",
        **run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Thm.ByElabPwn:olean"], env),
    }),
))

# P1b: by_elab modifying controlled options (linter.unusedVariables false + debug.skipKernelTC true)
results.append(run_case(
    warm,
    "P1b_by_elab_options_and_unused",
    {
        "formal_math/Chan/Thm/ByElabOpt.lean": (
            "module\n"
            "import Batteries.Lean.LawfulMonad\n"
            "public section\n"
            "def silenceUnused : Nat → Nat := by_elab do\n"
            "  Lean.withOptions (fun o => (o.setBool `linter.unusedVariables false).setBool `debug.skipKernelTC true) do\n"
            "    Lean.Elab.Term.elabTerm (← `(fun unusedVar => 0)) (some (Lean.mkArrow (Lean.mkConst ``Nat) (Lean.mkConst ``Nat)))\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P2a: sudo set_option via Mathlib.Tactic.SudoSetOption (also re-exported by Mathlib.Tactic.Common)
results.append(run_case(
    warm,
    "P2a_sudo_set_option_unused",
    {
        "formal_math/Chan/Thm/SudoOpt.lean": (
            "module\n"
            "import Mathlib.Tactic.SudoSetOption\n"
            "public section\n"
            "def bypassUnused : Nat → Nat :=\n"
            "  sudo set_option linter.unusedVariables false in\n"
            "  sudo set_option debug.skipKernelTC true in\n"
            "  sudo set_option autoImplicit true in\n"
            "  sudo set_option smartUnfolding false in\n"
            "  fun unusedArg => 0\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P3a: eval% (Mathlib.Tactic.Eval) running user code during fm_audit source
results.append(run_case(
    warm,
    "P3a_eval_percent",
    {
        "formal_math/Chan/Thm/EvalPct.lean": (
            "module\n"
            "import Mathlib.Tactic.Eval\n"
            "public section\n"
            'def userCode (n : Nat) : Nat := dbgTrace "EVAL_PCT_USER_CODE_RAN" fun _ => n + 1\n'
            "def res : Nat := eval% (userCode 41)\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P3b: include_str (Init, ZERO extra imports!) reading host file & evaluating user code during fm_audit source
secret_file = TMP_ROOT / "host_secret_probe.txt"
secret_file.write_text("TOP_SECRET_HOST_CONTENT_42\n")
results.append(run_case(
    warm,
    "P3b_include_str_host_read",
    {
        "formal_math/Chan/Thm/IncStr.lean": (
            "module\n"
            "public section\n"
            f'def leaked : String := include_str (dbgTrace "INCLUDE_STR_EVAL_RAN" fun _ => "{secret_file}")\n'
            'theorem leaked_eq : leaked = "TOP_SECRET_HOST_CONTENT_42\\n" := rfl\n'
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P3c: Mathlib trace & success_if_fail_with_msg evaluating user terms at elab/audit time
results.append(run_case(
    warm,
    "P3c_trace_and_siffwm",
    {
        "formal_math/Chan/Thm/EvalTacs.lean": (
            "module\n"
            "import Mathlib.Tactic.SuccessIfFailWithMsg\n"
            "public section\n"
            'def mkMsg : String := dbgTrace "SIFFWM_EVAL_RAN" fun _ => "tactic \'rfl\' failed, the left-hand side\\n  0\\nis not definitionally equal to the right-hand side\\n  1\\n⊢ 0 = 1"\n'
            "theorem t : True := by\n"
            "  success_if_fail_with_msg mkMsg (have : 0 = 1 := by rfl)\n"
            "  trivial\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P4: InfoTree hole in decreasing_by hiding library-macro set_option (rfl' and unhygienic)
results.append(run_case(
    warm,
    "P4a_decreasing_by_rfl_prime",
    {
        "formal_math/Chan/Thm/DecHole.lean": (
            "module\n"
            "public section\n"
            "def f (n : Nat) : Nat :=\n"
            "  if h : n = 0 then 0 else f (n - 1)\n"
            "termination_by n\n"
            "decreasing_by\n"
            "  have _ : (2 : Nat) = 2 := by rfl'\n"
            "  unhygienic omega\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# P5: #guard_msgs in Chan/Final swallowing warnings & errors WITHOUT `drop`, and wrapping `deriving`
results.append(run_case(
    warm,
    "P5a_guard_msgs_substring_swallow",
    {
        "formal_math/Chan/Thm/Dep.lean": (
            "module\n"
            "public section\n"
            "@[deprecated \"old\"] def oldFn : Nat := 1\n"
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

# P6: Gate 2 lakefile.toml bypass (linter.unusedVariables.funArgs / debug.skipKernelTC in [leanOptions] & moreLeanArgs)
results.append(run_case(
    warm,
    "P6a_lakefile_leanOptions_bypass",
    {
        "formal_math/Chan/Thm/UnusedArg.lean": (
            "module\n"
            "public section\n"
            "def hasUnusedArg (unusedParam : Nat) : Nat := 0\n"
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
        'linter.unusedVariables.funArgs = false\n'
        'debug.skipKernelTC = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n\n'
        '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n\n'
        '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
    ),
))

results.append(run_case(
    warm,
    "P6b_lakefile_moreLeanArgs_bypass",
    {
        "formal_math/Chan/Thm/UnusedArg.lean": (
            "module\n"
            "public section\n"
            "def hasUnusedArg (unusedParam : Nat) : Nat := 0\n"
        ),
    },
    gates=["2", "3"],
    run_build=False,
    custom_lakefile=(
        'name = "fixture"\ndefaultTargets = ["Chan"]\n\n'
        '[leanOptions]\n'
        'autoImplicit = false\n'
        'relaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n\n'
        '[[lean_lib]]\nname = "Chan"\nglobs = ["Chan.*"]\n'
        'moreLeanArgs = ["-Dlinter.unusedVariables.funArgs=false", "-Dlinter.all=false", "-Ddebug.skipKernelTC=true"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n\n'
        '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n\n'
        '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
    ),
))

(TMP_ROOT / "batch1.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
print("BATCH 1 COMPLETE", flush=True)
