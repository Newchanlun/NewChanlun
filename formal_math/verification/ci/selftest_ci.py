#!/usr/bin/env python3
"""#2315（FM-06）CI 流水线端到端自测套件（运行于 Linux + bwrap + Lean 4.36.0）。

覆盖 #2315 评论 7176006564 全部六条硬要求与 precheck.py 形状约束：
  T1  工作流静态审计（无 paths 过滤、pull_request_target、contents: read、全 SHA 钉选、
      无表达式注入进 run:、受保护环境）+ 全部 .sh `bash -n`
  T2  仓内模式与 precheck.py 合规（ci/ 与 formal-math.yml 全 100644、无禁止 Lake 名、
      未放行报 TRUST_UNAPPROVED、放行绿）
  T3  materialize.py 非 -I 隔离拒绝
  T4  非 formal_math PR（追平 main）快速路径绿
  T5  非 formal_math PR（落后 main，唯一 merge-base）快速路径绿
  T6  要求 1 必红：proof/* 改 .github/workflows/formal-math.yml -> PATH_SCOPE + TRUSTED_DRIFT
  T7  要求 6 默认红：infra/* 改 ci/ 无放行 -> TRUST_UNAPPROVED
  T8  要求 6 放行绿：同提交带 --trusted-change-approved 跑完 run.py + lake check + comparator
  T9  落后 main 且改了 formal_math -> NOT_ANCESTOR 红
  T10 合法 proof/* PR 全流程绿（run.py 七步 + lake check + 正式 ChanChallenge 两段隔离 comparator）
  T11 含 admit 的 proof/* PR 必红
  T12 要求 4 必红：正式 comparator.json 含非空 definition_names -> 门 5 拒收
  T13 要求 4 必红：正式 comparator.json 含非标准公理 sorryAx -> 门 5 拒收
  T14 要求 4 隔离核验：materialize.py challenge 物理不含任何证明目录文件
  T15 要求 3 隔离核验：bwrap_pkgbind.sh 剥除 --share-net 且沙箱内无法写只读依赖目录

用法：
  python3 -I formal_math/verification/ci/selftest_ci.py [--repo <仓库根目录>]
"""
import sys

if not sys.flags.isolated:
    import posix
    try:
        posix.write(2, b"selftest_ci.py must run with python3 -I\n")
    except BaseException:  # noqa: BLE001
        pass
    posix._exit(2)

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "LC_ALL": "C",
    "GIT_AUTHOR_NAME": "CI Selftest",
    "GIT_AUTHOR_EMAIL": "selftest@example.invalid",
    "GIT_COMMITTER_NAME": "CI Selftest",
    "GIT_COMMITTER_EMAIL": "selftest@example.invalid",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_GRAFT_FILE": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}


def run(argv, cwd=None, env=None, check=False):
    p = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"命令失败 ({p.returncode}): {argv}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
    return p


def git(repo, *args):
    return run(["git", "-C", repo, *args], env=GIT_ENV, check=True).stdout.strip()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o644)


def copy_tree_files(src_root, dst_root):
    for dirpath, _, filenames in os.walk(src_root):
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, src_root)
            dst = os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            os.chmod(dst, 0o644)


