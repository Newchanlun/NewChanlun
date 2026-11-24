#!/usr/bin/env python3
# FM-09 交付文档引文终检（独立于生成器）：对给定 md 文件中的每一处
#   【正文|答疑|解盘|课间 NNN:LLL】「……」
# 逐条复核：(1) 引文按“…”切分后的每一片都是 blog/NNN-*.md 第 LLL 行的逐字子串；
# (2) 不与该行的编者注区间重叠；(3) 该行不在人工登记的非作者区间；(4) 归属标签与正文/答疑分界一致；
# (5) 每一片都落在已复核台账(ledger_final.jsonl)中同一引用位某条引文之内（作者归属已由状态机或人工确认）。
# 另：文中裸引用位 NNN:LLL 必须指向存在的非空行；不带【】的「」视为违规（附录全量台账的备注列除外，由 verify_final.py 复核）。
import sys, os, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib
HERE = os.path.dirname(os.path.abspath(__file__))
WHO_REGION = {'正文': 'B', '答疑': 'P', '解盘': 'P', '课间': 'P'}
RE_Q = re.compile(r'【(正文|答疑|解盘|课间) (\d{3}):(\d+)】「([^「」]*)」')
RE_CITE = re.compile(r'(?<![0-9])(\d{3}):(\d{1,4})(?![0-9])')
def norm(s): return s.replace('\xa0', ' ')
def main(paths, allow_free=False):
    rows = [json.loads(l) for l in open(os.path.join(HERE, 'ledger_final.jsonl'), encoding='utf-8') if l.strip()]
    bycite = collections.defaultdict(list)
    for o in rows: bycite[o['cite']].append(norm(o['quote']))
    total = 0; bad = []; ncite = 0
    for p in paths:
        doc = open(p, encoding='utf-8').read()
        for m in RE_Q.finditer(doc):
            total += 1
            who, k, ln, q = m.group(1), m.group(2), int(m.group(3)), m.group(4)
            try: lines = lib.load(k)[0]
            except KeyError: bad.append((p, f'{k}:{ln}', 'no such file')); continue
            if not (1 <= ln <= len(lines)): bad.append((p, f'{k}:{ln}', 'line out of range')); continue
            s = norm(lines[ln-1]); spans = lib.note_spans(lines[ln-1])
            if lib.in_manual_nonauthor(k, ln): bad.append((p, f'{k}:{ln}', 'manual non-author line')); continue
            if lib.region(k, ln) != WHO_REGION[who]: bad.append((p, f'{k}:{ln}', 'region mismatch')); continue
            parts = [x for x in re.split(r'…+', norm(q)) if x.strip()]
            if not parts: bad.append((p, f'{k}:{ln}', 'empty quote')); continue
            for part in parts:
                i = s.find(part)
                if i < 0: bad.append((p, f'{k}:{ln}', 'not verbatim: ' + part[:30])); break
                # 取一个不与编者注重叠的出现位置
                okpos = False; st = 0
                while True:
                    i = s.find(part, st)
                    if i < 0: break
                    j = i + len(part)
                    if not any(i < b and a < j for a, b in spans): okpos = True; break
                    st = i + 1
                if not okpos: bad.append((p, f'{k}:{ln}', 'overlaps editor note: ' + part[:30])); break
                if not any(part in lq for lq in bycite.get(f'{k}:{ln}', [])): bad.append((p, f'{k}:{ln}', 'not within a verified ledger quote: ' + part[:30])); break
        stripped = RE_Q.sub('', doc)
        if not allow_free:
            for m in re.finditer(r'「([^「」]{2,})」', stripped):
                bad.append((p, '-', 'free-floating 「」: ' + m.group(1)[:30]))
        for m in RE_CITE.finditer(stripped):
            ncite += 1
            k, ln = m.group(1), int(m.group(2))
            try: lines = lib.load(k)[0]
            except KeyError: bad.append((p, f'{k}:{ln}', 'bare cite: no such file')); continue
            if not (1 <= ln <= len(lines)) or not lines[ln-1].strip(): bad.append((p, f'{k}:{ln}', 'bare cite: missing/empty line'))
    print('files', len(paths), 'quotes checked', total, 'bare cites', ncite, 'bad', len(bad))
    for b in bad[:80]: print('BAD', b)
    return 1 if bad else 0
if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sys.exit(main(args, allow_free='--allow-free' in sys.argv))
