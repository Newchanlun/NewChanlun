import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { z } from "zod";
import {
  artifactRefSchema, at18InputBundleSchema, at18ReportSchema, byteSha256, canonicalizeJcs,
  computeContentHash, deriveJson, generateAt18, legacyTickets, parseJsonObject, specPaths, tbTickets,
  type ArtifactRef, type At18Observations, type At18Report,
} from "./at18-report.ts";
import type { DeliveryManifest } from "./delivery-bundle.ts";
import { claim, legacyRules, type EvidenceClaim, type EvidenceFinding } from "./at18-evidence.ts";
import { at18GitHub } from "./at18-github.ts";
import { gitEnvironment } from "./git-environment.ts";

const repo = join(__dirname, "..");
const fixture = (name: string) => readFileSync(join(__dirname, "fixtures", "at18", name));
const crosswalk = JSON.parse(readFileSync(join(repo, specPaths.crosswalk_ref), "utf8")) as {
  rows: { story_id: string; success_closure_slice_ids: TB[] }[];
  family_entry_links: { id: string; success_closure_slice_ids: TB[] }[];
  detailed_acceptance_links: { id: string; success_closure_slice_ids: TB[] }[];
};
type TB = keyof typeof tbTickets;
const tbIds = Object.keys(tbTickets) as TB[];
const base = "a".repeat(40);
const head = "b".repeat(40);
const generatedAt = "2026-11-20T00:00:01Z";
const manifest: DeliveryManifest = {
  schemaVersion: 1, ticket: 1391, base, head, productDiff: [], reports: [], requiredReports: [],
  checks: [], requiredChecks: [], reviews: [], scan: { status: "not_run" },
};
const makeBytes = (value: unknown) => Buffer.from(JSON.stringify(value));

