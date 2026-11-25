"""Shared serial probe harness for #2312 R4 review."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path("/Volumes/AgentStorage/wt-2312-d-review")
VERIF = WT / "formal_math/verification"
PKG_CACHE = Path("/Volumes/AgentStorage/fm/lake/infra-2312-b-env-gates-2428b08ce810d112/packages")
TMP_ROOT = Path("/Volumes/AgentStorage/fm/tmp/2312-d-review")
CASES_DIR = TMP_ROOT / "cases"
WORK_DIR = TMP_ROOT / "work"
WARM_DIR = TMP_ROOT / "warm"
MIN_FREE = 6 * 1024**3

SOURCES = (
    "run_gates.py",
    "pins.json",
    "Audit.lean",
    "EnvGates.lean",
    "SourceGates.lean",
    "garbage-signoffs.yaml",
)


def free_gib() -> float:
    return shutil.disk_usage("/").free / (1024**3)


def check_disk(label: str) -> float:
    gb = free_gib()
    print(f"[DISK] {label}: / free = {gb:.3f} GiB", flush=True)
    if shutil.disk_usage("/").free < MIN_FREE:
        raise SystemExit(f"STOP_DISK_LOW: / free = {gb:.3f} GiB < 6.000 GiB at {label}")
    return gb


def base_env(repo: Path) -> dict:
    scratch = repo / "tmp"
    scratch.mkdir(exist_ok=True)
    env = os.environ.copy()
    elan_bin = str(Path.home() / ".elan/bin")
    if elan_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = elan_bin + os.pathsep + env.get("PATH", "")
    env["TMPDIR"] = str(scratch)
    env["TMP"] = str(scratch)
    env["TEMP"] = str(scratch)
    env.pop("GITHUB_HEAD_REF", None)
    return env


def needs_external_packages(files: dict[str, str]) -> bool:
    for content in files.values():
        for root in ("Mathlib", "Batteries", "Aesop", "Qq", "Plausible", "ProofWidgets", "Cli"):
            if f"import {root}" in content:
                return True
    return False


def build_base_package(
    repo: Path,
    files: dict[str, str],
    warm_build_dir: Path | None = None,
    custom_lakefile: str | None = None,
    force_mathlib: bool = False,
):
    fm = repo / "formal_math"
    verification = fm / "verification"
    verification.mkdir(parents=True, exist_ok=True)
    for fn in SOURCES:
        shutil.copy2(VERIF / fn, verification / fn)
    shutil.copy2(WT / "formal_math/lean-toolchain", fm / "lean-toolchain")
    shutil.copy2(WT / "formal_math/lake-manifest.json", fm / "lake-manifest.json")
    for fn in ("formalization.yaml", "statement-lock.json"):
        shutil.copy2(WT / "formal_math" / fn, fm / fn)
    (fm / "ChanTest").mkdir(exist_ok=True)
    shutil.copy2(WT / "formal_math/ChanTest/Probe.lean", fm / "ChanTest/Probe.lean")
    (fm / "Chan.lean").write_text("module\n")

    libs = {"Chan", "ChanTest"}
    for rel in files:
        if rel.startswith("formal_math/") and rel.endswith(".lean"):
            parts = Path(rel).relative_to("formal_math").parts
            libs.add(parts[0].removesuffix(".lean"))
    for lib in libs:
        (fm / lib).mkdir(exist_ok=True)

    uses_pkgs = force_mathlib or needs_external_packages(files)
    if uses_pkgs:
        (fm / ".lake").mkdir(exist_ok=True)
        pkg_link = fm / ".lake/packages"
        if not pkg_link.exists():
            pkg_link.symlink_to(PKG_CACHE)

    if custom_lakefile is not None:
        (fm / "lakefile.toml").write_text(custom_lakefile)
    else:
        (fm / "lakefile.toml").write_text(
            'name = "fixture"\ndefaultTargets = ["Chan"]\n\n'
            '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
            'linter.unusedVariables = true\n'
            + (
                '\n[[require]]\nname = "mathlib"\n'
                'git = "https://github.com/leanprover-community/mathlib4.git"\n'
                'rev = "v4.36.0"\n'
                if uses_pkgs
                else ""
            )
            + "".join(
                f'\n[[lean_lib]]\nname = "{lib}"\nglobs = ["{lib}.*"]\n'
                for lib in sorted(libs)
            )
            + '\n[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n'
            + '\n[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
        )

    if warm_build_dir is not None and warm_build_dir.is_dir():
        shutil.copytree(warm_build_dir, fm / ".lake/build", symlinks=True, dirs_exist_ok=True)

    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def ensure_warm() -> Path:
    WARM_DIR.mkdir(parents=True, exist_ok=True)
    warm_build = WARM_DIR / "formal_math/.lake/build"
    exe = warm_build / "bin/fm_audit"
    if exe.is_file():
        return warm_build
    check_disk("before warm_build")
    build_base_package(WARM_DIR, {}, warm_build_dir=None)
    env = base_env(WARM_DIR)
    res = subprocess.run(
        ["lake", "build", "fm_audit", "+ChanTest.Probe:olean"],
        cwd=WARM_DIR / "formal_math",
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    check_disk("after warm_build")
    if res.returncode != 0:
        raise RuntimeError(f"warm_build failed ({res.returncode}):\n{res.stdout}\n{res.stderr}")
    return warm_build


def save_case_files(case_name: str, files: dict[str, str]):
    case_dir = CASES_DIR / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    for rel, content in files.items():
        p = case_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def run_cmd(cwd: Path, args: list[str], env: dict, timeout: int = 180) -> dict:
    res = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    out = res.stdout
    err = res.stderr
    if "Building Mathlib" in out or "Building Mathlib" in err:
        raise SystemExit("ABORT: detected Mathlib build from source!")
    return {
        "cmd": " ".join(args),
        "rc": res.returncode,
        "stdout": out,
        "stderr": err,
    }


def run_case(
    warm: Path,
    case_name: str,
    files: dict[str, str],
    gates: list[str],
    run_build: bool = True,
    env_only_mods: list[str] | None = None,
    custom_lakefile: str | None = None,
    force_mathlib: bool = False,
    sentinel_paths: list[Path] | None = None,
    extra_fn=None,
) -> dict:
    disk_before = check_disk(f"before {case_name}")
    save_case_files(case_name, files)
    if custom_lakefile is not None:
        (CASES_DIR / case_name / "formal_math/lakefile.toml").write_text(custom_lakefile)

    if sentinel_paths:
        for sp in sentinel_paths:
            if sp.exists():
                sp.unlink()

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    repo = Path(tempfile.mkdtemp(prefix=f"{case_name}-", dir=WORK_DIR))
    record = {"case": case_name, "disk_before_gib": round(disk_before, 3), "steps": []}
    try:
        build_base_package(
            repo,
            files,
            warm_build_dir=warm,
            custom_lakefile=custom_lakefile,
            force_mathlib=force_mathlib,
        )
        env = base_env(repo)
        fm = repo / "formal_math"

        if run_build:
            lean_mods = []
            for rel in sorted(files):
                if rel.startswith("formal_math/") and rel.endswith(".lean"):
                    mod = ".".join(Path(rel).relative_to("formal_math").with_suffix("").parts)
                    if not mod.startswith("verification."):
                        lean_mods.append(f"+{mod}:olean")
            build_args = ["lake", "build", "--wfail", *lean_mods]
            step = run_cmd(fm, build_args, env)
            record["steps"].append({"name": "build_wfail", **step})

        if env_only_mods is not None:
            b = run_cmd(
                fm,
                ["lake", "build", *(f"+{m}:olean" for m in env_only_mods), "+ChanTest.Probe:olean"],
                env,
            )
            record["steps"].append({"name": "env_build", **b})
            if b["rc"] == 0:
                a = run_cmd(fm, ["lake", "exe", "fm_audit", "3", *env_only_mods, "ChanTest.Probe"], env)
                record["steps"].append({"name": "fm_audit_3_env", **a})

        for g in gates:
            if g == "report":
                step = run_cmd(
                    repo,
                    [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--report"],
                    env,
                )
                record["steps"].append({"name": "report", **step})
            else:
                step = run_cmd(
                    repo,
                    [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", g],
                    env,
                )
                record["steps"].append({"name": f"gate_{g}", **step})

        if extra_fn is not None:
            extra_fn(repo, fm, env, record)

        if sentinel_paths:
            sent = {}
            for sp in sentinel_paths:
                sent[str(sp)] = sp.read_text() if sp.exists() else None
            record["sentinels"] = sent
    finally:
        shutil.rmtree(repo, ignore_errors=True)
        disk_after = free_gib()
        record["disk_after_gib"] = round(disk_after, 3)

    print(f"=== {case_name} ===", flush=True)
    for st in record["steps"]:
        print(f"  [{st['name']}] rc={st['rc']}", flush=True)
        if st["stdout"].strip():
            print("    STDOUT:", st["stdout"].strip()[:800], flush=True)
        if st["stderr"].strip():
            print("    STDERR:", st["stderr"].strip()[:800], flush=True)
    if "sentinels" in record:
        print("  SENTINELS:", record["sentinels"], flush=True)
    check_disk(f"after {case_name}")
    return record
