import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import { byteSha256, canonicalizeJcs, digest, evidenceClass, integer, repoPath, sha, tbId, text, utc } from "./at18-format.ts";
import { object, rows, type Row } from "./at18-github.ts";
import { valueAt } from "./at18-source.ts";

const token = z.string().regex(/^[A-Za-z0-9._-]+$/);
export const profileId = token.refine(value => value !== "none");
export const ptr = z.string().regex(/^(?:\/(?:[^~]|~[01])*)?$/);
export const kind = z.enum(["story", "family", "detail"]);
export type Kind = z.infer<typeof kind>;
export const evidenceKey = z.strictObject({ kind, id: text });
const check = z.strictObject({ check_id: token, group: token, evidence_class: evidenceClass, profile_id: profileId.nullable(),
  runner: z.enum(["cargo-test", "node-test", "pytest", "command"]), selector: text, expected_count: integer,
  key_aware: z.boolean(), source: z.strictObject({ path: repoPath, sha256: digest }), record: text.nullable() });
const domain = z.strictObject({ evidence_class: evidenceClass, profile_id: profileId.nullable(),
  result: z.enum(["VERIFIED", "PRESERVED_BOUNDARY", "BOUNDED_DEFERRED"]), deferred_gate: text.nullable(),
  checks: z.array(token) });
const basis = z.strictObject({ path: repoPath, sha256: digest, pointer: ptr });
const binding = z.strictObject({ binding_id: token, slice_id: tbId.exclude(["TB-11"]), basis,
  keys: z.array(evidenceKey).min(1), domains: z.array(domain).min(1) });
const landingScope = z.union([tbId.exclude(["TB-11"]), z.literal("GRAPH")]);
const cure = z.strictObject({ commit: sha, run_id: integer.nullable(), kind: z.enum(["test", "step"]), target: text, check_id: token });
export const landing = z.strictObject({ ticket: integer, commits: z.array(sha).min(1), attribution_scopes: z.array(landingScope).min(1),
  cure_checks: z.array(cure) });
export const registrySchema = z.strictObject({ schema_version: z.literal("at18-registry/1"), crosswalk_sha256: digest,
  adapter_contract_sha256: digest, experiment_profile_id: profileId.nullable(), checks: z.array(check), bindings: z.array(binding),
  pregate: z.strictObject({ census_sha256: digest, landings: z.array(landing) }) });
export type Registry = z.infer<typeof registrySchema>;
export type Check = z.infer<typeof check>;
export type Domain = z.infer<typeof domain>;
export type Basis = Pick<z.infer<typeof basis>, "path" | "pointer">;
export type Landing = z.infer<typeof landing>;
export const pregateSchema = z.strictObject({ schema_version: z.literal("at18-pregate-review/1"), owner_ticket: z.literal(2132),
  rows: z.array(z.strictObject({ path: repoPath, blob: sha, mode: z.enum(["100644", "100755", "120000"]),
    verdict: z.enum(["PASS", "BLOCK"]) })) });
export const censusSchema = z.strictObject({ schema_version: z.literal("at18-landing-census/1"), p0: sha,
  sources: z.array(z.strictObject({ role: z.enum(["history", "relations", "signals", "adjudication"]),
    path: repoPath, sha256: digest })).length(4),
  attributions: z.array(z.strictObject({ ticket: integer, attribution_scopes: z.array(landingScope).min(1), sources: z.array(text).min(1) })),
});
export const envelope = z.strictObject({ schema_version: z.literal("at18-run-record/1"), record: text, head: sha,
  run_id: integer, run_attempt: integer, check_id: token, profile_id: profileId.nullable(), payload: z.record(z.string(), z.unknown()) });

