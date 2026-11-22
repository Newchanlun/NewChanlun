import { heavyInputChunk, type HeavyInputChunk } from "./at18-heavy-input.ts";
import { z } from "zod";
import {
  type Adapter, type Check, decodeFields, decodeRecord, envelope, profileId, tbConditions, tbOutput,
} from "./at18-contract.ts";
import {
  basisId, type Bindings, keyBasis, keyDomain, keyId, type Gap, type Blocked, type Key, type KeyDomain, unique,
} from "./at18-coverage.ts";
import {
  artifactRefSchema, byteSha256, canonicalizeJcs, deriveJson, digest, heavy, integer, manifestRefSchema,
  parseJsonObject, type ArtifactRef, type At18Report, type ManifestRef, type FailedCheck, workflows,
} from "./at18-format.ts";
import { deliveryManifestSchema } from "./delivery-bundle.ts";
import { object, rows, type Row } from "./at18-github.ts";
import { type Job, type JobEvidence, type Tracker, jobScope, success, utcBefore, proveExternalHead } from "./at18-integrations.ts";
import {
  artifactBytes, type At18Repository, compare, type Diagnostics, extRef, type Own,
  refs, sorted, utf8, type TreeEntry,
} from "./at18-source.ts";

type Migration = NonNullable<At18Report["migration_invariants"]["experiment"]>;
type PostGate = NonNullable<At18Report["post_gate_records"]["experiment"]>;
type Permission = NonNullable<NonNullable<At18Report["destinations"][number]["permission_evidence"]>["experiment"]>;
export type External = { ref: ArtifactRef; manifest: ManifestRef; json: Row; chunk?: HeavyInputChunk };
export type RecordEvidence = { ref: ArtifactRef; check: Check; data: Row };
export const slot = (record: string, profile: string | null) => "slot:" + record + "@" + (profile ?? "none");
export const P2 = "ISSUE_1561_P2_FIRST_SEND", EXP = "ADR_0036_POST_GATE_EXPERIMENT", PROD = "ADR_0036_POST_GATE_PRODUCTION";

export class Gaps {
  private readonly entries = new Map<string, Gap>();
  private readonly auth = new Map<string, Blocked>();
  private readonly priority = { AUTH_REQUIRED: 0, SOURCE_UNAVAILABLE: 1, CHECK_NOT_RUN: 2 };
  defer(obligation: string, evidence_class: Gap["evidence_class"], reason: string, blocker_or_gap: string) {
    this.entries.set(obligation, { obligation, evidence_class, reason, blocker_or_gap, required: false });
  }
  notRun(obligation: string, evidence_class: Gap["evidence_class"], reason: keyof Gaps["priority"], ...tickets: number[]) {
    const old = this.entries.get(obligation);
    const blocker = Math.min(...tickets);
    const previousPriority = old && Object.entries(this.priority).find(([name]) => name === old.reason)?.[1];
    const replace = !old || !old.required || previousPriority === undefined ||
      this.priority[reason] < previousPriority ||
      (reason === "AUTH_REQUIRED" && old.reason === reason && blocker < Number(old.blocker_or_gap.slice(7)));
    if (replace) this.entries.set(obligation, { obligation, evidence_class, reason, required: true,
      blocker_or_gap: tickets.length ? "ticket:" + blocker : reason });
    for (const blocker_ticket of tickets) {
      const key = obligation + "\0" + blocker_ticket + "\0" + evidence_class;
      this.auth.set(key, { obligation, evidence_class, blocker_ticket, missing_authorization: "AUTH_REQUIRED" });
    }
  }
  unexecuted() { return [...this.entries.values()].sort((a, b) => compare(a.obligation, b.obligation)); }
  blocked() { return [...this.auth.values()].sort((a, b) => compare(a.obligation, b.obligation) ||
    a.blocker_ticket - b.blocker_ticket || compare(a.evidence_class, b.evidence_class)); }
}
export async function externalSources(s: At18Repository, F: string, paths: string[], own: Own, diag: Diagnostics, heavyDiagnostics = diag) {
  const manifests = await Promise.all(sorted(paths).map(async path => {
    let bytes: Buffer;
    try { bytes = s.external(path); }
    catch { diag.add("FILE_READ", "/external_manifests"); return []; }
    let m;
    try { m = deriveJson(bytes, deliveryManifestSchema); }
    catch (e) { diag.add(derivationCode(e), "/external_manifests"); return []; }
    if (m.ticket === 1391 || m.ticket === 1403 || m.head === own.manifest.head && m.ticket === own.manifest.ticket ||
        !await proveExternalHead(s, m.head, F, diag, "/external_manifests")) return [];
    try { if (!s.ancestor(m.base, F)) throw new Error("base"); }
    catch { diag.add("ANCESTRY", "/external_manifests"); return []; }
    const ref = manifestRefSchema.parse({ ticket: m.ticket, base: m.base, head: m.head,
      manifest_path: path, manifest_sha256: byteSha256(bytes) });
    const records: External[] = [];
    const artifactDiag = m.ticket === 1320 ? heavyDiagnostics : diag;
    if (!unique(m.reports.map(r => r.path))) { diag.add("SCHEMA", "/external_manifests"); return []; }
    for (const report of m.reports) {
      if (!("storage" in report) || !report.path.endsWith(".json")) continue;
      let data: Buffer;
      try { data = artifactBytes(s, m, report); }
      catch { artifactDiag.add("ARTIFACT_REF", "ticket:" + m.ticket); continue; }
      try {
        const json = parseJsonObject(data);
        const artifact = extRef(m, report.path, data, "AUTHORIZATION");
        if (m.ticket === 1320 && json.schema_version === "at18-heavy-input-chunk/1") {
          const chunk = heavyInputChunk(json);
          records.push({ manifest: ref, ref: artifact, json: { schema_version: chunk.schema_version, head: chunk.head }, chunk });
        } else {
          canonicalizeJcs(json);
          records.push({ manifest: ref, ref: artifact, json });
        }
      } catch (e) { artifactDiag.add(derivationCode(e), "ticket:" + m.ticket); }
    }
    return records;
  }));
  return manifests.flat();
}
function derivationCode(e: unknown) {
  return e instanceof Error && "check_id" in e && typeof e.check_id === "string" ? e.check_id : "SCHEMA";
}

