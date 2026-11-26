#!/usr/bin/env bash
# 给 #2315 的输入：run.py 若不带 -I 运行，同目录下的 json.py 会在任何检查（含 RUNNER_MISMATCH）之前被导入执行。
# run.py 本身与受信提交逐字节相同，RUNNER_MISMATCH 管不到同目录的其它文件。不调用 lean/lake。
SRC=${RF_SRC:-/home/workspace/.t3/worktrees/NewChanlun/t3-279c6aca-c1e9a2095915fa5f}
D=${RF_WORK:-/home/workspace/fm/tmp/review-f/work}/no-isolated; rm -rf "$D"; mkdir -p "$D/runner"
cp "$SRC/formal_math/verification/runner/run.py" "$D/runner/run.py"
cat > "$D/runner/json.py" <<'PY'
import os
os.write(1, b"FM RESULT GREEN (forged by sibling json.py)\n")
os._exit(0)
PY
cmp "$SRC/formal_math/verification/runner/run.py" "$D/runner/run.py" && echo "run.py 与被审提交逐字节相同"
echo "--- 不带 -I："; python3 "$D/runner/run.py" --repo /nonexistent --base x --head y --branch z --workdir /nonexistent/w --packages /nonexistent; echo "rc=$?"
echo "--- 带 -I："; python3 -I "$D/runner/run.py" --repo /nonexistent --base x --head y --branch z --workdir /nonexistent/w --packages /nonexistent; echo "rc=$?"
