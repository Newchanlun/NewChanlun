# #1551 修订考古

基线：`6ba72e84c55aa6d65b11cc46b7288142f4fce62b`，PR #2065 的 `decision/1551` 头。分级 P；仅起草三个证据门，资金与权限待签项为空。检索于 2026-11-20，tracker 均为 Newchanlun/NewChanlun 并覆盖开放与已关票、标题/正文/评论；仓内路覆盖 `analysis/ docs/ .chanlun/`。以下列会改变裁定的命中；不是全仓穷举断言。

## Q1 · C：子义务如何定位证明原件

- Tracker：`gh issue list --search '"逐子义务" "原件" in:title,body,comments' --state all` 命中 #1551 OPEN。复搜 `gh issue list --search '"AT-18" "AT-14" in:title,body,comments' --state all --limit 30`，相关命中有 #1551、#1418、#1369。最新 [#1551 评论 7040728269](https://github.com/Newchanlun/NewChanlun/issues/1551#issuecomment-7040728269) 明言没有跨产品子义务定位协议。
- 仓内：`rg -n '逐子义务|US-ST-001.{0,120}US-ST-002|覆盖声明|原件定位' analysis/ docs/ .chanlun/`。命中基线 ADR 0064:25、发布切片 `.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB02-06-EXECUTION-SLICES.md:306-311`、旧取证索引 `.chanlun/review-results/issue1372-tb01c-20260913/reports/delivery-preparation/devskim-pr1451/review-package/ORIGINALS-INDEX.json:185`。发布切片有规范 ID 和局部证明范围；原件索引只能找到文件。附核已关 [#1359](https://github.com/Newchanlun/NewChanlun/issues/1359#issuecomment-5653549133) 区分直接贡献、共享基础设施和后续联合义务，ADR 0058:192-211 区分实际受测对象、类与行为，不允许 advisory/inconclusive 或跳过冒充 PASS。
- A 已裁部分：逐子义务、不跨类、证实实跑才销项。C 只标**声明与定位协议**，缺口去向为 `decision`。采用上游产出物内可机读声明，精确匹配规范 ID、切片、规范节点、类、profile；随后审其结果原件。按已核交付绑定产出者与字节，复用原有 `ArtifactRef`。观察端自行配表没有证据权；给 /1 报告加键违反封闭 schema；两者均不选。只由 TB-11 前置销项的既有通道保留。
- 实测依据：独审 `b22fd496` REPORT.md:15、:80、:86，US-ST-001/002 同引用时错误地双 VERIFIED，DST-01→DST-06 换件还未反映到产物。

## Q2 · B：squash 与纯报告尾部怎样复算产品等价

- Tracker：`gh issue list --search '"squash" "最终产品差异" in:title,body,comments' --state all` 命中 #1551 OPEN；`gh issue list --search '"squash" "关票" in:title,body,comments' --state all --limit 30` 的相关命中包括 #1551 OPEN、#1660 CLOSED、#1588 CLOSED。
- 仓内：`rg -n 'squash.{0,100}(差异|等价|CI)|最终产品差异|纯报告尾部' analysis/ docs/ .chanlun/`。命中基线 ADR 0064:17,31 和 `.chanlun/review-results/issue1626-closeout-20261026/README.md:7`（不同的 PR head 与 squash SHA，单列实际落地 CI）、`.chanlun/review-results/issue1737-deadline-sync-20261026/DEVSKIM-REVIEW.md:7`（PR head 与 squash SHA 分读）。补查 [#1359 已关票汇总](https://github.com/Newchanlun/NewChanlun/issues/1359#issuecomment-5653549133) 第 4 项，明确产品主线 CI、尾报告实际主线、树相等、旧扫描差别。
- A 已裁部分：`.sandcastle/docs/graph-engineering.md:237-241`「交付与关票」要求实际落地、最终差异独审和适用 CI，新代码补审、squash 不掩盖尾部；`.sandcastle/CODEX-CHILD.md:45-50,65,74` 允许同产品字节的报告尾部；`.sandcastle/delivery-bundle.ts:83-86,156-175,248-285,306-308` 已有逐路径前后 SHA 和 mode 口径。基线 ADR 0064:62(b) 只证明仓外引用的 source 已合入，不证明 CI 与独评覆盖。
- B 默认值：取真实落地主线与 PR/CI/独评原件。从实际 squash 父提交比较 PR head 和 squash 提交的完整产品前后字节与 mode，纯报告尾部仅认逐项核定的非产品差异；生成端和总验端各自复算。只核祖先关系不够；只认整树完全一致则会误拒已裁允许的纯报告尾部。主线 CI 仍须是实际主线运行。
- 实测依据：独审 REPORT.md:16、:82，旧祖先 `d4f14d7889` 到实际产品 `bc2efc7e72` 变更 `product.txt`，两旧证据仍误过。

## Q3 · B：自身已登记实体摘要何时阻断

- Tracker：`gh issue list --search '"manifest" "摘要不符" in:title,body,comments' --state all` 命中 #1551 OPEN；`gh issue list --search '"REPORT_HASH_MISMATCH" in:title,body,comments' --state all` 无命中；`gh issue list --search '"交付预检" "sha256" in:title,body,comments' --state all` 命中 #1527 OPEN，未给出 AT-18 引导例外。
- 仓内：`rg -n 'REPORT_HASH_MISMATCH|摘要不符|已登记.{0,16}摘要|引导前提' analysis/ docs/ .chanlun/` 命中基线 ADR 0064:59-61,67：自身清单可未登记本次产物，上游摘要失败为判定失败。补查 `.sandcastle/CODEX-CHILD.md:54-65` 和 `.sandcastle/delivery-bundle.ts:189-246,281,304,316-321`：版本及字节任一不符即阻断交付，已有 `REPORT_HASH_MISMATCH` 诊断；其阶段是交付预检。
- A 已裁部分：登记实体的摘要对不上不准交付。B 默认值：在 AT-18 引导第（1）步完成已登记实体的完整性检查，任何写入前用预检诊断阻断。本次产物尚未登记可引导；不提前要求完整交付清单。上游/受验清单仍按判定失败出具 FAIL 报告或回执。
- 实测依据：独审 REPORT.md:23、:83，合法 64 位全零的错误摘要与格式错误不同，原 CLI 仍以退出码 0 落盘。

独审复现源：`/Volumes/AgentStorage/issue1391-at18/non-author-astra-b22fd496/REPORT.md`（候选 `b22fd4960d6f18088f19ed7bb9c94144cf2ee3c4`）；关联公网条款与三个观察见 [#1551 最新评论](https://github.com/Newchanlun/NewChanlun/issues/1551#issuecomment-7040728269)。其余实现问题不作为本次正本改动。
