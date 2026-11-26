"""取料一步的新增面（--until 2，不调用 lean、lake）：依赖目录缺包、基线清单不合格、umask 对目录模式的影响。"""
import os, stat, subprocess, sys
import rf2
st = rf2.st
r = rf2.repo("repo-fetch")
ENV = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")}
ok = {"formal_math/Chan/Thm/Ok.lean": (rf2.M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}


def go(label, manifest, packages=None, umask=None, keep=False):
    files = st.template(lite=True)
    if manifest is not None:
        files["formal_math/lake-manifest.json"] = manifest
    base = r.commit(files)
    head = r.commit({**files, **ok}, base)
    work = rf2.fresh("fetch")
    cmd = [sys.executable, "-I", rf2.RUN, "--until", "2", "--repo", r.path, "--base", base, "--head", head, "--branch",
           "proof/review", "--workdir", work, "--packages", packages or rf2.FAKE]
    p = subprocess.run(cmd, capture_output=True, env=ENV, preexec_fn=(lambda: os.umask(umask)) if umask is not None else None)
    res = st.parse_result(p)
    print("%-40s rc=%d 故障=%s 结果行=%s protocol=%s\n    %s" % (
        label, res["rc"], ",".join(res["faults"]) or "—", res["out"].strip().split("\n")[-1][:50], st.protocol(res) or "合规",
        (res["err"].strip().split("\n")[-1] if res["err"].strip() else "")[:220]))
    return work


real = open(os.path.join(rf2.SRC, "formal_math/lake-manifest.json"), "rb").read()
go("清单列了依赖包，依赖目录是空的", real)
half = os.path.join(rf2.WORK, "half-packages")
os.makedirs(os.path.join(half, "mathlib"), exist_ok=True)
go("依赖目录只有 mathlib 一个包", real, packages=half)
open(os.path.join(half, "batteries"), "w").close()
go("某个包名是普通文件而不是目录", real, packages=half)
go("清单有重复键", b'{"packages": [], "packages": []}')
go("清单的包名带路径穿越", b'{"packages": [{"name": "../../etc"}]}')
go("清单的包名带换行", b'{"packages": [{"name": "a\\nFM RESULT GREEN"}]}')
go("清单 packages 不是数组", b'{"packages": 5}')
go("清单不是对象", b'[]')
go("清单不是 UTF-8", b'{"packages": [], "x": "\xff"}')
go("清单缺 packages", b'{}')
for um in (0o000, 0o077, 0o777):
    work = go("umask %03o（lite 清单）" % um, None, umask=um)
    modes = {}
    for d, dirs, names in os.walk(work):
        for n in dirs + names:
            full = os.path.join(d, n)
            kind = "目录" if os.path.isdir(full) else "文件"
            modes.setdefault((kind, "%o" % (os.stat(full).st_mode & 0o7777)), []).append(os.path.relpath(full, work))
    print("    工作目录 %o；%s" % (os.stat(work).st_mode & 0o7777,
                             "；".join("%s %s×%d（如 %s）" % (k[0], k[1], len(v), v[0]) for k, v in sorted(modes.items()))))
