# review-results 与 tmp/ 归档索引

按 ADR 0004「过程记录与产品文件」（历史 §5 的现行承接），review-results 是跟着票走的工作草稿，关票后移出仓库归档。下表目录对应的票都已关闭（2026-11-07 用 gh 逐张读回，44 张票全部 CLOSED）。过程记录出仓；仍约束产品行为的规范留在产品文档：

- `issue1644-p6-audit-ledger-20261021/AMENDMENT.md` 是 S 审计台账与写前闭包核验读法的生效修订（#1481、#1645 仍在使用），已逐字迁入 [ADR 0061](../../docs/adr/0061-s-writer-audit-ledger-delta-reading.md)，正文行号不变；ADR 0042 与 `rust/src/bin/s_session_v3/audit_ledger.rs` 已加指向它的正本指针。该目录其余工作件（SPEC-DRAFT、ARCHAEOLOGY、REVIEW-1..3）随目录归档。
- `issue1550-fu19-closeout-20261101` 只是证据记录；它的规范指针在 ADR 0058 与 `.chanlun/definitions/chong-traceability.md`，#1607 的待办记在 `replay_comparator.rs` 代码处，因此照常归档。

**仓内仍提到归档目录的地方**（2026-11-07 全树核对）：review-results 以外只有 ADR 0061 的出处说明，以及 `rust/src/theta_v0/parser/stroke_tb02v_tests.rs` 的 `#[ignore]` 说明（已改为指向本索引）。保留草稿里的历史路径会失效（§5 接受）：`issue1626-closeout-20261026/`（README、1734-ARCHIVE-INDEPENDENT-REVIEW26X、1626-WORKTREE-*）、`issue1657-closeout-20261028/CLAUSE4-EXCEPTION.md`、`eng-debt-20261020/`（P3-SWEEP、tests/REPORT）。`issue1481-h1-managed43r/REPORT.md` 原引 AMENDMENT 的那处已改指 ADR 0061。

**后续验收仍要用的归档件**（ADR 0042 切片 5 / #1645、ADR 0061 P6 验收引用，归档不影响它们的效力，届时按下面的方式取回）：`1488-acceptance/s86/compare_s86.py`、`1488-acceptance/degrade-0065/s86/compare_s86.py`（S86 INVARIANT 对拍），`1488-acceptance/degrade-0065/min12/`（MIN12 的 input、oracle、tools），`1488-acceptance/close-0085/receipts/reports/workers__degrade-0065__REPORT.md.md`（ADR 0042:173 引用的 0065 在案读数）。取回：`tar -xf /Volumes/AgentStorage/repo-archive/review-results-closed-9b436af2d2.tar .chanlun/review-results/1488-acceptance/<路径>`，或 `git show 3d61fb7294:.chanlun/review-results/1488-acceptance/<路径>`。

**取回**：
- review-results：`/Volumes/AgentStorage/repo-archive/review-results-closed-9b436af2d2.tar`（tar，保留原路径，`tar -xf <tar> <目录>`；tar 里另有 `issue1371-tb01-b`，那个目录由 #1908 出仓，本表不收）。也可直接 `git show 3d61fb7294:<路径>`。
- tmp/：756 个被强制加入的文件全部去跟踪（tmp/ 本来就在 .gitignore）。按用途分类迁移，脚本行为保持不变：真正的产品输入 `real-data-multi-tf-validation.json` 原样移到 `scripts/inputs/`，两个分段诊断脚本已同批改读取路径；运行时报告 `brn-level-report.json` 由 `brn_level_analysis.report_dir()` 写到仓库外（`NEWCHAN_REPORT_DIR`，默认外卷 `/Volumes/AgentStorage/newchanlun-reports`，没有外卷时用 `~/.local/state/newchanlun/reports`），`openclaw_scheduler` 照常生成报告，但不再 `git add`；其余是脚本每次运行都会重新生成的输出，写入前都会先建 tmp/ 目录（这次给 6 个原先依赖 tmp/ 已存在的脚本补了建目录，部署文档的日志重定向前也加了 `mkdir -p tmp`）；`detect_structural_encounters.py` 读的 `cross-gang-refs.json` 是 `scan_cross_gang_refs.py` 的产物，缺失时会给出明确提示。只被文档当作证据引用的，例如 `.chanlun/definitions/qujiantao.md`、`.chanlun/genealogy/settled/321-*`、`329-*`，可用下面的方式取回。原树在 `/Volumes/AgentStorage/repo-archive/tmp-from-main-979da0c634/tmp/`（与 main `3d61fb7294` 的 blob 逐字节核对一致），也可直接 `git show 3d61fb7294:tmp/<文件>`。
- 归档时间：2026-11-06（2026-11-07 按 #1912 正式审查补正）。

