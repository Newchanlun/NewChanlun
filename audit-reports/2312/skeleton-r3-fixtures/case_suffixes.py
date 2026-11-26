#!/usr/bin/env python3
"""r3 形状表「误红」一半：最小 Lake 包（无依赖）在多种情形下实际产出的 .lake 目录项，与被审形状表对照。
只跑 lake build，不经 run.py。须包在 flock + guard.sh 里。"""
import importlib.util, os, shutil, subprocess, sys

RUNNER = os.environ["RF_RUNNER"]
OUT = os.environ.get("RF_OUT", "/home/workspace/fm/tmp/review-f3/work/suffixes")
spec = importlib.util.spec_from_file_location("fm_run", os.path.join(RUNNER, "run.py"))
run = importlib.util.module_from_spec(spec); spec.loader.exec_module(run)
st_spec = importlib.util.spec_from_file_location("fm_st", os.path.join(RUNNER, "selftest.py"))
st = importlib.util.module_from_spec(st_spec); st_spec.loader.exec_module(st)
TOOLCHAIN = open("/home/workspace/.t3/worktrees/NewChanlun/t3-798198d0-7f46c36c7d707dbd/formal_math/lean-toolchain", "rb").read()
os.makedirs(OUT, exist_ok=True)
_probe = os.path.join(OUT, "toolchain-probe")
os.makedirs(_probe, exist_ok=True)
open(os.path.join(_probe, "lean-toolchain"), "wb").write(TOOLCHAIN)
PREFIX = subprocess.run(["lean", "--print-prefix"], cwd=_probe, capture_output=True, text=True).stdout.strip()
LAKE = os.path.join(PREFIX, "bin", "lake")
assert os.path.isfile(LAKE), ("lake 不在 %r" % LAKE)


def pkg(name, files):
    d = os.path.join(OUT, name)
    st.rmtree(d); os.makedirs(d)
    full = {"lean-toolchain": TOOLCHAIN, "lake-manifest.json": st.LITE_MANIFEST, **files}
    full["lakefile.toml"] = st.lakefile({"formal_math/" + k: v for k, v in full.items()}, require=False)
    for rel, data in full.items():
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(data)
    return d


def build(d, args=("build",), wfail=True):
    env = {"PATH": os.path.join(PREFIX, "bin") + ":/usr/bin:/bin", "HOME": os.path.join(d, "home"),
           "LANG": "C.UTF-8", "TMPDIR": os.environ.get("TMPDIR", "/tmp")}
    os.makedirs(env["HOME"], exist_ok=True)
    a = list(args) + (["--wfail"] if wfail and args[0] == "build" else [])
    return subprocess.run([LAKE, *a], cwd=d, capture_output=True, env=env)


def entries(lake_dir):
    got = []
    for d, dirs, names in os.walk(lake_dir):
        for n in sorted(dirs + names):
            full = os.path.join(d, n)
            rel = os.path.relpath(full, lake_dir)
            kind = "链接" if os.path.islink(full) else "目录" if os.path.isdir(full) else "文件"
            got.append((rel, kind))
    return sorted(got)


def table_check(d, modules):
    """用被审 run.py 自己的 artifact_reds() 判这堆真实产物。"""
    ctx = run.Run(); ctx.modules = modules
    return run.artifact_reds(ctx, os.path.join(d, ".lake"))


def report(label, d, modules, rc_note=""):
    lake = os.path.join(d, ".lake")
    ents = entries(lake)
    reds = table_check(d, modules)
    sufs = set()
    for rel, kind in ents:
        if kind == "文件":
            base = rel.rsplit("/", 1)[-1]
            sufs.add("." + base.split(".", 1)[1] if "." in base else "(无后缀)")
    print("### %s%s\n  目录项 %d 个（目录 %d、文件 %d、链接 %d）；形状表判定：%s"
          % (label, rc_note, len(ents), sum(k == "目录" for _, k in ents), sum(k == "文件" for _, k in ents),
             sum(k == "链接" for _, k in ents), reds or "全部在表内（无红）"))
    print("  出现的文件后缀：%s" % ", ".join(sorted(sufs)))
    unexpected = [e for e in ents if e[0].startswith("build") and e[1] == "文件"
                  and "." + e[0].rsplit("/", 1)[-1].split(".", 1)[1] not in run.LIB_SUFFIXES + run.IR_SUFFIXES
                  and not e[0].startswith("config")]
    if unexpected:
        print("  后缀不在 LIB_SUFFIXES+IR_SUFFIXES 里的文件：%r" % unexpected)
    sys.stdout.flush()
    return ents, reds, sufs


M = b"module\n\npublic section\n\n"
all_sufs, summary = set(), []

# 1 单模块（只有一个内容模块的被审提交）
d = pkg("single", {"Chan.lean": b"module\n"})
p = build(d); e, r, s_ = report("单模块 Chan（lake build --wfail 退 %d）" % p.returncode, d, ["Chan"]); all_sufs |= s_
summary.append(("单模块", r))

