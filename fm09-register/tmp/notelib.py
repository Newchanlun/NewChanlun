#!/usr/bin/env python3
# FM-09 备注内引文的判定与复核（只读）：区分「逐字引文」与〈登记者概括/术语〉
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
RE_CITE = re.compile(r'(?<![0-9])(\d{3}):(\d{1,4})(?![0-9])')
RE_RANGE = re.compile(r'(?<![0-9])(\d{3}):(\d{1,4})[–\-—~～至/](\d{1,4})(?![0-9:])')
def norm_nbsp(s): return s.replace('\xa0', ' ')
def author_segments(k, ln):
    """该行中属于作者文字的片段列表（剔除编者注区间；人工非作者行返回空）"""
    try: lines = lib.load(k)[0]
    except KeyError: return []
    if not (1 <= ln <= len(lines)): return []
    if lib.in_manual_nonauthor(k, ln): return []
    s = norm_nbsp(lines[ln-1])
    segs = []; pos = 0
    for a, b in lib.note_spans(lines[ln-1]):
        if a > pos: segs.append(s[pos:a])
        pos = max(pos, b)
    if pos < len(s): segs.append(s[pos:])
    return [x for x in segs if x.strip()]
def note_cites(note):
    out = []
    for m in RE_CITE.finditer(note): out.append((m.group(1), int(m.group(2))))
    for m in RE_RANGE.finditer(note):
        k, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        if a < b <= a + 80:
            for x in range(a, b + 1): out.append((k, x))
        else: out.append((k, b))
    return out
def pool_for(o, extra_cites=()):
    k0, l0 = o['cite'].split(':'); l0 = int(l0)
    pool = [norm_nbsp(o['quote'])]
    pool += author_segments(k0, l0)
    for (k, ln) in list(note_cites(o['note'])) + list(extra_cites):
        for d in (-2, -1, 0, 1, 2): pool += author_segments(k, ln + d)
    return pool
def split_parts(frag):
    return [p.strip() for p in re.split(r'…+|\.{3,}', frag) if len(p.strip()) >= 4]
_PUNC = {'，': ',', '：': ':', '；': ';', '（': '(', '）': ')', '！': '!', '？': '?', '－': '-', '—': '-', '–': '-', '％': '%', '．': '.', '～': '~'}
_DROP = set('“”‘’"\'「」『』 \t　')
def _norm_map(s):
    out = []; idx = []
    for i, ch in enumerate(s):
        if ch in _DROP: continue
        out.append(_PUNC.get(ch, ch)); idx.append(i)
    return ''.join(out), idx
def find_norm(part, pool):
    pn, _ = _norm_map(part)
    if len(pn) < 4: return None
    for s in pool:
        sn, idx = _norm_map(s)
        j = sn.find(pn)
        if j >= 0:
            return s[idx[j]: idx[j + len(pn) - 1] + 1]
    return None
def verify_fragment(frag, pool):
    """「frag」是否逐字成立：按…切分的每一片都是 pool 中某串的子串"""
    parts = split_parts(frag)
    if not parts: return True
    for p in parts:
        pn = norm_nbsp(p)
        if not any(pn in s for s in pool): return False
    return True
