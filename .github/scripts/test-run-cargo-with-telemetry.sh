#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly helper="$script_dir/run-cargo-with-telemetry.sh"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
readonly stub_dir="$tmp_dir/stubs"
readonly work_dir="$tmp_dir/work"
mkdir -p "$stub_dir" "$work_dir/target"

cat > "$stub_dir/free" <<'STUB'
#!/usr/bin/env bash
printf 'Mem: stub\n'
STUB
cat > "$stub_dir/df" <<'STUB'
#!/usr/bin/env bash
if [[ " $* " == *" --output=avail "* ]]; then
  printf 'Avail\n%s\n' "${STUB_AVAILABLE_BYTES:-2147483648}"
else
  printf 'Filesystem Type 1B-blocks Used Available Use%% Mounted on\nstub ext4 1 0 %s 0%% /\n' "${STUB_AVAILABLE_BYTES:-2147483648}"
fi
STUB
cat > "$stub_dir/du" <<'STUB'
#!/usr/bin/env bash
count=0
if [[ -f "$STUB_DU_COUNTER" ]]; then
  count="$(cat "$STUB_DU_COUNTER")"
fi
count=$((count + 1))
printf '%s\n' "$count" > "$STUB_DU_COUNTER"
printf '1024\ttarget\n'
if (( count >= 2 )); then
  exit "${STUB_SNAPSHOT_STATUS:-0}"
fi
STUB
cat > "$stub_dir/ps" <<'STUB'
#!/usr/bin/env bash
if (( ${STUB_SAMPLER_STATUS:-0} != 0 )); then
  exit "$STUB_SAMPLER_STATUS"
