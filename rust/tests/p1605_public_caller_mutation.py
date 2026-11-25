import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUST_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = RUST_DIR.parent
FILES = [
    Path("src/theta_v0/policy_records/research-stats.json"),
    Path("src/theta_v0/backtest/runner.rs"),
    Path("src/theta_v0/backtest/metrics.rs"),
]
CMD = ["cargo", "test", "--lib", "p1605_public_", "--", "--test-threads=1"]


def stage_workspace(tmp_root: Path) -> Path:
    for entry in REPO_ROOT.iterdir():
        if entry.name in ("rust", ".git"):
            continue
        os.symlink(entry, tmp_root / entry.name)
    work_rust = tmp_root / "rust"
    shutil.copytree(RUST_DIR, work_rust, ignore=shutil.ignore_patterns("target", ".git"))
    return work_rust


def run_public_tests(label: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    print(label, flush=True)
    result = subprocess.run(CMD, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, flush=True)
    return result


def assert_nondefault_policy_passes(work_rust: Path, env: dict[str, str], base_record: dict) -> None:
    active = json.loads(json.dumps(base_record))
    active["fields"]["annualization_days"]["value"] = 126.0
    active["fields"]["cvar_tail"]["value"] = 0.25
    (work_rust / FILES[0]).write_text(json.dumps(active), encoding="utf-8")
    result = run_public_tests("P1605 PUBLIC NONDEFAULT EXPECT GREEN", work_rust, env)
    if result.returncode != 0 or "2 passed; 0 failed" not in result.stdout:
        sys.exit("nondefault green failed")


def assert_same_version_stale_values_fail_numeric_assertions(
    work_rust: Path, env: dict[str, str], originals: dict[Path, str], stale_record_v2: dict
) -> None:
    const = '\nconst P1605_OLD_RECORD: &str = r##"' + json.dumps(stale_record_v2) + '"##;\n'
    for rel_path in FILES[1:]:
        source = originals[rel_path]
        count = source.count("Some(ACTIVE_RESEARCH_STATS_JSON)")
        if count == 0:
            sys.exit(f"{rel_path} 无公开入口加载点")
        (work_rust / rel_path).write_text(
            source.replace("Some(ACTIVE_RESEARCH_STATS_JSON)", "Some(P1605_OLD_RECORD)") + const,
            encoding="utf-8",
        )
        print(f"MUTATED {rel_path} load_sites={count}", flush=True)
    result = run_public_tests("P1605 PUBLIC OLD CONSTANT MUTANT EXPECT RED", work_rust, env)
    if (
        result.returncode != 101
        or "0 passed; 2 failed" not in result.stdout
        or "assertion `left == right` failed" not in result.stdout
    ):
        sys.exit("mutant did not fail at numeric assertions")


def assert_restored_workspace_passes(work_rust: Path, env: dict[str, str], originals: dict[Path, str]) -> None:
    for rel_path, source in originals.items():
        (work_rust / rel_path).write_text(source, encoding="utf-8")
    print("RESTORED", flush=True)
    result = run_public_tests("P1605 PUBLIC RESTORED EXPECT GREEN", work_rust, env)
    if result.returncode != 0 or "2 passed; 0 failed" not in result.stdout:
        sys.exit("restored green failed")


def main() -> None:
    originals = {rel_path: (RUST_DIR / rel_path).read_text(encoding="utf-8") for rel_path in FILES}
    stale_record_v2 = json.loads(originals[FILES[0]])
    stale_record_v2["version"] = 2

    with tempfile.TemporaryDirectory(prefix="p1605-mutation-") as tmp:
        work_rust = stage_workspace(Path(tmp))
        # 变异体只许写专属子目录：与真实 rust/target 共用会让失败后的变异产物被原始树当作新鲜缓存。
        target_base = Path(os.environ.get("CARGO_TARGET_DIR", str(RUST_DIR / "target")))
        env = {**os.environ, "CARGO_TARGET_DIR": str(target_base / "p1605-mutation")}
        assert_nondefault_policy_passes(work_rust, env, stale_record_v2)
        assert_same_version_stale_values_fail_numeric_assertions(work_rust, env, originals, stale_record_v2)
        assert_restored_workspace_passes(work_rust, env, originals)

    print("P1605 MUTATION CHECK OK", flush=True)


if __name__ == "__main__":
    main()
