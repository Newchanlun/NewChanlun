import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { MaintenanceOwner, MaintenanceClosed, maintenanceResource } from "./maintenance.mts";

const helper = fileURLToPath(new URL("./deepagents-pilot/pilot1742/maintenance.py", import.meta.url));
function control(root: string, command: string, ...args: string[]) {
  return JSON.parse(execFileSync("python3", [helper, "--root", root, command, ...args], { encoding: "utf8" }));
}

test("TS 已领取回调完整运行，Python 关闸挡住下一工作；已返回普通失败不占在途", async () => {
  const root = mkdtempSync(join(tmpdir(), "maintenance-ts-"));
  try {
    const owner = new MaintenanceOwner("decision", root);
    let release!: () => void;
    const barrier = new Promise<void>(resolve => { release = resolve; });
    const calls: string[] = [];
    const work = owner.work("ticket:1742", async () => {
      calls.push("first-request");
      await barrier;
      calls.push("later-request");
      return 42;
    });
    const closed = control(root, "request");
    assert.equal(closed.generation, 1);
    assert.equal(closed.inflight.length, 1);
    await assert.rejects(owner.work("ticket:1743", () => calls.push("forbidden")), MaintenanceClosed);
    release();
    assert.equal(await work, 42);
    assert.deepEqual(calls, ["first-request", "later-request"]);
    assert.equal(control(root, "status").inflight.length, 0);
    control(root, "resume", "--generation", "1");
    await assert.rejects(owner.work("ticket:1744", () => { throw new Error("fixture"); }));
    assert.equal(control(root, "status").inflight.length, 0);
    await assert.rejects(owner.work("ticket:1745", () => {
      const closed = maintenanceResource();
      closed(false);
      throw new Error("child cleanup unverified");
    }));
    assert.equal(control(root, "status").inflight[0].state, "unknown");
    owner.stop();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("缺少其它入口确认，单个 TS owner 不能报告 drained", () => {
  const root = mkdtempSync(join(tmpdir(), "maintenance-ts-"));
  try {
    const owner = new MaintenanceOwner("wayfinder", root);
    control(root, "request");
    assert.equal(owner.poll(), true);
    const report = control(root, "status");
    assert.equal(report.state, "unknown");
    assert.ok(report.unconfirmed.includes("executor"));
    owner.stop();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("关闸使一个池工作拒绝时，池仍等其它已领取工作结束", async () => {
  const { runPool } = await import("./decision-claimer.mts");
  let release!: () => void;
  const barrier = new Promise<void>(resolve => { release = resolve; });
  let finished = false;
  let returned = false;
  const running = runPool([1, 2], 2, async n => {
    if (n === 1) throw new MaintenanceClosed();
    await barrier;
    finished = true;
  }).catch(() => { returned = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(returned, false);
  release();
  await running;
  assert.equal(finished, true);
});


test("runPool 关闸保留同轮已完成结果，停止领取后续票", async () => {
  const { runPool } = await import("./decision-claimer.mts");
  const seen: number[] = [];
  const results = await runPool([1, 2, 3], 1, async n => {
    seen.push(n);
    if (n === 2) throw new MaintenanceClosed();
    return n;
  });
  assert.deepEqual(seen, [1, 2]);
  assert.deepEqual(results, [1]);
});

// 原 822 反例：真实 sleep 超时，迁移到生产同一监督入口，不把 close 当成资源证明。
test("同 boot 的 decision/Wayfinder 超时 wait + session 清空后释放，业务仍失败", async () => {
  const { spawn } = await import("node:child_process");
  const { maintenanceCommand } = await import("./maintenance.mts");
  const root = mkdtempSync(join(tmpdir(), "maintenance-timeout-"));
  const churn = spawn("python3", ["-c", `import signal,subprocess
running=True
def stop(*_):
    global running
    running=False
signal.signal(signal.SIGTERM,stop)
print('ready',flush=True)
while running:
    subprocess.run(['/bin/sleep','0.003'],check=True)
`], { stdio: ["ignore", "pipe", "inherit"] });
  await new Promise<void>((resolve, reject) => {
    churn.once("error", reject);
    churn.stdout.once("data", () => resolve());
  });
  try {
    const stderr: string[] = [];
    for (const lane of ["decision", "wayfinder"] as const) {
      const owner = new MaintenanceOwner(lane, root);
      const result = await owner.work("isolated-timeout", () => new Promise<number>((resolve, reject) => {
        const command = maintenanceCommand("/bin/sh", ["-c", "printf ready; exec /bin/sleep 30"]);
        const child = spawn(command.file, command.args, { stdio: ["ignore", "pipe", "pipe"] });
        child.stderr.on("data", data => stderr.push(String(data)));
        child.stdout.once("data", () => setTimeout(() => child.kill("SIGTERM"), 20));
        child.once("error", reject);
        child.once("close", code => resolve(code!));
      }));
      assert.equal(result, 143, stderr.join(""));
      owner.stop();
    }
    const report = control(root, "status");
    const evidence = execFileSync("python3", ["-c", "import sqlite3,sys,json; d=sqlite3.connect(sys.argv[1]); d.row_factory=sqlite3.Row; print(json.dumps({t:[dict(r) for r in d.execute('SELECT * FROM '+t)] for t in ['local_resources','local_resource_diagnostics']}))", join(root, "maintenance.sqlite3")], {encoding:"utf8"});
    assert.equal(report.inflight.length, 0, JSON.stringify({report, stderr, evidence}));
  } finally {
    await new Promise<void>(resolve => {
      churn.once("close", () => resolve());
      churn.kill("SIGTERM");
    });
    rmSync(root, { recursive: true, force: true });
  }
});

for (const failedRpc of ["action-exited", "finish"]) test(`收尾 RPC ${failedRpc} 丢失后，同 key 新回调不能借旧许可跨关闸派发`, async () => {
  const root = mkdtempSync(join(tmpdir(), "maintenance-rpc-"));
  try {
    const owner = new MaintenanceOwner("decision", root);
    const rpc = owner as unknown as { call: (command: string, args?: string[]) => Record<string, unknown> };
    const original = rpc.call.bind(owner);
    rpc.call = (command, args) => {
      if (command === failedRpc) throw new Error("injected receipt loss");
      return original(command, args);
    };
    let requests = 0;
    const summary = {ticket:1742, phase:"business-result"};
    assert.equal(await owner.work("ticket:1742", () => { requests++; return summary; }), summary);
    const businessError = new Error("business failure");
    await assert.rejects(owner.work("ticket:1743", () => { throw businessError; }), e => e === businessError);
    control(root, "request");
    rpc.call = original;
    await assert.rejects(owner.work("ticket:1742", () => { requests++; }), MaintenanceClosed);
    assert.equal(requests, 1);
    assert.equal(control(root, "status").inflight.length, 2);
    owner.stop();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("显式 ES 入口缺可信配置拒绝且不回退；未派发证据不伪造业务 wait", async () => {
  const { maintenanceCommand } = await import("./maintenance.mts");
  const { spawnSync } = await import("node:child_process");
  const root = mkdtempSync(join(tmpdir(), "maintenance-es-selection-"));
  try {
    const owner = new MaintenanceOwner("decision", root, join(root, "missing-managed-config"));
    const result = await owner.work("es-selection", () => {
      const command = maintenanceCommand("/bin/sh", ["-c", "exit 42"]);
      assert.ok(command.args.includes("--es-config"));
      return spawnSync(command.file, command.args, { encoding: "utf8" });
    });
    assert.equal(result.status, 78);
    assert.match(result.stderr, /native ES source unavailable/);
    assert.equal(control(root, "status").inflight.length, 0);
    owner.stop();
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("调度器进程退出再创建 owner，同票旧动作未结清不能新派发", async () => {
  const root = mkdtempSync(join(tmpdir(), "maintenance-restart-"));
  try {
    const moduleUrl = new URL("./maintenance.mts", import.meta.url).href;
    const program = `import {MaintenanceOwner,maintenanceCommand} from ${JSON.stringify(moduleUrl)};
const owner=new MaintenanceOwner('decision',process.argv[1]);
await owner.work('ticket:2063',()=>{maintenanceCommand('unused',[]);process.exit(0)});`;
    execFileSync(process.execPath, ["--import", "tsx", "--input-type=module", "-e", program, root]);
    const replacement = new MaintenanceOwner("decision", root);
    let dispatches = 0;
    await assert.rejects(replacement.work("ticket:2063", () => { dispatches++; }));
    assert.equal(dispatches, 0);
    assert.equal(control(root, "status").inflight.length, 1);
    assert.equal(await replacement.work("ticket:2064", () => 42), 42);
    replacement.stop();
  } finally { rmSync(root, {recursive:true,force:true}); }
});
