"""只接收能够绑定到源文件、且有执行身份的选择器。"""
from __future__ import annotations

import ast
import re
import sys
import tokenize
from io import StringIO

from common import read_regular, require
from rust_selector import declaration, selection

PY_SELECTOR = re.compile(r"(?:[A-Za-z_][\w]*::)*[A-Za-z_][\w]*(?:\[[^\]\r\n]+\])?", re.ASCII)
MARKER = re.compile(r"(?:#|//)\s*@at18 (TB-\d\d) (story|family|detail) (\S+)\s*")
JS_DECL = re.compile(r"""^\s*(?:(?:test|it)\s*\(|(?:test|it)\.(?:skip|todo)\s*\()\s*(["'])([^"'\\]+)\1\s*,""")


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
        # 原生转换保留文件/行身份；tsx 的运行时转换可把测试事件行号压成 1。
        loader = ["--experimental-transform-types"] if source.endswith((".ts", ".mts", ".cts")) else []
        return ["node", *loader, "--test", "--test-name-pattern", "^" + re.sub(r"([\\.^$*+?{}\[\]|()])", r"\\\1", selector) + "$",
                "--test-reporter", str(root / "scripts/at18/node_reporter.mjs"), source]
    require(source.endswith(".rs"), "CHECK_SELECTOR", selector)
    kind, target, features, name = selection(selector)
    argv = ["cargo", "test", "--locked", "--manifest-path", "rust/Cargo.toml"]
    if features:
        argv += ["--features", features]
    argv += ["--lib"] if kind == "lib" else ["--" + kind, target]
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


def annotation(check, source, root, *, read_source=None):
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
        location, comments = declaration(root, read_source or (lambda path: read_regular(root, path)), check)
        declarations = [location]
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
        return actual == exact or ("[" not in selector and actual.startswith(exact)
                                   and re.fullmatch(r"\[[A-Za-z0-9_.:+-]{1,128}\]", actual[len(exact):]) is not None)
    if check["runner"] == "cargo-test":
        return actual == selector.rsplit("/", 1)[1]
    return actual == selector
