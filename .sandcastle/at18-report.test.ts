import { rustReplacement } from "./at18-code.ts";
import { pythonReplacement } from "./at18-python-run.ts";
import { cargoContext, cargoTarget, enabledRustItem } from "./at18-cargo.ts";
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

test("R7/H3：正式 CLI 按冻结选择器核验实际执行、公开接入与 Rust 完整语法", {
  skip: !pathExistsGit, timeout: 180_000,
}, async t => {
  const imported = "from trading_system.at18_fixture_feed import route\n";
  const call = "list(route('1min', {'1min': 'ohlcv'}, [1, 2]))";
  for (const [id, mutation, accepts] of [
    ["callable-only", { feedTest: imported + "def test_route():\n    assert callable(route)\n" }, false],
    ["generator-not-consumed", { feedTest: imported + "def test_route():\n    assert route('1min', {}, []) is not None\n" }, false],
    ["outside-test", { feedTest: imported + call + "\ndef test_route():\n    assert True\n" }, false],
    ["failed-after-execution", { feedTest: imported + "def test_route():\n    assert " + call + " == []\n" }, false],
    ["public-feed", { feedTest: "from trading_system import select_feed\ndef test_route():\n" +
      "    assert list(select_feed({'1min': 'ohlcv'}, [1, 2])) == [1, 2]\n" }, true],
    ["yield-from", { feedReplacement: "def route(granularity, sources, events):\n    yield from events\n" }, true],
    ["public-wire", { wireCase: "public-entry" }, true],
    ["incomplete-wire", { wireCase: "incomplete" }, false],
  ] as const) await t.test(id, async () => {
    const { report } = await control(mutation, "R7/feed/" + id);
    assert.equal(legacyRow(report, 1319).disposition_valid, accepts);
    if (accepts) positive(report);
    else {
      reportFail(report, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE");
      assert.equal(report.failed_checks.length, 1);
    }
  });
});

test("R8/H3：正式 CLI 只接受生产接入的同一承接导出", {
  skip: !pathExistsGit, timeout: 180_000,
}, async t => {
  const feed = "trading_system.at18_fixture_feed";
  const route = "def route(granularity, sources, events):\n    return events\n";
  const label = "def format_label(label):\n    return label.strip().upper()\n";
  const onlyLabel = `from ${feed} import format_label\ndef test_route():\n    assert format_label(' dx ') == 'DX'\n`;
  const feedIntegration = "\nfrom .at18_fixture_feed import Feed\ndef select_feed(sources, events):\n" +
    "    feed = Feed()\n    return feed.route('1min', sources, events)\n";
  const feedClass = "class Feed:\n    def route(self, granularity, sources, events):\n        yield from events\n" +
    "    def format_label(self, label):\n        return label.strip().upper()\n";
  const wire = (from: string, body: string) =>
    `use newchan_rust::${from};\n#[test]\nfn check_connection() { ${body} }\n`;
  const handshake = "at18_fixture_wire::probe::handshake";
  const invoke = 'assert!(handshake("HELLO"));';
  const wireProbe = 'pub fn handshake(banner: &str) -> bool { banner.starts_with("HELLO") }\n' +
    "pub fn unrelated() -> bool { true }\n";
  for (const [id, mutation, accepts] of [
    ["python-broken-route-unrelated-test", { feedReplacement: route.replace("return events", "return []") + label, feedTest: onlyLabel }, false],
    ["python-healthy-route-unrelated-test", { feedReplacement: route + label, feedTest: onlyLabel }, false],
    ["python-same-named-local", { feedTest: `from ${feed} import route\ndef test_route():\n` +
      "    def route(*args): return [1, 2]\n    assert route() == [1, 2]\n" }, false],
    ["python-direct-route", { feedReplacement: route + label }, true],
    ["python-consume-through-production", { feedReplacement: route + label,
      feedTest: "from trading_system import select_feed\ndef test_route():\n    assert list(select_feed({}, [1, 2])) == [1, 2]\n" }, true],
    ["python-instance-method", { feedReplacement: feedClass, feedIntegration,
      feedTest: `from ${feed} import Feed\ndef test_route():\n    assert list(Feed().route('1min', {}, [1, 2])) == [1, 2]\n` }, true],
    ["python-unrelated-instance-method", { feedReplacement: feedClass, feedIntegration,
      feedTest: `from ${feed} import Feed\ndef test_route():\n    assert Feed().format_label(' dx ') == 'DX'\n` }, false],
    ["rust-pointer-only", { wireTest: wire(handshake, "let _signature: fn(&str) -> bool = handshake;") }, false],
    ["rust-direct", { wireTest: wire(handshake, invoke) }, true],
    ["rust-reexport-alias", { wireModule: "mod probe; pub use probe::handshake as accept_banner;\n",
      wireTest: wire("at18_fixture_wire::accept_banner as check", 'assert!(check("HELLO"));') }, true],
    ["rust-call-local-binding", { wireTest: wire(handshake, 'let f = handshake; assert!(f("HELLO"));') }, true],
    ["rust-unrelated-same-file", { wireCase: "public-entry", wireProbe,
      wireTest: wire("at18_fixture_wire::probe::unrelated", "assert!(unrelated());") }, false],
    ["rust-shadowed-call", { wireTest: wire(handshake, 'let handshake = |_: &str| true; ' + invoke) }, false],
  ] as const) await t.test(id, async () => {
    const { report } = await control(mutation, "R8/feed/" + id);
    assert.equal(legacyRow(report, 1319).disposition_valid, accepts);
    if (accepts) positive(report);
    else {
      reportFail(report, "LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE");
      assert.equal(report.failed_checks.length, 1);
    }
  });
});

test("R9/#1319：Python 生产调用按词法绑定，定义不等于调用", {
  skip: !pathExistsGit, timeout: 360_000,
}, async t => {
  const feedReplacement = "def route(granularity, sources, events):\n    return events\n\n" +
    "def discard(granularity, sources, events):\n    return []\n";
  const select = (code: string, global = false) =>
    (global ? "\nfrom .at18_fixture_feed import route\n" : "\n") + "\ndef select_feed(sources, events):\n" +
    code.split("\n").map(line => "    " + line).join("\n") + "\n";
  const publicTest = "from trading_system import select_feed\n\ndef test_route():\n" +
    "    assert list(select_feed({}, [1, 2])) == [1, 2]\n";
  const route = "return route('1min', sources, events)";
  const discard = select("from .at18_fixture_feed import discard as route\n" + route, true);
  for (const [id, feedIntegration, feedTest, accepts] of [
    ["py-local-import-direct", discard, undefined, false],
    ["py-local-import-public", discard, publicTest, false],
    ["py-local-only-valid", select("from .at18_fixture_feed import route\n" + route), publicTest, true],
    ["py-local-module-import", select("from . import at18_fixture_feed as mod\n" + route.replace("route(", "mod.route(")), publicTest, true],
    ["py-dotted-module-import", select("import trading_system.at18_fixture_feed\n" +
      route.replace("route(", "trading_system.at18_fixture_feed.route(")), publicTest, true],
    ["py-import-module-alias", select("import trading_system.at18_fixture_feed as mod\n" +
      route.replace("route(", "mod.route(")), publicTest, true],
    ["py-dead-def", select("def unused():\n    " + route + "\nreturn []", true), undefined, false],
    ["py-dead-lambda", select("unused = lambda: " + route.slice(7) + "\nreturn []", true), undefined, false],
    ["py-called-def", select("def dispatch():\n    from .at18_fixture_feed import route\n    " + route + "\nreturn dispatch()"), publicTest, true],
    ["py-called-lambda", select("dispatch = lambda: " + route.slice(7) + "\nreturn dispatch()", true), publicTest, true],
    ["py-inner-shadow-does-not-escape", select("def unused():\n    from .at18_fixture_feed import discard as route\n    " + route + "\n" + route, true), publicTest, true],
    ["py-local-def-shadows-import", select("def route(*args):\n    return []\n" + route, true), undefined, false],
    ["py-local-class-method", select("class Router:\n    def run(self):\n        " + route + "\nreturn Router().run()", true), publicTest, true],
    ["py-unbound-before-local", select(route + "\nfrom .at18_fixture_feed import route", true), undefined, false],
    ["py-del-does-not-restore", select("from .at18_fixture_feed import route\ndel route\n" + route, true), undefined, false],
    ["py-loop-rebind", select("from .at18_fixture_feed import discard\nfor route in [discard]:\n    " + route, true), undefined, false],
    ["py-with-rebind", select("from contextlib import nullcontext\nwith nullcontext(None) as route:\n    " + route, true), undefined, false],
    ["py-uncalled-async", select("async def dispatch():\n    " + route + "\n_dispatch = dispatch()\nreturn []", true), undefined, false],
    ["py-handler-rebind", select("try:\n    raise ValueError()\nexcept ValueError as route:\n    " + route, true), undefined, false],
  ] as const) await t.test(id, async () => {
    const { report } = await control({ feedReplacement, feedIntegration, feedTest }, "R9/feed/" + id);
    feedWireResult(report, accepts);
  });
});

function feedWireResult(report: At18Report, accepts: boolean) {
  assert.equal(legacyRow(report, 1319).disposition_valid, accepts);
  if (accepts) positive(report);
  else {
    assert.equal(report.overall_result, "FAIL");
    assert.deepEqual(report.failed_checks.map(row => [row.check_id, row.scope]),
      [["LEGACY_DISPOSITION", "ticket:1319@ISSUE_1319_FEED_WIRE"]]);
  }
}

test("R9/#1319：Rust 块作用域与闭包、局部 fn 调用分别核验", {
  skip: !pathExistsGit, timeout: 360_000,
}, async t => {
  const wire = (body: string) => "use newchan_rust::at18_fixture_wire::probe::handshake;\n#[test]\n" +
    "fn check_connection() {\n    " + body + "\n}\n";
  const invoke = 'assert!(handshake("HELLO"));';
  const wireProbe = 'pub fn handshake(banner: &str) -> bool { banner.starts_with("HELLO") }\n' +
    'pub fn other(_: &str) -> bool { false }\n';
  for (const [id, body, accepts] of [
    ["rs-local-fn", 'fn handshake(_: &str) -> bool { false }\n    assert!(!handshake("HELLO"));', false],
    ["rs-deferred", 'let _on_banner = || handshake("HELLO");', false],
    ["rs-wildcard-closure", 'let _ = move || handshake("HELLO");', false],
    ["rs-unused-async-closure", 'let _ = async move || handshake("HELLO");', false],
    ["rs-uninvoked-fn", 'fn dead() { handshake("HELLO"); }', false],
    ["rs-closure-parameter", 'let f = |handshake: fn(&str) -> bool| handshake("HELLO"); assert!(!f(|_| false));', false],
    ["rs-destructured-parameter", 'let f = |(handshake, _): (fn(&str) -> bool, bool)| handshake("HELLO"); assert!(!f((|_| false, true)));', false],
    ["rs-fn-parameter", 'fn run(handshake: fn(&str) -> bool) { assert!(!handshake("HELLO")); } run(|_| false);', false],
    ["rs-local-use", '{ assert!(!handshake("HELLO")); use newchan_rust::at18_fixture_wire::probe::other as handshake; }', false],
    ["rs-shadow-until-block-end", "{ fn handshake(_: &str) -> bool { false } } " + invoke, true],
    ["rs-local-use-positive", '{ use newchan_rust::at18_fixture_wire::probe::handshake as check; assert!(check("HELLO")); }', true],
    ["rs-immediate-closure", 'assert!((|| handshake("HELLO"))());', true],
    ["rs-bound-closure", 'let f = || { handshake("HELLO") }; assert!(f());', true],
    ["rs-called-local-fn", 'run(); fn run() { assert!(handshake("HELLO")); }', true],
    ["rs-passes-closure-to-local-fn", 'fn run(f: impl FnOnce() -> bool) -> bool { f() } assert!(run(|| handshake("HELLO")));', true],
    ["rs-passes-closure-to-dead-argument", 'fn run(_: impl FnOnce() -> bool) -> bool { true } assert!(run(|| handshake("HELLO")));', false],
    ["rs-unknown-macro-does-not-evaluate", 'macro_rules! discard { ($e:expr) => { true } } assert!(discard!(handshake("HELLO")));', false],
    ["rs-qualified-direct", 'assert!(newchan_rust::at18_fixture_wire::probe::handshake("HELLO"));', true],
  ] as const) await t.test(id, async () => {
    const { report } = await control({ wireCase: "public-entry", wireProbe, wireTest: wire(body) }, "R9/wire/" + id);
    feedWireResult(report, accepts);
  });
  for (const [id, body, accepts] of [
    ["rs-production-unused-closure", "let _ = || accept(banner); false", false],
    ["rs-production-unused-fn", 'fn dead() { accept("HELLO"); } false', false],
    ["rs-production-called-closure", "let call = || accept(banner); call()", true],
    ["rs-production-called-fn", "fn call(b: &str) -> bool { accept(b) } call(banner)", true],
  ] as const) await t.test(id, async () => {
    const wireIntegration = "use at18_fixture_wire::probe::handshake as accept;\n" +
      "pub fn select_wire(banner: &str) -> bool { " + body + " }\n";
    const { report } = await control({ wireIntegration, wireTest: wire(invoke) }, "R9/wire/" + id);
    feedWireResult(report, accepts);
  });
});

// 与正式 CLI 共用接线核验器；用最小树穷举语法分支，不重建整图证据。
function feedSource(files: Record<string, string>) {
  const repository = new At18Repository(root);
  repository.tree = () => new Map(Object.keys(files).map(path => [path, { mode: "100644", kind: "blob", oid: G0 }]));
  repository.blob = (_head, path) => {
    if (!Object.hasOwn(files, path)) throw new Error("missing fixture path: " + path);
    return Buffer.from(files[path]);
  };
  return repository;
}

test("R10/#1319：Python 声明目标、延迟体驱动和 CPython 生产调用链", {
  timeout: 180_000,
}, async t => {
  const from = "from .at18_fixture_feed import ";
  const feed = "trading_system.at18_fixture_feed";
  const call = "route('1min', sources, events)";
  const integration = (body: string, prefix = "") =>
    "\n" + prefix + "\ndef select_feed(sources, events):\n" + body.split("\n").map(line => "    " + line).join("\n") + "\n";
  const direct = `from ${feed} import route\ndef test_route():\n    assert list(route('1min', {}, [1, 2])) == [1, 2]\n`;
  const publicTest = "from trading_system import select_feed\ndef test_route():\n    assert list(select_feed({}, [1, 2])) == [1, 2]\n";
  const replacement = "def route(granularity, sources, events):\n    return events\n\n" +
    "def discard(granularity, sources, events):\n    return []\n";
  const generator = from + "route\ndef batches():\n    yield from " + call + "\ng = batches()\n";
  const genexp = from + "route\ng = (" + call + " for _ in [0])\n";
  const batches = from + "route\ndef batches():\n    yield []\n    yield " + call + "\nit = batches()\n";
  const nestedBatches = from + "route\ndef inner():\n    yield []\n    yield " + call +
    "\ndef batches():\n    yield from inner()\nit = batches()\n";
  const genexpCursor = from + "route\ndef batch(index):\n    if index:\n        return " + call +
    "\n    return []\nit = (batch(i) for i in [0, 1])\n";
  const switching = (declaration: string, bind: string, initial: string, global = false) =>
    integration((global ? "" : from + initial + "\n") +
      "def switch():\n    " + declaration + " route\n    " + bind + "\nswitch()\nreturn " + call,
      global ? from + initial + "\n" : "");
  const cases: [string, string, string, boolean][] = [
    ["nonlocal-switch", switching("nonlocal", "route = discard", "route, discard"), direct, false],
    ["nonlocal-restore-import", switching("nonlocal", from + "route", "discard as route"), direct, true],
    ["nonlocal-delete", switching("nonlocal", "del route", "route"), direct, false],
    ["nonlocal-walrus", switching("nonlocal", "(route := discard)", "route, discard"), direct, false],
    ["nonlocal-loop", switching("nonlocal", "for route in [discard]:\n        pass", "route, discard"), direct, false],
    ["nonlocal-with", switching("nonlocal", "with nullcontext(discard) as route:\n        pass", "route, discard").replace("def switch():", "from contextlib import nullcontext\n    def switch():"), direct, false],
    ["nonlocal-def", switching("nonlocal", "def route(*args):\n        return []", "route"), direct, false],
    ["global-switch", switching("global", "route = discard", "route, discard", true), direct, false],
    ["global-restore", switching("global", from + "route", "discard as route", true), direct, true],
    ["global-delete", switching("global", "del route", "route", true), direct, false],
    ["global-class", switching("global", "class route:\n        pass", "route", true), direct, false],
    ["generator-discarded", integration(generator + "return []"), direct, false],
    ["generator-next-stops-at-first-yield", integration(from + "route\ndef batches():\n    yield 0\n    " + call +
      "\nnext(batches())\nreturn []"), direct, false],
    ["r11-generator-loop-break-first-yield", integration(batches + "for first in it:\n    break\nreturn first"), direct, false],
    ["r11-generator-loop-return-first-yield", integration(batches + "for first in it:\n    return first\nreturn []"), direct, false],
    ["r11-generator-loop-drain", integration(batches + "for last in it:\n    pass\nreturn last"), direct, true],
    ["r11-generator-next-once", integration(batches + "return next(it)"), direct, false],
    ["r11-generator-next-twice", integration(batches + "next(it)\nreturn next(it)"), direct, true],
    ["r11-yield-from-next-once", integration(nestedBatches + "return next(it)"), direct, false],
    ["r11-yield-from-next-twice", integration(nestedBatches + "next(it)\nreturn next(it)"), direct, true],
    ["r11-genexpr-next-once", integration(genexpCursor + "return next(it)"), direct, false],
    ["r11-genexpr-next-twice", integration(genexpCursor + "alias = it\nnext(alias)\nreturn next(it)"), direct, true],
    ["generator-returned", integration(generator + "return g"), direct, true],
    ["generator-consumed", integration(generator + "return list(g)"), publicTest, true],
    ["generator-nested-yield-is-not-outer-yield",
      integration(from + "route\ndef unused():\n    yield 1\n" + call + "\nreturn []"), direct, true],
    ["genexp-discarded", integration(genexp + "return []"), direct, false],
    ["genexp-eager-first-iter", integration(from + "route\ng = (x for x in " + call + ")\nreturn []"), direct, true],
    ["genexp-empty-input", integration(from + "route\ng = (" + call + " for _ in [])\nreturn list(g)"), direct, false],
    ["genexp-consumed", integration(genexp + "return list(g)[0]"), publicTest, true],
    ["genexp-filter-false", integration(from + "route\nreturn list(" + call + " for _ in [0] if False)"), direct, false],
    ["list-comprehension-eager", integration(from + "route\nreturn [" + call + " for _ in [0]]"), direct, true],
    ["set-comprehension-eager", integration(from + "route\nreturn {tuple(" + call + ") for _ in [0]}"), direct, true],
    ["dict-comprehension-eager", integration(from + "route\nreturn {i: " + call + " for i in [0]}"), direct, true],
    ["literal-dead-if", integration(from + "route\nif False:\n    return " + call + "\nreturn []"), direct, false],
    ["literal-dead-while", integration(from + "route\nwhile False:\n    " + call + "\nreturn []"), direct, false],
    ["literal-while-else", integration(from + "route\nwhile False:\n    pass\nelse:\n    return " + call), direct, true],
    ["async-gen-dropped", integration(from + "route\nasync def stream():\n    yield " + call + "\nstream()\nreturn []"), direct, false],
    ["async-gen-driven", integration("import asyncio\n" + from + "route\nasync def stream():\n    yield " + call +
      "\nasync def collect():\n    async for batch in stream():\n        return batch\nreturn asyncio.run(collect())"), direct, true],
    ["coroutine-run", integration("from asyncio import run\n" + from + "route\nasync def dispatch():\n    return " + call +
      "\nreturn run(dispatch())"), direct, true],
    ["runtime-chain", integration(from + "route\nhandlers = {'read': route}\nreturn handlers['read']('1min', sources, events)"), publicTest, true],
    ["runtime-same-file-helper-bypass", integration("return []", from + "route\ndef _read():\n    return route('1min', {}, [1, 2])\n"),
    "from trading_system import _read\ndef test_route():\n    assert _read() == [1, 2]\n", false],
    ["runtime-returned-generator", integration(from + "route\ndef stream():\n    handlers = [route]\n    yield from handlers[0]('1min', sources, events)\nreturn stream()"), publicTest, true],
    ["runtime-discarded-generator-not-origin-proof", integration(from + "route\ndef stream():\n    handlers = [route]\n    yield from handlers[0]('1min', sources, events)\nstream()\nreturn []"), direct, false],
  ];
  for (const consume of ["list(g)", "tuple(g)", "set(g)", "sum(g)", "any(g)", "all(g)", "min(g)", "max(g)", "sorted(g)",
    "[*g]", "(*g,)", "next(g)", "g.__next__()", "g.send(None)", "for _ in g:\n    pass"]) {
    const body = consume.startsWith("for") ? consume + "\nreturn []" : "return " + consume;
    cases.push(["sync-drive-" + consume.split("\n")[0], integration(generator + body), direct, true]);
  }
  cases.push(["sync-drive-yield-from", integration(generator + "yield from g"), direct, true],
    ["sync-drive-dict", integration(genexp + "return dict((i, row) for i, row in enumerate(g))"), publicTest.replace(
      "list(select_feed({}, [1, 2])) == [1, 2]", "select_feed({}, [1, 2]) == {0: [1, 2]}"), true],
    ["sync-drive-join", integration(from + "route\ng = (str(" + call + ") for _ in [0])\nreturn ''.join(g)"), direct, true]);
  const exhaust = (source: string, step: string, handler: string, onError = "return []") =>
    integration(from + "route\n" + source +
      "\ntry:\n    next(it)\n    " + step + "\n    return " + call + "\n" + handler + "\n    " + onError);
  const oneGenerator = "def stream():\n    yield 0\nit = stream()";
  for (const [id, source] of [["list", "it = iter([0])"], ["tuple", "it = iter(tuple([0]))"],
    ["generator", oneGenerator]] as const) {
    cases.push(
      ["r12-exhaust-" + id, exhaust(source, "next(it)", "except StopIteration:"), direct, false],
      ["r12-exhaust-default-" + id, exhaust(source, "next(it, 0)", "except StopIteration:"), direct, true],
    );
  }
  const cleanup = from + "route\nout = []\ndef stream():\n    try:\n        yield 0\n" +
    "    finally:\n        out.extend(" + call + ")\nit = stream()\n";
  cases.push(
    ["r12-exhaust-dunder-bare", exhaust(oneGenerator, "it.__next__()", "except:"), direct, false],
    ["r12-exhaust-catches-exception", exhaust(oneGenerator, "it.__next__()", "except (TypeError, Exception):"), direct, false],
    ["r12-exhaust-skips-wrong-handler", exhaust(oneGenerator, "it.__next__()", "except IndexError:", "return " + call), direct, false],
    ["r12-exhaust-handler-runs", exhaust(oneGenerator, "it.__next__()", "except StopIteration:",
      "return " + call).replace("    return " + call + "\nexcept", "    return []\nexcept"), direct, true],
    ["r12-exhaust-finally-runs", integration(from + "route\n" + oneGenerator +
      "\ntry:\n    next(it)\n    next(it)\n    return []\nfinally:\n    " + call), direct, true],
    ["r12-close-created", integration(cleanup + "it.close()\nreturn out"), direct, false],
    ["r12-close-suspended", integration(cleanup + "next(it)\nit.close()\nreturn out"), direct, true],
    ["r12-close-after-break", integration(cleanup + "for _ in it:\n    break\nit.close()\nreturn out"), direct, true],
    ["r12-break-without-close", integration(cleanup + "for _ in it:\n    break\nreturn (out, it)"), direct, false],
    ["r12-with-closing-created", integration(cleanup +
      "from contextlib import closing\nwith closing(it):\n    pass\nreturn out"), direct, false],
    ["r12-with-closing-suspended", integration(cleanup +
      "import contextlib as ctx\nwith ctx.closing(it) as cursor:\n    next(cursor)\nreturn out"), direct, true],
    ["r12-close-nested-finally-order", integration(from + "route, discard\nout = []\n" +
      "def stream():\n    chosen = discard\n    try:\n        try:\n            yield 0\n" +
      "        finally:\n            chosen = route\n    finally:\n        out.extend(chosen('1min', sources, events))\n" +
      "it = stream()\nnext(it)\nit.close()\nreturn out"), direct, true],
    ["r12-close-delegated-finally", integration(cleanup.replace("it = stream()", "def outer():\n    yield from stream()\nit = outer()") +
      "next(it)\nit.close()\nreturn out"), direct, true],
  );
  const stop = from + "route\ndef stream():\n    if False:\n        yield\n    return route\n";
  const relay = "def relay():\n    return (yield from stream())\n";
  const readStop = "try:\n    next(it)\nexcept StopIteration as stop:\n    return stop.value('1min', sources, events)";
  const reraised = (rethrow: string, caught: string) => integration(from + "route\n" +
    "try:\n    try:\n        next(iter([]))\n    except StopIteration as stop:\n        " + rethrow +
    "\nexcept " + caught + ":\n    return " + call + "\nexcept Exception:\n    return []");
  cases.push(
    ["r13-bare-reraise-skips-other", reraised("raise", "IndexError"), direct, false],
    ["r13-bare-reraise-keeps-kind", reraised("raise", "StopIteration"), direct, true],
    ["r13-named-reraise-skips-other", reraised("raise stop", "IndexError"), direct, false],
    ["r13-reraise-inside-finally", integration(from + "route\ntry:\n    try:\n        raise StopIteration(route)\n" +
      "    finally:\n        raise\nexcept StopIteration as stop:\n    return stop.value('1min', sources, events)"), direct, true],
    ["r13-raised-instance-args", integration(from + "route\nfrom builtins import StopIteration as Finish\nDone = Finish\n" +
      "error = Done(route)\ntry:\n    raise error\nexcept Done as stop:\n    return stop.args[0]('1min', sources, events)"), direct, true],
    ["r13-generator-stop-value", integration(stop + "it = stream()\n" + readStop), direct, true],
    ["r13-delegated-stop-value-after-reraise", integration(stop + relay + "it = relay()\n" +
      "try:\n    try:\n        it.__next__()\n    except StopIteration as stop:\n        raise stop\n" +
      "except StopIteration as stop:\n    return stop.value('1min', sources, events)"), direct, true],
    ["r13-exhausted-generator-loses-old-value", integration(stop +
      "it = stream()\nnext(it, None)\n" + readStop), direct, false],
    ["r13-suspended-except-does-not-leak", integration(from + "route\n" +
      "def stream():\n    try:\n        raise StopIteration\n    except StopIteration:\n        yield 1\n" +
      "it = stream()\nnext(it)\ntry:\n    raise\nexcept StopIteration:\n    return []\n" +
      "except RuntimeError:\n    return " + call), direct, true],
    ["r13-restores-generator-exception", integration(from + "route\n" +
      "def stream():\n    try:\n        try:\n            raise IndexError(route)\n" +
      "        except IndexError:\n            yield 1\n            raise\n" +
      "    except IndexError as error:\n        yield error.args[0]\n" +
      "it = stream()\nnext(it)\nreturn next(it)('1min', sources, events)"), direct, true],
  );
  for (const [id, expr, accepts] of [
    ["set-equivalent-numbers", "set([1, True, 1.0, 1+0j])", false],
    ["set-tuple-equality", "set([(None, 1), (None, True)])", false],
    ["frozenset-duplicates", "frozenset([b'x', b'x'])", false],
    ["literal-set", "{-1, -1.0}", false],
    ["dict-duplicate-keys", "{1: 'a', True: 'b'}", false],
    ["dict-order-not-set-order", "{1: 'a', '1': 'b'}", true],
    ["set-two-distinct", "set([(1, None), (1, False)])", true],
    ["list-keeps-repeats", "[1, 1]", true],
    ["set-unknown-cannot-prove-extra", "set([1, events[0]])", false],
  ] as const) {
    cases.push(["r13-" + id, exhaust("it = iter(" + expr + ")", "next(it)", "except StopIteration:"), direct, accepts]);
  }
  const dictionaryKey = (key: string, normal: boolean) => integration(from + "route\ntry:\n    keys = {" +
    key + ": 0}\nexcept TypeError:\n    return " + (normal ? "[]" : call) + "\nreturn " + (normal ? call : "[]"));
  cases.push(
    ["r14-frozenset-normal", dictionaryKey("frozenset([1])", true), direct, true],
    ["r14-frozenset-except", dictionaryKey("frozenset([1])", false), direct, false],
    ["r14-set-normal", dictionaryKey("set([1])", true), direct, false],
    ["r14-set-except", dictionaryKey("set([1])", false), direct, true],
    ["r14-named-exception-tuple", reraised("raise stop", "handled").replace("    try:", "    handled = (IndexError, StopIteration)\n    try:"), direct, true],
    ["r14-yield-from-none", integration(from + "route\ndef inner():\n    if False:\n        yield\n    return None\n" +
      "def outer():\n    if (yield from inner()):\n        yield " + call + "\nreturn list(outer())"), direct, false],
    ["r14-production-raises-after-entry", integration(from + "route\n" + call + "\nraise RuntimeError()"), direct, true],
    ["r14-production-stdout-is-not-the-receipt", integration("print('selecting feed')\n" +
      "os.write(1, b'low-level feed log\\n')\nreturn " + call, "import os\n" + from + "route\n" +
      "print('feed imported')\n"), direct, true],
    ["r14-import-time-dispatch", from + "route\nroute('1min', {}, [])\ndef select_feed():\n    return []", direct, false],
    ["r14-imported-export-not-a-public-entry", from + "route as select_feed", direct, false],
    ["r14-private-class-constructor", from + "route\nclass Feed:\n    def __init__(self):\n        route('1min', {}, [])\n" +
      "    def select_feed(self):\n        return []", direct, false],
    ["r14-public-static-async", from + "route\nclass Feed:\n    @staticmethod\n" +
      "    async def select_feed(sources, /, *, events):\n        if events[0] == 1:\n            return " + call, direct, true],
    ["r14-public-async-generator-return", integration(from + "route\nasync def batches():\n    yield " + call + "\nreturn batches()"), direct, true],
    ["r14-container-is-not-a-generator-return", integration(generator + "return (g,)"), direct, false],
    ["r14-returned-generator-test-never-consumes", integration(generator + "return g"),
      "from trading_system import select_feed\ndef test_route():\n    assert select_feed({}, [1, 2]) is not None", false],
  );
  for (const [id, feedIntegration, feedTest, accepts] of cases) await t.test(id, async () => {
    const entry = "trading_system/at18_fixture_feed.py";
    const production = "trading_system/__init__.py";
    const testPath = "trading_system/tests/test_at18_fixture_feed.py";
    const repository = feedSource({ [entry]: replacement, [production]: feedIntegration, [testPath]: feedTest });
    assert.equal(pythonReplacement(repository, G0, entry, production, testPath, "test_route", 1), accepts);
  });
});

test("R15–R16/#1319：Python 公开承接、初始化排除与显式等待", { timeout: 180_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const production = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const imported = "from .at18_fixture_feed import route\n";
  const direct = "from trading_system.at18_fixture_feed import route\n" +
    "def test_route():\n    assert route([1, 2]) == [1, 2]\n";
  const through = "from trading_system import select_feed\ndef test_route():\n    assert select_feed([1, 2]) == [1, 2]\n";
  const through_async = "import asyncio\nfrom trading_system import select_feed\n" +
    "def test_route():\n    assert asyncio.run(select_feed([1, 2])) == [1, 2]\n";
  const implementations = "def _copy(events):\n    return list(events)\n" +
    "def route(events):\n    return _copy(events)\ndef preview(events):\n    return _copy(events)\n";
  const ordinary = imported + "def select_feed(events):\n    return route(events)\n";
  const reload = "from importlib import reload\nimport trading_system\n" +
    "def test_route():\n    assert reload(trading_system).cached == [1, 2]\n";
  const init = imported + "class Feed:\n    def __init__(self, events):\n        self.cached = self.read(events)\n" +
    "    def read(self, events):\n        return self.cached if hasattr(self, 'cached') else route(events)\n";
  const construct = "from trading_system import Feed\ndef test_route():\n" +
    "    assert Feed([1, 2]).read([]) == [1, 2]\n";
  const async_code = (body: string) => "import asyncio\n" + imported +
    "async def _child(events):\n    return route(events)\nasync def select_feed(events):\n" +
    body.split("\n").map(s => "    " + s).join("\n") + "\n";
  const check = (impl: string, wire: string, registered: string, expected: boolean) => {
    const repo = feedSource({ [entry]: impl, [production]: wire, [path]: registered });
    assert.equal(pythonReplacement(repo, G0, entry, production, path, "test_route", 1), expected);
  };
  for (const [name, impl, wire, registered, expected] of [
    ["私有助手交集不算承接", implementations, ordinary, direct.replace("assert route(", "assert preview(").replace("import route", "import preview"), false],
    ["同一公开导出经过私有助手", implementations, ordinary, direct, true],
    ["字面 __all__ 排除公开命名的函数", implementations + "__all__ = ['preview']\n", ordinary, direct, false],
    ["解包 __all__ 排除承接函数", implementations + "PUBLIC = ['preview']\n__all__ = [*PUBLIC]\n", ordinary, direct, false],
    ["拼接 __all__ 排除承接函数", implementations + "BASE = []\n__all__ = BASE + ['preview']\n", ordinary, direct, false],
    ["拼接 __all__ 保留承接函数", implementations + "BASE = ['preview']\n__all__ = BASE + ['route']\n", ordinary, direct, true],
    ["推导和 tuple 动态隐藏生产入口", implementations,
      ordinary + "__all__ = tuple(name for name in ['route'])\n", through, false],
    ["函数返回的 __all__ 排除承接函数", implementations +
      "def _public():\n    return ('preview',)\n__all__ = _public()\n", ordinary, direct, false],
    ["函数返回的 __all__ 保留生产入口", implementations,
      ordinary + "def _public():\n    return ('select_feed',)\n__all__ = _public()\n", through, true],
    ["非法 __all__ 类型不退回默认公开名", implementations + "__all__ = 1\n", ordinary, direct, false],
    ["非字符串 __all__ 元素使整张生产清单失效", implementations,
      ordinary + "__all__ = ['select_feed', None]\n", through, false],
    ["__all__ 读取异常使整张清单失效", implementations + "class _Exports:\n" +
      "    def __getitem__(self, i):\n        if i == 0:\n            return 'route'\n        raise ValueError()\n__all__ = _Exports()\n",
      ordinary, direct, false],
    ["__all__ 按 CPython 的整数下标读取", implementations + "class _Exports:\n" +
      "    def __getitem__(self, i):\n        return ('route',)[i]\n" +
      "    def __iter__(self):\n        return iter(('preview',))\n__all__ = _Exports()\n", ordinary, direct, true],
    ["字面 __all__ 可显式导出下划线函数", implementations + "__all__ = ('_copy',)\n",
      ordinary.replaceAll("route", "_copy"), direct.replace("assert route(", "assert _copy(").replace("import route", "import _copy"), true],
    ["实现公开类方法", "class Route:\n    @classmethod\n    def route(cls, events):\n        return list(events)\n",
      ordinary.replace("import route", "import Route").replace("return route(", "return Route.route("),
      direct.replace("import route", "import Route").replace("assert route(", "assert Route.route("), true],
    ["仅初始化重载", implementations, ordinary + "cached = select_feed([1, 2])\n", reload, false],
    ["重载结束后的测试调用", implementations, ordinary + "cached = select_feed([1, 2])\n",
      reload.replace("assert reload(trading_system).cached", "assert reload(trading_system).select_feed([1, 2])"), true],
    ["仅通过 __init__ 记入的缓存", implementations, init, construct, false],
    ["公开入口正常进入后可以调用构造器", implementations,
      init + "def select_feed(events):\n    return Feed(events).cached\n", through, true],
    ["仅通过 __new__ 记入的缓存", implementations,
      imported + "class Feed:\n    def __new__(cls, events):\n        self = object.__new__(cls)\n" +
      "        self.cached = self.read(events)\n        return self\n" +
      "    def read(self, events):\n        return self.cached if hasattr(self, 'cached') else route(events)\n", construct, false],
    ["try else 的定义进入公开集合", implementations,
      "try:\n    " + imported + "except ImportError:\n    raise\nelse:\n" +
      "    def select_feed(events):\n        return route(events)\n", through, true],
    ["with match 中的公开类静态方法", implementations,
      "from contextlib import nullcontext\n" + imported + "with nullcontext():\n    match 1:\n" +
      "        case 1:\n            class Feed:\n                if True:\n                    @staticmethod\n" +
      "                    def read(events):\n                        return route(events)\n", direct, true],
    ["同一源定义仍以公开别名存在", implementations,
      ordinary + "template = select_feed\ndef select_feed(events):\n    return []\n",
      through.replaceAll("select_feed", "template"), true],
    ["不计被覆盖而不再导出的定义", implementations,
      ordinary + "_template = select_feed\ndef select_feed(events):\n    return []\n",
      through.replaceAll("select_feed", "_template"), false],
    ["生产 __all__ 排除测试调用的入口", implementations, ordinary + "__all__ = []\n", through, false],
  ] as const) await t.test(name, () => check(impl, wire, registered, expected));
  const variants = [
    ["gather", "return (await asyncio.gather(_child(events)))[0]", true],
    ["gather of gather", "return (await asyncio.gather(asyncio.gather(_child(events))))[0][0]", true],
    ["wait for a gather", "batch = asyncio.gather(_child(events))\n" +
      "done, _ = await asyncio.wait({batch})\nreturn done.pop().result()[0]", true],
    ["shield wraps a gather", "return (await asyncio.shield(asyncio.gather(_child(events))))[0]", true],
    ["a gather waits on shield", "return (await asyncio.gather(asyncio.shield(_child(events))))[0]", true],
    ["wait_for wraps a shielded gather", "batch = asyncio.shield(asyncio.gather(_child(events)))\n" +
      "return (await asyncio.wait_for(batch, 1))[0]", true],
    ["wait_for consumes a completed gather with zero timeout", "batch = asyncio.gather(_child(events))\n" +
      "while not batch.done():\n    await asyncio.sleep(0)\nreturn (await asyncio.wait_for(batch, 0))[0]", true],
    ["as_completed consumes a gather", "batch = asyncio.gather(_child(events))\n" +
      "for item in asyncio.as_completed([batch]):\n    return (await item)[0]", true],
    ["TaskGroup task awaits a gather", "async def relay():\n    return (await asyncio.gather(_child(events)))[0]\n" +
      "async with asyncio.TaskGroup() as group:\n    task = group.create_task(relay())\nreturn task.result()", true],
    ["task", "task = asyncio.create_task(_child(events))\nreturn await task", true],
    ["already-done task", "task = asyncio.create_task(_child(events))\nawait asyncio.sleep(0)\nreturn await task", true],
    ["wait", "task = asyncio.create_task(_child(events))\nawait asyncio.wait({task})\nreturn task.result()", true],
    ["TaskGroup", "async with asyncio.TaskGroup() as group:\n    task = group.create_task(_child(events))\nreturn task.result()", true],
    ["transitive", "async def relay():\n    return await asyncio.create_task(_child(events))\n" +
      "return (await asyncio.gather(relay()))[0]", true],
    ["dropped task runs anyway", "asyncio.create_task(_child(events))\nawait asyncio.sleep(0)\nreturn events", false],
    ["dropped gather runs anyway", "asyncio.gather(_child(events))\nawait asyncio.sleep(0)\nreturn events", false],
    ["a joined gather cannot vouch for a parallel discarded gather", "asyncio.gather(_child(events))\n" +
      "await asyncio.gather(asyncio.sleep(0))\nreturn events", false],
    ["a timed-out wait does not vouch for a late gather", "gate = asyncio.Event()\nasync def delayed():\n" +
      "    await gate.wait()\n    return await _child(events)\nbatch = asyncio.gather(delayed())\n" +
      "done, pending = await asyncio.wait({batch}, timeout=0)\nassert not done and batch in pending\n" +
      "gate.set()\nwhile not batch.done():\n    await asyncio.sleep(0)\nreturn events", false],
    ["an as_completed item left unawaited cannot vouch for its gather", "gate = asyncio.Event()\nasync def delayed():\n" +
      "    await gate.wait()\n    return await _child(events)\nbatch = asyncio.gather(delayed())\n" +
      "items = iter(asyncio.as_completed([asyncio.sleep(0), batch]))\nawait next(items)\n" +
      "next(items).close()\ngate.set()\nwhile not batch.done():\n    await asyncio.sleep(0)\nreturn events", false],
    ["a wait_for timeout does not consume the shielded gather", "gate = asyncio.Event()\nasync def delayed():\n" +
      "    await gate.wait()\n    return await _child(events)\nbatch = asyncio.gather(delayed())\n" +
      "try:\n    await asyncio.wait_for(asyncio.shield(batch), 0)\nexcept TimeoutError:\n    pass\n" +
      "gate.set()\nwhile not batch.done():\n    await asyncio.sleep(0)\nreturn events", false],
    ["a failed gather does not consume late siblings", "gate = asyncio.Event()\nasync def delayed():\n" +
      "    await gate.wait()\n    return await _child(events)\nasync def fail():\n    raise ValueError()\n" +
      "task = asyncio.create_task(delayed())\nbatch = asyncio.gather(fail(), task)\n" +
      "while not batch.done():\n    await asyncio.sleep(0)\ngate.set()\n" +
      "while not task.done():\n    await asyncio.sleep(0)\ntry:\n    await batch\nexcept ValueError:\n    pass\nreturn events", false],
    ["wait does not consume its uncompleted task", "gate = asyncio.Event()\nasync def delayed():\n" +
      "    await gate.wait()\n    return await _child(events)\ntask = asyncio.create_task(delayed())\n" +
      "await asyncio.wait({task}, timeout=0)\ngate.set()\nawait asyncio.sleep(0)\nreturn events", false],
    ["awaited parent cannot vouch for its orphan", "async def relay():\n    asyncio.create_task(_child(events))\n" +
      "    await asyncio.sleep(0)\n    return events\nreturn await asyncio.create_task(relay())", false],
  ] as const;
  for (const [name, body, expected] of variants) {
    await t.test("补跑：" + name, () => check(implementations, async_code(body), direct, expected));
    await t.test("登记：" + name, () => check(implementations, async_code(body), through_async, expected));
  }
});

test("R17/#1319：按运行时属性解析整张 Python 导出清单", { timeout: 60_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const production = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const route = "def route(events):\n    return list(events)\n";
  const wire = "from .at18_fixture_feed import route\ndef select_feed(events):\n    return route(events)\n";
  const registered = (mod: string, name: string) =>
    `from ${mod} import ${name}\ndef test_route():\n    assert ${name}([1, 2]) == [1, 2]\n`;
  const through = registered("trading_system", "select_feed");
  const direct = registered("trading_system.at18_fixture_feed", "route");
  const dynamic = (name: string) => `def __getattr__(name):
    if name == "__all__":
        return ["${name}"]
    raise AttributeError(name)
`;
  const lazy = (name: string) => `__all__ = ["${name}"]
def __getattr__(name):
    if name == "${name}":
        return _${name}
    raise AttributeError(name)
`;
  for (const [name, replacement, integration, testCode, accepts] of [
    ["承接的动态 __all__ 隐藏 route", route + dynamic("preview") + "preview = 1\n", wire, through, false],
    ["动态 __all__ 显式导出 _route", route.replace("def route", "def _route") + dynamic("_route"),
      wire.replace("import route", "import _route as route"), through, true],
    ["惰性别名指向承接文件的函数", route.replace("def route", "def _route") + lazy("route"), wire, through, true],
    ["承接清单后续缺项否决已解析的 route", route + "__all__ = ['route', 'missing']\n", wire, through, false],
    ["生产的动态 __all__ 隐藏 select_feed", route, wire + dynamic("preview") + "preview = 1\n", through, false],
    ["生产的动态 __all__ 导出私有入口", route,
      wire.replace("def select_feed", "def _select_feed") + dynamic("_select_feed"), direct, true],
    ["惰性生产入口可被独立探针调用", route,
      wire.replace("def select_feed", "def _select_feed") + lazy("select_feed"), direct, true],
    ["生产清单后续缺项同时否决测试路径与探针", route,
      wire + "__all__ = ['select_feed', 'missing']\n", through, false],
    ["读取动态清单的非 AttributeError 不触发默认导出", route,
      wire + "def __getattr__(name):\n    raise RuntimeError(name)\n", through, false],
    ["解析清单成员的非 AttributeError 否决整张清单", route +
      "__all__ = ['route', 'missing']\ndef __getattr__(name):\n    raise RuntimeError(name)\n", wire, through, false],
  ] as const) await t.test(name, () => {
    const repository = feedSource({ [entry]: replacement, [production]: integration, [path]: testCode });
    assert.equal(pythonReplacement(repository, G0, entry, production, path, "test_route", 1), accepts);
  });
});

test("R18/#1319：原生星号导入和冻结文件内的导出绑定", { timeout: 60_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const production = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const backtest = "trading_system/backtest/__init__.py";
  const route = "def route(events):\n    return list(events)\n";
  const imported = "from .at18_fixture_feed import route\n";
  const wire = imported + "def dispatch(events):\n    return route(events)\n";
  const registered = (mod: string, name: string) =>
    `from ${mod} import ${name}\ndef test_route():\n    assert ${name}([13, 21]) == [13, 21]\n`;
  const through = registered("trading_system", "dispatch");
  const direct = registered("trading_system.at18_fixture_feed", "route");
  const check = (impl: string, integration: string, checkCode: string, expected: boolean, support = {}) => {
    const repo = feedSource({ ...support, [entry]: impl, [production]: integration, [path]: checkCode });
    assert.equal(pythonReplacement(repo, G0, entry, production, path, "test_route", 1), expected);
  };
  const indexed = (name: string) => `
class _Exports:
    def __getitem__(self, index):
        return ("${name}",)[index]
    def __iter__(self):
        raise TypeError("index-only table")
__all__ = _Exports()
`;
  await t.test("包的 fromlist 迭代失败否决整张清单", () => check(route, wire + indexed("dispatch"), through, false));
  await t.test("普通模块的整数下标清单有效", () => check(route + indexed("route"), wire, through, true));
  await t.test("包在追踪开始前自动导入未预载子包", () => {
    check(route, wire + "__all__ = ('dispatch', 'backtest')\n", through, true,
      { [backtest]: "import sys\nassert sys.getprofile() is None\n" });
  });
  await t.test("星号导入子包的初始化调用不能算生产接入", () => {
    check(route, wire.replace("return route(events)", "return []") + "__all__ = ('dispatch', 'backtest')\n",
      direct, false, { [backtest]: "from ..at18_fixture_feed import route\nroute([13, 21])\n" });
  });

  function binding(name: string, call: string, variant: "static" | "class" | "bound" | "lazy") {
    const [decorator, receiver, owner] = variant === "class"
      ? ["    @classmethod\n", "cls, ", "_Adapter"]
      : variant === "bound"
        ? ["", "self, ", "_Adapter(42)"]
        : ["    @staticmethod\n", "", "_Adapter"];
    const bind = variant === "lazy"
      ? `def __getattr__(name):\n    if name == "${name}":\n        return ${owner}._apply\n    raise AttributeError(name)\n`
      : `${name} = ${owner}._apply\n`;
    return "class _Adapter:\n    def __init__(self, key):\n        self.key = key\n" +
      decorator + `    def _apply(${receiver}events):\n        return ${call}\n` + bind + `__all__ = ("${name}",)\n`;
  }

  for (const variant of ["static", "class", "bound", "lazy"] as const) {
    await t.test("承接显式导出 " + variant, () =>
      check(binding("route", "list(events)", variant), wire, through, true));
    await t.test("生产显式导出 " + variant, () =>
      check(route, imported + binding("dispatch", "route(events)", variant), through, true));
  }
  await t.test("独立生产探针直接调用已绑定的类方法", () =>
    check(route, imported + binding("_api", "route(events)", "class"), direct, true));
  await t.test("承接默认公开别名指向本文件私有定义", () =>
    check(route.replace("def route", "def _work") + "route = _work\n", wire, through, true));
  await t.test("生产默认公开别名也能由探针调用", () =>
    check(route, wire.replace("def dispatch", "def _work") + "dispatch = _work\n", direct, true));
  await t.test("显式导出外来绑定方法不算本文件入口", () => {
    const foreign = "trading_system/foreign.py";
    check(route, "from .foreign import dispatch\n__all__ = ('dispatch',)\n", through, false,
      { [foreign]: imported + binding("dispatch", "route(events)", "class") });
  });
});

test("R19/#1319：精确导出对象、接收者和重载后的公开键", { timeout: 120_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const production = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const dependency = "trading_system/support.py";
  const route = "def route(events): return list(events)\n";
  const wire = "from .at18_fixture_feed import route\n";
  const dispatch = wire + "def dispatch(events): return route(events)\n";
  const via = (expr: string, prelude = "") => prelude + "import trading_system as p\n" +
    `def test_route():\n    assert ${expr} == [13, 21]\n`;
  const through = via("p.dispatch([13, 21])");
  const direct = via("f.route([13, 21])", "from trading_system import at18_fixture_feed as f\n");
  const check = async (name: string, impl: string, integration: string, registered: string, expected: boolean,
    support: Record<string, string> = {}) => {
    await t.test(name, () => {
      const repo = feedSource({ ...support, [entry]: impl, [production]: integration, [path]: registered });
      assert.equal(pythonReplacement(repo, G0, entry, production, path, "test_route", 1), expected);
    });
  };

  const factories = [
    ["零自由变量", "def make():\n    def f(events): return list(events)\n    return f\n", "make()", "make()"],
    ["相同闭包值", "def make(copy):\n    def f(events): return copy(events)\n    return f\n", "make(list)", "make(list)"],
    ["位置默认参数不同", "def make(tag):\n    def f(events, _tag=tag): return list(events)\n    return f\n", "make(1)", "make(2)"],
    ["关键字默认参数不同", "def make(tag):\n    def f(events, *, _tag=tag): return list(events)\n    return f\n", "make(1)", "make(2)"],
  ] as const;
  const fromEntry = "from trading_system import at18_fixture_feed as f\n";
  for (const [name, factory, real, sibling] of factories) {
    const impl = factory + `route = ${real}\npreview = ${sibling}\nalias = route\n__all__ = ('route', 'preview', 'alias')\n`;
    await check(name + "：另一导出不是承接", impl, dispatch, via("f.preview([13, 21])", fromEntry), false);
    await check(name + "：真别名与原导出相交", impl, dispatch, via("f.alias([13, 21])", fromEntry), true);
  }
  for (const [name, invoke, prelude] of [
    ["普通调用", (expr: string) => `${expr}([13, 21])`, ""],
    ["map 的 C 回调", (expr: string) => `list(map(${expr}, [[13, 21]]))[0]`, ""],
    ["partial 的 C 回调", (expr: string) => `partial(${expr})([13, 21])`, "from functools import partial\n"],
  ] as const) {
    const impl = `class _Adapter:
    def run(self, events): return self.backend(events)
_a, _b = _Adapter(), _Adapter()
_a.backend = list
_b.backend = route
dispatch = _a.run
__all__ = ('dispatch',)
`;
    await check(name + "：私有接收者不冒充公开绑定", route, wire + impl, via(invoke("p._b.run"), prelude), false);
    await check(name + "：重新取出同一接收者的方法", route, wire + impl.replace("dispatch = _a.run", "dispatch = _b.run"),
      via(invoke("p._b.run"), prelude), true);
    const entryImpl = "def make():\n    def run(events): return list(events)\n    return run\n" +
      "route = make()\npreview = make()\n";
    await check(name + "：同体闭包不混算", entryImpl, dispatch, via(invoke("f.preview"), fromEntry + prelude), false);
    await check(name + "：同一闭包可追踪", entryImpl, dispatch, via(invoke("f.route"), fromEntry + prelude), true);
  }

  for (const [name, method, asynchronous, harness] of [
    ["协程/create_task", "async def run(self, events): return self.backend(events)", true,
      "import asyncio\nasync def consume(fn): return await asyncio.create_task(fn([13, 21]))\n"],
    ["生成器", "def run(self, events): yield self.backend(events)", false, "def consume(fn): return next(fn([13, 21]))\n"],
    ["异步生成器", "async def run(self, events): yield self.backend(events)", true,
      "import asyncio\nasync def consume(fn): return await anext(fn([13, 21]))\n"],
  ] as const) {
    const impl = wire + `class _Adapter:
    ${method}
_a, _b = _Adapter(), _Adapter()
_a.backend, _b.backend = list, route
dispatch = _a.run
__all__ = ('dispatch',)
`;
    const run = (expr: string) => asynchronous ? `asyncio.run(consume(${expr}))` : `consume(${expr})`;
    await check(name + "：执行另一个接收者不算覆盖", route, impl, via(run("p._b.run"), harness), false);
    await check(name + "：已消费的精确绑定计入", route, impl.replace("dispatch = _a.run", "dispatch = _b.run"),
      via(run("p._b.run"), harness), true);
  }

  const decorate = (wraps: boolean) => `from functools import wraps
def _observe(fn):
    ${wraps ? "@wraps(fn)\n    " : ""}def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper
`;
  for (const [kind, descriptor, receiver, member] of [
    ["实例", "", "self, ", "Adapter().run"],
    ["静态", "    @staticmethod\n", "", "Adapter.run"],
    ["类", "    @classmethod\n", "cls, ", "Adapter.run"],
  ] as const) {
    for (const wraps of [true, false]) {
      const head = decorate(wraps) + `class Adapter:\n${descriptor}    @_observe\n    @_observe\n`;
      const signature = `    def run(${receiver}events): `;
      const label = kind + (wraps ? "/wraps" : "/不声明 wraps");
      const adapted = (obj: string) => `${member.replace("Adapter", obj + ".Adapter")}([13, 21])`;
      await check(label + "：多层透传的生产方法可由独立探针调用", route,
        wire + head + signature + "return route(events)\n", direct, true);
      const wired = `from .at18_fixture_feed import Adapter\ndef dispatch(events): return ${member}(events)\n`;
      await check(label + "：多层透传的承接方法", head + signature + "return list(events)\n", wired, through, true);
      await check(label + "：装饰器不能给 pass 桩生成证据", head + signature + "pass\n", wired,
        via(`${adapted("f")} is None and [13, 21]`, fromEntry), false);
    }
  }
  const external = "class Worker: pass\ndef run(events): return list(events)\n";
  const wiredClass = "from .at18_fixture_feed import Adapter\ndef dispatch(events): return Adapter.run(events)\n";
  for (const wraps of [true, false]) {
    const foreign = decorate(wraps) + "from .support import run\nclass Adapter:\n    run = staticmethod(_observe(run))\n";
    await check("外来实现经过本地类装饰器/" + wraps, foreign, wiredClass, through, false,
      { [dependency]: external });
    const stub = decorate(wraps) + "@_observe\ndef route(events): pass\n";
    await check("模块装饰器也不能包裹空桩/" + wraps, stub, dispatch,
      via("f.route([13, 21]) is None and [13, 21]", fromEntry), false);
  }
  const spoof = decorate(true) + "from .support import run\n" +
    "def local(events): return list(events)\nclass Adapter:\n    run = staticmethod(_observe(run))\n" +
    "Adapter.run.__wrapped__ = local\n";
  await check("伪造 __wrapped__ 不会改变闭包里的外来实现", spoof, wiredClass, through, false,
    { [dependency]: external });
  const cycle = decorate(true) + "class Adapter:\n    @staticmethod\n    @_observe\n" +
    "    def run(events): return list(events)\nAdapter.run.__wrapped__ = Adapter.run\n";
  await check("带环 __wrapped__ 不能证明承接", cycle, wiredClass, through, false);
  const foreignReceiver = wire + `from .support import Worker
from types import MethodType
class _Local: pass
def _call(receiver, events): return route(events)
Worker.__module__ = __name__
Worker.__qualname__ = '_Local'
dispatch = MethodType(_call, Worker())
__all__ = ('dispatch',)
`;
  await check("外来类的模块名和限定名均可伪造", route, foreignReceiver, through, false, { [dependency]: external });
  await check("本地声明的子类仍是本地接收者", route,
    foreignReceiver.replace("Worker.__module__ = __name__\nWorker.__qualname__ = '_Local'", "class _Derived(Worker): pass")
      .replace("Worker())", "_Derived())"), through, true, { [dependency]: external });
  await check("外来子类不能替代未导出的本地类接收者", route,
    foreignReceiver.replace("from .support import Worker\n", "")
      .replace("Worker.__module__ = __name__\nWorker.__qualname__ = '_Local'", "from .support import Derived")
      .replace("Worker())", "Derived())"), through, false,
    { [dependency]: "from . import _Local\nclass Derived(_Local): pass\n" });
  const realClass = wire + `class Adapter:
    @classmethod
    def run(cls, events): return cls._backend(events)
    _backend = staticmethod(list)
class _Derived(Adapter):
    _backend = staticmethod(route)
dispatch = Adapter.run
__all__ = ('dispatch', 'Adapter')
`;
  await check("公开基类方法覆盖真实子类的绑定", route, realClass, via("p._Derived.run([13, 21])"), true);
  await check("隐藏基类后只承认别名包含的精确接收者", route,
    realClass.replace("('dispatch', 'Adapter')", "('dispatch',)"), via("p._Derived.run([13, 21])"), false);
  const asyncEntry = "async def route(events): return list(events)\n";
  for (const gate of ["gather", "wait"] as const) {
    const consume = gate === "gather" ? "(await asyncio.gather(child))[0]" :
      "(await asyncio.wait((child,)))[0].pop().result()";
    const asyncProduction = "import asyncio\n" + wire +
      `async def dispatch(events):\n    child = asyncio.create_task(route(events))\n    return ${consume}\n`;
    await check("复合 Future 仍须等到精确承接：" + gate, asyncEntry, asyncProduction,
      via("asyncio.run(p.dispatch([13, 21]))", "import asyncio\n"), true);
  }
  const reloaded = (expr: string) => "import importlib\n" + fromEntry +
    `def test_route():\n    old = f.route\n    importlib.reload(f)\n    assert ${expr}([13, 21]) == [13, 21]\n`;
  const closure = factories[0][1] + "route, preview = make(), make()\n";
  await check("reload 后的新对象仍对齐独立探针的规范键", closure, dispatch, reloaded("f.route"), true);
  await check("reload 后 preview 不与 route 对齐", closure, dispatch, reloaded("f.preview"), false);
  await check("reload 后的旧持有引用不能冒充当前公开对象", closure, dispatch, reloaded("old"), false);
});

test("R20/#1319：透传只认本次调用实际执行的本地实现", { timeout: 120_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const production = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const wire = "from . import at18_fixture_feed as f\n";
  const dispatch = wire + "def dispatch(events): return f.route(events)\n";
  const direct = (body: string) =>
    "import asyncio, importlib\nfrom trading_system import at18_fixture_feed as f\nfrom trading_system import dispatch\n" +
    "async def take(gen): return await anext(gen)\ndef test_route():\n" + body.split("\n").map(line => "    " + line + "\n").join("");
  const check = async (name: string, impl: string, integration: string, registered: string, expected: boolean) => {
    await t.test(name, () => {
      const repo = feedSource({ [entry]: impl, [production]: integration, [path]: registered,
        "trading_system/support.py": "def foreign(events): return list(events)\ndef clean(v): return v * 2\n" });
      assert.equal(pythonReplacement(repo, G0, entry, production, path, "test_route", 1), expected);
    });
  };
  const plain = "def route(events): return list(events)\n";
  const basic = direct("assert f.route([13, 21]) == [13, 21]");
  for (const [name, carrier] of [
    ["partial", "relay = partial(fn)\n    return lambda *a, **kw: relay(*a, **kw)"],
    ["自定义对象", "relay = _Carrier(fn)\n    return lambda events: relay(events)"],
    ["字典", "relay = {'call': fn}\n    return lambda events: relay['call'](events)"],
  ] as const) {
    const preamble = `from functools import partial
from .support import foreign
class _Carrier:
    def __init__(self, callback): self.callback = callback
    def __call__(self, events): return self.callback(events)
def _wrap(fn):
    ${carrier}
__all__ = ('route',)
`;
    await check(name + "：本地非空实现", preamble + plain + "route = _wrap(route)\n", dispatch, basic, true);
    await check(name + "：本地空桩", preamble + "def route(events): pass\nroute = _wrap(route)\n",
      dispatch, direct("assert dispatch([13, 21]) is None"), false);
    await check(name + "：外来实现", preamble + "route = _wrap(foreign)\n", dispatch, basic, false);
  }
  await check("本地绑定方法可执行其接收者上的内建转换", `class _Adapter:
    def __init__(self, convert): self.convert = convert
    def read(self, events): return self.convert(events)
route = _Adapter(list).read
`, dispatch, basic, true);
  const defaultBridge = "def _forward(events, fn=backend): return fn(events)\nroute = _forward\n";
  await check("默认可调用参数透传到本地实现", plain + "backend = route\n" + defaultBridge, dispatch, basic, true);
  await check("默认可调用参数透传到外来实现", "from .support import foreign as backend\n" + defaultBridge,
    dispatch, basic, false);
  await check("闭包执行本地计算而非透传", `from .support import clean
def _make(transform):
    def route(events): return [transform(v) for v in events if v > 0]
    return route
route = _make(clean)
`, dispatch, direct("assert f.route([-1, 13, 21]) == [26, 42]"), true);
  const warm = "if 'route' in globals(): cache = route([13, 21])\n" + plain;
  await check("reload 只预热", warm, dispatch, direct("importlib.reload(f)\nassert f.cache == [13, 21]"), false);
  await check("reload 后显式进入新绑定", warm, dispatch,
    direct("importlib.reload(f)\nassert f.route([13, 21]) == [13, 21]"), true);

  for (const [name, constructor] of [
    ["__init__", "def __init__(self, events): self.cache = route(events)"],
    ["__new__", "def __new__(cls, events):\n        self = super().__new__(cls)\n        self.cache = route(events)\n        return self"],
  ] as const) {
    await check("生产公开调用内的承接侧 " + name + " 仍是初始化", plain +
      `class Cache:\n    ${constructor}\n__all__ = ('route',)\n`,
      wire + "def dispatch(events): return f.Cache(events).cache\n",
      direct("assert dispatch([13, 21]) == [13, 21]"), false);
  }

  const layers = `def _wrap(fn):
    def relay(*args, **kwargs): return fn(*args, **kwargs)
    return relay
`;
  const strictDispatch = wire + "def dispatch(events):\n    if events == [13, 21]: return f.route(events)\n";
  for (const [kind, slot, receiver, call] of [
    ["实例", "", "self, ", "Adapter().read"],
    ["类", "    @classmethod\n", "cls, ", "Adapter.read"],
    ["静态", "    @staticmethod\n", "", "Adapter.read"],
  ] as const) {
    const impl = layers + `class Adapter:
${slot}    @_wrap
    @_wrap
    def read(${receiver}events): return list(events)
`;
    const wired = strictDispatch.replace("f.route(events)", `f.${call}(events)`);
    for (const arg of ["[13, 21]", "events=[13, 21]"]) {
      await check(kind + "两层透传采样：" + arg, impl, wired,
        direct(`assert f.${call}(${arg}) == [13, 21]`), true);
    }
  }
  await check("中间包装器的具名样本在叶更名时仍可复用", layers + `def _make(leaf):
    def named(events): return leaf(events)
    return _wrap(named)
def _leaf(batch): return list(batch)
route = _make(_leaf)
`, strictDispatch, basic, true);
  for (const [kind, impl, consume] of [
    ["协程", "async def route(events): return list(events)\n", "asyncio.run(CALL)"],
    ["生成器", "def route(events): yield list(events)\n", "next(CALL)"],
    ["异步生成器", "async def route(events): yield list(events)\n", "asyncio.run(take(CALL))"],
  ] as const) {
    const replacement = layers + "@_wrap\n" + impl;
    await check(kind + "：消费返回值时进入本地叶", replacement, strictDispatch,
      direct("assert " + consume.replace("CALL", "f.route([13, 21])") + " == [13, 21]"), true);
    await check(kind + "：只取得返回值不计覆盖", replacement, strictDispatch,
      direct("assert f.route([13, 21]) is not None"), false);
  }
  const asyncImpl = `import asyncio
async def _leaf(events): return list(events)
def _wrap(fn):
    async def relay(*a, **kw):
        task = asyncio.create_task(fn(*a, **kw))
        ACTION
    return relay
route = _wrap(_leaf)
`;
  const asyncWired = wire + "async def dispatch(events): return await f.route(events)\n";
  await check("包装器等待新任务的本地叶", asyncImpl.replace("ACTION", "return await task"), asyncWired,
    direct("assert asyncio.run(dispatch([13, 21])) == [13, 21]"), true);
  await check("调用者显式等待包装器返回的那一个任务",
    asyncImpl.replace("async def relay", "def relay").replace("ACTION", "return task"), asyncWired,
    direct("assert asyncio.run(dispatch([13, 21])) == [13, 21]"), true);
  await check("未等待的任务即使跑完也不能证明本地叶",
    asyncImpl.replace("ACTION", "await asyncio.sleep(0)\n        return list(a[0])"), asyncWired,
    direct("assert asyncio.run(dispatch([13, 21])) == [13, 21]"), false);
  await check("独立探针必须实际触达本地叶", `from .support import foreign
def _choose():
    def local(events): return list(events)
    def relay(*a, **kw):
        backend = local if len(a[0]) == 2 else foreign
        return backend(*a, **kw)
    return relay
route = _choose()
`, dispatch.replace("f.route(events)", "f.route([13])"), basic, false);
});

test("R21/#1319：精确透传调用点、结果变换与位置专用实参", { timeout: 120_000 }, async t => {
  const entry = "trading_system/at18_fixture_feed.py";
  const integration = "trading_system/__init__.py";
  const path = "trading_system/tests/test_at18_fixture_feed.py";
  const wire = "from . import at18_fixture_feed as f\n";
  const registered = (expr: string, expected: string) => `import asyncio
from trading_system import at18_fixture_feed as f
async def take(iterator): return await anext(iterator)
def test_route(): assert ${expr} == ${expected}
`;
  const support = "def order(events): return sorted(events)\nasync def order_async(events): return sorted(events)\n" +
    "def order_stream(events): yield sorted(events)\nasync def order_async_stream(events): yield sorted(events)\n";
  const dispatch = wire + "def dispatch(events): return f.route(events)\n";
  const check = async (name: string, impl: string, prod: string, test: string, expected: boolean) => {
    await t.test(name, () => {
      const repo = feedSource({ [entry]: impl, [integration]: prod, [path]: test, "trading_system/support.py": support });
      assert.equal(pythonReplacement(repo, G0, entry, integration, path, "test_route", 1), expected);
    });
  };
  const log = "from . import support\nlog = []\ndef _record(*values): log.append(values)\n";
  for (const [name, relay, body, foreign, expr] of [
    ["前置同步", "_record(); return fn(*args, **kwargs)", "def leaf(events): return sorted(events)", "order", "CALL"],
    ["同行后置同步", "out = fn(*args, **kwargs); _record(out); return out", "def leaf(events): return sorted(events)", "order", "CALL"],
    ["finally 协程", "try: return fn(*args, **kwargs)\n        finally: _record()", "async def leaf(events): return sorted(events)", "order_async", "asyncio.run(CALL)"],
    ["嵌套 await", "_record(); return await fn(*args, **kwargs)", "async def leaf(events): return sorted(events)", "order_async", "asyncio.run(CALL)"],
    ["yield 单项结果", "_record(); yield fn(*args, **kwargs)", "def leaf(events): return sorted(events)", "order", "next(CALL)"],
    ["yield from", "_record(); yield from fn(*args, **kwargs)", "def leaf(events): yield sorted(events)", "order_stream", "next(CALL)"],
    ["for 原样产出", "for out in fn(*args, **kwargs): _record(out); yield out", "def leaf(events): yield sorted(events)", "order_stream", "next(CALL)"],
    ["async for 原样产出", "async for out in fn(*args, **kwargs): _record(out); yield out", "async def leaf(events): yield sorted(events)", "order_async_stream", "asyncio.run(take(CALL))"],
  ] as const) {
    const prefix = relay.includes("await") || relay.startsWith("async for") ? "async " : "";
    const wrap = log + `def wrap(fn):
    ${prefix}def relay(*args, **kwargs):
        ${relay}
    return relay
__all__ = ('route',)
`;
    const alias = (fn: string) => "\nroute = " + (name === "嵌套 await" ? `wrap(wrap(${fn}))` : `wrap(${fn})`) + "\n";
    const selection = expr.replace("CALL", "f.route([21, 13])");
    await check(name + "：记录不替外来实现作证", wrap + alias(`support.${foreign}`), dispatch,
      registered(selection, "[13, 21]"), false);
    await check(name + "：本地实现仍计入", wrap + body + alias("leaf"), dispatch,
      registered(selection, "[13, 21]"), true);
  }
  await check("记录不替空桩作证", log + `def leaf(events): pass
def route(*args, **kwargs):
    _record(); out = leaf(*args, **kwargs); _record(); return out
`, dispatch, registered("f.route([21, 13])", "None"), false);
  await check("星号调用外部排序后本地过滤", log + `def route(*args, **kwargs):
    raw = support.order(*args, **kwargs)
    return [value for value in raw if value > 0]
`, dispatch, registered("f.route([-4, 21, 13])", "[13, 21]"), true);
  const wrap = "def wrap(fn):\n    def relay(*args, **kwargs): return fn(*args, **kwargs)\n    return relay\n";
  for (const layers of [1, 2]) {
    const decorated = "@wrap\n".repeat(layers);
    const route = wrap + decorated + "def route(events, /, *, reverse): return sorted(events, reverse=reverse)\n";
    const prod = wire + wrap + decorated + "def dispatch(events, /, *, reverse): return f.route(events, reverse=reverse)\n";
    await check(`${layers} 层：位置专用列表与关键字专用开关`, route, prod,
      registered("f.route([21, 13], reverse=False)", "[13, 21]"), true);
  }
});

test("R15/#1319：三路并发的慢解释器发现不误拒列表迭代器", { timeout: 120_000 }, async () => {
  const f = makeFixture({ feedIntegration: `from .at18_fixture_feed import route
def select_feed(sources, events):
    cursor = iter([1, 1])
    next(cursor)
    try:
        next(cursor)
    except StopIteration:
        return []
    return route('1min', sources, events)
` });
  const python = execFileSync("which", ["python3"], { encoding: "utf8" }).trim();
  writeFileSync(join(f.bin, "python3"), `#!/bin/sh
case "$4" in *site.getsitepackages*) sleep 6;; esac
exec '${python.replaceAll("'", "'\\''")}' "$@"
`, { mode: 0o700 });
  await Promise.all([0, 1, 2].map(async i => {
    const output = join(f.dir, "slow-discovery-" + i);
    mkdirSync(output);
    const r = await execute([f.root, f.manifest, output, ...f.upstream], { env: {
      ...process.env, PATH: f.bin + ":" + process.env.PATH, AT18_TEST_GITHUB: f.apiFile,
    } });
    assert.equal(r.code, 0, r.stderr);
    const report = at18ReportSchema.parse(parseJsonObject(readFileSync(join(output, "at18-report.json"))));
    assert.equal(report.overall_result, "PASS", JSON.stringify(report.failed_checks));
    assert.deepEqual(report.failed_checks, []);
  }));
});

test("R10/#1319：Rust 延迟体、模式作用域与禁用控制体", {
  timeout: 180_000,
}, async t => {
  const path = "at18_fixture_wire::probe::handshake";
  const call = 'assert!(handshake("HELLO"));';
  const fake = "fn fake(_: &str) -> bool { false } ";
  const pointer = "fake as fn(&str) -> bool";
  const poll = "fn drive<F: std::future::Future>(pending: F) { let mut pinned = std::pin::pin!(pending); " +
    "let mut cx = std::task::Context::from_waker(std::task::Waker::noop()); let _ = pinned.as_mut().poll(&mut cx); } ";
  const genericPoll = (pending: boolean) =>
    "fn drive<F: std::future::Future<Output = ()>>(f: F) { let mut pinned = std::pin::pin!(f); " +
    "let mut cx = std::task::Context::from_waker(std::task::Waker::noop()); " +
    `assert!(pinned.as_mut().poll(&mut cx).${pending ? "is_pending" : "is_ready"}()); } `;
  const wire = (body: string) => `use newchan_rust::${path};\n#[test]\nfn check_connection() { ${body} }\n`;
  const check = (production: string, body: string, accepts: boolean, moduleItems = "") => {
    const entry = "rust/src/at18_fixture_wire/mod.rs";
    const testPath = "rust/tests/at18_fixture_wire.rs";
    const repository = feedSource({
      "rust/Cargo.toml": '[package]\nname = "newchan_rust"\nedition = "2024"\n',
      "rust/src/lib.rs": "pub mod at18_fixture_wire;\n" + production,
      [entry]: "pub mod probe;\n",
      "rust/src/at18_fixture_wire/probe.rs": 'pub fn handshake(banner: &str) -> bool { banner.starts_with("HELLO") }',
      [testPath]: moduleItems + wire(body),
    });
    assert.equal(rustReplacement(repository, G0, entry, testPath, "check_connection", []), accepts);
  };
  const cases = [
    ["async-block-dropped", `let _future = async { ${call} };`, false],
    ["async-move-block-dropped", `let _future = async move { ${call} };`, false],
    ["async-awaited-inline", poll + `drive(async { (async { ${call} }).await; });`, true],
    ["async-awaited-binding", poll + `drive(async { let fut = async move { ${call} }; fut.await; });`, true],
    ["async-known-poll", poll + `drive(async { ${call} });`, true],
    ["r11-generic-associated-output", genericPoll(false) + `drive(async { (async move { ${call} }).await; });`, true],
    ["r11-generic-fn-bound", `fn apply<F: Fn(&str) -> bool>(f: F) { assert!(f("HELLO")); } apply(handshake);`, true],
    ["r11-poll-suspended", genericPoll(true) + `drive(async { std::future::pending::<()>().await; ${call} });`, false],
    ["r11-nested-await-suspended", genericPoll(true) + `drive(async {
      (async { core::future::pending::<()>().await }).await; ${call}
    });`, false],
    ["r11-call-before-suspension", genericPoll(true) + `drive(async { ${call} core::future::pending::<()>().await; });`, true],
    ["r11-caller-continues-after-pending-poll", genericPoll(true) + `drive(core::future::pending::<()>()); ${call}`, true],
    ["async-nested-dropped", poll + `drive(async { let _future = async { ${call} }; });`, false],
    ["gen-block-dropped", `let _generator = gen { ${call} yield 0; };`, false],
    ["gen-move-block-driven", `let generator = gen move { ${call} yield 0; }; for _ in generator {}`, true],
    ["async-gen-block-dropped", `let _generator = async gen move { ${call} yield 0; };`, false],
    ["closure-paren-dropped", 'let _f = (|| handshake("HELLO"));', false],
    ["closure-argument-dropped", 'let _f = Some(|| handshake("HELLO"));', false],
    ["closure-array-dropped", 'let _f = [|| handshake("HELLO")];', false],
    ["closure-field-dropped", 'struct Holder<F> { f: F } let _f = Holder { f: || handshake("HELLO") };', false],
    ["closure-returned-dropped", 'fn helper() -> impl FnOnce() -> bool { return || handshake("HELLO"); } let _f = helper();', false],
    ["binary-or-is-not-closure", `assert!(false | handshake("HELLO"));`, true],
    ["binary-logical-or-is-not-closure", `assert!(false || handshake("HELLO"));`, true],
    ["for-shadow", fake + `for handshake in [${pointer}] { assert!(!handshake("HELLO")); }`, false],
    ["for-tuple-shadow", fake + `for (handshake, _) in [(${pointer}, 0)] { assert!(!handshake("HELLO")); }`, false],
    ["for-iter-before-pattern", fake + `for handshake in [{ ${call} ${pointer} }] { let _ = handshake; }`, true],
    ["for-wildcard", `for _ in [0] { ${call} }`, true],
    ["if-let-shadow", fake + `if let Some(handshake) = Some(${pointer}) { assert!(!handshake("HELLO")); }`, false],
    ["if-let-else-outer", fake + `if let Some(handshake) = None::<fn(&str) -> bool> { assert!(!handshake("HELLO")); } else { ${call} }`, true],
    ["while-let-shadow", fake + `let mut f = Some(${pointer}); while let Some(handshake) = f.take() { assert!(!handshake("HELLO")); }`, false],
    ["match-tuple-variant", fake + `match Some(${pointer}) { Some(handshake) => assert!(!handshake("HELLO")), None => () }`, false],
    ["match-at-or-guard", fake + `match Ok::<_, fn(&str) -> bool>(${pointer}) {
      Ok(handshake @ _) | Err(handshake) if !handshake("HELLO") => (),
      _ => (),
    }`, false],
    ["match-record-guard", fake + `struct Holder { f: fn(&str) -> bool } match (Holder { f: ${pointer} }) {
      Holder { f: handshake } if !handshake("HELLO") => (),
      _ => (),
    }`, false],
    ["match-guard-outer", `match Some(0) { Some(_) if handshake("HELLO") => (), _ => () }`, true],
    ["let-tuple-shadow", fake + `let (handshake, _) = (${pointer}, 0); assert!(!handshake("HELLO"));`, false],
    ["let-slice-shadow", fake + `let [handshake, ..] = [${pointer}]; assert!(!handshake("HELLO"));`, false],
    ["let-else-shadow", fake + `let Some(handshake) = Some(${pointer}) else { return; }; assert!(!handshake("HELLO"));`, false],
    ["let-else-outer", `let Some(handshake) = None::<fn(&str) -> bool> else { ${call} return; }; let _ = handshake;`, true],
    ["r11-match-false", `match false { true => ${call.slice(0, -1)}, false => () }`, false],
    ["r11-match-true", `match true { true => ${call.slice(0, -1)}, false => () }`, true],
    ["r11-match-or-literal-tuple", `match (7, "wire") {
      (4 | 7, "wire") => (),
      _ => { ${call} }
    }`, false],
    ["r11-match-guard-false-then-next-arm", `match Some(7) {
      Some(_) if false => (),
      Some(7) => { ${call} }
      _ => (),
    }`, true],
    ["r11-match-false-guard-does-not-hide-return", `match Some(7) {
      Some(_) if false => (),
      Some(7) => return,
      _ => (),
    } ${call}`, false],
    ["r11-match-none-does-not-bind", `match None::<i32> {
      None => { let Some(_) = None::<i32> else { return; }; ${call} }
      Some(_) => (),
    }`, false],
    ["r11-let-else-some", `let Some(_) = Some(7) else { ${call} return; };`, false],
    ["r11-let-else-none", `let Some(_) = None::<i32> else { ${call} return; };`, true],
    ["r11-let-else-none-stops-tail", `{ let Some(_) = None::<i32> else { return; }; } ${call}`, false],
    ["r12-ready-false", poll + `drive(async { if std::future::ready(false).await { ${call} } });`, false],
    ["r12-async-tail-false", poll + `drive(async { if (async { false }).await { ${call} } });`, false],
    ["r12-async-return-flag", poll + `drive(async { if (async { return true; }).await { ${call} } });`, true],
    ["r12-await-int-and-callable", poll + `drive(async {
      let f = core::future::ready(handshake).await;
      if (async { 0x10_i32 }).await >= 16 { assert!(f("HELLO")); }
    });`, true],
    ["r12-await-variant", poll + `drive(async {
      enum Mode { Dry, Live }
      match (async { core::future::ready(Mode::Dry).await }).await {
        Mode::Live => { ${call} }
        Mode::Dry => (),
      }
    });`, false],
    ["r12-enum-dry", `enum Mode { Live, Dry } match Mode::Dry { Mode::Live => { ${call} } _ => () }`, false],
    ["r12-enum-live", `enum Mode { Live, Dry } match Mode::Live { Mode::Live => { ${call} } _ => () }`, true],
    ["r12-tuple-enum-or-pattern", `enum State { Empty, Ok(fn(&str) -> bool, usize), Good(fn(&str) -> bool, usize) }
      match State::Good(handshake, 2) {
        State::Ok(f, 0) | State::Good(f, 2) => { assert!(f("HELLO")); }
        _ => (),
      }`, true],
    ["r12-record-enum-let-else", `enum State { Empty, Code { value: i32, f: fn(&str) -> bool } }
      let State::Code { value: 2, f } = (State::Code { value: 2, f: handshake }) else { return; };
      assert!(f("HELLO"));`, true],
    ["r12-record-enum-if-let", `enum State { Empty, Code { value: i32 } }
      if let State::Code { value: 1 } = (State::Code { value: 2 }) { ${call} }`, false],
    ["r12-enum-while-let", `enum Mode { Live, Dry } while let Mode::Live = Mode::Dry { ${call} break; }`, false],
    ["r12-guard-most-specific", `match Some(1u8) {
      Some(n) if n == 2 => (),
      Some(n) if n != 2 && n < 2 => { ${call} }
      _ => (),
    }`, true],
    ["r12-guard-char-string-bool", `match (2_usize, 'a', "wire", true) {
      (n, c, s, ok) if ok && n <= 2 && c < 'b' && s == r"wire" => { ${call} }
      _ => (),
    }`, true],
    ["r12-guard-short-circuits", `match Some(0x10_i32) {
      Some(n) if !(n >= 0x10) && handshake("HELLO") => (),
      _ => (),
    }`, false],
    ["r12-guard-runtime-disjunction-not-evidence", `let flag = std::hint::black_box(false);
      assert!(flag || handshake("HELLO"));`, false],
    ["r12-cast-hrtb-called", `let f = handshake as for<'a> fn(&'a str) -> bool; assert!(f("HELLO"));`, true],
    ["r12-cast-hrtb-stored", `let _f = (handshake as for<'a> fn(&'a str) -> bool, 0);`, false],
    ["r12-cast-hrtb-args-and-output", `fn adapt<'a>(s: &'a str, _: &str) -> &'a str { assert!(handshake(s)); s }
      let (f, _) = (adapt as for<'a, 'b> fn(&'a str, &'b str) -> &'a str, 0); assert_eq!(f("HELLO", ""), "HELLO");`, true],
    ["r12-unknown-if-single-arm", `if std::hint::black_box(false) { ${call} }`, false],
    ["r12-unknown-if-both-arms", `if std::hint::black_box(true) { ${call} } else { ${call} }`, true],
    ["r12-unknown-if-tail", `if std::hint::black_box(false) { let _ = 2; } ${call}`, true],
    ["r12-unknown-early-return-blocks-tail", `if std::hint::black_box(true) { return; } ${call}`, false],
    ["r12-unknown-if-conditional-rebind", `let mut f: fn(&str) -> bool = |_| false;
      if std::hint::black_box(false) { f = handshake; } let _ = f("HELLO");`, false],
    ["r12-unknown-if-both-rebind", `let mut f: fn(&str) -> bool = |_| false;
      if std::hint::black_box(false) { f = handshake; } else { f = handshake; } assert!(f("HELLO"));`, true],
    ["r12-unknown-if-let-single", `if let Some(_) = std::hint::black_box(None::<i32>) { ${call} }`, false],
    ["r12-unknown-if-let-both", `if let Some(_) = std::hint::black_box(None::<i32>) { ${call} } else { ${call} }`, true],
    ["r12-unknown-while-let-single", `while let Some(_) = std::hint::black_box(None::<i32>) { ${call} break; }`, false],
    ["r12-unknown-match-single", `match std::hint::black_box(false) { true => { ${call} } false => (), }`, false],
    ["r12-unknown-match-all", `match std::hint::black_box(false) { true => { ${call} } false => { ${call} } }`, true],
    ["r12-unknown-option-match-all", `match std::hint::black_box(None::<i32>) {
      Some(_) => { ${call} } None => { ${call} }
    }`, true],
    ["r12-unknown-enum-match-payload", `enum Status { Code(u8), Missing }
      match std::hint::black_box(Status::Code(2)) {
        Status::Code(1) | Status::Missing => { ${call} }
        Status::Code(_) => (),
      }`, false],
    ["r12-unknown-match-wildcard-intersection", `match std::hint::black_box(2) { 1 => { ${call} } _ => { ${call} } }`, true],
    ["r12-unknown-match-may-not-run-guard", `match std::hint::black_box(None::<i32>) {
      Some(_) if handshake("HELLO") => (),
      _ => (),
    }`, false],
    ["r13-if-return-and-tail", `if std::hint::black_box(false) { ${call} return; } ${call}`, true],
    ["r13-match-return-and-tail", `match std::hint::black_box(false) {
      true => { ${call} return; }
      false => (),
    } ${call}`, true],
    ["r13-let-else-return-and-tail", `let Some(_) = std::hint::black_box(Some(1)) else {
      ${call} return;
    }; ${call}`, true],
    ["r13-let-else-return-skips-tail", `let Some(_) = std::hint::black_box(Some(1)) else {
      return;
    }; ${call}`, false],
    ["r13-for-continue-path-and-tail", `for _ in [0, 1] {
      if std::hint::black_box(false) { ${call} continue; }
      ${call}
    }`, true],
    ["r13-for-break-skips-body", `for _ in [0, 1] {
      if std::hint::black_box(false) { break; }
      ${call}
    }`, false],
    ["r13-labelled-break-exits-outer-loop", `'outer: loop {
      loop { break 'outer; } ${call} break;
    }`, false],
    ["r13-labelled-continue-skips-outer-body", `'outer: for _ in [0, 1] {
      for _ in [0] { continue 'outer; } ${call}
    }`, false],
    ["r13-let-else-break-to-block-with-value", fake + `let f = 'pick: {
      let Some(_) = None::<u8> else { break 'pick handshake as fn(&str) -> bool; };
      fake as fn(&str) -> bool
    }; assert!(f("HELLO"));`, true],
    ["r13-loop-break-value", `let f = loop { break handshake as fn(&str) -> bool; }; assert!(f("HELLO"));`, true],
    ["r13-while-mixed-break-return", `while true {
      if std::hint::black_box(false) { ${call} return; }
      break;
    } ${call}`, true],
    ["r13-while-continue-can-diverge", `while true {
      if std::hint::black_box(false) { break; }
      continue;
    } ${call}`, false],
    ["r13-let-chain-short-circuit", `if let Some(_) = std::hint::black_box(Some(1)) && handshake("HELLO") {
      let _ = 1;
    }`, false],
    ["r13-await-mixed-poll", poll + `async fn gate(go: bool) {
      if go { return; }
      core::future::pending::<()>().await;
    } drive(async { gate(std::hint::black_box(false)).await; ${call} });`, false],
    ["r13-await-both-poll-paths-execute", poll + `async fn gate(go: bool, f: fn(&str) -> bool) {
      if go { return; }
      assert!(f("HELLO"));
      core::future::pending::<()>().await;
    } drive(async { gate(std::hint::black_box(true), handshake).await; ${call} });`, true],
    ["r13-poll-mixed-does-not-suspend-caller", poll + `drive(async {
      if std::hint::black_box(false) { return; }
      core::future::pending::<()>().await;
    }); ${call}`, true],
    ["r13-guard-second-or", `match (1_u8, 2_u8) {
      (n, _) | (_, n) if n == 2 => { ${call} }
      _ => (),
    }`, true],
    ["r13-guard-second-nested-or", `match ((1_u8, 2_u8), handshake as fn(&str) -> bool) {
      ((n, _) | (_, n), f) if n == 2 => { assert!(f("HELLO")); }
      _ => (),
    }`, true],
    ["r13-guard-all-failed-resumes-next-arm", `match (1_u8, 2_u8) {
      (n, _) | (_, n) if n == 3 => return,
      _ => { ${call} }
    }`, true],
    ["r13-first-successful-guard-wins", `match (1_u8, 2_u8) {
      (n, _) | (_, n) if n > 0 => { if n == 2 { ${call} } }
      _ => (),
    }`, false],
    ["r13-alias-chain-block", `enum Phase { Live, Dry }
      type First = Phase; type State = First;
      match State::Live { Phase::Live => { ${call} } Phase::Dry => (), }`, true],
    ["r13-alias-generic-prelude", `type Receiver<T> = core::option::Option<T>;
      let Receiver::Some(f) = Some(handshake) else { return; };
      assert!(f("HELLO"));`, true],
    ["r13-guard-or-alias-value-and-pattern", `enum Phase { Live(u8, u8), Dry }
      type State = Phase; match State::Live(1, 2) {
        Phase::Live(n, _) | State::Live(_, n) if n == 2 => { ${call} }
        _ => (),
      }`, true],
    ["r14-canonical-before-test-intersection", `if std::hint::black_box(false) {
      assert!(newchan_rust::select_wire("HELLO")); return;
    } ${call}`, true],
    ["r14-canonical-does-not-hide-empty-path", `if std::hint::black_box(false) {
      assert!(newchan_rust::select_wire("HELLO"));
    }`, false],
    ["r14-complementary-immutable-conditions", `let flag = std::hint::black_box(false);
      if flag { ${call} } if !flag { ${call} }`, true],
    ["r14-complementary-different-bindings", `let a = std::hint::black_box(false);
      let b = std::hint::black_box(false); if a { ${call} } if !b { ${call} }`, false],
    ["r14-complementary-shadowed-binding", `let flag = std::hint::black_box(false);
      if flag { ${call} } let flag = std::hint::black_box(false); if !flag { ${call} }`, false],
    ["r14-complementary-mutable-binding", `let mut flag = std::hint::black_box(false);
      if flag { ${call} } flag = std::hint::black_box(true); if !flag { ${call} }`, false],
    ["r15-boolean-parentheses-and-not-parity", `let flag = std::hint::black_box(false);
      if !!((flag)) { ${call} } if (!(!( !flag ))) { ${call} }`, true],
    ["r15-boolean-parentheses-do-not-equate-bindings", `let a = std::hint::black_box(false);
      let b = std::hint::black_box(false); if ((a)) { ${call} } if !(b) { ${call} }`, false],
    ["r15-boolean-parity-does-not-remove-shadowing", `let flag = std::hint::black_box(false);
      if ((flag)) { ${call} } let flag = std::hint::black_box(false); if (!(flag)) { ${call} }`, false],
    ["r15-boolean-parity-does-not-refine-mutable", `let mut flag = std::hint::black_box(false);
      if !!flag { ${call} } flag = std::hint::black_box(true); if (!(flag)) { ${call} }`, false],
    ["r14-ready-match", `use std::task::Poll; use std::future::Future;
      let mut fut = std::pin::pin!(std::future::ready(true));
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      match fut.as_mut().poll(&mut cx) {
        Poll::Ready(true) => { ${call} }
        Poll::Ready(false) | Poll::Pending => (),
      }`, true],
    ["r14-pending-is-pending", `use std::future::Future;
      let mut fut = std::pin::pin!(std::future::pending::<()>());
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if fut.as_mut().poll(&mut cx).is_pending() { ${call} }`, true],
    ["r14-pending-is-not-ready", `use std::future::Future;
      let mut fut = std::pin::pin!(std::future::pending::<()>());
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if fut.as_mut().poll(&mut cx).is_ready() { ${call} }`, false],
    ["r14-ready-is-ready", `let mut fut = std::pin::pin!(std::future::ready(()));
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if std::future::Future::poll(fut.as_mut(), &mut cx).is_ready() { ${call} }`, true],
    ["r14-ready-is-not-pending", `let mut fut = std::pin::pin!(std::future::ready(()));
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if std::future::Future::poll(fut.as_mut(), &mut cx).is_pending() { ${call} }`, false],
    ["r15-poll-ready-payload-is-not-pending", `use std::future::{pending, ready, Future};
      let mut fut = std::pin::pin!(ready(pending::<()>()));
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if fut.as_mut().poll(&mut cx).is_pending() { ${call} }`, false],
    ["r15-poll-ready-payload-is-ready", `use std::future::{pending, ready, Future};
      let mut fut = std::pin::pin!(ready(pending::<()>()));
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if fut.as_mut().poll(&mut cx).is_ready() { ${call} }`, true],
    ["r15-poll-only-drives-inner-after-unwrapping", `use std::future::{pending, Future}; use std::task::Poll;
      let mut outer = std::pin::pin!(async { pending::<()>() });
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      let Poll::Ready(inner) = outer.as_mut().poll(&mut cx) else { return; };
      let mut inner = std::pin::pin!(inner);
      if inner.as_mut().poll(&mut cx).is_pending() { ${call} }`, true],
    ["r15-await-outer-ready-does-not-drive-inner", poll + `drive(async {
      let _inner = std::future::ready(std::future::pending::<()>()).await;
      ${call}
    });`, true],
    ["r15-await-explicitly-drives-inner-pending", poll + `drive(async {
      std::future::ready(std::future::pending::<()>()).await.await;
      ${call}
    });`, false],
    ["r14-mixed-is-not-always-ready", `use std::future::Future;
      let mut fut = std::pin::pin!(async {
        if std::hint::black_box(false) { core::future::pending::<()>().await; }
      });
      let mut cx = std::task::Context::from_waker(std::task::Waker::noop());
      if fut.as_mut().poll(&mut cx).is_ready() { ${call} }`, false],
    ["r14-generic-alias-nested-argument", `enum Phase<T, U> { Live(T, U), Dry }
      type Id<T> = T; type State = Id<Id<Phase<u8, (u8, u8)>>>;
      match State::Live(1, (2, 3)) { Phase::Live(_, _) => { ${call} } Phase::Dry => (), }`, true],
    ["r15-type-alias-default-with-prior-argument", `enum Phase { Live, Dry }
      type Select<A, B = A> = B; type State = Select<Phase>;
      match State::Live { Phase::Live => { ${call} } Phase::Dry => (), }`, true],
    ["r15-type-alias-explicit-override", `enum Phase { Live, Dry } enum Other { Live, Dry }
      type Id<T = Phase> = T; type State = Id<Other>;
      match State::Live { Other::Live => { ${call} } Other::Dry => (), }`, true],
    ["r15-type-alias-default-does-not-reach-dead-arm", `enum Phase { Live, Dry }
      type Id<T = Phase> = T; type State = Id;
      match State::Dry { Phase::Live => { ${call} } Phase::Dry => (), }`, false],
    ["r11-if-let-some", `if let Some(f) = Some(handshake) { assert!(f("HELLO")); }`, true],
    ["r11-if-let-none", `if let Some(f) = None::<fn(&str) -> bool> { ${call} let _ = f; }`, false],
    ["r11-while-let-none", `while let Some(_) = None::<i32> { ${call} break; }`, false],
    ["r11-tuple-real", `let (f, _) = (handshake, 7); assert!(f("HELLO"));`, true],
    ["r11-tuple-fn-pointer", `let (f, _) = (handshake as fn(&str) -> bool, 7); assert!(f("HELLO"));`, true],
    ["r11-tuple-fake", fake + `let (handshake, _) = (fake, 7); assert!(!handshake("HELLO"));`, false],
    ["r11-array-nested-variant", `let [Ok(f), ..] = [Ok::<_, ()>(handshake)] else { return; }; assert!(f("HELLO"));`, true],
    ["if-dead", `if false { ${call} }`, false],
    ["while-dead", `while false { ${call} }`, false],
    ["if-parenthesized-dead", `if (false) { ${call} }`, false],
    ["if-else-live", `if false {} else if false {} else { ${call} }`, true],
    ["if-else-then-statement", `if true {} else if true { ${call} } else { ${call} } let _ = 0;`, false],
    ["cfg-false-block", `#[cfg(false)] { ${call} }`, false],
    ["cfg-any-block", `#[cfg(any())] { ${call} }`, false],
    ["cfg-false-statement", `#[cfg(any())] ${call} let _ = 0;`, false],
    ["cfg-true-statement", `#[cfg(all())] ${call}`, true],
    ["cfg-test-statement", `#[cfg(test)] ${call}`, true],
    ["local-macro-shadows-prelude", `macro_rules! assert { ($e:expr) => { () } } ${call}`, false],
    ["impl-method-dropped", `struct Holder; impl Holder { fn call() { ${call} } } let _ = Holder;`, false],
    ["trait-method-dropped", `trait Holder { fn call() { ${call} } }`, false],
    ["local-module-method-dropped", `mod other { pub fn call() { assert!(newchan_rust::${path}("HELLO")); } }`, false],
    ["local-const-shadows-import", 'const handshake: fn(&str) -> bool = |_| false; assert!(!handshake("HELLO"));', false],
    ["local-unsafe-fn-shadows-import", 'unsafe fn handshake(_: &str) -> bool { false } assert!(!unsafe { handshake("HELLO") });', false],
    ["local-const-fn-shadows-import", 'const fn handshake(_: &str) -> bool { false } assert!(!handshake("HELLO"));', false],
    ["local-extern-fn-shadows-import", 'extern "C" fn handshake(_: &str) -> bool { false } assert!(!handshake("HELLO"));', false],
  ] as const;
  for (const [id, body, accepts] of cases) await t.test(id, async () => {
    check(`pub fn select_wire(banner: &str) -> bool { ${path}(banner) }\n`, body, accepts);
  });
  await t.test("r12-canonical-module-enum", () => check("", `
    use crate::switches::Mode as Switch;
    match self::switches::Mode::Live {
      Switch::Live => { ${call} }
      crate::switches::Mode::Dry => (),
    }
  `, true, "mod switches { pub enum Mode { Dry, Live } }\n"));
  await t.test("r14-canonical-before-production-intersection", () => check(`
    fn encapsulated(banner: &str) -> bool { ${path}(banner) }
    pub fn select_wire(banner: &str) -> bool {
      if std::hint::black_box(false) { return encapsulated(banner); }
      ${path}(banner)
    }
  `, call, true));
  await t.test("r14-generic-module-alias-keeps-argument-scope", () => check("", `
    enum Local { Live, Dry }
    type State = crate::aliases::Id<Local>;
    match State::Live { Local::Live => { ${call} } Local::Dry => (), }
  `, true, "mod aliases { pub type Id<T> = T; }\n"));
  await t.test("r15-cascading-defaults-resolve-in-declaration-scope", () => check("", `
    enum Phase { Live, Dry }
    type State = crate::aliases::Select;
    match State::Live { crate::aliases::Phase::Live => { ${call} } crate::aliases::Phase::Dry => (), }
  `, true, "mod aliases { pub enum Phase { Live, Dry } pub type Select<A = Phase, B = A, C = B> = C; }\n"));
  await t.test("r13-qualified-module-alias-chain", () => check("", `
    type Local = crate::state::State<fn(&str) -> bool>;
    match Local::Live(handshake) {
      self::phase::Phase::Live(f) => { assert!(f("HELLO")); }
      phase::Phase::Dry => (),
    }
  `, true, `
    mod phase { pub enum Phase<T> { Live(T), Dry } }
    mod state {
      use super::phase::Phase as Imported;
      pub type Alias<T> = Imported<T>;
      pub type State<T> = self::Alias<T>;
    }
  `));
  const publicAsync = `pub async fn select_wire(banner: &str) -> bool { ${path}(banner) }\n`;
  await t.test("public-async-dropped", () => check(publicAsync, 'let _future = newchan_rust::select_wire("HELLO");', false));
  await t.test("public-async-driven", () => check(publicAsync, poll + 'drive(async { assert!(newchan_rust::select_wire("HELLO").await); });', true));
  const futureWrapper = `pub fn select_wire(banner: &str) -> impl std::future::Future<Output = bool> + '_ {
    let future = async move { ${path}(banner) }; future
  }\n`;
  await t.test("wrapper-future-dropped", () => check(futureWrapper, 'let _f = newchan_rust::select_wire("HELLO");', false));
  await t.test("wrapper-future-driven", () => check(futureWrapper, poll + 'drive(newchan_rust::select_wire("HELLO"));', true));
  for (const [id, body] of [
    ["dead-async", "let _f = async { accept(banner) }; false"],
    ["dead-closure-argument", "let _f = Some(|| accept(banner)); false"],
    ["shadow-pattern", "fn fake(_: &str) -> bool { false } for accept in [fake as fn(&str) -> bool] { return accept(banner); } false"],
    ["dead-if", "if false { return accept(banner); } false"],
    ["dead-cfg", "#[cfg(any())] { return accept(banner); } false"],
    ["dead-impl", "struct Holder; impl Holder { fn call(b: &str) -> bool { accept(b) } } false"],
  ] as const) await t.test("production-" + id, async () => {
    const wireIntegration = `use ${path} as accept;\npub fn select_wire(banner: &str) -> bool { ${body} }\n`;
    check(wireIntegration, call, false);
  });
});

test("R7/H3：#1942 与 #2021 的真实 Cargo 闭包不随冗余显式特性变化", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root);
  const testPath = "rust/tests/at18_review_local.rs";
  const original = s.blob.bind(s);
  for (const [commit, entry, body] of [
    ["3cd162ea4c3c8c73a0d6b8c6866894a0204e78bc", "rust/src/history_simulation/mod.rs",
      'assert_eq!(newchan_rust::history_simulation::model::MODEL_ID, "history-sim/bar-batch-known-frontier/1");'],
    ["b9d898dccf46c2a716115eaa1215bc39c458a959", "rust/src/economic_session/mod.rs",
      "assert!(newchan_rust::economic_session::cli(false).is_err());"],
  ]) {
    // 只替换测试文件；Cargo.toml 和全部生产模块读取真实合入树。
    s.blob = (F, path) => path === testPath ? Buffer.from("#[test]\nfn review_local() { " + body + " }\n") : original(F, path);
    for (const features of [["production_session"], ["production_session", "s_session"]]) {
      assert.ok(rustReplacement(s, commit, entry, testPath, "review_local", features), entry + " / " + features);
    }
    assert.equal(rustReplacement(s, commit, entry, testPath, "review_local", []), false);
  }
});

