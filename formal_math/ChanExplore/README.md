# ChanExplore：先找反例，再写证明

把待检断言写成可判定谓词。例如，搜索「两根 K 线都是单点」的首个反例：

```lean
module

meta import ChanExplore.Search

open ChanExplore

#eval findCounterexample 2 3 (fun path => path.all (fun b => b.low == b.high) = true)
#eval randomCheck 2 3 2319 100 (fun path => path.all (fun b => b.low == b.high) = true)
```

在 `ChanExplore/` 内使用 `#eval`。`findCounterexample n k P` 按低点、高点及路径位置的字典序遍历 `Fin k` 上的长度 `n` 路径；`witness` 是首条使 `P` 为假的路径，`checked` 是实际判定条数，包含命中条目。若 `witness = none`，则该界内没有反例。长度为零时只检查空路径；若 `k = 0` 且长度为正，则没有路径可查。

`randomCheck n k seed trials P` 从显式种子开启 Lean 的 `StdGen`，每根 K 线对两次取样的价位排序，至多判定 `trials` 条路径。相同输入可重放，不读取系统时间；端点取模再排序，区间抽样并非均匀分布。外层 `none` 代表空价格格无法生成正长度路径；结果里的 `witness = none` 只代表抽样未命中。

## 规模与实测

单点也算闭区间，每格有 `m = k(k+1)/2` 种区间，完整空间有 `m^n` 条路径。路径逐条生成并在首个反例处停止，不一次存下笛卡尔积。最坏情况下判定 `m^n` 次，每条路径另有 `O(n)` 的构造开销。

| 反例 | `Fin 8` 首次命中：实际判定 / 完整空间，耗时 | 最小规模：实际判定 / 完整空间，耗时 |
| --- | --- | --- |
| 外包线吞掉最高价 | `n=4, k=8`：2,881 / 1,679,616，5.36 ms | `n=4, k=3`：91 / 1,296，0.23 ms |
| 三段首尾相接而公共部分为空 | `n=3, k=8`：1,421 / 46,656，0.88 ms | `n=3, k=4`：139 / 1,000，0.10 ms |

* **外包线：** 输入 `[0,0], [0,2], [1,1], [0,0]`。第二根向下合并吞掉最高价 2，合并后仍有顶分型，顶价是 1。至少要保留三根才能有顶分型，再加至少一次合并，所以原序列至少四根。原最高价、合并后顶价、顶分型邻线高点严格有序，至少需要三个价位。
* **三段：** 连续方向为下、上、下，端点序列是 `1 → 0 → 3 → 2`，区间是 `[0,1], [0,3], [2,3]`。首末区间分离，且各有两个不同端点，因此三个非平段至少使用四个价位。

[Examples.lean](Examples.lean) 的两个定理用内核 `decide` 锁定从 `Fin 8` 搜出的首个路径及其反例判据。[Bench.lean](Bench.lean) 搜索更短路径与更小价格格，并检查穷举和抽样的边界行为。上表为本机单次搜索计时，不含导入和打印。在 `formal_math/` 下复跑：

```sh
TMPDIR=/Volumes/AgentStorage/fm/tmp PATH="$HOME/.elan/bin:$PATH" lake build --wfail ChanExplore
TMPDIR=/Volumes/AgentStorage/fm/tmp PATH="$HOME/.elan/bin:$PATH" lake env lean -DwarningAsError=true -DautoImplicit=false ChanExplore/Bench.lean
```

## 何时能用小模型结论

小模型定理证出之前，「界内无反例」只算启发式证据。将有界穷举的完备性推广到其他价格域，只适用于已证明在跨价格域保序嵌入下保持判定结果的谓词，或只比较路径上已出现的端点、只量化路径已有下标的谓词。长度界仍然有效；抽样不能替代穷举。

`ChanExplore` 是非可信探索库，包含处理和顶分型仅为草稿。可信库不得导入它；默认构建目标仍是 `Chan`。
