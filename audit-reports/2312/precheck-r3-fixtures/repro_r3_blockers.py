#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R3：新阻断缺陷复现脚本（R3-B1、R3-B2）。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_r3_blockers.py [--precheck PATH] [--real-repo PATH] [--case R3-B1|R3-B2]
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


def git(repo, *args, data=None):
    p = subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True, check=True)
    return p.stdout


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).strip()


def raw_entries(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m, n, bytes.fromhex(o.decode())) for m, n, o in entries)
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).strip()


def mktree(repo, entries):
    return git(repo, "mktree", "-z", "--missing", data=b"".join(b"%s %s %s\t%s\0" % e for e in entries)).strip()


def commit_tree(repo, tree_oid, parents=(), msg="c"):
    args = ["commit-tree", tree_oid.decode(), "-m", msg]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args).strip().decode()


def run_pre(precheck, repo, base, head, branch, approved=False):
    cmd = [sys.executable, "-I", precheck] + (["--trusted-change-approved"] if approved else []) + [repo, base, head, branch]
    p = subprocess.run(cmd, env=RUN_ENV, capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace").strip()


def case_r3_b1(tmp, precheck, _real_repo):
    """R3-B1（说明不实 + 退出码契约）：README.md:46-47 明示 BASE_FORM（退 2）覆盖 TREE_FORM 行的全部问题
    （含文件条目指向非 blob，凭据为 cat-file --batch-check），但 precheck.py:206-209 未对基线清单 old 调用
    file_objects()，导致基线含 100644->tree/commit/tag 或缺失对象时：
      - 被审提交修复或删除该条目时退 0（而非退 2 BASE_FORM/GIT）；
      - base==head 时退 1（TREE_FORM，无 BASE_FORM），而非退 2。"""
    repo = os.path.join(tmp, "r3_b1")
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_s = blob(repo, b"s\n")
    b_e = blob(repo, b"e\n")
    t_sub = mktree(repo, [(b"100644", b"blob", b_s, b"a")])

    def make_commit(src_entries, parent=None, msg="c"):
        t_src = raw_entries(repo, src_entries)
        t_fm = mktree(repo, [(b"040000", b"tree", t_src, b"sources")])
        t_sc = mktree(repo, [(b"100644", b"blob", b_e, b"fm_env.sh")])
        t_root = mktree(repo, [(b"040000", b"tree", t_fm, b"formal_math"), (b"040000", b"tree", t_sc, b"scripts")])
        return commit_tree(repo, t_root, [parent] if parent else (), msg=msg)

    c_seed = make_commit([(b"100644", b"s.md", b_s)], msg="seed")
    tag_oid = git(repo, "mktag", data=f"object {c_seed}\ntype commit\ntag v0\ntagger r <r@r> 0 +0000\n\nt\n".encode()).strip()

    res = []
    for kind_tag, bad_oid in [("tree", t_sub), ("commit", c_seed.encode()), ("tag", tag_oid), ("missing", b"de" * 20)]:
        c_bad_base = make_commit([(b"100644", b"evil.md", bad_oid), (b"100644", b"s.md", b_s)], msg=f"base-{kind_tag}")
        c_head_del = make_commit([(b"100644", b"s.md", b_s)], parent=c_bad_base, msg=f"del-{kind_tag}")
        rc, out, err = run_pre(precheck, repo, c_bad_base, c_head_del, "decl/x")
        res.append((f"基线 sources/evil.md -> {kind_tag}，被审删除之 (decl/x)", c_head_del, rc, out, err,
                    "按 README:47 应退 2 (BASE_FORM/GIT)，实际退 0"))
        if kind_tag != "missing":
            rc2, out2, err2 = run_pre(precheck, repo, c_bad_base, c_bad_base, "main")
            res.append((f"基线==被审均含 sources/evil.md -> {kind_tag} (main)", c_bad_base, rc2, out2, err2,
                        "按 README:47 应同时报 BASE_FORM 并退 2，实际仅退 1"))
    # 对比：基线 scripts/fm_env.sh -> tree，infra 放行修复之
    t_fm_ok = mktree(repo, [(b"040000", b"tree", raw_entries(repo, [(b"100644", b"s.md", b_s)]), b"sources")])
    c_base_env_tree = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_fm_ok, b"formal_math"),
        (b"040000", b"tree", raw_entries(repo, [(b"100644", b"fm_env.sh", t_sub)]), b"scripts"),
    ]), msg="base-env-tree")
    c_head_env_fix = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_fm_ok, b"formal_math"),
        (b"040000", b"tree", raw_entries(repo, [(b"100644", b"fm_env.sh", b_e)]), b"scripts"),
    ]), [c_base_env_tree], msg="fix-env")
    rc3, out3, err3 = run_pre(precheck, repo, c_base_env_tree, c_head_env_fix, "infra/x", approved=True)
    res.append(("基线 scripts/fm_env.sh -> tree，infra 放行修复之", c_head_env_fix, rc3, out3, err3,
                "按 README:47 应退 2 BASE_FORM，实际退 0"))
    return res


