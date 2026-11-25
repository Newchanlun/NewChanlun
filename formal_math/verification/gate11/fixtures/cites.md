# 引文报告自测夹具

每行一个样例，行末注释：`case:` 样例名（对应独审报告里的模式名），`expect:` 该行各引文按次序应得的 `status`，
`ids:` 第一条引文命中的 id 集合，`outside:1` 表示读数里应注明该行另有区间外出现，`unparsed:` 该行应出现一条未解析标记且原因含该子串。

样例取自语料原文与准入表现状；本文件在 gate11/fixtures/ 下，真实扫描会排除它。

- 【缠师 000:26】「而市场的波动，归根结底是在前后两个高低点关系构成的一个完全分类中展开的，明白了这一点，市场就如同自己的掌纹一样举手可见了。」 <!--case:ok-full expect:ok ids:1-->
- 【缠师 000:26】「归根结底是在前后两个高低点关系构成的一个完全分类中展开的」 <!--case:ok-substring expect:ok ids:1-->
- 【原文 000:26】「明白了这一点，市场就如同自己的掌纹一样举手可见了。」 <!--case:ok-attr-yuanwen expect:ok ids:1-->
- 【缠师 011:26】「湿吻。把短期均线」 <!--case:bridge expect:spans_multiple_ids ids:-->
- 【缠师 011:16】「技术分」 <!--case:single-id expect:ok ids:13-->
- 【缠师 000:26】「，归根」 <!--case:repeat-in-out expect:ok ids:1 outside:1-->
- 【缠师 017:40】「“一分为二”」 <!--case:excluded17 expect:quote_overlaps_excluded_text-->
- 【缠师 017:40】「像有些半吊子哲学胡诌什么“一分为二”」 <!--case:excluded17-context expect:quote_overlaps_excluded_text-->
- 【缠师 046:28】「三、没有中枢」 <!--case:excluded46 expect:quote_overlaps_excluded_text-->
- 【缠师 054:60】「*」 <!--case:excluded54 expect:quote_overlaps_excluded_text-->
- 【缠师 081:42】「而走势是所有人贪嗔痴疑的合力结果，反映在走势中，就使得走势显示出自相似性。」 <!--case:splice expect:quote_spliced_across_spans-->
- 【缠师 081:42】「显示出自相似性。」 <!--case:splice-also-outside expect:quote_overlaps_excluded_text-->
- 【缠师 081:42】「(后文改称自同构性结构）」 <!--case:excluded-note-itself expect:quote_overlaps_excluded_text-->
- 【缠师 081:42】「显示出自相似性……。」 <!--case:across-gap expect:elided_unsupported-->
- 【缠师 000:26】「而市场的波动……明白了这一点」 <!--case:elided-ok expect:elided ids:1-->
- 【缠师 000:26】「明白了这一点……而市场的波动」 <!--case:reverse expect:elided_unsupported-->
- 【缠师 000:26】「而市场的波动……而市场的波动」 <!--case:duplicate expect:elided_unsupported-->
- 【缠师 000:26】「而市场的波动……」 <!--case:missing-ellipsis expect:elided ids:1-->
- 【缠师 014:44】「析如下： 在周线2」 <!--case:nbsp-original expect:ok ids:46-->
- 【缠师 014:44】「析如下： 在周线2」 <!--case:ascii-space expect:whitespace_differs ids:46-->
- 【缠师 014:44】「析如下：　在周线2」 <!--case:ideographic-space expect:whitespace_differs ids:46-->
- 【缠师 000:26】「而市场的波动,」 <!--case:halfwidth-punct expect:quote_not_in_line-->
- 【缠师 017:1】「不在表内」 <!--case:table-miss expect:lesson_line_not_in_table-->
- 【缠师 000:26】「这句话并不在那一行里」 <!--case:not-in-line expect:quote_not_in_line-->
- 【缠师 000:26】「而市场的波动」与【缠师 054:60】「*」 <!--case:two expect:ok,quote_overlaps_excluded_text-->
- 【网友 000:26】「而市场的波动」 <!--case:other-speaker expect:attribution_not_accepted-->
- 【正文 000:26】「而市场的波动」 <!--case:region-label expect:attribution_not_accepted-->
- 【缠师 1011:26】「湿吻」 <!--case:four-digit unparsed:课号不是三位-->
- 【缠师 11:26】「湿吻」 <!--case:two-digit unparsed:课号不是三位-->
- 【缠师 011：26】「湿吻」 <!--case:wide-colon unparsed:全角-->
- 【缠师011:26】「湿吻」 <!--case:no-separator unparsed:无分隔-->
- 【缠师 011:26、27】「湿吻」 <!--case:multi-number unparsed:多行号-->
- 【缠师 011:26】「湿「吻」」 <!--case:nested unparsed:同行的「…」-->
- 【缠师 011:26】『湿吻』 <!--case:alternate-bracket unparsed:同行的「…」-->
- 【缠师 011:26】「湿 <!--case:cross-line unparsed:同行的「…」-->
吻」续行，不含标记
