# #2079 第五稿考古

固定基线：b9d898dccf46c2a716115eaa1215bc39c458a959。A 6 / B 4 / C 3。tracker 含已关闭票及评论。逐条原始输出见 queries/。C 类全为 decision，无未补仓外事实缺口。

## Q1 [A] 正式入口、域身份及写锁归属

- repo（12 命中）： `git grep -I -n -E '唯一 launcher|每个域有自己的|不持任何域的写者身份' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（11 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"唯一 launcher" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：ADR 0039:273–287；SPEC C09.1–2；#1530（已关）。
- 依据：0039 第三节明确各域各自 DB、锁与代，仅 launcher 装配；#1530 是现成裁定，#1823/#2079 探讨名字不改这条。
- 沿用：沿用逐域独占进程锁，不把传输层或 launcher 变成域写者。

## Q2 [A] S 测量域、旧首错和直绑边界

- repo（23 命中）： `git grep -I -n -E '测量边界|不比较 .s.socket|S 族条目' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"测量域" "socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：ADR 0059:95–121；#1818 resolution 6550813315；#1781。
- 依据：P 本身、A 树及 S 族路径/子树才属 M；并发域库与锁和 E/B socket 须过 `Q1–Q5` 排除；S 自己 socket 在 driver open 后 bind 的例外不把改名也放进去。0059:107 的代码行号是历史行锚；本轮以 main :57–81 核实际锁。
- 沿用：原 M 与 R4 沿用；只在 M 外做 S 的新认领。

## Q3 [B] OBS 第一错误、存活与路径替换负控

- repo（313 命中）： `git grep -I -n -E 'SAFE-RACE|socket路径已占用|残留 socket|孤儿' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（5 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：[#1823 OBS](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294)，[SAFE-RACE 回勘](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)，cc674e88:sources/1823-safe-original.md。
- 依据：#1823 已观察三布局两构建全拒，S 首错是参数期占用，不是 bind 或 admission；先前建议 PID 后按名清理遭有效反例。SAFE 不是获审实现合同，但可作为二值验收底本。
- 采纳默认：保留 LIVE/UNKNOWN/RACE/ADMISSION；SAFE-STALE 以同锁、钉住对象和退役而非 PID/boot 与 unlink 验收。
- 与先例或简报的冲突：原 SAFE 草案写了 PID/boot 与 unlink；产品不得接这条动作权限。

## Q4 [C] 名字 owner、钉住对象、发布／退役与中断窗口

- repo（0 命中）： `git grep -I -n -E 'endpoint-owner/1|端点名.*写者锁|退役名|RENAME_NOREPLACE' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（8 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"退役名" OR "端点归属" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：ADR 0059:117 留空；#2079 返修评论 7046963728；probe-ext4.log；probe/supplement.py。
- 依据：没有在案 owner/退役规则。#2079 历史提案与 #2128/#2129/#2130 命中只参照本题，其他检索命中不涉会话端点。ext4 试验显示原地连接残留拒、锁归还、钉住身份保留，且未钉 inode 可复用；替换文件名的普通 rename 会移除被换入的 socket，必须避开。
- 裁定推荐：用单个 owner、空址与可核残留的确定性表；钉住普通 owner FD 更新，不按名覆盖；退役 NOREPLACE 后核对象，不符原样放回或保留到 #2130。半写或不明拒绝。
- 已搜：endpoint-owner/1、端点名.*写者锁、退役名、RENAME_NOREPLACE；缺口去向：decision。
- 与先例或简报的冲突：简报 owner 临时文件覆盖不满足零毁损；补探针验证 pinned FD 写不会触碰换入 socket。

## Q5 [C] E/B 干净关库标记、事务与 SPEC 的恢复语义

