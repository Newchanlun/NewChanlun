#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R2：10 种独立弱化自测（区别于作者内置 15 种），聚焦原始树解析与集合差。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r2_mutants.py
"""
import importlib.util
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
DEFAULT_SELFTEST = os.path.join(ROOT, "formal_math", "verification", "precheck", "selftest.py")

CUSTOM_MUTANTS = [
    ("R2-M1 原始树排序键去掉目录结尾 /",
     'key = name + b"/" if is_tree(mode) else name',
     'key = name'),
    ("R2-M2 原始树解析去掉哈希截断边界检查",
     'if not m or m.end() + hash_len > len(body):',
     'if not m:'),
    ("R2-M3 is_tree 只认字面 40000 而不按位掩码判目录",
     'return int(mode, 8) & 0o170000 == 0o040000',
     'return mode == TREE_MODE'),
    ("R2-M4 cat-file 解析去掉尾随多余字节检查",
     'if pos != len(data):',
     'if False:'),
    ("R2-M5 集合差忽略原始模式差异、只比对象名",
     'if p not in ANCESTORS and old.get(p) != new.get(p)',
     'if p not in ANCESTORS and (old.get(p) or (None, None))[1] != (new.get(p) or (None, None))[1]'),
    ("R2-M6 集合差漏掉仅存在于基线的路径（忽略纯删除）",
     'for p in set(old) | set(new)',
     'for p in set(new)'),
    ("R2-M7 忽略基线树规范性检查 BASE_FORM",
     'if base_form:\n        raise Fault("BASE_FORM"',
     'if False:\n        raise Fault("BASE_FORM"'),
    ("R2-M8 LAKE_FILE 去掉 ASCII 小写折叠",
     'if parts[-1].lower() in LAKE_NAMES and path not in LAKE_ALLOWED:',
     'if parts[-1] in LAKE_NAMES and path not in LAKE_ALLOWED:'),
    ("R2-M9 重名条目允许后条覆盖前条（去掉 sub not in found）",
     'if managed(sub) and sub not in found:',
     'if managed(sub):'),
    ("R2-M10 TRUST_UNAPPROVED 去掉 GATE_DIR 节点自身判断",
     'any(p == GATE_DIR or within(p, TRUSTED_SURFACE) for p in changed)',
     'any(within(p, TRUSTED_SURFACE) for p in changed)'),
]


def run_suite_on_repo(st, script, repo, base, heads, parents):
    """等价于 selftest.suite()，复用同一份只读夹具仓，每次清理 special() 生成的 corrupt 副本。"""
    corrupt = os.path.join(os.fsencode(os.path.dirname(os.fsdecode(repo.path))), b"corrupt")
    shutil.rmtree(corrupt, ignore_errors=True)
    results = []
    for name, _, branch, approved, rc, want, *_ in st.CASES:
        argv = [repo.path, parents[name], heads[name], st.b(branch)]
        got = st.run(script, (["--trusted-change-approved"] if approved else []) + argv)
        green_line = got[0] != 0 or got[1] == b"PRECHECK GREEN OK %s role=%s\n" % (
            heads[name].encode(),
            (branch.split("/")[0] if re.fullmatch(r"(decl|proof|audit|infra)/\S+", branch) else "-").encode())
        results.append((name, got[0] == rc and st.codes(got[1], got[2]) == want and bool(green_line), got))
    results += st.special(script, repo, base, heads) + st.tables(script)
    failed = [r for r in results if not r[1]]
    return len(results), len(failed)


def main():
    precheck = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PRECHECK
    selftest = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SELFTEST
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("precheck_selftest", selftest)
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    source = open(precheck, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="precheck-r2-mutants-")
    try:
        repo_dir = os.path.join(tmp, "shared_repo")
        os.makedirs(repo_dir)
        repo, base, heads, parents = st.build(repo_dir)
        base_script = os.path.join(tmp, "m_base", "precheck.py")
        os.makedirs(os.path.dirname(base_script))
        with open(base_script, "w", encoding="utf-8") as f:
            f.write(source)
        t0, f0 = run_suite_on_repo(st, base_script, repo, base, heads, parents)
        print(f"[BASELINE] 未改弱副本: {f0}/{t0} failed", flush=True)
        if f0 != 0:
            raise RuntimeError("未改弱副本未全过")
        for i, (name, old, new) in enumerate(CUSTOM_MUTANTS):
            cnt = source.count(old)
            if cnt != 1:
                raise RuntimeError(f"{name}: 改弱点出现次数 {cnt} != 1")
            d = os.path.join(tmp, f"m{i}")
            os.makedirs(d)
            script = os.path.join(d, "precheck.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(source.replace(old, new))
            total, failed = run_suite_on_repo(st, script, repo, base, heads, parents)
            status = "KILLED" if failed > 0 else "SURVIVED"
            print(f"[{status}] {name}: {failed}/{total} failed", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
