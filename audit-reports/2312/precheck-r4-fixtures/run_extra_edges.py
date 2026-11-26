#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：补充边界探针（裸仓、带注释标签、空 blob、无关历史、合并提交、repo-level git config、深层目录、特殊分支名转义）。"""
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
            else:
                items.append((b"100644", b"blob", blob(repo, val), name))
        return mktree(repo, items)

    return rec(spec)


def run_pre(precheck, args):
    p = subprocess.run([sys.executable, "-I", precheck, *args], env=RUN_ENV, capture_output=True)
    out_items = LINE_RE.findall(p.stdout)
    err_items = LINE_RE.findall(p.stderr)
    reds = sorted({c.decode() for k, c in out_items if k == b"RED"})
    faults = sorted({c.decode() for k, c in err_items if k == b"FAULT"})
    return p.returncode, reds, faults, p.stdout, p.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r4-extra-")
    FM = b"formal_math/"
    total = 0
    failed = 0

    def verify(label, got, exp_rc, exp_reds=(), exp_faults=(), extra_ok=True):
        nonlocal total, failed
        total += 1
        rc, reds, faults, out, err = got
        ok = rc == exp_rc and sorted(exp_reds) == reds and sorted(exp_faults) == faults and extra_ok
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {label} => rc={rc} red={reds} fault={faults}")
        if not ok:
            print(f"    out={out!r} err={err!r}")

    try:
        # 1. 裸仓库（bare repo）+ 0 字节空 blob + 深层目录 + 合并提交 + 注释标签 + 简短 SHA + 无关孤儿历史 + 仓库级 config
        bare = os.path.join(tmp, "bare.git")
        os.makedirs(bare)
        git(bare, "init", "--bare", "-q")
        # 故意配一堆仓库级 git config（core.quotepath, ignorecase, diff.renames）
        git(bare, "config", "core.quotepath", "true")
        git(bare, "config", "core.ignorecase", "true")
        git(bare, "config", "diff.renames", "copies")

        base_f = {FM + b"Chan/Thm/B.lean": b"module\n", FM + b"sources/s.md": b"s\n", b"rust/a.rs": b"r\n"}
        c0 = commit_tree(bare, build_tree(bare, base_f), msg="base")
        # 0 字节文件 + 10 层深目录
        deep_f = {**base_f, FM + b"Chan/Thm/A/B/C/D/E/F/G/H/I/J/Zero.lean": b""}
        c1 = commit_tree(bare, build_tree(bare, deep_f), [c0], msg="deep-zero")
        # 分叉另一支做合并提交（两父）
        side_f = {**base_f, b"rust/a.rs": b"r2\n", b"scripts/other.sh": b"o\n"}
        c_side = commit_tree(bare, build_tree(bare, side_f), [c0], msg="side")
        merge_f = {**deep_f, b"rust/a.rs": b"r2\n", b"scripts/other.sh": b"o\n"}
        c_merge = commit_tree(bare, build_tree(bare, merge_f), [c_side, c1], msg="merge")
        # 孤儿提交（无关历史）
        c_orphan = commit_tree(bare, build_tree(bare, base_f), msg="orphan")
        # 注释标签指向 c0 与 c1
        t0 = git(bare, "mktag", data=f"object {c0}\ntype commit\ntag v0\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip().decode()
        t1 = git(bare, "mktag", data=f"object {c1}\ntype commit\ntag v1\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip().decode()
        git(bare, "update-ref", "refs/tags/v0", t0)
        git(bare, "update-ref", "refs/tags/v1", t1)

        verify("裸仓 + 0字节空blob + 10层深目录 + 仓库级config (proof/x)",
               run_pre(ns.precheck, [bare, c0, c1, "proof/x"]), 0)
        verify("裸仓 + 注释标签 revspec v0..v1 (proof/x)",
               run_pre(ns.precheck, [bare, "v0", "v1", "proof/x"]), 0,
               extra_ok=(f"PRECHECK GREEN OK {c1} role=proof\n".encode() == run_pre(ns.precheck, [bare, "v0", "v1", "proof/x"])[3]))
        verify("裸仓 + 简短 SHA (proof/x)",
               run_pre(ns.precheck, [bare, c0[:8], c1[:8], "proof/x"]), 0)
        verify("裸仓 + 合并提交相对第一父（含受管改动+新建 scripts）(proof/x)",
               run_pre(ns.precheck, [bare, c_side, c_merge, "proof/x"]), 0)
        verify("裸仓 + 合并提交相对第二父（仅受管外改动+新建 scripts）(main)",
               run_pre(ns.precheck, [bare, c1, c_merge, "main"]), 0)
        verify("裸仓 + 无关孤儿基线 -> NOT_ANCESTOR 退 2",
               run_pre(ns.precheck, [bare, c_orphan, c1, "proof/x"]), 2, exp_faults=("NOT_ANCESTOR",))
        # 分支名含反斜杠、制表符、中文：无受管改动绿，有受管改动报 BRANCH_ROLE 且单行正确转义
        weird_br = "中文\\分支\t名"
        verify("特殊分支名（反斜杠/制表符/中文）无受管改动绿",
               run_pre(ns.precheck, [bare, c0, c_side, weird_br]), 0)
        got_wb = run_pre(ns.precheck, [bare, c0, c1, weird_br])
        verify("特殊分支名有受管改动报 BRANCH_ROLE 且单行转义",
               got_wb, 1, exp_reds=("BRANCH_ROLE",),
               extra_ok=(got_wb[3].count(b"\n") == 1 and b"\\x5c" in got_wb[3] and b"\\x09" in got_wb[3]))
        # 指向 blob 的注释标签 -> BAD_REV 退 2
        b_oid = blob(bare, b"x\n").decode()
        t_blob = git(bare, "mktag", data=f"object {b_oid}\ntype blob\ntag vb\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip().decode()
        verify("指向 blob 的注释标签作基线 -> BAD_REV 退 2",
               run_pre(ns.precheck, [bare, t_blob, c1, "proof/x"]), 2, exp_faults=("BAD_REV",))

        print(f"EXTRA EDGE PROBES SUMMARY: {total} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
