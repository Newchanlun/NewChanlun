#!/usr/bin/env python3
"""FM-09 登记册机械护栏（#2316 第三轮）。标准库，`python3 -I` 可跑。

只收原件：语料目录、台账 ledger_final.jsonl、禁引表 hard_cite_exclusions.json、
被检 Markdown，以及 G3 需要核对的帖头记录（旧记录 pool_375_recheck.jsonl；
若存在本轮记录 pool_375_recheck_r3.jsonl，则以它为现行记录）。结论每次现算。

三道护栏：
  G1 禁引隔离：禁引表中每个课行在被检文档里的每一处出现，所在物理行必须含字面
     标记 `〔禁引〕`，且该行不含以该课行为出处的 `【…】「…」` 硬引文形态。
  G2 合并行与跨帖行：语料原行含两个及以上时间戳、或含跨帖分隔（连续四个以上星号、
     行中部五个以上等号或短横）时，按帖切分器把该行切成段；引文须整体落在单一段内，
     且该段机械判为作者答语段。台账 1,604 条与文档全部课行都过此检；不合格者须在
     禁引表里。
  G3 答疑帖边界：对 375 条答疑 A2 逐条重算帖边界（不沿用旧 context_header），
     判红条件见 check_g3()。可用 --emit-pool 写出本轮记录。

退出码：0 绿；1 红（至少一项违规）；2 无法判定（无红项但有切不出边界者）。
切分规则的完整文字说明见同目录 README.md。
"""
import argparse, collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REG = os.path.dirname(HERE)
REPO = os.path.dirname(REG)

TS = r'\d{4}-\d{1,2}-\d{1,2}\s*\d{1,2}[:：]\d{2}(?:[:：]\d{2})?'
RE_TS = re.compile(TS)
MANUAL_BODY_END = {'004': 22, '006': 24, '046': 35, '085': 50}  # 与 tmp/lib.py 相同的人工正文止行

# ---------------------------------------------------------------- 语料
class Corpus:
    def __init__(self, d):
        self.d = d
        self.names = {f[:3]: f for f in sorted(os.listdir(d)) if re.match(r'^\d{3}-.*\.md$', f)}
        self._c = {}
    def lines(self, k):
        if k not in self._c:
            if k not in self.names: raise KeyError(k)
            self._c[k] = open(os.path.join(self.d, self.names[k]), encoding='utf-8').read().split('\n')
        return self._c[k]
    def reply_start(self, k):
        """答疑区首行（1 起）；无答疑区返回 None"""
        L = self.lines(k)
        mark = next((i + 1 for i, l in enumerate(L) if '↑正文' in l), None)
        if mark is not None: return mark + 1
        if k in MANUAL_BODY_END: return MANUAL_BODY_END[k] + 1
        return None

# ---------------------------------------------------------------- 切分器
# 记号（token）种类：
#   CS   回复尾戳 `(YYYY-MM-DD hh:mm:ss)` 及其后的星号或短横，收束一帖
#   AH   作者帖头 `缠中说禅` 后接冒号或时间戳（或独占一行）
#   QN   提问者名头 `[匿名] 名`、`名 删除此人所有评论`
#   TSX  不在括号内的时间戳（帖头时间）
#   SEP  问答分隔：两个以上 `=`/`＝`、两个以上 `-`、三个以上全角破折号、两个以上 `－`；
#        单个 `=` 仅在行首或紧跟问句收尾字符时算
#   PSEP 不跟在尾戳后的四个以上星号（跨帖分隔）
TOKEN_RES = [
    ('CS', re.compile(r'[（(]\s*' + TS + r'\s*[)）][*\-]*')),
    ('AH', re.compile(r'(?:\*\*)?缠中说[禅缠]\s*(?:[:：]\s*(?:' + TS + r')?|(?=\s*' + TS + r')\s*' + TS + r')(?:\s*\[举报\])?(?:\*\*)?')),
    ('QN', re.compile(r'\[?匿名\][ \t　\xa0]*(?:(?!\d{4}-\d{1,2}-)[^\s\[\]（(]){0,24}(?:[ \t　\xa0]*(?:' + TS + r'))?|[^\s\[\]（()）]{1,24}[ \t　\xa0]*删除此人所有评论|文章提交者[:：][^\s]{1,24}')),
    ('TSX', RE_TS),
    ('SEP', re.compile(r'[=＝]{2,}|-{3,}|(?:(?<=^)|(?<=[？?。.！!)）~～\s]))-{2}(?!-)|\u2014{3,}|－{2,}|(?:(?<=^)|(?<=[？?。.！!)）哈谢吗呢啊复~～\s]))[=＝](?![=＝])|(?<![=＝])[=＝]\s*$')),
    ('PSEP', re.compile(r'\*{4,}')),
]
RE_AH_LINE = re.compile(r'^\s*(?:\*\*)?缠中说[禅缠]\s*[:：]?\s*(?:\d{4}-\d{1,2}-\d{1,2}\s*)?(?:\*\*)?\s*$')
RE_LEAD_DASH = re.compile(r'^\s*-(?=[^\-\s])')

