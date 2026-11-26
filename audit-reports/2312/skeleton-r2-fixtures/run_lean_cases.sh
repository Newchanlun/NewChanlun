#!/usr/bin/env bash
# 依次跑需要 lean 的夹具，日志落到 ../logs/。每个脚本各自包在 flock + guard.sh 里。
cd "$(dirname "$0")"
for c in "$@"; do
  flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 "$c.py" > "../logs/$c.txt" 2>&1
  echo "$c rc=$?"
done
