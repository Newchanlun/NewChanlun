#!/usr/bin/env bash
set -uo pipefail
# #1875：Boat 上偶发「刚编出的 build-script 执行被拒」（execve EACCES，cargo 报 never executed；3 次 / 约 800 作业，
#   3 台不同机器，与目录、挂载无关，见 /Volumes/AgentStorage/restart-20261107/slim/boat-eacces-report.md）。
# 用法：cargo-eacces-retry.sh <命令> [参数…]   原样执行命令（stdout+stderr 合并输出），返回其退出码。
#   只有退出码非 0 且输出命中下面两种 Boat 偶发特征之一时，才把同一命令重跑一次，并打一行 ::warning（原因、主机名、路径）；
#   其余失败原样返回、不重试：
#   - EACCES：同时含「Permission denied (os error 13)」与「could not execute process `…/build-script-build` (never executed)」；
#   - EXDEV：rustc 写 rlib 时「failed to rename archive file: Invalid cross-device link (os error 18)」（同目录内 rename，
#     run 42650813920，近 60 轮 1 次；只认这一句，测试本身报 EXDEV 不重试）。
#   重跑的是整条命令：被包的是多阶段脚本（如 test-feature-delta.sh）时，EACCES 之前已跑完的阶段会再跑一遍，
#   只多花时间、结论不变（cargo 与测试是幂等的）。需要只看最后一次输出的调用方，以下面这行 ::warning 为分界。
if (( $# == 0 )); then echo "usage: $0 <command> [arg ...]" >&2; exit 64; fi
# 终端里手动跑（runbook）时不截获输出：保留 TTY 的进度条与颜色，也不需要 Boat 偶发重试。
if [[ -t 1 || -t 2 ]]; then exec "$@"; fi
# 截获输出用的临时文件建不出来（TMPDIR 不存在、只读、inode 用尽）时，退化为直接执行、不重试；
#   绝不因为本脚本自身失败而让命令不执行或把结论改成成功（#2025 独审）。
log="$(mktemp 2>/dev/null)" || exec "$@"
trap 'rm -f "$log"' EXIT
run() { "$@" 2>&1 | tee "$log"; return "${PIPESTATUS[0]}"; }
run "$@"; status=$?
cause=; denied_path=
if (( status != 0 )); then
  if grep -q 'Permission denied (os error 13)' "$log" \
      && grep -Eq 'could not execute process `[^`]*/build-script-build` \(never executed\)' "$log"; then
    denied_path="$(grep -Eo 'could not execute process `[^`]*/build-script-build`' "$log" | head -n 1 | sed -E 's/^could not execute process `(.*)`$/\1/')"
    cause="EACCES could not execute process \`${denied_path}\`"
  elif grep -Eq 'failed to rename archive file: Invalid cross-device link \(os error 18\)' "$log"; then
    cause="EXDEV $(grep -Eo 'failed to build archive at `[^`]*`' "$log" | head -n 1)"
  fi
fi
# EACCES 时先记下被拒文件与所在挂载的现场再重试（#1875：同机原地重试也失败过两次，给 Boat 反馈用具体证据）。
#   只读：不执行被拒的 build script（执行权限看 stat 的权限位与 findmnt 的 noexec 等挂载选项）。每条 timeout -k 1 5
#   （卡在不可中断 IO 的进程仍可能拖住，属已知残余），出错全部忽略，不改变命令结论与重试次数。
eacces_diag() {
  local path=$1 dir
  dir="$(dirname -- "$path")"
  echo "::group::Boat EACCES diagnostics ${path}"
  for c in "ls -l --full-time" "stat" "lsattr" "getfattr -d -m -" "fuser -v"; do
    echo "\$ $c"; timeout -k 1 5 $c "$path" 2>&1 | head -n 20
  done
  echo "\$ ls -ld; findmnt -T"; timeout -k 1 5 ls -ld --full-time "$dir" 2>&1; timeout -k 1 5 findmnt -T "$dir" 2>&1
  echo "\$ id"; id
  echo "\$ dmesg（只取权限拒绝相关行）"
  timeout -k 1 5 sudo -n dmesg 2>/dev/null | grep -Ei 'denied|apparmor|selinux|audit|exec|lsm|EACCES' | tail -n 20
  echo "::endgroup::"
}
if [[ "$cause" == EACCES* && -n "$denied_path" ]]; then
  eacces_diag "$denied_path" || true
fi
if [[ -n "$cause" ]]; then
  # 标记行格式是调用方的分界依据（run-1488-delta-ci.py RETRY_MARKER），改动须同步。
  echo "::warning title=Boat transient cargo error retry::cause=${cause} host=$(hostname)"
  run "$@"; status=$?
fi
exit "$status"
