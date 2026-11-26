#!/usr/bin/env bash
# 隔离模式检查之前与各种启动方式（不调用 lean、lake）。参数：被审检出根目录。
SRC=${1:?用法：case_isolated.sh <被审检出>}
RUN=$SRC/formal_math/verification/runner/run.py
T=$(mktemp -d "${TMPDIR:-/tmp}/rf2-iso-XXXXXX")
mkdir "$T/evil" "$T/copy" "$T/link"
cp "$RUN" "$T/copy/run.py"
for m in json os re hashlib subprocess time unicodedata sitecustomize usercustomize encodings; do
  printf 'open(%s, "a").write("%s\\n")\nimport sys\nsys.stdout.write("FM RESULT GREEN forged\\n")\nraise SystemExit(0)\n' "'$T/ran'" "$m" > "$T/copy/$m.py"
  cp "$T/copy/$m.py" "$T/evil/$m.py"
  cp "$T/copy/$m.py" "$T/link/$m.py"
done
rm "$T/evil/encodings.py" "$T/copy/encodings.py" "$T/link/encodings.py"
printf 'open("%s", "a").write("startup\\n")\n' "$T/ran" > "$T/startup.py"
printf 'import os; open("%s", "a").write("pth\\n")\n' "$T/ran" > "$T/evil/x.pth"
ln -s "$RUN" "$T/link/run.py"
t() { # 标签 命令…
  local label=$1; shift
  rm -f "$T/ran"
  out=$("$@" 2>"$T/err"); rc=$?
  printf '%-58s rc=%s | out: %s | err: %s | 顶替模块被执行: %s\n' "$label" "$rc" "$(printf '%s' "$out" | head -c 200 | tr '\n' '|')" \
    "$(head -c 200 "$T/err" | tr '\n' '|')" "$( [ -e "$T/ran" ] && tr '\n' ',' < "$T/ran" || echo 否)"
}
cd "$T"
t "不带 -I，同目录有 json.py 等"                 python3 copy/run.py --repo x
t "-E -s（不是 -I）"                              python3 -E -s copy/run.py --repo x
t "-P（安全路径，不是 -I）"                       python3 -P copy/run.py --repo x
t "-I，同目录有 json.py 等"                       python3 -I copy/run.py --repo x
t "-I，PYTHONPATH 指向顶替目录"                   env PYTHONPATH="$T/evil" python3 -I copy/run.py --repo x
t "-I，PYTHONSTARTUP"                             env PYTHONSTARTUP="$T/startup.py" python3 -I copy/run.py --repo x
t "-I，PYTHONHOME 无效值"                         env PYTHONHOME="$T/evil" python3 -I copy/run.py --repo x
t "-I，经符号链接（链接目录里有 json.py）"        python3 -I link/run.py --repo x
t "-I，相对路径、当前目录有 json.py"              sh -c "cd '$T/copy' && exec python3 -I run.py --repo x"
t "-I -m run（当前目录是 runner 副本）"           sh -c "cd '$T/copy' && exec python3 -I -m run --repo x"
t "不带 -I 的 -m run"                             sh -c "cd '$T/copy' && exec python3 -m run --repo x"
t "-I，脚本从标准输入读"                          sh -c "exec python3 -I - --repo x < '$RUN'"
t "不带 -I，PYTHONPATH 指向顶替目录"              env PYTHONPATH="$T/evil" python3 copy/run.py --repo x
t "不带 -I，PYTHONSAFEPATH=1"                     env PYTHONSAFEPATH=1 python3 copy/run.py --repo x
echo "--- 不带 -I 时两路输出各种状态下的退出码（说明：NOT_ISOLATED 退 2）"
python3 copy/run.py --repo x >&- 2>"$T/err";  echo "标准输出已关闭            rc=$? | err: $(head -c 300 "$T/err" | tr '\n' '|')"
python3 copy/run.py --repo x 2>&- >"$T/out";  echo "标准错误已关闭            rc=$? | out: $(head -c 300 "$T/out" | tr '\n' '|')"
python3 copy/run.py --repo x >/dev/full 2>"$T/err"; echo "标准输出指向 /dev/full    rc=$? | err: $(head -c 300 "$T/err" | tr '\n' '|')"
python3 copy/run.py --repo x 2>/dev/full >"$T/out"; echo "标准错误指向 /dev/full    rc=$? | out: $(head -c 300 "$T/out" | tr '\n' '|')"
env PYTHONIOENCODING=ascii python3 copy/run.py --repo x >"$T/out" 2>"$T/err"; echo "PYTHONIOENCODING=ascii    rc=$? | out: $(tr '\n' '|' < "$T/out") | err: $(head -c 300 "$T/err" | tr '\n' '|')"
env LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0 python3 copy/run.py --repo x >"$T/out" 2>"$T/err"; echo "C 区域、关掉 UTF-8 模式    rc=$? | out: $(tr '\n' '|' < "$T/out") | err: $(head -c 300 "$T/err" | tr '\n' '|')"
echo "--- 带 -I 时参数错误（USAGE）在两路输出各种状态下的退出码"
python3 -I copy/run.py --repo x >&- 2>"$T/err";  echo "标准输出已关闭            rc=$? | err: $(head -c 300 "$T/err" | tr '\n' '|')"
python3 -I copy/run.py --repo x 2>&- >"$T/out";  echo "标准错误已关闭            rc=$? | out: $(head -c 300 "$T/out" | tr '\n' '|')"
python3 -I copy/run.py --repo x >/dev/full 2>"$T/err"; echo "标准输出指向 /dev/full    rc=$? | err: $(head -c 300 "$T/err" | tr '\n' '|')"
python3 -I copy/run.py --repo x <&- >&- 2>&-; echo "三路全关                  rc=$?"
rm -rf "$T"
