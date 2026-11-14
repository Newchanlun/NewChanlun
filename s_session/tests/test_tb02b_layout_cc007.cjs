// #1491 ADR 0037 段 B：Q3 读者按 rule_revision 布局组件分派 CC-007 读法（layout/1 旧载荷 AsKnown；
// bounded-layout/1 分型对象去后续发展 + CC-007.development_batch 三跳只读）。具名夹具，不代替真实 S/Q 验收。
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const T = require('../browser/q3-typed.js');

const BASE = 's2-axis-quantifiers+new-bi/2';
const BOUNDED = BASE + '+bounded-layout/1';
const ref = coord => ({identity_key:'id-' + coord, payload_hash:'a'.repeat(64), receipt_id:'r-' + coord, event_id:'e-' + coord,
  input_revision:'1', revision:'1', seq:String(Number(coord) + 1), source_coord:String(coord)});
const bar = (coord, o, h, l, c) => ({source_coord:String(coord), open:String(o), high:String(h), low:String(l), close:String(c)});
const PRICES = [['left.high', 0, '10'], ['left.low', 0, '7'], ['mid.high', 1, '8'], ['mid.low', 1, '5'], ['right.high', 2, '12'], ['right.low', 2, '8']]
  .map(([name, at, value]) => ({name, source_coord:String(at), axis:name.split('.')[1], value}));
const cmp = (a, b) => (BigInt(a) < BigInt(b) ? 'LT' : BigInt(a) > BigInt(b) ? 'GT' : 'EQ');
const unitOf = b => ({bar:b, relations:['open', 'high', 'low', 'close'].flatMap(axis => PRICES.map(p => ({axis, value:b[axis], reference:p.name, reference_value:p.value, order:cmp(b[axis], p.value)})))});
const record = (kind, factKey, payload, coords, extra = {}) => ({object_id:extra.id || 'obj3-' + kind + factKey, object_revision:'1', kind, batch_id:'batch3-x', fact_key:factKey, payload,
  input_refs:coords.map(ref), source_coords:coords.map(String), first_known_generation:'3', first_known_cut:'cut-3', published_generation:'3',
  withdrawn_generation:null, withdrawal_reason:null, superseded_by:null, lifecycle:'active', ...extra.fields});
const fractalPayload = withSubsequent => {
  const p = {shape_object_id:'obj3-shape', branch:'BOTTOM', window:['0', '1', '2'], description:'中组高点和低点均严格低于相邻两组', reference_prices:PRICES,
    descriptive_labels:{status:'not_determined', reason:'no_settled_numeric_rule', labels:[], source:'fenxing.md:64-74', raw_ohlc:[bar(0, 8, 10, 7, 8), bar(1, 6, 8, 5, 6), bar(2, 10, 12, 8, 10)]}};
  if (withSubsequent) p.subsequent_development = {status:'observed', reason:null, bars:[unitOf(bar(3, 9, 11, 8, 10))]};
  return p;
};
const FRACTAL_KEY = JSON.stringify(['CC-007.fractal_description', ['0', '1', '2']]);
const fractal = withSubsequent => record('CC-007.fractal_description', FRACTAL_KEY, fractalPayload(withSubsequent), [0, 1, 2], {id:'obj3-fractal'});
const BARS = [bar(3, 9, 11, 8, 10), bar(4, 10, 13, 9, 12)];
const batches = () => BARS.map((b, i) => record('CC-007.development_batch', JSON.stringify(['CC-007.development_batch', b.source_coord]),
  {bar:b, entries:[{fractal_object_id:'obj3-fractal', unit:unitOf(b), development:{root:BARS.slice(0, i + 1).map(unitOf), count:String(i + 1)}}]}, [Number(b.source_coord)]));

test('布局组件与教义组件正交：轴表/合同只看教义串，未知或重复布局组件拒收', () => {
  assert.deepEqual(T.splitRule(BASE), {doctrine:BASE, layout:'layout/1'});
  assert.deepEqual(T.splitRule(BOUNDED), {doctrine:BASE, layout:'bounded-layout/1'});
  assert.deepEqual(T.ruleContract(BOUNDED), T.RULE_CONTRACTS[BASE]);
  for (const bad of [BASE + '+bounded-layout/2', BOUNDED + '+bounded-layout/1'])
    assert.throws(() => T.splitRule(bad), /cut规则修订未声明/);
});

