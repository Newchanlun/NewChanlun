"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import asyncio
import builtins
import dis
import gc
import importlib
import inspect
import json
import os
import sys
from collections import namedtuple
from contextvars import ContextVar
from pathlib import Path
from types import AsyncGeneratorType, CodeType, CoroutineType, FunctionType, GeneratorType, MethodType
from weakref import WeakKeyDictionary

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


def arguments(fn, samples, variadic=False):
    args, kwargs = [], {}
    params = inspect.signature(fn, follow_wrapped=False).parameters
    for param in params.values():
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            args.append(sample(samples[param.name]) if param.name in samples else
                        None if param.default is inspect.Parameter.empty else param.default)
        elif param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            if param.name in samples:
                kwargs[param.name] = sample(samples[param.name])
            elif param.default is inspect.Parameter.empty:
                kwargs[param.name] = None
    if variadic:
        # 无显式签名的生产包装器只能使用已经观察到的普通参数。
        remaining = {k: sample(v) for k, v in samples.items() if k not in params}
        kinds = {param.kind for param in params.values()}
        if inspect.Parameter.VAR_KEYWORD in kinds:
            kwargs.update(remaining)
        elif inspect.Parameter.VAR_POSITIONAL in kinds and all(
                p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.VAR_POSITIONAL) for p in params.values()):
            args.extend(remaining.values())
    return args, kwargs


DEFERRED_FRAMES = {GeneratorType: "gi_frame", AsyncGeneratorType: "ag_frame", CoroutineType: "cr_frame"}
PROBE_STEPS = 1000
RELOAD_CODE = importlib.reload.__code__


def exported_bindings(name, path):
    # Git 路径转成语句前须是限定模块名，不允许路径文字成为 Python 语法。
    if not all(part.isidentifier() for part in name.split(".")):
        return None, {}
    try:
        loaded = importlib.import_module(name)
        if Path(loaded.__file__).resolve() != Path(path):
            return None, {}
        namespace = {}
        exec(f"from {name} import *", namespace)
        namespace.pop("__builtins__", None)
        return vars(loaded), namespace
    except BaseException:
        # import * 可能已写入前缀；整张清单失败时不得使用其中任何绑定。
        return None, {}


def underlying(member):
    return member.__func__ if type(member) in (MethodType, staticmethod, classmethod) else member


class ClassOrigins:
    """类的归属取自实际执行的类体，不信任可改写的 __module__/__qualname__。"""
    def __init__(self, *modules):
        self.modules = {m.path: m.classes for m in modules}
        self.classes = {}
        self.native = builtins.__build_class__

    def __enter__(self):
        builtins.__build_class__ = self.build
        return self

    def __exit__(self, *error):
        builtins.__build_class__ = self.native

    def build(self, body, name, /, *bases, **kwargs):
        local = (type(body) is FunctionType and
                 body.__code__ in self.modules.get(body.__code__.co_filename, ()))
        # 自定义元类可能原样返回已存在的外来类；只记录此次类语句新建的对象。
        previous = ()
        if local and (kwargs.get("metaclass", type) is not type or any(type(base) is not type for base in bases)):
            previous = {id(cls): cls for cls in gc.get_objects() if is_class(cls)}
        cls = self.native(body, name, *bases, **kwargs)
        if local and is_class(cls) and gc.is_tracked(cls) and id(cls) not in previous:
            self.classes[id(cls)] = (cls, body)
        return cls


MISSING = object()
FRAME_OWNER = getattr(type(sys._getframe()), "f_generator", None)
DEFERRED_FLAGS = inspect.CO_GENERATOR | inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR


def frame_function(frame, owner=None):
    # CPython 3.12–3.14 的 _PyFrame_Traverse 先访问函数对象，紧接实际 code，
    # 然后才访问局部变量/值栈。普通帧须在退栈后读取；暂停帧由生成器等持有。
    referents = gc.get_referents(owner if owner is not None else frame)
    for previous, obj in zip(referents, referents[1:]):
        if obj is frame.f_code:
            return previous if type(previous) is FunctionType else None
    return None


def deferred_owner(frame):
    if FRAME_OWNER is not None:
        return FRAME_OWNER.__get__(frame)
    # 3.12/3.13 尚未暴露 f_generator；只在候选暂停帧首次进入时反查原生所有者。
    return next((obj for obj in gc.get_referrers(frame)
                 if (attr := DEFERRED_FRAMES.get(type(obj))) and getattr(obj, attr) is frame), None)


