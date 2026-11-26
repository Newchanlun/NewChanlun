#!/usr/bin/env bash
# 门 4（内核重放与公理闭包）：在独立干净目录中离线运行 Lake 4.36.0 `lake check`。
#
# 要求落实（#2315 评论 7176006564 第 3、5 条）：
#   - 只从 git 原始对象取料（基线三配置 + 被审内容 .lean），绝不复用 run.py 的 audited/ 或工作树；
#   - 依赖目录经 COMPARATOR_BWRAP 严格只读挂载（--ro-bind），且剥除 --share-net 保持全程断网；
#   - PR 门与主干门都会调用本脚本（`--paranoid` 仅在手动 paranoid 作业中传）。
# 本文件在仓内保持 100644 模式，一律以 `bash run_lake_check.sh ...` 调用。
set -euo pipefail

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONUSERBASE

repo=""
base=""
head=""
packages=""
paranoid=0
timeout_sec=3600
log_file=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) repo=${2:?}; shift 2 ;;
    --base) base=${2:?}; shift 2 ;;
    --head) head=${2:?}; shift 2 ;;
    --packages) packages=${2:?}; shift 2 ;;
    --paranoid) paranoid=1; shift ;;
    --timeout-sec) timeout_sec=${2:?}; shift 2 ;;
    --log) log_file=${2:?}; shift 2 ;;
    *) echo "run_lake_check.sh: 未知参数: $1" >&2; exit 2 ;;
  esac
done

[ -n "$repo" ] && [ -n "$base" ] && [ -n "$head" ] && [ -n "$packages" ] || {
  echo "用法：bash run_lake_check.sh --repo <仓库> --base <基线> --head <被审> --packages <只读依赖目录> [--paranoid] [--timeout-sec <秒>] [--log <文件>]" >&2
  exit 2
}
[ -d "$packages" ] || { echo "run_lake_check.sh: 依赖目录不存在: $packages" >&2; exit 2; }

here=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fm-lake-check-XXXXXX")
trap 'chmod -R u+w -- "$work" 2>/dev/null || true; rm -rf -- "$work"' EXIT

proj=$work/proj
bwrap_wrap=$work/bwrap_check.sh

python3 -I "$here/materialize.py" audited \
  --repo "$repo" --base "$base" --head "$head" --out "$proj" >/dev/null

# 核对工具链与基线 lean-toolchain 一致
want_tc=$(tr -d '\r\n' < "$proj/lean-toolchain")
want_ver=${want_tc#leanprover/lean4:v}
if [ "$want_ver" = "$want_tc" ] || [ -z "$want_ver" ]; then
  echo "run_lake_check.sh: 基线 lean-toolchain 格式不合: $want_tc" >&2
  exit 2
fi
actual_ver=$(cd "$proj" && lean --version)
case "$actual_ver" in
  "Lean (version ${want_ver},"*) ;;
  *)
    echo "run_lake_check.sh: 运行中 Lean ($actual_ver) 与基线工具链 v$want_ver 不符" >&2
    exit 2
    ;;
esac

bash "$here/bwrap_pkgbind.sh" \
  --emit "$bwrap_wrap" \
  --lake-dir "$proj/.lake" \
  --packages "$packages" \
  --offline

cmd=(lake check)
if [ "$paranoid" = 1 ]; then
  cmd+=(--paranoid)
fi

run_cmd() {
  if [ -x /usr/bin/time ]; then
    (cd "$proj" && COMPARATOR_BWRAP="$bwrap_wrap" timeout --signal=TERM --kill-after=30 "$timeout_sec" /usr/bin/time -v "${cmd[@]}")
  else
    (cd "$proj" && COMPARATOR_BWRAP="$bwrap_wrap" timeout --signal=TERM --kill-after=30 "$timeout_sec" "${cmd[@]}")
  fi
}

rc=0
if [ -n "$log_file" ]; then
  mkdir -p -- "$(dirname -- "$log_file")"
  run_cmd >"$log_file" 2>&1 || rc=$?
  cat "$log_file"
else
  run_cmd || rc=$?
fi

# 纵深防御：宿主机挂载点 .lake/packages 必须仍为空目录（依赖只读绑定生效、未往宿主机落盘）。
if [ -n "$(ls -A "$proj/.lake/packages" 2>/dev/null || true)" ]; then
  echo "run_lake_check.sh: 异常：宿主机 .lake/packages 挂载点非空" >&2
  exit 2
fi

exit "$rc"