function setup() {
  const bytes = new Map(Object.values(specPaths).map(path => [path, readFileSync(join(repo, path))] as [string, Buffer]));
  const records = parseJsonObject(fixture("records.json"));
  const external = new Map<string, Buffer>();
  const externalBlob = (name: string, payload: unknown): ArtifactRef => {
    const path = `/evidence/${name}.json`;
    const contents = makeBytes(payload);
    external.set(path, contents);
    return { storage: "external", path, sha256: byteSha256(contents), commit: null, ticket: 1360,
      base, head, bounded_scope: "合成证据" };
  };
  const artifact = (name: string, payload = records[name]): ArtifactRef => {
    const path = `evidence/${name}.json`;
    const contents = makeBytes(payload);
    bytes.set(path, contents);
    return { storage: "in_repo", path, sha256: byteSha256(contents), commit: head, ticket: null, base: null,
      head: null, bounded_scope: "合成证据" };
  };
  const runtime = externalBlob("runtime", records.runtime);
  const upstreamPath = "/evidence/delivery-manifest.json";
  external.set(upstreamPath, makeBytes({ ...manifest, ticket: 1360, externalReportsRoot: "/evidence", reports: [{
    storage: runtime.storage, path: runtime.path, sha256: runtime.sha256, ticket: runtime.ticket, base: runtime.base, head: runtime.head,
  }] }));
  const migration = artifact("migration");
  const other = artifact("other");
  const venue_permission_document = artifact("venuePermissionDocument", { example: "合成场所文档原件" });
  const venue_permission_source = artifact("permissionSources", {
    ...records.permissionSources as object, sha256: venue_permission_document.sha256,
  });
  const confirm = (...evidence_refs: ArtifactRef[]) => ({ outcome: "CONFIRMED" as const, evidence_refs });
  const observations: At18Observations = {
    production_enabled: false, bounded_domain_statement: "合成实验槽位启用；P2 未启用。",
    external_manifests: [upstreamPath],
    destinations: [],
    tb_summaries: [],
    legacy_dispositions: legacyTickets.map(ticket => ({
      ticket, disposition: "合成去向", ticket_state: ticket === 942 || ticket === 1282 ? "CLOSED" : "OPEN",
      disposition_proof: confirm(other),
      ...(ticket === 1279 && { own_remaining_only: confirm(other), not_released: confirm(other) }),
    })),
    coverage: [],
    permission: { experiment: {
      authorization_declaration: artifact("authorization"), runtime_verification: artifact("startup"),
      venue_permission_source, venue_permission_document, capability_record: artifact("capability"), venue_profile: artifact("profile"),
    } },
    migration: { experiment: {
      no_lost_rights: true, no_duplicated_capital: true, no_dual_write: true, no_resend: true,
      non_empty_run: confirm(migration),
    } },
    post_gate: { experiment: { status: "TRIGGERED_AND_ENABLED", gate_reached_event: artifact("gate"),
      parameter_version: artifact("version"), first_activation: artifact("activation") } },
    unexecuted: [
      ["ISSUE_1561_P2_FIRST_SEND", "production"], ["ADR_0036_POST_GATE_PRODUCTION", "production"],
      ["ISSUE_1320_HEAVY_MEASUREMENT", "simulation"],
    ].map(([obligation, evidence_class]) => ({
      obligation, evidence_class: evidence_class as "production" | "simulation",
      blocker_or_gap: "合成保留项", reason: "合成夹具未启用或未完成", required: false,
    })),
  };
  const ci_runs = [{ workflow: "ci-ok", run_id: 1, head_sha: head, conclusion: "SUCCESS" as const, url: "https://example.test/ci/1" }];
  const final_reviews = [{ reviewer: "独立审查者", reviewed_head: head, verdict: "PASS" as const, artifact: other }];
  for (let id = 1; id <= 6; id++) observations.destinations!.push({
    id, tickets: [{ ticket: 1360, scope: "合成 Destination" }], main_sha: head, ci_runs, commits: [head],
    independent_reviews: final_reviews, evidence_by_class: { experiment: [runtime] }, downstream_status: [],
    obligations: confirm(runtime),
  });
  for (const tb_id of tbIds) {
    const child = 10_000 + tbTickets[tb_id];
    const tb11 = tb_id === "TB-11";
    observations.tb_summaries.push({
      tb_id, ticket_state: tb11 ? "OPEN" : "CLOSED", expected_slice_tickets: tb11 ? undefined : [child],
      slices: tb11 ? [1391, 1403].map(ticket => ({ ticket, state: "OPEN", main_sha: head }))
        : [{ ticket: child, state: "CLOSED", main_sha: head }],
      main_sha: head, ci_runs, final_reviews,
      ...(tb11 ? {} : {
        evidence_by_class: { experiment: tb_id === "TB-10" ? [migration] : [runtime] },
        entity_reports: [other], obligations: confirm(runtime),
      }),
    });
  }
  function coverage(kind: "story" | "family" | "detail", id: string, closes: TB[]) {
    observations.coverage!.push({
      kind, id, slices: closes.filter(tb_id => tb_id !== "TB-11").map(tb_id => ({ tb_id, proof: confirm(other) })),
    });
  }
  crosswalk.rows.forEach(row => coverage("story", row.story_id, row.success_closure_slice_ids));
  crosswalk.family_entry_links.forEach(row => coverage("family", row.id, row.success_closure_slice_ids));
  crosswalk.detailed_acceptance_links.forEach(row => coverage("detail", row.id, row.success_closure_slice_ids));

  // 合成独审者只认这次冻结的原字节和对应原件位置，不读后续被改写的 observations。
  const provenance = new Map<string, EvidenceFinding[]>();
  const attach = (ref: ArtifactRef, item: EvidenceClaim, verdict: EvidenceFinding["verdict"] = "PASS",
    execution: EvidenceFinding["execution"] = "EXECUTED") => {
    const key = `${ref.path}:${ref.sha256}`;
    const contents = provenance.get(key) ?? [];
    contents.push({ claim: structuredClone(item), verdict, execution, pointer: `/fixture/${contents.length}` });
    provenance.set(key, contents);
  };
  const destinations = parseJsonObject(bytes.get(specPaths.coverage_input_ref)!).destinations as { ordinal: number; verbatim: string }[];
  for (const d of observations.destinations!) {
    const id = `DST-0${d.id}`;
    attach(runtime, claim("runtime", id, "实际运行", "experiment", [head]));
    attach(runtime, claim("destination", id, "完整义务", undefined, {
      obligation: destinations.find(record => record.ordinal === d.id)!.verbatim,
      products: [head], tickets: d.tickets!, downstream_status: [], remaining_obligations: [],
    }));
    attach(other, claim("review", id, "非作者审查最终产品", undefined, { reviewer: final_reviews[0].reviewer, commit: head }));
  }
  const rosters = new Map<number, { state: "OPEN" | "CLOSED"; slices: { ticket: number; state: "OPEN" | "CLOSED" }[] }>();
  for (const tb of observations.tb_summaries) {
    const ticket = tbTickets[tb.tb_id];
    rosters.set(ticket, { state: tb.ticket_state, slices: tb.slices!.map(({ ticket, state }) => ({ ticket, state })) });
    attach(other, claim("review", tb.tb_id, "非作者审查最终产品", undefined, { reviewer: final_reviews[0].reviewer, commit: head }));
    if (tb.tb_id === "TB-11") continue;
    attach(tb.evidence_by_class!.experiment![0], claim("runtime", tb.tb_id, "实际运行", "experiment", [head]));
    attach(other, claim("tb", tb.tb_id, "本 TB 实体报告", undefined, { ticket, products: [head] }));
    attach(runtime, claim("tb", tb.tb_id, "全部外部行为", undefined,
      { ticket, products: [head], slices: tb.slices!, ticket_state: tb.ticket_state }));
  }
  for (const row of observations.coverage!) for (const slice of row.slices) {
    const scope = `spec_coverage.${row.kind}:${row.id}`;
    const preserve = row.kind === "family" && ["OE41", "OE45"].includes(row.id);
    attach(other, claim("coverage", scope, preserve ? "排除与防混用" : "完成子义务",
      undefined, { kind: row.kind, id: row.id, slice: slice.tb_id, main_sha: head }));
  }
  const permission = observations.permission!.experiment!;
  const binding = { profile: permission.venue_profile!.sha256, capability: permission.capability_record!.sha256 };
  for (const [key, ref] of Object.entries(permission)) attach(ref, claim("permission", "DST-05.experiment", key, "experiment", binding));
  for (const key of ["非空运行和回退", "no_lost_rights", "no_duplicated_capital", "no_dual_write", "no_resend"]) {
    attach(migration, claim("migration", "migration_invariants.experiment", key, "experiment"));
  }
  const post = observations.post_gate!.experiment!;
  for (const key of ["gate_reached_event", "parameter_version", "first_activation"] as const) {
    attach(post[key]!, claim("post_gate", "post_gate_records.experiment", key, "experiment"));
  }
  for (const row of observations.legacy_dispositions) {
    const scope = `legacy:#${row.ticket}`;
    const facts = { ticket: row.ticket, disposition: row.disposition, ticket_state: row.ticket_state, remaining_obligations: [] };
    attach(other, claim("legacy", scope, legacyRules[row.ticket as keyof typeof legacyRules], undefined, facts), "PASS", "RECONCILED");
    if (row.ticket === 1279) {
      attach(other, claim("legacy", scope, "剩余项仅属 #1279", undefined, []));
      attach(other, claim("legacy", scope, "未解除前置也未宣布试运行放行", undefined, facts));
    }
  }
  const independentCi = structuredClone(ci_runs);
  const read = (entries: Map<string, Buffer>, path: string) => {
    const found = entries.get(path);
    if (!found) throw new Error("fixture missing");
    return found;
  };
  return {
    bytes, external, artifact, observations, upstreamPath, attach,
    run: (originMain = head, mergedMainCommit?: (candidate: string) => string | undefined) => generateAt18({
      manifest, observations, originMain, generatedAt, inputBundlePath: "/evidence/out/at18-input-bundle.json",
      source: {
        readExternal: path => read(external, path),
        readBlob: (commit, path) => { assert.equal(commit, head); return read(bytes, path); },
        isAncestor: (commit, tip) => commit === head && tip === head,
        mergedMainCommit,
        productionEnabled: () => false,
        tbRoster: id => rosters.get(id),
        requiredCi: () => independentCi,
        findings: (ref, contents) => provenance.get(`${ref.path}:${byteSha256(contents)}`) ?? [],
      },
    }),
  };
}

