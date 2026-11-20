#!/usr/bin/env node
/* #1425 R4：tb03a-client.js 单元与反例锁（E:6/B:alpha:6 拒 E:8、投影态拒旧 Watch、严格拒裸整数、能力发现校验）。 */
"use strict";
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");
const TB03A = require("../browser/tb03a-client.js");

function sha256Text(text) {
  return crypto.createHash("sha256").update(Buffer.from(text, "utf8")).digest("hex");
}

function sha256Canon(value) {
  return sha256Text(TB03A.canonical(value));
}

function makeCut(domain, seq, tag = "ok") {
  return { domain_id: domain, commit_seq: String(seq), root_hash: sha256Canon([domain, String(seq), tag]) };
}

function makeDiscovery(withProjection = true) {
  const base = {
    schema_revision: "economic-discovery/1",
    session_id: "sess-js-r4",
    session_generation: "1",
    producer_epoch: "1",
    manifest_hash: "a".repeat(64),
    domains: ["E", "B:alpha", "B:beta"],
    max_reply_bytes: "1048576",
    operation_timeout_ms: "10000",
    scope: "TestOnlyRecordedEconomics",
    configured: true,
    book_revision: "tb03c-book/1",
    finance_revision: "tb03b-finance/6",
    read_pages: {
      schema_revision: "economic-read-pages/1",
      owner_epochs: { E: "1", "B:alpha": "1", "B:beta": "1" },
    },
  };
  if (withProjection) {
    base.read_projection = {
      schema_revision: "economic-read-projection/1",
      transport_revision: "economic-read-pages/1",
      owner_epochs: { E: "1", "B:alpha": "1", "B:beta": "1" },
      original_kinds: ["fact", "allocation", "decision", "grant", "command", "model"],
      watch_supported: false,
      available_actions: ["projection", "projection_original"],
    };
  }
  return base;
}

function makeProjectionState(discovery, cuts) {
  const domains = {};
  for (const [domain, c] of Object.entries(cuts)) {
    const proj = {
      book: null,
      recorded: [],
      pending: [],
      applied: [],
      unmatched: [],
      history: [],
      finance: {
        schema_revision: "tb03b-finance/6",
        rights: [],
        decisions: [],
        slots: [],
        responsibilities: [],
        commands: [],
      },
    };
    const enc = TB03A.canonical(proj);
    domains[domain] = {
      status: "Available",
      projection_revision: "economic-read-projection/1",
      cut: c,
      commit_ns: c.commit_seq,
      writer_epoch: "1",
      audit_verified: true,
      authoritative_image_hash: sha256Canon(["auth", domain, c.commit_seq]),
      authoritative_image_bytes: "1024",
      projection_hash: sha256Text(enc),
      projection_bytes: String(Buffer.byteLength(enc, "utf8")),
      omitted_peer_images: [],
      projection: proj,
    };
  }
  const body = {
    kind: "EconomicProjection",
    projection_revision: "economic-read-projection/1",
    session_id: discovery.session_id,
    session_generation: discovery.session_generation,
    manifest_hash: discovery.manifest_hash,
    mode: "AsKnown",
    as_known_ns: null,
    domains,
    projection_completeness: "CompleteProjectionVector",
  };
  return { ...body, projection_token: "economic-projection-" + sha256Canon(body) };
}

