"""从 Cargo target 沿 Rust 的模块声明走到直接定义的 libtest 用例。"""
from __future__ import annotations

import re
import tomllib
from pathlib import PurePosixPath

from tree_sitter import Language, Parser
import tree_sitter_rust

from common import path_name, require

SELECTOR = re.compile(
    r"(lib|(?:bin:|test:)?[A-Za-z_][A-Za-z0-9_-]*)(?:\+([A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*))?"
    r"/([A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*)"
)
LANGUAGE = Language(tree_sitter_rust.language())


def selection(selector):
    match = SELECTOR.fullmatch(selector)
    require(match, "CHECK_SELECTOR", "Rust target/test path")
    target, features, name = match.groups()
    require(not features or len(set(features.split(","))) == len(features.split(",")),
            "CHECK_SELECTOR", "Rust features")
    kind, target = ("lib", None) if target == "lib" else (
        target.split(":", 1) if ":" in target else ("test", target))
    return kind, target, features, name


def target_path(root, read, kind, target):
    manifest = tomllib.loads(read("rust/Cargo.toml").decode("utf-8"))
    package = manifest["package"]

    def exists(path):
        p = root / path
        return p.exists() or p.is_symlink()

    if kind == "lib":
        rule = manifest.get("lib", {})
        path = "rust/" + path_name(rule.get("path", "src/lib.rs"))
    else:
        explicit = [entry for entry in manifest.get(kind, []) if entry["name"] == target]
        require(len(explicit) <= 1, "CHECK_SELECTOR", "ambiguous Cargo target")
        rule = explicit[0] if explicit else {}
        if "path" in rule:
            path = "rust/" + path_name(rule["path"])
        else:
            # Cargo 2015 仅在未声明这一类 target 时默认开启自动发现。
            auto = package.get({"test": "autotests", "bin": "autobins"}[kind])
            edition = package.get("edition", "2015")
            if isinstance(edition, dict):
                edition = manifest.get("workspace", {}).get("package", {}).get("edition")
            require(explicit or auto is True or auto is None and (
                    not manifest.get(kind) or edition in ("2018", "2021", "2024")),
                    "CHECK_SELECTOR", "Cargo automatic target")
            parent = "rust/tests" if kind == "test" else "rust/src/bin"
            candidates = [f"{parent}/{target}.rs", f"{parent}/{target}/main.rs"]
            if kind == "bin" and target == package["name"]:
                candidates.append("rust/src/main.rs")
            found = [p for p in candidates if exists(p)]
            require(len(found) == 1, "CHECK_SELECTOR", "missing or ambiguous Cargo target")
            path = found[0]
    require(rule.get("harness", True) is True and rule.get("test", True) is True,
            "CHECK_SELECTOR", "nonstandard Rust test harness")
    return PurePosixPath(path)


def declaration(root, read, check):
    kind, target, _, name = selection(check["selector"])
    path = target_path(root, read, kind, target)
    parser = Parser(LANGUAGE)

    def parse(path):
        source = read(str(path))
        ast = parser.parse(source).root_node
        require(not ast.has_error and not any(
            node.type == "inner_attribute_item" and b"test_runner" in node.text for node in ast.named_children),
            "CHECK_SELECTOR", "Rust parse/harness: " + str(path))
        return ast, source.splitlines()

    def find(scope, item_type, ident):
        found = []
        attrs = []
        for node in scope.named_children:
            if node.type == "attribute_item":
                attrs.append(node)
                continue
            if node.type in ("line_comment", "block_comment"):
                continue
            require(node.type != "macro_invocation" and not (
                node.type == "expression_statement" and node.named_children
                and node.named_children[0].type == "macro_invocation"),
                "CHECK_SELECTOR", "Rust item expansion in selected scope: " + name)
            if node.type == item_type and node.child_by_field_name("name").text.removeprefix(b"r#") == ident.encode():
                found.append((node, attrs))
            attrs = []
        require(len(found) == 1, "CHECK_SELECTOR", "missing or ambiguous Rust definition: " + name)
        node, attrs = found[0]
        # cfg_attr、#[path] 或外部属性宏能改写所选定义。只接受直接、标准的声明。
        require(all(a.named_children[0].named_children[0].text in {
                    b"test", b"cfg", b"allow", b"warn", b"deny", b"forbid", b"ignore",
                    b"should_panic", b"doc", b"deprecated", b"inline", b"cold",
                    } for a in attrs),
                "CHECK_SELECTOR", "Rust definition-changing attribute: " + name)
        return node, attrs

    scope, lines = parse(path)
    directory = path.parent
    for module in name.split("::")[:-1]:
        node, _ = find(scope, "mod_item", module)
        directory /= module
        if (body := node.child_by_field_name("body")) is not None:
            scope = body
        else:
            candidates = [directory.with_suffix(".rs"), directory / "mod.rs"]
            found = [p for p in candidates if (root / p).exists() or (root / p).is_symlink()]
            require(len(found) == 1, "CHECK_SELECTOR", "missing or ambiguous Rust module: " + module)
            path = found[0]
            scope, lines = parse(path)
    require(str(path) == check["source"]["path"], "CHECK_SELECTOR",
            f"Rust definition file is {path}, not {check['source']['path']}")
    node, attrs = find(scope, "function_item", name.split("::")[-1])
    tests = [attr for attr in attrs if attr.named_children[0].text == b"test"]
    require(len(tests) == 1 and node.child_by_field_name("body") is not None,
            "CHECK_SELECTOR", "Rust direct #[test]: " + name)
    first = (attrs[0] if attrs else node).start_point.row + 1
    comments = {item.start_point.row + 1: item.text.decode("utf-8") for item in scope.named_children
                if item.type == "line_comment" and item.end_point.row == item.start_point.row
                and not lines[item.start_point.row][:item.start_point.column].strip()}
    return (first, node.start_point.row + 1), comments
