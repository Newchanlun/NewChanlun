# 代码审查回滚/事故评测集（#1931）

本目录存放 `origin/main` 真实历史事故、回滚与干净 PR 评测集（`cases.json`，`schema_version: "review-eval/1"`），用于每次改动代码审查提示词、模型、过滤或收敛策略前后的量化跑分与回归对比。

## 一条命令跑分与统计

以下命令默认在 `.sandcastle/deepagents-pilot` 目录执行：

```bash
VENV_PY=/Volumes/AgentStorage/issue1742-deepagents-pilot-20261027/venv/bin/python

# 1. 核验 cases.json 的 schema、40 位小写 SHA 存在性、bug_locations 行号界限及 base..head diff hunk 归属
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval validate-cases \
  --cases ../review-eval/cases.json \
  --repo-root ../..

# 2. 对审查器预测输出跑分（默认严格全覆盖，支持 --line-tolerance 15、--max-finding-span 120、--allow-partial）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval score \
  --cases ../review-eval/cases.json \
  --predictions /path/to/predictions.json \
  --out-json /path/to/score.json

# 3. 对比两次打分（强校验评测集指纹与容差一致，输出指标增量 + 逐案改进/回归/混合列表）
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
- 仅 `blocking` / `important` 计入 bug 定位一对一最大匹配与 `blocking_precision`；跨度超过 `--max-finding-span`（默认 `120` 行）的宽区间发现不计命中。
- 干净 PR 只要终态为 `BLOCK` 一律计为误报（无论 findings 为空、仅含 `nit` 还是含 `blocking`）；仅在 `verdict: "PASS"` 时非阻断 `nit` 不计误报。
- `score` 默认要求预测覆盖全部 `case_id`；传 `--allow-partial` 时缺漏案例记为 `MISSING` 并在 `coverage_rate` 显式暴露缺口。

## 如何新增事故/回滚案例

1. 用 `git show` 核实引入缺陷的提交（`head_sha`）、其审查基线（`base_sha`）以及后续回退/修复提交（`fix_sha`），均须填完整 40 位小写 SHA。
2. 用 `git diff -U0 <base_sha> <head_sha> -- <file>` 与 `git show <head_sha>:<file>` 核实每个 `bug_location` 的相对路径与 `line_start..line_end`，确保定位落在 `base_sha..head_sha` 实际新增/修改的行范围内。
3. 追加到 `cases.json` 后，执行 `validate-cases --cases ../review-eval/cases.json --repo-root ../..` 确认全量校验（含 diff hunk 归属核验）通过。