def tokenize(s):
    """返回按位置排序、互不重叠的记号列表 [(st, en, kind, text)]"""
    taken = []; out = []
    def free(a, b): return all(b <= x or a >= y for x, y in taken)
    m = RE_AH_LINE.match(s)
    if m and s.strip():
        out.append((0, len(s), 'AH', s)); taken.append((0, len(s)))
    for kind, rx in TOKEN_RES:
        for m in rx.finditer(s):
            a, b = m.start(), m.end()
            if a == b or not free(a, b): continue
            if kind == 'QN' and '删除此人所有评论' not in m.group(0) and m.group(0).strip() == '[匿名]':
                pass
            out.append((a, b, kind, m.group(0))); taken.append((a, b))
    m = RE_LEAD_DASH.match(s)
    if m and free(m.end() - 1, m.end()):
        out.append((m.end() - 1, m.end(), 'SEP', '-'))
    out.sort()
    return out

class Post:
    __slots__ = ('start', 'end', 'kind', 'ah', 'ah_ts', 'questioners', 'qlines', 'seps', 'close', 'near')
    def __init__(self, start, kind):
        self.start = start; self.end = start; self.kind = kind
        self.ah = None; self.ah_ts = None; self.questioners = []; self.qlines = set(); self.seps = []
        self.close = None; self.near = False
    @property
    def rounds(self): return (len(self.seps) + 1) // 2

class Seg:
    __slots__ = ('a', 'b', 'post', 'nb', 'after_sep', 'followed', 'qend')
    def __init__(self, a, b, post, nb, after_sep, qend=False):
        self.a, self.b, self.post, self.nb, self.after_sep, self.followed, self.qend = a, b, post, nb, after_sep, False, qend
    @property
    def role(self):
        """答语段判定（规则 R-A）：
        1. 无帖头、无提问者的帖（尾戳后的独立回复）：有尾戳收束即答语；
        2. 作者帖头而无提问者（作者自发帖，如解盘、图例）：答语；
        3. 其余：段须紧随分隔符（after_sep），并且满足其一：其后不紧跟分隔符；
           或从帖尾倒数，其后的帖内分隔符个数为偶数（帖总以作者答语收尾）；
           但以问号或“吗”“呢”收尾且其后紧跟分隔符的段一律是问句。"""
        p = self.post; n = len(p.seps)
        if p.kind == 'NONE' and not p.questioners and not self.after_sep:
            return 'A' if p.close is not None else 'NONE'
        if p.kind == 'AH' and not p.questioners: return 'A'
        if not self.after_sep: return 'Q'
        if self.followed and self.qend: return 'Q'
        if not self.followed or (n - self.nb) % 2 == 0: return 'A'
        return 'Q'

