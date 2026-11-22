"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import builtins
import dis
from inspect import GEN_CREATED, GEN_SUSPENDED, getgeneratorstate
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
    def __init__(self, kind, cursor):
        self.kind = kind
        self.cursor = cursor


class Consumer:
    def __init__(self, pending, operation):
        self.pending, self.operation = pending, operation


class Closing:
    def __init__(self, value):
        self.value = value


MISSING = object()
UNKNOWN = object()
NONE = object()


class Raised(Exception):
    """被模拟代码的异常；不要让宿主生成器把 StopIteration 改写成 RuntimeError。"""

    def __init__(self, kind, *args):
        self.kind = kind
        self.args_model = Tuple(list(args))
        self.value = args[0] if args and kind is StopIteration else NONE


class Sequence:
    def __init__(self, values, *, uncertain_tail=False):
        self.values = values
        self.uncertain_tail = uncertain_tail


class Tuple(Sequence):
    pass


class Dictionary(Sequence):
    pass


class IndeterminateIteration(Exception):
    """未知键可能与已知键相等；不能凭空证明又取到了一项或已经耗尽。"""


def hash_key(value):
    if value is NONE or type(value) in (bool, int, float, complex, str, bytes):
        return value
    if isinstance(value, Tuple):
        members = tuple(map(hash_key, value.values))
        return UNKNOWN if any(member is UNKNOWN for member in members) else members
    if isinstance(value, Sequence):
        raise Raised(TypeError)
    return UNKNOWN


def unique_items(values, *, dictionary=False):
    seen = set()
    keys = []
    uncertain = False
    for value in values:
        key = hash_key(value)
        if key is UNKNOWN:
            uncertain = True
        elif key not in seen:
            seen.add(key)
            keys.append(value)
    if uncertain or not dictionary and len(keys) > 1:
        # 集合迭代顺序不是构造顺序；未知键也可能改变字典的迭代次序。
        keys = [UNKNOWN] * len(keys)
    return (Dictionary if dictionary else Sequence)(keys, uncertain_tail=uncertain)


SYNC = ("sync_gen", "iterator")
ASYNC = ("async_gen",)
AWAIT = ("coroutine",)
BUILTIN_CONSUMERS = {"list", "tuple", "set", "frozenset", "dict", "next", "sum", "any", "all", "min", "max", "sorted"}


def finish(cursor):
    while True:
        try:
            next(cursor)
        except StopIteration as done:
            return done.value


class Instance:
    def __init__(self, cls):
        self.cls = cls


