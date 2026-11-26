#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：本轮新增面三重点、小仓库三形态、退出码与输出契约探针集。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r4_probes.py [--precheck PATH]
"""
import argparse
import importlib.util
import os
import re
import shlex
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


def run_pre(precheck, args, env=RUN_ENV, py=(), **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    p = subprocess.run([sys.executable, "-I", *py, precheck, *args], env=env, **kw)
    return p.returncode, p.stdout, p.stderr


def parse_lines(out, err):
    out_items = LINE_RE.findall(out)
    err_items = LINE_RE.findall(err)
    reds = sorted({c.decode() for k, c in out_items if k == b"RED"})
    faults = sorted({c.decode() for k, c in err_items if k == b"FAULT"})
    ch_ok = (
        all(l.startswith(b"PRECHECK ") for l in out.splitlines())
        and all(k in (b"RED", b"GREEN") for k, _ in out_items)
        and all(k == b"FAULT" for k, _ in err_items)
    )
    return reds, faults, ch_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r4-probes-")
    FM = b"formal_math/"
    checks = []

    def expect(sec, label, got, exp_rc, exp_reds=None, exp_faults=None, extra_ok=True):
        rc, out, err = got
        reds, faults, ch_ok = parse_lines(out, err)
        ok = (
            rc == exp_rc
            and ch_ok
            and (exp_reds is None or sorted(exp_reds) == reds)
            and (exp_faults is None or sorted(exp_faults) == faults)
            and extra_ok
        )
        checks.append((sec, label, ok, rc, reds, faults, out.decode("utf-8", "replace").strip(), err.decode("utf-8", "replace").strip()))

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
            FM + b"garbage-signoffs.yaml": b"{}\n",
            FM + b"Chan.lean": b"module\n",
            FM + b"ChanExplore.lean": b"module\n",
            FM + b"Chan/Final.lean": b"module\n",
            FM + b"Chan/Defs/A.lean": b"module\n",
            FM + b"Chan/Thm/B.lean": b"module\n",
            FM + b"Chan/Audit/Math/C.lean": b"module\n",
            FM + b"ChanTest/T.lean": b"module\n",
            FM + b"ChanExplore/E.lean": b"module\n",
            FM + b"verification/run_gates.py": b"x\n",
            FM + b"sources/s.md": b"s\n",
            FM + b"blueprint/b.tex": b"b\n",
            b"scripts/fm_env.sh": b"e\n",
            b"scripts/other.sh": b"o\n",
            b".github/workflows/formal-math.yml": b"w\n",
            b".github/workflows/ci.yml": b"c\n",
            b"rust/lib.rs": b"r\n",
        }
        base = commit_tree(repo, build_tree(repo, BASE), msg="base")
        b_mod = blob(repo, b"module\n")
        b_x = blob(repo, b"x\n")
        b_e = blob(repo, b"e\n")
        t_sub = mktree(repo, [(b"100644", b"blob", b_x, b"a")])
        tag_oid = git(repo, "mktag", data=f"object {base}\ntype commit\ntag v0\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip()

        def mk(edits, parent=base, base_files=BASE):
            f = dict(base_files)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            return commit_tree(repo, build_tree(repo, f), [parent] if parent else (), msg="c")

        # =====================================================================
        # 重点 2a：祖先目录完全不进改动集合后的完整安全矩阵
        # =====================================================================
        NO_OUTSIDE_WITH_ANC = {k: v for k, v in BASE.items()
                               if k not in (b"scripts/fm_env.sh", b".github/workflows/formal-math.yml")}
        NO_OUTSIDE_NO_ANC = {k: v for k, v in BASE.items()
                             if not k.startswith(b"scripts/") and not k.startswith(b".github/")}
        b_has_anc = commit_tree(repo, build_tree(repo, NO_OUTSIDE_WITH_ANC), msg="has-anc-no-trusted")
        b_no_anc = commit_tree(repo, build_tree(repo, NO_OUTSIDE_NO_ANC), msg="no-anc-no-trusted")

        # 2a-1：基线不存在受信文件，被审提交以合法或各种非规范形态引入之（祖先原已存在 vs 祖先同时新建）
        for anc_tag, p_commit, p_dict in [("祖先已有", b_has_anc, NO_OUTSIDE_WITH_ANC),
                                          ("祖先新建", b_no_anc, NO_OUTSIDE_NO_ANC)]:
            for tpath in (b"scripts/fm_env.sh", b".github/workflows/formal-math.yml"):
                tp = tpath.decode()
                # 合法 100644 新增：infra 放行绿；infra 无放行红；非 infra 红
                h_ok = mk({tpath: b"new\n"}, parent=p_commit, base_files=p_dict)
                expect("2A-ABSENT-ADD", f"{anc_tag} 合法新增 {tp} (infra 放行)",
                       run_pre(ns.precheck, ["--trusted-change-approved", repo, p_commit, h_ok, "infra/x"]), 0, [], [])
                expect("2A-ABSENT-ADD", f"{anc_tag} 合法新增 {tp} (infra 无放行)",
                       run_pre(ns.precheck, [repo, p_commit, h_ok, "infra/x"]), 1, ["TRUST_UNAPPROVED"], [])
                expect("2A-ABSENT-ADD", f"{anc_tag} 合法新增 {tp} (proof/x)",
                       run_pre(ns.precheck, [repo, p_commit, h_ok, "proof/x"]), 1, ["PATH_SCOPE", "TRUSTED_DRIFT"], [])
                expect("2A-ABSENT-ADD", f"{anc_tag} 合法新增 {tp} (main)",
                       run_pre(ns.precheck, [repo, p_commit, h_ok, "main"]), 1, ["BRANCH_ROLE", "TRUSTED_DRIFT"], [])

                # 非规范形态新增（100755 / 120000 / 160000 / 空目录 / 非空目录）
                for shape_tag, val, infra_reds in [
                    ("100755", (b"100755", b"new\n"), ["MODE"]),
                    ("120000", (b"120000", b"target"), ["MODE"]),
                    ("160000", (b"160000", b"11" * 20), ["MODE"]),
                    ("空目录", {}, ["MODE", "PATH_SCOPE"]),
                    ("非空目录", {b"inner": b"x\n"}, ["MODE", "PATH_SCOPE"]),
                ]:
                    h_bad = mk({tpath: val}, parent=p_commit, base_files=p_dict)
                    expect("2A-ABSENT-BAD", f"{anc_tag} 新增非规范 {tp} ({shape_tag}, infra 放行)",
                           run_pre(ns.precheck, ["--trusted-change-approved", repo, p_commit, h_bad, "infra/x"]),
                           1, infra_reds, [])
                    expect("2A-ABSENT-BAD", f"{anc_tag} 新增非规范 {tp} ({shape_tag}, infra 无放行)",
                           run_pre(ns.precheck, [repo, p_commit, h_bad, "infra/x"]),
                           1, sorted(set(infra_reds) | {"TRUST_UNAPPROVED"}), [])
                    expect("2A-ABSENT-BAD", f"{anc_tag} 新增非规范 {tp} ({shape_tag}, proof/x)",
                           run_pre(ns.precheck, [repo, p_commit, h_bad, "proof/x"]),
                           1, ["MODE", "PATH_SCOPE", "TRUSTED_DRIFT"], [])
                    expect("2A-ABSENT-BAD", f"{anc_tag} 新增非规范 {tp} ({shape_tag}, main)",
                           run_pre(ns.precheck, [repo, p_commit, h_bad, "main"]),
                           1, ["BRANCH_ROLE", "MODE", "TRUSTED_DRIFT"], [])

            # 基线不存在 scripts/fm_env.sh，以 100664（原始字节非规范文件模式）或 100644->tree/missing 引入
            t_sc_664 = raw_entries(repo, [(b"100664", b"fm_env.sh", b_e)])
            h_sc_664 = mk({b"scripts": (b"RAW_TREE", t_sc_664)}, parent=p_commit, base_files=p_dict)
            expect("2A-ABSENT-BAD", f"{anc_tag} 新增 100664 fm_env.sh (infra 放行)",
                   run_pre(ns.precheck, ["--trusted-change-approved", repo, p_commit, h_sc_664, "infra/x"]), 1, ["MODE"], [])
            expect("2A-ABSENT-BAD", f"{anc_tag} 新增 100664 fm_env.sh (proof/x)",
                   run_pre(ns.precheck, [repo, p_commit, h_sc_664, "proof/x"]), 1, ["MODE", "PATH_SCOPE", "TRUSTED_DRIFT"], [])

            t_sc_tree = raw_entries(repo, [(b"100644", b"fm_env.sh", t_sub)])
            h_sc_tree = mk({b"scripts": (b"RAW_TREE", t_sc_tree)}, parent=p_commit, base_files=p_dict)
            expect("2A-ABSENT-BAD", f"{anc_tag} 新增 100644->tree fm_env.sh (infra 放行)",
                   run_pre(ns.precheck, ["--trusted-change-approved", repo, p_commit, h_sc_tree, "infra/x"]), 1, ["TREE_FORM"], [])

            t_sc_miss = raw_entries(repo, [(b"100644", b"fm_env.sh", b"aa" * 20)])
            h_sc_miss = mk({b"scripts": (b"RAW_TREE", t_sc_miss)}, parent=p_commit, base_files=p_dict)
            expect("2A-ABSENT-BAD", f"{anc_tag} 新增 100644->missing fm_env.sh (infra 放行)",
                   run_pre(ns.precheck, ["--trusted-change-approved", repo, p_commit, h_sc_miss, "infra/x"]), 2, [], ["GIT"])

        # 2a-2：基线有受信文件，删之（同时删光兄弟使祖先一起消失 vs 兄弟留存），验证 infra 有/无放行与非 infra
        for del_tag, edits in [
            ("删 fm_env.sh 且删光 scripts/", {b"scripts/fm_env.sh": None, b"scripts/other.sh": None}),
            ("删 formal-math.yml 且删光 .github/", {b".github/workflows/formal-math.yml": None, b".github/workflows/ci.yml": None}),
        ]:
            h_del = mk(edits)
            expect("2A-DEL", f"{del_tag} (infra 放行)",
                   run_pre(ns.precheck, ["--trusted-change-approved", repo, base, h_del, "infra/x"]), 0, [], [])
            expect("2A-DEL", f"{del_tag} (infra 无放行)",
                   run_pre(ns.precheck, [repo, base, h_del, "infra/x"]), 1, ["TRUST_UNAPPROVED"], [])
            expect("2A-DEL", f"{del_tag} (proof/x)",
                   run_pre(ns.precheck, [repo, base, h_del, "proof/x"]), 1, ["PATH_SCOPE", "TRUSTED_DRIFT"], [])
            expect("2A-DEL", f"{del_tag} (main)",
                   run_pre(ns.precheck, [repo, base, h_del, "main"]), 1, ["BRANCH_ROLE", "TRUSTED_DRIFT"], [])

        # 2a-3：祖先换成非目录（有/无受信文件时），验证 infra 无放行在有受信文件时报 MODE+TRUST_UNAPPROVED，无受信文件时只报 MODE
        h_anc_sym_with = mk({b"scripts/fm_env.sh": None, b"scripts/other.sh": None, b"scripts": (b"120000", b"x")})
        expect("2A-ANC-REPL", "有 fm_env.sh 时 scripts->symlink (infra 无放行)",
               run_pre(ns.precheck, [repo, base, h_anc_sym_with, "infra/x"]), 1, ["MODE", "TRUST_UNAPPROVED"], [])
        expect("2A-ANC-REPL", "有 fm_env.sh 时 scripts->symlink (infra 放行)",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, base, h_anc_sym_with, "infra/x"]), 1, ["MODE"], [])
        h_anc_sym_without = mk({b"scripts/other.sh": None, b"scripts": (b"120000", b"x")},
                               parent=b_has_anc, base_files=NO_OUTSIDE_WITH_ANC)
        expect("2A-ANC-REPL", "无 fm_env.sh 时 scripts->symlink (infra 无放行)",
               run_pre(ns.precheck, [repo, b_has_anc, h_anc_sym_without, "infra/x"]), 1, ["MODE"], [])

        # 2a-4：验证 managed() 下不存在 ANCESTORS 之下的其他受管路径
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("precheck_mod", ns.precheck)
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        anc_closure_ok = (
            pc.ANCESTORS == {b"scripts", b".github", b".github/workflows"}
            and set(pc.OUTSIDE) == {b"scripts/fm_env.sh", b".github/workflows/formal-math.yml"}
            and all(not pc.managed(p) for p in (
                b"scripts/other.sh", b"scripts/fm_env.sh/x", b"scripts/sub/fm_env.sh",
                b".github/formal-math.yml", b".github/workflows/ci.yml", b".github/workflows/formal-math.yml/x",
            ))
        )
        checks.append(("2A-CLOSURE", "managed() 在 ANCESTORS 下仅包含两个 OUTSIDE 受信文件",
                       anc_closure_ok, 0 if anc_closure_ok else 1, [], [],
                       f"ANCESTORS={sorted(pc.ANCESTORS)} OUTSIDE={pc.OUTSIDE}", ""))

        # =====================================================================
        # 重点 2b：normative() 共用对称性、合法历史不误退 2、恢复边界与 GIT/BASE_FORM 划分
        # =====================================================================
        # 2b-1：基线含各类形状问题（但不违背树结构与 blob 类型）时，被审清理后绝不能误退 2 BASE_FORM
        hist_cases = [
            ("基线含 formal_math/.gitignore，infra 放行删之", {FM + b".gitignore": b"x\n"}, {}, "infra/x", True, 0, []),
            ("基线含 100755 B.lean，proof 改回 100644", {FM + b"Chan/Thm/B.lean": (b"100755", b"module\n")}, {}, "proof/x", False, 0, []),
            ("基线含 100755 scripts/fm_env.sh，infra 放行改回 100644", {b"scripts/fm_env.sh": (b"100755", b"e\n")}, {}, "infra/x", True, 0, []),
            ("基线含 120000 symlink(blob) B.lean，proof 改回 100644", {FM + b"Chan/Thm/B.lean": (b"120000", b"A.lean")}, {}, "proof/x", False, 0, []),
            ("基线含 160000 子模块于 sources/sub，decl 删之", {FM + b"sources/sub": (b"160000", b"11" * 20)}, {}, "decl/x", False, 0, []),
            ("基线含空目录 Chan/Thm/Empty，proof 删之", {FM + b"Chan/Thm/Empty": {}}, {}, "proof/x", False, 0, []),
            ("基线含大小写冲突 b.lean，proof 删之", {FM + b"Chan/Thm/b.lean": b"module\n"}, {}, "proof/x", False, 0, []),
            ("基线含 Chan/Thm/lakefile.lean，proof 删之", {FM + b"Chan/Thm/lakefile.lean": b"x\n"}, {}, "proof/x", False, 0, []),
            ("基线含顶层未知文件 notes.txt，decl 删之报 PATH_SCOPE 而非 BASE_FORM", {FM + b"notes.txt": b"x\n"}, {}, "decl/x", False, 1, ["PATH_SCOPE"]),
            ("基线含非模块名 foo-bar.lean，proof 删之", {FM + b"Chan/Thm/foo-bar.lean": b"x\n"}, {}, "proof/x", False, 0, []),
            ("基线含 100664 非规范文件模式，proof 改回 100644",
             {FM + b"Chan/Thm": (b"RAW_TREE", raw_entries(repo, [(b"100664", b"B.lean", b_mod)]))}, {}, "proof/x", False, 0, []),
            ("基线含 040000 非规范目录模式，proof 改回 40000",
             {FM + b"Chan": (b"RAW_TREE", raw_entries(repo, [
                 (b"40000", b"Audit", git(repo, "rev-parse", f"{base}:formal_math/Chan/Audit").stdout.strip()),
                 (b"40000", b"Defs", git(repo, "rev-parse", f"{base}:formal_math/Chan/Defs").stdout.strip()),
                 (b"100644", b"Final.lean", b_mod),
                 (b"040000", b"Thm", git(repo, "rev-parse", f"{base}:formal_math/Chan/Thm").stdout.strip()),
             ]))}, {}, "proof/x", False, 0, []),
            # README:102 恢复边界验证：子目录 strictly within 角色规则可恢复（退 0），规则边界目录/formal_math 根报 PATH_SCOPE（退 1，不报 BASE_FORM）
            ("README:102 基线 Chan/Thm/Sub 为 120000 symlink，proof 恢复为目录 -> 退 0",
             {FM + b"Chan/Thm/Sub": (b"120000", b"x")}, {FM + b"Chan/Thm/Sub/X.lean": b"module\n"}, "proof/x", False, 0, []),
            ("README:102 基线 Chan/Thm 为 120000 symlink，proof 恢复为目录 -> 退 1 PATH_SCOPE（非 BASE_FORM）",
             {FM + b"Chan/Thm/B.lean": None, FM + b"Chan/Thm": (b"120000", b"x")}, {}, "proof/x", False, 1, ["PATH_SCOPE"]),
            ("README:102 基线 formal_math 为 120000 symlink，infra 放行恢复为目录 -> 退 1 PATH_SCOPE（非 BASE_FORM）",
             {**{k: None for k in BASE if k.startswith(FM)}, b"formal_math": (b"120000", b"x")},
             {**{k: None for k in BASE if k.startswith(FM)}, FM + b"lakefile.toml": b"x\n"}, "infra/x", True, 1, ["PATH_SCOPE"]),
        ]
        for label, b_edits, h_edits, br, app, exp_rc, exp_reds in hist_cases:
            bc = mk(b_edits, parent=None)
            hc = mk(h_edits, parent=bc)
            argv = (["--trusted-change-approved"] if app else []) + [repo, bc, hc, br]
            expect("2B-LEGIT-BASE", label, run_pre(ns.precheck, argv), exp_rc, exp_reds, [])

        # 2b-2：基线受管外子树（rust/）不规范或缺失 -> 忽略不读，退 0
        t_rust_dup = raw_entries(repo, [(b"100644", b"a.rs", b_x), (b"100644", b"a.rs", b_e)])
        b_rust_bad = mk({b"rust": (b"RAW_TREE", t_rust_dup)}, parent=None)
        h_rust_ok = mk({}, parent=b_rust_bad)
        expect("2B-UNMANAGED", "基线受管外 rust/ 树重名（被审正常）-> 忽略退 0",
               run_pre(ns.precheck, [repo, b_rust_bad, h_rust_ok, "main"]), 0, [], [])

        t_root_miss_rust = raw_entries(repo, [
            (b"40000", b".github", git(repo, "rev-parse", f"{base}:.github").stdout.strip()),
            (b"40000", b"formal_math", git(repo, "rev-parse", f"{base}:formal_math").stdout.strip()),
            (b"40000", b"rust", b"cc" * 20),
            (b"40000", b"scripts", git(repo, "rev-parse", f"{base}:scripts").stdout.strip()),
        ])
        b_miss_rust = commit_tree(repo, t_root_miss_rust, msg="base-miss-rust")
        h_miss_rust = mk({}, parent=b_miss_rust)
        expect("2B-UNMANAGED", "基线受管外 rust/ 指向缺失对象 -> 忽略退 0",
               run_pre(ns.precheck, [repo, b_miss_rust, h_miss_rust, "main"]), 0, [], [])

        # 2b-3：基线各类错误与被审红项组合时的次序与 GIT/BASE_FORM 划分
        # 基线受管子树缺失 -> 退 2 GIT，且被审红项已先报出
        t_fm_miss_sub = raw_entries(repo, [(b"40000", b"sources", b"dd" * 20)])
        b_miss_sub = mk({b"formal_math": (b"RAW_TREE", t_fm_miss_sub)}, parent=None, base_files=NO_OUTSIDE_NO_ANC)
        h_red_on_miss = mk({FM + b"Chan/Thm/lakefile.lean": b"x\n"}, parent=b_miss_sub)
        expect("2B-ORDER", "基线受管子树缺失 + 被审 LAKE_FILE -> 先报 LAKE_FILE 再退 2 GIT",
               run_pre(ns.precheck, [repo, b_miss_sub, h_red_on_miss, "proof/x"]), 2, ["LAKE_FILE"], ["GIT"])

        # 基线文件对象缺失 + 被审 MODE -> 先报 MODE 再退 2 GIT
        t_src_miss = raw_entries(repo, [(b"100644", b"s.md", b"ee" * 20)])
        b_miss_file = mk({FM + b"sources": (b"RAW_TREE", t_src_miss)}, parent=None)
        h_red_mode = mk({FM + b"Chan/Thm/B.lean": (b"100755", b"module\n")}, parent=b_miss_file)
        expect("2B-ORDER", "基线文件对象缺失 + 被审 MODE -> 先报 MODE 再退 2 GIT",
               run_pre(ns.precheck, [repo, b_miss_file, h_red_mode, "proof/x"]), 2, ["MODE"], ["GIT"])

        # 基线同时有树结构乱序与缺失文件对象 -> 仍退 2（因 file_objects 在检查 base_form 前跑，报 GIT），被审红项已先报出
        t_src_both = raw_entries(repo, [(b"100644", b"z.md", b"ee" * 20), (b"100644", b"a.md", b_x)])
        b_both = mk({FM + b"sources": (b"RAW_TREE", t_src_both)}, parent=None)
        h_red_both = mk({FM + b"Chan/Thm/B.lean": (b"100755", b"module\n")}, parent=b_both)
        expect("2B-ORDER", "基线同时树乱序+文件缺失 + 被审 MODE -> 先报 MODE 再退 2 GIT",
               run_pre(ns.precheck, [repo, b_both, h_red_both, "proof/x"]), 2, ["MODE"], ["GIT"])

        # 基线 scripts 指向非树 blob -> BASE_FORM 退 2（对象栏写 scripts）
        t_root_sc_blob = raw_entries(repo, [
            (b"40000", b".github", git(repo, "rev-parse", f"{base}:.github").stdout.strip()),
            (b"40000", b"formal_math", git(repo, "rev-parse", f"{base}:formal_math").stdout.strip()),
            (b"40000", b"rust", git(repo, "rev-parse", f"{base}:rust").stdout.strip()),
            (b"40000", b"scripts", b_e),
        ])
        b_sc_blob = commit_tree(repo, t_root_sc_blob, msg="base-sc-blob")
        h_sc_ok = mk({}, parent=b_sc_blob)
        expect("2B-SYM", "基线 scripts 40000->blob -> 退 2 BASE_FORM",
               run_pre(ns.precheck, [repo, b_sc_blob, h_sc_ok, "infra/x"]), 2, [], ["BASE_FORM"])

        # 基线根树损坏（截断）-> BASE_FORM 退 2，对象栏写 -
        t_root_trunc = git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin",
                           data=b"100644 a\0" + b"\x11" * 19).stdout.strip()
        b_root_trunc = commit_tree(repo, t_root_trunc, msg="base-root-trunc")
        h_after_trunc = mk({}, parent=b_root_trunc)
        got_rt = run_pre(ns.precheck, [repo, b_root_trunc, h_after_trunc, "main"])
        expect("2B-SYM", "基线根树截断 -> 退 2 BASE_FORM 且对象栏为 -",
               got_rt, 2, [], ["BASE_FORM"], extra_ok=(b"PRECHECK FAULT BASE_FORM - " in got_rt[2]))

        # =====================================================================
        # 重点 2c：先形状后对象类型（59504398f4 次序改动全组合）
        # =====================================================================
        miss_oid = b"99" * 20
        # 1) 纯对象缺失（100644 合法形状）-> 退 2 GIT，无红行
        t_pure_miss = raw_entries(repo, [(b"100644", b"s.md", miss_oid)])
        expect("2C-ORDER", "被审仅 100644->missing -> 退 2 GIT（无红行）",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_pure_miss)}), "decl/x"]),
               2, [], ["GIT"])

        # 2) 各类形状违规 + 对象缺失 -> 先报出对应形状红项，再退 2 GIT
        for tag, parent_dir, entry, br, exp_r in [
            ("120000->missing", FM + b"Chan/Thm", (b"120000", b"L.lean", miss_oid), "proof/x", ["MODE"]),
            ("100755->missing", FM + b"Chan/Thm", (b"100755", b"E.lean", miss_oid), "proof/x", ["MODE"]),
            ("100664->missing", FM + b"Chan/Thm", (b"100664", b"N.lean", miss_oid), "proof/x", ["MODE"]),
            ("LAKE_FILE->missing", FM + b"Chan/Thm", (b"100644", b"lakefile.lean", miss_oid), "proof/x", ["LAKE_FILE"]),
            ("PATH_GRAMMAR->missing", FM + b"sources", (b"100644", b".hidden", miss_oid), "decl/x", ["PATH_GRAMMAR"]),
            ("CONTENT_SHAPE->missing", FM + b"Chan/Thm", (b"100644", b"bad-name.lean", miss_oid), "proof/x", ["CONTENT_SHAPE"]),
        ]:
            t_d = raw_entries(repo, [entry])
            expect("2C-ORDER", f"被审 {tag} -> 先报 {exp_r} 再退 2 GIT",
                   run_pre(ns.precheck, [repo, base, mk({parent_dir: (b"RAW_TREE", t_d)}), br]),
                   2, exp_r, ["GIT"])

        # 顶层未知文件指向 missing -> 先报 TOP_LEVEL 再退 2 GIT
        t_fm_entries = [
            (b"40000", b"Chan", git(repo, "rev-parse", f"{base}:formal_math/Chan").stdout.strip()),
            (b"100644", b"unknown.txt", miss_oid),
        ]
        h_top_miss = mk({b"formal_math": (b"RAW_TREE", raw_entries(repo, t_fm_entries))},
                        parent=b_no_anc, base_files=NO_OUTSIDE_NO_ANC)
        expect("2C-ORDER", "被审顶层未知文件->missing -> 先报 TOP_LEVEL 再退 2 GIT",
               run_pre(ns.precheck, [repo, b_no_anc, h_top_miss, "decl/x"]), 2, ["TOP_LEVEL"], ["GIT"])

        # 3) 形状违规 + 对象类型不符（不缺失）-> 退 1，同时报形状码与 TREE_FORM
        for tag, mode, name, oid, exp_r in [
            ("120000->tree", b"120000", b"L.lean", t_sub, ["MODE", "TREE_FORM"]),
            ("100755->commit", b"100755", b"E.lean", base.encode(), ["MODE", "TREE_FORM"]),
            ("lakefile.lean->tag", b"100644", b"lakefile.lean", tag_oid, ["LAKE_FILE", "TREE_FORM"]),
        ]:
            t_d = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (mode, name, oid)])
            expect("2C-ORDER", f"被审 {tag} -> 退 1 且同时报 {exp_r}",
                   run_pre(ns.precheck, [repo, base, mk({FM + b"Chan/Thm": (b"RAW_TREE", t_d)}), "proof/x"]),
                   1, exp_r, [])

        # 4) 三者并存：文件 A (100644->tree) + 文件 B (100644->missing) + 文件 C (100755->blob)
        #    shape() 先报 C 的 MODE，随后 file_objects() 调 objects() 在 missing 处抛 GIT（不报 A 的 TREE_FORM）
        t_tri = raw_entries(repo, [
            (b"100644", b"a.md", t_sub),
            (b"100644", b"b.md", miss_oid),
            (b"100755", b"c.md", b_x),
        ])
        expect("2C-ORDER", "被审同时含 (a->tree, b->missing, c 100755) -> 先报 MODE，objects 遇缺失退 2 GIT",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_tri)}), "decl/x"]),
               2, ["MODE"], ["GIT"])

        # 5) 被审受管子树缺失 + 同层根树已有乱序 TREE_FORM -> 先报根树 TREE_FORM 再退 2 GIT
        t_root_ord_miss = raw_entries(repo, [
            (b"40000", b"scripts", git(repo, "rev-parse", f"{base}:scripts").stdout.strip()),
            (b"40000", b"formal_math", miss_oid),
        ])
        h_sub_miss = commit_tree(repo, t_root_ord_miss, [base], msg="ord-and-miss-sub")
        expect("2C-ORDER", "被审根树乱序 + formal_math 子树缺失 -> 先报 TREE_FORM 再退 2 GIT",
               run_pre(ns.precheck, [repo, base, h_sub_miss, "main"]), 2, ["TREE_FORM"], ["GIT"])

        # =====================================================================
        # 重点 3b：三种小仓库拓扑（无 formal_math / 只有 formal_math / 两者都有）的正常改动
        # =====================================================================
        # 3b-1：无 formal_math 小仓库（正常改源码、新增/修改/删除 scripts 与 .github/workflows、可执行脚本、隐藏文件、符号链接）
        r_nofm = os.path.join(tmp, "small_nofm")
        os.makedirs(r_nofm)
        git(r_nofm, "init", "-q")
        c0 = commit_tree(r_nofm, build_tree(r_nofm, {b"README.md": b"hi\n", b"src/main.rs": b"fn main(){}\n"}), msg="init")
        c1 = commit_tree(r_nofm, build_tree(r_nofm, {
            b"README.md": b"hi2\n", b"src/main.rs": b"fn main(){}\n", b".gitignore": b"target/\n",
            b"scripts/build.sh": (b"100755", b"#!/bin/sh\n"), b".github/workflows/ci.yml": b"name: ci\n",
            b"docs/link": (b"120000", b"../README.md"),
        }), [c0], msg="add-all-unmanaged")
        c2 = commit_tree(r_nofm, build_tree(r_nofm, {b"README.md": b"hi3\n"}), [c1], msg="del-all-unmanaged")
        for br in ("main", "feature/abc", "", "proof/x", "decl/x", "audit/x", "infra/x"):
            expect("3B-NOFM", f"无 formal_math 小仓：新增脚本/工作流/隐藏文件/链接 ({br!r})",
                   run_pre(ns.precheck, [r_nofm, c0, c1, br]), 0, [], [])
            expect("3B-NOFM", f"无 formal_math 小仓：删光 scripts 与 .github ({br!r})",
                   run_pre(ns.precheck, [r_nofm, c1, c2, br]), 0, [], [])

        # 3b-2：只有 formal_math 小仓库（无 scripts、无 .github）
        r_onlyfm = os.path.join(tmp, "small_onlyfm")
        os.makedirs(r_onlyfm)
        git(r_onlyfm, "init", "-q")
        only_base_files = {
            FM + b"lakefile.toml": b"name = \"Chan\"\n",
            FM + b"README.md": b"r\n",
            FM + b"Chan/Defs/A.lean": b"module\n",
            FM + b"Chan/Thm/B.lean": b"module\n",
            FM + b"Chan/Audit/Math/C.lean": b"module\n",
            FM + b"verification/run_gates.py": b"x\n",
        }
        of0 = commit_tree(r_onlyfm, build_tree(r_onlyfm, only_base_files), msg="init")
        for label, edits, br, app in [
            ("decl 改 Defs", {FM + b"Chan/Defs/A.lean": b"module2\n"}, "decl/d1", False),
            ("proof 改 Thm", {FM + b"Chan/Thm/B.lean": b"module2\n"}, "proof/p1", False),
            ("audit 改 Audit/Math", {FM + b"Chan/Audit/Math/C.lean": b"module2\n"}, "audit/a1", False),
            ("infra 无放行改 README", {FM + b"README.md": b"r2\n"}, "infra/doc", False),
            ("infra 放行改 lakefile.toml", {FM + b"lakefile.toml": b"v2\n"}, "infra/cfg", True),
            ("infra 放行改 verification", {FM + b"verification/run_gates.py": b"y\n"}, "infra/gate", True),
        ]:
            f = dict(only_base_files)
            f.update(edits)
            of1 = commit_tree(r_onlyfm, build_tree(r_onlyfm, f), [of0], msg=label)
            argv = (["--trusted-change-approved"] if app else []) + [r_onlyfm, of0, of1, br]
            expect("3B-ONLYFM", f"只有 formal_math 小仓：{label}", run_pre(ns.precheck, argv), 0, [], [])

        # 3b-3：两者都有小仓库（正常改四角色 + 同提交带非受信脚本/工作流增删）
        r_both = os.path.join(tmp, "small_both")
        os.makedirs(r_both)
        git(r_both, "init", "-q")
        both_base_files = {**only_base_files, b"rust/lib.rs": b"r\n", b"scripts/fm_env.sh": b"e\n", b".github/workflows/ci.yml": b"c\n"}
        bf0 = commit_tree(r_both, build_tree(r_both, both_base_files), msg="init")
        for label, edits, br, app in [
            ("main 仅删 ci.yml 与改 rust", {b".github/workflows/ci.yml": None, b"rust/lib.rs": b"r2\n"}, "main", False),
            ("proof 改 Thm + 加 scripts/helper.sh", {FM + b"Chan/Thm/B.lean": b"m2\n", b"scripts/helper.sh": (b"100755", b"x\n")}, "proof/p2", False),
            ("decl 改 Defs + 删 ci.yml", {FM + b"Chan/Defs/A.lean": b"m2\n", b".github/workflows/ci.yml": None}, "decl/d2", False),
            ("infra 放行新增 formal-math.yml + 改 fm_env.sh", {b".github/workflows/formal-math.yml": b"w\n", b"scripts/fm_env.sh": b"e2\n"}, "infra/i2", True),
        ]:
            f = dict(both_base_files)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            bf1 = commit_tree(r_both, build_tree(r_both, f), [bf0], msg=label)
            argv = (["--trusted-change-approved"] if app else []) + [r_both, bf0, bf1, br]
            expect("3B-BOTH", f"两者都有小仓：{label}", run_pre(ns.precheck, argv), 0, [], [])

        # =====================================================================
        # 重点 7：退出码、输出契约与 file_objects() 空清单短路验证
        # =====================================================================
        # 7-1：空清单短路（无 formal_math 且无受信文件时，cat-file --batch-check 调用次数必须为 0）
        log_file = os.path.join(tmp, "git_calls.log")
        wrap_dir = os.path.join(tmp, "count_git")
        os.makedirs(wrap_dir)
        real_git = shutil.which("git")
        with open(os.path.join(wrap_dir, "git"), "w", encoding="utf-8") as f:
            f.write(
                f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {shlex.quote(log_file)}\nexec {shlex.quote(real_git)} \"$@\"\n"
            )
        os.chmod(os.path.join(wrap_dir, "git"), 0o755)
        wrap_env = {**RUN_ENV, "PATH": wrap_dir + os.pathsep + RUN_ENV["PATH"]}
        got_short = run_pre(ns.precheck, [r_nofm, c0, c1, "main"], env=wrap_env)
        calls = open(log_file, encoding="utf-8").read().splitlines()
        bc_calls = [ln for ln in calls if "--batch-check" in ln]
        expect("7-SHORT", f"空清单短路：无受管文件时不调用 --batch-check（实际调用 {len(bc_calls)} 次，总 git {len(calls)} 次）",
               got_short, 0, [], [], extra_ok=(len(bc_calls) == 0))

        # 7-2：输出契约再核（关闭 stderr、关闭 stdout、断管、ASCII locale、非 UTF-8 分支）
        h_ok_p = mk({FM + b"Chan/Thm/B.lean": b"ok\n"})
        h_red_p = mk({FM + b"Chan/Defs/A.lean": b"bad\n"})
        p_no_err = subprocess.run([sys.executable, "-I", ns.precheck, repo, base, h_ok_p, "proof/x"],
                                  env=RUN_ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  preexec_fn=lambda: os.close(2))
        expect("7-IO", "关闭 fd 2 绿例退 0", (p_no_err.returncode, p_no_err.stdout, b""), 0, [], [])

        p_fault_no_err = subprocess.run([sys.executable, "-I", ns.precheck, repo, "nope", h_ok_p, "proof/x"],
                                        env=RUN_ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                        preexec_fn=lambda: os.close(2))
        expect("7-IO", "关闭 fd 2 故障例退 2", (p_fault_no_err.returncode, p_fault_no_err.stdout, b""), 2, [], [])

        p_no_out = subprocess.run([sys.executable, "-I", ns.precheck, repo, base, h_ok_p, "proof/x"],
                                  env=RUN_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                  preexec_fn=lambda: os.close(1))
        expect("7-IO", "关闭 fd 1 绿例退 2 OUTPUT", (p_no_out.returncode, b"", p_no_out.stderr), 2, [], ["OUTPUT"])

        rd, wr = os.pipe()
        os.close(rd)
        p_bp_red = run_pre(ns.precheck, [repo, base, h_red_p, "proof/x"], stdout=wr, stderr=subprocess.PIPE)
        os.close(wr)
        expect("7-IO", "断管红例仍退 1", (p_bp_red[0], b"", p_bp_red[2]), 1, [], [])

        ascii_env = {"PATH": RUN_ENV["PATH"], "LC_ALL": "C"}
        got_nonutf = run_pre(ns.precheck, [repo, base, h_ok_p, os.fsdecode(b"bad/\xff\xfe")],
                             env=ascii_env, py=("-X", "utf8=0"))
        expect("7-IO", "ASCII locale 下非 UTF-8 分支名改受管路径报 BRANCH_ROLE 且正确转义 \\xff\\xfe",
               got_nonutf, 1, ["BRANCH_ROLE"], [], extra_ok=(b"bad/\\xff\\xfe" in got_nonutf[1]))

        failed = 0
        for sec, label, ok, rc, reds, faults, out, err in checks:
            if not ok:
                failed += 1
            print(f"[{'PASS' if ok else 'FAIL'}] [{sec}] {label} (rc={rc}, red={reds}, fault={faults})")
            if not ok:
                print(f"    out: {out}\n    err: {err}")
        print(f"R4 PROBES SUMMARY: {len(checks)} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
