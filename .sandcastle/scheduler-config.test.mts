import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { API } from "typescript/unstable/sync";
import * as ts from "typescript/unstable/ast";
import { configPath, readSchedulerConfig, schedulerEnvName, type SchedulerKey } from "./scheduler-config.mts";

const expected = {
  childKillGraceMs: 1000,
  childExitPollMs: 25,
  childExitWaitMs: 3000,
  healthProcessWaitMs: 15000,
  healthProcessPollSeconds: 1,
  healthHttpTimeoutMs: 5000,
  adrLockMaxWaits: 600,
  adrLockPollMs: 100,
  dockerCliTimeoutMs: 60000,
  dockerModelHttpTimeoutMs: 60000,
  dockerModelProcessTimeoutMs: 75000,
  frontierQueryLimit: 20,
  backlogQueryLimit: 1000,
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
test("版本1完整值保持集成基线 main@3a01bed557，来源完整且有效值冻结", () => {
  const config = readSchedulerConfig(configPath, {});
  assert.equal(config.revision, 1); assert.equal(config.ticket, 1606);
  assert.deepEqual(config.values, expected);
  assert.equal(Object.isFrozen(config.values), true);
  for (const key of Object.keys(expected)) assert.match(config.origins[key]!, /^record:1 /);
});
test("文件、JSON、逐字段、逐来源缺失均拒绝；不回退旧常量", () => fixture(path => {
  assert.throws(() => readSchedulerConfig(path, {}), /无法读取JSON/);
  writeFileSync(path, "{");
  assert.throws(() => readSchedulerConfig(path, {}), /无法读取JSON/);
  for (const section of ["values", "sources"]) for (const key of Object.keys(expected)) {
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
  for (const [key, value] of Object.entries(expected)) {
    env[schedulerEnvName(key as SchedulerKey)] = Array.isArray(value) ? JSON.stringify(value) : String(value);
  }
  const config = readSchedulerConfig(configPath, env);
  assert.deepEqual(config.values, expected);
  for (const key of Object.keys(expected) as SchedulerKey[]) assert.equal(config.origins[key], "env:" + schedulerEnvName(key));
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
    "claim-loop.mts": ["claimPollSeconds", "claimRollbackMs"],
    "health-monitor.mts": ["healthProcessWaitMs", "healthProcessPollSeconds", "healthHttpTimeoutMs", "wayfinderStaleMs", "claimStaleMs", "diskMinGiB"],
  };
  assert.match(readFileSync(new URL("./main-model.mts", import.meta.url), "utf8"),
    /MAIN_MODEL = useScheduler\("main-model", \["mainModel"\]\)\.mainModel/);
  for (const [file, keys] of Object.entries(files)) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    for (const key of keys) assert.match(source, new RegExp("scheduler\\." + key));
  }
  const result = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e",
    'import {useScheduler} from "./.sandcastle/scheduler-config.mts"; useScheduler("fixture",["mainModel","claimPollSeconds"]);'],
    { encoding: "utf8", env: { ...process.env, CLAIM_LOOP_POLL_SECONDS: "71", SECRET_TEST: "do-not-log-secret" } });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /mainModel="gpt-6.1-sol" source=record:1/);
  assert.match(result.stderr, /claimPollSeconds=71 source=env:CLAIM_LOOP_POLL_SECONDS/);
  assert.doesNotMatch(result.stdout + result.stderr, /do-not-log-secret/);
});
test("#1606 C-29/C-30 入口不新增绕开配置记录的调度常量", () => {
  const entries = [
    "main.mts", "main-swarm.mts", "main-model.mts", "codex-child.ts", "codex-child.mts",
    "decision-claimer.mts", "claim-loop.mts", "health-monitor.mts",
  ];
  // 逐字面量豁免；位置不绑定行号，每项只抵扣一次命中。
  const exceptions = new Map([
    ['codex-child.ts:EXTERNAL_REVIEW_MODELS="kimi-k3.1-pro"', "#1742 外审准入名单，与 external_review.py 的 MODELS 由测试对拍"],
    ['codex-child.ts:EXTERNAL_REVIEW_MODELS="claude-opus-5-5"', "#1742 外审准入名单，与 external_review.py 的 MODELS 由测试对拍"],
    ['codex-child.ts:PROMPT_JSON_MODELS="kimi-k3.1-pro"', "#1968 指定模型走提示词 JSON 的协议兼容表，不选调度模型"],
    ["decision-claimer.mts:MIN_MODEL_ATTEMPTS=5", "#1547 首次加至少四次重试的政策下限，可调总次数来自 decisionMaxAttempts"],
  ]);
  // 匹配完整模型 ID，不把路由前缀、入口标签、路径或环境变量名当作模型。
  const modelId = /^(?:(?:gpt|gemini|claude)-|claude-(?:opus|sonnet|haiku)-|kimi-k?|deepseek-v?|o(?=[134]))\d+(?:\.\d+)*(?:-[a-z0-9]+)*$/i;
  const isNumericConstant = (expression: ts.Expression): boolean => {
    const value = ts.skipOuterExpressions(expression);
    if (ts.isNumericLiteral(value)) return true;
    if (ts.isPrefixUnaryExpression(value)) {
      return (value.operator === ts.SyntaxKind.PlusToken || value.operator === ts.SyntaxKind.MinusToken)
        && isNumericConstant(value.operand);
    }
    return ts.isBinaryExpression(value) && /^(?:[+*/%-]|\*\*)$/.test(ts.tokenToString(value.operatorToken.kind) ?? "")
      && isNumericConstant(value.left) && isNumericConstant(value.right);
  };

  const failures: string[] = [];
  const projectPath = fileURLToPath(new URL("../tsconfig.sandcastle.json", import.meta.url));
  const api = new API({ cwd: dirname(projectPath) });
  try {
    const snapshot = api.updateSnapshot({ openProjects: [projectPath] });
    try {
      const project = snapshot.getProject(projectPath);
      assert.ok(project, projectPath);
      for (const file of entries) {
        const source = project.program.getSourceFile(fileURLToPath(new URL(file, import.meta.url)));
        assert.ok(source, `.sandcastle/${file} 未纳入扫描`);
        const report = (node: ts.Node, name: string, literal: string) => {
          const hit = name ? `${name}=${literal}` : literal;
          if (exceptions.delete(`${file}:${hit}`)) return;
          const { line } = source.getLineAndCharacterOfPosition(ts.getTokenPosOfNode(node, source));
          failures.push(`.sandcastle/${file}:${line + 1}: ${hit}`);
        };
        const scan = (node: ts.Node, binding = "") => {
          if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) {
            binding = node.name.text;
            if ((node.parent.flags & ts.NodeFlags.Const) && /^[A-Z][A-Z_0-9]*$/.test(binding) && node.initializer) {
              const value = ts.skipOuterExpressions(node.initializer);
              if (isNumericConstant(value) || (ts.isArrayLiteralExpression(value) && value.elements.length > 0
                  && value.elements.every(isNumericConstant))) {
                report(value, binding, source.text.slice(ts.getTokenPosOfNode(value, source), value.end));
              }
            }
          }
          if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && modelId.test(node.text)) {
            report(node, binding, JSON.stringify(node.text));
          }
          node.forEachChild(child => scan(child, binding));
        };
        scan(source);
      }
    } finally {
      snapshot.dispose();
    }
  } finally {
    api.close();
  }
  for (const key of exceptions.keys()) failures.push(`删除已失效的豁免：${key}`);
  assert.equal(failures.join("\n"), "", "#1606 请读取版本化配置，或按票号说明为何是固定协议");
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
  const run = (timeout: string) => spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e", code],
    {encoding: "utf8", env: {...process.env, SANDCASTLE_DOCKER_CLI_TIMEOUT_MS: timeout}});
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
