"""从仓库根运行；只读两个固定提交，不调用受审代码。"""
import hashlib
import json
import subprocess
from collections import Counter

SRC = "2031547003290e1692c0c397f34566b59c596245"
DST = "c7bd74255c0234363a968a91fa4f075038c5ba63"
A = "formal_math/sources/admit"
B = "docs/chanlun/text/blog"
G = "formal_math/verification/gate11"
FP = "b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d"


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args])


def inventory(rev, path):
    records = git("ls-tree", "-rz", rev + ":" + path).split(b"\0")
    entries = {}
    for rec in filter(None, records):
        head, name = rec.split(b"\t", 1)
        mode, kind, oid = head.split()
        assert kind == b"blob"
        entries[name.decode()] = (mode.decode(), git("cat-file", "blob", oid))
    return entries


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rows(data):
    return {r["id"]: r for r in map(json.loads, data.splitlines())}


def ix(spans):
    return {i for start, end in spans for i in range(start, end)}


src = inventory(SRC, "fm09-admit")
dst = inventory(DST, A)
blog = inventory(DST, B)
assert all(m == "100644" for m, _ in (*dst.values(), *blog.values()))
reviewed = {n for n in src if not n.startswith("errata/")}
assert set(dst) == reviewed | {"CORPUS_FINGERPRINT"}
assert {n for n in reviewed if dst[n] != src[n]} == {"SHA256SUMS", "candidate/README.md"}
assert len(dst) == 49 and sum(dst.get(n) == src[n] for n in reviewed) == 46
old_readme, new_readme = (x["candidate/README.md"][1] for x in (src, dst))
assert new_readme.split(b"\n", 1)[1].startswith(old_readme.split(b"\n", 1)[1])
pin = "".join(f"{m} {sha(b)} {A}/{n}\n" for n,(m,b) in sorted(dst.items()))
assert pin.encode() == git("show", DST + ":" + G + "/admit_identity.pin")
expected = sorted(f"{sha(b)}  ./{n}" for n, (_, b) in dst.items() if n != "SHA256SUMS")
assert sorted(dst["SHA256SUMS"][1].decode().splitlines()) == expected
fp = sha("".join(f"{sha(b)}  {n}\n" for n, (_,b) in sorted(blog.items())).encode())
assert fp == FP and dst["CORPUS_FINGERPRINT"][1] == f"{FP}  {B}/*.md\n".encode()
print(f"原件逐字节及模式一致 46；钉选 {len(dst)}；摘要清单 {len(expected)}；语料 {len(blog)}：{fp}")

item = rows(dst["candidate/tier1_candidate.jsonl"][1])
a, b = (rows(dst[f"pass-{p}/tier1.jsonl"][1]) for p in "ab")
exc = {r["id"]: r["span"] for r in json.loads(dst["candidate/adjudications.json"][1])["exclude"]}
assert len(item) == 790 and item.keys() == a.keys() == b.keys()
assert set(exc) == {137, 138, 743, 877}
groups = Counter()
trim = {}
for k, r in item.items():
    aa, bb, keep, quote = (
        a[k]["author_spans"], b[k]["author_spans"], r["author_spans"], r["quote_spans"])
    assert r["passes_agree"] == (aa == bb) and r["adjudicated"] == (k in exc)
    assert ix(keep) == ((ix(aa) & ix(bb)) - (ix([exc[k]]) if k in exc else set()))
    groups[r["passes_agree"], r["adjudicated"]] += 1
    if r["verdict"] == "clean":
        assert keep == quote
        continue
    assert r["verdict"] == "trimmed" and all(e < s for (_,e),(s,_) in zip(keep, keep[1:]))
    text = next(v[1] for n,v in blog.items() if n.startswith(r["lesson"]+"-"))
    line = text.decode().split("\n")[r["line"]-1]
    assert sha("".join(line[i] for i in sorted(ix(keep))).encode()) == r["author_text_sha256"]
    removed = "".join(line[i] for i in sorted(ix(quote)-ix(keep)))
    trim[k] = len(keep)
    print(k, f'{r["lesson"]}:{r["line"]}', len(keep), repr(removed), repr(line[keep[-1][0]:keep[-1][1]]) if k in (760,778,1259) else "")
assert trim == {132:1,137:2,138:2,743:1,760:2,778:2,877:2,929:2,1259:2}
assert {i for i,r in item.items() if not r["passes_agree"]} == {743,760,778}
assert all(a[i]["verdict"] == b[i]["verdict"] == "clean" for i in (137,138,877))
assert groups == {(True,False):784,(True,True):3,(False,True):1,(False,False):2}
print("字段组合", dict(groups))
