#!/usr/bin/env bash
# 新阻断 N-1 的复现（不调用 lean、lake、git）：不带 -I 运行，且标准错误或标准输出写不出时，
# NOT_ISOLATED 分支自己抛异常，解释器为打印回溯去导入 traceback，后者再导入 re 等，
# 这些模块从脚本所在目录取到。参数：被审检出根目录。
SRC=${1:?用法：case_not_isolated_stderr.sh <被审检出>}
T=$(mktemp -d "${TMPDIR:-/tmp}/rf2-n1-XXXXXX")
cp "$SRC/formal_math/verification/runner/run.py" "$T/run.py"
cmp "$SRC/formal_math/verification/runner/run.py" "$T/run.py" && echo "run.py 逐字节等于被审提交那份：$(git -C "$SRC" hash-object "$T/run.py")"
# 同目录的顶替模块：记下自己被执行，往标准输出写一行伪造的绿结果（写不出就算了），以 0 退出。
for m in re traceback; do
cat > "$T/$m.py" <<PY
import posix
fd = posix.open("$T/ran", posix.O_WRONLY | posix.O_CREAT | posix.O_APPEND, 0o644)
posix.write(fd, b"$m\n")
try:
    if fd != 1:  # 标准输出已关闭时 1 号描述符会被上面的 open 占用
        posix.write(1, "FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）\n".encode())
except OSError:
    pass
posix._exit(0)
PY
done
show() { echo "rc=$1 | 顶替模块被执行：$( [ -e "$T/ran" ] && tr '\n' ',' < "$T/ran" || echo 否 )"; rm -f "$T/ran"; }
echo '$ python3 run.py --repo x                      # 对照：两路输出正常'
python3 "$T/run.py" --repo x; show $?
echo '$ python3 run.py --repo x 2>&-                 # 标准错误已关闭'
python3 "$T/run.py" --repo x 2>&-; show $?
echo '$ python3 run.py --repo x 2>/dev/full          # 标准错误写不出'
python3 "$T/run.py" --repo x 2>/dev/full; show $?
echo '$ python3 run.py --repo x 2>&1 | true 之类：标准错误是读端已关的管道'
python3 - "$T" <<'PY'
import os, subprocess, sys
r, w = os.pipe()
os.close(r)
p = subprocess.run(["python3", sys.argv[1] + "/run.py", "--repo", "x"], stdout=subprocess.PIPE, stderr=w)
sys.stdout.write(p.stdout.decode())
sys.exit(p.returncode)
PY
show $?
echo '$ python3 run.py --repo x >&-                  # 标准输出已关闭'
python3 "$T/run.py" --repo x >&-; show $?
echo '$ python3 -I run.py --repo x 2>&-              # 对照：带 -I'
python3 -I "$T/run.py" --repo x 2>&-; show $?
# 解释器在这条路径上到底会从脚本目录取哪些模块：换成只记名字、随后抛 ImportError 的顶替模块（不退出），看全名单。
rm -f "$T/re.py" "$T/traceback.py"
for m in re traceback contextlib linecache tokenize warnings collections functools itertools keyword codeop ast enum types \
         textwrap _colorize dataclasses typing operator token copyreg sre_parse sre_compile json; do
cat > "$T/$m.py" <<PY
import posix
fd = posix.open("$T/ran", posix.O_WRONLY | posix.O_CREAT | posix.O_APPEND, 0o644)
posix.write(fd, b"$m\n")
posix.close(fd)
raise ImportError("probe")
PY
done
echo '$ 只记名字的顶替模块，python3 run.py --repo x 2>&-'
python3 "$T/run.py" --repo x 2>&- >/dev/null; echo "rc=$? | 解释器从脚本目录取到的模块（按顺序）：$( [ -e "$T/ran" ] && tr '\n' ',' < "$T/ran" || echo 无 )"; rm -f "$T/ran"
echo '$ 只记名字的顶替模块，python3 run.py --repo x >&-'
python3 "$T/run.py" --repo x >&- 2>/dev/null; echo "rc=$? | 解释器从脚本目录取到的模块（按顺序）：$( [ -e "$T/ran" ] && tr '\n' ',' < "$T/ran" || echo 无 )"; rm -f "$T/ran"
# 同目录没有任何顶替模块时，这几种状态下的退出码（说明写的是退 2）。
rm -f "$T"/*.py; cp "$SRC/formal_math/verification/runner/run.py" "$T/run.py"
echo '--- 同目录只有 run.py'
python3 "$T/run.py" --repo x 2>&- >/dev/null;      echo "标准错误已关闭            rc=$?"
python3 "$T/run.py" --repo x 2>/dev/full >/dev/null; echo "标准错误指向 /dev/full    rc=$?"
python3 "$T/run.py" --repo x >&- 2>/dev/null;      echo "标准输出已关闭            rc=$?"
python3 "$T/run.py" --repo x >/dev/full 2>/dev/null; echo "标准输出指向 /dev/full    rc=$?"
rm -rf "$T"
