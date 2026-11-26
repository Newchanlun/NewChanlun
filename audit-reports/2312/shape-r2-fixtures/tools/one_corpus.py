import importlib.util, os, pickle, sys
WT = "/home/workspace/.t3/worktrees/NewChanlun/t3-d0f2425c-f0be678e43ff7b3c"
PK = "/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages"
spec = importlib.util.spec_from_file_location("selftest", WT + "/formal_math/verification/runner/selftest.py")
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
import tempfile
tmp = tempfile.mkdtemp(prefix="r2-corpus-", dir=os.environ["TMPDIR"])
open(os.path.join(tmp, "driver.py"), "w").write(st.DRIVER)
s = st.Suite(tmp, PK, warm=True)
for fx in sys.argv[1:]:
    res, how = st.corpus_case(s, fx)
    print("=== %s  rc=%s  %s" % (fx, res["rc"], how))
    print("   步骤: " + " ".join("%s:%s" % (n, v) for _, n, v in res["steps"]))
    for l in res["out"].splitlines():
        if l.startswith("FM RED") or l.startswith("FM RESULT"): print("   " + l[:300])
