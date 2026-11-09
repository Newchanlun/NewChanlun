# Verification Command

提交前核验当前改动。只跑覆盖本次改动的检查，每项照实报告：通过、失败，或未跑及原因。

- `.sandcastle/`、`scripts/` 下的 TypeScript：`npm run typecheck`，再跑改动模块旁的测试，例如 `npx tsx --test .sandcastle/<模块>.test.mts`。
- Deep Agents 执行器（`.sandcastle/deepagents-pilot/`）：在该目录跑 `python -m pytest -q tests`，可加 `-k` 只跑相关用例。
- 其余 Python：`python -m pytest -q <相关测试>`。
- Rust：macOS 本机不跑 cargo 或 rustc。先提交，再用 `NC_REPO="$(git rev-parse --show-toplevel)" NC_TARGET=<唯一名> ~/.local/bin/nc-remote <已提交分支> rust cargo check --locked`，或推分支交 CI。拿不到真实结果就写「Rust 未验证」。
- 改了 `formal/`：`python3 scripts/check_fixture_drift.py`。
- `git status` 与 `git diff --cached --stat`：确认只暂存了本次要提交的文件。

输出：

```
VERIFICATION: PASS / FAIL
<检查>: 通过 / 失败（原因） / 未跑（原因）
```

$ARGUMENTS 可写要核验的路径或检查名；不写时按 `git status` 列出的改动选检查。
