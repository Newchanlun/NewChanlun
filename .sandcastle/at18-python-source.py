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
from types import AsyncGeneratorType, CodeType, CoroutineType, FunctionType, GeneratorType, GetSetDescriptorType, MemberDescriptorType, MethodType
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
        # 已实收的普通位置实参也能绑定到具名生产入口；不能因目标用
        # *args 而把它丢成 None，再把入口异常误当作成功执行。
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


ProductionSite = namedtuple("ProductionSite", "spreads capture")
ProductionShape = namedtuple("ProductionShape", "sites discarded")
ORDINARY_PRODUCTION = ProductionShape((), False)


def production_shape(node):
    """保持生产探针的包装器签名及显式消费约束；不用于判断承接函数体。"""
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

    def origin(value):
        if isinstance(value, ast.Name) and stores.get(value.id) == 1 and value.id in assigned:
            earlier = assigned[value.id]
            if (earlier.lineno, earlier.col_offset) < (value.lineno, value.col_offset):
                return origin(earlier)
        if isinstance(value, (ast.Await, ast.YieldFrom)):
            return origin(value.value)
        if not isinstance(value, ast.Call):
            return None
        callee = value.func
        label = callee.attr if isinstance(callee, ast.Attribute) else callee.id if isinstance(callee, ast.Name) else None
        if label in ("create_task", "ensure_future") and value.args:
            return origin(value.args[0])
        star = spreads(value)
        args = [*value.args, *(k.value for k in value.keywords)]
        if not star and not all(isinstance(a, ast.Name) and a.id in names for a in args):
            return None
        while isinstance(callee, (ast.Attribute, ast.Subscript)):
            callee = callee.value
        capture = (callee.id, callee is not value.func) if isinstance(callee, ast.Name) else None
        return ProductionSite(star, capture)

    sites = set()
    if isinstance(node, ast.Lambda):
        if site := origin(node.body):
            sites.add(site)
        values = [node.body]
    else:
        values = []
        for stmt in scope:
            if isinstance(stmt, ast.Return):
                values.append(stmt.value)
                if site := origin(stmt.value):
                    sites.add(site)
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
                        if site := origin(loop.iter):
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
    return ProductionShape(sites, discarded)


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


# 出口的值来源和调用点各有独立的源码位置。桥接位置供运行时追踪
# await/yield from/迭代，不把该行其它调用（包括收尾日志）挂进来。
Site = namedtuple("Site", "call consumes schedules iterates", defaults=(frozenset(), frozenset(), False))
Source = namedtuple("Source", "kind position site slots", defaults=(None, None))
SequenceSlots = namedtuple("SequenceSlots", "items unknown", defaults=(frozenset(),))
MappingSlots = namedtuple("MappingSlots", "items")
Filter = namedtuple("Filter", "test calls item_names reads_item")


def within(position, outer):
    start, end, col, end_col = position
    return (start is not None and end is not None and col is not None and end_col is not None and
            (outer[0], outer[2]) <= (start, col) <= (end, end_col) <= (outer[1], outer[3]))