# 2 多级目录 + deriving + instance + 结构
deep = {"Chan.lean": b"module\npublic import Chan.A.B.C\n",
        "Chan/A/B/C.lean": M + (
            "public inductive Color where\n  | red | green\n  deriving DecidableEq, Repr, Inhabited\n\n"
            "public instance : ToString Color := \u27e8fun _ => \"c\"\u27e9\n\n"
            "public structure P where\n  x : Nat\n  deriving Repr\n\n"
            "public def f (c : Color) : Nat := match c with | .red => 0 | .green => 1\n").encode()}
d = pkg("deep", deep)
p = build(d); e, r, s_ = report("多级目录 Chan/A/B/C，带 deriving、instance、structure（退 %d）" % p.returncode,
                               d, ["Chan", "Chan.A.B.C"]); all_sufs |= s_
summary.append(("多级+deriving", r))

# 3 @[expose] public section
exp = {"Chan.lean": b"module\npublic import Chan.Defs.D\n",
       "Chan/Defs/D.lean": b"module\n\n@[expose] public section\n\npublic def g (n : Nat) : Nat := n + 1\n\n"
                           b"public theorem g_ok : g 1 = 2 := rfl\n"}
d = pkg("expose", exp)
p = build(d); e, r, s_ = report("@[expose] public section（退 %d）" % p.returncode, d, ["Chan", "Chan.Defs.D"]); all_sufs |= s_
summary.append(("@[expose]", r))

# 4 增量构建：建好后改一个文件再建；以及完全重跑一次
d = pkg("incr", deep)
p1 = build(d); before = entries(os.path.join(d, ".lake"))
open(os.path.join(d, "Chan/A/B/C.lean"), "ab").write(b"\npublic def h : Nat := f .red\n")
p2 = build(d)
e, r, s_ = report("增量构建（第一次退 %d，改一个文件后第二次退 %d）" % (p1.returncode, p2.returncode),
                  d, ["Chan", "Chan.A.B.C"]); all_sufs |= s_
p3 = build(d)
e3, r3, s3 = report("无改动再建一次（退 %d）" % p3.returncode, d, ["Chan", "Chan.A.B.C"]); all_sufs |= s3
print("  增量前后目录项差异：新增 %r 消失 %r" % (sorted(set(e) - set(before)), sorted(set(before) - set(e))))
summary += [("增量构建", r), ("无改动重建", r3)]

# 5 构建失败后重跑（先放一个编译不过的模块，再修好）
bad = {"Chan.lean": b"module\npublic import Chan.Bad\n",
       "Chan/Bad.lean": M + b"public theorem oops : 1 = 2 := rfl\n"}
d = pkg("fail", bad)
pf = build(d)
ef, rf_, sf = report("构建失败后（退 %d）" % pf.returncode, d, ["Chan", "Chan.Bad"]); all_sufs |= sf
open(os.path.join(d, "Chan/Bad.lean"), "wb").write(M + b"public theorem oops : 1 = 1 := rfl\n")
pf2 = build(d)
e, r, s_ = report("修好后重跑（退 %d）" % pf2.returncode, d, ["Chan", "Chan.Bad"]); all_sufs |= s_
summary += [("构建失败后", rf_), ("失败后修好重跑", r)]

# 6 带告警 → --wfail 失败；之后的残留
warn = {"Chan.lean": b"module\npublic import Chan.W\n",
        "Chan/W.lean": M + b"public def w (n : Nat) : Nat := 0\n"}
d = pkg("warn", warn)
pw = build(d)
e, r, s_ = report("带 unusedVariables 告警、--wfail（退 %d）" % pw.returncode, d, ["Chan", "Chan.W"]); all_sufs |= s_
summary.append(("--wfail 告警", r))

# 7 lake 的锁文件与临时文件：构建中途与正常结束后
d = pkg("locks", deep)
p = build(d)
leftovers = [x for x in entries(os.path.join(d, ".lake")) if "lock" in x[0].lower() or "tmp" in x[0].lower()
             or x[0].startswith("packages") or x[0] in ("config",)]
print("### 正常结束后 .lake 里与锁/临时/packages/config 相关的目录项：%r" % leftovers)
print("### .lake 顶层：%r" % sorted(os.listdir(os.path.join(d, ".lake"))))
# 另看 lake 在构建期间是否在 .lake 外或内放锁文件
print("### 包目录顶层（.lake 之外）：%r" % sorted(x for x in os.listdir(d) if x != ".lake"))

print("\n=== 实测到的全部文件后缀（去重）")
print(sorted(all_sufs))
print("=== 被审形状表 LIB_SUFFIXES（%d 个）\n%r" % (len(run.LIB_SUFFIXES), list(run.LIB_SUFFIXES)))
print("=== 被审形状表 IR_SUFFIXES（%d 个）\n%r" % (len(run.IR_SUFFIXES), list(run.IR_SUFFIXES)))
print("=== 实测后缀里不在形状表的：%r" % sorted(all_sufs - set(run.LIB_SUFFIXES) - set(run.IR_SUFFIXES)
                                        - {".olean.trace", ".toml", ".json", "(无后缀)", ".lean-toolchain"}))
print("\n=== 各情形的形状表判定汇总")
for label, reds in summary:
    print("  %-18s → %s" % (label, reds or "无红"))
