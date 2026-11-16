import assert from 'node:assert/strict';
import test from 'node:test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { copyEngineSnapshot } from './wayfinder-maintenance-fixture.mts';

test('旧冻结不依赖 maintenance poll 成功，真实循环退出并 stop', () => {
  const root = mkdtempSync(join(tmpdir(), 'wayfinder-freeze-poll-'));
  try {
    copyEngineSnapshot(root);
    mkdirSync(join(root, 'drain'), { recursive: true });
    writeFileSync(join(root, 'drain/state.json'), JSON.stringify({ v: 1, mode: 'draining', generation: 1 }));
    writeFileSync(join(root, '.sandcastle/maintenance.mts'), `
      export class MaintenanceClosed extends Error {}
      export const maintenanceCommand = () => { throw new Error('must not dispatch'); };
      export class MaintenanceOwner {
        poll() { throw new Error('isolated unavailable'); }
        stop() { console.log('isolated owner stopped'); }
      }
    `);
    const output = execFileSync(process.execPath, ['--experimental-strip-types', 'scripts/wayfinder_engine.mts',
      '--live', '--maintenance-root', join(root, 'maintenance'), '--poll-seconds', '0.05'],
      { cwd: root, encoding: 'utf8', timeout: 2000, stdio: ['ignore', 'pipe', 'pipe'] });
    assert.match(output, /旧入口冻结/);
    assert.match(output, /isolated owner stopped/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
