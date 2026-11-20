# #2111 第 2 轮：R1 引用专修

首轮独审原件：[REVIEW.md](https://github.com/Newchanlun/NewChanlun/blob/59b6f401f94270db2c60cb4dca97b856c115fc14/.chanlun/review-results/issue2111-review-138e9377/REVIEW.md)。审查对象首轮裁定 `138e9377ae26e4f6a751348907ebc39e0a9e2551`；仅 R1 BLOCK，R2–R8 PASS。本轮不改四态归属、求值顺序、签署记录、测试要求或 blocking 边。

1. **溯源标签**：ADR 0044 把「其余为已裁沿用」限于原签署记录；为 §三的已知零总成本、波幅证据先决与零代理下界三条分别补 `[新缠论:推论]` 与推导所据的 ADR 0035 裁定一／二、ADR 0022 裁定六／七。不沿用 ADR 0035「其余 [新缠论:选择]」标签。
2. **正文援引**：§三「不设可调字段」仅引 ADR 0041 裁定二、四及 #799、#804；裁定一的标签要求由溯源节落实。
3. **Q5 的出处与归类**：`draft.md` 考古对照与 `archaeology.md/json` 改为 B，保留两路查询及原出处，并区分既有通则和本票推论；不改变「不新增字段」的答案。
4. **受影响代码清单**：保留 `b7e23c31` 行号，另补 `5a4033fd9083aafaea580ef56c050c1e21ef29df` 的原因变体、错误定义与早返、相反的测试，以及已经对齐的零代理路径。第二轮代码独审 BLOCK 后须重写，第三轮以新头为准。
5. **授权来源**：ADR 三行头注明「依 #1909 代理独审裁定，非 UserSigned」；获审版本及独审原件由主控在 PASS 后登记。
6. **原签署正本头**：ADR 0044 第 3 行恢复成取证源提交的原字节，保留 P0/P1 的代码样式及「θ 与四项成本输入的状态、来源与有效域」括注。

`classify.json` 只将 `round` 从 1 改为 2。`canonical-plan.json` 仍以 `b9d898dccf46c2a716115eaa1215bc39c458a959` 为源，四条精确替换逐条唯一命中；重放结果与第 2 轮 ADR blob 逐字相同。首轮其它实质建议未纳入专修。

## 证明 §三只有援引变化

在仓内使用 bash/zsh；把 `r2` 设为本包 `MANIFEST.txt` 的 `revision_head`。以下命令无输出、退出 0；不执行左侧的 `sed` 替换，则只看到第 2 条所列援引变化。

```bash
r1=138e9377ae26e4f6a751348907ebc39e0a9e2551
p=docs/adr/0044-cost-stop-policy-signed-instance-v1.md
adr_3() { git show "$1:$p" | sed -n '/^### 三、已知总成本/,/^## 签署记录/p'; }
diff -u <(adr_3 "$r1" | sed 's/裁定一、二、四；#799、#804/裁定二、四；#799、#804/') <(adr_3 "$r2")
```
