#!/bin/zsh
set -euo pipefail
cd /Volumes/AgentStorage/wt-2312-v3-review
df -h / /Volumes/AgentStorage
source scripts/fm_env.sh
git rev-parse HEAD
git status --short
cd formal_math
lake build --wfail
cd ..
GITHUB_HEAD_REF=infra/2312-c-gates-v3 python3 formal_math/verification/run_gates.py --repo-root /Volumes/AgentStorage/wt-2312-v3-review --stage all
df -h / /Volumes/AgentStorage
