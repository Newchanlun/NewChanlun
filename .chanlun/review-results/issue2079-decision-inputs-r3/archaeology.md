# #2079 第三稿考古：原会话端点同址换代

新起草会话。仓内检索固定为生效基线 `b9d898dccf46c2a716115eaa1215bc39c458a959` 的 `analysis/ docs/ .chanlun/`，不计第 2 稿正文。Q1–Q15 复跑原问题与查询词，保留实际计数；补查 Q12–Q14，新增 Q16–Q17。tracker 包含开放、关闭及评论。GitHub 搜索会随新评论变化，无命中不冒充穷举全历史。代码行为、探针、旧审查在下列固定 Git 对象复核。已经落地的教义和正本沿用，不用实现现状反推裁定。

分类 **P**，不代签真实操作，`userGate: []`。分级出处为 #1323 Notes N-1 与 ADR 0041。返修输入：[第 1 轮独审](https://github.com/Newchanlun/NewChanlun/tree/843c18d2cfe02aa4507810bf91decc7b8e64fa6c/.chanlun/review-results/issue2079-review-666a1a42)、[第 2 轮独审](https://github.com/Newchanlun/NewChanlun/tree/029077ad4851d0db7c8c85bf13e1701bdcfe041f/.chanlun/review-results/issue2079-review-c061b667)、[旧起草材料](https://github.com/Newchanlun/NewChanlun/tree/faf72afbf8f0a554bf0cb5fd3499a66015b03a27/.chanlun/review-results/issue2079-decision-inputs)、[OS 探针原件](https://github.com/Newchanlun/NewChanlun/tree/5a1ac9de73766f0a943c156f97cb467b7d690218/.chanlun/review-results/issue2079-endpoint-rotation)。

## Q1 [A] 正式 launcher、启动输入与职责

- repo: `git grep -I -n -E '唯一 launcher|production-entry-inventory-and-unique-launcher' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，41 条；[原件](queries/Q1.repo.txt).
- tracker: `gh issue list --search '"唯一 launcher" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，11 条；[原件](queries/Q1.tracker.txt).
- 命中与推导：#1530 已关；#1823、#2079 是调查和本票。0039 已裁 production_session 作为正式入口，域各自持写锁，launcher 只装配监督，不读取域写权。
- 出处：ADR 0039 裁定三.1–3，SPEC C09.1/C10.1。
- 沿用条款：沿用正本；辅助发布不是 launcher，选入时只增私有 FD 交付。

## Q2 [B] 受管写足迹与 S 测量域

- repo: `git grep -I -n -E 'production-session-layout-contract|不比较 .s.socket|S 测量边界' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，33 条；[原件](queries/Q2.repo.txt).
- tracker: `gh issue list --search '"测量域" "socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，3 条；[原件](queries/Q2.tracker.txt).
- 命中与推导：#1818/#1781/#1823 均命中。布局规则已经生效；[新缠论:推论] 受管 S 可能在 driver open 之前 bind，和并发写域一样能改变 M；直绑后 bind 的例外前提在此不成立。
- 出处：ADR 0059:95–123；#1818 resolution。
- 默认候选及处置：在改名、传 FD 和 spawn 前只读预检，不扩大到 P 全树，不放宽 R4。
- 边界或冲突：既有直绑 S 例外不得复制给受管 S。

## Q3 [B] 有序关库、留名与逐域结果

- repo: `git grep -I -n -E 'socket_handoff|正常关停|正常关库' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，0 条；[原件](queries/Q3.repo.txt).
- tracker: `gh issue list --search '"socket_handoff" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，0 条；[原件](queries/Q3.tracker.txt).
- 命中与推导：精确关键词 socket_handoff 两路在 main 和 issue 搜索为空；PR 要另读。真进程用例中 S 原库 cut-1、WAL/SHM 自收、S/E/B 名字仍在，下一次仍拒。X 不接 S/E/B 的私有停止指令。[新缠论:推论] 正常结果不能代替作业退出证明。
- 出处：#2077 b7b79657，#1823 评论 6994092216。
- 默认候选及处置：沿用逐域 writer_closed；整会话停机不替已退出域补正常结果，X 无本域结果走异常。
- 边界或冲突：主线未实现 #2077 的候选 shutdown 协议。