class Lesson:
    """对一课答疑区跑状态机；产出段表 segs[行] = [Seg] 与帖表 posts"""
    def __init__(self, corpus, k):
        self.k = k; self.L = corpus.lines(k); self.rs = corpus.reply_start(k)
        self.posts = []; self.segs = collections.defaultdict(list)
        self.cur = None; self.wait = None; self.last_pos = None
        self.state = 'HDR'; self.pending = None; self.pending_ln = None; self.text_since_q = False
        self.tok_ln = None; self.tok_end = 0
        self.toks = collections.defaultdict(list)
        if self.rs is not None: self._run()
    def _new(self, pos, kind):
        if self.cur is not None and self.cur.close is None and self.last_pos is not None: self.cur.end = self.last_pos
        self.cur = Post(pos, kind); self.posts.append(self.cur); self.wait = None
    def _open(self):
        c = self.cur
        return c is not None and c.close is None
    def _run(self):
        self.last_pos = (self.rs, 0)
        for ln in range(self.rs, len(self.L) + 1):
            s = self.L[ln - 1]
            if not s.strip(): continue
            p = 0
            for a, b, kind, txt in tokenize(s) + [(len(s), len(s), 'EOL', '')]:
                seg = s[p:a]
                if seg.strip():
                    if not self._open(): self._new((ln, p), 'NONE')
                    self.wait = None; self.text_since_q = True
                    sg = Seg(p, a, self.cur, len(self.cur.seps), self.state == 'SEP', seg.rstrip(' \t\u3000\xa0').endswith(('？', '?', '吗', '呢')))
                    self.segs[ln].append(sg); self.pending = sg; self.pending_ln = ln
                    self.last_pos = (ln, a)
                p = b
                if kind == 'EOL': break
                if kind == 'SEP' and self.pending is not None and (self.pending_ln == ln or not s[:a].strip()):
                    self.pending.followed = True
                if kind != 'SEP' or True: self.pending = None
                self._step(kind, txt, ln, a, s)
                if kind in ('QN', 'TSX'):
                    self.text_since_q = False
                    if self.cur is not None and self.cur.questioners and kind == 'QN' or (kind == 'TSX' and self.cur is not None and self.cur.questioners and self.cur.ah_ts != ln):
                        self.cur.qlines.add(ln)
                self.tok_ln, self.tok_end = ln, b
                self.state = 'SEP' if kind == 'SEP' else 'HDR'
                self.toks[ln].append((kind, bool(RE_TS.search(txt)), self.cur if kind != 'PSEP' else None))
                if self.cur is not None and self.cur.close is None: self.last_pos = (ln, b)
        if self._open(): self.cur.end = self.last_pos
    def _step(self, kind, txt, ln, a, s):
        cur = self.cur
        if kind == 'CS':
            if not self._open(): self._new((ln, a), 'NONE'); cur = self.cur
            cur.close = ln; cur.end = (ln, a + len(txt)); self.wait = None; return
        if kind == 'PSEP':
            if self._open(): cur.end = (ln, a)
            self.cur = None; self.wait = None; return
        if kind == 'AH':
            if self._open() and cur.questioners and not cur.seps and s[:a].strip():
                return  # 问句内转引的作者帖头（行中出现），不另起帖
            self._new((ln, a), 'AH'); self.cur.ah = ln; self.cur.near = '缠中说缠' in txt
            if RE_TS.search(txt): self.cur.ah_ts = ln
            else: self.wait = 'AH'
            return
        if kind == 'QN':
            has_ts = bool(RE_TS.search(txt))
            name = re.sub(TS, '', txt).replace('删除此人所有评论', '').replace('[匿名]', '').replace('匿名]', '').replace('文章提交者：', '').replace('文章提交者:', '').strip() or None
            if self._open() and cur.kind == 'Q' and not cur.seps and not self.text_since_q:
                cur.questioners.append((ln, name))  # 连续帖头：转引链
            elif self._open() and cur.kind == 'AH' and not cur.seps:
                if cur.questioners and cur.questioners[-1][1] is None and not self.text_since_q:
                    cur.questioners[-1] = (cur.questioners[-1][0], name)  # 时间在前、名在后的同一提问者
                else:
                    cur.questioners.append((ln, name))
            else:
                self._new((ln, a), 'Q'); self.cur.questioners.append((ln, name))
            self.wait = None if has_ts else 'Q'
            return
        if kind == 'TSX':
            pre = s[self.tok_end:a].strip() if self.tok_ln == ln else s[:a].strip()
            name = pre if pre and len(pre) <= 24 and not re.search(r'[，。？！,.?!=＝]', pre) else None
            if self.wait == 'AH' and self._open(): cur.ah_ts = ln; self.wait = None; return
            if self.wait == 'Q' and self._open(): self.wait = None; return
            if self._open() and cur.kind in ('AH', 'Q') and not cur.seps:
                cur.questioners.append((ln, name)); return
            self._new((ln, a), 'Q'); self.cur.questioners.append((ln, name)); return
        if kind == 'SEP':
            if not self._open():
                if s.strip() == txt.strip(): return  # 尾戳后的整行分隔线
                self._new((ln, a), 'NONE')
            self.cur.seps.append(ln); self.wait = None
            return
    def locate(self, ln, i, j):
        """返回 (角色, post, 是否整体在单段内)"""
        for x in self.segs.get(ln, []):
            if x.a <= i and j <= x.b: return x.role, x.post, True
        hit = [x for x in self.segs.get(ln, []) if x.a < j and i < x.b]
        if hit: return hit[0].role, hit[0].post, False
        return None, None, False

