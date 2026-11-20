import { createHash } from "node:crypto";
import { isAbsolute } from "node:path";
import { z } from "zod";
import { deliveryManifestSchema, type DeliveryManifest } from "./delivery-bundle.ts";

const repoSpec = ".chanlun/review-results/issue1339-r2-spec-20260909/payload/spec";
export const specPaths = {
  spec_ref: `${repoSpec}/SPEC.json`,
  crosswalk_ref: `${repoSpec}/IMPLEMENTATION-CROSSWALK.json`,
  coverage_input_ref: `${repoSpec}/inputs/SPEC-COVERAGE-INPUT.json`,
} as const;

export const tbTickets = {
  "TB-01": 1359, "TB-02": 1360, "TB-03": 1361, "TB-04": 1362, "TB-05": 1363,
  "TB-06": 1364, "TB-07": 1366, "TB-08": 1367, "TB-09": 1365, "TB-10": 1368, "TB-11": 1369,
} as const;
const tbIds = Object.keys(tbTickets) as (keyof typeof tbTickets)[];
const tbId = z.enum(tbIds);
export const legacyTickets = [942, 1096, 1282, 1304, 1319, 1320, 1279] as const;
const destinationIds = [1, 2, 3, 4, 5, 6] as const;
const deploymentClasses = ["experiment", "production"] as const;
const classSlot = <T extends z.ZodType>(schema: T) =>
  z.strictObject({ experiment: schema, production: schema });
const text = z.string().min(1);
const sha = z.string().regex(/^[0-9a-f]{40}$/);
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const utc = z.iso.datetime({ offset: false, local: false }).refine(value => /T\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(value));
const integer = z.int().positive();
const state = z.enum(["OPEN", "CLOSED"]);
const result = z.enum(["PASS", "FAIL"]);
const evidenceClass = z.enum(["simulation", "experiment", "production"]);
const cleanPath = (path: string) => !path.includes("\\") && !path.includes("\0") &&
  path.split("/").every(part => part !== "." && part !== "..");
const externalPath = text.refine(path => isAbsolute(path) && cleanPath(path));
const repoPath = text.refine(path => !isAbsolute(path) && cleanPath(path));

export const manifestRefSchema = z.strictObject({
  ticket: integer, base: sha, head: sha, manifest_path: externalPath, manifest_sha256: digest,
});
const artifactCommon = { sha256: digest, bounded_scope: text };
const inRepoArtifact = z.strictObject({ ...artifactCommon, storage: z.literal("in_repo"), path: repoPath,
  commit: sha, ticket: z.null(), base: z.null(), head: z.null() });
