"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import asyncio
import dis
import importlib
import inspect
import json
import os
import sys
from contextvars import ContextVar
from pathlib import Path
from types import AsyncGeneratorType, CodeType, CoroutineType, FunctionType, GeneratorType

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


def line(node):
    return min((d.lineno for d in node.decorator_list), default=node.lineno)


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


def sample(value, depth=5):
    """只复用登记测试的普通数据，不把测试对象、回调或其状态交给生产入口。"""
    kind = type(value)
    if kind in (type(None), bool, int, float, complex, str, bytes):
        return value
    if depth and kind is dict:
        return {sample(k, depth - 1): sample(v, depth - 1) for k, v in value.items()}
    if depth and kind in (tuple, list, set, frozenset):
        return kind(sample(v, depth - 1) for v in value)
    raise ValueError("not a plain parameter sample")


def arguments(fn, samples):
    args, kwargs = [], {}
    for param in inspect.signature(fn, follow_wrapped=False).parameters.values():
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            args.append(sample(samples[param.name]) if param.name in samples else
                        None if param.default is inspect.Parameter.empty else param.default)
        elif param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            if param.name in samples:
                kwargs[param.name] = sample(samples[param.name])
            elif param.default is inspect.Parameter.empty:
                kwargs[param.name] = None
    return args, kwargs


DEFERRED_FRAMES = {GeneratorType: "gi_frame", AsyncGeneratorType: "ag_frame", CoroutineType: "cr_frame"}
PROBE_STEPS = 1000
RELOAD_CODE = importlib.reload.__code__


def statements(body):
    """展开同一词法层的控制流块，不进入函数或类的内部作用域。"""
    for stmt in body:
        yield stmt
        if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            yield from statements(stmt.body)
            yield from statements(stmt.orelse)
        elif isinstance(stmt, (ast.Try, ast.TryStar)):
            yield from statements(stmt.body)
            for handler in stmt.handlers:
                yield from statements(handler.body)
            yield from statements(stmt.orelse)
            yield from statements(stmt.finalbody)
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            yield from statements(stmt.body)
        elif isinstance(stmt, ast.Match):
            for case in stmt.cases:
                yield from statements(case.body)


class Exports:
    def __init__(self, path, require_body=False):
        self.path = str(Path(path).resolve())
        raw = Path(path).read_bytes()
        top = list(statements(ast.parse(raw, path).body))
        self.literal_all = any(
            isinstance(stmt, (ast.Assign, ast.AnnAssign)) and
            any(isinstance(target, ast.Name) and target.id == "__all__" for target in
                (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])) and
            isinstance(stmt.value, (ast.List, ast.Tuple)) and
            all(isinstance(value, ast.Constant) and type(value.value) is str for value in stmt.value.elts)
            for stmt in top)
        functions = {(line(stmt), stmt.name) for stmt in top if isinstance(stmt, FUNCTIONS)
                     and (not require_body or substantive(stmt))}
        classes = {(line(stmt), stmt.name) for stmt in top if isinstance(stmt, ast.ClassDef)}
        methods = {(line(method), method.name) for cls in top if isinstance(cls, ast.ClassDef)
                   for method in statements(cls.body) if isinstance(method, FUNCTIONS) and
                   not method.name.startswith("_") and (not require_body or substantive(method))}
        codes = list(code_objects(compile(raw, self.path, "exec")))
        self.classes = {c for c in codes if (c.co_firstlineno, c.co_name) in classes}
        self.functions = {c for c in codes if (c.co_firstlineno, c.co_name) in functions}
        self.methods = {c for c in codes if (c.co_firstlineno, c.co_name) in methods}
        self.codes = self.functions | self.methods

    def members(self, namespace):
        explicit = self.literal_all and "__all__" in namespace
        if explicit:
            export_list = namespace["__all__"]
            if type(export_list) not in (tuple, list) or not all(type(name) is str for name in export_list):
                return
            names = export_list
        else:
            names = [name for name in namespace if not name.startswith("_")]
        for name in names:
            value = namespace.get(name)
            if type(value) is FunctionType and value.__code__ in self.functions:
                if explicit or not value.__code__.co_name.startswith("_"):
                    yield None, value
            elif isinstance(value, type) and value.__module__ == namespace.get("__name__"):
                if not explicit and value.__name__.startswith("_"):
                    continue
                for name, member in vars(value).items():
                    if name.startswith("_"):
                        continue
                    fn = member.__func__ if type(member) in (staticmethod, classmethod) else member
                    if type(fn) is FunctionType and fn.__code__ in self.methods:
                        yield value, member

    def contains(self, frame):
        code = frame.f_code
        if code.co_filename != self.path or code not in self.codes:
            return False
        return any((member.__func__ if type(member) in (staticmethod, classmethod) else member).__code__ is code
                   for _, member in self.members(frame.f_globals))

    def initialized(self, frame):
        while frame is not None:
            code = frame.f_code
            if code.co_filename == self.path and (code.co_name in ("<module>", "__init__", "__new__") or
                                                   code in self.classes):
                return False
            # reload() 的目标必须是这个模块；重载别的模块不改变本模块的公开边界。
            if code is RELOAD_CODE:
                target = frame.f_locals.get("module")
                if inspect.ismodule(target) and vars(target).get("__file__") == self.path:
                    return False
            frame = frame.f_back
        return True


