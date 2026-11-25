"""把每个夹具装入独立临时仓库，从入口重算门禁与审阅报告。

两类自测分开计数：
* 阻断门（1、2、3、6a、6b、15）：`must_red`、`must_green`、`must_unknown` 断言退出码与红码；
  另有一例 `fm_audit selfcheck` 核对门 3 的展开后检查。
* 审阅报告（S、7a、7b、8a、8b、9、10）：`report_cases/{finding,clean,unknown,known_limits}`
  断言 `run_gates.py --report` 里出现或不出现某条读数，报告退出码恒为 0。
"""

import argparse
import json
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
from threading import Event, Lock


HERE = Path(__file__).resolve().parent
GATES = ("1", "2", "3", "6a", "6b", "15")
REPORT_GATES = ("S", "7a", "7b", "8a", "8b", "9", "10")
REPORT_KINDS = ("finding", "clean", "unknown", "known_limits")
MAC_TEMP = Path("/Volumes/AgentStorage/fm/tmp")
MIN_FREE = 6 * 1024**3
SOURCES = ("run_gates.py", "pins.json", "Audit.lean", "EnvGates.lean", "SourceGates.lean",
           "Inventory.lean", "Perimeter.lean", "garbage-signoffs.yaml", "elaborators.tsv", "syntax-kinds.tsv")


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


def base_package(repo, fixture, warm=None):
    fm = repo / "formal_math"
    verification = fm / "verification"
    verification.mkdir(parents=True)
    for filename in SOURCES:
        if (HERE / filename).is_file():
            shutil.copy2(HERE / filename, verification)
    shutil.copy2(HERE.parent / "lean-toolchain", fm)
    shutil.copy2(HERE.parent / "lake-manifest.json", fm)
    for filename in ("formalization.yaml", "statement-lock.json"):
        shutil.copy2(HERE.parent / filename, fm)
    (fm / "ChanTest").mkdir()
    shutil.copy2(HERE.parent / "ChanTest/Probe.lean", fm / "ChanTest/Probe.lean")
    (fm / "Chan.lean").write_text("module\n")
    libs = {"Chan", "ChanTest"}
    lean_files = list((fixture / "formal_math").rglob("*.lean")) if fixture else []
    for path in lean_files:
        libs.add(path.relative_to(fixture / "formal_math").parts[0].removesuffix(".lean"))
    for lib in libs:
        (fm / lib).mkdir(exist_ok=True)
    uses_mathlib = any(re.search(r"import (Mathlib|Batteries|Aesop|Qq|Plausible|ProofWidgets)\b", p.read_text())
                       for p in lean_files)
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
        + '\n[[lean_lib]]\nname = "FMEnvGates"\nroots = ["verification.EnvGates", "verification.SourceGates", "verification.Perimeter", "verification.Inventory"]\n'
    )
    if warm is not None:
        # 预编译的审计程序产物；源码逐字相同，Lake 依哈希判定无需重建。
        shutil.copytree(warm, fm / ".lake/build", symlinks=True, dirs_exist_ok=True)


def warm_build(tmp):
    """先在一个空夹具里编好 fm_audit，供各夹具复用其构建产物。"""
    root = Path(tempfile.mkdtemp(prefix="fm-warm-", dir=tmp))
    base_package(root, None)
    fm = root / "formal_math"
    build = subprocess.run(["lake", "build", "fm_audit", "+ChanTest.Probe:olean"], cwd=fm,
                           capture_output=True, text=True)
    if build.returncode:
        raise ValueError("预编译 fm_audit 失败：\n" + build.stdout + build.stderr)
    return root, fm / ".lake/build"


def fixture_env(repo):
    scratch = repo / "tmp"
    scratch.mkdir()
    env = os.environ.copy()
    env.update(dict.fromkeys(("TMPDIR", "TMP", "TEMP"), str(scratch)))
    env.pop("GITHUB_HEAD_REF", None)
    return env


