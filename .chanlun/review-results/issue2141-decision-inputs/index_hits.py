#!/usr/bin/env python3
"""去重展示每项命中的分诊理由；不把标题/单行分诊说成正文考古。"""
from collections import defaultdict
import csv
import json
from pathlib import Path
import re

from sweep import HITS, OUT, read_matches

BOUND = {
    246:"相切是特征序列缺口边界；不处理首回抽角色。",
    290:"旧相切核心修订非本票；回抽相切沿 CC-019。",
    336:"先例为共用 owner，不定义两腿。",
    485:"旧点产出 anchor 归属，未实现 R5 挂起。",
    793:"原文、Lean、生产事实三方权限分工。",
    799:"收敛通则；禁止几何失败后改宽门。",
    804:"同输入跨级同输出。",
    812:"S-3、S-7、Z-5、Z-6 权威。",
    813:"笔段正本历史锚；实际段端使用现行 xianduan。",
    815:"外缘分离与走势类型；不单定首回抽。",
    816:"B-3 首回抽显式。",
    819:"冻结核心与升级；继承。",
    820:"续扫 A/B/C 判例；原文留白依 Lean C。",
    823:"发展情景，区分延伸与扩展。",
    824:"G/D、GG/DD 与核心分工。",
    905:"第一次的证据，不许晚段接管。",
    1014:"#905 独立先例，前件为共享枢轴。",
    1272:"整段 c 内含三类，不定左右成员边界。",
    1296:"Lean refStep/end+2 是在案边界。",
    1340:"CC-017/018/019/022/024、C08。",
    1343:"笔极值根与组锚区分，不等于腿角色。",
    1360:"总表，只登记下游归属。",
    1405:"源 parser 同价边界，旧 C 复核前置。",
    1419:"D-A Zn 方向，L3 旧读数有限，R8 来源。",
    1424:"根裁 5 报 C@u29、同项目替代正控。",
    1426:"CC-024 与 #2114；只消费见证。",
    1429:"后续上级素材、R22，不承担本票角色裁定。",
    1431:"分解读法不回流构造。",
    1432:"力度消费者，不以力度补 R5。",
    1433:"一类/完成消费者，不替回抽判定。",
    1434:"严格同源三类点，端点退场①实测。",
    1437:"多点完成分类消费者，不另判 R5。",
    1443:"组合验收，不增设规则。",
    1478:"外缘与末端角色两条裁定。",
    1490:"分界证明独立于区间标准化；不改线段规则。",
    1493:"V-18 已观测实际段端非段内极值。",
    1496:"首片边界及旧反例转述；后续 owner。",
    1627:"基底值域，无新的两段式裁定。",
    1977:"历史关系修订/输入和旧 C 不同。",
    2073:"重切外缘一致性，归 R22 同源消费。",
    2114:"相连文字分支、版本、首证和未裁范围。",
    2141:"当前票，明确四问。",
}
REPO_GROUPS = [
    ("definitions/zhongshu.md","正本/历史登记；旧句按本票限定，不拿未实装条目作行为证据。"),
    ("definitions/qushi.md","固定 #2114 正文；继承已裁字面分支与版本合同。"),
    ("CONTEXT.md","Zn 词条分工；本票不改词表。"),
    ("definitions/fenjie.md","读法指针与旧行号，不给 R5 腿归属。"),
    ("docs/adr/0011","同级别 S 读法及其验收，与唯一主塔分开。"),
    ("maimai_rules_v1.md","旧说明从 settled 枚举反向腿，预设本票待证的问题。"),
    ("Origin/CenterComplete","Lean seed 的交替及共同核心，不是 R5 角色。"),
    ("Origin/CenterConstruction","Lean seed 价区间及归并公式，非 R5。"),
    ("Origin/CenterConstruct","旧单哨兵参考、聚合与续扫；旧定理不是新两段行为。"),
    ("Origin/UnifiedScanMirrorBridge","固定镜像 seed 交替的证明，不决定失配回抽。"),
    ("Formal/DivergenceNesting","下钻力度/方向合格性，不是结算。"),
    ("recursive_tower.rs","源码/测试刻画旧扫描及上级投影，代码不是教义授权。"),
    ("pipeline.rs","代码事实：线段投影或传递方向与锚；不独证 R5。"),
    ("signal","现有三类或趋势 c 的消费者/测试，旧证书不授权几何兜底。"),
    ("classifier/center.rs","现有 Zn、seed 与几何谓词；分开值与角色。"),
    ("classifier/decompose","走势块方向来源，区分趋势与盘整。"),
    ("classifier/diag","诊断读数不进准入。"),
    ("lean_mirror","投影镜像代码不裁定义。"),
    ("classifier/scan","扫描变量或对拍的实现边界，不做语义来源。"),
    ("/parser/","线段/特征终结规则或几何类型说明，不裁中枢结算。"),
    ("/tests/","代码测试锚，限所涉输入，不能扩判。"),
    ("/bin/","诊断或输出镜像，不进判据。"),
]
TITLE = [
    (r"外缘|中枢|三类|回抽|线段|极值|两段","相邻结构议题；标题对象/verdict 不足以断言新增 R5 归属，作为近邻而非已裁。"),
    (r"背驰|区间套|力度|MACD|[Xx][Zz][Dd]|BSP|买卖点|证书","点、下钻、力度或候选对象，不是本枢 D/R 的成员和续扫。"),
    (r"资金|财务|账本|成交|仓位|筹码|经营|量档|责任|撤单|成本|场所|cap|资金|退出","资金/经营/订单/账本合同的退场，无权决 R5 结构。"),
    (r"CI|Code|会话|部署|Wayfinder|Sandcastle|回放|快照|恢复|缓存|写者|流程|运行|环境","基础设施或历史载体；不构成离开/回抽的判据。"),
]
BLOG = [
    (r"娇注|娇加|（注:|（注：|\(注：|（备注：","含编注，不能整行引作作者；取舍见阅读表。"),
    (r"请问|请教|谢谢|不明白|网友提问","有读者问题，须以署名应答上下文核归属；不以该行独证。"),
    (r"MACD|利润|买入|卖出|操作|仓位","有操作／力度语境，本行不能取代可证的首回抽构造。"),
    (r"特征序列|分型|线段|笔","构件或定位语境，不以单行建立 R5；相关段见阅读表。"),
    (r"三买|三卖|第三类|三类|破坏|不回","三类／波动应用用语，保留为复查线索；不以单条索引推码级归属。"),
    (r"扩展|扩张|重叠|延伸","发展/重叠语境，未单凭该行扩 R5。"),
]

