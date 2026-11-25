"""Batch 6: Fresh `@[macro]` with `stripInfo` (zero decl range -> ALL 8 gates exit 0!) + Gate 3 env-layer `partial` dead-check proof."""
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


def run_fresh(name: str, files: dict[str, str], gates: list[str], env_only_g3: bool = False):
    print(f"\n=== CASE {name} (fresh=True, env_only_g3={env_only_g3}) ===", flush=True)
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
    repo.mkdir(parents=True)
    selftest.base_package(repo, case_dir)
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
        if env_only_g3:
            p = subprocess.run(
                ["lake", "exe", "fm_audit", "3", "Chan", "ChanTest.Probe"],
                cwd=fm,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            res["gates"]["3_env_only"] = {
                "rc": p.returncode,
                "stdout": p.stdout.strip(),
                "stderr": p.stderr.strip(),
            }
            print(f"  fm_audit 3 (env only): rc={p.returncode} stdout={p.stdout.strip()!r} stderr={p.stderr.strip()!r}", flush=True)
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


def main():
    files_nuclear = {
        "formal_math/Chan/Thm/Helper.lean": """module
public meta import Lean
public section
open Lean in
public meta def stripInfo (s : Syntax) : Syntax :=
  match s with
  | .node _ k args => .node .none k (args.map stripInfo)
  | .ident _ r v p => .ident .none r v p
  | .atom _ v => .atom .none v
  | .missing => .missing

open Lean in
@[macro Lean.Parser.Command.check]
public meta def expandCheck : Macro := fun _ => do
  let mkA (s : String) := Syntax.atom .none s
  let idUnused := mkIdent `hiddenUnused
  let idAuto := mkIdent `hiddenAutoImp
  let idAlpha := mkIdent `α
  let idVac := mkIdent `hiddenVacuous
  let idPart := mkIdent `hiddenPartial
  let idUnsafe := mkIdent `hiddenUnsafe
  let idFake := mkIdent `fakeImpl
  let idImpl := mkIdent `hiddenImplBy

  let baseOpt1 ← `(set_option pp.all false in public def $idUnused (x : Nat) : Nat := 0)
  let inCmd1 := baseOpt1.raw.setArg 0 (baseOpt1.raw[0]!.setArg 1 (mkIdent (Name.mkStr2 "linter" "unusedVariables")))

  let baseOpt2 ← `(set_option pp.all true in public def $idAuto (x : $idAlpha) : $idAlpha := x)
  let inCmd2 := baseOpt2.raw.setArg 0 (baseOpt2.raw[0]!.setArg 1 (mkIdent `autoImplicit))

  let vacCmd ← `(public theorem $idVac (x : Nat) (h0 : x = 0) (h1 : x = 1) : False := Nat.noConfusion (h0.symm.trans h1))

  let partBase ← `(public def $idPart (n : Nat) : Nat := $idPart n)
  let partMod := Syntax.node .none `Lean.Parser.Command.partial #[mkA ("par" ++ "tial")]
  let partDecl := partBase.raw.setArg 0 (partBase.raw[0]!.setArg 6 (mkNullNode #[partMod]))

  let unsafeBase ← `(public def $idUnsafe : Nat := 0)
  let unsafeMod := Syntax.node .none `Lean.Parser.Command.unsafe #[mkA ("un" ++ "safe")]
  let unsafeDecl := unsafeBase.raw.setArg 0 (unsafeBase.raw[0]!.setArg 5 (mkNullNode #[unsafeMod]))

  let fakeImplCmd ← `(public def $idFake : Nat := 999)
  let implName := Name.mkSimple ("implemented_" ++ "by")
  let attrSimple := Syntax.node .none `Lean.Parser.Attr.simple #[mkIdent implName, mkNullNode #[idFake]]
  let attrInst := Syntax.node .none `Lean.Parser.Term.attrInstance #[mkNullNode, attrSimple]
  let attrs := Syntax.node .none `Lean.Parser.Term.attributes #[mkA "@[", mkNullNode #[attrInst], mkA "]"]
  let implBase ← `(public def $idImpl : Nat := 1)
  let implDecl := implBase.raw.setArg 0 (implBase.raw[0]!.setArg 1 (mkNullNode #[attrs]))

  return stripInfo (mkNullNode #[inCmd1, inCmd2, vacCmd, partDecl, unsafeDecl, fakeImplCmd, implDecl])
""",
        "formal_math/Chan/Thm/Victim.lean": """module
public import Chan.Thm.Helper
public section
#check Nat
def useAll : Nat := hiddenUnused 1 + hiddenAutoImp 2 + hiddenPartial 0 + hiddenImplBy
""",
        "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
    }

    files_partial_env = {
        "formal_math/Chan.lean": """module
public section
partial def loop (n : Nat) : Nat := loop n
""",
        "formal_math/formalization.yaml": json.dumps({"nodes": {}}),
    }

    r1 = run_fresh("A1g_macro_stripinfo_all_green", files_nuclear, ["2", "3", "S", "7a", "8a", "8b", "9", "15"])
    r2 = run_fresh("A1h_partial_env_only", files_partial_env, [], env_only_g3=True)
    (OUT_ROOT / "batch6.json").write_text(json.dumps([r1, r2], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