def merged_class(les, ln):
    """合并行分类：行内带时间戳的记号（帖头时间、尾戳）分属两个及以上帖 → 多帖合并行；
    否则为单帖行（一行一问一答、单帖多轮续行；可尾挂下一帖的无时间帖头残片）"""
    posts = {id(p) for kind, has_ts, p in les.toks.get(ln, []) if has_ts and p is not None}
    return '多帖合并行' if len(posts) >= 2 else '单帖行'

def answer_role(role, post):
    """段角色是否为作者答语：A 段；或无问独立回复（NONE 文字段后接尾戳收束）"""
    if role == 'A': return True
    return False

def layout(post, lesson):
    if post is None: return '未判定'
    one_line = post.start[0] == post.end[0]
    if post.kind == 'NONE': return '丁：无问独立回复（尾戳收束）' if post.close else '未判定'
    if one_line: return '丙：单行问答'
    if post.kind == 'AH': return '乙：作者帖头引问'
    return '甲：问头在前、尾戳收束' if post.close else '戊：问头在前、无尾戳'

def is_merged(s):
    if len(RE_TS.findall(s)) >= 2: return True
    if re.search(r'\*{4,}', TOKEN_RES[0][1].sub('', s)): return True  # 尾戳自带的星号不算跨帖分隔
    t = s.strip()
    if re.search(r'[=＝]{5,}', t[1:-1] if len(t) > 2 else '') and not re.match(r'^[=＝]+$', t): return True
    if re.search(r'-{5,}', t[1:-1] if len(t) > 2 else '') and not re.match(r'^-+$', t): return True
    return False

# ---------------------------------------------------------------- 文档课行抽取
RE_HARD = re.compile(r'【(正文|答疑|解盘|课间) (\d{3}):(\d+)】「([^「」]*)」')
RE_CITE = re.compile(r'(?<![0-9])(\d{3}):(\d{1,4})(?![0-9:])((?:\s*[\u2013\-~至]\s*(?:\d{3}:)?\d{1,4}(?![0-9:.]))?)((?:[、/](?!\d{3}:)\d{1,4}(?![0-9:.]))*)')

def doc_cites(line):
    """一物理行里的全部课行出现：[(课, 行集合, 原文片段)]；区间展开，`、`/`/` 续号展开"""
    out = []
    for m in RE_CITE.finditer(line):
        k, a = m.group(1), int(m.group(2)); S = {a}
        rng = m.group(3)
        if rng:
            mm = re.search(r'(?:(\d{3}):)?(\d{1,4})\s*$', rng)
            if mm and (mm.group(1) in (None, k)):
                b = int(mm.group(2))
                if a < b <= a + 400: S |= set(range(a, b + 1))
        for x in re.findall(r'\d{1,4}', m.group(4) or ''): S.add(int(x))
        out.append((k, S, m.group(0)))
    return out

# ---------------------------------------------------------------- 输入
def load_ledger(p):
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]

def load_excl(p):
    d = json.load(open(p, encoding='utf-8'))
    ids = {e['id'] for e in d['excluded_entries']}
    cites = {e['cite'] for e in d['excluded_entries']} | {e['cite'] for e in d.get('excluded_lines_r3', [])}
    return ids, cites

