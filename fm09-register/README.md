# fm09-register：FM-09 登记册抽审输入（#2310，供 FM-09a）

本目录只在 `evidence/2310-fm09-register` 分支上，供非作者抽审读取，不合入 `main`。
文件由 SafeCode `/home/workspace/fm/` 原样复制，摘要见 `SHA256SUMS`。

- 语料指纹（`docs/chanlun/text/blog` 下 `sha256sum *.md | sha256sum`）：
  `b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d`
- 分支基线：`origin/main` `a2a3ac866c41f97cb968eb3d34d507038ad8b899`
- `tmp/` 保留原目录层级，脚本按自身所在目录找台账与名单。
- `tmp/lib.py` 把语料目录写死为 SafeCode 的绝对路径。别的机器用 `run_on_checkout.py`
  复跑，它只在运行时改 `lib.BLOG`，不改原脚本字节。用法见该文件头部。
- `run_on_checkout.py` 与本 README、`SHA256SUMS` 是打包时新增的，其余文件都是原件。

SafeCode 上 2026-11-24 的复跑读数：

| 命令 | 输出 |
|---|---|
| `verify_final.py` | `entries 1604 bad 0` |
| `verify_report.py` 主册 | `files 1 quotes checked 966 bare cites 135 bad 0`（主册 6.4 自记 965，差一处，待 FM-09a 核对） |
| `verify_report.py --allow-free` 附录 1、2 | `files 2 quotes checked 3801 bare cites 1314 bad 0` |
| `verify_report.py` 手册 v2 | `bad 1`，唯一一条是文首线程链接标题里的直角引号，已知例外 |
