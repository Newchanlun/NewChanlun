/** 隔离快照使用真实维护协议，但所有 RPC 显式绑定临时账本。 */
import assert from "node:assert/strict";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

export function isolateMaintenance(root: string): void {
  for (const file of [".sandcastle/maintenance.mts",
    ".sandcastle/deepagents-pilot/pilot1742/maintenance.py"]) {
    const target = join(root, file);
    mkdirSync(dirname(target), { recursive: true });
    copyFileSync(new URL(`../${file}`, import.meta.url), target);
  }
  const engine = join(root, "scripts/wayfinder_engine.mts");
  const source = readFileSync(engine, "utf8");
  const constructor = 'new MaintenanceOwner("wayfinder")';
  assert.equal(source.split(constructor).length, 2, "快照必须有且仅有一个维护入口");
  writeFileSync(engine, source.replace(constructor,
    `new MaintenanceOwner("wayfinder", ${JSON.stringify(join(root, "maintenance"))})`));
}

export function copyEngineSnapshot(root: string): void {
  for (const file of ["scripts/wayfinder_engine.mts", ".sandcastle/cliproxy-env.mts",
    ".sandcastle/main-model.mts", ".sandcastle/scheduler-config.mts", ".sandcastle/scheduler-config.json",
    ".sandcastle/drain-control.mts", ".sandcastle/drain-control.py", ".sandcastle/deepagents-cutover.mts",
    ".sandcastle/queue-policy.json", ".sandcastle/deepagents-pilot/pilot1742/cutover.py"]) {
    const target = join(root, file);
    mkdirSync(dirname(target), { recursive: true });
    let source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");
    source = source.replace('"/Volumes/AgentStorage/newchanlun-legacy-drain"', JSON.stringify(join(root, "drain")))
      .replace('"/Volumes/AgentStorage/deepagents-exec"', JSON.stringify(join(root, "exec")));
    writeFileSync(target, source);
  }
  isolateMaintenance(root);
}
