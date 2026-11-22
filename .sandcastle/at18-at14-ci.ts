import { integer } from "./at18-format.ts";
import { object } from "./at18-github.ts";
import { rawJob, success } from "./at18-integrations.ts";
import { type At18Repository } from "./at18-source.ts";

export type RustLock = { name: string; target: string; selector?: string; features?: string[] };
const selectorOf = (lock: RustLock) => lock.selector ?? lock.name;

function withoutComment(line: string) {
  let quote = "";
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quote === '"' && c === "\\") { i++; continue; }
    if (c === quote) {
      if (quote === "'" && line[i + 1] === "'") { i++; continue; }
      quote = "";
    } else if (!quote) {
      if (c === "#" && (i === 0 || /\s/.test(line[i - 1]))) return line.slice(0, i).trimEnd();
      if ((c === '"' || c === "'") && (i === 0 || /[\s:[{,]/.test(line[i - 1]))) quote = c;
    }
  }
  return line.trimEnd();
}

function scalar(value: string): string {
  if (/^'(?:[^']|'')*'$/.test(value)) return value.slice(1, -1).replaceAll("''", "'");
  if (value.startsWith('"') && value.endsWith('"')) {
    try {
      const decoded: unknown = JSON.parse(value);
      if (typeof decoded === "string") return decoded;
    } catch { /* 不将未识别的标量猜成触发器或命令。 */ }
  }
  return value;
}
const field = (line: string) => /^ *(?:"([\w-]+)"|'([\w-]+)'|([\w-]+)):[ \t]*(.*)$/.exec(line);
const indentation = (line: string) => line.search(/\S/);
function childIndent(rows: string[]) {
  return rows.reduce((indent, row) => row.trim() ? Math.min(indent, indentation(row)) : indent, Infinity);
}


function section(lines: string[], key: string, indent: number) {
  const headings = lines.flatMap((line, i) => {
    const match = indentation(line) === indent ? field(line) : null;
    return match && (match[1] ?? match[2] ?? match[3]) === key ? [{ i, value: match[4] }] : [];
  });
  if (headings.length !== 1) return undefined;
  const [{ i, value }] = headings;
  const end = lines.findIndex((line, j) => j > i && line.trim() !== "" && indentation(line) <= indent);
  return { value, rows: lines.slice(i + 1, end < 0 ? lines.length : end) };
}

function prTrigger(lines: string[]) {
  const on = section(lines, "on", 0);
  if (!on) return false;
  if (on.value) {
    if (scalar(on.value) === "pull_request") return true;
    return /^\[[^\[\]{}]*\]$/.test(on.value) &&
      on.value.slice(1, -1).split(",").some(v => scalar(v.trim()) === "pull_request");
  }
  const rows = on.rows.filter(l => l.trim());
  const indent = childIndent(rows);
  if (rows.length && rows.every(l => indentation(l) === indent && l.trimStart().startsWith("- "))) {
    return rows.some(l => scalar(l.trim().slice(2)) === "pull_request");
  }
  const pr = section(rows, "pull_request", indent);
  if (!pr) return false;
  const options = pr.rows.filter(l => l.trim());
  if (pr.value) return !options.length && ["{}", "{ }", "null", "~"].includes(pr.value);
  if (!options.length) return true;
  // 只接受未收窄的普通 PR；禁止路径/事件等过滤器。同一语义支持 flow 与 block 序列。
  const optionIndent = childIndent(options);
  if (options.filter(row => indentation(row) === optionIndent && !row.trimStart().startsWith("- ")).length !== 1) return false;
  const branches = section(options, "branches", optionIndent);
  if (!branches) return false;
  const values = branches.rows.filter(l => l.trim());
  return branches.value
    ? !values.length && /^\[[^\[\]]*\]$/.test(branches.value) &&
        scalar(branches.value.slice(1, -1).trim().replace(/,$/, "").trim()) === "main"
    : values.length === 1 && /^-\s+/.test(values[0].trim()) && scalar(values[0].trim().replace(/^-\s+/, "")) === "main";
}

function executes(command: string, lock: RustLock) {
  const { target } = lock, name = selectorOf(lock);
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
          !/^[\w:]+$/.test(value) || name.includes(value))) return false;
        continue;
      }
      if (["--nocapture", "--show-output"].includes(flag) && eq === undefined) continue;
    }
    if (eq !== undefined || !/^[\w:]+$/.test(flag) || filter) return false;
    filter = flag;
  }
  return targets.has(target) && (lock.features ?? ["production_session"]).every(f => features.has(f)) &&
    !["production_session_testonly", "backtest_bin"].some(f => features.has(f)) &&
    (!filter || (exact ? filter === name : name.includes(filter))) && (!exact || !!filter);
}

