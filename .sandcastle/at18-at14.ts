import { at14CiSteps, recordedAt14Steps, type RustLock } from "./at18-at14-ci.ts";
import { rustTest } from "./at18-code.ts";
import { z } from "zod";
import { type Bindings, unique } from "./at18-coverage.ts";
import { byteSha256, canonicalizeJcs, computeContentHash, digest, integer, parseJsonObject,
  sha, text, utc, workflows } from "./at18-format.ts";
import { object } from "./at18-github.ts";
import { success, utcBefore, type ReviewRef } from "./at18-integrations.ts";
import { type At18Repository, type Diagnostics, repoRef, utf8, valueAt } from "./at18-source.ts";

export const AT14_LOCKS = ["dual_run_determinism_h1", "recovery_after_kill_h2", "seek_no_future_leak_h3", "asknown_evidence_segregation_h4"];
const AT14 = /^\.chanlun\/review-results\/(?:issue1304-at14|issue1366-at14)-[0-9]{8}-[0-9a-f]{7,40}\/at14-report\.json$/;
const n = z.int().nonnegative();
const pass = z.strictObject({ result: z.literal("PASS") });
const oracle = pass.extend({ test_name: text, diff_count: z.literal(0), diff_summary: z.string() });
const face = z.strictObject({ row_count: integer, diff_count: z.literal(0), diff_summary: z.string() });
const seed = z.union([z.literal("none"), n]);
const fault = z.enum(["crash_before_commit", "crash_after_commit", "reorder_reports", "drop", "duplicate", "restart",
  "writer_epoch_bump", "store_unreadable", "store_write_failure"]);
const echo = z.record(z.string(), z.unknown());
const knownModel = z.enum(["history-sim/bar-batch-known-frontier/1", "recorded-venue-replay/1"]);
const faces = z.strictObject({ s_structure_snapshot: face, b_chong_ledgers: face, e_responsibility: face,
  orders_and_fills: face, physical_positions: face, external_effect_journal: face });

// #1418 2d77870e 的 At14ReportBody。只接收可用于 #1304 的 PASS 子集。
export const acceptedAt14 = z.strictObject({
  schema_version: z.literal("at14-report/1"),
  content_hash: digest,
  verdict: z.strictObject({ kind: z.literal("PASS") }),
  session: z.strictObject({ manifest_revision: z.literal("production-session-manifest/1"), manifest_hash: digest, manifest_echo: echo,
    profile_revision: z.literal("history-input-profile/1"), profile_hash: digest, profile_echo: echo,
    evidence_class: z.literal("simulation"), clock_kind: z.literal("logical-bar/1"), scheduler: z.literal("launcher-sched/sequential/1") }),
  build_fingerprint: z.strictObject({ commit: sha, lockfile_hash: digest, features: z.array(text).min(1) }),
  version_set: z.strictObject({
    rule_versions: z.array(z.strictObject({ rule_id: text, version: text, content_hash: digest })).min(1),
    policy_refs: z.array(z.strictObject({ policy_id: text, version: text, profile_id: text.nullable(), content_hash: digest })).min(1),
    model_ref: z.strictObject({ model_id: knownModel, revision: text, content_hash: digest }),
  }),
  capability_manifest_hash: digest,
  model_execution: z.strictObject({ model_id: knownModel, seed, capacity_source: z.literal("scenario_contract") }),
  dual_run_tuple: z.strictObject({ input_profile_hash: digest, input_events_hash: digest, fault_schedule_hash: digest,
    schedule_trace_hash: digest, policy_version: text, model_id: knownModel, model_revision: text, seed, scheduler: text }),
  actual_load: z.strictObject({ input_range: z.strictObject({ symbols: z.array(text).min(1), from: utc, to: utc }),
    bar_count: integer, checkpoint_count: integer }),
  fault_schedule: z.array(z.strictObject({
    at: z.union([z.strictObject({ kind: z.literal("bar_index"), value: n }), z.strictObject({ kind: z.literal("cut"), value: text })]),
    target: z.union([z.strictObject({ domain: z.enum(["s", "e", "x", "transport", "store"]) }),
      z.strictObject({ domain: z.literal("bi"), chong_id: text })]),
    kind: fault,
  })).min(1),
  schedule_trace: z.array(z.strictObject({ step: n, bar_index: n, stage: text, triggered_fault: fault.nullable(), detail: z.string() })).min(1),
  h1: oracle, h2: oracle, h3: oracle, h4: oracle, six_faces: faces,
  fu14_gates: z.strictObject({ a_launcher_process_tree: pass, b_six_domains_nonempty: pass,
    c_model_order_unspecified_no_legacy: pass, d_shadow_component_only: pass }),
  model_order_unspecified_count: n, diagnostic_not_production_count: z.literal(0), input_source_unavailable_count: z.literal(0),
  input_source: z.enum(["massive-stock-tick/1", "databento-equs-mini-tick/1"]),
  verification_source_label: z.literal("校验源").nullable(),
  assumption_counts: z.strictObject({ stochastic_l1_count: n, bar_volume_derived_l0_count: n, unconstrained_capacity_l0_count: n }),
  unexecuted: z.tuple([]),
  bounded_domain_statement: text.refine(s => s.includes("仅证有界受测域")),
  ci_run_id: z.string().regex(/^[1-9][0-9]*$/),
  review_binding: z.string().regex(/^[0-9a-f]{7,40}$/),
});
type At14 = z.infer<typeof acceptedAt14>;
const jcsHash = (value: unknown) => byteSha256(Buffer.from(canonicalizeJcs(value)));

