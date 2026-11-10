"""按内容认读全（#2037）：审查员在宿主采集的合格 git 读取里实际看到了整份冻结补丁，也算读过补丁。

patch_read 按「某一条命令的写法」判定，写法一变就误判未读（#2018 attempt 40343 diff 后接 `git log -4`，
#2025 kimi 前置 `cat`/`printf`，#2036 链尾 `git status` 失败）。这里改按内容判，与 patch_read 两者满足其一即可，
所以只会多认、不会多拒。三条约束（#2037 首轮 opus、kimi BLOCK）：

1. 证据只来自 events.jsonl（宿主从 codex stdout 采集）里已结束的 command_execution，且整条命令只由合格段组成
   （coverage_segments）：合格 git 读取（diff/show/log，对 head、merge-base、base，选项白名单）、只印元数据的 git、
   不输出的准备段，以及输出可在 controller 侧算准的 printf/echo/`cat /review/<文件>`。后者不得印出 `diff --git` 头或
   `D<TAB>` 删除行，它们在输出里的位置按执行顺序找到后剔除（git_spans），所以计入的文件头、删除清单和 hunk 行
   只出自 git。审查员写得了 session.jsonl（rollout 在容器 /tmp 下），它只用来判断模型看到了多少：
   同一条命令（脚本逐字相同、退出码相同、按出现顺序）的可见正文须能在 aggregated_output 里找到，绑不上不算；
   被 Codex 从中间截掉的部分不算，截断处两侧的半行也不算；可见量按 aggregated_output 核：超过 Codex 可见上限却声称
   整段可见的不算，截断标记记下的原始长度须与 aggregated_output 相符（visible_spans）。
2. 改动行按 (文件头, `+`/`-`, 行号, 行文本) 认：行号按 hunk 头逐行推出（`-` 行取旧文件行号，`+` 行取新文件行号），
   与上下文行数无关。同一行看几遍都是同一个键，两个 hunk 里各一条 `+return` 是两个键（#2037 kimi BLOCK）。
3. 整文件删除的内容不计入逐行核对，只要求删除清单（`D<TAB><path>`）或文件头出现在合格 git 读取的输出里；整份补丁没有一行可逐行核对的内容时
   （全删除、全二进制、只改 mode），须有一条输出单独列全。
"""
from __future__ import annotations

import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass

from .patch_read import (
    _BREAK,
    _CONFIG_KEYS,
    _DIFF_HEADER,
    _KNOWN,
    _OPAQUE,
    _PATCH_ON,
    _PIPE,
    _SPECIAL_NAME,
    _Command,
    _emits_patch,
    _evaluate,
    _Expanded,
    _filter,
    _lex,
    _lines,
    _parse,
    _Revisions,
    _script,
    _setup,
    _unquote,
)

_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_DELETED = re.compile(r"D\t(.+)")  # `--name-status` 的整文件删除行
_NUMBERED = re.compile(r"\s*\d+[\t:]")  # `nl -ba`、`cat -n`、`grep -n` 的行号前缀
_PREAMBLE = re.compile(r"Warning: truncated output \(original token count: (\d+)\)\nTotal output lines: (\d+)\n\n")
_MARKER = re.compile(r"…(\d+) chars truncated…")
# Codex 交给模型的单条命令输出上限（UTF-8 字节）。全部 run 目录重放（2026-11-10，23789 条绑上的命令）：完整可见的
# 最长 10000 字节；6761 次截断都只有一个截断标记，可见部分 9996–10000 字节，`…N chars truncated…` 的 N 加可见字符数
# 恰等于 aggregated_output 的字符数，original token count 恰为字节数除以 4 向上取整，Total output lines 恰为行数。
# exec_command 的 max_output_tokens（实测 500–120000）不改变这个上限。
CODEX_VISIBLE_BYTES = 10_000

Key = tuple[str, str, int, str]  # (文件头, `+`/`-`, 行号, 行文本)


