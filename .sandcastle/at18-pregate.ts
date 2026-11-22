import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import { censusSchema, type Landing, type Registry } from "./at18-contract.ts";
import { byteSha256, canonicalizeJcs, historicalDeviation, integer, parseJsonObject, sha, tbId, text, workflows } from "./at18-format.ts";
import { mainPr, ciConclusion, Tracker } from "./at18-integrations.ts";
import { object, type Row } from "./at18-github.ts";
import {
  at18, compare, type At18Repository, type Diagnostics, P0, sorted, utf8,
} from "./at18-source.ts";
import { unique, type Bindings } from "./at18-coverage.ts";

const historyRow = z.object({ commit: sha, parent: sha.nullable(), epoch: z.int(), subject: z.string() });
type GitHistoryRow = z.infer<typeof historyRow> & { parents: string[]; body: string };

export function verifyPregateHistory(s: At18Repository, bytes: Buffer): GitHistoryRow[] {
  const published = utf8(bytes).trimEnd().split("\n").map(row => historyRow.parse(parseJsonObject(Buffer.from(row))));
  const physical = s.chain(P0);
  const fields = utf8(s.git("log", "-z", "--first-parent", "--format=%H%x00%P%x00%ct%x00%s%x00%b", P0)).split("\0");
  if (published.length !== physical.length || fields.length !== 5 * physical.length + 1) throw new Error("full history");
  return published.map((h, i) => {
    const [commit, parentList, epoch, subject, body] = fields.slice(i * 5, i * 5 + 5);
    const parents = parentList.split(" ").filter(Boolean);
    if (h.commit !== physical[i] || h.commit !== commit || h.parent !== (physical[i + 1] ?? null) ||
        h.parent !== (parents[0] ?? null) || h.epoch !== Number(epoch) || h.subject !== subject) throw new Error("nonmatching git history");
    return { ...h, parents, body };
  });
}
const native = z.object({ number: integer, parent: integer.nullable(), impl: z.boolean() });
const relations = z.object({ issues: z.array(native), followups: z.array(integer),
  pull_requests: z.array(z.object({ number: integer, base: text, commit: sha.nullable(), merged_at: text.nullable(),
    owners: z.array(integer), closing: z.array(integer) })),
  issue_evidence: z.record(z.string(), z.array(z.object({ url: text, commits: z.array(sha), prs: z.array(integer) }))),
});
const signal = z.object({ commit: sha, parent: sha.nullable(), epoch: z.int(), subject: z.string(),
  prs: z.array(integer), declared: z.array(integer), mentions: z.array(integer),
  references: z.array(z.object({ ticket: integer, url: text })), tb_markers: z.array(text) });
const associated = z.object({ ticket: integer, commit: sha, source: text });
const adjudication = z.object({ admitted_related: z.record(z.string(), z.object({ source: text })),
  additional_associations: z.array(associated), rejected_signals: z.array(associated) });

