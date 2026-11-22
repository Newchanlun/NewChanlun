import { execFileSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { at18, At18Repository, Diagnostics, G0, P0, sorted, utf8 } from "./at18-source.ts";
import { basisId, readCoverage } from "./at18-coverage.ts";
import { adapter as decodeAdapter, type Registry } from "./at18-contract.ts";
import {
  byteSha256, canonicalizeJcs, computeContentHash, ledgerPaths, parseJsonObject, specPaths, tbIds, tbTickets, workflows,
} from "./at18-format.ts";
import { object, type Row } from "./at18-github.ts";
import { AT14_LOCKS } from "./at18-legacy.ts";

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
  ], { input, stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"], maxBuffer: 64 * 1024 * 1024, timeout: 20_000 }).toString().trim();
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
    const H = git(["commit-tree", tree, "-p", parent], title);
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
    const destination = (stories.stories as Row[]).find(row => row.id === "US-DST-01")!;
    destination.observable_result = null;
    documents.set(specPaths.spec_ref, raw(stories));
  }
  for (const [path, bytes] of documents) put(path, bytes);
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
  const hist = utf8(src.git("log", "-z", "--first-parent", "--format=%H%x00%P%x00%ct%x00%s%x00%b", P0)).split("\0");
  const history: { commit: string; parents: string[]; epoch: number; subject: string; body: string }[] = [];
  for (let i = 0; i + 5 < hist.length; i += 5) {
    const [commit, parents, epoch, subject, body] = hist.slice(i, i + 5);
    history.push({ commit, parents: parents.split(" ").filter(Boolean), epoch: Number(epoch), subject, body });
  }
  const censusDir = at18 + "pregate/";
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
  const censusFiles = new Map([
    ["history", { path: censusDir + "all-first-parent.jsonl", bytes: Buffer.from(history.map(h => canonicalizeJcs(h)).join("\n") + "\n") }],
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
    return { ticket: n, commits: sorted(cs), attribution_scopes: [tbIds[scope - 1] as "TB-02"],
      cure_checks: fixedCure ? [{ commit: fixedCure[1], run_id: null, target: fixedCure[2],
        kind: "test", check_id: "cure." + n }] : [] };
  });
  put(at18 + "pregate-review.json", raw({ schema_version: "at18-pregate-review/1", owner_ticket: 2132,
    rows: sorted(candidates).map(path => ({ path, mode: prior.get(path)!.mode, blob: prior.get(path)!.oid, verdict: "PASS" })) }));

  const checks: Registry["checks"] = [];
  const tbl = new Map<string, { check: Registry["checks"][number]; keys: Row[] }>();
  const groups = new Map<string, "simulation" | "experiment">();
  const childIds = [];
  const command = "#!/usr/bin/env node\n// Fixture selection and actual witness are represented by the mocked Jobs endpoint.\n";
  for (const [ix, slice] of tbIds.slice(0, 10).entries()) {
    const tag = "control." + slice;
    const c = ix >= 7 ? "experiment" : "simulation";
    const path = ".sandcastle/fixtures/at18/" + tag + ".mjs";
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
    issue(ticket); issue(child, "closed", "正式交付", ["wayfinder:impl"]);
    const secondary = ix === 1 ? [1493, ...fixed.map(r => r[0])] : [];
    children(ticket, [child, ...secondary, 34001 + ix]);
    issue(34001 + ix, "open", "仅讨论：非实施片", ["wayfinder:discussion"]);
    children(child, []); children(34001 + ix, []);
    childIds.push(child, ...secondary);
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
  const curePath = ".sandcastle/fixtures/at18/control-cures.mjs";
  const cureSource = [...fixed.map(f => f[2]), ...AT14_LOCKS].map(test => `test("${test}", () => {});\n`).join("");
  put(curePath, cureSource);
  for (const [t, , selector] of fixed) {
    checks.push({ check_id: "cure." + t, group: "control.cures", evidence_class: "simulation", profile_id: null,
      runner: "node-test", selector, expected_count: 1, key_aware: true, source: { path: curePath, sha256: note(cureSource) }, record: null });
  }
  groups.set("control.cures", "simulation");
  AT14_LOCKS.forEach((selector, i) => checks.push({
    check_id: "at14.h" + (i + 1), group: "control.at14", evidence_class: "simulation", profile_id: null,
    runner: "node-test", selector, expected_count: 1, key_aware: true, source: { path: curePath, sha256: note(cureSource) }, record: null,
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
  mutation.registry?.(registry);
  const registryBytes = raw(registry), S = byteSha256(registryBytes);
  put(at18 + "registry.json", registryBytes);
  put(at18 + "adapter-contract.json", adapterBytes);
  const dispatch = "on:\n  workflow_dispatch:\n";
  put(workflows[0], dispatch + "jobs:\n  at18-registry-lint:\n    runs-on: ubuntu-latest\n  ci-ok:\n    needs: at18-registry-lint\n    runs-on: ubuntu-latest\n");
  put(workflows[1], dispatch + "jobs:\n  devskim:\n    name: DevSkim\n    runs-on: ubuntu-latest\n");
  for (const i of [2, 3]) put(workflows[i], dispatch + [
    "jobs:", "  plan:", "    runs-on: ubuntu-latest", "  checks:", "    runs-on: ubuntu-latest",
    "  scaffold:", "    runs-on: ubuntu-latest", "  seal_plan:", "    needs: [plan, checks, scaffold]",
    "  seal:", "    needs: [plan, seal_plan, checks, scaffold]",
    "    if: needs.checks.result == 'success'", "    name: at18-seal ${{ matrix.record }} ${{ matrix.profile }} ${{ needs.plan.outputs.registry_sha }} ${{ matrix.sha256 }}",
    "    strategy:", "      matrix: ${{ fromJSON(needs.seal_plan.outputs.seals) }}",
    "    steps:", "      - run: python scripts/at18/workflow.py seal --group=${{ matrix.group }}",
  ].join("\n") + "\n");
  put(ownPaths[0], "export const report = 'fixture report';\n");
  const a = merge(G0, 39001, "#1391 fixture report", "impl/1391-report", childIds.map(n => "Fixes #" + n).join("\n"));
  put(ownPaths[1], "export const verification = 'fixture verification';\n");
  const b = merge(a, 39002, "#1403 fixture verification", "impl/1403-verification");
  const profileEcho = { schema_revision: "history-input-profile/1", evidence_class: "simulation",
    clock: { kind: "logical-bar/1", known_frontier_cut: "bar_close" }, funding: { policy_refs: [] },
    structure: { source_ref: "fixture" }, model: { input_domain: ["control"] }, initial_positions: [],
    scenario_contract: { scheduler: "launcher-sched/sequential/1" } };
  const manifestEcho = { manifest_revision: "production-session-manifest/1", profile: "simulation" };
  const profileHash = note(canonicalizeJcs(profileEcho));
  const at14 = {
    schema_version: "at14-report/1", verdict: { kind: "PASS" },
    build_fingerprint: { commit: b, lockfile_hash: note("Cargo.lock"), features: ["production_session"] },
    session: { evidence_class: "simulation", manifest_revision: manifestEcho.manifest_revision,
      manifest_hash: note(canonicalizeJcs(manifestEcho)), manifest_echo: manifestEcho,
      profile_revision: profileEcho.schema_revision, profile_hash: profileHash, profile_echo: profileEcho,
      clock_kind: "logical-bar/1", scheduler: "launcher-sched/sequential/1" },
    dual_run_tuple: { input_profile_hash: profileHash }, capability_manifest_hash: note("fixture capacity"),
    actual_load: { input_range: { symbols: ["ES"], from: "2026-01-01T00:00:00Z", to: "2026-01-02T00:00:00Z" },
      bar_count: 17, checkpoint_count: 17 },
    fault_schedule: [{ kind: "SIGKILL" }], schedule_trace: [{ sequence: 1 }],
    ...Object.fromEntries(AT14_LOCKS.map((test_name, i) => ["h" + (i + 1), { result: "PASS", diff_count: 0, test_name, diff_summary: "" }])),
    six_faces: Object.fromEntries(["s_structure_snapshot", "b_chong_ledgers", "e_responsibility", "orders_and_fills",
      "physical_positions", "external_effect_journal"].map(face => [face, { row_count: 1, diff_count: 0, diff_summary: "" }])),
    unexecuted: [], model_order_unspecified_count: 0, diagnostic_not_production_count: 0, input_source_unavailable_count: 0,
  };
  put(`.chanlun/review-results/issue1304-at14-20261101-${b.slice(0, 7)}/at14-report.json`, raw({
    ...at14, content_hash: computeContentHash(at14),
  }));
  const F = merge(b, 39003, "#1418 fixture entity publication", "impl/1418-publication");
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
  for (const [g, c] of groups) job(c === "simulation" ? 2 : 3, `at18 ${g} ${S}`);

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
    conditions: { processes: 2 }, output: { samples: [[1, 2, 3]] },
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
  artifact(1367, "feed-wire.json", raw({ schema_version: "feed-wire-inventory/1", head: F,
    entries: [{ path: "rust/Cargo.toml", disposition: "FROZEN", replacement: null }] }));

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
