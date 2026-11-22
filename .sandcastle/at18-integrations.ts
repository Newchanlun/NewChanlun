import { z } from "zod";
import { acceptanceJob, ciRun, conclusion, integer, review, sha, state, text, workflows } from "./at18-format.ts";
import { object, rows, type Row } from "./at18-github.ts";
import { type At18Repository, type Diagnostics, G0, P0, sorted, utf8 } from "./at18-source.ts";
import { unique, type Bindings } from "./at18-coverage.ts";

const parsedReview = z.object({ id: integer, state: review.shape.state, context: text,
  creator: z.object({ login: text }), created_at: text });
const issueShape = z.object({ number: integer, state: z.enum(["open", "closed"]),
  state_reason: z.string().nullable().optional(), labels: z.array(z.object({ name: text })), updated_at: text,
  pull_request: z.unknown().optional() });
const runShape = z.object({ id: integer, run_attempt: integer, workflow_id: integer, head_sha: sha, head_branch: text,
  status: text, conclusion: text.nullable(), event: text, html_url: text, path: text, updated_at: text,
  repository: z.object({ full_name: text }), head_repository: z.object({ full_name: text }) });
export const rawJob = z.object({ id: integer, name: text, run_id: integer, run_attempt: integer, head_sha: sha,
  status: text, conclusion: z.string().nullable(), labels: z.array(text).optional(),
  runner_group_name: z.string().nullable().optional() });
export type Job = z.infer<typeof rawJob>;
export type Selected = { run: z.infer<typeof runShape>; jobs: Job[] | undefined };
export type JobRef = z.infer<typeof acceptanceJob>;
export type ReviewRef = z.infer<typeof review>;
export type AcceptedReview = Row & { review_approved_at: string };

export const ciConclusion = (raw: string | null) => {
  const r = conclusion.safeParse(raw?.toUpperCase());
  return r.success ? r.data : null;
};
export const success = (row: { status: string; conclusion: string | null }) =>
  row.status === "completed" && row.conclusion === "success";
export function basename(path: string) { return path.split("/").at(-1)!; }
export const jobScope = (workflow: string, run: Selected | undefined, name: string) =>
  `job:${basename(workflow)}/${run?.run.id ?? "none"}/${name}`;

export async function selectRun(s: At18Repository, F: string, workflow: string, diag: Diagnostics, index: number, fresh = false) {
  return diag.get(`/workflow_runs/${index}`, async () => {
    const { id, path } = await s.github.get("actions/workflows/" + basename(workflow), fresh);
    if (path !== workflow || !integer.safeParse(id).success) throw new Error("workflow identity");
    const list = await s.github.list(`actions/workflows/${id}/runs?head_sha=${F}&branch=main&event=workflow_dispatch&per_page=100`, "workflow_runs", fresh);
    const candidates = z.array(runShape).parse(list);
    if (!unique(candidates.map(r => r.id)) || candidates.some(r => r.workflow_id !== id ||
      r.head_sha !== F || r.path !== workflow || r.head_branch !== "main" || r.event !== "workflow_dispatch" ||
      [r.repository, r.head_repository].some(repo => repo.full_name.toLowerCase() !== s.github.repo.toLowerCase()))) throw new Error("run identity");
    return candidates.sort((a, b) => b.id - a.id)[0] ?? null;
  });
}
export async function loadRuns(s: At18Repository, F: string, diag: Diagnostics) {
  const selected = await Promise.all(workflows.map((path, i) => selectRun(s, F, path, diag, i)));
  return Promise.all(selected.map(async (run, i): Promise<Selected | undefined> => {
    if (!run) return undefined;
    const jobs = await diag.get(`/workflow_runs/${i}`, async () => {
      const result = await s.github.list(`actions/runs/${run.id}/attempts/${run.run_attempt}/jobs?per_page=100`, "jobs");
      const projected = z.array(rawJob).parse(result);
      if (!unique(projected.map(j => j.id)) || projected.some(j => j.run_id !== run.id || j.run_attempt !== run.run_attempt ||
        j.head_sha !== F)) throw new Error("job identity");
      return projected;
    });
    return { run, jobs };
  }));
}
export class JobEvidence {
  readonly entries = new Map<string, JobRef>();
  private readonly ambiguous = new Set<string>();
  constructor(readonly runs: (Selected | undefined)[], readonly diag: Diagnostics) {}
  use(index: number, name: string) {
    const source = this.runs[index];
    const matches = source?.jobs?.filter(j => j.name === name) ?? [];
    const key = index + "\0" + name;
    if (matches.length > 1) {
      this.entries.delete(key);
      if (!this.ambiguous.has(key)) this.diag.add("SCHEMA", jobScope(workflows[index], source, name));
      this.ambiguous.add(key);
    }
    if (matches.length !== 1 || !source || this.ambiguous.has(key)) return undefined;
    const job = matches[0];
    const normalized = job.status === "completed" ? ciConclusion(job.conclusion) : null;
    if (job.status === "completed" && normalized === null) this.diag.add("SOURCE_UNAVAILABLE", jobScope(workflows[index], source, name));
    this.entries.set(key, {
      workflow: workflows[index], run_id: source.run.id, run_attempt: source.run.run_attempt,
      head_sha: source.run.head_sha, job: name, conclusion: normalized,
    });
    return job;
  }
}

