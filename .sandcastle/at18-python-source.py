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
import re
import struct
import sys
from collections import Counter
from contextvars import ContextVar
from itertools import combinations, product
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
        return kind, struct.pack("!d", value)
    if kind is complex:
        return kind, (struct.pack("!d", value.real), struct.pack("!d", value.imag))
    if kind is dict:
        return kind, tuple((sample_key(k), sample_key(v)) for k, v in value.items())
    if kind is list or kind is tuple:
        return kind, tuple(map(sample_key, value))
    if kind is set or kind is frozenset:
        # 不同 NaN 可以同时在同一容器中；归一后仍保留其出现次数。
        return kind, frozenset(Counter(map(sample_key, value)).items())
    return kind, value


def keyword_sample_key(kwargs):
    return tuple((k, sample_key(v)) for k, v in kwargs.items())


POSITIONAL = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
KEYWORD = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
VARIADIC = (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)


def variadic_modes(signature, shapes=()):
    kinds = {param.kind for param in signature.parameters.values()}
    has_kwargs = inspect.Parameter.VAR_KEYWORD in kinds
    has_args = inspect.Parameter.VAR_POSITIONAL in kinds
    if has_kwargs:
        yield "kwargs"
        if inspect.Parameter.POSITIONAL_ONLY in kinds:
            yield "kwargs_shadow"
    # 透明双变参层没有固定槽给具名值定位；只用原见证的位置形状，
    # 不从外来规范或任意具名值的顺序发明位置尾参。
    if has_args and (not has_kwargs or not variadic_only(signature)):
        yield "args"
    if has_args and has_kwargs:
        for args, kwargs in shapes:
            if args and kwargs:
                yield "both", args, kwargs


def arguments(signature, samples, variadic=False):
    args, kwargs, defaults = [], {}, {}
    params = signature.parameters
    extra_args, extra_kwargs = (), {}
    if variadic is True:
        # 诊断调用仍使用原来的单通道解释。
        kinds = {param.kind for param in params.values()}
        variadic = ("kwargs" if inspect.Parameter.VAR_KEYWORD in kinds else
                    "args" if inspect.Parameter.VAR_POSITIONAL in kinds else False)
    if variadic:
        # 仅位置槽占用位置，不会占用同名的 **kwargs 键。
        shadow = variadic == "kwargs_shadow" or type(variadic) is tuple
        fixed = {name for name, param in params.items()
                 if (param.kind in KEYWORD if shadow else param.kind not in VARIADIC)}
        if type(variadic) is tuple:
            _, tail, options = variadic
            extra_args = tuple(map(sample, tail))
            extra_kwargs = {k: sample(v) for k, v in options.items() if k not in fixed}
        else:
            remaining = {k: sample(v) for k, v in samples.items() if k not in fixed}
            if variadic == "args":
                extra_args = tuple(remaining.values())
            else:
                extra_kwargs = remaining

    pos_kinds = POSITIONAL if extra_args else (inspect.Parameter.POSITIONAL_ONLY,)
    kw_kinds = (inspect.Parameter.KEYWORD_ONLY,) if extra_args else KEYWORD
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
    return bool(signature.parameters) and all(p.kind in VARIADIC for p in signature.parameters.values())


def has_variadic(signature):
    return any(p.kind in VARIADIC for p in signature.parameters.values())


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


def mro_member(cls, name):
    for base in type.__getattribute__(cls, "__mro__"):
        members = type.__dict__["__dict__"].__get__(base)
        if name in members:
            return base, members[name]
    return None, None


def choice_value_key(value, default_refs):
    try:
        plain = sample(value)
    except ValueError:
        # 非纯数据的生产默认值只按身份比较；保活以免 id 被复用。
        identity = id(value)
        default_refs[identity] = value
        return MISSING, identity
    return sample_key(plain)


def argument_choice(signature, args, kwargs, defaults, default_refs):
    # 先校验全部来自测试侧的实参，避免非纯测试对象进入 bind 后落入默认值身份分支。
    for i, value in enumerate(args):
        if i not in defaults:
            sample(value)
    for value in kwargs.values():
        sample(value)
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    params = signature.parameters
    items = []
    for name, value in bound.arguments.items():
        kind = params[name].kind
        if kind is inspect.Parameter.VAR_POSITIONAL:
            key = tuple(choice_value_key(item, default_refs) for item in value)
        elif kind is inspect.Parameter.VAR_KEYWORD:
            key = tuple((k, sample_key(sample(v))) for k, v in value.items())
        else:
            key = choice_value_key(value, default_refs)
        items.append((name, key))
    return tuple(items)


