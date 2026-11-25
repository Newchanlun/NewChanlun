#!/usr/bin/env python3
"""merge.py 重建用的最小 lib 替身。

正本 `fm09-register/tmp/lib.py` 属登记册，按 #2317 不入库；merge.py 只用到其中的
`BLOG`（会被 merge.py 覆写）与 `load(k)[0]`（某课的行列表，按 '\\n' 切分，0 起）。
下面 `load` 的取文逻辑与正本逐句等价：课文件名须以「课号-」开头且在以三位数字加连字符
开头的文件里恰有一个。本文件只服务 check_admit_table.py 在临时目录里搭的重建环境。
"""
import os, re
BLOG = ''
_cache = {}
def files():
    return sorted(f for f in os.listdir(BLOG) if re.match(r'^\d{3}-', f))
def load(k):
    if k in _cache: return _cache[k]
    fn = [f for f in files() if f.startswith(k + '-')]
    if len(fn) != 1: raise KeyError(k)
    lines = open(os.path.join(BLOG, fn[0]), encoding='utf-8').read().split('\n')
    mark = next((i + 1 for i, l in enumerate(lines) if '↑正文' in l), None)
    _cache[k] = (lines, mark, fn[0])
    return _cache[k]
