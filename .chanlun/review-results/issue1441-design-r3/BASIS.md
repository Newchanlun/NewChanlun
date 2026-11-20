# 选型依据

底稿取设计一（求值器只收名字，三种封口值无公开构造器，Rust 常量登记表按 sha256 取原件，窗内计数由样本时间戳推导）。嫁接：设计三的 evaluate(level) 无证据参数、同一分层多份 run 都不用、零合计（含代理零）收在一个函数、只用公开面的集成测试；设计二的「行类别须等于槽位类别」、测试登记一律 ResearchOverride、consumed 列表、沿用 check-compile-negatives-1394.sh。按评审补的洞：波幅下界方法未裁，非测试构建不认任何 method_id，恒得 InsufficientEvidence（设计一、二在核内自选均值，设计三信原件申报的下界，三者都不取）；政策记录不复用 parse_header（我开码核实它要 fields 外壳，signed_value 私有），改手写点分路径读取器；不引入 Cut 与 NoPolicyInEffect，不往已签 v1 记录补摘要，不自定生产成本读数 schema。用到的原则：Attack the Premise（把前两轮共用的前提写出来，用反例的入口分布检验它，结论是删通道而不是再加校验）；Type System Discipline（外部字节只在登记表这一道边界解析成类型，合格波幅、非零合计、已签政策在类型上不可由调用方构造）。本设计未运行 cargo，结论全部来自读码与 git show；证据门与费率簿的 sha256 是实算。

来源：#1323 主控本机设计工作流 design-1441-cost-stop（三套独立设计、两名评审、一次综合），基于 origin/impl/1441-cost-stop-policy @ 5a4033fd9083aafaea580ef56c050c1e21ef29df 与 origin/main b9d898dccf 只读得出；未运行 cargo。
