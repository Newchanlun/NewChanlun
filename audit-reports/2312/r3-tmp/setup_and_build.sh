#!/bin/zsh
set -euo pipefail
cd /Volumes/AgentStorage/wt-2312-v3-review
df -h / /Volumes/AgentStorage
source scripts/fm_env.sh
cd formal_math
lake build fm_audit
df -h / /Volumes/AgentStorage
