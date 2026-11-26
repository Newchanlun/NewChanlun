#!/usr/bin/env bash
# formal_math CI 统一受信入口（#2315 FM-06）。
#
# 支持分阶段调用，让 GitHub Actions 在纯静态预检通过前不下载 elan / Mathlib 缓存：
#   --phase preflight  快速路径检查（未碰 formal_math 与受信文件即直接绿）+ 严格祖先与静态预检；
#                      写出 `need_heavy=true|false` 到 --output-file（如 $GITHUB_OUTPUT）。
#   --phase heavy      在只读依赖目录下依次跑：
#                        1. #2312 七步阻断门（run.py，从受信提交取出，stderr 重定向到文件，总超时，严判退出码）
#                        2. 门 4：run_lake_check.sh（独立干净目录，离线沙箱，依赖只读）
#                        3. 门 5：comparator.sh（样板自检 + 正式配置两段隔离比对）
#   --phase all        合并运行 preflight 与 heavy（本地/自测便捷入口）。
#
# 本文件在仓内保持 100644 模式，一律以 `bash run_pr_gate.sh ...` 调用。
set -euo pipefail

unset PYTHONPATH PYTHONSTARTUP PYTHONHOME PYTHONUSERBASE

phase="all"
mode="pr"
repo=""
base=""
head=""
before=""
branch=""
trusted_from=""
packages=""
output_file=""
log_dir=""
approved=0
skip_lake_check=0
skip_comparator=0
timeout_sec=3600

while [ "$#" -gt 0 ]; do
  case "$1" in
    --phase) phase=${2:?}; shift 2 ;;
    --mode) mode=${2:?}; shift 2 ;;
    --repo) repo=${2:?}; shift 2 ;;
    --base) base=${2:?}; shift 2 ;;
    --head) head=${2:?}; shift 2 ;;
    --before) before=${2:?}; shift 2 ;;
    --branch) [ "$#" -ge 2 ] || { echo "run_pr_gate.sh: --branch 缺少值" >&2; exit 2; }; branch=$2; shift 2 ;;
    --trusted-change-approved) approved=1; shift ;;
    --bootstrap-trusted-from) trusted_from=${2:?}; shift 2 ;;
    --packages) packages=${2:?}; shift 2 ;;
    --output-file) output_file=${2:?}; shift 2 ;;
    --log-dir) log_dir=${2:?}; shift 2 ;;
    --skip-lake-check) skip_lake_check=1; shift ;;
    --skip-comparator) skip_comparator=1; shift ;;
    --timeout-sec) timeout_sec=${2:?}; shift 2 ;;
    *) echo "run_pr_gate.sh: 未知参数: $1" >&2; exit 2 ;;
  esac
done

case "$phase" in preflight|heavy|all) ;; *) echo "run_pr_gate.sh: 非法 --phase: $phase" >&2; exit 2 ;; esac
case "$mode" in pr|main) ;; *) echo "run_pr_gate.sh: 非法 --mode: $mode" >&2; exit 2 ;; esac
[ -n "$repo" ] && [ -n "$base" ] && [ -n "$head" ] || {
  echo "用法：bash run_pr_gate.sh --phase <preflight|heavy|all> --mode <pr|main> --repo <仓库> --base <基线> --head <被审> --branch <分支名> [选项]" >&2
  exit 2
}

here=$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -P -- "$repo" && pwd)

sgit() {
  env -i PATH="$PATH" LC_ALL=C \
    GIT_NO_REPLACE_OBJECTS=1 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null \
    GIT_GRAFT_FILE=/dev/null GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0 \
    git -C "$repo" -c core.hooksPath=/dev/null -c advice.graftFileDeprecated=false "$@"
}

base_sha=$(sgit rev-parse --verify --quiet --end-of-options "${base}^{commit}") || {
  echo "run_pr_gate.sh: 解析不出基线提交: $base" >&2; exit 2
}
head_sha=$(sgit rev-parse --verify --quiet --end-of-options "${head}^{commit}") || {
  echo "run_pr_gate.sh: 解析不出被审提交: $head" >&2; exit 2
}
if [ -n "$trusted_from" ]; then
  trusted_sha=$(sgit rev-parse --verify --quiet --end-of-options "${trusted_from}^{commit}") || {
    echo "run_pr_gate.sh: 解析不出受信提交: $trusted_from" >&2; exit 2
  }
else
  trusted_sha=$base_sha
fi