function requireFailure(report: At18Report, scope: string, check: string) {
  assert.equal(report.overall_result, "FAIL");
  assert.ok(report.failed_checks.some(f => f.scope === scope && f.check_id === check),
    `缺 ${scope} ${check}；实得 ${report.failed_checks.slice(0, 8).map(f => `${f.scope}.${f.check_id}`).join(", ")}`);
}

test("AT-18 证据齐全才 PASS；TB-11 开票状态与每条覆盖正确保留", () => {
  const f = setup();
  f.observations.coverage = f.observations.coverage!.filter(row => row.id !== "US-ENG-10");
  const { report, inputBundle } = f.run();
  assert.deepEqual(report.failed_checks, []);
  assert.equal(report.overall_result, "PASS");
  assert.deepEqual(Object.keys(report).length, 18);
  assert.deepEqual(Object.keys(inputBundle!).length, 10);
  assert.deepEqual(
    [report.spec_coverage.stories.length, report.spec_coverage.families.length, report.spec_coverage.details.length],
    [97, 345, 496],
  );
  assert.deepEqual(report.spec_coverage.families.filter(f => f.entry_mode === "OUT_OF_SCOPE_PRESERVE")
    .map(f => [f.id, f.status]), [["OE41", "PRESERVED_BOUNDARY"], ["OE45", "PRESERVED_BOUNDARY"]]);
  assert.equal(report.spec_coverage.families.find(f => f.id === "OE42")?.status, "VERIFIED");
  const tb11 = report.tb_summaries[10];
  assert.equal(tb11.ticket_state, "OPEN");
  assert.equal(tb11.gate_satisfied, true);
  assert.deepEqual(tb11.entity_reports, []);
  assert.deepEqual(tb11.evidence_by_class, { simulation: [], experiment: [], production: null });
  assert.deepEqual(report.spec_coverage.stories.find(row => row.story_id === "US-ENG-10")?.evidence_refs,
    [tb11.input_bundle]);
  for (const [i, story] of report.spec_coverage.stories.entries()) {
    assert.equal(story.story_id, crosswalk.rows[i].story_id);
    if (crosswalk.rows[i].success_closure_slice_ids.includes("TB-11")) assert.deepEqual(story.evidence_refs.at(-1), tb11.input_bundle);
  }
  assert.equal(report.post_gate_records.experiment?.first_activation_known_at, "2026-11-20T00:00:00.000003Z");
});

const missingEvidence: [string, string, (f: ReturnType<typeof setup>) => void][] = [
  ["report", "ORIGIN_MAIN_HEAD", () => {}],
  ["DST-01", "RUNTIME_EVIDENCE", f => { delete f.observations.destinations![0].evidence_by_class; }],
  ["DST-01", "INDEPENDENT_REVIEW", f => { delete f.observations.destinations![0].independent_reviews; }],
  ["DST-01", "REQUIRED_CI", f => { delete f.observations.destinations![0].ci_runs; }],
  ["DST-01", "MAIN_COMMIT", f => { delete f.observations.destinations![0].main_sha; }],
  ["DST-01", "DESTINATION_OBLIGATIONS", f => { delete f.observations.destinations![0].obligations; }],
  ["TB-02", "TB_NOT_CLOSED", f => { f.observations.tb_summaries[1].ticket_state = "OPEN"; }],
  ["TB-02", "ENTITY_REPORTS", f => { delete f.observations.tb_summaries[1].entity_reports; }],
  ["TB-11.#1403", "MAIN_COMMIT", f => { f.observations.tb_summaries[10].slices![1].main_sha = null; }],
  ["DST-05.experiment", "AUTHORIZATION_DECLARATION", f => { delete f.observations.permission!.experiment!.authorization_declaration; }],
  ["DST-05.experiment", "VENUE_PERMISSION_FACT", f => { delete f.observations.permission!.experiment!.venue_permission_source; }],
  ["DST-05.experiment", "VENUE_PERMISSION_FACT", f => { delete f.observations.permission!.experiment!.venue_permission_document; }],
  ["DST-05.experiment", "RUNTIME_VERIFICATION", f => { delete f.observations.permission!.experiment!.runtime_verification; }],
  ["DST-05.experiment", "CAPABILITY_HASH", f => { delete f.observations.permission!.experiment!.capability_record; }],
  ["DST-05.experiment", "CAPABILITY_HASH", f => { delete f.observations.permission!.experiment!.venue_profile; }],
  ["migration_invariants.experiment", "NO_DUAL_WRITE", f => { f.observations.migration!.experiment!.no_dual_write = false; }],
  ["post_gate_records.experiment", "POST_GATE_EVENT", f => { delete f.observations.post_gate!.experiment!.gate_reached_event; }],
  ["post_gate_records.experiment", "POST_GATE_VERSION", f => { delete f.observations.post_gate!.experiment!.parameter_version; }],
  ["post_gate_records.experiment", "POST_GATE_ACTIVATION", f => { delete f.observations.post_gate!.experiment!.first_activation; }],
  ["legacy:#942", "LEGACY_DISPOSITION_EVIDENCE", f => { delete f.observations.legacy_dispositions[0].disposition_proof; }],
  ["legacy:#1279", "ISSUE_1279_OWN_REMAINING_ONLY", f => { delete f.observations.legacy_dispositions.at(-1)!.own_remaining_only; }],
  ["legacy:#1320", "ISSUE_1320_HEAVY_MEASUREMENT", f => { f.observations.unexecuted!.pop(); }],
  ["spec_coverage.family:OE42", "COVERAGE_TB-09", f => {
    const oe42 = f.observations.coverage!.find(entry => entry.kind === "family" && entry.id === "OE42")!;
    oe42.slices = oe42.slices.filter(slice => slice.tb_id !== "TB-09");
  }],
  ["DST-01", "ARTIFACT_MANIFEST_BINDING", f => { delete f.observations.external_manifests; }],
];

