# #1551　ADR 0064 第五稿裁定输入

## 问题

本条依 #1909 代理独审裁定。

**分级：P**。本票裁 AT-18 用哪个主线版本证明整图已验收、怎样认定有效独评与 #1279 的下游放行界线。按 `.sandcastle/docs/graph-engineering.md:25-32, :50`，关图门不是实现细节。此票没有待签真实外部动作，`user_gate=[]`；#2133 的 runner 凭据接触面独立交用户签，#1412 实际发送权限不随签。第 2 轮由 #1551 评论 7047086314「退回」。第四稿异家族独审核实了历史落地底册、票态不参与选审及引用预检；第五稿闭合其余四项阻断：来源归属、证据和未完义务边界、诊断与适配器合同，以及本交接草稿。

## 权威依据

- SPEC #1340 当前正文第 370–382、428–432 行：TB 交付顺序与 P1/P2 边界、AT-18 的**六项**最终验收。签署时的归档附件 `.chanlun/review-results/issue1339-r2-spec-20260909/view/spec/SPEC.md:210-220, :372, :424` 分别定义六 Destination、TB-11 与 AT-18，仍按当前票面补充解释，不反写历史 SPEC。
- `docs/agents/doctrine-rules.md:43-55, :61-87`、`docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:9-15, :39-48`：不同判断可分设，但同一判据不许失败降档、级别不改算法；独审不代签真实权限。
- `.sandcastle/docs/graph-engineering.md:15-17, :96-110, :237-241`：日常合入门、非作者独审与关票；`.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279` 为同树 merge 的实际入口；`.sandcastle/CODEX-CHILD.md:54-65` 不把预检当身份或结论证明。
- `.github/workflows/ci.yml:4, :82-119, :1457-1518` 与 `.github/workflows/devskim.yml:8-27`：push 可能复用 Rust，现有手动 CI 为全跑，DevSkim 缺 dispatch；引入 ci-ok 的提交 `037b5335ead32ec4625c1644dd79b82b9155b124`。
- #1551 评论 7047086314 对十一项作了本轮起草裁定；#1391/#1403/#1369 保留原本业务义务；#2131/#2132/#2133 分别承接实现、存量复审和用户硬门。原始考古及命中见 [第三稿归档](../issue1551-amend-inputs-r3/archaeology.md)；第四稿独审报告和第五稿重放证据随本轮交接。

## 候选

选 F 上的可重跑行为证据，加两类**必须同时**成立的审查覆盖（闸后集成事件、闸前留存基准）。历史现场只照录，当前 F 有失败就按同一标准修复和重跑。拒绝逐历史合入重证：真实的缺跑、红灯、原工作流不能手动补跑，不能靠伪造清单或不计必需作业使结论可达。也拒绝只在 F 跑测试却不审最终差异：SPEC 还要求最终独评，行为结果不能等价于审查。

验收对象从 Git、GitHub 及 F 上获审来源算出，报告作者不选。对非原生来源，裁逐票举证的 `attributions`；拒绝临时解析散文或只用父票而漏列 33 张来源票。`GRAPH` 记整图出处，六个 Destination 均可审计，但不产生新关票门。冻结窗口重跑费时，但避免任何尾部“猜不影响”的路径；采用现有受保护入口与正式门，不设另一个可调宽严档。

## 裁定

正本落点：docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md

Q1：主线 CI、技术行为与运行资料同绑 F（R01、R06–R08）；Q2：按对象合取闸后审查与闸前复审，绝不互相接管（R09–R10）。Q3：身份信任限 #2132 的关票加正式登记 PR，机器核字节与锚。Q4：#2133 未签则 experiment 必须失败，不走别路（R06）。Q5：首定域由登记者声明并随 PR 独审；机器执行同类与不缩域约束（R03–R05）。Q6：运行字节放到同 run/attempt 的服务端封印，仍由业务解码器确认原件（R07）。Q7：#1493 改挂 #1360、纳底册，保留旧结论（R10、R11、七）。Q8：主控冻结日常合入、不改保护，在同窗生成与总验（R01）。Q9：最大 run id 的最新 attempt，不选绿运行和拼接（R06、R08）。Q10：历史成功查空照记无运行，F 查空不通过（R01、R06、R11）。Q11：TB-01 的原实际重启和浏览器探针用同射程的 Actions 检查改写，证不出另开缺陷，不能代盖章（R05）。

R10 完整底册重放覆盖 62 张来源票、133 个票／提交关系、115 个唯一落地、1,025 条 PRE 留存路径（其中 978 条闸后未动、47 条闸后另变）；21 张仍开放（含 #1406）。这些数是冻结样本，不是验收上限。33 张无原生 TB 的来源票影响 61 个专属落地，由获审映射进入 `Landing.attribution_scopes`。共用提交一律按实际唯一 SHA 计路径。