def slot_key(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        if type(node.operand.value) in (int, float, complex):
            return -node.operand.value
    return MISSING


def aggregate(position, slots):
    # 循环中同一构造点可能包住上一轮的容器。截在重复构造点，
    # 保留该值的来源，但不把无限嵌套的形状带进固定点。
    def prune(source, seen):
        if source.slots is None:
            return source
        if source.position in seen:
            return source._replace(slots=None)
        return source._replace(slots=prune_slots(source.slots, seen | {source.position}))

    def prune_slots(shape, seen):
        def items(sources):
            return frozenset(prune(source, seen) for source in sources)
        if isinstance(shape, SequenceSlots):
            return SequenceSlots(tuple(items(part) for part in shape.items), items(shape.unknown))
        return MappingSlots(tuple((key, items(part)) for key, part in shape.items))

    return frozenset({Source("local" if slots.items or isinstance(slots, SequenceSlots) and slots.unknown else "constant", position,
                             slots=prune_slots(slots, {position}))})

Exit = namedtuple("Exit", "kind position operands sources")


def merge_states(*states):
    result = {}
    for state in states:
        for name, sources in state.items():
            result[name] = result.get(name, frozenset()) | sources
    return result


def guarded_stream(node):
    return isinstance(node, ast.GeneratorExp) and any(c.ifs for c in node.generators)


class ExitFlow:
    def __init__(self, node, code):
        self.exits, self.scheduled = {}, set()
        self.yield_filters, self.iterators = {}, set()
        self.call_nodes = {}
        self.predicate_sites = set()
        self.loop_reads = {}
        self.local_iterators = {}
        self.while_bodies = {}
        self.iteration_targets = set()
        self.names, self.writes = {}, {}
        parameters = {}
        self.spread = set()
        if guarded_stream(node):
            # 隐式的 <genexpr> 帧从外层接到迭代器；仅进入该帧或
            # 沿用元素不是本地证据，真正的变换/过滤走与 for 相同的规则。
            body = [ast.copy_location(ast.Expr(
                value=ast.copy_location(ast.Yield(value=node.elt), node.elt)), node.elt)]
            for index, comp in reversed(list(enumerate(node.generators))):
                for test in reversed(comp.ifs):
                    body = [ast.copy_location(ast.If(test=test, body=body, orelse=[]), test)]
                iterator = comp.iter
                if index == 0:
                    iterator = ast.copy_location(ast.Name(id=".0", ctx=ast.Load()), iterator)
                    parameters[".0"] = frozenset({Source("borrowed", span(iterator))})
                loop = ast.AsyncFor if comp.is_async else ast.For
                body = [ast.copy_location(loop(target=comp.target, iter=iterator, body=body, orelse=[]),
                                          comp.iter)]
            self.block(body, parameters)
        else:
            args = node.args
            extra = tuple(p for p in (args.vararg, args.kwarg) if p is not None)
            self.spread = {p.arg for p in extra}
            parameters = {p.arg: frozenset({Source("read", None)})
                          for p in (*args.posonlyargs, *args.args, *args.kwonlyargs, *extra)}
            if isinstance(node, ast.Lambda):
                self.exit("return", node.body, node.body, self.value(node.body, parameters))
            else:
                self.block(node.body, parameters)
        # 谓词入参必须参与返回值或选择返回值的分支；旁支读取不算。
        predicate_nodes, control_nodes = set(), set()
        definition = (node.body,) if isinstance(node, ast.Lambda) else tuple(scope_nodes(node))
        assignments = {}
        for part in definition:
            if isinstance(node, ast.Lambda) and part is node.body:
                predicate_nodes.add(part)
            elif isinstance(part, ast.Return) and part.value is not None:
                predicate_nodes.add(part.value)
                if isinstance(part.value, ast.IfExp):
                    control_nodes.add(part.value.test)
            elif isinstance(part, ast.If) and any(isinstance(n, ast.Return) for n in scope_nodes(part)):
                control_nodes.add(part.test)
            elif isinstance(part, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and part.value is not None:
                targets = part.targets if isinstance(part, ast.Assign) else (part.target,)
                for target in targets:
                    for name in ast.walk(target):
                        if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                            assignments.setdefault(name.id, set()).add(part.value)
        pending = list(predicate_nodes | control_nodes)
        read = set()
        while pending:
            for part in ast.walk(pending.pop()):
                if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Load) and part.id not in read:
                    read.add(part.id)
                    pending.extend(assignments.get(part.id, ()))
        self.predicate_inputs = read.intersection(parameters.keys() | set(code.co_freevars))

        self.filters = {f for group in self.yield_filters.values() for f in group}
        self.sites = {o.site for e in self.exits.values() for o in e.sources if o.site is not None}
        self.sites.update(self.predicate_sites)
        self.sites.update(Site(key) for f in self.filters for key in f.calls)
        self.calls = {site.call for site in self.sites}
        self.invoking, self.scheduling = {}, {}
        for site in self.sites:
            for position in {site.call} | site.consumes:
                self.invoking.setdefault(position, set()).add(site.call)
            for position in site.schedules:
                self.scheduling.setdefault(position, set()).add(site.call)
        self.iterated_calls = {o.site.call for e in self.exits.values() if e.kind in ("delegate", "yield")
                               for o in e.sources if o.site is not None and o.site.iterates}
        self.positions = self.calls | {o.position for e in self.exits.values() for o in e.sources}
        self.operands = {}
        for e in self.exits.values():
            for position in e.operands:
                self.operands.setdefault(position, set()).add(e.position)
        self.instructions = {i.offset: (i.opname, tuple(i.positions), i.argval) for i in dis.get_instructions(code)}
        self.code_positions = tuple(code.co_positions())
        yields = {position for op, position, _ in self.instructions.values() if op == "YIELD_VALUE"
                  and position in self.exits}
        self.iteration_offsets = {
            offset for offset, (op, position, _) in self.instructions.items()
            if any(not self.local_iterators[loop].isdisjoint(yields) for loop in self.loop_reads.get(position, ())) or (
                op not in ("NOP", "NOT_TAKEN", "JUMP_BACKWARD") and
                any(not outputs.isdisjoint(yields) and within(position, body)
                    for body, outputs in self.while_bodies.items()))
        }
        self.advance_offsets = {
            offset for offset, (op, position, _) in self.instructions.items()
            if position in self.iteration_targets and op.startswith("STORE_")
        }
        self.filter_offsets, self.predicate_controls = {}, {}
        direct_controls = []
        for test in control_nodes:
            scope = list(ast.walk(test))
            if not any(isinstance(n, ast.Call) for n in scope):
                names = self.predicate_inputs.intersection(n.id for n in scope if isinstance(n, ast.Name))
                if names:
                    direct_controls.append((span(test), names))
        previous = None
        for offset, (op, position, _) in self.instructions.items():
            if op.startswith("POP_JUMP_IF"):
                if names := set().union(*(names for test, names in direct_controls if within(position, test))):
                    self.predicate_controls[offset] = names
                choices = tuple(f for f in self.filters if within(position, f.test) or (
                    guarded_stream(node) and previous is not None and within(previous, f.test)))
                if choices:
                    self.filter_offsets[offset] = choices
            previous = position


    @staticmethod
    def yield_positions(statements):
        return {span(n) for stmt in statements for n in (stmt, *scope_nodes(stmt))
                if isinstance(n, (ast.Yield, ast.YieldFrom))}

    def exit(self, kind, node, operand, sources):
        key = span(node)
        if operand is None:
            leaves = {key}
        else:
            def arms(expr):
                if isinstance(expr, ast.IfExp):
                    return arms(expr.body) | arms(expr.orelse)
                if isinstance(expr, ast.NamedExpr):
                    return arms(expr.value)
                if isinstance(expr, ast.BoolOp):
                    return set().union(*(arms(v) for v in expr.values))
                return {span(expr)}
            leaves = arms(operand)
        old = self.exits.get(key)
        self.exits[key] = Exit(kind, key, frozenset(leaves), sources if old is None else sources | old.sources)

    @staticmethod
    def bridge(sources, position, *, schedule=False, iterates=False):
        return frozenset(Source(o.kind, position, o.site._replace(
            schedules=o.site.schedules | {position}) if schedule else o.site._replace(
            consumes=o.site.consumes | {position}, iterates=iterates or o.site.iterates), o.slots) if o.site is not None else
            o._replace(position=position) for o in sources)

    @classmethod
    def project(cls, sources, key, position):
        result = set()
        for source in sources:
            if isinstance(source.slots, SequenceSlots):
                items = source.slots.items
                result.update(source.slots.unknown)
                if key is MISSING:
                    result.update(*items)
                elif type(key) is int and -len(items) <= key < len(items):
                    result.update(items[key])
            elif isinstance(source.slots, MappingSlots):
                items = source.slots.items
                if key is MISSING:
                    result.update(*(values for _, values in items))
                else:
                    result.update(dict(items).get(key, ()), dict(items).get(MISSING, ()))
            else:
                result.update(cls.bridge((source,), position, iterates=True) if source.site is not None else (source,))
        return frozenset(result)

    @classmethod
    def unpack(cls, targets, sources, position):
        star = next((i for i, target in enumerate(targets)
                     if isinstance(target, (ast.Starred, ast.MatchStar))), None)
        for index, target in enumerate(targets):
            if star is not None and index == star:
                rest = set()
                after = len(targets) - star - 1
                for source in sources:
                    if isinstance(source.slots, SequenceSlots):
                        items = source.slots.items
                        rest.update(aggregate(position, SequenceSlots(items[star:len(items) - after],
                                                                     source.slots.unknown)))
                    else:
                        # 星号绑定本身新建列表；未知的是列表内各项，而不是列表身份。
                        rest.update(aggregate(position, SequenceSlots((), cls.project((source,), MISSING, position))))
                yield target, frozenset(rest)
            else:
                key = index if star is None or index < star else index - len(targets)
                yield target, cls.project(sources, key, position)

    def pattern(self, pattern, sources, env, subject):
        if isinstance(pattern, ast.MatchAs):
            if pattern.pattern is not None:
                self.pattern(pattern.pattern, sources, env, subject)
            if pattern.name is not None:
                self.write(pattern.name, span(pattern), sources, env, subject)
        elif isinstance(pattern, ast.MatchOr):
            arms = []
            for option in pattern.patterns:
                arm = env.copy()
                self.pattern(option, sources, arm, subject)
                arms.append(arm)
            env.update(merge_states(*arms))
        elif isinstance(pattern, ast.MatchSequence):
            for child, part in self.unpack(pattern.patterns, sources, span(subject if subject is not None else pattern)):
                self.pattern(child, part, env, None)
        elif isinstance(pattern, ast.MatchStar):
            if pattern.name is not None:
                self.write(pattern.name, span(pattern), sources, env)
        elif isinstance(pattern, ast.MatchMapping):
            for key, child in zip(pattern.keys, pattern.patterns):
                self.pattern(child, self.project(sources, slot_key(key), span(key)), env, None)
            if pattern.rest is not None:
                keys = {slot_key(key) for key in pattern.keys}
                rest = set()
                for source in sources:
                    if isinstance(source.slots, MappingSlots):
                        rest.update(aggregate(span(pattern), MappingSlots(tuple(
                            (key, values) for key, values in source.slots.items if key not in keys))))
                    else:
                        rest.update(aggregate(span(pattern), MappingSlots((
                            (MISSING, self.project((source,), MISSING, span(pattern))),))))
                self.write(pattern.rest, span(pattern), frozenset(rest), env)
        elif isinstance(pattern, ast.MatchClass):
            for child in (*pattern.patterns, *pattern.kwd_patterns):
                self.pattern(child, self.project(sources, MISSING, span(child)), env, None)

    def value(self, value, env):
        if value is None:
            return frozenset({Source("constant", None)})
        key = span(value)
        if isinstance(value, ast.Name):
            self.names[key] = value.id
            for origin in env.get(value.id, ()):
                if origin.position in self.local_iterators and origin.kind in ("local", "read"):
                    self.loop_reads.setdefault(key, set()).add(origin.position)
            return env.get(value.id, frozenset({Source("read", key)}))
        if isinstance(value, ast.NamedExpr):
            sources = self.value(value.value, env)
            self.bind(value.target, sources, env, value.value)
            return sources
        if isinstance(value, ast.IfExp):
            self.value(value.test, env)
            left, right = env.copy(), env.copy()
            sources = self.value(value.body, left) | self.value(value.orelse, right)
            env.update(merge_states(left, right))
            return sources
        if isinstance(value, ast.BoolOp):
            # 短路表达式可返回任一操作数；其后的赋值不保证发生。
            states, sources = [env.copy()], frozenset()
            inside = env.copy()
            for operand in value.values:
                sources |= self.value(operand, inside)
                states.append(inside.copy())
            env.update(merge_states(*states))
            return sources
        if isinstance(value, ast.Await):
            return self.bridge(self.value(value.value, env), key)
        if isinstance(value, ast.YieldFrom):
            sources = self.bridge(self.value(value.value, env), key, iterates=True)
            self.exit("delegate", value, value.value, sources)
            return sources
        if isinstance(value, ast.Yield):
            self.exit("yield", value, value.value, self.value(value.value, env))
            if isinstance(value.value, ast.IfExp):
                self.guard(value.value.test, env, {key})
            return frozenset({Source("read", key)})   # yield 表达式的结果由 send 给入。
        if isinstance(value, (ast.Tuple, ast.List)):
            items, unknown = [], frozenset()
            for part in value.elts:
                if isinstance(part, ast.Starred):
                    variants = self.value(part.value, env)
                    if len(variants) == 1 and isinstance((o := next(iter(variants))).slots, SequenceSlots):
                        items.extend(o.slots.items)
                        unknown |= o.slots.unknown
                    else:
                        unknown |= self.project(variants, MISSING, key)
                else:
                    items.append(self.value(part, env))
            if unknown:
                unknown = unknown.union(*items)
                items = []
            return aggregate(key, SequenceSlots(tuple(items), unknown))
        if isinstance(value, ast.Dict):
            items = {}
            for k, v in zip(value.keys, value.values):
                if k is not None:
                    self.value(k, env)
                part = self.value(v, env)
                if k is None and len(part) == 1 and isinstance(next(iter(part)).slots, MappingSlots):
                    items.update(next(iter(part)).slots.items)
                else:
                    label = slot_key(k)
                    items[label] = part if label is not MISSING else items.get(label, frozenset()) | part
            return aggregate(key, MappingSlots(tuple(items.items())))
        if isinstance(value, ast.Subscript):
            container = self.value(value.value, env)
            self.value(value.slice, env)
            if not isinstance(value.slice, ast.Slice):
                sources = self.project(container, slot_key(value.slice), key)
                if sources:
                    return sources
        if isinstance(value, ast.Call):
            self.call_nodes[key] = value
            self.value(value.func, env)
            args = [self.value(a, env) for a in value.args]
            for keyword in value.keywords:
                self.value(keyword.value, env)
            callee = value.func
            label = callee.attr if isinstance(callee, ast.Attribute) else callee.id if isinstance(callee, ast.Name) else None
            if label in ("create_task", "ensure_future") and args and any(o.site for o in args[0]):
                if any(isinstance(a, ast.Starred) and isinstance(a.value, ast.Name) and a.value.id in self.spread or
                       isinstance(a, ast.keyword) and a.arg is None and isinstance(a.value, ast.Name) and a.value.id in self.spread
                       for a in ast.walk(value.args[0])):
                    self.scheduled.add(key)
                return self.bridge(args[0], key, schedule=True)
            return frozenset({Source("call", key, Site(key))})
        if guarded_stream(value):
            self.value(value.generators[0].iter, env)
            return frozenset({Source("call", key, Site(key))})
        if not isinstance(value, (ast.Lambda, ast.GeneratorExp)):
            for child in ast.iter_child_nodes(value):
                self.nested(child, env)
        literal = (isinstance(value, ast.Constant) or
                   isinstance(value, (ast.List, ast.Tuple, ast.Set)) and not value.elts or
                   isinstance(value, ast.Dict) and not value.keys or
                   isinstance(value, ast.UnaryOp) and isinstance(value.operand, ast.Constant))
        return frozenset({Source("constant" if literal else "local", key)})

    def nested(self, node, env):
        if isinstance(node, ast.expr):
            self.value(node, env)
        else:
            for child in ast.iter_child_nodes(node):
                self.nested(child, env)

    def write(self, name, position, sources, env, operand=None):
        env[name] = sources
        old = self.writes.get(position)
        alias = operand.id if isinstance(operand, ast.Name) else None
        self.writes[position] = (name, alias, sources if old is None else sources | old[2])

    def bind(self, target, sources, env, operand=None):
        if isinstance(target, ast.Name):
            self.write(target.id, span(target), sources, env, operand)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for value, part in self.unpack(target.elts, sources, span(target)):
                self.bind(value, part, env)
        elif isinstance(target, ast.Starred):
            self.bind(target.value, sources, env)
        elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name):
            name = target.value.id
            key = slot_key(target.slice)
            old = env.get(name)
            if old and key is not MISSING:
                updated = set()
                for source in old:
                    shape = source.slots
                    if isinstance(shape, MappingSlots):
                        items = dict(shape.items)
                        items[key] = sources
                        updated.update(aggregate(source.position, MappingSlots(tuple(items.items()))))
                    elif isinstance(shape, SequenceSlots) and type(key) is int and -len(shape.items) <= key < len(shape.items):
                        parts = list(shape.items)
                        parts[key] = sources
                        updated.update(aggregate(source.position, SequenceSlots(tuple(parts), shape.unknown)))
                    else:
                        updated.add(source)
                for alias, current in list(env.items()):
                    if current is old:
                        env[alias] = frozenset(updated)

    def guard(self, test, env, outputs):
        if not outputs:
            return
        def current(sources):
            return any(o.position in self.iterators for o in sources)
        item_names = frozenset(name for name, sources in env.items() if current(sources))
        if not item_names:
            return
        nodes = list(ast.walk(test))
        reads_item = any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in item_names for n in nodes)
        calls = {span(n) for n in nodes if isinstance(n, ast.Call)}
        for n in nodes:
            if isinstance(n, ast.Await):
                for source in self.value(n, env.copy()):
                    if source.site is not None:
                        self.predicate_sites.add(source.site)
                        calls.add(source.site.call)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                calls.update(o.site.call for o in env.get(n.id, ()) if o.site is not None and not o.site.iterates)
        if reads_item or calls:
            rule = Filter(span(test), frozenset(calls), item_names, reads_item)
            for output in outputs:
                self.yield_filters.setdefault(output, set()).add(rule)

    def block(self, statements, original):
        env, transfers = original.copy(), {}

        def stop(kind, state):
            transfers[kind] = merge_states(transfers.get(kind, {}), state)

        def follow(part, state):
            paths = self.block(part, state)
            next_state = paths.pop("next", None)
            for kind, effect in paths.items():
                stop(kind, effect)
            return next_state

        for i, stmt in enumerate(statements):
            if env is None:
                break
            if isinstance(stmt, ast.Return):
                self.exit("return", stmt, stmt.value, self.value(stmt.value, env))
                stop("return", env)
                env = None
            elif isinstance(stmt, (ast.Break, ast.Continue, ast.Raise)):
                stop(type(stmt).__name__.lower(), env)
                env = None
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if stmt.value is not None:
                    sources = self.value(stmt.value, env)
                    if isinstance(stmt, ast.AugAssign):
                        sources = frozenset({Source("local", span(stmt))})
                    for target in stmt.targets if isinstance(stmt, ast.Assign) else (stmt.target,):
                        self.bind(target, sources, env, None if isinstance(stmt, ast.AugAssign) else stmt.value)
            elif isinstance(stmt, ast.If):
                self.value(stmt.test, env)
                yes, no = self.yield_positions(stmt.body), self.yield_positions(stmt.orelse)
                affected = yes | no if not (yes and no) else set()
                if any(isinstance(arm[-1], (ast.Continue, ast.Break, ast.Return))
                       for arm in (stmt.body, stmt.orelse) if arm):
                    affected.update(self.yield_positions(statements[i + 1:]))
                self.guard(stmt.test, env, affected)
                paths = [follow(part, env) for part in (stmt.body, stmt.orelse)]
                env = merge_states(*(p for p in paths if p is not None)) if any(p is not None for p in paths) else None
            elif isinstance(stmt, ast.Match):
                subject = self.value(stmt.subject, env)
                paths = []
                for case in stmt.cases:
                    arm = env.copy()
                    self.pattern(case.pattern, subject, arm, stmt.subject)
                    if case.guard is not None:
                        self.value(case.guard, arm)
                        self.guard(case.guard, arm, self.yield_positions(case.body))
                    paths.append(follow(case.body, arm))
                # 只有无守卫的不可反驳末臂才确定吃掉不匹配路径。
                last = stmt.cases[-1]
                if not (last.guard is None and isinstance(last.pattern, ast.MatchAs) and last.pattern.pattern is None):
                    paths.append(env)
                env = merge_states(*(p for p in paths if p is not None)) if any(p is not None for p in paths) else None
            elif isinstance(stmt, (ast.Try, ast.TryStar)):
                # except 可从 try 的任意语句收到异常，包含赋值尚未完成的边。
                prefixes = [env]
                for statement in stmt.body:
                    normal = self.block([statement], prefixes[-1]).get("next")
                    if normal is None:
                        break
                    prefixes.append(normal)
                paths = self.block(stmt.body, env)
                normal = paths.pop("next", None)
                caught = merge_states(*prefixes, *paths.values())
                results = [paths]
                if normal is not None:
                    results.append(self.block(stmt.orelse, normal))
                for handler in stmt.handlers:
                    arm = caught.copy()
                    if handler.name is not None:
                        arm.pop(handler.name, None)
                    result = self.block(handler.body, arm)
                    for state in result.values():
                        state.pop(handler.name, None)
                    results.append(result)
                joined = {}
                for result in results:
                    for kind, state in result.items():
                        joined[kind] = merge_states(joined.get(kind, {}), state)
                env = None
                for kind, state in joined.items():
                    final = follow(stmt.finalbody, state)
                    if final is not None:
                        if kind == "next":
                            env = final
                        else:
                            stop(kind, final)
            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
                head = env.copy()
                while True:
                    test = head.copy()
                    if isinstance(stmt, ast.While):
                        condition = self.value(stmt.test, test)
                        if any(o.kind in ("local", "read") for o in condition):
                            if self.yield_positions(stmt.body):
                                self.while_bodies.update((span(part), self.yield_positions(stmt.body))
                                                         for part in stmt.body)
                    else:
                        iterator = self.value(stmt.iter, test)
                        position = span(stmt if isinstance(stmt, ast.AsyncFor) else stmt.iter)
                        self.iterators.add(position)
                        self.iteration_targets.update(span(target) for target in ast.walk(stmt.target)
                                                      if isinstance(target, ast.Name))
                        if self.yield_positions(stmt.body):
                            self.local_iterators[position] = self.yield_positions(stmt.body)
                        self.bind(stmt.target, self.bridge(iterator, position, iterates=True), test)
                    body = self.block(stmt.body, test)
                    new = merge_states(env, *(body[k] for k in ("next", "continue") if k in body))
                    if new == head:
                        break
                    head = new
                for kind in ("return", "raise"):
                    if kind in body:
                        stop(kind, body[kind])
                paths = [follow(stmt.orelse, head), body.get("break")]
                env = merge_states(*(p for p in paths if p is not None)) if any(p is not None for p in paths) else None
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    self.value(item.context_expr, env)
                    if item.optional_vars is not None:
                        self.bind(item.optional_vars, frozenset({Source("read", span(item.context_expr))}), env)
                env = follow(stmt.body, env)
            elif isinstance(stmt, ast.Delete):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        env.pop(target.id, None)
            elif isinstance(stmt, (*FUNCTIONS, ast.ClassDef)):
                env[stmt.name] = frozenset({Source("local", span(stmt))})
            elif isinstance(stmt, ast.Expr):
                self.value(stmt.value, env)
        if env is not None:
            stop("next", env)
        return transfers


