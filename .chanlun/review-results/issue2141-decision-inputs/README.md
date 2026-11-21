# #2141 起草输入：中枢 R5 的未裁边界

第二版候选 `decision/2141`，父提交 `0f11ebe6952badfcc2ad4a6c67eb542ef07b4385`，先合 [PR #2140](https://github.com/Newchanlun/NewChanlun/pull/2140)。本输入分支从当轮 `origin/main@b9d898dccf46c2a716115eaa1215bc39c458a959` 切出，证据不会进候选正本。分级 P、user_gate 为空；只交作者稿。

**先看 [draft.md](draft.md)**：七节、引用自证、考古对照及唯一 canonical_edit。正本保留 #2114 字面结算；首个不重叠单元若已证本身是离开，必须等已完成首回抽才分返回与破坏，不把只看外侧价格或占位方向当角色。内部非 Zn 的覆盖限定到相连交替输入。返回接纳后先过九段升级门：3+2 续原窗，7+2 交 #1429 重切。未知的真实角色桥及外段是 Zn 又返回时的成员组织留在未决。

| 内容 | 入口 |
|---|---|
| 分级、两路考古与可回查原件 | [classify.json](classify.json)、[archaeology.md](archaeology.md)、[archaeology.json](archaeology.json)、[queries.tsv](queries.tsv)、[逐项处置](hit-dispositions.tsv)、hits/ |
| 成段阅读、补检和未读范围 | [READING.md](READING.md) |
| 固定源码、真实夹具、旧 C 原件缺失与替代 | [FACTS.md](FACTS.md)、[fixture.txt](fixture.txt)、[joint_fixture.py](joint_fixture.py) |
| 五关节及 C 型逐条候选 | [CANDIDATES.md](CANDIDATES.md) |
| 后续实施与历史契约 | [IMPLEMENTATION.md](IMPLEMENTATION.md) |
| 正本精确编辑 | [canonical_edit.json](canonical_edit.json)、[canonical.py](canonical.py) |

复核本版：在候选 checkout 运行 `canonical.py --check`，按实际父提交执行唯一替换并比较候选文件；再以 `git show HEAD:.chanlun/definitions/zhongshu.md` 比较提交内字节。运行 `pytest -p no:cacheprovider tests/test_retired_references.py` 检查引用。夹具输出和 3+2／7+2 工作例见 `fixture.txt`。本版是待独审的作者候选，Rust/Lean 及发布对拍随 #1496。C@u29 的层级和「9 中 2」不能以现有原件核实，保留为旧票转述。
