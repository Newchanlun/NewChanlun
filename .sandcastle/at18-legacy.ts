import { substantiveReplacement } from "./at18-code.ts";
import { z } from "zod";
import { findAt14 } from "./at18-at14.ts";
import { authorizedHeavyRetirement, measuredHeavy } from "./at18-heavy.ts";
import { type Adapter, typed } from "./at18-contract.ts";
import { type Bindings, type Slice, unique } from "./at18-coverage.ts";
import { byteSha256, dispositions, heavy, legacyTickets, parseJsonObject,
  repoPath, sha, text, type ArtifactRef, type At18Report } from "./at18-format.ts";
import { type External } from "./at18-evidence.ts";
import { type Row } from "./at18-github.ts";
import { type AcceptedReview, type ReviewRef, type Tracker } from "./at18-integrations.ts";
import { type At18Repository, type Diagnostics, repoRef, refs, sorted, utf8, valueAt } from "./at18-source.ts";

// #1319 的 884568065c 收口记录（SPEC 旧票处置档）给出两项候选；
// #1351 受影响代码清单及 F 的 Git 树给出同一能力的留存 feed / HL wire。
export const feedWirePaths = {
  feed: ["rust/src/theta_v0/live/feed.rs", "trading_system/data/feed_abstraction.py"],
  wire: ["rust/src/theta_v0/live/exec.rs", "trading_system/live/hl_verify_sdk.py", "trading_system/live/hl_verify_nautilus.py"],
};
const feedWireRow = z.discriminatedUnion("disposition", [
  z.strictObject({ path: repoPath, disposition: z.literal("INCORPORATED"), replacement: repoPath, basis: repoPath, anchor: sha }),
  z.strictObject({ path: repoPath, disposition: z.literal("RETIRED"), basis: repoPath, anchor: sha }),
]);
const feedWireInventory = z.strictObject({ schema_version: z.literal("feed-wire-inventory/1"), head: sha, entries: z.array(feedWireRow) });
const feedWireDecision = z.strictObject({ schema_version: z.literal("feed-wire-disposition/1"),
  ticket: z.literal(1319), dispositions: z.array(z.strictObject({ path: repoPath, replacement: repoPath.nullable(), rationale: text })).min(1) });

const closeoutEntity = z.object({ schema_version: text, head: sha });
const inventoryRow = z.strictObject({ path: repoPath, disposition: z.enum(["FROZEN", "INCORPORATED", "RETIRED"]),
  replacement: repoPath.nullable() });
const inventory = z.strictObject({ schema_version: text, head: sha, entries: z.array(inventoryRow).min(1) });
const legacyAtoms = new Map<number, string[]>([
  [942, ["ISSUE_942_DISPOSITION"]],
  [1096, ["ISSUE_1096_ENTRY_END_STATE", "ISSUE_1096_RETIREMENT_CONDITIONS"]],
  [1282, ["ISSUE_1282_ARCHIVE"]],
  [1304, ["ISSUE_1304_REPLAY", "ISSUE_1304_RECOVERY", "ISSUE_1304_AS_KNOWN", "ISSUE_1304_STATE_PARITY", "ISSUE_1304_AT14"]],
  [1319, ["ISSUE_1319_FEED_WIRE", "ISSUE_1319_INTENT_RECEIPT", "ISSUE_1319_SEND_ISOLATION"]],
  [1320, ["ISSUE_1320_FULL_REPLAY", heavy]], [1279, []],
]);