// 同 #1418 render_summary 的 PASS 投影逐字节比较，摘要不成为第二套判据。
export function at14Summary(d: At14) {
  const { session: s, build_fingerprint: b, dual_run_tuple: t, actual_load: l, assumption_counts: a } = d;
  const { symbols, from, to } = l.input_range;
  const faceNames = ["1. S 结构快照", "2. 各重 B 账", "3. E 责任", "4. 订单/成交原件", "5. 物理持仓", "6. 外效历史"];
  const faceRows = [d.six_faces.s_structure_snapshot, d.six_faces.b_chong_ledgers, d.six_faces.e_responsibility,
    d.six_faces.orders_and_fills, d.six_faces.physical_positions, d.six_faces.external_effect_journal];
  return [
    "# AT-14 回放验收报告摘要", "",
    `- schema_version: \`${d.schema_version}\``, `- content_hash: \`${d.content_hash}\``, "- verdict: `PASS`", "",
    "## 会话与构建", "",
    `- evidence_class: \`${s.evidence_class}\``, `- clock.kind: \`${s.clock_kind}\``, `- scheduler: \`${s.scheduler}\``,
    `- manifest_hash: \`${s.manifest_hash}\``, `- profile_hash: \`${s.profile_hash}\``,
    `- capability_manifest_hash: \`${d.capability_manifest_hash}\``,
    `- build: commit=\`${b.commit}\`, lockfile_hash=\`${b.lockfile_hash}\`, features=\`[${b.features.join(", ")}]\``,
    `- ci_run_id: \`${d.ci_run_id}\``, `- review_binding: \`${d.review_binding}\``, "",
    "## 模型、容量来源与双跑五元组", "",
    `- model_id: \`${d.model_execution.model_id}\` (revision=\`${d.version_set.model_ref.revision}\`)`,
    `- seed: \`${d.model_execution.seed}\``, `- capacity_source: \`${d.model_execution.capacity_source}\``,
    `- input_source: \`${d.input_source}\` (校验源标注: \`${d.verification_source_label ?? "无"}\`)`,
    `- dual_run_tuple: profile=\`${t.input_profile_hash}\`, events=\`${t.input_events_hash}\`, fault_schedule=\`${t.fault_schedule_hash}\`, schedule_trace=\`${t.schedule_trace_hash}\`, policy=\`${t.policy_version}\`, model=\`${t.model_id}@${t.model_revision}\`, seed=\`${t.seed}\`, scheduler=\`${t.scheduler}\``,
    `- actual_load: symbols=\`[${symbols.join(", ")}]\`, range=\`${from}..${to}\`, bars=${l.bar_count}, checkpoints=${l.checkpoint_count}, fault_schedule=${d.fault_schedule.length}, schedule_trace=${d.schedule_trace.length}`,
    "", "## FU-14 判据 (a)-(d)", "",
    "- (a) 进程树根 production_session: `PASS`",
    "- (b) 六域输入与产出非空: `PASS`",
    "- (c) 域外 ModelOrderUnspecified 且旧臂零调用: `PASS`",
    "- (d) 影子 bin 仅组件证据: `PASS`",
    "", "## H1-H4 Oracle", "",
    ...[d.h1, d.h2, d.h3, d.h4].map(o => `- \`${o.test_name}\`: \`${o.result}\` (${o.diff_summary})`),
    "", "## 六面摘要", "",
    ...faceRows.map((v, i) => `- ${faceNames[i]}: rows=${v.row_count}, diff=${v.diff_summary}`),
    "", "## 专项与假设分层计数", "",
    `- model_order_unspecified_count: ${d.model_order_unspecified_count}`,
    `- diagnostic_not_production_count: ${d.diagnostic_not_production_count}`,
    `- input_source_unavailable_count: ${d.input_source_unavailable_count}`,
    `- L1 stochastic_l1_count: ${a.stochastic_l1_count}`,
    `- L0 bar_volume_derived_l0_count: ${a.bar_volume_derived_l0_count}`,
    `- L0 unconstrained_capacity_l0_count: ${a.unconstrained_capacity_l0_count}`,
    "", "## 未执行项与有界受测域声明", "",
    "- unexecuted: []", `- bounded_domain_statement: ${d.bounded_domain_statement}`, "",
  ].join("\n");
}

