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
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from types import AsyncGeneratorType, CodeType, CoroutineType, FunctionType, GeneratorType, MethodType
from weakref import WeakKeyDictionary

import pytest


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
    if any(kind is native for native in (type(None), bool, int, float, complex, str, bytes)):
        return value
    if depth and kind is dict:
        return {sample(k, depth - 1): sample(v, depth - 1) for k, v in value.items()}
    if depth and any(kind is native for native in (tuple, list, set, frozenset)):
        return kind(sample(v, depth - 1) for v in value)
    raise ValueError("not a plain parameter sample")


def sample_key(value):
    # 仅接收 sample() 验过的值；类型标签避免 True、1、1.0 等合并。
    kind = type(value)
    if kind is float:
        return kind, value.hex()  # NaN 有稳定键，且不混同正负零。
    if kind is complex:
        return kind, (value.real.hex(), value.imag.hex())
    if kind is dict:
        items = ((sample_key(k), sample_key(v)) for k, v in value.items())
        return kind, frozenset(Counter(items).items())
    if kind is list or kind is tuple:
        return kind, tuple(map(sample_key, value))
    if kind is set or kind is frozenset:
        # 不同 NaN 可以同时在同一容器中；归一后仍保留其出现次数。
        return kind, frozenset(Counter(map(sample_key, value)).items())
    return kind, value


POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)


