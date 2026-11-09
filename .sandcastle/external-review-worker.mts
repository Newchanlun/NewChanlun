import type { BindMountSandboxHandle, SandboxProvider } from "@ai-hero/sandcastle";
import { execFileSync, spawn } from "node:child_process";
import { closeSync, existsSync, lstatSync, openSync, readFileSync, realpathSync, renameSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { dirname, join, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";
import { CodexTranscript, OUTPUT_SCHEMA, assertRoute, type ChildModel } from "./codex-child.ts";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { codexWorker } from "./codex-route.mts";
import { assertSwarmExecutionReady, dockerCliProxyEnv } from "./swarm-route.mts";
import { IMAGE_ID, codeIdentity, type Admission } from "./docker-acceptance.mts";
import { containerEnvLeaks, declaredContainerEnv, type MountSpec } from "./docker-isolation.mts";
import { gitEnvironment } from "./git-environment.ts";

export interface ReviewLaunch {
  run_id: string; launch_id: string; pr_number: number; model: ChildModel;
  base_sha: string; merge_base_sha: string; head_sha: string; controller_code_head: string;
  checkout: string; prompt: string; mode: "review";
}
export const REVIEW_IMAGE = "sandcastle:newchanlun";
/** #1968：kimi 在 codex exec --output-schema 下把开场白当成终答、零工具调用就结束（PR #1966 实测 3/3）；
 *  不带 schema、改由提示词约束 JSON 时 3/3 正常读代码。表内模型不传 schema，提示词末尾追加下面这句。 */
export const PROMPT_JSON_MODELS: ReadonlySet<string> = new Set(["kimi-k3.1-pro"]);
export const PROMPT_JSON_INSTRUCTION = "\n最终消息只输出一个 JSON 对象，不加 Markdown 代码围栏、不加其它文字。"
  + "键恰为 status、summary、findings、validation：status 取 completed、blocked、failed 之一；"
  + "summary 为字符串；findings、validation 为字符串数组。";
const inside = (root: string, path: string) => path === root || path.startsWith(root + sep);

export function readLaunch(folder: string): ReviewLaunch {
  const path = join(folder, "launch.json");
  if (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink()) throw new Error("launch intent 不是普通文件");
  const launch = JSON.parse(readFileSync(path, "utf8")) as ReviewLaunch;
  assertRoute(launch.model);
  for (const sha of [launch.base_sha, launch.merge_base_sha, launch.head_sha, launch.controller_code_head]) {
    if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("launch SHA 无效");
  }
  if (!/^[a-f0-9-]{36}$/.test(launch.run_id) || !/^[a-f0-9-]{36}$/.test(launch.launch_id)
    || !Number.isSafeInteger(launch.pr_number) || launch.pr_number <= 0 || launch.mode !== "review"
    || typeof launch.prompt !== "string" || !launch.prompt.trim()) throw new Error("launch intent 不完整");
  if (realpathSync(launch.checkout) !== launch.checkout || !lstatSync(join(launch.checkout, ".git")).isDirectory()) {
    throw new Error("只接受独立无凭据 clone，不接受 linked worktree");
  }
  if (inside(launch.checkout, folder) || inside(folder, launch.checkout)) throw new Error("源码与宿主回执目录重叠");
  if (existsSync(join(launch.checkout, ".codex", "config.toml"))) throw new Error("候选项目 Codex 配置未获准入");
  return launch;
}

/** #1986：宿主 checkout 不再 bind mount 进容器。Colima（vz）经 virtiofs 共享宿主目录，VM 为容器读过的每个文件
 *  开一个宿主句柄；容器删了、宿主删了 checkout 也不关（实测在容器里 rm 同样不关），空间只有重启 VM 才还。
 *  现在每次独审建一个 Docker 命名卷，用 docker cp（Docker API 的 tar 流，不经 virtiofs）灌入 checkout，
 *  只读挂到 /review；容器关闭后删卷。卷名带 launch_id，一次 launch 一个卷。 */
export const REVIEW_VOLUME_LABEL = "newchanlun.external-review.launch";
const REVIEW_VOLUME = /^newchanlun-external-review-[a-f0-9-]{36}$/;
export function reviewVolumeName(launchId: string): string {
  const name = `newchanlun-external-review-${launchId}`;
  if (!REVIEW_VOLUME.test(name)) throw new Error("launch_id 不能构成审阅卷名");
  return name;
}

export function reviewMounts(volume: string): MountSpec[] {
  if (!REVIEW_VOLUME.test(volume)) {
    throw new Error("review 只允许本次 launch 的审阅卷一个挂载，不接收宿主 home、Git、session 或状态目录挂载");
  }
  return [{ hostPath: volume, sandboxPath: "/review", readonly: true }];
}

type CreateOptions = { worktreePath: string; hostRepoPath: string; mounts: MountSpec[]; env: Record<string, string> };
type DockerProvider = SandboxProvider & { create(options: CreateOptions): Promise<BindMountSandboxHandle> };

/** 审阅容器的 provider：与 swarmSandbox 同一 Sandcastle docker()、同一镜像 Id 校验和 env 白名单，但只接受
 *  reviewMounts 给出的单个只读卷。hardenMounts 为可写的宿主 worktree 补挂只读 .git 等子路径；审阅卷整卷只读，
 *  补挂宿主子路径反而会把 .git 重新经 virtiofs 带进 VM，所以这里不走它。 */
export function reviewSandbox(image: string, env: Record<string, string> = dockerCliProxyEnv()): DockerProvider {
  if (!IMAGE_ID.test(image)) throw new Error("审阅容器必须以准入核对过的 sha256 镜像 Id 启动");
  const base = docker({ imageName: image, env }) as unknown as DockerProvider;
  const declared = declaredContainerEnv(base.env);
  return { ...base, create: (options: CreateOptions) => {
    const [mount, ...rest] = options.mounts;
    if (rest.length || !mount || !REVIEW_VOLUME.test(mount.hostPath) || mount.sandboxPath !== "/review" || mount.readonly !== true
      || options.worktreePath !== mount.hostPath) throw new Error("审阅容器只接受本次 launch 的只读审阅卷");
    return base.create.call(base, { ...options, mounts: [{ ...mount }], env: declared });
  } };
}

type Snapshot = { head: string; branch: string; status: string };
export function snapshot(checkout: string): Snapshot {
  const env = { ...gitEnvironment(), GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", GIT_NO_REPLACE_OBJECTS: "1" };
  const git = (...args: string[]) => execFileSync("git", ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-C", checkout, ...args],
    { env, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  return { head: git("rev-parse", "HEAD"), branch: git("rev-parse", "--abbrev-ref", "HEAD"), status: git("status", "--porcelain", "--untracked-files=all") };
}

export interface ReviewVolumes {
  /** 先核 VM 磁盘余量，再新建卷并灌入宿主 checkout（含 .git），属主改成容器用户；卷已存在即拒绝，不复用旧内容。 */
  populate(volume: string, image: string, checkout: string, launchId: string): void;
  /** 在新起的一次性容器里读卷的 Git 状态（与 snapshot 同一组读取），不经审查员容器。 */
  snapshot(volume: string, image: string, launchId: string): Snapshot;
  /** 先删仍引用该卷的容器（含残留的辅助容器与审阅容器），再删卷；删不掉时抛错。 */
  remove(volume: string): void;
}

/** VM 磁盘（/var/lib/docker，在 macOS 系统盘的稀疏镜像上）灌卷后至少留这么多余量。 */
export const VM_SPACE_RESERVE = 2 * 1024 ** 3;
/** 一次性容器里的 Git 读取：绝对路径的 sh、env、git，env -i 清空 env，hooks 与 fsmonitor 关闭。
 *  不在审查员容器里跑：那里 PATH 前几段可被审查员写入，after 快照可被伪造。 */
export const VOLUME_SNAPSHOT = "g() { /usr/bin/env -i PATH=/usr/bin:/bin GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null"
  + " GIT_NO_REPLACE_OBJECTS=1 GIT_OPTIONAL_LOCKS=0 /usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -C /review \"$@\"; };"
  + " g rev-parse HEAD && g rev-parse --abbrev-ref HEAD && g status --porcelain --untracked-files=all";

const dockerCli = (args: string[]) => execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
const hostKilobytes = (path: string) => Number(execFileSync("du", ["-sk", path], { encoding: "utf8" }).split(/\s/, 1)[0]);

/** 建卷准入锁：checkout 在 <checkout_root>/<run_id>/<model>，锁放 checkout_root 下，本机所有监督共用一把。 */
export const volumeAdmissionLock = (checkout: string): string => join(dirname(dirname(checkout)), ".vm-volume-admission.lock");
/** 锁持有进程：拿到 flock 后写信号文件，然后阻塞读 stdin。父进程正常放锁时杀掉它；父进程被 SIGKILL、OOM 或
 *  重启打断时管道断开，它读到 EOF 退出。两种情况都由内核在它退出时释放 flock，没有陈旧锁，也没有「接管」。 */
const LOCK_HOLDER = "import fcntl, sys\n"
  + "lock = open(sys.argv[1], 'a')\n"
  + "fcntl.flock(lock, fcntl.LOCK_EX)\n"
  + "open(sys.argv[2], 'w').close()\n"
  + "sys.stdin.read()\n";
/** 跨进程互斥用内核 flock（Node 没有内置 flock，借 python3 的一个子进程持有）。锁文件本身从不删除，
 *  放锁就是结束自己起的那个持有进程，所以任何一方都删不掉、也放不掉别人的锁。
 *  populate 是同步调用，SIGTERM 要等它返回才处理，finally 一定放锁。 */
export function withVolumeAdmissionLock<T>(lock: string, body: () => T, waitMs = 30 * 60_000): T {
  execFileSync("python3", ["-c", "import fcntl"], { stdio: "ignore" });  // 先确认持有进程起得来，免得白等到超时
  const acquired = `${lock}.${process.pid}.${randomUUID()}.acquired`;
  const holder = spawn("python3", ["-c", LOCK_HOLDER, lock, acquired], { stdio: ["pipe", "ignore", "ignore"] });
  try {
    const deadline = Date.now() + waitMs;
    while (!existsSync(acquired)) {
      if (Date.now() > deadline) throw new Error("等待 VM 建卷准入锁超时");
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 20);
    }
    return body();
  } finally {
    holder.kill("SIGKILL");
    rmSync(acquired, { force: true });
  }
}

export function dockerReviewVolumes(run: (args: string[]) => string = dockerCli, checkoutKilobytes = hostKilobytes,
  lockFor: (checkout: string) => string = volumeAdmissionLock): ReviewVolumes {
  // 本次 launch 起的每个容器和卷都带同一标签，宿主 reaper 据此回收崩溃、被杀或重启后留下的孤儿。
  const label = (launchId: string) => ["--label", `${REVIEW_VOLUME_LABEL}=${launchId}`];
  const owner = `${process.getuid?.() ?? 1000}:${process.getgid?.() ?? 1000}`;
  const fill = (volume: string, image: string, checkout: string, launchId: string) => {
      const df = run(["run", "--rm", "--network", "none", ...label(launchId), "--entrypoint", "/bin/df", image, "-Pk", "/"]);
      const available = Number(df.split("\n").at(-1)?.trim().split(/\s+/)[3]) * 1024;
      const needed = checkoutKilobytes(checkout) * 1024 + VM_SPACE_RESERVE;
      if (!(available >= needed)) throw new Error(`VM 磁盘空间不足：审阅卷需要 ${needed} bytes，可用 ${available} bytes；未建卷`);
      let exists = true;
      try { run(["volume", "inspect", volume]); } catch { exists = false; }
      if (exists) throw new Error("审阅卷已存在，不复用旧内容");
      run(["volume", "create", ...label(launchId), volume]);
      // docker cp 进卷的文件属 root；容器以宿主 uid:gid 运行（Sandcastle docker() 的缺省），属主不符时 git 拒读。
      const helper = run(["create", "--network", "none", ...label(launchId), "--user", "0:0", "-v", `${volume}:/review`,
        "--entrypoint", "chown", image, "-R", "-h", owner, "/review"]);
      try {
        run(["cp", `${checkout}/.`, `${helper}:/review`]);
        run(["start", "-a", helper]);
        if (run(["inspect", "--format", "{{.State.ExitCode}}", helper]) !== "0") throw new Error("审阅卷属主设置失败");
      } finally { run(["rm", "-f", helper]); }
  };
  return {
    populate(volume, image, checkout, launchId) {
      reviewMounts(volume);
      // 并发的 reviewer（同一 run 的两位、别的 PR 的 run）各读 df 再各自灌卷会超卖余量：从读 df 到灌完卷串行进行，
      // 后来者读到的 df 已扣掉前者的卷。
      withVolumeAdmissionLock(lockFor(checkout), () => fill(volume, image, checkout, launchId));
    },
    snapshot(volume, image, launchId) {
      reviewMounts(volume);
      const out = run(["run", "--rm", "--network", "none", ...label(launchId), "--user", owner, "-v", `${volume}:/review:ro`,
        "--entrypoint", "/bin/sh", image, "-c", VOLUME_SNAPSHOT]);
      const [head = "", branch = "", ...status] = out.split("\n");
      return { head: head.trim(), branch: branch.trim(), status: status.join("\n").trim() };
    },
    remove(volume) {
      reviewMounts(volume);
      // Sandcastle 的 close 吞掉 stop/rm 的错误；仍引用卷的容器（含 created/exited）会让删卷一直报 in use。
      for (const id of run(["ps", "-a", "-q", "--filter", `volume=${volume}`]).split("\n").filter(Boolean)) run(["rm", "-f", id]);
      run(["volume", "rm", volume]);
    },
  };
}

export function verifyReviewAdmission(admission: Admission): void {
  if (!admission.accepted) throw new Error("外部独审必须先完成当前代码 head 的 Docker 验收，不能占用旧受控行");
}

export async function probeReviewFilesystem(handle: BindMountSandboxHandle, folder: string): Promise<Record<string, string>> {
  const canary = join(folder, "nonsecret-canary.txt");
  writeFileSync(canary, "external-review non-secret canary", { flag: "wx", mode: 0o600 });
  try {
    const program = `const fs=require('node:fs');const out={};
      const probe=(k,f)=>{try{f();out[k]='ALLOWED'}catch(e){out[k]=e.code}};
      probe('source_write',()=>fs.writeFileSync('/review/.external-review-write-probe','probe'));
      probe('git_write',()=>{const fd=fs.openSync('/review/.git/config','a');fs.closeSync(fd)});
      probe('host_read',()=>fs.readFileSync(${JSON.stringify(canary)}));
      probe('state_write',()=>fs.writeFileSync(${JSON.stringify(join(folder, ".state-probe"))},'probe'));
      console.log(JSON.stringify(out));`;
    const quote = (s: string) => "'" + s.replaceAll("'", "'\\''") + "'";
    const result = await handle.exec(`node -e ${quote(program)}`);
    if (result.exitCode) throw new Error("review 文件隔离探针无法运行");
    const observation = JSON.parse(result.stdout.trim());
    if (observation.source_write !== "EROFS" || observation.git_write !== "EROFS"
      || !["ENOENT", "EACCES"].includes(observation.host_read)
      || !["ENOENT", "EACCES", "EROFS"].includes(observation.state_write)) {
      throw new Error("review 源码、Git、宿主 canary 或状态目录可被访问");
    }
    return observation;
  } finally { unlinkSync(canary); }
}

function save(folder: string, name: string, value: unknown): void {
  const tmp = join(folder, `${name}.${process.pid}.tmp`);
  writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 });
  renameSync(tmp, join(folder, name));
}

export interface WorkerDependencies {
  ready(image: string): string;
  sandbox(image: string): DockerProvider;
  identity(): { head: string; dirty: string };
  inspect(id: string): { Id: string; Image: string; Mounts: Array<{ Type?: string; Name?: string; Source: string; Destination: string; RW: boolean }>; Config: { Env: string[] } };
  /** #1986：审阅卷的灌入与删除。 */
  volumes: ReviewVolumes;
  imageEnv(image: string): string[];
  timeoutMs: number;
  /** 单次独审的命令数上限；超出即停并记 failure_code=budget_exceeded。缺省见 REVIEW_COMMAND_CAP。 */
  commandCap?: number;
  /** 429 重连之后多久没有新事件就按限流停下，记 failure_code=rate_limited。缺省见 RATE_LIMIT_STALL_MS。 */
  rateLimitStallMs?: number;
}
// 实测（2026-11-01..08，247 次完成的独审）：Opus 命令数中位 47、p90 98、最大 143；墙钟最大 23 分钟。
// 上限约取正常一次的 3–5 倍，并高于实测最大值，只拦失控，不拦正常审查。
export const REVIEW_COMMAND_CAP = 250;
/** codex 对单个请求的重试用尽、最后一次是 429 时报出的文字。只看 error、turn.failed 事件和 stderr，不看命令输出。
 *  2026-11-09 opus 实测（#1917/#1920/#1921/#1935/#1942）：「Reconnecting... 1/5 (exceeded retry limit, last status: 429 …)」
 *  只是一次重连，不是终态——#1942 之后又跑了约 190 个事件；#1920/#1921/#1935 在这句之后不再有任何输出，干等到 45 分钟超时；
 *  #1917 以 turn.failed 带同一句结束。 */
export const RATE_LIMIT_EXHAUSTED = /exceeded retry limit, last status: 429\b|\b429 Too Many Requests\b/;
/** 429 重连之后静默这么久即判限流卡死。正常审查两个事件之间远短于此（命令执行另有 item.started 在前）。 */
export const RATE_LIMIT_STALL_MS = 300_000;
/** terminal：立即停（turn.failed 带 429，或最后一次重连 n==max 带 429）；retry：429 重连，后续静默才停；null：无关。 */
export function rateLimitSignal(event: unknown): "terminal" | "retry" | null {
  if (typeof event !== "object" || event === null) return null;
  const e = event as { type?: unknown; message?: unknown; error?: { message?: unknown } };
  if (e.type === "turn.failed") {
    return typeof e.error?.message === "string" && RATE_LIMIT_EXHAUSTED.test(e.error.message) ? "terminal" : null;
  }
  if (e.type !== "error" || typeof e.message !== "string" || !RATE_LIMIT_EXHAUSTED.test(e.message)) return null;
  const reconnect = /^Reconnecting\.\.\. ([1-9]\d*)\/([1-9]\d*) \(/.exec(e.message);
  return reconnect && BigInt(reconnect[1]!) >= BigInt(reconnect[2]!) ? "terminal" : "retry";
}
const dependencies: WorkerDependencies = {
  ready: (image) => assertSwarmExecutionReady(image, { rows: [], verify: verifyReviewAdmission }),
  sandbox: (image) => reviewSandbox(image),
  volumes: dockerReviewVolumes(),
  identity: () => codeIdentity(),
  inspect: (id) => JSON.parse(execFileSync("docker", ["inspect", id], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }))[0],
  imageEnv: (image) => JSON.parse(execFileSync("docker", ["image", "inspect", image, "--format", "{{json .Config.Env}}"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] })) ?? [],
  timeoutMs: 2_700_000,
};

export async function runExternalReview(folder: string, deps: WorkerDependencies = dependencies): Promise<void> {
  let launch: ReviewLaunch | undefined;
  let ownsLock = false;
  const record: Record<string, unknown> = { status: "failed", mode: "review",
    sandbox: "docker-read-only", process_pid: process.pid, started_at: new Date().toISOString(),
    phase: "launch", exit_code: null, turn_completed: false, session_id: null, result: null, container_closed: false };
  let handle: BindMountSandboxHandle | undefined;
  let creationStarted = false;
  let volume: string | undefined;
  let removeOnExit: (() => void) | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelled = false;
  // 主动停机标志放在外层：exec 在容器被关后可能 reject 而不是返回，catch 里也要据此补齐原因码。
  let timedOut = false;
  let overBudget = false;
  // 限流终态或 429 重连后静默：关停记 rate_limited，不再等超时。结论规则不变（FAILED，整轮照发 error）。
  let rateLimited = false;
  let stall: ReturnType<typeof setTimeout> | undefined;
  const stopCode = (): string | undefined =>
    cancelled ? "cancelled" : overBudget ? "budget_exceeded" : rateLimited ? "rate_limited" : timedOut ? "timeout" : undefined;
  const cancel = () => { cancelled = true; void handle?.close(); };
  process.once("SIGTERM", cancel); process.once("SIGINT", cancel);
  try {
    launch = readLaunch(folder);
    Object.assign(record, launch, { prompt: undefined });
    record.phase = "lock";
    const lock = openSync(join(folder, "supervisor.lock"), "wx", 0o600);
    ownsLock = true;
    closeSync(lock);
    record.phase = "controller";
    const identity = deps.identity();
    if (identity.head !== launch.controller_code_head || identity.dirty) throw new Error("controller 代码已漂移或未提交");
    record.phase = "checkout";
    const before = snapshot(launch.checkout); record.before = before;
    if (before.head !== launch.head_sha || before.status || before.branch !== "HEAD") throw new Error("checkout 不干净或 head 不符");
    record.phase = "admission";
    const image = deps.ready(REVIEW_IMAGE); record.image_id = image;
    const sandbox = deps.sandbox(image);
    record.phase = "volume";
    volume = reviewVolumeName(launch.launch_id); record.volume = volume; record.volume_removed = false;
    // SIGTERM/SIGINT 时 Sandcastle 的 shutdown 钩子同步删容器后 process.exit(1)，finally 跑不到；退出钩子同步删卷。
    // 被 SIGKILL、OOM 或重启打断时退出钩子也跑不到，由宿主派发前的 reaper 按标签回收。
    // remove() 会强删仍引用卷的容器：进程退出时本 launch 的审阅容器（Sandcastle 的 rm 失败时仍在）和辅助容器都已无用，
    // 卷名带本次 launch_id，别的 launch 的容器不会挂它；不强删，残留容器会让删卷一直报 in use。
    const reviewVolume = volume;
    removeOnExit = () => { try { deps.volumes.remove(reviewVolume); } catch { /* 留给 reaper */ } };
    process.once("exit", removeOnExit);
    deps.volumes.populate(volume, image, launch.checkout, launch.launch_id);
    if (cancelled) throw new Error("监督已取消");
    // 卷内容须与宿主 checkout 一致：同一 head、detached、工作树与 head 无差异且无多余文件。
    if (JSON.stringify(deps.volumes.snapshot(volume, image, launch.launch_id)) !== JSON.stringify(before)) {
      throw new Error("审阅卷与宿主 checkout 不一致");
    }
    const mounts = reviewMounts(volume);
    record.phase = "container";
    creationStarted = true;
    handle = await sandbox.create({ worktreePath: volume, hostRepoPath: launch.checkout,
      mounts, env: declaredContainerEnv(sandbox.env) });
    if (cancelled) throw new Error("监督已取消");
    const hostname = await handle.exec("cat /etc/hostname");
    const id = hostname.stdout.trim();
    if (hostname.exitCode || !/^[a-f0-9]{12,64}$/.test(id)) throw new Error("无法确认真实容器身份");
    const inspected = deps.inspect(id);
    const [actual, ...extra] = inspected.Mounts;
    if (inspected.Image !== image || !inspected.Id.startsWith(id) || !actual || extra.length || actual.Type !== "volume"
      || actual.Name !== volume || actual.Destination !== "/review" || actual.RW
      || containerEnvLeaks(inspected.Config.Env, deps.imageEnv(image)).length) {
      throw new Error("实际容器挂载、镜像或 env 不符合只读合同");
    }
    record.container_id = inspected.Id;
    record.phase = "filesystem";
    record.filesystem = await probeReviewFilesystem(handle, folder);
    save(folder, "supervisor.json", record);
    record.phase = "provider";
    const provider = codexWorker({ docker: true, model: launch.model, effort: "xhigh" });
    const schema = join(folder, "output-schema.json");
    writeFileSync(schema, JSON.stringify(OUTPUT_SCHEMA), { mode: 0o600 });
    await handle.copyFileIn(schema, "/tmp/external-review-schema.json");
    if (cancelled) throw new Error("监督已取消");
    const promptJson = PROMPT_JSON_MODELS.has(launch.model);
    record.output_contract = promptJson ? "prompt" : "schema";
    const prompt = promptJson ? launch.prompt + PROMPT_JSON_INSTRUCTION : launch.prompt;
    const built = provider.buildPrintCommand({ prompt, dangerouslySkipPermissions: false });
    if (built.stdin !== prompt || !built.command.includes("--disable multi_agent")) throw new Error("Codex 命令协议已漂移");
    // project_doc_max_bytes=0：不把候选仓 AGENTS.md 当指令自动注入每次请求（实测约 13k 字符，随每轮请求重发）；
    // 候选 AGENTS 本就是不可信审阅材料，审查员需要时可用 cat 读取。
    const command = built.command + " --skip-git-repo-check"
      + (promptJson ? "" : " --output-schema /tmp/external-review-schema.json") + " -c 'features.apps=false' -c 'features.plugins=false'"
      + " -c 'web_search=\"disabled\"' -c 'shell_environment_policy.inherit=\"core\"' -c 'project_doc_max_bytes=0' -";
    const transcript = new CodexTranscript(provider);
    const events = openSync(join(folder, "events.jsonl"), "wx", 0o600);
    const cap = deps.commandCap ?? REVIEW_COMMAND_CAP;
    // reported：是否收到过带 usage 的 turn.completed。codex exec 只在整轮结束时报用量，被中途关停的独审
    // token 数未知（不是 0），额度闸据 reported=false 按命令数估算，不把失控的独审算成零。
    const usage = { input_tokens: 0, cached_input_tokens: 0, output_tokens: 0, reasoning_output_tokens: 0, commands: 0,
      reported: false };
    record.usage = usage;
    timer = setTimeout(() => { timedOut = true; void handle?.close(); }, deps.timeoutMs);
    let execution;
    record.phase = "model";
    try {
      execution = await handle.exec(command, { cwd: "/review", stdin: built.stdin, onLine(line) {
        writeFileSync(events, line + "\n");
        if (stall) { clearTimeout(stall); stall = undefined; }  // 429 重连后又有事件：没卡死，继续审
        transcript.accept(line);
        try {
          const event = JSON.parse(line);
          if (event?.type === "turn.completed" && event.usage) {
            usage.reported = true;
            for (const key of ["input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"] as const) {
              usage[key] += Number(event.usage[key]) || 0;
            }
          }
          if (event?.type === "item.completed" && event.item?.type === "command_execution" && ++usage.commands > cap && !overBudget) {
            overBudget = true; void handle?.close();
          }
          const signal = rateLimitSignal(event);
          if (signal === "retry" && !rateLimited) {
            stall = setTimeout(() => {
              if (!timedOut && !rateLimited) { rateLimited = true; void handle?.close(); }
            }, deps.rateLimitStallMs ?? RATE_LIMIT_STALL_MS);
          }
          if (signal === "terminal" && !rateLimited && !timedOut) { rateLimited = true; void handle?.close(); }
        } catch { /* 非 JSON 行由 transcript 判失败，这里只计量 */ }
      } });
    } finally { closeSync(events); }
    record.exit_code = execution.exitCode;
    record.turn_completed = transcript.turnCompleted;
    record.session_id = transcript.sessionId;
    writeFileSync(join(folder, "stderr.log"), execution.stderr, { mode: 0o600 });
    if (!rateLimited && !timedOut && execution.exitCode !== 0 && RATE_LIMIT_EXHAUSTED.test(execution.stderr)) rateLimited = true;
    if (cancelled || timedOut || overBudget || rateLimited || execution.exitCode !== 0) {
      // 显式原因码：触顶是「暂停待人看」，不是静默失败。
      record.failure_code = stopCode() ?? "model_exit";
      throw new Error(cancelled ? "监督已取消" : overBudget ? `独审命令数超过上限 ${cap}`
        : rateLimited ? "限流重试已用尽" : timedOut ? "独审超时" : "Codex 退出失败");
    }
    record.phase = "transcript";
    const output = transcript.output();
    if (!provider.sessionStorage) throw new Error("模型未提供 session storage");
    record.phase = "session";
    await provider.sessionStorage.captureToHost({ hostCwd: launch.checkout, sandboxCwd: "/review",
      sessionId: transcript.sessionId!, handle });
    const log = await provider.sessionStorage.readHostSession(launch.checkout, transcript.sessionId!);
    if (!log) throw new Error("缺少真实 session 日志");
    const first = JSON.parse(log.split("\n")[0]!);
    if (first.type !== "session_meta" || first.payload?.id !== transcript.sessionId) throw new Error("session 日志身份不符");
    writeFileSync(join(folder, "session.jsonl"), log, { mode: 0o600, flag: "wx" });
    record.phase = "checkout-after";
    record.after = deps.volumes.snapshot(volume, image, launch.launch_id);
    if (JSON.stringify(record.before) !== JSON.stringify(record.after)) throw new Error("只读 review 后 checkout 变化");
    record.status = "completed"; record.result = output; record.phase = "completed";
  } catch (error) {
    record.status = cancelled ? "cancelled" : "failed";
    // SDK 传输异常可能含 Docker argv/env，只持久化错误类别，不记录其原始消息。
    record.failure_reason = error instanceof Error ? error.name : "SupervisionError";
    // 主动停机（取消、命令数触顶、超时）无论 exec 是返回还是 reject 都留下显式原因码；模型阶段的其他异常记 model_error。
    const code = record.failure_code ?? stopCode() ?? (record.phase === "model" ? "model_error" : undefined);
    if (code !== undefined) record.failure_code = code;
    try { record.after = launch ? snapshot(launch.checkout) : null; } catch { record.after = null; }
  } finally {
    if (timer) clearTimeout(timer);
    if (stall) clearTimeout(stall);
    process.removeListener("SIGTERM", cancel); process.removeListener("SIGINT", cancel);
    try {
      await handle?.close();
      record.container_closed = handle !== undefined || !creationStarted;
    } catch { record.status = "failed"; record.failure_reason = "ContainerCleanupError"; }
    // 删卷失败不改审阅结论（容器已关、内容只读）；回执记 volume_removed=false，宿主回收 checkout 时再删。
    if (volume !== undefined && record.container_closed) {
      try { deps.volumes.remove(volume); record.volume_removed = true; } catch { record.volume_removed = false; }
    }
    if (removeOnExit) process.removeListener("exit", removeOnExit);
    record.ended_at = new Date().toISOString();
    save(folder, ownsLock || !existsSync(join(folder, "supervisor.lock"))
      ? "receipt.json" : `startup-failure-${process.pid}.json`, record);
  }
  if (!ownsLock) throw new Error("独审监督启动失败，终态已保存");
}

/** 沿用旧 PASS 前的部署准入：与正式派发同一组检查（controller 已提交、ready() 核当前镜像的 accepted 记录并做容器隔离合同观测），不建审阅容器、不调模型。 */
export function checkReviewAdmission(deps: Pick<WorkerDependencies, "identity" | "ready"> = dependencies):
  { controller_code_head: string; image_id: string } {
  const identity = deps.identity();
  if (identity.dirty) throw new Error("controller 代码未提交");
  return { controller_code_head: identity.head, image_id: deps.ready(REVIEW_IMAGE) };
}

async function main(): Promise<void> {
  if (process.argv.length === 3 && process.argv[2] === "--admission-only") {
    process.stdout.write(JSON.stringify(checkReviewAdmission()) + "\n");
    return;
  }
  if (process.argv.length !== 4 || process.argv[2] !== "--output-dir") throw new Error("只接受宿主 --output-dir");
  const folder = resolve(process.argv[3]!);
  if (folder !== realpathSync(folder)) throw new Error("回执目录含符号链接");
  await runExternalReview(folder);
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(() => { process.stderr.write("外部独审监督入口失败\n"); process.exitCode = 2; });
}