test('layout/1 分型旧载荷 AsKnown 可读；bounded 库不得带后续发展，layout/1 库不得缺', async () => {
  await T.validateTyped(fractal(true));
  await T.validateTyped(fractal(true), 'layout/1');
  await T.validateTyped(fractal(false), 'bounded-layout/1');
  await assert.rejects(() => T.validateTyped(fractal(false), 'layout/1'), /完整字段不符|缺完整字段/);
  await assert.rejects(() => T.validateTyped(fractal(true), 'bounded-layout/1'), /完整字段不符/);
});

test('单元批记录：只在 bounded 库出现；单元/序列末项/计数/槽位逐项核', async () => {
  for (const b of batches()) await T.validateTyped(b, 'bounded-layout/1');
  await assert.rejects(() => T.validateTyped(batches()[0], 'layout/1'), /layout\/1 库不含单元批记录/);
  const cases = [
    b => { b.payload.entries[0].development.count = '2'; },
    b => { b.payload.entries[0].development.root = [unitOf(bar(9, 1, 1, 1, 1))]; },
    b => { b.payload.entries[0].unit.bar = bar(9, 1, 1, 1, 1); },
    b => { b.payload.entries[0].unit.relations.pop(); },
    b => { b.fact_key = JSON.stringify(['CC-007.development_batch', '4']); },
    b => { b.payload.entries = []; },
  ];
  for (const mutate of cases) {
    const b = structuredClone(batches()[0]); mutate(b);
    await assert.rejects(() => T.validateTyped(b, 'bounded-layout/1'));
  }
});

test('三跳只读绑定：entry → 本库活动分型、关系来源逐项同分型参考价、单元序列连续', async () => {
  const live = [fractal(false), ...batches()];
  const counts = await T.bindDevelopmentBatches(live, 'bounded-layout/1');
  assert.equal(counts.get('obj3-fractal'), 2n);
  // 批记录次序不影响（快照数组按出生序，读者按 bar 坐标绑定）。
  await T.bindDevelopmentBatches([fractal(false), ...batches().reverse()], 'bounded-layout/1');
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...batches()], 'layout/1'), /layout\/1 库不含单元批记录/);
  await assert.rejects(() => T.bindDevelopmentBatches(batches(), 'bounded-layout/1'), /指向缺失分型/);
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), batches()[1]], 'bounded-layout/1'), /不连续/);
  const wrong = batches(); wrong[0].payload.entries[0].unit.relations[0].reference_value = '99';
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...wrong], 'bounded-layout/1'), /后续关系来源不同/);
  const early = batches(); early[0].payload.bar = bar(2, 9, 11, 8, 10); early[0].payload.entries[0].unit.bar = early[0].payload.bar;
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), early[0]], 'bounded-layout/1'), /右组之后/);
  // layout/1 库照旧：没有批记录即通过。
  await T.bindDevelopmentBatches([fractal(true)], 'layout/1');
});

// #1419 31P bounded-layout/2：版本表只多一条精确现役 W2 串；单元在 bar/relations 外仅加 source_ref（八字段 RawRefSpec 文本）。
const LEGACY_W2_NO_SEG_OWN = 's2-axis-quantifiers+new-bi/2+segment-second/2+segment-turn/1+second-seq-scan-budget/2+center-seed/1+center-pair/1+raw-initialization-w/2';
const W2_DOCTRINE = T.V3_STRUCTURE_RULE + '+raw-initialization-w/2';
const B2 = 'bounded-layout/2';
const sourcedUnit = (b, revision = '1') => ({...unitOf(b), source_ref:{...ref(b.source_coord), input_revision:revision, revision}});
const batches2 = (revision = '1') => BARS.map((b, i) => {
  const units = BARS.slice(0, i + 1).map(x => sourcedUnit(x, revision));
  const r = record('CC-007.development_batch', JSON.stringify(['CC-007.development_batch', b.source_coord]),
    {bar:b, entries:[{fractal_object_id:'obj3-fractal', unit:units[i], development:{root:units, count:String(i + 1)}}]}, [Number(b.source_coord)]);
  r.input_refs = [{...ref(b.source_coord), input_revision:revision, revision}];
  return r;
});