def receiver_at_entry(frame):
    code = frame.f_code
    if code.co_argcount:
        return frame.f_locals.get(code.co_varnames[0], MISSING)
    if code.co_flags & inspect.CO_VARARGS:
        args = frame.f_locals.get(code.co_varnames[code.co_kwonlyargcount], ())
        if args:
            return args[0]
    return MISSING


def inherits(actual, owner):
    # 用真实 MRO，不执行受验对象的 __class__ 或元类的 __instancecheck__。
    return any(base is owner for base in type.__getattribute__(actual, "__mro__"))


def is_class(obj):
    return inherits(type(obj), type)


def class_members(cls):
    return type.__dict__["__dict__"].__get__(cls).items()


class Binding:
    def __init__(self, key, member, signature, owner=None, *, wrapper, variadic):
        self.key, self.member, self.signature, self.owner = key, member, signature, owner
        self.function = underlying(member)
        self.wrapper, self.variadic = wrapper, variadic

    @property
    def has_receiver(self):
        return type(self.member) is MethodType or self.owner is not None and type(self.member) is not staticmethod

    def matches_receiver(self, receiver):
        kind = type(self.member)
        if kind is MethodType:
            return receiver is self.member.__self__
        if kind is staticmethod or self.owner is None:
            return True
        if kind is classmethod:
            return is_class(receiver) and inherits(receiver, self.owner)
        return receiver is not MISSING and inherits(type(receiver), self.owner)

    def callable(self, instances, samples):
        if self.owner is None:
            return self.member
        if type(self.member) in (staticmethod, classmethod):
            return self.member.__get__(None, self.owner)
        key = id(self.owner)
        if key not in instances:
            instances[key] = None  # 构造器异常也只试一次。
            args, kwargs = arguments(self.owner, samples)
            instances[key] = self.owner(*args, **kwargs)
        if instances[key] is not None:
            return self.member.__get__(instances[key], self.owner)

    def arguments(self, fn, named, shapes):
        signature = self.signature
        if type(fn) is MethodType:
            signature = MethodType(signature, fn.__self__)
        fallback = arguments(signature, named, self.variadic)
        choices = []
        params = inspect.signature(signature, follow_wrapped=False)
        if self.variadic:
            for args, kwargs in shapes:
                try:
                    params.bind(*args, **kwargs)
                except TypeError:
                    continue
                if (args, kwargs) not in choices:
                    choices.append((tuple(sample(v) for v in args), {k: sample(v) for k, v in kwargs.items()}))
        args, kwargs = fallback
        if (tuple(args), kwargs) not in choices:
            choices.append((tuple(args), kwargs))
        return choices


builtin_callables = {id(obj) for obj in vars(builtins).values() if callable(obj)}


def scope_nodes(node):
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (*FUNCTIONS, ast.Lambda, ast.ClassDef)):
            yield child
            yield from scope_nodes(child)


def span(node):
    return node.lineno, node.end_lineno, node.col_offset, node.end_col_offset


ForwardSite = namedtuple("ForwardSite", "call consumes schedules spreads capture")
ForwardPlan = namedtuple("ForwardPlan", "sites exits all_exits discarded")
NO_FORWARDING = ForwardPlan((), (), False, False)


