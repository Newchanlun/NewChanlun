# #2114 第 3 稿考古

主线原件 `b9d898dccf46c2a716115eaa1215bc39c458a959`；#1426 实现原件 `271f3fbef99d3bbdffb4581f2610eb3679c6468b`；查询日 2026-11-20。分级 T，`user_gate=[]`，沿用票上已存在的分级评论。Q1–Q5 为 B，Q6–Q7 为 A；没有外部事实或探针缺口。本稿为新会话整链重跑；旧审法不是引文依据。

## Q1 · B · A 已结算、B 开放且当前严格外缘分离时，原文如何称说，本仓能否发布正式趋势？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `第二个(同级别)?(走势)?中枢&#124;构成趋势&#124;开放期&#124;未结算.{0,20}(趋势&#124;形成)` | `rg -n --max-columns 450 --max-columns-preview '第二个(同级别)?(走势)?中枢&#124;构成趋势&#124;开放期&#124;未结算.{0,20}(趋势&#124;形成)' analysis/ docs/ .chanlun/` | 122；见下面的命中及处置 |
| tracker | `"第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments' --json number,title,state,url` | 7；#2114 OPEN、#1426 OPEN、#485 CLOSED、#1419 OPEN、#832 CLOSED、#815 CLOSED、#812 CLOSED |
| repo | `第二个同级别中枢&#124;形成两个依次同向&#124;中枢的新生&#124;第二个中枢` | `rg -n --max-columns 450 --max-columns-preview '第二个同级别中枢&#124;形成两个依次同向&#124;中枢的新生&#124;第二个中枢' analysis/ docs/ .chanlun/` | 94；见下面的命中及处置 |
| tracker | `"第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments' --json number,title,state,url` | 1；#2114 OPEN |
| repo | `中枢完成前&#124;一个中枢的完成&#124;第二个中枢的前三段` | `rg -n --max-columns 450 --max-columns-preview '中枢完成前&#124;一个中枢的完成&#124;第二个中枢的前三段' analysis/ docs/ .chanlun/` | 11；见下面的命中及处置 |
| tracker | `"中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments' --json number,title,state,url` | 1；#2114 OPEN |
| repo | `形成了&#124;才算(下跌&#124;上涨)&#124;第二个(同级别)?(走势)?中枢&#124;第二[个個]?中[枢樞]&#124;是否延续&#124;演化成` | `rg -n --max-columns 450 --max-columns-preview '形成了&#124;才算(下跌&#124;上涨)&#124;第二个(同级别)?(走势)?中枢&#124;第二[个個]?中[枢樞]&#124;是否延续&#124;演化成' docs/chanlun/text/blog/` | 151；见下面的命中及处置 |
| repo | `(趋势&#124;升势&#124;跌势&#124;上涨&#124;下跌).{0,18}(成立&#124;形成&#124;走出来&#124;尚未&#124;不算)&#124;(成立&#124;形成&#124;才算&#124;就是&#124;构成).{0,20}(趋势&#124;升势&#124;跌势&#124;上涨&#124;下跌)&#124;两[个個](同级别)?(走势)?中枢` | `rg -n --max-columns 450 --max-columns-preview '(趋势&#124;升势&#124;跌势&#124;上涨&#124;下跌).{0,18}(成立&#124;形成&#124;走出来&#124;尚未&#124;不算)&#124;(成立&#124;形成&#124;才算&#124;就是&#124;构成).{0,20}(趋势&#124;升势&#124;跌势&#124;上涨&#124;下跌)&#124;两[个個](同级别)?(走势)?中枢' docs/chanlun/text/blog/` | 431；见下面的命中及处置 |

- docs/chanlun/text/blog/036-第36课.md:26,30：实案 2892 > 2888；有效突破前仍可扩展，第二枢尚未走完可当下组合。
- docs/chanlun/text/blog/102-第102课.md:238：1 分钟下跌已形成；B 尚可反向三买或走 c 再标准背驰。
- docs/chanlun/text/blog/035-第35课.md:122：当下 30 分钟上涨；是否延续、是否演化为更大中枢仍待。
- docs/chanlun/text/blog/025-第25课.md:304–308：新下跌自身第二枢才算下跌；不能借旧上涨 A。
- docs/chanlun/text/blog/020-第20课.md:32：完成前波动仍可触及前枢形成更大级别枢。
- docs/chanlun/text/blog/041-第41课.md:317–319：读者问是否仅看前三段；缠师答完成与三类点关联，延伸即未完成。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512：同一前 111 根，普通续流可在第 202 根扩展。

**归类：B。** 原文有当下趋势叫法与可变几何；并无二者等于逐 bar 正式类型信号的合同。只比较发布候选：111→202 保持身份却翻叶，故不可将普通发展制造为正式首证撤回。#799/ADR 0041 裁定二不容同一判断两档；当下读法仍有效。
**在案差异：** 第 1 轮未处理同状态称「形成」的原句；第 2 轮把技术边界标成 [旧缠论]，与这些原句相悖。
**推荐并落稿：** 采候选 3：开放切面发布观察，双 R5 且严格分离的真实相邻首对才给正式类型。下列记录列足正反语料。

