#!/usr/bin/env python3
"""r3 N-2 形状表「漏」一半：表内合法名字能否承载内容判定之外的东西，并被第 7 步读到。
A 组只用表内合法名字（期望七步全绿——问题是这时有没有逃出声明范围）；B 组用近似名字（期望判红）。
须包在 flock + guard.sh 里。"""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf3 as rf

L = ".lake/build/lib/lean"


def shell(script, imports=()):
    head = "module\n\n" + "".join("public import %s\n" % m for m in imports) + "\npublic section\n\n"
    return (head + '#eval show IO Unit from do\n  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n'
            % json.dumps(script)).encode()


r = rf.repo()
HOST_CANARY = os.path.join(rf.WORK, "host-canary-shape")
open(HOST_CANARY, "w").write("original-host-content\n")

# ---- A 组：全部用形状表内的合法名字 ----
A = r'''
set -x
B=.lake/build/lib/lean; I=.lake/build/ir
echo "---- CAP"; grep -E '^Cap(Eff|Prm|Bnd)' /proc/self/status
echo "---- 能否 mount"; (mount -t tmpfs none $B 2>&1 | head -2) ; (unshare -m true 2>&1 | head -2)
echo "---- 硬链接：宿主机只读根上的文件 -> 表内合法名"
ln /etc/hostname $B/Chan/Base.olean.hash 2>&1 | head -1
echo "---- 硬链接：被审工作区（只读绑定）的源码 -> 表内合法名"
ln ../Chan/Base.lean $B/Chan/Base.trace 2>&1 | head -1
ln HOSTCANARY $B/Chan/Base.ilean.hash 2>&1 | head -1
echo "---- 硬链接：.lake 之内（同一挂载）"
ln $B/Chan/Base.olean $B/Chan/Base.olean.server 2>&1 | head -1
ls -li $B/Chan/Base.olean $B/Chan/Base.olean.server | head -3
echo "---- 表内合法名字的内容换成别的"
printf 'NOT AN ILEAN AT ALL' > $B/Chan/Base.ilean
printf 'junk' > $B/Chan/Base.trace
printf 'junk' > $I/Chan/Base.c
printf '{"not":"a setup"}' > $I/Chan/Base.setup.json
echo "---- 稀疏且很大的表内合法名字（不占盘）"
truncate -s 3G $B/Chan/Base.ir && du -sh --apparent-size $B/Chan/Base.ir && du -sh $B/Chan/Base.ir
echo "---- .lake/config 下的合法名字由被审构建自己造"
mkdir -p .lake/config/77 && printf 'FORGED CONFIG' > .lake/config/77/lakefile.olean && : > .lake/config/77/lakefile.olean.trace
echo "---- 把 Chan.Base 的 .olean.private 换成另一个模块的（同为内容模块）"
cp $B/Chan.olean $B/Chan/Base.olean.private 2>&1 | head -1
echo "---- 模式：合法名字改成 0400 与 0600"
chmod 400 $B/Chan/Base.olean.private.hash; chmod 600 $B/Chan/Base.ir.sig
echo "---- 目录模式改成 0700（表内目录）"
chmod 700 $I/Chan
echo "---- 结束"; ls -la $B/Chan | head -20
'''
A = A.replace("HOSTCANARY", HOST_CANARY)

# ---- B 组：近似但不在表内的名字 ----
B = r'''
set -x
B=.lake/build/lib/lean
cp $B/Chan/Base.olean $B/Chan/base.olean                 # 只差大小写
cp $B/Chan/Base.olean "$B/Chan/Bаse.olean"          # 西里尔 a 的同形名
cp $B/Chan/Base.olean $B/Chan/Base.olean.hash.hash       # 后缀叠加
cp $B/Chan/Base.olean $B/Chan/.Base.olean                # 隐藏名
mkdir -p $B/Chan/Base && cp $B/Chan/Base.olean $B/Chan/Base/Inner.olean   # 不是模块前缀的目录
ln $B/Chan/Base.olean $B/Chan/Hard.olean                 # .lake 内硬链接到表外名字
mkdir -p .lake/config/88 && : > .lake/config/88/other.olean
: > .lake/build/lib/extra
'''

lite_files = rf.st.template(lite=True)
base = r.commit(lite_files)
head_a = r.commit({**lite_files, "formal_math/ChanExplore/PlantA.lean": shell(A, ("Chan", "Chan.Base"))}, base)
head_b = r.commit({**lite_files, "formal_math/ChanExplore/PlantB.lean": shell(B, ("Chan", "Chan.Base"))}, base)

print("基线 %s；A 头 %s；B 头 %s\n" % (base, head_a, head_b))

res_a = rf.run("N2-A-legal-names", r, head_a, base, full_err=True, warm=True)
print("A 组：rc=%s 红码=%s" % (res_a["rc"], sorted(res_a["reds"])))
work_a = res_a["work"]
lake_a = os.path.join(work_a, "audited", ".lake")
print("A 组运行后宿主机一侧：")
print("  宿主机金丝雀内容 = %r" % open(HOST_CANARY).read())
print("  /etc/hostname = %r（对照：%r）" % (open("/etc/hostname").read(), open("/etc/hostname").read()))
src = os.path.join(work_a, "audited", "Chan", "Base.lean")
print("  被审工作区 Chan/Base.lean = %r" % (open(src, "rb").read() if os.path.exists(src) else "不存在"))
for rel in ("build/lib/lean/Chan/Base.olean.hash", "build/lib/lean/Chan/Base.trace",
            "build/lib/lean/Chan/Base.ilean.hash", "build/lib/lean/Chan/Base.olean",
            "build/lib/lean/Chan/Base.olean.server", "build/lib/lean/Chan/Base.ir",
            "config/77/lakefile.olean"):
    p = os.path.join(lake_a, rel)
    if os.path.lexists(p):
        s = os.lstat(p)
        print("  %-46s 链接数=%d 大小=%d 实占块=%d 模式=%o" % (rel, s.st_nlink, s.st_size, s.st_blocks, s.st_mode & 0o7777))
    else:
        print("  %-46s 不存在" % rel)
print("  A 组 .lake 全部目录项数 = %d" % sum(len(d) + len(f) for _, d, f in os.walk(lake_a)))

res_b = rf.run("N2-B-near-miss", r, head_b, base, full_err=True, warm=True)
print("B 组：rc=%s 红码=%s" % (res_b["rc"], sorted(res_b["reds"])))
print("B 组逐项（红码，路径）：")
for pair in sorted(res_b["pairs"]):
    print("   ", pair)