def norm(s): return s.replace('\xa0', ' ')

def find_pos(s, q):
    i = norm(s).find(norm(q))
    return (i, i + len(q)) if i >= 0 else (None, None)

# ---------------------------------------------------------------- G1
def check_g1(docs, ban_cites, red):
    n = 0
    ban = collections.defaultdict(set)
    for c in ban_cites:
        k, l = c.split(':'); ban[k].add(int(l))
    for p in docs:
        for no, line in enumerate(open(p, encoding='utf-8').read().split('\n'), 1):
            for k, S, frag in doc_cites(line):
                hit = sorted(S & ban.get(k, set()))
                for l in hit:
                    n += 1; c = f'{k}:{l}'
                    if '〔禁引〕' not in line:
                        red.append(('G1', os.path.basename(p), no, c, '缺〔禁引〕登记标记：' + frag))
                        continue
                    for m in RE_HARD.finditer(line):
                        if m.group(2) == k and int(m.group(3)) == l:
                            red.append(('G1', os.path.basename(p), no, c, '登记行内仍有该课行硬引文'))
    return n

# ---------------------------------------------------------------- G2
def check_g2(corpus, ledger, ex_ids, ex_cites, docs, red, und, info):
    lessons = {}
    def les(k):
        if k not in lessons: lessons[k] = Lesson(corpus, k)
        return lessons[k]
    def judge(k, ln, q):
        s = corpus.lines(k)[ln - 1]
        parts = [x for x in re.split(r'…+', q) if x.strip()]
        res = []
        for part in parts:
            i, j = find_pos(s, part)
            if i is None: return ('notfound', None, None)
            role, post, whole = les(k).locate(ln, i, j)
            if role is None: return ('nosegment', None, None)
            if not whole: return ('span', role, post)
            if not answer_role(role, post): return ('notanswer', role, post)
            res.append((role, post))
        return ('ok', res[0][0] if res else None, res[0][1] if res else None)
    merged_cites = {}
    for o in ledger:
        k, l = o['cite'].split(':'); l = int(l)
        try: s = corpus.lines(k)[l - 1]
        except (KeyError, IndexError): red.append(('G2', 'ledger', o['id'], o['cite'], '课行不存在')); continue
        if not is_merged(s): continue
        v, role, post = judge(k, l, o['quote'])
        cls = merged_class(les(k), l)
        merged_cites.setdefault(o['cite'], []).append((o['id'], v))
        info.append(('G2', o['id'], o['cite'], v, cls, '禁引' if (o['id'] in ex_ids or o['cite'] in ex_cites) else '未禁'))
        if v == 'ok': continue
        if o['id'] in ex_ids or o['cite'] in ex_cites: continue
        if v in ('notfound', 'nosegment'):
            und.append(('G2', 'ledger', o['id'], o['cite'], v)); continue
        red.append(('G2', 'ledger', o['id'], o['cite'], '合并行引文不在单一作者答语段：' + v))
    for p in docs:
        for no, line in enumerate(open(p, encoding='utf-8').read().split('\n'), 1):
            for m in RE_HARD.finditer(line):
                k, l, q = m.group(2), int(m.group(3)), m.group(4)
                try: s = corpus.lines(k)[l - 1]
                except (KeyError, IndexError): red.append(('G2', os.path.basename(p), no, f'{k}:{l}', '课行不存在')); continue
                if not is_merged(s): continue
                c = f'{k}:{l}'
                if c in ex_cites: continue  # 由 G1 管
                v, role, post = judge(k, l, q)
                if v != 'ok': red.append(('G2', os.path.basename(p), no, c, '硬引文落在合并行的非答语段：' + v))
            for k, S, frag in doc_cites(line):
                for l in S:
                    c = f'{k}:{l}'
                    try: s = corpus.lines(k)[l - 1]
                    except (KeyError, IndexError):
                        if len(S) == 1: red.append(('G2', os.path.basename(p), no, c, '课行不存在'))
                        continue
                    if not s.strip() or not is_merged(s) or c in ex_cites: continue
                    if c not in merged_cites:
                        red.append(('G2', os.path.basename(p), no, c, '合并行无台账引文可定位且不在禁引表'))
                    elif any(v != 'ok' for _, v in merged_cites[c]):
                        red.append(('G2', os.path.basename(p), no, c, '合并行含不合格台账引文且不在禁引表'))
    return lessons

