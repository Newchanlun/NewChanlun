import { at14CiSteps } from "./at18-at14-ci.ts";
import { deliveredProducts } from "./at18-products.ts";
import assert from "node:assert/strict";
import { execFileSync, spawn, type SpawnOptions } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { adapter, censusSchema, decodeRecord, registrySchema } from "./at18-contract.ts";
import { canMakeFixture, makeFixture, type Mutation, type API } from "./at18-fixture.ts";
import { artifactRefSchema, at18InputBundleSchema, at18ReportSchema, byteSha256, canonicalizeJcs, computeContentHash,
  legacyTickets, ledgerPaths, parseJsonObject, specPaths, tbTickets, workflows, type At18Report } from "./at18-format.ts";
import { ciNames, integrationReviews, utcBefore, type Ticket } from "./at18-integrations.ts";
import { object } from "./at18-github.ts";
import { boundedStatement } from "./at18-report.ts";
import { at18, At18Repository, Diagnostics, G0, P0, valueAt } from "./at18-source.ts";
import { bindCoverage, keyBasis, keyDomain, keyId, readCoverage } from "./at18-coverage.ts";

import { entityRefs } from "./at18-evidence.ts";
import { verifyPregateHistory } from "./at18-pregate.ts";
import { feedWirePaths } from "./at18-legacy.ts";

const root = resolve(__dirname, "..");
const sandbox = resolve(root, ".sandcastle");
const tsx = resolve(root, "node_modules/.bin/tsx");
const fixtureRoot = resolve(__dirname, "fixtures/at18");
function execute(args: string[], options: SpawnOptions = {}) {
  return new Promise<{ code: number | null; stdout: string; stderr: string }>((resolve, reject) => {
    const cmd = spawn(tsx, ["at18-report.mts", ...args], {
      cwd: sandbox, stdio: ["ignore", "pipe", "pipe"], ...options,
    });
    let stdout = "", stderr = "";
    cmd.stdout!.setEncoding("utf8").on("data", (value: string) => { stdout += value; });
    cmd.stderr!.setEncoding("utf8").on("data", (value: string) => { stderr += value; });
    cmd.on("error", reject);
    cmd.on("close", code => resolve({ code, stdout, stderr }));
  });
}
const pathExistsGit = canMakeFixture();
let passedFixture: At18Report | undefined;
async function control(mutation: Mutation = {}, name?: string) {
  const f = makeFixture(mutation);
  if (name) writeFileSync(join(f.dir, "case.txt"), name + "\n");
  const output = join(f.dir, "output");
  mkdirSync(output);
  const r = await execute([f.root, f.manifest, output, ...f.upstream], {
    env: { ...process.env, PATH: f.bin + ":" + process.env.PATH, AT18_TEST_GITHUB: f.apiFile },
  });
  writeFileSync(join(f.dir, "cli.stdout.json"), r.stdout);
  writeFileSync(join(f.dir, "cli.stderr.log"), r.stderr);
  assert.equal(r.code, 0, [f.dir, r.stdout, r.stderr].join("\n"));
  const report = at18ReportSchema.parse(parseJsonObject(readFileSync(join(output, "at18-report.json"))));
  return { f, report, output };
}
function reportFail(report: At18Report, check: string, scope?: string) {
  assert.equal(report.overall_result, "FAIL");
  assert.ok(report.failed_checks.some(row => row.check_id === check &&
    (scope === undefined || row.scope.includes(scope))), `${check}@${scope ?? "…"}: ${JSON.stringify(report.failed_checks.slice(0, 24))}`);
}

test("严格 JSON + RFC 8785：转义重键、非法 UTF-8、非有限数字、孤立代理与 Unicode 顺序", () => {
  assert.throws(() => parseJsonObject(Buffer.from('{"n":0,"\\u006e":1}')), { check_id: "JSON_PARSE" });
  assert.throws(() => parseJsonObject(Buffer.from([0x7b, 0xff, 0x7d])), { check_id: "JSON_PARSE" });
  assert.throws(() => canonicalizeJcs(parseJsonObject(Buffer.from('{"n":1e400}'))), { check_id: "JCS_CANONICALIZE" });
  assert.throws(() => canonicalizeJcs({ value: "\ud800" }), { check_id: "JCS_CANONICALIZE" });
  assert.throws(() => canonicalizeJcs({ ["\udc00"]: 1 }), { check_id: "JCS_CANONICALIZE" });
  const vector = canonicalizeJcs(parseJsonObject(readFileSync(join(fixtureRoot, "jcs.json"))));
  assert.match(vector, /"numbers":\[333333333\.3333333,1e\+30,4\.5,0\.002,1e-27,0,0\.000001,1e-7\]/);
  assert.equal(canonicalizeJcs({ "\uE000": 3, "😀": 2, a: -0 }), '{"a":0,"😀":2,"\uE000":3}');
  assert.ok(utcBefore("2026-11-01T00:00:00.000000001Z", "2026-11-01T00:00:00.000000002Z"));
  assert.equal(utcBefore("2026-11-01T00:00:00.01Z", "2026-11-01T00:00:00.010Z"), false);
});

test("M1：本票 manifest 坏 JSON、非法 UTF-8、票号不符都不写产物；仅不可读 MANIFEST_UNREADABLE", async () => {
  const dir = mkdtempSync(join(realpathSync(process.env.AT18_TEST_EVIDENCE || tmpdir()), "at18-bootstrap-"));
  const manifest = { schemaVersion: 1, ticket: 1403, base: G0, head: G0, productDiff: [], requiredReports: [],
    reports: [], reviews: [], requiredChecks: [], checks: [], scan: { status: "not_run" } };
  const out = join(dir, "output");
  mkdirSync(out);
  for (const [index, sample] of ["{", Buffer.from([0x7b, 0xff, 0x7d]), JSON.stringify(manifest), undefined].entries()) {
    const path = join(dir, "manifest-" + index + ".json");
    if (sample !== undefined) writeFileSync(path, sample);
    const result = await execute([root, path, out]);
    assert.equal(result.code, 1, result.stderr);
    const response = parseJsonObject(Buffer.from(result.stdout));
    assert.equal(response.status, "BLOCKED");
    assert.equal(valueAt(response, "/diagnostics/0/code"), sample === undefined ? "MANIFEST_UNREADABLE" : "INVALID_MANIFEST");
    assert.deepEqual(readdirSync(out), []);
  }
});

