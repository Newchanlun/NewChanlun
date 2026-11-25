"""Fast zero-Mathlib serial probes: 甲 core bypasses + 乙 deriving matrix + Gate 6a/6b/15 + 报告."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from probe_lib import (
    TMP_ROOT,
    WORK_DIR,
    base_env,
    build_base_package,
    check_disk,
    ensure_warm,
    free_gib,
    run_case,
    run_cmd,
    save_case_files,
)

warm = ensure_warm()
out_jsonl = TMP_ROOT / "batch_fast.jsonl"
if out_jsonl.exists():
    out_jsonl.unlink()


def emit(rec):
    with out_jsonl.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# 1. P3b2: include_str (pure Init, zero imports!) reading host file & running user code during fm_audit source
secret_file = TMP_ROOT / "host_secret_probe.txt"
secret_file.write_text("TOP_SECRET_HOST_CONTENT_42\n")
emit(run_case(
    warm,
    "P3b2_include_str_clean",
    {
        "formal_math/Chan/Thm/IncStr.lean": (
            "module\n"
            "public section\n"
            f'@[expose] def leaked : String := include_str (dbgTrace "INCLUDE_STR_EVAL_RAN" fun _ => "{secret_file}")\n'
            'theorem leaked_eq : leaked = "TOP_SECRET_HOST_CONTENT_42\\n" := rfl\n'
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 2. P5a: #guard_msgs (substring := true) swallowing error & warning without drop, plus deriving inside #guard_msgs
emit(run_case(
    warm,
    "P5a_guard_msgs_substring_swallow",
    {
        "formal_math/Chan/Thm/Dep.lean": (
            "module\n"
            "public section\n"
            '@[deprecated "old"] def oldFn : Nat := 1\n'
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

# 3. P6a & P6b: Gate 2 lakefile.toml bypass (`linter.unusedVariables.funArgs = false`, `debug.skipKernelTC = true`)
emit(run_case(
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

emit(run_case(
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
        'moreLeanArgs = ["-Dlinter.unusedVariables.funArgs=false", "-Ddebug.skipKernelTC=true"]\n\n'
        '[[lean_lib]]\nname = "ChanTest"\nglobs = ["ChanTest.*"]\n\n'
        '[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n\n'
        '[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
    ),
))

# 4. P7a, P7b, P7c: Env Gate 3 exemption spoofs (running fm_audit 3 directly!)
emit(run_case(
    warm,
    "P7a_env_deriving_spoof",
    {
        "formal_math/Chan/Thm/SpoofDerive.lean": (
            "module\n"
            "public section\n"
            "inductive Tree where\n"
            "  | leaf\n"
            "  | node (cs : List Tree)\n\n"
            "namespace instReprTree\n"
            "partial def repr (n : Nat) : Nat := repr (n + 1)\n"
            "end instReprTree\n\n"
            "def instReprTree : Repr Tree :=\n"
            "  let _ := @instReprTree.repr\n"
            "  { reprPrec := fun _ _ => Std.Format.nil }\n\n"
            "def callPartial (n : Nat) : Nat := instReprTree.repr n\n"
        ),
    },
    gates=[],
    run_build=False,
    env_only_mods=["Chan.Thm.SpoofDerive"],
))

emit(run_case(
    warm,
    "P7b_env_ctoridx_spoof",
    {
        "formal_math/Chan/Thm/SpoofCtorIdx.lean": (
            "module\n"
            "public section\n"
            "inductive MyProp : Prop where\n"
            "  | mk\n\n"
            "unsafe def fakeImpl (n : Nat) : Nat := getObjTagNat Nat n\n\n"
            "@[implemented_by fakeImpl]\n"
            "def MyProp.ctorIdx (n : Nat) : Nat := 0\n"
        ),
    },
    gates=[],
    run_build=False,
    env_only_mods=["Chan.Thm.SpoofCtorIdx"],
))

emit(run_case(
    warm,
    "P7c_env_extern_on_exempt",
    {
        "formal_math/Chan/Thm/ExternExempt.lean": (
            "module\n"
            "public section\n"
            "inductive Color | red | blue\n"
            'attribute [extern "evil_c_symbol"] Color.ctorIdx\n'
            'attribute [extern "evil_c_impl"] Color.ctorIdx._impl\n'
            "def myRec : Nat → Nat\n"
            "  | 0 => 0\n"
            "  | n + 1 => myRec n\n"
            'attribute [extern "evil_c_rec"] myRec._unsafe_rec\n'
        ),
    },
    gates=[],
    run_build=False,
    env_only_mods=["Chan.Thm.ExternExempt"],
))

# 5. P7d & P7e: term `unsafe` and `_root_.sorryAx` in `example`
emit(run_case(
    warm,
    "P7d_term_unsafe_expr",
    {
        "formal_math/Chan/Thm/TermUnsafe.lean": (
            "module\n"
            "public section\n"
            "def u : Nat := unsafe 42\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
    extra_fn=lambda repo, fm, env, rec: rec["steps"].append({
        "name": "fm_audit_source_3",
        **run_cmd(fm, ["lake", "exe", "fm_audit", "source", "Chan.Thm.TermUnsafe", "Chan/Thm/TermUnsafe.lean", "3"], env),
    }),
))

emit(run_case(
    warm,
    "P7e_root_sorryAx_example",
    {
        "formal_math/Chan/Thm/RootSorry.lean": (
            "module\n"
            "public section\n"
            "example : False := _root_.sorryAx False false\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 6. W1a: Plain recursive inductive deriving Ord (PREDICTED 乙 BLOCK FALSE POSITIVE!)
emit(run_case(
    warm,
    "W1a_plain_rec_deriving_ord",
    {
        "formal_math/Chan/Exec/BinTreeOrd.lean": (
            "module\n"
            "public section\n"
            "inductive BinTree where\n"
            "  | leaf (v : Nat)\n"
            "  | node (l r : BinTree)\n"
            "deriving Ord\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 7. W1b, W1c, W1d: Other deriving edge cases (namespace matching decl, private inductive, Chan/Defs expose)
emit(run_case(
    warm,
    "W1b_plain_rec_deriving_others",
    {
        "formal_math/Chan/Exec/BinTreeOthers.lean": (
            "module\n"
            "public section\n"
            "inductive BinTree where\n"
            "  | leaf (v : Nat)\n"
            "  | node (l r : BinTree)\n"
            "deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Repr, Inhabited, Nonempty\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

emit(run_case(
    warm,
    "W1c_ns_and_private_deriving",
    {
        "formal_math/Chan/Exec/NsDerive.lean": (
            "module\n"
            "public section\n"
            "structure Bar where\n"
            "  x : Nat\n"
            "namespace Bar\n"
            "inductive Rose where\n"
            "  | mk (cs : List Rose)\n"
            "deriving Repr, BEq, Hashable, Ord\n"
            "end Bar\n\n"
            "private inductive PrivRose where\n"
            "  | mk (cs : List PrivRose)\n"
            "deriving Repr, BEq, Hashable, Ord\n\n"
            "inductive ParamRose (α : Type) where\n"
            "  | leaf (a : α)\n"
            "  | node (cs : List (ParamRose α))\n"
            "deriving Repr, BEq, Hashable, Ord\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

emit(run_case(
    warm,
    "W1d_defs_deriving_expose",
    {
        "formal_math/Chan/Defs/Types.lean": (
            "module\n"
            "@[expose] public section\n"
            "inductive Dir | up | down deriving DecidableEq, BEq, ReflBEq, LawfulBEq, Hashable, Ord, Repr, Inhabited, Nonempty\n"
            "structure Bar where\n"
            "  lo : Nat\n"
            "  hi : Nat\n"
            "deriving DecidableEq, BEq, Hashable, Ord, Repr, Inhabited\n"
            "inductive Rose where\n"
            "  | leaf (n : Nat)\n"
            "  | node (cs : List Rose)\n"
            "deriving Repr, BEq, Hashable, Ord, Inhabited\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 8. P8a: Instance priority shadowing + @[simp] + attribute [-simp]
emit(run_case(
    warm,
    "P8a_instance_priority_and_simp",
    {
        "formal_math/Chan/Thm/ShadowInst.lean": (
            "module\n"
            "public section\n"
            "local instance (priority := high) fakeLT : LT Nat := ⟨fun _ _ => True⟩\n"
            "theorem looks_absurd : 10 < 1 := trivial\n"
            "@[simp] theorem my_simp (x : Nat) : x + 0 = x := Nat.add_zero x\n"
            "attribute [-simp] my_simp\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

# 9. P9a: Gate 6a let vs have (nondep ignored)
def run_gate6a_pair():
    case_name = "P9a_gate6a_let_vs_have"
    disk_before = check_disk(f"before {case_name}")
    f1 = "module\n@[expose] public section\ndef calcVal (n : Nat) : Nat := let x := n + 1; x + x\n"
    f2 = "module\n@[expose] public section\ndef calcVal (n : Nat) : Nat := have x := n + 1; x + x\n"
    save_case_files(case_name, {"v1/formal_math/Chan/Defs/V.lean": f1, "v2/formal_math/Chan/Defs/V.lean": f2})
    rec = {"case": case_name, "disk_before_gib": round(disk_before, 3), "steps": []}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix=f"{case_name}-", dir=WORK_DIR))
    try:
        build_base_package(repo, {"formal_math/Chan/Defs/V.lean": f1}, warm_build_dir=warm)
        env = base_env(repo)
        fm = repo / "formal_math"
        rec["steps"].append({"name": "build_v1", **run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Defs.V:olean", "+Chan:olean", "+ChanTest.Probe:olean"], env)})
        out1 = run_cmd(fm, ["lake", "exe", "fm_audit", "6a", "Chan.Defs.V"], env)
        rec["steps"].append({"name": "audit_6a_v1", **out1})
        lock = {}
        for line in out1["stdout"].splitlines():
            name, _mod, stmt = json.loads(line)
            payload = json.dumps(stmt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            lock[name] = hashlib.sha256(payload).hexdigest()
        (fm / "statement-lock.json").write_text(json.dumps(lock, indent=2))
        (fm / "Chan/Defs/V.lean").write_text(f2)
        rec["steps"].append({"name": "build_v2", **run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Defs.V:olean"], env)})
        rec["steps"].append({"name": "gate_6a_v2_against_v1_lock", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6a"], env)})
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        rec["disk_after_gib"] = round(free_gib(), 3)
    print(f"=== {case_name} ===", flush=True)
    for st in rec["steps"]:
        print(f"  [{st['name']}] rc={st['rc']} stdout={st['stdout'].strip()[:300]} stderr={st['stderr'].strip()[:300]}", flush=True)
    emit(rec)
    check_disk(f"after {case_name}")

run_gate6a_pair()

# 10. P9b: Gate 6a + Gate 15 on Chan.Hypotheses dropping `@[expose]`
def run_gate6a_hyp():
    case_name = "P9b_gate6a_hyp_no_expose"
    disk_before = check_disk(f"before {case_name}")
    f1 = "module\n@[expose] public section\ndef HypPred (n : Nat) : Prop := n = 0\n"
    f2 = "module\npublic section\ndef HypPred (n : Nat) : Prop := n = 0\n"
    save_case_files(case_name, {"v1/formal_math/Chan/Hypotheses/H.lean": f1, "v2/formal_math/Chan/Hypotheses/H.lean": f2})
    rec = {"case": case_name, "disk_before_gib": round(disk_before, 3), "steps": []}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix=f"{case_name}-", dir=WORK_DIR))
    try:
        build_base_package(repo, {"formal_math/Chan/Hypotheses/H.lean": f1}, warm_build_dir=warm)
        env = base_env(repo)
        fm = repo / "formal_math"
        run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Hypotheses.H:olean", "+Chan:olean", "+ChanTest.Probe:olean"], env)
        out1 = run_cmd(fm, ["lake", "exe", "fm_audit", "6a", "Chan.Hypotheses.H"], env)
        lock = {}
        for line in out1["stdout"].splitlines():
            name, _mod, stmt = json.loads(line)
            payload = json.dumps(stmt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            lock[name] = hashlib.sha256(payload).hexdigest()
        (fm / "statement-lock.json").write_text(json.dumps(lock, indent=2))
        (fm / "Chan/Hypotheses/H.lean").write_text(f2)
        run_cmd(fm, ["lake", "build", "--wfail", "+Chan.Hypotheses.H:olean"], env)
        rec["steps"].append({"name": "gate_6a_after_drop_expose", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6a"], env)})
        rec["steps"].append({"name": "gate_15_after_drop_expose", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "15"], env)})
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        rec["disk_after_gib"] = round(free_gib(), 3)
    print(f"=== {case_name} ===", flush=True)
    for st in rec["steps"]:
        print(f"  [{st['name']}] rc={st['rc']} stdout={st['stdout'].strip()[:300]} stderr={st['stderr'].strip()[:300]}", flush=True)
    emit(rec)
    check_disk(f"after {case_name}")

run_gate6a_hyp()

# 11. P9c: Gate 6b pure-git probes
def run_gate6b():
    case_name = "P9c_gate6b_probes"
    disk_before = check_disk(f"before {case_name}")
    rec = {"case": case_name, "disk_before_gib": round(disk_before, 3), "steps": []}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix=f"{case_name}-", dir=WORK_DIR))
    try:
        build_base_package(repo, {}, warm_build_dir=None)
        env = base_env(repo)
        fm = repo / "formal_math"
        git = lambda *a: subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=T", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *a],
            cwd=repo, check=True, capture_output=True, text=True,
        )
        git("init", "-q", "-b", "main")
        git("add", "formal_math")
        git("commit", "-qm", "base")
        git("update-ref", "refs/remotes/origin/main", "HEAD")

        git("switch", "-qc", "proof/untracked-root")
        (repo / "stray.txt").write_text("hi\n")
        rec["steps"].append({"name": "proof_untracked_root", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6b"], env)})
        (repo / "stray.txt").unlink()

        (fm / "Chan/Defs").mkdir(parents=True, exist_ok=True)
        (fm / "Chan/Defs/Sneak.lean").write_text("module\n")
        rec["steps"].append({"name": "proof_untracked_defs", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6b"], env)})
        (fm / "Chan/Defs/Sneak.lean").unlink()

        git("switch", "-q", "main")
        git("switch", "-qc", "infra/sneak-signoff")
        (fm / "verification/garbage-signoffs.yaml").write_text('{"Chan.x":{"Nat.div":{"count":1,"review":"fake"}}}\n')
        git("add", "formal_math/verification/garbage-signoffs.yaml")
        git("commit", "-qm", "sneak signoff")
        rec["steps"].append({"name": "infra_nonempty_signoff", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6b"], env)})

        git("switch", "-q", "main")
        git("switch", "--detach", "HEAD")
        env2 = dict(env)
        env2["GITHUB_HEAD_REF"] = "decl/"
        rec["steps"].append({"name": "detached_decl_empty_suffix", **run_cmd(repo, [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", "6b"], env2)})
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        rec["disk_after_gib"] = round(free_gib(), 3)
    print(f"=== {case_name} ===", flush=True)
    for st in rec["steps"]:
        print(f"  [{st['name']}] rc={st['rc']} stdout={st['stdout'].strip()[:300]} stderr={st['stderr'].strip()[:300]}", flush=True)
    emit(rec)
    check_disk(f"after {case_name}")

run_gate6b()

# 12. P9d: Gate 15 probes (Defs empty expose + noncomputable expose + Challenge trans Std)
emit(run_case(
    warm,
    "P9d1_gate15_defs_noncomputable_expose",
    {
        "formal_math/Chan/Defs/Noncomp.lean": (
            "module\n"
            "@[expose] public section\n"
            "noncomputable def pick : Nat := Classical.choice ⟨0⟩\n"
        ),
    },
    gates=["2", "3", "15"],
    run_build=True,
))

emit(run_case(
    warm,
    "P9d2_gate15_challenge_trans_std",
    {
        "formal_math/Chan/Defs/UsesStd.lean": (
            "module\n"
            "public import Std.Data.HashMap\n"
            "@[expose] public section\n"
            "def emptyMap : Std.HashMap Nat Nat := {}\n"
        ),
        "formal_math/ChanChallenge/C.lean": (
            "module\n"
            "public import Chan.Defs.UsesStd\n"
            "public section\n"
            "def m := emptyMap\n"
        ),
    },
    gates=["15"],
    run_build=True,
))

# 13. R1: Report certified accuracy & robustness (zero Mathlib!)
emit(run_case(
    warm,
    "R1_report_certified_and_robustness",
    {
        "formal_math/Chan/Defs/RepDefs.lean": (
            "module\n"
            "@[expose] public section\n"
            "def D (n : Nat) : Nat := n + 1\n"
            "structure CarryD where\n"
            "  x : Nat\n"
            "  h : D x = x + 1\n"
            "def divWithClass {α : Type} [Inhabited α] (_x : α) (a b : Rat) (_h : 0 < b) : Rat := a / b\n"
        ),
        "formal_math/Chan/Hypotheses/RepHyp.lean": (
            "module\n"
            "public import Chan.Defs.RepDefs\n"
            "@[expose] public section\n"
            "inductive NomInd (n : Nat) : Prop where\n"
            "  | mk : D n = 1 → NomInd n\n"
            "  | alt : D n = 1 → NomInd n\n"
        ),
        "formal_math/Chan/Thm/RepThm.lean": (
            "module\n"
            "public import Chan.Hypotheses.RepHyp\n"
            "public section\n"
            "theorem depends_on_D : D 0 = 1 := rfl\n"
            "theorem generalizes_D (n : Nat) : D n = D n := rfl\n"
            "theorem uses_carryD (c : CarryD) : c.x + 1 = c.x + 1 := rfl\n"
            "theorem uses_nom (h : NomInd 0) : D 0 = 1 := by cases h with | mk e => exact e | alt e => exact e\n"
            "theorem uses_prem_omega (a b : Nat) (h : a < b) : a + 1 ≤ b := by omega\n"
            "theorem unused_prem (a : Nat) (_h : a = 0) : a + 0 = a := Nat.add_zero a\n"
            "theorem dep_prem (l : List Nat) (i : Nat) (h1 : i < l.length) (h2 : l[i] = 0) : l[i] + 1 = 1 := by omega\n"
        ),
        "formal_math/formalization.yaml": json.dumps({
            "nodes": {
                "depends_on_D": {"about": ["D"], "mode": "依赖具体定义"},
                "generalizes_D": {"about": ["D"], "mode": "依赖具体定义"},
                "uses_carryD": {"about": ["D"], "mode": "依赖具体定义"},
                "uses_nom": {"about": ["D"], "mode": "依赖具体定义"},
                "uses_prem_omega": {"about": ["D"], "mode": "对任意实现成立"},
                "unused_prem": {"about": ["D"], "mode": "对任意实现成立"},
                "dep_prem": {"about": ["D"], "mode": "对任意实现成立", "main_theorem": True, "necessary": [1, 2]},
            },
            "refinements": {},
        }, ensure_ascii=False, indent=2),
    },
    gates=["2", "3", "15", "report"],
    run_build=True,
))

print("BATCH FAST COMPLETE", flush=True)
