# #2079 第五稿考古（一次重做）

固定基线：b9d898dccf46c2a716115eaa1215bc39c458a959。A 6 / B 5 / C 2。tracker 含已关闭票及评论。逐条原始输出见 queries/。C 类全为 decision，无未补仓外事实缺口。

## Q1 [A] 正式入口、域身份及写锁归属

- repo（12 命中）： `git grep -I -n -E '唯一 launcher|每个域有自己的|不持任何域的写者身份' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（11 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"唯一 launcher" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：ADR 0039:273–287；SPEC C09.1–2；#1530（已关）；#1895 关票说明 6727386306；session_transport.rs:42–81
  - ADR 0039:273–287；SPEC C09.1–2；#1530（已关）：0039 第三节明确各域各自 DB、锁与代，仅 launcher 装配；#1530 是现成裁定，#1823/#2079 探讨名字不改这条。
  - https://github.com/Newchanlun/NewChanlun/issues/1895#issuecomment-6727386306：#2007 与 #2010/#2008 修复已入 main；guard 析构显式解锁。
- 依据：0039 第三节明确各域各自 DB、锁与代，仅 launcher 装配；#1530 是现成裁定，#1823/#2079 探讨名字不改这条。 #1895 的修复在 guard 析构时显式解锁；重新取得同一文件的锁不证明前代 PID 消失。
- 沿用：沿用逐域独占进程锁，不把传输层或 launcher 变成域写者。 guard 最后释放，覆盖监听关闭、标记事务与关库。

## Q2 [A] S 测量域、旧首错和直绑边界

- repo（23 命中）： `git grep -I -n -E '测量边界|不比较 .s.socket|S 族条目' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"测量域" "socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：ADR 0059:95–121；#1818 resolution 6550813315；#1781
  - ADR 0059:95–121；#1818 resolution 6550813315；#1781：P 本身、A 树及 S 族路径/子树才属 M；并发域库与锁和 E/B socket 须过 `Q1–Q5` 排除；S 自己 socket 在 driver open 后 bind 的例外不把改名也放进去。0059:107 的代码行号是历史行锚；本轮以 main :57–81 核实际锁。
- 依据：P 本身、A 树及 S 族路径/子树才属 M；并发域库与锁和 E/B socket 须过 `Q1–Q5` 排除；S 自己 socket 在 driver open 后 bind 的例外不把改名也放进去。0059:107 的代码行号是历史行锚；本轮以 main :57–81 核实际锁。 现行 0059:109 只列 E/B socket，不列 simulation X；X 无 S 准入输入。
- 沿用：原 M 与 R4 沿用；只在 M 外做 S 的新认领。 simulation X 的本地 socket 路径不布在 M 内，核查与整改归 #2130，不加跨域运行时闸。

## Q3 [B] OBS 第一错误、存活与路径替换负控