test("R7/H3：Cargo 多行、传递与循环；cfg all/any/not 不借用依赖特性", () => {
  const { features } = cargoContext(`[features]
production = [
  "linked", # 继续传递
  'dep:wire',
  "extension?/transport",
  "crate/remote",
]
linked = ["leaf"]
leaf = ["production"]
wire = []
extension = []
crate = []
`, ["production"]);
  assert.deepEqual([...features].sort(), ["leaf", "linked", "production"]);
  assert.deepEqual([...cargoContext(undefined, ["given"]).features], ["given"]);
  assert.deepEqual([...cargoContext("[package]\nname = 'local'\n", ["given"]).features], ["given"]);
  const cfg = (...body: string[]) => enabledRustItem(["#", "[", "cfg", "(", ...body, ")", "]"], features);
  const feature = (name: string) => ["feature", "=", JSON.stringify(name)];
  assert.ok(cfg("all", "(", ...feature("leaf"), ",", "any", "(", ...feature("linked"), ",", ...feature("wire"),
    ")", ",", "not", "(", ...feature("crate"), ")", ",", ")"));
  assert.equal(cfg("not", "(", ...feature("leaf"), ")"), false);
  assert.equal(cfg("any", "(", ...feature("wire"), ",", ...feature("remote"), ")"), false);
});

