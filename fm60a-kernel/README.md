# FM-60a 原典作者陈述库（#2324，R3 交付口径）

本目录交付 #2324 的 61 条四分类映射与 **9 条重点示范判例的纯作者陈述库（`fm60a-author-statements-v1`）**——每条仅记录作者在原文中说过的具体命题、说话场景与时间锚点、保守语气、条件与外层限定、对象指代（「原文未指明」诚实留白）、陈述间依存关系与说话人确认依据，**不含任何整理者建模、合成数字或预期结果**。

引文括号约定：`【归属 课号:行号】「…」` 为缠师逐字；`『…』` 为网友或编者；`〈…〉` 为概括。

## 正式交付物

| 文件 | 用途 |
|---|---|
| `classification.jsonl` | 61 条判例四分类映射（与 `fm60a-inventory/cases.jsonl` 严格双射，`3 / 27 / 26 / 5`） |
| `kernel-cases.jsonl` | **9 条示范判例的纯作者陈述库**（`011, 012, 020, 021, 026, 027, 028, 031, 043`，共 63 条陈述） |
| `check.py` | 纯标准库机械核对脚本（`python3 -I`，只核对作者陈述库结构与隔离对齐） |
| `SCHEMA.md` | `fm60a-author-statements-v1` 格式契约、下游使用指引与机检/人审边界 |
| `JUDGMENT.md` | 是否需要当年 K 线、四分类划界单位与交付口径说明 |
| `LIMITATIONS.md` | 机检证明不了的五类人审项、63 条陈述盲对读自查记录（12 处出入修正）与 33 项「原文未指明」汇总 |
| `REVISION-R1.md` / `REVISION-R2.md` | R1（`ab339d74`）与 R2（`799d96f9`）两轮忠实性独审逐项返修对照表 |

## 隔离文件（非交付物，未过审，不得直接导入）

| 文件 | 说明 |
|---|---|
| `draft-models-unreviewed.jsonl` + `DRAFT-MODELS-WARNING.md` | R2 移出的 9 条整理者建模与合成实例草稿（原样移出、未过审，供定义作者自行核对前提参考） |
| `drafts/non_normative_probe.py` | 原 `demo_harness/` 建模层演示脚本（随建模层原样移至草稿侧） |
| `legacy-v1-unreviewed.jsonl` + `LEGACY-V1-WARNING.md` | R1 移出的其余 20 条旧格式 `fm60a-kernel-v1` 记录（未经忠实性审查，不得使用） |

## 复核命令

在仓库内任意目录运行（需已执行 `git fetch origin infra/2317-admit-table`）：

```bash
python3 -I fm60a-kernel/check.py
```