def forwarding(node):
    """先从实际返回/产出值反查调用，不把同一函数体中的其它调用算入透传。"""
    params = node.args
    names = {p.arg for p in (*params.posonlyargs, *params.args, *params.kwonlyargs)}
    vararg = params.vararg and params.vararg.arg
    kwarg = params.kwarg and params.kwarg.arg
    scope = tuple(scope_nodes(node))
    stores, assigned, iterations = {}, {}, {}
    for stmt in scope:
        if isinstance(stmt, ast.Name) and isinstance(stmt.ctx, (ast.Store, ast.Del)):
            stores[stmt.id] = stores.get(stmt.id, 0) + 1
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,):
                if isinstance(target, ast.Name) and stmt.value is not None:
                    assigned[target.id] = stmt.value
        if isinstance(stmt, (ast.For, ast.AsyncFor)) and isinstance(stmt.target, ast.Name):
            iterations[stmt.target.id] = stmt

    def spreads(call):
        return (any(isinstance(a, ast.Starred) and isinstance(a.value, ast.Name) and a.value.id == vararg
                    for a in call.args) or
                any(k.arg is None and isinstance(k.value, ast.Name) and k.value.id == kwarg
                    for k in call.keywords))

    def origin(value, bridges=(), scheduled=()):
        if isinstance(value, ast.Name) and stores.get(value.id) == 1 and value.id in assigned:
            earlier = assigned[value.id]
            if (earlier.lineno, earlier.col_offset) < (value.lineno, value.col_offset):
                return origin(earlier, bridges, scheduled)
        if isinstance(value, (ast.Await, ast.YieldFrom)):
            return origin(value.value, (*bridges, span(value)), scheduled)
        if not isinstance(value, ast.Call):
            return None
        callee = value.func
        label = callee.attr if isinstance(callee, ast.Attribute) else callee.id if isinstance(callee, ast.Name) else None
        if label in ("create_task", "ensure_future") and value.args:
            return origin(value.args[0], bridges, (*scheduled, span(value)))
        star = spreads(value)
        args = [*value.args, *(k.value for k in value.keywords)]
        if not star and not all(isinstance(a, ast.Name) and a.id in names for a in args):
            return None
        while isinstance(callee, (ast.Attribute, ast.Subscript)):
            callee = callee.value
        capture = (callee.id, callee is not value.func) if isinstance(callee, ast.Name) else None
        return ForwardSite(span(value), bridges, scheduled, star, capture)

    sites, exits, returns_ = set(), set(), 0
    if isinstance(node, ast.Lambda):
        if site := origin(node.body):
            sites.add(site)
            exits.add(span(node.body))
        values = [node.body]
    else:
        values = []
        for stmt in scope:
            if isinstance(stmt, ast.Return):
                returns_ += 1
                values.append(stmt.value)
                if site := origin(stmt.value):
                    sites.add(site)
                    exits.add(span(stmt))
            elif isinstance(stmt, ast.YieldFrom):
                values.append(stmt)
                if site := origin(stmt):
                    sites.add(site)
            elif isinstance(stmt, ast.Yield):
                values.append(stmt.value)
                if site := origin(stmt.value):
                    sites.add(site)
                elif isinstance(stmt.value, ast.Name) and stores.get(stmt.value.id) == 1:
                    loop = iterations.get(stmt.value.id)
                    if loop and any(stmt is n for s in loop.body for n in (s, *scope_nodes(s))):
                        consumption = span(loop if isinstance(loop, ast.AsyncFor) else loop.iter)
                        if site := origin(loop.iter, (consumption,)):
                            sites.add(site)

    def transformed(value, seen=()):
        if value is None:
            return False
        for item in (value, *scope_nodes(value)):
            if isinstance(item, ast.Call) and spreads(item):
                return True
            if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load) and item.id not in seen:
                loop = iterations.get(item.id)
                earlier = assigned.get(item.id, loop.iter if loop else None)
                if transformed(earlier, (*seen, item.id)):
                    return True
        return False

    # 已丢弃的星号调用（例如未等待任务）不构成有证据的叶；若返回值
    # 确实由调用结果变换而来，则计算发生在本地，不是透传。
    discarded = (not any(site.spreads for site in sites) and any(isinstance(n, ast.Call) and spreads(n) for n in scope)
                 and not any(transformed(v) for v in values))
    # CPython 可把 try:return 的 RETURN_VALUE 标在收尾语句上。只有所有
    # 显式返回都已关联透传时，才允许从该种实际返回转交延迟结果。
    return ForwardPlan(sites, exits, bool(returns_ and returns_ == len(exits)), discarded)


def captures(fn, name):
    code = fn.__code__
    if name in code.co_freevars:
        try:
            return fn.__closure__[code.co_freevars.index(name)].cell_contents
        except ValueError:
            return MISSING
    defaults = fn.__defaults__ or ()
    positional = code.co_varnames[:code.co_argcount]
    if defaults and name in positional[-len(defaults):]:
        return defaults[positional[-len(defaults):].index(name)]
    return (fn.__kwdefaults__ or {}).get(name, MISSING)


