#!/usr/bin/env node
/* #1425 R3 方案 1：真实 Chrome CDP pipe 验证 economic-read-projection/1 与同切面取证。 */
"use strict";
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const args = Object.fromEntries(
  process.argv.slice(2).reduce((a, x, i, v) => (i % 2 ? a : [...a, [x, v[i + 1]]]), [])
);
const output = path.resolve(args["--output"]);
fs.mkdirSync(output, { recursive: true });
const chrome = args["--chrome"] || "/usr/bin/google-chrome";
const url = new URL(args["--url"]);
const mode = args["--mode"] || "full";
const cut5CutsPath = args["--cut5-cuts"];
const expectedJsonPath = args["--expected"];
if (url.hostname !== "127.0.0.1" || url.protocol !== "http:") {
  throw new Error("仅允许本机正式页面");
}
const expected = expectedJsonPath ? JSON.parse(fs.readFileSync(expectedJsonPath, "utf8")) : null;
const cut5Cuts = cut5CutsPath ? JSON.parse(fs.readFileSync(cut5CutsPath, "utf8")) : null;

const flags = [
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--disable-background-networking",
  "--disable-component-update",
  "--disable-sync",
  "--no-first-run",
  "--no-default-browser-check",
  "--window-size=1440,1200",
  "--remote-debugging-pipe",
  "--user-data-dir=" + path.join(output, "profile"),
  "about:blank",
];
fs.writeFileSync(
  path.join(output, "command.json"),
  JSON.stringify({ chrome, flags, url: url.href, mode }, null, 2)
);
const child = spawn(chrome, flags, {
  stdio: ["ignore", "pipe", "pipe", "pipe", "pipe"],
  env: { PATH: process.env.PATH, TMPDIR: output, HOME: output },
});
child.stdout.pipe(fs.createWriteStream(path.join(output, "chrome.stdout")));
child.stderr.pipe(fs.createWriteStream(path.join(output, "chrome.stderr")));
const log = fs.createWriteStream(path.join(output, "cdp.jsonl"));

let sequence = 0;
let buffer = Buffer.alloc(0);
let session;
const pending = new Map();
const consoleErrors = [];
const pageErrors = [];
const httpResponses = [];

child.stdio[4].on("data", (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  while (buffer.includes(0)) {
    const at = buffer.indexOf(0);
    const raw = buffer.subarray(0, at).toString();
    buffer = buffer.subarray(at + 1);
    const message = JSON.parse(raw);
    log.write(JSON.stringify({ direction: "received", message }) + "\n");
    if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
      consoleErrors.push(message.params);
    }
    if (message.method === "Runtime.exceptionThrown") {
      pageErrors.push(message.params);
    }
    if (
      message.method === "Network.responseReceived" &&
      message.params.response.url.includes("/api/economic/")
    ) {
      httpResponses.push({
        url: message.params.response.url,
        status: message.params.response.status,
      });
    }
    const waiter = pending.get(message.id);
    if (waiter) {
      pending.delete(message.id);
      clearTimeout(waiter.timer);
      message.error
        ? waiter.reject(new Error(JSON.stringify(message.error)))
        : waiter.resolve(message.result);
    }
  }
});
function failAll(error) {
  for (const w of pending.values()) {
    clearTimeout(w.timer);
    w.reject(error);
  }
  pending.clear();
}
child.on("error", failAll);
child.on("exit", (code, signal) => failAll(new Error("Chrome 退出 " + code + " / " + signal)));

function send(method, params = {}, target = session) {
  const id = ++sequence;
  const message = { id, method, params, ...(target ? { sessionId: target } : {}) };
  log.write(JSON.stringify({ direction: "sent", message }) + "\n");
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("CDP 超时 " + method));
    }, 30000);
    pending.set(id, { resolve, reject, timer });
    child.stdio[3].write(JSON.stringify(message) + "\0");
  });
}

async function evaluate(expression) {
  const r = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (r.exceptionDetails) {
    throw new Error("JS exception: " + JSON.stringify(r.exceptionDetails));
  }
  return r.result.value;
}

async function settle(predicate = "typeof client !== 'undefined' && client.state !== null && !busy") {
  const end = Date.now() + 30000;
  while (Date.now() < end) {
    if (await evaluate(predicate)) return;
    await new Promise((r) => setTimeout(r, 80));
  }
  const status = await evaluate("document.getElementById('status')?.textContent || ''");
  throw new Error("页面未稳定，status=" + status);
}

async function screenshot(name) {
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(path.join(output, name + ".png"), Buffer.from(shot.data, "base64"));
}