# ---------------------------------------------------------------- G3
RE_OLD = re.compile(r'^L(\d+):')
RE_OLDQ = re.compile(r'提问=L(\d+)')

def compute_pool(corpus, ledger, targets, lessons):
    byid = {o['id']: o for o in ledger}
    out = []
    for t in targets:
        o = byid.get(t['id']); k = t['lesson']; ln = t['line']
        rec = {'id': t['id'], 'lesson': k, 'line': ln}
        if o is None or o['cite'] != f'{k}:{ln}':
            rec.update(layout='未判定', verdict='undecidable', why='台账无此 id 或课行不符'); out.append(rec); continue
        if k not in lessons: lessons[k] = Lesson(corpus, k)
        les = lessons[k]; s = corpus.lines(k)[ln - 1]
        i, j = find_pos(s, o['quote'])
        if i is None:
            rec.update(layout='未判定', verdict='undecidable', why='引文不在原行'); out.append(rec); continue
        role, post, whole = les.locate(ln, i, j)
        rec['layout'] = layout(post, les)
        if post is None:
            rec.update(verdict='undecidable', why='切不出所在段'); out.append(rec); continue
        rec['post_start'] = post.start[0]; rec['post_end'] = post.end[0]
        rec['questioner_lines'] = [q[0] for q in post.questioners]
        rec['questioner_names'] = [q[1] for q in post.questioners]
        rec['questioner_all_lines'] = sorted(post.qlines | {q[0] for q in post.questioners})
        rec['reply_time_line'] = post.close if post.close is not None else post.ah_ts
        rec['author_header_line'] = post.ah
        rec['rounds'] = post.rounds
        rec['segment_role'] = role
        named = []
        for q in post.questioners:
            if q[1] is not None and q[1] not in named: named.append(q[1])
        distinct = named
        flags = []; undec = []
        if not whole: undec.append('引文跨段')
        if not answer_role(role, post): undec.append('答语段机械不能确认')
        if len(distinct) >= 2: flags.append('帖内第二提问者')
        if post.near: flags.append('近名帖头')
        if rec['layout'].startswith('戊'): undec.append('无尾戳收束，帖尾由下一帖头推定')
        if rec['layout'] == '未判定': undec.append('版式未判定')
        rec['flags'] = flags + undec
        if flags: rec['verdict'] = 'red'
        elif undec: rec['verdict'] = 'undecidable'
        else: rec['verdict'] = 'ok'
        out.append(rec)
    return out

def header_lines(rec):
    S = set(rec.get('questioner_lines') or []) | set(rec.get('questioner_all_lines') or [])
    for x in ('reply_time_line', 'author_header_line'):
        if rec.get(x) is not None: S.add(rec[x])
    return S

def old_header(o):
    h = o.get('context_header', '')
    m = RE_OLD.match(h); q = RE_OLDQ.search(h)
    return (int(m.group(1)) if m else None, int(q.group(1)) if q else None)

def compare_record(fresh, rec_rows, kind):
    """返回差异表 [(id, 课行, 差异说明)]"""
    by = {r['id']: r for r in rec_rows}; diffs = []
    for f in fresh:
        if f.get('verdict') == 'undecidable' or 'post_start' not in f: continue
        r = by.get(f['id'])
        if r is None: diffs.append((f['id'], f"{f['lesson']}:{f['line']}", '记录缺此 id')); continue
        if kind == 'old':
            a, q = old_header(r)
            span = (f['post_start'], f['post_end'])
            hl = header_lines(f)
            bad = []
            for nm, x in (('回复行', a), ('提问行', q)):
                if x is None: continue
                if not (span[0] <= x <= span[1]): bad.append(f'{nm} L{x} 在新算帖 L{span[0]} 至 {span[1]} 之外（跨帖绑定）')
                elif x not in hl: bad.append(f'{nm} L{x} 不是新算帖头行 {sorted(hl)}')
            if bad: diffs.append((f['id'], f"{f['lesson']}:{f['line']}", '；'.join(bad)))
        else:
            for key in ('post_start', 'post_end', 'questioner_lines', 'reply_time_line', 'layout'):
                if r.get(key) != f.get(key):
                    diffs.append((f['id'], f"{f['lesson']}:{f['line']}", f'{key}: 记录 {r.get(key)} ≠ 新算 {f.get(key)}'))
    return diffs

