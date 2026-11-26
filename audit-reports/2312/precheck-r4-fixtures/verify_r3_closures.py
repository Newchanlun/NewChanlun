#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：R3-B1 与 R3-B2 闭合复验（新构造形状 + 真实清理仓库）。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I verify_r3_closures.py [--precheck PATH] [--real-repo PATH]
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


def build_tree(repo, files):
    spec = {}
    for path, val in files.items():
        node, parts = spec, path.split(b"/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = val

    def rec(d):
        items = []
        for name, val in d.items():
            if isinstance(val, dict):
                items.append((b"040000", b"tree", rec(val), name))
            elif isinstance(val, tuple):
                if val[0] == b"160000":
                    items.append((b"160000", b"commit", val[1], name))
                elif val[0] == b"RAW_TREE":
                    items.append((b"040000", b"tree", val[1], name))
                else:
                    items.append((val[0], b"blob", blob(repo, val[1]), name))
            else:
                items.append((b"100644", b"blob", blob(repo, val), name))
        return mktree(repo, items)

    return rec(spec)


def run_pre(precheck, repo, base, head, branch, approved=False):
    cmd = [sys.executable, "-I", precheck] + (["--trusted-change-approved"] if approved else []) + [repo, base, head, branch]
    p = subprocess.run(cmd, env=RUN_ENV, capture_output=True)
    out_items = LINE_RE.findall(p.stdout)
    err_items = LINE_RE.findall(p.stderr)
    reds = sorted({c.decode() for k, c in out_items if k == b"RED"})
    faults = sorted({c.decode() for k, c in err_items if k == b"FAULT"})
    ch_ok = (
        all(l.startswith(b"PRECHECK ") for l in p.stdout.splitlines())
        and all(k in (b"RED", b"GREEN") for k, _ in out_items)
        and all(k == b"FAULT" for k, _ in err_items)
    )
    return p.returncode, reds, faults, ch_ok, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--real-repo", default=ROOT)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r4-r3closures-")
    FM = b"formal_math/"
    total = 0
    failed = 0

    def verify(sec, label, got, exp_rc, exp_reds=(), exp_faults=()):
        nonlocal total, failed
        total += 1
        rc, reds, faults, ch_ok, out, err = got
        ok = (
            rc == exp_rc
            and ch_ok
            and sorted(exp_reds) == reds
            and sorted(exp_faults) == faults
        )
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] [{sec}] {label} => rc={rc} red={reds} fault={faults}")
        if not ok:
            print(f"    want rc={exp_rc} red={sorted(exp_reds)} fault={sorted(exp_faults)} ch_ok={ch_ok}")
            print(f"    out: {out}\n    err: {err}")

    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")

        b_mod = blob(repo, b"module\n")
        b_s = blob(repo, b"s\n")
        b_e = blob(repo, b"e\n")
        b_w = blob(repo, b"w\n")
        b_x = blob(repo, b"x\n")
        t_sub = mktree(repo, [(b"100644", b"blob", b_x, b"a")])

        BASE = {
            FM + b"lakefile.toml": b'name = "Chan"\n',
            FM + b"Chan/Thm/B.lean": b"module\n",
            FM + b"sources/s.md": b"s\n",
            FM + b"verification/run_gates.py": b"x\n",
            b"scripts/fm_env.sh": b"e\n",
            b"scripts/other.sh": b"o\n",
            b".github/workflows/formal-math.yml": b"w\n",
            b".github/workflows/ci.yml": b"c\n",
            b"rust/lib.rs": b"r\n",
        }
        c_seed = commit_tree(repo, build_tree(repo, BASE), msg="seed")
        tag_oid = git(repo, "mktag", data=f"object {c_seed}\ntype commit\ntag v0\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip()

        def mk(edits, parent=None, base_files=BASE):
            f = dict(base_files)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            return commit_tree(repo, build_tree(repo, f), [parent] if parent else (), msg="c")

        # === R3-B1 新形状（8 组） ===
        # 新 1/2：基线 Chan/Thm/B.lean 为 120000 symlink 指向 tree/commit/tag/missing，被审修复为 100644 blob
        for kind_tag, oid, fault in [("tree", t_sub, "BASE_FORM"), ("commit", c_seed.encode(), "BASE_FORM"),
                                     ("tag", tag_oid, "BASE_FORM"), ("missing", b"ab" * 20, "GIT")]:
            t_thm_bad = raw_entries(repo, [(b"120000", b"B.lean", oid)])
            b_c = mk({FM + b"Chan/Thm": (b"RAW_TREE", t_thm_bad)})
            h_c = mk({}, parent=b_c)
            verify("R3-B1-NEW", f"基线 120000 symlink B.lean -> {kind_tag}，被审修复 (proof/x)",
                   run_pre(ns.precheck, repo, b_c, h_c, "proof/x"), 2, exp_faults=(fault,))

        # 新 3：基线 .github/workflows/formal-math.yml 为 100644 指向 commit/tag/missing，infra 放行修复/删除
        for kind_tag, oid, fault in [("commit", c_seed.encode(), "BASE_FORM"), ("tag", tag_oid, "BASE_FORM"),
                                     ("missing", b"cd" * 20, "GIT")]:
            t_wf_bad = raw_entries(repo, [(b"100644", b"ci.yml", b_x), (b"100644", b"formal-math.yml", oid)])
            b_c = mk({b".github/workflows": (b"RAW_TREE", t_wf_bad)})
            h_fix = mk({}, parent=b_c)
            h_del = mk({b".github/workflows/formal-math.yml": None}, parent=b_c)
            verify("R3-B1-NEW", f"基线 formal-math.yml -> {kind_tag}，infra 放行修复",
                   run_pre(ns.precheck, repo, b_c, h_fix, "infra/x", True), 2, exp_faults=(fault,))
            verify("R3-B1-NEW", f"基线 formal-math.yml -> {kind_tag}，infra 放行删除",
                   run_pre(ns.precheck, repo, b_c, h_del, "infra/x", True), 2, exp_faults=(fault,))

        # 新 4：基线 verification/run_gates.py 为 100755 可执行指向 tree，infra 放行修复
        t_ver_bad = raw_entries(repo, [(b"100755", b"run_gates.py", t_sub)])
        b_ver = mk({FM + b"verification": (b"RAW_TREE", t_ver_bad)})
        h_ver = mk({}, parent=b_ver)
        verify("R3-B1-NEW", "基线 100755 verification/run_gates.py -> tree，infra 放行修复",
               run_pre(ns.precheck, repo, b_ver, h_ver, "infra/x", True), 2, exp_faults=("BASE_FORM",))

        # 新 5：基线祖先 scripts 是 120000 symlink 指向 tree/missing，被审恢复为正常 40000 目录
        NO_SC = {k: v for k, v in BASE.items() if not k.startswith(b"scripts/")}
        t_no_sc = build_tree(repo, NO_SC)
        # 解析 t_no_sc 并在末尾加 scripts 条目（按 git 排序：.github, formal_math, rust, scripts）
        t_gh_ok = git(repo, "rev-parse", f"{c_seed}:.github").stdout.strip()
        t_fm_ok = git(repo, "rev-parse", f"{c_seed}:formal_math").stdout.strip()
        t_ru_ok = git(repo, "rev-parse", f"{c_seed}:rust").stdout.strip()
        for kind_tag, oid, fault in [("tree", t_sub, "BASE_FORM"), ("missing", b"ef" * 20, "GIT")]:
            t_root_bad = raw_entries(repo, [
                (b"40000", b".github", t_gh_ok),
                (b"40000", b"formal_math", t_fm_ok),
                (b"40000", b"rust", t_ru_ok),
                (b"120000", b"scripts", oid),
            ])
            b_sc = commit_tree(repo, t_root_bad, msg=f"base-sc-{kind_tag}")
            h_sc = mk({b"scripts/fm_env.sh": None}, parent=b_sc)
            verify("R3-B1-NEW", f"基线祖先 scripts 为 120000 -> {kind_tag}，被审恢复正常目录 (main)",
                   run_pre(ns.precheck, repo, b_sc, h_sc, "main"), 2, exp_faults=(fault,))

        # 新 6：对照——基线 formal_math/sources/sub 是 160000 子模块指向不存在 OID，decl 删除之 -> 应退 0（不误报 BASE_FORM/GIT）
        b_sub = mk({FM + b"sources/sub": (b"160000", b"11" * 20)})
        h_sub = mk({}, parent=b_sub)
        verify("R3-B1-NEW", "对照：基线 160000 子模块指向缺失 OID，decl 删除之退 0",
               run_pre(ns.precheck, repo, b_sub, h_sub, "decl/x"), 0)

        # 新 7：SHA-256 仓库基线 100644 -> tree 与 100644 -> missing
        r256 = os.path.join(tmp, "r256")
        os.makedirs(r256)
        git(r256, "init", "-q", "--object-format=sha256")
        b256 = blob(r256, b"s\n")
        t256_sub = mktree(r256, [(b"100644", b"blob", b256, b"a")])
        for kind_tag, oid, fault in [("tree", t256_sub, "BASE_FORM"), ("missing", b"de" * 32, "GIT")]:
            t256_src = raw_entries(r256, [(b"100644", b"evil.md", oid), (b"100644", b"s.md", b256)])
            t256_fm = mktree(r256, [(b"040000", b"tree", t256_src, b"sources")])
            b256_c = commit_tree(r256, mktree(r256, [(b"040000", b"tree", t256_fm, b"formal_math")]), msg=f"b256-{kind_tag}")
            h256_c = commit_tree(r256, build_tree(r256, {FM + b"sources/s.md": b"s\n"}), [b256_c], msg="h256")
            verify("R3-B1-NEW", f"SHA-256 基线 sources/evil.md -> {kind_tag}，decl 删除之",
                   run_pre(ns.precheck, r256, b256_c, h256_c, "decl/x"), 2, exp_faults=(fault,))

        # 新 8：基线 file_objects 不规范 + 被审含 MODE 与 LAKE_FILE -> 先报被审两红项再退 2 BASE_FORM
        t_src_tree = raw_entries(repo, [(b"100644", b"evil.md", t_sub), (b"100644", b"s.md", b_s)])
        b_f2t = mk({FM + b"sources": (b"RAW_TREE", t_src_tree)})
        h_bad = mk({FM + b"Chan/Thm/lakefile.lean": b"x\n", FM + b"Chan/Thm/B.lean": (b"100755", b"module\n")}, parent=b_f2t)
        verify("R3-B1-NEW", "基线 file_objects 非 blob 且被审有 MODE+LAKE_FILE -> 先报红再退 2 BASE_FORM",
               run_pre(ns.precheck, repo, b_f2t, h_bad, "proof/x"), 2,
               exp_reds=("LAKE_FILE", "MODE"), exp_faults=("BASE_FORM",))

        # === R3-B2 新形状（6 组） ===
        # 新 1：仅 .github 出现/消失（无 workflows 目录，如 .github/README.md）
        for tag, base_dict in [("无 formal_math", {b"rust/lib.rs": b"r\n"}),
                               ("有 formal_math", {FM + b"Chan/Thm/B.lean": b"module\n", b"rust/lib.rs": b"r\n"})]:
            c0 = mk({}, base_files=base_dict)
            c1 = mk({b".github/README.md": b"hi\n"}, parent=c0, base_files=base_dict)
            c2 = mk({}, parent=c1, base_files=base_dict)
            for br in ("main", "proof/x", "decl/x", "audit/x", "infra/x"):
                verify("R3-B2-NEW", f"{tag}：仅新增 .github/README.md ({br})",
                       run_pre(ns.precheck, repo, c0, c1, br), 0)
                verify("R3-B2-NEW", f"{tag}：仅删除 .github/README.md ({br})",
                       run_pre(ns.precheck, repo, c1, c2, br), 0)

        # 新 2：.github 已存在（含 README.md），仅 .github/workflows 出现/消失
        d_gh = {b"rust/lib.rs": b"r\n", b".github/README.md": b"hi\n"}
        c_gh0 = mk({}, base_files=d_gh)
        c_gh1 = mk({b".github/workflows/ci.yml": b"ci\n"}, parent=c_gh0, base_files=d_gh)
        c_gh2 = mk({}, parent=c_gh1, base_files=d_gh)
        for br in ("main", "proof/x", "decl/x", "infra/x"):
            verify("R3-B2-NEW", f".github 已存在：仅 .github/workflows 出现 ({br})",
                   run_pre(ns.precheck, repo, c_gh0, c_gh1, br), 0)
            verify("R3-B2-NEW", f".github 已存在：仅 .github/workflows 消失 ({br})",
                   run_pre(ns.precheck, repo, c_gh1, c_gh2, br), 0)

        # 新 3：scripts 出现 + .github/workflows 消失 + 合法角色内改动同提交
        d_mix = {FM + b"Chan/Thm/B.lean": b"module\n", FM + b"sources/s.md": b"s\n", b".github/workflows/ci.yml": b"c\n"}
        c_mix0 = mk({}, base_files=d_mix)
        c_mix_p = mk({b"scripts/tool.sh": b"t\n", b".github/workflows/ci.yml": None, FM + b"Chan/Thm/B.lean": b"module2\n"},
                     parent=c_mix0, base_files=d_mix)
        c_mix_d = mk({b"scripts/tool.sh": b"t\n", b".github/workflows/ci.yml": None, FM + b"sources/s.md": b"s2\n"},
                     parent=c_mix0, base_files=d_mix)
        verify("R3-B2-NEW", "scripts 出现 + .github/workflows 消失 + proof 合法改 B.lean",
               run_pre(ns.precheck, repo, c_mix0, c_mix_p, "proof/x"), 0)
        verify("R3-B2-NEW", "scripts 出现 + .github/workflows 消失 + decl 合法改 s.md",
               run_pre(ns.precheck, repo, c_mix0, c_mix_d, "decl/x"), 0)

        # 新 4：基线祖先 scripts 为 120000 symlink（指向 blob，无 fm_env.sh），恢复为 40000 目录或删除之
        b_sc_link = mk({b"scripts": (b"120000", b"target")}, base_files=NO_SC)
        h_sc_dir = mk({b"scripts/other.sh": b"o\n"}, parent=b_sc_link, base_files=NO_SC)
        h_sc_del = mk({}, parent=b_sc_link, base_files=NO_SC)
        for br in ("main", "proof/x", "infra/x"):
            verify("R3-B2-NEW", f"基线 scripts 为 symlink(blob)，恢复为 40000 目录 ({br})",
                   run_pre(ns.precheck, repo, b_sc_link, h_sc_dir, br), 0)
            verify("R3-B2-NEW", f"基线 scripts 为 symlink(blob)，直接删除 ({br})",
                   run_pre(ns.precheck, repo, b_sc_link, h_sc_del, br), 0)

        # 新 5：三个祖先同时出现、同时消失（含空分支名 ""）
        d_bare = {b"rust/lib.rs": b"r\n"}
        c_all0 = mk({}, base_files=d_bare)
        c_all1 = mk({b"scripts/a.sh": b"a\n", b".github/workflows/ci.yml": b"c\n"}, parent=c_all0, base_files=d_bare)
        c_all2 = mk({}, parent=c_all1, base_files=d_bare)
        for br in ("", "main", "proof/x", "decl/x", "audit/x", "infra/x"):
            verify("R3-B2-NEW", f"三祖先同时出现 ({br!r})", run_pre(ns.precheck, repo, c_all0, c_all1, br), 0)
            verify("R3-B2-NEW", f"三祖先同时消失 ({br!r})", run_pre(ns.precheck, repo, c_all1, c_all2, br), 0)

        # 新 6：真实仓库（59504398f4 清理 17 处后）删光现有全部非受信工作流（使 .github/workflows 消失）再恢复
        real_clone = os.path.join(tmp, "real_clone")
        git(tmp, "clone", "--shared", "--no-checkout", ns.real_repo, real_clone)
        head_real = "59504398f4acc85a08a312624ee000f08cbb5db5"
        if git(real_clone, "cat-file", "-e", f"{head_real}^{{commit}}", check=False).returncode != 0:
            head_real = git(real_clone, "rev-parse", "HEAD").stdout.strip().decode()
        p0 = subprocess.run([sys.executable, "-I", ns.precheck, "--trusted-change-approved", real_clone,
                             "594e49b5ec034461f9196c6cfb0c58fe017e8dc5", head_real, "infra/cleanup"],
                            env=RUN_ENV, capture_output=True)
        bad_paths = [l.split(b" ")[3].decode() for l in p0.stdout.splitlines() if l.startswith(b"PRECHECK RED ")]
        assert len(bad_paths) == 17, f"expected 17 legacy reds, got {len(bad_paths)}"
        idx = os.path.join(tmp, "clean.idx")
        env_idx = dict(GENV, GIT_INDEX_FILE=idx)
        subprocess.run(["git", "-C", real_clone, "read-tree", head_real], env=env_idx, check=True)
        subprocess.run(["git", "-C", real_clone, "update-index", "--force-remove", "--"] + bad_paths, env=env_idx, check=True)
        t_clean = subprocess.run(["git", "-C", real_clone, "write-tree"], env=env_idx, capture_output=True, check=True).stdout.strip()
        c_clean = commit_tree(real_clone, t_clean, [head_real], msg="cleanup-17")
        wf_files = git(real_clone, "ls-tree", "-r", "--name-only", c_clean, ".github/workflows").stdout.decode().splitlines()
        assert wf_files and ".github/workflows/formal-math.yml" not in wf_files, f"unexpected wf_files: {wf_files}"
        idx2 = os.path.join(tmp, "nowf.idx")
        env_idx2 = dict(GENV, GIT_INDEX_FILE=idx2)
        subprocess.run(["git", "-C", real_clone, "read-tree", c_clean], env=env_idx2, check=True)
        subprocess.run(["git", "-C", real_clone, "update-index", "--force-remove", "--"] + wf_files, env=env_idx2, check=True)
        t_nowf = subprocess.run(["git", "-C", real_clone, "write-tree"], env=env_idx2, capture_output=True, check=True).stdout.strip()
        c_nowf = commit_tree(real_clone, t_nowf, [c_clean], msg="rm-all-unmanaged-wf")
        c_rewf = commit_tree(real_clone, t_clean, [c_nowf], msg="readd-unmanaged-wf")
        for br in ("main", "proof/x", "decl/x", "audit/x", "infra/x"):
            verify("R3-B2-REAL", f"真实清理树删光 {len(wf_files)} 个非受信工作流使 .github/workflows 消失 ({br})",
                   run_pre(ns.precheck, real_clone, c_clean, c_nowf, br), 0)
            verify("R3-B2-REAL", f"真实清理树从无重建 .github/workflows ({br})",
                   run_pre(ns.precheck, real_clone, c_nowf, c_rewf, br), 0)

        print(f"R3 CLOSURE VERIFY SUMMARY: {total} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
