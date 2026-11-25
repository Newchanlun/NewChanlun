#!/usr/bin/env python3
"""门禁 11 自测：阻断检查的必红样本、引文报告的必报样本，以及对自测本身的反向检验。
退出 0 全部符合预期，1 有不符。用法：python3 -I formal_math/verification/gate11/selftest.py
样例里的引文标记都放在 fixtures/ 下（扫描时被排除），本文件里不写字面标记。
"""
import importlib.util, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gate11_common", HERE / "_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
ROOT = C.default_root()
NESTED = os.environ.get("GATE11_SELFTEST_NESTED") == "1"
RESULTS = []
GATE_REL = Path("formal_math/verification/gate11")
OLD_137 = '"author_spans": [[35, 72], [78, 191]]'
NEW_137 = '"author_spans": [[35, 191]]'


def run(script, *args, at=None, env=None):
    d = (at / GATE_REL) if at else HERE
    e = dict(os.environ, **(env or {}))
    p = subprocess.run([sys.executable, "-I", str(d / script), *map(str, args)], capture_output=True, text=True,
                       encoding="utf-8", env=e)
    return p.returncode, p.stdout, p.stderr


def expect(name, cond, note=""):
    RESULTS.append(bool(cond))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("  — " + note) if note and not cond else ""))


def mk_root(tmp, with_gate=False):
    r = Path(tmp)
    shutil.copytree(ROOT / C.ADMIT_REL, r / C.ADMIT_REL)
    shutil.copytree(ROOT / C.BLOG_REL, r / C.BLOG_REL)
    if with_gate:  # 门禁代码也拷一份（含钉选清单），改了钉选清单就能单独检验更深一层
        shutil.copytree(HERE, r / GATE_REL, ignore=shutil.ignore_patterns("__pycache__"))
    return r


def sums(root, pin=False):
    """重算 SHA256SUMS；pin=True 时把门禁副本里的钉选清单也同步（模拟「钉选一起换」，只用来单独检验更深的检查层）。"""
    a = root / C.ADMIT_REL
    lines = []
    for dp, dn, fn in os.walk(a):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), a).replace(os.sep, "/")
            if rel != "SHA256SUMS":
                lines.append((rel, C.sha256_bytes((a / rel).read_bytes())))
    lines.sort()
    (a / "SHA256SUMS").write_text("".join("%s  ./%s\n" % (h, r) for r, h in lines), encoding="utf-8")
    if pin:
        pf = root / GATE_REL / "pinned_admit.sha256"
        old = [l for l in pf.read_text(encoding="utf-8").splitlines()]
        new = []
        for l in old:
            if l.startswith("#") or not l.strip():
                new.append(l)
            else:
                rel = l.split("  ", 1)[1]
                new.append("%s  %s" % (C.sha256_bytes((a / rel).read_bytes()), rel))
        pf.write_text("\n".join(new) + "\n", encoding="utf-8")


def rows_of(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def enc(rr):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rr)


def line_of(r):
    return C.Corpus(ROOT / C.BLOG_REL).line(r["lesson"], r["line"])


def sub1(path, old, new):
    s = path.read_text(encoding="utf-8")
    assert old in s, (path, old)
    path.write_text(s.replace(old, new, 1), encoding="utf-8")


def tamper_137(s):  # 反向检验会改写这里：把「放回被剔除的字」换成只翻 passes_agree
    return s.replace(OLD_137, NEW_137, 1)