export const artifactRefSchema = z.discriminatedUnion("storage", [
  inRepoArtifact,
  z.strictObject({ ...artifactCommon, storage: z.literal("external"), path: externalPath,
    commit: z.null(), ticket: integer, base: sha, head: sha }),
]);
const refs = z.array(artifactRefSchema);
const evidenceByClass = z.strictObject({ simulation: refs, experiment: refs, production: refs.nullable() });
const capability = z.strictObject({
  capability_record_version: text, capability_record_sha256: digest, venue_profile_sha256: digest,
});
const venueFact = z.strictObject({ source_url: text, retrieved_at: text, sha256: digest });
const permission = z.strictObject({
  authorization_declaration: artifactRefSchema.nullable(), venue_permission_fact: venueFact.nullable(),
  runtime_verification: artifactRefSchema.nullable(), capability_hash: capability.nullable(),
});
const review = z.strictObject({
  reviewer: text, reviewed_head: sha, verdict: z.enum(["PASS", "BLOCK"]), artifact: artifactRefSchema,
});
const ciRun = z.strictObject({ workflow: text, run_id: integer, head_sha: sha, url: text,
  conclusion: z.enum(["SUCCESS", "FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "NEUTRAL", "SKIPPED", "STALE"]),
});
const ticketScope = z.strictObject({ ticket: integer, scope: text });
const downstream = z.strictObject({ ticket: integer, state });
const slice = downstream.extend({ main_sha: sha.nullable() });
const migration = z.strictObject({
  no_lost_rights: z.boolean(), no_duplicated_capital: z.boolean(), no_dual_write: z.boolean(), no_resend: z.boolean(),
  non_empty_evidence_refs: refs,
});
const postStatus = z.enum([
  "NOT_TRIGGERED", "TRIGGERED_AWAITING_POLICY", "TRIGGERED_VERSION_AUTHORIZED", "TRIGGERED_AND_ENABLED",
]);
const postGate = z.strictObject({
  status: postStatus, gate_reached_event: artifactRefSchema.nullable(), parameter_version: artifactRefSchema.nullable(),
  first_activation: artifactRefSchema.nullable(), gate_reached_known_at: utc.nullable(),
  version_authorized_at: utc.nullable(), first_activation_known_at: utc.nullable(), non_activation_evidence: refs,
});
const coverageGates = ["ISSUE_1561_P2_FIRST_SEND", "ADR_0036_POST_GATE_EXPERIMENT", "ADR_0036_POST_GATE_PRODUCTION"] as const;
const heavy = "ISSUE_1320_HEAVY_MEASUREMENT";
const coverage = { evidence_refs: refs, deferred_gates: z.array(text) };
const coverageEntry = <Shape extends z.ZodRawShape>(shape: Shape) => [
  z.strictObject({ ...shape, ...coverage, status: z.literal("VERIFIED") }),
  z.strictObject({ ...shape, ...coverage, status: z.literal("BOUNDED_DEFERRED") }),
  z.strictObject({ ...shape, ...coverage, status: z.literal("FAIL") }),
] as const;
const storyEntry = z.discriminatedUnion("status", coverageEntry({
  story_id: text, closure_slice_ids: z.array(text), destination_ids: z.array(text),
}));
const familyShape = { family: text, id: text, entry_mode: z.enum(["REQUIRED", "OUT_OF_SCOPE_PRESERVE"]) };
const familyEntry = z.discriminatedUnion("status", [
  ...coverageEntry(familyShape), z.strictObject({ ...familyShape, ...coverage, status: z.literal("PRESERVED_BOUNDARY") }),
]);
const detailEntry = z.discriminatedUnion("status", coverageEntry({ id: text, family_entry_id: text }));
const coverageLedger = z.strictObject({
  crosswalk_sha256: digest.nullable(), stories: z.array(storyEntry),
  families: z.array(familyEntry), details: z.array(detailEntry),
});
export const failedCheckSchema = z.strictObject({
  scope: text, check_id: text, detail: text, evidence_ref: artifactRefSchema.nullable(),
});
export type FailedCheck<Id extends string = string> =
  Omit<z.infer<typeof failedCheckSchema>, "check_id"> & { check_id: Id };
export type ArtifactRef = z.infer<typeof artifactRefSchema>;
export type ManifestRef = z.infer<typeof manifestRefSchema>;

const identity = { ticket: integer, base: sha, head: sha, generated_at: utc };
const bundleShape = z.strictObject({
  schema_version: z.literal("at18-input-bundle/1"), content_hash: digest, ...identity,
  spec_ref: inRepoArtifact, crosswalk_ref: inRepoArtifact, coverage_input_ref: inRepoArtifact,
  external_manifests: z.array(manifestRefSchema),
});
const destination = z.strictObject({
  id: integer, obligation: text, tickets: z.array(ticketScope), commits: z.array(sha),
  independent_reviews: z.array(review), main_sha: sha.nullable(), ci_runs: z.array(ciRun),
  evidence_by_class: evidenceByClass, permission_evidence: classSlot(permission.nullable()).nullable(),
  downstream_status: z.array(downstream), remaining_obligations: z.array(text), result,
});
const tbSummary = z.strictObject({
  tb_id: text, ticket: integer, slices: z.array(slice), input_bundle: artifactRefSchema.nullable(),
  evidence_by_class: evidenceByClass, final_reviews: z.array(review), main_sha: sha.nullable(),
  ci_runs: z.array(ciRun), entity_reports: refs, remaining_obligations: z.array(text), ticket_state: state,
  gate_satisfied: z.boolean(),
});
const legacy = z.strictObject({
  ticket: integer, disposition: text, evidence_refs: refs, ticket_state: state,
  remaining_obligations: z.array(text), disposition_valid: z.boolean(),
});
const unexecuted = z.strictObject({
  obligation: text, reason: text, blocker_or_gap: text, evidence_class: evidenceClass, required: z.boolean(),
});
const permissionBlocked = z.strictObject({
  obligation: text, missing_authorization: text, blocker_ticket: integer, evidence_class: evidenceClass,
});
const reportFields = {
  schema_version: z.literal("at18-report/1"), content_hash: digest, ...identity,
  capability_hash: classSlot(capability.nullable()),
  destinations: z.array(destination).length(6),
  tb_summaries: z.array(tbSummary).length(11),
  spec_coverage: coverageLedger,
  migration_invariants: classSlot(migration.nullable()),
  post_gate_records: classSlot(postGate.nullable()),
  legacy_dispositions: z.array(legacy).length(7),
  unexecuted: z.array(unexecuted), permission_blocked: z.array(permissionBlocked), bounded_domain_statement: text,
};
const reportShape = z.discriminatedUnion("overall_result", [
  z.strictObject({ ...reportFields, overall_result: z.literal("PASS"), failed_checks: z.tuple([]) }),
  z.strictObject({ ...reportFields, overall_result: z.literal("FAIL"), failed_checks: z.tuple([failedCheckSchema]).rest(failedCheckSchema) }),
]);
export type At18InputBundle = z.infer<typeof bundleShape>;
export type At18Report = z.infer<typeof reportShape>;

// 采集边界不是第三份交付文档。只接收观察值和实体凭据，不接收报告判定字段。
const proof = z.strictObject({ outcome: z.enum(["CONFIRMED", "REJECTED"]), evidence_refs: refs });
const collected = {
  main_sha: sha.nullable().optional(), ci_runs: z.array(ciRun).optional(),
  evidence_by_class: evidenceByClass.partial().optional(), remaining_obligations: z.array(text).optional(),
};
const venueObservation = z.strictObject({
  authorization_declaration: artifactRefSchema.optional(), runtime_verification: artifactRefSchema.optional(),
  capability_record: artifactRefSchema.optional(), venue_profile: artifactRefSchema.optional(),
  venue_permission_source: artifactRefSchema.optional(), venue_permission_document: artifactRefSchema.optional(),
});
const postObservation = z.strictObject({
  status: postStatus, gate_reached_event: artifactRefSchema.optional(), parameter_version: artifactRefSchema.optional(),
  first_activation: artifactRefSchema.optional(), non_activation: proof.optional(),
});
const migrationKeys = ["no_lost_rights", "no_duplicated_capital", "no_dual_write", "no_resend"] as const;
const migrationObservation = z.strictObject({
  no_lost_rights: z.boolean(), no_duplicated_capital: z.boolean(), no_dual_write: z.boolean(), no_resend: z.boolean(),
  non_empty_run: proof,
});
const coverageObservation = z.strictObject({
  kind: z.enum(["story", "family", "detail"]), id: text, slices: z.array(z.strictObject({ tb_id: tbId, proof })),
  deferred_gates: z.array(z.strictObject({ gate: z.enum(coverageGates), boundary: proof })).optional(),
});
export const observationsSchema = z.strictObject({
  production_enabled: z.boolean(), bounded_domain_statement: text,
  destinations: z.array(z.strictObject({
    id: integer, ...collected, tickets: z.array(ticketScope).optional(), commits: z.array(sha).optional(),
    independent_reviews: z.array(review).optional(), downstream_status: z.array(downstream).optional(),
    obligations: proof.optional(),
  })).optional(),
  tb_summaries: z.array(z.strictObject({
    tb_id: tbId, ticket_state: state, expected_slice_tickets: z.array(integer).optional(), slices: z.array(slice).optional(),
    ...collected, final_reviews: z.array(review).optional(), entity_reports: refs.optional(), obligations: proof.optional(),
  })),
  legacy_dispositions: z.array(z.strictObject({
    ticket: integer, disposition: text, ticket_state: state, remaining_obligations: z.array(text).optional(),
    disposition_proof: proof.optional(), own_remaining_only: proof.optional(), not_released: proof.optional(),
    heavy_resolved: proof.optional(),
  })),
  external_manifests: z.array(externalPath).optional(),
  coverage: z.array(coverageObservation).optional(),
  permission: classSlot(venueObservation.optional()).optional(),
  migration: classSlot(migrationObservation.optional()).optional(),
  post_gate: classSlot(postObservation.optional()).optional(),
  unexecuted: z.array(unexecuted).optional(),
  permission_blocked: z.array(permissionBlocked).optional(),
});
export type At18Observations = z.infer<typeof observationsSchema>;

export interface At18Source {
  readExternal(path: string): Buffer;
  readBlob(commit: string, path: string): Buffer;
  isAncestor(commit: string, head: string): boolean;
  /** 采集端只能依据已合入 main、head 完全相同的 GitHub 记录返回合并 SHA。 */
  mergedMainCommit?(head: string): string | undefined;
}

const crosswalkFields = z.object({
  rows: z.array(z.object({ story_id: text, success_closure_slice_ids: z.array(tbId), destination_ids: z.array(text) })),
  family_entry_links: z.array(z.object({
    family: text, id: text, success_closure_slice_ids: z.array(tbId), exclusion_boundary: z.boolean().optional(),
    source_json_pointer: text,
  })),
  detailed_acceptance_links: z.array(z.object({ id: text, family_entry_id: text, success_closure_slice_ids: z.array(tbId) })),
});
const coverageInputFields = z.object({
  destinations: z.array(z.object({ ordinal: integer, id: text, verbatim: text })),
});
const specDestinationFields = z.object({ stories: z.array(z.object({ id: text, need: text })) });
const oldEntryField = z.object({ id: text, effective_disposition: z.object({ kind: text }) });
type Crosswalk = z.infer<typeof crosswalkFields>;
type ObservedProof = z.infer<typeof proof>;

// §五：首先读原字节；只有读到且需要结构化字段时才进入后续步骤。
type DerivedStep = "FILE_READ" | "JSON_PARSE" | "JCS_CANONICALIZE" | "SCHEMA";
export class At18DerivationError extends Error {
  constructor(readonly check_id: DerivedStep, detail: string) { super(detail); }
}

export class At18BootstrapError extends Error {
  constructor(readonly code: "MANIFEST_UNREADABLE" | "INVALID_MANIFEST" | "FIXED_ITEM_UNAVAILABLE" |
    "CONTENT_NOT_CANONICAL" | "OUTPUT_WRITE_FAILED", detail: string) { super(detail); }
}

export const byteSha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

export function parseJsonObject(bytes: Uint8Array): Record<string, unknown> {
  let source: string;
  let value: unknown;
  try {
    source = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new At18DerivationError("JSON_PARSE", "文件不是合法 UTF-8。");
  }
  try { value = JSON.parse(source); }
  catch { throw new At18DerivationError("JSON_PARSE", "文件不符合 JSON 语法。"); }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new At18DerivationError("JSON_PARSE", "JSON 顶层须为对象。");
  }
  // 语法由 JSON.parse 核验；扫描原 token，以免重复键（包括转义后同名）被覆盖。
  const stack: (Set<string> | null)[] = [];
  for (const [token] of source.matchAll(/"(?:[^"\\]|\\.)*"[\x20\t\r\n]*:?|[{}\[\]]/gs)) {
    if (token === "{") stack.push(new Set());
    else if (token === "[") stack.push(null);
    else if (token === "}" || token === "]") stack.pop();
    else if (token.endsWith(":")) {
      const name: string = JSON.parse(token.slice(0, -1));
      const keys = stack.at(-1)!;
      if (keys.has(name)) throw new At18DerivationError("JSON_PARSE", "JSON 含重复键。");
      keys.add(name);
    }
  }
  return value as Record<string, unknown>;
}