test('bounded-layout/2 版本表：唯一现役 W2 串与归档 W2+/1 各自精确分派，其余组合拒', () => {
  assert.deepEqual(T.splitRule(W2_DOCTRINE + '+' + B2), {doctrine:W2_DOCTRINE, layout:B2});
  assert.deepEqual(T.splitRule(W2_DOCTRINE + '+bounded-layout/1'), {doctrine:W2_DOCTRINE, layout:'bounded-layout/1'});
  assert.equal(T.LAYOUTS.BOUNDED2, B2);
  for (const bad of [BASE + '+' + B2, BOUNDED + '+' + B2, LEGACY_W2_NO_SEG_OWN + '+' + B2, LEGACY_W2_NO_SEG_OWN + '+bounded-layout/1', W2_DOCTRINE + '+' + B2 + '+' + B2, W2_DOCTRINE.replace('raw-initialization-w/2', 'raw-initialization-w/1') + '+' + B2])
    assert.throws(() => T.splitRule(bad), /cut规则修订未声明/, bad);
});

test('bounded-layout/2 单元 exact：source_ref 八字段、同坐标、等于本批披露源；旧 /1 与 /2 互不接受', async () => {
  for (const b of batches2()) await T.validateTyped(b, B2);
  for (const b of batches()) await assert.rejects(() => T.validateTyped(b, B2), /完整字段不符/);
  for (const b of batches2()) await assert.rejects(() => T.validateTyped(b, 'bounded-layout/1'), /完整字段不符/);
  await assert.rejects(() => T.validateTyped(batches2()[0], 'layout/1'), /layout\/1 库不含单元批记录/);
  const r1 = batches2('1')[0], r2 = batches2('2')[0];
  await T.validateTyped(r2, B2);
  assert.deepEqual(r1.payload.entries[0].unit.bar, r2.payload.entries[0].unit.bar);
  assert.notDeepEqual(r1.payload.entries[0].unit.source_ref, r2.payload.entries[0].unit.source_ref);
  const mixed = structuredClone(r2); mixed.input_refs = r1.input_refs;
  await assert.rejects(() => T.validateTyped(mixed, B2), /单元源引用不是本批披露源/);
  const unitCase = (mutate, pattern) => async () => {
    const b = structuredClone(batches2()[0]); const u = b.payload.entries[0].unit; mutate(u); b.payload.entries[0].development.root = [u];
    await assert.rejects(() => T.validateTyped(b, B2), pattern);
  };
  await unitCase(u => { delete u.source_ref; }, /完整字段不符/)();
  await unitCase(u => { u.source_ref = ref(4); }, /单元源引用坐标与单元 bar 不同/)();
  await unitCase(u => { u.source_ref.receipt_id = 'r-x'; }, /单元源引用不是本批披露源/)();
  await unitCase(u => { u.source_ref.revision = '2'; }, /单元源引用修订不同/)();
  await unitCase(u => { u.source_ref.payload_hash = 'A'.repeat(64); }, /SHA-256/)();
  await unitCase(u => { u.source_ref.extra = '1'; }, /完整字段不符/)();
  await unitCase(u => { u.source_ref.seq = 4; }, /非法内容值|要求标量|UTF-8/)();
  const twoRefs = structuredClone(batches2()[0]); twoRefs.input_refs.push(ref(4)); twoRefs.source_coords.push('4');
  await assert.rejects(() => T.validateTyped(twoRefs, B2), /单元源引用不是本批披露源/);
});

test('bounded-layout/2 三跳只读绑定沿用 /1 判据', async () => {
  const counts = await T.bindDevelopmentBatches([fractal(false), ...batches2()], B2);
  assert.equal(counts.get('obj3-fractal'), 2n);
  await assert.rejects(() => T.bindDevelopmentBatches(batches2(), B2), /指向缺失分型/);
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), batches2()[1]], B2), /不连续/);
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...batches2()], 'bounded-layout/9'), /未知内容布局/);
  await T.validateTyped(fractal(false), B2);
  await assert.rejects(() => T.validateTyped(fractal(true), B2), /完整字段不符/);
});

