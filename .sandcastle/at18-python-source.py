"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import json
import sys
from functools import cache
from pathlib import Path
from types import CodeType

import pytest


def substantive(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return any(map(substantive, node.body))
    if isinstance(node, ast.Expr):
        return not isinstance(node.value, ast.Constant)
    return isinstance(node, ast.stmt) and not isinstance(node, (ast.Pass, ast.Import, ast.ImportFrom))


def module(path):
    return path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*names(node.value), node.attr]
    return []


def imports(tree, path):
    package = module(path).split(".")
    if not path.endswith("/__init__.py"):
        package.pop()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted = alias.name.split(".")
                yield dotted, [alias.asname] if alias.asname else dotted
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                continue
            prefix = package[:len(package) - node.level + 1] if node.level else []
            if node.module:
                prefix += node.module.split(".")
            for alias in node.names:
                if alias.name != "*":
                    yield [*prefix, alias.name], [alias.asname or alias.name]


def definitions(tree):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and substantive(node):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from definitions(node)


def line(node):
    return min((d.lineno for d in node.decorator_list), default=node.lineno)


def integration_reaches(entry, start, exports):
    paths = {}
    for file in Path("trading_system").rglob("*.py"):
        if "tests" in file.parts:
            continue
        path = file.as_posix()
        paths.setdefault(module(path), []).append(path)
    seen = set()

    @cache
    def parsed(path):
        tree = ast.parse(Path(path).read_bytes(), path)
        return tree, list(imports(tree, path))

    def walk(path, symbol):
        if path == entry:
            return symbol in exports
        key = (path, symbol)
        if key in seen:
            return False
        seen.add(key)
        tree, bindings = parsed(path)
        local = [node for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol]
        if not local:
            # 只沿实际被上游调用的重导出继续，不把孤立的 import 当作接入。
            return any(resolve(path, origin) for origin, alias in bindings if alias == [symbol])
        for node in ast.walk(local[-1]):
            if not isinstance(node, ast.Call):
                continue
            use = names(node.func)
            if len(use) == 1 and walk(path, use[0]):
                return True
            if any(resolve(path, origin + use[len(alias):]) for origin, alias in bindings if use[:len(alias)] == alias):
                return True
        return False

    def resolve(path, qualified):
        for end in range(len(qualified) - 1, 0, -1):
            hits = paths.get(".".join(qualified[:end]), [])
            if len(hits) == 1 and hits[0] != path:
                return walk(hits[0], qualified[end])
        return False

    tree, _ = parsed(start)
    return any(walk(start, node.name) for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"))


def code_objects(code):
    for child in code.co_consts:
        if isinstance(child, CodeType):
            yield child
            yield from code_objects(child)


def selected_test(path, selector):
    node = ast.parse(Path(path).read_bytes(), path)
    for part in selector.split("[", 1)[0].split("::"):
        matches = [child for child in node.body if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                   and child.name == part]
        if len(matches) != 1:
            return None
        node = matches[0]
    return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def proves(doc, scratch):
    entry, integration, path, selector = (doc[k] for k in ("entry", "integration", "checkPath", "selector"))
    test = selected_test(path, selector)
    if test is None:
        return False
    source = Path(entry).read_bytes()
    source_path, test_path = str(Path(entry).resolve()), str(Path(path).resolve())
    source_tree = ast.parse(source, source_path)
    targets = list(definitions(source_tree))
    exports = {node.name for node in source_tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and substantive(node)}
    if not targets or not integration_reaches(entry, integration, exports):
        return False
    positions = {(line(node), node.name) for node in targets}
    test_position = (line(test), test.name)
    target_codes = {code for code in code_objects(compile(source, source_path, "exec"))
                    if (code.co_firstlineno, code.co_name) in positions}

    class Trace:
        covered = False
        passed = 0
        nonpass = False

        def profile(self, frame, event, _arg):
            code = frame.f_code
            if event != "call" or code.co_filename != source_path or code not in target_codes:
                return
            parent = frame.f_back
            while parent is not None:
                code = parent.f_code
                if code.co_filename == test_path and (code.co_firstlineno, code.co_name) == test_position:
                    self.covered = True
                    return
                parent = parent.f_back

        @pytest.hookimpl(wrapper=True, trylast=True)
        def pytest_runtest_call(self, item):
            sys.setprofile(self.profile)
            try:
                return (yield)
            finally:
                sys.setprofile(None)

        def pytest_runtest_logreport(self, report):
            self.nonpass |= not report.passed or hasattr(report, "wasxfail")
            if report.when == "call" and report.passed:
                self.passed += 1

    trace = Trace()
    sys.path.insert(0, str(Path.cwd()))
    result = pytest.main(["-p", "no:cacheprovider", "-p", "no:terminal", "--basetemp", scratch + "/pytest",
                          path + "::" + selector], plugins=[trace])
    return result == pytest.ExitCode.OK and not trace.nonpass and trace.passed == doc["count"] and trace.covered


if __name__ == "__main__":
    if proves(json.load(sys.stdin), sys.argv[1]):
        print("AT18_PYTHON_COVERED")
    else:
        sys.exit(1)