class Invocation:
    """调用只能继承自己显式消费过的任务，任务继承上下文本身不提供证明。"""
    def __init__(self):
        self.owner = current_task()
        self.joined = {}

    def reachable(self):
        reached, todo = set(), [self.owner]
        while todo:
            task = todo.pop()
            if task not in reached:
                reached.add(task)
                todo.extend(self.joined.get(task, ()))
        return reached


active = ContextVar("at18-active-invocations", default=())
returns = {dis.opmap[name] for name in ("RETURN_VALUE", "RETURN_CONST") if name in dis.opmap}


def current_task():
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


def joined(scopes, waiter, tasks):
    if not scopes:
        return
    done = [task for task in tasks if isinstance(task, native_task) and task.done() and not task.cancelled()]
    for scope in scopes:
        scope.joined.setdefault(waiter, set()).update(done)


native_task = asyncio.Task


def observe_waits():
    """在原生等待完成的位置记因果边；不推进本来没有被调用者等待的任务。"""
    class TracedTask(native_task):
        def __await__(self):
            scopes, waiter = active.get(), current_task()
            try:
                return (yield from super().__await__())
            finally:
                joined(scopes, waiter, (self,))

        __iter__ = __await__

    # 保留原生 Future 接口和 gather 的调度、取消、异常语义。
    class TracedGather(asyncio.tasks._GatheringFuture):
        def __await__(self):
            scopes, waiter = active.get(), current_task()
            try:
                return (yield from super().__await__())
            finally:
                if self.done() and not self.cancelled():
                    joined(scopes, waiter, self._children)

        __iter__ = __await__

    native_wait = asyncio.wait

    async def traced_wait(*args, **kwargs):
        scopes, waiter = active.get(), current_task()
        done, pending = await native_wait(*args, **kwargs)
        joined(scopes, waiter, done)
        return done, pending

    class TracedGroup(asyncio.TaskGroup):
        def __init__(self):
            super().__init__()
            self.children = []

        def create_task(self, *args, **kwargs):
            task = super().create_task(*args, **kwargs)
            self.children.append(task)
            return task

        async def __aexit__(self, *args):
            scopes, waiter = active.get(), current_task()
            try:
                result = await super().__aexit__(*args)
                joined(scopes, waiter, self.children)
                return result
            finally:
                self.children.clear()

    native_run = asyncio.BaseEventLoop.run_until_complete
    cleanup = (asyncio.BaseEventLoop.shutdown_asyncgens.__code__,
               asyncio.BaseEventLoop.shutdown_default_executor.__code__)

    def traced_run(loop, future):
        scopes = active.get()
        if not scopes or (type(future) is CoroutineType and future.cr_code in cleanup):
            return native_run(loop, future)
        # asyncio.run 的主任务由 run_until_complete 显式驱动；循环清理不计。
        if not asyncio.isfuture(future):
            loop._check_closed()
            loop._check_running()
            future = asyncio.ensure_future(future, loop=loop)
        try:
            return native_run(loop, future)
        finally:
            joined(scopes, None, (future,))

    asyncio.Task = asyncio.tasks.Task = TracedTask
    asyncio.tasks._GatheringFuture = TracedGather
    asyncio.wait = asyncio.tasks.wait = traced_wait
    asyncio.TaskGroup = asyncio.taskgroups.TaskGroup = TracedGroup
    asyncio.BaseEventLoop.run_until_complete = traced_run