## Q2 · B · 何时正式确认，如何区别中枢离开、结算、类型确认、走势实际完成和继任？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `走势必完美&#124;后中枢.{0,16}(结算&#124;确认)&#124;停在核心之外的那段回抽&#124;破坏未证&#124;首回试.{0,10}完成` | `rg -n --max-columns 450 --max-columns-preview '走势必完美&#124;后中枢.{0,16}(结算&#124;确认)&#124;停在核心之外的那段回抽&#124;破坏未证&#124;首回试.{0,10}完成' docs/chanlun/text/blog/ .chanlun/definitions/ docs/adr/` | 74；见下面的命中及处置 |
| tracker | `"趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments' --json number,title,state,url` | 13；#2114 OPEN、#1426 OPEN、#1360 OPEN、#1429 OPEN、#1443 OPEN、#1323 OPEN、#1463 CLOSED、#871 CLOSED、#877 CLOSED、#832 CLOSED、#858 CLOSED、#854 CLOSED、#1340 OPEN |
| repo | `isTrend&#124;IsUpTrend&#124;IsDownTrend&#124;CompletedTrend&#124;TrendFormed&#124;ProvisionalSeparation&#124;firstRetest&#124;thirdClassSide&#124;known_at&#124;first_known` | `rg -n --max-columns 450 --max-columns-preview 'isTrend&#124;IsUpTrend&#124;IsDownTrend&#124;CompletedTrend&#124;TrendFormed&#124;ProvisionalSeparation&#124;firstRetest&#124;thirdClassSide&#124;known_at&#124;first_known' formal/Origin/` | 95；见下面的命中及处置 |

- https://github.com/Newchanlun/NewChanlun/issues/1496：实际中枢破坏需离开与完成首回抽，旧塔有误关样本。
- .chanlun/definitions/zhongshu.md:324–360,536：S-3/R5 是中枢结束语义，不是走势结束。
- formal/Origin/CenterStates.lean:215–238；formal/Origin/TrendCompleteClassification.lean:66–80：前者为静态几何，后者为已完成良构三分。
- #1340 冻结 JSON /classification_axes/18,22,24,61：分别判破坏、完成分类、实例、同级连接，域不可混。

**归类：B。** 中心的两段式结束有既定谓词，但没有为走势发布首证的切面；CC-025 保护实例生命周期，CC-023 分类限定已完成，CC-062 已完成后才排除同向同级继任。若离开早于首次完成的合法回试，证据未齐，不回填；证齐时即使走势尚未完成也可以发布类型。
**在案差异：** 现头用两次单段扫描结算作临时确认，不是两端 R5。
**推荐并落稿：** 同一切面收两个 R5、真实相邻连接及外缘，第一根齐证 K 线作为 known_at 输入锚；不代填走势完成或继任。

## Q3 · B · 如何据在案 R5 推导段角色并处理反向结算；同向 T3-in-c 是否是形成门？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `两段式&#124;c[[:space:]]*至少包含对[[:space:]]*B&#124;T3-in-c&#124;trend_third_class_in_c&#124;第5段构成第三类&#124;先挂起看下一段&#124;停在核心之外的那段回抽` | `rg -n --max-columns 450 --max-columns-preview '两段式&#124;c[[:space:]]*至少包含对[[:space:]]*B&#124;T3-in-c&#124;trend_third_class_in_c&#124;第5段构成第三类&#124;先挂起看下一段&#124;停在核心之外的那段回抽' docs/chanlun/text/blog/ .chanlun/definitions/ docs/adr/` | 24；见下面的命中及处置 |
| tracker | `"两段式结算" OR "离开后看回抽" OR "不回则破坏" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"两段式结算" OR "离开后看回抽" OR "不回则破坏" in:title,body,comments' --json number,title,state,url` | 4；#1496 OPEN、#2114 OPEN、#1424 OPEN、#1323 OPEN |
| tracker | `"T3-in-c" OR "trend_third_class_in_c" OR "c至少包含对B" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"T3-in-c" OR "trend_third_class_in_c" OR "c至少包含对B" in:title,body,comments' --json number,title,state,url` | 27；#1229 CLOSED、#1260 CLOSED、#1249 CLOSED、#586 CLOSED、#1275 CLOSED、#584 CLOSED、#1278 CLOSED、#487 CLOSED、#1300 CLOSED、#1291 CLOSED、#1299 CLOSED、#606 CLOSED、#993 CLOSED、#607 CLOSED、#582 CLOSED、#589 CLOSED、#1226 CLOSED、#903 CLOSED、#883 CLOSED、#812 CLOSED、#1232 CLOSED、#565 CLOSED、#608 CLOSED、#913 CLOSED、#848 CLOSED、#846 CLOSED、#817 CLOSED |
| repo | `isTrend&#124;IsUpTrend&#124;IsDownTrend&#124;CompletedTrend&#124;TrendFormed&#124;ProvisionalSeparation&#124;firstRetest&#124;thirdClassSide&#124;known_at&#124;first_known` | `rg -n --max-columns 450 --max-columns-preview 'isTrend&#124;IsUpTrend&#124;IsDownTrend&#124;CompletedTrend&#124;TrendFormed&#124;ProvisionalSeparation&#124;firstRetest&#124;thirdClassSide&#124;known_at&#124;first_known' formal/Origin/` | 95；见下面的命中及处置 |

