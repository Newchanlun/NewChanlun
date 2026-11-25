#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R1：阻断缺陷复现脚本。

全部临时仓库在 TMPDIR 下现造，默认运行后自动清理（传 --keep 保留）。
用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_blockers.py
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_blockers.py --case B1a
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
GENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "LC_ALL": "C",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "r",
    "GIT_AUTHOR_EMAIL": "r@r",
    "GIT_COMMITTER_NAME": "r",
    "GIT_COMMITTER_EMAIL": "r@r",
    "GIT_AUTHOR_DATE": "@0 +0000",
    "GIT_COMMITTER_DATE": "@0 +0000",
}
RUN_ENV = {"PATH": GENV["PATH"], "LC_ALL": "C.UTF-8"}


def git(repo, *args, data=None, check=True):
    p = subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {args} 失败：{p.returncode} {p.stderr.decode('utf-8', 'replace')}")
    return p


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).stdout.strip()


def mktree(repo, entries):
    lines = b"".join(b"%s %s %s\t%s\0" % e for e in entries)
    return git(repo, "mktree", "-z", "--missing", data=lines).stdout.strip()


def raw_tree(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m.lstrip(b"0"), n, bytes.fromhex(o.decode())) for m, n, o in entries)
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).stdout.strip()


def commit_tree(repo, tree_oid, parents=(), msg="c"):
    args = ["commit-tree", tree_oid.decode(), "-m", msg]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args).stdout.strip().decode()


def init_base(repo):
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_mod = blob(repo, b"module\n")
    b_cfg = blob(repo, b'name = "Chan"\n')
    b_run = blob(repo, b"x\n")
    b_env = blob(repo, b"e\n")
    b_wf = blob(repo, b"w\n")
    b_rs = blob(repo, b"r\n")
    b_readme = blob(repo, b"readme\n")

    t_defs = mktree(repo, [(b"100644", b"blob", b_mod, b"A.lean")])
    t_thm = mktree(repo, [(b"100644", b"blob", b_mod, b"B.lean")])
    t_chan = mktree(repo, [(b"040000", b"tree", t_defs, b"Defs"), (b"040000", b"tree", t_thm, b"Thm")])
    t_verif = mktree(repo, [(b"100644", b"blob", b_run, b"run_gates.py")])
    t_src = mktree(repo, [(b"100644", b"blob", b_readme, b"s.md")])
    t_fm = mktree(repo, [
        (b"040000", b"tree", t_chan, b"Chan"),
        (b"100644", b"blob", b_readme, b"README.md"),
        (b"100644", b"blob", b_cfg, b"lakefile.toml"),
        (b"040000", b"tree", t_src, b"sources"),
        (b"040000", b"tree", t_verif, b"verification"),
    ])
    t_scripts = mktree(repo, [(b"100644", b"blob", b_env, b"fm_env.sh")])
    t_wf = mktree(repo, [(b"100644", b"blob", b_wf, b"formal-math.yml")])
    t_gh = mktree(repo, [(b"040000", b"tree", t_wf, b"workflows")])
    t_rust = mktree(repo, [(b"100644", b"blob", b_rs, b"lib.rs")])
    t_root = mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"040000", b"tree", t_rust, b"rust"),
        (b"040000", b"tree", t_scripts, b"scripts"),
    ])
    base = commit_tree(repo, t_root, msg="base")
    return {
        "base": base,
        "b_mod": b_mod,
        "b_cfg": b_cfg,
        "b_run": b_run,
        "b_readme": b_readme,
        "t_defs": t_defs,
        "t_thm": t_thm,
        "t_chan": t_chan,
        "t_verif": t_verif,
        "t_src": t_src,
        "t_fm": t_fm,
        "t_scripts": t_scripts,
        "t_gh": t_gh,
        "t_rust": t_rust,
    }


