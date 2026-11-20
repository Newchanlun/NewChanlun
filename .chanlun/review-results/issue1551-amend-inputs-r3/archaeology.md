# #1551 考古：第三稿

取证版本：ADR 基线（`origin/decision/1551`）`6ba72e84c55aa6d65b11cc46b7288142f4fce62b`；主线实测 `b9d898dccf46c2a716115eaa1215bc39c458a959`。退回为 #1551 评论 7047086314，前置 held 为 7042797850，实现暴露三处缺口为 7040728269。方向简报原件 Git 提交 `0e83628c81cdcb6b2b4ccfc9dc8debc07f11d9ae`，路径 `.chanlun/review-results/issue1551-design-r3/{DESIGN,UNRESOLVED,BASIS}.md`。前两轮审查的原件版本及行号见 `HANDOFF.md`。

逐点查询在下节逐条列出，tracker 全包含 closed。仓内另执行 `rg -n -m 1 'AT-18|#1551|#1493|TB-11|场所实验 runner' analysis`，退出 1、无命中（无额外在案推论）。以下按正本、票面取证、尝试实测三种来源分别裁：

| 点 | 归类与原件 | 推理或建议裁定 |
|---|---|---|
| Q1 最终 CI 与报告头 | B；SPEC #1340 正文第 380、432 行，`.sandcastle/docs/graph-engineering.md:237-241`，`.github/workflows/devskim.yml:8-27`。 | SPEC 按六终点而非历史合入时间求验；现场缺 2 次、有 12 次 DevSkim 红，原始工作流无法手动补在 M 上。用 F 当次执行，不改已关历史。 |
| Q2 #799/#804 | A；`docs/agents/doctrine-rules.md:43-55, :61-87`。 | 守既定通则。R09 是集成事件，R10 是 P0 留存原件复审；同一事实证明从不在两条通道任选，F 行为仍同一门。 |
| Q3 非作者身份 | B；`.sandcastle/CODEX-CHILD.md:54-65`，#2132 正文验收，#1915 合入及 App status。 | 实测 PRE 可以由正式 PR 固定字节，不存在能分辨用户和代理或两个实际审查人的账户字段。审查担保归 #2132 验收和登记正式门，机器写明其验证边界。 |
| Q4 实验 runner 硬门 | A；`docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:39-48`，#2133，SPEC #1340 正文第 377–382 行。 | 定方案不增加授权。没有用户有效域，experiment 失败；simulation 可继续，P2 不能冒名。 |
| Q5 证据类别下限 | C/decision；SPEC #1340 正文第 377–382、429 行，三份 JSON 切片账各 `/units`，crosswalk 三个展开数组。 | 整体知道哪些 TB 需要 P1，键级没有统一机读下限。默认由登记作者声明并经独审，机器可核持续不缩。 |
| Q6 运行记录封印 | C/decision；`.sandcastle/delivery-bundle.ts:189-246`，`.github/workflows/ci.yml:1499-1513`。 | manifest 只核实体存在与摘要；借 Rust 作业名将服务端事实与摘要绑定。匹配 F、组、profile、run/attempt，不能以一个文本结论冒充原件。 |
| Q7 #1493 改挂 | B；#1493 评论 6292806300、PR #1582；`raw/tb02-children.jsonl`。 | 原生未挂 #1360，但实质 TB-02-X 已交付。改挂并纳原生分母，保留旧票态和依赖。 |
| Q8 验收窗口 | C/decision；`.sandcastle/deepagents-pilot/pilot1742/executor.py:889-892, :961-967`；`.sandcastle/docs/graph-engineering.md:15-17`。 | 利用已有合入开关，而非暂停审查或放宽保护。主线前移重跑，不能用宣称纯文档的尾部替代。 |
| Q9 同 F 重跑 | C/decision；`.github/workflows/ci.yml:4, :82-119`；原件查询服务端 `run_attempt`。 | 预先明确单一最新规则，不先筛绿。部分 job 重跑未产生齐全的新 attempt 时不能拼，须全量重跑。 |
| Q10 记录过期 | C/decision；`raw/historical.jsonl`、`.sandcastle/docs/graph-engineering.md:240-241`。 | GitHub 正常回应无匹配与查询报错不同；历史保持 NO_RUN，F 查空则失败重跑，不能给未知绿灯。 |
| Q11 TB-01 原实际探针 | B；`.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-PARENT-CONTRIBUTION.md:24`，#1359 评论 5653549133；#1340 正文第 7 行。 | 只迁原已签受测合同；headless 真浏览器与进程重启都须在 Actions 实际运行。产品前端整体交付仍归 #1460，不扩张本图。 |

