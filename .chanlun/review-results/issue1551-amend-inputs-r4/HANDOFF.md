# #1551 · ADR 0064 第四稿复审输入

**对账对象**：历史观察头 b9d898dccf46c2a716115eaa1215bc39c458a959；G0 是 #1915 的落地 bd54d4b28ec4f83d596837f84f1f861dd085124c，P0 是其第一父 b5cd3fee352e5f7199233de628da05ff06c5798f。此观察头用于重现历史，未来实际验收另冻结 F。

## 两份精确编辑合同

- canonical_edit.json 中的 primary 与 sync 都以 6ba72e84c55aa6d65b11cc46b7288142f4fce62b 为源；draft.md 中只有一份 canonical_edit fence，解析后与 primary 一致。
- canonical-check.txt 用仓内 canonical-edit.mts 独立重放到候选 Git 对象。ADR 0036 的既有 §二第 4 条链接/锚点不变；未发现仓中引用 ADR 0064 数字行号的现役调用。
- pytest.txt 是暂合候选到实际 origin/main 后运行原命令的结果。这里不添加占位文件，也不更改测试/基线。

## 重放底册

从包含完整 origin/main 历史的克隆运行。将 B 设为本证据包的目录（不是候选 ADR 路径），O 设为一个空目录：

    python3 "$B/rebuild_pregate.py" --f b9d898dccf46c2a716115eaa1215bc39c458a959 \
      --source "$B/sources.json" --adjudication "$B/adjudication.json" \
      --historical-runs "$B/historical-runs.json" --out "$O"
    python3 "$B/check_census.py" "$B"

线上重新采集时用 --capture 取代 --source，给出 --followup 1495 --followup 1527 --followup 1608 --followup 1737；登记正式承接时同步更新归属出处。用 --capture-runs 与 --adjudication 一起向 GitHub 重新取历史 main push 观测，之后用该次导出的 historical-runs.json 重放偏差。当前票态和服务端 run 可见性并非永久稳定，复现实测用冻结无凭据的投影原件 sources.json 与 historical-runs.json。

| 输入或输出 | 核验要点 |
|---|---|
| sources.json | GitHub 原生关系、议题/评论定位、PR merge SHA 与关联、历史 PR 枚举索引。仅保存关系及出处投影，不复制整段评论。 |
| all-first-parent.jsonl、candidate-signals.json | 从 Git 第一父遍历产生。可查已选与未选提交；PR 关联按实际 merge SHA，而非标题猜测。 |
| adjudication.json、unattributed-window-audit.json | 自动信号无法证明语义归属时的补修、正式尾件与共享归属处理；其余图创建后第一父提交及实际触及路径单列。普通落地由 Git 和 GitHub 关联全量枚举，不从此文件抄提交表。 |
| landings.json、paths.json、pre.json、postgate-path-history.json | 完整逐票/逐提交落地、原始第一父差异、P0 和观察头叶路径的 mode/blob、闸后触及提交及 PRE 清册。PRE **没有**复审 verdict；#2132 需实际审查。 |
| historical-runs.json、historical-deviations.json | 实际 CI/DevSkim main push 运行观察与按票归属展开的历史偏差。包含明确的无运行，不把历史绿/红冒充本轮 F。 |
| summary.json、census-check.txt | 计数、仍开放的落地票、r3 反例复现及离线逐字节校验。 |

## 独审应先看什么

1. **R10/R11 的分母**：脚本遍历 P0 的 2,987 个第一父提交，归档当前认得的 62 张来源票、133 个票/提交关系、115 个唯一落地和 1,025 条 PRE 路径，其中 21 张来源票仍开放。`#2132`须核语义归属及无标签/错标签的剩余提交；文件数和此处统计不是合同上限。#1493 当前仍在 #1323 下；依旧须在正式落地时按裁定改挂 #1360，演算先计入。
2. **R09 与 R10 各自留红**：修改过的历史路径仍须复审 P0，对应闸后集成仍需 R09。晚关、重开、未关均不改变纳入路径；#1406 的 #1616 单件就有 89 条不在 r3 表里且闸后未改的留存路径。R11 按唯一提交取服务端运行，以每张归属票分账。
3. **#1403 精确重算**：第八节检查原因、引用、诊断、时间和排序。相同的生产首发事实只能得出 PRODUCTION_NOT_ENABLED / ticket:1561，不比较自然语言。TB-11/R13 仍按成品之前的因子求值；#1391 与 #1403 的两次封包和独审仍是关图的必要条件。
4. **真实权限**：#2133 当前 OPEN、零评论；未获得签署、未启动凭据实验或 Rust 验证。#2131/#2132/#1391/#1403 的实际运行和各自下游验收留给原责任票；本包只送 Gemini 异家族独审。
