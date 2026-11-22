import { deliveredProducts, ownedPr } from "./at18-products.ts";
import { z } from "zod";
import { adapter, pregateSchema, registrySchema, type Adapter, type Registry } from "./at18-contract.ts";
import {
  bindCoverage, destinationNames, keyId, preserveRegistryDomains, projectCoverage, readCoverage, resolveKeys, type Slice,
} from "./at18-coverage.ts";
import {
  authorizeExperiment, validateTbEntities, EXP, externalSources, type External, Gaps, migration, P2, permission, postGate,
  PROD, productionDisabled, proveDomain, runRecords, slot,
} from "./at18-evidence.ts";
import {
  At18BootstrapError, at18InputBundleSchema, at18ReportSchema, byteSha256, canonicalizeJcs, heavy, ledgerPaths,
  legacyTickets, parseJsonObject, seal, sha, specPaths, type ArtifactRef, type At18InputBundle, type At18Report, tbIds, tbTickets, workflows,
} from "./at18-format.ts";
import {
  checkWorkflows, integrationReviews, JobEvidence, loadRuns, selectRun, Tracker, type Ticket,
} from "./at18-integrations.ts";
import { type Row, object } from "./at18-github.ts";
import { legacyDispositions } from "./at18-legacy.ts";
import { historyDeviations, replayPregate } from "./at18-pregate.ts";
import { at18, type At18Repository, compare, Diagnostics, extRef, jsonBlob, type Own, repoRef, refs, sorted } from "./at18-source.ts";

export { at18InputBundleSchema, at18ReportSchema, byteSha256, canonicalizeJcs, computeContentHash, parseJsonObject,
  type At18InputBundle, type At18Report, type ArtifactRef, specPaths, tbTickets } from "./at18-format.ts";

const registryPath = at18 + "registry.json";
const contractPath = at18 + "adapter-contract.json";
const prePath = at18 + "pregate-review.json";
const postgateApi = new Map([[1391, ".sandcastle/at18-report.mts"], [1403, ".sandcastle/at18-verification.mts"]]);
const failCode = (e: unknown) =>
  e instanceof Error && "check_id" in e && typeof e.check_id === "string" ? e.check_id :
    e instanceof z.ZodError ? "SCHEMA" : "FILE_READ";

export function boundedStatement(deviations: number, status: NonNullable<At18Report["post_gate_records"]["experiment"]>["status"],
  heavyDeferred: boolean) {
  return [
    "AT18_LANDING_CI_NOT_CERTIFIED n=" + deviations,
    "AT18_PREGATE_REVIEWER_VOUCHED_BY_TICKET 2132",
    "AT18_CHECK_SUFFICIENCY_BY_FORMAL_GATE",
    "AT18_SCOPE SIMULATION_P1_ONLY", "AT18_PRODUCTION_SLOT DISABLED",
    "AT18_POST_GATE_EXPERIMENT " + status, "AT18_POST_GATE_PRODUCTION DISABLED",
    ...(heavyDeferred ? ["AT18_HEAVY_MEASUREMENT DEFERRED"] : []),
  ].join("\n");
}

function tb11Products(s: At18Repository, F: string, chain: string[], accepted: Map<string, Row>, diag: Diagnostics) {
  let ok = true;
  for (const [ticket, path] of postgateApi) {
    let valid = false;
    try {
      const product = s.blob(F, path);
      const anchor = s.anchor(path, chain);
      const pr = anchor && accepted.get(anchor);
      if (anchor && pr && product.length && ownedPr(pr, ticket)) {
        const i = chain.indexOf(anchor);
        const parent = chain[i + 1] ?? s.string("rev-parse", anchor + "^1");
        valid = s.changed(parent, anchor).includes(path);
      }
    } catch { /* 未落地、路径非普通 blob 或无法验证归属。 */ }
    if (!valid) {
      diag.add("TB11_PREFLIGHT", "ticket:" + ticket);
      ok = false;
    }
  }
  return ok;
}

