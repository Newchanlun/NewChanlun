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
  另一边是别的已知提交，只给一个提交时另一边是工作区；show 的位置参数全是 head 的提交、`<other>..<head>` 范围，
  或全是 `<head>:<path>` 文件内容（path 须是本 PR 改动的文件）；stdout 没被丢掉（/dev/null、关闭、写进文件）。
- git 之前只有不输出的段（_setup），用 `&&`、`;` 或换行接上；git 之后只有经管道串联的纯过滤器（_FILTERS），
  管道就是脚本的结尾。别的命令（echo、printf、cat 文件、tee、python、另一条 git……）只要出现，整条命令就不算：
  aggregated_output 是整条命令的输出，那些段印出的改动行与 git 印出的分不开（#1969 正式审查 kimi BLOCK）。
  唯一的例外（PR #2018 run 45a4c22b）：整个 PR 的 git diff（merge-base 对 head，不带 pathspec、不接管道、
  没有任何重定向，全局选项只许白名单 `-c`，选项只在 _PLAIN_DIFF 里）之后，用 `;`/`&&`/换行接白名单里只印提交元数据的 `git show`/`git log`（_trailing）。
  PR 非空，真实补丁必定先印出；证据只在输出开头、合 git diff 格式的那段里找（_leading_diff），diff 失败时
  开头是报错，后一段的输出当不了证据（#2022 kimi、opus BLOCK）。

命令文本只说明脚本打算让 git 输出补丁，不说明它真的输出了：`if false; then git diff …; fi` 没执行，
`exec >/dev/null`、`export GIT_EXTERNAL_DIFF=true` 改的是之后命令的环境，textconv 保留 `diff --git`/`@@` 头而把内容
换掉（#1969 kimi BLOCK）。所以还要看这条事件实际记录的输出（Codex `aggregated_output`，约 1 MiB 截断、保留前部）：
其中须有一行就是冻结补丁的真实内容，见 FrozenPatch。输出只按 `\n` 切行，含其他行终止符的行不当证据。
证据按文件存，出处须与命令读的对象一致（_Read）：`git show <head>:<path>` 的 path 须是本 PR 改动的文件，证据只取
该文件加进来的行；不是 merge-base 对 head 的 diff 与 show 提交、范围，只认冻结文件头之后属于该文件的行
（#1969 正式审查 bb8aa92e opus BLOCK：没改的模块里的 `from __future__ import annotations` 曾被当成读到了补丁）。

按命令写法判定之外，另有按内容的判定 FrozenPatch.covered_by：模型实际看到的输出合起来含整份冻结补丁（每个文件头、
每条改动行），也算读过；external_review 两者满足其一即可。
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field, replace

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
    def __init__(self, head: str, merge_base: str, base: str) -> None:
        self.head, self.merge_base, self.base = head.lower(), merge_base.lower(), base.lower()

    def kind(self, token: str) -> str:
        """head / merge-base / base（恰好是该提交，不带 `~`/`^`）/ other（这三个提交的祖先写法）/
        unknown（像 SHA 但不认识）/ path。"""
        match = _REV.fullmatch(token)
        if not match:
            return "path"
        base, suffix = match.group(1), match.group(2)
        if base in ("HEAD", "@") or self.head.startswith(base.lower()):
            return "other" if suffix else "head"
        for name, sha in (("merge-base", self.merge_base), ("base", self.base)):
            if sha and sha.startswith(base.lower()):
                return "other" if suffix else name
        return "unknown"


_KNOWN = ("merge-base", "base", "other")


@dataclass(frozen=True)
class _Read:
    """合格读取让 git 输出的是什么，决定输出里哪些行能当证据（#1969 正式审查 bb8aa92e opus BLOCK）。
    patch：merge-base 与 head 之间的 diff（可带 pathspec），输出的每一行都出自冻结补丁；
    diff：别的 diff，或 show 提交、范围，输出里可能有本 PR 没改的文件，只认落在冻结补丁某个文件的
    `diff --git` 头之后、且是该文件改动内容的行；
    blobs：`git show <head>:<path>`，paths 须全是本 PR 改动的文件，证据只取这些文件在 head 上加进来的行。"""
    kind: str
    paths: tuple[str, ...] = ()
    leading: bool = False  # 后面还接了别的段（_trailing）：证据只在输出开头那段 diff 里找，见 _leading_diff


