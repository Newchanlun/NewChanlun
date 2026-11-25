"""#2317 第二轮黑盒夹具。在仓库根运行；TMPDIR 指向专用临时目录。"""
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
A = Path("formal_math/sources/admit")
G = Path("formal_math/verification/gate11")
B = Path("docs/chanlun/text/blog")
T = Path("candidate/tier1_candidate.jsonl")
U = "2031547003290e1692c0c397f34566b59c596245"
BASE = "594e49b5ec034461f9196c6cfb0c58fe017e8dc5"
HEAD = "01cdc3a32a6cbf9ccb9d29529d4218eb3171ff7e"
TMP = Path(os.environ["TMPDIR"]).resolve()


def git(*args, root=ROOT):
    return subprocess.check_output(["git", "-C", root, *map(str, args)])


def archive(rel):
    return git("show", U + ":fm09-admit/" + rel)


def h(b):
    return hashlib.sha256(b).hexdigest()


def sums(blob):
    pairs = []
    for raw in blob.decode().splitlines():
        if not raw or raw.startswith("#"):
            continue
        digest, name = raw.split("  ")
        name = name.removeprefix("./")
        assert re.fullmatch("[0-9a-f]{64}", digest) and name == Path(name).as_posix()
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        pairs.append((name, digest))
    assert len(dict(pairs)) == len(pairs) == len({n.casefold() for n, _ in pairs})
    return dict(pairs)


def rows(file):
    return [json.loads(l) for l in file.read_bytes().splitlines()]


def dump(rr):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rr).encode()


def lesson(r):
    return next((ROOT / B).glob(r["lesson"] + "-*.md")).read_text(encoding="utf-8").split("\n")[r["line"] - 1]


def positions(sp):
    return {k for a, b in sp for k in range(a, b)}


def intervals(chars):
    return [[x[0], x[-1] + 1] for _, grp in itertools.groupby(
        enumerate(sorted(chars)), lambda v: v[1] - v[0]) if (x := [v for _, v in grp])]


def reconstruct(d, show=False):
    ballots = [rows(d / p / "tier1.jsonl") for p in ("pass-a", "pass-b")]
    assert len(ballots[0]) == len(ballots[1]) == 790
    cuts = defaultdict(set)
    for c in json.loads((d / "candidate/adjudications.json").read_bytes())["exclude"]:
        a, b = c["span"]
        assert lesson(c)[a:b] == c["text"]
        cuts[c["id"]].update(range(a, b))
    out = []
    for x, y in zip(*ballots):
        assert all(x[k] == y[k] for k in ("id", "lesson", "line", "quote_spans"))
        r = {k: x[k] for k in ("id", "lesson", "line", "quote_spans")}
        inter = positions(x["author_spans"]) & positions(y["author_spans"])
        sp = intervals(inter - cuts.get(x["id"], set()))
        z = lesson(r)
        r.update(author_spans=sp, verdict="reject" if not sp else
                 "clean" if sp == r["quote_spans"] else "trimmed",
                 passes_agree=x["author_spans"] == y["author_spans"], adjudicated=bool(cuts.get(x["id"])))
        for k, v in (("pass_a", x), ("pass_b", y)):
            r[k] = {"verdict": v["verdict"], "kind": v["nonauthor_kind"]}
        r["author_text_sha256"] = h("".join(z[a:b] for a, b in sp).encode()) if sp else ""
        out.append(r)
        if show and not r["passes_agree"]:
            print(r["id"], "intersection", intervals(inter), "final", sp)
    return out