test("AT-18 缺证逐项留红，不把必需成功路径补成默认值", () => {
  for (const [scope, check, change] of missingEvidence) {
    const f = setup();
    change(f);
    requireFailure(f.run(check === "ORIGIN_MAIN_HEAD" ? base : head).report, scope, check);
  }
});
test("AT-18 输入包缺任一规范文件不生成输入包，报告继续写可核字段", () => {
  const obligations = setup().run().report.destinations.map(d => d.obligation);
  for (const key of ["spec_ref", "crosswalk_ref", "coverage_input_ref"] as const) {
    const f = setup();
    f.bytes.delete(specPaths[key]);
    const out = f.run();
    assert.equal(out.inputBundle, null);
    assert.equal(out.report.head, head);
    assert.equal(out.report.tb_summaries[10].input_bundle, null);
    assert.equal(out.report.spec_coverage.stories.length, key === "crosswalk_ref" ? 0 : 97);
    assert.deepEqual(out.report.destinations.map(d => d.obligation), obligations);
    requireFailure(out.report, `input_bundle.${key}`, "FILE_READ");
    requireFailure(out.report, "TB-11", "INPUT_BUNDLE_MISSING");
  }
});
test("AT-18 crosswalk 读取成功但投影 schema 失败，保留字节摘要，不捏造覆盖行", () => {
  const f = setup();
  const invalid = Buffer.from('{"rows":[]}');
  f.bytes.set(specPaths.crosswalk_ref, invalid);
  const { report } = f.run();
  requireFailure(report, "spec_coverage.family_entry_links", "SCHEMA");
  assert.deepEqual(report.spec_coverage, { crosswalk_sha256: byteSha256(invalid), stories: [], families: [], details: [] });
  const oneBad = setup();
  const source = parseJsonObject(oneBad.bytes.get(specPaths.crosswalk_ref)!);
  source.family_entry_links = "invalid";
  oneBad.bytes.set(specPaths.crosswalk_ref, makeBytes(source));
  const partial = oneBad.run().report;
  requireFailure(partial, "spec_coverage.family_entry_links", "SCHEMA");
  assert.deepEqual([partial.spec_coverage.stories.length, partial.spec_coverage.families.length,
    partial.spec_coverage.details.length], [97, 0, 496]);
});
test("AT-18 OE42 不改分类，覆盖输入处分失配时单独留红", () => {
  const f = setup();
  const raw = parseJsonObject(f.bytes.get(specPaths.coverage_input_ref)!);
  const groups = raw.old_entry_groups as { id: string; effective_disposition: { kind: string } }[];
  groups.find(group => group.id === "OE42")!.effective_disposition.kind = "DIFFERENT";
  f.bytes.set(specPaths.coverage_input_ref, makeBytes(raw));
  const { report } = f.run();
  requireFailure(report, "spec_coverage.family:OE42", "COVERAGE_OE42_DISPOSITION");
  const row = report.spec_coverage.families.find(f => f.id === "OE42");
  assert.equal(row?.entry_mode, "REQUIRED");
  assert.equal(row?.status, "FAIL");
});
test("AT-18 已批准但未触发的边界须有本条证据，不能用全局未执行登记代替", () => {
  const f = setup();
  const row = f.observations.coverage!.find(item => item.kind === "story" && item.id === "US-DST-03")!;
  const evidence = f.artifact("bounded", { example: "本条的 P2 专属子义务" });
  f.attach(evidence, claim("deferral", "spec_coverage.story:US-DST-03", "获准延期本子义务", "production",
    { kind: "story", id: "US-DST-03", gate: "ISSUE_1561_P2_FIRST_SEND" }), "PASS", "RECONCILED");
  row.deferred_gates = [{ gate: "ISSUE_1561_P2_FIRST_SEND", boundary: { outcome: "CONFIRMED", evidence_refs: [evidence] } }];
  const { report } = f.run();
  assert.equal(report.overall_result, "PASS");
  assert.equal(report.spec_coverage.stories.find(row => row.story_id === "US-DST-03")?.status, "BOUNDED_DEFERRED");
  row.deferred_gates[0].boundary.evidence_refs = [];
  requireFailure(f.run().report, "spec_coverage.story:US-DST-03", "COVERAGE_DEFERRED_BOUNDARY");
});
test("AT-18 squash 只证明仓外 artifact 归属，不能推断最终产品独评或 CI 等价", () => {
  const f = setup();
  const candidate = "c".repeat(40);
  f.observations.tb_summaries[10].ci_runs![0].head_sha = candidate;
  f.observations.tb_summaries[10].final_reviews![0].reviewed_head = candidate;
  const { report } = f.run(head, code => code === candidate ? head : undefined);
  requireFailure(report, "TB-11.#1403", "SLICE_REQUIRED_CI");
  requireFailure(report, "TB-11.#1403", "SLICE_INDEPENDENT_REVIEW");
});
test("AT-18 上游 manifest 各步骤失败有独立编号", () => {
  for (const [bytes, step] of [
    [undefined, "FILE_READ"], [Buffer.from("{"), "JSON_PARSE"], [Buffer.from('{"value":1e400}'), "JCS_CANONICALIZE"],
    [Buffer.from('{"ticket":1391}'), "SCHEMA"],
  ] as const) {
    const f = setup();
    if (bytes) f.external.set(f.upstreamPath, bytes);
    else f.external.delete(f.upstreamPath);
    const out = f.run();
    requireFailure(out.report, `external_manifests:${f.upstreamPath}`, step);
    assert.deepEqual(out.inputBundle!.external_manifests, []);
  }
});

