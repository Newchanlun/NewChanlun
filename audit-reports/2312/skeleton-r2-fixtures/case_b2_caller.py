"""B-2 的调用方来源（上一轮 case_args.sh 的两例按原样重做，另加几种新形状）。不调用 lean、lake。"""
import os, shutil, subprocess, sys
import rf2
st = rf2.st
r = rf2.repo("repo-precheck")
base, files = rf2.lite(r)
ENV = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
W = os.fsencode(rf2.WORK)
nonempty = W + b"/wd-\xff-nonempty"
os.makedirs(nonempty, exist_ok=True)
open(nonempty + b"/x", "w").close()
ok_wd = W + b"/wd-new"


def go(label, **over):
    args = {"--repo": os.fsencode(r.path), "--base": base.encode(), "--head": base.encode(), "--branch": b"proof/x",
            "--workdir": ok_wd, "--packages": os.fsencode(rf2.FAKE)}
    extra = over.pop("extra", [])
    args.update({"--" + k: v for k, v in over.items()})
    shutil.rmtree(ok_wd, ignore_errors=True)
    argv = [x for k, v in args.items() for x in (k.encode(), v)] + extra
    p = subprocess.run([sys.executable, "-I", rf2.RUN, *argv, "--until", "1"], capture_output=True, env=ENV)
    res = st.parse_result(p)
    print("%-44s rc=%d 故障=%s protocol=%s\n    out: %s\n    err: %s" % (
        label, res["rc"], ",".join(res["faults"]) or "—", st.protocol(res) or "合规",
        res["out"].strip().replace("\n", " ⏎ ")[-160:], res["err"].strip().split("\n")[-1][:230] if res["err"].strip() else ""))


go("工作目录含非 UTF-8（已存在非空）", workdir=nonempty)
go("依赖目录含非 UTF-8 且不存在", packages=b"/nonexistent-\xff")
go("工作目录含非 UTF-8、父目录不存在", workdir=W + b"/a-bad-\xff/x")
go("工作目录含非 UTF-8、可新建（应正常跑到第 1 步）", workdir=W + b"/wd-\xff-new")
shutil.rmtree(W + b"/wd-\xff-new", ignore_errors=True)
go("仓库路径非 UTF-8 且不存在", repo=W + b"/repo-\xff")
go("自举提交参数非 UTF-8", extra=[b"--bootstrap-trusted-from", b"\xff\xfe"])
go("基线参数是孤立代理项的 UTF-8 形式", base=b"\xed\xa0\x80")
go("分支名非 UTF-8 且带换行", branch=b"proof/\xff\nFM RESULT GREEN")
shutil.rmtree(nonempty)
shutil.rmtree(ok_wd, ignore_errors=True)