def fidelity():
    d = ROOT / A
    changes = git("diff", "--name-status", BASE, HEAD).decode().splitlines()
    print("changes", Counter(x.split("\t")[0] for x in changes), "admit", sum(str(A)+"/" in x for x in changes),
          "gate", sum(str(G)+"/" in x for x in changes))
    manifest = archive("SHA256SUMS")
    upstream = sums(manifest)
    freeze = {n: v for n, v in upstream.items() if not n.startswith("errata/")}
    pins = sums((ROOT / G / "pinned_admit.sha256").read_bytes())
    names = {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    assert pins.keys() == freeze.keys() and names == pins.keys() | {"CORPUS_FINGERPRINT", "SHA256SUMS"}
    diff = [n for n in pins if (d / n).read_bytes() != archive(n)]
    assert all(h(archive(n)) == freeze[n] and h((d/n).read_bytes()) == pins[n] for n in pins)
    listed = sums((d / "SHA256SUMS").read_bytes())
    assert listed == {n: h((d/n).read_bytes()) for n in names if n != "SHA256SUMS"}
    print("upstream sums", h(manifest), "errata", len(upstream)-len(freeze))
    print("pins", len(pins), "upstream_digest_diff", [n for n in pins if pins[n] != freeze[n]],
          "byte_diff", diff, "local_sums", len(listed))
    orig = archive("candidate/README.md").decode().splitlines()
    new = (d/"candidate/README.md").read_text().splitlines()
    print("README original body unchanged:", orig[1:] == new[1:len(orig)])
    md = sorted((ROOT / B).glob("*.md"), key=lambda f: f.name.encode())
    print("corpus", len(md), h(b"".join((h(p.read_bytes())+"  "+p.name+"\n").encode() for p in md)))
    out = reconstruct(d, True)
    print("rebuilt", len(out), "byte_equal", dump(out) == (d/T).read_bytes(),
          "trimmed", [(r["id"],len(r["author_spans"])) for r in out if r["verdict"] == "trimmed"])
    print("agree/adjudicated", sorted(Counter((r["passes_agree"],r["adjudicated"]) for r in out).items()))
    print("touching pairs", sum(b == c for r in out for (_,b),(c,_) in zip(r["author_spans"],r["author_spans"][1:])))
    print("absolute machine paths", [(str(f.relative_to(ROOT)), i)
          for b in (ROOT/A, ROOT/G) for f in b.rglob("*.py") for i, l in enumerate(f.read_text().splitlines(),1)
          if re.search(r"/(?:Users|Volumes|home|root|private|tmp|mnt|opt)/|\b[a-zA-Z]:[\\/]", l) and not "fm09-register/tmp/" in l])


def rootcopy():
    root = Path(tempfile.mkdtemp(dir=TMP))
    for sub in (A, G, B):
        shutil.copytree(ROOT / sub, root / sub)
    return root


def run(r, entry, *args, **env):
    return subprocess.run([sys.executable, "-I", str(r/G/entry), *map(str,args)],
                          capture_output=True, encoding="utf-8", cwd=r, env={**os.environ, **env})


def block(r, name):
    p = run(r, "check_admit_table.py")
    diag = (p.stderr or p.stdout).splitlines()
    print(name, "rc", p.returncode, "|", " | ".join(diag[:2]))


def refresh(d):
    files = sorted(p for p in d.rglob("*") if p.is_file() and p != d/"SHA256SUMS")
    (d/"SHA256SUMS").write_text("".join(f"{h(p.read_bytes())}  ./{p.relative_to(d)}\n" for p in files))


def first_b2():
    for case in ("swap-id", "restore-votes", "no-cut-synced"):
        r = rootcopy()
        d = r/A
        if case == "no-cut-synced":
            f = d/"candidate/adjudications.json"
            j = json.loads(f.read_bytes())
            j["exclude"] = [c for c in j["exclude"] if c["id"] not in (137,138)]
            f.write_text(json.dumps(j, ensure_ascii=False))
        else:
            for f in (d/"pass-a/tier1.jsonl", d/"pass-b/tier1.jsonl"):
                rr = rows(f)
                if case == "swap-id":
                    rr[0]["id"] = 900001
                else:
                    v = next(x for x in rr if x["id"] == 1259)
                    v.update(author_spans=v["quote_spans"], verdict="clean", nonauthor_kind="none", reason="干净")
                    v["author_text_sha256"] = h("".join(lesson(v)[a:b] for a,b in v["author_spans"]).encode())
                f.write_bytes(dump(rr))
        (d/T).write_bytes(dump(reconstruct(d)))
        refresh(d)
        block(r,case)


def write(r, n, s):
    f = r/n
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(s.encode() if isinstance(s,str) else s)
    return f


def pins():
    for case in ("comment-pin","duplicate-pin","drop-pin","unsafe-pin","case-pin",
                 "comment-sums","duplicate-sums","drop-sums","parent-sums","case-sums","extra","alias-sums"):
        if sys.argv[2:] and case not in sys.argv[2:]:
            continue
        r = rootcopy()
        f = r/G/"pinned_admit.sha256" if case.endswith("-pin") else r/A/"SHA256SUMS"
        s = f.read_text()
        line = next(l for l in s.splitlines() if l.endswith("SPEC.md"))
        digest = line.split()[0]
        if case.startswith("comment"):
            s += "# fixture note\n"
        elif case.startswith("duplicate"):
            s += line + "\n"
        elif case.startswith("drop-"):
            s = s.replace(line+"\n","")
        elif case == "unsafe-pin":  # 仅解析，不读取该路径
            alt = line.replace("SPEC.md","../SPEC.md")
            f.write_text(s.replace(line,alt))
            sys.dont_write_bytecode = True
            import runpy
            print(case,"parser_kept_parent_component", "../SPEC.md" in runpy.run_path(str(r/G/"check_admit_table.py"))["read_pins"]())
            continue
        elif case.startswith("case-"):
            s = s.replace(line,line.replace("SPEC.md","spec.md"))
        elif case == "parent-sums":
            s += digest+"  ../SPEC.md\n"
        elif case == "alias-sums":
            s += digest+"  ././SPEC.md\n"
        elif case == "extra":
            write(r,A/"reader-note.txt","普通额外文件")
        f.write_text(s)
        block(r,case)


def inventory():
    # 普通目录与符号链接只引用本夹具自有文件。检查的是归档 blob 和跟踪清单。
    for case in ("regular-control","linked-document","extra-document"):
        r = rootcopy()
        git("init","-q",root=r)
        d = r/A
        if case == "linked-document":
            (r/"docs").mkdir(exist_ok=True)
            (d/"SPEC.md").rename(r/"docs"/"fixture-spec.md")
            (d/"SPEC.md").symlink_to(os.path.relpath(r/"docs/fixture-spec.md",d))
            git("add","--","docs/fixture-spec.md",root=r)
        elif case == "extra-document":
            write(r,A/"__pycache__/errata.jsonl",archive("errata/errata.jsonl"))
        git("add","-f","--",A,root=r)
        blob = git("show",":"+str(A/"SPEC.md"),root=r)
        mode = git("ls-files","-s","--",A/"SPEC.md",root=r).split()[0].decode()
        n = len(git("ls-files","-z","--",A,root=r).split(b"\0"))-1
        print(case,"git_mode",mode,"blob_equals_upstream",blob == archive("SPEC.md"),"indexed_files",n)
        block(r,case)


def report(r):
    p = run(r,"report_citations.py","--json","-")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def mark(loc,q,who="缠师"):
    return "【"+who+" "+loc+"】「"+q+"」"


def cites():
    r = rootcopy()
    git("init","-q",root=r)
    cases = [
        ("bridge",mark("011:26","湿吻。把短期均线")), ("single-id",mark("011:16","技术分")),
        ("outside",mark("000:26","，归根")), ("literal",mark("000:26","而市场的波动","原文")),
        ("reverse",mark("000:26","明白了这一点……而市场的波动")),
        ("repeat",mark("000:26","而市场的波动……而市场的波动")),
        ("tail",mark("000:26","而市场的波动……")), ("ordered",mark("000:26","而市场的波动...明白了这一点")),
        ("unsupported",mark("081:42","显示出自相似性……。")), ("nbsp",mark("014:44","析如下：\xa0在周线2")),
        ("ascii",mark("014:44","析如下： 在周线2")), ("ideo",mark("014:44","析如下：　在周线2")),
        ("speaker",mark("000:26","而市场的波动","网友")), ("speaker+cross",mark("011:26","湿吻。把短期均线","正文")),
        ("excluded",mark("017:40","“一分为二”")), ("missing",mark("017:1","一分为二")),
        ("splice",mark("081:42","而走势是所有人贪嗔痴疑的合力结果，反映在走势中，就使得走势显示出自相似性。")),
        ("space-only",mark("014:44","\xa0")), ("empty",mark("014:44","")),
        ("valid-tab","【原文\t000:26】  「而市场的波动」"), ("two",mark("011:16","技术分")+mark("054:60","*")),
        ("four",mark("1011:26","湿吻")), ("two-digits",mark("11:26","湿吻")),
        ("wide-colon",mark("011：26","湿吻")), ("wide-digits",mark("０１１:２６","湿吻")),
        ("nospace","【缠师011:26】「湿吻」"), ("empty-who","【011:26】「湿吻」"),
        ("multiple",mark("011:26、27","湿吻")), ("alternate","【缠师 011:26】『湿吻』"),
        ("nested","【缠师 011:26】「湿「吻」」"), ("inner-square","【缠师 011:26【注】】「湿吻」"),
    ]
    name = "formal_math/sources/review.txt"
    write(r,name,"\n".join(s for _,s in cases)+"\n")
    git("add","--",name,root=r)
    note = mark("054:60","*")
    for suffix in ("sources/free", "sources/note.txt", "sources/note.lean", "sources/admit-extra/n", "verification/gate11/fixtures2/n",
                   "sources/admit/extra", "verification/gate11/fixtures/extra","sources/ignored.note"):
        write(r,"formal_math/"+suffix,note)
    write(r,".gitignore","*.note\n")
    write(r,"formal_math/sources/latin",b"caf\xe9")
    write(r,"formal_math/sources/nul",b"plain\0text")
    j = report(r)
    print("source",j["file_source"],"rc 0")
    for i,(label,_) in enumerate(cases,1):
        hit = [(x["match"],x["status"],[(v["id"],v["span"]) for v in x["hits"]],x["attribution_accepted"],x["outside_also"])
               for x in j["citations"] if x["file"] == name and x["line"] == i]
        bad = [(u["col"],u["reason"]) for u in j["unparsed_markers"] if u["file"] == name and u["line"] == i]
        print(label, hit or bad or "silent")
    print("other files",[(x["file"],x["status"]) for x in j["citations"] if x["file"] != name])
    print("excluded",[(v["prefix"],v["files"]) for v in j["excluded"]],"unscanned",j["unscanned"])


def newlines():
    r = rootcopy()
    git("init","-q",root=r)
    sample = ["前言",mark("000:26","而市场的波动"),"【原文 000:26】","「明白了这一点」"]
    for n, sep in (("lf","\n"),("crlf","\r\n"),("cr","\r")):
        write(r,"formal_math/"+n+".txt",sep.join(sample)+sep)
    git("add","--","formal_math/lf.txt","formal_math/crlf.txt","formal_math/cr.txt",root=r)
    j = report(r)
    assert j["file_source"] == "git"
    for n in ("lf","crlf","cr"):
        f = "formal_math/"+n+".txt"
        print(n, "cites", [(x["line"],x["col"],x["status"]) for x in j["citations"] if x["file"] == f],
              "unparsed",[(x["line"],x["col"]) for x in j["unparsed_markers"] if x["file"] == f])


def oracle():
    r = rootcopy()
    groups = defaultdict(list)
    for row in rows(r/A/T):
        groups[row["lesson"],row["line"]].append(row)
    samples = []
    extra = None
    for (k,n), rr in sorted(groups.items()):
        z = lesson(rr[0])
        span = [(v["id"],a,b) for v in rr for a,b in v["author_spans"]]
        words = {z[a:b] for _,a,b in span}
        for _,a,b in span:
            for end in (a,b):
                words.update(z[max(0,end-1):min(len(z),end+j)] for j in (1,2))
        words.update(m[0] for m in re.finditer(r"……|…|\.{3,}|。。。",z))
        if k == "014" and n == 44:
            words.add("\xa0")
        for q in sorted(words):
            if not q or "「" in q or "」" in q:
                continue
            starts = [m.start() for m in re.finditer("(?="+re.escape(q)+")",z)]
            hit = sorted((i,p,p+len(q)) for p in starts for i,a,b in span if a<=p and p+len(q)<=b)
            samples.append((mark("%s:%d"%(k,n),q),q,hit,len({p for _,p,_ in hit})<len(starts)))
        if extra is None and len(rr)>1:
            for i in range(len(z)-1):
                q = z[i:i+2]
                if not all(c.isalpha() for c in q) or q[0]+" "+q[1] in z:
                    continue
                locations = [(p,v) for p in range(len(z)-1) if z.startswith(q,p)
                             for v,a,b in span if a<=p and p+2<=b]
                if len({p for p,_ in locations})>=2 and len({v for _,v in locations})>=2:
                    first_ids = {v for p,v in locations if p==locations[0][0]}
                    if first_ids != {v for _,v in locations}:
                        extra = (k,n,q,locations)
                        break
    f = "formal_math/probe.txt"
    data = [s for s,_,_,_ in samples]
    if extra:
        k,n,q,_ = extra
        data.append(mark("%s:%d"%(k,n),q[0]+" "+q[1]))
    write(r,f,"\n".join(data)+"\n")
    recs = [c for c in report(r)["citations"] if c["file"] == f]
    assert len(recs) == len(data)
    mismatch = []
    literal_ellipsis = 0
    for (s,q,hits,outside),c in zip(samples,recs):
        actual = sorted((v["id"],*v["span"]) for v in c["hits"])
        if c["status"]=="ok" and re.search(r"…|\.{3}|。。。",q):
            literal_ellipsis += 1
        if (bool(hits) != (c["status"]=="ok") or
                hits and (hits != actual or c["outside_also"] != outside)):
            mismatch.append((s,c["status"],hits[:2]))
    print("endpoint samples",len(samples),"real ellipses ok",literal_ellipsis,
          "mismatches",len(mismatch),"nonblank mismatches",sum(not s.split("」")[0].split("「")[-1].isspace() for s,_,_ in mismatch))
    print("014:44 white",[(x[1],x[2]) for x in mismatch if x[0]==mark("014:44","\xa0")])
    if extra:
        print("whitespace alternative positions", extra, recs[-1]["match"], recs[-1]["hits"])


def inputs():
    for case in ("wrong-corpus","bad-report-input","missing-scan","real-ledger","walk-scope"):
        if sys.argv[2:] and case not in sys.argv[2:]:
            continue
        r = rootcopy()
        if case == "wrong-corpus":
            write(r,B/"index-fixture.md","语料清单校验")
            block(r,case)
        elif case == "walk-scope":
            for p in ("review","__pycache__",".git",".lake"):
                write(r,"formal_math/"+p+"/plain.txt",mark("011:16","技术分"))
            v = report(r)
            print(case, v["file_source"], [x["file"] for x in v["citations"]])
        elif case == "real-ledger":
            d = r/"origin-rebuild"
            for p in ("candidate/merge.py","candidate/adjudications.json","pass-a/tier1.jsonl","pass-b/tier1.jsonl"):
                write(d,"fm09-admit/"+p, (r/A/p).read_bytes())
            for p in ("fm09-register/tmp/ledger_final.jsonl","fm09-register/tmp/lib.py"):
                write(d,p,git("show",U+":"+p))
            shutil.copytree(r/B,d/B)
            out = subprocess.run([sys.executable,"-I",str(d/"fm09-admit/candidate/merge.py")],
                                 cwd=d,capture_output=True,encoding="utf-8",check=True)
            print(case,out.stdout.strip(),"byte_equal",(d/"fm09-admit"/T).read_bytes()==(r/A/T).read_bytes())
        else:
            args = []
            if case == "bad-report-input":
                (r/A/T).write_text("{\n")
            else:
                args += ["--scan", r/"absent"]
            p = run(r,"report_citations.py",*args,"--json","-")
            print(case, "rc",p.returncode, "report",bool(p.stdout),"error",p.stderr.splitlines()[-1].split(":")[0])


def meta():
    for case in ("plain-walk","plain-git","no-cross","bad-reason","weak-137","skip-file-comparison","wrong-hits"):
        if sys.argv[2:] and case not in sys.argv[2:]:
            continue
        r = rootcopy()
        if case != "plain-walk":
            git("init","-q",root=r)
            git("add","-f","--","formal_math",root=r)
        test, data, check = (r/G/"selftest.py", r/G/"fixtures/cites.md", r/G/"check_admit_table.py")
        if case == "no-cross":
            data.write_text("\n".join(l for l in data.read_text().split("\n") if "case:cross-line" not in l))
        elif case == "bad-reason":
            data.write_text(data.read_text().replace("case:four-digit unparsed:课号不是三位","case:four-digit unparsed:原因不符"))
        elif case == "weak-137":
            test.write_text(test.read_text().replace("return s.replace(OLD_137, NEW_137, 1)",
                """return s.replace('"passes_agree": true', '"passes_agree": false', 1)""", 1))
        elif case == "skip-file-comparison":
            check.write_text(check.read_text().replace("elif C.sha256_bytes(p.read_bytes()) != want:", "elif False:", 1))
        elif case == "wrong-hits":
            f = r/G/"report_citations.py"
            f.write_text(f.read_text().replace('"span": [p, p + L]', '"span": [0, 0]'))
        p = run(r, "selftest.py", GATE11_SELFTEST_NESTED="1")
        assert p.stdout.splitlines(), p.stderr
        print(case,"rc",p.returncode, p.stdout.splitlines()[-1])
        if case == "plain-walk":
            common = p.returncode == 1
            print("unmodified child satisfies four outer verdicts:",
                  [common and "FAIL" in p.stdout and "cross-line" in p.stdout,
                   common and "four-digit" in p.stdout,
                   common and "id 137" in p.stdout and "FAIL" in p.stdout,
                   common and "FAIL" in p.stdout])
        for l in p.stdout.splitlines():
            if l.startswith("FAIL"):
                print(l.split("  — ")[0])


if __name__ == "__main__":
    {"fidelity":fidelity, "first-b2":first_b2, "pins":pins, "inventory":inventory,
     "cites":cites, "newlines":newlines, "oracle":oracle, "inputs":inputs, "meta":meta}[sys.argv[1]]()
