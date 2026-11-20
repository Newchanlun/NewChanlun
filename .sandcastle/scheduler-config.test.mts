import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync, mkdirSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFile, execFileSync, spawnSync } from "node:child_process";
import { promisify } from "node:util";
import { API } from "typescript/unstable/sync";
import * as ts from "typescript/unstable/ast";
import {
  configPath,
  readSchedulerConfig,
  SCHEDULER_KEYS,
  schedulerEnvName,
  type SchedulerKey,
  type SchedulerValues,
} from "./scheduler-config.mts";

const execFileAsync = promisify(execFile);
const REPO_ROOT = fileURLToPath(new URL("../", import.meta.url));
const TSX_LOADER = pathToFileURL(createRequire(import.meta.url).resolve("tsx")).href;

const expected: SchedulerValues = {
  childKillGraceMs: 1000, childExitPollMs: 25, childExitWaitMs: 3000,
  healthProcessWaitMs: 15000, healthProcessPollSeconds: 1, healthHttpTimeoutMs: 5000,
  adrLockMaxWaits: 600, adrLockPollMs: 100,
  dockerCliTimeoutMs: 60000, dockerModelHttpTimeoutMs: 60000, dockerModelProcessTimeoutMs: 75000,
  frontierQueryLimit: 20, backlogQueryLimit: 1000,
  mainModel: "gpt-6.1-sol", opusModel: "claude-opus-5-5", workerEffort: "medium", childEffort: "xhigh",
  mainMaxIterations: 3, mainMaxTickets: 1, implementerIdleSeconds: 1800,
  worktreeMaxAttempts: 2, worktreeRetryDelayMs: 5000,
  swarmMaxIterations: 3, swarmMaxParallel: 4,
  childIdleSeconds: 600, childTimeoutSeconds: 3600, decisionMaps: [1323, 1340],
  decisionMaxConcurrent: 3, decisionLoopMs: 600000, decisionMaxRounds: 3,
  decisionMaxAttempts: 6, decisionTimeoutMs: 1800000,
  decisionBackoffBaseMs: 20000, decisionBackoffCapMs: 300000,
  claimPollSeconds: 60, claimRollbackMs: 900000,
  wayfinderStaleMs: 600000, claimStaleMs: 172800000, diskMinGiB: 100,
};
const original = JSON.parse(readFileSync(configPath, "utf8"));

function fixture(fn: (path: string) => void) {
  const dir = mkdtempSync(join(tmpdir(), "scheduler1606-"));
  try { fn(join(dir, "config.json")); } finally { rmSync(dir, { recursive: true, force: true }); }
}

async function asyncFixture(fn: (dir: string) => Promise<void>) {
  const dir = mkdtempSync(join(tmpdir(), "scheduler1606-"));
  try { await fn(dir); } finally { rmSync(dir, { recursive: true, force: true }); }
}

test("版本1完整值保持集成基线 main@3a01bed557，来源完整且有效值冻结", () => {
  const config = readSchedulerConfig(configPath, {});
  assert.equal(config.revision, 1); assert.equal(config.ticket, 1606);
  assert.deepEqual(config.values, expected);
  assert.deepEqual([...SCHEDULER_KEYS].sort(), Object.keys(config.values).sort());
  assert.equal(Object.isFrozen(config.values), true);
  for (const key of SCHEDULER_KEYS) assert.match(config.origins[key]!, /^record:1 /);
});

test("文件、JSON、逐字段、逐来源缺失均拒绝；不回退旧常量", () => fixture(path => {
  assert.throws(() => readSchedulerConfig(path, {}), /无法读取JSON/);
  writeFileSync(path, "{");
  assert.throws(() => readSchedulerConfig(path, {}), /无法读取JSON/);
  for (const section of ["values", "sources"]) for (const key of SCHEDULER_KEYS) {
    const record = structuredClone(original); delete record[section][key];
    writeFileSync(path, JSON.stringify(record));
    assert.throws(() => readSchedulerConfig(path, {}), new RegExp(section + "\\." + key));
  }
}));

test("非法类型、边界、跨字段关系和未知字段均拒绝", () => fixture(path => {
  for (const [key, value] of [
    ["mainModel", "bad model"], ["opusModel", "gpt-6.1-sol"], ["workerEffort", "max"], ["childEffort", ""],
    ["swarmMaxParallel", 0], ["mainMaxTickets", 1.5], ["decisionMaps", []],
    ["decisionMaxAttempts", 4], ["childTimeoutSeconds", 43201],
    ["worktreeRetryDelayMs", 4999], ["claimPollSeconds", -1],
    ["decisionBackoffBaseMs", 300001], ["unknown", 1],
  ] as const) {
    const record = structuredClone(original); record.values[key] = value;
    writeFileSync(path, JSON.stringify(record));
    assert.throws(() => readSchedulerConfig(path, {}), /配置 #1606/);
  }
}));

test("记录结构、版本、来源和整数边界保持严格拒绝", () => fixture(path => {
  for (const raw of [null, [], {}, { ...original, schemaVersion: "sandcastle-scheduler/2" },
    { ...original, revision: 1.5 }, { ...original, ticket: 0 }, { ...original, extra: true },
    { ...original, values: null }, { ...original, sources: [] },
    { ...original, sources: { ...original.sources, mainModel: "" } },
    { ...original, sources: { ...original.sources, mainModel: 1 } }]) {
    writeFileSync(path, JSON.stringify(raw));
    assert.throws(() => readSchedulerConfig(path, {}), /配置 #1606/);
  }
  for (const value of [0, -1, 0.5, Number.MAX_SAFE_INTEGER + 1, "1", null]) {
    const record = structuredClone(original); record.values.childKillGraceMs = value;
    writeFileSync(path, JSON.stringify(record));
    assert.throws(() => readSchedulerConfig(path, {}), /values.childKillGraceMs/);
  }
  const record = structuredClone(original);
  record.values.claimPollSeconds = 0.5; record.values.diskMinGiB = 0.5;
  writeFileSync(path, JSON.stringify(record));
  assert.equal(readSchedulerConfig(path, {}).values.claimPollSeconds, 0.5);
}));

test("全部环境覆盖可追溯；旧env名称保留；非法覆盖拒绝且不回显值", () => {
  const env: NodeJS.ProcessEnv = {};
  for (const key of SCHEDULER_KEYS) {
    const value = expected[key];
    env[schedulerEnvName(key)] = Array.isArray(value) ? JSON.stringify(value) : String(value);
  }
  const config = readSchedulerConfig(configPath, env);
  assert.deepEqual(config.values, expected);
  for (const key of SCHEDULER_KEYS) assert.equal(config.origins[key], "env:" + schedulerEnvName(key));
  assert.equal(readSchedulerConfig(configPath, { CLAIM_LOOP_POLL_SECONDS: "120", HEALTH_DISK_MIN_GIB: "148" }).values.claimPollSeconds, 120);
  assert.equal(readSchedulerConfig(configPath, { HEALTH_DISK_MIN_GIB: "148" }).values.diskMinGiB, 148);
  for (const key of ["CLAIM_LOOP_POLL_SECONDS", "SANDCASTLE_MAIN_MODEL", "SANDCASTLE_DECISION_MAPS"]) {
    assert.throws(() => readSchedulerConfig(configPath, { [key]: "secret invalid sentinel" }),
      (error: Error) => !error.message.includes("secret invalid sentinel"));
  }
});

test("各入口绑定集中记录；启动日志含值和来源但不含无关secret", () => {
  const files = {
    "docker-isolation.mts": ["dockerCliTimeoutMs"],
    "swarm-route.mts": ["dockerModelHttpTimeoutMs", "dockerModelProcessTimeoutMs"],
    "main.mts": ["frontierQueryLimit", "backlogQueryLimit", "workerEffort", "mainMaxIterations", "mainMaxTickets", "implementerIdleSeconds", "worktreeMaxAttempts", "worktreeRetryDelayMs"],
    "main-swarm.mts": ["swarmMaxIterations", "swarmMaxParallel"],
    "codex-child.ts": ["opusModel", "childKillGraceMs", "childExitPollMs", "childExitWaitMs", "childEffort", "childIdleSeconds", "childTimeoutSeconds"],
    "codex-route.mts": ["workerEffort"],
    "decision-claimer.mts": ["opusModel", "adrLockMaxWaits", "adrLockPollMs", "decisionMaps", "decisionMaxConcurrent", "decisionLoopMs", "decisionMaxRounds", "decisionMaxAttempts", "decisionTimeoutMs", "decisionBackoffBaseMs", "decisionBackoffCapMs"],
    "claim-loop.mts": ["claimPollSeconds", "claimRollbackMs", "frontierQueryLimit"],
    "health-monitor.mts": ["healthProcessWaitMs", "healthProcessPollSeconds", "healthHttpTimeoutMs", "wayfinderStaleMs", "claimStaleMs", "diskMinGiB"],
  };
  assert.match(readFileSync(new URL("./main-model.mts", import.meta.url), "utf8"),
    /MAIN_MODEL = useScheduler\("main-model", \["mainModel"\]\)\.mainModel/);
  for (const [file, keys] of Object.entries(files)) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    for (const key of keys) assert.match(source, new RegExp("scheduler\\." + key));
  }
  const result = spawnSync(process.execPath, ["--import", TSX_LOADER, "--input-type=module", "-e",
    'import {useScheduler} from "./.sandcastle/scheduler-config.mts"; useScheduler("fixture",["mainModel","claimPollSeconds"]);'],
    { encoding: "utf8", env: { ...process.env, CLAIM_LOOP_POLL_SECONDS: "71", SECRET_TEST: "do-not-log-secret" } });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /mainModel="gpt-6.1-sol" source=record:1/);
  assert.match(result.stderr, /claimPollSeconds=71 source=env:CLAIM_LOOP_POLL_SECONDS/);
  assert.doesNotMatch(result.stdout + result.stderr, /do-not-log-secret/);
});

// ═════════════════════════════════════════════════════════════════════════════
// 层 1（主体）：全字段哨兵行为守卫 —— 每个配置字段改成互不相同的非默认哨兵值，
// 断言每个消费入口的可观察出口生效该哨兵值。字段清单由 SCHEDULER_KEYS 导出。
// ═════════════════════════════════════════════════════════════════════════════