class Trace:
    def __init__(self, production, targets, *, test=None, probe=None):
        self.production, self.targets = production, targets
        self.test, self.probe = test, probe
        self.test_scope = None
        self.deferred = set()
        self.scopes = {}
        self.activations = {}
        self.hits = []

    def profile(self, frame, event, arg):
        code = frame.f_code
        if event == "return" and frame in self.activations:
            active.reset(self.activations.pop(frame))
            if self.scopes[frame] is not self.test_scope and code.co_code[frame.f_lasti] in returns:
                attr = DEFERRED_FRAMES.get(type(arg))
                if attr and (child := getattr(arg, attr)) is not None:
                    self.deferred.add(child)
            return
        if event != "call":
            return
        scopes = active.get()
        scope = None
        if self.test and (code.co_filename, code.co_firstlineno, code.co_name) == self.test:
            if frame not in self.scopes:
                self.scopes[frame] = Invocation()
            scope = self.test_scope = self.scopes[frame]
        elif ((self.probe is not None and (frame in self.deferred or
                frame.f_back is self.probe and self.production.contains(frame))) or
                (self.test_scope in scopes and (frame in self.deferred or self.production.contains(frame)))):
            if not self.production.initialized(frame):
                return
            if frame not in self.scopes:
                self.scopes[frame] = Invocation()
            scope = self.scopes[frame]
        if scope is not None:
            scopes = (*scopes, scope)
            self.activations[frame] = active.set(scopes)
        if scopes and self.targets.contains(frame):
            # 只排除入口外层的初始化；正常公开调用自身可以再构造对象。
            if any(scope is not self.test_scope for scope in scopes) or self.production.initialized(frame):
                self.hits.append((code, current_task(), scopes, self.samples(frame) if self.test else {}))

    @staticmethod
    def samples(frame):
        code = frame.f_code
        args = {}
        for name in code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]:
            try:
                args[name] = sample(frame.f_locals[name])
            except (KeyError, ValueError):
                pass
        return args

    def accepted(self):
        reach = {}
        for code, task, scopes, samples in self.hits:
            for scope in scopes:
                if scope not in reach:
                    reach[scope] = scope.reachable()
            if self.test_scope and task not in reach.get(self.test_scope, ()):
                continue
            via_public = any(scope is not self.test_scope and task in reach[scope] for scope in scopes)
            yield code, samples, via_public

    def covers(self, expected):
        return any(via_public and code in expected for code, _, via_public in self.accepted())


