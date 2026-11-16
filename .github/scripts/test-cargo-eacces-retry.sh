#!/usr/bin/env bash
# #2066：cargo-eacces-retry.sh 的删脚本重试与删除范围。假 cargo：被拒文件带 .bad 标记时按 cargo 原样格式报 EACCES，
#   文件缺失时「重编」出好文件并成功。删除只许落在 CARGO_TARGET_DIR 真实路径下、紧跟 os error 13 的那个构建脚本。
set -u
S="$(cd "$(dirname "$0")" && pwd)/cargo-eacces-retry.sh"
W="$(realpath -e "$(mktemp -d)")"; trap 'rm -rf "$W"' EXIT
pass=0; fail=0
ok() { if eval "$2"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $1" >&2; fi; }
cat >"$W/fake" <<'F'
#!/usr/bin/env bash
# 用法：fake <被拒脚本> [同一日志里因 ENOENT never executed 的另一脚本]
f="$1"; echo call >>"$W_CALLS"
if [[ ! -e "$f" ]]; then mkdir -p "$(dirname "$f")"; : >"$f"; echo "Compiling x"; exit 0; fi
if [[ -e "$f.bad" ]]; then
  if [[ -n "${2:-}" ]]; then
    echo "error: failed to run custom build command for \`y\`"; echo "Caused by:"
    echo "  could not execute process \`$2\` (never executed)"; echo "Caused by:"; echo "  No such file or directory (os error 2)"
  fi
  echo "error: failed to run custom build command for \`x\`"; echo "Caused by:"
  echo "  could not execute process \`$f\` (never executed)"; echo "Caused by:"; echo "  Permission denied (os error 13)"; exit 101
fi
echo ok; exit 0
F
chmod +x "$W/fake"
go() { : >"$W/calls"; out=$(cd "$W" && W_CALLS="$W/calls" "$S" "$W/fake" "$@" 2>&1 </dev/null); rc=$?; calls=$(wc -l <"$W/calls"); }
mkbad() { mkdir -p "$(dirname "$1")"; : >"$1"; : >"$1.bad"; }
export CARGO_TARGET_DIR="$W/target"; mkdir -p "$CARGO_TARGET_DIR"

# 1 target 下粘性 EACCES：删掉被拒脚本与同目录 build_script_build-*，重编后成功
d="$CARGO_TARGET_DIR/debug/build/zmij-776859aea9499a21"; f="$d/build-script-build"; mkbad "$f"; : >"$d/build_script_build-776859aea9499a21"
go "$f"
ok "sticky EACCES recovers" '[[ $rc -eq 0 && $calls -eq 2 ]]'
ok "marker printed" '[[ "$out" == *"::warning title=Boat transient cargo error retry::cause=EACCES"* ]]'
ok "rejected file and hashed sibling removed" '[[ "$out" == *"removed rejected build script: $f"* && ! -e "$d/build_script_build-776859aea9499a21" ]]'
# 2 同形路径但在 target 根外：不删，原地重跑仍失败
f="$W/elsewhere/debug/build/serde-d86abc301256d089/build-script-build"; mkbad "$f"
go "$f"
ok "outside target kept" '[[ -e "$f" && $rc -eq 101 && $calls -eq 2 && "$out" != *"removed rejected build script:"* ]]'
# 3 target 内但更高一级祖先是符号链接（target/release -> 外部目录）：不删
mkdir -p "$W/outside/build/quote-3884a4293a159004"; ln -s "$W/outside" "$CARGO_TARGET_DIR/release"
f="$CARGO_TARGET_DIR/release/build/quote-3884a4293a159004/build-script-build"; : >"$f"; : >"$f.bad"
go "$f"
ok "ancestor symlink kept" '[[ -e "$W/outside/build/quote-3884a4293a159004/build-script-build" && $rc -eq 101 && "$out" != *"removed rejected build script:"* ]]'
# 4 crate 目录本身是符号链接：不删
mkdir -p "$W/outside2" "$CARGO_TARGET_DIR/debug/build"; : >"$W/outside2/build-script-build"; : >"$W/outside2/build-script-build.bad"
ln -s "$W/outside2" "$CARGO_TARGET_DIR/debug/build/syn-0123456789abcdef"
go "$CARGO_TARGET_DIR/debug/build/syn-0123456789abcdef/build-script-build"
ok "crate dir symlink kept" '[[ -e "$W/outside2/build-script-build" && $rc -eq 101 ]]'
# 5 同一日志里另一脚本因 ENOENT never executed：只删 EACCES 的那个
d="$CARGO_TARGET_DIR/debug/build/libc-1111111111111111"; f="$d/build-script-build"; mkbad "$f"
e="$CARGO_TARGET_DIR/debug/build/proc-2222222222222222/build-script-build"; mkdir -p "$(dirname "$e")"; : >"$e"
go "$f" "$e"
ok "ENOENT sibling kept, EACCES one removed" '[[ -e "$e" && $rc -eq 0 && "$out" == *"removed rejected build script: $f"* && "$out" != *"removed rejected build script: $e"* ]]'
# 6 路径不符（无 16 位 hash）：不删，原地重跑一次
f="$CARGO_TARGET_DIR/debug/build/weird/build-script-build"; mkbad "$f"
go "$f"
ok "nonmatching path kept" '[[ -e "$f" && $rc -eq 101 && $calls -eq 2 ]]'
# 7 被拒文件本身是符号链接：不删链接目标
d="$CARGO_TARGET_DIR/debug/build/itoa-3333333333333333"; mkdir -p "$d"; : >"$W/real"; ln -s "$W/real" "$d/build-script-build"; : >"$d/build-script-build.bad"
go "$d/build-script-build"
ok "symlinked script kept" '[[ -L "$d/build-script-build" && -e "$W/real" && $rc -eq 101 ]]'
# 8 target 根不存在：不删
f="$CARGO_TARGET_DIR/debug/build/ryu-4444444444444444/build-script-build"; mkbad "$f"
CARGO_TARGET_DIR="$W/no-such-target" go "$f"
ok "missing target root keeps file" '[[ -e "$f" && $rc -eq 101 ]]'
# 9 非 EACCES 失败：不重试；10 成功：一次、无标记
cat >"$W/boom" <<'F'
#!/usr/bin/env bash
echo call >>"$W_CALLS"; echo "test failed"; exit 7
F
chmod +x "$W/boom"; : >"$W/calls"; out=$(W_CALLS="$W/calls" "$S" "$W/boom" 2>&1 </dev/null); rc=$?
ok "other failure not retried, code kept" '[[ $rc -eq 7 && $(wc -l <"$W/calls") -eq 1 && "$out" != *warning* ]]'
f="$CARGO_TARGET_DIR/debug/build/serde-5555555555555555/build-script-build"; mkdir -p "$(dirname "$f")"; : >"$f"
go "$f"
ok "success single call" '[[ $rc -eq 0 && $calls -eq 1 && "$out" != *warning* ]]'
echo "cargo-eacces-retry delete tests: pass=$pass fail=$fail"
(( fail == 0 ))