const SENTINELS: SchedulerValues = {
  mainModel: "gpt-sentinel-99", opusModel: "claude-opus-sentinel-98", workerEffort: "low", childEffort: "high",
  mainMaxIterations: 7, mainMaxTickets: 8, implementerIdleSeconds: 1811,
  worktreeMaxAttempts: 9, worktreeRetryDelayMs: 5113,
  swarmMaxIterations: 11, swarmMaxParallel: 12,
  childIdleSeconds: 613, childTimeoutSeconds: 3617, decisionMaps: [9101, 9102],
  decisionMaxConcurrent: 13, decisionLoopMs: 601103, decisionMaxRounds: 14,
  decisionMaxAttempts: 15, decisionTimeoutMs: 1801109,
  decisionBackoffBaseMs: 21107, decisionBackoffCapMs: 311111,
  claimPollSeconds: 73, claimRollbackMs: 901117,
  wayfinderStaleMs: 601121, claimStaleMs: 172801123, diskMinGiB: 137,
  childKillGraceMs: 1129, childExitPollMs: 43, childExitWaitMs: 3137,
  healthProcessWaitMs: 53, healthProcessPollSeconds: 16, healthHttpTimeoutMs: 5147,
  adrLockMaxWaits: 17, adrLockPollMs: 149,
  dockerCliTimeoutMs: 61151, dockerModelHttpTimeoutMs: 61153, dockerModelProcessTimeoutMs: 76157,
  frontierQueryLimit: 29, backlogQueryLimit: 1031,
};

function cleanSchedulerEnv(configFile: string, extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env };
  for (const key of SCHEDULER_KEYS) delete env[schedulerEnvName(key)];
  for (const k of ["SANDCASTLE_CONFIG_FILE", "SANDCASTLE_REVIEW_ONLY", "SANDCASTLE_SWARM_MERGE_MANIFEST", "SANDCASTLE_SWARM_PLAN", "SANDCASTLE_DOCKER_ACCEPTANCE_ROW"]) delete env[k];
  return { ...env, SANDCASTLE_CONFIG_FILE: configFile, ...extra };
}

function writeSingleFieldSentinelConfig(dir: string, key: SchedulerKey): string {
  const record = structuredClone(original);
  record.values[key] = SENTINELS[key];
  const file = join(dir, `sentinel-${key}.json`);
  writeFileSync(file, JSON.stringify(record));
  return file;
}

function assertRecordLog(stderr: string, component: string, key: SchedulerKey, value: unknown): void {
  const line = `[配置 #1606] ${component}.${key}=${JSON.stringify(value)} source=record:1 `;
  assert.ok(stderr.includes(line), `缺少期望启动日志：\n  期望: ${line}\n  实际:\n${stderr}`);
}

const parseLastJson = (stdout: string) => JSON.parse(stdout.trim().split("\n").at(-1)!);

async function runScript(cmd: string, args: string[], env: NodeJS.ProcessEnv, cwd = REPO_ROOT) {
  try {
    const { stdout, stderr } = await execFileAsync(cmd, args, { cwd, env, encoding: "utf8", timeout: 15000 });
    return { stdout, stderr, exitCode: 0 };
  } catch (error) {
    const e = error as { stdout?: string; stderr?: string; code?: number };
    return { stdout: e.stdout ?? "", stderr: e.stderr ?? "", exitCode: typeof e.code === "number" ? e.code : 1 };
  }
}

const runNodeEval = (code: string, env: NodeJS.ProcessEnv, cwd = REPO_ROOT) =>
  runScript(process.execPath, ["--import", TSX_LOADER, "--input-type=module", "-e", code], env, cwd);

async function probeMainStartup(env: NodeJS.ProcessEnv, dir: string, key: SchedulerKey, value: unknown, component = "main") {
  const isolated = join(dir, `main-cwd-${key}`);
  mkdirSync(isolated, { recursive: true });
  const r = await runScript(process.execPath, ["--import", TSX_LOADER, resolve(REPO_ROOT, ".sandcastle/main.mts")], { ...env, TMPDIR: isolated }, isolated);
  assert.notEqual(r.exitCode, 0);
  assertRecordLog(r.stderr, component, key, value);
}

async function probeMainSwarmStartup(env: NodeJS.ProcessEnv, key: SchedulerKey, value: unknown) {
  const r = await runScript(process.execPath, ["--import", TSX_LOADER, resolve(REPO_ROOT, ".sandcastle/main-swarm.mts")],
    { ...env, SANDCASTLE_SWARM_MERGE_MANIFEST: "sentinel-a", SANDCASTLE_SWARM_PLAN: "sentinel-b" });
  assert.notEqual(r.exitCode, 0);
  assertRecordLog(r.stderr, "main-swarm", key, value);
}