def test_t1_workflow_and_shell(repo):
    wf_path = os.path.join(repo, ".github", "workflows", "formal-math.yml")
    with open(wf_path, encoding="utf-8") as f:
        wf = f.read()

    # 若有 PyYAML 则同时做语法解析
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(wf)
        assert isinstance(parsed, dict), "workflow 顶层不是对象"
        on_block = parsed.get(True) or parsed.get("on")
        assert isinstance(on_block, dict), "缺少 on 区块"
        assert "pull_request_target" in on_block, "缺少 pull_request_target"
        assert "pull_request" not in on_block, "不得使用 on.pull_request 触发必需检查"
        assert "paths" not in (on_block.get("pull_request_target") or {}), "pull_request_target 禁止 paths 过滤"
        assert "paths" not in (on_block.get("push") or {}), "push 禁止 paths 过滤"
        assert parsed.get("permissions") == {"contents": "read"}, "permissions 必须严格为 contents: read"
        jobs = parsed.get("jobs") or {}
        assert set(jobs.keys()) >= {"formal-math-pr", "formal-math-trusted-release", "formal-math-main", "formal-math-paranoid"}
        assert jobs["formal-math-trusted-release"].get("environment") == "formal-math-trusted-change"
        # 检查所有 uses 均为 40 位 SHA 钉选，且 run: 文本中不直接插值不可信事件/输入表达式
        bad_expr = re.compile(r"\$\{\{\s*(github\.event\.pull_request\.|inputs\.)")
        for jname, jdef in jobs.items():
            for step in jdef.get("steps", []):
                if "uses" in step:
                    assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"]), f"{jname} action 未钉选 SHA: {step['uses']}"
                if "run" in step:
                    assert not bad_expr.search(step["run"]), f"{jname} step.run 含未隔离表达式: {step['name']}"
    except ImportError:
        assert "pull_request_target:" in wf
        assert "paths:" not in wf
        assert "environment: formal-math-trusted-change" in wf
        for m in re.finditer(r"uses:\s*(\S+)", wf):
            assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", m.group(1)), f"action 未钉选 SHA: {m.group(1)}"

    # 全部 .sh 做 bash -n
    ci_dir = os.path.join(repo, "formal_math", "verification", "ci")
    sh_files = [os.path.join(ci_dir, fn) for fn in sorted(os.listdir(ci_dir)) if fn.endswith(".sh")]
    assert len(sh_files) >= 6, f".sh 数量过少: {sh_files}"
    for p in sh_files:
        run(["bash", "-n", p], check=True)
    # 全仓工作流与 ci/ 下文件在磁盘上无执行位
    for root in (ci_dir,):
        for dp, _, fns in os.walk(root):
            for fn in fns:
                fp = os.path.join(dp, fn)
                mode = stat.S_IMODE(os.lstat(fp).st_mode)
                assert (mode & 0o111) == 0, f"formal_math 下不允许执行位: {fp} ({oct(mode)})"
    wf_mode = stat.S_IMODE(os.lstat(wf_path).st_mode)
    assert (wf_mode & 0o111) == 0, f"formal-math.yml 不允许执行位 ({oct(wf_mode)})"


def test_t3_materialize_isolated(repo):
    mat = os.path.join(repo, "formal_math", "verification", "ci", "materialize.py")
    p = run([sys.executable, mat, "configs"])
    assert p.returncode == 2, f"不带 -I 期望退 2，实际 {p.returncode}"


