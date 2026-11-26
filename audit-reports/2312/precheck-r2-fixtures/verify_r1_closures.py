#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R2：R1 B1–B5 闭合复验（含原样复现 + 每条至少一种 R1 未测过的新同类形状）。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I verify_r1_closures.py
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


def git(repo, *args, data=None):
    p = subprocess.run(["git", "-C", repo, *args], input=data, env=GENV, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"git {args} failed: {p.returncode} {p.stderr.decode('utf-8', 'replace')}")
    return p


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).stdout.strip()


def mktree(repo, entries):
    return git(repo, "mktree", "-z", "--missing", data=b"".join(b"%s %s %s\t%s\0" % e for e in entries)).stdout.strip()


def raw_entries(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m, n, bytes.fromhex(o.decode())) for m, n, o in entries)
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).stdout.strip()


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
    tmp = tempfile.mkdtemp(prefix="precheck-r1-closure-")
    FM = b"formal_math/"
    failed = 0
    total = 0

    def verify(group, label, got, exp_rc, req_codes=()):
        nonlocal failed, total
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
        BASE = {
            FM + b"lakefile.toml": b'name = "Chan"\n',
            FM + b"lake-manifest.json": b"{}\n",
            FM + b"lean-toolchain": b"v4\n",
            FM + b"README.md": b"r\n",
            FM + b"HISTORY.md": b"h\n",
            FM + b"statement-lock.json": b"{}\n",
            FM + b"formalization.yaml": b"{}\n",
            FM + b"Chan/Defs/A.lean": b"module\n",
            FM + b"Chan/Thm/B.lean": b"module\n",
            FM + b"Chan/Audit/Math/C.lean": b"module\n",
            FM + b"verification/run_gates.py": b"x\n",
            FM + b"sources/s.md": b"s\n",
            FM + b"blueprint/b.tex": b"b\n",
            b"scripts/fm_env.sh": b"e\n",
            b"scripts/other.sh": b"o\n",
            b".github/workflows/formal-math.yml": b"w\n",
            b".github/workflows/ci.yml": b"c\n",
            b"rust/lib.rs": b"r\n",
        }
        t_base = build_tree(repo, BASE)
        base = commit_tree(repo, t_base, msg="base")
        b_mod = blob(repo, b"module\n")
        b_link = blob(repo, b"/etc/passwd")
        b_run = blob(repo, b"x\n")
        b_env = blob(repo, b"e\n")
        b_wf = blob(repo, b"w\n")
        t_empty = mktree(repo, [])
        t_sub = mktree(repo, [(b"100644", b"blob", b_mod, b"E.lean")])
        t_defs = git(repo, "rev-parse", f"{base}:formal_math/Chan/Defs").stdout.strip()
        t_audit = git(repo, "rev-parse", f"{base}:formal_math/Chan/Audit").stdout.strip()
        t_fm = git(repo, "rev-parse", f"{base}:formal_math").stdout.strip()
        t_scripts = git(repo, "rev-parse", f"{base}:scripts").stdout.strip()
        t_gh = git(repo, "rev-parse", f"{base}:.github").stdout.strip()
        t_rust = git(repo, "rev-parse", f"{base}:rust").stdout.strip()
        fm_ents = parse_tree(repo, t_fm)

        def mk(edits, parent=base):
            f = dict(BASE)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            return commit_tree(repo, build_tree(repo, f), [parent], msg="c")

        # --- B1: 原样 + 新形状 ---
        for tag, mode, oid, req in [
            ("B1a 原样 symlink+tree", b"120000", b_link, ("TREE_FORM", "MODE")),
            ("B1a 原样 exec+tree", b"100755", b_mod, ("TREE_FORM", "MODE")),
            ("B1a 原样 gitlink+tree", b"160000", b"1" * 40, ("TREE_FORM", "MODE")),
            ("B1a 原样 non-lean-blob+tree", b"100644", b_link, ("TREE_FORM", "CONTENT_SHAPE")),
        ]:
            t_thm = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (mode, b"Sub", oid),
                                       (b"100644", b"Sub.lean", b_mod), (b"40000", b"Sub", t_sub)])
            t_ch = mktree(repo, [(b"040000", b"tree", t_audit, b"Audit"), (b"040000", b"tree", t_defs, b"Defs"),
                                 (b"040000", b"tree", t_thm, b"Thm")])
            verify("B1", tag, run_pre(ns.precheck, repo, base, mk({FM + b"Chan": (b"RAW_TREE", t_ch)}), "proof/x"), 1, req)

        # B1b 原样：根上 (120000 formal_math) + (40000 formal_math)
        h_b1b = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh), (b"120000", b"formal_math", b_link),
            (b"40000", b"formal_math", t_fm), (b"40000", b"rust", t_rust), (b"40000", b"scripts", t_scripts),
        ]), [base])
        verify("B1", "B1b 原样 main", run_pre(ns.precheck, repo, base, h_b1b, "main"), 1, ("TREE_FORM", "MODE", "BRANCH_ROLE"))
        verify("B1", "B1b 原样 proof/x", run_pre(ns.precheck, repo, base, h_b1b, "proof/x"), 1, ("TREE_FORM", "MODE", "PATH_SCOPE"))

        # B1 新形状：反序 (tree 在 symlink 前)、scripts/ 内重名 fm_env.sh、.github/workflows/ 内重名 formal-math.yml、根上重名 scripts
        t_thm_rev = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (b"40000", b"Sub", t_sub), (b"120000", b"Sub", b_link)])
        t_ch_rev = mktree(repo, [(b"040000", b"tree", t_audit, b"Audit"), (b"040000", b"tree", t_defs, b"Defs"),
                                 (b"040000", b"tree", t_thm_rev, b"Thm")])
        verify("B1", "新形状：Chan/Thm 反序（tree 在 symlink 前）",
               run_pre(ns.precheck, repo, base, mk({FM + b"Chan": (b"RAW_TREE", t_ch_rev)}), "proof/x"), 1, ("TREE_FORM",))
        t_s_dup = raw_entries(repo, [(b"100644", b"fm_env.sh", b_env), (b"120000", b"fm_env.sh", b_link),
                                     (b"100644", b"other.sh", blob(repo, b"o\n"))])
        verify("B1", "新形状：scripts/ 内重名 fm_env.sh（blob+symlink，main）",
               run_pre(ns.precheck, repo, base, mk({b"scripts": (b"RAW_TREE", t_s_dup)}), "main"), 1, ("TREE_FORM",))
        t_wf_dup = raw_entries(repo, [(b"100644", b"ci.yml", blob(repo, b"c\n")), (b"100644", b"formal-math.yml", b_wf),
                                      (b"40000", b"formal-math.yml", t_empty)])
        verify("B1", "新形状：.github/workflows/ 内重名 formal-math.yml（blob+tree，main）",
               run_pre(ns.precheck, repo, base, mk({b".github": (b"RAW_TREE", mktree(repo, [(b"040000", b"tree", t_wf_dup, b"workflows")]))}), "main"),
               1, ("TREE_FORM",))
        h_r_sdup = commit_tree(repo, raw_entries(repo, [
            (b"40000", b".github", t_gh), (b"40000", b"formal_math", t_fm), (b"40000", b"rust", t_rust),
            (b"120000", b"scripts", b_link), (b"40000", b"scripts", t_scripts),
        ]), [base])
        verify("B1", "新形状：根树重名 scripts（symlink+原树，main）",
               run_pre(ns.precheck, repo, base, h_r_sdup, "main"), 1, ("TREE_FORM", "MODE"))

        # --- B2: 原样 + 新形状 ---
        c_nofm = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_rust, b"rust")]), msg="nofm")
        c_empty_fm = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_empty, b"formal_math"),
                                                     (b"040000", b"tree", t_rust, b"rust")]), [c_nofm])
        verify("B2", "B2a 原样 新增空 formal_math (proof/x)", run_pre(ns.precheck, repo, c_nofm, c_empty_fm, "proof/x"), 1, ("EMPTY_TREE",))
        verify("B2", "B2a 原样 新增空 formal_math (infra 无放行)", run_pre(ns.precheck, repo, c_nofm, c_empty_fm, "infra/x"), 1, ("EMPTY_TREE",))
        c_only_rm = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", mktree(repo, [(b"100644", b"blob", blob(repo, b"r\n"), b"README.md")]), b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"),
        ]), msg="only-rm")
        c_del_empty = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_empty, b"formal_math"),
                                                      (b"040000", b"tree", t_rust, b"rust")]), [c_only_rm])
        verify("B2", "B2b 原样 删光文件留空 formal_math (infra 无放行)",
               run_pre(ns.precheck, repo, c_only_rm, c_del_empty, "infra/x"), 1, ("EMPTY_TREE",))
        # B2 新形状：仅含嵌套空目录 formal_math/Chan/Thm；仅删光 verification/ 留下空门禁目录
        t_fm_nest = mktree(repo, [(b"040000", b"tree", mktree(repo, [(b"040000", b"tree", t_empty, b"Thm")]), b"Chan")])
        c_nest = commit_tree(repo, mktree(repo, [(b"040000", b"tree", t_fm_nest, b"formal_math"),
                                                 (b"040000", b"tree", t_rust, b"rust")]), [c_nofm])
        verify("B2", "新形状：嵌套空目录 formal_math/Chan/Thm 无任何文件 (proof/x)",
               run_pre(ns.precheck, repo, c_nofm, c_nest, "proof/x"), 1, ("EMPTY_TREE",))
        verify("B2", "新形状：删光 verification/ 留下空门禁目录 (infra 有放行)",
               run_pre(ns.precheck, repo, base, mk({FM + b"verification/run_gates.py": None, FM + b"verification": {}}), "infra/x", True),
               1, ("EMPTY_TREE",))

        # --- B3: 原样 + 新形状 ---
        c_base_ve = commit_tree(repo, build_tree(repo, {**BASE, FM + b"verification/Empty": {}}), msg="base-ve")
        c_head_ve = commit_tree(repo, t_base, [c_base_ve], msg="del-ve")
        verify("B3", "B3a 原样 infra 无放行删门禁空子树", run_pre(ns.precheck, repo, c_base_ve, c_head_ve, "infra/x"), 1, ("TRUST_UNAPPROVED",))
        c_base_de = commit_tree(repo, build_tree(repo, {**BASE, FM + b"Chan/Defs/Empty": {}}), msg="base-de")
        c_head_de = commit_tree(repo, t_base, [c_base_de], msg="del-de")
        verify("B3", "B3b 原样 proof 删 decl 空子树", run_pre(ns.precheck, repo, c_base_de, c_head_de, "proof/x"), 1, ("PATH_SCOPE",))
        t_v664 = raw_entries(repo, [(b"100664", b"run_gates.py", b_run)])
        verify("B3", "B3c 原样 infra 无放行改门禁文件为 100664",
               run_pre(ns.precheck, repo, base, mk({FM + b"verification": (b"RAW_TREE", t_v664)}), "infra/x"),
               1, ("MODE", "TRUST_UNAPPROVED"))
        # B3 新形状：infra 无放行改 verification 目录节点模式为 040000；decl 改 lakefile.toml 为 100664；infra 无放行新增 verification/Empty
        t_fm_v04 = raw_entries(repo, [(b"040000" if n == b"verification" else m, n, o) for m, n, o in fm_ents])
        h_v04 = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_gh, b".github"), (b"040000", b"tree", t_fm_v04, b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"), (b"040000", b"tree", t_scripts, b"scripts"),
        ]), [base])
        verify("B3", "新形状：infra 无放行改 verification 目录节点模式 40000->040000",
               run_pre(ns.precheck, repo, base, h_v04, "infra/x"), 1, ("MODE", "TRUST_UNAPPROVED"))
        t_fm_lf664 = raw_entries(repo, [(b"100664" if n == b"lakefile.toml" else m, n, o) for m, n, o in fm_ents])
        h_lf664 = commit_tree(repo, mktree(repo, [
            (b"040000", b"tree", t_gh, b".github"), (b"040000", b"tree", t_fm_lf664, b"formal_math"),
            (b"040000", b"tree", t_rust, b"rust"), (b"040000", b"tree", t_scripts, b"scripts"),
        ]), [base])
        verify("B3", "新形状：decl 改 lakefile.toml 为 100664",
               run_pre(ns.precheck, repo, base, h_lf664, "decl/x"), 1, ("MODE", "PATH_SCOPE", "TRUSTED_DRIFT"))
        verify("B3", "新形状：infra 无放行新增 verification/Empty",
               run_pre(ns.precheck, repo, base, mk({FM + b"verification/Empty": {}}), "infra/x"), 1, ("EMPTY_TREE", "TRUST_UNAPPROVED"))

        # --- B4: 原样 + 新形状 ---
        verify("B4", "B4 原样 Chan/Thm/lakefile.lean (proof/x)",
               run_pre(ns.precheck, repo, base, mk({FM + b"Chan/Thm/lakefile.lean": b"x\n"}), "proof/x"), 1, ("LAKE_FILE",))
        verify("B4", "B4 原样 sources/lakefile.lean (decl/x)",
               run_pre(ns.precheck, repo, base, mk({FM + b"sources/lakefile.lean": b"x\n"}), "decl/x"), 1, ("LAKE_FILE",))
        verify("B4", "新形状：Chan/Defs/Lakefile.Lean（混合大小写，decl/x）",
               run_pre(ns.precheck, repo, base, mk({FM + b"Chan/Defs/Lakefile.Lean": b"x\n"}), "decl/x"), 1, ("LAKE_FILE", "CONTENT_SHAPE"))
        verify("B4", "新形状：Chan/Audit/Math/LAKEFILE.lean（全大写，audit/x）",
               run_pre(ns.precheck, repo, base, mk({FM + b"Chan/Audit/Math/LAKEFILE.lean": b"x\n"}), "audit/x"), 1, ("LAKE_FILE",))
        verify("B4", "新形状：verification/auditor/Lakefile.toml（例外路径大小写变体，infra 放行）",
               run_pre(ns.precheck, repo, base, mk({FM + b"verification/auditor/Lakefile.toml": b"x\n"}), "infra/x", True), 1, ("LAKE_FILE",))
        verify("B4", "新形状：verification/auditor/sub/lean-toolchain（例外路径更深层，infra 放行）",
               run_pre(ns.precheck, repo, base, mk({FM + b"verification/auditor/sub/lean-toolchain": b"v4\n"}), "infra/x", True), 1, ("LAKE_FILE",))
        verify("B4", "新形状：sources/lakefile.toml 作为目录（decl/x）",
               run_pre(ns.precheck, repo, base, mk({FM + b"sources/lakefile.toml/a.md": b"x\n"}), "decl/x"), 1, ("LAKE_FILE",))

        # --- B5: 按新设计核对行为（受管外改动不判红） ---
        verify("B5", "B5 原样 proof/x 仅改 rust/lib.rs（按新设计退 0）",
               run_pre(ns.precheck, repo, base, mk({b"rust/lib.rs": b"changed\n"}), "proof/x"), 0)
        verify("B5", "新形状：proof/x 同改 Chan/Thm/B.lean + rust/lib.rs + ci.yml + scripts/other.sh（按新设计退 0）",
               run_pre(ns.precheck, repo, base, mk({FM + b"Chan/Thm/B.lean": b"changed\n", b"rust/lib.rs": b"z\n",
                                                    b".github/workflows/ci.yml": b"z\n", b"scripts/other.sh": b"z\n"}), "proof/x"), 0)
        verify("B5", "新形状：infra/x 无放行同改 README.md + scripts/other.sh + ci.yml（按新设计退 0）",
               run_pre(ns.precheck, repo, base, mk({FM + b"README.md": b"changed\n", b"scripts/other.sh": b"z\n",
                                                    b".github/workflows/ci.yml": b"z\n"}), "infra/x"), 0)

        print(f"R1 CLOSURE SUMMARY: {total} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
