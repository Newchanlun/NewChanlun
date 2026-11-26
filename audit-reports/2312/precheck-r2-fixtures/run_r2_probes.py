#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R2：原始树解析、排序、受管边界、Lake 例外、交接、无误红与退出码探针集。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r2_probes.py
"""
import argparse
import importlib.util
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


def parse_tree(repo, tree_oid):
    raw = git(repo, "cat-file", "tree", tree_oid.decode()).stdout
    out, pos = [], 0
    while pos < len(raw):
        sp = raw.index(b" ", pos)
        nul = raw.index(b"\0", sp)
        out.append((raw[pos:sp], raw[sp + 1:nul], raw[nul + 1:nul + 21].hex().encode()))
        pos = nul + 21
    return out


def run_pre(precheck, args, env=RUN_ENV, py=(), **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    p = subprocess.run([sys.executable, "-I", *py, precheck, *args], env=env, **kw)
    return p.returncode, p.stdout, p.stderr


def codes(out, err):
    return sorted({c.decode() for k, c in LINE_RE.findall(out + err) if k != b"GREEN"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", default=DEFAULT_PRECHECK)
    ns = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="precheck-r2-probes-")
    FM = b"formal_math/"
    checks = []

    def expect(sec, label, got, exp_rc, req_codes=()):
        rc, out, err = got
        cs = codes(out, err)
        ok = rc == exp_rc and all(c in cs for c in req_codes)
        checks.append((sec, label, ok, rc, cs, out.decode("utf-8", "replace").strip(), err.decode("utf-8", "replace").strip()))

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
        b20 = bytes.fromhex(b_mod.decode())
        t_empty = mktree(repo, [])
        root_ents = parse_tree(repo, t_base)
        fm_oid = dict((n, o) for _, n, o in root_ents)[b"formal_math"]
        fm_ents = parse_tree(repo, fm_oid)

        def mk(edits, parent=base):
            f = dict(BASE)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            return commit_tree(repo, build_tree(repo, f), [parent], msg="c")

        def replace_root(fn):
            return raw_entries(repo, fn(list(root_ents)))

        def with_raw_fm(body):
            t_bad = raw_tree(repo, body)
            return commit_tree(repo, replace_root(lambda es: [(m, n, t_bad if n == b"formal_math" else o) for m, n, o in es]), [base])

        # 1. 原始树解析健壮性
        chan_oid_b = bytes.fromhex(dict((n, o) for _, n, o in fm_ents)[b"Chan"].decode())
        for label, raw_b, req in [
            ("空条目名", b"100644 \0" + b20, ("TREE_FORM",)),
            ("哈希截断 19B", b"100644 README.md\0" + b20[:19], ("TREE_FORM",)),
            ("NUL 后 0 字节", b"100644 README.md\0", ("TREE_FORM",)),
            ("尾随 1 字节垃圾", b"100644 README.md\0" + b20 + b"X", ("TREE_FORM",)),
            ("七位模式 0100644", b"0100644 README.md\0" + b20, ("TREE_FORM",)),
            ("七位模式 0040000", b"0040000 Chan\0" + chan_oid_b, ("TREE_FORM",)),
            ("非八进制模式 100684", b"100684 README.md\0" + b20, ("TREE_FORM",)),
            ("非八进制模式 10064a", b"10064a README.md\0" + b20, ("TREE_FORM",)),
            ("空模式字段", b" README.md\0" + b20, ("TREE_FORM",)),
            ("模式 0", b"0 README.md\0" + b20, ("MODE",)),
            ("模式 240000 目录位", b"240000 Chan\0" + chan_oid_b, ("MODE",)),
            ("条目名含 /", b"100644 a/b\0" + b20, ("TREE_FORM",)),
        ]:
            expect("PARSE", label, run_pre(ns.precheck, [repo, base, with_raw_fm(raw_b), "proof/x"]), 1, req)

        tag_oid = git(repo, "mktag", data=f"object {base}\ntype commit\ntag v0\ntagger r <r@r> 0 +0000\n\nt\n".encode()).stdout.strip()
        for label, oid_b, exp_rc, req in [
            ("目录指向 commit", base.encode(), 1, ("TREE_FORM",)),
            ("目录指向 tag", tag_oid, 1, ("TREE_FORM",)),
            ("目录指向缺失对象", b"deadbeef" * 5, 2, ("GIT",)),
            ("目录指向全零 OID", b"0" * 40, 2, ("GIT",)),
        ]:
            t_d = raw_entries(repo, [(b"40000", b"Bad", oid_b)])
            h_d = commit_tree(repo, replace_root(lambda es: [(m, n, t_d if n == b"formal_math" else o) for m, n, o in es]), [base])
            expect("PARSE", label, run_pre(ns.precheck, [repo, base, h_d, "proof/x"]), exp_rc, req)

        # cat-file 头行伪造 + 根树怪名（空格、\n、高位字节、10KB 名）
        weird_root = sorted(root_ents + [
            (b"100644", b" leading_space", b_mod),
            (b"100644", b"\n", b_mod),
            (b"100644", b"zz\n" + fm_oid + b" tree 0\n", b_mod),
            (b"100644", b"formal_math\x80", b_mod),
            (b"100644", b"formal_math\xff", b_mod),
            (b"100644", b"z" * 10000, b_mod),
        ], key=lambda e: e[1] + b"/" if e[0] == b"40000" else e[1])
        expect("PARSE", "根树非受管怪名（前导空格/换行/伪造 cat-file 头/0x80/0xff/10KB）",
               run_pre(ns.precheck, [repo, base, commit_tree(repo, raw_entries(repo, weird_root), [base]), "main"]), 0)
        expect("PARSE", "5000 字符合法模块名",
               run_pre(ns.precheck, [repo, base, mk({FM + b"Chan/Thm/" + b"A" * 5000 + b".lean": b"module\n"}), "proof/x"]), 0)

        # 损坏的 zlib 子树对象
        corrupt_r = os.path.join(tmp, "corrupt_zlib")
        h_c = mk({FM + b"Chan/Thm/B.lean": b"corrupt_target\n"})
        shutil.copytree(repo, corrupt_r)
        thm_oid = git(corrupt_r, "rev-parse", f"{h_c}:formal_math/Chan/Thm").stdout.strip().decode()
        p_obj = os.path.join(corrupt_r, ".git", "objects", thm_oid[:2], thm_oid[2:])
        os.chmod(p_obj, 0o600)
        with open(p_obj, "wb") as f:
            f.write(b"not-valid-zlib")
        expect("PARSE", "损坏的 zlib 子树对象退 2 GIT", run_pre(ns.precheck, [corrupt_r, base, h_c, "proof/x"]), 2, ("GIT",))

        # 2. git 排序规则精确性 + BASE_FORM 绝不退 0
        pref_root = mktree(repo, [
            (b"160000", b"commit", base.encode(), b"foo"),
            (b"100644", b"blob", b_mod, b"foo-a"),
            (b"100644", b"blob", b_mod, b"foo.a"),
            (b"040000", b"tree", t_empty, b"foo_a"),
            (b"040000", b"tree", t_empty, b"a.d"),
            (b"040000", b"tree", t_empty, b"a"),
            (b"100644", b"blob", b_mod, b"a-file"),
            (b"100644", b"blob", b_mod, b"a.file"),
            (b"100644", b"blob", b_mod, b"a_file"),
        ] + [(b"040000" if m == b"40000" else m, b"tree" if m == b"40000" else b"blob", o, n) for m, n, o in root_ents])
        expect("SORT", "根树合法前缀混排（含 160000 子模块与同名文件/目录）",
               run_pre(ns.precheck, [repo, base, commit_tree(repo, pref_root, [base]), "main"]), 0)
        expect("SORT", "sources 合法前缀混排（p-1/p.1/p.d/p/p0/p_1）",
               run_pre(ns.precheck, [repo, base, mk({
                   FM + b"sources/p-1": b"1", FM + b"sources/p.1": b"2", FM + b"sources/p.d/x": b"3",
                   FM + b"sources/p/x": b"4", FM + b"sources/p0": b"5", FM + b"sources/p_1": b"6",
               }), "decl/x"]), 0)
        t_ord1 = raw_entries(repo, [(b"40000", b"p", mktree(repo, [(b"100644", b"blob", b_mod, b"x")])),
                                    (b"100644", b"p.1", b_mod), (b"100644", b"s.md", b_mod)])
        t_ord2 = raw_entries(repo, [(b"100644", b"p_1", b_mod),
                                    (b"40000", b"p", mktree(repo, [(b"100644", b"blob", b_mod, b"x")])),
                                    (b"100644", b"s.md", b_mod)])
        expect("SORT", "乱序：目录 p/ 在文件 p.1 前", run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_ord1)}), "decl/x"]), 1, ("TREE_FORM",))
        expect("SORT", "乱序：文件 p_1 在目录 p/ 前", run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_ord2)}), "decl/x"]), 1, ("TREE_FORM",))
        c_bad_base = mk({FM + b"sources": (b"RAW_TREE", t_ord1)})
        expect("SORT", "BASE_FORM + 规范被审退 2", run_pre(ns.precheck, [repo, c_bad_base, commit_tree(repo, t_base, [c_bad_base]), "proof/x"]), 2, ("BASE_FORM",))
        expect("SORT", "BASE_FORM + 应红被审退 2（不退 0）",
               run_pre(ns.precheck, [repo, c_bad_base, mk({FM + b"lakefile.toml": b"hack\n"}, parent=c_bad_base), "proof/x"]), 2, ("BASE_FORM",))
        expect("SORT", "BASE_FORM + base==head 退 2（不退 0）", run_pre(ns.precheck, [repo, c_bad_base, c_bad_base, "main"]), 2, ("BASE_FORM",))

        # 3. SHA-256 仓库
        r256 = os.path.join(tmp, "r256")
        os.makedirs(r256)
        git(r256, "init", "-q", "--object-format=sha256")
        b256 = blob(r256, b"module\n")
        c256_1 = commit_tree(r256, build_tree(r256, {FM + b"Chan/Thm/B.lean": b"module\n", b"scripts/fm_env.sh": b"e\n"}), msg="1")
        c256_2 = commit_tree(r256, build_tree(r256, {FM + b"Chan/Thm/B.lean": b"changed\n", b"scripts/fm_env.sh": b"e\n"}), [c256_1], msg="2")
        expect("SHA256", "SHA-256 正常绿", run_pre(ns.precheck, [r256, c256_1, c256_2, "proof/x"]), 0)
        expect("SHA256", "SHA-256 跨角色红", run_pre(ns.precheck, [r256, c256_1, c256_2, "decl/x"]), 1, ("PATH_SCOPE",))
        t256_664 = raw_entries(r256, [(b"100664", b"B.lean", b256)])
        c256_664 = commit_tree(r256, mktree(r256, [
            (b"040000", b"tree", mktree(r256, [(b"040000", b"tree", mktree(r256, [(b"040000", b"tree", t256_664, b"Thm")]), b"Chan")]), b"formal_math"),
            (b"040000", b"tree", mktree(r256, [(b"100644", b"blob", blob(r256, b"e\n"), b"fm_env.sh")]), b"scripts"),
        ]), [c256_1])
        expect("SHA256", "SHA-256 原始模式 100664 红", run_pre(ns.precheck, [r256, c256_1, c256_664, "proof/x"]), 1, ("MODE",))
        t256_tr = raw_tree(r256, b"100644 B.lean\0" + bytes.fromhex(b256.decode())[:20])
        c256_tr = commit_tree(r256, mktree(r256, [
            (b"040000", b"tree", mktree(r256, [(b"040000", b"tree", mktree(r256, [(b"040000", b"tree", t256_tr, b"Thm")]), b"Chan")]), b"formal_math"),
        ]), [c256_1])
        expect("SHA256", "SHA-256 截断 20B 条目报 TREE_FORM", run_pre(ns.precheck, [r256, c256_1, c256_tr, "proof/x"]), 1, ("TREE_FORM",))

        # 4. LAKE_FILE 绕过试探 + 交接评估样本（100644 -> tree）
        expect("LAKE", "Unicode 同形字 lаkefile.lean 被 PATH_GRAMMAR 拒",
               run_pre(ns.precheck, [repo, base, mk({FM + "Chan/Thm/l\u0430kefile.lean".encode(): b"x\n"}), "proof/x"]), 1, ("PATH_GRAMMAR",))
        expect("LAKE", "尾点 lakefile.lean. 被 PATH_GRAMMAR 拒",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources/lakefile.lean.": b"x\n"}), "decl/x"]), 1, ("PATH_GRAMMAR",))
        expect("LAKE", "尾空格 lakefile.lean  被 PATH_GRAMMAR 拒",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources/lakefile.lean ": b"x\n"}), "decl/x"]), 1, ("PATH_GRAMMAR",))
        expect("LAKE-NOTE", "verification/auditor/lakefile.toml 作目录（infra 放行）实测退 0（建议收紧）",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, base, mk({FM + b"verification/auditor/lakefile.toml/a.py": b"x\n"}), "infra/x"]), 0)
        t_src_ff = raw_entries(repo, [(b"100644", b"evil.md", fm_oid), (b"100644", b"s.md", b_mod)])
        expect("HANDOFF", "100644 sources/evil.md 指向 tree 对象退 0（取料片需注意非代码文件）",
               run_pre(ns.precheck, [repo, base, mk({FM + b"sources": (b"RAW_TREE", t_src_ff)}), "decl/x"]), 0)

        # 5. 无误红（全角色、带点/连字符/下划线、.gitignore 清理、git replace 树对象、宿主 GIT_* 隔离）
        expect("VALID", "合法文件名含点/连字符/下划线（README.md/v1.2-notes.md/_private/__init__.py/foo_.md）",
               run_pre(ns.precheck, [repo, base, mk({
                   FM + b"sources/README.md": b"1", FM + b"sources/v1.2-notes.md": b"2",
                   FM + b"sources/_private.md": b"3", FM + b"sources/__init__.py": b"4",
                   FM + b"sources/foo_.md": b"5", FM + b"sources/foo._bar": b"6",
                   FM + b"sources/foo-_bar": b"7", FM + b"blueprint/a_1/b-2/c.3/doc.tex": b"8",
               }), "decl/x"]), 0)
        c_gi_base = mk({FM + b".gitignore": b"/.lake\n"})
        c_gi_del = commit_tree(repo, t_base, [c_gi_base], msg="del-gi")
        expect("VALID", "infra 获放行删除 formal_math/.gitignore 绿",
               run_pre(ns.precheck, ["--trusted-change-approved", repo, c_gi_base, c_gi_del, "infra/x"]), 0)

        # git replace 替换树对象被屏蔽
        repl_r = os.path.join(tmp, "repl_tree")
        h_hack = mk({FM + b"lakefile.toml": b"hack\n"})
        shutil.copytree(repo, repl_r)
        git(repl_r, "replace",
            git(repl_r, "rev-parse", f"{h_hack}:formal_math").stdout.strip().decode(),
            git(repl_r, "rev-parse", f"{base}:formal_math").stdout.strip().decode())
        expect("ISOLATE", "git replace 替换树对象被屏蔽", run_pre(ns.precheck, [repl_r, base, h_hack, "proof/x"]), 1, ("PATH_SCOPE", "TRUSTED_DRIFT"))

        # 宿主 GIT_DIR / GIT_CONFIG_PARAMETERS 被清零
        other_r = os.path.join(tmp, "other_repo")
        os.makedirs(other_r)
        git(other_r, "init", "-q")
        h_ok = mk({FM + b"Chan/Thm/B.lean": b"ok\n"})
        expect("ISOLATE", "宿主 GIT_DIR/GIT_CONFIG_PARAMETERS 被屏蔽",
               run_pre(ns.precheck, [repo, base, h_ok, "proof/x"],
                       env=dict(RUN_ENV, GIT_DIR=os.path.join(other_r, ".git"), GIT_CONFIG_PARAMETERS="'core.bare=true'")), 0)

        # 6. CLI 22 项 + 非 UTF-8 分支 + stderr 关闭/断管
        h_rust = mk({b"rust/lib.rs": b"new\n"})
        ascii_env = {"PATH": RUN_ENV["PATH"], "LC_ALL": "C"}
        expect("IO", "非 UTF-8 分支无受管改动（ASCII 环境）退 0",
               run_pre(ns.precheck, [os.fsencode(repo), base.encode(), h_rust.encode(), b"feat/\xff\xfe"], env=ascii_env, py=("-X", "utf8=0")), 0)
        expect("IO", "非 UTF-8 分支改受管路径（ASCII 环境）报 BRANCH_ROLE",
               run_pre(ns.precheck, [os.fsencode(repo), base.encode(), h_ok.encode(), b"feat/\xff\xfe"], env=ascii_env, py=("-X", "utf8=0")), 1, ("BRANCH_ROLE",))
        cli_cases = [
            [], [repo], [repo, base], [repo, base, h_ok], [repo, base, h_ok, "proof/x", "extra"],
            ["--trusted-change-approved"], ["--trusted-change-approved", repo, base, h_ok],
            ["--trusted-change-approved", repo, base, h_ok, "infra/x", "extra"],
            ["--trusted-change-approved", "--trusted-change-approved", repo, base, h_ok, "infra/x"],
            ["--", repo, base, h_ok, "proof/x"], ["--help"], ["-h"],
            ["--unknown", repo, base, h_ok, "proof/x"],
            ["--trusted-change-approved=true", repo, base, h_ok, "infra/x"],
            ["--trusted", repo, base, h_ok, "infra/x"],
            ["-repo", base, h_ok, "proof/x"], [repo, "-base", h_ok, "proof/x"],
            [repo, base, "-head", "proof/x"], [repo, base, h_ok, "-branch"],
            ["", base, h_ok, "proof/x"], [repo, "", h_ok, "proof/x"], [repo, base, "", "proof/x"],
        ]
        bad_cli = [a for a in cli_cases if (lambda r: r[0] != 2 or b"PRECHECK FAULT USAGE " not in r[2])(run_pre(ns.precheck, a))]
        checks.append(("CLI", "CLI 22 项参数矩阵全退 2 USAGE", not bad_cli, 0 if not bad_cli else 1, [], f"bad={bad_cli}", ""))

        # 7. cat-file --batch 协议边界直测（objects() 16 项边界）
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("precheck_proto", ns.precheck)
        pc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pc)
        oid1, oid2 = b"a" * 40, b"b" * 40
        proto_cases = [
            ("合法空树", [oid1], oid1 + b" tree 0\n\n", False),
            ("合法双对象", [oid1, oid2], oid1 + b" tree 3\nabc\n" + oid2 + b" blob 0\n\n", False),
            ("missing", [oid1], oid1 + b" missing\n", True),
            ("ambiguous", [oid1], oid1 + b" ambiguous\n", True),
            ("空输出", [oid1], b"", True),
            ("头行缺换行", [oid1], oid1 + b" tree 0", True),
            ("头行 OID 不符", [oid1], oid2 + b" tree 0\n\n", True),
            ("负数长度", [oid1], oid1 + b" tree -1\n\n", True),
            ("非十进制长度", [oid1], oid1 + b" tree 0x1\n\n", True),
            ("头行四字段", [oid1], oid1 + b" tree 0 extra\n\n", True),
            ("长度越界", [oid1], oid1 + b" tree 5\nabc\n", True),
            ("正文后缺换行", [oid1], oid1 + b" tree 3\nabcX", True),
            ("正文后 EOF", [oid1], oid1 + b" tree 3\nabc", True),
            ("尾随多余字节", [oid1], oid1 + b" tree 0\n\nEXTRA", True),
            ("尾随多余换行", [oid1], oid1 + b" tree 0\n\n\n", True),
            ("正文含伪造头行", [oid1], oid1 + b" tree 48\n" + oid2 + b" tree 0\n\n", False),
        ]
        bad_proto = []
        for pname, poids, payload, want_fault in proto_cases:
            pc.git = lambda repo, *args, ok=(0,), data=b"", _p=payload: (0, _p)
            try:
                pc.objects(b"/fake", poids)
                got_fault = False
            except pc.Fault:
                got_fault = True
            if got_fault != want_fault:
                bad_proto.append(pname)
        checks.append(("PROTO", "cat-file --batch 协议边界 16 项直测", not bad_proto, 0 if not bad_proto else 1, [], f"bad={bad_proto}", ""))

        failed = 0
        for sec, label, ok, rc, cs, out, err in checks:
            if not ok:
                failed += 1
            print(f"[{'PASS' if ok else 'FAIL'}] [{sec}] {label} (rc={rc}, codes={cs})")
            if not ok:
                print(f"    out: {out}\n    err: {err}")
        print(f"R2 PROBES SUMMARY: {len(checks)} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
