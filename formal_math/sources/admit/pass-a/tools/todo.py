#!/usr/bin/env python3
"""列出某批（view.py 的分批）中尚无判定的 id。用法：todo.py <批号> [预算]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import entries, split_cite
from view import lesson_batches
from build import load_decisions
b = lesson_batches(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)[int(sys.argv[1])]
D, _ = load_decisions()
ids = [r['id'] for r in entries() if split_cite(r['cite'])[0] in b]
print('批内', len(ids), '缺判定', [i for i in ids if i not in D])
