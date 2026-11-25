#!/usr/bin/env python3
"""给两个附录里的禁引课行打登记标记（幂等）。

规则：禁引表（tmp/hard_cite_exclusions.json 的 excluded_entries 与 excluded_lines_r3）里的课行，
  1. 硬引文形态 `【归属 课:行】「` 改为 `〔禁引〕归属 课:行「`：保留逐字文本以便追溯，去掉出处框，不再是硬引文；
  2. 其余提及该课行、但所在物理行还没有 `〔禁引〕` 的，在第一次提及前插入 `〔禁引〕`。
只处理两个附录；主册与手册逐处人工改写。
用法：python3 -I fm09-register/guards/mark_appendix_bans.py
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard_register as g  # noqa: E402

FILES = ['FM-09-附录1-全量台账.md', 'FM-09-附录2-四清单分类索引.md']
_, ban = g.load_excl(os.path.join(g.REG, 'tmp', 'hard_cite_exclusions.json'))
banset = {(c.split(':')[0], int(c.split(':')[1])) for c in ban}

def fix_line(line):
    def hard(m):
        if (m.group(2), int(m.group(3))) in banset:
            return f'〔禁引〕{m.group(1)} {m.group(2)}:{m.group(3)}「'
        return m.group(0)
    line = re.sub(r'【(正文|答疑|解盘|课间) (\d{3}):(\d+)】「', hard, line)
    if '〔禁引〕' in line: return line
    for m in g.RE_CITE.finditer(line):
        k = m.group(1)
        hits = [x for x in g.doc_cites(m.group(0)) if any((x[0], l) in banset for l in x[1])]
        if hits:
            return line[:m.start()] + '〔禁引〕' + line[m.start():]
    return line

for name in FILES:
    p = os.path.join(g.REG, name)
    src = open(p, encoding='utf-8').read().split('\n')
    out = [fix_line(l) for l in src]
    n = sum(1 for a, b in zip(src, out) if a != b)
    open(p, 'w', encoding='utf-8').write('\n'.join(out))
    print(name, '改动行', n)