- repo（313 命中）： `git grep -I -n -E 'SAFE-RACE|socket路径已占用|残留 socket|孤儿' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（5 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- repo（244 命中）： `git grep -I -n -E 'ECONNREFUSED|prepare_socket|unlink|control-owner|清理' b9d898dccf -- s_session/s_service_control.py s_session/economic_service_control.py docs/adr .chanlun/review-results`
- tracker（8 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"ECONNREFUSED" OR "prepare_socket" OR "control-owner" OR "残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- tracker（1 命中）： `gh issue view 1372 --repo Newchanlun/NewChanlun --json url,number,title,state,body,comments`

- 出处：[#1823 OBS](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294)，[SAFE-RACE 回勘](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)，cc674e88:sources/1823-safe-original.md；main s_session/s_service_control.py:498–528、:712–729、s_session/economic_service_control.py:83–95；#1372 PY-XR-02（.chanlun/review-results/issue1372-tb01c-20260913/reports/python-cross-review-fix-01/REVIEW.md:8）
  - [#1823 OBS](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294)，[SAFE-RACE 回勘](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)，cc674e88:sources/1823-safe-original.md：#1823 已观察三布局两构建全拒，S 首错是参数期占用，不是 bind 或 admission；先前建议 PID 后按名清理遭有效反例。SAFE 不是获审实现合同，但可作为二值验收底本。
  - main s_session/s_service_control.py:498–528、:712–729、s_session/economic_service_control.py:83–95；#1372 PY-XR-02（.chanlun/review-results/issue1372-tb01c-20260913/reports/python-cross-review-fix-01/REVIEW.md:8）：S 与 E/B 独立控制器调用 prepare_socket；:527 在按名重核后 unlink。
- 依据：#1823 已观察三布局两构建全拒，S 首错是参数期占用，不是 bind 或 admission；先前建议 PID 后按名清理遭有效反例。SAFE 不是获审实现合同，但可作为二值验收底本。 #1372 控制器先例经限定复核：允许自有失活路径，拒绝未知登记、换 inode 与活监听。复核没有穷尽最后一次核验之后到 unlink 之间的替换窗口。
- 采纳默认：保留 LIVE/UNKNOWN/RACE/ADMISSION；SAFE-STALE 以同锁、钉住对象和退役而非 PID/boot 与 unlink 验收。 保留旧工具的拒绝先例，不把其删名方式移植进正式合同。
- 与先例或简报的冲突：原 SAFE 草案写了 PID/boot 与 unlink；产品不得接这条动作权限。

## Q4 [B] 名字 owner、钉住对象、发布／退役与中断窗口

- repo（0 命中）： `git grep -I -n -E 'endpoint-owner/1|端点名.*写者锁|退役名|RENAME_NOREPLACE' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（8 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"退役名" OR "端点归属" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- repo（244 命中）： `git grep -I -n -E 'ECONNREFUSED|prepare_socket|unlink|control-owner|清理' b9d898dccf -- s_session/s_service_control.py s_session/economic_service_control.py docs/adr .chanlun/review-results`
- tracker（8 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"ECONNREFUSED" OR "prepare_socket" OR "control-owner" OR "残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- tracker（1 命中）： `gh issue view 1372 --repo Newchanlun/NewChanlun --json url,number,title,state,body,comments`

- 出处：main s_session/s_service_control.py:498–528、:712–729、s_session/economic_service_control.py:83–95；#1372 PY-XR-02（.chanlun/review-results/issue1372-tb01c-20260913/reports/python-cross-review-fix-01/REVIEW.md:8）；#1823 comment 6994092216；ADR 0059:117；probe-ext4.log
  - main s_session/s_service_control.py:498–528、:712–729、s_session/economic_service_control.py:83–95；#1372 PY-XR-02（.chanlun/review-results/issue1372-tb01c-20260913/reports/python-cross-review-fix-01/REVIEW.md:8）：已停止的 owner 记录、dev/ino/uid、仅接 ECONNREFUSED、删前同身份复核，最后路径 unlink。
  - #1823 comment 6994092216；probe-ext4.log：最后一次按名核验不排除随后被换入对象；NOREPLACE 后比较钉住 dev/ino，不销毁换入对象。
- 依据：旧控制器有以停止记录和已登记身份处置残留的在案做法，不是正式唯一 launcher 的规范。PY-XR-02 闭合限所测四臂；#1823 的并发边界另外否决核后按名删。ext4 读数支持钉住、仅接 ECONNREFUSED、移动后用 dev/ino 复核；owner 更新按 FD 以避免覆盖被换入的 socket。
- 采纳默认：采用独立工具边界。借用拒绝存活/未知对象的判据，不把停机记录或核后按名 unlink 作为正式域所有权。正式域只在持锁、钉住失活对象后按 NOREPLACE 改名并复核。两个 Python 控制器不得用于本合同管辖的端点目录；独立 E/B stop 再 start 仍经正式恢复与有效代。
- 与先例或简报的冲突：旧 Python 工具可 unlink；本票选独立工具边界，不改 Python 或将它作为正式入口。

## Q5 [C] E/B 干净关库标记、事务与 SPEC 的恢复语义

