#!/usr/bin/env python3
"""门禁 11 自测：阻断检查必红样本与引文报告必报样本。退出 0 全部符合预期，1 有不符。
用法：python3 -I formal_math/verification/gate11/selftest.py
"""
import importlib.util, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("gate11_common", HERE / "_common.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
ROOT = C.default_root()
RESULTS = []


def run(script, *args):
    p = subprocess.run([sys.executable, "-I", str(HERE / script), *args], capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout, p.stderr


def expect(name, cond, note=""):
    RESULTS.append(bool(cond))
    print("%s  %s%s" % ("ok  " if cond else "FAIL", name, ("  — " + note) if note and not cond else ""))


def mk_root(tmp):
    """拷一份准入表与语料到临时仓库根，供改坏后检查。"""
    r = Path(tmp)
    shutil.copytree(ROOT / C.ADMIT_REL, r / C.ADMIT_REL)
    shutil.copytree(ROOT / C.BLOG_REL, r / C.BLOG_REL)
    return r


def resum(root):
    """改完文件后重算 SHA256SUMS，模拟「连清单一起改」的绕过。"""
    a = root / C.ADMIT_REL
    lines = []
    for dp, dn, fn in os.walk(a):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), a).replace(os.sep, "/")
            if rel != "SHA256SUMS":
                lines.append("%s  ./%s\n" % (C.sha256_bytes((a / rel).read_bytes()), rel))
    (a / "SHA256SUMS").write_text("".join(sorted(lines, key=lambda s: s.split("  ./")[1])), encoding="utf-8")


def block_cases():
    print("== 阻断检查 ==")
    with tempfile.TemporaryDirectory() as t:
        rc, out, err = run("check_admit_table.py", "--root", str(mk_root(t)))
        expect("正常：通过，退 0，无红行", rc == 0 and not err, "rc=%d %s" % (rc, err[:200]))
    real_rc, _, real_err = run("check_admit_table.py")
    expect("真仓库：通过", real_rc == 0, real_err[:200])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        last = sorted(f for f in os.listdir(r / C.BLOG_REL) if f.endswith(".md"))[-1]
        with open(r / C.BLOG_REL / last, "ab") as f:
            f.write("补".encode())
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("语料多一个字：指纹不符，退 1", rc == 1 and "语料指纹" in err and "≠ 基线" in err, err[:300])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        p = r / C.ADMIT_REL / C.TABLE_REL
        b = bytearray(p.read_bytes())
        i = b.index(b'"author_text_sha256": "') + len(b'"author_text_sha256": "')
        b[i] = ord("0") if b[i] != ord("0") else ord("1")
        p.write_bytes(bytes(b))
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("准入表改一个字节：退 1，摘要清单点名该文件",
               rc == 1 and "摘要不符: candidate/tier1_candidate.jsonl" in err, err[:300])
        expect("  同时报作者文字摘要与重建差分，并指到 id 1", "作者文字摘要" in err and "重建差分" in err and "id 1 " in err, err[:400])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        p = r / C.ADMIT_REL / C.TABLE_REL
        p.write_text(p.read_text(encoding="utf-8").replace('"passes_agree": true', '"passes_agree": false', 1), encoding="utf-8")
        resum(r)
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("连摘要清单一起改（只动 passes_agree）：重建差分仍红",
               rc == 1 and "摘要不符" not in err and "重建差分" in err, err[:300])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        p = r / C.ADMIT_REL / C.TABLE_REL
        ls = p.read_text(encoding="utf-8").splitlines(True)
        p.write_text("".join(ls[:-1]), encoding="utf-8")
        resum(r)
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("删一行并重算清单：行数与重建差分红", rc == 1 and "行数" in err and "重建差分" in err, err[:300])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        p = r / C.ADMIT_REL / C.TABLE_REL
        s = p.read_text(encoding="utf-8")
        # 把某条的 author_spans 放宽到含被剔除处（017:40 的「“一分为二”」），并重算清单：作者文字摘要须红
        s = s.replace('"author_spans": [[35, 72], [78, 191]]', '"author_spans": [[35, 191]]', 1)
        p.write_text(s, encoding="utf-8")
        resum(r)
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("把被剔除的字放回作者区间：红（摘要与重建差分）", rc == 1 and "id 137" in err, err[:300])

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        pa = r / C.ADMIT_REL / "pass-a/tier1.jsonl"
        s0 = pa.read_text(encoding="utf-8")
        assert '"author_spans": [[49, 110]]' in s0
        pa.write_text(s0.replace('"author_spans": [[49, 110]]', '"author_spans": [[49, 100]]', 1), encoding="utf-8")
        resum(r)
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("甲遍原件被改区间（并同步清单）：重建与入库准入表不再相同，退 1",
               rc == 1 and "重建差分" in err and "id 1）" in err, "rc=%d %s" % (rc, err[:300]))

    with tempfile.TemporaryDirectory() as t:
        r = mk_root(t)
        pa = r / C.ADMIT_REL / "pass-a/tier1.jsonl"
        pa.write_text(pa.read_text(encoding="utf-8").replace('"verdict": "clean"', '"verdict": "reject"', 1), encoding="utf-8")
        resum(r)
        rc, _, err = run("check_admit_table.py", "--root", str(r))
        expect("甲遍原件只改 verdict（并同步清单）：准入表里 pass_a 摘要对不上，退 1", rc == 1 and "重建差分" in err, "rc=%d %s" % (rc, err[:300]))

    rc, _, err = run("check_admit_table.py", "--root", str(ROOT / "不存在的目录"))
    expect("找不到准入表：退 2（不是红也不是绿）", rc == 2, "rc=%d" % rc)


def report_cases():
    print("== 引文报告 ==")
    fx = (HERE / "fixtures/cites.md").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as t:
        scan = Path(t) / "scan"
        scan.mkdir()
        (scan / "cites.md").write_text(fx, encoding="utf-8")
        outj = Path(t) / "r.json"
        rc, out, err = run("report_citations.py", "--scan", str(scan), "--json", str(outj))
        expect("夹具里有很多问题引文，退出码仍恒为 0", rc == 0, "rc=%d %s" % (rc, err[:200]))
        rep = json.loads(outj.read_text(encoding="utf-8"))
        got = {}
        for c in rep["citations"]:
            got.setdefault(c["line"], []).append(c["status"])
        for i, l in enumerate(fx.split("\n"), 1):
            m = re.search(r"<!--expect:([a-z_,]*)-->", l)
            if not m:
                continue
            want = [x for x in m.group(1).split(",") if x]
            expect("夹具第 %d 行读数 %s" % (i, want or "（无，只进未解析）"), got.get(i, []) == want, "实得 %s" % got.get(i, []))
        expect("跨行与多行号的标记进未解析清单，不假装抽到",
               len(rep["unparsed_markers"]) >= 2, str(rep["unparsed_markers"]))
        expect("摘要计数自洽", rep["summary"]["total"] == len(rep["citations"])
               and rep["summary"]["ok"] + rep["summary"]["flagged"] == rep["summary"]["total"])
    rc, out, err = run("report_citations.py", "--scan", str(ROOT / "不存在的目录"))
    expect("扫描目录不存在：脚本自身出错，退 2", rc == 2, "rc=%d" % rc)
    rc, out, err = run("report_citations.py")
    expect("对真实 formal_math 实跑：退 0", rc == 0, "rc=%d %s" % (rc, err[:200]))
    print("   ", out.strip().splitlines()[0])


def main():
    block_cases()
    report_cases()
    bad = RESULTS.count(False)
    print("\n自测：%d 项，不符 %d" % (len(RESULTS), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
