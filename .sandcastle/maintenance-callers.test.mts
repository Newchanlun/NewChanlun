import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { round, processTicket, type Deps } from './decision-claimer.mts';
import { MaintenanceOwner, MaintenanceClosed } from './maintenance.mts';
import { copyEngineSnapshot } from '../scripts/wayfinder-maintenance-fixture.mts';

test('decision 真实 round 隔离准入拒绝并保留其它票 Summary', async () => {
  const root = mkdtempSync(join(tmpdir(), 'caller-decision-'));
  const lines: string[] = [];
  const original = process.stdout.write;
  process.stdout.write = ((s: string) => { lines.push(String(s)); return true; }) as typeof original;
  try {
    const d: Deps = { mode: 'dry-run', outRoot: root, srcDir: root, repoRoot: root,
      drainRoot: join(root, 'drain'), stateRoot: join(root, 'state'), now: Date.now,
      gh: (args) => args[0] === 'issue' ? JSON.stringify({ number: 2, state: 'CLOSED', title: 'done', body: '', labels: [], assignees: [], comments: [] }) : '[]',
      git: () => assert.fail('git must not run'), model: async () => assert.fail('model must not run'),
      maintenance: { work: async (key: string, fn: () => unknown) => {
        if (key === 'ticket:1') throw new Error('previous local action unresolved');
        return fn();
      } } as unknown as MaintenanceOwner };
    await round({ mode: 'dry-run', loop: false, tickets: [1, 2], maps: [], outRoot: root,
      concurrency: 2, archaeologyOnly: false }, d);
    assert.match(lines.join(''), /#1 → error.*准入拒绝/);
    assert.match(lines.join(''), /#2 → skipped/);
    d.maintenance = { work: async () => { throw new MaintenanceClosed(); } } as unknown as MaintenanceOwner;
    await assert.rejects(processTicket(3, d), MaintenanceClosed);
    d.maintenance = { work: async (_key: string, fn: () => unknown) => { await fn(); throw new Error('after callback'); } } as unknown as MaintenanceOwner;
    await assert.rejects(processTicket(4, d), /after callback/);
  } finally { process.stdout.write = original; rmSync(root, { recursive: true, force: true }); }
});

test('Wayfinder 真实循环 Closed 停领，业务失败保持失败且继续', async () => {
  const root = mkdtempSync(join(tmpdir(), 'caller-wayfinder-'));
  const logs: string[] = [], errors: string[] = [];
  const log = console.log, error = console.error;
  console.log = (...v) => { logs.push(v.join(' ')); };
  console.error = (...v) => { errors.push(v.join(' ')); };
  try {
    copyEngineSnapshot(root);
    const engine = await import(pathToFileURL(join(root, 'scripts/wayfinder_engine.mts')).href);
    const { MaintenanceClosed: Closed } = await import(pathToFileURL(join(root, '.sandcastle/maintenance.mts')).href);
    errors.length = 0; // 模块加载配置诊断不是动作失败。
    const maps = [1, 2, 3].map(number => ({ number, title: 'map', body: '', state: 'OPEN', labels: ['wayfinder:map'],
      children: [{ number: number + 10, title: '[grilling] decision', body: '', state: 'CLOSED', labels: ['wayfinder:grilling'], assignees: [], blockedBy: 0, comments: [] }] }));
    const completed: string[] = [], attempted: string[] = [];
    const io = { frozen: () => false, maps: () => maps, ready: () => [], admit: async (fn: () => unknown) => fn(),
      execute: async () => { await Promise.resolve(); completed.push('done'); }, release: () => assert.fail('release'), status: () => {} };
    const cfg = { orchestrator: 'fixture', dryRun: false, pollSeconds: 1, specModel: '', specProvider: '', once: true, explain: false };
    await engine.runOnce(cfg, { work: async (key: string, fn: () => unknown) => {
      attempted.push(key); if (attempted.length === 2) throw new Closed(); return fn();
    } }, io);
    assert.equal(attempted.length, 2);
    assert.deepEqual(completed, ['done']);
    assert.equal(errors.length, 0);
    assert.match(logs.join(''), /停止本轮新领取/);
    attempted.length = 0;
    await engine.runOnce(cfg, { work: async (key: string, fn: () => unknown) => {
      attempted.push(key); if (attempted.length === 2) throw new Error('business failure'); return fn();
    } }, io);
    assert.equal(attempted.length, 3);
    assert.match(errors.join(''), /执行失败.*business failure/);
    // 同一个真实循环的 release 分支也必须停止，而不是给余下票记失败。
    const impls = [201, 202, 203].map(number => ({ number, title: `[impl] S${number}`, body: '',
      state: 'OPEN', labels: ['ready-for-agent'], assignees: [], blockedBy: 0, comments: [] }));
    const spec = { number: 500, title: '📋 SPEC：实施总单（map #42）', body: '', state: 'OPEN',
      labels: [], assignees: [], blockedBy: 0, comments: [{ author: 'fixture',
        body: engine.specRulingBody({ specNumber: 500, verdict: 'PASS', author: 'author', reviewer: 'reviewer',
          digest: engine.specBodyDigest(''), evidence: '/fixtures/review.json' }), createdAt: '2026-08-18T12:00:00Z' }] };
    const releaseAttempts: string[] = [], released: number[] = [];
    errors.length = 0;
    await engine.runOnce(cfg, { work: async (key: string, fn: () => unknown) => {
      releaseAttempts.push(key); if (key === 'release:202') throw new Closed(); return fn();
    } }, { ...io, maps: () => [{ ...maps[0], number: 42, children: [maps[0].children[0], spec, ...impls] }],
      ready: () => impls, release: (n: number) => { released.push(n); return null; } });
    assert.deepEqual(released, [201]);
    assert.deepEqual(releaseAttempts, ['release:201', 'release:202']);
    assert.equal(errors.length, 0);

  } finally { console.log = log; console.error = error; rmSync(root, { recursive: true, force: true }); }
});