const noP2Comments = [6264190851, 6264283538, 6282695814, 6310811399, 6310848771, 6311315578, 6315084208];
const signedQ1 = "0389547746c5945f318a8b411605f8b083c97ab16878a0b69a4772385d6a0fdb";
export async function productionDisabled(tracker: Tracker, diag: Diagnostics) {
  const issue = await tracker.issue(1561);
  const comments = await diag.get("ticket:1561", () => tracker.s.github.list("issues/1561/comments?per_page=100"));
  const proof = comments?.find(c => c.id === 6310811399);
  const disabled = issue.state === "CLOSED" && issue.reason === "COMPLETED" &&
    comments?.length === noP2Comments.length && unique(comments.map(c => c.id)) && comments.every(c => noP2Comments.includes(Number(c.id))) &&
    typeof proof?.body === "string" && byteSha256(Buffer.from(proof.body)) === signedQ1;
  if (!disabled) diag.add("PRODUCTION_SCOPE_CHANGED", "ticket:1561");
  return !!disabled;
}
export async function authorizeExperiment(adapter: Adapter | undefined, b: Bindings, tracker: Tracker, profile: string | null,
  now: string, checkJobs: ReadonlyMap<string, Job>, diag: Diagnostics) {
  const missing = new Map<string, number[]>();
  const groups = [...b.groups].filter(([, c]) => c[0].evidence_class === "experiment");
  const policy = adapter?.experiment_authorization;
  let auth: Row | undefined;
  if (policy?.comment_id && policy.body_sha256 && profile && adapter) {
    const comment = await diag.get("ticket:2133", () => tracker.s.github.get("issues/comments/" + policy.comment_id));
    const issue = await tracker.issue(2133);
    const active = issue.data && await diag.get("ticket:2133", () => tracker.s.github.list("issues/2133/comments?per_page=100"));
    if (comment?.id === policy.comment_id && typeof comment.body === "string" &&
        comment.issue_url === `https://api.github.com/repos/${tracker.s.github.repo}/issues/2133` &&
        active?.some(c => c.id === comment.id && c.body === comment.body) &&
        active.every(c => typeof c.id === "number" && c.id <= policy.comment_id!) &&
        byteSha256(Buffer.from(comment.body)) === policy.body_sha256) {
      const fence = "```" + policy.signature_fence + "\n";
      const source = comment.body.replace(/\n$/, "");
      if (source.startsWith(fence) && source.endsWith("\n```")) {
        try {
          const raw = parseJsonObject(Buffer.from(source.slice(fence.length, -4)));
          canonicalizeJcs(raw);
          if (sorted(Object.keys(raw)).join() !== sorted(Object.keys(policy.fields)).join()) throw new Error("signature");
          const signed = decodeFields(adapter, policy.fields, raw);
          if (signed.schema_version === policy.signature_fence && signed.profile_id === profile &&
              profileId.safeParse(signed.runner_label).success && profileId.safeParse(signed.runner_group).success &&
              signed.runner_label !== "self-hosted" && signed.runner_group !== "Default" &&
              (signed.not_before === now || utcBefore(signed.not_before, now)) && utcBefore(now, signed.expires_at) &&
              Array.isArray(signed.actions) && signed.actions.length && unique(signed.actions) &&
              signed.actions.every(a => ["query", "place", "cancel", "reduce_only_close"].includes(String(a)))) auth = signed;
        } catch { /* 缺可验证签署照实记权限阻塞。 */ }
      }
    }
  }
  for (const [group] of groups) {
    const actions = policy?.group_actions[group];
    const required: number[] = [];
    const job = checkJobs.get(group);
    const allowed = auth?.actions;
    if (!auth || !actions?.length || !Array.isArray(allowed) || !actions.every(a => allowed.includes(a)) ||
        (job && (!job.labels?.includes("self-hosted") || !job.labels?.includes(String(auth.runner_label)) || job.runner_group_name !== auth.runner_group))) required.push(2133);
    // #2131 只接 query，逐动作发送的消费者尚未启用；不能从读授权推得发送。
    if (actions?.some(a => a !== "query")) required.push(1412);
    if (required.length) missing.set(group, required);
  }
  if (!auth) diag.add("AUTH_REQUIRED", "ticket:2133");
  return missing;
}

