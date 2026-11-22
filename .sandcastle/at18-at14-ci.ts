import { integer } from "./at18-format.ts";
import { object } from "./at18-github.ts";
import { rawJob, success } from "./at18-integrations.ts";
import { type At18Repository } from "./at18-source.ts";

export type RustLock = { name: string; target: string };

function section(lines: string[], key: string, indent: number) {
  const prefix = " ".repeat(indent);
  const headings = lines.map((l, i) => l.startsWith(prefix + key + ":") ? i : -1).filter(i => i >= 0);
  if (headings.length !== 1) return undefined;
  const start = headings[0];
  const end = lines.findIndex((line, i) => i > start && line.trim() !== "" && line.search(/\S/) <= indent);
  return { value: lines[start].slice(prefix.length + key.length + 1).trim(),
    rows: lines.slice(start + 1, end < 0 ? lines.length : end) };
}

function prTrigger(lines: string[]) {
  const on = section(lines, "on", 0) ?? section(lines, '"on"', 0) ?? section(lines, "'on'", 0);
  if (!on) return false;
  if (on.value) return /^(?:pull_request|\[[\w, ]*\bpull_request\b[\w, ]*\])$/.test(on.value);
  const pr = section(on.rows, "pull_request", 2);
  if (!pr) return false;
  if (pr.value) return pr.value === "{}";
  // 生产 Rust 改动不得被路径过滤；主线正常 PR 事件不得被收窄。
  return pr.rows.filter(l => l.trim()).every(l => /^ {4}branches:\s*\[\s*['"]?main['"]?\s*\]\s*$/.test(l)) ||
    pr.rows.map(l => l.trim()).filter(Boolean).join(" ") === "branches: - main";
}

function executes(command: string, target: string, name: string) {
  // 仅接受单条、可静态确定选择集的 Cargo 调用。脚本、shell 表达式及未知过滤不作证。
  const line = command.replaceAll('"\x24{CI_CARGO_JOBS:-1}"', "1");
  if (/[;&|<>`$\\#]/.test(line)) return false;
  const args = line.trim().split(/\s+/).map(token => token.replace(/^(['"])(.*)\1$/, "$2"));
  if (["../.github/scripts/run-cargo-with-telemetry.sh", "./.github/scripts/run-cargo-with-telemetry.sh"].includes(args[0])) args.shift();
  if (args.shift() !== "cargo" || args.shift() !== "test") return false;
  const features = new Set<string>(), targets = new Set<string>();
  let filter: string | undefined;
  let harness = false;
  let exact = false;
  for (let i = 0; i < args.length; i++) {
    const [flag, eq] = args[i].split("=", 2);
    if (flag === "--" && !harness) { harness = true; continue; }
    if (!harness) {
      if (["--release", "--locked", "--no-default-features"].includes(flag) && eq === undefined) continue;
      if (["--features", "--test", "--jobs", "-j"].includes(flag)) {
        const value = eq ?? args[++i];
        if (!value || !/^[\w,.-]+$/.test(value)) return false;
        if (flag === "--features") for (const feature of value.split(",")) features.add(feature);
        if (flag === "--test") targets.add(value);
        continue;
      }
    } else {
      if (flag === "--exact" && eq === undefined) { exact = true; continue; }
      if (["--test-threads", "--skip"].includes(flag)) {
        const value = eq ?? args[++i];
        if (!value || (flag === "--test-threads" ? !/^\d+$/.test(value) :
          !/^[\w:]+$/.test(value) || name.includes(value) || value.includes(name) || value.includes("::"))) return false;
        continue;
      }
      if (["--nocapture", "--show-output"].includes(flag) && eq === undefined) continue;
    }
    if (eq !== undefined || !/^[\w:]+$/.test(flag) || filter) return false;
    filter = flag;
  }
  return targets.has(target) && features.has("production_session") &&
    !["production_session_testonly", "backtest_bin"].some(f => features.has(f)) &&
    (!filter || (exact ? filter === name : name.includes(filter))) && (!exact || !!filter);
}

export function at14CiSteps(workflow: string, locks: RustLock[]) {
  const lines = workflow.split(/\r?\n/).filter(l => !l.trimStart().startsWith("#"));
  if (!prTrigger(lines)) return [];
  const jobs = section(lines, "jobs", 0);
  if (!jobs || jobs.value) return [];
  return jobs.rows.flatMap(line => {
    const name = /^ {2}([\w-]+):\s*$/.exec(line)?.[1];
    if (!name) return [];
    const job = section(jobs.rows, name, 2);
    if (!job || section(job.rows, "strategy", 4) || section(job.rows, "continue-on-error", 4)) return [];
    const when = section(job.rows, "if", 4)?.value;
    if (when && when !== "needs.changes.outputs.rust == 'true'") return [];
    const jobName = section(job.rows, "name", 4)?.value || name;
    const steps = section(job.rows, "steps", 4);
    if (!steps) return [];
    const blocks = steps.rows.join("\n").split(/^ {6}- /m).slice(1);
    return blocks.flatMap(block => {
      const body = block.split("\n");
      const named = /^name:\s*(.+)$/.exec(body[0])?.[1];
      if (!named || !blocks.every(other => other === block || other.split("\n")[0] !== body[0]) ||
          section(body, "continue-on-error", 8)) return [];
      const condition = section(body, "if", 8)?.value;
      if (condition && condition !== "\x24{{ !cancelled() && steps.setup.outcome == 'success' }}") return [];
      const command = section(body, "run", 8)?.value;
      if (!command) return [];
      const selected = locks.filter(lock => executes(command, lock.target, lock.name));
      return selected.length ? [{ jobName, stepName: named, command, locks: selected }] : [];
    });
  });
}

export async function recordedAt14Steps(s: At18Repository, runId: number, attempt: number, head: string,
  steps: ReturnType<typeof at14CiSteps>, locks: RustLock[]) {
  const rows = await s.github.list(`actions/runs/${runId}/attempts/${attempt}/jobs?per_page=100`, "jobs");
  const passed = new Set<string>();
  for (const jobName of new Set(steps.map(step => step.jobName))) {
    const selections = steps.filter(step => step.jobName === jobName);
    const matches = rows.filter(row => row.name === jobName);
    if (matches.length !== 1) continue;
    const raw = matches[0];
    const job = rawJob.parse(raw);
    if (job.run_id !== runId || job.run_attempt !== attempt || job.head_sha !== head || !success(job) ||
        !Array.isArray(raw.steps)) continue;
    const good = selections.filter(selection => {
      const steps = raw.steps;
      if (!Array.isArray(steps)) return false;
      const named = steps.map(object).filter(step => step.name === selection.stepName);
      return named.length === 1 && named[0].status === "completed" && named[0].conclusion === "success" &&
        integer.safeParse(named[0].number).success;
    });
    if (!good.length) continue;
    const log = await s.github.jobLog(job.id);
    const records = log.split(/\r?\n/).map(line => line
      .replace(/^\d{4}-\d\d-\d\dT\S+\s+/, "").replace(/\x1b\[[0-9;]*m/g, ""));
    for (const step of good) {
      // Actions 的 Run 分组只采与提交中实际命令相同的一段；其他步骤的同名输出不计。
      const command = "##[group]Run " + step.command;
      const starts = records.map((line, i) => line === command ? i : -1).filter(i => i >= 0);
      if (starts.length !== 1) continue;
      const end = records.findIndex((line, i) => i > starts[0] &&
        (/^##\[group\]Run /.test(line) || /^Post job cleanup/.test(line)));
      const transcript = records.slice(starts[0] + 1, end < 0 ? records.length : end);
      for (const { name, target } of step.locks) {
        const entries = transcript.map((line, i) => {
          const harness = /^\s*Running (?:rust\/)?tests\/([^\s]+)\s+\(/.exec(line)?.[1];
          return harness === target + ".rs" || harness === target + "/main.rs" ? i : -1;
        }).filter(i => i >= 0);
        if (entries.length !== 1) continue;
        const after = transcript.slice(entries[0] + 1);
        const summary = after.findIndex(line => /^test result: |^\s*Running /.test(line));
        if (summary < 0 || !after[summary].startsWith("test result: ok.")) continue;
        const observations = after.slice(0, summary).flatMap(line => {
          const test = /^test (?:[\w]+::)*([\w]+) \.\.\. (ok|ignored|FAILED)\s*$/.exec(line);
          return test?.[1] === name ? [test[2]] : [];
        });
        if (observations.length === 1 && observations[0] === "ok") passed.add(name);
      }
    }
  }
  return locks.every(lock => passed.has(lock.name));
}