### 补充取证与反查

- 额外换说法查询 `gh issue list --state all --limit 30 --search '"DevSkim" "例外" in:comments' --json number,state,title`：#1359/#1371–#1374/#1392/#1404/#1414/#1493 等；完整结果在 `raw/deviation-search.json`，不是只从旧审查转述。
- `gh issue view 1551 --comments` 及只列评论编号的 `gh issue view 1551 --json comments`；读 #1340、#1391、#1403、#1369、#1493、#2131–#2133 正文及评论：`gh issue view <号> --json number,url,body,comments,state,stateReason,closedAt,labels`。#1340 的编号为对本次 API 正文运行 `jq -r .body … | nl -ba`；归档 SPEC 的历史行号另列，不混用。
- 对 #1369、#1391、#1403、#2131、#2132 执行 `gh api --paginate repos/Newchanlun/NewChanlun/issues/<号>/dependencies/blocked_by --jq '.[]|.number'`，对 #1359/#1360/#1361/#1369 查 `/sub_issues`；命中见 `raw/`。#1369 下实际有 #1391/#1403/#2131/#2132/#2133。#1403 的原生 blockers 只列 #1391、#1359，票面多列 TB 不代表原生另有边。
- `fieldwork.py` 可重放核验：对 Git 第一父提交查 `commits/<sha>/pulls`、`commits/<head>/statuses`，比对树；对历史提交查 `actions/runs?head_sha=<sha>`，仅留真实 push 的 ci/devskim。所有命中见 `raw/postgate.jsonl`（40 项成功）和 `raw/historical.jsonl`（15 个提交，CI failure 3、DevSkim failure 13、完全无两个 workflow 的提交 2）。G0、#2021 与 #1582 的 PR 回读单列；#1374 在 P0 残存的 roster blob 为 `3dd5a98a88eeaca7783af575f033e2f07c06a997`。
- `python3 fieldwork.py --local` 在候选 worktree 按真实 JSON 重算：TB-01..11 键数 722/659/456/462/219/189/881/89/145/136/113；无显式叶片的 654 键中 TB-01 占 638。以旧 summary 代替展开会丢 TB-01 的 US-DST-01/02/04。六条 DST 均链接到仅由 TB-11 销项的 US-ENG-10。历史底册扩入 #1493 且不按目录剔除后，P0 至实测主线保留路径 483 条。重跑输出保留在 `raw/fieldwork.txt`。

