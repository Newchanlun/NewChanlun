#!/usr/bin/env bash
# CI 用：装钉选版本的 elan（发行包按 sha256 核对），工具链由 lean-toolchain 首次调用时装。
# 环境变量 ELAN_VERSION、ELAN_SHA256 由工作流给出；缓存命中（CACHE_HIT=true 且 elan 可执行）时跳过下载。
set -euo pipefail
: "${ELAN_VERSION:?}" "${ELAN_SHA256:?}"
if [ "${CACHE_HIT:-}" != true ] || [ ! -x "$HOME/.elan/bin/elan" ]; then
  tmp=${RUNNER_TEMP:-$(mktemp -d)}
  tgz=$tmp/elan.tar.gz
  curl --retry 5 --retry-all-errors --retry-delay 10 -sSfL -o "$tgz" \
    "https://github.com/leanprover/elan/releases/download/$ELAN_VERSION/elan-x86_64-unknown-linux-gnu.tar.gz"
  echo "$ELAN_SHA256  $tgz" | sha256sum -c -
  tar -xzf "$tgz" -C "$tmp"
  "$tmp/elan-init" -y --default-toolchain none --no-modify-path
fi
"$HOME/.elan/bin/elan" --version
if [ -n "${GITHUB_PATH:-}" ]; then echo "$HOME/.elan/bin" >> "$GITHUB_PATH"; fi
