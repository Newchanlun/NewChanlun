"""把每个夹具装入独立临时仓库，从入口重算门禁。"""

import argparse
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import Event


HERE = Path(__file__).resolve().parent
GATES = ("1", "2", "3", "6a", "6b", "7a", "7b", "S", "8a", "8b", "9", "10", "15")
MAC_TEMP = Path("/Volumes/AgentStorage/fm/tmp")
MIN_FREE = 6 * 1024**3


def temporary_root():
    configured = MAC_TEMP if sys.platform == "darwin" else os.environ.get("TMPDIR")
    if not configured:
        raise ValueError("请先 source scripts/fm_env.sh")
    root = Path(configured).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{root} 不是临时目录")
    if sys.platform == "darwin" and root.stat().st_dev == Path("/System/Volumes/Data").stat().st_dev:
        raise ValueError(f"{root} 未落在独立卷上")
    return root


@contextmanager
def fixture_repo(tmp, gate):
    # 仅清理由 mkdtemp 创建的本夹具；不会递归进入共享 packages 符号链接。
    repo = Path(tempfile.mkdtemp(prefix=f"fm-g{gate}-", dir=tmp))
    try:
        yield repo
    finally:
        shutil.rmtree(repo)


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=FM 自测",
         "-c", "user.email=fm-fixture@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def base_package(repo, fixture):
    fm = repo / "formal_math"
    verification = fm / "verification"
    verification.mkdir(parents=True)
    for filename in ("run_gates.py", "pins.json", "Audit.lean", "EnvGates.lean", "SourceGates.lean",
                     "garbage-signoffs.yaml"):
        shutil.copy2(HERE / filename, verification)
    shutil.copy2(HERE.parent / "lean-toolchain", fm)
    shutil.copy2(HERE.parent / "lake-manifest.json", fm)
    for filename in ("formalization.yaml", "statement-lock.json"):
        shutil.copy2(HERE.parent / filename, fm)
    (fm / "ChanTest").mkdir()
    shutil.copy2(HERE.parent / "ChanTest/Probe.lean", fm / "ChanTest/Probe.lean")
    (fm / "Chan.lean").write_text("module\n")
    libs = {"Chan", "ChanTest"}
    for path in (fixture / "formal_math").rglob("*.lean"):
        libs.add(path.relative_to(fixture / "formal_math").parts[0].removesuffix(".lean"))
    for lib in libs:
        (fm / lib).mkdir(exist_ok=True)
    uses_mathlib = any("import Mathlib." in p.read_text()
                       for p in (fixture / "formal_math").rglob("*.lean"))
    if uses_mathlib:
        (fm / ".lake").mkdir()
        (fm / ".lake/packages").symlink_to((HERE.parent / ".lake/packages").resolve())
    (fm / "lakefile.toml").write_text(
        'name = "fixture"\ndefaultTargets = ["Chan"]\n\n'
        '[leanOptions]\nautoImplicit = false\nrelaxedAutoImplicit = false\n'
        'linter.unusedVariables = true\n'
        + ('\n[[require]]\nname = "mathlib"\ngit = "https://github.com/leanprover-community/mathlib4.git"\n'
           'rev = "v4.36.0"\n' if uses_mathlib else "")
        + "".join(
            f'\n[[lean_lib]]\nname = "{lib}"\nglobs = ["{lib}.*"]\n'
            for lib in sorted(libs)
        )
        + '\n[[lean_exe]]\nname = "fm_audit"\nroot = "verification.Audit"\nsupportInterpreter = true\n'
        + '\n[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates"]\n'
    )


