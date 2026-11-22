import { z } from "zod";
import { kind, type Basis, type Check, type Domain, type Kind, type Registry } from "./at18-contract.ts";
import {
  At18BootstrapError, byteSha256, evidenceClass, ledgerPaths, repoPath, specPaths, tbId, text, type ArtifactRef, unexecuted, permissionBlocked,
} from "./at18-format.ts";
import {
  type At18Repository, type Diagnostics, escapeToken, jsonBlob, refs, sorted, utf8, valueAt,
} from "./at18-source.ts";

export const destinationNames = ["DST-01", "DST-02", "DST-03", "DST-04", "DST-05", "DST-06"] as const;
const destinationName = z.enum(destinationNames);
const lists = { story: "story_ids", family: "family_entry_ids", detail: "detailed_acceptance_ids" } as const;
const kinds = kind.options;
export type Slice = z.infer<typeof tbId>;
const owner = {
  success_closure_slice_ids: z.array(tbId).min(1), destination_ids: z.array(destinationName),
};
const story = z.object({ story_id: text, ...owner });
const family = z.object({ id: text, family: text, source_json_pointer: text,
  exclusion_boundary: z.boolean().optional(), user_story_ids: z.array(text),
  acceptance_point_ids: z.array(text).optional(), ...owner });
const detail = z.object({ id: text, family_entry_id: text, source_json_pointer: text, user_story_ids: z.array(text), ...owner });
const dst = z.object({ destination_id: destinationName, story_ids: z.array(text).min(1),
  family_entry_ids: z.array(text).min(1), detailed_acceptance_ids: z.array(text).min(1) });
const storySource = z.object({ id: text, observable_result: z.string().optional() });
const unit = z.object({ parent_tb: tbId, story_ids: z.array(text), family_entry_ids: z.array(text), detailed_acceptance_ids: z.array(text) });
const contribution = z.object({ family_entry_id: text, parent_detailed_acceptance_ids: z.array(text) });
export type Dst = z.infer<typeof dst>;
export type Entry = { kind: Kind; id: string; slices: Slice[]; destinations: z.infer<typeof destinationName>[];
  boundary: boolean; family: string | null; familyEntry: string | null; path: string; pointer: string };
export type Key = { slice: Slice; entry: Entry; id: string; bases: Basis[] };
export const keyId = (slice: string, kind: string, id: string) => `key:${slice}/${kind}/${escapeToken(id)}`;
export const keyBasis = (key: string, basis: Basis) => `${key}@basis:${escapeToken(basis.path)}@${escapeToken(basis.pointer)}`;
export const keyDomain = (key: string, domain: Pick<Domain, "evidence_class" | "profile_id">) =>
  `${key}@${domain.evidence_class}@${domain.profile_id ?? "none"}`;
export function basisId(b: Basis) { return b.path + "\0" + b.pointer; }
export const unique = <T>(xs: T[]) => new Set(xs).size === xs.length;