| 目录 | 票 |
|---|---|
| 1488-acceptance | #1488 |
| issue1372-devskim-summary-20260913 | #1372 |
| issue1372-main-delivery-20260913 | #1372 |
| issue1373-tb02a-20260913 | #1373 |
| issue1374-tb03a-20260914 | #1374 |
| issue1392-tb02b-20260914 | #1392 |
| issue1394-ac123-closeout-20261019 | #1394 |
| issue1394-delivery-20261014 | #1394 |
| issue1394-interface-entries-20260930 | #1394 |
| issue1394-q16-checked-frame-20260930 | #1394 |
| issue1394-q16-cost-20260930 | #1394 |
| issue1394-s-cache-20260914 | #1394 |
| issue1404-tb02c-20261007 | #1404 |
| issue1405-tb02v-20261014 | #1405 |
| issue1414-tb02d-20261012 | #1414 |
| issue1420-tb02w-20261019 | #1420 |
| issue1456-sandcastle-codex-20260914 | #1456 |
| issue1488-closeout-20261026 | #1488 |
| issue1493-delivery-20261020 | #1493 |
| issue1493-tb02x-head-20261020 | #1493 |
| issue1495-lean-first-break-20261015 | #1495 |
| issue1495-resume-closeout-20261018 | #1495 |
| issue1516-premise-20261026 | #1516 |
| issue1533-closeout-20261026 | #1533 |
| issue1550-fu19-closeout-20261101 | #1550 |
| issue1568-20261021 | #1568 |
| issue1576-serve-stale-begin-20261020 | #1576 |
| issue1581 | #1581 |
| issue1585-20261021 | #1585 |
| issue1590-land-20261021 | #1590 |
| issue1597 | #1597 |
| issue1600-dof-20261021 | #1600 |
| issue1601-20261026 | #1601 |
| issue1602-production-profiles-20261025 | #1602 |
| issue1603 | #1603 |
| issue1604 | #1604 |
| issue1604-20261021 | #1604 |
| issue1605-closeout-20261026 | #1605 |
| issue1608-20261021 | #1608 |
| issue1609-20261021 | #1609 |
| issue1621-1622-clock-integration-20261024 | #1621 |
| issue1621-1622-closeout-20261025 | #1621 |
| issue1621-clock-repair-20261023 | #1621 |
| issue1621-main-regression-20261024 | #1621 |
| issue1626-versioned-fields-20261025 | #1626 |
| issue1627-land-20261021 | #1627 |
| issue1629 | #1629 |
| issue1630 | #1630 |
| issue1630-20261021 | #1630 |
| issue1644-p6-audit-ledger-20261021 | #1644（AMENDMENT.md 已迁入 ADR 0061） |
| issue1653-20261021 | #1653 |
| issue1654-20261021 | #1654 |
| issue1666-20261021 | #1666 |
| issue1666-20261026 | #1666 |
| issue1669-20261022 | #1669 |
| issue1669-final-coverage-20261025 | #1669 |
| issue1670-final-review-20261025 | #1670 |
| issue1672-acceptance-20261027 | #1672 |
| issue1674-final-acceptance-20261025 | #1674 |
| issue1678-closeout-20261026 | #1678 |
| issue1678-selfheal-20261024 | #1678 |

## 三份历史纪律（#1742 / #2030，2026-11-13）

仅本批三份历史原文已出仓；不包含 #2057 的 14 件批次或 #1920 的归档，两者保留独立索引与验收。

外卷批次：`/Volumes/AgentStorage/restart-20261107/slim/remaining-archive/discipline-2030-fac7e87-20261113/`，含原相对路径与 `INVENTORY.md`。删除前逐字节比对工作树、Git blob 与归档副本，三份一致。恢复也可用 `git show fac7e87a8876c0f5cff79b27556120d31e65c7c8:<原路径>`；不需要外卷才能读取现役规范。

| 已退役原路径 | 字节数 | 现行入口 |
|---|---:|---|
| `docs/agents/generation-constitution.md` | 4773 | `docs/adr/0004-generation-constitution.md`「现行名分与现役线」 |
| `docs/agents/delivery-discipline.md` | 12334 | `.sandcastle/docs/graph-engineering.md`「交付与关票」与 `.sandcastle/CODEX-CHILD.md` |
| `docs/agents/stat-provenance.md` | 4096 | `docs/adr/0022-acceptance-criterion-parameters.md`「统计结论的标注与引用」 |

旧报告、roster 与推论中的原路径保持历史原文，按本批来源提交恢复。ADR 0039/0048 的历史引文保留，当前产品名分指向 ADR 0004；ADR 0058 的 AT-14 专用报告 schema、路径及消费者合同不在本批改动范围。移除的是历史纪律原件，不是整个 docs/agents 或产品报告树。


