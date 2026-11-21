# 代码审查回滚/事故评测集（#1931）

本目录存放 `origin/main` 真实历史事故、回滚与干净 PR 评测集（`cases.json`，`schema_version: "review-eval/1"`），用于每次改动代码审查提示词、模型、过滤或收敛策略前后的量化跑分与回归对比。

## 一条命令跑分与统计

以下命令默认在 `.sandcastle/deepagents-pilot` 目录执行：

```bash
VENV_PY=/Volumes/AgentStorage/issue1742-deepagents-pilot-20261027/venv/bin/python

# 1. 核验 cases.json 的 schema、SHA 存在性与 bug_locations 文件及行号界限
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval validate-cases \
  --cases ../review-eval/cases.json \
  --repo-root ../..

# 2. 对审查器预测输出跑分（支持 --line-tolerance，默认 15 行）
PYTHONPATH=../approval-signing "$VENV_PY" -m pilot1742.review_eval score \
  --cases ../review-eval/cases.json \
  --predictions /path/to/predictions.json \
  --out-json /path/to/score.json

# 3. 对比两次打分（输出指标增量 + 逐案改进/回归列表）
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
- 仅 `blocking` / `important` 计入 bug 定位命中与 `blocking_precision`；干净 PR 收到非阻断 `nit` 且 `verdict: "PASS"` 不计为误报。

## 如何新增事故/回滚案例

1. 用 `git show` 核实引入缺陷的提交（`head_sha`）、其审查基线（`base_sha`）以及后续回退/修复提交（`fix_sha`），均须填完整 40 位小写 SHA。
2. 用 `git show <head_sha>:<file>` 核实每个 `bug_location` 的相对路径与 `line_start..line_end`，确保定位落在 `head_sha` 的真实缺陷代码上。
3. 追加到 `cases.json` 后，执行 `validate-cases --cases ../review-eval/cases.json --repo-root ../..` 确认全量校验通过。