- https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：裁定一只遍历 Zn，裁定二是向 Zn 方向离开的端点；两种退场条件照旧。
- docs/chanlun/text/blog/061-第61课.md:44：第四段离开，第五段构成第三类点；作者正文。
- .chanlun/definitions/zhongshu.md:250–252,342–350,536：已有离开与回抽的两种角色解读，本票推导并由 #1496 同拍订措辞。
- docs/chanlun/text/blog/037-第37课.md:16–20；.chanlun/definitions/beichi.md:106–124：背驰结构前件先假定趋势，严守同向与新高/新低各自条件。
- https://github.com/Newchanlun/NewChanlun/issues/1229#issuecomment-5417718452：全窗后扫统一为 trend_third_class_in_c。
- https://github.com/Newchanlun/NewChanlun/issues/1300#issuecomment-5463525851：Lean IsType1 补 isTrend；当前源码 :92–97 与 :362–366 支持。

**归类：B。** 连续且方向交替的完成单元：第一个不重叠单元从外端反向回抽，前与核心相交的一段才是离开；若不相连使不重叠者本身为离开，则同一规则等待首回抽。第102课允许后枢直接反向破坏；结算用 R5，趋势方向读外缘，反向不作同向背驰前件。对反向末非 Zn 远端的比较直接继承 #1478，登记读数而非另立外缘。
**在案差异：** §5.2 与 §9 R5 把不重叠单元一概当离开；#1478 的评论没说「不等回抽之后第三单元」，其 §4.1 条款明指向 Zn 方向离开。
**推荐并落稿：** 按实际角色完成即取两段见证；同对反向 R5 后严格分离则依外缘确认；保留标准背驰／一类点的全窗同向见证，完成另证。

## Q4 · B · 未确认时如何对外表述，哪些状态保留，何者不能参与准入？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `ProvisionalSeparation&#124;开放期严格分离&#124;FORMED_OPEN&#124;暂态&#124;观察.{0,8}准入` | `rg -n --max-columns 450 --max-columns-preview 'ProvisionalSeparation&#124;开放期严格分离&#124;FORMED_OPEN&#124;暂态&#124;观察.{0,8}准入' .chanlun/definitions/ docs/adr/` | 4；见下面的命中及处置 |
| tracker | `"ProvisionalSeparation" OR "开放期严格分离" OR "待升级" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"ProvisionalSeparation" OR "开放期严格分离" OR "待升级" in:title,body,comments' --json number,title,state,url` | 1；#2114 OPEN |

- rust/src/theta_v0/classifier/trend_formation.rs@271f3fbe:45–57,136–173：PairState 已有观察、扩展交接、升级待定；本票划定实例发布侧适用域。
- #1340 冻结 JSON /classification_axes/19,22,23,24：CC-020 两个有效枢及相邻性；已完成分类、技术与语义方向、实例状态各有主体。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6152239745：仅待升级不宣告中枢不存在。

**归类：B。** 先有单枢实例；B 合法新生时五叶可知，形成门未证；实例生命周期、关系几何与知识状态分别输出，避免实例回退、五叶变六叶和下游把关系当正式趋势。
**在案差异：** 第 2 稿将观察叫作 CC-020 关系观察，易读为第六叶。
**推荐并落稿：** ProvisionalSeparation 含观察方向、不准入，五叶独立，同实例 FORMED_OPEN 不回退；扩展或待升级只按适用域交接。

## Q5 · B · 如何记知识时间；普通追加、数据更正、结构归属失效分别何时修订或撤回？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `known_at&#124;AsKnown&#124;RecomputedWithRevision&#124;修订.{0,8}撤回` | `rg -n --max-columns 450 --max-columns-preview 'known_at&#124;AsKnown&#124;RecomputedWithRevision&#124;修订.{0,8}撤回' docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md` | 24；见下面的命中及处置 |
| tracker | `"known_at" "撤回" OR "C08" "撤回" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"known_at" "撤回" OR "C08" "撤回" in:title,body,comments' --json number,title,state,url` | 14；#2114 OPEN、#1719 OPEN、#1340 OPEN、#1621 CLOSED、#1461 OPEN、#1460 OPEN、#1424 OPEN、#1534 CLOSED、#1406 OPEN、#1323 OPEN、#1467 OPEN、#1557 CLOSED、#1590 CLOSED、#1336 CLOSED |

- docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md:273–294：撤回追加、原 cut 与 AsKnown 不动；同切面 delta 可重放。
- https://github.com/Newchanlun/NewChanlun/issues/1621#issuecomment-6390401345：已合入的跨域获知时钟复核，非本票结构输入锚定义。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6990012358：待升级中枢对保有 ID、连接；叶与方向为空。
- rust/src/bin/s_session_v3/content_structure.rs@271f3fbe:2790–2816：既有关系变更为 pending_upgrade、leaf_revised 等；不是 PairState。

**归类：B。** 结构几何证齐所在的输入前沿与 S 实际提交、接收分列；旧 AsKnown 固定。普通发展保留同一有效关系，可变的是叶或证据；失效才追加撤回，替代在当前提交。#1429 未决和已证明失效是两种状态。
**推荐并落稿：** 同身份原主张有效则修订；失效才撤；待升级保留旧对叶暂空；更早重算锚只在 RecomputedWithRevision。

