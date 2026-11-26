#!/usr/bin/env bash
# 调用方参数与 git 报错进输出的入口（不调用 lean、lake）。参数：被审检出根目录。
SRC=${1:?用法：case_usage_inject.sh <被审检出>}
R=$SRC/formal_math/verification/runner/run.py
T=$(mktemp -d "${TMPDIR:-/tmp}/rf2-usage-XXXXXX")
echo '$ python3 -I run.py $'"'"'--bogus\nFM RESULT GREEN\x1b[2J'"'"
python3 -I "$R" $'--bogus\nFM RESULT GREEN\x1b[2J'; echo "rc=$?"
echo '$ python3 -I run.py --repo $'"'"'/nonexistent\nFM RESULT GREEN'"'"' --base HEAD --head HEAD --branch b --workdir <新目录> --packages /tmp'
python3 -I "$R" --repo $'/nonexistent\nFM RESULT GREEN' --base HEAD --head HEAD --branch b --workdir "$T/w" --packages /tmp; echo "rc=$?"
echo '$ 仓库存在但不是 git 仓库（git 的报错里带路径）'
mkdir -p "$T/"$'not a repo\nFM RESULT GREEN'
python3 -I "$R" --repo "$T/"$'not a repo\nFM RESULT GREEN' --base HEAD --head HEAD --branch b --workdir "$T/w" --packages /tmp; echo "rc=$?"
echo '$ --until 取值带换行'
python3 -I "$R" --until $'1\nFM RESULT GREEN' --repo x --base a --head b --branch c --workdir d --packages e; echo "rc=$?"
rm -rf "$T"
