# ADR 0064 第三稿方向简报（#1551）

目标：#1323 只凭 AT-18 整图报告关图；报告不出假 PASS，也不要求证不出的东西。本文是第三稿的方向，不是 ADR 正文。

## 1 改掉的前提

前两稿都假定生成器能逐片复证历史合入当时合规。实测不成立：TB-01..03 已关的 11 张实施片加 #1359 共 14 个落地提交，12 个 DevSkim push failure，3 个 CI push failure，`2706d87f`、`c65f0219` 没有任何 run；`ci-ok` 自 `037b5335ea` 才有。第三稿改为验收最终产品：证据全部绑定报告顶层 `head`（记 F），历史合入只记录、不复证；正式门启用前进入主线的字节由今天做得到的一次非作者复审承担。SPEC #1340:432 写「最终独评、落地主线及适用 CI」，按 F 读有据。原则：Attack the Premise（先实测前提）、Subtract Before You Add（先删后建）。

## 2 证据模型

常量：G0=`bd54d4b28ec4f83d596837f84f1f861dd085124c`（PR #1915，#1909 生效）；P0=G0^1；GATE_BOT=`newchanlun-review-gate[bot]`；REG=`.chanlun/at18/registry.json`；PRE=`.chanlun/at18/pregate-review.json`。

```
Registry(at18-registry/1) = {crosswalk_sha256, checks[], bindings[], pregate}
Check = {check_id, group, evidence_class, profile_id|null, runner, selector, expected_count, key_aware, source:{path,sha256}, record|null}
Binding = {binding_id, slice_id, basis:{path,sha256,pointer}, keys:[{kind,id}], domains:[Domain]}
Domain = {evidence_class, profile_id|null, result, deferred_gate|null, checks:[check_id]}
pregate = {landings:[{ticket, commits[], cure_checks[]}]}
PregateReview(at18-pregate-review/1) = {owner_ticket, rows:[{path, blob, verdict}]}
```

`runner` 取 `cargo-test|node-test|pytest|command`；`record` 取 `permission|migration|post_gate` 接 `.experiment|.production`，或 null。

## 3 规则（替换 r2 的「子义务覆盖门」「落地绑定」两小节）

