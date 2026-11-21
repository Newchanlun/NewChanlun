# #1551 · ADR 0064 第五稿复审输入

先读 [完整 resolution 草稿](draft.md)；决策候选与精确替换在 [canonical_edit.json](canonical_edit.json)。历史观察头为 `b9d898dccf46c2a716115eaa1215bc39c458a959`，实际验收另冻结 F。G0 是 #1915 的落地 `bd54d4b28ec4f83d596837f84f1f861dd085124c`，P0 是其第一父 `b5cd3fee352e5f7199233de628da05ff06c5798f`。

## 哪些边界已钉死

- **B3-1** · [清册入口](landing-census.json)绑定四份输入，显式裁 33 张非原生来源票的 scope；[归属依据](scope-basis.md)逐票列原件。脚本对原生父链和显式映射取并集，拒绝漏项、重复和越域。多 TB 分开投影；GRAPH 只作为历史出处进入全部 DST，不增加任何票的成功门。此观察头的六个 DST 均含 TB-01..10；因此实际 R10 子投影各为 68 个票／作用域对、62 个票号、加 F 后 116 个提交。R12 原生分母和 R13 旧票在完整报告里另按各自规则并入。
- **B3-2** · #1320 重型测量只进入 TB-11、#1320 旧票及顶层延期；其余三个合法延期只跟具名键。TB 实体不混入专用槽；目的地专用证据只取第二节指定的权限运行引用或迁移封印引用。后闸专用原件只留顶层。授权依据始终与运行引用分层。
- **B3-3** · `FailedCheck` 按第八节固定 scope 分隔符与 `none`，两节统一 `detail=check_id`。适配器由 F 的登记册按字节摘要绑定，两个路径各自核 R09，后闸参数版本固定引用签署原件。
- **D1** · 七段、引用自证与 Q1–Q11 考古对照恢复；[分级](../issue1551-amend-inputs-r3/classify.json)与[原始考古](../issue1551-amend-inputs-r3/archaeology.md)仍用冻结的前稿原件。唯一 `canonical_edit` fence 等于合同的 `primary`。

## 重放证明

在含完整 Git 历史的克隆根目录运行。将 B 设为本证据目录，O、I 和 S 分别设为新输出目录、新翻转输出目录和新票态 JSON 路径：

    python3 "$B/rebuild_pregate.py" --f b9d898dccf46c2a716115eaa1215bc39c458a959 \
      --source "$B/sources.json" --adjudication "$B/adjudication.json" \
      --census "$B/landing-census.json" --historical-runs "$B/historical-runs.json" --out "$O"
    python3 "$B/check_census.py" "$B"
    python3 "$B/flip_states.py" "$B/sources.json" "$S"
    python3 "$B/rebuild_pregate.py" --f b9d898dccf46c2a716115eaa1215bc39c458a959 \
      --source "$S" --adjudication "$B/adjudication.json" \
      --census "$B/landing-census.json" --historical-runs "$B/historical-runs.json" --out "$I"
    python3 "$B/check_r5.py" "$B" "$O" "$I"
    node "$B/check_edits.mjs" "$B"

翻转只在反例演算中替换 relations，原清册的摘要绑定仍对正式冻结原件核验，不把翻转样本当成可验收输入。运行选择、归属映射、Git path/blob 与历史偏差均不读票态；唯一变化是 summary 的开放票观察字段（21→41）。报告里的 `downstream_status` 仍依报告窗口照录真票态。完整输出见 [底册重放](census-check.txt)、[编辑重放](canonical-check.txt)、[暂合主线的引用测试](pytest.txt)。

## 正式验收的交棒

#2132 继续用正式非作者复审核逐票语义归属、未标记提交及 PRE 原件，并按裁定核 #1493 从 #1323 改挂 #1360。62 票、115 落地、1,025 PRE 只是本次实测，不冻结分母。#2131 的适配器与 #1391/#1403 两个独立实现须运行草稿验收清单的真实夹具。#2133 未有效签署时不接触凭据；#1279 不提前关闭或放行。决策稿待本轮异家族独审。
