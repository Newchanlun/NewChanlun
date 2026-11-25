#!/usr/bin/env bash
# 用法：comparator.sh
#
# 主干门的 comparator 一步（#2315）。依次：
#   1. 样板自检（`ci/comparator/`，Lean 源存为 `*.lean.in`：run_gates.py 会把 formal_math/ 下所有 `.lean`
#      当包源码审，样板放不进去；这里复制到 formal_math/.lake/fm-comparator-sample/ 再改回 `.lean`）：绿样本须退 0；`definition_names` 留空的对照须退 1；
#      把锁定定义填进 `definition_names` 的必红样本记录 Lake 的实际退出码——Lake 4.36.0 接受它
#      （SafeCode 实测退 0，见 README），这正是门 5 必须拒收非空 `definition_names` 的依据。
#      若哪天 Lake 改为拒收，本步报出来，提醒回头复核门 5 的依据，但不判红。
#   2. 正式配置 `formal_math/comparator.json`：存在时先拒收非空 `definition_names`（门 5 的这一条），
#      再跑 `lake comparator`；不存在时（ChanChallenge 尚未落地）跳过并说明。
#
# `lake comparator` 自己用 bwrap 隔离构建、导出与内核（`--unshare-all`；只有依赖解析一步放网络），
# 所以这里不再套 offline.sh：嵌套 bwrap 的读数见 README。
set -uo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
sample=$repo/formal_math/.lake/fm-comparator-sample
status=0

rm -rf -- "$sample"
mkdir -p -- "$sample/Sample"
cp -- "$here"/comparator/lakefile.toml "$here"/comparator/lean-toolchain "$here"/comparator/*.json "$sample/"
for f in "$here"/comparator/Sample/*.lean.in; do
  cp -- "$f" "$sample/Sample/$(basename -- "${f%.in}")"
done

run() { # 名称 期望退出码 目录 配置
  local name=$1 want=$2 dir=$3 cfg=$4 rc
  echo "::group::lake comparator $name"
  (cd "$dir" && lake comparator --config "$cfg")
  rc=$?
  echo "::endgroup::"
  echo "$name: 退出 $rc（期望 $want）"
  if [ "$want" = record ]; then
    if [ "$rc" = 0 ]; then
      echo "$name: Lake 接受了填进 definition_names 的锁定定义被替换——门 5 必须拒收非空 definition_names。"
    else
      echo "::warning::$name: Lake 这次拒收了（退出 $rc），与 README 的实测读数不符，请复核门 5 的依据。"
    fi
  elif [ "$rc" != "$want" ]; then
    echo "::error::$name: 退出 $rc，期望 $want"
    status=1
  fi
}

(cd "$sample" && lake build) || { echo "::error::样板构建失败"; exit 1; }
run sample-green 0 "$sample" comparator.json
run defhole-control 1 "$sample" comparator-defhole-control.json
run defhole-filled record "$sample" comparator-defhole.json

cfg=$repo/formal_math/comparator.json
if [ -f "$cfg" ]; then
  if ! python3 - "$cfg" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
names = cfg.get("definition_names") or []
if names:
    print(f"::error::门 5：comparator.json 的 definition_names 必须为空，现有 {names}")
    sys.exit(1)
PY
  then
    status=1
  else
    run formal 0 "$repo/formal_math" comparator.json
  fi
else
  echo "formal_math/comparator.json 不存在（ChanChallenge 未落地），正式比对跳过。"
fi
exit "$status"