def lines_of(fixture, name):
    path = fixture / name
    return [line.strip() for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def run_blocking(repo, fixture, gate, env):
    fm = repo / "formal_math"
    if gate == "3" and (fixture / "environment-only.txt").is_file():
        # 源码必红样本另测前端；这里直接核对环境层也不能通过。
        mods = lines_of(fixture, "modules.txt") or ["Chan"]
        build = subprocess.run(["lake", "build", *(f"+{m}:olean" for m in mods), "+ChanTest.Probe:olean"],
                               cwd=fm, env=env, capture_output=True, text=True)
        if build.returncode:
            raise ValueError(build.stdout + build.stderr)
        return subprocess.run(["lake", "exe", "fm_audit", "3", *mods, "ChanTest.Probe"],
                              cwd=fm, env=env, capture_output=True, text=True), None
    if (fixture / "source-only.txt").is_file():
        # 跳过依赖顺序，直接让前端审一个文件：核对审计期不执行被审代码。
        module, path, *deps = lines_of(fixture, "source-only.txt")
        if deps:
            build = subprocess.run(["lake", "build", *(f"+{m}:olean" for m in deps)],
                                   cwd=fm, env=env, capture_output=True, text=True)
            if build.returncode:
                raise ValueError(build.stdout + build.stderr)
        result = subprocess.run(["lake", "exe", "fm_audit", "source", module, path, gate],
                                cwd=fm, env=env, capture_output=True, text=True)
        try:
            _, issues, _ = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise ValueError(result.stdout + result.stderr)
        rows = [f"GATE{gate} RED {path}:{line} TOKEN {detail}"
                for number, line, detail in issues if number == gate]
        return result, rows
    return subprocess.run(
        [sys.executable, str(fm / "verification/run_gates.py"), "--repo-root", str(repo), "--gate", gate],
        cwd=repo, env=env, capture_output=True, text=True, check=False,
    ), None


def exercise(tmp, warm, fixture, gate, color):
    expected = set((fixture / "expect.txt").read_text().split()) if color == "red" else set()
    if color == "red" and not expected:
        raise ValueError(f"{fixture} 没有期望代码")
    with fixture_repo(tmp, gate) as repo:
        env = fixture_env(repo)
        expected_exit = {"green": 0, "red": 1, "unknown": 2}[color]
        base_package(repo, fixture, warm)
        if (fixture / "lean-version.txt").is_file():
            fake = repo / "fixture-bin"
            fake.mkdir()
            lean = fake / "lean"
            lean.write_text("#!/bin/sh\nprintf '%s\\n' 'Lean (version 4.35.0, fixture)'\n")
            lean.chmod(0o755)
            env["PATH"] = str(fake) + os.pathsep + env["PATH"]
        if gate == "6b":
            git(repo, "init", "-q", "-b", "main")
            # 自测的临时目录不是被审改动。
            (repo / ".git/info/exclude").write_text("/tmp/\n/fixture-bin/\n")
            git(repo, "add", "formal_math")
            git(repo, "commit", "-qm", "创建夹具基线")
            git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
            git(repo, "switch", "-qc", "proof/fixture")
            branch_file = fixture / "branch.txt"
            if branch_file.is_file():
                git(repo, "switch", "-qc", branch_file.read_text().strip())
        shutil.copytree(fixture / "formal_math", repo / "formal_math", dirs_exist_ok=True)
        for line in lines_of(fixture, "symlinks.txt"):
            link, target = line.split()
            (repo / link).symlink_to(target)
        if gate == "6b":
            git(repo, "add", "formal_math")
            git(repo, "commit", "-qm", "应用门禁夹具")
            for name in lines_of(fixture, "root-files.txt"):
                (repo / name).write_text("未跟踪的仓根文件\n")
            head_mode = fixture / "head.txt"
            if head_mode.is_file():
                mode = head_mode.read_text().strip()
                if mode != "symbolic-overrides-ci":
                    git(repo, "switch", "--detach", "HEAD")
                if mode == "symbolic-overrides-ci":
                    env["GITHUB_HEAD_REF"] = "proof/ci"
                elif mode != "absent":
                    env["GITHUB_HEAD_REF"] = mode
        result, synthetic = run_blocking(repo, fixture, gate, env)
        # 审计期不得执行被审代码：夹具里的初始化器若被执行会写下这些文件。
        leaked = [p for p in lines_of(fixture, "forbid-file.txt") if (repo / p).exists()]
    lines = synthetic if synthetic is not None else result.stdout.splitlines()
    rows = [re.fullmatch(rf"GATE{gate} RED (\S+):(\S+) ([A-Z_]+) .+", line) for line in lines]
    actual = {row[3] for row in rows if row}
    ok = result.returncode == expected_exit and actual == expected and all(rows) and not leaked
    if (fixture / "expect_decls.txt").is_file():
        ok = ok and {row[2] for row in rows if row} == set(
            (fixture / "expect_decls.txt").read_text().split()
        )
    output = result.stdout + result.stderr
    missing = [d for d in lines_of(fixture, "expect_detail.txt") if d not in output]
    ok = ok and not missing
    if gate == "3" and fixture.name == "private-proof":
        ok = ok and bool(rows) and all(row and row[2].startswith("_private.") for row in rows)
    show = lambda codes: ",".join(sorted(codes)) or "—"
    print(f"{gate}\t{fixture.name}\t{show(expected)}\t{show(actual)}\t"
          f"{result.returncode}\t{'通过' if ok else '失败'}", flush=True)
    if not ok:
        if leaked:
            print(f"{fixture}: 审计期执行了被审代码，留下 {leaked}", file=sys.stderr)
        if missing:
            print(f"{fixture}: 输出缺少 {missing}", file=sys.stderr)
        print(output, file=sys.stderr, end="")
    return ok


def exercise_report(tmp, warm, fixture, gate, kind):
    words = lambda name: set((fixture / name).read_text().split()) if (fixture / name).is_file() else set()
    expected = words("expect.txt")
    expected_exit = int((fixture / "report-exit.txt").read_text()) if (fixture / "report-exit.txt").is_file() else 0
    if kind == "finding" and not expected:
        raise ValueError(f"{fixture} 没有期望读数")
    if kind == "known_limits" and not (fixture / "README.md").is_file():
        raise ValueError("已知边界须附说明")
    with fixture_repo(tmp, f"report-{gate}") as repo:
        env = fixture_env(repo)
        base_package(repo, fixture, warm)
        shutil.copytree(fixture / "formal_math", repo / "formal_math", dirs_exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(repo / "formal_math/verification/run_gates.py"),
             "--repo-root", str(repo), "--report"],
            cwd=repo, env=env, capture_output=True, text=True, check=False,
        )
    readings = []
    try:
        document = json.loads(result.stdout)
        for row in document["declarations"]:
            readings += [(row["declaration"], r) for r in row["readings"][gate]]
    except (ValueError, KeyError, TypeError):
        document = None
    findings = [(name, r) for name, r in readings if r["status"] == "finding"]
    unknown = [(name, r) for name, r in readings if r["status"] == "unknown"]
    codes = {r["code"] for _, r in findings}
    ok = result.returncode == expected_exit
    if expected_exit:
        pass  # 夹具本身不能构建：报告按工具出错退 2，不再看读数。
    elif document is None:
        ok = False
    elif kind == "finding":
        ok = ok and codes == expected
        if (fixture / "expect_decls.txt").is_file():
            ok = ok and {name for name, _ in findings} == words("expect_decls.txt")
    elif kind == "unknown":
        ok = ok and bool(unknown)
    else:
        ok = ok and not findings and not unknown
    certified = words("expect_certified.txt")
    if certified:
        ok = ok and {r["code"] for _, r in findings if r["evidence"] == "certified"} == certified
    show = lambda items: ",".join(sorted(items)) or "—"
    actual = codes | ({"UNKNOWN"} if unknown else set())
    print(f"报告{gate}\t{fixture.name}\t{kind}:{show(expected)}\t{show(actual)}\t"
          f"{result.returncode}\t{'通过' if ok else '失败'}", flush=True)
    if not ok:
        print(result.stdout[-4000:] + result.stderr[-4000:], file=sys.stderr, end="")
    return ok