- repo（11 命中）： `git grep -I -n -E 'clean_close/1|正常关库|从旧 Open 恢复' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"正常关库" OR "clean_close" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- repo（10 命中）： `git grep -I -n -E '本地状态恢复|持久.*退出|正常列|有序关停' b9d898dccf -- docs/adr .chanlun/definitions`

- 命中与出处：SPEC C09.9/11、IC:62；#2077 service.rs:1521–1568、transport:797–809；#2082 store.rs:70、:786–835、:967–1084、:1694–1743。
- 依据：#1823/#2079/#1411 命中均未裁库内关库证据。主库 schema 只固定表和 DDL，audit 逐键核身份与代、逐步重放，不枚举 meta 键全集；#2082 recovery.rs:148–153 已加具名 meta 键作为先例。同域停机返回不是 launcher 事件出证。
- 裁定推荐：init、升代事务、规定关停后三处写本代标记；持锁、当前代和全史重验后核标记，bind、认领持久化后首个 accept 前消费。无标记须正式恢复；不自动回退。
- 已搜：clean_close/1、正常关库、从旧 Open 恢复；缺口去向：decision。

## Q6 [C] E/B 部分缺库与子集计划的代闭合

- repo（6 命中）： `git grep -I -n -E 'current-recovery|launcher-economic-recovery/1|经济恢复计划|部分缺失' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（1 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"恢复计划" OR "部分缺失" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：main production_session.rs:276–320；#2082 production_session.rs:249–342、:553–584；store.rs:659–663；service.rs:905–926。
- 依据：B/ E 原来单独 init，S 夹具先单独 init/锚（#2077 test:461–470）；缺部分不可当首启。#2082 用当前回执而非库整数授权；launcher 不持域锁，域 serve 在实际持锁后再核自己代。B 在读取 E 原事实事务中核配置下 E 的有效代，不提前审健康 E。
- 裁定推荐：任一 init 前判 E/所有 B 为全有或全无，部分缺即拒；计划只允许已声明 E/B 的子集；省略项用 manifest，已列且核验失败即失败。B 来源用 E 的有效代。
- 已搜：current-recovery、launcher-economic-recovery/1、经济恢复计划、部分缺失；缺口去向：decision。
- 与先例或简报的冲突：全集改子集扩大计划形状，不能叫 launcher 纯新增拒绝；域代校验仍完整。

## Q7 [B] S 强杀后的介质、有效代归谁

- repo（3 命中）： `git grep -I -n -E 'UnsupportedWalShmJournalCombination|SHM.*再准入|未完成Begin' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（4 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"SHM" "再准入" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：main S admission_provider.rs:231–233、audit_owner.rs:1198；#2128（open）；#1823 OBS；#1375 被测基线 b9d898dc 的 Linux run-3。
- 依据：已知 SHM 不满足 R4；#1823 OBS 被 socket 门先挡，不能冒称 R4 实测。另一 Linux 运行在旧 launcher 用信号收尾、夹具先移除旧 socket 后，重启确观察到该 R4 诊断；不是 #2077 后的强杀同址续服。#1675 是签锚成功凭证，#1527 是准入消费与失败收据，不裁恢复重准入。
- 采纳默认：本票保持 R4、Begin 与原代；合法残留的预筛可放行但门先于正式退役，介质与代交接由 #2128 裁。

## Q8 [B] 升代后的 X 权威配置与 E 授权来源

- repo（4 命中）： `git grep -I -n -E 'authority_profile|authority_epoch|authorized_sources' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"authority_epoch" OR "权威代" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：main history_simulation/runtime.rs:506–517、:815–826；store.rs:214–243、:359–373；#2129；x-epoch.log。
- 依据：E 的回复通过现任 producer_epoch 进入信封；X 用冻结的 e/s 代重建期望信封；受控真 E/E recover/真 X 证实 E 1→2 后 X 从正常处理同代权威错误变为 IdentityConflict，X 状态 NoRecord。没有解消费已升代的 E 或 S。
- 采纳默认：保留本地 X 启动门；权威代跟随、E 的 authorized_sources 与在途责任交 #2129。

## Q9 [A] 在线故障隔离与单域原址重拉分界