work=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/fm-gate-XXXXXX")
trap 'chmod -R u+w -- "$work" 2>/dev/null || true; rm -rf -- "$work"' EXIT

write_out() {
  if [ -n "$output_file" ]; then
    printf '%s=%s\n' "$1" "$2" >> "$output_file"
  fi
}

do_preflight() {
  local precheck_py=$work/precheck.py
  python3 -I "$here/materialize.py" blob \
    --repo "$repo" --rev "$trusted_sha" \
    --path "formal_math/verification/precheck/precheck.py" \
    --out "$precheck_py" >/dev/null

  # 快速路径：用受信提交的 precheck.py 以空分支名核对唯一 merge-base..head。
  # 仅当（1）merge-base 唯一，（2）受管范围（formal_math/ 与两个仓根受信文件）零改动（含原始模式与目录节点），
  # （3）被审提交整棵 formal_math/ 通过全部形状检查时，precheck.py 才退 0 且输出精确绿行。
  local mb_target=""
  if [ "$mode" = pr ]; then
    mb_target=$base_sha
  elif [ "$mode" = main ] && [ -n "$before" ] && [ "$before" != "0000000000000000000000000000000000000000" ]; then
    if sgit rev-parse --verify --quiet --end-of-options "${before}^{commit}" >/dev/null 2>&1; then
      mb_target=$(sgit rev-parse --verify --quiet --end-of-options "${before}^{commit}")
    fi
  fi

  if [ -n "$mb_target" ]; then
    local mbs mb_count mb
    mbs=$(sgit merge-base --all -- "$mb_target" "$head_sha" || true)
    mb_count=$(printf '%s\n' "$mbs" | awk 'NF{c++} END{print c+0}')
    if [ "$mb_count" = 1 ]; then
      mb=$(printf '%s\n' "$mbs" | awk 'NF{print; exit}')
      local fp_out fp_rc=0
      fp_out=$(python3 -I "$precheck_py" "$repo" "$mb" "$head_sha" "" 2>/dev/null) || fp_rc=$?
      if [ "$fp_rc" = 0 ] && [ "$fp_out" = "PRECHECK GREEN OK ${head_sha} role=-" ]; then
        echo "FM_CI FAST_PATH_GREEN mode=${mode} head=${head_sha} merge_base=${mb} base=${base_sha} (未改动 formal_math 或受信文件)"
        write_out need_heavy false
        write_out fast_path true
        return 0
      fi
    fi
  fi

  # 改动了 formal_math 或受信文件（或形状有问题 / 无唯一 merge-base）：
  # 在任何联网下载之前，先严格核对基线祖先关系与静态预检。
  if ! sgit merge-base --is-ancestor -- "$base_sha" "$head_sha"; then
    echo "FM_CI RED NOT_ANCESTOR base=${base_sha} head=${head_sha} 基线不是被审提交的祖先，请先追平 main 后重试" >&2
    write_out need_heavy false
    return 1
  fi

  local pc_args=()
  if [ "$approved" = 1 ]; then
    pc_args+=(--trusted-change-approved)
  fi
  local pc_out pc_err=$work/precheck.stderr pc_rc=0
  pc_out=$(python3 -I "$precheck_py" "${pc_args[@]}" "$repo" "$base_sha" "$head_sha" "$branch" 2>"$pc_err") || pc_rc=$?
  [ -n "$pc_out" ] && printf '%s\n' "$pc_out"
  [ -s "$pc_err" ] && cat "$pc_err" >&2
  if [ "$pc_rc" != 0 ]; then
    echo "FM_CI PREFLIGHT_FAILED exit=${pc_rc} mode=${mode} base=${base_sha} head=${head_sha} branch=${branch}" >&2
    write_out need_heavy false
    return "$pc_rc"
  fi
  case "$pc_out" in
    "PRECHECK GREEN OK ${head_sha} role="*) ;;
    *)
      echo "FM_CI PREFLIGHT_FAULT 预检绿行格式不符: $pc_out" >&2
      write_out need_heavy false
      return 2
      ;;
  esac

  echo "FM_CI PREFLIGHT_OK mode=${mode} base=${base_sha} head=${head_sha} branch=${branch}"
  write_out need_heavy true
  write_out fast_path false
  return 0
}

