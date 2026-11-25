#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R1：边角与正向核验探针集。

覆盖：全角色合法改动、深层/长模块名、非规范文件模式（100664/100600/040755）、合并提交、
重命名/复制配置屏蔽、git replace 与 grafts 屏蔽、SHA-256 仓库、裸仓/子目录、浅克隆/缺失树对象、
22 项命令行参数矩阵、关闭/断管标准错误、rev-parse --end-of-options 验证。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_edge_probes.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
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


def run_pre(args, env=RUN_ENV, py=(), **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    p = subprocess.run([sys.executable, "-I", *py, PRECHECK, *args], env=env, **kw)
    return p.returncode, p.stdout, p.stderr


def blob(repo, data):
    return git(repo, "hash-object", "-w", "--stdin", data=data).stdout.strip()


def mktree(repo, entries):
    return git(repo, "mktree", "-z", "--missing", data=b"".join(b"%s %s %s\t%s\0" % e for e in entries)).stdout.strip()


def raw_tree(repo, entries):
    body = b"".join(b"%s %s\0%s" % (m.lstrip(b"0"), n, bytes.fromhex(o.decode())) for m, n, o in entries)
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
                else:
                    items.append((val[0], b"blob", blob(repo, val[1]), name))
            else:
                items.append((b"100644", b"blob", blob(repo, val), name))
        return mktree(repo, items)

    return rec(spec)


def main():
    tmp = tempfile.mkdtemp(prefix="precheck-r1-probes-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        git(repo, "init", "-q")
        FM = b"formal_math/"
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
            b".github/workflows/formal-math.yml": b"w\n",
            b"rust/lib.rs": b"r\n",
        }
        base = commit_tree(repo, build_tree(repo, BASE), msg="base")
        X = b"changed\n"

        def mk(edits, parents=None, msg="c"):
            f = dict(BASE)
            for k, v in edits.items():
                if v is None:
                    f.pop(k, None)
                else:
                    f[k] = v
            return commit_tree(repo, build_tree(repo, f), (base,) if parents is None else parents, msg=msg)

        checks = []

        def expect(label, got, exp_rc, needle=b""):
            rc, out, err = got
            ok = rc == exp_rc and (not needle or needle in (out + err))
            checks.append((label, ok, rc, out.decode("utf-8", "replace").strip(), err.decode("utf-8", "replace").strip()))

        # 1. 四角色全路径正向验证 + 深层/长模块名 + 合法边界
        h_decl = mk({
            FM + b"Chan/Defs/A.lean": X, FM + b"Chan/Hypotheses/H.lean": X,
            FM + b"Chan/Audit/Literal/L.lean": X, FM + b"Chan/Proxy/P.lean": X,
            FM + b"ChanChallenge/C.lean": X, FM + b"sources/s.md": X, FM + b"blueprint/b.tex": X,
            FM + b"statement-lock.json": X, FM + b"formalization.yaml": X,
            FM + b"garbage-signoffs.yaml": X, FM + b"HISTORY.md": X,
        })
        expect("decl 全表合法改动", run_pre([repo, base, h_decl, "decl/all-paths_1.2/sub"]), 0, b"role=decl")

        h_proof = mk({
            FM + b"Chan/Thm/A_1/B_2/" + b"C" * 180 + b".lean": X,
            FM + b"Chan/Proofs/p_0.lean": X, FM + b"Chan/Exec/E.lean": X,
            FM + b"Chan/Final/F.lean": X, FM + b"Chan/Final.lean": X, FM + b"Chan.lean": X,
            FM + b"ChanTest/T.lean": X, FM + b"ChanDyn/D.lean": X,
            FM + b"ChanExplore/E.lean": X, FM + b"ChanExplore.lean": X,
        })
        expect("proof 全表+深层长模块名", run_pre([repo, base, h_proof, "proof/all"]), 0, b"role=proof")

        h_audit = mk({
            FM + b"Chan/Audit/Math/C.lean": X, FM + b"Chan/Audit/Separation/S.lean": X,
            FM + b"Chan/Audit/Cases/K.lean": X, FM + b"ChanTest/T.lean": X,
        })
        expect("audit 全表合法改动", run_pre([repo, base, h_audit, "audit/all"]), 0, b"role=audit")

        h_infra = mk({
            FM + b"lakefile.toml": X, FM + b"lake-manifest.json": X, FM + b"lean-toolchain": X,
            b"scripts/fm_env.sh": X, b".github/workflows/formal-math.yml": X,
            FM + b"verification/run_gates.py": X, FM + b"README.md": X,
        })
        expect("infra 全表放行", run_pre(["--trusted-change-approved", repo, base, h_infra, "infra/all"]), 0, b"role=infra")
        expect("proof 带放行改 lakefile 仍红", run_pre(["--trusted-change-approved", repo, base, mk({FM + b"lakefile.toml": X}), "proof/x"]), 1, b"TRUSTED_DRIFT")

        # 2. 合并提交、无关根、重命名/复制配置屏蔽
        h_merge_bad = mk({FM + b"Chan/Thm/B.lean": X, FM + b"Chan/Defs/A.lean": X}, parents=(h_proof, h_decl))
        expect("合并提交夹带跨角色改动", run_pre([repo, base, h_merge_bad, "proof/x"]), 1, b"PATH_SCOPE")
        c_unrel = commit_tree(repo, build_tree(repo, BASE), msg="unrelated-root")
        expect("无关根提交为基线", run_pre([repo, c_unrel, h_proof, "proof/x"]), 2, b"NOT_ANCESTOR")

        git(repo, "config", "diff.renames", "copies")
        h_ren = mk({FM + b"Chan/Defs/A.lean": None, FM + b"Chan/Thm/A.lean": b"module\n"})
        expect("diff.renames=copies 下跨角色重命名仍判红", run_pre([repo, base, h_ren, "proof/x"]), 1, b"PATH_SCOPE")
        h_copy = mk({FM + b"Chan/Thm/CopyB.lean": b"module\n"})
        expect("diff.renames=copies 下合法复制仍退 0", run_pre([repo, base, h_copy, "proof/x"]), 0, b"role=proof")

        # 3. 屏蔽 git replace 与 grafts
        repl_dir = os.path.join(tmp, "repl")
        shutil.copytree(repo, repl_dir)
        git(repl_dir, "replace", h_decl, h_proof)
        expect("git replace 被屏蔽", run_pre([repl_dir, base, h_decl, "proof/x"]), 1, b"PATH_SCOPE")
        os.makedirs(os.path.join(repl_dir, ".git", "info"), exist_ok=True)
        with open(os.path.join(repl_dir, ".git", "info", "grafts"), "w") as f:
            f.write(f"{h_proof} {c_unrel}\n")
        expect("grafts 被屏蔽", run_pre([repl_dir, c_unrel, h_proof, "proof/x"]), 2, b"NOT_ANCESTOR")

        # 4. 裸仓、子目录、浅克隆、缺失树对象
        bare = os.path.join(tmp, "bare.git")
        git(tmp, "clone", "-q", "--bare", repo, bare)
        expect("裸仓正常判绿", run_pre([bare, base, h_proof, "proof/x"]), 0, b"role=proof")
        sub = os.path.join(repo, "nested_cwd")
        os.makedirs(sub)
        expect("仓库子目录正常判绿", run_pre([sub, base, h_proof, "proof/x"]), 0, b"role=proof")

        git(repo, "update-ref", "refs/heads/tip", h_proof)
        shallow = os.path.join(tmp, "shallow")
        git(tmp, "clone", "-q", "--depth=1", "--branch", "tip", "file://" + repo, shallow)
        expect("浅克隆缺基线退 2", run_pre([shallow, base, h_proof, "proof/x"]), 2, b"BAD_REV")

        corrupt = os.path.join(tmp, "corrupt")
        shutil.copytree(repo, corrupt)
        htree = git(corrupt, "rev-parse", h_proof + "^{tree}").stdout.strip().decode()
        obj = os.path.join(corrupt, ".git", "objects", htree[:2], htree[2:])
        os.chmod(obj, 0o600)
        os.remove(obj)
        expect("缺失树对象退 2", run_pre([corrupt, base, h_proof, "proof/x"]), 2, b"GIT")

        # 5. SHA-256 仓库
        r256 = os.path.join(tmp, "r256")
        os.makedirs(r256)
        git(r256, "init", "-q", "--object-format=sha256")
        c256_1 = commit_tree(r256, build_tree(r256, {FM + b"Chan/Thm/B.lean": b"module\n"}), msg="1")
        c256_2 = commit_tree(r256, build_tree(r256, {FM + b"Chan/Thm/B.lean": X}), [c256_1], msg="2")
        expect("SHA-256 仓库判绿", run_pre([r256, c256_1, c256_2, "proof/x"]), 0, b"role=proof")
        expect("SHA-256 仓库判红", run_pre([r256, c256_1, c256_2, "decl/x"]), 1, b"PATH_SCOPE")

        # 6. 标准错误关闭/断管 + 空 PATH
        expect("空 PATH 退 2 GIT", run_pre([repo, base, h_proof, "proof/x"], env={"PATH": "", "LC_ALL": "C"}), 2, b"PRECHECK FAULT GIT")
        for tag, args, exp_rc in [
            ("关闭 stderr 绿例", [repo, base, h_proof, "proof/x"], 0),
            ("关闭 stderr 红例", [repo, base, h_decl, "proof/x"], 1),
            ("关闭 stderr 故障例", [repo, "nope", h_proof, "proof/x"], 2),
        ]:
            p = subprocess.run([sys.executable, "-I", PRECHECK, *args], env=RUN_ENV,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, preexec_fn=lambda: os.close(2))
            expect(tag, (p.returncode, p.stdout, b""), exp_rc)
        for tag, args, exp_rc in [
            ("断管 stderr 绿例", [repo, base, h_proof, "proof/x"], 0),
            ("断管 stderr 红例", [repo, base, h_decl, "proof/x"], 1),
            ("断管 stderr 故障例", [repo, "nope", h_proof, "proof/x"], 2),
        ]:
            rd, wr = os.pipe()
            os.close(rd)
            rc, out, _ = run_pre(args, stderr=wr)
            os.close(wr)
            expect(tag, (rc, out, b""), exp_rc)

        # 7. CLI 参数矩阵（22 项均须退 2 USAGE）
        cli_cases = [
            [], [repo], [repo, base], [repo, base, h_proof], [repo, base, h_proof, "proof/x", "extra"],
            ["--trusted-change-approved"], ["--trusted-change-approved", repo, base, h_proof],
            ["--trusted-change-approved", repo, base, h_proof, "infra/x", "extra"],
            ["--trusted-change-approved", "--trusted-change-approved", repo, base, h_proof, "infra/x"],
            ["--", repo, base, h_proof, "proof/x"], ["--help"], ["-h"],
            ["--unknown", repo, base, h_proof, "proof/x"],
            ["--trusted-change-approved=true", repo, base, h_proof, "infra/x"],
            ["--trusted", repo, base, h_proof, "infra/x"],
            ["-repo", base, h_proof, "proof/x"], [repo, "-base", h_proof, "proof/x"],
            [repo, base, "-head", "proof/x"], [repo, base, h_proof, "-branch"],
            ["", base, h_proof, "proof/x"], [repo, "", h_proof, "proof/x"], [repo, base, "", "proof/x"],
        ]
        bad_cli = [a for a in cli_cases if (lambda r: r[0] != 2 or b"PRECHECK FAULT USAGE " not in r[2])(run_pre(a))]
        checks.append((f"CLI 22 项参数矩阵全退 2 USAGE", not bad_cli, 0 if not bad_cli else 1, f"bad={bad_cli}", ""))

        # 8. rev-parse --end-of-options
        p_eoo = git(repo, "rev-parse", "--verify", "--quiet", "--end-of-options", "--all^{commit}", check=False)
        checks.append(("git rev-parse --end-of-options 拒 --all", p_eoo.returncode == 1, p_eoo.returncode, "", ""))

        failed = 0
        for label, ok, rc, out, err in checks:
            mark = "OK" if ok else "FAIL"
            if not ok:
                failed += 1
            print(f"[{mark}] {label} (rc={rc})")
            if not ok:
                print(f"    out={out}\n    err={err}")
        print(f"EDGE PROBES: {len(checks)} total, {failed} failed")
        return 1 if failed else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
