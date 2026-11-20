# #1551 r2 考古：从首轮四项 BLOCK 回到在案机制

首轮源提交 `9ad6b51c15614be207d6208c93d560eb832ea8d7`，原 PR #2065 头 `6ba72e84c55aa6d65b11cc46b7288142f4fce62b`。Claude 原审见 `Review-r1.md`（源证据头 `263165e6b69c5c86b2867666fb3d14f5a07120ce`）；三处原始 #1391 复现见同包 `REPORT-1391-astra.md:15-16,23,75-86`。首轮分级和两路查询沿用，补本轮会改变裁定的命中，不把搜索结果当成穷举。

## Q1 · C，B3/B4：覆盖键、实际结果映射与已关片

- Tracker：`gh issue list --search '"逐子义务" "原件" in:title,body,comments' --state all` 命中 #1551；`gh issue list --search '"AT-18" "补件" in:title,body,comments' --state all --limit 20` 命中 #1374 的历史补件，未给出逐键 AT-18 的现行协议。另查 `gh issue list --search '"TB01-PARENT-CONTRIBUTION" in:title,body,comments' --state all --limit 20` 命中 #1359。
- 仓内：`rg -n '逐子义务|US-ST-001.{0,120}US-ST-002|覆盖声明|原件定位' analysis/ docs/ .chanlun/` 有 ADR 0064 与 `TB02-06-EXECUTION-SLICES.md:306-311`；复查 `rg -n 'at18-evidence-scope|TB01-PARENT-CONTRIBUTION' docs/adr/ .chanlun/review-results/issue1340-publication-20260909/view/inputs/TB01-PARENT-CONTRIBUTION.md`，定位现审改动与 TB01 正式贡献账。用 `git ls-tree -r --name-only b9d898dccf -- .chanlun/review-results .sandcastle` 查 AT-18 scope 已落地实体，无命中。没有依据把旧索引当成新证明格式。
- `for n in 1359 1370 1371 1372 1373 1374 1392 1404 1414 1418 1403; do gh issue view "$n" --json number,state,title; done`：前九张均 CLOSED，#1418、#1403 OPEN。[#1359 已关闭回执](https://github.com/Newchanlun/NewChanlun/issues/1359#issuecomment-5653549133) 明列 A/B/C 交付、各自 AC 与后续联合义务；主线 `b9d898dccf:.chanlun/review-results/issue1370-tb01-a/ROOT-ACCEPTANCE.md` 可读。`git show c65f021959:.chanlun/review-results/issue1373-tb02a-20260913/EVIDENCE-INDEX.json` 有原件索引与保全位置，不能代替实际验收。
- 发布包 `.chanlun/review-results/issue1340-publication-20260909/payload/inputs/TB01-PARENT-CONTRIBUTION.json`：`jq '{keys:keys,runtime_acceptance}' <原件>` 核到 `runtime_acceptance="NOT_EVALUATED"`。分配账可以找来源，不能证成测试；manifest 已绑定 ticket/base/head/path/SHA-256，沿用 `.sandcastle/CODEX-CHILD.md:54-65` 和 `.sandcastle/delivery-bundle.ts:189-241,281,304,316-321`，额外的只是本任务需要的可回溯映射和逐键独审身份。
- 读取 `.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/{IMPLEMENTATION-CROSSWALK.json,SPEC.json,inputs/SPEC-COVERAGE-INPUT.json}`：`rows[].story_id` 与 `destination_success_obligations[].destination_id` 没有 `source_json_pointer`；345 个 family 和 496 个 detail 指针均能从覆盖输入解析并取回相等的 `id`；六条 Destination 的 crosswalk 行没有 `success_closure_slice_ids`。其中 US-ST-001 的关闭切片为 TB-01、TB-02、TB-07，US-ENG-10 仅 TB-11。规范没有完整的类×profile 表，不能从观察或已收证据推导该分母。见 `verify-contract.log` 的静态复算。
- C 的裁定去向 `decision`：保留已裁逐项完整/不跨类规则，固定四类规范定位；一个补件 owner 先冻结正式非作者核过的域目录，再封包与独审。通过两份摘要与逐键收据绑定定位、真实结果和来源票。B3 的三案与数量、边变化见 `candidates-b3.md`、`new-ticket.md`。

## Q2 · B，B1/B2：本仓双父落地与真实 Rust 去重