do_heavy() {
  [ -n "$packages" ] && [ -d "$packages" ] || {
    echo "run_pr_gate.sh: heavy 阶段需要已准备好的只读 --packages 目录" >&2
    return 2
  }
  packages=$(cd -P -- "$packages" && pwd)

  local out_logs=${log_dir:-$work/logs}
  mkdir -p -- "$out_logs"

  # 1. 从受信提交提取 run.py 并在独立工作目录运行七步阻断门。
  # 按 run.py 契约：必须 python3 -I、不设 PYTHONPATH、stderr 重定向到文件、外层设总超时、严格以退出码判成败。
  local runner_py=$work/runner/run.py
  local runner_workdir=$work/run_workdir
  python3 -I "$here/materialize.py" blob \
    --repo "$repo" --rev "$trusted_sha" \
    --path "formal_math/verification/runner/run.py" \
    --out "$runner_py" >/dev/null

  local run_args=(
    --repo "$repo"
    --base "$base_sha"
    --head "$head_sha"
    --branch "$branch"
    --workdir "$runner_workdir"
    --packages "$packages"
  )
  if [ "$approved" = 1 ]; then
    run_args=(--trusted-change-approved "${run_args[@]}")
  fi
  if [ -n "$trusted_from" ]; then
    run_args=(--bootstrap-trusted-from "$trusted_sha" "${run_args[@]}")
  fi

  echo "::group::#2312 seven-step blocking gates (run.py)"
  local run_rc=0
  timeout --signal=TERM --kill-after=30 "$timeout_sec" \
    python3 -I "$runner_py" "${run_args[@]}" \
    >"$out_logs/run.stdout" 2>"$out_logs/run.stderr" || run_rc=$?
  cat "$out_logs/run.stdout"
  if [ "$run_rc" != 0 ] && [ -s "$out_logs/run.stderr" ]; then
    echo "--- run.py stderr (tail 200) ---" >&2
    tail -n 200 "$out_logs/run.stderr" >&2
  fi
  echo "::endgroup::"

  if [ "$run_rc" != 0 ]; then
    echo "FM_CI RED RUN_PY exit=${run_rc}" >&2
    return "$run_rc"
  fi
  # 按 run.py 契约：退出码 0 是唯一通过依据；另核对最后一行确实是 FM RESULT GREEN。
  local last_line
  last_line=$(tail -n 1 "$out_logs/run.stdout" || true)
  case "$last_line" in
    "FM RESULT GREEN "*) ;;
    *)
      echo "FM_CI FAULT RUN_PY 退出 0 但末行不是 FM RESULT GREEN: $last_line" >&2
      return 2
      ;;
  esac

  # 释放 run.py 工作目录，避免与后续门 4/5 叠加磁盘占用，也物理断绝共享目录。
  chmod -R u+w -- "$runner_workdir" 2>/dev/null || true
  rm -rf -- "$runner_workdir"

  # 2. 门 4：lake check（独立干净目录、只读依赖、断网沙箱）
  if [ "$skip_lake_check" = 0 ]; then
    echo "::group::Gate 4 kernel replay (lake check)"
    local lc_rc=0
    bash "$here/run_lake_check.sh" \
      --repo "$repo" --base "$base_sha" --head "$head_sha" \
      --packages "$packages" --timeout-sec "$timeout_sec" \
      --log "$out_logs/lake-check.log" || lc_rc=$?
    echo "::endgroup::"
    if [ "$lc_rc" != 0 ]; then
      echo "FM_CI RED LAKE_CHECK exit=${lc_rc}" >&2
      return "$lc_rc"
    fi
  fi

  # 3. 门 5：lake comparator（样板自检 + 正式配置两段隔离比对）
  if [ "$skip_comparator" = 0 ]; then
    local comp_rc=0
    bash "$here/comparator.sh" \
      --repo "$repo" --base "$base_sha" --head "$head_sha" \
      --packages "$packages" --timeout-sec "$timeout_sec" \
      >"$out_logs/comparator.log" 2>&1 || comp_rc=$?
    cat "$out_logs/comparator.log"
    if [ "$comp_rc" != 0 ]; then
      echo "FM_CI RED COMPARATOR exit=${comp_rc}" >&2
      return "$comp_rc"
    fi
  fi

  echo "FM_CI GREEN mode=${mode} base=${base_sha} head=${head_sha} branch=${branch}"
  return 0
}

case "$phase" in
  preflight)
    do_preflight
    ;;
  heavy)
    do_heavy
    ;;
  all)
    flag_file=$work/preflight.out
    output_file=$flag_file
    do_preflight
    if grep -qx 'need_heavy=true' "$flag_file"; then
      do_heavy
    fi
    ;;
esac
