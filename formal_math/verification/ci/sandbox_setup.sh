#!/usr/bin/env bash
# CI 用：装 bubblewrap，放开非特权用户命名空间，再用探针确认 bwrap 能拆网络。
# ubuntu-24.04 托管 runner 默认 kernel.apparmor_restrict_unprivileged_userns=1；
# 本仓 #2071（hillclimb/isolation-apparmor-absent）在隔离与 AppArmor 上出过问题，所以探针失败即红，
# 不退回无沙箱运行。
set -euo pipefail
if ! command -v bwrap >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq bubblewrap
fi
bwrap --version
for f in kernel/apparmor_restrict_unprivileged_userns kernel/unprivileged_userns_clone user/max_user_namespaces; do
  [ -r "/proc/sys/$f" ] && echo "$f=$(cat "/proc/sys/$f")"
done
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = 1 ]; then
  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
fi
# 探针：沙箱里只有回环接口，连不出去。
bwrap --ro-bind / / --dev /dev --proc /proc --unshare-all --die-with-parent -- \
  sh -c 'if command -v curl >/dev/null && curl -sS -m 5 -o /dev/null https://github.com 2>/dev/null; then
           echo "沙箱里仍能联网" >&2; exit 1; fi; cat /proc/net/dev'
echo "bwrap 探针通过：--unshare-all 可用，沙箱内无网络"