test("引导已登记原件版本、声明和摘要不符分别阻断，缺尚未登记的本次产物不等于声明错误", async () => {
  const dir = mkdtempSync(join(realpathSync(process.env.AT18_TEST_EVIDENCE || tmpdir()), "at18-preflight-"));
  const output = join(dir, "output");
  mkdirSync(output);
  const file = join(dir, "report.json");
  writeFileSync(file, "{}");
  const manifest = { schemaVersion: 1, ticket: 1391, base: G0, head: G0, productDiff: [],
    requiredReports: ["at18-report.json"], requiredChecks: [], checks: [], scan: { status: "not_run" },
    externalReportsRoot: dir };
  const artifact = { storage: "external", path: file, ticket: 1391, base: G0, head: G0, sha256: byteSha256(Buffer.from("{}")) };
  const cases = [
    [{ ...manifest, reports: [{ ...artifact, head: "a".repeat(40) }], reviews: [] }, "REPORT_VERSION_MISMATCH"],
    [{ ...manifest, reports: [{ ...artifact, sha256: "a".repeat(64) }], reviews: [] }, "REPORT_HASH_MISMATCH"],
    [{ ...manifest, reports: [], reviews: [{ report: artifact, covers: [] }] }, "UNDECLARED_REPORT"],
    [{ ...manifest, reports: [artifact], reviews: [{ report: { ...artifact, sha256: "b".repeat(64) }, covers: [] }] }, "REPORT_DECLARATION_MISMATCH"],
  ] as const;
  for (const [i, [input, expected]] of cases.entries()) {
    const path = join(dir, "manifest-" + i + ".json");
    writeFileSync(path, JSON.stringify(input));
    const result = await execute([root, path, output]);
    assert.equal(result.code, 1, result.stderr);
    assert.equal(valueAt(parseJsonObject(Buffer.from(result.stdout)), "/diagnostics/0/code"), expected);
    assert.deepEqual(readdirSync(output), []);
  }
});

test("#2131 schema、封闭输出形状原语与 RFC 6901 scope", () => {
  const raw = parseJsonObject(readFileSync(join(fixtureRoot, "adapter-contract.json")));
  assert.equal(adapter(raw).experiment_authorization.ticket, 2133);
  assert.throws(() => adapter({ ...raw, additional: true }));
  assert.throws(() => adapter({ ...raw, run_records: { ...object(raw.run_records), extra: {} } }));
  assert.throws(() => registrySchema.parse({ schema_version: "at18-registry/1", checks: [], bindings: [] }));
  assert.equal(keyDomain(keyBasis(keyId("TB-02", "story", "x/@%"), { path: "a/b@%", pointer: "/p~1" }),
    { evidence_class: "simulation", profile_id: null }), "key:TB-02/story/x~1%40%25@basis:a~1b%40%25@~1p~01@simulation@none");
  assert.equal(valueAt({ a: [{ "/b": 1 }] }, "/a/0/~1b"), 1);
  assert.equal(valueAt({ a: [1] }, "/a/00"), undefined);
  assert.equal(valueAt({ a: 2 }, "/__proto__"), undefined);
});

test("R08 从 F 的矩阵声明展开必需作业，不从成功作业子集缩减分母", () => {
  const workflow = [
    "jobs:", "  at18-registry-lint:", "    runs-on: ubuntu-latest", "  check:", "    name: check ${{ matrix.shard }}",
    "    strategy:", "      matrix:", "        shard: [0, 1, 2, 3]", "  ci-ok:", "    needs:", "      - at18-registry-lint", "      - check",
  ].join("\n");
  assert.deepEqual(ciNames(workflow, []), ["ci-ok", "at18-registry-lint", "check 0", "check 1", "check 2", "check 3"]);
  assert.throws(() => ciNames(workflow.replace("[0, 1, 2, 3]", "${{ unknown }}"), []));
});
test("R02 实际主线规范：97/345/496 行、4,071 键、113 个 TB-11、OE42 必需", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root);
  const head = "b9d898dccf46c2a716115eaa1215bc39c458a959";
  const read = (path: string) => parseJsonObject(s.blob(head, path));
  const diag = new Diagnostics();
  const out = readCoverage(read(specPaths.crosswalk_ref), read(specPaths.coverage_input_ref), ledgerPaths.map(read), diag, read(specPaths.spec_ref));
  assert.deepEqual(out.entries.reduce((a, r) => { a[r.kind]++; return a; }, { story: 0, family: 0, detail: 0 }),
    { story: 97, family: 345, detail: 496 });
  assert.equal(out.keys.size, 4071);
  assert.equal([...out.keys.values()].filter(k => k.slice === "TB-11").length, 113);
  assert.equal(out.lookup.get("family/OE42")!.boundary, false);
  assert.deepEqual(diag.all(), []);
});

