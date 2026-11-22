# 闸前落地清册（ADR 0064 R10/R11）

[入口](../landing-census.json)绑定 r5 的四份原始字节：完整 P0 第一父链、收集到的 GitHub 关联、候选信号和逐条裁决。来源提交为
[r5 冻结原件（10f41af19c）](https://github.com/Newchanlun/NewChanlun/tree/10f41af19cb46ffa23fa03b5cdc650179328a3fe/.chanlun/review-results/issue1551-amend-inputs-r5)。[作用域依据](scope-basis.md)解释显式归属；
[落地账](landings.json)列逐票作用域、逐提交的第一父文件差异。

从有完整历史的克隆根目录运行以下命令。把 `F` 设为验收所用的主线提交，`O` 设为新的仓外输出目录；
要复验 r5 观察窗时用 `F=b9d898dccf46c2a716115eaa1215bc39c458a959`。默认用 `origin/main`
核主线第一父位置；只检出实施线时，可以把 `--main-ref` 设为已从服务端核实的主线提交。

```sh
P=.chanlun/at18/pregate
python3 "$P/rebuild_pregate.py" --f "$F" --out "$O" \
  --source "$P/sources.json" --adjudication "$P/adjudication.json" \
  --census .chanlun/at18/landing-census.json --historical-runs "$P/historical-runs.json"
python3 "$P/check_census.py" "$O"
cmp "$P/landings.json" "$O/landings.json"
cmp "$P/historical-deviations.json" "$O/historical-deviations.json"
cmp "$P/unattributed-window-audit.json" "$O/unattributed-window-audit.json"
```

对 r5 观测提交，重放应得到 62 张票、115 个唯一落地提交和 1,025 条 PRE 路径。
`check_census.py` 先将逐票落地与登记册核对，再反向核对逐提交归属，从 Git 枚举留存路径。
它将 `pre.json` 和 [非作者复审原件](../pregate-review.json) 逐条与 P0 的 `(path, blob, mode)`
对齐，并报告原裁定计数。所有读入的 JSON（含重放目录中随附的历史偏差表）均拒绝重复键；
普通 Python 与 `python3 -O` 执行相同的校验。R3 回归检查以 r5 观测窗为前提；F 推进后，路径和留存关系以重算为准。
`paths.json`、`postgate-path-history.json` 和 `unattributed-window-audit.json` 保留过程差异与归属扫尾。

[历史偏差](historical-deviations.json)照录 r5 原观察；[补救定位](cure-sources.json)列出 CI 原失败
run、job、步骤及具名复跑。若同名测试在默认及 `backtest_bin` 两种构建中均失败，保留两条独立
检查。聚合门因子作业失败而转红时，补救绑定实际失败的子作业或测试。历史的 `CANCELLED`、
`NO_RUN` 和 DevSkim 失败按 R11 照录；补救检查通过不改变历史结论。

## 仍待通过的验收门

1. **R10**：P0 的 **978 PASS / 47 BLOCK** 原样归档。47 条 BLOCK 仍阻断 R10。
2. **TB-01**：仍为 **0/722**（53 story、237 family、432 detail），待 #1675 交付实测准入合同和正式入口的签锚收据。
3. **DevSkim**：本切片的 `DS173237` 待 CI/Boat 非作者核销；切片 1 的扫描读数不适用于当前候选。
4. **切片 1 Rust funding 测试**：待 Boat 恢复或远端 CI 复跑。
5. **ADR 0064 归属口径**：R10 第 197 行的线性公式与 §四的具名归属存在既有分歧，由主控另案裁定。
