# #2114 考古（第 2 轮）

原件基线：`b9d898dccf46c2a716115eaa1215bc39c458a959`；只读实施参照：`5e66d04ff65609c03f7706a22cfab7a5c2d70c27`。复搜在 R1 `7b3a2e6523fc3d727aa4964be1c9f947cab3adab` 上执行，基线除 qushi 外未变。复用 R1 两路证据，按异家族 [REVIEW.md](https://github.com/Newchanlun/NewChanlun/blob/06e6e28e337fdbf0acc2ade98ba927489518940c/.chanlun/review-results/issue2114-review-7b3a2e65/REVIEW.md) 的 R8 反馈追加查义、查段角色与趋势语境。T，`user_gate=[]`；A 已裁 4，B 有先例未正式裁 3，C 确未设计 0。Q1 由 B 订正为 A；Q2 的工程钟仍为 B。

tracker 命中数为返回票数（直读数为正文与评论数）；仓内为匹配行数。新增查询及实质命中如下。开放事实、当前候选分支和报告只用作例证，不把实现当教义。

## Q1 · A · 已成立的后中枢 B 开放、当下严格外缘分离，能否发布趋势已形成？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个中枢" OR "构成趋势" OR "开放期" in:title,body,comments' --json number,title,state,url` | 7 |
| tracker | "第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"第二个同级别中枢" OR "形成两个依次同向" OR "中枢的新生" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | 第二个(同级别)?(走势)?中枢\|构成趋势\|开放期\|未结算.{0,20}(趋势\|形成) | `rg -n --max-columns 450 --max-columns-preview '第二个(同级别)?(走势)?中枢\|构成趋势\|开放期\|未结算.{0,20}(趋势\|形成)' analysis/ docs/ .chanlun/` | 122 |
| repo | 第二个同级别中枢\|形成两个依次同向\|中枢的新生\|第二个中枢 | `rg -n --max-columns 450 --max-columns-preview '第二个同级别中枢\|形成两个依次同向\|中枢的新生\|第二个中枢' analysis/ docs/ .chanlun/` | 94 |
| tracker | #2114 正文与评论 | `gh issue view 2114 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 1 |
| tracker | #1426 正文与评论 | `gh issue view 1426 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 13 |
| tracker | #815 正文与评论 | `gh issue view 815 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 11 |
| tracker | "中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | 中枢完成前\|一个中枢的完成\|第二个中枢的前三段 | `rg -n --max-columns 480 --max-columns-preview '中枢完成前\|一个中枢的完成\|第二个中枢的前三段' analysis/ docs/ .chanlun/` | 11 |

tracker-completion.json：#2114 OPEN。

- docs/chanlun/text/blog/020-第20课.md:32,52,58：界 :94 前缠师正文；:32 行首为「二、」列项，无行内注。原文明确后枢完成前的波动仍能触及前枢或其延伸波动而扩展；:52 则明确采全部合法 Zn。
- docs/chanlun/text/blog/041-第41课.md:313–319：界 :36 后；:313「缠中说禅」与 :315「2007-04-02 22:16:22」是回复头；:317 读者九头鸟引 020:32 并问是否仅取后枢前三段，末尾 == 分隔；:319 无注，明确答「概念有问题，一个中枢的完成，是和第三类买卖点相关的。如果一个中枢延伸，就证明没完成。」
- https://www.fengmr.com/cld41ka.html（041 正本 :3 的转录来源）：用 curl -fsSL https://www.fengmr.com/cld41ka.html 核作者归属：HTML 先有缠中说禅/时刻段，再是读者问、==，最后独立加粗答段。引文及行号仍只取仓内 blog 正本。
- docs/chanlun/text/blog/023-第23课.md:340,344–352；107-第107课.md:26,30,32：023:340 是读者句；缠师在 :346–348 讨论不同级别及回抽。107:32 的「上升趋势形成」是操作语境，:26、:30 说信号出现后仍等待第二/其余中枢，不能替同级两枢类型确认。
- docs/chanlun/text/blog/018-第18课.md:42,44；qushi.md:124–144,224（取证基线）：前提是依次同向；允许形成后继续延伸，不规定后枢成员尚变时的正式发布。
- docs/chanlun/text/blog/019-第19课.md:524；023-第23课.md:188：前者是次级三走势未完的上涨延续个例，后者明分扩展与新生；不能以第二枢存在代替同向证明。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512：R1 给出开放 B 的同前缀追加反证；R2 将形态观察与趋势形成拆开但仍待 #2114 正式裁定。
- https://github.com/Newchanlun/NewChanlun/issues/815#issuecomment-5173454002：CLOSED：M-2 外缘判据已裁，未裁外缘何时封口。

**出处**：docs/chanlun/text/blog/020-第20课.md:32,52,58；docs/chanlun/text/blog/041-第41课.md:313–319；#815 M-2。
**推导**：:32 明示完成前触及改变类型；:317 正问前三段是否足够，:319 以三类点界定完成而非种子。Z-6 的中枢是否存在与外缘封口是两问；采用 [旧缠论]：后枢尚未完成不作正式趋势判定。111→202 验证可翻，不是定性第一依据；CC-025 的单调也不是否决候选 1 的依据。

## Q2 · B · 把后枢须完成的已裁语义映射到哪个可知切面；怎样区分离开、结算、类型确认和走势完成？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"趋势形成" OR "形成时点" OR "走势必完美" OR "形成/完成" in:title,body,comments' --json number,title,state,url` | 13 |
| tracker | "首回试" "形成" OR "B 结算" OR "后中枢" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"首回试" "形成" OR "B 结算" OR "后中枢" in:title,body,comments' --json number,title,state,url` | 30 |
| repo | 走势必完美\|形(成\|态).{0,18}(确认\|完成)\|完成.{0,12}(时点\|时刻) | `rg -n --max-columns 450 --max-columns-preview '走势必完美\|形(成\|态).{0,18}(确认\|完成)\|完成.{0,12}(时点\|时刻)' analysis/ docs/ .chanlun/` | 576 |
| repo | 后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成 | `rg -n --max-columns 450 --max-columns-preview '后中枢.{0,16}(结算\|确认)\|停在核心之外的那段回抽\|破坏未证\|首回试.{0,10}完成' analysis/ docs/ .chanlun/` | 19 |
| tracker | #1424 正文与评论 | `gh issue view 1424 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 7 |
| tracker | #1478 正文与评论 | `gh issue view 1478 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 3 |
| tracker | #1340 正文与评论 | `gh issue view 1340 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 10 |
| tracker | "中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"中枢的完成" OR "中枢完成前" OR "第二个中枢的前三段" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | 中枢完成前\|一个中枢的完成\|第二个中枢的前三段 | `rg -n --max-columns 480 --max-columns-preview '中枢完成前\|一个中枢的完成\|第二个中枢的前三段' analysis/ docs/ .chanlun/` | 11 |
| repo | isTrend\|IsUpTrend\|IsDownTrend\|CompletedTrend\|TrendFormed\|ProvisionalSeparation\|firstRetest\|thirdClassSide\|known_at\|first_known | `rg -n --max-columns 480 --max-columns-preview 'isTrend\|IsUpTrend\|IsDownTrend\|CompletedTrend\|TrendFormed\|ProvisionalSeparation\|firstRetest\|thirdClassSide\|known_at\|first_known' formal/Origin/` | 95 |

tracker-completion.json：#2114 OPEN。

- docs/chanlun/text/blog/020-第20课.md:32,52,58：界 :94 前缠师正文；:32 行首为「二、」列项，无行内注。原文明确后枢完成前的波动仍能触及前枢或其延伸波动而扩展；:52 则明确采全部合法 Zn。
- docs/chanlun/text/blog/041-第41课.md:313–319：界 :36 后；:313「缠中说禅」与 :315「2007-04-02 22:16:22」是回复头；:317 读者九头鸟引 020:32 并问是否仅取后枢前三段，末尾 == 分隔；:319 无注，明确答「概念有问题，一个中枢的完成，是和第三类买卖点相关的。如果一个中枢延伸，就证明没完成。」
- docs/chanlun/text/blog/037-第37课.md:16–20：先假定趋势，再给趋势背驰的 c 前件。不能把同向三类点作形成判据。
- .chanlun/definitions/qushi.md:61,224；docs/chanlun/text/blog/018-第18课.md:42,44：两个依次同向中枢具结束条件，但可能继续，原句未给在线时钟。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7023365989：123 根老窗口改为双枢 settled；留独立走势完成义务。
- https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：CLOSED：末外回抽可为连接/突破段；代码的 break_unit 不是段角色。
- 冻结 #1340 附件 CC-019 :10031–10037、CC-025 :11001–11036：正式结算见证来自完成的首回试；走势可独立处在 FORMED_OPEN。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7025393576：正式 S 实跑止于 cut-71，不能把 123 fixture 当成发布回执。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7023365989；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661；CC-019/025；docs/chanlun/text/blog/020-第20课.md:32,52,58；docs/chanlun/text/blog/041-第41课.md:313–319。
**推导**：语义上必须待后枢完成已是 A（Q1/3），首证 K 线、同切面绑定与实际发布仍属 B；#1478 仅给端点角色。真实离开与首回抽已完成、外缘封口且仍分离时即发类型确认，不等走势完结。原续流 u7/u8 同源验证这一切面。
**默认候选**：取两枢结算、实际相邻连接和严格分离全部首次可知的原始收盘；发布绑定实际 S cut。
**冲突**：稍早的候选代码不携源切面证书；其 123 正例可用几何重核，不能由代码布尔推出正式语义。

## Q3 · A · 已裁 R5 的段角色、反向结算与同向 T3-in-c 各管什么？

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
| tracker | "T3-in-c" OR "trend_third_class_in_c" OR "c至少包含对B" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"T3-in-c" OR "trend_third_class_in_c" OR "c至少包含对B" in:title,body,comments' --json number,title,state,url` | 27 |
| tracker | "首个不重叠" OR "第一段离开" OR "停在核心之外的那段回抽" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"首个不重叠" OR "第一段离开" OR "停在核心之外的那段回抽" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | c[[:space:]]*至少包含对[[:space:]]*B\|T3-in-c\|trend_third_class_in_c | `rg -n --max-columns 480 --max-columns-preview 'c[[:space:]]*至少包含对[[:space:]]*B\|T3-in-c\|trend_third_class_in_c' analysis/ docs/ .chanlun/` | 80 |
| repo | 第5段构成第三类\|先挂起看下一段\|停在核心之外的那段回抽 | `rg -n --max-columns 480 --max-columns-preview '第5段构成第三类\|先挂起看下一段\|停在核心之外的那段回抽' analysis/ docs/ .chanlun/` | 4 |
| repo | isTrend\|IsUpTrend\|IsDownTrend\|CompletedTrend\|TrendFormed\|ProvisionalSeparation\|firstRetest\|thirdClassSide\|known_at\|first_known | `rg -n --max-columns 480 --max-columns-preview 'isTrend\|IsUpTrend\|IsDownTrend\|CompletedTrend\|TrendFormed\|ProvisionalSeparation\|firstRetest\|thirdClassSide\|known_at\|first_known' formal/Origin/` | 95 |
| tracker | #1229 正文与评论 | `gh issue view 1229 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 2 |
| tracker | #1300 正文与评论 | `gh issue view 1300 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 2 |
| tracker | #1496 正文与评论 | `gh issue view 1496 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 1 |

tracker-t3.json：#1229 CLOSED、#1260 CLOSED、#1249 CLOSED、#586 CLOSED、#1275 CLOSED、#584 CLOSED、#1278 CLOSED、#487 CLOSED、#1300 CLOSED、#1291 CLOSED、#1299 CLOSED、#606 CLOSED、#993 CLOSED、#607 CLOSED、#582 CLOSED、#589 CLOSED、#1226 CLOSED、#903 CLOSED、#883 CLOSED、#812 CLOSED、#1232 CLOSED、#565 CLOSED、#608 CLOSED、#913 CLOSED、#848 CLOSED、#846 CLOSED、#817 CLOSED。 tracker-role.json：#1478 CLOSED。 #1229 CLOSED：正文及 1 条评论。 #1300 CLOSED：正文及 1 条评论。 #1496 OPEN：正文及 0 条评论。

- https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5148740332：CLOSED：S-3 定案为离开+不回，单段是残缺实现。例中 j 被当作离开；旧表未区分 j 已是回抽的情形。
- .chanlun/definitions/zhongshu.md:238–252,324–360,536：同一正本并列 R5 与 #1478 末外回抽角色；不回才破坏，回则延伸、有效 Zn 进外缘。
- https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661：CLOSED：仅裁端点归属，停在核心之外的回抽为突破/连接段，前枢末成员为其前 Zn。原评论没有「不等到回抽之后第三单元」；下列回抽即结算是 018:64、020:60、061:44 加已裁端点角色的推导。
- https://github.com/Newchanlun/NewChanlun/issues/1496：OPEN，0 评论；正式两段式实现归此票。
- https://github.com/Newchanlun/NewChanlun/issues/485：CLOSED；anchor/高级三类点链修复；未完成共用中枢扫描的 R5。
- docs/chanlun/text/blog/018-第18课.md:64；020-第20课.md:60；061-第61课.md:44：三处均是正文（界 :68、:94、:56 前），作者缠中说禅，无行首或行内注；061:44 明确第四段离开第五段成三类。已完成回抽若已是不重叠突破，本切面证齐；只有离开时才等真正回抽。
- .chanlun/definitions/zhongshu.md:250–252,342–350,536：基线 §4.1 按角色认末端回抽，§5.2/R5 未分角色即写下一段；#1496 同拍订正文和 Lean。上级成员集差异的退场与 #1405/#1490 后另裁边界不变。
- docs/chanlun/text/blog/037-第37课.md:16–20；zhongshu.md:366,378；beichi.md:110,118：37课 :40 前正文，行首/行内无注。先假定趋势后约束 c；在案正本把同向 T3 落为趋势背驰和标准第一类点前件。
- https://github.com/Newchanlun/NewChanlun/issues/1229#issuecomment-5417718452：CLOSED，统一为 trend_third_class_in_c 全窗后扫，不用固定首对代替同向 c 的见证。
- https://github.com/Newchanlun/NewChanlun/issues/1300#issuecomment-5463525851；formal/Origin/BspClassification.lean:92–97,362–366：CLOSED，IsType1 显式 isTrend 合取，witness_type1_needs_trend 为反例。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/812#issuecomment-5148740332；zhongshu.md:248–252,324–360,536；https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661；020:60、061:44；https://github.com/Newchanlun/NewChanlun/issues/1229#issuecomment-5417718452；https://github.com/Newchanlun/NewChanlun/issues/1300#issuecomment-5463525851。
**推导**：018:64/020:60 和冻结 CC-019 的 R5 有上下两支；041:319 不限破坏方向。020:58 以两枢外缘独立定方向，不含第三类点的符号。037:16 的先假定趋势证明 T3-in-c 是后续语境门而非构成门。因此 B 反向 R5 且相邻证明和严格外缘仍有效时照常确认该几何方向，既不报同向 T3-in-c，也不因此发一类点。ADR 0041 不提供另一个合法参数值。

## Q4 · B · 确认前的关系如何对外命名，哪些消费者可以使用？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "ProvisionalSeparation" OR "当前切面" "趋势" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"ProvisionalSeparation" OR "当前切面" "趋势" in:title,body,comments' --json number,title,state,url` | 1 |
| tracker | "开放期严格分离" OR "临时的向上扩展" OR "发展中" "未完成尾部" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"开放期严格分离" OR "临时的向上扩展" OR "发展中" "未完成尾部" in:title,body,comments' --json number,title,state,url` | 1 |
| repo | ProvisionalSeparation\|暂态\|当下.{0,10}(判断\|确认)\|候选.{0,12}准入 | `rg -n --max-columns 450 --max-columns-preview 'ProvisionalSeparation\|暂态\|当下.{0,10}(判断\|确认)\|候选.{0,12}准入' analysis/ docs/ .chanlun/` | 150 |
| tracker | #1426 正文与评论 | `gh issue view 1426 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 13 |
| tracker | #1429 正文与评论 | `gh issue view 1429 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 5 |
| tracker | #1437 正文与评论 | `gh issue view 1437 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 2 |



- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512：现有独立 ProvisionalSeparation 是暂行合同，无正式趋势权。
- https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7001165057：cut-106 的临时扩展标有 NOT_ASSERTED_DEFERRED_1426；观察与完成对象分开。
- docs/agents/doctrine-rules.md:49–55；CONTEXT.md:218–220,251–256：不同命题可分层；观察不可参与正式准入。避免借用已定义的背驰活假设或候选中枢名。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6990012358；https://github.com/Newchanlun/NewChanlun/issues/1437：上级要可证结构和血缘，买卖标签另需确认及可知时点。
- 冻结 SPEC #1340 CC-020/023/024/025/062：关系叶、完成分类、方向和实例时序各有不同主体；CC-025 合法追加不回退，110 单枢形成在 111 保持。CC-023 允许形成的盘整发展成趋势或高级结构；不以此发布完成三分类。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7041670512；https://github.com/Newchanlun/NewChanlun/issues/1426#issuecomment-7001165057；CC-020/025；CC-023/024/062。
**推导**：同一实例已由 A 成立；B 暂缺 R5 只是类型确认的依据未齐，不能抹走已形成实例。区别 CC-020 观察方向、CC-024 语义方向，以及 CC-025 实例形成和完成时钟。
**默认候选**：ProvisionalSeparation 沿用；单枢已形成时 CC-025 保持 FORMED_OPEN，仅趋势类型、语义方向、趋势确认钟为空。接入共同 R5 前第 123 根也不得凭扫描位发正式类型。

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



- https://github.com/Newchanlun/NewChanlun/issues/1340 C08.2/.5/.6、AT-04：快照和变化同切面；实际 AsKnown 与后修重算分证。CC-025 要同时显示 known_at 和发生位置。
- docs/adr/0051-per-bar-domain-event-identity-lifecycle-contract.md:273–282,312；docs/adr/0038-dual-run-determinism-recovery-seek-asknown.md:60–76：撤回只追加；不能回填晚到结果，首达时刻不透支未来。
- https://github.com/Newchanlun/NewChanlun/issues/1534（CLOSED）；https://github.com/Newchanlun/NewChanlun/issues/1621（CLOSED）：前者确立生命周期，后者是分辨可审计时间和跨域顺序的实施先例，不以经济域时钟线偷换 S 原始切面。
- impl/1426-trend-formation @ 5e66d04ff65609c03f7706a22cfab7a5c2d70c27，s_session/browser/q3-center.js:413–417,540–563：CC-020 同对变叶与对象撤回是独立变化；同对修订保留 formed_known_at。Python/JS/生产结构只作现状证据。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6152239745：第九个成员进入待升级时保留原中枢身份，外缘暂缺，写修订而非撤回。
- https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-6990012358：待升级相邻对实物仍有旧端点与连接，leaf/direction 为空；这是构造器实物，不是正式发布回执。

**出处**：https://github.com/Newchanlun/NewChanlun/issues/1340 C08；ADR 0051 §三；CC-025。
**推导**：先看命题与身份：相邻对仍存在而其观察叶改变，是事实的新修订；已确认趋势假据被推翻时旧主张失效，必须撤回。首证不变则保留原锚；实际提交代不能伪装成更早提交。 第九段只待升级时同身份待定不等同失效；只有新归属证成该关系不再成立才撤回。早期数据更正仅重算出更早锚时，不改原有效 AsKnown 和实际获知。
**默认候选**：形成时钟取合取第一次可知的原始收盘切面，S 发布另按实际提交记录；有效同身份更新走修订，失效走追加撤回及适用替代，旧 AsKnown 不动。 较早后修锚单列；同身份待升级为 pending_upgrade，实际失效则撤回。

## Q6 · A · 上下行与不同自然级别用同一形成判据吗？

| 路径 | 查询词 | 命令 | 命中 |
|---|---|---|---:|
| tracker | "总缝规则" OR "同输入同输出" in:title,body,comments | `gh issue list -R Newchanlun/NewChanlun --state all --limit 30 --search '"总缝规则" OR "同输入同输出" in:title,body,comments' --json number,title,state,url` | 30 |
| repo | 总缝规则\|同输入同输出\|同一个判定.{0,6}每一级 | `rg -n --max-columns 450 --max-columns-preview '总缝规则\|同输入同输出\|同一个判定.{0,6}每一级' analysis/ docs/ .chanlun/` | 90 |
| tracker | #804 正文与评论 | `gh issue view 804 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 4 |
| tracker | #1531 正文与评论 | `gh issue view 1531 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 10 |
| tracker | #1429 正文与评论 | `gh issue view 1429 -R Newchanlun/NewChanlun --json number,title,state,body,url,comments,labels` | 5 |



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
- #1426 原生阻 #1429/#1443；#1429 原生阻 #1431/#1432/#1434/#1443；#1437 原生前置 #1433/#1434/#1436/#1359（closed）；#1443 的原生前置含 #1426/#1429/#1437/#1496。无需加重复直边。R1 仅发 #2114 分级评论；R2 未写票或边。

## 复搜核对：合同、角色与移动边界

- 冻结 JSON 的 CC-019 :9990 起、CC-020 :10159 起、CC-023 :10661 起、CC-024 :10822 起、CC-025 :10979 起、CC-062 :17200 起逐条读过。CC-019 完成首回试的 UP.GT / DOWN.LT 才破坏（含 EQ 不成立）；CC-020 是五叶，不自动提升；CC-023 仅分良构完成域，允许形成的盘整后续发展；CC-024 技术方向另列；CC-025 是实例且合法追加不回退；CC-062 以读法、实际完成、不同身份为前件。
- Origin 不作任意全库无定义的断言：枚举命中后逐段读了 `CenterStates.lean:215–238`（价格谓词）、`CenterConstruct.lean:408–450`（旧窗扫描状态）、`ScanAssemblyMirror.lean:352–381`（回抽阶段）、`BspClassification.lean:92–97,362–366`（一类点语境）、`TrendCompleteClassification.lean:66–80`（完成三分）；命中 `CompletedTrend` 的镜面结构在 `ScanAssemblyMirror.lean:196–219`，不是开放期首证。所检入口没有把开放外缘升正式趋势的规则。术语与代码引用按 R1 固定实施参照并列记录。
- 托管第 123 根证据的是 #1496 的共同 R5：端点相连的已完成段中，首个全区间不交从外部起步，前段因相交而从核心越到同一外端，现段反向而不回。若端点不相连，首个不交本身可能只是离开，此时等已完成的实际首回抽。此推导不是 #1478 原话，且不提前决定上层成员集争议。
- 反向例：上涨首对 A.GG=5500、B.DD=5600、B 核心 [5700,6300]；B 下离至 5550 后回抽最高 5650 < 5700，仍可保持外缘严格分离。同对类型为上涨、B 实际下破；下跌镜像。不是已有实跑回执，实施须锁两向合成判别例。
- 混合链的实例归属仍由 #1429/#1431；#1509 消费非空 raw 见证，#1432/#1433 消费力度/一类点语境，#2072 消费 Q3 合同。R2 未改票、未改边。

机械核对：七点均有两路、开闭 tracker 与出处；三个 B 均有推导与默认候选，无 research/probe。
