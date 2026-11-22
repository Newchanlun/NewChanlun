import assert from "node:assert/strict";
import { spawn, type SpawnOptions } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { adapter, registrySchema } from "./at18-contract.ts";
import { canMakeFixture, makeFixture, type Mutation, type API } from "./at18-fixture.ts";
import { artifactRefSchema, at18InputBundleSchema, at18ReportSchema, byteSha256, canonicalizeJcs, computeContentHash,
  legacyTickets, ledgerPaths, parseJsonObject, specPaths, tbTickets, workflows, type At18Report } from "./at18-format.ts";
import { ciNames, utcBefore } from "./at18-integrations.ts";
import { object } from "./at18-github.ts";
import { boundedStatement } from "./at18-report.ts";
import { At18Repository, Diagnostics, G0, valueAt } from "./at18-source.ts";
import { keyBasis, keyDomain, keyId, readCoverage } from "./at18-coverage.ts";

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
async function control(mutation: Mutation = {}) {
  const f = makeFixture(mutation);
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
  const { f, report, output } = await control();
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

function jobs(api: API, i: number, apply: (r: Record<string, unknown>) => boolean) {
  const envelope = object(api[`actions/runs/${49000 + i}/attempts/2/jobs?per_page=100`]);
  const after = (envelope.jobs as unknown[]).map(object).filter(apply);
  envelope.jobs = after;
  envelope.total_count = after.length;
}
const conditions: [string, Mutation, string, string?][] = [
  ["CI/独评在错误产品上", { api: api => {
    const key = Object.keys(api).find(k => k.startsWith("commits/") && k.endsWith("/statuses?per_page=100"))!;
    const first = object((api[key] as unknown[])[0]); first.creator = { login: "not-review-gate" };
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
    (api["issues/1561/comments?per_page=100"] as unknown[]).push({ id: 9999999999, body: "production 已完成首次发送" });
  } }, "PRODUCTION_SCOPE_CHANGED", "ticket:1561"],
  ["未启用结论不能从首次启用原件缺失倒推：触达与版本均齐", { enabledWithoutFirstActivation: true },
    "SPECIAL_GATE", "first_activation"],
  ["没有证明的延期不能套给覆盖键", { registry: reg => {
    const b = reg.bindings.find(x => x.domains[0].result === "VERIFIED")!;
    b.domains.push({ evidence_class: "production", profile_id: "P2-not-authorized", result: "BOUNDED_DEFERRED",
      deferred_gate: "LEGACY_OE41_DEPLOYMENT", checks: [] });
  } }, "DOMAIN_INVALID", "@production@P2-"],
  ["#1279 明示提前放行", { api: api => {
    (api["issues/1279/comments?per_page=100"] as unknown[]).push({ id: 9999999999, body: "图前置尚缺，现宣布试运行放行" });
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
  ["覆盖计数减一不能用同步截断来源过关", { crosswalk: source => { (source.rows as unknown[]).pop(); } },
    "COVERAGE_SOURCE", "/spec_coverage"],
  ["缺 R07 封印对应外部原件照常产出 FAIL", { omitRecord: record => record.record === "permission.experiment" },
    "RECORD_UNSEALED", "at18-seal permission.experiment"],
];
test("R1/R2 回归：每个单点破坏均产生具名 FAIL", {
  skip: !pathExistsGit ? "需要 G0/P0 与发布的规范 Git 对象" : false, timeout: 420_000,
}, async t => {
  for (const [name, mutation, check, scope] of conditions) {
    await t.test(name, { timeout: 60_000 }, async () => {
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
    });
  }
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
