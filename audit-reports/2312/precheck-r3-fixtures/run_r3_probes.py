#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R3：本轮新增面三重点、无误红矩阵、退出码与输出契约探针集。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r3_probes.py [--precheck PATH] [--real-repo PATH]
"""
import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

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


def raw_tree(repo, body):
    return git(repo, "hash-object", "-t", "tree", "-w", "--literally", "--stdin", data=body).stdout.strip()


def raw_entries(repo, entries):
    return raw_tree(repo, b"".join(b"%s %s\0%s" % (m, n, bytes.fromhex(o.decode())) for m, n, o in entries))


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
    out_codes = sorted({c.decode() for k, c in out_items if k == b"RED"})
    err_codes = sorted({c.decode() for k, c in err_items if k == b"FAULT"})
    return out_codes, err_codes, out_items, err_items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ap.add_argument("--real-repo", default=ROOT)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r3-probes-")
    FM = b"formal_math/"
    checks = []

    def expect(sec, label, got, exp_rc, req_red=(), req_fault=(), extra_ok=True):
        rc, out, err = got
        rcodes, fcodes, oitems, eitems = parse_lines(out, err)
        ch_ok = (
            all(l.startswith(b"PRECHECK ") for l in out.splitlines())
            and all(k in (b"RED", b"GREEN") for k, _ in oitems)
            and all(k == b"FAULT" for k, _ in eitems)
        )
        ok = (
            rc == exp_rc
            and ch_ok
            and all(c in rcodes for c in req_red)
            and all(c in fcodes for c in req_fault)
            and extra_ok
        )
        checks.append((sec, label, ok, rc, rcodes, fcodes, out.decode("utf-8", "replace").strip(), err.decode("utf-8", "replace").strip()))

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
        t_base = build_tree(repo, BASE)
        base = commit_tree(repo, t_base, msg="base")
        b_mod = blob(repo, b"module\n")
        b_x = blob(repo, b"x\n")
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

        # === 1. 次序变化：无条件检查先于读基线，BASE_FORM 退 2 时先报被审红项 ===
        t_bad_ord = raw_entries(repo, [(b"100644", b"z.md", b_x), (b"100644", b"a.md", b_x)])
        c_bad_base = mk({FM + b"sources": (b"RAW_TREE", t_bad_ord)}, parent=None)
        # 被审有 LAKE_FILE + MODE + file_objects TREE_FORM，同时基线不规范
        t_src_tree_file = raw_entries(repo, [(b"100644", b"evil.md", t_sub), (b"100644", b"s.md", b_x)])
        c_head_multi = mk({
            FM + b"sources": (b"RAW_TREE", t_src_tree_file),
            FM + b"Chan/Thm/lakefile.lean": b"x\n",
            FM + b"Chan/Thm/exec.lean": (b"100755", b"module\n"),
        }, parent=c_bad_base)
        expect("ORDER", "BASE_FORM 退 2 时先报出被审提交的 TREE_FORM + LAKE_FILE + MODE",
               run_pre(ns.precheck, [repo, c_bad_base, c_head_multi, "proof/x"]),
               2, req_red=("TREE_FORM", "LAKE_FILE", "MODE"), req_fault=("BASE_FORM",))

        # 探针（不符 README:47）：基线里文件条目指向 tree（非 blob），被审提交删/修它 -> 实际行为观察
        c_base_f2t = mk({FM + b"sources": (b"RAW_TREE", t_src_tree_file)}, parent=None)
        c_head_fix = commit_tree(repo, t_base, [c_base_f2t], msg="fix-f2t")
        got_fix = run_pre(ns.precheck, [repo, c_base_f2t, c_head_fix, "decl/x"])
        print(f"[OBSERVE-BASE-FILEOBJ] base 含 100644->tree, head 修复之 (decl/x): rc={got_fix[0]} out={got_fix[1].decode().strip()!r} err={got_fix[2].decode().strip()!r}")
        got_same = run_pre(ns.precheck, [repo, c_base_f2t, c_base_f2t, "main"])
        print(f"[OBSERVE-BASE-FILEOBJ] base==head 均含 100644->tree (main): rc={got_same[0]} out={got_same[1].decode().strip()!r} err={got_same[2].decode().strip()!r}")

        # === 2. formal_math 存在性四象限（双方无 / 仅基线有 / 仅被审有 / 双方有） ===
        NO_FM_WITH_ANC = {
            b"rust/lib.rs": b"r\n",
            b"scripts/other.sh": b"o\n",
            b".github/workflows/ci.yml": b"c\n",
        }
        c_nofm_b = mk({}, parent=None, base_files=NO_FM_WITH_ANC)
        c_nofm_h = mk({b"rust/lib.rs": b"r2\n", b"scripts/other.sh": b"o2\n", b".github/workflows/ci.yml": b"c2\n"},
                      parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        for br in ("main", "feature/foo", "proof/x", "decl/x", "audit/x", "infra/x"):
            expect("NO-FM", f"双方无 formal_math，改 rust+other.sh+ci.yml ({br})",
                   run_pre(ns.precheck, [repo, c_nofm_b, c_nofm_h, br]), 0)

        # 双方无 formal_math 且原无 scripts/.github，新增/删光受管外兄弟文件（观察）
        NO_FM_NO_ANC = {b"rust/lib.rs": b"r\n"}
        c_bare_b = mk({}, parent=None, base_files=NO_FM_NO_ANC)
        c_bare_add_sc = mk({b"scripts/helper.sh": b"echo hi\n"}, parent=c_bare_b, base_files=NO_FM_NO_ANC)
        c_bare_add_ci = mk({b".github/workflows/ci.yml": b"name: ci\n"}, parent=c_bare_b, base_files=NO_FM_NO_ANC)
        c_del_last_sc = mk({b"scripts/other.sh": None}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        c_del_last_ci = mk({b".github/workflows/ci.yml": None}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        for tag, bc, hc in [
            ("无 scripts 时新增 scripts/helper.sh", c_bare_b, c_bare_add_sc),
            ("无 .github 时新增 .github/workflows/ci.yml", c_bare_b, c_bare_add_ci),
            ("删光仅有的非受信脚本 scripts/other.sh", c_nofm_b, c_del_last_sc),
            ("删光仅有的非受信工作流 ci.yml", c_nofm_b, c_del_last_ci),
        ]:
            for br in ("main", "proof/x", "infra/x"):
                g = run_pre(ns.precheck, [repo, bc, hc, br])
                print(f"[OBSERVE-ANC-APPEAR] {tag} ({br}): rc={g[0]} out={g[1].decode().strip()!r}")

        # 仅基线含 formal_math（被审整棵删掉）
        c_del_fm = commit_tree(repo, build_tree(repo, {k: v for k, v in BASE.items() if not k.startswith(FM)}), [base])
        expect("ONE-SIDE", "仅基线含 formal_math：proof 删光红", run_pre(ns.precheck, [repo, base, c_del_fm, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))
        expect("ONE-SIDE", "仅基线含 formal_math：main 删光红", run_pre(ns.precheck, [repo, base, c_del_fm, "main"]), 1, ("BRANCH_ROLE", "TRUSTED_DRIFT"))
        expect("ONE-SIDE", "仅基线含 formal_math：infra 放行删含内容文件的 formal_math 红",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, base, c_del_fm, "infra/x"]), 1, ("PATH_SCOPE",))
        c_infra_only_fm = mk({FM + b"lakefile.toml": b"x\n", FM + b"verification/run_gates.py": b"x\n"}, parent=None, base_files=NO_FM_WITH_ANC)
        c_infra_del_fm = commit_tree(repo, build_tree(repo, NO_FM_WITH_ANC), [c_infra_only_fm])
        expect("ONE-SIDE", "仅基线含 infra-only formal_math：infra 放行删光绿",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, c_infra_only_fm, c_infra_del_fm, "infra/x"]), 0)
        expect("ONE-SIDE", "仅基线含 infra-only formal_math：infra 无放行删光红",
               run_pre(ns.precheck, [repo, c_infra_only_fm, c_infra_del_fm, "infra/x"]), 1, ("TRUST_UNAPPROVED",))

        # 仅被审含 formal_math
        c_add_proof = mk({FM + b"Chan/Thm/B.lean": b"module\n"}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        c_add_infra = mk({FM + b"lakefile.toml": b"x\n", FM + b"verification/run_gates.py": b"x\n"}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        c_add_both = mk({FM + b"lakefile.toml": b"x\n", FM + b"Chan/Thm/B.lean": b"module\n"}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
        expect("ONE-SIDE", "仅被审含 formal_math：proof 仅加 Chan/Thm/B.lean 绿",
               run_pre(ns.precheck, [repo, c_nofm_b, c_add_proof, "proof/x"]), 0)
        expect("ONE-SIDE", "仅被审含 formal_math：infra 放行仅加受信文件绿",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, c_nofm_b, c_add_infra, "infra/x"]), 0)
        expect("ONE-SIDE", "仅被审含 formal_math：infra 无放行加受信文件红",
               run_pre(ns.precheck, [repo, c_nofm_b, c_add_infra, "infra/x"]), 1, ("TRUST_UNAPPROVED",))
        expect("ONE-SIDE", "仅被审含 formal_math：同加受信+内容（proof）红",
               run_pre(ns.precheck, [repo, c_nofm_b, c_add_both, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))
        expect("ONE-SIDE", "仅被审含 formal_math：同加受信+内容（infra 放行）红",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, c_nofm_b, c_add_both, "infra/x"]), 1, ("PATH_SCOPE",))

        # === 3. signature() 完备性：祖先保持 40000 时，受信文件每种变更均进改动集合 ===
        for path, sibling in [(b"scripts/fm_env.sh", b"scripts/other.sh"),
                              (b".github/workflows/formal-math.yml", b".github/workflows/ci.yml")]:
            pname = path.decode()
            # 3.1 改内容 + 同时改兄弟
            h_mod = mk({path: b"evil\n", sibling: b"sib2\n"})
            expect("SIG", f"{pname} 改内容+兄弟（proof）", run_pre(ns.precheck, [repo, base, h_mod, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))
            expect("SIG", f"{pname} 改内容+兄弟（infra 无放行）", run_pre(ns.precheck, [repo, base, h_mod, "infra/x"]), 1, ("TRUST_UNAPPROVED",))
            # 3.2 删除 + 兄弟留存（祖先仍是 40000）
            h_del = mk({path: None, sibling: b"sib2\n"})
            expect("SIG", f"{pname} 删除+兄弟留存（proof）", run_pre(ns.precheck, [repo, base, h_del, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))
            expect("SIG", f"{pname} 删除+兄弟留存（infra 无放行）", run_pre(ns.precheck, [repo, base, h_del, "infra/x"]), 1, ("TRUST_UNAPPROVED",))
            # 3.3 新增（基线仅有兄弟，祖先已是 40000）
            h_add = mk({path: b"new\n"}, parent=c_nofm_b, base_files=NO_FM_WITH_ANC)
            expect("SIG", f"{pname} 新增于已有 40000 祖先（proof）", run_pre(ns.precheck, [repo, c_nofm_b, h_add, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))
            expect("SIG", f"{pname} 新增于已有 40000 祖先（infra 无放行）", run_pre(ns.precheck, [repo, c_nofm_b, h_add, "infra/x"]), 1, ("TRUST_UNAPPROVED",))
            # 3.4 换类型（symlink / gitlink / directory / 100755）
            for ktag, val in [("120000", (b"120000", b"x")), ("160000", (b"160000", b"1" * 40)),
                              ("dir", {b"sub": b"x\n"}), ("100755", (b"100755", b"e\n"))]:
                h_t = mk({path: val})
                expect("SIG", f"{pname} 换为 {ktag}（proof）", run_pre(ns.precheck, [repo, base, h_t, "proof/x"]), 1, ("MODE", "PATH_SCOPE", "TRUSTED_DRIFT"))
                expect("SIG", f"{pname} 换为 {ktag}（infra 放行）", run_pre(ns.precheck, ["--trusted-change-approved", repo, base, h_t, "infra/x"]), 1, ("MODE",))

        # === 4. cat-file --batch-check 与 file_objects() 全面边界测试 ===
        # 4.1 协议直测（18 项）
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("precheck_bc", ns.precheck)
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        oid1, oid2 = b"a" * 40, b"b" * 40
        sent_payloads = []
        bc_cases = [
            ("空列表", [], b"", False),
            ("单 blob", [oid1], oid1 + b" blob 5\n", False),
            ("双对象去重排序", [oid2, oid1, oid1], oid1 + b" blob 1\n" + oid2 + b" tree 0\n", False),
            ("missing", [oid1], oid1 + b" missing\n", True),
            ("ambiguous", [oid1], oid1 + b" ambiguous\n", True),
            ("空输出但有请求", [oid1], b"", True),
            ("少一行", [oid1, oid2], oid1 + b" blob 1\n", True),
            ("多一行", [oid1], oid1 + b" blob 1\n" + oid2 + b" blob 1\n", True),
            ("顺序颠倒", [oid1, oid2], oid2 + b" blob 1\n" + oid1 + b" blob 1\n", True),
            ("缺尾换行", [oid1], oid1 + b" blob 1", True),
            ("尾随多余字节", [oid1], oid1 + b" blob 1\nX", True),
            ("尾随多余换行", [oid1], oid1 + b" blob 1\n\n", True),
            ("四字段", [oid1], oid1 + b" blob 1 extra\n", True),
            ("两字段", [oid1], oid1 + b" blob\n", True),
            ("负数大小", [oid1], oid1 + b" blob -1\n", True),
            ("非十进制大小", [oid1], oid1 + b" blob 0x10\n", True),
            ("OID 不符", [oid1], oid2 + b" blob 1\n", True),
            ("空大小", [oid1], oid1 + b" blob \n", True),
        ]
        bad_bc = []
        for cname, poids, payload, want_fault in bc_cases:
            def fake_git(repo_arg, *args, ok=(0,), data=b"", _p=payload):
                sent_payloads.append((args, data))
                return 0, _p
            pc.git = fake_git
            try:
                res = pc.objects(b"/fake", poids, body=False)
                got_fault = False
                if not want_fault and any(v[1] != b"" for v in res.values()):
                    bad_bc.append(cname + "(non-empty-body)")
            except pc.Fault:
                got_fault = True
            if got_fault != want_fault:
                bad_bc.append(cname)
        # 确认发送的是纯 OID + \n（无路径）
        oid_only_ok = all(
            args == (b"cat-file", b"--batch-check")
            and all(re.fullmatch(rb"[0-9a-f]{40}", ln) for ln in data.splitlines())
            for args, data in sent_payloads
        )
        checks.append(("BATCH-CHECK", "cat-file --batch-check 协议边界 18 项直测（确认纯 OID 请求）",
                       not bad_bc and oid_only_ok, 0 if (not bad_bc and oid_only_ok) else 1, [], [],
                       f"bad={bad_bc} oid_only={oid_only_ok}", ""))

        # 4.2 端到端 file_objects(): 100644 指向 tree / commit / tag / missing，涵盖各类受管位置
        for loc_tag, parent_path, fname, oid, br, app, exp_rc, req_r, req_f in [
            ("sources -> tree", FM + b"sources", b"evil.md", t_sub, "decl/x", False, 1, ("TREE_FORM",), ()),
            ("sources -> commit", FM + b"sources", b"evil.md", base.encode(), "decl/x", False, 1, ("TREE_FORM",), ()),
            ("sources -> tag", FM + b"sources", b"evil.md", tag_oid, "decl/x", False, 1, ("TREE_FORM",), ()),
            ("sources -> missing", FM + b"sources", b"evil.md", b"de" * 20, "decl/x", False, 2, (), ("GIT",)),
            ("Chan/Thm -> commit", FM + b"Chan/Thm", b"X.lean", base.encode(), "proof/x", False, 1, ("TREE_FORM",), ()),
            ("verification/auditor/lakefile.toml -> tree", FM + b"verification/auditor", b"lakefile.toml", t_sub, "infra/x", True, 1, ("TREE_FORM",), ()),
            ("scripts/fm_env.sh -> tree", b"scripts", b"fm_env.sh", t_sub, "infra/x", True, 1, ("TREE_FORM",), ()),
            ("formal-math.yml -> commit", b".github/workflows", b"formal-math.yml", base.encode(), "infra/x", True, 1, ("TREE_FORM",), ()),
        ]:
            t_dir = raw_entries(repo, [(b"100644", fname, oid)])
            h_f = mk({parent_path: (b"RAW_TREE", t_dir)})
            argv = (["--trusted-change-approved"] if app else []) + [repo, base, h_f, br]
            expect("FILE-OBJ", loc_tag, run_pre(ns.precheck, argv), exp_rc, req_red=req_r, req_fault=req_f)

        # 4.3 120000 symlink 指向 tree / missing；160000 / 160755 子模块指向不存在 OID；根上非受管子模块
        t_sym_tree = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (b"120000", b"L.lean", t_sub)])
        expect("FILE-OBJ", "120000 symlink 指向 tree -> MODE + TREE_FORM 退 1",
               run_pre(ns.precheck, [repo, base, mk({FM + b"Chan/Thm": (b"RAW_TREE", t_sym_tree)}), "proof/x"]),
               1, req_red=("MODE", "TREE_FORM"))
        t_sym_miss = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (b"120000", b"L.lean", b"ab" * 20)])
        expect("FILE-OBJ", "120000 symlink 指向缺失对象 -> 先报 MODE 再报 GIT 退 2",
               run_pre(ns.precheck, [repo, base, mk({FM + b"Chan/Thm": (b"RAW_TREE", t_sym_miss)}), "proof/x"]),
               2, req_red=("MODE",), req_fault=("GIT",))
        t_sub_160755 = raw_entries(repo, [(b"100644", b"B.lean", b_mod), (b"160755", b"Sub", b"cd" * 20)])
        expect("FILE-OBJ", "160755 子模块指向不存在 OID -> 跳过 batch-check，只报 MODE 退 1",
               run_pre(ns.precheck, [repo, base, mk({FM + b"Chan/Thm": (b"RAW_TREE", t_sub_160755)}), "proof/x"]),
               1, req_red=("MODE",))
        expect("FILE-OBJ", "根上非受管 160000 子模块指向不存在 OID -> 忽略退 0",
               run_pre(ns.precheck, [repo, base, mk({b"ext_sub": (b"160000", b"ef" * 20)}), "main"]), 0)

        # 4.4 大清单（2000 个不同对象名 + 1 个指向 tree 的文件）与损坏 zlib blob、怪文件名
        # 用 fast-import 批量写 2000 个独立 blob，避免重复起进程
        fi_stream = bytearray()
        for i in range(2000):
            payload = f"doc-{i}\n".encode()
            fi_stream += f"blob\nmark :{i + 1}\ndata {len(payload)}\n".encode() + payload + b"\n"
        marks_file = os.path.join(tmp, "marks.txt")
        git(repo, "fast-import", "--quiet", f"--export-marks={marks_file}", data=bytes(fi_stream))
        marks = {}
        for line in open(marks_file, "rb"):
            m, o = line.strip().split(b" ")
            marks[int(m[1:])] = o
        many_blobs = [marks[i + 1] for i in range(2000)]
        t_big_ok = mktree(repo, [(b"100644", b"blob", many_blobs[i], f"f{i:04d}.md".encode()) for i in range(2000)])
        h_big_ok = mk({FM + b"sources": (b"RAW_TREE", t_big_ok)})
        t_pre0 = time.monotonic()
        got_big_ok = run_pre(ns.precheck, [repo, base, h_big_ok, "decl/x"])
        dt_ok = time.monotonic() - t_pre0
        expect("LARGE", f"2000 个不同 blob 清单（耗时 {dt_ok:.2f}s）退 0", got_big_ok, 0)
        t_big_bad = raw_entries(repo, sorted(
            [(b"100644", f"f{i:04d}.md".encode(), many_blobs[i]) for i in range(1999)]
            + [(b"100644", b"f1999.md", t_sub)],
            key=lambda e: e[1],
        ))
        h_big_bad = mk({FM + b"sources": (b"RAW_TREE", t_big_bad)})
        expect("LARGE", "2000 文件中混入 1 个 100644->tree 退 1 TREE_FORM",
               run_pre(ns.precheck, [repo, base, h_big_bad, "decl/x"]), 1, req_red=("TREE_FORM",))

        # 含伪造 batch-check 输出行的文件名 -> 确认请求按纯 OID 发
        fake_name = b"a b\n" + t_sub + b" blob 0\n"
        t_weird_f = raw_entries(repo, [(b"100644", fake_name, t_sub), (b"100644", b"s.md", b_x)])
        expect("FILE-OBJ", "文件名含空格/换行/伪造 batch-check 头行且指向 tree -> PATH_GRAMMAR + TREE_FORM",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_weird_f)}), "decl/x"]),
               1, req_red=("PATH_GRAMMAR", "TREE_FORM"))

        # 损坏的 zlib blob 对象 -> cat-file --batch-check 失败退 2 GIT
        corrupt_b_repo = os.path.join(tmp, "corrupt_blob_repo")
        h_cb = mk({FM + b"sources/s.md": b"corrupt-blob-target\n"})
        shutil.copytree(repo, corrupt_b_repo)
        cb_oid = git(corrupt_b_repo, "rev-parse", f"{h_cb}:formal_math/sources/s.md").stdout.strip().decode()
        cb_path = os.path.join(corrupt_b_repo, ".git", "objects", cb_oid[:2], cb_oid[2:])
        os.chmod(cb_path, 0o600)
        with open(cb_path, "wb") as f:
            f.write(b"not-valid-zlib")
        expect("FILE-OBJ", "损坏的 zlib blob 对象在 batch-check 阶段退 2 GIT",
               run_pre(ns.precheck, [corrupt_b_repo, base, h_cb, "decl/x"]), 2, req_fault=("GIT",))

        # 4.5 SHA-256 仓库下 100644 指向 tree
        r256 = os.path.join(tmp, "r256")
        os.makedirs(r256)
        git(r256, "init", "-q", "--object-format=sha256")
        b256 = blob(r256, b"module\n")
        t256_sub = mktree(r256, [(b"100644", b"blob", b256, b"a")])
        c256_1 = commit_tree(r256, build_tree(r256, {FM + b"sources/s.md": b"s\n"}), msg="1")
        t256_src = raw_entries(r256, [(b"100644", b"evil.md", t256_sub), (b"100644", b"s.md", b256)])
        c256_2 = commit_tree(r256, mktree(r256, [(b"040000", b"tree", mktree(r256, [(b"040000", b"tree", t256_src, b"sources")]), b"formal_math")]), [c256_1])
        expect("SHA256", "SHA-256 100644 指向 tree 报 TREE_FORM 退 1",
               run_pre(ns.precheck, [r256, c256_1, c256_2, "decl/x"]), 1, req_red=("TREE_FORM",))

        # === 5. 真实仓库清理 17 处后各角色无误红验证 ===
        real_clone = os.path.join(tmp, "real_clone")
        git(tmp, "clone", "--shared", "--no-checkout", ns.real_repo, real_clone)
        head_real = "d6605824729f45015c6c3ff309c593c8292a38ad"
        if git(real_clone, "cat-file", "-e", f"{head_real}^{{commit}}", check=False).returncode != 0:
            head_real = git(real_clone, "rev-parse", "HEAD").stdout.strip().decode()
        # 枚举当前 17 处红项路径并由 infra 放行一次删除
        rc0, out0, err0 = run_pre(ns.precheck, ["--trusted-change-approved", real_clone, "594e49b5ec034461f9196c6cfb0c58fe017e8dc5", head_real, "infra/cleanup"])
        bad_paths = [l.split(b" ")[3] for l in out0.splitlines() if l.startswith(b"PRECHECK RED ")]
        expect("REAL", f"真实提交 594e..d660 恰报 17 处红项（实测 {len(bad_paths)}）", (rc0, out0, err0), 1,
               req_red=("LAKE_FILE", "PATH_GRAMMAR"), extra_ok=(len(bad_paths) == 17))
        # 用独立 index 删这 17 个文件造清理提交
        idx = os.path.join(tmp, "clean.idx")
        env_idx = dict(GENV, GIT_INDEX_FILE=idx)
        subprocess.run(["git", "-C", real_clone, "read-tree", head_real], env=env_idx, check=True)
        subprocess.run(["git", "-C", real_clone, "update-index", "--force-remove", "--"] + [p.decode() for p in bad_paths], env=env_idx, check=True)
        t_clean = subprocess.run(["git", "-C", real_clone, "write-tree"], env=env_idx, capture_output=True, check=True).stdout.strip()
        c_clean = commit_tree(real_clone, t_clean, [head_real], msg="cleanup-17")
        expect("REAL", "真实树：infra 放行清理 17 处退 0",
               run_pre(ns.precheck, ["--trusted-change-approved", real_clone, head_real, c_clean, "infra/cleanup"]), 0)
        expect("REAL", "真实树：infra 无放行清理 17 处退 1 TRUST_UNAPPROVED",
               run_pre(ns.precheck, [real_clone, head_real, c_clean, "infra/cleanup"]), 1, req_red=("TRUST_UNAPPROVED",))
        expect("REAL", "真实树：proof 清理 17 处退 1 PATH_SCOPE + TRUSTED_DRIFT",
               run_pre(ns.precheck, [real_clone, head_real, c_clean, "proof/cleanup"]), 1, req_red=("PATH_SCOPE", "TRUSTED_DRIFT"))

        # 在干净真实树上逐一验证四角色与受管外改动的无误红
        def add_on_clean(relpath, content):
            idx2 = os.path.join(tmp, f"idx_{relpath.replace('/', '_')}.idx")
            e2 = dict(GENV, GIT_INDEX_FILE=idx2)
            subprocess.run(["git", "-C", real_clone, "read-tree", c_clean], env=e2, check=True)
            bo = blob(real_clone, content)
            subprocess.run(["git", "-C", real_clone, "update-index", "--add", "--cacheinfo", f"100644,{bo.decode()},{relpath}"], env=e2, check=True)
            t2 = subprocess.run(["git", "-C", real_clone, "write-tree"], env=e2, capture_output=True, check=True).stdout.strip()
            return commit_tree(real_clone, t2, [c_clean], msg=relpath)

        for label, relp, br, app in [
            ("干净真实树：decl 改 Chan/Defs/NewDef.lean", "formal_math/Chan/Defs/NewDef.lean", "decl/new-def", False),
            ("干净真实树：decl 改 sources/note.md", "formal_math/sources/note.md", "decl/note", False),
            ("干净真实树：proof 改 Chan/Thm/NewThm.lean", "formal_math/Chan/Thm/NewThm.lean", "proof/new-thm", False),
            ("干净真实树：proof 改 ChanTest/T.lean", "formal_math/ChanTest/T.lean", "proof/test", False),
            ("干净真实树：audit 改 Chan/Audit/Cases/C1.lean", "formal_math/Chan/Audit/Cases/C1.lean", "audit/case1", False),
            ("干净真实树：infra 无放行改 formal_math/README.md", "formal_math/README.md", "infra/doc", False),
            ("干净真实树：infra 放行改 formal_math/lakefile.toml", "formal_math/lakefile.toml", "infra/cfg", True),
            ("干净真实树：infra 放行新增 .github/workflows/formal-math.yml", ".github/workflows/formal-math.yml", "infra/wf", True),
            ("干净真实树：main 仅改 rust/lib.rs", "rust/src/dummy_r3.rs", "main", False),
            ("干净真实树：proof 仅改 .github/workflows/ci.yml", ".github/workflows/ci.yml", "proof/x", False),
            ("干净真实树：decl 仅改 scripts/other_r3.sh", "scripts/other_r3.sh", "decl/x", False),
        ]:
            hc = add_on_clean(relp, b"ok\n")
            argv = (["--trusted-change-approved"] if app else []) + [real_clone, c_clean, hc, br]
            expect("REAL", label, run_pre(ns.precheck, argv), 0)

        # === 6. 退出码与输出契约再核（关闭 fd 2、断管等） ===
        got_no_stderr = subprocess.run(
            [sys.executable, "-I", ns.precheck, repo, base, mk({FM + b"Chan/Thm/B.lean": b"ok\n"}), "proof/x"],
            env=RUN_ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            preexec_fn=lambda: os.close(2),
        )
        expect("IO", "关闭 stderr 绿例仍退 0", (got_no_stderr.returncode, got_no_stderr.stdout, b""), 0)
        got_fault_no_stderr = subprocess.run(
            [sys.executable, "-I", ns.precheck, repo, "bad-rev", base, "proof/x"],
            env=RUN_ENV, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            preexec_fn=lambda: os.close(2),
        )
        expect("IO", "关闭 stderr 故障例仍退 2", (got_fault_no_stderr.returncode, got_fault_no_stderr.stdout, b""), 2)

        failed = 0
        for sec, label, ok, rc, rcs, fcs, out, err in checks:
            if not ok:
                failed += 1
            print(f"[{'PASS' if ok else 'FAIL'}] [{sec}] {label} (rc={rc}, red={rcs}, fault={fcs})")
            if not ok:
                print(f"    out: {out}\n    err: {err}")
        print(f"R3 PROBES SUMMARY: {len(checks)} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
