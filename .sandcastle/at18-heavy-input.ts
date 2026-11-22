import { z } from "zod";
import { digest, sha, text, utc } from "./at18-format.ts";
import { utcBefore } from "./at18-integrations.ts";

export const heavyWindow = z.strictObject({ first_bar_at: utc, last_bar_at: utc, bars: z.int().min(2) });
const identity = { head: sha, symbol: text, interval: z.literal("1min") };

export const heavySeries = heavyWindow.extend({
  ...identity, schema_version: z.literal("at18-heavy-input-series/1"), chunks: z.array(digest).min(1),
});

const chunkDocument = z.strictObject({
  ...identity, schema_version: z.literal("at18-heavy-input-chunk/1"),
  bars: z.array(z.strictObject({ at: utc, open: z.number(), high: z.number(), low: z.number(),
    close: z.number(), volume: z.number().nonnegative() })).min(1).max(100_000),
});

// 逐块核原件，不把七个标的的十年分钟行一起留在内存里。
export function heavyInputChunk(json: unknown) {
  const chunk = chunkDocument.parse(json);
  if (chunk.bars.some((bar, i) => !/T\d\d:\d\d:00(?:\.0+)?Z$/.test(bar.at) ||
      (i > 0 && !utcBefore(chunk.bars[i - 1].at, bar.at)) ||
      bar.low > Math.min(bar.open, bar.close) || bar.high < Math.max(bar.open, bar.close))) throw new Error("SCHEMA");
  return { head: chunk.head, symbol: chunk.symbol, interval: chunk.interval, schema_version: chunk.schema_version,
    first_bar_at: chunk.bars[0].at, last_bar_at: chunk.bars[chunk.bars.length - 1].at, bars: chunk.bars.length };
}
export type HeavyInputChunk = ReturnType<typeof heavyInputChunk>;