def selfcheck(tmp, warm):
    """门 3 展开后检查的固定样例：宏生成的选项、属性、命令都要被看到。"""
    with fixture_repo(tmp, "selfcheck") as repo:
        env = fixture_env(repo)
        base_package(repo, None, warm)
        result = subprocess.run(["lake", "exe", "fm_audit", "selfcheck"], cwd=repo / "formal_math",
                                env=env, capture_output=True, text=True)
    ok = result.returncode == 0
    print(f"3\tselfcheck-expansion\t—\t—\t{result.returncode}\t{'通过' if ok else '失败'}", flush=True)
    if not ok:
        print(result.stdout + result.stderr, file=sys.stderr, end="")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--only", help="只跑名字含此子串的夹具")
    parser.add_argument("gates", nargs="*", metavar="门禁")
    args = parser.parse_args()
    selected = args.gates or GATES + REPORT_GATES
    if args.jobs < 1 or not set(selected) <= set(GATES + REPORT_GATES):
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
        if gate in GATES:
            for color in ("red", "green", "unknown"):
                group = f"must_{color}"
                fixtures = sorted((HERE / group / f"g{gate}").glob("*/"))
                if not fixtures and color in ("red", "green"):
                    print(f"门禁 {gate} 缺少 {color} 夹具", file=sys.stderr)
                    ok = False
                cases += [(f, gate, color, group) for f in fixtures]
            if gate == "3" and not args.only:
                cases.append((None, gate, "selfcheck", "selfcheck"))
        else:
            for kind in REPORT_KINDS:
                group = f"report_{kind}"
                fixtures = sorted((HERE / "report_cases" / kind / f"g{gate}").glob("*/"))
                if not fixtures and kind in ("finding", "clean"):
                    print(f"报告 {gate} 缺少 {kind} 样本", file=sys.stderr)
                    ok = False
                cases += [(f, gate, kind, group) for f in fixtures]
    if args.only:
        cases = [c for c in cases if c[0] is not None and args.only in str(c[0])]
    for _, _, _, group in cases:
        attempted[group] += 1

    stop = Event()
    disk_lock = Lock()

    def disk_ok():
        with disk_lock:
            free = shutil.disk_usage("/").free
            if free < MIN_FREE:
                if not stop.is_set():
                    print(f"根分区可用 {free / 1024**3:.2f} GiB，低于 6 GiB；停止派发夹具。",
                          file=sys.stderr)
                stop.set()
            return not stop.is_set()

    try:
        warm_root, warm = warm_build(tmp)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    def run(case):
        fixture, gate, color, group = case
        if not disk_ok():
            return group, False
        try:
            if color == "selfcheck":
                success = selfcheck(tmp, warm)
            elif gate in GATES:
                success = exercise(tmp, warm, fixture, gate, color)
            else:
                success = exercise_report(tmp, warm, fixture, gate, color)
            return group, disk_ok() and success
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"{fixture}: {exc}", file=sys.stderr)
            return group, False

    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for group, success in pool.map(run, cases):
                passed[group] += success
                ok = success and ok
    finally:
        shutil.rmtree(warm_root)
    blocking = ("must_red", "must_green", "must_unknown", "selfcheck")
    report = tuple(f"report_{kind}" for kind in REPORT_KINDS)
    for title, groups in (("阻断门", blocking), ("报告回归", report)):
        total = sum(attempted[g] for g in groups)
        print(f"{title}：{sum(passed[g] for g in groups)}/{total}（"
              + "；".join(f"{g}={passed[g]}/{attempted[g]}" for g in groups) + "）")
    return int(not ok)


if __name__ == "__main__":
    sys.exit(main())
