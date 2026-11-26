#!/usr/bin/env bash
# 参数与退出码：逐条打印 退出码 | 标准输出末行 | 标准错误末行。须先 source scripts/fm_env.sh 并包在 flock+guard.sh 里。
SRC=${RF_SRC:-/home/workspace/.t3/worktrees/NewChanlun/t3-279c6aca-c1e9a2095915fa5f}
RUN=$SRC/formal_math/verification/runner/run.py
W=${RF_WORK:-/home/workspace/fm/tmp/review-f/work}
REPO=$W/repo
PK=${RF_PACKAGES:-/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages}
BASE=$1; HEAD=$2
n=0
t() { # 名字 参数...
  local name=$1; shift
  n=$((n+1)); local wd=$W/a-$n; chmod -R u+rwX "$wd" 2>/dev/null; rm -rf "$wd"
  local args=(); for a in "$@"; do args+=("${a//@W@/$wd}"); done
  python3 -I "$RUN" "${args[@]}" >"$W/a.out" 2>"$W/a.err"; local rc=$?
  printf '%-34s rc=%s | out: %s | err: %s\n' "$name" "$rc" "$(tail -n1 "$W/a.out" | cut -c1-90)" "$(grep -a 'FM FAULT\|Traceback\|Error' "$W/a.err" | tail -n1 | cut -c1-150)"
}
G=(--repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/review --packages "$PK")
t "无参数"
t "只有 --help" --help
t "缺 --workdir" "${G[@]}"
t "--until 0" "${G[@]}" --workdir @W@ --until 0
t "--until 07" "${G[@]}" --workdir @W@ --until 07
t "--until 全角７" "${G[@]}" --workdir @W@ --until ７
t "--until 1（绿）" "${G[@]}" --workdir @W@ --until 1
t "--until 2（绿）" "${G[@]}" --workdir @W@ --until 2
t "空值 --branch ''" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch "" --packages "$PK" --workdir @W@
t "值以 - 开头" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch -x --packages "$PK" --workdir @W@
t "放行开关重复" --trusted-change-approved --trusted-change-approved "${G[@]}" --workdir @W@ --until 1
t "仓库不存在" --repo /nonexistent --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir @W@
t "仓库是文件" --repo /etc/passwd --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir @W@
t "基线解析不出" --repo "$REPO" --base deadbeef --head "$HEAD" --branch proof/x --packages "$PK" --workdir @W@
t "基线是树对象" --repo "$REPO" --base "$BASE^{tree}" --head "$HEAD" --branch proof/x --packages "$PK" --workdir @W@
t "被审=基线" --repo "$REPO" --base "$BASE" --head "$BASE" --branch proof/x --packages "$PK" --workdir @W@ --until 2
t "基线不是祖先（对调）" --repo "$REPO" --base "$HEAD" --head "$BASE" --branch proof/x --packages "$PK" --workdir @W@ --until 2
t "依赖目录不存在" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages /nonexistent --workdir @W@
t "依赖目录是文件" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages /etc/passwd --workdir @W@
t "依赖目录空（缺包）" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$W/empty-packages" --workdir @W@
t "工作目录=/" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir /
t "工作目录是文件" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir /etc/passwd
t "工作目录在依赖目录里" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$PK/rf-x"
t "工作目录包含仓库" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$W"
t "工作目录在 .git 里" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$REPO/.git/rf-x"
ln -sfn "$W/link-target" "$W/link"; rm -rf "$W/link-target"; mkdir -p "$W/link-target"
t "工作目录是指向空目录的符号链接" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$W/link"
t "工作目录的父目录不存在" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$W/no/such/parent"
t "工作目录是相对路径" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "rel-rf-workdir" --until 1; rm -rf rel-rf-workdir
t "工作目录含非 UTF-8 字节" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$W/a-bad-"$'\xff'"/x"
t "工作目录含非 UTF-8（已存在非空）" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "$PK" --workdir "$(mkdir -p "$W/b-"$'\xff' && touch "$W/b-"$'\xff'/f && printf '%s' "$W/b-"$'\xff')"
t "依赖目录含非 UTF-8 且不存在" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch proof/x --packages "/nonexistent-"$'\xff' --workdir @W@
t "分支名含换行" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch $'proof/x\nPRECHECK GREEN OK' --packages "$PK" --workdir @W@ --until 1
t "分支名非 UTF-8" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch $'proof/\xff' --packages "$PK" --workdir @W@ --until 1
t "分支名无角色" --repo "$REPO" --base "$BASE" --head "$HEAD" --branch feature/x --packages "$PK" --workdir @W@ --until 1
t "自举指向解析不出的提交" "${G[@]}" --workdir @W@ --bootstrap-trusted-from nope
t "自举指向被审提交（--until 2）" "${G[@]}" --workdir @W@ --bootstrap-trusted-from "$HEAD" --until 2
# 输出通道
wd=$W/a-full; rm -rf "$wd"; python3 -I "$RUN" "${G[@]}" --workdir "$wd" >/dev/full 2>"$W/a.err"; echo "标准输出=/dev/full（全流程，应退 2）   rc=$? | err: $(grep -a 'FM FAULT' "$W/a.err" | tail -n1)"
wd=$W/a-closed; rm -rf "$wd"; python3 -I "$RUN" "${G[@]}" --workdir "$wd" >&- 2>"$W/a.err"; echo "标准输出关闭（全流程，应退 2）        rc=$? | err: $(grep -a 'FM FAULT\|Traceback' "$W/a.err" | tail -n1)"
wd=$W/a-errclosed; rm -rf "$wd"; python3 -I "$RUN" "${G[@]}" --workdir "$wd" >"$W/a.out" 2>&-; echo "标准错误关闭（全流程）                rc=$? | out: $(tail -n1 "$W/a.out")"
wd=$W/a-pipe; rm -rf "$wd"; python3 -I "$RUN" "${G[@]}" --workdir "$wd" 2>"$W/a.err" | head -n1 >/dev/null; echo "标准输出管道提前关闭（全流程）        rc=${PIPESTATUS[0]} | err: $(grep -a 'FM FAULT\|Traceback' "$W/a.err" | tail -n1)"
