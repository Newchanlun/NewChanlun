"""跟进用例：锁文件里的孤立代理项（未捕获回溯）、产物目录符号链接、垃圾 .olean、Defs 不用 public section、
派生证书等价性（旧必绿夹具在新入口的 ENV_PARTIAL / EXPOSE_SECTION 是否只来自缺证书）。"""
import rf, os, sys, json, subprocess, re
r = rf.repo()
base, files = rf.base_and_files(r)
only = sys.argv[1:]
M = "module\n\npublic section\n\n"
def enc(d):
    return {"formal_math/" + k: (v if isinstance(v, bytes) else v.encode()) for k, v in d.items()}
def case(name, extra, **kw):
    if only and name not in only:
        return None
    head = r.commit({**files, **enc(extra)}, base)
    return rf.run(name, r, head, base, **kw)
def sh(script, header=M):
    q = '"' + script.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return header + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n  pure ()\n' % q

# L1/L2：statement-lock.json（被审提交、decl 角色可改）的键里放 JSON 转义的孤立代理项
case("L1-lock-lone-surrogate-key", {"statement-lock.json": b'{"\\ud800": "x"}\n'}, branch="decl/review")
case("L2-lock-dup-surrogate-key", {"statement-lock.json": b'{"\\ud800": "x", "\\ud800": "y"}\n'}, branch="decl/review")
case("L3-lock-dup-newline-key", {"statement-lock.json": b'{"a\\nFM RESULT GREEN": "x", "a\\nFM RESULT GREEN": "y"}\n'}, branch="decl/review")
case("L4-lock-newline-key-removed", {"statement-lock.json": b'{"a\\nFM RESULT GREEN forged": "x"}\n'}, branch="decl/review")
# P9b：把 lib/lean 换成符号链接
dep = {"ChanExplore/A.lean": M + "theorem a_ok : True := trivial\n"}
imp = "module\n\npublic import ChanExplore.A\n\npublic section\n\n"
case("P9b-symlink-lib", {**dep, "ChanExplore/P9b.lean": sh("mv .lake/build/lib/lean .lake/build/lib/lean.real && ln -s lean.real .lake/build/lib/lean", imp)})
# P11c：上游模块的三个分片换成垃圾（先写临时文件再改名，不动已映射的 inode）
g = "for s in olean olean.private olean.server; do head -c 65536 /dev/urandom > .lake/tmp.$s && mv .lake/tmp.$s .lake/build/lib/lean/ChanExplore/A.$s; done"
case("P11c-garbage-olean-renamed", {**dep, "ChanExplore/P11c.lean": sh(g, imp)})
# X1c：Chan/Defs 文件不用 public section，锁文件登记现算哈希
case("X1c-defs-no-public-section-locked", {"Chan/Defs/X1.lean": "module\n\ndef hidden : Nat := 1\n",
     "statement-lock.json": json.dumps({"_private.Chan.Defs.X1.0.hidden": "1349635ccd065bdf2c3fa7c77c279bc39371c74f6315f9cced14677ac054d24b"}) + "\n"}, branch="decl/review")

# D1：派生证书等价性
if not only or "D1" in only:
    V = os.path.join(rf.SRC, "formal_math/verification")
    rows = [l.rstrip("\n").split("\t") for l in open(os.path.join(V, "runner/fixtures.tsv"), encoding="utf-8") if l.strip() and not l.startswith("#")]
    targets = [x[0] for x in rows if x[0].startswith("must_green") and x[2] == "1" and ("ENV_PARTIAL" in x[4] or "EXPOSE_SECTION" in x[4])]
    prefix = subprocess.run(["lean", "--print-prefix"], capture_output=True, text=True, cwd=os.path.join(rf.SRC, "formal_math")).stdout.strip()
    print("\n=== D1 派生证书等价性：%d 个旧必绿夹具" % len(targets))
    for fx in targets:
        src = os.path.join(V, fx, "formal_math"); overlay = {}
        for d, _, names in os.walk(src):
            for n in names:
                overlay["formal_math/" + os.path.relpath(os.path.join(d, n), src)] = open(os.path.join(d, n), "rb").read()
        fs = rf.st.template(overlay, placeholders=False)
        head = r.commit(fs)
        os.environ["RF_ERR"] = "0"
        _o = sys.stdout; sys.stdout = open(os.devnull, "w")
        res = rf.run("D1", r, head, head)
        sys.stdout = _o
        reds = [l for l in res["out"].splitlines() if l.startswith("FM RED ")]
        aud = os.path.join(res["work"], "audited")
        binary = os.path.join(res["work"], "trusted/verification/auditor/.lake/build/bin/fm_audit")
        mods = sorted(p[len("formal_math/"):-5].replace("/", ".") for p in fs if p.endswith(".lean") and not p.startswith("formal_math/verification/"))
        search = [os.path.join(rf.PACKAGES, n, ".lake/build/lib/lean") for n in sorted(os.listdir(rf.PACKAGES))] + [aud + "/.lake/build/lib/lean"]
        env = {"PATH": prefix + "/bin:/usr/bin:/bin", "LEAN_PATH": ":".join(search), "LEAN_SYSROOT": prefix, "LANG": "C.UTF-8"}
        p0 = subprocess.run([binary, "env", *mods], cwd=aud, env=env, capture_output=True, text=True)
        f0 = [json.loads(l) for l in p0.stdout.splitlines() if l.startswith('["finding"')]
        # 证书：ENV_PARTIAL 的源定义名 + 门 15 被判的声明名（旧实现的证书同时豁免这两处）
        names = set()
        for f in f0:
            if f[4] == "ENV_PARTIAL":
                m = re.search(r"源定义 (.+) 不是结构", f[5]); names.add(m.group(1))
            if f[4] == "EXPOSE_SECTION":
                names.add(f[3])
        cert = os.path.join(res["work"], "rf-cert.json")
        json.dump(sorted(names), open(cert, "w"), ensure_ascii=False)
        p1 = subprocess.run([binary, "env", "--derived", cert, *mods], cwd=aud, env=env, capture_output=True, text=True)
        f1 = [json.loads(l) for l in p1.stdout.splitlines() if l.startswith('["finding"')]
        print("%s\n   流水线 rc=%d 红码=%s\n   无证书发现=%s\n   证书名单=%s\n   给证书后 rc=%d 剩余发现=%s" % (
            fx, res["rc"], sorted({l.split(" ")[3] for l in reds}), sorted({(f[4], f[3]) for f in f0}), sorted(names), p1.returncode, [(f[4], f[3]) for f in f1]))
