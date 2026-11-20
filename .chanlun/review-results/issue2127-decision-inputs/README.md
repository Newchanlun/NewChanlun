# #2127 决策输入

推荐新写格式不把主机路径写入业务承诺；原件按原版本核验，双跑硬比实际提交根与全状态。

- [七节草稿及唯一正本编辑](draft.md)，配套 [ADR 编辑 JSON](canonical_edit.json) 和 [词条原样编辑 JSON](context-edit.json)。
- [分级](classify.json)、[两路考古](archaeology.md)、[结构化考古](archaeology.json)、[代码与实测事实](CODE-FACTS.md)。
- [方案比较](OPTIONS.md)、[交给主控的实施票](IMPLEMENTATION-DRAFTS.md)、[未决与相邻票边界](UNRESOLVED.md)。

送审提交 [`2a82e458b8d868590f2bd7cf023744f97099f063`](https://github.com/Newchanlun/NewChanlun/commit/2a82e458b8d868590f2bd7cf023744f97099f063)，父提交 `b9d898dccf46c2a716115eaa1215bc39c458a959`。ADR 0038 是唯一 `canonical_edit` 主对象，符合宿主一稿一正本解析；用户要求同步的 `CONTEXT.md` 词条是同一送审 diff 的配套精确编辑，主控须连同 ADR 一起送审。两个编辑对固定父提交分别应用后，与决策分支两份文档逐字匹配；`git diff-tree --check HEAD^ HEAD` 通过。尚无独审和新产品运行结果。
