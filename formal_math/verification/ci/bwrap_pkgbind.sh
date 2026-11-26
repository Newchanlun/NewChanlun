#!/usr/bin/env bash
# 为 Lake 4.36.0 `lake check` / `lake comparator` 生成可执行 COMPARATOR_BWRAP 包装脚本。
#
# 原因：
#   1. Lake 在 Lake/CLI/Check.lean:214-219 用 `env -i <COMPARATOR_BWRAP> ...` 启动 bwrap，
#      环境变量会被清空，因此包装脚本必须把路径字面烤进脚本里；
#   2. 仓内 formal_math/ 下的文件按 precheck.py 规则全部为 100644（不带执行位），
#      而 Lake 的 whichExe 要求 COMPARATOR_BWRAP 可执行，因此本脚本把它写出到仓外临时目录并 chmod 0700；
#   3. 包装脚本只做两件事：
#      - 若指定了 --packages，只要 Lake 挂载了 <lake_dir>（--bind 或 --ro-bind），
#        立刻在其后追加 `--ro-bind <packages> <lake_dir>/packages`，保证依赖目录在沙箱里严格只读；
#      - 若指定了 --offline，剥除 Lake 依赖解析步所传的 `--share-net`，保证全部沙箱步断网。
set -euo pipefail

out_exe=""
lake_dir=""
packages=""
real_bwrap=""
offline=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --emit) out_exe=${2:?}; shift 2 ;;
    --lake-dir) lake_dir=${2:?}; shift 2 ;;
    --packages) packages=${2:?}; shift 2 ;;
    --bwrap) real_bwrap=${2:?}; shift 2 ;;
    --offline) offline=1; shift ;;
    *) echo "bwrap_pkgbind.sh: 未知参数: $1" >&2; exit 2 ;;
  esac
done

[ -n "$out_exe" ] || { echo "bwrap_pkgbind.sh: 缺少 --emit" >&2; exit 2; }
if [ -n "$packages" ] && [ -z "$lake_dir" ]; then
  echo "bwrap_pkgbind.sh: 指定 --packages 时必须同时指定 --lake-dir" >&2
  exit 2
fi
if [ -z "$real_bwrap" ]; then
  real_bwrap=$(command -v bwrap || true)
fi
[ -n "$real_bwrap" ] && [ -x "$real_bwrap" ] || { echo "bwrap_pkgbind.sh: 找不到可执行的 bwrap" >&2; exit 2; }

if [ -n "$packages" ]; then
  [ -d "$packages" ] || { echo "bwrap_pkgbind.sh: 依赖目录不存在: $packages" >&2; exit 2; }
  packages=$(cd -P -- "$packages" && pwd)
fi
if [ -n "$lake_dir" ]; then
  mkdir -p -- "$lake_dir"
  lake_dir=$(cd -P -- "$lake_dir" && pwd)
  if [ -n "$packages" ]; then
    mkdir -p -- "$lake_dir/packages"
  fi
fi

q_bwrap=$(printf '%q' "$real_bwrap")
q_pkg=$(printf '%q' "$packages")
q_lake=$(printf '%q' "$lake_dir")

umask 077
cat > "$out_exe" <<EOF
#!/usr/bin/env bash
set -euo pipefail
real_bwrap=${q_bwrap}
pkg_src=${q_pkg}
lake_dir=${q_lake}
pkg_dst="\${lake_dir}/packages"
offline=${offline}

out=()
saw_lake=0
while [ "\$#" -gt 0 ]; do
  arg=\$1
  shift
  if [ "\$arg" = "--" ]; then
    if [ "\$saw_lake" = 1 ] && [ -n "\$pkg_src" ]; then
      out+=(--ro-bind "\$pkg_src" "\$pkg_dst")
      saw_lake=0
    fi
    out+=(-- "\$@")
    break
  fi
  if [ "\$offline" = 1 ] && [ "\$arg" = "--share-net" ]; then
    continue
  fi
  case "\$arg" in
    --bind|--ro-bind|--dev-bind|--bind-try|--ro-bind-try|--dev-bind-try|--symlink|--setenv)
      [ "\$#" -ge 2 ] || { echo "bwrap_pkgbind: 缺少参数: \$arg" >&2; exit 2; }
      out+=("\$arg" "\$1" "\$2")
      if [ -n "\$pkg_src" ] && { [ "\$arg" = "--bind" ] || [ "\$arg" = "--ro-bind" ]; } && [ "\$2" = "\$lake_dir" ]; then
        saw_lake=1
      fi
      shift 2
      ;;
    --tmpfs|--dir|--dev|--proc|--chdir|--unsetenv|--file|--bind-data|--ro-bind-data|--seccomp|--add-seccomp-fd|--info-fd|--json-status-fd|--sync-fd|--block-fd|--userns-block-fd|--hostname|--cap-add|--cap-drop|--uid|--gid|--perms|--size|--chmod|--remount-ro)
      [ "\$#" -ge 1 ] || { echo "bwrap_pkgbind: 缺少参数: \$arg" >&2; exit 2; }
      out+=("\$arg" "\$1")
      shift
      ;;
    --unshare-all)
      if [ "\$saw_lake" = 1 ] && [ -n "\$pkg_src" ]; then
        out+=(--ro-bind "\$pkg_src" "\$pkg_dst")
        saw_lake=0
      fi
      out+=("\$arg")
      ;;
    *)
      out+=("\$arg")
      ;;
  esac
done
exec "\$real_bwrap" "\${out[@]}"
EOF
chmod 0700 "$out_exe"
