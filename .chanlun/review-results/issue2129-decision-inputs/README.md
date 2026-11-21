# #2129 裁决候选：交给异家族 R1–R8

- `classify.json`、`archaeology.json`、`archaeology.md`：T 类、四问两路考古及归类。tracker 搜索覆盖已关闭票；原生 parent/dependencies 单独核实。
- `draft.md`、`canonical-edit/plan.json`、`canonical-edit/final.diff`：同一最终提案。以官方 canonical-edit 解析、校验并写入后，对比候选 Git blob 与 plan.after 字节相等，只改 ADR 0073。
- `probe/`：实际 Boat Linux 原日志、测试片段和启动脚本。首跑已观察争点，但探针错误地期望 E2 原回复为 IdentityConflict，因断言失败退出 101；更正为真实 StaleWriter 后，同一用例通过，包含 E2 新代读回与 X 冷改拒绝两个对照。
- `checks/`：引用 HTTP 状态、退役引用检查、机械结构检查。业务功能实装和正式 launcher 的 H2 多臂验收仍归 #1411。

## 在隔离 Linux 复跑探针

从指定 #2082 原件准备干净目录，复制本包 `probe/` 下的三个输入文件（BASELINE、probe.rs、run-probe.sh）。现有 archive 原件不含额外测试；脚本只追加独立测试函数。

```sh
git archive 329be34f5a9ca9c2bcc38ae75783304cc654904c rust s_session | tar -xf - -C "$isolated_input_dir"
cp "$evidence_dir/probe/"{BASELINE,probe.rs,run-probe.sh} "$isolated_input_dir/"
boat run --from hc-ci-slim --no-env --timeout 1100 --push "$isolated_input_dir" -- bash run-probe.sh
```

两个生产 binary 用 production_session feature 构建。只有预制非空经济状态与逻辑时钟用现成受控夹具；实际 ReleaseExact、E 具名恢复、X ↔ E 权威往返都是真进程。无 S 服务、无真实场所、无正式 launcher；夹具为本基线缺少 #2079 的同址退役实现而移走自己的 E1 残留，未改任何业务库。

待审对象的优先反例：拒绝后换代重试、上次已请求但 S 未给结果、原 E 回执被用新代重标、只改本机路径导致业务根或绑定变化、跨计划收据、S 介质门未过却已发布 X、提交回执丢失重复追加。
