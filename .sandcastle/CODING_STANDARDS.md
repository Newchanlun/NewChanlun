# Coding Standards（NewChanlun）

评审工蜂经 @.sandcastle/CODING_STANDARDS.md 加载本文件；实装工蜂同样遵循。

## 语言与工具链

- 主力 Rust（`rust/` 单 crate workspace）：`cargo fmt` 风格、`cargo clippy` 零新增 warning、`cargo check` 必过；测试纪律见 `docs/agents/delivery-discipline.md`「验证范围与测试计数」（测试指纹）与 `docs/agents/doctrine-rules.md`「总缝规则」（对拍口径）。
- **本机（macOS 宿主）禁跑 cargo / rustc**（#1588）：Rust 验证走 CI、Boat 或远端环境（与 AGENTS.md「底线」同一口径）。远端环境即 `~/.local/bin/nc-remote <已提交 ref> rust <cmd>`（`NC_REPO="$(git rev-parse --show-toplevel)"`、`NC_TARGET=<工蜂唯一名>`），在 windows-5090 的 WSL 上跑；CI 由编排层推分支触发。沙盒 PATH 已前置垫片，本机调用即非零退出。
- 文档一律简体中文；缠论概念对齐 `.chanlun/definitions/` 正本，不自造口径。

## 纪律（commit 与引用）

- commit message：`<type>(<scope>): #<GitHubIssue号>——<一句话>`；编号只指 GitHub Issue（编号声明行必备）。
- 引用缠论课原文须回查 `docs/chanlun/text/blog/` 正本，核验步骤见 `docs/agents/doctrine-rules.md`「文档层名分」节（行号未漂、逐字无删改、作者归属三查，逐字摘引须目视避开行内注，行号以 `docs/chanlun/text/blog/` 为准）；任何「课号:行号」形式的引用都不算已核实，援引方须自己回查那一课。
- 代码注释登记口径分歧必须带票号。

## 架构

- 教义分层、同一判断不设宽严两档、每级跑同一个判定：规则本身见 `docs/agents/doctrine-rules.md`「缠论教义正本」「收敛通则」「总缝规则」各节与 ADR 0047，这里不复写。
