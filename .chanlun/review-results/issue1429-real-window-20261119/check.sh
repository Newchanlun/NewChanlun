#!/bin/sh
set -eu
cd "$(dirname "$0")"
uname -sm
lean --version
mkdir -p ../olean/Formal
export LEAN_PATH="$PWD/../olean"
for unit in TrendTrichotomy CenterTrichotomy RecursiveConstruction; do
  printf '编译上游 %s\n' "$unit"
  lean -o "../olean/Formal/$unit.olean" "Formal/$unit.lean"
done
lean -o ../olean/Boundary1429.olean Boundary1429.lean
echo 'Boundary1429: PASS'