- **R0 读法**。验收对象是 F 上的最终产品。各片历史落地当时的 CI、独评、manifest 不复核、不作证据，只照 R11 记录。
- **R1 输入封闭**。#1391、#1403 只读 F 上的 Git blob、GitHub 服务端事实、本票仓外 manifest。CLI 删去 observations。
- **R2 期望键**。键为 `(kind,id,slice_id)`，只按 crosswalk `rows`、`family_entry_links`、`detailed_acceptance_links` 各行乘 `success_closure_slice_ids` 展开（`slice_success_obligations` 在 TB-01 少 3 个故事，不得用）。共 4071 个；`TB-11` 的 113 个按基线走前置实施门；其余 3958 个须绑定。Destination 不是键。
- **R3 绑定**。键不在期望集记 `KEY_NOT_EXPECTED`，期望键无 binding 记 `KEY_UNBOUND`。`basis.path` 只许 crosswalk、coverage input、三份 `*-EXECUTION-SLICES.json` 与 `TB01-PARENT-CONTRIBUTION.json`，不可解析或摘要不符记 `BASIS_MISMATCH`。台账中 `parent_tb=slice_id` 且对应 `*_ids` 含该 id 的每个叶片 unit，都须有一条以它为 basis 的 binding 含此键，缺则 `BASIS_INCOMPLETE`。台账未列叶片的 654 键（TB-01 占 638）取贡献档的 row 或 crosswalk 节点。
- **R4 域**。`VERIFIED` 与 `PRESERVED_BOUNDARY` 域的 `checks` 非空，检查的类与 profile 等于域值；`PRESERVED_BOUNDARY` 只用于且必用于 `exclusion_boundary=true` 的 family 条目。延期域的 `checks` 为空，`deferred_gate` 取既有三常量之一且类相符，`unexecuted[]` 有同名 `required=false` 条目。每键至少一个非延期域。#1561 未启用期间 production 域只许延期，不得有 production 检查。违者 `DOMAIN_INVALID`。
- **R5 检查**。`source` 在 F 的 blob 摘要不等于登记值记 `CHECK_SOURCE_DRIFT`。`key_aware=false` 时 `source` 须对所绑每个键含一行 `@at18 <slice_id> <kind> <id>`，缺则 `CHECK_NOT_ANNOTATED`；`key_aware=true`（`command` 必为 true）时命令收到键表，对缺见证的键非零退出。运行器核执行数等于 `expected_count`、忽略与跳过为 0，不符即令作业失败。
- **R6 运行证据**。simulation 检查只在 `.github/workflows/at18-acceptance.yml`，experiment 只在 `at18-experiment.yml`，两者的 dispatch 不设 inputs。主控在 F 上 dispatch。每个 `group` 一个作业，名为 `at18 <group> <S>`，S 是 REG 在 F 的字节 sha256。检查通过当且仅当：本仓该 workflow、`event=workflow_dispatch`、`head_sha=F` 的 run 中 run_id 最大者，最新 attempt 有同名作业且为 success。没有记 `CHECK_JOB_MISSING`，非 success 记 `CHECK_JOB_FAILED`。`head_sha≠F` 的 run 不计，不设尾部复用；不读日志和自填结论。
- **R7 运行记录封印**。`record` 非 null 的检查把记录文件的 sha256 经作业输出交给同 run 的封印作业 `at18-seal <record> <sha256>`。第二节三个专用槽里承载运行内容的 external `ArtifactRef` 与 `evidence_by_class` 条目，PASS 另须 `sha256` 等于 R6 所认 run 中成功封印作业名里的摘要，并由 #1391 自身 manifest 登记，否则 `RECORD_UNSEALED`。内容解读与文书类引用沿用基线。
- **R8 F 的 CI**。(a) ci.yml 在 `head_sha=F`、`event=workflow_dispatch` 的 run 中 run_id 最大者：`ci-ok` 为 success，且 F 版 `ci-ok.needs` 每个作业的实例至少一个且全为 success，skipped 不计。(b) devskim.yml 在 `head_sha=F` 的 push 或 workflow_dispatch run 中 run_id 最大者，作业 `DevSkim` 为 success。不成立记 `HEAD_CI`。push run 不作证据，不复算去重。
- **R9 评审覆盖（闸后）**。对 F 第一父链上 G0 至 F 的每个提交 M，须同时成立：M 恰两父；GitHub 有 `merged=true`、`base.ref="main"`、`merge_commit_sha=M`、`head.sha=M^2` 的 PR；`tree(M)=tree(M^2)`；M^2 上 `deepagents/review` 的最新 status 为 success 且 `creator.login=GATE_BOT`。任一不成立记 `REVIEW_FINAL_PRODUCT`，没有替代路径。
- **R10 评审覆盖（闸前）**。#1359–#1368 及其带 `wayfinder:impl` 的原生子票里，`closedAt` 早于 G0 所属 PR `merged_at` 的每张票须在 `landings` 有一行；每个 commit 在 F 第一父链上且为 P0 或其祖先；不合记 `PREGATE_LANDINGS`。残留集取所列 commit 的 `M^1→M` 差异路径（`--no-renames`，剔除 `.chanlun/review-results/` 下的）中在 P0 存在者。PRE 须满足：每行 `blob` 等于 P0 上该路径的 Git blob id；行路径都在残留集内，并覆盖其中在 F 仍存在的每条；`verdict` 全为 `PASS`；F 第一父链上最后改动 PRE 的提交满足 R9；`owner_ticket` 为 N2 且 N2 `CLOSED/COMPLETED`。否则 `PREGATE_REVIEW`。
- **R11 历史记录**。对 `landings` 每个 commit，#1391 向 GitHub 取 ci.yml、devskim.yml 的 push run，非 success 的 run 和没有 run 的 workflow 各成一项写入 `historical_deviations[]`，`observed` 照录或记 `NO_RUN`。历史 run 不进 `ci_runs`、不写成 SUCCESS；「用户批准例外」不录为授权。ci.yml 有 failure 的 commit，其票的 `cure_checks` 须非空且各检查按 R5、R6 通过，否则 `DEVIATION_NOT_CURED`。
- **R12 键与 TB 门**。键通过当且仅当 R3 成立且含它的每条 binding 的每个域按 R4–R6 成立；带合法延期域的条目记 `BOUNDED_DEFERRED`；其余 `FAIL`，没有第二条路。`TB-01..TB-10` 的 `gate_satisfied=true` 当且仅当：汇总票 `CLOSED` 且 `stateReason=COMPLETED`（`TICKET_NOT_CLOSED`）；带 `wayfinder:impl` 的原生子票非空且无 OPEN（`SUBTICKET_OPEN`）；该 TB 全部键非 FAIL（`TB_KEYS`）；第二节属于该 TB 的专用门、R10 与 R11 中归该 TB 的项成立。
- **R13 Destination 聚合**。`result="PASS"` 当且仅当：`destination_success_obligations[i]` 所列条目在 `spec_coverage` 无 FAIL；这些条目的关闭切片里 TB-01..TB-10 均 `gate_satisfied=true`，TB-11 满足前置实施门；第二节对它的专用门成立；DST-06 另须 #1304、#1279 两项 `disposition_valid=true`；R8、R9 成立。否则 `DESTINATION_AGGREGATE`。报告前不要求 #1391、#1403、#1369 关闭。
- **R14 TB-11 前置实施门**改为：两片入口文件在 F 上存在（路径由第三稿写定）、R8 与 R9 成立、`input_bundle` 非 null。
- **R15**。r2 的自身清单引导条文原样保留。#1403 独立从 F 与 GitHub 重算 R2–R13，不读 #1391 的中间结果。
- **lint**。N1 的 `at18-registry-lint` 进 `ci-ok.needs`，逐 PR 核 R3（`KEY_UNBOUND` 除外）、R4、R5 的 pin 与标注，并对 merge-base 版本核域不缩：已有 `(键,basis)`、域的类与 profile 不得删，`VERIFIED` 不得改延期，违者 `DOMAIN_SHRINK`。

