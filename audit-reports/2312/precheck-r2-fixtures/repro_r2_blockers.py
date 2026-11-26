#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R2：可复现阻断缺陷复现脚本。

全部临时仓库在 TMPDIR 下现造，默认运行后自动清理（传 --keep 保留）。
用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_r2_blockers.py
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_r2_blockers.py --case R2-B1a
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I repro_r2_blockers.py --case R2-B1b
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


def raw_entries(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m, n, bytes.fromhex(o.decode())) for m, n, o in entries)
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).stdout.strip()


def commit_tree(repo, tree_oid, parents=(), msg="c"):
    args = ["commit-tree", tree_oid.decode(), "-m", msg]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args).stdout.strip().decode()


def run_pre(precheck, repo, base, head, branch, approved=False):
    cmd = [sys.executable, "-I", precheck]
    if approved:
        cmd.append("--trusted-change-approved")
    cmd += [repo, base, head, branch]
    p = subprocess.run(cmd, env=RUN_ENV, capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace").strip()


def parse_tree_entries(repo, tree_oid):
    raw = git(repo, "cat-file", "tree", tree_oid.decode()).stdout
    out, pos = [], 0
    while pos < len(raw):
        sp = raw.index(b" ", pos)
        nul = raw.index(b"\0", sp)
        out.append((raw[pos:sp], raw[sp + 1:nul], raw[nul + 1:nul + 21].hex().encode()))
        pos = nul + 21
    return out


def case_r2_b1a(tmp, precheck):
    """R2-B1a（误绿 + 说明不实）：即使基线与被审均完整包含 scripts/fm_env.sh 与 .github/workflows/formal-math.yml，
    单独将受管祖先目录（scripts、.github、.github/workflows）的原始模式从 40000 改为 040000 或 40755，
    因 ANCESTORS 被无条件排除出 changed 导致跳过 shape()，在任何角色与无角色分支下均退 0。"""
    repo = os.path.join(tmp, "r2_b1a")
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_mod = blob(repo, b"module\n")
    b_cfg = blob(repo, b'name = "Chan"\n')
    b_env = blob(repo, b"e\n")
    b_wf = blob(repo, b"w\n")

    t_thm = mktree(repo, [(b"100644", b"blob", b_mod, b"B.lean")])
    t_chan = mktree(repo, [(b"040000", b"tree", t_thm, b"Thm")])
    t_fm = mktree(repo, [(b"040000", b"tree", t_chan, b"Chan"), (b"100644", b"blob", b_cfg, b"lakefile.toml")])
    t_scripts = mktree(repo, [(b"100644", b"blob", b_env, b"fm_env.sh")])
    t_wf = mktree(repo, [(b"100644", b"blob", b_wf, b"formal-math.yml")])
    t_gh = mktree(repo, [(b"040000", b"tree", t_wf, b"workflows")])
    t_root = mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"040000", b"tree", t_scripts, b"scripts"),
    ])
    base = commit_tree(repo, t_root, msg="base")
    root_ents = parse_tree_entries(repo, t_root)

    res = []
    # 1. scripts: 40000 -> 040000
    t_s04 = raw_entries(repo, [(b"040000" if n == b"scripts" else m, n, o) for m, n, o in root_ents])
    h_s04 = commit_tree(repo, t_s04, [base], msg="scripts-040000")
    for br in ("main", "proof/x", "infra/x"):
        rc, out, err = run_pre(precheck, repo, base, h_s04, br)
        res.append((f"scripts 40000->040000 ({br})", h_s04, rc, out, err, "scripts/fm_env.sh 存在且未变"))

    # 2. scripts: 40000 -> 40755
    t_s755 = raw_entries(repo, [(b"40755" if n == b"scripts" else m, n, o) for m, n, o in root_ents])
    h_s755 = commit_tree(repo, t_s755, [base], msg="scripts-40755")
    rc, out, err = run_pre(precheck, repo, base, h_s755, "proof/x")
    res.append(("scripts 40000->40755 (proof/x)", h_s755, rc, out, err, "scripts/fm_env.sh 存在且未变"))

    # 3. .github: 40000 -> 040000
    t_gh04 = raw_entries(repo, [(b"040000" if n == b".github" else m, n, o) for m, n, o in root_ents])
    h_gh04 = commit_tree(repo, t_gh04, [base], msg="gh-040000")
    rc, out, err = run_pre(precheck, repo, base, h_gh04, "proof/x")
    res.append((".github 40000->040000 (proof/x)", h_gh04, rc, out, err, "formal-math.yml 存在且未变"))

    # 4. .github/workflows: 40000 -> 040000
    t_gh_wf04 = raw_entries(repo, [(b"040000", b"workflows", t_wf)])
    t_r_wf04 = raw_entries(repo, [(m, n, t_gh_wf04 if n == b".github" else o) for m, n, o in root_ents])
    h_wf04 = commit_tree(repo, t_r_wf04, [base], msg="wf-040000")
    rc, out, err = run_pre(precheck, repo, base, h_wf04, "proof/x")
    res.append((".github/workflows 40000->040000 (proof/x)", h_wf04, rc, out, err, "formal-math.yml 存在且未变"))

    # 5. 对照：同样把 scripts 改为 040000 并顺带做一处合法 proof 改动，shape() 运行并判 MODE 红
    b_mod2 = blob(repo, b"module -- ok\n")
    t_thm2 = mktree(repo, [(b"100644", b"blob", b_mod2, b"B.lean")])
    t_chan2 = mktree(repo, [(b"040000", b"tree", t_thm2, b"Thm")])
    t_fm2 = mktree(repo, [(b"040000", b"tree", t_chan2, b"Chan"), (b"100644", b"blob", b_cfg, b"lakefile.toml")])
    t_s04_thm = raw_entries(repo, [
        (b"40000", b".github", t_gh),
        (b"40000", b"formal_math", t_fm2),
        (b"040000", b"scripts", t_scripts),
    ])
    h_s04_thm = commit_tree(repo, t_s04_thm, [base], msg="scripts-040000+thm")
    rc, out, err = run_pre(precheck, repo, base, h_s04_thm, "proof/x")
    res.append(("对照：scripts 40000->040000 + 合法 Thm 改动 (proof/x)", h_s04_thm, rc, out, err, "changed 非空则判 MODE 红"))
    return res