const reversed = (value: unknown): unknown => Array.isArray(value) ? value.map(reversed)
  : value !== null && typeof value === "object"
    ? Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, reversed(item)])) : value;
const withHash = <T extends Record<string, unknown>>(value: T) => ({ ...value, content_hash: computeContentHash(value) });
test("AT-18 content_hash 覆盖顶层所有语义字段及嵌套字段，忽略键序与自身字段", () => {
  const out = setup().run();
  for (const document of [out.report, out.inputBundle!]) {
    const old = document.content_hash;
    assert.equal(computeContentHash(reversed(document) as Record<string, unknown>), old);
    assert.equal(computeContentHash({ ...document, content_hash: "不同" }), old);
    for (const key of Object.keys(document).filter(key => key !== "content_hash")) {
      assert.notEqual(computeContentHash({ ...document, [key]: "不同" }), old, key);
    }
  }
  const report = structuredClone(out.report);
  report.destinations[0].tickets[0].scope += "不同";
  assert.notEqual(computeContentHash(report), out.report.content_hash);
  const bundle = structuredClone(out.inputBundle!);
  bundle.crosswalk_ref.bounded_scope += "不同";
  assert.notEqual(computeContentHash(bundle), out.inputBundle!.content_hash);
});

test("AT-18 交付 schema 拒绝未知键、错版本、错摘要和不合法 PASS/FAIL 组合", () => {
  const out = setup().run();
  for (const [schema, doc] of [[at18InputBundleSchema, out.inputBundle!], [at18ReportSchema, out.report]] as const) {
    assert.equal(schema.safeParse(doc).success, true);
    assert.equal(schema.safeParse(withHash({ ...doc, extra: 1 })).success, false);
    assert.equal(schema.safeParse(withHash({ ...doc, schema_version: doc.schema_version.replace("/1", "/2") })).success, false);
    assert.equal(schema.safeParse({ ...doc, content_hash: "f".repeat(64) }).success, false);
  }
  const extraNested = { ...out.inputBundle!, spec_ref: { ...out.inputBundle!.spec_ref, extra: true } };
  assert.equal(at18InputBundleSchema.safeParse(withHash(extraNested)).success, false);
  const hidden = structuredClone(out.inputBundle!);
  Object.defineProperty(hidden.spec_ref, "__proto__", { value: true, enumerable: true });
  assert.equal(at18InputBundleSchema.safeParse(hidden).success, false);
  const failedCheck = { scope: "a", check_id: "A", detail: "a", evidence_ref: null };
  assert.equal(at18ReportSchema.safeParse(withHash({ ...out.report, failed_checks: [failedCheck] })).success, false);
  assert.equal(at18ReportSchema.safeParse(withHash({ ...out.report, overall_result: "FAIL" })).success, false);
  const dst = [...out.report.destinations].reverse();
  assert.equal(at18ReportSchema.safeParse(withHash({ ...out.report, destinations: dst })).success, false);
  assert.equal(artifactRefSchema.safeParse({ ...out.inputBundle!.spec_ref, commit: null }).success, false);
});

test("AT-18 JCS 按 UTF-16 排键、按 ECMAScript 写数值，并保留 JSON 转义", () => {
  assert.equal(canonicalizeJcs(parseJsonObject(fixture("jcs.json"))),
    String.raw`{"\r":2,"1":3,"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27,0,0.000001,1e-7],"string":"€$\u000f\nA'B\"\\\"/","":1,"€":0,"😀":4,"דּ":5}`);
});
test("AT-18 严格 JSON 在 JCS 前拒绝重键、坏 UTF-8 和非对象；JCS 拒绝溢出与孤立代理码点", () => {
  for (const bytes of [Buffer.from(String.raw`{"a":[{"a":1,"\u0061":2}]}`), Buffer.from([123, 34, 255, 34, 58, 49, 125]), Buffer.from("[]")]) {
    assert.throws(() => parseJsonObject(bytes), { check_id: "JSON_PARSE" });
  }
  for (const source of ['{"n":1e400}', String.raw`{"bad":"\ud800"}`, String.raw`{"\udbff":"bad"}`]) {
    assert.throws(() => deriveJson(Buffer.from(source), z.object({})), { check_id: "JCS_CANONICALIZE" });
    assert.throws(() => computeContentHash(parseJsonObject(Buffer.from(source))), { check_id: "JCS_CANONICALIZE" });
  }
});

test("AT-18 CLI 自身 manifest 缺失或不合型时 BLOCKED，退出 1 且不落文件", t => {
  const work = realpathSync(mkdtempSync(join(tmpdir(), "at18-cli-")));
  t.after(() => rmSync(work, { recursive: true, force: true }));
  const missing = join(work, "manifest-absent.json");
  const bad = join(work, "manifest-invalid.json");
  writeFileSync(bad, '{"unexpected":true}');
  for (const [manifest, code] of [[missing, "MANIFEST_UNREADABLE"], [bad, "INVALID_MANIFEST"], ["", "MANIFEST_UNREADABLE"]]) {
    const child = spawnSync(process.execPath, ["--import", "tsx", ".sandcastle/at18-report.mts",
      repo, manifest, "NOT_NEEDED", work], { cwd: repo, encoding: "utf8" });
    assert.equal(child.status, 1, child.stderr);
    assert.equal(JSON.parse(child.stdout).status, "BLOCKED");
    assert.equal(JSON.parse(child.stdout).diagnostics[0].code, code);
    assert.deepEqual(readdirSync(work), ["manifest-invalid.json"]);
  }
});

const confirmed = (ref: ArtifactRef) => ({ outcome: "CONFIRMED" as const, evidence_refs: [ref] });

