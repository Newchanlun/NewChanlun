#!/usr/bin/env -S npx tsx
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { lstatSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { gitEnvironment } from "./git-environment.ts";
import {
  At18BootstrapError, At18DerivationError, deriveJson, generateAt18, observationsSchema,
  readOwnManifest, renderSummary, type At18Source,
} from "./at18-report.ts";

function run(repo: string, manifestPath: string, observationsPath: string, outputDir: string) {
  const root = realpathSync(repo);
  const inside = (path: string) => {
    const local = relative(root, path);
    return local === "" || (local !== ".." && !local.startsWith(`..${sep}`));
  };
  const git = (...args: string[]) => execFileSync("git", ["--no-replace-objects", "-C", root, ...args], {
    stdio: ["ignore", "pipe", "pipe"], env: gitEnvironment(), maxBuffer: 64 * 1024 * 1024,
  });
  const source: At18Source = {
    readExternal(path) {
      if (inside(path) || realpathSync(path) !== path || !lstatSync(path).isFile()) throw new Error("不是仓外普通文件。");
      return readFileSync(path);
    },
    readBlob(commit, path) {
      return git("cat-file", "blob", `${commit}:${path}`);
    },
    isAncestor(commit, head) {
      try { git("merge-base", "--is-ancestor", commit, head); return true; }
      catch { return false; }
    },
  };

  const manifest = readOwnManifest(source, manifestPath);
  let observations;
  try { observations = deriveJson(readFileSync(observationsPath), observationsSchema); }
  catch (error) {
    throw new At18BootstrapError(error instanceof At18DerivationError && error.check_id === "JCS_CANONICALIZE"
      ? "CONTENT_NOT_CANONICAL" : "FIXED_ITEM_UNAVAILABLE", "采集观察不可读或不合型：" +
      (error instanceof Error ? error.message : String(error)));
  }

  let originMain: string | null = null;
  try { originMain = git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}").toString("utf8").trim(); }
  catch { /* 不用 HEAD 或候选分支冒充主线。 */ }

  const directory = resolve(outputDir);
  const inputBundlePath = join(directory, "at18-input-bundle.json");
  const names = [inputBundlePath, join(directory, "at18-report.json"), join(directory, "summary.md")];
  try {
    if (realpathSync(directory) !== directory || inside(directory) || !lstatSync(directory).isDirectory()) {
      throw new Error("输出目录须为仓外实际目录，不能经符号链接。");
    }
    if (names.some(path => lstatSync(path, { throwIfNoEntry: false }))) throw new Error("输出目录已有 AT-18 产物，请使用新目录。");
  } catch (error) {
    throw new At18BootstrapError("OUTPUT_WRITE_FAILED", error instanceof Error ? error.message : String(error));
  }

  const output = generateAt18({
    manifest, observations, source, originMain, generatedAt: new Date().toISOString(), inputBundlePath,
  });
  const documents = [output.inputBundleBytes, output.reportBytes, renderSummary(output.report)];
  const staged: { temporary: string; target: string }[] = [];
  const published: string[] = [];
  try {
    for (const [index, document] of documents.entries()) {
      if (document === null) continue;
      const target = names[index];
      const temporary = `${target}.${randomUUID()}.tmp`;
      staged.push({ temporary, target });
      writeFileSync(temporary, document, { flag: "wx", mode: 0o600 });
    }
    for (const { temporary, target } of staged) {
      renameSync(temporary, target);
      published.push(target);
    }
  } catch (error) {
    for (const path of published.reverse()) rmSync(path, { force: true });
    throw new At18BootstrapError("OUTPUT_WRITE_FAILED", error instanceof Error ? error.message : String(error));
  } finally {
    for (const { temporary } of staged) rmSync(temporary, { force: true });
  }

  process.stdout.write(`${JSON.stringify({
    overall_result: output.report.overall_result,
    report: names[1], input_bundle: output.inputBundle ? inputBundlePath : null, summary: names[2],
  })}\n`);
}

const [repo, manifest, observations, output, ...extra] = process.argv.slice(2);
if (!repo || !observations || !output || extra.length) {
  process.stderr.write("用法：npx tsx .sandcastle/at18-report.mts <仓库根目录> <仓外清单> <观察 JSON> <仓外新输出目录>\n");
  process.exitCode = 2;
} else {
  try {
    if (!manifest) throw new At18BootstrapError("MANIFEST_UNREADABLE", "未提供自身交付 manifest。");
    run(repo, manifest, observations, output);
  } catch (error) {
    if (!(error instanceof At18BootstrapError || error instanceof At18DerivationError)) throw error;
    const code = error instanceof At18BootstrapError ? error.code : "CONTENT_NOT_CANONICAL";
    process.stdout.write(`${JSON.stringify({ status: "BLOCKED", diagnostics: [{ code, message: error.message }] }, null, 2)}\n`);
    process.exitCode = 1;
  }
}