def mutate(root, case):
    """对应独审报告 B2 表里的模式名。返回需要同步清单与否由调用方决定。"""
    a = root / C.ADMIT_REL
    PA, PB, T = a / "pass-a/tier1.jsonl", a / "pass-b/tier1.jsonl", a / C.TABLE_REL
    if case in ("swap-id", "swap-one", "drop-id", "add-id", "restore-votes"):
        for f in (PA, PB, T):
            if case == "swap-one" and f != PA:
                continue
            rr = rows_of(f)
            if case in ("swap-id", "swap-one"):
                rr[0]["id"] = 900001
            elif case == "drop-id":
                rr.pop()
            elif case == "add-id":
                rr.append(dict(rr[-1], id=900001))
            else:
                r = next(r for r in rr if r["id"] == 1259)
                r.update(author_spans=r["quote_spans"], verdict="clean")
                s = line_of(r)
                r["author_text_sha256"] = C.sha256_bytes("".join(s[x:y] for x, y in r["quote_spans"]).encode())
                if f == T:
                    r.update(pass_a={"verdict": "clean", "kind": "none"}, pass_b={"verdict": "clean", "kind": "none"})
                else:
                    r.update(nonauthor_kind="none", reason="干净")
            f.write_text(enc(rr), encoding="utf-8")
    elif case in ("no-cut", "no-cut-synced", "cut-bad", "cut-reason"):
        f = a / "candidate/adjudications.json"
        data = json.loads(f.read_text(encoding="utf-8"))
        if case == "cut-bad":
            data["exclude"][0]["text"] = "不是该处的字"
        elif case == "cut-reason":
            data["exclude"][0]["reason"] = "夹具替换说明"
        else:
            data["exclude"] = [v for v in data["exclude"] if v["id"] not in (137, 138)]
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if case == "no-cut-synced":
            rr = rows_of(T)
            for r in rr:
                if r["id"] in (137, 138):
                    r.update(author_spans=r["quote_spans"], verdict="clean", adjudicated=False)
                    r["author_text_sha256"] = C.sha256_bytes("".join(line_of(r)[x:y] for x, y in r["quote_spans"]).encode())
            T.write_text(enc(rr), encoding="utf-8")
    elif case in ("corpus", "corpus-only"):
        if case == "corpus":
            f = next((root / C.BLOG_REL).glob("017-*.md"))
            ls = f.read_text(encoding="utf-8").split("\n")
            assert ls[39][72:78] == "“一分为二”"
            ls[39] = ls[39][:73] + "三" + ls[39][74:]
        else:
            f = next((root / C.BLOG_REL).glob("000-*.md"))
            ls = f.read_text(encoding="utf-8").split("\n")
            ls[25] = "合" + ls[25][1:]
        f.write_text("\n".join(ls), encoding="utf-8")
    elif case.startswith("spec"):
        sub1(a / "SPEC.md", "790 条", "791 条")
    elif case.startswith("merge"):
        f = a / "candidate/merge.py"
        if case == "merge-different":
            sub1(f, 'agree = a["author_spans"] == b["author_spans"]', "agree = True")
        else:
            sub1(f, 'if not agree: disputes.append(row["id"])', "pass  # 不再记分歧清单；不影响表")
    elif case.startswith("shim"):
        f = root / GATE_REL / "merge_shim/lib.py"
        sub1(f, "_cache[k] = (lines, mark, fn[0])",
             "_cache[k] = ([], mark, fn[0])" if case == "shim-different" else "_cache[k] = (lines, None, fn[0])")
    else:
        raise ValueError(case)


# 模式 -> (是否同步 SHA256SUMS, 预期退出码, 应出现在标准错误里的子串)
B2_CASES = [
    ("swap-id", True, 1, ["钉选", "tier1_candidate.jsonl"]),
    ("swap-one", True, 1, ["钉选", "pass-a/tier1.jsonl"]),
    ("drop-id", True, 1, ["钉选", "pass-b/tier1.jsonl"]),
    ("add-id", True, 1, ["钉选", "pass-a/tier1.jsonl"]),
    ("restore-votes", True, 1, ["钉选", "pass-a/tier1.jsonl", "tier1_candidate.jsonl"]),
    ("no-cut", False, 1, ["重建差分"]),
    ("no-cut-synced", True, 1, ["钉选", "adjudications.json", "tier1_candidate.jsonl"]),
    ("cut-bad", True, 1, ["钉选", "adjudications.json"]),
    ("cut-reason", True, 1, ["钉选", "adjudications.json"]),
    ("corpus-only", False, 1, ["语料指纹"]),
    ("corpus", False, 1, ["语料指纹"]),
    ("spec-stale", False, 1, ["SPEC.md"]),
    ("spec-refresh", True, 1, ["钉选", "SPEC.md"]),
    ("merge-stale", False, 1, ["merge.py"]),
    ("merge-refresh", True, 1, ["钉选", "merge.py"]),
    ("merge-different", True, 1, ["钉选", "merge.py"]),
    ("shim-different", True, 1, ["重建"]),
    ("shim-same", True, 0, []),  # 替身返回的界标不影响 merge.py 用到的行列表，重建合同下应仍绿
]


