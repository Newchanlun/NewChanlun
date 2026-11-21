#!/usr/bin/env bash
# #1608：执行 #1394 的两个编译负例，断言它们仍然「编译失败，且失败在负例块本身」。
# 负例只在 `--cfg` 打开时编译，普通构建和 cargo test 都不会碰到；没有本入口时，负例是否仍被拒绝无人检查。
# 判据：rustc 退出非 0；至少一条 error；每条 error 的编号都在该负例允许的集合内（默认 E0308），且落在负例块（cfg 行起 20 行内）。
# #1890：只读快照负例另允许 E0599（无此方法）、E0616（私有字段）；白名单负例只允许 E0451（私有字段构造），
#   并要求错误条数恰好等于负例行数（第 5 参数），防止一行被拒就掩盖其余几行意外编译通过。
# #1426：check 新增第 6 参数指定 cargo 目标参数（默认不变：`--features s_session --bin s_structure_session`）、
#   第 7 参数可选精确匹配无码错误（默认空，原行为不变），并新增 `--test trend_formation_1426` 五结构体完整字面量
#   拒绝负例（5 条 E0451 + 1 条私有类型 `trend_formation::Chain` 无码错误），以及形成凭据与归属的类型负例。
# 任一不满足即失败：负例意外编译通过，或因别处的无关错误失败，都不能当作「边界仍然拒绝」。
# 用法：在 rust/ 目录下运行：`check-compile-negatives-1394.sh [all|s_session|default]`（默认 all）。
set -uo pipefail

check() {
  local cfg="$1" file="$2" test_flag="$3" codes="${4:-E0308}" expected="${5:-}" target_args="${6:---features s_session --bin s_structure_session}" extra_re="${7:-}"
  local start
  start=$(grep -n "${cfg})" "$file" | grep -m1 '#\[cfg' | cut -d: -f1)
  if [ -z "$start" ]; then
    echo "FAIL ${cfg}: ${file} 中找不到 #[cfg(...${cfg}...)]"; return 1
  fi
  local out rc
  # shellcheck disable=SC2086
  out=$(cargo rustc --locked ${target_args} -- ${test_flag} --cfg "$cfg" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "FAIL ${cfg}: 负例编译通过，类型边界不再拒绝旧写法"; return 1
  fi
  local errors locations allow_re
  errors=$(printf '%s\n' "$out" | grep -E '^error(\[E[0-9]+\])?: ' | grep -v '^error: could not compile' || true)
  if [ -z "$errors" ]; then
    printf '%s\n' "$out" | tail -40
    echo "FAIL ${cfg}: rustc 失败但没有编译错误（rc=${rc}）"; return 1
  fi
  if [ -n "$extra_re" ]; then
    allow_re="^error(\[(${codes})\]: |: ${extra_re})"
  else
    allow_re="^error\[(${codes})\]: "
  fi
  if printf '%s\n' "$errors" | grep -qvE "$allow_re"; then
    printf '%s\n' "$out" | tail -60
    echo "FAIL ${cfg}: 出现 ${codes} 以外的错误，不能证明是负例本身被拒"; return 1
  fi
  locations=$(printf '%s\n' "$out" | grep -A1 -E "$allow_re" | grep -E '^ *--> ' | sed -E 's/^ *--> //')
  local loc path line
  while IFS= read -r loc; do
    path=${loc%%:*}; line=$(printf '%s' "$loc" | cut -d: -f2)
    if [ "$path" != "$file" ] || [ "$line" -lt "$start" ] || [ "$line" -gt $((start + 20)) ]; then
      printf '%s\n' "$out" | tail -60
      echo "FAIL ${cfg}: 错误位置 ${loc} 不在负例块 ${file}:${start}+20 内"; return 1
    fi
  done <<< "$locations"
  local count extra_count=0
  count=$(printf '%s\n' "$errors" | wc -l | tr -d ' ')
  if [ -n "$extra_re" ]; then
    extra_count=$(printf '%s\n' "$errors" | grep -cE "^error: $extra_re" || true)
    if [ "$extra_count" -ne 1 ] || [ "$(printf '%s\n' "$locations" | grep -c .)" -ne "$count" ]; then
      printf '%s\n' "$out" | tail -80
      echo "FAIL $cfg: 必须恰有 1 条私有类型错误，且每条错误都须有负例块内的位置"; return 1
    fi
  fi
  if [ -n "$expected" ] && [ "$count" != "$expected" ]; then
    printf '%s\n' "$out" | tail -80
    echo "FAIL ${cfg}: 期望 ${expected} 条错误，实际 ${count} 条"; return 1
  fi
  if [ -n "$extra_re" ]; then
    echo "PASS ${cfg}: rc=${rc}，$((count - extra_count)) 条 ${codes} + ${extra_count} 条私有类型错误，均在 ${file}:${start}+20 内"
  else
    echo "PASS ${cfg}: rc=${rc}，${count} 条 ${codes}，均在 ${file}:${start}+20 内"
  fi
}

suite="${1:-all}"
status=0
case "$suite" in
  all|s_session)
    check issue1394_capture_callback_refusal src/bin/s_session_v2/content_store.rs --test || status=1
    check issue1394_closed_owner_refusal src/bin/s_session_v3/audit_store.rs "" || status=1
    check issue1890_read_snapshot_refusal src/bin/s_session_v3/history.rs "" "E0308|E0599|E0616" 9 || status=1
    check issue1890_snapshot_query_refusal src/bin/s_session_v3/history.rs "" "E0451" 1 || status=1
    ;;
  default)
    ;;
  *)
    echo "usage: $0 [all|s_session|default]" >&2
    exit 64
    ;;
esac

case "$suite" in
  all|default)
    check issue1426_formation_type_refusal tests/trend_formation_1426.rs "" "E0308|E0061" 4 "--test trend_formation_1426" || status=1
    check issue1426_fabricated_evidence_refusal tests/trend_formation_1426.rs "" "E0451" 6 "--test trend_formation_1426" 'type `trend_formation::Chain` is private$' || status=1
    ;;
esac
exit $status
