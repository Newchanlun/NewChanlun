"""复用固定 C2 驱动装配真进程；只改 logical-bar 夹具的两个消息读数。仅 Linux，所有写入限于 --out。"""
import os,sys
from pathlib import Path
product=Path(sys.argv.pop(1)).resolve()
arm=sys.argv.pop(1); assert arm in ('valid','expired')
original=product/'rust/tests/c2_formal_entry.py'
sys.path.insert(0,str(original.parent))
source=original.read_text()
def between(a,b):
    assert source.count(a)==1 and source.count(b)==1
    return source[source.index(a):source.index(b)]
pre=source[:source.index('    release = ewire(')]
old='messages["ReleaseExact-alpha"] = "2"'
assert pre.count(old)==1
pre=pre.replace(old,'messages["ReleaseExact-alpha"] = "100000"\nmessages["ReleaseExact-alpha-expired"] = "100001"')
body='''
    assert data["policy"]["valid_through_ns"] == "100000"
    pre_view = ewire("E","probe-before",dict(op="ReadView",cut=None,as_known_ns=None),"EconomicView")
    prefix = {d:business_dump(Path(n["db"])) for d,n in nodes.items()}
    write("prefix.json",prefix)
    release_payload = dict(op="ReleaseExact", decision_id="alpha", command_id=cid, plan_hash=digest(change),
        certificate=certificate, x_id="X", x_epoch="1", writer_epoch="1")
    key = "ReleaseExact-alpha"+("-expired" if arm=="expired" else "")
    release = ewire("E",key,release_payload)
    current = ewire("E","query-after",dict(op="QueryCommand",command_id=cid,cut=None,as_known_ns=None),"EconomicCommand")
    ending = ewire("E","view-after",dict(op="ReadView",cut=None,as_known_ns=None),"EconomicView")
    liab = pre_view["image"]["finance"]["responsibilities"]
    assert same(liab,ending["image"]["finance"]["responsibilities"]) and [int(i["amount"]) for i in liab] == [20,30,40]
    assert reserve["record"]["retained_total"] == "90" == reserve["record"]["required_total"]
    threshold = int(data["policy"]["valid_through_ns"])
    tick=int(manifest["clock"]["bars"]["messages"][key])
    expected_command = dict(command_id=cid, logical_order_family=x["logical_order_family"], session_id=sid,
        session_generation=gen, x_id="X", x_epoch="1", first_quantity=x["first_quantity"], allocation_id=x["allocation_id"],
        symbol=x["symbol"],projection_kind=freeze["projection_kind"],change=change, plan_hash=digest(change),certificate=certificate,
        certificate_hash=digest(certificate))
    if arm=="valid":
        assert release["kind"]=="ReleasedExactReceipt" and release["commit_ns"]==str(threshold)==str(tick)
        assert current["state"]=="ReleasedExact" and same(current["receipts"],[disp,release])
        assert same(current["record"]["command"],expected_command) and current["record"]["responsibility_ref"]==grants["alpha"]
        assert current["cut"]["commit_seq"]=="6" and same(current["cut"],ending["cut"])
    else:
        assert tick==threshold+1 and release.get("error","").startswith("MissingDependency：共同界/能力证据过期"), release
        assert current["state"]=="Dispatchable" and same(current["receipts"],[disp])
        assert same(ending["cut"],disp["cut"]) and same(current["cut"],disp["cut"])
        assert all(same(prefix[d],business_dump(Path(n["db"]))) for d,n in nodes.items()),"过界写入改变 E/B 业务表"
'''
xsection=between('    model_config = ','    def sign_once(')
tail='''
    aq = dict(op="QueryReleasedExact", protocol="x-exact-authority/1", session_id=sid,session_generation=gen,
        authority_id="E",authority_epoch="1",command_id=cid,command_hash=digest(expected_command),
        command=expected_command,release_receipt_id=None)
    author = ewire("E", "x-authority-"+digest(aq),aq,source=src_x)
    if arm=="valid":
        assert author["state"]=="ReleasedExact" and author["receipt_id"]==release["receipt_key"]
    else:
        assert author["state"]=="NoRecord" and author["receipt_id"]=="NoRecord@5" and author["release_receipt_id"] is None,author
    attempt = xwire("x-first-accept","AcceptExact",expected_command,"Error")
    query=xwire("x-after","QueryCommand",cid,"ExactCommandState")
    assert query["state"]=="NoRecord" and observe()==dict(accepted=0,owned=0,calls=0,s=0)
    assert (("时钟早于 E 持久交付" in attempt["error"]) == (arm=="valid")), attempt
    write("summary.json",dict(arm=arm,policy_bound=threshold,commit_reading=tick,release=release.get("kind"),error=release.get("error"),
      e_command=current["state"],e_cut=current["cut"],economic_receipts=[q["kind"] for q in current["receipts"]],
      responsibilities=[(i["responsibility_id"],i["amount"]) for i in liab],retained="90",x_authority_state=author.get("state"),
      x_authority_error=author.get("error"),x_attempt_error=attempt["error"],x_state=query["state"],x_counts=observe()))
    print((run/"summary.json").read_text())
'''
cleanup=source[source.rindex('\nfinally:\n    for label, p in reversed(processes):'):]
namespace=dict(__file__=str(original),__name__="__main__",arm=arm)
exec(compile(pre+body+xsection+tail+cleanup,str(original)+"-C3-probe","exec"),namespace)
