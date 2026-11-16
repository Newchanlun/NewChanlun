#!/bin/sh
# Compilation only. Never starts collector/helper, signs artifacts or invokes ES.
set -eu
out=${1:?usage: build.sh /absolute/evidence/build-directory}
case "$out" in /*) ;; *) echo 'absolute output directory required' >&2; exit 2;; esac
src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$out"
for target in collector helper; do
  xcrun clang -std=c11 -Wall -Wextra -Werror -fblocks -mmacosx-version-min=13.0 \
    "$src/common.c" "$src/$target.c" -framework Security -framework CoreFoundation \
    -lEndpointSecurity -o "$out/maintenance-es-$target"
done
xcrun clang -std=c11 -Wall -Wextra -Werror -mmacosx-version-min=13.0 -dynamiclib \
  "$src/common.c" -framework Security -framework CoreFoundation -o "$out/libmaintenance-es-ipc.dylib"
