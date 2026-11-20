set -eu
if test -f "$HOME/.cargo/env"; then . "$HOME/.cargo/env"; fi
cat CANDIDATE
cargo --version
rustc --version
export CARGO_TARGET_DIR="$PWD/target"
cd rust
echo 'CHECK cargo fmt --check'
cargo fmt --check
echo 'CHECK cargo test --locked --lib --features lav_seal at14_report'
cargo test --locked --lib --features lav_seal at14_report
echo 'CHECK cargo check --locked (default non-test targets)'
cargo check --locked
echo 'CHECK cargo build --locked --lib (default cdylib+rlib)'
cargo build --locked --lib
file "$CARGO_TARGET_DIR/debug/libnewchan_rust.so"
test -s "$CARGO_TARGET_DIR/debug/libnewchan_rust.so"
cd ../review
echo 'CHECK external public consumer expectations (contract assertions)'
cargo test --offline --lib -- --nocapture
