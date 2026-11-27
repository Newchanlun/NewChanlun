#!/usr/bin/env -S npx tsx
import { randomUUID } from "node:crypto";
import { lstatSync, realpathSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { At18BootstrapError, renderSummary } from "./at18-format.ts";
import { generateAt18 } from "./at18-report.ts";
import { At18Repository, inside, readOwnManifest } from "./at18-source.ts";

async function run(repo: string, manifestPath: string, output: string, upstream: string[]) {
  const root = realpathSync(repo);
  const repository = new At18Repository(root);
  const own = readOwnManifest(repository, manifestPath);
  let directory: string;
  try {
    directory = realpathSync(output);
    if (resolve(output) !== directory || inside(root, directory) || !lstatSync(directory).isDirectory() ||
        ["at18-input-bundle.json", "at18-report.json", "summary.md"].some(name => lstatSync(join(directory, name), { throwIfNoEntry: false }))) {
      throw new Error("输出必须使用不含本次产物的真实仓外目录。");
    }
  } catch {
    throw new At18BootstrapError("OUTPUT_WRITE_FAILED", "输出必须使用不含本次产物的真实仓外目录。");
  }
  const bundlePath = join(directory, "at18-input-bundle.json");
  const reportPath = join(directory, "at18-report.json");
  const summary = join(directory, "summary.md");
  const data = await generateAt18(repository, own, upstream, bundlePath);
  function publish(target: string, bytes: Buffer | string) {
    try {
      const temporary = target + "." + randomUUID() + ".tmp";
      writeFileSync(temporary, bytes, { mode: 0o600, flag: "wx" });
      renameSync(temporary, target);
    } catch {
      throw new At18BootstrapError("OUTPUT_WRITE_FAILED", "无法原子发布产物。", target);
    }
  }
  if (data.bundleBytes) publish(bundlePath, data.bundleBytes);
  publish(reportPath, data.reportBytes);
  publish(summary, renderSummary(data.report));
  process.stdout.write(JSON.stringify({ overall_result: data.report.overall_result, report: reportPath,
    input_bundle: data.bundle ? bundlePath : null, summary }) + "\n");
}

const [repo, manifest, output, ...upstream] = process.argv.slice(2);
if (!repo || !manifest || !output) {
  process.stderr.write("用法：npx tsx .sandcastle/at18-report.mts <仓库根目录> <本票仓外清单> <仓外新输出目录> [上游仓外清单…]\n");
  process.exitCode = 2;
} else {
  try { await run(repo, manifest, output, upstream); }
  catch (error) {
    if (!(error instanceof At18BootstrapError)) throw error;
    process.stdout.write(JSON.stringify({ status: "BLOCKED", diagnostics: [{
      code: error.code, message: error.message, ...(error.path === undefined ? {} : { path: error.path }),
    }] }) + "\n");
    process.exitCode = 1;
  }
}