export function runRecords(s: At18Repository, F: string, own: Own, b: Bindings, contract: Adapter | undefined,
  registrySha: string | undefined, jobs: JobEvidence, passed: Set<string>, missing: Map<string, number[]>, diag: Diagnostics) {
  const byRecord = new Map<string, RecordEvidence[]>();
  if (!contract || !registrySha) return byRecord;
  const found = new Set<string>();
  const sealWorkflowsOK = new Map<number, boolean>();
  for (const i of [2, 3]) {
    try {
      const workflow = utf8(s.blob(F, workflows[i]));
      const seal = /^  seal:\s*\n([\s\S]*?)(?=^  [a-z_]+:\s*$|(?![\s\S]))/m.exec(workflow)?.[1] ?? "";
      sealWorkflowsOK.set(i, /^    needs: \[plan, seal_plan, checks, scaffold\]$/m.test(seal) &&
        seal.includes("needs.checks.result == 'success'") && seal.includes("matrix.group") &&
        seal.includes("needs.seal_plan.outputs.seals") && seal.includes("scripts/at18/workflow.py seal"));
    } catch { sealWorkflowsOK.set(i, false); }
  }
  for (const report of own.manifest.reports) {
    if (!("storage" in report) || !report.path.endsWith(".json")) continue;
    const bytes = own.registered.get(report.path)!;
    let raw: Row;
    try { raw = parseJsonObject(bytes); canonicalizeJcs(raw); }
    catch (e) { diag.add(derivationCode(e), "/acceptance_jobs"); continue; }
    if (raw.schema_version !== "at18-run-record/1" && !Object.hasOwn(raw, "record")) continue;
    const parsed = envelope.safeParse(raw);
    if (!parsed.success) { diag.add("RECORD_UNSEALED", "/acceptance_jobs"); continue; }
    const r = parsed.data;
    const name = slot(r.record, r.profile_id);
    const producer = b.producer.get(r.record + "@" + (r.profile_id ?? "none"));
    const i = producer?.evidence_class === "experiment" ? 3 : 2;
    const run = jobs.runs[i];
    const sealName = `at18-seal ${r.record} ${r.profile_id ?? "none"} ${registrySha} ${report.sha256}`;
    const seal = jobs.use(i, sealName);
    if (!producer || !run || !seal || !success(seal) || !sealWorkflowsOK.get(i) || !passed.has(producer.group) ||
        missing.has(producer.group) || r.check_id !== producer.check_id || r.head !== F ||
        r.run_id !== run.run.id || r.run_attempt !== run.run.run_attempt || found.has(sealName)) {
      diag.add("RECORD_UNSEALED", name); continue;
    }
    found.add(sealName);
    try {
      const decodedEnvelope = decodeFields(contract, contract.run_record_envelope, raw);
      if (canonicalizeJcs(decodedEnvelope) !== canonicalizeJcs(raw)) throw new Error("envelope projection");
      const data = decodeRecord(contract, r.record, r.payload);
      const info = byRecord.get(name) ?? [];
      info.push({ ref: extRef(own.manifest, report.path, bytes, "RUN_RECORD"), data, check: producer });
      byRecord.set(name, info);
    } catch { diag.add("RECORD_UNSEALED", name); }
  }
  for (const i of [2, 3]) {
    for (const job of jobs.runs[i]?.jobs ?? []) {
      if (!/^at18-seal [A-Za-z0-9_.-]+ [A-Za-z0-9_.-]+ [0-9a-f]{64} [0-9a-f]{64}$/.test(job.name)) continue;
      jobs.use(i, job.name);
      if (!found.has(job.name)) diag.add("RECORD_UNSEALED", jobScope(workflows[i], jobs.runs[i], job.name));
    }
  }
  for (const p of b.producer.values()) {
    const key = slot(p.record!, p.profile_id);
    if (!byRecord.has(key)) diag.add("RECORD_UNSEALED", key);
  }
  return byRecord;
}

