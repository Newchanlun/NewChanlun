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


def names(node, bindings):
    if isinstance(node, ast.Name):
        return bindings.get(node.id, (node.id,))
    if isinstance(node, ast.Attribute):
        receiver = node.value.func if isinstance(node.value, ast.Call) else node.value
        base = names(receiver, bindings)
        return (*base, node.attr) if base else ()
    return ()


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


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITIONS = (*FUNCTIONS, ast.ClassDef)


def definition(tree, symbol):
    for i, name in enumerate(symbol):
        if i and not isinstance(tree, ast.ClassDef):
            return None
        node = next((n for n in reversed(tree.body) if isinstance(n, DEFINITIONS) and n.name == name), None)
        if node is None:
            return None
        tree = node
    return tree


def line(node):
    return min((d.lineno for d in node.decorator_list), default=node.lineno)


def calls(node):
    if isinstance(node, ast.Call):
        yield node
    if not isinstance(node, (*DEFINITIONS, ast.Lambda)):
        for child in ast.iter_child_nodes(node):
            yield from calls(child)


def integration_targets(entry, start):
    paths = {}
    for file in Path("trading_system").rglob("*.py"):
        if "tests" in file.parts:
            continue
        path = file.as_posix()
        paths.setdefault(module(path), []).append(path)
    seen, targets = set(), set()

    @cache
    def parsed(path):
        return ast.parse(Path(path).read_bytes(), path)

    def walk(path, symbol):
        if not symbol or (path, symbol) in seen:
            return
        seen.add((path, symbol))
        tree = parsed(path)
        local = definition(tree, symbol)
        if path == entry:
            # 构造函数和类上的其他方法是不同的轨迹目标。
            found = (definition(local, (name,)) for name in ("__new__", "__init__")) if isinstance(local, ast.ClassDef) else (local,)
            targets.update(node for node in found if isinstance(node, FUNCTIONS) and substantive(node))
            return
        if isinstance(local, ast.ClassDef):
            for name in ("__new__", "__init__"):
                walk(path, (*symbol, name))
        elif isinstance(local, FUNCTIONS):
            params = [*local.args.posonlyargs, *local.args.args, *local.args.kwonlyargs,
                      local.args.vararg, local.args.kwarg]
            bindings = {arg.arg: () for arg in params if arg}
            positional = [*local.args.posonlyargs, *local.args.args]
            if len(symbol) > 1 and positional and not any(
                isinstance(d, ast.Name) and d.id == "staticmethod" for d in local.decorator_list
            ):
                bindings[positional[0].arg] = symbol[:-1]
            for statement in local.body:
                for call in calls(statement):
                    walk(path, names(call.func, bindings))
                if isinstance(statement, ast.Assign):
                    value = statement.value.func if isinstance(statement.value, ast.Call) else statement.value
                    bound = names(value, bindings)
                    for target in statement.targets:
                        if isinstance(target, ast.Name):
                            bindings[target.id] = bound
        else:
            # 只有上游调用了该名字，才沿重导出继续；孤立的 import 不构成接入。
            imported(path, symbol)

    def imported(path, symbol):
        for origin, alias in imports(parsed(path), path):
            if tuple(alias) != symbol[:len(alias)]:
                continue
            qualified = [*origin, *symbol[len(alias):]]
            for end in range(len(qualified) - 1, 0, -1):
                hits = paths.get(".".join(qualified[:end]), [])
                if len(hits) == 1 and hits[0] != path:
                    walk(hits[0], tuple(qualified[end:]))
                    break

    tree = parsed(start)
    for node in tree.body:
        if isinstance(node, DEFINITIONS) and not node.name.startswith("_"):
            walk(start, (node.name,))
            if isinstance(node, ast.ClassDef):
                for method in node.body:
                    if isinstance(method, FUNCTIONS) and not method.name.startswith("_"):
                        walk(start, (node.name, method.name))
    return targets


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
    targets = integration_targets(entry, integration)
    if not targets:
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