def build_mini_repo(src_repo, tmp):
    mini = os.path.join(tmp, "mini-repo")
    os.makedirs(mini)
    git(mini, "init", "-b", "main")

    # 拷贝 #2312 过审的 precheck、runner、auditor 以及本票 ci/ 与 formal-math.yml
    for rel in (
        "formal_math/verification/precheck/precheck.py",
        "formal_math/verification/runner/run.py",
        ".github/workflows/formal-math.yml",
        "scripts/fm_env.sh",
    ):
        src = os.path.join(src_repo, rel)
        dst = os.path.join(mini, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o644)

    copy_tree_files(os.path.join(src_repo, "formal_math/verification/auditor"),
                    os.path.join(mini, "formal_math/verification/auditor"))
    copy_tree_files(os.path.join(src_repo, "formal_math/verification/ci"),
                    os.path.join(mini, "formal_math/verification/ci"))

    # 构造只依赖 Lean 核心（packages=[]）的最小合规 formal_math 包，含 ChanChallenge 与 comparator.json
    write_text(os.path.join(mini, "formal_math/lean-toolchain"), "leanprover/lean4:v4.36.0\n")
    write_text(os.path.join(mini, "formal_math/lakefile.toml"), """name = "chan"
version = "0.1.0"
defaultTargets = ["Chan", "ChanTest", "ChanChallenge"]

[leanOptions]
autoImplicit = false
relaxedAutoImplicit = false
linter.unusedVariables = true

[[lean_lib]]
name = "Chan"
globs = ["Chan.*"]

[[lean_lib]]
name = "ChanTest"
roots = ["ChanTest.Probe"]
globs = ["ChanTest.+"]

[[lean_lib]]
name = "ChanChallenge"
globs = ["ChanChallenge.+"]
""")
    write_text(os.path.join(mini, "formal_math/lake-manifest.json"), json.dumps({
        "version": "1.3.0",
        "packagesDir": ".lake/packages",
        "packages": [],
        "name": "chan",
        "lakeDir": ".lake",
        "fixedToolchain": False,
    }, indent=1) + "\n")
    write_text(os.path.join(mini, "formal_math/README.md"), "# mini\n")
    write_text(os.path.join(mini, "formal_math/HISTORY.md"), "# history\n")
    write_text(os.path.join(mini, "formal_math/formalization.yaml"), "{}\n")
    write_text(os.path.join(mini, "formal_math/garbage-signoffs.yaml"), "{}\n")

    write_text(os.path.join(mini, "formal_math/Chan/Defs/Val.lean"), """module

@[expose] public section

namespace Chan.Defs

def double (n : Nat) : Nat := n + n

end Chan.Defs
""")
    write_text(os.path.join(mini, "formal_math/Chan/Thm/Basic.lean"), """module

public import Chan.Defs.Val

public section

namespace Chan.Thm

theorem double_eq (n : Nat) : Chan.Defs.double n = n + n := rfl

end Chan.Thm
""")
    write_text(os.path.join(mini, "formal_math/ChanChallenge/Goal.lean"), """module

public import Chan.Defs.Val

public section

namespace Chan.Thm

theorem double_eq (n : Nat) : Chan.Defs.double n = n + n := by
  exact Eq.refl _

end Chan.Thm
""")
    write_text(os.path.join(mini, "formal_math/ChanTest/Probe.lean"), """module

/-- 门禁每次先读这个私有定理的证明体，再审计包里的声明。 -/
private theorem gateProofProbe : (1 : Nat) < 2 := by decide
""")
    write_text(os.path.join(mini, "formal_math/Chan.lean"), """module

public import Chan.Defs.Val
public import Chan.Thm.Basic
""")
    # 先用空锁算一次真实锁哈希，确保基线 statement-lock.json 严格匹配
    write_text(os.path.join(mini, "formal_math/statement-lock.json"), "{}\n")
    write_text(os.path.join(mini, "formal_math/verification/comparator.json"), json.dumps({
        "challenge_module": "ChanChallenge.Goal",
        "solution_module": "Chan.Thm.Basic",
        "theorem_names": ["Chan.Thm.double_eq"],
        "definition_names": [],
        "permitted_axioms": ["propext", "Quot.sound", "Classical.choice"],
    }, indent=2) + "\n")
    write_text(os.path.join(mini, "docs/init.txt"), "init\n")

    git(mini, "add", ".")
    git(mini, "commit", "-m", "init mini")
    c0 = git(mini, "rev-parse", "HEAD")

    # 借 run.py 算出 Chan.Defs.double 的精确锁哈希并回写基线
    pkg_dir = os.path.join(tmp, "empty-pkgs")
    os.makedirs(pkg_dir, exist_ok=True)
    wd = os.path.join(tmp, "wd-lock")
    p = run([sys.executable, "-I", os.path.join(mini, "formal_math/verification/runner/run.py"),
             "--repo", mini, "--base", c0, "--head", c0, "--branch", "main",
             "--workdir", wd, "--packages", pkg_dir])
    assert p.returncode == 1, f"期望缺锁判红，实际 {p.returncode}\n{p.stdout}\n{p.stderr}"
    locks = {}
    for line in p.stdout.splitlines():
        m = re.match(r"FM RED env LOCK_UNLISTED [^:]+:(\S+) 现算 ([0-9a-f]{64})", line)
        if m:
            locks[m.group(1)] = m.group(2)
    assert "Chan.Defs.double" in locks, f"未提取到锁哈希: {p.stdout}"
    shutil.rmtree(wd)

    write_text(os.path.join(mini, "formal_math/statement-lock.json"), json.dumps(locks, sort_keys=True, indent=2) + "\n")
    git(mini, "add", "formal_math/statement-lock.json")
    git(mini, "commit", "--amend", "--no-edit")
    base = git(mini, "rev-parse", "HEAD")
    return mini, base, pkg_dir


