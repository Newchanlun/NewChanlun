import { execFileSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { at18, At18Repository, Diagnostics, G0, P0, sorted } from "./at18-source.ts";
import { basisId, readCoverage } from "./at18-coverage.ts";
import { adapter as decodeAdapter, type Registry } from "./at18-contract.ts";
import {
  byteSha256, canonicalizeJcs, computeContentHash, ledgerPaths, parseJsonObject, specPaths, tbId, tbIds, tbTickets, workflows,
} from "./at18-format.ts";
import { object, rows, type Row } from "./at18-github.ts";
import { acceptedAt14, at14Summary, AT14_LOCKS } from "./at18-at14.ts";
import { feedWirePaths } from "./at18-legacy.ts";
import { r11Checks, r11Source, verifyPregateHistory } from "./at18-pregate.ts";
import { heavySymbols } from "./at18-heavy.ts";

const specCommit = "b9d898dccf46c2a716115eaa1215bc39c458a959";
const fixture = resolve(__dirname, "fixtures/at18");
const project = resolve(__dirname, "..");
const repoId = "Newchanlun/NewChanlun";
const githubRepo = { full_name: repoId };
const profile = "P1-hl-testnet";
const releaseBody = "**用户批复（#1561 Q1）**：不做 P2 真钱首次发送（用户 2026-10-21 原话「我暂时不用真钱」）。\n\n按推荐落地：本图 TB-09／TB-10 以 P1-hl-testnet 验收；P2 首发授权记录按 Q2 格式只登记、不执行，签署人只能是用户本人；Q3（P2 字段）因 Q1 未否决而不触发。日后要上真钱另起票，按 ADR 0021 重启并需主网存款。Q2 默认值待用户与 #1559／#1560／#1567 一并确认。\n";
const raw = (value: unknown) => Buffer.from(canonicalizeJcs(value) + "\n");
const note = (s: string) => byteSha256(Buffer.from(s));
const signature = "```at18-experiment-authorization/1\n" + canonicalizeJcs({
  schema_version: "at18-experiment-authorization/1", profile_id: profile, runner_group: "p1-fixture", runner_label: "p1-isolated",
  not_before: "2025-01-01T00:00:00Z", expires_at: "2099-12-31T00:00:00Z", actions: ["query"],
}) + "\n```";
const fixed = [
  [1392, "8619a20f2800095e6bb9ec20ba2607a744740f91", "m3_partition_synthetic_holds"],
  [1404, "f95a7f3ebc0ce84ec2d2f8a8d71b5030b19f89b9", "calibration_sweep_finds_non_collapsed_segments"],
  [1414, "465174240b989a1d99f99a047fbb46b3ee215f49", "seam_btc_tick_bars_yield_non_trivial_structure"],
] as const;
const current = "2026-11-01T09:00:00Z";
const ownPaths = [".sandcastle/at18-report.mts", ".sandcastle/at18-verification.mts"];
export type API = Record<string, unknown>;
export type Mutation = {
  api?: (routes: API) => void;
  registry?: (registry: Registry) => void;
  crosswalk?: (crosswalk: Row) => void;
  omitObligation?: boolean;
  records?: (record: Row) => void;
  omitRecord?: (record: Row) => boolean;
  enabledWithoutFirstActivation?: boolean;
  at14?: (record: Row) => void;
  at14Node?: boolean;
  at14Ci?: "ignored" | "skip-ci" | "dispatch-only" | "ignored-only" | "unrecorded";
  feedReplacement?: string;
  historicProducts?: "correct" | "swapped";
  emptyProduct?: boolean;
  summary?: "missing" | "inconsistent";
  crosswalkBytes?: Buffer;
  feedWire?: (entries: Row[]) => Row[];
  historicalCures?: "all" | "missing" | "failed" | "empty-node" | "empty-step" | "empty-rust";
  heavyCase?: "measured" | "short" | "missing-control" | "wrong-trial" | "retired" | "unapproved-retirement" | "one-bar" | "late-review" |
    "malformed-heavy" | "input-unregistered" | "second-run-missing" | "output-diverges";
};

export function canMakeFixture() {
  try {
    const g = new At18Repository(project);
    return g.string("rev-parse", "--is-shallow-repository") === "false" &&
      g.ancestor(P0, G0) && g.ancestor(G0, specCommit);
  } catch { return false; }
}
export function makeFixture(mutation: Mutation = {}) {
  const dir = mkdtempSync(join(realpathSync(process.env.AT18_TEST_EVIDENCE || tmpdir()), "at18-control-"));
  const root = join(dir, "git"), bin = join(dir, "bin"), evidence = join(dir, "evidence");
  mkdirSync(root); mkdirSync(bin); mkdirSync(evidence);
  const git = (args: string[], input?: Buffer | string) => execFileSync("git", [
    "-c", "core.hooksPath=/dev/null", "-c", "user.name=AT18 Fixtures", "-c", "user.email=at18@example.invalid", "-C", root, ...args,
  ], { input, env: { ...process.env, GIT_AUTHOR_DATE: current, GIT_COMMITTER_DATE: current }, stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"], maxBuffer: 64 * 1024 * 1024, timeout: 20_000 }).toString().trim();
  git(["init", "-q"]);
  const src = new At18Repository(project);
  const objects = src.string("rev-parse", "--path-format=absolute", "--git-path", "objects");
  writeFileSync(join(root, ".git/objects/info/alternates"), objects + "\n");
  git(["remote", "add", "origin", "https://github.com/" + repoId + ".git"]);
  git(["read-tree", G0]);
  const put = (path: string, bytes: Buffer | string, mode = "100644") => {
    const stage = join(dir, "fixture-object");
    writeFileSync(stage, bytes);
    const oid = git(["hash-object", "-w", "--no-filters", "--", stage]);
    git(["update-index", "--add", "--cacheinfo", `${mode},${oid},${path}`]);
  };
  const write = (path: string, bytes: Buffer | string) => { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, bytes); };

  const api: API = {};
  function issue(n: number, state = "closed", body = "合成票面（断网夹具）", labels: string[] = []) {
    api["issues/" + n] = { number: n, state, state_reason: state === "closed" ? "completed" : null,
      labels: labels.map(name => ({ name })), updated_at: current, created_at: "2026-11-22T00:00:00Z", body };
  }
  function comment(n: number, ticket: number, body: string) {
    const record = { id: n, issue_url: `https://api.github.com/repos/${repoId}/issues/${ticket}`, body };
    api["issues/comments/" + n] = record;
    return record;
  }
  function children(n: number, children: number[]) {
    api[`issues/${n}/sub_issues?per_page=100`] = children.map(number => ({ number }));
  }
  function reviewed(M: string, H: string, id: number, title: string, ref: string, body = "") {
    const pr = { number: id, title, body, merged: true, merged_at: current, merge_commit_sha: M,
      base: { ref: "main", repo: githubRepo }, head: { sha: H, ref } };
    api["pulls/" + id] = pr;
    api[`commits/${M}/pulls?per_page=100`] = [{ number: id, merge_commit_sha: M }];
    api[`commits/${H}/statuses?per_page=100`] = [{
      id: id + 10000, state: "success", context: "deepagents/review",
      creator: { login: "newchanlun-review-gate[bot]" }, created_at: "2026-11-01T08:00:00Z",
    }];
  }
  reviewed(G0, git(["rev-parse", G0 + "^2"]), 1915, "#1915 formal review", "impl/1915-formal");
  const merge = (parent: string, id: number, title: string, branch: string, body = "") => {
    const tree = git(["write-tree"]);
    const H = git(["commit-tree", tree, "-p", parent], body ? title + "\n\n" + body : title);
    const M = git(["commit-tree", tree, "-p", parent, "-p", H], "Merge PR #" + id);
    reviewed(M, H, id, title, branch, body);
    return M;
  };

  const paths = [...Object.values(specPaths), ...ledgerPaths];
  const documents = new Map(paths.map(path => [path, src.blob(specCommit, path)]));
  if (mutation.crosswalk) {
    const data = parseJsonObject(documents.get(specPaths.crosswalk_ref)!);
    mutation.crosswalk(data);
    documents.set(specPaths.crosswalk_ref, raw(data));
  }
  if (mutation.omitObligation) {
    const stories = parseJsonObject(documents.get(specPaths.spec_ref)!);
    const destination = rows(stories.stories).find(row => row.id === "US-DST-01")!;
    destination.observable_result = null;
    documents.set(specPaths.spec_ref, raw(stories));
  }
  for (const [path, bytes] of documents) put(path, path === specPaths.crosswalk_ref ? mutation.crosswalkBytes ?? bytes : bytes);
  const sourceJSON = (p: string) => parseJsonObject(documents.get(p)!);
  const d = new Diagnostics();
  const coverage = readCoverage(sourceJSON(specPaths.crosswalk_ref), sourceJSON(specPaths.coverage_input_ref),
    ledgerPaths.map(sourceJSON), d, mutation.omitObligation ? parseJsonObject(src.blob(specCommit, specPaths.spec_ref)) : sourceJSON(specPaths.spec_ref));

  const r = parseJsonObject(readFileSync(join(fixture, "adapter-contract.json")));
  const permissions = object(r.experiment_authorization);
  permissions.comment_id = 440000001;
  permissions.body_sha256 = note(signature);
  const auth = comment(440000001, 2133, signature);
  issue(2133);
  api["issues/2133/comments?per_page=100"] = [auth];
  for (const [name, item] of Object.entries(object(r.legacy_sources))) {
    const entry = object(item);
    if (entry.kind === "git-blob") {
      const bytes = src.blob(G0, String(entry.path));
      entry.commit = G0;
      entry.sha256 = byteSha256(bytes);
    } else {
      const body = [
        "合成旧票出处 " + name,
        "保留原处分；只在断网测试环境替代 GitHub 服务端。",
        "自有最低测量清单（若适用）。",
        "保留实验归档；不作为 F 的运行证据。",
        "自有研究与试运行清单；不得提前放行。",
        "旧票约束；本图前置只由 R13 聚合前因子销项。",
      ].join("\n");
      entry.sha256 = note(body);
      const num = Number(entry.ticket);
      if (entry.kind === "issue-body") issue(num, [1279, 1304, 1320].includes(num) ? "open" : "closed", body);
      else comment(Number(entry.comment_id), num, body);
    }
  }
  const known = decodeAdapter(r).issue_1279.release_disposition.known_historical_comments;
  api["issues/1279/comments?per_page=100"] = known.map(k => api["issues/comments/" + k.slice(1)]);
  const savedQ1 = releaseBody.endsWith("\n") ? releaseBody : releaseBody + "\n";
  const q1 = [savedQ1, savedQ1.trimEnd(), savedQ1 + "\n"].find(body => note(body) === "0389547746c5945f318a8b411605f8b083c97ab16878a0b69a4772385d6a0fdb");
  if (!q1) throw new Error("fixture: #1561 Q1");
  issue(1561); issue(942); issue(1282); issue(2132); issue(1369, "open"); issue(1391, "open"); issue(1403, "open");
  api["issues/1561/comments?per_page=100"] = [6264190851, 6264283538, 6282695814, 6310811399, 6310848771, 6311315578, 6315084208]
    .map(n => comment(n, 1561, n === 6310811399 ? q1 : "合成：其余固定历史评论"));

  // 已钉住的 P0 与 G0 使用真实提交及完整第一父历史，F 之后的 GitHub 行全部为合成。
  const censusDir = at18 + "pregate/";
  const historyBytes = src.blob("d896e31be8353a9445af46629737be6a4d6363e5", censusDir + "all-first-parent.jsonl");
  const history = verifyPregateHistory(src, historyBytes);
  const anchors = [1359, 1360, 1361, 1362, 1363, 1364, 1365, 1366, 1367, 1368];
  const relevant = new Set([...anchors, 1493, ...fixed.map(f => f[0])]);
  const links = [...anchors.map(number => ({ number, parent: null, impl: false })),
    { number: 1493, parent: 1360, impl: true }, ...fixed.map(([number]) => ({ number, parent: 1360, impl: true }))];
  const additions: { ticket: number; commit: string; source: string }[] = [];
  const observed = new Map<number, string[]>();
  const add = (t: number, m: string) => observed.set(t, [...(observed.get(t) ?? []), m]);
  const candidateSignals = history.flatMap(h => {
    const match = /^(?:(?:[\w.-]+(?:\([^()]*\))?|Sandcastle)\s*[: ]\s*)?(?:[\[(]\s*)?(#[0-9]+(?:[ ,/#、，]+#?[0-9]+)*)/i.exec(h.subject);
    const leading = [...(match?.[1].matchAll(/[0-9]+/g) ?? [])].map(m => Number(m[0]));
    const mentions = [...h.body.matchAll(/^(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|part of)\s+#([1-9][0-9]*)/gim)].map(r => Number(r[1]));
    const declared = [...new Set([...leading, ...mentions].filter(n => relevant.has(n)))].sort((a, b) => a - b);
    for (const t of declared) add(t, h.commit);
    return declared.length ? [{
      commit: h.commit, parent: h.parents[0] ?? null, epoch: h.epoch, subject: h.subject,
      prs: [], declared, mentions: [], references: [], tb_markers: [],
    }] : [];
  });
  const failedRun = 39034285362;
  const failedCommit = "8d84e21e2c9e9800a22900c2d4c67878310c1ab9";
  const failedStep = "cargo fmt --check（#611：归零后防回潮）";
  if (mutation.historicalCures && !observed.get(1366)?.includes(failedCommit)) {
    additions.push({ ticket: 1366, commit: failedCommit, source: `https://github.com/${repoId}/issues/1366` });
    add(1366, failedCommit);
  }
  for (const [ticket, commit] of fixed) {
    issue(ticket, "closed", "实现交付 " + commit, ["wayfinder:impl"]);
    if (!observed.get(ticket)?.includes(commit)) {
      additions.push({ ticket, commit, source: `https://github.com/${repoId}/issues/${ticket}` });
      add(ticket, commit);
    }
  }
  issue(1493, "closed", "正式改挂 TB-02。");
  issue(1323, "open"); issue(1340, "open");
  children(1323, []); children(1340, []);
  for (const n of [1493, ...fixed.map(f => f[0])]) children(n, []);
  const shared = "3d61fb72944f577ea3b758b54001c2a7544b04dc";
  const historicalPaths = ["s_session/tests/tb02b_verify.py", "s_session/tests/tb02c_verify.py"];
  if (mutation.historicProducts) for (const [i, ticket] of [1392, 1404].entries()) {
    const id = 89000 + ticket;
    comment(id, ticket, "实际交付 " + shared + " " + historicalPaths[i]);
    if (!observed.get(ticket)?.includes(shared)) {
      add(ticket, shared);
      additions.push({ ticket, commit: shared, source: `https://github.com/${repoId}/issues/${ticket}#issuecomment-${id}` });
    }
  }
  const censusFiles = new Map([
    ["history", { path: censusDir + "all-first-parent.jsonl", bytes: historyBytes }],
    ["relations", { path: censusDir + "sources.json", bytes: raw({ issues: links, followups: [], pull_requests: [], issue_evidence: {} }) }],
    ["signals", { path: censusDir + "candidate-signals.json", bytes: raw(candidateSignals) }],
    ["adjudication", { path: censusDir + "adjudication.json",
      bytes: raw({ admitted_related: {}, additional_associations: additions, rejected_signals: [] }) }],
  ]);
  for (const f of censusFiles.values()) put(f.path, f.bytes);
  const census = raw({ schema_version: "at18-landing-census/1", p0: P0,
    sources: [...censusFiles].map(([role, f]) => ({ role, path: f.path, sha256: byteSha256(f.bytes) })), attributions: [] });
  put(at18 + "landing-census.json", census);

  const prior = src.tree(P0);
  const candidates = new Set<string>();
  const landings: Registry["pregate"]["landings"] = [...observed].sort(([a], [b]) => a - b).map(([n, cs]) => {
    for (const c of cs) {
      const h = history.find(h => h.commit === c)!;
      for (const p of src.changed(h.parents[0], c)) if (prior.has(p) && src.tree(G0).has(p)) candidates.add(p);
    }
    const fixedCure = fixed.find(r => r[0] === n);
    const scope = n >= 1359 && n <= 1368 ? anchors.indexOf(n) + 1 : 2;
    return { ticket: n, commits: sorted(cs), attribution_scopes: [tbId.exclude(["TB-11"]).parse(tbIds[scope - 1])],
      cure_checks: fixedCure ? [{ commit: fixedCure[1], run_id: null, target: fixedCure[2],
        kind: "test", check_id: "cure." + n }] : [] };
  });
  put(at18 + "pregate-review.json", raw({ schema_version: "at18-pregate-review/1", owner_ticket: 2132,
    rows: sorted(candidates).map(path => ({ path, mode: prior.get(path)!.mode, blob: prior.get(path)!.oid, verdict: "PASS" })) }));

  const checks: Registry["checks"] = [];
  const tbl = new Map<string, { check: Registry["checks"][number]; keys: Row[] }>();
  const groups = new Map<string, "simulation" | "experiment">();
  const childIds: { ticket: number; path: string }[] = [];
  const command = "#!/usr/bin/env node\n// Fixture selection and actual witness are represented by the mocked Jobs endpoint.\n";
  for (const [ix, slice] of tbIds.slice(0, 10).entries()) {
    const tag = "control." + slice;
    const c = ix >= 7 ? "experiment" : "simulation";
    const path = ix === 0 ? "scripts/probe.py" : "scripts/at18-fixture/" + tag + ".mjs";
    put(path, command, "100755");
    const check = { check_id: tag, group: tag, evidence_class: c, profile_id: c === "experiment" ? profile : null,
      runner: "command", selector: path, expected_count: 1, key_aware: true,
      source: { path, sha256: note(command) }, record: `tb.${c}.${slice}` } satisfies Registry["checks"][number];
    tbl.set(slice, { check, keys: [] });
    checks.push(check);
    groups.set(tag, c);
    if (c === "experiment") object(permissions.group_actions)[tag] = ["query"];
    const ticket = tbTickets[slice];
    const child = 33001 + ix;
    issue(ticket, "closed", ticket === 1366 && mutation.historicalCures ? "已裁承接 " + failedCommit : undefined); issue(child, "closed", "正式交付", ["wayfinder:impl"]);
    const secondary = ix === 1 ? [1493, ...fixed.map(r => r[0])] : [];
    children(ticket, [child, ...secondary, 34001 + ix]);
    issue(34001 + ix, "open", "仅讨论：非实施片", ["wayfinder:discussion"]);
    children(child, []); children(34001 + ix, []);
    childIds.push({ ticket: child, path });
  }
  for (const special of ["permission", "migration", "post_gate"]) {
    const id = "control." + special;
    const path = ".sandcastle/fixtures/at18/" + id + ".mjs";
    put(path, command, "100755");
    checks.push({ check_id: id, group: id, evidence_class: "experiment", profile_id: profile, runner: "command", selector: path,
      expected_count: 1, key_aware: true, source: { path, sha256: note(command) }, record: special + ".experiment" });
    groups.set(id, "experiment");
    object(permissions.group_actions)[id] = ["query"];
  }
  const originalCures = r11Checks(src);
  for (const [t, , target] of fixed) {
    const original = originalCures.find(c => c.check_id === "r11.backtest." + target)!;
    const bytes = src.blob(r11Source, original.source.path);
    put(original.source.path, bytes);
    checks.push({ ...original, check_id: "cure." + t, group: "control.cures",
      source: { path: original.source.path, sha256: byteSha256(bytes) }, record: null });
  }
  groups.set("control.cures", "simulation");
  const at14Target = "at18_fixture_at14";
  const at14Source = `rust/tests/${at14Target}.rs`;
  const at14Carrier = [
    '#![cfg(feature = "production_session")]',
    'use std::process::Command;',
    ...AT14_LOCKS.flatMap(name => [
      "#[test]", ...(mutation.at14Ci === "ignored" ? ["#[ignore]"] : []), `fn ${name}() {`,
      '    let fixture = std::env::var("AT14_ORACLE_FIXTURE").expect("AT-14 oracle fixture");',
      `    let run = Command::new(fixture).arg("${name}").status().expect("official AT-14 fixture");`,
      '    assert!(run.success());', '}',
    ]),
  ].join("\n") + "\n";
  put(at14Source, at14Carrier);
  const nodeLockPath = ".sandcastle/fixtures/at18/at14-node-locks.mjs";
  const nodeLocks = AT14_LOCKS.map(test => `test("${test}", () => {});\n`).join("");
  if (mutation.at14Node) put(nodeLockPath, nodeLocks);
  AT14_LOCKS.forEach((selector, i) => checks.push({
    check_id: "at14.h" + (i + 1), group: "control.at14", evidence_class: "simulation", profile_id: null,
    runner: mutation.at14Node ? "node-test" : "cargo-test",
    selector: mutation.at14Node ? selector : `test:${at14Target}+production_session/${selector}`,
    expected_count: 1, key_aware: true, record: null,
    source: mutation.at14Node ? { path: nodeLockPath, sha256: note(nodeLocks) } : { path: at14Source, sha256: note(at14Carrier) },
  }));
  groups.set("control.at14", "simulation");

  const map = new Map<string, Registry["bindings"][number]>();
  for (const key of coverage.keys.values()) {
    if (key.slice === "TB-11") continue;
    const producer = tbl.get(key.slice)!;
    for (const b of key.bases) {
      const index = [key.slice, basisId(b), key.entry.boundary].join("\0");
      let binding = map.get(index);
      if (!binding) {
        const { check_id, evidence_class, profile_id } = producer.check;
        binding = {
          binding_id: "b." + (map.size + 1), slice_id: key.slice,
          basis: { ...b, sha256: byteSha256(documents.get(b.path)!) }, keys: [],
          domains: [{ evidence_class, profile_id, result: key.entry.boundary ? "PRESERVED_BOUNDARY" : "VERIFIED",
            deferred_gate: null, checks: [check_id] }],
        };
        map.set(index, binding);
      }
      binding.keys.push({ kind: key.entry.kind, id: key.entry.id });
      producer.keys.push({ kind: key.entry.kind, id: key.entry.id, slice_id: key.slice,
        basis_path: b.path, basis_pointer: b.pointer });
    }
  }
  [...map.values()].find(x => x.slice_id === "TB-07")!.domains[0].checks.push(...AT14_LOCKS.map((_, i) => "at14.h" + (i + 1)));
  const adapterBytes = raw(r);
  const registry: Registry = {
    schema_version: "at18-registry/1", crosswalk_sha256: byteSha256(documents.get(specPaths.crosswalk_ref)!),
    adapter_contract_sha256: byteSha256(adapterBytes), experiment_profile_id: profile, checks,
    bindings: [...map.values()], pregate: { census_sha256: byteSha256(census), landings },
  };
  if (mutation.historicalCures) {
    const owner = registry.pregate.landings.find(l => l.ticket === 1366);
    if (!owner?.commits.includes(failedCommit)) throw new Error("fixture: #1366 historical run is not attributed");
    for (const [ticket, , target] of fixed) {
      if (mutation.historicalCures === "missing" && ticket === 1414) continue;
      const checkId = "r11.backtest." + target;
      const original = checks.find(check => check.check_id === "cure." + ticket)!;
      const group = "control.history." + ticket;
      if (mutation.historicalCures === "empty-node") {
        const path = "scripts/at18-fixture/fake-cure-" + ticket + ".mjs";
        const source = `test(${JSON.stringify(target)}, () => {});\n`;
        put(path, source);
        checks.push({ ...original, check_id: checkId, group, runner: "node-test", selector: target,
          source: { path, sha256: note(source) } });
      } else if (mutation.historicalCures === "empty-rust") {
        const source = fixed.filter(([t]) => t === 1392 ? ticket === 1392 : ticket !== 1392)
          .map(([, , name]) => `#[test]\nfn ${name}() { /* 没有验证 */ }\n`).join("");
        put(original.source.path, source);
        const sourceRef = { path: original.source.path, sha256: note(source) };
        for (const check of checks.filter(c => c.source.path === original.source.path)) check.source = sourceRef;
        checks.push({ ...original, check_id: checkId, group, source: sourceRef });
      } else checks.push({ ...original, check_id: checkId, group });
      groups.set(group, "simulation");
      owner.cure_checks.push({ commit: failedCommit, run_id: failedRun, kind: "test", target, check_id: checkId });
    }
    const checkId = "r11.rustfmt";
    const path = "scripts/at18/cures/rustfmt";
    const script = mutation.historicalCures === "empty-step" ? Buffer.from("#!/usr/bin/env bash\n# no command\n") : src.blob(r11Source, path);
    put(path, script, "100755");
    checks.push({ check_id: checkId, group: "control.history.rustfmt", evidence_class: "simulation", profile_id: null,
      runner: "command", selector: path, source: { path, sha256: byteSha256(script) }, expected_count: 1, key_aware: true, record: null });
    groups.set("control.history.rustfmt", "simulation");
    owner.cure_checks.push({ commit: failedCommit, run_id: failedRun, kind: "step", target: failedStep, check_id: checkId });
  }
  mutation.registry?.(registry);
  const registryBytes = raw(registry), S = byteSha256(registryBytes);
  put(at18 + "registry.json", registryBytes);
  put(at18 + "adapter-contract.json", adapterBytes);
  const dispatch = "on:\n  workflow_dispatch:\n";
  const stepName = "production_session AT-14 H1–H4";
  const at14Filter = mutation.at14Ci === "skip-ci" ? " -- " + AT14_LOCKS.map(name => "--skip " + name).join(" ") :
    mutation.at14Ci === "ignored-only" ? " -- --ignored" : "";
  const at14Command = `cargo test --locked --features production_session --test ${at14Target}${at14Filter}`;
  const prTrigger = mutation.at14Ci === "dispatch-only" ? "" : "  pull_request:\n    branches: [main]\n";
  put(workflows[0], dispatch + prTrigger + "jobs:\n  at18-registry-lint:\n    runs-on: ubuntu-latest\n  ci-ok:\n    needs: at18-registry-lint\n    runs-on: ubuntu-latest\n    steps:\n" +
    `      - name: ${stepName}\n        run: ${at14Command}\n`);
  put(workflows[1], dispatch + "jobs:\n  devskim:\n    name: DevSkim\n    runs-on: ubuntu-latest\n");
  for (const i of [2, 3]) put(workflows[i], dispatch + [
    "jobs:", "  plan:", "    runs-on: ubuntu-latest", "  checks:", "    runs-on: ubuntu-latest",
    "  scaffold:", "    runs-on: ubuntu-latest", "  seal_plan:", "    needs: [plan, checks, scaffold]",
    "  seal:", "    needs: [plan, seal_plan, checks, scaffold]",
    "    if: needs.checks.result == 'success'", "    name: at18-seal ${{ matrix.record }} ${{ matrix.profile }} ${{ needs.plan.outputs.registry_sha }} ${{ matrix.sha256 }}",
    "    strategy:", "      matrix: ${{ fromJSON(needs.seal_plan.outputs.seals) }}",
    "    steps:", "      - run: python scripts/at18/workflow.py seal --group=${{ matrix.group }}",
  ].join("\n") + "\n");
  const feedReplacement = "rust/src/at18_fixture_feed.rs", wireReplacement = "rust/src/at18_fixture_wire.rs";
  put(feedReplacement, mutation.feedReplacement ?? "pub fn normalize(price: f64) -> Option<f64> { (price > 0.0).then_some(price) }\n");
  put(wireReplacement, "pub fn wire_price(raw: u64) -> String { format!(\"{}.{}\", raw / 100, raw % 100) }\n");
  const legacyBasis = at18 + "pregate/fixture-1319-disposition.json";
  const oldFeedWire = [...feedWirePaths.feed, ...feedWirePaths.wire].filter(path => !src.tree(G0).has(path));
  put(legacyBasis, raw({ schema_version: "feed-wire-disposition/1", ticket: 1319,
    dispositions: [...feedWirePaths.feed, ...feedWirePaths.wire].map(path => ({
      path, replacement: oldFeedWire.includes(path) ? null : feedWirePaths.feed.includes(path) ? feedReplacement : wireReplacement,
      rationale: oldFeedWire.includes(path) ? "旧原型未进主线，正式能力另行交付。" : "按 TB-08 重新接入对应能力。",
    })) }));
  let heavyPlan: { path: string; bytes: Buffer } | undefined;
  const heavyControls = ["random-entry", "direction-shuffle"].map(id => ({
    id, definition_sha256: note(id + "/v1"), seed: 20260625, replications: 1000,
  }));
  const heavyTrial = { id: "reference-theta-v0", definition_sha256: note("reference-theta-v0/v1") };
  let heavyRuling: { path: string; bytes: Buffer } | undefined;
  if (mutation.heavyCase?.endsWith("retirement") || mutation.heavyCase === "retired") {
    const path = at18 + "pregate/fixture-1320-retirement.json";
    const bytes = raw({ schema_version: "at18-heavy-retirement/1", ticket: 1320,
      obligation: "ISSUE_1320_HEAVY_MEASUREMENT", decision_ticket: 39004, authorization_comment_id: 39004001,
      disposition: "RETIRE", scope: "SEVEN_SYMBOL_FROZEN_10Y_1MIN_MEASUREMENT_ONLY", rationale: "独立授权只废弃重型测量。" });
    put(path, bytes);
    heavyRuling = { path, bytes };
    issue(39004, "closed", "独立裁定", ["wayfinder:decision"]);
    const approval = { ...comment(39004001, 39004, "```at18-heavy-retirement-approval/1\n" + canonicalizeJcs({
      decision_ticket: 39004, ticket: 1320, obligation: "ISSUE_1320_HEAVY_MEASUREMENT", disposition: "RETIRE",
      decision_sha256: byteSha256(bytes),
    }) + "\n```"), author_association: mutation.heavyCase === "retired" ? "OWNER" : "CONTRIBUTOR",
      user: { type: "User" }, updated_at: "2026-11-01T07:00:00Z" };
    api["issues/39004/comments?per_page=100"] = [approval];
  } else if (mutation.heavyCase) {
    const path = at18 + "pregate/fixture-1320-prereg.json";
    const bytes = raw({ schema_version: "at18-heavy-preregistration/1", ticket: 1320, design: "FROZEN_PREREGISTERED_DUAL_CONTROLS",
      protocol_sha256: byteSha256(src.blob("7fa4a278eec54704637dd68dcb6101d6dbccdd6a", "docs/backtest-protocol-v0.md")),
      windows_sha256: byteSha256(src.blob(G0, "docs/backtest-prereg-windows-v0.md")),
      symbols: heavySymbols, interval: "1min", trials: [heavyTrial], controls: heavyControls });
    put(path, bytes);
    heavyPlan = { path, bytes };
  }
  const fence = (d: object) => "```at18-product-delivery/1\n" + canonicalizeJcs(d) + "\n```";
  put(ownPaths[0], "export const report = 'fixture report';\n");
  const a = merge(G0, 39001, "#1391 fixture report", "impl/1391-report",
    childIds.map(({ ticket, path }) => `Fixes #${ticket}\n\n${fence({ ticket, paths: [path] })}`).join("\n\n"));
  for (const { ticket, path } of childIds) {
    object(api["issues/" + ticket]).body = fence({ ticket, products: [{ commit: a, path }] });
  }
  for (const [ticket, commit] of fixed) {
    const h = history.find(row => row.commit === commit)!;
    const path = src.changed(h.parents[0], commit).find(path => {
      try { return src.blob(commit, path).length > 0; } catch { return false; }
    });
    if (!path) throw new Error("fixture: historical product missing");
    object(api["issues/" + ticket]).body = "实现交付 " + commit + "\n\n" + fence({ ticket, products: [{ commit, path }] });
  }
  if (mutation.historicProducts) for (const [i, ticket] of [1392, 1404].entries()) {
    const row = object(api["issues/" + ticket]);
    row.body = String(row.body).split("\n\n")[0] + "\n\n" + fence({ ticket, products: [{
      commit: shared, path: historicalPaths[mutation.historicProducts === "swapped" ? 1 - i : i],
    }] });
  }
  if (mutation.heavyCase === "late-review") {
    object(api["pulls/39001"]).merged_at = "2026-11-03T11:00:00Z";
    const head = object(object(api["pulls/39001"]).head).sha;
    const status = rows(api[`commits/${head}/statuses?per_page=100`])[0];
    status.created_at = "2026-11-03T10:00:00Z";
  }
  put(ownPaths[1], "export const verification = 'fixture verification';\n");
  const b = merge(a, 39002, "#1403 fixture verification", "impl/1403-verification");
  let parent = b;
  if (mutation.emptyProduct) {
    const [child] = childIds;
    parent = merge(b, 39005, "#33001 close only", "fixture/33001-close-only",
      `Closes #${child.ticket}\n\n${fence({ ticket: child.ticket, paths: [child.path] })}`);
    object(api["issues/" + child.ticket]).body = fence({ ticket: child.ticket, products: [{ commit: parent, path: child.path }] });
  }
  const profileEcho = { schema_revision: "history-input-profile/1", evidence_class: "simulation", input_source: "massive-stock-tick/1",
    clock: { kind: "logical-bar/1", known_frontier_cut: "bar_close" }, funding: { policy_refs: ["funding/1"] },
    structure: { source_ref: "fixture" }, model: { input_domain: ["control"] }, initial_positions: ["fixture-position"],
    scenario_contract: { scheduler: "launcher-sched/sequential/1" } };
  const manifestEcho = { manifest_revision: "production-session-manifest/1", profile: "simulation", state_dir: "/tmp/at14-fixture/state",
    s: { db: "/tmp/at14-fixture/s.db" }, economic: { manifest: "/tmp/at14-fixture/economic.json" },
    x: { db: "/tmp/at14-fixture/x.db", profile: "/tmp/at14-fixture/x-profile.json" } };
  const profileHash = note(canonicalizeJcs(profileEcho));
  const reviewBinding = git(["rev-parse", b + "^2"]);
  const model = "history-sim/bar-batch-known-frontier/1";
  const faultSchedule = [{ at: { kind: "bar_index", value: 1 }, target: { domain: "e" }, kind: "crash_after_commit" }];
  const scheduleTrace = [{ step: 1, bar_index: 1, stage: "E->X", triggered_fault: "crash_after_commit", detail: "fixture recovery" }];
  const at14: Row = {
    schema_version: "at14-report/1", verdict: { kind: "PASS" },
    build_fingerprint: { commit: b, lockfile_hash: byteSha256(src.blob(G0, "rust/Cargo.lock")), features: ["production_session"] },
    version_set: { rule_versions: [{ rule_id: "strict", version: "1", content_hash: note("strict") }],
      policy_refs: [{ policy_id: "funding", version: "1", profile_id: null, content_hash: note("policy") }],
      model_ref: { model_id: model, revision: "1", content_hash: note("model") } },
    session: { evidence_class: "simulation", manifest_revision: manifestEcho.manifest_revision,
      manifest_hash: note(canonicalizeJcs(manifestEcho)), manifest_echo: manifestEcho,
      profile_revision: profileEcho.schema_revision, profile_hash: profileHash, profile_echo: profileEcho,
      clock_kind: "logical-bar/1", scheduler: "launcher-sched/sequential/1" },
    model_execution: { model_id: model, seed: "none", capacity_source: "scenario_contract" },
    dual_run_tuple: { input_profile_hash: profileHash, input_events_hash: note("events"), policy_version: "1",
      model_id: model, model_revision: "1", seed: "none", scheduler: "launcher-sched/sequential/1",
      fault_schedule_hash: note(canonicalizeJcs(faultSchedule)), schedule_trace_hash: note(canonicalizeJcs(scheduleTrace)) },
    capability_manifest_hash: note("fixture capacity"),
    actual_load: { input_range: { symbols: ["ES"], from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" },
      bar_count: 17, checkpoint_count: 17 },
    fault_schedule: faultSchedule, schedule_trace: scheduleTrace,
    ...Object.fromEntries(AT14_LOCKS.map((test_name, i) => ["h" + (i + 1), { result: "PASS", diff_count: 0, test_name, diff_summary: "" }])),
    six_faces: Object.fromEntries(["s_structure_snapshot", "b_chong_ledgers", "e_responsibility", "orders_and_fills",
      "physical_positions", "external_effect_journal"].map(face => [face, { row_count: 1, diff_count: 0, diff_summary: "" }])),
    fu14_gates: Object.fromEntries(["a_launcher_process_tree", "b_six_domains_nonempty", "c_model_order_unspecified_no_legacy",
      "d_shadow_component_only"].map(id => [id, { result: "PASS" }])),
    unexecuted: [], model_order_unspecified_count: 0, diagnostic_not_production_count: 0, input_source_unavailable_count: 0,
    input_source: "massive-stock-tick/1", verification_source_label: null,
    assumption_counts: { stochastic_l1_count: 0, bar_volume_derived_l0_count: 0, unconstrained_capacity_l0_count: 0 },
    bounded_domain_statement: "仅证有界受测域", ci_run_id: "49010", review_binding: reviewBinding,
  };
  const at14Dir = `.chanlun/review-results/issue1304-at14-20261101-${b.slice(0, 7)}/`;
  const unmutated = acceptedAt14.parse({ ...at14, content_hash: computeContentHash(at14) });
  mutation.at14?.(at14);
  const sealed = { ...at14, content_hash: computeContentHash(at14) };
  const accepted = acceptedAt14.safeParse(sealed);
  const officialSummary = at14Summary(accepted.success ? accepted.data : unmutated);
  put(at14Dir + "at14-report.json", raw(sealed));
  if (mutation.summary !== "missing") put(at14Dir + "summary.md", mutation.summary === "inconsistent"
    ? officialSummary.replace("- verdict: `PASS`", "- verdict: `FAIL`") : officialSummary);
  api["actions/runs/49010"] = { id: 49010, run_attempt: 1, head_sha: b, path: workflows[0], status: "completed",
    conclusion: "success", event: "pull_request", repository: githubRepo, head_repository: githubRepo };
  const lockJob = { id: 58980, run_id: 49010, run_attempt: 1, head_sha: b, name: "ci-ok",
    status: "completed", conclusion: "success", steps: [{ name: stepName, number: 1, status: "completed", conclusion: "success" }] };
  api["actions/runs/49010/attempts/1/jobs?per_page=100"] = { total_count: 1, jobs: [lockJob] };
  api["actions/jobs/58980/logs"] = ["##[group]Run " + at14Command, "##[endgroup]",
    `     Running tests/${at14Target}.rs (target/debug/deps/${at14Target}-e1)`, "running 4 tests", ...AT14_LOCKS.slice(0, mutation.at14Ci === "unrecorded" ? 3 : 4)
    .map(name => `test ${name} ... ok`), "test result: ok."].join("\n");
  const F = merge(parent, 39003, "#1418 fixture entity publication", "impl/1418-publication");
  git(["update-ref", "refs/remotes/origin/main", F]);
  api["git/ref/heads/main"] = { ref: "refs/heads/main", object: { sha: F, type: "commit" } };
  const runId = (i: number) => 49000 + i;
  const jobs: Row[][] = [[], [], [], []];
  let jobId = 59000;
  const job = (i: number, name: string) => {
    jobs[i].push({ id: ++jobId, name, run_id: runId(i), run_attempt: 2, head_sha: F,
      status: "completed", conclusion: "success", labels: i === 3 ? ["self-hosted", "p1-isolated"] : ["ubuntu-latest"],
      runner_group_name: i === 3 ? "p1-fixture" : "GitHub Actions" });
  };
  job(0, "ci-ok"); job(0, "at18-registry-lint"); job(1, "DevSkim");
  for (const [g, c] of groups) {
    const i = c === "simulation" ? 2 : 3;
    job(i, `at18 ${g} ${S}`);
    if (mutation.historicalCures === "failed" && g === "control.history.1414") jobs[i].at(-1)!.conclusion = "failure";
  }

  const external = new Map<number, { path: string; sha256: string; storage: "external"; ticket: number; base: string; head: string }[]>();
  const artifact = (n: number, filename: string, body: Buffer) => {
    const path = join(evidence, filename);
    write(path, body);
    const declaration = { path, sha256: byteSha256(body), storage: "external" as const, ticket: n, base: G0, head: F };
    external.set(n, [...(external.get(n) ?? []), declaration]);
    return declaration.sha256;
  };
  function record(check: Registry["checks"][number], payload: Row, suffix = "") {
    const i = check.evidence_class === "simulation" ? 2 : 3;
    const content: Row = { schema_version: "at18-run-record/1", record: check.record, check_id: check.check_id,
      profile_id: check.profile_id, head: F, run_id: runId(i), run_attempt: 2, payload };
    mutation.records?.(content);
    const omitted = mutation.omitRecord?.(content) ?? false;
    const bytes = raw(content);
    const hash = omitted ? byteSha256(bytes) : artifact(1391, check.record + suffix + ".json", bytes);
    job(i, `at18-seal ${check.record} ${check.profile_id ?? "none"} ${S} ${hash}`);
  }
  for (const [slice, { check, keys }] of tbl) record(check, {
    schema_version: "at18-tb-entity/1", tb_id: slice, evidence_class: check.evidence_class, profile_id: check.profile_id,
    tests: [{ check_id: check.check_id, name: check.selector, source_path: check.source.path }], keys,
    conditions: { processes: 2 }, output: { samples: [1, 2] },
  });
  const cap = artifact(1770, "capability.json", raw({ version: "hl-testnet-capability/1", session_permission: {
    source: { url: "https://example.invalid/session-permission", retrieved_at: "2026-10-01T00:00:00Z", sha256: note("venue source") },
  } }));
  const prof = artifact(1351, "profile.json", raw({ profile_id: profile, version: 1, evidence_class: "experiment",
    account: "synthetic-account", allowed_actions: ["query"], credential_scope: { class: "trade_no_transfer", public_id: "synthetic-agent" },
    authorization: { authorization_id: "fixture-auth", authorizer: "synthetic-account", authorized_at: "2026-10-01T00:00:00Z" } }));
  record(checks.find(c => c.record === "permission.experiment")!, {
    schema_version: "at18-permission/1", venue_profile_sha256: prof, capability_record_sha256: cap,
    derived_credential_public_id: "synthetic-agent",
    user_role: { request: { public_id: "synthetic-agent" }, response: { role: "agent", data: { user: "synthetic-account" } },
      received_at: "2026-11-01T06:00:00Z" },
    binding: { writer_epoch: 2, profile_id: profile, profile_version: 1, venue_profile_sha256: prof,
      capability_record_version: "hl-testnet-capability/1", capability_record_sha256: cap, tb09_fingerprint: note("fixture capability"),
      authorization_id: "fixture-auth", evidence_class: "experiment" },
    launch: { writer_epoch: 2, launch_seq: 1, launched_at: "2026-11-01T06:01:00Z", tb09_fingerprint_computed: note("fixture capability"),
      credential_public_id_verified: true, session_permission_verified: true,
      send_state: "can_send", send_refusal_class: null, send_refusal_detail: null },
  });
  const movement = (prefix: string, owner_epoch: number) => {
    const entry = (kind: string) => [{ id: prefix + kind, owner: "fixture-owner", account: "fixture-account", asset: "USD", quantity: "1.0" }];
    return { positions: entry("position"), open_orders: entry("order"), fee_tail: entry("fee"), capital: entry("capital"), owner_epoch };
  };
  const ledger = ["position", "order", "fee", "capital"].map(kind => ({ kind, old_id: "old-" + kind, new_id: "new-" + kind }));
  const old = movement("old-", 1), after = movement("new-", 2);
  const baseMigr = { schema_version: "at18-migration/1", profile_id: profile, evidence_class: "experiment", identity_map: ledger,
    old_before: old, new_after: after, after_recovery: after, after_rollback: after,
    interruption: { step: "cutover", interrupted_at: "2026-11-01T06:00:00Z", recovered_at: "2026-11-01T06:00:00.001Z" } };
  const migrationCheck = checks.find(c => c.record === "migration.experiment")!;
  record(migrationCheck, { ...baseMigr,
    ownership_journal: ledger.map((l, i) => ({ sequence: i + 1, id: l.new_id, owner: "fixture-owner", writer_epoch: 2 })),
    capital_journal: [{ sequence: 1, id: "new-capital", account: "fixture-account", asset: "USD", quantity: "1" }],
    writer_journal: [], send_journal: [],
  }, "-ownership");
  record(migrationCheck, { ...baseMigr, ownership_journal: [], capital_journal: [],
    writer_journal: [
      { sequence: 1, writer_epoch: 1, writer_id: "old-writer", operation: "release" },
      { sequence: 2, writer_epoch: 2, writer_id: "new-writer", operation: "acquire" },
      { sequence: 3, writer_epoch: 2, writer_id: "new-writer", operation: "write" },
    ],
    send_journal: [{ sequence: 1, command_id: "fixture-command", writer_epoch: 1, operation: "may_have_called" }],
  }, "-writers");
  const enabled = mutation.enabledWithoutFirstActivation === true;
  if (enabled) artifact(1358, "post-gate-version.json", raw({ parameter_version_id: "fixture-pv",
    profile_id: profile, evidence_class: "experiment", gate_event_id: "fixture-gate",
    authorized_at: "2026-11-01T06:00:00.000000002Z", authorizer: "synthetic-account", parameters: { policy: "fixture" } }));
  record(checks.find(c => c.record === "post_gate.experiment")!, {
    schema_version: "at18-post-gate/1", profile_id: profile, evidence_class: "experiment", growth_eligible: enabled,
    growth_enabled: enabled, post_gate_params_effective: enabled, outputs: [], parameter_version_id: enabled ? "fixture-pv" : null,
    gate_events: enabled ? [{ type: "GateReachedEvent", profile_id: profile, evidence_class: "experiment",
      known_at: "2026-11-01T06:00:00.000000001Z", event_id: "fixture-gate" }] : [], first_activations: [],
  });
  artifact(1368, "entry-inventory.json", raw({ schema_version: "tb-entry-inventory/1", head: F,
    entries: [{ path: "rust/src/recursive_t/mod.rs", disposition: "FROZEN", replacement: null }] }));
  const feedEntries = [...feedWirePaths.feed, ...feedWirePaths.wire].map(path => oldFeedWire.includes(path)
    ? { path, disposition: "RETIRED", basis: legacyBasis, anchor: a }
    : { path, disposition: "INCORPORATED", basis: legacyBasis, replacement: feedWirePaths.feed.includes(path) ? feedReplacement : wireReplacement, anchor: a });
  artifact(1367, "feed-wire.json", raw({ schema_version: "feed-wire-inventory/1", head: F,
    entries: mutation.feedWire?.(feedEntries) ?? feedEntries }));
  if (heavyRuling) artifact(1320, "heavy-retirement.json", raw({ schema_version: "at18-heavy-retirement-reference/1", head: F,
    decision: { commit: a, path: heavyRuling.path, sha256: byteSha256(heavyRuling.bytes) } }));
  if (heavyPlan) {
    const preregistration_sha256 = byteSha256(heavyPlan.bytes);
    const symbols = heavySymbols.map(symbol => {
      const first_bar_at = "2015-01-01T00:00:00Z";
      const last_bar_at = mutation.heavyCase === "short" && symbol === "ES" ? "2024-12-31T23:59:00Z" : "2025-01-01T00:00:00Z";
      const at = "2020-01-01T00:00:00Z";
      const stamps = mutation.heavyCase === "one-bar" && symbol === "ES" ? [first_bar_at] : [first_bar_at, at, last_bar_at];
      const scope = { head: F, symbol, interval: "1min", first_bar_at, last_bar_at, bars: stamps.length };
      const chunks = stamps.map((time, i) => artifact(1320, `heavy-${symbol}-input-${i}.json`, raw({
        schema_version: "at18-heavy-input-chunk/1", head: F, symbol, interval: "1min",
        bars: [{ at: time, open: 100 + i, low: 99 + i, high: 102 + i, close: 101 + i, volume: 12 }],
      })));
      const series = raw({ ...scope, schema_version: "at18-heavy-input-series/1", chunks });
      const input_sha256 = mutation.heavyCase === "input-unregistered" && symbol === "ES" ? note(symbol + " unregistered") :
        artifact(1320, `heavy-${symbol}-input.json`, series);
      const common = { ...scope, preregistration_sha256, input_sha256 };
      const outputs = {
        trades: [{ id: "trade-1", opened_at: at, closed_at: "2020-01-01T00:01:00Z", pnl: -1, drawdown: 1 }],
        voice_lifecycle: [{ at, voice_id: "voice-1", transition: "created" }],
        center_transitions: [{ at, center_id: "center-1", transition: "entered" }],
      };
      const runs = ["replay-a", "replay-b"].map((id, i) => {
        const divergence = mutation.heavyCase === "output-diverges" && symbol === "ES" && i === 1;
        const output_sha256 = artifact(1320, `heavy-${symbol}-${id}-output.json`, raw({
          schema_version: "at18-heavy-replay-output/1", head: F, symbol, run_id: id,
          outputs: divergence ? { ...outputs, voice_lifecycle: [{ at, voice_id: "voice-1", transition: "terminated" }] } : outputs,
        }));
        const receipt = raw({ ...common, schema_version: "at18-heavy-replay-run/1", run_id: id,
          started_at: `2026-11-02T0${i}:00:00Z`, finished_at: `2026-11-02T0${i}:30:00Z`, output_sha256 });
        const result_sha256 = mutation.heavyCase === "second-run-missing" && i === 1 ? byteSha256(receipt) :
          artifact(1320, `heavy-${symbol}-${id}-run.json`, receipt);
        return { id, result_sha256 };
      });
      const replay_sha256 = artifact(1320, `heavy-${symbol}-replay.json`, raw({
        ...common, schema_version: "at18-heavy-replay/1", runs,
      }));
      const trials = [heavyTrial].map(t => {
        const id = mutation.heavyCase === "wrong-trial" && symbol === "ES" ? "other-trial" : t.id;
        return { id, result_sha256: artifact(1320, `heavy-${symbol}-${id}.json`, raw({
          ...common, schema_version: "at18-heavy-arm-result/1", id, definition_sha256: t.definition_sha256, kind: "trial", seed: null,
          results: [{ replication: 0, sharpe: -0.5, cagr: -0.02, trades: 1 }],
        })) };
      });
      const controls = heavyControls.slice(0, mutation.heavyCase === "missing-control" && symbol === "ES" ? 1 : 2).map(c => ({
        id: c.id, result_sha256: artifact(1320, `heavy-${symbol}-${c.id}.json`, raw({
          ...common, schema_version: "at18-heavy-arm-result/1", id: c.id, definition_sha256: c.definition_sha256, kind: "control", seed: c.seed,
          results: Array.from({ length: c.replications }, (_, replication) => ({ replication, sharpe: 0, cagr: 0, trades: 110 })),
        })),
      }));
      const result_sha256 = artifact(1320, `heavy-${symbol}.json`, raw({
        ...common, schema_version: "at18-heavy-symbol-result/1", replay_sha256, trials, controls,
      }));
      const { head: _head, ...index } = scope;
      return { ...index, years: 10, result_sha256 };
    });
    artifact(1320, "heavy-measurement.json", mutation.heavyCase === "malformed-heavy" ? Buffer.from('{"schema') : raw({ schema_version: "at18-heavy-measurement/1", head: F,
      design: "FROZEN_PREREGISTERED_DUAL_CONTROLS", preregistration: { commit: a, path: heavyPlan.path, sha256: preregistration_sha256 },
      started_at: "2026-11-02T00:00:00Z", finished_at: "2026-11-03T00:00:00Z", symbols }));
  }

  for (const [i, path] of workflows.entries()) {
    const workflowId = 69000 + i;
    api["actions/workflows/" + path.split("/").at(-1)] = { id: workflowId, path };
    const run = { id: runId(i), run_attempt: 2, workflow_id: workflowId, path, head_sha: F, head_branch: "main",
      status: "completed", conclusion: "success", event: "workflow_dispatch", html_url: `https://github.com/${repoId}/actions/runs/${runId(i)}`,
      updated_at: current, repository: githubRepo, head_repository: githubRepo };
    api[`actions/workflows/${workflowId}/runs?head_sha=${F}&branch=main&event=workflow_dispatch&per_page=100`] = { workflow_runs: [run], total_count: 1 };
    api[`actions/runs/${runId(i)}/attempts/2/jobs?per_page=100`] = { jobs: jobs[i], total_count: jobs[i].length };
    if (i < 2) for (const commit of new Set([...observed.values()].flat())) {
      api[`actions/workflows/${workflowId}/runs?head_sha=${commit}&branch=main&event=push&per_page=100`] = { workflow_runs: [], total_count: 0 };
    }
  }
  if (mutation.historicalCures) {
    api[`actions/workflows/69000/runs?head_sha=${failedCommit}&branch=main&event=push&per_page=100`] = {
      workflow_runs: [{ id: failedRun, conclusion: "failure", status: "completed", head_sha: failedCommit, event: "push",
        head_branch: "main", workflow_id: 69000 }], total_count: 1 };
    api[`actions/runs/${failedRun}/jobs?per_page=100`] = { jobs: [{ steps: [{ name: failedStep, conclusion: "failure" }] }], total_count: 1 };
  }
  const manifestPaths = new Map<number, string>();
  for (const [ticket, reports] of external) {
    const path = join(evidence, "manifest-" + ticket + ".json");
    write(path, raw({ schemaVersion: 1, ticket, base: G0, head: F, productDiff: [], requiredReports: [],
      reports, reviews: [], requiredChecks: [], checks: [], scan: { status: "not_run" }, externalReportsRoot: evidence }));
    manifestPaths.set(ticket, path);
  }
  mutation.api?.(api);
  const apiFile = join(dir, "api.json");
  write(apiFile, raw(api));
  const gh = join(bin, "gh");
  write(gh, readFileSync(join(fixture, "gh-fixture.cjs")));
  chmodSync(gh, 0o700);
  return { dir, root, bin, apiFile, F, manifest: manifestPaths.get(1391)!, upstream: [...manifestPaths].filter(([n]) => n !== 1391).map(([, p]) => p) };
}
