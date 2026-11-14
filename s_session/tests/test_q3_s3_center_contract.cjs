/* #1419/#1424：Q3 读 S3 结构写者（W_STRUCTURE_RULE_REVISION）的规则/22 轴/中枢族 typed 合同。
 * 夹具是按当前 Rust 构造规则（s_session_v3/content_structure.rs 中枢/对段、tb02a_facts catalog_axes）手工封装的最小 cut，
 * 非真实 Rust 产物；真实 S3 产物（fixtures/q3-real-s3-w-recover-revise.json）沿公开 Client 入口的验收见 test_q3_s3_real_cut.cjs，
 * 其第 1、2 条进 CI、第 3–5 条属重型验证窗口，运行命令与收据见该文件头注释。 */
"use strict";
const assert = require("node:assert/strict"),
  test = require("node:test");
const API = require("../browser/tb01c-client.js"),
  Q3 = API.Q3,
  typed = Q3.typed,
  C = typed.Center;
const W = "s2-axis-quantifiers+new-bi/2+segment-second/2+segment-turn/1+second-seq-scan-budget/2+center-seed/1+center-pair/1+raw-initialization-w/1",
  BASE = W.slice(0, -"+raw-initialization-w/1".length),
  V3_BASE = "s2-axis-quantifiers+new-bi/2+segment-second/2+segment-turn/1+second-seq-scan-budget/2+segment-first-own/1+center-seed/1+center-pair/1";
const copy = (v) => JSON.parse(JSON.stringify(v));
const K = { generation: "1", input_frontier: "10", receipt_id: "r1", received_at: "t1", semantic_commit_ns: null };
const U = ["segment:1:0", "segment:1:3", "segment:1:6", "segment:1:9"],
  RANGE = [["UP", "10", "20"], ["DOWN", "12", "18"], ["UP", "11", "22"], ["DOWN", "1", "5"]],
  CID = "center:1:0";
const unit = (k) => ({ unit_id: U[k], unit_object_id: "obj3-seg" + k, direction: RANGE[k][0], lo: RANGE[k][1], hi: RANGE[k][2] });
const wrap = (tuple, slot, data) => ({ schema_revision: tuple[0], semantic_version: tuple[1], policy_version: tuple[2], view_role: tuple[3], object_generation: "1", slot, data });
const e = (slot, data) => wrap(C.CENTER_TUPLE, slot, data),
  f = (slot, data) => wrap(C.PAIR_TUPLE, slot, data);
const role = (value, contributors, frozen) => ({ value, contributors, same_price_witness: contributors.length >= 2 ? contributors : [], frozen, null_reason: null });
function centerCut() {
  // 四个完成段：seed U0..U2 成立（ZD=12/ZG=18），U3 严格在下 ⟹ 结算、break_up=false，U3 为右侧待定连接段。
  const segments = U.slice(0, 4).map((id, k) => ({
    kind: "CC-013.segment",
    object_id: "obj3-seg" + k,
    payload: { data: { entity_id: id, result: "CASE_ONE", construction: { start_stroke: String(k), stroke_indices: [String(k)], direction: RANGE[k][0] },
      stroke_refs: [{ stroke_index: String(k), start_price: RANGE[k][0] === "UP" ? RANGE[k][1] : RANGE[k][2], end_price: RANGE[k][0] === "UP" ? RANGE[k][2] : RANGE[k][1] }] } },
  }));
  const attempt = { entity_id: "seed_attempt:1:0", units: [0, 1, 2].map(unit), vector: { completed: true, consecutive: true, same_level: true, alternating: true, strict: true },
    ZD: { value: "12", contributors: [U[1]], same_price_witness: [] }, ZG: { value: "18", contributors: [U[1]], same_price_witness: [] },
    core_order: "ZD<ZG", result: "FORMED", exclusion_reason: null, center_id: CID, known_at: K };
  const center = { entity_id: CID, entity_revision: "1", seed_attempt_id: "seed_attempt:1:0", seed_units: U.slice(0, 3), zn_direction: "UP", members: U.slice(0, 3),
    zn_members: [U[0], U[2]], status: "SETTLED", settled: true, break_unit: U[3], break_up: false, break_up_defined: true,
    resume_anchor: { after_unit_id: U[2], offset: "2" }, next_tested_unit: null, roles_id: "roles:" + CID, formed_known_at: K, settled_known_at: K };
  const roles = { entity_id: "roles:" + CID, entity_revision: "1", center_id: CID, previous: null, known_at: K,
    roles: { CORE: { ZD: role("12", [U[1]], true), ZG: role("18", [U[1]], true) }, OUTER: { DD: role("10", [U[0]], false), GG: role("22", [U[2]], false) },
      INNER_EXTREMA: { D: role("11", [U[2]], false), G: role("20", [U[0]], false) } } };
  const assign = (k, status, extra) => ({ entity_id: "assign:" + U[k], unit: unit(k), status, center_id: null, left_center_id: null, right_center_id: null,
    right_pending: false, reason: null, seed_from_self: k === 0 ? "FORMED" : "NOT_EVALUATED", known_at: K, ...extra });
  const ucp = { entity_id: "ucp:1:0:1:9", center_id: CID, unit: unit(3), core: { ZD: "12", ZG: "18" }, position: "STRICT_BELOW", closed_overlap: false,
    strict_leave: true, leave_side: "DOWN", construction_role: "BREAK_UNIT", destruction: "NOT_EVALUATED_DEFERRED_1434", center_revision: "1", known_at: K };
  const rel = (kind, s, r, t, v, w) => ({ kind, object_id: "obj3-rel-" + [s, r, t].join("|"), payload: (kind.includes("pair") ? f : e)([s, r, t], { source_id: s, relation_kind: r, target_id: t, version: v, witness_object_id: w }) });
  const records = [
    ...segments,
    { kind: C.CENTER_KINDS[0], object_id: "obj3-attempt", payload: e(attempt.entity_id, attempt) },
    { kind: C.CENTER_KINDS[1], object_id: "obj3-center", payload: e(CID, center) },
    { kind: C.CENTER_KINDS[2], object_id: "obj3-roles", payload: e(roles.entity_id, roles) },
    ...[0, 1, 2].map((k) => ({ kind: C.CENTER_KINDS[3], object_id: "obj3-assign" + k, payload: e("assign:" + U[k], assign(k, "CENTER_MEMBER", { center_id: CID })) })),
    { kind: C.CENTER_KINDS[3], object_id: "obj3-assign3", payload: e("assign:" + U[3], assign(3, "CONNECTOR", { left_center_id: CID, right_pending: true })) },
    rel(C.CENTER_KINDS[4], "seed_attempt:1:0", "attempted_from", U[0], "1", "obj3-attempt"),
    ...[0, 1, 2].map((k) => rel(C.CENTER_KINDS[4], U[k], "member_of", CID, "1", "obj3-center")),
    rel(C.CENTER_KINDS[4], U[3], "connects_left", CID, "1", "obj3-assign3"),
    { kind: C.CENTER_KINDS[5], object_id: "obj3-cchange", payload: e(["1", CID, "formed"], { entity_id: CID, change: "formed", before: null, after: center, known_at: K, object_id: "obj3-center" }) },
    { kind: C.CENTER_KINDS[6], object_id: "obj3-cver", payload: e("TB-02-E", { input_frontier: "10", known_at: K, waiting_reasons: [],
      scan_cursor: { state: "SEEKING_SEED", center_id: null, seed_start_unit_id: null, awaiting_unit_id: null, awaiting_after_unit_id: U[3], awaiting_offset: "3" },
      delivered_scope: "l0_strict_seed_zn_roles_c_resume_assignment", deferred_scope: C.TB02E_DEFERRED }) },
    { kind: C.PAIR_KINDS[0], object_id: "obj3-ucp", payload: f(ucp.entity_id, ucp) },
    rel(C.PAIR_KINDS[2], ucp.entity_id, "position_of", U[3], "1", "obj3-ucp"),
    rel(C.PAIR_KINDS[2], ucp.entity_id, "position_against", CID, "1", "obj3-ucp"),
    { kind: C.PAIR_KINDS[4], object_id: "obj3-pver", payload: f("TB-02-F", { input_frontier: "10", known_at: K, pair_count: "0", pending_pairs: "0", waiting_reasons: [],
      delivered_scope: "l0_adjacent_pair_five_leaf_zn_outer_and_unit_core_position", deferred_scope: C.TB02F_DEFERRED }) },
  ];
  for (const r of records) Object.assign(r, { first_known_generation: "1", withdrawn_generation: null });
  return records;
}
// 两中枢：A=U0..U2（结算于 U3），B=U4..U6（EXTENDING）；U3 为 A→B 连接段；对 A→B 叶 DOWN_NEWBIRTH（B.GG=5<A.DD=10）。
function twoCenterCut() {
  U.push("segment:1:12", "segment:1:15", "segment:1:18");
  RANGE.push(["UP", "0", "4"], ["DOWN", "1", "3"], ["UP", "0", "5"]);
  try {
    const records = centerCut().filter((r) => ![C.CENTER_KINDS[6], C.PAIR_KINDS[4]].includes(r.kind));
    const BID = "center:1:12", A = { ZD: "12", ZG: "18", DD: "10", GG: "22" }, B = { ZD: "1", ZG: "3", DD: "0", GG: "5" };
    const connector = records.find((r) => r.object_id === "obj3-assign3").payload.data;
    Object.assign(connector, { right_center_id: BID, right_pending: false });
    const segs = [4, 5, 6].map((k) => ({ kind: "CC-013.segment", object_id: "obj3-seg" + k,
      payload: { data: { entity_id: U[k], result: "CASE_ONE", construction: { start_stroke: String(k), stroke_indices: [String(k)], direction: RANGE[k][0] },
        stroke_refs: [{ stroke_index: String(k), start_price: RANGE[k][0] === "UP" ? RANGE[k][1] : RANGE[k][2], end_price: RANGE[k][0] === "UP" ? RANGE[k][2] : RANGE[k][1] }] } } }));
    const attempt = { entity_id: "seed_attempt:1:12", units: [4, 5, 6].map(unit), vector: { completed: true, consecutive: true, same_level: true, alternating: true, strict: true },
      ZD: { value: "1", contributors: [U[5]], same_price_witness: [] }, ZG: { value: "3", contributors: [U[5]], same_price_witness: [] },
      core_order: "ZD<ZG", result: "FORMED", exclusion_reason: null, center_id: BID, known_at: K };
    const center = { entity_id: BID, entity_revision: "1", seed_attempt_id: attempt.entity_id, seed_units: U.slice(4, 7), zn_direction: "UP", members: U.slice(4, 7),
      zn_members: [U[4], U[6]], status: "EXTENDING", settled: false, break_unit: null, break_up: false, break_up_defined: false,
      resume_anchor: null, next_tested_unit: null, roles_id: "roles:" + BID, formed_known_at: K, settled_known_at: null };
    const roles = { entity_id: "roles:" + BID, entity_revision: "1", center_id: BID, previous: null, known_at: K,
      roles: { CORE: { ZD: role("1", [U[5]], true), ZG: role("3", [U[5]], true) }, OUTER: { DD: role("0", [U[4], U[6]], false), GG: role("5", [U[6]], false) },
        INNER_EXTREMA: { D: role("0", [U[4], U[6]], false), G: role("4", [U[4]], false) } } };
    const ends = ["DD", "ZD", "ZG", "GG"], cmp = (x, y) => (BigInt(x) < BigInt(y) ? "<" : x === y ? "=" : ">"), matrix = {};
    for (const x of ends) for (const y of ends) matrix[`B.${x}?A.${y}`] = cmp(B[x], A[y]);
    const pair = { entity_id: "pair:1:0:1:12", entity_revision: "1", a_center_id: CID, a_revision: "1", b_center_id: BID, b_revision: "1", connector_units: [U[3]],
      status: "EVALUATED", leaf: "DOWN_NEWBIRTH", direction: "DOWN", provisional: true, inputs: { A, B }, matrix,
      witnesses: { core_tangent: false, outer_touch: false, outer_containment: "NONE", core_containment: "NONE" },
      realization: { upper_center: "NOT_CONSTRUCTED_DEFERRED_1429", trend: "NOT_ASSERTED_DEFERRED_1426" }, null_reason: null, previous: null, formed_known_at: K, known_at: K };
    const rel = (kind, s, r, tt, v, w) => ({ kind, object_id: "obj3-rel-" + [s, r, tt].join("|"), payload: (kind.includes("pair") ? f : e)([s, r, tt], { source_id: s, relation_kind: r, target_id: tt, version: v, witness_object_id: w }) });
    const assign = (k) => ({ kind: C.CENTER_KINDS[3], object_id: "obj3-assign" + k, payload: e("assign:" + U[k], { entity_id: "assign:" + U[k], unit: unit(k), status: "CENTER_MEMBER",
      center_id: BID, left_center_id: null, right_center_id: null, right_pending: false, reason: null, seed_from_self: k === 4 ? "FORMED" : "NOT_EVALUATED", known_at: K }) });
    const more = [
      ...segs,
      { kind: C.CENTER_KINDS[0], object_id: "obj3-attemptB", payload: e(attempt.entity_id, attempt) },
      { kind: C.CENTER_KINDS[1], object_id: "obj3-centerB", payload: e(BID, center) },
      { kind: C.CENTER_KINDS[2], object_id: "obj3-rolesB", payload: e(roles.entity_id, roles) },
      ...[4, 5, 6].map(assign),
      rel(C.CENTER_KINDS[4], attempt.entity_id, "attempted_from", U[4], "1", "obj3-attemptB"),
      ...[4, 5, 6].map((k) => rel(C.CENTER_KINDS[4], U[k], "member_of", BID, "1", "obj3-centerB")),
      rel(C.CENTER_KINDS[4], U[3], "connects_right", BID, "1", "obj3-assign3"),
      { kind: C.CENTER_KINDS[5], object_id: "obj3-cchangeB", payload: e(["1", BID, "formed"], { entity_id: BID, change: "formed", before: null, after: center, known_at: K, object_id: "obj3-centerB" }) },
      { kind: C.CENTER_KINDS[6], object_id: "obj3-cver", payload: e("TB-02-E", { input_frontier: "10", known_at: K, waiting_reasons: [],
        scan_cursor: { state: "EXTENDING", center_id: BID, seed_start_unit_id: null, awaiting_unit_id: null, awaiting_after_unit_id: U[6], awaiting_offset: "1" },
        delivered_scope: "l0_strict_seed_zn_roles_c_resume_assignment", deferred_scope: C.TB02E_DEFERRED }) },
      { kind: C.PAIR_KINDS[1], object_id: "obj3-pair", payload: f(pair.entity_id, pair) },
      rel(C.PAIR_KINDS[2], pair.entity_id, "pair_from", CID, "1", "obj3-pair"),
      rel(C.PAIR_KINDS[2], pair.entity_id, "pair_to", BID, "1", "obj3-pair"),
      { kind: C.PAIR_KINDS[3], object_id: "obj3-pchange", payload: f(["1", pair.entity_id, "formed"], { entity_id: pair.entity_id, change: "formed", before: null, after: pair, known_at: K, object_id: "obj3-pair" }) },
      { kind: C.PAIR_KINDS[4], object_id: "obj3-pver", payload: f("TB-02-F", { input_frontier: "10", known_at: K, pair_count: "1", pending_pairs: "0", waiting_reasons: [],
        delivered_scope: "l0_adjacent_pair_five_leaf_zn_outer_and_unit_core_position", deferred_scope: C.TB02F_DEFERRED }) },
    ];
    for (const r of more) Object.assign(r, { first_known_generation: "1", withdrawn_generation: null });
    return [...records, ...more];
  } finally {
    U.length = 4;
    RANGE.length = 4;
  }
}
const AXES22 = ["CC-001", "CC-002", "CC-003", "CC-004", "CC-005", "CC-006", "CC-007", "CC-008", "CC-009", "CC-010", "CC-011", "CC-012", "CC-013", "CC-014",
  "CC-016", "CC-017", "CC-018", "CC-020", "CC-022", "CC-054", "CC-055", "CC-056"];