## Q4 [B] 名字处置方：活实例、替换或未知对象

- repo: `git grep -I -n -E '残留 socket|6994092216|改名.{0,20}(unlink|删除)|SAFE-RACE' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，14 条；[原件](queries/Q4.repo.txt).
- tracker: `gh issue list --search '"残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，3 条；[原件](queries/Q4.tracker.txt).
- 命中与推导：#1823 调查推荐原 launcher supervisor，明写清理权另裁。#2077 首版「检查后按名删」无共同排他；同 inode 与 PID 都不证明处置权。[新缠论:推论] 被强杀的 launcher 无法持续证明自己及派生作业退出。main transport 旧注释提到 PID 核验却不实现、不授权它。
- 出处：#1823 评论 6550850441、6687775294、6994092216；ADR 0059:117。
- 默认候选及处置：否决 B 默认由 launcher 清退；按 Q13 改由独立部署监督器出证并封堵复起，发布助手只操作有持续排他和有效登记的原对象。launcher 只装配。
- 边界或冲突：代码注释不是处置权；不采纳「核 PID/路径后直接 unlink」。

## Q5 [B] 新监听器与继承旧 FD/改址

- repo: `git grep -I -n -E '每域每代|每代换监听器|queued-before-next-generation|SCM_RIGHTS' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，2 条；[原件](queries/Q5.repo.txt).
- tracker: `gh issue list --search '"监听器" "队列" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，1 条；[原件](queries/Q5.tracker.txt).
- 命中与推导：#2079 命中候选；原 Linux 容器日志两代同址答复、域身份不能创建兄弟条目/改名/删名，旧队列连接断开。Darwin/Linux 留 FD 对照都处理空窗旧载荷。[新缠论:推论] 要同时满足原路径和旧队列不过代，不能继承监听器或改址。
- 出处：5a1ac9de 原探针 linux-fresh.log、darwin-fd.jsonl、linux-fd.jsonl。
- 默认候选及处置：显式受管时每代新建；直绑保留为独立默认模式。只保留 FD 被同一队列隔离要求排除。

## Q6 [C] 发布、退役与可续做的持久边界

- repo: `git grep -I -n -E '发布意图|退役意图|已发布.*端点|端点.*登记' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，25 条；[原件](queries/Q6-exact.repo.txt).
- tracker: `gh issue list --search '"发布意图" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，0 条；[原件](queries/Q6-exact.tracker.txt).
- repo: `git grep -I -n -E '发布意图|退役意图|发布完成|受信发布者|端点代' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，11 条；[原件](queries/Q6.repo.txt).
- tracker: `gh issue list --search '"端点" "发布" "登记" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，32 条；[原件](queries/Q6.tracker.txt).
- 命中与推导：宽查混有几何端点与其他出版登记；精确「发布意图」无票，只见无关发布语义。探针有目录项凭据但没有中断日志。[新缠论:选择] 原子清退不是一个 syscall；重放必须先区分「知道是哪一个旧对象」和「不知 bind 是否完成」。
- 出处：#1823 SAFE；5a1ac9de fresh_listener.py:12–28。
- C / decision 裁定值：先记意图再动名字，已发布记录后才交 FD；有完整旧绑定与排他可续退役，未记完 bind 且现场有物只报需恢复。
- 已搜词：发布意图、退役意图、已发布、端点登记。

## Q7 [B] FD 交付与余副本回收

