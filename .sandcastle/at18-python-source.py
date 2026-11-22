"""只用 AST 核对冻结 Python 源码；不 import 或运行任何受验代码。"""
import ast
import json
import sys


def substantive(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return any(map(substantive, node.body))
    if isinstance(node, ast.Expr):
        return not isinstance(node.value, ast.Constant)
    return isinstance(node, ast.stmt) and not isinstance(node, (ast.Pass, ast.Import, ast.ImportFrom))


def module(path):
    return path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def names(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*names(node.value), node.attr]
    return []


def imports(tree, path):
    package = module(path).split(".")
    if not path.endswith("/__init__.py"):
        package.pop()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                dotted = alias.name.split(".")
                yield dotted, [alias.asname] if alias.asname else dotted
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                continue
            prefix = package[:len(package) - node.level + 1] if node.level else []
            if node.module:
                prefix += node.module.split(".")
            for alias in node.names:
                if alias.name != "*":
                    yield [*prefix, alias.name], [alias.asname or alias.name]


def uses(tree, path, bodies, expected, exports):
    bindings = [(origin, local) for origin, local in imports(tree, path)
                if origin[:len(expected)] == expected or expected[:len(origin)] == origin]
    for body in bodies:
        for node in ast.walk(body):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            used = names(node)
            for origin, local in bindings:
                if used[:len(local)] == local:
                    target = origin + used[len(local):]
                    if target[:len(expected)] == expected and target[len(expected):len(expected) + 1] in exports:
                        return True
    return False


def proves(doc):
    source = ast.parse(doc["source"])
    if not any(map(substantive, source.body)):
        return False
    if "entry" not in doc:
        return True
    caller = ast.parse(doc["caller"])
    test = ast.parse(doc["test"])
    selected = test
    for part in doc["selector"].split("::"):
        candidates = [n for n in selected.body
                      if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == part]
        if len(candidates) != 1:
            return False
        selected = candidates[0]
    entry = module(doc["entry"]).split(".")
    exports = [[node.name] for node in source.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and substantive(node)]
    exports.extend([target.id] for node in source.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name))
    exports.extend([node.target.id] for node in source.body if isinstance(node, ast.AnnAssign)
                   and isinstance(node.target, ast.Name) and node.value is not None)
    return (isinstance(selected, (ast.FunctionDef, ast.AsyncFunctionDef))
            and uses(caller, doc["integration"], caller.body, entry, exports)
            and uses(test, doc["checkPath"], [selected], entry, exports))


if __name__ == "__main__":
    sys.exit(not proves(json.load(sys.stdin)))
