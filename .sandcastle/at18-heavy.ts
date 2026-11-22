import { z } from "zod";
import { type External } from "./at18-evidence.ts";
import { byteSha256, canonicalizeJcs, digest, heavy, integer, parseJsonObject, repoPath, sha, text, utc } from "./at18-format.ts";
import { object, type Row } from "./at18-github.ts";
import { type Tracker, utcBefore } from "./at18-integrations.ts";
import { type At18Repository, type Diagnostics, repoRef } from "./at18-source.ts";
import { unique } from "./at18-coverage.ts";

export const heavySymbols = ["ES", "GC", "CL", "ZN", "6E", "BRN", "DX"];
// backtest-protocol-v0 §4：两项随机对照各 1,000 次，冻结种子 20260625；B&H 是另外的收益基线。
const protocolCommit = "7fa4a278eec54704637dd68dcb6101d6dbccdd6a";
const protocolPath = "docs/backtest-protocol-v0.md";
const controlIds = ["random-entry", "direction-shuffle"];
const armId = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$/);
const pinnedFile = z.strictObject({ commit: sha, path: repoPath, sha256: digest });
const window = z.strictObject({ first_bar_at: utc, last_bar_at: utc, bars: integer });
const arm = z.strictObject({ id: armId, definition_sha256: digest });
const control = arm.extend({ seed: z.literal(20260625), replications: z.literal(1000) });
const plan = z.strictObject({
  schema_version: z.literal("at18-heavy-preregistration/1"), ticket: z.literal(1320),
  protocol_sha256: digest, windows_sha256: digest, design: z.literal("FROZEN_PREREGISTERED_DUAL_CONTROLS"),
  symbols: z.array(z.string()), interval: z.literal("1min"), trials: z.array(arm).min(1), controls: z.array(control).length(2),
});
const rollup = z.strictObject({ schema_version: z.literal("at18-heavy-measurement/1"), head: sha,
  design: z.literal("FROZEN_PREREGISTERED_DUAL_CONTROLS"), preregistration: pinnedFile,
  started_at: utc, finished_at: utc,
  symbols: z.array(window.extend({ symbol: text, interval: z.literal("1min"), years: integer.optional(), result_sha256: digest })).length(7),
});
const index = z.strictObject({ id: armId, result_sha256: digest });
const replay = window.extend({
  schema_version: z.literal("at18-heavy-replay/1"), head: sha, preregistration_sha256: digest, input_sha256: digest,
  symbol: text, interval: z.literal("1min"),
  first_run: armId, second_run: armId, second_output_sha256: digest,
  outputs: z.strictObject({
    trades: z.array(z.strictObject({ id: armId, opened_at: utc, closed_at: utc, pnl: z.number(), drawdown: z.number() })),
    voice_lifecycle: z.array(z.strictObject({ at: utc, voice_id: armId, transition: text })).min(1),
    center_transitions: z.array(z.strictObject({ at: utc, center_id: armId, transition: text })).min(1),
  }),
});
const symbolResult = window.extend({
  schema_version: z.literal("at18-heavy-symbol-result/1"), head: sha, preregistration_sha256: digest, symbol: text,
  interval: z.literal("1min"), input_sha256: digest, replay_sha256: digest, trials: z.array(index).min(1), controls: z.array(index).length(2),
});
const armResult = window.extend({
  schema_version: z.literal("at18-heavy-arm-result/1"), head: sha, preregistration_sha256: digest, input_sha256: digest,
  symbol: text, interval: z.literal("1min"), id: armId, definition_sha256: digest,
  kind: z.enum(["trial", "control"]), seed: z.literal(20260625).nullable(),
  // 每次运行的原始统计值；允许负结果，不允许用布尔“完成”或空对象冒充。
  results: z.array(z.strictObject({ replication: z.int().nonnegative(), sharpe: z.number(), cagr: z.number(),
    trades: z.int().nonnegative() })).min(1),
});
const retirement = z.strictObject({
  schema_version: z.literal("at18-heavy-retirement/1"), ticket: z.literal(1320), obligation: z.literal(heavy),
  decision_ticket: integer, authorization_comment_id: integer, disposition: z.literal("RETIRE"),
  scope: z.literal("SEVEN_SYMBOL_FROZEN_10Y_1MIN_MEASUREMENT_ONLY"), rationale: text,
});