export function readCoverage(
  crosswalk: Record<string, unknown> | undefined, coverage: Record<string, unknown> | undefined,
  ledgers: (Record<string, unknown> | undefined)[], issues: Diagnostics, spec?: Record<string, unknown>,
) {
  const specStories = (Array.isArray(spec?.stories) ? spec.stories : []).flatMap(row => {
    const parsed = storySource.safeParse(row);
    return parsed.success ? [parsed.data] : [];
  });
  const titles = destinationNames.map(id => {
    const scope = `/destinations/${destinationNames.indexOf(id)}/obligation`;
    const found = (Array.isArray(spec?.stories) ? spec.stories : []).filter(row => valueAt(row, "/id") === `US-${id}`);
    if (found.length > 1) throw new At18BootstrapError("FIXED_ITEM_UNAVAILABLE", "Destination 的实际义务不唯一。", scope);
    const obligation = valueAt(found[0], "/observable_result");
    if (typeof obligation === "string" && obligation) return obligation;
    if (obligation !== undefined && typeof obligation !== "string") {
      throw new At18BootstrapError("FIXED_ITEM_UNAVAILABLE", "Destination 的实际义务无法表示为字符串。", scope);
    }
    issues.add("COVERAGE_SOURCE", scope);
    return id;
  });
  const entries: Entry[] = [];
  const keys = new Map<string, Key>();
  const destinations = new Map<string, Dst>();
  const tables = [["story", "rows", story, 97], ["family", "family_entry_links", family, 345],
    ["detail", "detailed_acceptance_links", detail, 496]] as const;
  const lookup = new Map<string, Entry>();
  const linkedStories = new Set<string>();
  const linkedFamilies = new Set<string>();
  const linkedDetails = new Map<string, string>();
  const storyIds = new Set(specStories.map(s => s.id));
  for (const [type, table, schema, count] of tables) {
    const raw = crosswalk?.[table];
    const entriesForTable = new Map<string, Entry>();
    if (!Array.isArray(raw) || raw.length !== count) issues.add("COVERAGE_SOURCE", `/spec_coverage/${type === "family" ? "families" : type + (type === "story" ? "ies" : "s")}`.replace("storyies", "stories"));
    if (!Array.isArray(raw)) continue;
    for (const [index, value] of raw.entries()) {
      const parsed = schema.safeParse(value);
      if (!parsed.success) { issues.add("SCHEMA", `/spec_coverage/${type === "story" ? "stories" : type === "family" ? "families" : "details"}/${index}`); continue; }
      const row = parsed.data;
      const id = "story_id" in row ? row.story_id : row.id;
      const entry: Entry = { kind: type, id, slices: row.success_closure_slice_ids, destinations: row.destination_ids,
        boundary: "exclusion_boundary" in row && row.exclusion_boundary === true,
        family: "family" in row ? row.family : null,
        familyEntry: "family_entry_id" in row ? row.family_entry_id : null,
        path: specPaths.crosswalk_ref, pointer: `/${table}/${index}` };
      const path = "/spec_coverage/" + (type === "story" ? "stories" : type === "family" ? "families" : "details") + "/" + index;
      if (!unique(entry.slices) || !unique(entry.destinations) || /\s/.test(id) ||
          (type === "story" && !storyIds.has(id)) || ("user_story_ids" in row && row.user_story_ids.some(s => !linkedStories.has(s))) ||
          (entry.familyEntry && !linkedFamilies.has(entry.familyEntry))) issues.add("COVERAGE_SOURCE", path);
      if ("source_json_pointer" in row && valueAt(coverage, row.source_json_pointer + "/id") !== id) issues.add("COVERAGE_SOURCE", path);
      if (id === "OE42" && "source_json_pointer" in row &&
          valueAt(coverage, row.source_json_pointer + "/effective_disposition/kind") !== "OUT_OF_SCOPE_PRESERVE") issues.add("COVERAGE_SOURCE", path);
      if (entriesForTable.has(id)) { issues.add("COVERAGE_SOURCE", path); continue; }
      entriesForTable.set(id, entry);
      lookup.set(type + "/" + id, entry);
      if (type === "story") linkedStories.add(id);
      if (type === "family") linkedFamilies.add(id);
      if (entry.familyEntry) linkedDetails.set(id, entry.familyEntry);
      entries.push(entry);
      for (const slice of entry.slices) {
        const key = keyId(slice, type, id);
        keys.set(key, { slice, entry, id: key, bases: [] });
      }
    }
  }
  for (const row of Array.isArray(crosswalk?.family_entry_links) ? crosswalk.family_entry_links : []) {
    const entry = family.safeParse(row);
    if (entry.success && entry.data.acceptance_point_ids?.some(id => linkedDetails.get(id) !== entry.data.id)) {
      issues.add("COVERAGE_SOURCE", "/spec_coverage/families/" + entries.filter(e => e.kind === "family").findIndex(e => e.id === entry.data.id));
    }
  }
  if (keys.size !== 4071 || [...keys.values()].filter(k => k.slice === "TB-11").length !== 113 ||
      sorted(entries.filter(e => e.boundary).map(e => e.id)).join(",") !== "OE41,OE45") issues.add("COVERAGE_SOURCE", "/spec_coverage");
  const allDst = z.array(dst).safeParse(crosswalk?.destination_success_obligations);
  if (!allDst.success) issues.add("COVERAGE_SOURCE", "/destinations");
  for (const d of allDst.success ? allDst.data : []) {
    if (destinations.has(d.destination_id)) issues.add("COVERAGE_SOURCE", "/destinations");
    destinations.set(d.destination_id, d);
    for (const type of kinds) {
      if (!unique(d[lists[type]]) || d[lists[type]].some(id => !lookup.get(type + "/" + id)?.destinations.includes(d.destination_id))) {
        issues.add("COVERAGE_SOURCE", "/destinations/" + destinationNames.indexOf(d.destination_id));
      }
    }
  }
  if (destinations.size !== 6) issues.add("COVERAGE_SOURCE", "/destinations");
  for (const [i, path] of ledgerPaths.entries()) {
    if (i === 3) {
      const result = z.array(contribution).safeParse(ledgers[i]?.rows);
      if (!result.success) { issues.add("COVERAGE_SOURCE", "/slice_ledger_refs/3"); continue; }
      for (const [j, row] of result.data.entries()) {
        for (const [type, ids] of [["family", [row.family_entry_id]], ["detail", row.parent_detailed_acceptance_ids]] as const) {
          for (const id of ids) {
            const key = keys.get(keyId("TB-01", type, id));
            if (key && !key.bases.some(b => b.path !== path)) key.bases.push({ path, pointer: `/rows/${j}` });
          }
        }
      }
    } else {
      const result = z.array(unit).safeParse(ledgers[i]?.units);
      if (!result.success) { issues.add("COVERAGE_SOURCE", "/slice_ledger_refs/" + i); continue; }
      for (const [j, row] of result.data.entries()) {
        for (const type of kinds) for (const id of row[lists[type]]) {
          keys.get(keyId(row.parent_tb, type, id))?.bases.push({ path, pointer: `/units/${j}` });
        }
      }
    }
  }
  for (const key of keys.values()) if (!key.bases.length) key.bases.push({ path: key.entry.path, pointer: key.entry.pointer });
  return { entries, lookup, keys, destinations, titles };
}
export type Coverage = ReturnType<typeof readCoverage>;

