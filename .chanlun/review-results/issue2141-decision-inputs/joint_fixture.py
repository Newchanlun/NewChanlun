#!/usr/bin/env python3
"""重算冻结的真实 L0 夹具；合成 C 型仅作判别工作例，不代替 BTC 末切面。"""
import json
from subprocess import check_output

REV = "4402c64d1ca78fbab9c3649b000e4c91178f60c0"
PATH = "s_session/tests/fixtures/tb02e-real/btc-tail50k-first600.json"
doc = json.loads(check_output(["git","show",f"{REV}:{PATH}"]))
units = doc["tower_units"]

def draw_ends(u):
    return (u["lo"],u["hi"]) if u["dir"] == "UP" else (u["hi"],u["lo"])

def source_ends(segment):
    data = segment["payload"]["data"]
    refs = {x["stroke_index"]: x for x in data["stroke_refs"]}
    members = data["construction"]["stroke_indices"]
    first, last = (refs[members[i]] for i in [0,-1])
    return int(first["start_price"]), int(last["end_price"])

def inside(x, core):
    return x["lo"] <= core[1] and x["hi"] >= core[0]

def znvals(indices, seq):
    sel = [seq[i] for i in indices]
    return dict(DD=min(x["lo"] for x in sel), D=max(x["lo"] for x in sel),
                G=min(x["hi"] for x in sel), GG=max(x["hi"] for x in sel))

print("价格保留夹具原整数单位，u 下标从 0 开始")
print("u dir start end lo hi source_start source_end")
for i,u in enumerate(units):
    print(i,u["dir"],u["start_index"],u["end_index"],u["lo"],u["hi"],*source_ends(doc["segments"][i]))
core = max(x["lo"] for x in units[:3]), min(x["hi"] for x in units[:3])
print("seed [0,1,2], core",core)
print("prev->cur Kjoint extremum(prev/end,next/start) equal stroke_end/start equal cur_closed_overlap")
joints = []
for i,(a,b) in enumerate(zip(units,units[1:])):
    p,q = draw_ends(a)[1], draw_ends(b)[0]
    sa,sb = source_ends(doc["segments"][i])[1], source_ends(doc["segments"][i+1])[0]
    joints.append((a["end_index"] == b["start_index"],p == q,sa == sb))
    print(f"{i}->{i+1}", joints[-1][0], (p,q), joints[-1][1], (sa,sb), joints[-1][2], inside(b,core))
assert joints == [(True,x,True) for x in [False,True,True,False,True]]
j = next(i for i in range(3,len(units)) if not inside(units[i],core))
members = list(range(j))
zn = [i for i in members if units[i]["dir"] == units[0]["dir"]]
assert j == 5 and units[4]["dir"] == "DOWN" and units[4]["lo"] == units[5]["lo"]
assert units[5]["dir"] == "UP" and units[5]["hi"] < core[0]
assert units[1]["lo"] < min(units[0]["lo"],units[2]["lo"])
print("baseline j, terminal, connector, next:",j,j-1,j,j+1)
print("members",members,"Zn",zn,"Zn metrics",znvals(zn,units),"all-member metrics",znvals(members,units))
print("u1.lo uncovered by adjacent Zn:",units[1]["lo"],units[0]["lo"],units[2]["lo"])
print("u3.hi mismatched but covered:",units[3]["hi"],units[2]["hi"],units[4]["hi"])

def spread(rows):
    return [dict(dir=d,lo=l,hi=h) for d,l,h in rows]
# PZ-Zn 两侧：i=29，D=32，R=33。方向/角色、相邻与完成均为工作例前提；
# j=32 曾是旧位置扫描的 first non-overlap；不拟造历史 C 的真实价格。
seed = [("DOWN",20,40),("UP",20,40),("DOWN",25,35)]
base = spread(seed)
assert znvals([0,2],base) == {"DD":20,"D":25,"G":35,"GG":40}
print("worked C rows in synthetic ticks: core [25,35], prefix metrics",znvals([0,2],base))
for name, side, dep, ret, selected in [
    ("return/non-Zn","UP",("UP",36,50),("DOWN",33,50),[0,2,4]),
    ("touch/non-Zn","UP",("UP",36,50),("DOWN",35,50),[0,2,4]),
    ("no-return/non-Zn","UP",("UP",36,50),("DOWN",37,50),[0,2]),
    ("return/Zn","DOWN",("DOWN",10,24),("UP",10,28),None),
    ("no-return/Zn","DOWN",("DOWN",10,24),("UP",10,24),[0,2]),
]:
    seq = spread(seed + [dep,ret])
    assert not inside(seq[3],(25,35))
    assert inside(seq[4],(25,35)) == ("return/" in name and not name.startswith("no-") or name.startswith("touch"))
    print(name,"D/R bounds",dep,ret,"side",side,"Zn metrics",znvals(selected,seq) if selected else "unresolved (keep prefix)")
