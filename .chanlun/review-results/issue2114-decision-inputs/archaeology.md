# #2114 考古

正本取证基线：`b9d898dccf46c2a716115eaa1215bc39c458a959`；实现/测试只读参照：`origin/impl/1426-trend-formation` @ `5e66d04ff65609c03f7706a22cfab7a5c2d70c27`。T 类，`user_gate=[]`；[分级评论](https://github.com/Newchanlun/NewChanlun/issues/2114#issuecomment-7042051844)。A 已裁 3、B 有先例未正式裁 4、C 确未设计 0。没有需外部调查或探针才能裁定的事实缺口；正式 S 尚未产出目标切面是下游验收缺口，不冒充本票读数。

查询的 tracker 数是返回的票数（直读是正文与评论数），仓内数是取证基线的匹配行数；宽查询会混入历史材料或无关命中，下列列实质证据。tracker 以 `--state all` 覆盖开闭，并显式检索评论、直读邻票；#1496 实际 OPEN 无评论，闭合判例在 #812／#1478，另核 CLOSED #485。

## Q1 · B · 已成立的后中枢 B 开放、当下严格外缘分离，能否发布趋势已形成？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments' --json number,title,state,url` | 7 |
| tracker | "第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | 第二个(同级别)?(走势)?中枢\|构成趋势\|开放期\|未结算.{0,20}(趋势\|形成) | `rg -n --max-columns 450 --max-columns-preview '第二个(同级别)?(走势)?中枢\|构成趋势\|开放期\|未结算.{0,20}(趋势\|形成)' analysis/ docs/ .chanlun/` | 122 |
| repo | 第二个同级别中枢\|形成两个依次同向\|中枢的新生\|第二个中枢 | `rg -n --max-columns 450 --max-columns-preview '第二个同级别中枢\|形成两个依次同向\|中枢的新生\|第二个中枢' analysis/ docs/ .chanlun/` | 94 |
| tracker | #2114 正文与评论 | `gh issue view 2114 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 1 |
| tracker | #1426 正文与评论 | `gh issue view 1426 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 13 |
| tracker | #815 正文与评论 | `gh issue view 815 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 11 |

q1 tracker 返回：#2114 OPEN、#1426 OPEN、#485 CLOSED、#1419 OPEN、#832 CLOSED、#815 CLOSED、#812 CLOSED。 q1b tracker 返回：#2114 OPEN。 #2114 直读：OPEN，正文与 0 条评论。 #1426 直读：OPEN，正文与 12 条评论。 #815 直读：CLOSED，正文与 10 条评论。

- docs/chanlun/text/blog/018-第18课.md:42,44；qushi.md:124–144,224（取证基线）：前提是依次同向；允许形成后继续延伸，不规定后枢成员尚变时的正式发布。
- docs/chanlun/text/blog/019-第19课.md:524；023-第23课.md:188：前者是次级三走势未完的上涨延续个例，后者明分扩展与新生；不能以第二枢存在代替同向证明。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512：R1 给出开放 B 的同前缀追加反证；R2 将形态观察与趋势形成拆开但仍待 #2114 正式裁定。
- https://github.com/Newchanlun/NewChanlun/issues/815#issuecomment-5173454002：CLOSED：M-2 外缘判据已裁，未裁外缘何时封口。

**出处**：qushi.md:124–144,224；https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512。
**推导**：B 尚开放时新增合法 Zn 可增大 GG 或减小 DD；同前缀续流产生不同终局。CC-025 合法未更正前缀不能靠撤回容纳这类开放期翻转。观察当前真不等于该走势已确认。
**默认候选**：开放期只记当前几何；未获结算证据不签 TrendFormed。
**冲突**：R1 候选曾把临时分离直接装成已形成；反例驳的是该承诺，未驳严格不等式。

## Q2 · B · 正式确认的首切面是哪一个；B 离开、B 结算与实际走势完成如何分开？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments' --json number,title,state,url` | 13 |
| tracker | "首回试" "形成" OR "B 结算" OR "后中枢" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"首回试" "形成" OR "B 结算" OR "后中枢" in:title,body,comments' --json number,title,state,url` | 30 |
| repo | 走势必完美\|形(成\|态).{0,18}(确认\|完成)\|完成.{0,12}(时点\|时刻) | `rg -n --max-columns 450 --max-columns-preview '走势必完美\|形(成\|态).{0,18}(确认\|完成)\|完成.{0,12}(时点\|时刻)' analysis/ docs/ .chanlun/` | 576 |
| repo | 后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成 | `rg -n --max-columns 450 --max-columns-preview '后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成' analysis/ docs/ .chanlun/` | 19 |
| tracker | #1424 正文与评论 | `gh issue view 1424 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 7 |
| tracker | #1478 正文与评论 | `gh issue view 1478 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 3 |
| tracker | #1340 正文与评论 | `gh issue view 1340 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 10 |

q2 tracker 返回：#2114 OPEN、#1426 OPEN、#1360 OPEN、#1429 OPEN、#1443 OPEN、#1323 OPEN、#1463 CLOSED、#871 CLOSED、#877 CLOSED、#832 CLOSED、#858 CLOSED、#854 CLOSED、#1340 OPEN。 q2b tracker 返回：#2114 OPEN、#1426 OPEN、#1360 OPEN、#1424 OPEN、#1443 OPEN、#1537 CLOSED、#1340 OPEN、#1291 CLOSED、#327 CLOSED、#1260 CLOSED、#585 CLOSED、#583 CLOSED、#290 CLOSED、#1478 CLOSED、#466 CLOSED、#903 CLOSED、#1353 CLOSED、#323 CLOSED、#584 CLOSED、#811 CLOSED、#606 CLOSED、#474 CLOSED、#927 CLOSED、#565 CLOSED、#218 CLOSED、#473 CLOSED、#1598 CLOSED、#918 CLOSED、#810 CLOSED、#252 CLOSED（输出上限 30，不声称全量）。 #1424 直读：OPEN，正文与 6 条评论。 #1478 直读：CLOSED，正文与 2 条评论。 #1340 直读：OPEN，正文与 9 条评论。

- .chanlun/definitions/qushi.md:61,224；docs/chanlun/text/blog/018-第18课.md:42,44：两个依次同向中枢具结束条件，但可能继续，原句未给在线时钟。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7023365989：123 根老窗口改为双枢 settled；留独立走势完成义务。
- https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：CLOSED：末外回抽可为连接/突破段；代码的 break_unit 不是段角色。
- 冻结 #1340 附件 CC-019 :10031–10037、CC-025 :11001–11036：正式结算见证来自完成的首回试；走势可独立处在 FORMED_OPEN。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7025393576：正式 S 实跑止于 cut-71，不能把 123 fixture 当成发布回执。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7023365989；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661；CC-019/025。
**推导**：单窗 settled 可能只有离开。用两个实际完成的角色并冻结 Zn 外缘，再在第一可知前缀用 M-2，可避免早判且不把完成移到形成门。123 原续流 u8 实为首回抽，u7 是已完成离开，时间不必再多等。
**默认候选**：采纳两枢 R5 事实与合法相邻严格分离全部首次可知的切面；拒绝仅看旧 settled 位的暂行写法。
**冲突**：稍早的候选代码不携源切面证书；其 123 正例可用几何重核，不能由代码布尔推出正式语义。

## Q3 · A · 既有 R5 的回归/破坏与端点角色约束是什么，谁产出结算证据？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "两段式结算" OR "离开后看回抽" OR "不回则破坏" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"两段式结算" OR "离开后看回抽" OR "不回则破坏" in:title,body,comments' --json number,title,state,url` | 4 |
| tracker | "停在核心之外的那段回抽" OR "端点条款" OR "中枢破坏" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"停在核心之外的那段回抽" OR "端点条款" OR "中枢破坏" in:title,body,comments' --json number,title,state,url` | 23 |
| repo | 两段式\|回到核心\|越出后返回\|不返回则破坏\|离开后.{0,12}回抽\|Z-6 | `rg -n --max-columns 450 --max-columns-preview '两段式\|回到核心\|越出后返回\|不返回则破坏\|离开后.{0,12}回抽\|Z-6' analysis/ docs/ .chanlun/` | 74 |
| repo | 后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成 | `rg -n --max-columns 450 --max-columns-preview '后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成' analysis/ docs/ .chanlun/` | 19 |
| tracker | #1496 正文与评论 | `gh issue view 1496 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 1 |
| tracker | #812 正文与评论 | `gh issue view 812 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 11 |
| tracker | #485 正文与评论 | `gh issue view 485 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 3 |
| tracker | #1478 正文与评论 | `gh issue view 1478 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 3 |

q3 tracker 返回：#1496 OPEN、#2114 OPEN、#1424 OPEN、#1323 OPEN。 q3b tracker 返回：#1719 OPEN、#1478 CLOSED、#1496 OPEN、#1340 OPEN、#1424 OPEN、#1599 CLOSED、#292 CLOSED、#415 CLOSED、#336 CLOSED、#474 CLOSED、#1226 CLOSED、#485 CLOSED、#820 CLOSED、#456 CLOSED、#274 CLOSED、#473 CLOSED、#695 CLOSED、#823 CLOSED、#825 CLOSED、#812 CLOSED、#421 CLOSED、#787 CLOSED、#59 CLOSED。 #1496 直读：OPEN，正文与 0 条评论。 #812 直读：CLOSED，正文与 10 条评论。 #485 直读：CLOSED，正文与 2 条评论。 #1478 直读：CLOSED，正文与 2 条评论。

- https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5148740332：CLOSED：S-3 定案为离开+不回，单段是残缺实现。举例的 j 是只见离开之情形。
- .chanlun/definitions/zhongshu.md:238–252,324–360,536：同一正本并列 R5 与 #1478 末外回抽角色；不回才破坏，回则延伸、有效 Zn 进外缘。
- https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：回抽在核心外可为旧单位窗所称突破；认实际角色，不等到回抽之后第三单元。
- https://github.com/Newchanlun/NewChanlun/issues/1496：OPEN，0 评论；正式两段式实现归此票。
- https://github.com/Newchanlun/NewChanlun/issues/485：CLOSED；anchor/高级三类点链修复；未完成共用中枢扫描的 R5。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5148740332；zhongshu.md:248–252,324–360,536；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661。

## Q4 · B · 确认前的关系如何对外命名，哪些消费者可以使用？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "ProvisionalSeparation" OR "当前切面" "趋势" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"ProvisionalSeparation" OR "当前切面" "趋势" in:title,body,comments' --json number,title,state,url` | 1 |
| tracker | "开放期严格分离" OR "临时的向上扩展" OR "发展中" "未完成尾部" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"开放期严格分离" OR "临时的向上扩展" OR "发展中" "未完成尾部" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | ProvisionalSeparation\|暂态\|当下.{0,10}(判断\|确认)\|候选.{0,12}准入 | `rg -n --max-columns 450 --max-columns-preview 'ProvisionalSeparation\|暂态\|当下.{0,10}(判断\|确认)\|候选.{0,12}准入' analysis/ docs/ .chanlun/` | 150 |
| tracker | #1426 正文与评论 | `gh issue view 1426 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 13 |
| tracker | #1429 正文与评论 | `gh issue view 1429 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 5 |
| tracker | #1437 正文与评论 | `gh issue view 1437 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 2 |

q4 tracker 返回：#2114 OPEN。 q4b tracker 返回：#1426 OPEN。 #1426 直读：OPEN，正文与 12 条评论。 #1429 直读：OPEN，正文与 4 条评论。 #1437 直读：OPEN，正文与 1 条评论。

- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512：现有独立 ProvisionalSeparation 是暂行合同，无正式趋势权。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7001165057：cut-106 的临时扩展标有 NOT_ASSERTED_DEFERRED_1426；观察与完成对象分开。
- docs/agents/doctrine-rules.md:49–55；CONTEXT.md:218–220,251–256：不同命题可分层；观察不可参与正式准入。避免借用已定义的背驰活假设或候选中枢名。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6990012358；https://github.com/Newchanlun/NewChanlun/issues/1437：上级要可证结构和血缘，买卖标签另需确认及可知时点。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512；https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7001165057；CC-020/025。
**推导**：可观察的相邻对方向和公式是快照命题，已形成是另一个有时钟的稳定首证命题；区分即可保留切面信号，又不降低后续准入条件。
**默认候选**：采用开放期严格分离（趋势未确认）/ProvisionalSeparation；CC-025 未形成、无正式方向或时钟。

## Q5 · B · 首证 known_at 取哪根 K 线，追加/更正后何时修订、何时撤回？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "known_at" "撤回" OR "C08" "撤回" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"known_at" "撤回" OR "C08" "撤回" in:title,body,comments' --json number,title,state,url` | 14 |
| tracker | "当时可知" "不回填" OR "形成时点" "修订" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"当时可知" "不回填" OR "形成时点" "修订" in:title,body,comments' --json number,title,state,url` | 6 |
| repo | known_at\|修订/撤回\|修订／撤回\|修订与撤回\|C08 | `rg -n --max-columns 450 --max-columns-preview 'known_at\|修订/撤回\|修订／撤回\|修订与撤回\|C08' analysis/ docs/ .chanlun/` | 2027 |
| repo | 当时可知\|形成时点\|不回填 | `rg -n --max-columns 450 --max-columns-preview '当时可知\|形成时点\|不回填' analysis/ docs/ .chanlun/` | 346 |
| tracker | #1340 正文与评论 | `gh issue view 1340 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 10 |
| tracker | #1534 正文与评论 | `gh issue view 1534 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 9 |
| tracker | #1621 正文与评论 | `gh issue view 1621 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 18 |

q5 tracker 返回：#2114 OPEN、#1719 OPEN、#1340 OPEN、#1621 CLOSED、#1461 OPEN、#1460 OPEN、#1424 OPEN、#1534 CLOSED、#1406 OPEN、#1323 OPEN、#1467 OPEN、#1557 CLOSED、#1590 CLOSED、#1336 CLOSED。 q5b tracker 返回：#1468 OPEN、#1343 CLOSED、#1355 CLOSED、#1354 CLOSED、#1340 OPEN、#1550 CLOSED。 #1340 直读：OPEN，正文与 9 条评论。 #1534 直读：CLOSED，正文与 8 条评论。 #1621 直读：CLOSED，正文与 17 条评论。

- https://github.com/Newchanlun/NewChanlun/issues/1340 C08.2/.5/.6、AT-04：快照和变化同切面；实际 AsKnown 与后修重算分证。CC-025 要同时显示 known_at 和发生位置。
- docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md:273–282,312；docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md:60–76：撤回只追加；不能回填晚到结果，首达时刻不透支未来。
- https://github.com/Newchanlun/NewChanlun/issues/1534（CLOSED）；https://github.com/Newchanlun/NewChanlun/issues/1621（CLOSED）：前者确立生命周期，后者是分辨可审计时间和跨域顺序的实施先例，不以经济域时钟线偷换 S 原始切面。
- impl/1426-trend-formation @ 5e66d04ff65609c03f7706a22cfab7a5c2d70c27，s_session/browser/q3-center.js:413–417,540–563：CC-020 同对变叶与对象撤回是独立变化；同对修订保留 formed_known_at。Python/JS/生产结构只作现状证据。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1340 C08；ADR 0051 §三；CC-025。
**推导**：先看命题与身份：相邻对仍存在而其观察叶改变，是事实的新修订；已确认趋势假据被推翻时旧主张失效，必须撤回。首证不变则保留原锚；实际提交代不能伪装成更早提交。
**默认候选**：形成时钟取合取第一次可知的原始收盘切面，S 发布另按实际提交记录；有效同身份更新走修订，失效走追加撤回及适用替代，旧 AsKnown 不动。

## Q6 · A · 上下行与不同自然级别用同一形成判据吗？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "总缝规则" OR "同输入同输出" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"总缝规则" OR "同输入同输出" in:title,body,comments' --json number,title,state,url` | 30 |
| repo | 总缝规则\|同输入同输出\|同一个判定.{0,6}每一级 | `rg -n --max-columns 450 --max-columns-preview '总缝规则\|同输入同输出\|同一个判定.{0,6}每一级' analysis/ docs/ .chanlun/` | 90 |
| tracker | #804 正文与评论 | `gh issue view 804 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 4 |
| tracker | #1531 正文与评论 | `gh issue view 1531 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 10 |
| tracker | #1429 正文与评论 | `gh issue view 1429 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 5 |

q6 tracker 返回：#1651 OPEN、#1439 OPEN、#1486 OPEN、#1531 CLOSED、#2114 OPEN、#1669 CLOSED、#809 CLOSED、#1489 CLOSED、#1605 CLOSED、#1604 CLOSED、#1603 CLOSED、#1602 CLOSED、#1229 CLOSED、#1302 CLOSED、#1294 CLOSED、#1228 CLOSED、#1601 CLOSED、#1265 CLOSED、#1266 CLOSED、#1249 CLOSED、#1488 CLOSED、#1053 CLOSED、#1619 CLOSED、#1621 CLOSED、#1347 CLOSED、#960 CLOSED、#1350 CLOSED、#975 CLOSED、#1598 CLOSED、#804 CLOSED（输出上限 30，不声称全量）。 #804 直读：CLOSED，正文与 3 条评论。 #1531 直读：CLOSED，正文与 9 条评论。 #1429 直读：OPEN，正文与 4 条评论。

- docs/agents/doctrine-rules.md:61–98：同输入输出逐位相同；级别只作为输入，机械锁必须实际执行；例外须举证、退场和配额。
- https://github.com/Newchanlun/NewChanlun/issues/804（CLOSED）；https://github.com/Newchanlun/NewChanlun/issues/1531（CLOSED）：总缝正本与严格判据唯一/级别同构锁。
- docs/chanlun/text/blog/020-第20课.md:58；.chanlun/definitions/qushi.md:124–144：同条已裁双向对偶，用同一关系/结算事实输入。

**出处**：docs/agents/doctrine-rules.md:61–98；https://github.com/Newchanlun/NewChanlun/issues/1531；qushi.md:124–144。

## Q7 · A · 严格外缘、Zn 总集与中枢成立本身是否重裁？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "外缘分离" OR "依次同向" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"外缘分离" OR "依次同向" in:title,body,comments' --json number,title,state,url` | 15 |
| repo | 外缘分离\|依次同向\|后GG<前DD\|后DD>前GG | `rg -n --max-columns 450 --max-columns-preview '外缘分离\|依次同向\|后GG<前DD\|后DD>前GG' analysis/ docs/ .chanlun/` | 128 |
| tracker | #815 正文与评论 | `gh issue view 815 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 11 |
| tracker | #812 正文与评论 | `gh issue view 812 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 11 |
| tracker | #1478 正文与评论 | `gh issue view 1478 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 3 |

q7 tracker 返回：#2114 OPEN、#1426 OPEN、#900 CLOSED、#1011 CLOSED、#882 CLOSED、#898 CLOSED、#894 CLOSED、#897 CLOSED、#815 CLOSED、#847 CLOSED、#322 CLOSED、#794 CLOSED、#870 CLOSED、#252 CLOSED、#787 CLOSED。 #815 直读：CLOSED，正文与 10 条评论。 #812 直读：CLOSED，正文与 10 条评论。 #1478 直读：CLOSED，正文与 2 条评论。

- https://github.com/Newchanlun/NewChanlun/issues/815#issuecomment-5173454002：CLOSED：只按外缘严格分离判同向；核心分离而外缘不分是扩展，不放宽为趋势。
- https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5145337088；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：Z-6 中枢无候选态；#1478 保持全部合法 Zn 口径与端点归属。
- .chanlun/definitions/qushi.md:124–144；.chanlun/definitions/zhongshu.md:210–232,416–426：几何、成员和中枢存在均已有正本。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/815#issuecomment-5173454002；https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5145337088；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661。

## 固定原件与可手算的判别例

- 原课核对随 `draft.md` 权威依据表。另检 `030-第30课.md:132–136`：:132 为读者假设，:134 是分隔后缠师答、:136 署明，讨论有无第二中枢和价格非保证，未裁正式首证时点。`019-第19课.md:1198–1204` 的「第二个中枢完成」首先见于读者提问，不当作作者的定义句。
- 固定 SPEC JSON 以 Git 对象 `efc1ddc4d6c015f4f8c6d44f904d704a88308b46:.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/inputs/SPEC-COVERAGE-INPUT.json` 读 CC-019 :9990 起（重点 :10031–10037）、CC-025 :11001–11036、CC-061 :17038 起、CC-062 :17200 起；再核 [当前 #1340 C08/R3–R5](https://github.com/Newchanlun/NewChanlun/issues/1340)，后裁未替换本边界。
- 远端可从候选的 `rust/tests/fixtures/trend_formation_1426.json` 和 `rust/src/theta_v0/classifier/tests/trend_formation_1426.rs:35–69,149–415,419–477` 提取两条原始 OHLC 流（分叉严格复用 n=111，尾部新加 91 根）。[原 123 输入评论](https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7023365989) 和 [F 两向核对评论](https://github.com/Newchanlun/NewChanlun/issues/1424#issuecomment-7023030025) 双校输入与阶段；本地只读交叉核了 F 的 `/Volumes/AgentStorage/issue1424-newbirth-witness-20261119/selected.json` 中 down-123/up-123 段行，及非作者 R1 的 `raw-fork-v2.log`、R2 的 `REPORT.md`（在 #1426 两轮摘要所列目录）。远端以分支内夹具、生产解析和票评论复核，不要求挂载该卷。
- 用段行手证而不取代码结算位：下行 A 核心 [4000,5500]，u3（37→49，5500→2500）离开，u4（49→61，2500→2900）首回不到 4000；B 核心 [2200,2800]，u7（85→97，2800→2100）已经离开，u8（97→109，2100→2150）首次回抽且 `2150 < 2200`。u8 在 111 未具备完成证，在 123 首次完整可知。按 #1478 它可叫首个全区间不交的「突破段」，但角色是首回抽；#812/R5 不能被简化成看这个单元，也不能误解释成一律再等 u9。上镜像同法，末回抽低点 6350 > 6300。两极端比较：下行 `2900 < 3000`，镜像 `5600 > 5500`；保持本级已成而走势仍未完成。源索引用零基：111→110、123→122、202→201。
- 分叉读数：n=202、B.GG=3411、A.DD=3000，B 核心 [2200,2800]、连接 49→61 同一且 B 窗仍开放；这不能证明任何已结算的同一首对被正常后缀撤回。第 123 根属于原续流，不混入另一个 202 分叉。
- 权威边界分工：原始博文 > 编纂版 > 思维导图；本票只用博文作原文依据。取证基线的 `formal/Origin/CenterStates.lean:215–238`、`CenterConstruct.lean:408–450`、`ScanAssemblyMirror.lean:352–381`、`TrendCompleteClassification.lean:66–80` 分别覆盖几何、旧窗、离开/回抽几何、完成后的域；既无以开放窗正式确认的等式，旧窗也非两阶段事件。实现只提供反证和待落代码入口。

## 依赖对账

只读复现：`gh api repos/Newchanlun/NewChanlun/issues/<票号>/dependencies/<blocking|blocked_by> --paginate`。核了 #2114、#1496、#1426、#1429、#1437、#1424、#1419；另以 #1434/#1433/#1436/#1443 的 blocked_by 反核。

- #2114 已实接阻 #1426；#1426 原 blocker 为 #1419、#1424、#1359（closed）及 #2114，未实接 #1496。
- #1496 的 blocker 只有 #1419。其现有被阻塞方 #1443 不动；PASS 后新增 #1496 → #1426 不形成环。
- #1426 原生阻 #1429/#1443；#1429 原生阻 #1431/#1432/#1434/#1443；#1437 原生前置 #1433/#1434/#1436/#1359（closed）；#1443 的原生前置含 #1426/#1429/#1437/#1496。无需加重复直边。票和边本轮未动（除 #2114 单行分级评论）。

机械校验：每点两路、tracker 含开闭与评论、A/B 有出处、四个 B 均有推导和默认候选；无 research/probe，七点全入草稿考古对照。
