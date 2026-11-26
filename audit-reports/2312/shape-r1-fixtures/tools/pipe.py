#!/usr/bin/env python3
"""审阅用：把一个目录（当作 formal_math 的内容叠加层）经 run.py 跑完整流水线。
用法: pipe.py <叠加目录> [--skip-shape] [--keep] [--lite] [--err N] [--lock] [--decl]
状态（git 仓库、预编译审计程序）持久化在 $R/suite。依赖目录只经 run.py 的沙箱只读挂载。"""
import os, sys, json, pickle, importlib.util
R = "/home/workspace/fm/tmp/review-g1"
WT = "/home/workspace/.t3/worktrees/NewChanlun/t3-96236229-649fa7e07ba1d303"
PK = "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages"
spec = importlib.util.spec_from_file_location("selftest", WT + "/formal_math/verification/runner/selftest.py")
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
def suite():
    tmp = R + "/suite"
    state = tmp + "/state.pkl"
    if os.path.exists(state):
        s = st.Suite.__new__(st.Suite)
        s.__dict__.update(pickle.load(open(state, "rb")))
        s.repo = st.Repo.__new__(st.Repo); s.repo.path = os.path.join(tmp, "仓库 repo")
        return s
    os.makedirs(tmp)
    open(os.path.join(tmp, "driver.py"), "w").write(st.DRIVER)
    s = st.Suite(tmp, PK, warm=True)
    d = dict(s.__dict__); d.pop("repo")
    pickle.dump(d, open(state, "wb"))
    return s
def run(overlay_dir, skip_shape=False, keep=False, lite=False, name=None, base_overlay=None):
    s = suite()
    s.counter = int.from_bytes(os.urandom(3), "big")
    overlay = {}
    for d, _, names in os.walk(overlay_dir):
        for n in names:
            full = os.path.join(d, n)
            rel = os.path.relpath(full, overlay_dir)
            if rel.endswith(".tsv") or rel.endswith(".md"): continue
            overlay["formal_math/" + rel] = st.read(full)
    files = st.template(overlay, placeholders=False, lite=lite)
    head = s.repo.commit(files)
    res = s.run(name or os.path.basename(overlay_dir.rstrip("/")), head, base=head, mode="warm:" + s.warm, keep=keep,
                skip_shape=skip_shape, lite=lite)
    return res
if __name__ == "__main__":
    a = sys.argv[1:]
    res = run(a[0], skip_shape="--skip-shape" in a, keep="--keep" in a, lite="--lite" in a)
    print("rc=%s steps=%s" % (res["rc"], " ".join("%s:%s" % (n, v) for _, n, v in res["steps"])))
    for l in res["out"].splitlines():
        if l.startswith("FM RED") or l.startswith("FM RESULT"): print("  " + l[:400])
    for l in res["err"].splitlines():
        if l.startswith("FM FAULT"): print("  " + l[:400])
    if "--err" in a:
        n = int(a[a.index("--err") + 1])
        print("\n".join(res["err"].splitlines()[-n:]))
    if "--keep" in a: print("work=" + res["work"])