test("R4 #2: verifyProjectionOriginal rejects E:8 Recorded under E:6 / B:alpha:6 / B:beta:4 vector", async () => {
  const discovery = makeDiscovery(true);
  const e6 = makeCut("E", 6);
  const e8 = makeCut("E", 8);
  const e10 = makeCut("E", 10);
  const b6 = makeCut("B:alpha", 6);
  const beta4 = makeCut("B:beta", 4);
  const rawFee = '{"kind":"fee","amount":1}';
  const rawSha = sha256Text(rawFee);

  const buildReply = (cuts, state) => ({
    kind: "EconomicProjectionOriginal",
    projection_revision: "economic-read-projection/1",
    session_id: discovery.session_id,
    session_generation: discovery.session_generation,
    manifest_hash: discovery.manifest_hash,
    cuts,
    domain_id: "B:alpha",
    original_kind: "allocation",
    object_id: "sim-command-fee:1",
    authoritative_image_hash: state.domains["B:alpha"].authoritative_image_hash,
    authoritative_image_bytes: state.domains["B:alpha"].authoritative_image_bytes,
    commit_ns: state.domains["B:alpha"].commit_ns,
    writer_epoch: "1",
    original: {
      kind: "EconomicAllocationAtCut",
      domain_id: "B:alpha",
      allocation_id: "sim-command-fee:1",
      receipt: { kind: "Applied", domain_id: "B:alpha", cut: b6 },
      fact_ref: { fact_key: "f".repeat(64), fact_hash: "e".repeat(64) },
      fact: {
        kind: "EconomicFactAtCut",
        domain_id: "B:alpha",
        fact_key: "f".repeat(64),
        fact_hash: "e".repeat(64),
        raw_sha256: rawSha,
        raw_utf8: rawFee,
        raw_exact_text: {
          representation: "ExactDecimalIntegerTextProjection",
          raw_sha256: rawSha,
          value: { kind: "fee", amount: "1" },
        },
        projected_record: {
          cut: e8,
          e_receipt: { kind: "Recorded", domain_id: "E", cut: e8 },
          e_resolution_proof: { receipt: { kind: "Resolved", domain_id: "E", cut: e10 } },
        },
        receipts: [
          { kind: "Recorded", domain_id: "E", cut: e8 },
          { kind: "Applied", domain_id: "B:alpha", cut: b6 },
        ],
      },
    },
  });

  // Counterexample: E:6 / B:alpha:6 / B:beta:4 must reject E:8 receipt in BOTH main projection and original!
  const cutsE6 = { E: e6, "B:alpha": b6, "B:beta": beta4 };
  const stateE6 = makeProjectionState(discovery, cutsE6);
  await TB03A.verifyProjection(stateE6, discovery);

  const leakyStateE6 = makeProjectionState(discovery, cutsE6);
  leakyStateE6.domains["B:alpha"].projection.recorded.push({
    fact_key: "f".repeat(64),
    fact_hash: "e".repeat(64),
    raw_sha256: rawSha,
    raw_utf8: rawFee,
    cut: e8,
    e_receipt: { kind: "Recorded", domain_id: "E", cut: e8 },
    e_resolution_proof: { receipt: { kind: "Resolved", domain_id: "E", cut: e10 } },
  });
  const leakyProjEnc = TB03A.canonical(leakyStateE6.domains["B:alpha"].projection);
  leakyStateE6.domains["B:alpha"].projection_hash = sha256Text(leakyProjEnc);
  leakyStateE6.domains["B:alpha"].projection_bytes = String(Buffer.byteLength(leakyProjEnc, "utf8"));
  const leakyBody = { ...leakyStateE6 };
  delete leakyBody.projection_token;
  leakyStateE6.projection_token = "economic-projection-" + sha256Canon(leakyBody);
  await assert.rejects(
    TB03A.verifyProjection(leakyStateE6, discovery),
    /MissingDependency.*E:8.*晚于固定切面.*E:6/
  );

  await assert.rejects(
    TB03A.verifyProjectionOriginal(buildReply(cutsE6, stateE6), stateE6, discovery, "B:alpha", "allocation", "sim-command-fee:1"),
    /E:8.*晚于固定切面.*E:6/
  );

  // Positive case: E:10 / B:alpha:6 / B:beta:4 must succeed for BOTH main projection (with E:8/E:10) and original!
  const cutsE10 = { E: e10, "B:alpha": b6, "B:beta": beta4 };
  const stateE10 = makeProjectionState(discovery, cutsE10);
  stateE10.domains["B:alpha"].projection.recorded.push({
    fact_key: "f".repeat(64),
    fact_hash: "e".repeat(64),
    raw_sha256: rawSha,
    raw_utf8: rawFee,
    cut: e8,
    e_receipt: { kind: "Recorded", domain_id: "E", cut: e8 },
    e_resolution_proof: { receipt: { kind: "Resolved", domain_id: "E", cut: e10 } },
  });
  const okProjEnc = TB03A.canonical(stateE10.domains["B:alpha"].projection);
  stateE10.domains["B:alpha"].projection_hash = sha256Text(okProjEnc);
  stateE10.domains["B:alpha"].projection_bytes = String(Buffer.byteLength(okProjEnc, "utf8"));
  const okBody = { ...stateE10 };
  delete okBody.projection_token;
  stateE10.projection_token = "economic-projection-" + sha256Canon(okBody);
  await TB03A.verifyProjection(stateE10, discovery);
  const ok = await TB03A.verifyProjectionOriginal(
    buildReply(cutsE10, stateE10),
    stateE10,
    discovery,
    "B:alpha",
    "allocation",
    "sim-command-fee:1"
  );
  assert.equal(ok.kind, "EconomicProjectionOriginal");
});

