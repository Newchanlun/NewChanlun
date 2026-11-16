#!/usr/bin/env bash
set -euo pipefail

# #1394/#1481：只执行「开某个 TestOnly 特性后才编译出来」的测试。
# 其余同名测试与不带该特性的 s_session 步同体，已在那一步执行（#1588 起为 ci.yml 的 rust-test-s-session 各分片）；
# 这里只补特性新增的那一批。
# 用法（在 rust/ 下）：test-feature-delta.sh <feature>
# 门：两份 --list 都须成功；新增集合为空即失败（只编译不执行、或一个都没编出来，都按无锁计）。

if (( $# != 1 )); then
  echo "usage: $0 <feature>" >&2
  exit 64
fi
readonly feature="$1"
readonly base_features="s_session"
# #1875：CI_DELTA_SKIP_FILE（可选）每行「<lib|bin> <测试全名>」，列出同一 CI 内另有作业以相同 features 逐名精确执行的测试
#   （同为 dev 档，但对方依赖优化级别与进程模型不同：每条单独进程、--exact），这里不再重复执行。
#   「新增集合为空即失败」与「特性移除测试」两道门仍按完整集合判定；跳过条数写进日志。
readonly skip_file="${CI_DELTA_SKIP_FILE:-}"
if [[ -n "$skip_file" && ! -r "$skip_file" ]]; then
  echo "::error title=Feature delta skip list unreadable::$skip_file" >&2
  exit 1
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# #1875：一组 features 只调一次 cargo 编出 lib 与 bin 两个测试二进制（两份编译在同一次构建里并行），
#   再各用 cargo 列名（产物已是最新，不重编）。列出的名单、求差集与两道门都和逐目标各编一次时相同。
list_tests() {
  local features="$1" out="$2" target sel
  cargo test --locked --features "$features" --lib --bin s_structure_session --no-run --jobs "${CI_CARGO_JOBS:-1}"
  for target in lib bin; do
    if [[ "$target" == lib ]]; then sel=(--lib); else sel=(--bin s_structure_session); fi
    cargo test --locked --features "$features" "${sel[@]}" --jobs "${CI_CARGO_JOBS:-1}" -- --list >"$out.$target.raw"
    sed -n 's/: test$//p' "$out.$target.raw" | LC_ALL=C sort >"$out.$target"
  done
}

# #1875：CI_TEST_PART=i/N 时只执行新增集合中按名字排序后第 i、i+N、i+2N… 个（i 从 0 起）。N 个作业各取一份，
#   并集恰为新增集合、互不重叠；每个作业的机器上仍是 RUST_TEST_THREADS 个线程，同机负载与不拆时相同。
#   「新增集合为空即失败」仍按完整集合判定。不设或 0/1 时执行全部。
run_delta() {
  local target="$1"; shift
  local sel part=() i n k
  if [[ "$target" == lib ]]; then sel=(--lib); else sel=(--bin s_structure_session); fi
  IFS=/ read -r i n <<<"${CI_TEST_PART:-0/1}"
  for (( k = i; k < $#; k += n )); do part+=("${@:k+1:1}"); done
  echo "feature_delta target=$target part=$i/$n run=${#part[@]} of $#"
  (( ${#part[@]} == 0 )) && return 0
  cargo test --locked --features "$base_features,$feature" "${sel[@]}" --jobs "${CI_CARGO_JOBS:-1}" -- --exact "${part[@]}"
}

# #1875：每个阶段成功后打一行公开 annotation（免认证可读）：用时。用来量「只为求差集的无特性构建」占多少。只打日志：
#   不包在 || 或 if 里调用（那样会关掉被调函数内的 set -e，吞掉 cargo 失败），阶段失败时照旧由 set -e 退出、不打这一行。
phase_done() {
  echo "::notice title=feature-delta phase::feature=$feature part=${CI_TEST_PART:-0/1} target=$1 phase=$2 seconds=$((SECONDS - $3))"
}

t0=$SECONDS
list_tests "$base_features" "$work/base"
phase_done both list-base "$t0"
t0=$SECONDS
list_tests "$base_features,$feature" "$work/feature"
phase_done both list-feature "$t0"

total=0
for target in lib bin; do
  mv "$work/base.$target" "$work/$target.base"
  mv "$work/feature.$target" "$work/$target.feature"
  LC_ALL=C comm -13 "$work/$target.base" "$work/$target.feature" >"$work/$target.delta"
  removed="$(LC_ALL=C comm -23 "$work/$target.base" "$work/$target.feature" | wc -l | tr -d ' ')"
  count="$(wc -l <"$work/$target.delta" | tr -d ' ')"
  echo "feature_delta target=$target feature=$feature base=$(wc -l <"$work/$target.base" | tr -d ' ') with_feature=$(wc -l <"$work/$target.feature" | tr -d ' ') delta=$count removed=$removed"
  if (( removed != 0 )); then
    echo "::error title=Feature removes tests::$feature removed $removed tests from $target" >&2
    exit 1
  fi
  if (( count > 0 )); then
    names=()
    skipped=0
    while IFS= read -r name; do
      if [[ -n "$skip_file" ]] && grep -Fxq -- "$target $name" "$skip_file"; then
        skipped=$((skipped + 1))
        continue
      fi
      names+=("$name")
    done <"$work/$target.delta"
    echo "feature_delta target=$target skipped_elsewhere=$skipped"
    t0=$SECONDS
    run_delta "$target" "${names[@]}"
    phase_done "$target" run "$t0"
  fi
  total=$(( total + count ))
done
if (( total == 0 )); then
  echo "::error title=Empty feature delta::$feature compiled no additional tests; nothing was executed" >&2
  exit 1
fi
