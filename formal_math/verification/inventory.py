"""收集精化器白名单的候选（维护工具，门禁不调用）。

对合法语料逐文件跑 `fm_audit inventory`，汇总语法种类、各处理表登记的处理器、信息树里实际
出现的精化器，以及每个处理器的所在模块、声明行与静态闭包里命中的危险常量，写成一份 JSON。
语料：`must_green/` 全部夹具、`report_cases/clean/` 全部夹具、`formal_math/Chan/` 现有源码。

用法（从仓库根，已 source scripts/fm_env.sh）：
    python3 formal_math/verification/inventory.py <输出.json> [增补夹具目录…]
"""

import json
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import selftest  # noqa: E402


def corpus():
    for group in ("must_green", "report_cases/clean"):
        for fixture in sorted((HERE / group).glob("*/*/")):
            if (fixture / "formal_math").is_dir():
                yield fixture
    yield None  # 仓库本身的 Chan/ 源码


def modules(fm):
    for path in sorted(fm.rglob("*.lean")):
        rel = path.relative_to(fm)
        if rel.parts[0] in {"verification", ".lake"}:
            continue
        yield ".".join(rel.with_suffix("").parts), rel.as_posix()


def collect(tmp, warm, fixture, sink):
    with selftest.fixture_repo(tmp, "inventory") as repo:
        env = selftest.fixture_env(repo)
        fm = repo / "formal_math"
        if fixture is None:
            fixture = Path(tempfile.mkdtemp(prefix="fm-chan-", dir=tmp))
            shutil.copytree(HERE.parent / "Chan", fixture / "formal_math/Chan")
            shutil.copy2(HERE.parent / "Chan.lean", fixture / "formal_math/Chan.lean")
            label = "Chan"
        else:
            label = str(fixture.relative_to(HERE))
        selftest.base_package(repo, fixture, warm)
        shutil.copytree(fixture / "formal_math", fm, dirs_exist_ok=True)
        mods = list(modules(fm))
        build = subprocess.run(["lake", "build", *(f"+{m}:olean" for m, _ in mods)],
                               cwd=fm, env=env, capture_output=True, text=True)
        if build.returncode:
            print(f"跳过（不能构建）：{fixture}", file=sys.stderr)
            return
        for mod, path in mods:
            result = subprocess.run(["lake", "exe", "fm_audit", "inventory", mod, path],
                                    cwd=fm, env=env, capture_output=True, text=True)
            if result.returncode:
                print(f"{fixture}:{path}: {result.stderr.strip()[:500]}", file=sys.stderr)
                continue
            for line in result.stdout.splitlines():
                row = json.loads(line)
                where = f"{label}:{path}"
                sink.append((row, where))


def scan(tmp, warm, imports, names):
    """在导入语料全部库模块的环境里，查每个名字的位置与静态闭包里的危险常量。"""
    with selftest.fixture_repo(tmp, "scan") as repo:
        env = selftest.fixture_env(repo)
        fixture = Path(tempfile.mkdtemp(prefix="fm-scan-", dir=tmp))
        (fixture / "formal_math/Chan").mkdir(parents=True)
        (fixture / "formal_math/Chan/Scan.lean").write_text(
            "module\n" + "".join(f"import {m}\n" for m in imports))
        selftest.base_package(repo, fixture, warm)
        shutil.copytree(fixture / "formal_math", repo / "formal_math", dirs_exist_ok=True)
        result = subprocess.run(["lake", "exe", "fm_audit", "inventory-scan", "Chan/Scan.lean"],
                                cwd=repo / "formal_math", env=env, capture_output=True, text=True,
                                input="\n".join(names))
        if result.returncode:
            raise SystemExit(result.stderr)
        out = {}
        for line in result.stdout.splitlines():
            name, module, line_no, dangers, present, paths = json.loads(line)
            out[name] = {"module": module, "line": line_no, "dangers": dangers, "present": present,
                         "paths": paths}
        return out


def main():
    out = Path(sys.argv[1])
    tmp = selftest.temporary_root()
    warm_root, warm = selftest.warm_build(tmp)
    rows = []
    cache = out.with_suffix(".rows.json")
    try:
        extra = [Path(a).resolve() for a in sys.argv[2:]]
        if cache.is_file():
            rows = [tuple(r) for r in json.loads(cache.read_text())]
            # 增补语料：只收新给的夹具，并入缓存。
            for fixture in extra:
                collect(tmp, warm, fixture, rows)
            if extra:
                cache.write_text(json.dumps(rows, ensure_ascii=False))
        else:
            for fixture in corpus():
                collect(tmp, warm, fixture, rows)
            cache.write_text(json.dumps(rows, ensure_ascii=False))
        document = summarize(tmp, warm, rows)
    finally:
        shutil.rmtree(warm_root)
    out.write_text(json.dumps(document, ensure_ascii=False, indent=1))
    print(f"种类 {len(document['kinds'])}，信息树精化器 {len(document['elaborators'])}，"
          f"处理器与精化器声明 {len(document['decls'])}")


def summarize(tmp, warm, rows):
    kinds, elabs, imports = {}, {}, set()
    for row, where in rows:
        if row[0] == "kind":
            entry = kinds.setdefault(row[1], {"handlers": set(), "seen": set()})
            entry["handlers"].update(tuple(h) for h in row[2])
            entry["seen"].add(where)
        elif row[0] == "elab":
            elabs.setdefault(row[2], set()).add((row[1], row[3]))
        elif row[0] == "import":
            if row[1].partition(".")[0] in {"Init", "Std", "Mathlib", "Batteries", "Lean", "Aesop", "Qq"}:
                imports.add(row[1])
    imports.add("Lean")  # 内建精化器编进了 fm_audit，声明在 Lean 包里
    names = set(elabs) | {n for v in kinds.values() for _, n in v["handlers"]}
    decls = scan(tmp, warm, sorted(imports), sorted(n for n in names if n))
    return {
        "kinds": {k: {"handlers": sorted(v["handlers"]), "seen": sorted(v["seen"])[:3]}
                  for k, v in sorted(kinds.items())},
        "elaborators": {k: sorted(v) for k, v in sorted(elabs.items())},
        "decls": dict(sorted(decls.items())),
    }


if __name__ == "__main__":
    main()