test("正式 CLI 正控：同一 Git 图／API 原件／已登记实体得到 PASS，双份产物与全部 locator 可核", {
  skip: !pathExistsGit ? "需要 G0/P0 与发布的规范 Git 对象" : false, timeout: 180_000,
}, async () => {
  const { f, report, output } = await control({}, "official-positive");
  assert.equal(report.overall_result, "PASS", f.dir + ": " + JSON.stringify(report.failed_checks.slice(0, 40)));
  assert.deepEqual(report.failed_checks, []);
  const bytes = readFileSync(join(output, "at18-input-bundle.json"));
  const bundle = at18InputBundleSchema.parse(parseJsonObject(bytes));
  assert.equal(Object.keys(report).length, 21);
  assert.equal(Object.keys(bundle).length, 13);
  assert.deepEqual(report.workflow_runs.map(r => r.workflow), workflows);
  assert.deepEqual(report.legacy_dispositions.map(r => r.ticket), [...legacyTickets]);
  assert.equal(report.tb_summaries[10].input_bundle?.sha256, byteSha256(bytes));
  assert.deepEqual([report.spec_coverage.stories.length, report.spec_coverage.families.length, report.spec_coverage.details.length], [97, 345, 496]);
  assert.equal(report.migration_invariants.experiment?.non_empty_evidence_refs.length, 2);
  assert.equal(report.bounded_domain_statement, boundedStatement(report.historical_deviations.length, "NOT_TRIGGERED", true));
  assert.ok(report.tb_summaries.slice(0, 10).every(tb => tb.slices.length && !tb.slices.some(s => s.ticket >= 34001)));
  assert.ok(report.destinations[4].evidence_by_class.experiment.every(ref => ref.bounded_scope === "AT18:RUN_RECORD"));
  const s = new At18Repository(f.root);
  const registry = registrySchema.parse(parseJsonObject(s.blob(f.F, bundle.registry_ref.path)));
  for (const b of registry.bindings) {
    const data = s.blob(f.F, b.basis.path);
    assert.equal(b.basis.sha256, byteSha256(data));
    assert.notEqual(valueAt(parseJsonObject(data), b.basis.pointer), undefined);
  }
  passedFixture = report;
  const evidence = join(f.dir, "evidence");
  const producer = join(f.dir, "producer-2131");
  mkdirSync(producer);
  const aae = "aae6abf9234eca663fc3e59484e90f644c12899e";
  const repository = new At18Repository(root);
  for (const name of ["adapter.py", "common.py", "run_checks.py"]) {
    writeFileSync(join(producer, name), repository.blob(aae, "scripts/at18/" + name));
  }
  writeFileSync(join(producer, "adapter-contract.json"), s.blob(f.F, at18 + "adapter-contract.json"));
  writeFileSync(join(producer, "registry.json"), s.blob(f.F, at18 + "registry.json"));
  const firstRecord = parseJsonObject(readFileSync(join(evidence, "tb.simulation.TB-01.json")));
  const actualPeer = process.env.AT18_UPSTREAM_TB01;
  const peer = join(f.dir, "peer-tb01.json");
  writeFileSync(peer, actualPeer ? readFileSync(actualPeer) : Buffer.from(canonicalizeJcs(firstRecord.payload) + "\n"));
  const validated = execFileSync("python3", [join(fixtureRoot, "check-producer.py"), producer, evidence, peer], {
    env: { ...process.env, PYTHONPATH: producer, PYTHONDONTWRITEBYTECODE: "1" }, encoding: "utf8",
  });
  writeFileSync(join(f.dir, "producer-check.json"), validated);
  assert.equal(report.tb_summaries.slice(0, 10).flatMap(tb => tb.entity_reports).length, 10);
  for (const tb of report.tb_summaries.slice(0, 10)) for (const ref of tb.entity_reports) {
    assert.equal(byteSha256(readFileSync(ref.path)), ref.sha256);
  }
  // Peer 的原始字节（未改身份、样本或任一个键）直接进入同一个 R07 业务校验器。
  const contract = adapter(parseJsonObject(s.blob(f.F, at18 + "adapter-contract.json")));
  const diag = new Diagnostics();
  const read = (path: string) => parseJsonObject(s.blob(f.F, path));
  const coverage = readCoverage(read(specPaths.crosswalk_ref), read(specPaths.coverage_input_ref),
    ledgerPaths.map(read), diag, read(specPaths.spec_ref));
  const bindings = bindCoverage(registry, coverage, s, f.F, diag);
  const check = registry.checks.find(c => c.check_id === firstRecord.check_id)!;
  const original = parseJsonObject(readFileSync(peer));
  assert.ok(typeof firstRecord.record === "string");
  const data = decodeRecord(contract, firstRecord.record, original);
  assert.equal(entityRefs(firstRecord.record, null, [{ data, check, ref: report.tb_summaries[0].entity_reports[0] }], bindings, diag).length, 1);
  assert.deepEqual(diag.all(), []);
  assert.throws(() => decodeRecord(contract, "tb.simulation.TB-01", { ...original, output: { samples: [[1, 2]] } }));
  assert.deepEqual(report.legacy_dispositions.find(r => r.ticket === 1304)?.evidence_refs.filter(r => r.bounded_scope.startsWith("AT18:AT14"))
    .map(r => r.path.split("/").at(-1)), ["at14-report.json", "summary.md"]);
  writeFileSync(join(f.dir, "upstream-interop.json"), JSON.stringify({
    producerAccepted: 10, cliAccepted: 10, peerKeys: 803, peerAccepted: 1, usedSuppliedPeer: !!actualPeer,
  }) + "\n");
});
test("输出 schema 拒绝多余键、错误次序、production 槽与自指 hash 篡改", {
  skip: !pathExistsGit ? "需要完整 CLI 正控" : false,
}, () => {
  assert.ok(passedFixture);
  const report = passedFixture;
  const encode = (input: object) => ({ ...input, content_hash: computeContentHash({ ...input }) });
  assert.equal(at18ReportSchema.safeParse({ ...report, other: 1 }).success, false);
  assert.equal(at18ReportSchema.safeParse({ ...report, content_hash: "a".repeat(64) }).success, false);
  assert.equal(at18ReportSchema.safeParse(encode({ ...report, workflow_runs: [...report.workflow_runs].reverse() })).success, false);
  assert.equal(at18ReportSchema.safeParse(encode({
    ...report, destinations: report.destinations.map(d => ({ ...d, evidence_by_class: { ...d.evidence_by_class, production: [] } })),
  })).success, false);
  assert.equal(artifactRefSchema.safeParse({ ...report.tb_summaries[10].input_bundle, commit: G0 }).success, false);
});

