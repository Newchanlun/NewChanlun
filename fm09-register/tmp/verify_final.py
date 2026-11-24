#!/usr/bin/env python3
# FM-09 终版台账(ledger_final.jsonl)全量复核：
#  (1) 主引文：逐字子串、不与编者注重叠、不在人工非作者区、正文/答疑分界一致；
#      答疑区主引文的作者归属：机器状态机确认，或在 manual_author_confirmed.json（人工复核）名单内
#  (2) 备注内「…」：逐字（按…切分各片均为 本条引文/本条行/备注所引行±2行/尾注〔〕所指行 的子串）
#  (3) 备注内『…』：逐字存在于语料（不要求作者归属）
#  (4) 备注内 NNN:LLL：行存在且非空
import sys, os, re, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib, notelib as N, attrib
HERE = os.path.dirname(os.path.abspath(__file__))
WHO_REGION = {'正文': 'B', '答疑': 'P', '解盘': 'P', '课间': 'P'}
def raw_lines(cands):
    out = []
    for (k, ln) in cands:
        try: L = lib.load(k)[0]
        except KeyError: continue
        if 1 <= ln <= len(L): out.append(N.norm_nbsp(L[ln-1]))
    return out
def main(path=None):
    path = path or os.path.join(HERE, 'ledger_final.jsonl')
    rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
    confirmed = {x['id'] for x in json.load(open(os.path.join(HERE, 'manual_author_confirmed.json'), encoding='utf-8'))}
    bad = []; c = collections.Counter()
    ids = set()
    for o in rows:
        if o['id'] in ids: bad.append((o['id'], 'dup id'))
        ids.add(o['id'])
        k, ln = o['cite'].split(':'); ln = int(ln)
        ok, q, i, j, err = lib.find_quote(k, ln, o['quote'])
        if not ok or q != o['quote']: bad.append((o['id'], o['cite'], 'main quote: ' + str(err))); continue
        if lib.region(k, ln) != WHO_REGION.get(o['who']): bad.append((o['id'], o['cite'], 'region mismatch')); continue
        if o['who'] != '正文':
            cls = attrib.classify(k, ln, i)
            if (cls.startswith('REVIEW') or (o['who'] == '答疑' and attrib.forward_flag(k, ln, j))):
                if o['id'] in confirmed: c['main_manual_confirmed'] += 1
                else: bad.append((o['id'], o['cite'], 'author attribution unconfirmed: ' + cls)); continue
            else: c['main_machine_author'] += 1
        else: c['main_body'] += 1
        cands = [(k, ln)]
        for (kk, ll) in N.note_cites(o['note']):
            for d in (0, -1, 1, -2, 2): cands.append((kk, ll + d))
        pool = [N.norm_nbsp(o['quote'])] + raw_lines(cands)
        for m in re.finditer(r'「([^「」]+)」', o['note']):
            c['note_author_verbatim'] += 1
            if not N.verify_fragment(m.group(1), pool): bad.append((o['id'], o['cite'], 'note「」not verbatim: ' + m.group(1)[:40]))
        for m in re.finditer(r'『([^『』]+)』', o['note']):
            c['note_nonauthor_verbatim'] += 1
            if not N.verify_fragment(m.group(1), pool): bad.append((o['id'], o['cite'], 'note『』not verbatim: ' + m.group(1)[:40]))
        for (kk, ll) in N.note_cites(o['note']):
            c['note_cites'] += 1
            try: L = lib.load(kk)[0]
            except KeyError: bad.append((o['id'], o['cite'], f'note cite {kk}:{ll} no such file')); continue
            if not (1 <= ll <= len(L)) : bad.append((o['id'], o['cite'], f'note cite {kk}:{ll} out of range'))
        stripped = re.sub(r'「[^「」]*」|『[^『』]*』', '', o['note'])
        if re.search(r'“[^“”]{8,}”', stripped): bad.append((o['id'], o['cite'], 'unconverted long “” in note'))
    print('entries', len(rows), 'bad', len(bad), dict(c))
    for b in bad[:60]: print('BAD', b)
    return 1 if bad else 0
if __name__ == '__main__': sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
