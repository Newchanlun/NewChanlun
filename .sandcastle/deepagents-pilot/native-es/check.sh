#!/bin/sh
# Isolated local checks only: no collector development invocation, ES client or signing.
set -eu
out=${1:?usage: check.sh /absolute/evidence/build-directory}
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
"$src/build.sh" "$out"
for test in common_test peer_test io_test; do
  injection=""
  if [ "$test" = io_test ]; then injection="-Dwrite=native_test_write"; fi
  xcrun clang $injection -std=c11 -Wall -Wextra -Werror -mmacosx-version-min=13.0 \
    "$src/common.c" "$src/$test.c" -framework Security -framework CoreFoundation -o "$out/$test"
  "$out/$test"
done
for target in collector helper; do
  if "$out/maintenance-es-$target" >"$out/$target-disabled.stdout" 2>"$out/$target-disabled.stderr"; then
    echo 'unexpected enabled default' >&2; exit 1
  else
    test "$?" -eq 78
  fi
  grep -q 'disabled' "$out/$target-disabled.stderr"
done
printf 'native build/framing/isolated peer/default disabled: passed\n'
if "$out/maintenance-es-helper" --development-only "$out/unused.sock" "$out/absent-collector.req" "$out/absent-helper.req" resource nonce helper -- /usr/bin/true >"$out/helper-rejected.stdout" 2>"$out/helper-rejected.stderr"; then
  echo 'unexpected accepted unconfigured helper' >&2; exit 1
else
  test "$?" -eq 78
fi
grep -q '^signature_unverified$' "$out/helper-rejected.stderr"
printf 'helper missing trusted requirements: refused before socket/fork
'
