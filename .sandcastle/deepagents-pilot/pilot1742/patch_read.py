"""审查员的一条 command_execution 是否把冻结候选补丁读进了输出（#1968，#1969 kimi BLOCK）。

防护边界：这道门防的是审查员没读补丁就给结论，包括零工具、只读无关文件、空输出、输出被丢掉或吞掉、
同一条命令里别的段拼出伪造的改动行这类无意或低成本的情形。它不是沙箱，不对抗刻意构造 shell 来骗过这里的
静态分析的审查员；那要在执行层隔离（审查容器只读 home、专用的补丁读取工具），见 #1971。判断一个写法该不该拦，
先看它属于哪一边：审查员顺手写出来的命令会碰到的，在这里拦；只有存心伪造才会写出来的，记进 #1971。
在这个边界内，看不懂的写法一律判未读取，不猜：`$'…'`、`$"…"`、命令替换、未知变量、含换行或其他行终止符的参数。

Codex 记录的命令形如 `/bin/bash -lc '<脚本>'`。这里按 bash 语法静态切开脚本，不执行：引号、注释、heredoc 正文、
`$(...)` 按 shell 的含义处理；变量按执行顺序代回（同名取最后一次赋值，单引号里不代回，子 shell 与多段管道里的赋值
不外泄，`H=x cmd $H` 的前缀赋值不影响本命令的展开，未加引号的变量按空白分词）。求不出值的部分记为 _OPAQUE。
整条命令须是这个形状，其中恰好一个简单命令是 git 读取：
- git 读取：去掉保留字 `do`/`then`/`else`/`{`/`time` 与 `NAME=val` 前缀后，第一个词就是 `git`（或 `/usr/bin/git`），
  之后只有全局选项 `-C <dir>`、`-c <k=v>`（只认 _CONFIG_KEYS）、`--no-pager`/`-P`、`--git-dir`、`--work-tree`，
  紧跟子命令 diff 或 show，且不带会印出自定文字的选项（`--format=<格式串>`、`--line-prefix`）；
  按 git 的实际输出规则会输出补丁：diff 两侧一边是冻结 head（`HEAD` 也算，审阅 checkout 已证实停在 head 且干净）、
  另一边是别的已知提交，只给一个提交时另一边是工作区；show 指名 head 的提交、`<other>..<head>` 范围，
  或 `<head>:<path>` 文件内容；stdout 没被丢掉（/dev/null、关闭、写进文件）。
- git 之前只有不输出的段（_setup），用 `&&`、`;` 或换行接上；git 之后只有经管道串联的纯过滤器（_FILTERS），
  管道就是脚本的结尾。别的命令（echo、printf、cat 文件、tee、python、另一条 git……）只要出现，整条命令就不算：
  aggregated_output 是整条命令的输出，那些段印出的改动行与 git 印出的分不开（#1969 正式审查 kimi BLOCK）。

命令文本只说明脚本打算让 git 输出补丁，不说明它真的输出了：`if false; then git diff …; fi` 没执行，
`exec >/dev/null`、`export GIT_EXTERNAL_DIFF=true` 改的是之后命令的环境，textconv 保留 `diff --git`/`@@` 头而把内容
换掉（#1969 kimi BLOCK）。所以还要看这条事件实际记录的输出（Codex `aggregated_output`，约 1 MiB 截断、保留前部）：
其中须有一行就是冻结补丁的真实内容，见 FrozenPatch。输出只按 `\n` 切行，含其他行终止符的行不当证据。
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
_CONFIG_KEYS = frozenset({"core.quotepath", "core.hookspath", "core.excludesfile"})  # 不改 diff/show 输出的配置
_NAMED_FORMAT = r"oneline|short|medium|full|fuller|reference|email|raw|mboxrd"
_PRINTS_TEXT = re.compile(rf"--(?:pretty|format)=(?!(?:{_NAMED_FORMAT})$).*|--format|--line-prefix(?:=.*)?")
_BREAK = re.compile("[\r\x0b\x0c\x1c-\x1e\x85\u2028\u2029]")  # str.splitlines 认作换行、而 `\n` 切行不认的字符

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
    if not quoted and s[i + 1:i + 2] in ("'", '"'):
        word.append(("opaque", ""))  # `$'…'` 会解码 `\n` 等转义，`$"…"` 按语言环境翻译；合法审查用不到，整条拒绝
        return i + 1
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
    # `-c` 能换掉 git 的输出（diff.external、textconv、core.pager、format.pretty……），只认不影响输出的几项；
    # 补丁旁边能印出审查员自己写的文字的选项（`--format='+<改动行>'`、`--line-prefix`）也不认（#1969 kimi BLOCK）
    if any(c.partition("=")[0].lower() not in _CONFIG_KEYS for c in config) or any(
            _PRINTS_TEXT.fullmatch(o) for o in options):
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


def _lines(text: str) -> list[str]:
    """只按 `\n`（及 `\r\n`）切行。git 与过滤器把参数原样写进报错，`str.splitlines` 还会在 U+2028 等处切开，
    参数里的这些字符就成了一行伪造的证据（#1969 opus BLOCK）。"""
    return [line.removesuffix("\r") for line in text.split("\n")]


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
        changed = {line[1:].strip() for line in _lines(diff)
                   if line[:1] in "+-" and not line.startswith(("+++ ", "--- ")) and not _BREAK.search(line)} - {""}
        headers = {line for line in _lines(diff) if line.startswith("diff --git ")}
        return cls(head_sha, other_shas,
                   frozenset({line for line in changed if len(line) >= _DISTINCT} or changed or headers))

    def shown_in(self, output: str) -> bool:
        """输出里有一行（去掉行号前缀、diff 的 `+`/`-`/空格标记后）是冻结补丁的改动内容。
        `git show <head>:<path>` 输出的是新文件，加进来的行同样在其中。含 _BREAK 字符的行不当证据：
        它在别的切行规则下可能是两行。"""
        for raw in _lines(output):
            if _BREAK.search(raw):
                continue
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
    写一个不存在的 SHA 再接管道（`git diff <bad> <head> | head`，无 pipefail 时退出码为 0）不算读取。
    命令替换会执行别的命令，含换行或其他行终止符（U+2028 等）的参数会被 git 或过滤器的报错原样带进输出
    （`git show <head>:'x<U+2028>+<改动行>'`；`$'x\n+<改动行>'` 在词法上就判为求不出值），
    _SPECIAL_NAME 里的变量改的是跑哪个 git、读哪份配置和 shell 怎么分词，这三样都不算。"""
    script = _script(command)
    if script is None:
        return False
    items = _parse(_lex(script))
    commands = [x for x in items if isinstance(x, _Command)]
    if not commands or any(kind == "opaque" for c in commands
                           for word in [*c.words, *(t for _, t in c.redirects)] for kind, _ in word):
        return False
    expanded = _evaluate(items)
    if any("\n" in arg or _BREAK.search(arg) for e in expanded for arg in e.argv):
        return False
    revisions = _Revisions(head_sha, other_shas)
    reads = [k for k, e in enumerate(expanded) if _git_patch_read(e, revisions)]
    if len(reads) != 1:
        return False
    k = reads[0]
    if (expanded[k].argv[0] not in ("git", "/usr/bin/git") or _discards_stdout(expanded[k], [])
            or (k and commands[k - 1].op not in ("&&", ";", "\n"))
            or commands[-1].op not in ("", ";", "\n")
            or any(_SPECIAL_NAME.fullmatch(name) for e in expanded for name in e.env_names)):
        return False
    before, pipeline = expanded[:k], expanded[k + 1:]
    return (all(_setup(e) and c.op in ("&&", ";", "\n") for c, e in zip(commands[:k], before, strict=True))
            and all(commands[j].op in _PIPE for j in range(k, len(commands) - 1))
            and all(_filter(e) for e in pipeline))


def _setup(command: _Expanded) -> bool:
    """git 之前不输出的段：`NAME=val`、`export NAME[=val]`、`cd /review`（审阅 checkout 的只读挂载点，本就是 cwd）。"""
    argv = command.argv
    if command.redirects:
        return False
    if not argv:
        return True
    if argv[0] == "export" and len(argv) > 1:
        names = [arg.partition("=")[0] for arg in argv[1:]]
        return all(_NAME.fullmatch(n) and not _SPECIAL_NAME.fullmatch(n) for n in names)
    return argv == ["cd", "/review"]


_SPECIAL_NAME = re.compile(r"GIT_(?!PAGER$)\w*|PATH|IFS|CDPATH|HOME|XDG_CONFIG_HOME")
_COUNT = r"\+\d+|0*[1-9]\d*"  # 0 行就是吞掉输出
_SED_SCRIPT = re.compile(r"(?:\d+|\$)(?:,(?:\d+|\$))?p(?:;(?:\d+|\$)(?:,(?:\d+|\$))?p)*")


@dataclass(frozen=True)
class _FilterSpec:
    """flags：单独出现的选项；values：带值选项及值的形状；pattern：须且只能有一个位置参数（grep 的模式、sed 的脚本），
    给了 `-e` 时不能再有。没有文件参数，也不接受会往输出里加任意文字的选项（`nl -s`、`grep --label`、sed 的 `i`/`a`/`s`）。"""
    flags: str
    values: dict[str, str] = field(default_factory=dict)
    pattern: str | None = None


_FILTERS = {
    "nl": _FilterSpec(r"-b[at]|-w\d+|-n(?:ln|rn|rz)", {"-b": "[at]", "-w": r"\d+", "-n": "ln|rn|rz"}),
    "head": _FilterSpec(rf"-(?:{_COUNT})|-[nc](?:{_COUNT})|--(?:lines|bytes)=(?:{_COUNT})", {"-n": _COUNT, "-c": _COUNT}),
    "tail": _FilterSpec(rf"-(?:{_COUNT})|-[nc](?:{_COUNT})|--(?:lines|bytes)=(?:{_COUNT})", {"-n": _COUNT, "-c": _COUNT}),
    "cat": _FilterSpec(r"-[nbsuvetAET]+|-"),
    "sed": _FilterSpec(r"-n", {"-e": _SED_SCRIPT.pattern}, _SED_SCRIPT.pattern),
    "grep": _FilterSpec(r"-[nivEFwxah]+|-[ABCm]\d+|--colou?r=never",
                        {"-e": r"(?s:.*)", "-A": r"\d+", "-B": r"\d+", "-C": r"\d+", "-m": r"\d+"}, r"(?s:.*)"),
}


def _filter(command: _Expanded) -> bool:
    """git 之后的管道段只做筛选或截取，输出的每一行都来自 git 的输出（只加行号）。"""
    argv = command.argv
    spec = _FILTERS.get(argv[0]) if argv else None
    if spec is None or any(not op.startswith("2") for op, _ in command.redirects) or (argv[0] == "sed" and "-n" not in argv):
        return False
    positional: list[str] = []
    given_e, i, options_done = False, 1, False
    while i < len(argv):
        arg = argv[i]
        if options_done or arg == "-" and argv[0] != "cat" or not arg.startswith("-"):
            positional.append(arg)
        elif arg == "--":
            options_done = True
        elif arg in spec.values:
            if i + 1 == len(argv) or not re.fullmatch(spec.values[arg], argv[i + 1]):
                return False
            given_e, i = given_e or arg == "-e", i + 1
        elif not re.fullmatch(spec.flags, arg):
            return False
        i += 1
    if spec.pattern is None or given_e:
        return not positional
    return len(positional) == 1 and bool(re.fullmatch(spec.pattern, positional[0]))
