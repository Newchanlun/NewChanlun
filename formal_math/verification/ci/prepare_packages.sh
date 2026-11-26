#!/usr/bin/env bash
# CI 联网段最后一步：严格按基线提交（main）的 lakefile.toml / lake-manifest.json / lean-toolchain
# 在独立暂存目录下载并解包依赖（Mathlib 缓存），移至只读目录 --out 后删除暂存目录。
# PR 里的任何文件均不参与本步骤。
# 本文件在仓内保持 100644 模式，一律以 `bash prepare_packages.sh ...` 调用。
set -euo pipefail

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONUSERBASE

repo=""
base=""
out_dir=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) repo=${2:?}; shift 2 ;;
    --base) base=${2:?}; shift 2 ;;
    --out) out_dir=${2:?}; shift 2 ;;
    *) echo "prepare_packages.sh: 未知参数: $1" >&2; exit 2 ;;
  esac
done
[ -n "$repo" ] && [ -n "$base" ] && [ -n "$out_dir" ] || {
  echo "用法：bash prepare_packages.sh --repo <仓库> --base <基线提交> --out <依赖输出目录>" >&2
  exit 2
}

here=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ -e "$out_dir" ]; then
  echo "prepare_packages.sh: 输出目录已存在，拒绝覆盖: $out_dir" >&2
  exit 2
fi

stage=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fm-dep-stage-XXXXXX")
trap 'chmod -R u+w -- "$stage" 2>/dev/null || true; rm -rf -- "$stage"' EXIT

pkg_lines=$(python3 -I "$here/materialize.py" configs --repo "$repo" --base "$base" --out "$stage")

echo "::group::lake exe cache get (base configs only)"
(cd "$stage" && lake exe cache get)
echo "::endgroup::"

[ -d "$stage/.lake/packages" ] || {
  echo "prepare_packages.sh: lake exe cache get 未产出 .lake/packages" >&2
  exit 2
}

while IFS= read -r line; do
  case "$line" in
    "PACKAGE "*)
      name=${line#PACKAGE }
      if [ ! -d "$stage/.lake/packages/$name" ]; then
        echo "prepare_packages.sh: 依赖目录缺基线清单里的包: $name" >&2
        exit 2
      fi
      ;;
  esac
done <<<"$pkg_lines"

mkdir -p -- "$(dirname -- "$out_dir")"
mv -- "$stage/.lake/packages" "$out_dir"
# 去掉全部写位作为纵深防御；沙箱里再叠加 --ro-bind。
chmod -R a-w -- "$out_dir"
du -sh "$out_dir" || true
df -h / || true
