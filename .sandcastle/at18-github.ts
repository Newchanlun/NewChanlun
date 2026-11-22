import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execute = promisify(execFile);
export type Row = Record<string, unknown>;
export const isRow = (value: unknown): value is Row =>
  value !== null && typeof value === "object" && !Array.isArray(value);
export function object(value: unknown): Row {
  if (!isRow(value)) throw new Error("object");
  return value;
}
export function rows(value: unknown): Row[] {
  if (!Array.isArray(value)) throw new Error("array");
  return value.map(object);
}
export interface At18GitHub {
  repo: string;
  get(route: string, fresh?: boolean): Promise<Row>;
  list(route: string, key?: string, fresh?: boolean): Promise<Row[]>;
}
export function at18GitHub(root: string, origin: string): At18GitHub {
  const repo = /^(?:https:\/\/github\.com\/|git@github\.com:)([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+?)(?:\.git)?$/.exec(origin)?.[1] ?? "";
  const cached = new Map<string, Promise<unknown>>();
  const waiting: (() => void)[] = [];
  let active = 0;
  async function request(args: string[]) {
    if (!repo) throw new Error("repository");
    if (active >= 8) await new Promise<void>(resolve => waiting.push(resolve));
    else active++;
    try {
      const { stdout } = await execute("gh", ["api", ...args], {
        cwd: root, timeout: 30_000, maxBuffer: 32 * 1024 * 1024,
        env: { ...process.env, GH_HOST: "github.com", GH_PROMPT_DISABLED: "1" },
      });
      const result: unknown = JSON.parse(stdout);
      return result;
    } finally {
      const next = waiting.shift();
      if (next) next();
      else active--;
    }
  }
  function call(route: string, paginate: boolean, fresh = false) {
    const key = (paginate ? "list:" : "get:") + route;
    if (fresh || !cached.has(key)) {
      cached.set(key, request([...(paginate ? ["--paginate", "--slurp"] : []), "repos/" + repo + "/" + route]));
    }
    return cached.get(key)!;
  }
  return {
    repo,
    async get(route, fresh) { return object(await call(route, false, fresh)); },
    async list(route, key, fresh) {
      const pages = await call(route, true, fresh);
      if (!Array.isArray(pages) || !pages.length) throw new Error("pagination");
      if (!key) return pages.flatMap(rows);
      const envelopes = pages.map(object);
      const result = envelopes.flatMap(page => rows(page[key]));
      if (envelopes.some(page => page.total_count !== result.length)) throw new Error("incomplete pagination");
      return result;
    },
  };
}