### Q1 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"AT-18" "主线"' --json number,state,title,url` → #2131(OPEN)、#2133(OPEN)、#2132(OPEN)、#1551(OPEN)、#1403(OPEN)、#1369(OPEN)、#1365(OPEN)、#1368(OPEN)、#1391(OPEN)、#1367(OPEN)。原件 `raw/Q01-gh.json`。
- 仓内：`rg -n -m 2 'AT-18|整图验收' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:1、docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:3。原件 `raw/Q01-rg.txt`。

### Q2 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"DevSkim" "例外" in:comments' --json number,state,title,url` → #1606(OPEN)、#1385(OPEN)、#1411(OPEN)、#1551(OPEN)、#1375(OPEN)、#1414(CLOSED)、#1404(CLOSED)、#1392(CLOSED)、#1374(CLOSED)、#1495(CLOSED)。原件 `raw/Q02-gh.json`。
- 仓内：`rg -n -m 2 'ci-ok|merge_method' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .github/workflows/ci.yml:122、.github/workflows/ci.yml:275、.sandcastle/docs/graph-engineering.md:15、.sandcastle/docs/graph-engineering.md:17。原件 `raw/Q02-rg.txt`。

### Q3 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"审查" "精确 head" in:comments' --json number,state,title,url` → #2070(OPEN)、#1742(OPEN)、#1719(OPEN)、#1717(OPEN)、#1523(OPEN)、#1716(OPEN)、#1640(OPEN)、#1768(OPEN)、#1419(OPEN)、#1715(OPEN)。原件 `raw/Q03-gh.json`。
- 仓内：`rg -n -m 2 '非作者|正式门' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:4、docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:17、docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:41、.sandcastle/docs/graph-engineering.md:15、.sandcastle/docs/graph-engineering.md:17。原件 `raw/Q03-rg.txt`。

### Q4 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"场所实验" "凭据"' --json number,state,title,url` → #2133(OPEN)、#1551(OPEN)。原件 `raw/Q04-gh.json`。
- 仓内：`rg -n -m 2 '用户授权|凭据接触' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:46、.sandcastle/docs/graph-engineering.md:72。原件 `raw/Q04-rg.txt`。

### Q5 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"证据" "P1" "P2"' --json number,state,title,url` → #1467(OPEN)、#1465(OPEN)、#1365(OPEN)、#1768(OPEN)、#1340(OPEN)、#1323(OPEN)、#1419(OPEN)、#1572(OPEN)、#1527(OPEN)、#1540(CLOSED)。原件 `raw/Q05-gh.json`。
- 仓内：`rg -n -m 2 'PRESERVED_BOUNDARY|exclusion_boundary|证据类' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:21、docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:25。原件 `raw/Q05-rg.txt`。

### Q6 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"AT-18" "摘要" in:comments' --json number,state,title,url` → #1551(OPEN)。原件 `raw/Q06-gh.json`。
- 仓内：`rg -n -m 2 'deliveryManifestSchema|sha256|at14-report/1' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .sandcastle/docs/graph-engineering.md:152、.sandcastle/docs/graph-engineering.md:169、docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:22、docs/adr/0064-at18-whole-graph-acceptance-and-closeout.md:36、.github/workflows/ci.yml:917、.github/workflows/ci.yml:1013。原件 `raw/Q06-rg.txt`。

### Q7 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"TB-02-X"' --json number,state,title,url` → #1442(OPEN)、#1634(OPEN)、#1441(OPEN)、#1440(OPEN)、#1978(OPEN)、#1360(OPEN)、#1493(CLOSED)、#1490(CLOSED)、#1604(CLOSED)、#1347(CLOSED)。原件 `raw/Q07-gh.json`。
- 仓内：`rg -n -m 2 'TB-02-X|PARENT-CONTRIBUTION' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-PARENT-CONTRIBUTION.md:1。原件 `raw/Q07-rg.txt`。

### Q8 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"review_sweep" "strict"' --json number,state,title,url` → #1926(OPEN)、#1742(OPEN)。原件 `raw/Q08-gh.json`。
- 仓内：`rg -n -m 2 '不得放宽|strict' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .sandcastle/docs/graph-engineering.md:15、.sandcastle/docs/graph-engineering.md:17、.github/workflows/ci.yml:42。原件 `raw/Q08-rg.txt`。

### Q9 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"workflow_dispatch" "ci-ok" in:comments' --json number,state,title,url` → #1924(CLOSED)。原件 `raw/Q09-gh.json`。
- 仓内：`rg -n -m 2 'workflow_dispatch|ci-ok' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .github/workflows/ci.yml:4、.github/workflows/ci.yml:122、.sandcastle/docs/graph-engineering.md:15、.sandcastle/docs/graph-engineering.md:17。原件 `raw/Q09-rg.txt`。

### Q10 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"DevSkim" "无运行" in:comments' --json number,state,title,url` → #1551(OPEN)、#1599(CLOSED)。原件 `raw/Q10-gh.json`。
- 仓内：`rg -n -m 2 '无报告|未检验' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .sandcastle/docs/graph-engineering.md:240、.sandcastle/docs/graph-engineering.md:241。原件 `raw/Q10-rg.txt`。

### Q11 两向命令与命中

- Tracker：`gh issue list --state all --limit 10 --search '"TB-01" "浏览器"' --json number,state,title,url` → #2132(OPEN)、#1415(OPEN)、#1551(OPEN)、#1406(OPEN)、#1419(OPEN)、#1424(OPEN)、#1426(OPEN)、#1429(OPEN)、#1393(OPEN)、#1439(OPEN)。原件 `raw/Q11-gh.json`。
- 仓内：`rg -n -m 2 '耐久|浏览器|NOT_EVALUATED' .sandcastle/docs/graph-engineering.md docs/adr/0041* docs/adr/0064* .github/workflows/{ci,devskim}.yml .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-*` → .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-EXECUTION-SLICES.md:7、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-EXECUTION-SLICES.md:11、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-DISPATCH-REVIEW.md:11、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-PARENT-CONTRIBUTION.md:19、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-PARENT-CONTRIBUTION.md:32、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-ENTRY-RECON.md:5、.chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-ENTRY-RECON.md:15、.github/workflows/ci.yml:1268。原件 `raw/Q11-rg.txt`。
