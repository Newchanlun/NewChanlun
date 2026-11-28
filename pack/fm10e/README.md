# FM-10e 盲写引文包（`#2322`：M16、M17、M18、M19a 与 M19b 模型类签名）

本分支 `pack/fm10e` 是 `#2322`（FM-10e 声明包丙）盲写双形式化阶段的**唯一授权输入**，按 `FM-MASTER-PLAN-v2.md` 第 1.5、3.4 节、`#2322` 评论 1 订正条款与 `#2316` 结项引文裁定构建，包含以下文件：

- `01-rulings.md`：`#2295` 七项顶层裁定、`#2316` 引文规则、`#2322` 评论 1 三处订正与防泄题边界、M19b 五条红线以及本包相关清单 B 修复处置
- `02-citations.md` 与 `citations.jsonl`：经 `#2317` 790 条正文区准入表（`origin/infra/2317-admit-table` @ `7d0082ff6f`）与 `docs/chanlun/text/blog/` 逐字核对的 73 条硬证据引文 + 8 条显式标明的二级旁证（已剥离行内编者注）
- `03-informal-specs.md`：M16a、M16b、M16c、M17、M18、M19a 与 M19b 模型类签名的非形式数学规范（零 Lean 签名；按 `#2322` 评论 1 不含任何对撞专用外部候选定义式）
- `04-interface-constraints.md`：13 个目标文件的路径、命名空间、公开定义名与职责、载体类型及 Lean `v4.36.0` 模块规范（零 Lean 签名）
- `verify_pack.py`：机检脚本，复核全部 Tier 1 引文的准入表归属与 `author_text_sha256`，并断言零 Lean 声明泄漏

## 盲写固定简报模板（手册 3.4）

```text
目标：为声明包 fm10e 写出 Lean 定义草稿，供对撞使用。本任务只写定义，不写定理证明。
输入：只读分支 pack/fm10e 在提交 <PACK_SHA> 上的引文包。不读其他分支，不读其他线程，不读 formal/ 与 .chanlun/definitions/。
产出：在分支 blind/fm10e-<甲方/乙方代号> 上提交接口约束页列出的 13 个文件（Chan/Proxy、Chan/Defs/Dynamics、Chan/Defs/Limits、Chan/Hypotheses、ChanDyn）。每个定义的文档串带引文包里的课行号与逐字引文。
验收：lake build --wfail 退出码 0。力度四参数与假设五项齐备且不设默认值。不出现禁用构造。
不要推送分支。完成后只回报 head SHA 与构建退出码。
固定约束：见引文包 04-interface-constraints.md 第三节（原样十四条）。
```