def check_g3(corpus, ledger, ex_ids, targets, old_rows, rec_rows, manual, red, und, info, lessons):
    fresh = compute_pool(corpus, ledger, targets, lessons)
    for f in fresh:
        m = manual.get(str(f['id']))
        if m is None: continue
        if f['verdict'] != 'undecidable':
            red.append(('G3', f['id'], f"{f['lesson']}:{f['line']}", '人工判定只许用于无法判定项，本条机算为 ' + f['verdict'])); continue
        L = corpus.lines(f['lesson']); a, b = m['post_start'], m['post_end']
        hl = [x for x in (m.get('questioner_lines') or []) + [m.get('reply_time_line'), m.get('author_header_line')] if x is not None]
        if not (a <= f['line'] <= b) or any(not (a <= x <= b) or not L[x - 1].strip() for x in hl):
            red.append(('G3', f['id'], f"{f['lesson']}:{f['line']}", '人工判定的帖边界与目标行或帖头行不自洽')); continue
        for key in ('post_start', 'post_end', 'questioner_lines', 'reply_time_line', 'author_header_line', 'layout', 'layout_note'):
            if key in m: f[key] = m[key]
        f['verdict'] = 'ok_manual'; f['manual_reason'] = m['reason']
    for f in fresh:
        c = f"{f['lesson']}:{f['line']}"
        if f['verdict'] == 'undecidable':
            if f['id'] in ex_ids: info.append(('G3', f['id'], c, '已禁引：' + (f.get('why') or ','.join(f.get('flags', [])))))
            else: und.append(('G3', f['id'], c, f.get('why') or ','.join(f.get('flags', []))))
        elif f['verdict'] == 'red':
            if f['id'] in ex_ids: info.append(('G3', f['id'], c, '已禁引：' + ','.join(f['flags'])))
            else: red.append(('G3', f['id'], c, ','.join(f['flags'])))
    old_diffs = compare_record(fresh, old_rows, 'old')
    for d in old_diffs: info.append(('G3-旧记录差异',) + d)
    if rec_rows is None:
        for d in old_diffs:
            if d[0] in ex_ids: continue
            red.append(('G3', d[0], d[1], '旧记录帖头与新算不符：' + d[2]))
    else:
        for d in compare_record(fresh, rec_rows, 'r3'):
            red.append(('G3', d[0], d[1], '现行记录与新算不符：' + d[2]))
    return fresh, old_diffs

def reconstruct_375(reg_tmp, corpus_dir, ledger):
    """按二审口径重建 375：答疑、非原人工名单、classify=A2、无 forward_flag"""
    sys.path.insert(0, reg_tmp)
    import lib, attrib  # noqa: E402  原脚本，只读调用
    lib.BLOG = corpus_dir; lib._cache.clear()
    mj = json.load(open(os.path.join(reg_tmp, 'manual_author_confirmed.json'), encoding='utf-8'))
    mids = {int(x['id']) for x in mj}
    out = []
    for o in ledger:
        if o['who'] != '答疑' or o['id'] in mids: continue
        k, l = o['cite'].split(':'); l = int(l)
        s = lib.load(k)[0][l - 1]
        i = s.find(o['quote'])
        if i < 0: i = s.replace('\xa0', ' ').find(o['quote'].replace('\xa0', ' '))
        if i < 0: continue
        if attrib.classify(k, l, i) != 'A2': continue
        if attrib.forward_flag(k, l, i + len(o['quote'])): continue
        out.append({'id': o['id'], 'lesson': k, 'line': l})
    return out

