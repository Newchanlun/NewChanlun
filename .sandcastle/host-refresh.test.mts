/**
 * #1979 / #1988：automation host 自刷新只许快进，HEAD 上有 origin/main 没有的提交（部署候选或分叉）必须 fail-closed。
 * `git merge --ff-only` 在 HEAD 领先时返回 0，所以 claim-loop 与 arch_hotzone 都要显式数领先提交。
 * 跑法：npx tsx --test .sandcastle/host-refresh.test.mts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { refreshHostMain } from "./claim-loop.mts";

function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

function commit(cwd: string, msg: string): void {
  git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
    "commit", "-q", "--allow-empty", "-m", msg);
}

/** bare origin + host 克隆；host 本地多 ahead 个提交，origin 多 behind 个提交（两者都 >0 = 分叉）。 */
function fixture(ahead: number, behind: number): { root: string; host: string; seed: string } {
  const root = mkdtempSync(join(tmpdir(), "host-refresh-"));
  const origin = join(root, "origin.git");
  const seed = join(root, "seed");
  const host = join(root, "host");
  git(root, "init", "-q", "--bare", "-b", "main", origin);
  git(root, "init", "-q", "-b", "main", seed);
  commit(seed, "base");
  git(seed, "push", "-q", origin, "main");
  git(root, "clone", "-q", origin, host);
  for (let i = 0; i < ahead; i++) commit(host, `deploy${i}`);
  for (let i = 0; i < behind; i++) commit(seed, `upstream${i}`);
  git(seed, "push", "-q", origin, "main");
  return { root, host, seed };
}

function withAutoUpdate<T>(fn: () => T): T {
  const prev = process.env.SANDCASTLE_HOST_AUTO_UPDATE;
  process.env.SANDCASTLE_HOST_AUTO_UPDATE = "1";
  const quiet = console.error;
  console.error = () => {};
  try {
    return fn();
  } finally {
    console.error = quiet;
    if (prev === undefined) delete process.env.SANDCASTLE_HOST_AUTO_UPDATE;
    else process.env.SANDCASTLE_HOST_AUTO_UPDATE = prev;
  }
}

for (const [name, ahead, behind, ok] of [
  ["HEAD = origin/main → 放行", 0, 0, true],
  ["HEAD 落后 → 快进并放行", 0, 2, true],
  ["HEAD 领先（部署候选，#1979）→ fail-closed，部署提交保留", 1, 0, false],
  ["HEAD 分叉 → fail-closed，HEAD 不动", 1, 1, false],
] as const) {
  test(`claim-loop refreshHostMain：${name}`, () => {
    const f = fixture(ahead, behind);
    try {
      const before = git(f.host, "rev-parse", "HEAD");
      assert.equal(withAutoUpdate(() => refreshHostMain(f.host)), ok);
      const after = git(f.host, "rev-parse", "HEAD");
      assert.equal(after, ok ? git(f.seed, "rev-parse", "HEAD") : before);
    } finally {
      rmSync(f.root, { recursive: true, force: true });
    }
  });
}

test("arch_hotzone_monitor.sh --selftest（含宿主自刷新领先/分叉样例）全过", () => {
  const r = spawnSync("bash", ["scripts/arch_hotzone_monitor.sh", "--selftest"], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stdout, /HEAD 领先 origin\/main（部署候选）→ fail-closed/);
});