def by_title(title):
    return next((msg for pattern,msg in TITLE if re.search(pattern,title)),
                "该标题讨论其他票的归口或执行对象；不作为本票权威；未逐条拉正文。")

def run():
    rows = []
    trackers = {}
    paths = defaultdict(set)
    for file in sorted(HITS.glob("tracker-*.json")):
        for item in json.loads(file.read_text()):
            trackers[item["number"]] = item
            paths[item["number"]].add(file.stem)
    for n,item in sorted(trackers.items()):
        rows.append(("tracker",";".join(sorted(paths[n])),str(n),item["state"],
                     item["title"],BOUND.get(n, by_title(item["title"]))))
    for file in sorted(HITS.glob("repo-*.txt")):
        for row in file.read_text().splitlines():
            _,path,no,body = row.split(":",3)
            reason = next((note for part,note in REPO_GROUPS if part in path),
                          "同词的实现/辅助入口；不是本票权威，保留原行供复查。")
            rows.append(("repo",file.stem,path+":"+no,"",body[:140].strip(),reason))
    direct = {18:{64,66},20:{30,52,54,56,60,62},24:{158,160},28:{770},29:{362},
              30:{150},36:{169},41:{319},46:{152},49:{62,138},61:{44},69:{208,302},
              71:{34,38,40},78:{42,58,60},81:{504,508},86:{66,70},92:{16,26}}
    for file, matches in sorted(read_matches(HITS.glob("blog-*.txt")).items()):
        course = int(Path(file).name[:3])
        for no,body in sorted(matches.items()):
            if no in direct.get(course,set()):
                reason = "承重或反向样例。作者与限定按 READING.md 成段核。"
            else:
                reason = next((note for pattern,note in BLOG if re.search(pattern,body)),
                              "同词语境或图文转述；保留原行供复查，未据该行下规则。")
            rows.append(("blog","五词族并集",f"{course:03}:{no}","",body[:112].strip(),reason))
    with (OUT / "hit-dispositions.tsv").open("w") as handle:
        writer = csv.writer(handle,delimiter="\t",lineterminator="\n")
        writer.writerow(("路","查询","对象","状态","摘录","逐项分诊"))
        writer.writerows(rows)
    print("tracker unique",len(trackers),"repo/ blog dispositions",len(rows)-len(trackers))

if __name__ == "__main__":
    run()
