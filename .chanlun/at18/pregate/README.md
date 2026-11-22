# 闸前落地清册（ADR 0064 R10/R11）

[入口](../landing-census.json)绑定 r5 的四份原始字节：完整 P0 第一父链、收集到的 GitHub 关联、候选信号和逐条裁决。来源提交为
[r5 冻结原件（10f41af19c）](https://github.com/Newchanlun/NewChanlun/tree/10f41af19cb46ffa23fa03b5cdc650179328a3fe/.chanlun/review-results/issue1551-amend-inputs-r5)。[作用域依据](scope-basis.md)解释显式归属；
[落地账](landings.json)列逐票作用域、逐提交的第一父文件差异。

从有完整历史的克隆根目录运行：

```sh
python3 .chanlun/at18/pregate/check_census.py
```

省略 `--head` 时默认在本地回放冻结窗 `b9d898dccf46c2a716115eaa1215bc39c458a959`。
回放使用工作树中固定的历史复审原件，与冻结 PRE **1,025/1,025** 逐条核对，不表示原件已入这个窗口的 Git 树。
预期退出 **1**：**978 PASS / 47 BLOCK**；**42** 条原 blob 硬阻断，**5** 条换了最终
blob 待补救，**0** 条删除，**0** 条放行。

指定 `--head <F>`（或用非冻结窗的重放目录指定观察头）时，查 F 树的固定复审文件，
沿第一父链核首载 blob，并把当前登记与重算的 PRE 一一核对。路径可退出或重入，原裁定不随窗口改变。
即使显式指定的 F 就是冻结窗，F 树缺件仍报 `PREGATE_REVIEW`。只有显式给出
`--review <path>` 才能预检未入树登记；若 F 已有登记，则候选必须与 F 原件逐字节相同。

补救原件也只从 F 树的固定路径读取；F 尚无原件时可用 `--remediation <path>` 预检候选，
不能覆盖已有原件。校验器核对 P0/F 两端、行集、复核依据及末次第一父变更；本地核验
不替代 R09、非作者逐缺陷复核或整图验收。

归档中的夹具只有在首父同一提交以同一 blob 原子迁出、全部历史归档路径已从 F 消失时，才可在目标路径引用。
迁移提交和 F 中，同一个普通 `FIXTURE-MOVED.md` 都须精确指明旧归档相对路径和新仓库路径；指针须在原包内。
同字节别名、指针本身和报告正文不能借迁移成为依据。首见于现役路径的原件和同期清单声明的冻结副本沿用原规则。

从来源重放清册时，把 `F` 设为所查观察头、`O` 设为新的仓外输出目录。默认用 `origin/main`
核主线第一父位置；仅检出实施线时，可传入已从服务端核实的主线提交作为 `--main-ref`。这些
`cmp` 只用于冻结观察窗。同一次核对也可以把 `O` 交给 `check_census.py`，核验重放的 PRE、路径和历史输入。

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

冻结窗重放应得到 62 张票、115 个唯一落地提交、133 对票—提交和 1,025 条 PRE 路径。
`check_census.py` 双向核对登记册与落地账，按 ADR 0064 r6 的显式映射重算每票作用域，从 Git
枚举留存路径，并校验 [历史复审原件](../pregate-review.json) 的原始 Git blob 及逐条 P0 身份。
所有严格 JSON 输入均拒绝重复键和无法表示为有限 IEEE 754 binary64 的数值；普通 Python 与 `python3 -O` 执行相同的校验。R3 回归检查固定在 r5
观察窗；F 推进后，路径和留存关系以重算为准。
路径回放的 `post_gate_commits` 保留过程差异；`final_blob_changed` 才表示留存路径的
最终字节是否变化。仅改变 mode 或先改后退回原 blob，不能进入补救行集。

[历史偏差](historical-deviations.json)照录 r5 原观察；[补救定位](cure-sources.json)列出 CI 原失败
run、job、步骤及具名复跑。若同名测试在默认及 `backtest_bin` 两种构建中均失败，保留两条独立
检查。聚合门因子作业失败而转红时，补救绑定实际失败的子作业或测试。历史的 `CANCELLED`、
`NO_RUN` 和 DevSkim 失败按 R11 照录；补救检查通过不改变历史结论。

## 仍待通过的验收门

1. **R10**：冻结窗的 42 条原字节仍硬阻断。改过 blob 的 5 条尚缺非作者逐缺陷补救原件和相应 R09 证据。
2. **TB-01**：仍为 **0/722**（53 story、237 family、432 detail），待 #1675 交付实测准入合同和正式入口的签锚收据。
3. **DevSkim**：本切片的 `DS173237` 待 CI/Boat 非作者核销；切片 1 的扫描读数不适用于当前候选。
4. **切片 1 Rust funding 测试**：待 Boat 恢复或远端 CI 复跑。
