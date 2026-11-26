"""N-2 的逐字复现（真实命令行入口 python3 -I run.py，不走预编译审计程序）：
被审构建在产物目录里放名字带点的 .olean、以及一个只可进入不可列出的目录（里面有没有源码的 .olean 与符号链接），七步全绿。
之后在流水线之外确认：那个目录里的 .olean 按模块名是读得到的。"""
import os, subprocess
import rf2
r = rf2.repo()
base, files = rf2.lite(r)
M = rf2.M
L = ".lake/build/lib/lean"
ok = {"formal_math/Chan/Thm/Ok.lean": (M + "theorem ok : 1 + 1 = 2 := rfl\n").encode()}
script = ("for e in olean olean.server olean.private; do cp %s/Chan/Thm/Ok.$e %s/Chan/Thm.Ok.$e; done; "
          "mkdir %s/Chan/Hidden && for e in olean olean.server olean.private; do cp %s/Chan/Thm/Ok.$e %s/Chan/Hidden/Ghost.$e; done && "
          "ln -s /etc/hostname %s/Chan/Hidden/Link.olean && chmod 111 %s/Chan/Hidden" % ((L,) * 7))
plant = (M + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", "%s"]}\n' % script).encode()
head = r.commit({**files, **ok, "formal_math/ChanExplore/Plant.lean": plant}, base)
res = rf2.run("N2-artifacts", r, head, base, warm=False)
lib = os.path.join(res["work"], "audited", L)
hidden = os.path.join(lib, "Chan", "Hidden")
print("运行后宿主机上：Chan/Thm.Ok.olean 存在=%s；Chan/Hidden 模式=%o" % (
    os.path.isfile(os.path.join(lib, "Chan", "Thm.Ok.olean")), os.stat(hidden).st_mode & 0o777))
try:
    os.listdir(hidden)
    print("Hidden 可列出（不应如此）")
except PermissionError as e:
    print("os.listdir(Hidden) → PermissionError（os.walk 默认吞掉这个错误，目录内容不进核对）")
for mod in ("Chan.Hidden.Ghost", "Chan.«Thm.Ok»", "Chan.Hidden.Missing"):
    p = subprocess.run(["lean", "--stdin"], input=("import %s\n#check @ok\n" % mod).encode(), capture_output=True,
                       env={**os.environ, "LEAN_PATH": lib}, cwd=os.path.join(res["work"], "audited"))
    print("$ echo 'import %s' | LEAN_PATH=<产物目录> lean --stdin → rc=%d %s" % (
        mod, p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip().replace("\n", " ⏎ ")[:200]))
print("符号链接：%s -> %s" % ("Chan/Hidden/Link.olean", os.readlink(os.path.join(hidden, "Link.olean"))))
os.chmod(hidden, 0o755)