test("R4 #5: projection state rejects legacy watch() clearly, strict parser still rejects bare integers, and legacy discovery without read_projection works", async () => {
  const discovery = makeDiscovery(true);
  const cuts = { E: makeCut("E", 10), "B:alpha": makeCut("B:alpha", 6), "B:beta": makeCut("B:beta", 4) };
  const projState = makeProjectionState(discovery, cuts);
  const client = new TB03A.Client();
  client.discovery = discovery;
  client.state = projState;
  await assert.rejects(client.watch(), /只读投影视图不支持旧 Watch/);

  // Strict JSON parser must still reject bare integers
  assert.throws(() => TB03A.parse('{"amount": 28}'), /精确文本/);

  // Legacy discovery without read_projection (e.g., old FIN/6 owner) is accepted by discover()
  const legacyDisc = makeDiscovery(false);
  const legacyClient = new TB03A.Client({
    fetcher: async () => ({
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(ctrl) {
          ctrl.enqueue(new TextEncoder().encode(TB03A.canonical(legacyDisc)));
          ctrl.close();
        },
      }),
    }),
  });
  const got = await legacyClient.discover();
  assert.equal(got.read_projection, undefined);
  await assert.rejects(legacyClient.loadProjection(), /未声明 economic-read-projection\/1/);
});