def copy_arguments(args, kwargs, defaults):
    return (tuple(v if i in defaults else sample(v) for i, v in enumerate(args)),
            {k: sample(v) for k, v in kwargs.items()})


def ctor_receiver_count(hook_name, member):
    if hook_name == "__new__":
        return 2 if type(member) is classmethod else 1
    return 0 if type(member) in (staticmethod, MethodType) else 1


def strip_receivers(signature, count):
    slots = list(signature.parameters.values())
    for _ in range(count):
        if not slots:
            return None
        kind = slots[0].kind
        if kind in POSITIONAL:
            slots.pop(0)
        elif kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        else:
            return None
    return signature.replace(parameters=slots)


def merge_kwonly(signature, extra_kwonly):
    added = [param for name, param in extra_kwonly.items() if name not in signature.parameters]
    if not added:
        return None
    params = list(signature.parameters.values())
    if params and params[-1].kind is inspect.Parameter.VAR_KEYWORD:
        params = [*params[:-1], *added, params[-1]]
    else:
        params = [*params, *added]
    try:
        return signature.replace(parameters=params)
    except ValueError:
        return None


def strip_kwonly(signature, names):
    params = signature.parameters
    kept = [p for name, p in params.items()
            if p.kind is not inspect.Parameter.KEYWORD_ONLY or name not in names]
    return signature if len(kept) == len(params) else signature.replace(parameters=kept)


