# FM-10d 接口约束页（M10 至 M14）

本页只写文件路径、命名空间、公开定义名与一句话职责、Mathlib 载体类型、以及 Lean 4.36.0 `module` 与门禁规范。**本页不含任何 Lean 类型签名**，具体数据结构、参数顺序与实现方式由盲写双方独立决定。

## 一、文件、命名空间与公开定义清单

全部文件位于 `formal_math/Chan/Defs/Base/` 下，文件模式 `100644`，每个 `.lean` 文件首行必须是 `module`，全部公开定义放进 `@[expose] public section`。本包可在冻结后的 M0、M2、M3、M4 公开定义之上构建（如复用 `Chan.Defs.Order.Bar`、`Chan.Defs.Alt.Basic` 等）。

| 模块 | 文件路径（相对 `formal_math/`） | 命名空间 | 公开定义名及一句话职责 |
|---|---|---|---|
| M10 | `Chan/Defs/Base/Kline.lean` | `Chan.Defs.Base` | `InitIncludePolicy`（开头即包含时的初始合并方向策略）；`MergedBar`（合并后 K 线：闭区间、原始索引跨度、所含原始 K 线根数）；`hasInclusion`（两闭区间互有包含关系，含端相等）；`mergePair`（给定方向的单步包含合并）；`klineNormalize`（从左到右顺序非包含处理函数）；`IsInclusionFree`（相邻无包含关系的规范形谓词） |
| M11 | `Chan/Defs/Base/Fractal.lean` | `Chan.Defs.Base` | `TripleKind`（无包含三邻 K 线四态完全分类：上升、下降、顶分型、底分型）；`classifyTriple`（判定连续三根无包含 K 线的类别）；`FractalKind`（顶分型/底分型枚举）；`LocalFractal`（局部三根无包含 K 线形成的原始分型）；`scanLocalFractals`（扫描无包含序列的全部局部原始分型）；`RetainedFractal`（经结合律与去重过滤后保留作笔端点的成笔分型）；`fractalEdge`（顶分型下边沿或底分型上边沿，仅作必要条件特征） |
| M12 | `Chan/Defs/Base/Pen.lean` | `Chan.Defs.Base` | `PenRule`（参数化笔规则：合并 K 线最少跨度、原始 K 线最少间隔、分型区间不重合开关）；`oldPenRule`（老笔规则实例）；`newPenRule`（新笔规则实例）；`sixBarPenRule`（六根笔规则实例）；`disjointFractalPenRule`（分型区间不重合规则实例）；`Pen`（由保留顶底分型构成的单笔，携带方向、值域闭区间、原始跨度）；`ValidPenPair`（相邻顶底分型构成合法单笔的谓词）；`ValidPenDecomp`（声明式合法笔分解谓词）；`parsePens`（带等值保留与反证回溯的确定性笔解析函数）；`PenPhase`（分型构造中/确认延伸为笔中二态）；`PenOnlineState`（缠中说禅笔定理四态在线状态与判定函数 `penOnlineState`） |
| M13 | `Chan/Defs/Base/Segment.lean` | `Chan.Defs.Base` | `SegRuleConfig`（显式固定两处答疑冲突处置口径的线段规则配置）；`FeatureElem`（特征序列元素及归属笔跨度）；`featureSeq`（提取候选线段的特征序列）；`hasFeatureGap`（特征序列相邻两元素严格分离缺口谓词）；`stdFeatureSeq`（按指定范围作包含处理后的标准特征序列）；`SegTermKind`（第一种情况无缺口/第二种情况有缺口待第二特征序列分型）；`Segment`（由至少三笔且前三笔重叠构成的线段，保留实际凸包区间与笔跨度）；`parseSegments`（以笔序列与起点为输入的确定性线段划分算法，输出方向交替区间序列）；`standardizeSegment`（将线段高低极值标准化到端点的视图函数） |
| M14 | `Chan/Defs/Base/Instance.lean` | `Chan.Defs.Base` | `BaseTag`（四种基底的具名标签枚举，用于类型级区分不同基底的级别）；`Tick`（带顺序索引与单点成交价的分笔成交点）；`BaseInterface`（抽象递归起始程序接口：基底标签、输入类型、确定性产出方向交替区间序列的算子）；`segmentBase`（默认线段基底实例）；`fractalDirectBase`（分型直连基底实例）；`klineOverlapBase`（最低级别 K 线重叠基底实例）；`tickBase`（分笔成交基底实例） |

