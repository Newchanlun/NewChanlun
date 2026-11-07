"""审查员的一条 command_execution 是否把冻结候选补丁读进了输出（#1968，#1969 kimi BLOCK）。

Codex 记录的命令形如 `/bin/bash -lc '<脚本>'`。这里按 bash 语法静态切开脚本，不执行：引号、注释、heredoc 正文、
`$(...)` 按 shell 的含义处理；变量按执行顺序代回（同名取最后一次赋值，单引号里不代回，子 shell 与多段管道里的赋值
不外泄，`H=x cmd $H` 的前缀赋值不影响本命令的展开，未加引号的变量按空白分词）。求不出值的部分记为 _OPAQUE。
一个简单命令算读取，须同时满足：
- 去掉保留字 `do`/`then`/`else`/`{`/`time` 与 `NAME=val` 前缀后，第一个词就是 git，之后只有全局选项
  `-C <dir>`、`-c <k=v>`、`--no-pager`/`-P`、`--git-dir`、`--work-tree`，紧跟子命令 diff 或 show；
- 按 git 的实际输出规则会输出补丁：diff 两侧一边是冻结 head（`HEAD` 也算，审阅 checkout 已证实停在 head 且干净）、
  另一边是别的已知提交，只给一个提交时另一边是工作区；show 指名 head 的提交、`<other>..<head>` 范围，
  或 `<head>:<path>` 文件内容；
- 输出进了日志：本命令和其后管道段的 stdout 没被丢掉（/dev/null、关闭、写进之后没人读的文件），管道后面没有
  `true`/`:`/`head -0`/`grep -q` 这类吞输出的段；退出码没被掩盖：管道之后不接 `||`、`&`，前面不是 `||`，
  脚本末尾不是另起一段的 `true`/`:`/`exit 0`。

命令文本只说明脚本打算让 git 输出补丁，不说明它真的输出了：`if false; then git diff …; fi` 没执行，
`exec >/dev/null`、`export GIT_EXTERNAL_DIFF=true` 改的是之后命令的环境，textconv 保留 `diff --git`/`@@` 头而把内容
换掉（#1969 kimi BLOCK）。所以还要看这条事件实际记录的输出（Codex `aggregated_output`，约 1 MiB 截断、保留前部）：
其中须有一行就是冻结补丁的真实内容，见 FrozenPatch。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPAQUE = "\0"  # 无法静态求值的部分（`$(...)`、未知变量）；含它的词不会匹配任何 SHA 或命令名
_OPS = ("&&", "||", ";;", "|&", "&>>", "&>", ">>", ">|", ">&", "<<<", "<<-", "<<", "<&", "<>",
        ">", "<", "|", "&", ";", "(", ")")
_REDIRECTS = frozenset({"&>>", "&>", ">>", ">|", ">&", "<<<", "<<-", "<<", "<&", "<>", ">", "<"})
_PIPE = frozenset({"|", "|&"})
_RESERVED_PREFIX = frozenset({"do", "then", "else", "{", "time"})
_DECLARE = frozenset({"export", "declare", "local", "readonly", "typeset"})
_NAME = re.compile(r"[A-Za-z_]\w*")
_REV = re.compile(r"(HEAD|@|[0-9a-fA-F]{7,40})((?:[~^]\d*)*)")
_PATCH_ON = re.compile(r"-p|-u|--patch|-U\d*|--unified(?:=\d+)?|--patch-with-(?:stat|raw)")
_SUMMARY = re.compile(r"--(?:stat|numstat|shortstat|dirstat|dirstat-by-file|summary|compact-summary|raw)(?:=.*)?|-X.*")
_NO_OUTPUT = re.compile(r"--(?:name-only|name-status|check|output=.*)")
_VALUE_OPTIONS = frozenset({"-O", "-S", "-G", "-I"})

Part = tuple[str, str]  # (kind, text)，kind ∈ lit（未加引号）/ q（加引号）/ var（未加引号，展开后按空白分词）/ qvar / opaque


@dataclass
class _Command:
    words: list[list[Part]] = field(default_factory=list)
    redirects: list[tuple[str, list[Part]]] = field(default_factory=list)
    op: str = ""  # 结束本命令的控制符（括号除外）；脚本末尾为 ""


@dataclass
class _Expanded:
    argv: list[str]
    env_names: list[str]
    redirects: list[tuple[str, str]]


def _dollar(s: str, i: int, word: list[Part], quoted: bool = False) -> int:
    if s.startswith("$(", i):
        depth, j = 0, i + 1
        while j < len(s):
            depth += {"(": 1, ")": -1}.get(s[j], 0)
            j += 1
            if depth == 0:
                break
        word.append(("opaque", ""))
        return j
    if s.startswith("${", i):
        end = s.find("}", i)
        end = len(s) if end < 0 else end
        inner = s[i + 2:end]
        word.append(("qvar" if quoted else "var", inner) if _NAME.fullmatch(inner) else ("opaque", ""))
        return end + 1
    name = _NAME.match(s, i + 1)
    if name:
        word.append(("qvar" if quoted else "var", name.group()))
        return name.end()
    if i + 1 < len(s) and (s[i + 1].isdigit() or s[i + 1] in "@*#?$!-"):
        word.append(("opaque", ""))
        return i + 2
    word.append(("lit", "$"))
    return i + 1


def _double_quoted(s: str, i: int, word: list[Part]) -> int:
    word.append(("q", ""))
    while i < len(s) and s[i] != '"':
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] in '$`"\\\n':
            if s[i + 1] != "\n":
                word.append(("q", s[i + 1]))
            i += 2
        elif s[i] == "$":
            i = _dollar(s, i, word, quoted=True)
        elif s[i] == "`":
            end = s.find("`", i + 1)
            word.append(("opaque", ""))
            i = len(s) if end < 0 else end + 1
        else:
            word.append(("q", s[i]))
            i += 1
    return i + 1


def _text(word: list[Part]) -> str:
    return "".join(text for kind, text in word if kind in ("lit", "q"))


def _lex(s: str) -> list[tuple[str, object]]:
    """切成 ("word", parts) / ("op", 控制符) / ("redir", fd+重定向符) / ("body", heredoc 正文)；注释直接丢弃。
    heredoc 正文不当命令，只供判断前面写出的文件之后有没有被读。"""
    tokens: list[tuple[str, object]] = []
    word: list[Part] = []
    started = False
    heredocs: list[tuple[str, bool]] = []
    want_delimiter: bool | None = None

    def flush() -> None:
        nonlocal word, started, want_delimiter
        if started:
            tokens.append(("word", word))
            if want_delimiter is not None:
                heredocs.append((_text(word), want_delimiter))
                want_delimiter = None
        word, started = [], False

    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            if s[i + 1] != "\n":
                word.append(("q", s[i + 1]))
                started = True
            i += 2
        elif c in " \t\r":
            flush()
            i += 1
        elif c == "\n":
            flush()
            tokens.append(("op", "\n"))
            i += 1
            for delimiter, strip_tabs in heredocs:
                body = []
                while i < len(s):
                    end = s.find("\n", i)
                    end = len(s) if end < 0 else end
                    line, i = s[i:end], end + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
                    body.append(line)
                tokens.append(("body", "\n".join(body)))
            heredocs = []
        elif c == "#" and not started:
            end = s.find("\n", i)
            i = len(s) if end < 0 else end
        elif c == "'":
            end = s.find("'", i + 1)
            end = len(s) if end < 0 else end
            word.append(("q", s[i + 1:end]))
            started, i = True, end + 1
        elif c == '"':
            started, i = True, _double_quoted(s, i + 1, word)
        elif c == "`":
            end = s.find("`", i + 1)
            word.append(("opaque", ""))
            started, i = True, len(s) if end < 0 else end + 1
        elif c == "$":
            started, i = True, _dollar(s, i, word)
        elif c in ";&|()<>":
            fd = ""
            if c in "<>" and started and all(kind == "lit" and text.isdigit() for kind, text in word):
                fd, word, started = _text(word), [], False
            flush()
            op = next(o for o in _OPS if s.startswith(o, i))
            i += len(op)
            tokens.append(("redir" if op in _REDIRECTS else "op", fd + op))
            if op in ("<<", "<<-"):
                want_delimiter = op == "<<-"
        else:
            word.append(("lit", c))
            started, i = True, i + 1
    flush()
    return tokens


def _parse(tokens: list[tuple[str, object]]) -> list[_Command | str]:
    """按序给出简单命令和括号（"(" / ")"），每个命令的 op 是其后第一个非括号控制符。"""
    items: list[_Command | str] = []
    current = _Command()
    redirect: str | None = None
    for kind, value in tokens:
        if kind == "word":
            assert isinstance(value, list)
            if redirect is not None:
                current.redirects.append((redirect, value))
                redirect = None
            else:
                current.words.append(value)
        elif kind == "redir":
            assert isinstance(value, str)
            redirect = value
        elif kind == "body":
            assert isinstance(value, str)
            owner = next((x for x in reversed(items) if isinstance(x, _Command)), None)
            if owner is not None:
                owner.redirects.append(("<<body", [("q", value)]))
        else:
            assert isinstance(value, str)
            if current.words or current.redirects:
                items.append(current)
                current = _Command()
            items.append(value)
    if current.words or current.redirects:
        items.append(current)
    pending: list[_Command] = []
    for item in items:
        if isinstance(item, _Command):
            pending.append(item)
        elif item not in ("(", ")"):
            for command in pending:
                command.op = item
            pending = []
    return [x for x in items if isinstance(x, _Command) or x in ("(", ")")]


def _assignment(word: list[Part]) -> str | None:
    prefix = ""
    for kind, text in word:
        if kind != "lit":
            break
        prefix += text
    name, eq, _ = prefix.partition("=")
    return name if eq and _NAME.fullmatch(name) else None


def _expand(word: list[Part], env: dict[str, str]) -> str:
    """不分词的展开（赋值右侧、重定向目标）。"""
    return "".join(text if kind in ("lit", "q") else env.get(text, _OPAQUE) if kind in ("var", "qvar") else _OPAQUE
                   for kind, text in word)


def _fields(word: list[Part], env: dict[str, str]) -> list[str]:
    """命令参数的展开：未加引号的变量按空白分词（`D="git diff A B"; $D` 展开成四个参数）。"""
    fields: list[str] = []
    current: str | None = None
    for kind, text in word:
        if kind != "var":
            current = (current or "") + _expand([(kind, text)], env)
            continue
        value = env.get(text, _OPAQUE)
        pieces = value.split()
        if value[:1].isspace() and current is not None:
            fields.append(current)
            current = None
        for j, piece in enumerate(pieces):
            if j:
                fields.append(current or "")
                current = None
            current = (current or "") + piece
        if value[-1:].isspace() and current is not None:
            fields.append(current)
            current = None
    return fields if current is None else [*fields, current]


def _evaluate(items: list[_Command | str]) -> list[_Expanded]:
    scopes: list[dict[str, str]] = [{}]
    commands = [x for x in items if isinstance(x, _Command)]
    out: list[_Expanded] = []
    previous_op = ""
    for item in items:
        if item == "(":
            scopes.append(dict(scopes[-1]))
            continue
        if item == ")":
            if len(scopes) > 1:
                scopes.pop()
            continue
        assert isinstance(item, _Command)
        env = scopes[-1]
        words = list(item.words)
        while words and len(words[0]) and all(k == "lit" for k, _ in words[0]) and _text(words[0]) in _RESERVED_PREFIX:
            words.pop(0)
        assignments: dict[str, str] = {}
        while words and (name := _assignment(words[0])) is not None:
            assignments[name] = _expand(words.pop(0), env).partition("=")[2]
        argv = [field for w in words for field in _fields(w, env)]
        redirects = [(op, _expand(target, env)) for op, target in item.redirects]
        out.append(_Expanded(argv, list(assignments), redirects))
        persists = previous_op not in _PIPE and item.op not in _PIPE
        if persists and not argv:
            env.update(assignments)
        elif persists and argv[0] in _DECLARE:
            for arg in argv[1:]:
                name, eq, value = arg.partition("=")
                if eq and _NAME.fullmatch(name):
                    env[name] = value
        previous_op = item.op
    assert len(out) == len(commands)
    return out


def _discards_stdout(command: _Expanded, later: list[_Expanded]) -> bool:
    """stdout 被丢掉：重定向到 /dev/null、关闭或别的 fd；写进文件且之后没有命令提到这个文件。"""
    for op, target in command.redirects:
        fd = op.rstrip("<>&|")
        kind = op[len(fd):]
        if kind == ">&" and fd in ("", "1"):
            if target != "2":
                return True
        elif kind in ("&>", "&>>") or (fd in ("", "1") and kind in (">", ">>", ">|")):
            if target in ("/dev/null", "") or _OPAQUE in target or not any(
                    target in arg for c in later for arg in [*c.argv, *(t for _, t in c.redirects)]):
                return True
    return False


def _swallows(command: _Expanded, later: list[_Expanded]) -> bool:
    if _discards_stdout(command, later):
        return True
    argv = command.argv
    if not argv:
        return False
    name = argv[0].rsplit("/", 1)[-1]
    if name in ("true", ":", "false", "exit"):
        return True
    args = " ".join(argv[1:])
    if name in ("head", "tail"):
        return bool(re.search(r"(?:^|\s)(?:-[nc]?\s*0+|--(?:lines|bytes)=0+)(?:\s|$)", args))
    if name in ("grep", "egrep", "fgrep", "rg"):
        return any(re.fullmatch(r"-[A-Za-z]*q[A-Za-z]*|--quiet|--silent", a) for a in argv[1:])
    return False


class _Revisions:
    def __init__(self, head: str, others: tuple[str, ...]) -> None:
        self.head, self.others = head.lower(), tuple(o.lower() for o in others if o)

    def kind(self, token: str) -> str:
        """head / other（别的已知提交，或 head 的祖先写法）/ unknown（像 SHA 但不认识）/ path。"""
        match = _REV.fullmatch(token)
        if not match:
            return "path"
        base, suffix = match.group(1), match.group(2)
        if base in ("HEAD", "@") or self.head.startswith(base.lower()):
            return "other" if suffix else "head"
        if any(o.startswith(base.lower()) for o in self.others):
            return "other"
        return "unknown"


def _emits_patch(subcommand: str, options: list[str]) -> bool:
    """按 git 2.50 实测的输出规则：-s/--no-patch 清空之前的格式，-p 等显式打开补丁，
    统计类选项（show 的 -q 同类）去掉默认补丁，name-only/name-status/check/--output 与 diff 的 --quiet 不出补丁。"""
    explicit, summary, silent = False, False, False
    for option in options:
        if _PATCH_ON.fullmatch(option):
            explicit = True
        elif option in ("-s", "--no-patch"):
            explicit, summary, silent = False, True, False
        elif _SUMMARY.fullmatch(option) or (subcommand == "show" and option in ("-q", "--quiet")):
            summary = True
        elif _NO_OUTPUT.fullmatch(option) or (subcommand == "diff" and option in ("--quiet", "--exit-code")):
            silent = True
    return not silent and (explicit or not summary)


def _git_patch_read(command: _Expanded, revisions: _Revisions) -> bool:
    argv = command.argv
    if not argv or argv[0].rsplit("/", 1)[-1] != "git":
        return False
    i, config = 1, []
    while i < len(argv):
        if argv[i] in ("-C", "-c", "--git-dir", "--work-tree"):
            config += argv[i + 1:i + 2] if argv[i] == "-c" else []
            i += 2
        elif argv[i] in ("--no-pager", "-P") or argv[i].startswith(("--git-dir=", "--work-tree=")):
            i += 1
        else:
            break
    if i >= len(argv) or argv[i] not in ("diff", "show"):
        return False
    subcommand, rest = argv[i], argv[i + 1:]
    separator = rest.index("--") if "--" in rest else len(rest)
    options, positional, skip = [], [], False
    for arg in rest[:separator]:
        if skip:
            skip = False
        elif arg.startswith("-") and arg != "-":
            options.append(arg)
            skip = arg in _VALUE_OPTIONS
        else:
            positional.append(arg)
    if "--no-index" in options or (subcommand == "show" and "--output" in " ".join(options)):
        return False
    external = "GIT_EXTERNAL_DIFF" in command.env_names or any(
        re.match(r"diff\.(?:external|[^=]*\.command)=", c, re.IGNORECASE) for c in config)
    if external and "--no-ext-diff" not in options:
        return False
    # 补丁走 stdout 的前提下，blob 内容不受输出格式选项影响；提交和范围要看格式选项，且不能混进求不出值的参数
    # （`$X` 可能就是 `-s`）。diff 在 `--` 之前只接受认识的提交：像 `'$H'`、`<head>x` 这样的词 git 会当路径，
    # 路径不存在就报错，接了管道后退出码仍是 0。
    unresolved = any(_OPAQUE in arg for arg in rest[:separator])
    kinds: list[str] = []
    for arg in positional:
        if subcommand == "show":
            base, colon, path = arg.partition(":")
            if colon:
                if path and revisions.kind(base) == "head":
                    return True
            elif not unresolved and _emits_patch(subcommand, options):
                left, dots, right = arg.partition("..")
                pair = [revisions.kind(left or "HEAD"), revisions.kind(right.lstrip(".") or "HEAD")]
                if (pair == ["other", "head"] if dots else revisions.kind(arg) == "head"):
                    return True
            continue
        left, dots, right = arg.partition("..")
        sides = [left or "HEAD", right.lstrip(".") or "HEAD"] if dots else [arg]
        resolved = [revisions.kind(side) for side in sides]
        if not all(kind in ("head", "other") for kind in resolved):
            return False
        kinds += resolved
    if subcommand == "show" or unresolved:
        return False
    if len(kinds) == 1:
        kinds.append("head")  # 一个提交对工作区或索引；审阅 checkout 已证实停在 head 且干净
    return "head" in kinds and "other" in kinds and _emits_patch(subcommand, options)


def _script(command: str) -> str | None:
    """取出 Codex 外层 `/bin/bash -lc '<脚本>'` 的脚本；不是这个形状时按原文当脚本。"""
    commands = _parse(_lex(command))
    if len(commands) == 1 and isinstance(commands[0], _Command):
        argv = [field for w in commands[0].words for field in _fields(w, {})]
        if (len(argv) == 3 and argv[0].rsplit("/", 1)[-1] in ("bash", "sh", "zsh")
                and re.fullmatch(r"-[a-z]*c[a-z]*", argv[1])):
            return None if _OPAQUE in argv[2] else argv[2]
    return command


_LINE_NUMBER = re.compile(r"\d+[\t:]")  # `nl -ba`、`cat -n`、`grep -n` 加在行首的行号
_DISTINCT = 12  # 够长的改动行才当证据；`}`、`return` 这类短行在任何文件里都可能出现


@dataclass(frozen=True)
class FrozenPatch:
    """controller 侧取得的冻结候选补丁。`evidence` 是审查员输出里须出现的行（去掉首尾空白）：
    改动行（`+`/`-` 之后的内容）里至少 _DISTINCT 个字符的；没有这样的行就取全部非空改动行；
    纯二进制、改名、改权限的补丁没有改动行，取 `diff --git` 头。"""
    head_sha: str
    other_shas: tuple[str, ...]
    evidence: frozenset[str]

    @classmethod
    def from_diff(cls, head_sha: str, other_shas: tuple[str, ...], diff: str) -> FrozenPatch:
        changed = {line[1:].strip() for line in diff.splitlines()
                   if line[:1] in "+-" and not line.startswith(("+++ ", "--- "))} - {""}
        headers = {line for line in diff.splitlines() if line.startswith("diff --git ")}
        return cls(head_sha, other_shas,
                   frozenset({line for line in changed if len(line) >= _DISTINCT} or changed or headers))

    def shown_in(self, output: str) -> bool:
        """输出里有一行（去掉行号前缀、diff 的 `+`/`-`/空格标记后）是冻结补丁的改动内容。
        `git show <head>:<path>` 输出的是新文件，加进来的行同样在其中。"""
        for raw in output.splitlines():
            line = raw.strip()
            if match := _LINE_NUMBER.match(line):
                line = line[match.end():].strip()
            if line in self.evidence or (line[:1] in "+-" and line[1:].strip() in self.evidence):
                return True
        return False


def reads_candidate_patch(command: str, output: str, patch: FrozenPatch) -> bool:
    """命令按 bash 语义会让 git 输出冻结补丁，且记录的输出里真有冻结补丁的内容。"""
    return _would_print_patch(command, patch.head_sha, patch.other_shas) and patch.shown_in(output)


def _would_print_patch(command: str, head_sha: str, other_shas: tuple[str, ...]) -> bool:
    """`other_shas` 是同一冻结目标里别的已知提交（merge-base、base）；diff 另一侧须是它们或 head 的祖先写法，
    写一个不存在的 SHA 再接管道（`git diff <bad> <head> | head`，无 pipefail 时退出码为 0）不算读取。"""
    script = _script(command)
    if script is None:
        return False
    items = _parse(_lex(script))
    commands = [x for x in items if isinstance(x, _Command)]
    expanded = _evaluate(items)
    revisions = _Revisions(head_sha, other_shas)
    last = expanded[-1] if expanded else None
    trailing_mask = (len(commands) > 1 and commands[-2].op in (";", "\n", "&", ";;")
                     and last is not None and not last.redirects
                     and (last.argv in (["true"], [":"], ["exit"], ["exit", "0"])))
    for k, simple in enumerate(expanded):
        if _discards_stdout(simple, expanded[k + 1:]) or not _git_patch_read(simple, revisions):
            continue
        end = k
        while commands[end].op in _PIPE and end + 1 < len(commands):
            end += 1
        if any(_swallows(expanded[j], expanded[j + 1:]) for j in range(k + 1, end + 1)):
            continue
        if commands[end].op in ("||", "&") or (k and commands[k - 1].op == "||"):
            continue
        if trailing_mask and end < len(commands) - 1:
            continue
        return True
    return False