def strip_params(signature, names):
    params = signature.parameters
    kept = [p for name, p in params.items() if name not in names or p.kind not in (
        inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    return signature if len(kept) == len(params) else signature.replace(parameters=kept)


def strip_variadics(signature):
    return signature.replace(parameters=[p for p in signature.parameters.values() if p.kind not in VARIADIC])


KW_DROP = re.compile(r"[^\n]+\(\) got (?:multiple values for (?:keyword )?argument|an unexpected keyword argument) '([^']+)'")
KW_POSONLY = re.compile(r"[^\n]+\(\) got some positional-only arguments passed as keyword arguments: '([^',]+(?:, [^',]+)*)'")
KW_NEED = re.compile(r"[^\n]+\(\) missing ([1-9][0-9]*) required (?:keyword-only|positional) (argument|arguments): (.+)")
KW_NAME = r"'[^']+'"
KW_LIST = re.compile(rf"{KW_NAME}(?: and {KW_NAME}|(?:, {KW_NAME})+, and {KW_NAME})?")


def parse_kw_type_error(exc, extra_set):
    # 诊断只用于安排实参；是否覆盖仍由实际公开调用的轨迹决定。
    if type(exc) is not TypeError or len(exc.args) != 1 or type(exc.args[0]) is not str:
        return None
    msg = exc.args[0]
    if match := KW_DROP.fullmatch(msg):
        name = match[1]
        if name in extra_set:
            return "drop", (name,)
    if match := KW_POSONLY.fullmatch(msg):
        dropped = tuple(name for name in match[1].split(", ") if name in extra_set)
        if dropped:
            return "drop", dropped
    if (match := KW_NEED.fullmatch(msg)) and KW_LIST.fullmatch(match[3]):
        names = tuple(re.findall(KW_NAME, match[3]))
        if str(len(names)) == match[1] and (len(names) == 1) == (match[2] == "argument"):
            missing = tuple(name[1:-1] for name in names if name[1:-1] in extra_set)
            if missing:
                return "need", missing


def peel_chain(layers, args, kwargs, default_refs):
    parts, cur_args, cur_kwargs = [], tuple(args), dict(kwargs)
    pos_offset = 0
    pos_default_matches, kw_default_matches = set(), set()
    concrete = False
    for sig in layers:
        try:
            bound = sig.bind(*cur_args, **cur_kwargs)
        except TypeError:
            break
        bound.apply_defaults()
        params = sig.parameters
        pos_params = [p for p in params.values() if p.kind in POSITIONAL]
        next_args, next_kwargs, var_pos, var_kw = (), {}, False, False
        layer_items = []
        for name, value in bound.arguments.items():
            kind = params[name].kind
            if kind is inspect.Parameter.VAR_POSITIONAL:
                next_args, var_pos = value, True
            elif kind is inspect.Parameter.VAR_KEYWORD:
                next_kwargs, var_kw = value, True
            else:
                layer_items.append((name, choice_value_key(value, default_refs)))
        consumed_pos = len(cur_args) - len(next_args) if var_pos else len(cur_args)
        for j in range(consumed_pos):
            param = pos_params[j]
            if (param.default is not inspect.Parameter.empty and
                    choice_value_key(cur_args[j], default_refs) == choice_value_key(param.default, default_refs)):
                pos_default_matches.add(pos_offset + j)
        for k, v in cur_kwargs.items():
            param = params.get(k)
            if (param is not None and
                    param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY) and
                    param.default is not inspect.Parameter.empty and
                    choice_value_key(v, default_refs) == choice_value_key(param.default, default_refs)):
                kw_default_matches.add(k)
        pos_offset += consumed_pos
        parts.append(tuple(layer_items))
        if not (var_pos or var_kw):
            concrete = True
            cur_args, cur_kwargs = (), {}
            break
        cur_args, cur_kwargs = next_args, next_kwargs
    trailing_default_pos = 0
    i = len(args) - 1
    while i >= 0 and i in pos_default_matches:
        trailing_default_pos += 1
        i -= 1
    if concrete:
        return True, tuple(parts), (), (), pos_offset, trailing_default_pos, frozenset(kw_default_matches)
    res_args = tuple(choice_value_key(item, default_refs) for item in cur_args)
    res_kwargs = tuple((k, choice_value_key(v, default_refs)) for k, v in cur_kwargs.items())
    return False, tuple(parts), res_args, res_kwargs, pos_offset, trailing_default_pos, frozenset(kw_default_matches)


def ctor_choice(primary_layers, secondary_layers, args, kwargs, defaults, default_refs):
    # 先校验全部来自测试侧的实参，避免非纯测试对象进入 bind 后落入默认值身份分支。
    for i, value in enumerate(args):
        if i not in defaults:
            sample(value)
    for value in kwargs.values():
        sample(value)
    c1, p1, ra1, rk1, rp1, td1, dkw1 = peel_chain(primary_layers, args, kwargs, default_refs)
    if not secondary_layers:
        return c1, p1, ra1, rk1
    c2, p2, ra2, rk2, rp2, td2, dkw2 = peel_chain(secondary_layers, args, kwargs, default_refs)
    limit1 = len(args) - td2
    ra1 = tuple(v for m, v in enumerate(ra1) if rp1 + m < limit1)
    rk1 = tuple((k, v) for k, v in rk1 if k not in dkw2)
    limit2 = len(args) - td1
    ra2 = tuple(v for m, v in enumerate(ra2) if rp2 + m < limit2)
    rk2 = tuple((k, v) for k, v in rk2 if k not in dkw1)
    return (c1, p1, ra1, rk1), (c2, p2, ra2, rk2)


CTOR_PROBE_TIERS = ((False, False), (False, True), (True, None))



class Binding:
    def __init__(self, key, member, chain, owner=None, ctor_chains=((), ()), ctor_shapes=True):
        self.key, self.member, self.chain, self.owner = key, member, chain, owner
        self.ctor_chains = ctor_chains if len(ctor_chains) == 2 else ((), ())
        self.ctor_shapes = ctor_shapes
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

    @staticmethod
    def ctor_target_signatures(target, strip, guaranteed, observed_names, after_class_hook=False):
        try:
            params = inspect.signature(target, follow_wrapped=False)
        except (ValueError, TypeError):
            return ()
        if variadic_only(params):
            return ()
        if strip == 0:
            return ((params, False),)
        clipped = strip_receivers(params, strip)
        if guaranteed:
            return () if (clipped is None or variadic_only(clipped)) else ((clipped, True),)
        slots = tuple(params.parameters.values())
        if not slots or slots[0].kind not in POSITIONAL:
            return ((params, False),)
        full, stripped = (params, False), (clipped, True)
        can_strip = clipped is not None and not variadic_only(clipped)
        if slots[0].default is not inspect.Parameter.empty or slots[0].name in observed_names:
            if not can_strip:
                return (full,)
            return (full, stripped) if after_class_hook or not clipped.parameters else (stripped, full)
        return (stripped, full) if can_strip else (None, full)

    def ctor_plan(self, public, observed_names):
        primary_targets, secondary_targets = self.ctor_chains
        primary_entries = [
            self.ctor_target_signatures(target, strip, guaranteed, observed_names, after_class_hook)
            for target, strip, guaranteed, after_class_hook in primary_targets
        ]
        secondary_entries = [
            self.ctor_target_signatures(target, strip, guaranteed, observed_names, after_class_hook)
            for target, strip, guaranteed, after_class_hook in secondary_targets
        ]
        nonempty_primary = [sigs for sigs in primary_entries if sigs]
        nonempty_secondary = [sigs for sigs in secondary_entries if sigs]
        def side_variants(prefix, entries):
            layers = (*prefix, *(sigs[0][0] for sigs in entries if sigs[0] is not None))
            polarities = tuple(sigs[0] is None or sigs[0][1] for sigs in entries if len(sigs) > 1)
            ordinary = tuple(sigs[0] is not None for sigs in entries if len(sigs) > 1)

            def ordinary_polarities(values):
                return tuple(value for value, keep in zip(values, ordinary) if keep)

            variants, alternatives = [(layers, polarities, ordinary_polarities(polarities))], {}
            # 同一侧只替换一层，避免包装深度使候选数量指数增长。
            pos, polarity_offset = len(prefix), 0
            for offset, sigs in enumerate(entries):
                # 主解释透明时不进入剥层；备选按原相对顺序插入完整签名。
                end = pos + (sigs[0] is not None)
                if len(sigs) > 1:
                    sig, is_clipped = sigs[1]
                    alt_layers = (*layers[:pos], sig, *layers[end:])
                    alt_polarities = (*polarities[:polarity_offset], is_clipped, *polarities[polarity_offset + 1:])
                    alternatives[offset] = len(variants)
                    normal = ordinary_polarities(alt_polarities) if sigs[0] is not None else None
                    variants.append((alt_layers, alt_polarities, normal))
                    polarity_offset += 1
                pos = end
            return variants, alternatives

        primary_variants, primary_alts = side_variants((public,), nonempty_primary)
        secondary_variants, secondary_alts = side_variants((), nonempty_secondary)
        default_primary, default_secondary = primary_variants[0][0], secondary_variants[0][0]

        def polarity_rank(left, right):
            left, right = set(left), set(right)
            if not left or not right or left == right and len(left) == 1:
                return 0
            return 1 if left & right else 2

        def joint_rank(pair):
            p, s = pair
            _, left, normal_left = primary_variants[p]
            _, right, normal_right = secondary_variants[s]
            # 补入的纯备选只影响备选配对，不改变主姿态原有的顺序或归一。
            if normal_left is None or normal_right is None:
                return 1, polarity_rank(left, right)
            return 0, polarity_rank(normal_left, normal_right)

        joint = sorted(product(range(len(primary_variants)), range(len(secondary_variants))), key=joint_rank)
        joint_index = {pair: i for i, pair in enumerate(joint)}
        layer_variants = [(primary_variants[p][0], secondary_variants[s][0]) for p, s in joint]
        primary_count = sum(v[2] is not None for v in primary_variants)
        ordinary_count = primary_count * sum(v[2] is not None for v in secondary_variants)

        def aligned(variants, is_clipped, alternate):
            def rank(i):
                polarities = variants[i][1 if alternate else 2]
                return (1, 0) if polarities is None else (0, polarities.count(not is_clipped))
            return min(range(len(variants)), key=rank)

        def tagged(entries, alts, other, primary):
            for offset, sigs in enumerate(entries):
                candidates = []
                for sig_idx, candidate in enumerate(sigs):
                    if candidate is None:
                        continue
                    sig, is_clipped = candidate
                    if len(sigs) == 1:
                        variant = None if not primary and primary_count > 1 else joint_index[0, 0]
                    else:
                        own = alts[offset] if sig_idx else 0
                        peer = aligned(other, is_clipped, sig_idx > 0)
                        variant = joint_index[own, peer] if primary else joint_index[peer, own]
                    candidates.append((sig, variant, sig_idx > 0))
                yield candidates

        primary_tagged = list(tagged(nonempty_primary, primary_alts, secondary_variants, True))
        secondary_tagged = list(tagged(nonempty_secondary, secondary_alts, primary_variants, False))

        public_has_varkw = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in public.parameters.values()
        )
        public_kw_names = {name for name, p in public.parameters.items() if p.kind in KEYWORD}
        public_required_kw = {
            name for name, p in public.parameters.items()
            if p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is inspect.Parameter.empty
        }
        public_kwonly = {
            name: param for name, param in public.parameters.items()
            if param.kind is inspect.Parameter.KEYWORD_ONLY and (name in observed_names or name in public_required_kw)
        }
        all_kwonly = {}
        for sig in (*default_primary, *default_secondary):
            for name, param in sig.parameters.items():
                if (param.kind is inspect.Parameter.KEYWORD_ONLY and name not in all_kwonly and
                        (public_has_varkw or name in public_kw_names) and
                        (name in observed_names or name in public_required_kw)):
                    all_kwonly[name] = param
        extra_kwonly = {name: param for name, param in all_kwonly.items() if name not in public_kwonly}
        full_kwonly = {**public_kwonly, **extra_kwonly}
        extra_recover = dict(extra_kwonly)
        # 新同名键只参与备用阶段，不能改变主阶段成功与失败的缓存键。
        ordinary_recover = set(extra_recover)
        if public_has_varkw:
            for sig in (*default_primary, *default_secondary):
                for name, param in sig.parameters.items():
                    if (name not in extra_recover and name not in public_kw_names and param.kind in KEYWORD and
                            (name in observed_names or param.default is inspect.Parameter.empty)):
                        extra_recover[name] = (param if param.kind is inspect.Parameter.KEYWORD_ONLY else
                                               param.replace(kind=inspect.Parameter.KEYWORD_ONLY))
                        public_param = public.parameters.get(name)
                        if public_param is None or public_param.kind is not inspect.Parameter.POSITIONAL_ONLY:
                            ordinary_recover.add(name)
        pairs, recovery, recovery_keys = [], [], set()
        generic = has_variadic(public)

        def add_recovery(base_sig, variant):
            # Signature.__hash__ 会访问默认值；形状只按原生名、种类和身份去重。
            key = variant, tuple((p.name, p.kind, id(p.default)) for p in base_sig.parameters.values())
            if key not in recovery_keys:
                recovery_keys.add(key)
                recovery.append((base_sig, variant))

        def add(sig, variant=None, alternate=False):
            if not public_has_varkw:
                sig = strip_kwonly(sig, sig.parameters.keys() - public_kw_names)
            pairs.append((sig, variant, alternate))
            if variadic_only(sig):
                return
            for kw_set in ((public_kwonly, full_kwonly) if extra_kwonly else (public_kwonly,)):
                merged = merge_kwonly(sig, kw_set)
                if merged is not None:
                    pairs.append((merged, variant, alternate))
            if extra_recover:
                add_recovery(strip_params(sig, extra_recover), variant)

        if not generic:
            add(public)
        for tagged_sigs in reversed(primary_tagged):
            for candidate in tagged_sigs:
                add(*candidate)
        for tagged_sigs in reversed(secondary_tagged):
            for candidate in tagged_sigs:
                add(*candidate)
        if generic:
            add(public)
        if public_has_varkw and extra_recover:
            add_recovery(strip_variadics(public), None)
        return layer_variants, pairs, (recovery, public_kwonly, extra_recover, ordinary_recover), ordinary_count

    def callables(self, instances, views, variadic=None, alternate=None, ctor_errors=None, shapes=()):
        if self.owner is None:
            if not variadic and alternate is not True:
                yield self.member
            return
        if type(self.member) in (staticmethod, classmethod):
            if not variadic and alternate is not True:
                yield self.member.__get__(None, self.owner)
            return
        try:
            public = inspect.signature(self.owner, follow_wrapped=False)
        except (ValueError, TypeError):
            return
        shapes = shapes if self.ctor_shapes else ()
        observed_names = {name for view in views for name in view}
        layer_variants, pairs, recover_plan, ordinary_count = self.ctor_plan(public, observed_names)
        recovery, public_kwonly, extra_recover, ordinary_recover = recover_plan
        seen, default_refs = set(), {}
        extra_set = set(extra_recover)
        if ctor_errors is None:
            ctor_errors = {}

        def convergence_score(choice, has_secondary):
            if not has_secondary:
                return int(choice[0])
            return int(choice[0][0]) + int(choice[1][0])

        def pick_ctor_key(variant, args, kwargs, defaults):
            if variant is not None:
                p_layers, s_layers = layer_variants[variant]
                return variant, ctor_choice(p_layers, s_layers, args, kwargs, defaults, default_refs)
            p0, s0 = layer_variants[0]
            best_idx = 0
            best_choice = ctor_choice(p0, s0, args, kwargs, defaults, default_refs)
            best_score = convergence_score(best_choice, bool(s0))
            max_score = 2 if s0 else 1
            if best_score < max_score:
                for alt_idx in range(1, ordinary_count):
                    pa, sa = layer_variants[alt_idx]
                    alt_choice = ctor_choice(pa, sa, args, kwargs, defaults, default_refs)
                    alt_score = convergence_score(alt_choice, bool(sa))
                    if alt_score > best_score:
                        best_idx, best_choice, best_score = alt_idx, alt_choice, alt_score
                        if best_score == max_score:
                            break
            return best_idx, best_choice

        def resolve_args(args, kwargs, defaults, variant, error_keys):
            try:
                public.bind(*args, **kwargs)
                ctor_key = pick_ctor_key(variant, args, kwargs, defaults)
            except (ValueError, TypeError):
                return False, None
            key = id(self.owner), ctor_key
            raw_key = None
            if len(layer_variants) > 1 or error_keys:
                raw_key = (
                    id(self.owner),
                    MISSING,
                    tuple(choice_value_key(v, default_refs) for v in args),
                    tuple((k, choice_value_key(v, default_refs)) for k, v in kwargs.items()),
                )
            # 成功仍按绑定后默认值归一；失败若含可恢复键，按原实参记录。
            # 显式传默认值可能与外层注入冲突，而同一键省略时可以成功。
            failed_key = raw_key if error_keys else key
            if failed_key in instances and instances[failed_key] is None:
                return False, ctor_errors.get(failed_key)
            if key not in instances:
                if raw_key is not None and raw_key in instances:
                    inst = instances[raw_key]
                    if inst is None:
                        return False, ctor_errors.get(raw_key)
                else:
                    ctor_args, ctor_kwargs = copy_arguments(args, kwargs, defaults)
                    try:
                        inst = self.owner(*ctor_args, **ctor_kwargs)
                    except (Exception, SystemExit) as exc:
                        tag = parse_kw_type_error(exc, error_keys) if error_keys else None
                        instances[failed_key] = None
                        if raw_key is not None:
                            instances[raw_key] = None
                        if tag is not None:
                            ctor_errors[failed_key] = tag
                        return False, tag
                instances[key] = inst
            inst = instances[key]
            if inst is None:
                return False, None
            if raw_key is not None:
                instances.setdefault(raw_key, inst)
            if ctor_key not in seen:
                seen.add(ctor_key)
                yield self.member.__get__(inst, self.owner)
            return True, None

        def resolve(sig, view, mode, variant, shadow_kw=None, error_keys=ordinary_recover):
            try:
                args, kwargs, defaults = arguments(sig, view, mode)
                if shadow_kw:
                    for name, param in shadow_kw.items():
                        if name in view:
                            kwargs[name] = sample(view[name])
                        elif param.default is inspect.Parameter.empty:
                            kwargs[name] = None
            except (ValueError, TypeError):
                return False, None
            return (yield from resolve_args(args, kwargs, defaults, variant, error_keys))

        def recover_kwonly(pair, view):
            base_sig, variant = pair
            extra = tuple(extra_recover)
            tested = {}

            def attempt(names):
                if names not in tested:
                    kw_set = {**public_kwonly, **{name: extra_recover[name] for name in names}}
                    sig = merge_kwonly(base_sig, kw_set)
                    shadow = {name: param for name, param in kw_set.items()
                              if (slot := base_sig.parameters.get(name)) is not None and
                              slot.kind is inspect.Parameter.POSITIONAL_ONLY}
                    # Signature 不能同时声明两个同名槽，关键字独立传给公开绑定。
                    tested[names] = yield from resolve(sig if sig is not None else base_sig, view, False, variant,
                                                       shadow, extra_set)
                return tested[names]

            # 从全集按真实绑定冲突剥离；每一轮至少少一个键。
            cur = extra
            while True:
                _, error = yield from attempt(cur)
                if error is None or error[0] != "drop":
                    break
                reduced = tuple(name for name in cur if name not in error[1])
                if reduced == cur:
                    break
                cur = reduced

            # 全集也可能先遇到用户异常。从空集只增长真实缺少的必填键。
            cur = ()
            while True:
                ok, error = yield from attempt(cur)
                if error is None or error[0] != "need":
                    break
                enlarged = tuple(name for name in extra if name in cur or name in error[1])
                if enlarged == cur:
                    break
                cur = enlarged
            if ok and cur and cur != extra:
                accepted = set(cur)
                for name in extra:
                    if name not in cur:
                        combo = tuple(k for k in extra if k in cur or k == name)
                        if (yield from attempt(combo))[0]:
                            accepted.add(name)
                yield from attempt(tuple(name for name in extra if name in accepted))

            # 构造成功只表示接纳实参，不表示已经覆盖承接导出。
            accepted = []
            for name in extra:
                if (yield from attempt((name,)))[0]:
                    accepted.append(name)
            if 2 <= len(accepted) < len(extra):
                yield from attempt(tuple(accepted))

            # 无可用绑定诊断时，小集合补齐子集；大集合只补试删一键、删两键。
            n = len(extra)
            sizes = range(n - 1, 1, -1) if n <= 6 else (n - 1, n - 2)
            for size in sizes:
                for subset in combinations(extra, size):
                    yield from attempt(subset)

        for use_variadic, use_alternate in CTOR_PROBE_TIERS:
            if variadic is not None and variadic is not use_variadic:
                continue
            if alternate is not None and use_alternate is not None and alternate is not use_alternate:
                continue
            only_alternate = alternate if use_variadic else use_alternate
            if use_variadic:
                for args, kwargs in shapes:
                    yield from resolve_args(args, kwargs, {}, None, extra_set)
            for view in views:
                for sig, variant, is_alternate in pairs:
                    if only_alternate is None or is_alternate is only_alternate:
                        if use_variadic:
                            for mode in variadic_modes(sig, shapes):
                                yield from resolve(sig, view, mode, variant, error_keys=extra_set)
                        else:
                            yield from resolve(sig, view, False, variant)
            if use_alternate is True:
                for view in views:
                    for pair in recovery:
                        yield from recover_kwonly(pair, view)

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

    def arguments(self, fn, named, shapes, overrides=()):
        try:
            public = inspect.signature(fn, follow_wrapped=False)
        except (ValueError, TypeError):
            return

        def candidates():
            for args, kwargs in shapes:
                yield args, kwargs, {}
            for view in (named, *overrides):
                for signature in self.signatures(fn, public, view):
                    modes = variadic_modes(signature, shapes) if has_variadic(signature) else (False,)
                    for mode in modes:
                        try:
                            yield arguments(signature, view, mode)
                        except (ValueError, TypeError):
                            continue

        choices, default_refs = set(), {}
        for args, kwargs, defaults in candidates():
            try:
                choice = argument_choice(public, args, kwargs, defaults, default_refs)
            except (ValueError, TypeError):
                continue
            if choice not in choices:
                choices.add(choice)
                yield copy_arguments(args, kwargs, defaults)


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

    @staticmethod
    def ctor_callable(cls, member):
        if cls is None or cls is object:
            return None
        if type(member) in (staticmethod, classmethod):
            target = member.__func__
            return target if type(target) in (FunctionType, MethodType) else None
        return member if type(member) in (FunctionType, MethodType) else None

    def class_defines_code(self, owner, code, hook_name):
        if code.co_name != hook_name:
            return False
        for base in type.__getattribute__(owner, "__mro__"):
            body = self.class_body(base)
            if body is not None and code in body.co_consts:
                return True
        return False

    def tag_ctor_chain(self, owner, hook_name, member, chain, *, include_first=False):
        strip = ctor_receiver_count(hook_name, member)
        start = 0 if include_first else 1
        items = []
        after_class_hook = False
        for idx, target in enumerate(chain):
            is_class_hook = type(target) is FunctionType and self.class_defines_code(owner, target.__code__, hook_name)
            if idx >= start:
                guaranteed = strip > 0 and (idx == 0 or is_class_hook)
                items.append((target, strip, guaranteed, after_class_hook))
            if is_class_hook:
                after_class_hook = True
            if type(target) is MethodType:
                strip += 1
        return tuple(items)

    def ctor_chains(self, owner):
        new_cls, new_member = mro_member(owner, "__new__")
        init_cls, init_member = mro_member(owner, "__init__")
        new_target = self.ctor_callable(new_cls, new_member)
        init_target = self.ctor_callable(init_cls, init_member)
        hooks = ((new_cls, new_target), (init_cls, init_target))

        def local_chain(cls, target):
            if target is not None and self.class_body(cls) is not None:
                return self.wrapped_chain(target)

        meta_cls, meta_member = mro_member(type(owner), "__call__")
        if meta_cls is not None and meta_cls is not type:
            chain = local_chain(meta_cls, self.ctor_callable(meta_cls, meta_member))
            if not chain:
                return (), (), False
            # 元类可以转发给实例构造链，不替其外来钩子提供身份依据。
            shapes_local = all(cls is None or cls is object or local_chain(cls, target) is not None
                               for cls, target in hooks)
            return self.tag_ctor_chain(type(owner), "__call__", meta_member, chain), (), shapes_local

        # 只给已经核验的本地构造链复用原始形状。透明签名能绑定，
        # 不代表可以替未核验的包装对象或另一侧构造钩子猜测输入。
        shapes_local = all(cls is None or cls is object or target is not None
                           for cls, target in hooks)
        if new_target is None and init_target is None:
            return (), (), shapes_local

        mro = type.__getattribute__(owner, "__mro__")
        new_rank = mro.index(new_cls) if new_target is not None else len(mro)
        init_rank = mro.index(init_cls) if init_target is not None else len(mro)
        if new_rank <= init_rank:
            primary = ("__new__", new_cls, new_member, new_target)
            secondary = ("__init__", init_cls, init_member, init_target) if init_target is not None else None
        else:
            primary = ("__init__", init_cls, init_member, init_target)
            secondary = ("__new__", new_cls, new_member, new_target) if new_target is not None else None

        p_name, p_cls, p_member, p_target = primary
        p_chain = local_chain(p_cls, p_target)
        if not p_chain:
            return (), (), False

        p_items = self.tag_ctor_chain(owner, p_name, p_member, p_chain)
        s_items = ()
        if secondary is not None:
            s_name, s_cls, s_member, s_target = secondary
            s_chain = local_chain(s_cls, s_target)
            if s_chain:
                s_items = self.tag_ctor_chain(owner, s_name, s_member, s_chain, include_first=True)
            else:
                shapes_local = False
        return p_items, s_items, shapes_local

    def binding(self, key, member, owner=None, ctor_chains=((), ()), ctor_shapes=True):
        fn = underlying(member)
        if chain := self.wrapped_chain(fn):
            return Binding(key, member, chain, owner, ctor_chains, ctor_shapes)

    def local_members(self, bindings):
        for export_name, value in bindings.items():
            if type(value) is FunctionType or type(value) is MethodType and self.owns_receiver(value.__self__):
                if (binding := self.binding(("module", export_name), value)) is not None:
                    yield binding
            elif is_class(value) and self.class_body(value) is not None:
                primary, secondary, ctor_shapes = self.ctor_chains(value)
                seen = set()
                for owner in type.__getattribute__(value, "__mro__"):
                    local = self.class_body(owner) is not None
                    for name, member in class_members(owner):
                        if name in seen:
                            continue
                        seen.add(name)
                        if local and not name.startswith("_") and type(member) in (FunctionType, staticmethod, classmethod):
                            if (binding := self.binding(("class", export_name, name), member, value,
                                                       (primary, secondary), ctor_shapes)) is not None:
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