def exercise(tmp, fixture, gate, color):
    expected = set((fixture / "expect.txt").read_text().split()) if color == "red" else set()
    if color == "red" and not expected:
        raise ValueError(f"{fixture} 没有期望代码")
    with fixture_repo(tmp, gate) as repo:
        scratch = repo / "tmp"
        scratch.mkdir()
        env = os.environ.copy()
        env.update(dict.fromkeys(("TMPDIR", "TMP", "TEMP"), str(scratch)))
        env.pop("GITHUB_HEAD_REF", None)
        expected_exit = {"green": 0, "red": 1, "unknown": 2, "known_limits": 0}[color]
        base_package(repo, fixture)
        if (fixture / "lean-version.txt").is_file():
            fake = repo / "fixture-bin"
            fake.mkdir()
            lean = fake / "lean"
            lean.write_text("#!/bin/sh\nprintf '%s\\n' 'Lean (version 4.35.0, fixture)'\n")
            lean.chmod(0o755)
            env["PATH"] = str(fake) + os.pathsep + env["PATH"]
        if gate == "6b":
            git(repo, "init", "-q", "-b", "main")
            git(repo, "add", "formal_math")
            git(repo, "commit", "-qm", "创建夹具基线")
            git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
            git(repo, "switch", "-qc", "proof/fixture")
            branch_file = fixture / "branch.txt"
            if branch_file.is_file():
                git(repo, "switch", "-qc", branch_file.read_text().strip())
        shutil.copytree(fixture / "formal_math", repo / "formal_math", dirs_exist_ok=True)
        if gate == "6b":
            git(repo, "add", "formal_math")
            git(repo, "commit", "-qm", "应用门禁夹具")
            head_mode = fixture / "head.txt"
            if head_mode.is_file():
                mode = head_mode.read_text().strip()
                if mode != "symbolic-overrides-ci":
                    git(repo, "switch", "--detach", "HEAD")
                if mode == "symbolic-overrides-ci":
                    env["GITHUB_HEAD_REF"] = "proof/ci"
                elif mode != "absent":
                    env["GITHUB_HEAD_REF"] = mode
        if gate == "3" and (fixture / "environment-only.txt").is_file():
            # 源码必红样本另测前端；这里直接核对手写声明在环境层也不能通过。
            fm = repo / "formal_math"
            build = subprocess.run(
                ["lake", "build", "+Chan:olean", "+ChanTest.Probe:olean"],
                cwd=fm, env=env, capture_output=True, text=True,
            )
            if build.returncode:
                raise ValueError(build.stdout + build.stderr)
            result = subprocess.run(
                ["lake", "exe", "fm_audit", "3", "Chan", "ChanTest.Probe"],
                cwd=fm, env=env, capture_output=True, text=True,
            )
        else:
            result = subprocess.run(
                [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
                 "--repo-root", str(repo), "--gate", gate],
                cwd=repo, env=env, capture_output=True, text=True, check=False,
            )
    rows = [
        re.fullmatch(rf"GATE{gate} RED (\S+):(\S+) ([A-Z_]+) .+", line)
        for line in result.stdout.splitlines()
    ]
    actual = {row[3] for row in rows if row}
    ok = result.returncode == expected_exit and actual == expected and all(rows)
    if (fixture / "expect_decls.txt").is_file():
        ok = ok and {row[2] for row in rows if row} == set(
            (fixture / "expect_decls.txt").read_text().split()
        )
    if gate == "3" and fixture.name == "private-proof":
        ok = ok and bool(rows) and all(row and row[2].startswith("_private.") for row in rows)
    show = lambda codes: ",".join(sorted(codes)) or "—"
    print(f"{gate}\t{fixture.name}\t{show(expected)}\t{show(actual)}\t"
          f"{result.returncode}\t{'通过' if ok else '失败'}", flush=True)
    if not ok:
        print(result.stdout + result.stderr, file=sys.stderr, end="")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("gates", nargs="*", metavar="门禁")
    args = parser.parse_args()
    selected = args.gates or GATES
    if args.jobs < 1 or not set(selected) <= set(GATES):
        parser.error("并行数须为正整数，门禁须为已实现编号")
    try:
        tmp = temporary_root()
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print("门禁\t样本\t期望代码\t实际代码\t退出码\t自测", flush=True)
    ok = True
    attempted, passed = Counter(), Counter()
    cases = []
    for gate in selected:
        for color in ("red", "green", "unknown", "known_limits"):
            group = color if color == "known_limits" else f"must_{color}"
            fixtures = sorted((HERE / group / f"g{gate}").glob("*/"))
            if not fixtures and color in ("red", "green"):
                print(f"门禁 {gate} 缺少 {color} 夹具", file=sys.stderr)
                ok = False
            for fixture in fixtures:
                attempted[group] += 1
                cases.append((fixture, gate, color, group))

    stop = Event()

    def disk_ok():
        if sys.platform != "darwin":
            return True
        free = shutil.disk_usage("/").free
        if free < MIN_FREE:
            if not stop.is_set():
                print(f"内置盘可用 {free / 1024**3:.2f} GiB，低于 6 GiB；停止派发夹具。",
                      file=sys.stderr)
            stop.set()
        return not stop.is_set()

    def run(case):
        fixture, gate, color, group = case
        if not disk_ok():
            return group, False
        try:
            if color == "known_limits" and not (fixture / "README.md").is_file():
                raise ValueError("已知边界须附说明")
            success = exercise(tmp, fixture, gate, color)
            return group, disk_ok() and success
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"{fixture}: {exc}", file=sys.stderr)
            return group, False

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for group, success in pool.map(run, cases):
            passed[group] += success
            ok = success and ok
    print("；".join(f"{g}={passed[g]}/{attempted[g]}"
                   for g in ("must_red", "must_green", "must_unknown", "known_limits")))
    return int(not ok)


if __name__ == "__main__":
    sys.exit(main())
