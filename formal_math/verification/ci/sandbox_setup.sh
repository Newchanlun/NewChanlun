#!/usr/bin/env bash
# CI 用：确认 bubblewrap 可用，在必要时放开非特权用户命名空间，并用断网探针验证 --unshare-all。
# 探针失败即红，绝不退回无沙箱运行。
# 本文件在仓内保持 100644 模式（precheck.py 要求），一律以 `bash sandbox_setup.sh` 调用。
set -euo pipefail

if ! command -v bwrap >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq bubblewrap
fi

bwrap --version
for f in kernel/apparmor_restrict_unprivileged_userns kernel/unprivileged_userns_clone user/max_user_namespaces; do
  if [ -r "/proc/sys/$f" ]; then
    printf '%s=%s\n' "$f" "$(cat "/proc/sys/$f")"
  fi
done

if ! bwrap --ro-bind / / --dev /dev --proc /proc --unshare-all --die-with-parent --new-session -- /bin/true 2>/dev/null; then
  if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = 1 ]; then
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
  fi
fi

# 断网 + 清环境探针：沙箱内不得存在除 lo 之外的接口，且无法连通外网，也不得继承外部凭据变量。
FM_SANDBOX_PROBE_SECRET=must-not-leak \
bwrap --ro-bind / / --tmpfs /home --tmpfs /root --tmpfs /run --tmpfs /var --tmpfs /tmp \
  --dir /tmp/home --dev /dev --proc /proc --clearenv \
  --setenv HOME /tmp/home --setenv TMPDIR /tmp --setenv PATH /usr/bin:/bin \
  --unshare-all --die-with-parent --new-session -- \
  /bin/sh -eu -c '
    if [ -n "${FM_SANDBOX_PROBE_SECRET:-}" ]; then
      echo "sandbox_setup.sh: 环境变量泄漏进沙箱" >&2
      exit 1
    fi
    if command -v curl >/dev/null 2>&1 && curl -sS -m 5 -o /dev/null https://github.com 2>/dev/null; then
      echo "sandbox_setup.sh: 沙箱内仍能联网" >&2
      exit 1
    fi
    non_lo=$(awk "NR>2 {gsub(/:/, \"\", \$1); if (\$1 != \"lo\") print \$1}" /proc/net/dev)
    if [ -n "$non_lo" ]; then
      echo "sandbox_setup.sh: 沙箱内出现非回环网卡: $non_lo" >&2
      exit 1
    fi
    cat /proc/net/dev
  '

echo "bwrap 探针通过：--unshare-all、--clearenv 可用，沙箱内无网络"