def public_probe(production, targets, origins, test_entered, samples, shapes, overrides):
    # pytest 可能已加载或修改受验模块；用同一冻结副本重新导入，且导入不记覆盖。
    root = Path.cwd().resolve()
    for name, loaded in list(sys.modules.items()):
        filename = vars(loaded).get("__file__") if inspect.ismodule(loaded) else None
        if isinstance(filename, str) and Path(filename).resolve().is_relative_to(root):
            sys.modules.pop(name, None)
    production.load(origins)
    targets.load(origins)

    views, shapes = (samples, *overrides), tuple(shapes)
    instances, ctor_errors, tried = {}, {}, set()
    for variadic, alternate in CTOR_PROBE_TIERS:
        for binding in production.members:
            try:
                for fn in binding.callables(instances, views, variadic=variadic, alternate=alternate,
                                            ctor_errors=ctor_errors, shapes=shapes):
                    try:
                        identity = (id(fn.__func__), id(fn.__self__)) if type(fn) is MethodType else (id(fn),)
                        if identity in tried:
                            continue
                        tried.add(identity)
                        for args, kwargs in binding.arguments(fn, samples, shapes, overrides):
                            if probe_call(production, targets, test_entered, fn, args, kwargs):
                                return True
                    except (Exception, SystemExit):
                        continue
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
            self.shapes = {}
            self.named_observations = {}

        def overrides(self):
            # 先保留可跨调用拼合的首值表与合并覆写视图，再保留未补齐的原始观察以触发生产默认。
            seen = {keyword_sample_key(self.samples)}
            merged = [observed | {k: v for k, v in self.samples.items() if k not in observed}
                      for observed in self.named_observations.values()]
            for view in (*merged, *self.named_observations.values()):
                key = keyword_sample_key(view)
                if key not in seen:
                    seen.add(key)
                    yield view

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
                    for samples, (args, kwargs) in path:
                        key = tuple(map(sample_key, args)), keyword_sample_key(kwargs)
                        self.shapes.setdefault(key, (args, kwargs))
                        self.named_observations.setdefault(keyword_sample_key(samples), samples)
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
                 public_probe(production, targets, origins, registration.entered, registration.samples,
                              registration.shapes.values(), tuple(registration.overrides()))))


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