function scalar(s: string): string {
  if (s.startsWith('"')) {
    const parsed: unknown = JSON.parse(s);
    return text.parse(parsed);
  }
  if (s.startsWith("'") && s.endsWith("'")) return s.slice(1, -1).replaceAll("''", "'");
  return s.trim();
}

// 只解读 F 的 ci.yml 所用受支持的 job/needs/name/strategy 子集；未知表达式不缩分母。
export function ciNames(content: string, jobs: Job[]): string[] {
  const jobLines = new Map<string, string[]>();
  let inJobs = false;
  let current: string | undefined;
  for (const line of content.split(/\r?\n/)) {
    if (line === "jobs:") { inJobs = true; continue; }
    if (!inJobs) continue;
    if (/^\S[^:]*:/.test(line) && !line.startsWith("#")) break;
    const job = /^  ([A-Za-z0-9_-]+):\s*(?:#.*)?$/.exec(line);
    if (job) {
      current = job[1];
      if (jobLines.has(current)) throw new Error("duplicate job");
      jobLines.set(current, []);
    } else if (current) jobLines.get(current)!.push(line);
  }
  const gate = jobLines.get("ci-ok");
  if (!gate) throw new Error("ci-ok");
  const needLines = gate.map((s, i) => s.startsWith("    needs:") ? i : -1).filter(i => i >= 0);
  if (needLines.length !== 1) throw new Error("needs");
  const needAt = needLines[0];
  const value = gate[needAt].slice("    needs:".length).trim();
  let ids: string[];
  if (!value) {
    ids = [];
    for (const line of gate.slice(needAt + 1)) {
      if (/^    [A-Za-z_-]/.test(line)) break;
      const match = /^      -\s+([A-Za-z0-9_-]+)\s*(?:#.*)?$/.exec(line);
      if (match) ids.push(match[1]);
      else if (line.trim() && !line.trim().startsWith("#")) throw new Error("needs list");
    }
  } else if (/^\[[^\[\]]+\]$/.test(value)) ids = value.slice(1, -1).split(",").map(s => scalar(s.trim()));
  else ids = [scalar(value)];
  if (!ids.includes("at18-registry-lint") || !unique(ids) || ids.includes("ci-ok")) throw new Error("needs incomplete");

  const result: string[] = [];
  for (const id of ["ci-ok", ...ids]) {
    const lines = jobLines.get(id);
    if (!lines) throw new Error("unknown job");
    const rawNames = lines.filter(row => row.startsWith("    name: "));
    if (rawNames.length > 1) throw new Error("duplicate name");
    const name = rawNames.length ? scalar(rawNames[0].slice("    name: ".length)) : id;
    const strategy = lines.findIndex(line => line.startsWith("    strategy:"));
    if (strategy < 0) {
      if (name.includes("${{")) throw new Error("unknown job name");
      result.push(name);
      continue;
    }
    if (lines[strategy].trim() !== "strategy:") throw new Error("unsupported strategy");
    const axis = lines.findIndex((line, i) => i > strategy && /^      matrix:\s*$/.test(line));
    if (axis < 0) throw new Error("matrix");
    const matrixLines = [];
    for (const line of lines.slice(axis + 1)) {
      if (/^ {0,6}\S/.test(line) && !line.trim().startsWith("#")) break;
      if (line.trim() && !line.trim().startsWith("#")) matrixLines.push(line);
    }
    const key = /\$\{\{\s*matrix\.([A-Za-z_][\w]*)\s*\}\}/g;
    const keys = [...name.matchAll(key)].map(m => m[1]);
    if (keys.length !== 1) throw new Error("matrix name");
    const col = keys[0];
    let values: string[];
    if (matrixLines[0] === "        include:") {
      values = matrixLines.filter(row => new RegExp(`^ {10}- ${col}: `).test(row))
        .map(row => scalar(row.slice(row.indexOf(":") + 1).trim()));
      if (matrixLines.filter(row => /^ {10}- /.test(row)).length !== values.length) throw new Error("matrix include");
    } else {
      const m = new RegExp(`^ {8}${col}: (.+)$`).exec(matrixLines[0] ?? "");
      if (!m || matrixLines.length !== 1) throw new Error("matrix dimensions");
      let vals = m[1];
      if (vals.includes("${{")) {
        const runners = lines.find(line => /^    runs-on: /.test(line));
        const expression = /^\$\{\{ fromJSON\((.+) && '(\[[^']+\])' \|\| '(\[[^']+\])'\) \}\}$/.exec(vals);
        if (!expression || !runners?.includes(expression[1] + " && 'boat-large/from=hc-ci-slim' || 'ubuntu-latest'")) throw new Error("runner plans");
        const prefix = name.split("${{")[0];
        const instances = jobs.filter(j => j.name.startsWith(prefix));
        const modes = instances.map(j => j.labels?.some(l => l.startsWith("boat-large/")) ? "boat" :
          j.labels?.includes("ubuntu-latest") ? "standard" : "unknown");
        if (!modes.length || !unique([...new Set(modes)]) || new Set(modes).size !== 1 || modes[0] === "unknown") throw new Error("runner type");
        vals = expression[modes[0] === "boat" ? 2 : 3];
      }
      const parsed: unknown = JSON.parse(vals);
      if (!Array.isArray(parsed) || parsed.some(v => typeof v !== "string" && !Number.isSafeInteger(v))) throw new Error("matrix values");
      values = parsed.map(String);
    }
    if (!values.length || !unique(values)) throw new Error("matrix unique");
    for (const v of values) {
      const instance = name.replace(key, () => v);
      if (instance.includes("${{")) throw new Error("matrix role");
      result.push(instance);
    }
  }
  if (!unique(result)) throw new Error("duplicate rendered job names");
  return result;
}
export function checkWorkflows(s: At18Repository, F: string, evidence: JobEvidence, b: Bindings, registrySha: string | undefined) {
  const ci: z.infer<typeof ciRun>[] = [];
  let ok = true;
  for (const i of [0, 1]) {
    const run = evidence.runs[i];
    const workflow = workflows[i];
    if (run) ci.push({ workflow, run_id: run.run.id, run_attempt: run.run.run_attempt,
      head_sha: run.run.head_sha, conclusion: run.run.status === "completed" ? ciConclusion(run.run.conclusion) : null, url: run.run.html_url });
    let names: string[] | undefined;
    try {
      const bytes = s.blob(F, workflow);
      const source = utf8(bytes);
      if (!/^ {2}workflow_dispatch:\s*(?:\{\})?\s*$/m.test(source)) throw new Error("dispatch");
      names = i === 0 ? ciNames(source, run?.jobs ?? []) : ["DevSkim"];
    } catch { evidence.diag.add("HEAD_CI", `/workflow_runs/${i}`); ok = false; }
    if (!run || !success(run.run)) { evidence.diag.add("HEAD_CI", `/workflow_runs/${i}`); ok = false; }
    for (const name of names ?? []) {
      const j = evidence.use(i, name);
      if (!j || !success(j)) {
        ok = false; evidence.diag.add("HEAD_CI", jobScope(workflow, run, name));
      }
    }
  }
  const passed = new Set<string>();
  const failed = new Set<string>();
  const executed = new Set<string>();
  const checkJobs = new Map<string, Job>();
  for (const [group, checks] of b.groups) {
    const i = checks[0].evidence_class === "experiment" ? 3 : 2;
    const run = evidence.runs[i];
    const name = "at18 " + group + " " + (registrySha ?? "none");
    const scope = jobScope(workflows[i], run, name);
    const job = evidence.use(i, name);
    if (job) checkJobs.set(group, job);
    if (job && job.status === "completed" && job.conclusion !== "skipped") executed.add(group);
    if (!job) evidence.diag.add("CHECK_JOB_MISSING", scope);
    else if (!success(job) || !run || !success(run.run)) {
      evidence.diag.add("CHECK_JOB_FAILED", scope);
      failed.add(group);
    } else if (checks.every(c => !b.invalidChecks.has(c.check_id))) passed.add(group);
  }
  for (const i of [2, 3]) {
    try {
      const workflow = utf8(s.blob(F, workflows[i]));
      if (!/^ {2}workflow_dispatch:\s*(?:\{\})?\s*$/m.test(workflow) || !evidence.runs[i] || !success(evidence.runs[i]!.run)) throw new Error("run");
    } catch { evidence.diag.add("CHECK_JOB_MISSING", `/workflow_runs/${i}`); }
  }
  return { ci, ok, passed, failed, executed, checkJobs };
}

function repoMatches(value: unknown, repo: string) {
  try { const full = object(value).full_name; return typeof full === "string" && full.toLowerCase() === repo.toLowerCase(); }
  catch { return false; }
}
export function mainPr(value: Row, commit: string, repo: string) {
  try { const base = object(value.base); return value.merged === true && value.merge_commit_sha === commit &&
    base.ref === "main" && repoMatches(base.repo, repo); } catch { return false; }
}
export async function integrationReviews(s: At18Repository, F: string, diag: Diagnostics) {
  let chain: string[] = [];
  try {
    if (s.string("rev-parse", "--is-shallow-repository") !== "false") throw new Error("history");
    chain = s.chain(F, P0);
    if (chain.at(-1) !== G0 || s.string("rev-parse", G0 + "^1") !== P0) throw new Error("G0");
  } catch { diag.add("REVIEW_FINAL_PRODUCT", "/head"); return { chain: [], accepted: new Map<string, AcceptedReview>(), reviews: [], ok: false }; }
  const accepted = new Map<string, AcceptedReview>();
  const refs = await Promise.all(chain.map(async (M, i) => {
    const scope = "commit:" + M;
    const fail = () => { diag.add("REVIEW_FINAL_PRODUCT", scope); return undefined; };
    let H: string;
    try {
      const parents = s.string("show", "-s", "--format=%P", M).split(" ");
      if (parents.length !== 2 || parents[0] !== (chain[i + 1] ?? P0)) return fail();
      H = parents[1];
      if (s.string("rev-parse", M + "^{tree}") !== s.string("rev-parse", H + "^{tree}")) return fail();
    } catch { return fail(); }
    const pr = await diag.get(scope, async () => {
      const linked = await s.github.list(`commits/${M}/pulls?per_page=100`);
      const candidates = linked.filter(p => p.merge_commit_sha === M);
      const official = (await Promise.all(candidates.map(p => s.github.get("pulls/" + integer.parse(p.number)))))
        .filter(p => mainPr(p, M, s.github.repo) && object(p.head).sha === H);
      return official.length === 1 ? official[0] : undefined;
    });
    if (!pr || !integer.safeParse(pr.number).success) return fail();
    const statuses = await diag.get(scope, () => s.github.list(`commits/${H}/statuses?per_page=100`));
    const latest = statuses?.find(r => r.context === "deepagents/review");
    const parsed = parsedReview.safeParse(latest);
    if (!parsed.success || !utcBefore(parsed.data.created_at, pr.merged_at)) return fail();
    const { id, state, creator } = parsed.data;
    if (state !== "success" || creator.login !== "newchanlun-review-gate[bot]") fail();
    else accepted.set(M, { ...pr, review_approved_at: parsed.data.created_at });
    return { pr: integer.parse(pr.number), reviewed_head: H, merge_commit: M, status_id: id, creator: creator.login, state };
  }));
  return { chain, accepted,
    reviews: refs.filter((r): r is ReviewRef => r !== undefined).sort((a, b) => a.merge_commit.localeCompare(b.merge_commit) || a.pr - b.pr || a.status_id - b.status_id),
    ok: accepted.size === chain.length && !!chain.length };
}
export function utcBefore(a: unknown, b: unknown) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const stamp = (input: string) => /^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?Z$/.exec(input);
  const ma = stamp(a), mb = stamp(b);
  if (!ma || !mb || !Number.isFinite(Date.parse(a)) || !Number.isFinite(Date.parse(b))) return false;
  if (ma[1] !== mb[1]) return ma[1] < mb[1];
  const p = Math.max(ma[2]?.length ?? 0, mb[2]?.length ?? 0);
  return (ma[2] ?? "").padEnd(p, "0") < (mb[2] ?? "").padEnd(p, "0");
}

export type Ticket = { number: number; state: z.infer<typeof state>; reason: null | "COMPLETED" | "NOT_PLANNED" | "REOPENED" | "DUPLICATE";
  labels: string[]; updated_at: string | null; data: Row | undefined };
export class Tracker {
  private readonly seen = new Map<number, Promise<Ticket>>();
  private readonly lists = new Map<number, Promise<number[] | undefined>>();
  constructor(readonly s: At18Repository, readonly diag: Diagnostics) {}
  private async read(n: number, fresh = false): Promise<Ticket> {
    const scope = "ticket:" + n;
    const got = await this.diag.get(scope, async () => {
      const data = await this.s.github.get("issues/" + n, fresh);
      const p = issueShape.parse(data);
      if (n !== p.number || p.pull_request !== undefined) throw new Error("ticket identity");
      return { data, p };
    });
    if (!got) return { number: n, state: null, reason: null, labels: [], updated_at: null, data: undefined };
    const mapped = got.p.state_reason?.toUpperCase();
    const reason = mapped === "COMPLETED" || mapped === "NOT_PLANNED" || mapped === "REOPENED" || mapped === "DUPLICATE" ? mapped : null;
    if (mapped && !reason) this.diag.add("SCHEMA", scope);
    return { number: n, state: got.p.state === "open" ? "OPEN" : "CLOSED", reason: got.p.state === "open" ? null : reason,
      labels: sorted(got.p.labels.map(l => l.name)), updated_at: got.p.updated_at, data: got.data };
  }
  issue(n: number) {
    if (!this.seen.has(n)) this.seen.set(n, this.read(n));
    return this.seen.get(n)!;
  }
  private readChildren(n: number, fresh = false) {
    return this.diag.get("ticket:" + n, async () => {
      const list = await this.s.github.list(`issues/${n}/sub_issues?per_page=100`, undefined, fresh);
      const ids = list.map(i => integer.parse(i.number)).sort((a, b) => a - b);
      if (!unique(ids) || ids.includes(n)) throw new Error("subissue identity");
      return ids;
    });
  }
  children(n: number) {
    if (!this.lists.has(n)) this.lists.set(n, this.readChildren(n));
    return this.lists.get(n)!;
  }
  async native(n: number) {
    const direct = await this.children(n);
    if (!direct) return [];
    const tickets = await Promise.all(direct.map(t => this.issue(t)));
    return tickets.filter(t => t.labels.includes("wayfinder:impl"));
  }
  async stable() {
    await Promise.all([
      ...[...this.seen].map(async ([n, old]) => {
        const [a, b] = await Promise.all([old, this.read(n, true)]);
        if (a.updated_at !== b.updated_at || a.state !== b.state || a.reason !== b.reason ||
            a.labels.join("\0") !== b.labels.join("\0")) this.diag.add("WINDOW_DRIFT", "ticket:" + n);
      }),
      ...[...this.lists].map(async ([n, old]) => {
        const [a, b] = await Promise.all([old, this.readChildren(n, true)]);
        if (a?.join(",") !== b?.join(",")) this.diag.add("WINDOW_DRIFT", "ticket:" + n);
      }),
    ]);
  }
}

export async function proveExternalHead(s: At18Repository, h: string, F: string, diag: Diagnostics, scope: string) {
  try { if (s.ancestor(h, F)) return true; } catch { /* squash 不一定保留原 head */ }
  const proven = await diag.get(scope, async () => {
    const prs = await s.github.list(`commits/${h}/pulls?per_page=100`);
    const details = await Promise.all(prs.map(p => s.github.get("pulls/" + integer.parse(p.number))));
    return details.some(p => typeof p.merge_commit_sha === "string" && mainPr(p, p.merge_commit_sha, s.github.repo) &&
      object(p.head).sha === h && s.ancestor(p.merge_commit_sha, F));
  });
  if (!proven) diag.add("ANCESTRY", scope);
  return !!proven;
}