## 历史层归档（#1920）

本批已删除 **114 件**：`.auto-memory-snapshot/` 48 件、`.rtas/review-results/` 12 件、`chanlun/harness/` 54 件（其中 vendored harness-engineering 51 件）。以下清单是本 PR 相对 main 的精确删除集合；现役 watcher roster 保留。

- 来源版本：`923d5f1187fefc549f810643390068884c36ba9e`。本批文件在后续整合 main `40ce4c56b9780390b5ebaca7c711ca253d0be44b` 时内容未变。
- 外卷原件：`/Volumes/AgentStorage/restart-20261107/slim/remaining-archive/implementation/historical-178-f43fac8f.tar`。包名的 178 是早期归档全集，包含后来保留或由 main 先行删除的文件；不代表本批删除 178 件。只按下列清单选择恢复，不把整个 tar 覆盖回工作树。
- 验证：原归档解包已逐文件核对字节、原路径和模式；本批 114 件均在包中，与来源 Git blob 一致。后续整合未改变删除集合，复用该恢复证据。原报告位于同一外卷目录；早期报告的 178 件范围以此处当前清单收窄。
- 单文件取回（无需外卷）：`git show 923d5f1187fefc549f810643390068884c36ba9e:<原路径> > <恢复目标>`。也可在新建空目录执行 `tar -xf <上述归档包> -C <空目录> <原路径>`，保留原目录结构与模式；不要覆盖现役文件。

<details>
<summary>114 件原相对路径（模式均为 100644）</summary>