WHOLE_PATCH = _Read("patch")


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


@dataclass(frozen=True)
class _GitCall:
    """`git [全局选项] <子命令> …` 切开后的样子；`-c` 只认 _CONFIG_KEYS（别的能换掉 git 的输出：diff.external、
    textconv、core.pager、format.pretty……）。options/positional 只含 `--` 之前的参数。"""
    subcommand: str
    rest: list[str]
    options: list[str]
    positional: list[str]
    moved: bool


def _git_call(argv: list[str]) -> _GitCall | None:
    if not argv or argv[0].rsplit("/", 1)[-1] != "git":
        return None
    i, config, moved = 1, [], False
    while i < len(argv):
        if argv[i] in ("-C", "-c", "--git-dir", "--work-tree"):
            config += argv[i + 1:i + 2] if argv[i] == "-c" else []
            moved = moved or argv[i] == "-C"
            i += 2
        elif argv[i] in ("--no-pager", "-P") or argv[i].startswith(("--git-dir=", "--work-tree=")):
            i += 1
        else:
            break
    if i >= len(argv) or any(c.partition("=")[0].lower() not in _CONFIG_KEYS for c in config):
        return None
    rest = argv[i + 1:]
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
    return _GitCall(argv[i], rest, options, positional, moved)


def _git_patch_read(command: _Expanded, revisions: _Revisions) -> _Read | None:
    call = _git_call(command.argv)
    if call is None or call.subcommand not in ("diff", "show"):
        return None
    subcommand, rest, options, positional, moved = call.subcommand, call.rest, call.options, call.positional, call.moved
    separator = rest.index("--") if "--" in rest else len(rest)
    if "--no-index" in options or (subcommand == "show" and "--output" in " ".join(options)):
        return None
    # 补丁旁边能印出审查员自己写的文字的选项（`--format='+<改动行>'`、`--line-prefix`）不认（#1969 kimi BLOCK）
    if any(_PRINTS_TEXT.fullmatch(o) for o in options):
        return None
    # 补丁走 stdout 的前提下，blob 内容不受输出格式选项影响；提交和范围要看格式选项，且不能混进求不出值的参数
    # （`$X` 可能就是 `-s`）。diff 在 `--` 之前只接受认识的提交：像 `'$H'`、`<head>x` 这样的词 git 会当路径，
    # 路径不存在就报错，接了管道后退出码仍是 0。
    unresolved = any(_OPAQUE in arg for arg in rest[:separator])
    if subcommand == "show":
        return _show_read(positional, options, unresolved, moved, revisions)
    kinds: list[str] = []
    for arg in positional:
        left, dots, right = arg.partition("..")
        sides = [left or "HEAD", right.lstrip(".") or "HEAD"] if dots else [arg]
        resolved = [revisions.kind(side) for side in sides]
        if not all(kind == "head" or kind in _KNOWN for kind in resolved):
            return None
        kinds += resolved
    if unresolved:
        return None
    if len(kinds) == 1:
        kinds.append("head")  # 一个提交对工作区或索引；审阅 checkout 已证实停在 head 且干净
    if "head" not in kinds or not any(k in _KNOWN for k in kinds) or not _emits_patch(subcommand, options):
        return None
    return WHOLE_PATCH if _whole_range(positional, revisions) else _Read("diff")


def _whole_range(positional: list[str], revisions: _Revisions) -> bool:
    """diff 的位置参数恰好是「左 merge-base、右 head」：`<mb> <head>`、`<mb>`（对工作区）、`<mb>..<head>`，
    或 `<mb>...<head>`、`<base>...<head>`（比的是 merge-base(左, head) 与 head）。区间两侧都须写出；
    反向（`<head> <mb>`）、`HEAD...`、`@...`、`...<mb>` 这类形状输出的不是冻结补丁或是空的，不算整份补丁读取
    （#2022 第三轮 opus BLOCK）。"""
    if len(positional) == 2 and ".." not in "".join(positional):
        return [revisions.kind(arg) for arg in positional] == ["merge-base", "head"]
    if len(positional) != 1:
        return False
    left, dots, right = positional[0].partition("..")
    if not dots:
        return revisions.kind(left) == "merge-base"
    triple = right.startswith(".")
    right = right[1:] if triple else right
    if not left or not right:
        return False
    pair = [revisions.kind(left), revisions.kind(right)]
    return pair == ["merge-base", "head"] or (triple and pair == ["base", "head"])