def assign(node, value, scope):
    if isinstance(node, ast.Name):
        scope.bind(node.id, value)
    elif isinstance(node, (ast.Tuple, ast.List)):
        values = value.values if isinstance(value, Sequence) and len(value.values) == len(node.elts) else [None] * len(node.elts)
        for target, member in zip(node.elts, values):
            assign(target, member, scope)
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
    error_frames = [[]]

    def load(path):
        if path not in modules:
            tree = ast.parse(Path(path).read_bytes(), path)
            scope = modules[path] = Scope(path)
            finish(statements(tree.body, scope, False))
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
        if isinstance(value, Raised):
            if name == "value" and value.kind is StopIteration:
                return value.value
            if name == "args":
                return value.args_model
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
                if name == "__next__" or value.kind == "sync_gen":
                    return Consumer(value, "next")
            if value.kind == "sync_gen" and name == "close":
                return Consumer(value, "close")
            if value.kind in ASYNC and name in ("__anext__", "asend"):
                return Consumer(value, "anext")
        return None

    def invoke(value, args, keywords, record):
        if isinstance(value, Consumer):
            if value.operation == "anext":
                return Pending("coroutine", next_result(value.pending, ASYNC))
            if value.operation == "close":
                return close(value.pending)
            return take(value.pending, SYNC)
        value = resolve(value)
        if isinstance(value, Class):
            obj = Instance(value)
            for name in ("__new__", "__init__"):
                invoke([value.values.get(name), obj], args, keywords, record)
            return obj
        if isinstance(value, list):
            value, receiver = value
            args = [receiver, *args]
        if not isinstance(value, Routine):
            return None
        cursor = execute(value, args, keywords, record)
        return Pending(value.kind, cursor) if value.kind else finish(cursor)

    def execute(value, args, keywords, record):
        node = value.node
        if record and value.scope.path == entry and isinstance(node, FUNCTIONS) and substantive(node):
            targets.add(node)
            # 接线扫描只确认进入承接实现，不推断实现的返回值。
            if value.kind in (*SYNC, *ASYNC):
                yield UNKNOWN
            return None
        body = [node.body] if isinstance(node, ast.Lambda) else node.body
        params = parameters(node.args)
        scope = Scope(value.scope.path, value.scope, Locals(body, params), "function")
        scope.values.update(value.defaults)
        scope.values.update((param.arg, arg) for param, arg in zip([*node.args.posonlyargs, *node.args.args], args))
        scope.values.update((key, value) for key, value in keywords.items() if key in scope.values)
        cursor = expression(node.body, scope, record) if isinstance(node, ast.Lambda) else statements(body, scope, record)
        # 仅在运行时阻止递归；暂停的帧不会阻止同一例程的其他实例。
        injected, active_errors = None, []
        while node not in active:
            active.add(node)
            # 暂停帧保留自己的异常栈，但只有运行时才参与裸 raise 的查找。
            error_frames.append(active_errors)
            try:
                item = next(cursor) if injected is None else cursor.throw(injected)
                injected = None
            except StopIteration as done:
                if isinstance(node, ast.Lambda):
                    return done.value
                flow, result = done.value
                if value.kind == "sync_gen" and (flow is None or result is NONE):
                    return None
                return result if flow == "return" else NONE
            except Raised as error:
                if value.kind == "sync_gen" and error.kind is StopIteration:
                    raise Raised(RuntimeError) from None
                raise
            finally:
                error_frames.pop()
                active.remove(node)
            try:
                yield item
            except Raised as error:
                injected = error

    def routine(node, scope, record):
        value = Routine(node, scope.lexical_parent())
        positional = [*node.args.posonlyargs, *node.args.args]
        for arg, default in zip(positional[len(positional) - len(node.args.defaults):], node.args.defaults):
            value.defaults[arg.arg] = yield from expression(default, scope, record)
        for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
            if default is not None:
                value.defaults[arg.arg] = yield from expression(default, scope, record)
        return value

    NO_DEFAULT = object()

    def take(value, kinds, default=NO_DEFAULT):
        if not isinstance(value, Pending) or value.kind not in kinds or value.cursor.gi_running:
            return UNKNOWN if default is NO_DEFAULT else default
        try:
            return next(value.cursor)
        except StopIteration as stop:
            if default is NO_DEFAULT:
                raise Raised(StopIteration, *stop.args) from None
            return default

    def close(value):
        if not isinstance(value, Pending) or value.kind != "sync_gen":
            return NONE
        state = getgeneratorstate(value.cursor)
        if state == GEN_CREATED:
            value.cursor.close()
        elif state == GEN_SUSPENDED:
            # 仅显式关闭注入 GeneratorExit；宿主回收游标不是被分析程序的调用。
            try:
                value.cursor.throw(Raised(GeneratorExit))
            except StopIteration:
                pass
            except Raised as error:
                if error.kind is not GeneratorExit:
                    raise
            else:
                raise Raised(RuntimeError)
        return NONE

    def next_result(value, kinds):
        # 异步单步消费者要等到 await 才推进源游标。
        yield from ()
        return take(value, kinds, None)

    def force(value, kinds):
        if isinstance(value, Pending) and value.kind in kinds and not value.cursor.gi_running:
            return finish(value.cursor)

    def items(value, kinds):
        if isinstance(value, Pending):
            while (item := take(value, kinds, MISSING)) is not MISSING:
                yield item
        elif isinstance(value, Sequence):
            yield from value.values
            if value.uncertain_tail:
                raise IndeterminateIteration
        elif type(value) in (str, bytes):
            yield from value
        else:
            # 未知可迭代值保持有界的一次迭代近似。
            yield UNKNOWN

    def comprehension(node, scope, record, first_value):
        inner = Scope(scope.path, scope.lexical_parent(), kind="comprehension")

        def walk(index, value):
            item = node.generators[index]
            for member in items(value, ASYNC if item.is_async else SYNC):
                assign(item.target, member, inner)
                for test in item.ifs:
                    guard = yield from expression(test, inner, record)
                    if truth(guard) is False:
                        break
                else:
                    if index + 1 < len(node.generators):
                        source = yield from expression(node.generators[index + 1].iter, inner, record)
                        yield from walk(index + 1, source)
                    elif isinstance(node, ast.DictComp):
                        key = yield from expression(node.key, inner, record)
                        yield from expression(node.value, inner, record)
                        yield key
                    else:
                        yield (yield from expression(node.elt, inner, record))

        yield from walk(0, first_value)

    def truth(value):
        if value is NONE:
            return False
        if isinstance(value, Sequence):
            return True if value.values else None if value.uncertain_tail else False
        if type(value) in (bool, int, float, complex, str, bytes):
            return bool(value)
        return None

    def expression(node, scope, record):
        if node is None:
            return NONE
        if isinstance(node, ast.Constant):
            return node.value if node.value is not None else NONE
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = yield from expression(node.operand, scope, record)
            if type(value) in (bool, int, float, complex):
                return +value if isinstance(node.op, ast.UAdd) else -value
            return UNKNOWN
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            left = yield from expression(node.left, scope, record)
            right = yield from expression(node.right, scope, record)
            if type(left) in (bool, int, float, complex) and type(right) in (bool, int, float, complex):
                try:
                    return left + right if isinstance(node.op, ast.Add) else left - right
                except OverflowError:
                    raise Raised(OverflowError) from None
            return UNKNOWN
        if isinstance(node, ast.Name):
            value = scope.get(node.id, MISSING)
            return builtin_exception(node.id) if value is MISSING else value
        if isinstance(node, ast.Attribute):
            value = yield from expression(node.value, scope, record)
            return attribute(value, node.attr)
        if isinstance(node, ast.Lambda):
            return (yield from routine(node, scope, record))
        if isinstance(node, ast.Call):
            callee = yield from expression(node.func, scope, record)
            args, keywords = [], {}
            for arg in node.args:
                args.append((yield from expression(arg, scope, record)))
            for kw in node.keywords:
                keywords[kw.arg] = yield from expression(kw.value, scope, record)
            builtin = callee[1] if isinstance(callee, tuple) and len(callee) == 2 and callee[0] == "builtins" else None
            if isinstance(node.func, ast.Name) and scope.get(node.func.id, MISSING) is MISSING:
                builtin = node.func.id
            kind = exception_type(callee)
            if kind is not None:
                return Raised(kind, *args)
            if builtin in BUILTIN_CONSUMERS and args:
                if builtin == "next":
                    return take(args[0], SYNC, *args[1:2])
                if builtin in ("any", "all"):
                    for member in items(args[0], SYNC):
                        flag = truth(member)
                        if flag is None or flag == (builtin == "any"):
                            return flag
                    return builtin == "all"
                if builtin in ("list", "tuple", "sorted"):
                    return (Tuple if builtin == "tuple" else Sequence)(list(items(args[0], SYNC)))
                if builtin in ("set", "frozenset"):
                    return unique_items(items(args[0], SYNC))
                if builtin == "dict" and isinstance(args[0], Dictionary) and not keywords:
                    return args[0]
                force(args[0], SYNC)
            elif builtin in ("list", "tuple", "set", "frozenset", "dict") and not args:
                if builtin == "dict":
                    return unique_items(keywords, dictionary=True)
                return (Tuple if builtin == "tuple" else Sequence)([])
            elif builtin == "iter" and len(args) == 1:
                if isinstance(args[0], Sequence) or type(args[0]) in (str, bytes):
                    return Pending("iterator", (item for item in items(args[0], SYNC)))
                return args[0]
            elif builtin == "anext" and args:
                return Pending("coroutine", next_result(args[0], ASYNC))
            if callee == ("contextlib", "closing") and args:
                return Closing(args[0])
            if callee == ("asyncio", "run") and args:
                return force(args[0], AWAIT)
            if (args and isinstance(node.func, ast.Attribute) and node.func.attr == "join"
                    and isinstance(node.func.value, ast.Constant) and isinstance(node.func.value.value, str)):
                force(args[0], SYNC)
            return invoke(callee, args, keywords, record)
        if isinstance(node, ast.Await):
            return force((yield from expression(node.value, scope, record)), AWAIT)
        if isinstance(node, ast.Starred):
            return force((yield from expression(node.value, scope, record)), SYNC)
        if isinstance(node, ast.Yield):
            yield (yield from expression(node.value, scope, record))
            return UNKNOWN
        if isinstance(node, ast.YieldFrom):
            value = yield from expression(node.value, scope, record)
            if isinstance(value, Pending) and value.kind in SYNC and not value.cursor.gi_running:
                return (yield from value.cursor)
            yield from items(value, SYNC)
            return NONE if isinstance(value, Sequence) or type(value) in (str, bytes) else UNKNOWN
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            values = []
            for part in node.elts:
                if isinstance(part, ast.Starred):
                    values.extend(items((yield from expression(part.value, scope, record)), SYNC))
                else:
                    values.append((yield from expression(part, scope, record)))
            if isinstance(node, ast.Set):
                return unique_items(values)
            return (Tuple if isinstance(node, ast.Tuple) else Sequence)(values)
        if isinstance(node, ast.Dict):
            keys = []
            for key, expr in zip(node.keys, node.values):
                if key is not None:
                    keys.append((yield from expression(key, scope, record)))
                value = yield from expression(expr, scope, record)
                if key is None:
                    if not isinstance(value, Dictionary):
                        keys.append(UNKNOWN)
                    else:
                        keys.extend(value.values)
                        if value.uncertain_tail:
                            keys.append(UNKNOWN)
            return unique_items(keys, dictionary=True)
        if isinstance(node, ast.Subscript):
            value = yield from expression(node.value, scope, record)
            index = yield from expression(node.slice, scope, record)
            if isinstance(value, Tuple) and type(index) is int:
                try:
                    return value.values[index]
                except IndexError:
                    raise Raised(IndexError) from None
            return UNKNOWN
        if isinstance(node, ast.NamedExpr):
            value = yield from expression(node.value, scope, record)
            containing = scope
            while containing.kind == "comprehension":
                containing = containing.parent
            assign(node.target, value, containing)
            return value
        if isinstance(node, ast.IfExp):
            value = yield from expression(node.test, scope, record)
            flag = truth(value)
            if flag is not None:
                return (yield from expression(node.body if flag else node.orelse, scope, record))
            yield from expression(node.body, scope, record)
            yield from expression(node.orelse, scope, record)
            return None
        if isinstance(node, ast.BoolOp):
            value, uncertain = None, False
            for part in node.values:
                value = yield from expression(part, scope, record)
                flag = truth(value)
                uncertain |= flag is None
                if flag == isinstance(node.op, ast.Or):
                    break
            return UNKNOWN if uncertain else value
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            first = node.generators[0]
            outer_iter = yield from expression(first.iter, scope, record)
            cursor = comprehension(node, scope, record, outer_iter)
            if isinstance(node, ast.GeneratorExp):
                asynchronous = any(item.is_async for item in node.generators) or any(
                    isinstance(part, ast.Await) for part in ast.walk(node))
                return Pending("async_gen" if asynchronous else "sync_gen", cursor)
            if isinstance(node, (ast.SetComp, ast.DictComp)):
                return unique_items(cursor, dictionary=isinstance(node, ast.DictComp))
            return Sequence(list(cursor))
        if node is not None:
            for child in ast.iter_child_nodes(node):
                yield from expression(child, scope, record)
        return None

    def exception_type(value):
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "builtins":
            return builtin_exception(value[1])
        return value if isinstance(value, type) and issubclass(value, BaseException) else None

    def builtin_exception(name):
        value = getattr(builtins, name, None)
        return value if isinstance(value, type) and issubclass(value, BaseException) else None

    def catches(node, scope, kind, record):
        if node is None:
            return True
        if isinstance(node, ast.Tuple):
            for member in node.elts:
                if (yield from catches(member, scope, kind, record)):
                    return True
            return False
        handler_type = exception_type((yield from expression(node, scope, record)))
        return handler_type is not None and issubclass(kind, handler_type)

    def alternatives(scope, *branches):
        scopes = []
        while scope is not None:
            scopes.append(scope)
            scope = scope.parent
        before = [layer.values.copy() for layer in scopes]
        continuing, stopped = [], []
        for run in branches:
            for layer, state in zip(scopes, before):
                layer.values.clear()
                layer.values.update(state)
            try:
                flow, result = yield from run
            except Raised as error:
                if error.kind is GeneratorExit:
                    raise
                flow, result = "raise", error
            if flow is None:
                continuing.append([layer.values.copy() for layer in scopes])
            else:
                stopped.append((flow, result))
        for index, (layer, initial) in enumerate(zip(scopes, before)):
            layer.values.clear()
            states = [branch[index] for branch in continuing]
            for name in initial.keys() | {name for state in states for name in state}:
                bindings = [state.get(name) for state in states]
                layer.values[name] = bindings[0] if bindings and all(value == bindings[0] for value in bindings) else None
        if not continuing and stopped:
            flows = {flow for flow, _ in stopped}
            if len(flows) == 1:
                flow, value = stopped[0]
                result = value if all(result == value for _, result in stopped) else None
                if flow == "raise":
                    errors = [error for _, error in stopped]
                    if all(error is errors[0] for error in errors):
                        raise errors[0]
                    kind = errors[0].kind
                    if all(error.kind is kind for error in errors):
                        args = errors[0].args_model.values
                        if all(error.args_model.values == args for error in errors):
                            raise errors[0]
                        raise Raised(kind, UNKNOWN)
                    raise Raised(None)
                return flow, result
            # 所有分支都离开当前语句列表；只保留仍可能继续的外层路径。
            return ("continue" if "continue" in flows else "break" if "break" in flows else "return"), None
        return None, None

    def statements(body, scope, record):
        def walk(nodes):
            return statements(nodes, scope, record)

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name, ref in import_bindings(node, scope.path):
                    scope.bind(name, ref)
            elif isinstance(node, FUNCTIONS):
                value = yield from routine(node, scope, record)
                known = all(isinstance(d, ast.Name) and d.id in ("staticmethod", "classmethod") for d in node.decorator_list)
                for deco in node.decorator_list:
                    yield from expression(deco, scope, record)
                value.static = any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in node.decorator_list)
                scope.bind(node.name, value if known else None)
            elif isinstance(node, ast.ClassDef):
                for expr in [*node.bases, *[kw.value for kw in node.keywords], *node.decorator_list]:
                    yield from expression(expr, scope, record)
                namespace = Scope(scope.path, scope.lexical_parent(), Locals(node.body), "class")
                yield from statements(node.body, namespace, record)
                scope.bind(node.name, Class(namespace) if not node.decorator_list else None)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                value = yield from expression(node.value, scope, record)
                if not isinstance(node, ast.AnnAssign) or node.value is not None:
                    for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                        assign(target, None if isinstance(node, ast.AugAssign) else value, scope)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    assign(target, None, scope)
            elif isinstance(node, ast.Return):
                return "return", (yield from expression(node.value, scope, record))
            elif isinstance(node, ast.Raise):
                if node.exc is None:
                    for active_errors in reversed(error_frames):
                        if active_errors:
                            raise active_errors[-1]
                    raise Raised(RuntimeError)
                error = yield from expression(node.exc, scope, record)
                if node.cause is not None:
                    yield from expression(node.cause, scope, record)
                if isinstance(error, Raised):
                    raise error
                kind = exception_type(error)
                if kind is None and (error is NONE or type(error) in (bool, int, float, complex, str, bytes)):
                    kind = TypeError
                raise Raised(kind)
            elif isinstance(node, ast.If):
                flag = truth((yield from expression(node.test, scope, record)))
                branches = walk(node.body if flag else node.orelse) if flag is not None else alternatives(
                    scope, walk(node.body), walk(node.orelse))
                flow, result = yield from branches
                if flow:
                    return flow, result
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(node, ast.While):
                    flag = truth((yield from expression(node.test, scope, record)))
                    source = Sequence([]) if flag is False else None
                else:
                    source = yield from expression(node.iter, scope, record)
                    flag = True if isinstance(source, (Pending, Sequence)) else None

                def iteration(item):
                    if isinstance(node, (ast.For, ast.AsyncFor)):
                        assign(node.target, item, scope)
                    flow, result = yield from walk(node.body)
                    return (None, None) if flow == "continue" else (flow, result)

                if flag is None:
                    yield from alternatives(scope, iteration(UNKNOWN), walk([]))
                else:
                    for item in items(source, ASYNC if isinstance(node, ast.AsyncFor) else SYNC):
                        flow, result = yield from iteration(item)
                        if flow == "break":
                            break
                        if flow:
                            return flow, result
                    else:
                        flow, result = yield from walk(node.orelse)
                        if flow:
                            return flow, result
                    continue
                flow, result = yield from walk(node.orelse)
                if flow:
                    return flow, result
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                def enter(index):
                    if index == len(node.items):
                        return (yield from walk(node.body))
                    item = node.items[index]
                    value = yield from expression(item.context_expr, scope, record)
                    if item.optional_vars:
                        assign(item.optional_vars, value.value if isinstance(value, Closing) else None, scope)
                    try:
                        result = yield from enter(index + 1)
                    except Raised:
                        if isinstance(value, Closing):
                            close(value.value)
                        raise
                    if isinstance(value, Closing):
                        close(value.value)
                    return result

                flow, result = yield from enter(0)
                if flow:
                    return flow, result
            elif isinstance(node, (ast.Try, ast.TryStar)):
                def handler(item, error):
                    if item.name:
                        scope.bind(item.name, error)
                    active_errors = error_frames[-1]
                    active_errors.append(error)
                    try:
                        return (yield from walk(item.body))
                    finally:
                        active_errors.pop()
                        if item.name:
                            scope.bind(item.name, None)

                raised = None
                try:
                    try:
                        flow, result = yield from walk(node.body)
                    except Raised as error:
                        if error.kind is None and node.handlers:
                            flow, result = yield from alternatives(scope, *(handler(item, error) for item in node.handlers))
                        else:
                            for item in node.handlers:
                                if not isinstance(node, ast.TryStar) and (yield from catches(item.type, scope, error.kind, record)):
                                    flow, result = yield from handler(item, error)
                                    break
                            else:
                                raise
                    else:
                        if not flow:
                            flow, result = yield from walk(node.orelse)
                except Raised as error:
                    raised = error

                active_errors = error_frames[-1]
                if raised is not None:
                    active_errors.append(raised)
                try:
                    final, other = yield from walk(node.finalbody)
                finally:
                    if raised is not None:
                        active_errors.pop()
                if final:
                    return final, other
                if raised is not None:
                    raise raised
                if flow:
                    return flow, result
            elif isinstance(node, ast.Match):
                yield from expression(node.subject, scope, record)

                def arm(case):
                    for name in Locals([case.pattern]).bound:
                        scope.bind(name, None)
                    yield from expression(case.guard, scope, record)
                    return (yield from walk(case.body))

                yield from alternatives(scope, walk([]), *(arm(case) for case in node.cases))
            elif isinstance(node, ast.Break):
                return "break", None
            elif isinstance(node, ast.Continue):
                return "continue", None
            else:
                yield from expression(node, scope, record)
        return None, None

    for name, value in tuple(load(start).values.items()):
        # 单纯导入不构成生产接入；从公开定义的实际调用开始。
        if name.startswith("_"):
            continue
        def call(routine):
            try:
                return force(invoke(routine, [], {}, True), SYNC)
            except (Raised, IndeterminateIteration):
                return None

        if isinstance(value, Routine):
            call(value)
        elif isinstance(value, Class):
            try:
                instance = invoke(value, [], {}, True)
            except (Raised, IndeterminateIteration):
                continue
            for method in value.values:
                if not method.startswith("_"):
                    call(attribute(instance, method))
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