function array(value: unknown): unknown[] {
  assert.ok(Array.isArray(value));
  return value;
}
function jobs(api: API, i: number, apply: (r: Record<string, unknown>) => boolean) {
  const envelope = object(api[`actions/runs/${49000 + i}/attempts/2/jobs?per_page=100`]);
  const after = array(envelope.jobs).map(object).filter(apply);
  envelope.jobs = after;
  envelope.total_count = after.length;
}
const conditions: [string, Mutation, string, string?][] = [
  ["CI/独评在错误产品上", { api: api => {
    const key = Object.keys(api).find(k => k.startsWith("commits/") && k.endsWith("/statuses?per_page=100"))!;
    const first = object(array(api[key])[0]); first.creator = { login: "not-review-gate" };
  } }, "REVIEW_FINAL_PRODUCT", "commit:"],
  ["TB-11 两票产品互换，两个合入仍经正式门", { api: api => {
    const report = object(api["pulls/39001"]), verifier = object(api["pulls/39002"]);
    [object(report.head).ref, object(verifier.head).ref] = [object(verifier.head).ref, object(report.head).ref];
    [report.title, verifier.title] = [verifier.title, report.title];
  } }, "TB11_PREFLIGHT", "ticket:1403"],
  ["#1391 权威票态为 CLOSED", { api: api => {
    const issue = object(api["issues/1391"]); issue.state = "closed"; issue.state_reason = "completed";
  } }, "TB11_PREFLIGHT", "ticket:1391"],
  ["缺失可变 ReviewRef 不抹掉报告", { api: api => {
    const key = Object.keys(api).find(k => k.startsWith("commits/") && k.endsWith("/statuses?per_page=100"))!;
    api[key] = [];
  } }, "REVIEW_FINAL_PRODUCT", "commit:"],
  ["错 R07 实体身份／原件版本", { records: record => {
    if (record.record === "tb.simulation.TB-02") object(record.payload).schema_version = "at18-tb-entity/999";
  } }, "RECORD_UNSEALED", "tb.simulation.TB-02"],
  ["借邻行 locator 覆盖别的义务", { registry: registry => {
    const b = registry.bindings[0]; b.basis.pointer += "/nonexistent";
  } }, "BASIS_MISMATCH", "key:"],
  ["TB-11-only 义务缺输入包也不能 VERIFIED", { registry: reg => { reg.adapter_contract_sha256 = "0".repeat(64); } },
    "TB11_PREFLIGHT", "/tb_summaries/10/input_bundle"],
  ["输入不能自缩原生子票分母", { api: api => {
    api["issues/1361/sub_issues?per_page=100"] = [{ number: 34003 }];
  } }, "SUBTICKET_INCOMPLETE", "ticket:1361"],
  ["生产范围变化／任意声明不能覆盖 P2 原件", { api: api => {
    array(api["issues/1561/comments?per_page=100"]).push({ id: 9999999999, body: "production 已完成首次发送" });
  } }, "PRODUCTION_SCOPE_CHANGED", "ticket:1561"],
  ["未启用结论不能从首次启用原件缺失倒推：触达与版本均齐", { enabledWithoutFirstActivation: true },
    "SPECIAL_GATE", "first_activation"],
  ["没有证明的延期不能套给覆盖键", { registry: reg => {
    const b = reg.bindings.find(x => x.domains[0].result === "VERIFIED")!;
    b.domains.push({ evidence_class: "production", profile_id: "P2-not-authorized", result: "BOUNDED_DEFERRED",
      deferred_gate: "LEGACY_OE41_DEPLOYMENT", checks: [] });
  } }, "DOMAIN_INVALID", "@production@P2-"],
  ["#1279 明示提前放行", { api: api => {
    array(api["issues/1279/comments?per_page=100"]).push({ id: 9999999999, body: "图前置尚缺，现宣布试运行放行" });
  } }, "LEGACY_DISPOSITION", "ticket:1279"],
  ["#942/#1282 反处分", { api: api => {
    for (const n of [942, 1282]) { const issue = object(api["issues/" + n]); issue.state = "open"; issue.state_reason = null; }
  } }, "LEGACY_DISPOSITION", "ticket:942@ISSUE_942_DISPOSITION"],
  ["#1304 未完成时不能关闭", { api: api => {
    const issue = object(api["issues/1304"]); issue.state = "closed"; issue.state_reason = "completed";
    jobs(api, 2, r => !String(r.name).startsWith("at18 control.TB-07 "));
  } }, "LEGACY_DISPOSITION", "ticket:1304@ISSUE_1304_REPLAY"],
  ["空仓迁移", { records: record => {
    if (record.record === "migration.experiment") object(object(record.payload).old_before).positions = [];
  } }, "SPECIAL_GATE", "no_lost_rights"],
  ["权限原件无运行时核验", { records: record => {
    if (record.record === "permission.experiment") object(object(record.payload).launch).session_permission_verified = false;
  } }, "SPECIAL_GATE", "runtime_verification"],
  ["模拟触达不等于业务触达", { records: record => {
    if (record.record === "post_gate.experiment") {
      const p = object(record.payload); p.growth_eligible = true;
      p.gate_events = [{ type: "SimulatedGateReached", profile_id: "P1-hl-testnet", evidence_class: "experiment",
        known_at: "2026-11-01T06:00:00Z", event_id: "synthetic-only" }];
      p.outputs = [{ type: "AwaitingPolicy", dependency: "post_gate_params" }];
    }
  } }, "SPECIAL_GATE", "slot:post_gate.experiment"],
  ["最新 attempt 缺组不得借旧组", { api: api => {
    jobs(api, 3, r => !String(r.name).startsWith("at18 control.TB-10 "));
  } }, "CHECK_JOB_MISSING", "control.TB-10"],
  ["缺 #2133 签名不延期", { api: api => object(api["issues/comments/440000001"]).body = "不是签署" },
    "AUTH_REQUIRED", "ticket:2133"],
  ["覆盖计数减一不能用同步截断来源过关", { crosswalk: source => { array(source.rows).pop(); } },
    "COVERAGE_SOURCE", "/spec_coverage"],
  ["缺 R07 封印对应外部原件照常产出 FAIL", { omitRecord: record => record.record === "permission.experiment" },
    "RECORD_UNSEALED", "at18-seal permission.experiment"],
];
test("R1/R2 回归：每个单点破坏均产生具名 FAIL", {
  skip: !pathExistsGit ? "需要 G0/P0 与发布的规范 Git 对象" : false, timeout: 420_000, concurrency: 2,
}, async t => {
  await Promise.all(conditions.map(([name, mutation, check, scope]) => t.test(name, { timeout: 90_000 }, async () => {
      const { report } = await control(mutation);
      reportFail(report, check, scope);
      if (name.startsWith("#942/#1282")) reportFail(report, check, "ticket:1282@ISSUE_1282_ARCHIVE");
      if (name.startsWith("未启用结论")) {
        assert.equal(report.post_gate_records.experiment?.status, "TRIGGERED_AND_ENABLED");
        assert.ok(report.post_gate_records.experiment?.gate_reached_event);
        assert.equal(report.post_gate_records.experiment?.parameter_version?.bounded_scope, "AT18:AUTHORIZATION");
        assert.equal(report.post_gate_records.experiment?.first_activation, null);
        assert.equal(report.post_gate_records.experiment?.non_activation_evidence.length, 0);
      }
      if (name.startsWith("生产范围")) {
        assert.equal(report.destinations[4].result, "FAIL");
        assert.equal(report.tb_summaries.find(t => t.ticket === tbTickets["TB-10"])?.gate_satisfied, false);
        assert.equal(report.legacy_dispositions.find(t => t.ticket === 1279)?.disposition_valid, false);
        assert.match(report.bounded_domain_statement, /^AT18_PRODUCTION_SLOT DISABLED$/m);
      }
      if (name.startsWith("缺 #2133")) assert.ok(report.permission_blocked.some(p => p.blocker_ticket === 2133));
  })));
});