async function probeClaimLoopDryRun(env: NodeJS.ProcessEnv, dir: string, rollbackFixtureMs?: number) {
  const work = join(dir, "claim-work");
  const bin = join(work, "bin");
  mkdirSync(bin, { recursive: true });
  const calls = join(work, "calls");
  writeFileSync(calls, "");
  writeFileSync(join(bin, "pgrep"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
  writeFileSync(join(bin, "gh"), '#!/bin/sh\necho "$*" >> "$CALLS"\ncase "$1 $2" in\n"issue list") echo \'[{"number":1606,"assignees":[]}]\';;\n"api repos/"*) echo 0;;\n*) exit 98;;\nesac\n', { mode: 0o755 });
  if (rollbackFixtureMs !== undefined) {
    mkdirSync(join(work, ".sandcastle/logs"), { recursive: true });
    const now = Date.now();
    writeFileSync(join(work, ".sandcastle/logs/workers.jsonl"),
      JSON.stringify({ ts: new Date(now - (rollbackFixtureMs - 10_000)).toISOString(), ticket: 9001, branch: "sandcastle/issue-9001", phase: "claim", status: "claimed" }) + "\n"
      + JSON.stringify({ ts: new Date(now - (rollbackFixtureMs + 10_000)).toISOString(), ticket: 9002, branch: "sandcastle/issue-9002", phase: "claim", status: "claimed" }) + "\n");
  }
  // 在内存里把宿主 drain 状态文件视为未冻结（不修改磁盘上的任何宿主状态），使 --dry-run 真实走到回滚与 frontier 查询。
  const preload = join(work, "open-drain.mjs");
  writeFileSync(preload, `
    import fs from "node:fs";
    import { syncBuiltinESMExports } from "node:module";
    const orig = fs.readFileSync;
    fs.readFileSync = function (p, ...rest) {
      if (String(p).endsWith("/newchanlun-legacy-drain/state.json")) {
        throw Object.assign(new Error("ENOENT"), { code: "ENOENT" });
      }
      return orig.call(this, p, ...rest);
    };
    syncBuiltinESMExports();
  `);
  const r = await runScript(
    process.execPath,
    ["--import", TSX_LOADER, "--import", preload, resolve(REPO_ROOT, ".sandcastle/claim-loop.mts"), "--once", "--dry-run"],
    { ...env, PATH: bin + ":" + (env.PATH ?? ""), CALLS: calls, HOME: work },
    work,
  );
  assert.equal(r.exitCode, 0, r.stderr);
  return { stdout: r.stdout, stderr: r.stderr, ghCalls: readFileSync(calls, "utf8") };
}

function makeFakeCodexCheckout(dir: string) {
  const checkout = join(dir, "worker"), controller = join(dir, "controller"), bin = join(dir, "bin"), home = join(dir, "home");
  for (const p of [checkout, controller, bin, join(home, ".codex")]) mkdirSync(p, { recursive: true });
  const git = (...args: string[]) => execFileSync("git", ["-C", checkout, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  git("init", "-b", "codex/1606-sentinel"); git("config", "user.name", "Sentinel"); git("config", "user.email", "sentinel@example.invalid");
  writeFileSync(join(checkout, "a.txt"), "ok\n"); git("add", "."); git("commit", "-qm", "init");
  const promptFile = join(dir, "prompt.md"); writeFileSync(promptFile, "只读哨兵探针。\n");
  const sid = "12345678-1234-1234-1234-123456789abc";
  const good = { status: "completed", summary: "ok", findings: [], validation: ["ok"] };
  const fakeCodex = join(bin, "codex");
  writeFileSync(fakeCodex, `#!${process.execPath}\nconst fs=require("node:fs"),path=require("node:path");\n`
    + `const p=path.join(process.env.CODEX_HOME,"sessions","2026","09","14");fs.mkdirSync(p,{recursive:true});\n`
    + `fs.writeFileSync(path.join(p,"rollout-${sid}.jsonl"),"{}\\n");\n`
    + `const emit=(v)=>process.stdout.write(JSON.stringify(v)+"\\n");\n`
    + `process.stdin.resume();process.stdin.on("end",()=>{emit({type:"thread.started",thread_id:${JSON.stringify(sid)}});`
    + `emit({type:"item.completed",item:{type:"agent_message",text:${JSON.stringify(JSON.stringify(good))}}});emit({type:"turn.completed"});});\n`);
  chmodSync(fakeCodex, 0o700);
  return { checkout, controller, promptFile, outputDir: join(dir, "out"), expectedHead: git("rev-parse", "HEAD"), bin, home };
}

async function probeChildTimeoutField(field: "childIdleSeconds" | "childTimeoutSeconds", sec: number, env: NodeJS.ProcessEnv, dir: string) {
  const explicitKey = field === "childIdleSeconds" ? "idleTimeoutSeconds" : "timeoutSeconds";
  const cli = await runScript(process.execPath, [
    "--import", TSX_LOADER, resolve(REPO_ROOT, ".sandcastle/codex-child.mts"),
    "--ticket", "1606", "--parent-thread-id", "sentinel-parent", "--manager-agent-id", "sentinel-mgr",
    "--expected-head", "a".repeat(40), "--checkout", join(dir, "absent"),
    "--output-dir", join(dir, "unused-out"), "--prompt-file", join(dir, "unused-prompt"),
  ], env);
  assert.equal(cli.exitCode, 1);
  assertRecordLog(cli.stderr, "codex-child", field, sec);
  assert.doesNotMatch(cli.stderr, new RegExp(`source=explicit:${explicitKey}`));

  const fx = makeFakeCodexCheckout(dir);
  const r = await runNodeEval(`
    const delays = [];
    const orig = globalThis.setTimeout;
    globalThis.setTimeout = (fn, ms, ...rest) => { delays.push(ms); return orig(fn, ms, ...rest); };
    const { runCodexChild } = await import("./.sandcastle/codex-child.ts");
    const rec = await runCodexChild({
      ticket: 1606, parentThreadId: "p", managerAgentId: "m",
      checkout: ${JSON.stringify(fx.checkout)}, controllerCheckout: ${JSON.stringify(fx.controller)},
      expectedHead: ${JSON.stringify(fx.expectedHead)}, mode: "review",
      promptFile: ${JSON.stringify(fx.promptFile)}, outputDir: ${JSON.stringify(fx.outputDir)},
    }, { env: { ...process.env, PATH: ${JSON.stringify(fx.bin)} + ":" + process.env.PATH, HOME: ${JSON.stringify(fx.home)}, CODEX_HOME: ${JSON.stringify(join(fx.home, ".codex"))}, CLIPROXY_LOCAL_KEY: "fixture" } });
    console.log(JSON.stringify({ status: rec.status, delays }));
  `, env);
  assert.equal(r.exitCode, 0, r.stderr);
  const out = parseLastJson(r.stdout);
  assert.equal(out.status, "completed");
  assert.ok(out.delays.includes(sec * 1000), `实际 setTimeout=${JSON.stringify(out.delays)}`);
  assertRecordLog(r.stderr, "codex-child", field, sec);
  assert.doesNotMatch(r.stderr, new RegExp(`source=explicit:${explicitKey}`));
}

type SentinelProbe = (ctx: { key: SchedulerKey; value: SchedulerValues[SchedulerKey]; env: NodeJS.ProcessEnv; dir: string }) => Promise<void>;

const SENTINEL_PROBES: Record<SchedulerKey, SentinelProbe> = {
  async mainModel({ value, env, dir }) {
    const m = value as string;
    const r = await runNodeEval(`
      import { MAIN_MODEL, SUPPORTED_MAIN_MODELS } from "./.sandcastle/main-model.mts";
      import { codexWorker } from "./.sandcastle/codex-route.mts";
      import { MODEL, ALLOWED_MODELS, boundedCodex } from "./.sandcastle/codex-child.ts";
      import { MODEL_MAIN, MODEL_REVIEW, initialState, reviewerModel } from "./.sandcastle/decision-claimer.mts";
      import { DOCKER_MODEL_PROBE, swarmAgent } from "./.sandcastle/swarm-route.mts";
      const routeCmd = codexWorker().buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command;
      const childCmd = (await boundedCodex("review", "/tmp/s.json")).buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command;
      const swarmCmd = swarmAgent().buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command;
      console.log(JSON.stringify({
        MAIN_MODEL, SUPPORTED_MAIN_MODELS, MODEL, ALLOWED_MODELS, MODEL_MAIN, MODEL_REVIEW,
        drafter: initialState("T").drafterModel, revFromClaude: reviewerModel("x", "claude-x"),
        routeCmd, childCmd, swarmCmd, DOCKER_MODEL_PROBE,
      }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.MAIN_MODEL, m); assert.deepEqual(out.SUPPORTED_MAIN_MODELS, [m]);
    assert.equal(out.MODEL, m); assert.ok(out.ALLOWED_MODELS.includes(m));
    assert.equal(out.MODEL_MAIN, m); assert.equal(out.MODEL_REVIEW, m);
    assert.equal(out.drafter, m); assert.equal(out.revFromClaude, m);
    for (const cmd of [out.routeCmd, out.childCmd, out.swarmCmd]) assert.ok(cmd.includes(` -m '${m}'`), cmd);
    assert.ok(out.DOCKER_MODEL_PROBE.includes(`model: "${m}"`));
    assertRecordLog(r.stderr, "main-model", "mainModel", m);
    await probeMainStartup(env, dir, "mainModel", m, "main-model");
  },

  async opusModel({ value, env }) {
    const m = value as string;
    const r = await runNodeEval(`
      import { ALLOWED_MODELS, assertRoute } from "./.sandcastle/codex-child.ts";
      import { MODEL_OPUS, MODEL_DRAFTER, reviewerModel } from "./.sandcastle/decision-claimer.mts";
      assertRoute(${JSON.stringify(m)});
      console.log(JSON.stringify({ ALLOWED_MODELS, MODEL_OPUS, MODEL_DRAFTER, revFromGpt: reviewerModel("x", "gpt-x") }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.ok(out.ALLOWED_MODELS.includes(m)); assert.equal(out.MODEL_OPUS, m);
    assert.equal(out.MODEL_DRAFTER, m); assert.equal(out.revFromGpt, m);
    assertRecordLog(r.stderr, "codex-child", "opusModel", m);
    assertRecordLog(r.stderr, "decision-claimer", "opusModel", m);
  },

  async workerEffort({ value, env, dir }) {
    const e = value as string;
    const r = await runNodeEval(`
      import { codexWorker } from "./.sandcastle/codex-route.mts";
      import { swarmAgent } from "./.sandcastle/swarm-route.mts";
      console.log(JSON.stringify({
        routeCmd: codexWorker().buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command,
        swarmCmd: swarmAgent().buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command,
      }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.ok(out.routeCmd.includes(`model_reasoning_effort="${e}"`));
    assert.ok(out.swarmCmd.includes(`model_reasoning_effort="${e}"`));
    assertRecordLog(r.stderr, "codex-route", "workerEffort", e);
    await probeMainStartup(env, dir, "workerEffort", e);
  },

  async childEffort({ value, env }) {
    const e = value as string;
    const r = await runNodeEval(`
      import { EFFORT, boundedCodex } from "./.sandcastle/codex-child.ts";
      const cmd = (await boundedCodex("review", "/tmp/s.json")).buildPrintCommand({ prompt: "x", dangerouslySkipPermissions: false }).command;
      console.log(JSON.stringify({ EFFORT, cmd }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.EFFORT, e);
    assert.ok(out.cmd.includes(`model_reasoning_effort="${e}"`));
    assertRecordLog(r.stderr, "codex-child", "childEffort", e);
  },

  mainMaxIterations: ({ value, env, dir }) => probeMainStartup(env, dir, "mainMaxIterations", value),
  mainMaxTickets: ({ value, env, dir }) => probeMainStartup(env, dir, "mainMaxTickets", value),
  implementerIdleSeconds: ({ value, env, dir }) => probeMainStartup(env, dir, "implementerIdleSeconds", value),
  worktreeMaxAttempts: ({ value, env, dir }) => probeMainStartup(env, dir, "worktreeMaxAttempts", value),
  worktreeRetryDelayMs: ({ value, env, dir }) => probeMainStartup(env, dir, "worktreeRetryDelayMs", value),
  backlogQueryLimit: ({ value, env, dir }) => probeMainStartup(env, dir, "backlogQueryLimit", value),
  swarmMaxIterations: ({ value, env }) => probeMainSwarmStartup(env, "swarmMaxIterations", value),
  swarmMaxParallel: ({ value, env }) => probeMainSwarmStartup(env, "swarmMaxParallel", value),

  async frontierQueryLimit({ value, env, dir }) {
    const claim = await probeClaimLoopDryRun(env, dir);
    assert.match(claim.ghCalls, new RegExp(`--limit ${value}\\b`));
    assertRecordLog(claim.stderr, "claim-loop", "frontierQueryLimit", value);
    await probeMainStartup(env, dir, "frontierQueryLimit", value);
  },

  childIdleSeconds: ({ value, env, dir }) => probeChildTimeoutField("childIdleSeconds", value as number, env, dir),
  childTimeoutSeconds: ({ value, env, dir }) => probeChildTimeoutField("childTimeoutSeconds", value as number, env, dir),

  async childKillGraceMs({ value, env, dir }) {
    const ms = value as number;
    const r = await runNodeEval(`
      const delays = [];
      const orig = globalThis.setTimeout;
      globalThis.setTimeout = (fn, d, ...rest) => { delays.push(d); return orig(fn, d, ...rest); };
      const { supervisedNoSandbox } = await import("./.sandcastle/codex-child.ts");
      const ac = new AbortController();
      const handle = await supervisedNoSandbox(${JSON.stringify(dir)}, {
        signal: ac.signal, env: { PATH: process.env.PATH ?? "" },
        stdoutFile: ${JSON.stringify(join(dir, "out.log"))}, stderrFile: ${JSON.stringify(join(dir, "err.log"))},
        idleTimeoutSeconds: 60, timeoutSeconds: 60,
        onSpawn() { setTimeout(() => ac.abort(), 30); }, onExit() {},
      });
      await handle.exec("sleep 10").catch(() => {}); await handle.close();
      console.log(JSON.stringify({ delays }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.ok(parseLastJson(r.stdout).delays.includes(ms));
    assertRecordLog(r.stderr, "codex-child", "childKillGraceMs", ms);
  },

  async childExitPollMs({ value, env, dir }) {
    const ms = value as number;
    const r = await runNodeEval(`
      const delays = [];
      const origTimeout = globalThis.setTimeout;
      globalThis.setTimeout = (fn, d, ...rest) => { delays.push(d); return origTimeout(fn, d, ...rest); };
      const origKill = process.kill.bind(process);
      let probes = 0;
      process.kill = (pid, sig) => (pid < 0 && sig === 0 && probes++ === 0) ? true : origKill(pid, sig);
      const { supervisedNoSandbox } = await import("./.sandcastle/codex-child.ts");
      const handle = await supervisedNoSandbox(${JSON.stringify(dir)}, {
        env: { PATH: process.env.PATH ?? "" },
        stdoutFile: ${JSON.stringify(join(dir, "out.log"))}, stderrFile: ${JSON.stringify(join(dir, "err.log"))},
        idleTimeoutSeconds: 60, timeoutSeconds: 60, onSpawn() {}, onExit() {},
      });
      await handle.exec("true"); await handle.close();
      console.log(JSON.stringify({ delays }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.ok(parseLastJson(r.stdout).delays.includes(ms));
    assertRecordLog(r.stderr, "codex-child", "childExitPollMs", ms);
  },

  async childExitWaitMs({ value, env, dir }) {
    const ms = value as number;
    const r = await runNodeEval(`
      const origTimeout = globalThis.setTimeout;
      globalThis.setTimeout = (fn, d, ...rest) => origTimeout(fn, d === 25 ? 0 : d, ...rest);
      let now = 1_700_000_000_000, probes = 0;
      Date.now = () => now;
      const origKill = process.kill.bind(process);
      process.kill = (pid, sig) => {
        if (pid < 0 && sig === 0) {
          probes++;
          if (probes > 4) throw Object.assign(new Error("ESRCH"), { code: "ESRCH" });
          now += probes === 1 ? ${ms - 1} : 1;
          return true;
        }
        return origKill(pid, sig);
      };
      const { supervisedNoSandbox } = await import("./.sandcastle/codex-child.ts");
      const handle = await supervisedNoSandbox(${JSON.stringify(dir)}, {
        env: { PATH: process.env.PATH ?? "" },
        stdoutFile: ${JSON.stringify(join(dir, "out.log"))}, stderrFile: ${JSON.stringify(join(dir, "err.log"))},
        idleTimeoutSeconds: 60, timeoutSeconds: 60, onSpawn() {}, onExit() {},
      });
      let message = "";
      try { await handle.exec("true"); } catch (e) { message = e.message; }
      await handle.close();
      console.log(JSON.stringify({ message, probes }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.match(out.message, /工蜂进程组退出未确认/);
    assert.equal(out.probes, 2);
    assertRecordLog(r.stderr, "codex-child", "childExitWaitMs", ms);
  },

  async decisionMaps({ value, env }) {
    const r = await runNodeEval(`import { DEFAULT_MAPS, parseArgs } from "./.sandcastle/decision-claimer.mts"; console.log(JSON.stringify({ DEFAULT_MAPS, parsed: parseArgs([]).maps }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.deepEqual(out.DEFAULT_MAPS, value); assert.deepEqual(out.parsed, value);
    assertRecordLog(r.stderr, "decision-claimer", "decisionMaps", value);
  },

  async decisionMaxConcurrent({ value, env }) {
    const r = await runNodeEval(`import { MAX_CONCURRENT, parseArgs } from "./.sandcastle/decision-claimer.mts"; console.log(JSON.stringify({ MAX_CONCURRENT, def: parseArgs([]).concurrency, capped: parseArgs(["--concurrency", "999"]).concurrency }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.MAX_CONCURRENT, value); assert.equal(out.def, value); assert.equal(out.capped, value);
    assertRecordLog(r.stderr, "decision-claimer", "decisionMaxConcurrent", value);
  },

  async decisionLoopMs({ value, env }) {
    const r = await runNodeEval(`import { LOOP_INTERVAL_MS } from "./.sandcastle/decision-claimer.mts"; console.log(JSON.stringify({ LOOP_INTERVAL_MS }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).LOOP_INTERVAL_MS, value);
    assertRecordLog(r.stderr, "decision-claimer", "decisionLoopMs", value);
  },

  async decisionMaxRounds({ value, env }) {
    const n = value as number;
    const r = await runNodeEval(`
      import { MAX_ROUNDS, initialState, nextAfterReview } from "./.sandcastle/decision-claimer.mts";
      const review = { verdict: "BLOCK", items: [{ rule: "R2", verdict: "BLOCK", basis: "x" }], problems: [], parseError: false };
      console.log(JSON.stringify({
        MAX_ROUNDS,
        before: nextAfterReview({ ...initialState("T"), attempt: ${n - 1} }, review).phase,
        atMax: nextAfterReview({ ...initialState("T"), attempt: ${n} }, review).phase,
      }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.MAX_ROUNDS, n); assert.equal(out.before, "draft"); assert.equal(out.atMax, "held");
    assertRecordLog(r.stderr, "decision-claimer", "decisionMaxRounds", n);
  },

  async decisionMaxAttempts({ value, env }) {
    const n = value as number;
    const r = await runNodeEval(`
      import { makeClaudeRunner } from "./.sandcastle/decision-claimer.mts";
      let calls = 0;
      const run = makeClaudeRunner({ once: async () => { calls++; return { code: 1, stdout: "", stderr: "429 rate_limit" }; }, sleep: async () => {}, token: () => "fixture" });
      await run({ role: "draft", model: "gpt-6.1-sol", prompt: "x", cwd: "." }).catch(() => {});
      console.log(JSON.stringify({ calls }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).calls, n);
    assertRecordLog(r.stderr, "decision-claimer", "decisionMaxAttempts", n);
  },

  async decisionTimeoutMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`
      import { makeClaudeRunner } from "./.sandcastle/decision-claimer.mts";
      let observed = null;
      const run = makeClaudeRunner({ once: async (_c, _tok, timeoutMs) => { observed = timeoutMs; return { code: 0, stdout: JSON.stringify({ result: "ok" }), stderr: "" }; }, sleep: async () => {}, token: () => "fixture" });
      await run({ role: "draft", model: "gpt-6.1-sol", prompt: "x", cwd: "." });
      console.log(JSON.stringify({ observed }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).observed, ms);
    assertRecordLog(r.stderr, "decision-claimer", "decisionTimeoutMs", ms);
  },

  async decisionBackoffBaseMs({ value, env }) {
    const r = await runNodeEval(`import { backoffMs } from "./.sandcastle/decision-claimer.mts"; console.log(JSON.stringify({ first: backoffMs(1) }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).first, value);
    assertRecordLog(r.stderr, "decision-claimer", "decisionBackoffBaseMs", value);
  },

  async decisionBackoffCapMs({ value, env }) {
    const r = await runNodeEval(`import { backoffMs } from "./.sandcastle/decision-claimer.mts"; console.log(JSON.stringify({ capped: backoffMs(20) }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).capped, value);
    assertRecordLog(r.stderr, "decision-claimer", "decisionBackoffCapMs", value);
  },

  async adrLockMaxWaits({ value, env, dir }) {
    const n = value as number;
    const r = await runNodeEval(`
      import { writeFileSync } from "node:fs"; import { join } from "node:path";
      import { allocateAdr } from "./.sandcastle/decision-claimer.mts";
      writeFileSync(join(${JSON.stringify(dir)}, ".adr-alloc.lock"), String(process.pid));
      const sleeps = []; let err = "";
      try { await allocateAdr("docs/adr/NNNN-sentinel.md", 1606, { adrDir: ${JSON.stringify(dir)}, stateDir: ${JSON.stringify(dir)}, reserve: false, sleep: async (ms) => { sleeps.push(ms); } }); }
      catch (e) { err = e.message; }
      console.log(JSON.stringify({ count: sleeps.length, err }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.count, n); assert.match(out.err, /被占用超时/);
    assertRecordLog(r.stderr, "decision-claimer", "adrLockMaxWaits", n);
  },

  async adrLockPollMs({ value, env, dir }) {
    const ms = value as number;
    const r = await runNodeEval(`
      import { writeFileSync } from "node:fs"; import { join } from "node:path";
      import { allocateAdr } from "./.sandcastle/decision-claimer.mts";
      writeFileSync(join(${JSON.stringify(dir)}, ".adr-alloc.lock"), String(process.pid));
      const sleeps = [];
      try { await allocateAdr("docs/adr/NNNN-sentinel.md", 1606, { adrDir: ${JSON.stringify(dir)}, stateDir: ${JSON.stringify(dir)}, reserve: false, sleep: async (d) => { sleeps.push(d); if (sleeps.length >= 2) throw new Error("stop"); } }); } catch {}
      console.log(JSON.stringify({ sleeps }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.deepEqual(parseLastJson(r.stdout).sleeps, [ms, ms]);
    assertRecordLog(r.stderr, "decision-claimer", "adrLockPollMs", ms);
  },

  async claimPollSeconds({ value, env, dir }) {
    const claim = await probeClaimLoopDryRun(env, dir);
    assert.match(claim.stdout, new RegExp(`poll=${value}s\\b`));
    assertRecordLog(claim.stderr, "claim-loop", "claimPollSeconds", value);
  },

  async claimRollbackMs({ value, env, dir }) {
    const ms = value as number;
    const claim = await probeClaimLoopDryRun(env, dir, ms);
    assert.match(claim.stdout, /#9002/);
    assert.doesNotMatch(claim.stdout, /#9001/);
    assertRecordLog(claim.stderr, "claim-loop", "claimRollbackMs", ms);
  },

  async wayfinderStaleMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`import { WAYFINDER_STALE_MS, judgeFreshness } from "./.sandcastle/health-monitor.mts"; console.log(JSON.stringify({ WAYFINDER_STALE_MS, atEdge: judgeFreshness(0, ${ms}), pastEdge: judgeFreshness(0, ${ms + 1}) }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.WAYFINDER_STALE_MS, ms); assert.equal(out.atEdge, "healthy"); assert.equal(out.pastEdge, "red");
    assertRecordLog(r.stderr, "health-monitor", "wayfinderStaleMs", ms);
  },

  async claimStaleMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`
      import { CLAIM_STALE_MS, findStaleClaims } from "./.sandcastle/health-monitor.mts";
      const ev = [{ ts: new Date(0).toISOString(), ticket: 7, phase: "claim", status: "claimed" }];
      console.log(JSON.stringify({ CLAIM_STALE_MS, atEdge: findStaleClaims(ev, { now: ${ms} }).length, pastEdge: findStaleClaims(ev, { now: ${ms + 1} }).length }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.CLAIM_STALE_MS, ms); assert.equal(out.atEdge, 0); assert.equal(out.pastEdge, 1);
    assertRecordLog(r.stderr, "health-monitor", "claimStaleMs", ms);
  },

  async diskMinGiB({ value, env }) {
    const gib = value as number;
    const r = await runNodeEval(`import { DISK_MIN_GIB, judgeDisk } from "./.sandcastle/health-monitor.mts"; console.log(JSON.stringify({ DISK_MIN_GIB, atEdge: judgeDisk(${gib}), belowEdge: judgeDisk(${gib - 0.1}) }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    const out = parseLastJson(r.stdout);
    assert.equal(out.DISK_MIN_GIB, gib); assert.equal(out.atEdge, "healthy"); assert.equal(out.belowEdge, "red");
    assertRecordLog(r.stderr, "health-monitor", "diskMinGiB", gib);
  },

  async healthProcessWaitMs({ value, env }) {
    const r = await runNodeEval(`import "./.sandcastle/health-monitor.mts";`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assertRecordLog(r.stderr, "health-monitor", "healthProcessWaitMs", value);
  },

  async healthProcessPollSeconds({ value, env }) {
    const r = await runNodeEval(`import "./.sandcastle/health-monitor.mts";`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assertRecordLog(r.stderr, "health-monitor", "healthProcessPollSeconds", value);
  },

  async healthHttpTimeoutMs({ value, env, dir }) {
    const ms = value as number;
    const bin = join(dir, "bin"); mkdirSync(bin, { recursive: true });
    writeFileSync(join(bin, "pgrep"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
    writeFileSync(join(bin, "df"), "#!/bin/sh\necho 'fs 100 0 209715200 0% /'\n", { mode: 0o755 });
    const captured = join(dir, "abort-timeout.json"), preload = join(dir, "spy-abort.mjs");
    writeFileSync(preload, `import { writeFileSync } from "node:fs"; const orig = AbortSignal.timeout.bind(AbortSignal); const seen = []; AbortSignal.timeout = (d) => { seen.push(d); writeFileSync(${JSON.stringify(captured)}, JSON.stringify(seen)); return orig(d); }; globalThis.fetch = async () => { throw new Error("stop"); };`);
    const r = await runScript(
      process.execPath,
      ["--import", TSX_LOADER, "--import", preload, resolve(REPO_ROOT, ".sandcastle/health-monitor.mts"), "--report", join(dir, "report.json")],
      { ...env, PATH: bin + ":" + (env.PATH ?? ""), HEALTH_MAIN_REPO: dir, SANDCASTLE_HOST_REPO: dir, HEALTH_DISK_PATH: dir, HEALTH_CLIPROXY_KEY: "fixture", HEALTH_CLIPROXY_URL: "http://127.0.0.1:1/v1/models" },
    );
    assert.equal(r.exitCode, 0, r.stderr);
    assert.deepEqual(JSON.parse(readFileSync(captured, "utf8")), [ms]);
    assertRecordLog(r.stderr, "health-monitor", "healthHttpTimeoutMs", ms);
  },

  async dockerCliTimeoutMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`
      import cp from "node:child_process"; import { syncBuiltinESMExports } from "node:module";
      const timeouts = [];
      cp.execFileSync = (_cmd, args, opts) => { timeouts.push([args[0], opts.timeout]); if (args[0] === "run") throw Object.assign(new Error("stop"), { signal: "SIGKILL" }); return ""; };
      syncBuiltinESMExports();
      const { probeDockerIsolation } = await import("./.sandcastle/docker-isolation.mts");
      try { probeDockerIsolation("fixture-only"); } catch {}
      console.log(JSON.stringify({ timeouts }));
    `, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.deepEqual(parseLastJson(r.stdout).timeouts, [["run", ms], ["rm", ms]]);
    assertRecordLog(r.stderr, "docker-isolation", "dockerCliTimeoutMs", ms);
  },

  async dockerModelHttpTimeoutMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`import { DOCKER_MODEL_PROBE } from "./.sandcastle/swarm-route.mts"; console.log(JSON.stringify({ DOCKER_MODEL_PROBE }));`, env);
    assert.equal(r.exitCode, 0, r.stderr);
    assert.ok(parseLastJson(r.stdout).DOCKER_MODEL_PROBE.includes(`AbortSignal.timeout(${ms})`));
    assertRecordLog(r.stderr, "swarm-route", "dockerModelHttpTimeoutMs", ms);
  },

  async dockerModelProcessTimeoutMs({ value, env }) {
    const ms = value as number;
    const r = await runNodeEval(`
      import cp from "node:child_process"; import { syncBuiltinESMExports } from "node:module";
      let observed = null;
      cp.execFileSync = (_cmd, _args, opts) => { observed = opts.timeout; return ""; };
      syncBuiltinESMExports();
      const { assertDockerCliProxyReachable } = await import("./.sandcastle/swarm-route.mts");
      assertDockerCliProxyReachable("sha256:" + "a".repeat(64));
      console.log(JSON.stringify({ observed }));
    `, { ...env, CLIPROXY_LOCAL_KEY: "fixture" });
    assert.equal(r.exitCode, 0, r.stderr);
    assert.equal(parseLastJson(r.stdout).observed, ms);
    assertRecordLog(r.stderr, "swarm-route", "dockerModelProcessTimeoutMs", ms);
  },
};

test("#1606 C-29/C-30 全字段哨兵行为守卫：逐字段非默认互异哨兵在所有消费入口真实生效", async () => {
  const schemaKeys = [...SCHEDULER_KEYS];
  assert.deepEqual(Object.keys(SENTINEL_PROBES).sort(), [...schemaKeys].sort(), "新增配置字段缺少哨兵消费断言");
  const seenSentinels = new Set<string>();
  for (const key of schemaKeys) {
    assert.notDeepEqual(SENTINELS[key], expected[key], `${key} 哨兵值不得与默认值相同`);
    const tag = JSON.stringify(SENTINELS[key]);
    assert.ok(!seenSentinels.has(tag), `${key} 哨兵值 ${tag} 与其他字段冲突`);
    seenSentinels.add(tag);
  }
  await asyncFixture(async (rootDir) => {
    let cursor = 0;
    const failures: string[] = [];
    const worker = async () => {
      while (cursor < schemaKeys.length) {
        const key = schemaKeys[cursor++]!;
        const fieldDir = join(rootDir, key);
        mkdirSync(fieldDir, { recursive: true });
        const env = cleanSchedulerEnv(writeSingleFieldSentinelConfig(fieldDir, key));
        try { await SENTINEL_PROBES[key]({ key, value: SENTINELS[key], env, dir: fieldDir }); }
        catch (error) { failures.push(`[${key}=${JSON.stringify(SENTINELS[key])}] ${error instanceof Error ? error.message : String(error)}`); }
      }
    };
    await Promise.all(Array.from({ length: 6 }, worker));
    assert.equal(failures.join("\n\n"), "", "以下配置字段未在消费入口真实生效哨兵值");
  });
});

// ═════════════════════════════════════════════════════════════════════════════
// 层 2（补充）：TypeScript 编译器 API AST 汇点与残留调度声明守卫
// ═════════════════════════════════════════════════════════════════════════════

interface SinkSpec {
  readonly id: string;
  readonly category: "timer" | "subprocess" | "model" | "effort" | "concurrency" | "retry" | "threshold" | "cli-default" | "query-limit";
  readonly kind: "call-arg" | "call-option" | "sh-sleep" | "cli-option-default" | "param-default" | "nullish-fallback" | "deadline-add" | "loop-bound" | "cli-flag-template" | "probe-template";
  readonly target: string;
  readonly argIndex?: number;
  readonly optionKeys?: readonly string[];
  readonly allowZeroKeys?: readonly string[];
  readonly names?: readonly string[];
  readonly description: string;
}

/** 调度参数汇点清单：每一类汇点写明位置、语义和必须追溯到配置的理由。 */
const SCHEDULER_SINKS: readonly SinkSpec[] = [
  { id: "timer.setTimeout", category: "timer", kind: "call-arg", target: "setTimeout", argIndex: 1, description: "计时器延时实参（空转/总超时/退避/轮询/退出轮询/强杀宽限）必须追溯到配置或入参" },
  { id: "timer.abortSignalTimeout", category: "timer", kind: "call-arg", target: "AbortSignal.timeout", argIndex: 0, description: "HTTP 请求超时实参（健康检查/容器模型预检）必须追溯到配置" },
  { id: "timer.sleep", category: "timer", kind: "call-arg", target: "sleep", argIndex: 0, description: "重试、锁等待与轮询休眠实参必须追溯到配置或入参" },
  { id: "timer.shSleep", category: "timer", kind: "sh-sleep", target: "sh", description: "子进程 sleep 秒数实参（进程等待轮询间隔）必须追溯到配置" },
  { id: "subprocess.execFileSync", category: "subprocess", kind: "call-option", target: "execFileSync", argIndex: 2, optionKeys: ["timeout"], description: "execFileSync 超时选项（Docker CLI/容器预检）必须追溯到配置" },
  { id: "subprocess.execSync", category: "subprocess", kind: "call-option", target: "execSync", argIndex: 1, optionKeys: ["timeout"], description: "execSync 超时选项必须追溯到配置" },
  { id: "subprocess.spawnSync", category: "subprocess", kind: "call-option", target: "spawnSync", argIndex: 2, optionKeys: ["timeout"], description: "spawnSync 超时选项必须追溯到配置" },
  { id: "model.codex", category: "model", kind: "call-arg", target: "codex", argIndex: 0, description: "Sandcastle codex() 模型实参必须追溯到配置或入参" },
  { id: "effort.codex", category: "effort", kind: "call-option", target: "codex", argIndex: 1, optionKeys: ["effort"], description: "Sandcastle codex() 推理强度选项必须追溯到配置或入参" },
  { id: "modelEffort.codexWorker", category: "effort", kind: "call-option", target: "codexWorker", argIndex: 0, optionKeys: ["model", "effort"], description: "codexWorker() 模型与推理强度选项必须追溯到配置（拦截 effort: \"low\"）" },
  { id: "child.runCodexChild", category: "timer", kind: "call-option", target: "runCodexChild", argIndex: 0, optionKeys: ["model", "idleTimeoutSeconds", "timeoutSeconds"], description: "runCodexChild() 模型与超时选项必须追溯到配置或显式 CLI 入参" },
  { id: "child.supervisedNoSandbox", category: "timer", kind: "call-option", target: "supervisedNoSandbox", argIndex: 1, optionKeys: ["idleTimeoutSeconds", "timeoutSeconds"], description: "supervisedNoSandbox() 空闲与总超时选项必须追溯到配置或入参" },
  { id: "main.runWithResume", category: "timer", kind: "call-option", target: "runWithResume", argIndex: 1, optionKeys: ["idleTimeoutSeconds"], description: "runWithResume() 空闲超时选项必须追溯到配置或入参" },
  { id: "concurrency.semaphore", category: "concurrency", kind: "call-arg", target: "semaphore", argIndex: 0, description: "Swarm 并发信号量上限实参必须追溯到配置" },
  { id: "threshold.rollbackStuckClaims", category: "threshold", kind: "call-option", target: "rollbackStuckClaims", argIndex: 0, optionKeys: ["minAgeMs"], allowZeroKeys: ["minAgeMs"], description: "认领回滚看门狗陈旧阈值必须追溯到配置（0 为失败后立即回滚模式）" },
  { id: "cli.parseArgsDefault", category: "cli-default", kind: "cli-option-default", target: "parseArgs", names: ["idle-timeout-seconds", "timeout-seconds", "model", "effort", "poll-seconds", "max-attempts", "max-rounds", "concurrency"], description: "CLI parseArgs 不得为调度参数设置字面量默认值（拦截 codex-child.mts default: \"600\"/\"3600\"）" },
  { id: "param.schedulingDefault", category: "threshold", kind: "param-default", target: "parameter", names: ["staleMs", "minGiB", "waitMs", "baseMs", "capMs", "timeoutMs", "idleTimeoutSeconds", "timeoutSeconds", "maxAttempts", "maxRounds", "pollSeconds", "drafter", "model", "effort"], description: "调度函数形参默认值必须追溯到配置（拦截 health-monitor.mts staleMs = 600_000）" },
  { id: "fallback.schedulingNullish", category: "threshold", kind: "nullish-fallback", target: "??", names: ["staleMs", "minGiB", "waitMs", "baseMs", "capMs", "timeoutMs", "idleTimeoutSeconds", "timeoutSeconds", "maxAttempts", "maxRounds", "pollSeconds", "model", "effort", "concurrency", "maps"], allowZeroKeys: ["minAgeMs"], description: "调度选项空值回退右侧必须追溯到配置" },
  { id: "timer.deadlineAdd", category: "timer", kind: "deadline-add", target: "Date.now()+ms", description: "Date.now() + 截止时长必须追溯到配置或入参" },
  { id: "retry.loopUpperBound", category: "retry", kind: "loop-bound", target: "attempt/round/iter/iteration", names: ["attempt", "round", "iter", "iteration"], description: "重试次数、续跑轮次与单轮票数上界必须追溯到配置" },
  { id: "query.ghIssueListLimit", category: "query-limit", kind: "cli-flag-template", target: "gh issue list --limit", description: "gh issue list --limit 上限必须追溯到配置" },
  { id: "model.dockerProbeTemplate", category: "model", kind: "probe-template", target: "DOCKER_MODEL_PROBE", description: "容器模型预检脚本中的模型名与 AbortSignal.timeout 必须插值自配置" },
];

const ENTRY_FILES = [
  "main.mts", "main-swarm.mts", "main-model.mts",
  "codex-child.ts", "codex-child.mts", "codex-route.mts",
  "decision-claimer.mts", "claim-loop.mts", "health-monitor.mts",
  "docker-isolation.mts", "swarm-route.mts",
] as const;

type ConstEval =
  | { kind: "number"; value: number; text: string }
  | { kind: "string"; value: string; text: string }
  | { kind: "number[]"; text: string };

const splitTokens = (name: string) =>
  name.replace(/([a-z0-9])([A-Z])/g, "$1_$2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2").toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);

const NUMERIC_SCHED_TOKENS = new Set([
  "timeout", "idle", "poll", "interval", "delay", "delays", "backoff", "stale",
  "retry", "retries", "attempts", "rounds", "iterations", "parallel", "concurrent",
  "concurrency", "grace", "waits", "schedule", "rollback", "gib", "watchdog",
]);

function isNumericSchedulingName(name: string): boolean {
  const tokens = splitTokens(name);
  if (tokens.some(t => NUMERIC_SCHED_TOKENS.has(t))) return true;
  const set = new Set(tokens);
  return (set.has("query") && set.has("limit")) || (set.has("max") && set.has("tickets")) || (set.has("decision") && set.has("maps"));
}

function isModelOrEffortSchedulingName(name: string): boolean {
  const set = new Set(splitTokens(name));
  if (set.has("effort")) return true;
  if (set.has("model") || set.has("models")) return !(set.has("provider") || set.has("family") || set.has("probe") || set.has("attempts") || set.has("ids"));
  if (set.has("route")) return !(set.has("env") || set.has("checked"));
  return false;
}

const propKeyName = (name: ts.PropertyName) =>
  (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNoSubstitutionTemplateLiteral(name)) ? name.text : null;

function calleeName(expr: ts.Expression): string | null {
  const v = ts.skipOuterExpressions(expr);
  if (ts.isIdentifier(v)) return v.text;
  if (ts.isPropertyAccessExpression(v) && ts.isIdentifier(v.expression)) return `${v.expression.text}.${v.name.text}`;
  return null;
}

function isEnvAccess(expr: ts.Expression): boolean {
  const v = ts.skipOuterExpressions(expr);
  if (!ts.isPropertyAccessExpression(v) && !ts.isElementAccessExpression(v)) return false;
  const obj = ts.skipOuterExpressions(v.expression);
  return (ts.isPropertyAccessExpression(obj) && ts.isIdentifier(obj.expression) && obj.expression.text === "process" && obj.name.text === "env")
    || (ts.isIdentifier(obj) && obj.text === "env");
}

function evalConst(expr: ts.Expression, source: ts.SourceFile): ConstEval | null {
  const v = ts.skipOuterExpressions(expr);
  if (ts.isNumericLiteral(v)) return { kind: "number", value: Number(v.text), text: source.text.slice(ts.getTokenPosOfNode(v, source), v.end) };
  if (ts.isStringLiteral(v) || ts.isNoSubstitutionTemplateLiteral(v)) return { kind: "string", value: v.text, text: JSON.stringify(v.text) };
  if (ts.isTemplateExpression(v)) {
    let out = v.head.text;
    for (const span of v.templateSpans) {
      const part = evalConst(span.expression, source);
      if (!part || part.kind === "number[]") return null;
      out += String(part.value) + span.literal.text;
    }
    return { kind: "string", value: out, text: JSON.stringify(out) };
  }
  if (ts.isPrefixUnaryExpression(v) && (v.operator === ts.SyntaxKind.PlusToken || v.operator === ts.SyntaxKind.MinusToken)) {
    const inner = evalConst(v.operand, source);
    if (inner?.kind === "number") return { kind: "number", value: v.operator === ts.SyntaxKind.MinusToken ? -inner.value : inner.value, text: source.text.slice(ts.getTokenPosOfNode(v, source), v.end) };
  }
  if (ts.isBinaryExpression(v)) {
    const op = ts.tokenToString(v.operatorToken.kind) ?? "";
    if ((op === "??" || op === "||") && isEnvAccess(v.left)) return evalConst(v.right, source);
    if (/^(?:[+*/%-]|\*\*)$/.test(op)) {
      const l = evalConst(v.left, source), r = evalConst(v.right, source);
      if (l?.kind === "number" && r?.kind === "number") {
        const value = op === "+" ? l.value + r.value : op === "-" ? l.value - r.value : op === "*" ? l.value * r.value : op === "/" ? l.value / r.value : op === "%" ? l.value % r.value : l.value ** r.value;
        return { kind: "number", value, text: source.text.slice(ts.getTokenPosOfNode(v, source), v.end) };
      }
      if (op === "+" && l && r && l.kind !== "number[]" && r.kind !== "number[]") {
        const value = String(l.value) + String(r.value);
        return { kind: "string", value, text: JSON.stringify(value) };
      }
    }
  }
  if (ts.isCallExpression(v) && ts.isIdentifier(v.expression) && v.arguments.length >= 1) {
    const fn = v.expression.text;
    if (fn === "Number" || fn === "parseInt" || fn === "parseFloat") {
      const arg = evalConst(v.arguments[0]!, source);
      if (arg && arg.kind !== "number[]" && Number.isFinite(Number(arg.value))) {
        return { kind: "number", value: Number(arg.value), text: source.text.slice(ts.getTokenPosOfNode(v, source), v.end) };
      }
    }
    if (fn === "String") {
      const arg = evalConst(v.arguments[0]!, source);
      if (arg && arg.kind !== "number[]") return { kind: "string", value: String(arg.value), text: JSON.stringify(String(arg.value)) };
    }
  }
  if (ts.isArrayLiteralExpression(v) && v.elements.length > 0 && v.elements.every(el => evalConst(el, source)?.kind === "number")) {
    return { kind: "number[]", text: source.text.slice(ts.getTokenPosOfNode(v, source), v.end) };
  }
  return null;
}

function extractStringElements(expr: ts.Expression, source: ts.SourceFile): Array<{ node: ts.Node; value: string }> {
  const v = ts.skipOuterExpressions(expr);
  if (ts.isNewExpression(v) && ts.isIdentifier(v.expression) && v.expression.text === "Set" && v.arguments?.length === 1) {
    return extractStringElements(v.arguments[0]!, source);
  }
  if (ts.isArrayLiteralExpression(v)) {
    const out: Array<{ node: ts.Node; value: string }> = [];
    for (const el of v.elements) {
      const ev = evalConst(el, source);
      if (ev?.kind === "string") out.push({ node: el, value: ev.value });
    }
    return out;
  }
  const single = evalConst(v, source);
  return single?.kind === "string" ? [{ node: v, value: single.value }] : [];
}

function isSandboxSingleTurnOption(prop: ts.PropertyAssignment): boolean {
  const obj = prop.parent;
  const call = obj?.parent;
  if (!call || !ts.isCallExpression(call)) return false;
  const callee = ts.skipOuterExpressions(call.expression);
  return ts.isPropertyAccessExpression(callee) && callee.name.text === "run";
}

test("#1606 C-29/C-30 入口调度汇点与残留声明 AST 守卫（含四条精确例外）", () => {
  assert.ok(SCHEDULER_SINKS.length >= 20, "汇点清单不得为空");
  // 逐字面量精确豁免；不绑定行号、不许通配，每项只抵扣一次命中。
  const exceptions = new Map<string, string>([
    ['codex-child.ts:EXTERNAL_REVIEW_MODELS="kimi-k3.1-pro"', "#1742 外审准入名单，与 external_review.py 的 MODELS 由测试对拍"],
    ['codex-child.ts:EXTERNAL_REVIEW_MODELS="claude-opus-5-5"', "#1742 外审准入名单，与 external_review.py 的 MODELS 由测试对拍"],
    ['codex-child.ts:PROMPT_JSON_MODELS="kimi-k3.1-pro"', "#1968 指定模型走提示词 JSON 的协议兼容表，不选调度模型"],
    ["decision-claimer.mts:MIN_MODEL_ATTEMPTS=5", "#1547 首次加至少四次重试的政策下限，可调总次数来自 decisionMaxAttempts"],
  ]);

  const paramSinkNames = new Set(SCHEDULER_SINKS.find(s => s.kind === "param-default")!.names!);
  const fallbackSinkNames = new Set(SCHEDULER_SINKS.find(s => s.kind === "nullish-fallback")!.names!);
  const cliDefaultNames = new Set(SCHEDULER_SINKS.find(s => s.kind === "cli-option-default")!.names!);
  const loopCounterNames = new Set(SCHEDULER_SINKS.find(s => s.kind === "loop-bound")!.names!);
  const callArgSinks = new Map<string, SinkSpec[]>();
  const callOptSinks = new Map<string, SinkSpec[]>();
  for (const s of SCHEDULER_SINKS) {
    if (s.kind === "call-arg") callArgSinks.set(s.target, [...(callArgSinks.get(s.target) ?? []), s]);
    if (s.kind === "call-option") callOptSinks.set(s.target, [...(callOptSinks.get(s.target) ?? []), s]);
  }

  const failures: string[] = [];
  const projectPath = fileURLToPath(new URL("../tsconfig.sandcastle.json", import.meta.url));
  const api = new API({ cwd: dirname(projectPath) });
  try {
    const snapshot = api.updateSnapshot({ openProjects: [projectPath] });
    try {
      const project = snapshot.getProject(projectPath);
      assert.ok(project, projectPath);
      for (const file of ENTRY_FILES) {
        const source = project.program.getSourceFile(fileURLToPath(new URL(file, import.meta.url)));
        assert.ok(source, `.sandcastle/${file} 未纳入 AST 扫描`);
        const textOf = (n: ts.Node) => source.text.slice(ts.getTokenPosOfNode(n, source), n.end);
        const lineOf = (n: ts.Node) => source.getLineAndCharacterOfPosition(ts.getTokenPosOfNode(n, source)).line + 1;
        const reportDecl = (n: ts.Node, name: string, lit: string) => {
          const hit = `${name}=${lit}`;
          if (exceptions.delete(`${file}:${hit}`)) return;
          failures.push(`.sandcastle/${file}:${lineOf(n)}: ${hit}`);
        };
        const reportSink = (n: ts.Node, sinkId: string, detail: string) => failures.push(`.sandcastle/${file}:${lineOf(n)}: [${sinkId}] ${detail}`);

        const configImports = new Set<string>(), schedulerVars = new Set<string>(), parseArgsVars = new Set<string>();
        const topBindings = new Map<string, ts.Expression>();
        const collectTop = (n: ts.Node) => {
          if (ts.isImportDeclaration(n) && ts.isStringLiteral(n.moduleSpecifier) && n.moduleSpecifier.text === "./main-model.mts") {
            const b = n.importClause?.namedBindings;
            if (b && ts.isNamedImports(b)) for (const el of b.elements) if ((el.propertyName?.text ?? el.name.text) === "MAIN_MODEL") configImports.add(el.name.text);
          }
          if (ts.isVariableDeclaration(n) && n.initializer) {
            const init = ts.skipOuterExpressions(n.initializer);
            if (ts.isIdentifier(n.name)) {
              topBindings.set(n.name.text, init);
              if (ts.isCallExpression(init) && calleeName(init.expression) === "useScheduler") schedulerVars.add(n.name.text);
            }
            if (ts.isObjectBindingPattern(n.name) && ts.isCallExpression(init) && calleeName(init.expression) === "parseArgs") {
              for (const el of n.name.elements) if (el.name && ts.isIdentifier(el.name)) parseArgsVars.add(el.name.text);
            }
          }
          n.forEachChild(collectTop);
        };
        collectTop(source);

        const isConfigBacked = (expr: ts.Expression, scope: Map<string, ts.Expression>, params: Set<string>, visited = new Set<string>()): boolean => {
          const v = ts.skipOuterExpressions(expr);
          if (evalConst(v, source) !== null) return false;
          if (ts.isPropertyAccessExpression(v)) {
            const base = ts.skipOuterExpressions(v.expression);
            if (ts.isIdentifier(base) && (schedulerVars.has(base.text) || parseArgsVars.has(base.text) || params.has(base.text))) return true;
            if (ts.isCallExpression(base) && calleeName(base.expression) === "useScheduler") return true;
            return isConfigBacked(base, scope, params, visited);
          }
          if (ts.isElementAccessExpression(v)) {
            const base = ts.skipOuterExpressions(v.expression);
            if (ts.isIdentifier(base) && (parseArgsVars.has(base.text) || params.has(base.text))) return true;
            return isConfigBacked(base, scope, params, visited);
          }
          if (ts.isIdentifier(v)) {
            const name = v.text;
            if (configImports.has(name) || schedulerVars.has(name) || parseArgsVars.has(name) || params.has(name)) return true;
            if (visited.has(name)) return false;
            visited.add(name);
            const init = scope.get(name) ?? topBindings.get(name);
            return init ? isConfigBacked(init, scope, params, visited) : false;
          }
          if (ts.isBinaryExpression(v)) {
            const op = ts.tokenToString(v.operatorToken.kind) ?? "";
            if (op === "??" || op === "||") return isConfigBacked(v.right, scope, params, visited);
            if (/^(?:[+*/%-]|\*\*)$/.test(op)) return isConfigBacked(v.left, scope, params, visited) || isConfigBacked(v.right, scope, params, visited);
          }
          if (ts.isConditionalExpression(v)) {
            if (evalConst(v.whenTrue, source) !== null && evalConst(v.whenFalse, source) !== null) return false;
            return isConfigBacked(v.whenTrue, scope, params, visited) || isConfigBacked(v.whenFalse, scope, params, visited);
          }
          if (ts.isCallExpression(v)) {
            const fn = calleeName(v.expression);
            if (fn === "useScheduler" || fn === "backoffMs" || fn === "parseArgs") return true;
            return v.arguments.some(a => isConfigBacked(a, scope, params, visited));
          }
          return false;
        };

        const walk = (node: ts.Node, scope: Map<string, ts.Expression>, params: Set<string>, inForInit = false) => {
          let nextScope = scope, nextParams = params;
          if (ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node) || ts.isMethodDeclaration(node)) {
            nextParams = new Set(params); nextScope = new Map(scope);
            for (const p of node.parameters) {
              if (ts.isIdentifier(p.name)) {
                nextParams.add(p.name.text);
                if (p.initializer && paramSinkNames.has(p.name.text) && !isConfigBacked(p.initializer, nextScope, nextParams)) {
                  reportSink(p.initializer, "param.schedulingDefault", `${p.name.text}=${textOf(p.initializer)}`);
                }
              } else if (ts.isObjectBindingPattern(p.name)) {
                for (const el of p.name.elements) if (el.name && ts.isIdentifier(el.name)) nextParams.add(el.name.text);
              }
            }
          }

          if (ts.isCallExpression(node)) {
            const fn = calleeName(node.expression);
            if (fn) {
              for (const spec of callArgSinks.get(fn) ?? []) {
                const arg = node.arguments[spec.argIndex!];
                if (arg && !isConfigBacked(arg, nextScope, nextParams)) reportSink(arg, spec.id, `${fn} arg[${spec.argIndex}]=${textOf(arg)}`);
              }
              for (const spec of callOptSinks.get(fn) ?? []) {
                const optArg = node.arguments[spec.argIndex!];
                if (optArg && ts.isObjectLiteralExpression(ts.skipOuterExpressions(optArg))) {
                  for (const prop of (ts.skipOuterExpressions(optArg) as ts.ObjectLiteralExpression).properties) {
                    if (ts.isPropertyAssignment(prop)) {
                      const key = propKeyName(prop.name);
                      if (key && spec.optionKeys!.includes(key)) {
                        const ev = evalConst(prop.initializer, source);
                        if (spec.allowZeroKeys?.includes(key) && ev?.kind === "number" && ev.value === 0) continue;
                        if (!isConfigBacked(prop.initializer, nextScope, nextParams)) reportSink(prop.initializer, spec.id, `${fn}({ ${key}: ${textOf(prop.initializer)} })`);
                      }
                    } else if (ts.isShorthandPropertyAssignment(prop) && ts.isIdentifier(prop.name)) {
                      const key = prop.name.text;
                      if (spec.optionKeys!.includes(key) && !isConfigBacked(prop.name, nextScope, nextParams)) reportSink(prop, spec.id, `${fn}({ ${key} })`);
                    }
                  }
                }
              }
              if (fn === "sh" && node.arguments.length >= 2) {
                const first = evalConst(node.arguments[0]!, source), second = ts.skipOuterExpressions(node.arguments[1]!);
                if (first?.kind === "string" && first.value === "sleep" && ts.isArrayLiteralExpression(second) && second.elements[0] && !isConfigBacked(second.elements[0], nextScope, nextParams)) {
                  reportSink(second.elements[0], "timer.shSleep", `sh("sleep", [${textOf(second.elements[0])}])`);
                }
              }
              if (fn === "parseArgs" && node.arguments[0]) {
                const arg0 = ts.skipOuterExpressions(node.arguments[0]);
                if (ts.isObjectLiteralExpression(arg0)) {
                  const optsProp = arg0.properties.find(p => ts.isPropertyAssignment(p) && propKeyName(p.name) === "options");
                  if (optsProp && ts.isPropertyAssignment(optsProp) && ts.isObjectLiteralExpression(ts.skipOuterExpressions(optsProp.initializer))) {
                    for (const p of (ts.skipOuterExpressions(optsProp.initializer) as ts.ObjectLiteralExpression).properties) {
                      if (!ts.isPropertyAssignment(p)) continue;
                      const optName = propKeyName(p.name);
                      if (!optName || !cliDefaultNames.has(optName)) continue;
                      const desc = ts.skipOuterExpressions(p.initializer);
                      if (!ts.isObjectLiteralExpression(desc)) continue;
                      const defProp = desc.properties.find(dp => ts.isPropertyAssignment(dp) && propKeyName(dp.name) === "default");
                      if (defProp && ts.isPropertyAssignment(defProp) && !isConfigBacked(defProp.initializer, nextScope, nextParams)) {
                        reportSink(defProp, "cli.parseArgsDefault", `parseArgs options[${JSON.stringify(optName)}].default=${textOf(defProp.initializer)}`);
                      }
                    }
                  }
                }
              }
              if (fn === "execSync" || fn === "execFileSync") {
                for (const arg of node.arguments) {
                  const a = ts.skipOuterExpressions(arg);
                  if ((ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) && /gh\s+issue\s+list\b.*--limit\s+\d+/.test(a.text)) {
                    reportSink(a, "query.ghIssueListLimit", a.text);
                  } else if (ts.isTemplateExpression(a) && /gh\s+issue\s+list\b/.test(a.head.text)) {
                    if (/--limit\s+\d+/.test(a.head.text)) reportSink(a, "query.ghIssueListLimit", a.head.text);
                    for (const span of a.templateSpans) if (/--limit\s+\d+/.test(span.literal.text)) reportSink(span.literal, "query.ghIssueListLimit", span.literal.text);
                    if (/--limit\s+$/.test(a.head.text) && a.templateSpans[0] && !isConfigBacked(a.templateSpans[0].expression, nextScope, nextParams)) {
                      reportSink(a.templateSpans[0].expression, "query.ghIssueListLimit", textOf(a.templateSpans[0].expression));
                    }
                  }
                }
              }
            }
          }

          if (ts.isBinaryExpression(node)) {
            const op = ts.tokenToString(node.operatorToken.kind) ?? "";
            if (op === "??") {
              const lhs = ts.skipOuterExpressions(node.left);
              if (ts.isPropertyAccessExpression(lhs) && fallbackSinkNames.has(lhs.name.text) && !isConfigBacked(node.right, nextScope, nextParams)) {
                reportSink(node.right, "fallback.schedulingNullish", `${lhs.name.text} ?? ${textOf(node.right)}`);
              }
            } else if (op === "+") {
              const lhs = ts.skipOuterExpressions(node.left);
              if (ts.isCallExpression(lhs) && calleeName(lhs.expression) === "Date.now" && evalConst(node.right, source)?.kind === "number") {
                reportSink(node.right, "timer.deadlineAdd", `Date.now() + ${textOf(node.right)}`);
              }
            } else if (op === "<" || op === "<=" || op === ">" || op === ">=") {
              const lhs = ts.skipOuterExpressions(node.left);
              const counter = ts.isIdentifier(lhs) ? lhs.text : ts.isPropertyAccessExpression(lhs) ? lhs.name.text : null;
              if (counter && loopCounterNames.has(counter)) {
                const rhsConst = evalConst(node.right, source);
                const isLowerOneCheck = rhsConst?.kind === "number" && rhsConst.value === 1 && (op === "<" || op === ">" || op === ">=");
                if (!isLowerOneCheck && rhsConst?.kind === "number") reportSink(node.right, "retry.loopUpperBound", `${counter} ${op} ${rhsConst.text}`);
              }
            }
          }

          if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === "DOCKER_MODEL_PROBE" && node.initializer) {
            const init = ts.skipOuterExpressions(node.initializer);
            if (ts.isTaggedTemplateExpression(init) && ts.isTemplateExpression(init.template)) {
              for (const chunk of [init.template.head.text, ...init.template.templateSpans.map(s => s.literal.text)]) {
                if (/AbortSignal\.timeout\(\s*\d+/.test(chunk)) reportSink(init.template, "model.dockerProbeTemplate", "AbortSignal.timeout 字面量");
                if (/model:\s*"[^"$]+?"/.test(chunk)) reportSink(init.template, "model.dockerProbeTemplate", "model 字面量");
              }
              for (const span of init.template.templateSpans) {
                if (!isConfigBacked(span.expression, nextScope, nextParams) && !textOf(span.expression).includes("responseModelIds")) {
                  reportSink(span.expression, "model.dockerProbeTemplate", textOf(span.expression));
                }
              }
            }
          }

          if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer && !inForInit) {
            const name = node.name.text, init = ts.skipOuterExpressions(node.initializer);
            nextScope.set(name, init);
            if (isNumericSchedulingName(name)) {
              const ev = evalConst(init, source);
              if (ev && (ev.kind === "number" || ev.kind === "number[]")) reportDecl(init, name, ev.text);
            }
            if (isModelOrEffortSchedulingName(name)) {
              for (const hit of extractStringElements(init, source)) reportDecl(hit.node, name, JSON.stringify(hit.value));
            }
          }
          if (ts.isPropertyAssignment(node)) {
            const key = propKeyName(node.name), init = ts.skipOuterExpressions(node.initializer);
            if (key && isNumericSchedulingName(key)) {
              const ev = evalConst(init, source);
              if (ev && (ev.kind === "number" || ev.kind === "number[]")) {
                const isSingleTurnRun = key === "maxIterations" && ev.kind === "number" && ev.value === 1 && isSandboxSingleTurnOption(node);
                const isZeroAttemptCounter = key === "attempts" && ev.kind === "number" && ev.value === 0;
                if (!isSingleTurnRun && !isZeroAttemptCounter) reportDecl(init, key, ev.text);
              }
            }
            if (key && isModelOrEffortSchedulingName(key)) {
              for (const hit of extractStringElements(init, source)) reportDecl(hit.node, key, JSON.stringify(hit.value));
            }
          }

          if (ts.isForStatement(node)) {
            if (node.initializer) walk(node.initializer, nextScope, nextParams, true);
            if (node.condition) walk(node.condition, nextScope, nextParams, false);
            if (node.incrementor) walk(node.incrementor, nextScope, nextParams, false);
            walk(node.statement, nextScope, nextParams, false);
            return;
          }
          node.forEachChild(child => walk(child, nextScope, nextParams, inForInit));
        };
        walk(source, new Map(topBindings), new Set());
      }
    } finally { snapshot.dispose(); }
  } finally { api.close(); }

  for (const key of exceptions.keys()) failures.push(`删除已失效的豁免：${key}`);
  assert.equal(failures.join("\n"), "", "#1606 调度汇点或残留声明必须读取版本化配置，或按票号登记精确例外");
});

test("真实 claim-loop dry-run 与集成基线 main@3a01bed557 同值等价，不写票不启动工蜂", () => fixture(path => {
  const dir = dirname(path); const bin = join(dir, "bin"); mkdirSync(bin);
  const calls = join(dir, "calls");
  writeFileSync(join(bin, "pgrep"), "#!/bin/sh\nexit 1\n", { mode: 0o755 });
  writeFileSync(join(bin, "gh"), '#!/bin/sh\necho "$*" >> "$CALLS"\ncase "$1 $2" in\n"issue list") echo \'[{"number":1606,"assignees":[]}]\';;\n"api repos/"*) echo 0;;\n*) exit 98;;\nesac\n', { mode: 0o755 });
  const baseline = readFileSync(new URL("./fixtures/issue1606/claim-loop-before.mts", import.meta.url), "utf8");
  const before = join(dir, "before.mts"); writeFileSync(before, baseline);
  for (const helper of ["drain-control.mts", "drain-control.py"]) writeFileSync(join(dir, helper), readFileSync(new URL("./" + helper, import.meta.url)));
  const env = { PATH: bin + ":" + process.env.PATH, CALLS: calls, HOME: dir };
  const run = (script: string) => {
    writeFileSync(calls, "");
    const result = spawnSync("bun", [script, "--once", "--dry-run"], { cwd: dir, env, encoding: "utf8", timeout: 10000 });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /dry-run=true poll=60s/);
    assert.match(result.stdout, /dry-run/);
    return { stdout: result.stdout, calls: readFileSync(calls, "utf8") };
  };
  assert.deepEqual(run(fileURLToPath(new URL("./claim-loop.mts", import.meta.url))), run(before));
}));

test("Node timer 毫秒字段拒绝溢出；最大合法值保留真实 timer 延时", () => fixture(path => {
  const max = 2 ** 31 - 1;
  const keys: SchedulerKey[] = ["childKillGraceMs", "childExitPollMs", "adrLockPollMs",
    "healthHttpTimeoutMs", "dockerModelHttpTimeoutMs", "worktreeRetryDelayMs",
    "decisionLoopMs", "decisionTimeoutMs", "decisionBackoffBaseMs", "decisionBackoffCapMs"];
  for (const key of keys) {
    const record = structuredClone(original);
    record.values[key] = max + 1;
    writeFileSync(path, JSON.stringify(record));
    assert.throws(() => readSchedulerConfig(path, {}), new RegExp("values\\." + key));
    assert.throws(() => readSchedulerConfig(configPath, { [schedulerEnvName(key)]: String(max + 1) }), new RegExp("values\\." + key));
    const config = readSchedulerConfig(configPath, {
      [schedulerEnvName(key)]: String(max), SANDCASTLE_DECISION_BACKOFF_CAP_MS: String(max),
    });
    const timer = setTimeout(() => {}, config.values[key] as number);
    try { assert.equal((timer as unknown as { _idleTimeout: number })._idleTimeout, max); }
    finally { clearTimeout(timer); }
  }
}));

test("秒换算 timer 范围有界，非 timer 参数不受 Node 上限影响", () => {
  for (const [key, max] of [["implementerIdleSeconds", 2147483], ["claimPollSeconds", 2147483.647]] as const) {
    assert.equal(readSchedulerConfig(configPath, { [schedulerEnvName(key)]: String(max) }).values[key], max);
    assert.throws(() => readSchedulerConfig(configPath, { [schedulerEnvName(key)]: String(max + 1) }), new RegExp("values\\." + key));
  }
  for (const key of ["childExitWaitMs", "healthProcessWaitMs", "healthProcessPollSeconds", "claimRollbackMs", "claimStaleMs", "wayfinderStaleMs", "adrLockMaxWaits", "frontierQueryLimit", "diskMinGiB"] as const) {
    assert.equal(readSchedulerConfig(configPath, { [schedulerEnvName(key)]: "2147483648" }).values[key], 2147483648);
  }
});

test("Docker CLI 现役探针和失败回收读取同一超时，日志保留来源", () => {
  const code = `
    import cp from "node:child_process";
    import {syncBuiltinESMExports} from "node:module";
    const calls = [];
    cp.execFileSync = (command, args, options) => {
      calls.push({command, args, timeout: options.timeout, killSignal: options.killSignal});
      if (args[0] === "run") throw Object.assign(new Error("probe timeout"), {signal:"SIGKILL"});
      return "";
    };
    syncBuiltinESMExports();
    const {probeDockerIsolation} = await import("./.sandcastle/docker-isolation.mts");
    try { probeDockerIsolation("fixture-only"); } catch (e) {
      if (e.message !== "probe timeout") throw e;
    }
    console.log(JSON.stringify(calls));
  `;
  const run = (timeout: string) => spawnSync(process.execPath, ["--import", TSX_LOADER, "--input-type=module", "-e", code],
    { encoding: "utf8", env: { ...process.env, SANDCASTLE_DOCKER_CLI_TIMEOUT_MS: timeout } });
  const result = run("1234");
  assert.equal(result.status, 0, result.stderr);
  const calls = JSON.parse(result.stdout);
  assert.deepEqual(calls.map((c: any) => [c.command, c.args[0], c.timeout, c.killSignal]),
    [["docker", "run", 1234, "SIGKILL"], ["docker", "rm", 1234, "SIGKILL"]]);
  assert.equal(calls[0].args[calls[0].args.indexOf("--name") + 1], calls[1].args[2]);
  assert.match(result.stderr, /docker-isolation.dockerCliTimeoutMs=1234 source=env:SANDCASTLE_DOCKER_CLI_TIMEOUT_MS/);
  const bad = run("0");
  assert.notEqual(bad.status, 0);
  assert.match(bad.stderr, /values.dockerCliTimeoutMs/);
  assert.equal(bad.stdout, "");
});