test("R8/H3：真实 X runtime::WIRE 的平台 cfg 归入同一递归求值", { skip: !pathExistsGit }, () => {
  const s = new At18Repository(root);
  const F = "b9d898dccf46c2a716115eaa1215bc39c458a959";
  const entry = "rust/src/history_simulation/mod.rs", testPath = "rust/tests/at18_review_cfg.rs";
  const read = s.blob.bind(s);
  const original = read(F, entry).toString();
  assert.match(original, /#\[cfg\(unix\)\]\r?\npub mod runtime;/);
  const testSource = Buffer.from('#[test]\nfn actual_wire() { assert_eq!(newchan_rust::history_simulation::runtime::WIRE, "x-exact-simulation/1"); }\n');
  assert.equal(cargoTarget(["ubuntu-latest"]), "linux");
  assert.equal(cargoTarget(["self-hosted", "macOS"]), "macos");
  assert.equal(cargoTarget(["windows-2022"]), "windows");
  assert.equal(cargoTarget(["linux", "windows"]), undefined);
  for (const [guard, targets] of [
    ["unix", [true, true, false, false]],
    ["all(unix)", [true, true, false, false]],
    ["any(unix)", [true, true, false, false]],
    ["not(not(unix))", [true, true, false, false]],
    ["windows", [false, false, true, false]],
    ["all(windows)", [false, false, true, false]],
    ["not(unix)", [false, false, true, false]],
    ['target_family = "unix"', [true, true, false, false]],
    ['target_os = "linux"', [true, false, false, false]],
  ] as const) {
    s.blob = (F, path) => path === testPath ? testSource : path === entry ?
      Buffer.from(original.replace("#[cfg(unix)]", "#[cfg(" + guard + ")]")) : read(F, path);
    const actual = [["ubuntu-latest"], ["macos-latest"], ["self-hosted", "Windows"], ["p1-isolated"]]
      .map(labels => rustReplacement(s, F, entry, testPath, "actual_wire", ["production_session"], cargoTarget(labels)));
    assert.deepEqual(actual, targets, guard);
  }
});

test("R7/H9：UTC 同时刻的两个拼写满十年，少一分钟仍拒", {
  skip: !pathExistsGit, timeout: 120_000,
}, async t => {
  for (const [heavyCase, accepts] of [["utc-equivalent", true], ["utc-short-minute", false]] as const) {
    await t.test(heavyCase, async () => {
      const { report } = await control({ heavyCase, api: routes => close(routes, 1320) }, "R7/heavy/" + heavyCase);
      assert.equal(legacyRow(report, 1320).disposition_valid, accepts);
      if (accepts) positive(report);
      else {
        reportFail(report, "LEGACY_DISPOSITION", "ticket:1320@" + heavy);
        assert.equal(report.failed_checks.length, 1);
      }
    });
  }
});
