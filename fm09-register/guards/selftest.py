#!/usr/bin/env python3
"""护栏自检：必红夹具必须红，绿样本必须绿；另在真实语料上核对 G2 分类与 G3 已知阳性。

用法：python3 -I fm09-register/guards/selftest.py   退出 0 = 全部通过，1 = 有失败。
"""
import contextlib, io, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import guard_register as g  # noqa: E402

FX = os.path.join(HERE, 'fixtures')
fails = []

def run(docs, pool_old, report):
    args = ['--corpus', os.path.join(FX, 'corpus'), '--ledger', os.path.join(FX, 'ledger.jsonl'),
            '--exclusions', os.path.join(FX, 'exclusions.json'), '--pool-old', os.path.join(FX, pool_old),
            '--pool-record', os.path.join(FX, '不存在的记录.jsonl'), '--g3-manual', os.path.join(FX, '不存在的人工判定.json'),
            '--no-set-check', '--report', report, '--docs'] + [os.path.join(FX, d) for d in docs]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = g.main(args)
    return rc, open(report, encoding='utf-8').read()

def expect(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (('：' + detail) if detail and not cond else ''))
    if not cond: fails.append(name)

with tempfile.TemporaryDirectory() as td:
    rep = os.path.join(td, 'r.txt')
    # 1. 禁引复用：未标〔禁引〕的硬引、标了〔禁引〕仍硬引，两处都要红
    rc, out = run(['doc_ban_reuse.md'], 'pool_ok.jsonl', rep)
    n = out.count('RED G1')
    expect('夹具·禁引复用必红', rc == 1 and n == 2, f'rc={rc} G1 红 {n}')
    # 2. 合并行硬引：引文落在合并行第二帖的问句段，必须红
    rc, out = run(['doc_merged_hardcite.md'], 'pool_ok.jsonl', rep)
    expect('夹具·合并行硬引必红', rc == 1 and 'RED G2' in out and '非答语段' in out, f'rc={rc}')
    # 3. 跨帖绑定：第二帖答语被记到第一帖帖头下，必须红
    rc, out = run(['doc_green.md'], 'pool_cross.jsonl', rep)
    expect('夹具·跨帖绑定必红', rc == 1 and 'RED G3' in out and '跨帖绑定' in out, f'rc={rc}')
    # 4. 绿样本：登记性提及、一行一问一答、合并行内单一答语段，帖头绑定正确
    rc, out = run(['doc_green.md'], 'pool_ok.jsonl', rep)
    expect('夹具·绿样本必绿', rc == 0, out[:400])

# 5. 真实语料：G2 分类（每类至少两个真实行）
corpus = g.Corpus(os.path.join(g.REPO, 'docs', 'chanlun', 'text', 'blog'))
ledger = {o['id']: o for o in g.load_ledger(os.path.join(g.REG, 'tmp', 'ledger_final.jsonl'))}
cache = {}
def lesson(k):
    if k not in cache: cache[k] = g.Lesson(corpus, k)
    return cache[k]
def g2(id_):
    o = ledger[id_]; k, l = o['cite'].split(':'); l = int(l)
    s = corpus.lines(k)[l - 1]; i, j = g.find_pos(s, o['quote'])
    role, post, whole = lesson(k).locate(l, i, j)
    return g.is_merged(s), g.merged_class(lesson(k), l), whole and g.answer_role(role, post)

for id_, cite in ((682, '040:34'), (765, '047:116'), (849, '052:470')):
    merged, cls, ok = g2(id_)
    expect(f'真实·一行一问一答 {cite}（id {id_}）判单帖行且引文合格', merged and cls == '单帖行' and ok, f'{merged} {cls} {ok}')
for id_, cite in ((683, '040:36'), (774, '048:84')):
    merged, cls, ok = g2(id_)
    expect(f'真实·多帖合并行 {cite}（id {id_}）判多帖合并行', merged and cls == '多帖合并行', f'{merged} {cls}')

# 6. 真实语料：G3 已知阳性 id 1071（067:196 应属 067:188 至 198 的 8 月 16 日帖）
old = g.load_ledger(os.path.join(g.REG, 'tmp', 'pool_375_recheck.jsonl'))
tg = [{'id': r['id'], 'lesson': r['lesson'], 'line': r['line']} for r in old if r['id'] == 1071]
fresh = g.compute_pool(corpus, list(ledger.values()), tg, cache)
diffs = g.compare_record(fresh, [r for r in old if r['id'] == 1071], 'old')
f = fresh[0]
expect('真实·id 1071 新算帖为 067:188 至 198、提问者 067:188、回复时间 067:198',
       (f.get('post_start'), f.get('post_end'), f.get('questioner_lines'), f.get('reply_time_line')) == (188, 198, [188], 198), str(f))
expect('真实·id 1071 旧记录被判跨帖绑定', len(diffs) == 1 and '跨帖绑定' in diffs[0][2], str(diffs))

print('selftest', 'FAIL ' + str(len(fails)) if fails else 'OK')
sys.exit(1 if fails else 0)
