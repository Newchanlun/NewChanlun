# #2134 考古：命名域此前未裁，隔离与授权边界早有正本

固定读码基线 `b9d898dccf46c2a716115eaa1215bc39c458a959`（本 worktree HEAD 与远端 main 相同）；第四轮是 `bf8e6dfee8e659b5ff84e40786e41db71da292ee`。票上较早正文说「不阻塞 #2113」，已由 [#2134 最新评论](https://github.com/Newchanlun/NewChanlun/issues/2134#issuecomment-7047583818) 与两个方向的原生依赖回执覆盖。前序 #2113 评论提出的单拦 PATH 因现状可启动被撤回，不当成已裁。

## 六个点的两路证据

查询编号的实际命令、退出码、完整结果在 [搜索账](search/commands.json)。tracker 用 `--state all`、`in:title,body,comments`，已打开和已关闭结果一起归档；未撞单查询 100 条上限。仓内 `git grep` 在固定 commit 搜，不混本地文书差异。G1–G3 覆盖指定目录和相关配置；G4 定向覆盖通用词 `PATH/stat` 的实际运行接缝，避免把全仓行情路径同名当有效候选；G5 按票号串回 ADR 与推论层；G6 跨整个 Git 树复搜版本字段；G7 用管道字段、文件名和中文别称补查 `.chanlun/`、旧入口目录及测试。代码图检索索引不含本次固定工作树且目标符号未返回，故以 Git 指定 commit blob 核行号。

| 点 | 归类 | tracker 与 repo 查询 | 命中、推理和处置 |
|---|---|---|---|
| Q1 名字及表示 | **B** | T01–T07、T15、T18、T22–T24；G1/G2/G4/G6/G7 | `docs/runbook_production_session.md:72` 用专用基名，`rust/tests/production_session_entry.rs:29,247` 已有同根哨兵；ADR 0039 :287 只规定隔离。 [新缠论:选择] 仅作现行技术选择的溯源码：保留正当名字并保持一配置名→一同名键，推荐专用前缀、ASCII、有界；空、等号、NUL 硬拒绝。 |
| Q2 保留名单 | **C decision** | T06、T09–T14、T20、T23；G2/G3/G4 | #2113 R4 只保 PATH 是 stat 传递口径，不是 X 准入正本；票面提出 PATH、LD_PRELOAD/LD_LIBRARY_PATH；仓内没有 X 专用禁止名单。未裁技术缺口：只拒 PATH 仍允许进程控制；逐项新增跨运行时控制键缺闭合边界，推荐专用命名空间而不是名单。 |
| Q3 收窄与迁移 | **B** | T01–T03、T08、T15–T18、T22、T24；G1/G5/G6/G7 | runbook 基名与测试哨兵均保留；仓内唯一落在拟定合法域之外的实际配置值在 `rust/tests/history_simulation_entry.py:123`，仅作合成回放占位。字面 PATH 能启动，Boat 再测两类等号、NUL、空、空白、长、Unicode，读数见 [baseline](baseline.md)。 [新缠论:选择] 技术迁移默认：不设豁免，#2113 改一处占位；私有部署在升版前只核字段名和注入点。 |
| Q4 双入口与字段版本 | **B** | T01–T03、T17–T18、T22–T24；G1/G4/G6/G7 | 主线 `rust/src/bin/production_session.rs:185–192,257,277,324` 与 `rust/src/bin/x_execution_session.rs:59–63,202–217` 都对缺/空名字报 `InvalidDomain`；其他非法值仍可迟于副作用才失败。ADR 0062 :40 已裁 /2 字段改名，原样沿用。 [新缠论:推论] 技术推理：同一名字判据应前移到两入口首次可判时，默认同谓词同拒绝类别；不改合法名但缺值的原 `MissingDependency`。 |
| Q5 #2113 声明与原始环境 | **B** | T04、T09、T12–T14、T16–T17、T19–T20；G3/G4/G5/G7 | 0039 :371、#1383 加强 B13、#2113 R4 与独审报告 `:9–13,38–41`。 [新缠论:推论] 技术推理：非法名别名与空名的 raw envp 不同源；同一语法确认 HIGH 不可达，不能证明 MED 过滤成功；默认保标准库查找且由 #2113 闭合 MED/LOW、用内核边界验收。 |
| Q6 部署字段和用户权限边界 | **A** | T01–T02、T08、T17、T21–T22；G1/G2/G3/G5/G6 | `docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:39–48`；0062 :9,32–40；0039 :287,511；0048 :311,460–466；CONTEXT :370,403–408。沿用部署管道/权限分界与 P2 不启用，真实凭据授权不变。 |

以下完整结果逐条带归属或排除理由；同一行跨查询命中仍各保留查询编号，重复票也保留全部查询编号。不把 `PATH` 的路径变量、普通 `stat` 文件身份采样、CI/代理供应商密钥或交易凭据政策的命中误记为 X 注入键。

- [仓内逐条命中与处置](search/repo-hits.tsv)（同一行的原文可按路径/行号固定在源 commit 回查）。
- [tracker 逐票命中、命令编号与处置](search/tracker-hits.tsv)（含零命中查询的实际 JSON）。
- [正面票 #2134](search/I2134.json)、[#2113](search/I2113.json) 保存正文和全部评论；其他被点读票的命中、状态、原文链接见 tracker 账。

## 正本落点和在途号

追加 0039 现有「唯一正式 launcher 的 seam」的修订节最直接：它已经管谁注入、注入到哪，不把字段语法塞进账户/授权 ADR，也不把推论稿当前的结论当正本回引。0062 只在第 290 行原文之后追加 #2134 修订节，为 /2 字段指回 0039，不改原正文；runbook 只给运维口径；0048 已从属指向 0039 与 0062，CONTEXT 已分开名分，不需改。

`ls docs/adr` 在 main 至 0063；`git ls-tree -r --name-only origin/decision/1551 docs/adr` 已占 0064（`6ba72e84c55aa6d65b11cc46b7288142f4fce62b`）；`git diff --name-only origin/main...origin/decision/2079-r5 -- docs/adr` 命中 0065（`4812b992057ff5c6bf39da50e8b40bd1816382d3`）；同查 `origin/decision/2127` 只修 0038（`2a82e458b8d868590f2bd7cf023744f97099f063`）。远端用 `git ls-remote origin` 对这些指定 refs 核过。已有落点更近，不分配新 ADR 编号。