def run_pre(precheck, repo, base, head, branch, approved=False):
    cmd = [sys.executable, "-I", precheck]
    if approved:
        cmd.append("--trusted-change-approved")
    cmd += [repo, base, head, branch]
    p = subprocess.run(cmd, env=RUN_ENV, capture_output=True)
    return cmd, p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def case_b1a(tmp, precheck):
    """B1a（误绿 + 说明不实）：同目录同名异类重复树条目（符号链接/可执行位/子模块/非 .lean + 同名目录）绕过 BAD_TREE 与 shape。"""
    repo = os.path.join(tmp, "b1a")
    s = init_base(repo)
    b_link = blob(repo, b"/etc/passwd")
    t_sub = mktree(repo, [(b"100644", b"blob", s["b_mod"], b"E.lean")])
    variants = [
        ("symlink+tree", b"120000", b_link),
        ("exec+tree", b"100755", s["b_mod"]),
        ("gitlink+tree", b"160000", b"1" * 40),
        ("non-lean-blob+tree", b"100644", b_link),
    ]
    outputs = []
    for tag, mode, oid in variants:
        t_thm_evil = raw_tree(repo, [
            (b"100644", b"B.lean", s["b_mod"]),
            (mode, b"Sub", oid),
            (b"100644", b"Sub.lean", s["b_mod"]),  # 不相邻也能绕过
            (b"040000", b"Sub", t_sub),
        ])
        t_chan = mktree(repo, [(b"040000", b"tree", s["t_defs"], b"Defs"), (b"040000", b"tree", t_thm_evil, b"Thm")])
        t_fm = mktree(repo, [
            (b"040000", b"tree", t_chan, b"Chan"),
            (b"100644", b"blob", s["b_readme"], b"README.md"),
            (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
            (b"040000", b"tree", s["t_src"], b"sources"),
            (b"040000", b"tree", s["t_verif"], b"verification"),
        ])
        t_root = mktree(repo, [
            (b"040000", b"tree", s["t_gh"], b".github"),
            (b"040000", b"tree", t_fm, b"formal_math"),
            (b"040000", b"tree", s["t_rust"], b"rust"),
            (b"040000", b"tree", s["t_scripts"], b"scripts"),
        ])
        head = commit_tree(repo, t_root, [s["base"]], msg=tag)
        _, rc, out, err = run_pre(precheck, repo, s["base"], head, "proof/x")
        diff_out = git(repo, "diff-tree", "-r", "--no-renames", "--raw", s["base"], head).stdout.decode().strip()
        outputs.append((tag, head, rc, out.strip(), err.strip(), diff_out))
    return outputs


def case_b1b(tmp, precheck):
    """B1b（误绿 + 说明不实）：仓库根放 (120000 formal_math) + 原样 (040000 formal_math)，根节点比对看不到受管路径变化。"""
    repo = os.path.join(tmp, "b1b")
    s = init_base(repo)
    b_link = blob(repo, b"/etc/passwd")
    b_rs2 = blob(repo, b"evil\n")
    t_rust2 = mktree(repo, [(b"100644", b"blob", b_rs2, b"lib.rs")])
    t_root = raw_tree(repo, [
        (b"040000", b".github", s["t_gh"]),
        (b"120000", b"formal_math", b_link),
        (b"040000", b"formal_math", s["t_fm"]),
        (b"040000", b"rust", t_rust2),
        (b"040000", b"scripts", s["t_scripts"]),
    ])
    head = commit_tree(repo, t_root, [s["base"]], msg="root-dup-fm")
    diff_out = git(repo, "diff-tree", "-r", "--no-renames", "--raw", s["base"], head).stdout.decode().strip()
    res = []
    for br in ("main", "proof/x"):
        _, rc, out, err = run_pre(precheck, repo, s["base"], head, br)
        res.append((br, head, rc, out.strip(), err.strip(), diff_out))
    return res


def case_b2(tmp, precheck):
    """B2（误绿）：formal_math 自身为空树（git fsck 零错零警）时逃逸 EMPTY_TREE，角色分支下退 0。"""
    repo = os.path.join(tmp, "b2")
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_r = blob(repo, b"r\n")
    t_empty = mktree(repo, [])

    # B2a：基线无 formal_math（如当前 main），head 新增空树 formal_math
    c_base_a = commit_tree(repo, mktree(repo, [(b"100644", b"blob", b_r, b"README.md")]), msg="no-fm")
    c_head_a = commit_tree(repo, mktree(repo, [
        (b"100644", b"blob", b_r, b"README.md"),
        (b"040000", b"tree", t_empty, b"formal_math"),
    ]), [c_base_a], msg="add-empty-fm")

    # B2b：基线仅有 formal_math/README.md，删后留下空树 formal_math
    t_fm_r = mktree(repo, [(b"100644", b"blob", b_r, b"README.md")])
    c_base_b = commit_tree(repo, mktree(repo, [
        (b"100644", b"blob", b_r, b"README.md"),
        (b"040000", b"tree", t_fm_r, b"formal_math"),
    ]), msg="only-readme")
    c_head_b = commit_tree(repo, mktree(repo, [
        (b"100644", b"blob", b_r, b"README.md"),
        (b"040000", b"tree", t_empty, b"formal_math"),
    ]), [c_base_b], msg="del-to-empty-fm")

    git(repo, "update-ref", "refs/heads/a", c_head_a)
    git(repo, "update-ref", "refs/heads/b", c_head_b)
    fsck = git(repo, "fsck", "--strict", "--full", check=False)

    res = []
    for tag, b_c, h_c, br in [
        ("B2a-proof", c_base_a, c_head_a, "proof/x"),
        ("B2a-infra-unapproved", c_base_a, c_head_a, "infra/x"),
        ("B2b-infra-unapproved", c_base_b, c_head_b, "infra/x"),
    ]:
        _, rc, out, err = run_pre(precheck, repo, b_c, h_c, br)
        res.append((tag, h_c, rc, out.strip(), err.strip(), f"fsck_rc={fsck.returncode}"))
    return res


def case_b3(tmp, precheck):
    """B3（误绿）：diff-tree -r 对空子树删除及规范化前模式变动不可见，导致无放行 infra 改门禁树对象、proof 改 decl 目录树对象退 0。"""
    repo = os.path.join(tmp, "b3")
    s = init_base(repo)
    t_empty = mktree(repo, [])

    # B3a：基线 verification/ 下含空子树 Empty（fsck 全绿），head 在无放行 infra/x 下删去该空子树，verification 树对象变更
    t_verif_e = mktree(repo, [
        (b"040000", b"tree", t_empty, b"Empty"),
        (b"100644", b"blob", s["b_run"], b"run_gates.py"),
    ])
    t_fm_ve = mktree(repo, [
        (b"040000", b"tree", s["t_chan"], b"Chan"),
        (b"100644", b"blob", s["b_readme"], b"README.md"),
        (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
        (b"040000", b"tree", s["t_src"], b"sources"),
        (b"040000", b"tree", t_verif_e, b"verification"),
    ])
    c_base_ve = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", t_fm_ve, b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), msg="base-verif-empty")
    c_head_ve = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", s["t_fm"], b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [c_base_ve], msg="del-verif-empty")

    # B3b：基线 Chan/Defs/（decl 辖区）下含空子树 Empty，head 在 proof/x 下删去该空子树
    t_defs_e = mktree(repo, [
        (b"100644", b"blob", s["b_mod"], b"A.lean"),
        (b"040000", b"tree", t_empty, b"Empty"),
    ])
    t_chan_de = mktree(repo, [(b"040000", b"tree", t_defs_e, b"Defs"), (b"040000", b"tree", s["t_thm"], b"Thm")])
    t_fm_de = mktree(repo, [
        (b"040000", b"tree", t_chan_de, b"Chan"),
        (b"100644", b"blob", s["b_readme"], b"README.md"),
        (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
        (b"040000", b"tree", s["t_src"], b"sources"),
        (b"040000", b"tree", s["t_verif"], b"verification"),
    ])
    c_base_de = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", t_fm_de, b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), msg="base-defs-empty")
    c_head_de = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", s["t_fm"], b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [c_base_de], msg="del-defs-empty")

    # B3c：verification/run_gates.py 模式 100644->100664（git fsck 仅警告、退 0），verification 树对象变更但 diff-tree 为空
    t_verif_664 = raw_tree(repo, [(b"100664", b"run_gates.py", s["b_run"])])
    t_fm_v664 = mktree(repo, [
        (b"040000", b"tree", s["t_chan"], b"Chan"),
        (b"100644", b"blob", s["b_readme"], b"README.md"),
        (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
        (b"040000", b"tree", s["t_src"], b"sources"),
        (b"040000", b"tree", t_verif_664, b"verification"),
    ])
    c_head_v664 = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", t_fm_v664, b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [s["base"]], msg="verif-mode-100664")

    git(repo, "update-ref", "refs/heads/ve", c_head_ve)
    git(repo, "update-ref", "refs/heads/de", c_head_de)
    fsck_empty = git(repo, "fsck", "--strict", "--full", check=False)

    res = []
    for tag, b_c, h_c, br, note in [
        ("B3a-infra-no-approve-del-verif-empty", c_base_ve, c_head_ve, "infra/x", f"fsck_rc={fsck_empty.returncode}"),
        ("B3b-proof-del-decl-defs-empty", c_base_de, c_head_de, "proof/x", f"fsck_rc={fsck_empty.returncode}"),
        ("B3c-infra-no-approve-verif-100664", s["base"], c_head_v664, "infra/x",
         f"verif_oid_changed={s['t_verif'] != t_verif_664}"),
    ]:
        _, rc, out, err = run_pre(precheck, repo, b_c, h_c, br)
        res.append((tag, h_c, rc, out.strip(), err.strip(), note))
    return res


def case_b4(tmp, precheck):
    """B4（误绿）：formal_math/ 子目录下的 lakefile.lean（内容根 Chan/Thm/、非内容根 sources/）退 0。"""
    repo = os.path.join(tmp, "b4")
    s = init_base(repo)
    b_lf = blob(repo, b"import Lake\n")

    # Chan/Thm/lakefile.lean (proof/x)
    t_thm_lf = mktree(repo, [(b"100644", b"blob", s["b_mod"], b"B.lean"), (b"100644", b"blob", b_lf, b"lakefile.lean")])
    t_chan_lf = mktree(repo, [(b"040000", b"tree", s["t_defs"], b"Defs"), (b"040000", b"tree", t_thm_lf, b"Thm")])
    t_fm1 = mktree(repo, [
        (b"040000", b"tree", t_chan_lf, b"Chan"),
        (b"100644", b"blob", s["b_readme"], b"README.md"),
        (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
        (b"040000", b"tree", s["t_src"], b"sources"),
        (b"040000", b"tree", s["t_verif"], b"verification"),
    ])
    h1 = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", t_fm1, b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [s["base"]], msg="thm-lakefile-lean")

    # sources/lakefile.lean (decl/x)
    t_src_lf = mktree(repo, [(b"100644", b"blob", b_lf, b"lakefile.lean"), (b"100644", b"blob", s["b_readme"], b"s.md")])
    t_fm2 = mktree(repo, [
        (b"040000", b"tree", s["t_chan"], b"Chan"),
        (b"100644", b"blob", s["b_readme"], b"README.md"),
        (b"100644", b"blob", s["b_cfg"], b"lakefile.toml"),
        (b"040000", b"tree", t_src_lf, b"sources"),
        (b"040000", b"tree", s["t_verif"], b"verification"),
    ])
    h2 = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", t_fm2, b"formal_math"),
        (b"040000", b"tree", s["t_rust"], b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [s["base"]], msg="sources-lakefile-lean")

    res = []
    for tag, head, br in [("Chan/Thm/lakefile.lean", h1, "proof/x"), ("sources/lakefile.lean", h2, "decl/x")]:
        _, rc, out, err = run_pre(precheck, repo, s["base"], head, br)
        res.append((tag, head, rc, out.strip(), err.strip(), ""))
    return res


def case_b5(tmp, precheck):
    """B5（说明不实佐证）：有角色分支 proof/x 只改 rust/lib.rs（旧门 6b 判 PATH_SCOPE 红，新预检退 0），README 出入表漏列。"""
    repo = os.path.join(tmp, "b5")
    s = init_base(repo)
    b_rs2 = blob(repo, b"changed\n")
    t_rust2 = mktree(repo, [(b"100644", b"blob", b_rs2, b"lib.rs")])
    head = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", s["t_gh"], b".github"),
        (b"040000", b"tree", s["t_fm"], b"formal_math"),
        (b"040000", b"tree", t_rust2, b"rust"),
        (b"040000", b"tree", s["t_scripts"], b"scripts"),
    ]), [s["base"]], msg="only-rust")
    _, rc, out, err = run_pre(precheck, repo, s["base"], head, "proof/x")
    return [("proof/x only rust/lib.rs", head, rc, out.strip(), err.strip(), "")]


CASES = {"B1a": case_b1a, "B1b": case_b1b, "B2": case_b2, "B3": case_b3, "B4": case_b4, "B5": case_b5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--case", choices=sorted(CASES))
    ap.add_argument("--keep", action="store_true")
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r1-blockers-")
    try:
        names = [ns.case] if ns.case else list(CASES)
        for name in names:
            print(f"=== {name} ===")
            for tag, head, rc, out, err, extra in CASES[name](tmp, ns.precheck):
                print(f"  [{tag}] rc={rc} head={head}")
                if out:
                    print(f"    stdout: {out}")
                if err:
                    print(f"    stderr: {err}")
                if extra:
                    print(f"    extra:  {extra}")
    finally:
        if ns.keep:
            print(f"临时目录已保留：{tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