export async function replayPregate(s: At18Repository, F: string, registry: Registry, pre: z.infer<
  typeof import("./at18-contract.ts").pregateSchema>, chain: string[], accepted: Map<string, Row>,
  tracker: Tracker, diag: Diagnostics) {
  const projection: Pick<Landing, "ticket" | "commits" | "attribution_scopes">[] = [];
  const scope = "/pregate_review_ref";
  const fail = (check = "PREGATE_LANDINGS", target = scope) => diag.add(check, target);
  let verified = true;
  const path = at18 + "landing-census.json";
  function requireAnchor(path: string) {
    const changedAt = s.anchor(path, chain);
    if (!changedAt || !accepted.has(changedAt)) {
      fail("REVIEW_FINAL_PRODUCT", changedAt ? "commit:" + changedAt : "pre:" + path);
      fail("PREGATE_REVIEW", "pre:" + path);
      throw new Error("anchor");
    }
  }
  try {
    requireAnchor(path);
    requireAnchor(at18 + "pregate-review.json");
    const bytes = s.blob(F, path);
    if (byteSha256(bytes) !== registry.pregate.census_sha256) throw new Error("census hash");
    const census = censusSchema.parse(parseJsonObject(bytes));
    if (census.p0 !== P0 || !unique(census.sources.map(row => row.role)) ||
        !unique(census.sources.map(row => row.path))) throw new Error("census roles");
    const sources = Object.fromEntries(census.sources.map(row => {
      requireAnchor(row.path);
      const data = s.blob(F, row.path);
      if (!data.length || byteSha256(data) !== row.sha256) throw new Error("census source hash");
      return [row.role, data];
    }));
    const history = verifyPregateHistory(s, sources.history);
    const byCommit = new Map(history.map(h => [h.commit, h]));
    const relation = relations.parse(parseJsonObject(sources.relations));
    const judgment = adjudication.parse(parseJsonObject(sources.adjudication));
    const rawSignals = parseJsonObject(Buffer.from('{"items":' + utf8(sources.signals) + "}")).items;
    canonicalizeJcs(rawSignals);
    const signals = z.array(signal).parse(rawSignals);
    if (!unique(relation.issues.map(i => i.number)) || !unique(relation.pull_requests.map(i => i.number)) ||
        !unique(signals.map(i => i.commit)) || !unique(relation.followups) ||
        Object.keys(judgment.admitted_related).sort().join(",") !== relation.followups.map(String).sort().join(",")) throw new Error("census identity");
    const known = new Set([...Array.from({ length: 10 }, (_, i) => i + 1359), 1493,
      ...relation.issues.filter(i => i.impl).map(i => i.number), ...relation.followups]);
    const parents = new Map(relation.issues.map(i => [i.number, i.parent] as const));
    // #1493 的正式改挂必须由当窗 tracker 核实，不能由清册代填。
    if (!(await tracker.children(1360))?.includes(1493)) throw new Error("1493 reparenting");
    parents.set(1493, 1360);
    // 不能同时从清册与 registry 删掉一张已有归属的原生实施票。
    const todo = [1323, 1340, ...Array.from({ length: 10 }, (_, i) => 1359 + i)];
    const walked = new Set<number>();
    const liveParent = new Map<number, number>();
    const p0Time = Number(s.string("show", "-s", "--format=%ct", P0)) * 1000;
    while (todo.length) {
      const parent = todo.shift()!;
      if (walked.has(parent)) continue;
      walked.add(parent);
      const children = await tracker.children(parent);
      if (!children) throw new Error("native source absent");
      const entries = await Promise.all(children.map(async n => [n, await tracker.issue(n)] as const));
      for (const [n, issue] of entries) {
        if (!issue.data || (liveParent.has(n) && liveParent.get(n) !== parent) || n === 1323) throw new Error("native ambiguity");
        liveParent.set(n, parent);
        const impl = issue.labels.includes("wayfinder:impl");
        const reported = relation.issues.find(i => i.number === n);
        if (reported && reported.parent !== null && n !== 1493 && reported.parent !== parent) throw new Error("native scope drift");
        if (impl && !reported) {
          const addedAt = Date.parse(String(issue.data.created_at ?? ""));
          if (!Number.isFinite(addedAt) || addedAt <= p0Time) {
            fail("PREGATE_LANDINGS", "ticket:" + n);
            throw new Error("unadjudicated native product");
          }
        }
        if ((impl && (parent === 1323 || parent === 1340)) || (parent !== 1323 && parent !== 1340 && n !== 1369)) todo.push(n);
      }
    }
    const prIndex = new Map(relation.pull_requests.map(p => [p.number, p]));
    const signalsIndex = new Map(signals.map(row => [row.commit, row]));
    const prsByCommit = new Map<string, typeof relation.pull_requests>();
    for (const q of relation.pull_requests) {
      if (q.commit && q.base === "main" && q.merged_at && byCommit.has(q.commit)) {
        const matches = prsByCommit.get(q.commit) ?? [];
        matches.push(q);
        prsByCommit.set(q.commit, matches);
      }
    }
    const ownership = new Map<string, Set<number>>();
    const d = new Map<string, string[]>();
    const add = (m: string, t: number) => {
      const members = ownership.get(m) ?? new Set<number>();
      if (members.has(t)) return false;
      members.add(t);
      ownership.set(m, members);
      return true;
    };
    function leading(subject: string) {
      const m = /^(?:(?:[\w.-]+(?:\([^()]*\))?|Sandcastle)\s*[: ]\s*)?(?:[\[(]\s*)?(#[0-9]+(?:[ ,/#、，]+#?[0-9]+)*)/i.exec(subject);
      return [...(m?.[1].matchAll(/[0-9]+/g) ?? [])].map(m => Number(m[0]));
    }
    function parseOwners(pr: Row) {
      const h = object(pr.head);
      const ref = typeof h.ref === "string" ? h.ref : "";
      const branch = /^(?:(?:codex|opus|claude|sandcastle|fix|impl|feat|decision)\/)*(?:issue[-/]?)?([0-9]+)(?:[-_/]|$)/i.exec(ref);
      const title = typeof pr.title === "string" ? pr.title : "";
      return new Set([...(branch ? [Number(branch[1])] : []), ...leading(title)]);
    }
    for (const h of history) {
      const line = signalsIndex.get(h.commit);
      // 独立重算 Git 原文申明与清册登记 PR 的归属；状态不参与。
      const m = [...h.body.matchAll(/^(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|part of)\s+#([1-9][0-9]*)/gim)].map(r => Number(r[1]));
      const declared = sorted([...leading(h.subject), ...m, ...(prsByCommit.get(h.commit) ?? []).flatMap(p => [...p.owners, ...p.closing])]
        .filter(n => known.has(n)).map(String)).map(Number).sort((a, b) => a - b);
      if (declared.length && !line) throw new Error("undeclared history");
      if (!line) continue;
      if (line.parent !== (h.parents[0] ?? null) || line.epoch !== h.epoch || line.subject !== h.subject ||
          !unique(line.declared) || !unique(line.prs) ||
          [...line.declared].sort((a, b) => a - b).join(",") !== declared.join(",") ||
          line.prs.some(p => prIndex.get(p)?.commit !== h.commit)) throw new Error("candidate drift");
      for (const n of declared) add(h.commit, n);
    }
    if (signals.some(row => !byCommit.has(row.commit))) throw new Error("non-history candidate");
    const sourceCache = new Map<string, Promise<Row | undefined>>();
    async function resolveLocator(url: string) {
      const match = /^https:\/\/github\.com\/(?:Newchanlun|xy7365527-lang)\/NewChanlun\/(issues|pull)\/([1-9]\d*)(?:#issuecomment-([1-9]\d*))?$/i.exec(url);
      if (!match) return undefined;
      if (match[3]) {
        const result = await diag.get(scope, () => s.github.get("issues/comments/" + match[3]));
        return result?.id === Number(match[3]) &&
          typeof result.issue_url === "string" && result.issue_url.toLowerCase().endsWith(`/repos/${s.github.repo.toLowerCase()}/issues/${match[2]}`) ? result : undefined;
      }
      if (match[1] === "pull") {
        const result = await diag.get(scope, () => s.github.get("pulls/" + match[2]));
        return result?.number === Number(match[2]) ? result : undefined;
      }
      return (await tracker.issue(Number(match[2]))).data;
    }
    const locator = (url: string) => {
      if (!sourceCache.has(url)) sourceCache.set(url, resolveLocator(url));
      return sourceCache.get(url)!;
    };
    const proves = (original: Row, ticket: number, h: GitHistoryRow, prs: number[]) => {
      const material = [original.body, original.title].filter((s): s is string => typeof s === "string").join("\n");
      const t = new RegExp(`(?:#|/issues/)${ticket}(?![0-9])`);
      const originTicket = original.number === ticket || (typeof original.issue_url === "string" && original.issue_url.endsWith("/issues/" + ticket));
      return (originTicket || t.test(material) || (original.merge_commit_sha === h.commit && parseOwners(original).has(ticket))) &&
        (original.merge_commit_sha === h.commit || new RegExp(`(?:^|[^0-9a-f])${h.commit.slice(0, 7)}[0-9a-f]{0,33}(?![0-9a-f])`, "im").test(material) ||
          prs.some(p => new RegExp(`(?:#|/pull/)${p}(?![0-9])`).test(material)));
    };
    for (const a of judgment.additional_associations) {
      const h = byCommit.get(a.commit);
      const doc = await locator(a.source);
      const actual = h && doc && (proves(doc, a.ticket, h, signalsIndex.get(a.commit)?.prs ?? []) ||
        // 补修承接可用同一票原件对提交的已审固定出处配对。
        (relation.issue_evidence[String(a.ticket)] ?? []).some(e => e.url === a.source &&
          (e.commits.includes(a.commit) || e.prs.some(p => prIndex.get(p)?.commit === a.commit))));
      if (!actual || !known.has(a.ticket) || !add(a.commit, a.ticket)) throw new Error("attribution");
    }
    for (const a of judgment.rejected_signals) {
      if (!await locator(a.source) || !ownership.get(a.commit)?.delete(a.ticket)) throw new Error("unbound exclusion");
    }
    for (const [M, tickets] of ownership) {
      if (!tickets.size) continue;
      const h = byCommit.get(M)!;
      if (!h.parents[0]) throw new Error("unbound root product");
      d.set(M, s.changed(h.parents[0], M));
      if (!d.get(M)?.length) throw new Error("empty landing");
      const official = await Promise.all((prsByCommit.get(M) ?? []).map(pr => diag.get("commit:" + M,
        () => s.github.get("pulls/" + pr.number))));
      for (const [i, candidate] of (prsByCommit.get(M) ?? []).entries()) {
        const actual = official[i];
        if (!actual || !mainPr(actual, M, s.github.repo) ||
            candidate.owners.some(n => !parseOwners(actual).has(n)) ||
            candidate.closing.some(n => !(new RegExp(`\\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\\s+(?:#|https://github\\.com/[^/]+/[^/]+/issues/)${n}(?![0-9])`, "i")
              .test(String(actual.body ?? ""))))) throw new Error("PR drift");
      }
    }
    const commitsByTicket = new Map<number, string[]>();
    for (const [commit, tickets] of ownership) for (const ticket of tickets) {
      const items = commitsByTicket.get(ticket) ?? [];
      items.push(commit);
      commitsByTicket.set(ticket, items);
    }
    if (!commitsByTicket.size) throw new Error("empty ledger");
    let prior = 0;
    const attributions = new Map<number, typeof census.attributions[number]>();
    for (const row of census.attributions) {
      if (row.ticket <= prior || !commitsByTicket.has(row.ticket) ||
          sorted(row.sources).join("\0") !== row.sources.join("\0") ||
          sorted(row.attribution_scopes).join("\0") !== row.attribution_scopes.join("\0") ||
          (row.attribution_scopes.includes("GRAPH") && row.attribution_scopes.length !== 1) ||
          (await Promise.all(row.sources.map(locator))).some(r => !r)) throw new Error("scope evidence");
      prior = row.ticket;
      attributions.set(row.ticket, row);
    }
    for (const [ticket, commits] of [...commitsByTicket].sort(([a], [b]) => a - b)) {
      const seen = new Set<number>();
      let cursor: number | null = ticket;
      let native: Landing["attribution_scopes"][number] | undefined;
      while (cursor !== null) {
        if (seen.has(cursor)) throw new Error("native cycle");
        seen.add(cursor);
        if (cursor >= 1359 && cursor <= 1368) {
          native = tbId.exclude(["TB-11"]).parse("TB-" + String(cursor - 1358).padStart(2, "0"));
          break;
        }
        if (cursor === 1323 || cursor === 1340) break;
        if (!parents.has(cursor)) throw new Error("missing native parent");
        const parent: number | null = parents.get(cursor) ?? null;
        if (parent !== null && !(await tracker.children(parent))?.includes(cursor)) throw new Error("native parent drift");
        cursor = parent;
      }
      const extra = attributions.get(ticket)?.attribution_scopes ?? [];
      if ((!native && !extra.length) || (native && (extra.includes(native) || extra.includes("GRAPH")))) {
        fail("PREGATE_LANDINGS", "ticket:" + ticket);
        verified = false;
        continue;
      }
      const scopes = [...extra, ...(native ? [native] : [])].sort(compare);
      projection.push({ ticket, commits: sorted(commits), attribution_scopes: scopes });
    }
    const declared = registry.pregate.landings.map(({ ticket, commits, attribution_scopes }) => ({
      ticket, commits: sorted(commits), attribution_scopes,
    })).sort((a, b) => a.ticket - b.ticket);
    const actual = new Map(projection.map(p => [p.ticket, p]));
    for (const ticket of new Set([...declared.map(p => p.ticket), ...actual.keys()])) {
      const found = declared.filter(p => p.ticket === ticket);
      if (found.length !== 1 || !actual.has(ticket) || canonicalizeJcs(found[0]) !== canonicalizeJcs(actual.get(ticket))) {
        fail("PREGATE_LANDINGS", "ticket:" + ticket); verified = false;
      }
    }
    const previous = s.tree(P0);
    const end = s.tree(F);
    const expected = new Set([...d.values()].flat().filter(path => previous.has(path) && end.has(path)));
    const rows = new Map<string, number>();
    for (const row of pre.rows) {
      rows.set(row.path, (rows.get(row.path) ?? 0) + 1);
      const start = previous.get(row.path);
      if (!expected.has(row.path) || rows.get(row.path) !== 1 || row.verdict !== "PASS" ||
          start?.kind !== "blob" || end.get(row.path)?.kind !== "blob" || start.mode !== row.mode || start.oid !== row.blob) {
        fail("PREGATE_REVIEW", "pre:" + row.path); verified = false;
      }
    }
    for (const path of expected) if (!rows.has(path)) { fail("PREGATE_REVIEW", "pre:" + path); verified = false; }
    const owner = await tracker.issue(2132);
    if (owner.state !== "CLOSED" || owner.reason !== "COMPLETED") { fail("PREGATE_REVIEW", "ticket:2132"); verified = false; }
  } catch { fail(); verified = false; }
  return { projection, ok: verified };
}

// #2132 d896e31b 的具名失败目标是分母，不允许登记册通过删掉一项缩分母。
const historicalTargets = z.array(z.strictObject({
  ticket: integer, run_id: integer,
  targets: z.array(z.strictObject({ kind: z.enum(["step", "test"]), target: text, check_id: text })).min(1),
})).parse(JSON.parse(readFileSync(resolve(__dirname, "fixtures/at18/pregate-cure-targets.json"), "utf8")));
const cureId = (cure: Pick<Landing["cure_checks"][number], "kind" | "target" | "check_id">) =>
  [cure.kind, cure.target, cure.check_id].join("\0");
const historicalDenominator = new Map(historicalTargets.map(row => [
  `${row.ticket}/${row.run_id}`, row.targets.map(cureId),
]));

const fixed = new Map([
  [1392, ["8619a20f2800095e6bb9ec20ba2607a744740f91", "m3_partition_synthetic_holds"]],
  [1404, ["f95a7f3ebc0ce84ec2d2f8a8d71b5030b19f89b9", "calibration_sweep_finds_non_collapsed_segments"]],
  [1414, ["465174240b989a1d99f99a047fbb46b3ee215f49", "seam_btc_tick_bars_yield_non_trivial_structure"]],
]);
export async function historyDeviations(s: At18Repository, landings: Pick<Landing, "ticket" | "commits">[], reg: Registry | undefined,
  b: Bindings, passed: Set<string>, diag: Diagnostics) {
  const rows: z.infer<typeof historicalDeviation>[] = [];
  const failedTickets = new Set<number>();
  const lookup = (ticket: number, commit: string) => reg?.pregate.landings.find(l => l.ticket === ticket)?.cure_checks.filter(c => c.commit === commit) ?? [];
  const cured = (cure: Landing["cure_checks"][number]) => {
    const check = b.checks.get(cure.check_id);
    if (!check || check.expected_count !== 1 || !passed.has(check.group)) return false;
    if (cure.kind === "step") return check.runner === "command" && check.key_aware;
    const selected = check.runner === "cargo-test" ? check.selector.split("/").at(-1) : check.selector;
    return check.runner !== "command" && (selected === cure.target || selected?.endsWith("::" + cure.target));
  };
  const fail = (ticket: number, scope: string) => {
    diag.add("DEVIATION_NOT_CURED", scope);
    failedTickets.add(ticket);
  };
  for (const [ticket, [commit, target]] of fixed) {
    if (!landings.some(l => l.ticket === ticket && l.commits.includes(commit)) ||
        !lookup(ticket, commit).some(c => c.run_id === null && c.kind === "test" && c.target === target && cured(c))) {
      fail(ticket, `history:${ticket}/${commit}/ci.yml/none`);
    }
  }
  if (!landings.length) return { rows, failedTickets };
  const runs = new Map<string, Promise<unknown>>();
  const historyRun = z.object({ id: integer, conclusion: z.string().nullable(), status: text, head_sha: sha,
    event: z.literal("push"), head_branch: z.literal("main"), workflow_id: integer });
  const wids = await Promise.all(workflows.slice(0, 2).map(w => diag.get("/historical_deviations", async () => {
    const found = await s.github.get("actions/workflows/" + w.split("/").at(-1));
    if (found.path !== w) throw new Error("workflow");
    return integer.parse(found.id);
  })));
  await Promise.all(landings.flatMap(l => l.commits.flatMap(commit => workflows.slice(0, 2).map(async (workflow, i) => {
    const base = workflow.split("/").at(-1);
    const scope = (id: number | null) => `history:${l.ticket}/${commit}/${base}/${id ?? "none"}`;
    const wid = wids[i];
    if (!wid) { failedTickets.add(l.ticket); return; }
    const route = `actions/workflows/${wid}/runs?head_sha=${commit}&branch=main&event=push&per_page=100`;
    if (!runs.has(route)) runs.set(route, s.github.list(route, "workflow_runs"));
    const observed = await diag.get(scope(null), async () => {
      const data = z.array(historyRun).parse(await runs.get(route));
      if (!unique(data.map(r => r.id)) || data.some(r => r.head_sha !== commit || r.workflow_id !== wid)) throw new Error("run identity");
      return data;
    });
    if (!observed) { failedTickets.add(l.ticket); return; }
    if (!observed.length) rows.push({ ticket: l.ticket, commit, workflow, run_id: null, observed: "NO_RUN" });
    for (const run of observed) {
      const val = run.status === "completed" ? ciConclusion(run.conclusion) ?? "UNKNOWN" : "INCOMPLETE";
      if (val === "SUCCESS") continue;
      rows.push({ ticket: l.ticket, commit, workflow, run_id: run.id, observed: val });
      if (val === "UNKNOWN") diag.add("SOURCE_UNAVAILABLE", scope(run.id));
      if (i !== 0 || val !== "FAILURE") continue;
      const candidates = lookup(l.ticket, commit).filter(c => c.run_id === run.id);
      const ids = new Set(candidates.map(cureId));
      const required = historicalDenominator.get(`${l.ticket}/${run.id}`) ?? [];
      if (!candidates.length || ids.size !== candidates.length || required.some(id => !ids.has(id)) ||
          candidates.some(c => !cured(c))) {
        fail(l.ticket, scope(run.id)); continue;
      }
      const steps = candidates.filter(c => c.kind === "step");
      if (steps.length) {
        const jobs = await diag.get(scope(run.id), () => s.github.list(`actions/runs/${run.id}/jobs?per_page=100`, "jobs"));
        if (!jobs || steps.some(c => !jobs.some(j => Array.isArray(j.steps) && j.steps.some(step => {
          const value = object(step);
          return value.name === c.target && value.conclusion === "failure";
        })))) fail(l.ticket, scope(run.id));
      }
    }
  }))));
  return { rows: rows.sort((a, b) => a.ticket - b.ticket || compare(a.commit, b.commit) ||
    compare(a.workflow, b.workflow) || (a.run_id ?? 0) - (b.run_id ?? 0)), failedTickets };
}
