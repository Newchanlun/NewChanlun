import { createHash } from "node:crypto";
import { isAbsolute } from "node:path";
import { z } from "zod";
import { isRow, type Row } from "./at18-github.ts";

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
const isTb = (key: string): key is keyof typeof tbTickets => Object.hasOwn(tbTickets, key);
export const tbIds = Object.keys(tbTickets).filter(isTb);
export const tbId = z.enum(tbIds);
export const legacyTickets = [942, 1096, 1282, 1304, 1319, 1320, 1279] as const;
export const dispositions = ["PRESERVE_BOUNDED", "RETIRE_OR_INCORPORATE", "PRESERVE_ARCHIVE", "ADOPT_AT14", "INCORPORATE_FEED_WIRE", "REPLAY_AND_PRESERVE_HEAVY", "KEEP_OPEN"] as const;
const destinationIds = [1, 2, 3, 4, 5, 6] as const;
const classSlot = <T extends z.ZodType>(schema: T) =>
  z.strictObject({ experiment: schema, production: schema });
export const text = z.string().min(1).refine(s => !/[\uD800-\uDFFF]/u.test(s));
export const sha = z.string().regex(/^[0-9a-f]{40}$/);
export const digest = z.string().regex(/^[0-9a-f]{64}$/);
export const utc = z.iso.datetime({ offset: false, local: false }).refine(value => /T\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(value));
export const integer = z.int().positive();
export const state = z.enum(["OPEN", "CLOSED"]).nullable();
const result = z.enum(["PASS", "FAIL"]);
export const evidenceClass = z.enum(["simulation", "experiment", "production"]);
export const cleanPath = (path: string) => !path.includes("\\") && !path.includes("\0") &&
  path.split("/").every(part => part !== "." && part !== "..");
export const externalPath = text.refine(path => isAbsolute(path) && cleanPath(path));
export const repoPath = text.refine(path => !isAbsolute(path) && cleanPath(path));

