"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import dis
import json
import sys
from pathlib import Path
from types import AsyncGeneratorType, CodeType, CoroutineType, GeneratorType

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
        self.globals = set()
        self.nonlocals = set()
        for node in body:
            self.visit(node)
        self.bound.difference_update(self.globals | self.nonlocals)

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
        self.globals.update(node.names)

    def visit_Nonlocal(self, node):
        self.nonlocals.update(node.names)

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
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.visit(node.iter)
        for guard in node.ifs:
            self.visit(guard)

    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp


class Scope:
    def __init__(self, path, parent=None, local=None, kind="module"):
        self.path = path
        self.parent = parent
        self.local = local
        self.kind = kind
        self.values = dict.fromkeys(local.bound if local and kind == "function" else ())
        self.module = self if parent is None else parent.module

    def get(self, name, default=None):
        scope = target_scope(self, name)
        if name in scope.values:
            return scope.values[name]
        if self.local and name in self.local.globals:
            return default
        return scope.parent.get(name, default) if scope.parent is not None else default

    def lexical_parent(self):
        # 类命名空间不是方法或嵌套类的闭包。
        return self.parent if self.kind == "class" else self

    def bind(self, name, value):
        target_scope(self, name).values[name] = value


def target_scope(scope, name):
    if scope.local and name in scope.local.globals:
        return scope.module
    if scope.local and name in scope.local.nonlocals:
        outer = scope.parent
        while outer is not None:
            if outer.kind == "function" and name in outer.local.bound:
                return outer
            outer = outer.parent
    return scope


def deferred_kind(node):
    def yields(current):
        if isinstance(current, (*DEFINITIONS, ast.Lambda)):
            return False
        return isinstance(current, (ast.Yield, ast.YieldFrom)) or any(map(yields, ast.iter_child_nodes(current)))

    body = [node.body] if isinstance(node, ast.Lambda) else node.body
    generator = any(map(yields, body))
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_gen" if generator else "coroutine"
    return "sync_gen" if generator else None


class Routine:
    def __init__(self, node, scope):
        self.node = node
        self.scope = scope
        self.static = False
        self.defaults = {}
        self.kind = deferred_kind(node)


class Class:
    def __init__(self, scope):
        self.values = scope.values


class Pending:
    def __init__(self, kind, work):
        self.kind = kind
        self.work = work
        self.exhausted = False


class Consumer:
    def __init__(self, pending, kinds):
        self.pending, self.kinds = pending, kinds


SYNC = ("sync_gen",)
ASYNC = ("async_gen",)
AWAIT = ("coroutine",)
BUILTIN_CONSUMERS = {"list", "tuple", "set", "dict", "next", "sum", "any", "all", "min", "max", "sorted"}
SHORT_CONSUMERS = {"next", "any", "all"}
MISSING = object()


class Suspend(Exception):
    """静态分析只证明已驱动到首个 yield 的前缀；不把剩余部分当成本次执行。"""



class Instance:
    def __init__(self, cls):
        self.cls = cls


