#!/usr/bin/env python3
"""阅读器：按课列出目标行及前后各三行全文，摘句用 ⟦ ⟧ 标出，并给出机械提示（仅供提示，不作判定）。
用法：python3 -I view.py <批号> [每批课数]   批号从 0 起，按台账中课号首次出现的次序分批。
     python3 -I view.py ids <id,id,...>      只看指定条目。"""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import entries, lines_of, split_cite, locate

HINT = re.compile(r'[（(【\[〔「『“"]|缠中说禅|本ID|注[:：]|娇|网友|问[:：]|答[:：]|图|——')


def lesson_batches(budget):
    """按课号排序，按上下文窗口字符数累计到 budget 切批。"""
    W = {}
    for r in entries():
        k, ln = split_cite(r['cite'])
        n = len(lines_of(k))
        W.setdefault(k, set()).update(range(max(1, ln - 3), min(n, ln + 3) + 1))
    out, cur, acc = [], [], 0
    for k in sorted(W):
        c = sum(len(lines_of(k)[x - 1]) for x in W[k])
        if cur and acc + c > budget:
            out.append(cur)
            cur, acc = [], 0
        cur.append(k)
        acc += c
    if cur:
        out.append(cur)
    return out


def show(sel):
    E = entries()
    by = {}
    for r in E:
        if sel(r):
            k, ln = split_cite(r['cite'])
            by.setdefault(k, []).append((ln, r))
    for k in sorted(by):
        L = lines_of(k)
        mark = next((i + 1 for i, l in enumerate(L) if '↑正文' in l), None)
        print(f'===== 课 {k}  共{len(L)}行  ↑正文标记行={mark}  首行={L[0][:60]!r}')
        tgt = {}
        for ln, r in by[k]:
            tgt.setdefault(ln, []).append(r)
        win = sorted({x for ln in tgt for x in range(max(1, ln - 3), min(len(L), ln + 3) + 1)})
        prev = None
        for x in win:
            if prev is not None and x != prev + 1:
                print('   ...')
            prev = x
            s = L[x - 1]
            if x in tgt:
                marks = []
                for r in tgt[x]:
                    sp = locate(s, r['quote'])
                    marks.append((r['id'], sp))
                pts = sorted({p for _, sp in marks for a, b in sp for p in (a, b)})
                out, last = [], 0
                opens = {a for _, sp in marks for a, b in sp}
                for p in pts:
                    out.append(s[last:p])
                    out.append('⟦' if p in opens else '⟧')
                    last = p
                out.append(s[last:])
                print(f'>>{x:4d}| ' + ''.join(out))
                for i, sp in marks:
                    q = ''.join(s[a:b] for a, b in sp)
                    h = sorted({m.group(0) for m in HINT.finditer(q)})
                    print(f'      [id {i}] span={sp} len={len(s)} 提示={h}')
            else:
                print(f'  {x:4d}| {s}')


if __name__ == '__main__':
    if sys.argv[1] == 'ids':
        want = {int(x) for x in sys.argv[2].split(',')}
        show(lambda r: r['id'] in want)
    else:
        per = int(sys.argv[2]) if len(sys.argv) > 2 else 14000
        b = lesson_batches(per)[int(sys.argv[1])]
        print('本批课号:', b)
        show(lambda r: split_cite(r['cite'])[0] in b)
