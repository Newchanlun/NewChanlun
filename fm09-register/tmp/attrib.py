#!/usr/bin/env python3
# FM-09 答疑区逐位置作者归属判定（状态机启发式，只读）；供台账二次校验与备注引文分级共用
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
RE_TS_LEAD = re.compile(r'^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?')
RE_TS_PAREN = re.compile(r'[（(]\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?\s*[)）]')
RE_AUTHOR_HDR = re.compile(r'^\s*(\*\*)?缠中说禅\s*[:：]?\s*(\*\*)?\s*$')
RE_ANON = re.compile(r'^\s*\[匿名\]')
RE_MARK_START = re.compile(r'^(=+|-{2,}|—{2,}|－{2,}|\*\*)')
RE_MARK_INLINE = re.compile(r'={2,}|(?<=[？?。.！!)）哈谢吗呢啊复])=|-{2,}|—{2,}|－{2,}')
def classify(k, ln, i):
    """(课, 行, 行内起始下标) → 'A1'/'A2'/'A3'（作者文字）或 'REVIEW:…'（机器不能确认）"""
    lines, mark, _ = lib.load(k)
    s = lines[ln-1]
    st = s.lstrip()
    if RE_MARK_START.match(st): return 'A1'
    m = None
    for m in RE_MARK_INLINE.finditer(s[:i]): pass
    if m is not None and '[匿名]' not in s[m.end():i]: return 'A1'
    mh = None
    for mh in re.finditer(r'缠中说禅\s*[:：]?\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?', s[:i]): pass
    if mh is not None and '[匿名]' not in s[mh.end():i]: return 'A3'
    for u in range(ln-1, 0, -1):
        t = lines[u-1].strip()
        if not t: continue
        if lib.region(k, u) != 'P': break
        if t == '==' or t.endswith('==') or t.endswith('=') or RE_MARK_START.match(t): return 'A2'
        if RE_ANON.match(t): return 'REVIEW:anon-above'
        if RE_AUTHOR_HDR.match(t): return 'REVIEW:author-hdr-no-eq'
        if RE_TS_PAREN.search(t) and not RE_TS_LEAD.match(t): return 'A3'
        if RE_TS_LEAD.match(t):
            for v in range(u-1, 0, -1):
                w = lines[v-1].strip()
                if not w: continue
                if RE_AUTHOR_HDR.match(w): return 'REVIEW:author-hdr-no-eq'
                return 'REVIEW:netizen-ts-above'
        if '==' in t: return 'REVIEW:after-inline-eq'
    return 'A3'
def forward_flag(k, ln, j):
    """引文之后紧跟作答标记 → 引文处于问句位置"""
    lines, mark, _ = lib.load(k)
    s = lines[ln-1]
    if re.search(r'={2,}', s[j:]): return True
    for u in range(ln+1, min(len(lines), ln+6)+1):
        t = lines[u-1].strip()
        if not t: continue
        return bool(re.match(r'^={2,}', t))
    return False
def is_author_pos(k, ln, i, j):
    """严格口径：位置 [i,j) 是否可由机器确认为作者文字"""
    lines = lib.load(k)[0]
    s = lines[ln-1]
    if lib.in_manual_nonauthor(k, ln): return False
    for a, b in lib.note_spans(s):
        if i < b and a < j: return False
    r = lib.region(k, ln)
    if r == 'B': return True
    if r != 'P': return False
    c = classify(k, ln, i)
    if c.startswith('REVIEW'): return False
    if forward_flag(k, ln, j): return False
    return True
