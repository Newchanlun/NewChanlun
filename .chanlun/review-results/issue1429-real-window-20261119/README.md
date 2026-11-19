# 九段重切：如何判别是哪些段贡献了外缘（#1429）

在 #1552 冻结的 9011 根 OHLC 中，`center:1:301` 有 11 个已完成段成员。取前九段，三段一组，逐窗以三段高低区间取严格交集，得到 **[8834,11512]、[8205,9155]、[10655,12908]**。继承第一窗核心会算错后两窗。

第二窗的起始锚为 558↓、653↑、678↓，端点价格依次 **11988 → 7478 → 9155 → 8205**。下表的锚是达到外缘下沿 DD 的参与段，不是所有成员；三种候选的 DD 恰好都是 7478。

| 选择 Zn 的办法 | 取到的段 | 外缘上沿 GG | DD 的贡献段 |
|---|---|---:|---|
| 跟随本窗首段（↓） | 558、678 | 11988 | 558 |
| 跟随母 seed（↑） | 653 | 9155 | 653 |
| 不分方向，取全员 | 558、653、678 | 11988 | 558、653 |

**采用这组数作 R22 的判别输入，验收时同时检查价格与贡献段身份。** 按[正本 Z-4](https://github.com/Newchanlun/NewChanlun/blob/68f7eb9dfef6b130b270071ffcc8b4d8191c74ed/.chanlun/definitions/zhongshu.md#L308-L318)，重切所得是本级子中枢；若按现有三段中枢合同构造它，应以本窗首段为参照。[第 20 课正文第 52 行](https://github.com/Newchanlun/NewChanlun/blob/68f7eb9dfef6b130b270071ffcc8b4d8191c74ed/docs/chanlun/text/blog/020-第20课.md#L48-L54)将 A、C 的方向与该中枢形成的方向联系，四指标只遍历 Zn。取母向将失去首成员的高点；取全员虽然复得本窗外缘数值，却给低点多记一个贡献者。这里给出 #1429 的推荐方案和独立验收输入；[§9.5](https://github.com/Newchanlun/NewChanlun/blob/68f7eb9dfef6b130b270071ffcc8b4d8191c74ed/.chanlun/definitions/zhongshu.md#L615-L622) 的过渡例外仍待正式裁定、落码和验收。

**Lean 的唯一性有明确边界。** W2 的 `CenterDerivedAt` 对带自身方向的三个 segment 已唯一决定核心与外缘；[定理和整数工作例](Boundary1429.lean)排除了母向数值。对相同的三个递归良构 compose，原谓词却允许相同核心 [20,30] 配外缘 [10,35] 或 [4,40]，两种父走势均满足 WellFormed。构造器默认 ↑ 只给出后一种的一个见证。要把 R22 推到上级，实际方向必须与 #1426 的完成对象及投影上下文绑定；不能直接用默认 ↑、不能把盘整赋成语义上的上涨。这个形式反例不声称生产曾对同一输入作出两个决定。

**成员边界。** 九段均有可回查的反向摆动，三个子窗核心均非空；这不是无波动/空核心分支的测试。937、989 是母窗尾段；1212 是左、右两中枢之间的连接段，不属于任一中枢成员。候选 S 的原母窗仍为待升级状态、外缘未发布。所用对象来自 [C/D、E/F 构造器末切面](https://github.com/Newchanlun/NewChanlun/issues/1552#issuecomment-6990003817)；本证据不产生上级完成 Move、S 的发布回执或经济 terminal。

## 从最小输入复核

[原始对象定位、段与源锚](input.json)和[两组候选计算](candidates.json)可用相邻脚本重算，无需重放 9011 根：

```sh
python3 witness.py calc input.json | cmp - candidates.json
```

原 `objects.jsonl` 及冻结行情在 `/Volumes/AgentStorage/issue1552-domain-9011-20261118/`。在那里取得两份原文件后，`python3 witness.py extract /path/to/that-directory | cmp - input.json` 可复核抽取。

[Linux x86_64 / Lean 4.31.0 编译原件](lean-result.json)。在本证据提交的仓根，用项目版本的 Lean 在临时目录重编三份原模块与定理：

```sh
p=.chanlun/review-results/issue1429-real-window-20261119
d=$(mktemp -d)
mkdir -p "$d/src/Formal"
cp "$p/Boundary1429.lean" "$p/check.sh" "$d/src/"
for m in TrendTrichotomy CenterTrichotomy RecursiveConstruction; do
  cp "formal/Formal/$m.lean" "$d/src/Formal/"
done
sh "$d/src/check.sh"
```

受测为 W2 `68f7eb9d`，三份 Lean 源与工具链在 `9e57032b` 未变。这是独立验证代码及其原件，不改生产构造。
