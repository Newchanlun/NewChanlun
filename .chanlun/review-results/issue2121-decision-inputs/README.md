# #2121 送审输入

从 [起草七节](draft.md) 开始；[精确编辑](canonical-edit.json) 与 [base／原件／结果／差异](canonical-plan.json) 一一对应。送审分支是 `decision/2121`，本输入分支不含正本或 Rust 变更。

- [分级](classify.json)：P，`user_gate=[]`。普通研发方法与真实准入阈值授权分离。
- [考古](archaeology.md)：#907 的实际点统计和聚簇，已裁／先例／新缺口；可重跑的 [命令](search/commands.tsv)、[命中计数](search/counts.tsv)、[逐票处置](search/tracker-disposition.tsv)、[逐行处置](search/repo-disposition.tsv)、[评论定位](search/comment-index.tsv) 均在包内。T、R、B、E 的原始结果按查询 ID 跟在同目录。
- [候选取舍及未决](candidates.md)：逐参数的新裁理由、保留的可选研究与授权边界。
- [手算](example.md)、[Python oracle](verify_example.py)、[实跑输出](example-output.txt)：可在本目录用 `python3 verify_example.py` 核对。不代表 #1441 的产品验收。

这是起草候选；没有本票非作者独审结论，不变更票面、授权或依赖边。