def assign(node, value, scope):
    if isinstance(node, ast.Name):
        scope.bind(node.id, value)
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
    modules, active, targets, stepping = {}, set(), set(), set()

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
        if isinstance(value, Pending):
            if value.kind in SYNC and name in ("__next__", "send"):
                return Consumer(value, SYNC)
            if value.kind in ASYNC and name in ("__anext__", "asend"):
                return Consumer(value, ASYNC)
        return None

    def invoke(value, args, keywords, record, driving=False, step=False):
        if isinstance(value, Consumer):
            if value.kinds == ASYNC:
                return Pending("coroutine", lambda _: force(value.pending, ASYNC, step=True))
            return force(value.pending, SYNC, step=True)
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
        if value.kind and not driving:
            return Pending(value.kind, lambda single: invoke(value, args, keywords, record, driving=True, step=single))
        if record and value.scope.path == entry and isinstance(node, FUNCTIONS) and substantive(node):
            targets.add(node)
            return None
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        params = parameters(node.args)
        scope = Scope(value.scope.path, value.scope, Locals(body, params), "function")
        scope.values.update(value.defaults)
        scope.values.update((param.arg, arg) for param, arg in zip([*node.args.posonlyargs, *node.args.args], args))
        scope.values.update((key, value) for key, value in keywords.items() if key in scope.values)
        active.add(node)
        if step:
            stepping.add(scope)
        try:
            if isinstance(node, ast.Lambda):
                return expression(node.body, scope, record)
            return statements(body, scope, record)[1]
        except Suspend:
            if not step:
                raise
            return None
        finally:
            stepping.discard(scope)
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

    def force(value, kinds, *, step=False):
        if not isinstance(value, Pending) or value.kind not in kinds or value.exhausted:
            return None
        if not step:
            value.exhausted = True
        return value.work(step)

    def comprehension(node, scope, record, first_value):
        inner = Scope(scope.path, scope.lexical_parent(), kind="comprehension")
        for index, item in enumerate(node.generators):
            if isinstance(item.iter, (ast.List, ast.Tuple, ast.Set)) and not item.iter.elts:
                return
            value = expression(item.iter, inner, record) if index else first_value
            force(value, ASYNC if item.is_async else SYNC)
            assign(item.target, None, inner)
            for test in item.ifs:
                expression(test, inner, record)
                if isinstance(test, ast.Constant) and not test.value:
                    return
        for field in ("elt", "key", "value"):
            if hasattr(node, field):
                expression(getattr(node, field), inner, record)

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
            builtin = callee[1] if isinstance(callee, tuple) and len(callee) == 2 and callee[0] == "builtins" else None
            if isinstance(node.func, ast.Name) and scope.get(node.func.id, MISSING) is MISSING:
                builtin = node.func.id
            if builtin in BUILTIN_CONSUMERS and args:
                force(args[0], SYNC, step=builtin in SHORT_CONSUMERS)
            elif builtin == "iter" and len(args) == 1:
                return args[0]
            elif builtin == "anext" and args:
                return Pending("coroutine", lambda _: force(args[0], ASYNC, step=True))
            if callee == ("asyncio", "run") and args:
                return force(args[0], AWAIT)
            if (args and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
                    and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)):
                force(args[0], SYNC)
            return invoke(callee, args, keywords, record)
        if isinstance(node, ast.Await):
            return force(expression(node.value, scope, record), AWAIT)
        if isinstance(node, ast.Starred):
            return force(expression(node.value, scope, record), SYNC)
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            value = expression(node.value, scope, record)
            if isinstance(node, ast.YieldFrom):
                force(value, SYNC, step=scope in stepping)
            if scope in stepping:
                raise Suspend
            return None
        if isinstance(node, ast.NamedExpr):
            value = expression(node.value, scope, record)
            containing = scope
            while containing.kind == "comprehension":
                containing = containing.parent
            assign(node.target, value, containing)
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
            first = node.generators[0]
            outer_iter = expression(first.iter, scope, record)
            if isinstance(node, ast.GeneratorExp):
                asynchronous = any(item.is_async for item in node.generators) or any(
                    isinstance(part, ast.Await) for part in ast.walk(node))
                return Pending("async_gen" if asynchronous else "sync_gen",
                               lambda _: comprehension(node, scope, record, outer_iter))
            return comprehension(node, scope, record, outer_iter)
        if node is not None:
            for child in ast.iter_child_nodes(node):
                expression(child, scope, record)
        return None

    def alternatives(scope, *branches):
        scopes = []
        while scope is not None:
            scopes.append(scope)
            scope = scope.parent
        before = [layer.values.copy() for layer in scopes]
        continuing = []
        for run in branches:
            for layer, state in zip(scopes, before):
                layer.values.clear()
                layer.values.update(state)
            if not run():
                continuing.append([layer.values.copy() for layer in scopes])
        for index, (layer, initial) in enumerate(zip(scopes, before)):
            layer.values.clear()
            states = [branch[index] for branch in continuing]
            for name in initial.keys() | {name for state in states for name in state}:
                bindings = [state.get(name) for state in states]
                layer.values[name] = bindings[0] if bindings and all(value == bindings[0] for value in bindings) else None
        return not continuing

    def statements(body, scope, record):
        def walk(nodes):
            return statements(nodes, scope, record)[0]

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name, ref in import_bindings(node, scope.path):
                    scope.bind(name, ref)
            elif isinstance(node, FUNCTIONS):
                value = routine(node, scope, record)
                known = all(isinstance(d, ast.Name) and d.id in ("staticmethod", "classmethod") for d in node.decorator_list)
                for deco in node.decorator_list:
                    expression(deco, scope, record)
                value.static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in node.decorator_list)
                scope.bind(node.name, value if known else None)
            elif isinstance(node, ast.ClassDef):
                for expr in [*node.bases, *[kw.value for kw in node.keywords], *node.decorator_list]:
                    expression(expr, scope, record)
                namespace = Scope(scope.path, scope.lexical_parent(), Locals(node.body), "class")
                statements(node.body, namespace, record)
                scope.bind(node.name, Class(namespace) if not node.decorator_list else None)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = expression(node.value, scope, record)
                if not isinstance(node, ast.AnnAssign) or node.value is not None:
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        assign(target, None if isinstance(node, ast.AugAssign) else value, scope)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    assign(target, None, scope)
            elif isinstance(node, ast.Return):
                return True, expression(node.value, scope, record)
            elif isinstance(node, ast.Raise):
                expression(node.exc, scope, record)
                expression(node.cause, scope, record)
                return True, None
            elif isinstance(node, ast.If):
                expression(node.test, scope, record)
                if isinstance(node.test, ast.Constant):
                    stopped, result = statements(node.body if node.test.value else node.orelse, scope, record)
                    if stopped:
                        return True, result
                elif alternatives(scope, lambda: walk(node.body), lambda: walk(node.orelse)):
                    return True, None
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(node, ast.While):
                    expression(node.test, scope, record)
                    if isinstance(node.test, ast.Constant) and not node.test.value:
                        stopped, result = statements(node.orelse, scope, record)
                        if stopped:
                            return True, result
                        continue
                else:
                    force(expression(node.iter, scope, record), ASYNC if isinstance(node, ast.AsyncFor) else SYNC)

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
                        scope.bind(item.name, None)
                    stopped = walk(item.body)
                    if item.name:
                        scope.bind(item.name, None)
                    return stopped

                stopped = alternatives(scope, lambda: walk(node.body) or walk(node.orelse),
                                       *(lambda item=item: handler(item) for item in node.handlers))
                if walk(node.finalbody) or stopped:
                    return True, None
            elif isinstance(node, ast.Match):
                expression(node.subject, scope, record)

                def arm(case):
                    for name in Locals([case.pattern]).bound:
                        scope.bind(name, None)
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
            force(invoke(value, [], {}, True), SYNC)
        elif isinstance(value, Class):
            instance = invoke(value, [], {}, True)
            for method in value.values:
                if not method.startswith("_"):
                    force(invoke(attribute(instance, method), [], {}, True), SYNC)
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
    def positions(nodes):
        return {(line(node), node.name) for node in nodes}

    def file_codes(path, selected):
        filename = str(Path(path).resolve())
        source = Path(path).read_bytes()
        return filename, {code for code in code_objects(compile(source, filename, "exec"))
                          if (code.co_firstlineno, code.co_name) in selected}

    def public_functions(body):
        for node in body:
            if isinstance(node, DEFINITIONS) and not node.name.startswith("_"):
                if isinstance(node, ast.ClassDef):
                    yield from public_functions(node.body)
                else:
                    yield node
            elif isinstance(node, ast.If):
                yield from public_functions(node.body)
                yield from public_functions(node.orelse)

    integration_tree = ast.parse(Path(integration).read_bytes(), integration)
    entry_tree = ast.parse(Path(entry).read_bytes(), entry)
    static_positions = positions(integration_targets(entry, integration))
    substantive_positions = positions(node for node in ast.walk(entry_tree) if isinstance(node, FUNCTIONS) and substantive(node))
    source_path, entry_codes = file_codes(entry, substantive_positions)
    static_codes = {code for code in entry_codes if (code.co_firstlineno, code.co_name) in static_positions}
    integration_path, public_codes = file_codes(integration, positions(public_functions(integration_tree.body)))
    test_path, test_position = str(Path(path).resolve()), (line(test), test.name)
    deferred_frames = {GeneratorType: "gi_frame", AsyncGeneratorType: "ag_frame", CoroutineType: "cr_frame"}
    # profile emits "return" on suspension too; a yield is not an exported return value.
    returns = {dis.opmap[name] for name in ("RETURN_VALUE", "RETURN_CONST") if name in dis.opmap}

    class Trace:
        covered = False
        passed = 0
        nonpass = False

        def __init__(self):
            self.returned = set()

        def ancestry(self, frame):
            public = False
            while frame is not None:
                code = frame.f_code
                if code.co_filename == test_path and (code.co_firstlineno, code.co_name) == test_position:
                    return True, public
                public |= (code.co_filename == integration_path and code in public_codes) or frame in self.returned
                frame = frame.f_back
            return False, False

        def profile(self, frame, event, arg):
            code = frame.f_code
            if (event == "return" and
                ((code.co_filename == integration_path and code in public_codes) or frame in self.returned)):
                member = deferred_frames.get(type(arg))
                if member and code.co_code[frame.f_lasti] in returns and self.ancestry(frame.f_back)[0]:
                    child = getattr(arg, member)
                    if child is not None:
                        self.returned.add(child)
            if event != "call" or code.co_filename != source_path or code not in entry_codes:
                return
            in_test, via_public = self.ancestry(frame.f_back)
            self.covered |= in_test and (via_public or frame in self.returned or code in static_codes)

        @pytest.hookimpl(wrapper=True, trylast=True)
        def pytest_runtest_call(self, item):
            sys.setprofile(self.profile)
            try:
                return (yield)
            finally:
                sys.setprofile(None)
                self.returned.clear()

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