def block_cases():
    print("== 阻断检查：身份钉选（独审 B2）==")
    for case, sync, rc_want, subs in B2_CASES:
        with tempfile.TemporaryDirectory() as t:
            r = mk_root(t, with_gate=True)
            mutate(r, case)
            if sync:
                sums(r)
            rc, out, err = run("check_admit_table.py", "--root", r, at=r)
            ok = rc == rc_want and all(x in err for x in subs) and (rc_want != 0 or not err)
            expect("%s：退 %d，诊断含 %s" % (case, rc_want, subs), ok, "rc=%d %s" % (rc, err[:400]))

    print("== 阻断检查：钉选之外各层独立可红（钉选清单同步换掉后单独检验）==")
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("正常：退 0，无红行", rc == 0 and not err, err[:200])
    rc, _, err = run("check_admit_table.py")
    expect("真仓库：退 0", rc == 0, err[:200])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        T = r / C.ADMIT_REL / C.TABLE_REL
        b = bytearray(T.read_bytes())
        i = b.index(b'"author_text_sha256": "') + len(b'"author_text_sha256": "')
        b[i] = ord("0") if b[i] != ord("0") else ord("1")
        T.write_bytes(bytes(b))
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("准入表改一个字节（不同步）：钉选与摘要清单都点名该文件",
               rc == 1 and "钉选" in err and "摘要不符: candidate/tier1_candidate.jsonl" in err, err[:300])
        sums(r, pin=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("  钉选与清单同步换掉后：作者文字摘要与重建差分各自点到 id 1",
               rc == 1 and "[作者文字摘要] id 1 " in err and re.search(r"\[重建差分\] 第 1 行（id 1）", err), err[:400])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        T = r / C.ADMIT_REL / C.TABLE_REL
        T.write_text(tamper_137(T.read_text(encoding="utf-8")), encoding="utf-8")
        sums(r, pin=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("把 017:40 被剔除的字放回 137 的作者区间：作者文字摘要与重建差分都点到 id 137",
               rc == 1 and "[作者文字摘要] id 137 " in err and re.search(r"\[重建差分\] 第 \d+ 行（id 137）", err), err[:400])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        T = r / C.ADMIT_REL / C.TABLE_REL
        sub1(T, '"passes_agree": true', '"passes_agree": false')
        sums(r, pin=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("只翻 passes_agree 且钉选同步：只有重建差分红，作者文字摘要不红",
               rc == 1 and "[重建差分]" in err and "[作者文字摘要]" not in err, err[:300])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        T = r / C.ADMIT_REL / C.TABLE_REL
        ls = T.read_text(encoding="utf-8").splitlines(True)
        T.write_text("".join(ls[:-1]), encoding="utf-8")
        sums(r, pin=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("删一行且钉选同步：行数与重建差分红", rc == 1 and "[行数]" in err and "[重建差分]" in err, err[:300])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        mutate(r, "cut-reason")
        sums(r, pin=True)
        rc, _, err = run("check_admit_table.py", "--root", r, at=r)
        expect("信任前提（README 明写）：原件与钉选清单在同一次改动里一起换，本检查拦不住（只换理由文字）", rc == 0, err[:200])

    print("== 阻断检查：缺输入 ==")
    with tempfile.TemporaryDirectory() as t:
        rc, _, err = run("check_admit_table.py", "--root", t)
        expect("缺整个 admit 目录：退 2，点名目录", rc == 2 and "sources/admit" in err and "tier1_candidate" not in err, err[:200])
        (Path(t) / C.ADMIT_REL).mkdir(parents=True)
        (Path(t) / C.BLOG_REL).mkdir(parents=True)
        rc, _, err = run("check_admit_table.py", "--root", t)
        expect("admit 与语料目录在、缺准入表文件：退 2，点名 tier1_candidate.jsonl", rc == 2 and "tier1_candidate.jsonl" in err, err[:200])


def parse_fixture(text):
    out = []
    for i, l in enumerate(text.split("\n"), 1):
        m = re.search(r"<!--case:(\S+) (.*?)-->", l)
        if m:
            kv = dict(x.split(":", 1) for x in m.group(2).split())
            out.append(dict(name=m.group(1), line=i, text=l, kv=kv))
    return out


REQUIRED = ["bridge", "single-id", "repeat-in-out", "excluded17", "excluded46", "excluded54", "splice",
            "splice-also-outside", "across-gap", "reverse", "duplicate", "missing-ellipsis", "nbsp-original",
            "ascii-space", "ideographic-space", "halfwidth-punct", "table-miss", "two", "other-speaker",
            "four-digit", "two-digit", "wide-colon", "multi-number", "nested", "alternate-bracket", "cross-line"]


def report_cases():
    print("== 引文报告：夹具逐条 ==")
    fx = (HERE / "fixtures/cites.md").read_text(encoding="utf-8")
    cases = parse_fixture(fx)
    names = {c["name"] for c in cases}
    expect("夹具含独审报告的全部模式名", set(REQUIRED) <= names, "缺 %s" % sorted(set(REQUIRED) - names))
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        scan = r / "formal_math/scan"
        scan.mkdir(parents=True)
        (scan / "cites.md").write_text(fx, encoding="utf-8")
        rc, out, err = run("report_citations.py", "--root", r, "--scan", scan, "--json", r / "r.json")
        expect("夹具里有大量坏引文，成功生成报告退 0", rc == 0, "rc=%d %s" % (rc, err[:200]))
        rep = json.loads((r / "r.json").read_text(encoding="utf-8"))
        by_line, unp = {}, {}
        for c in rep["citations"]:
            by_line.setdefault(c["line"], []).append(c)
        for u in rep["unparsed_markers"]:
            unp.setdefault(u["line"], []).append(u)
        want_total = want_unp = 0
        for c in cases:
            kv, ln = c["kv"], c["line"]
            if "expect" in kv:
                want = kv["expect"].split(",")
                want_total += len(want)
                got = by_line.get(ln, [])
                expect("%s（行 %d）：读数 %s" % (c["name"], ln, want), [g["status"] for g in got] == want,
                       "实得 %s" % [g["status"] for g in got])
                if "ids" in kv and got:
                    ids = sorted({h["id"] for h in got[0]["hits"]})
                    expect("  %s：命中 id %s，且附字符起止" % (c["name"], kv["ids"] or "无"),
                           ids == [int(x) for x in kv["ids"].split(",") if x]
                           and all(len(h["span"]) == 2 for h in got[0]["hits"]), "实得 %s" % got[0]["hits"])
                if "outside" in kv and got:
                    expect("  %s：读数注明该行另有区间外出现" % c["name"],
                           got[0]["outside_also"] and "另有区间外出现" in got[0]["detail"])
            elif "unparsed" in kv:
                want_unp += 1
                col = c["text"].index("【") + 1
                got = [u for u in unp.get(ln, []) if kv["unparsed"] in u["reason"]]
                expect("%s（行 %d 列 %d）：进未解析，原因含「%s」" % (c["name"], ln, col, kv["unparsed"]),
                       len(got) == 1 and got[0]["col"] == col and not by_line.get(ln),
                       "实得 %s / %s" % (unp.get(ln), by_line.get(ln)))
        expect("引文总数与未解析总数等于夹具标注之和（%d、%d），无多无少" % (want_total, want_unp),
               len(rep["citations"]) == want_total and len(rep["unparsed_markers"]) == want_unp,
               "实得 %d、%d" % (len(rep["citations"]), len(rep["unparsed_markers"])))
    rc, _, err = run("report_citations.py", "--scan", ROOT / "不存在的目录")
    expect("扫描目录不存在：没有报告可读，退 2", rc == 2, "rc=%d" % rc)

    print("== 引文报告：扫描范围（独审 B6）==")
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        src = r / "formal_math/sources"
        shutil.copyfile(HERE / "fixtures/note.txt", src / "note.txt")
        shutil.copyfile(HERE / "fixtures/note.lean.txt", src / "note.lean")
        (src / "latin.dat").write_bytes("caf".encode() + b"\xe9 \xe3\x80")
        (src / "bin.dat").write_bytes(b"\x00\x01\x02")
        (src / C.ADMIT_REL.name / "extra.md").write_text("\u3010缠师 054:60\u3011\u300c*\u300d\n", encoding="utf-8")
        rc, out, err = run("report_citations.py", "--root", r, "--json", "-", at=r)
        rep = json.loads(out)
        files = {c["file"]: c["status"] for c in rep["citations"]}
        expect("非 .md/.lean 后缀（.txt）里的引文也被扫到", files.get("formal_math/sources/note.txt") == "quote_overlaps_excluded_text", str(files))
        expect(".lean 里的引文被扫到", files.get("formal_math/sources/note.lean") == "quote_overlaps_excluded_text", str(files))
        expect("sources/admit 下的文件被显式排除，不出读数", not any(f.startswith("formal_math/sources/admit/") for f in files))
        ex = {e["prefix"]: e["files"] for e in rep["excluded"]}
        expect("排除清单逐项带理由与文件数", ex.get("formal_math/sources/admit/", 0) >= 50
               and ex.get("formal_math/verification/gate11/fixtures/", 0) == 3 and all(e["reason"] for e in rep["excluded"]), str(ex))
        un = {u["path"]: u["reason"] for u in rep["unscanned"]}
        expect("非 UTF-8 文件与二进制文件列入未扫描，不静默跳过",
               "非 UTF-8" in un.get("formal_math/sources/latin.dat", "") and "NUL" in un.get("formal_math/sources/bin.dat", ""), str(un))
        expect("门禁自己的 README、脚本不产生引文或未解析噪音",
               not any(x["file"].startswith("formal_math/verification/gate11/")
                       for x in rep["citations"] + rep["unparsed_markers"]))
    rc, out, err = run("report_citations.py", "--json", "-")
    rep = json.loads(out)
    expect("对真实 formal_math 实跑：退 0，用 git 文件清单，输出排除计数",
           rc == 0 and rep["file_source"] == "git" and rep["excluded_files"] >= 50, "rc=%d" % rc)
    print("   ", err.strip().splitlines()[0] if err.strip() else "")


def meta_cases():
    """反向检验：把自测依赖的夹具或改坏动作弱化后，自测本身必须变红。"""
    print("== 反向检验：弱化夹具或改坏动作，自测必须红 ==")
    env = {"GATE11_SELFTEST_NESTED": "1"}
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        f = r / GATE_REL / "fixtures/cites.md"
        s = f.read_text(encoding="utf-8")
        s = re.sub(r"- \u3010缠师 011:26\u3011\u300c湿 <!--case:cross-line[^\n]*\n[^\n]*\n", "", s)
        assert "cross-line" not in s
        f.write_text(s, encoding="utf-8")
        rc, out, _ = run("selftest.py", at=r, env=env)
        expect("去掉跨行标记样例：自测红，且点名缺的模式名", rc == 1 and "cross-line" in out and "FAIL" in out, out[-300:])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        f = r / GATE_REL / "fixtures/cites.md"
        s = f.read_text(encoding="utf-8")
        s = re.sub(r"(<!--case:four-digit )unparsed:[^-]*-->", r"\1unparsed:不会出现的原因-->", s)
        f.write_text(s, encoding="utf-8")
        rc, out, _ = run("selftest.py", at=r, env=env)
        expect("把某条未解析原因标注改错：自测红", rc == 1 and "four-digit" in out, out[-300:])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        f = r / GATE_REL / "selftest.py"
        sub1(f, "    return s.replace(OLD_137, NEW_137, 1)",
             "    return s.replace('\"passes_agree\": true', '\"passes_agree\": false', 1)")
        rc, out, _ = run("selftest.py", at=r, env=env)
        expect("把「放回被剔除的字」换成只翻 passes_agree（区间不变）：自测红", rc == 1 and "id 137" in out and "FAIL" in out, out[-300:])
    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t, with_gate=True)
        f = r / GATE_REL / "check_admit_table.py"
        sub1(f, '        elif C.sha256_bytes(p.read_bytes()) != want:\n            fail("钉选"', '        elif False:\n            fail("钉选"')
        rc, out, _ = run("selftest.py", at=r, env=env)
        expect("把被测的钉选比对弱化：自测红", rc == 1 and "FAIL" in out, out[-300:])


def main():
    block_cases()
    report_cases()
    if not NESTED:
        meta_cases()
    bad = RESULTS.count(False)
    print("\n自测：%d 项，不符 %d" % (len(RESULTS), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
