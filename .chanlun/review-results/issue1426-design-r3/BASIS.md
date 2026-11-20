# 选型依据

设计一（D1）：单一公开入口 judge_trend_formation(unit_level, units)，level 到 build 的分派私有，证据类型字段全私有并拥有内容。嫁接三处：D2 的私有字段凭据类型 FormedTrend、cfg 编译负例和公开面源码锁；D3 的删除清单、状态对照表锁、「公开函数只收单元来源」规则。改掉 D1 两处：去掉 formed_trends() 同向分组（两位评审都指出它是第二份分组规则，R2-1 和 R2-6 也都出在聚合上），consolidation() 明确为「全链恰一个窗口且未被标升级」。所用原则与它改变的选择：Attack the Premise（两轮共用前提「收证据再校验」经读码证伪，所以删掉全部收证据的入口，不再收紧校验）；Type System Discipline（状态、方向、结算都不存储，只从叶和来源现算，非法组合无处可写）；Laziness Protocol（不做分组、不加来源副本、不加域检查）；Build the Lever（仓外 Python 扫描模型加两处植入缺陷对照，用来核期望值与单调性）。

来源：#1323 主控本机设计工作流 design-1426-trend-formation（三套独立设计、两名评审、一次综合），基于 PR #1855 head 9e57032bcd08399b0a90189402be07200d95a857 与第二轮候选 5e66d04ff65609c03f7706a22cfab7a5c2d70c27 只读得出；测试期望值只在仓外扫描模型上核过，Rust 未跑。
