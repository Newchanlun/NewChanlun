#!/usr/bin/env sh
# 复现门 6b 符号链接检查在 HEAD 含符号链接、索引/工作树替换为普通文件时放行（退出码 0）
# 前提：在已初始化且含 origin/main 基线的仓库根目录执行
set -eu
git switch -qc proof/symtest
ln -s Ok.lean formal_math/Chan/Thm/link.lean
git add formal_math/Chan/Thm/link.lean
git commit -qm "commit symlink in HEAD"
# 步骤 1：此时门 6b 报 SYMLINK 退 1
python3 formal_math/verification/run_gates.py --repo-root . --gate 6b || true
# 步骤 2：在工作树与暂存区用普通文件覆盖，HEAD 仍保留 120000 符号链接
rm formal_math/Chan/Thm/link.lean
printf 'module\npublic section\ndef ok2 : Nat := 2\n' > formal_math/Chan/Thm/link.lean
git add formal_math/Chan/Thm/link.lean
git ls-tree HEAD -- formal_math/Chan/Thm/link.lean
# 实测退出码 0（应红）
python3 formal_math/verification/run_gates.py --repo-root . --gate 6b
