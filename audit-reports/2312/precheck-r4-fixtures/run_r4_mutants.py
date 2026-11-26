#!/usr/bin/env python3
"""#2312 第一片（precheck.py）独立审阅 R4：抽核本轮新增自测用例 + 10 种针对 R4 新增代码的独立弱化自测。

用法：
  TMPDIR=/Volumes/AgentStorage/tmp python3 -I run_r4_mutants.py [precheck.py] [selftest.py]
"""
import importlib.util
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_PRECHECK = os.path.join(ROOT, "formal_math", "verification", "precheck", "precheck.py")
DEFAULT_SELFTEST = os.path.join(ROOT, "formal_math", "verification", "precheck", "selftest.py")

R4_MUTANTS = [
    ("R4-M1 祖先重新进入改动集合（去掉 p not in ANCESTORS）",
     "if p not in ANCESTORS and old.get(p) != new.get(p)",
     "if old.get(p) != new.get(p)"),
    ("R4-M2 p not in ANCESTORS 误写成前缀匹配（连带放掉其下受信文件）",
     "if p not in ANCESTORS and old.get(p) != new.get(p)",
     "if not any(p == a or p.startswith(a + b\"/\") for a in ANCESTORS) and old.get(p) != new.get(p)"),
    ("R4-M3 基线不走 normative()（只走 inventory，漏基线文件对象类型）",
     "old = normative(repo, base, lambda *r: base_form.append(r))",
     "old = inventory(repo, base, lambda *r: base_form.append(r))"),
    ("R4-M4 normative() 里把 shape 与 file_objects 顺序调换（先对象类型后形状）",
     "    if with_shape:\n        shape(tree, red)\n    file_objects(repo, tree, red)\n",
     "    file_objects(repo, tree, red)\n    if with_shape:\n        shape(tree, red)\n"),
    ("R4-M5 normative() 对基线也错做 shape()（with_shape 默认 True）",
     "def normative(repo, commit, red, with_shape=False):",
     "def normative(repo, commit, red, with_shape=True):"),
    ("R4-M6 被审调用 normative() 漏传 with_shape=True",
     "new = normative(repo, head, red, with_shape=True)",
     "new = normative(repo, head, red)"),
    ("R4-M7 base_form 收集后被吞掉不抛 BASE_FORM",
     "    if base_form:\n        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])",
     "    if False:\n        raise Fault(\"BASE_FORM\", base_form[0][1], \"基线树不规范：\" + base_form[0][2])"),
    ("R4-M8 基线 normative() 错传 head 的 red 回调（BASE_FORM 退 2 退化成 TREE_FORM 退 1）",
     "old = normative(repo, base, lambda *r: base_form.append(r))",
     "old = normative(repo, base, red)"),
    ("R4-M9 shape() 漏查 ANCESTORS 的 TREE_MODE（祖先不进改动集合后将重开 R2-B1）",
     "want = TREE_MODE if path in ANCESTORS or path == FM_ROOT else FILE_MODE if path in OUTSIDE else None",
     "want = TREE_MODE if path == FM_ROOT else FILE_MODE if path in OUTSIDE else None"),
    ("R4-M10 去掉 file_objects() 空清单短路（行为等价探针：观察自测是否可区分）",
     "    if not files:\n        return\n",
     "    pass\n"),
]


def main():
    precheck = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PRECHECK
    selftest = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SELFTEST
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("precheck_selftest_r4", selftest)
    st = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(st)
    source = open(precheck, encoding="utf-8").read()
    tmp = tempfile.mkdtemp(prefix="precheck-r4-mutants-")
    try:
        fixture = st.build(os.path.join(tmp, "fixture"))
        base_script = os.path.join(tmp, "m_base", "precheck.py")
        os.makedirs(os.path.dirname(base_script))
        with open(base_script, "w", encoding="utf-8") as f:
            f.write(source)
        t0, f0 = st.suite(base_script, None, verbose=True, fixture=fixture)
        print(f"[BASELINE] 未改弱副本: {f0}/{t0} failed", flush=True)
        if f0 != 0:
            raise RuntimeError("未改弱副本未全过")

        repo, base, heads, parents = fixture
        spot_names = [
            "R3-B1 基线 文件条目指向树，被审原样",
            "R3-B1 基线 文件条目指向树，被审修复",
            "R3-B1 基线 文件条目指向提交，被审删除",
            "R3-B1 基线 文件条目指向缺失对象，被审删除",
            "R3-B1 基线 fm_env.sh 指向树，infra 放行修复",
            "R3 被审符号链接指向缺失对象：先报 MODE 再退 2",
            "R3-M7 基线树不规范时被审红项先报出",
            "R3-B2 无 formal_math：新增第一个 scripts/foo.sh（proof/x）",
            "R3-B2 无 formal_math：删除最后一个 ci.yml（main）",
            "R3-B2 有 formal_math 无 fm_env.sh：新增第一个 scripts/foo.sh（whatever name）",
            "R3-B2 祖先存在且合法：只改兄弟 scripts/other.sh（main）",
        ]
        print("=== 抽核本轮新增自测用例实际输出与规则码 ===", flush=True)
        found_spot = 0
        for case in st.CASES:
            name, _, branch, approved, rc, want, *_ = case
            if name in spot_names:
                found_spot += 1
                argv = (["--trusted-change-approved"] if approved else []) + [repo.path, parents[name], heads[name], st.b(branch)]
                got_rc, got_out, got_err = st.run(base_script, argv)
                got_codes = st.codes(got_out, got_err)
                ok = got_rc == rc and got_codes == want
                out_s = got_out.decode("utf-8", "replace").strip().replace("\n", " // ")
                err_s = got_err.decode("utf-8", "replace").strip().replace("\n", " // ")
                print(f"  [{'PASS' if ok else 'FAIL'}] {name}: rc={got_rc} codes={sorted(got_codes or ())} | out={out_s!r} | err={err_s!r}", flush=True)
        assert found_spot == len(spot_names), f"missing spot cases: {found_spot} != {len(spot_names)}"

        print("=== R4 独立弱化自测（10 种） ===", flush=True)
        for i, (name, old, new) in enumerate(R4_MUTANTS):
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
    raise SystemExit(main())
