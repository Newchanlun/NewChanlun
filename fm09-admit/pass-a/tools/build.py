#!/usr/bin/env python3
"""把人工判定（decisions/bNN.json）合成 tier1.jsonl。

判定文件格式：
  {"clean": [id, ...],
   "x": {"<id>": {"v": "trimmed|reject", "kind": "<nonauthor_kind>",
                  "cut": ["要剔除的原行子串", ...],   # trimmed 用：从摘句区间里剔除这些子串
                  "reason": "..."}},
   "unsure": {"<id>": "拿不准的原因"}}
脚本只做区间算术：判定本身全部来自人工逐条读原行后写入的判定文件。
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import entries, lines_of, split_cite, locate, sha, OUT

DEC = os.path.join(os.path.dirname(OUT), 'decisions')
EDGE = ' 　\xa0\t'


def subtract(spans, s, cuts, rid):
    keep = [list(x) for x in spans]
    for c in cuts:
        hit = False
        nxt = []
        for a, b in keep:
            seg = s[a:b]
            pos = 0
            while True:
                j = seg.find(c, pos)
                if j < 0:
                    break
                hit = True
                if j > pos:
                    nxt.append([a + pos, a + j])
                pos = j + len(c)
            if pos < len(seg):
                nxt.append([a + pos, b])
        if not hit:
            sys.exit(f'id {rid}: cut 子串不在摘句区间内: {c!r}')
        keep = nxt
    out = []
    for a, b in keep:
        while a < b and s[a] in EDGE:
            a += 1
        while b > a and s[b - 1] in EDGE:
            b -= 1
        if b > a:
            out.append([a, b])
    return out


def load_decisions():
    D, U = {}, {}
    for f in sorted(glob.glob(os.path.join(DEC, 'b*.json'))):
        d = json.load(open(f, encoding='utf-8'))
        for i in d.get('clean', []):
            if i in D:
                sys.exit(f'重复判定 {i} ({f})')
            D[i] = {'v': 'clean'}
        for k, v in d.get('x', {}).items():
            i = int(k)
            if i in D:
                sys.exit(f'重复判定 {i} ({f})')
            D[i] = v
        for k, v in d.get('unsure', {}).items():
            U[int(k)] = v
    return D, U


def build(partial=False):
    D, U = load_decisions()
    rows = []
    for r in entries():
        if r['id'] not in D:
            if partial:
                continue
            sys.exit(f'缺判定 id {r["id"]}')
        k, ln = split_cite(r['cite'])
        s = lines_of(k)[ln - 1]
        qs = locate(s, r['quote'])
        d = D[r['id']]
        v = d['v'] if qs else 'reject'
        if v == 'clean':
            au, kind, why = qs, 'none', '干净'
        elif v == 'reject':
            au, kind, why = [], (d.get('kind') if qs else 'not_found'), d.get('reason') or '原行中找不到摘句'
        elif v == 'trimmed':
            au, kind, why = subtract(qs, s, d['cut'], r['id']), d['kind'], d['reason']
            if not au or au == qs:
                sys.exit(f'id {r["id"]}: trimmed 结果为空或未变')
        else:
            sys.exit(f'id {r["id"]}: 未知判定 {v}')
        rows.append({'id': r['id'], 'lesson': k, 'line': ln, 'quote_spans': qs,
                     'author_spans': au, 'verdict': v, 'nonauthor_kind': kind,
                     'reason': why, 'author_text_sha256': sha(s, au)})
    extra = set(D) - {r['id'] for r in entries()}
    if extra:
        sys.exit(f'判定里有台账正文外的 id: {sorted(extra)}')
    with open(OUT, 'w', encoding='utf-8') as fh:
        for x in rows:
            fh.write(json.dumps(x, ensure_ascii=False) + '\n')
    from collections import Counter
    print(len(rows), dict(Counter(x['verdict'] for x in rows)), 'unsure', sorted(U))


if __name__ == '__main__':
    build(partial='--partial' in sys.argv)
