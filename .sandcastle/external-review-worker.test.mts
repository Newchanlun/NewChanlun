import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import { codexWorker } from "./codex-route.mts";
import { PROMPT_JSON_INSTRUCTION, REVIEW_IMAGE, REVIEW_VOLUME_LABEL, VM_SPACE_RESERVE, VOLUME_SNAPSHOT, checkReviewAdmission, dockerReviewVolumes, rateLimitSignal, readLaunch, reviewMounts, reviewSandbox, reviewVolumeName, runExternalReview, snapshot, verifyReviewAdmission, withVolumeAdmissionLock, type ReviewLaunch, type ReviewVolumes, type WorkerDependencies } from "./external-review-worker.mts";
import type { BindMountSandboxHandle } from "@ai-hero/sandcastle";

const image = "sha256:" + "1".repeat(64);
const container = "a".repeat(64);
function fixture(model = "gpt-6.1-sol") {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "external-review-test-")));
  const checkout = join(root, "source"), folder = join(root, "receipt");
  mkdirSync(checkout); mkdirSync(folder);
  const git = (...args: string[]) => execFileSync("git", ["-C", checkout, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  git("init", "-q"); git("-c", "user.name=Fixture", "-c", "user.email=f@example.invalid", "commit", "--allow-empty", "-qm", "base");
  git("checkout", "--detach", "-q");
  const head = git("rev-parse", "HEAD");
  const launch: ReviewLaunch = { run_id: randomUUID(), launch_id: randomUUID(), pr_number: 1810, model,
    head_sha: head, base_sha: head, merge_base_sha: head, controller_code_head: "b".repeat(40), checkout, prompt: "完整 PR 独审", mode: "review" };
  writeFileSync(join(folder, "launch.json"), JSON.stringify(launch), { mode: 0o600 });
  return { root, checkout, folder, launch };
}

/** 替身审阅卷：populate 记下灌入来源；卷的 Git 读取按该宿主 checkout 作答（卷内容 = 灌入时的 checkout）。 */
function fakeVolumes(options: { removeFails?: boolean; mismatch?: boolean } = {}) {
  const calls: string[] = [];
  let checkout = "";
  const volumes: ReviewVolumes = {
    populate(volume, img, source, launchId) { checkout = source; calls.push(`populate ${volume} ${img} ${source} ${launchId}`); },
    snapshot(volume, img, launchId) {
      assert.equal(img, image); assert.equal(volume, reviewVolumeName(launchId));
      return options.mismatch ? { head: "f".repeat(40), branch: "HEAD", status: "" } : snapshot(checkout);
    },
    remove(volume) { calls.push(`remove ${volume}`); if (options.removeFails) throw new Error("volume in use"); },
  };
  return { calls, volumes };
}
const volumeMount = (launch: ReviewLaunch, rw = false) =>
  ({ Type: "volume", Name: reviewVolumeName(launch.launch_id), Source: `/var/lib/docker/volumes/${reviewVolumeName(launch.launch_id)}/_data`, Destination: "/review", RW: rw });

test("review 挂载只接受本次 launch 的只读审阅卷，不接受宿主路径", () => {
  const f = fixture();
  try {
    const volume = reviewVolumeName(f.launch.launch_id);
    assert.deepEqual(reviewMounts(volume), [{ hostPath: volume, sandboxPath: "/review", readonly: true }]);
    assert.throws(() => reviewMounts(f.checkout));
    assert.throws(() => reviewMounts("newchanlun-external-review-../x"));
    assert.throws(() => reviewVolumeName("../../etc"));
    assert.equal(readLaunch(f.folder).model, "gpt-6.1-sol");
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

test("审阅 provider 拒绝宿主 bind mount、可写卷与多挂载，并校验镜像 Id", async () => {
  const volume = reviewVolumeName(randomUUID());
  assert.throws(() => reviewSandbox("sandcastle:newchanlun", {}), /sha256/);
  const sandbox = reviewSandbox(image, {});
  for (const mounts of [[{ hostPath: "/Volumes/AgentStorage/checkout", sandboxPath: "/review", readonly: true }],
    [{ hostPath: volume, sandboxPath: "/review", readonly: false }],
    [{ hostPath: volume, sandboxPath: "/review", readonly: true }, { hostPath: "/tmp", sandboxPath: "/host", readonly: true }],
    [{ hostPath: volume, sandboxPath: "/elsewhere", readonly: true }]]) {
    assert.throws(() => sandbox.create({ worktreePath: mounts[0]!.hostPath, hostRepoPath: "/x", mounts, env: {} }), /只读审阅卷/);
  }
});

test("审阅卷先核 VM 磁盘，再经 docker cp 灌入（不经 bind mount）、改属主；容器与卷都带 launch 标签；已存在的卷不复用", () => {
  const launchId = randomUUID(); const volume = reviewVolumeName(launchId);
  const label = ["--label", `${REVIEW_VOLUME_LABEL}=${launchId}`];
  const calls: string[][] = [];
  let present = false, availableKb = 100 * 1024 * 1024, holders = "";
  const run = (args: string[]) => {
    calls.push(args);
    if (args[0] === "run" && args.includes("/bin/df")) return `Filesystem 1024-blocks Used Available Capacity Mounted on\noverlay 102400000 1 ${availableKb} 1% /`;
    if (args[0] === "volume" && args[1] === "inspect") { if (!present) throw new Error("no such volume"); return "[]"; }
    if (args[0] === "create") return "c".repeat(64);
    if (args[0] === "inspect") return "0";
    if (args[0] === "ps") return holders;
    if (args[0] === "run") return "a".repeat(40) + "\nHEAD\n M x";
    return "";
  };
  const checkoutKb = 1024 * 1024;  // 1 GiB
  const lockRoot = mkdtempSync(join(tmpdir(), "volume-lock-"));
  const lockFor = () => join(lockRoot, "lock");
  dockerReviewVolumes(run, () => checkoutKb, lockFor).populate(volume, image, "/checkouts/run/model", launchId);
  const owner = `${process.getuid!()}:${process.getgid!()}`;
  assert.deepEqual(calls, [
    ["run", "--rm", "--network", "none", ...label, "--entrypoint", "/bin/df", image, "-Pk", "/"],
    ["volume", "inspect", volume],
    ["volume", "create", ...label, volume],
    ["create", "--network", "none", ...label, "--user", "0:0", "-v", `${volume}:/review`, "--entrypoint", "chown", image, "-R", "-h", owner, "/review"],
    ["cp", "/checkouts/run/model/.", `${"c".repeat(64)}:/review`],
    ["start", "-a", "c".repeat(64)],
    ["inspect", "--format", "{{.State.ExitCode}}", "c".repeat(64)],
    ["rm", "-f", "c".repeat(64)],
  ]);
  // 只有辅助容器挂卷，且不带任何宿主路径挂载。
  assert(calls.every((a) => !a.includes("-v") || a[a.indexOf("-v") + 1] === `${volume}:/review`));
  // VM 磁盘不够「checkout + 2 GiB」就不建卷。
  calls.length = 0; availableKb = checkoutKb + VM_SPACE_RESERVE / 1024 - 1;
  assert.throws(() => dockerReviewVolumes(run, () => checkoutKb, lockFor).populate(volume, image, "/checkouts/run/model", launchId), /VM 磁盘空间不足/);
  assert.equal(calls.length, 1);
  availableKb = 100 * 1024 * 1024;
  present = true; calls.length = 0;
  assert.throws(() => dockerReviewVolumes(run, () => checkoutKb, lockFor).populate(volume, image, "/checkouts/run/model", launchId), /已存在/);
  assert.deepEqual(calls.map((a) => a.slice(0, 2)), [["run", "--rm"], ["volume", "inspect"]]);
  // 快照在一次性容器里只读挂卷执行，不经审查员容器；脚本只用绝对路径的 env 与 git。
  calls.length = 0;
  assert.deepEqual(dockerReviewVolumes(run).snapshot(volume, image, launchId), { head: "a".repeat(40), branch: "HEAD", status: "M x" });
  assert.deepEqual(calls, [["run", "--rm", "--network", "none", ...label, "--user", owner, "-v", `${volume}:/review:ro`,
    "--entrypoint", "/bin/sh", image, "-c", VOLUME_SNAPSHOT]]);
  assert.doesNotMatch(VOLUME_SNAPSHOT.replaceAll("/usr/bin/env", "").replaceAll("/usr/bin/git", ""), /\b(env|git) /);
  // 删卷先删仍引用它的容器（Sandcastle close 吞错、残留的辅助容器），再删卷。
  calls.length = 0; holders = "d1\nd2";
  dockerReviewVolumes(run).remove(volume);
  assert.deepEqual(calls, [["ps", "-a", "-q", "--filter", `volume=${volume}`], ["rm", "-f", "d1"], ["rm", "-f", "d2"], ["volume", "rm", volume]]);
  assert.throws(() => dockerReviewVolumes(run).remove("/Volumes/AgentStorage"));
  assert.deepEqual(readdirSync(lockRoot).filter((f) => f.endsWith(".acquired")), [], "成功与失败后都放锁");
  rmSync(lockRoot, { recursive: true, force: true });
});

/** 监督子进程：withVolumeAdmissionLock 包住 body。mode=hold 拿到锁后写 held 并一直持有（等父进程 SIGKILL，模拟崩溃）；
 *  mode=populate 共享一个替身 VM（文件里记可用 KB，docker cp 扣减），按「checkout + 2 GiB」准入。 */
function writeChild(root: string, checkoutKb: number): string {
  const child = join(root, "child.mts");
  writeFileSync(child, `
    import { readdirSync, readFileSync, writeFileSync } from "node:fs";
    import { dirname, join } from "node:path";
    const w = await import(${JSON.stringify(pathToFileURL(join(import.meta.dirname, "external-review-worker.mts")).href)});
    const [mode, vm, lock, launchId, starters] = process.argv.slice(2);
    const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
    if (mode === "hold") {
      w.withVolumeAdmissionLock(lock, () => { writeFileSync(join(dirname(vm), "held"), ""); for (;;) sleep(1000); });
    }
    // 起跑线：所有等待者都加载完才开始，免得启动快慢不一把竞态窗口错开。
    writeFileSync(join(dirname(vm), "ready-" + launchId), "");
    while (readdirSync(dirname(vm)).filter((f) => f.startsWith("ready-")).length < Number(starters)) sleep(10);
    const run = (args) => {
      if (args.includes("/bin/df")) return "Filesystem 1024-blocks Used Available Capacity Mounted on\\noverlay 1 1 " + readFileSync(vm, "utf8") + " 1% /";
      if (args[0] === "volume" && args[1] === "inspect") throw new Error("no such volume");
      if (args[0] === "create") return "c".repeat(64);
      if (args[0] === "inspect") return "0";
      if (args[0] === "cp") { sleep(400); writeFileSync(vm, String(Number(readFileSync(vm, "utf8")) - ${checkoutKb})); }
      return "";
    };
    try {
      w.dockerReviewVolumes(run, () => ${checkoutKb}, () => lock).populate(w.reviewVolumeName(launchId), "${image}", "/x/run/model", launchId);
      console.log("admitted");
    } catch (e) { console.log(/VM 磁盘空间不足/.test(String(e)) ? "refused" : "error " + e); }
  `);
  return child;
}
const spawnChild = (root: string, child: string, args: string[]) =>
  spawn(process.execPath, ["--import", "tsx", child, ...args], { cwd: dirname(import.meta.dirname), stdio: ["ignore", "pipe", "inherit"] });
const output = (proc: ReturnType<typeof spawnChild>) => new Promise<string>((done, fail) => {
  let out = ""; proc.stdout!.on("data", (c) => { out += c; });
  proc.on("error", fail); proc.on("close", () => done(out.trim()));
});
const waitFor = async (path: string) => { while (!existsSync(path)) await new Promise((r) => setTimeout(r, 20)); };

/** n 个监督同时灌卷，可用空间只够一份卷加余量。crashedHolder：先让一个持锁进程在所有等待者都排上队后被 SIGKILL，
 *  即 kimi 在 55e81cec 上说的「多个等待者同时撞上同一把陈旧锁」。 */
async function racePopulate(n: number, sharedLock: boolean, crashedHolder = false): Promise<string[]> {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "volume-race-")));
  try {
    const vm = join(root, "vm-available-kb");
    const checkoutKb = 2.5 * 1024 * 1024;  // 2.5 GiB：各需 4.5 GiB，可用 5 GiB 只够一份（kimi 在 68e4778e 上的反例）
    writeFileSync(vm, String(5 * 1024 * 1024));
    const child = writeChild(root, checkoutKb);
    const lockOf = (i: number) => join(root, sharedLock ? "lock" : `lock-${i}`);
    const holder = crashedHolder ? spawnChild(root, child, ["hold", vm, lockOf(0), randomUUID(), "0"]) : undefined;
    if (holder) await waitFor(join(root, "held"));
    const waiters = Array.from({ length: n }, (_, i) => output(spawnChild(root, child, ["populate", vm, lockOf(i), randomUUID(), String(n)])));
    if (holder) {
      while (readdirSync(root).filter((f) => f.startsWith("ready-")).length < n) await new Promise((r) => setTimeout(r, 20));
      await new Promise((r) => setTimeout(r, 300));  // 等待者都已在锁上排队
      holder.kill("SIGKILL");
    }
    return (await Promise.all(waiters)).sort();
  } finally { rmSync(root, { recursive: true, force: true }); }
}

test("并发灌卷：可用空间只够一份时只有一份通过准入（跨进程准入锁）；不共用锁时都过，证明这道竞态真实存在", async () => {
  assert.deepEqual(await racePopulate(2, true), ["admitted", "refused"]);
  assert.deepEqual(await racePopulate(2, false), ["admitted", "admitted"]);
});

test("持锁进程被 SIGKILL 后，三个同时排队的等待者里只有一个拿到空间，没有两个按同一份余量通过", async () => {
  assert.deepEqual(await racePopulate(3, true, true), ["admitted", "refused", "refused"]);
});

test("准入锁：持有者活着时后来者等到超时，超时不释放别人的锁；body 抛错也放锁；锁文件从不删除", async () => {
  const root = realpathSync(mkdtempSync(join(tmpdir(), "volume-lock-")));
  try {
    const lock = join(root, "lock");
    const vm = join(root, "vm-available-kb");
    const holder = spawnChild(root, writeChild(root, 1), ["hold", vm, lock, randomUUID(), "0"]);
    await waitFor(join(root, "held"));
    assert.throws(() => withVolumeAdmissionLock(lock, () => "ran", 300), /准入锁超时/);
    assert.throws(() => withVolumeAdmissionLock(lock, () => "ran", 300), /准入锁超时/, "前一个超时的等待者没有放掉持有者的锁");
    holder.kill("SIGKILL");
    await new Promise((r) => holder.on("close", r));
    assert.equal(withVolumeAdmissionLock(lock, () => "ran", 10_000), "ran", "持有者崩溃后内核释放锁");
    assert.throws(() => withVolumeAdmissionLock(lock, () => { throw new Error("body failed"); }), /body failed/);
    assert.equal(withVolumeAdmissionLock(lock, () => "again", 2000), "again", "body 抛错也放锁");
    assert(existsSync(lock), "锁文件从不删除，放锁只是结束自己的持有进程");
    assert.deepEqual(readdirSync(root).filter((f) => f.endsWith(".acquired") && f.includes(`.${process.pid}.`)), [], "本进程的信号文件都已清掉");
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("显式两家族模型保留旧默认并拒绝路由外模型", () => {
  for (const model of ["gpt-6.1-sol", "claude-opus-5-5"] as const) {
    const a = codexWorker({ docker: true, model });
    const b = codexWorker({ docker: true, model });
    const options = { prompt: "只审不修", dangerouslySkipPermissions: false };
    const command = a.buildPrintCommand(options);
    assert.match(command.command, new RegExp(model));
    assert.match(command.command, /host.docker.internal:8318/);
    assert.doesNotMatch(command.command, /--skip-git-repo-check/);
    assert.notEqual(command.command, b.buildPrintCommand(options).command);
    assert.equal(command.stdin, options.prompt);
  }
  assert.throws(() => codexWorker({ docker: true, model: "other" as never }));
  assert.throws(() => verifyReviewAdmission({ imageId: image, consume() {} }));
});

const modes = ["PASS", "BLOCK", "failed", "missing-log", "missing-completed", "write", "bad-mount", "bind-mount", "volume-mismatch",
  "volume-remove-fails", "secret-env", "bad-filesystem",
  "over-budget", "over-budget-reject", "timeout-reject", "rate-limited-hang", "rate-limited-final", "rate-limited-exit", "rate-limited-stderr",
  "reconnect-429-recovers"] as const;
const RECONNECT_429 = "Reconnecting... 1/5 (exceeded retry limit, last status: 429 Too Many Requests)";
for (const [mode, model] of [...modes.map((m) => [m, "gpt-6.1-sol"] as const),
  ["PASS", "kimi-k3.1-pro"], ["BLOCK", "kimi-k3.1-pro"], ["PASS", "claude-opus-5-5"]] as const) {
  test(`宿主监督 ${model} ${mode} 不把缺证据转为通过`, async () => {
    const f = fixture(model); const session = randomUUID();
    const schemaless = model === "kimi-k3.1-pro";
    let closed = false, creates = 0;
    let modelCommand = "";
    const fake = fakeVolumes({ removeFails: mode === "volume-remove-fails", mismatch: mode === "volume-mismatch" });
    const volume = reviewVolumeName(f.launch.launch_id);
    const output = { status: mode === "BLOCK" ? "blocked" : "completed", summary: `VERDICT: ${mode}`, findings: [], validation: [] };
    const handle: BindMountSandboxHandle = {
      worktreePath: "/review",
      async exec(command, options) {
        if (command === "cat /etc/hostname") return { stdout: container.slice(0, 12), stderr: "", exitCode: 0 };
        if (command.startsWith("node -e ")) return { stdout: JSON.stringify({ source_write: mode === "bad-filesystem" ? "ALLOWED" : "EROFS", git_write: "EROFS", host_read: "ENOENT", state_write: "ENOENT" }), stderr: "", exitCode: 0 };
        if (command.includes("find ")) {
          const sessionsDir = JSON.parse(command.match(/^find (".*?") /)![1]!);
          return { stdout: `${sessionsDir}/2026/10/29/rollout-2026-10-29-${session}.jsonl\n`, stderr: "", exitCode: 0 };
        }
        modelCommand = command;
        assert.equal(command.includes("--output-schema"), !schemaless);
        assert(command.includes("--disable multi_agent"));
        assert.equal(options?.stdin, schemaless ? f.launch.prompt + PROMPT_JSON_INSTRUCTION : f.launch.prompt);
        if (mode === "timeout-reject") {
          // 真实 SDK 在容器被关后可能让 exec reject：等超时关容器，再以传输异常结束。
          while (!closed) await new Promise((r) => setTimeout(r, 5));
          throw new Error("container closed");
        }
        if (mode === "rate-limited-hang" || mode === "rate-limited-final") {
          // hang：#1920/#1921/#1935 实测，1/5 的 429 重连后 stdout 不再有输出，进程挂着直到被关停（等静默窗口）。
          // final：最后一次重连 5/5 仍是 429，立即停。
          const message = mode === "rate-limited-final" ? RECONNECT_429.replace("1/5", "5/5") : RECONNECT_429;
          for (const e of [{ type: "thread.started", thread_id: session }, { type: "turn.started" },
            { type: "error", message }]) options?.onLine?.(JSON.stringify(e));
          while (!closed) await new Promise((r) => setTimeout(r, 5));
          throw new Error("container closed");
        }
        if (mode === "rate-limited-exit") {
          const message = "exceeded retry limit, last status: 429 Too Many Requests";
          for (const e of [{ type: "thread.started", thread_id: session }, { type: "turn.started" },
            { type: "error", message }, { type: "turn.failed", error: { message } }]) options?.onLine?.(JSON.stringify(e));
          return { stdout: "", stderr: "", exitCode: 1 };
        }
        if (mode === "rate-limited-stderr") {
          options?.onLine?.(JSON.stringify({ type: "thread.started", thread_id: session }));
          return { stdout: "", stderr: "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n", exitCode: 1 };
        }
        if (mode === "reconnect-429-recovers") {
          // #1942 实测：1/5 的 429 重连后继续产出事件。事件间隔短于静默窗口，总时长超过它，也不能被提前停。
          options?.onLine?.(JSON.stringify({ type: "thread.started", thread_id: session }));
          options?.onLine?.(JSON.stringify({ type: "error", message: RECONNECT_429 }));
          for (let n = 0; n < 8; n++) {
            await new Promise((r) => setTimeout(r, 40));
            if (closed) throw new Error("container closed");
            options?.onLine?.(JSON.stringify({ type: "item.completed", item: { id: `r${n}`, type: "reasoning", text: "…" } }));
          }
          for (const e of [{ type: "item.completed", item: { type: "agent_message", text: JSON.stringify(output) } },
            { type: "turn.completed", usage: { input_tokens: 100, cached_input_tokens: 40, output_tokens: 7, reasoning_output_tokens: 3 } }]) {
            options?.onLine?.(JSON.stringify(e));
          }
          return { stdout: "", stderr: "", exitCode: 0 };
        }
        const commands = mode.startsWith("over-budget")
          ? [1, 2, 3].map((n) => ({ type: "item.completed", item: { id: `c${n}`, type: "command_execution", command: "git diff", exit_code: 0 } })) : [];
        const events = [{ type: "thread.started", thread_id: session }, ...commands,
          { type: "item.completed", item: { type: "agent_message", text: JSON.stringify(output) } },
          ...(mode === "missing-completed" ? [] : [{ type: "turn.completed",
            usage: { input_tokens: 100, cached_input_tokens: 40, output_tokens: 7, reasoning_output_tokens: 3 } }])];
        for (const e of events) {
          options?.onLine?.(JSON.stringify(e));
          if (mode.startsWith("over-budget") && closed) {  // 容器已关：不再有输出，exec 返回非零或 reject
            if (mode === "over-budget-reject") throw new Error("container closed");
            return { stdout: "", stderr: "", exitCode: 137 };
          }
        }
        if (mode === "write") writeFileSync(join(f.checkout, "changed"), "write simulated");
        return { stdout: "", stderr: "", exitCode: mode === "failed" ? 1 : 0 };
      },
      async copyFileIn() {},
      async copyFileOut(_src, dest) {
        if (mode === "missing-log") throw new Error("missing session");
        mkdirSync(dirname(dest), { recursive: true });
        writeFileSync(dest, JSON.stringify({ type: "session_meta", payload: { id: session, cwd: "/review" } }) + "\n");
      },
      async close() { closed = true; },
    };
    const deps: WorkerDependencies = {
      identity: () => ({ head: f.launch.controller_code_head, dirty: "" }),
      ready: () => image,
      sandbox: () => ({ name: "fixture", env: {}, create: async (options) => {
        creates++;
        assert.deepEqual(options.mounts, [{ hostPath: volume, sandboxPath: "/review", readonly: true }]);
        assert.equal(options.worktreePath, volume);
        assert.deepEqual(fake.calls, [`populate ${volume} ${image} ${f.checkout} ${f.launch.launch_id}`], "卷在建容器前灌好");
        assert.deepEqual(options.env, {});
        return handle;
      } }),
      inspect: () => ({ Id: container, Image: image,
        Mounts: mode === "bind-mount" ? [{ Type: "bind", Source: f.checkout, Destination: "/review", RW: false }] : [volumeMount(f.launch, mode === "bad-mount")],
        Config: { Env: mode === "secret-env" ? ["GH_TOKEN=fixture"] : [] } }),
      volumes: fake.volumes,
      imageEnv: () => [], timeoutMs: mode === "timeout-reject" ? 20 : 10000, commandCap: 2, rateLimitStallMs: 100,
    };
    try {
      const started = Date.now();
      await runExternalReview(f.folder, deps);
      const elapsed = Date.now() - started;
      const receipt = JSON.parse(readFileSync(join(f.folder, "receipt.json"), "utf8"));
      assert.equal(creates, mode === "volume-mismatch" ? 0 : 1); assert.equal(closed, mode !== "volume-mismatch");
      assert.equal(receipt.status, ["PASS", "BLOCK", "reconnect-429-recovers", "volume-remove-fails"].includes(mode) ? "completed" : "failed");
      // 每次 launch 恰灌一个卷；容器关闭后删卷，删不掉只记 volume_removed=false，不改结论。
      assert.deepEqual(fake.calls, [`populate ${volume} ${image} ${f.checkout} ${f.launch.launch_id}`, `remove ${volume}`]);
      assert.equal(receipt.volume, volume);
      assert.equal(receipt.volume_removed, mode !== "volume-remove-fails");
      if (["bind-mount", "bad-mount", "volume-mismatch"].includes(mode)) assert.equal(modelCommand, "", "挂载或卷内容不符时不启动模型");
      if (receipt.status === "completed") {
        assert.match(modelCommand, /(?:^|\s)--skip-git-repo-check(?:\s|$)/);
        assert(modelCommand.includes("-c 'project_doc_max_bytes=0'"));
        assert.deepEqual(receipt.usage, { input_tokens: 100, cached_input_tokens: 40, output_tokens: 7,
          reasoning_output_tokens: 3, commands: 0, reported: true });
        assert.equal(receipt.result.summary, `VERDICT: ${mode}`);
        assert.equal(receipt.failure_code, undefined);
        assert.equal(receipt.session_id, session);
        assert(receipt.turn_completed);
        assert.equal(receipt.container_id, container);
        assert.equal(receipt.output_contract, schemaless ? "prompt" : "schema");
      }
      if (mode.startsWith("over-budget")) {
        assert.equal(receipt.failure_code, "budget_exceeded");
        assert.equal(receipt.usage.commands, 3);
        assert.equal(receipt.usage.reported, false);  // 被关停的独审没报用量：标为未知，不是 0
      }
      if (mode === "timeout-reject") assert.equal(receipt.failure_code, "timeout");
      if (mode.startsWith("rate-limited")) {
        // 限流终态立即停、429 重连后静默过窗口（这里 100 ms）即停，记 rate_limited，不等 timeoutMs（这里 10 秒）。
        assert.equal(receipt.failure_code, "rate_limited");
        assert(elapsed < 5000, `rate_limited 应及时结束，实际 ${elapsed} ms`);
        if (mode === "rate-limited-hang") assert(elapsed >= 100, `静默窗口未到就停了：${elapsed} ms`);
        assert.equal(receipt.turn_completed, false);
      }
      if (mode === "reconnect-429-recovers") assert(elapsed >= 300, "事件持续到达的审查要跑完，总时长超过静默窗口");
      if (mode === "failed") assert.equal(receipt.failure_code, "model_exit");
      await assert.rejects(runExternalReview(f.folder, deps));
      assert.equal(creates, mode === "volume-mismatch" ? 0 : 1);
    } finally { rmSync(f.root, { recursive: true, force: true }); }
  });
}


test("限流信号：turn.failed 带 429 与最后一次 429 重连是终态，中途 429 重连只是重试；其他原因与命令输出不算", () => {
  assert.equal(rateLimitSignal({ type: "error", message: RECONNECT_429 }), "retry");
  assert.equal(rateLimitSignal({ type: "error", message: RECONNECT_429.replace("1/5", "5/5") }), "terminal");
  assert.equal(rateLimitSignal({ type: "turn.failed", error: { message: "exceeded retry limit, last status: 429 Too Many Requests" } }), "terminal");
  assert.equal(rateLimitSignal({ type: "error", message: "Reconnecting... 5/5 (stream disconnected before completion: unexpected EOF)" }), null);
  assert.equal(rateLimitSignal({ type: "turn.failed", error: { message: "exceeded retry limit, last status: 500 Internal Server Error" } }), null);
  assert.equal(rateLimitSignal({ type: "item.completed", item: { type: "command_execution", aggregated_output: RECONNECT_429 } }), null);
  assert.equal(rateLimitSignal(null), null);
});


test("损坏 launch 在读取阶段也保存失败终态", async () => {
  const f = fixture();
  try {
    writeFileSync(join(f.folder, "launch.json"), "{invalid");
    await assert.rejects(runExternalReview(f.folder));
    const receipt = JSON.parse(readFileSync(join(f.folder, "receipt.json"), "utf8"));
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.phase, "launch");
    assert.equal(receipt.container_closed, true);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});

test("已有 supervisor 锁时保留原回执并保存本进程启动终态", async () => {
  const f = fixture();
  try {
    writeFileSync(join(f.folder, "supervisor.lock"), "");
    writeFileSync(join(f.folder, "receipt.json"), "original evidence");
    await assert.rejects(runExternalReview(f.folder));
    assert.equal(readFileSync(join(f.folder, "receipt.json"), "utf8"), "original evidence");
    const receipt = JSON.parse(readFileSync(join(f.folder, `startup-failure-${process.pid}.json`), "utf8"));
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.phase, "lock");
    assert.equal(receipt.launch_id, f.launch.launch_id);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});


test("创建容器结果不明时不能声明已关闭，也不删仍可能被占用的卷", async () => {
  const f = fixture();
  const fake = fakeVolumes();
  const deps: WorkerDependencies = {
    identity: () => ({ head: f.launch.controller_code_head, dirty: "" }),
    ready: () => image,
    sandbox: () => ({ name: "unknown-create", env: {}, create: async () => { throw new Error("unknown create"); } }),
    inspect: () => { throw new Error("must not inspect"); },
    volumes: fake.volumes,
    imageEnv: () => [], timeoutMs: 10000,
  };
  try {
    await runExternalReview(f.folder, deps);
    const receipt = JSON.parse(readFileSync(join(f.folder, "receipt.json"), "utf8"));
    assert.equal(receipt.status, "failed");
    assert.equal(receipt.phase, "container");
    assert.equal(receipt.container_closed, false);
    assert.equal(receipt.volume_removed, false);
    assert.deepEqual(fake.calls.map((c) => c.split(" ")[0]), ["populate"]);
  } finally { rmSync(f.root, { recursive: true, force: true }); }
});


for (const signal of ["SIGTERM", "SIGINT"] as const) {
  test(`容器 create 等待期间 ${signal} 不得启动模型`, async () => {
    const f = fixture();
    const fake = fakeVolumes();
    let resolveCreate!: (handle: BindMountSandboxHandle) => void;
    let entered!: () => void;
    const creating = new Promise<void>((resolve) => { entered = resolve; });
    const created = new Promise<BindMountSandboxHandle>((resolve) => { resolveCreate = resolve; });
    const commands: string[] = [];
    let closed = false;
    const handle: BindMountSandboxHandle = {
      worktreePath: "/review",
      async exec(command) {
        commands.push(command);
        if (command === "cat /etc/hostname") return { stdout: container.slice(0, 12), stderr: "", exitCode: 0 };
        if (command.startsWith("node -e ")) return { stdout: JSON.stringify({ source_write: "EROFS", git_write: "EROFS", host_read: "ENOENT", state_write: "ENOENT" }), stderr: "", exitCode: 0 };
        return { stdout: "", stderr: "", exitCode: 1 };
      },
      async copyFileIn() {}, async copyFileOut() {}, async close() { closed = true; },
    };
    const deps: WorkerDependencies = {
      identity: () => ({ head: f.launch.controller_code_head, dirty: "" }), ready: () => image,
      sandbox: () => ({ name: "cancel-create", env: {}, create: async () => { entered(); return created; } }),
      inspect: () => ({ Id: container, Image: image, Mounts: [volumeMount(f.launch)], Config: { Env: [] } }),
      volumes: fake.volumes,
      imageEnv: () => [], timeoutMs: 10000,
    };
    try {
      const running = runExternalReview(f.folder, deps);
      await creating;
      process.emit(signal);
      resolveCreate(handle);
      await running;
      assert.deepEqual(commands, [], "cancelled create must close before executing any container command");
      assert(closed);
      const receipt = JSON.parse(readFileSync(join(f.folder, "receipt.json"), "utf8"));
      assert.equal(receipt.status, "cancelled");
      assert.equal(receipt.container_closed, true);
      assert.equal(receipt.phase, "container");
      assert.equal(receipt.volume_removed, true, "取消后容器已关，卷随之删除");
    } finally { rmSync(f.root, { recursive: true, force: true }); }
  });
}

test("沿用前准入与正式派发同一组检查：controller 未提交或镜像未验收即拒绝", () => {
  const head = "c".repeat(40);
  const ready = (img: string) => { assert.equal(img, REVIEW_IMAGE); return image; };
  assert.deepEqual(checkReviewAdmission({ identity: () => ({ head, dirty: "" }), ready }), { controller_code_head: head, image_id: image });
  assert.throws(() => checkReviewAdmission({ identity: () => ({ head, dirty: " M .sandcastle/x" }), ready }), /未提交/);
  assert.throws(() => checkReviewAdmission({ identity: () => ({ head, dirty: "" }),
    ready: () => { throw new Error("外部独审必须先完成当前代码 head 的 Docker 验收"); } }), /Docker 验收/);
});
