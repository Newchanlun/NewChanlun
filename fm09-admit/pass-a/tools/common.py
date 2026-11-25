#!/usr/bin/env python3
"""甲遍公用：加载台账正文条目、读原行、定位摘句区间。只做机械定位，不做作者判定。"""
import hashlib, json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
BLOG = os.path.join(ROOT, 'docs', 'chanlun', 'text', 'blog')
LEDGER = os.path.join(ROOT, 'fm09-register', 'tmp', 'ledger_final.jsonl')
OUT = os.path.join(ROOT, 'fm09-admit', 'pass-a', 'tier1.jsonl')
_cache = {}


def entries():
    rows = [json.loads(l) for l in open(LEDGER, encoding='utf-8') if l.strip()]
    return [r for r in rows if r['who'] == '正文']


def lines_of(lesson):
    if lesson not in _cache:
        fn = [f for f in sorted(os.listdir(BLOG)) if f.startswith(lesson + '-')]
        if len(fn) != 1:
            raise KeyError(lesson)
        _cache[lesson] = open(os.path.join(BLOG, fn[0]), encoding='utf-8').read().split('\n')
    return _cache[lesson]


def split_cite(cite):
    k, ln = cite.split(':')
    return k, int(ln)


ELLIPSIS = re.compile(r'(?:……|…|\.{3,}|。。。)')


def locate(s, q):
    """返回摘句在原行 s 中的区间列表；先整串精确匹配，失败再按省略号切段依次匹配。
    NBSP 与空格视为同一字符（长度不变）。找不到返回 []。"""
    sn = s.replace('\xa0', ' ')
    qn = q.replace('\xa0', ' ')
    i = sn.find(qn)
    if i >= 0:
        return [[i, i + len(qn)]]
    parts = [p.strip() for p in ELLIPSIS.split(qn) if p.strip()]
    if len(parts) < 2:
        return []
    out, pos = [], 0
    for p in parts:
        j = sn.find(p, pos)
        if j < 0:
            return []
        out.append([j, j + len(p)])
        pos = j + len(p)
    return out


def text_of(s, spans):
    return ''.join(s[a:b] for a, b in spans)


def sha(s, spans):
    if not spans:
        return ''
    return hashlib.sha256(text_of(s, spans).encode('utf-8')).hexdigest()