function tenYears(from: string, to: string) {
  // 以 UTC 日历周年而非 3650 天或年份差判定；闰日周年取 2 月末。
  const start = /^([0-9]{4})-([0-9]{2})-([0-9]{2})(T.*)$/.exec(from);
  if (!start || !utcBefore(from, to)) return false;
  const [, year, month, day, time] = start;
  const anniversaryYear = Number(year) + 10;
  const lastDay = new Date(Date.UTC(anniversaryYear, Number(month), 0)).getUTCDate();
  const anniversary = String(anniversaryYear).padStart(4, "0") + "-" + month + "-" +
    String(Math.min(Number(day), lastDay)).padStart(2, "0") + time;
  return anniversary === to || utcBefore(anniversary, to);
}
const sameWindow = (a: z.infer<typeof window>, b: z.infer<typeof window>) =>
  a.first_bar_at === b.first_bar_at && a.last_bar_at === b.last_bar_at && a.bars === b.bars;

export function measuredHeavy(s: At18Repository, F: string, sources: External[], reviewed: ReadonlyMap<string, Row>, windows: Buffer | undefined) {
  if (!windows) return undefined;
  const candidates = sources.filter(e => e.ref.ticket === 1320 && e.json.schema_version === "at18-heavy-measurement/1");
  if (candidates.length !== 1) return undefined;
  try {
    const summary = rollup.parse(candidates[0].json);
    const p = summary.preregistration;
    if (summary.head !== F || !utcBefore(summary.started_at, summary.finished_at) ||
        !reviewed.has(p.commit) || !s.ancestor(p.commit, F) ||
        !utcBefore(s.string("show", "-s", "--format=%cI", p.commit).replace(/\+00:00$/, "Z"), summary.started_at)) return undefined;
    const bytes = s.blob(p.commit, p.path);
    if (byteSha256(bytes) !== p.sha256 || !s.changed(s.string("rev-parse", p.commit + "^1"), p.commit).includes(p.path)) return undefined;
    const frozen = plan.parse(parseJsonObject(bytes));
    if (!s.blob(protocolCommit, protocolPath).equals(s.blob(p.commit, protocolPath)) ||
        frozen.protocol_sha256 !== byteSha256(s.blob(protocolCommit, protocolPath)) ||
        !frozen.trials.some(t => t.id === "reference-theta-v0") ||
        frozen.windows_sha256 !== byteSha256(windows) ||
        !unique(frozen.trials.map(a => a.id)) || !unique([...frozen.trials, ...frozen.controls].map(a => a.id)) ||
        !heavySymbols.every(x => frozen.symbols.includes(x)) || frozen.symbols.length !== heavySymbols.length ||
        !controlIds.every(x => frozen.controls.some(c => c.id === x)) ||
        !heavySymbols.every(x => summary.symbols.some(e => e.symbol === x))) return undefined;

    const records = new Map(sources.filter(e => e.ref.ticket === 1320 && e.ref.head && e.json.head === F)
      .map(e => [e.ref.sha256, e]));
    const consumed = new Set(candidates);
    for (const row of summary.symbols) {
      if (!tenYears(row.first_bar_at, row.last_bar_at) || !utcBefore(row.last_bar_at, summary.started_at)) return undefined;
      const item = records.get(row.result_sha256);
      if (!item) return undefined;
      const data = symbolResult.parse(item.json);
      if (data.symbol !== row.symbol || !sameWindow(row, data) || data.preregistration_sha256 !== p.sha256) return undefined;
      consumed.add(item);
      const replayItem = records.get(data.replay_sha256);
      if (!replayItem || consumed.has(replayItem)) return undefined;
      const replayed = replay.parse(replayItem.json);
      const { outputs } = replayed;
      const inside = (stamp: string) => !utcBefore(stamp, row.first_bar_at) && !utcBefore(row.last_bar_at, stamp);
      if (replayed.symbol !== row.symbol || !sameWindow(row, replayed) || replayed.preregistration_sha256 !== p.sha256 ||
          replayed.input_sha256 !== data.input_sha256 || replayed.first_run === replayed.second_run ||
          byteSha256(Buffer.from(canonicalizeJcs(outputs))) !== replayed.second_output_sha256 ||
          !unique(outputs.trades.map(t => t.id)) || outputs.trades.some(t => !inside(t.opened_at) ||
            !inside(t.closed_at) || utcBefore(t.closed_at, t.opened_at)) ||
          [...outputs.voice_lifecycle, ...outputs.center_transitions].some(e => !inside(e.at))) return undefined;
      consumed.add(replayItem);
      for (const kind of ["trial", "control"] as const) {
        const expected = kind === "trial" ? frozen.trials : frozen.controls;
        const observed = kind === "trial" ? data.trials : data.controls;
        if (expected.length !== observed.length || !unique(observed.map(e => e.id))) return undefined;
        for (const arm of expected) {
          const ref = observed.find(e => e.id === arm.id);
          const original = ref && records.get(ref.result_sha256);
          if (!original || consumed.has(original)) return undefined;
          const doc = armResult.parse(original.json);
          if (doc.kind !== kind || doc.id !== arm.id || doc.definition_sha256 !== arm.definition_sha256 ||
              doc.symbol !== row.symbol || doc.input_sha256 !== data.input_sha256 || !sameWindow(doc, data) ||
              doc.preregistration_sha256 !== p.sha256 || doc.seed !== (kind === "control" ? 20260625 : null) ||
              doc.results.length !== (kind === "control" ? 1000 : 1) ||
              !doc.results.every((r, i) => r.replication === i) ||
              (kind === "trial" && arm.id === "reference-theta-v0" && doc.results[0].trades !== outputs.trades.length)) return undefined;
          consumed.add(original);
        }
      }
    }
    return { used: consumed, preregistration: repoRef(p.commit, p.path, bytes, "LEGACY_SOURCE") };
  } catch { return undefined; }
}

