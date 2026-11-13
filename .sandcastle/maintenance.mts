import { AsyncLocalStorage } from "node:async_hooks";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HELPER = fileURLToPath(new URL("./deepagents-pilot/pilot1742/maintenance.py", import.meta.url));
const resources = new AsyncLocalStorage<{ pending: number; uncertain: boolean; owner: MaintenanceOwner; job: string }>();
const LOCAL = fileURLToPath(new URL("./deepagents-pilot/pilot1742/maintenance_local.py", import.meta.url));
/** 本机 CLI 派发前绑定监督域；escaped 后代也须证明结束，不支持外置资源。 */
export function maintenanceCommand(file: string, args: string[]): { file: string; args: string[] } {
  const scope = resources.getStore();
  if (!scope) return { file, args };
  const resource = scope.owner.reserveResource(scope.job);
  return { file: "python3", args: [LOCAL, "--root", scope.owner.root ?? "/Volumes/AgentStorage/newchanlun-maintenance",
    "--resource", resource, "--", file, ...args] };
}
/** 模型启动前登记，只有进程明确结束且收尾可判定才释放；无 context 的旧调用不变。 */
export function maintenanceResource(): (settled: boolean) => void {
  const scope = resources.getStore();
  if (!scope) return () => {};
  scope.pending++;
  let done = false;
  return settled => {
    if (done) return;
    done = true;
    scope.pending--;
    if (!settled) scope.uncertain = true;
  };
}
export class MaintenanceClosed extends Error {}
export class MaintenanceOwner {
  readonly id: string;
  readonly lane: "decision" | "wayfinder";
  readonly root?: string;
  constructor(lane: "decision" | "wayfinder", root?: string) {
    this.lane = lane;
    this.root = root;
    this.id = this.call("register", ["--lane", lane, "--pid", String(process.pid), "--local-actions"]).owner as string;
  }
  private call(command: string, args: string[] = []): Record<string, unknown> {
    const result = spawnSync("python3", [HELPER, ...(this.root ? ["--root", this.root] : []), command, ...args],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    if (result.status === 75) throw new MaintenanceClosed("maintenance closed");
    if (result.error || result.status !== 0) throw new Error("maintenance unavailable");
    const value: unknown = JSON.parse(result.stdout);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("maintenance invalid response");
    return value as Record<string, unknown>;
  }
  reserveResource(job: string): string {
    const resource = this.call("reserve-resource", ["--owner", this.id, "--job", job]).resource;
    if (typeof resource !== "string") throw new Error("maintenance missing resource");
    return resource;
  }
  poll(): boolean { return this.call("poll", ["--owner", this.id]).closed === true; }
  stop(): void { this.call("stop", ["--owner", this.id]); }
  async work<T>(key: string, action: () => T | Promise<T>, natural: (result: T) => boolean = () => true): Promise<T> {
    const job = this.call("admit", ["--owner", this.id, "--work", key]).job;
    if (typeof job !== "string") throw new Error("maintenance missing receipt");
    const scope = { pending: 0, uncertain: false, owner: this, job };
    return resources.run(scope, async () => {
      let accepted = true;
      try {
        const result = await action();
        accepted = natural(result);
        return result;
      } finally {
        // 业务成功与生命周期终止分开：gh/锁竞争错误可以返回，模型中断不能冒充收尾。
        const opaqueClear = accepted && scope.pending === 0 && !scope.uncertain;
        const settled = this.call("action-exited", ["--owner", this.id, "--job", job, ...(opaqueClear ? ["--natural"] : [])]).settled === true;
        this.call("finish", ["--owner", this.id, "--job", job, ...(settled ? ["--natural"] : [])]);
      }
    });
  }
}