test("R6 #1: dual-domain Watch advances 0/0->1/1, E-then-B, B-then-E, and still rejects truly out-of-bounds future receipt", async () => {
  const discovery = {
    schema_revision: "economic-discovery/1",
    session_id: "sess-r6-watch",
    session_generation: "1",
    producer_epoch: "1",
    manifest_hash: "c".repeat(64),
    domains: ["E", "B:alpha"],
    max_reply_bytes: "1048576",
    operation_timeout_ms: "10000",
    scope: "TestOnlyRecordedEconomics",
    configured: true,
  };
  const emptyImg = () => ({ book: null, recorded: [], pending: [], applied: [], unmatched: [], history: [] });
  const rawOpen = TB03A.canonical({ events: [{ event: "open", units: "4" }], receipt: { label: "Delivery note" } });
  const rawSha = sha256Text(rawOpen);
  const cutsBySeq = {
    E: { 0: makeCut("E", 0), 1: makeCut("E", 1), 2: makeCut("E", 2) },
    "B:alpha": { 0: makeCut("B:alpha", 0), 1: makeCut("B:alpha", 1), 2: makeCut("B:alpha", 2) },
  };
  const makeImages = (mode) => {
    const imgs = {
      E: { 0: emptyImg(), 1: emptyImg(), 2: emptyImg() },
      "B:alpha": { 0: emptyImg(), 1: emptyImg(), 2: emptyImg() },
    };
    const e1Rec = {
      fact_key: "1".repeat(64),
      fact_hash: "2".repeat(64),
      raw_sha256: rawSha,
      raw_utf8: rawOpen,
      cut: cutsBySeq.E[1],
      e_receipt: { kind: "Recorded", domain_id: "E", cut: cutsBySeq.E[1] },
    };
    if (mode === "paired_0_to_1" || mode === "e_then_b") {
      imgs.E[1].recorded.push({ ...e1Rec });
      imgs["B:alpha"][1].recorded.push({ ...e1Rec });
    } else if (mode === "b_then_e") {
      // B:1 PrepareDecision (no E dep); E:1 Reserve references B:alpha:1 prepared_cut.
      imgs["B:alpha"][1].history.push({ kind: "PrepareDecision", record: { decision_id: "d1", prepared_cut: cutsBySeq["B:alpha"][1] } });
      imgs.E[1].history.push({ kind: "Reserve", record: { grants: [{ grant_id: "g1", owner: "B:alpha", prepared_cut: cutsBySeq["B:alpha"][1] }] } });
    } else if (mode === "out_of_bounds" || mode === "invalid_seq") {
      // Negative control: B:1 embeds E:2 even though E only advanced to E:1!
      const future = mode === "invalid_seq" ? {...cutsBySeq.E[2], commit_seq: "1x"} : cutsBySeq.E[2];
      imgs.E[1].recorded.push({ ...e1Rec });
      imgs["B:alpha"][1].recorded.push({
        ...e1Rec,
        cut: future,
        e_receipt: { kind: "Recorded", domain_id: "E", cut: future },
      });
    }
    return imgs;
  };

  function makeStrictWatchClient(mode, frontiers, strictQuery = true) {
    const imgs = makeImages(mode);
    let currentFrontier = { ...frontiers[0] };
    const snapFor = (reqCuts) => {
      // Enforce Q's exact Invariant A on every snapshot request (refusing E:0 / B:1 when B:1 embeds E:1!).
      const eSeq = BigInt(reqCuts.E.commit_seq);
      const bSeq = BigInt(reqCuts["B:alpha"].commit_seq);
      const bImg = imgs["B:alpha"][Number(bSeq)];
      for (const rec of bImg.recorded) {
        if (strictQuery && rec.e_receipt && BigInt(rec.e_receipt.cut.commit_seq) > eSeq) {
          throw new Error(`MissingDependency：回执(E:${rec.e_receipt.cut.commit_seq})晚于固定切面(E:${eSeq})，拒绝未来回执（向量未就绪）`);
        }
      }
      const eImg = imgs.E[Number(eSeq)];
      for (const h of eImg.history) {
        for (const g of h.record?.grants || []) {
          if (g.prepared_cut && BigInt(g.prepared_cut.commit_seq) > bSeq) {
            throw new Error(`MissingDependency：回执(B:alpha:${g.prepared_cut.commit_seq})晚于固定切面(B:alpha:${bSeq})，拒绝未来回执（向量未就绪）`);
          }
        }
      }
      const domains = {};
      for (const d of discovery.domains) {
        const seq = Number(reqCuts[d].commit_seq);
        const img = imgs[d][seq];
        domains[d] = { status: "Available", cut: cutsBySeq[d][seq], commit_ns: String(seq), image: img, image_hash: sha256Canon(img) };
      }
      const body = {
        kind: "EconomicSnapshot",
        session_id: discovery.session_id,
        session_generation: discovery.session_generation,
        manifest_hash: discovery.manifest_hash,
        mode: "AsKnown",
        as_known_ns: null,
        domains,
        completeness: "CompleteVector",
      };
      return { ...body, snapshot_token: "economic-snapshot-" + sha256Canon(body) };
    };
    const watchFor = (afterCuts) => {
      const domains = {};
      for (const d of discovery.domains) {
        const from = Number(afterCuts[d].commit_seq);
        const to = currentFrontier[d];
        const ch = [];
        for (let s = from + 1; s <= to; s++) {
          const img = imgs[d][s];
          ch.push({ cut: cutsBySeq[d][s], image: img, image_hash: sha256Canon(img), commit_ns: String(s) });
        }
        domains[d] = { status: "Available", base_cut: cutsBySeq[d][from], next_cut: cutsBySeq[d][to], changes: ch };
      }
      return {
        kind: "EconomicWatch",
        session_id: discovery.session_id,
        session_generation: discovery.session_generation,
        manifest_hash: discovery.manifest_hash,
        domains,
      };
    };
    const c = new TB03A.Client();
    c.discovery = discovery;
    c.query = async (payload) => {
      if (payload.op === "snapshot") {
        const target = payload.cuts || { E: cutsBySeq.E[currentFrontier.E], "B:alpha": cutsBySeq["B:alpha"][currentFrontier["B:alpha"]] };
        const res = snapFor(target);
        if (!payload.cuts) {
          res.mode = "Current";
          delete res.snapshot_token;
          res.snapshot_token = "economic-snapshot-" + sha256Canon(res);
        }
        return res;
      }
      if (payload.op === "watch") return watchFor(payload.cuts);
      throw new Error("unexpected op: " + payload.op);
    };
    return { client: c, setFrontier: (f) => { currentFrontier = { ...f }; } };
  }

  // Positive 1: paired simultaneous 0/0 -> 1/1
  {
    const { client, setFrontier } = makeStrictWatchClient("paired_0_to_1", [{ E: 0, "B:alpha": 0 }]);
    const s0 = await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    assert.equal(s0.domains.E.cut.commit_seq, "0");
    assert.equal(s0.domains["B:alpha"].cut.commit_seq, "0");
    setFrontier({ E: 1, "B:alpha": 1 });
    const s1 = await client.watch();
    assert.equal(s1.domains.E.cut.commit_seq, "1");
    assert.equal(s1.domains["B:alpha"].cut.commit_seq, "1");
  }
  // Positive 2: E leads (0/0 -> 1/0), then B follows (1/0 -> 1/1)
  {
    const { client, setFrontier } = makeStrictWatchClient("e_then_b", [{ E: 0, "B:alpha": 0 }]);
    await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    setFrontier({ E: 1, "B:alpha": 0 });
    const mid = await client.watch();
    assert.equal(mid.domains.E.cut.commit_seq, "1");
    assert.equal(mid.domains["B:alpha"].cut.commit_seq, "0");
    setFrontier({ E: 1, "B:alpha": 1 });
    const end = await client.watch();
    assert.equal(end.domains.E.cut.commit_seq, "1");
    assert.equal(end.domains["B:alpha"].cut.commit_seq, "1");
  }
  // Positive 3: B leads (0/0 -> 0/1 Prepare), then E follows (0/1 -> 1/1 Reserve) AND paired 0/0 -> 1/1
  {
    const { client, setFrontier } = makeStrictWatchClient("b_then_e", [{ E: 0, "B:alpha": 0 }]);
    await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    setFrontier({ E: 0, "B:alpha": 1 });
    const mid = await client.watch();
    assert.equal(mid.domains.E.cut.commit_seq, "0");
    assert.equal(mid.domains["B:alpha"].cut.commit_seq, "1");
    setFrontier({ E: 1, "B:alpha": 1 });
    const end = await client.watch();
    assert.equal(end.domains.E.cut.commit_seq, "1");
    assert.equal(end.domains["B:alpha"].cut.commit_seq, "1");
  }
  // Negative: B:1 embeds E:2 when E only reached E:1 -> MUST fail with MissingDependency and retain 0/0!
  {
    const { client, setFrontier } = makeStrictWatchClient("out_of_bounds", [{ E: 0, "B:alpha": 0 }]);
    await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    setFrontier({ E: 1, "B:alpha": 1 });
    await assert.rejects(client.watch(), /MissingDependency.*E:2/);
    assert.equal(client.state.domains.E.cut.commit_seq, "0");
    assert.equal(client.state.domains["B:alpha"].cut.commit_seq, "0");
  }
  // The same malformed response is sent successfully this time; only the client may reject it.
  {
    const { client, setFrontier } = makeStrictWatchClient("out_of_bounds", [{ E: 0, "B:alpha": 0 }], false);
    await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    setFrontier({ E: 1, "B:alpha": 1 });
    await assert.rejects(client.watch(), /MissingDependency.*E:2/);
    assert.equal(client.state.domains.E.cut.commit_seq, "0");
    assert.equal(client.state.domains["B:alpha"].cut.commit_seq, "0");
  }
  {
    const { client, setFrontier } = makeStrictWatchClient("invalid_seq", [{ E: 0, "B:alpha": 0 }], false);
    await client.load({ cuts: { E: cutsBySeq.E[0], "B:alpha": cutsBySeq["B:alpha"][0] } });
    setFrontier({ E: 1, "B:alpha": 1 });
    await assert.rejects(client.watch(), {name: "Error", message: /整数不是规范文本/});
    assert.equal(client.state.domains["B:alpha"].cut.commit_seq, "0");
  }
});