- repo（11 命中）： `git grep -I -n -E 'clean_close/1|正常关库|从旧 Open 恢复' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"正常关库" OR "clean_close" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- repo（10 命中）： `git grep -I -n -E '本地状态恢复|持久.*退出|正常列|有序关停' b9d898dccf -- docs/adr .chanlun/definitions`

- 出处：SPEC C09.9/11、IC:62；#2077 service.rs:1521–1568、transport:797–809；#2082 store.rs:70、:786–835、:967–1084、:1694–1743
  - SPEC C09.9/11、IC:62；#2077 service.rs:1521–1568、transport:797–809；#2082 store.rs:70、:786–835、:967–1084、:1694–1743：#1823/#2079/#1411 命中均未裁库内关库证据。主库 schema 只固定表和 DDL，audit 逐键核身份与代、逐步重放，不枚举 meta 键全集；#2082 recovery.rs:148–153 已加具名 meta 键作为先例。同域停机返回不是 launcher 事件出证。
- 依据：#1823/#2079/#1411 命中均未裁库内关库证据。主库 schema 只固定表和 DDL，audit 逐键核身份与代、逐步重放，不枚举 meta 键全集；#2082 recovery.rs:148–153 已加具名 meta 键作为先例。同域停机返回不是 launcher 事件出证。
- 裁定推荐：init、升代事务、规定关停后三处写本代标记；持锁、当前代和全史重验后核标记，bind、认领持久化后首个 accept 前消费。无标记须正式恢复；不自动回退。 消费属于所有 bind 路径的共同接纳前门，非 Linux 和不适用认领的直绑也必须消费；先前旧二进制开服或恢复备份时，授权运维先正式恢复。
- 已搜：clean_close/1、正常关库、从旧 Open 恢复；缺口去向：decision。

## Q6 [C] E/B 部分缺库与子集计划的代闭合

- repo（6 命中）： `git grep -I -n -E 'current-recovery|launcher-economic-recovery/1|经济恢复计划|部分缺失' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（1 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"恢复计划" OR "部分缺失" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：main production_session.rs:276–320；#2082 production_session.rs:249–342、:553–584；store.rs:659–663；service.rs:905–926
  - main production_session.rs:276–320；#2082 production_session.rs:249–342、:553–584；store.rs:659–663；service.rs:905–926：B/ E 原来单独 init，S 夹具先单独 init/锚（#2077 test:461–470）；缺部分不可当首启。#2082 用当前回执而非库整数授权；launcher 不持域锁，域 serve 在实际持锁后再核自己代。B 在读取 E 原事实事务中核配置下 E 的有效代，不提前审健康 E。
- 依据：B/ E 原来单独 init，S 夹具先单独 init/锚（#2077 test:461–470）；缺部分不可当首启。#2082 用当前回执而非库整数授权；launcher 不持域锁，域 serve 在实际持锁后再核自己代。B 在读取 E 原事实事务中核配置下 E 的有效代，不提前审健康 E。
- 裁定推荐：任一 init 前判 E/所有 B 为全有或全无，部分缺即拒；计划只允许已声明 E/B 的子集；省略项用 manifest，已列且核验失败即失败。B 来源用 E 的有效代。
- 已搜：current-recovery、launcher-economic-recovery/1、经济恢复计划、部分缺失；缺口去向：decision。
- 与先例或简报的冲突：全集改子集扩大计划形状，不能叫 launcher 纯新增拒绝；域代校验仍完整。

## Q7 [B] S 强杀后的介质、有效代归谁

