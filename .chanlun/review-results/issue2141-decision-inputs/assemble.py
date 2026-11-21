#!/usr/bin/env python3
"""把已取证的命令和作者裁定拼成宿主可读的输入，不调用裁决或独审。"""
import csv
import json
from pathlib import Path
import re
import shlex
import sys

OUT = Path(__file__).resolve().parent
questions = [
    ("Q1","关节极值不等但回抽在外是否已证",
     [(".chanlun/definitions/qushi.md:244","已裁相连交替分支"),
      ("docs/chanlun/text/blog/078-第78课.md:42,58–60","真实分界与标准化相接的权威及边界"),
      ("docs/chanlun/text/blog/081-第81课.md:504–508","端点不能覆盖途中穿回")],
     "保持 #2114，裸失配投影不证角色；独立角色桥尚未定。",
     "本地独立极值投影与原文讨论的首尾相连折线不是同一量。",
     ["端点相连","关节极值","JointNotConnected"]),
    ("Q2","首个不重叠段确为离开的成员、连接、续扫与外缘",
     [("https://github.com/Newchanlun/NewChanlun/issues/1478#issuecomment-6149640661","两个端点/外缘裁定"),
      (".chanlun/definitions/zhongshu.md §4.1/§4.4–4.7/§6.1","条件②、九段升级优先和 Z-5"),
      ("docs/chanlun/text/blog/020-第20课.md:30,52,56,60,62","相邻触及、Zn 和首次回抽"),
      ("https://github.com/Newchanlun/NewChanlun/issues/1424#issuecomment-6160553615","报告 C@u29；原件缺失")],
     "待 R，有证后返回或破坏；非 Zn 离开后返回，接纳后不足 9 从 j+2 续验母窗，达到 9 交 #1429 按 S-4/Z-4 重切。区间外 Zn 已返回的成员组织仍未决；不回才走 Z-5。",
     "旧扫描单哨兵当结算；不加条件从 j+2 续验会越过九段门；强纳外侧 Zn 则违反中心定理一。",
     ["退场条件②","离开段 回抽段","续扫锚","C@u29"]),
    ("Q3","占位方向能否作离开或回抽",
     [("docs/chanlun/text/blog/018-第18课.md:64–66","盘整可能当一腿"),
      ("rust/src/theta_v0/classifier/recursive_tower.rs:794–824@4402c64d","ownership 及外缘占位来源"),
      ("https://github.com/Newchanlun/NewChanlun/issues/1429#issuecomment-7000557985","上级组合材料方向非默认 Up")],
     "占位不充角色；已完成且真实角色有独立源证者仍可参与。",
     "同一枚举把趋势来源与占位压扁。",
     ["占位方向","非语义方向","leave_anchor"]),
    ("Q4","限定内部非 Zn 极值覆盖",
     [("docs/chanlun/text/blog/020-第20课.md:52,54","只遍历 Zn"),
      (".chanlun/definitions/zhongshu.md:232,360","旧证明泛出适用域"),
      ("s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json@4402c64d","内部 u1.lo 小于两个邻 Zn 的 lo")],
     "只限定覆盖推导，合法 Zn 聚合不变。",
     "真实 L0 前缀已反证内部极值总由两边覆盖。",
     ["Zn 外缘","相邻 Zn 覆盖","zn_extrema"]),
]

def run():
    ledger = list(csv.DictReader((OUT/"queries.tsv").open(), delimiter="\t"))
    points = []
    for point,question,hits,recommended,conflict,keywords in questions:
        queries = []
        for row in ledger:
            name = row["结果"]
            if point not in name or not name.startswith(("tracker-","repo-")):
                continue
            cmd = row["命令"]
            args = shlex.split(cmd)
            tracker = name.startswith("tracker-")
            queries.append({"channel":"tracker" if tracker else "repo",
                            "query":args[args.index("--search")+1] if tracker else args[args.index("-E")+1],
                            "command":cmd,"hits":int(row["命中数"])})
        assert {q["channel"] for q in queries} == {"tracker","repo"}
        assert all("--state all" in q["command"] for q in queries if q["channel"] == "tracker")
        points.append({"id":point,"question":question,"class":"C","queries":queries,
                       "hits":[{"source":a,"excerpt":b} for a,b in hits],
                       "citation":hits[0][0],"reasoning":conflict,"recommended":recommended,
                       "searched_keywords":keywords,"gap":"decision","conflict":conflict})
    (OUT/"archaeology.json").write_text(json.dumps({"points":points},ensure_ascii=False,indent=2)+"\n")

    draft_path = OUT/"draft.md"
    prose = Path(sys.argv[1]).read_text() if len(sys.argv) == 2 else draft_path.read_text().split("\n\n```canonical_edit\n", 1)[0]
    headings = ["问题","权威依据","候选","裁定","验收清单","受影响票与 blocking 边变化","授权引用","引用自证","考古对照"]
    assert re.findall(r"^## (.+)$",prose,re.M) == headings
    assert sum(x.startswith("正本落点：") for x in prose.splitlines()) == 1
    table = prose.split("## 考古对照")[1]
    assert set(re.findall(r"^\| (Q\d+) ",table,re.M)) == {x[0] for x in questions}
    contract = (OUT/"canonical_edit.json").read_text().strip()
    assert not re.search(r"^\x60{3}canonical_edit",prose,re.M)
    draft = prose.rstrip()+"\n\n\x60\x60\x60canonical_edit\n"+contract+"\n\x60\x60\x60\n"
    draft_path.write_text(draft)
    print("四个考古点均有 tracker + 仓内查询；起草七节、两表及一个 canonical_edit")

if __name__ == "__main__":
    run()
