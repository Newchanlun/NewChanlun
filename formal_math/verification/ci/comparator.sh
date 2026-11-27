#!/usr/bin/env bash
# 门 5（陈述比对）：两段隔离运行 Lake 4.36.0 `lake comparator`。
#
# 要求落实（#2315 评论 7176006564 第 3、4 条）：
#   1. 样板自检（独立仓外临时目录，每次挑战与解答彻底分目录、互不共享 .lake）：
#      - gate5-reject-defhole：门 5 配置校验必须拒收非空 definition_names（退 1）；
#      - sample-green：Sample.Challenge 与 Sample.Solution 分目录构建与比对，须退 0；
#      - defhole-control：definition_names 为空时替换定义须退 1；
#      - defhole-filled：definition_names 非空时记录 Lake 实测退出码（4.36.0 实测退 0，
#        作为门 5 必须拒收非空 definition_names 的实测依据）。
#   2. 正式比对（当传入 --repo 且仓内存在配置文件时）：
#      - 配置默认取 `formal_math/verification/comparator.json`（受信文件，符合 precheck.py 现有顶层表），
#        也兼容未来列入 decl 角色的 `formal_math/comparator.json`；二者不可同时存在；
#      - 严格校验：definition_names 必为空、permitted_axioms 仅限标准三公理、challenge_module 必在声明/挑战目录、
#        禁止配置中指定 external_kernels 或 enable_nanoda；
#      - 挑战模块在被审代码从未存在也从未写过的独立目录 `chal/`（只含基线配置与声明/挑战源码，
#        物理上不含任何证明目录）内离线沙箱构建并只读导出 `challenge.export`；
#      - 解答模块在另一干净独立目录 `sol/` 内经 `lake comparator --challenge-from-export` 比对，
#        依赖目录全程只读挂载且剥除 `--share-net`。
# 本文件在仓内保持 100644 模式，一律以 `bash comparator.sh ...` 调用。
set -euo pipefail

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONUSERBASE

repo=""
base=""
head=""
packages=""
config_path=""
skip_samples=0
paranoid=0
timeout_sec=3600

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) repo=${2:?}; shift 2 ;;
    --base) base=${2:?}; shift 2 ;;
    --head) head=${2:?}; shift 2 ;;
    --packages) packages=${2:?}; shift 2 ;;
    --config-path) config_path=${2:?}; shift 2 ;;
    --skip-samples) skip_samples=1; shift ;;
    --paranoid) paranoid=1; shift ;;
    --timeout-sec) timeout_sec=${2:?}; shift 2 ;;
    *) echo "comparator.sh: 未知参数: $1" >&2; exit 2 ;;
  esac
done

here=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
real_bwrap=$(command -v bwrap || true)
[ -n "$real_bwrap" ] && [ -x "$real_bwrap" ] || { echo "comparator.sh: 找不到可执行的 bwrap" >&2; exit 2; }

work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fm-comparator-XXXXXX")
trap 'chmod -R u+w -- "$work" 2>/dev/null || true; rm -rf -- "$work"' EXIT

status=0

