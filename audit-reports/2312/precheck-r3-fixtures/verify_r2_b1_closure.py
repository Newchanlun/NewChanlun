#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R3：R2-B1 闭合复验（原 14 形状 + 16 种新同类形状 + 真实仓库验证）。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I verify_r2_b1_closure.py [--precheck PATH]
"""
import argparse
import os
import re
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
LINE_RE = re.compile(rb"^PRECHECK (\S+) (\S+) ", re.M)


def git(repo, *args, data=None, check=True):
    p = subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {args} failed: {p.returncode} {p.stderr.decode('utf-8', 'replace')}")
    return p


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).stdout.strip()


def raw_entries(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m, n, bytes.fromhex(o.decode())) for m, n, o in entries)
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).stdout.strip()


def mktree(repo, entries):
    return git(repo, "mktree", "-z", "--missing", data=b"".join(b"%s %s %s\t%s\0" % e for e in entries)).stdout.strip()


def commit_tree(repo, tree_oid, parents=(), msg="c"):
    args = ["commit-tree", tree_oid.decode(), "-m", msg]
    for p in parents:
        args += ["-p", p]
    return git(repo, *args).stdout.strip().decode()


def parse_tree(repo, tree_oid):
    raw = git(repo, "cat-file", "tree", tree_oid.decode()).stdout
    out, pos = [], 0
    while pos < len(raw):
        sp = raw.index(b" ", pos)
        nul = raw.index(b"\0", sp)
        out.append((raw[pos:sp], raw[sp + 1:nul], raw[nul + 1:nul + 21].hex().encode()))
        pos = nul + 21
    return out


def run_pre(precheck, repo, base, head, branch, approved=False):
    cmd = [sys.executable, "-I", precheck] + (["--trusted-change-approved"] if approved else []) + [repo, base, head, branch]
    p = subprocess.run(cmd, env=RUN_ENV, capture_output=True)
    cs = sorted({c.decode() for k, c in LINE_RE.findall(p.stdout + p.stderr) if k != b"GREEN"})
    return p.returncode, cs, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r3-b1-")
    total = 0
    failed = 0

    def verify(group, label, got, exp_rc, req_codes=()):
        nonlocal total, failed
        total += 1
        rc, cs, out, err = got
        ok = rc == exp_rc and all(c in cs for c in req_codes)
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] [{group}] {label} => rc={rc} codes={cs}")
        if not ok:
            print(f"    out: {out}\n    err: {err}")

    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")

        b_mod = blob(repo, b"module\n")
        b_cfg = blob(repo, b'name = "Chan"\n')
        b_env = blob(repo, b"e\n")
        b_wf = blob(repo, b"w\n")
        b_ci = blob(repo, b"ci\n")
        b_ci2 = blob(repo, b"ci-edited\n")
        b_other = blob(repo, b"other\n")
        b_other2 = blob(repo, b"other-edited\n")
        b_link = blob(repo, b"/etc/passwd")
        b_rust = blob(repo, b"fn main() {}\n")
        b_rust2 = blob(repo, b"fn main() { /* edit */ }\n")
        b_gitlink = b"1" * 40

        t_thm = mktree(repo, [(b"100644", b"blob", b_mod, b"B.lean")])
        t_chan = mktree(repo, [(b"040000", b"tree", t_thm, b"Thm")])
        t_fm = mktree(repo, [(b"040000", b"tree", t_chan, b"Chan"), (b"100644", b"blob", b_cfg, b"lakefile.toml")])
        t_rust = mktree(repo, [(b"100644", b"blob", b_rust, b"lib.rs")])
        t_rust2 = mktree(repo, [(b"100644", b"blob", b_rust2, b"lib.rs")])

        t_scripts_full = mktree(repo, [(b"100644", b"blob", b_env, b"fm_env.sh"), (b"100644", b"blob", b_other, b"other.sh")])
        t_scripts_full_sib = mktree(repo, [(b"100644", b"blob", b_env, b"fm_env.sh"), (b"100644", b"blob", b_other2, b"other.sh")])
        t_scripts_unmanaged = mktree(repo, [(b"100644", b"blob", b_other, b"other.sh")])
        t_scripts_unmanaged_sib = mktree(repo, [(b"100644", b"blob", b_other2, b"other.sh")])

        t_wf_full = mktree(repo, [(b"100644", b"blob", b_ci, b"ci.yml"), (b"100644", b"blob", b_wf, b"formal-math.yml")])
        t_wf_full_sib = mktree(repo, [(b"100644", b"blob", b_ci2, b"ci.yml"), (b"100644", b"blob", b_wf, b"formal-math.yml")])
        t_wf_unmanaged = mktree(repo, [(b"100644", b"blob", b_ci, b"ci.yml")])
        t_wf_unmanaged_sib = mktree(repo, [(b"100644", b"blob", b_ci2, b"ci.yml")])

        t_gh_full = mktree(repo, [(b"040000", b"tree", t_wf_full, b"workflows")])
        t_gh_full_sib = mktree(repo, [(b"040000", b"tree", t_wf_full_sib, b"workflows")])
        t_gh_unmanaged = mktree(repo, [(b"040000", b"tree", t_wf_unmanaged, b"workflows")])
        t_gh_unmanaged_sib = mktree(repo, [(b"040000", b"tree", t_wf_unmanaged_sib, b"workflows")])

        # 基线 1：含 fm_env.sh 与 formal-math.yml 与兄弟文件
        base_full = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_gh_full, b".github"),
            (b"040000", b"tree", t_fm, b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"),
            (b"040000", b"tree", t_scripts_full, b"scripts"),
        ]), msg="base-full")

        # 基线 2：不含 fm_env.sh 与 formal-math.yml，只有兄弟文件
        base_no_trusted = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_gh_unmanaged, b".github"),
            (b"040000", b"tree", t_fm, b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"),
            (b"040000", b"tree", t_scripts_unmanaged, b"scripts"),
        ]), msg="base-no-trusted")

        # 基线 3：既无 scripts 也无 .github（更无受信文件）
        base_no_anc = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_fm, b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"),
        ]), msg="base-no-anc")

        # --- 新形状组 1：基线无祖先目录时直接引入非法祖先节点 ---
        for label, ent_mode, ent_oid in [
            ("无基线 scripts -> 新增 120000 symlink scripts", b"120000", b_link),
            ("无基线 scripts -> 新增 160000 submodule scripts", b"160000", b_gitlink),
            ("无基线 scripts -> 新增 100644 file scripts", b"100644", b_other),
            ("无基线 scripts -> 新增 040000 dir scripts", b"040000", t_scripts_unmanaged),
        ]:
            t = raw_entries(repo, [(b"40000", b"formal_math", t_fm), (b"40000", b"rust", t_rust), (ent_mode, b"scripts", ent_oid)])
            h = commit_tree(repo, t, [base_no_anc])
            verify("NEW-EXIST", f"{label} (main)", run_pre(ns.precheck, repo, base_no_anc, h, "main"), 1, ("MODE", "BRANCH_ROLE"))
            verify("NEW-EXIST", f"{label} (proof/x)", run_pre(ns.precheck, repo, base_no_anc, h, "proof/x"), 1, ("MODE", "PATH_SCOPE"))
            verify("NEW-EXIST", f"{label} (infra 放行)", run_pre(ns.precheck, repo, base_no_anc, h, "infra/x", True), 1, ("MODE",))

        # --- 新形状组 2：.github 自身是符号链接或子模块（受信文件存在/不存在两套基线） ---
        for base_tag, b_commit, t_sc, has_trusted in [
            ("含 formal-math.yml", base_full, t_scripts_full, True),
            ("无 formal-math.yml", base_no_trusted, t_scripts_unmanaged, False),
        ]:
            for kind_tag, mode, oid in [("120000 symlink", b"120000", b_link), ("160000 submodule", b"160000", b_gitlink)]:
                t = raw_entries(repo, [(mode, b".github", oid), (b"40000", b"formal_math", t_fm),
                                       (b"40000", b"rust", t_rust), (b"40000", b"scripts", t_sc)])
                h = commit_tree(repo, t, [b_commit])
                req_main = ("MODE", "BRANCH_ROLE", "TRUSTED_DRIFT") if has_trusted else ("MODE", "BRANCH_ROLE")
                req_proof = ("MODE", "PATH_SCOPE", "TRUSTED_DRIFT") if has_trusted else ("MODE", "PATH_SCOPE")
                verify("NEW-GH", f".github -> {kind_tag}（{base_tag}，main）", run_pre(ns.precheck, repo, b_commit, h, "main"), 1, req_main)
                verify("NEW-GH", f".github -> {kind_tag}（{base_tag}，proof/x）", run_pre(ns.precheck, repo, b_commit, h, "proof/x"), 1, req_proof)
                verify("NEW-GH", f".github -> {kind_tag}（{base_tag}，infra 放行）", run_pre(ns.precheck, repo, b_commit, h, "infra/x", True), 1, ("MODE", "PATH_SCOPE"))

        # --- 新形状组 3：祖先节点下受管外兄弟文件同时变化 ---
        # 3a: 兄弟变 + scripts 模式变 40000->040000
        h_sib_bad_sc = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_full_sib), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust2), (b"040000", b"scripts", t_scripts_full_sib),
        ]), [base_full])
        verify("NEW-SIB", "兄弟 ci.yml/other.sh/rust 同改 + scripts 40000->040000 (main)",
               run_pre(ns.precheck, repo, base_full, h_sib_bad_sc, "main"), 1, ("MODE", "BRANCH_ROLE"))
        verify("NEW-SIB", "兄弟 ci.yml/other.sh/rust 同改 + scripts 40000->040000 (proof/x)",
               run_pre(ns.precheck, repo, base_full, h_sib_bad_sc, "proof/x"), 1, ("MODE", "PATH_SCOPE"))
        verify("NEW-SIB", "兄弟 ci.yml/other.sh/rust 同改 + scripts 40000->040000 (infra 放行)",
               run_pre(ns.precheck, repo, base_full, h_sib_bad_sc, "infra/x", True), 1, ("MODE",))

        # 3b: 兄弟变 + .github/workflows 模式变 40000->40755
        t_gh_wf755_sib = raw_entries(repo, [(b"40755", b"workflows", t_wf_full_sib)])
        h_sib_bad_wf = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_wf755_sib), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust2), (b"40000", b"scripts", t_scripts_full_sib),
        ]), [base_full])
        verify("NEW-SIB", "兄弟 ci.yml/other.sh 同改 + .github/workflows 40000->40755 (proof/x)",
               run_pre(ns.precheck, repo, base_full, h_sib_bad_wf, "proof/x"), 1, ("MODE", "PATH_SCOPE"))

        # 3c: 对照——仅改兄弟文件（ci.yml + other.sh + rust），祖先目录保持 40000，应绿
        h_sib_ok = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_gh_full_sib, b".github"),
            (b"040000", b"tree", t_fm, b"formal_math"),
            (b"040000", b"tree", t_rust2, b"rust"),
            (b"040000", b"tree", t_scripts_full_sib, b"scripts"),
        ]), [base_full])
        for br in ("main", "proof/x", "decl/x", "audit/x", "infra/x"):
            verify("NEW-SIB", f"对照：仅改兄弟 ci.yml + other.sh + rust（{br}）",
                   run_pre(ns.precheck, repo, base_full, h_sib_ok, br), 0)

        # --- 新形状组 4：scripts 与 .github 一个合法一个不合法 ---
        # 4a: scripts 合法 (40000)，.github 非法 (040000)
        h_one_gh_bad = commit_tree(repo, raw_entries(repo, [
            (b"040000", b".github", t_gh_full), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust), (b"40000", b"scripts", t_scripts_full),
        ]), [base_full])
        verify("NEW-MIX", "scripts 合法 + .github 040000 (main)",
               run_pre(ns.precheck, repo, base_full, h_one_gh_bad, "main"), 1, ("MODE", "BRANCH_ROLE"))
        # 4b: scripts 非法 (120000)，.github 合法 (40000)，无 fm_env.sh
        h_one_sc_bad = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_unmanaged), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust), (b"120000", b"scripts", b_link),
        ]), [base_no_trusted])
        verify("NEW-MIX", "scripts 120000 + .github 合法（无 fm_env.sh，proof/x）",
               run_pre(ns.precheck, repo, base_no_trusted, h_one_sc_bad, "proof/x"), 1, ("MODE", "PATH_SCOPE"))

        # --- 新形状组 5：祖先目录保持 40000 但指向 blob 或树内畸形（signature 不变、changed 为空） ---
        h_sc_40000_blob = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_unmanaged), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust), (b"40000", b"scripts", b_other),
        ]), [base_no_trusted])
        verify("NEW-SIG0", "无 fm_env.sh 时 scripts 保持 40000 但指向 blob（changed 为空，main）",
               run_pre(ns.precheck, repo, base_no_trusted, h_sc_40000_blob, "main"), 1, ("TREE_FORM",))
        t_sc_dup = raw_entries(repo, [(b"100644", b"other.sh", b_other), (b"100644", b"other.sh", b_other2)])
        h_sc_malformed = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_unmanaged), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust), (b"40000", b"scripts", t_sc_dup),
        ]), [base_no_trusted])
        verify("NEW-SIG0", "无 fm_env.sh 时 scripts 保持 40000 但树内非受管文件重名（changed 为空，main）",
               run_pre(ns.precheck, repo, base_no_trusted, h_sc_malformed, "main"), 1, ("TREE_FORM",))

        # --- 新形状组 6：基线已有不合规祖先节点（120000），被审提交未动它只改 rust ---
        base_poison = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_unmanaged), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust), (b"120000", b"scripts", b_link),
        ]), msg="base-poison")
        h_poison_untouched = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh_unmanaged), (b"40000", b"formal_math", t_fm),
            (b"40000", b"rust", t_rust2), (b"120000", b"scripts", b_link),
        ]), [base_poison])
        verify("NEW-UNCOND", "基线 scripts 已为 120000，被审仅改 rust/lib.rs（无条件 shape，main）",
               run_pre(ns.precheck, repo, base_poison, h_poison_untouched, "main"), 1, ("MODE",))

        print(f"R2-B1 CLOSURE SUMMARY: {total} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
