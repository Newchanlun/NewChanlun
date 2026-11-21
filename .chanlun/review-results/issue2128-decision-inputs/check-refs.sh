set -eu
i=0
while read -r ref path; do
  i=$((i+1))
  url=$(gh api --include -X GET "repos/Newchanlun/NewChanlun/contents/$path" -f "ref=$ref" | awk '/^HTTP\// { line=$0 } /^\{/ { print line; print; }')
  printf '%s\n' "$url" | head -1
  printf '%s\n' "$url" | tail -n +2 | jq -er 'select(.type=="file") | .html_url'
done <<'REFS'
329be34f5a9ca9c2bcc38ae75783304cc654904c rust/src/economic_session/recovery.rs
329be34f5a9ca9c2bcc38ae75783304cc654904c rust/src/bin/production_session.rs
d18e70fad7aae91156ac28860acab1132a076bea docs/adr/0065-production-session-endpoint-ownership.md
15ffe5083724a858e1f0fc669f457f8e6451d84d docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md
efc1ddc4d6c015f4f8c6d44f904d704a88308b46 .chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md
REFS