test("固定 Destination 义务实际值不可表示时 BLOCKED/FIXED_ITEM_UNAVAILABLE，不猜测并且无产物", {
  skip: !pathExistsGit, timeout: 90_000,
}, async () => {
  const f = makeFixture({ omitObligation: true });
  const out = join(f.dir, "output");
  mkdirSync(out);
  const result = await execute([f.root, f.manifest, out, ...f.upstream], {
    env: { ...process.env, PATH: f.bin + ":" + process.env.PATH, AT18_TEST_GITHUB: f.apiFile },
  });
  writeFileSync(join(f.dir, "cli.stdout.json"), result.stdout);
  writeFileSync(join(f.dir, "cli.stderr.log"), result.stderr);
  assert.equal(result.code, 1, result.stderr);
  assert.equal(valueAt(parseJsonObject(Buffer.from(result.stdout)), "/diagnostics/0/code"), "FIXED_ITEM_UNAVAILABLE");
  assert.deepEqual(readdirSync(out), []);
});

test("R4/H2：真实 #2132 清册全量 2,987 行与固定 P0 第一父链逐位、按序相等", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root), revision = "d896e31be8353a9445af46629737be6a4d6363e5";
  const census = censusSchema.parse(parseJsonObject(s.blob(revision, at18 + "landing-census.json")));
  const published = census.sources.find(row => row.role === "history")!;
  const bytes = s.blob(revision, published.path);
  assert.equal(census.p0, P0);
  assert.equal(byteSha256(bytes), published.sha256);
  const history = verifyPregateHistory(s, bytes);
  assert.equal(history.length, 2987);
  assert.deepEqual(history.map(h => h.commit), s.chain(P0));
  assert.equal(history.at(-1)?.parent, null);
  assert.ok(history.some(h => h.parents.length > 1 && !!h.body));
  assert.throws(() => verifyPregateHistory(s, Buffer.from(bytes.toString().replace(/"parent": "[0-9a-f]{40}"/, '"parent": null'))));
});

