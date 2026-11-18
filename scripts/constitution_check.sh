#!/usr/bin/env bash
# 世代宪法轻量检查（#506）：只出报告不阻断。手动/仪式触发。
# 判据源：docs/adr/0004-generation-constitution.md
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "=== ① 残骸 worktree 候选（票关 ∧ 干净 ∧ 无未合入）==="
git worktree list --porcelain | grep '^worktree ' | awk '{print $2}' | while read -r wt; do
  [ "$wt" = "$PWD" ] && continue
  dirty=$(git -C "$wt" status --short 2>/dev/null | head -1)
  [ -n "$dirty" ] && continue
  branch=$(git -C "$wt" branch --show-current 2>/dev/null)
  [ -z "$branch" ] && continue
  ahead=$(git rev-list --count main.."$branch" 2>/dev/null || echo "?")
  [ "$ahead" = "0" ] && echo "CANDIDATE: $wt ($branch)"
done

echo "=== ② 残骸分支候选（无未合入 commit 的非 main 本地分支）==="
git branch | sed 's/^[*+ ] *//' | while read -r b; do
  [ "$b" = "main" ] && continue
  ahead=$(git rev-list --count main.."$b" 2>/dev/null || echo "?")
  [ "$ahead" = "0" ] && echo "CANDIDATE: ${b}（注：须核票状态与 owner，gh issue view <n>）"
done

echo "=== ③ 禁入仓模式现货（应已 gitignore，出现即异常）==="
for pat in "*.bak" ".git.bak-*" "kimi-export-*.md" ".playwright-mcp" "G:"; do
  found=$(find . -maxdepth 1 -name "$pat" 2>/dev/null | head -3)
  [ -n "$found" ] && echo "JUNK: $found"
done

echo "=== ④ 未跟踪大文件（>10M，review-results 活期口径外）==="
git status --porcelain | grep '^??' | awk '{print $2}' | while read -r f; do
  [ -f "$f" ] && size=$(stat -f%z "$f" 2>/dev/null || echo 0) && [ "$size" -gt 10485760 ] && echo "BIG-UNTRACKED: $f ($((size/1048576))M)"
done
echo "=== 检查完毕（报告制，不阻断；候选不代表票已关闭，处置见 ADR 0004）==="