export async function generateAt18(s: At18Repository, own: Own, manifestPaths: string[], inputBundlePath: string,
  windowsStart = new Date().toISOString()) {
  const diag = new Diagnostics();
  const heavyDiagnostics = new Diagnostics();
  const gaps = new Gaps();
  const { manifest } = own;
  const F = manifest.head;
  async function confirmMain(fresh: boolean) {
    const observed = await diag.get("/head", async () => {
      const ref = await s.github.get("git/ref/heads/main", fresh);
      if (ref.ref !== "refs/heads/main" || object(ref.object).type !== "commit") throw new Error("ref");
      return sha.parse(object(ref.object).sha);
    });
    if (observed !== F) diag.add("HEAD_CHANGED", "/head");
    try {
      if (s.string("rev-parse", "--verify", F + "^{commit}") !== F ||
          s.string("rev-parse", "--verify", "refs/remotes/origin/main^{commit}") !== F ||
          !s.ancestor(manifest.base, F)) {
        diag.add("ANCESTRY", "/head");
        return false;
      }
    } catch { diag.add("ANCESTRY", "/head"); return false; }
    return observed === F;
  }
  const main = await confirmMain(false);
  const tracker = new Tracker(s, diag);
  const tickets = Promise.all([...new Set([...Object.values(tbTickets), ...legacyTickets, 1391, 1403, 1340, 1323])]
    .map(n => tracker.issue(n))).then(rows => new Map(rows.map(row => [row.number, row])));
  const roster = Promise.all(tbIds.slice(0, 10).map(async slice => [slice, await tracker.native(tbTickets[slice])] as const));
  const r09 = integrationReviews(s, F, diag);
  const selectedRuns = loadRuns(s, F, diag);
  const p2 = productionDisabled(tracker, diag);
  const external = externalSources(s, F, manifestPaths, own, diag, heavyDiagnostics);
  function read(path: string, scope: string) {
    try { return jsonBlob(s, F, path); }
    catch (e) { diag.add(failCode(e), scope); return undefined; }
  }
  const specData = read(specPaths.spec_ref, "/spec_ref");
  let crosswalkSha: string | null = null;
  let crosswalk: ReturnType<typeof jsonBlob> | undefined;
  try {
    const bytes = s.blob(F, specPaths.crosswalk_ref);
    crosswalkSha = byteSha256(bytes);
    const json = parseJsonObject(bytes);
    canonicalizeJcs(json);
    crosswalk = { bytes, json };
  } catch (e) { diag.add(failCode(e), "/crosswalk_ref"); }
  const coverageInput = read(specPaths.coverage_input_ref, "/coverage_input_ref");
  const ledgers = ledgerPaths.map((path, index) => read(path, "/slice_ledger_refs/" + index));
  const coverage = readCoverage(crosswalk?.json, coverageInput?.json, ledgers.map(l => l?.json), diag, specData?.json);
  if (coverageInput && crosswalk?.json.coverage_sha256 !== byteSha256(coverageInput.bytes)) diag.add("COVERAGE_SOURCE", "/spec_coverage");
  const sourcesOK = !diag.all().some(f => ["COVERAGE_SOURCE", "SCHEMA"].includes(f.check_id) &&
    ["/spec_coverage", "/destinations", "/slice_ledger_refs"].some(prefix => f.scope.startsWith(prefix)));
  const regData = read(registryPath, "/registry_ref");
  const contractData = read(contractPath, "/registry_ref");
  const preData = read(prePath, "/pregate_review_ref");
  const finalReviews = await r09;
  let reg: Registry | undefined;
  let contract: Adapter | undefined;
  try {
    reg = registrySchema.parse(regData?.json);
    if (!contractData || !crosswalk || reg.crosswalk_sha256 !== crosswalkSha ||
        reg.adapter_contract_sha256 !== byteSha256(contractData.bytes)) throw new Error("reference");
    contract = adapter(contractData.json);
    for (const p of [registryPath, contractPath]) {
      const anchor = s.anchor(p, finalReviews.chain);
      if (!anchor || !finalReviews.accepted.has(anchor)) {
        diag.add("REVIEW_FINAL_PRODUCT", anchor ? "commit:" + anchor : "/registry_ref");
        if (p === registryPath) diag.add("PREGATE_REVIEW", "pre:" + p);
        throw new Error("anchor");
      }
      if (p === registryPath) {
        const previous = s.string("rev-parse", anchor + "^1");
        if (s.tree(previous).has(registryPath)) {
          const old = registrySchema.parse(jsonBlob(s, previous, registryPath).json);
          if (!preserveRegistryDomains(old, reg, diag)) throw new Error("domain shrink");
        }
      }
    }
  } catch {
    reg = undefined; contract = undefined;
    diag.add("REGISTRY_INVALID", "/registry_ref");
  }
  // 即使登记内容不可解码，仍能为每个未获审的 PRE 原件单独定位。
  for (const p of [registryPath, prePath, at18 + "landing-census.json"]) {
    const anchor = s.anchor(p, finalReviews.chain);
    if (!anchor || !finalReviews.accepted.has(anchor)) {
      diag.add("REVIEW_FINAL_PRODUCT", anchor ? "commit:" + anchor : "pre:" + p);
      diag.add("PREGATE_REVIEW", "pre:" + p);
    }
  }
  const prereview = pregateSchema.safeParse(preData?.json);
  if (!prereview.success) diag.add("PREGATE_REVIEW", "/pregate_review_ref");
  if (!reg || !prereview.success) diag.add("PREGATE_LANDINGS", "/pregate_review_ref");
  const pre = reg && prereview.success ?
    await replayPregate(s, F, reg, prereview.data, finalReviews.chain, finalReviews.accepted, tracker, diag) :
    { ok: false, projection: [] };
  const bindings = bindCoverage(reg, coverage, s, F, diag);
  const checkRuns = await selectedRuns;
  const jobs = new JobEvidence(checkRuns, diag);
  const registrySha = reg && regData ? byteSha256(regData.bytes) : undefined;
  const execution = checkWorkflows(s, F, jobs, bindings, registrySha);
  const profile = reg?.experiment_profile_id ?? null;
  const auth = await authorizeExperiment(contract, bindings, tracker, profile, windowsStart, execution.checkJobs, diag);
  const runEvidence = runRecords(s, F, own, bindings, contract, registrySha, jobs, execution.passed, auth, diag);
  const previous = await historyDeviations(s, F, pre.projection, reg, bindings, execution.passed, diag);
  const allExternal = await external;
  const used = new Set<External>();
  const p2Disabled = await p2;
  const scopeOK = p2Disabled && !diag.all().some(f => f.check_id === "PRODUCTION_SCOPE_CHANGED");
  const permissionSlot = permission(runEvidence.get(slot("permission.experiment", profile)) ?? [], allExternal, contract, profile, diag, used);
  const permitted = Object.values(permissionSlot).every(x => x !== null) && scopeOK;
  const migrationSlot = migration(runEvidence.get(slot("migration.experiment", profile)) ?? [], profile, diag);
  const migrated = migrationSlot.no_lost_rights && migrationSlot.no_duplicated_capital && migrationSlot.no_dual_write &&
    migrationSlot.no_resend && scopeOK;
  const post = postGate(runEvidence.get(slot("post_gate.experiment", profile)) ?? [], allExternal, contract, profile, diag, used);
  const p1Entities = new Map<string, ArtifactRef[]>();
  const verifiedEntities = new Map<string, ReturnType<typeof validateTbEntities>>();
  for (const [id, producer] of bindings.producer) {
    if (!id.startsWith("tb.")) continue;
    const record = producer.record!;
    const s = slot(record, producer.profile_id);
    const valid = validateTbEntities(record, producer.profile_id, runEvidence.get(s) ?? [], bindings, diag);
    verifiedEntities.set(s, valid);
    p1Entities.set(record, refs([...(p1Entities.get(record) ?? []), ...valid.map(e => e.ref)]));
  }
  for (const name of ["permission.experiment", "migration.experiment", "post_gate.experiment"]) {
    const obligation = slot(name, profile);
    const producer = bindings.producer.get(name + "@" + (profile ?? "none"));
    const blockers = producer && auth.get(producer.group);
    if (blockers || !producer && !contract) {
      diag.add("AUTH_REQUIRED", obligation);
      gaps.notRun(obligation, "experiment", "AUTH_REQUIRED", ...(blockers ?? [2133]));
    } else if (!producer) {
      diag.add("SPECIAL_GATE", obligation);
      gaps.notRun(obligation, "experiment", "SOURCE_UNAVAILABLE");
    } else if (!execution.executed.has(producer.group)) gaps.notRun(obligation, "experiment", "CHECK_NOT_RUN");
  }
  gaps.defer(P2, "production", "PRODUCTION_NOT_ENABLED", "ticket:1561");
  gaps.defer(PROD, "production", "POST_GATE:DISABLED", "adr:0036");
  if (post.result.status !== "TRIGGERED_AND_ENABLED") gaps.defer(EXP, "experiment", "POST_GATE:" + post.result.status, "adr:0036");

  const byTicket = await tickets;
  const native = new Map<Slice, Ticket[]>(await roster);
  const reviewOK = main && execution.ok && finalReviews.ok;
  const fixedInputs = [specData, crosswalk, coverageInput, regData, preData, ...ledgers];
  const inputAvailable = Boolean(main && fixedInputs.every(Boolean) && reg && contract && prereview.success && sourcesOK && pre.ok);
  const stage = byTicket.get(1391)?.state === "OPEN" && byTicket.get(1403)?.state !== null && byTicket.get(1403) !== undefined;
  if (!stage) diag.add("TB11_PREFLIGHT", "ticket:1391");
  // 阶段错误不反向参与 TB-11 的前置结果。
  for (const n of [1369, 1340, 1323]) {
    if (byTicket.get(n)?.state !== "OPEN") diag.add("CLOSEOUT_STAGE", "ticket:" + n);
  }
  const products = tb11Products(s, F, finalReviews.chain, finalReviews.accepted, diag);
  const tb11 = stage && inputAvailable && reviewOK && products;
  if (!tb11) diag.add("TB11_PREFLIGHT", "/tb_summaries/10/input_bundle");
  const keyResults = resolveKeys(coverage, bindings, (d, k) => proveDomain(d, k, bindings, execution.passed, execution.executed,
    auth, runEvidence, verifiedEntities, post, scopeOK, gaps, diag), tb11, diag);
  const tbPass = new Map<Slice, boolean>([["TB-11", tb11]]);
  const historicalOwners = new Map<string, Set<number>>();
  for (const { ticket, commits } of pre.projection) for (const commit of commits) {
    let owners = historicalOwners.get(commit);
    if (!owners) { owners = new Set(); historicalOwners.set(commit, owners); }
    owners.add(ticket);
  }
  const nativeAttributions = new Map<number, string[]>();
  const r12ByTicket = new Map<number, boolean>();
  for (const slice of tbIds.slice(0, 10)) {
    const ticket = tbTickets[slice];
    const parent = byTicket.get(ticket);
    const scope = "ticket:" + ticket;
    const slices = native.get(slice) ?? [];
    const parentDone = parent?.state === "CLOSED" && parent.reason === "COMPLETED";
    if (!parentDone) diag.add("TICKET_NOT_CLOSED", scope);
    const children = await tracker.children(ticket);
    const childSources = await Promise.all((children ?? []).map(id => tracker.issue(id)));
    const complete = !!children && childSources.every(a => a.state !== null) && slices.length > 0;
    if (!complete) diag.add("SUBTICKET_INCOMPLETE", scope);
    for (const t of slices) {
      const products = deliveredProducts(s, t, historicalOwners, finalReviews.accepted);
      if (products.length) nativeAttributions.set(t.number, products);
      const pass = products.length > 0;
      if (!pass) diag.add("SUBTICKET_INCOMPLETE", "ticket:" + t.number);
      r12ByTicket.set(t.number, pass);
    }
    const sliceKeys = [...coverage.keys.values()].filter(k => k.slice === slice);
    const keysOK = !!sliceKeys.length && sliceKeys.every(k => keyResults.get(k.id)?.status !== "FAIL");
    if (!keysOK) diag.add("TB_KEYS", scope);
    const simulation = p1Entities.get("tb.simulation." + slice) ?? [];
    const experiment = p1Entities.get("tb.experiment." + slice) ?? [];
    const asksExperiment = sliceKeys.some(k => bindings.keyDomains.get(k.id)?.some(d =>
      d.domain.evidence_class === "experiment" && d.domain.result !== "BOUNDED_DEFERRED")) || ["TB-08", "TB-09", "TB-10"].includes(slice);
    let reportsOK = simulation.length + experiment.length > 0 && (!asksExperiment || experiment.length > 0);
    reportsOK &&= !diag.all().some(f => f.check_id === "TB_REPORT" && f.scope.includes("." + slice + "@"));
    if (!reportsOK) diag.add("TB_REPORT", scope);
    const affectedHistory = pre.projection.some(p => p.attribution_scopes.some(scope => scope === slice) && previous.failedTickets.has(p.ticket));
    const special = (slice !== "TB-09" || permitted) && (slice !== "TB-10" || migrated);
    tbPass.set(slice, reviewOK && pre.ok && parentDone && complete && slices.every(r => r12ByTicket.get(r.number) === true) &&
      keysOK && reportsOK && special && !affectedHistory);
  }
  const allCurrent = main && reviewOK && pre.ok && sourcesOK && scopeOK && permitted && migrated && post.valid &&
    [...coverage.keys.values()].every(k => keyResults.get(k.id)?.status !== "FAIL") && tbIds.every(slice => tbPass.get(slice)) && !diag.size;
  const legacy = await legacyDispositions(s, F, contract, tracker, allCurrent, tbPass, bindings, execution.passed, permitted, allExternal, used, finalReviews.accepted, finalReviews.reviews, diag);
  for (const error of heavyDiagnostics.all()) diag.add(error.check_id, error.scope, error.evidence_ref);
  if (legacy.deferredHeavy) gaps.defer(heavy, "simulation", "MEASUREMENT_NOT_COMPLETED", "ticket:1320");

  function bundleRef(path: string, bytes: Buffer, role: string) { return repoRef(F, path, bytes, role); }
  const registryRef = regData && reg ? bundleRef(registryPath, regData.bytes, "REGISTRY") : null;
  await Promise.all([...new Set(pre.projection.map(p => p.ticket))].map(ticket => tracker.issue(ticket)));
  const sampleRuns = await Promise.all(workflows.map((path, i) => selectRun(s, F, path, diag, i, true)));
  for (const [i, current] of sampleRuns.entries()) {
    const previous = checkRuns[i]?.run;
    if (current?.id !== previous?.id || current?.run_attempt !== previous?.run_attempt || current?.updated_at !== previous?.updated_at || current?.status !== previous?.status || current?.conclusion !== previous?.conclusion) {
      diag.add("WINDOW_DRIFT", "/workflow_runs/" + i);
    }
  }
  await tracker.stable();
  const finalMain = await confirmMain(true);
  const stableWindow = finalMain && !diag.all().some(f => f.check_id === "WINDOW_DRIFT");
  if (!stableWindow) {
    legacy.list.find(row => row.ticket === 1279)!.disposition_valid = false;
    diag.add("LEGACY_DISPOSITION", "ticket:1279");
  }
  const generated_at = new Date().toISOString();
  const identity = { ticket: 1391, base: manifest.base, head: F, generated_at };
  const uniqueManifests = new Map<string, External["manifest"]>();
  const manifestConflicts = new Set<string>();
  for (const x of used) {
    const key = x.manifest.ticket + "\0" + x.manifest.manifest_path;
    const existing = uniqueManifests.get(key);
    if (existing && canonicalizeJcs(existing) !== canonicalizeJcs(x.manifest)) manifestConflicts.add(key);
    uniqueManifests.set(key, x.manifest);
  }
  for (const key of manifestConflicts) {
    diag.add("SCHEMA", "/external_manifests");
    uniqueManifests.delete(key);
  }
  let bundle: At18InputBundle | null = null, bundleBytes: Buffer | null = null, inputRef: ArtifactRef | null = null;
  if (inputAvailable && specData && crosswalk && coverageInput && registryRef && preData && !manifestConflicts.size) {
    bundle = seal(at18InputBundleSchema, {
      schema_version: "at18-input-bundle/1", ...identity, spec_ref: bundleRef(specPaths.spec_ref, specData.bytes, "SPEC"),
      crosswalk_ref: bundleRef(specPaths.crosswalk_ref, crosswalk.bytes, "CROSSWALK"),
      coverage_input_ref: bundleRef(specPaths.coverage_input_ref, coverageInput.bytes, "COVERAGE_INPUT"),
      registry_ref: registryRef, pregate_review_ref: bundleRef(prePath, preData.bytes, "PREGATE"),
      slice_ledger_refs: ledgers.map((entry, i) => bundleRef(ledgerPaths[i], entry!.bytes, "SLICE_LEDGER")),
      external_manifests: [...uniqueManifests.values()].sort((a, b) => a.ticket - b.ticket || compare(a.manifest_path, b.manifest_path)),
    });
    bundleBytes = Buffer.from(canonicalizeJcs(bundle) + "\n");
    inputRef = extRef(manifest, inputBundlePath, bundleBytes, "INPUT_BUNDLE");
  } else diag.add("TB11_PREFLIGHT", "/tb_summaries/10/input_bundle");

  const projected = projectCoverage(coverage, keyResults, registryRef, inputRef);
  const remaining = new Map<Slice, Set<string>>();
  for (const slice of tbIds) remaining.set(slice, new Set<string>());
  const diagnostics = diag.all();
  const requiredGaps = gaps.unexecuted().filter(gap => gap.required);
  for (const [slice, values] of remaining) {
    const t = tbTickets[slice];
    if (slice !== "TB-11" && (byTicket.get(t)?.state !== "CLOSED" || byTicket.get(t)?.reason !== "COMPLETED")) values.add("ticket:" + t);
    for (const n of native.get(slice) ?? []) if (!r12ByTicket.get(n.number)) values.add("ticket:" + n.number);
    for (const { obligation } of requiredGaps) {
      if (obligation.startsWith("key:" + slice + "/") || obligation.includes("." + slice + "@") ||
          (slice === "TB-09" && obligation.startsWith("slot:permission.")) ||
          (slice === "TB-10" && obligation.startsWith("slot:migration.")) ||
          (slice === "TB-11" && obligation.startsWith("slot:post_gate."))) values.add(obligation);
    }
  }
  for (const key of coverage.keys.values()) {
    const r = keyResults.get(key.id);
    if (r?.status === "FAIL") remaining.get(key.slice)?.add(key.id);
    for (const d of r?.deferred ?? []) remaining.get(key.slice)?.add(d);
  }
  for (const error of heavyDiagnostics.all()) diag.add(error.check_id, error.scope, error.evidence_ref);
  if (legacy.deferredHeavy) remaining.get("TB-11")?.add(heavy);
  const CI = execution.ci;
  const reviews = finalReviews.reviews;
  const main_sha = main && finalMain ? F : null;
  const evidenceByClass = (slice: Slice) => ({
    simulation: p1Entities.get("tb.simulation." + slice) ?? [], experiment: p1Entities.get("tb.experiment." + slice) ?? [],
    production: null,
  });
  const ts = (t: Ticket | undefined, ticket: number) => ({ ticket, state: t?.state ?? null, state_reason: t?.reason ?? null });
  const diagnosticsForTb = (f: { scope: string; check_id: string }, slice: Slice) => {
    const t = tbTickets[slice];
    if (f.scope.startsWith("key:")) return f.scope.startsWith("key:" + slice + "/");
    if (f.scope.startsWith("slot:")) return f.scope.includes("." + slice + "@") ||
      (slice === "TB-09" && f.scope.startsWith("slot:permission.")) ||
      (slice === "TB-10" && f.scope.startsWith("slot:migration.")) ||
      (slice === "TB-11" && f.scope.startsWith("slot:post_gate."));
    if (f.scope.startsWith("ticket:")) return [t, ...(native.get(slice) ?? []).map(n => n.number),
      ...(slice === "TB-11" ? [1391, 1403] : [])].some(id => f.scope === "ticket:" + id || f.scope.startsWith("ticket:" + id + "@"));
    return ["HEAD_CHANGED", "WINDOW_DRIFT", "HEAD_CI", "REVIEW_FINAL_PRODUCT", "PREGATE_LANDINGS", "PREGATE_REVIEW",
      "REGISTRY_INVALID"].includes(f.check_id) || (slice === "TB-11" && f.check_id === "TB11_PREFLIGHT");
  };
  const tb_summaries: At18Report["tb_summaries"] = tbIds.map((slice, i) => {
    const t = tbTickets[slice];
    const evidence_by_class = evidenceByClass(slice);
    const slices = i === 10 ? [ts(byTicket.get(1391), 1391), ts(byTicket.get(1403), 1403)] :
      (native.get(slice) ?? []).map(t => ts(t, t.number));
    const isGateOK = tbPass.get(slice) === true && stableWindow && main_sha !== null && (i !== 10 || inputRef !== null);
    const todo = sorted([...(remaining.get(slice) ?? []), ...diagnostics.filter(f => diagnosticsForTb(f, slice))
      .map(f => f.check_id + "@" + f.scope)]);
    return { tb_id: slice, ticket: t, slices, input_bundle: i === 10 ? inputRef : null, evidence_by_class,
      final_reviews: reviews, main_sha, ci_runs: CI, entity_reports: refs([...evidence_by_class.simulation, ...evidence_by_class.experiment]),
      remaining_obligations: todo, ticket_state: byTicket.get(t)?.state ?? null, gate_satisfied: isGateOK };
  });
  const destinations: At18Report["destinations"] = [];
  for (const [i, name] of destinationNames.entries()) {
    const d = coverage.destinations.get(name);
    const entries = d ? [
      ...d.story_ids.map(id => coverage.lookup.get("story/" + id)),
      ...d.family_entry_ids.map(id => coverage.lookup.get("family/" + id)),
      ...d.detailed_acceptance_ids.map(id => coverage.lookup.get("detail/" + id)),
    ] : [];
    const selectedKeys = new Set(entries.flatMap(e => e?.slices.map(slice => keyId(slice, e.kind, e.id)) ?? []));
    const slices = [...new Set(entries.flatMap(e => e?.slices ?? []))];
    const id = i + 1;
    const tickets = new Map<string, { ticket: number; scope: string }>();
    const add = (ticket: number, scope: string) => tickets.set(ticket + "\0" + scope, { ticket, scope });
    for (const s of slices) {
      add(tbTickets[s], s);
      for (const n of native.get(s) ?? []) add(n.number, s);
      if (s === "TB-11") { add(1391, s); add(1403, s); }
    }
    for (const p of pre.projection) for (const sc of p.attribution_scopes) if (sc === "GRAPH" || slices.includes(sc)) add(p.ticket, sc);
    if (id === 6) { add(1304, "LEGACY"); add(1279, "LEGACY"); }
    const ticketIds = [...new Set([...tickets.values()].map(t => t.ticket))].sort((a, b) => a - b);
    const downstream_status = await Promise.all(ticketIds.map(async ticket => ({ ticket, state: (await tracker.issue(ticket)).state })));
    const relevant = [...selectedKeys].map(key => keyResults.get(key));
    const specOk = entries.length > 0 && entries.every(Boolean) && relevant.every(r => r && r.status !== "FAIL");
    const special = (![2, 3, 5].includes(id) || migrated) && (id !== 5 || permitted) &&
      (id !== 6 || legacy.list.filter(x => x.ticket === 1304 || x.ticket === 1279).every(x => x.disposition_valid));
    const pass = reviewOK && stableWindow && slices.every(slice => tbPass.get(slice) === true) && specOk && special && sourcesOK && scopeOK &&
      downstream_status.every(t => t.state !== null);
    if (!pass) diag.add("DESTINATION_AGGREGATE", "/destinations/" + i);
    const sim = slices.flatMap(s => evidenceByClass(s).simulation);
    const exp = slices.flatMap(s => evidenceByClass(s).experiment);
    if (id === 5 && permissionSlot.runtime_verification) exp.push(permissionSlot.runtime_verification);
    if ([2, 3, 5].includes(id)) exp.push(...migrationSlot.non_empty_evidence_refs);
    const todo = new Set<string>();
    for (const key of selectedKeys) {
      const result = keyResults.get(key);
      if (!result || result.status === "FAIL") todo.add(key);
      for (const deferred of result?.deferred ?? []) todo.add(deferred);
    }
    for (const tb of slices) {
      if (tb !== "TB-11" && byTicket.get(tbTickets[tb])?.state !== "CLOSED") todo.add("ticket:" + tbTickets[tb]);
      for (const n of native.get(tb) ?? []) if (!r12ByTicket.get(n.number)) todo.add("ticket:" + n.number);
    }
    const keyScope = (scope: string) => [...selectedKeys].some(key => scope === key || scope.startsWith(key + "@"));
    for (const { obligation } of requiredGaps) {
      if (keyScope(obligation) || ([2, 3, 5].includes(id) && obligation.startsWith("slot:migration.")) ||
        (id === 5 && obligation.startsWith("slot:permission.")) ||
        slices.some(slice => obligation.includes("." + slice + "@"))) todo.add(obligation);
    }
    for (const f of diagnostics) if (f.scope.startsWith("key:") ? keyScope(f.scope) :
      (slices.some(slice => diagnosticsForTb(f, slice)) && !f.scope.startsWith("slot:post_gate.") && f.check_id !== "TB11_PREFLIGHT") ||
      ([2, 3, 5].includes(id) && f.scope.startsWith("/migration_invariants")) ||
      (id === 5 && f.scope.startsWith("/destinations/4/permission_evidence/")) ||
      (id === 6 && (f.scope === "ticket:1279" || f.scope.startsWith("ticket:1304@")))) todo.add(f.check_id + "@" + f.scope);
    destinations.push({
      id, obligation: coverage.titles[i], tickets: [...tickets.values()].sort((a, b) => a.ticket - b.ticket || compare(a.scope, b.scope)),
      commits: sorted([...(main_sha ? [F] : []), ...pre.projection.filter(p => ticketIds.includes(p.ticket)).flatMap(p => p.commits),
        ...ticketIds.flatMap(t => nativeAttributions.get(t) ?? [])]),
      independent_reviews: reviews, main_sha, ci_runs: CI,
      evidence_by_class: { simulation: refs(sim), experiment: refs(exp), production: null },
      permission_evidence: id === 5 ? { experiment: permissionSlot, production: null } : null,
      downstream_status, remaining_obligations: sorted(todo), result: pass ? "PASS" : "FAIL",
    });
  }

  const failures = diag.all();
  const unexecuted = gaps.unexecuted();
  const permission_blocked = gaps.blocked();
  const passing = !failures.length && !unexecuted.some(u => u.required) && !permission_blocked.length &&
    destinations.every(d => d.result === "PASS") && tb_summaries.every(t => t.gate_satisfied) && legacy.list.every(l => l.disposition_valid);
  if (!passing && !failures.length) diag.add("SCHEMA", "/overall_result");
  let report: At18Report;
  try {
    report = seal(at18ReportSchema, {
      schema_version: "at18-report/1", ...identity,
      capability_hash: { experiment: permissionSlot.capability_hash, production: null },
      destinations, tb_summaries,
      spec_coverage: { crosswalk_sha256: crosswalkSha, ...projected },
      migration_invariants: { experiment: migrationSlot, production: null },
      post_gate_records: { experiment: post.result, production: null }, legacy_dispositions: legacy.list, unexecuted, permission_blocked,
      failed_checks: diag.all(), bounded_domain_statement: boundedStatement(previous.rows.length, post.result.status, legacy.deferredHeavy),
      workflow_runs: workflows.map((workflow, i) => ({ workflow, run_id: checkRuns[i]?.run.id ?? null, run_attempt: checkRuns[i]?.run.run_attempt ?? null })),
      acceptance_jobs: [...jobs.entries.values()].sort((a, b) => compare(a.workflow, b.workflow) || a.run_id - b.run_id ||
        a.run_attempt - b.run_attempt || compare(a.job, b.job)),
      historical_deviations: previous.rows, overall_result: passing ? "PASS" : "FAIL",
    });
  } catch (error) {
    throw new At18BootstrapError("CONTENT_NOT_CANONICAL", error instanceof Error ? error.message : "报告无法按合同编码。");
  }
  return { bundle, bundleBytes, report, reportBytes: Buffer.from(canonicalizeJcs(report) + "\n") };
}