export async function legacyDispositions(s: At18Repository, F: string, adapter: Adapter | undefined, tracker: Tracker,
  pureGraph: boolean, tb: Map<Slice, boolean>, b: Bindings, groupPass: Set<string>, permission: boolean, external: External[], used: Set<External>,
  reviewed: ReadonlyMap<string, AcceptedReview>, reviews: ReviewRef[], diag: Diagnostics) {
  const atoms = new Map<number, Set<string>>();
  const inGraph = new Map<number, boolean>();
  const knownSources = new Map<string, Promise<{ value: unknown; ref: ArtifactRef | null } | undefined>>();
  async function rawSource(name: string) {
    const rule = adapter?.legacy_sources[name];
    if (!rule) return undefined;
    try {
      if (rule.kind === "git-blob") {
        if (!s.ancestor(rule.commit, F)) return undefined;
        const bytes = s.blob(rule.commit, rule.path);
        if (byteSha256(bytes) !== rule.sha256) return undefined;
        const value = rule.pointer === null ? bytes : valueAt(parseJsonObject(bytes), rule.pointer);
        return typed(value, rule.type) ? { value, ref: repoRef(rule.commit, rule.path, bytes, "LEGACY_SOURCE") } : undefined;
      }
      const item = rule.comment_id ? await diag.get("ticket:" + rule.ticket, () => s.github.get("issues/comments/" + rule.comment_id)) :
        (await tracker.issue(rule.ticket)).data;
      if (rule.comment_id && (item?.id !== rule.comment_id ||
          String(item.issue_url).toLowerCase() !== `https://api.github.com/repos/${s.github.repo.toLowerCase()}/issues/${rule.ticket}`)) return undefined;
      const value = valueAt(item, rule.pointer);
      return typeof value === "string" && typed(value, rule.type) && byteSha256(Buffer.from(value)) === rule.sha256 ?
        { value, ref: null } : undefined;
    } catch { return undefined; }
  }
  function source(name: string) {
    if (!knownSources.has(name)) knownSources.set(name, rawSource(name));
    return knownSources.get(name)!;
  }
  const at14 = findAt14(s, F, b, groupPass, reviews, diag);
  const list = await Promise.all(legacyTickets.map(async (ticket, index): Promise<At18Report["legacy_dispositions"][number]> => {
    const original = await tracker.issue(ticket);
    const scope = "ticket:" + ticket;
    const contract = adapter?.legacy_dispositions[String(ticket)];
    const refsFound: ArtifactRef[] = [];
    const remaining = new Set<string>();
    atoms.set(ticket, remaining);
    let valid = !!contract && contract.disposition === dispositions[index] && original.state !== null;
    const fail = (obligation?: string) => {
      diag.add("LEGACY_DISPOSITION", obligation ? scope + "@" + obligation : scope);
      if (obligation && ticket !== 1279) remaining.add(obligation);
      valid = false;
    };
    const scan = async (name: string) => {
      const document = await source(name);
      if (document?.ref) refsFound.push(document.ref);
      return !!document;
    };
    const root = await Promise.all((contract?.sources ?? []).map(scan));
    if (!valid || root.some(pass => !pass)) fail();
    function pinExt(entity: string, tickets: number[]) {
      const matches = external.filter(x => tickets.includes(x.ref.ticket ?? -1) &&
        x.json.schema_version === entity && closeoutEntity.safeParse(x.json).success && x.json.head === F);
      if (!matches.length || new Set(matches.map(m => m.ref.sha256)).size !== 1) return undefined;
      const first = matches[0];
      refsFound.push({ ...first.ref, bounded_scope: "AT18:LEGACY_SOURCE" });
      used.add(first);
      return first.json;
    }
    function inventoryProof(entity: string, tickets: number[], requiredPaths: string[]) {
      const record = pinExt(entity, tickets);
      const result = inventory.safeParse(record);
      if (!result.success || !unique(result.data.entries.map(r => r.path))) return { ok: false, deleted: false };
      const paths = s.tree(F);
      const entries = result.data.entries;
      const deleted = entries.some(r => r.disposition === "RETIRED");
      const ok = requiredPaths.every(path => entries.some(r => r.path === path)) && entries.every(r => {
        if (r.disposition === "RETIRED") return !paths.has(r.path) && r.replacement !== null && paths.has(r.replacement);
        if (r.disposition === "INCORPORATED") return r.replacement !== null && paths.has(r.replacement);
        return paths.has(r.path) && r.replacement === null;
      });
      return { ok, deleted };
    }
    function feedWireProof(record: Row | undefined) {
      const data = feedWireInventory.parse(record);
      const paths = [...feedWirePaths.feed, ...feedWirePaths.wire];
      if (!unique(data.entries.map(e => e.path)) || data.entries.length !== paths.length ||
          paths.some(path => !data.entries.some(row => row.path === path))) return false;
      const current = s.tree(F);
      for (const row of data.entries) {
        const pr = reviewed.get(row.anchor);
        if (!pr || !s.ancestor(row.anchor, F)) return false;
        const parent = s.string("rev-parse", row.anchor + "^1");
        const changed = s.changed(parent, row.anchor);
        if (!changed.includes(row.basis)) return false;
        const decision = s.blob(row.anchor, row.basis);
        const ruling = feedWireDecision.parse(parseJsonObject(decision));
        if (!decision.equals(s.blob(F, row.basis)) || !unique(ruling.dispositions.map(r => r.path)) ||
            !ruling.dispositions.some(r => r.path === row.path &&
              r.replacement === (row.disposition === "RETIRED" ? null : row.replacement))) return false;
        refsFound.push(repoRef(row.anchor, row.basis, decision, "LEGACY_SOURCE"));
        if (row.disposition === "RETIRED") {
          if (current.has(row.path)) return false;
        } else {
          if (!changed.includes(row.replacement) || !/^(?:rust|trading_system)\/.+\.(?:rs|py)$/.test(row.replacement)) return false;
          const source = s.blob(F, row.replacement);
          if (!substantiveReplacement(row.replacement, utf8(source)) || !source.equals(s.blob(row.anchor, row.replacement))) return false;
          refsFound.push(repoRef(row.anchor, row.replacement, source, "LEGACY_SOURCE"));
        }
      }
      return true;
    }
    async function liveAt14() {
      const proof = await at14;
      refsFound.push(...proof);
      return !!proof.length;
    }
    let entry: { ok: boolean; deleted: boolean } | undefined;
    if (ticket === 1096) {
      try { entry = inventoryProof("tb-entry-inventory/1", [1368, 1096], ["rust/src/recursive_t/mod.rs"]); } catch { /* 取证失败 */ }
    }
    const stateOk = original.state === "CLOSED" && original.reason === "COMPLETED";
    for (const atom of legacyAtoms.get(ticket) ?? []) {
      if (atom === heavy || (atom === "ISSUE_1096_RETIREMENT_CONDITIONS" && !entry?.deleted)) continue;
      const data = contract?.obligations[atom];
      const supportingSources = await Promise.all((data?.sources ?? []).map(scan));
      let good = !!data && supportingSources.every(Boolean) && data.tb_ids.every(id => tb.get(id) === true);
      try {
        if (atom === "ISSUE_942_DISPOSITION" || atom === "ISSUE_1282_ARCHIVE") good &&= stateOk;
        if (atom === "ISSUE_1096_ENTRY_END_STATE") good &&= !!entry?.ok;
        if (atom === "ISSUE_1096_RETIREMENT_CONDITIONS") {
          const accepted = await tracker.issue(1096), execution = await tracker.issue(1385);
          good &&= accepted.state === "CLOSED" && accepted.reason === "COMPLETED" &&
            typeof execution.data?.body === "string" && /^- \[x\] OE11 /m.test(execution.data.body) &&
            /^- \[x\] #1096 rec_t_strategy/m.test(execution.data.body);
        }
        if (atom === "ISSUE_1304_REPLAY" || atom === "ISSUE_1320_FULL_REPLAY") {
          good &&= await liveAt14();
        }
        if (["ISSUE_1304_RECOVERY", "ISSUE_1304_AS_KNOWN", "ISSUE_1304_STATE_PARITY", "ISSUE_1304_AT14"].includes(atom)) good &&= await liveAt14();
        if (atom === "ISSUE_1319_FEED_WIRE") good &&= feedWireProof(pinExt("feed-wire-inventory/1", [1367, 1319]));
        if (atom === "ISSUE_1319_SEND_ISOLATION") good &&= permission;
      } catch { good = false; }
      if (!good) fail(atom);
    }
    // 图内只读重测分支之前的完整程序回放等前因子。
    if (ticket === 1304 || ticket === 1320) inGraph.set(ticket, valid);
    if (ticket === 1320) {
      const windows = (await source("prereg_windows"))?.value;
      const measured = measuredHeavy(s, F, external, reviewed, Buffer.isBuffer(windows) ? windows : undefined);
      const retired = measured ? undefined : await authorizedHeavyRetirement(s, F, external, reviewed, tracker, diag);
      if (measured) {
        refsFound.push(measured.preregistration);
        for (const item of measured.used) {
          used.add(item);
          refsFound.push({ ...item.ref, bounded_scope: "AT18:LEGACY_SOURCE" });
        }
      } else if (retired) {
        used.add(retired.used);
        refsFound.push(retired.ruling, { ...retired.used.ref, bounded_scope: "AT18:LEGACY_SOURCE" });
      } else {
        remaining.add(heavy);
        if (original.state !== "OPEN") fail(heavy);
      }
    }
    if (ticket === 1304 && original.state === "CLOSED" && (!stateOk || remaining.size)) {
      fail();
      inGraph.set(ticket, false);
    }
    if (ticket === 1279) {
      const known = adapter?.issue_1279.release_disposition.known_historical_comments ?? [];
      const sourceIds = new Set(known.map(n => {
        const rule = adapter?.legacy_sources[n];
        return rule && rule.kind !== "git-blob" ? rule.comment_id : null;
      }));
      const comments = await diag.get(scope, () => s.github.list("issues/1279/comments?per_page=100"));
      if (original.state !== "OPEN" || !comments || comments.length !== sourceIds.size || !unique(comments.map(c => c.id)) ||
          comments.some(c => !sourceIds.has(Number(c.id))) || !(await Promise.all(known.map(scan))).every(Boolean)) fail();
      for (const row of adapter?.issue_1279.own_checklist ?? []) {
        const record = await source(row.source);
        const rule = adapter?.legacy_sources[row.source];
        if (typeof record?.value !== "string" || !record.value.split("\n")[row.line - 1]?.trim() ||
            !rule || rule.kind === "git-blob" || rule.comment_id === null) fail();
        else remaining.add(`ISSUE_1279:${rule.comment_id}/${row.entry}`);
      }
      if (!pureGraph) fail();
    }
    return { ticket, disposition: dispositions[index], evidence_refs: refs(refsFound), ticket_state: original.state,
      remaining_obligations: sorted(remaining), disposition_valid: valid };
  }));
  const keepOpen = list.find(row => row.ticket === 1279)!;
  if (![1304, 1320].every(ticket => inGraph.get(ticket) === true)) {
    keepOpen.disposition_valid = false;
    diag.add("LEGACY_DISPOSITION", "ticket:1279");
  }
  return { list, deferredHeavy: atoms.get(1320)?.has(heavy) ?? true };
}