# 在完全隔离的 chal_dir 中离线沙箱构建 challenge_mod，并在纯只读离线沙箱中导出 challenge.export。
# 注意：本函数可能被置于 `if` / `||` 下（Bash 会关闭函数体内 set -e），因此每条关键命令均显式失败返回。
build_and_export_challenge() {
  local chal_dir=$1 chal_mod=$2 export_out=$3 pkg_dir=$4 lean_path_extra=$5
  shift 5
  local targets=("$@")

  local want_tc want_ver actual_ver prefix
  want_tc=$(tr -d '\r\n' < "$chal_dir/lean-toolchain") || return 2
  want_ver=${want_tc#leanprover/lean4:v}
  if [ "$want_ver" = "$want_tc" ] || [ -z "$want_ver" ]; then
    echo "comparator.sh: lean-toolchain 格式不合: $want_tc" >&2
    return 2
  fi
  actual_ver=$(cd "$chal_dir" && lean --version) || return 2
  case "$actual_ver" in
    "Lean (version ${want_ver},"*) ;;
    *)
      echo "comparator.sh: 运行中 Lean ($actual_ver) 与工具链 v$want_ver 不符" >&2
      return 2
      ;;
  esac

  prefix=$(cd "$chal_dir" && lean --print-prefix) || return 2
  prefix=$(cd -P -- "$prefix" && pwd) || return 2
  [ -x "$prefix/bin/leanexport" ] || { echo "comparator.sh: 找不到 $prefix/bin/leanexport" >&2; return 2; }

  mkdir -p -- "$chal_dir/.lake" || return 2
  local build_binds=(--ro-bind "$chal_dir" "$chal_dir" --bind "$chal_dir/.lake" "$chal_dir/.lake" --ro-bind "$prefix" "$prefix")
  if [ -n "$pkg_dir" ]; then
    mkdir -p -- "$chal_dir/.lake/packages" || return 2
    build_binds+=(--ro-bind "$pkg_dir" "$chal_dir/.lake/packages")
  fi

  timeout --signal=TERM --kill-after=30 "$timeout_sec" \
    "$real_bwrap" --ro-bind / / \
      --tmpfs /home --tmpfs /root --tmpfs /run --tmpfs /var --tmpfs /tmp \
      --dir /tmp/home --dev /dev --proc /proc \
      "${build_binds[@]}" \
      --clearenv \
      --setenv HOME /tmp/home \
      --setenv TMPDIR /tmp \
      --setenv LANG C.UTF-8 \
      --setenv PATH "$prefix/bin:/usr/bin:/bin" \
      --setenv LEAN_ABORT_ON_PANIC 1 \
      --unshare-all --die-with-parent --new-session --chdir "$chal_dir" -- \
      lake build "$chal_mod" || return $?

  local export_lp="$chal_dir/.lake/build/lib/lean"
  if [ -n "$lean_path_extra" ]; then
    export_lp="${lean_path_extra}:${export_lp}"
  fi
  local exp_binds=(--ro-bind "$chal_dir" "$chal_dir" --ro-bind "$prefix" "$prefix")
  if [ -n "$pkg_dir" ]; then
    exp_binds+=(--ro-bind "$pkg_dir" "$pkg_dir")
  fi

  timeout --signal=TERM --kill-after=30 "$timeout_sec" \
    "$real_bwrap" --ro-bind / / \
      --tmpfs /home --tmpfs /root --tmpfs /run --tmpfs /var --tmpfs /tmp \
      --dir /tmp/home --dev /dev --proc /proc \
      "${exp_binds[@]}" \
      --clearenv \
      --setenv HOME /tmp/home \
      --setenv TMPDIR /tmp \
      --setenv LANG C.UTF-8 \
      --setenv PATH "$prefix/bin:/usr/bin:/bin" \
      --setenv LEAN_PATH "$export_lp" \
      --setenv LEAN_ABORT_ON_PANIC 1 \
      --unshare-all --die-with-parent --new-session --chdir "$chal_dir" -- \
      "$prefix/bin/leanexport" "$chal_mod" -- "${targets[@]}" > "$export_out" || return $?
  [ -s "$export_out" ] || { echo "comparator.sh: challenge.export 为空" >&2; return 2; }
  return 0
}