def case_r2_b1b(tmp, precheck):
    """R2-B1b（误绿 + 说明不实，100% 通过 git fsck --strict --full 零错零警）：
    当基线不含 .github/workflows/formal-math.yml（即当前 origin/main 与被审提交 5b6cc3ea16 的真实状态）
    或不含 scripts/fm_env.sh（origin/main 的真实状态）时，将 .github/workflows、.github 或 scripts
    替换为 120000 符号链接、100644 普通文件或 160000 子模块，预检退 0；合入后将导致后续所有合法 formal_math PR 全部红。"""
    repo = os.path.join(tmp, "r2_b1b")
    os.makedirs(repo)
    git(repo, "init", "-q")
    b_mod = blob(repo, b"module\n")
    b_mod2 = blob(repo, b"module -- next PR\n")
    b_cfg = blob(repo, b'name = "Chan"\n')
    b_ci = blob(repo, b"ci\n")
    b_other = blob(repo, b"o\n")
    b_link = blob(repo, b"/etc/passwd")

    t_thm = mktree(repo, [(b"100644", b"blob", b_mod, b"B.lean")])
    t_chan = mktree(repo, [(b"040000", b"tree", t_thm, b"Thm")])
    t_fm = mktree(repo, [(b"040000", b"tree", t_chan, b"Chan"), (b"100644", b"blob", b_cfg, b"lakefile.toml")])
    t_wf = mktree(repo, [(b"100644", b"blob", b_ci, b"ci.yml")])
    t_gh = mktree(repo, [(b"040000", b"tree", t_wf, b"workflows")])
    t_scripts = mktree(repo, [(b"100644", b"blob", b_other, b"other.sh")])
    t_root = mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"040000", b"tree", t_scripts, b"scripts"),
    ])
    base = commit_tree(repo, t_root, msg="base-no-wf-no-env")

    # 1. .github/workflows -> 120000 symlink
    t_gh_link = mktree(repo, [(b"120000", b"blob", b_link, b"workflows")])
    t_r_wflink = mktree(repo, [
        (b"040000", b"tree", t_gh_link, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"040000", b"tree", t_scripts, b"scripts"),
    ])
    h_wflink = commit_tree(repo, t_r_wflink, [base], msg="wf-symlink")

    # 2. scripts -> 120000 symlink / 100644 file / 160000 gitlink
    h_slink = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"120000", b"blob", b_link, b"scripts"),
    ]), [base], msg="scripts-symlink")
    h_sfile = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"100644", b"blob", b_other, b"scripts"),
    ]), [base], msg="scripts-file")
    h_sgit = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_gh, b".github"),
        (b"040000", b"tree", t_fm, b"formal_math"),
        (b"160000", b"commit", base.encode(), b"scripts"),
    ]), [base], msg="scripts-gitlink")

    # 3. 二段投毒效果：h_wflink 合入成新基线后，下一条完全合法的 proof/x PR 被 MODE 阻断
    t_thm2 = mktree(repo, [(b"100644", b"blob", b_mod2, b"B.lean")])
    t_chan2 = mktree(repo, [(b"040000", b"tree", t_thm2, b"Thm")])
    t_fm2 = mktree(repo, [(b"040000", b"tree", t_chan2, b"Chan"), (b"100644", b"blob", b_cfg, b"lakefile.toml")])
    h_next_pr = commit_tree(repo, mktree(repo, [
        (b"040000", b"tree", t_gh_link, b".github"),
        (b"040000", b"tree", t_fm2, b"formal_math"),
        (b"040000", b"tree", t_scripts, b"scripts"),
    ]), [h_wflink], msg="innocent-proof-pr")

    git(repo, "update-ref", "refs/heads/main", h_next_pr)
    git(repo, "update-ref", "refs/heads/s1", h_slink)
    git(repo, "update-ref", "refs/heads/s2", h_sfile)
    git(repo, "update-ref", "refs/heads/s3", h_sgit)
    fsck = git(repo, "fsck", "--strict", "--full", check=False)
    fsck_note = f"fsck_rc={fsck.returncode}"

    res = []
    for br in ("main", "proof/x", "infra/x"):
        rc, out, err = run_pre(precheck, repo, base, h_wflink, br)
        res.append((f".github/workflows dir->120000 symlink ({br})", h_wflink, rc, out, err, fsck_note))
    for tag, hc in [("scripts dir->120000 symlink", h_slink), ("scripts dir->100644 file", h_sfile),
                    ("scripts dir->160000 gitlink", h_sgit)]:
        rc, out, err = run_pre(precheck, repo, base, hc, "proof/x")
        res.append((f"{tag} (proof/x)", hc, rc, out, err, fsck_note))
    rc, out, err = run_pre(precheck, repo, h_wflink, h_next_pr, "proof/x")
    res.append(("后续无辜 proof/x PR（仅改 Chan/Thm/B.lean）", h_next_pr, rc, out, err, "被前一步合入的符号链接阻断"))
    return res


CASES = {"R2-B1a": case_r2_b1a, "R2-B1b": case_r2_b1b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--case", choices=sorted(CASES))
    ap.add_argument("--keep", action="store_true")
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r2-blockers-")
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