- repo（3 命中）： `git grep -I -n -E 'UnsupportedWalShmJournalCombination|SHM.*再准入|未完成Begin' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（4 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"SHM" "再准入" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：main S admission_provider.rs:231–233、audit_owner.rs:1198；#2128（open）；#1823 OBS；#1375 被测基线 b9d898dc 的 Linux run-3
  - main S admission_provider.rs:231–233、audit_owner.rs:1198；#2128（open）；#1823 OBS；#1375 被测基线 b9d898dc 的 Linux run-3：已知 SHM 不满足 R4；#1823 OBS 被 socket 门先挡，不能冒称 R4 实测。另一 Linux 运行在旧 launcher 用信号收尾、夹具先移除旧 socket 后，重启确观察到该 R4 诊断；不是 #2077 后的强杀同址续服。#1675 是签锚成功凭证，#1527 是准入消费与失败收据，不裁恢复重准入。
- 依据：已知 SHM 不满足 R4；#1823 OBS 被 socket 门先挡，不能冒称 R4 实测。另一 Linux 运行在旧 launcher 用信号收尾、夹具先移除旧 socket 后，重启确观察到该 R4 诊断；不是 #2077 后的强杀同址续服。#1675 是签锚成功凭证，#1527 是准入消费与失败收据，不裁恢复重准入。
- 采纳默认：本票保持 R4、Begin 与原代；合法残留的预筛可放行但门先于正式退役，介质与代交接由 #2128 裁。

## Q8 [B] 升代后的 X 权威配置与 E 授权来源

- repo（4 命中）： `git grep -I -n -E 'authority_profile|authority_epoch|authorized_sources' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（3 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"authority_epoch" OR "权威代" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：main history_simulation/runtime.rs:506–517、:815–826；store.rs:214–243、:359–373；#2129；x-epoch.log；x-epoch-boat.log
  - main history_simulation/runtime.rs:506–517、:815–826；store.rs:214–243、:359–373；#2129；x-epoch.log：E 的回复通过现任 producer_epoch 进入信封；X 用冻结的 e/s 代重建期望信封；受控真 E/E recover/真 X 证实 E 1→2 后 X 从正常处理同代权威错误变为 IdentityConflict，X 状态 NoRecord。没有解消费已升代的 E 或 S。
- 依据：E 的回复通过现任 producer_epoch 进入信封；X 用冻结的 e/s 代重建期望信封；受控真 E/E recover/真 X 证实 E 1→2 后 X 从正常处理同代权威错误变为 IdentityConflict，X 状态 NoRecord。没有解消费已升代的 E 或 S。 原始 OrbStack 输出与 Boat ext4 重跑一致；后者记录 uname 和 findmnt，且未继承环境。
- 采纳默认：保留本地 X 启动门；权威代跟随、E 的 authorized_sources 与在途责任交 #2129。

## Q9 [A] 在线故障隔离与单域原址重拉分界

- repo（55 命中）： `git grep -I -n -E '单域原址|故障隔离|单域.*重启' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（4 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"单域" "重启" in:title,body,comments' --state all --limit 100 --json number,state,title,url`
- tracker（35 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"故障隔离" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：SPEC C09.3；#1363、#1376、#1396、#1409、#1417、#1423；#2120 顶部修订
  - SPEC C09.3；#1363、#1376、#1396、#1409、#1417、#1423；#2120 顶部修订：既有隔离义务不依赖新的端点模式。#2120 是另立的原址在线重拉决策，仍需三问；native #2079 只 blocking #2120，#2120 挂 #1363。
- 依据：既有隔离义务不依赖新的端点模式。#2120 是另立的原址在线重拉决策，仍需三问；native #2079 只 blocking #2120，#2120 挂 #1363。
- 沿用：原隔离合同照旧，#2120 承接在线重拉，与 #1411 整会话重启分开。

## Q10 [A] 拒绝、孤儿和同 UID 外部操作的归属

- repo（2 命中）： `git grep -I -n -E '结束孤儿|退役对象|拒绝态清场|手工用生产库' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（7 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"结束孤儿" OR "退役对象" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：ADR 0039:286、0041:39–48；#2130 正文；#2079 评论 7046963728
  - ADR 0039:286、0041:39–48；#2130 正文；#2079 评论 7046963728：0039 把手拉域 bin 排除交 TB-09；0041 不授权外部动作。#2130 已承接停止孤儿、拒绝态清场、目录整改、退役对象清理且不直接阻 #1411。
- 依据：0039 把手拉域 bin 排除交 TB-09；0041 不授权外部动作。#2130 已承接停止孤儿、拒绝态清场、目录整改、退役对象清理且不直接阻 #1411。
- 沿用：只规范产品不毁 socket 与不换路；同 UID 越权隔离与真实运维沿既有授权，留拒绝现场。

## Q11 [A] 原路径复用与提交根另裁

- repo（20 命中）： `git grep -I -n -E '一一重命名|bundle_raw_utf8|提交根' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（1 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"绝对路径" "提交根" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：#1411 验收、SPEC C10.4；#2127 正文第 4 问
  - #1411 验收、SPEC C10.4；#2127 正文第 4 问：路径同字节是本票原 manifest 验收；路径是否进 E/B 根、X 冻结 profile 的持久语义尚由 #2127 承接，不把其候选当结论。
