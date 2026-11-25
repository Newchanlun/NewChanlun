"""FM-04 门禁。退出码：0 绿，1 红，2 无法判定。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from collections import Counter, defaultdict


class Undetermined(Exception):
    """没有足够的原件或工具作出判断。"""


def command(cwd, *args, stdin=None):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False,
                          input=stdin, timeout=600)


def checked(cwd, *args):
    result = command(cwd, *args)
    if result.returncode:
        raise Undetermined(f"{' '.join(args)}: {(result.stdout + result.stderr).strip()}")
    return result.stdout


def red(gate, path, where, code, detail):
    print(f"GATE{gate} RED {path}:{where} {code} {detail}", flush=True)


def sources(root):
    """依赖和构建产物在 .lake；故意写坏的样本不属于包源码。"""
    for directory, dirs, files in os.walk(root / "formal_math"):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        here = Path(directory).relative_to(root)
        if here == Path("formal_math/verification"):
            dirs[:] = [d for d in dirs if d not in {"must_red", "must_green", "must_unknown", "report_cases"}]
        for name in sorted(files):
            if name.endswith(".lean"):
                yield here / name


def gate1(root):
    fm = root / "formal_math"
    pins = load_data(fm / "verification/pins.json")
    manifest = load_data(fm / "lake-manifest.json")
    toolchain = (fm / "lean-toolchain").read_text().strip()
    failed = False
    if toolchain != pins["toolchain"]:
        red("1", "formal_math/lean-toolchain", 1, "TOOLCHAIN_PIN", f"期望 {pins['toolchain']}")
        failed = True
    # 钉选文件自身不匹配时不触发 elan 下载错误工具链。
    else:
        runtime = checked(fm, "lean", "--version")
        match = re.match(r"Lean \(version ([^,\s)]+)", runtime)
        if not match:
            raise Undetermined("无法识别运行期 Lean 版本")
        if match[1] != toolchain.rsplit(":v", 1)[-1]:
            red("1", "formal_math/lean-toolchain", 1, "RUNTIME_TOOLCHAIN_PIN",
                f"实际版本 {match[1]}，期望 {toolchain}")
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
    # 修订相同而来源换成本地路径或别的远端，同样不是钉选的那份代码。
    for package in packages:
        want = pins["sources"].get(package["name"])
        if want and (package.get("type") != want["type"] or package.get("url") != want["url"]):
            red("1", "formal_math/lake-manifest.json", package["name"], "PACKAGE_SOURCE",
                f"期望 {want['type']} 来源 {want['url']}")
            failed = True
    return int(failed)


def gate2(root):
    config = root / "formal_math/lakefile.toml"
    try:
        package = tomllib.loads(config.read_text())
    except tomllib.TOMLDecodeError as exc:
        # 解析不了的配置不在白名单里（例如同一键既是值又是表，借此夹带子选项）。
        red("2", "formal_math/lakefile.toml", 1, "LAKEFILE_KEY", f"lakefile.toml 无法解析：{exc}")
        return 1
    options = package.get("leanOptions", {})
    failed = False
    controlled = {"autoImplicit", "relaxedAutoImplicit", "linter.unusedVariables"}
    for target in [package, *package.get("lean_lib", []), *package.get("lean_exe", [])]:
        overrides = set(target.get("leanOptions", {}))
        if target is package:
            overrides = set()
        args = target.get("moreLeanArgs", []) + target.get("weakLeanArgs", [])
        if overrides & (controlled | {"linter"}) or any(
            re.search(r"(?:^|\s)(?:-D\s*)?(autoImplicit|relaxedAutoImplicit|linter\.unusedVariables)=", arg)
            for arg in args
        ):
            red("2", config.relative_to(root), 1, "LEAN_OPTION_OVERRIDE",
                f"{target.get('name', 'package')} 覆盖受控选项")
            failed = True
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
    if failed:
        return 1
    # 封闭世界：lakefile 里能传 Lean 选项或参数的入口（moreLeanArgs、weakLeanArgs、
    # moreServerOptions、目标级 leanOptions、插件等）一律不在名单里；名单外即红，构建照跑以便读数。
    failed = lakefile_whitelist(root, package)
    source, state = audit_sources(root, "2")
    if state:
        return state
    targets = [f"+{module_name(p)}:olean" for p in source if p.parts[1] != "verification"]
    result = command(config.parent, "lake", "build", "--wfail")
    if not result.returncode and targets:
        result = command(config.parent, "lake", "build", "--wfail", *targets)
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


LAKEFILE_KEYS = {
    "package": {"name", "version", "defaultTargets", "leanOptions", "require", "lean_lib", "lean_exe"},
    "require": {"name", "git", "rev", "scope"},
    "lean_lib": {"name", "globs", "roots"},
    "lean_exe": {"name", "root", "supportInterpreter"},
}
LAKEFILE_OPTIONS = {"autoImplicit": False, "relaxedAutoImplicit": False, "linter": {"unusedVariables": True}}


def lakefile_whitelist(root, package):
    """lakefile.toml 的键与取值白名单（Lake 4.36.0 `Lake/Load/Toml.lean` 生成的解码器接受的
    其余键——构建参数、服务器选项、插件、原生链接参数等——都不在名单里）。"""
    fm = root / "formal_math"
    path = "formal_math/lakefile.toml"
    failed = False

    def bad(where, detail):
        nonlocal failed
        red("2", path, where, "LAKEFILE_KEY", detail)
        failed = True

    if (fm / "lakefile.lean").exists():
        bad(1, "不许 lakefile.lean（Lake 会优先读它，绕开本白名单）")
    for key in sorted(set(package) - LAKEFILE_KEYS["package"]):
        bad(key, f"包级键不在白名单：{key}")
    if package.get("leanOptions") != LAKEFILE_OPTIONS:
        bad("leanOptions", "包级 leanOptions 只许 autoImplicit=false、relaxedAutoImplicit=false、"
            "linter.unusedVariables=true 三项")
    for section in ("require", "lean_lib", "lean_exe"):
        for target in package.get(section, []):
            if not isinstance(target, dict):
                bad(section, f"{section} 须为表")
                continue
            for key in sorted(set(target) - LAKEFILE_KEYS[section]):
                bad(f"{target.get('name', section)}.{key}", f"{section} 键不在白名单：{key}")
            for key in ("globs", "roots"):
                if key in target and not (isinstance(target[key], list) and
                                          all(isinstance(v, str) for v in target[key])):
                    bad(f"{target.get('name', section)}.{key}", f"{key} 须为字符串数组")
            if section == "lean_exe" and not isinstance(target.get("supportInterpreter", True), bool):
                bad(target.get("name", section), "supportInterpreter 须为布尔值")
    return failed


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


def lean_audit(fm, gate, mods, config="{}", derived=None):
    checked(fm, "lake", "build", *(f"+{module}:olean" for module in mods))
    extra = []
    if derived is not None:
        # 本轮源码层观察到的派生产物（证书）；环境层只据此豁免派生处理器的辅助函数。
        certificate = fm / ".lake" / "fm-derived.json"
        certificate.parent.mkdir(exist_ok=True)
        certificate.write_text(json.dumps(sorted(set(derived))))
        extra = ["--derived", str(certificate)]
    result = command(fm, "lake", "exe", "fm_audit", gate, *extra, *mods, stdin=config)
    if result.returncode not in (0, 1):
        raise Undetermined(result.stderr.strip() or f"Lean 审计退出 {result.returncode}")
    return result


def emit_findings(gate, result):
    findings = []
    for line in result.stdout.splitlines():
        if re.fullmatch(rf"GATE{gate} RED formal_math/\S+:\S+ [A-Z_]+ .+", line):
            findings.append(line)
        elif line.strip():
            raise Undetermined(f"审计输出无法识别：{line}")
    if result.returncode not in (0, 1) or bool(findings) != bool(result.returncode):
        raise Undetermined(result.stderr.strip() or f"Lean 审计退出 {result.returncode}")
    for line in findings:
        print(line)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def source_headers(root):
    fm = root / "formal_math"
    paths = {path.relative_to("formal_math").as_posix(): path for path in sources(root)}
    rows = checked(fm, "lake", "exe", "fm_audit", "headers", *paths).splitlines()
    if len(rows) != len(paths):
        raise Undetermined("Lean 前端没有返回完整的源码头部")
    return {paths[name]: (is_module, imports) for name, is_module, imports in map(json.loads, rows)}


def audit_sources(root, gate, headers=None, derived=None):
    fm = root / "formal_math"
    source = source_headers(root) if headers is None else headers
    local = {module_name(path): path for path in source}
    visiting, checked_sources, built = set(), set(), set()

    def visit(path):
        module = module_name(path)
        if module in checked_sources:
            return 0
        if module in visiting:
            raise Undetermined(f"{module}: 模块导入有环")
        visiting.add(module)
        is_module, imports = source[path]
        if gate == "3" and module not in AUDIT_TOOLS:
            denied = [line for _, line, import_all in imports if import_all]
            if denied:
                for line in denied:
                    red("3", path, line, "TOKEN", "禁止普通源码使用 import all")
                return 1
        targets = []
        for dependency, _, _ in imports:
            if dependency not in local:
                continue
            status = visit(local[dependency])
            if status:
                return status
            if dependency not in built:
                targets.append(dependency)
                built.add(dependency)
        if targets:
            checked(fm, "lake", "build", *(f"+{m}:olean" for m in targets))
        result = command(fm, "lake", "exe", "fm_audit", "source", module,
                         path.relative_to("formal_math").as_posix(), gate)
        if result.returncode not in (0, 1):
            raise Undetermined((result.stdout + result.stderr).strip())
        exposes, issues, made = json.loads(result.stdout)
        if derived is not None:
            derived.extend(made)
        relevant = [(line, detail) for number, line, detail in issues if number == gate]
        for line, detail in relevant:
            red(gate, path, line, "LOCAL_OPTION" if gate == "2" else "TOKEN", detail)
        if relevant:
            return 1
        for number, line, detail in issues:
            if number != "build":
                continue
            if gate != "2":
                raise Undetermined(result.stderr.strip() or f"{path}:{line}: {detail}")
            red("2", path, line, "BUILD_WFAIL", detail)
            print(result.stderr, file=sys.stderr, end="")
            return 1
        if gate == "15" and is_module and lane(module) == "Chan.Defs" and not exposes:
            red("15", path, 1, "EXPOSE_SECTION", "定义文件须用 @[expose] public section")
            return 1
        if result.returncode:
            raise Undetermined(f"{path}: Lean 前端未返回本门的红证据")
        visiting.remove(module)
        checked_sources.add(module)
        return 0

    for path in source:
        result = visit(path)
        if result:
            return source, result
    return source, 0


def gate3(root):
    derived = []
    source, failed = audit_sources(root, "3", derived=derived)
    mods = ["ChanTest.Probe"] if failed else [
        module_name(path) for path in source if module_name(path) not in AUDIT_TOOLS
    ]
    return max(failed, emit_findings("3", lean_audit(root / "formal_math", "3", mods, derived=derived)))


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"重复键：{key}")
        obj[key] = value
    return obj


def load_data(path):
    # 台账采用 YAML 1.2 的 JSON 子集；拒绝重复键，不猜测缩进或隐式类型。
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def formalization(fm):
    raw = load_data(fm / "formalization.yaml")
    if raw == []:
        raw = {}  # 第一片的空台账。
    if not isinstance(raw, dict):
        raise ValueError("formalization.yaml 需要对象")
    nodes, refinements = raw.get("nodes", {}), raw.get("refinements", {})
    normalized = []
    for name, conf in nodes.items():
        if not isinstance(conf, dict):
            raise ValueError(f"{name}: 节点登记需要对象")
        row = {"registration": "about" in conf and "mode" in conf}
        for field in ("about", "helpers"):
            values = conf.get(field, [])
            if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
                raise ValueError(f"{name}: {field} 需要非空字符串组成的数组")
            if len(set(values)) != len(values):
                raise ValueError(f"{name}: {field} 不允许重复")
            row[field] = values
        row["mode"] = conf.get("mode", "")
        exemptions = conf.get("doc_only", {})
        row["doc_only"] = []
        for key, reason in exemptions.items():
            if not re.fullmatch(r"[1-9][0-9]*", key) or not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"{name}: doc_only 需要从 1 起算的前提序号及理由")
            row["doc_only"].append((int(key), reason))
        for field in ("convenience",):
            row[field] = []
            for key, reason in conf.get(field, {}).items():
                if not re.fullmatch(r"[1-9][0-9]*", key) or not isinstance(reason, str) or not reason.strip():
                    raise ValueError(f"{name}: {field} 需要从 1 起算的前提序号及理由")
                row[field].append((int(key), reason.strip()))
        necessary = conf.get("necessary", [])
        if not isinstance(necessary, list):
            raise ValueError(f"{name}: necessary 需要前提序号数组")
        # 老台账非主定理的名字数组只用于历史回归；不视为主定理的登记。
        if necessary and all(isinstance(v, str) for v in necessary) and not conf.get("main_theorem"):
            necessary = []
        if not all(type(v) is int and v > 0 for v in necessary) or len(set(necessary)) != len(necessary):
            raise ValueError(f"{name}: necessary 需要互异的正整数前提序号")
        row["necessary"] = necessary
        for field in ("declarative_unique", "needs_necessity", "main_theorem"):
            row[field] = conf.get(field, False)
        normalized.append((name, row))
    return json.dumps({"nodes": normalized, "refinements": list(refinements.items())})


def compare_lock(fm, result):
    expect = load_data(fm / "statement-lock.json")
    path = "formal_math/statement-lock.json"
    if not isinstance(expect, dict):
        raise ValueError(f"{path} 需要对象")
    actual = {}
    for line in result.stdout.splitlines():
        name, mod, statement = json.loads(line)
        payload = json.dumps(statement, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if name in actual:
            raise ValueError(f"声明名重复：{name}")
        actual[name] = (mod, hashlib.sha256(payload).hexdigest())
    failed = False
    for name in sorted(actual.keys() | expect.keys()):
        if name not in actual:
            red("6a", path, name, "LOCK_REMOVED", "锁定声明不在环境中")
        else:
            mod, digest = actual[name]
            if name in expect and digest == expect[name]:
                continue
            code = "LOCK_CHANGED" if name in expect else "LOCK_UNLISTED"
            red("6a", "formal_math/" + mod.replace(".", "/") + ".lean", name, code, f"现算 {digest}")
        failed = True
    return int(failed)


def report_signoffs(fm, declarations, counts):
    signoffs = load_data(fm / "verification/garbage-signoffs.yaml")
    expected = {}
    for name, entries in signoffs.items():
        for op, signoff in entries.items():
            count, review = signoff["count"], signoff["review"]
            if type(count) is not int or count < 1 or not isinstance(review, str) or not review.strip():
                raise ValueError(f"{name}: {op} 的签注需要正整数 count 与非空 review")
            expected[name, op] = count
    for name, op in sorted(counts.keys() | expected.keys()):
        actual, signed = counts[name, op], expected.get((name, op), 0)
        entry = declarations.get(name)
        if entry is not None and any(reading["status"] == "unknown" for reading in entry["readings"]["10"]):
            continue  # 缺少读数时，不能据此判签注过时。
        if actual == signed == 0:
            continue
        if actual > signed:
            code = "SIGNOFF_MISSING"
        elif actual == signed:
            code = "SIGNOFF_MATCH"  # 已签注，只作记录，不算发现。
        else:
            code = "SIGNOFF_STALE"
        if entry is None:
            entry = declarations.setdefault(name, {
                "module": None, "declaration": name, "readings": {gate: [] for gate in REPORT_GATES}
            })
        entry["readings"]["10"].append(reading("signed" if code == "SIGNOFF_MATCH" else "finding",
                                               "hint", code, f"{op} 实有 {actual} 处，签注 {signed} 处"))


REPORT_GATES = ("S", "7a", "7b", "8a", "8b", "9", "10")
TRUSTED_ROOTS = {"Chan", "ChanChallenge", "ChanDyn", "ChanTest"}


def reading(status, evidence, code, detail):
    return dict(status=status, evidence=evidence, code=code, detail=detail)


def review_report(root, report_dir=None):
    fm = root / "formal_math"
    mods = [m for path in sources(root) if (m := module_name(path)).partition(".")[0] in TRUSTED_ROOTS]
    result = lean_audit(fm, "report", mods, formalization(fm))
    if result.returncode:
        raise Undetermined("审阅报告未生成")
    declarations = {}
    counts = Counter()
    for line in result.stdout.splitlines():
        mod, name, *fields = json.loads(line)
        if fields == ["declaration"]:
            if name in declarations or mod not in mods:
                raise Undetermined(f"报告返回重复或未请求的声明：{mod}:{name}")
            declarations[name] = {
                "module": mod, "declaration": name, "readings": {gate: [] for gate in REPORT_GATES}
            }
            continue
        gate, status, *payload = fields
        if [gate, status] == ["10", "operation"]:
            op, = payload
            counts[name, op] += 1
        elif status in {"finding", "unknown"}:
            declarations[name]["readings"][gate].append(reading(status, *payload))
        else:
            raise Undetermined(f"无法识别报告事件：{status}")
    report_signoffs(fm, declarations, counts)
    rows = sorted(declarations.values(), key=lambda row: (row["module"] or "", row["declaration"]))
    table = ["| 模块 | 声明 | " + " | ".join(REPORT_GATES) + " |",
             "|" + " --- |" * (2 + len(REPORT_GATES))]
    for row in rows:
        cells = []
        for gate in REPORT_GATES:
            items = row["readings"][gate]
            if not items:
                items.append(reading("no_finding", "hint", "NO_FINDING", "无读数命中或不适用"))
            shown = [r for r in items if r["status"] != "no_finding"]
            cells.append("<br>".join(f"{r['evidence']}/{r['status']} {r['code']}: "
                                     f"{' '.join(r['detail'].split())}".replace("|", "\\|")
                                     for r in shown) or "—")
        if all(cell == "—" for cell in cells):
            continue  # 人读表只列有读数的声明；全部读数仍在 JSON 里。
        table.append("| " + " | ".join([row["module"] or "（仅签注）", row["declaration"], *cells]) + " |")
    document = json.dumps({"schema": "fm-review-v1", "declarations": rows}, ensure_ascii=False, indent=2)
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "report.json").write_text(document + "\n")
        (report_dir / "report.md").write_text("# FM 审阅报告\n\n" + "\n".join(table) + "\n")
    print("\n".join(table), file=sys.stderr)
    print(document)
    return 0


def gate6a(root):
    fm = root / "formal_math"
    mods = [module_name(path) for path in sources(root)]
    result = lean_audit(fm, "6a", mods)
    if result.returncode:
        raise Undetermined("审计枚举没有完成")
    return compare_lock(fm, result)


PATHS = {
    "decl": ("formal_math/Chan/Defs/", "formal_math/Chan/Hypotheses/", "formal_math/Chan/Audit/Literal/",
             "formal_math/ChanChallenge/", "formal_math/statement-lock.json",
             "formal_math/Chan/Proxy/", "formal_math/sources/",
             "formal_math/verification/garbage-signoffs.yaml",
             "formal_math/formalization.yaml", "formal_math/HISTORY.md", "formal_math/blueprint/"),
    "proof": ("formal_math/Chan/Thm/", "formal_math/Chan/Proofs/", "formal_math/ChanTest/",
              "formal_math/ChanDyn/", "formal_math/Chan/Exec/", "formal_math/Chan/Final.lean",
              "formal_math/Chan/Final/", "formal_math/Chan.lean"),
    "audit": ("formal_math/Chan/Audit/Math/", "formal_math/Chan/Audit/Separation/",
              "formal_math/Chan/Audit/Cases/", "formal_math/ChanTest/"),
    "infra": ("formal_math/verification/", "scripts/", ".github/workflows/", "formal_math/lakefile.toml",
              "formal_math/README.md", "formal_math/ChanExplore/", "formal_math/ChanExplore.lean"),
}
# 前置片尚未进 main 时，只从已验收且确为本 HEAD 祖先的原件接续。
# 不豁免任何路径；main 纳入前置片后，正常的 merge-base 自然优先。
ACCEPTED_LAYOUT = "c97fe37cdf1ce90a4b0c1cd7871a271154f032e1"


def within(path, rules):
    return any(path.startswith(rule) if rule.endswith("/") else path == rule for rule in rules)


SIGNOFF_PATH = "formal_math/verification/garbage-signoffs.yaml"


def initializes_empty_signoffs(root, base, head):
    if command(root, "git", "cat-file", "-e", f"{base}:{SIGNOFF_PATH}").returncode == 0:
        return False
    current = root / SIGNOFF_PATH
    if not current.is_file() or load_data(current) != {}:
        return False
    committed = command(root, "git", "show", f"{head}:{SIGNOFF_PATH}")
    staged = command(root, "git", "show", f":{SIGNOFF_PATH}")
    if committed.returncode == 0 and staged.returncode != 0:
        return False
    return all(json.loads(v.stdout, object_pairs_hook=unique_object) == {}
               for v in (committed, staged) if v.returncode == 0)


def gate6b(root):
    ref = command(root, "git", "symbolic-ref", "--quiet", "--short", "HEAD")
    if ref.returncode not in (0, 1):
        raise Undetermined(ref.stderr.strip())
    branch = ref.stdout.strip() if ref.returncode == 0 else os.environ.get("GITHUB_HEAD_REF", "").strip()
    if not branch:
        raise Undetermined("分离 HEAD 且缺少 GITHUB_HEAD_REF")
    prefix, marker, _ = branch.partition("/")
    head = checked(root, "git", "rev-parse", "HEAD").strip()
    base = checked(root, "git", "merge-base", "refs/remotes/origin/main", head).strip()
    if command(root, "git", "cat-file", "-e", f"{ACCEPTED_LAYOUT}^{{commit}}").returncode == 0:
        if all(command(root, "git", "merge-base", "--is-ancestor", a, b).returncode == 0
               for a, b in ((base, ACCEPTED_LAYOUT), (ACCEPTED_LAYOUT, head))):
            base = ACCEPTED_LAYOUT
    changes = set()
    # 分开查提交、暂存区、工作树，避免两个相反的改动互相抵消。
    for revisions in ((base, head), ("--cached", head), ()):
        changes.update(checked(root, "git", "diff", "--name-only", "-z", "--no-renames", *revisions).split("\0"))
    # 整个仓库的未跟踪文件都算改动，不只看三个目录。
    changes.update(checked(root, "git", "ls-files", "-z", "--others", "--exclude-standard").split("\0"))
    changes.discard("")
    if not marker or prefix not in PATHS or not branch.partition("/")[2].strip():
        red("6b", ".git/HEAD", 1, "BRANCH_PREFIX", f"分支 {branch} 没有可交付的路径权限")
        return 1
    failed = False
    for path in sorted(changes):
        # 符号链接能把受管路径之外的文件带进可写目录；改动里一律不许。
        if (root / path).is_symlink() or command(root, "git", "ls-files", "-s", "--", path).stdout.startswith("120000"):
            red("6b", path, 1, "SYMLINK", "改动不得包含符号链接")
            failed = True
            continue
        if within(path, PATHS[prefix]) and (
            path != SIGNOFF_PATH or prefix == "decl" or
            prefix == "infra" and initializes_empty_signoffs(root, base, head)
        ):
            continue
        red("6b", path, 1, "PATH_SCOPE", f"分支 {branch} 不允许修改此路径")
        failed = True
    return int(failed)


PROOF_LANES = {"Chan.Thm", "Chan.Proofs", "Chan.Exec"}
FOUNDATION = {"Chan.Defs", "Chan.Proxy", "Chan.Hypotheses"}
AUDIT_LANES = {"Chan.Audit", "Chan.Audit.Literal"}
AUDIT_TOOLS = {"verification.Audit", "verification.EnvGates", "verification.SourceGates",
               "verification.Perimeter", "verification.Inventory"}
EXTERNAL = {"Lean", "Init", "Std", "Mathlib", "Batteries", "Aesop", "Qq", "Plausible",
            "ProofWidgets", "LeanSearchClient", "ImportGraph", "Cli", "Lake"}


def allowed_edge(src, dst, local, transitive=False):
    a, b = lane(src), lane(dst)
    if dst not in local:
        external = dst.partition(".")[0]
        if a in {"ChanChallenge", "Chan.Audit.Literal"}:
            return external in {"Mathlib", "Init"}
        return external in EXTERNAL
    if src in AUDIT_TOOLS:
        return dst in AUDIT_TOOLS
    if not a or not b:
        return False
    if a == "ChanExplore":
        return True
    if b == "ChanExplore":
        return False
    if a in {"ChanChallenge", "Chan.Audit.Literal"}:
        return b in {
            "Chan.Defs", "Chan.Hypotheses", "Chan.Audit.Literal",
        }
    if a == "Chan.Defs":
        return b == "Chan.Defs"
    if a in {"Chan.Proxy", "Chan.Hypotheses"}:
        return b in {a, "Chan.Defs"}
    if a in PROOF_LANES:
        return b in FOUNDATION | PROOF_LANES
    if a in AUDIT_LANES:
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES
    if a == "Chan.Final":
        return b == "Chan.Thm" or transitive and b in FOUNDATION | PROOF_LANES
    if a == "ChanDyn":
        return b in FOUNDATION | PROOF_LANES | AUDIT_LANES | {"Chan", "Chan.Final", "ChanDyn"}
    if a == "ChanTest":
        return b not in {"ChanChallenge", "ChanExplore"}
    return b not in {"ChanChallenge", "ChanDyn", "ChanTest"}


def gate15(root):
    source = source_headers(root)
    local = {module_name(path) for path in source}
    graph = defaultdict(list)
    failed = False
    for path, (is_module, imports) in source.items():
        module = module_name(path)
        graph[module]
        if not is_module:
            red("15", path, 1, "MODULE_FIRST", "第一条命令必须为 module")
            failed = True
            continue
        for dst, line, import_all in imports:
            graph[module].append((dst, line))
            if dst == "Mathlib":
                red("15", path, line, "WHOLE_MATHLIB", "请只导入所需的 Mathlib 子模块")
                failed = True
            elif import_all and module not in AUDIT_TOOLS:
                red("15", path, line, "IMPORT_ALL", "仅审计工具能使用 import all")
                failed = True
            elif not allowed_edge(module, dst, local):
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
                if not allowed_edge(module, target, local, transitive=True):
                    red("15", path, line, "IMPORT_CLOSURE", f"经 {dst} 间接导入 {target}")
                    failed = True
                    break
                pending.extend(imported for imported, _ in graph.get(target, ()))
    if failed:
        return 1
    derived = []
    _, frontend = audit_sources(root, "15", source, derived=derived)
    if frontend:
        return frontend
    definitions = [m for m in graph if lane(m) == "Chan.Defs"]
    if definitions:
        return emit_findings("15", lean_audit(root / "formal_math", "15", definitions, derived=derived))
    return 0


GATES = {"1": gate1, "2": gate2, "3": gate3, "6a": gate6a, "6b": gate6b, "15": gate15}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--gate", choices=GATES)
    mode.add_argument("--stage", choices=("decl", "proof", "all"), default="all")
    mode.add_argument("--report", action="store_true",
                      help="生成不阻断的审阅报告：标准输出为 JSON，标准错误为人读表")
    parser.add_argument("--report-dir", type=Path, help="另把 report.json 与 report.md 写入此目录")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    if not (root / "formal_math").is_dir():
        print(f"FM: {root} 下找不到 formal_math", file=sys.stderr)
        return 2
    result = 0
    selected = {"报告": lambda root: review_report(root, args.report_dir)} if args.report else (
        {args.gate: GATES[args.gate]} if args.gate else GATES)
    if args.gate:
        print(f"FM: 只跑了门 {args.gate}；单门结论只覆盖该门的承诺，合入以全部阻断门（默认运行）为准。",
              file=sys.stderr)
    for number, action in selected.items():
        try:
            result = max(result, action(root))
        except (Undetermined, OSError, ValueError, KeyError, TypeError, AttributeError,
                subprocess.TimeoutExpired) as exc:
            print(f"GATE{number}: 无法判定：{exc}", file=sys.stderr)
            result = 2
    return result


if __name__ == "__main__":
    sys.exit(main())
