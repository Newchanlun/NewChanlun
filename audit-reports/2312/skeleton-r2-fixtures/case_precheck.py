"""第 1 步对预检输出的转出：不调用 lean、lake（--until 1）。
第一部分：真预检的每个规则码与故障码，运行脚本的红码集合须等于直跑预检的红码集合，故障一律退 2。
第二部分：自举模式下把受信提交里的 precheck.py 换成打印任意内容的假预检，核对未知输出都退 2。"""
import os, re, subprocess, sys
import rf2
st = rf2.st
r = rf2.repo("repo-precheck")
base, files = rf2.lite(r)
ok = {"formal_math/Chan/Thm/Ok.lean": (rf2.M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}
with_thm = {**files, **ok}
blob = r.git("hash-object", "-w", "--no-filters", "--stdin", data=ok["formal_math/Chan/Thm/Ok.lean"]).strip()
ENV = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
PRE = os.path.join(rf2.SRC, "formal_math/verification/precheck/precheck.py")


def both(label, head, branch="proof/review", base_=None, approved=False, expect=None):
    b = base_ or base
    flag = ["--trusted-change-approved"] if approved else []
    d = subprocess.run([sys.executable, "-I", PRE, *flag, r.path, b, head, branch], capture_output=True, env=ENV)
    direct = sorted({l.split(b" ")[2].decode() for l in d.stdout.split(b"\n") if l.startswith(b"PRECHECK RED ")})
    dfault = re.findall(rb"^PRECHECK FAULT (\S+)", d.stderr, re.M)
    work = rf2.fresh("pre-" + label)
    p = subprocess.run([sys.executable, "-I", rf2.RUN, *flag, "--until", "1", "--repo", r.path, "--base", b, "--head", head,
                        "--branch", branch, "--workdir", work, "--packages", rf2.FAKE], capture_output=True, env=ENV)
    res = st.parse_result(p)
    same = (d.returncode == 1 and res["rc"] == 1 and sorted(res["reds"]) == direct) or \
           (d.returncode == 2 and res["rc"] == 2 and res["faults"] == ["PRECHECK_EXIT"]) or \
           (d.returncode == 0 and res["rc"] == 2 and "FM RESULT PARTIAL" in res["out"])
    print("%s\t%-22s 直跑预检 rc=%d 红码=%s 故障=%s | 运行脚本 rc=%d 红码=%s 故障=%s 结果行=%s | protocol=%s" % (
        "一致" if same and not st.protocol(res) else "不一致", label, d.returncode, ",".join(direct) or "—",
        b",".join(dfault).decode() or "—", res["rc"], ",".join(sorted(res["reds"])) or "—", ",".join(res["faults"]) or "—",
        res["out"].strip().split("\n")[-1][:60], st.protocol(res) or "合规"))
    if expect and expect not in direct + [x.decode() for x in dfault]:
        print("  ！夹具没有触发预期的 %s" % expect)
    sys.stdout.flush()


print("== 第一部分：真预检")
both("GREEN", r.commit(with_thm, base))
dup = st.entry(b"100644", b"Ok.lean", blob) * 2
both("TREE_FORM", r.commit(with_thm, base, raw={"formal_math/Chan/Thm": dup}), expect="TREE_FORM")
both("EMPTY_TREE", r.commit(with_thm, base, raw={"formal_math/Chan/Thm": b""}), expect="EMPTY_TREE")
both("MODE", r.commit(with_thm, base, raw={"formal_math/Chan/Thm": st.entry(b"100755", b"Ok.lean", blob)}), expect="MODE")
both("LAKE_FILE", r.commit({**with_thm, "formal_math/Chan/Thm/lakefile.lean": b"import Lake\n"}, base), expect="LAKE_FILE")
both("PATH_GRAMMAR", r.commit(with_thm, base, raw={"formal_math/Chan/Thm": st.entry(b"100644", b"A b\x1b[2J\\x41.lean", blob)}),
     expect="PATH_GRAMMAR")
both("PATH_GRAMMAR-case", r.commit({**with_thm, "formal_math/Chan/Thm/ok.lean": b"module\n"}, base), expect="PATH_GRAMMAR")
both("TOP_LEVEL", r.commit({**with_thm, "formal_math/extra.txt": b"x\n"}, base), expect="TOP_LEVEL")
both("CONTENT_SHAPE", r.commit({**with_thm, "formal_math/Chan/Thm/notes.txt": b"x\n"}, base), expect="CONTENT_SHAPE")
both("BRANCH_ROLE", r.commit(with_thm, base), branch="feature/x", expect="BRANCH_ROLE")
both("PATH_SCOPE", r.commit({**files, "formal_math/Chan/Defs/X.lean": b"module\n"}, base), expect="PATH_SCOPE")
readme = "formal_math/verification/runner/README.md"
infra = r.commit({**files, readme: files[readme] + b"\n"}, base)
both("TRUST_UNAPPROVED", infra, branch="infra/x", expect="TRUST_UNAPPROVED")
both("infra-approved-GREEN", infra, branch="infra/x", approved=True)
both("TRUSTED_DRIFT", r.commit({**files, "formal_math/lean-toolchain": b"leanprover/lean4:v4.0.0\n"}, base), expect="TRUSTED_DRIFT")
both("NOT_ANCESTOR", r.commit(with_thm), expect="NOT_ANCESTOR")
bad_base = r.commit(with_thm, raw={"formal_math/Chan/Thm": dup})
both("BASE_FORM", r.commit(with_thm, bad_base), base_=bad_base, expect="BASE_FORM")

print("== 第二部分：假预检（自举模式，受信提交里的 precheck.py 被换掉；run.py 仍是受信那份）")
head = r.commit(with_thm, base)
H = head.encode()
GREEN = b"PRECHECK GREEN OK " + H + b" role=proof\n"
variants = [
    ("退 0，绿行两条", 0, GREEN * 2),
    ("退 0，绿行提交名不符", 0, b"PRECHECK GREEN OK " + b"0" * 40 + b" role=proof\n"),
    ("退 0，绿行后多一行", 0, GREEN + b"hello\n"),
    ("退 0，没有输出", 0, b""),
    ("退 0，绿行没有换行结尾", 0, GREEN[:-1]),
    ("退 0，输出是红行", 0, b"PRECHECK RED TOP_LEVEL x y\n"),
    ("退 1，没有输出", 1, b""),
    ("退 1，绿行", 1, GREEN),
    ("退 1，红行加一行杂项", 1, b"PRECHECK RED TOP_LEVEL x y\nnote\n"),
    ("退 1，红码小写", 1, b"PRECHECK RED top_level x y\n"),
    ("退 1，红行缺说明栏", 1, b"PRECHECK RED TOP_LEVEL x\n"),
    ("退 1，红行加空行", 1, b"PRECHECK RED TOP_LEVEL x y\n\n"),
    ("退 1，红行与绿行混排", 1, b"PRECHECK RED TOP_LEVEL x y\n" + GREEN),
    ("退 2，带红行", 2, b"PRECHECK RED TOP_LEVEL x y\n"),
    ("退 3", 3, GREEN),
    ("退 1，未知红码（应原样转出，退 1）", 1, b"PRECHECK RED BRAND_NEW_RULE formal_math/x\\x0aFM\\x20RESULT\\x20GREEN msg \xff\x1b[2J\xe2\x80\xa8tail\n"),
    ("退 0，绿行的 role 栏带控制符（应全绿到第 1 步，PARTIAL）", 0, GREEN[:-1] + b"\x1b[2J\rFM RESULT GREEN\n"),
    ("被信号杀死", -9, GREEN),
]
for label, rc, out in variants:
    body = "import os, signal\nos.write(1, %r)\n" % out
    body += "os.kill(os.getpid(), signal.SIGKILL)\n" if rc < 0 else "raise SystemExit(%d)\n" % rc
    trusted = r.commit({**files, "formal_math/verification/precheck/precheck.py": body.encode()})
    work = rf2.fresh("fakepre")
    p = subprocess.run([sys.executable, "-I", rf2.RUN, "--until", "1", "--bootstrap-trusted-from", trusted, "--repo", r.path,
                        "--base", base, "--head", head, "--branch", "proof/review", "--workdir", work,
                        "--packages", rf2.FAKE], capture_output=True, env=ENV)
    res = st.parse_result(p)
    lines = res["out"].strip().split("\n")
    print("%-44s rc=%d 红码=%s 故障=%s protocol=%s\n    标准输出第 3 行起：%s" % (
        label, res["rc"], ",".join(sorted(res["reds"])) or "—", ",".join(res["faults"]) or "—",
        st.protocol(res) or "合规", " ⏎ ".join(lines[2:])))
