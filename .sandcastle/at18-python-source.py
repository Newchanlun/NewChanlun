"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import json
import sys
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


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINITIONS = (*FUNCTIONS, ast.ClassDef)


def line(node):
    return min((d.lineno for d in node.decorator_list), default=node.lineno)


def parameters(args):
    return [*args.posonlyargs, *args.args, *args.kwonlyargs,
            *[arg for arg in (args.vararg, args.kwarg) if arg]]


class Locals(ast.NodeVisitor):
    """函数整段预先决定哪些名字是局部；赋值/导入才在执行到时建立值。"""

    def __init__(self, body, args=()):
        self.bound = {arg.arg for arg in args}
        self.external = set()
        for node in body:
            self.visit(node)
        self.bound.difference_update(self.external)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bound.add(node.id)

    def visit_Import(self, node):
        self.bound.update(a.asname or a.name.split(".")[0] for a in node.names if a.name != "*")

    visit_ImportFrom = visit_Import

    def visit_FunctionDef(self, node):
        self.bound.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_Lambda(self, node):
        pass

    def visit_Global(self, node):
        self.external.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.bound.add(node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.bound.add(node.rest)
        self.generic_visit(node)

    def visit_ListComp(self, node):
        # 推导式目标不写入外部作用域；命名表达式除外。
        for nested in ast.walk(node):
            if isinstance(nested, ast.NamedExpr):
                self.visit(nested.target)

    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp


class Scope:
    def __init__(self, path, parent=None, initial=(), is_class=False):
        self.path = path
        self.parent = parent
        self.values = dict.fromkeys(initial)
        self.is_class = is_class

    def get(self, name):
        if name in self.values:
            return self.values[name]
        return self.parent.get(name) if self.parent is not None else None

    def lexical_parent(self):
        # 类命名空间不是方法或嵌套类的闭包。
        return self.parent if self.is_class else self


class Routine:
    def __init__(self, node, scope):
        self.node = node
        self.scope = scope
        self.static = False
        self.defaults = {}


class Class:
    def __init__(self, scope):
        self.values = scope.values


class Pending:
    def __init__(self, routine, args, keywords):
        self.routine, self.args, self.keywords = routine, args, keywords


class Instance:
    def __init__(self, cls):
        self.cls = cls


def assign(node, value, scope):
    if isinstance(node, ast.Name):
        scope.values[node.id] = value
    elif isinstance(node, (ast.Tuple, ast.List)):
        for target in node.elts:
            assign(target, None, scope)
    elif isinstance(node, ast.Starred):
        assign(node.value, None, scope)


def import_bindings(node, path):
    if isinstance(node, ast.Import):
        for alias in node.names:
            origin = tuple(alias.name.split("."))
            yield alias.asname or origin[0], origin if alias.asname else origin[:1]
    else:
        package = module(path).split(".")
        if not path.endswith("/__init__.py"):
            package.pop()
        if node.level > len(package):
            return
        prefix = package[:len(package) - node.level + 1] if node.level else []
        if node.module:
            prefix += node.module.split(".")
        for alias in node.names:
            if alias.name != "*":
                yield alias.asname or alias.name, (*prefix, alias.name)


def integration_targets(entry, start):
    paths = {}
    for file in Path("trading_system").rglob("*.py"):
        if "tests" not in file.parts:
            path = file.as_posix()
            paths.setdefault(module(path), []).append(path)
    modules, active, targets = {}, set(), set()

    def load(path):
        if path not in modules:
            tree = ast.parse(Path(path).read_bytes(), path)
            scope = modules[path] = Scope(path)
            statements(tree.body, scope, False)
        return modules[path]

    def resolve(ref):
        seen = set()
        while isinstance(ref, tuple) and ref not in seen:
            seen.add(ref)
            for end in range(len(ref) - 1, 0, -1):
                hits = paths.get(".".join(ref[:end]), [])
                if len(hits) == 1:
                    value = load(hits[0]).get(ref[end])
                    tail = ref[end + 1:]
                    if value is not None:
                        for name in tail:
                            value = attribute(value, name)
                        ref = value
                        break
            else:
                return None
        return None if isinstance(ref, tuple) else ref

    def attribute(value, name):
        if isinstance(value, tuple):
            return (*value, name)
        if isinstance(value, Instance):
            method = value.cls.values.get(name)
            if isinstance(method, Routine) and not method.static:
                return [method, value]  # 已绑定实例的方法。
            return method
        if isinstance(value, Class):
            return value.values.get(name)
        return None

    def invoke(value, args, keywords, record, awaited=False):
        value = resolve(value)
        if isinstance(value, Class):
            obj = Instance(value)
            for name in ("__new__", "__init__"):
                invoke([value.values.get(name), obj], args, keywords, record)
            return obj
        if isinstance(value, list):
            value, receiver = value
            args = [receiver, *args]
        if not isinstance(value, Routine) or value.node in active:
            return None
        node = value.node
        if isinstance(node, ast.AsyncFunctionDef) and not awaited:
            return Pending(value, args, keywords)
        if record and value.scope.path == entry and isinstance(node, FUNCTIONS) and substantive(node):
            targets.add(node)
            return None
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        params = parameters(node.args)
        scope = Scope(value.scope.path, value.scope, Locals(body, params).bound)
        scope.values.update(value.defaults)
        scope.values.update((param.arg, arg) for param, arg in zip([*node.args.posonlyargs, *node.args.args], args))
        scope.values.update((key, value) for key, value in keywords.items() if key in scope.values)
        active.add(node)
        try:
            if isinstance(node, ast.Lambda):
                return expression(node.body, scope, record)
            return statements(body, scope, record)[1]
        finally:
            active.remove(node)

    def routine(node, scope, record):
        value = Routine(node, scope.lexical_parent())
        positional = [*node.args.posonlyargs, *node.args.args]
        for arg, default in zip(positional[len(positional) - len(node.args.defaults):], node.args.defaults):
            value.defaults[arg.arg] = expression(default, scope, record)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                value.defaults[arg.arg] = expression(default, scope, record)
        return value

    def expression(node, scope, record):
        if isinstance(node, ast.Name):
            return scope.get(node.id)
        if isinstance(node, ast.Attribute):
            return attribute(expression(node.value, scope, record), node.attr)
        if isinstance(node, ast.Lambda):
            return routine(node, scope, record)
        if isinstance(node, ast.Call):
            callee = expression(node.func, scope, record)
            args = [expression(arg, scope, record) for arg in node.args]
            keywords = {kw.arg: expression(kw.value, scope, record) for kw in node.keywords}
            return invoke(callee, args, keywords, record)
        if isinstance(node, ast.Await):
            value = expression(node.value, scope, record)
            if isinstance(value, Pending):
                return invoke(value.routine, value.args, value.keywords, record, awaited=True)
            return None
        if isinstance(node, ast.NamedExpr):
            value = expression(node.value, scope, record)
            assign(node.target, value, scope)
            return value
        if isinstance(node, ast.IfExp):
            expression(node.test, scope, record)
            if isinstance(node.test, ast.Constant):
                return expression(node.body if node.test.value else node.orelse, scope, record)
            expression(node.body, scope, record)
            expression(node.orelse, scope, record)
            return None
        if isinstance(node, ast.BoolOp):
            for part in node.values:
                expression(part, scope, record)
                if isinstance(part, ast.Constant) and bool(part.value) == isinstance(node.op, ast.Or):
                    break
            return None
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            first, *rest = node.generators
            expression(first.iter, scope, record)
            if isinstance(node, ast.GeneratorExp):
                return None
            inner = Scope(scope.path, scope.lexical_parent())
            for index, item in enumerate((first, *rest)):
                if index:
                    expression(item.iter, inner, record)
                assign(item.target, None, inner)
                for test in item.ifs:
                    expression(test, inner, record)
            for field in ("elt", "key", "value"):
                if hasattr(node, field):
                    expression(getattr(node, field), inner, record)
            return None
        if node is not None:
            for child in ast.iter_child_nodes(node):
                expression(child, scope, record)
        return None

    def alternatives(scope, *branches):
        before = scope.values.copy()
        continuing = []
        for run in branches:
            scope.values.clear()
            scope.values.update(before)
            if not run():
                continuing.append(scope.values.copy())
        scope.values.clear()
        for name in before.keys() | {key for state in continuing for key in state}:
            bindings = [state.get(name) for state in continuing]
            scope.values[name] = bindings[0] if bindings and all(value == bindings[0] for value in bindings) else None
        return not continuing

    def statements(body, scope, record):
        def walk(nodes):
            return statements(nodes, scope, record)[0]

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                scope.values.update(import_bindings(node, scope.path))
            elif isinstance(node, FUNCTIONS):
                value = routine(node, scope, record)
                known = all(isinstance(d, ast.Name) and d.id in ("staticmethod", "classmethod") for d in node.decorator_list)
                for deco in node.decorator_list:
                    expression(deco, scope, record)
                value.static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in node.decorator_list)
                scope.values[node.name] = value if known else None
            elif isinstance(node, ast.ClassDef):
                for expr in [*node.bases, *[kw.value for kw in node.keywords], *node.decorator_list]:
                    expression(expr, scope, record)
                namespace = Scope(scope.path, scope.lexical_parent(), is_class=True)
                statements(node.body, namespace, record)
                scope.values[node.name] = Class(namespace) if not node.decorator_list else None
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = expression(node.value, scope, record)
                if not isinstance(node, ast.AnnAssign) or node.value is not None:
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        assign(target, None if isinstance(node, ast.AugAssign) else value, scope)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    assign(target, None, scope)
            elif isinstance(node, (ast.Return, ast.Raise)):
                return True, expression(node.value if isinstance(node, ast.Return) else node.exc, scope, record)
            elif isinstance(node, ast.If):
                expression(node.test, scope, record)
                if isinstance(node.test, ast.Constant):
                    stopped, result = statements(node.body if node.test.value else node.orelse, scope, record)
                    if stopped:
                        return True, result
                elif alternatives(scope, lambda: walk(node.body), lambda: walk(node.orelse)):
                    return True, None
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                expression(node.test if isinstance(node, ast.While) else node.iter, scope, record)

                def iteration():
                    if isinstance(node, (ast.For, ast.AsyncFor)):
                        assign(node.target, None, scope)
                    return walk(node.body)

                alternatives(scope, iteration, lambda: False)
                if walk(node.orelse):
                    return True, None
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    expression(item.context_expr, scope, record)
                    if item.optional_vars:
                        assign(item.optional_vars, None, scope)
                stopped, result = statements(node.body, scope, record)
                if stopped:
                    return True, result
            elif isinstance(node, (ast.Try, ast.TryStar)):
                def handler(item):
                    expression(item.type, scope, record)
                    if item.name:
                        scope.values[item.name] = None
                    stopped = walk(item.body)
                    if item.name:
                        scope.values[item.name] = None
                    return stopped

                stopped = alternatives(scope, lambda: walk(node.body) or walk(node.orelse),
                                       *(lambda item=item: handler(item) for item in node.handlers))
                if walk(node.finalbody) or stopped:
                    return True, None
            elif isinstance(node, ast.Match):
                expression(node.subject, scope, record)

                def arm(case):
                    for name in Locals([case.pattern]).bound:
                        scope.values[name] = None
                    expression(case.guard, scope, record)
                    return walk(case.body)

                alternatives(scope, lambda: False, *(lambda case=case: arm(case) for case in node.cases))
            elif isinstance(node, (ast.Break, ast.Continue)):
                return True, None
            else:
                expression(node, scope, record)
        return False, None

    for name, value in tuple(load(start).values.items()):
        # 单纯导入不构成生产接入；从公开定义的实际调用开始。
        if name.startswith("_"):
            continue
        if isinstance(value, Routine):
            invoke(value, [], {}, True, awaited=True)
        elif isinstance(value, Class):
            instance = invoke(value, [], {}, True)
            for method in value.values:
                if not method.startswith("_"):
                    invoke(attribute(instance, method), [], {}, True, awaited=True)
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
