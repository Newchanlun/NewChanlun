# FM-60a 内核判例数字化（#2324）

本目录交付对 #2324「FM-60a 原典判例数字化」的重新定向与内核数字化产物：将 61 条原典判例按「是否依赖当年 K 线」做四分划，并将其中 **29 条**不依赖 2007—2008 年历史行情即可检验缠论纯数学定义（`ChanTest` / FM-60b）的判例全部数字化为可机检的机读材料。

引文括号约定：`【归属 课号:行号】「…」` 为缠师逐字；`『…』` 为网友或编者；`〈…〉` 为概括。

## 目录内容

| 文件 | 用途 |
|---|---|
| `JUDGMENT.md` | 交付一：简短判断（是否需要当年 K 线、对原问题描述的修正、61 条四分类读数与代表例） |
| `SCHEMA.md` | 交付二（格式）：机读格式说明，面向 FM-60b（Lean 4 `ChanTest`）作者 |
| `classification.jsonl` | 61 条判例的完整四分类映射（与 `fm60a-inventory/cases.jsonl` 逐一双射） |
| `kernel-cases.jsonl` | 交付二（数据）：29 条内核判例（A 类 3 条 + C 类 26 条，含 5 组 9 条重点示范判例） |
| `check.py` | 交付三：纯标准库机械核对脚本（`python3 -I`，零机器绝对路径） |
| `LIMITATIONS.md` | 交付四：如实局限与解释性选择台账（供非作者独审逐条复核） |
| `demo_harness/non_normative_probe.py` | 可选参考探针（与数据分离，非缠论定义，仅证明 `kernel-cases.jsonl` 可脱离博文直接被程序消费） |

## 复核与演示命令

在仓库内任意目录运行（需已执行 `git fetch origin infra/2317-admit-table`）：

```bash
# 1. 机械核对全部 61 条分类 + 29 条内核判例（退出码 0 全过；1 有不符；2 环境问题）
python3 -I fm60a-kernel/check.py

# 2. 运行非规范演示探针（仅演示消费格式与公理分叉区分度，不构成定义）
python3 -I fm60a-kernel/demo_harness/non_normative_probe.py
```