test("AT-18 共享原件只销它实际覆盖的行；排除或未执行的子义务不能借它通过", () => {
  const f = setup();
  const only001 = f.artifact("one-story-only", { covers: ["US-ST-001"], excludes: ["US-ST-002"] });
  for (const row of f.observations.coverage!.filter(row => ["US-ST-001", "US-ST-002"].includes(row.id))) {
    for (const slice of row.slices) {
      if (row.id === "US-ST-001") f.attach(only001, claim("coverage", "spec_coverage.story:US-ST-001",
        "完成子义务", undefined, { kind: "story", id: row.id, slice: slice.tb_id, main_sha: head }));
      slice.proof = confirmed(only001);
    }
  }
  const { report } = f.run();
  assert.equal(report.spec_coverage.stories[0].status, "VERIFIED");
  assert.equal(report.spec_coverage.stories[1].status, "FAIL");
  requireFailure(report, "spec_coverage.story:US-ST-002", "COVERAGE_TB-01");
  const finding = claim("coverage", "spec_coverage.story:US-ST-001", "完成子义务", undefined,
    { kind: "story", id: "US-ST-001", slice: "TB-01", main_sha: head });
  f.attach(only001, finding, "FAIL");
  requireFailure(f.run().report, "spec_coverage.story:US-ST-001", "COVERAGE_TB-01");
});

test("AT-18 DST-06 的原件不能给 DST-01 销项；报告保留所用原件定位", () => {
  const f = setup();
  const before = f.run().report;
  assert.ok(before.destinations[0].evidence_by_class.experiment.some(ref => ref.bounded_scope.startsWith("/fixture/")));
  const wrong = f.artifact("only-dst06", { applies_only_to: "DST-06", applies_to_dst01: false });
  f.observations.destinations![0].obligations = confirmed(wrong);
  const { report } = f.run();
  requireFailure(report, "DST-01", "DESTINATION_OBLIGATIONS");
  assert.ok(report.failed_checks.some(c => c.evidence_ref?.path === wrong.path));
  assert.notEqual(report.content_hash, before.content_hash);
});

test("AT-18 实体报告需支持当前 TB，且 AT-18 文件须通过内部摘要", () => {
  const f = setup();
  const bad = f.artifact("bad-bundle", { ...f.run().inputBundle, content_hash: "0".repeat(64) });
  f.observations.tb_summaries[1].entity_reports = [bad];
  requireFailure(f.run().report, "TB-02", "ENTITY_REPORT_CONTENT_INVALID");
  f.observations.tb_summaries[1].entity_reports = [f.artifact("another-tb", { tb: "TB-03" })];
  requireFailure(f.run().report, "TB-02", "ENTITY_REPORT_SCOPE");
});

test("AT-18 旧祖先 CI/独评、捏造的当前 CI 和无非作者绑定的独评都不销项", () => {
  const f = setup();
  const tb = f.observations.tb_summaries[1];
  const old = "c".repeat(40);
  tb.ci_runs = [{ ...tb.ci_runs![0], head_sha: old }];
  tb.final_reviews = [{ ...tb.final_reviews![0], reviewed_head: old }];
  const { report } = f.run(head, sha => sha === old ? head : undefined);
  requireFailure(report, "TB-02", "REQUIRED_CI");
  requireFailure(report, "TB-02", "INDEPENDENT_REVIEW");
  tb.ci_runs = [{ ...tb.ci_runs![0], head_sha: head, run_id: 84 }];
  tb.final_reviews = [{ ...tb.final_reviews[0], reviewed_head: head,
    artifact: f.artifact("author-reviewed", { reviewer_is_author: true }) }];
  requireFailure(f.run().report, "TB-02", "REQUIRED_CI");
  requireFailure(f.run().report, "TB-02", "INDEPENDENT_REVIEW");
});

test("AT-18 应交子票由 tracker 决定，TB-11 的正式生成阶段要求三票 OPEN", () => {
  const f = setup();
  const tb = f.observations.tb_summaries[1];
  tb.expected_slice_tickets = [1373];
  tb.slices = [{ ticket: 1373, state: "CLOSED", main_sha: head }];
  const tb11 = f.observations.tb_summaries[10];
  tb11.ticket_state = "CLOSED";
  tb11.slices!.forEach(slice => { slice.state = "CLOSED"; });
  const { report } = f.run();
  requireFailure(report, "TB-02", "IMPLEMENTATION_SLICES");
  requireFailure(report, "TB-02", "TB_TRACKER_SCOPE");
  requireFailure(report, "TB-11", "TB11_STAGE_STATE");
});

test("AT-18 启动 FAIL、空仓未跑以及单向证据类冒充都不能通过", () => {
  const f = setup();
  f.observations.permission!.experiment!.runtime_verification = f.artifact("startup-failed", { steps_4_through_7: "FAIL" });
  const migration = f.artifact("empty-migration", { positions: [], open_orders: [], test_executed: false });
  f.observations.migration!.experiment!.non_empty_run = confirmed(migration);
  f.observations.tb_summaries[9].evidence_by_class!.experiment = [migration];
  const simulation = f.artifact("simulated-venue", { evidence_class: "simulation", venue_run: false });
  f.attach(simulation, claim("runtime", "TB-08", "实际运行", "simulation", [head]));
  f.observations.tb_summaries[7].evidence_by_class!.experiment = [simulation];
  const { report } = f.run();
  requireFailure(report, "DST-05.experiment", "RUNTIME_VERIFICATION_SUPPORT");
  requireFailure(report, "migration_invariants.experiment", "NON_EMPTY_MIGRATION");
  requireFailure(report, "TB-08", "RUNTIME_EVIDENCE_SCOPE");
  assert.equal(report.destinations[4].result, "FAIL");
  assert.equal(report.migration_invariants.experiment?.no_lost_rights, false);
});