@dataclass(frozen=True)
class CoverageFile:
    """冻结补丁里的一个文件：header 是 controller 侧的 `diff --git a/… b/…`；keys 是它全部非空改动行；
    deleted 是整文件删除时它在 merge-base 上的路径。"""
    header: str
    keys: frozenset[Key]
    deleted: str | None


class _Scan:
    """按 git diff 的输出格式逐行走：认冻结文件头、hunk 头推行号、`D<TAB>` 删除行。"""

    def __init__(self, headers: frozenset[str], skip: frozenset[str] = frozenset()) -> None:
        """skip：这些文件头下的改动行不记（整文件删除的内容不要求读到，大删除 PR 有上千万行）。"""
        self.headers = headers
        self.skip = skip
        self.keys: set[Key] = set()
        self.seen_headers: set[str] = set()
        self.listed: set[str] = set()

    def feed(self, text: str) -> None:
        lines = _lines(text)
        numbered = any(lines) and all(_NUMBERED.match(line) for line in lines if line)
        current: str | None = None
        in_hunk = False
        old = new = left_old = left_new = 0
        for raw in lines:
            # 含 `\r`、U+2028 或字面 `…N chars truncated…` 的行照常计入（#2037 第二轮正式审查 opus BLOCK：冻结补丁里遇到
            # 这种行就跳过该文件余下的改动行，覆盖要求被悄悄缩小）。计入的片段都切自 aggregated_output，里面没有 Codex 的
            # 截断标记；git 段的参数里不许有这些字符（coverage_segments），报错也就带不出伪造的行。
            prefix = _NUMBERED.match(raw) if numbered else None
            line = raw[prefix.end():] if prefix else raw
            if line.startswith("diff --git "):
                current, in_hunk = (line if line in self.headers else None), False
                if current is not None:
                    self.seen_headers.add(current)
                continue
            if (status := _DELETED.fullmatch(line)) is not None:
                self.listed.add(_unquote(status.group(1)))
                current = None
                continue
            if current is None or current in self.skip:
                continue
            if (hunk := _HUNK.match(line)) is not None:
                old, new = int(hunk.group(1)), int(hunk.group(3))
                left_old, left_new = (int(n) if n is not None else 1 for n in (hunk.group(2), hunk.group(4)))
                in_hunk = True
                continue
            if not in_hunk:
                if not (_DIFF_HEADER.match(line) or line.startswith("\\")):
                    current = None
                continue
            sign = line[:1]
            if (left_old > 0 or left_new > 0) and sign in (" ", "-", "+"):
                if sign != "+":
                    if sign == "-" and line[1:].strip():
                        self.keys.add((current, "-", old, line[1:]))
                    old, left_old = old + 1, left_old - 1
                if sign != "-":
                    if sign == "+" and line[1:].strip():
                        self.keys.add((current, "+", new, line[1:]))
                    new, left_new = new + 1, left_new - 1
            elif sign != "\\":
                current = None