# 只剔除编译后没有可执行工作的桩；Python 3.12/3.14 对 None
# 返回和生成器入口的指令组合不同。
def live_body(code):
    scaffold = {"RESUME", "RETURN_GENERATOR", "POP_TOP", "COPY_FREE_VARS", "MAKE_CELL", "NOP",
                "CACHE", "RETURN_VALUE", "RETURN_CONST", "NOT_TAKEN", "RERAISE"}
    return any(i.opname not in scaffold and not (i.opname == "LOAD_CONST" and i.argval is None or
               i.opname == "CALL_INTRINSIC_1" and i.argrepr == "INTRINSIC_STOPITERATION_ERROR")
               for i in dis.get_instructions(code))


class Exports:
    def __init__(self, path, require_body=False):
        self.require_body = require_body
        self.path, self.module = str(Path(path).resolve()), module(path)
        raw = Path(path).read_bytes()
        declarations = list(ast.walk(ast.parse(raw, path)))
        functions = {}
        for node in declarations:
            if isinstance(node, ast.Lambda):
                functions.setdefault((node.lineno, "<lambda>"), []).append(node)
            elif require_body and guarded_stream(node):
                functions.setdefault((node.lineno, "<genexpr>"), []).append(node)
            elif isinstance(node, FUNCTIONS) and (not require_body or substantive(node)):
                functions.setdefault((line(node), node.name), []).append(node)
        classes = {(line(node), node.name) for node in declarations if isinstance(node, ast.ClassDef)}
        codes = list(code_objects(compile(raw, self.path, "exec")))
        self.definitions = {c for c in codes if (c.co_firstlineno, c.co_name) in functions and (not require_body or live_body(c))}
        self.classes = {c for c in codes if (c.co_firstlineno, c.co_name) in classes}
        self.shapes, self.flows = {}, {}
        for code in self.definitions:
            candidates = functions[code.co_firstlineno, code.co_name]
            if len(candidates) != 1 and code.co_name in ("<lambda>", "<genexpr>"):
                # 同行的多个表达式用实际结果操作数位置区分。
                positions = set(code.co_positions())
                candidates = [n for n in candidates if span(n.body if isinstance(n, ast.Lambda) else n.elt) in positions]
            if len(candidates) == 1:
                if require_body:
                    self.flows[code] = ExitFlow(candidates[0], code)
                else:
                    self.shapes[code] = production_shape(candidates[0])

    def owns_frame(self, frame):
        return (frame.f_globals is self.globals and frame.f_code.co_filename == self.path and
                frame.f_code in self.definitions)

    def wrapper(self, fn):
        if "__wrapped__" in vars(fn):
            return True
        plan = self.shapes.get(fn.__code__, ORDINARY_PRODUCTION)
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
            return Binding(key, member, signature, owner, wrapper=not self.require_body and self.wrapper(fn),
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
wait_infrastructure = {asyncio.BaseEventLoop._asyncgen_firstiter_hook.__code__}


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

    wait_infrastructure.add(ObservedAwait.__await__.__code__)

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


# 不调用被验对象的 __eq__、__repr__、__iter__ 或属性钩子。内建容器
# 通过自身的描述符读出结构；普通实例的字典及槽同样读实际存储。
ATOMIC_TYPES = (type(None), bool, int, float, complex, str, bytes, type(Ellipsis), type(NotImplemented))


def snapshot(root):
    seen = {}

    def take(value):
        cls = type(value)
        if cls in ATOMIC_TYPES:
            if cls is float:
                return (cls, float.hex(value))
            if cls is complex:
                return (cls, float.hex(value.real), float.hex(value.imag))
            return (cls, value)
        identity = id(value)
        if identity in seen:
            return (identity,)
        seen[identity] = value
        mro = type.__getattribute__(cls, "__mro__")
        if any(kind is base for kind in (type, FunctionType, MethodType, CodeType, GeneratorType,
                                        AsyncGeneratorType, CoroutineType) for base in mro):
            return (identity, id(cls))
        payload = ()
        for kind, reader in ((list, list.__iter__), (tuple, tuple.__iter__), (set, set.__iter__),
                             (frozenset, frozenset.__iter__)):
            if any(kind is base for base in mro):
                parts = map(take, reader(value))
                payload = frozenset(parts) if kind in (set, frozenset) else tuple(parts)
                break
        if any(dict is base for base in mro):
            payload = tuple((take(k), take(v)) for k, v in dict.items(value))
        elif any(bytearray is base for base in mro):
            payload = bytes(bytearray.__iter__(value))
        fields = []
        for owner in mro:
            for name, descriptor in type.__getattribute__(owner, "__dict__").items():
                if type(descriptor) is MemberDescriptorType or (
                        name == "__dict__" and type(descriptor) is GetSetDescriptorType):
                    try:
                        field = descriptor.__get__(value, cls)
                    except AttributeError:
                        continue
                    fields.append((id(descriptor), take(field)))
        return (identity, id(cls), payload, tuple(fields))

    # 只比较结构；同时保留被观察的身份，避免调用间复用对象地址。
    state = take(root)
    return state, seen


Output = namedtuple("Output", "value attempt gate unchanged", defaults=(None, False))


class Delegation:
    def __init__(self, owner):
        self.owner = owner
        self.calls = {}  # 实际进入的 Python 帧；None 表示外来实现或空桩。
        self.values = {}
        self.delayed = False
        self.projected = False
        self.predicate_inputs = {}
        self.clock = owner.clock


class ForwardCall:
    def __init__(self, call, task, scopes, samples, bound, flow, parent):
        self.call, self.task, self.scopes = call, task, scopes
        self.samples, self.bound, self.flow = samples, bound, flow
        self.clock, self.executed, self.attempts = 0, {}, {}
        self.outputs = []
        self.pending_exit = None
        self.pending_write = None
        self.bound_sources, self.exit_reads = {}, {}
        self.iterated = False
        self.filtered, self.completed_filters = {}, set()
        self.iteration_clock = 0
        self.predicate_control_inputs = set()
        self.child_returns = {}
        # 委托帧也能接到上层已经取得的对象，例如 lambda(Box(raw))。
        # 拷贝回执而非共享累加表，避免随后同帧或并发调用污染本次判断。
        self.inherited_returns = dict(parent.inherited_returns) if parent is not None else {}
        if parent is not None:
            for key, entries in parent.child_returns.items():
                self.inherited_returns[key] = (*self.inherited_returns.get(key, ()), *entries)

    def remember(self, value, visit):
        if type(value) in ATOMIC_TYPES:
            return
        proved_here = visit is not None and any(
            output.value is value and not output.unchanged and output.gate is None and
            (output.attempt is None or not output.attempt.calls and not output.attempt.delayed)
            for output in visit.outputs
        )
        if not proved_here:
            self.child_returns.setdefault(id(value), []).append(snapshot(value))
        if visit is not None:
            # 外来对象也可能嵌在本地叶返回的容器内。容器的本地
            # 实现不能替其中原样转交的外来元素作证。
            for key, entries in visit.child_returns.items():
                self.child_returns.setdefault(key, []).extend(entries)

    def identity(self, value):
        identity = id(value)
        before = (*self.inherited_returns.get(identity, ()), *self.child_returns.get(identity, ()))
        if not before:
            return False, False
        after, _ = snapshot(value)
        unchanged = any(state == after for state, _ in before)
        return unchanged, not unchanged

    def commit_write(self, frame):
        # INSTRUCTION 发生在 STORE 之前。下一条指令读到的是实际选中
        # 的赋值，而非其它分支也已计算、却没有赋给这个变量的值。
        if self.pending_write is not None:
            name, alias, sources = self.pending_write
            self.pending_write = None
            value = frame.f_locals.get(name, frame.f_globals.get(name, MISSING))
            if alias in self.bound_sources:
                self.bound_sources[name] = self.bound_sources[alias]
            else:
                self.bound_sources[name] = self.source(sources, value, storing=True)

    def opcode(self, frame, offset):
        self.commit_write(frame)
        op, position, _ = self.flow.instructions.get(offset, (None, None, None))
        self.clock += 1
        if position in self.flow.positions or position in self.flow.scheduled:
            self.executed[position] = self.clock
        if op not in ("RETURN_VALUE", "RETURN_CONST", "YIELD_VALUE"):
            for key in self.flow.operands.get(position, ()):
                if self.flow.exits[key].kind == "return":
                    self.pending_exit = key
                name = self.flow.names.get(position)
                self.exit_reads[key] = self.bound_sources.get(name)
        if op is not None and op.startswith("STORE_") and position in self.flow.writes:
            self.pending_write = self.flow.writes[position]
        if op in ("CALL", "CALL_KW", "CALL_FUNCTION_EX") and position in self.flow.calls:
            self.attempts[position] = Delegation(self)
        self.iterated |= offset in self.flow.iteration_offsets
        self.predicate_control_inputs.update(self.flow.predicate_controls.get(offset, ()))
        if offset in self.flow.advance_offsets:
            self.iteration_clock = self.clock
            self.filtered.clear()
        for predicate in self.flow.filter_offsets.get(offset, ()):
            matching = tuple(self.attempts[key] for key in sorted(predicate.calls) if key in self.attempts
                             and self.attempts[key].clock > self.iteration_clock)
            if matching or predicate.reads_item and not predicate.calls:
                self.filtered[predicate] = matching
                self.completed_filters.add(matching)

    def predicate_inputs(self, frame, flow, position):
        bindings = {}
        locals_ = frame.f_locals
        caller = self.call.frame.f_locals
        call = self.flow.call_nodes.get(position)
        for predicate in self.flow.filters:
            if position not in predicate.calls:
                continue
            items = [(name, caller[name]) for name in predicate.item_names if name in caller]
            names = frozenset(name for name, value in items)
            dependency = set()
            captured = flow.predicate_inputs.intersection(frame.f_code.co_freevars)
            for name, value in items:
                if name in captured and locals_.get(name, MISSING) is value:
                    dependency.add(name)
            if call is not None and not any(isinstance(arg, ast.Starred) for arg in call.args):
                def depends(expr):
                    return any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(expr))
                code = frame.f_code
                names_ = code.co_varnames[:code.co_argcount]
                if isinstance(call.func, ast.Attribute) and names_ and names_[0] in ("self", "cls"):
                    names_ = names_[1:]
                for target, arg in zip(names_, call.args):
                    if target in flow.predicate_inputs and depends(arg):
                        dependency.add(target)
                for keyword in call.keywords:
                    if keyword.arg in flow.predicate_inputs and depends(keyword.value):
                        dependency.add(keyword.arg)
            bindings[predicate] = dependency
        return bindings

    def attempts_at(self, position, *, schedules=False):
        # 同一个消费点可接到多个分支的延迟体；取本次实际创建的最近来源。
        sites = self.flow.scheduling.get(position, ()) if schedules else self.flow.invoking.get(position, ())
        return sorted((key for key in sites if key in self.attempts),
                      key=lambda key: self.executed.get(key, 0), reverse=True)

    def source(self, origins, value, *, storing=False):
        candidates = []
        for source in origins:
            clock = self.executed.get(source.position, 0)
            if source.position is not None and not clock and not (storing and source.slots is not None):
                continue
            same = False
            if source.site is not None:
                site = source.site
                attempt = self.attempts.get(site.call)
                if attempt is None:
                    continue
                same = any(v is value for v in attempt.values.values())
                if not same and attempt.values and not site.consumes and not attempt.delayed:
                    continue
                if not clock:
                    clock = self.executed.get(site.call, 0)
            candidates.append((same, clock, source))
        return max(candidates, key=lambda row: row[:2])[2] if candidates else None

    def produced(self, frame, arg, normal):
        self.commit_write(frame)
        op, position, _ = self.flow.instructions.get(frame.f_lasti, (None, None, None))
        exit_ = self.flow.exits.get(position)
        stream = frame.f_code.co_flags & (inspect.CO_GENERATOR | inspect.CO_ASYNC_GENERATOR)
        if op == "YIELD_VALUE":
            if exit_ is None or exit_.kind not in ("yield", "delegate"):
                return  # await/async for 的挂起不是对外产出。
        elif normal:
            if stream:
                # 裸 return / return None 和自然耗尽都只结算已经执行的工作。
                if self.iterated:
                    self.outputs.append(Output(MISSING, None))
                for gates in self.completed_filters:
                    self.outputs.append(Output(MISSING, None, gates))
                for key in self.flow.iterated_calls:
                    attempt = self.attempts.get(key)
                    if attempt is not None and attempt.calls:
                        self.outputs.append(Output(MISSING, attempt))
                return
            if exit_ is None or exit_.kind != "return":
                # try:return 的实际 RETURN_VALUE 可落在 finally 收尾指令上。
                exit_ = self.flow.exits.get(self.pending_exit)
        else:
            return
        unchanged, modified = self.identity(arg) if normal else (False, False)
        # 调生成器/协程函数创建对象时还没有 Python 帧返回。若出口
        # 原样交回未驱动的外部延迟体，直接核对该对象所带的真实帧。
        deferred_attr = DEFERRED_FRAMES.get(type(arg)) if normal else None
        if deferred_attr and (child := getattr(arg, deferred_attr)) is not None:
            unchanged |= child.f_globals is not frame.f_globals or child.f_code.co_filename != frame.f_code.co_filename
        if modified and not unchanged and not self.flow.scheduled.intersection(self.executed):
            self.outputs.append(Output(arg, None))
            return
        if exit_ is None or op == "RETURN_CONST":
            return
        if op == "YIELD_VALUE" and frame.f_code.co_flags & inspect.CO_ASYNC_GENERATOR and exit_.kind == "yield":
            arg, = gc.get_referents(arg)  # CPython 的 async_generator_wrapped_value。
        for predicate in self.flow.yield_filters.get(exit_.position, ()):
            gates = self.filtered.get(predicate)
            if gates is not None:
                self.outputs.append(Output(arg, None, gates))
        chosen = self.exit_reads.get(exit_.position)
        if chosen is None and len(exit_.operands) == 1:
            chosen = self.bound_sources.get(self.flow.names.get(next(iter(exit_.operands))))
        if chosen is not None and chosen not in exit_.sources:
            # 同一调用在 await / 迭代处换成消费位置，仍是同一来源。
            chosen = next((o for o in exit_.sources if o.site is not None and chosen.site is not None and
                           o.site.call == chosen.site.call), None)
        if chosen is None:
            chosen = self.source(exit_.sources, arg)
        if chosen is None:
            return None
        if chosen.site is not None:
            site = chosen.site
            attempt = self.attempts.get(site.call)
            if attempt is None:
                return None
            if self.flow.scheduled.intersection(self.executed) - site.schedules and not attempt.calls:
                return None   # 没有消费的星号任务不能由另一个内建调用替代。
            attempt.projected |= site.iterates and any(not f.f_code.co_flags & DEFERRED_FLAGS for f in attempt.calls)
            self.outputs.append(Output(arg, attempt, unchanged=unchanged))
            return attempt
        if chosen.kind in ("read", "local") and not unchanged and not self.flow.scheduled.intersection(self.executed):
            self.outputs.append(Output(arg, None))
        return None



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
        self.delegations = {}
        self.resumed = {}
        self.activations = {}
        self.hits = []
        self.monitor_id = None
        self.monitored_codes = {}

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

    def start(self):
        # 只监听已进入的承接帧，用真实 code 限定指令事件；不跟踪 pytest
        # 和生产调用树的每条指令。两个受支持版本均提供这一接口。
        monitor = sys.monitoring
        self.monitor_id = next(tool for tool in (3, 4) if monitor.get_tool(tool) is None)
        monitor.use_tool_id(self.monitor_id, "at18-source")
        monitor.register_callback(self.monitor_id, monitor.events.INSTRUCTION, self.instruction)
        sys.setprofile(self.profile)

    def stop(self):
        sys.setprofile(None)
        if self.monitor_id is not None:
            monitor = sys.monitoring
            for code in self.monitored_codes.values():
                monitor.set_local_events(self.monitor_id, code, 0)
            monitor.register_callback(self.monitor_id, monitor.events.INSTRUCTION, None)
            monitor.free_tool_id(self.monitor_id)
            self.monitor_id = None

    def instruction(self, code, offset):
        frame = sys._getframe(1)
        visit = self.forward_calls.get(frame)
        if visit is not None:
            visit.opcode(frame, offset)

    def delegation(self, frame):
        if frame.f_code in wait_infrastructure or frame.f_code is Trace.instruction.__code__:
            return None
        if frame in self.forward_results:
            return self.forward_results[frame]
        caller = frame.f_back
        if (parent := self.forward_calls.get(caller)) is None:
            return None
        _, position, _ = parent.flow.instructions.get(caller.f_lasti, (None, None, None))
        # CPython 的 profile 回调可能将 f_lasti 留在 CALL 的内联 CACHE。
        if position is None and caller.f_lasti >= 0:
            position = parent.flow.code_positions[caller.f_lasti // 2]
        if frame.f_code in task_creators:
            keys = parent.attempts_at(position, schedules=True)
            if keys:
                value = frame.f_locals.get(task_creators[frame.f_code])
                if type(value) is CoroutineType and value.cr_frame is not None:
                    attempt = parent.attempts[keys[0]]
                    attempt.delayed = True
                    self.forward_results.setdefault(value.cr_frame, attempt)
                return None
        keys = parent.attempts_at(position)
        if not keys:
            return None
        return parent.attempts[keys[0]]

    def handoff(self, arg, attempt):
        if inherits(type(arg), native_task):
            arg = native_task.get_coro(arg)
        attr = DEFERRED_FRAMES.get(type(arg))
        if attr and (child := getattr(arg, attr)) is not None:
            if attempt is not None:
                attempt.delayed = True
            # 外层不能越过内层把同一个延迟体改认成自己的直接实现。
            self.forward_results.setdefault(child, attempt)

    def profile(self, frame, event, arg):
        code = frame.f_code
        if event == "c_call" and code in wait_result_codes and arg.__name__ == "result":
            joined(active.get(), current_task(), (arg.__self__,))
        if event == "return":
            visit = self.forward_calls.get(frame)
            attempt = self.delegations.get(frame)
            parent = self.forward_calls.get(frame.f_back)
            if not (visit is not None or attempt is not None or parent is not None or
                    frame in self.activations or code is RELOAD_CODE):
                return
            normal_return = frame.f_lasti >= 0 and code.co_code[frame.f_lasti] in returns
            if visit is not None:
                selected = visit.produced(frame, arg, normal_return)
                if normal_return:
                    self.handoff(arg, selected)
            elif attempt is not None and normal_return:
                self.handoff(arg, None)
            if parent is not None and normal_return:
                parent.remember(arg, visit)
            if attempt is not None:
                attempt.values[frame] = arg
                if normal_return:
                    self.delegations.pop(frame, None)
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
        attempt = self.delegation(frame)
        parent = attempt.owner if attempt is not None else None
        visit = None
        if ((scopes or parent) and self.targets.owns_frame(frame) and code in self.targets.flows
                and self.production.initialized(frame, constructors=False) and self.targets.initialized(frame)):
            bindings = self.targets.candidates(frame)
            if bindings or parent:
                visit = self.forward_calls.get(frame)
                if visit is None:
                    call = self.call(frame, bindings)
                    samples, bound = self.samples(frame, call, parent) if self.test else (({}, ((), {})), False)
                    visit = self.forward_calls[frame] = ForwardCall(
                        call, current_task(), scopes, samples, bound, self.targets.flows[code], parent)
                    if id(code) not in self.monitored_codes:
                        self.monitored_codes[id(code)] = code
                        sys.monitoring.set_local_events(self.monitor_id, code, sys.monitoring.events.INSTRUCTION)
                if bindings:
                    if frame not in self.wrappers:
                        self.wrappers[frame] = Invocation(wrapper=True)
                    wrapper = self.wrappers[frame]
                    local.append(wrapper)
                    direct = in_test and self.production.initialized(frame)
                    self.hits.append((visit, current_task(), scopes, wrapper, direct))
        if attempt is not None:
            attempt.calls[frame] = visit
            if visit is not None and parent.flow.filters:
                position = next((key for key, value in parent.attempts.items() if value is attempt), None)
                attempt.predicate_inputs[frame] = parent.predicate_inputs(frame, visit.flow, position)
            self.delegations[frame] = attempt
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

        def local_gate(attempt, wrapper, seen):
            for frame, child in attempt.calls.items():
                if child is None:
                    return False
                inputs = set().union(*attempt.predicate_inputs.get(frame, {}).values())
                if not inputs:
                    return False
                value = attempt.values.get(frame, MISSING)
                if not (any(witnesses(child, wrapper, seen, value)) or (
                        type(value) is bool and child.predicate_control_inputs.intersection(inputs)
                        and reachable(wrapper, child.task))):
                    return False
            return True

        def witnesses(visit, wrapper, seen=frozenset(), value=MISSING):
            if visit in seen or self.test_scope and not reachable(self.test_scope, visit.task):
                return
            if not any(s.origin is wrapper and reachable(s, visit.task) for s in (wrapper, *visit.scopes)) and not (
                    visit.task in wrapper.returned and any(reachable(s, visit.task) for s in visit.scopes)):
                return
            for produced, attempt, gates, unchanged in visit.outputs:
                if value is not MISSING and produced is not value:
                    continue
                if gates is not None:
                    # 每个实际执行的 Python 条件调用都必须是本文件的实质
                    # 谓词，且至少一条路径从当前项取值。裸内联判断没有调用。
                    if not gates or (any(a.calls for a in gates) and all(
                            local_gate(a, wrapper, seen | {visit}) for a in gates)):
                        yield (visit.samples,)
                elif attempt is None or not attempt.calls and not attempt.delayed:
                    if not unchanged:
                        yield (visit.samples,)
                elif all(child is not None for child in attempt.calls.values()):
                    for child in attempt.calls.values():
                        if child.call.actual() is not None:
                            expected = MISSING if attempt.delayed or attempt.projected and not unchanged else produced
                            for path in witnesses(child, wrapper, seen | {visit}, expected):
                                yield (visit.samples, *path)

        for root, task, scopes, wrapper, direct in self.hits:
            matched = root.call.matches()
            if not matched or self.test_scope and not reachable(self.test_scope, task):
                continue
            via_public = any(scope is not self.test_scope and not scope.origin.wrapper
                             and reachable(scope, task) and public(scope) for scope in scopes)
            if not via_public and not direct:
                continue
            keys = frozenset(b.key for b in matched)
            for path in witnesses(root, wrapper):
                yield keys, path, via_public

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
            trace.stop()

    try:
        trace.start()
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