const lower = (a: unknown) => typeof a === "string" ? a.toLowerCase() : undefined;
export function permission(records: RecordEvidence[], external: External[], adapter: Adapter | undefined, profile: string | null,
  diag: Diagnostics, used: Set<External>): Permission {
  const result: Permission = { authorization_declaration: null, venue_permission_fact: null, runtime_verification: null, capability_hash: null };
  const base = "/destinations/4/permission_evidence/experiment/";
  const p: { record: External; data: Row }[] = [], c: typeof p = [];
  const tryRead = (role: "venue_profile" | "capability_record", into: typeof p, expected: string) => {
    const rule = adapter?.external_sources[role];
    if (!rule || !adapter) return;
    for (const record of external.filter(x => x.ref.ticket === rule.ticket)) {
      try {
        const decoded = decodeFields(adapter, rule.fields, record.json);
        into.push({ record, data: decoded });
      } catch { diag.add("SCHEMA", base + expected); }
    }
  };
  tryRead("venue_profile", p, "authorization_declaration");
  tryRead("capability_record", c, "capability_hash");
  const choose = (items: typeof p, identity: (r: Row) => unknown) => {
    if (!items.length || items.some(x => canonicalizeJcs(identity(x.data)) !== canonicalizeJcs(identity(items[0].data)) ||
        x.record.ref.sha256 !== items[0].record.ref.sha256)) return undefined;
    return items.sort((a, b) => compare(a.record.ref.path, b.record.ref.path))[0];
  };
  const profileRec = choose(p.filter(x => x.data.profile_id === profile && x.data.evidence_class === "experiment"), x => [x.profile_id, x.version]);
  const capability = choose(c, x => x.capability_record_version);
  const authorized = profileRec && profileRec.data.credential_class === "trade_no_transfer" &&
    lower(profileRec.data.account) === lower(profileRec.data.authorizer) &&
    Array.isArray(profileRec.data.allowed_actions) && profileRec.data.allowed_actions.includes("query") &&
    typeof profileRec.data.authorization_id === "string";
  if (authorized && profileRec) { result.authorization_declaration = profileRec.record.ref; used.add(profileRec.record); }
  if (capability) {
    result.venue_permission_fact = { source_url: String(capability.data.source_url), retrieved_at: displayTime(capability.data.retrieved_at)!,
      sha256: digest.parse(capability.data.sha256) };
    used.add(capability.record);
  }
  if (profileRec && capability) {
    result.capability_hash = { capability_record_version: String(capability.data.capability_record_version),
      capability_record_sha256: capability.record.ref.sha256, venue_profile_sha256: profileRec.record.ref.sha256 };
    used.add(profileRec.record);
  }
  const matched = records.filter(({ data: d }) => profileRec && capability && authorized &&
    d.binding_profile_id === profile && d.binding_profile_version === profileRec.data.version && d.binding_evidence_class === "experiment" &&
    d.binding_authorization_id === profileRec.data.authorization_id &&
    d.binding_venue_profile_sha256 === profileRec.record.ref.sha256 && d.venue_profile_sha256 === profileRec.record.ref.sha256 &&
    d.binding_capability_record_version === capability.data.capability_record_version &&
    d.binding_capability_record_sha256 === capability.record.ref.sha256 && d.capability_record_sha256 === capability.record.ref.sha256 &&
    d.binding_writer_epoch === d.launch_writer_epoch &&
    d.binding_tb09_fingerprint === d.launch_tb09_fingerprint_computed &&
    d.launch_credential_public_id_verified === true && d.launch_session_permission_verified === true &&
    lower(d.derived_credential_public_id) === lower(profileRec.data.public_id) && lower(d.queried_public_id) === lower(profileRec.data.public_id) &&
    d.role === "agent" && lower(d.role_user) === lower(profileRec.data.account) &&
    utcBefore(profileRec.data.authorized_at, d.launch_launched_at) && (d.query_received_at === d.launch_launched_at ||
      utcBefore(d.query_received_at, d.launch_launched_at)) &&
    ["can_send", "allowed", "enabled"].includes(String(d.launch_send_state)) &&
    d.launch_send_refusal_class === null && d.launch_send_refusal_detail === null);
  if (matched.length && matched.length === records.length &&
      matched.every(x => ["binding_writer_epoch", "launch_launch_seq", "launch_launched_at", "query_received_at", "launch_send_state"]
        .every(key => x.data[key] === matched[0].data[key]))) result.runtime_verification = refs(matched.map(r => r.ref))[0];
  for (const [field, v] of Object.entries(result)) if (v === null) diag.add("SPECIAL_GATE", base + field);
  return result;
}
function normalizedDecimal(value: unknown) {
  const d = String(value);
  return d.includes(".") ? d.replace(/0+$/, "").replace(/\.$/, "").replace(/^-0$/, "0") : d.replace(/^-0$/, "0");
}
function chronologicalJournals(rowsByPart: Row[][]): Row[] {
  const items = new Map<number, Row>();
  for (const row of rowsByPart.flat()) {
    const seq = integer.parse(row.sequence);
    const old = items.get(seq);
    if (old && canonicalizeJcs(old) !== canonicalizeJcs(row)) throw new Error("conflicting journal");
    items.set(seq, row);
  }
  return [...items].sort(([a], [b]) => a - b).map(([, r]) => r);
}
export function migration(records: RecordEvidence[], profile: string | null, diag: Diagnostics): Migration {
  const result: Migration = { no_lost_rights: false, no_duplicated_capital: false,
    no_dual_write: false, no_resend: false, non_empty_evidence_refs: [] };
  const scope = slot("migration.experiment", profile);
  try {
    if (!records.length || records.some(({ data }) => data.profile_id !== profile || data.evidence_class !== "experiment")) throw new Error("identity");
    const [first] = records;
    // 多文件只能补同一迁移的独立日志；快照、身份映射和中断时序必须互证。
    const common = ["identity_map", "old_before", "new_after", "after_recovery", "after_rollback", "interruption"];
    if (records.some(({ data }) => common.some(k => canonicalizeJcs(data[k]) !== canonicalizeJcs(first.data[k])))) throw new Error("mixed migrations");
    const old = object(first.data.old_before);
    const after = object(first.data.new_after);
    const recovered = object(first.data.after_recovery);
    const rollback = object(first.data.after_rollback);
    const stage = object(first.data.interruption);
    const snapshots = [old, after, recovered, rollback];
    const fields = ["positions", "open_orders", "fee_tail"];
    if (fields.some(f => !rows(old[f]).length) || !rows(old.capital).length ||
        !utcBefore(stage.interrupted_at, stage.recovered_at) ||
        Number(old.owner_epoch) >= Number(after.owner_epoch) || after.owner_epoch !== recovered.owner_epoch ||
        Number(rollback.owner_epoch) < Number(after.owner_epoch)) throw new Error("nonempty run");
    const mapping = rows(first.data.identity_map);
    const changes = new Map(mapping.map(m => [String(m.old_id), String(m.new_id)]));
    if (changes.size !== mapping.length || new Set(changes.values()).size !== changes.size || !changes.size) throw new Error("mapping");
    const evidenceJournal = (field: string) => chronologicalJournals(records.map(r => rows(r.data[field])));
    const owner = evidenceJournal("ownership_journal");
    const capital = evidenceJournal("capital_journal");
    const written = evidenceJournal("writer_journal");
    const sent = evidenceJournal("send_journal");
    const stable = (xs: Row[], id: (x: Row) => string) => sorted(xs.map(x =>
      canonicalizeJcs([id(x), x.account, x.asset, normalizedDecimal(x.quantity)])));
    const snapshotOK = fields.every(field => {
      const original = rows(old[field]);
      if (!unique(original.map(x => x.id))) return false;
      return original.every(x => changes.has(String(x.id))) && snapshots.slice(1).every(r => {
        const entries = rows(r[field]);
        return unique(entries.map(x => x.id)) &&
          stable(original, x => changes.get(String(x.id))!).join("\0") === stable(entries, x => String(x.id)).join("\0");
      });
    });
    result.no_lost_rights = snapshotOK && owner.length > 0 &&
      [...changes.values()].every(id => owner.some(e => e.id === id && e.writer_epoch === after.owner_epoch &&
        snapshots.slice(1).every(s => fields.flatMap(f => rows(s[f])).filter(x => x.id === id).every(x => x.owner === e.owner))));
    const capOld = stable(rows(old.capital), x => changes.get(String(x.id)) ?? String(x.id)).join("\0");
    result.no_duplicated_capital = capital.length > 0 && unique(capital.map(e => e.id)) &&
      snapshots.slice(1).every(s => unique(rows(s.capital).map(e => e.id)) &&
        stable(rows(s.capital), x => String(x.id)).join("\0") === capOld) &&
      capital.every(c => rows(after.capital).some(x => x.id === c.id && x.asset === c.asset && x.account === c.account &&
        normalizedDecimal(x.quantity) === normalizedDecimal(c.quantity)));
    let active: { epoch: number; writer: unknown } | undefined;
    let lastEpoch = Number(old.owner_epoch);
    let released = false;
    let wroteNew = false;
    let rejected = false;
    for (const w of written) {
      const epoch = integer.parse(w.writer_epoch);
      if (epoch < lastEpoch) { rejected = true; break; }
      if (!active && !released && epoch === old.owner_epoch) active = { epoch, writer: w.writer_id };
      if (w.operation === "acquire" && !active && released && epoch > lastEpoch) {
        active = { epoch, writer: w.writer_id };
      } else if (!active || active.epoch !== epoch || active.writer !== w.writer_id ||
          !["acquire", "write", "release"].includes(String(w.operation)) ||
          (w.operation === "acquire" && epoch !== old.owner_epoch)) {
        rejected = true; break;
      }
      if (w.operation === "release") {
        released ||= epoch === old.owner_epoch;
        active = undefined;
      }
      if (w.operation === "write" && epoch === after.owner_epoch && released) wroteNew = true;
      lastEpoch = epoch;
    }
    result.no_dual_write = !rejected && wroteNew;
    const dispatched = new Set<unknown>();
    const known = new Set<unknown>();
    result.no_resend = sent.length > 0 && sent.every(e => {
      if (e.operation === "observation" || e.operation === "reconcile") return true;
      if (e.operation === "may_have_called" || e.operation === "MayHaveCalled") { known.add(e.command_id); return true; }
      if (e.operation !== "send" || known.has(e.command_id) || dispatched.has(e.command_id) ||
          Number(e.writer_epoch) < Number(after.owner_epoch)) return false;
      dispatched.add(e.command_id);
      return true;
    }) && known.size > 0;
    result.non_empty_evidence_refs = refs(records.map(r => r.ref));
  } catch { /* 分槽保留已证值；未能取证的判据仍留红。 */ }
  for (const k of ["no_lost_rights", "no_duplicated_capital", "no_dual_write", "no_resend"] as const) {
    if (!result[k]) diag.add("SPECIAL_GATE", "/migration_invariants/experiment/" + k, result.non_empty_evidence_refs[0]);
  }
  if (!result.non_empty_evidence_refs.length) diag.add("SPECIAL_GATE", scope);
  return result;
}
function displayTime(value: unknown) {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value))) return null;
  return new Date(value).toISOString();
}
export function postGate(records: RecordEvidence[], external: External[], adapter: Adapter | undefined,
  profile: string | null, diag: Diagnostics, used: Set<External>) {
  const result: PostGate = { status: "UNKNOWN", gate_reached_event: null, parameter_version: null, first_activation: null,
    gate_reached_known_at: null, version_authorized_at: null, first_activation_known_at: null, non_activation_evidence: [] };
  const scope = slot("post_gate.experiment", profile);
  let valid = false;
  try {
    if (!records.length || records.some(r => r.data.profile_id !== profile || r.data.evidence_class !== "experiment")) throw new Error("profile");
    const observed = records.map(r => r.data.growth_enabled === true || r.data.post_gate_params_effective === true ? "TRIGGERED_AND_ENABLED" :
      r.data.growth_eligible === true ? r.data.parameter_version_id ? "TRIGGERED_VERSION_AUTHORIZED" : "TRIGGERED_AWAITING_POLICY" :
      "NOT_TRIGGERED");
    result.status = observed.includes("TRIGGERED_AND_ENABLED") ? "TRIGGERED_AND_ENABLED" :
      new Set(observed).size === 1 ? observed[0] : "UNKNOWN";
    const single = (field: string, type: string) => {
      const candidates = records.flatMap(r => rows(r.data[field]).map(data => ({ data, ref: r.ref })));
      const real = candidates.filter(v => v.data.type === type && v.data.profile_id === profile && v.data.evidence_class === "experiment");
      return real.length && real.every(v => canonicalizeJcs(v.data) === canonicalizeJcs(real[0].data)) ?
        real.find(v => v.ref === refs(real.map(v => v.ref))[0]) ?? real[0] : undefined;
    };
    const gate = single("gate_events", "GateReachedEvent");
    const activation = single("first_activations", "FirstActivation");
    if (gate) {
      result.gate_reached_event = gate.ref;
      result.gate_reached_known_at = displayTime(gate.data.known_at);
    }
    if (activation) {
      result.first_activation = activation.ref;
      result.first_activation_known_at = displayTime(activation.data.known_at);
    }
    const ids = new Set(records.map(r => r.data.parameter_version_id).filter(x => x !== null));
    let signed: { source: External; data: Row } | undefined;
    const rule = adapter?.external_sources.post_gate_parameter_version;
    if (rule && adapter && ids.size === 1) {
      const candidates: typeof signed[] = [];
      for (const source of external.filter(x => x.json.parameter_version_id === [...ids][0] &&
        (rule.ticket === null || x.ref.ticket === rule.ticket))) {
        try {
          const data = decodeFields(adapter, rule.fields, source.json);
          if (data.profile_id === profile && data.evidence_class === "experiment" &&
              typeof data.authorizer === "string" && gate && data.gate_event_id === gate.data.event_id) candidates.push({ source, data });
        } catch { diag.add("SCHEMA", "/post_gate_records/experiment/parameter_version"); }
      }
      const first = candidates[0];
      if (first && candidates.every(x => x?.source.ref.sha256 === first.source.ref.sha256)) signed = first;
    }
    if (signed) {
      used.add(signed.source);
      result.parameter_version = signed.source.ref;
      result.version_authorized_at = displayTime(signed.data.authorized_at);
    }
    const disjointSimulated = records.some(r => rows(r.data.gate_events).some(ev => ev.type !== "GateReachedEvent") &&
      r.data.growth_eligible === true && !rows(r.data.gate_events).some(ev => ev.type === "GateReachedEvent"));
    const nonActivation = !observed.includes("TRIGGERED_AND_ENABLED") && records.every(r => r.data.growth_enabled === false &&
      r.data.post_gate_params_effective === false);
    const common = new Set(observed).size === 1 && !disjointSimulated && ids.size <= 1;
    const correctGate = !!gate && records.every(r => r.data.growth_eligible === true);
    const ordered = correctGate && signed && utcBefore(gate.data.known_at, signed.data.authorized_at);
    if (result.status === "TRIGGERED_AND_ENABLED") valid = !!(common && ordered && activation &&
        activation.data.gate_event_id === gate?.data.event_id && activation.data.parameter_version_id === signed?.data.parameter_version_id &&
        utcBefore(signed?.data.authorized_at, activation.data.known_at));
    else if (result.status === "TRIGGERED_VERSION_AUTHORIZED") valid = !!(common && nonActivation && ordered && !activation);
    else if (result.status === "TRIGGERED_AWAITING_POLICY") valid = common && nonActivation && correctGate && ids.size === 0 && !activation &&
        records.every(r => rows(r.data.outputs).some(o => o.type === "AwaitingPolicy" && o.dependency === "post_gate_params"));
    else if (result.status === "NOT_TRIGGERED") valid = common && nonActivation && !gate && !activation && ids.size === 0;
    if (valid && nonActivation) result.non_activation_evidence = refs(records.map(r => r.ref));
  } catch { /* 输出实际可辨的阶段，不从记录缺失倒推未启用。 */ }
  if (!valid) {
    diag.add("SPECIAL_GATE", scope, refs(records.map(r => r.ref))[0]);
    if (result.status === "TRIGGERED_AND_ENABLED" || result.status === "TRIGGERED_VERSION_AUTHORIZED") {
      const fields: ("gate_reached_event" | "parameter_version" | "first_activation")[] = ["gate_reached_event", "parameter_version"];
      if (result.status === "TRIGGERED_AND_ENABLED") fields.push("first_activation");
      for (const field of fields) {
        if (result[field] === null) diag.add("SPECIAL_GATE", "/post_gate_records/experiment/" + field);
      }
    }
  }
  return { result, valid };
}
export function validateTbEntities(record: string, profile: string | null, records: RecordEvidence[], b: Bindings, diag: Diagnostics) {
  const scope = slot(record, profile);
  const [, evidenceClass, slice] = record.split(".");
  const valid: { ref: ArtifactRef; checkId: string; keys: Set<string> }[] = [];
  const seen = new Set<string>();
  const expected = new Set<string>();
  for (const bindings of b.activeByCheck.values()) for (const { key, basis } of bindings.values()) {
    if (key.slice !== slice || !(b.keyDomains.get(key.id) ?? []).some(d => basisId(d.basis) === basisId(basis) &&
        d.domain.evidence_class === evidenceClass && d.domain.profile_id === profile && d.domain.result !== "BOUNDED_DEFERRED")) continue;
    expected.add(keyBasis(key.id, basis));
  }
  for (const { data, ref, check } of records) {
    try {
      if (data.tb_id !== slice || data.evidence_class !== evidenceClass || data.profile_id !== profile) throw new Error("identity");
      const tests = rows(data.tests);
      const names = tests.map(t => t.name);
      if (tests.length !== check.expected_count || !unique(names) || tests.some(t => {
        if (t.check_id !== check.check_id || t.source_path !== check.source.path || typeof t.name !== "string") return true;
        if (check.runner === "pytest") return !t.name.startsWith(check.source.path + "::" + check.selector) ||
          !["", "["].includes(t.name.slice((check.source.path + "::" + check.selector).length).charAt(0));
        if (check.runner === "cargo-test") return t.name !== check.selector.split("/").at(-1);
        return t.name !== check.selector;
      })) throw new Error("tests");
      const ownKeys = b.activeByCheck.get(check.check_id) ?? new Map();
      const keys = rows(data.keys).map(k => keyBasis(keyId(String(k.slice_id), String(k.kind), String(k.id)),
        { path: String(k.basis_path), pointer: String(k.basis_pointer) }));
      if (!keys.length || !unique(keys) || keys.some(k => !expected.has(k) || !ownKeys.has(k))) throw new Error("keys");
      tbConditions.parse(data.conditions);
      tbOutput.parse(data.output);
      for (const k of keys) seen.add(k);
      valid.push({ ref, checkId: check.check_id, keys: new Set(keys) });
    } catch { diag.add("TB_REPORT", scope, ref); }
  }
  if (!expected.size || !valid.length || expected.size !== seen.size) { diag.add("TB_REPORT", scope); return []; }
  return valid;
}

