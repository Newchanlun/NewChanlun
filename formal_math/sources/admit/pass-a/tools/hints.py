#!/usr/bin/env python3
"""复查提示：列出摘句区间内含括注、引号、「缠中说禅」「网友」等记号的条目及其片段，仅供人工复核，不作判定。"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import entries, lines_of, split_cite, OUT
R = {r['id']: r for r in (json.loads(l) for l in open(OUT, encoding='utf-8'))}
PAT = re.compile(r'[（(【\[〔][^）)】\]〕]{0,60}[）)】\]〕]?|[“"「『][^”"」』]{0,40}[”"」』]?|缠中说禅|网友|注[:：]|娇')
for e in entries():
    k, ln = split_cite(e['cite']); s = lines_of(k)[ln - 1]; r = R[e['id']]
    q = ''.join(s[a:b] for a, b in r['quote_spans'])
    hits = [m.group(0) for m in PAT.finditer(q)]
    hits = [h for h in hits if not re.fullmatch(r'缠中说禅', h)] + (['缠中说禅'] if '缠中说禅' in q and not re.search(r'缠中说禅(?:[^\s，。]{0,8})(?:定理|定律|原理|中枢|盘整|趋势|买|卖|力度|指标|操作|程序|笔|分解|小背驰|走势)', q) else [])
    if hits:
        print(e['id'], k + ':' + str(ln), r['verdict'], ' | '.join(hits))
