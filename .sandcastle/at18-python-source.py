"""在隔离的 F 副本中，核验生产接入并跟踪登记的 pytest 选择器。"""
import ast
import asyncio
import dis
import importlib
import inspect
import json
import os
import sys
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
DEFINITIONS = (*FUNCTIONS, ast.ClassDef)


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


def public_probe(integration, integration_path, public_codes, source_path, test_entered_codes, samples):
    # pytest 可能已加载或修改受验模块；用同一冻结副本重新导入，且导入不记覆盖。
    root = Path.cwd().resolve()
    for name, loaded in list(sys.modules.items()):
        filename = vars(loaded).get("__file__") if inspect.ismodule(loaded) else None
        if isinstance(filename, str) and Path(filename).resolve().is_relative_to(root):
            sys.modules.pop(name, None)
    try:
        production = importlib.import_module(module(integration))
        if Path(production.__file__).resolve() != Path(integration_path):
            return False
    except (Exception, SystemExit):
        return False

    def local_public(fn):
        return (type(fn) is FunctionType and fn.__code__.co_filename == integration_path and
                fn.__code__ in public_codes)

    def entries():
        for name, value in list(vars(production).items()):
            if name.startswith("_"):
                continue
            if local_public(value):
                yield value
            elif isinstance(value, type) and value.__module__ == production.__name__:
                instance = None
                tried = False
                for method, member in list(vars(value).items()):
                    if method.startswith("_"):
                        continue
                    if type(member) in (staticmethod, classmethod):
                        if local_public(member.__func__):
                            yield member.__get__(None, value)
                    elif local_public(member):
                        if not tried:
                            tried = True
                            try:
                                args, kwargs = arguments(value, samples)
                                instance = value(*args, **kwargs)
                            except (Exception, SystemExit):
                                continue
                        if instance is not None:
                            yield member.__get__(instance, value)

    for fn in entries():
        covered = False
        returned_frame = None
        result = None
        public_code = fn.__code__

        def profile(frame, event, arg):
            nonlocal covered
            code = frame.f_code
            if event != "call" or code.co_filename != source_path or code not in test_entered_codes:
                return
            while frame is not None:
                if frame.f_code is public_code or frame is returned_frame:
                    covered = True
                    return
                frame = frame.f_back

        async def consume_async_generator(generator):
            try:
                for _ in range(PROBE_STEPS):
                    if covered:
                        break
                    try:
                        await anext(generator)
                    except StopAsyncIteration:
                        break
            finally:
                # asyncio.run 关闭事件循环时的隐式 aclose 不属于公开消费。
                sys.setprofile(None)

        try:
            args, kwargs = arguments(fn, samples)
            sys.setprofile(profile)
            result = fn(*args, **kwargs)
            member = DEFERRED_FRAMES.get(type(result))
            if not covered and member:
                # 只驱动公开返回值；不查找或推进函数内部未返回的生成器。
                returned_frame = getattr(result, member)
                if type(result) is CoroutineType:
                    asyncio.run(result)
                elif type(result) is AsyncGeneratorType:
                    asyncio.run(consume_async_generator(result))
                else:
                    for _ in range(PROBE_STEPS):
                        if covered:
                            break
                        next(result)
        except (Exception, SystemExit):
            # 只承认异常前实际进入的导出；不因一次探针异常停止其他公开入口。
            pass
        finally:
            sys.setprofile(None)
            result = None
        if covered:
            return True
    return False


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
    substantive_positions = positions(node for node in ast.walk(entry_tree) if isinstance(node, FUNCTIONS) and substantive(node))
    source_path, entry_codes = file_codes(entry, substantive_positions)
    integration_path, public_codes = file_codes(integration, positions(public_functions(integration_tree.body)))
    test_path, test_position = str(Path(path).resolve()), (line(test), test.name)
    # profile emits "return" on suspension too; a yield is not an exported return value.
    returns = {dis.opmap[name] for name in ("RETURN_VALUE", "RETURN_CONST") if name in dis.opmap}

    class Trace:
        covered = False
        passed = 0
        nonpass = False

        def __init__(self):
            self.returned = set()
            self.test_entered_codes = set()
            self.samples = {}

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
                member = DEFERRED_FRAMES.get(type(arg))
                if member and code.co_code[frame.f_lasti] in returns and self.ancestry(frame.f_back)[0]:
                    child = getattr(arg, member)
                    if child is not None:
                        self.returned.add(child)
            if event != "call" or code.co_filename != source_path or code not in entry_codes:
                return
            in_test, via_public = self.ancestry(frame.f_back)
            if in_test:
                self.covered |= via_public or frame in self.returned
                self.test_entered_codes.add(code)
                for name in code.co_varnames[:code.co_argcount + code.co_kwonlyargcount]:
                    if name not in self.samples and name in frame.f_locals:
                        try:
                            self.samples[name] = sample(frame.f_locals[name])
                        except ValueError:
                            pass

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
    return (result == pytest.ExitCode.OK and not trace.nonpass and trace.passed == doc["count"] and
            (trace.covered or bool(trace.test_entered_codes) and
             public_probe(integration, integration_path, public_codes, source_path, trace.test_entered_codes, trace.samples)))


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
