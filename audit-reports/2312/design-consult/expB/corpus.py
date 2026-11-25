#!/usr/bin/env python3
"""原型驱动：把 gates-d 的夹具语料交给 Shape.lean（只解析、不精化），按夹具汇总命中。"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
VER = Path("/home/workspace/fm/wt/gates-d/formal_math/verification")
LIB_ROOTS = {"Init", "Std", "Mathlib", "Batteries"}
LEAN = ["flock", "-w", "1800", "/home/workspace/fm/lean.lock", "/home/workspace/fm/guard.sh",
        "lean", "--run", str(HERE / "Shape.lean")]
ENV = dict(os.environ, LEAN_PATH=(HERE / "leanpath.txt").read_text().strip())


def fixtures():
    for group in ("must_green", "must_red", "must_unknown"):
        for gate in sorted((VER / group).iterdir()):
            for case in sorted(gate.iterdir()):
                yield f"{group}/{gate.name}/{case.name}", case
    for kind in sorted((VER / "report_cases").iterdir()):
        for gate in sorted(kind.iterdir()):
            if not gate.is_dir():
                continue
            for case in sorted(gate.iterdir()):
                if case.is_dir():
                    yield f"report_cases/{kind.name}/{gate.name}/{case.name}", case


def lean_files(case):
    root = case / "formal_math"
    if not root.is_dir():
        return {}
    out = {}
    for path in sorted(root.rglob("*.lean")):
        rel = path.relative_to(root)
        if rel.parts[0] == "verification" or any(p.startswith(".") for p in rel.parts):
            continue
        if rel.name.startswith("lakefile"):
            continue
        out[".".join(rel.with_suffix("").parts)] = path
    return out


def main():
    cases = {name: lean_files(case) for name, case in fixtures()}
    paths = sorted({str(p) for files in cases.values() for p in files.values()})
    print(f"fixtures={len(cases)} lean_files={len(paths)}", file=sys.stderr)
    headers = {}
    for i in range(0, len(paths), 200):
        out = subprocess.run(LEAN + ["headers", *paths[i:i + 200]], env=ENV, text=True,
                             capture_output=True, cwd=HERE)
        if out.returncode:
            print(out.stderr[-2000:], file=sys.stderr)
            sys.exit(2)
        for line in out.stdout.splitlines():
            path, is_module, bad, imports = json.loads(line)
            headers[path] = (is_module, bad, imports)
    groups = defaultdict(list)
    for name, files in cases.items():
        for module, path in files.items():
            libs, seen, todo = set(), set(), [module]
            while todo:
                current = todo.pop()
                if current in seen or current not in files:
                    continue
                seen.add(current)
                for imp in headers[str(files[current])][2]:
                    if imp.split(".")[0] in LIB_ROOTS:
                        libs.add(imp)
                    else:
                        todo.append(imp)
            groups[",".join(sorted(libs))].append((name, module, str(path)))
    print(f"import_sets={len(groups)}", file=sys.stderr)
    results = defaultdict(list)
    for n, (libs, items) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        args = [f"{module}={path}" for _, module, path in items]
        out = subprocess.run(LEAN + ["scan", libs, "check", *args], env=ENV, text=True,
                             capture_output=True, cwd=HERE)
        rows = [json.loads(line) for line in out.stdout.splitlines() if line.startswith("{")]
        print(f"[{n + 1}/{len(groups)}] files={len(items)} rc={out.returncode} "
              f"{out.stderr.strip().splitlines()[-1][:160] if out.stderr.strip() else ''}", file=sys.stderr)
        by_path = {row["path"]: row for row in rows}
        for name, module, path in items:
            row = by_path.get(path) or {"path": path, "module": module, "commands": 0,
                                         "parse_error": f"scanner rc={out.returncode}: "
                                         f"{out.stderr.strip()[-300:]}", "issues": []}
            results[name].append(row)
    summary = {}
    for name in cases:
        rows = results.get(name, [])
        summary[name] = {
            "files": len(rows),
            "commands": sum(r["commands"] for r in rows),
            "parse_errors": [(Path(r["path"]).name, r["parse_error"][:200]) for r in rows if r["parse_error"]],
            "issues": [(Path(r["path"]).name, *i) for r in rows for i in r["issues"]],
        }
    (HERE / "corpus-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print("written corpus-result.json", file=sys.stderr)


if __name__ == "__main__":
    main()