- repo: `git grep -I -n -E '监听 FD|SCM_RIGHTS|FD 保管|SO_ACCEPTCONN|listener FD' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，2 条；[原件](queries/Q7.repo.txt).
- tracker: `gh issue list --search '"监听 FD" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，1 条；[原件](queries/Q7.tracker.txt).
- 命中与推导：#2079 和私有交付查询仅提供候选。探针验证一枚 SCM_RIGHTS、地址和监听状态，不证明产品鉴权。[新缠论:推论] FD 交过界后，旧作业退出不能证明最后监听关闭。
- 出处：5a1ac9de fresh_listener.py:17–41；ADR 0039 三.2–4。
- 默认候选及处置：仅定向白名单或已认证的私有交付，随 FD 绑定部署/域/登记代/端点代，关闭余副本并禁止跨域或越界传播。只在选入新增。

## Q8 [B] 原 manifest 与正式写者代

- repo: `git grep -I -n -E 'recover-named|current-recovery|恢复收据|writer epoch' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，8 条；[原件](queries/Q8.repo.txt).
- tracker: `gh issue list --search '"具名恢复" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，1 条；[原件](queries/Q8.tracker.txt).
- 命中与推导：原配置给初始代。候选 recover/query/current 绑定恢复 ID、原域及 cut，current 拒陈旧原件；B 用独立本域与 E 来源代。当前核验与 serve 同锁，不能在健康 E 仍活时借用。[新缠论:推论] 端点代不是 writer epoch。
- 出处：#2082 @329be34f；#1411 评论；SPEC C09.7–9。
- 默认候选及处置：整会话按域取值：原代仍有效不强制升代或找凭证，换代用该域正式持久回执，丢答复按原 ID 重取。B 核当前 E 来源不改历史。

## Q9 [A] 故障隔离、X 发送与证据类区分

- repo: `git grep -I -n -E 'C09\.[3789]|MayHaveCalled|各域独立|X 无.*(socket|端点)' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，204 条；[原件](queries/Q9.repo.txt).
- tracker: `gh issue list --search '"MayHaveCalled" "就绪" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，2 条；[原件](queries/Q9.tracker.txt).
- 命中与推导：#1340 与 #1407 命中；局部故障不能冒充全宿主故障，X 旧发送者先退出；模拟与真实事实恢复有不同合同。
- 出处：SPEC C09.3/C09.7–9，ADR 0038 #1539 修订。
- 沿用条款：沿用同一域合同和外效边界；接通、锁或换代不能授予新发送。

## Q10 [A] 普通 P 决策及实际权限硬门

- repo: `git grep -I -n -E '授权来源与生效边界|本票不授予 unlink|未选入部署' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，11 条；[原件](queries/Q10.repo.txt).
- tracker: `gh issue list --search '"授权来源与生效边界" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，1 条；[原件](queries/Q10.tracker.txt).
- 命中与推导：#1551 命中授权来源；另核 N-1 与 #1909。普通 P 独审裁定非 UserSigned；真实权限仍独立。
- 出处：ADR 0041:39–48，#1323 Notes N-1、#1909。
- 沿用条款：仅定方案，userGate 空；不赋 unlink、宿主/部署、账户、资金或凭据权限。

## Q11 [B] 原会话闭环与 #1411 交付门

- repo: `git grep -I -n -E 'input-2|SAFE-ADMISSION|OBS-IN|SAFE-LIVE|完整会话双进程' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，6 条；[原件](queries/Q11.repo.txt).
- tracker: `gh issue list --search '"input-2" "cut-1" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，2 条；[原件](queries/Q11.tracker.txt).
- 命中与推导：双路命中两张票、AT-14 等报告；#2077 有正常关库，#2082 有 E/B 子合同，均未验证整链。[新缠论:推论] 同址应答不足以证明同库原状态成功。
- 出处：#2079/#1411，#1823 OBS/SAFE，SPEC C10.4 / AT-14。
- 默认候选及处置：两次不同 launcher 的原配置、原库、同址 cut-1 完整回执及 input-2 持久提交；不减逐域真实中断及全状态双跑。
- 边界或冲突：#1411 仍有原 S R4 媒体成功证据缺口，不能按 socket 正控结案。

