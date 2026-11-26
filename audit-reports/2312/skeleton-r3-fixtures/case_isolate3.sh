#!/usr/bin/env bash
# r3 N-1：隔离检查。被审 run.py 逐字节复制到放满冒名模块的目录，试多种启动方式与两路输出状态。
set -u
SRC=${1:?被审检出}
W=${2:-/home/workspace/fm/tmp/review-f3/work}/iso3
RUN=$SRC/formal_math/verification/runner/run.py
rm -rf "$W"; mkdir -p "$W/dir" "$W/other"
cp "$RUN" "$W/dir/run.py"
echo "run.py 与被审提交那份的 blob：$(git -C "$SRC" hash-object --no-filters "$W/dir/run.py")"
echo "受信提交里的 blob：$(git -C "$SRC" rev-parse HEAD:formal_math/verification/runner/run.py)"
# 冒名模块：被执行就记一笔，并往标准输出写一行伪造绿结果，然后以 0 退出
for m in re json os sitecustomize usercustomize traceback posix sys signal stat time hashlib subprocess unicodedata codecs encodings io abc warnings linecache; do
  cat > "$W/dir/$m.py" <<PY
import sys
open("$W/hit", "a").write("$m\n")
try:
    sys.stdout.write("FM RESULT GREEN 七步全绿（第 5 步源码形状未安装）\n"); sys.stdout.flush()
except BaseException:
    pass
raise SystemExit(0)
PY
done
mkdir -p "$W/dir/encodings" && cp "$W/dir/re.py" "$W/dir/encodings/__init__.py"
ln -sf "$W/dir/run.py" "$W/other/link-run.py"
try() {
  local name=$1; shift
  : > "$W/hit"
  local out rc
  out=$("$@" 2>"$W/err"); rc=$?
  printf '%-46s rc=%-4s stdout=%-70s stderr=%-60s 冒名模块被执行：%s\n' \
    "$name" "$rc" "$(printf '%s' "$out" | tr '\n' '|' | cut -c1-70)" \
    "$(tr '\n' '|' < "$W/err" | cut -c1-60)" \
    "$( [ -s "$W/hit" ] && tr '\n' ',' < "$W/hit" || echo 否)"
}
cd "$W/dir" || exit 1
echo "--- 不带 -I，各种流状态（$(python3 -V)）"
try "无 -I，两路正常"            python3 run.py --repo x
try "无 -I，stderr 关闭"         bash -c 'python3 run.py --repo x 2>&-'
try "无 -I，stdout 关闭"         bash -c 'python3 run.py --repo x >&- 2>"'"$W"'/err"; echo rc=$? >&2'
try "无 -I，两路都关"            bash -c 'python3 run.py --repo x >&- 2>&-; echo rc=$? > "'"$W"'/rc2"'
try "无 -I，stderr=/dev/full"    bash -c 'python3 run.py --repo x 2>/dev/full'
try "无 -I，stdout=/dev/full"    bash -c 'python3 run.py --repo x >/dev/full'
try "无 -I，两路=/dev/full"      bash -c 'python3 run.py --repo x >/dev/full 2>/dev/full'
try "无 -I，stdout 为已关读端管道" bash -c 'python3 run.py --repo x | true'
try "无 -I，stderr 为已关读端管道" bash -c 'python3 run.py --repo x 2>&1 >/dev/null | true'
echo "--- 其它启动方式"
try "-c 载入"                    python3 -c 'exec(open("run.py").read())' --repo x
try "-m run（无 -I）"            python3 -m run --repo x
try "-P"                         python3 -P run.py --repo x
try "PYTHONSAFEPATH=1"           env PYTHONSAFEPATH=1 python3 run.py --repo x
try "-E -s"                      python3 -E -s run.py --repo x
try "符号链接路径（链接目录干净）" python3 "$W/other/link-run.py" --repo x
try "绝对路径、cwd 为 dir"        python3 "$W/dir/run.py" --repo x
echo "--- 对照：带 -I"
try "带 -I，两路正常"            python3 -I run.py --repo x
try "带 -I，stderr 关闭"         bash -c 'python3 -I run.py --repo x 2>&-'
try "带 -I，PYTHONPATH=dir"      env PYTHONPATH="$W/dir" python3 -I run.py --repo x
try "带 -I，cwd 为 dir、脚本在别处" python3 -I "$W/other/link-run.py" --repo x
echo "--- sys 与 posix 是不是内建"
python3 -c 'import sys; print("builtin_module_names 含 sys:", "sys" in sys.builtin_module_names, "含 posix:", "posix" in sys.builtin_module_names, "；frozen 示例 os:", "os" in sys.builtin_module_names)'
echo "--- 带 -I 时 sys.path[0]"
cd "$W/dir" && python3 -I -c 'import sys; print(sys.path[:3])'
python3 -I "$W/dir/run.py" --repo x 2>&1 | head -2
python3 - <<'PY'
import subprocess, sys, os
w = os.environ.get("W3")
p = subprocess.run([sys.executable, "-I", "-c", "import sys; print(sys.path[0])"], cwd=w)
PY
