"""FM-04 门禁。退出码：0 绿，1 红，2 无法判定。"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from collections import defaultdict


class Undetermined(Exception):
    """没有足够的原件或工具作出判断。"""


def command(cwd, *args):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def checked(cwd, *args):
    result = command(cwd, *args)
    if result.returncode:
        raise Undetermined(f"{' '.join(args)}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def red(gate, path, where, code, detail):
    print(f"GATE{gate} RED {path}:{where} {code} {detail}", flush=True)


def sources(root):
    """依赖和构建产物在 .lake；故意写坏的样本不属于包源码。"""
    for directory, dirs, files in os.walk(root / "formal_math"):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        here = Path(directory).relative_to(root)
        if here == Path("formal_math/verification"):
            dirs[:] = [d for d in dirs if d not in {"must_red", "must_green"}]
        for name in sorted(files):
            if name.endswith(".lean"):
                yield here / name


# 消费完整标识符、注释、字面量；不把说明文字算作命令。
LEX = re.compile(
    r'/\-|--[^\n]*|r(?P<hash>#+)?"[\s\S]*?"(?P=hash)|'
    r'"(?:\\.|[^"\\])*"|' r"'(?:\\.|[^'\\\n])'|"
    r'«[^»]*»|[#@]?[^\W\d][\w′\']*|[^\s]',
    re.UNICODE,
)


def tokens(text):
    index = 0
    line = 1
    while match := LEX.search(text, index):
        line += text.count("\n", index, match.start())
        token = match.group()
        end = match.end()
        if token == "/-":
            depth = 1
            while depth:
                marker = re.search(r"/-|-/", text[end:])
                if marker is None:
                    raise Undetermined(f"第 {line} 行的块注释未闭合")
                depth += 1 if marker.group() == "/-" else -1
                end += marker.end()
        elif token.startswith("--"):
            pass
        elif token.startswith(('"', 'r"', "r#", "'")) and len(token) > 1:
            # 字面量仍是语法中的一个位置，不允许跳过它找首条命令。
            yield "", line
        else:
            yield token.removeprefix("«").removesuffix("»"), line
        line += text.count("\n", match.start(), end)
        index = end


def load_sources(root):
    return {path: list(tokens((root / path).read_text())) for path in sources(root)}


def gate1(root):
    fm = root / "formal_math"
    pins = json.loads((fm / "verification/pins.json").read_text())
    manifest = json.loads((fm / "lake-manifest.json").read_text())
    toolchain = (fm / "lean-toolchain").read_text().strip()
    failed = False
    if toolchain != pins["toolchain"]:
        red("1", "formal_math/lean-toolchain", 1, "TOOLCHAIN_PIN", f"期望 {pins['toolchain']}")
        failed = True
    packages = manifest["packages"]
    actual = {package["name"]: package["rev"] for package in packages}
    if len(packages) != 9 or actual.keys() != pins["packages"].keys():
        red("1", "formal_math/lake-manifest.json", 1, "PACKAGE_SET", "应恰有九个不同的钉选包")
        failed = True
    for name, rev in sorted(pins["packages"].items()):
        if name in actual and actual[name] != rev:
            red("1", "formal_math/lake-manifest.json", name, "PACKAGE_PIN", f"期望修订 {rev}")
            failed = True
    return int(failed)


def option_issues(items, include_linter=True):
    values = [t for t, _ in items]
    for i, (value, line) in enumerate(items):
        if value == "set_option" and i + 1 < len(items):
            key = values[i + 1]
            if key == "autoImplicit" or (include_linter and key == "linter"):
                yield line, key


def gate2(root):
    config = root / "formal_math/lakefile.toml"
    options = tomllib.loads(config.read_text()).get("leanOptions", {})
    failed = False
    for option, expected in (
        ("autoImplicit", False), ("relaxedAutoImplicit", False), ("linter.unusedVariables", True)
    ):
        table = options
        pieces = option.split(".")
        for section in pieces[:-1]:
            table = table.get(section, {})
        if table.get(pieces[-1]) is not expected:
            red("2", config.relative_to(root), 1, "LEAN_OPTION", f"{option} 必须为 {str(expected).lower()}")
            failed = True
    for path, items in load_sources(root).items():
        for line, key in option_issues(items):
            red("2", path, line, "LOCAL_OPTION", f"禁止在源码设置 {key}")
            failed = True
    result = command(config.parent, "lake", "build", "--wfail")
    if result.returncode:
        if result.returncode < 0 or re.search(
            r"(?:no default toolchain|toolchain .*not installed|could not (?:download|resolve host))",
            result.stderr, re.IGNORECASE
        ):
            raise Undetermined(result.stderr.strip())
        red("2", config.relative_to(root), 1, "BUILD_WFAIL", f"lake build --wfail 退出 {result.returncode}")
        print(result.stdout + result.stderr, file=sys.stderr, end="")
        failed = True
    return int(failed)


BANNED = {
    "axiom", "sorry", "admit", "native_decide", "unsafe", "extern",
    "implemented_by", "partial", "syntax", "macro", "macro_rules", "elab",
    "elab_rules", "notation", "infix", "infixl", "infixr", "prefix", "postfix",
    "declare_syntax_cat",
}


def module_name(path):
    return ".".join(path.relative_to("formal_math").with_suffix("").parts)


def lane(module):
    for prefix in (
        "Chan.Audit.Literal", "Chan.Defs", "Chan.Proxy", "Chan.Hypotheses", "Chan.Thm",
        "Chan.Proofs", "Chan.Exec", "Chan.Audit", "Chan.Final", "ChanChallenge",
        "ChanDyn", "ChanTest", "ChanExplore",
    ):
        if module == prefix or module.startswith(prefix + "."):
            return prefix
    return "Chan" if module == "Chan" or module.startswith("Chan.") else ""


def audit(fm, mods):
    checked(fm, "lake", "build", *(f"+{module}:olean" for module in mods))
    result = command(fm, "lake", "exe", "fm_audit", *mods)
    findings = []
    for line in result.stdout.splitlines():
        if re.fullmatch(r"GATE3 RED formal_math/\S+:\S+ [A-Z_]+ .+", line):
            findings.append(line)
        elif line.strip():
            raise Undetermined(f"审计输出无法识别：{line}")
    if result.returncode not in (0, 1) or bool(findings) != bool(result.returncode):
        raise Undetermined(result.stderr.strip() or f"Lean 审计退出 {result.returncode}")
    for line in findings:
        print(line)
    return result.returncode


def gate3(root):
    source = load_sources(root)
    findings = []
    for path, items in source.items():
        for value, line in items:
            if value in BANNED or (value == "#eval" and lane(module_name(path)) != "ChanExplore"):
                findings.append((path, line, f"禁用记号 {value}"))
        for line, key in option_issues(items):
            if key == "linter":
                findings.append((path, line, "禁止在源码设置 linter"))
    fm = root / "formal_math"
    # 文本已有硬反例时，只编译与读取独立探针，不编译有禁用记号的模块。
    mods = ["ChanTest.Probe"] if findings else [module_name(path) for path in source]
    environment = audit(fm, mods)
    for path, line, detail in findings:
        red("3", path, line, "TOKEN", detail)
    return max(environment, int(bool(findings)))


PATHS = {
    "decl": ("formal_math/Chan/Defs/", "formal_math/Chan/Hypotheses/", "formal_math/Chan/Audit/Literal/",
             "formal_math/ChanChallenge/", "formal_math/statement-lock.json",
             "formal_math/formalization.yaml", "formal_math/HISTORY.md", "formal_math/blueprint/"),
    "proof": ("formal_math/Chan/Thm/", "formal_math/Chan/Proofs/", "formal_math/ChanTest/",
              "formal_math/ChanDyn/"),
    "audit": ("formal_math/Chan/Audit/Math/", "formal_math/Chan/Audit/Separation/",
              "formal_math/Chan/Audit/Cases/", "formal_math/ChanTest/"),
    "infra": ("formal_math/verification/", "scripts/", ".github/workflows/", "formal_math/lakefile.toml"),
}
BOOTSTRAP_HEAD = "38f65e920a851a29a3ec55142113a90d8921d1db"
BOOTSTRAP_BRANCH = "infra/2312-a-layout-gates"
BOOTSTRAP_PATHS = (
    "formal_math/ChanTest/", "formal_math/README.md", "formal_math/HISTORY.md",
    "formal_math/formalization.yaml", "formal_math/Chan/Smoke.lean",
)


def within(path, rules):
    return any(path.startswith(rule) if rule.endswith("/") else path == rule for rule in rules)


def gate6b(root):
    branch = checked(root, "git", "symbolic-ref", "--short", "HEAD").strip()
    prefix, marker, _ = branch.partition("/")
    head = checked(root, "git", "rev-parse", "HEAD").strip()
    base = checked(root, "git", "merge-base", "refs/remotes/origin/main", head).strip()
    special = branch == BOOTSTRAP_BRANCH and command(
        root, "git", "merge-base", "--is-ancestor", BOOTSTRAP_HEAD, head
    ).returncode == 0
    if special and command(root, "git", "merge-base", "--is-ancestor", BOOTSTRAP_HEAD, base).returncode == 1:
        base = BOOTSTRAP_HEAD
    changes = set()
    # 分开查提交、暂存区、工作树，避免两个相反的改动互相抵消。
    for revisions in ((base, head), ("--cached", head), ()):
        changes.update(checked(root, "git", "diff", "--name-only", "-z", "--no-renames", *revisions).split("\0"))
    changes.update(checked(root, "git", "ls-files", "-z", "--others", "--exclude-standard", "--",
                           "formal_math", "scripts", ".github/workflows").split("\0"))
    changes.discard("")
    if not marker or prefix not in PATHS:
        red("6b", ".git/HEAD", 1, "BRANCH_PREFIX", f"分支 {branch} 没有可交付的路径权限")
        return 1
    failed = False
    for path in sorted(changes):
        if within(path, PATHS[prefix]) or special and within(path, BOOTSTRAP_PATHS):
            continue
        if special and path == "formal_math/statement-lock.json":
            existed = command(root, "git", "cat-file", "-e", f"{base}:{path}").returncode == 0
            current = root / path
            committed = command(root, "git", "show", f"{head}:{path}")
            staged = command(root, "git", "show", f":{path}")
            versions = [r.stdout for r in (committed, staged) if r.returncode == 0]
            if not existed and current.is_file() and all(
                json.loads(data) == {} for data in [current.read_text(), *versions]
            ):
                continue
        red("6b", path, 1, "PATH_SCOPE", f"分支 {branch} 不允许修改此路径")
        failed = True
    return int(failed)


def read_imports(items):
    index = 1  # 调用方已检查首条命令。
    if index < len(items) and items[index][0] == "prelude":
        index += 1
    while index < len(items):
        while index < len(items) and items[index][0] in {"public", "meta"}:
            index += 1
        if index == len(items) or items[index][0] != "import":
            break
        line = items[index][1]
        index += 1
        if index < len(items) and items[index][0] == "all":
            index += 1
        if index == len(items):
            raise Undetermined(f"第 {line} 行的 import 缺少模块")
        parts = [items[index][0]]
        index += 1
        # Lean 的层级名不允许把有空白的独立点号误当作路径；构建另验语法。
        while index + 1 < len(items) and items[index][0] == ".":
            parts.append(items[index + 1][0])
            index += 2
        yield ".".join(parts), line


PROOF_LANES = {"Chan.Thm", "Chan.Proofs", "Chan.Exec"}
FOUNDATION = {"Chan.Defs", "Chan.Proxy", "Chan.Hypotheses"}
AUDIT_LANES = {"Chan.Audit", "Chan.Audit.Literal"}


def allowed_edge(src, dst):
    a, b = lane(src), lane(dst)
    if a == "ChanExplore":
        return True
    if b == "ChanExplore":
        return False
    if a == "ChanChallenge":
        return dst.startswith(("Mathlib.", "Init.")) or dst == "Init" or b in {
            "Chan.Defs", "Chan.Hypotheses", "Chan.Audit.Literal",
        }
    if b == "" and dst != "Chan":
        return True  # 外部工具链依赖不属于 Chan 分层。
    if a == "Chan.Defs":
        return b == "Chan.Defs"
    if a in {"Chan.Proxy", "Chan.Hypotheses"}:
        return b in {a, "Chan.Defs"}
    if a in PROOF_LANES:
        return b in FOUNDATION | PROOF_LANES
    if a in AUDIT_LANES:
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES
    if a == "Chan.Final":
        return b == "Chan.Thm"
    if a == "ChanDyn":
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES | {"Chan", "Chan.Final", "ChanDyn"}
    return b != "ChanChallenge"


def gate15(root):
    source = load_sources(root)
    graph = defaultdict(list)
    failed = False
    for path, items in source.items():
        module = module_name(path)
        graph[module]
        if not items or items[0][0] != "module":
            red("15", path, items[0][1] if items else 1, "MODULE_FIRST", "第一条命令必须为 module")
            failed = True
            continue
        values = [t for t, _ in items]
        expose = ["@", "[", "expose", "]", "public", "section"]
        if lane(module) == "Chan.Defs" and not any(
            values[i:i + len(expose)] == expose for i in range(len(values))
        ):
            red("15", path, 1, "EXPOSE_SECTION", "定义文件须用 @[expose] public section")
            failed = True
        for dst, line in read_imports(items):
            graph[module].append((dst, line))
            if dst == "Mathlib":
                red("15", path, line, "WHOLE_MATHLIB", "请只导入所需的 Mathlib 子模块")
                failed = True
            elif not allowed_edge(module, dst):
                red("15", path, line, "IMPORT_EDGE", f"禁止导入 {dst}")
                failed = True
    if failed:
        return 1
    # Lake 按当前包配置解析真实模块边；源位置仍来自头部文本。
    targets = [f"+{module}:imports" for module in graph]
    resolved = checked(root / "formal_math", "lake", "query", "--json", *targets).splitlines()
    if not targets or len(resolved) != len(targets):
        raise Undetermined("Lake 的模块图未覆盖全部源码")
    for (module, edges), actual in zip(graph.items(), resolved, strict=True):
        declared = {dst for dst, _ in edges}
        lake_imports = set(json.loads(actual))
        if not declared.intersection(graph) <= lake_imports <= declared:
            raise Undetermined(f"{module}: Lake 解析的导入与源码不一致")
    for path in source:
        module = module_name(path)
        for dst, line in graph.get(module, ()):
            pending, seen = [dst], {module}
            while pending:
                target = pending.pop()
                if target in seen:
                    continue
                seen.add(target)
                target_lane = lane(target)
                if (lane(module) != "ChanExplore" and target_lane == "ChanExplore") or (
                    lane(module) == "Chan.Final" and target_lane in AUDIT_LANES | {"ChanDyn"}
                ):
                    red("15", path, line, "IMPORT_CLOSURE", f"经 {dst} 间接导入 {target}")
                    failed = True
                    break
                pending.extend(imported for imported, _ in graph.get(target, ()))
    return int(failed)


GATES = {"1": gate1, "2": gate2, "3": gate3, "6b": gate6b, "15": gate15}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--gate", choices=GATES)
    parser.add_argument("--stage", choices=("decl", "proof", "all"), default="all")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    if not (root / "formal_math").is_dir():
        print(f"FM: {root} 下找不到 formal_math", file=sys.stderr)
        return 2
    result = 0
    # 本片各门在声明期和证明期均适用。
    for number in (args.gate,) if args.gate else GATES:
        try:
            result = max(result, GATES[number](root))
        except (Undetermined, OSError, ValueError, KeyError, TypeError) as exc:
            print(f"GATE{number}: 无法判定：{exc}", file=sys.stderr)
            result = 2
    return result


if __name__ == "__main__":
    sys.exit(main())