export function canonicalizeJcs(value: unknown): string {
  const bad = (detail: string): never => { throw new At18DerivationError("JCS_CANONICALIZE", detail); };
  const string = (value: string) => {
    if (/[\uD800-\uDFFF]/u.test(value)) bad("JSON 字符串或键含孤立代理码点。");
    return JSON.stringify(value);
  };
  const active = new Set<object>();
  const encode = (item: unknown): string => {
    if (item === null || typeof item === "boolean") return String(item);
    if (typeof item === "string") return string(item);
    if (typeof item === "number") {
      if (!Number.isFinite(item)) bad("JSON 数值不能表示为有限的 IEEE 754 双精度数。");
      return JSON.stringify(item);
    }
    if (typeof item !== "object" || item === null) return bad("值不是 JSON 数据。");
    if (active.has(item)) return bad("JSON 对象存在循环引用。");
    active.add(item);
    try {
      if (Array.isArray(item)) return `[${Array.from(item, encode).join(",")}]`;
      if (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null) {
        return bad("值不是 JSON 对象。");
      }
      const object = item as Record<string, unknown>;
      return `{${Object.keys(object).sort().map(key => `${string(key)}:${encode(object[key])}`).join(",")}}`;
    } finally { active.delete(item); }
  };
  return encode(value);
}

export function computeContentHash({ content_hash: _self, ...body }: Record<string, unknown>): string {
  return byteSha256(Buffer.from(canonicalizeJcs(body), "utf8"));
}

function hashMatches(value: { content_hash: string }, ctx: z.RefinementCtx) {
  try {
    if (computeContentHash(value as Record<string, unknown>) === value.content_hash) return;
  } catch (error) {
    ctx.addIssue({ code: "custom", path: ["content_hash"], message: String(error) });
    return;
  }
  ctx.addIssue({ code: "custom", path: ["content_hash"], message: "content_hash 与规范化内容不符。" });
}

export const at18InputBundleSchema = bundleShape.superRefine(hashMatches);
export const at18ReportSchema = reportShape.superRefine((report, ctx) => {
  const wrong = (field: string) => ctx.addIssue({ code: "custom", path: [field], message: "固定项顺序或槽位编码不符。" });
  if (report.destinations.some((d, i) => d.id !== destinationIds[i] || (d.id === 5) !== (d.permission_evidence !== null))) wrong("destinations");
  if (report.tb_summaries.some((tb, i) => tb.tb_id !== tbIds[i] || tb.ticket !== tbTickets[tbIds[i]] ||
    (i === 10 ? tb.entity_reports.length !== 0 : tb.input_bundle !== null))) wrong("tb_summaries");
  if (report.legacy_dispositions.some((l, i) => l.ticket !== legacyTickets[i])) wrong("legacy_dispositions");
  const enabled = report.migration_invariants.production !== null;
  const permissionSlots = report.destinations[4]?.permission_evidence;
  if (report.migration_invariants.experiment === null || report.post_gate_records.experiment === null ||
    !permissionSlots?.experiment || (permissionSlots.production !== null) !== enabled ||
    (report.post_gate_records.production !== null) !== enabled ||
    (!enabled && report.capability_hash.production !== null) ||
    [...report.destinations, ...report.tb_summaries].some(r => (r.evidence_by_class.production !== null) !== enabled) ||
    report.tb_summaries.slice(-1).some(tb => Object.values(tb.evidence_by_class).some(refs => refs?.length))) wrong("post_gate_records");
  hashMatches(report, ctx);
});

function schemaValue<T>(value: unknown, schema: z.ZodType<T>): T {
  const parsed = schema.safeParse(value);
  if (!parsed.success) throw new At18DerivationError("SCHEMA", parsed.error.issues.map(
    issue => `${issue.path.join(".") || "$"}: ${issue.message}`,
  ).join("；"));
  return parsed.data;
}

export function deriveBytes(read: () => Buffer): Buffer {
  try { return read(); }
  catch { throw new At18DerivationError("FILE_READ", "文件或指定提交的 Git blob 不可读。"); }
}

export function deriveJson<T>(bytes: Buffer, schema: z.ZodType<T>, canonicalize = true): T {
  const parsed = parseJsonObject(bytes);
  if (canonicalize) canonicalizeJcs(parsed);
  const value = schemaValue(parsed, schema);
  if (!canonicalize) canonicalizeJcs(value);
  return value;
}

export function readOwnManifest(source: At18Source, path: string): DeliveryManifest {
  if (!externalPath.safeParse(path).success) throw new At18BootstrapError("INVALID_MANIFEST", "自身 manifest 须使用仓外绝对路径。");
  try {
    const manifest = deriveJson(deriveBytes(() => source.readExternal(path)), deliveryManifestSchema);
    if (manifest.ticket !== 1391) throw new At18DerivationError("SCHEMA", "自身 manifest.ticket 须为 1391。");
    return manifest;
  } catch (error) {
    if (!(error instanceof At18DerivationError)) throw error;
    throw new At18BootstrapError(error.check_id === "FILE_READ" ? "MANIFEST_UNREADABLE" : "INVALID_MANIFEST", error.message);
  }
}

const encodeDocument = (document: object) => Buffer.from(`${JSON.stringify(document, null, 2)}\n`, "utf8");

interface GenerateArgs {
  manifest: DeliveryManifest;
  observations: At18Observations;
  source: At18Source;
  originMain: string | null;
  generatedAt: string;
  inputBundlePath: string;
}