## Q12 [C] 受管隔离的返回路径；存活 launcher 下的单域换代

- repo: `git grep -I -n -E '单域.{0,14}故障隔离|TB-05 验收汇总|#1376、#1417|一域损坏、阻塞或重启' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，4 条；[原件](queries/Q12-isolation.repo.txt).
- tracker: `gh issue list --search '"故障隔离" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，34 条；[原件](queries/Q12-isolation.tracker.txt).
- repo: `git grep -I -n -E '单域.{0,16}(换代|原址|重拉|重启|再服务)|E 来源代|current-recovery' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，0 条；[原件](queries/Q12-reattach.repo.txt).
- tracker: `gh issue list --search '"单域" "端点" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，2 条；[原件](queries/Q12-reattach.tracker.txt).
- repo: `git grep -I -n -E '单域.{0,20}(重启|重拉|接续)|局部故障|一域损坏|current-recovery' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，3 条；[原件](queries/Q12.repo.txt).
- tracker: `gh issue list --search '"单域" "重启" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，3 条；[原件](queries/Q12.tracker.txt).
- 命中与推导：故障隔离补查命中 TB-05，与原生子票和依赖核对。已裁隔离并未给本地热换代权。#1425 是责任应用、#1419 是结构与读路径；#2082 的全 E/B 集合与域锁反证直接套用。[新缠论:选择] 不能为坏域的接续摧毁健康域的业务状态或伪造 E 的当前回执。
- 出处：SPEC C09.3；#1363 与五片；#2082 @329be34f。
- C / decision 裁定值：受管模式只隔离，无自动整会话回收或单域重拉；返回 Ready 走显式整会话有序停机，逐域分类后重启。direct 监督由 TB-05 承接；在线同址单域换代另交具名 grilling（不作为本票现有待裁值或 #1411 前置）。
- 边界或冲突：第二稿把 direct 整组回收固化、把未裁在线换代交实施，与 TB-05 和 #1411 名分相冲突。
- 已搜词：故障隔离、单域 重启、单域 端点、current-recovery。

## Q13 [C] launcher 崩溃后谁能终止孤儿、谁出证

- repo: `git grep -I -n -E '孤儿.{0,12}(进程|退出|回收|端点)|部署监督器|launcher.{0,15}(崩溃|强杀)' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，10 条；[原件](queries/Q13-orphan.repo.txt).
- tracker: `gh issue list --search '"孤儿" "监督" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，2 条；[原件](queries/Q13-orphan.tracker.txt).
- repo: `git grep -I -n -E 'launcher.{0,16}(崩溃|被杀|强杀)|孤儿.{0,15}(回收|FD|端点)|进程退出.*发送子进程' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，2 条；[原件](queries/Q13.repo.txt).
- tracker: `gh issue list --search '"launcher 崩溃" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，0 条；[原件](queries/Q13.tracker.txt).
- 命中与推导：launcher 崩溃精确查空；孤儿/监督补查命中 #2079 与 #1406 的业务/事实归属，不是进程处置授权。有序控制 EOF 不退出，基线进程无联动。[新缠论:选择] 新 launcher 不能自证旧作业回收，观察职责不能推导出终止权限。
- 出处：SPEC C09.8、0039 三.6、main spawn、#2077 EOF。
- C / decision 裁定值：孤儿维持原服务，拒绝新代并保留现场；仅另获授权的动作可终止它。监督器封堵复起而不发信号，只在作业内全部进程退出且 FD 回收证据成立后出证。
- 边界或冲突：第二稿「按原权责回收」无来源；C09.8 只规定确认退出。
- 已搜词：launcher 崩溃、孤儿 监督、FD 回收、发送子进程。