class Exports:
    def __init__(self, path, require_body=False):
        self.path, self.module = str(Path(path).resolve()), module(path)
        raw = Path(path).read_bytes()
        declarations = list(ast.walk(ast.parse(raw, path)))
        functions = {}
        for node in declarations:
            if isinstance(node, ast.Lambda):
                functions.setdefault((node.lineno, "<lambda>"), []).append(node)
            elif isinstance(node, FUNCTIONS) and (not require_body or substantive(node)):
                functions.setdefault((line(node), node.name), []).append(node)
        classes = {(line(node), node.name) for node in declarations if isinstance(node, ast.ClassDef)}
        codes = list(code_objects(compile(raw, self.path, "exec")))
        self.definitions = {c for c in codes if (c.co_firstlineno, c.co_name) in functions}
        self.classes = {c for c in codes if (c.co_firstlineno, c.co_name) in classes}
        self.forwarding = {}
        for code in self.definitions:
            candidates = functions[code.co_firstlineno, code.co_name]
            if len(candidates) != 1 and code.co_name == "<lambda>":
                # 同行的多个 lambda 用实际表达式位置区分。
                positions = set(code.co_positions())
                candidates = [n for n in candidates if
                              (n.body.lineno, n.body.end_lineno, n.body.col_offset, n.body.end_col_offset) in positions]
            if len(candidates) == 1:
                self.forwarding[code] = forwarding(candidates[0])

    def owns_frame(self, frame):
        return (frame.f_globals is self.globals and frame.f_code.co_filename == self.path and
                frame.f_code in self.definitions)

    def wrapper(self, fn):
        if "__wrapped__" in vars(fn):
            return True
        plan = self.forwarding.get(fn.__code__, NO_FORWARDING)
        if plan.discarded:
            return True
        for site in plan.sites:
            if site.spreads:
                return True
            if site.capture is None:
                continue
            name, selector = site.capture
            value = captures(fn, name)
            if value is not MISSING:
                if (selector or callable(value)) and id(value) not in builtin_callables:
                    return True
            # __call__ 可只是中转；普通绑定方法的接收者不等于闭包捕获。
            elif selector and fn.__code__.co_name == "__call__" and fn.__code__.co_varnames[:1] == (name,):
                return True
        return False

    def owns_fn(self, fn):
        return (type(fn) is FunctionType and fn.__globals__ is self.globals and
                fn.__code__.co_filename == self.path and fn.__code__ in self.definitions)

    def class_body(self, cls):
        record = self.origins.classes.get(id(cls))
        if record is not None:
            _, body = record
            if body.__globals__ is self.globals and body.__code__ in self.classes:
                return body.__code__

    def owns_receiver(self, receiver):
        cls = receiver if is_class(receiver) else type(receiver)
        return self.class_body(cls) is not None

    def signature(self, fn):
        # 显式 __wrapped__ 链须全部归属冻结文件；链仅提供调用签名，不能证明运行。
        seen = set()
        while self.owns_fn(fn) and fn not in seen:
            seen.add(fn)
            explicit = vars(fn).get("__wrapped__", MISSING)
            if explicit is MISSING:
                return fn
            fn = explicit
        return None

    def load(self, origins):
        self.origins = origins
        self.globals, bindings = exported_bindings(self.module, self.path)
        self.members = tuple(self.local_members(bindings))
        self.by_code = {}
        for binding in self.members:
            self.by_code.setdefault(id(binding.function.__code__), []).append(binding)

    def binding(self, key, member, owner=None):
        fn = underlying(member)
        signature = self.signature(fn)
        if signature is not None:
            return Binding(key, member, signature, owner, wrapper=self.wrapper(fn),
                           variadic=bool(signature.__code__.co_flags & (inspect.CO_VARARGS | inspect.CO_VARKEYWORDS)))

    def local_members(self, bindings):
        for export_name, value in bindings.items():
            if type(value) is FunctionType or type(value) is MethodType and self.owns_receiver(value.__self__):
                if (binding := self.binding(("module", export_name), value)) is not None:
                    yield binding
            elif is_class(value) and self.class_body(value) is not None:
                for name, member in class_members(value):
                    if not name.startswith("_") and type(member) in (FunctionType, staticmethod, classmethod):
                        if (binding := self.binding(("class", export_name, name), member, value)) is not None:
                            yield binding

    def candidates(self, frame):
        if frame.f_globals is self.globals:
            return self.by_code.get(id(frame.f_code), ())
        return ()

    def initialized(self, frame, *, constructors=True):
        while frame is not None:
            code = frame.f_code
            if code.co_filename == self.path and (code.co_name == "<module>" or code in self.classes or
                                                   constructors and code.co_name in ("__init__", "__new__")):
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
    def __init__(self, call=None, parent=None, *, wrapper=False):
        self.call, self.parent = call, parent
        self.origin = parent.origin if parent is not None else self
        self.wrapper = wrapper
        self.returned = set()
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


native_task = asyncio.Task
native_future = asyncio.Future
children_of = WeakKeyDictionary()