export function entityRefs(...params: Parameters<typeof validateTbEntities>) {
  return refs(validateTbEntities(...params).map(e => e.ref));
}

export function proveDomain(d: KeyDomain, key: Key, b: Bindings, checkPass: Set<string>, executed: Set<string>, missing: Map<string, number[]>,
  records: Map<string, RecordEvidence[]>, entities: Map<string, ReturnType<typeof validateTbEntities>>, post: ReturnType<typeof postGate>, p2: boolean, gaps: Gaps, diag: Diagnostics) {
  const { domain, basis, checkIds } = d;
  const scope = keyDomain(keyBasis(key.id, basis), domain);
  const obligation = keyDomain(key.id, domain);
  if (domain.result === "BOUNDED_DEFERRED") {
    const gate = domain.deferred_gate;
    if ((gate === P2 || gate === PROD) && domain.evidence_class === "production" && p2) return true;
    if (gate === EXP && domain.evidence_class === "experiment" && post.valid && post.result.status !== "TRIGGERED_AND_ENABLED") return true;
    diag.add("DOMAIN_INVALID", scope);
    return false;
  }
  let ok = checkIds.length > 0;
  for (const id of checkIds) {
    const c = b.checks.get(id);
    if (!c) { gaps.notRun(obligation, domain.evidence_class, "SOURCE_UNAVAILABLE"); ok = false; continue; }
    const absent = missing.get(c.group);
    if (absent) {
      diag.add("AUTH_REQUIRED", obligation); gaps.notRun(obligation, domain.evidence_class, "AUTH_REQUIRED", ...absent);
      ok = false;
    } else if (!checkPass.has(c.group)) {
      if (!executed.has(c.group)) gaps.notRun(obligation, domain.evidence_class, "CHECK_NOT_RUN");
      diag.add(executed.has(c.group) ? "CHECK_JOB_FAILED" : "CHECK_JOB_MISSING", scope);
      ok = false;
    } else if (c.record) {
      const recordSlot = slot(c.record, c.profile_id);
      const valid = c.record.startsWith("tb.")
        ? entities.get(recordSlot)?.some(e => e.checkId === id && e.keys.has(keyBasis(key.id, basis)))
        : records.get(recordSlot)?.some(e => e.check.check_id === id);
      if (!valid) { diag.add("RECORD_UNSEALED", scope); ok = false; }
    }
  }
  return ok;
}
