# E 判域使用的模型尚未绑定模拟 X 的实际模型（#1407 C3 / #1381）

在 #2081 产品候选上维持同一个 E 财务输入和同一条精确命令，只将模拟 X 的 maker 费率从 1/100 改成 10/100。两次实际成交均为 2 × 14 = 28 TEST-CASH，均取得一次受控资格、占有与本地模拟执行；X 的费用原件分别为 ceil(28/100) = **1** 和 ceil(280/100) = **3 TEST-CASH**。两个配置都能对这条 limit 命令成交。这里缺的是对同一模型版本的授权，而不是订单类型本身越界。

[逐项对照](comparison.json)；[对照模型](control/x-profile.json)、[变更模型](altered/x-profile.json)；[对照原批](control/x-bar-3.reply.wire)、[变更后的原批](altered/x-bar-3.reply.wire)。两组原帧均已保留：FIN/5 输入、给 X 的重试请求、X 接纳回包及受控 S 资格回执逐字节相同。E 的 Release 收据键和命令摘要相同；整份 Release 回包并非相同。三项原责任在两臂均合计 90 TEST-CASH。

## 为什么不是已绑定的模型

E 判域所用的 model_ref 固定于 FIN/5 输入。此 TestOnly 出具者对模型名称加版本的字符串求摘要，不是对实际 X 模型正文求摘要。[E 组装命令与证书](https://github.com/Newchanlun/NewChanlun/blob/eabdfb02013135db78d21cb2d8a47dec0a71a555/rust/src/economic_session/exact_command.rs#L338-L362)时未携带完整模型身份。X 冻结并使用自己实际加载的模型产生有出处的回报；命令相同没有约束这个模型。变更臂的[正式装配](altered/production.json)和[启动记录](altered/outer.stderr)证实唯一 launcher 没有拒绝这对配置。签署执行资格的 S 仍为受控夹具，正式 S 进程并未签发这张回执。

优先在 E 签发的不可改命令中绑定获准的执行模型，在 X 接纳或创建首次执行责任前与实际模型核对；E 仍是唯一覆盖域判定点。不同模型对象若使用不同规范表示，须有权威映射，不能把两个不同对象的哈希直接视作可互换，也不能只对名称和版本标签。X 的真实回报继续按实际模型留存，不靠 E 事后拒绝回报来防止执行。

## 在 Linux 重现

固定产品头 `eabdfb02013135db78d21cb2d8a47dec0a71a555`；对照原件复用先前的 C2 实跑。按同头 [C2 复跑说明](https://github.com/Newchanlun/NewChanlun/blob/eabdfb02013135db78d21cb2d8a47dec0a71a555/rust/src/history_simulation/README.md#在-linux-复跑-1407-c2)准备 L1 的 unit 夹具。二进制目录同时需含同头 production_session、s_structure_session、E/B/X 及其运行库。用独立的新目录运行：

```sh
python3 probe.py "$PRODUCT" --bin "$BINS" --fixture "$UNIT_FIXTURE" --out "$(mktemp -d /tmp/cm.XXXXXX)/run"
```

[探针](probe.py)复用该固定版本的正式组件，仅使用本地 simulation 及 Unix socket。完整现场在 `/Volumes/AgentStorage/issue1407-c2/c3-model-binding-20261119/`。这是阻断 C3 模型身份验收的实测，不是对已冻结归档的改写。