run_sample_case() {
  local name=$1 want=$2 cfg_name=$3 chal_file=$4 sol_file=$5 extra_chal_defs=$6 extra_sol_defs=$7 want_pattern=${8:-}
  local case_dir=$work/sample_$name
  local chal=$case_dir/chal sol=$case_dir/sol cfg=$case_dir/$cfg_name chal_exp=$case_dir/chal.export
  local wrap=$case_dir/bwrap_sol.sh comp_log=$case_dir/comp.log

  mkdir -p -- "$chal/Sample" "$sol/Sample"
  cp -- "$here/comparator/lakefile.toml.in" "$chal/lakefile.toml"
  cp -- "$here/comparator/lean-toolchain.in" "$chal/lean-toolchain"
  cp -- "$here/comparator/lake-manifest.json.in" "$chal/lake-manifest.json"
  cp -- "$here/comparator/lakefile.toml.in" "$sol/lakefile.toml"
  cp -- "$here/comparator/lean-toolchain.in" "$sol/lean-toolchain"
  cp -- "$here/comparator/lake-manifest.json.in" "$sol/lake-manifest.json"
  cp -- "$here/comparator/$cfg_name" "$cfg"

  if [ "$extra_chal_defs" = 1 ]; then
    cp -- "$here/comparator/Sample/Defs.lean.in" "$chal/Sample/Defs.lean"
  fi
  cp -- "$here/comparator/Sample/${chal_file}.in" "$chal/Sample/${chal_file}"

  if [ "$extra_sol_defs" = 1 ]; then
    cp -- "$here/comparator/Sample/Defs.lean.in" "$sol/Sample/Defs.lean"
  fi
  cp -- "$here/comparator/Sample/${sol_file}.in" "$sol/Sample/${sol_file}"

  local vflags=(--allow-sample-modules)
  if [ "$want" = record ]; then
    vflags+=(--allow-def-names)
  fi
  local meta chal_mod targets=()
  meta=$(python3 -I "$here/materialize.py" validate-comparator-config --file "$cfg" "${vflags[@]}")
  chal_mod=""
  while IFS= read -r line; do
    case "$line" in
      CHALLENGE_MODULE=*) chal_mod=${line#CHALLENGE_MODULE=} ;;
      EXPORT_TARGET=*) targets+=("${line#EXPORT_TARGET=}") ;;
    esac
  done <<<"$meta"

  bash "$here/bwrap_pkgbind.sh" --emit "$wrap" --lake-dir "$sol/.lake" --bwrap "$real_bwrap" --offline

  echo "::group::lake comparator $name"
  local chal_rc=0 comp_rc=0
  build_and_export_challenge "$chal" "$chal_mod" "$chal_exp" "" "" "${targets[@]}" || chal_rc=$?
  if [ "$chal_rc" != 0 ]; then
    echo "::endgroup::"
    echo "::error::$name: 挑战构建或导出失败（退出 $chal_rc），未进入 lake comparator"
    status=1
    return 0
  fi
  (cd "$sol" && COMPARATOR_BWRAP="$wrap" timeout --signal=TERM --kill-after=30 "$timeout_sec" \
    lake comparator --config "$cfg" --challenge-from-export "$chal_exp") >"$comp_log" 2>&1 || comp_rc=$?
  cat "$comp_log"
  echo "::endgroup::"

  echo "$name: 退出 $comp_rc（期望 $want）"
  if [ "$want" = record ]; then
    if [ "$comp_rc" = 0 ]; then
      echo "$name: 实测 Lake 接受了 definition_names 中的锁定定义替换，证明门 5 必须拒收非空 definition_names。"
    else
      echo "::warning::$name: Lake 此次拒收了（退出 $comp_rc），与既有读数不符，请复核门 5 依据。"
    fi
  elif [ "$comp_rc" != "$want" ]; then
    echo "::error::$name: 退出 $comp_rc，期望 $want"
    status=1
  elif [ -n "$want_pattern" ] && ! grep -Fq "$want_pattern" "$comp_log"; then
    echo "::error::$name: 退出码符合 $want，但输出未包含预期诊断 '$want_pattern'"
    status=1
  fi
}

if [ "$skip_samples" = 0 ]; then
  # 先验证门 5 配置校验确会拒收非空 definition_names
  defhole_rc=0
  python3 -I "$here/materialize.py" validate-comparator-config \
    --file "$here/comparator/comparator-defhole.json" --allow-sample-modules >/dev/null 2>&1 || defhole_rc=$?
  if [ "$defhole_rc" != 1 ]; then
    echo "::error::gate5-reject-defhole: 期望退出 1，实际 $defhole_rc"
    status=1
  else
    echo "gate5-reject-defhole: 退出 1（符合预期：非空 definition_names 已拒收）"
  fi

  run_sample_case sample-green 0 comparator.json Challenge.lean Solution.lean 1 1 "Your solution is okay!"
  run_sample_case defhole-control 1 comparator-defhole-control.json ChallengeFalse.lean SolutionSwap.lean 1 0 "Const does not match"
  run_sample_case defhole-filled record comparator-defhole.json ChallengeFalse.lean SolutionSwap.lean 1 0
fi