@dataclass(frozen=True)
class CoveragePatch:
    files: tuple[CoverageFile, ...]

    @classmethod
    def from_diff(cls, diff: str) -> CoveragePatch:
        """diff 须是 controller 用固定 `a/`、`b/` 前缀取的 `git diff -U0 <merge_base> <head>`。"""
        headers: list[str] = []
        deleted: dict[str, str | None] = {}  # 整文件删除的文件头 -> `--- a/` 行给出的路径
        for line in _lines(diff):
            if line.startswith("diff --git "):
                headers.append(line)
            elif headers and line.startswith("deleted file mode "):
                deleted[headers[-1]] = None
            elif headers and headers[-1] in deleted and line.startswith(("--- a/", '--- "a/')):
                # 路径含空格时 git 在 `---`/`+++` 行尾加一个 TAB（#2037 opus 非阻断项）
                deleted[headers[-1]] = _unquote(line[4:].removesuffix("\t"))[2:]
        scan = _Scan(frozenset(headers), skip=frozenset(deleted))
        scan.feed(diff)
        by_header: dict[str, set[Key]] = {}
        for key in scan.keys:
            by_header.setdefault(key[0], set()).add(key)
        return cls(tuple(CoverageFile(header, frozenset(by_header.get(header, ())),
                                      (deleted[header] or _header_path(header)) if header in deleted else None)
                         for header in headers))

    def covered_by(self, outputs: list[list[str]]) -> bool:
        """outputs 是每条合格命令可见的片段。每个文件：有改动行的，全部 (文件头, 符号, 行号, 文本) 都见过；
        整文件删除的，见过删除清单或文件头；其余（二进制、只改 mode）见过文件头。整份补丁没有改动行时，须有一条
        输出单独满足。"""
        if not self.files:
            return False
        headers = frozenset(f.header for f in self.files)
        scans = []
        for pieces in outputs:
            scan = _Scan(headers)
            for piece in pieces:
                scan.feed(piece)
            scans.append(scan)
        if not any(f.keys for f in self.files):
            return any(self._satisfied([scan]) for scan in scans)
        return self._satisfied(scans)

    def _satisfied(self, scans: list[_Scan]) -> bool:
        keys = set().union(*(s.keys for s in scans))
        seen = set().union(*(s.seen_headers for s in scans))
        listed = set().union(*(s.listed for s in scans))
        return all(f.header in seen or f.deleted in listed if f.deleted is not None
                   else f.keys <= keys if f.keys else f.header in seen for f in self.files)


def _header_path(header: str) -> str | None:
    """`diff --git a/<p> b/<p>`（两侧同名，含 C 风格引号）里的 <p>；二进制删除没有 `--- a/` 行，只能从这里取。"""
    rest = header.removeprefix("diff --git ")
    if quoted := re.fullmatch(r'("(?:[^"\\]|\\.)*") ("(?:[^"\\]|\\.)*")', rest):
        left, right = _unquote(quoted.group(1)), _unquote(quoted.group(2))
    else:
        half = (len(rest) - 1) // 2
        left, right = rest[:half], rest[half + 1:]
    return left[2:] if left.startswith("a/") and right.startswith("b/") and left[2:] == right[2:] else None


