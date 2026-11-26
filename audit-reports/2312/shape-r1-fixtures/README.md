# #2312 第四片独审 r1 的夹具与脚本

被审提交 `1acb400d631e6d4154a3ef4ebb779f7a781e2425`。全部只读审阅，没有改被审分支上的任何文件。

## 布局

| 位置 | 内容 |
|---|---|
| `tools/shp.py` | 对一个目录（当作 `formal_math` 根）直接跑 `fm_audit shape-plan` 与 `fm_audit shape`，按库导入集合分组，每组一个 `bwrap` 只读沙箱进程。只测第 5 步，不跑流水线 |
| `tools/cmp.py` | 跑 `shp.py` 并与同目录 `EXPECT.tsv` 比对（`GREEN` 须零命中；红码集合须被实际红码覆盖） |
| `tools/gen.py`、`cases/cases_*.py` | 生成式夹具：`cases_a.py` 185 个禁用清单变体、`cases_b.py` 311 个五张白名单与 `set_option`／`#guard_msgs`／`Chan/Defs` 变体、`cases_c.py` 41 个配置项与未点名写法探针。用 `python3 tools/gen.py cases/cases_a.py` 重新落盘到 `fx/<批名>/` |
| `expect/*.tsv` | 上面三批的期望表（逐文件一行），与 `gen.py` 落盘的内容一致 |
| `tools/sweep.py` | 对仓内 `must_green/`、`must_red/` 夹具目录批量只跑第 5 步 |
| `tools/redcheck.py` | 对 `runner/fixtures.tsv` 里归「本片判红」的 74 行逐行跑第 5 步并与第 5 列红码比对 |
| `tools/pipe.py` | 把一个叠加层目录经 `runner/run.py` 跑完整七步（复用 `runner/selftest.py` 的 `Suite`、`template`、驱动脚本；`--skip-shape` 走自测驱动的第 5 步旁路） |
| `tools/Kinds.lean` | 打印各战术 `(config := …)` 写法的语法种类，甲-1 的判据来源 |
| `fx/` | 手写夹具，逐个见下 |
| `packages-before.txt`、`packages-after.txt` | 共享依赖目录开工与收工的顶层列表与修改时间，`diff` 为空 |

## 手写夹具

| 目录 | 用途 | 实测 |
|---|---|---|
| `fx/a1-aesop-green` | 甲-1：点名禁用的旧式 `(config := …)` 以明文出现 | 七步全绿（rc=0） |
| `fx/a1-aesop-eval` | 甲-1：同一写法的取值带 `dbgTrace` 标记 | 七步全绿，构建日志出现 `info: …: FM-LEGACY-CONFIG-RAN` |
| `fx/a1-plausible` | 甲-1：`plausible (config := …)` | 第 5 步零命中（第 6 步因 plausible 自身判红） |
| `fx/g-green` | 日常 Lean／Mathlib 语料（5 个文件 65 条命令：结构、归纳、类、实例、各种 `deriving`、良基与互递归、`calc`／`conv`／`rcases`／`obtain`／`linarith`／`positivity`／`norm_num`／`ring`、`Finset`／`List` 记号、`open scoped`、`«»` 标识符、`#guard_msgs`） | 第 5 步零命中、第 6 步构建绿；第 7 步只剩 `LOCK_UNLISTED`（夹具不带锁文件）与 `ENV_META`（见 N1） |
| `fx/y-auto` | N1 最小化：`structure` 字段的 autoParam 默认证明 `:= by omega` | 1–6 步全绿，第 7 步 `ENV_META`（`Win.ok._autoParam`） |
| `fx/x-expose` | `SHAPE_EXPOSE`「谁接」核实：空的 `@[expose] public section end` 加节外 `public def` | 第 5 步绿，第 7 步门 15 `EXPOSE_SECTION` 接住 |
| `fx/e-eval1` | 清单外求值入口探针（Aesop／核心配置项取值带纯代码标记） | 第 5 步零命中；`E3`（Aesop 旧式 config）的标记出现在构建日志 |
| `fx/e-eval2`、`fx/e-eval3`、`fx/e-eval4` | Aesop 规则战术按名字求值这条入口是否可从被审源码触达。写入目标只落第 6 步沙箱内可写的 `.lake` | `e-eval2`／`e-eval4` 构建期报 `may not access declaration … imported as meta`；`e-eval3` 按编译器建议补 `import Lean.CoreM` 后第 4 步 `IMPORT_PINNED` |
| `fx/e-eval5` | 新式配置项（键不是 `native`／`config`，按设计放行）的取值能否求值 | 第 6 步报 `Could not evaluate the expression`，没有求值能力 |
| `fx/z-prop1`、`fx/z-prop2` | `shape-plan` 的模块制分组与真实构建是否一致：上游 `public import` 传下来 vs 不传 | `z-prop1` 七步全绿；`z-prop2` 第 5 步 `SHAPE_PARSE unknown tactic`，跳过第 5 步时真实构建在同一行同一列报同一句 `unknown tactic` |
| `fx/w-where` | 解析模型保真：`where aux : T := by` 换行后缩进不足 | 第 5 步 `SHAPE_PARSE unexpected identifier; expected command`，真实 `lean` 在同一位置报同一句 |

## 复现

```sh
source scripts/fm_env.sh
# 第 5 步单测（夹具目录当作 formal_math 根）
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 tools/cmp.py fx/<批名>
# 完整七步
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 -I tools/pipe.py fx/<目录>
# fixtures.tsv 的 74 行
flock /home/workspace/fm/lean.lock /home/workspace/fm/guard.sh python3 tools/redcheck.py
```

`tools/shp.py`、`tools/pipe.py` 里的审计程序路径与依赖目录是本机绝对路径，换机器要改。依赖目录
`/home/workspace/.t3/worktrees/NewChanlun/t3-f01a145b-83fe37a7a2bbcc16/formal_math/.lake/packages`
全程只读使用：`shp.py` 经 `bwrap --ro-bind` 挂载，`pipe.py` 把它交给 `run.py --packages`（第 5、7 步只读挂载，
第 6 步只读挂到 `.lake/packages`）。