## 二、推荐 Mathlib 载体（Lean `v4.36.0` + Mathlib `v4.36.0` 已实测存在）

- 闭区间与段：复用 `Chan.Defs.Order.Bar`、`Chan.Defs.Alt.Basic`（或 `NonemptyInterval P`）
- 列表与相邻关系：`List`、`List.IsChain`（`List.Chain'` 已更名为 `List.IsChain`）、`List.IsPrefix`
- 有限极值：`max`/`min` 列表递归或 `Finset.sup'`/`Finset.inf'`
- 多空对偶：`OrderDual`
- 可判定性：全部在可判定线性序上定义的核心谓词与解析函数应提供 `Decidable` / `DecidablePred` 实例或直接写成可计算函数，以便小模型穷举与 `decide` 核验。

## 三、Lean `v4.36.0` 模块系统与 `#2312` 阻断门硬规范（原样附 3.9 十四条约束）

1. 每个 `.lean` 文件第一条命令必须是 `module`。公开签名用到的模块用 `public import`，其余用 `import`。`Chan/Defs/` 下的定义一律放进 `@[expose] public section`。
2. 禁止整库 `import Mathlib`，只导入用到的具体子模块；`Chan/Defs/` 仅允许导入 `Chan.Defs.*`、`Mathlib.*` 与 `Init.*`（禁止导入 `Chan.Proxy`、`Chan.Thm`、`ChanExplore` 等）。
3. Mathlib 名称先在本机 `#check` 核实后再用（`List.Chain'` 已不存在，现名 `List.IsChain`）。
4. 禁用 `axiom`、`sorry`、`admit`、`native_decide`、`unsafe`、`extern`、`implemented_by`、`partial`、任何受控 `set_option`（`autoImplicit`、`relaxedAutoImplicit`、`linter.*`）及本地元编程（`macro`、`syntax`、`elab`、`notation`、`initialize`、`#eval`、`run_cmd` 等）。
5. 盲写工位只允许在自身盲写分支创建/修改 `formal_math/Chan/Defs/Base/` 下上表列出的文件，禁止修改 `lakefile.toml`、`lake-manifest.json`、`lean-toolchain`、`statement-lock.json`、`verification/`、`scripts/`、`.github/`。
6. 写定义阶段不写定理证明（可仅附构造性实例或必要类型不变式证明，确保定义良型、可判定）。
7. 每条 shell 命令保持短、单一用途；多行脚本先写成文件再执行。
8. 环境优先复用外置盘 `/Volumes/AgentStorage/fm/` 下的只读 Mathlib 依赖目录与 `TMPDIR`，不向系统内置盘复制 Mathlib。
9. 严禁从源码重新编译 Mathlib；若发现 Lake 开始编译 Mathlib 立即中止并报告。
10. 交卷前必须通过 `lake build --wfail`（以及 `#2312` 阻断门第 4、5、6、7 步检查，除未更新 `statement-lock.json` 外的全部红项必须为零）。
11. 文档串中的课行号与逐字引文只能从本引文包 `02-citations.md` 原样复制；硬证据标 `[课号:行号]`，二级旁证必须显式标 `[二级旁证 课号:行号]`，不得引用编者注或修改引文。
12. 严禁读取对方盲写分支、对方会话、旧 `formal/` 目录或 `.chanlun/definitions/` 目录。
13. 后台任务未结束前不结束回合，必须拿到最终退出码。
14. 盲写期间不推送分支到远端（封存 SHA 后才揭示）；交卷末行按格式回报 `RESULT: 分支，head SHA，构建命令与退出码，门禁结果，未解决项`。