- Tracker：`gh issue list --search '"squash" "最终产品差异" in:title,body,comments' --state all` 命中 #1551；复搜 `gh issue list --search '"1875" "rust-green" in:title,body,comments' --state all --limit 20` 和 `gh issue list --search '"merge_method" "strict" in:title,body,comments' --state all --limit 20` 无直接命中，追现行工作流的 #1875/#2027 注释与在案运行。
- 仓内：`rg -n 'squash.{0,100}(差异|等价|CI)|最终产品差异|纯报告尾部' analysis/ docs/ .chanlun/` 命中 ADR 0064 和 `.chanlun/review-results/issue1626-closeout-20261026/README.md:7` 的已验 squash；补查实际写入入口 `.sandcastle/deepagents-pilot/pilot1742/review_sweep.py:276-279`，REST 用 `merge_method=merge`，并传精确 PR head。上位交付要求仍是 `.sandcastle/docs/graph-engineering.md:237-241`、`.sandcastle/CODEX-CHILD.md:45-50,65,74` 的最终差异和真实主线。
- 统计冻结主线 `b9d898dccf46c2a716115eaa1215bc39c458a959`。以下可重跑（取 300 个第一父提交，不把双父第二条支线采样算进去）：

```bash
git log --first-parent -300 --format='%H %P' b9d898dccf |
  awk '{n[NF-1]++} END{for(i in n)print i,n[i]}'
git log --first-parent -300 --format='%H %P' b9d898dccf |
  awk 'NF==3{print $1"^{tree}\n"$3"^{tree}"}' |
  git cat-file --batch-check='%(objectname)' |
  awk 'NR%2{a=$0;next} {n[a==$0]++} END{print "same",n[1],"different",n[0]}'
```

  单父 166、双父 134；双父中与第二父同树 107、异树 27。单父计数不等于已验证 squash 数，须另核 PR。#2021 的 M 第一父 `ed780bcd4a`、第二父 `fdda2200fb`，M/H 树均为 `d7383eac789bbcf1a239b7c2f999921cec78cbb4`；`c65f021959` 是异树在案，不能仅以不同树断言产品改了或独评失效。
- `.github/workflows/ci.yml:41-46,76-116,1459-1530`：push 只为双父同树、路径确定且无 Cargo.lock 变更时去重；跳过集内是 Rust 不适用，否则必须有真跑的同树 PR Rust。DevSkim 的 main push 独立成功（`.github/workflows/devskim.yml:10-15,23-34,55-56`）。`gh api repos/Newchanlun/NewChanlun/branches/main/protection` 核现行 context 为 `deepagents/review`、`ci-ok`、`DevSkim`，strict=true；审 PR 不等于审主线作业。
- #2021 实例已用 `gh api repos/Newchanlun/NewChanlun/actions/runs/<id>` 和 `.../jobs?per_page=100&filter=latest` 复核：M 的 CI push [43853928501](https://github.com/Newchanlun/NewChanlun/actions/runs/43853928501) 中 ci-ok green、Rust skipped；`git diff --name-only b9d898dccf^1 b9d898dccf -- rust` 有 15 个路径、Cargo.lock 不在差异。其 `changes` 作业 133253234569 的日志原行是 `PR run on same tree that ran Rust: 43559429852` 与 `push dedup: rust=false`。该 PR run 为同仓、确切 H、GitHub 原作业清单中所有 Rust 实跑作业与矩阵项成功。M 的 DevSkim push [43853928206](https://github.com/Newchanlun/NewChanlun/actions/runs/43853928206) 也成功。
- 以 M 的 Git tree 和 M 版 `.github/scripts/ci-rust-reuse.py:71-79`、工作流 `SKIP_RE` 复算得到 `e2c84167d8de876969a03911c5692811df6dcdbbae4248635f93e7b6ba59efdb`，与 GitHub 服务端 PR `rust-green <指纹>` 名称相同。B 的裁定：独评对实际双父 merge 和 squash 采用各自明确基线的同一差异判据；CI 坚持实际 M 的 push 锚，只在上述在案去重条件可独立复核时合并使用真正的 PR 实跑，不把 PR run 改名为 main 证据。

## Q3 · B：自身已登记实体在引导阻断

- Tracker：`gh issue list --search '"manifest" "摘要不符" in:title,body,comments' --state all` 命中 #1551；`gh issue list --search '"REPORT_HASH_MISMATCH" in:title,body,comments' --state all` 无命中。仓内：`rg -n 'REPORT_HASH_MISMATCH|摘要不符|已登记.{0,16}摘要|引导前提' analysis/ docs/ .chanlun/` 命中 ADR 0064 的自身引导和上游派生条。
- 沿用 CODEX-CHILD:54-63 与 `.sandcastle/delivery-bundle.ts:189-241` 的版本和完整字节规则。补齐引导诊断清单；完整预检 :242–245 的 `requiredReports` 与空报告集合规则不提前执行。已登记错误在第（1）步 BLOCKED，不写入；只污染受验对象仍出 FAIL。首轮独审已通过实质门，本轮不改变。