报告形状（ADR 未合入，仍为 /1）：输入包加 `registry_ref`、`pregate_review_ref`、`slice_ledger_refs`；`ReviewRef` 改为 `{pr, reviewed_head, merge_commit, creator, state}`，填 F 所属 PR，有闸前落地的 TB 另填最后改动 PRE 的 PR；`SliceStatusRef` 去掉 `main_sha`，其余 `main_sha` 与 `commits` 取 F；顶层加 `acceptance_jobs[]`（`{workflow, run_id, run_attempt, head_sha, job, conclusion}`）与 `historical_deviations[]`（`{ticket, commit, workflow, run_id|null, observed}`）；非 TB-11 键通过时 `evidence_refs` 含与 `registry_ref` 同值的引用；`bounded_domain_statement` 须含三行固定句：`AT18_LANDING_CI_NOT_CERTIFIED n=<项数>`、`AT18_PREGATE_REVIEWER_VOUCHED_BY_TICKET <N2 票号>`、`AT18_CHECK_SUFFICIENCY_BY_FORMAL_GATE`，缺则 `STATEMENT_MISSING`。基线 L17、L35–36、L62、L101 里逐项的独评、main SHA 与 CI 措辞按 R8–R10 改写。

## 4 从 r2 删除

`at18-coverage-domains/1`、`at18-evidence-scope/1`、`at18-evidence-review/1` 三份记录与「交付回执」一词；期望键表的 destination 行；「落地绑定」整节（E/H/M 链、差异等价、「须在 M 补审」）；逐 M 主线 CI（「M 版 `ci-ok.needs`」、去重复算、对 M 补跑）；补件票与 `source_tickets`；`EXCLUDED` 取值；`slices[].main_sha`；测试 `at18_coverage_scope`、`at18_final_product_binding`。保留引导子条文与 L62 的「squash 或 merge commit」，引用改为 review_sweep.py:276-279。

## 5 阻断与漏洞的闭合

- 阻断 1（成环）：Destination 不是键，由 R13 聚合；TB-11 键走前置门。
- 阻断 2（旧 M 无法求值）：不在任何 M 上求值。CI 只在 F 核（R8）；历史红灯照录、不作 SUCCESS，具名失败测试在 F 跑绿（R11）。
- 阻断 3（回执无定义）：身份只取 GitHub 事实（GATE_BOT 的 status、PR、run、作业名与结论、票态）。闸前复审者身份明写不由机器证明。
- 阻断 4（独评无产出者）：闸后由 R9 逐提交核；闸前给固定依据 R10，产出者为 N2，PRE 路径固定故登记唯一。
- 漏洞 (i)：002 须有自己的 binding、每个叶片各一条、源文件标注 002 或键感知见证；只标 001 的原件记 `CHECK_NOT_ANNOTATED`。
- 漏洞 (ii)：运行与 CI 只认 `head_sha=F`；R9 使审后的任何改动自身必经正式门；pin 使审后改测试即漂移。
- 漏洞 (iii)：r2 引导条文不动，摘要不符即 `BLOCKED`、退出 1、不写文件。

## 6 历史个案（均可达，不重开已关票）