def case_r3_b2(tmp, precheck, real_repo):
    """R3-B2（误红 + 说明不实）：ANCESTORS（scripts、.github、.github/workflows）的 None <-> 40000 变化被记入
    changed，导致仓库不含 formal_math/（或不含对应受信文件）时，非 infra 分支新增首个非受信脚本/工作流或删除
    最后一个非受信脚本/工作流时判红（BRANCH_ROLE / PATH_SCOPE），直接与 README.md:94,101,125 冲突，并在真实
    origin/main 历史提交上复现。"""
    repo = os.path.join(tmp, "r3_b2")
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_rust = blob(repo, b"fn main() {}\n")
    b_other = blob(repo, b"echo hi\n")
    b_ci = blob(repo, b"name: ci\n")

    t_rust = mktree(repo, [(b"100644", b"blob", b_rust, b"lib.rs")])
    t_scripts = mktree(repo, [(b"100644", b"blob", b_other, b"other.sh")])
    t_wf = mktree(repo, [(b"100644", b"blob", b_ci, b"ci.yml")])
    t_gh = mktree(repo, [(b"040000", b"tree", t_wf, b"workflows")])

    c_bare = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_rust, b"rust")]), msg="bare-no-fm")
    c_add_sc = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_rust, b"rust"), (b"040000", b"tree", t_scripts, b"scripts")]), [c_bare], msg="add-other-sh")
    c_add_ci = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_gh, b".github"), (b"040000", b"tree", t_rust, b"rust")]), [c_bare], msg="add-ci-yml")
    c_del_sc = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_rust, b"rust")]), [c_add_sc], msg="del-last-other-sh")
    c_del_ci = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_rust, b"rust")]), [c_add_ci], msg="del-last-ci-yml")

    res = []
    for tag, bc, hc in [
        ("无 formal_math：新增首个 scripts/other.sh", c_bare, c_add_sc),
        ("无 formal_math：新增首个 .github/workflows/ci.yml", c_bare, c_add_ci),
        ("无 formal_math：删除最后一个 scripts/other.sh", c_add_sc, c_del_sc),
        ("无 formal_math：删除最后一个 .github/workflows/ci.yml", c_add_ci, c_del_ci),
    ]:
        for br in ("main", "proof/x", "infra/x"):
            rc, out, err = run_pre(precheck, repo, bc, hc, br)
            res.append((f"{tag} ({br})", hc, rc, out, err, "全程无 formal_math 与受信文件"))

    # 真实仓库 origin/main 历史上首次引入 scripts/ 与 .github/workflows/ci.yml 的提交
    if real_repo and os.path.exists(real_repo):
        for tag, bc, hc in [
            ("真实 origin/main 首次新增 scripts/（无 formal_math）",
             "f6ad9b6362da7dc0bce6014cc883c19f21cc4207", "6d221b2f216f08b38be656a7b3fd8ba4d02b0f24"),
            ("真实 origin/main 首次新增 .github/workflows/ci.yml（无 formal_math）",
             "2abaf54559e882b4f29ab1d297cf78a3b4f4170b", "9560db2d08ddd0ca2e2810cf2d915d9fe2a2dd9e"),
        ]:
            chk = subprocess.run(["git", "-C", real_repo, "cat-file", "-e", f"{hc}^{{commit}}"], env=GENV)
            if chk.returncode == 0:
                for br in ("main", "proof/x"):
                    rc, out, err = run_pre(precheck, real_repo, bc, hc, br)
                    res.append((f"{tag} ({br})", hc, rc, out, err, f"real repo {bc[:10]}..{hc[:10]}"))
    return res


CASES = {"R3-B1": case_r3_b1, "R3-B2": case_r3_b2}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--real-repo", default=ROOT)
    ap.add_argument("--case", choices=sorted(CASES))
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r3-blockers-")
    try:
        names = [ns.case] if ns.case else list(CASES)
        for name in names:
            print(f"=== {name} ===")
            for tag, head, rc, out, err, extra in CASES[name](tmp, ns.precheck, ns.real_repo):
                print(f"  [{tag}] rc={rc} head={head}")
                if out:
                    print(f"    stdout: {out}")
                if err:
                    print(f"    stderr: {err}")
                if extra:
                    print(f"    extra:  {extra}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