## Q6 · A · 上下方向和各级是否用同一形成判据？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `总缝规则&#124;同输入同输出` | `rg -n --max-columns 450 --max-columns-preview '总缝规则&#124;同输入同输出' docs/agents/doctrine-rules.md docs/adr/ .chanlun/definitions/` | 30；见下面的命中及处置 |
| tracker | `"总缝规则" OR "同输入同输出" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"总缝规则" OR "同输入同输出" in:title,body,comments' --json number,title,state,url` | 50；#1651 OPEN、#1439 OPEN、#1486 OPEN、#1531 CLOSED、#2114 OPEN、#1669 CLOSED、#809 CLOSED、#1489 CLOSED、#1605 CLOSED、#1604 CLOSED、#1603 CLOSED、#1602 CLOSED、#1229 CLOSED、#1302 CLOSED、#1294 CLOSED、#1228 CLOSED、#1601 CLOSED、#1265 CLOSED、#1266 CLOSED、#1249 CLOSED、#1488 CLOSED、#1053 CLOSED、#1619 CLOSED、#1621 CLOSED、#1347 CLOSED、#960 CLOSED、#1350 CLOSED、#975 CLOSED、#1598 CLOSED、#804 CLOSED、#1348 CLOSED、#1790 CLOSED、#814 CLOSED、#1590 CLOSED、#816 CLOSED、#815 CLOSED、#1565 CLOSED、#1612 CLOSED、#810 CLOSED、#348 CLOSED、#1561 CLOSED、#812 CLOSED、#980 CLOSED、#984 CLOSED、#1406 OPEN、#827 CLOSED、#862 CLOSED、#826 CLOSED、#1560 CLOSED、#1559 CLOSED |

- https://github.com/Newchanlun/NewChanlun/issues/804#issuecomment-5138190089：同一判断各级一致，只有输入值可换。
- https://github.com/Newchanlun/NewChanlun/issues/1531#issuecomment-6381351416：严格唯一与级别同构落 ADR 0047。
- docs/agents/doctrine-rules.md:61–104：同输入逐位相同的行为锁，例外需权威与退出条件。

**归类：A。** 级别只作输入；按语义行为而不按分支形状判断。镜像换方向及对应端点，不改变证据职责；不新增例外。
**沿用：** 直接沿用 #804 与 #1531 的测试锁。

## Q7 · A · 严格外缘、Zn 全集与中枢成立本身是否重裁？

| 路 | 查询词 | 复跑命令 | 命中 |
|---|---|---|---|
| repo | `外缘分离&#124;依次同向&#124;后GG<前DD&#124;后DD>前GG&#124;Zn 总集` | `rg -n --max-columns 450 --max-columns-preview '外缘分离&#124;依次同向&#124;后GG<前DD&#124;后DD>前GG&#124;Zn 总集' docs/chanlun/text/blog/ .chanlun/definitions/` | 31；见下面的命中及处置 |
| tracker | `"外缘分离" OR "依次同向" in:title,body,comments` | `gh issue list -R Newchanlun/NewChanlun --state all --limit 50 --search '"外缘分离" OR "依次同向" in:title,body,comments' --json number,title,state,url` | 15；#2114 OPEN、#1426 OPEN、#900 CLOSED、#1011 CLOSED、#882 CLOSED、#898 CLOSED、#894 CLOSED、#897 CLOSED、#815 CLOSED、#847 CLOSED、#322 CLOSED、#794 CLOSED、#870 CLOSED、#252 CLOSED、#787 CLOSED |

- https://github.com/Newchanlun/NewChanlun/issues/815#issuecomment-5173454002：严格外缘为同向判据，不能用核心分离替代。
- https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5145337088：Z-6 不设候选枢。
- .chanlun/definitions/zhongshu.md:218–232,254–266,416–420：Zn、严格几何与中枢存在锚定既有正本。

**归类：A。** 外缘只遍历所有有效 Zn，严格新生与扩展均按五叶；中枢三段成立无候选，开放是生命周期；和本票的发布门不同。
**沿用：** 沿用；外缘等号在核心严格分离时为扩展，核心相切不归扩展。

## Q1 逐行复筛和四步核

Q1 首条仓内查询原样复跑 122 行；旧第二条 94、第三条 11。两条换说法的博文复搜分别 151、431 行，重合按「博文路径＋行号」消重；另以窗口短摘分课号段核读，长命中回到 `nl -ba docs/chanlun/text/blog/<课>.md` 查问答边界。下表按原文段组计：**8 组当下／构成表述，3 组开放期／扩展边界**；「构成／条件」与「当下已明确称形成」分开。未将摘要、图注或读者转述算成作者原话。102、035 无给出完整数值外缘，不从注家补算；036:26 则直接给出两个价位。

### 八组当下／构成表述