function assert(cond, msg) {
  if (!cond) throw new Error("ASSERTION FAILED: " + msg);
}

(async () => {
  try {
    const { targetId } = await send("Target.createTarget", { url: "about:blank" }, null);
    ({ sessionId: session } = await send("Target.attachToTarget", { targetId, flatten: true }, null));
    await send("Page.enable");
    await send("Runtime.enable");
    await send("Network.enable");
    await send("Page.navigate", { url: url.href });
    // R4：页面默认走完整快照（保留既有快照/Watch 入口）；在超大 cut 6 上应诚实报错（严格拒裸整数/超4MiB），
    // 同时探明 owner 支持投影后启用独立「读取固定切面投影」按钮。
    await settle("typeof client !== 'undefined' && client.discovery !== null && !busy");
    const initialState = await evaluate("({status: document.getElementById('status').textContent, watchDisabled: document.getElementById('watch').disabled, projDisabled: document.getElementById('projection-current').disabled, committed: client.state !== null})");
    assert(!initialState.projDisabled, "projection-current button must be enabled after real owner probe: " + JSON.stringify(initialState));
    assert(initialState.watchDisabled, "watch button must be disabled without CompleteVector snapshot: " + JSON.stringify(initialState));
    // 显式点击独立「读取固定切面投影」按钮切换到只读投影视图！
    await evaluate("document.getElementById('projection-current').click()");
    await settle("client.state !== null && client.state.kind === 'EconomicProjection' && !busy");
    const projWatchDisabled = await evaluate("document.getElementById('watch').disabled");
    assert(projWatchDisabled, "watch button must remain disabled in EconomicProjection view");
    const capText = await evaluate("document.getElementById('capabilities').textContent");
    assert(capText.includes("不支持 Watch"), "capabilities text must state Watch unsupported in projection: " + capText);

    const discovery = await evaluate("client.discovery");
    const cut6State = await evaluate("client.state");
    const cut6Dom = await evaluate("document.body.innerText");
    const readLogAfterCut6 = await evaluate("client.readLog");

    assert(discovery.read_projection && discovery.read_projection.schema_revision === "economic-read-projection/1"
      && discovery.read_projection.watch_supported === false,
      "discovery must advertise economic-read-projection/1 with watch_supported=false");
    assert(cut6State.kind === "EconomicProjection", "state.kind must be EconomicProjection");
    assert(cut6State.projection_revision === "economic-read-projection/1", "projection_revision mismatch");
    assert(cut6State.projection_completeness === "CompleteProjectionVector",
      "expected CompleteProjectionVector, got " + cut6State.projection_completeness);

    const alpha6 = cut6State.domains["B:alpha"];
    const beta4 = cut6State.domains["B:beta"];
    const e10 = cut6State.domains["E"];
    assert(e10.cut.commit_seq === "10" && alpha6.cut.commit_seq === "6" && beta4.cut.commit_seq === "4",
      "unexpected cut vector: " + JSON.stringify({ E: e10.cut, alpha: alpha6.cut, beta: beta4.cut }));
    assert(alpha6.authoritative_image_hash !== alpha6.projection_hash,
      "authoritative_image_hash must be distinct from projection_hash");
    // 指定会话按该次原账读数核对；无 --expected 时仍验最初的 R2 冻结样本。
    const alphaImageBytes = expected ? expected.b_alpha_cut6_image_bytes : 6821123;
    assert(Number.isSafeInteger(alphaImageBytes) && alphaImageBytes > 4194304
      && alpha6.authoritative_image_bytes === String(alphaImageBytes),
      "B:alpha cut 6 权威原像字节数与所选原账不符：" + alpha6.authoritative_image_bytes);
    assert(Number(alpha6.projection_bytes) < 120000,
      "B:alpha cut 6 projection_bytes should be ~70KB, got " + alpha6.projection_bytes);
    assert(alpha6.projection.book.actual_quantity === "6", "B:alpha cut 6 actual_quantity must be 6");
    assert(alpha6.projection.book.cost_totals.acquisition_cash === "80028", "acquisition_cash must be 80028");
    assert(alpha6.projection.book.cost_totals.fee_only === "1", "fee_only at cut 6 must be 1");
    assert(alpha6.projection.book.cost_basis.K === "80029", "K at cut 6 must be 80029");
    assert(beta4.projection.book.actual_quantity === "15" && beta4.projection.book.cost_basis.K === "80000" && beta4.projection.book.cost_totals.fee_only === "0",
      "B:beta cut 4 must be qty=15, K=80000, fee_only=0");
    assert(cut6Dom.includes("CompleteProjectionVector"), "DOM must explicitly display CompleteProjectionVector");
    assert(cut6Dom.includes(String(alphaImageBytes)), "DOM 须显示本会话的权威原像字节数");
    assert(cut6Dom.includes("80029"), "DOM must display K=80029");
    assert(cut6Dom.includes("保留总额") && cut6Dom.includes("90"), "DOM must display E 保留总额 90");

    const shotPrefix = mode === "post-restart" ? "04-after-restart-epoch4" : "01-cut6-projection";
    await screenshot(shotPrefix);

    const report = {
      mode,
      discovery,
      cut6: {
        projection_token: cut6State.projection_token,
        projection_completeness: cut6State.projection_completeness,
        domains: Object.fromEntries(
          Object.entries(cut6State.domains).map(([d, v]) => [
            d,
            {
              cut: v.cut,
              commit_ns: v.commit_ns,
              writer_epoch: v.writer_epoch,
              authoritative_image_hash: v.authoritative_image_hash,
              authoritative_image_bytes: v.authoritative_image_bytes,
              projection_hash: v.projection_hash,
              projection_bytes: v.projection_bytes,
              omitted_peer_images_count: v.omitted_peer_images.length,
            },
          ])
        ),
        alpha_book: {
          actual_quantity: alpha6.projection.book.actual_quantity,
          opening_quantity: alpha6.projection.book.opening_quantity,
          cost_totals: alpha6.projection.book.cost_totals,
          cost_basis: alpha6.projection.book.cost_basis,
          cost_remaining: alpha6.projection.book.cost_remaining,
          principal: alpha6.projection.book.principal,
          phase: alpha6.projection.book.phase,
        },
      },
      readLogAfterCut6,
    };

    if (mode === "full") {
      // 2. Click EVERY same-cut original expand button on cut 6 (one evaluate per button)!
      const buttonCount = await evaluate(`document.querySelectorAll("button[data-original-kind]").length`);
      assert(buttonCount >= 10, "expected >=10 same-cut original buttons, got " + buttonCount);
      const expandedOriginals = [];
      for (let idx = 0; idx < buttonCount; idx++) {
        const item = await evaluate(`(async () => {
          const btn = document.querySelectorAll("button[data-original-kind]")[${idx}];
          const t0 = performance.now();
          btn.click();
          const pre = btn.nextElementSibling;
          const end = Date.now() + 25000;
          while (Date.now() < end && (btn.disabled || pre.hidden)) {
            await new Promise(r => setTimeout(r, 40));
          }
          const txt = pre.textContent;
          let parsed = null;
          try { parsed = JSON.parse(txt); } catch (e) {}
          return {
            domain: btn.dataset.originalDomain,
            kind: btn.dataset.originalKind,
            id: btn.dataset.originalId,
            label: btn.textContent,
            elapsed_ms: Math.round(performance.now() - t0),
            ok: parsed !== null && parsed.kind === "EconomicProjectionOriginal",
            bytes: txt.length,
            original_kind: parsed?.original_kind || null,
            raw_sha256: parsed?.original?.raw_sha256 || parsed?.original?.fact?.raw_sha256 || null,
            model_content_hash: parsed?.original?.model_ref?.content_hash || null,
            error: parsed ? null : txt.slice(0, 200),
          };
        })()`);
        assert(item.ok, "same-cut original expand failed: " + JSON.stringify(item));
        expandedOriginals.push(item);
      }
      if (expected && expected.model_content_hash) {
        const modelItems = expandedOriginals.filter((x) => x.kind === "model");
        assert(modelItems.length >= 2, "expected >=2 model original buttons");
        for (const m of modelItems) {
          assert(m.model_content_hash === expected.model_content_hash,
            "model_content_hash mismatch: " + JSON.stringify(m));
        }
      }
      await screenshot("02-cut6-originals-expanded");
      report.expandedOriginalsCut6 = expandedOriginals;

      // 3. Switch to fixed historical cut 5 ([E:10, B:alpha:5, B:beta:4]) via UI input + button!
      assert(cut5Cuts !== null, "--cut5-cuts required in full mode");
      await evaluate(`(() => {
        document.getElementById("cuts-json").value = ${JSON.stringify(JSON.stringify(cut5Cuts))};
        document.getElementById("load-cuts").click();
      })()`);
      await settle("client.state && client.state.domains['B:alpha'].cut.commit_seq === '5' && !busy");
      const cut5State = await evaluate("client.state");
      const alpha5 = cut5State.domains["B:alpha"];
      assert(cut5State.mode === "AsKnown", "cut 5 must be AsKnown mode");
      assert(alpha5.cut.commit_seq === "5", "B:alpha must be at seq 5");
      assert(alpha5.projection.book.actual_quantity === "6", "B:alpha cut 5 qty must be 6");
      assert(alpha5.projection.book.cost_totals.acquisition_cash === "80028", "cut 5 acq cash must be 80028");
      assert(alpha5.projection.book.cost_totals.fee_only === "0", "cut 5 fee_only must be 0");
      assert(alpha5.projection.book.cost_basis.K === "80028", "cut 5 K must be 80028 (before causal fee)");
      await screenshot("03-cut5-before-fee");
      report.cut5 = {
        projection_token: cut5State.projection_token,
        alpha_cut: alpha5.cut,
        alpha_authoritative_image_bytes: alpha5.authoritative_image_bytes,
        alpha_projection_bytes: alpha5.projection_bytes,
        alpha_K: alpha5.projection.book.cost_basis.K,
        alpha_fee_only: alpha5.projection.book.cost_totals.fee_only,
      };

      // 4. Negative boundary checks directly inside real Chrome!
      const negatives = await evaluate(`(async () => {
        const res = {};
        const cut5State = client.state;
        try {
          await client.watch();
          res.watchOnProjection = { rejected: false };
        } catch (e) {
          res.watchOnProjection = { rejected: true, error: e.message };
        }
        try {
          await client.projectionOriginal(cut5State, "B:alpha", "fact", ${JSON.stringify(expected.fee_fact_key)});
          res.feeFactAtCut5 = { rejected: false };
        } catch (e) {
          res.feeFactAtCut5 = { rejected: true, error: e.message };
        }
        try {
          await client.projectionOriginal(cut5State, "B:alpha", "allocation", ${JSON.stringify(expected.fee_allocation_id)});
          res.feeAllocAtCut5 = { rejected: false };
        } catch (e) {
          res.feeAllocAtCut5 = { rejected: true, error: e.message };
        }
        if (${JSON.stringify(Boolean(expected && expected.e6_b6_b4_cuts))}) {
          const e6Cuts = ${JSON.stringify((expected && expected.e6_b6_b4_cuts) || null)};
          try {
            await client.query({
              op: "projection_original",
              projection_revision: "economic-read-projection/1",
              domain_id: "B:alpha",
              kind: "allocation",
              object_id: ${JSON.stringify(expected.fee_allocation_id)},
              cuts: e6Cuts,
            });
            res.e6VectorFeeAlloc = { rejected: false };
          } catch (e) {
            res.e6VectorFeeAlloc = { rejected: true, error: e.message };
          }
        }
        const badNonTargetCuts = JSON.parse(JSON.stringify(${JSON.stringify(cut5Cuts)}));
        badNonTargetCuts["B:beta"].root_hash = "0".repeat(64);
        try {
          await client.query({
            op: "projection_original",
            projection_revision: "economic-read-projection/1",
            domain_id: "B:alpha",
            kind: "fact",
            object_id: ${JSON.stringify(expected.fill_fact_key || expected.fee_fact_key)},
            cuts: badNonTargetCuts,
          });
          res.nonTargetBetaWrongRoot = { rejected: false };
        } catch (e) {
          res.nonTargetBetaWrongRoot = { rejected: true, error: e.message };
        }
        const badSeqCuts = JSON.parse(JSON.stringify(${JSON.stringify(cut5Cuts)}));
        badSeqCuts["B:alpha"].commit_seq = "99";
        try {
          const r = await client.loadProjection({ cuts: badSeqCuts });
          res.futureCut99 = {
            rejected: r.projection_completeness === "PartialProjectionVector" && r.domains["B:alpha"].status === "Unavailable",
            status: r.domains["B:alpha"].status,
            error: r.domains["B:alpha"].error || null,
          };
        } catch (e) {
          res.futureCut99 = { rejected: true, error: e.message };
        }
        const badRootCuts = JSON.parse(JSON.stringify(${JSON.stringify(cut5Cuts)}));
        badRootCuts["B:alpha"].root_hash = "0".repeat(64);
        try {
          const r = await client.loadProjection({ cuts: badRootCuts });
          res.wrongRootCut = {
            rejected: r.projection_completeness === "PartialProjectionVector" && r.domains["B:alpha"].status === "Unavailable",
            status: r.domains["B:alpha"].status,
            error: r.domains["B:alpha"].error || null,
          };
        } catch (e) {
          res.wrongRootCut = { rejected: true, error: e.message };
        }
        return res;
      })()`);
      // 旧 HTTP 正文与旧客户端能否解码是两件事。从同一次读取旁观分页，不改变客户端返回值。
      negatives.legacySnapshotCut6 = await evaluate(`(async () => {
        const chunks = [];
        class LegacyProbe extends TB03A.Client {
          async rpc(...args) {
            const page = await super.rpc(...args);
            if (page.kind === "EconomicReadPage") chunks.push(atob(page.data_base64));
            return page;
          }
        }
        const legacyClient = new LegacyProbe();
        let parserError = null;
        try { await legacyClient.load(); } catch (error) { parserError = error.message; }
        const bytes = Uint8Array.from(chunks.join(""), c => c.charCodeAt(0));
        const legacySnap = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
        return {
          parserError, committed: legacyClient.state !== null,
          kind: legacySnap.kind,
          completeness: legacySnap.completeness,
          alpha_status: legacySnap.domains["B:alpha"].status,
          alpha_error: legacySnap.domains["B:alpha"].error || null,
          e_status: legacySnap.domains["E"].status,
          beta_status: legacySnap.domains["B:beta"].status,
        };
      })()`);
      assert(negatives.watchOnProjection.rejected && negatives.watchOnProjection.error.includes("Watch"),
        "watchOnProjection must reject clearly: " + JSON.stringify(negatives.watchOnProjection));
      if (expected && expected.e6_b6_b4_cuts) {
        assert(negatives.e6VectorFeeAlloc.rejected && negatives.e6VectorFeeAlloc.error.includes("E:8"),
          "e6VectorFeeAlloc must reject E:8 under E:6 cut: " + JSON.stringify(negatives.e6VectorFeeAlloc));
      }
      assert(negatives.nonTargetBetaWrongRoot.rejected && negatives.nonTargetBetaWrongRoot.error.includes("B:beta"),
        "nonTargetBetaWrongRoot must reject non-target B:beta wrong root: " + JSON.stringify(negatives.nonTargetBetaWrongRoot));
      assert(negatives.feeFactAtCut5.rejected && negatives.feeFactAtCut5.error.includes("MissingDependency"),
        "feeFactAtCut5 must reject with MissingDependency: " + JSON.stringify(negatives.feeFactAtCut5));
      assert(negatives.feeAllocAtCut5.rejected && negatives.feeAllocAtCut5.error.includes("MissingDependency"),
        "feeAllocAtCut5 must reject with MissingDependency: " + JSON.stringify(negatives.feeAllocAtCut5));
      assert(negatives.futureCut99.rejected, "futureCut99 must reject: " + JSON.stringify(negatives.futureCut99));
      assert(negatives.wrongRootCut.rejected, "wrongRootCut must reject: " + JSON.stringify(negatives.wrongRootCut));
      assert(negatives.legacySnapshotCut6.kind === "EconomicSnapshot"
        && negatives.legacySnapshotCut6.completeness === "PartialVector"
        && negatives.legacySnapshotCut6.alpha_status === "Unavailable"
        && negatives.legacySnapshotCut6.alpha_error.includes("QueryBudgetExceeded")
        && !negatives.legacySnapshotCut6.alpha_error.includes("Open 字段"),
        "legacySnapshotCut6 must preserve PartialVector + QueryBudgetExceeded: " + JSON.stringify(negatives.legacySnapshotCut6));
      assert(!negatives.legacySnapshotCut6.committed
        && negatives.legacySnapshotCut6.parserError === "JSON 非法值；v2 整数必须使用精确文本",
        "旧客户端不能把含裸整数的旧正文当作可用账面");
      report.negatives = negatives;
    }

    report.readLogFinal = await evaluate("client.readLog");
    report.consoleErrorCount = consoleErrors.length;
    report.pageErrorCount = pageErrors.length;
    report.httpResponseCount = httpResponses.length;
    assert(consoleErrors.length === 0, "console errors detected: " + JSON.stringify(consoleErrors));
    assert(pageErrors.length === 0, "page errors detected: " + JSON.stringify(pageErrors));

    fs.writeFileSync(path.join(output, "browser_report.json"), JSON.stringify(report, null, 2));
    console.log("CHROME_CDP_OK", JSON.stringify({ mode, httpResponses: httpResponses.length, consoleErrors: 0, pageErrors: 0 }));
    child.kill("SIGTERM");
    process.exit(0);
  } catch (err) {
    console.error("CHROME_CDP_FAIL", err);
    try { child.kill("SIGKILL"); } catch {}
    process.exit(1);
  }
})();