## Q14 [C] 需恢复出口、登记代、宿主重启证据

- repo: `git grep -I -n -E '受管.{0,12}(退役|重登)|boot[_ -]id|可信恢复原件|managed-rotation' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，0 条；[原件](queries/Q14-generation.repo.txt).
- tracker: `gh issue list --search '"端点" "重登" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，2 条；[原件](queries/Q14-generation.tracker.txt).
- repo: `git grep -I -n -E '端点需恢复|登记.{0,15}(作废|废止|重登)|boot[_ -]id|退役意图' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，2 条；[原件](queries/Q14.repo.txt).
- tracker: `gh issue list --search '"端点需恢复" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，1 条；[原件](queries/Q14.tracker.txt).
- 命中与推导：重登补查的 #2070 是 Docker 准入，不是登记授权。bind 未记完成缺对象绑定；临时地址重启消失与发布日志丢失也不补绑定。[新缠论:选择] 当前独立部署记录可标明前代，单纯备份不能证明最新；boot ID 只证明内核实例已换。
- 出处：#1823 SAFE/RACE，ADR 0059:117，#2079 两轮独审。
- C / decision 裁定值：用当前独立部署记录封堵并对应前代回收；重验保护及空址后原子废止旧代、开新代。只认当前原记录；三种出口同一规则。同一 VM 的持久保留正控另核名称连续，临时地址消失走重登。
- 边界或冲突：过期备份会封堵错代；重启只核 inode 不能证明排他保护。
- 已搜词：端点需恢复、端点 重登、boot id、退役意图。

## Q15 [B] 监听状态的证据

- repo: `git grep -I -n -E 'SO_ACCEPTCONN|ENOPROTOOPT|同一判断.*松紧' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，20 条；[原件](queries/Q15.repo.txt).
- tracker: `gh issue list --search '"SO_ACCEPTCONN" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，0 条；[原件](queries/Q15.tracker.txt).
- 命中与推导：精确 issue 搜索无 SO_ACCEPTCONN；仓内命中通则及旧判据。Linux 探针直接向内核查；Darwin 只跑保留 FD 对照。[新缠论:推论] 私有交付只证明来源，不证明收到的 FD 已监听。
- 出处：ADR 0041:11–15；5a1ac9de fresh_listener.py:39–41、probe.py:15–27。
- 默认候选及处置：只用 SO_ACCEPTCONN；不支持、报错、返回 0 均拒绝，不用「可信创建」替代。

## Q16 [C] 受管预检与卸载/改回直绑

- repo: `git grep -I -n -E 'production-session-deployment|endpoint_mode|相对路径|链接祖先' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，26 条；[原件](queries/Q16-mode.repo.txt).
- tracker: `gh issue list --search '"路径" "直绑" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，0 条；[原件](queries/Q16-mode.tracker.txt).
- 命中与推导：路径/直绑未命中专门裁定。0059 使用 canon 判布局，不会维持原路径字节；受管发布必须核原配置与内核地址相同。[新缠论:选择] 先解析再换字面会掩盖祖先链接；不先退役登记则 direct 只能拒占用。
- 出处：ADR 0059:95–123；ADR 0041:17–27。
- C / decision 裁定值：原配置必须绝对、无链接祖先或最终条目，在副作用前拒绝不合格路径。事前新获准部署版本可切模式；原发布助手凭严证退役登记，监督器确认空址后交给 direct。
- 边界或冲突：不是运行时把 direct 作为失败兜底。
- 已搜词：原绝对路径、相对路径、链接祖先、endpoint_mode、直绑。

## Q17 [C] 受管就绪状态的只读载体与见证