test("R7: transfer vector, Voice records and unlisted cut paths at public exit", async (t) => {
  const discovery = makeDiscovery();
  const cuts = { E: makeCut("E", 10), "B:alpha": makeCut("B:alpha", 6), "B:beta": makeCut("B:beta", 4) };
  const raw = "{}";
  const build = (seq, mode = "transfer") => {
    const state = makeProjectionState(discovery, cuts);
    const view = state.domains["B:beta"];
    if (mode === "unlisted") {
      view.projection.finance.decisions.push({e_future_proof: {cut: makeCut("E", 12)}});
    } else if (["voice", "source-cost", "derived-cost"].includes(mode)) {
      view.projection.book = {chong_id: "beta", book_revision: discovery.book_revision,
        fixed_q: "1", operation_level: "1", actual_quantity: "0", opening_quantity: "0",
        income_book: {Pi: "0", A: "0", W: "0", R: "0"},
        cost_totals: {acquisition_cash: "0", commission: "0", fee_only: "0"},
        cost_basis: {K: "0"}, cost_remaining: {}, principal: {}, phase: {}};
      if (mode === "voice") {
        view.projection.book.voice = {records: [{opening_basis: {e_cut: makeCut("E", seq)}}]};
      } else {
        const cost = {derivation: {resolve_cut: makeCut("E", seq)}};
        if (mode === "source-cost") Object.assign(cost, {source_ref: "source-evidence", amount_text: "1"});
        view.projection.book.known_cost_components = [cost];
      }
    } else {
      view.projection.recorded.push({raw_utf8: raw, raw_sha256: sha256Text(raw),
        b_source_debit_proof: {domain_id: "B:alpha", receipt: {kind: "Applied", domain_id: "B:alpha",
          cut: makeCut("B:alpha", seq)}}});
    }
    view.projection_hash = sha256Canon(view.projection);
    view.projection_bytes = String(Buffer.byteLength(TB03A.canonical(view.projection)));
    delete state.projection_token;
    state.projection_token = "economic-projection-" + sha256Canon(state);
    return state;
  };
  for (const state of [build(6), build(10, "voice")]) {
    const unlisted = [];
    await TB03A.verifyProjection(state, discovery, unlisted);
    assert.deepEqual(unlisted, []);
  }
  await t.test("B:alpha:9 under B:alpha:6", () =>
    assert.rejects(TB03A.verifyProjection(build(9), discovery), /MissingDependency.*B:alpha:9/));
  await t.test("Voice E:12 under E:10", () =>
    assert.rejects(TB03A.verifyProjection(build(12, "voice"), discovery), /MissingDependency.*E:12/));
  await t.test("unlisted E:12 under E:10", () =>
    assert.rejects(TB03A.verifyProjection(build(6, "unlisted"), discovery), /MissingDependency.*E:12/));
  await t.test("source cost is opaque; derived cost is not", async () => {
    await TB03A.verifyProjection(build(12, "source-cost"), discovery);
    await assert.rejects(TB03A.verifyProjection(build(12, "derived-cost"), discovery), /MissingDependency.*E:12/);
  });
});