```text
.auto-memory-snapshot/MEMORY.md
.auto-memory-snapshot/feedback_bidirectional_always_in.md
.auto-memory-snapshot/feedback_chanlun_stroke_types.md
.auto-memory-snapshot/feedback_chunk_long_tasks.md
.auto-memory-snapshot/feedback_dispatch_as_commander.md
.auto-memory-snapshot/feedback_docx_editing_rules.md
.auto-memory-snapshot/feedback_essay_course_materials.md
.auto-memory-snapshot/feedback_file_write_verification.md
.auto-memory-snapshot/feedback_necessity_accumulation.md
.auto-memory-snapshot/feedback_no_asset_specialization.md
.auto-memory-snapshot/feedback_no_workaround_bsp_lesson.md
.auto-memory-snapshot/feedback_options_expiry.md
.auto-memory-snapshot/feedback_options_selector_redesign.md
.auto-memory-snapshot/feedback_order_pricing.md
.auto-memory-snapshot/feedback_python_output_pattern.md
.auto-memory-snapshot/feedback_recursive_nested_fugue.md
.auto-memory-snapshot/feedback_rubric_scoring.md
.auto-memory-snapshot/feedback_tutor_rj_dissertation.md
.auto-memory-snapshot/feedback_use_latest_model.md
.auto-memory-snapshot/mac_migration.md
.auto-memory-snapshot/project_alpha_diagnosis.md
.auto-memory-snapshot/project_c_segment_fix.md
.auto-memory-snapshot/project_concept_movement.md
.auto-memory-snapshot/project_crude_oil_options.md
.auto-memory-snapshot/project_dissertation_genealogy.md
.auto-memory-snapshot/project_dissertation_status.md
.auto-memory-snapshot/project_emergent_direction.md
.auto-memory-snapshot/project_located_direction_discovery.md
.auto-memory-snapshot/project_m3_capital_flow_milestone.md
.auto-memory-snapshot/project_mu_short.md
.auto-memory-snapshot/project_omega_research.md
.auto-memory-snapshot/project_orbit_enumeration_duality.md
.auto-memory-snapshot/project_quant_system_progress.md
.auto-memory-snapshot/project_recursive_regularization.md
.auto-memory-snapshot/project_rtas_swarm.md
.auto-memory-snapshot/project_session2_organic_fugue.md
.auto-memory-snapshot/project_session3_fusion.md
.auto-memory-snapshot/project_session4_strict_necessity.md
.auto-memory-snapshot/project_session5_spiral_reinterpretation.md
.auto-memory-snapshot/project_session_mental_model.md
.auto-memory-snapshot/project_session_organic_fugue.md
.auto-memory-snapshot/project_todo_master.md
.auto-memory-snapshot/project_zombie_short_diagnosis.md
.auto-memory-snapshot/reference_coil_scan.md
.auto-memory-snapshot/reference_nautilus_trader.md
.auto-memory-snapshot/reference_tv_chanlun_colors.md
.auto-memory-snapshot/trading_setup.md
.auto-memory-snapshot/user_profile.md
.rtas/review-results/codex-decide-20260626-1543.md
.rtas/review-results/codex-diagnose-20260626-0820.md
.rtas/review-results/codex-diagnose-recursion-20260626-0230.md
.rtas/review-results/codex-diagnose-recursion-20260626-0231.md
.rtas/review-results/codex-diagnose-recursion-20260626-0236.md
.rtas/review-results/codex-review-20260625-2116.md
.rtas/review-results/codex-review-20260625-accounting-t33-t46.md
.rtas/review-results/codex-review-20260626-0845.md
.rtas/review-results/codex-review-20260629-0807.md
.rtas/review-results/codex-review-20260629-1425.md
.rtas/review-results/codex-review-oq9-fix-20260626.md
.rtas/review-results/gemini-decide-cc-direction-20260626-0709.md
chanlun/harness/WORKERS.md
chanlun/harness/harness-ledger-20260719.md
chanlun/harness/runbooks/long-run.md
chanlun/harness/vendor/harness-engineering/AGENTS.md
chanlun/harness/vendor/harness-engineering/ARCHITECTURE.md
chanlun/harness/vendor/harness-engineering/CLAUDE.md
chanlun/harness/vendor/harness-engineering/COPYING.md
chanlun/harness/vendor/harness-engineering/LICENSE
chanlun/harness/vendor/harness-engineering/PROVENANCE.md
chanlun/harness/vendor/harness-engineering/README.md
chanlun/harness/vendor/harness-engineering/docs/AGENTS.md
chanlun/harness/vendor/harness-engineering/docs/CLAUDE.md
chanlun/harness/vendor/harness-engineering/docs/README.md
chanlun/harness/vendor/harness-engineering/docs/authority/README.md
chanlun/harness/vendor/harness-engineering/docs/continuous-maintenance/README.md
chanlun/harness/vendor/harness-engineering/docs/domain-modeling/README.md
chanlun/harness/vendor/harness-engineering/docs/domain-modeling/homelab.md
chanlun/harness/vendor/harness-engineering/docs/domain-modeling/hyperbola.md
chanlun/harness/vendor/harness-engineering/docs/domain-modeling/implementations.md
chanlun/harness/vendor/harness-engineering/docs/durable-systems/README.md
chanlun/harness/vendor/harness-engineering/docs/durable-systems/dependency-ownership.md
chanlun/harness/vendor/harness-engineering/docs/effectiveness/README.md
chanlun/harness/vendor/harness-engineering/docs/feedback/README.md
chanlun/harness/vendor/harness-engineering/docs/feedback/mld.md
chanlun/harness/vendor/harness-engineering/docs/fixed-worker/README.md
chanlun/harness/vendor/harness-engineering/docs/fixed-worker/model-native-semantics.md
chanlun/harness/vendor/harness-engineering/docs/just-in-time-context/README.md
chanlun/harness/vendor/harness-engineering/docs/last-mile-deployment/README.md
chanlun/harness/vendor/harness-engineering/docs/lineage/README.md
chanlun/harness/vendor/harness-engineering/docs/proof/README.md
chanlun/harness/vendor/harness-engineering/docs/proof/release-integrity.md
chanlun/harness/vendor/harness-engineering/docs/proof/rustsec.md
chanlun/harness/vendor/harness-engineering/docs/tool-legibility/README.md
chanlun/harness/vendor/harness-engineering/docs/whole-job/README.md
chanlun/harness/vendor/harness-engineering/evals/README.md
chanlun/harness/vendor/harness-engineering/evals/artichoke-state-modeling.md
chanlun/harness/vendor/harness-engineering/playbooks/AGENTS.md
chanlun/harness/vendor/harness-engineering/playbooks/CLAUDE.md
chanlun/harness/vendor/harness-engineering/playbooks/README.md
chanlun/harness/vendor/harness-engineering/playbooks/improve-harness.md
chanlun/harness/vendor/harness-engineering/playbooks/repository-review.md
chanlun/harness/vendor/harness-engineering/sources/AGENTS.md
chanlun/harness/vendor/harness-engineering/sources/CLAUDE.md
chanlun/harness/vendor/harness-engineering/sources/README.md
chanlun/harness/vendor/harness-engineering/sources/artichoke-state-refactor-ledger.md
chanlun/harness/vendor/harness-engineering/sources/raw/acp/LICENSE
chanlun/harness/vendor/harness-engineering/sources/raw/acp/README.md
chanlun/harness/vendor/harness-engineering/sources/raw/hyperbola/README.md
chanlun/harness/vendor/harness-engineering/sources/raw/images/README.md
chanlun/harness/vendor/harness-engineering/sources/ryan-notes.md
chanlun/harness/vendor/harness-engineering/sources/scripts/AGENTS.md
chanlun/harness/vendor/harness-engineering/sources/scripts/CLAUDE.md
chanlun/harness/vendor/harness-engineering/sources/scripts/README.md
chanlun/harness/vendor/harness-engineering/sources/twitter/README.md
```

</details>
