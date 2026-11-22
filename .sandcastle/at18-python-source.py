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
    def __init__(self, key, member, signature, owner=None):
        self.key, self.member, self.signature, self.owner = key, member, signature, owner
        self.function = underlying(member)

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

    def arguments(self, fn, samples):
        signature = self.signature
        if type(fn) is MethodType:
            signature = MethodType(signature, fn.__self__)
        return arguments(signature, samples)


def captured_functions(fn):
    """只查看冻结包装器的捕获对象；不访问任意对象属性或运行用户代码。"""
    pending = [fn.__defaults__, fn.__kwdefaults__]
    for cell in fn.__closure__ or ():
        try:
            pending.append(cell.cell_contents)
        except ValueError:
            pass
    visited = set()
    while pending:
        obj = pending.pop()
        if id(obj) in visited:
            continue
        visited.add(id(obj))
        kind = type(obj)
        if kind in (FunctionType, MethodType):
            yield obj
        elif kind in (tuple, list, set, frozenset):
            pending.extend(obj)
        elif kind is dict:
            pending.extend(obj.values())


class Exports:
    def __init__(self, path, require_body=False):
        self.path, self.module = str(Path(path).resolve()), module(path)
        self.require_body = require_body
        raw = Path(path).read_bytes()
        declarations = list(ast.walk(ast.parse(raw, path)))
        functions = {(line(node), node.name) for node in declarations if isinstance(node, FUNCTIONS)
                     and (not require_body or substantive(node))}
        functions.update((node.lineno, "<lambda>") for node in declarations if isinstance(node, ast.Lambda))
        classes = {(line(node), node.name) for node in declarations if isinstance(node, ast.ClassDef)}
        codes = list(code_objects(compile(raw, self.path, "exec")))
        self.definitions = {c for c in codes if (c.co_firstlineno, c.co_name) in functions}
        self.classes = {c for c in codes if (c.co_firstlineno, c.co_name) in classes}

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

    def signature(self, fn, declared=(), *, inspect_captures=False):
        # __wrapped__ 是线索，不是归属证明。无该属性时，支持通过闭包/默认参数
        # 透传的本地装饰；元数据被重写也不能盖过捕获到的实际包装目标。
        def validate(current, path):
            if not self.owns_fn(current) or current in path:
                return None
            path = path | {current}
            explicit = vars(current).get("__wrapped__", MISSING)
            explicit_signature = current if explicit is MISSING else validate(explicit, path)
            if explicit_signature is None or not inspect_captures or current.__code__ in declared:
                return explicit_signature
            captures = tuple(obj for obj in captured_functions(current) if obj is not current)
            if not captures:
                return explicit_signature
            originals = tuple(obj for obj in captures if underlying(obj).__code__ in declared)
            if originals:
                captures = originals  # 其它捕获（如日志回调）不是该方法的被包装定义。
            signatures = [validate(obj, path) for obj in captures]
            if any(signature is None for signature in signatures):
                return None
            if len(signatures) == 1:
                return signatures[0]
            return explicit_signature

        return validate(fn, set())

    def load(self, origins):
        self.origins = origins
        self.globals, bindings = exported_bindings(self.module, self.path)
        self.members = tuple(self.local_members(bindings))
        self.by_code = {}
        for binding in self.members:
            self.by_code.setdefault(id(binding.function.__code__), []).append(binding)

    def class_signature(self, cls, name, fn):
        code = self.class_body(cls)
        declared = [c for c in code.co_consts if type(c) is CodeType and c.co_name == name]
        if declared and not any(c in self.definitions for c in declared):
            return None
        return self.signature(fn, declared, inspect_captures=True)

    def local_members(self, bindings):
        for export_name, value in bindings.items():
            if type(value) is FunctionType:
                if (signature := self.signature(value, inspect_captures=self.require_body)) is not None:
                    yield Binding(("module", export_name), value, signature)
            elif type(value) is MethodType and self.owns_receiver(value.__self__):
                fn = value.__func__
                cls = value.__self__ if is_class(value.__self__) else type(value.__self__)
                # 显式别名也不能替被装饰的类槽跳过实现检查。
                slots = [(base, name) for base in type.__getattribute__(cls, "__mro__")
                         if self.class_body(base) is not None for name, member in class_members(base)
                         if type(member) in (FunctionType, classmethod, staticmethod) and underlying(member) is fn]
                signatures = [self.class_signature(base, name, fn) for base, name in slots]
                signature = next((s for s in signatures if s is not None), None) if slots else self.signature(fn, inspect_captures=self.require_body)
                if signature is not None:
                    yield Binding(("module", export_name), value, signature)
            elif is_class(value) and self.class_body(value) is not None:
                for name, member in class_members(value):
                    if not name.startswith("_") and type(member) in (FunctionType, staticmethod, classmethod):
                        if (signature := self.class_signature(value, name, underlying(member))) is not None:
                            # 两个类即使由同一个工厂生成，公开名仍可区分它们。
                            yield Binding(("class", export_name, name), member, signature, value)

    def candidates(self, frame):
        if frame.f_globals is self.globals:
            return self.by_code.get(id(frame.f_code), ())
        return ()

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
    def __init__(self, call=None, parent=None):
        self.call, self.parent = call, parent
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
        self.frame, self.function = frame, function
        self.bindings = tuple(b for b in bindings if b.matches_receiver(receiver))
        self.matched = None

    def keys(self):
        if self.matched is not None:
            return self.matched
        if not self.bindings:
            return frozenset()
        fn = self.function or frame_function(self.frame)
        if fn is None:
            return frozenset()
        self.matched = frozenset(b.key for b in self.bindings if b.function is fn)
        return self.matched