const legacyRow = (report: At18Report, ticket: number) => report.legacy_dispositions.find(row => row.ticket === ticket)!;
const close = (api: API, ticket: number) => {
  const data = object(api["issues/" + ticket]);
  data.state = "closed";
  data.state_reason = "completed";
};
const heavy = "ISSUE_1320_HEAVY_MEASUREMENT";
const positive = (report: At18Report) => {
  assert.equal(report.overall_result, "PASS", JSON.stringify(report.failed_checks.slice(0, 20)));
  assert.deepEqual(report.failed_checks, []);
};
const at14Fail = (report: At18Report) => {
  reportFail(report, "LEGACY_DISPOSITION", "ticket:1304@ISSUE_1304_AT14");
  reportFail(report, "LEGACY_DISPOSITION", "ticket:1320@ISSUE_1320_FULL_REPLAY");
  assert.ok([1304, 1320, 1279].every(ticket => !legacyRow(report, ticket).disposition_valid));
};
test("R4/H3,H5,H6,H8/M2,M3：单点破坏精确落到实体、逐键、产品、授权和原件身份", {
  skip: !pathExistsGit, timeout: 360_000, concurrency: 2,
}, async t => {
  const cases: [string, Mutation, (report: At18Report) => void][] = [
    ["comment-replacement：匹配字节的纯注释不算收编", { feedReplacement: "/* mod fake { fn run() {} } */\n// no implementation" },
      r => reportFail(r, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE")],
    ...(["isolated", "no-coverage", "missing-child", "wrong-test-symbol"] as const)
      .map((feedCase): [string, Mutation, (report: At18Report) => void] =>
        ["#1319 " + feedCase, { feedCase }, r => reportFail(r, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE")]),
    ...["# comment only", '"""docstring only"""', "", "def route():\n    pass"].map(
      (feedReplacement): [string, Mutation, (report: At18Report) => void] =>
        ["#1319 空壳: " + JSON.stringify(feedReplacement), { feedReplacement },
          r => reportFail(r, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE")]),
    ["#1319 Python yield from 与 Rust pub mod 接入且有 TB-08 验证", {}, r => {
      positive(r);
      const paths = legacyRow(r, 1319).evidence_refs.map(ref => ref.path);
      assert.ok(paths.includes("trading_system/at18_fixture_feed.py"));
      assert.ok(paths.includes("rust/src/at18_fixture_wire/mod.rs"));
      assert.ok(paths.includes("trading_system/tests/test_at18_fixture_feed.py"));
      assert.ok(paths.includes("rust/tests/at18_fixture_wire.rs"));
    }],
    ["#1319 Rust pub use 追到真实子模块", { feedCase: "reexport" }, positive],
    ["opaque_extra：R07 不投影掉未知 TB 记录业务键", { records: r => {
      if (r.record === "tb.simulation.TB-01") object(r.payload).opaque_extra = "unexpected";
    } }, r => {
      assert.equal(r.tb_summaries[0].entity_reports.length, 0);
      reportFail(r, "TB_REPORT", "ticket:1359");
    }],
    ["R07 不投影掉嵌在 tests 中的未知键", { records: r => {
      if (r.record !== "tb.simulation.TB-01") return;
      const tests = object(r.payload).tests;
      assert.ok(Array.isArray(tests));
      object(tests[0]).opaque_extra = "unexpected";
    } }, r => {
      assert.equal(r.tb_summaries[0].entity_reports.length, 0);
      reportFail(r, "TB_REPORT", "ticket:1359");
    }],
    ["历史 PR #1906：真归属接受", { historicProducts: "correct" }, positive],
    ["历史 PR #1906：#1392↔#1404 互换拒收", { historicProducts: "swapped" }, r => {
      reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:1392");
      reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:1404");
    }],
    ["已审 head 中含 fence 的空差异 Closes 仍然拒收", { emptyProduct: true },
      r => reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:33001")],
    ["无关 Cargo.toml 不能销 #1319", { feedWire: () => [{ path: "rust/Cargo.toml", disposition: "FROZEN", replacement: null }] },
      r => reportFail(r, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE")],
    ...[...feedWirePaths.feed, ...feedWirePaths.wire].map((missing): [string, Mutation, (report: At18Report) => void] =>
      ["缺 " + missing, { feedWire: rows => rows.filter(row => row.path !== missing) },
        r => reportFail(r, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE")]),
    ["十份 TB 业务实体拒绝必须红及逐键与 TB 门", { records: r => {
      if (String(r.record).startsWith("tb.")) object(r.payload).tb_id = "TB-11";
    } }, r => {
      for (const tb of r.tb_summaries.slice(0, 10)) {
        assert.equal(tb.gate_satisfied, false);
        assert.equal(tb.entity_reports.length, 0);
        reportFail(r, "TB_REPORT", `ticket:${tb.ticket}`);
      }
      assert.equal(r.spec_coverage.stories.length, 97);
      // US-ENG-10 只有 TB-11 前置，R12 明确不读 TB-01..10 的实体。
      assert.deepEqual(r.spec_coverage.stories.filter(row => row.status !== "FAIL").map(row => ({
        story_id: row.story_id, closure_slice_ids: row.closure_slice_ids, status: row.status,
      })), [{ story_id: "US-ENG-10", closure_slice_ids: ["TB-11"], status: "VERIFIED" }]);
      for (const [rows, count] of [[r.spec_coverage.families, 345], [r.spec_coverage.details, 496]] as const) {
        assert.equal(rows.length, count);
        assert.ok(rows.every(row => row.status === "FAIL"));
      }
      reportFail(r, "RECORD_UNSEALED", "key:TB-01/");
    }],
    ["同一合入 PR 的两张实施票交换产品路径也必须失败", { api: api => {
      const a = object(api["issues/33001"]), b = object(api["issues/33002"]);
      a.body = String(a.body).replace("scripts/probe.py", "scripts/at18-fixture/control.TB-02.mjs");
      b.body = String(b.body).replace("scripts/at18-fixture/control.TB-02.mjs", "scripts/probe.py");
    } }, r => {
      reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:33001");
      reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:33002");
    }],
    ["关票语句不能代替逐票产品原件", { api: api => {
      object(api["pulls/39001"]).body = Array.from({ length: 10 }, (_, i) => "Closes #" + (33001 + i)).join("\n");
    } }, r => {
      for (let n = 33001; n <= 33010; n++) reportFail(r, "SUBTICKET_INCOMPLETE", "ticket:" + n);
    }],
    ["#1369 提前关票记阶段失败，TB-11 前置仍按自身条件", { api: api => close(api, 1369) }, r => {
      reportFail(r, "CLOSEOUT_STAGE", "ticket:1369");
      assert.equal(r.tb_summaries[10].ticket_state, "CLOSED");
      assert.equal(r.tb_summaries[10].gate_satisfied, true);
    }],
    ["伪有授权的前缀 job 不能给缺标签的精确 job 借权限", { api: api => {
      const envelope = object(api["actions/runs/49003/attempts/2/jobs?per_page=100"]);
      const records = Array.isArray(envelope.jobs) ? envelope.jobs.map(object) : [];
      const actual = records.find(j => String(j.name).startsWith("at18 control.TB-08 "))!;
      envelope.jobs = [{ ...actual, id: 58999, name: "at18 control.TB-08 " + "0".repeat(64) }, ...records];
      envelope.total_count = records.length + 1;
      actual.labels = ["ubuntu-latest"];
    } }, r => {
      reportFail(r, "AUTH_REQUIRED", "key:TB-08/");
      assert.equal(r.tb_summaries[7].gate_satisfied, false);
    }],
    ["PRE 最近变更未获审同时登记两个失败码", { api: api => {
      const anchor = object(object(api["pulls/39001"]).head).sha;
      api[`commits/${anchor}/statuses?per_page=100`] = [];
    } }, r => {
      reportFail(r, "REVIEW_FINAL_PRODUCT", "commit:");
      for (const path of ["registry.json", "landing-census.json", "pregate-review.json"]) reportFail(r, "PREGATE_REVIEW", "pre:" + at18 + path);
    }],
    ["8 字节截断 crosswalk 报解析失败但保留字节摘要", { crosswalkBytes: Buffer.from('{"schema') }, r => {
      reportFail(r, "JSON_PARSE", "/crosswalk_ref");
      assert.equal(r.spec_coverage.crosswalk_sha256, byteSha256(Buffer.from('{"schema')));
    }],
  ];
  await Promise.all(cases.map(([name, mutation, verify]) => t.test(name, { timeout: 90_000 }, async () => verify((await control(mutation, name)).report))));
});

test("R4/H4：AT-14 合同缺字段、缺摘要／不一致、Node 冒充 Rust 锁均阻断三个依赖者", {
  skip: !pathExistsGit, timeout: 360_000, concurrency: 2,
}, async t => {
  const fields = ["version_set", "bounded_domain_statement", "input_source", "fu14_gates", "ci_run_id", "review_binding",
    "model_execution", "assumption_counts", "verification_source_label"];
  const cases: [string, Mutation][] = [
    ...fields.map((field): [string, Mutation] => ["缺 " + field, { at14: row => { delete row[field]; } }]),
    ["缺 summary.md", { summary: "missing" }],
    ["summary.md 结论与 JSON 不同", { summary: "inconsistent" }],
    ["TestOnly 入口冒充正式会话", { at14: row => {
      const session = object(row.session), manifest = object(session.manifest_echo);
      manifest.kind = "TestOnly";
      session.manifest_hash = byteSha256(Buffer.from(canonicalizeJcs(manifest)));
    } }],
    ["四个通过的具名 Node 锁冒充 Rust", { at14Node: true }],
    ["shadow", { at14: row => {
      const session = object(row.session), manifest = object(session.manifest_echo);
      manifest.launcher = "theta_replay";
      session.manifest_hash = byteSha256(Buffer.from(canonicalizeJcs(manifest)));
    } }],
    ["profile launcher shadow", { at14: row => {
      const session = object(row.session), profile = object(session.profile_echo);
      profile.launcher = "theta_replay";
      session.profile_hash = byteSha256(Buffer.from(canonicalizeJcs(profile)));
      object(row.dual_run_tuple).input_profile_hash = session.profile_hash;
    } }],
    ["contradiction", { at14: row => { object(row.assumption_counts).stochastic_l1_count = 1; } }],
    ["wrong-policy-version", { at14: row => { object(row.dual_run_tuple).policy_version = "funding@2"; } }],
    ...(["ignored", "skip-ci", "dispatch-only", "ignored-only", "unrecorded", "wrong-step", "comment", "qualified-selector", "sibling-selector"] as const)
      .map((at14Ci): [string, Mutation] => [at14Ci, { at14Ci }]),
    ["qualified-policy", { at14: row => { object(row.dual_run_tuple).policy_version = "funding@1"; } }],
  ];
  await Promise.all(cases.map(([name, mutation]) =>
    t.test(name, { timeout: 90_000 }, async () => {
      const { report } = await control(mutation, name);
      (["qualified-policy", "comment", "qualified-selector"].includes(name) ? positive : at14Fail)(report);
    })));
});

test("R4/H7：同一历史失败 run 的四项 cure 缺一或败一均不通行", {
  skip: !pathExistsGit, timeout: 180_000, concurrency: 2,
}, async t => {
  await Promise.all((["all", "missing", "failed", "empty-node", "empty-step", "empty-rust"] as const).map(historicalCures => t.test(historicalCures, async () => {
    const { report } = await control({ historicalCures }, "R11/" + historicalCures);
    assert.ok(report.historical_deviations.some(row => row.ticket === 1366 && row.run_id === 39034285362 && row.observed === "FAILURE"));
    if (historicalCures === "all") positive(report);
    else reportFail(report, "DEVIATION_NOT_CURED", "history:1366/8d84e21e2c9e9800a22900c2d4c67878310c1ab9/ci.yml/39034285362");
  })));
});

test("R4/H9/M1：重测、废弃及延期相互独立；图外状态不影响 #1279 / DST-06", {
  skip: !pathExistsGit, timeout: 240_000, concurrency: 2,
}, async t => {
  await Promise.all((["measured", "short", "missing-control", "wrong-trial", "retired", "unapproved-retirement", "one-bar", "late-review",
    "malformed-heavy", "input-unregistered", "second-run-missing", "output-diverges", "sparse", "unapproved-gap", "wrong-count", "wrong-chunk",
    "retired-thanks", "retired-owner-revoke", "retired-nonowner-revoke", undefined] as const)
    .map(heavyCase => t.test(heavyCase ?? "未测先关 #1320", async () => {
      const { report } = await control({ heavyCase, api: api => close(api, 1320) }, "heavy/" + (heavyCase ?? "unmeasured"));
      const disposition = legacyRow(report, 1320);
      assert.equal(legacyRow(report, 1279).disposition_valid, true);
      assert.equal(report.destinations[5].result, "PASS");
      if (["measured", "retired", "retired-thanks", "retired-nonowner-revoke"].some(x => x === heavyCase)) {
        positive(report);
        assert.equal(disposition.disposition_valid, true);
        assert.equal(report.unexecuted.some(row => row.obligation === heavy), false);
      } else {
        reportFail(report, "LEGACY_DISPOSITION", "ticket:1320@" + heavy);
        if (heavyCase === "malformed-heavy") reportFail(report, "JSON_PARSE", "ticket:1320");
        assert.equal(disposition.disposition_valid, false);
        assert.equal(report.unexecuted.find(row => row.obligation === heavy)?.required, false);
        assert.ok(disposition.remaining_obligations.includes(heavy));
        assert.ok(!disposition.remaining_obligations.includes("ISSUE_1320_FULL_REPLAY"));
      }
    })));
});

test("R5/H6：R09 绑定真实 PR #1942 的旧 head，无新 fence 仍归 #1381", { skip: !pathExistsGit }, async () => {
  const s = new At18Repository(root);
  const merge = "3cd162ea4c3c8c73a0d6b8c6866894a0204e78bc";
  const pull = new Map<string, object>();
  const merged = new Map<string, number>();
  const reviewed = new Set<string>();
  for (const M of s.chain(merge, P0)) {
    const H = s.string("rev-parse", M + "^2");
    const subject = s.string("show", "-s", "--format=%s", M);
    const match = /^Merge pull request #(\d+) from [\w.-]+\/(.+)$/.exec(subject);
    assert.ok(match, subject);
    const n = Number(match[1]);
    pull.set("pulls/" + n, { number: n, merged: true, merged_at: "2026-11-10T00:00:00Z", merge_commit_sha: M,
      base: { ref: "main", repo: { full_name: s.github.repo } }, head: { sha: H, ref: match[2] }, body: "既有交付" });
    merged.set(`commits/${M}/pulls?per_page=100`, n);
    reviewed.add(`commits/${H}/statuses?per_page=100`);
  }
  s.github.get = async route => object(pull.get(route));
  s.github.list = async route => {
    const number = merged.get(route);
    if (number) {
      const pr = object(pull.get("pulls/" + number));
      return [{ number, merge_commit_sha: pr.merge_commit_sha }];
    }
    if (reviewed.has(route)) return [{ id: 1, state: "success", context: "deepagents/review",
      creator: { login: "newchanlun-review-gate[bot]" }, created_at: "2026-11-09T10:00:00Z" }];
    throw new Error(route);
  };
  const R09 = await integrationReviews(s, merge, new Diagnostics());
  assert.ok(R09.ok);
  const H = s.string("rev-parse", merge + "^2");
  assert.doesNotMatch(s.string("show", "-s", "--format=%B", H), /at18-product-delivery/);
  const path = "rust/src/history_simulation/mod.rs";
  const ticket: Ticket = { number: 1381, state: "CLOSED", reason: "COMPLETED", labels: [], updated_at: null,
    data: { body: "既有票面，没有新 fence" } };
  const claim = (number: number, p: string): Ticket => ({ ...ticket, number, data: {
    body: "```at18-product-delivery/1\n" + JSON.stringify({ ticket: number, products: [{ commit: merge, path: p }] }) + "\n```",
  } });
  assert.deepEqual(deliveredProducts(s, ticket, new Map(), R09.accepted), [merge]);
  assert.deepEqual(deliveredProducts(s, claim(1381, path), new Map(), R09.accepted), [merge]);
  assert.deepEqual(deliveredProducts(s, claim(1404, path), new Map(), R09.accepted), []);
  assert.deepEqual(deliveredProducts(s, claim(1381, "README.md"), new Map(), R09.accepted), []);
  assert.deepEqual(deliveredProducts(s, claim(1381, path), new Map(), new Map()), []);
});

test("R6/H4：真实 CI 的 pull_request 行尾注释不改变目标；拒被过滤的 PR", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root);
  const workflow = s.blob("b9d898dccf46c2a716115eaa1215bc39c458a959", workflows[0]).toString("utf8");
  const lock = { name: "dual_run_determinism_h1", target: "production_session_entry" };
  const expected = at14CiSteps(workflow, [lock]);
  assert.ok(expected.some(step => step.jobName === "rust-test-production-session" && step.index === 3));
  const commented = workflow.replace(/^  pull_request:$/m, "  pull_request: # comment");
  assert.notEqual(commented, workflow);
  assert.deepEqual(at14CiSteps(commented, [lock]), expected);
  const quoteName = commented.replace("（纯生产构建）", "（纯生产构建） # inline");
  assert.deepEqual(at14CiSteps(quoteName, [lock]), expected);
  const filtered = commented.replace(/^(  pull_request:.*)$/m, "$1\n    paths: ['rust/**']");
  assert.deepEqual(at14CiSteps(filtered, [lock]), []);
});

test("R6/H1：正式 CLI 依据原始 JSON 数字类型；大整数不按 Number 取整", {
  skip: !pathExistsGit, timeout: 180_000, concurrency: 2,
}, async t => {
  for (const [field, literal, accepts] of [
    ["processes", "1.0", false], ["processes", "1e0", false], ["processes", "9007199254740992", true],
    ["processes", "9007199254740993", true], ["processes", "1" + "0".repeat(400), true],
    ["run_attempt", "2.0", false],
  ] as const) await t.test(field + "=" + (literal.length > 60 ? "401 位整数" : literal), async () => {
    const { report } = await control({ recordLexeme: (r, bytes) => {
      if (r.record !== "tb.simulation.TB-01") return bytes;
      return Buffer.from(bytes.toString("utf8").replace('"'+field+'":2', '"'+field+'":'+literal));
    } }, "R6/numbers/" + field + "/" + (literal.length > 60 ? "401digits" : literal));
    if (accepts) positive(report);
    else {
      reportFail(report, "RECORD_UNSEALED", "slot:tb.simulation.TB-01");
      assert.equal(report.tb_summaries[0].entity_reports.length, 0);
    }
  });
});

test("R6/H9：旧三根跨十年输入保持 #1320 OPEN，延期非图内必需", { skip: !pathExistsGit, timeout: 90_000 }, async () => {
  const { report } = await control({ heavyCase: "sparse" }, "R6/heavy/sparse-open");
  positive(report);
  const row = legacyRow(report, 1320);
  assert.equal(row.ticket_state, "OPEN");
  assert.ok(row.remaining_obligations.includes(heavy));
  assert.equal(report.unexecuted.find(row => row.obligation === heavy)?.required, false);
});

test("R6/H6：真实 #2021 路径提交的自然位置票号归 #1407，仍要求 R09 和实际差异", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root);
  const commit = "b9d898dccf46c2a716115eaa1215bc39c458a959";
  const path = "rust/src/economic_session/exact_command.rs";
  const head = s.string("rev-parse", commit + "^2");
  assert.equal(head, "fdda2200fbe8caf4e400faa1b7c12e8bd7143258");
  const reviewed = new Map([[commit, { number: 2021, head: { sha: head, ref: "opus/1407-c1-e-release" } }]]);
  const claim = (number: number, p: string): Ticket => ({
    number, state: "CLOSED", reason: "COMPLETED", labels: [], updated_at: null,
    data: { body: "```at18-product-delivery/1\n" + JSON.stringify({ ticket: number, products: [{ commit, path: p }] }) + "\n```" },
  });
  assert.deepEqual(deliveredProducts(s, claim(1407, path), new Map(), reviewed), [commit]);
  assert.deepEqual(deliveredProducts(s, claim(1404, path), new Map(), reviewed), []);
  assert.deepEqual(deliveredProducts(s, claim(1407, "README.md"), new Map(), reviewed), []);
  assert.deepEqual(deliveredProducts(s, claim(1407, path), new Map(), new Map()), []);
});