第八节的 `remaining_obligations` 对 #1320 重测只投影到 TB-11 与 #1320 旧票清单，不扩为各 Destination 或键内延期；另三项只跟已核准的具名键。TB 证据只含本 TB 对应类的合法封印实体；DST-05 另取权限运行核验，DST-02/03/05 另取非空迁移封印；授权签署不进证据类数组，后闸专用原件留顶层。scope 固定字面模板，`detail=check_id`；F 上适配器合同由登记册字节摘要绑定且两锚过 R09，后闸参数版本是授权原件。

Destination 不生产键；TB-11 只从代码、通用 CI、独评及输入包打开前置，避免报告自证。#1279 去向核聚合前原件，不读 DST-06 成品结论。每个判定失败落 `FailedCheck`，缺知状态用 null/UNKNOWN；只有自身引导失败走 BLOCKED 诊断且不写文档。

## 验收清单

- [x] 暂合 `origin/main` 运行 `pytest -p no:cacheprovider tests/test_retired_references.py -v`：6 passed / 0 failed；`git diff --check` 退出 0。两份编辑合同经独立 Python 和仓内解析器重放，分别与候选 Git blob 字节一致；见 `pytest.txt` / `canonical-check.txt`。
- [x] 用 `rebuild_pregate.py` 与 `check_r5.py` 从固定原件复算 62 票／115 落地／1,025 PRE；259 票态反转后核心八件逐字节不变（`summary.json` 仅开放票观察字段 21→41）。`check_r5.py` 核 33 张非原生 TB 归属、61 个独占落地、6 项无效归属拒绝与六个 DST 的历史出处路由；见 `census-check.txt`。
- [x] 复用同一冻结主线的原件核对：4,071 键 = 113 个 TB-11 键 + 3,958 个其余键，六个 DST 均含 TB-11（[原始 fieldwork](../issue1551-amend-inputs-r3/raw/fieldwork.txt)）。报告实现验收归 #1391/#1403。
- [ ] #2131 实施验证：登记指针与执行数量/标注不符、域删除、误读历史运行均失败；R03 的 `adapter-contract.json` 缺件、摘要不符或文件／登记册的 R09 锚无效时留红。先用无凭据的骨架 dispatch 验作业名；真实凭据等 #2133。
- [ ] #2132 正式交付 `landing-census.json`、`pregate-review.json`、R10 可重放枚举及 cure 锁；从 F 核四原件摘要、完整第一父历史、逐票作用域、PRE mode/blob 和实际非作者关票链。历史样本只作重放输入。
- [ ] #1391/#1403 实施后分别运行 `node --import tsx --test --test-name-pattern='at18_(key_binding|final_head_binding|own_manifest_bootstrap_digest|destination_dag|records_and_permissions|report_projection)' .sandcastle/at18-report.test.ts` 与同命令的 `.sandcastle/at18-verification.test.ts`。两个实现均须满足：
  - `at18_key_binding`：只标 001 却绑 002、漏叶片、漂移摘要、跨类、TOCTOU 缩域，各出对应诊断；合法多 basis 与 OE42 正例分别保留。
  - `at18_final_head_binding`：闸后缺状态、非 App、异树、无 CI、矩阵缺项、跳过、只在祖先成功、同 F 旧 attempt 绿、本窗口变动均 FAIL；双父同树与完整 dispatch 正例；PRE 无 #1493、错 mode/blob、有未批准行或未关 #2132 都失败，旧无 run 不伪造合规；具名失败测试未重跑必失败。
  - `at18_own_manifest_bootstrap_digest`：自身已登记实体填 64 个 0 时 BLOCKED、退出 1、无新文档；仅缺未产出的本次登记允许引导；#1403 读到受验物坏摘要须生成合法 FAIL 回执。
  - `at18_destination_dag`：六个 DST 与 US-ENG-10 同在；#1391/#1403/#1369 均 OPEN 时可有正例；缺任一必要链接、把 #1279 自己的结论喂回或伪造关闭不出 PASS。
  - `at18_records_and_permissions`：异 run/attempt 或异 profile 封印、缺真实事实、未签 #2133、UNKNOWN 被当未触发均失败且文档符合形状。具有全部有效原件的 P1、production 仅具名延期、两类证据不混用、三专用门均实际执行时有合法通过形状。
  - `at18_report_projection`：同原件异分页、异日志措辞及两票封包前后阶段重放一致；单 TB／多 TB／GRAPH 的 scope、共享提交去重、皆未激活与合法延期、#1320 重测、签署/封印分层、闸门后授权角色按第八节逐项断言。键四种模板、票义务和空 profile 槽精确匹配；无效 #2133 留红；改一个合法标量必须在精确 JSON Pointer 产生 `REPORT_MISMATCH`。
- [ ] `gh issue view 1279 --json state --jq .state` 为 OPEN；正式合入后按各票接边，#1493 保持 CLOSED/COMPLETED，不执行任何场所动作。

## 受影响票与 blocking 边变化

