#!/usr/bin/env python3
# FM-09 只读工具库：加载 blog 语料、判定正文/答疑分界、识别编者注区间
import os, re, json
BLOG = '/home/workspace/src/NewChanlun/docs/chanlun/text/blog'
_cache = {}
def files():
    return sorted(f for f in os.listdir(BLOG) if re.match(r'^\d{3}-', f))
def load(k):
    """k: '017' -> (lines(list, 0-based), mark(1-based or None), fname)"""
    if k in _cache: return _cache[k]
    fn = [f for f in files() if f.startswith(k + '-')]
    if len(fn) != 1: raise KeyError(k)
    lines = open(os.path.join(BLOG, fn[0]), encoding='utf-8').read().split('\n')
    mark = next((i+1 for i, l in enumerate(lines) if '↑正文' in l), None)
    _cache[k] = (lines, mark, fn[0])
    return _cache[k]
OPEN = '（(【[〔'
CLOSE = {'（': '）)', '(': '）)', '【': '】', '[': ']', '〔': '〕'}
NOTE_HEAD = r'(?:旁观者注|娇注标题|娇加注|娇注|娇加|加注|备注|娇|注)'
RE_INLINE = re.compile(r'[（(【\[〔]\s*' + NOTE_HEAD + r'\s*[:：,，\-－ ]')
RE_DASH = re.compile(r'-{2,}\s*(?:[（(]\s*)?注\s*[:：\-－]')
# 编者插入的分类小标签（整括号）：如（买卖）(卖买)
RE_LABEL = re.compile(r'[（(]\s*(?:买卖|卖买)\s*[)）]')
RE_EDVOC = re.compile(r'[0-9]{6}[^）)]*[123]买|[123]买|[123]卖|多牛的人|按照他|他前期|他的意思|禅师|缠师|缠主|禅主|递归级别|递归后|后期定义|前期的定义|此处盘整|此例子|这课级别|此课文|课文')
RE_LINESTART = re.compile(r'^\s*[\-—\s]*' + NOTE_HEAD + r'\s*[:：]')
def _match_close(s, i):
    """s[i] 是开括号；返回配对闭括号之后的位置（找不到则行尾）"""
    depth = 0
    for j in range(i, len(s)):
        ch = s[j]
        if ch in '（(【[〔': depth += 1
        elif ch in '）)】]〕':
            depth -= 1
            if depth == 0: return j + 1
    return len(s)
def note_spans(s):
    """返回该行中编者注所占的 [start,end) 区间列表"""
    spans = []
    if RE_LINESTART.match(s):
        return [(0, len(s))]
    for m in RE_INLINE.finditer(s):
        spans.append((m.start(), _match_close(s, m.start())))
    for m in RE_DASH.finditer(s):
        # 破折号引出的注：到其后第一个闭括号（若破折号前有未闭合的开括号）或行尾
        st = m.start(); rest = s[st:]
        # 若注内自带开括号，则配对；否则到下一个闭括号或行尾
        k = None
        mm = re.search(r'[（(]', s[st:m.end()])
        if mm: k = _match_close(s, st + mm.start())
        else:
            c = re.search(r'[）)]', s[m.end():])
            k = m.end() + c.end() if c else len(s)
        spans.append((st, k))
    for m in RE_LABEL.finditer(s):
        spans.append((m.start(), m.end()))
    # 无“注”字头但以第三人称称呼作者或使用编者术语的括注，同样视为编者注
    for m in re.finditer(r'[（(]', s):
        e = _match_close(s, m.start())
        if RE_EDVOC.search(s[m.start():e]): spans.append((m.start(), e))
    # 合并
    spans.sort(); out = []
    for a, b in spans:
        if out and a <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], b))
        else: out.append((a, b))
    return out
# 人工登记的整行/多行非作者区间（阅读时逐个核实后补入）： {课: [(起行, 止行, 说明)]}
MANUAL_NONAUTHOR = {}
_mn = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'manual_nonauthor.json')
if os.path.exists(_mn):
    MANUAL_NONAUTHOR = json.load(open(_mn, encoding='utf-8'))
def in_manual_nonauthor(k, ln):
    for a, b, why in MANUAL_NONAUTHOR.get(k, []):
        if a <= ln <= b: return why
    return None
# 无“↑正文”分界标记、但正文之后仍带解盘/答疑的文件：人工核定的正文末行（含）。
MANUAL_BODY_END = {'004': 22, '006': 24, '046': 35, '085': 50}
def region(k, ln):
    lines, mark, _ = load(k)
    if mark is None:
        end = MANUAL_BODY_END.get(k)
        if end is None or ln <= end: return 'B'
        return 'P'
    if ln < mark: return 'B'
    if ln == mark: return 'M'
    return 'P'
def find_quote(k, ln, q):
    """返回 (ok, 实际逐字串, 起, 止, 错误)；先精确匹配，失败再做 NBSP->空格 归一匹配并回填原文真串"""
    lines, mark, _ = load(k)
    if not (1 <= ln <= len(lines)): return (False, None, 0, 0, 'line out of range')
    s = lines[ln-1]
    i = s.find(q)
    if i < 0:
        sn = s.replace('\xa0', ' '); qn = q.replace('\xa0', ' ')
        i = sn.find(qn)
        if i < 0: return (False, None, 0, 0, 'not a substring')
        q = s[i:i+len(qn)]
    j = i + len(q)
    for a, b in note_spans(s):
        if i < b and a < j: return (False, q, i, j, f'overlaps editor note span [{a},{b}): {s[a:b][:40]}')
    why = in_manual_nonauthor(k, ln)
    if why: return (False, q, i, j, 'manual non-author range: ' + why)
    return (True, q, i, j, None)
SENT_END = '。！？；!?;'
def expand_sentence(k, ln, anchor):
    """把锚点扩成所在整句（不跨编者注）；返回 (ok, quote, err)"""
    lines, mark, _ = load(k)
    if not (1 <= ln <= len(lines)): return (False, None, 'line out of range')
    s = lines[ln-1]
    i = s.find(anchor)
    if i < 0:
        sn = s.replace('\xa0', ' '); i = sn.find(anchor.replace('\xa0', ' '))
        if i < 0: return (False, None, 'anchor not a substring')
    j = i + len(anchor)
    spans = note_spans(s)
    for a, b in spans:
        if i < b and a < j: return (False, None, 'anchor overlaps editor note')
    lo = 0
    for a, b in spans:
        if b <= i: lo = max(lo, b)
    hi = len(s)
    for a, b in spans:
        if a >= j: hi = min(hi, a)
    st = i
    while st > lo and s[st-1] not in SENT_END: st -= 1
    en = j
    while en < hi and s[en-1] not in SENT_END: en += 1
    q = s[st:en].strip()
    return (True, q, None)