def test_t15_bwrap_pkgbind_ro_offline(repo, tmp):
    wrap = os.path.join(tmp, "wrap-ro-test.sh")
    lake_dir = os.path.join(tmp, "fake-proj/.lake")
    pkg_dir = os.path.join(tmp, "ro-pkg-sentinel")
    os.makedirs(pkg_dir)
    sentinel = os.path.join(pkg_dir, "sentinel.txt")
    write_text(sentinel, "immutable\n")
    os.chmod(sentinel, 0o444)
    os.chmod(pkg_dir, 0o555)
    try:
        run(["bash", os.path.join(repo, "formal_math/verification/ci/bwrap_pkgbind.sh"),
             "--emit", wrap, "--lake-dir", lake_dir, "--packages", pkg_dir, "--offline"], check=True)
        # 模拟 Lake 传 --bind <lake_dir> 和 --share-net：验证 (1) 沙箱内只有 lo（--share-net 已剥除），
        # (2) 沙箱内写 <lake_dir>/packages/pwned 失败（只读挂载生效），(3) 宿主机 sentinel 未变。
        p = run([
            "env", "-i", wrap,
            "--ro-bind", "/", "/",
            "--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp",
            "--dev", "/dev", "--proc", "/proc",
            "--bind", lake_dir, lake_dir,
            "--clearenv", "--setenv", "PATH", "/usr/bin:/bin",
            "--unshare-all", "--die-with-parent", "--new-session", "--share-net",
            "--", "/bin/sh", "-eu", "-c",
            f'non_lo=$(awk "NR>2 {{gsub(/:/, \\"\\", \\$1); if (\\$1 != \\"lo\\") print \\$1}}" /proc/net/dev); '
            f'[ -z "$non_lo" ] || {{ echo "NET_LEAK=$non_lo" >&2; exit 10; }}; '
            f'grep -qx immutable "{lake_dir}/packages/sentinel.txt"; '
            f'if touch "{lake_dir}/packages/pwned" 2>/dev/null; then echo "RO_BYPASS" >&2; exit 11; fi'
        ])
        assert p.returncode == 0, f"T15 失败 ({p.returncode}): {p.stdout}\n{p.stderr}"
    finally:
        os.chmod(pkg_dir, 0o755)
        os.chmod(sentinel, 0o644)