| 票与落地提交 | 实测 | 处理 |
|---|---|---|
| #1370 `2212eba31e`；#1371 `d2219e8e01`、`e46cf3bca6`；#1372 `21b7898a`；#1359 `65298686cf` | CI push 成功，DevSkim push 全 failure | R11 照录，F 的 DevSkim 由 R8 承担。TB-01 的 722 键由 N2 绑到 F 上的检查，当年的本机探针与浏览器取证改写成 Actions 检查；贡献档只作 basis |
| #1373 `2706d87f` | 无任何 run | 记两项 `NO_RUN`，不补跑；键由 #1360 绑 |
| #1374 `abf5c0f8`、`c65f0219` | 前者 DevSkim failure；后者无 run 且异树，`.chanlun/agent-roster-2026-09-13.md` 的 blob `3dd5a98a` 由合并产生 | 两提交都进 `landings`，该路径自动进残留集并按 P0 的 blob 复审；键由 #1361 绑 |
| #1392 `8619a20f2800`、#1404 `f95a7f3e`、#1414 `465174240b` | CI 与 DevSkim push 均 failure，关票评论记获批例外 | 例外不作依据。`cure_checks` 取关票评论所记三测试 `m3_partition_synthetic_holds`、`calibration_sweep_finds_non_collapsed_segments`、`seam_btc_tick_bars_yield_non_trivial_structure`，在 F 各执行 1 次。#1414 的浏览器 30 秒帽由 #1360 绑检查，不放宽 |
| #1405 `28df886697`、#1420 `b63a3fd586`、#1394 `6badaa6049` | CI 成功，DevSkim failure；#1394 有中间提交不可编译的豁免 | 照录；豁免是过程事实，最终树由 F 的 CI 编译 |
| #1370–#1372 | 无 manifest | AT-18 不读历史 manifest，不补造 |

以上 12 张票、14 个提交全部进 `landings`，实测残留集 308 条路径。#1975、#1993 不是实施片。

## 7 票与边

新开三张 #1323 直属票（已搜 tracker，未见同用途票）：
- **N1** `[task] AT-18 登记册合同、lint、运行器与验收 workflow（#1323 / #1551）`，`wayfinder:task`。交付 REG 骨架、lint、运行器、两个 workflow、devskim.yml 的 dispatch 触发。
- **N2** `[task] TB-01 键绑定、闸前落地清单与闸前复审（#1323 / #1551）`，`wayfinder:task`。交付 TB-01 的绑定与检查、`landings`、cure、PRE。
- **N3** `[task] 场所实验 runner 的凭据接触面签署（ADR 0041:46）`，`ready-for-human`。

新增 blocking 边：#1551→N1；N1→N2；N1→#1360..#1368；N2→#1391；N3→#1365、#1367、#1368。既有边不动：#1359–#1368→#1391→#1403，#1551→#1369。改票面：#1360–#1368 各加关票 AC「本 TB 的键在 REG 绑齐、lint 绿、各 group 在一次主线 dispatch 中 success」；#1391 改输入侧；#1403 独立实现。

无环：N1 只依赖 #1551；N2、N3 与各 TB 不引用 AT-18 输出；Destination 与 TB-11 键没有产出票。顺序 #1551 → N1 → {N2、N3、TB-02..TB-10} → #1391 → #1403 → #1369 → #1340、#1323，之后才解除 #1279 上的本图前置。第四节 #1279 条文一字不改，#1279 全程 OPEN。

## 8 独审将对草稿执行的检查

1. `rg -n '交付回执|at18-(coverage-domains|evidence-scope|evidence-review)|M 版|EXCLUDED' <草稿>` 零命中。
2. 从 crosswalk 重算得 4071、113、3958。
3. 走真实提交：G0 至 `b9d898dccf` 的 40 个第一父提交全部满足 R9。
4. 每个诊断码有触发条件与 FAIL 结果；没有「由独审核定」式的机器判据；边能拓扑排序；第四节相对基线 diff 为空；逐 TB 写得出真 PASS 路径。
5. 验收命令 `node --import tsx --test --test-name-pattern='at18_(key_binding|final_head_binding|own_manifest_bootstrap_digest)' .sandcastle/at18-report.test.ts`，#1403 同名对 `.sandcastle/at18-verification.test.ts`。夹具：
   - `at18_key_binding`：只标 001 却绑 002；缺 binding；缺叶片；pin 漂移；作业只在祖先成功；作业名摘要不同；域与检查异类；链接条目 FAIL；正例含 DST-06。
   - `at18_final_head_binding`：闸后提交缺 status、status 出自他人、合入树异于 head 树；PRE 缺路径、blob 不符、N2 未关；`landings` 漏票；needs 作业 skipped、只有 push run、DevSkim failure；历史 CI failure 而无 cure；记录未封印；正例按 #2021 构造。
   - `at18_own_manifest_bootstrap_digest`：沿用 r2。
