/* #1789：Q3Values.Reader 区间验完即释放 proof.graph 的行为与内存上界锁。 */
"use strict";
const assert = require("node:assert/strict");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const root = path.resolve(__dirname, "../..");
const API = require(path.join(root, "s_session/browser/tb01c-client.js"));
const C = require(path.join(root, "s_session/browser/s-content-v3.js"));
const V = API.Q3.V;
const { proofNodes } = require("./q3_complete_fixture.cjs");

async function buildMockContentSource(plainObj, extraNodes = []) {
  const encoded = await C.encode(C.fromPlain(plainObj));
  const nodeMap = new Map();
  for (const n of extraNodes) nodeMap.set(n.root, n);
  for (const n of encoded.nodes) nodeMap.set(n.root, n);
  const graph = await C.GraphView.create([...nodeMap.values()]);
  const anchor = {
    kind: "projection",
    fixed_cut: {
      session_id: "sess-1789",
      session_generation: "1",
      cut_generation: "1",
      structure_cut: "cut-1",
      history_mode: "AsKnown",
      as_of_generation: "1",
      catalog_revision: "cat-1",
      rule_revision: "rule-1",
      profile_id: "p",
      profile_hash: "0".repeat(64),
      input_frontier: "0",
      index_frontier: "batch3-" + "0".repeat(64),
      seq_range: { from: "0", to: "0" },
      scope: { families: ["objects"] },
      catalog_evidence: encoded.ref,
    },
    cut_projection_digest: "qcut3-" + V.F(0x22, V.unhex(encoded.ref.root.slice(4))),
    projection_ref: encoded.ref,
  };
  const base = { nodes: nodeMap, graph, ref: encoded.ref };
  const cap = "a".repeat(64);
  const stats = { reqCount: 0, proofNodeCopies: 0 };
  async function request(req) {
    stats.reqCount++;
    const c = req.content_token ? req.content_token : req;
    const offset = BigInt(c.offset),
      limit = BigInt(c.limit);
    const target = graph.resolve(encoded.ref, c.path);
    const total = c.unit === "value" ? 1n : BigInt(target.extent);
    const end = offset + limit < total ? offset + limit : total;
    const done = end === total;
    let items;
    if (c.unit === "items") {
      items = [...graph.entries(target, offset, end)].map((e) =>
        target.kind === "object" ? { key: e.key, value_ref: e.value_ref } : e.value_ref,
      );
    } else if (c.unit === "bytes") {
      let hx = "";
      for (const b of graph.byteChunks(target, offset, end)) hx += Buffer.from(b).toString("hex");
      items = hx;
    } else {
      items = offset === 0n ? [target] : [];
    }
    const nodes = proofNodes(base, anchor, c.path, target, offset, end);
    stats.proofNodeCopies += nodes.length;
    let next_token = null;
    if (!done) {
      const tok = {
        token_schema: "s-content-token/1",
        anchor,
        path: c.path,
        target_ref: target,
        unit: c.unit,
        offset: end.toString(),
        limit: c.limit,
        issued_capture_digest: c.issued_capture_digest || cap,
      };
      tok.token_checksum = await C.tokenChecksum(tok);
      next_token = tok;
    }
    return {
      ok: true,
      anchor,
      path: c.path,
      target_ref: target,
      unit: c.unit,
      offset: offset.toString(),
      end: end.toString(),
      total: total.toString(),
      items,
      nodes,
      done,
      next_token,
      validated_capture_digest: cap,
    };
  }
  return { encoded, nodeMap, graph, anchor, request, stats };
}

