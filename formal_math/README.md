# 独立纯数学包

从仓库根目录加载环境、取预编译缓存，再构建和跑门禁：

```sh
source scripts/fm_env.sh
(cd formal_math && lake exe cache get && lake build --wfail)
python3 formal_math/verification/run_gates.py --repo-root .
python3 formal_math/verification/selftest.py
```

需要单查一门时加 `--gate 3`。当前有 13 道门：1、2、3、6a、6b、7a、7b、S、8a、8b、9、10、15。`--stage decl` 跑共用门及 7a、S、8a、10；`--stage proof` 跑共用门及 7b、8b；默认 `all` 全跑。路径门禁读取当前 Git 差异；CI 分离 HEAD 时由 `GITHUB_HEAD_REF` 提供 PR 分支名。

- `Chan/` 是主库，现有 `Chan/Smoke.lean` 检查工具链与 Mathlib 名称。后续可信定义在 `Chan/Defs/`，命名假设在 `Chan/Hypotheses/`；定理、证明、审计和可执行纯函数分别进 `Thm/`、`Proofs/`、`Audit/`、`Exec/`。
- `ChanTest/` 是随全包构建的见证与反例库。小判例用 `decide`，不借助原生执行证明。研究库、陈述镜像和可运行小模型分别预留给 `ChanDyn/`、`ChanChallenge/` 和 `ChanExplore/`。
- `formalization.yaml` 登记原文断言与 Lean 声明，`HISTORY.md` 记录修订和理由，`statement-lock.json` 预留给声明锁门禁。
- [verification/](verification/README.md) 存放门禁、钉选和自测夹具。红夹具故意含禁用构造，不编入任何 Lean 库。
