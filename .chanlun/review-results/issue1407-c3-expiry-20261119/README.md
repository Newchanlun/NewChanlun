# E 放行时核验资金有效期（#1407 C3）

同一份 TestOnly 资金政策在 FIN/5 逻辑读数 100000 仍有效，100001 不再有效。两次独立启动正式 E、两个 B 和模拟 X，从完全相同的 E/B 业务表、cut 5 和 Dispatchable 原收据开始，不发送到期通知。两份 Release 请求除用于逻辑调度的消息 ID 外完全相同；给 X 的请求逐字节相同。

| E 逻辑读数 | E 放行与原 ID 查询 | X 尝试接纳 |
|---:|---|---|
| 100000 | 发布 cut 6，ReleasedExact，两份原收据 | 本地时钟仍早于放行，拒绝 |
| 100001 | 报资金/能力证据过期；仍为 cut 5、Dispatchable，只有准备收据 | E 授权查回 NoRecord@5，X 拒绝 |

两臂的既有责任 20、alpha 30、beta 40 共 90 TEST-CASH 均保留；X 的接纳、占有、调用均为 0。这里核的是 E 财务交付时点；本次受控 S 没有取得资格，CE-S09 的真实 S/X 后续断源或时钟失效另验。

## 复跑

Linux 使用本证据提交的父提交 `eabdfb02013135db78d21cb2d8a47dec0a71a555`，见[该候选的构建及 L1 原输入生成方法](../../../rust/src/history_simulation/README.md#在-linux-复跑-1407-c2)。完成其中的 build 和 L1 测试后，令 `src` 指向该产品树绝对路径，`bin` 为 debug 二进制目录，`fixture` 为实际的 `unit-*` 目录，`probe` 为本目录 `probe.py` 的绝对路径。两臂须复用同一个绝对输出路径以比较业务表。

```sh
d=$(mktemp -d /tmp/c3.XXXXXX)
for arm in valid expired; do
  python3 "$probe" "$src" "$arm" --bin "$bin" --fixture "$fixture" --out "$d/case" || exit 1
  mv "$d/case" "$d/$arm"
done
cmp "$d/valid/prefix.json" "$d/expired/prefix.json" &&
cmp "$d/valid/manifest.json" "$d/expired/manifest.json" &&
cmp "$d/valid/MakeDispatchable-alpha.reply.wire" "$d/expired/MakeDispatchable-alpha.reply.wire" &&
cmp "$d/valid/x-first-accept.request.wire" "$d/expired/x-first-accept.request.wire"
```

[有效臂摘要](valid/summary.json)和[过界臂摘要](expired/summary.json)记录切面、责任身份和实际错误；同目录收录 E 的放行请求、回复及 X 的接纳回复原帧。`policy_bound` 和 `commit_reading` 是 logical-bar/1 的离散读数。完整请求应答、逐表前缀和执行记录另存 `/Volumes/AgentStorage/issue1407-c2/c3-expiry-20261119/`。
