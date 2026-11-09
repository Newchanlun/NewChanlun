#!/usr/bin/env bash
set -uo pipefail
# #1875：Boat 上偶发「刚编出的 build-script 执行被拒」（execve EACCES，cargo 报 never executed；3 次 / 约 800 作业，
#   3 台不同机器，与目录、挂载无关，见 /Volumes/AgentStorage/restart-20261107/slim/boat-eacces-report.md）。
# 用法：cargo-eacces-retry.sh <命令> [参数…]   原样执行命令（stdout+stderr 合并输出），返回其退出码。
#   只有退出码非 0 且输出同时含「Permission denied (os error 13)」与「could not execute process `…/build-script-build`
#   (never executed)」时，才把同一命令重跑一次，并打一行 ::warning（主机名与被拒路径）；其余失败原样返回、不重试。
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
if (( status != 0 )) && grep -q 'Permission denied (os error 13)' "$log" \
    && grep -Eq 'could not execute process `[^`]*/build-script-build` \(never executed\)' "$log"; then
  denied="$(grep -Eo 'could not execute process `[^`]*/build-script-build`' "$log" | head -n 1)"
  echo "::warning title=Boat build-script EACCES retry::host=$(hostname) ${denied}"
  run "$@"; status=$?
fi
exit "$status"