export function at14CiSteps(workflow: string, locks: RustLock[]) {
  const lines = workflow.split(/\r?\n/).map(withoutComment);
  if (!prTrigger(lines)) return [];
  const jobs = section(lines, "jobs", 0);
  if (!jobs || jobs.value) return [];
  const jobsIndent = childIndent(jobs.rows);
  return jobs.rows.flatMap(line => {
    if (indentation(line) !== jobsIndent) return [];
    const match = field(line);
    const name = match?.[1] ?? match?.[2] ?? match?.[3];
    if (!name) return [];
    const job = section(jobs.rows, name, jobsIndent);
    if (!job || job.value) return [];
    const jobIndent = childIndent(job.rows);
    const jobField = (key: string) => section(job.rows, key, jobIndent);
    if (jobField("strategy") || jobField("continue-on-error")) return [];
    const when = jobField("if");
    if (when && scalar(when.value) !== "needs.changes.outputs.rust == 'true'") return [];
    const jobName = scalar(jobField("name")?.value ?? name);
    const steps = jobField("steps");
    if (!steps || steps.value) return [];
    const stepIndent = childIndent(steps.rows);
    const starts = steps.rows.flatMap((row, i) => indentation(row) === stepIndent && /^-(?: |$)/.test(row.trimStart()) ? [i] : []);
    const declared = starts.map((start, i) => {
      const first = steps.rows[start].trimStart().slice(1);
      const contents = steps.rows.slice(start + 1, starts[i + 1]);
      const indent = first.trim() ? stepIndent + first.search(/\S/) + 1 : childIndent(contents);
      const body = first.trim() ? [" ".repeat(indent) + first.trimStart(), ...contents] : contents;
      const stepField = (key: string) => section(body, key, indent);
      const condition = stepField("if");
      return {
        index: i, name: scalar(stepField("name")?.value ?? ""), command: scalar(stepField("run")?.value ?? ""),
        eligible: !stepField("continue-on-error") && (!condition ||
          scalar(condition.value) === "\x24{{ !cancelled() && steps.setup.outcome == 'success' }}"),
      };
    });
    return declared.flatMap(step => {
      if (!step.name || !step.eligible || !step.command ||
          declared.filter(other => other.name === step.name).length !== 1 ||
          declared.filter(other => other.command === step.command).length !== 1) return [];
      const selected = locks.filter(lock => executes(step.command, lock));
      return selected.length ? [{ jobName, stepName: step.name, command: step.command, locks: selected, index: step.index,
        stepCount: declared.length }] : [];
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
    const actual = raw.steps.map(object);
    const system = actual[0]?.name === "Set up job" && actual[0].number === 1;
    const leading = system ? (actual[1]?.name === "Set up runner" && actual[1].number === 2 ? 2 : 1) : 0;
    const good = selections.filter(selection => {
      const body = actual.slice(leading, leading + selection.stepCount);
      const selected = body[selection.index];
      // GitHub reserves the leading setup step; match both the declared ordinal and the API step number.
      return body.length === selection.stepCount && body.every((step, i) => step.number === i + leading + 1) &&
        selected?.name === selection.stepName && actual.filter(step => step.name === selection.stepName).length === 1 &&
        selected.status === "completed" && selected.conclusion === "success" && integer.safeParse(selected.number).success;
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
      for (const lock of step.locks) {
        const { name, target } = lock;
        const entries = transcript.map((line, i) => {
          const harness = /^\s*Running (?:rust\/)?tests\/([^\s]+)\s+\(/.exec(line)?.[1];
          return harness === target + ".rs" || harness === target + "/main.rs" ? i : -1;
        }).filter(i => i >= 0);
        if (entries.length !== 1) continue;
        const after = transcript.slice(entries[0] + 1);
        const summary = after.findIndex(line => /^test result: |^\s*Running /.test(line));
        if (summary < 0 || !after[summary].startsWith("test result: ok.")) continue;
        const observations = after.slice(0, summary).flatMap(line => {
          const test = /^test ((?:[\w]+::)*[\w]+) \.\.\. (ok|ignored|FAILED)\s*$/.exec(line);
          return test?.[1] === selectorOf(lock) ? [test[2]] : [];
        });
        if (observations.length === 1 && observations[0] === "ok") passed.add(name);
      }
    }
  }
  return locks.every(lock => passed.has(lock.name));
}