def visible_spans(aggregated: str, visible: str) -> list[tuple[int, int]] | None:
    """模型看到的正文（session.jsonl）对上宿主采集的 aggregated_output 后，模型看到的那几段在 aggregated_output 里的位置。
    session.jsonl 审查员写得了，所以可见量按 aggregated_output 核：没截断时须逐字相同，且不超过 Codex 的可见上限
    （更长的输出 Codex 必定截断，声称整段可见的是伪造，#2037 第二轮独审 BLOCK）；截断时须是 Codex 的原样：开头的
    警告里 original token count、Total output lines 与 aggregated_output 相符，一个 `…N chars truncated…` 两侧的首段是前缀、
    末段是后缀、两段字符数加 N 恰为 aggregated_output 的字符数、两段合计不超过上限；截断处两侧的半行去掉。对不上给 None。"""
    size = len(aggregated.encode())
    if visible == aggregated:
        return [(0, len(aggregated))] if size <= CODEX_VISIBLE_BYTES else None
    preamble = _PREAMBLE.match(visible)
    lines = aggregated.count("\n") + (not aggregated.endswith("\n") and aggregated != "")
    if (preamble is None or size <= CODEX_VISIBLE_BYTES
            or (int(preamble.group(1)), int(preamble.group(2))) != (-(-size // 4), lines)):
        return None
    rest = visible[preamble.end():]
    for marker in _MARKER.finditer(rest):
        head, tail = rest[:marker.start()], rest[marker.end():]
        if (len(head) + int(marker.group(1)) + len(tail) == len(aggregated) and aggregated.startswith(head)
                and aggregated.endswith(tail) and len(head.encode()) + len(tail.encode()) <= CODEX_VISIBLE_BYTES):
            head_end = aggregated.rfind("\n", 0, len(head)) + 1  # 截断处之前的半行不算
            newline = aggregated.find("\n", len(aggregated) - len(tail))  # 截断处之后的半行不算
            return [(0, head_end), (len(aggregated) if newline < 0 else newline + 1, len(aggregated))]
    return None


def seen_pieces(aggregated: str, git: list[tuple[int, int]], visible: list[tuple[int, int]]) -> list[str]:
    """既出自 git 段、又是模型看到的那些片段。"""
    return [aggregated[max(a, c):min(b, d)] for a, b in git for c, d in visible if max(a, c) < min(b, d)]


def git_spans(aggregated: str, segments: list[str | None], *, failed: bool) -> list[tuple[int, int]] | None:
    """按执行顺序把输出切开：segments 里 None 是 git 段，字符串是输出可算准的段（printf、echo、cat）的输出。
    后者逐个按顺序在 aggregated_output 里找到并剔除，两个已知段之间、且其间确有 git 段的部分记为 git 的输出，
    之间没有 git 段的部分不认。已知段找不到时：整条命令成功就是对不上，给 None；整条命令失败（`&&` 链中途断了，
    之后的段可能没跑）只留此前两头都有已知段夹住的部分，剩下的输出来源不明，不算给 git（#2037 第二轮正式审查 opus
    BLOCK：已知段的真实输出与模拟不符时，它会混在剩下的输出里冒充 git）。"""
    spans: list[tuple[int, int]] = []
    position, git_since = 0, False
    for segment in segments:
        if segment is None:
            git_since = True
            continue
        found = aggregated.find(segment, position)
        if found < 0:
            return spans if failed else None
        if git_since:
            spans.append((position, found))
        position, git_since = found + len(segment), False
    if git_since:
        spans.append((position, len(aggregated)))
    return spans


# ---- 命令是否只由合格段组成 ----

_DIFF_OPTION = (r"--no-ext-diff|--no-textconv|--no-color|--color=never|-U\d+|--unified=\d+|-p|-u|--patch|"
                r"--stat(?:=[\d,]+)?|--stat-width=\d+|--numstat|--shortstat|--summary|--name-status|--name-only|"
                r"--no-renames|-M(?:\d+%?)?|--find-renames(?:=\d+%?)?|--diff-filter=[ACDMRTUXBacdmrtux]+|"
                r"--minimal|--patience|--histogram|--check")
_DIFF_OK = re.compile(_DIFF_OPTION)
_LOG_OK = re.compile(_DIFF_OPTION + r"|-s|--no-patch|--oneline|--no-decorate|--decorate|--no-abbrev-commit|"
                     r"--abbrev-commit|--reverse|--first-parent|--no-merges|-\d+|--max-count=\d+|"
                     r"--date=(?:iso|iso-strict|short|relative|rfc|raw|unix|default)")
_STATUS_OK = re.compile(r"-s|--short|--porcelain(?:=v1)?|-b|--branch|-uno|--untracked-files=no")
# 命名格式只认不印提交正文的：标题跟在提交号后或缩进（medium、full、fuller 印正文，#2037 第二轮正式审查 kimi BLOCK）
_SAFE_NAMED = frozenset({"oneline", "short", "reference"})
_LEAD = re.compile(r"%[HhTtPp]")  # 格式串每行须以提交号类占位符开头：行首不会是作者能写的文字
# 占位符只认单行的：`%b`、`%B` 展开成多行正文，后面的行不带提交号前缀（同上 kimi BLOCK：`--format='%H %b'`）
_PLACEHOLDERS = re.compile(r"(?:%(?:[HhTtPpsn%]|[ac][neEdDrtiIsh])|[ :,|/()\[\]-])*")


def _format_ok(value: str) -> bool:
    if value in _SAFE_NAMED:
        return True
    body = re.sub(r"^t?format:", "", value)
    return bool(_PLACEHOLDERS.fullmatch(body)) and all(not line or _LEAD.match(line) for line in body.split("%n"))


def _git_segment(command: _Expanded, revisions: _Revisions) -> str | None:
    """"read"：输出 diff、删除清单（diff/show/log，对 head、merge-base、base）；"meta"：只印提交号、状态等元数据；
    其余 None。stdout 不能转向，stderr 只能丢掉或并进 stdout；全局选项只认 `--no-pager`/`-P`、`-C /review` 与
    _CONFIG_KEYS 里的 `-c`。"""
    argv = command.argv
    if not argv or argv[0] not in ("git", "/usr/bin/git"):
        return None
    if any((op, target) not in (("2>", "/dev/null"), ("2>&", "1")) for op, target in command.redirects):
        return None
    i = 1
    while i < len(argv):
        if argv[i] in ("--no-pager", "-P"):
            i += 1
        elif argv[i] == "-C" and argv[i + 1:i + 2] == ["/review"]:
            i += 2
        elif argv[i] == "-c" and i + 1 < len(argv) and argv[i + 1].partition("=")[0].lower() in _CONFIG_KEYS:
            i += 2
        else:
            break
    if i >= len(argv) or any(_OPAQUE in arg for arg in argv):
        return None
    sub, rest = argv[i], argv[i + 1:]
    separator = rest.index("--") if "--" in rest else len(rest)
    options: list[str] = []
    positional: list[str] = []
    j = 0
    while j < separator:
        arg = rest[j]
        if arg == "-n" and sub == "log" and j + 1 < separator and rest[j + 1].isdigit():
            j += 2
            continue
        (options if arg.startswith("-") else positional).append(arg)
        j += 1
    if sub == "status":
        return "meta" if all(_STATUS_OK.fullmatch(o) for o in options) and not positional and separator == len(rest) else None
    if sub in ("rev-parse", "merge-base"):
        flags = ("--verify", "-q", "--quiet", "--short") if sub == "rev-parse" else ("--is-ancestor", "--all")
        ok = all(o in flags or (sub == "rev-parse" and re.fullmatch(r"--short=\d+", o)) for o in options)
        return "meta" if ok and separator == len(rest) and all(_rev_ok(p, revisions) for p in positional) else None
    if sub == "diff":
        if not all(_DIFF_OK.fullmatch(o) for o in options):
            return None
        kinds = [revisions.kind(side) for arg in positional for side in _sides(arg)]
        if not kinds or not all(k == "head" or k in _KNOWN for k in kinds):
            return None
        if len(kinds) == 1:
            kinds.append("head")  # 一个提交对工作区；审阅 checkout 已证实停在 head 且干净
        return "read" if "head" in kinds and any(k in _KNOWN for k in kinds) else None
    if sub in ("show", "log"):
        for option in options:
            name, eq, value = option.partition("=")
            if name in ("--format", "--pretty") and eq:
                if not _format_ok(value):
                    return None
            elif not _LOG_OK.fullmatch(option):
                return None
        if any(":" in p for p in positional) or not all(_rev_ok(p, revisions) for p in positional):
            return None
        patchy = (any(_PATCH_ON.fullmatch(o) for o in options) or "--name-status" in options
                  or (sub == "show" and _emits_patch("show", options)))
        if not patchy:
            return "meta"
        # 输出补丁或删除清单时，提交须是 head，或范围以 head 结尾
        heads = [p for p in positional if [revisions.kind(s) for s in _sides(p)][-1] == "head"]
        return "read" if positional and len(heads) == len(positional) else None
    return None


def _sides(arg: str) -> list[str]:
    left, dots, right = arg.partition("..")
    return [left or "HEAD", right.lstrip(".") or "HEAD"] if dots else [arg]


def _rev_ok(arg: str, revisions: _Revisions) -> bool:
    return all(revisions.kind(side) == "head" or revisions.kind(side) in _KNOWN for side in _sides(arg))


def _printf(argv: list[str]) -> str | None:
    """`printf <格式> [参数…]` 的输出；只认 `%s`、`%%` 和常见反斜杠转义，别的不算。"""
    if len(argv) < 2 or argv[1].startswith("-"):
        return None
    fmt, args = argv[1], argv[2:]
    escapes = {"n": "\n", "t": "\t", "\\": "\\", '"': '"', "'": "'"}
    pieces: list[str | None] = []  # None 处填参数
    i = 0
    while i < len(fmt):
        c = fmt[i]
        if c == "\\" and i + 1 < len(fmt) and fmt[i + 1] in escapes:
            pieces.append(escapes[fmt[i + 1]])
            i += 2
        elif c == "%" and fmt[i + 1:i + 2] == "%":
            pieces.append("%")
            i += 2
        elif c == "%" and fmt[i + 1:i + 2] == "s":
            pieces.append(None)
            i += 2
        elif c in "%\\":
            return None
        else:
            pieces.append(c)
            i += 1
    slots = pieces.count(None)
    if not slots:
        return "".join(p for p in pieces if p is not None)
    out = []
    for start in range(0, max(len(args), 1), slots):
        chunk = iter(args[start:start + slots])
        out.append("".join(p if p is not None else next(chunk, "") for p in pieces))
    return "".join(out)


def _known_output(command: _Expanded, blob: Callable[[str], str | None]) -> str | None:
    """输出在 controller 侧能算准的段：printf、echo（不带选项）、`cat /review/<文件>`（head 上的内容）。"""
    argv = command.argv
    if command.redirects or not argv:
        return None
    if argv[0] == "printf":
        return _printf(argv)
    if argv[0] == "echo" and not any(a.startswith("-") for a in argv[1:2]):
        return " ".join(argv[1:]) + "\n"
    if argv[0] == "cat" and len(argv) == 2 and argv[1].startswith("/review/"):
        path = posixpath.normpath(argv[1]).removeprefix("/review/")
        if path.startswith(("..", ".git/")) or path in (".git", "", "."):
            return None
        return blob(path)
    return None


def _inert(text: str) -> bool:
    """非 git 段的输出不能冒充 git：没有 `diff --git` 头、没有 `D<TAB>` 删除行（#2037 opus BLOCK：照提示词里的清单
    printf 出删除清单或文件头）。它在输出里的位置由 git_spans 剔除，接不进前后的 diff。"""
    return not any(line.startswith("diff --git ") or _DELETED.fullmatch(line) for line in _lines(text))


def coverage_segments(command: str, revisions: _Revisions,
                      blob: Callable[[str], str | None]) -> list[str | None] | None:
    """整条命令只由合格段组成且至少有一个合格 git 读取时，按执行顺序给出各段（git 段为 None，输出可算准的段为其输出，
    不输出的段略去）；否则 None。段之间只用 `;`、`&&`、换行，git 段之后可接 patch_read 的纯过滤器管道；没有 `||`、
    子 shell、后台、控制结构、命令替换、改 git 行为的环境变量。"""
    script = _script(command)
    if script is None:
        return None
    items = _parse(_lex(script))
    if any(item in ("(", ")") for item in items):
        return None
    commands = [x for x in items if isinstance(x, _Command)]
    if not commands or any(kind == "opaque" for c in commands
                           for word in [*c.words, *(t for _, t in c.redirects)] for kind, _ in word):
        return None
    expanded = _evaluate(items)
    if any("\n" in arg or _BREAK.search(arg) for e in expanded for arg in e.argv) or any(
            _SPECIAL_NAME.fullmatch(name) for e in expanded for name in e.env_names):
        return None
    segments: list[str | None] = []
    read = False
    i = 0
    while i < len(commands):
        end = i
        while commands[end].op in _PIPE:
            end += 1
            if end == len(commands):
                return None
        if commands[end].op not in (";", "&&", "\n", ""):
            return None
        head, filters = expanded[i], expanded[i + 1:end + 1]
        kind = _git_segment(head, revisions)
        if kind is None:
            if filters:
                return None
            if not (_setup(head) or head.argv in (["true"], [":"])):
                text = _known_output(head, blob)
                if text is None or not _inert(text):
                    return None
                if text:
                    segments.append(text)
        elif not all(_filter(f) for f in filters):
            return None
        else:
            segments.append(None)
        read = read or kind == "read"
        i = end + 1
    return segments if read else None