test('有界布局前缀全文绑定已验证单元：/1 与 /2 篡改前缀 bar、关系或来源均拒绝', async () => {
  for (const edit of [
    u => { u.source_ref.receipt_id = 'forged'; },
    u => { u.relations[0].order = 'EQ'; },
    u => { Object.assign(u, sourcedUnit({...u.bar, open:'99999'})); },
  ]) {
    const bs = structuredClone(batches2()); edit(bs[1].payload.entries[0].development.root[0]);
    for (const b of bs) await T.validateTyped(b, B2);
    await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...bs], B2), /单元序列未绑定已验证单元/);
  }
  for (const edit of [
    u => { u.relations[0].order = 'EQ'; },
    u => { Object.assign(u, unitOf({...u.bar, open:'99999'})); },
  ]) {
    const legacy = structuredClone(batches()); edit(legacy[1].payload.entries[0].development.root[0]);
    for (const b of legacy) await T.validateTyped(b, 'bounded-layout/1');
    await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...legacy], 'bounded-layout/1'), /单元序列未绑定已验证单元/);
  }
});

function revisedBatches() {
  const old = structuredClone(batches2('1')), current = structuredClone(batches2('2'));
  for (const b of old) Object.assign(b, {
    lifecycle:'withdrawn', withdrawn_generation:'4', withdrawal_reason:'superseded_by_revision',
    superseded_by:b.object_id + '-r2',
  });
  for (const b of current) Object.assign(b, {
    object_id:b.object_id + '-r2', first_known_generation:'4', published_generation:'4', first_known_cut:'cut-4',
  });
  return {old, current};
}

test('bounded-layout/2 撤回前缀保留出生代来源，活动前缀只绑定当前来源', async () => {
  const read = async ({old, current}) => {
    const records = [fractal(false), ...old, ...current];
    for (const b of [...old, ...current]) await T.validateTyped(b, B2);
    return T.bindDevelopmentBatches(records, B2);
  };
  assert.equal((await read(revisedBatches())).get('obj3-fractal'), 2n);
  const stale = revisedBatches();
  stale.current[1].payload.entries[0].development.root[0] = stale.old[0].payload.entries[0].unit;
  await assert.rejects(() => read(stale), /单元序列.*绑定/);
  const rewritten = revisedBatches();
  rewritten.old[1].payload.entries[0].development.root[0] = rewritten.current[0].payload.entries[0].unit;
  await assert.rejects(() => read(rewritten), /单元序列.*绑定/);
  const missing = revisedBatches(); missing.old.shift();
  await assert.rejects(() => read(missing), /单元序列.*绑定/);
  const ambiguous = revisedBatches(); ambiguous.old.push(structuredClone(ambiguous.old[0]));
  await assert.rejects(() => read(ambiguous), /单元序列绑定的版本不唯一/);
  const nullWithdrawn = revisedBatches();
  nullWithdrawn.old[0].payload.entries[0].unit.relations = Array(24).fill(null);
  nullWithdrawn.old[0].payload.entries[0].development.root = [nullWithdrawn.old[0].payload.entries[0].unit];
  nullWithdrawn.old[1].payload.entries[0].development.root[0] = nullWithdrawn.old[0].payload.entries[0].unit;
  await assert.rejects(() => T.validateTyped(nullWithdrawn.old[0], B2), /后续关系/);
  await assert.rejects(() => T.bindDevelopmentBatches([fractal(false), ...nullWithdrawn.old, ...nullWithdrawn.current], B2), /后续关系/);
  const badRefValWithdrawn = revisedBatches();
  badRefValWithdrawn.old[0].payload.entries[0].unit.relations[0].reference_value = '999';
  badRefValWithdrawn.old[0].payload.entries[0].development.root = [badRefValWithdrawn.old[0].payload.entries[0].unit];
  badRefValWithdrawn.old[1].payload.entries[0].development.root[0] = badRefValWithdrawn.old[0].payload.entries[0].unit;
  await assert.rejects(() => read(badRefValWithdrawn), /后续关系来源不同/);
});