function axes22(records) {
  const ids = (kinds) => records.filter((r) => kinds.includes(r.kind)).map((r) => r.object_id);
  const out = {};
  for (const cid of AXES22) {
    const seg = ["CC-011", "CC-012", "CC-013", "CC-014"].includes(cid),
      center = ["CC-016", "CC-017", "CC-022"].includes(cid),
      pair = ["CC-018", "CC-020"].includes(cid);
    const evidence = { scope: seg ? "TB-02-D" : center ? "TB-02-E" : pair ? "TB-02-F" : "TB-02-A", object_ids: [], waiting_reasons: [] };
    if (cid === "CC-013" || cid === "CC-014") evidence.object_ids = ids(["CC-013.segment"]);
    if (cid === "CC-016") evidence.object_ids = ids(C.CENTER_KINDS.slice(0, 2));
    if (cid === "CC-017") evidence.object_ids = ids([C.CENTER_KINDS[2]]);
    if (cid === "CC-022") evidence.object_ids = ids([C.CENTER_KINDS[3]]);
    if (cid === "CC-018") evidence.object_ids = ids([C.PAIR_KINDS[0]]);
    if (cid === "CC-020") evidence.object_ids = ids([C.PAIR_KINDS[1]]);
    if (seg) Object.assign(evidence, { delivered_subobligations: ["finite_complete_prefix_strict_second", "independent_stroke_and_segment_break_facts"],
      deferred_subobligations: ["general_equal_identity", "general_scan_continuation", "global_G006_bridge"] });
    if (center) Object.assign(evidence, { delivered_subobligations: C.TB02E_DELIVERED, deferred_subobligations: C.TB02E_DEFERRED });
    if (pair) Object.assign(evidence, { delivered_subobligations: C.TB02F_DELIVERED, deferred_subobligations: C.TB02F_DEFERRED });
    if (cid === "CC-056") Object.assign(evidence, { raw_revisions: [], withdrawals: [], replaces: [] });
    const notImpl = ["CC-012", "CC-013", "CC-014", "CC-016", "CC-017", "CC-018", "CC-020", "CC-022"].includes(cid);
    out[cid] = { impl_status: notImpl ? "not_implemented" : "implemented", proof_status: "not_proved",
      run_status: cid === "CC-056" ? "not_run" : evidence.object_ids.length ? "run" : "not_run", evidence };
  }
  return out;
}

test("S3 规则串：冻结 W1 显式映射 W1 基串，现役 V3 基串分离登记，未授权组合一律拒", () => {
  assert.equal(typed.W1_BASE_STRUCTURE_RULE, BASE);
  assert.equal(typed.V3_STRUCTURE_RULE, V3_BASE);
  assert.equal(typed.W_STRUCTURE_RULE, W);
  assert.equal(typed.baseRule(W), BASE);
  assert.deepEqual(typed.RULE_CONTRACTS[BASE], ["s-new-bi/2", "s-segment/5", "established_direction_with_extreme_root_sets"]);
  assert.deepEqual(typed.RULE_CONTRACTS[V3_BASE], ["s-new-bi/2", "s-segment/5", "established_direction_with_extreme_root_sets"]);
  assert(typed.CENTER_RULES.has(BASE));
  assert(typed.CENTER_RULES.has(V3_BASE));
  const bad = [
    BASE, // 剥去 W 后缀：库里无此 cut 规则
    V3_BASE, // 裸现役 V3 基串从未写库
    V3_BASE + "+raw-initialization-w/1", // 冻结 W1 混入 +segment-first-own/1 一律拒收
    W + "+raw-initialization-w/1", // 重复后缀
    BASE + "+raw-initialization-w/2", // W 版本变体
    V3_BASE + "+raw-initialization-w/2", // W2 缺布局后缀
    "s2-axis-quantifiers+new-bi/2+segment-second/2+center-seed/1+center-pair/1+raw-initialization-w/1", // 旧 CF22 未经段组件
    "s2-axis-quantifiers+new-bi/2+segment-second/2+center-seed/1+center-pair/1",
    W.replace("center-seed/1+center-pair/1", "center-pair/1+center-seed/1"), // 错序
    W.replace("+segment-turn/1", ""), // 缺组件
    W.replace("+center-pair/1", ""),
    "s2-axis-quantifiers+new-bi/2+segment-second/2+segment-turn/1+second-seq-scan-budget/2+raw-initialization-w/1",
  ];
  for (const rule of bad) assert.throws(() => typed.baseRule(rule), /未获准的完整规则组合/, rule);
});

test("22 轴目录：CF22/W 规则选 22 轴，scope 与子义务按 E/F 片，中枢轴绑定实际对象", async () => {
  const records = centerCut(),
    axes = axes22(records);
  await Q3.axesValidate(axes);
  const reject = async (mutate, pattern) => {
    const a = copy(axes);
    mutate(a);
    await assert.rejects(() => Q3.axesValidate(a), pattern);
  };
  await reject((a) => delete a["CC-020"], /逐cut目录轴 完整字段不符/);
  await reject((a) => (a["CC-016"].evidence.scope = "TB-02-A"), /完整字段不符|轴范围错误/);
  await reject((a) => (a["CC-018"].evidence.scope = "TB-02-E"), /中枢子义务范围不符|轴范围错误/);
  await reject((a) => (a["CC-017"].evidence.deferred_subobligations = C.TB02F_DEFERRED), /中枢子义务范围不符/);
  await reject((a) => (a["CC-020"].impl_status = "implemented"), /有限交付冒称全轴完成/);
  await reject((a) => (a["CC-013"].evidence.scope = "TB-02-W"), /轴范围错误|完整字段不符/);
  // 22 轴之外再多一条段/中枢轴都不是合法轴表。
  await reject((a) => (a["CC-015"] = copy(a["CC-016"])), /逐cut目录轴 完整字段不符/);
  // 对象绑定：轴证据须恰为实际中枢族对象（含无中枢族对象时为空）。
  const bound = copy(axes);
  bound["CC-016"].evidence.object_ids.pop();
  assert.throws(() => C.validateCenterFamilyCut(records, bound), /TB02E_AXIS_BINDING/);
  const segOnly = records.filter((r) => r.kind === "CC-013.segment"),
    empty = axes22(segOnly);
  C.validateCenterFamilyCut(segOnly, empty);
  empty["CC-022"].evidence.object_ids = ["obj3-seg0"];
  assert.throws(() => C.validateCenterFamilyCut(segOnly, empty), /TB02E_AXIS_BINDING/);
});

