# #2079 考古：原会话端点同址换代

取证基线：`5a1ac9de73766f0a943c156f97cb467b7d690218`，分支 `decision/2079`，初始 main 原件 `b9d898dccf46c2a716115eaa1215bc39c458a959`。分类 **P**：ADR 0039 已裁启动、监督和换代；ADR 0059 明留残留名字处置。给未来受管部署定义持续发布和退役权，是新的 OS 权限归属取舍。按 #1909 起草、非作者独审后由代理裁定。硬门清单为空（`userGate: []`）；本票不授予实际 unlink、部署、隔离、资金、账户、场所、密钥或凭据权限。

tracker 使用含 title/body/comments 的查询并包含已关闭票。仓内 `rg -n` 覆盖 `analysis/ docs/ .chanlun/`，逐点原输出见相邻 Qn 文件。PR 不计为 issue 搜索命中：用 PR 工具读 #2077、#2082、#2065、#2088，再读精确 Git 原件。零/少量命中只描述对应检索式；旧候选、评论、代码及探针不能代替已有正本。Q6 待决的是生产状态与中断恢复，不把本轮草稿中的提议写成旧先例。


## Q1 [A] 正式 owner、适用范围与旧入口

- `gh issue list --search '"唯一 launcher" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：11 个搜索结果，见 [Q1.tracker.txt](Q1.tracker.txt)。
- `rg -n '唯一 launcher|production-entry-inventory-and-unique-launcher' analysis/ docs/ .chanlun/`：42 行，见 [Q1.repo.txt](Q1.repo.txt)。
- 命中 #1530（CLOSED）、#1823、#2079：历史 launcher 裁定、调查、现票；后两者不是发布授权。
- 命中 docs/adr/0039-production-entry-inventory-and-unique-launcher.md:273-292：production_session 是正式 launcher；负责装配、监督、换代，不持域写者身份。
- 出处：ADR 0039 裁定三；SPEC #1340 C09.1、C10.1。
- 结论：沿用正式 owner、协议和进程域。现役入口沿用 ADR 定义，不重新宣称当下全仓扫描。直绑选入条件与新合约分离，现有 CLI 不新增门。

## Q2 [B] 受管端点、登记和锁相对 S 准入测量域的布局

- `gh issue list --search '"测量域" "socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：3 个搜索结果，见 [Q2.tracker.txt](Q2.tracker.txt)。
- `rg -n 'production-session-layout-contract|不比较 .s.socket|S 测量边界' analysis/ docs/ .chanlun/`：34 行，见 [Q2.repo.txt](Q2.repo.txt)。
- 命中 #1818、#1781、#1823：布局裁定、实施消费、残留调查。#1818 仍 OPEN，但已有 resolution 及主线 ADR。
- 命中 docs/adr/0059-production-session-layout-contract.md:95-121：已裁 canon、M、并发写域拒绝以及直绑 S 后 bind 的例外。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/DRAFT.md:23：受管模式可能提前发布；原例外前提不再成立。
- 出处：[#1818 resolution](https://github.com/Newchanlun/NewChanlun/issues/1818#issuecomment-6550813315)；ADR 0059 裁定第 1–4、6–9 条。
- 结论：原条文为 A 直接沿用；受管 S/X 和发布状态是 B 的新增适用。早期发布或运行中改名与并发侧件同样能扰动 M，采用相同拒绝判据；不把其余 P 子树转为禁区。
- 默认采纳：在任何写入和拉起前完成只读布局预检。对受管监听名、登记和互斥写足迹用 M 拒绝；直绑 S 例外和 R4 不变。

## Q3 [B] 正常关库、保留原名与 X 范围

- `gh issue list --search '"socket_handoff" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：0 个搜索结果，见 [Q3.tracker.txt](Q3.tracker.txt)。
- `rg -n 'socket_handoff|正常关停|正常关库' analysis/ docs/ .chanlun/`：3 行，见 [Q3.repo.txt](Q3.repo.txt)。
- 命中 Q3 tracker 查询：socket_handoff 无 issue 命中；#2077 是 PR，另查主机 PR 读数和精确 Git 源。
- 命中 #2077 @ b7b79657d85c4d9ef830d0422c29f944c7a4cc87：正常停止 S/E/B，socket_handoff=not_performed；X 监督行为不变，原 manifest 重启仍拒绝。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/DRAFT.md:25-29：成功关库与持有者确已退出是两个不同事实。
- 出处：[#2077](https://github.com/Newchanlun/NewChanlun/pull/2077)；b7b79657 的 rust/tests/production_session_entry.rs:934-1001；[#1823 停机对照](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)。
- 结论：实际被测 S 主库仍为 cut-1、SQLite 自收 WAL/SHM，S/E/B 的相关路径仍在。X 无法从 S/E/B 停机信号推得已正常退出。
- 默认采纳：关停只形成该域结果和退出证据，不动名字；在下一次发布前按每域核验。X 走自己的生命周期。

## Q4 [B] 崩溃、活实例、未知或替换残留由谁处置

- `gh issue list --search '"残留 socket" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：3 个搜索结果，见 [Q4.tracker.txt](Q4.tracker.txt)。
- `rg -n '残留 socket|6994092216|改名.{0,20}(unlink|删除)|SAFE-RACE' analysis/ docs/ .chanlun/`：17 行，见 [Q4.repo.txt](Q4.repo.txt)。
- 命中 #1823、#1818、#1781：布局合同把清理留给后续设计。
- 命中 #1823 两份复核评论：两构建各三种布局，S 先拒 socket；按路径先查后删不能证明排他。
- 命中 docs/adr/0059-production-session-layout-contract.md:117：只保留直绑 S 例外，不决定谁清。
- 出处：[#1823 六份观察](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6687775294)、[受信归属反例](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6994092216)、[归属调查](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6550850441)。
- 结论：#1823 的书面建议把工作归既有 supervisor，但未定名字权限；票正文内/外错误是旧推测，被 CI 首错订正。批过的清理对象必须来自持续部署排他、旧作业与 FD 回收及登记三者，不来自 PID、inode 或探活。
- 默认采纳：由正式 launcher 经受信部署入口接续；只清退自己完整登记的上一代 socket。活着、未知、替换、排他或退出证据不成立均保留。

## Q5 [B] 同址每代新 listener，还是跨代沿用 FD 或换址

- `gh issue list --search '"监听器" "队列" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：1 个搜索结果，见 [Q5.tracker.txt](Q5.tracker.txt)。
- `rg -n '每域每代|每代换监听器|queued-before-next-generation|SCM_RIGHTS' analysis/ docs/ .chanlun/`：12 行，见 [Q5.repo.txt](Q5.repo.txt)。
- 命中 #2079 票及候选评论：提出同址每代新建，尚未生效。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/linux-fresh.log:1-9：同址两代回应，分离身份的客户端不能变更名字，旧排队连接在换代前断开。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/darwin-fd.jsonl:1-4、linux-fd.jsonl:1-4：保留同一 FD 时下一代可处理空窗旧请求。
- 出处：固定取证基线 5a1ac9de 的三份探针日志与其脚本，见下文原件核对。
- 结论：新 listener 同时保持原绝对地址和代际隔离。跨代保留能接续 socket，却不符合本合同不继承旧队列的前提；换址失去客户端原地址。
- 默认采纳：选入后按域、按代新建。旧模式在未选入部署照旧，不做失败兜底；保留 FD 留作其他队列语义的候选。

## Q6 [C] 生产端点登记、发布及退役的持久状态与中断续接

- `gh issue list --search '"端点" "发布" "登记" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：31 个搜索结果，见 [Q6.tracker.txt](Q6.tracker.txt)。
- `rg -n '发布意图|退役意图|发布完成|受信发布者|端点代' analysis/ docs/ .chanlun/`：16 行，见 [Q6.repo.txt](Q6.repo.txt)。
- `gh issue list --search '"发布意图" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：0 个搜索结果，见 [Q6-exact.tracker.txt](Q6-exact.tracker.txt)。
- `rg -n '发布意图|退役意图|已发布.*端点|端点.*登记' analysis/ docs/ .chanlun/`：27 行，见 [Q6-exact.repo.txt](Q6-exact.repo.txt)。
- 命中 Q6 tracker 宽查及精确补查：宽查含无关金融/几何端点与 #1411/#1340；发布意图精确查询无结果。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/DRAFT.md:16-18：本轮候选提出留意图，未定义哪些部分完成可安全续接。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/fresh_listener.py:12-19：探针只保存对象身份并串行验证，不是持久发布状态前例。
- 出处：#1823 的归属调查与 #2079 的未审候选只提供问题和边界。
- 结论：受保护目录加身份、退出证据使已知的退役可恢复；单凭发布意图不能确认崩溃恰发生在本次 bind 之后，不因此摸已有对象。按域记录避免让某个域的中断成为健康域的恢复闸。
- 推荐裁定：先持久记意图再动名字，先提交发布完成再交 FD。退役意图与排他连续均可证明时重做或补完成；发布窗口中现场已有对象且无完成记录时原位保留。
- 缺口去向 `decision`；检索词：端点 发布 登记、发布意图、退役意图、已发布.*端点、端点.*登记。

## Q7 [B] FD 交付的身份、角色与保管边界

- `gh issue list --search '"监听 FD" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：1 个搜索结果，见 [Q7.tracker.txt](Q7.tracker.txt)。
- `rg -n '监听 FD|SCM_RIGHTS|FD 保管|SO_ACCEPTCONN|listener FD' analysis/ docs/ .chanlun/`：15 行，见 [Q7.repo.txt](Q7.repo.txt)。
- 命中 #2079：已选备选交付方式，不是认证实现。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/fresh_listener.py:20-41：私有夹具传一个监听 FD 并核地址/监听状态，不能外推生产身份。
- 命中 .chanlun/review-results/goal1323-resume-20261017/c6a-external-anchor-review.md:34-36：C6a 的私有继承、关闭意外 FD 是类比先例，不是生产 listener 决定。
- 出处：5a1ac9de 的受控夹具；C6a 复核第 34–36 行。
- 结论：继承/私有通道可用，但没有发布权证明的接收者不得获得 FD；最后一个副本不回收会破坏跨代隔离。
- 默认采纳：只交本域本代 FD；验证部署、域、代、类型、地址、监听状态；关闭多余/非法副本，防止兄弟域或后续进程继承。

## Q8 [B] 原 manifest 怎样装配有效 writer epoch

- `gh issue list --search '"具名恢复" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：1 个搜索结果，见 [Q8.tracker.txt](Q8.tracker.txt)。
- `rg -n 'recover-named|current-recovery|恢复收据|writer epoch' analysis/ docs/ .chanlun/`：10 行，见 [Q8.repo.txt](Q8.repo.txt)。
- 命中 #1411（issue）、#2082（另读 PR）：#2082 的非作者 PASS 在 329be34f，仅 E/B 具名恢复及显式装配。
- 命中 5a1ac9de 的 rust/src/bin/production_session.rs:398-444：S/E/B/X 初始 epoch 来自配置。
- 命中 329be34f 的 rust/src/economic_session/recovery.rs:111-154、rust/src/bin/production_session.rs:265-341：按同一 ID 取回已提交原回执；current-recovery 拒旧回执。launcher 只核回执，不接管名字。
- 出处：[#2082](https://github.com/Newchanlun/NewChanlun/pull/2082) 及精确头；/Volumes/AgentStorage/issue1411-epoch-handoff-20261119/REVIEW-NAMED-RECOVERY-INDEPENDENT.md。
- 结论：端点代不能替代库的 epoch。不能把 #2082 全 E/B 计划硬套到活着的其他域；其当前回执核验用本域锁，E 仍在持锁时不能代验。
- 默认采纳：照原配置标识会话，换代取本域正式当前恢复凭证，serve 自己复核；B 按合同分别使用本域与 E 来源代。S/X 由各自 owner 接线，不拿 E/B 回执代用。

## Q9 [A] 局部服务、真实就绪和 X 外效边界

- `gh issue list --search '"MayHaveCalled" "就绪" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：2 个搜索结果，见 [Q9.tracker.txt](Q9.tracker.txt)。
- `rg -n 'C09\.[3789]|MayHaveCalled|各域独立|X 无.*(socket|端点)' analysis/ docs/ .chanlun/`：207 行，见 [Q9.repo.txt](Q9.repo.txt)。
- 命中 #1340、#1407：SPEC 与执行命令下游，不能从 socket 可连导出业务可用。
- 命中 docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md:134-139：三证据类恢复和外效保留语义。
- 命中 SPEC.md @ efc1ddc4:326-332：域局部恢复；S/E/B 写者代；X 发送隔离和收据；S 恢复不等待 E。
- 出处：SPEC #1340 C09.3、C09.7–9；ADR 0038 #1539 修订。
- 结论：继续按实际域进程与原业务门判就绪，不改 X 的发送授权、无本地监听器时不造监听/查询协议。源代码证明已有两条 X profile 分支，非对全仓 X 实现穷举。

## Q10 [A] 实际部署、unlink、账户、资金和凭据授权

- `gh issue list --search '"授权来源与生效边界" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：1 个搜索结果，见 [Q10.tracker.txt](Q10.tracker.txt)。
- `rg -n '授权来源与生效边界|本票不授予 unlink|未选入部署' analysis/ docs/ .chanlun/`：13 行，见 [Q10.repo.txt](Q10.repo.txt)。
- 命中 #1551、#1909（另查）、#2079（另查）：普通政策与实际外部授权区分。
- 命中 docs/adr/0041-degrees-of-freedom-configurable-not-excluded.md:39-48：独审 PASS 不代签真实权限。
- 出处：ADR 0041 授权来源与生效边界；graph-engineering「分级」「资金与权限硬门」；#1323 Notes N-1。
- 结论：本方案仅定义未来受管部署的前提和角色；无实际资金、账户、场所、风险值、凭据、宿主权限、安装或部署要求。userGate=[]。

## Q11 [B] 同路径恢复如何接到 #1411 全会话验收

- `gh issue list --search '"input-2" "cut-1" in:title,body,comments' --state all --limit 100 --json number,state,title,url`：2 个搜索结果，见 [Q11.tracker.txt](Q11.tracker.txt)。
- `rg -n 'input-2|SAFE-ADMISSION|OBS-IN|SAFE-LIVE|完整会话双进程' analysis/ docs/ .chanlun/`：9 行，见 [Q11.repo.txt](Q11.repo.txt)。
- 命中 #2079、#1411：票面明确同库、原回执 cut-1 与 input-2；#1411 另有全状态双跑。
- 命中 .chanlun/review-results/issue2079-endpoint-rotation/DRAFT.md:40-49：提出有序、异常、SAFE 和旧入口四组实施闸。
- 命中 #1823 OBS/SAFE 规格及读数；#2077；#2082：收据各自覆盖观察、关库、E/B 恢复，均不含整条同名恢复。
- 出处：[#1411](https://github.com/Newchanlun/NewChanlun/issues/1411)、[#1823 规格](https://github.com/Newchanlun/NewChanlun/issues/1823#issuecomment-6550850441)、SPEC #1340 C10.4 / AT-14。
- 结论：正式入口留第一次提交原件，再由新进程以原配置和库、实际路径及有效写者代恢复；查询同 cut、继续提交才排除假 Ready 或空库。
- 默认采纳：四组二值验收以原回执逐字节、input-2 Committed 且持久化为正控，保留局部健康、崩溃及 SAFE 负控；不减 #1411 原有六面双跑义务。

## 引用原件和范围

- ADR 0039 的「唯一」是 ADR 已裁的规范，沿用其裁定三；不重报仓内实现全覆盖。本文要核的端点集合按原配置字段枚举：launcher 的 S、经济 manifest 的 E、逐个配置重匹配的 B、所选 X profile 的实际本地监听项。基线 X 的两个分支见 `rust/src/bin/x_execution_session.rs:73-95,201-234` 与 `rust/src/history_simulation/runtime.rs:42-51,866-897`，不把未监听的场所地址当作本地端点。发布名对各已登记会话物理目录项判重，不数全仓 bind 点。
- #1818 resolution 评论和主线 ADR 0059 可直接回查；现票仍 OPEN 不等于布局未裁。ADR 0059 第 6 条不是受管 S 的布局豁免。#1823 六份收据仅在该 CI 的两步生产会话构建与 OBS-IN-A、OBS-IN-BASENAME、OBS-OUT 中逐项计数；不把不具域归属的 EADDRINUSE 当作 S 首错。
- `linux-fresh.log:1-3,6-9` 读两代发布、worker 与客户端结果；`:4-5` 读旧队列和 ECONNRESET。原址以及前代最后一个监听副本的关闭顺序以 `fresh_listener.py:4-5,17-28,42-51`、`run_fresh.py:18-29` 互证。两代使用私有容器；测试本身未运行产品。
- `darwin-fd.jsonl:1-4`、`linux-fd.jsonl:1-4` 逐行读托管地址、占用、不同 PID + 同 inode + 旧载荷、最终留名。两次占用 errno 由 `probe.py:50-54,74-80` 的断言核对，JSONL 未输出 errno；真实往返、旧进程退出、inode 检查在 `probe.py:60-73`。EVIDENCE.md 的 Darwin 初试 ENOPROTOOPT 只有摘要，无对应原始日志，最终代码 `probe.py:15-27` 只在 Linux 查 SO_ACCEPTCONN；ADR 不将初试 errno 作为已核原始观测。没有 Darwin 异 UID 同址换代的实测。
- ADR 编号：按要求查本 worktree `ls docs/adr | tail`，用实时 main 的 `git ls-tree -r --name-only` 复核；对开放 PR 查询 `docs/adr` 与 `0065`，把命中项和 #2088 的活动 Git head 逐个检查 `git diff --name-status <main>...<head> -- docs/adr` 与 head 树的 `/0065[-.]`。主线已有 0061，#2065 新增 0064，#2088 改 0039；所查 PR 未见 0065。原件见 [编号核查](adr-number-check.txt)。
- 原生依赖：查 GitHub REST 的 `/issues/{2079,1411,1818,1823}/dependencies/{blocked_by,blocking}`，原输出在同目录。本票无现成原生边；#1411 完整恢复验收依赖本裁定，不能把功能依赖写成已有 GitHub 边。#1818→#1781 保持；#1823 读取这些结论，不改其 ticket 名分。#2077/#2082 是 #1411 的候选 PR，并非 #2079 的决策阻塞票。为不阻塞不消费端点合同的准备工作，本稿不要求新增整票排程边。