方向为「阻塞者 → 被阻塞者」。原生 API 回读见 [第三稿原件](../issue1551-amend-inputs-r3/raw/)下的 `edges-*.txt`；第四稿异家族复核相同边。

| 票 | 变化或保留 |
|---|---|
| #1551 / PR #2065 | 只交第五稿候选；落地后才执行本节状态更新。保留 #1551→#2131、#1551→#1369。 |
| #2131 | 保留 →#2132；新增 →#1360..#1368。交登记册、F 版适配器数据合同、两 workflow、lint、运行器与 DevSkim dispatch。 |
| #2132 / #1359 | 新增 #2132→#1391；承接 TB-01 检查、全 TB 闸前清册、结构化 scope、PRE 与非作者复审。#1359 不重开。 |
| #2133 | 新增 →#1365/#1367/#1368。硬门仍归用户，simulation 可独立推进。 |
| #1493 / #1360 | 从 #1323 改原生父票为 #1360；不改 CLOSED/COMPLETED 或既有依赖。 |
| #1360..#1368 / #1391 / #1403 / #1369 | 各 TB 汇总新增 F 的准备性关票 AC。#1391 写验收窗口、重跑与新输入。#1403 原生 blockers 为 #1359/#1391，其他 TB 经 #1391 传递；不新增重复边。不改变 #1369 的既有决定与 TB blockers。 |
| #1366、#1381、#1399、#1411、#1418 | 保留 TB-07、AT-14 与原件要求；由当前 TB owner 搬到 R02–R07 的取证，不改 ADR 0058。 |
| #942/#1096/#1282/#1304/#1319/#1320/#1279 | 不新增反向整票 blocker，不改旧裁定。#1279 自有条件仍另核。 |
| #1340/#1323 | 两张验收票同 F 完备、#1369 通过后才走关图。 |

## 授权引用

本条依 #1909 代理独审裁定。起草权限不含独审、合入、关票、调度 workflow 或现场授予凭据；真实权限独立援引 `docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:39-48`。第五稿待异家族独审；真实授权状态不随草稿改变。

## 引用自证

| 对象 | 出处与查证 |
|---|---|
| #1551 两轮与退回 | `gh issue view 1551 --comments`；原件及评论 ID 见第三稿考古。 |
| #1340 / #1323 / #1279 | `gh issue view 1340 --json body`；对正文行编号查 AT-18/TB-11；#1323 与 #1279 当前文本、评论及 OPEN 另外读取。 |
| PR #1915 / #2021 / #1582 | GitHub PR API 回读合入、head 与提交；Git 比对树；#1915/#2021 查 App statuses。原始查证见第三稿归档 `raw/`，第四稿独立核对了同一观察头的 40 个闸后提交。 |
| 当前工作流、交付和流程 | `.github/workflows/ci.yml:82-119, :1457-1518`、`.github/workflows/devskim.yml:8-27`、`.sandcastle/delivery-bundle.ts:189-246`、`.sandcastle/docs/graph-engineering.md:68-104, :237-241`；本轮用带行号读取核附注。 |
| 闸前历史与分母 | `landing-census.json` 按 R10 绑定四来源与显式作用域，`rebuild_pregate.py` 遍历 P0 第一父链 2,987 提交，实际重建 **62 票／115 落地／1,025 PRE 路径**。133 关系、21 张开放票、33 张非原生 TB／61 个独占落地及具名反例见 `census-check.txt`、`scope-basis.md`；#1406 的 #1616 独立贡献第三稿表外的 90 条留存路径（89 条闸后未动）。 |

## 考古对照

| 点 | 名分 | 裁定 |
|---|---|---|
| Q1 | B | 最终整图解释、CI 现实与独评；R01/R08。 |
| Q2 | A | #799/#804 按对象分别求值，R09 和 R10 同时为必需；R10 用全量可重放清册，不冻结旧票数。 |
| Q3 | B | #2132 + App 锚，机器证据和过程担保分开；33 张非原生来源的已裁映射由清册钉住。 |
| Q4 | A | ADR 0041 硬门归用户，未签失败。 |
| Q5 | C/decision | 首定域受正式门审，机器比基线禁止缩域。 |
| Q6 | C/decision | 同 run/attempt 封印；适配器数据合同随 F 绑定，签署原件与运行证据分层。 |
| Q7 | B | #1493 已交付 TB-02-X，改挂并纳分母。 |
| Q8 | C/decision | 窗口冻结、前移即重算；不发明尾部免检。 |
| Q9 | C/decision | 最大 id 的最新 attempt。 |
| Q10 | C/decision | 区分历史查空、当前查空和查询失败。 |
| Q11 | B | 保持原射程的 Actions 测试；实测能力留实施验证。 |

后附的 `canonical_edit` 块按原宿主单正本格式。同步修订 `.sandcastle/docs/graph-engineering.md:238-239` 同时在 `canonical_edit.json` 的 `sync` 中精确列入；两份差异一并交独审。宿主仅支持单一正本路径，不把该同步包作为自动落地输入。
