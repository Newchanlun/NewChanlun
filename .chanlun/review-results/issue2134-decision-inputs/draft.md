本条依 #1323 Notes N-1 预授权判定

## 问题

X 执行 profile 可指定一个名字，让 launcher 把文件里的凭据写进 X 的启动环境。目前两个入口只要求名字非空。用合成值实测，主线不仅允许文字 `PATH` 启动，两个带等号的畸形名字在 launcher 路径上也能使 experiment X 达到 serving；X 单启时还可能先开库、再发现没有凭据。部署管道字段换名与作用域政策是两回事。这里裁名字的合法取值、前置检查和 #2113 的验收域；不接触真实凭据，不改场所、账户、权限、发送、交易或账本判据，不移交任何用户签署事项。

## 权威依据

1. `docs/adr/0039-production-entry-inventory-and-unique-launcher.md:283–287,371` 把凭据限定在 X 子进程，B13 验证这一边界。唯一 launcher 可控，不等于直接启动的 X 不需自检。
2. `docs/adr/0062-fu18-venue-account-permission-binding.md:9,37–41,147` 把 `credential_scope.{env,file}` 改名为 `credential_source.{env,file}`；`CONTEXT.md:370,403–408` 规定作用域政策记录不是部署管道。 `docs/adr/0048-legacy-engine-module-level-dispositions.md:311,460–466` 排除旧 Python 凭据源。迁移不恢复该路径。
3. `docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:9–15,39–48` 区分事前配置与失败兜底，保留实际凭据/权限硬门。`docs/agents/doctrine-rules.md:43–58,60–80` 的 #799、#804：同判断不分松紧；本技术入口用同一判据和同输入对拍，不动教义及其例外。
4. 主线 `rust/src/bin/production_session.rs:98–105,177–192,216–225,251–277,370–448`：先读文本，再尝试读文件；清环境只放回 PATH/显式白名单；S/E/B 先于 X 启动；只给 X 按名字注入。`rust/src/bin/x_execution_session.rs:37–63,193–229`：X 接受非空键；持锁、开库、持久化后才在 experiment/production 查环境非空。`rust/src/economic_session/store.rs:470–516,527–534`：macOS 直接探测，Linux 的 `stat` 在 SQLite 打开前启动。
5. [#2134 修订票面](https://github.com/Newchanlun/NewChanlun/issues/2134#issuecomment-7047583818) 与 [#2113 R4 处置](https://github.com/Newchanlun/NewChanlun/issues/2113#issuecomment-7047584698) 排定本票先于 #2113。候选 `bf8e6dfe` 的 `rust/src/economic_session/store.rs:505–518` 按枚举逐键删，保留 PATH；独审 `REPORT.md:9–13,38–41,65–67` 区分名字编码与原始环境枚举。本次 [主线矩阵和配置盘点](baseline.md) 确认运行边界，不把偶然可运行当正当用法。

## 候选

三者都先否决空、任意位置的等号和 NUL，不把不可移植的表示当作另一档合法输入。

| 形状 | 收益 | 代价与结论 |
|---|---|---|
| A：固定为 `NC_X_VENUE_CREDENTIAL` | 最小规则、专用名，无黑名单。跨工具直接复制。 | 仍要保留每个 profile 的版本字段归属，却失去在部署/夹具中区分键的能力；改动主线哨兵与 B13。此基名作为 B 的推荐取值，不把 A 当独立准入模式。 |
| **B：有界专用前缀** | 保留 runbook 基名与既有哨兵；一个命名空间和一个谓词排除现有或新增的非专用控制键。 | 通用合法名不在命名空间时需改名；当前追到一个 simulation 占位夹具需迁移。把命名空间注册为 X 注入专用，不再给它分配其他消费者。**采用**。 |
| C：`[A-Za-z_][A-Za-z0-9_]*` 减去保留名单（也可加同样的长度上限） | 保留现有可移植第三方名字，迁移最少；形状已堵分隔符别名。 | 只拒 PATH 仅堵 stat 保留键，仍容许 `LD_PRELOAD`、`LD_LIBRARY_PATH` 等在 X 启动时影响行为。增加一份跨系统/运行时/库/应用的控制名单也须随消费者变化增补；即使集中所有者、测试每个名单条目并审新增消费者，也不能证明名单闭合。仓内没有非专用键的部署需求，划专用域更可靠。 |

这里选择单一字段语法，而不是让 profile 可选 A/B/C 三档校验。一个合法 profile 可在基名和后缀名之间事前选择，单次启动只使用选定名；不默认补缺或失败改名。64 字节是可移植的项目上限：现有合规名字最长 30 字节，仍有足够的命名空间，且不会把键名可用性押给系统 exec 限额。长度不限制凭据值。

## 裁定

正本落点：docs/adr/0039-production-entry-inventory-and-unique-launcher.md

采用 B。合法键是字节长度不超过 64 的全串 `NC_X_VENUE_CREDENTIAL(?:_[A-Za-z0-9][A-Za-z0-9_]*)?`，大小写精确，无修剪、规范化、别名、备用值或旧配置豁免。基名是推荐示例，不是缺项默认值。专用命名空间不承载其他控制含义；不用逐项保留名单。`PATH` 只保留作进程查找语义，`LD_PRELOAD`、`LD_LIBRARY_PATH` 等不属于此空间。更改键名只改部署管道，不改场所作用域与签署实例。

launcher 在读取文件、创建状态或任何域 init/spawn 前与 X 在锁、开库和环境取值前调用同一谓词；两个支持的 profile 版本各取各字段，不读另一字段作兼容；任一模式，不合规、缺失或类型错误统一 `InvalidDomain`，不回显非法内容。runbook 与 ADR 0062 只指回本落点；ADR 0062 在第 290 行之后追加指针，不改正文。固定主线当前只实现 /1，/2 实施者直接复用谓词。

#2113 两部分同一交付。HIGH 从合法 profile 注入不可达；合法名与 `PATH` 不相等且不会失真。MED 仍能来自绕过 launcher 的原始环境，尤其零个可枚举键会被删除时；不把 profile 校验当环境过滤，归 #2113。过滤经内核边界验收后，#2113 可声明：「Linux 上，采用合法 X 凭据键名时，打开持久库启动的 stat 的初始执行环境除原有 PATH（如有）外没有任何继承项；由 X 执行 profile 注入的凭据不可能编码成内核键 PATH，不会到达 stat。」具体声明边界与实现锁见 [#2113 收口要求](2113-closeout.md)。

## 验收清单

1. 文书：`git diff --check b9d898dc decision/2134` 退出 0；`git diff --name-only b9d898dc decision/2134` 只列 ADR 0039、ADR 0062、生产 runbook 三文件。对 ADR 0039 基线应用唯一 `canonical_edit`，结果须与候选逐字节相同，且仅新增 #2134 修订。ADR 0062 前 290 行须与 `b9d898dc` 逐字节相同，文末仅追加下方 `adr_0062_append` 的字节；生产 runbook 保持原候选的运维指针不变。
2. 输入：[主线矩阵](baseline.md) 可定位 24 次观测，原始 `boat-mainline.log:99–101` 为 1 passed、沙盒已回收；[考古](archaeology.md) 与完整搜索命中可复核。部署未证事实单列，不声称核完私有实例。
3. **#2113 下游验收**：`invalid_x_credential_key_refuses_before_side_effects` 双入口负控、正控及合成文件读检测；`durable_db_stat_preserves_only_path` 覆盖零删除的原始项；两档 `credential_key_only_in_x_child` 使用 #1383 内核级测试；`rust/tests/history_simulation_entry.py` 现有入口通过（迁移占位名）。测试以 [#2113 收口要求](2113-closeout.md) 的行为为判据，名字为建议。此项以实施候选为对象，不作本稿代码验收。
4. 票状态：`gh api repos/Newchanlun/NewChanlun/issues/2113/dependencies/blocked_by --jq 'map(.number)|index(2134)!=null'` 为 `true`；对 #1383 同一查询以 2113 为前置。无新建/删除边。

## 受影响票与 blocking 边变化

- #2134 是 #1365 的子票。已存在 #2134 → #2113（箭头由前置指向被阻塞票）；#2113 → #1383 保留。只读核边，不新增、删除或提前解锁。
- #2113 承接 launcher/X 共同校验、夹具迁移及 stat 环境；#1383 保有 B13 全树验收与 launcher 启动键集登记；#1769 的骨架与 #1770 对 X 的离线 adapter 是规则消费者，不另挂边。ADR 0062 /2 实施路径复用谓词，不被提前拉入本票。#1365 汇总、#1323 Destination 以及 #1561 P2 处置不改。

## 授权引用

本条依 #1323 Notes N-1 预授权判定。见 [2026-10-18 用户原话记录](https://github.com/Newchanlun/NewChanlun/issues/1323#issuecomment-6261281111)：「其实很多技术的东西 完全不需要我来做 我完全信任你的判断」。T 类依据为现有隔离合同的技术接口修订，`user_gate=[]`。异家族非作者独审尚未做；此稿不是凭据、权限或外部操作签署，保留 ADR 0041 硬门。

## 引用自证

| 引用 | 核实命令 | 结果摘要 |
|---|---|---|
| ADR 0039 :283–287,371 | `nl -ba docs/adr/0039-production-entry-inventory-and-unique-launcher.md` 对应行 | 生产由唯一 launcher 拉域；凭据只写 X；B13 指定测试。 |
| ADR 0062 :9,37–41,147 | `nl -ba docs/adr/0062-fu18-venue-account-permission-binding.md` 对应行 | /2 字段改名，只管管道；授权硬门未撤销。 |
| ADR 0048 :311,460–466 | `nl -ba docs/adr/0048-legacy-engine-module-level-dispositions.md` 对应行 | 旧 Python 键不收编；字段别名按 #1540 解释。 |
| ADR 0041 :9–15,39–48 | `nl -ba docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md` 对应行 | 事前选值；失败不得换判据；实际权限须用户授权。 |
| CONTEXT.md :370,403–408 | `nl -ba CONTEXT.md` 对应行 | 作用域政策、管道字段和权限证据三层分开。 |
| doctrine-rules.md :43–58,60–80 | `nl -ba docs/agents/doctrine-rules.md` 对应行 | 同一判断不做宽严接管；同输入输出一致。 |
| production_session.rs :98–105,177–192,216–225,251–277,370–448 | `nl -ba rust/src/bin/production_session.rs` 对应行 | 非空、read_to_string、clean/env_clear、S/E/B 后 X 注入。 |
| x_execution_session.rs :37–63,193–229 | `nl -ba rust/src/bin/x_execution_session.rs` 对应行 | 非空；先锁/库/持久化，再 var_os。 |
| store.rs :470–516,527–534 | `nl -ba rust/src/economic_session/store.rs` 对应行 | macOS statfs；其余 stat 命令接在 SQLite open 之前。 |
| `bf8e6dfe` 候选 store.rs :505–518 | `git show bf8e6dfe:rust/src/economic_session/store.rs` 后编号 | Linux 逐键移除，保留 PATH，仍用标准库 output。 |
| R4 REPORT.md :9–13,38–41,65–67 | `nl -ba /Users/silencehan/.t3/evidence/issue2113-stat-child-env/non-author-astra-bf8e6dfe/REPORT.md` | HIGH 编码、MED 枚举、重复键与字面 PATH 实测。 |
| #2134 评论 7047583818 | `gh api repos/Newchanlun/NewChanlun/issues/comments/7047583818` | 作者 xy7365527-lang；更正旧正文顺序、列出五点。 |
| #2113 评论 7047584698 | `gh api repos/Newchanlun/NewChanlun/issues/comments/7047584698` | 同作者；R4 BLOCK 并等 #2134。前四轮上下文以 `gh issue view 2113 --comments` 核。 |
| #1383 评论 7040986467 | `gh api repos/Newchanlun/NewChanlun/issues/comments/7040986467` | 同作者；B13 取样提交、#2113 与记录键集的分工。 |
| #1323 评论 6261281111 | `gh api repos/Newchanlun/NewChanlun/issues/comments/6261281111` | 同作者；Notes N-1 与用户原话。 |
| #2134、#2113、#1383、#1365 原生关系 | `gh api repos/Newchanlun/NewChanlun/issues/2134/parent` 及 `gh api repos/Newchanlun/NewChanlun/issues/{2113,1383}/dependencies/blocked_by`（分开执行） | 父票 #1365；#2113 等 #2134；#1383 等 #2113。 |
| #1769、#1770、#1561 | `gh issue view <号码> -R Newchanlun/NewChanlun --json number,title,state,url,body,comments,labels`（各自执行） | 骨架、X 离线 adapter、P2 不激活分别有既定范围；本票不改。 |

## 考古对照

| 点 | 归类 | 出处 | 草稿处置 |
|---|---|---|---|
| Q1 | B | 0039 :287；runbook :72；主线键盘点 | 专用名由惯例变成有界命名空间；比较三种形状。 |
| Q2 | C decision | R4 反例；T09–11；G2–4 | 不设名单；由专用空间切断控制键冲突。 |
| Q3 | B | 作者 PATH 读数、本次 Boat、G1/G6/G7 | 可启动与正当配置分列；单个仓内占位迁移，私有部署只在切换前由 owner 核。 |
| Q4 | B | 双入口非空先例；#2113 R3 提案已撤回；0062 :40 | 同类、同判据、同一相对时点，无兼容旁路。 |
| Q5 | B | #2113 R4、#1383 B13 | HIGH 关在 profile；MED 交 #2113 清理，证据通过后才签交付句。 |
| Q6 | A | 0041 :39–48；0062 :9,40；0048 :464–466 | 只裁部署键，不变作用域、真实授权及旧入口名分。 |

```canonical_edit
{"version":1,"operation":"edit","path":"docs/adr/0039-production-entry-inventory-and-unique-launcher.md","replacements":[{"before":"2. **启动门。** :287-288 对 `experiment` profile 同样生效（ADR 0062 裁定五），作为独立的发送前置件，不是 ADR 0045 SR-3 的失效触发，拒发不产生 SR-3 记录。X 按 ADR 0062「发送门（8 步）」核验，拒发词汇按 ADR 0062 裁定六。拒发在当前 `writer_epoch` 内为终态并拦截一切写请求（ADR 0062 裁定七），**仅对 `P1-hl-testnet`（`experiment`）签署**；production（P2）下拒发期间撤单、reduce-only 平仓与急停是否放行是真金取舍，属 P 类，在 P2 激活时另裁（#1561 后继），本条不预裁。\n","after":"2. **启动门。** :287-288 对 `experiment` profile 同样生效（ADR 0062 裁定五），作为独立的发送前置件，不是 ADR 0045 SR-3 的失效触发，拒发不产生 SR-3 记录。X 按 ADR 0062「发送门（8 步）」核验，拒发词汇按 ADR 0062 裁定六。拒发在当前 `writer_epoch` 内为终态并拦截一切写请求（ADR 0062 裁定七），**仅对 `P1-hl-testnet`（`experiment`）签署**；production（P2）下拒发期间撤单、reduce-only 平仓与急停是否放行是真金取舍，属 P 类，在 P2 激活时另裁（#1561 后继），本条不预裁。\n\n## 修订（#2134，X 凭据注入键名，2026-11-20）\n\n1. **键名。** X 执行 profile 必须显式指定一个凭据注入键。推荐 `NC_X_VENUE_CREDENTIAL`；也可在该名字后加一个下划线和一个非空后缀。后缀首字节须为 ASCII 字母或数字，其余字节只许 ASCII 字母、数字或下划线；全名最多 64 字节，区分大小写，按原字节使用。空名、等号、NUL、空白、非 ASCII 和专用命名空间外的名字一律不合法。该命名空间只用于 X 凭据注入，不作查找路径、动态加载或其他进程控制变量；不维护逐项禁止名单。在 Linux/macOS 的 `name=value` 启动环境中，首个等号就是键值分隔符；合规名字只编码为同名键，不可能编码成 `PATH`。\n2. **入口与拒绝。** launcher 装读 X profile 与 X 自己读 profile 的 `serve`（含单独启动）用同一个键名谓词。旧 `x-execution-profile/1` 的 `credential_scope.env` 与 [ADR 0062](0062-fu18-venue-account-permission-binding.md) 的 `x-execution-profile/2` 的 `credential_source.env` 同口径。各版本只取自己定义的字段，任何模式均不得用旧字段、默认值、别名、去空白或大小写转换挽救不合法值。缺字段、非字符串或不合规均报 `InvalidDomain`；launcher 在读凭据文件、创建状态及启动任何域（含 init）前拒绝，X 在持写者锁、开库或取环境凭据前拒绝。拒绝信息指出字段及合法形状，不回显原输入或凭据。\n3. **隔离与生效。** 本修订只限名字，不改凭据来源、作用域、发送门、交易与账本判据。读用真实凭据和授予权限仍按 [ADR 0041](0041-degrees-of-freedom-configurable-not-excluded.md) 的独立用户授权；文书裁定不代签。现有配置若取命名空间外的名字，部署方须在启用新版本前改成合规名字并同步已有获授权的注入配置，不设旧配置豁免。键名校验和 Linux `stat` 子进程环境收口由 #2113 一并实现；本节不把校验等同于清理单启 X 时外部传入的原始环境，也不把文书合入当作验收 13 已通过。\n"}]}
```

ADR 0062 的文末追加合同（含首个空行）：

```adr_0062_append

## 修订（#2134，凭据注入键名指针，2026-11-20）

（append-only：以上原文不改；本节仅同步 #2134 指针，已裁 P 类正文与授权硬门照旧。）

本 ADR 第 40、147 行的 `credential_source.env` 指定注入键名，沿用 [ADR 0039「修订（#2134）」](0039-production-entry-inventory-and-unique-launcher.md#修订2134x-凭据注入键名2026-11-20) 的同一准入规则与前置 `InvalidDomain`。字段改名不另立键名判据，也不授予凭据接触权限。
```
