#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R1：8 种独立弱化自测（区别于作者内置的 5 种）。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_custom_mutants.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
SELFTEST = os.path.join(ROOT, "formal_math", "verification", "precheck", "selftest.py")

CUSTOM_MUTANTS = [
    ("M1 去掉大小写冲突判断",
     'if twin != rel:\n            red("PATH_GRAMMAR"',
     'if False:\n            red("PATH_GRAMMAR"'),
    ("M2 第 7 步去掉 lean-toolchain 比对",
     'TRUSTED = TRUSTED_FILES + (GATE_DIR,)',
     'TRUSTED = tuple(p for p in TRUSTED_FILES if p != FM + b"lean-toolchain") + (GATE_DIR,)'),
    ("M3 祖先检查改成恒真",
     'if git(repo, b"merge-base", b"--is-ancestor", base, head, ok=(0, 1))[0]:',
     'if False:'),
    ("M4 分支名文法放宽（允许 .. 与首尾分隔符）",
     'WORD = rb"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"',
     'WORD = rb"[A-Za-z0-9._-]+"'),
    ("M5 去掉 diff-tree 的 --no-renames",
     'b"-r", b"-z", b"--no-renames", b"--raw"',
     'b"-r", b"-z", b"--raw"'),
    ("M6 受信文件模式检查漏掉 formal-math.yml",
     'for path in GOVERNED[1:]:',
     'for path in (b"scripts/fm_env.sh",):'),
    ("M7 放行开关在非 infra 角色下跳过 TRUSTED_DRIFT",
     'if role != b"infra":',
     'if role != b"infra" and not approved:'),
    ("M8 去掉空子树检查",
     'if kind == TREE and rel not in parents:',
     'if False:'),
]


def main():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("precheck_selftest", SELFTEST)
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    source = open(PRECHECK, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="precheck-r1-mutants-")
    try:
        for i, (name, old, new) in enumerate(CUSTOM_MUTANTS):
            if source.count(old) != 1:
                raise RuntimeError(f"{name}: 改弱点出现次数 {source.count(old)} != 1")
            d = os.path.join(tmp, f"m{i}")
            os.makedirs(d)
            script = os.path.join(d, "precheck.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(source.replace(old, new))
            total, failed = st.suite(script, d, verbose=False)
            status = "KILLED" if failed > 0 else "SURVIVED"
            print(f"[{status}] {name}: {failed}/{total} failed", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