def joined(scopes, waiter, futures):
    if not scopes:
        return
    # 只在显式等待完成时展开；之后自行完成的任务不得补入已消费集合。
    done, seen, pending = set(), set(), list(futures)
    while pending:
        future = pending.pop()
        if not isinstance(future, native_future) or future in seen or not future.done() or future.cancelled():
            continue
        seen.add(future)
        if isinstance(future, native_task):
            done.add(future)
        pending.extend(children_of.get(future, ()))
    for scope in scopes:
        scope.joined.setdefault(waiter, set()).update(done)


# wait_for 的部分分支以及同步 as_completed 项通过 result() 取结果，不走 __await__。
wait_result_codes = {asyncio.wait_for.__code__}
completion_iterator = getattr(asyncio.tasks, "_AsCompletedIterator", None)
if completion_iterator is not None:
    wait_result_codes.add(completion_iterator._wait_for_one.__code__)
else:
    wait_result_codes.update(code for code in code_objects(asyncio.as_completed.__code__)
                             if code.co_name == "_wait_for_one")


def observe_waits():
    """在原生等待完成的位置记因果边；不推进本来没有被调用者等待的任务。"""
    class ObservedAwait:
        def __await__(self):
            scopes, waiter = active.get(), current_task()
            try:
                return (yield from super().__await__())
            except asyncio.CancelledError:
                scopes = ()
                raise
            finally:
                joined(scopes, waiter, (self,))

        __iter__ = __await__

    class TracedTask(ObservedAwait, native_task):
        pass

    class TracedFuture(ObservedAwait, native_future):
        pass

    # 保留原生 Future 接口和 gather 的调度、取消、异常语义。
    class TracedGather(ObservedAwait, asyncio.tasks._GatheringFuture):
        def __init__(self, children, *, loop):
            super().__init__(children, loop=loop)
            children_of[self] = tuple(children)

        def set_exception(self, exception):
            super().set_exception(exception)
            # gather 可提前抛错；此时未完成的兄弟任务不属于已等待的批次。
            children_of[self] = tuple(child for child in children_of[self] if child.done())

    native_shield = asyncio.shield

    def traced_shield(arg):
        inner = asyncio.ensure_future(arg)
        outer = native_shield(inner)
        if outer is not inner:
            children_of[outer] = (inner,)
        return outer

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
    asyncio.BaseEventLoop.create_future = lambda loop: TracedFuture(loop=loop)
    asyncio.tasks._GatheringFuture = TracedGather
    asyncio.shield = asyncio.tasks.shield = traced_shield
    asyncio.wait = asyncio.tasks.wait = traced_wait
    asyncio.TaskGroup = asyncio.taskgroups.TaskGroup = TracedGroup
    asyncio.BaseEventLoop.run_until_complete = traced_run


class Call:
    """候选 code 仅用于分流，实际计入的键必须有精确的函数和接收者。"""
    def __init__(self, frame, bindings, receiver, function=None):
        self.frame, self.function, self.receiver = frame, function, receiver
        self.bindings = tuple(b for b in bindings if b.matches_receiver(receiver))
        self.matched = None

    def actual(self):
        if self.function is None:
            self.function = frame_function(self.frame)
        return self.function

    def matches(self):
        if self.matched is None and self.bindings:
            fn = self.actual()
            if fn is not None:
                self.matched = tuple(b for b in self.bindings if b.function is fn)
        return self.matched or ()


def public(scope):
    while scope.call is None:
        if scope.parent is None:
            return True  # 独立探针显式驱动已返回的生成器/协程。
        scope = scope.parent
    return bool(scope.call.matches())


task_creators = {asyncio.create_task.__code__: "coro", asyncio.ensure_future.__code__: "coro_or_future"}


class ForwardCall:
    def __init__(self, call, task, scopes, samples, bound):
        self.call, self.task, self.scopes = call, task, scopes
        self.samples, self.bound = samples, bound
        self.children = []


