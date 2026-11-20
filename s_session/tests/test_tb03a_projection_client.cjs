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

  // Counterexample: E:6 / B:alpha:6 / B:beta:4 must reject E:8 receipt!
  const cutsE6 = { E: e6, "B:alpha": b6, "B:beta": beta4 };
  const stateE6 = makeProjectionState(discovery, cutsE6);
  await TB03A.verifyProjection(stateE6, discovery);
  await assert.rejects(
    TB03A.verifyProjectionOriginal(buildReply(cutsE6, stateE6), stateE6, discovery, "B:alpha", "allocation", "sim-command-fee:1"),
    /E:8.*晚于固定切面.*E:6/
  );

  // Positive case: E:10 / B:alpha:6 / B:beta:4 must succeed!
  const cutsE10 = { E: e10, "B:alpha": b6, "B:beta": beta4 };
  const stateE10 = makeProjectionState(discovery, cutsE10);
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
