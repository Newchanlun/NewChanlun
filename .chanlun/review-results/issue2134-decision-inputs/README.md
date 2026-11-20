# #2134 决策输入：X 凭据注入键名

**T 类技术取舍，送独审。** 首选专用命名空间：沿用 `NC_X_VENUE_CREDENTIAL`，允许有界的 ASCII 后缀。它保留已记录的通用配置与凭据哨兵，不让凭据文件驱动 `PATH`、动态加载或其他进程控制。一个合成用例在主线即使含 `=` 也能跑到 serving；收紧依据是身份编码和进程隔离，不是启动偶然失败。

- [起草七节、引用自证、考古对照与 canonical_edit](draft.md)
- [分级与用户硬门](classify.json)；[两路考古与逐条排除](archaeology.md)、[机器可读考古](archaeology.json)
- [主线实测与仓内键名盘点](baseline.md)
- [#2113 收口要求及未决事实](2113-closeout.md)

源基线 `b9d898dccf46c2a716115eaa1215bc39c458a959`，#2113 R4 候选 `bf8e6dfee8e659b5ff84e40786e41db71da292ee`。实际文档候选是 `decision/2134` @ `7701547bb1a70ad2bcc85e8372ea177bf7e4b39a`，与证据分支分别从同一主线派生。原始操作日志和临时构建输入保存在 Mac 内盘 `/Users/silencehan/.t3/evidence/issue2134/`；仓内仅附可复核的搜索账和合成实测记录。
