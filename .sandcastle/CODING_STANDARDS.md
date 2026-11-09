# Coding Standards（NewChanlun）

评审工蜂经 @.sandcastle/CODING_STANDARDS.md 加载本文件；实装工蜂同样遵循。

## 语言与工具链

- 主力 Rust（`rust/` 单 crate workspace）：`cargo fmt` 风格、`cargo clippy` 零新增 warning、`cargo check` 必过；测试纪律见 AGENTS.md「收敛通则」（同一判断不设宽严两档）与 ADR 0047，测试计数口径见 AGENTS.md「记忆」节「测试指纹」。
- **本机（macOS 宿主）禁跑 cargo / rustc**（#1588）：上面的 check/clippy/test 一律经 `~/.local/bin/nc-remote <已提交 ref> rust <cmd>`（`NC_REPO="$(git rev-parse --show-toplevel)"`、`NC_TARGET=<工蜂唯一名>`）在 windows-5090 的 WSL 上跑，或由编排层推分支走 CI。沙盒 PATH 已前置垫片，本机调用即非零退出。
- 文档一律简体中文；缠论概念对齐 `.chanlun/definitions/` 正本，不自造口径。

## 纪律（commit 与引用）

- commit message：`<type>(<scope>): #<GitHubIssue号>——<一句话>`；编号只指 GitHub Issue（编号声明行必备）。
- 引用缠论课原文须回查 `docs/chanlun/text/blog/` 正本，核验步骤见 AGENTS.md「文档层名分」节（行号未漂、逐字无删改、作者归属三查，逐字摘引须目视避开行内注，行号以 `docs/chanlun/text/blog/` 为准）；任何「课号:行号」形式的引用都不算已核实，援引方须自己回查那一课。
- 代码注释登记口径分歧必须带票号。

## 架构

- 教义分层、同一判断不设宽严两档、每级跑同一个判定：规则本身见 AGENTS.md「缠论教义正本」「收敛通则」「总缝规则」各节与 ADR 0047，这里不复写。