// Zod 4 在 strictObject 中也会忽略此键；AT-18 的封闭格式不能丢字段后再校验。
const rejectProtoKey = z.unknown().superRefine((value, ctx) => {
  const pending = [value];
  const seen = new Set<object>();
  for (const item of pending) {
    if (item === null || typeof item !== "object" || seen.has(item)) continue;
    if (Object.hasOwn(item, "__proto__")) {
      ctx.addIssue({ code: "custom", message: "未声明的 __proto__ 键。" });
      return;
    }
    seen.add(item);
    for (const field of Object.values(item)) pending.push(field);
  }
});


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
const evidenceByClass = z.strictObject({ simulation: refs, experiment: refs, production: z.null() });
const capability = z.strictObject({
  capability_record_version: text, capability_record_sha256: digest, venue_profile_sha256: digest,
});
const venueFact = z.strictObject({ source_url: text, retrieved_at: text, sha256: digest });
const permission = z.strictObject({
  authorization_declaration: artifactRefSchema.nullable(), venue_permission_fact: venueFact.nullable(),
  runtime_verification: artifactRefSchema.nullable(), capability_hash: capability.nullable(),
});
export const review = z.strictObject({
  pr: integer, reviewed_head: sha, merge_commit: sha, status_id: integer, creator: text,
  state: z.enum(["success", "failure", "pending", "error"]),
});
export const conclusion = z.enum(["SUCCESS", "FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "NEUTRAL", "SKIPPED", "STALE"]);
export const workflows = ["ci.yml", "devskim.yml", "at18-acceptance.yml", "at18-experiment.yml"]
  .map(name => ".github/workflows/" + name);
export const ciRun = z.strictObject({ workflow: text, run_id: integer, run_attempt: integer, head_sha: sha,
  conclusion: conclusion.nullable(), url: text });
export const workflowRun = z.strictObject({ workflow: text, run_id: integer.nullable(), run_attempt: integer.nullable() });
export const acceptanceJob = ciRun.omit({ url: true }).extend({ job: text });
export const historicalDeviation = z.strictObject({ ticket: integer, commit: sha, workflow: text,
  run_id: integer.nullable(), observed: z.union([conclusion, z.enum(["NO_RUN", "INCOMPLETE", "UNKNOWN"])]) });
const ticketScope = z.strictObject({ ticket: integer, scope: text });
const downstream = z.strictObject({ ticket: integer, state });
const slice = downstream.extend({ state_reason: z.enum(["COMPLETED", "NOT_PLANNED", "REOPENED", "DUPLICATE"]).nullable() });
const migration = z.strictObject({
  no_lost_rights: z.boolean(), no_duplicated_capital: z.boolean(), no_dual_write: z.boolean(), no_resend: z.boolean(),
  non_empty_evidence_refs: refs,
});
export const postStatus = z.enum([
  "UNKNOWN", "NOT_TRIGGERED", "TRIGGERED_AWAITING_POLICY", "TRIGGERED_VERSION_AUTHORIZED", "TRIGGERED_AND_ENABLED",
]);
const postGate = z.strictObject({
  status: postStatus, gate_reached_event: artifactRefSchema.nullable(), parameter_version: artifactRefSchema.nullable(),
  first_activation: artifactRefSchema.nullable(), gate_reached_known_at: utc.nullable(),
  version_authorized_at: utc.nullable(), first_activation_known_at: utc.nullable(), non_activation_evidence: refs,
});
export const coverageGates = ["ISSUE_1561_P2_FIRST_SEND", "ADR_0036_POST_GATE_EXPERIMENT", "ADR_0036_POST_GATE_PRODUCTION"] as const;
export const heavy = "ISSUE_1320_HEAVY_MEASUREMENT";
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

const identity = { ticket: z.literal(1391), base: sha, head: sha, generated_at: utc };
const bundleShape = z.strictObject({
  schema_version: z.literal("at18-input-bundle/1"), content_hash: digest, ...identity,
  spec_ref: inRepoArtifact, crosswalk_ref: inRepoArtifact, coverage_input_ref: inRepoArtifact,
  registry_ref: inRepoArtifact, pregate_review_ref: inRepoArtifact,
  slice_ledger_refs: z.array(inRepoArtifact).length(4), external_manifests: z.array(manifestRefSchema),
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
  ticket: integer, disposition: z.enum(dispositions), evidence_refs: refs, ticket_state: state,
  remaining_obligations: z.array(text), disposition_valid: z.boolean(),
});
export const unexecuted = z.strictObject({
  obligation: text, reason: text, blocker_or_gap: text, evidence_class: evidenceClass, required: z.boolean(),
});
export const permissionBlocked = z.strictObject({
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
  workflow_runs: z.array(workflowRun).length(4), acceptance_jobs: z.array(acceptanceJob),
  historical_deviations: z.array(historicalDeviation),
  unexecuted: z.array(unexecuted), permission_blocked: z.array(permissionBlocked), bounded_domain_statement: text,
};
const reportShape = z.discriminatedUnion("overall_result", [
  z.strictObject({ ...reportFields, overall_result: z.literal("PASS"), failed_checks: z.tuple([]) }),
  z.strictObject({ ...reportFields, overall_result: z.literal("FAIL"), failed_checks: z.tuple([failedCheckSchema]).rest(failedCheckSchema) }),
]);
export type At18InputBundle = z.infer<typeof bundleShape>;
export type At18Report = z.infer<typeof reportShape>;

// §五：首先读原字节；只有读到且需要结构化字段时才进入后续步骤。
type DerivedStep = "FILE_READ" | "JSON_PARSE" | "JCS_CANONICALIZE" | "SCHEMA";
export class At18DerivationError extends Error {
  constructor(readonly check_id: DerivedStep, detail: string) { super(detail); }
}

export class At18BootstrapError extends Error {
  constructor(readonly code: string, detail: string, readonly path?: string) { super(detail); }
}

export const byteSha256 = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");

// JSON.parse 负责语法；对同一棵树保留数字原词，避免将 1.0、1e0 和 1 判成同一个 Python int。
const numberTokens = new WeakMap<object, Map<string, string>>();
const intToken = /^-?(?:0|[1-9][0-9]*)$/;
export function jsonInteger(parent: unknown, key: string, value: unknown): bigint | undefined {
  const token = typeof parent === "object" && parent !== null ? numberTokens.get(parent)?.get(key) : undefined;
  if (token !== undefined) return intToken.test(token) ? BigInt(token) : undefined;
  return typeof value === "number" && Number.isSafeInteger(value) ? BigInt(value) : undefined;
}
export function jsonNumber(parent: unknown, key: string, value: unknown) {
  return (typeof value === "number" && Number.isFinite(value)) || jsonInteger(parent, key, value) !== undefined;
}

export function parseJsonObject(bytes: Uint8Array, numbers: "jcs" | "producer" = "jcs"): Record<string, unknown> {
  let source: string;
  let value: unknown;
  const bad = (message: string): never => { throw new At18DerivationError("JSON_PARSE", message); };
  try {
    source = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new At18DerivationError("JSON_PARSE", "文件不是合法 UTF-8。");
  }
  try { value = JSON.parse(source); }
  catch { throw new At18DerivationError("JSON_PARSE", "文件不符合 JSON 语法。"); }
  if (!isRow(value)) throw new At18DerivationError("JSON_PARSE", "JSON 顶层须为对象。");
  const tokens = source.matchAll(/"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\]:,]|true|false|null/gs);
  const next = () => tokens.next().value?.[0];
  const unicode = (s: string) => { if (/[\uD800-\uDFFF]/u.test(s)) bad("JSON 含孤立代理码点。"); };
  function scan(item: unknown, parent: object | undefined, key: string, token = next()): void {
    if (token === "{") {
      const keys = new Set<string>();
      for (let field = next(); field !== undefined && field !== "}"; field = next()) {
        if (field === ",") continue;
        const name: string = JSON.parse(field);
        if (keys.has(name)) bad("JSON 含重复键。");
        keys.add(name);
        if (numbers === "producer") unicode(name);
        next(); // 冒号已由 JSON.parse 验证
        scan(isRow(item) ? item[name] : undefined, isRow(item) ? item : undefined, name);
      }
    } else if (token === "[") {
      let index = 0;
      for (let element = next(); element !== undefined && element !== "]"; element = next()) {
        if (element !== ",") {
          scan(Array.isArray(item) ? item[index] : undefined, Array.isArray(item) ? item : undefined, String(index), element);
          index++;
        }
      }
    } else if (typeof item === "number" && token !== undefined && parent) {
      let fields = numberTokens.get(parent);
      if (!fields) { fields = new Map(); numberTokens.set(parent, fields); }
      fields.set(key, token);
      // CPython strict_json 的 float 必须有限；int 不经过 IEEE 754。
      if (numbers === "producer") {
        if (!intToken.test(token) && !Number.isFinite(item)) bad("JSON 浮点数必须有限。");
        // 与 CPython 生产入口默认的十进制解析上限一致；不设 IEEE 754 安全整数上限。
        if (intToken.test(token) && token.length - Number(token.startsWith("-")) > 4300) bad("JSON 整数字面量超过生产入口上限。");
      }
    } else if (numbers === "producer" && typeof item === "string") unicode(item);
  }
  try { scan(value, undefined, ""); }
  catch (e) {
    if (e instanceof At18DerivationError) throw e;
    throw new At18DerivationError("JSON_PARSE", "JSON 嵌套无法读取。");
  }
  return value;
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
      const entries: [string, unknown][] = Object.entries(item);
      return `{${entries.sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
        .map(([key, v]) => `${string(key)}:${encode(v)}`).join(",")}}`;
    } finally { active.delete(item); }
  };
  return encode(value);
}

export function computeContentHash({ content_hash: _self, ...body }: Record<string, unknown>): string {
  return byteSha256(Buffer.from(canonicalizeJcs(body), "utf8"));
}

function hashMatches(value: Row & { content_hash: string }, ctx: z.RefinementCtx) {
  try {
    if (computeContentHash(value) === value.content_hash) return;
  } catch (error) {
    ctx.addIssue({ code: "custom", path: ["content_hash"], message: String(error) });
    return;
  }
  ctx.addIssue({ code: "custom", path: ["content_hash"], message: "content_hash 与规范化内容不符。" });
}

export const ledgerPaths = ["TB01-EXECUTION-SLICES", "TB02-06-EXECUTION-SLICES", "TB07-11-EXECUTION-SLICES", "TB01-PARENT-CONTRIBUTION"]
  .map(name => ".chanlun/review-results/issue1340-publication-20260909/payload/inputs/" + name + ".json");
export const at18InputBundleSchema = rejectProtoKey.pipe(bundleShape.superRefine((value, ctx) => {
  hashMatches(value, ctx);
  if (value.slice_ledger_refs.some((r, i) => r.path !== ledgerPaths[i])) {
    ctx.addIssue({ code: "custom", path: ["slice_ledger_refs"], message: "切片账固定顺序不符。" });
  }
}));
export const at18ReportSchema = rejectProtoKey.pipe(reportShape.superRefine((report, ctx) => {
  const wrong = (field: string) => ctx.addIssue({ code: "custom", path: [field], message: "固定项顺序或槽位编码不符。" });
  if (report.destinations.some((d, i) => d.id !== destinationIds[i] || (d.id === 5) !== (d.permission_evidence !== null))) wrong("destinations");
  if (report.tb_summaries.some((tb, i) => tb.tb_id !== tbIds[i] || tb.ticket !== tbTickets[tbIds[i]] ||
    (i === 10 ? tb.entity_reports.length !== 0 : tb.input_bundle !== null))) wrong("tb_summaries");
  if (report.legacy_dispositions.some((l, i) => l.ticket !== legacyTickets[i] || l.disposition !== dispositions[i])) wrong("legacy_dispositions");
  if (report.workflow_runs.some((r, i) => r.workflow !== workflows[i])) wrong("workflow_runs");
  const enabled = false;
  if (report.migration_invariants.production !== null) wrong("migration_invariants");
  const permissionSlots = report.destinations[4]?.permission_evidence;
  if (report.migration_invariants.experiment === null || report.post_gate_records.experiment === null ||
    !permissionSlots?.experiment || (permissionSlots.production !== null) !== enabled ||
    (report.post_gate_records.production !== null) !== enabled ||
    (!enabled && report.capability_hash.production !== null) ||
    [...report.destinations, ...report.tb_summaries].some(r => (r.evidence_by_class.production !== null) !== enabled) ||
    report.tb_summaries.slice(-1).some(tb => Object.values(tb.evidence_by_class).some(refs => refs?.length))) wrong("post_gate_records");
  hashMatches(report, ctx);
}));

export function schemaValue<T>(value: unknown, schema: z.ZodType<T>): T {
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

export function seal<T>(schema: z.ZodType<T>, body: Record<string, unknown>): T {
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