// #1418 reject_shadow_producer 对 manifest/profile 中可回读的五个来源字段同口径。
const shadowSources = ["backtest_bin", "theta_backtest", "theta_replay", "theta_accept", "replay_compare",
  "MinimalEngine", "ThetaPiStream", "PyThetaStream", "run_theta_v0_pi"];
const sourceFields = ["provenance", "evidence_kind", "producer", "launcher", "engine"];
const notShadow = (doc: Record<string, unknown>) => sourceFields.every(key => {
  const value = doc[key];
  return typeof value !== "string" || (value !== "shadow" && value !== "component_evidence" &&
    !shadowSources.some(shadow => value.includes(shadow)));
});

function validSession(d: At14) {
  const { session, build_fingerprint: build, dual_run_tuple: tuple, version_set: versions, model_execution: model } = d;
  const { manifest_echo: manifest, profile_echo: profile } = session;
  return notShadow(manifest) && notShadow(profile) && manifest.manifest_revision === session.manifest_revision && manifest.profile === "simulation" &&
    profile.schema_revision === session.profile_revision && profile.evidence_class === "simulation" &&
    profile.input_source === d.input_source && text.safeParse(manifest.state_dir).success &&
    text.safeParse(valueAt(manifest, "/s/db")).success && text.safeParse(valueAt(manifest, "/economic/manifest")).success &&
    text.safeParse(valueAt(manifest, "/x/db")).success && text.safeParse(valueAt(manifest, "/x/profile")).success &&
    manifest.kind !== "TestOnly" && profile.kind !== "TestOnly" && profile.mode !== "diagnostic" &&
    valueAt(manifest, "/structure_source/category") !== "TestOnlyStructure" &&
    valueAt(profile, "/clock/kind") === session.clock_kind && valueAt(manifest, "/clock/kind") !== "TestOnly" &&
    valueAt(profile, "/scenario_contract/scheduler") === session.scheduler &&
    ["structure", "funding", "model", "initial_positions", "scenario_contract", "clock"]
      .every(k => profile[k] !== undefined && profile[k] !== null) &&
    session.manifest_hash === jcsHash(manifest) && session.profile_hash === jcsHash(profile) &&
    tuple.input_profile_hash === session.profile_hash && tuple.scheduler === session.scheduler &&
    tuple.fault_schedule_hash === jcsHash(d.fault_schedule) && tuple.schedule_trace_hash === jcsHash(d.schedule_trace) &&
    tuple.model_id === model.model_id && tuple.model_id === versions.model_ref.model_id &&
    tuple.model_revision === versions.model_ref.revision && tuple.seed === model.seed && model.seed === "none" &&
    versions.policy_refs.some(p => p.version === tuple.policy_version || p.policy_id + "@" + p.version === tuple.policy_version) &&
    d.assumption_counts.stochastic_l1_count === 0 && d.assumption_counts.bar_volume_derived_l0_count === 0 &&
    unique(build.features) && build.features.includes("production_session") &&
    !build.features.some(f => f === "production_session_testonly" || f === "backtest_bin") &&
    d.verification_source_label === (d.input_source === "databento-equs-mini-tick/1" ? "校验源" : null) &&
    utcBefore(d.actual_load.input_range.from, d.actual_load.input_range.to) &&
    [d.h1, d.h2, d.h3, d.h4].every((o, i) => o.test_name === AT14_LOCKS[i]);
}

