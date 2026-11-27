import { z } from "zod";
import { byteSha256, canonicalizeJcs, digest, sha, text, utc } from "./at18-format.ts";

const minute = utc.refine(stamp => /T\d\d:\d\d:00(?:\.0+)?Z$/.test(stamp));
const minuteMs = 60_000;
const minuteOf = (stamp: string) => Date.parse(stamp) / minuteMs;
const stampOf = (at: number) => new Date(at * minuteMs).toISOString().replace(".000Z", "Z");
type Span = { first: number; end: number }; // UTC 分钟；右开
export const heavyWindow = z.strictObject({ first_bar_at: minute, last_bar_at: minute, bars: z.int().min(2) });
const identity = { head: sha, symbol: text, interval: z.literal("1min") };

export const heavySeries = heavyWindow.extend({
  ...identity, schema_version: z.literal("at18-heavy-input-series/1"), chunks: z.array(digest).min(1),
});

const prices = { open: z.number(), high: z.number(), low: z.number(), close: z.number(), volume: z.number().nonnegative() };
const bar = z.strictObject({ at: minute, ...prices });
const run = bar.extend({ minutes: z.int().min(1).max(100_000) });
const chunkIdentity = { ...identity, schema_version: z.literal("at18-heavy-input-chunk/1") };
const chunkDocument = z.union([
  z.strictObject({ ...chunkIdentity, bars: z.array(bar).min(1).max(100_000) }),
  z.strictObject({ ...chunkIdentity, runs: z.array(run).min(1).max(100_000) }),
]);
export const snapshotSymbol = heavyWindow.extend({
  symbol: text,
  chunks: z.array(heavyWindow.extend({ bars: z.int().positive(), data_sha256: digest })).min(1),
  calendar: z.strictObject({ source: text, sessions: z.array(z.strictObject({
    // 每周 UTC 交易周期，周一=1；季节或节日的例外通过分段日历及获批缺口表达。
    effective_from: minute, effective_to: minute,
    week: z.array(z.strictObject({ weekday: z.int().min(1).max(7),
      start_minute: z.int().min(0).max(1439), end_minute: z.int().min(1).max(1440) })).min(1),
  })).min(1) }),
  approved_gaps: z.array(z.strictObject({ from: minute, until: minute, reason: text })),
});

function append(spans: Span[], first: number, end: number) {
  const last = spans.at(-1);
  if (!Number.isSafeInteger(first) || !Number.isSafeInteger(end) || end <= first || (last && last.end > first)) {
    throw new Error("SCHEMA");
  }
  if (last?.end === first) last.end = end;
  else spans.push({ first, end });
}

// 串联块的实际分钟区间与冻结计划匹配；OHLCV 数据哈希不包含 F，故可在测量前登记。
export function heavyInputChunk(json: unknown) {
  const chunk = chunkDocument.parse(json);
  const rows = "runs" in chunk ? chunk.runs : chunk.bars.map(b => ({ ...b, minutes: 1 }));
  const spans: Span[] = [];
  let bars = 0;
  for (const { at, open, low, high, close, minutes } of rows) {
    const first = minuteOf(at);
    if (low > Math.min(open, close) || high < Math.max(open, close)) throw new Error("SCHEMA");
    append(spans, first, first + minutes);
    bars += minutes;
    if (bars > 100_000) throw new Error("SCHEMA");
  }
  const { head, symbol, interval, schema_version } = chunk;
  const dataSha = byteSha256(Buffer.from(canonicalizeJcs({ symbol, interval, rows })));
  return { head, symbol, interval, schema_version, spans, data_sha256: dataSha,
    first_bar_at: stampOf(spans[0].first), last_bar_at: stampOf(spans.at(-1)!.end - 1), bars };
}
export type HeavyInputChunk = ReturnType<typeof heavyInputChunk>;

export function matchesHeavySnapshot(snapshot: z.infer<typeof snapshotSymbol>, chunks: HeavyInputChunk[]) {
  const first = minuteOf(snapshot.first_bar_at), end = minuteOf(snapshot.last_bar_at) + 1;
  const minutePerDay = 1440;
  const planned: Span[] = [];
  let boundary = first;
  for (const { effective_from, effective_to, week } of snapshot.calendar.sessions) {
    const from = minuteOf(effective_from), until = minuteOf(effective_to);
    if (from !== boundary || until <= from || until > end) return false;
    boundary = until;
    const weekSpans: Span[] = [];
    for (const { weekday, start_minute, end_minute } of [...week].sort((a, b) =>
      a.weekday - b.weekday || a.start_minute - b.start_minute)) {
      append(weekSpans, (weekday - 1) * minutePerDay + start_minute, (weekday - 1) * minutePerDay + end_minute);
    }
    // 交易周不能把数日/数年的洞伪装成例行休市；长假另登记为获批缺口。
    if (weekSpans[0].first + 7 * minutePerDay - weekSpans.at(-1)!.end > 3 * minutePerDay ||
        weekSpans.some((span, i) => i > 0 && span.first - weekSpans[i - 1].end > 3 * minutePerDay)) return false;
    const utcDay = Math.floor(from / minutePerDay);
    const monday = (utcDay - ((utcDay + 3) % 7 + 7) % 7) * minutePerDay;
    for (let offset = monday; offset < until; offset += 7 * minutePerDay) {
      for (const span of weekSpans) {
        const start = Math.max(from, span.first + offset), stop = Math.min(until, span.end + offset);
        if (start < stop) append(planned, start, stop);
      }
    }
  }
  if (boundary !== end || planned.some((span, i) => i > 0 && span.first - planned[i - 1].end > 3 * minutePerDay)) return false;
  const gaps: Span[] = [];
  for (const gap of snapshot.approved_gaps) {
    const from = minuteOf(gap.from), until = minuteOf(gap.until);
    if (from <= first || until >= end) return false;
    append(gaps, from, until);
  }
  const expected: Span[] = [];
  const used = new Set<Span>();
  let index = 0;
  for (const span of planned) {
    let cursor = span.first;
    while (gaps[index]?.end <= cursor) index++;
    for (let i = index; i < gaps.length && gaps[i].first < span.end; i++) {
      const gap = gaps[i];
      if (cursor < gap.first) append(expected, cursor, gap.first);
      cursor = Math.max(cursor, Math.min(gap.end, span.end));
      used.add(gap);
    }
    if (cursor < span.end) append(expected, cursor, span.end);
  }
  if (used.size !== gaps.length || expected[0]?.first !== first || expected.at(-1)?.end !== end ||
      expected.reduce((total, span) => total + span.end - span.first, 0) !== snapshot.bars ||
      chunks.length !== snapshot.chunks.length) return false;
  const actual: Span[] = [];
  let total = 0;
  for (const [i, chunk] of chunks.entries()) {
    const pinned = snapshot.chunks[i];
    if (chunk.data_sha256 !== pinned.data_sha256 || chunk.bars !== pinned.bars ||
        minuteOf(chunk.first_bar_at) !== minuteOf(pinned.first_bar_at) ||
        minuteOf(chunk.last_bar_at) !== minuteOf(pinned.last_bar_at)) return false;
    total += chunk.bars;
    for (const span of chunk.spans) append(actual, span.first, span.end);
  }
  return total === snapshot.bars && actual.length === expected.length &&
    expected.every((span, i) => span.first === actual[i].first && span.end === actual[i].end);
}
