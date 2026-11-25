# #2317 身份检查：第六轮非作者独立复审

被审提交：`cec8455099b59dc124303c48f77118f64ef93b17`（已核对远端 `infra/2317-admit-table`）。模型与档位：`gpt-6.2-astra / xhigh`。

**第五轮的唯一阻断已闭合。** 按 [#2317 验收条款](https://github.com/Newchanlun/NewChanlun/issues/2317)，未发现材料变更误绿，亦未发现合法环境下未变材料误红。本轮仍有一项文档阻断：README 第 31 行把唯一的**准入依据**写成了引文核对工具的**唯一输入**。

## 第 14 行：修订与行为相符

从[第五轮报告](https://github.com/Newchanlun/NewChanlun/blob/631f9b42db3bd460aa9edb6b880ec442633d48b6/audit-reports/2317/FM-09b-identity-review-r5.md)所审的 `9e2135af6a1560c0758d611c7cd3d5f6e655b1a8` 到本提交，全树 `git diff --raw --no-abbrev` 只有 `formal_math/verification/gate11/README.md` 一项；逐行差异只有第 14 行中关于标准错误的一句。`check_admit_identity.py`、`admit_identity.pin`、`selftest_identity.py` 的 blob 和模式均未变。

新句区分了两个写入者。[检查器第 100–105 行](../../formal_math/verification/gate11/check_admit_identity.py#L100-L105)忽略自身写诊断时的 `OSError`；参数无效仍退 2，已判材料不符仍退 1。Git 则继承标准错误，第 23–25 行要求子进程成功，第 153–158 行把子进程失败转为 2。第五轮在同一提交、同一版本名上测得：Git 警告可写时检查器退 0；警告遇断管时 Git 因 SIGPIPE 终止，检查器退 2；换成无歧义的完整提交号，同一断管仍退 0。新句与该对照一致。ASCII 环境 24 项自测及五种单项弱化的检出结果沿用第五轮证据，未重跑。

## R6-1 · 第 31 行把准入依据与运行输入混为一谈

**第 3 类阻断：受审文字与实际行为不符。** [README 第 31 行](../../formal_math/verification/gate11/README.md#L31)说「引文核对工具的输入只有一份」，并指向 `candidate/tier1_candidate.jsonl`。即便待核文本与这份准入表都在，工具仍须另读博文语料。[第 165–171 行](../../formal_math/verification/gate11/report_citations.py#L165-L171)分别检查表、语料和扫描目录；[第 218 行](../../formal_math/verification/gate11/report_citations.py#L218)从语料取所引原行。语料不是准入表的别名。

实测：在独立临时目录中，将 `sans-blog/formal_math` 指向本提交完整的 `formal_math/`，不提供 `docs/chanlun/text/blog/`。从被审工作树执行：

```sh
python3 -IB formal_math/verification/gate11/report_citations.py --root ../sans-blog
```

进程退 **2**，诊断点名缺少 `sans-blog/docs/chanlun/text/blog`。第五轮确认的是准入表的用途；本例核实的是工具实际需要哪些输入。只需把该句改为「引文核对只以这份表判定正文准入；核对字面时另读博文原文和待核文本」。不需要改脚本或扩大工具的过审范围。

**整体裁决：阻断 1 项，非阻断建议 0 项。** 已复读 README 开头至「两个脚本」之前（第 1–34 行），其余可检验陈述未发现与实际不符。合并前五轮证据，本提交的检查器、钉选与自测未发现身份判定阻断；连同 README 受审一节的四文件整体仍为 BLOCK，仅因 R6-1。此结论不裁定旧辅助工具的引文读数，也不涉及总门禁接线。

VERDICT: BLOCK
