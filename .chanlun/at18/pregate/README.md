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
`check_census.py` 中的 R3 回归断言以 r5 观测窗为前提；F 推进后，路径/留存关系以重新计算为准。
输出的 `pre.json` 只列复审分母。`check_census.py` 将它和 [非作者复审原件](../pregate-review.json)
逐条与 P0 的 `(path, blob, mode)` 对齐，并报告裁定计数。r5 的 **978 PASS / 47 BLOCK**
均照录；本地结构与覆盖核验通过不改变 47 条历史 BLOCK，它们仍阻断 R10。
`paths.json`、
`postgate-path-history.json` 和 `unattributed-window-audit.json` 保留过程差异与归属扫尾。

[历史偏差](historical-deviations.json)照录 r5 原观察；[补救定位](cure-sources.json)列出 CI 原失败
run、job、步骤及具名复跑。若同名测试在默认及 `backtest_bin` 两种构建中均失败，保留两条独立
检查。聚合门因子作业失败而转红时，补救绑定实际失败的子作业或测试。历史的 `CANCELLED`、
`NO_RUN` 和 DevSkim 失败按 R11 照录；补救检查通过不改变历史结论。