- repo（55 命中）： `git grep -I -n -E '单域原址|故障隔离|单域.*重启' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（4 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"单域" "重启" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- tracker（35 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"故障隔离" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：SPEC C09.3；#1363、#1376、#1396、#1409、#1417、#1423；#2120 顶部修订。
- 依据：既有隔离义务不依赖新的端点模式。#2120 是另立的原址在线重拉决策，仍需三问；native #2079 只 blocking #2120，#2120 挂 #1363。
- 沿用：原隔离合同照旧，#2120 承接在线重拉，与 #1411 整会话重启分开。

## Q10 [A] 拒绝、孤儿和同 UID 外部操作的归属

- repo（2 命中）： `git grep -I -n -E '结束孤儿|退役对象|拒绝态清场|手工用生产库' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（7 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"结束孤儿" OR "退役对象" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：ADR 0039:286、0041:39–48；#2130 正文；#2079 评论 7046963728。
- 依据：0039 把手拉域 bin 排除交 TB-09；0041 不授权外部动作。#2130 已承接停止孤儿、拒绝态清场、目录整改、退役对象清理且不直接阻 #1411。
- 沿用：只规范产品不毁 socket 与不换路；同 UID 越权隔离与真实运维沿既有授权，留拒绝现场。

## Q11 [A] 原路径复用与提交根另裁

- repo（20 命中）： `git grep -I -n -E '一一重命名|bundle_raw_utf8|提交根' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（1 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"绝对路径" "提交根" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：#1411 验收、SPEC C10.4；#2127 正文第 4 问。
- 依据：路径同字节是本票原 manifest 验收；路径是否进 E/B 根、X 冻结 profile 的持久语义尚由 #2127 承接，不把其候选当结论。
- 沿用：原址字节不变、提交根政策不动。

## Q12 [A] 分级、拒绝边界和生效授权

- repo（62 命中）： `git grep -I -n -E '不授予|代理独审裁定|同一判断不得有宽严两档' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（48 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"代理独审裁定" OR "收敛通则" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：graph-engineering.md:25–44；ADR 0041:39–48；doctrine-rules.md:43–54；#1909。
- 依据：新增端点政策和持久标记无在案裁定；不启用真实账户/凭据/外部操作。没有“正式门失败则改直绑”分档。在不适用布局保留旧合同按输入范围事先判；有残留仍拒。
- 沿用：P，user_gate 空，依 #1909 非 UserSigned；本工作只提交供独审核的候选。

## Q13 [B] 验收入口、先合头与受影响票

- repo（61 命中）： `git grep -I -n -E 'production_session_entry|完整历史回放.*重启|同一输入档案' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（61 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"双跑" "恢复" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 命中与出处：CI ci.yml:811、:830–841；#1411、#2077、#2082；edges.txt、adr-number-check.txt。
- 依据：既有两种构建的真 launcher 测试同文件。#2077 :934 起的夹具仅 S/E/B socket，X 骨架无本地监听；本稿四域正控要加有本地监听的 simulation X。#2082 仍为草稿头，当前原生子票与 blocking 回读在证据里。
- 采纳默认：沿九个具名测试和精确头序；结构成功不等于整链通过；0065 只在决策 branch 新建。

## 四轮独审到第五稿的覆盖

- 666a1a42：不延用监听 FD、不准备用证明；分支只新增 ADR，本文与 canonical_plan 可逐字比，具名验收给成功与失败。
- c061b667：不新增杀孤儿权限，不借备份或日志当已有资格；TB-05 与在线重拉各自有票。
- 1a2be7e6：域退出证据不靠 launcher 日志。E/B 的标记与持久 writer_epoch 同库；旧标记在 accept 前已消费。
- 173fff70：不存在模式切换或首次受管入口。旧库无标记、一侧缺库、owner 不明、写到一半，分别有显式去向和负控。

## 证据的使用边界

Boat 两次均是 Linux x86_64 6.8.0-117-generic、ext4。原脚本输出在 probe-ext4.log；补探针说明为什么 owner 不能用按名覆盖。未在 macOS 复跑、未运行未来 #1411 实现或 Rust 构建。X 定向用例来自主线的现成 Linux E/X 生产 bin（#1375 run-3 的 b9d898dc 构建），在 OrbStack Linux 无网隔离容器运行；用真 E 懂得封装的业务拒绝做同代对照，真杀 E、正式 recover 和相同 X 的信封差异只验出 #2129 缺口。夹具移动的是自己旧 E 的监听残留，不代表产品已实现退役。脚本 x_helpers.py 是当前主线 history_simulation_entry.py 的辅助函数原样前缀。