test("中枢族 typed：每种对象按 s-center/1、s-center-pair/1 合同校验，同 cut 链接闭合", () => {
  const records = centerCut();
  for (const r of records)
    if (C.CENTER_KINDS.includes(r.kind)) C.validateCenterPayload(r.kind, r.payload);
    else if (C.PAIR_KINDS.includes(r.kind)) C.validatePairPayload(r.kind, r.payload);
  C.validateCenterFamilyCut(records, axes22(records));
  C.validatePairHistory(records);
  const reject = (mutate, pattern) => {
    const rs = copy(records);
    mutate(rs);
    assert.throws(() => {
      for (const r of rs)
        if (C.CENTER_KINDS.includes(r.kind)) C.validateCenterPayload(r.kind, r.payload);
        else if (C.PAIR_KINDS.includes(r.kind)) C.validatePairPayload(r.kind, r.payload);
      C.validateCenterFamilyCut(rs, axes22(rs));
    }, pattern);
  };
  const find = (rs, kind, k = 0) => rs.filter((r) => r.kind === kind)[k].payload;
  reject((rs) => (find(rs, C.CENTER_KINDS[1]).schema_revision = "s-center/2"), /TB02E_VERSION/);
  reject((rs) => (find(rs, C.PAIR_KINDS[0]).policy_version = "x"), /TB02F_VERSION/);
  reject((rs) => (find(rs, C.CENTER_KINDS[2]).data.roles.OUTER.DD.value = "11"), /TB02E_ROLE_VALUE|TB02E_CONTRIBUTORS/);
  reject((rs) => (find(rs, C.CENTER_KINDS[0]).data.ZD.value = "11"), /TB02E_CORE_VALUE/);
  reject((rs) => (find(rs, C.PAIR_KINDS[0]).data.position = "LOW_TOUCH"), /TB02F_POSITION/);
  reject((rs) => (find(rs, C.PAIR_KINDS[0]).data.construction_role = "EXTENSION_MEMBER"), /TB02F_ROLE/);
  reject((rs) => rs.splice(rs.findIndex((r) => r.payload.data?.relation_kind === "member_of"), 1), /TB02E_MEMBER_EDGE_COUNT/);
  reject((rs) => rs.splice(rs.findIndex((r) => r.payload.data?.relation_kind === "position_of"), 1), /TB02F_EDGE/);
  reject((rs) => rs.splice(rs.findIndex((r) => r.kind === C.PAIR_KINDS[4]), 1), /TB02F_VERSION_COUNT/);
  reject((rs) => (find(rs, C.CENTER_KINDS[6]).data.scan_cursor.awaiting_offset = "2"), /TB02E_SCAN_CURSOR/);
  reject((rs) => (find(rs, C.CENTER_KINDS[3], 3).data.status = "CENTER_MEMBER"), /TB02E_ASSIGNMENT/);
  reject((rs) => (find(rs, C.CENTER_KINDS[1]).slot = "center:1:3"), /TB02E_SLOT/);
  // 单元区间须是同 cut CC-013 成员笔极值。
  reject((rs) => (rs[0].payload.data.stroke_refs[0].end_price = "21"), /TB02E_UNIT_SOURCE/);
  reject((rs) => rs.push({ kind: "CC-016.center_shadow", object_id: "x", payload: {} }), /TB02E_CANDIDATE_KIND/);
});

test("公开入口：中枢族记录经 typed 路由与规则绑定，旧规则 cut 混入中枢族/W 对象拒", async () => {
  const records = centerCut(),
    attempt = records.find((r) => r.kind === C.CENTER_KINDS[0]);
  const ref = { identity_key: "k0", payload_hash: "0".repeat(64), receipt_id: "r1", event_id: "e1", input_revision: "1", revision: "1", seq: "0", source_coord: "0" };
  const record = { object_id: "obj3-x", object_revision: "1", kind: attempt.kind, batch_id: "b1", fact_key: API.canonical([attempt.kind, attempt.payload.slot]),
    payload: attempt.payload, input_refs: [ref], source_coords: ["0"], first_known_generation: "1", first_known_cut: "cut-1", published_generation: "1",
    withdrawn_generation: null, withdrawal_reason: null, superseded_by: null, lifecycle: "active" };
  await typed.validateTyped(Q3.V.of(record));
  const bad = copy(record);
  bad.payload.data.core_order = "ZD=ZG";
  await assert.rejects(() => typed.validateTyped(Q3.V.of(bad)), /TB02E_CORE_ORDER/);
  const wrongSlot = copy(record);
  wrongSlot.fact_key = API.canonical([attempt.kind, "seed_attempt:1:3"]);
  await assert.rejects(() => typed.validateTyped(Q3.V.of(wrongSlot)), /事实语义槽未绑定 payload/);
  // 规则绑定先于内容身份：W 规则下进入身份比对（身份不符），旧规则下按 RULE_MIX 拒。
  const fixed = (rule) => ({ rule_revision: rule, profile_id: "ohlc_integer_tb02a_v1", protocol: "s-session/3" });
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(record), fixed(W)), /对象内容身份不符/);
  // S3 结构规则只属 s-session/3：v2 协议 cut 携 W 串按未获准组合拒（v2 写者已退役）。
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(record), { ...fixed(W), protocol: "s-session/2" }), /未获准的完整规则组合/);
  const old = "s2-axis-quantifiers+new-bi/2+segment-second/2+segment-turn/1+second-seq-scan-budget/2";
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(record), fixed(old)), /TB02E_RULE_MIX/);
  const pair = records.find((r) => r.kind === C.PAIR_KINDS[0]);
  const pairRecord = { ...copy(record), kind: pair.kind, payload: pair.payload, fact_key: API.canonical([pair.kind, pair.payload.slot]) };
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(pairRecord), fixed(old)), /TB02F_RULE_MIX/);
  // W 对象只准出现在 W 后继串 cut。
  const wRecord = { ...copy(record), kind: "CC-004.initialization", payload: { initialization_policy_revision: "raw-initialization-w/1", direction_state: "Undetermined", first_raw_pair: null },
    fact_key: API.canonical(["CC-004.initialization", "W"]) };
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(wRecord), fixed(old)), /旧规则cut混入W对象/);
  await assert.rejects(() => Q3.validateTB02Identity(Q3.V.of(wRecord), fixed(W)), /对象内容身份不符/);
});

test("相邻中枢对：五叶/方向/矩阵/证据/连接段/修订/边/版本计数闭合，出生事件绑定发布代", () => {
  const records = twoCenterCut();
  const run = (rs) => {
    for (const r of rs)
      if (C.CENTER_KINDS.includes(r.kind)) C.validateCenterPayload(r.kind, r.payload);
      else if (C.PAIR_KINDS.includes(r.kind)) { C.validatePairPayload(r.kind, r.payload); if ([C.PAIR_KINDS[1], C.PAIR_KINDS[3]].includes(r.kind)) C.validatePairPublication(r, r.first_known_generation); }
    C.validateCenterFamilyCut(rs, axes22(rs));
    C.validatePairHistory(rs);
  };
  run(records);
  const pairOf = (rs) => rs.find((r) => r.kind === C.PAIR_KINDS[1]).payload.data;
  const reject = (mutate, pattern) => { const rs = copy(records); mutate(rs); assert.throws(() => run(rs), pattern); };
  reject((rs) => (pairOf(rs).leaf = "DOWN_EXPANSION"), /TB02F_LEAF/);
  reject((rs) => (pairOf(rs).direction = "UP"), /TB02F_DIRECTION/);
  reject((rs) => (pairOf(rs).matrix["B.GG?A.DD"] = ">"), /TB02F_MATRIX/);
  reject((rs) => (pairOf(rs).provisional = false), /TB02F_PROVISIONAL|TB02F_CHANGE/);
  reject((rs) => (pairOf(rs).realization.trend = "ASSERTED"), /TB02F_REALIZATION/);
  reject((rs) => (pairOf(rs).inputs.B.GG = "6"), /TB02F_/);
  reject((rs) => (pairOf(rs).known_at = { ...K, generation: "2" }), /TB02F_PUBLICATION|TB02F_CHANGE/);
  reject((rs) => rs.splice(rs.findIndex((r) => r.kind === C.PAIR_KINDS[3]), 1), /TB02F_CHANGE/);
  reject((rs) => (rs.find((r) => r.kind === C.PAIR_KINDS[4]).payload.data.pair_count = "0"), /TB02F_VERSION_COUNT/);
  reject((rs) => (rs.find((r) => r.object_id === "obj3-assign3").payload.data.right_center_id = null), /TB02E_/);
  // 撤回：后一代中枢对撤回须有 withdrawn 事件，且前件为真实活动对象。
  const withdrawn = copy(records).filter((r) => [C.PAIR_KINDS[1], C.PAIR_KINDS[3]].includes(r.kind));
  withdrawn.find((r) => r.kind === C.PAIR_KINDS[1]).withdrawn_generation = "2";
  assert.throws(() => C.validatePairHistory(withdrawn), /TB02F_CHANGE/);
  const pairData = pairOf(records), K2 = { ...K, generation: "2" };
  withdrawn.push({ kind: C.PAIR_KINDS[3], object_id: "obj3-pchange2", first_known_generation: "2", withdrawn_generation: null,
    payload: f(["2", pairData.entity_id, "withdrawn"], { entity_id: pairData.entity_id, change: "withdrawn", before: pairData, after: null, known_at: K2, object_id: null }) });
  C.validatePairHistory(withdrawn);
});

test("通用整数遍历：中枢/中枢对 payload.slot 是逻辑身份（取 q3-center.js 的 schema），换成非逻辑槽 schema 即按整数拒", async () => {
  const records = twoCenterCut(),
    center = records.filter((r) => C.CENTER_KINDS.includes(r.kind)),
    pair = records.filter((r) => C.PAIR_KINDS.includes(r.kind));
  assert(center.length && pair.length);
  // 正控：中枢族与中枢对各 kind 的 slot（"TB-02-E"/"TB-02-F"、实体 id、三元组）经整数遍历放行。
  for (const r of [...center, ...pair]) await Q3.integerWalk(Q3.V.of({ kind: r.kind, payload: r.payload }));
  // 负控：同一 payload 只改 schema_revision（不在逻辑槽表），slot 回到整数口径即拒。
  for (const r of [center.find((x) => x.kind === C.CENTER_KINDS[6]), pair.find((x) => x.kind === C.PAIR_KINDS[4])]) {
    const bad = copy(r.payload);
    bad.schema_revision = "s-unknown/1";
    await assert.rejects(() => Q3.integerWalk(Q3.V.of({ kind: r.kind, payload: bad })), /精确整数必须是规范文本/);
  }
  // 见证等非逻辑槽对象的整数 slot 仍按整数核对。
  await assert.rejects(() => Q3.integerWalk(Q3.V.of({ witness_id: "w", slot: "TB-02-E" })), /精确整数必须是规范文本/);
});