if (process.env.Q3_RELEASE_GRAPH_PROBE === "1") {
  (async () => {
    const ancestorKey = "k".repeat(32768);
    const leaves = Array.from({ length: 600 }, (_, i) => "leaf-" + i);
    const src = await buildMockContentSource({ [ancestorKey]: leaves, flag: true });
    global.gc();
    global.gc();
    const before = process.memoryUsage();
    const reader = new V.Reader({
      anchor: src.anchor,
      request: src.request,
      check: () => {},
      accept: async () => {},
      store: async () => {},
      limit: 31,
    });
    const rootVal = reader.value(src.encoded.ref);
    await reader.complete(rootVal);
    const finished = await reader.finish();
    const flagVal = await (await rootVal.field("flag")).scalar();
    global.gc();
    global.gc();
    const after = process.memoryUsage();
    console.log(
      JSON.stringify({
        reqCount: src.stats.reqCount,
        uniqueNodes: src.nodeMap.size,
        proofNodeCopies: src.stats.proofNodeCopies,
        finishedUniqueNodes: finished.metrics.uniqueNodes,
        flagVal,
        heapDeltaBytes: after.heapUsed - before.heapUsed,
        arrayBuffersDeltaBytes: after.arrayBuffers - before.arrayBuffers,
        liveRetainedDeltaBytes: after.heapUsed + after.arrayBuffers - (before.heapUsed + before.arrayBuffers),
      }),
    );
    if (!reader.cache.size) throw new Error("keep reader alive");
  })().catch((e) => {
    console.error(e);
    process.exit(1);
  });
} else {
  const test = require("node:test");

  test("Reader 对全值域与跨片读取产出逐值一致结果并完成闭包核验", async () => {
    const jt = await C.encodeJSONText('{"inner_bool_f":false,"inner_bool_t":true,"k":"v"}');
    const sample = {
      b_true: true,
      b_false: false,
      nil: null,
      str: "alpha-beta-".repeat(25),
      num_text: "9007199254740993",
      arr: [true, false, null, "x", "y", "z", { nested: true }],
      embedded: C.refEdge(jt.ref),
    };
    const src = await buildMockContentSource(sample, jt.nodes);
    const stored = new Set();
    const reader = new V.Reader({
      anchor: src.anchor,
      request: src.request,
      check: () => {},
      accept: async () => {},
      store: async (n) => stored.add(n.root),
      limit: 2,
    });
    const rootVal = reader.value(src.encoded.ref);
    await reader.complete(rootVal);
    const finishedGraph = await reader.finish();
    assert.equal(finishedGraph.metrics.uniqueNodes, src.nodeMap.size);
    assert.equal(stored.size, src.nodeMap.size);
    assert.equal(reader.cache.size, src.nodeMap.size);

    assert.equal(await (await rootVal.field("b_true")).scalar(), true);
    assert.equal(await (await rootVal.field("b_false")).scalar(), false);
    assert.equal(await (await rootVal.field("nil")).scalar(), null);
    assert.equal(await (await rootVal.field("str")).scalar(), sample.str);
    assert.equal(await (await rootVal.field("num_text")).scalar(), sample.num_text);
    assert.equal(
      await (await rootVal.field("embedded")).scalar(),
      '{"inner_bool_f":false,"inner_bool_t":true,"k":"v"}',
    );
    const arr = [];
    for await (const item of (await rootVal.field("arr")).items()) {
      arr.push(
        item.kind === "object" ? { nested: await (await item.field("nested")).scalar() } : await item.scalar(),
      );
    }
    assert.deepEqual(arr, sample.arr);

    let canonical = "";
    for await (const c of V.canonicalChunks(rootVal)) canonical += c;
    let oracle = "";
    for await (const c of src.graph.renderChunks(src.encoded.ref)) oracle += c;
    assert.equal(canonical, oracle);
  });

  test("坏证明负控：篡改布尔tag、篡改节点哈希、缺失证明节点、缺失json_text内层、未全闭包finish均拒绝", async () => {
    const jt = await C.encodeJSONText('{"ok":true}');
    const sample = { flag: true, other: false, list: ["a", "b", "c"], embedded: C.refEdge(jt.ref) };
    const src = await buildMockContentSource(sample, jt.nodes);

    {
      const reader = new V.Reader({
        anchor: src.anchor,
        request: async (req) => {
          const rep = await src.request(req);
          if (req.unit === "value") rep.nodes = rep.nodes.map((n) => (n.tag === "02" ? { ...n, tag: "01" } : n));
          return rep;
        },
        check: () => {},
        accept: async () => {},
        store: async () => {},
        limit: 2,
      });
      const bv = await reader.value(src.encoded.ref).field("flag");
      await assert.rejects(() => bv.scalar(), /s-content\/1: node hash/);
    }

    {
      const reader = new V.Reader({
        anchor: src.anchor,
        request: async (req) => {
          const rep = await src.request(req);
          if (req.path && req.path.length === 1 && req.path[0].field === "list") {
            rep.nodes = rep.nodes.map((n, i) =>
              i === 0 ? { ...n, body_hex: (n.body_hex[0] === "0" ? "1" : "0") + n.body_hex.slice(1) } : n,
            );
          }
          return rep;
        },
        check: () => {},
        accept: async () => {},
        store: async () => {},
        limit: 2,
      });
      const lv = await reader.value(src.encoded.ref).field("list");
      await assert.rejects(async () => {
        for await (const _ of lv.items()) {}
      }, /s-content\/1: node hash/);
    }

    {
      const reader = new V.Reader({
        anchor: src.anchor,
        request: async (req) => {
          const rep = await src.request(req);
          if (req.path && req.path.length === 1 && req.path[0].field === "list") {
            rep.nodes = rep.nodes.filter((n) => n.root !== rep.target_ref.root);
          }
          return rep;
        },
        check: () => {},
        accept: async () => {},
        store: async () => {},
        limit: 2,
      });
      const lv = await reader.value(src.encoded.ref).field("list");
      await assert.rejects(async () => {
        for await (const _ of lv.items()) {}
      }, /s-content\/1: missing node|field membership missing/);
    }

    {
      const reader = new V.Reader({
        anchor: src.anchor,
        request: async (req) => {
          const rep = await src.request(req);
          if (req.unit === "value") {
            const jtNode = rep.nodes.find((n) => n.tag === "07");
            if (jtNode) {
              const innerRoot = "sc1-" + jtNode.body_hex.slice(0, 64);
              rep.nodes = rep.nodes.filter((n) => n.root !== innerRoot);
            }
          }
          return rep;
        },
        check: () => {},
        accept: async () => {},
        store: async () => {},
        limit: 2,
      });
      const jv = await reader.value(src.encoded.ref).field("embedded");
      await assert.rejects(() => jv.scalar(), /s-content\/1: missing node/);
    }

    {
      const reader = new V.Reader({
        anchor: src.anchor,
        request: src.request,
        check: () => {},
        accept: async () => {},
        store: async () => {},
        limit: 2,
      });
      const rootVal = reader.value(src.encoded.ref);
      await rootVal.field("flag");
      await assert.rejects(() => reader.finish(), /s-content\/1: missing node/);
    }
  });

  test("重复共享证明路径的大批量读取释放每区间图，活堆增幅与唯一原件规模同阶而非乘以请求数", () => {
    const raw = execFileSync(process.execPath, ["--expose-gc", __filename], {
      encoding: "utf8",
      env: { ...process.env, Q3_RELEASE_GRAPH_PROBE: "1" },
      timeout: 60000,
    });
    const m = JSON.parse(raw.trim());
    assert.equal(m.flagVal, true);
    assert.equal(m.finishedUniqueNodes, m.uniqueNodes);
    assert(m.reqCount >= 600, `expected >= 600 content requests, got ${m.reqCount}`);
    assert(
      m.proofNodeCopies > m.uniqueNodes * 5,
      `expected heavy proof repetition, got ${m.proofNodeCopies} vs ${m.uniqueNodes}`,
    );
    const limitBytes = 12 * 1024 * 1024;
    assert(
      m.liveRetainedDeltaBytes < limitBytes,
      `live retained delta (${(m.liveRetainedDeltaBytes / 1048576).toFixed(2)} MiB; heap=${(m.heapDeltaBytes / 1048576).toFixed(2)} MiB, arrayBuffers=${(m.arrayBuffersDeltaBytes / 1048576).toFixed(2)} MiB) exceeded ${limitBytes / 1048576} MiB bound over ${m.reqCount} requests (${m.proofNodeCopies} proof node copies, ${m.uniqueNodes} unique nodes)`,
    );
  });
}
