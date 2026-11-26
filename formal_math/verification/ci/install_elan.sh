#!/usr/bin/env bash
# CI 用：安装钉选版本的 elan（发行包按 sha256 核对），工具链由 lean-toolchain 首次调用时拉取。
# 本文件在仓内保持 100644 模式（precheck.py 要求），一律以 `bash install_elan.sh` 调用。
# 环境变量 ELAN_VERSION、ELAN_SHA256 由工作流给出；缓存命中（CACHE_HIT=true 且 elan 可执行）时跳过下载。
set -euo pipefail

: "${ELAN_VERSION:?需要 ELAN_VERSION}"
: "${ELAN_SHA256:?需要 ELAN_SHA256}"

arch=$(uname -m)
triple=${ELAN_ARCH_TRIPLE:-x86_64-unknown-linux-gnu}
if [ "$triple" = "x86_64-unknown-linux-gnu" ] && [ "$arch" != "x86_64" ]; then
  echo "install_elan.sh: 架构不符（实际 $arch，期望 x86_64；如需其他架构请显式提供对应 ELAN_ARCH_TRIPLE 与 ELAN_SHA256）" >&2
  exit 2
fi

if [ "${CACHE_HIT:-}" != true ] || [ ! -x "$HOME/.elan/bin/elan" ]; then
  tmp=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fm-elan-XXXXXX")
  trap 'rm -rf -- "$tmp"' EXIT
  tgz=$tmp/elan.tar.gz
  curl --retry 5 --retry-all-errors --retry-delay 10 -sSfL -o "$tgz" \
    "https://github.com/leanprover/elan/releases/download/${ELAN_VERSION}/elan-${triple}.tar.gz"
  printf '%s  %s\n' "$ELAN_SHA256" "$tgz" | sha256sum -c -
  tar -xzf "$tgz" -C "$tmp"
  "$tmp/elan-init" -y --default-toolchain none --no-modify-path
fi

"$HOME/.elan/bin/elan" --version
if [ -n "${GITHUB_PATH:-}" ]; then
  printf '%s\n' "$HOME/.elan/bin" >> "$GITHUB_PATH"
fi
