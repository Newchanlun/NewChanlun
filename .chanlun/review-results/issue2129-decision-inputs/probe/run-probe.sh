#!/usr/bin/env bash
set -euo pipefail
[[ $(uname -s) == Linux ]]
printf 'baseline='; cat BASELINE
uname -sm
command -v cargo
rustc --version
export CARGO_PROFILE_DEV_DEBUG=0 CARGO_INCREMENTAL=0
# .probe-input 为指定基线 git archive 的独立副本，clip 只加测试函数。
cd rust
export PROBE_BIN_DIR="${CARGO_TARGET_DIR:-$PWD/target}/debug"
cargo build --locked --features production_session --bin e_economic_session --bin x_execution_session
cat ../probe.rs >> src/economic_session/exact_x_e2e_tests.rs
cargo test --locked --features production_session --lib issue2129_real_e_named_recovery_then_x_next_exchange -- --nocapture
