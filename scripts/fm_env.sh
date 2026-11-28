# 在 Bash 或 Zsh 中 source 此脚本，工具链按 formal_math 的钉选解析。
if [ -n "${ZSH_VERSION:-}" ]; then
  _fm_script=${(%):-%x}
else
  _fm_script=${BASH_SOURCE[0]}
fi

_fm_setup() {
  local script=$1 root lake store target actual version hash
  root=$(cd -P -- "$(dirname -- "$script")/.." && pwd) || return 1
  lake=$root/formal_math/.lake
  case $(uname -s) in
    Darwin)
      store=/Volumes/AgentStorage/fm
      if [ ! -d /Volumes/AgentStorage ] ||
         [ "$(stat -f %d /Volumes/AgentStorage)" = "$(stat -f %d /System/Volumes/Data)" ]; then
        printf '%s\n' 'FM: AgentStorage 未挂载在独立卷上。' >&2
        return 1
      fi
      hash=$(printf '%s' "$root" | shasum -a 256 | cut -c1-16) || return 1
      target=$store/lake/${root##*/}-$hash
      export TMPDIR=$store/tmp
      mkdir -p -- "$TMPDIR" "$target" || return 1
      if [ ! -L "$lake" ] && [ ! -e "$lake" ]; then
        ln -s -- "$target" "$lake" || return 1
      fi
      if [ ! -L "$lake" ] || [ "$(readlink "$lake")" != "$target" ]; then
        printf 'FM: %s 必须是指向 %s 的符号链接；原件未修改。\n' "$lake" "$target" >&2
        return 1
      fi
      ;;
    Linux)
      export TMPDIR=/home/workspace/fm/tmp
      mkdir -p -- "$TMPDIR" || return 1
      ;;
    *) printf '%s\n' 'FM: 仅支持 macOS 与 Linux。' >&2; return 1 ;;
  esac
  case ":$PATH:" in
    *":$HOME/.elan/bin:"*) ;;
    *) export PATH="$HOME/.elan/bin:$PATH" ;;
  esac
  actual=$lake
  if [ -d "$lake" ]; then
    actual=$(cd -P -- "$lake" && pwd) || return 1
  fi
  version=$(cd -- "$root/formal_math" && lean --version) || return 1
  printf 'TMPDIR=%s\n.lake=%s\n%s\n' "$TMPDIR" "$actual" "$version"
}

if _fm_setup "$_fm_script"; then
  unset -f _fm_setup
  unset _fm_script
else
  unset -f _fm_setup
  unset _fm_script
  return 1
fi
