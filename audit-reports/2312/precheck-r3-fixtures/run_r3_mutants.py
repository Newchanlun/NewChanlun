#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R3：针对本轮新增代码的 8 种独立弱化自测，并抽核本轮新增用例的规则码。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r3_mutants.py [precheck.py] [selftest.py]
"""
import importlib.util
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
DEFAULT_SELFTEST = os.path.join(ROOT, "formal_math", "verification", "precheck", "selftest.py")

R3_MUTANTS = [
    ("R3-M1 无条件 shape 改回仅在 changed 非空时执行",
     "    shape(new, red)\n    file_objects(repo, new, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n"
     "    if base_form:\n"
     "        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])\n"
     "    changed = sorted(p for p in set(old) | set(new) if signature(p, old.get(p)) != signature(p, new.get(p)))",
     "    file_objects(repo, new, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n"
     "    if base_form:\n"
     "        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])\n"
     "    changed = sorted(p for p in set(old) | set(new) if signature(p, old.get(p)) != signature(p, new.get(p)))\n"
     "    if changed:\n        shape(new, red)"),
    ("R3-M2 signature 对祖先目录也比对象名（return entry）",
     "return None if entry is None else entry[:1] if path in ANCESTORS else entry",
     "return entry"),
    ("R3-M3 去掉 file_objects 调用（不做 blob 类型核对）",
     "    file_objects(repo, new, red)\n",
     "    pass\n"),
    ("R3-M4 LAKE_FILE 例外不再限制为 BLOB 文件",
     "if parts[-1].lower() in LAKE_NAMES and (kind != BLOB or path not in LAKE_ALLOWED):",
     "if parts[-1].lower() in LAKE_NAMES and path not in LAKE_ALLOWED:"),
    ("R3-M5 file_objects 漏排除 0o160000 子模块条目",
     "if int(mode, 8) & 0o170000 not in (0o040000, 0o160000)",
     "if int(mode, 8) & 0o170000 not in (0o040000,)"),
    ("R3-M6 shape 不检查 ANCESTORS 的 TREE_MODE（只检查 FM_ROOT）",
     "want = TREE_MODE if path in ANCESTORS or path == FM_ROOT else FILE_MODE if path in OUTSIDE else None",
     "want = TREE_MODE if path == FM_ROOT else FILE_MODE if path in OUTSIDE else None"),
    ("R3-M7 把 shape/file_objects 移到 BASE_FORM 之后（破坏先报被审红项次序）",
     "    new = inventory(repo, head, red)\n    shape(new, red)\n    file_objects(repo, new, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n"
     "    if base_form:\n        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])",
     "    new = inventory(repo, head, red)\n    base_form = []\n"
     "    old = inventory(repo, base, lambda *r: base_form.append(r))\n"
     "    if base_form:\n        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])\n"
     "    shape(new, red)\n    file_objects(repo, new, red)"),
    ("R3-M8 objects() 只在 body=True 时核对尾随多余字节（漏 --batch-check）",
     "    if pos != len(data):",
     "    if body and pos != len(data):"),
]


def main():
    precheck = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PRECHECK
    selftest = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SELFTEST
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("precheck_selftest_r3", selftest)
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    source = open(precheck, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="precheck-r3-mutants-")
    try:
        fixture = st.build(os.path.join(tmp, "fixture"))
        # 先验证未改弱副本 + 抽核本轮新增用例（R2 前缀及新增用例）的精确规则码与输出
        base_script = os.path.join(tmp, "m_base", "precheck.py")
        os.makedirs(os.path.dirname(base_script))
        with open(base_script, "w", encoding="utf-8") as f:
            f.write(source)
        t0, f0 = st.suite(base_script, None, verbose=True, fixture=fixture)
        print(f"[BASELINE] 未改弱副本: {f0}/{t0} failed", flush=True)
        if f0 != 0:
            raise RuntimeError("未改弱副本未全过")

        repo, base, heads, parents = fixture
        new_case_names = [
            "R2 只改 ci.yml proof",
            "R2 只改 ci.yml infra 无放行",
            "R2-B1a scripts 目录模式改成 040000 main",
            "R2-B1a .github/workflows 目录模式改成 040755 infra 放行",
            "R2 基线里的祖先目录已不规范且未改",
            "R2-B1b 受信文件不存在时 scripts 换成符号链接 main",
            "R2-M10 门禁目录节点自身模式改成 040000 infra 无放行",
            "R2-M2 树对象里对象名截断",
            "文件条目指向树对象（内容根）",
            "文件条目指向树对象（sources）",
            "Lake 配置名：例外路径是目录",
        ]
        print("=== 抽核本轮新增自测用例实际输出与规则码 ===", flush=True)
        for case in st.CASES:
            name, _, branch, approved, rc, want, *_ = case
            if name in new_case_names:
                argv = (["--trusted-change-approved"] if approved else []) + [repo.path, parents[name], heads[name], st.b(branch)]
                got_rc, got_out, got_err = st.run(base_script, argv)
                got_codes = st.codes(got_out, got_err)
                ok = got_rc == rc and got_codes == want
                print(f"  [{'PASS' if ok else 'FAIL'}] {name}: rc={got_rc} codes={sorted(got_codes or ())} | {got_out.decode('utf-8', 'replace').strip().replace(chr(10), ' // ')}", flush=True)

        print("=== R3 独立弱化自测（8 种） ===", flush=True)
        for i, (name, old, new) in enumerate(R3_MUTANTS):
            cnt = source.count(old)
            if cnt != 1:
                raise RuntimeError(f"{name}: 改弱点出现次数 {cnt} != 1")
            d = os.path.join(tmp, f"m{i}")
            os.makedirs(d)
            script = os.path.join(d, "precheck.py")
            with open(script, "w", encoding="utf-8") as f:
                f.write(source.replace(old, new))
            total, failed = st.suite(script, None, verbose=False, fixture=fixture)
            status = "KILLED" if failed > 0 else "SURVIVED"
            print(f"[{status}] {name}: {failed}/{total} failed", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