test("AT-18 未触达必须有同槽原件；TestOnly 触达不得激活，未适用的 P2 门不能延期", () => {
  const f = setup();
  const source = f.artifact("already-active", { profile_id: "P1-fixture", evidence_class: "experiment",
    growth_enabled: true, gate_reached: true });
  f.observations.post_gate!.experiment = { status: "NOT_TRIGGERED", non_activation: confirmed(source) };
  f.observations.unexecuted!.push({ obligation: "ADR_0036_POST_GATE_EXPERIMENT", required: false,
    reason: "未触达", blocker_or_gap: "未触达", evidence_class: "experiment" });
  requireFailure(f.run().report, "post_gate_records.experiment", "POST_GATE_NON_ACTIVATION");

  const g = setup();
  const gate = g.artifact("test-gate", { id: "gate", profile_id: "P1-fixture", evidence_class: "experiment",
    known_at: "2026-11-20T00:00:00.000001Z", kind: "SimulatedGateReached", mode: "TestOnly" });
  g.observations.post_gate!.experiment!.gate_reached_event = gate;
  const row = g.observations.coverage!.find(e => e.id === "US-ST-001")!;
  row.deferred_gates = [{ gate: "ISSUE_1561_P2_FIRST_SEND",
    boundary: confirmed(g.artifact("not-applicable", { story: row.id, p2_first_send_applies: false })) }];
  const { report } = g.run();
  requireFailure(report, "post_gate_records.experiment", "POST_GATE_GATE_REACHED_EVENT_SUPPORT");
  requireFailure(report, "spec_coverage.story:US-ST-001", "COVERAGE_DEFERRED_BOUNDARY");
});

test("AT-18 七张旧票逐一抵挡反处分，零年样本不能销 #1320", () => {
  const f = setup();
  const inverted = {
    942: "恢复强平实验", 1096: "未核退场即删除", 1282: "旧实验代替新程序验收",
    1304: "报告器未核实即关闭", 1319: "旧简化链作为完整发送和隔离证据",
    1320: "单个组件样例等同七标的十年全量", 1279: "已宣布试运行放行",
  };
  for (const l of f.observations.legacy_dispositions) l.disposition = inverted[l.ticket as keyof typeof inverted];
  const item1279 = f.observations.legacy_dispositions.at(-1)!;
  item1279.remaining_obligations = ["#1323 Destination ⑥ 尚未完成"];
  item1279.not_released = confirmed(f.artifact("trial-released", { trial_released: true }));
  const item1320 = f.observations.legacy_dispositions[5];
  item1320.ticket_state = "CLOSED";
  item1320.heavy_resolved = confirmed(f.artifact("zero-year", { years: 0, instruments: 1 }));
  f.observations.unexecuted!.pop();
  const { report } = f.run();
  for (const ticket of legacyTickets) requireFailure(report, `legacy:#${ticket}`, "LEGACY_DISPOSITION_EVIDENCE");
  requireFailure(report, "legacy:#1279", "ISSUE_1279_OWN_REMAINING_ONLY");
  requireFailure(report, "legacy:#1279", "ISSUE_1279_NOT_RELEASED");
  requireFailure(report, "legacy:#1320", "ISSUE_1320_HEAVY_RESOLUTION_EVIDENCE");
  assert.ok(report.legacy_dispositions.every(l => !l.disposition_valid));
});

test("AT-18 任一组同时减掉原始覆盖行和观察仍失败；坏行不抹掉其他 96 个", () => {
  for (const [kind, field] of [["story", "rows"], ["family", "family_entry_links"],
    ["detail", "detailed_acceptance_links"]] as const) {
    const f = setup();
    const cross = parseJsonObject(f.bytes.get(specPaths.crosswalk_ref)!);
    const removed = (cross[field] as { id?: string; story_id?: string }[]).pop()!;
    f.observations.coverage = f.observations.coverage!.filter(o => o.kind !== kind || o.id !== (removed.id ?? removed.story_id));
    f.bytes.set(specPaths.crosswalk_ref, makeBytes(cross));
    const { report } = f.run();
    requireFailure(report, "spec_coverage", "CROSSWALK_ALIGNMENT");
    requireFailure(report, "legacy:#1279", "ISSUE_1279_GRAPH_OBLIGATIONS");
    assert.equal(report.legacy_dispositions.at(-1)!.disposition_valid, false);
  }
  const f = setup();
  const cross = parseJsonObject(f.bytes.get(specPaths.crosswalk_ref)!);
  delete (cross.rows as { story_id?: string }[])[2].story_id;
  f.bytes.set(specPaths.crosswalk_ref, makeBytes(cross));
  const { report } = f.run();
  requireFailure(report, "spec_coverage.rows[2]", "SCHEMA");
  assert.deepEqual(report.spec_coverage.stories.map(r => r.story_id),
    crosswalk.rows.filter((_, index) => index !== 2).map(r => r.story_id));
  assert.equal(report.spec_coverage.families.length, 345);
  assert.equal(report.spec_coverage.details.length, 496);
});

test("AT-18 GitHub 合入查询只接受精确 head、main 和 merged=true", () => {
  const prHead = "c".repeat(40);
  for (const [merged, topic, exact, expected] of [
    [true, "main", prHead, head], [false, "main", prHead, undefined],
    [true, "other", prHead, undefined], [true, "main", "d".repeat(40), undefined],
  ] as const) {
    const github = at18GitHub("https://github.com/Newchanlun/NewChanlun.git", (...args) =>
      args.includes("--slurp") ? [[{ number: 7, head: { sha: prHead }, base: { ref: "main" } }]] :
        { merged, base: { ref: topic }, head: { sha: exact }, merge_commit_sha: head });
    assert.equal(github.mergedMainCommit?.(prHead), expected);
  }
});

test("AT-18 缺一个 Destination 固定条目时保留 SPEC 已知义务，但不得通过", () => {
  const f = setup();
  const input = parseJsonObject(f.bytes.get(specPaths.coverage_input_ref)!);
  (input.destinations as unknown[]).pop();
  f.bytes.set(specPaths.coverage_input_ref, makeBytes(input));
  const { report } = f.run();
  assert.equal(report.destinations[5].id, 6);
  assert.ok(report.destinations[5].obligation);
  requireFailure(report, "destinations", "DESTINATION_ALIGNMENT");
});

