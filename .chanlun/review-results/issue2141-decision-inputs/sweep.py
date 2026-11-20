#!/usr/bin/env python3
"""只读取本任务固定 Git 对象与公开 tracker；在输入材料目录留取证原件。"""
import csv
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

OUT = Path(__file__).resolve().parent
HITS = OUT / "hits"
BASE = "ba74fd6344df5d03d3a8c5b6a5a2c9d8bef7a8b6"
REPO = "Newchanlun/NewChanlun"
FIELDS = "number,title,state,url"
QUERIES = {
    "Q1": ["端点相连", "关节极值", '"方向极值" 中枢', '"回抽" "端点"'],
    "Q2": ["退场条件", '"离开段" "回抽段"', '"越出后返回"', '"续扫锚" 中枢', 'C@u29'],
    "Q3": ['"占位方向"', '"方向占位" 中枢', '"非语义方向" 三类', '"首回试" 次级别'],
    "Q4": ['"Zn" "外缘"', '"内部非" "端点"', '"非 Zn" "末成员"'],
}
REPO_QUERIES = {
    "Q1": r"端点相连|关节极值|方向极值|端点不相连|JointNotConnected|DirAlternates",
    "Q2": r"退场条件②|离开段.{0,16}回抽段|越出后返回|首回试|首回抽|last_member\s*\+\s*2|refSeg4Break|BreakUnitOutward|C@u29|tb1424-prep-r2|续扫锚",
    "Q3": r"占位方向|方向.{0,5}占位|外缘占位|非语义方向|技术突破方向|center_own_dir_at|leave_anchor",
    "Q4": r"相邻.{0,4}Zn.{0,7}(端点|覆盖)|非.{0,3}Zn.{0,8}(极值|远端|成员)|Zn.{0,14}(聚合|外缘)|zn_extrema|extendWeak_nonZn_member",
}
BLOG_CONCEPTS = {
    "legs": r"离开.{0,14}(中枢|区间)|中枢.{0,12}(离开|脱离)|离开.{0,36}(回抽|回试|回拉|回跌|回调)|回抽.{0,22}(中枢|低点|高点)|回试.{0,22}(中枢|低点|高点)|回拉.{0,22}(中枢|低点|高点)",
    "nonreturn": r"(不[能再]?回(到|去|落|跌)|不重新回到|不重回|不(再)?触及|不返回|不(跌|升)破[ Zz]*(ZG|ZD|中枢)|跌不回|升不回).{0,18}(中枢|区间|三类|[Zz][GgDd])|中枢.{0,24}(不回|不重回|不[能再]?回来|不重新回到|不触及|破坏)",
    "t3": r"(第三类|三类买卖|三买|三卖|三买卖).{0,24}(定理|回抽|回试|回拉|低点|高点|破坏|完成|完结|结束|延伸)|(完成|完结|结束|延伸|破坏|回抽|回试|回拉|低点|高点).{0,25}(第三类|三买|三卖)|第三类买卖点定理",
    "ends": r"(线段|笔|走势类型|反弹|回试|回抽).{0,18}(端点|关节|连接点|起点|结束点|分界点|终点|最高点|最低点|高低点)|(端点|结合点|分界点|连接点|起点|终点|最高点|最低点).{0,18}(线段|笔|走势类型)|[a-z][12][=＝][a-z][12]|特征序列.{0,14}(缺口|区间)",
    "extension": r"中[枢樞].{0,14}(延伸|破坏|重叠|不重叠|完成|完结)|(延伸|破坏|完成|完结).{0,10}中枢|[dD]n.{0,30}[gG]n|遍历.{0,12}Zn",
}
SCOPES = [".chanlun/definitions", "docs/adr", "analysis", "docs", "formal", "rust", "CONTEXT.md", ":(exclude)docs/chanlun/text"]
BLOG_PATH = "docs/chanlun/text/blog"
REQUIRED = {18,20,36,37,41,43,44,46,49,51,53,61,86,92,*range(62,72),*range(77,82)}
def collect(name, args, codes=(0,), data=None):
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode not in codes:
        raise RuntimeError(f"{name}: exit {proc.returncode} ({proc.stderr})")
    if data is not None:
        raw = json.loads(proc.stdout)
        if len(raw) >= 1000:
            raise RuntimeError(f"{name}: GitHub 搜索上限")
        body = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    else:
        body = "\n".join(line.rstrip(" \t") for line in proc.stdout.splitlines()) + ("\n" if proc.stdout else "")
    (HITS / name).write_text(body)
    return name, shlex.join(args), proc.returncode, len(raw) if data is not None else len(body.splitlines())

def sweep():
    specs = []
    for q, terms in QUERIES.items():
        for j, term in enumerate(terms, 1):
            specs.append((f"tracker-{q}-{j}.json", ["gh","issue","list","-R",REPO,"--state","all","--limit","1000","--search",term,"--json",FIELDS], (0,), True))
    for q, term in REPO_QUERIES.items():
        specs.append((f"repo-{q}.txt", ["git","grep","-nI","-E",term,BASE,"--",*SCOPES], (0,1), None))
    for q, term in BLOG_CONCEPTS.items():
        specs.append((f"blog-{q}.txt", ["git","grep","-nI","-E",term,BASE,"--",BLOG_PATH], (0,1), None))
    with ThreadPoolExecutor(max_workers=6) as pool:
        ledger = list(pool.map(lambda args: collect(*args), specs))
    with (OUT / "queries.tsv").open("w") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("结果", "命令", "退出码", "命中数"))
        writer.writerows(ledger)

def read_matches(paths):
    found = {}
    for path in paths:
        for row in path.read_text().splitlines():
            _,file,no,body = row.split(":", 3)
            course = re.search(r"/(\d{3})-", file)
            if not course:
                continue
            number = int(course[1])
            file = f"{BLOG_PATH}/{number:03d}-第{number}课.md" if number else f"{BLOG_PATH}/000-序篇.md"
            found.setdefault(file, {})[int(no)] = body
    return found

def contexts(mode):
    found = read_matches(HITS.glob("blog-*.txt"))
    for file, rows in sorted(found.items()):
        no = int(Path(file).name[:3])
        if mode == "required" and no not in REQUIRED or mode == "extra" and no in REQUIRED:
            continue
        lines = subprocess.check_output(["git","show",f"{BASE}:{file}"], text=True).splitlines()
        keep = sorted({j for n in rows for j in range(max(n-2,1), min(n+2,len(lines))+1)})
        print(f"\n## {file}｜{len(rows)} 命中｜{len(keep)} 行上下文")
        prev = -1
        for n in keep:
            if n > prev + 1:
                print("…")
            print(f"{n:4d}{'*' if n in rows else ' '}: {lines[n-1]}")
            prev = n

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sweep()
    elif sys.argv[1] == "normalize":
        for path in [OUT/"queries.tsv", *HITS.glob("*.txt")]:
            lines = path.read_text().splitlines()
            path.write_text("\n".join(line.rstrip(" \t") for line in lines) + ("\n" if lines else ""))
    else:
        contexts(sys.argv[1])
