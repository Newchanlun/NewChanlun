/* 使用真实 HTTP 全应答校验浏览器结构访问器；不自行拼接/裁剪账本对象。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const TB03A = require("../../s_session/browser/tb03a-client.js");

async function main() {
  // The test archive also contains legacy owner snapshots with bare integers. Inspect
  // their shape without weakening the production parser or rewriting their values.
  const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const discovery = fixture.discovery;
  const projection = fixture.public.find(({doc}) => doc.kind === "EconomicProjection").doc;
  const snapshot = fixture.public.find(({label}) => label === "read/snapshot/")?.doc;
  for (const {label, doc, vector} of fixture.public) {
    assert.deepEqual(TB03A.protocolCutCoverage(doc, vector, discovery.domains), [], label);
    if (label === "snapshot/snapshot/") await TB03A.verifySnapshot(doc, discovery);
    if (label === "read/snapshot/") assert.throws(() => TB03A.parse(JSON.stringify(doc)), /整数必须使用精确文本/);
    if (doc.kind === "EconomicProjection") await TB03A.verifyProjection(TB03A.parse(JSON.stringify(doc)), discovery);
    if (doc.kind === "EconomicOriginal") await TB03A.verifyOriginal(doc, snapshot, discovery, doc.domain_id, "decision", "alpha");
    if (doc.kind === "EconomicProjectionOriginal") {
      await TB03A.verifyProjectionOriginal(TB03A.parse(JSON.stringify(doc)), projection, discovery, doc.domain_id, doc.original_kind, doc.object_id);
    }
    console.log("BROWSER_CUT_COVERAGE", label);
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