test("AT-18 CLI 恢复可省坏字符串、独立发布输入包、阻断自身错摘要，并接通外部 squash", t => {
  const directory = realpathSync(mkdtempSync(join(tmpdir(), "at18-r2-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const checkout = join(directory, "repo");
  mkdirSync(checkout);
  const localGit = (...args: string[]) => execFileSync("git", [
    "-C", checkout, "-c", "user.name=AT-18 test", "-c", "user.email=at18@example.invalid",
    "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", ...args,
  ], { encoding: "utf8", env: gitEnvironment() }).trim();
  for (const file of Object.values(specPaths)) {
    const target = join(checkout, file);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, readFileSync(join(repo, file)));
  }
  localGit("init", "-q", "-b", "main");
  localGit("add", ".");
  localGit("commit", "-qm", "AT-18 evidence fixture");
  const actualHead = localGit("rev-parse", "HEAD");
  localGit("update-ref", "refs/remotes/origin/main", actualHead);
  const ownPath = join(directory, "delivery.json");
  const obsPath = join(directory, "observations.json");
  const own = { ...manifest, base: actualHead, head: actualHead, externalReportsRoot: directory };
  const snapshot = () => {
    const f = setup().observations;
    const obs: At18Observations = {
      production_enabled: false, bounded_domain_statement: "离线缺证试跑",
      tb_summaries: f.tb_summaries.map(({ tb_id, ticket_state }) => ({ tb_id, ticket_state })),
      legacy_dispositions: f.legacy_dispositions.map(({ ticket, disposition, ticket_state }) => ({ ticket, disposition, ticket_state })),
    };
    return obs;
  };
  const run = (name: string, own: DeliveryManifest, obs: At18Observations, env = process.env) => {
    const out = join(directory, name);
    mkdirSync(out);
    writeFileSync(ownPath, makeBytes(own));
    writeFileSync(obsPath, makeBytes(obs));
    const child = spawnSync(process.execPath, ["--import", "tsx", ".sandcastle/at18-report.mts",
      checkout, ownPath, obsPath, out], { cwd: repo, encoding: "utf8", env });
    return { out, child, result: JSON.parse(child.stdout) };
  };
  const recoverable = snapshot();
  recoverable.legacy_dispositions[0].remaining_obligations = ["保留此项", "\ud800"];
  const repaired = run("recoverable", own, recoverable);
  assert.equal(repaired.child.status, 0, repaired.child.stderr);
  const report = at18ReportSchema.parse(JSON.parse(readFileSync(join(repaired.out, "at18-report.json"), "utf8")));
  requireFailure(report, "observations.legacy_dispositions.0.remaining_obligations.1", "JCS_CANONICALIZE");
  assert.deepEqual(report.legacy_dispositions[0].remaining_obligations, ["保留此项"]);

  const fixedMissing = snapshot();
  fixedMissing.tb_summaries.pop();
  const partial = run("missing-fixed", own, fixedMissing);
  assert.equal(partial.child.status, 1);
  assert.equal(partial.result.diagnostics[0].code, "FIXED_ITEM_UNAVAILABLE");
  assert.deepEqual(readdirSync(partial.out), ["at18-input-bundle.json"]);

  const registered = join(directory, "registered.json");
  writeFileSync(registered, "{}");
  const badDigest = run("wrong-own-hash", { ...own, reports: [{ storage: "external", ticket: 1391,
    base: actualHead, head: actualHead, path: registered, sha256: "0".repeat(64) }] }, snapshot());
  assert.equal(badDigest.child.status, 1);
  assert.equal(badDigest.result.diagnostics[0].code, "INVALID_MANIFEST");
  assert.deepEqual(readdirSync(badDigest.out), []);

  const upstreamHead = "c".repeat(40);
  const upstreamReport = { storage: "external" as const, ticket: 1360, base: actualHead, head: upstreamHead,
    path: registered, sha256: byteSha256(Buffer.from("{}")) };
  const upstreamOwn = join(directory, "upstream.json");
  writeFileSync(upstreamOwn, makeBytes({ ...own, ticket: 1360, head: upstreamHead, reports: [upstreamReport] }));
  const squash = snapshot();
  squash.external_manifests = [upstreamOwn];
  squash.destinations = [{ id: 1, evidence_by_class: { experiment: [
    { ...upstreamReport, commit: null, bounded_scope: "待核的离线仓外实体" },
  ] } }];
  localGit("remote", "add", "origin", "https://github.com/Newchanlun/NewChanlun.git");
  const stub = join(directory, "gh");
  writeFileSync(stub, `#!${process.execPath}\nconst args=process.argv.slice(2);
    if(args[1]==="graphql") { console.log(JSON.stringify({data:{repository:{}}})); }
    else if(args.includes("--slurp")) { console.log(JSON.stringify([[{number:7, head:{sha:${JSON.stringify(upstreamHead)}}, base:{ref:"main"}}]])); }
    else { console.log(JSON.stringify({merged:true, head:{sha:${JSON.stringify(upstreamHead)}}, base:{ref:"main"}, merge_commit_sha:${JSON.stringify(actualHead)}})); }\n`, { mode: 0o700 });
  const merged = run("valid-squash", own, squash, { ...process.env, PATH: `${directory}:${process.env.PATH}` });
  assert.equal(merged.child.status, 0, merged.child.stderr);
  const mergedReport = at18ReportSchema.parse(JSON.parse(readFileSync(join(merged.out, "at18-report.json"), "utf8")));
  requireFailure(mergedReport, "DST-01", "RUNTIME_EVIDENCE_SCOPE");
  assert.ok(!mergedReport.failed_checks.some(f => f.check_id === "ARTIFACT_ANCESTRY"));
});