// #2131 PR #2166 的封闭 schema；不使用 F 上自报的新 schema 改写消费方的判据。
const adapterSchema: Row = object(JSON.parse(readFileSync(resolve(__dirname, "fixtures/at18/adapter-contract.schema.json"), "utf8")));
const eq = (a: unknown, b: unknown) => canonicalizeJcs(a) === canonicalizeJcs(b);
function matches(value: unknown, schema: Row): boolean {
  if (typeof schema.$ref === "string") return matches(value, object(valueAt(adapterSchema, schema.$ref.slice(1))));
  if (Object.hasOwn(schema, "const") && !eq(value, schema.const)) return false;
  if (Array.isArray(schema.enum) && !schema.enum.some(item => eq(item, value))) return false;
  if (Array.isArray(schema.anyOf) && !rows(schema.anyOf).some(item => matches(value, item))) return false;
  if (schema.type === "object") {
    const v = object(value);
    const properties = schema.properties ? object(schema.properties) : {};
    if (Array.isArray(schema.required) && schema.required.some(k => typeof k !== "string" || !Object.hasOwn(v, k))) return false;
    return Object.entries(v).every(([key, item]) => {
      if (schema.propertyNames && !matches(key, object(schema.propertyNames))) return false;
      if (Object.hasOwn(properties, key)) return matches(item, object(properties[key]));
      return schema.additionalProperties !== false &&
        (!schema.additionalProperties || schema.additionalProperties === true || matches(item, object(schema.additionalProperties)));
    });
  }
  if (schema.type === "array") {
    if (!Array.isArray(value) || (typeof schema.minItems === "number" && value.length < schema.minItems)) return false;
    if (schema.uniqueItems && new Set(value.map(canonicalizeJcs)).size !== value.length) return false;
    return !schema.items || value.every(item => matches(item, object(schema.items)));
  }
  if (schema.type === "string") return typeof value === "string" &&
    (typeof schema.minLength !== "number" || value.length >= schema.minLength) &&
    (typeof schema.pattern !== "string" || new RegExp(schema.pattern, "u").test(value));
  if (schema.type === "integer") return typeof value === "number" && Number.isSafeInteger(value) &&
    (typeof schema.minimum !== "number" || value >= schema.minimum);
  if (schema.type === "boolean") return typeof value === "boolean";
  if (schema.type === "null") return value === null;
  return schema.type === undefined;
}
const fieldRule = z.strictObject({ pointer: ptr, type: text, decode_as: text.optional() });
const fieldsSchema = z.record(z.string(), fieldRule);
const decoder = z.object({ fields: fieldsSchema, role: text });
const authPin = z.object({ ticket: integer, comment_id: integer.nullable(), body_sha256: digest.nullable(), signature_fence: text });
export const contractProjection = z.object({
  run_record_envelope: fieldsSchema,
  run_records: z.record(z.string(), decoder.extend({ version: text, version_pointer: ptr })),
  item_sources: z.record(z.string(), fieldsSchema),
  external_sources: z.record(z.string(), decoder.extend({ ticket: integer.nullable() })),
  legacy_sources: z.record(z.string(), z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("git-blob"), commit: sha, path: repoPath, pointer: ptr.nullable(), type: text, sha256: digest }),
    z.object({ kind: z.enum(["issue-comment", "issue-body"]), ticket: integer, comment_id: integer.nullable(), pointer: ptr, type: text, sha256: digest }),
  ])),
  legacy_dispositions: z.record(z.string(), z.object({ disposition: text, sources: z.array(text),
    obligations: z.record(z.string(), z.object({ requirement: text, sources: z.array(text), tb_ids: z.array(tbId),
      when: text, entity: text.nullable() })) })),
  issue_1279: z.object({
    own_checklist: z.array(z.object({ source: text, entry: integer, line: integer, key: text })),
    release_disposition: z.object({ known_historical_comments: z.array(text) }),
  }),
  experiment_authorization: authPin.extend({ fields: fieldsSchema, group_actions: z.record(z.string(), z.array(text)),
    send_authorization: authPin }),
});
export type Adapter = z.infer<typeof contractProjection>;
export function adapter(value: unknown): Adapter {
  if (!matches(value, adapterSchema)) throw new Error("REGISTRY_INVALID");
  return contractProjection.parse(value);
}
export function typed(value: unknown, type: string): boolean {
  if (type.startsWith("nullable-")) return value === null || typed(value, type.slice(9));
  if (type.endsWith("-array")) return Array.isArray(value) && value.every(v => typed(v, type.slice(0, -6)));
  if (type === "object") return !!value && typeof value === "object" && !Array.isArray(value);
  if (type === "boolean") return typeof value === "boolean";
  if (type === "bytes") return Buffer.isBuffer(value);
  if (type === "https-url") {
    if (typeof value !== "string") return false;
    try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password; } catch { return false; }
  }
  const schemas: Record<string, z.ZodType> = { string: text, "profile-id": profileId, "positive-integer": integer,
    sha256: digest, "git-commit": sha, "evidence-class": evidenceClass, pointer: ptr, "utc-timestamp": utc,
    "decimal-string": z.string().regex(/^-?(0|[1-9]\d*)(\.\d+)?$/) };
  return schemas[type]?.safeParse(value).success ?? false;
}
type FieldRules = z.infer<typeof fieldsSchema>;
export function decodeFields(contract: Adapter, fields: FieldRules, input: unknown, depth = 0): Row {
  if (depth > 8) throw new Error("SCHEMA");
  return Object.fromEntries(Object.entries(fields).map(([name, rule]) => {
    const value = valueAt(input, rule.pointer);
    if (!typed(value, rule.type)) throw new Error("SCHEMA");
    const nested = rule.decode_as && contract.item_sources[rule.decode_as];
    if (rule.decode_as && !nested) throw new Error("SCHEMA");
    return [name, !nested ? value : Array.isArray(value)
      ? value.map(v => decodeFields(contract, nested, v, depth + 1)) : decodeFields(contract, nested, value, depth + 1)];
  }));
}
export function decodeRecord(contract: Adapter, record: string, payload: Row): Row {
  const rule = contract.run_records[record] ?? contract.run_records.tb;
  if (valueAt(payload, rule.version_pointer) !== rule.version) throw new Error("SCHEMA");
  return decodeFields(contract, rule.fields, payload);
}
export function sameDigest(bytes: Buffer, hash: string) { return byteSha256(bytes) === hash; }