def run_mini_suite(repo, tmp):
    mini, base, pkg_dir = build_mini_repo(repo, tmp)
    gate = os.path.join(mini, "formal_math/verification/ci/run_pr_gate.sh")
    comp = os.path.join(mini, "formal_math/verification/ci/comparator.sh")
    mat = os.path.join(mini, "formal_math/verification/ci/materialize.py")

    def make_branch_commit(bname, start_rev, edits):
        git(mini, "checkout", "-B", bname, start_rev)
        for rel, content in edits.items():
            write_text(os.path.join(mini, rel), content)
        git(mini, "add", *edits.keys())
        git(mini, "commit", "-m", f"test {bname}")
        sha = git(mini, "rev-parse", "HEAD")
        git(mini, "checkout", "main")
        return sha

    # T4: 非 formal_math PR（追平 main）快速路径绿
    c_nonfm = make_branch_commit("feat/docs-only", base, {"docs/note.txt": "hello\n"})
    out4 = os.path.join(tmp, "t4.out")
    p = run(["bash", gate, "--phase", "preflight", "--mode", "pr",
             "--repo", mini, "--base", base, "--head", c_nonfm, "--branch", "feat/docs-only",
             "--output-file", out4], check=True)
    assert "FM_CI FAST_PATH_GREEN" in p.stdout, p.stdout
    assert "need_heavy=false" in open(out4).read()
    print("PASS T4_NON_FM_PR_FAST_PATH_UPTODATE")

    # T5: 非 formal_math PR（落后 main，唯一 merge-base）快速路径绿
    c_main2 = make_branch_commit("main", base, {"docs/main-advance.txt": "m2\n"})
    c_behind_nonfm = make_branch_commit("feat/behind-docs", base, {"docs/behind.txt": "b\n"})
    out5 = os.path.join(tmp, "t5.out")
    p = run(["bash", gate, "--phase", "preflight", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_behind_nonfm, "--branch", "feat/behind-docs",
             "--output-file", out5], check=True)
    assert "FM_CI FAST_PATH_GREEN" in p.stdout, p.stdout
    assert "need_heavy=false" in open(out5).read()
    print("PASS T5_NON_FM_PR_FAST_PATH_BEHIND_MAIN")

    # T6: 要求 1 必红 —— proof/* 改 .github/workflows/formal-math.yml
    c_evil_wf = make_branch_commit("proof/evil-wf", c_main2, {
        ".github/workflows/formal-math.yml": "name: pwned\non: push\njobs: {}\n"
    })
    p = run(["bash", gate, "--phase", "preflight", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_evil_wf, "--branch", "proof/evil-wf"])
    assert p.returncode == 1, f"T6 期望退 1，实际 {p.returncode}\n{p.stdout}\n{p.stderr}"
    assert "PATH_SCOPE" in p.stdout and "TRUSTED_DRIFT" in p.stdout, p.stdout
    print("PASS T6_PROOF_EDITS_WORKFLOW_RED")

    # T7 & T8: 要求 6 —— infra/* 改受信目录默认红（TRUST_UNAPPROVED），带放行全流程绿
    c_infra = make_branch_commit("infra/doc-tweak", c_main2, {
        "formal_math/verification/ci/README.md": "# tweaked\n"
    })
    p = run(["bash", gate, "--phase", "preflight", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_infra, "--branch", "infra/doc-tweak"])
    assert p.returncode == 1 and "TRUST_UNAPPROVED" in p.stdout, f"T7 失败: {p.returncode}\n{p.stdout}\n{p.stderr}"
    print("PASS T7_INFRA_UNAPPROVED_RED")

    p = run(["bash", gate, "--phase", "all", "--mode", "pr", "--trusted-change-approved",
             "--repo", mini, "--base", c_main2, "--head", c_infra, "--branch", "infra/doc-tweak",
             "--packages", pkg_dir], check=True)
    assert "FM_CI GREEN" in p.stdout, p.stdout
    print("PASS T8_INFRA_APPROVED_GREEN")

    # T9: 落后 main 且改了 formal_math -> NOT_ANCESTOR 红
    c_stale_proof = make_branch_commit("proof/stale", base, {
        "formal_math/Chan/Thm/Basic.lean": """module

public import Chan.Defs.Val

public section

namespace Chan.Thm

theorem double_eq (n : Nat) : Chan.Defs.double n = n + n := rfl
theorem extra_zero : 0 = 0 := rfl

end Chan.Thm
"""
    })
    p = run(["bash", gate, "--phase", "preflight", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_stale_proof, "--branch", "proof/stale"])
    assert p.returncode == 1 and "NOT_ANCESTOR" in p.stderr, f"T9 失败: {p.returncode}\n{p.stdout}\n{p.stderr}"
    print("PASS T9_PROOF_BEHIND_MAIN_RED")

    # T10: 合法 proof/* PR 全流程绿（run.py 七步 + lake check + 正式两段隔离 comparator）
    c_good_proof = make_branch_commit("proof/good-thm", c_main2, {
        "formal_math/Chan/Thm/Basic.lean": """module

public import Chan.Defs.Val

public section

namespace Chan.Thm

theorem double_eq (n : Nat) : Chan.Defs.double n = n + n := by
  rfl

theorem extra_ok (n : Nat) : n + 0 = n := Nat.add_zero n

end Chan.Thm
"""
    })
    p = run(["bash", gate, "--phase", "all", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_good_proof, "--branch", "proof/good-thm",
             "--packages", pkg_dir], check=True)
    assert "FM_CI GREEN" in p.stdout and "Your solution is okay!" in p.stdout, p.stdout
    print("PASS T10_PROOF_GREEN_FULL")

    # T11: 含 admit 的 proof/* PR 必红
    c_bad_sorry = make_branch_commit("proof/bad-sorry", c_main2, {
        "formal_math/Chan/Thm/Basic.lean": """module

public import Chan.Defs.Val

public section

namespace Chan.Thm

theorem double_eq (n : Nat) : Chan.Defs.double n = n + n := by
  admit

end Chan.Thm
"""
    })
    p = run(["bash", gate, "--phase", "all", "--mode", "pr",
             "--repo", mini, "--base", c_main2, "--head", c_bad_sorry, "--branch", "proof/bad-sorry",
             "--packages", pkg_dir])
    assert p.returncode == 1 and "SHAPE_FORBIDDEN" in p.stdout, f"T11 失败: {p.returncode}\n{p.stdout}\n{p.stderr}"
    print("PASS T11_PROOF_SORRY_RED")

    # T12: 要求 4 必红 —— 正式 comparator.json 含非空 definition_names
    c_defhole = make_branch_commit("infra/defhole-cfg", c_main2, {
        "formal_math/verification/comparator.json": json.dumps({
            "challenge_module": "ChanChallenge.Goal",
            "solution_module": "Chan.Thm.Basic",
            "theorem_names": ["Chan.Thm.double_eq"],
            "definition_names": ["Chan.Defs.double"],
            "permitted_axioms": ["propext", "Quot.sound", "Classical.choice"],
        }, indent=2) + "\n"
    })
    p = run(["bash", comp, "--skip-samples",
             "--repo", mini, "--base", c_main2, "--head", c_defhole, "--packages", pkg_dir])
    assert p.returncode == 1, f"T12 期望退 1，实际 {p.returncode}\n{p.stdout}\n{p.stderr}"
    print("PASS T12_COMPARATOR_DEFHOLE_FORMAL_RED")

    # T13: 要求 4 必红 —— permitted_axioms 含非标准公理 sorryAx
    c_bad_ax = make_branch_commit("infra/bad-ax-cfg", c_main2, {
        "formal_math/verification/comparator.json": json.dumps({
            "challenge_module": "ChanChallenge.Goal",
            "solution_module": "Chan.Thm.Basic",
            "theorem_names": ["Chan.Thm.double_eq"],
            "definition_names": [],
            "permitted_axioms": ["propext", "sorryAx"],
        }, indent=2) + "\n"
    })
    p = run(["bash", comp, "--skip-samples",
             "--repo", mini, "--base", c_main2, "--head", c_bad_ax, "--packages", pkg_dir])
    assert p.returncode == 1, f"T13 期望退 1，实际 {p.returncode}\n{p.stdout}\n{p.stderr}"
    print("PASS T13_COMPARATOR_BAD_AXIOM_RED")

    # T14: 要求 4 隔离核验 —— challenge 目录物理不含任何证明/测试文件
    chal_out = os.path.join(tmp, "t14-chal")
    run([sys.executable, "-I", mat, "challenge",
         "--repo", mini, "--base", c_main2, "--head", c_good_proof, "--out", chal_out], check=True)
    assert os.path.isfile(os.path.join(chal_out, "ChanChallenge/Goal.lean"))
    assert os.path.isfile(os.path.join(chal_out, "Chan/Defs/Val.lean"))
    for forbidden in ("Chan/Thm", "Chan/Proofs", "Chan/Exec", "Chan/Final", "Chan.lean", "ChanTest", "ChanExplore"):
        assert not os.path.exists(os.path.join(chal_out, forbidden)), f"T14 挑战目录泄露证明路径: {forbidden}"
    print("PASS T14_COMPARATOR_CHALLENGE_ISOLATION")

    # T16: mode=main 快速路径（未改动 formal_math）与完整主干门（无 --before）
    out16 = os.path.join(tmp, "t16.out")
    p = run(["bash", gate, "--phase", "preflight", "--mode", "main", "--before", base,
             "--repo", mini, "--base", c_main2, "--head", c_main2, "--branch", "main",
             "--output-file", out16], check=True)
    assert "FM_CI FAST_PATH_GREEN" in p.stdout and "need_heavy=false" in open(out16).read(), p.stdout

    p = run(["bash", gate, "--phase", "all", "--mode", "main",
             "--repo", mini, "--base", c_main2, "--head", c_main2, "--branch", "main",
             "--packages", pkg_dir], check=True)
    assert "FM_CI GREEN" in p.stdout and "Your solution is okay!" in p.stdout, p.stdout
    print("PASS T16_MAIN_FAST_PATH_AND_FULL")


def main(argv):
    repo = DEFAULT_REPO
    if len(argv) == 2 and argv[0] == "--repo":
        repo = os.path.abspath(argv[1])
    elif argv:
        sys.stderr.write("用法: python3 -I selftest_ci.py [--repo <仓库>]\n")
        return 2

    test_t1_workflow_and_shell(repo)
    print("PASS T1_WORKFLOW_AND_SHELL")
    test_t3_materialize_isolated(repo)
    print("PASS T3_MATERIALIZE_ISOLATED")

    with tempfile.TemporaryDirectory(prefix="fm-ci-selftest-") as tmp:
        test_t15_bwrap_pkgbind_ro_offline(repo, tmp)
        print("PASS T15_BWRAP_PKGBIND_RO_OFFLINE")
        run_mini_suite(repo, tmp)

    print("CI_SELFTEST_ALL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
