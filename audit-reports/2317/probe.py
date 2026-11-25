"""#2317 独审夹具。用法及临时目录约束见同目录报告；不修改被审材料。"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A = Path("formal_math/sources/admit")
G = Path("formal_math/verification/gate11")
BLOG = Path("docs/chanlun/text/blog")
T = Path("candidate/tier1_candidate.jsonl")
P = [Path(x, "tier1.jsonl") for x in ("pass-a", "pass-b")]
UP = "2031547003290e1692c0c397f34566b59c596245"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def rows(path):
    return list(map(json.loads, path.read_bytes().splitlines()))


def encoded(rr):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rr).encode()


def sha(b):
    return hashlib.sha256(b).hexdigest()


def chars(sp):
    return {i for a, b in sp for i in range(a, b)}


def runs(cs):
    out = []
    for i in sorted(cs):
        if out and i == out[-1][1]:
            out[-1][1] += 1
        else:
            out.append([i, i+1])
    return out


def line(r):
    return next((ROOT/BLOG).glob(r["lesson"] + "-*.md")).read_text(encoding="utf8").split("\n")[r["line"]-1]


def fidelity():
    src = "fm09-admit/"
    paths = {p[len(src):] for p in git("ls-tree", "-r", "--name-only", UP, src).decode().splitlines()}
    disk = {str(p.relative_to(ROOT/A)) for p in (ROOT/A).rglob("*") if p.is_file()}
    read = lambda p: git("show", UP + ":" + src + p)
    modified = sorted(p for p in paths & disk if read(p) != (ROOT/A/p).read_bytes())
    missing = sorted(paths - disk)
    print("added", sorted(disk-paths), "changed", modified, "identical", len(paths & disk)-len(modified))
    print("not imported", len(missing), "all errata", all(p.startswith("errata/") for p in missing))
    print("upstream manifest", sha(read("SHA256SUMS")))
    old = read("candidate/README.md").splitlines(keepends=True)
    new = (ROOT/A/"candidate/README.md").read_bytes().splitlines(keepends=True)
    print("README: title changed", old[0] != new[0], "existing body untouched", old[1:] == new[1:len(old)])
    listing = {p.removeprefix("./"): h for h, p in (s.split("  ", 1) for s in (ROOT/A/"SHA256SUMS").read_text().splitlines())}
    assert set(listing) == disk - {"SHA256SUMS"}
    assert all(sha((ROOT/A/p).read_bytes()) == h for p, h in listing.items())
    ledger = [json.loads(s) for s in git("show", UP + ":fm09-register/tmp/ledger_final.jsonl").splitlines()]
    ids = [r["id"] for r in ledger if r["who"] == "正文"]
    a, b, t = [rows(ROOT/A/p) for p in [*P, T]]
    assert all([r["id"] for r in v] == ids for v in [a,b,t])
    adj = json.loads((ROOT/A/"candidate/adjudications.json").read_bytes())
    cuts = {x["id"]: chars([x["span"]]) for x in adj["exclude"]}
    groups = Counter()
    rebuilt = []
    for la, lb, r in zip(a, b, t):
        i = la["id"]
        assert (la["lesson"],la["line"],la["quote_spans"]) == (lb["lesson"],lb["line"],lb["quote_spans"])
        qs = la["quote_spans"]
        eq = la["author_spans"] == lb["author_spans"]
        both = chars(la["author_spans"]) & chars(lb["author_spans"])
        sp = runs(both - cuts.get(i,set()))
        verdict = "reject" if not sp else ("clean" if sp == qs else "trimmed")
        s = line(la)
        actual = dict(id=i,lesson=la["lesson"],line=la["line"],quote_spans=qs,author_spans=sp,verdict=verdict,
                      passes_agree=eq,adjudicated=i in cuts,pass_a=dict(verdict=la["verdict"],kind=la["nonauthor_kind"]),
                      pass_b=dict(verdict=lb["verdict"],kind=lb["nonauthor_kind"]),
                      author_text_sha256=sha("".join(s[x:y] for x,y in sp).encode()) if sp else "")
        rebuilt.append(actual)
        assert r == actual
        groups[(eq,i in cuts)] += 1
        if verdict == "trimmed":
            excluded = "".join(s[j] for j in sorted(chars(qs)-chars(sp)))
            print(i, la["lesson"], la["line"], sp, repr(excluded), "agree", eq, "adj", i in cuts)
        if i == 743:
            print("743 intersection", runs(both), "final", sp)
    assert encoded(rebuilt) == (ROOT/A/T).read_bytes()
    print("manifest verified", len(listing), "ledger IDs / identical rebuilt rows", len(ids), "groups", dict(groups))


def script(path,*args):
    return subprocess.run([sys.executable, "-I", str(path), *map(str,args)], capture_output=True, text=True, encoding="utf8")


def refresh(admit):
    p = admit/"SHA256SUMS"
    files = sorted(f for f in admit.rglob("*") if f.is_file() and f != p)
    p.write_text("".join(f"{sha(f.read_bytes())}  ./{f.relative_to(admit)}\n" for f in files), encoding="utf8")


def change(path, old, new):
    s = path.read_text(encoding="utf8")
    assert old in s
    path.write_text(s.replace(old, new, 1), encoding="utf8")


def citation_result(root, scan):
    p = script(root/G/"report_citations.py", "--root", root, "--scan", scan, "--json", "-")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def add_inputs(root):
    for path in [A, BLOG, G]:
        shutil.copytree(ROOT/path, root/path)


def mutate(root, case):
    a = root/A
    add_inputs(root)
    table = a/T
    if case in ("swap-id", "swap-one", "drop-id", "add-id", "restore-votes"):
        for f in [*P,T]:
            if case == "swap-one" and f != P[0]:
                continue
            rr = rows(a/f)
            if case in ("swap-id","swap-one"):
                assert rr[0]["id"] == 1
                rr[0]["id"] = 900001
            elif case == "drop-id":
                rr.pop()
            elif case == "add-id":
                rr.append(dict(rr[-1], id=900001))
            else:
                r = next(r for r in rr if r["id"] == 1259)
                r.update(author_spans=r["quote_spans"], verdict="clean")
                s = line(r)
                r["author_text_sha256"] = sha("".join(s[x:y] for x,y in r["quote_spans"]).encode())
                if f == T:
                    r.update(pass_a={"verdict":"clean","kind":"none"}, pass_b={"verdict":"clean","kind":"none"})
                else:
                    r.update(nonauthor_kind="none",reason="干净")
            (a/f).write_bytes(encoded(rr))
    elif case in ("no-cut", "no-cut-synced", "cut-bad", "cut-reason"):
        f = a/"candidate/adjudications.json"
        data = json.loads(f.read_bytes())
        if case == "cut-bad":
            data["exclude"][0]["text"] = "不是该处的字"
        elif case == "cut-reason":
            data["exclude"][0]["reason"] = "夹具替换说明"
        else:
            data["exclude"] = [v for v in data["exclude"] if v["id"] not in [137,138]]
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")
        if case == "no-cut-synced":
            rr = rows(table)
            for r in rr:
                if r["id"] in (137,138):
                    r.update(author_spans=r["quote_spans"], verdict="clean", adjudicated=False)
                    q = "".join(line(r)[x:y] for x,y in r["quote_spans"])
                    r["author_text_sha256"] = sha(q.encode())
            table.write_bytes(encoded(rr))
    elif case == "corpus":
        f = next((root/BLOG).glob("017-*.md"))
        ls = f.read_text(encoding="utf8").split("\n")
        assert ls[39][72:78] == "“一分为二”"
        ls[39] = ls[39][:73] + "三" + ls[39][74:]
        f.write_text("\n".join(ls), encoding="utf8")
    elif case == "corpus-only":
        f = next((root/BLOG).glob("000-*.md"))
        ls = f.read_text(encoding="utf8").split("\n")
        assert ls[25].startswith("投资")
        ls[25] = "合" + ls[25][1:]
        f.write_text("\n".join(ls), encoding="utf8")
    elif case.startswith("spec"):
        change(a/"SPEC.md", "790 条", "791 条")
    elif case.startswith("merge"):
        f = a/"candidate/merge.py"
        if case == "merge-different":
            change(f, 'agree = a["author_spans"] == b["author_spans"]', 'agree = True')
        else:
            change(f, 'if not agree: disputes.append(row["id"])', 'pass  # 不再记分歧清单；不影响表')
    elif case.startswith("shim"):
        f = root/G/"merge_shim/lib.py"
        if case == "shim-different":
            change(f, "_cache[k] = (lines, mark, fn[0])", "_cache[k] = ([], mark, fn[0])")
        else:
            change(f, "_cache[k] = (lines, mark, fn[0])", "_cache[k] = (lines, None, fn[0])")
    else:
        raise ValueError(case)
    if case not in ("spec-stale","merge-stale"):
        refresh(a)
    p = script(root/G/"check_admit_table.py", "--root", root)
    print(f"{case} rc={p.returncode}")
    print((p.stdout or p.stderr).strip())
    if case == "swap-id":
        for rel in [*P,Path("candidate/merge.py"),Path("candidate/adjudications.json")]:
            dst = root/"fm09-admit"/rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a/rel,dst)
        legacy = Path("fm09-register/tmp")
        (root/legacy).mkdir(parents=True)
        for name in ("ledger_final.jsonl","lib.py"):
            (root/legacy/name).write_bytes(git("show",UP+":"+str(legacy/name)))
        old = script(root/"fm09-admit/candidate/merge.py")
        print("original ledger rc",old.returncode,old.stderr.strip().splitlines()[-1])
    if case in ("no-cut-synced","restore-votes"):
        loc, q = ("017:40","“一分为二”") if case == "no-cut-synced" else ("081:42","(后文改称自同构性结构）")
        (root/"formal_math/probe.md").write_text(f"【缠师 {loc}】「{q}」", encoding="utf8")
        obj = citation_result(root, root/"formal_math")["citations"][0]
        print("citation", loc, obj["quote"], obj["status"], obj["row_ids"])

def citations(root):
    # 使用实表与实语料；只在临时扫描目录里放引文。
    add_inputs(root)
    ff = root/"formal_math/sources"
    cases = [
        ("bridge", "【缠师 011:26】「湿吻。把短期均线」"),
        ("single-id", "【缠师 011:16】「技术分」"),
        ("repeat-in-out", "【缠师 000:26】「，归根」"),
        ("excluded17", "【缠师 017:40】「“一分为二”」"),
        ("excluded46", "【缠师 046:28】「三、没有中枢」"),
        ("excluded54", "【缠师 054:60】「*」"),
        ("splice", "【缠师 081:42】「而走势是所有人贪嗔痴疑的合力结果，反映在走势中，就使得走势显示出自相似性。」"),
        ("splice-also-outside", "【缠师 081:42】「显示出自相似性。」"),
        ("across-gap", "【缠师 081:42】「显示出自相似性……。」"),
        ("reverse", "【缠师 000:26】「明白了这一点……而市场的波动」"),
        ("duplicate", "【缠师 000:26】「而市场的波动……而市场的波动」"),
        ("missing-ellipsis", "【缠师 000:26】「而市场的波动……」"),
        ("nbsp-original", "【缠师 014:44】「析如下：\u00a0在周线2」"),
        ("ascii-space", "【缠师 014:44】「析如下： 在周线2」"),
        ("ideographic-space", "【缠师 014:44】「析如下：　在周线2」"),
        ("halfwidth", "【缠师 000:26】「而市场的波动,」"),
        ("table-miss", "【缠师 017:1】「不在表内」"),
        ("two", "【缠师 000:26】「而市场的波动」与【缠师 054:60】「*」"),
        ("other-speaker", "【网友 000:26】「而市场的波动」"),
        ("four-digit", "【缠师 1011:26】「湿吻」"),
        ("two-digit", "【缠师 11:26】「湿吻」"),
        ("wide-colon", "【缠师 011：26】「湿吻」"),
        ("multi-number", "【缠师 011:26、27】「湿吻」"),
        ("nested", "【缠师 011:26】「湿「吻」」"),
        ("alternate", "【编者 011:26】『湿吻』"),
        ("cross-line", "【缠师 011:26】「湿"),
        ("continuation", "吻」"),
    ]
    (ff/"cases.md").write_text("\n".join(v for _,v in cases), encoding="utf8")
    (ff/"note.txt").write_text("硬证据：【缠师 054:60】「*」", encoding="utf8")
    (ff/"note.lean").write_text("-- 硬证据：【缠师 054:60】「*」", encoding="utf8")
    p = script(ROOT/G/"report_citations.py", "--root", root, "--json", "-")
    js = json.loads(p.stdout)
    print("rc",p.returncode,"scanned",js["scanned_files"],"of 3")
    for n,(name,_) in enumerate(cases,1):
        cc = [(x["status"],x["row_ids"],x["attribution"]) for x in js["citations"] if x["file"].endswith("cases.md") and x["line"] == n]
        uu = [u for u in js["unparsed_markers"] if u["file"].endswith("cases.md") and u["line"] == n]
        print(name, cc or ("unparsed" if uu else "silent"))
    for suffix in ("lean","txt"):
        print("note."+suffix,[x["status"] for x in js["citations"] if x["file"].endswith("note."+suffix)] or "silent")
    for k,n,q in [("011",26,"湿吻。把短期均线"),("011",16,"技术分"),("000",26,"，归根"),
                  ("000",26,"明白了这一点"),("000",26,"而市场的波动"),
                  ("014",44,"析如下： 在周线2"),("014",44,"析如下：\u00a0在周线2")]:
        rr = [r for r in rows(ROOT/A/T) if (r["lesson"],r["line"]) == (k,n)]
        s = line(rr[0])
        pos = [i for i in range(len(s)) if s.startswith(q,i)]
        print(k,n,repr(q),"starts",pos,"admitted",[(r["id"],r["author_spans"]) for r in rr])


def weak_tests(root):
    add_inputs(root)
    f = root/G/"fixtures/cites.md"
    change(f, "跨行引文抽不到（只报未解析） 【缠师 000:26】", "跨行引文缺了标记 ")
    change(f, "【缠师 017:40、41】", "【缠师 017:40、41】【缠师 017:40、42】")
    f = root/G/"selftest.py"
    change(f, """s = s.replace('"author_spans": [[35, 72], [78, 191]]', '"author_spans": [[35, 191]]', 1)""",
           """s = "".join(v.replace('"passes_agree": true', '"passes_agree": false') if v.startswith('{"id": 137,') else v for v in s.splitlines(True))""")
    p = script(f)
    print("mutated fixture: no cross-line marker; id 137 author spans unchanged")
    print("rc",p.returncode)
    print(p.stdout.strip().splitlines()[-1])
    if p.returncode != 0:
        print(p.stdout,p.stderr)
    missing = root/"empty-root"
    for d in (A,BLOG):
        (missing/d).mkdir(parents=True)
    for title,loc in (("absent root",root/"absent"),("absent table",missing)):
        p = script(root/G/"check_admit_table.py","--root",loc)
        print(title,p.returncode,p.stderr.strip())


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "fidelity":
        fidelity()
    else:
        with tempfile.TemporaryDirectory(dir=os.environ["TMPDIR"]) as tmp:
            root = Path(tmp)
            if mode == "cites":
                citations(root)
            elif mode == "weak-tests":
                weak_tests(root)
            else:
                mutate(root,mode)