| 博文行号 | 逐字锚（非全文） | 作者归属与注 | 读法与边界 |
|---|---|---|---|
| `018-第18课.md:42,44` | 「形成两个依次同向的缠中说禅走势中枢后，任何趋势都可以随时结束而完美」；「相应的“类型”必然是确定的」 | 界 :68 前；作者正文；:42/:44 无行首或行内注，后续 :46–48 是娇注，不引。 | 以两同向枢判断当下类型，可继续；没写「形成」必须先有后枢三类点。:28 对完成类型的定义和不重叠条件另存。 |
| `025-第25课.md:304–308` | 「然后再跌破中枢下去形成新的中枢构成下跌。」；「在下面形成第二个中枢才算下跌」 | 界 :54 后；:300/:302 缠师答头；:304 猫猫提问，:306 `==` 后及 :308 为缠师，无注。 | 第②支的第二枢是新下跌自己的第二枢，不能把旧上涨 A 混入。是第二枢新生的构成语义，未给完成该枢的额外门，未报数值外缘。 |
| `035-第35课.md:122` | 「这次上来就是两个中枢2858下面一个，2911下面一个，从而形成30分钟级别的上涨，」；「现在的问题是这个上涨是否延续，还是最后演化成a`+B型。」 | 界 :38 后；:116/:118 缠师回复，:120 读者，:122 只取 `=` 后两段，跳过「(注：这两个30分中枢震荡高点有重叠，后面走势完成后第二个中枢后移，满足不叠的要求）」。 | 已有两枢而称上涨；B 去向开放，同日 :60/:64 明说仍绕 2911 枢、后续三买待出。精确外缘数值不从注家取得。 |
| `036-第36课.md:26` | 「这个中枢震荡的低点2892点比2888点高，如果其后的震荡不出现跌破2888的走势，那么就是一个30分钟的上涨走势形成了。」；「但在这个新的中枢被一个新的第三类买点有效突破前，依然存在震荡跌破2888点甚至最终确认中枢扩展。」 | 界 :42 前；作者正文；:26 无注，相邻 :22/:24/:28 是图。 | 明确同级与当下分离；作者的「形成了」带条件，不升级为无条件断言，也不把组合变动当作同一实现 ID 的规定。 |
| `078-第78课.md:166` | 「A+b+B也是一分钟的上涨，关键是两个中枢之间没重合，中枢之前之后有没有走势并不重要。」 | 界 :64 后；:156/:158 缠师头，:160/:162 读者问，:164 图，:166 `==` 后为缠师，无注。 | 切片组合上承认无末段 c 的两枢上涨；提问参考完整历史走势，不能据此还原实时 R5 与价格比较。这是构成旁证。 |
| `099-第99课.md:196,200` | 「下午那波反弹完成第二个1分钟中枢的构造，所以，4695点下来的走势，肯定至少是1分钟级别的下跌了。」；「这反弹就在今天所构成的1分钟中枢范围内结束」 | 界 :42 后；:184/:186 为缠师 2008-02-25 解盘题名／时刻；摘引两处无注。 | :196 的第三类卖点属于前一个枢；下午完成的是第二枢的「构造」，:200 的可能后缀仍在这个枢内。是当下称下跌的新增例，原段没有完整外缘数值。 |
| `102-第102课.md:238` | 「技术上，那1分钟的下跌也形成了，目前唯一需要确定的是，第二个中枢是直接第三类买点反弹上去，还是把a+A+b+B+c的c给走出来再标准背弛上去。」 | 界 :48 后；:234/:236 缠师 2008-03-11 解盘题名／时刻，:238 无注；上一交易日 :216 只证首枢三卖。 | 已称下跌形成、后枢仍待决定；反向三买是其中一支，不等于同向 T3-in-c，也没定义发布钟。 |
| `105-第105课.md:468` | 「3700点上下来的下跌进入第二中枢的震荡，一旦出现背驰将宣告调整结束」 | 界 :30 后；:466 缠师 2008-06-23 解盘题名、时刻合行；:468 无注。:430/:432 题签对应 :448/:452，均无注。 | 在第二枢震荡时以「下跌」称整个走势；未报外缘数值或独立完成门。早先 :448/:452 是待第二枢的前瞻、另有反向三买路径，不重复算当下已形成。 |

### 三组开放期／扩展边界

| 博文行号 | 逐字锚 | 作者归属与注 | 处置 |
|---|---|---|---|
| `020-第20课.md:32` | 「一个走势中枢完成前，其波动触及上一个走势中枢或延伸时的某个瞬间波动区间，由此产生更大级别的走势中枢。」 | 界 :94 前；缠师正文，行首「二、」是列项，无注。 | 普通后缀可以翻转当下严格分离；未定义趋势「正式确认」。 |
| `041-第41课.md:317,319` | 「概念有问题，一个中枢的完成，是和第三类买卖点相关的。如果一个中枢延伸，就证明没完成。」 | 界 :36 后；:313/:315 为缠师回复头；:317 九头鸟引 020:32 问是否只算前三段；:319 才是答；无注。 | 回答中枢何时完成，不能倒读成作者不称开放期趋势「形成」。 |
| `036-第36课.md:30` | 「中枢扩展的定义是在两个中枢都完全走出来的情况下定义的，而实际操作中，往往第二个中枢还没有走完，还在继续延伸中」 | 界 :42 前，缠师正文；引文截在两处「(注：…）」「(娇注：…）」之前，未引注。 | 作者明分终局分类和当下可用的组合；支持在发布层区分观察和不回填的正式首证。 |

### 补充命中与排除

| 博文窗口 | 核读后的处置 |
|---|---|
| `017:38,44,46,48`，`018:28`；`020:52,58` | 正文，分别在界 :98/:68/:94 前，引句无行内注。:46 起「某完成的走势类型」，:48 另行才是方向；:58 无「完成后」三字，只给几何等价。教义定义不充发布协议。 |
| `021:34` | 界 :74 前正文，无注：「而中枢新生，就形成一个上涨的趋势」；说 A 的三买后的两种发展，没交代 B 是否开放或其确认时间。属一般构成旁证。 |
| `023:184–190,298–306,334–352` | 界 :24 后；:188 的答隔 :186、答时 :194；「但两个中枢并没有形成趋势，只形成了中枢的扩展。只有中枢的新生才能形成趋势的。」是作者，:184 与 :340 是读者。:298 是引前篇的问方，:306 答复为三分。:344 后 :346–348 是缠师答插班生（:352 时刻），说 5 分钟中枢可能回跌原 30 分钟中枢；这是跨级或外缘不合格，不是开放但外缘严格分离的反例。 |
| `019:454–468,516–526,792–804` | 界 :38 后；:460 答隔后的 :462–466 讲 seed 三走势要完成；:520 后 :524（:526 答时）「次级别的三个走势还没完全走出来」——首枢后的 B 尚未成立，不是已成立开放 B。:794 后 :800（:804 答时）两枢足以完成且可二十枢，是一般延伸旁证。 |
| `027:700–714` | 界 :78 后，:700 缠师回帖、:702/:704 两访客，:712 分隔后 :714 缠师、无注。「你首先要形成趋势，也就是要有两个中枢。最后一个出现后，就意味着进入背驰段」。相关，佐证先有二枢结构才看背驰；问的是背驰、没有示出 B 的外缘和完成切面，不能作为 R5 结论。:148 问、:152 答（:548 重复合并）讲一个中枢及两段比较，不计「已形成双枢」。 |
| `030:114–134`；`031:506–512` | 界 :40/:32 后；030:134 属 :114/:116 作者回复头，段中嵌有问答，`==` 后才是答「目前的关键是否能形成第二个中枢的问题」，只谈形成前。031:506 是读者，作者 :512 的第二枢属明日假设。 |
| `042:136–146,229–237` | 界 :46 后，:136/:138 回复头，:142 读者，:146 缠师谈同级读法；:229/:231 作者回复，:237 仅 `==` 后答围绕新枢的波动已重叠要扩展。前者分解选择、后者已经触及，均不否定当下严格分离叫趋势。 |
| `048:152–164`；`058:28–34`；`059:40–42` | 048 界 :32 后，:152/:154 回复头，:160 为读者引第47课，:164 缠师「对于趋势，有两个中枢后就可以随时结束」只讲随时可结束。058/059 在界 :40/:50 前，作者正文，无行内注的 :34/:42 都把后枢是否形成及最终不重叠列为条件；尚未展示严格分离的开放后枢。 |
| `053:32,38–42,46–60` | 界 :36。:32 作者正文只说枢结束和后续选项；:38–42 在界后、无作者回复头，:46 后明确转载。从未认证的 :42 与注家 :58/:60 不进入作者原话清单。 |
| `086:74`；`087:60,102–110`；`091:80,214–218,228–240` | 086 在界 :84 前、无注；是举例谈操作与背驰，未给 B 的完成状态。087 界 :52 后、:54/:56 解盘头，:60 是新枢尚未成；:102–110 把「类下跌」与真正级别的后续分开。091 界 :62 后的 :80 第二枢已经三卖；:214–218 次日走法仍假设；:228/:238（:224/:226 解盘头）明确有二枢且后枢去向未定，但并未一句断言当下正式方向，作相近旁证。各处引义均避注。 |
| `100:24–26` | 界 :50 前；:24 作者正文。5 分钟只离开**第一个**中枢且无三卖，不能 100% 确定；1 分钟已成下跌但同段未交代该级 B 的状态。:26 是娇注，不纳入。 |
| `107:26,30,32` | 界 :36 前、正文无注；保留「上升趋势形成的最精确定义」原话。该课要求在操作信号后等第二枢，并非第二枢开放的例子；工程侧分层另打推论标签。 |

首条 122 行逐条复读；以下将原始命中逐行编号落到出处，顺序用「路径＋数值行号」固定。博文条目再按正文、解盘、问答、注家与事实域筛；非博文分别是正本/研究/旧报告及编纂重复，均不作为引文。长行中遇拼接回复只认拆分后的作者段；同一命中若只是别课反复转载，不再计一次。

### 首条查询的 122 个命中坐标

```sh
rg -n --max-columns 450 --max-columns-preview '第二个(同级别)?(走势)?中枢|构成趋势|开放期|未结算.{0,20}(趋势|形成)' analysis/ docs/ .chanlun/
```

```text
001  .chanlun/definitions/beichi.md:61
002  .chanlun/definitions/beichi.md:707
003  .chanlun/definitions/qushi.md:128
004  .chanlun/definitions/qushi.md:149
005  .chanlun/definitions/zhongshu.md:350
006  .chanlun/review-results/issue815-m2-same-direction-doctrine-20260803.md:46
007  .chanlun/review-results/issue815-m2-same-direction-doctrine-20260803.md:52
008  .chanlun/review-results/issue815-m2-same-direction-doctrine-20260803.md:77
009  .chanlun/review-results/issue817-n5-cand-definition-20260805.md:440
010  .chanlun/review-results/issue820-center-rescan-anchor-20260730.md:74
011  .chanlun/review-results/issue824-tiandao-ggdd-20260731.md:336
012  .chanlun/review-results/issue825-tiandao-full-ocr-20260731.md:151
013  .chanlun/review-results/issue825-tiandao-full-ocr-20260731.md:356
014  .chanlun/review-results/issue826-tower-vs-same-level-decomp-20260731.md:62
015  .chanlun/review-results/issue830-recursion-base-doctrine-20260731.md:105
016  .chanlun/review-results/issue832-B-later-courses-20260731.md:190
017  .chanlun/review-results/issue832-B-later-courses-20260731.md:194
018  .chanlun/review-results/issue832-B-later-courses-20260731.md:195
019  .chanlun/review-results/issue832-B-later-courses-20260731.md:199
020  .chanlun/review-results/t3-in-c-caliber-20260728.md:316
021  .chanlun/review-results/tiandao-ch5-mingbian-20260728.md:90
022  .chanlun/review-results/tiandao-zhixingheyi-20260728.md:127
023  .chanlun/review-results/tiandao-zhixingheyi-20260728.md:222
024  analysis/beichi_round4_basic_principles.md:101
025  analysis/beichi_round4_basic_principles.md:508
026  analysis/recursive_efficiency_validation.md:172
027  analysis/strict_form_audit.md:95
028  analysis/strict_form_audit.md:123
029  analysis/strict_form_audit.md:230
030  analysis/t_engine_profit_destination.md:255
031  analysis/t_engine_profit_destination.md:269
032  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:3597
033  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:3643
034  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:3950
035  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:3972
036  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:4232
037  docs/chanlun/mineru/缠中说禅-股市技术理论/58681e7d-7da5-4786-93b5-f862d8b9dd1d_content_list.json:10691
038  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:6602
039  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:6689
040  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:7181
041  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:7217
042  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:7664
043  docs/chanlun/mineru/缠中说禅-股市技术理论/content_list_v2.json:18458
044  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:653
045  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:661
046  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:713
047  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:715
048  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:760
049  docs/chanlun/mineru/缠中说禅-股市技术理论/full.md:1874
050  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:25445
051  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:26913
052  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:26992
053  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:29789
054  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:29810
055  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:76147
056  docs/chanlun/mineru/缠中说禅-股市技术理论/layout.json:76210
057  docs/chanlun/text/blog/016-第16课.md:16
058  docs/chanlun/text/blog/016-第16课.md:566
059  docs/chanlun/text/blog/017-第17课.md:586
060  docs/chanlun/text/blog/017-第17课.md:588
061  docs/chanlun/text/blog/017-第17课.md:660
062  docs/chanlun/text/blog/017-第17课.md:966
063  docs/chanlun/text/blog/017-第17课.md:1146
064  docs/chanlun/text/blog/019-第19课.md:524
065  docs/chanlun/text/blog/019-第19课.md:1198
066  docs/chanlun/text/blog/019-第19课.md:1200
067  docs/chanlun/text/blog/023-第23课.md:340
068  docs/chanlun/text/blog/025-第25课.md:38
069  docs/chanlun/text/blog/025-第25课.md:308
070  docs/chanlun/text/blog/027-第27课.md:14
071  docs/chanlun/text/blog/027-第27课.md:102
072  docs/chanlun/text/blog/027-第27课.md:148
073  docs/chanlun/text/blog/027-第27课.md:200
074  docs/chanlun/text/blog/027-第27课.md:310
075  docs/chanlun/text/blog/027-第27课.md:314
076  docs/chanlun/text/blog/027-第27课.md:342
077  docs/chanlun/text/blog/027-第27课.md:420
078  docs/chanlun/text/blog/027-第27课.md:548
079  docs/chanlun/text/blog/028-第28课.md:38
080  docs/chanlun/text/blog/028-第28课.md:268
081  docs/chanlun/text/blog/028-第28课.md:294
082  docs/chanlun/text/blog/028-第28课.md:830
083  docs/chanlun/text/blog/029-第29课.md:92
084  docs/chanlun/text/blog/029-第29课.md:226
085  docs/chanlun/text/blog/029-第29课.md:280
086  docs/chanlun/text/blog/030-第30课.md:68
087  docs/chanlun/text/blog/030-第30课.md:134
088  docs/chanlun/text/blog/031-第31课.md:506
089  docs/chanlun/text/blog/031-第31课.md:600
090  docs/chanlun/text/blog/031-第31课.md:614
091  docs/chanlun/text/blog/031-第31课.md:784
092  docs/chanlun/text/blog/034-第34课.md:146
093  docs/chanlun/text/blog/035-第35课.md:16
094  docs/chanlun/text/blog/035-第35课.md:64
095  docs/chanlun/text/blog/035-第35课.md:122
096  docs/chanlun/text/blog/036-第36课.md:30
097  docs/chanlun/text/blog/036-第36课.md:36
098  docs/chanlun/text/blog/037-第37课.md:42
099  docs/chanlun/text/blog/037-第37课.md:174
100  docs/chanlun/text/blog/041-第41课.md:317
101  docs/chanlun/text/blog/044-第44课.md:52
102  docs/chanlun/text/blog/044-第44课.md:56
103  docs/chanlun/text/blog/048-第48课.md:76
104  docs/chanlun/text/blog/053-第53课.md:58
105  docs/chanlun/text/blog/053-第53课.md:60
106  docs/chanlun/text/blog/068-第68课.md:130
107  docs/chanlun/text/blog/078-第78课.md:162
108  docs/chanlun/text/blog/079-第79课.md:40
109  docs/chanlun/text/blog/086-第86课.md:74
110  docs/chanlun/text/blog/087-第87课.md:110
111  docs/chanlun/text/blog/091-第91课.md:214
112  docs/chanlun/text/blog/091-第91课.md:284
113  docs/chanlun/text/blog/102-第102课.md:238
114  docs/chanlun/text/blog/105-第105课.md:448
115  docs/chanlun/text/chan99/0014-第二节 走势分解.md:79
116  docs/chanlun/text/chan99/0014-第二节 走势分解.md:87
117  docs/chanlun/text/chan99/0016-第四节 背驰与盘整背驰.md:25
118  docs/chanlun/text/chan99/0016-第四节 背驰与盘整背驰.md:27
119  docs/chanlun/text/chan99/0016-第四节 背驰与盘整背驰.md:72
120  docs/chanlun/text/chan99/0043-第二十二节 走势分析中必须杜绝一根筋思维.md:46
121  docs/chanlun/text/tiandao/ocr/INDEX.md:110
122  docs/persistence_theory.md:1239
```

### 分层结论

已在案的语义：三段合格 seed 使枢成立；当下可读趋势，同时后枢完成前同级外缘仍可能扩展。待裁的 **Q1 = B** 是在前缀上向下游发布哪一种主张。普通后缀 111→202 能改叶，且第 36 课已经区分观察和终局；以 CC-019 的实质 R5 冻结成员取正式首证，保持 CC-020 记录当切关系、CC-025 保持实例生命周期、C08 只撤回失效主张。反向破坏例保留，即已确认也不可顺手宣布实际走势完成。不存在「原文不承认开放时形成」的前提。

## 可复核的代码、合同及依赖锚

- `git show 271f3fbe:rust/tests/fixtures/trend_formation_1426.json`，`git show 271f3fbe:rust/tests/trend_formation_1426.rs`。夹具的 `prefix_before_separation/strict_separation/b_settled=110/111/123`；现有断言 123 记录 `break_unit=8`、端点 97→109。旧报告 [#1424 双向输入](https://github.com/Newchanlun/NewChanlun/issues/1424#issuecomment-7023030025) 明示读数是解析／关系内核；[同输入的正式 S](https://github.com/Newchanlun/NewChanlun/issues/1424#issuecomment-7025367845) 止于 cut-71。123 的 R5 角色与 202 的翻叶手证见草稿表，122→123 的正式首证是下游验收断言；本轮不把旧测试当作新证据已经执行。
- `git show 271f3fbe:rust/src/theta_v0/classifier/trend_formation.rs`：:45 枚举，:100 扫描位，:136 状态分支，:164 已形成凭证，:258 共用扫描，:318–320 两个 `is_settled()`。`center_scan.rs:459–484` 逐窗相邻、待升级域，不能自行改叶。
- Origin 枚举命中中，`CenterStates.lean:215–238` 仅静态趋势几何，`CenterConstruct.lean:408–450` 为 reference 单窗，`ScanAssemblyMirror.lean:352–381` 是取离开和回试角色，`TrendCompleteClassification.lean:66–80` 限已完成分类，`BspClassification.lean:92–97,362–366` 验结构背驰条件。未发现这些定义中有逐 bar 双 R5 的类型首证。没有拿 Lean 的单窗作替代或声称有已落具名证明。
- 冻结 SPEC：`git show efc1ddc4d6c015f4f8c6d44f904d704a88308b46:.chanlun/review-results/issue1339-r2-spec-20260909/payload/spec/inputs/SPEC-COVERAGE-INPUT.json`。读 `/classification_axes/18,19,22,23,24,61` 的 domain、branches、legal_transitions 与适用域；再查 #1340 C02 与 C08 正文、AT-04。CC-019 失败首抽不得拿晚抽替代；CC-020 五叶及值域；CC-023 仅已完成三分类；CC-024 技术方向不替语义方向；CC-025 合法前缀单调；CC-062 只管已完成相邻实例、同向不伪造继任。ADR 0051 §三、ADR 0038 §三与 `CONTEXT.md:247–256,482–483` 分开来源、身份和历史。
- 每个用到的票以 `gh issue view <票号> -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` 重读相应正文与评论；本票暂停、退回和分级已核。独审原件分别 `06e6e28e337fdbf0acc2ade98ba927489518940c` 与 `4c4b472039132fec54758f54bd24a0c3443cd92a`；只用以识别原错误、不是代替原文。
- 依赖方向按 `gh api repos/Newchanlun/NewChanlun/issues/<票号>/dependencies/<blocking|blocked_by> --paginate` 核回。新增拟边 #2114→#1496、#1496→#1426：#2114 当前无前置、唯一后继 #1426；#1496 当前前置仅 #1419、后继仅 #1443，#1426 不是 #1496 的上游。按下表与验收汇点复核，新增不构成环。本稿不写票或边。

| 票 | 前置 | 后继 |
|---|---|---|
| #2114 | — | #1426 |
| #1419 | #1414、#1359、#1565、#1488、#1640 | #1424、#1426、#1443、#1486、#1496、#1497、#1570、#1393 |
| #1424 | #1419、#1359、#1488 | #1426、#1443 |
| #1426 | #1419、#1424、#1359、#2114 | #1429、#1443 |
| #1429 | #1426、#1359 | #1431、#1432、#1434、#1443 |
| #1431 | #1429、#1359 | #1438、#1443 |
| #1432 | #1429、#1359 | #1433、#1443 |
| #1433 | #1432、#1359 | #1434、#1435、#1437、#1443 |
| #1434 | #1429、#1433、#1359 | #1435、#1437、#1443 |
| #1435 | #1433、#1434、#1359 | #1436、#1443 |
| #1436 | #1435、#1359 | #1437、#1443 |
| #1437 | #1433、#1434、#1436、#1359 | #1438、#1443、#1552 |
| #1496 | #1419 | #1443 |
| #1509 | — | — |
| #2072 | — | — |