def public_probe(integration, production, targets, test_entered_codes, samples):
    # pytest 可能已加载或修改受验模块；用同一冻结副本重新导入，且导入不记覆盖。
    root = Path.cwd().resolve()
    for name, loaded in list(sys.modules.items()):
        filename = vars(loaded).get("__file__") if inspect.ismodule(loaded) else None
        if isinstance(filename, str) and Path(filename).resolve().is_relative_to(root):
            sys.modules.pop(name, None)
    try:
        loaded = importlib.import_module(module(integration))
        if Path(loaded.__file__).resolve() != Path(production.path):
            return False
    except (Exception, SystemExit):
        return False

    instances = {}
    for owner, member in production.members(vars(loaded)):
        try:
            if owner is None:
                fn = member
            elif type(member) in (staticmethod, classmethod):
                fn = member.__get__(None, owner)
            else:
                if owner not in instances:
                    instances[owner] = None  # 构造器异常也只试一次。
                    args, kwargs = arguments(owner, samples)
                    instances[owner] = owner(*args, **kwargs)
                if instances[owner] is None:
                    continue
                fn = member.__get__(instances[owner], owner)
            args, kwargs = arguments(fn, samples)
        except (Exception, SystemExit):
            continue

        trace = Trace(production, targets, probe=sys._getframe())
        result = None

        async def consume_async_generator(generator):
            try:
                for _ in range(PROBE_STEPS):
                    if trace.covers(test_entered_codes):
                        break
                    try:
                        await anext(generator)
                    except StopAsyncIteration:
                        break
            finally:
                # asyncio.run 关闭事件循环时的隐式 aclose 不属于公开消费。
                sys.setprofile(None)

        try:
            sys.setprofile(trace.profile)
            result = fn(*args, **kwargs)
            attr = DEFERRED_FRAMES.get(type(result))
            if attr and not trace.covers(test_entered_codes):
                # 只驱动公开返回值；不查找或推进函数内部未返回的生成器。
                trace.deferred.add(getattr(result, attr))
                if type(result) is CoroutineType:
                    asyncio.run(result)
                elif type(result) is AsyncGeneratorType:
                    asyncio.run(consume_async_generator(result))
                else:
                    for _ in range(PROBE_STEPS):
                        if trace.covers(test_entered_codes):
                            break
                        next(result)
        except (Exception, SystemExit):
            # 只承认异常前实际进入的导出；不因一次探针异常停止其他公开入口。
            pass
        finally:
            sys.setprofile(None)
            result = None
        if trace.covers(test_entered_codes):
            return True
    return False


def proves(doc, scratch):
    entry, integration, path, selector = (doc[k] for k in ("entry", "integration", "checkPath", "selector"))
    test = selected_test(path, selector)
    if test is None:
        return False
    production, targets = Exports(integration), Exports(entry, require_body=True)
    position = str(Path(path).resolve()), line(test), test.name

    class Registration:
        covered, passed, nonpass = False, 0, False

        def __init__(self):
            self.entered = set()
            self.samples = {}

        @pytest.hookimpl(wrapper=True, trylast=True)
        def pytest_runtest_call(self, item):
            trace = Trace(production, targets, test=position)
            sys.setprofile(trace.profile)
            try:
                return (yield)
            finally:
                sys.setprofile(None)
                for code, samples, via_public in trace.accepted():
                    self.entered.add(code)
                    self.covered |= via_public
                    for key, value in samples.items():
                        self.samples.setdefault(key, value)

        def pytest_runtest_logreport(self, report):
            self.nonpass |= not report.passed or hasattr(report, "wasxfail")
            if report.when == "call" and report.passed:
                self.passed += 1

    registration = Registration()
    observe_waits()
    sys.path.insert(0, str(Path.cwd()))
    result = pytest.main(["-p", "no:cacheprovider", "-p", "no:terminal", "--basetemp", scratch + "/pytest",
                          path + "::" + selector], plugins=[registration])
    return (result == pytest.ExitCode.OK and not registration.nonpass and registration.passed == doc["count"] and
            (registration.covered or bool(registration.entered) and
             public_probe(integration, production, targets, registration.entered, registration.samples)))


if __name__ == "__main__":
    # 受验源码可以打印日志；它的 stdout 不属于驱动器的回执。
    with open(os.devnull, "wb") as sink:
        output = os.dup(1)
        try:
            os.dup2(sink.fileno(), 1)
            if not proves(json.load(sys.stdin), sys.argv[1]):
                sys.exit(1)
            os.write(output, b"AT18_PYTHON_COVERED\n")
        finally:
            os.close(output)
