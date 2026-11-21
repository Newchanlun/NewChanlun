# 代码审查回滚/事故评测集（#1931）

本目录存放 `origin/main` 真实历史事故、回滚与干净 PR 评测集（`cases.json`，`schema_version: "review-eval/1"`），用于每次改动代码审查提示词、模型、过滤或收敛策略前后的量化跑分与回归对比。

## 一条命令跑分与统计

以下命令默认在 `.sandcastle/deepagents-pilot` 目录执行：

```bash
VENV_PY=/Volumes/AgentStorage/issue1742-deepagents-pilot-20261027/venv/bin/python

# 1. 核验 cases.json 的 schema、40 位小写 SHA 存在性、bug_locations 行号界限及 base..head diff hunk 归属
#    （须在完整历史仓库 / fetch-depth: 0 环境下执行；CI 浅克隆 fetch-depth: 1 下 pytest 会自动跳过完整历史溯源单测，仅跑 schema 与临时 Git 仓正负校验）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval validate-cases \
  --cases ../review-eval/cases.json \
  --repo-root ../..

# 2. 对审查器预测输出跑分（默认严格全覆盖，支持 --line-tolerance 15、--max-finding-span 120、--allow-partial）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval score \
  --cases ../review-eval/cases.json \
  --predictions /path/to/predictions.json \
  --out-json /path/to/score.json

# 3. 对比两次打分（强校验评测集指纹与容差一致，输出指标增量 + 逐案改进/回归/混合/未裁定列表）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval compare \
  --before /path/to/score-before.json \
  --after /path/to/score-after.json

# 4. 统计外部正式审查历史运行基线（可选叠加人工去向 JSONL 台账）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval baseline-stats \
  --runs-dir /Volumes/AgentStorage/issue1742-deepagents-pilot-20261027/external-review/runs \
  --out-json /Volumes/AgentStorage/restart-20261107/review-1931-baseline-report.json \
  --out-md /Volumes/AgentStorage/restart-20261107/review-1931-baseline-report.md
```

## 预测 JSON 格式

`score` 接受数组或 `{"predictions": [...]}`：

```json
{
  "predictions": [
    {
      "case_id": "bug-2016-spec-revocation-regression",
      "verdict": "BLOCK",
      "findings": [
        {
          "file": "scripts/wayfinder_engine.mts",
          "line_start": 270,
          "line_end": 274,
          "severity": "blocking",
          "summary": "撤销路径误用严格解析导致不成形 BLOCK 被忽略"
        }
      ]
    }
  ]
}
```

- `severity` 合法值：`blocking`、`important`、`nit`、`pre_existing`、`info`。
- 仅 `blocking` / `important` 计入 bug 定位匹配与 `blocking_precision`；进入二分图一对一匹配前会按规范坐标 `(file, line_start, line_end)` 去重（重复副本仍计入精确率分母，不可领取额外位置召回），闭区间跨度（`line_end - line_start + 1`）超过 `--max-finding-span`（默认 `120` 行）的宽区间发现不计命中。
- 干净 PR 只要终态为 `BLOCK` 一律计为误报（无论 findings 为空、仅含 `nit` 还是含 `blocking`）；仅在 `verdict: "PASS"` 时非阻断 `nit` 不计误报。
- `score` 默认要求预测覆盖全部 `case_id`；`evaluated_cases` 仅计实际产生 `PASS` / `BLOCK` 裁定的案例，`FAILED`（`failed_cases`）与 `--allow-partial` 下的 `MISSING`（`missing_cases`）均计入覆盖缺口（`coverage_rate = evaluated_cases / total_cases`），不充当 clean 零误报分母；当已裁定 clean 案数 `decided_clean_cases == 0` 时，`clean_false_positive_rate` 与 `compare` 产出的 `clean_false_positive_rate_delta` 均为 `null`（不可计算），且在 `compare` 中未裁定案例绝不进入 `improved_cases`（从正常状态退化进 `regressed_cases`，其余归入 `undecided_cases`）。

## 如何新增事故/回滚案例

1. 用 `git show` 核实引入缺陷的提交（`head_sha`）、其审查基线（`base_sha`）以及后续回退/修复提交（`fix_sha`），均须填完整 40 位小写 SHA（不允许带空白字符）。
2. 用 `git diff -U0 <base_sha> <head_sha> -- <file>` 与 `git show <head_sha>:<file>` 核实每个 `bug_location` 的相对路径与 `line_start..line_end`（若同一逻辑缺陷分散在同一文件的多个离散改动点，可用可选字段 `"extra_ranges": [[start, end], ...]` 逐一列出离散可接受区间，避免用大跨度把中间未改动行包进去），确保每个区间均落在 `base_sha..head_sha` 实际新增/修改的行范围内。
3. 追加到 `cases.json` 后，在完整历史仓库（非浅克隆）执行 `PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval validate-cases --cases ../review-eval/cases.json --repo-root ../..` 确认全量校验（含对象存在性、行号界限与 diff hunk 归属核验）通过。