- 依据：路径同字节是本票原 manifest 验收；路径是否进 E/B 根、X 冻结 profile 的持久语义尚由 #2127 承接，不把其候选当结论。
- 沿用：原址字节不变、提交根政策不动。

## Q12 [A] 分级、拒绝边界和生效授权

- repo（62 命中）： `git grep -I -n -E '不授予|代理独审裁定|同一判断不得有宽严两档' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（48 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"代理独审裁定" OR "收敛通则" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：graph-engineering.md:25–44；ADR 0041:39–48；doctrine-rules.md:43–54；#1909
  - graph-engineering.md:25–44；ADR 0041:39–48；doctrine-rules.md:43–54；#1909：新增端点政策和持久标记无在案裁定；不启用真实账户/凭据/外部操作。没有“正式门失败则改直绑”分档。在不适用布局保留旧合同按输入范围事先判；有残留仍拒。
- 依据：新增端点政策和持久标记无在案裁定；不启用真实账户/凭据/外部操作。没有“正式门失败则改直绑”分档。在不适用布局保留旧合同按输入范围事先判；有残留仍拒。
- 沿用：P，user_gate 空，依 #1909 非 UserSigned；本工作只提交供独审核的候选。

## Q13 [B] 验收入口、先合头与受影响票

- repo（61 命中）： `git grep -I -n -E 'production_session_entry|完整历史回放.*重启|同一输入档案' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`
- tracker（61 命中）： `gh issue list --repo Newchanlun/NewChanlun --search '"双跑" "恢复" in:title,body,comments' --state all --limit 100 --json number,state,title,url`

- 出处：CI ci.yml:811、:830–841；#1411、#2077、#2082；edges.txt、adr-number-check.txt
  - CI ci.yml:811、:830–841；#1411、#2077、#2082；edges.txt、adr-number-check.txt：既有两种构建的真 launcher 测试同文件。#2077 :934 起的夹具仅 S/E/B socket，X 骨架无本地监听；本稿四域正控要加有本地监听的 simulation X。#2082 仍为草稿头，当前原生子票与 blocking 回读在证据里。
- 依据：既有两种构建的真 launcher 测试同文件。#2077 :934 起的夹具仅 S/E/B socket，X 骨架无本地监听；本稿四域正控要加有本地监听的 simulation X。#2082 仍为草稿头，当前原生子票与 blocking 回读在证据里。
- 采纳默认：沿九个具名测试和精确头序；结构成功不等于整链通过；0065 只在决策 branch 新建。 保留九个具名测试，在原用例内补旧直绑、关停提交失败、两种 vacant 与半写强杀。

## 四轮独审到第五稿的覆盖

- 666a1a42：不延用监听 FD、不准备用证明；分支只新增 ADR，本文与 canonical_plan 可逐字比，具名验收给成功与失败。
- c061b667：不新增杀孤儿权限，不借备份或日志当已有资格；TB-05 与在线重拉各自有票。
- 1a2be7e6：域退出证据不靠 launcher 日志。E/B 的标记与持久 writer_epoch 同库；旧标记在 accept 前已消费。
- 173fff70：不存在模式切换或首次受管入口。旧库无标记、一侧缺库、owner 不明、写到一半，分别有显式去向和负控。

## 第五稿独审返修

R5 的旧直绑门现在也在 bind 后、accept 前消费标记；R8 回查 #1372 旧控制器并补齐原始 stdout/stderr。逐项处置见 REDO-1.md。

## 证据的使用边界

probe-ext4.log 为原两次 ext4 探针，保留内核、挂载和输出，不重跑。x-epoch.log 为原 Linux/amd64 OrbStack 真 E/X 对照；x-epoch-boat.log 用同一 #1375 b9d898dc Linux release 的 E/X 可执行文件，在 Boat ext4 上得到同样结论并记录 uname、findmnt。两者只验 #2129 的信封拒绝，夹具移动的是自己创建的 E 残留。不以此为 #1411 的产品验收。
