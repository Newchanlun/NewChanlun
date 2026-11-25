#!/usr/bin/env python3
"""合并甲、乙两遍：作者区间取交集（任一遍剔除的字符都不准入）。只读原件，结论现算。
用法（仓库根目录）：python3 -I fm09-admit/candidate/merge.py
"""
import hashlib, json, os, sys
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(root, "fm09-register", "tmp"))
import lib
lib.BLOG = os.path.join(root, "docs", "chanlun", "text", "blog")
def load(p): return [json.loads(l) for l in open(os.path.join(root, "fm09-admit", p), encoding="utf-8")]
A, B = load("pass-a/tier1.jsonl"), load("pass-b/tier1.jsonl")
led = [json.loads(l) for l in open(os.path.join(root, "fm09-register/tmp/ledger_final.jsonl"), encoding="utf-8")]
want = [e["id"] for e in led if e["who"] == "正文"]
assert [x["id"] for x in A] == want == [x["id"] for x in B], "id 集合或次序不符"
def chars(spans): return {i for a, b in spans for i in range(a, b)}
def spans(cs):
    out = []
    for i in sorted(cs):
        if out and out[-1][1] == i: out[-1][1] = i + 1
        else: out.append([i, i + 1])
    return out
rows, disputes = [], []
for a, b in zip(A, B):
    assert (a["lesson"], a["line"]) == (b["lesson"], b["line"]), a["id"]
    assert a["quote_spans"] == b["quote_spans"], ("摘句定位不一致", a["id"])
    line = lib.load(a["lesson"])[0][a["line"] - 1]
    au = spans(chars(a["author_spans"]) & chars(b["author_spans"]))
    agree = a["author_spans"] == b["author_spans"]
    text = "".join(line[x:y] for x, y in au)
    verdict = "reject" if not au else ("clean" if au == a["quote_spans"] else "trimmed")
    row = {"id": a["id"], "lesson": a["lesson"], "line": a["line"], "quote_spans": a["quote_spans"],
           "author_spans": au, "verdict": verdict, "passes_agree": agree,
           "pass_a": {"verdict": a["verdict"], "kind": a["nonauthor_kind"]},
           "pass_b": {"verdict": b["verdict"], "kind": b["nonauthor_kind"]},
           "author_text_sha256": hashlib.sha256(text.encode()).hexdigest() if au else ""}
    rows.append(row)
    if not agree: disputes.append(row["id"])
out = os.path.join(root, "fm09-admit/candidate/tier1_candidate.jsonl")
with open(out, "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
from collections import Counter
print("rows", len(rows), dict(Counter(r["verdict"] for r in rows)), "disputes", disputes)