export function generateAt18({ manifest, observations: obs, source, originMain, generatedAt, inputBundlePath }: GenerateArgs) {
  const { ticket, base, head } = manifest;
  const identity = { ticket, base, head, generated_at: generatedAt };
  const failures: FailedCheck[] = [];
  const fail = (scope: string, check_id: string, detail: string, evidence_ref: ArtifactRef | null = null) =>
    { failures.push({ scope, check_id, detail, evidence_ref }); };
  const expect = (condition: unknown, scope: string, check: string, detail: string) => {
    if (!condition) fail(scope, check, detail);
  };
  const derive = <T>(scope: string, work: () => T, ref: ArtifactRef | null = null): T | null => {
    try { return work(); }
    catch (error) {
      if (!(error instanceof At18DerivationError)) throw error;
      fail(scope, error.check_id, error.message, ref);
      return null;
    }
  };
  const blob = (commit: string, path: string) => deriveBytes(() => source.readBlob(commit, path));
  const external = (path: string) => deriveBytes(() => source.readExternal(path));
  const integrated = (commit: string) => {
    if (source.isAncestor(commit, head)) return true;
    const merge = source.mergedMainCommit?.(commit);
    return merge !== undefined && source.isAncestor(merge, head);
  };
  const matchesMerged = (commit: string, merged: string) =>
    commit === merged || source.mergedMainCommit?.(commit) === merged;
  expect(head === originMain, "report", "ORIGIN_MAIN_HEAD", "自身 manifest.head 不是对账时的 origin/main。");

  const upstream = new Map<string, { manifest: DeliveryManifest; ref: ManifestRef }>();
  for (const manifest_path of obs.external_manifests ?? []) {
    const loaded = derive(`external_manifests:${manifest_path}`, () => {
      const bytes = external(manifest_path);
      return { manifest: deriveJson(bytes, deliveryManifestSchema), manifest_sha256: byteSha256(bytes) };
    });
    if (!loaded) continue;
    const { ticket, base, head } = loaded.manifest;
    const key = `${ticket}/${base}/${head}`;
    if (upstream.has(key)) {
      fail("input_bundle", "DUPLICATE_UPSTREAM_MANIFEST", `重复的上游 manifest 绑定：#${ticket}。`);
      continue;
    }
    upstream.set(key, { manifest: loaded.manifest,
      ref: { ticket, base, head, manifest_path, manifest_sha256: loaded.manifest_sha256 } });
  }

  const artifactBytes = new Map<string, Buffer>();
  function checkedRef(scope: string, field: string, ref?: ArtifactRef | null): ArtifactRef | null {
    if (!ref) return null;
    const owner = ref.storage === "in_repo" ? ref.commit : `${ref.ticket}/${ref.base}/${ref.head}`;
    const key = canonicalizeJcs([ref.storage, owner, ref.path, ref.sha256]);
    let bytes = artifactBytes.get(key);
    if (bytes) return ref;
    if (ref.storage === "external") {
      const manifest = upstream.get(owner)?.manifest;
      const root = manifest?.externalReportsRoot;
      const prefix = root?.replace(/\/+$/, "") + "/";
      const declared = manifest?.reports.filter(item => "storage" in item && item.path === ref.path &&
        item.ticket === ref.ticket && item.base === ref.base && item.head === ref.head && item.sha256 === ref.sha256);
      if (!root || !externalPath.safeParse(root).success || !ref.path.startsWith(prefix) || declared?.length !== 1 ||
          manifest?.reports.filter(item => item.path === ref.path).length !== 1) {
        fail(scope, "ARTIFACT_MANIFEST_BINDING", `${field} 未唯一命中对应的上游仓外 manifest。`, ref);
        return null;
      }
      if (!integrated(ref.head)) {
        fail(scope, "ARTIFACT_ANCESTRY", `${field} 的交付 head 未证实进入 main。`, ref);
        return null;
      }
    } else if (!source.isAncestor(ref.commit, head)) {
      fail(scope, "ARTIFACT_ANCESTRY", `${field} 的仓内 commit 不在审定 head 的祖先链。`, ref);
      return null;
    }
    bytes = derive(scope, () => ref.storage === "in_repo" ? blob(ref.commit, ref.path) : external(ref.path), ref) ?? undefined;
    if (!bytes) return null;
    if (byteSha256(bytes) !== ref.sha256) {
      fail(scope, "ARTIFACT_HASH_MISMATCH", `${field} 与登记的文件字节摘要不符。`, ref);
      return null;
    }
    artifactBytes.set(key, bytes);
    return ref;
  }

  const checkedRefs = (scope: string, field: string, values: ArtifactRef[] = []) =>
    values.flatMap(ref => checkedRef(scope, field, ref) ?? []);
  const fromArtifact = <T>(scope: string, field: string, ref: ArtifactRef | undefined, schema: z.ZodType<T>) => {
    if (!checkedRef(scope, field, ref) || !ref) return null;
    const owner = ref.storage === "in_repo" ? ref.commit : `${ref.ticket}/${ref.base}/${ref.head}`;
    const bytes = artifactBytes.get(canonicalizeJcs([ref.storage, owner, ref.path, ref.sha256]))!;
    return derive(scope, () => deriveJson(bytes, schema, false), ref);
  };
  function proved(scope: string, check: string, detail: string, observed?: ObservedProof) {
    const evidence = checkedRefs(scope, check, observed?.evidence_refs);
    if (observed?.outcome === "CONFIRMED" && evidence.length) return evidence;
    fail(scope, check, detail, evidence[0]);
    return [];
  }

  const specBytes = {
    spec_ref: derive("input_bundle.spec_ref", () => blob(head, specPaths.spec_ref)),
    crosswalk_ref: derive("input_bundle.crosswalk_ref", () => blob(head, specPaths.crosswalk_ref)),
    coverage_input_ref: derive("input_bundle.coverage_input_ref", () => blob(head, specPaths.coverage_input_ref)),
  };
  const specRef = (key: keyof typeof specPaths): ArtifactRef | null => {
    const bytes = specBytes[key];
    return bytes && {
      storage: "in_repo", path: specPaths[key], sha256: byteSha256(bytes),
      commit: head, ticket: null, base: null, head: null, bounded_scope: "SPEC #1340 正本输入",
    };
  };
  const spec_ref = specRef("spec_ref");
  const crosswalk_ref = specRef("crosswalk_ref");
  const coverage_input_ref = specRef("coverage_input_ref");
  const inputBundle = spec_ref && crosswalk_ref && coverage_input_ref
    ? seal(at18InputBundleSchema, {
      schema_version: "at18-input-bundle/1", ...identity, spec_ref, crosswalk_ref, coverage_input_ref,
      external_manifests: Array.from(upstream.values(), ({ ref }) => ref),
    }) : null;
  const inputBundleBytes = inputBundle && encodeDocument(inputBundle);
  const inputRef: ArtifactRef | null = inputBundleBytes && {
    storage: "external", path: inputBundlePath, sha256: byteSha256(inputBundleBytes), commit: null,
    ticket, base, head, bounded_scope: "TB-11 两实施片共同消费的 AT-18 输入包",
  };
  if (inputRef) schemaValue(inputRef, artifactRefSchema);
  const coverageInput = specBytes.coverage_input_ref && derive("coverage_input", () =>
    parseJsonObject(specBytes.coverage_input_ref!), coverage_input_ref);
  const document = coverageInput && derive("coverage_input.destinations", () =>
    schemaValue(coverageInput, coverageInputFields), coverage_input_ref);

  function index<K, V>(scope: string, values: readonly V[], key: (value: V) => K) {
    const map = new Map<K, V>();
    for (const value of values) {
      const id = key(value);
      if (map.has(id)) fail(scope, "DUPLICATE_OBSERVATION", `重复观察：${String(id)}。`);
      else map.set(id, value);
    }
    return map;
  }
  const obligations = index("destinations", document?.destinations ?? [], d => d.ordinal);
  if (destinationIds.some(id => !obligations.has(id)) && specBytes.spec_ref) {
    // 两份正本均逐字收录 Destination。缺覆盖输入仍失败，但不丢另一份正本已知的固定义务。
    const spec = derive("spec.destinations", () => deriveJson(specBytes.spec_ref!, specDestinationFields, false), spec_ref);
    for (const id of destinationIds) {
      const fixed = spec?.stories.filter(story => story.id === `US-DST-0${id}`);
      if (!obligations.has(id) && fixed?.length === 1) {
        obligations.set(id, { ordinal: id, id: `DST-0${id}`, verbatim: fixed[0].need });
      }
    }
  }
  const destInput = index("destinations", obs.destinations ?? [], d => d.id);
  const tbInput = index("tb_summaries", obs.tb_summaries, tb => tb.tb_id);
  const legacyInput = index("legacy_dispositions", obs.legacy_dispositions, item => item.ticket);
  const unavailable = [
    ...destinationIds.filter(id => !obligations.get(id) || obligations.get(id)!.id !== `DST-0${id}`).map(id => `DST-0${id}`),
    ...tbIds.filter(id => !tbInput.has(id)),
    ...legacyTickets.filter(id => !legacyInput.has(id)).map(id => `#${id}`),
  ];
  if (unavailable.length) throw new At18BootstrapError("FIXED_ITEM_UNAVAILABLE", `缺固定项的实际值：${unavailable.join("、")}。`);

  const evidenceOwners = new Map<string, string>();
  function classRefs(scope: string, cls: z.infer<typeof evidenceClass>, values?: ArtifactRef[] | null) {
    return checkedRefs(scope, cls, values ?? []).filter(ref => {
      const owner = evidenceOwners.get(ref.sha256);
      if (owner && owner !== cls) {
        fail(scope, "EVIDENCE_CLASS_CONFLICT", `${owner} 的同一证据字节不能计入 ${cls}。`, ref);
        return false;
      }
      evidenceOwners.set(ref.sha256, cls);
      return true;
    });
  }

  const grouped = (scope: string, byClass:
    Partial<z.infer<typeof evidenceByClass>> | undefined, required: boolean) => {
    const simulation = classRefs(scope, "simulation", byClass?.simulation);
    const experiment = classRefs(scope, "experiment", byClass?.experiment);
    const production = obs.production_enabled ? classRefs(scope, "production", byClass?.production) : null;
    if (!obs.production_enabled && byClass?.production != null) fail(scope, "PRODUCTION_INACTIVE", "未授权启用的生产槽位有输入。");
    if (required) expect(simulation.length || experiment.length || production?.length,
      scope, "RUNTIME_EVIDENCE", "没有可用的实际运行证据。");
    return { simulation, experiment, production };
  };

  const reviews = (scope: string, values: z.infer<typeof review>[] = []) => {
    const usable = values.filter(r => checkedRef(scope, "independent_review", r.artifact));
    expect(usable.length > 0 && usable.every(r => r.verdict === "PASS" && integrated(r.reviewed_head)),
      scope, "INDEPENDENT_REVIEW", "缺覆盖已合入差异的非作者 PASS 独评，或所审提交未证实进入 main。");
    return usable;
  };
  const checkCi = (scope: string, values: z.infer<typeof ciRun>[] = []) => {
    expect(values.length && values.every(run => run.conclusion === "SUCCESS" && integrated(run.head_sha)),
      scope, "REQUIRED_CI", "缺绑定已合入提交的必需 CI，或 CI 未全部成功。");
    return values;
  };
  const main = (scope: string, sha: string | null | undefined) => {
    expect(sha && source.isAncestor(sha, head), scope, "MAIN_COMMIT", "缺进入 main 的产品提交，或提交不可达。");
    return sha ?? null;
  };
  const remaining = (scope: string, values: string[] = []) => {
    expect(!values.length, scope, "REMAINING_OBLIGATIONS", "仍有未完成的本图必需义务。");
    return values;
  };

  const unexecuted = obs.unexecuted ?? [];
  const pending = index("unexecuted", unexecuted, item => item.obligation);
  for (const item of unexecuted) expect(!item.required, `unexecuted:${item.obligation}`,
    "REQUIRED_UNEXECUTED", "本图必需成功项未执行。");
  for (const item of obs.permission_blocked ?? []) fail(`permission_blocked:${item.obligation}`,
    "REQUIRED_PERMISSION_BLOCKED", "本图必需成功项缺授权。");
  function pendingGate(scope: string, name: string, cls: z.infer<typeof evidenceClass>, required: boolean) {
    const entry = pending.get(name);
    if (required) expect(entry && entry.evidence_class === cls && entry.required === false,
      scope, name, "缺正确分槽的非必需未执行登记。");
    else expect(!entry, scope, name, "具名门已启用或已完成，仍登记为未执行。");
  }
  pendingGate("production", coverageGates[0], "production", !obs.production_enabled);


  const at = (value: string) => value.slice(0, -1).split(".");
  const earlier = (left: string, right: string) => {
    // RFC 3339 允许任意位小数；Date 比较会丢掉毫秒以下的先后。
    const [a, af = ""] = at(left);
    const [b, bf = ""] = at(right);
    const width = Math.max(af.length, bf.length);
    return a < b || (a === b && af.padEnd(width, "0") < bf.padEnd(width, "0"));
  };
  // 采集端提供绑定证据的 JSON 投影；存储连接器不由本生成器猜测。
  const postIdentity = { id: text, profile_id: text, evidence_class: evidenceClass };
  const gateFields = z.object({ ...postIdentity, known_at: utc });
  const versionFields = z.object({ ...postIdentity, authorized_at: utc, gate_reached_event_id: text });
  const activationFields = z.object({ ...postIdentity, known_at: utc, gate_reached_event_id: text, parameter_version_id: text });
  const sourceFields = venueFact.extend({
    source_url: z.url({ protocol: /^https?$/ }), retrieved_at: z.union([utc, z.iso.date()]),
  }).strip();
  const capabilityFields = z.object({ version: z.union([text, integer]).transform(String) });
  const permission_evidence: Record<(typeof deploymentClasses)[number], z.infer<typeof permission> | null> =
    { experiment: null, production: null };
  const migration_invariants: z.infer<typeof reportShape>["migration_invariants"] = { experiment: null, production: null };
  const post_gate_records: z.infer<typeof reportShape>["post_gate_records"] = { experiment: null, production: null };
  const permissionStart = failures.length;
  for (const cls of deploymentClasses) {
    const scope = `DST-05.${cls}`;
    const observed = obs.permission?.[cls];
    const enabled = cls === "experiment" || obs.production_enabled;
    if (!enabled) {
      expect(!observed, scope, "PRODUCTION_INACTIVE", "未启用生产权限槽位却提供了观察。");
      continue;
    }
    const [authorization_declaration = null] = classRefs(scope, cls,
      observed?.authorization_declaration ? [observed.authorization_declaration] : []);
    const [runtime_verification = null] = classRefs(scope, cls,
      observed?.runtime_verification ? [observed.runtime_verification] : []);
    const venue = fromArtifact(scope, "venue_permission_source", observed?.venue_permission_source, sourceFields);
    const venueDocument = checkedRef(scope, "venue_permission_document", observed?.venue_permission_document);
    if (venue && venueDocument) expect(venue.sha256 === venueDocument.sha256,
      scope, "VENUE_PERMISSION_SOURCE_HASH", "权限来源登记的摘要与场所文档原件不符。");
    const version = fromArtifact(scope, "capability_record", observed?.capability_record, capabilityFields);
    const profile = checkedRef(scope, "venue_profile", observed?.venue_profile);
    const slot = permission_evidence[cls] = {
      authorization_declaration, runtime_verification,
      venue_permission_fact: venue && venueDocument && venue.sha256 === venueDocument.sha256 ? venue : null,
      capability_hash: version && profile && {
        capability_record_version: version.version,
        capability_record_sha256: observed!.capability_record!.sha256, venue_profile_sha256: profile.sha256,
      },
    };
    for (const [key, value] of Object.entries(slot)) {
      expect(value, scope, key.toUpperCase(), `缺权限证据字段 ${key}。`);
    }
    expect(!authorization_declaration || !runtime_verification || authorization_declaration.sha256 !== runtime_verification.sha256,
      scope, "PERMISSION_LAYER_CONFLICT", "授权声明和运行时核验不能由同一份证据相互代替。");
  }
  const capability_hash = { experiment: permission_evidence.experiment?.capability_hash ?? null,
    production: permission_evidence.production?.capability_hash ?? null };
  const [experiment, production] = [capability_hash.experiment, capability_hash.production];
  if (experiment && production && experiment.capability_record_version === production.capability_record_version) {
    expect(experiment.capability_record_sha256 === production.capability_record_sha256,
      "DST-05", "CAPABILITY_VERSION_CONFLICT", "同版本能力记录内容冲突。");
  }
  const permissionOk = failures.length === permissionStart;

  const migrationOk = new Map<string, boolean>();
  for (const cls of deploymentClasses) {
    const scope = `migration_invariants.${cls}`;
    const observed = obs.migration?.[cls];
    if (cls === "production" && !obs.production_enabled) {
      expect(!observed, scope, "PRODUCTION_INACTIVE", "未启用生产迁移槽位却提供了观察。");
      continue;
    }
    const start = failures.length;
    const evidence = classRefs(scope, cls, proved(scope, "NON_EMPTY_MIGRATION", "缺非空场景和实际回退证据。", observed?.non_empty_run));
    const flags = {
      no_lost_rights: !!evidence.length && observed?.no_lost_rights === true,
      no_duplicated_capital: !!evidence.length && observed?.no_duplicated_capital === true,
      no_dual_write: !!evidence.length && observed?.no_dual_write === true,
      no_resend: !!evidence.length && observed?.no_resend === true,
    };
    for (const key of migrationKeys) expect(flags[key], scope, key.toUpperCase(), `未证实迁移不变量 ${key}。`);
    migration_invariants[cls] = { ...flags, non_empty_evidence_refs: evidence };
    migrationOk.set(cls, failures.length === start);
  }

  for (const cls of deploymentClasses) {
    const scope = `post_gate_records.${cls}`;
    const observed = obs.post_gate?.[cls];
    const gateName = coverageGates[cls === "experiment" ? 1 : 2];
    if (cls === "production" && !obs.production_enabled) {
      expect(!observed, scope, "PRODUCTION_INACTIVE", "未启用生产闸门后槽位却提供了观察。");
      pendingGate(scope, gateName, cls, true);
      continue;
    }
    const status = observed?.status ?? "NOT_TRIGGERED";
    const gate = fromArtifact(scope, "gate_reached_event", observed?.gate_reached_event, gateFields);
    const version = fromArtifact(scope, "parameter_version", observed?.parameter_version, versionFields);
    const activation = fromArtifact(scope, "first_activation", observed?.first_activation, activationFields);
    const active = status === "TRIGGERED_AND_ENABLED";
    const authorized = active || status === "TRIGGERED_VERSION_AUTHORIZED";
    const triggered = status !== "NOT_TRIGGERED";
    expect(!!gate === triggered, scope, "POST_GATE_EVENT", "触达记录与观测状态不符。");
    expect(!!version === authorized, scope, "POST_GATE_VERSION", "参数版本记录与观测状态不符。");
    expect(!!activation === active, scope, "POST_GATE_ACTIVATION", "首次启用记录与观测状态不符。");
    expect([gate, version, activation].every(record => record === null ||
      (record.evidence_class === cls && record.profile_id === gate?.profile_id)),
    scope, "POST_GATE_SCOPE", "闸门后记录不在同一受测 profile 和证据类。");
    if (gate && version) expect(version.gate_reached_event_id === gate.id && earlier(gate.known_at, version.authorized_at),
      scope, "POST_GATE_AUTHORIZATION_ORDER", "触达与版本的互引或时序不符。");
    if (activation && version && gate) expect(activation.gate_reached_event_id === gate.id &&
      activation.parameter_version_id === version.id && earlier(version.authorized_at, activation.known_at),
    scope, "POST_GATE_ACTIVATION_ORDER", "首次启用与前序记录的互引或时序不符。");
    const nonActivation = active
      ? checkedRefs(scope, "non_activation_evidence", observed?.non_activation?.evidence_refs)
      : proved(scope, "POST_GATE_NON_ACTIVATION", "缺受测运行未启用阶段能力的证据。", observed?.non_activation);
    if (active) expect(!observed?.non_activation, scope, "POST_GATE_STATE_CONFLICT", "已启用槽位却提供了未启用观察。");
    pendingGate(scope, gateName, cls, !active);
    post_gate_records[cls] = {
      status, gate_reached_event: gate ? observed!.gate_reached_event! : null,
      parameter_version: version ? observed!.parameter_version! : null,
      first_activation: activation ? observed!.first_activation! : null,
      gate_reached_known_at: gate?.known_at ?? null, version_authorized_at: version?.authorized_at ?? null,
      first_activation_known_at: activation?.known_at ?? null,
      non_activation_evidence: classRefs(scope, cls, nonActivation),
    };
  }

  const destinations: At18Report["destinations"] = destinationIds.map(id => {
    const scope = `DST-0${id}`;
    const start = failures.length;
    const d = destInput.get(id);
    const tickets = d?.tickets ?? [];
    const commits = d?.commits ?? [];
    expect(tickets.length, scope, "IMPLEMENTATION_TICKETS", "缺实施票和范围。");
    expect(commits.length && commits.every(commit => source.isAncestor(commit, head)),
      scope, "IMPLEMENTATION_COMMITS", "缺确切的已合入实施提交。");
    const independent_reviews = reviews(scope, d?.independent_reviews);
    const main_sha = main(scope, d?.main_sha);
    const ci_runs = checkCi(scope, d?.ci_runs);
    const evidence_by_class = grouped(scope, d?.evidence_by_class, true);
    const downstream_status = d?.downstream_status ?? [];
    expect(d?.downstream_status !== undefined, scope, "DOWNSTREAM_STATUS", "缺下游票状态观察。");
    const remaining_obligations = remaining(scope, d?.remaining_obligations);
    proved(scope, "DESTINATION_OBLIGATIONS", "缺覆盖完整 Destination 义务的实际对账。", d?.obligations);
    if ([2, 3, 5].includes(id)) expect([...migrationOk.values()].every(ok => ok),
      scope, "MIGRATION_INVARIANTS", "相关非空迁移及回退不变量未齐。");
    const passed = failures.length === start && (id !== 5 || permissionOk);
    return { id, obligation: obligations.get(id)!.verbatim, tickets, commits, independent_reviews, main_sha, ci_runs,
      evidence_by_class, permission_evidence: id === 5 ? permission_evidence : null, downstream_status,
      remaining_obligations, result: passed ? "PASS" : "FAIL" };
  });

  const tb_summaries: At18Report["tb_summaries"] = tbIds.map(tb_id => {
    const t = tbInput.get(tb_id)!;
    const ticket = tbTickets[tb_id];
    const preflight = tb_id === "TB-11";
    const start = failures.length;
    const slices = t.slices ?? [];
    const expected = preflight ? [1391, 1403] : t.expected_slice_tickets ?? [];
    expect(expected.length > 0 && slices.length === expected.length && new Set(expected).size === expected.length &&
      expected.every(ticket => slices.filter(s => s.ticket === ticket).length === 1),
    tb_id, "IMPLEMENTATION_SLICES", "缺应验实施子片清单，或实际子片未齐。");
    for (const slice of slices) {
      main(`${tb_id}.#${slice.ticket}`, slice.main_sha);
      if (!preflight) expect(slice.state === "CLOSED", `${tb_id}.#${slice.ticket}`,
        "SLICE_NOT_CLOSED", "必需实施子片尚未关闭。");
    }
    if (!preflight) expect(t.ticket_state === "CLOSED", tb_id, "TB_NOT_CLOSED", "TB 票仍为 OPEN，独立关票门未满足。");
    const main_sha = main(tb_id, t.main_sha);
    const final_reviews = reviews(tb_id, t.final_reviews);
    const ci_runs = checkCi(tb_id, t.ci_runs);
    const input_bundle = preflight ? inputRef : null;
    const evidence_by_class = grouped(tb_id, preflight ? undefined : t.evidence_by_class, !preflight);
    const entity_reports = preflight ? [] : checkedRefs(tb_id, "entity_reports", t.entity_reports);
    const remaining_obligations = preflight ? t.remaining_obligations ?? [] : remaining(tb_id, t.remaining_obligations);
    if (preflight) {
      expect(input_bundle, tb_id, "INPUT_BUNDLE_MISSING", "缺可绑定的共同输入包。");
      for (const child of expected) {
        const s = slices.find(item => item.ticket === child);
        expect(s?.main_sha && ci_runs.some(run => matchesMerged(run.head_sha, s.main_sha!)),
          `${tb_id}.#${child}`, "SLICE_REQUIRED_CI", "缺子片提交对应的必需 CI。");
        expect(s?.main_sha && final_reviews.some(review => review.verdict === "PASS" &&
          matchesMerged(review.reviewed_head, s.main_sha!)),
        `${tb_id}.#${child}`, "SLICE_INDEPENDENT_REVIEW", "缺覆盖子片最终差异的 PASS 独评。");
      }
    } else {
      expect(entity_reports.length, tb_id, "ENTITY_REPORTS", "缺本 TB 已落地的实体报告。");
      proved(tb_id, "TB_OBLIGATIONS", "缺全部外部行为的实际对账。", t.obligations);
      if (tb_id === "TB-08" || tb_id === "TB-09" || tb_id === "TB-10") {
        for (const cls of deploymentClasses) {
          if (cls === "experiment" || obs.production_enabled) expect(evidence_by_class[cls]?.length,
            `${tb_id}.${cls}`, "DEPLOYMENT_RUNTIME_EVIDENCE", "缺该已启用部署槽位的实际运行证据。");
        }
      }
      if (tb_id === "TB-10") {
        for (const cls of deploymentClasses) {
          if (cls === "production" && !obs.production_enabled) continue;
          const evidence = migration_invariants[cls]?.non_empty_evidence_refs ?? [];
          expect(migrationOk.get(cls) && evidence.some(ref => evidence_by_class[cls]?.some(r => r.sha256 === ref.sha256)),
            `${tb_id}.${cls}`, "TB_MIGRATION_INVARIANTS", "缺本 TB 自身的非空迁移及回退证据。");
        }
      }
    }
    return { tb_id, ticket, slices, input_bundle, evidence_by_class, final_reviews, main_sha, ci_runs, entity_reports,
      remaining_obligations, ticket_state: t.ticket_state, gate_satisfied: start === failures.length };
  });

  const rawCrosswalk = specBytes.crosswalk_ref;
  const rows = rawCrosswalk && derive("spec_coverage", () => parseJsonObject(rawCrosswalk), crosswalk_ref);
  const projection = <T>(key: keyof Crosswalk, schema: z.ZodType<T[]>): T[] => {
    if (!rows) return [];
    return derive(`spec_coverage.${key}`, () => {
      const value = schemaValue(rows[key], schema);
      canonicalizeJcs(value);
      return value;
    }, crosswalk_ref) ?? [];
  };
  const crosswalk = rows && {
    rows: projection("rows", crosswalkFields.shape.rows),
    family_entry_links: projection("family_entry_links", crosswalkFields.shape.family_entry_links),
    detailed_acceptance_links: projection("detailed_acceptance_links", crosswalkFields.shape.detailed_acceptance_links),
  };
  const spec_coverage = buildCoverage(crosswalk, crosswalk_ref?.sha256 ?? null);
  function buildCoverage(crosswalk: Crosswalk | null, crosswalk_sha256: string | null): At18Report["spec_coverage"] {
    const collected = index("spec_coverage", obs.coverage ?? [], value => `${value.kind}:${value.id}`);
    const used = new Set<string>();
    const expected = [97, 345, 496];
    const count = [crosswalk?.rows.length, crosswalk?.family_entry_links.length, crosswalk?.detailed_acceptance_links.length];
    expect(count.every((value, i) => value === expected[i]) && crosswalk_sha256 === inputBundle?.crosswalk_ref.sha256,
      "spec_coverage", "CROSSWALK_ALIGNMENT", "crosswalk 必须对齐同一输入包的 97 故事、345 family、496 细项。");
    const entryKeys = new Set<string>();
    function resolveEntry(kind: "story" | "family" | "detail", id: string,
      slices: Crosswalk["rows"][number]["success_closure_slice_ids"], preserve = false) {
      const scope = `spec_coverage.${kind}:${id}`;
      const start = failures.length;
      const key = `${kind}:${id}`;
      expect(!entryKeys.has(key), scope, "CROSSWALK_DUPLICATE_ID", "crosswalk 的同类条目 ID 重复。");
      entryKeys.add(key);
      const item = collected.get(key);
      used.add(key);
      const bySlice = index(scope, item?.slices ?? [], s => s.tb_id);
      const evidence_refs: ArtifactRef[] = [];
      for (const slice of slices) {
        if (slice === "TB-11") {
          const tb11 = tb_summaries[10];
          if (tb11.gate_satisfied && tb11.input_bundle) evidence_refs.push(tb11.input_bundle);
          else fail(scope, "COVERAGE_TB11_GATE", "TB-11 前置实施门或共同输入包缺失。");
          continue;
        }
        evidence_refs.push(...proved(scope, `COVERAGE_${slice}`,
          preserve ? `${slice} 缺本条的排除与防混用证据。` : `${slice} 缺本条在该切片的子义务证据。`,
        bySlice.get(slice)?.proof));
      }
      for (const id of bySlice.keys()) expect(id !== "TB-11" && slices.includes(id), scope,
        "COVERAGE_UNEXPECTED_SLICE", "观察引用了非对应切片或尝试替代 TB-11 共同输入包。");
      const deferred = index(scope, item?.deferred_gates ?? [], entry => entry.gate);
      const deferred_gates = [...deferred.keys()];
      expect(evidence_refs.length && !(slices.length === 1 && slices[0] === "TB-11" && deferred_gates.length),
        scope, "COVERAGE_EVIDENCE", "缺本条已启用范围的子义务证据。");
      expect(!preserve || !deferred_gates.length, scope, "BOUNDARY_CANNOT_DEFER", "排除边界仍须核验，不得延后。");
      for (const [gate, observation] of deferred) {
        const entry = pending.get(gate);
        const isProduction = gate !== coverageGates[1];
        evidence_refs.push(...proved(scope, "COVERAGE_DEFERRED_BOUNDARY",
          `缺 ${gate} 对本条子义务适用的证据。`, observation.boundary));
        expect(entry?.required === false && entry.evidence_class === (isProduction ? "production" : "experiment") &&
          (gate === coverageGates[0] ? !obs.production_enabled :
            post_gate_records[entry.evidence_class]?.status !== "TRIGGERED_AND_ENABLED"),
        scope, "COVERAGE_DEFERRED_GATE", `延期门 ${gate} 没有对应的非必需未执行登记。`);
      }
      const status: "FAIL" | "BOUNDED_DEFERRED" | "VERIFIED" = start !== failures.length ? "FAIL" : deferred_gates.length ? "BOUNDED_DEFERRED" : "VERIFIED";
      const seen = new Set<string>();
      return { evidence_refs: evidence_refs.filter(ref => {
        const key = canonicalizeJcs(ref);
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      }), deferred_gates, status };
    }
    const stories = (crosswalk?.rows ?? []).map(row => ({
      story_id: row.story_id, closure_slice_ids: row.success_closure_slice_ids, destination_ids: row.destination_ids,
      ...resolveEntry("story", row.story_id, row.success_closure_slice_ids),
    })) satisfies At18Report["spec_coverage"]["stories"];
    const families = (crosswalk?.family_entry_links ?? []).map(row => {
      const preserve = row.exclusion_boundary === true;
      const entry = resolveEntry("family", row.id, row.success_closure_slice_ids, preserve);
      if (row.id === "OE42") {
        const match = /^\/old_entry_groups\/(0|[1-9]\d*)$/.exec(row.source_json_pointer);
        const groups = coverageInput?.old_entry_groups;
        const disposition = match && Array.isArray(groups) && oldEntryField.safeParse(groups[Number(match[1])]);
        if (preserve || !disposition || !disposition.success || disposition.data.id !== row.id ||
            disposition.data.effective_disposition.kind !== "OUT_OF_SCOPE_PRESERVE") {
          entry.status = "FAIL";
          fail("spec_coverage.family:OE42", "COVERAGE_OE42_DISPOSITION", "所绑定覆盖输入未指向 OE42 的 OUT_OF_SCOPE_PRESERVE 处分。");
        }
      }
      return { family: row.family, id: row.id, ...entry, entry_mode: preserve ? "OUT_OF_SCOPE_PRESERVE" : "REQUIRED",
        status: preserve && entry.status === "VERIFIED" ? "PRESERVED_BOUNDARY" : entry.status };
    }) satisfies At18Report["spec_coverage"]["families"];
    const details = (crosswalk?.detailed_acceptance_links ?? []).map(row => ({
      id: row.id, family_entry_id: row.family_entry_id, ...resolveEntry("detail", row.id, row.success_closure_slice_ids),
    })) satisfies At18Report["spec_coverage"]["details"];
    for (const key of collected.keys()) expect(used.has(key), "spec_coverage", "COVERAGE_UNKNOWN_ENTRY", `观察条目不在 crosswalk：${key}。`);
    return { crosswalk_sha256, stories, families, details };
  }

  const legacy_dispositions: At18Report["legacy_dispositions"] = legacyTickets.map(ticket => {
    const item = legacyInput.get(ticket)!;
    const scope = `legacy:#${ticket}`;
    const start = failures.length;
    const evidence_refs = proved(scope, "LEGACY_DISPOSITION_EVIDENCE", "缺旧关联票逐项去向证据。", item.disposition_proof);
    const { disposition, ticket_state, remaining_obligations = [] } = item;
    if (ticket === 942 || ticket === 1282) expect(ticket_state === "CLOSED", scope,
      "LEGACY_MUST_STAY_CLOSED", "原处分须保持关闭。");
    if (ticket === 1304 && ticket_state === "CLOSED") expect(evidence_refs.length, scope,
      "LEGACY_1304_CLOSED_WITHOUT_EVIDENCE", "未核实报告器及回归锁，不得关闭 #1304。");
    if (ticket === 1320) {
      const heavyEvidence = item.heavy_resolved
        ? proved(scope, "ISSUE_1320_HEAVY_RESOLUTION_EVIDENCE", "缺重型测量完成或合法废弃原件。", item.heavy_resolved) : [];
      evidence_refs.push(...heavyEvidence);
      pendingGate(scope, heavy, "simulation", heavyEvidence.length === 0);
      if (!heavyEvidence.length) expect(ticket_state === "OPEN", scope,
        "ISSUE_1320_HEAVY_MEASUREMENT_OPEN", "重型测量未完成或未合法废弃，#1320 必须仍为 OPEN。");
    }
    if (ticket === 1279) {
      expect(ticket_state === "OPEN", scope, "ISSUE_1279_MUST_STAY_OPEN", "#1279 在整图验收阶段须仍为 OPEN。");
      evidence_refs.push(...proved(scope, "ISSUE_1279_OWN_REMAINING_ONLY", "缺证据表明剩余项只属于 #1279。", item.own_remaining_only));
      evidence_refs.push(...proved(scope, "ISSUE_1279_NOT_RELEASED", "缺未宣布试运行放行的证据。", item.not_released));
      expect(destinations.every(d => d.result === "PASS") && tb_summaries.slice(0, 10).every(tb => tb.gate_satisfied) &&
        [...spec_coverage.stories, ...spec_coverage.families, ...spec_coverage.details].every(entry => entry.status !== "FAIL"),
      scope, "ISSUE_1279_GRAPH_OBLIGATIONS", "本图 Destination、TB 或 SPEC 覆盖义务尚未完成。");
    }
    return { ticket, disposition, evidence_refs, ticket_state, remaining_obligations,
      disposition_valid: failures.length === start };
  });

  const body = {
    schema_version: "at18-report/1" as const, ...identity, capability_hash, destinations, tb_summaries, spec_coverage,
    migration_invariants, post_gate_records, legacy_dispositions, unexecuted, permission_blocked: obs.permission_blocked ?? [],
    bounded_domain_statement: obs.bounded_domain_statement,
  };
  const [first, ...rest] = failures;
  const report = seal(at18ReportSchema, first
    ? { ...body, overall_result: "FAIL", failed_checks: [first, ...rest] }
    : { ...body, overall_result: "PASS", failed_checks: [] });
  return { inputBundle, inputBundleBytes, report, reportBytes: encodeDocument(report) };
}