def public(scope):
    while scope.call is None:
        if scope.parent is None:
            return True  # 独立探针显式驱动已返回的生成器/协程。
        scope = scope.parent
    return bool(scope.call.keys())


class Trace:
    def __init__(self, production, targets, *, test=None, probe=None):
        self.production, self.targets = production, targets
        self.test, self.probe = test, probe
        self.test_scope = None
        self.deferred = {}
        self.suspended_calls = {}
        self.scopes = {}
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

    def profile(self, frame, event, arg):
        code = frame.f_code
        if event == "c_call" and code in wait_result_codes and arg.__name__ == "result":
            joined(active.get(), current_task(), (arg.__self__,))
        if event == "return" and (frame in self.activations or code is RELOAD_CODE):
            normal_return = code.co_code[frame.f_lasti] in returns if frame.f_lasti >= 0 else False
            if frame in self.activations:
                active.reset(self.activations.pop(frame))
                scope = self.scopes[frame]
                if scope is not self.test_scope and normal_return:
                    attr = DEFERRED_FRAMES.get(type(arg))
                    if attr and (child := getattr(arg, attr)) is not None:
                        self.deferred[child] = scope
            if code is RELOAD_CODE and normal_return and inspect.ismodule(arg):
                # 按每次实际加载的精确绑定匹配；老对象不能替换新一轮的公开绑定。
                for exports in (self.production, self.targets):
                    if vars(arg) is exports.globals and arg is frame.f_locals.get("module"):
                        exports.load(exports.origins)
            return
        if event != "call":
            return
        scopes = active.get()
        scope = None
        if self.test and (code.co_filename, code.co_firstlineno, code.co_name) == self.test:
            if frame not in self.scopes:
                self.scopes[frame] = Invocation()
            scope = self.test_scope = self.scopes[frame]
        elif (self.probe is not None and (frame.f_back is self.probe or
                                          frame in self.deferred or frame in self.scopes) or
              self.test_scope in scopes):
            bindings = self.production.candidates(frame)
            if bindings or frame in self.deferred or frame in self.scopes:
                if not self.production.initialized(frame):
                    return
                if frame not in self.scopes:
                    if frame in self.deferred:
                        self.scopes[frame] = Invocation(parent=self.deferred[frame])
                    else:
                        self.scopes[frame] = Invocation(call=self.call(frame, bindings))
                scope = self.scopes[frame]
        if scope is not None:
            scopes = (*scopes, scope)
            self.activations[frame] = active.set(scopes)
        if scopes and (bindings := self.targets.candidates(frame)):
            direct = self.test_scope in scopes and self.production.initialized(frame)
            self.hits.append((self.call(frame, bindings), current_task(), scopes,
                              self.samples(frame) if self.test else {}, direct))

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
        for call, task, scopes, samples, direct in self.hits:
            keys = call.keys()
            if not keys:
                continue
            for scope in scopes:
                if scope not in reach:
                    reach[scope] = scope.reachable()
            if self.test_scope and task not in reach.get(self.test_scope, ()):
                continue
            via_public = any(scope is not self.test_scope and task in reach[scope] and public(scope)
                             for scope in scopes)
            if direct or via_public:
                yield keys, samples, via_public

    def covers(self, expected):
        return any(via_public and not keys.isdisjoint(expected) for keys, _, via_public in self.accepted())


def public_probe(production, targets, origins, test_entered, samples):
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
            args, kwargs = binding.arguments(fn, samples)
        except (Exception, SystemExit):
            continue

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
                trace.deferred.setdefault(getattr(result, attr), None)
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
        if trace.covers(test_entered):
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
            # 先完成星号导入（包括包的子模块加载及动态属性），只追踪登记调用。
            production.load(origins)
            targets.load(origins)
            trace = Trace(production, targets, test=position)
            sys.setprofile(trace.profile)
            try:
                return (yield)
            finally:
                sys.setprofile(None)
                for keys, samples, via_public in trace.accepted():
                    self.entered.update(keys)
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
    if sys.implementation.name != "cpython" or not (3, 12) <= sys.version_info[:2] <= (3, 14):
        return False
    with ClassOrigins(production, targets) as origins:
        result = pytest.main(["-p", "no:cacheprovider", "-p", "no:terminal", "--basetemp", scratch + "/pytest",
                              path + "::" + selector], plugins=[registration])
        return (result == pytest.ExitCode.OK and not registration.nonpass and registration.passed == doc["count"] and
                (registration.covered or bool(registration.entered) and
                 public_probe(production, targets, origins, registration.entered, registration.samples)))


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
