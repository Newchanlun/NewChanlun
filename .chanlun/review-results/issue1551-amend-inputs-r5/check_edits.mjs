import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const { applyCanonicalEdit, parseCanonicalEdit } =
  await import(pathToFileURL(resolve('.sandcastle/canonical-edit.mts')));
const root = process.argv[2];
const c = JSON.parse(readFileSync(resolve(root, 'canonical_edit.json')));
const primary = parseCanonicalEdit(readFileSync(resolve(root, 'draft.md'), 'utf8'), c.primary.path);
assert.deepEqual(primary, c.primary);
for (const edit of [primary, ...c.sync]) {
  const before = execFileSync('git', ['show', c.source_commit + ':' + edit.path]);
  const after = applyCanonicalEdit(edit, before.toString('utf8'));
  const actual = execFileSync('git', ['show', c.candidate_commit + ':' + edit.path]);
  assert.deepEqual(Buffer.from(after), actual);
  console.log('canonical-edit.mts: equal blob bytes: ' + edit.path);
}