function seal<T>(schema: z.ZodType<T>, body: Record<string, unknown>): T {
  const content_hash = computeContentHash(body);
  return schemaValue({ ...body, content_hash }, schema);
}

export function renderSummary(report: At18Report): string {
  const ledger = report.spec_coverage;
  const counts = new Map<string, number>();
  for (const check of report.failed_checks) counts.set(check.check_id, (counts.get(check.check_id) ?? 0) + 1);
  return [
    "# AT-18 整图验收", "", `结论：**${report.overall_result}**`, "", `主线提交：\`${report.head}\``, "",
    `覆盖账本：${ledger.stories.length} 个故事、${ledger.families.length} 个 family、${ledger.details.length} 个细项。`, "",
    "## Destination", "", ...report.destinations.map(d => `- DST-0${d.id}：${d.result}`), "",
    "## TB 关票门", "", ...report.tb_summaries.map(tb => `- ${tb.tb_id} #${tb.ticket}：${tb.ticket_state}，${tb.gate_satisfied ? "满足" : "未满足"}`), "",
    "## 失败项", "", `共 ${report.failed_checks.length} 项。逐项 scope 和证据见同批 at18-report.json。`, "",
    ...Array.from(counts, ([name, count]) => `- \`${name}\`：${count}`), "",
  ].join("\n");
}
