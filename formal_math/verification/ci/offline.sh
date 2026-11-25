#!/usr/bin/env bash
# 用法：offline.sh <命令...>
#
# 在无网络、无凭据的 bwrap 沙箱里运行命令（#2315；要求来自 #2312 第四轮审阅：Lean 精化本身会执行代码，
# 源码白名单只是前置防线）。布局照 Lake 4.36.0 `Lake/CLI/Check.lean` 的 `buildSandboxArgs`：
#
#   - 根目录只读，`/home`、`/root`、`/run`、`/var`、`/tmp` 换成空 tmpfs（runner 的 `.credentials`、
#     `_temp` 下的事件文件、其他检出都看不见）；
#   - 只回绑仓库（只读）、`formal_math/.lake`（可写，构建产物与依赖）、elan 工具链（只读）；
#   - `--unshare-all` 拆掉网络、IPC、PID 等命名空间，`--clearenv` 清空环境变量，只放回下面列出的几项，
#     `GITHUB_TOKEN`、`ACTIONS_*` 一类即使存在也进不来；
#   - `--die-with-parent`、`--new-session`：父进程退出即收尸，子进程拿不到控制终端。
#
# 可选环境变量：
#   FM_OFFLINE_EXTRA_RO   以冒号分隔的额外只读路径（SafeCode 本机实测时用来回绑 `.lake/packages`
#                         的符号链接目标；CI 上依赖是 `.lake` 里的实体目录，不需要）
#   FM_OFFLINE_EXTRA_RW   以冒号分隔的额外可写路径
#   FM_OFFLINE_DRYRUN=1   只打印 bwrap 命令行
set -euo pipefail

[ "$#" -gt 0 ] || { echo "用法：offline.sh <命令...>" >&2; exit 2; }

repo=$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
lake_dir=$repo/formal_math/.lake
elan_home=${ELAN_HOME:-$HOME/.elan}
bwrap=${FM_BWRAP:-bwrap}

command -v "$bwrap" >/dev/null || { echo "offline.sh: 找不到 bwrap" >&2; exit 2; }
[ -d "$lake_dir" ] || { echo "offline.sh: $lake_dir 不存在，先在联网阶段取依赖" >&2; exit 2; }
[ -d "$elan_home" ] || { echo "offline.sh: $elan_home 不存在" >&2; exit 2; }

args=(
  --ro-bind / /
  --tmpfs /home --tmpfs /root --tmpfs /run --tmpfs /var --tmpfs /tmp
  --dir /tmp/home
  --dev /dev --proc /proc
  --ro-bind "$repo" "$repo"
  --bind "$lake_dir" "$lake_dir"
  --ro-bind "$elan_home" "$elan_home"
)
# git 工作树（`git worktree add`）的元数据在主仓库的 .git 里，不在检出目录下；只读回绑，门 6b 要读它。
common=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)
case "$common" in "$repo"/*) ;; *) args+=(--ro-bind "$common" "$common") ;; esac
IFS=: read -r -a extra_ro <<<"${FM_OFFLINE_EXTRA_RO:-}"
for p in "${extra_ro[@]}"; do [ -n "$p" ] && args+=(--ro-bind "$p" "$p"); done
IFS=: read -r -a extra_rw <<<"${FM_OFFLINE_EXTRA_RW:-}"
for p in "${extra_rw[@]}"; do [ -n "$p" ] && args+=(--bind "$p" "$p"); done

args+=(--clearenv
  --setenv HOME /tmp/home
  --setenv TMPDIR /tmp
  --setenv PATH "$elan_home/bin:/usr/local/bin:/usr/bin:/bin"
  --setenv ELAN_HOME "$elan_home"
  --setenv LANG C.UTF-8
  --setenv PYTHONDONTWRITEBYTECODE 1)
# 门 6b 在分离检出时靠它取分支名；它只是分支名，不是凭据。
for name in GITHUB_HEAD_REF GITHUB_BASE_REF GITHUB_ACTIONS CI LEAN_NUM_THREADS; do
  if [ -n "${!name:-}" ]; then args+=(--setenv "$name" "${!name}"); fi
done
args+=(--unshare-all --die-with-parent --new-session --chdir "$repo" -- "$@")

if [ "${FM_OFFLINE_DRYRUN:-0}" = 1 ]; then
  printf '%q ' "$bwrap" "${args[@]}"; echo
  exit 0
fi
exec "$bwrap" "${args[@]}"
