#!/usr/bin/env python3
"""在 r2 基线（36fc364）的原件上跑护栏，生成 guards/baseline-red.txt（“先红”证据）。

从 git 对象取基线的四份文档、禁引表与旧帖头记录，放进临时目录；语料与台账用当前检出
（本轮未改，语料指纹见 README）。不读本轮新增的 r3 记录与人工判定。
用法：python3 -I fm09-register/guards/baseline.py
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard_register as g  # noqa: E402

BASE = '36fc364aea774f8f2e9cd0de994cd500c2139bb0'
DOCS = ['FM-09-原典登记册.md', 'FM-MASTER-PLAN-v2.md', 'FM-09-附录1-全量台账.md', 'FM-09-附录2-四清单分类索引.md']

def show(rel, dst):
    data = subprocess.run(['git', '-C', g.REPO, 'show', f'{BASE}:fm09-register/{rel}'], check=True, capture_output=True).stdout
    open(dst, 'wb').write(data)

with tempfile.TemporaryDirectory() as td:
    for d in DOCS: show(d, os.path.join(td, d))
    show('tmp/hard_cite_exclusions.json', os.path.join(td, 'excl.json'))
    show('tmp/pool_375_recheck.jsonl', os.path.join(td, 'pool.jsonl'))
    out = os.path.join(HERE, 'baseline-red.txt')
    rc = g.main(['--exclusions', os.path.join(td, 'excl.json'), '--pool-old', os.path.join(td, 'pool.jsonl'),
                 '--pool-record', os.path.join(td, '无.jsonl'), '--g3-manual', os.path.join(td, '无.json'),
                 '--report', out, '--docs'] + [os.path.join(td, d) for d in DOCS])
    body = open(out, encoding='utf-8').read()
    open(out, 'w', encoding='utf-8').write(f'# 基线 {BASE} 上的护栏结果，退出码 {rc}\n' + body)
    print('baseline exit', rc)
