"""只接收能够绑定到源文件、且有执行身份的选择器。"""
from __future__ import annotations

import ast
import re
import sys
import tokenize
from io import StringIO
from pathlib import PurePosixPath

from common import require

PY_SELECTOR = re.compile(r"(?:[A-Za-z_][\w]*::)*[A-Za-z_][\w]*(?:\[[^\]\r\n]+\])?", re.ASCII)
RUST_SELECTOR = re.compile(r"(lib|[A-Za-z_][A-Za-z0-9_-]*)(?:\+([A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*))?/([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)")
MARKER = re.compile(r"(?:#|//)\s*@at18 (TB-\d\d) (story|family|detail) (\S+)\s*")
JS_DECL = re.compile(r"""^\s*(?:(?:test|it)\s*\(|(?:test|it)\.(?:skip|todo)\s*\()\s*(["'])([^"'\\]+)\1\s*,""")
RUST_FN = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RUST_ATTR = re.compile(r"^\s*#\[.*\]\s*$")


def command(check, root):
    source, selector = check["source"]["path"], check["selector"]
    runner = check["runner"]
    require(all(ord(c) >= 32 for c in selector), "CHECK_SELECTOR", check["check_id"])
    if runner == "command":
        require(selector == source, "CHECK_SELECTOR", check["check_id"])
        return [str(root / source)]
    if runner == "pytest":
        require(PY_SELECTOR.fullmatch(selector) and source.endswith(".py"), "CHECK_SELECTOR", selector)
        return [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "at18_pytest",
                "-q", "--rootdir", str(root), source + "::" + selector]
    if runner == "node-test":
        require(source.endswith((".mjs", ".js", ".cjs", ".ts", ".mts", ".cts")) and selector.strip() == selector,
                "CHECK_SELECTOR", selector)
        return ["node", "--test", "--test-name-pattern", "^" + re.sub(r"([\\.^$*+?{}\[\]|()])", r"\\\1", selector) + "$",
                "--test-reporter", str(root / "scripts/at18/node_reporter.mjs"), source]
    match = RUST_SELECTOR.fullmatch(selector)
    require(match and source.endswith(".rs"), "CHECK_SELECTOR", selector)
    target, features, name = match.groups()
    if target == "lib":
        require(source.startswith("rust/src/"), "CHECK_SELECTOR", selector)
        modules = list(PurePosixPath(source).relative_to("rust/src").with_suffix("").parts)
        if modules[-1] in ("mod", "lib"):
            modules.pop()
        require(name.split("::")[:len(modules)] == modules, "CHECK_SELECTOR", selector)
    else:
        require(source == f"rust/tests/{target}.rs", "CHECK_SELECTOR", selector)
    argv = ["cargo", "test", "--locked", "--manifest-path", "rust/Cargo.toml"]
    if features:
        require(len(set(features.split(","))) == len(features.split(",")), "CHECK_SELECTOR", selector)
        argv += ["--features", features]
    argv += ["--lib"] if target == "lib" else ["--test", target]
    return argv + [name, "--", "--exact", "--test-threads", "1", "--color", "never"]


def _python_functions(text):
    comment_lines = {t.start[0]: t.string for t in tokenize.generate_tokens(StringIO(text).readline)
                     if t.type == tokenize.COMMENT and not t.line[:t.start[1]].strip()}
    def walk(body, parents=()):
        for node in body:
            if isinstance(node, ast.ClassDef):
                yield from walk(node.body, parents + (node.name,))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                line = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
                yield "::".join(parents + (node.name,)), line, node.lineno
    return walk(ast.parse(text).body), comment_lines


def _rust_tokens(text):
    # 先遮住字符串和整段块注释、保留行号；只提取真正的行注释。
    tokens = re.compile(r'//[^\n]*|/\*|r(\#{0,255})"|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\n\'\\])\'')
    comments = {}
    cut = []
    pos = 0
    while match := tokens.search(text, pos):
        start, end = match.span()
        cut.append(text[pos:start])
        if match[0].startswith("//"):
            line = text.count("\n", 0, start) + 1
            if not text[text.rfind("\n", 0, start) + 1:start].strip():
                comments[line] = match[0]
        elif match[0] == "/*":
            depth = 1
            while depth:
                edge = re.search(r"/\*|\*/", text[end:])
                require(edge is not None, "CHECK_SELECTOR", "Rust block comment")
                end += edge.end()
                depth += 1 if edge[0] == "/*" else -1
        elif match[1] is not None:
            closing = '"' + match[1]
            index = text.find(closing, end)
            require(index >= 0, "CHECK_SELECTOR", "Rust raw string")
            end = index + len(closing)
        cut.append(re.sub(r"[^\n]", " ", text[start:end]))
        pos = end
    cut.append(text[pos:])
    return "".join(cut).splitlines(), comments


def annotation(check, source):
    """返回选中定义的行号及紧贴定义的注释块；不会向同源其他测试借标注。"""
    runner, selector = check["runner"], check["selector"]
    if runner == "command":
        return None, set()
    text = source.decode("utf-8")
    lines = text.splitlines()
    declarations = []
    if runner == "pytest":
        functions, comments = _python_functions(text)
        declarations = [(start, line) for name, start, line in functions if name == selector.split("[")[0]]
    elif runner == "node-test":
        comments = {i: row.lstrip() for i, row in enumerate(lines, 1) if row.lstrip().startswith("//")}
        declarations = [(i, i) for i, row in enumerate(lines, 1)
                        if (m := JS_DECL.match(row)) and m[2] == selector]
    else:
        rust, comments = _rust_tokens(text)
        target = selector.rsplit("/", 1)[1].split("::")[-1]
        for i, row in enumerate(rust, 1):
            m = RUST_FN.match(row)
            if m and m[1] == target:
                first = i
                while first > 1 and RUST_ATTR.fullmatch(rust[first - 2]):
                    first -= 1
                if any(re.fullmatch(r"\s*#\[test\]\s*", x) for x in rust[first - 1:i - 1]):
                    declarations.append((first, i))
    require(len(declarations) == 1, "CHECK_SELECTOR", check["check_id"])
    start, line = declarations[0]
    keys = set()
    for at in range(start - 1, 0, -1):
        if at not in comments:
            break
        if marker := MARKER.fullmatch(comments[at]):
            keys.add(marker.groups())
    return (start, line), keys


def selector_matches(check, actual):
    selector = check["selector"]
    if check["runner"] == "pytest":
        exact = check["source"]["path"] + "::" + selector
        return actual == exact or ("[" not in selector and actual.startswith(exact + "[") and actual.endswith("]"))
    if check["runner"] == "cargo-test":
        return actual == selector.rsplit("/", 1)[1]
    return actual == selector
