# #2128 候选裁决送审包（R1）

- 固定基线 `b9d898dccf46c2a716115eaa1215bc39c458a959`；候选 `be2749f2996f8e928e72051193a693819c72fdbf`，仅向 ADR 0050 文末追加。ADR 0039 在 #2134 的同类追加在途，故此处不抢同一 EOF；ADR 0073 由主控预留给 #2129。本票未占 ADR 新编号。
- `classify.json`、`archaeology.json`、`archaeology.md`、`draft.md`、`canonical-edit.json`、`canonical-plan.json` 是审核输入；`candidate.diff` 为真实暂存 diff，宿主计划 diff 的对象缩写宽度与之不同，hunk 和字节内容相同。由此分支检出后执行 `python3 .chanlun/review-results/issue2128-decision-inputs/replay.py be2749f2996f8e928e72051193a693819c72fdbf` 可从真实 Git 父提交独立重放并比较候选 blob 和 diff。
- `queries/` 是每个点两路原始查询结果；`repo-hits.tsv` 是固定源提交上 repo 路查询的全部行。tracker 搜索取 all states 并包含评论索引；`source/` 留实际票面、在案原始评论、签准 SPEC 取证行和原生边。搜索未命中不单独证明“未设计”；Q6 并回查失败测试、相邻合同与驱动。
- `blob-http.txt` 是经登录的 GitHub Contents API 返回 HTTP 200 和实际 `html_url`；浏览器查看私仓 blob 要仓库登录。固定下游 SHA 仅作对应版本证据。
- `probe/boat.txt` 是 `boat run --no-env --timeout 60 --push <仅探针目录> -- python3 wal.py` 的原始小探针。结果改变了设计：清理现存 SHM 要 SQLite NORMAL 承接，EXCLUSIVE 仅放在 R4 成功后的具名写事务。探针用的是 Boat 的 Python SQLite 3.45.1，不是产品锁定版本；Rust 产品改动、同构建测试和 #1411 正式双跑都归实施，不作为本次文书完成项。
- `pytest.txt`：候选树引用测试 6 passed / 0 failed；当前 pytest 缺少配置项对应插件，产生 1 条无涉测试判定的警告。`mechanical.txt` 与 `byte-replay.txt` 分别记录宿主机械校验和独立逐字节重放结果。