function annotations(check: Check, source: string): Set<string> {
  if (check.runner === "command") return new Set();
  const lines = source.split(/\r?\n/);
  const declarations: number[] = [];
  for (const [i, line] of lines.entries()) {
    const node = /^\s*(?:test|it)\s*\(\s*(["'])([^"'\\]+)\1\s*,/.exec(line);
    const py = /^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\(/.exec(line);
    const rust = /^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)\(/.exec(line);
    const name = check.runner === "node-test" ? node?.[2] : check.runner === "pytest" ? py?.[1] : rust?.[1];
    const leaf = check.runner === "node-test" ? check.selector : check.selector.split("[")[0].split("::").at(-1)?.split("/").at(-1);
    if (name && leaf === name) declarations.push(i);
  }
  if (declarations.length !== 1) throw new Error("CHECK_SELECTOR");
  let start = declarations[0] - 1;
  while (start >= 0 && /^\s*(?:#\[|@)/.test(lines[start])) start--;
  const result = new Set<string>();
  for (let i = start; i >= 0 && /^\s*(?:\/\/|#)/.test(lines[i]); i--) {
    const m = /^\s*(?:\/\/|#)\s*@at18 (TB-\d\d) (story|family|detail) (\S+)\s*$/.exec(lines[i]);
    if (m) result.add(keyId(m[1], m[2], m[3]));
  }
  return result;
}
export type KeyDomain = { domain: Domain; checkIds: string[]; basis: Basis };
export function bindCoverage(reg: Registry | undefined, coverage: Coverage, source: At18Repository, F: string, diag: Diagnostics) {
  const checks = new Map<string, Check>();
  const groups = new Map<string, Check[]>();
  const invalidChecks = new Set<string>();
  const keyDomains = new Map<string, KeyDomain[]>();
  const badKeys = new Set<string>();
  const activeByCheck = new Map<string, Map<string, { key: Key; basis: Basis }>>();
  const producer = new Map<string, Check>();
  const marker = new Map<string, Set<string>>();
  const byBasis = new Map<string, Set<string>>();
  const basisDoc = new Map<string, ReturnType<typeof jsonBlob>>();
  const lookup = (record: string, profile: string | null) => record + "@" + (profile ?? "none");
  const badCheck = (check: Check, code: string) => { invalidChecks.add(check.check_id); diag.add(code, "check:" + check.check_id); };
  for (const check of reg?.checks ?? []) {
    if (checks.has(check.check_id)) badCheck(check, "REGISTRY_INVALID");
    checks.set(check.check_id, check);
    if (check.evidence_class === "production") badCheck(check, "PRODUCTION_SCOPE_CHANGED");
    if (check.evidence_class === "experiment" && (!check.profile_id || check.profile_id !== reg?.experiment_profile_id)) badCheck(check, "DOMAIN_INVALID");
    const group = groups.get(check.group) ?? [];
    if (group.some(c => c.evidence_class !== check.evidence_class || c.profile_id !== check.profile_id)) {
      for (const c of [...group, check]) badCheck(c, "DOMAIN_INVALID");
    }
    group.push(check);
    groups.set(check.group, group);
    const ext = { "node-test": /\.[cm]?[jt]s$/, pytest: /\.py$/, "cargo-test": /\.rs$/, command: /./ }[check.runner];
    if (!ext.test(check.source.path) || /[\x00-\x1f]/.test(check.selector) ||
        (check.runner === "command" && (check.selector !== check.source.path || !check.key_aware || check.expected_count !== 1)) ||
        (check.runner === "node-test" && check.selector.trim() !== check.selector)) badCheck(check, "CHECK_SELECTOR");
    try {
      const bytes = source.blob(F, check.source.path);
      if (byteSha256(bytes) !== check.source.sha256) badCheck(check, "CHECK_SOURCE_DRIFT");
      else if (!check.key_aware || check.runner !== "command") marker.set(check.check_id, annotations(check, utf8(bytes)));
    } catch (e) { badCheck(check, e instanceof Error && e.message === "CHECK_SELECTOR" ? "CHECK_SELECTOR" : "CHECK_SOURCE_DRIFT"); }
    if (check.record !== null) {
      const name = lookup(check.record, check.profile_id);
      const valid = /^tb\.(simulation|experiment)\.TB-(0[1-9]|10)$/.exec(check.record)?.[1] === check.evidence_class ||
        (check.evidence_class === "experiment" && /^(permission|migration|post_gate)\.experiment$/.test(check.record));
      if (!valid || producer.has(name)) badCheck(check, "RECORD_UNSEALED");
      else producer.set(name, check);
    }
  }

  const ids = new Set<string>();
  for (const binding of reg?.bindings ?? []) {
    let goodBasis = true;
    try {
      const data = basisDoc.get(binding.basis.path) ?? jsonBlob(source, F, binding.basis.path);
      basisDoc.set(binding.basis.path, data);
      goodBasis = byteSha256(data.bytes) === binding.basis.sha256 && valueAt(data.json, binding.basis.pointer) !== undefined;
    } catch { goodBasis = false; }
    const idRepeated = ids.has(binding.binding_id);
    ids.add(binding.binding_id);
    for (const declared of binding.keys) {
      const k = keyId(binding.slice_id, declared.kind, declared.id);
      const key = coverage.keys.get(k);
      if (!key || key.slice === "TB-11") { diag.add("KEY_NOT_EXPECTED", k); continue; }
      const basis = basisId(binding.basis);
      const present = byBasis.get(k) ?? new Set<string>();
      const scope = keyBasis(k, binding.basis);
      const fail = (code: string, s = scope) => { badKeys.add(k); diag.add(code, s); };
      if (idRepeated) fail("REGISTRY_INVALID");
      if (!goodBasis || !key.bases.some(b => basisId(b) === basis) || present.has(basis)) { fail("BASIS_MISMATCH"); continue; }
      present.add(basis);
      byBasis.set(k, present);
      const seenDomains = new Set<string>();
      if (!binding.domains.some(d => d.result !== "BOUNDED_DEFERRED")) fail("DOMAIN_INVALID");
      for (const domain of binding.domains) {
        const scoped = keyDomain(scope, domain);
        const dfail = (code: string) => fail(code, scoped);
        const id = lookup(domain.evidence_class, domain.profile_id);
        if (seenDomains.has(id) || !unique(domain.checks) ||
            (domain.evidence_class !== "simulation" && domain.profile_id === null) ||
            (domain.evidence_class === "experiment" && domain.profile_id !== reg?.experiment_profile_id) ||
            key.entry.boundary !== (domain.result === "PRESERVED_BOUNDARY")) dfail("DOMAIN_INVALID");
        seenDomains.add(id);
        if (domain.result === "BOUNDED_DEFERRED") {
          if (domain.checks.length || !domain.deferred_gate) dfail("DOMAIN_INVALID");
        } else {
          if (!domain.checks.length || domain.deferred_gate !== null || domain.evidence_class === "production") dfail("DOMAIN_INVALID");
          for (const id of domain.checks) {
            const check = checks.get(id);
            if (!check || check.evidence_class !== domain.evidence_class || check.profile_id !== domain.profile_id) {
              dfail("DOMAIN_INVALID"); continue;
            }
            if (invalidChecks.has(id)) dfail("CHECK_SOURCE_DRIFT");
            if (!check.key_aware && !marker.get(id)?.has(k)) dfail("CHECK_NOT_ANNOTATED");
            const active = activeByCheck.get(id) ?? new Map();
            active.set(scope, { key, basis: binding.basis });
            activeByCheck.set(id, active);
          }
        }
        const domains = keyDomains.get(k) ?? [];
        domains.push({ domain, checkIds: domain.checks, basis: binding.basis });
        keyDomains.set(k, domains);
      }
    }
  }
  for (const key of coverage.keys.values()) {
    if (key.slice === "TB-11") continue;
    const found = byBasis.get(key.id);
    if (!found?.size) { badKeys.add(key.id); diag.add("KEY_UNBOUND", key.id); }
    else for (const basis of key.bases) if (!found.has(basisId(basis))) {
      badKeys.add(key.id); diag.add("BASIS_INCOMPLETE", keyBasis(key.id, basis));
    }
  }
  const usedCures = new Set(reg?.pregate.landings.flatMap(l => l.cure_checks.map(c => c.check_id)));
  for (const c of checks.values()) {
    if (!activeByCheck.has(c.check_id) && !c.record && !usedCures.has(c.check_id)) badCheck(c, "DOMAIN_INVALID");
  }
  return { checks, groups, invalidChecks, keyDomains, badKeys, activeByCheck, producer };
}
export type Bindings = ReturnType<typeof bindCoverage>;
export type Gap = z.infer<typeof unexecuted>;
export type Blocked = z.infer<typeof permissionBlocked>;
export type Class = z.infer<typeof evidenceClass>;
export type KeyResult = { status: "FAIL" | "VERIFIED" | "PRESERVED_BOUNDARY" | "BOUNDED_DEFERRED"; deferred: string[] };
export function resolveKeys(coverage: Coverage, bindings: Bindings, prove: (d: KeyDomain, key: Key) => boolean,
  tb11: boolean, diag: Diagnostics) {
  const results = new Map<string, KeyResult>();
  for (const k of coverage.keys.values()) {
    if (k.slice === "TB-11") {
      results.set(k.id, { status: tb11 ? "VERIFIED" : "FAIL", deferred: [] });
      continue;
    }
    let good = !bindings.badKeys.has(k.id);
    const deferred: string[] = [];
    for (const d of bindings.keyDomains.get(k.id) ?? []) {
      if (!prove(d, k)) good = false;
      else if (d.domain.deferred_gate) deferred.push(d.domain.deferred_gate);
    }
    if (!good) diag.add("TB_KEYS", k.id);
    results.set(k.id, { status: !good ? "FAIL" : k.entry.boundary ? "PRESERVED_BOUNDARY" :
      deferred.length ? "BOUNDED_DEFERRED" : "VERIFIED", deferred: sorted(deferred) });
  }
  return results;
}
export function projectCoverage(coverage: Coverage, results: Map<string, KeyResult>, registry: ArtifactRef | null, bundle: ArtifactRef | null) {
  function fields(entry: Entry) {
    const found = entry.slices.map(slice => results.get(keyId(slice, entry.kind, entry.id)));
    const status = !found.length || found.some(r => !r || r.status === "FAIL") ? "FAIL" :
      entry.boundary ? "PRESERVED_BOUNDARY" : found.some(r => r?.status === "BOUNDED_DEFERRED") ? "BOUNDED_DEFERRED" : "VERIFIED";
    return { status,
      evidence_refs: refs([registry && found.some((r, i) => r && r.status !== "FAIL" && entry.slices[i] !== "TB-11") ? registry : null,
        bundle && found.some((r, i) => r && r.status !== "FAIL" && entry.slices[i] === "TB-11") ? bundle : null]
        .filter((ref): ref is ArtifactRef => ref !== null)),
      deferred_gates: sorted(found.flatMap(r => r?.deferred ?? [])) };
  }
  const stories = coverage.entries.filter(e => e.kind === "story").map(e => ({ story_id: e.id,
    closure_slice_ids: e.slices, destination_ids: e.destinations, ...fields(e) }));
  const families = coverage.entries.filter(e => e.kind === "family").map(e => ({ family: e.family, id: e.id,
    entry_mode: e.boundary ? "OUT_OF_SCOPE_PRESERVE" : "REQUIRED", ...fields(e) }));
  const details = coverage.entries.filter(e => e.kind === "detail").map(e => ({ id: e.id, family_entry_id: e.familyEntry, ...fields(e) }));
  return { stories, families, details };
}

export function preserveRegistryDomains(old: Registry, current: Registry, diag: Diagnostics) {
  const identity = (reg: Registry) => new Map(reg.bindings.flatMap(b => b.keys.flatMap(k => {
    const key = keyBasis(keyId(b.slice_id, k.kind, k.id), b.basis);
    return b.domains.map(d => [keyDomain(key, d), d.result] as const);
  })));
  const before = identity(old), now = identity(current);
  let ok = true;
  for (const [scope, result] of before) {
    if (!now.has(scope) || (result !== "BOUNDED_DEFERRED" && now.get(scope) !== result)) {
      diag.add("DOMAIN_SHRINK", scope);
      ok = false;
    }
  }
  return ok;
}
