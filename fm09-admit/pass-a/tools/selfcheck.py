#!/usr/bin/env python3
"""按 SPEC「自检」逐项核对 tier1.jsonl。全部通过 exit 0，否则打印问题并 exit 1。"""
import hashlib, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import entries, lines_of, split_cite, locate, OUT

KEYS = ['id', 'lesson', 'line', 'quote_spans', 'author_spans', 'verdict',
        'nonauthor_kind', 'reason', 'author_text_sha256']
KINDS = {'none', 'editor_note', 'quoted_other', 'reader', 'non_body', 'not_found'}
err = []
from common import BLOG, LEDGER
# 语料指纹：按文件名排序逐个 `sha256sum` 行（"<hex>  <name>\n"）拼接后再取 sha256
fp = hashlib.sha256(''.join(
    hashlib.sha256(open(os.path.join(BLOG, f), 'rb').read()).hexdigest() + '  ' + f + '\n'
    for f in sorted(os.listdir(BLOG))).encode()).hexdigest()
if fp != 'b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d':
    err.append(f'语料指纹不符 {fp}')
if sum(1 for l in open(LEDGER, encoding='utf-8') if l.strip()) != 1604:
    err.append('台账行数不是 1604')
rows =[json.loads(l) for l in open(OUT, encoding='utf-8')]
E = entries()
if len(rows) != 790:
    err.append(f'行数 {len(rows)} != 790')
if [r['id'] for r in rows] != [e['id'] for e in E]:
    err.append('id 序列与台账 who==正文 不一致')
emap = {e['id']: e for e in E}


def ok_spans(sp, n):
    last = 0
    for x in sp:
        if not (isinstance(x, list) and len(x) == 2 and all(isinstance(t, int) for t in x)):
            return False
        a, b = x
        if not (0 <= a < b <= n) or a < last:
            return False
        last = b
    return True


for r in rows:
    i = r['id']
    if list(r) != KEYS:
        err.append(f'{i}: 键或次序不对 {list(r)}')
        continue
    e = emap.get(i)
    k, ln = split_cite(e['cite'])
    if r['lesson'] != k or r['line'] != ln or not isinstance(r['line'], int):
        err.append(f'{i}: lesson/line 与台账不符')
    s = lines_of(k)[ln - 1]
    q, a = r['quote_spans'], r['author_spans']
    if q != locate(s, e['quote']):
        err.append(f'{i}: quote_spans 与重新定位结果不符')
    if not ok_spans(q, len(s)) or not ok_spans(a, len(s)):
        err.append(f'{i}: 区间越界、空段、相交或不递增')
    for x, y in a:
        if not any(qa <= x and y <= qb for qa, qb in q):
            err.append(f'{i}: author 段 {[x, y]} 不在任何 quote 段内')
    v = r['verdict']
    if v == 'clean' and a != q:
        err.append(f'{i}: clean 但 author != quote')
    if v == 'reject' and a:
        err.append(f'{i}: reject 但 author 非空')
    if v == 'trimmed':
        qa = sum(y - x for x, y in q)
        aa = sum(y - x for x, y in a)
        if not a or aa >= qa:
            err.append(f'{i}: trimmed 但 author 为空或不严格小于 quote')
    if v not in ('clean', 'trimmed', 'reject'):
        err.append(f'{i}: verdict 非法')
    if r['nonauthor_kind'] not in KINDS:
        err.append(f'{i}: nonauthor_kind 非法')
    if (v == 'clean') != (r['nonauthor_kind'] == 'none'):
        err.append(f'{i}: verdict 与 nonauthor_kind 不协调')
    if not q and (v != 'reject' or r['nonauthor_kind'] != 'not_found'):
        err.append(f'{i}: 找不到摘句却未判 reject/not_found')
    if v != 'clean' and (not r['reason'] or r['reason'] == '干净'):
        err.append(f'{i}: 非 clean 缺理由')
    txt = ''.join(s[x:y] for x, y in a)
    want = hashlib.sha256(txt.encode('utf-8')).hexdigest() if a else ''
    if r['author_text_sha256'] != want:
        err.append(f'{i}: sha256 不可重算')

by = {r['id']: r for r in rows}
r = by.get(1259)
if not r or (r['lesson'], r['line']) != ('081', 42) or r['verdict'] == 'clean':
    err.append('已知实例 1259(081:42) 不得为 clean')
r = by.get(265)
if not r or (r['lesson'], r['line']) != ('020', 56) or r['verdict'] != 'clean':
    err.append('已知实例 265(020:56) 应为 clean')

for x in err:
    print('FAIL', x)
print('selfcheck:', 'PASS' if not err else f'{len(err)} 项失败', f'rows={len(rows)}')
sys.exit(1 if err else 0)
