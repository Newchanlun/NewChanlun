#!/usr/bin/env python3
"""r3 N-2 续：硬链接与能力探测重做（上一版 ln 的目标已存在、诊断被 IO.Process.output 吞掉）。
诊断经 IO.eprintln 打到 lean 的标准错误，会以 FM LOG build 行进日志。须包在 flock + guard.sh 里。"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rf3 as rf


def shell(script, imports=()):
    """跑一段 shell 并把它的两路输出打到 lean 的标准错误（经 FM LOG build 出现在日志里）。"""
    head = "module\n\n" + "".join("public import %s\n" % m for m in imports) + "\npublic section\n\n"
    return (head + '#eval show IO Unit from do\n'
            '  let out ← IO.Process.output {cmd := "/bin/sh", args := #["-c", %s]}\n'
            '  IO.eprintln ("PROBE-OUT " ++ out.stdout.replace "\\n" " | ")\n'
            '  IO.eprintln ("PROBE-ERR " ++ out.stderr.replace "\\n" " | ")\n' % json.dumps(script)).encode()


r = rf.repo()
CANARY = os.path.join(rf.WORK, "host-canary-hardlink")
open(CANARY, "w").write("ORIGINAL\n")
os.chmod(CANARY, 0o666)

A = r'''
B=.lake/build/lib/lean; I=.lake/build/ir
echo "CAP=$(grep -E '^CapEff' /proc/self/status | tr -d '\t')"
echo "mount-tmpfs: $(mount -t tmpfs none $B 2>&1 | head -1)"
echo "unshare-m: $(unshare -m true 2>&1 | head -1)"
echo "id: $(id -u):$(id -g)"
# 先删掉表内的可选文件，再试硬链接到它的名字上
for t in "$B/Chan/Base.olean.hash:/etc/hostname" "$B/Chan/Base.trace:../Chan/Base.lean" \
         "$B/Chan/Base.ilean.hash:CANARY" "$B/Chan/Base.ir.hash:$I/Chan/Base.c"; do
  dst=${t%%:*}; src=${t#*:}
  rm -f "$dst"
  echo "ln $src -> ${dst##*/}: $(ln "$src" "$dst" 2>&1 | head -1)$( [ -e "$dst" ] && echo " 建成，链接数=$(stat -c %h "$dst")" )"
done
# 若链接建成，试着经链接改写
if [ -e "$B/Chan/Base.ilean.hash" ]; then
  echo "写链接: $(printf 'TAMPERED-VIA-HARDLINK\n' > "$B/Chan/Base.ilean.hash" 2>&1 && echo ok)"
fi
echo "符号链接能不能建: $(ln -s /etc/hostname $B/Chan/Base.olean.server.hash 2>&1 | head -1; [ -L $B/Chan/Base.olean.server.hash ] && echo 建成)"
rm -f $B/Chan/Base.olean.server.hash
echo "宿主机根可写否: $(printf x > /etc/fm-probe 2>&1 | head -1)"
echo "被审源码可写否: $(printf x > ../Chan/Base.lean 2>&1 | head -1)"
echo "依赖挂载点可写否: $(printf x > .lake/packages/probe 2>&1 | head -1)"
echo "DONE"
'''.replace("CANARY", CANARY)

lite_files = rf.st.template(lite=True)
base = r.commit(lite_files)
head = r.commit({**lite_files, "formal_math/ChanExplore/PlantC.lean": shell(A, ("Chan", "Chan.Base"))}, base)
print("基线 %s；头 %s\n" % (base, head))
res = rf.run("N2-C-hardlink", r, head, base, full_err=True, warm=True)
print("rc=%s 红码=%s" % (res["rc"], sorted(res["reds"])))
print("\n宿主机金丝雀 %s 内容 = %r" % (CANARY, open(CANARY).read()))
src = os.path.join(res["work"], "audited", "Chan", "Base.lean")
print("被审工作区 Chan/Base.lean = %r" % (open(src, "rb").read() if os.path.exists(src) else "不存在"))
print("/etc/fm-probe 存在 = %s" % os.path.exists("/etc/fm-probe"))
lake = os.path.join(res["work"], "audited", ".lake")
for rel in ("build/lib/lean/Chan/Base.olean.hash", "build/lib/lean/Chan/Base.trace",
            "build/lib/lean/Chan/Base.ilean.hash", "build/lib/lean/Chan/Base.ir.hash"):
    p = os.path.join(lake, rel)
    print("  %-42s %s" % (rel, ("链接数=%d 大小=%d" % (os.lstat(p).st_nlink, os.lstat(p).st_size))
                          if os.path.lexists(p) else "不存在"))
