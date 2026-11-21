#!/usr/bin/env bash
set -euo pipefail
base=b9d898dccf46c2a716115eaa1215bc39c458a959
for q in 'authority_epoch|authority_profile|具名恢复|写者履历' 'authorized_sources|来源纪元|producer_epoch|单写者' 'MayHaveCalled|QueryExecuteCommitted|不重发|旧代在途' 'H2|同轨迹重复|部署位置'; do
  printf '\nREPO %s\n' "$q"
  git grep -n -E "$q" "$base" -- docs/adr .chanlun analysis || test "$?" -eq 1
done
printf '\nFROZEN 2127\n'
git show 15ffe508:docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md | nl -ba | sed -n '142,188p'
printf '\nFROZEN 2079\n'
git show d18e70fa:docs/adr/0065-production-session-endpoint-ownership.md | nl -ba | sed -n '54,89p'
