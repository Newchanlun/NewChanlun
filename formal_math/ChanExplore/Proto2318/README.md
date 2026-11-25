# Proto2318：多级结构表示法对比与规范形唯一性预搜

票 #2318（FM-10a）的原型码。全部定义是探索用草稿，不是 `Chan` 的正式定义；可信库不得导入本目录。结论正文在票评论里，这里只说明文件与复跑办法。

## 文件

| 文件 | 内容 |
|---|---|
| `Basic.lean` | 区间序列、块语言、八个政策、声明式规范 `ValidDecomp policy S d` 及其 `Decidable` 实例、良构切点表的有限枚举 |
| `Cert.lean` | 逐级粗化 `coarsen`、多级规范 `ValidTower`、三种中枢生成证书 `Cert` 与校验 `Cert.Holds` |
| `Unique.lean` | 对任意序列成立的定理：`chain_unique`、`chain_exists`、五个政策各自的 `…_existsUnique`、`tower_unique`、`tower_exists`、`mixed_existsUnique`，以及把枚举读数转成 `∃!` 的桥接引理 |
| `Repr.lean` | 三种表示（括号树、切点集合的层状族、序列塔）与六条玩具引理 |
| `Cases.lean` | 判别例的内核读数：八段来回、九段来回、设计输入的九段折线、相邻两核外缘相触的七段折线 |
| `Enum.lean` | `Fin k` 上方向交替折线的直接枚举与分布统计 `census` |
| `Census.lean` | 由 `py/gen_census_lean.py` 生成的 `#guard`，把 Lean 的直接枚举与 Python 读数逐格比对 |
| `py/model.py` | Python 侧模型：照定义直写的检查器 `valid` 与带预计算的枚举器 `analyze` |
| `py/selfcheck.py` | 核对 `analyze` 与穷举全部切点子集的 `brute` 一致 |
| `py/census.py` | 序型穷举（`packed`）与 `Fin k` 直接枚举（`raw`） |
| `py/cases.py` | 判别例读数 |
| `py/invariance.py` | 镜像等变与保序变换不变的读数 |
| `py/nine_stats.py` | 延伸满九段的折线按 `3+3+3` 重切后各组有没有自己的三段重叠 |
| `py/gen_census_lean.py` | 由 Python 读数生成 `Census.lean` |
| `py/summary.py` | 把 `census.py` 的 JSON 压成结论文档里的表 |
| `py/out/` | 各次运行的输出（`.md` 表格与 `.json` 原始计数） |

## 政策对照

Python 名与 Lean 构造子一一对应：`ANY_FULL`/`anyFull`、`ANY_EXH`/`anyExh`、`SAME`/`same`、`MIN`/`minimal`、`MAX`/`maximal`、`EXT_EXH`/`extExh`、`NOCAP`/`noCap`、`CARRY`/`carry`。全局择优的 `LEXMIN_FULL`、`LEXMAX_FULL`、`HIGH` 只在 Python 侧。

## 复跑

Python 只用标准库，在 `py/` 下运行。括号里是本机实测耗时。

```sh
python3 selfcheck.py 6 5 600                         # 28 秒
python3 cases.py                                     # 不到 1 秒
python3 invariance.py 7                              # 7 秒
python3 nine_stats.py 9                              # 13 秒
python3 census.py packed 9 4 out/packed9.json > out/packed9.md          # 4 进程，1 分 52 秒
python3 census.py packed 10 5 out/packed10only.json 10 > out/packed10only.md   # 5 进程，只跑 10 段
python3 census.py raw 3 18 4 out/raw3_18.json > out/raw3_18.md          # 9 秒
python3 census.py raw 4 13 4 out/raw4_13.json > out/raw4_13.md          # 32 秒
python3 census.py raw 5 11 4 out/raw5_11.json > out/raw5_11.md
python3 gen_census_lean.py out/raw3_18.json out/raw4_13.json out/packed9.json > ../Census.lean
```

Lean 在 `formal_math/` 下构建。`.lake/packages` 指向已有的预编译 Mathlib，不重新下载。

```sh
export TMPDIR=/home/workspace/fm/tmp PATH=$HOME/.elan/bin:$PATH
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh lake build --wfail ChanExplore
```

`Cases.lean` 约 37 秒，`Census.lean` 约 49 秒，都是内核判定与解释执行的耗时。

## 证据等级

- 内核已验·一般：`Unique.lean` 与 `Repr.lean` 的定理，对任意序列成立。
- 内核已验·判例：`Cases.lean` 里用 `decide +kernel` 得到的读数，只对写明的那条折线成立。
- Lean 解释执行读数：`Census.lean` 的 `#guard`。
- Python 读数：`py/out/` 下的表。
- 小模型读数都只是启发式证据。谓词只比较价位大小，所以 n 段折线的序型穷举对任意线序价位域完备；长度界仍然有效。