def _show_read(positional: list[str], options: list[str], unresolved: bool, moved: bool,
               revisions: _Revisions) -> _Read | None:
    """show 的位置参数须全部指名 head：要么都是 `<head>:<path>`（blobs），要么都是 head 提交或
    `<known>..<head>` 范围（diff）。混进别的提交或 blob，输出里就有与本 PR 无关的内容。"""
    paths: list[str] = []
    commits = 0
    for arg in positional:
        base, colon, path = arg.partition(":")
        if colon:
            if path.startswith(("./", "../")) or path in (".", ".."):
                # `<rev>:./x` 相对当前目录（就是 /review 根）；`-C` 换了目录就不知道指的是哪个文件
                path = "" if moved else posixpath.normpath(path)
            if not path or path == "." or path == ".." or path.startswith("../") or revisions.kind(base) != "head":
                return None
            paths.append(path)
            continue
        left, dots, right = arg.partition("..")
        pair = [revisions.kind(left or "HEAD"), revisions.kind(right.lstrip(".") or "HEAD")]
        if not (pair[0] in _KNOWN and pair[1] == "head" if dots else revisions.kind(arg) == "head"):
            return None
        commits += 1
    if paths and not commits:
        return _Read("blobs", tuple(paths))
    if commits and not paths and not unresolved and _emits_patch("show", options):
        return _Read("diff")
    return None


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


_C_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _unquote(name: str) -> str:
    """git 给特殊字符路径加的 C 风格引号（`"b/\\303\\244.py"`）解回原文。"""
    if not (len(name) >= 2 and name[0] == name[-1] == '"'):
        return name
    out, i, body = bytearray(), 0, name[1:-1]
    while i < len(body):
        if body[i] == "\\" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        elif body[i] == "\\" and body[i + 1:i + 2] in _C_ESCAPES:
            out.append(_C_ESCAPES[body[i + 1]])
            i += 2
        else:
            out += body[i].encode()
            i += 1
    return out.decode(errors="replace")


_DIFF_HEADER = re.compile(r"(?:index|old mode|new mode|deleted file mode|new file mode|similarity index|"
                          r"dissimilarity index|rename from|rename to|copy from|copy to|--- |\+\+\+ |Binary files )")
