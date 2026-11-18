#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export C4B_ACCEPT_OUT="$(mktemp -d)"
cd rust
cargo test --locked --lib --features s_session c4b_process_acceptance_forward -- --nocapture
cargo test --locked --lib --features s_session c4b_process_acceptance_recover -- --nocapture