fi
printf 'cargo\nrustc\nrust-lld\n'
STUB
cat > "$stub_dir/cargo" <<'STUB'
#!/usr/bin/env bash
{
  printf 'cargo\n'
  printf '%s\n' "$@"
} > "$STUB_ARGV_FILE"
sleep 0.15
exit "${STUB_COMMAND_STATUS:-0}"
STUB
chmod +x "$stub_dir"/*

assert_status() {
  local expected_status=$1 actual_status=$2 label=$3 log_file=$4
  if (( actual_status != expected_status )); then
    echo "FAIL $label: expected status $expected_status, got $actual_status" >&2
    cat "$log_file" >&2
    exit 1
  fi
}

run_matrix_case() {
  local command_variant=$1 command_status=$2 sampler_status=$3 snapshot_status=$4
  local expected_status=0 actual_status label log_file argv_file counter_file expected_file
  local -a command_argv
  case "$command_variant" in
    default)
      command_argv=(cargo test --all-targets --jobs 1)
      ;;
    backtest)
      command_argv=(cargo test --lib --features backtest_bin --jobs 1)
      ;;
    *)
      echo "unknown command variant: $command_variant" >&2
      exit 2
      ;;
  esac
  if (( command_status != 0 )); then
    expected_status=$command_status
  elif (( sampler_status != 0 )); then
    expected_status=$sampler_status
  else
    expected_status=$snapshot_status
  fi

  label="$command_variant-command${command_status}-sampler${sampler_status}-snapshot${snapshot_status}"
  log_file="$tmp_dir/$label.log"
  argv_file="$tmp_dir/$label.argv"
  counter_file="$tmp_dir/$label.du-count"
  expected_file="$tmp_dir/$label.expected"
  printf '%s\n' "${command_argv[@]}" > "$expected_file"

  set +e
  (
    cd "$work_dir"
    env \
      PATH="$stub_dir:$PATH" \
      STUB_ARGV_FILE="$argv_file" \
      STUB_DU_COUNTER="$counter_file" \
      STUB_COMMAND_STATUS="$command_status" \
      STUB_SAMPLER_STATUS="$sampler_status" \
      STUB_SNAPSHOT_STATUS="$snapshot_status" \
      CARGO_TELEMETRY_TEST_SAMPLE_SECONDS=0.01 \
      "$helper" "${command_argv[@]}"
  ) >"$log_file" 2>&1
  actual_status=$?
  set -e

  assert_status "$expected_status" "$actual_status" "$label" "$log_file"
  diff -u "$expected_file" "$argv_file"
  grep -Fq 'telemetry_min_free_bytes=2147483648 telemetry_sample_seconds=0.01 command=' "$log_file"
  if (( sampler_status == 0 )); then
    if grep -Fq 'Resource sampler failed' "$log_file" || grep -Fq 'Resource sampler exited unexpectedly' "$log_file"; then
      echo "FAIL $label: actively stopped sampler was reported as an error" >&2
      cat "$log_file" >&2
      exit 1
    fi
  else
    grep -Fq 'Resource sampler exited unexpectedly::status=42' "$log_file"
  fi
}

matrix_count=0
for command_variant in default backtest; do
  for command_status in 0 7; do
    for sampler_status in 0 42; do
      for snapshot_status in 0 9; do
        run_matrix_case "$command_variant" "$command_status" "$sampler_status" "$snapshot_status"
        matrix_count=$((matrix_count + 1))
      done
    done
  done
done
if (( matrix_count != 16 )); then
  echo "FAIL: expected 16 matrix cells, ran $matrix_count" >&2
  exit 1
fi

run_guard_case() {
  local label=$1 available_bytes=$2 expected_status=$3
  local log_file="$tmp_dir/guard-$label.log"
  local argv_file="$tmp_dir/guard-$label.argv"
  local counter_file="$tmp_dir/guard-$label.du-count"
  local actual_status
  set +e
  (
    cd "$work_dir"
    env \
      PATH="$stub_dir:$PATH" \
      STUB_ARGV_FILE="$argv_file" \
      STUB_DU_COUNTER="$counter_file" \
      STUB_AVAILABLE_BYTES="$available_bytes" \
      "$helper" cargo test --all-targets --jobs 1
  ) >"$log_file" 2>&1
  actual_status=$?
  set -e
  assert_status "$expected_status" "$actual_status" "guard-$label" "$log_file"
  if (( expected_status == 0 )); then
    grep -Fq "available_bytes=$available_bytes minimum_bytes=2147483648" "$log_file"
    grep -Fq 'telemetry_min_free_bytes=2147483648 telemetry_sample_seconds=10 command=' "$log_file"
  elif [[ -e "$argv_file" ]]; then
    echo "FAIL guard-$label: command ran after guard rejection" >&2
    cat "$log_file" >&2
    exit 1
  fi
}

run_guard_case exact-boundary 2147483648 0
run_guard_case one-byte-low 2147483647 1
run_guard_case non-numeric not-a-number 1

grep -Fqx 'readonly MIN_FREE_BYTES=2147483648' "$helper"
grep -Fqx 'readonly DEFAULT_SAMPLE_SECONDS=10' "$helper"

for bad_sample in 0 nope; do
  log_file="$tmp_dir/bad-sample-$bad_sample.log"
  set +e
  CARGO_TELEMETRY_TEST_SAMPLE_SECONDS="$bad_sample" "$helper" cargo true >"$log_file" 2>&1
  actual_status=$?
  set -e
  assert_status 64 "$actual_status" "bad-sample-$bad_sample" "$log_file"
done

log_file="$tmp_dir/no-command.log"
set +e
"$helper" >"$log_file" 2>&1
actual_status=$?
set -e
assert_status 64 "$actual_status" no-command "$log_file"

# #1875 偶发重试：只认 EACCES（build-script never executed + os error 13）与 EXDEV（rlib rename os error 18）两种特征，最多重试一次。
retry_dir="$tmp_dir/retry-stubs"
mkdir -p "$retry_dir"
cat > "$retry_dir/cargo" <<'STUB'
#!/usr/bin/env bash
n=0; [[ -f "$STUB_CALLS" ]] && n="$(cat "$STUB_CALLS")"; n=$((n + 1)); printf '%s\n' "$n" > "$STUB_CALLS"
mode="${STUB_RETRY_MODE:?}"
if [[ "$mode" == eacces-once && $n -eq 1 ]] || [[ "$mode" == eacces-always ]]; then
  printf 'error: failed to run custom build command for `serde_json v1.0.0`\n' >&2
  printf 'Caused by:\n  could not execute process `/w/rust/target/debug/build/serde_json-1/build-script-build` (never executed)\n' >&2
  printf 'Caused by:\n  Permission denied (os error 13)\n' >&2
  exit 101
fi
if [[ "$mode" == exdev-once && $n -eq 1 ]]; then
  printf 'error: failed to build archive at `/w/1488-target/debug/deps/liblibc-1.rlib`: failed to rename archive file: Invalid cross-device link (os error 18)\n' >&2
  printf 'error: could not compile `libc` (lib) due to 1 previous error\n' >&2
  exit 101
fi
if [[ "$mode" == exdev-with-build-script && $n -eq 1 ]]; then
  printf 'could not execute process `/w/rust/target/debug/build/serde_json-1/build-script-build` (never executed)\n' >&2
  printf 'error: failed to build archive at `/w/1488-target/debug/deps/liblibc-1.rlib`: failed to rename archive file: Invalid cross-device link (os error 18)\n' >&2
  exit 101
fi
if [[ "$mode" == exdev-rmeta-once && $n -eq 1 ]]; then
  printf '{"reason":"compiler-message","message":{"rendered":"error: failed to write /w/t/debug/deps/libshlex-1.rmeta: Invalid cross-device link (os error 18)\\n\\n"}}\n'
  printf 'error: could not compile `shlex` (lib) due to 1 previous error\n' >&2
  exit 101
fi
if [[ "$mode" == exdev-in-test ]]; then
  printf 'thread main panicked: rename failed: Invalid cross-device link (os error 18)\n' >&2
  exit 101
fi
if [[ "$mode" == other-error ]]; then
  printf 'error[E0308]: mismatched types\nPermission denied (os error 13)\n' >&2
  exit 101
fi
exit 0
STUB
chmod +x "$retry_dir/cargo"
run_retry_case() {
  local mode=$1 expected_status=$2 expected_calls=$3 expect_warning=$4 log_file calls_file actual_status calls
  log_file="$tmp_dir/retry-$mode.log"; calls_file="$tmp_dir/retry-$mode.calls"
  set +e
  STUB_RETRY_MODE="$mode" STUB_CALLS="$calls_file" STUB_DU_COUNTER="$tmp_dir/retry-$mode.du" \
    CARGO_TELEMETRY_TEST_SAMPLE_SECONDS=0.05 PATH="$retry_dir:$stub_dir:$PATH" \
    bash -c 'cd "$1" && "$2" cargo test' _ "$work_dir" "$helper" >"$log_file" 2>&1
  actual_status=$?
  set -e
  assert_status "$expected_status" "$actual_status" "retry-$mode" "$log_file"
  calls="$(cat "$calls_file")"
  if [[ "$calls" != "$expected_calls" ]]; then
    echo "FAIL retry-$mode: expected $expected_calls cargo calls, got $calls" >&2; cat "$log_file" >&2; exit 1
  fi
  if [[ "$expect_warning" == yes ]] && ! grep -q 'Boat transient cargo error retry::cause=' "$log_file"; then
    echo "FAIL retry-$mode: missing retry warning" >&2; exit 1
  fi
  if [[ "$expect_warning" == no ]] && grep -q 'Boat transient cargo error retry' "$log_file"; then
    echo "FAIL retry-$mode: unexpected retry warning" >&2; exit 1
  fi
}
run_retry_case eacces-once 0 2 yes
run_retry_case eacces-always 101 2 yes
grep -q '::group::Boat EACCES diagnostics /w/rust/target/debug/build/serde_json-1/build-script-build' "$tmp_dir/retry-eacces-once.log" \
  || { echo "FAIL retry-eacces-once: missing EACCES diagnostics group" >&2; exit 1; }
run_retry_case exdev-once 0 2 yes
! grep -q 'Boat EACCES diagnostics' "$tmp_dir/retry-exdev-once.log" \
  || { echo "FAIL retry-exdev-once: EACCES diagnostics on EXDEV" >&2; exit 1; }
run_retry_case exdev-with-build-script 0 2 yes
! grep -q 'Boat EACCES diagnostics' "$tmp_dir/retry-exdev-with-build-script.log" \
  || { echo "FAIL retry-exdev-with-build-script: EACCES diagnostics on EXDEV" >&2; exit 1; }
run_retry_case exdev-rmeta-once 0 2 yes
run_retry_case exdev-in-test 101 1 no
run_retry_case other-error 101 1 no
run_retry_case success 0 1 no

# 阴性：TMPDIR 不可用时也必须如实反映命令结论（#2025 独审 BLOCK：mktemp 失败不得把失败改成成功、不得不跑命令）。
for case in other-error:101:1 success:0:1; do
  IFS=: read -r mode want calls_want <<<"$case"
  calls_file="$tmp_dir/notmp-$mode.calls"; log_file="$tmp_dir/notmp-$mode.log"
  set +e
  TMPDIR="$tmp_dir/does-not-exist" STUB_RETRY_MODE="$mode" STUB_CALLS="$calls_file" STUB_DU_COUNTER="$tmp_dir/notmp-$mode.du" \
    CARGO_TELEMETRY_TEST_SAMPLE_SECONDS=0.05 PATH="$retry_dir:$stub_dir:$PATH" \
    bash -c 'cd "$1" && "$2" cargo test' _ "$work_dir" "$helper" >"$log_file" 2>&1
  actual_status=$?
  set -e
  assert_status "$want" "$actual_status" "notmp-$mode" "$log_file"
  [[ "$(cat "$calls_file")" == "$calls_want" ]] || { echo "FAIL notmp-$mode: expected $calls_want cargo calls" >&2; cat "$log_file" >&2; exit 1; }
done

# 直接调用共用的 cargo-eacces-retry.sh（#1488 作业与 release-locks 循环不经过包装器，直接用它）。
direct_calls="$tmp_dir/retry-direct.calls"; direct_log="$tmp_dir/retry-direct.log"
set +e
STUB_RETRY_MODE=eacces-once STUB_CALLS="$direct_calls" PATH="$retry_dir:$PATH" "$script_dir/cargo-eacces-retry.sh" cargo test >"$direct_log" 2>&1
direct_status=$?
set -e
assert_status 0 "$direct_status" retry-direct "$direct_log"
[[ "$(cat "$direct_calls")" == 2 ]] || { echo "FAIL retry-direct: expected 2 calls" >&2; exit 1; }

printf 'PASS: 16 status-priority cells, guard boundaries, defaults, configuration validation, argv preservation, 9 transient-retry cases (EACCES, EXDEV rlib/rmeta), and 2 no-TMPDIR fail-closed cases\n'