// #1419 P2（issuecomment-6504760769）W/2 完整发布串的公共读者合同。下列夹具是手工最小单元，只证规则选择与逐原件替代判据；
// 真实 W/2 写者产物的公开 Client 验收待 #1419 owner 交付后另立具名测试。
// #1419 31P：现役 W/2 串改为 bounded-layout/2；失败候选的 W2+bounded-layout/1 完整串仍按 W2＋Bounded1 归档读。
const W2 = V3_BASE + "+raw-initialization-w/2+bounded-layout/1";
const W2B2 = V3_BASE + "+raw-initialization-w/2+bounded-layout/2";
test("W/2 规则串与 Rust 写者字面量逐字符对齐：冻结 W1 与现役 W2/归档 W2+/1 精确分派，混入/漏掉 segment-first-own/1 一律拒", () => {
  const rust = require("node:fs").readFileSync(require("node:path").join(__dirname, "../../rust/src/bin/s_structure_session.rs"), "utf8");
  const literal = (name) => {
    const m = rust.match(new RegExp(`^const ${name}: &str = "([^"]+)";$`, "m"));
    assert(m, name);
    return m[1];
  };
  assert.equal(typed.V3_STRUCTURE_RULE, literal("V3_STRUCTURE_RULE_REVISION"));
  assert.equal(typed.W_STRUCTURE_RULE, literal("W1_STRUCTURE_RULE_REVISION"));
  assert.equal(typed.W2_DOCTRINE, literal("W2_DOCTRINE_RULE_REVISION"));
  assert.equal(typed.W2_ARCHIVED_RULE, literal("W2_BOUNDED1_RULE_REVISION"));
  assert.equal(typed.W2_PUBLICATION_RULE, literal("W_STRUCTURE_RULE_REVISION"));
  assert.equal(typed.W2_PUBLICATION_RULE, W2B2);
  assert.equal(typed.W2_ARCHIVED_RULE, W2);
  assert.deepEqual(typed.resolveRule(W2B2), { base: V3_BASE, w: "raw-initialization-w/2", layout: "bounded-layout/2" });
  assert.deepEqual(typed.resolveRule(W2), { base: V3_BASE, w: "raw-initialization-w/2", layout: "bounded-layout/1" });
  assert.equal(typed.protocolRule(W2B2, "s-session/3"), V3_BASE);
  assert.equal(typed.protocolRule(W2, "s-session/3"), V3_BASE);
  assert.deepEqual(typed.resolveRule(W), { base: BASE, w: "raw-initialization-w/1", layout: "layout/1" });
  assert.deepEqual(typed.resolveRule(W + "+bounded-layout/1"), { base: BASE, w: "raw-initialization-w/1", layout: "bounded-layout/1" });
  assert.equal(typed.protocolRule(W, "s-session/3"), BASE);
  assert.deepEqual(typed.resolveRule(BASE.replace(/\+center-seed.*$/, "") + "+bounded-layout/1").w, null);
  assert.deepEqual(typed.resolveRule(V3_BASE.replace(/\+center-seed.*$/, "") + "+bounded-layout/1").w, null);
  const bad = [
    BASE, // 裸冻结 W1 基串
    V3_BASE, // 裸现役 V3 基串
    V3_BASE + "+raw-initialization-w/1", // 冻结 W1 混入 +segment-first-own/1
    V3_BASE + "+raw-initialization-w/1+bounded-layout/1", // 冻结 W1 混入 +segment-first-own/1 并挂布局
    BASE + "+raw-initialization-w/2+bounded-layout/2", // W2 漏掉 +segment-first-own/1（现役布局）
    BASE + "+raw-initialization-w/2+bounded-layout/1", // W2 漏掉 +segment-first-own/1（归档布局）
    V3_BASE + "+raw-initialization-w/2", // W/2 无布局组件
    BASE + "+raw-initialization-w/2", // 旧基串 W/2 无布局组件
    V3_BASE + "+bounded-layout/1+raw-initialization-w/2", // 布局组件错位
    W2 + "+bounded-layout/1", // 重复布局
    W2 + "+raw-initialization-w/2", // 重复 W
    V3_BASE + "+raw-initialization-w/1+raw-initialization-w/2+bounded-layout/1", // 混版本
    V3_BASE + "+raw-initialization-w/2+raw-initialization-w/1+bounded-layout/1",
    V3_BASE + "+raw-initialization-w/3+bounded-layout/1", // 未知 W
    V3_BASE + "+raw-initialization-w/2+bounded-layout/3", // 未知布局
    W2B2 + "+bounded-layout/2",
    W2 + "+bounded-layout/2",
    V3_BASE + "+raw-initialization-w/2+bounded-layout/2+bounded-layout/1",
    V3_BASE + "+bounded-layout/2+raw-initialization-w/2", // 新布局错位
    W + "+bounded-layout/2",
    V3_BASE + "+bounded-layout/2",
    BASE + "+bounded-layout/2",
    W2B2.replace("center-seed/1+center-pair/1", "center-pair/1+center-seed/1"),
    "s2-axis-quantifiers+new-bi/2+raw-initialization-w/2+bounded-layout/2",
    W2.replace("center-seed/1+center-pair/1", "center-pair/1+center-seed/1"), // 教义组件错序
    W2.replace("+segment-turn/1", ""),
    W2B2.replace("+segment-first-own/1", ""), // 显式漏掉 segment-first-own/1
    "s2-axis-quantifiers+new-bi/2+raw-initialization-w/2+bounded-layout/1", // W/2 接到非 CF22 基规则
  ];
  for (const rule of bad) {
    assert.throws(() => typed.resolveRule(rule), /cut规则修订未声明/, rule);
    assert.throws(() => typed.protocolRule(rule, "s-session/3"), /cut规则修订未声明/, rule);
  }
  // 中枢族基规则只属 s-session/3。
  assert.throws(() => typed.protocolRule(W2, "s-session/2"), /未获准的完整规则组合/);
  assert.throws(() => typed.protocolRule(W2B2, "s-session/2"), /未获准的完整规则组合/);
  // 领域初始化政策仍是 W/1：W/2 不改 payload 政策值。
  assert.equal(typed.INITIALIZATION_POLICY, "raw-initialization-w/1");
});

function w2Case() {
  const raw = (id, coord, extra = {}) => ({ object_id: id, coord, first_known_generation: "1", withdrawn_generation: null, withdrawal_reason: null, superseded_by: null, ...extra });
  const pending = [
    raw("u0", "0", { withdrawn_generation: "4", withdrawal_reason: "superseded_by_revision", superseded_by: "g0" }),
    raw("u1", "1", { withdrawn_generation: "2", withdrawal_reason: "superseded_by_revision", superseded_by: "u1r" }), // 修订换新原件身份
    raw("u1r", "1", { first_known_generation: "2", withdrawn_generation: "4", withdrawal_reason: "superseded_by_revision", superseded_by: "g0" }),
    raw("u2", "2", { withdrawn_generation: "4", withdrawal_reason: "superseded_by_revision", superseded_by: "g1" }),
  ];
  const groups = [
    { object_id: "g0", members: ["0", "1"], first_known_generation: "4", withdrawn_generation: null },
    { object_id: "g1", members: ["2"], first_known_generation: "4", withdrawn_generation: null },
  ];
  const kinds = new Map([...pending.map((p) => [p.object_id, "CC-004.undetermined_raw"]), ...groups.map((g) => [g.object_id, "CC-005.inclusion_group"])]);
  const superseded = pending.filter((p) => p.superseded_by).map((p) => ({ ...p, kind: "CC-004.undetermined_raw" }));
  const replaces = superseded.map((w) => ({ subject: w.superseded_by, object: w.object_id }));
  const objects = new Map([...pending, ...groups].map((r) => [r.object_id, r]));
  return { pending, groups, superseded, replaces, kinds, objects };
}
test("W/2 逐原件替代：每个未定原件（含修订身份）替代到含其坐标的定向组，公开 replaces 关系逐条对应", () => {
  typed.w2Replacements(w2Case());
  const reject = (mutate, pattern) => {
    const c = w2Case();
    mutate(c);
    assert.throws(() => typed.w2Replacements(c), pattern);
  };
  // 原 W/1 g4 形态：进组的未定原件按 fact_removed/null 撤回，W/2 下必须拒。
  reject((c) => Object.assign(c.pending[0], { withdrawal_reason: "fact_removed", superseded_by: null }), /fact_removed/);
  reject((c) => {
    Object.assign(c.pending[1], { withdrawal_reason: "fact_removed", superseded_by: null });
    c.superseded = c.superseded.filter((w) => w.object_id !== "u1");
    c.replaces = c.replaces.filter((r) => r.object !== "u1");
  }, /fact_removed/);
  const genuineRemoved = w2Case();
  const gone = { object_id: "ugone", coord: "9", first_known_generation: "1", withdrawn_generation: "2", withdrawal_reason: "fact_removed", superseded_by: null };
  genuineRemoved.pending.push(gone);
  genuineRemoved.kinds.set("ugone", "CC-004.undetermined_raw");
  genuineRemoved.objects.set("ugone", gone);
  typed.w2Replacements(genuineRemoved);
  reject((c) => { c.pending[3].superseded_by = "g0"; c.replaces[3].subject = "g0"; }, /不满足坐标、种类或生命周期/); // 错coord/非所属组
  reject((c) => { c.groups[1].first_known_generation = "5"; }, /不满足坐标、种类或生命周期/); // 组在替代代尚未出生
  reject((c) => { c.replaces.splice(0, 1); }, /缺公开replaces关系/); // 漏边
  reject((c) => { c.replaces.splice(1, 1); }, /缺公开replaces关系/); // 修订身份漏边
  reject((c) => { c.replaces.push({ subject: "g1", object: "u0" }); }, /缺对应撤回或superseded_by不符/); // 额外边
  reject((c) => { c.pending[1].superseded_by = "u1"; c.replaces[1].subject = "u1"; }, /不满足坐标、种类或生命周期/); // 修订身份混淆为自身
  reject((c) => { c.kinds.set("x", "CC-010.bi"); c.kinds.set("y", "CC-005.inclusion_group"); c.objects.set("y", {first_known_generation: "1", withdrawn_generation: null}); c.superseded.push({ object_id: "x", kind: "CC-010.bi", superseded_by: "y" }); c.replaces.push({ subject: "y", object: "x" }); }, /跨kind替代未获准/); // 任意kind
  reject((c) => {
    const oldBatch = { object_id: "b4", kind: "CC-007.development_batch", slot: JSON.stringify(["CC-007.development_batch", "4"]), first_known_generation: "4", withdrawn_generation: "5", withdrawal_reason: "superseded_by_revision", superseded_by: "b3" };
    const newBatch = { object_id: "b3", kind: "CC-007.development_batch", slot: JSON.stringify(["CC-007.development_batch", "3"]), first_known_generation: "4", withdrawn_generation: null, withdrawal_reason: null, superseded_by: null };
    c.kinds.set("b4", oldBatch.kind); c.kinds.set("b3", newBatch.kind);
    c.objects.set("b4", oldBatch); c.objects.set("b3", newBatch);
    c.superseded.push(oldBatch);
    c.replaces.push({ subject: "b3", object: "b4" });
  }, /W2同kind替代槽位不符/);
  reject((c) => {
    const slot = JSON.stringify(["CC-007.development_batch", "3"]);
    const oldBatch = { object_id: "b3old", kind: "CC-007.development_batch", slot, first_known_generation: "3", withdrawn_generation: "4", withdrawal_reason: "fact_removed", superseded_by: null };
    const newBatch = { object_id: "b3new", kind: "CC-007.development_batch", slot, first_known_generation: "4", withdrawn_generation: null, withdrawal_reason: null, superseded_by: null };
    c.kinds.set("b3old", oldBatch.kind); c.kinds.set("b3new", newBatch.kind);
    c.objects.set("b3old", oldBatch); c.objects.set("b3new", newBatch);
  }, /W2同槽位存在替代目标却按fact_removed撤回/);
  reject((c) => {
    c.pending[1].withdrawn_generation = "3";
  }, /W2同槽位对象生命周期重叠/);
});