_HUNK = re.compile(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def _leading_diff(output: str) -> list[str]:
    """输出开头那段 `git diff` 的行：从第一行 `diff --git` 起，按 git diff 的输出格式（文件头、扩展头、
    按 `@@` 行数走完的 hunk、`\\ No newline`）一行行吃，碰到不合格式的第一行就停。命令是
    `git diff … ; git show --no-patch …` 时，aggregated_output 是两段按执行顺序拼起来的：diff 失败或什么都没印，
    开头就是报错或后一段的输出，这里给出空表，后一段印的东西当不了证据（PR #2018 run 45a4c22b）。"""
    lines = _lines(output)
    if not lines[0].startswith("diff --git "):
        return []
    old = new = 0
    for n, line in enumerate(lines):
        if old > 0 or new > 0:
            sign = line[:1]
            if sign not in (" ", "+", "-", "\\"):
                return lines[:n]
            old -= sign in ("-", " ")
            new -= sign in ("+", " ")
        elif hunk := _HUNK.match(line):
            old, new = (int(k) if k is not None else 1 for k in hunk.groups())
        elif not (line.startswith(("diff --git ", "\\")) or _DIFF_HEADER.match(line)):
            return lines[:n]
    return lines


@dataclass(frozen=True)
class FrozenFile:
    """冻结补丁里的一个文件。header 是 controller 侧的 `diff --git a/… b/…` 行，path 是它在 head 上的路径
    （删除的文件为 None）；evidence 是这个文件的证据行，added 是其中由 `+` 加进来、head 上这个文件里有的。"""
    header: str
    path: str | None
    evidence: frozenset[str]
    added: frozenset[str]
    changes: frozenset[str] = frozenset()  # 全部非空改动行，带 `+`/`-` 号（去掉首尾空白），供 FrozenPatch.covered_by


def _split_files(diff: str) -> list[tuple[str, str | None, list[tuple[str, str]]]]:
    """按文件切开 `-U<n>` 补丁：(header, head 上的路径, [(`+`/`-`, 改动行去掉首尾空白)])。
    hunk 按 `@@ -a,b +c,d @@` 的行数走完，所以内容里形如 `+++ x`、`diff --git` 的改动行不会被当成文件头。"""
    files: list[tuple[str, str | None, list[tuple[str, str]]]] = []
    old = new = 0
    for line in _lines(diff):
        if old > 0 or new > 0:
            sign = line[:1]
            old -= sign in ("-", " ")
            new -= sign in ("+", " ")
            if sign in ("+", "-") and not _BREAK.search(line) and (text := line[1:].strip()):
                files[-1][2].append((sign, text))
        elif line.startswith("diff --git "):
            files.append((line, None, []))
        elif files and line.startswith("+++ "):
            target = _unquote(line[4:])
            files[-1] = (files[-1][0], target[2:] if target.startswith("b/") else None, files[-1][2])
        elif files and (hunk := re.match(r"@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)):
            old, new = (int(n) if n is not None else 1 for n in hunk.groups())
    return files


@dataclass(frozen=True)
class FrozenPatch:
    """controller 侧取得的冻结候选补丁，按文件存证据（#1969 正式审查 bb8aa92e opus BLOCK：不分文件时，
    `git show <head>:<本 PR 没改的文件>` 里的 `from __future__ import annotations` 就能冒充读到了改动行）。
    证据是审查员输出里须出现的行（去掉首尾空白）：改动行（`+`/`-` 之后的内容）里至少 _DISTINCT 个字符的；
    整个补丁都没有这样的行就取全部非空改动行；纯二进制、改名、改权限的补丁没有改动行，取 `diff --git` 头。"""
    head_sha: str
    merge_base_sha: str
    base_sha: str
    files: tuple[FrozenFile, ...]

    @classmethod
    def from_diff(cls, head_sha: str, merge_base_sha: str, base_sha: str, diff: str) -> FrozenPatch:
        """diff 须是 controller 用固定 `a/`、`b/` 前缀取的 `git diff -U0 <merge_base> <head>`。"""
        split = _split_files(diff)
        changed = {text for _, _, lines in split for _, text in lines}
        least = _DISTINCT if any(len(text) >= _DISTINCT for text in changed) else 0
        files = tuple(FrozenFile(header, path,
                                 frozenset({t for _, t in lines if len(t) >= least} if changed else {header}),
                                 frozenset({t for sign, t in lines if sign == "+" and len(t) >= least}),
                                 frozenset({sign + t for sign, t in lines}))
                      for header, path, lines in split)
        return cls(head_sha, merge_base_sha, base_sha, files)

    @property
    def evidence(self) -> frozenset[str]:
        return frozenset().union(*(f.evidence for f in self.files))

    def shown_in(self, output: str, read: _Read = WHOLE_PATCH) -> bool:
        """输出里有一行（去掉行号前缀、diff 的 `+`/`-`/空格标记后）是冻结补丁的改动内容，按 read 限定出处：
        patch 认整个补丁的证据；diff 只认跟在冻结补丁某个文件的 `diff --git` 头之后、属于该文件的证据；
        blobs 只认所指文件（须全是本 PR 改动的文件）在 head 上加进来的行。
        含 _BREAK 字符的行不当证据：它在别的切行规则下可能是两行。"""
        by_header = {f.header: f.evidence for f in self.files}
        if read.kind == "blobs":
            by_path = {f.path: f.added for f in self.files if f.path is not None}
            if not all(path in by_path for path in read.paths):
                return False
            evidence: frozenset[str] = frozenset().union(*(by_path[path] for path in read.paths))
        else:
            evidence = self.evidence if read.kind == "patch" else frozenset()
        for raw in _leading_diff(output) if read.leading else _lines(output):
            if _BREAK.search(raw):
                continue
            line = raw.strip()
            unstripped = raw
            if match := _LINE_NUMBER.match(line):
                unstripped = line[match.end():]
                line = unstripped.strip()
            if read.kind == "diff" and unstripped.startswith("diff --git "):
                # 未加行号时原样比对：diff 的上下文行带一个前导空格，不会被当成文件头
                evidence = by_header.get(unstripped, frozenset())
            if line in evidence or (line[:1] in "+-" and line[1:].strip() in evidence):
                return True
        return False


    def covered_by(self, outputs: list[str]) -> bool:
        """审查员看到的输出合起来覆盖了整份冻结补丁（#2018 attempt 40343、#2025 的误判，不看命令怎么写）：
        每个文件的 `diff --git` 头都出现过，且该文件的每一条改动行（带 `+`/`-` 号）都出现在某段输出里、
        跟在这个文件头之后。输出须是模型实际看到的（Codex 给模型的输出会从中间截掉，含截断标记的行与
        _BREAK 行不算，截断标记之后的行不再归属前面的文件头）。行号前缀（`nl -ba`、`grep -n`）照常去掉。
        这是「读全了」的判定：一行没出现就不算，分段读、换着写法读都能认；只看 `--stat`、只读 head 上的文件
        （没有 `+`/`-` 号）、只读了一部分文件都不算。"""
        if not self.files:
            return False
        wanted = {f.header: f.changes for f in self.files}
        seen: dict[str, set[str]] = {header: set() for header in wanted}
        headers: set[str] = set()
        for output in outputs:
            current: str | None = None
            for raw in _lines(output):
                if _BREAK.search(raw) or _TRUNCATED.search(raw):
                    current = None
                    continue
                line = raw
                if match := _LINE_NUMBER.match(raw.strip()):
                    line = raw.strip()[match.end():]
                if line.startswith("diff --git "):
                    current = line if line in wanted else None
                    if current is not None:
                        headers.add(current)
                elif current is not None and line[:1] in ("+", "-") and line[1:].strip():
                    seen[current].add(line[0] + line[1:].strip())
        return all(header in headers and changes <= seen[header] for header, changes in wanted.items())


_TRUNCATED = re.compile(r"…\d+ (?:chars|tokens) truncated…")


def reads_candidate_patch(command: str, output: str, patch: FrozenPatch) -> bool:
    """命令按 bash 语义会让 git 输出冻结补丁，且记录的输出里真有冻结补丁的内容，出处与命令读的对象一致。"""
    read = _patch_read(command, patch.head_sha, patch.merge_base_sha, patch.base_sha)
    return read is not None and patch.shown_in(output, read)


def _patch_read(command: str, head_sha: str, merge_base_sha: str, base_sha: str) -> _Read | None:
    """diff 另一侧须是 merge-base、base 或这几个提交的祖先写法，写一个不存在的 SHA 再接管道
    （`git diff <bad> <head> | head`，无 pipefail 时退出码为 0）不算读取。
    命令替换会执行别的命令，含换行或其他行终止符（U+2028 等）的参数会被 git 或过滤器的报错原样带进输出
    （`git show <head>:'x<U+2028>+<改动行>'`；`$'x\n+<改动行>'` 在词法上就判为求不出值），
    _SPECIAL_NAME 里的变量改的是跑哪个 git、读哪份配置和 shell 怎么分词，这三样都不算。"""
    script = _script(command)
    if script is None:
        return None
    items = _parse(_lex(script))
    commands = [x for x in items if isinstance(x, _Command)]
    if not commands or any(kind == "opaque" for c in commands
                           for word in [*c.words, *(t for _, t in c.redirects)] for kind, _ in word):
        return None
    expanded = _evaluate(items)
    if any("\n" in arg or _BREAK.search(arg) for e in expanded for arg in e.argv):
        return None
    revisions = _Revisions(head_sha, merge_base_sha, base_sha)
    reads = [(k, read) for k, e in enumerate(expanded) if (read := _git_patch_read(e, revisions)) is not None]
    if len(reads) != 1:
        return None
    k, read = reads[0]
    if (expanded[k].argv[0] not in ("git", "/usr/bin/git") or _discards_stdout(expanded[k], [])
            or (k and commands[k - 1].op not in ("&&", ";", "\n"))
            or commands[-1].op not in ("", ";", "\n")
            or any(_SPECIAL_NAME.fullmatch(name) for e in expanded for name in e.env_names)):
        return None
    if not all(_setup(e) and c.op in ("&&", ";", "\n") for c, e in zip(commands[:k], expanded[:k], strict=True)):
        return None
    if commands[k].op in _PIPE or k + 1 == len(commands):
        ok = (all(commands[j].op in _PIPE for j in range(k, len(commands) - 1))
              and all(_filter(e) for e in expanded[k + 1:]))
        return read if ok else None
    # git diff 之后用 `;`/`&&`/换行接上只印提交元数据的 git 段（PR #2018 run 45a4c22b opus：
    # `git diff <mb> <head>; git show --no-patch --format=… <head>`）。前一段须是整个 PR 的 diff（不带 pathspec、
    # 只带 _PLAIN_DIFF 里的选项）：PR 非空，真实补丁就必定先于后一段印出；diff 失败时开头是报错。证据只在开头
    # 那段 diff 里找（leading）。#2022 两位审查 BLOCK：带 `-- nope` 时 diff 什么都不印，`%B` 印出的提交说明就成了
    # 开头那段；后一段按黑名单放行时，`--binary` 隐含 `--patch`、`--show-linear-break=<文字>` 印审查员写的字。
    # 第二轮 kimi BLOCK：`git --git-dir=/nonexistent diff … 2>/dev/null; git show -s --format=%B …` 里 diff 悄悄失败、
    # 报错又被丢掉，开头就成了 `%B`。所以前一段不许有任何重定向，全局选项只许 _CONFIG_KEYS 里的 `-c`。
    call = _git_call(expanded[k].argv)
    if call is None or call.subcommand != "diff":
        return None
    globals_ = expanded[k].argv[1:len(expanded[k].argv) - len(call.rest) - 1]
    if (read.kind != "patch" or "--" in call.rest or expanded[k].redirects
            or globals_[::2] != ["-c"] * len(globals_[::2]) or len(globals_) % 2
            or not all(_PLAIN_DIFF.fullmatch(o) for o in call.options) or commands[k].op not in ("&&", ";", "\n")):
        return None
    for j in range(k + 1, len(commands)):
        if commands[j].op not in ("&&", ";", "\n", "") or not _trailing(expanded[j], revisions):
            return None
    return replace(read, leading=True)


# 复合形式里前一段 diff 只认的选项：都不改补丁的范围与内容（外部 diff、textconv、颜色关掉；上下文行数、显式 -p）
_PLAIN_DIFF = re.compile(r"--no-ext-diff|--no-textconv|--no-color|--color=never|-U\d+|--unified=\d+|-p|-u|--patch")
# 后一段格式串只能由这些占位符和分隔符拼成：印出的只有 git 生成的提交元数据，没有审查员能写进去的字面文字
_PLACEHOLDER_FORMAT = re.compile(r"(?:%(?:[HhTtPpsbBn%]|[ac](?:n|e|d|I|i))|[ \t:,|/()\[\]-])*")


def _trailing(command: _Expanded, revisions: _Revisions) -> bool:
    """冻结补丁的 git diff 之后接的段，白名单：`git show|log`，不带全局选项、重定向与管道；选项只有 `-s`/`--no-patch`
    （至少一个）和恰好一个 `--format=<占位符>`/`--pretty=[t]format:<占位符>`；位置参数只能是 head、merge-base、base
    本身。别的选项（`--binary`、`--show-linear-break`、`-p`、`--stat`、`-c` 覆盖……）一律整条不认。"""
    argv = command.argv
    if command.redirects or len(argv) < 3 or argv[0] not in ("git", "/usr/bin/git") or argv[1] not in ("show", "log"):
        return False
    formats, quiet, revs = 0, False, 0
    for arg in argv[2:]:
        name, eq, value = arg.partition("=")
        if arg in ("-s", "--no-patch"):
            quiet = True
        elif eq and name in ("--format", "--pretty"):
            body = re.sub(r"^t?format:", "", value) if name == "--format" else value.removeprefix("t").removeprefix("format:")
            if name == "--pretty" and not value.startswith(("format:", "tformat:")):
                return False
            if not _PLACEHOLDER_FORMAT.fullmatch(body):
                return False
            formats += 1
        elif revisions.kind(arg) in ("head", "merge-base", "base"):
            revs += 1
        else:
            return False
    return quiet and formats == 1 and revs >= 1


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
