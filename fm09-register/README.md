# fm09-register：FM-09 登记册二审输入（#2316 R2，供 FM-09a 复审）

本目录位于证据分支 `evidence/2310-fm09-register-r2`，仅供非作者二审读取，不合入 `main`。
首轮基线为 `origin/evidence/2310-fm09-register`（`4b75e60e9ef92b78460a4bf017f7f9b43a0c7b9c`）。摘要见 `SHA256SUMS`。

- 语料指纹（`docs/chanlun/text/blog` 下 `sha256sum *.md | sha256sum`）：
  `b6a35574ed6db3625da6d18f4e11c8976874ba66b0e888362e1769483f0c0a0d`
- 本轮返修覆盖 `#2316` 首轮 Astra 审计全部 12 项阻塞（K1 至 K12）、全部非阻塞项（N1 至 N9）、375 条答疑 A2 层全量人工重核与 367 对账、32 条人工名单分层（21 条干净一手白名单 / 11 条禁入）、第二份 Astra 审计 M16a/M6/门禁订正，以及五课召回 5 项候选。
- 变更对照见 `FM-09a-r2-changelog.md`，375+32 归属重核全报见 `FM-09a-r2-attrib-summary.md`，机读产物见 `tmp/pool_375_recheck.jsonl`、`tmp/manual_32_recheck.json`、`tmp/hard_cite_exclusions.json`（含 `tmp/attribution_flags.json` 补登 `006:42`）。
- 原 `tmp/ledger_final.jsonl`、`tmp/manual_author_confirmed.json` 与 `tmp/*.py` 保持首轮原字节不变，确保 375 总体与首轮复现口径完全一致。
- 复跑入口：`python3 -I fm09-register/run_on_checkout.py <脚本名> [参数]`（运行时重定向 `lib.BLOG`，不改脚本字节）。

2026-11-24 二审打包实测读数（全部退出码 0）：

| 命令 | 输出 | 退出码 |
|---|---|---:|
| `verify_final.py` | `entries 1604 bad 0 {'main_body': 790, 'main_machine_author': 782, 'note_cites': 2054, 'note_author_verbatim': 1685, 'note_nonauthor_verbatim': 58, 'main_manual_confirmed': 32}` | `0` |
| `verify_report.py` 主册 | `files 1 quotes checked 976 bare cites 340 bad 0` | `0` |
| `verify_report.py --allow-free` 附录 1、2 | `files 2 quotes checked 3801 bare cites 1314 bad 0` | `0` |
| `verify_report.py` 手册 v2 | `files 1 quotes checked 21 bare cites 214 bad 0` | `0` |