test("W/2 完整 validateState：替代目标须在撤回代已出生且在世，公开 replaces 全集对应撤回事实", async (t) => {
  const H = require("./q3_complete_fixture.cjs");
  const b = await H.makeS16Base("3", "q3-real-s3-w-recover-revise.json");
  b.graph = await H.C.GraphView.create([...b.nodes.values()]);
  async function plain(ref) { let t = ""; for await (const c of b.graph.renderChunks(ref)) t += c; return JSON.parse(t); }
  const snapshot = await plain(b.graph.header(b.publication.snapshot_root)), catalog = await plain(b.catalog);
  snapshot.rule_revision = b.fixed.rule_revision;
  const state = { snapshot, catalog, cut: Object.fromEntries(["session_id", "generation", "structure_cut", "catalog_revision", "index_frontier"].map((k) => [k, snapshot[k]])) };
  async function reid(st) {
    const mm = new Map();
    for (const r of [...st.snapshot.objects, ...st.snapshot.withdrawn_objects]) {
      const p = Object.fromEntries(["kind", "fact_key", "payload", "input_refs"].map((k) => [k, r[k]]));
      p.profile_id = st.snapshot.profile_id;
      p.rule_revision = st.snapshot.rule_revision;
      mm.set(r.object_id, await Q3.V.identity(0x20, p, "obj3-"));
    }
    function replace(v) {
      if (typeof v === "string") return mm.get(v) || v;
      if (Array.isArray(v)) return v.map(replace);
      if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, replace(x)]));
      return v;
    }
    return replace(st);
  }
  await Q3.validateState(state, "s-session/3");
  t.diagnostic("W1 历史完整入口正控通过");
  let w2 = structuredClone(state);
  w2.snapshot.rule_revision = typed.W2_PUBLICATION_RULE;
  w2.snapshot.catalog_evidence.rule_revision = w2.snapshot.rule_revision;
  w2.catalog.catalog_evidence.rule_revision = w2.snapshot.rule_revision;
  for (let k = 0; k < 4; k++) w2 = await reid(w2);
  await Q3.validateState(w2, "s-session/3");
  t.diagnostic("手工 W2 正控及非 raw g1 到 g2 到 g3 历史链通过，目标后来撤回合法");
  let archived = structuredClone(state);
  archived.snapshot.rule_revision = archived.snapshot.catalog_evidence.rule_revision = archived.catalog.catalog_evidence.rule_revision = typed.W2_ARCHIVED_RULE;
  for (let k = 0; k < 4; k++) archived = await reid(archived);
  await Q3.validateState(archived, "s-session/3");
  t.diagnostic("失败候选 W2+bounded-layout/1 完整串仍按 W2 语义归档读通过");

  const reject = async (candidate, pattern, label) => {
    await assert.rejects(() => Q3.validateState(candidate, "s-session/3"), pattern);
    t.diagnostic(label);
  };
  let futureRevision = structuredClone(w2);
  const cur = futureRevision.snapshot.objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.payload.raw.source_coord === "0");
  const old = structuredClone(cur);
  old.object_id = "obj3-" + "f".repeat(64);
  old.lifecycle = "withdrawn";
  old.withdrawn_generation = "2";
  old.withdrawal_reason = "superseded_by_revision";
  old.superseded_by = cur.object_id;
  cur.first_known_generation = cur.published_generation = "3";
  cur.first_known_cut = cur.payload.pending_since_cut = "cut-3";
  futureRevision.snapshot.withdrawn_objects.push(old);
  futureRevision.snapshot.relations.push({ subject: cur.object_id, relation_type: "replaces", object: old.object_id });
  for (let k = 0; k < 4; k++) futureRevision = await reid(futureRevision);
  await reject(futureRevision, /不满足坐标、种类或生命周期/, "F1 未来目标在生命周期判据拒绝");

  // 手工单元历史为 old 在 g2 被 middle 替代，middle 在 g3 被 current 替代。
  let laterWithdrawn = structuredClone(w2);
  const current = laterWithdrawn.snapshot.objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.payload.raw.source_coord === "0");
  const middle = structuredClone(current), oldest = structuredClone(current);
  current.first_known_generation = current.published_generation = "3";
  current.first_known_cut = current.payload.pending_since_cut = "cut-3";
  Object.assign(middle, { object_id: "obj3-" + "d".repeat(64), first_known_generation: "2", published_generation: "2", first_known_cut: "cut-2", withdrawn_generation: "3", withdrawal_reason: "superseded_by_revision", superseded_by: current.object_id, lifecycle: "withdrawn" });
  middle.payload.pending_since_cut = "cut-2";
  Object.assign(oldest, { object_id: "obj3-" + "e".repeat(64), withdrawn_generation: "2", withdrawal_reason: "superseded_by_revision", superseded_by: middle.object_id, lifecycle: "withdrawn" });
  laterWithdrawn.snapshot.withdrawn_objects.push(oldest, middle);
  laterWithdrawn.snapshot.relations.push({ subject: middle.object_id, relation_type: "replaces", object: oldest.object_id }, { subject: current.object_id, relation_type: "replaces", object: middle.object_id });
  for (let k = 0; k < 4; k++) laterWithdrawn = await reid(laterWithdrawn);
  await Q3.validateState(laterWithdrawn, "s-session/3");
  t.diagnostic("F1 g1→g2→g3 历史链通过，目标后来撤回合法");

  let disguisedFactRemoved = structuredClone(laterWithdrawn);
  const g1Raw = disguisedFactRemoved.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.first_known_generation === "1");
  Object.assign(g1Raw, { withdrawal_reason: "fact_removed", superseded_by: null });
  disguisedFactRemoved.snapshot.relations = disguisedFactRemoved.snapshot.relations.filter((r) => r.relation_type !== "replaces" || r.object !== g1Raw.object_id);
  await reject(disguisedFactRemoved, /W2未定原件存在替代目标却按fact_removed撤回/, "R2-1 未定原件修订伪装 fact_removed 漏替代边在完整 validateState 拒绝");

  let omittedMiddleFactRemoved = structuredClone(disguisedFactRemoved);
  const g2Raw = omittedMiddleFactRemoved.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.first_known_generation === "2");
  omittedMiddleFactRemoved.snapshot.withdrawn_objects = omittedMiddleFactRemoved.snapshot.withdrawn_objects.filter((r) => r.object_id !== g2Raw.object_id);
  omittedMiddleFactRemoved.snapshot.relations = omittedMiddleFactRemoved.snapshot.relations.filter((r) => r.relation_type !== "replaces" || r.object !== g2Raw.object_id);
  await reject(omittedMiddleFactRemoved, /W2未定原件存在替代目标却按fact_removed撤回/, "R2-1b 删去中间代未定原件仍由同代初始化来源锁死拒绝");

  let genuineFactRemovedState = structuredClone(w2);
  const activeCoord2 = genuineFactRemovedState.snapshot.objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.payload.raw.source_coord === "2");
  const removedCoord2 = structuredClone(activeCoord2);
  Object.assign(removedCoord2, { object_id: "obj3-" + "c".repeat(64), first_known_generation: "1", published_generation: "1", first_known_cut: "cut-1", withdrawn_generation: "2", withdrawal_reason: "fact_removed", superseded_by: null, lifecycle: "withdrawn" });
  removedCoord2.payload.pending_since_cut = "cut-1";
  activeCoord2.first_known_generation = activeCoord2.published_generation = "3";
  activeCoord2.first_known_cut = activeCoord2.payload.pending_since_cut = "cut-3";
  const initAt1 = genuineFactRemovedState.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.first_known_generation === "1");
  initAt1.input_refs.push(structuredClone(activeCoord2.input_refs[0]));
  initAt1.source_coords.push("2");
  genuineFactRemovedState.snapshot.withdrawn_objects.push(removedCoord2);
  for (let k = 0; k < 4; k++) genuineFactRemovedState = await reid(genuineFactRemovedState);
  genuineFactRemovedState.snapshot.withdrawn_objects.sort((a, b) =>
    Number(a.withdrawn_generation) - Number(b.withdrawn_generation) || (a.object_id < b.object_id ? -1 : 1));
  await Q3.validateState(genuineFactRemovedState, "s-session/3");
  t.diagnostic("R2-1c 无同代继任者的合法 fact_removed 完整 validateState 正常通过");

  const alreadyWithdrawn = structuredClone(laterWithdrawn);
  const withdrawnRaws = alreadyWithdrawn.snapshot.withdrawn_objects.filter((r) => r.kind === "CC-004.undetermined_raw");
  const earlier = withdrawnRaws.find((r) => r.first_known_generation === "1"), later = withdrawnRaws.find((r) => r.first_known_generation === "2");
  // later 在 g3 撤回，却指向已于 g2 撤回的 earlier。去掉原边以免先触发多余边检查。
  later.superseded_by = earlier.object_id;
  alreadyWithdrawn.snapshot.relations = alreadyWithdrawn.snapshot.relations.filter((r) => r.relation_type !== "replaces" || r.object !== later.object_id);
  alreadyWithdrawn.snapshot.relations.push({ subject: earlier.object_id, relation_type: "replaces", object: later.object_id });
  await reject(alreadyWithdrawn, /不满足坐标、种类或生命周期/, "F1 已先撤回目标在生命周期判据拒绝");

  const extraEdge = structuredClone(w2);
  const raw = extraEdge.snapshot.objects.find((r) => r.kind === "CC-004.undetermined_raw");
  const init = extraEdge.snapshot.objects.find((r) => r.kind === "CC-004.initialization");
  extraEdge.snapshot.relations.push({ subject: raw.object_id, relation_type: "replaces", object: init.object_id });
  await reject(extraEdge, /缺对应撤回/, "F2 额外跨 kind 边在撤回对应判据拒绝");

  const activeReplaced = structuredClone(w2);
  const activeRaw = activeReplaced.snapshot.objects.find((r) => r.kind === "CC-004.undetermined_raw" && r.withdrawn_generation === null);
  const activeInit = activeReplaced.snapshot.objects.find((r) => r.kind === "CC-004.initialization");
  activeReplaced.snapshot.relations.push({ subject: activeInit.object_id, relation_type: "replaces", object: activeRaw.object_id });
  await reject(activeReplaced, /缺对应撤回/, "F2 活动对象被替代在撤回对应判据拒绝");

  const wrongTarget = structuredClone(w2);
  const wrongEdge = structuredClone(wrongTarget.snapshot.relations.find((r) => r.relation_type === "replaces"));
  wrongEdge.subject = raw.object_id;
  wrongTarget.snapshot.relations.push(wrongEdge);
  await reject(wrongTarget, /superseded_by不符/, "F2 replaces 与 superseded_by 不符在精确对应判据拒绝");

  const crossKind = structuredClone(w2);
  const previousInit = crossKind.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.superseded_by !== null);
  const edge = crossKind.snapshot.relations.find((r) => r.relation_type === "replaces" && r.object === previousInit.object_id);
  previousInit.superseded_by = raw.object_id;
  edge.subject = raw.object_id;
  await reject(crossKind, /跨kind替代未获准/, "F2 有撤回对应的非法跨 kind 边在端点种类判据拒绝");

  const missingEdge = structuredClone(w2);
  missingEdge.snapshot.relations = missingEdge.snapshot.relations.filter((r) => r.relation_type !== "replaces" || r.object !== previousInit.object_id);
  await reject(missingEdge, /替代撤回缺公开replaces关系/, "F2 非 raw 替代撤回漏边在完整性判据拒绝");

  const duplicateEdge = structuredClone(w2);
  duplicateEdge.snapshot.relations.push(structuredClone(duplicateEdge.snapshot.relations.find((r) => r.relation_type === "replaces")));
  await reject(duplicateEdge, /重复公开replaces关系/, "N1 重复公开 replaces 边在一一对应判据拒绝");

  const selfReplace = structuredClone(w2);
  const self = selfReplace.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.superseded_by !== null);
  self.superseded_by = self.object_id;
  selfReplace.snapshot.relations.find((r) => r.relation_type === "replaces" && r.object === self.object_id).subject = self.object_id;
  await reject(selfReplace, /替代目标不存在或生命周期不符/, "N2 非 raw 自我替代在目标生命周期判据拒绝");

  const ghostTarget = structuredClone(w2);
  const ghostOld = ghostTarget.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.superseded_by !== null);
  ghostOld.superseded_by = "obj3-" + "a".repeat(64);
  ghostTarget.snapshot.relations.find((r) => r.relation_type === "replaces" && r.object === ghostOld.object_id).subject = ghostOld.superseded_by;
  await reject(ghostTarget, /替代目标不存在或生命周期不符/, "N2 不存在的非 raw 目标在目标存在性判据拒绝");

  const nonrawFuture = structuredClone(w2);
  const initFirst = nonrawFuture.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.first_known_generation === "1");
  const initLast = nonrawFuture.snapshot.objects.find((r) => r.kind === "CC-004.initialization");
  initFirst.superseded_by = initLast.object_id;
  nonrawFuture.snapshot.relations.find((r) => r.relation_type === "replaces" && r.object === initFirst.object_id).subject = initLast.object_id;
  await reject(nonrawFuture, /替代目标不存在或生命周期不符/, "N2 非 raw 未来目标在生命周期判据拒绝");

  const nonrawDead = structuredClone(w2);
  const initEarlier = nonrawDead.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.first_known_generation === "1");
  const initLater = nonrawDead.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.initialization" && r.first_known_generation === "2");
  initLater.superseded_by = initEarlier.object_id;
  nonrawDead.snapshot.relations.find((r) => r.relation_type === "replaces" && r.object === initLater.object_id).subject = initEarlier.object_id;
  await reject(nonrawDead, /替代目标不存在或生命周期不符/, "N2 非 raw 已先撤回目标在生命周期判据拒绝");

  const nonrawDisguisedRemoved = structuredClone(w2);
  const ksRemoved = nonrawDisguisedRemoved.snapshot.withdrawn_objects.find((r) => r.kind === "CC-054.knowledge_state" && r.first_known_generation === "1");
  Object.assign(ksRemoved, { withdrawal_reason: "fact_removed", superseded_by: null });
  nonrawDisguisedRemoved.snapshot.relations = nonrawDisguisedRemoved.snapshot.relations.filter((r) => r.relation_type !== "replaces" || r.object !== ksRemoved.object_id);
  await reject(nonrawDisguisedRemoved, /W2同槽位存在替代目标却按fact_removed撤回/, "R3-1 非 pending 同槽位存在在世替代目标却伪装 fact_removed 被拒绝");

  const nonrawOverlap = structuredClone(w2);
  const ksOverlap = nonrawOverlap.snapshot.withdrawn_objects.find((r) => r.kind === "CC-054.knowledge_state" && r.first_known_generation === "1");
  ksOverlap.withdrawn_generation = "3";
  await reject(nonrawOverlap, /W2同槽位对象生命周期重叠/, "R3-2 同槽位生命周期重叠被拒绝");
});

