import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HELPER = fileURLToPath(new URL("./deepagents-pilot/pilot1742/maintenance.py", import.meta.url));
export class MaintenanceClosed extends Error {}
export class MaintenanceOwner {
  readonly id: string;
  readonly lane: "decision" | "wayfinder";
  readonly root?: string;
  constructor(lane: "decision" | "wayfinder", root?: string) {
    this.lane = lane;
    this.root = root;
    this.id = this.call("register", ["--lane", lane, "--pid", String(process.pid)]).owner as string;
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
  poll(): boolean { return this.call("poll", ["--owner", this.id]).closed === true; }
  stop(): void { this.call("stop", ["--owner", this.id]); }
  async work<T>(key: string, action: () => T | Promise<T>, natural: (result: T) => boolean = () => true): Promise<T> {
    const job = this.call("admit", ["--owner", this.id, "--work", key]).job;
    if (typeof job !== "string") throw new Error("maintenance missing receipt");
    let completed = false;
    try {
      const result = await action();
      completed = natural(result);
      if (completed) this.call("returned-action", ["--owner", this.id, "--job", job]);
      return result;
    } finally {
      this.call("finish", ["--owner", this.id, "--job", job, ...(completed ? ["--natural"] : [])]);
    }
  }
}