def arguments(signature, samples, variadic=False):
    args, kwargs, defaults = [], {}, {}
    params = signature.parameters
    extra_args, extra_kwargs = (), {}
    if variadic:
        # 无显式签名的生产包装器只能使用已经观察到的普通参数。
        remaining = {k: sample(v) for k, v in samples.items() if k not in params}
        kinds = {param.kind for param in params.values()}
        if inspect.Parameter.VAR_KEYWORD in kinds:
            extra_kwargs = remaining
        elif inspect.Parameter.VAR_POSITIONAL in kinds:
            extra_args = tuple(remaining.values())

    pos_kinds = POSITIONAL if extra_args else (inspect.Parameter.POSITIONAL_ONLY,)
    kw_kinds = (inspect.Parameter.KEYWORD_ONLY,) if extra_args else (
        inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    positional = [p for p in params.values() if p.kind in pos_kinds]
    if not extra_args:
        # 只在后面还有位置实参时填默认值；其余由 Python 自己应用。
        while positional and positional[-1].name not in samples and positional[-1].default is not inspect.Parameter.empty:
            positional.pop()
    for param in positional:
        if param.name in samples:
            args.append(sample(samples[param.name]))
        elif param.default is inspect.Parameter.empty:
            args.append(None)
        else:
            defaults[len(args)] = param.default
            args.append(param.default)
    args.extend(extra_args)

    for param in params.values():
        if param.kind in kw_kinds:
            if param.name in samples:
                kwargs[param.name] = sample(samples[param.name])
            elif param.default is inspect.Parameter.empty:
                kwargs[param.name] = None
    kwargs.update(extra_kwargs)
    return args, kwargs, defaults


def variadic_only(signature):
    return bool(signature.parameters) and all(
        p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for p in signature.parameters.values())


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
    def __init__(self, key, member, chain, owner=None):
        self.key, self.member, self.chain, self.owner = key, member, chain, owner
        self.function = chain[0]

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
            args, kwargs, _ = arguments(inspect.signature(self.owner, follow_wrapped=False), samples)
            instances[key] = self.owner(*args, **kwargs)
        if instances[key] is not None:
            return self.member.__get__(instances[key], self.owner)

    def signatures(self, fn, public, named):
        generic = variadic_only(public)
        if not generic:
            yield public
        receiver = fn.__self__ if type(fn) is MethodType else MISSING
        for target in self.chain[1:]:
            # 实际绑定的层自带签名和接收者；只考察它之后的未绑定层。
            if type(target) is MethodType:
                receiver = target.__self__
            try:
                params = inspect.signature(target, follow_wrapped=False)
            except (ValueError, TypeError):
                continue
            if variadic_only(params):
                continue
            slots = tuple(params.parameters.values())
            if type(target) is FunctionType and receiver is not MISSING and slots and slots[0].kind in POSITIONAL:
                # 按观察值排序两种形状，不绑定内层函数，也不把接收者放进实参。
                clipped = params.replace(parameters=slots[1:])
                yield from (params, clipped) if slots[0].name in named else (clipped, params)
            else:
                yield params
        if generic:
            yield public

    def arguments(self, fn, named, shapes):
        try:
            public = inspect.signature(fn, follow_wrapped=False)
        except (ValueError, TypeError):
            return

        def candidates():
            for args, kwargs in shapes:
                yield args, kwargs, {}
            for signature in self.signatures(fn, public, named):
                try:
                    yield arguments(signature, named, True)
                except (ValueError, TypeError):
                    continue

        choices, default_refs = set(), {}

        def positional_key(i, value, defaults):
            if i not in defaults:
                return sample_key(sample(value))
            try:
                plain = sample(value)
            except ValueError:
                # 非纯数据的生产默认值只按身份比较；保活以免 id 被复用。
                identity = id(value)
                default_refs[identity] = value
                return MISSING, identity
            return sample_key(plain)

        for args, kwargs, defaults in candidates():
            try:
                public.bind(*args, **kwargs)
                positional = tuple(positional_key(i, v, defaults) for i, v in enumerate(args))
                keywords = frozenset((k, sample_key(sample(v))) for k, v in kwargs.items())
            except (ValueError, TypeError):
                continue
            choice = positional, keywords
            if choice not in choices:
                choices.add(choice)
                yield (tuple(v if i in defaults else sample(v) for i, v in enumerate(args)),
                       {k: sample(v) for k, v in kwargs.items()})


def has_executable_body(code):
    # 两版 CPython 对隐式 None 返回和空生成器的指令组合不同。
    scaffold = {"RESUME", "RETURN_GENERATOR", "POP_TOP", "COPY_FREE_VARS", "MAKE_CELL",
                "NOP", "CACHE", "RETURN_VALUE", "NOT_TAKEN", "RERAISE"}
    return any(i.opname not in scaffold and not (
        i.opname in ("LOAD_CONST", "RETURN_CONST") and i.argval is None or
        i.opname == "CALL_INTRINSIC_1" and i.argrepr == "INTRINSIC_STOPITERATION_ERROR"
    ) for i in dis.get_instructions(code))


class Exports:
    def __init__(self, path, require_body=False):
        self.path, self.module = str(Path(path).resolve()), module(path)
        raw = Path(path).read_bytes()
        declarations = tuple(ast.walk(ast.parse(raw, path)))
        functions = {(line(n), n.name) for n in declarations if isinstance(n, FUNCTIONS)}
        functions.update((n.lineno, "<lambda>") for n in declarations if isinstance(n, ast.Lambda))
        classes = {(line(n), n.name) for n in declarations if isinstance(n, ast.ClassDef)}
        codes = tuple(code_objects(compile(raw, self.path, "exec")))
        self.definitions = {c for c in codes if (c.co_firstlineno, c.co_name) in functions}
        self.executable = {c for c in self.definitions if not require_body or has_executable_body(c)}
        self.classes = {c for c in codes if (c.co_firstlineno, c.co_name) in classes}

    def owns_frame(self, frame):
        return (frame.f_globals is self.globals and frame.f_code.co_filename == self.path and
                frame.f_code in self.definitions)

    def owns_fn(self, fn):
        return (type(fn) is FunctionType and fn.__globals__ is self.globals and
                fn.__code__.co_filename == self.path and fn.__code__ in self.executable)

    def class_body(self, cls):
        record = self.origins.classes.get(id(cls))
        if record is not None:
            _, body = record
            if body.__globals__ is self.globals and body.__code__ in self.classes:
                return body.__code__

    def owns_receiver(self, receiver):
        cls = receiver if is_class(receiver) else type(receiver)
        return self.class_body(cls) is not None

    def wrapped_chain(self, target):
        chain, seen = [], set()
        while True:
            if type(target) is MethodType:
                if not self.owns_receiver(target.__self__):
                    return None
                fn = target.__func__
                identity = (id(fn), id(target.__self__))
            elif type(target) is FunctionType:
                fn, identity = target, (id(target),)
            else:
                return None
            if identity in seen or not self.owns_fn(fn):
                return None
            seen.add(identity)
            chain.append(target)
            explicit = vars(fn).get("__wrapped__", MISSING)
            if explicit is MISSING:
                return tuple(chain)
            target = explicit

    def load(self, origins):
        self.origins = origins
        self.globals, bindings = exported_bindings(self.module, self.path)
        self.members = tuple(self.local_members(bindings))
        self.by_code = {}
        self.wrapped_codes = set()
        for binding in self.members:
            self.by_code.setdefault(id(binding.function.__code__), []).append(binding)
            self.wrapped_codes.update(id(underlying(target).__code__) for target in binding.chain[1:])

    def binding(self, key, member, owner=None):
        fn = underlying(member)
        if chain := self.wrapped_chain(fn):
            return Binding(key, member, chain, owner)

    def local_members(self, bindings):
        for export_name, value in bindings.items():
            if type(value) is FunctionType or type(value) is MethodType and self.owns_receiver(value.__self__):
                if (binding := self.binding(("module", export_name), value)) is not None:
                    yield binding
            elif is_class(value) and self.class_body(value) is not None:
                seen = set()
                for owner in type.__getattribute__(value, "__mro__"):
                    local = self.class_body(owner) is not None
                    for name, member in class_members(owner):
                        if name in seen:
                            continue
                        seen.add(name)
                        if local and not name.startswith("_") and type(member) in (FunctionType, staticmethod, classmethod):
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
    """等待关系属调用；继承上下文不等于调用者显式消费了任务。"""
    def __init__(self, kind, call=None, origin=None):
        self.kind, self.call = kind, call
        self.origin = origin if origin is not None else self
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
    done, pending = set(), list(futures)
    while pending:
        future = pending.pop()
        if not isinstance(future, native_future) or future in done or not future.done() or future.cancelled():
            continue
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
    def __init__(self, frame, bindings):
        code = frame.f_code
        self.frame, self.function = frame, None
        self.receiver = receiver_at_entry(frame)
        if code.co_flags & DEFERRED_FLAGS:
            # 恢复后接收者局部变量可已改写；只在第一次 RESUME 取初值。
            if code.co_code[frame.f_lasti:frame.f_lasti + 2] != bytes((dis.opmap["RESUME"], 0)):
                self.receiver = MISSING
            if (owner := deferred_owner(frame)) is not None:
                self.function = frame_function(frame, owner)
        self.bindings = tuple(b for b in bindings if b.matches_receiver(self.receiver))

    def actual(self):
        if self.function is None:
            self.function = frame_function(self.frame)
        return self.function

    def matches(self):
        return tuple(b for b in self.bindings if b.function is self.actual())

    def matches_member(self, target):
        if type(target) is MethodType:
            return self.actual() is target.__func__ and self.receiver is target.__self__
        return self.actual() is target


def deferred_result(value):
    if attr := DEFERRED_FRAMES.get(type(value)):
        return getattr(value, attr) or MISSING
    if inherits(type(value), native_future):
        return value
    return None


class Trace:
    def __init__(self, production, targets, *, test=None, probe=None):
        self.production, self.targets = production, targets
        self.test, self.probe = test, probe
        self.test_scope = None
        self.probe_scope = Invocation("probe") if probe is not None else None
        self.calls, self.scopes, self.activations = {}, {}, {}
        self.deferred, self.resumed, self.results = {}, {}, {}
        self.hits, self.observations = [], {}

    def call(self, frame, bindings):
        if frame not in self.calls:
            self.calls[frame] = Call(frame, bindings)
        return self.calls[frame]

    def start(self):
        sys.setprofile(self.profile)

    def stop(self):
        sys.setprofile(None)

    def leave(self, frame, result):
        code = frame.f_code
        normal = frame.f_lasti >= 0 and code.co_code[frame.f_lasti] in returns
        if frame in self.activations:
            token, local = self.activations.pop(frame)
            active.reset(token)
            if normal and (pending := deferred_result(result)) is not None:
                self.results[frame] = pending
                if type(result) in DEFERRED_FRAMES and pending is not MISSING:
                    self.deferred.setdefault(pending, set()).update(s.origin for s in local if s.kind != "test")
        if code is RELOAD_CODE and normal and inspect.ismodule(result):
            for exports in (self.production, self.targets):
                if vars(result) is exports.globals and result is frame.f_locals.get("module"):
                    exports.load(exports.origins)

    def profile(self, frame, event, arg):
        code = frame.f_code
        if event == "return":
            if frame in self.activations or code is RELOAD_CODE:
                self.leave(frame, arg)
            return
        if event == "c_call" and code in wait_result_codes and arg.__name__ == "result":
            joined(active.get(), current_task(), (arg.__self__,))
        if event != "call":
            return
        inherited, local = active.get(), []
        in_test = self.test_scope in inherited
        in_probe = self.probe is not None and frame.f_back is self.probe
        if self.test and (code.co_filename, code.co_firstlineno, code.co_name) == self.test:
            if frame not in self.scopes:
                self.scopes[frame] = Invocation("test")
            self.test_scope = self.scopes[frame]
            local.append(self.test_scope)
        elif in_test or self.probe is not None:
            if (in_probe or in_test or frame in self.scopes) and (bindings := self.production.candidates(frame)):
                if self.production.initialized(frame):
                    if frame not in self.scopes:
                        self.scopes[frame] = Invocation("production", self.call(frame, bindings))
                    local.append(self.scopes[frame])
            if frame in self.deferred and self.production.initialized(frame, constructors=False) and self.targets.initialized(frame):
                task = current_task()
                resumed = self.resumed.setdefault(frame, {})
                for origin in self.deferred[frame]:
                    key = (origin, task)
                    if key not in resumed:
                        resumed[key] = Invocation(origin.kind if origin else "production", origin=origin)
                    local.append(resumed[key])
        scopes = (*inherited, *local)
        if (scopes and self.targets.owns_frame(frame) and self.targets.initialized(frame)
                and self.production.initialized(frame, constructors=False)):
            bindings = self.targets.candidates(frame)
            if bindings:
                call = self.call(frame, bindings)
                if frame not in self.scopes:
                    self.scopes[frame] = Invocation("target", call)
                target = self.scopes[frame]
                local.append(target)
                self.hits.append((frame, target, scopes, in_test and self.production.initialized(frame), current_task()))
            # 内层帧只核显式包装对象与实收的纯数据，不推断未声明的包装关系。
            wrapped = id(code) in self.targets.wrapped_codes
            for scope in (*inherited, *local):
                if scope.kind != "target" or not (wrapped or self.test):
                    continue
                frames = self.observations.setdefault(scope.origin, {})
                if frame not in frames:
                    root, receiver = scope.origin.call, receiver_at_entry(frame)
                    bound = (receiver is root.receiver and any(b.has_receiver for b in root.bindings)
                             or any(b.has_receiver and b.matches_receiver(receiver) for b in bindings))
                    frames[frame] = (scope, current_task(), self.call(frame, bindings) if wrapped else None,
                                     self.sample_frame(frame, bound) if self.test else None)
        if local:
            self.activations[frame] = active.set((*inherited, *local)), local

    @staticmethod
    def sample_frame(frame, bound):
        code = frame.f_code
        locals_ = frame.f_locals
        count = code.co_argcount + code.co_kwonlyargcount
        varargs = bool(code.co_flags & inspect.CO_VARARGS)
        offset = int(bound and code.co_argcount > 0)
        items = [(name, locals_[name]) for name in code.co_varnames[offset:count] if name in locals_]
        extra = locals_.get(code.co_varnames[count + varargs], {}) if code.co_flags & inspect.CO_VARKEYWORDS else {}
        def plain(items):
            values = {}
            for name, value in items:
                if type(name) is str:
                    try:
                        values[name] = sample(value)
                    except ValueError:
                        pass
            return values

        named, extras = plain(items), plain(extra.items())
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
        # 同名 / 槽不会占用 **kwargs 的键。
        keywords = {k: v for k, v in named.items() if k not in positional_names}
        for key, value in extras.items():
            named.setdefault(key, value)
        return named, (tuple(positional), keywords | extras)

    def accepted(self):
        reach = {}

        def reachable(scope, task):
            if scope not in reach:
                reach[scope] = scope.reachable()
            return task in reach[scope]

        def test_reaches(task):
            return self.test_scope is None or reachable(self.test_scope, task)

        def consumed(frame, target, scopes):
            # 只追踪原生延迟对象的消费，不检查一般返回值。
            consumer = self.test_scope or self.probe_scope
            seen = set()
            while (pending := self.results.get(frame)) is not None:
                if pending is MISSING or pending in seen:
                    return False
                if inherits(type(pending), native_future):
                    return any(reachable(s, pending) for s in (*scopes, consumer))
                if not any(origin is target and test_reaches(task) and any(reachable(s, task) for s in (*scopes, consumer))
                           for origin, task in self.resumed.get(pending, ())):
                    return False
                seen.add(pending)
                frame = pending
            return True

        for frame, target, scopes, direct, task in self.hits:
            matched = target.call.matches()
            if not matched or not test_reaches(task) or not consumed(frame, target, scopes):
                continue
            via_public = any(s.kind == "production" and reachable(s, task) and
                             (s.origin.call is None or s.origin.call.matches()) for s in scopes)
            if not (via_public or direct):
                continue
            entries = [(call, data) for s, t, call, data in self.observations.get(target, {}).values()
                       if reachable(s, t) and test_reaches(t)]
            observed = [call for call, _ in entries if call is not None]
            keys = frozenset(b.key for b in matched if
                             all(any(call.matches_member(target) for call in observed) for target in b.chain[1:]))
            if keys:
                yield keys, tuple(data for _, data in entries if data is not None), via_public

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
            for args, kwargs in binding.arguments(fn, samples, shapes):
                if probe_call(production, targets, test_entered, fn, args, kwargs):
                    return True
        except (Exception, SystemExit):
            continue
    return False


def probe_call(production, targets, test_entered, fn, args, kwargs):
    trace = Trace(production, targets, probe=sys._getframe())
    result = None

    async def consume(generator):
        try:
            for _ in range(PROBE_STEPS):
                if trace.covers(test_entered):
                    break
                await anext(generator)
        except StopAsyncIteration:
            pass
        finally:
            trace.stop()  # 不观察 asyncio.run 收尾时的隐式 aclose。

    try:
        trace.start()
        result = fn(*args, **kwargs)
        if (attr := DEFERRED_FRAMES.get(type(result))) and not trace.covers(test_entered):
            # 只驱动公开入口返回的原生延迟对象。
            origins = trace.deferred.setdefault(getattr(result, attr), set())
            if not origins:
                origins.add(None)
            token = active.set((trace.probe_scope,))
            try:
                if type(result) is CoroutineType:
                    asyncio.run(result)
                elif type(result) is AsyncGeneratorType:
                    asyncio.run(consume(result))
                else:
                    for _ in range(PROBE_STEPS):
                        if trace.covers(test_entered):
                            break
                        next(result)
            finally:
                active.reset(token)
    except (Exception, SystemExit):
        # 只承认异常前实际进入的导出；不因一次探针异常停止其他公开入口。
        pass
    finally:
        trace.stop()
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
            trace.start()
            try:
                return (yield)
            finally:
                trace.stop()
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