// #1419 31P bounded-layout/2：单元 source_ref 经真实公开入口 Q3.validateState 消费。底座是真实 Rust 导出 g5（W1 原件），
// 下列改动均为手工读者夹具：三条 fact_removed 未定原件改为 W2 逐原件替代到含其坐标的组并补 replaces 边；
// 另加一个分型及坐标 3、4 的具名单元批记录，覆盖活动与撤回序列。期望 source_ref 由 raw_history
// 原行按 RawRefSpec 八字段独立抽取，不取候选生成物。不代替 #1419 正式 /2 产物的真实 S/Q 验收。
test("bounded-layout/2 完整 validateState：单元 source_ref 精确绑定同坐标当前披露源，旧 W2+/1 仍按原单元字段读", async (t) => {
  const H = require("./q3_complete_fixture.cjs");
  const b = await H.makeS16Base("5", "q3-real-s3-w-recover-revise.json");
  b.graph = await H.C.GraphView.create([...b.nodes.values()]);
  async function plain(ref) { let s = ""; for await (const c of b.graph.renderChunks(ref)) s += c; return JSON.parse(s); }
  const snapshot = await plain(b.graph.header(b.publication.snapshot_root)), catalog = await plain(b.catalog);
  snapshot.rule_revision = b.fixed.rule_revision;
  const base = { snapshot, catalog, cut: Object.fromEntries(["session_id", "generation", "structure_cut", "catalog_revision", "index_frontier"].map((k) => [k, snapshot[k]])) };
  await Q3.validateState(base, "s-session/3");
  function convert(r, keys = ["seq", "revision"]) {
    return Object.fromEntries(Object.entries(r).map(([k, x]) =>
      [k, keys.includes(k) && x !== null ? Q3.V.number(x) : x]));
  }
  async function reid(st) {
    for (let k = 0; k < 5; k++) {
      const mm = new Map();
      for (const r of [...st.snapshot.objects, ...st.snapshot.withdrawn_objects]) {
        let p;
        if (r.kind !== "CC-006.local_shape") {
          p = Object.fromEntries(["kind", "fact_key", "payload", "input_refs"].map(k => [k, r[k]]));
        } else {
          p = Object.fromEntries(["branch", "dir_ab", "dir_bc", "window_start",
            "window_mid", "window_end", "comparisons"].map(k => [k, r[k]]));
          const groups = r.input_refs.map(ir => st.snapshot.objects.find(g =>
            g.kind === "CC-005.inclusion_group" && g.payload.group_index === ir.merged_index));
          p.merged_highs = groups.map(g => g.payload.high);
          p.merged_lows = groups.map(g => g.payload.low);
          p.input_refs = r.input_refs.map(g => ({
            merged_index: Q3.V.number(g.merged_index),
            raw_refs: g.raw_refs.map(r => convert(r)),
            dependency_refs: g.dependency_refs.map(r => convert(r))
          }));
        }
        p.profile_id = st.snapshot.profile_id;
        p.rule_revision = st.snapshot.rule_revision;
        mm.set(r.object_id, await Q3.V.identity(0x20, p, "obj3-"));
      }
      const replace = v => typeof v === "string" ? mm.get(v) || v
        : Array.isArray(v) ? v.map(replace)
        : v && typeof v === "object"
          ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, replace(x)])) : v;
      st = replace(st);
    }
    for (const w of st.snapshot.witnesses) {
      const group = st.snapshot.objects.find(g => g.kind === "CC-005.inclusion_group"
        && g.payload.group_anchor === w.merged_source_index);
      const raw_bars = w.raw_bars.map(r => ({
        ...convert(r, ["revision", "seq", "supersedes_revision"]), price: r.close
      }));
      w.witness_id = "wit-" + (await Q3.V.sha({
        mi: Q3.V.number(group.payload.group_index), object_id: w.object_id,
        raw_bars, slot: Q3.V.number(w.slot)
      })).slice(0, 16);
    }
    return st;
  }
  const REF_KEYS = ["identity_key", "payload_hash", "receipt_id", "event_id", "input_revision", "revision", "seq", "source_coord"];
  const rawRef = (coord) => {
    const rows = snapshot.raw_history.filter((r) => r.source_coord === coord);
    assert.equal(rows.length, 1, "夹具每坐标单一修订");
    return Object.fromEntries(REF_KEYS.map((k) => [k, rows[0][k]]));
  };
  const rawBar = (coord) => { const r = snapshot.raw_history.find((x) => x.source_coord === coord); return { source_coord: coord, open: r.open, high: r.high, low: r.low, close: r.close }; };
  const names = ["left.high", "left.low", "mid.high", "mid.low", "right.high", "right.low"];
  const prices = names.map((name, i) => ({ name, source_coord: String(i >> 1), axis: name.split(".")[1], value: rawBar(String(i >> 1))[name.split(".")[1]] }));
  const cmp = (a, c) => (BigInt(a) < BigInt(c) ? "LT" : BigInt(a) > BigInt(c) ? "GT" : "EQ");
  const unitOf = (bar, source) => ({ bar, relations: ["open", "high", "low", "close"].flatMap((axis) => prices.map((p) => ({ axis, value: bar[axis], reference: p.name, reference_value: p.value, order: cmp(bar[axis], p.value) }))), ...(source ? { source_ref: source } : {}) });
  function build(rule, withSource) {
    const st = structuredClone(base);
    st.snapshot.rule_revision = st.snapshot.catalog_evidence.rule_revision = st.catalog.catalog_evidence.rule_revision = rule;
    const group = st.snapshot.objects.find((r) => r.kind === "CC-005.inclusion_group" && r.payload.members.includes("0"));
    for (const u of st.snapshot.withdrawn_objects.filter((r) => r.kind === "CC-004.undetermined_raw")) {
      assert(group.payload.members.includes(u.payload.raw.source_coord));
      Object.assign(u, { withdrawal_reason: "superseded_by_revision", superseded_by: group.object_id });
      st.snapshot.relations.push({ subject: group.object_id, relation_type: "replaces", object: u.object_id });
    }
    for (const r of st.snapshot.objects)
      if (r.kind === "CC-007.fractal_description") delete r.payload.subsequent_development;
    const template = st.snapshot.objects.find((r) => r.kind === "CC-005.inclusion_group");
    const record = (kind, factKey, payload, coords, id) => ({ ...structuredClone(template), object_id: id, kind, fact_key: factKey, payload,
      input_refs: coords.map(rawRef), source_coords: coords });
    const fractalKey = JSON.stringify(["CC-007.fractal_description", ["0", "1", "2"]]);
    st.snapshot.objects.push(record("CC-007.fractal_description", fractalKey, { shape_object_id: "obj3-shape", branch: "TOP", window: ["0", "1", "2"], description: "手工读者夹具",
      reference_prices: prices, descriptive_labels: { status: "not_determined", reason: "no_settled_numeric_rule", labels: [], source: "fenxing.md:64-74", raw_ohlc: ["0", "1", "2"].map(rawBar) } }, ["0", "1", "2"], "obj3-fractal31p"));
    const unit = unitOf(rawBar("3"), withSource ? rawRef("3") : null);
    st.snapshot.objects.push(record("CC-007.development_batch", JSON.stringify(["CC-007.development_batch", "3"]),
      { bar: rawBar("3"), entries: [{ fractal_object_id: "obj3-fractal31p", unit, development: { root: [unit], count: "1" } }] }, ["3"], "obj3-batch31p"));
    return st;
  }
  const batchOf = (st) => st.snapshot.objects.find((r) => r.kind === "CC-007.development_batch");
  const unitEdit = (st, edit) => { const p = batchOf(st).payload; edit(p.entries[0].unit); p.entries[0].development.root = [p.entries[0].unit]; return st; };
  await Q3.validateState(await reid(build(typed.W2_PUBLICATION_RULE, true)), "s-session/3");
  t.diagnostic("P1 新 /2 串：单元 bar 五字段、24 关系保留，source_ref 等于 raw_history 坐标 3 的八字段原值");
  await Q3.validateState(await reid(build(typed.W2_ARCHIVED_RULE, false)), "s-session/3");
  t.diagnostic("P2 旧 W2+/1：单元仍为 bar/relations 两字段，按 W2 语义＋Bounded1 读");
  const asW1 = build(typed.W2_ARCHIVED_RULE, false), u0 = asW1.snapshot.withdrawn_objects.find((r) => r.kind === "CC-004.undetermined_raw");
  Object.assign(u0, { withdrawal_reason: "fact_removed", superseded_by: null });
  asW1.snapshot.relations = asW1.snapshot.relations.filter((r) => r.object !== u0.object_id);
  await assert.rejects(async () => Q3.validateState(await reid(asW1), "s-session/3"), /fact_removed/);
  t.diagnostic("P2' 旧 W2+/1 遇 W1 式 fact_removed 进组撤回即拒：未误落 W1");
  const reject = async (st, pattern, label) => { await assert.rejects(async () => Q3.validateState(await reid(st), "s-session/3"), pattern); t.diagnostic(label); };
  const NEW = typed.W2_PUBLICATION_RULE;
  await reject(build(NEW, false), /完整字段不符/, "R1 /2 缺 source_ref 拒");
  await reject(build(typed.W2_ARCHIVED_RULE, true), /完整字段不符/, "R2 旧 /1 携 source_ref 拒");
  await reject(unitEdit(build(NEW, true), (u) => { u.source_ref = rawRef("2"); }), /单元源引用坐标与单元 bar 不同/, "R3 错坐标拒");
  await reject(unitEdit(build(NEW, true), (u) => { u.source_ref = { ...u.source_ref, revision: "2", input_revision: "2" }; }), /单元源引用不是本批披露源/, "R4 错修订拒");
  for (const [label, value] of [["数", 4], ["null", null], ["对象", { n: "4" }]]) {
    const typedWrong = await reid(build(NEW, true));
    unitEdit(typedWrong, (u) => { u.source_ref.seq = value; });
    await assert.rejects(() => Q3.validateState(typedWrong, "s-session/3"), /非法内容值|要求标量|要求 UTF-8 文本/);
    t.diagnostic("R5 seq 为" + label + "：正式读取拒");
  }
  await reject(unitEdit(build(NEW, true), (u) => { u.source_ref = { ...u.source_ref, generation: "4" }; }), /完整字段不符/, "R6 掺入多余字段拒");
  await reject(unitEdit(build(NEW, true), (u) => { delete u.source_ref.receipt_id; }), /完整字段不符/, "R7 缺八字段之一拒");
  const drifted = build(NEW, true);
  for (const r of drifted.snapshot.objects.filter((x) => x.kind === "CC-007.development_batch")) {
    const forged = { ...r.input_refs[0], receipt_id: "rcpt-forged" };
    r.input_refs = [forged];
    unitEdit(drifted, (u) => { u.source_ref = forged; });
  }
  await reject(drifted, /对象八键来源未绑定独立完整原始历史/, "R8 source_ref 与批来源同改但不在原始历史：正式读取链拒");
  for (const [axis, badVal] of [["open", "99999"], ["high", "99999"], ["low", "1"], ["close", "99999"]]) {
    const forgedOhlc = build(NEW, true), bRec = batchOf(forgedOhlc);
    const tamperedBar = { ...bRec.payload.bar, [axis]: badVal };
    bRec.payload.bar = tamperedBar;
    bRec.payload.entries[0].unit = unitOf(tamperedBar, rawRef("3"));
    bRec.payload.entries[0].development.root = [bRec.payload.entries[0].unit];
    await reject(forgedOhlc, /事实中原始 OHLC 值与真实源记录不符/, "R9 保持真实 source_ref 篡改单元 bar." + axis + " 被完整 validateState 拒绝");
  }
  {
    const forgedArchivedOhlc = build(typed.W2_ARCHIVED_RULE, false), bRec = batchOf(forgedArchivedOhlc);
    const tamperedBar = { ...bRec.payload.bar, open: "99999" };
    bRec.payload.bar = tamperedBar;
    bRec.payload.entries[0].unit = unitOf(tamperedBar, null);
    bRec.payload.entries[0].development.root = [bRec.payload.entries[0].unit];
    await reject(forgedArchivedOhlc, /事实中原始 OHLC 值与真实源记录不符/, "R9b 旧 W2+/1 篡改批与单元 bar.open 同样拒绝");
  }
  const twoUnits = (rule = NEW, sourced = true) => {
    const st = build(rule, sourced), first = batchOf(st), second = structuredClone(first);
    second.object_id = "obj3-batch31w-second";
    second.fact_key = JSON.stringify(["CC-007.development_batch", "4"]);
    second.source_coords = ["4"];
    second.input_refs = [rawRef("4")];
    second.payload.bar = rawBar("4");
    const entry = second.payload.entries[0];
    entry.unit = unitOf(rawBar("4"), sourced ? rawRef("4") : null);
    entry.development = { root: [structuredClone(first.payload.entries[0].unit), entry.unit], count: "2" };
    st.snapshot.objects.push(second);
    return st;
  };
  const prefixOf = (st) => st.snapshot.objects.find((r) => r.kind === "CC-007.development_batch" && r.source_coords[0] === "4").payload.entries[0].development.root[0];
  await t.test("双单元公开正控及 W2+/1 归档正控", async () => {
    await Q3.validateState(await reid(twoUnits()), "s-session/3");
    await Q3.validateState(await reid(twoUnits(typed.W2_ARCHIVED_RULE, false)), "s-session/3");
  });
  const withdrawnUnits = () => {
    const st = twoUnits();
    const bs = st.snapshot.objects.filter(r => r.kind === "CC-007.development_batch");
    st.snapshot.objects = st.snapshot.objects.filter(r => r.kind !== "CC-007.development_batch");
    for (const batch of bs) Object.assign(batch, {
      lifecycle: "withdrawn", withdrawn_generation: "5", withdrawal_reason: "fact_removed", superseded_by: null,
    });
    st.snapshot.withdrawn_objects.push(...bs);
    return st;
  };
  await t.test("已撤回双单元公开正控及非末项缺边、伪来源、坏关系拒绝", async () => {
    await Q3.validateState(await reid(withdrawnUnits()), "s-session/3");
    for (const [edit, pattern] of [
      [(u) => { delete u.source_ref; }, /完整字段不符/],
      [(u) => { u.source_ref.receipt_id = "forged-withdrawn-31w"; }, /单元序列.*绑定/],
    ]) {
      const bad = withdrawnUnits();
      const batch = bad.snapshot.withdrawn_objects.find(r => r.kind === "CC-007.development_batch" && r.source_coords[0] === "4");
      edit(batch.payload.entries[0].development.root[0]);
      await assert.rejects(async () => Q3.validateState(await reid(bad), "s-session/3"), pattern);
    }
    for (const [mutate, pattern] of [
      [(b) => { b.payload.entries[0].unit.relations = Array(24).fill(null); b.payload.entries[0].development.root = [b.payload.entries[0].unit]; }, /后续关系/],
      [(b) => { b.payload.entries[0].unit.relations[0].reference_value = "99999"; b.payload.entries[0].development.root = [b.payload.entries[0].unit]; }, /后续关系来源不同/],
      [(b) => { b.payload.entries[0].unit.relations[0].order = "BAD"; b.payload.entries[0].development.root = [b.payload.entries[0].unit]; }, /后续关系来源不同/],
      [(b) => { b.payload.entries[0].fractal_object_id = "obj3-" + "9".repeat(64); }, /指向缺失分型/],
      [(b) => {
        const tamperedBar = { ...b.payload.bar, open: "99999" };
        b.payload.bar = tamperedBar;
        b.payload.entries[0].unit = unitOf(tamperedBar, rawRef("3"));
        b.payload.entries[0].development.root = [b.payload.entries[0].unit];
      }, /事实中原始 OHLC 值与真实源记录不符/],
    ]) {
      const bad = build(NEW, true), bRec = batchOf(bad);
      bad.snapshot.objects = bad.snapshot.objects.filter((r) => r !== bRec);
      Object.assign(bRec, { lifecycle: "withdrawn", withdrawn_generation: "5", withdrawal_reason: "fact_removed", superseded_by: null });
      mutate(bRec);
      bad.snapshot.withdrawn_objects.push(bRec);
      await assert.rejects(async () => Q3.validateState(await reid(bad), "s-session/3"), pattern);
    }
  });
  for (const [label, edit, pattern] of [
    ["缺 source_ref", (u) => { delete u.source_ref; }, /完整字段不符/],
    ["伪 receipt", (u) => { u.source_ref.receipt_id = "forged-31w"; }, /单元序列.*绑定/],
    ["错坐标", (u) => { u.source_ref = rawRef("2"); }, /单元源引用坐标/],
    ["错修订", (u) => { u.source_ref.input_revision = u.source_ref.revision = "2"; }, /单元序列.*绑定/],
    ["数字 seq", (u) => { u.source_ref.seq = 4; }, /非法内容值|要求标量|UTF-8/],
    ["null seq", (u) => { u.source_ref.seq = null; }, /要求标量|UTF-8/],
    ["对象 seq", (u) => { u.source_ref.seq = { n: "4" }; }, /要求标量|UTF-8/],
    ["多余键", (u) => { u.source_ref.extra = "1"; }, /完整字段不符/],
    ["缺八字段之一", (u) => { delete u.source_ref.receipt_id; }, /完整字段不符/],
    ["不是前批单元", (u) => { u.relations[0].order = "EQ"; }, /单元序列.*绑定/],
    ["自洽篡改 bar.open", (u) => { Object.assign(u, unitOf({ ...rawBar("3"), open: "99999" }, rawRef("3"))); }, /单元序列未绑定已验证单元/],
  ]) await t.test("非末项" + label + "在来源或序列判据拒绝", async () => {
    const bad = twoUnits(); edit(prefixOf(bad));
    await assert.rejects(async () => Q3.validateState(await reid(bad), "s-session/3"), pattern);
  });
  await t.test("W2_ARCHIVED_RULE（bounded-layout/1）第二批前缀单元自洽篡改 bar.open 被拒绝", async () => {
    const bad = twoUnits(typed.W2_ARCHIVED_RULE, false);
    Object.assign(prefixOf(bad), unitOf({ ...rawBar("3"), open: "99999" }, null));
    await assert.rejects(async () => Q3.validateState(await reid(bad), "s-session/3"), /单元序列未绑定已验证单元/);
  });
  await t.test("layout/1 与有界布局下 CC-007.fractal_description 原始 bar OHLC 篡改与未绑定坐标被拒绝", async () => {
    const template = base.snapshot.objects.find((r) => r.kind === "CC-005.inclusion_group");
    const layout1WithFractal = () => {
      const st = structuredClone(base);
      st.snapshot.objects.push({
        ...structuredClone(template),
        object_id: "obj3-fractal-layout1",
        kind: "CC-007.fractal_description",
        fact_key: JSON.stringify(["CC-007.fractal_description", ["0", "1", "2"]]),
        input_refs: ["0", "1", "2", "3"].map(rawRef),
        source_coords: ["0", "1", "2", "3"],
        payload: {
          shape_object_id: "obj3-shape",
          branch: "TOP",
          window: ["0", "1", "2"],
          description: "手工读者夹具",
          reference_prices: prices,
          descriptive_labels: {
            status: "not_determined",
            reason: "no_settled_numeric_rule",
            labels: [],
            source: "fenxing.md:64-74",
            raw_ohlc: ["0", "1", "2"].map(rawBar),
          },
          subsequent_development: {
            status: "observed",
            reason: null,
            bars: [unitOf(rawBar("3"), null)],
          },
        },
      });
      return st;
    };
    await Q3.validateState(await reid(layout1WithFractal()), "s-session/3");
    for (const [axis, badVal] of [["open", "99999"], ["high", "99999"], ["low", "1"], ["close", "99999"]]) {
      const badLabel = layout1WithFractal();
      badLabel.snapshot.objects.find((r) => r.object_id === "obj3-fractal-layout1").payload.descriptive_labels.raw_ohlc[0][axis] = badVal;
      await assert.rejects(async () => Q3.validateState(await reid(badLabel), "s-session/3"), /事实中原始 OHLC 值与真实源记录不符/);
      const badSub = layout1WithFractal();
      badSub.snapshot.objects.find((r) => r.object_id === "obj3-fractal-layout1").payload.subsequent_development.bars[0] = unitOf({ ...rawBar("3"), [axis]: badVal }, null);
      await assert.rejects(async () => Q3.validateState(await reid(badSub), "s-session/3"), /事实中原始 OHLC 值与真实源记录不符/);
    }
    const unboundLabel = layout1WithFractal();
    unboundLabel.snapshot.objects.find((r) => r.object_id === "obj3-fractal-layout1").payload.descriptive_labels.raw_ohlc[2] = rawBar("4");
    await assert.rejects(async () => Q3.validateState(await reid(unboundLabel), "s-session/3"), /typed payload 使用未绑定的原始坐标/);
    const unboundSub = layout1WithFractal();
    unboundSub.snapshot.objects.find((r) => r.object_id === "obj3-fractal-layout1").payload.subsequent_development.bars[0] = unitOf(rawBar("4"), null);
    await assert.rejects(async () => Q3.validateState(await reid(unboundSub), "s-session/3"), /typed payload 使用未绑定的原始坐标/);
    for (const [rule, sourced] of [[NEW, true], [typed.W2_ARCHIVED_RULE, false]]) {
      const badBounded = build(rule, sourced);
      badBounded.snapshot.objects.find((r) => r.object_id === "obj3-fractal31p").payload.descriptive_labels.raw_ohlc[0].open = "99999";
      await assert.rejects(async () => Q3.validateState(await reid(badBounded), "s-session/3"), /事实中原始 OHLC 值与真实源记录不符/);
    }
  });
  await t.test("CC-004.inclusion_step 的 payload.incoming 原始 OHLC 篡改与未绑定坐标被拒绝", async () => {
    for (const [axis, badVal] of [["open", "99999"], ["high", "99999"], ["low", "1"], ["close", "99999"]]) {
      const badStep = structuredClone(base);
      badStep.snapshot.objects.find((r) => r.kind === "CC-004.inclusion_step").payload.incoming[axis] = badVal;
      await assert.rejects(async () => Q3.validateState(await reid(badStep), "s-session/3"), /事实中原始 OHLC 值与真实源记录不符/);
    }
    const badW2Step = build(NEW, true);
    badW2Step.snapshot.objects.find((r) => r.kind === "CC-004.inclusion_step").payload.incoming.open = "99999";
    await assert.rejects(async () => Q3.validateState(await reid(badW2Step), "s-session/3"), /事实中原始 OHLC 值与真实源记录不符/);
    const unboundStep = structuredClone(base);
    const step = unboundStep.snapshot.objects.find((r) => r.kind === "CC-004.inclusion_step" && !r.source_coords.includes("4"));
    step.payload.incoming = rawBar("4");
    step.fact_key = JSON.stringify(["CC-004.inclusion_step", "4"]);
    await assert.rejects(async () => Q3.validateState(await reid(unboundStep), "s-session/3"), /typed payload 使用未绑定的原始坐标/);
  });
  await t.test("W/2 同 kind 异槽位替代、非 pending 伪装 fact_removed 与同槽位生命周期重叠在完整 validateState 拒绝", async () => {
    const makeWithdrawnCoord4 = (forged) => {
      const st = build(NEW, true), curBatch = batchOf(st), oldBatch = structuredClone(curBatch);
      oldBatch.object_id = "obj3-batch31p-coord4";
      oldBatch.fact_key = JSON.stringify([oldBatch.kind, "4"]);
      oldBatch.source_coords = ["4"];
      oldBatch.input_refs = [rawRef("4")];
      oldBatch.payload.bar = rawBar("4");
      const u4 = unitOf(oldBatch.payload.bar, oldBatch.input_refs[0]);
      oldBatch.payload.entries[0].unit = u4;
      oldBatch.payload.entries[0].development = { root: [structuredClone(curBatch.payload.entries[0].unit), u4], count: "2" };
      Object.assign(oldBatch, {
        lifecycle: "withdrawn",
        withdrawn_generation: "5",
        withdrawal_reason: forged ? "superseded_by_revision" : "fact_removed",
        superseded_by: forged ? curBatch.object_id : null,
      });
      st.snapshot.withdrawn_objects.push(oldBatch);
      if (forged) st.snapshot.relations.push({ subject: curBatch.object_id, relation_type: "replaces", object: oldBatch.object_id });
      return st;
    };
    await Q3.validateState(await reid(makeWithdrawnCoord4(false)), "s-session/3");
    await assert.rejects(async () => Q3.validateState(await reid(makeWithdrawnCoord4(true)), "s-session/3"), /W2同kind替代槽位不符/);

    const dupIdState = build(NEW, true), dupActive = batchOf(dupIdState), dupWithdrawn = structuredClone(dupActive);
    dupActive.first_known_generation = dupActive.published_generation = "5";
    dupActive.first_known_cut = "cut-5";
    Object.assign(dupWithdrawn, {
      first_known_generation: "4",
      published_generation: "4",
      first_known_cut: "cut-4",
      lifecycle: "withdrawn",
      withdrawn_generation: "5",
      withdrawal_reason: "fact_removed",
      superseded_by: null,
    });
    dupIdState.snapshot.withdrawn_objects.push(dupWithdrawn);
    await assert.rejects(async () => Q3.validateState(await reid(dupIdState), "s-session/3"), /W2对象身份重复/);

    const makeBatchRevisionChain = () => {
      const st = build(NEW, true);
      const activeFractal = st.snapshot.objects.find((r) => r.object_id === "obj3-fractal31p");
      const priorFractal = structuredClone(activeFractal);
      priorFractal.object_id = "obj3-fractal31p-prior";
      priorFractal.payload.description = "手工读者旧分型";
      Object.assign(priorFractal, {
        first_known_generation: "4",
        published_generation: "4",
        first_known_cut: "cut-4",
        lifecycle: "withdrawn",
        withdrawn_generation: "5",
        withdrawal_reason: "superseded_by_revision",
        superseded_by: activeFractal.object_id,
      });
      Object.assign(activeFractal, { first_known_generation: "5", published_generation: "5", first_known_cut: "cut-5" });
      const activeBatch = batchOf(st), priorBatch = structuredClone(activeBatch);
      priorBatch.object_id = "obj3-batch31p-prior";
      priorBatch.payload.entries[0].fractal_object_id = priorFractal.object_id;
      Object.assign(priorBatch, {
        first_known_generation: "4",
        published_generation: "4",
        first_known_cut: "cut-4",
        lifecycle: "withdrawn",
        withdrawn_generation: "5",
        withdrawal_reason: "superseded_by_revision",
        superseded_by: activeBatch.object_id,
      });
      Object.assign(activeBatch, { first_known_generation: "5", published_generation: "5", first_known_cut: "cut-5" });
      st.snapshot.withdrawn_objects.push(priorFractal, priorBatch);
      st.snapshot.relations.push(
        { subject: activeFractal.object_id, relation_type: "replaces", object: priorFractal.object_id },
        { subject: activeBatch.object_id, relation_type: "replaces", object: priorBatch.object_id },
      );
      return st;
    };
    await Q3.validateState(await reid(makeBatchRevisionChain()), "s-session/3");

    const disguisedBatchRemoved = makeBatchRevisionChain();
    const priorBatch = disguisedBatchRemoved.snapshot.withdrawn_objects.find((r) => r.object_id === "obj3-batch31p-prior");
    Object.assign(priorBatch, { withdrawal_reason: "fact_removed", superseded_by: null });
    disguisedBatchRemoved.snapshot.relations = disguisedBatchRemoved.snapshot.relations.filter((r) => r.object !== "obj3-batch31p-prior");
    await assert.rejects(async () => Q3.validateState(await reid(disguisedBatchRemoved), "s-session/3"), /W2同槽位存在替代目标却按fact_removed撤回/);

    const overlapBatch = makeBatchRevisionChain();
    const oldOverlap = overlapBatch.snapshot.withdrawn_objects.find((r) => r.object_id === "obj3-batch31p-prior");
    const curOverlap = batchOf(overlapBatch);
    const oldFractal = overlapBatch.snapshot.withdrawn_objects.find((r) => r.object_id === "obj3-fractal31p-prior");
    Object.assign(oldFractal, { first_known_generation: "3", published_generation: "3", first_known_cut: "cut-3" });
    Object.assign(oldOverlap, { first_known_generation: "3", published_generation: "3", first_known_cut: "cut-3", withdrawn_generation: "5" });
    const curFractal = overlapBatch.snapshot.objects.find((r) => r.object_id === "obj3-fractal31p");
    Object.assign(curFractal, { first_known_generation: "4", published_generation: "4", first_known_cut: "cut-4" });
    Object.assign(curOverlap, { first_known_generation: "4", published_generation: "4", first_known_cut: "cut-4" });
    await assert.rejects(async () => Q3.validateState(await reid(overlapBatch), "s-session/3"), /W2同槽位对象生命周期重叠/);
  });
  await t.test("活动 development_batch 引用晚出生分型或晚出生前缀批记录在完整 validateState 拒绝", async () => {
    const lateFractal = build(NEW, true);
    const fractal = lateFractal.snapshot.objects.find((r) => r.object_id === "obj3-fractal31p");
    Object.assign(fractal, { first_known_generation: "5", published_generation: "5", first_known_cut: "cut-5" });
    await assert.rejects(async () => Q3.validateState(await reid(lateFractal), "s-session/3"), /单元批记录指向缺失分型/);

    const latePrefix = twoUnits();
    const firstBatch = latePrefix.snapshot.objects.find((r) => r.kind === "CC-007.development_batch" && r.source_coords[0] === "3");
    Object.assign(firstBatch, { first_known_generation: "5", published_generation: "5", first_known_cut: "cut-5" });
    await assert.rejects(async () => Q3.validateState(await reid(latePrefix), "s-session/3"), /单元序列引用晚于自身出生的单元/);
  });
});
