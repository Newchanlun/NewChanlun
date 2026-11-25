# fm09-register：FM-09 登记册三审输入（#2316 r3，供 FM-09a 复审）

本目录位于证据分支 `evidence/2310-fm09-register-r3`，仅供非作者复审读取，不合入 `main`。
基线为 r2 `origin/evidence/2310-fm09-register-r2`（`36fc364aea774f8f2e9cd0de994cd500c2139bb0`），首轮为 `4b75e60e9ef92b78460a4bf017f7f9b43a0c7b9c`。逐件摘要见 `SHA256SUMS`。

- 语料指纹（`docs/chanlun/text/blog` 下 `sha256sum *.md | sha256sum`）：
  `b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d`
- 本轮按二审报告 `audit-reports/2316/FM-09a-audit-r2.md` 返修：先落机械护栏 `guards/`（G1 禁引隔离、G2 合并行与跨帖行、G3 答疑帖边界），在 r2 原件上跑出红项清单 `guards/baseline-red.txt`，再一次改完主册、手册、两个附录的禁引标记与旧标签、禁引表，终稿护栏退出 0。
- 变更对照与未解决项见 `FM-09a-r3-changelog.md`；r2 的 `FM-09a-r2-changelog.md`、`FM-09a-r2-attrib-summary.md` 原样保留。护栏规则全文见 `guards/README.md`。
- 机读产物：`tmp/hard_cite_exclusions.json`（r3 增至 36 个 id，另有 `excluded_lines_r3` 11 个课行）、`tmp/pool_375_recheck_r3.jsonl`（375 条帖边界重算记录，含旧帖头与差异）、`guards/g3_manual.json`（3 条人工判定）。
- `tmp/*.py`、`tmp/ledger_final.jsonl`、`tmp/pool_375_recheck.jsonl`、`tmp/manual_*.json` 与语料保持原字节。
- 复跑入口：`python3 -I fm09-register/run_on_checkout.py <脚本名> [参数]`（运行时重定向 `lib.BLOG`，不改脚本字节）；护栏 `python3 -I fm09-register/guards/guard_register.py`，自检 `python3 -I fm09-register/guards/selftest.py`。

2026-11-25 r3 打包实测读数（仓库根目录）：

| 命令 | 输出 | 退出码 |
|---|---|---:|
| `guards/selftest.py` | `selftest OK` | `0` |
| `guards/guard_register.py` | 红 0，无法判定 0，`exit 0` | `0` |
| `guards/baseline.py`（r2 原件） | `baseline exit 1`：红 156（G1 121、G2 19、G3 16），无法判定 6 | 脚本 `0`，护栏 `1` |
| `verify_final.py` | `entries 1604 bad 0 {'main_body': 790, 'main_machine_author': 782, 'note_cites': 2054, 'note_author_verbatim': 1685, 'note_nonauthor_verbatim': 58, 'main_manual_confirmed': 32}` | `0` |
| `verify_report.py` 主册 | `files 1 quotes checked 968 bare cites 379 bad 0` | `0` |
| `verify_report.py --allow-free` 附录 1、2 | `files 2 quotes checked 3716 bare cites 1401 bad 0` | `0` |
| `verify_report.py` 手册 v2 | `files 1 quotes checked 20 bare cites 119 bad 0` | `0` |