export async function findAt14(s: At18Repository, F: string, b: Bindings, groupPass: Set<string>,
  reviews: ReviewRef[], diag: Diagnostics) {
  try {
    const tb07 = [...b.activeByCheck].filter(([, uses]) => [...uses.values()].some(use => use.key.slice === "TB-07"));
    const locks: RustLock[] = [];
    for (const name of AT14_LOCKS) {
      const targets = new Map<string, RustLock>();
      for (const [id] of tb07) {
        const check = b.checks.get(id);
        if (!check || check.expected_count !== 1 || check.runner !== "cargo-test" ||
            check.evidence_class !== "simulation" || !groupPass.has(check.group)) continue;
        const selection = /^(?:test:)?([\w-]+)\+([\w,-]+)\/((?:[\w]+::)*[\w]+)$/.exec(check.selector);
        if (!selection || selection[3].split("::").at(-1) !== name) continue;
        const [, target, features, selector] = selection;
        const enabled = features.split(",");
        if (!enabled.includes("production_session") || enabled.some(f => ["production_session_testonly", "backtest_bin"].includes(f)) ||
            ![`rust/tests/${target}.rs`, `rust/tests/${target}/main.rs`].includes(check.source.path)) continue;
        if (rustTest(utf8(s.blob(F, check.source.path)), name, selector)) {
          targets.set([target, selector, ...enabled.sort()].join("/"), { target, name, selector, features: enabled });
        }
      }
      if (targets.size !== 1) return [];
      locks.push(...targets.values());
    }
    const found = [...s.tree(F).keys()].filter(path => AT14.test(path));
    const candidates = found.flatMap(path => {
      const bytes = s.blob(F, path);
      const raw = parseJsonObject(bytes);
      const parsed = acceptedAt14.safeParse(raw);
      if (!parsed.success || computeContentHash(raw) !== parsed.data.content_hash) return [];
      const d = parsed.data;
      const dir = path.slice(0, -("at14-report.json".length));
      const builtAt = d.build_fingerprint.commit;
      if (!validSession(d) || !s.ancestor(builtAt, F) ||
          s.changed(builtAt, F).some(p => !p.startsWith(dir)) ||
          byteSha256(s.blob(builtAt, "rust/Cargo.lock")) !== d.build_fingerprint.lockfile_hash) return [];
      const summaryPath = dir + "summary.md";
      const entry = s.tree(F).get(summaryPath);
      if (entry?.kind !== "blob") return [];
      const summary = s.blob(F, summaryPath);
      if (utf8(summary) !== at14Summary(d)) return [];
      const matching = reviews.filter(r => r.state === "success" && r.reviewed_head.startsWith(d.review_binding) &&
        [r.merge_commit, r.reviewed_head].includes(builtAt));
      if (matching.length !== 1) return [];
      return [{ d, path, bytes, summaryPath, summary }];
    });
    if (candidates.length !== 1) return [];
    const { d, path, bytes, summaryPath, summary } = candidates[0];
    const scoped = "ticket:1304@ISSUE_1304_AT14";
    const approved = await diag.get(scoped, async () => {
      const run = await s.github.get("actions/runs/" + d.ci_run_id);
      if (!(String(run.id) === d.ci_run_id && run.path === workflows[0] &&
        run.head_sha === d.build_fingerprint.commit && object(run.repository).full_name === s.github.repo &&
        object(run.head_repository).full_name === s.github.repo && run.status === "completed" &&
        (run.event === "workflow_dispatch" || run.event === "push" || run.event === "pull_request") &&
        success({ status: run.status, conclusion: typeof run.conclusion === "string" ? run.conclusion : null }))) return false;
      const steps = at14CiSteps(utf8(s.blob(d.build_fingerprint.commit, workflows[0])), locks);
      if (locks.some(lock => !steps.some(step => step.locks.includes(lock)))) return false;
      return recordedAt14Steps(s, integer.parse(run.id), integer.parse(run.run_attempt), d.build_fingerprint.commit, steps, locks);
    });
    return approved ? [repoRef(F, path, bytes, "AT14_REPORT"), repoRef(F, summaryPath, summary, "AT14_SUMMARY")] : [];
  } catch { return []; }
}
