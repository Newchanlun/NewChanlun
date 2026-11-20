# #1551 · ADR 0064 修订送审稿

## 问题

#1391 候选 `b22fd4960d6f18088f19ed7bb9c94144cf2ee3c4` 的非作者复现发现三处合同缝隙：与子义务不相干的证据可以销项；CI 和独评在产品改动之前的祖先上仍过门；自身清单已登记实体的错误摘要仍能落盘。只修这三处，#1279 仍保持 OPEN，不改变现有业务与硬门判据。

## 权威依据

1. [#1551 最新评论](https://github.com/Newchanlun/NewChanlun/issues/1551#issuecomment-7040728269) 列三处修订范围。独审报告 REPORT.md:15-16,23,75-86 说明受控反例与合同时序。
2. [#1340](https://github.com/Newchanlun/NewChanlun/issues/1340) 正文 AT-18、[#1391](https://github.com/Newchanlun/NewChanlun/issues/1391) 的验收与「证明与销项范围」，要求逐子义务真实验收且不得扩大射程。ADR 0058:192-211 的 AT-14 先例区分受测对象、证据类和结果。
3. `.sandcastle/docs/graph-engineering.md:237-241` 规定实际主线、终态独审、评审后新代码补审与 squash 约束。`.sandcastle/CODEX-CHILD.md:45-50,65,74` 和 `.sandcastle/delivery-bundle.ts:83-86,156-175,248-285,306-308` 给出产品差异、权限与报告尾部先例。[#1359 的关票回执](https://github.com/Newchanlun/NewChanlun/issues/1359#issuecomment-5653549133) 第 4 项给出实际主线与同树对照实例。
4. `.sandcastle/CODEX-CHILD.md:54-63` 规定仓外 manifest 的版本、字节和文件类型约束；`.sandcastle/delivery-bundle.ts:189-246` 已定义 `REPORT_HASH_MISMATCH` 等诊断。`docs/agents/doctrine-rules.md:43-55` 禁止严格判据失败后以宽松判据放行。

## 候选

- Q1：采用上游产生的可复核子义务声明。原件共享合法，逐个证明键不可互换。拒绝观察端 scope、自报确认与仅引用路径；保留 ADR 0058 原件及 TB-11 共同输入包例外。
- Q2：沿用既有最终差异和实际 main 的要求。选真实 GitHub 落地映射及 Git 产品差异复算；需比较集合、字节及 mode。拒绝把祖先当等价，也不因真正纯报告尾部而拟制产品变化。
- Q3：沿用已登记实体的摘要门，移到 AT-18 自身清单引导。等到封包才拦会留下错误产物；在引导执行完整交付预检会挡住合法空引导清单。

## 裁定

1. 从冻结规范取得应核项。逐项接受可机读、精确匹配且能从真实记录复核的覆盖原件；缺证及排除不能销项。等价性与覆盖均由 #1403 从证据原件独立复算。
2. CI 与独评必须覆盖实际落地产品。提交不同时按真实 PR 记录、共同 squash 父提交和完整产品差异复算，仅排除经核定的纯报告尾部；适用主线 CI 不以 PR CI 顶替。
3. 自身清单已登记实体在引导时即校验完整字节。摘要不符为 `BLOCKED`、退出 1、不写文件；未登记本次产物仍可引导，受验对象不符按原流程写 FAIL。

正本落点：docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md

## 验收清单

- [ ] 在 #1391 实现运行 `at18_coverage_scope`：同一报告只证明 001、排除 002 或仅覆盖错误 Destination，必须拒收不涵盖的子义务。同时证明两条时可共享；TB-11-only 的证据仍可仅用共同输入包。
- [ ] 运行 `at18_final_product_binding`：旧祖先到落地产品存在差异时 CI 和独评均不可计；已核 squash 的相同产品差异与真实主线 CI 可通过，mode/构建输入差异不可豁免。
- [ ] 运行 `at18_own_manifest_bootstrap_digest`：实际 CLI 对 64 个零的错误 SHA 退出 1，带 `REPORT_HASH_MISMATCH` 且输出目录不增不改。正确摘要或未登记本次产物可继续；只污染受验对象产出结构化 FAIL。
- [x] 修订稿静态验收：以仓内 `.sandcastle/canonical-edit.mts` 对固定基线解析并重放唯一 `canonical_edit`，结果与提交中的 ADR blob 字节相同，且改动只触及头部、第五节三项门与验收。运行用例归 #1391/#1403，修订分支不改实现。

## 受影响票与 blocking 边变化

| 票 | 处置 | 边变化 |
|---|---|---|
| #1551 / PR #2065 | 当前分支只供非作者独审，主控持有是否并入和裁定登记 | 无 |
| #1391、#1403 | 分别实现/复算三处门及验收；两票原封包顺序不变 | 无 |
| #1369、#1340、#1323、#1279 | 保留原关图顺序与开放义务 | 无 |
| 上游实施子片（含 #1418） | 使用现有交付链提供与各自子义务对应的证据；AT-14 既有 schema 与路径不变 | 无 |

## 授权引用

本条依 #1909 代理独审裁定。#1551 已分为 P 类，不代签资金、交易、账户、权限或凭据。修订候选须由主控送异家族非作者独审，当前不改票、PR 或主线。

## 引用自证

| 引用 | 回查 |
|---|---|
| #1551 全评论、#1391、#1909 批准门 | `gh issue view 1551 --comments` 与 `gh issue view 1391/1909` 分别读取；最新评论号 `7040728269` |
| #1340 AT-18、#1279 | `gh issue view 1340 --json body`；`gh issue view 1279 --json state` 为 OPEN |
| #1359 已关票 | `gh api repos/Newchanlun/NewChanlun/issues/comments/5653549133`，内容第 2、4 项确认部分覆盖与实际落地 CI |
| 仓内规则、AT-14、报告与差异 | `git show 6ba72e84c5:<path>` 按前列位置读取；review REPORT.md 以本地保存的精确候选为准 |
| 三行头 | ADR 0059–0063 第 3–5 行；保留 #2065 的正式门措辞，补 2026-11-20 修订日期与 #1391 两实现文件 |

## 考古对照

| 点 | 类 | 采用 |
|---|---|---|
| Q1 | C | 新定覆盖原件定位协议；旧证据类、子义务与 AT-14 拒收门直接沿用 |
| Q2 | B | 沿用评审和 CI 最终差异门；补实际提交及产品等价复算法 |
| Q3 | B | 沿用实体摘要不符即阻断；补自身清单引导阶段和无文件结果 |

```canonical_edit
{"version":1,"operation":"edit","path":"docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md","replacements":[{"before":"> 最后裁定：以 PR #2065 合入 head 的正式门 `deepagents/review` 双审 PASS 为准（#1551，P 类，依 #1909 代理独审裁定，ADR 0041:41）\n> 受影响代码清单：本 ADR 不直接改代码；报告生成与独立总验归 #1391 与 #1403，TB-07 汇总归 #1366，AT-14 原件归 #1418。","after":"> 最后裁定：以 PR #2065 合入 head 的正式门 `deepagents/review` 双审 PASS 为准（#1551，2026-11-20 修订，P 类，依 #1909 代理独审裁定，ADR 0041:41）\n> 受影响代码清单：`.sandcastle/at18-report.ts`、`.sandcastle/at18-report.mts`。实施归 #1391；独立总验归 #1403，TB-07 汇总归 #1366，AT-14 原件归 #1418。"},{"before":"（1）读取本票仓外 delivery manifest（此时可尚未登记本次产物），它须可读且通过 `deliveryManifestSchema` 校验","after":"（1）读取本票仓外 delivery manifest（此时可尚未登记本次产物），它须可读且通过 `deliveryManifestSchema` 校验，并通过本步下列已登记实体校验"},{"before":"`MANIFEST_UNREADABLE` 或 `INVALID_MANIFEST`、`FIXED_ITEM_UNAVAILABLE`","after":"`MANIFEST_UNREADABLE`、`INVALID_MANIFEST` 或本步的实体预检诊断，其余依次为 `FIXED_ITEM_UNAVAILABLE`"},{"before":"- **派生值**。","after":"  - 引导第（1）步校验本票 manifest 中**已登记**的实体。逐项检查 `reports[]` 以及 `reviews[].report`、`checks[].evidence`、`scan.evidence`、`scan.disclosure.triage` 的已有引用。按 `.sandcastle/CODEX-CHILD.md:54-63` 和 `.sandcastle/delivery-bundle.ts:189-246` 核完整声明与存储、路径、普通文件、可读性和版本绑定。仓内实体从自身 manifest 的 `head` 读 Git blob，不用当前工作树替代；仓外实体按 `externalReportsRoot` 和本票 `ticket/base/head` 读取。两者均重算完整文件字节的 SHA-256，与登记值精确比较。路径、版本、实体或登记引用不合法时用相应的预检诊断；摘要数值不符用 `REPORT_HASH_MISMATCH`。任一失败走第（1）步的 `BLOCKED`，退出码 `1`。在任何临时或正式产物写入前返回，不创建、改名或覆盖文件；#1391 的输入包、报告及 `summary.md` 均不写，#1403 的回执也不写。\n  - 未登记本次待生成产物的清单仍可引导。不在引导阶段要求待生成产物或执行完整交付预检；封包关票仍按第三节运行完整预检。上游或受验清单的实体摘要不符不是自身清单引导失败，按本节判定规则使报告或回执为 `\"FAIL\"`。\n- **派生值**。"},{"before":"共用子记录封闭类型定义如下","after":"以下两条分别是子义务证据与最终产品版本取通过的必要条件。#1403 对两条均独立复核。\n\n- **子义务覆盖以产出方的机器记录为准**。#1391 从输入包绑定的 crosswalk、SPEC、覆盖输入和同一 `head` 上已批准的切片验收记录取应核子义务。故事、family、细项分别用其规范 ID，Destination 用 `DST-01..DST-06`。逐一核本条目实际承担的验收项、关闭切片和适用证据槽；一条记录须做数项检查时，逐项核对，不能由其中一项代过。观察输入和声明射程不能增删应核项。\n  - 供 AT-18 销项的原件须含可机读覆盖记录。采用独立的 `at18-evidence-scope/1` JSON 产物：顶层为 `{schema_version: \"at18-evidence-scope/1\", claims: Claim[]}`；每条 `Claim` 固定为 `{kind, id, slice_id, obligation, evidence_class, profile_id, result, records}`。`kind` 取 `story|family|detail|destination`；`id` 为该类的规范 ID；`slice_id` 为该子义务的关闭切片 ID，仅无切片的 Destination 子义务取 `null`。`obligation={path,sha256,pointer}` 定位上述应核规范的具体 JSON 节点，`path` 为仓内相对路径，`sha256` 为输入包 `head` 上该 Git blob 的字节摘要，`pointer` 为 RFC 6901 JSON Pointer；节点有多项判据时全核。`evidence_class` 取本 ADR 的三值，`profile_id` 取受测 profile 的精确 ID，无 profile 的义务才取 `null`。`result` 取 `VERIFIED|PRESERVED_BOUNDARY|BOUNDED_DEFERRED|EXCLUDED`。`records` 是 `{artifact: ArtifactRef, pointer: string}[]`，定位实际结果原件及其 JSON 节点；除 `EXCLUDED` 外须非空，不得指回覆盖声明或 AT-18 的报告、回执。声明以 `kind/id/slice_id/obligation/evidence_class/profile_id` 为键，覆盖原件按本节「派生值」的严格 JSON 规则读取，所有对象拒收未列键，同一原件内重复声明键拒收。\n  - 覆盖原件由负责该子义务的上游执行方随实际结果封包，随该票交付按第三节验收；已定仓内原件（如 ADR 0058 的 AT-14）保留各自 schema 和路径，由覆盖原件指向其真实结果。生成器和总验器均按本节 `ArtifactRef` 规则核覆盖原件与实际结果原件，按各原件已定合同校验内部 schema 与内容摘要（适用时），复核其来源票、记录身份、证据类、受测 profile 与适用的正本判据。只有键精确命中且定位的原件记录及其受测运行上下文共同证实所报结论时才计入覆盖。同一子义务、同一次运行的声明互相矛盾时不得选择其中的通过声明。摘要正确、路径相同、总报告写 PASS、观察填 `CONFIRMED`、`bounded_scope` 自述或单独维护的对账索引均不能代替该证明。声明缺失、排除、与原件冲突或原件无法定位时，该引用不支持当前子义务；对缺少支持的子义务记 `COVERAGE_SCOPE`，在 `scope` 写条目 ID、关闭切片与槽位，在 `detail` 写规范定位和失败原因，所在条目按本节判定规则失败。本条按 ADR 0058「AT-14 实体报告」的口径区分受测对象与行为结果，不改其判据。\n  - 同一覆盖原件可以含多条不同键的声明。#1391 把支持本条目的覆盖原件写入原有 `evidence_refs` 或 Destination 的 `evidence_by_class` 对应槽，专用原件引用仍填写专用槽；包及所引仓外原件的 manifest 按本节规则进入 `external_manifests[]`。#1403 从报告引用、输入包和原件重新定位并逐项验证，不以观察文件或报告状态代证。三份 AT-18 产物的封闭键集不变。仅由 `SpecCoverageLedger` 已定的 TB-11 前置门承接的子义务继续用共同输入包证明。具名延期与排除仍按 `SpecCoverageLedger` 原判据分别取证，不把 `EXCLUDED` 当成 `PRESERVED_BOUNDARY`，也不把被排除的运行当成通过或延期。\n\n- **适用 CI 与最终独评绑定到实际落地差异**。沿用 [交付与关票](../../.sandcastle/docs/graph-engineering.md#交付与关票) 和 [一次收齐交付材料](../../.sandcastle/CODEX-CHILD.md#一次收齐交付材料)。按 Destination、TB 和它们的必需实施子片，取各票实际交付的 `main_sha` 及其冻结交付范围；多票汇总不以其他子片的绿灯覆盖本片。对每个适用必需检查，从冻结工作流及分支必需检查规则确定应有项，以 GitHub 原件核对仓库、workflow、run ID、实际 `head_sha` 和应执行的检查结果。要求 `SUCCESS`，缺跑或跳过必需检查不算成功。对每次独评，从已验收的审查原件核对非作者身份、`reviewed_head` 和 PASS，并核实该评审或连续补审覆盖落地的全部最终产品差异。正式合入门仍认已合入 PR 的精确 head 上的 `deepagents/review`、`ci-ok` 及 strict；适用的主线 CI 仍须来自实际 `main` 运行，不能用 PR CI 顶替。\n  - 令 `M` 为所核产品的实际主线落地提交，必须是报告 `head` 的可达祖先。CI 或独评的实际受测提交 `E` 等于 `M` 时直接核原件与适用范围；不等时，须复算以下任一条产品等价链：\n    1. **纯报告尾部**：`E` 和 `M` 均在被审 `head` 的实际主线交付链上，一方是另一方的祖先。二者之间只允许交付清单和非作者审查原件逐路径、按前后值核定的纯文档、实体报告或机械收据变化。不得把任何运行、构建、测试、CI 的输入或权限/类型变化列作报告。逐提交核尾部的全部变化，不按路径后缀推定分类；无法核定的条目按产品变化处理。该规则也用于下项 `E` 到 PR head 的候选尾部。\n    2. **Squash**：从该票已核交付记录取得对应 PR，由 GitHub 证实其已合入 `main`、精确 `head.sha=H`、`merge_commit_sha=M`。核 `M` 只有一个父提交 `P`，且 `P` 是 `H` 的可达祖先。`E=H`，或 `E` 是 `H` 的祖先且 `E..H` 仅为上项定义的候选尾部。分别从 Git 实际计算 `P→H` 和 `P→M` 的完整差异，不按申报路径截取。仅剔除上项定义的非产品变化，比较所有产品路径的前后 blob 字节及 Git mode，对增删记录不存在，改名按删加。路径集或任一前后值不同即不等价。提交、blob 或尾部分类无法核实时也不成立。\n  - 交付方提供已验收的 manifest、实际 CI run、独评原件及主线落地记录。#1391 用这些原件和 Git 对象计算等价证明，#1403 自行取 GitHub 记录及 Git 对象重算，不信任交付方的「等价」字样或 `ArtifactRef.head` 祖先规则（b）本身。用交付预检的实际差异与逐文件内容、权限比对口径（`.sandcastle/delivery-bundle.ts:83-86, :156-175, :248-285, :306-308`），不把旧扫描改称在新 SHA 上执行，也不免需要补跑或补审的尾部。无法证明、未覆盖或应有项缺失时，记 `CI_FINAL_PRODUCT` 或 `REVIEW_FINAL_PRODUCT`，指出该产品、原件与差异，所在 Destination 或 TB 判失败。\n\n共用子记录封闭类型定义如下"},{"before":"## 六、实施归属与图边","after":"### 三处证据门的实施验收\n\n- [ ] `at18_coverage_scope`：在其余门均满足的输入中，让 US-ST-001、US-ST-002 指向同一覆盖原件，原件证明 001、明确排除 002。断言 002 的对应子义务报 `COVERAGE_SCOPE`、条目为 `FAIL`，整图报告为 `FAIL`，不误伤原件确证的 001。删除 002 的声明，或将 DST-01 的原件换成只覆盖 DST-06 的原件，同样失败。正例中原件各自声明并证明两条精确键，允许共享这一份原件；仅由 TB-11 前置门销项的 US-ENG-10 仍可使用共同输入包。#1403 对篡改的通过报告复算为 `verdict=\"FAIL\"`。\n- [ ] `at18_final_product_binding`：让 TB-02 的绿 CI 与 PASS 独评只指向 `d4f14d7889`，实际落地到 `bc2efc7e72` 时 `product.txt` 已改。即使祖先关系成立，仍分别报 `CI_FINAL_PRODUCT`、`REVIEW_FINAL_PRODUCT`，TB-02 不过门。正例中适用主线 CI 在实际落地提交成功，正式独评绑定真实 squash 前 PR head，两个完整产品差异逐路径的字节与 mode 相等；仅有已登记的纯报告尾部也允许复用适用证据。单独改文件 mode、构建/测试输入或移除应有主线 CI 都不能过门。#1403 独立重算同样结论。\n- [ ] `at18_own_manifest_bootstrap_digest`：给合法自身 manifest 的已登记非空实体填 64 个零作为 SHA-256。#1391 在真实 CLI 上必须输出 `BLOCKED` 和 `REPORT_HASH_MISMATCH`、退出 `1`，空输出目录仍为空且既有文件不变；#1403 自身清单同例不写回执。正例的登记摘要与固定原件相符、manifest 尚未登记本次产物，应继续引导。只污染上游或受验清单的实体时不报自身引导失败，其余引导条件满足时仍输出结构化 `FAIL`。\n\n## 六、实施归属与图边"}]}
```