export async function authorizedHeavyRetirement(s: At18Repository, F: string, sources: External[],
  reviewed: ReadonlyMap<string, Row>, tracker: Tracker, diag: Diagnostics) {
  const candidates = sources.filter(e => e.ref.ticket === 1320 && e.json.schema_version === "at18-heavy-retirement-reference/1");
  if (candidates.length !== 1) return undefined;
  try {
    const locator = z.strictObject({ schema_version: z.literal("at18-heavy-retirement-reference/1"),
      head: sha, decision: pinnedFile }).parse(candidates[0].json);
    const p = locator.decision;
    if (locator.head !== F || !reviewed.has(p.commit) || !s.ancestor(p.commit, F) ||
        !s.changed(s.string("rev-parse", p.commit + "^1"), p.commit).includes(p.path)) return undefined;
    const bytes = s.blob(p.commit, p.path);
    if (byteSha256(bytes) !== p.sha256 || !bytes.equals(s.blob(F, p.path))) return undefined;
    const d = retirement.parse(parseJsonObject(bytes));
    if ([1320, 1369, 1391, 1403].includes(d.decision_ticket)) return undefined;
    const ticket = await tracker.issue(d.decision_ticket);
    if (ticket.state !== "CLOSED" || ticket.reason !== "COMPLETED" || !ticket.labels.includes("wayfinder:decision")) return undefined;
    const scope = "ticket:" + d.decision_ticket;
    const reviews = await diag.get(scope, () => s.github.list(`issues/${d.decision_ticket}/comments?per_page=100`));
    const expected = "```at18-heavy-retirement-approval/1\n" + canonicalizeJcs({
      decision_ticket: d.decision_ticket, ticket: 1320, obligation: heavy, disposition: "RETIRE", decision_sha256: p.sha256,
    }) + "\n```";
    const approval = reviews?.find(c => c.id === d.authorization_comment_id);
    const approvedBeforeMerge = approval && utcBefore(approval.updated_at, reviewed.get(p.commit)?.merged_at);
    if (!approval || approval.issue_url !== `https://api.github.com/repos/${s.github.repo}/issues/${d.decision_ticket}` ||
        approval.author_association !== "OWNER" || object(approval.user).type !== "User" ||
        !approvedBeforeMerge || approval.body !== expected ||
        reviews?.some(c => typeof c.id !== "number" || c.id > d.authorization_comment_id)) return undefined;
    return { used: candidates[0], ruling: repoRef(p.commit, p.path, bytes, "LEGACY_SOURCE") };
  } catch { return undefined; }
}