- repo: `git grep -I -n -E 'session_ready|逐域.*就绪|全会话.*Ready|per.domain.*ready' b9d898dccf46c2a716115eaa1215bc39c458a959 -- analysis/ docs/ .chanlun/`，0 条；[原件](queries/Q17-ready.repo.txt).
- tracker: `gh issue list --search '"端点" "就绪" in:title,body,comments' --state all --limit 100 --json number,state,title,url`，14 条；[原件](queries/Q17-ready.tracker.txt).
- 命中与推导：端点/就绪搜索命中 #2079/#1411 及观察票；仓内没有具体受管事件。main 已有 stderr JSON，spawn 不等于 Ready。[新缠论:选择] 复用正式入口既有日志通路，按同一 run 的域实例和聚合状态核观察，不引入公共 RPC。
- 出处：main production_session.rs:90–96,327–367；#1823 OBS；#1376/#1417。
- C / decision 裁定值：受管输出 managed-readiness、session_ready、domains 和首错类别，验收另外看真实读/写结果；不以总状态卡健康域或给 X 开发送。
- 已搜词：全会话 Ready、逐域就绪、session_ready、端点 就绪。

## 版本、依赖与穷举范围

- **编号**：基线 main ADR 最大为 0063。对 T3 PR 列表分页直到无下一页（141 个 open PR），取得对应 Git head 并逐棵查 `docs/adr`；查到 #2065 加 0064、#2088 不占 0065，未发现 0065 冲突。见 [PR 列表](queries/adr-open-prs.tsv)、[固定 heads](queries/adr-open-pr-heads.tsv) 和 [树检查](queries/adr-number-check.txt)。已有草案分支的 0065 就是本票候选，不是另一项裁定。
- **依赖**：以 [#1363 原生子票](queries/1363-subissues.tsv) 与 [#1376](queries/deps-1376.txt)、[#1396](queries/deps-1396.txt)、[#1409](queries/deps-1409.txt)、[#1417](queries/deps-1417.txt)、[#1423](queries/deps-1423.txt)、[#1411](queries/deps-1411.txt) 双向原生边核验五片链。#1993 是关闭的 CI 锁争用排查，不消费端点。#1363 的父汇总与实施边不同；[#2079](queries/deps-2079.txt) 是 #1411 [原生子票](queries/2079-parent.json)，尚无原生阻塞边。保持 [#1818](queries/deps-1818.txt) → #1781；[#1823](queries/deps-1823.txt) 无现有边。
- **端点与进程集合**：按 0065 逐域表读 S 配置、经济 manifest 与配置重列表、所选 X 实际本地监听，逐项核有效登记簿；不声称搜尽仓库中的 Unix bind。正式 launcher 的唯一名分沿用 0039，不用代码搜索自封。前代进程的全覆盖以启动登记的 launcher、发布助手、各域与 OS 受约束作业跟踪的所有派生者为范围，同时核 FD 私有通道及越界条件。无法穷举受控范围时拒绝。隔离态恢复路径只穷举 0065 内的单域处置、显式停机、launcher 崩溃和宿主重启；后两者不是保持 launcher 存活时的处置，未宣称查遍第三方运维方案。
- **观察的六份**：由 [#1823 CI 收据说明](sources/comment-6687775294.json) 指定两个构建乘以三个具名布局；S 参数期拒占用，未到 R4 或 bind。#2077 的关库和 #2082 的 E/B 都是候选头限域证据。#1411 当前 R4/SHM 首错见 [票面评论](sources/1411-comments.txt)，媒体缺口不能由端点裁定关闭。
- **检索与逐行原件**：`queries/` 是本轮实际命令及结果；`sources/` 存快速复核的公开票/评论/PR 和 [带行号的正文/代码切片](sources/citations.txt)。[#1823 SAFE 原规格片段](sources/1823-safe-original.md) 摘自 `/Volumes/AgentStorage/socket-probe40v/TEST-SPEC.md` 第 47–71 行（冻结基线 `9de18e606b2c0330162a83e2a030898b46c3690f`），属历史验收规格，不是现在的操作授权或运行结果。OS 探针固定在独立证据提交，保留该分支。