# 正式比对（基于 git 提交对象，绝不读工作树）
if [ -n "$repo" ]; then
  [ -n "$base" ] && [ -n "$head" ] && [ -n "$packages" ] || {
    echo "comparator.sh: 指定 --repo 时必须同时指定 --base、--head、--packages" >&2
    exit 2
  }
  [ -d "$packages" ] || { echo "comparator.sh: 依赖目录不存在: $packages" >&2; exit 2; }
  packages=$(cd -P -- "$packages" && pwd)

  git_has() {
    GIT_NO_REPLACE_OBJECTS=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_GRAFT_FILE=/dev/null \
      git -C "$repo" -c core.hooksPath=/dev/null rev-parse --verify --quiet --end-of-options "${head}:$1" >/dev/null 2>&1
  }

  chosen=""
  if [ -n "$config_path" ]; then
    if git_has "$config_path"; then
      chosen=$config_path
    else
      echo "::error::指定的 comparator 配置不存在于提交 $head: $config_path"
      exit 1
    fi
  else
    has_trusted=0
    has_top=0
    git_has "formal_math/verification/comparator.json" && has_trusted=1 || true
    git_has "formal_math/comparator.json" && has_top=1 || true
    if [ "$has_trusted" = 1 ] && [ "$has_top" = 1 ]; then
      echo "::error::formal_math/verification/comparator.json 与 formal_math/comparator.json 同时存在，拒绝歧义配置"
      exit 1
    elif [ "$has_trusted" = 1 ]; then
      chosen="formal_math/verification/comparator.json"
    elif [ "$has_top" = 1 ]; then
      chosen="formal_math/comparator.json"
    fi
  fi

  if [ -z "$chosen" ]; then
    # 若 ChanChallenge/ 已落地任何 .lean 文件但缺少配置文件，禁止静默跳过。
    has_challenge_lean=$(GIT_NO_REPLACE_OBJECTS=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_GRAFT_FILE=/dev/null \
      git -C "$repo" -c core.hooksPath=/dev/null ls-tree -r --name-only "$head" -- formal_math/ChanChallenge 2>/dev/null \
      | grep -E '\.lean$' || true)
    if [ -n "$has_challenge_lean" ]; then
      echo "::error::formal_math/ChanChallenge/ 已存在 .lean 文件，但缺少 formal_math/verification/comparator.json，拒绝跳过正式比对"
      exit 1
    fi
    echo "formal_math/verification/comparator.json 与 formal_math/comparator.json 均不存在（ChanChallenge 未落地），正式比对跳过。"
  else
    formal_dir=$work/formal
    chal=$formal_dir/chal
    sol=$formal_dir/sol
    cfg=$formal_dir/comparator.json
    chal_exp=$formal_dir/challenge.export
    wrap=$formal_dir/bwrap_sol.sh
    mkdir -p -- "$formal_dir"

    python3 -I "$here/materialize.py" blob --repo "$repo" --rev "$head" --path "$chosen" --out "$cfg" >/dev/null
    meta=$(python3 -I "$here/materialize.py" validate-comparator-config --file "$cfg") || {
      echo "::error::门 5 配置校验失败: $chosen"
      exit 1
    }
    chal_mod=""
    targets=()
    while IFS= read -r line; do
      case "$line" in
        CHALLENGE_MODULE=*) chal_mod=${line#CHALLENGE_MODULE=} ;;
        EXPORT_TARGET=*) targets+=("${line#EXPORT_TARGET=}") ;;
      esac
    done <<<"$meta"

    # 挑战目录：只放基线三配置 + 声明/挑战源码，物理上不含任何证明文件
    pkg_lines=$(python3 -I "$here/materialize.py" challenge --repo "$repo" --base "$base" --head "$head" --out "$chal")
    lp_extra=""
    while IFS= read -r line; do
      case "$line" in
        "PACKAGE "*)
          p="${packages}/${line#PACKAGE }/.lake/build/lib/lean"
          lp_extra="${lp_extra:+${lp_extra}:}${p}"
          ;;
      esac
    done <<<"$pkg_lines"

    # 解答目录：独立干净目录
    python3 -I "$here/materialize.py" audited --repo "$repo" --base "$base" --head "$head" --out "$sol" >/dev/null
    bash "$here/bwrap_pkgbind.sh" --emit "$wrap" --lake-dir "$sol/.lake" --packages "$packages" --bwrap "$real_bwrap" --offline

    comp_args=(lake comparator --config "$cfg" --challenge-from-export "$chal_exp")
    if [ "$paranoid" = 1 ]; then
      comp_args+=(--paranoid)
    fi

    echo "::group::lake comparator formal ($chosen)"
    chal_rc=0
    comp_rc=0
    build_and_export_challenge "$chal" "$chal_mod" "$chal_exp" "$packages" "$lp_extra" "${targets[@]}" || chal_rc=$?
    if [ "$chal_rc" != 0 ]; then
      echo "::endgroup::"
      echo "::error::formal ($chosen): 挑战构建或导出失败（退出 $chal_rc），未进入 lake comparator"
      status=1
    else
      if [ -x /usr/bin/time ]; then
        (cd "$sol" && COMPARATOR_BWRAP="$wrap" timeout --signal=TERM --kill-after=30 "$timeout_sec" /usr/bin/time -v "${comp_args[@]}") || comp_rc=$?
      else
        (cd "$sol" && COMPARATOR_BWRAP="$wrap" timeout --signal=TERM --kill-after=30 "$timeout_sec" "${comp_args[@]}") || comp_rc=$?
      fi
      echo "::endgroup::"
      echo "formal ($chosen): 退出 $comp_rc（期望 0）"
      if [ "$comp_rc" != 0 ]; then
        status=1
      fi
    fi

    if [ -n "$(ls -A "$chal/.lake/packages" 2>/dev/null || true)" ] || \
       [ -n "$(ls -A "$sol/.lake/packages" 2>/dev/null || true)" ]; then
      echo "::error::异常：宿主机 .lake/packages 挂载点非空"
      exit 2
    fi
  fi
fi

exit "$status"
