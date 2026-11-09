# CLAUDE.md

@AGENTS.md

## formal/ 的 fixture 漂移检查

改动 `formal/` 的会话收尾跑一次漂移检查，核对两个机器导出的 fixture 与 Lean 源一致：

```bash
python3 scripts/check_fixture_drift.py
```

- exit=0 无漂移；exit=1 真漂移（脚本打出字段级差异：重落 fixture 或回退 Lean 改动）；
  exit=3/4/5 是工具链或构建问题，不是漂移（3=lake 不在 PATH，4=lake build 失败，5=导出器运行失败）。
- 冷环境（`formal/.lake/build` 缺失或为空）时脚本先全量 `lake build`，耗时见 `scripts/check_fixture_drift.py` docstring。
- 覆盖 fixture：`rust/tests/fixtures/theta_v0_parity.json`（导出器 `formal/Origin/ParityFixtureExport.lean`）、
  `rust/tests/fixtures/theta_v0_center_parity.json`（导出器 `formal/Origin/CenterConstruct.lean:634`）。
  改了对应 Lean 源后用 `cd formal && lake env lean <导出器> > ../rust/tests/fixtures/<fixture>` 重落盘；fixture 只由机器导出，不手编。
- CI 的 `fixture-drift` job 跑同一脚本，漂移即红并打出再生命令。
- 另有 cargo 入口 `rust/tests/theta_v0_fixture_drift.rs`，标了 `#[ignore]`，CI 不跑它（`ci.yml` 保持 ignore）。需要时在远端环境用
  `cd rust && cargo test --release --test theta_v0_fixture_drift -- --ignored --nocapture` 触发；macOS 本机不跑 cargo。