class Trace:
    def __init__(self, production, targets, *, test=None, probe=None):
        self.production, self.targets = production, targets
        self.test, self.probe = test, probe
        self.test_scope = None
        self.deferred = {}
        self.suspended_calls = {}
        self.scopes = {}
        self.wrappers = {}
        self.forward_calls = {}
        self.forward_results = {}
        self.foreign_calls = set()
        self.positions = {}
        self.resumed = {}
        self.activations = {}
        self.hits = []

    def call(self, frame, bindings):
        code = frame.f_code
        if not code.co_flags & DEFERRED_FLAGS:
            return Call(frame, bindings, receiver_at_entry(frame))
        if frame not in self.suspended_calls:
            owner = deferred_owner(frame)
            bytecode = code.co_code
            start = bytecode[frame.f_lasti:frame.f_lasti + 2] == bytes((dis.opmap["RESUME"], 0))
            # 恢复时局部变量可已改写；不知道首入的接收者时，不证实绑定方法。
            self.suspended_calls[frame] = (receiver_at_entry(frame) if start else MISSING,
                                           frame_function(frame, owner) if owner is not None else None)
        receiver, fn = self.suspended_calls[frame]
        return Call(frame, bindings, receiver, fn)

    def position(self, frame):
        code = frame.f_code
        if code not in self.positions:
            self.positions[code] = tuple(code.co_positions())
        return self.positions[code][frame.f_lasti // 2] if frame.f_lasti >= 0 else None

    def forwarding_parent(self, frame):
        if not (parent := self.forward_calls.get(frame.f_back)):
            return None
        caller = frame.f_back
        sites = self.targets.forwarding.get(caller.f_code, NO_FORWARDING).sites
        if sites:
            # 匹配字节码位置而非行号或范围相交：同一行、甚至实参中
            # 的日志调用各有自己的位置。延迟体则从消费令牌进入。
            position = self.position(caller)
            if any(position == site.call or frame.f_code.co_flags & DEFERRED_FLAGS and position in site.consumes
                   for site in sites):
                return parent
            if parameter := task_creators.get(frame.f_code):
                if any(position in site.schedules for site in sites):
                    coroutine = frame.f_locals.get(parameter)
                    if type(coroutine) is CoroutineType and coroutine.cr_frame is not None:
                        self.forward_results.setdefault(coroutine.cr_frame, parent)
        return None

    def forward_return(self, frame, arg):
        # 内层已交接的同一对象保留内层归属，不能从外层直接跳过内层包装器。
        if inherits(type(arg), native_task):
            arg = native_task.get_coro(arg)
        attr = DEFERRED_FRAMES.get(type(arg))
        if not attr or (child := getattr(arg, attr)) is None or child in self.forward_results:
            return
        visit = self.forward_calls.get(frame)
        plan = self.targets.forwarding.get(frame.f_code, NO_FORWARDING)
        self.forward_results[child] = visit if visit and (plan.all_exits or self.position(frame) in plan.exits) else None

    def profile(self, frame, event, arg):
        code = frame.f_code
        if event == "c_call" and code in wait_result_codes and arg.__name__ == "result":
            joined(active.get(), current_task(), (arg.__self__,))
        if event == "return" and (frame in self.activations or frame in self.forward_calls
                                  or frame in self.foreign_calls or code is RELOAD_CODE):
            normal_return = code.co_code[frame.f_lasti] in returns if frame.f_lasti >= 0 else False
            if frame in self.forward_calls or frame in self.foreign_calls:
                if normal_return:
                    self.forward_return(frame, arg)
                self.foreign_calls.discard(frame)
            if frame in self.activations:
                token, local = self.activations.pop(frame)
                active.reset(token)
                if normal_return:
                    attr = DEFERRED_FRAMES.get(type(arg))
                    if attr and (child := getattr(arg, attr)) is not None:
                        parents = self.deferred.setdefault(child, {})
                        parents.update((s.origin, s) for s in local if s is not self.test_scope)
                    elif inherits(type(arg), native_task):
                        for scope in local:
                            if scope.origin.wrapper:
                                scope.origin.returned.add(arg)
            if code is RELOAD_CODE and normal_return and inspect.ismodule(arg):
                # 按每次实际加载的精确绑定匹配；老对象不能替换新一轮的公开绑定。
                for exports in (self.production, self.targets):
                    if vars(arg) is exports.globals and arg is frame.f_locals.get("module"):
                        exports.load(exports.origins)
            return
        if event != "call":
            return
        inherited, local = active.get(), []
        in_probe = self.probe is not None and frame.f_back is self.probe
        in_test = self.test_scope in inherited
        if self.test and (code.co_filename, code.co_firstlineno, code.co_name) == self.test:
            if frame not in self.scopes:
                self.scopes[frame] = Invocation()
            self.test_scope = self.scopes[frame]
            local.append(self.test_scope)
        elif in_test or self.probe is not None:
            if (in_probe or in_test or frame in self.scopes) and (bindings := self.production.candidates(frame)):
                if self.production.initialized(frame):
                    if frame not in self.scopes:
                        self.scopes[frame] = Invocation(call=self.call(frame, bindings))
                    local.append(self.scopes[frame])
            if frame in self.deferred and self.production.initialized(frame):
                for origin, parent in self.deferred[frame].items():
                    key = (frame, origin)
                    if key not in self.resumed:
                        self.resumed[key] = Invocation(parent=parent)
                    local.append(self.resumed[key])
        scopes = (*inherited, *local)
        # 生产公开入口可主动调用生产构造器；导入、重载、类体以及承接侧
        # 构造器仍是初始化。裸生产构造器也不能替登记测试形成直接证据。
        parent = (self.forward_results[frame] if frame in self.forward_results
                  else self.forwarding_parent(frame))
        if parent and not self.targets.owns_frame(frame):
            # 外来 Python 中间层若返回延迟对象，不让本地外层越过它认领该对象。
            self.foreign_calls.add(frame)
        if ((scopes or parent) and self.targets.owns_frame(frame)
                and self.production.initialized(frame, constructors=False) and self.targets.initialized(frame)):
            bindings = self.targets.candidates(frame)
            if bindings or parent:
                visit = self.forward_calls.get(frame)
                if visit is None:
                    call = self.call(frame, bindings)
                    samples, bound = self.samples(frame, call, parent) if self.test else (({}, ((), {})), False)
                    visit = self.forward_calls[frame] = ForwardCall(call, current_task(), scopes, samples, bound)
                    if parent:
                        parent.children.append(visit)
                if bindings:
                    wrapper = None
                    if any(b.wrapper for b in bindings):
                        if frame not in self.wrappers:
                            self.wrappers[frame] = Invocation(wrapper=True)
                        wrapper = self.wrappers[frame]
                        local.append(wrapper)
                    direct = in_test and self.production.initialized(frame)
                    self.hits.append((visit, current_task(), scopes, wrapper, direct))
        if local:
            self.activations[frame] = active.set((*inherited, *local)), local

    @staticmethod
    def samples(frame, call, parent):
        code = frame.f_code
        locals_ = frame.f_locals
        count = code.co_argcount + code.co_kwonlyargcount
        varargs = bool(code.co_flags & inspect.CO_VARARGS)
        bound = any(binding.has_receiver for binding in call.bindings) or (
            parent is not None and parent.call.receiver is call.receiver and parent.bound)
        offset = int(bound and code.co_argcount > 0)
        items = [(name, locals_[name]) for name in code.co_varnames[offset:count] if name in locals_]
        extra = locals_.get(code.co_varnames[count + varargs], {}) if code.co_flags & inspect.CO_VARKEYWORDS else {}
        named = {}
        for name, value in (*items, *extra.items()):
            if type(name) is str:
                try:
                    named.setdefault(name, sample(value))
                except ValueError:
                    pass
        # *args/**kwargs 保留外层实收形状；普通帧已完成绑定，只能确认
        # / 和 * 的方向，其余具名槽在没有实际 *args 时可按名称复用。
        rest = locals_.get(code.co_varnames[count], ()) if varargs else ()
        if bound and not code.co_argcount:
            rest = rest[1:]
        end = code.co_argcount if rest else code.co_posonlyargcount
        positional = []
        positional_names = code.co_varnames[offset:end]
        for value in (*(locals_[name] for name in positional_names), *rest):
            try:
                positional.append(sample(value))
            except ValueError:
                break  # 不能让后面的参数滑进被滤掉的位置。
        keywords = {k: v for k, v in named.items() if k not in positional_names}
        return (named, (tuple(positional), keywords)), bound

    def accepted(self):
        reach = {}

        def reachable(scope, task):
            if scope not in reach:
                reach[scope] = scope.reachable()
            return task in reach[scope]

        for root, task, scopes, wrapper, direct in self.hits:
            matched = root.call.matches()
            if not matched or self.test_scope and not reachable(self.test_scope, task):
                continue
            via_public = any(scope is not self.test_scope and not scope.origin.wrapper
                             and reachable(scope, task) and public(scope) for scope in scopes)
            if not via_public and not direct:
                continue
            ordinary = [b.key for b in matched if not b.wrapper]
            if ordinary:
                yield frozenset(ordinary), (root.samples,), via_public
            if wrapper is None or not any(b.wrapper for b in matched):
                continue
            stack = [(child, (root.samples,)) for child in reversed(root.children)]
            while stack:
                child, previous = stack.pop()
                if self.test_scope and not reachable(self.test_scope, child.task):
                    continue
                if not any(s.origin is wrapper and reachable(s, child.task) for s in (wrapper, *child.scopes)) and not (
                        child.task in wrapper.returned and any(reachable(s, child.task) for s in scopes)):
                    continue
                fn = child.call.actual()
                if fn is None:
                    continue
                path = (*previous, child.samples)
                if self.targets.wrapper(fn):
                    stack.extend((visit, path) for visit in reversed(child.children))
                else:
                    yield frozenset(b.key for b in matched if b.wrapper), path, via_public

    def covers(self, expected):
        return any(via_public and not keys.isdisjoint(expected) for keys, _, via_public in self.accepted())


def public_probe(production, targets, origins, test_entered, samples, shapes):
    # pytest 可能已加载或修改受验模块；用同一冻结副本重新导入，且导入不记覆盖。
    root = Path.cwd().resolve()
    for name, loaded in list(sys.modules.items()):
        filename = vars(loaded).get("__file__") if inspect.ismodule(loaded) else None
        if isinstance(filename, str) and Path(filename).resolve().is_relative_to(root):
            sys.modules.pop(name, None)
    production.load(origins)
    targets.load(origins)

    instances, tried = {}, set()
    for binding in production.members:
        try:
            fn = binding.callable(instances, samples)
            if fn is None:
                continue
            identity = (id(fn.__func__), id(fn.__self__)) if type(fn) is MethodType else (id(fn),)
            if identity in tried:
                continue
            tried.add(identity)
            choices = binding.arguments(fn, samples, shapes)
        except (Exception, SystemExit):
            continue

        if any(probe_call(production, targets, test_entered, fn, args, kwargs) for args, kwargs in choices):
            return True
    return False


def probe_call(production, targets, test_entered, fn, args, kwargs):
    trace = Trace(production, targets, probe=sys._getframe())
    result = None

    async def consume_async_generator(generator):
        try:
            for _ in range(PROBE_STEPS):
                if trace.covers(test_entered):
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
        if attr and not trace.covers(test_entered):
            # 只驱动公开返回值；不查找或推进函数内部未返回的生成器。
            parents = trace.deferred.setdefault(getattr(result, attr), {})
            if not parents:
                parents[None] = None
            if type(result) is CoroutineType:
                asyncio.run(result)
            elif type(result) is AsyncGeneratorType:
                asyncio.run(consume_async_generator(result))
            else:
                for _ in range(PROBE_STEPS):
                    if trace.covers(test_entered):
                        break
                    next(result)
    except (Exception, SystemExit):
        # 只承认异常前实际进入的导出；不因一次探针异常停止其他公开入口。
        pass
    finally:
        sys.setprofile(None)
        result = None
    return trace.covers(test_entered)


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
            self.shapes = []

        @pytest.hookimpl(wrapper=True, trylast=True)
        def pytest_runtest_call(self, item):
            # 先完成星号导入（包括包的子模块加载及动态属性），只追踪登记调用。
            production.load(origins)
            targets.load(origins)
            trace = Trace(production, targets, test=position)
            sys.setprofile(trace.profile)
            try:
                return (yield)
            finally:
                sys.setprofile(None)
                for keys, path, via_public in trace.accepted():
                    self.entered.update(keys)
                    self.covered |= via_public
                    for samples, shape in path:
                        if shape not in self.shapes:
                            self.shapes.append(shape)
                        for key, value in samples.items():
                            self.samples.setdefault(key, value)

        def pytest_runtest_logreport(self, report):
            self.nonpass |= not report.passed or hasattr(report, "wasxfail")
            if report.when == "call" and report.passed:
                self.passed += 1

    registration = Registration()
    observe_waits()
    sys.path.insert(0, str(Path.cwd()))
    if sys.implementation.name != "cpython" or not (3, 12) <= sys.version_info[:2] <= (3, 14):
        return False
    with ClassOrigins(production, targets) as origins:
        result = pytest.main(["-p", "no:cacheprovider", "-p", "no:terminal", "--basetemp", scratch + "/pytest",
                              path + "::" + selector], plugins=[registration])
        return (result == pytest.ExitCode.OK and not registration.nonpass and registration.passed == doc["count"] and
                (registration.covered or bool(registration.entered) and
                 public_probe(production, targets, origins, registration.entered, registration.samples, registration.shapes)))


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
