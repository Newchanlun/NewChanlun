import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { DEEPAGENTS_OUTPUT_PROTOCOL, workerOutputSchema } from "./codex-child.ts";

const valid = { status: "completed", summary: "已核查", findings: [], validation: ["离线"], confidence: "high", caveats: [] };
const legacy = { status: "completed", summary: "旧协议", findings: [], validation: [] };
const cases = [
  { name: "Kimi 六键成功", output: valid, success: true },
  { name: "Kimi blocked 终态", output: { ...valid, status: "blocked" }, result: true },
  { name: "Kimi failed 终态", output: { ...valid, status: "failed" }, result: true },
  { name: "六键协议拒绝四键", output: legacy },
  { name: "拒绝多余键", output: { ...valid, extra: true } },
  { name: "拒绝错误类型", output: { ...valid, caveats: "none" } },
  { name: "拒绝非 JSON", text: "正在开始工作" },
  { name: "拒绝缺失完成事件", output: valid, incomplete: true },
  { name: "拒绝失败事件", output: valid, failed: true },
  { name: "拒绝非零退出", output: valid, exit: 1 },
  { name: "拒绝模型漂移", output: valid, actual: "claude-opus-5-5" },
  { name: "历史四键协议", output: legacy, protocol: "legacy", success: true },
  { name: "Opus 保留 schema", output: valid, model: "claude-opus-5-5", success: true },
];

for (const sample of cases) test(sample.name, () => {
  const dir = mkdtempSync(join(tmpdir(), "boat-protocol-"));
  try {
    const root = join(dir, "package"), repo = join(root, "repo"), claim = join(root, "claim");
    mkdirSync(repo, { recursive: true }); mkdirSync(claim); mkdirSync(join(dir, "private"));
    const git = (...args: string[]) => execFileSync("git", ["-C", repo, ...args], { encoding: "utf8" }).trim();
    git("init", "-q", "-b", "main");
    writeFileSync(join(repo, "README"), "fixture\n"); git("add", ".");
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture");
    const head = git("rev-parse", "HEAD"), model = sample.model ?? "kimi-k3.1-pro";
    const events = [
      { type: "thread.started", thread_id: "fixture-session" },
      { type: "item.completed", item: { type: "agent_message", text: sample.text ?? JSON.stringify(sample.output) } },
      ...(!sample.incomplete ? [{ type: sample.failed ? "turn.failed" : "turn.completed" }] : []),
    ];
    const fixture = { root, events, exit: sample.exit ?? 0, actual: sample.actual ?? model };
    writeFileSync(join(dir, "private/model-key"), "fixture-only");
    const request = { root, model, mode: "execute", ticket: 1911, image: "sha256:" + "a".repeat(64),
      endpoint: "https://fixture.invalid/v1", identity: { run_id: "t1911-1", target_head: head },
      package_id: "fixture", allowed_prefixes: ["demo/"], prompt: "完成离线任务",
      ...(sample.protocol === "legacy" ? {} : { output_protocol: DEEPAGENTS_OUTPUT_PROTOCOL }) };
    writeFileSync(join(root, "request.json"), JSON.stringify(request));
    // 只替换容器边界：保留真实 Sandcastle buildPrintCommand、CodexTranscript 和结果消费。
    const docker = `import {writeFileSync} from 'node:fs';
      const f = ${JSON.stringify(fixture)};
      export const docker = () => ({create: async () => ({
        copyFileIn: async () => {},
        copyFileOut: async (source, target) => writeFileSync(target, source === '/tmp/newchanlun-exit'
          ? String(f.exit) : JSON.stringify({type:'turn_context', payload:{model:f.actual}})+'\\n'),
        exec: async (command, options) => {
          if (!options?.onLine) return {exitCode:0, stdout:'/sessions/fixture-session.jsonl\\n'};
          writeFileSync(f.root+'/observed.json', JSON.stringify({command, stdin:options.stdin}));
          for (const event of f.events) options.onLine(JSON.stringify(event));
          return {exitCode:f.exit, stdout:''};
        },
        close: async () => writeFileSync(f.root+'/closed', 'yes'),
      })});`;
    const modules = {
      "@ai-hero/sandcastle/sandboxes/docker": docker,
      "./docker-isolation.mts": "export const assertContainerIsolationContract = () => ({}); export const hardenProvider = x => x;",
    };
    const loader = join(dir, "loader.mjs");
    writeFileSync(loader, `import {registerHooks} from 'node:module'; const modules=${JSON.stringify(modules)};
      registerHooks({resolve(s,c,next) {return c.parentURL?.endsWith('/boat-worker.mts') && s in modules
        ? {url:'data:text/javascript,'+encodeURIComponent(modules[s]),shortCircuit:true} : next(s,c)}});`);
    const child = spawnSync(process.execPath, ["--import", "tsx", "--import", loader,
      resolve(".sandcastle/boat-worker.mts"), join(root, "request.json")], { encoding: "utf8", timeout: 15000 });
    assert.equal(child.status, 0, child.stderr);
    const observed = JSON.parse(readFileSync(join(root, "observed.json"), "utf8"));
    assert.match(observed.command, /--disable multi_agent/);
    assert.match(observed.command, new RegExp(model.replaceAll(".", "\\.")));
    const receipt = JSON.parse(readFileSync(join(claim, "receipt.json"), "utf8"));
    if (model === "kimi-k3.1-pro") {
      assert.doesNotMatch(observed.command, /--output-schema/);
      const schema = JSON.parse(observed.stdin.split("：\n").at(-1));
      assert.deepEqual(schema, workerOutputSchema(sample.protocol === "legacy" ? "legacy" : DEEPAGENTS_OUTPUT_PROTOCOL));
      assert.equal(receipt.record.output_contract, "prompt");
    } else {
      assert.match(observed.command, /--output-schema \/tmp\/output.schema.json/);
      assert.equal(receipt.record.output_contract, "schema");
    }
    assert.equal(receipt.state, "terminal");
    assert.equal(receipt.record.status, sample.success ? "completed" : "failed");
    if (sample.success || sample.result) assert.deepEqual(receipt.record.result, sample.output);
    else assert.ok(receipt.record.failure_reason);
    assert.deepEqual(receipt.files, []);
    assert.equal(readFileSync(join(root, "closed"), "utf8"), "yes");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