test("R6 #2/#3/#4: JS decoder allows source keys named receipt/cut/witness, enforces receipt domain ownership, and rejects 5-layer unknown witness fields", async (t) => {
  const discovery = makeDiscovery(true);
  const e10 = makeCut("E", 10);
  const b6 = makeCut("B:alpha", 6);
  const beta4 = makeCut("B:beta", 4);
  const cuts = { E: e10, "B:alpha": b6, "B:beta": beta4 };
  const sourceDoc = {
    events: [{ event: "open_chong", units: "4" }],
    receipt: { label: "Delivery note" },
    cut: { note: "user-cut-field" },
    e_cut: { note: "user-ecut" },
    witness: { author: "desk" },
  };
  const rawUtf8 = TB03A.canonical(sourceDoc);
  const rawSha = sha256Text(rawUtf8);
  const state = makeProjectionState(discovery, cuts);
  state.domains.E.projection.recorded.push({
    fact_key: "f".repeat(64),
    fact_hash: "e".repeat(64),
    raw_sha256: rawSha,
    raw_utf8: rawUtf8,
    event: { event: "open_chong", receipt: { label: "event note" }, cut: { bar: "1" } },
  });
  const projEnc = TB03A.canonical(state.domains.E.projection);
  state.domains.E.projection_hash = sha256Text(projEnc);
  state.domains.E.projection_bytes = String(Buffer.byteLength(projEnc, "utf8"));
  const stateBody = { ...state };
  delete stateBody.projection_token;
  state.projection_token = "economic-projection-" + sha256Canon(stateBody);

  // #2 Positive: source document containing receipt/cut/e_cut/witness passes verifyProjection AND verifyProjectionOriginal!
  await TB03A.verifyProjection(state, discovery);
  const factReply = {
    kind: "EconomicProjectionOriginal",
    projection_revision: "economic-read-projection/1",
    session_id: discovery.session_id,
    session_generation: discovery.session_generation,
    manifest_hash: discovery.manifest_hash,
    cuts,
    domain_id: "E",
    original_kind: "fact",
    object_id: "f".repeat(64),
    authoritative_image_hash: state.domains.E.authoritative_image_hash,
    authoritative_image_bytes: state.domains.E.authoritative_image_bytes,
    commit_ns: state.domains.E.commit_ns,
    writer_epoch: state.domains.E.writer_epoch,
    original: {
      kind: "EconomicFactAtCut",
      domain_id: "E",
      fact_key: "f".repeat(64),
      fact_hash: "e".repeat(64),
      raw_sha256: rawSha,
      json_pointer: "/events/0",
      raw_utf8: rawUtf8,
      raw_exact_text: { representation: "ExactDecimalIntegerTextProjection", raw_sha256: rawSha, value: sourceDoc },
      projected_record: state.domains.E.projection.recorded[0],
      fill_allocation_row: null,
      receipts: [{ kind: "Recorded", domain_id: "E", cut: e10 }],
    },
  };
  await TB03A.verifyProjectionOriginal(factReply, state, discovery, "E", "fact", "f".repeat(64));

  // #3 Negative: B:alpha allocation attaching a valid E receipt MUST be rejected!
  const bAllocBase = {
    kind: "EconomicProjectionOriginal",
    projection_revision: "economic-read-projection/1",
    session_id: discovery.session_id,
    session_generation: discovery.session_generation,
    manifest_hash: discovery.manifest_hash,
    cuts,
    domain_id: "B:alpha",
    original_kind: "allocation",
    object_id: "sim-command-fee:1",
    authoritative_image_hash: state.domains["B:alpha"].authoritative_image_hash,
    authoritative_image_bytes: state.domains["B:alpha"].authoritative_image_bytes,
    commit_ns: state.domains["B:alpha"].commit_ns,
    writer_epoch: state.domains["B:alpha"].writer_epoch,
    original: {
      kind: "EconomicAllocationAtCut",
      domain_id: "B:alpha",
      allocation_id: "sim-command-fee:1",
      applied_entry: { allocation_id: "sim-command-fee:1" },
      application: { allocation_id: "sim-command-fee:1" },
      receipt: { kind: "Applied", domain_id: "E", cut: e10 },
      fact_ref: { fact_key: "f".repeat(64), fact_hash: "e".repeat(64) },
      fact: null,
    },
  };
  await assert.rejects(
    TB03A.verifyProjectionOriginal(bAllocBase, state, discovery, "B:alpha", "allocation", "sim-command-fee:1"),
    /回执域与期望域不符/
  );
  // #3 Positive: fixing receipt domain to B:alpha succeeds!
  const bAllocOk = structuredClone(bAllocBase);
  bAllocOk.original.receipt = { kind: "Applied", domain_id: "B:alpha", cut: b6 };
  await TB03A.verifyProjectionOriginal(bAllocOk, state, discovery, "B:alpha", "allocation", "sim-command-fee:1");

  // #4 Negative: unknown key injected into any of the 5 witness/allocation layers MUST be rejected!
  const makeEAlloc = (mutate) => {
    const rep = {
      kind: "EconomicProjectionOriginal",
      projection_revision: "economic-read-projection/1",
      session_id: discovery.session_id,
      session_generation: discovery.session_generation,
      manifest_hash: discovery.manifest_hash,
      cuts,
      domain_id: "E",
      original_kind: "allocation",
      object_id: "sim-command-fee:1",
      authoritative_image_hash: state.domains.E.authoritative_image_hash,
      authoritative_image_bytes: state.domains.E.authoritative_image_bytes,
      commit_ns: state.domains.E.commit_ns,
      writer_epoch: state.domains.E.writer_epoch,
      original: {
        kind: "EconomicAllocationAtCut",
        domain_id: "E",
        allocation_id: "sim-command-fee:1",
        fill_allocation_row: {
          fact_key: "f".repeat(64),
          fact_hash: "e".repeat(64),
          evidence_id: "ev-1",
          allocations: [{ allocation_id: "sim-command-fee:1", chong_id: "alpha" }],
          x_execution_witness: {
            witness_revision: "x-sim-execution-witness/1",
            e_release_cut: e10,
            x_release_evidence: { protocol: "x-exact-authority/1", command_ref: { command_id: "cmd-alpha", command_hash: "a".repeat(64) } },
            x_execute_evidence: { claimed_ns: "2", reply: { protocol: "x-exact-authority/1", command_ref: { command_id: "cmd-alpha", command_hash: "a".repeat(64) } } },
          },
        },
        resolve_receipt: { kind: "Resolved", domain_id: "E", cut: e10 },
        fact_ref: { fact_key: "f".repeat(64), fact_hash: "e".repeat(64) },
        fact: null,
      },
    };
    mutate(rep.original.fill_allocation_row);
    return rep;
  };
  // #4 Positive: clean whitelisted payload succeeds
  const allocationOnly = structuredClone(discovery);
  allocationOnly.read_projection.original_kinds = ["allocation"];
  const verifyAllocation = (reply, d = allocationOnly) =>
    TB03A.verifyProjectionOriginal(reply, state, d, "E", "allocation", "sim-command-fee:1");
  await verifyAllocation(makeEAlloc(() => {}));
  await t.test("preserves authority_epoch in both receipts", () => verifyAllocation(makeEAlloc(r => {
    r.x_execution_witness.x_release_evidence.authority_epoch = "1";
    r.x_execution_witness.x_execute_evidence.reply.authority_epoch = "1";
  })));
  for (const location of ["release", "execute"]) {
    await t.test(`allocation-only cannot receive full ${location} command`, async () => {
      const full = makeEAlloc(r => {
        const w = r.x_execution_witness;
        for (const receipt of [w.x_release_evidence, w.x_execute_evidence.reply]) {
          receipt.command = receipt.command_ref;
          delete receipt.command_ref;
        }
      });
      await verifyAllocation(full, discovery);
      const w = full.original.fill_allocation_row.x_execution_witness;
      const other = location === "release" ? w.x_execute_evidence.reply : w.x_release_evidence;
      other.command_ref = other.command;
      delete other.command;
      await assert.rejects(verifyAllocation(full), /未声明字段.*command/);
    });
  }
  // #4 Five-layer mutations must ALL reject
  const mutations = [
    ["row", (r) => { r.review_new_label = "blue"; }],
    ["witness", (r) => { r.x_execution_witness.review_new_label = "blue"; }],
    ["release", (r) => { r.x_execution_witness.x_release_evidence.review_new_label = "blue"; }],
    ["execute", (r) => { r.x_execution_witness.x_execute_evidence.review_new_label = "blue"; }],
    ["reply", (r) => { r.x_execution_witness.x_execute_evidence.reply.review_new_label = "blue"; }],
  ];
  for (const [layer, fn] of mutations) {
    await assert.rejects(
      verifyAllocation(makeEAlloc(fn)),
      /白名单|未声明字段|未知字段/,
      `layer ${layer} must be rejected`
    );
  }
});
