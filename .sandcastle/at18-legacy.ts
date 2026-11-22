import { z } from "zod";
import { type Adapter, typed } from "./at18-contract.ts";
import { type Bindings, type Slice, unique } from "./at18-coverage.ts";
import { byteSha256, canonicalizeJcs, computeContentHash, digest, dispositions, heavy, integer, legacyTickets, parseJsonObject,
  repoPath, sha, text, type ArtifactRef, type At18Report } from "./at18-format.ts";
import { type External } from "./at18-evidence.ts";
import { object, type Row } from "./at18-github.ts";
import { type Tracker, utcBefore } from "./at18-integrations.ts";
import { type At18Repository, type Diagnostics, repoRef, refs, sorted, valueAt } from "./at18-source.ts";

export const AT14_LOCKS = ["dual_run_determinism_h1", "recovery_after_kill_h2", "seek_no_future_leak_h3", "asknown_evidence_segregation_h4"];
const AT14_FACES = ["s_structure_snapshot", "b_chong_ledgers", "e_responsibility", "orders_and_fills", "physical_positions", "external_effect_journal"];
const W = ["ES", "GC", "CL", "ZN", "6E", "BRN", "DX"];
const AT14 = /^\.chanlun\/review-results\/issue1304-at14-[0-9]{8}-[0-9a-f]{7,40}\/at14-report\.json$/;
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
  pureGraph: boolean, tb: Map<Slice, boolean>, b: Bindings, groupPass: Set<string>, permission: boolean, external: External[], used: Set<External>, diag: Diagnostics) {
  const atoms = new Map<number, Set<string>>();
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
    function inventoryProof(entity: string, tickets: number[], requiredPaths: string[] = []) {
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
    function liveAt14() {
      if (ticket !== 1304 && ticket !== 1320) return false;
      const tb07 = [...b.activeByCheck].filter(([, uses]) => [...uses.values()].some(use => use.key.slice === "TB-07"));
      if (!AT14_LOCKS.every(name => tb07.some(([id]) => {
        const check = b.checks.get(id);
        if (!check || check.expected_count !== 1 || check.runner === "command" ||
           check.evidence_class !== "simulation" || !groupPass.has(check.group)) return false;
        const selector = check.selector.split("/").at(-1);
        return selector === name || selector?.endsWith("::" + name);
      }))) return false;
      try {
        const candidates: { ref: ArtifactRef; data: Row }[] = [];
        for (const path of s.tree(F).keys()) {
          if (!AT14.test(path)) continue;
          const bytes = s.blob(F, path);
          const record = parseJsonObject(bytes);
          if (record.schema_version !== "at14-report/1" || record.content_hash !== computeContentHash(record) ||
              !sha.safeParse(valueAt(record, "/build_fingerprint/commit")).success || valueAt(record, "/session/evidence_class") !== "simulation") continue;
          const builtAt = sha.parse(valueAt(record, "/build_fingerprint/commit"));
          if (!s.ancestor(builtAt, F) || s.changed(builtAt, F).some(p => !p.startsWith(path.slice(0, path.lastIndexOf("/") + 1)))) continue;
          candidates.push({ ref: repoRef(F, path, bytes, "AT14_REPORT"), data: record });
        }
        if (candidates.length !== 1) return false;
        const { ref, data } = candidates[0];
        refsFound.push(ref);
        const session = object(data.session);
        const profile = object(session.profile_echo);
        const manifest = object(session.manifest_echo);
        const actual = object(data.actual_load);
        const range = object(actual.input_range);
        const faces = object(data.six_faces);
        const clock = valueAt(profile, "/clock/kind");
        const hasSixDomains = ["structure", "funding", "model", "initial_positions", "scenario_contract", "clock"]
          .every(name => Object.hasOwn(profile, name));
        return valueAt(data, "/verdict/kind") === "PASS" && hasSixDomains &&
          session.manifest_revision === "production-session-manifest/1" && manifest.manifest_revision === session.manifest_revision &&
          manifest.profile === "simulation" && session.profile_revision === "history-input-profile/1" &&
          profile.schema_revision === session.profile_revision && profile.evidence_class === "simulation" &&
          clock === "logical-bar/1" && session.clock_kind === clock && text.safeParse(session.scheduler).success &&
          session.manifest_hash === byteSha256(Buffer.from(canonicalizeJcs(manifest))) &&
          session.profile_hash === byteSha256(Buffer.from(canonicalizeJcs(profile))) &&
          valueAt(data, "/dual_run_tuple/input_profile_hash") === session.profile_hash &&
          digest.safeParse(valueAt(data, "/build_fingerprint/lockfile_hash")).success &&
          digest.safeParse(data.capability_manifest_hash).success &&
          integer.safeParse(actual.bar_count).success && integer.safeParse(actual.checkpoint_count).success &&
          Array.isArray(range.symbols) && range.symbols.length > 0 && utcBefore(range.from, range.to) &&
          Array.isArray(data.fault_schedule) && data.fault_schedule.length > 0 &&
          Array.isArray(data.schedule_trace) && data.schedule_trace.length > 0 &&
          ["h1", "h2", "h3", "h4"].every((lock, index) => {
            const rec = object(data[lock]);
            return rec.test_name === AT14_LOCKS[index] && rec.result === "PASS" &&
              rec.diff_count === 0 && typeof rec.diff_summary === "string";
          }) && Object.keys(faces).length === AT14_FACES.length && AT14_FACES.every(face => {
            const row = object(faces[face]);
            return integer.safeParse(row.row_count).success && row.diff_count === 0;
          }) && Array.isArray(data.unexecuted) && data.unexecuted.length === 0 &&
          ["model_order_unspecified_count", "diagnostic_not_production_count", "input_source_unavailable_count"].every(k => data[k] === 0);
      } catch { return false; }
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
          good &&= liveAt14();
        }
        if (["ISSUE_1304_RECOVERY", "ISSUE_1304_AS_KNOWN", "ISSUE_1304_STATE_PARITY", "ISSUE_1304_AT14"].includes(atom)) good &&= liveAt14();
        if (atom === "ISSUE_1319_FEED_WIRE") good &&= inventoryProof("feed-wire-inventory/1", [1367, 1319]).ok;
        if (atom === "ISSUE_1319_SEND_ISOLATION") good &&= permission;
      } catch { good = false; }
      if (!good) fail(atom);
    }
    if (ticket === 1320) {
      const measured = pinExt("at18-heavy-measurement/1", [1320]);
      let completed = false;
      if (measured && Array.isArray(measured.symbols)) {
        try {
          const all = measured.symbols.map(object);
          completed = all.length === W.length && unique(all.map(r => r.symbol)) &&
            W.every(symbol => all.some(r => r.symbol === symbol && r.interval === "1min" && r.years === 10 &&
              digest.safeParse(r.result_sha256).success && integer.safeParse(r.bars).success &&
              external.some(item => {
                if (item.ref.ticket !== 1320 || item.ref.sha256 !== r.result_sha256 ||
                    item.json.schema_version !== "at18-heavy-symbol-result/1" || item.json.symbol !== symbol ||
                    item.json.interval !== "1min" || item.json.years !== 10 ||
                    item.json.head !== F || item.json.bars !== r.bars || !Array.isArray(item.json.trials) ||
                    !item.json.trials.length || !Array.isArray(item.json.controls) || item.json.controls.length !== 2) return false;
                used.add(item);
                refsFound.push({ ...item.ref, bounded_scope: "AT18:LEGACY_SOURCE" });
                return true;
              }))) && measured.design === "FROZEN_PREREGISTERED_DUAL_CONTROLS";
        } catch { /* 无合法完成实体则继续保留 OPEN。 */ }
      }
      if (!completed) {
        remaining.add(heavy);
        if (original.state !== "OPEN") fail(heavy);
      }
    }
    if (ticket === 1304 && original.state === "CLOSED" && (!stateOk || remaining.size)) fail();
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
  if (list.some(row => (row.ticket === 1304 || row.ticket === 1320) && !row.disposition_valid)) {
    keepOpen.disposition_valid = false;
    diag.add("LEGACY_DISPOSITION", "ticket:1279");
  }
  return { list, deferredHeavy: atoms.get(1320)?.has(heavy) ?? true };
}