# ---------------------------------------------------------------- 主程序
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', default=os.path.join(REPO, 'docs', 'chanlun', 'text', 'blog'))
    ap.add_argument('--ledger', default=os.path.join(REG, 'tmp', 'ledger_final.jsonl'))
    ap.add_argument('--exclusions', default=os.path.join(REG, 'tmp', 'hard_cite_exclusions.json'))
    ap.add_argument('--pool-old', default=os.path.join(REG, 'tmp', 'pool_375_recheck.jsonl'))
    ap.add_argument('--pool-record', default=os.path.join(REG, 'tmp', 'pool_375_recheck_r3.jsonl'))
    ap.add_argument('--g3-manual', default=os.path.join(HERE, 'g3_manual.json'))
    ap.add_argument('--docs', nargs='*', default=[os.path.join(REG, x) for x in (
        'FM-09-原典登记册.md', 'FM-MASTER-PLAN-v2.md', 'FM-09-附录1-全量台账.md', 'FM-09-附录2-四清单分类索引.md')])
    ap.add_argument('--no-set-check', action='store_true', help='夹具用：不按原脚本重建 375 总体')
    ap.add_argument('--emit-pool', help='把新算 G3 结果写成本轮记录（JSONL）')
    ap.add_argument('--report', help='把红项、无法判定项与差异表写入该文本文件')
    a = ap.parse_args(argv)
    if not os.path.isdir(a.corpus): print('无法判定：语料目录不存在', a.corpus); return 2
    corpus = Corpus(a.corpus)
    ledger = load_ledger(a.ledger)
    ex_ids, ex_cites = load_excl(a.exclusions)
    red, und, info = [], [], []
    n1 = check_g1(a.docs, ex_cites, red)
    lessons = check_g2(corpus, ledger, ex_ids, ex_cites, a.docs, red, und, info)
    old_rows = load_ledger(a.pool_old) if os.path.exists(a.pool_old) else []
    targets = [{'id': r['id'], 'lesson': r['lesson'], 'line': r['line']} for r in old_rows]
    if not a.no_set_check:
        recon = reconstruct_375(os.path.join(REG, 'tmp'), a.corpus, ledger)
        if [x['id'] for x in recon] != [x['id'] for x in targets]:
            red.append(('G3', '-', '-', f'375 总体重建不符：重建 {len(recon)} 条，记录 {len(targets)} 条'))
        targets = recon
    rec_rows = None
    if a.pool_record and os.path.exists(a.pool_record) and not a.emit_pool:
        rec_rows = load_ledger(a.pool_record)
    manual = json.load(open(a.g3_manual, encoding='utf-8')) if a.g3_manual and os.path.exists(a.g3_manual) else {}
    fresh, old_diffs = check_g3(corpus, ledger, ex_ids, targets, old_rows, rec_rows, manual, red, und, info, lessons)
    if a.emit_pool:
        dmap = {d[0]: d[2] for d in old_diffs}
        omap = {r['id']: r.get('context_header') for r in old_rows}
        with open(a.emit_pool, 'w', encoding='utf-8') as f:
            for r in fresh:
                r = dict(r)
                r['excluded'] = r['id'] in ex_ids
                r['old_context_header'] = omap.get(r['id'])
                r['diff_vs_old'] = dmap.get(r['id'])
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    lay = collections.Counter(f.get('layout') for f in fresh)
    lines = [f'G1 禁引出现 {n1} 处；G2 合并行台账引文 {sum(1 for x in info if x[0]=="G2")} 条；G3 目标 {len(fresh)} 条，版式 {dict(lay)}；旧记录差异 {len(old_diffs)} 条',
             f'红 {len(red)}；无法判定 {len(und)}']
    for r in red: lines.append('RED ' + ' | '.join(map(str, r)))
    for u in und: lines.append('UND ' + ' | '.join(map(str, u)))
    for x in info: lines.append('INFO ' + ' | '.join(map(str, x)))
    if a.report:
        open(a.report, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    for l in lines[:2]: print(l)
    for l in lines[2:2 + 60]:
        if l.startswith(('RED', 'UND')): print(l)
    rc = 1 if red else (2 if und else 0)
    print('exit', rc)
    return rc

if __name__ == '__main__':
    sys.exit(main())
